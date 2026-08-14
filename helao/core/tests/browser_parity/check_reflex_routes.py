"""Rendered check of every Reflex route: computed styles and drawn pixels.

Covers all six entries of ``app.SHELL_ROUTES`` -- including ``/`` and
``/control``, which no check in this repo touched before -- and asserts, for
each, a *content* fact and then a *style* fact measured from the same elements.
The order is the point: a style measured off a selector that matched nothing is
the way this kind of check passes while the page is broken.

What is asserted per route, and why each one can fail:

* **Page tint** (``REFLEX_PAGE_TINTS``). The shell's measured background must
  match the route's declared shade to within a small per-channel tolerance, and
  no two routes may share a tint. A stale bundle drops the ``bg-*`` utility
  from the compiled CSS entirely and the shell measures transparent/white --
  which is what this catches, and what a source grep for ``bg-sky-50`` cannot.
* **Text contrast on the measured pixels.** Heading and muted text are read
  back through the browser's own sRGB rasterizer and their contrast against the
  measured tint must clear the role floor. Not a hex comparison: Tailwind v4 is
  OKLCH-native and will not reproduce ``palette.py``'s hex (see
  :mod:`~helao.core.tests.browser_parity.probe`).
* **Table header hues** (``REFLEX_TABLE_HUES``) on the routes that carry
  tables, again as achieved contrast rather than as a colour match.
* **Control-button hues** on ``/control``: the five P7g routes render buttons
  whose colour *is* the state signal, so an unstyled button is a control that
  lies about the line it drives.
* **Stop-button hues** on any potentiostat panel (P7i). These are the newest
  ``class_name=`` usage in the tree, so they are the sharpest stale-bundle
  detector the lane has.
* **Drawn pixels and live WebGL contexts.** At least one chart per charting
  route must have actually painted data, and the page's live context count must
  stay inside its budget with zero evictions.

**A static string is a statement about the bundle, not about the group, and
this is measured rather than argued.** Panel headings are compiled into the
exported JavaScript -- ``grep 'GP simulator: GPSIM' .reflex-bundle/helao_ui/
assets/_live_._index-*.js`` finds it. Serving a config with *no GPSIM server*
through a bundle built for one therefore renders that heading perfectly, and a
heading assertion passes on a group that does not have the panel. Confirmed by
running this check's ``goldenreflex`` expectations against a ``goldenreflexspec``
group: every heading assertion passed while the chart, WebGL and Specs
assertions all failed.

The consequence for anyone extending this file: ``headings`` is a **bundle**
assertion and is useful only as such. Anything that must say something about
the running group has to come from live state -- the chart descriptions ``xy``
emits from a payload, the canvas pixels, the WebGL context count, a table's
rows. Those are the assertions carrying this lane; the text ones are cheap
context around them.

Run it against a launched group::

    python launch.py goldenreflex
    python helao/core/tests/browser_parity/check_reflex_routes.py http://127.0.0.1:5010
"""

import json
import sys
from typing import Optional

from playwright.sync_api import sync_playwright

from helao.ui.shared.palette import (
    REFLEX_PAGE_TINTS,
    REFLEX_TABLE_HUES,
    TW,
)
from helao.core.tests.browser_parity.probe import (
    Measurement,
    canvas_ink,
    contrast,
    element_colors,
    gl_stats,
    new_page,
    page_problems,
    to_srgb,
)

#: Role floors, pinned here rather than imported from ``test_palette.py`` for
#: the reason given in ``probe._linearize``: these measure the browser, those
#: measure the palette, and the two must be able to disagree.
FLOOR_BODY_TEXT = 4.5
FLOOR_HEADING_TEXT = 3.0
FLOOR_CONTROL = 3.0

#: Per-channel slack allowed between a measured tint and ``TW``'s hex.
#:
#: **Three, not zero, and not thirty.** Tailwind v4 emits its palette in OKLCH,
#: so a measured shade is the browser's conversion rather than the pinned hex.
#: Measured on this stack, the unsaturated 50-level tints every route uses
#: round-trip *exactly* (``sky-50`` -> ``rgb(240,249,255)`` = ``#f0f9ff``), so
#: a tolerance of three is slack for a rounding difference and nothing more. It
#: is deliberately far too tight to absorb the divergence saturated shades
#: show -- ``violet-700`` renders 32 units off in green -- which is why
#: saturated colours are asserted through :func:`contrast` instead of here.
TINT_TOLERANCE = 3

#: Live WebGL contexts allowed on one page.
#:
#: Chrome's hard cap is 16, past which it evicts the oldest context *silently
#: and permanently* -- the evicted chart never draws again while data keeps
#: arriving, the view stays mounted, the append keeps firing, and nothing is
#: logged on either side. A budget at the cap would therefore only fail after
#: the damage; 12 leaves room for the compositor's own contexts and for the
#: browser a station actually runs, and it fails while the page is still
#: correct. ``webgl_lost`` above zero is asserted separately and is the direct
#: observation of an eviction that has already happened.
#:
#: **Measured, and one number here is not fully calibrated -- say so rather
#: than imply otherwise.** On this Linux sim: ``goldenreflex`` ``/live`` 2,
#: ``/action`` 1; ``htereflex`` ``/live`` 4 (12 canvas elements), ``/action``
#: **8** (24 canvas elements, 8 charts). The gap between canvas elements and
#: contexts is ``xy`` drawing axes and overlays on ordinary 2D canvases, which
#: is exactly why counting ``<canvas>`` is not a substitute.
#:
#: The uncalibrated part: the simulator discovers **no BioLogic channels**, so
#: the per-channel panels contribute nothing to that 8. A station with four
#: channels adds charts this measurement has never seen -- the pre-merge figure
#: on record for that page was 16, at the cliff edge. So 12 is a *warning*
#: threshold sitting above every Linux-measurable page and below the cap; it is
#: **not** a claim about the station, and the station number has to be measured
#: at the station. What holds unconditionally is the separate ``webgl_lost ==
#: 0`` assertion: it observes an eviction that has already happened rather than
#: predicting one, so it is correct at any channel count.
WEBGL_BUDGET = 12

#: Ink thresholds for classifying what a chart canvas drew, from measured
#: values on a live page: a chart carrying six data series showed ~16700
#: distinct colours, an axes-and-labels-only frame 249, and a chart with no
#: series at all 3. The bands are wide because the exact count depends on the
#: data; the classification does not.
INK_DRAWN = 1000
INK_AXES_ONLY = 20


def classify_ink(ink: dict) -> str:
    """Bucket a canvas measurement into blank / axes-only / drawn.

    The bucket is what the parity matrix compares. The raw distinct-colour
    count is genuinely run-dependent -- it moves with the simulator's data --
    so diffing it would report a difference on every run and train everyone to
    ignore the diff.
    """
    if "error" in ink:
        return f"error:{ink['error']}"
    distinct = ink["distinct"]
    if distinct >= INK_DRAWN:
        return "drawn"
    if distinct >= INK_AXES_ONLY:
        return "axes-only"
    return "blank"


#: Per-config expectations. Keyed by config prefix so a second config joins the
#: lane by adding an entry, not by editing the checks.
#:
#: ``headings`` are content the route must show; ``charts`` is how many charting
#: panels the route hosts; ``drawn`` says whether a chart on this route must
#: have painted *data* by settle time. ``drawn`` is False for ``/action`` on
#: ``goldenreflex`` and that is not a weakened assertion -- CPSIM streams
#: ``ws_data`` only while an action runs, so requiring data there would fail on
#: correct behaviour. The check starts an action to make it true where it can.
CONFIG_EXPECTATIONS = {
    "goldenreflex": {
        "/": {"headings": ["Routes"], "links": 5},
        "/live": {
            "headings": ["Live visualizers", "Live: SIM", "GP simulator: GPSIM"],
            "charts": 2,
            "drawn": True,
        },
        "/action": {
            "headings": ["Action visualizers", "Action: CPSIM"],
            "charts": 1,
            "drawn": False,
        },
        "/operator": {
            "headings": ["Operator"],
            # Each table is behind its own tab path, and Radix does not render
            # an inactive tab's content at all -- so a table is measurable only
            # once its tab is open. Reading the default tab's body for them is
            # a check that fails for the wrong reason, which is how this was
            # first written. Four kinds through four paths, because the point
            # of keying hues by *kind* is that the same object type reads the
            # same in Queues and in History.
            "tables": [
                {"kind": "sequence", "tabs": ["Queues", "Sequences"]},
                {"kind": "experiment", "tabs": ["Queues", "Experiments"]},
                {"kind": "action", "tabs": ["Queues", "Actions"]},
                {"kind": "server", "tabs": ["Queues", "Servers"]},
            ],
            # Q10's omitting branch: this config declares no
            # `seqspec_parser_path`, so the Specs tab must say so. Asserted
            # positively -- if the note went missing while no parser was
            # configured, the degrade path itself has broken.
            "specs": "absent",
        },
        "/browser": {
            "headings": ["Data browser"],
            "tables": [{"kind": "browser", "tabs": []}],
        },
        "/control": {
            "headings": ["Engineering controls"],
            "controls": ["gamry_aux", "Thorlab_led", "cell_valve", "purge_valve"],
        },
    },
    # The hte panels, which is where P7i's potentiostat stop buttons live.
    #
    # **They are not reachable from `goldenreflex` and that is not an
    # oversight**, it is the config-dependence of the compiled CSS: Tailwind
    # only emits utilities it finds in the *exported* frontend, and a bundle
    # built for `goldenreflex` compiles only the panels that config mounts.
    # Measured -- `bg-red-700` appears zero times in the goldenreflex bundle's
    # CSS and once in the htereflex bundle's. So the newest `class_name=` usage
    # in the tree is only measurable here, which makes this entry the sharpest
    # stale-bundle detector the lane has.
    #
    # `expect_stops` is the count that must render with nothing running: the
    # single-potentiostat panel carries its button from the start, per-channel
    # panels build theirs from channels seen on the wire.
    "htereflex": {
        "/live": {
            "headings": ["CO2 (ppm)", "Flow rate (sccm)", "Pressure (psi)"],
            "charts": 4,
            "drawn": True,
        },
        "/action": {
            "headings": ["Gamry:", "BioLogic:", "Cells:"],
            "charts": 5,
            "drawn": False,
            "expect_stops": 1,
        },
    },
    # Q10's *declaring* branch. Only the operator route differs, so only the
    # operator route is measured -- re-measuring five identical routes under a
    # second launch would double the lane's runtime to re-assert what the
    # `goldenreflex` entry already asserted.
    "goldenreflexspec": {
        "/operator": {
            "headings": ["Operator"],
            "specs": "present",
        },
    },
}

#: How long a route is given to settle before measuring. The panels tick from
#: an ``rx.moment`` in the page, so a chart needs several intervals to have
#: anything to draw.
SETTLE_MS = 14000

#: Shorter settle for the routes with no live data path.
STATIC_SETTLE_MS = 6000


def page_tint(measurement: Measurement) -> tuple:
    """The tint already measured for this route, as a tuple.

    Recorded as a list (JSON has no tuples) and read back here, so a contrast
    against "this page's canvas" always uses the pixel measured on *this* page
    rather than an assumed white.
    """
    return tuple(measurement.values.get("tint_rgb") or (255, 255, 255))


def colors_or_fail(page, measurement: Measurement, selector: str):
    """Measured colours for *selector*, or ``None`` with a failure recorded.

    The one place a colour is allowed to come from. ``element_colors`` returns
    ``None`` when its selector matched nothing, and a caller that subscripted
    that result without checking would raise -- but a caller that *defaulted*
    it would record a fabricated colour, which is worse: the matrix would carry
    a value no pixel ever had. Funnelling every read through here means the
    only way to get a colour is to have found an element.
    """
    colors = element_colors(page, selector)
    if colors is None:
        measurement.fail(f"nothing matched '{selector}', so no colour was measured")
    return colors


def measure_shell(page, measurement: Measurement, route: str) -> Optional[tuple]:
    """Assert the page shell rendered, then measure its tint.

    Returns:
        tuple: The measured tint sRGB, or ``None`` when the shell is missing --
        in which case every later style measurement on this route is skipped,
        because measuring colours off a page that did not render is precisely
        the vacuous pass this lane exists to prevent.
    """
    shell = page.locator('div[class*="min-h-screen"]')
    if not measurement.require(shell.count() > 0, "no page shell rendered"):
        return None

    text_length = len(page.inner_text("body"))
    # A shell with no content is a blank page that still has computed styles.
    if not measurement.require(
        text_length > 40, f"page shell is effectively empty ({text_length} chars)"
    ):
        return None
    measurement.record("body_text_length_band", text_length // 100)

    style = shell.first.evaluate(
        "(el) => { const s = getComputedStyle(el);"
        " return {bg: s.backgroundColor, cls: el.className}; }"
    )
    tint = to_srgb(page, style["bg"])
    measurement.record("tint_rgb", list(tint))

    shade = REFLEX_PAGE_TINTS[route]
    expected = tuple(int(TW[shade].lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
    measurement.record("tint_shade", shade)
    drift = max(abs(a - b) for a, b in zip(tint, expected))
    measurement.record("tint_drift", drift)
    measurement.require(
        drift <= TINT_TOLERANCE,
        f"tint is {tint}, expected {shade} = {expected} "
        f"(drift {drift} > {TINT_TOLERANCE}); a bundle built before this "
        f"utility existed renders the shell unstyled",
    )
    # The class must actually be on the element: a tint that matches by
    # coincidence (white page, white-ish expectation) would otherwise pass.
    measurement.require(
        f"bg-{shade}" in style["cls"],
        f"shell does not carry bg-{shade}: {style['cls'][:120]}",
    )
    return tint


def measure_text_contrast(page, measurement: Measurement, tint: tuple) -> None:
    """Measure heading and muted-text contrast against the measured tint."""
    headings = page.locator("h1, h2, h3, h4, h5")
    if measurement.require(headings.count() > 0, "no headings rendered"):
        colors = colors_or_fail(page, measurement, "h1, h2, h3, h4, h5")
        if colors is not None:
            ratio = contrast(colors["fg"], tint)
            measurement.record("heading_contrast", ratio)
            measurement.record("heading_rgb", list(colors["fg"]))
            measurement.require(
                ratio >= FLOOR_HEADING_TEXT,
                f"heading contrast {ratio} < {FLOOR_HEADING_TEXT} on this tint",
            )

    muted = page.locator(".text-slate-600")
    measurement.record("muted_count", muted.count())
    colors = (
        colors_or_fail(page, measurement, ".text-slate-600") if muted.count() else None
    )
    if colors is not None:
        ratio = contrast(colors["fg"], tint)
        measurement.record("muted_contrast", ratio)
        measurement.require(
            ratio >= FLOOR_BODY_TEXT,
            f"muted text contrast {ratio} < {FLOOR_BODY_TEXT} on this tint",
        )


#: The note the operator's Specs tab renders when no parser is configured.
#: Matched verbatim against ``OperatorSpecState.on_mount``'s message.
NO_PARSER_NOTE = "no spec parser is configured for this station"


def open_tab(page, measurement: Measurement, name: str) -> bool:
    """Switch to a named tab, asserting it exists first."""
    tab = page.get_by_role("tab", name=name)
    if not measurement.require(tab.count() > 0, f"no '{name}' tab rendered"):
        return False
    tab.first.click()
    page.wait_for_timeout(3000)
    return True


def measure_specs_tab(page, measurement: Measurement, branch: str) -> None:
    """Assert the Q10 branch this config selects.

    The instrument's ambiguity -- "is the Specs tab empty because this station
    configures no parser, or because the parser it configures is broken?" --
    does not exist for a gate, because the gate holds the config. So the branch
    is asserted from the config rather than inferred from the page:

    * ``"absent"``  -- the config omits ``seqspec_parser_path``, so the
      "nothing configured" note **must be present**. Asserted positively: its
      absence with no parser configured would mean the degrade path broke, and
      a check that only looked for specs would read that as a pass.
    * ``"present"`` -- the config declares one, so the tab must list at least
      one spec file and must **not** carry the degraded note.
    """
    if not open_tab(page, measurement, "Specs"):
        return
    body = page.inner_text("body")
    degraded = NO_PARSER_NOTE in body
    measurement.record("specs_branch", branch)
    measurement.record("specs_degraded_note", degraded)
    if branch == "absent":
        measurement.require(
            degraded,
            "the config declares no seqspec parser, so the Specs tab must say "
            f"'{NO_PARSER_NOTE}' -- it does not, so the degrade path is broken",
        )
        return

    measurement.require(
        not degraded,
        f"the config declares a seqspec parser but the Specs tab reports "
        f"'{NO_PARSER_NOTE}'. A relative parser path resolves against the "
        f"Reflex process's own directory, not the repo root, and fails exactly "
        f"like an unconfigured station",
    )
    listed = "specification file(s) in" in body
    measurement.record("specs_listed", listed)
    measurement.require(
        listed,
        "the Specs tab lists no specification files for a declared parser",
    )


def measure_tables(page, measurement: Measurement, specs: list) -> None:
    """Assert each declared table kind rendered, and measure its header hue."""
    for spec in specs:
        kind, tabs = spec["kind"], spec.get("tabs", [])
        if not all(open_tab(page, measurement, name) for name in tabs):
            continue
        headers = page.locator("th")
        measurement.record(f"table_{kind}_header_count", headers.count())
        if not measurement.require(
            headers.count() > 0, f"no table headers rendered for {kind}"
        ):
            continue
        background_shade, text_shade, _ = REFLEX_TABLE_HUES[kind]
        selector = f"th.bg-{background_shade}"
        matching = page.locator(selector)
        measurement.record(f"table_{kind}_headers", matching.count())
        if not measurement.require(
            matching.count() > 0,
            f"no {kind} table header carries bg-{background_shade}; "
            f"a bundle built before this utility renders a stock grey header",
        ):
            continue
        colors = colors_or_fail(page, measurement, selector)
        if colors is None:
            continue
        ratio = contrast(colors["fg"], colors["bg"])
        measurement.record(f"table_{kind}_contrast", ratio)
        measurement.record(f"table_{kind}_bg_rgb", list(colors["bg"]))
        measurement.require(
            ratio >= FLOOR_BODY_TEXT,
            f"{kind} header text on {background_shade} measures {ratio}, "
            f"below the {FLOOR_BODY_TEXT} body floor",
        )
        measurement.require(
            f"text-{text_shade}" in colors["class"],
            f"{kind} header does not carry text-{text_shade}",
        )


def measure_controls(page, measurement: Measurement, lines: list) -> None:
    """Assert /control's buttons rendered and carry their state colour."""
    body = page.inner_text("body")
    for line in lines:
        measurement.require(line in body, f"control line '{line}' did not render")

    # Every digital output opens `unknown` against a simulator with no
    # readback, so amber is the state to expect here -- and the colour *is*
    # the signal, which is what makes an unstyled button a safety problem
    # rather than a cosmetic one.
    amber = page.locator("button.bg-amber-700")
    measurement.record("control_unknown_buttons", amber.count())
    if measurement.require(
        amber.count() >= len(lines),
        f"{amber.count()} amber (unknown-state) controls for {len(lines)} lines",
    ):
        colors = colors_or_fail(page, measurement, "button.bg-amber-700")
        if colors is not None:
            ratio = contrast(colors["fg"], colors["bg"])
            measurement.record("control_unknown_contrast", ratio)
            measurement.record("control_unknown_bg_rgb", list(colors["bg"]))
            measurement.require(
                ratio >= FLOOR_BODY_TEXT,
                f"unknown-state control label measures {ratio} on its own fill",
            )

    read = page.locator("button.bg-sky-700")
    measurement.record("control_read_buttons", read.count())
    if measurement.require(read.count() > 0, "no 'Read state' button rendered"):
        colors = colors_or_fail(page, measurement, "button.bg-sky-700")
        if colors is not None:
            ratio = contrast(colors["bg"], page_tint(measurement))
            measurement.record("control_read_on_canvas_contrast", ratio)
            measurement.require(
                ratio >= FLOOR_CONTROL,
                f"read button against the /control canvas measures {ratio}, "
                f"below the {FLOOR_CONTROL} control floor",
            )


def measure_stop_buttons(page, measurement: Measurement, expected: int = 0) -> None:
    """Measure any P7i potentiostat stop button on this route.

    Recorded on every route, including those with none: a count of zero is
    itself a comparable value, and the panels that carry these buttons are
    deployment code that a different config mounts on a different page.
    """
    stops = page.locator("button.bg-red-700")
    measurement.record("stop_buttons", stops.count())
    if expected:
        measurement.require(
            stops.count() >= expected,
            f"{stops.count()} stop button(s), expected at least {expected}; "
            f"a bundle built before P7i renders them with no fill at all",
        )
    if stops.count() == 0:
        return
    colors = colors_or_fail(page, measurement, "button.bg-red-700")
    if colors is None:
        return
    label = contrast(colors["fg"], colors["bg"])
    canvas = contrast(colors["bg"], page_tint(measurement))
    measurement.record("stop_label_contrast", label)
    measurement.record("stop_on_canvas_contrast", canvas)
    measurement.record("stop_bg_rgb", list(colors["bg"]))
    measurement.require(
        label >= FLOOR_BODY_TEXT,
        f"stop-button label measures {label} on its own fill",
    )
    measurement.require(
        canvas >= FLOOR_CONTROL,
        f"stop button against this page's canvas measures {canvas}",
    )


def measure_charts(
    page, measurement: Measurement, expected_charts: int, must_draw: bool
) -> None:
    """Assert the charts rendered, drew, and stayed inside the WebGL budget."""
    body = page.inner_text("body")
    # xy emits an accessibility summary per chart. It is the cheapest proof
    # that a chart component exists at all, and it carries the series count.
    descriptions = [ln for ln in body.splitlines() if "Interactive chart" in ln]
    measurement.record("chart_descriptions", len(descriptions))
    measurement.require(
        len(descriptions) >= expected_charts,
        f"{len(descriptions)} chart descriptions, expected {expected_charts}",
    )

    stats = gl_stats(page)
    measurement.record("webgl_live", stats["live"])
    measurement.record("webgl_lost", stats["lost"])
    measurement.require(
        stats["live"] <= WEBGL_BUDGET,
        f"{stats['live']} live WebGL contexts exceeds the {WEBGL_BUDGET} "
        f"per-page budget; Chrome evicts silently past 16",
    )
    # The direct observation. A lost context is a chart that will never draw
    # again, and this is the only place either stack can see it.
    measurement.require(
        stats["lost"] == 0,
        f"{stats['lost']} WebGL context(s) were evicted; those charts are "
        f"dead for the life of the page and nothing else reports it",
    )
    # One WebGL context per chart is the contract; fewer means a chart never
    # got a context, which renders as a permanently blank plot.
    measurement.require(
        stats["live"] >= expected_charts,
        f"{stats['live']} WebGL contexts for {expected_charts} charts",
    )

    canvases = page.locator("canvas")
    measurement.record("canvas_elements", canvases.count())

    buckets = []
    for index in range(canvases.count()):
        ink = canvas_ink(page, "canvas", index)
        buckets.append(classify_ink(ink))
        measurement.record(f"canvas{index}_ink_distinct", ink.get("distinct", -1))
    measurement.record("canvas_ink_buckets", sorted(buckets))

    if must_draw:
        measurement.require(
            "drawn" in buckets,
            f"no canvas on this route drew data (buckets: {sorted(buckets)}); "
            f"an evicted or disconnected chart looks exactly like this",
        )
        series = [ln for ln in descriptions if "0 data series" not in ln]
        measurement.require(
            bool(series),
            "every chart reports 0 data series: no data reached the panel",
        )


def measure_route(page, base: str, route: str, expectations: dict) -> Measurement:
    """Load one route and take every measurement it supports."""
    measurement = Measurement(route)
    charts = expectations.get("charts", 0)
    page.goto(f"{base}{route}", wait_until="load", timeout=60000)
    page.wait_for_timeout(SETTLE_MS if charts else STATIC_SETTLE_MS)

    tint = measure_shell(page, measurement, route)
    body = page.inner_text("body")
    for heading in expectations.get("headings", []):
        measurement.require(heading in body, f"'{heading}' did not render")

    if "links" in expectations:
        links = page.locator("a")
        measurement.record("link_count", links.count())
        measurement.require(
            links.count() >= expectations["links"],
            f"{links.count()} links, expected at least {expectations['links']}",
        )

    if tint is None:
        # The shell did not render. Nothing measured past here would mean
        # anything, and recording it would put fabricated values in the matrix.
        return measurement

    measure_text_contrast(page, measurement, tint)
    measure_stop_buttons(page, measurement, expectations.get("expect_stops", 0))
    if expectations.get("specs"):
        measure_specs_tab(page, measurement, expectations["specs"])
    if expectations.get("tab"):
        open_tab(page, measurement, expectations["tab"])
    if expectations.get("tables"):
        measure_tables(page, measurement, expectations["tables"])
    if expectations.get("controls"):
        measure_controls(page, measurement, expectations["controls"])
    if charts:
        measure_charts(page, measurement, charts, expectations.get("drawn", False))
    return measurement


def check_tints_are_distinct(measurements: list) -> list:
    """Every route must carry its *own* tint.

    Without this, a stale bundle that dropped every ``bg-*`` utility -- so all
    six routes measure the same default -- could still clear the per-route
    tolerance if the default happened to sit near one expectation. Distinctness
    is a property of the set, so it has to be checked over the set.
    """
    seen = {}
    problems = []
    for m in measurements:
        tint = tuple(m.values.get("tint_rgb") or ())
        if not tint:
            continue
        if tint in seen:
            problems.append(
                f"{m.name} and {seen[tint]} render the same tint {tint}: "
                f"the functional-section signal is gone"
            )
        seen[tint] = m.name
    return problems


def run(base: str, config: str = "goldenreflex") -> tuple:
    """Measure every route of one running Reflex server.

    Returns:
        tuple: ``(measurements, problems)``.
    """
    expectations = CONFIG_EXPECTATIONS[config]
    measurements = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page, errors = new_page(browser)
        for route in REFLEX_PAGE_TINTS:
            if route not in expectations:
                continue
            measurements.append(measure_route(page, base, route, expectations[route]))
        browser.close()

    problems = [p for m in measurements for p in m.problems]
    problems.extend(check_tints_are_distinct(measurements))
    real_errors = page_problems(errors)
    if real_errors:
        problems.append(f"browser errors: {real_errors[:5]}")
    return measurements, problems


def main() -> int:
    """CLI: ``check_reflex_routes.py [base_url] [config] [--json out.json]``."""
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    base = args[0] if args else "http://127.0.0.1:5010"
    config = args[1] if len(args) > 1 else "goldenreflex"
    out = None
    for index, arg in enumerate(sys.argv):
        if arg == "--json" and index + 1 < len(sys.argv):
            out = sys.argv[index + 1]

    measurements, problems = run(base, config)
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
    print(f"PASS: {len(measurements)} Reflex routes, styles and pixels measured")
    return 0


if __name__ == "__main__":
    sys.exit(main())
