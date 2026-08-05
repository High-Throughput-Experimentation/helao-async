"""The Bokeh half of the HELAO palette: a shared ``Theme`` plus CSS factories.

``palette.py`` holds the colours; this module is the only place that knows how
Bokeh wants them. It is the second of the two modules the AST sweeper in
``helao/core/tests/test_palette.py`` exempts by exact path, because
:data:`GLOBAL_CSS` is hand-authored CSS whose declarations match the sweeper's
"looks like a colour" rule by construction.

Three mechanisms, and the boundary between them is not a style preference — it
is where CSS can physically reach. Bokeh 3 renders **every** ``UIElement`` into
its own shadow root, and layout containers nest, so a ``Button`` inside a
``Row`` inside a ``Column`` sits three shadow boundaries below the document.
Selectors do not cross those boundaries; inherited properties do. Measured
against Bokeh 3.9.1 with headless Chromium; the readings are in
``.omc/artifacts/p3-step0-probe.md``.

1. :data:`HELAO_THEME` — model *property* defaults (plot backgrounds, axes,
   grids, legends). These travel as Bokeh properties, not CSS, so shadow roots
   are irrelevant to them. This is what themes the charts.
2. :data:`GLOBAL_CSS` — lands in ``<head>``, so it reaches the document tree
   only: ``html``/``body`` page chrome, and whatever inherits from ``body``.
   It cannot reach ``Div`` content (Bokeh renders ``Div.text`` into the *Div's*
   shadow root — that content is not light DOM), nor widget internals, nor even
   a widget's host element. Keep it small; anything else added here is a no-op.
   The **one** exception, and it is an exception Bokeh built deliberately, is
   the ``--bokeh-base-font`` / ``--bokeh-mono-font`` pair: Bokeh references
   those from inside each shadow root without ever declaring them, so setting
   them on ``html`` themes every widget's typeface at once. See the comment
   above the constant.
3. :func:`marker_style_block` / :func:`semantic_button_stylesheet` — per-widget
   ``InlineStyleSheet``, which lands *inside* the target widget's shadow root.
   The only mechanism that can recolour a Bokeh widget. There is no
   document-level shortcut: Bokeh's buttons read ``var(--primary)`` and friends,
   but it re-declares those on each widget's ``:host``, which shadows any value
   inherited from ``html``.

**No model instance may be a module constant.** The Bokeh document factory
re-runs on every browser connection (``bokeh_operator.py:71-72``), so a shared
``Model`` raises ``RuntimeError: Models must be owned by only a single
document`` on the *second* client — a defect that a single-connection smoke
test cannot see. Hence ``GLOBAL_CSS`` is a ``str`` and both factories return
fresh models per call. :data:`HELAO_THEME` is shared precisely because
``bokeh.themes.Theme`` is not a ``Model``.

Every palette constant is resolved at module scope, so a mistyped ``TW`` key is
an ImportError-time crash rather than a ``KeyError`` inside a document factory,
which would render as a blank page with nothing in the log.
"""

__all__ = [
    "HELAO_THEME",
    "GLOBAL_CSS",
    "CARRIER_TAG",
    "SECTION_MARGIN",
    "apply_theme",
    "stretch_section",
    "color_declaration",
    "color_rule",
    "estop_button_stylesheet",
    "marker_style_block",
    "semantic_button_stylesheet",
]

from typing import Final

from bokeh.models import Column, Div, GlobalInlineStyleSheet, InlineStyleSheet, Row
from bokeh.themes import Theme

from helao.core.servers.palette import (
    BODY_TEXT,
    BUTTON_DANGER_BG,
    BUTTON_LABEL,
    BUTTON_PRIMARY_BG,
    BUTTON_SUCCESS_BG,
    BUTTON_WARNING_BG,
    ESTOP_BG,
    ESTOP_HOVER_BG,
    INPUT_FONT_STACK,
    MARKER_SWATCHES,
    MUTED_TEXT_ON_WHITE,
    PAGE_BG,
    PANEL_BG,
    SURFACE_WHITE,
    TW,
    UI_FONT_STACK,
    font_import_css,
)

# Chart-chrome roles, named here rather than in palette.py because they are
# Bokeh-figure furniture with no counterpart in the Reflex stack.
_AXIS_LINE: Final[str] = TW["slate-400"]
"""Axis lines, tick marks, plot outline, legend border."""

_GRID_LINE: Final[str] = TW["slate-300"]
"""Grid lines inside the plot area."""


# ---------------------------------------------------------------------------
# Model property defaults
# ---------------------------------------------------------------------------
# Keyed by *class* name, and Theme._for_class walks a model's whole MRO
# (bokeh/themes/theme.py:198-213), so "Plot" reaches every bokeh.plotting
# figure and "Axis" every LinearAxis / DatetimeAxis / CategoricalAxis.
#
# A class name that does not resolve is a **silent no-op** there — no error, no
# warning, just an unthemed document — which is why test_bokeh_theme.py asserts
# every key below is a real bokeh.models class. A bad *property* name raises on
# apply, so that half is self-reporting.
HELAO_THEME: Final[Theme] = Theme(
    json={
        "attrs": {
            "Plot": {
                # White plot area so traces keep their contrast; the border ring
                # takes the panel colour so figures sit flush on the layout.
                "background_fill_color": SURFACE_WHITE,
                "border_fill_color": PANEL_BG,
                "outline_line_color": _AXIS_LINE,
            },
            "Axis": {
                "axis_line_color": _AXIS_LINE,
                "major_tick_line_color": _AXIS_LINE,
                "minor_tick_line_color": _AXIS_LINE,
                "axis_label_text_color": BODY_TEXT,
                "major_label_text_color": MUTED_TEXT_ON_WHITE,
                "axis_label_text_font": UI_FONT_STACK,
                "major_label_text_font": UI_FONT_STACK,
            },
            # minor_grid_line_color is deliberately absent: it defaults to None
            # and setting it would add gridlines no figure asked for.
            "Grid": {
                "grid_line_color": _GRID_LINE,
            },
            # Figure titles are chart furniture, not section headers, so they
            # take BODY_TEXT. HEADING_TEXT belongs to the banner and the
            # section headers, which are Div markup styled at their own sites.
            "Title": {
                "text_color": BODY_TEXT,
                "text_font": UI_FONT_STACK,
            },
            "Label": {
                "text_color": BODY_TEXT,
                "text_font": UI_FONT_STACK,
            },
            "Legend": {
                "background_fill_color": SURFACE_WHITE,
                "border_line_color": _AXIS_LINE,
                "label_text_color": BODY_TEXT,
                "title_text_color": BODY_TEXT,
                "label_text_font": UI_FONT_STACK,
                "title_text_font": UI_FONT_STACK,
            },
            "ColorBar": {
                "background_fill_color": SURFACE_WHITE,
                "major_label_text_color": MUTED_TEXT_ON_WHITE,
                "title_text_color": BODY_TEXT,
                "major_label_text_font": UI_FONT_STACK,
                "title_text_font": UI_FONT_STACK,
            },
            # The one Theme entry that is not chart furniture, and the only
            # mechanism that gives a Bokeh *text field* a different family from
            # the rest of the page. `styles` is an inline style on the widget's
            # host element, which beats both the `:host{font-family:var(
            # --base-font)}` rule inside the widget's own shadow root and the
            # `*{font-family:inherit}` its parent layout imposes from the outer
            # tree. Keyed on "InputWidget" so Theme's MRO walk reaches TextInput,
            # TextAreaInput, Select, MultiSelect, NumericInput, Spinner,
            # AutocompleteInput and DatePicker alike.
            #
            # It survives a widget that sets `stylesheets` explicitly -- which
            # the operator's param inputs do, and then replace wholesale from
            # CustomJS -- because a theme default is only lost for the *same*
            # property. It does **not** survive a call site that sets `styles`
            # on an input widget; no site does today, and
            # test_no_bokeh_input_widget_sets_styles keeps it that way.
            "InputWidget": {
                "styles": {"font-family": INPUT_FONT_STACK},
            },
        }
    }
)


# ---------------------------------------------------------------------------
# Document chrome
# ---------------------------------------------------------------------------
# Everything a <head> stylesheet can actually do to a Bokeh 3 document, and
# nothing more. `color` on body is here because inherited properties *do* cross
# shadow boundaries, so it reaches Div-rendered text that no selector can.
#
# Deliberately absent: any box-model rule on `body > div`. Those per-root shells
# are in the document tree and therefore reachable, and apply_theme adds one for
# the theme carrier — a border or margin there would open a gap at the top of
# every page.
# The canvas is PAGE_BG, *not* PANEL_BG. Painting the page in the panel colour
# collapses the recessed-panel hierarchy this stack has always had — light
# canvas, mid-tone panel, light plot area — and the section panels vanish into
# the page on every document. See palette.PAGE_BG.
#
# The fonts are the one thing here that reaches *past* the document tree, and
# they do it through a hole Bokeh left open rather than through inheritance.
# `styles/base.css` opens every widget's shadow root with
#
#   :host{--base-font:var(--bokeh-base-font, Helvetica, Arial, sans-serif);
#         --mono-font:var(--bokeh-mono-font, monospace);
#         font-family:var(--base-font);}
#   *,*:before,*:after{font-family:inherit;}
#   pre,code,tt{font-family:var(--mono-font);}
#
# `--bokeh-base-font` and `--bokeh-mono-font` are *referenced and never
# declared*, so unlike `--primary` and the rest of the colour vars — which Bokeh
# re-declares on `:host` and which therefore cannot be themed from here at all —
# an inherited custom property set on `html` reaches every widget in the
# document. Measured on Bokeh 3.9.1: setting these two alone moved a Div's span,
# a Button's label, a TextInput's `<input>`, a Select, a TextAreaInput and a
# DataTable's header cells, including a button that carried its own
# `InlineStyleSheet`. **`body { font-family: ... }` moves none of them** — the
# probe's earlier reading of a stubborn `Helvetica, Arial, sans-serif` was this,
# not a shadow-boundary limit on inheritance. Do not "simplify" this to a body
# rule.
GLOBAL_CSS: Final[str] = font_import_css() + f"""
html {{
  --bokeh-base-font: {UI_FONT_STACK};
  --bokeh-mono-font: {INPUT_FONT_STACK};
}}
html, body {{
  background-color: {PAGE_BG};
  font-family: {UI_FONT_STACK};
}}
body {{
  color: {BODY_TEXT};
}}
"""

CARRIER_TAG: Final[str] = "helao_theme_carrier"

SECTION_MARGIN: Final[tuple[int, int, int, int]] = (4, 4, 4, 4)

#: Box of the ``FileInput`` load button (see :func:`file_load_button_stylesheet`).
#:
#: CSS lengths rather than ints: they are interpolated into a stylesheet, not
#: passed to a Bokeh ``width=``. Sizing the widget in Python instead would set
#: the *host* box while the native control inside kept its intrinsic width, and
#: the two would disagree.
#: The height matches the parameter form's text inputs (``height=31`` in
#: ``bokeh_operator``), because the button sits *beside* one: a shorter box
#: would float against the taller input and read as misaligned rather than as
#: a pair.
FILE_LOAD_BUTTON_WIDTH: Final[str] = "56px"
FILE_LOAD_BUTTON_HEIGHT: Final[str] = "31px"
"""Margin (top, right, bottom, left) on every Bokeh section panel.

Sections are ``sizing_mode="stretch_width"``, so this is the only thing holding
them off the browser's edges — and off each other. Two adjacent margins do not
collapse in a Bokeh flex container (each child is its own flex box, not a block
in normal flow), so panels sit 8px apart and 4px from the page edge.

Here rather than in ``palette.py`` because it is a layout value, not a colour,
and ``palette`` is deliberately the one module whose contents are colours; here
rather than in each app because the operator and every visualizer have to agree
or the pages do not line up when a station runs several side by side.
"""


def stretch_section(panel):
    """Make ``panel`` and its nested containers fill the page width, in place.

    **Do not pass ``sizing_mode="stretch_width"`` to ``layout()`` instead.**
    ``bokeh.layouts._create_grid`` assigns that mode to every child it walks
    whose own ``sizing_mode`` is ``None`` and whose width/height policies are
    both ``"auto"`` — which is every plain ``TextInput(width=150)``,
    ``Button(width=70)`` and ``DataTable(width=400)``. The fixed width is then
    ignored and the widget stretches. Measured on a visualizer panel at 1600px:
    two 150px inputs came out 785px each, and a row of ``[plot, Spacer, table]``
    split three ways so the plot rendered at 526px instead of filling the space
    the table left. Nothing is raised, and at 1024px — the width the panels used
    to be pinned to — it is barely visible.

    Walking the built tree afterwards avoids that: only ``Row``/``Column``
    containers are touched, so a figure that asked for ``stretch_width`` still
    gets it and a widget that asked for a width keeps it.

    Args:
        panel: The container returned by ``layout()``.

    Returns:
        The same object, for use as an expression.
    """
    panel.sizing_mode = "stretch_width"
    for child in getattr(panel, "children", []):
        if isinstance(child, (Row, Column)):
            stretch_section(child)
    return panel


"""Tag marking the hidden root that carries the document's ``GLOBAL_CSS``."""


def apply_theme(doc) -> None:
    """Apply the HELAO theme and document CSS to a Bokeh ``Document``.

    Called once from ``HelaoVis.__init__``, which is the single seam that
    reaches every HELAO Bokeh document — including the aligner served by
    ``helao/hexagon/adapters/vis/galil_aligner_host.py``, whose ``Server`` is
    built inside an action-server process and never passes through
    ``bokeh_launcher.py``.

    Idempotent: a second call on the same document is a no-op, detected by
    scanning existing roots for :data:`CARRIER_TAG` rather than by a flag on
    the document, so it holds across callers that do not share state.

    Args:
        doc: A Bokeh ``Document``, or any stub with a settable ``theme``
            attribute. Documents are constructed against fakes throughout the
            test suite (``unit_test_config_seam.py`` passes a
            ``SimpleNamespace``), so the root-add is guarded rather than
            assumed.
    """
    doc.theme = HELAO_THEME

    if not hasattr(doc, "add_root"):
        return

    for root in getattr(doc, "roots", ()) or ():
        if CARRIER_TAG in (getattr(root, "tags", None) or ()):
            return

    # A GlobalInlineStyleSheet reaches <head> by riding some model's
    # `stylesheets`; this zero-sized invisible Div exists only to carry it.
    doc.add_root(
        Div(
            text="",
            visible=False,
            width=0,
            height=0,
            margin=0,
            tags=[CARRIER_TAG],
            stylesheets=[GlobalInlineStyleSheet(css=GLOBAL_CSS)],
        )
    )


def color_rule(selector: str, color: str, important: bool = False) -> str:
    """Return a one-declaration CSS rule: ``<selector> { color: <color>; }``.

    For the handful of call sites that must author CSS as a **string** rather
    than pass a Bokeh property or a ``styles={...}`` dict — a ``TextInput``'s
    ``stylesheets``, or a rule handed to ``CustomJS`` to install client-side.

    This exists because the sweeper's rule 2 matches the *declaration text*
    ``color:`` on any string literal, regardless of what the value is. A call
    site that interpolates a palette constant into its own f-string still
    reports a finding, so substitution alone cannot clear those sites. Moving
    the declaration in here does clear them, and that is the honest fix rather
    than a dodge: ``bokeh_theme.py`` is exempt by exact path precisely because
    it is the module that is *supposed* to hold CSS text.

    Args:
        selector: CSS selector, e.g. ``".bk-input"``.
        color: A colour from :mod:`helao.core.servers.palette`.
        important: Append ``!important``. Needed when the rule has to beat a
            declaration Bokeh already applies to the same element.
    """
    priority = " !important" if important else ""
    return f"{selector} {{ color: {color}{priority}; }}"


def color_declaration(color: str, important: bool = False, prop: str = "color") -> str:
    """Return a bare ``<prop>: <color>`` for an inline HTML ``style=`` attribute.

    The attribute form of :func:`color_rule`, for markup built as a string —
    ``f"<span style='{color_declaration(BROWSER_FAILURE_TEXT)}'>…</span>"``.
    Same rationale: the declaration text is what the sweeper matches, so it has
    to live in this module.

    ``prop`` exists because inline markup needs ``background-color`` as often as
    ``color``, and the sweeper matches ``(?:background-)?color\\s*:`` — so a call
    site cannot author either one itself. Without it, a caller is pushed toward
    hiding the property name behind a local constant, which satisfies the gate by
    defeating it. That is the one resolution this project rejects: the point is
    for CSS text to live in the exempt module, not for the text to be disguised.

    Args:
        color: A colour from :mod:`helao.core.servers.palette`.
        important: Append ``!important``.
        prop: The CSS property. ``"color"`` (default) or ``"background-color"``.
    """
    priority = " !important" if important else ""
    return f"{prop}: {color}{priority}"


def estop_button_stylesheet() -> InlineStyleSheet:
    """Return a fresh ``InlineStyleSheet`` for the operator's ESTOP button.

    ESTOP is a ``button_type="danger"`` widget that deliberately does **not**
    take the ordinary danger hue: it carries the palette's darkest red so it
    reads as distinct from every other destructive control on the page. Re-sources
    the hand-written sheet at ``bokeh_operator.py:409-417``.

    **Attach this sheet alone**, not alongside
    :func:`semantic_button_stylesheet`. Both target ``.bk-btn.bk-btn-danger``
    at equal specificity, so whichever comes later in ``stylesheets=`` wins —
    and if the semantic sheet won, ESTOP would silently render as an ordinary
    danger button.

    Fresh model per call, for the same reason as every other factory here.
    """
    return InlineStyleSheet(
        css=(
            f".bk-btn.bk-btn-danger {{ background-color: {ESTOP_BG}; "
            f"border-color: {ESTOP_HOVER_BG}; color: {BUTTON_LABEL}; }} "
            f".bk-btn.bk-btn-danger:hover {{ background-color: {ESTOP_HOVER_BG}; "
            f"border-color: {ESTOP_HOVER_BG}; }}"
        )
    )


def marker_style_block() -> list[InlineStyleSheet]:
    """Return one fresh ``InlineStyleSheet`` per aligner marker chip.

    Five sheets in :data:`~helao.core.servers.palette.MARKER_SWATCHES` order,
    to be attached to the five ``marker_buttonsel`` buttons in the same index
    order::

        sheets = marker_style_block()
        Button(label="", button_type="default", stylesheets=[sheets[idx]])

    Replaces the ``<style>``-inside-``Div.text`` block the aligners carry
    today, which has been **inert since the Bokeh 3 upgrade**: that stylesheet
    is sealed in the ``Div``'s own shadow root while the buttons live in five
    others, so the chips currently render as plain default buttons. Measured,
    not inferred — the probe read ``rgb(255, 255, 255)`` off a chip whose rule
    asked for ``#ff0000``, and ``rgb(255, 0, 0)`` off the same button styled
    this way instead.

    Targets ``.bk-btn-default`` because the chips *are* default buttons. That
    is legitimate here and forbidden in
    :func:`semantic_button_stylesheet`: the prohibition is on a blanket
    document-wide ``.bk-btn-default`` rule, and each sheet returned here is
    scoped to one widget's shadow root.
    """
    return [
        InlineStyleSheet(
            css=(
                f".bk-btn.bk-btn-default {{ background-color: {swatch}; "
                f"color: {BODY_TEXT}; }} "
                f".bk-btn.bk-btn-default:hover {{ background-color: {swatch}; "
                f"filter: brightness(0.92); }}"
            )
        )
        for swatch in MARKER_SWATCHES
    ]


def file_load_button_stylesheet() -> InlineStyleSheet:
    """Return a fresh ``InlineStyleSheet`` reducing a ``FileInput`` to one button.

    Bokeh 3 renders ``FileInput`` as a **native** ``<input type="file">`` inside
    the widget's own shadow root, so what the browser draws is a platform
    button plus a status string -- "Browse... No file selected" in Firefox,
    "Choose File / No file chosen" in Chrome. Beside a one-line text input that
    is three widgets' worth of chrome for a file picker nobody reads the state
    of, and the wording is not ours.

    Neither half is fixable the obvious way. A native file input is a *replaced*
    element, so ``::before`` on it never renders, and ``::file-selector-button``
    cannot be relabelled -- ``content`` does not apply to it. What *is*
    styleable is ``:host``: this sheet is injected into the FileInput's own
    shadow root, where the host is an ordinary element that takes a pseudo.

    So the host draws the label, and the native control is stretched over the
    whole host and made invisible -- still the thing that receives the click, so
    the file dialog opens with no JavaScript and no reach into the shadow DOM
    from outside. Sizing lives here rather than on the Python widget for the
    same reason it does for the semantic buttons: the caller should ask for "a
    load button", not compute a pixel box.

    Returns:
        InlineStyleSheet: A new instance per call. A module-level instance
        would raise ``Models must be owned by only a single document`` on the
        second browser connection, because the document factory re-runs per
        client.
    """
    return InlineStyleSheet(
        css=(
            ":host { position: relative; display: inline-block; "
            f"width: {FILE_LOAD_BUTTON_WIDTH}; height: {FILE_LOAD_BUTTON_HEIGHT}; "
            f"border-radius: 4px; background-color: {BUTTON_PRIMARY_BG}; "
            "overflow: hidden; }"
            ':host::before { content: "load"; position: absolute; inset: 0; '
            "display: flex; align-items: center; justify-content: center; "
            f"color: {BUTTON_LABEL}; font-size: 12px; line-height: 1; "
            "pointer-events: none; }"
            ":host(:hover) { filter: brightness(0.92); }"
            # The native control keeps the click. Transparent rather than
            # `display: none`, which would stop it receiving one at all.
            'input[type="file"] { position: absolute; inset: 0; width: 100%; '
            "height: 100%; opacity: 0; padding: 0; margin: 0; border: 0; "
            "cursor: pointer; }"
            'input[type="file"]::file-selector-button { width: 100%; '
            "height: 100%; opacity: 0; padding: 0; margin: 0; border: 0; "
            "cursor: pointer; }"
        )
    )


def semantic_button_stylesheet() -> InlineStyleSheet:
    """Return a fresh ``InlineStyleSheet`` re-hueing Bokeh's semantic buttons.

    Attach to any widget whose ``button_type`` is ``primary``, ``success``,
    ``warning`` or ``danger``; the sheet carries all four, so a widget that
    toggles between two of them (the operator's STEP/RUN button, the data
    browser's scan swap) needs one sheet and keeps its dynamic recolour.

    ``.bk-btn-default`` is **never** emitted: it is Bokeh's neutral, and a
    blanket rule would collide with the marker chips, which are default
    buttons carrying their own per-widget override.

    Two details that a one-declaration version gets wrong:

    * Selectors are ``.bk-btn.bk-btn-<type>`` (two classes) rather than
      ``.bk-btn-<type>``, matching the ESTOP precedent at
      ``bokeh_operator.py:409-417``. Bokeh's own ``.bk-active.bk-btn-primary``
      rule is also two classes, so the single-class form would lose to it on a
      toggled widget and revert to stock blue.
    * ``:hover`` is overridden too. Bokeh's hover reads ``var(--primary-hover)``
      and friends, which stay stock, so without this a themed button flips to
      Bokeh's blue/green/orange/red under the cursor. ``filter: brightness()``
      supplies the hover affordance from the palette colour itself, so no
      hover-only shade has to be invented.
    """
    rules = []
    for kind, background in (
        ("primary", BUTTON_PRIMARY_BG),
        ("success", BUTTON_SUCCESS_BG),
        ("warning", BUTTON_WARNING_BG),
        ("danger", BUTTON_DANGER_BG),
    ):
        rules.append(
            f".bk-btn.bk-btn-{kind} {{ background-color: {background}; "
            f"border-color: {background}; color: {BUTTON_LABEL}; }}"
        )
        rules.append(
            f".bk-btn.bk-btn-{kind}:hover {{ background-color: {background}; "
            f"border-color: {background}; filter: brightness(0.92); }}"
        )
    return InlineStyleSheet(css=" ".join(rules))
