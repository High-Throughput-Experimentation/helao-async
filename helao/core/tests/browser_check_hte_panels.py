"""Headless check of the hte deployment's Reflex panels against a running group.

Not a pytest module: it needs a launched orchestration group, and the whole
point is to load the page in a real browser. The hte sensors have no simulator,
so ``htereflex.yml`` points the test deployment's websocket simulator at the
column names the real drivers publish -- which is what makes each panel's
rolling-mean rules fire here.

Run it after ``python launch.py htereflex``::

    /home/dan/miniforge3/envs/helao/bin/python \\
        helao/core/tests/browser_check_hte_panels.py [base_url]
"""

import json
import sys
import urllib.error
import urllib.request

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5110"

#: Panels the dev config declares, by the heading each renders.
EXPECTED_PANELS = [
    "CO2 (ppm)",
    "Flow rate (sccm)",
    "Pressure (psi)",
    "Temperature (C)",
]

#: Columns that prove the rolling means were computed rather than skipped.
EXPECTED_MEAN_ROWS = ["co2_ppm_mean", "CO2__mass_flow_mean", "pressure_psi_0_mean"]

#: A column that must NOT gain a mean: temp_vis plots its channels raw, and
#: mfc_vis leaves temperature alone.
UNEXPECTED_MEAN_ROWS = ["cell_temp_0_mean", "CO2__temperature_mean"]

#: Long enough for the ring buffer to exceed the 20-point filter width at the
#: simulator's 10 Hz, so the means are real rather than passed-through.
SETTLE_MS = 12000


#: Action panels the dev config declares, by their heading.
EXPECTED_ACTION_PANELS = [
    "Cells:",
    "Power supply:",
    "Gamry:",
    "BioLogic:",
    "Spectra:",
    "Samples:",
]

#: ws_data is silent unless an action is streaming, so the check starts one on
#: each simulator. Two things about doing that, both learned the hard way:
#:
#: * The parameters go in the JSON **body**. Sent as a query string with a `{}`
#:   body, HELAO reads the body as a malformed `action` kwarg, logs "using
#:   blank Action", and the executor dies on the resulting empty `comp_vec`.
#: * That failure does not just lose one action. The crashed executor leaves
#:   the endpoint marked busy, so every later action queues behind it forever
#:   and the panel stays empty until the server restarts.
ACTION_SERVERS = [
    ("http://127.0.0.1:8106", "NIDAQMX"),
    ("http://127.0.0.1:8107", "POWERSUPPLY"),
    ("http://127.0.0.1:8108", "GAMRY"),
    ("http://127.0.0.1:8109", "BIOLOGIC"),
    ("http://127.0.0.1:8110", "SPEC"),
]

#: A composition present in the simulator's stored dataset for plate 2750.
COMP_VEC = [0, 10, 0, 0, 10, 0, 0, 0, 20, 0, 0, 60, 0]


def start_actions(problems) -> None:
    """Start a simulated CP on each ws_data server."""
    body = json.dumps({"comp_vec": COMP_VEC, "acquisition_rate": 0.2}).encode()
    for base, key in ACTION_SERVERS:
        request = urllib.request.Request(
            f"{base}/{key}/measure_cp",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                if response.status != 200:
                    problems.append(f"{key}: measure_cp returned {response.status}")
        except urllib.error.URLError as exc:
            problems.append(f"{key}: measure_cp failed ({exc})")


def check_action_page(page, problems) -> None:
    """Assert the ws_data panels rendered and offer their cell selector.

    The NI-DAQmx panel draws four figures and a per-cell selector. An empty
    selector means the cell columns were never discovered from the stream,
    which renders as four blank charts and no error -- exactly the kind of
    failure a unit suite cannot see.
    """
    start_actions(problems)
    page.goto(f"{BASE}/action", wait_until="load", timeout=60000)
    page.wait_for_timeout(SETTLE_MS)
    body = page.inner_text("body")
    for heading in EXPECTED_ACTION_PANELS:
        if heading not in body:
            problems.append(f"action panel '{heading}' did not render")
    # Four for NI-DAQmx, one for the power supply, two each for the two
    # potentiostats (this action + previous action).
    canvases = page.locator("canvas").count()
    if canvases < 10:
        problems.append(f"{canvases} canvases on /action, expected at least 10")
    # The sample panel draws no chart; its tables are the evidence it rendered.
    if "Newest solid samples:" not in body:
        problems.append("the sample tables did not render")
    # The potentiostat panels pick their axes from the technique. Seeing the
    # column names in their selectors proves the action name reached the panel
    # through the ingest row store, which is the part that had to be added.
    if "Ewe_V" not in body:
        problems.append("the potentiostat axis selectors are empty")
    if "voltage (previous action)" not in body:
        problems.append("the previous-action figures did not render")
    checkboxes = page.get_by_role("checkbox").count()
    if checkboxes == 0:
        problems.append("the cell selector offered no cells")
    # The selector is populated from column names discovered in the stream, so
    # a cell being offered at all proves ws_data packets arrived and were
    # decoded -- which no unit test can show.
    #
    # Assert on the *voltage of the running action* specifically. Three of the
    # four figures are legitimately empty here: both previous-action figures
    # (there is no previous action on a first run) and the current figure (the
    # simulator's stored trace carries no current column). Requiring every
    # chart to have data would fail on correct behaviour.
    voltage_charts = [
        line
        for line in body.splitlines()
        if "data series" in line and "Ecell (V)" in line
    ]
    if not voltage_charts:
        problems.append("no voltage chart rendered a description")
    elif all(
        line.strip().startswith("Interactive chart. 0 data series")
        for line in voltage_charts
    ):
        problems.append("every voltage chart is empty: no ws_data reached the panel")


def main() -> int:
    """Load /live and /action, asserting every panel rendered and is updating."""
    problems = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)[:300]))
        page.on(
            "console",
            lambda m: errors.append(m.text[:200]) if m.type == "error" else None,
        )

        page.goto(f"{BASE}/live", wait_until="load", timeout=60000)
        page.wait_for_timeout(SETTLE_MS)

        body = page.inner_text("body")
        for heading in EXPECTED_PANELS:
            if heading not in body:
                problems.append(f"panel '{heading}' did not render")

        # A chart that never painted has no canvas. One per panel.
        canvases = page.locator("canvas").count()
        if canvases < len(EXPECTED_PANELS):
            problems.append(
                f"{canvases} canvases for {len(EXPECTED_PANELS)} panels: "
                "a chart did not paint"
            )

        for column in EXPECTED_MEAN_ROWS:
            if column not in body:
                problems.append(f"rolling mean '{column}' is missing")
        for column in UNEXPECTED_MEAN_ROWS:
            if column in body:
                problems.append(f"'{column}' was computed but should not be")

        # The panels must keep updating, not paint once and freeze -- the
        # defect that shipped past a green suite in the parent port.
        before = body
        page.wait_for_timeout(6000)
        if page.inner_text("body") == before:
            problems.append("the panels did not update between samples")

        check_action_page(page, problems)

        real_errors = [e for e in errors if "favicon" not in e]
        if real_errors:
            problems.append(f"browser errors: {real_errors[:3]}")

        browser.close()

    if problems:
        for problem in problems:
            print(f"FAIL: {problem}")
        return 1
    total = len(EXPECTED_PANELS) + len(EXPECTED_ACTION_PANELS)
    print(f"PASS: {total} hte panels rendered, painted and updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
