"""Rendered check of the Bokeh documents: operator, live vis, action vis.

No check in this repo loaded a Bokeh document in a browser before this one.
That matters more here than on the Reflex side, because Bokeh's theming reaches
its widgets through a *measured* seam rather than an obvious one, and every
failure mode in it is silent:

* **Everything is inside a shadow root.** In Bokeh 3 every ``UIElement``
  renders into its own, and layout containers nest, so a button in a row in a
  column is three boundaries deep. ``document.querySelectorAll('button')``
  evaluated in the page therefore returns **zero** on the operator -- measured,
  on a document carrying 25 buttons. Every selector here goes through a
  Playwright locator, which pierces open shadow roots; anything written as
  ``page.evaluate`` with a ``querySelector`` would silently assert nothing.
  Same for text: ``document.body.innerText`` is empty on all three documents.
* **``GlobalInlineStyleSheet`` reaches only the chrome.** The page canvas and
  the font stack come through ``<head>``; widget internals do not, and need a
  per-widget ``InlineStyleSheet``. Both halves are asserted, because they fail
  independently.
* **``.bk-btn-default`` must stay unstyled.** ``semantic_button_stylesheet()``
  overrides the four semantic classes and must never emit a ``.bk-btn-default``
  rule -- the marker chips are ``default`` buttons carrying their own
  per-widget override, and a blanket rule collides with them. ``button_type``
  is invisible to the palette AST sweep, so a rendered check is the only place
  that collision can be observed. Asserted here as: default buttons measure a
  light fill, semantic ones do not.

Unlike the Reflex half, Bokeh's stylesheet carries plain hex, so a measured
semantic button matches ``palette.py`` exactly rather than approximately --
there is no OKLCH conversion in this path. The check asserts both: the exact
colour *and* the achieved contrast.

Run it against a launched group::

    python launch.py goldenvis
    python helao/core/tests/browser_parity/check_bokeh_docs.py goldenvis
"""

import json
import sys

from playwright.sync_api import sync_playwright

from helao.core.servers.palette import (
    BUTTON_DANGER_BG,
    BUTTON_PRIMARY_BG,
    BUTTON_SUCCESS_BG,
    BUTTON_WARNING_BG,
    PAGE_BG,
    UI_FONT_STACK,
)
from helao.core.tests.browser_parity.probe import (
    Measurement,
    canvas_ink,
    contrast,
    gl_stats,
    new_page,
    page_problems,
    to_srgb,
)

FLOOR_BODY_TEXT = 4.5
FLOOR_SURFACE = 1.20

#: Semantic button classes and the palette constant each must render.
SEMANTIC_BUTTONS = {
    "primary": BUTTON_PRIMARY_BG,
    "success": BUTTON_SUCCESS_BG,
    "warning": BUTTON_WARNING_BG,
    "danger": BUTTON_DANGER_BG,
}

#: Exact-match tolerance for a Bokeh semantic button, per channel.
#:
#: **One, not the Reflex side's three.** Bokeh's stylesheet carries the hex
#: from ``palette.py`` straight through -- there is no OKLCH round trip in this
#: path -- so a measured semantic fill equals the constant. Measured:
#: ``primary`` renders ``rgb(3,105,161)`` against ``sky-700`` ``#0369a1`` =
#: ``rgb(3,105,161)``, exactly. A tolerance of one absorbs a compositor
#: rounding artefact and nothing else.
BOKEH_TOLERANCE = 1

#: A ``.bk-btn-default`` fill must stay at least this light. Bokeh's stock
#: default button is near-white; any semantic hue is far below this. The point
#: is not the exact shade -- it is that a blanket ``.bk-btn-default`` rule,
#: which would collide with the marker chips' own per-widget override, has not
#: been introduced.
DEFAULT_BUTTON_MIN_LUMA = 200

#: Documents in the gate pair, by config, as ``{name: (port, expectations)}``.
#:
#: ``min_divs`` is the content assertion that must pass before any colour on
#: that document is recorded -- a document that failed to build still has a
#: themed ``<body>``, and reading a page background off it is the vacuous pass
#: this lane exists to prevent. Measured on a healthy run: operator 605 divs,
#: live 169, action visualizer 14.
DOCUMENTS = {
    "operator": {
        "port": 5001,
        "min_divs": 100,
        "min_buttons": 10,
        "header": "Operator",
        "semantic": ["primary", "success", "danger"],
        "expect_default_buttons": True,
    },
    "live": {
        "port": 5002,
        "min_divs": 50,
        "min_buttons": 0,
        "header": "Live visualizer on",
        "semantic": [],
        "min_canvases": 1,
        "expect_default_buttons": False,
    },
    "actvis": {
        "port": 5003,
        "min_divs": 5,
        "min_buttons": 0,
        "header": "Action visualizer on",
        "semantic": [],
        "expect_default_buttons": False,
    },
}

#: Bokeh needs a websocket round trip before its widgets exist.
SETTLE_MS = 12000


def _hex_to_rgb(value: str) -> tuple:
    raw = value.lstrip("#")
    return tuple(int(raw[i : i + 2], 16) for i in (0, 2, 4))


def measure_button(page, measurement: Measurement, role: str) -> None:
    """Measure one semantic button class, if the document carries it."""
    locator = page.locator(f".bk-btn-{role}")
    count = locator.count()
    measurement.record(f"btn_{role}_count", count)
    if not measurement.require(
        count > 0,
        f"no .bk-btn-{role} button on this document; the semantic stylesheet "
        f"reaches widgets through a per-widget InlineStyleSheet, and its "
        f"absence is invisible to the palette AST sweep",
    ):
        return
    raw = locator.first.evaluate(
        "(el) => { const s = getComputedStyle(el);"
        " return {bg: s.backgroundColor, fg: s.color}; }"
    )
    background = to_srgb(page, raw["bg"])
    foreground = to_srgb(page, raw["fg"])
    expected = _hex_to_rgb(SEMANTIC_BUTTONS[role])
    drift = max(abs(a - b) for a, b in zip(background, expected))
    measurement.record(f"btn_{role}_bg_rgb", list(background))
    measurement.record(f"btn_{role}_drift", drift)
    measurement.require(
        drift <= BOKEH_TOLERANCE,
        f".bk-btn-{role} renders {background}, expected {expected} "
        f"(drift {drift}); the per-widget stylesheet did not reach it",
    )
    ratio = contrast(foreground, background)
    measurement.record(f"btn_{role}_contrast", ratio)
    measurement.require(
        ratio >= FLOOR_BODY_TEXT,
        f".bk-btn-{role} label measures {ratio} on its own fill",
    )


def measure_default_buttons(page, measurement: Measurement) -> None:
    """Assert ``.bk-btn-default`` was left alone.

    A blanket ``.bk-btn-default`` rule in ``semantic_button_stylesheet()``
    would collide with the marker chips, which are ``default`` buttons with
    their own per-widget override. Nothing static can see that: ``button_type``
    does not appear in the AST sweep, and a grep can only find the rule if
    someone thought to grep for it.
    """
    locator = page.locator(".bk-btn-default")
    count = locator.count()
    measurement.record("btn_default_count", count)
    if not measurement.require(count > 0, "no .bk-btn-default button"):
        return
    raw = locator.first.evaluate("(el) => getComputedStyle(el).backgroundColor")
    background = to_srgb(page, raw)
    measurement.record("btn_default_bg_rgb", list(background))
    measurement.require(
        min(background) >= DEFAULT_BUTTON_MIN_LUMA,
        f".bk-btn-default renders {background}, darker than a stock default "
        f"button: a blanket rule has been added and it collides with the "
        f"marker chips' per-widget override",
    )


def measure_document(page, name: str, expectations: dict) -> Measurement:
    """Load one Bokeh document and take every measurement it supports."""
    measurement = Measurement(name)
    port = expectations["port"]
    page.goto(f"http://127.0.0.1:{port}", wait_until="load", timeout=60000)
    page.wait_for_timeout(SETTLE_MS)

    measurement.record("doc_title", page.title())

    # Content first, always. Every colour below is read off this document, and
    # a document that never built still themes its <body>.
    divs = page.locator("div").count()
    measurement.record("div_count_band", divs // 50)
    if not measurement.require(
        divs >= expectations["min_divs"],
        f"{divs} divs, expected at least {expectations['min_divs']}: the "
        f"document did not build, so nothing measured on it would mean anything",
    ):
        return measurement

    buttons = page.locator("button").count()
    measurement.record("button_count", buttons)
    measurement.require(
        buttons >= expectations["min_buttons"],
        f"{buttons} buttons, expected at least {expectations['min_buttons']}",
    )

    # The header Div is the one piece of light-DOM-ish text worth pinning: it
    # names the document and the config, and it is what a blank page lacks.
    header_divs = page.locator(".bk-Div, div.bk-clearfix")
    texts = []
    for index in range(min(header_divs.count(), 10)):
        try:
            texts.append(header_divs.nth(index).inner_text())
        except Exception:  # a zero-size or detached node; not a failure
            continue
    joined = " ".join(texts)
    measurement.record("header_found", expectations["header"] in joined)
    measurement.require(
        expectations["header"] in joined,
        f"the document header '{expectations['header']}' did not render",
    )

    # Chrome: the GlobalInlineStyleSheet half of the theme.
    chrome = page.evaluate(
        "() => { const b = getComputedStyle(document.body);"
        " return {bg: b.backgroundColor, font: b.fontFamily}; }"
    )
    canvas_bg = to_srgb(page, chrome["bg"])
    expected_bg = _hex_to_rgb(PAGE_BG)
    drift = max(abs(a - b) for a, b in zip(canvas_bg, expected_bg))
    measurement.record("page_bg_rgb", list(canvas_bg))
    measurement.record("page_bg_drift", drift)
    measurement.require(
        drift <= BOKEH_TOLERANCE,
        f"page canvas renders {canvas_bg}, expected PAGE_BG {expected_bg}: "
        f"apply_theme's <head> stylesheet did not reach this document",
    )
    first_family = UI_FONT_STACK.split(",")[0].strip().strip('"')
    measurement.record("ui_font_first", first_family in chrome["font"])
    measurement.require(
        first_family in chrome["font"],
        f"body font is {chrome['font'][:60]!r}, missing {first_family}",
    )

    # Widgets: the per-widget InlineStyleSheet half.
    for role in expectations.get("semantic", []):
        measure_button(page, measurement, role)
    if expectations.get("expect_default_buttons"):
        measure_default_buttons(page, measurement)

    # Drawn content. Bokeh figures render on 2D canvases, so the live count of
    # *WebGL* contexts here is expected to be zero -- recorded anyway, because
    # a Bokeh document that suddenly started consuming WebGL contexts would be
    # spending a page's budget nobody accounted for.
    canvases = page.locator("canvas")
    measurement.record("canvas_count", canvases.count())
    stats = gl_stats(page)
    measurement.record("webgl_live", stats["live"])
    measurement.record("webgl_lost", stats["lost"])
    measurement.require(
        stats["lost"] == 0, f"{stats['lost']} WebGL context(s) were evicted"
    )

    minimum = expectations.get("min_canvases", 0)
    if minimum:
        if measurement.require(
            canvases.count() >= minimum,
            f"{canvases.count()} canvases, expected at least {minimum}",
        ):
            inks = []
            for index in range(canvases.count()):
                ink = canvas_ink(page, "canvas", index)
                inks.append(ink.get("distinct", -1))
                measurement.record(f"canvas{index}_ink_distinct", ink.get("distinct"))
            # A figure that painted axes has hundreds of distinct colours; a
            # canvas that never painted has one or two.
            #
            # Two values, and the split is load-bearing. *How many* canvases
            # have painted at capture time is a function of when the browser
            # connected -- measured, the same document gave 5 on one run and 4
            # on the next, which is a diff that would fire on every run and
            # teach everyone to ignore the diff. *Whether any* has painted is
            # the property being asserted, and it is stable. The count is kept
            # because it is useful in a failure report, and named so the
            # volatile-key rule excludes it.
            measurement.record("canvas_painted_count", sum(1 for i in inks if i > 20))
            measurement.record("canvas_any_painted", any(i > 20 for i in inks))
            measurement.require(
                any(i > 20 for i in inks),
                f"no canvas on this document painted anything (distinct "
                f"colours per canvas: {inks})",
            )
    return measurement


def run(config: str) -> tuple:
    """Measure every Bokeh document of one running group."""
    measurements = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page, errors = new_page(browser)
        for name, expectations in DOCUMENTS.items():
            measurements.append(measure_document(page, name, expectations))
        browser.close()
    problems = [p for m in measurements for p in m.problems]
    real_errors = page_problems(errors)
    if real_errors:
        problems.append(f"browser errors: {real_errors[:5]}")
    return measurements, problems


def main() -> int:
    """CLI: ``check_bokeh_docs.py [config] [--json out.json]``."""
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    config = args[0] if args else "goldenvis"
    out = None
    for index, arg in enumerate(sys.argv):
        if arg == "--json" and index + 1 < len(sys.argv):
            out = sys.argv[index + 1]

    measurements, problems = run(config)
    if out:
        from helao.core.tests.browser_parity.matrix import save_matrix

        save_matrix(out, config, measurements)
        print(f"matrix written to {out}")
    for m in measurements:
        print(f"  {m.name}: {json.dumps(m.values, sort_keys=True)[:300]}")
    if problems:
        for problem in problems:
            print(f"FAIL: {problem}")
        return 1
    print(f"PASS: {len(measurements)} Bokeh documents, styles and pixels measured")
    return 0


if __name__ == "__main__":
    sys.exit(main())
