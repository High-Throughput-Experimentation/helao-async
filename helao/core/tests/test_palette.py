"""Gate on ``helao.core.servers.palette`` and on the colour-literal sweeper.

Four things are pinned here:

1. Every ``TW`` shade is a genuine Tailwind shade, checked against
   :data:`CANONICAL_TAILWIND` — a table that lives in **this file**, authored
   separately from the one in ``palette.py``. If the table supplying the values
   were also the table the assertion checks against, the assertion would reduce
   to ``assert TW["cyan-600"] in TW.values()``, which is vacuous.
2. The full contrast matrix, computed under pinned arithmetic and published at
   2 dp, so a later shade edit that degrades contrast fails loudly instead of
   silently shipping.
3. The six-rule AST sweeper, calibrated against frozen fixture snapshots with
   **complete** manifests. A nine-of-seventeen example list is satisfied by a
   sweeper that still misses the other eight, so the manifests below enumerate
   every finding in each fixture.
4. The whole-tree sweep, which is **expected to fail** until the last sweep
   phase lands. It is deliberately not marked ``xfail``: a marker that has to
   be removed later is a stub that passes green.
"""

import ast
import math
import re
from pathlib import Path
from typing import Final

import pytest

from helao.core.servers import palette
from helao.core.servers.palette import SERIES, TW

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
FIXTURE_DIR: Final[Path] = Path(__file__).parent / "fixtures" / "sweeper_calibration"

WHITE: Final[str] = "#ffffff"

# ===========================================================================
# 1. Canonical Tailwind table — independent of palette.TW
# ===========================================================================
# Tailwind's default palette, in sRGB hex. Tailwind v4 expresses these same
# shades in OKLCH; the sRGB round-trip differs by at most a couple of units per
# channel, and the hex values below are the ones the palette mapping was
# derived against, so they are what is pinned.
CANONICAL_TAILWIND: Final[dict[str, str]] = {
    "slate-50": "#f8fafc",
    "slate-100": "#f1f5f9",
    "slate-200": "#e2e8f0",
    "slate-300": "#cbd5e1",
    "slate-400": "#94a3b8",
    "slate-500": "#64748b",
    "slate-600": "#475569",
    "slate-700": "#334155",
    "slate-800": "#1e293b",
    "slate-900": "#0f172a",
    "slate-950": "#020617",
    "red-50": "#fef2f2",
    "red-100": "#fee2e2",
    "red-200": "#fecaca",
    "red-300": "#fca5a5",
    "red-400": "#f87171",
    "red-500": "#ef4444",
    "red-600": "#dc2626",
    "red-700": "#b91c1c",
    "red-800": "#991b1b",
    "red-900": "#7f1d1d",
    "red-950": "#450a0a",
    "orange-400": "#fb923c",
    "orange-500": "#f97316",
    "orange-600": "#ea580c",
    "orange-700": "#c2410c",
    "amber-50": "#fffbeb",
    "amber-100": "#fef3c7",
    "amber-200": "#fde68a",
    "amber-400": "#fbbf24",
    "amber-500": "#f59e0b",
    "amber-600": "#d97706",
    "amber-700": "#b45309",
    "amber-800": "#92400e",
    "yellow-400": "#facc15",
    "yellow-500": "#eab308",
    "yellow-600": "#ca8a04",
    "yellow-700": "#a16207",
    "yellow-800": "#854d0e",
    "green-400": "#4ade80",
    "green-500": "#22c55e",
    "green-600": "#16a34a",
    "green-700": "#15803d",
    "green-800": "#166534",
    "emerald-50": "#ecfdf5",
    "emerald-100": "#d1fae5",
    "emerald-500": "#10b981",
    "emerald-600": "#059669",
    "emerald-700": "#047857",
    "teal-500": "#14b8a6",
    "teal-600": "#0d9488",
    "teal-700": "#0f766e",
    "cyan-100": "#cffafe",
    "cyan-400": "#22d3ee",
    "cyan-500": "#06b6d4",
    "cyan-600": "#0891b2",
    "cyan-700": "#0e7490",
    "sky-50": "#f0f9ff",
    "sky-100": "#e0f2fe",
    "sky-200": "#bae6fd",
    "sky-500": "#0ea5e9",
    "sky-600": "#0284c7",
    "sky-700": "#0369a1",
    "blue-50": "#eff6ff",
    "blue-100": "#dbeafe",
    "blue-600": "#2563eb",
    "blue-700": "#1d4ed8",
    "blue-800": "#1e40af",
    "violet-50": "#f5f3ff",
    "violet-100": "#ede9fe",
    "violet-600": "#7c3aed",
    "violet-700": "#6d28d9",
    "purple-700": "#7e22ce",
    "purple-800": "#6b21a8",
    "fuchsia-600": "#c026d3",
    "fuchsia-700": "#a21caf",
    "pink-400": "#f472b6",
    "pink-500": "#ec4899",
}

TW_KEY_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z]+-(50|[1-9]00|950)$")


def test_tw_is_a_final_mapping() -> None:
    annotation = palette.__annotations__["TW"]
    assert "Final" in str(annotation)
    assert "Mapping[str, str]" in str(annotation)


def test_tw_keys_have_tailwind_shape() -> None:
    bad = [key for key in TW if not TW_KEY_RE.match(key)]
    assert bad == [], f"keys are not <family>-<step>: {bad}"


def test_every_tw_shade_is_genuine() -> None:
    """Each ``TW`` entry appears in the canonical table at the same value."""
    missing = sorted(key for key in TW if key not in CANONICAL_TAILWIND)
    assert missing == [], f"not Tailwind shade names: {missing}"
    wrong = {
        key: (value, CANONICAL_TAILWIND[key])
        for key, value in TW.items()
        if value.lower() != CANONICAL_TAILWIND[key]
    }
    assert wrong == {}, f"value does not match the canonical shade: {wrong}"


def test_tw_values_are_lowercase_six_digit_hex() -> None:
    bad = [v for v in TW.values() if not re.fullmatch(r"#[0-9a-f]{6}", v)]
    assert bad == [], f"not lowercase 6-digit hex: {bad}"


def test_neutral_ramp_is_slate_only() -> None:
    """Constraint: slate is the neutral ramp. No other grey family may appear."""
    forbidden = {"gray", "zinc", "neutral", "stone"}
    present = {key.split("-")[0] for key in TW} & forbidden
    assert present == set(), f"non-slate grey families present: {present}"


# ===========================================================================
# 2. Exports
# ===========================================================================
def test_palette_imports_nothing_heavy() -> None:
    """The module must stay importable by both stacks and by the tests."""
    source = (REPO_ROOT / "helao/core/servers/palette.py").read_text()
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {"typing"}, f"palette.py must be stdlib-only, got {imported}"


def test_series_has_ten_entries_in_the_pinned_order() -> None:
    assert len(SERIES) == 10
    assert SERIES == (
        TW["red-600"],
        TW["blue-600"],
        TW["green-600"],
        TW["orange-600"],
        TW["violet-600"],
        TW["amber-800"],
        TW["pink-500"],
        TW["slate-500"],
        TW["cyan-600"],
        TW["fuchsia-600"],
    )


def test_the_two_nudged_series_slots() -> None:
    assert SERIES[3] == TW["orange-600"] == "#ea580c"
    assert SERIES[6] == TW["pink-500"] == "#ec4899"


def test_both_pinks_exist_for_their_separate_roles() -> None:
    """``pink-500`` is SERIES[6]; ``pink-400`` is the ``#FF69B4`` marker swatch.

    Neither supersedes the other. An executor reading the nudge note and
    deleting ``pink-400`` breaks the marker mapping, which is why this is
    asserted rather than only documented.
    """
    assert TW["pink-400"] == "#f472b6"
    assert TW["pink-500"] == "#ec4899"
    assert palette.MARKER_SWATCH_5 == TW["pink-400"]
    assert SERIES[6] == TW["pink-500"]
    assert palette.MARKER_SWATCH_5 not in SERIES


def test_marker_swatches() -> None:
    assert palette.MARKER_SWATCHES == (
        TW["red-600"],
        TW["blue-700"],
        TW["green-500"],
        TW["amber-500"],
        TW["pink-400"],
    )


def test_semantic_button_constants() -> None:
    assert palette.BUTTON_PRIMARY_BG == TW["sky-700"]
    assert palette.BUTTON_SUCCESS_BG == TW["green-700"]
    assert palette.BUTTON_WARNING_BG == TW["amber-700"]
    assert palette.BUTTON_DANGER_BG == TW["red-700"]
    assert palette.BUTTON_LABEL == WHITE


def test_warning_text_is_amber_700_not_600() -> None:
    assert palette.WARNING_TEXT == TW["amber-700"]
    assert palette.WARNING_TEXT != CANONICAL_TAILWIND["amber-600"]


def test_two_muted_text_roles_keyed_by_surface() -> None:
    assert palette.MUTED_TEXT_ON_WHITE == TW["slate-500"]
    assert palette.MUTED_TEXT_ON_PANEL == TW["slate-600"]
    assert palette.MUTED_TEXT_ON_WHITE != palette.MUTED_TEXT_ON_PANEL


# The 22 CSS custom properties ``xy-client.js`` reads, transcribed from the
# bundled client into *this* file. Authored separately from ``CHART_CHROME`` for
# the same reason as :data:`CANONICAL_TAILWIND`: a subset check against the set
# the palette itself supplies would reduce to ``assert set(d) <= set(d)``. With
# the list held here, a mistyped variable name — which the browser accepts in
# silence and simply resolves nowhere — fails a test instead of shipping.
XY_CHART_VARS: Final[frozenset[str]] = frozenset(
    {
        "--chart-annotation-text",
        "--chart-axis",
        "--chart-badge-bg",
        "--chart-badge-text",
        "--chart-bg",
        "--chart-crosshair",
        "--chart-cursor",
        "--chart-cursor-pan",
        "--chart-focus",
        "--chart-grid",
        "--chart-legend-bg",
        "--chart-modebar-active",
        "--chart-modebar-bg",
        "--chart-modebar-focus",
        "--chart-selection",
        "--chart-selection-fill",
        "--chart-text",
        "--chart-tick-label-max-width",
        "--chart-tooltip-bg",
        "--chart-tooltip-text",
        "--chart-zoom-selection",
        "--chart-zoom-selection-fill",
    }
)

# Three of the 22 hold something other than a colour, and assigning a colour to
# any of them breaks a working feature rather than failing to theme one.
NON_COLOUR_CHART_VARS: Final[frozenset[str]] = frozenset(
    {
        "--chart-cursor",  # `cursor: var(--chart-cursor, crosshair)` — a keyword
        "--chart-cursor-pan",  # `cursor: var(--chart-cursor-pan, grab)` — a keyword
        "--chart-tick-label-max-width",  # `min(var(--…, Npx))` — a length
    }
)


def test_chart_chrome_names_are_all_read_by_xy() -> None:
    """No ``CHART_CHROME`` key may be a name ``xy-client.js`` never looks up.

    An unread custom property is a *silent* no-op: the ``:root`` block still
    parses, the page still renders, and the chart simply keeps the JS fallback.
    Nothing in either stack notices.
    """
    unread = set(palette.CHART_CHROME) - XY_CHART_VARS
    assert unread == set(), f"CHART_CHROME sets properties xy never reads: {unread}"


def test_chart_chrome_omits_the_three_non_colour_vars() -> None:
    """The regression guard against "completing the set".

    ``CHART_CHROME`` covers 19 of 22, and the three left out are left out
    *because they are not colours* — two CSS cursor keywords and a length. A
    later edit that fills the gap for symmetry would drop the pan tool's grab
    cursor and unclamp the tick labels, and neither failure surfaces anywhere:
    the properties are syntactically fine, they just no longer mean what
    ``cursor:`` and ``min()`` need them to mean.
    """
    intruders = set(palette.CHART_CHROME) & NON_COLOUR_CHART_VARS
    assert intruders == set(), (
        f"{sorted(intruders)} hold CSS keywords/lengths, not colours — setting "
        f"them to a colour breaks the feature instead of theming it"
    )
    assert set(palette.CHART_CHROME) == XY_CHART_VARS - NON_COLOUR_CHART_VARS
    assert len(palette.CHART_CHROME) == 19


def test_chart_chrome_values() -> None:
    assert palette.CHART_CHROME == {
        "--chart-bg": palette.SURFACE_WHITE,
        "--chart-grid": TW["slate-300"],
        "--chart-axis": TW["slate-400"],
        "--chart-text": TW["slate-700"],
        "--chart-annotation-text": TW["slate-700"],
        "--chart-tooltip-bg": "rgba(30, 41, 59, 0.95)",
        "--chart-tooltip-text": WHITE,
        "--chart-badge-bg": "rgba(30, 41, 59, 0.95)",
        "--chart-badge-text": WHITE,
        "--chart-crosshair": "rgba(15, 23, 42, 0.42)",
        "--chart-legend-bg": TW["slate-100"],
        "--chart-modebar-bg": WHITE,
        "--chart-modebar-active": TW["slate-100"],
        "--chart-focus": TW["sky-600"],
        "--chart-modebar-focus": TW["sky-600"],
        "--chart-selection": TW["sky-600"],
        "--chart-selection-fill": "rgba(2, 132, 199, 0.12)",
        "--chart-zoom-selection": TW["sky-700"],
        "--chart-zoom-selection-fill": "rgba(3, 105, 161, 0.12)",
    }


def test_chart_bg_matches_the_bokeh_plot_area() -> None:
    """The Reflex chart canvas and the Bokeh plot area are the same surface.

    This is the parity claim the whole change exists for: the Bokeh figures take
    their background from ``HELAO_THEME``'s ``Plot.background_fill_color``, and
    while ``--chart-bg`` sat at xy's own fallback the two stacks disagreed about
    the plot interior.
    """
    assert palette.CHART_CHROME["--chart-bg"] == palette.SURFACE_WHITE


def test_chart_crosshair_is_the_xy_default_made_palette_sourced() -> None:
    """``rgba(15, 23, 42, .42)`` is what ``xy-client.js`` already falls back to.

    ``slate-900`` *is* ``rgb(15, 23, 42)``, so this entry changes no pixel — it
    moves the value from a hardcoded fallback in a vendored JS bundle to the
    palette, where a later shade edit carries it along.
    """
    assert palette.CHART_CHROME["--chart-crosshair"] == "rgba(15, 23, 42, 0.42)"
    assert TW["slate-900"] == "#0f172a"  # == rgb(15, 23, 42)


def test_red_ramp() -> None:
    assert palette.red_ramp(1) == (TW["red-100"],)
    ramp = palette.red_ramp(2)
    assert ramp == (TW["red-100"], TW["red-900"])
    ramp = palette.red_ramp(5)
    assert len(ramp) == 5
    assert ramp[0] == TW["red-100"]
    assert ramp[-1] == TW["red-900"]
    assert all(re.fullmatch(r"#[0-9a-f]{6}", step) for step in ramp)
    # monotonically darkening: red-100 -> red-900 falls in every channel
    lums = [_luminance(step) for step in palette.red_ramp(12)]
    assert lums == sorted(lums, reverse=True)
    with pytest.raises(ValueError):
        palette.red_ramp(0)


# ===========================================================================
# 3. Contrast matrix, under pinned arithmetic
# ===========================================================================
# Two implementers must produce the same numbers, so the constants are fixed
# rather than left to choice.
SRGB_LINEARIZATION_THRESHOLD: Final[float] = 0.04045
D65_WHITE_POINT: Final[tuple[float, float, float]] = (0.95047, 1.0, 1.08883)
LAB_F_CUTOFF: Final[float] = 0.008856


def _channels(hex_color: str) -> tuple[int, int, int]:
    raw = hex_color.lstrip("#")
    return (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))


def _linearize(channel: int) -> float:
    c = channel / 255.0
    if c <= SRGB_LINEARIZATION_THRESHOLD:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def _luminance(hex_color: str) -> float:
    r, g, b = (_linearize(c) for c in _channels(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: str, b: str) -> float:
    """WCAG 2.x relative-luminance contrast ratio."""
    la, lb = _luminance(a), _luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def _lab(hex_color: str) -> tuple[float, float, float]:
    r, g, b = (_linearize(c) for c in _channels(hex_color))
    x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / D65_WHITE_POINT[0]
    y = (0.2126729 * r + 0.7151522 * g + 0.0721750 * b) / D65_WHITE_POINT[1]
    z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / D65_WHITE_POINT[2]

    def f(t: float) -> float:
        return t ** (1 / 3) if t > LAB_F_CUTOFF else 7.787 * t + 16 / 116

    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def delta_e_76(a: str, b: str) -> float:
    """CIE76 ``ΔE*ab`` — a perceptual distance, not a luminance ratio."""
    return math.dist(_lab(a), _lab(b))


# Role floors. Contrast resolves by role, not by one uniform value: a uniform
# 3:1 is arithmetically unsatisfiable by this mapping and is also the wrong
# rule, since WCAG 3:1 is a threshold for text and interactive components, not
# for a 1px data stroke.
FLOOR_BODY_TEXT: Final[float] = 4.5
FLOOR_HEADING_TEXT: Final[float] = 3.0
FLOOR_CONTROL: Final[float] = 3.0
FLOOR_TRACE: Final[float] = 2.0
FLOOR_SURFACE: Final[float] = 1.20
FLOOR_DELTA_E: Final[float] = 15.0

# "Never lower a floor" and "the palette test is green with zero skips" are only
# compatible through an explicit registry of accepted exceptions carrying each
# pair's *measured* value. A later change that degrades contrast still fails
# loudly, because the pinned measurement moves.
#
# Currently **empty**, and that is the intended end state. The one entry it held
# was the "Non-queued" plan panel: sky-200 is the nearest shade to the original
# #AED6F1 but measures 1.12 against the surface floor. Rather than carry a
# standing exception, the panel was lifted one step to sky-100 (1.29). An empty
# registry is a stronger gate than a populated one — every pair now meets its
# floor on its own merits, so any future entry is a deliberate, reviewable act
# rather than a value inherited from a prior compromise.
ACCEPTED_CONTRAST_EXCEPTIONS: Final[dict[tuple[str, str], float]] = {}

PANEL: Final[str] = "slate-300"

# --- published matrix, 2 dp -------------------------------------------------
# Every SERIES entry against the panel surface and against white.
TRACE_ROWS: Final[dict[str, tuple[float, float]]] = {
    "red-600": (3.25, 4.83),
    "blue-600": (3.48, 5.17),
    "green-600": (2.22, 3.30),
    "orange-600": (2.40, 3.56),
    "violet-600": (3.84, 5.70),
    "amber-800": (4.78, 7.09),
    "pink-500": (2.38, 3.53),
    "slate-500": (3.21, 4.76),
    "cyan-600": (2.48, 3.68),
    "fuchsia-600": (3.17, 4.71),
}

# Adjacent SERIES pairs plus the wrap-around.
DELTA_E_ROWS: Final[dict[tuple[str, str], float]] = {
    ("red-600", "blue-600"): 126.00,
    ("blue-600", "green-600"): 139.86,
    ("green-600", "orange-600"): 111.79,
    ("orange-600", "violet-600"): 144.18,
    ("violet-600", "amber-800"): 126.96,
    ("amber-800", "pink-500"): 66.36,
    ("pink-500", "slate-500"): 69.94,
    ("slate-500", "cyan-600"): 24.14,
    ("cyan-600", "fuchsia-600"): 101.61,
    ("fuchsia-600", "red-600"): 102.76,
}

HEADING_ROWS: Final[dict[tuple[str, str], float]] = {
    ("red-600", "slate-300"): 3.25,  # banner + section-header titles
    ("sky-700", "slate-300"): 4.00,  # data-browser header
}

BODY_TEXT_ROWS: Final[dict[tuple[str, str], float]] = {
    ("slate-500", "white"): 4.76,  # muted text on white
    ("slate-600", "slate-300"): 5.10,  # muted text on the panel
    ("amber-700", "white"): 5.02,  # warning text
    ("amber-700", "slate-50"): 4.80,  # the cell that makes 2 dp matter
    ("slate-900", "white"): 17.85,  # body text
    ("slate-900", "amber-200"): 14.33,  # param-input text on its amber block
    ("slate-700", "white"): 10.35,  # chart text
    ("red-600", "white"): 4.83,  # modified-param text
    ("red-700", "white"): 6.47,  # data-browser failure text
    ("sky-700", "white"): 5.93,  # data-browser header on white
}

# The four semantic button surfaces (plus ESTOP) against their container.
BUTTON_SURFACE_ROWS: Final[dict[tuple[str, str], float]] = {
    ("sky-700", "slate-300"): 4.00,  # primary
    ("green-700", "slate-300"): 3.38,  # success
    ("amber-700", "slate-300"): 3.38,  # warning
    ("red-700", "slate-300"): 4.36,  # danger
    ("red-900", "slate-300"): 6.75,  # ESTOP
}

# White label text on each button surface, declared as a first-class row class:
# its omission is how an amber-600 label at 3.19 slipped past two reviews.
BUTTON_LABEL_ROWS: Final[dict[tuple[str, str], float]] = {
    ("white", "sky-700"): 5.93,
    ("white", "green-700"): 5.02,
    ("white", "amber-700"): 5.02,
    ("white", "red-700"): 6.47,
    ("white", "red-900"): 10.02,
}

SURFACE_ROWS: Final[dict[tuple[str, str], float]] = {
    # The page canvas against the panels sitting on it. This is the pair that
    # regressed: pointing both at slate-300 made every section panel vanish.
    ("slate-50", "slate-300"): 1.42,
    ("slate-300", "white"): 1.48,
    ("amber-200", "white"): 1.25,
    ("sky-100", "slate-300"): 1.29,  # was sky-200 at 1.12, below the floor
    # The section border, against everything it can sit between. Both sides of
    # the line are declared for each panel it outlines, because the border has
    # panel on one side and canvas on the other and has to be visible against
    # both -- one row would only prove half of it.
    ("slate-400", "slate-300"): 1.73,  # section border on the panel
    ("slate-400", "slate-50"): 2.45,  # ... and against the page behind it
    ("slate-400", "sky-100"): 2.23,  # ... on the non-queued plan panel
    # The aligners' two dark panels take their own darker border: slate-400 is
    # *lighter* than these, so on them it would read as a highlight.
    ("slate-800", "teal-600"): 3.91,
    ("slate-800", "yellow-700"): 2.97,
}

# --- Reflex functional-section colour --------------------------------------
# Text on each of the five Reflex route tints. Both columns are declared for
# every tint rather than only the worst one, because "muted text moved to
# slate-600" is a claim about all five surfaces and the margins are narrow
# enough that guessing which cells fail does not work: slate-500 fails on
# violet-50 (4.34) and sky-50 (4.46) but passes on slate-50 (4.55), amber-50
# (4.59) and emerald-50 (4.52) -- the last by 0.02. Only a complete row set
# separates those, and only slate-600 clears every one of them by a margin
# (6.91-7.31) rather than by a rounding error.
PAGE_TINT_TEXT_ROWS: Final[dict[tuple[str, str], float]] = {
    ("slate-900", "slate-50"): 17.06,  # index
    ("slate-600", "slate-50"): 7.24,
    ("slate-900", "sky-50"): 16.75,  # /live
    ("slate-600", "sky-50"): 7.11,
    ("slate-900", "violet-50"): 16.28,  # /action
    ("slate-600", "violet-50"): 6.91,
    ("slate-900", "amber-50"): 17.22,  # /operator
    ("slate-600", "amber-50"): 7.31,
    ("slate-900", "emerald-50"): 16.95,  # /browser
    ("slate-600", "emerald-50"): 7.19,
}

# The shade slate-600 replaced, kept as a measurement rather than a comment.
# Two of these cells fail the body floor outright and a third clears it by 0.02,
# which together are what make the migration mandatory rather than cosmetic. If
# a later Tailwind revision moved slate-500 enough to change that, this says so.
SLATE_500_ON_TINT_ROWS: Final[dict[tuple[str, str], float]] = {
    ("slate-500", "slate-50"): 4.55,
    ("slate-500", "sky-50"): 4.46,
    ("slate-500", "violet-50"): 4.34,
    ("slate-500", "amber-50"): 4.59,
    ("slate-500", "emerald-50"): 4.52,
}

# Each table's header text on its own header background. Body-floor rows: a
# column header is body-sized text.
#
# ``blue-700`` appears here *and* as MARKER_SWATCH_2, deliberately, the same way
# both pinks exist for separate roles. Neither supersedes the other and neither
# may be deleted on the grounds that the other exists.
REFLEX_HEADER_ROWS: Final[dict[tuple[str, str], float]] = {
    ("violet-700", "violet-100"): 5.98,  # Sequences
    ("blue-700", "blue-100"): 5.49,  # Experiments
    ("cyan-700", "cyan-100"): 4.79,  # Actions
    ("slate-700", "slate-100"): 9.45,  # Servers
    ("emerald-700", "emerald-100"): 4.84,  # data browser
}

# Each table's 3px left border against its worst-case page tint. A border is a
# non-text graphical object, so the 3:1 control floor applies, not 4.5. Every
# one of the five is worst on violet-50, the darkest tint, so that is the only
# background that needs declaring -- the four brighter tints are strictly
# easier.
REFLEX_BORDER_ROWS: Final[dict[tuple[str, str], float]] = {
    ("violet-600", "violet-50"): 5.20,
    ("blue-600", "violet-50"): 4.71,
    ("cyan-600", "violet-50"): 3.36,  # the tightest cell in the whole design
    ("slate-600", "violet-50"): 6.91,
    ("emerald-600", "violet-50"): 3.44,
}


# --- xy chart surfaces ------------------------------------------------------
# Everything the plot interior paints, measured against `--chart-bg`, which is
# the one background all of it sits on. Keyed by CHART_CHROME *variable name*
# rather than by shade name, so a row tracks the role even if the shade behind
# it moves, and pinned with the floor that role answers to — the roles here span
# three different floors, which is why the floor is a column rather than one
# value for the whole table.
#
# Floors, and why each is the right one:
#
# * Gridlines are `FLOOR_SURFACE` (1.20), not a text or control floor. A
#   gridline's job is to be *findable* against the canvas while staying quieter
#   than every trace drawn over it; that is the same "two neighbouring surfaces
#   must not collapse into one" question `SURFACE_ROWS` asks, and `slate-300`
#   answers it at the same 1.48 it gives the Bokeh panel against white. Holding
#   a 1px reference line to the 4.5 body floor would force it up past the data.
# * Axis lines are `FLOOR_TRACE` (2.0). An axis is a stroke that carries meaning
#   — it is the frame the reader measures against, not backdrop — so it sits
#   with the traces rather than with the surfaces, one step darker at
#   `slate-400`.
# * Selection, zoom-band and focus borders are `FLOOR_CONTROL` (3.0): WCAG's
#   non-text floor for a graphical object that communicates interaction state.
# * `--chart-text` and `--chart-annotation-text` are tick labels and annotation
#   labels — body-sized text, so `FLOOR_BODY_TEXT` (4.5).
#
# `--chart-legend-bg` and `--chart-modebar-active` are deliberately absent; see
# the `CHART_CHROME` docstring. Both measure 1.10 against `--chart-bg` and both
# are faint chrome washes whose content carries the affordance, so neither is a
# surface-boundary row and neither takes an exception.
CHART_SURFACE_ROWS: Final[dict[tuple[str, str], tuple[float, float]]] = {
    ("--chart-grid", "--chart-bg"): (1.48, FLOOR_SURFACE),
    ("--chart-axis", "--chart-bg"): (2.56, FLOOR_TRACE),
    ("--chart-selection", "--chart-bg"): (4.10, FLOOR_CONTROL),
    ("--chart-zoom-selection", "--chart-bg"): (5.93, FLOOR_CONTROL),
    ("--chart-focus", "--chart-bg"): (4.10, FLOOR_CONTROL),
    ("--chart-modebar-focus", "--chart-bg"): (4.10, FLOOR_CONTROL),
    ("--chart-text", "--chart-bg"): (10.35, FLOOR_BODY_TEXT),
    ("--chart-annotation-text", "--chart-bg"): (10.35, FLOOR_BODY_TEXT),
}


def _shade(name: str) -> str:
    return WHITE if name == "white" else TW[name]


def _check(pair: tuple[str, str], published: float, floor: float) -> None:
    fg, bg = pair
    measured = contrast_ratio(_shade(fg), _shade(bg))
    assert measured == pytest.approx(
        published, abs=0.01
    ), f"{fg} on {bg}: published {published:.2f}, measured {measured:.2f}"
    if measured < floor:
        accepted = ACCEPTED_CONTRAST_EXCEPTIONS.get(pair)
        assert accepted is not None, (
            f"{fg} on {bg} is {measured:.2f}, below its {floor} floor, and is "
            f"not in ACCEPTED_CONTRAST_EXCEPTIONS"
        )
        assert accepted == pytest.approx(measured, abs=0.01), (
            f"{fg} on {bg} measures {measured:.2f} but the registry pins "
            f"{accepted:.2f} — contrast has changed since it was accepted"
        )


@pytest.mark.parametrize("shade", sorted(TRACE_ROWS))
def test_trace_contrast(shade: str) -> None:
    on_panel, on_white = TRACE_ROWS[shade]
    _check((shade, PANEL), on_panel, FLOOR_TRACE)
    _check((shade, "white"), on_white, FLOOR_TRACE)


def test_trace_rows_cover_every_series_slot() -> None:
    assert {TW[name] for name in TRACE_ROWS} == set(SERIES)


@pytest.mark.parametrize("pair", sorted(DELTA_E_ROWS))
def test_adjacent_series_are_perceptually_distinct(pair: tuple[str, str]) -> None:
    measured = delta_e_76(TW[pair[0]], TW[pair[1]])
    assert measured == pytest.approx(DELTA_E_ROWS[pair], abs=0.01)
    assert (
        measured >= FLOOR_DELTA_E
    ), f"{pair[0]} and {pair[1]} are ΔE76 {measured:.2f} apart, below {FLOOR_DELTA_E}"


def test_delta_e_rows_are_the_adjacent_pairs_plus_wrap_around() -> None:
    expected = {
        (
            _name_of(SERIES[i]),
            _name_of(SERIES[(i + 1) % len(SERIES)]),
        )
        for i in range(len(SERIES))
    }
    assert set(DELTA_E_ROWS) == expected


def _name_of(value: str) -> str:
    for key, shade in TW.items():
        if shade == value:
            return key
    raise AssertionError(f"{value} is not a TW shade")


@pytest.mark.parametrize("pair", sorted(HEADING_ROWS))
def test_heading_contrast(pair: tuple[str, str]) -> None:
    _check(pair, HEADING_ROWS[pair], FLOOR_HEADING_TEXT)


@pytest.mark.parametrize("pair", sorted(BODY_TEXT_ROWS))
def test_body_text_contrast(pair: tuple[str, str]) -> None:
    _check(pair, BODY_TEXT_ROWS[pair], FLOOR_BODY_TEXT)


@pytest.mark.parametrize("pair", sorted(BUTTON_SURFACE_ROWS))
def test_button_surface_contrast(pair: tuple[str, str]) -> None:
    _check(pair, BUTTON_SURFACE_ROWS[pair], FLOOR_CONTROL)


@pytest.mark.parametrize("pair", sorted(BUTTON_LABEL_ROWS))
def test_button_label_contrast(pair: tuple[str, str]) -> None:
    _check(pair, BUTTON_LABEL_ROWS[pair], FLOOR_BODY_TEXT)


def test_button_label_rows_cover_every_button_surface() -> None:
    surfaces = {surface for surface, _ in BUTTON_SURFACE_ROWS}
    labelled = {surface for _, surface in BUTTON_LABEL_ROWS}
    assert surfaces == labelled, "every button surface needs a declared label row"


@pytest.mark.parametrize("pair", sorted(SURFACE_ROWS))
def test_neighbouring_surface_contrast(pair: tuple[str, str]) -> None:
    _check(pair, SURFACE_ROWS[pair], FLOOR_SURFACE)


@pytest.mark.parametrize("pair", sorted(CHART_SURFACE_ROWS))
def test_chart_surface_contrast(pair: tuple[str, str]) -> None:
    """Every painted part of the plot interior, against the chart background.

    Resolved through ``CHART_CHROME`` rather than through :data:`TW`, so the row
    measures the value the browser will actually receive.
    """
    published, floor = CHART_SURFACE_ROWS[pair]
    fg, bg = (palette.CHART_CHROME[name] for name in pair)
    measured = contrast_ratio(fg, bg)
    assert measured == pytest.approx(published, abs=0.01), (
        f"{pair[0]} ({fg}) on {pair[1]} ({bg}): published {published:.2f}, "
        f"measured {measured:.2f}"
    )
    assert measured >= floor, (
        f"{pair[0]} on {pair[1]} is {measured:.2f}, below its {floor} floor "
        f"(see the floor rationale above CHART_SURFACE_ROWS)"
    )


def test_grid_and_axis_are_distinguishable_from_the_chart_background() -> None:
    """The two roles the Bokeh figures already theme and the Reflex charts did not.

    Named separately from the parametrized rows because "the gridlines are
    visible" is the claim, and it must not be satisfiable by the rows table
    simply losing an entry. The ordering assertion is part of it: the axis has to
    read as *stronger* than the gridlines, or the frame disappears into the mesh.
    """
    chrome = palette.CHART_CHROME
    bg = chrome["--chart-bg"]
    grid = contrast_ratio(chrome["--chart-grid"], bg)
    axis = contrast_ratio(chrome["--chart-axis"], bg)
    assert grid >= FLOOR_SURFACE, f"gridlines are {grid:.2f} on the canvas"
    assert axis >= FLOOR_TRACE, f"axis lines are {axis:.2f} on the canvas"
    assert axis > grid, "the axis must read stronger than the gridlines it frames"


def test_chart_rows_cover_every_interaction_affordance() -> None:
    """Selection, zoom band and both focus rings each carry a declared row.

    Omitting one is exactly how an under-contrast control slips through: the
    palette still looks complete and the missing pair is simply never measured.
    """
    measured = {fg for fg, _ in CHART_SURFACE_ROWS}
    assert {
        "--chart-selection",
        "--chart-zoom-selection",
        "--chart-focus",
        "--chart-modebar-focus",
    } <= measured


def test_no_swatch_rows_are_asserted() -> None:
    """The five marker chips carry no contrast floor and no label row.

    They are ``label=""`` 40x40 swatches whose only job is to match a plotted
    marker hue; a luminance floor against their container would break the very
    correspondence they encode, and there is no label text to carry legibility
    instead. Two earlier drafts got this wrong in opposite directions — the
    control floor (arithmetically false at 1.78/1.53/1.45) and a 4.5 label
    floor (slate-900 fails on two of the five). Neither is asserted.
    """
    declared = (
        set(TRACE_ROWS)
        | {fg for fg, _ in HEADING_ROWS}
        | {fg for fg, _ in BODY_TEXT_ROWS}
        | {fg for fg, _ in BUTTON_SURFACE_ROWS}
        | {bg for _, bg in BUTTON_LABEL_ROWS}
    )
    swatch_only = {"blue-700", "green-500", "amber-500", "pink-400"}
    assert (
        declared & swatch_only == set()
    ), f"swatch-only shades must carry no asserted row: {declared & swatch_only}"


def test_page_and_panel_are_distinct() -> None:
    """The page canvas must not be the same colour as the panels on it.

    A regression guard for a real defect: ``GLOBAL_CSS`` painted ``html``/``body``
    in ``PANEL_BG``, the same value the section panels use. Nothing failed — the
    sweep was clean, every contrast row passed, the pages rendered — but the
    panels were invisible on every visualizer, the operator, and the data
    browser, because a surface against an identical surface has no contrast at
    all. Only looking at a page caught it.

    The pre-palette stack had a recessed-panel hierarchy (white canvas,
    ``#D6DBDF`` panel, white plot area) and this keeps it.
    """
    assert palette.PAGE_BG != palette.PANEL_BG
    ratio = contrast_ratio(palette.PAGE_BG, palette.PANEL_BG)
    assert ratio >= FLOOR_SURFACE, (
        f"page {palette.PAGE_BG} vs panel {palette.PANEL_BG} is {ratio:.2f}:1, "
        f"under the {FLOOR_SURFACE} surface floor — panels will not read as "
        f"separate regions from the canvas behind them"
    )


@pytest.mark.parametrize("pair", sorted(PAGE_TINT_TEXT_ROWS))
def test_page_tint_text_contrast(pair: tuple[str, str]) -> None:
    _check(pair, PAGE_TINT_TEXT_ROWS[pair], FLOOR_BODY_TEXT)


def test_page_tint_rows_cover_every_route_twice() -> None:
    """Both text roles, declared for every route. No tint may go unmeasured."""
    tints = set(palette.REFLEX_PAGE_TINTS.values())
    assert {bg for _, bg in PAGE_TINT_TEXT_ROWS} == tints
    for tint in tints:
        assert ("slate-900", tint) in PAGE_TINT_TEXT_ROWS
        assert (palette.REFLEX_MUTED_TEXT, tint) in PAGE_TINT_TEXT_ROWS


@pytest.mark.parametrize("pair", sorted(SLATE_500_ON_TINT_ROWS))
def test_slate_500_is_measured_on_every_tint(pair: tuple[str, str]) -> None:
    """The shade the Reflex stack moved *away* from, pinned as a measurement.

    Two of the five tints put ``slate-500`` under the 4.5 body floor and a third
    clears it by 0.02, which is why ``REFLEX_MUTED_TEXT`` is ``slate-600``.
    Asserting the numbers here means a future edit that reintroduces
    ``slate-500`` cannot claim it was fine, and a Tailwind revision that changed
    the shade enough to matter would surface as a published-value mismatch
    rather than as silently degraded text.
    """
    measured = contrast_ratio(_shade(pair[0]), _shade(pair[1]))
    assert measured == pytest.approx(SLATE_500_ON_TINT_ROWS[pair], abs=0.01)


def test_slate_500_fails_the_body_floor_on_two_of_the_five_tints() -> None:
    """Exactly two, and named -- not "at least one".

    A count would pass if the failing set moved to two different tints, and the
    point of the row block above is that *which* surfaces fail is not guessable
    from the shade names.
    """
    failing = {
        bg
        for (fg, bg) in SLATE_500_ON_TINT_ROWS
        if contrast_ratio(_shade(fg), _shade(bg)) < FLOOR_BODY_TEXT
    }
    assert failing == {"sky-50", "violet-50"}


def test_slate_600_clears_every_tint_by_a_real_margin() -> None:
    """The positive half of the claim: the replacement is not marginal either.

    ``emerald-50`` shows why this matters -- ``slate-500`` "passes" there at 4.52,
    two hundredths above the floor, which is not a margin anyone should ship
    muted text on. ``slate-600`` is at 7.19 on the same surface.
    """
    for tint in set(palette.REFLEX_PAGE_TINTS.values()):
        measured = contrast_ratio(TW[palette.REFLEX_MUTED_TEXT], TW[tint])
        assert measured >= 6.5, f"{palette.REFLEX_MUTED_TEXT} on {tint} is {measured}"


@pytest.mark.parametrize("pair", sorted(REFLEX_HEADER_ROWS))
def test_reflex_table_header_contrast(pair: tuple[str, str]) -> None:
    _check(pair, REFLEX_HEADER_ROWS[pair], FLOOR_BODY_TEXT)


def test_header_rows_cover_every_table_hue() -> None:
    declared = {(text, background) for background, text, _ in _table_hues()}
    assert declared == set(REFLEX_HEADER_ROWS)


@pytest.mark.parametrize("pair", sorted(REFLEX_BORDER_ROWS))
def test_reflex_table_border_contrast(pair: tuple[str, str]) -> None:
    _check(pair, REFLEX_BORDER_ROWS[pair], FLOOR_CONTROL)


def test_border_rows_cover_every_hue_at_its_worst_tint() -> None:
    """Each border is declared against the tint it is *weakest* on.

    Declaring the strongest pair would be the same shape of test and would prove
    nothing: a border only fails where the canvas is darkest.
    """
    tints = sorted(set(palette.REFLEX_PAGE_TINTS.values()))
    for _, _, border in _table_hues():
        worst = min(tints, key=lambda tint: contrast_ratio(TW[border], TW[tint]))
        assert (border, worst) in REFLEX_BORDER_ROWS, (
            f"{border} is weakest on {worst}, which is the pair that has to be "
            f"declared"
        )


def _table_hues() -> tuple[tuple[str, str, str], ...]:
    return tuple(palette.REFLEX_TABLE_HUES.values())


def test_reflex_page_tints_cover_the_shell_routes() -> None:
    """One tint per route, and every route distinct from its neighbours.

    A duplicated tint is the same defect ``test_page_and_panel_are_distinct``
    guards for the Bokeh canvas: nothing fails, every contrast row passes, and
    the signal the colour exists to carry is simply gone.
    """
    from helao.core.servers.reflex.app import SHELL_ROUTES

    assert set(palette.REFLEX_PAGE_TINTS) == set(SHELL_ROUTES)
    assert len(set(palette.REFLEX_PAGE_TINTS.values())) == len(SHELL_ROUTES)


def test_reflex_page_tint_shades_are_all_in_tw() -> None:
    missing = sorted(v for v in palette.REFLEX_PAGE_TINTS.values() if v not in TW)
    assert missing == [], f"tint names must be TW keys: {missing}"


def test_reflex_table_hue_shades_are_all_in_tw() -> None:
    names = [name for triple in _table_hues() for name in triple]
    assert sorted(n for n in names if n not in TW) == []


def test_reflex_table_hues_are_one_family_each() -> None:
    """A table's background, text and border come from one ramp.

    Mixing families would leave the header and its border reading as two
    unrelated signals rather than one object type.
    """
    for kind, (background, text, border) in palette.REFLEX_TABLE_HUES.items():
        families = {name.split("-")[0] for name in (background, text, border)}
        assert len(families) == 1, f"{kind} spans families {families}"


def test_reflex_table_hues_are_mutually_distinct() -> None:
    assert len({triple[0] for triple in _table_hues()}) == len(
        palette.REFLEX_TABLE_HUES
    )


def test_reflex_page_tint_is_not_the_bokeh_page_bg_constant() -> None:
    """The two canvases are separate constants even where they name a shade.

    ``PAGE_BG`` is the Bokeh page; ``REFLEX_PAGE_TINTS["/"]`` is the Reflex
    index. Both currently resolve to ``slate-50``, which is a coincidence of
    both wanting the faintest neutral -- moving one must not move the other, so
    neither is defined in terms of the other.
    """
    assert palette.PAGE_BG == TW["slate-50"]
    assert palette.REFLEX_PAGE_TINTS["/"] == "slate-50"
    assert isinstance(palette.REFLEX_PAGE_TINTS["/"], str)
    assert not palette.REFLEX_PAGE_TINTS["/"].startswith("#")


def test_reflex_class_helpers_emit_the_declared_utilities() -> None:
    assert palette.reflex_page_class("/live") == "bg-sky-50 min-h-screen"
    assert palette.reflex_page_class("/operator") == "bg-amber-50 min-h-screen"
    assert (
        palette.reflex_header_class("action")
        == "bg-cyan-100 text-cyan-700 py-1! h-auto!"
    )
    assert palette.reflex_table_class("action") == "border-l-[3px] border-cyan-600"
    assert palette.reflex_muted_text_class() == "text-slate-600"


def test_reflex_page_class_carries_min_h_screen_for_every_route() -> None:
    """Without it the tint stops at the content box and the page reads as two.

    Asserted per route rather than once, because the helper takes the route as
    an argument and a conditional could drop it for one of them.
    """
    for route in palette.REFLEX_PAGE_TINTS:
        assert palette.reflex_page_class(route).endswith(" min-h-screen")


def test_reflex_class_helpers_raise_on_an_unknown_key() -> None:
    """Loudly at build time, rather than an untinted page that looks unfinished."""
    with pytest.raises(KeyError):
        palette.reflex_page_class("/nope")
    with pytest.raises(KeyError):
        palette.reflex_header_class("nope")
    with pytest.raises(KeyError):
        palette.reflex_table_class("nope")


def test_gridjs_header_css_carries_the_browser_hue() -> None:
    """The one CSS rule the Reflex stack needs, pinned to the same two shades.

    It exists because ``rx.data_table`` drops ``class_name`` and gridjs's own
    ``th.gridjs-th`` is unlayered, so a Tailwind utility can reach neither the
    element nor a winning cascade position. Asserting the shades here keeps that
    rule from drifting away from ``REFLEX_TABLE_HUES["browser"]``, which is the
    only reason it is allowed to hold literals at all.
    """
    css = palette.reflex_gridjs_header_css()
    background, text, _ = palette.REFLEX_TABLE_HUES["browser"]
    assert f"background-color: {TW[background]}" in css
    assert f"color: {TW[text]}" in css
    assert TW[background] == "#d1fae5"
    assert TW[text] == "#047857"


def test_gridjs_header_css_outranks_gridjs_on_specificity() -> None:
    """Not on source order, which ``head_components`` does not control.

    gridjs declares ``th.gridjs-th`` (0,1,1) and ``th.gridjs-th-sort:hover``
    (0,2,1). Every selector here adds ``.gridjs-container``, so the resting rule
    is (0,2,1) and the hover rule (0,3,1) -- each strictly above the rule it has
    to beat, whichever stylesheet the browser happens to parse first.
    """
    css = palette.reflex_gridjs_header_css()
    selectors = [part.strip() for part in css.split("{")[0].split(",")]
    assert len(selectors) == 3
    assert all(part.startswith(".gridjs-container ") for part in selectors)
    assert any(":hover" in part for part in selectors)
    assert any(":focus" in part for part in selectors)


def test_gridjs_hover_does_not_reintroduce_a_grey_header() -> None:
    """One declaration block, so hover cannot fall back to gridjs's grey.

    The alternative -- ``emerald-200`` for hover -- measures 4.28 against
    ``emerald-700`` and would need a standing contrast exception, so the resting
    fill is repeated and the pointer cursor carries the affordance.
    """
    css = palette.reflex_gridjs_header_css()
    assert css.count("{") == 1, "hover must share the resting declaration block"
    assert contrast_ratio(TW["emerald-700"], "#a7f3d0") == pytest.approx(4.28, abs=0.01)
    assert contrast_ratio(TW["emerald-700"], "#a7f3d0") < FLOOR_BODY_TEXT


REFLEX_STACK_GLOBS: Final[tuple[str, ...]] = (
    "helao/core/servers/reflex/**/*.py",
    "helao/core/servers/operator/app_reflex.py",
    "helao/core/servers/data_browser/app_reflex.py",
    "helao/deploy/*/servers/reflex/**/*.py",
)


def test_no_muted_slate_500_remains_in_the_reflex_stack() -> None:
    """``text-slate-500`` fails the body floor on two of the five route tints.

    A grep rather than a computed-style check because the failure mode is a
    *source* one: the utility renders perfectly, it is simply too light. Globbed
    so a panel added later cannot reintroduce it, and it names no deployment.
    """
    offenders: list[str] = []
    for pattern in REFLEX_STACK_GLOBS:
        for path in REPO_ROOT.glob(pattern):
            for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1
            ):
                if "text-slate-500" in line:
                    offenders.append(f"{_relative(path)}:{lineno}")
    assert offenders == [], (
        "muted text in the Reflex stack must be text-slate-600; slate-500 is "
        f"4.34 on violet-50, under the 4.5 body floor:\n  " + "\n  ".join(offenders)
    )


def test_the_reflex_stack_glob_actually_matches_files() -> None:
    """A guard on the guard: a typo'd glob makes the sweep above vacuous."""
    for pattern in REFLEX_STACK_GLOBS:
        assert list(REPO_ROOT.glob(pattern)), f"{pattern} matched nothing"


#: Reflex components on which Radix ``size`` is a *font* size. The distinction
#: matters: on ``rx.button``/``rx.select``/``rx.input`` the same keyword is a
#: component token driving padding and control height, so it is deliberately
#: not swept -- shrinking one would change control geometry, not type size.
REFLEX_TEXT_COMPONENTS: Final[frozenset[str]] = frozenset(
    {
        "rx.text",
        "rx.heading",
        "rx.table.cell",
        "rx.table.column_header_cell",
        "rx.code",
        "rx.badge",
    }
)

#: Radix's text scale is 12/14/16/18/20/24px for sizes 1-6, so ``"1"`` is
#: exactly the 12px floor and there is nothing legal below it.
REFLEX_MIN_TEXT_SIZE: Final[int] = 1


def _dotted_call_name(node: ast.expr) -> str | None:
    """Return ``rx.table.cell`` for the callee of such a call, else ``None``."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def test_no_reflex_text_size_is_below_the_12px_floor() -> None:
    """No text-bearing Reflex component may carry a ``size`` under ``"1"``.

    The floor is enforced rather than trusted, because the failure is invisible
    from the source: ``size="0"`` is not an error Reflex raises, it just renders
    below the 12px the type scale bottoms out at. AST-driven so each ``size`` is
    attributed to the component that owns it -- a grep cannot tell a multi-line
    ``rx.text(..., size="1")`` from an ``rx.button(..., size="1")`` and would
    police the buttons this deliberately leaves alone.
    """
    offenders: list[str] = []
    seen = 0
    for pattern in REFLEX_STACK_GLOBS:
        for path in sorted(REPO_ROOT.glob(pattern)):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = _dotted_call_name(node.func)
                if name not in REFLEX_TEXT_COMPONENTS:
                    continue
                for kw in node.keywords:
                    if kw.arg != "size":
                        continue
                    if not isinstance(kw.value, ast.Constant) or not isinstance(
                        kw.value.value, str
                    ):
                        # A Var-driven size cannot be checked statically; the
                        # floor then has to be argued at the call site.
                        continue
                    seen += 1
                    where = f"{_relative(path)}:{kw.value.lineno}"
                    if not kw.value.value.isdigit():
                        offenders.append(f"{where} {name} size={kw.value.value!r}")
                    elif int(kw.value.value) < REFLEX_MIN_TEXT_SIZE:
                        offenders.append(f"{where} {name} size={kw.value.value!r}")
    assert offenders == [], (
        f'Radix size "{REFLEX_MIN_TEXT_SIZE}" is the 12px floor of the text '
        "scale; nothing may render smaller:\n  " + "\n  ".join(offenders)
    )
    assert seen, "swept no text-component size= at all, so this proves nothing"


def test_gridjs_header_css_trims_vertical_padding_only() -> None:
    """The header's height complaint is fixed here, and only vertically.

    gridjs's own ``th.gridjs-th`` sets ``14px``, measured as a 52.5px header row
    against 49px body rows. This rule is the only thing that can override it (a
    utility loses to unlayered CSS; see the function's docstring), so the padding
    has to ride along with the hue.

    The shorthand is asserted *absent*: ``padding: 4px`` would collapse gridjs's
    24px horizontal padding too, narrowing every column -- a change nobody asked
    for and one no colour test would have caught.
    """
    css = palette.reflex_gridjs_header_css()
    pad = palette.GRIDJS_HEADER_PAD_Y
    assert f"padding-top: {pad}" in css
    assert f"padding-bottom: {pad}" in css
    assert re.search(r"[;{]\s*padding:", css) is None, "must not use the shorthand"
    assert "padding-left" not in css and "padding-right" not in css


# --- typefaces -------------------------------------------------------------
#: The CSS generic font families. A stack ending in one of these is guaranteed
#: to resolve to *something* the browser has locally; a stack ending in a named
#: family is not. https://drafts.csswg.org/css-fonts-4/#generic-font-families
CSS_GENERIC_FAMILIES = frozenset(
    {
        "serif",
        "sans-serif",
        "monospace",
        "cursive",
        "fantasy",
        "system-ui",
        "ui-serif",
        "ui-sans-serif",
        "ui-monospace",
        "ui-rounded",
        "math",
        "emoji",
        "fangsong",
    }
)


def _stack_entries(stack: str) -> list[str]:
    """Split a ``font-family`` value into its families, unquoted."""
    return [entry.strip().strip("\"'") for entry in stack.split(",")]


@pytest.mark.parametrize(
    "name",
    ["UI_FONT_STACK", "INPUT_FONT_STACK", "UI_FONT_FALLBACK", "INPUT_FONT_FALLBACK"],
)
def test_font_stacks_end_in_a_generic_family(name: str) -> None:
    """**The offline guarantee, and the reason it is a construction not a check.**

    Stations frequently run with no route to the internet, so both ``@import``
    lines can simply fail — and a failed ``@import`` means only that the first
    family in a stack is unavailable, which is the case CSS fallback already
    exists for. That makes the *last* entry the promise: a generic family always
    resolves to something installed, a named one does not.

    Asserted rather than trusted because the failure mode is invisible from the
    source. An editor who appends a favourite face, or trims the tail as
    "redundant", leaves every offline station rendering in whatever the
    browser's last-resort font happens to be — on the machine where the edit was
    made, with the webfont cached, nothing looks wrong at all.
    """
    stack = getattr(palette, name)
    entries = _stack_entries(stack)
    assert len(entries) >= 2, f"{name} has no fallback at all: {stack!r}"
    assert entries[-1] in CSS_GENERIC_FAMILIES, (
        f"{name} ends in {entries[-1]!r}, which is a named family. The last "
        f"entry must be one of the CSS generics or an offline station has no "
        f"guaranteed font: {stack!r}"
    )


def test_the_two_font_roles_are_different_stacks() -> None:
    """A single stack for both roles would silently drop the input/UI split."""
    assert palette.UI_FONT_STACK != palette.INPUT_FONT_STACK
    assert _stack_entries(palette.UI_FONT_STACK)[-1] == "sans-serif"
    assert _stack_entries(palette.INPUT_FONT_STACK)[-1] == "monospace"


def test_each_stack_leads_with_the_family_its_import_provides() -> None:
    """The webfont's own family name, which is not always the obvious one.

    ``iosevka.css`` names its faces ``Iosevka Web``; a stack asking only for
    ``Iosevka`` ignores the webfont entirely and falls through to
    ``ui-monospace`` — except on a machine with Iosevka installed locally, where
    it looks right and the defect is invisible.
    """
    ui = _stack_entries(palette.UI_FONT_STACK)
    assert ui[0] == "IBM Plex Sans Condensed"
    assert "family=IBM+Plex+Sans+Condensed" in palette.UI_FONT_IMPORT

    inp = _stack_entries(palette.INPUT_FONT_STACK)
    assert inp[0] == "Iosevka Web", "the family iosevka.css actually defines"
    assert inp[1] == "Iosevka", "a locally installed copy, for offline stations"
    assert "iosevka" in palette.INPUT_FONT_IMPORT


def test_the_ui_import_asks_for_display_swap() -> None:
    """Without it a dead network holds the text invisible instead of falling back."""
    assert "display=swap" in palette.UI_FONT_IMPORT


def test_font_import_css_emits_imports_and_nothing_else() -> None:
    """``@import`` is only valid before every style rule in its stylesheet.

    A rule sneaking in ahead of one makes the browser drop it silently, leaving
    both families unavailable and both stacks quietly on their fallbacks.
    """
    css = palette.font_import_css()
    lines = [line.strip() for line in css.splitlines() if line.strip()]
    assert lines, "emitted nothing"
    assert all(line.startswith("@import") for line in lines), css
    assert "{" not in css


def test_reflex_font_css_puts_its_imports_before_any_rule() -> None:
    css = palette.reflex_font_css()
    assert css.index("@import") < css.index("{")
    first_rule = css.index("{")
    assert css.count("@import", 0, first_rule) == 2


def test_reflex_font_css_overrides_both_frameworks_font_tokens() -> None:
    """Radix and Tailwind each own a token that decides the resolved family.

    Radix declares ``--default-font-family`` on ``.radix-themes`` — unlayered,
    so a ``:root`` override loses to it on specificity and the page stays on
    ``-apple-system``. Tailwind declares ``--font-sans`` in ``@layer theme``.
    Missing either one leaves half the page on the old face.
    """
    css = palette.reflex_font_css()
    assert f"--font-sans: {palette.UI_FONT_STACK}" in css
    assert f"--font-mono: {palette.INPUT_FONT_STACK}" in css
    for token in (
        "--default-font-family",
        "--heading-font-family",
        "--strong-font-family",
        "--em-font-family",
        "--quote-font-family",
    ):
        assert f"{token}: {palette.UI_FONT_STACK}" in css, token
    assert f"--code-font-family: {palette.INPUT_FONT_STACK}" in css
    assert ".radix-themes" in css


def test_reflex_font_css_outranks_radix_on_specificity() -> None:
    """Every selector is class-qualified under ``html``, not bare.

    ``head_components`` does not control where this lands relative to the
    bundled Radix stylesheet, so the rules cannot rely on source order. A bare
    ``input`` is (0,0,1) and loses to Radix's own single-class rule on its
    field; ``html .rt-TextFieldInput`` is (0,1,1) and wins either way.
    """
    css = palette.reflex_font_css()
    body = css[css.index("{") :]
    selectors = [
        part.strip()
        for chunk in body.split("}")
        if "{" in chunk
        for part in chunk[: chunk.index("{")].split(",")
        if part.strip()
    ]
    assert selectors
    for selector in selectors:
        assert selector == "html" or selector.startswith("html "), selector


def test_reflex_font_css_gives_text_fields_the_input_font() -> None:
    css = palette.reflex_font_css()
    rule = css.rsplit("{", 1)
    assert palette.INPUT_FONT_STACK in rule[1]
    for target in ("input", "textarea", "select", ".rt-TextFieldInput"):
        assert target in rule[0].rsplit("}", 1)[-1], target


def test_reflex_header_class_carries_the_height_trim() -> None:
    """Both utilities, both important, for every hue.

    ``py-1`` alone cannot move the height: Radix sets
    ``height: var(--table-cell-min-height)`` (36px) on ``.rt-TableCell``, and
    ``height`` on a table cell is a minimum. Measured — trimming the padding
    from 8px to 4px on its own left the cell at exactly 36px. And without the
    trailing ``!`` neither utility applies at all, because Radix is unlayered
    while Tailwind utilities are in ``@layer utilities``.
    """
    assert palette.REFLEX_HEADER_TRIM == "py-1! h-auto!"
    for kind in palette.REFLEX_TABLE_HUES:
        emitted = palette.reflex_header_class(kind)
        assert emitted.endswith(palette.REFLEX_HEADER_TRIM), kind
        for utility in palette.REFLEX_HEADER_TRIM.split():
            assert utility.endswith("!"), utility


def test_gridjs_header_css_sets_the_header_font_size() -> None:
    """gridjs takes no Radix ``size`` prop, so this rule is the only route.

    Measured 16px against 12px page body text before; 14px is one step above
    the body, which is what a header wants.
    """
    css = palette.reflex_gridjs_header_css()
    assert f"font-size: {palette.GRIDJS_HEADER_FONT_SIZE}" in css
    size = palette.GRIDJS_HEADER_FONT_SIZE
    assert size.endswith("px")
    assert 12 <= int(size.removesuffix("px")) <= 16


def test_gridjs_header_padding_cannot_clip_its_content() -> None:
    """``4px`` is slack, not a squeeze, so the label and sort icon stay whole.

    The tallest thing a header can hold is the sort button, and gridjs gives it
    a flat ``height: 24px`` that no font size touches -- so 24px is the content
    box to clear, and the padding only ever adds to it. Pinned as a number
    because the safety of the value is the whole argument for it: 24 + 2*4 +
    0.5px border measured 32.5px in-browser, down from 52.5px, with the sort
    icon 4px clear of each edge.

    A header *without* a sort button is shorter still, and got shorter again
    when :data:`~helao.core.servers.palette.GRIDJS_HEADER_FONT_SIZE` brought the
    label to 14px: its 21px line box measured 29.5px overall. The 24px figure
    below is deliberately the worst case rather than that one.
    """
    pad = palette.GRIDJS_HEADER_PAD_Y
    assert pad.endswith("px")
    pad_px = int(pad.removesuffix("px"))
    assert 0 <= pad_px < 14, "must trim gridjs's 14px without going negative"
    content_px = 24
    assert content_px + 2 * pad_px == 32


def test_exceptions_registry_is_empty() -> None:
    """Pinned so the registry cannot quietly grow to absorb regressions.

    Every declared pair meets its floor on its own merits, so nothing needs an
    exception. This started as a single entry (the "Non-queued" plan panel at
    1.12 against the 1.20 surface floor) and was closed by lifting that panel
    from ``sky-200`` to ``sky-100``. Adding an entry here is a deliberate act
    that has to be argued for at review — which is the point of asserting the
    empty case rather than deleting the mechanism.
    """
    assert ACCEPTED_CONTRAST_EXCEPTIONS == {}


def test_every_accepted_exception_is_a_declared_row() -> None:
    declared = (
        set(SURFACE_ROWS)
        | set(HEADING_ROWS)
        | set(BODY_TEXT_ROWS)
        | set(BUTTON_SURFACE_ROWS)
        | set(BUTTON_LABEL_ROWS)
        | set(PAGE_TINT_TEXT_ROWS)
        | set(REFLEX_HEADER_ROWS)
        | set(REFLEX_BORDER_ROWS)
    )
    assert set(ACCEPTED_CONTRAST_EXCEPTIONS) <= declared


# ===========================================================================
# 4. The six-rule AST sweeper
# ===========================================================================
# Rule 1's keyword allowlist. For each of these the *entire value subtree* is
# walked, not just the direct value node: styles={"color": "#566573"} is a Dict,
# line_color=(255, 0, 0) is a Tuple, and css=("..." "...") is an implicit
# concatenation.
COLOR_KEYWORDS: Final[frozenset[str]] = frozenset(
    {
        "line_color",
        "fill_color",
        "text_color",
        "background_fill_color",
        "color",
        "background",
        "styles",
        "css",
        "class_name",
        "color_scheme",
        "stylesheets",
        "code",
        "text",
    }
)

# Rule 2's literal shapes, matched anywhere. AST-based rather than a text
# regex because a regex false-positives on real sites in the swept set
# (mfc_vis.py's "blue rolling-mean line" docstring, colorama, .hexdigest(),
# --color=no, and "#" in URLs).
_HEX_RE: Final[re.Pattern[str]] = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_RGB_RE: Final[re.Pattern[str]] = re.compile(r"\brgb\(")
_DECL_RE: Final[re.Pattern[str]] = re.compile(r"(?:background-)?color\s*:")

# CSS colour names are only looked for under an allowlisted keyword or a
# colour-named assignment, never file-wide. File-wide name matching is what
# would flag mfc_vis.py's "blue rolling-mean line" docstring.
# A bare CSS colour name, NOT a colour word embedded in a compound token.
#
# `\b` treats `-` as a word boundary, so a naive `\b(red|white|...)\b` matches
# "red" inside "text-red-600" and "white" inside "text-white" — i.e. it flags the
# exact Tailwind utility strings the spec *prescribes* for the red-text and
# E-STOP mappings, making AC2's whole-tree gate unsatisfiable by construction.
# The hyphen-flank guard below is why: a match may not be preceded or followed by
# a word character or a hyphen.
#
# This is a token-boundary fix rather than a `class_name`-specific exemption,
# because the same collision reaches any keyword that can carry a compound
# identifier — `class_name`, `css`, `code`, `text`, `stylesheets`. Note it only
# affects *name* matching: rule 2's hex regex still fires inside a class string,
# so a Tailwind arbitrary value like `text-[#ff0000]` is still correctly flagged.
#
# Kept matching: `"red"`, `["red", "blue"]`, `line_color="red"`, `color: red;`,
# `color:red`. Now excluded: `text-red-600`, `bg-red-900`, `text-white`,
# `hover:bg-red-950`.
_NAME_RE: Final[re.Pattern[str]] = re.compile(
    r"(?<![\w-])(black|white|red|blue|green|orange|purple|violet|cyan|magenta"
    r"|gray|grey|yellow|pink|brown|lime|navy|teal|olive|silver|maroon|gold)"
    r"(?![\w-])"
)

# Rule 3: an Assign at *any* scope, since the real lists are function-local
# rather than module-level. Full-match, not search: `color_callback_js = ...`
# holds no colour and must not be flagged.
_ASSIGN_TARGET_RE: Final[re.Pattern[str]] = re.compile(
    r"colou?rs?|palette|.*_style(?:sheet)?"
)

# Rule 6: the two source-of-truth modules are exempt by **exact path**, not
# basename, so a deployment file named palette.py does not inherit it. These
# are the modules that are supposed to hold literals: palette.py is nothing but
# hex values plus the shade table, and bokeh_theme.py's GLOBAL_CSS is
# hand-authored CSS whose declarations match rule 2. Without the exemption the
# whole-tree sweep could never reach zero — it would fail on its first run,
# against the file the palette phase just wrote.
SWEEP_EXEMPT_PATHS: Final[tuple[str, ...]] = (
    "helao/core/servers/palette.py",
    "helao/core/servers/bokeh_theme.py",
)

# Rule 4: a named per-site allowlist for ColumnDataSource *column-name*
# references. These two are color="color" — a column name, not a colour.
SWEEP_EXEMPT_SITES: Final[frozenset[tuple[str, int]]] = frozenset(
    {
        ("helao/deploy/hte/servers/visualizer/spec_vis.py", 311),
        ("helao/deploy/hte/servers/visualizer/spec_vis.py", 319),
    }
)


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _scan_line(text: str, match_names: bool) -> str | None:
    for pattern in (_HEX_RE, _RGB_RE, _DECL_RE):
        found = pattern.search(text)
        if found:
            return found.group(0)
    if match_names:
        found = _NAME_RE.search(text)
        if found:
            return found.group(0)
    return None


def _span_hits(
    node: ast.AST, lines: list[str], match_names: bool, into: dict[int, str]
) -> None:
    """Record every physical line in *node*'s span that carries a colour.

    Per-line rather than per-node because CPython folds implicitly concatenated
    strings into a single Constant: ``css=("...#7B0000..." "...#5A0000..."
    "...#5A0000...")`` is one node, but the three literals sit on three lines
    and each is a separate site to fix.
    """
    start = getattr(node, "lineno", None)
    if start is None:
        return
    end = getattr(node, "end_lineno", start) or start
    for lineno in range(start, min(end, len(lines)) + 1):
        hit = _scan_line(lines[lineno - 1], match_names)
        if hit is not None:
            into.setdefault(lineno, hit)


def _rgb_tuple_hits(node: ast.AST, into: dict[int, str]) -> None:
    """RGB tuples carry no colour-shaped *text*, so they are found structurally."""
    for sub in ast.walk(node):
        if isinstance(sub, (ast.Tuple, ast.List)):
            ints = [
                element.value
                for element in sub.elts
                if isinstance(element, ast.Constant) and isinstance(element.value, int)
            ]
            if len(ints) >= 3 and all(0 <= value <= 255 for value in ints[:4]):
                into.setdefault(sub.lineno, f"({', '.join(str(i) for i in ints)})")


def _assigned_name(target: ast.expr) -> str | None:
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


def sweep_color_literals(paths) -> list[tuple[Path, int, str]]:
    """Return every raw-colour site in *paths* as ``(path, line, literal)``.

    Exported as a path-list entry point so each sweep phase can run it over its
    own absolute paths; the glob-driven pytest test is a thin wrapper. Without
    this, per-phase acceptance checks would be unusable, because the whole-tree
    sweep stays red until the last phase lands.
    """
    findings: list[tuple[Path, int, str]] = []
    for raw in paths:
        path = Path(raw)
        relative = _relative(path)
        if relative in SWEEP_EXEMPT_PATHS:  # rule 6
            continue
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines()
        tree = ast.parse(source, filename=str(path))
        hits: dict[int, str] = {}

        for node in ast.walk(tree):
            # rule 1 — allowlisted keyword, whole value subtree
            if isinstance(node, ast.keyword) and node.arg in COLOR_KEYWORDS:
                if isinstance(node.value, ast.Constant) and node.value.value is None:
                    # rule 4: the None exemption is keyword-scoped, not
                    # line-scoped. A line carrying both color=None and
                    # line_color="black" keeps the second as a finding.
                    continue
                _span_hits(node, lines, True, hits)
                _rgb_tuple_hits(node.value, hits)

            # rule 3 — colour-named assignment at any scope
            elif isinstance(node, ast.Assign):
                if any(
                    (name := _assigned_name(target)) is not None
                    and _ASSIGN_TARGET_RE.fullmatch(name)
                    for target in node.targets
                ):
                    _span_hits(node.value, lines, True, hits)
                    _rgb_tuple_hits(node.value, hits)
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                name = _assigned_name(node.target)
                if name is not None and _ASSIGN_TARGET_RE.fullmatch(name):
                    _span_hits(node.value, lines, True, hits)
                    _rgb_tuple_hits(node.value, hits)

            # rule 2 — literal shape anywhere, names excluded
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                _span_hits(node, lines, False, hits)
            elif isinstance(node, ast.JoinedStr):
                if any(
                    isinstance(part, ast.Constant) and isinstance(part.value, str)
                    for part in node.values
                ):
                    _span_hits(node, lines, False, hits)

        findings.extend(
            (path, lineno, hits[lineno])
            for lineno in sorted(hits)
            if (relative, lineno) not in SWEEP_EXEMPT_SITES
        )
    return findings


def test_exemption_list_holds_exactly_two_entries() -> None:
    """Pinned by exact path so the exemption cannot quietly grow."""
    assert SWEEP_EXEMPT_PATHS == (
        "helao/core/servers/palette.py",
        "helao/core/servers/bokeh_theme.py",
    )
    assert len(SWEEP_EXEMPT_PATHS) == 2
    assert all(
        "/" in entry for entry in SWEEP_EXEMPT_PATHS
    ), "exemptions are by exact path, not basename"


def test_palette_module_is_exempt_from_its_own_sweep() -> None:
    assert sweep_color_literals([REPO_ROOT / "helao/core/servers/palette.py"]) == []


def test_a_deployment_palette_py_does_not_inherit_the_exemption(tmp_path) -> None:
    decoy = tmp_path / "palette.py"
    decoy.write_text('x = Div(styles={"color": "#123456"})\n')
    assert [line for _, line, _ in sweep_color_literals([decoy])] == [1]


def test_sweeper_skips_absent_paths() -> None:
    assert (
        sweep_color_literals([REPO_ROOT / "helao/core/servers/no_such_file.py"]) == []
    )


# --- fixture calibration ---------------------------------------------------
# Verbatim snapshots of five files as they existed when the palette module was
# written, with complete expected-findings manifests. Two properties make this
# work where the obvious version does not: it runs against the **fixtures, not
# the live tree**, so it survives the later phases that edit those same five
# files; and each manifest is **complete, not illustrative**, because a
# nine-of-seventeen example list is satisfied by a sweeper that still misses
# the other eight.
FIXTURE_MANIFESTS: Final[dict[str, list[int]]] = {
    # color=None at :2415 is exempt but line_color="black" on the same line is
    # not, so :2415 appears; :2600 carries only color=None and does not.
    # :901 is background="#D6DBDF" — a live site the plan's manifest omitted.
    # :692 and :760 carry the same literal *commented out* and are correctly
    # absent, which a text regex could not manage.
    "bokeh_operator.py.txt": [
        177, 374, 386, 412, 413, 414, 545, 557, 565, 677, 689, 716, 730, 744,
        779, 823, 891, 901, 1156, 1212, 1218, 1301, 1316, 1353, 2131, 2146,
        2148, 2150, 2197, 2415, 2602,
    ],  # fmt: skip
    "data_browser_app.py.txt": [78, 277],
    # :235-236 is a docstring reading "blue rolling-mean line" and must not be
    # flagged; :245 is the function-local trace list, :266 the rolling mean.
    "mfc_vis.py.txt": [154, 245, 266],
    # The matplotlib colormap calls hold no literal; only the panel does. The
    # live file's :311/:319 color="color" column names are exempt by site and
    # would not match anyway.
    "spec_vis.py.txt": [160],
    # :93 is a trailing comment "# success: green, danger: red" — AST-invisible.
    "gpsim_live_vis.py.txt": [133, 213],
}


def test_fixture_snapshots_are_present() -> None:
    assert sorted(p.name for p in FIXTURE_DIR.glob("*.py.txt")) == sorted(
        FIXTURE_MANIFESTS
    )


@pytest.mark.parametrize("fixture", sorted(FIXTURE_MANIFESTS))
def test_sweeper_calibration(fixture: str) -> None:
    """A sweeper reporting green over an unedited operator module is broken."""
    path = FIXTURE_DIR / fixture
    found = sorted(line for _, line, _ in sweep_color_literals([path]))
    expected = sorted(FIXTURE_MANIFESTS[fixture])
    missing = sorted(set(expected) - set(found))
    extra = sorted(set(found) - set(expected))
    assert (
        found == expected
    ), f"{fixture}: sweeper missed {missing} and falsely flagged {extra}"


def test_calibration_covers_the_known_false_positives() -> None:
    """The two sites a text regex gets wrong stay clean."""
    mfc = sweep_color_literals([FIXTURE_DIR / "mfc_vis.py.txt"])
    assert {line for _, line, _ in mfc} & {235, 236} == set()
    operator = sweep_color_literals([FIXTURE_DIR / "bokeh_operator.py.txt"])
    lines = {line for _, line, _ in operator}
    assert 2600 not in lines, "color=None alone is exempt"
    assert 2415 in lines, "line_color='black' beside color=None is still a finding"
    assert {692, 760} & lines == set(), "commented-out literals are not findings"


def test_column_name_sites_are_not_flagged() -> None:
    """spec_vis.py's color="color" is a column name, not a colour."""
    findings = sweep_color_literals([FIXTURE_DIR / "spec_vis.py.txt"])
    assert {line for _, line, _ in findings} & {311, 319} == set()


# --- whole-tree wrapper ----------------------------------------------------
def test_no_raw_color_literals_anywhere() -> None:
    """EXPECTED TO FAIL until the final sweep phase lands.

    This is the AC2 gate. It is deliberately **not** marked ``xfail`` or
    ``skip``: a marker that has to be removed later is a stub that passes
    green, and the point of this test is to stay visibly red until every
    module actually resolves its colours through the palette. Its failure
    while the sweep phases are outstanding is the expected state, not a
    regression — read the listed sites as the remaining work.

    Globbed rather than a frozen file list so a newly added visualizer cannot
    slip past, and it names no deployment: this repo is a public remote.
    """
    targets = sorted(
        {
            *REPO_ROOT.glob("helao/deploy/*/servers/**/*.py"),
            *REPO_ROOT.glob("helao/core/servers/**/*.py"),
        }
    )
    findings = sweep_color_literals(targets)
    rendered = "\n".join(
        f"  {_relative(path)}:{line}  {literal}" for path, line, literal in findings
    )
    assert findings == [], (
        f"{len(findings)} raw colour literals remain across "
        f"{len({p for p, _, _ in findings})} modules. This test is EXPECTED TO "
        f"FAIL until the final sweep phase lands; every site below must resolve "
        f"through helao.core.servers.palette:\n{rendered}"
    )


# ---------------------------------------------------------------------------
# Section borders and the CSS-side font sizes
# ---------------------------------------------------------------------------
# The three checks below all guard failures that are invisible from the source
# and silent in the browser, which is the recurring shape of every defect this
# module has caught.


def _bokeh_layout_sources() -> list[Path]:
    """Return every non-test module that can build a Bokeh section layout.

    Deployment paths are globbed, never named: this file is tracked in a public
    repo and the deployments under ``helao/deploy`` other than ``hte`` and
    ``test`` are separate private repositories. An absent path simply yields
    nothing.
    """
    paths: set[Path] = set()
    for pattern in ("helao/**/servers/**/*.py", "helao/**/layouts/**/*.py"):
        for path in REPO_ROOT.glob(pattern):
            if "/tests/" in path.as_posix():
                continue
            paths.add(path)
    return sorted(paths)


def test_panel_styles_carries_the_background_as_well_as_the_border() -> None:
    """``panel_styles`` must emit ``background-color``, not only ``border``.

    The regression this pins is a *silent* one, and it nearly shipped. Bokeh 3's
    ``LayoutDOM.background`` is a write-only alias that assigns
    ``styles["background-color"]``, and a ``styles=`` kwarg **replaces** that
    dict rather than merging into it. So a section written as
    ``layout(..., background=PANEL_BG, styles=panel_styles())`` keeps only the
    border and loses its fill — measured on Bokeh 3.9.1 as
    ``{'border': '1px solid #94a3b8'}``, with nothing raised on either side and
    every section panel rendering unpainted.

    Carrying both declarations in one dict is what makes that unrepresentable,
    so the call sites pass no ``background=`` at all. See
    ``test_no_section_layout_still_uses_the_background_kwarg``.
    """
    styles = palette.panel_styles(palette.PANEL_BG)
    assert styles["background-color"] == palette.PANEL_BG
    assert (
        styles["border"] == f"{palette.PANEL_BORDER_WIDTH} solid {palette.PANEL_BORDER}"
    )
    custom = palette.panel_styles(palette.PANEL_BG, palette.TW["slate-800"])
    assert custom["background-color"] == palette.PANEL_BG, "background must survive"
    assert palette.TW["slate-800"] in custom["border"]


# Names a *section* background is referred to by at a Bokeh call site. The
# shared roles plus the per-layout aliases the two aligners declare for their own
# panels -- those are sections too, and each takes its own darker border.
#
# Deliberately does NOT include the operator's param-input blocks
# (`background=self.color_sq_param_inputs`): those are small tinted blocks
# *inside* the Params section, one per parameter, not sections themselves.
# Outlining every one of them would be noise, so they keep the plain kwarg.
SECTION_BACKGROUND_NAMES: Final[frozenset[str]] = frozenset(
    {
        "PANEL_BG",
        "PLAN_PANEL_NONQUEUED_BG",
        "_PANEL_BG",
        "_MOTOR_PANEL_BG",
        "_ARROW_PANEL_BG",
        "_JOG_PANEL_BG",
    }
)


def test_no_layout_passes_both_background_and_styles() -> None:
    """A Bokeh layout may never carry ``background=`` and ``styles=`` together.

    This is the silent clobber, stated as an invariant: the two kwargs write the
    same inline dict and the second wins outright, so whichever is listed first
    is discarded with nothing raised. See
    ``test_panel_styles_carries_the_background_as_well_as_the_border`` for the
    measurement.

    Scoped to ``layout``/``column``/``row`` so a ``background=`` on a ``Spacer``
    -- a divider bar, which takes no ``styles`` -- is left alone.
    """
    offenders: list[str] = []
    for path in _bokeh_layout_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _dotted_call_name(node.func) not in ("layout", "column", "row"):
                continue
            kwargs = {kw.arg for kw in node.keywords}
            if {"background", "styles"} <= kwargs:
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
    assert not offenders, (
        "background= and styles= overwrite each other, so one of the two is "
        "silently lost:\n  " + "\n  ".join(offenders)
    )


def test_every_section_background_is_routed_through_panel_styles() -> None:
    """A section's fill must reach Bokeh via ``panel_styles``, not ``background=``.

    Without this, a newly added visualizer panel renders unbordered and nothing
    says so -- the sweep that added the borders would simply have skipped it.
    Names rather than values because the call site refers to the role by name;
    see :data:`SECTION_BACKGROUND_NAMES` for what is deliberately excluded.
    """
    offenders: list[str] = []
    for path in _bokeh_layout_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _dotted_call_name(node.func) not in ("layout", "column", "row"):
                continue
            for kw in node.keywords:
                if kw.arg != "background":
                    continue
                name = kw.value.id if isinstance(kw.value, ast.Name) else None
                if name in SECTION_BACKGROUND_NAMES:
                    offenders.append(
                        f"{path.relative_to(REPO_ROOT)}:{node.lineno} "
                        f"background={name}"
                    )
    assert not offenders, (
        "a section fill must be passed as styles=panel_styles(<bg>) so the "
        "section also gets its border:\n  " + "\n  ".join(offenders)
    )


def test_section_background_sweep_actually_reaches_the_bokeh_sources() -> None:
    """A guard on the two guards above: the file sweep must not be empty.

    Both tests pass trivially if the globs match nothing -- the same
    failure mode the Reflex-stack glob test exists for. Anchored on the
    operator, which is the Bokeh UI named by the most configs, and on a count
    that a moved directory would break.
    """
    found = {p.relative_to(REPO_ROOT).as_posix() for p in _bokeh_layout_sources()}
    assert "helao/core/servers/operator/bokeh_operator.py" in found
    assert len(found) >= 20, f"only {len(found)} Bokeh layout sources swept"
    assert any(
        "panel_styles" in p.read_text(encoding="utf-8") for p in _bokeh_layout_sources()
    )


def test_css_font_sizes_respect_the_text_floor() -> None:
    """The two CSS-side sizes may not drop below :data:`palette.TEXT_FLOOR_PX`.

    These are the sizes that cannot be expressed as a Radix ``size`` prop -- an
    input's size is geometry, and gridjs takes no size prop at all -- so the
    ``size=``-based floor test cannot see them. Stepping either one further down
    the type scale is the plausible future edit, and 10px on an instrument
    screen is the thing to stop.
    """
    for name in ("INPUT_FONT_SIZE", "TABLE_BODY_FONT_SIZE"):
        raw = getattr(palette, name)
        assert raw.endswith("px"), f"{name} must be a px length, got {raw!r}"
        assert (
            int(raw.removesuffix("px")) >= palette.TEXT_FLOOR_PX
        ), f"{name} is {raw}, below the {palette.TEXT_FLOOR_PX}px floor"


def test_table_body_css_leaves_radix_headers_alone() -> None:
    """The body-size rule must not reach a Radix column header.

    Radix renders a ``<th>`` as ``class="rt-TableCell rt-TableColumnHeaderCell"``
    and ``.rt-TableColumnHeaderCell`` adds only ``font-weight: 700`` -- no size of
    its own. So any ``.rt-TableCell`` selector here would resize every Radix
    column header along with the body, and the headers are the part that already
    reads correctly. The rule is gridjs-only; this is the guard on that.
    """
    css = palette.reflex_table_body_css()
    assert "gridjs-td" in css, "the gridjs body rule is the point of this function"
    assert "rt-TableCell" not in css, (
        "a .rt-TableCell selector also matches every Radix column header; "
        "keep this rule scoped to gridjs"
    )
    assert palette.TABLE_BODY_FONT_SIZE in css
