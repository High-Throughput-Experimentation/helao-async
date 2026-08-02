"""Headless check of the Reflex data browser against a running group.

Not a pytest module: it needs a launched orchestration group, and the whole
point is to load the page in a real browser. The parent Reflex port shipped six
rendering defects past a green unit suite because nothing ever did.

Run it after ``python launch.py goldenreflex``::

    /home/dan/miniforge3/envs/helao/bin/python \\
        helao/core/tests/browser_check_data_browser.py [base_url]
"""

import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5010"

#: Seconds allowed for the scan. Generous, because it walks a run tree -- but
#: bounded, so a hang fails rather than hanging the check too.
SCAN_WAIT_MS = 20000


def main() -> int:
    """Scan, select a dataset, plot it, and assert the chart actually painted."""
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

        page.goto(f"{BASE}/browser", wait_until="load", timeout=60000)
        page.wait_for_timeout(4000)

        if page.get_by_role("button", name="Scan").count() == 0:
            print("FAIL: the page did not render its controls")
            browser.close()
            return 1

        page.get_by_role("button", name="Scan").click()
        page.wait_for_timeout(SCAN_WAIT_MS)
        body = page.inner_text("body")

        if "scan failed" in body:
            problems.append(f"scan reported failure: {body[:200]}")
        elif "indexed" not in body:
            problems.append("scan produced neither an index nor an error")

        # Tick the first row and plot it. A run tree with no datasets is a
        # legitimate outcome, so the plot assertions only apply if there is
        # something to plot -- but say so rather than passing silently.
        boxes = page.get_by_role("checkbox")
        plotted = False
        if boxes.count() > 0:
            # .click(), not .check(): Radix renders a <button role="checkbox">,
            # and Playwright's .check() waits on a state contract it does not
            # satisfy -- which fails while the page is working perfectly.
            boxes.first.click()
            page.get_by_role("button", name="Add to plot").click()
            page.wait_for_timeout(6000)
            body = page.inner_text("body")
            plotted = True
            # xy emits an accessibility summary; cheapest proof of a real paint.
            if "Interactive chart" not in body:
                problems.append("chart did not render after Add to plot")
            if page.locator("canvas").count() == 0:
                problems.append("no canvas element after Add to plot")
        else:
            print("NOTE: index was empty, so the plot path was not exercised")

        if errors:
            problems.append(f"page errors: {errors[:5]}")

        browser.close()

    if problems:
        print("FAIL: " + "; ".join(problems))
        return 1
    print("PASS" + (" (scan and plot)" if plotted else " (scan only)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
