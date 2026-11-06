"""Pure geometry for the /group network graph.

No Reflex state and no xy import: :meth:`NetGraph.marks` returns plain mark
dicts that :func:`helao.ui.reflex.plots.marks_chart` renders. Marker sizes are
in px and ports in data units, so the chart has a fixed domain, a fixed pixel
size and padding (``plots.CHART_PADDING_PX``); ``sx``/``sy`` convert between
them. Markers cannot rotate, so every curve ends vertically: a cubic Bezier
whose end tangents are vertical, which lets a ``triangle`` (up) or
``triangle_down`` sit flush at either end.
"""

import bisect
import math
from dataclasses import dataclass, field

from helao.ui.reflex import plots
from helao.ui.shared.palette import GROUP_EDGE_TEXT

CURVE_SAMPLES = 24
FANOUT = 0.7
ARROW_PX = 10.0
PULSE_PX = 12.0
SYMBOLS = ("triangle", "triangle_down")


@dataclass
class Node:
    key: str
    x: float
    y: float
    color: str
    label_color: str
    text: str = ""
    subtext: str = ""
    size_px: float = 28.0


@dataclass
class Edge:
    edge_id: str
    src: str
    dst: str
    color: str
    text: str = ""
    width: float = 2.0
    arrow_at: set = field(default_factory=set)


@dataclass
class Pulse:
    edge_id: str
    direction: str
    t0: float
    duration: float
    color: str


def control_points(pa, pb):
    """P0..P3 with vertical end tangents: ``d = 0.5*|dy|`` toward the other end."""
    (xa, ya), (xb, yb) = pa, pb
    d = 0.5 * abs(yb - ya)
    s = 1.0 if yb >= ya else -1.0
    return (xa, ya), (xa, ya + s * d), (xb, yb - s * d), (xb, yb)


def bezier(pa, pb, n=CURVE_SAMPLES):
    """The curve sampled at ``n`` points, ends included."""
    p0, p1, p2, p3 = control_points(pa, pb)
    pts = []
    for i in range(n):
        t = i / (n - 1)
        u = 1.0 - t
        a, b, c, d = u**3, 3 * u * u * t, 3 * u * t * t, t**3
        pts.append(
            (
                a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
                a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1],
            )
        )
    return pts


def arc_table(pts, sx, sy):
    """Cumulative arc length in px, so a pulse moves at even screen speed."""
    cum = [0.0]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        cum.append(cum[-1] + math.hypot((x1 - x0) / sx, (y1 - y0) / sy))
    return cum


def point_at(pts, cum, s):
    """The point at arc-length fraction ``s`` (clamped to [0, 1])."""
    s = min(max(s, 0.0), 1.0)
    target = s * cum[-1]
    i = bisect.bisect_left(cum, target)
    if i <= 0:
        return pts[0]
    if i >= len(cum):
        return pts[-1]
    seg = cum[i] - cum[i - 1]
    f = 0.0 if seg == 0 else (target - cum[i - 1]) / seg
    (x0, y0), (x1, y1) = pts[i - 1], pts[i]
    return (x0 + f * (x1 - x0), y0 + f * (y1 - y0))


def group_layout(orch_key, server_keys):
    """Orchestrator at (0, 0); servers sorted, alternating above/below.

    Up to 8 per row sit at y = +/-0.7, evenly spaced in x; above 8 a row splits
    into two bands at +/-0.4 and +/-0.9.
    """
    keys = sorted(server_keys)
    pos = {orch_key: (0.0, 0.0)}
    for row, sign in ((keys[0::2], 1.0), (keys[1::2], -1.0)):
        bands = [(row, 0.7)] if len(row) <= 8 else [(row[0::2], 0.4), (row[1::2], 0.9)]
        for band, y in bands:
            n = len(band)
            for i, key in enumerate(band):
                pos[key] = (-0.9 + 1.8 * (i + 0.5) / n, sign * y)
    return pos


class NetGraph:
    """Nodes, edges, arrowheads and pulses on a fixed view."""

    def __init__(
        self,
        height_px=360,
        width_px=720,
        domain=((-1.0, 1.0), (-1.0, 1.0)),
        padding_px=None,
    ):
        (x0, x1), (y0, y1) = domain
        self.domain = domain
        if padding_px is None:
            padding_px = plots.CHART_PADDING_PX
        self.sx = (x1 - x0) / (width_px - 2 * padding_px)
        self.sy = (y1 - y0) / (height_px - 2 * padding_px)
        self.nodes: dict = {}
        self.edges: dict = {}
        self.pulses: list = []

    def add_node(
        self, key, x, y, *, color, label_color, text="", subtext="", size_px=28.0
    ):
        self.nodes[key] = Node(
            key, float(x), float(y), color, label_color, text, subtext, float(size_px)
        )

    def add_edge(self, edge_id, src, dst, *, color, text="", width=2.0):
        self.edges[edge_id] = Edge(edge_id, src, dst, color, text, float(width))

    def add_arrowhead(self, edge_id, at="dst"):
        self.edges[edge_id].arrow_at.add(at)

    def set_node_color(self, key, c):
        self.nodes[key].color = c

    def set_node_text(self, key, s):
        self.nodes[key].text = s

    def set_edge_color(self, edge_id, c):
        self.edges[edge_id].color = c

    def set_edge_text(self, edge_id, s):
        self.edges[edge_id].text = s

    def pulse(self, edge_id, *, t0, color, direction="fwd", duration=0.6):
        self.pulses.append(Pulse(edge_id, direction, float(t0), float(duration), color))

    def ports(self):
        """edge_id -> (src port, dst port), fanned out where ends share a side."""
        ends: dict = {}
        for e in self.edges.values():
            a, b = self.nodes[e.src], self.nodes[e.dst]
            ends.setdefault((a.key, "top" if b.y > a.y else "bottom"), []).append(
                (b.x, e.edge_id, 0)
            )
            ends.setdefault((b.key, "top" if a.y > b.y else "bottom"), []).append(
                (a.x, e.edge_id, 1)
            )
        out = {eid: [(0.0, 0.0), (0.0, 0.0)] for eid in self.edges}
        for (key, side), items in ends.items():
            n = self.nodes[key]
            rx = n.size_px / 2 * self.sx
            ry = n.size_px / 2 * self.sy
            y = n.y + ry if side == "top" else n.y - ry
            items.sort()
            k = len(items)
            for i, (_, eid, end) in enumerate(items):
                off = 0.0 if k == 1 else (-FANOUT + 2 * FANOUT * i / (k - 1)) * rx
                out[eid][end] = (n.x + off, y)
        return {eid: (p[0], p[1]) for eid, p in out.items()}

    def marks(self, now):
        """Mark dicts for ``plots.marks_chart``. Drops pulses with s >= 1.

        Every scatter trace is always present (possibly empty), so the trace
        set -- and the layout token -- does not change as pulses come and go.
        """
        self.pulses = [p for p in self.pulses if (now - p.t0) / p.duration < 1.0]
        ports = self.ports()
        lines, texts, curves = [], [], {}
        arrows = {sym: ([], [], []) for sym in SYMBOLS}
        moving = {sym: ([], [], []) for sym in SYMBOLS}
        for eid in sorted(self.edges):
            e = self.edges[eid]
            pa, pb = ports[eid]
            pts = bezier(pa, pb)
            curves[eid] = (pts, arc_table(pts, self.sx, self.sy))
            lines.append(
                {
                    "kind": "line",
                    "name": f"edge:{eid}",
                    "x": [p[0] for p in pts],
                    "y": [p[1] for p in pts],
                    "color": e.color,
                    "width": e.width,
                }
            )
            for at in sorted(e.arrow_at):
                tip, other = (pb, pa) if at == "dst" else (pa, pb)
                up = tip[1] > other[1]
                half = ARROW_PX / 2 * self.sy
                xs, ys, cs = arrows["triangle" if up else "triangle_down"]
                xs.append(tip[0])
                ys.append(tip[1] - half if up else tip[1] + half)
                cs.append(e.color)
            if e.text:
                mx, my = pts[len(pts) // 2]
                texts.append(
                    {
                        "kind": "text",
                        "x": mx,
                        "y": my,
                        "value": e.text,
                        "dx": 6.0,
                        "dy": 0.0,
                        "color": GROUP_EDGE_TEXT,
                        "anchor": "start",
                    }
                )
        for p in self.pulses:
            if p.edge_id not in curves:
                continue
            pts, cum = curves[p.edge_id]
            s = max(0.0, (now - p.t0) / p.duration)
            x, y = point_at(pts, cum, s if p.direction == "fwd" else 1.0 - s)
            up = (pts[-1][1] > pts[0][1]) == (p.direction == "fwd")
            xs, ys, cs = moving["triangle" if up else "triangle_down"]
            xs.append(x)
            ys.append(y)
            cs.append(p.color)
        by_size: dict = {}
        for n in self.nodes.values():
            xs, ys, cs = by_size.setdefault(n.size_px, ([], [], []))
            xs.append(n.x)
            ys.append(n.y)
            cs.append(n.color)
            if n.text:
                texts.append(
                    {
                        "kind": "text",
                        "x": n.x,
                        "y": n.y,
                        "value": n.text,
                        "dx": 0.0,
                        "dy": 4.0,
                        "color": n.label_color,
                        "anchor": "middle",
                    }
                )
            if n.subtext:
                ry = n.size_px / 2 * self.sy
                above = n.y > 0
                texts.append(
                    {
                        "kind": "text",
                        "x": n.x,
                        "y": n.y + ry if above else n.y - ry,
                        "value": n.subtext,
                        "dx": 0.0,
                        "dy": -6.0 if above else 14.0,
                        "color": GROUP_EDGE_TEXT,
                        "anchor": "middle",
                    }
                )

        def scatter(name, cols, size, symbol):
            xs, ys, cs = cols
            return {
                "kind": "scatter",
                "name": name,
                "x": xs,
                "y": ys,
                "colors": cs,
                "size": size,
                "symbol": symbol,
                "opacity": 1.0,
            }

        out = list(lines)
        out += [scatter(f"arrow:{s}", arrows[s], ARROW_PX, s) for s in SYMBOLS]
        out += [
            scatter(f"nodes:{size:g}", by_size[size], size, "circle")
            for size in sorted(by_size)
        ]
        out += [scatter(f"pulse:{s}", moving[s], PULSE_PX, s) for s in SYMBOLS]
        return out + texts
