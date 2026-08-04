"""The single source of every colour used by the HELAO UIs.

Both UI stacks resolve their colours here: the Bokeh documents (visualizers, the
operator, the data browser, the aligners) and the Reflex pages. This module is
deliberately **dependency-free** — no bokeh, no reflex, no matplotlib, stdlib
only — so either stack and the tests can import it freely.

Two rules govern edits:

1. **Nothing outside this module may hold a raw colour literal.** That is
   enforced by the AST sweeper in ``helao/core/tests/test_palette.py``, which
   exempts this file (and ``bokeh_theme.py``) by exact path, because these two
   are the modules that are *supposed* to hold literals.
2. **Consumers resolve their constants at module scope.** A mistyped ``TW`` key
   is a ``KeyError``; raised at import it is a loud crash, but raised inside a
   Bokeh document factory it is a blank page with nothing in the log. So write
   ``_ARM_TRACE = TW["cyan-600"]`` at module level, not ``TW["cyan-600"]``
   inline at the call site.

The shades are Tailwind's default palette. ``TW`` is the generic accessor;
role-named constants below give the shades their meaning. Deployment-specific
role names deliberately do **not** live here (this repo is a public remote) —
a deployment defines its own role-named constants over ``TW`` in its own files.
"""

from typing import Final, Mapping

# ---------------------------------------------------------------------------
# Generic shade table
# ---------------------------------------------------------------------------
# Every shade that any role below, or any deployment mapping, needs. Keys are
# ``<family>-<step>``; a key that does not match ``^[a-z]+-(50|[1-9]00|950)$``
# is rejected by the tests, so plain names such as "white" are role constants
# rather than TW entries.
TW: Final[Mapping[str, str]] = {
    # neutral ramp — slate throughout; the palette uses no other grey family
    "slate-50": "#f8fafc",
    "slate-100": "#f1f5f9",
    "slate-300": "#cbd5e1",
    "slate-400": "#94a3b8",
    "slate-500": "#64748b",
    "slate-600": "#475569",
    "slate-700": "#334155",
    "slate-800": "#1e293b",
    "slate-900": "#0f172a",
    "slate-950": "#020617",
    "red-100": "#fee2e2",
    "red-500": "#ef4444",
    "red-600": "#dc2626",
    "red-700": "#b91c1c",
    "red-900": "#7f1d1d",
    "red-950": "#450a0a",
    "orange-600": "#ea580c",
    "amber-50": "#fffbeb",
    "amber-200": "#fde68a",
    "amber-500": "#f59e0b",
    "amber-700": "#b45309",
    "amber-800": "#92400e",
    "yellow-400": "#facc15",
    "yellow-700": "#a16207",
    "green-500": "#22c55e",
    "green-600": "#16a34a",
    "green-700": "#15803d",
    "emerald-50": "#ecfdf5",
    "emerald-100": "#d1fae5",
    "emerald-600": "#059669",
    "emerald-700": "#047857",
    "teal-600": "#0d9488",
    "cyan-100": "#cffafe",
    "cyan-400": "#22d3ee",
    "cyan-500": "#06b6d4",
    "cyan-600": "#0891b2",
    "cyan-700": "#0e7490",
    "sky-50": "#f0f9ff",
    "sky-100": "#e0f2fe",
    "sky-200": "#bae6fd",
    "sky-600": "#0284c7",
    "sky-700": "#0369a1",
    "blue-100": "#dbeafe",
    "blue-600": "#2563eb",
    "blue-700": "#1d4ed8",
    "violet-50": "#f5f3ff",
    "violet-100": "#ede9fe",
    "violet-600": "#7c3aed",
    "violet-700": "#6d28d9",
    "purple-800": "#6b21a8",
    "fuchsia-600": "#c026d3",
    "pink-400": "#f472b6",
    "pink-500": "#ec4899",
}

WHITE: Final[str] = "#ffffff"

# ---------------------------------------------------------------------------
# Surfaces
# ---------------------------------------------------------------------------
PAGE_BG: Final[str] = TW["slate-50"]
"""The page canvas — ``html``/``body``, behind every panel.

**Distinct from :data:`PANEL_BG` on purpose, and it must stay that way.** Before
this palette existed the page was Bokeh's default white and panels were
``#D6DBDF``, giving a recessed-panel look: light canvas, mid-tone panel, light
plot area. An earlier draft pointed both the canvas and the panels at
``PANEL_BG``, which collapsed that hierarchy — the section panels became
invisible against the page on every visualizer, the operator, and the data
browser, because a 1.0:1 "contrast" is no contrast.

``slate-50`` restores the separation at 1.42:1, within a hair of the original
white's 1.48:1, while keeping the canvas in the slate family so it does not read
as stark white against slate panels. ``test_page_and_panel_are_distinct``
guards the collapse.
"""

PANEL_BG: Final[str] = TW["slate-300"]
"""Panel / layout background. Replaces ``#D6DBDF`` across both stacks.

Sits *between* :data:`PAGE_BG` behind it and :data:`SURFACE_WHITE` plot areas
inside it. Also the figure ``border_fill_color``, so a figure reads as flush
within its panel rather than as a card floating on one.
"""

SURFACE_WHITE: Final[str] = WHITE
"""Tree overflow panels, input fields, and figure plot areas."""

SURFACE_ALT: Final[str] = TW["slate-50"]
"""The faint off-white surface; replaces Radix ``var(--gray-2)``."""

PLAN_PANEL_NONQUEUED_BG: Final[str] = TW["sky-100"]
""""Non-queued" plan panel. Replaces ``#AED6F1``.

1.29:1 against :data:`PANEL_BG`, clearing the 1.20 neighbouring-surface floor.

``sky-200`` is the *nearest* shade to the original ``#AED6F1`` but sits at
1.12:1, so it was lifted one step along the same ramp. Going the other way does
not work: ``sky-300`` measures the same 1.12:1, because it sits symmetrically on
the far side of ``PANEL_BG``'s luminance, and ``sky-400`` clears the surface
floor only by dropping muted text on this panel to 3.54:1. Staying in the sky
ramp matters because the tint is categorical — it marks a plan item as *not
queued* — so a neutral like ``slate-100`` would clear the floor while discarding
the signal.
"""

PARAM_INPUT_BG: Final[str] = TW["amber-200"]
"""Operator param-input blocks and plate-map fill/border. Replaces ``#F9E79F``."""

# ---------------------------------------------------------------------------
# Reflex functional-section colour
# ---------------------------------------------------------------------------
REFLEX_PAGE_TINTS: Final[Mapping[str, str]] = {
    "/": "slate-50",
    "/live": "sky-50",
    "/action": "violet-50",
    "/operator": "amber-50",
    "/browser": "emerald-50",
}
"""One page canvas per Reflex route — the functional-section signal.

Values are TW shade **names**, not hex, and that is the load-bearing choice.
Each name has to yield two things that must never drift apart: ``TW[name]`` for
the contrast matrix in ``test_palette.py``, and ``f"bg-{name}"`` for the
Tailwind utility the component actually carries. The Reflex stack reaches its
colours through utility classes rather than inline hex, so a hex constant here
would be unusable at the call site, while a hand-written class string at the
call site would be unmeasurable here.

Distinct from :data:`PAGE_BG`, which is the **Bokeh** canvas. The ``"/"`` entry
happens to name the same shade; that is a coincidence of both wanting the
faintest neutral, not a shared constant. Changing one must not move the other.

Every tint clears the 4.5 body floor against :data:`BODY_TEXT` (16.28–17.22)
and against :data:`REFLEX_MUTED_TEXT` (6.91–7.31). ``slate-500`` does not: it
measures 4.34 on ``violet-50`` and 4.46 on ``sky-50``, and clears the floor on
``emerald-50`` by 0.02 — which is why muted text in the Reflex stack is a step
darker than the ``slate-500`` that serves the same role on white.
"""

REFLEX_TABLE_HUES: Final[Mapping[str, tuple[str, str, str]]] = {
    "sequence": ("violet-100", "violet-700", "violet-600"),
    "experiment": ("blue-100", "blue-700", "blue-600"),
    "action": ("cyan-100", "cyan-700", "cyan-600"),
    "server": ("slate-100", "slate-700", "slate-600"),
    "browser": ("emerald-100", "emerald-700", "emerald-600"),
}
"""Per-table hue by table *kind*: ``(header background, header text, border)``.

Keyed by kind rather than by tab, so the Queues and History views of the same
object type read as the same thing — which is the whole point of colouring by
function. Shade names, for the same reason as :data:`REFLEX_PAGE_TINTS`.

**Table bodies stay white.** Only the header row carries saturation; a tinted
body makes the data harder to read and would need every cell's text re-measured
against it. Zebra striping, if any is ever added, stays ``slate-50``.

Each header text clears the 4.5 body floor on its own header background
(4.79–9.45). Each 600-level border clears the 3.0 non-text floor against every
entry in :data:`REFLEX_PAGE_TINTS`, worst case ``cyan-600`` at 3.36 on
``violet-50``.
"""

REFLEX_MUTED_TEXT: Final[str] = "slate-600"
"""Muted text throughout the Reflex stack, as a TW shade name.

One value rather than the Bokeh stack's two surface-keyed roles
(:data:`MUTED_TEXT_ON_WHITE` / :data:`MUTED_TEXT_ON_PANEL`), because every
Reflex page now sits on a tint and two of the five cannot carry ``slate-500``
at all. A per-route muted role would be the *consistent* generalisation of the
Bokeh split, and it is deliberately not what this is: it would mean a caption
changing shade as you navigate, to buy back a step of lightness on three
surfaces. One shade that clears the floor on all five is the better trade.
"""


def reflex_page_class(route: str) -> str:
    """Return the Tailwind utilities painting *route*'s page canvas.

    ``min-h-screen`` is part of the answer, not decoration: without it the tint
    stops at the bottom of the content box and the viewport below it stays the
    browser default, so a short page reads as two colours.

    Args:
        route: A key of :data:`REFLEX_PAGE_TINTS`.

    Raises:
        KeyError: For an unknown route — loudly, at build time, rather than
            rendering an untinted page that looks merely unfinished.
    """
    return f"bg-{REFLEX_PAGE_TINTS[route]} min-h-screen"


def reflex_header_class(kind: str) -> str:
    """Return the Tailwind utilities for *kind*'s table header cells.

    Args:
        kind: A key of :data:`REFLEX_TABLE_HUES`.
    """
    background, text, _ = REFLEX_TABLE_HUES[kind]
    return f"bg-{background} text-{text}"


def reflex_table_class(kind: str) -> str:
    """Return the Tailwind utilities for *kind*'s 3px left border.

    Carried by the table's container rather than the header row, so the marker
    runs the full height of the table and stays visible while the body scrolls.

    Args:
        kind: A key of :data:`REFLEX_TABLE_HUES`.
    """
    _, _, border = REFLEX_TABLE_HUES[kind]
    return f"border-l-[3px] border-{border}"


def reflex_muted_text_class() -> str:
    """Return the Tailwind utility for muted text on any Reflex page tint."""
    return f"text-{REFLEX_MUTED_TEXT}"


def reflex_gridjs_header_css() -> str:
    """Return the CSS giving the data browser's gridjs header its table hue.

    **The one place in the Reflex stack that needs CSS rather than a utility
    class, for two independent reasons.** ``rx.data_table`` does not forward
    ``class_name`` to the grid it renders, so the utility never reaches the DOM
    at all — and even when it does, gridjs ships ``th.gridjs-th`` as *unlayered*
    CSS while Tailwind v4 emits utilities into ``@layer utilities``, which every
    unlayered rule outranks regardless of specificity. Verified both ways with
    ``getComputedStyle``: the class was absent from the element and no matching
    rule existed in any stylesheet.

    Authored here rather than at the call site because a CSS ``color:``
    declaration is exactly what the sweeper in ``test_palette.py`` flags, and
    this module is one of the two it exempts. ``bokeh_theme.py``'s ``GLOBAL_CSS``
    is the same arrangement for the other stack.

    Selectors are prefixed with ``.gridjs-container`` to outrank gridjs's own
    ``th.gridjs-th`` (0,1,1) and ``th.gridjs-th-sort:hover`` (0,2,1) on
    specificity rather than on source order, which ``head_components`` does not
    control. Hover and focus repeat the resting background on purpose: the only
    in-family step up is ``emerald-200``, which drops the header text to 4.28 and
    would need a standing contrast exception to ship. The ``cursor: pointer``
    gridjs already sets on a sortable header carries the affordance instead.
    """
    background, text, _ = REFLEX_TABLE_HUES["browser"]
    fill, ink = TW[background], TW[text]
    return (
        f".gridjs-container th.gridjs-th,"
        f".gridjs-container th.gridjs-th.gridjs-th-sort:hover,"
        f".gridjs-container th.gridjs-th.gridjs-th-sort:focus"
        f" {{ background-color: {fill}; color: {ink}; }}"
    )


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------
HEADING_TEXT: Final[str] = TW["red-600"]
"""Banner and section-header titles. Replaces ``#CB4335``.

Heading-sized, so it is held to the 3:1 large-text floor (3.25:1 on the panel),
not the 4.5:1 body floor. The claim is explicit rather than a lowered floor.
"""

BODY_TEXT: Final[str] = TW["slate-900"]
"""Default body text, error labels, param inputs, marker outlines. Was ``"black"``."""

MUTED_TEXT_ON_WHITE: Final[str] = TW["slate-500"]
MUTED_TEXT_ON_PANEL: Final[str] = TW["slate-600"]
"""Muted text is **two** roles keyed by surface, not one value.

``slate-500`` clears AA on white (4.76:1) but reaches only 3.21:1 on
:data:`PANEL_BG`; ``slate-600`` on the panel is 5.10:1. Picking one value for
both surfaces fails AA on whichever surface it was not chosen for.
``#566573`` (version + arg-description text, which sits on the panel) maps to
:data:`MUTED_TEXT_ON_PANEL`.
"""

WARNING_TEXT: Final[str] = TW["amber-700"]
"""Warning text — ``amber-700``, not ``amber-600``.

``amber-600`` is 3.19:1 on white and fails the body floor. ``amber-700`` serves
both this role and :data:`BUTTON_WARNING_BG`.
"""

MODIFIED_PARAM_TEXT: Final[str] = TW["red-600"]
"""Param-input text when the value differs from the default. Was ``"red"``."""

BROWSER_HEADER_TEXT: Final[str] = TW["sky-700"]
"""Data-browser header. Replaces ``#2471A3``."""

BROWSER_FAILURE_TEXT: Final[str] = TW["red-700"]
"""Data-browser scan-failure span. Replaces ``#c0392b``."""

# ---------------------------------------------------------------------------
# Controls
# ---------------------------------------------------------------------------
ESTOP_BG: Final[str] = TW["red-900"]
"""ESTOP button background. Replaces ``#7B0000``."""

ESTOP_HOVER_BG: Final[str] = TW["red-950"]
"""ESTOP hover / border. Replaces ``#5A0000``."""

# Bokeh supplies its own semantic-button colours from inside each widget's
# shadow root, where a document-level stylesheet cannot reach. These four feed
# the per-widget ``InlineStyleSheet`` override of ``.bk-btn-primary`` and
# friends. Each clears both the 3:1 control floor against PANEL_BG and the
# 4.5:1 body floor for its white label — the second is why ``green-600``
# (2.22 vs panel) and ``amber-600`` (3.19 white label) were both rejected.
BUTTON_PRIMARY_BG: Final[str] = TW["sky-700"]
BUTTON_SUCCESS_BG: Final[str] = TW["green-700"]
BUTTON_WARNING_BG: Final[str] = TW["amber-700"]
BUTTON_DANGER_BG: Final[str] = TW["red-700"]
BUTTON_LABEL: Final[str] = WHITE
"""White label text on all four semantic button surfaces, and on ESTOP."""

SELECTED_MARKER_OUTLINE: Final[str] = TW["red-600"]
"""Selected-sample marker outline. Replaces the ``(255, 0, 0)`` tuple."""

# ---------------------------------------------------------------------------
# Identity marker swatches
# ---------------------------------------------------------------------------
# The five aligner marker buttons are ``label=""`` 40x40 chips whose only job
# is to match a plotted marker hue. No contrast floor applies to them and no
# label row is generated: forcing a luminance ratio against their container
# would break the very correspondence they encode, and there is no label text
# to carry legibility instead.
#
# MARKER_SWATCH_5 is ``pink-400``, and SERIES[6] is ``pink-500``. **Both pinks
# exist, for different roles, and neither supersedes the other.** ``pink-400``
# is the ``#FF69B4`` swatch target; ``pink-500`` is the series slot, nudged one
# step from ``pink-400`` so the trace floor passes. Deleting either breaks a
# live mapping.
MARKER_SWATCH_1: Final[str] = TW["red-600"]  # was #ff0000
MARKER_SWATCH_2: Final[str] = TW["blue-700"]  # was #0000ff
MARKER_SWATCH_3: Final[str] = TW["green-500"]  # was #00ff00
MARKER_SWATCH_4: Final[str] = TW["amber-500"]  # was #FFA500
MARKER_SWATCH_5: Final[str] = TW["pink-400"]  # was #FF69B4

MARKER_SWATCHES: Final[tuple[str, ...]] = (
    MARKER_SWATCH_1,
    MARKER_SWATCH_2,
    MARKER_SWATCH_3,
    MARKER_SWATCH_4,
    MARKER_SWATCH_5,
)

# ---------------------------------------------------------------------------
# Qualitative series palette
# ---------------------------------------------------------------------------
# One 10-entry tuple replaces plots.py's 8-entry PALETTE, both Category10[10]
# uses, and all eight ad-hoc per-file trace lists. Slot order preserves today's
# role assignment (red first), so existing charts keep the colour *slot* each
# trace already has — the hues themselves change, which is the point.
#
# Two slots were nudged one step so every trace clears the 2.0:1 floor against
# PANEL_BG with no standing exception: slot 3 orange-500 -> orange-600
# (1.89 -> 2.40) and slot 6 pink-400 -> pink-500 (1.78 -> 2.38). The other
# eight stand as first derived.
SERIES: Final[tuple[str, ...]] = (
    TW["red-600"],  # 0  was "red" / #d62728
    TW["blue-600"],  # 1  was "blue" / #1f77b4
    TW["green-600"],  # 2  was "green" / #2ca02c
    TW["orange-600"],  # 3  was "orange" / #ff7f0e   (nudged from orange-500)
    TW["violet-600"],  # 4  was "purple" / #9467bd
    TW["amber-800"],  # 5  was #8c564b (tab10 brown)
    TW["pink-500"],  # 6  was "magenta" / #e377c2    (nudged from pink-400)
    TW["slate-500"],  # 7  was #7f7f7f (tab10 grey)
    TW["cyan-600"],  # 8  was "cyan"
    TW["fuchsia-600"],  # 9  extends to 10 for Category10 parity
)

# ---------------------------------------------------------------------------
# Continuous ramp
# ---------------------------------------------------------------------------
RAMP_START: Final[str] = TW["red-100"]
RAMP_END: Final[str] = TW["red-900"]


def _to_rgb(hex_color: str) -> tuple[int, int, int]:
    raw = hex_color.lstrip("#")
    return (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))


def _to_hex(channels: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % channels


def red_ramp(n: int) -> tuple[str, ...]:
    """Return *n* hex strings interpolating :data:`RAMP_START` to :data:`RAMP_END`.

    The recency shading for the spectra visualizer, which is why that module
    needs no matplotlib. Interpolation is linear in sRGB and inclusive of both
    endpoints; ``n == 1`` yields the start colour alone.
    """
    if n < 1:
        raise ValueError(f"red_ramp needs at least one step, got {n}")
    start, end = _to_rgb(RAMP_START), _to_rgb(RAMP_END)
    if n == 1:
        return (RAMP_START,)
    out = []
    for i in range(n):
        t = i / (n - 1)
        out.append(
            _to_hex(tuple(round(s + (e - s) * t) for s, e in zip(start, end)))  # type: ignore[arg-type]
        )
    return tuple(out)


# ---------------------------------------------------------------------------
# xy chart chrome
# ---------------------------------------------------------------------------
def _rgba(hex_color: str, alpha: float) -> str:
    r, g, b = _to_rgb(hex_color)
    return f"rgba({r}, {g}, {b}, {alpha})"


CHART_CHROME: Final[Mapping[str, str]] = {
    "--chart-text": TW["slate-700"],
    "--chart-tooltip-bg": _rgba(TW["slate-800"], 0.95),
    "--chart-tooltip-text": WHITE,
    "--chart-legend-bg": TW["slate-100"],
}
"""Four of the 22 CSS custom properties ``xy-client.js`` reads.

The other 18 — including the visually dominant ``--chart-bg``, ``--chart-grid``
and ``--chart-axis`` — are knowingly left at their JS fallbacks, so "chart
chrome matches the palette" is scoped to text, tooltip and legend background.
"""
