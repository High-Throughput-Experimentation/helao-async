"""Shared fixtures for the native-adapter tests.

A bare ``ActionHost`` built with ``ActionHost.__new__`` (no FastAPI app, no
routes, no NTP, no WebSockets), populated with every attribute an
``ActionSession`` and its native write collaborators touch, and an
``ActionSession`` over it. The session constructs the native collaborators
itself, so no test swaps one in.

Tests layer — may import anything (boundary rule)."""

import inspect
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from helao.core.hooks import HookSet
from helao.core.models.file import FileConnParams, HloFileGroup
from helao.core.models.machine import MachineModel
from helao.helpers.active_params import ActiveParams
from helao.helpers.dequedict import DequeDict
from helao.helpers.multisubscriber_queue import MultisubscriberQueue
from helao.helpers.premodels import Action
from helao.hexagon.adapters.legacy.clock import LegacyClockAdapter
from helao.hexagon.adapters.native.artifact_store import NativeArtifactStoreAdapter
from helao.hexagon.app.action_host import ActionHost
from helao.hexagon.app.action_session import ActionSession
from helao.hexagon.app.wiring import PortWiring

FIXED_DT = datetime(2026, 1, 2, 3, 4, 5, 678901)


def make_base(save_root: str) -> ActionHost:
    """Bare ``ActionHost`` with every attribute session construction + the
    write path (myinit/log_data_task/finish/meta writers) touches."""
    host = ActionHost.__new__(ActionHost)
    store = NativeArtifactStoreAdapter(config=None, clock=None)
    host.hexagon_wiring = PortWiring(
        clock=LegacyClockAdapter(0.0), artifact_store=store
    )
    host.server_key = "ACTSRV"
    host.driver = None
    host.server = MachineModel(
        server_name="ACTSRV",
        machine_name="test-machine",
        hostname="127.0.0.1",
        port=8000,
    )
    host.world_cfg = {"dummy": False, "simulation": False}
    host.ntp_offset = 0.0
    host.helaodirs = SimpleNamespace(save_root=save_root)  # type: ignore[reportAttributeAccessIssue]
    host.run_journal = None
    host.aloop = None
    host.status_q = MultisubscriberQueue()
    host.data_q = MultisubscriberQueue()
    host.live_q = MultisubscriberQueue()
    host.live_buffer = {}
    host.status_clients = set()
    host.actives = {}
    host.history = DequeDict(maxlen=200)
    host.executors = {}
    host.local_action_task_queue = []
    host.prefinish_hooks = HookSet.empty()
    host.meta_writer = store.meta_writer_for(host)
    return host


def mk_action(**overrides) -> Action:
    """Deterministic non-manual Action with data saving enabled."""
    kwargs = dict(
        action_name="nutest",
        action_abbr="nute",
        orch_key="ORCH",
        orch_host="127.0.0.1",
        orch_port=8001,
        action_uuid=UUID("00000000-0000-0000-0000-0000000000a1"),
        action_timestamp=FIXED_DT,
        sequence_uuid=UUID("00000000-0000-0000-0000-0000000000b1"),
        sequence_name="seq_nu",
        sequence_label="p2b1",
        sequence_timestamp=FIXED_DT,
        experiment_uuid=UUID("00000000-0000-0000-0000-0000000000c1"),
        experiment_name="exp_nu",
        experiment_timestamp=FIXED_DT,
        save_data=True,
    )
    kwargs.update(overrides)
    action = Action(**kwargs)  # type: ignore[reportArgumentType]
    # Mirrors what session construction does to every action before it
    # reaches the write path (`action.init_act(...)`, which cascades into
    # `init_seq`/`init_exp` when needed): populate sequence/experiment/action
    # output dirs. sequence_timestamp/experiment_timestamp/action_timestamp
    # are already fixed above, so this only fills the *_output_dir fields
    # deterministically -- it never re-stamps the fixed timestamps.
    action.init_seq()
    action.init_exp()
    action.init_act()
    return action


def mk_active(base: ActionHost, json_data_keys=None, action=None):
    """``ActionSession`` + its default file-conn key. Not registered in
    ``base.actives``; tests that need that register it themselves."""
    if action is None:
        action = mk_action()
    dflt = base.dflt_file_conn_key()
    ap = ActiveParams(
        action=action,
        file_conn_params_dict={
            dflt: FileConnParams(
                file_conn_key=dflt,
                json_data_keys=json_data_keys or ["t_s", "value"],
                file_type="nu__test_file",
                file_group=HloFileGroup.helao_files,
            )
        },
        aux_listen_uuids=[],
    )
    return ActionSession(base, ap), dflt


def _make_active_for_journal(tmp_path, manual_action: bool = False):
    """A session on a real ``RunStateJournal``, rooted at ``tmp_path``.

    ``make_base`` gives the finish path every attribute it touches but no
    station root, so it has no journal. ``test_run_state_wiring.py`` drives
    the real ``move_dir`` through ``finish`` to assert the journal drains.
    Call it from a running event loop: the finalizer schedules ``move_dir``
    on ``base.aloop``, and with ``aloop`` unset that raises inside a caught
    block and the eviction silently never runs.
    """
    import asyncio

    from helao.helpers.run_state import RunStateJournal

    save_root = Path(tmp_path) / "RUNS"
    save_root.mkdir(parents=True, exist_ok=True)
    base = make_base(str(save_root))
    base.world_cfg = {"dummy": False, "simulation": False, "root": str(tmp_path)}
    base.helaodirs = SimpleNamespace(  # type: ignore[reportAttributeAccessIssue]
        root=str(tmp_path),
        save_root=str(save_root),
        states_root=str(Path(tmp_path) / "STATES"),
    )
    base.run_journal = RunStateJournal(base.helaodirs.states_root, "SIM")
    base.aloop = asyncio.get_running_loop()  # type: ignore[reportAttributeAccessIssue]
    action = mk_action(manual_action=manual_action, save_act=True)
    session, _ = mk_active(base, json_data_keys=["t", "v"], action=action)
    return base, session


def assert_source_parity(native_cls, legacy_cls, methods):
    """Byte-parity pin: each relocated method's source must be identical to
    its legacy counterpart (methods contain no class-name references, so
    straight equality holds for a verbatim copy)."""
    diffs = []
    for name in methods:
        n_src = inspect.getsource(getattr(native_cls, name))
        l_src = inspect.getsource(getattr(legacy_cls, name))
        if n_src != l_src:
            diffs.append(name)
    assert not diffs, f"native methods drifted from legacy source: {diffs}"
