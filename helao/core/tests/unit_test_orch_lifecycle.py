"""Unit tests for the ``RunLifecycle`` collaborator extracted from ``Orch``
(CARDS P5, Stage S6): active-sequence/experiment close-out cluster.

``finish_active_sequence``/``finish_active_experiment`` are already exercised
(byte-for-byte) by ``test_orch_dispatch_golden_master.py --check`` via the
dispatch loop's own end-of-run/end-of-experiment calls, but that harness
shadows ``write_seq``/``write_exp``/``put_lbuf`` and rebinds
``helao.core.servers.orch.move_dir`` for its whole run rather than asserting
on the resulting ``active_*``/``last_*``/history state directly. This module
is the S6-specific behavior-preservation gate for that close-out state and
for the two small ``write_active_*`` helpers.

Mirrors the ``Orch.__new__`` bypass fixture used by
``test_orch_dispatch_golden_master.py``'s ``_make_orch`` (and the S3/S4/S5
sibling unit tests): a bare ``Orch`` built without ``Base.__init__`` (no
FastAPI app, no disk I/O, no NTP), populated only with the attributes
``RunLifecycle`` methods touch, then ``_init_collaborators()`` is called so
``orch.run_lifecycle`` exists exactly as it would after the real ``__init__``.

Hermetic: no network, no disk I/O -- ``write_seq``/``write_exp``/``put_lbuf``
are recording no-ops bound directly on the fixture (mirrors the golden
master's own stub technique), and ``helao.core.servers.orch.move_dir`` is
monkeypatched with a recording no-op for the duration of each check (restored
in a ``finally``) since ``finish_active_sequence``/``finish_active_experiment``
fire-and-forget a background task that calls it.
"""

__all__ = ["orch_lifecycle_unit_test"]

import asyncio
import traceback

import helao.core.servers.orch as orch_module
from helao.core.models.hlostatus import HloStatus
from helao.core.models.machine import MachineModel
from helao.core.models.server import GlobalStatusModel
from helao.core.servers.orch import Orch
from helao.core.tests._test_utils import TestReporter
from helao.helpers.dequedict import DequeDict
from helao.helpers.premodels import Experiment, Sequence

ORCH_SERVER_NAME = "ORCH"
ORCH_MACHINE = "test-machine"


def _make_orch() -> Orch:
    """Build a bare ``Orch`` with every attribute ``RunLifecycle`` methods touch."""
    orch = Orch.__new__(Orch)

    orch.server = MachineModel(
        server_name=ORCH_SERVER_NAME,
        machine_name=ORCH_MACHINE,
        hostname="127.0.0.1",
        port=8000,
    )
    orch.ntp_offset = 0.0
    orch.global_params = {}

    orch.seq_postprocessors = []
    orch.seq_postprocess_libs = []
    orch.exp_postprocessors = []
    orch.exp_postprocess_libs = []

    orch.nonblocking = []
    orch.active_sequence = None
    orch.active_experiment = None
    orch.last_sequence = None
    orch.last_experiment = None
    orch.active_seq_exp_counter = 3

    orch.action_history = DequeDict(maxlen=1000)
    orch.experiment_history = DequeDict(maxlen=1000)
    orch.sequence_history = DequeDict(maxlen=1000)

    orch.globalstatusmodel = GlobalStatusModel(orchestrator=orch.server)
    orch.globalstatusmodel.counter_dispatched_actions = {"leftover": 4}

    recorded = {"write_seq": [], "write_exp": [], "put_lbuf": []}

    async def _write_seq(sequence):
        recorded["write_seq"].append(sequence.sequence_name)

    async def _write_exp(experiment):
        recorded["write_exp"].append(experiment.experiment_name)

    async def _put_lbuf(live_dict):
        recorded["put_lbuf"].append([v for v in live_dict.values()])

    orch.write_seq = _write_seq
    orch.write_exp = _write_exp
    orch.put_lbuf = _put_lbuf

    orch._init_collaborators()
    return orch, recorded


def _mk_sequence(name: str) -> Sequence:
    seq = Sequence(sequence_name=name, sequence_params={})
    seq.init_seq(time_offset=0.0)
    seq.sequence_status = [HloStatus.active]
    return seq


def _mk_experiment(name: str) -> Experiment:
    exp = Experiment(experiment_name=name, experiment_params={})
    exp.init_exp(time_offset=0.0)
    exp.experiment_status = [HloStatus.active]
    return exp


class _MoveDirRecorder:
    """Context manager that patches ``helao.core.servers.orch.move_dir`` with a
    recording no-op, restoring the original in ``__exit__`` -- mirrors the
    dispatch golden-master harness's own ``move_dir`` rebind technique
    (``finish_active_sequence``/``finish_active_experiment`` import it lazily
    from ``helao.core.servers.orch`` specifically so this external patch
    point keeps working post-extraction)."""

    def __init__(self):
        self.calls = []
        self._orig = None

    def __enter__(self):
        async def _fake_move_dir(hobj, base=None, retry_delay=5):
            self.calls.append(hobj)
            return None

        self._orig = orch_module.move_dir
        orch_module.move_dir = _fake_move_dir
        return self

    def __exit__(self, exc_type, exc, tb):
        orch_module.move_dir = self._orig


async def _drain_tasks():
    """Let any fire-and-forget ``aloop.create_task(...)`` background tasks run."""
    for _ in range(5):
        await asyncio.sleep(0)


async def _check_finish_active_sequence() -> bool:
    orch, recorded = _make_orch()
    orch.aloop = asyncio.get_running_loop()
    orch.active_sequence = _mk_sequence("seq1")

    with _MoveDirRecorder() as md:
        await orch.finish_active_sequence()
        await _drain_tasks()

    return (
        orch.active_sequence is None
        and orch.last_sequence is not None
        and orch.last_sequence.sequence_name == "seq1"
        and orch.last_sequence.sequence_status == [HloStatus.finished]
        and orch.active_seq_exp_counter == 0
        and orch.globalstatusmodel.counter_dispatched_actions == {}
        and recorded["write_seq"] == ["seq1"]
        and len(recorded["put_lbuf"]) == 1
        and recorded["put_lbuf"][0][0]["status"] == HloStatus.finished.value
        and len(md.calls) == 1
        and md.calls[0] is orch.last_sequence
        and orch.sequence_history[orch.last_sequence.sequence_uuid]["sequence_status"]
        == HloStatus.finished.value
    )


async def _check_finish_active_experiment() -> bool:
    orch, recorded = _make_orch()
    orch.aloop = asyncio.get_running_loop()
    orch.active_sequence = _mk_sequence("seq1")
    orch.active_experiment = _mk_experiment("exp1")

    with _MoveDirRecorder() as md:
        await orch.finish_active_experiment()
        await _drain_tasks()

    return (
        orch.active_experiment is None
        and orch.last_experiment is not None
        and orch.last_experiment.experiment_name == "exp1"
        and orch.last_experiment.experiment_status == [HloStatus.finished]
        and len(orch.active_sequence.dispatched_experiments) == 1
        and orch.active_sequence.dispatched_experiments[0].experiment_name == "exp1"
        # finish_active_experiment calls write_active_sequence_seq() (the
        # Orch delegator -> RunLifecycle.write_active_sequence_seq(), which
        # in turn calls orch.write_seq) and its own write_exp on the way out.
        and recorded["write_seq"] == ["seq1"]
        and recorded["write_exp"] == ["exp1"]
        and len(recorded["put_lbuf"]) == 1
        and recorded["put_lbuf"][0][0]["status"] == HloStatus.finished.value
        and len(md.calls) == 1
        and md.calls[0] is orch.last_experiment
        and orch.experiment_history[orch.last_experiment.experiment_uuid][
            "experiment_status"
        ]
        == HloStatus.finished.value
    )


async def _check_write_active_experiment_exp() -> bool:
    orch, recorded = _make_orch()
    orch.active_experiment = _mk_experiment("exp1")
    orch.global_params = {"kept": 1, "_fast_samples_in": "dropped"}

    await orch.write_active_experiment_exp()

    return orch.active_experiment.initial_global_params == {"kept": 1} and recorded[
        "write_exp"
    ] == ["exp1"]


async def _check_write_active_sequence_seq() -> bool:
    orch, recorded = _make_orch()
    orch.active_sequence = _mk_sequence("seq1")
    orch.global_params = {"kept": 2, "_fast_samples_in": "dropped"}

    await orch.write_active_sequence_seq()

    return orch.active_sequence.initial_global_params == {"kept": 2} and recorded[
        "write_seq"
    ] == ["seq1"]


async def _run_checks() -> dict:
    return {
        "finish_active_sequence": await _check_finish_active_sequence(),
        "finish_active_experiment": await _check_finish_active_experiment(),
        "write_active_experiment_exp": await _check_write_active_experiment_exp(),
        "write_active_sequence_seq": await _check_write_active_sequence_seq(),
    }


def orch_lifecycle_unit_test() -> bool:
    reporter = TestReporter("orch_lifecycle")
    try:
        res = asyncio.run(_run_checks())
    except Exception as exc:  # noqa: BLE001
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        print(repr(exc), tb)
        return False

    reporter.section("finish_active_sequence")
    reporter.check(
        "finishes+rolls-over active_sequence, resets counters, writes/persists,"
        " and schedules move_dir on the finished sequence",
        lambda: res["finish_active_sequence"],
    )

    reporter.section("finish_active_experiment")
    reporter.check(
        "finishes+rolls-over active_experiment, appends it to the sequence's"
        " dispatched_experiments, re-persists the sequence, and schedules move_dir",
        lambda: res["finish_active_experiment"],
    )

    reporter.section("write_active_experiment_exp / write_active_sequence_seq")
    reporter.check(
        "snapshot initial_global_params (dropping _fast_samples_in) and persist",
        lambda: res["write_active_experiment_exp"] and res["write_active_sequence_seq"],
    )

    return reporter.success()


if __name__ == "__main__":
    import sys

    sys.exit(0 if orch_lifecycle_unit_test() else 1)
