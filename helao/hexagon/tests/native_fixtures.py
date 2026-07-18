"""Shared fixtures for the P2b-1 native-adapter tests.

Mirrors the ``Base.__new__`` bypass fixture proven by
``helao/core/tests/unit_test_active_data_file.py`` (`_make_base`/`_mk_action`):
a bare ``Base`` built without ``Base.__init__`` (no FastAPI app, no NTP, no
WebSockets), populated with every attribute the Active construction + the
write collaborators + the graft touch, then ``_init_collaborators()``.

Tests layer — may import anything (boundary rule)."""

import inspect
from datetime import datetime
from types import SimpleNamespace
from uuid import UUID

from helao.core.servers.base import Base, Active
from helao.core.models.file import FileConnParams, HloFileGroup
from helao.core.models.machine import MachineModel
from helao.helpers.active_params import ActiveParams
from helao.helpers.multisubscriber_queue import MultisubscriberQueue
from helao.helpers.premodels import Action

FIXED_DT = datetime(2026, 1, 2, 3, 4, 5, 678901)


def make_base(save_root: str) -> Base:
    """Bare ``Base`` with every attribute Active construction + the write
    path (myinit/log_data_task/finish/meta writers) touches."""
    base = Base.__new__(Base)
    base.app = SimpleNamespace(driver=None)  # type: ignore[reportAttributeAccessIssue]
    base.server = MachineModel(
        server_name="ACTSRV",
        machine_name="test-machine",
        hostname="127.0.0.1",
        port=8000,
    )
    base.world_cfg = {"dummy": False, "simulation": False}
    base.ntp_offset = 0.0
    base.helaodirs = SimpleNamespace(save_root=save_root)  # type: ignore[reportAttributeAccessIssue]
    base.status_q = MultisubscriberQueue()
    base.data_q = MultisubscriberQueue()
    base.actives = {}
    base.history = {}  # type: ignore[reportAttributeAccessIssue]
    base.local_action_task_queue = []
    base.hlo_postprocessors = []
    base.hlo_postprocess_libs = []
    base._init_collaborators()
    return base


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
    # Mirrors what `Active.__init__` does to every action before it reaches
    # the write path (`action.init_act(...)`, which cascades into
    # `init_seq`/`init_exp` when needed): populate sequence/experiment/action
    # output dirs. sequence_timestamp/experiment_timestamp/action_timestamp
    # are already fixed above, so this only fills the *_output_dir fields
    # deterministically -- it never re-stamps the fixed timestamps.
    action.init_seq()
    action.init_exp()
    action.init_act()
    return action


def mk_active(base: Base, json_data_keys=None, action=None):
    """Legacy Active + its default file-conn key (collaborators still legacy;
    tests swap in the native class under test explicitly)."""
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
    return Active(base, ap), dflt


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
