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


def test_no_arrowheads_and_no_hovered_traces():
    g = _g()
    g.add_node("UP", 0.0, 0.7, color=GROUP_IDLE, label_color=WHITE)
    g.add_edge("UP", "ORCH", "UP", color=GROUP_IDLE)
    marks = g.marks()
    assert not any(m.get("name", "").startswith("arrow") for m in marks)
    assert not any(m.get("name", "").startswith("hovered") for m in marks)


def test_node_descriptors_give_position_current_colour_and_px_radius():
    g = NetGraphWith()
    g.add_node(
        "UP", 0.2, 0.7, color=GROUP_PULSE_DISPATCH, label_color=WHITE, size_px=44.0
    )
    d = {x["key"]: x for x in g.node_descriptors()}
    assert d["UP"] == {
        "key": "UP",
        "x": 0.2,
        "y": 0.7,
        "color": GROUP_PULSE_DISPATCH,
        "r": 22.0,
    }
    g.set_node_color("UP", GROUP_IDLE)
    assert {x["key"]: x for x in g.node_descriptors()}["UP"]["color"] == GROUP_IDLE
    assert g.node_descriptors() == sorted(g.node_descriptors(), key=lambda x: x["key"])


def NetGraphWith(**kw):
    from helao.ui.reflex.netgraph import NetGraph

    g = NetGraph(height_px=360, width_px=720, **kw)
    g.add_node("ORCH", 0.0, 0.0, color=GROUP_IDLE, label_color=WHITE)
    return g


def test_an_edge_changing_style_changes_only_column_data():
    # A line's style is spec (a restyle rebuilds the chart); a trace per declared
    # style keeps the trace set, names and styles identical across statuses.
    styles = ((GROUP_IDLE, 2.0), (GROUP_PULSE_DISPATCH, 4.0))
    g = NetGraphWith(edge_styles=styles)
    g.add_node("UP", 0.0, 0.7, color=GROUP_IDLE, label_color=WHITE)
    g.add_edge("UP", "ORCH", "UP", color=GROUP_IDLE, width=2.0)
    before = [m for m in g.marks() if m["kind"] == "segments"]
    g.set_edge_color("UP", GROUP_PULSE_DISPATCH)
    g.edges["UP"].width = 4.0
    after = [m for m in g.marks() if m["kind"] == "segments"]
    strip = lambda ms: [
        {k: v for k, v in m.items() if k not in ("x0", "y0", "x1", "y1")} for m in ms
    ]
    assert strip(before) == strip(after) and len(after) == 2
    assert [len(m["x0"]) > 0 for m in before] == [True, False]
    assert [len(m["x0"]) > 0 for m in after] == [False, True]


def test_edge_path_runs_from_src_port_to_dst_port_and_marks_have_no_pulses():
    from helao.ui.reflex.netgraph import bezier

    g = _g()
    g.add_node("UP", 0.4, 0.7, color=GROUP_IDLE, label_color=WHITE)
    g.add_edge("UP", "ORCH", "UP", color=GROUP_IDLE)
    pa, pb = g.ports()["UP"]
    path = g.edge_path("UP")
    assert path == bezier(pa, pb)
    assert path[0] == pytest.approx(pa) and path[-1] == pytest.approx(pb)
    assert not [m for m in g.marks() if m.get("name", "").startswith("pulse")]
    assert not hasattr(g, "pulses") and not hasattr(g, "pulse")


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
    texts = {m["value"]: m for m in g.marks() if m["kind"] == "text"}
    assert texts["UP"]["anchor"] == "middle" and texts["UP"]["y"] == 0.7
    assert texts["move"]["y"] > 0.7  # above an upper node


def test_netgraph_does_not_import_xy():
    import helao.ui.reflex.netgraph as ng

    assert "xy" not in vars(ng)


def test_default_padding_is_the_charts_padding():
    from helao.ui.reflex import plots
    from helao.ui.reflex.netgraph import NetGraph

    g = NetGraph(height_px=360, width_px=720)
    assert g.sx == pytest.approx(2.0 / (720 - 2 * plots.CHART_PADDING_PX))
    assert g.sy == pytest.approx(2.0 / (360 - 2 * plots.CHART_PADDING_PX))


def test_subtext_clears_the_enlarged_hover_disc():
    def dy(hover_px):
        g = NetGraphWith(hover_px=hover_px)
        g.add_node("UP", 0.0, 0.7, color=GROUP_IDLE, label_color=WHITE, subtext="move")
        return next(m for m in g.marks() if m.get("value") == "move")["dy"]

    assert dy(28.0) == -6.0  # no enlargement, no nudge
    assert dy(40.0) == -6.0 - 6.0  # pushed out by the disc's growth (12 px / 2)
