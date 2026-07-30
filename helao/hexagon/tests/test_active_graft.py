"""Active write-path graft (P2b-1): drift pin, honesty tripwire, in-process
end-to-end. The graft reproduces Base.contain_action's body (Q1, binding)
because the collaborator swap MUST land between Active.__init__ and
myinit() — myinit spawns (and awaits alongside) the data_logger task, so a
post-return swap races the drain loop's collaborator resolution."""

import asyncio
import inspect
import os
import textwrap

import pytest

import helao.hexagon.adapters.native.finalizer as native_finalizer_mod
from helao.core.models.data import DataModel
from helao.core.models.file import FileConnParams, HloFileGroup
from helao.core.servers.base import Base
from helao.core.servers.base_meta_writer import MetaFileWriter
from helao.helpers.active_params import ActiveParams
from helao.hexagon.adapters.errors import UnwiredPortError
from helao.hexagon.adapters.native.artifact_store import NativeArtifactStoreAdapter
from helao.hexagon.adapters.native.data_file import NativeDataFileWriter
from helao.hexagon.adapters.native.data_sink import NativeDataSinkAdapter
from helao.hexagon.adapters.native.data_stream import NativeDataStreamer
from helao.hexagon.adapters.native.finalizer import NativeActionFinalizer
from helao.hexagon.adapters.native.meta_writer import NativeMetaFileWriter
from helao.hexagon.app.active_graft import ActiveWriteGraft, graft_active_write_path
from helao.hexagon.app.wiring import PortWiring
from helao.hexagon.tests.native_fixtures import make_base, mk_action

# ---------------------------------------------------------------------------
# drift pin (Q1): the graft reproduces this body verbatim (+ swap lines).
# If this test fails, legacy contain_action changed — update BOTH the pinned
# text below AND hex_contain_action in app/active_graft.py, then re-run the
# GM gate.
# ---------------------------------------------------------------------------
PINNED_CONTAIN_ACTION = '''\
async def contain_action(self, activeparams: ActiveParams):
    """Register an action as ``Active`` on the server, substituting any prior one with the same UUID.

    Args:
        activeparams: Parameters describing the action to contain.

    Returns:
        The newly created ``Active`` instance for the action.
    """
    if activeparams.action.action_uuid in self.actives:
        await self.actives[activeparams.action.action_uuid].substitute()
    self.actives[activeparams.action.action_uuid] = Active(
        self, activeparams=activeparams
    )
    await self.actives[activeparams.action.action_uuid].myinit()
    cact = copy(self.actives[activeparams.action.action_uuid].action)
    self.history[cact.action_uuid] = cact
    # register action_uuid in local action task queue
    return self.actives[activeparams.action.action_uuid]
'''


def test_contain_action_drift_pin():
    src = textwrap.dedent(inspect.getsource(Base.contain_action))
    assert src == PINNED_CONTAIN_ACTION, (
        "Base.contain_action drifted from the pinned body the graft "
        "reproduces — update app/active_graft.py:hex_contain_action AND "
        "this pin, then re-run GM-1..GM-5"
    )


def _wiring():
    store = NativeArtifactStoreAdapter(config=None, clock=None)
    return PortWiring(artifact_store=store, data_sink=NativeDataSinkAdapter())


def _activeparams(base, action=None):
    action = action or mk_action()
    dflt = base.dflt_file_conn_key()
    return ActiveParams(
        action=action,
        file_conn_params_dict={
            dflt: FileConnParams(
                file_conn_key=dflt,
                json_data_keys=["t_s", "value"],
                file_type="nu__test_file",
                file_group=HloFileGroup.helao_files,
            )
        },
        aux_listen_uuids=[],
    )


def test_graft_requires_wired_artifact_store(tmp_path):
    base = make_base(str(tmp_path))
    with pytest.raises(UnwiredPortError):
        graft_active_write_path(base, PortWiring())


@pytest.mark.asyncio
async def test_honesty_tripwire_native_collaborators_carry_traffic(
    tmp_path, monkeypatch
):
    """THE DD-7 tripwire: a contained Active's collaborators must BE the
    native types (GM parity alone cannot distinguish 'native carried the
    traffic' from silent legacy fallthrough)."""

    async def fake_move_dir(action, base=None):
        pass

    monkeypatch.setattr(native_finalizer_mod, "move_dir", fake_move_dir)
    base = make_base(str(tmp_path / "RUNS_ACTIVE"))
    base.aloop = asyncio.get_running_loop()
    graft = graft_active_write_path(base, _wiring())
    assert isinstance(graft, ActiveWriteGraft)
    assert isinstance(base.meta_writer, NativeMetaFileWriter)
    # the CLASS attr is untouched (instance-rebind only, zero legacy edits)
    assert Base.contain_action is graft.originals["contain_action"].__func__  # type: ignore[reportAttributeAccessIssue]

    active = await base.contain_action(_activeparams(base))
    assert isinstance(active.data_stream, NativeDataStreamer)
    assert isinstance(active.data_file_writer, NativeDataFileWriter)
    assert isinstance(active.action_finalizer, NativeActionFinalizer)
    assert active.action.action_uuid in base.history  # legacy body reproduced

    # end-to-end through the grafted runtime: enqueue -> drain -> finish
    dflt = base.dflt_file_conn_key()
    await active.enqueue_data(
        DataModel(data={dflt: {"t_s": 1, "value": 2.0}}, errors=[])
    )
    await asyncio.sleep(0.15)
    await active.finish()
    out_dir = os.path.join(
        str(base.helaodirs.save_root), str(active.action.action_output_dir)
    )
    hlo = [f for f in os.listdir(out_dir) if f.endswith(".hlo")]
    assert hlo, "native drain loop wrote no .hlo"
    text = open(os.path.join(out_dir, hlo[0])).read()
    # hlo_json_dumps compact separators (no spaces)
    assert "%%\n" in text and '{"t_s":1,"value":2.0}' in text
    assert [f for f in os.listdir(out_dir) if f.endswith("-act.yml")]


@pytest.mark.asyncio
async def test_duplicate_uuid_substitutes_prior_active(tmp_path, monkeypatch):
    """The substitute-on-duplicate-uuid branch (base.py:447-448) — the
    behavior half of the drift pin."""

    async def fake_move_dir(action, base=None):
        pass

    monkeypatch.setattr(native_finalizer_mod, "move_dir", fake_move_dir)
    base = make_base(str(tmp_path / "RUNS_ACTIVE"))
    base.aloop = asyncio.get_running_loop()
    graft_active_write_path(base, _wiring())
    first = await base.contain_action(_activeparams(base))
    dflt = base.dflt_file_conn_key()
    await first.enqueue_data(DataModel(data={dflt: {"t_s": 1}}, errors=[]))
    await asyncio.sleep(0.15)
    assert first.file_conn_dict[dflt].file is not None
    # same uuid again -> prior active's open streams are substituted (closed)
    second = await base.contain_action(_activeparams(base, action=mk_action()))
    assert second is not first
    with pytest.raises(ValueError):
        await first.file_conn_dict[dflt].file.write("x")
    first.data_logger.cancel()
    second.data_logger.cancel()
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_close_restores_originals(tmp_path):
    base = make_base(str(tmp_path))
    base.aloop = asyncio.get_running_loop()
    original_contain = base.contain_action
    original_meta = base.meta_writer
    graft = graft_active_write_path(base, _wiring())
    assert base.contain_action is not original_contain
    graft.close()
    assert base.contain_action == original_contain
    assert base.meta_writer is original_meta
    assert isinstance(base.meta_writer, MetaFileWriter)
