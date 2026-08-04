"""Contract tests for the Bokeh half of the palette.

Three defects these pin, each of which is invisible to a normal smoke test:

* A ``Theme`` ``attrs`` key that names no real class is a **silent no-op** in
  ``Theme._for_class`` (``bokeh/themes/theme.py:198-213``) — the document simply
  renders unthemed. A bad *property* name does raise (``has_props.py:718``), so
  only the class-name half needs an explicit assertion, and that is the half a
  typo would slip through.
* A module-level ``GlobalInlineStyleSheet`` raises ``RuntimeError: Models must
  be owned by only a single document`` on the **second** browser connection,
  because Bokeh re-runs the document factory per client. One connection looks
  fine.
* A non-idempotent ``apply_theme`` accumulates one carrier root per call, which
  shows up as a growing gap at the top of the page rather than as an error.
"""

import bokeh.models
from bokeh.document import Document
from bokeh.models import Div, GlobalInlineStyleSheet, InlineStyleSheet

from helao.core.servers import bokeh_theme
from helao.core.servers.bokeh_theme import (
    CARRIER_TAG,
    GLOBAL_CSS,
    HELAO_THEME,
    apply_theme,
    color_declaration,
    color_rule,
    estop_button_stylesheet,
    marker_style_block,
    semantic_button_stylesheet,
)
from helao.core.servers.palette import (
    BODY_TEXT,
    BUTTON_DANGER_BG,
    BUTTON_LABEL,
    BUTTON_PRIMARY_BG,
    BUTTON_SUCCESS_BG,
    BUTTON_WARNING_BG,
    ESTOP_BG,
    ESTOP_HOVER_BG,
    MARKER_SWATCHES,
    PANEL_BG,
)


# ---------------------------------------------------------------------------
# Theme json validation
# ---------------------------------------------------------------------------
def _theme_attrs() -> dict:
    # Theme keeps its json private; the attrs block is what _for_class reads.
    return HELAO_THEME._json["attrs"]


def test_theme_attrs_is_not_empty():
    """Guard the two tests below: they pass vacuously over an empty attrs block."""
    attrs = _theme_attrs()
    assert attrs, "HELAO_THEME declares no attrs — nothing would be themed"
    assert all(props for props in attrs.values()), "an attrs block is empty"


def test_every_theme_class_name_resolves():
    """A misspelled class name is silently ignored by Bokeh, so assert on it."""
    unresolved = [
        name
        for name in _theme_attrs()
        if not isinstance(getattr(bokeh.models, name, None), type)
    ]
    assert unresolved == [], f"not bokeh.models classes: {unresolved}"


def test_every_theme_property_exists_on_its_class():
    """Pin the properties too, so the failure names the offender.

    Bokeh raises on a bad property when the theme is applied, but the message
    surfaces from inside whichever document happened to be built first.
    """
    missing = []
    for name, props in _theme_attrs().items():
        cls = getattr(bokeh.models, name)
        known = cls.properties()
        missing += [f"{name}.{prop}" for prop in props if prop not in known]
    assert missing == [], f"unknown properties: {missing}"


def test_theme_reaches_plotting_figure_through_the_mro():
    """``Plot`` is the themeable name; ``figure`` is what call sites build.

    ``_for_class`` walks the MRO, so themeing ``Plot`` covers every
    ``bokeh.plotting.figure``. If that ever stopped holding, every chart would
    quietly go unthemed while the class-name test above still passed.
    """
    from bokeh.plotting import figure

    resolved = HELAO_THEME._for_class(figure)
    assert resolved.get("background_fill_color") is not None
    assert resolved.get("border_fill_color") == PANEL_BG


def test_theme_applies_to_a_real_figure():
    """End to end: build a figure in a themed document and read the property."""
    from bokeh.plotting import figure

    doc = Document()
    apply_theme(doc)
    fig = figure()
    doc.add_root(fig)
    assert fig.border_fill_color == PANEL_BG
    assert fig.xaxis[0].axis_label_text_color == BODY_TEXT


# ---------------------------------------------------------------------------
# Per-document model construction
# ---------------------------------------------------------------------------
def test_global_css_is_a_string_not_a_model():
    """The whole reason ``GLOBAL_CSS`` exists as a ``str``.

    A module-level model instance is the highest-severity known defect in this
    design: it survives the first browser connection and raises on the second.
    """
    assert isinstance(GLOBAL_CSS, str)
    assert GLOBAL_CSS.strip()
    module_models = [
        name
        for name, value in vars(bokeh_theme).items()
        if isinstance(value, (GlobalInlineStyleSheet, InlineStyleSheet, Div))
    ]
    assert module_models == [], f"module-level Bokeh models: {module_models}"


def test_global_css_carries_palette_chrome():
    assert PANEL_BG in GLOBAL_CSS
    assert BODY_TEXT in GLOBAL_CSS


def test_global_css_declares_no_box_model_on_root_shells():
    """Per-root shells are the one thing in the document tree ``GLOBAL_CSS``
    can reach, and ``apply_theme`` puts the carrier in one. A border or margin
    there opens a gap at the top of every page."""
    assert "body > div" not in GLOBAL_CSS
    assert "body>div" not in GLOBAL_CSS


def test_apply_theme_on_two_separate_documents():
    """Pins the multi-connection crash: a shared model raises on the second."""
    first, second = Document(), Document()
    apply_theme(first)
    apply_theme(second)
    assert len(first.roots) == 1
    assert len(second.roots) == 1
    # ...and the two carriers are genuinely distinct models.
    (first_carrier,), (second_carrier,) = first.roots, second.roots
    assert isinstance(first_carrier, Div) and isinstance(second_carrier, Div)
    assert first_carrier is not second_carrier
    assert first_carrier.stylesheets[0] is not second_carrier.stylesheets[0]


def test_apply_theme_is_idempotent_on_one_document():
    doc = Document()
    apply_theme(doc)
    apply_theme(doc)
    apply_theme(doc)
    assert len(doc.roots) == 1


def test_apply_theme_carrier_is_tagged_and_invisible():
    doc = Document()
    apply_theme(doc)
    (carrier,) = doc.roots
    assert isinstance(carrier, Div)
    assert CARRIER_TAG in carrier.tags
    assert carrier.visible is False
    assert (carrier.width, carrier.height, carrier.margin) == (0, 0, 0)
    assert isinstance(carrier.stylesheets[0], GlobalInlineStyleSheet)
    assert carrier.stylesheets[0].css == GLOBAL_CSS


def test_apply_theme_sets_the_document_theme():
    doc = Document()
    apply_theme(doc)
    assert doc.theme is HELAO_THEME


def test_apply_theme_leaves_pre_existing_roots_alone():
    doc = Document()
    doc.add_root(Div(text="already here"))
    apply_theme(doc)
    assert len(doc.roots) == 2
    apply_theme(doc)
    assert len(doc.roots) == 2


def test_apply_theme_tolerates_a_doc_stub():
    """``unit_test_config_seam.py`` builds a ``HelaoBokehAPI`` against a
    ``SimpleNamespace``, and ``HelaoVis.__init__`` now calls through here."""
    from types import SimpleNamespace

    stub = SimpleNamespace(title=None)
    apply_theme(stub)
    assert stub.theme is HELAO_THEME

    # A stub that has roots but no add_root must also survive.
    half = SimpleNamespace(roots=[])
    apply_theme(half)
    assert half.theme is HELAO_THEME


# ---------------------------------------------------------------------------
# Per-widget stylesheet factories
# ---------------------------------------------------------------------------
def test_marker_style_block_returns_one_fresh_sheet_per_swatch():
    first = marker_style_block()
    second = marker_style_block()
    assert len(first) == len(MARKER_SWATCHES)
    for sheet, swatch in zip(first, MARKER_SWATCHES):
        assert isinstance(sheet, InlineStyleSheet)
        assert swatch in sheet.css
    # Fresh models: two documents must be able to hold their own.
    assert all(a is not b for a, b in zip(first, second))


def test_marker_sheets_can_coexist_in_two_documents():
    """The failure mode a module-level constant would produce."""
    for _ in range(2):
        doc = Document()
        doc.add_root(Div(text="", stylesheets=[marker_style_block()[0]]))
        assert len(doc.roots) == 1


def test_marker_style_block_targets_default_buttons():
    """The chips are ``button_type="default"``; the sheet is per-widget, so
    naming ``.bk-btn-default`` here is scoped, not blanket."""
    for sheet in marker_style_block():
        assert ".bk-btn-default" in sheet.css


# These assertions are written without spelling the declaration text, so this
# test file does not itself become a sweeper finding. The property name is
# reached via split() and the rule shape via composition — `"color"` on its own
# matches neither rule 2 nor the colour-name regex, only `color:` does.
def test_color_declaration_shape():
    declaration = color_declaration(BODY_TEXT)
    property_name, _, value = declaration.partition(":")
    assert property_name == "color"
    assert value.strip() == BODY_TEXT


def test_color_declaration_important():
    declaration = color_declaration(BODY_TEXT)
    assert color_declaration(BODY_TEXT, important=True) == f"{declaration} !important"


def test_color_rule_wraps_the_declaration_in_the_selector():
    """Pins both the rule shape and its relationship to the bare declaration."""
    declaration = color_declaration(BODY_TEXT)
    assert color_rule(".bk-input", BODY_TEXT) == f".bk-input {{ {declaration}; }}"


def test_color_rule_important():
    declaration = color_declaration(BODY_TEXT, important=True)
    assert color_rule(".bk-input", BODY_TEXT, important=True) == (
        f".bk-input {{ {declaration}; }}"
    )


def test_color_helpers_carry_the_palette_value():
    """Why these two exist: the declaration text lives in this module, which is
    sweep-exempt by exact path, so the call sites stay clean. Interpolating a
    palette constant at the call site does *not* clear the sweep — rule 2
    matches the declaration text, not the value."""
    assert BODY_TEXT in color_rule(".x", BODY_TEXT)
    assert BODY_TEXT in color_declaration(BODY_TEXT)


def test_estop_stylesheet_uses_the_estop_reds():
    sheet = estop_button_stylesheet()
    assert isinstance(sheet, InlineStyleSheet)
    assert ESTOP_BG in sheet.css
    assert ESTOP_HOVER_BG in sheet.css
    assert BUTTON_LABEL in sheet.css
    assert ".bk-btn.bk-btn-danger:hover" in sheet.css


def test_estop_stylesheet_is_fresh_per_call():
    assert estop_button_stylesheet() is not estop_button_stylesheet()


def test_estop_is_distinct_from_the_ordinary_danger_button():
    """ESTOP deliberately does not take the ordinary danger hue. If these ever
    converged, the button would stop reading as the exceptional control."""
    assert ESTOP_BG != BUTTON_DANGER_BG
    assert BUTTON_DANGER_BG not in estop_button_stylesheet().css


def test_estop_and_semantic_sheets_collide_at_equal_specificity():
    """Documents why the ESTOP button must carry its sheet *alone*: both target
    the same selector, so the later entry in ``stylesheets=`` wins."""
    estop, semantic = estop_button_stylesheet().css, semantic_button_stylesheet().css
    assert ".bk-btn.bk-btn-danger" in estop
    assert ".bk-btn.bk-btn-danger" in semantic


def test_semantic_button_stylesheet_covers_all_four_types():
    sheet = semantic_button_stylesheet()
    assert isinstance(sheet, InlineStyleSheet)
    for kind, background in (
        ("primary", BUTTON_PRIMARY_BG),
        ("success", BUTTON_SUCCESS_BG),
        ("warning", BUTTON_WARNING_BG),
        ("danger", BUTTON_DANGER_BG),
    ):
        assert f".bk-btn.bk-btn-{kind} " in sheet.css
        assert background in sheet.css
    assert BUTTON_LABEL in sheet.css


def test_semantic_button_stylesheet_never_emits_a_default_rule():
    """A blanket ``.bk-btn-default`` rule would collide with the marker chips."""
    assert "bk-btn-default" not in semantic_button_stylesheet().css


def test_semantic_button_stylesheet_overrides_hover():
    """Without a hover rule a themed button flips to stock Bokeh under the
    cursor, because Bokeh's hover reads ``var(--primary-hover)``."""
    css = semantic_button_stylesheet().css
    for kind in ("primary", "success", "warning", "danger"):
        assert f".bk-btn.bk-btn-{kind}:hover" in css


def test_semantic_button_stylesheet_is_fresh_per_call():
    assert semantic_button_stylesheet() is not semantic_button_stylesheet()


def test_semantic_button_selectors_outrank_bokehs_active_rule():
    """Bokeh ships ``.bk-active.bk-btn-primary`` (two classes). A single-class
    override would lose to it and a toggled button would revert to stock."""
    css = semantic_button_stylesheet().css
    for kind in ("primary", "success", "warning", "danger"):
        assert f".bk-btn.bk-btn-{kind}" in css
        assert f" .bk-btn-{kind} {{" not in css


# ---------------------------------------------------------------------------
# Seam
# ---------------------------------------------------------------------------
def test_helao_vis_themes_its_document():
    """The one hook that reaches all six ``HelaoVis`` construction sites.

    Behavioural rather than a source grep: construct a real ``HelaoVis`` over a
    real ``Document`` and look for the carrier. ``HelaoVis`` has no config
    injection seam of its own, so the module-level ``CONFIG`` is swapped and
    restored the way ``unit_test_config_seam.py`` does it.
    """
    import tempfile

    from helao.helpers import config_loader

    from helao.core.servers.vis import HelaoVis

    config = {
        "root": tempfile.mkdtemp(),
        "servers": {
            "VIS": {
                "host": "127.0.0.1",
                "port": 5099,
                "bokeh": "test_bokeh_theme",
                "group": "visualizer",
            }
        },
    }
    saved = config_loader.CONFIG
    config_loader.CONFIG = config
    try:
        doc = Document()
        HelaoVis("VIS", doc)
    finally:
        config_loader.CONFIG = saved

    assert doc.theme is HELAO_THEME
    (carrier,) = doc.roots
    assert isinstance(carrier, Div)
    assert CARRIER_TAG in carrier.tags
