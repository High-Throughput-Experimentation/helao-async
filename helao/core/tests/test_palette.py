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
    "teal-500": "#14b8a6",
    "teal-600": "#0d9488",
    "teal-700": "#0f766e",
    "cyan-400": "#22d3ee",
    "cyan-500": "#06b6d4",
    "cyan-600": "#0891b2",
    "cyan-700": "#0e7490",
    "sky-100": "#e0f2fe",
    "sky-200": "#bae6fd",
    "sky-500": "#0ea5e9",
    "sky-600": "#0284c7",
    "sky-700": "#0369a1",
    "blue-600": "#2563eb",
    "blue-700": "#1d4ed8",
    "blue-800": "#1e40af",
    "violet-600": "#7c3aed",
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


def test_chart_chrome_has_the_four_vars() -> None:
    assert set(palette.CHART_CHROME) == {
        "--chart-text",
        "--chart-tooltip-bg",
        "--chart-tooltip-text",
        "--chart-legend-bg",
    }
    assert palette.CHART_CHROME["--chart-text"] == TW["slate-700"]
    assert palette.CHART_CHROME["--chart-tooltip-bg"] == "rgba(30, 41, 59, 0.95)"
    assert palette.CHART_CHROME["--chart-tooltip-text"] == WHITE
    assert palette.CHART_CHROME["--chart-legend-bg"] == TW["slate-100"]


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
