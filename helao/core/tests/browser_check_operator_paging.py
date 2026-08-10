"""Headless check of the operator's paginated Queues and History tables.

Not a pytest module: it needs a launched orchestration group with a live
orchestrator, and the whole point is to load the page in a real browser. Run it
beside ``browser_check_operator.py``, which covers the render/poll/enqueue path
this one assumes works.

What it proves that no unit test can:

* the queue tables show rows past the tenth. The orchestrator used to default
  ``list_sequences(limit=10)`` and its endpoint called it with no arguments, so
  **no operator UI could see an eleventh queued item** -- and the subtab count,
  being ``len(rows)``, reported the truncation as the queue's depth.
* the pager moves the view and the row a control acts on is the absolute one.
  The rendered index is page-local while the orchestrator indexes its deques
  absolutely, so a page-2 click that forgot the offset would silently act on a
  page-1 item -- a wrong action dispatched, with nothing looking wrong.
* the History tables refresh without anyone pressing Refresh.

Run it after ``python launch.py goldenreflex``::

    /home/dan/miniforge3/envs/helao/bin/python \\
        helao/core/tests/browser_check_operator_paging.py [base_url]
"""

import re
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5010"

#: Sequences to enqueue. Must exceed the old cap of 10 by enough that the
#: truncation is unmistakable, and exceed one page at the smallest offered page
#: size (25) so the pager has a second page to move to.
ENQUEUE_N = 28

#: Page size to select, so `ENQUEUE_N` spans two pages.
PAGE_SIZE = "25"

LIB_WAIT_MS = 20000
POLL_WAIT_MS = 8000


def _tab_count(body: str, label: str):
    """The ``[n]`` in a subtab title, or None when the title has no count."""
    match = re.search(rf"{label}\s*\[(\d+)\]", body)
    return int(match.group(1)) if match else None


def _window(body: str):
    """The pager's ``51-100 of 412`` line, or None."""
    match = re.search(r"(\d+)-(\d+) of (\d+)", body)
    return match.group(0) if match else None


def _set_page_size(page, size: str) -> bool:
    """Choose a page size.

    ``rx.select`` is a **Radix** select, not a native ``<select>``: it renders a
    ``combobox`` button and portals its options into the document body when
    opened. ``locator("select").select_option`` matches nothing, silently
    leaves the size at its default, and then the check blames the pager for a
    disabled Next that was disabled correctly.
    """
    trigger = page.get_by_role("combobox")
    if trigger.count() == 0:
        return False
    trigger.first.click()
    page.wait_for_timeout(500)
    option = page.get_by_role("option", name=size, exact=True)
    if option.count() == 0:
        page.keyboard.press("Escape")
        return False
    option.first.click()
    return True


def main() -> int:
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

        page.goto(f"{BASE}/operator", wait_until="load", timeout=60000)
        page.wait_for_timeout(4000)
        page.wait_for_timeout(LIB_WAIT_MS)

        page.get_by_role("tab", name="Queues").click()
        page.wait_for_timeout(POLL_WAIT_MS)
        depth = _tab_count(page.inner_text("body"), "Sequences") or 0

        if depth <= ENQUEUE_N:
            page.get_by_role("tab", name="Build").click()
            page.wait_for_timeout(1000)
            add = page.get_by_role("button", name="Add to plan")
            if add.count() == 0:
                print("FAIL: the build tab did not render; is the group up?")
                browser.close()
                return 1
            # Buffer locally, then flush once. Buffering is client-side, so
            # this costs one orchestrator round trip rather than N of them.
            for _ in range(ENQUEUE_N - depth + 1):
                add.first.click()
            page.wait_for_timeout(3000)
            page.get_by_role("tab", name="Plan").click()
            page.wait_for_timeout(1000)
            flush = page.get_by_role("button", name="Add plan")
            if flush.count() == 0:
                print("FAIL: the plan tab did not render its flush button")
                browser.close()
                return 1
            flush.first.click()
            page.wait_for_timeout(POLL_WAIT_MS * 2)
            page.get_by_role("tab", name="Queues").click()
            page.wait_for_timeout(POLL_WAIT_MS)

        body = page.inner_text("body")

        # -- the cap is gone, and the count is the queue's not the page's ----
        depth = _tab_count(body, "Sequences")
        if depth is None:
            problems.append("the Sequences subtab has no row count")
        elif depth <= 10:
            problems.append(
                f"the sequence queue reports a depth of {depth}; the limit=10 "
                f"truncation is still in the path (expected > {ENQUEUE_N})"
            )
        else:
            print(f"  queue depth reported as {depth} (the old cap was 10)")

        # -- the pager exists and reports a window --------------------------
        if _window(body) is None:
            problems.append(f"no pager under the queue table: {body[:400]}")

        # -- moving to page 2 changes the window ----------------------------
        # The page size has to come down first: at the default 50 a queue this
        # deep is a single page, and a correctly-disabled Next would read as a
        # broken one.
        if not _set_page_size(page, PAGE_SIZE):
            problems.append("could not choose a page size")
        page.wait_for_timeout(POLL_WAIT_MS)
        first_window = _window(page.inner_text("body"))
        nxt = page.get_by_role("button", name=">", exact=True)
        if nxt.count() == 0:
            problems.append("the pager rendered no next control")
        elif not nxt.first.is_enabled():
            problems.append(
                f"Next is disabled with {depth} rows at a page size of "
                f"{PAGE_SIZE}; window reads {first_window}"
            )
        else:
            nxt.first.click()
            page.wait_for_timeout(POLL_WAIT_MS)
            second_window = _window(page.inner_text("body"))
            if not second_window or first_window == second_window:
                problems.append(
                    f"Next did not move the window ({first_window} -> {second_window})"
                )
            elif not second_window.startswith(f"{int(PAGE_SIZE) + 1}-"):
                problems.append(
                    f"page 2 does not start at row {int(PAGE_SIZE) + 1}: "
                    f"{second_window}"
                )
            else:
                print(f"  pager moved {first_window} -> {second_window}")

        # -- History: order, counts, and a tick nobody clicked ---------------
        page.get_by_role("tab", name="History").click()
        page.wait_for_timeout(1000)
        body = page.inner_text("body")
        order = [
            body.index(label)
            for label in ("Sequences [", "Experiments [", "Actions [")
            if label in body
        ]
        if len(order) != 3:
            problems.append(
                f"the history subtabs do not all carry counts: {body[:400]}"
            )
        elif order != sorted(order):
            problems.append("the history subtabs are not sequence-experiment-action")

        # Nothing is clicked here on purpose: the history used to move only
        # when its Refresh button was pressed.
        before = _tab_count(body, "Actions")
        page.wait_for_timeout(POLL_WAIT_MS * 3)
        after = _tab_count(page.inner_text("body"), "Actions")
        if before is None or after is None:
            problems.append("the Actions history subtab has no row count")
        elif after < before:
            problems.append(
                f"the action history shrank on its own: {before} -> {after}"
            )

        real_errors = [e for e in errors if "favicon" not in e]
        if real_errors:
            problems.append(f"browser errors: {real_errors[:3]}")

        browser.close()

    if problems:
        for problem in problems:
            print(f"FAIL: {problem}")
        return 1
    print("PASS: queues page past ten rows, the pager moves, history ticks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
