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
    "red-400": "#f87171",
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

PANEL_BORDER: Final[str] = TW["slate-400"]
"""Hairline around a :data:`PANEL_BG` section in the Bokeh stack.

One step darker than the panel it outlines, which is what the border is for:
:data:`PAGE_BG` separates panels from the canvas at 1.42:1, but two panels
stacked in the same column meet at an edge with *no* luminance step at all, so a
tall page reads as one undivided slab. The border draws that missing edge.

1.73:1 against :data:`PANEL_BG` and 2.45:1 against :data:`PAGE_BG` — clears the
1.20 neighbouring-surface floor from both sides, which it has to, since the line
has panel on one side and canvas on the other. ``slate-500`` also clears (3.21
and 4.55) but at 1px reads as a drawn rule dividing two regions rather than as
the edge of one; the ask was a thin border, so the lighter of the two shades
that clear is the right one.
"""

PANEL_BORDER_WIDTH: Final[str] = "1px"
"""Width of the :data:`PANEL_BORDER` hairline.

A length rather than a hue, kept beside the colour because
:func:`panel_styles` is the only consumer of either and a test can read a
constant. 1px because the border marks an edge; anything heavier competes with
the figure frames inside the panel.
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

# ---------------------------------------------------------------------------
# Typefaces
# ---------------------------------------------------------------------------
# Not colours, but the same argument puts them here: one source, two stacks.
# Both stacks reach the families through the constants below, and both deliver
# the two ``@import`` lines through their own document-CSS seam
# (``reflex/app.py``'s ``head_components`` and ``bokeh_theme.GLOBAL_CSS``).
UI_FONT_FALLBACK: Final[str] = (
    "ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "
    '"Segoe UI", Roboto, "Helvetica Neue", Helvetica, Arial, sans-serif'
)
"""What the UI font falls back to, ending in the ``sans-serif`` generic."""

INPUT_FONT_FALLBACK: Final[str] = (
    "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "
    '"Liberation Mono", "Courier New", monospace'
)
"""What the input font falls back to, ending in the ``monospace`` generic."""

UI_FONT_STACK: Final[str] = f'"IBM Plex Sans Condensed", {UI_FONT_FALLBACK}'
"""Every glyph that is not inside a text field.

**The fallback tail is the entire offline story, and it is a construction
rather than a check.** Stations routinely run with no route to the internet, so
:data:`UI_FONT_IMPORT` will simply fail to fetch — and a failed ``@import``
means nothing more than that the *first* family in a stack is unavailable,
which is the case CSS font fallback already exists to handle. No JS font
detection is involved anywhere, and none should be added: a detector can only
observe the same absence the cascade already handles, and it can do it wrongly.

``test_font_stacks_end_in_a_generic_family`` is the guard. Editing either stack
to end in a named family would leave an offline station rendering in whatever
the browser's last-resort font happens to be.
"""

INPUT_FONT_STACK: Final[str] = f'"Iosevka Web", "Iosevka", {INPUT_FONT_FALLBACK}'
"""Text fields, and monospaced runs (``pre``/``code``) in either stack.

Iosevka is a fixed-pitch face, which is why it also takes the ``mono`` role
rather than only the input role: a station operator reads sample IDs, plate
coordinates and JSON out of these fields, and column alignment is the point.
Same fallback rule as :data:`UI_FONT_STACK`.

**Two Iosevka entries, and both are load-bearing.** The stylesheet at
:data:`INPUT_FONT_IMPORT` names its faces ``Iosevka Web`` (and ``Iosevka Web
Oblique`` for italics) — *not* ``Iosevka``. A stack asking only for ``Iosevka``
therefore ignores the webfont entirely and silently falls through to
``ui-monospace``… except on a developer machine that happens to have Iosevka
installed, where it renders correctly and the bug is invisible. ``Iosevka``
stays as the second entry because it is the name a locally installed copy
answers to, which is the only way an offline station can have Iosevka at all.
"""

UI_FONT_IMPORT: Final[str] = (
    "@import url('https://fonts.googleapis.com/css2"
    "?family=IBM+Plex+Sans+Condensed:wght@400;500;600;700&display=swap');"
)
"""Google Fonts request for the UI family. ``display=swap`` is not optional.

Without it the browser holds text invisible for its font-block period while the
request is outstanding, so a station on a slow or half-dead network renders a
blank page rather than a fallback one.
"""

INPUT_FONT_IMPORT: Final[str] = (
    "@import url('https://iosevka-webfonts.github.io/iosevka/iosevka.css');"
)
"""The Iosevka webfont stylesheet, as the project specified it."""


def font_import_css() -> str:
    """Return the two ``@import`` lines, and nothing else.

    **Must be emitted first in whichever stylesheet carries it.** ``@import`` is
    only valid ahead of every style rule in a stylesheet; a browser drops one
    that appears after a rule, silently, leaving both families unavailable and
    both stacks quietly on their fallbacks. Both callers concatenate this at the
    very top of their document CSS for that reason.
    """
    return f"{UI_FONT_IMPORT}\n{INPUT_FONT_IMPORT}\n"


REFLEX_HEADER_TRIM: Final[str] = "py-1! h-auto!"
"""Height trim for a Radix table header cell: 36px measured, 28px after.

**Padding alone cannot move this number, and that is the whole subtlety.**
Radix's ``.rt-TableCell`` sets ``height: var(--table-cell-min-height)``, which
is ``calc(36px * var(--scaling))`` at sizes 1 and 2 — and ``height`` on a table
cell acts as a *minimum*. Measured: dropping the padding from 8px to 4px on its
own left the cell at exactly 36px, with the extra 8px reappearing as content
box. ``h-auto`` releases the floor; then 4px + a 20px line box gives 28px.

Both utilities carry Tailwind's trailing ``!``, and both need it: Radix Themes
is **unlayered** CSS while Tailwind v4 emits utilities into ``@layer
utilities``, and an unlayered rule outranks every layered one regardless of
specificity. Without the ``!`` the classes reach the element and nothing moves.

Only the *header* is trimmed. ``--table-cell-min-height`` would have been the
smaller change but it is declared per table size and would take the body rows
with it; the complaint was about the header.
"""

GRIDJS_HEADER_FONT_SIZE: Final[str] = "14px"
"""Font size for a gridjs header cell.

gridjs's header inherits nothing useful — it measured 16px while the body text
around it had come down to 12px, so the table read as though its header
belonged to a different page. 14px is one step above the body, which is what a
header wants, and is set in the same rule as the header's hue and padding
because only that rule can reach a ``th.gridjs-th`` at all.
"""

GRIDJS_HEADER_PAD_Y: Final[str] = "4px"
"""Vertical padding for a gridjs header cell, replacing gridjs's own ``14px``.

A length rather than a colour, and so the one non-hue value in this module. It
lives here because it can only be applied from
:func:`reflex_gridjs_header_css` — see that function for why a Tailwind utility
cannot reach a ``th.gridjs-th`` at all — and a constant a test can read beats a
number buried in an f-string.

Measured, not guessed: gridjs's ``14px`` gave a 52.5px header against 49px body
rows. ``4px`` gives 32.5px, a 38% trim. It cannot clip, because the content it
pads is 24px tall either way — the label's ``line-height`` and the sort button
are both 24px — so this value is entirely slack above and below the glyphs.
Horizontal padding is deliberately left at gridjs's ``24px``: the complaint was
header *height*, and narrowing the columns was no part of it.
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

    Carries :data:`REFLEX_HEADER_TRIM` as well as the hue, so the operator's
    queue and history tables and the data browser's table trim together —
    every Radix header cell in the Reflex stack takes its class from here.
    Radix components *do* forward ``class_name``, so unlike ``rx.data_table``
    the utility route works here; see the constant for the two cascade facts
    that make it work.

    Args:
        kind: A key of :data:`REFLEX_TABLE_HUES`.
    """
    background, text, _ = REFLEX_TABLE_HUES[kind]
    return f"bg-{background} text-{text} {REFLEX_HEADER_TRIM}"


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

    The rule also trims the header's **vertical** padding, and has to: gridjs's
    own ``th.gridjs-th`` sets ``14px``, which measured a 52.5px header row —
    *taller* than the 49px body rows below it despite holding one line of text.
    Only ``padding-top``/``padding-bottom`` are set, never the ``padding``
    shorthand, so the 24px horizontal padding keeps the columns' breathing room.
    ``GRIDJS_HEADER_PAD_Y`` is safe against clipping because the header's content
    box is 24px whether it holds the label (``line-height: 24px``) or the sort
    button (24px tall), so the padding is pure slack on both; measured 32.5px
    after, with the sort icon 4px clear of each edge.

    It belongs in this same rule rather than a utility class for the reason
    above — a ``th.gridjs-th`` padding declared in ``@layer utilities`` loses to
    gridjs's unlayered one no matter how specific it is.

    :data:`GRIDJS_HEADER_FONT_SIZE` rides along for a third instance of the same
    reason. gridjs takes no Radix ``size`` prop, so its header cannot be brought
    down by the means every other label on the page uses, and it measured 16px
    against 12px body text.
    """
    background, text, _ = REFLEX_TABLE_HUES["browser"]
    fill, ink = TW[background], TW[text]
    return (
        f".gridjs-container th.gridjs-th,"
        f".gridjs-container th.gridjs-th.gridjs-th-sort:hover,"
        f".gridjs-container th.gridjs-th.gridjs-th-sort:focus"
        f" {{ background-color: {fill}; color: {ink};"
        f" font-size: {GRIDJS_HEADER_FONT_SIZE};"
        f" padding-top: {GRIDJS_HEADER_PAD_Y}; padding-bottom:"
        f" {GRIDJS_HEADER_PAD_Y}; }}"
    )


def panel_styles(background: str, border: str = PANEL_BORDER) -> dict[str, str]:
    """Return the inline styles painting and outlining one Bokeh section panel.

    Used as ``styles=panel_styles(PANEL_BG)``, **replacing** the ``background=``
    kwarg a section layout used to carry rather than joining it. A dict rather
    than a stylesheet because ``LayoutDOM.styles`` is the only seam that reaches
    a layout container: the container renders into its own shadow root, so no
    ``<head>`` rule can select it, and a ``Theme`` entry for ``Column`` cannot
    tell a section apart from the nested rows and columns inside it — it would
    outline every one of them.

    **Both declarations have to come from the same dict, and this is the whole
    reason the function takes the background at all.** Bokeh 3's
    ``LayoutDOM.background`` is a write-only alias that assigns
    ``styles["background-color"]``, and a ``styles=`` kwarg *replaces* the dict
    rather than merging into it. Passing both therefore silently loses whichever
    came first: measured on Bokeh 3.9.1, ``background=..., styles=...`` yields
    ``{'border': ...}`` with no background at all — every section panel would
    have rendered unpainted, with nothing raised on either side. Passing one dict
    also drops a deprecated property, which is why the call sites no longer use
    ``background=``.

    Args:
        background: Panel fill, e.g. :data:`PANEL_BG`.
        border: Border colour. Defaults to :data:`PANEL_BORDER`, which is the
            right answer for every :data:`PANEL_BG` section and for the
            :data:`PLAN_PANEL_NONQUEUED_BG` one (2.23:1, and darker). A section
            painted a *dark* hue must pass its own: the border has to be darker
            than the panel it outlines, and ``slate-400`` on a ``teal-600`` panel
            would be a lighter line, reading as a highlight rather than an edge.
            The aligner is the only layout with such panels and names its own
            border role beside its own panel roles.

    Returns:
        dict[str, str]: A ``styles`` value for a Bokeh layout container.
    """
    return {
        "background-color": background,
        "border": f"{PANEL_BORDER_WIDTH} solid {border}",
    }


def reflex_font_css() -> str:
    """Return the Reflex stack's font CSS, ``@import`` lines first.

    Three groups of declarations, each answering a different owner of the
    resolved family:

    * ``--font-sans`` / ``--font-mono`` are **Tailwind v4**'s theme variables,
      declared in ``@layer theme`` on ``:root, :host``. Setting them unlayered
      wins, and it is what makes the ``font-sans``/``font-mono`` utilities and
      Tailwind's preflight agree with the rest of the page.
    * ``--default-font-family`` and its five siblings are **Radix Themes**'
      tokens, declared on ``.radix-themes``. Radix is unlayered, so a ``:root``
      override loses to it on specificity; ``html .radix-themes`` (0,1,1) wins
      whatever the source order, which ``head_components`` does not control.
    * the ``input``/``textarea``/``select`` group is the input font, class
      qualified for the same reason: bare ``html input`` is (0,0,2) and would
      lose to Radix's own single-class rule on its field.

    ``rx.el.style`` is the only delivery seam — ``rx.App(style={...})`` cannot
    reach ``html`` at all. See ``reflex/app.py``.
    """
    return (
        font_import_css() + f"html {{ --font-sans: {UI_FONT_STACK};"
        f" --font-mono: {INPUT_FONT_STACK}; }}\n"
        f"html .radix-themes, html body {{"
        f" --default-font-family: {UI_FONT_STACK};"
        f" --heading-font-family: {UI_FONT_STACK};"
        f" --strong-font-family: {UI_FONT_STACK};"
        f" --em-font-family: {UI_FONT_STACK};"
        f" --quote-font-family: {UI_FONT_STACK};"
        f" --code-font-family: {INPUT_FONT_STACK};"
        f" --default-mono-font-family: {INPUT_FONT_STACK};"
        f" font-family: {UI_FONT_STACK}; }}\n"
        f"html input, html textarea, html select,"
        f" html .rt-TextFieldInput, html .rt-TextAreaInput,"
        f" html .rt-SelectTrigger, html .gridjs-input"
        f" {{ font-family: {INPUT_FONT_STACK}; }}\n"
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
RAMP_START: Final[str] = TW["red-400"]
"""Lightest end of the spectra recency ramp — the *newest* trace.

**Was ``red-100``, which measured 1.22:1 against the white plot area and was
effectively invisible.** The trace floor is 2.0:1 and this is a trace, but no
test measured the ramp: ``test_red_ramp`` checked its length, endpoints and
monotonicity only, so a shade three steps too light passed every gate. That is
now covered by ``test_every_red_ramp_step_clears_the_trace_floor``.

The lightest end is the one that matters here, and that is not obvious: in
``spec_vis`` a newly-arrived spectrum is drawn ``_ramp[0]`` and older ones shift
*darker*, so the light end is the freshest data rather than the faded history.

``red-400`` is the lightest red that clears the floor: ``red-200`` measures 1.45
and ``red-300`` 1.90, both still under it. Every step of a 10-entry ramp then
lands between 2.77 and 10.02 (against ``red-100``'s 1.22-10.02, whose first three
steps were all below the floor). ``red-500`` would clear it too but compresses
the ramp's luminance spread from 6.0x to 4.2x, and the spread is what encodes
recency at all.
"""

RAMP_END: Final[str] = TW["red-900"]
"""Darkest end of the spectra ramp — the oldest retained trace, 10.02:1."""


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
    # --- plot interior: the surfaces the Bokeh figures already theme ---------
    "--chart-bg": SURFACE_WHITE,
    "--chart-grid": TW["slate-300"],
    "--chart-axis": TW["slate-400"],
    # --- text ---------------------------------------------------------------
    "--chart-text": TW["slate-700"],
    "--chart-annotation-text": TW["slate-700"],
    # --- overlays -----------------------------------------------------------
    "--chart-tooltip-bg": _rgba(TW["slate-800"], 0.95),
    "--chart-tooltip-text": WHITE,
    "--chart-badge-bg": _rgba(TW["slate-800"], 0.95),
    "--chart-badge-text": WHITE,
    "--chart-crosshair": _rgba(TW["slate-900"], 0.42),
    # --- chrome fills -------------------------------------------------------
    "--chart-legend-bg": TW["slate-100"],
    "--chart-modebar-bg": WHITE,
    "--chart-modebar-active": TW["slate-100"],
    # --- interaction affordances -------------------------------------------
    "--chart-focus": TW["sky-600"],
    "--chart-modebar-focus": TW["sky-600"],
    "--chart-selection": TW["sky-600"],
    "--chart-selection-fill": _rgba(TW["sky-600"], 0.12),
    "--chart-zoom-selection": TW["sky-700"],
    "--chart-zoom-selection-fill": _rgba(TW["sky-700"], 0.12),
}
"""Nineteen of the 22 CSS custom properties ``xy-client.js`` reads.

Delivered as one ``:root`` block through ``head_components`` in
``helao/core/servers/reflex/app.py`` — **not** ``rx.App(style=...)``, which
serializes a string key into a descendant selector that can never match
``<html>`` and so fails silently.

The point of covering ``--chart-bg``, ``--chart-grid`` and ``--chart-axis`` is
parity, not decoration: the Bokeh figures take those same three roles from
``HELAO_THEME`` (``Plot.background_fill_color``, ``Grid.grid_line_color``, the
axis line colour). While the Reflex charts sat at xy's own JS fallbacks the two
stacks disagreed about the plot interior, which is exactly what a shared palette
is supposed to make impossible.

**The remaining three are deliberately unset because they are not colours.**
``--chart-cursor`` and ``--chart-cursor-pan`` resolve into ``cursor:`` and hold
CSS cursor *keywords* (``crosshair`` and ``grab``); ``--chart-tick-label-max-width``
resolves inside ``maxWidth: min(...)`` and holds a *length*. Assigning any of
them a colour does not merely fail to theme anything — it breaks the feature,
silently: the pan tool loses its grab cursor and tick labels lose their clamp.
``test_chart_chrome_omits_the_three_non_colour_vars`` exists so that nobody
"completes the set" later. That test, plus the subset check against the 22 names
xy actually reads, is why a typo'd variable name cannot ship as a no-op either.

Two values are pinned to xy's own defaults rather than changed: ``--chart-crosshair``
is ``rgba(15, 23, 42, .42)`` in the JS, which *is* ``slate-900`` at 0.42, so
routing it through :data:`TW` makes it palette-sourced without moving a pixel.

``--chart-legend-bg`` and ``--chart-modebar-active`` are both ``slate-100`` on a
white chart background — 1.10:1, below the 1.20 neighbouring-surface floor, and
they carry **no** surface row on purpose. That floor governs a panel boundary
that has to be *seen*; these two are faint chrome washes behind their own
content, and the affordance is carried by the legend swatches and modebar icons
sitting on them, not by the step in the background. Lifting them to
``slate-200`` (1.23:1) would clear the floor at the cost of making resting
chrome compete with the data it sits over.
"""
