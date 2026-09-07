"""Turning MPR point reads into HELAO column dicts.

The cursor is what makes a poll loop possible over an API that has no
streaming: it remembers how many points it has already handed back, so the
driver can call it every tick and concatenate. It is also where the derived
columns are computed -- P_W, cycle, and the EIS pair -- so a mistake here is a
wrong number under a right column name, which no schema check would catch.
"""

import math

import pytest

from helao.deploy.hte.drivers.pstat.biologic_ole import technique as ot
from helao.deploy.hte.drivers.pstat.biologic_ole.mpr_cursor import (
    MprCursor,
    empty_frame,
)
from helao.deploy.hte.drivers.pstat.biologic_ole.olecom_client import OleComClient
from helao.deploy.hte.drivers.pstat.biologic_ole.sim import SimConfig, make_factory


def running_client(config: SimConfig) -> tuple[OleComClient, str]:
    """A client whose channel 0 has run to completion, plus its MPR path."""
    cli = OleComClient(factory=make_factory(config))
    dev = cli.connect_device_by_ip("1.2.3.4")
    cli.load_settings(dev, 0, "x.mps")
    cli.run_channel(dev, 0, "out")
    return cli, cli.get_data_file_name(dev, 0, 0)


def test_an_empty_frame_has_every_column_and_no_rows():
    frame = empty_frame(ot.resolve("CA").column_plan)
    assert set(frame) == set(ot.columns(ot.resolve("CA").column_plan))
    assert all(values == [] for values in frame.values())


def test_a_dc_read_returns_every_point_once():
    cli, mpr = running_client(SimConfig(run_seconds=0.0, points_per_second=100.0))
    cursor = MprCursor(cli, ot.resolve("CA").column_plan, mpr)
    first = cursor.read_new()
    assert len(first["t_s"]) == cli.measure_number_of_points(mpr)
    assert cursor.read_new()["t_s"] == []


def test_the_cursor_reports_how_many_points_it_has_read():
    cli, mpr = running_client(SimConfig(run_seconds=0.0))
    cursor = MprCursor(cli, ot.resolve("CA").column_plan, mpr)
    frame = cursor.read_new()
    assert cursor.n_read == len(frame["t_s"])


def test_every_dc_column_is_the_same_length():
    cli, mpr = running_client(SimConfig(run_seconds=0.0))
    frame = MprCursor(cli, ot.resolve("CA").column_plan, mpr).read_new(cycle=3.0)
    lengths = {name: len(values) for name, values in frame.items()}
    assert len(set(lengths.values())) == 1, lengths


def test_power_is_derived_as_the_absolute_product():
    """EC-Lab defines variable 70 as |Ewe * I|, so this is exact, not close."""
    cli, mpr = running_client(SimConfig(run_seconds=0.0))
    frame = MprCursor(cli, ot.resolve("CA").column_plan, mpr).read_new()
    for ewe, current, power in zip(frame["Ewe_V"], frame["I_A"], frame["P_W"]):
        assert power == pytest.approx(abs(ewe * current))


def test_cycle_is_stamped_from_the_callers_status_reading():
    cli, mpr = running_client(SimConfig(run_seconds=0.0))
    frame = MprCursor(cli, ot.resolve("CA").column_plan, mpr).read_new(cycle=7.0)
    assert set(frame["cycle"]) == {7.0}


def test_ocv_emits_only_time_and_potential():
    cli, mpr = running_client(SimConfig(run_seconds=0.0))
    frame = MprCursor(cli, ot.resolve("OCV").column_plan, mpr).read_new()
    assert set(frame) == {"t_s", "Ewe_V"}


def test_an_eis_read_fills_every_declared_column():
    cli, mpr = running_client(SimConfig(kind="eis", run_seconds=0.0, n_eis_points=6))
    plan = ot.resolve("PEIS").column_plan
    frame = MprCursor(cli, plan, mpr).read_new()
    assert set(frame) == set(ot.columns(plan))
    assert all(len(values) == 6 for values in frame.values())


def test_the_impedance_pair_comes_straight_off_measure_eis_value():
    """R_ohm is Re(Z); X_ohm is the 'imaginary part', already -Im(Z)."""
    cli, mpr = running_client(SimConfig(kind="eis", run_seconds=0.0, n_eis_points=4))
    frame = MprCursor(cli, ot.resolve("PEIS").column_plan, mpr).read_new()
    for index in range(4):
        _, _, re_z, minus_im_z = cli.measure_eis_value(mpr, index)
        assert frame["R_ohm"][index] == pytest.approx(re_z)
        assert frame["X_ohm"][index] == pytest.approx(minus_im_z)


def test_the_derived_pair_agrees_with_the_eclib_formula():
    """eclib computes R = |Z|cos(phase), X = -|Z|sin(phase). Same numbers."""
    cli, mpr = running_client(SimConfig(kind="eis", run_seconds=0.0, n_eis_points=4))
    frame = MprCursor(cli, ot.resolve("PEIS").column_plan, mpr).read_new()
    for modulus, phase, r_ohm, x_ohm in zip(
        frame["modulus"], frame["phase"], frame["R_ohm"], frame["X_ohm"]
    ):
        assert r_ohm == pytest.approx(modulus * math.cos(phase))
        assert x_ohm == pytest.approx(-modulus * math.sin(phase))


def test_process_is_one_where_the_frequency_is_non_zero():
    """A non-EIS index returns frequency zero, per section 5.2.14."""
    cli, mpr = running_client(SimConfig(kind="eis", run_seconds=0.0, n_eis_points=4))
    frame = MprCursor(cli, ot.resolve("PEIS").column_plan, mpr).read_new()
    for f_hz, process in zip(frame["f_Hz"], frame["process"]):
        assert process == (1.0 if f_hz else 0.0)


def test_reading_before_any_points_exist_returns_an_empty_frame():
    cli = OleComClient(factory=make_factory(SimConfig()))
    dev = cli.connect_device_by_ip("1.2.3.4")
    cli.load_settings(dev, 0, "x.mps")
    cursor = MprCursor(cli, ot.resolve("CA").column_plan, "nonexistent.mpr")
    frame = cursor.read_new()
    assert set(frame) == set(ot.columns(ot.resolve("CA").column_plan))
    assert frame["t_s"] == []


def test_reset_points_the_cursor_at_a_new_file_and_rewinds_it():
    """A multi-technique .mps has one MPR per technique."""
    cli, mpr = running_client(SimConfig(run_seconds=0.0))
    cursor = MprCursor(cli, ot.resolve("CA").column_plan, mpr)
    cursor.read_new()
    assert cursor.n_read > 0
    cursor.reset(mpr)
    assert cursor.n_read == 0
    assert len(cursor.read_new()["t_s"]) > 0


def test_a_second_read_after_new_points_returns_only_the_new_ones():
    cli, mpr = running_client(SimConfig(run_seconds=0.15, points_per_second=200.0))
    cursor = MprCursor(cli, ot.resolve("CA").column_plan, mpr)
    first = len(cursor.read_new()["t_s"])
    import time

    time.sleep(0.2)
    second = len(cursor.read_new()["t_s"])
    total = cli.measure_number_of_points(mpr)
    assert first + second == total
    assert second > 0
