"""ArtifactStore + DataSink adapters: Protocol conformance + verbatim
delegation onto recording stubs (real-Base/Active integration is exercised
by the Task 12 smoke through the launched group)."""

import asyncio

import pytest

from helao.hexagon.adapters.errors import UnwiredPortError
from helao.hexagon.adapters.legacy.artifact_store import LegacyArtifactStoreAdapter
from helao.hexagon.adapters.legacy.data_sink import ActiveDataSinkAdapter
from helao.hexagon.ports.artifact_store import ArtifactStorePort
from helao.hexagon.ports.data_sink import DataSinkPort


class _Rec:
    """Attribute-recording stand-in: every method records (name, args, kwargs)."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def _record(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            if name in ("split",):
                return []
            return f"<{name}>"

        return _record


class _AsyncRec(_Rec):
    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        async def _record(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            if name in ("split",):
                return []
            return f"<{name}>"

        return _record


class _StubActive(_AsyncRec):
    def __init__(self):
        super().__init__()
        self.base = _Rec()  # sync members: put_lbuf_nowait / get_lbuf / ...

    # sync-on-Active members the adapter must NOT await
    def enqueue_data_nowait(self, datamodel, action=None):
        self.calls.append(("enqueue_data_nowait", (datamodel, action), {}))

    def get_realtime_nowait(self, epoch_ns=None, offset=None):
        self.calls.append(("get_realtime_nowait", (epoch_ns, offset), {}))
        return 123

    def finish_hlo_header(self, file_conn_keys=None, realtime=None):
        self.calls.append(("finish_hlo_header", (file_conn_keys, realtime), {}))

    def write_file_nowait(self, *args, **kwargs):
        self.calls.append(("write_file_nowait", args, kwargs))
        return kwargs.get("filename")

    def set_estop(self, action=None):
        self.calls.append(("set_estop", (action,), {}))


def test_conformance():
    active = _StubActive()
    assert isinstance(ActiveDataSinkAdapter(active), DataSinkPort)
    assert isinstance(LegacyArtifactStoreAdapter(base=_AsyncRec()), ArtifactStorePort)


@pytest.mark.asyncio
async def test_data_sink_delegates_verbatim():
    active = _StubActive()
    sink = ActiveDataSinkAdapter(active)
    await sink.enqueue_data("dm")  # type: ignore[reportArgumentType]
    sink.enqueue_data_nowait("dm2")  # type: ignore[reportArgumentType]
    assert sink.get_realtime_nowait() == 123
    await sink.finish_hlo_header(file_conn_keys=None, realtime=9)
    sink.write_file_nowait("s", "t", filename="f.csv")
    sink.set_estop()
    await sink.append_sample(["smp"], IO="in")
    assert await sink.split() == []
    names = [c[0] for c in active.calls]
    assert names == [
        "enqueue_data",
        "enqueue_data_nowait",
        "get_realtime_nowait",
        "finish_hlo_header",
        "write_file_nowait",
        "set_estop",
        "append_sample",
        "split",
    ]


@pytest.mark.asyncio
async def test_data_sink_lbuf_routes_via_base():
    active = _StubActive()
    sink = ActiveDataSinkAdapter(active)
    sink.put_lbuf_nowait({"k": 1})
    sink.get_lbuf("k")
    assert [c[0] for c in active.base.calls] == ["put_lbuf_nowait", "get_lbuf"]


@pytest.mark.asyncio
async def test_artifact_store_meta_and_promotion_delegate():
    base = _AsyncRec()
    store = LegacyArtifactStoreAdapter(base=base)
    await store.write_act("A")  # type: ignore[reportArgumentType]
    await store.write_exp("E")  # type: ignore[reportArgumentType]
    await store.write_seq("S")  # type: ignore[reportArgumentType]
    assert [c[0] for c in base.calls] == ["write_act", "write_exp", "write_seq"]


@pytest.mark.asyncio
async def test_artifact_store_stream_members_require_bound_active():
    store = LegacyArtifactStoreAdapter(base=_AsyncRec())
    with pytest.raises(UnwiredPortError):
        await store.write_one_shot("A", "data", "csv__file", "f.csv", None)  # type: ignore[reportArgumentType]
    with pytest.raises(UnwiredPortError):
        await store.finish("A")  # type: ignore[reportArgumentType]


@pytest.mark.asyncio
async def test_artifact_store_bound_active_delegates():
    base, active = _AsyncRec(), _StubActive()
    store = LegacyArtifactStoreAdapter(base=base).for_action(active)
    await store.write_one_shot("A", "data", "csv__file", "f.csv", "h")  # type: ignore[reportArgumentType]
    await store.close_streams("A")  # type: ignore[reportArgumentType]  # -> Active.substitute (close-every-hlo)
    await store.finish("A")  # type: ignore[reportArgumentType]  # -> Active.finish (join-drain-close)
    names = [c[0] for c in active.calls]
    assert names == ["write_file", "substitute", "finish"]
