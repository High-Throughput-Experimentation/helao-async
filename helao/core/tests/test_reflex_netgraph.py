"""netgraph: pure geometry for the /group network graph."""

import math

import pytest

from helao.ui.shared.palette import GROUP_IDLE, GROUP_PULSE_DISPATCH, WHITE


def _g():
    from helao.ui.reflex.netgraph import NetGraph

    g = NetGraph(height_px=360, width_px=720)
    g.add_node("ORCH", 0.0, 0.0, color=GROUP_IDLE, label_color=WHITE, text="ORCH")
    return g


def _trace(marks, name):
    return next(m for m in marks if m.get("name") == name)


def test_ports_face_each_other_by_relative_y():
    g = _g()
    g.add_node("UP", 0.0, 0.7, color=GROUP_IDLE, label_color=WHITE)
    g.add_node("DN", 0.5, -0.7, color=GROUP_IDLE, label_color=WHITE)
    g.add_edge("UP", "ORCH", "UP", color=GROUP_IDLE)
    g.add_edge("DN", "ORCH", "DN", color=GROUP_IDLE)
    ry = 14.0 * g.sy
    ports = g.ports()
    assert ports["UP"][0][1] == pytest.approx(ry)  # leaves ORCH from its top
    assert ports["UP"][1][1] == pytest.approx(0.7 - ry)  # enters UP from its bottom
    assert ports["DN"][0][1] == pytest.approx(-ry)
    assert ports["DN"][1][1] == pytest.approx(-0.7 + ry)


def test_bezier_end_tangents_are_vertical():
    from helao.ui.reflex.netgraph import bezier, control_points

    p0, p1, p2, p3 = control_points((-0.3, 0.1), (0.6, 0.6))
    assert p1[0] == p0[0] and p2[0] == p3[0]
    assert p1[1] > p0[1] and p2[1] < p3[1]
    pts = bezier((-0.3, 0.1), (0.6, 0.6))
    assert (
        len(pts) == 24
        and pts[0] == pytest.approx((-0.3, 0.1))
        and pts[-1] == pytest.approx((0.6, 0.6))
    )


def test_node_trace_is_drawn_last_and_no_arrowheads():
    # xy's hover marker reuses the symbol of the LAST scatter trace drawn
    # (probe note, 2026-11-06): last = a pulse triangle hovered as a big
    # down-triangle over the node. Nodes last, and no arrow traces at all.
    g = _g()
    g.add_node("UP", 0.0, 0.7, color=GROUP_IDLE, label_color=WHITE)
    g.add_edge("UP", "ORCH", "UP", color=GROUP_IDLE)
    scatters = [m for m in g.marks(0.0) if m["kind"] == "scatter"]
    assert [m["symbol"] for m in scatters] == ["triangle", "triangle_down", "circle"]
    assert not any(m.get("name", "").startswith("arrow") for m in g.marks(0.0))


def test_a_queued_pulse_is_kept_but_not_drawn_until_its_start():
    g = _g()
    g.add_node("UP", 0.0, 0.7, color=GROUP_IDLE, label_color=WHITE)
    g.add_edge("UP", "ORCH", "UP", color=GROUP_IDLE)
    g.pulse("UP", t0=5.0, duration=1.0, color=GROUP_PULSE_DISPATCH, direction="rev")
    assert _trace(g.marks(4.0), "pulse:triangle_down")["x"] == []
    assert len(g.pulses) == 1
    assert len(_trace(g.marks(5.5), "pulse:triangle_down")["x"]) == 1


def test_pulse_positions_and_expiry():
    from helao.ui.reflex.netgraph import arc_table, bezier, point_at

    g = _g()
    g.add_node("UP", 0.4, 0.7, color=GROUP_IDLE, label_color=WHITE)
    g.add_edge("UP", "ORCH", "UP", color=GROUP_IDLE)
    g.pulse("UP", t0=10.0, duration=1.0, color=GROUP_PULSE_DISPATCH)
    pa, pb = g.ports()["UP"]
    pts = bezier(pa, pb)
    cum = arc_table(pts, g.sx, g.sy)

    at0 = _trace(g.marks(10.0), "pulse:triangle")
    assert (at0["x"][0], at0["y"][0]) == pytest.approx(pa)
    mid = _trace(g.marks(10.5), "pulse:triangle")
    assert (mid["x"][0], mid["y"][0]) == pytest.approx(point_at(pts, cum, 0.5))
    assert pa[1] < mid["y"][0] < pb[1]
    gone = g.marks(11.0)
    assert _trace(gone, "pulse:triangle")["x"] == [] and g.pulses == []


def test_reverse_pulse_starts_at_the_destination_and_points_down():
    g = _g()
    g.add_node("UP", 0.0, 0.7, color=GROUP_IDLE, label_color=WHITE)
    g.add_edge("UP", "ORCH", "UP", color=GROUP_IDLE)
    g.pulse("UP", t0=0.0, duration=1.0, color=GROUP_PULSE_DISPATCH, direction="rev")
    pa, pb = g.ports()["UP"]
    down = _trace(g.marks(0.0), "pulse:triangle_down")
    assert (down["x"][0], down["y"][0]) == pytest.approx(pb)


def test_fan_out_ports_are_distinct():
    g = _g()
    for i, x in enumerate((-0.6, 0.0, 0.6)):
        g.add_node(f"S{i}", x, 0.7, color=GROUP_IDLE, label_color=WHITE)
        g.add_edge(f"S{i}", "ORCH", f"S{i}", color=GROUP_IDLE)
    xs = [g.ports()[f"S{i}"][0][0] for i in range(3)]
    assert len(set(xs)) == 3 and xs == sorted(xs)
    assert max(abs(x) for x in xs) == pytest.approx(0.7 * 14.0 * g.sx)


def test_layout_alternates_rows_and_adds_a_second_band():
    from helao.ui.reflex.netgraph import group_layout

    pos = group_layout("ORCH", ["C", "A", "B"])
    assert pos["ORCH"] == (0.0, 0.0)
    assert [math.copysign(1, pos[k][1]) for k in ("A", "B", "C")] == [1, -1, 1]
    assert {abs(pos[k][1]) for k in "ABC"} == {0.7}
    many = group_layout("ORCH", [f"S{i:02d}" for i in range(20)])
    assert {round(y, 2) for k, (x, y) in many.items() if k != "ORCH"} == {
        0.4,
        0.9,
        -0.4,
        -0.9,
    }


def test_node_label_is_centred_and_subtext_sits_away_from_the_orch():
    g = _g()
    g.add_node(
        "UP", 0.0, 0.7, color=GROUP_IDLE, label_color=WHITE, text="UP", subtext="move"
    )
    texts = {m["value"]: m for m in g.marks(0.0) if m["kind"] == "text"}
    assert texts["UP"]["anchor"] == "middle" and texts["UP"]["y"] == 0.7
    assert texts["move"]["y"] > 0.7  # above an upper node


def test_netgraph_does_not_import_xy():
    import helao.ui.reflex.netgraph as ng

    assert "xy" not in vars(ng)


def test_arc_table_measures_in_pixels_not_data_units():
    from helao.ui.reflex.netgraph import arc_table

    # 1 data unit is 2 px along x (sx=0.5) and 4 px along y (sy=0.25)
    assert arc_table([(0.0, 0.0), (1.0, 0.0)], 0.5, 0.25) == pytest.approx([0.0, 2.0])
    assert arc_table([(0.0, 0.0), (0.0, 1.0)], 0.5, 0.25) == pytest.approx([0.0, 4.0])


def test_default_padding_is_the_charts_padding():
    from helao.ui.reflex import plots
    from helao.ui.reflex.netgraph import NetGraph

    g = NetGraph(height_px=360, width_px=720)
    assert g.sx == pytest.approx(2.0 / (720 - 2 * plots.CHART_PADDING_PX))
    assert g.sy == pytest.approx(2.0 / (360 - 2 * plots.CHART_PADDING_PX))
