"""NativeArtifactStoreAdapter (P2b-1): ArtifactStorePort implemented over
the native collaborator bodies. Conformance + factory members
(meta_writer_for / collaborators_for / bind_base) + keep-callable
move_dir/zip_dir mapping ({} rejection sentinel, same as the legacy
adapter's documented drift note)."""

import os

import pytest

from helao.hexagon.adapters.errors import UnwiredPortError
from helao.hexagon.adapters.native.artifact_store import NativeArtifactStoreAdapter
from helao.hexagon.adapters.native.data_file import NativeDataFileWriter
from helao.hexagon.adapters.native.data_stream import NativeDataStreamer
from helao.hexagon.adapters.native.finalizer import NativeActionFinalizer
from helao.hexagon.adapters.native.meta_writer import NativeMetaFileWriter
from helao.hexagon.ports.artifact_store import ArtifactStorePort
from helao.hexagon.tests.native_fixtures import make_base, mk_active


def _store():
    # config/clock are only stored (native bodies read state off base/active
    # at call time); construction must not need a live Base
    return NativeArtifactStoreAdapter(config=None, clock=None)


def test_port_conformance_and_no_base_inheritance():
    from helao.core.servers.base import Base

    store = _store()
    assert isinstance(store, ArtifactStorePort)  # runtime_checkable Protocol
    assert not isinstance(store, Base)


def test_factory_members(tmp_path):
    store = _store()
    base = make_base(str(tmp_path))
    mw = store.meta_writer_for(base)
    assert isinstance(mw, NativeMetaFileWriter) and mw.base is base
    active, _ = mk_active(base)
    streamer, file_writer, finalizer = store.collaborators_for(active)
    assert isinstance(streamer, NativeDataStreamer) and streamer.active is active
    assert (
        isinstance(file_writer, NativeDataFileWriter) and file_writer.active is active
    )
    assert isinstance(finalizer, NativeActionFinalizer) and finalizer.active is active


@pytest.mark.asyncio
async def test_meta_members_require_bound_base(tmp_path):
    store = _store()
    base = make_base(str(tmp_path / "RUNS_ACTIVE"))
    active, _ = mk_active(base)
    with pytest.raises(UnwiredPortError):
        await store.write_act(active.action)
    store.bind_base(base)
    base.meta_writer = store.meta_writer_for(base)  # type: ignore[reportAttributeAccessIssue]
    active.action.save_act = True
    await store.write_act(active.action)
    out_dir = os.path.join(
        str(base.helaodirs.save_root), str(active.action.action_output_dir)
    )
    assert [f for f in os.listdir(out_dir) if f.endswith("-act.yml")]


@pytest.mark.asyncio
async def test_stream_members_require_active_handle(tmp_path):
    store = _store()
    base = make_base(str(tmp_path / "RUNS_ACTIVE"))
    active, dflt = mk_active(base)
    with pytest.raises(UnwiredPortError):
        await store.write_one_shot(active.action, "x", "t", "f.csv", None)
    streamer, file_writer, finalizer = store.collaborators_for(active)
    active.data_stream = streamer  # type: ignore[reportAttributeAccessIssue]
    active.data_file_writer = file_writer  # type: ignore[reportAttributeAccessIssue]
    active.action_finalizer = finalizer  # type: ignore[reportAttributeAccessIssue]
    bound = store.for_action(active)
    path = await bound.write_one_shot(active.action, "row", "aux__csv", "os.csv", "h")
    assert path is not None and open(path).read() == "h\n%%\nrow"
    # write_data_line feeds the data_q (native enqueue re-body)
    await bound.write_data_line(active.action, dflt, {"t_s": 1})
    assert active.num_data_queued == 1
    await bound.close_streams(active.action)  # substitute: no open files -> no-op


@pytest.mark.asyncio
async def test_move_dir_sentinel_mapping(tmp_path):
    from types import SimpleNamespace

    store = _store()
    base = make_base(str(tmp_path / "RUNS_ACTIVE"))
    store.bind_base(base)
    # unsupported hobj type (has manual_action so move_dir reaches the
    # `match obj_type` branch) -> legacy move_dir returns {} -> port False
    unsupported = SimpleNamespace(manual_action=False)
    assert await store.move_dir(unsupported) is False


@pytest.mark.asyncio
async def test_zip_dir_maps_to_helper(tmp_path):
    store = _store()
    d = tmp_path / "seqdir"
    d.mkdir()
    (d / "a.txt").write_text("x")
    out = await store.zip_dir(d)
    assert out.suffix == ".zip" and out.exists()
