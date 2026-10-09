"""NativeActionFinalizer (P2b-1): verbatim re-body of legacy ActionFinalizer
(helao/core/servers/active_finalizer.py, deleted by B7b) — the ce846da1
join-drain-close chain. Behavior on real tmp trees with a full native
collaborator set: finish drains queued data BEFORE closing
handles, closes every file, cancels data_logger, writes the final -act.yml,
schedules move_dir (manual included -- it is the journal eviction
point), pops base.actives into history;
substitute closes streams; split forks file conns + resets counters;
finish_manual_action writes synthesized exp/seq metas. Module globals
(move_dir/set_time/async_private_dispatcher) are patched on THIS module,
mirroring the legacy golden-master patching seam."""

import asyncio
import os
from uuid import UUID

import pytest

import helao.hexagon.adapters.native.finalizer as native_finalizer_mod
from helao.core.error import ErrorCodes
from helao.core.models.data import DataModel
from helao.core.models.hlostatus import HloStatus
from helao.hexagon.adapters.native.finalizer import NativeActionFinalizer
from helao.hexagon.adapters.native.meta_writer import NativeMetaFileWriter
from helao.hexagon.tests.native_fixtures import make_base, mk_action, mk_active


def _grafted_active(tmp_path, **action_over):
    """A session over a bare host (native collaborators and meta writer by
    construction), registered in base.actives, data_logger running."""
    base = make_base(str(tmp_path / "RUNS_ACTIVE"))
    action = mk_action(**action_over) if action_over else None
    active, dflt = mk_active(base, action=action)
    assert isinstance(active.action_finalizer, NativeActionFinalizer)
    assert isinstance(base.meta_writer, NativeMetaFileWriter)
    action_uuid = active.action.action_uuid
    assert action_uuid is not None
    base.actives[action_uuid] = active
    return base, active, dflt


async def _start_logger(base, active):
    base.aloop = asyncio.get_running_loop()
    active.data_logger = base.aloop.create_task(active.log_data_task())
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_finish_join_drain_close_chain(tmp_path, monkeypatch):
    """The ce846da1 chain: data enqueued right before finish must land in
    the .hlo BEFORE the handle closes; afterwards every handle is closed,
    data_logger is cancelled, the final -act.yml exists, move_dir was
    scheduled (non-manual), and the active moved to history."""
    moved = []

    async def fake_move_dir(action, base=None):
        moved.append(action.action_uuid)

    monkeypatch.setattr(native_finalizer_mod, "move_dir", fake_move_dir)
    base, active, dflt = _grafted_active(tmp_path)
    await _start_logger(base, active)

    await active.enqueue_data(
        DataModel(data={dflt: {"t_s": 1, "value": 2.0}}, errors=[])
    )
    # enqueue WITHOUT yielding to the drain loop: finish must wait for it
    active.enqueue_data_nowait(
        DataModel(data={dflt: {"t_s": 2, "value": 3.0}}, errors=[])
    )
    result = await active.finish()
    await asyncio.sleep(0.1)  # let the fire-and-forget move_dir task run

    assert result is active.action
    out_dir = os.path.join(
        str(base.helaodirs.save_root), str(active.action.action_output_dir)
    )
    hlo = [f for f in os.listdir(out_dir) if f.endswith(".hlo")]
    text = open(os.path.join(out_dir, hlo[0]), encoding="utf-8").read()
    # hlo_json_dumps compact separators (no spaces)
    assert '{"t_s":2,"value":3.0}' in text  # late row landed before close
    assert active.file_conn_dict == {}  # close-all cleared the dict
    assert active.data_logger is not None
    assert active.data_logger.cancelled() or active.data_logger.done()
    assert [f for f in os.listdir(out_dir) if f.endswith("-act.yml")]
    assert moved == [active.action.action_uuid]
    assert active.action.action_uuid not in base.actives
    assert active.action.action_uuid in base.history
    assert len(base.data_q.subscribers) == 0  # no leaked subscription


@pytest.mark.asyncio
async def test_finish_exports_global_params(tmp_path, monkeypatch):
    calls = []

    async def fake_dispatch(**kwargs):
        calls.append(kwargs)
        return {}, ErrorCodes.none

    async def fake_move_dir(action, base=None):
        pass

    monkeypatch.setattr(native_finalizer_mod, "async_private_dispatcher", fake_dispatch)
    monkeypatch.setattr(native_finalizer_mod, "move_dir", fake_move_dir)
    base, active, _ = _grafted_active(tmp_path)
    await _start_logger(base, active)
    active.action.to_global_params = ["gain"]
    active.action.action_params = {"gain": 7}
    await active.finish()
    assert calls and calls[0]["private_action"] == "update_global_params"
    assert calls[0]["json_dict"] == {"gain": 7}

    # empty resolution => RPC skipped (the estop-interrupt guard)
    calls.clear()
    base2, active2, _ = _grafted_active(tmp_path / "b")
    await _start_logger(base2, active2)
    active2.action.to_global_params = ["missing_key"]
    await active2.finish()
    assert calls == []


@pytest.mark.asyncio
async def test_substitute_closes_open_streams(tmp_path):
    base, active, dflt = _grafted_active(tmp_path)
    await _start_logger(base, active)
    await active.enqueue_data(DataModel(data={dflt: {"t_s": 1}}, errors=[]))
    await asyncio.sleep(0.1)
    assert active.file_conn_dict[dflt].file is not None
    await active.action_finalizer.substitute()  # ActionSession has no substitute
    # aiofiles handle closed: writing now raises ValueError on closed file
    with pytest.raises(ValueError):
        await active.file_conn_dict[dflt].file.write("x")
    assert active.data_logger is not None
    active.data_logger.cancel()
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_split_forks_conns_and_resets_counters(tmp_path, monkeypatch):
    async def fake_move_dir(action, base=None):
        pass

    monkeypatch.setattr(native_finalizer_mod, "move_dir", fake_move_dir)
    base, active, dflt = _grafted_active(tmp_path)
    await _start_logger(base, active)
    await active.enqueue_data(DataModel(data={dflt: {"t_s": 1}}, errors=[]))
    await asyncio.sleep(0.1)
    prev_uuid = active.action.action_uuid
    new_keys = await active.split(uuid_list=[])  # keep prior open
    assert len(new_keys) == 1
    assert active.action.action_uuid != prev_uuid
    assert active.action.action_split == 1
    assert prev_uuid not in active.listen_uuids
    assert active.action.action_uuid in active.listen_uuids
    assert active.num_data_queued == 0 and active.num_data_written == 0
    assert active.action.parent_action_uuid == prev_uuid
    assert active.data_logger is not None
    active.data_logger.cancel()
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_split_keep_active_then_finish_all_finishes_the_chain(
    tmp_path, monkeypatch
):
    """Moved from unit_test_active_finalizer (split_keep_active_then_finish_all):
    split(uuid_list=[]) forks a child with fresh file conns and marks the
    parent split but leaves it open; finish_all then finishes both, and a row
    streamed to the child's new conn lands on disk."""

    async def fake_move_dir(action, base=None):
        pass

    monkeypatch.setattr(native_finalizer_mod, "move_dir", fake_move_dir)
    base, active, dflt = _grafted_active(tmp_path)
    await _start_logger(base, active)
    await active.enqueue_data(DataModel(data={dflt: {"t_s": 0}}, errors=[]))
    await asyncio.sleep(0.1)
    parent_uuid = active.action.action_uuid

    new_keys = await active.split(uuid_list=[])
    assert active.action.action_uuid != parent_uuid
    assert len(active.action_list) == 2
    parent = active.action_list[1]
    assert parent.action_uuid == parent_uuid
    assert HloStatus.split in parent.action_status
    assert HloStatus.finished not in parent.action_status
    assert new_keys and all(k in active.file_conn_dict for k in new_keys)

    await active.enqueue_data(DataModel(data={new_keys[0]: {"t_s": 999}}, errors=[]))
    await asyncio.sleep(0.1)
    await active.action_finalizer.finish_all()  # ActionSession has no finish_all
    await asyncio.sleep(0.1)
    assert all(HloStatus.finished in a.action_status for a in active.action_list)
    rows = []
    for dirpath, _dirs, files in os.walk(str(base.helaodirs.save_root)):
        for fn in files:
            if fn.endswith(".hlo"):
                rows += (
                    open(os.path.join(dirpath, fn), encoding="utf-8")
                    .read()
                    .split("%%\n", 1)[1]
                    .splitlines()
                )
    assert '{"t_s":999}' in rows


@pytest.mark.asyncio
async def test_manual_action_calls_move_dir_and_writes_exp_seq(tmp_path, monkeypatch):
    """A manual action must still reach ``move_dir`` -- that is where the
    producing server evicts its own journal entry (plan A34, D-C). The
    finalizer used to skip it, which was correct only while ``move_dir``
    copied a tree. This test asserted ``moved == []`` and kept passing after
    the fix purely because ``move_dir`` is scheduled fire-and-forget and it
    never yielded to the loop; the drain below is what makes it falsifiable.
    The eviction itself is asserted at rest in
    ``helao/core/tests/test_run_state_wiring.py``."""
    moved = []

    async def fake_move_dir(action, base=None):
        moved.append(action.action_uuid)

    monkeypatch.setattr(native_finalizer_mod, "move_dir", fake_move_dir)
    base, active, dflt = _grafted_active(
        tmp_path, manual_action=True, run_type="manual", save_act=True
    )
    await _start_logger(base, active)
    await active.finish()
    await asyncio.sleep(0.1)  # let the fire-and-forget move_dir task run
    assert moved == [active.action.action_uuid]
    from helao.core.models.run_dir import RunDir

    diag_root = str(base.helaodirs.save_root).replace(
        RunDir.ACTIVE.value, RunDir.DIAG.value
    )
    exp_dir = os.path.join(diag_root, str(active.action.get_experiment_dir()))
    seq_dir = os.path.join(diag_root, str(active.action.get_sequence_dir()))
    assert [f for f in os.listdir(exp_dir) if f.endswith("-exp.yml")]
    assert [f for f in os.listdir(seq_dir) if f.endswith("-seq.yml")]
