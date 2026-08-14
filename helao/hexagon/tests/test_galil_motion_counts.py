"""``NativeGalilMotion`` counts-domain moves and dual-unit reads (T-I1).

The commanded value is what these tests exist to protect. ``_motor_move``'s
new ``units="counts"`` branch must hand the caller's integer to ``PR``/``PA``
untouched -- no ``count_to_mm`` division, no second application of the
axis->letter map -- and the mm path must stay byte-identical to what shipped.

This runs in CI on Linux because the only vendor seam is
``GalilCommandChannel``: a fake channel records the exact command strings the
driver emits, so the whole branch is observable without ``gclib``. The
assertions are on the *emitted commands*, never on the return code -- the
per-axis ``except Exception`` in ``_motor_move`` turns any fault into
``ErrorCodes.numerical``, which would mask a broken branch behind a plausible
error value.

Each move drives the real settle-poll, which sleeps 0.5 s once before reading
the (already "stopped") ``SC`` code, so each move test costs about half a
second of wall clock.
"""

import asyncio
import re
from typing import Optional

import numpy as np
import pytest

from helao.core.error import ErrorCodes
from helao.hexagon.adapters.native.galil_motion_native import NativeGalilMotion

# adss MOTOR's B-axis scale, copied from the tracked hte config. Kept as a
# literal so a station recalibration cannot silently retune this regression
# witness: at this scale a 7-count move expressed in mm and converted back
# floors to 6, which is the count the mm path would have delivered.
ADSS_B_COUNT_TO_MM = 0.00015627999999717445


class FakeChannel:
    """Records commands; returns programmed responses (default '0')."""

    def __init__(self, responses: Optional[dict] = None):
        self.commands: list = []
        self.opened: Optional[str] = None
        self.closed = False
        self._responses = responses or {}

    def open(self, connection_string: str) -> None:
        self.opened = connection_string

    def command(self, cmd: str) -> str:
        self.commands.append(cmd)
        r = self._responses.get(cmd, "0")
        if isinstance(r, list):
            return r.pop(0)
        return r

    def info(self) -> str:
        return "fake-info"

    def version(self) -> str:
        return "fake-1.0"

    def close(self) -> None:
        self.closed = True


# Single axis deliberately mapped x -> "C", not "A": if the axis->letter map
# were applied twice (or not at all) the emitted letter would differ, so the
# letter itself is the assertion.
MOVE_CFG = {
    "axis_id": {"x": "C"},
    "galil_ip_str": "10.0.0.1",
    "count_to_mm": {"C": ADSS_B_COUNT_TO_MM},
    "def_speed_count_sec": 10000,
    "max_speed_count_sec": 25000,
}


# The controller reports every axis it has, so a three-axis controller with
# only "C" configured is what exercises the axis->letter map: TP/PA/SC all
# answer with three fields, and the driver has to pick the third.
PA_QUERY = "PA ?,?,?"


def _responses(extra=None):
    # SC "1" per axis == stopped, so the settle-poll breaks on its first read
    base = {"MG _MOC": "0", "TP": "0, 0, 0", PA_QUERY: "0, 0, 0", "SC": "1, 1, 1"}
    base.update(extra or {})
    return base


def _connected(config=None, responses=None):
    ch = FakeChannel(responses=responses or _responses())
    d = NativeGalilMotion(config or dict(MOVE_CFG), channel=ch)
    d.connect()
    ch.commands.clear()
    return d, ch


class _UnitsLike:
    """Stands in for Phase 1's ``Units`` str-enum member.

    The driver must select the counts branch from the member's ``value``, so
    that a real ``Units.counts`` and the bare string ``"counts"`` are the same
    instruction and no second enum has to be defined driver-side.
    """

    value = "counts"


# --------------------------------------------------------------------------
# _motor_move: the counts branch carries the commanded integer
# --------------------------------------------------------------------------
def test_counts_relative_move_emits_the_typed_integer():
    d, ch = _connected()
    out = asyncio.run(d._motor_move([7], ["x"], None, "relative", "motorxy", "counts"))
    assert "PRC=7" in ch.commands
    assert out["counts"] == [7]
    assert out["err_code"] == [ErrorCodes.none]


def test_the_same_move_in_mm_loses_a_count_to_the_division():
    """The B1 witness, both halves in one test.

    7 counts expressed in mm and converted back by the mm path floors to 6.
    That one-count loss is the whole reason the counts branch exists, so the
    two paths are asserted against each other rather than in isolation.
    """
    d, ch = _connected()
    asyncio.run(
        d._motor_move(
            [7 * ADSS_B_COUNT_TO_MM], ["x"], None, "relative", "motorxy", "mm"
        )
    )
    assert "PRC=6" in ch.commands  # mm round-trip: one count short
    assert "PRC=7" not in ch.commands

    d2, ch2 = _connected()
    asyncio.run(d2._motor_move([7], ["x"], None, "relative", "motorxy", "counts"))
    assert "PRC=7" in ch2.commands  # counts: exactly as typed


def test_counts_move_emits_the_exact_SP_PR_BG_sequence():
    d, ch = _connected()
    asyncio.run(d._motor_move([1234], ["x"], None, "relative", "motorxy", "counts"))
    # the position queries the poll issues are dropped ("PA ?,?,?" is a read,
    # not a move); what matters is the per-axis move triple and its order.
    move_cmds = [c for c in ch.commands if re.match(r"^(SP|PR|PA|BG)[A-H]", c)]
    assert move_cmds == ["SPC=10000", "PRC=1234", "BGC"]


def test_counts_absolute_move_uses_PA():
    d, ch = _connected()
    asyncio.run(d._motor_move([500], ["x"], None, "absolute", "motorxy", "counts"))
    assert "PAC=500" in ch.commands
    assert not any(c.startswith("PRC") for c in ch.commands)


def test_counts_move_needs_no_configured_scale():
    """A counts move performs no ``count_to_mm`` lookup at all.

    On an axis with no scale entry the mm path raises ``KeyError`` into the
    per-axis handler and returns ``ErrorCodes.numerical`` with no command
    emitted. The counts branch reaching the controller is therefore positive
    proof that it never touched the scale table.
    """
    cfg = dict(MOVE_CFG, count_to_mm={})
    d, ch = _connected(config=cfg)
    out = asyncio.run(d._motor_move([42], ["x"], None, "relative", "motorxy", "counts"))
    assert "PRC=42" in ch.commands
    assert out["err_code"] == [ErrorCodes.none]

    d2, ch2 = _connected(config=dict(MOVE_CFG, count_to_mm={}))
    out2 = asyncio.run(d2._motor_move([42], ["x"], None, "relative", "motorxy", "mm"))
    assert out2["err_code"] == [ErrorCodes.numerical]
    assert not any(c.startswith("PRC") for c in ch2.commands)


def test_counts_move_reports_zero_error_distance():
    d, _ = _connected()
    out = asyncio.run(d._motor_move([9], ["x"], None, "relative", "motorxy", "counts"))
    assert out["err_dist"] == [0.0]
    # the mm path still reports the floored remainder it always did
    d2, _ = _connected()
    out2 = asyncio.run(
        d2._motor_move(
            [7 * ADSS_B_COUNT_TO_MM], ["x"], None, "relative", "motorxy", "mm"
        )
    )
    assert out2["err_dist"][0] > 0.0


def test_units_enum_member_selects_the_counts_branch():
    d, ch = _connected()
    # type: ignore on purpose -- the declared contract is ``str`` (which a real
    # ``Units`` member satisfies), and this test deliberately passes something
    # outside it to prove the driver reads ``.value`` rather than requiring the
    # enum. See ``test_units_enum_member_...`` below for the in-contract case.
    asyncio.run(
        d._motor_move([11], ["x"], None, "relative", "motorxy", _UnitsLike())  # type: ignore[arg-type]
    )
    assert "PRC=11" in ch.commands


def test_the_shared_units_enum_drives_both_branches():
    """The real enum, not just a value-compatible stand-in.

    The driver stays free of a ``helao.core.servers`` import -- a hexagon
    adapter should not depend on the server layer to know what "counts"
    means -- so this is the test that proves the two halves actually agree.
    """
    from helao.ui.shared.motion_control import Units

    d, ch = _connected()
    asyncio.run(d._motor_move([13], ["x"], None, "relative", "motorxy", Units.counts))
    assert "PRC=13" in ch.commands

    d2, ch2 = _connected()
    asyncio.run(d2._motor_move([1.0], ["x"], None, "relative", "motorxy", Units.mm))
    assert f"PRC={int(np.floor(1.0 / ADSS_B_COUNT_TO_MM))}" in ch2.commands


def test_mm_remains_the_default_and_is_unchanged_by_the_new_parameter():
    """Existing call sites pass five positional arguments and must not move."""
    d_old, ch_old = _connected()
    asyncio.run(d_old._motor_move([1.0], ["x"], None, "absolute", "motorxy"))
    d_new, ch_new = _connected()
    asyncio.run(d_new._motor_move([1.0], ["x"], None, "absolute", "motorxy", "mm"))
    assert ch_old.commands == ch_new.commands
    expected = int(np.floor(1.0 / ADSS_B_COUNT_TO_MM))
    assert f"PAC={expected}" in ch_old.commands


def test_non_integral_counts_value_floors_and_warns(caplog):
    d, ch = _connected()
    with caplog.at_level("WARNING"):
        asyncio.run(d._motor_move([7.5], ["x"], None, "relative", "motorxy", "counts"))
    assert "PRC=7" in ch.commands
    assert any("non-integral count" in r.getMessage() for r in caplog.records)


def test_counts_move_is_refused_outside_the_motorxy_frame():
    """platexy/instrxy are mm arithmetic; a count through them is garbage."""
    for frame in ("platexy", "instrxy"):
        d, ch = _connected()
        out = asyncio.run(
            d._motor_move([100], ["x"], None, "relative", frame, "counts")
        )
        assert out["err_code"] == ErrorCodes.not_available
        assert ch.commands == []  # refused before any device call
        assert d.motor_busy is False  # and the busy flag is released


def test_no_move_path_ever_de_energizes_a_motor():
    """AC3: moving and stopping must never emit ``MO``."""
    d, ch = _connected()
    asyncio.run(d._motor_move([25], ["x"], None, "relative", "motorxy", "counts"))
    asyncio.run(d._motor_move([1.0], ["x"], None, "relative", "motorxy", "mm"))
    asyncio.run(d.stop_axis(["x"]))
    assert not any(c.startswith("MO") for c in ch.commands)
    assert "STC" in ch.commands  # stop_axis did reach the controller


# --------------------------------------------------------------------------
# query_axis_position_counts: one sample, two renderings
# --------------------------------------------------------------------------
def test_dual_read_returns_the_raw_count_and_its_mm_rendering():
    d, ch = _connected(responses=_responses({PA_QUERY: "0, 0, 1234"}))
    out = asyncio.run(d.query_axis_position_counts(["x"]))
    assert out["ax"] == ["x"]
    assert out["counts"] == [1234]
    assert out["position"] == [pytest.approx(1234 * ADSS_B_COUNT_TO_MM)]
    # one TP/PA exchange only -- never a second sample for the second unit
    assert ch.commands.count("TP") == 1
    assert ch.commands.count(PA_QUERY) == 1


def test_dual_read_renders_a_missing_scale_as_unknown_not_zero():
    """P8: ``None``, because 0.0 mm is a legitimate coordinate."""
    cfg = dict(MOVE_CFG, count_to_mm={})
    d, _ = _connected(config=cfg, responses=_responses({PA_QUERY: "0, 0, 555"}))
    out = asyncio.run(d.query_axis_position_counts(["x"]))
    assert out["counts"] == [555]
    assert out["position"] == [None]

    # and the pre-existing mm-only reader deliberately keeps its 0 default,
    # because 24 frozen action routes depend on its shape.
    d2, _ = _connected(
        config=dict(MOVE_CFG, count_to_mm={}),
        responses=_responses({PA_QUERY: "0, 0, 555"}),
    )
    legacy = asyncio.run(d2.query_axis_position(["x"]))
    assert legacy["position"] == [0.0]


def test_dual_read_reports_an_unconfigured_axis_as_unknown():
    d, _ = _connected(responses=_responses({PA_QUERY: "0, 0, 10"}))
    out = asyncio.run(d.query_axis_position_counts(["x", "z"]))
    assert out["ax"] == ["x", None]
    assert out["counts"][1] is None and out["position"][1] is None


def test_dual_read_on_a_disabled_controller_is_empty_not_zero():
    ch = FakeChannel(responses=_responses())
    d = NativeGalilMotion(dict(MOVE_CFG), channel=ch)  # never connected
    out = asyncio.run(d.query_axis_position_counts(["x"]))
    assert out == {"ax": [], "position": [], "counts": []}


def test_dual_read_does_not_feed_the_aligner_sink():
    """An on-demand engineering read is side-effect free."""

    class _Sink:
        def __init__(self):
            self.items: list = []

        async def put(self, msg):
            self.items.append(msg)

    sink = _Sink()
    ch = FakeChannel(responses=_responses({PA_QUERY: "0, 0, 77"}))
    d = NativeGalilMotion(dict(MOVE_CFG), channel=ch, position_sink=sink)
    d.connect()
    asyncio.run(d.query_axis_position_counts(["x"]))
    assert sink.items == []
    # the action-path query still does feed it
    asyncio.run(d.query_axis_position(["x"]))
    assert len(sink.items) == 1
