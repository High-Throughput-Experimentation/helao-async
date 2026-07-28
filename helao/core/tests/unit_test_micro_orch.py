"""Unit tests for :class:`helao.core.runners.micro_orch.MicroOrch`.

Exercises the small surface that ``MicroOrch`` exposes on top of the
RPC client cache:

* :func:`_is_terminal` — the helper that classifies an action's
  ``action_status`` list as still-active or finished.
* :meth:`MicroOrch.start` / :meth:`stop` lifecycle, including the
  no-op behaviour when called outside an ``async with`` block.
* :meth:`run_action` end-to-end: spins up a fake action server (a
  :class:`RPCDispatcher` on an ephemeral localhost port) that returns
  a finished action dump directly, and verifies the run resolves.
* :meth:`latest` / :meth:`pending_uuids` introspection helpers behave
  as documented around a dispatched action.
"""

__all__ = ["micro_orch_unit_test"]

import asyncio
import random
import socket
import traceback
from copy import deepcopy
from typing import Any, Dict

from helao.core.models.hlostatus import HloStatus
from helao.core.models.machine import MachineModel
from helao.core.models.run_dir import RunDir
from helao.core.rpc import RPCDispatcher, derive_rpc_port
from helao.core.runners.micro_orch import MicroOrch, _is_terminal
from helao.helpers.premodels import Action
from helao.core.tests._test_utils import TestReporter

import os
import tempfile
import shutil
import zipfile
from datetime import datetime as _dt
from helao.helpers.premodels import Experiment, Sequence
from helao.helpers.yml_tools import yml_dumps as _yml_dumps


def _make_orch(root: str, world_servers: dict = None) -> MicroOrch:
    """Build a MicroOrch with a filesystem root but without starting it."""
    return MicroOrch(
        server_key="micro",
        host="127.0.0.1",
        port=_free_port(),
        world_cfg={"root": root, "servers": world_servers or {}},
        default_timeout=3.0,
        finished_timeout=5.0,
        poll_interval=0.05,
    )


def _build_experiment(name: str = "exp_demo") -> Experiment:
    """A minimal Experiment with a manual sequence context, fully stamped."""
    exp = Experiment(experiment_name=name)
    exp.manual_action = True
    exp.access = "manual"
    exp.sequence_name = f"seq--{name}"
    exp.sequence_label = "manual"
    exp.init_seq(time_offset=0)
    exp.init_exp(time_offset=0)
    return exp


#: Low TCP window to draw test ports from. Kept well below ``65535 -
#: RPC_PORT_OFFSET`` so the derived RPC port never overflows, and below the
#: Windows dynamic range (49152-65535) so it does not fight OS ephemeral ports.
_PORT_WINDOW = (20000, 40000)


def _port_pair_free(port: int) -> bool:
    """True if both ``port`` and its derived RPC port bind cleanly right now."""
    rpc_port = derive_rpc_port(port)
    if rpc_port > 65535:
        return False
    try:
        with (
            socket.socket(socket.AF_INET, socket.SOCK_STREAM) as http_s,
            socket.socket(socket.AF_INET, socket.SOCK_STREAM) as rpc_s,
        ):
            http_s.bind(("127.0.0.1", port))
            rpc_s.bind(("127.0.0.1", rpc_port))
        return True
    except OSError:
        return False


def _free_port() -> int:
    """Return a free TCP port whose derived RPC port is also free.

    Binding an OS ephemeral port (``bind(..., 0)``) is unreliable here: the RPC
    dispatcher binds ``port + RPC_PORT_OFFSET`` (10000), and on Windows the
    dynamic port range is 49152-65535, so the kernel routinely hands back ports
    above 55535 whose offset overflows past 65535 — every retry fails. Instead
    scan a fixed low window and return the first port where BOTH the HTTP port
    and its RPC port bind, so coexisting fake servers never collide on the
    offset port. A randomized start spreads back-to-back calls to dodge
    ``TIME_WAIT`` reuse races.
    """
    lo, hi = _PORT_WINDOW
    start = random.randint(lo, hi - 1)
    span = hi - lo
    for i in range(span):
        port = lo + (start - lo + i) % span
        if _port_pair_free(port):
            return port
    raise RuntimeError("could not obtain a free HTTP/RPC port pair for the test")


class _FakeActionServer:
    """Stand-in action server that exposes a single action over RPC.

    The action immediately reports as finished by including
    ``HloStatus.finished`` in the response's ``action_status`` list, so
    :meth:`MicroOrch.run_action` can complete synchronously off the
    dispatch reply without needing an ``update_status`` callback.
    """

    def __init__(self, server_key: str, action_name: str):
        """Bind the server identity and create an empty dispatcher."""
        self.server_key = server_key
        self.action_name = action_name
        self.dispatcher = RPCDispatcher(server_key)
        self.attach_calls = 0
        self.action_calls: list = []
        self.dispatcher.register(f"{server_key}/{action_name}", self._run_action)
        self.dispatcher.register("attach_client", self._attach_client)
        self.dispatcher.register("detach_client", self._detach_client)

    async def _attach_client(
        self,
        client_servkey: str,
        client_host: str,
        client_port: int,
    ) -> bool:
        """Record that ``client`` subscribed to status updates."""
        self.attach_calls += 1
        return True

    async def _detach_client(
        self,
        client_servkey: str,
        client_host: str,
        client_port: int,
    ) -> bool:
        """Record the detach call from the client (no-op locally)."""
        return True

    async def _run_action(self, action: dict = None, **kwargs) -> Dict[str, Any]:
        """Return a finished action dump that includes the requested name.

        ``action`` is declared explicitly so the RPC ``_coerce_args`` pass
        binds the inbound dict to it; the ``**kwargs`` catches any extra
        params the dispatcher merges in.
        """
        action_dict = action or {}
        self.action_calls.append(deepcopy(action_dict))
        # Reply with a terminal status -> MicroOrch.run_action returns
        # directly off this dump, no waiting on a status callback.
        action_dict["action_status"] = [HloStatus.finished.value]
        return action_dict


class _FakeDataActionServer:
    """Fake action server that writes a finished act.yml + .hlo to disk.

    Mirrors what a real action server does on finish: writes its action meta
    yml and one HLO data file into ``<root>/<state>/<action_output_dir>/`` and
    returns a terminal dump (so MicroOrch resolves off the reply).
    """

    def __init__(self, server_key: str, action_name: str, root: str):
        self.server_key = server_key
        self.action_name = action_name
        self.root = root
        self.dispatcher = RPCDispatcher(server_key)
        self.action_calls = []
        self.dispatcher.register(f"{server_key}/{action_name}", self._run_action)
        self.dispatcher.register("attach_client", self._noop)
        self.dispatcher.register("detach_client", self._noop)

    async def _noop(self, **kwargs) -> bool:
        return True

    async def _run_action(self, action: dict = None, **kwargs):
        action_dict = action or {}
        self.action_calls.append(deepcopy(action_dict))
        action_dict["action_status"] = [HloStatus.finished.value]
        # produce a sample_out so the experiment aggregates something
        action_dict.setdefault("samples_out", [])
        # write artifacts to disk like a real server would
        state = (
            RunDir.DIAG.value
            if action_dict.get("manual_action")
            else RunDir.FINISHED.value
        )
        out_dir = action_dict.get("action_output_dir")
        if out_dir:
            abs_dir = os.path.join(self.root, state, out_dir)
            os.makedirs(abs_dir, exist_ok=True)
            ts = _dt.now().strftime("%y%m%d.%H%M%S%f")
            hlo_name = f"{ts}__data.hlo"
            # the .hlo file (yml header + %% + one json line)
            with open(os.path.join(abs_dir, hlo_name), "w") as f:
                f.write("epoch_ns: 0\n%%\n")
                f.write('{"t": [0.0], "v": [1.0]}\n')
            # the act.yml, referencing the hlo file
            act_meta = {"file_type": "action"}
            act_meta.update(action_dict)
            act_meta["files"] = [
                {
                    "file_name": hlo_name,
                    "file_type": "helao__file",
                    "data_keys": ["t", "v"],
                    "action_uuid": action_dict.get("action_uuid"),
                }
            ]
            action_dict["files"] = act_meta["files"]
            with open(os.path.join(abs_dir, f"{ts}-act.yml"), "w") as f:
                f.write(_yml_dumps(act_meta))
        return action_dict


def _demo_exp_func(experiment, wait_time: float = 0.0):
    """Experiment function: plan two actions on the FAKE server via ActionPlanMaker."""
    from helao.helpers.premodels import ActionPlanMaker

    apm = ActionPlanMaker()
    apm.add("FAKE", "ping", {"wait_time": wait_time})
    apm.add("FAKE", "ping", {"wait_time": wait_time})
    return apm.planned_actions


async def _drive_run_experiment(reporter: TestReporter) -> None:
    root = tempfile.mkdtemp(prefix="micro_runexp_")
    fake_port = _free_port()
    fake = _FakeDataActionServer("FAKE", "ping", root)
    await fake.dispatcher.serve("127.0.0.1", derive_rpc_port(fake_port))
    try:
        async with _make_orch(
            root, {"FAKE": {"host": "127.0.0.1", "port": fake_port}}
        ) as orch:
            loaded = await orch.run_experiment(
                _demo_exp_func, experiment=Experiment(experiment_name="runexp")
            )
            from helao.core.drivers.data.loaders.localfs import HelaoExperiment

            reporter.check(
                "run_experiment returns a HelaoExperiment",
                lambda: isinstance(loaded, HelaoExperiment),
            )
            reporter.check(
                "fake server received two dispatches",
                lambda: len(fake.action_calls) == 2,
            )
            reporter.check(
                "both actions nested under the same experiment dir",
                lambda: all(
                    "__runexp" in c.get("action_output_dir", "")
                    for c in fake.action_calls
                ),
            )
            reporter.check(
                "exp run was tracked",
                lambda: any(r["type"] == "experiment" for r in orch.runs),
            )

            # standalone run_action -> HelaoAction
            act = Action(
                action_name="ping",
                action_server=MachineModel(server_name="FAKE"),
            )
            aloaded = await orch.run_action(act)
            from helao.core.drivers.data.loaders.localfs import HelaoAction

            reporter.check(
                "run_action returns a HelaoAction",
                lambda: isinstance(aloaded, HelaoAction),
            )
            reporter.check(
                "action run was tracked",
                lambda: any(r["type"] == "action" for r in orch.runs),
            )
            reporter.check(
                "exp.yml aggregates files from both dispatched actions",
                lambda: len(loaded.json.get("files", [])) == 2,
            )
    finally:
        await fake.dispatcher.close()
        shutil.rmtree(root, ignore_errors=True)


def _demo_seq_func(cycles: int = 2):
    """Sequence function: plan ``cycles`` demo experiments via ExperimentPlanMaker."""
    from helao.helpers.premodels import ExperimentPlanMaker

    epm = ExperimentPlanMaker()
    for _ in range(cycles):
        epm.add("demo_exp", {"wait_time": 0.0})
    return epm.planned_experiments


async def _drive_run_sequence(reporter: TestReporter) -> None:
    root = tempfile.mkdtemp(prefix="micro_runseq_")
    fake_port = _free_port()
    fake = _FakeDataActionServer("FAKE", "ping", root)
    await fake.dispatcher.serve("127.0.0.1", derive_rpc_port(fake_port))
    experiment_lib = {"demo_exp": _demo_exp_func}
    try:
        async with _make_orch(
            root, {"FAKE": {"host": "127.0.0.1", "port": fake_port}}
        ) as orch:
            loaded = await orch.run_sequence(_demo_seq_func, experiment_lib, cycles=2)
            from helao.core.drivers.data.loaders.localfs import HelaoSequence

            reporter.check(
                "run_sequence returns a HelaoSequence",
                lambda: isinstance(loaded, HelaoSequence),
            )
            reporter.check(
                "two experiments * two actions = four dispatches",
                lambda: len(fake.action_calls) == 4,
            )
            reporter.check(
                "sequence run tracked",
                lambda: any(r["type"] == "sequence" for r in orch.runs),
            )
            reporter.check(
                "all experiments nested under one sequence dir",
                lambda: len(
                    {
                        c["action_output_dir"].replace("\\", "/").split("/")[2]
                        for c in fake.action_calls
                    }
                )
                == 1,
            )
    finally:
        await fake.dispatcher.close()
        shutil.rmtree(root, ignore_errors=True)


async def _drive_zip_runs(reporter: TestReporter) -> None:
    root = tempfile.mkdtemp(prefix="micro_zip_")
    fake_port = _free_port()
    fake = _FakeDataActionServer("FAKE", "ping", root)
    await fake.dispatcher.serve("127.0.0.1", derive_rpc_port(fake_port))
    experiment_lib = {"demo_exp": _demo_exp_func}
    try:
        async with _make_orch(
            root, {"FAKE": {"host": "127.0.0.1", "port": fake_port}}
        ) as orch:
            await orch.run_sequence(_demo_seq_func, experiment_lib, cycles=1)
            zip_path = os.path.join(root, "artifacts.zip")
            out = orch.zip_runs(zip_path)
            reporter.check("zip_runs returns the zip path", lambda: out == zip_path)
            reporter.check("zip file exists", lambda: os.path.isfile(zip_path))
            with zipfile.ZipFile(zip_path) as zf:
                names = zf.namelist()
            reporter.check(
                "zip contains a seq yml entry",
                lambda: any(n.endswith("-seq.yml") for n in names),
            )
            reporter.check(
                "zip contains an exp yml entry",
                lambda: any(n.endswith("-exp.yml") for n in names),
            )
            reporter.check(
                "zip contains an act yml entry",
                lambda: any(n.endswith("-act.yml") for n in names),
            )
            reporter.check(
                "zip entries are relative (no RUNS_* prefix, no leading sep)",
                lambda: all(
                    not n.startswith("RUNS_") and not n.startswith(os.sep)
                    for n in names
                ),
            )
            reporter.check(
                "no duplicate entries",
                lambda: len(names) == len(set(names)),
            )
    finally:
        await fake.dispatcher.close()
        shutil.rmtree(root, ignore_errors=True)


async def _drive_zip_roundtrip(reporter: TestReporter) -> None:
    """A MicroOrch zip loads back through LocalLoader."""
    root = tempfile.mkdtemp(prefix="micro_ziprt_")
    fake_port = _free_port()
    fake = _FakeDataActionServer("FAKE", "ping", root)
    await fake.dispatcher.serve("127.0.0.1", derive_rpc_port(fake_port))
    experiment_lib = {"demo_exp": _demo_exp_func}
    try:
        async with _make_orch(
            root, {"FAKE": {"host": "127.0.0.1", "port": fake_port}}
        ) as orch:
            seq_loaded = await orch.run_sequence(
                _demo_seq_func, experiment_lib, cycles=1
            )
            zip_path = os.path.join(root, "artifacts.zip")
            orch.zip_runs(zip_path)

        from helao.core.drivers.data.loaders.localfs import LocalLoader

        loader = LocalLoader(zip_path)
        reporter.check(
            "loader indexed exactly one sequence",
            lambda: len(loader.sequences) == 1,
        )
        reporter.check(
            "loader indexed one experiment",
            lambda: len(loader.experiments) == 1,
        )
        reporter.check(
            "loader indexed two actions",
            lambda: len(loader.actions) == 2,
        )
        seq = loader.get_seq(0)
        reporter.check(
            "round-tripped sequence_uuid matches",
            lambda: str(seq.sequence_uuid) == str(seq_loaded.sequence_uuid),
        )
        act = loader.get_act(0)
        meta, data = act.hlo
        reporter.check(
            "round-tripped action hlo data is readable",
            lambda: "v" in data and list(data["v"]) == [1.0],
        )
    finally:
        await fake.dispatcher.close()
        shutil.rmtree(root, ignore_errors=True)


async def _drive_micro_orch(reporter: TestReporter) -> None:
    """Build a fake action server + MicroOrch, run an action, assert state."""
    server_key = "FAKE"
    action_name = "ping"
    fake_port = _free_port()
    fake_server = _FakeActionServer(server_key, action_name)
    await fake_server.dispatcher.serve("127.0.0.1", derive_rpc_port(fake_port))

    micro_port = _free_port()
    world_cfg = {
        "servers": {
            server_key: {"host": "127.0.0.1", "port": fake_port},
        }
    }

    try:
        async with MicroOrch(
            server_key="micro",
            host="127.0.0.1",
            port=micro_port,
            world_cfg=world_cfg,
            default_timeout=3.0,
        ) as orch:
            # Dispatcher should now be listening on derive_rpc_port(micro_port)
            reporter.check(
                "MicroOrch.dispatcher is bound after start()",
                lambda: orch.dispatcher._task is not None,
            )

            action = Action(
                action_name=action_name,
                action_server=MachineModel(server_name=server_key),
            )

            result = await orch.run_action(
                action, wait_timeout=3.0, await_completion=False
            )

            reporter.check(
                "run_action returns the finished action dump",
                lambda: isinstance(result, dict)
                and HloStatus.finished.value in result.get("action_status", []),
            )
            reporter.check(
                "fake action server received exactly one dispatch",
                lambda: len(fake_server.action_calls) == 1,
            )
            reporter.check(
                "dispatched payload preserved the action_name",
                lambda: fake_server.action_calls[0].get("action_name") == action_name,
            )
            reporter.check(
                "MicroOrch attached to the action server",
                lambda: fake_server.attach_calls >= 1,
            )
            reporter.check(
                "MicroOrch.latest caches the dispatched action UUID",
                lambda: orch.latest(action.action_uuid) is not None,
            )
            reporter.check(
                "pending_uuids drains once the action resolves",
                lambda: action.action_uuid not in orch.pending_uuids(),
            )

        # After leaving the async-with, the dispatcher must be closed.
        reporter.check(
            "MicroOrch dispatcher closes on __aexit__",
            lambda: orch.dispatcher._task is None,
        )
    finally:
        await fake_server.dispatcher.close()


async def _drive_yml_writers(reporter: TestReporter) -> None:
    """_write_exp / _write_seq land yml under RUNS_DIAG for a manual experiment."""
    root = tempfile.mkdtemp(prefix="micro_yml_")
    try:
        orch = _make_orch(root)
        exp = _build_experiment("yml_exp")

        exp_file = await orch._write_exp(exp)
        reporter.check(
            "_write_exp returns an existing .yml path",
            lambda: isinstance(exp_file, str) and os.path.isfile(exp_file),
        )
        reporter.check(
            "exp yml is under RUNS_DIAG (manual_action)",
            lambda: os.sep + RunDir.DIAG.value + os.sep in exp_file,
        )
        from helao.helpers.yml_tools import yml_load

        with open(exp_file) as f:
            exp_meta = yml_load(f.read())
        reporter.check(
            "exp yml has file_type=experiment and matching uuid",
            lambda: (
                exp_meta["file_type"] == "experiment"
                and str(exp_meta["experiment_uuid"]) == str(exp.experiment_uuid)
            ),
        )

        seq = Sequence(sequence_name="yml_seq", sequence_label="manual")
        seq.manual_action = True
        seq.init_seq(time_offset=0)
        seq_file = await orch._write_seq(seq)
        reporter.check(
            "_write_seq returns an existing .yml path under RUNS_DIAG",
            lambda: os.path.isfile(seq_file)
            and os.sep + RunDir.DIAG.value + os.sep in seq_file,
        )
        with open(seq_file) as f:
            seq_meta = yml_load(f.read())
        reporter.check(
            "seq yml has file_type=sequence",
            lambda: seq_meta["file_type"] == "sequence",
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _check_stage_experiment(reporter: TestReporter) -> None:
    """_stage_experiment synthesizes a manual sequence and nests the exp dir."""
    root = tempfile.mkdtemp(prefix="micro_stage_")
    try:
        orch = _make_orch(root)

        # standalone: no sequence supplied -> manual sequence synthesized
        exp = Experiment(experiment_name="stage_exp")
        orch._stage_experiment(exp, order=0, sequence=None)
        reporter.check(
            "standalone experiment is flagged manual",
            lambda: exp.manual_action is True and exp.access == "manual",
        )
        reporter.check(
            "experiment has a sequence_output_dir",
            lambda: bool(exp.sequence_output_dir),
        )
        reporter.check(
            "experiment_output_dir nests under sequence_output_dir",
            lambda: exp.get_experiment_dir().startswith(str(exp.sequence_output_dir)),
        )

        # with a supplied sequence -> identity copied, not manual
        seq = Sequence(sequence_name="parent_seq", sequence_label="lbl")
        seq.init_seq(time_offset=0)
        exp2 = Experiment(experiment_name="child_exp")
        orch._stage_experiment(exp2, order=0, sequence=seq)
        reporter.check(
            "child experiment inherits parent sequence_uuid",
            lambda: str(exp2.sequence_uuid) == str(seq.sequence_uuid),
        )
        reporter.check(
            "child experiment inherits parent sequence_output_dir",
            lambda: exp2.sequence_output_dir == seq.sequence_output_dir,
        )
        reporter.check(
            "child experiment is not manual",
            lambda: not exp2.manual_action,
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


async def _drive_load_finished(reporter: TestReporter) -> None:
    """_await_finished finds a written yml; _load_finished wraps it."""
    root = tempfile.mkdtemp(prefix="micro_load_")
    try:
        orch = _make_orch(root)
        exp = _build_experiment("load_exp")  # manual -> RUNS_DIAG
        await orch._write_exp(exp)

        rel_dir = exp.get_experiment_dir()
        found = await orch._await_finished(rel_dir, "exp")
        reporter.check(
            "_await_finished locates the manual exp yml in RUNS_DIAG",
            lambda: os.path.isfile(found)
            and os.sep + RunDir.DIAG.value + os.sep in found,
        )

        loaded = await orch._load_finished(rel_dir, "exp")
        from helao.core.drivers.data.loaders.localfs import HelaoExperiment

        reporter.check(
            "_load_finished returns a HelaoExperiment",
            lambda: isinstance(loaded, HelaoExperiment),
        )
        reporter.check(
            "loaded experiment_uuid matches",
            lambda: str(loaded.experiment_uuid) == str(exp.experiment_uuid),
        )

        # timeout path: a relative dir that never appears
        async def _expect_timeout():
            try:
                await orch._await_finished("99.99/9999/000000__nope__none", "exp")
                return False
            except TimeoutError:
                return True

        timed_out = await _expect_timeout()
        reporter.check(
            "_await_finished raises TimeoutError when nothing appears",
            lambda: timed_out,
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _check_track_run(reporter: TestReporter) -> None:
    """_track_run appends a normalized RunRecord derived from a yml path."""
    root = tempfile.mkdtemp(prefix="micro_track_")
    try:
        orch = _make_orch(root)
        yml_path = os.path.join(
            root,
            RunDir.DIAG.value,
            "26.24",
            "0616",
            "120000__seq--x__manual",
            "260616.120001000000__exp--x",
            "260616.120001000000-exp.yml",
        )
        os.makedirs(os.path.dirname(yml_path), exist_ok=True)
        with open(yml_path, "w") as f:
            f.write("file_type: experiment\n")

        rec = orch._track_run("experiment", "uuid-1", "exp--x", yml_path)
        reporter.check("_track_run returns the record", lambda: rec in orch.runs)
        reporter.check(
            "record state derived from path",
            lambda: rec["state"] == RunDir.DIAG,
        )
        reporter.check(
            "record rel_dir is relative to the state root",
            lambda: rec["rel_dir"]
            == os.path.join(
                "26.24",
                "0616",
                "120000__seq--x__manual",
                "260616.120001000000__exp--x",
            ),
        )
        reporter.check("runs list has one entry", lambda: len(orch.runs) == 1)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def micro_orch_unit_test() -> bool:
    """Run all MicroOrch assertions and report pass/fail."""
    reporter = TestReporter("micro_orch")

    try:
        reporter.section("_is_terminal helper")
        reporter.check(
            "empty status list is not terminal",
            lambda: _is_terminal([]) is False,
        )
        reporter.check(
            "None status list is not terminal",
            lambda: _is_terminal(None) is False,
        )
        reporter.check(
            "active HloStatus member -> not terminal",
            lambda: _is_terminal([HloStatus.active]) is False,
        )
        reporter.check(
            "string 'active' (post msgpack) -> not terminal",
            lambda: _is_terminal(["active"]) is False,
        )
        reporter.check(
            "finished status -> terminal",
            lambda: _is_terminal([HloStatus.finished]) is True,
        )
        reporter.check(
            "errored status -> terminal",
            lambda: _is_terminal(["errored"]) is True,
        )

        reporter.section("MicroOrch end-to-end run_action")
        asyncio.run(_drive_micro_orch(reporter))

        reporter.section("MicroOrch yml writers")
        asyncio.run(_drive_yml_writers(reporter))

        reporter.section("MicroOrch _stage_experiment")
        _check_stage_experiment(reporter)

        reporter.section("MicroOrch loader read-back")
        asyncio.run(_drive_load_finished(reporter))

        reporter.section("MicroOrch run tracking")
        _check_track_run(reporter)

        reporter.section("MicroOrch run_experiment / run_action end-to-end")
        asyncio.run(_drive_run_experiment(reporter))

        reporter.section("MicroOrch run_sequence end-to-end")
        asyncio.run(_drive_run_sequence(reporter))

        reporter.section("MicroOrch zip_runs")
        asyncio.run(_drive_zip_runs(reporter))

        reporter.section("MicroOrch zip <-> LocalLoader round-trip")
        asyncio.run(_drive_zip_roundtrip(reporter))

        return reporter.success()

    except Exception as exc:  # noqa: BLE001
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        print(repr(exc), tb)
        return False
