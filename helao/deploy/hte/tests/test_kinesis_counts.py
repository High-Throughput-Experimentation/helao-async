"""``KinesisMotor`` counts-domain moves and dual-unit reads (T-I2).

`pylablib` is installed in the `helao` environment but no Thorlabs stage is,
so `Thorlabs.KinesisMotor` is replaced with a recorder. That is enough to pin
the two things that carry real risk:

- a `units="counts"` move must reach `move_by`/`move_to` with `scale=False`,
  so pylablib applies no scaling and the typed integer is what the controller
  receives -- while the default `units="mm"` call stays exactly as it shipped;
- the dual-unit read must call `get_position` **once per axis, with
  `scale=False`**. The call count alone would be satisfied by a single
  `get_position(scale=True)`, which throws away the raw count the read exists
  to keep and reintroduces pylablib's internal division; the operand alone
  would be satisfied by two reads at two instants, which cannot describe one
  coordinate on a moving axis. Both assertions are needed.

`pos_scale` is **counts per mm**; mm per count is its reciprocal. The golden
value is the shipped MLJ150/M scale, 1/1228800.
"""

import pytest

from helao.deploy.hte.drivers.motion import kinesis_driver as kd
from helao.deploy.hte.drivers.motion.kinesis_driver import KinesisMotor, MoveModes

# MLJ150/M as shipped: 61 440 000 counts over 50 mm.
POS_SCALE = 1228800.0


class FakeKinesisMotor:
    """Recorder standing in for ``pylablib.devices.Thorlabs.KinesisMotor``."""

    def __init__(self, conn=None, scale=None, position: int = 0, status=()):
        self.conn = conn
        self.scale = scale
        self.position = position
        self._status = list(status)
        self.calls: list[tuple] = []

    def _record(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))

    def get_position(self, *args, **kwargs):
        self._record("get_position", *args, **kwargs)
        return self.position

    def get_status(self, *args, **kwargs):
        self._record("get_status", *args, **kwargs)
        return list(self._status)

    def move_by(self, *args, **kwargs):
        self._record("move_by", *args, **kwargs)

    def move_to(self, *args, **kwargs):
        self._record("move_to", *args, **kwargs)

    def stop(self, *args, **kwargs):
        self._record("stop", *args, **kwargs)

    def setup_velocity(self, *args, **kwargs):
        self._record("setup_velocity", *args, **kwargs)

    def close(self, *args, **kwargs):
        self._record("close", *args, **kwargs)

    def method_names(self) -> set:
        return {name for name, _, _ in self.calls}


class _UnitsLike:
    """Stands in for Phase 1's ``Units`` str-enum member (value-compatible)."""

    value = "counts"


def _cfg(**axis_overrides) -> dict:
    axis = {
        "serial_no": "45470574",
        "pos_scale": POS_SCALE,
        "vel_scale": 65970697.6,
        "acc_scale": 13518.2,
    }
    axis.update(axis_overrides)
    return {"axes": {"z": axis}}


@pytest.fixture
def make_driver(monkeypatch):
    """Build a ``KinesisMotor`` whose devices are recorders, not hardware."""
    built: dict = {}

    def _factory(conn=None, scale=None, **kw):
        motor = FakeKinesisMotor(conn=conn, scale=scale)
        built[conn] = motor
        return motor

    monkeypatch.setattr(kd.Thorlabs, "KinesisMotor", _factory)

    def _make(config=None, position=0, status=()):
        driver = KinesisMotor(config=config or _cfg())
        for motor in driver.motors.values():
            motor.position = position
            motor._status = list(status)
            motor.calls.clear()
        return driver

    return _make


# --------------------------------------------------------------------------
# move: the commanded value
# --------------------------------------------------------------------------
def test_counts_relative_move_is_handed_over_unscaled(make_driver):
    driver = make_driver()
    driver.move("z", MoveModes.relative, 7, units="counts")
    assert driver.motors["z"].calls == [("move_by", (7,), {"scale": False})]


def test_counts_absolute_move_is_handed_over_unscaled(make_driver):
    driver = make_driver()
    driver.move("z", MoveModes.absolute, 61440, units="counts")
    assert driver.motors["z"].calls == [("move_to", (61440,), {"scale": False})]


def test_mm_move_is_unchanged_by_the_new_parameter(make_driver):
    """The default must keep pylablib doing the scaling, exactly as before."""
    explicit = make_driver()
    explicit.move("z", MoveModes.relative, 1.5, units="mm")
    defaulted = make_driver()
    defaulted.move("z", MoveModes.relative, 1.5)
    assert explicit.motors["z"].calls == [("move_by", (1.5,), {})]
    assert defaulted.motors["z"].calls == explicit.motors["z"].calls


def test_units_enum_member_selects_the_counts_branch(make_driver):
    driver = make_driver()
    driver.move("z", MoveModes.relative, 12, units=_UnitsLike())
    assert driver.motors["z"].calls == [("move_by", (12,), {"scale": False})]


def test_the_shared_units_enum_drives_both_branches(make_driver):
    """The real enum, not just a value-compatible stand-in.

    The driver stays free of a ``helao.core.servers`` import, so this is the
    test that proves the two halves actually agree on what "counts" means.
    """
    from helao.core.servers.motion_control import Units

    counts = make_driver()
    counts.move("z", MoveModes.relative, 13, units=Units.counts)
    assert counts.motors["z"].calls == [("move_by", (13,), {"scale": False})]

    mm = make_driver()
    mm.move("z", MoveModes.relative, 1.5, units=Units.mm)
    assert mm.motors["z"].calls == [("move_by", (1.5,), {})]


# --------------------------------------------------------------------------
# query_axis_positions: one sample, two renderings
# --------------------------------------------------------------------------
def test_read_takes_exactly_one_unscaled_sample_per_axis(make_driver):
    driver = make_driver(position=61440)
    driver.query_axis_positions()
    reads = [c for c in driver.motors["z"].calls if c[0] == "get_position"]
    assert len(reads) == 1  # never two reads presented as one coordinate
    assert reads[0][2] == {"scale": False}  # and the raw count is what we kept


def test_read_renders_the_one_sample_as_both_units(make_driver):
    driver = make_driver(position=61440)
    state = driver.query_axis_positions()
    assert state["z"]["counts"] == 61440
    assert state["z"]["mm"] == pytest.approx(61440 / POS_SCALE, rel=1e-12)
    assert state["z"]["mm"] == pytest.approx(61440 * (1 / POS_SCALE), rel=1e-12)


def test_read_uses_the_reciprocal_not_the_raw_pos_scale(make_driver):
    """A dropped inversion would report 61440 counts as 7.5e10 mm."""
    driver = make_driver(position=61440)
    mm = driver.query_axis_positions()["z"]["mm"]
    assert mm == pytest.approx(0.05, rel=1e-9)
    assert mm != pytest.approx(61440 * POS_SCALE)


def test_missing_scale_reads_as_unknown_not_zero(make_driver):
    """P8: zero is a legitimate coordinate, so a missing scale is ``None``.

    Deliberately synthetic. ``connect()`` subscripts ``pos_scale`` directly,
    so an axis without one never opens a motor at all and no shipped config
    can reach this branch -- the scale is removed after construction to
    exercise it. It is a robustness path, not a station scenario.
    """
    driver = make_driver(position=123)
    del driver.config["axes"]["z"]["pos_scale"]
    state = driver.query_axis_positions()
    assert state["z"]["mm"] is None
    assert state["z"]["counts"] == 123  # the counts half still reads


def test_zero_scale_reads_as_unknown_not_infinite(make_driver):
    driver = make_driver(config=_cfg(pos_scale=0.0), position=123)
    assert driver.query_axis_positions()["z"]["mm"] is None


def test_moving_flag_comes_from_get_status(make_driver):
    moving = make_driver(status=("moving_fw",))
    stopped = make_driver(status=())
    assert moving.query_axis_positions()["z"]["moving"] is True
    assert stopped.query_axis_positions()["z"]["moving"] is False


def test_a_failed_axis_read_is_unknown_and_does_not_take_out_the_others(
    make_driver,
):
    cfg = {
        "axes": {
            "z": {
                "serial_no": "1",
                "pos_scale": POS_SCALE,
                "vel_scale": 1.0,
                "acc_scale": 1.0,
            },
            "y": {
                "serial_no": "2",
                "pos_scale": POS_SCALE,
                "vel_scale": 1.0,
                "acc_scale": 1.0,
            },
        }
    }
    driver = make_driver(config=cfg, position=1000)

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated device fault")

    driver.motors["y"].get_position = _boom
    state = driver.query_axis_positions()
    assert state["y"] == {"mm": None, "counts": None, "moving": False}
    assert state["z"]["counts"] == 1000


# --------------------------------------------------------------------------
# stop: unchanged, and asserted to stay that way (AC3)
# --------------------------------------------------------------------------
def test_stop_halts_every_axis_and_never_de_energizes(make_driver):
    cfg = {
        "axes": {
            "z": {
                "serial_no": "1",
                "pos_scale": POS_SCALE,
                "vel_scale": 1.0,
                "acc_scale": 1.0,
            },
            "y": {
                "serial_no": "2",
                "pos_scale": POS_SCALE,
                "vel_scale": 1.0,
                "acc_scale": 1.0,
            },
        }
    }
    driver = make_driver(config=cfg)
    driver.stop()
    for motor in driver.motors.values():
        assert motor.calls == [("stop", (), {"immediate": True, "sync": True})]
        assert motor.method_names() == {"stop"}  # nothing that cuts power
