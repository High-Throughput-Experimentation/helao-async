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
    "amber-200": "#fde68a",
    "amber-500": "#f59e0b",
    "amber-700": "#b45309",
    "amber-800": "#92400e",
    "yellow-400": "#facc15",
    "yellow-700": "#a16207",
    "green-500": "#22c55e",
    "green-600": "#16a34a",
    "green-700": "#15803d",
    "teal-600": "#0d9488",
    "cyan-400": "#22d3ee",
    "cyan-500": "#06b6d4",
    "cyan-600": "#0891b2",
    "sky-100": "#e0f2fe",
    "sky-200": "#bae6fd",
    "sky-600": "#0284c7",
    "sky-700": "#0369a1",
    "blue-600": "#2563eb",
    "blue-700": "#1d4ed8",
    "violet-600": "#7c3aed",
    "purple-800": "#6b21a8",
    "fuchsia-600": "#c026d3",
    "pink-400": "#f472b6",
    "pink-500": "#ec4899",
}

WHITE: Final[str] = "#ffffff"

# ---------------------------------------------------------------------------
# Surfaces
# ---------------------------------------------------------------------------
PANEL_BG: Final[str] = TW["slate-300"]
"""Panel / layout background. Replaces ``#D6DBDF`` across both stacks."""

SURFACE_WHITE: Final[str] = WHITE
"""Tree overflow panels and input fields."""

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
