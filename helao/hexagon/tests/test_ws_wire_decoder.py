"""Wire codec: real frames round-trip, hostile/oversize/malformed are skipped."""

import asyncio
import datetime
import pathlib
import uuid

import msgspec
import numpy as np
import pyzstd
import pytest

from harness import ws_frames as wf
from helao.core.error import ErrorCodes
from helao.core.models.action import ActionModel
from helao.core.models.data import DataModel, DataPackageModel
from helao.core.models.hlostatus import HloStatus
from helao.helpers import ws_utils
from helao.helpers.ws_utils import WireDecodeError, wire_dumps, wire_loads


def _frame(tag, payload) -> bytes:
    return pyzstd.compress(msgspec.msgpack.encode([tag, payload]))


def test_real_payloads_roundtrip():
    am = ActionModel(
        action_name="x",
        action_uuid=uuid.uuid4(),
        action_output_dir=pathlib.Path("/tmp/x"),
        error_code=ErrorCodes.none,
        action_params={"f": np.float64(2.5), "a": np.arange(4)},
    )
    out = wire_loads(wire_dumps(am))
    assert isinstance(out, ActionModel) and out.error_code == ErrorCodes.none
    assert out.action_uuid == am.action_uuid and isinstance(out.action_uuid, uuid.UUID)
    assert out.action_output_dir == pathlib.Path("/tmp/x")
    assert out.action_params["a"] == [0, 1, 2, 3]  # ndarray travels as a list
    assert out.action_params["f"] == 2.5 and type(out.action_params["f"]) is float


def test_nested_datapackage_roundtrip():
    key = uuid.uuid4()
    pkg = DataPackageModel(
        action_uuid=uuid.uuid4(),
        action_name="a",
        datamodel=DataModel(
            data={key: {"v": [1.0, 2.0], "s": ["a", "b"]}}, status=HloStatus.active
        ),
    )
    out = wire_loads(wire_dumps(pkg))
    assert isinstance(out, DataPackageModel) and out.action_uuid == pkg.action_uuid
    assert out.datamodel.status is HloStatus.active
    assert out.datamodel.data == {key: {"v": [1.0, 2.0], "s": ["a", "b"]}}
    assert isinstance(next(iter(out.datamodel.data)), uuid.UUID)


def test_plain_payload_types():
    """Untagged payloads: what msgspec gives back (documented, not hidden)."""
    uid = uuid.uuid4()
    aware = datetime.datetime.now(datetime.timezone.utc)
    out = wire_loads(
        wire_dumps(
            {
                "t": (1, 2),
                "e": HloStatus.active,
                "u": uid,
                "dt": aware,
                "arr": np.arange(3),
                "np": np.int32(3),
                "p": pathlib.PurePosixPath("/a/b"),
            }
        )
    )
    assert out["t"] == [1, 2]
    assert out["e"] == HloStatus.active.value
    assert out["u"] == str(uid)  # msgspec encodes UUID natively as str
    assert out["dt"] == aware  # tz-aware datetime is a native msgpack timestamp
    assert out["arr"] == [0, 1, 2] and out["np"] == 3 and out["p"] == "/a/b"
    assert wire_loads(wire_dumps("raw")) == "raw"


def test_unencodable_raises():
    with pytest.raises(Exception):
        wire_dumps({"x": object()})


def test_oversize_and_ratio_rejected(monkeypatch):
    monkeypatch.setattr(ws_utils, "MAX_DECOMPRESSED_BYTES", 1000)
    with pytest.raises(WireDecodeError):
        wire_loads(_frame(None, "x" * 5000))
    monkeypatch.undo()
    ratio = _frame(None, b"\x00" * (4 * 1024 * 1024))
    with pytest.raises(WireDecodeError):
        wire_loads(ratio)


def test_text_frame_rejected():
    with pytest.raises(WireDecodeError):
        wire_loads("not bytes")


@pytest.mark.parametrize(
    "tag",
    [
        "os:system",
        "helao.core.models.credentials:Credentials",
        "helao.core.models.action:ActionModel.__init__",  # dotted qualname
        "helao.core.models.action:Missing",
        "helao.core.models.action:BaseModel",  # imported, not defined there
        "helao.core.models.action:",
        "no-colon",
        "helao.core.error:ErrorCodes",  # allowed module, not a BaseModel
        "helao.hexagon.domain.models:Spacingmethod",
        "helao.core.models.nonexistent_zz:X",
        7,
    ],
)
def test_disallowed_tag_rejected(tag):
    with pytest.raises(WireDecodeError):
        wire_loads(_frame(tag, {}))


def test_disallowed_module_is_never_imported(monkeypatch):
    import importlib

    calls = []
    real = importlib.import_module
    monkeypatch.setattr(
        importlib, "import_module", lambda n, *a: calls.append(n) or real(n, *a)
    )
    with pytest.raises(WireDecodeError):
        wire_loads(_frame("subprocess:Popen", {}))
    assert calls == []


@pytest.mark.parametrize(
    "env",
    [[], [None], [None, 1, 2], {"a": 1}, "x", 5],
)
def test_malformed_envelope_rejected(env):
    with pytest.raises(WireDecodeError):
        wire_loads(pyzstd.compress(msgspec.msgpack.encode(env)))


def test_garbage_and_validation_failure_rejected():
    with pytest.raises(WireDecodeError):
        wire_loads(pyzstd.compress(b"\xc1\xc1"))  # invalid msgpack byte
    with pytest.raises(WireDecodeError):
        wire_loads(b"not zstd")
    with pytest.raises(WireDecodeError):
        wire_loads(
            _frame("helao.core.models.action:ActionModel", {"action_uuid": "nope"})
        )


@pytest.mark.asyncio
async def test_subscriber_skips_hostile_frame_without_reconnect():
    benign = await wf.frame("ws_live", "base_api")
    bad = _frame("os:system", {})
    async with wf.replay_server({"p": [bad, benign]}) as (h, p):
        got = await wf.decode_via_wssubscriber(h, p, "p", count=1)
        await asyncio.sleep(1.5)  # a reconnect would replay and duplicate
        sub = ws_utils.WsSubscriber(h, p, "p")
        await asyncio.sleep(1.0)
        extra = await sub.read_messages()
        sub.subscriber_task.cancel()
    assert len(got) == 1 and wf.LIVE_FLOAT_LABEL in got[0]
    assert len(extra) == 1  # exactly one benign frame; hostile one skipped
