"""Restricted wire decoder: real frames round-trip, hostile/oversize are skipped."""

import asyncio
import datetime
import os
import pathlib
import pickle
import uuid

import numpy as np
import pyzstd
import pytest

from harness import ws_frames as wf
from helao.core.error import ErrorCodes
from helao.core.models.action import ActionModel
from helao.helpers import ws_utils
from helao.helpers.ws_utils import WireDecodeError, wire_loads


def _frame(obj) -> bytes:
    return pyzstd.compress(pickle.dumps(obj))


class _Evil:
    def __init__(self, marker):
        self.marker = marker

    def __reduce__(self):
        return (os.system, (f"touch {self.marker}",))


def test_real_payloads_roundtrip():
    uid = uuid.uuid4()
    am = ActionModel(
        action_name="x",
        action_output_dir=pathlib.Path("/tmp/x"),
        error_code=ErrorCodes.none,
        action_params={
            "f": np.float64(2.5),
            "a": np.arange(4),
            "t": datetime.timedelta(1),
        },
    )
    out = wire_loads(_frame(am))
    assert isinstance(out, ActionModel) and out.error_code == ErrorCodes.none
    assert np.array_equal(out.action_params["a"], np.arange(4))
    assert out.action_params["f"] == 2.5
    from helao.deploy.hte.drivers.pstat.biologic.enum import EC_IRange
    from helao.hexagon.domain.models import Spacingmethod

    enums = {"r": list(EC_IRange)[0], "s": list(Spacingmethod)[0]}
    assert wire_loads(_frame(enums)) == enums
    assert wire_loads(_frame(np.array([{"a": 1}], dtype=object)))[0] == {"a": 1}
    assert wire_loads(_frame({"big": np.arange(100, dtype=np.float32)}))[
        "big"
    ].shape == (100,)
    live = {uid: ("v", 1.0), "k": (np.int32(3), 2.0)}
    assert wire_loads(_frame(live)) == live


def test_windows_path_decodes_on_any_host():
    # protocol 2 GLOBAL is newline-terminated, so the class name can be swapped
    # for the concrete class a Windows peer would send
    raw = pickle.dumps(pathlib.PureWindowsPath("c:/a/b"), protocol=2)
    assert b"PureWindowsPath\n" in raw
    out = wire_loads(pyzstd.compress(raw.replace(b"PureWindowsPath", b"WindowsPath")))
    assert isinstance(out, pathlib.PureWindowsPath) and out.name == "b"


def test_hostile_and_oversize_rejected(tmp_path, monkeypatch):
    marker = tmp_path / "pwned"
    with pytest.raises(WireDecodeError):
        wire_loads(_frame(_Evil(marker)))
    assert not marker.exists()
    dotted = b"\x80\x04\x8c\x10helao.core.error\x94\x8c\x0cEnum.__new__\x94\x93."
    with pytest.raises(WireDecodeError):
        wire_loads(pyzstd.compress(dotted))
    monkeypatch.setattr(ws_utils, "MAX_DECOMPRESSED_BYTES", 1000)
    with pytest.raises(WireDecodeError):
        wire_loads(_frame(b"x" * 5000))


@pytest.mark.asyncio
async def test_subscriber_skips_hostile_frame_without_reconnect(tmp_path):
    marker = tmp_path / "pwned"
    benign = await wf.frame("ws_live", "base_api")
    async with wf.replay_server({"p": [_frame(_Evil(marker)), benign]}) as (h, p):
        got = await wf.decode_via_wssubscriber(h, p, "p", count=1)
        await asyncio.sleep(1.5)  # a reconnect would replay and duplicate
        sub = ws_utils.WsSubscriber(h, p, "p")
        await asyncio.sleep(1.0)
        extra = await sub.read_messages()
        sub.subscriber_task.cancel()
    assert not marker.exists()
    assert len(got) == 1 and wf.LIVE_FLOAT_LABEL in got[0]
    assert len(extra) == 1  # exactly one benign frame; hostile one skipped


class _Reduce:
    def __init__(self, func, args):
        self.func, self.args = func, args

    def __reduce__(self):
        return self.func, self.args


def test_build_on_allowed_classes_cannot_poison_them():
    from helao.core.error import ErrorCodes

    before = dict(pathlib.PosixPath.__dict__), dict(ErrorCodes.__dict__)
    # GLOBAL cls; MARK None (MARK DICT SETITEM) TUPLE; BUILD  => setattr(cls, ...)
    for mod, name in (("pathlib", "PosixPath"), ("helao.core.error", "ErrorCodes")):
        payload = f"c{mod}\n{name}\n(N(dV_str\nV/x\nstb.".encode()
        try:
            wire_loads(pyzstd.compress(payload))
        except WireDecodeError:
            pass
    assert (dict(pathlib.PosixPath.__dict__), dict(ErrorCodes.__dict__)) == before
    assert str(pathlib.Path("/a/b")) == "/a/b"


@pytest.mark.parametrize(
    "obj",
    [
        _Reduce(set, (range(3_000_000),)),
        _Reduce(bytearray, (200 * 1024 * 1024,)),
        _Reduce(np.ndarray, ((20_000_000,), np.dtype("O"))),
        _Reduce(
            np._core.multiarray._reconstruct,  # type: ignore[attr-defined]
            (np.ndarray, (20_000_000,), b"O"),
        ),
    ],
    ids=["set-range", "bytearray", "ndarray-direct", "reconstruct-big-shape"],
)
def test_dos_payloads_rejected(obj):
    with pytest.raises(WireDecodeError):
        wire_loads(pyzstd.compress(pickle.dumps(obj)))


def test_unloaded_module_is_never_imported(tmp_path, monkeypatch):
    import helao.deploy as deploy_pkg

    pkg = tmp_path / "zz_wire_probe"
    pkg.mkdir()
    marker = tmp_path / "ran"
    (pkg / "boom.py").write_text(f"open({str(marker)!r}, 'w').close()\nexit(3)\n")
    monkeypatch.setattr(deploy_pkg, "__path__", [*deploy_pkg.__path__, str(tmp_path)])
    payload = b"chelao.deploy.zz_wire_probe.boom\nThing\n(Vraw\ntR."
    assert wire_loads(pyzstd.compress(payload)) == "raw"  # raw enum value
    assert not marker.exists()
    assert "helao.deploy.zz_wire_probe.boom" not in __import__("sys").modules


def test_enum_member_build_poisoning_rejected_and_undone():
    from helao.core.error import ErrorCodes

    val = ErrorCodes.none.value
    payload = (
        f"chelao.core.error\nErrorCodes\n(V{val}\ntR(N(dV_value_\nVpwned\nstb.".encode()
    )
    with pytest.raises(WireDecodeError):
        wire_loads(pyzstd.compress(payload))
    assert ErrorCodes.none.value == val


def test_memo_bomb_and_ratio_bomb_rejected():
    bomb = b"\x80\x05N\x94]\x94(" + b"h\x00" * 10_000_000 + b"e."  # BINGET 0 x10M
    frame = pyzstd.compress(bomb)
    assert len(bomb) > ws_utils.MAX_DECOMPRESSED_BYTES
    with pytest.raises(WireDecodeError):
        wire_loads(frame)
    ratio = pyzstd.compress(b"\x80\x05" + b"N" * (4 * 1024 * 1024) + b".")
    with pytest.raises(WireDecodeError):
        wire_loads(ratio)


def test_text_frame_rejected():
    with pytest.raises(WireDecodeError):
        wire_loads("not bytes")


def test_poisoned_member_restored_when_load_fails():
    from helao.core.error import ErrorCodes

    val = ErrorCodes.none.value
    # poison via BUILD, then fail on an unknown opcode
    payload = (
        f"chelao.core.error\nErrorCodes\n(V{val}\ntR(N(dV_value_\nVpwned\nstb.".encode()
    )
    payload = payload[:-1] + b"\xff"
    with pytest.raises(WireDecodeError):
        wire_loads(pyzstd.compress(payload))
    assert ErrorCodes.none.value == val


class _Poison:
    def __init__(self, cls, val, state):
        self.cls, self.val, self.state = cls, val, state

    def __reduce__(self):
        return self.cls, (self.val,), self.state


def test_ndarray_poisoned_member_rejected_and_restored():
    from helao.core.error import ErrorCodes

    val = ErrorCodes.none.value
    state = (None, {"_value_": np.array([1, 2])})
    frame = pyzstd.compress(pickle.dumps(_Poison(ErrorCodes, val, state)))
    with pytest.raises(WireDecodeError):
        wire_loads(frame)
    assert ErrorCodes.none.value == val


def test_module_getattr_hook_not_triggered(monkeypatch):
    import sys
    import types

    calls = []
    mod = types.ModuleType("helao.zz_lazy")
    setattr(mod, "__getattr__", lambda n: calls.append(n))
    monkeypatch.setitem(sys.modules, "helao.zz_lazy", mod)
    with pytest.raises(WireDecodeError):
        wire_loads(pyzstd.compress(b"chelao.zz_lazy\nMissing\n."))
    assert calls == []
