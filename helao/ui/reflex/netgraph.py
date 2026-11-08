"""Pure geometry for the /group network graph.

No Reflex state and no xy import: :meth:`NetGraph.marks` returns plain mark
dicts that :func:`helao.ui.reflex.plots.marks_chart` renders. Marker sizes are
in px and ports in data units, so the chart has a fixed domain, a fixed pixel
size and padding (``plots.CHART_PADDING_PX``); ``sx``/``sy`` convert between
them. Markers cannot rotate, so every curve ends vertically: a cubic Bezier
whose end tangents are vertical. Pulses are not drawn here: the chart shim
animates them in the browser from :meth:`NetGraph.edge_path`.
"""

from dataclasses import dataclass

from helao.ui.reflex import plots
from helao.ui.shared.palette import GROUP_EDGE_TEXT

CURVE_SAMPLES = 24
FANOUT = 0.7


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
    """Nodes, edges and pulses on a fixed view."""

    def __init__(
        self,
        height_px=360,
        width_px=720,
        domain=((-1.0, 1.0), (-1.0, 1.0)),
        padding_px=None,
        edge_styles=(),
        node_colors=(),
        hover_px=36.0,
    ):
        (x0, x1), (y0, y1) = domain
        self.domain = domain
        if padding_px is None:
            padding_px = plots.CHART_PADDING_PX
        self.sx = (x1 - x0) / (width_px - 2 * padding_px)
        self.sy = (y1 - y0) / (height_px - 2 * padding_px)
        self.nodes: dict = {}
        self.edges: dict = {}
        #: Every (colour, width) an edge may take. A line's style is spec, so a
        #: restyled edge rebuilds the chart; instead each style is its own
        #: always-present trace and an edge moves between them as column data.
        self.edge_styles = tuple(edge_styles)
        #: Every colour a node may take. xy applies a column update in place by
        #: writing only the points past the old length, and only when the trace
        #: keeps its length and column offsets (a colour-only change leaves the
        #: old colour on screen; a node joining a colour trace ahead of its
        #: existing points left a stale copy of them and no node: the orch
        #: vanished). So every (node, colour) is its own trace of ONE point that
        #: is either the node or the off-domain placeholder, and a node
        #: changing colour swaps two traces' offsets, which xy rebuilds.
        self.node_colors = tuple(node_colors)
        #: Size of the disc the browser draws over a hovered node. Only the
        #: subtext offset needs it here, to clear that disc.
        self.hover_px = float(hover_px)

    def add_node(
        self, key, x, y, *, color, label_color, text="", subtext="", size_px=28.0
    ):
        self.nodes[key] = Node(
            key, float(x), float(y), color, label_color, text, subtext, float(size_px)
        )

    def add_edge(self, edge_id, src, dst, *, color, text="", width=2.0):
        self.edges[edge_id] = Edge(edge_id, src, dst, color, text, float(width))

    def set_node_color(self, key, c):
        self.nodes[key].color = c

    def set_node_text(self, key, s):
        self.nodes[key].text = s

    def set_edge_color(self, edge_id, c):
        self.edges[edge_id].color = c

    def set_edge_text(self, edge_id, s):
        self.edges[edge_id].text = s

    def edge_path(self, edge_id):
        """The edge's sampled curve in data units, from its ``src`` to its ``dst``."""
        pa, pb = self.ports()[edge_id]
        return bezier(pa, pb)

    def node_descriptors(self) -> list:
        """One dict per node for the browser's hover overlay: key, data x/y,
        current fill colour and radius in px. Sorted by key, so equal graphs
        give equal lists."""
        return [
            {
                "key": n.key,
                "x": round(n.x, 5),
                "y": round(n.y, 5),
                "color": n.color,
                "r": n.size_px / 2,
            }
            for n in sorted(self.nodes.values(), key=lambda n: n.key)
        ]

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

    def marks(self):
        """Mark dicts for ``plots.marks_chart``.

        Pure state, no time: nothing here moves, so the chart changes only when
        a status or the topology does. Every scatter trace is always
        present (possibly empty), so the layout token does not change.
        A segments (edge) trace exists per declared style. Hover is not drawn
        here: the chart shim draws it in the browser from :meth:`node_descriptors`.
        """
        ports = self.ports()
        texts = []
        by_style = {st: ([], [], [], []) for st in self.edge_styles}
        for eid in sorted(self.edges):
            e = self.edges[eid]
            pa, pb = ports[eid]
            pts = bezier(pa, pb)
            seg = by_style.setdefault((e.color, e.width), ([], [], [], []))
            for (xa, ya), (xb, yb) in zip(pts, pts[1:]):
                for col, v in zip(seg, (xa, ya, xb, yb)):
                    col.append(v)
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
        by_node = {
            (n.key, c): ([], [])
            for n in self.nodes.values()
            for c in {*self.node_colors, n.color}
        }
        for n in self.nodes.values():
            xs, ys = by_node[(n.key, n.color)]
            xs.append(n.x)
            ys.append(n.y)
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
                # clear the enlarged hover disc too, not just the node
                grow = max(0.0, (self.hover_px - n.size_px) / 2)
                ry = n.size_px / 2 * self.sy
                above = n.y > 0
                if n.y == 0:
                    # the centre row (the orch) has edges above and below, so a
                    # name under it hits them: put it to the right, left-aligned,
                    # so a long name grows away from the node
                    texts.append(
                        {
                            "kind": "text",
                            "x": n.x + n.size_px / 2 * self.sx,
                            "y": n.y,
                            "value": n.subtext,
                            "dx": 6.0 + grow,
                            "dy": 4.0,
                            "color": GROUP_EDGE_TEXT,
                            "anchor": "start",
                        }
                    )
                    continue
                texts.append(
                    {
                        "kind": "text",
                        "x": n.x,
                        "y": n.y + ry if above else n.y - ry,
                        "value": n.subtext,
                        "dx": 0.0,
                        "dy": -6.0 - grow if above else 14.0 + grow,
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

        out = [
            {
                "kind": "segments",
                "name": f"edges:{color}:{width:g}",
                "x0": by_style[(color, width)][0],
                "y0": by_style[(color, width)][1],
                "x1": by_style[(color, width)][2],
                "y1": by_style[(color, width)][3],
                "color": color,
                "width": width,
            }
            for color, width in sorted(by_style)
        ]
        out += [
            scatter(
                f"nodes:{key}:{color}",
                (*by_node[(key, color)], [color] * len(by_node[(key, color)][0])),
                self.nodes[key].size_px,
                "circle",
            )
            for key, color in sorted(by_node)
        ]
        return out + texts
