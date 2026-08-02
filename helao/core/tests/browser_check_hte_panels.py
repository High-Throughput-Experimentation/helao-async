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

import sys

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
EXPECTED_ACTION_PANELS = ["Cells:", "Power supply:"]


def check_action_page(page, problems) -> None:
    """Assert the ws_data panels rendered and offer their cell selector.

    The NI-DAQmx panel draws four figures and a per-cell selector. An empty
    selector means the cell columns were never discovered from the stream,
    which renders as four blank charts and no error -- exactly the kind of
    failure a unit suite cannot see.
    """
    page.goto(f"{BASE}/action", wait_until="load", timeout=60000)
    page.wait_for_timeout(SETTLE_MS)
    body = page.inner_text("body")
    for heading in EXPECTED_ACTION_PANELS:
        if heading not in body:
            problems.append(f"action panel '{heading}' did not render")
    # Four figures for NI-DAQmx plus one for the power supply.
    canvases = page.locator("canvas").count()
    if canvases < 5:
        problems.append(f"{canvases} canvases on /action, expected at least 5")
    if "voltage (previous action)" not in body:
        problems.append("the previous-action figures did not render")
    checkboxes = page.get_by_role("checkbox").count()
    if checkboxes == 0:
        problems.append("the cell selector offered no cells")


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
