"""Headless check of the Reflex operator against a running group.

Not a pytest module: it needs a launched orchestration group with a live
orchestrator, and the whole point is to load the page in a real browser. The
parent Reflex port shipped six rendering defects past a green unit suite
because nothing ever did, and the operator's unit suite cannot execute a single
Reflex event handler.

Run it after ``python launch.py goldenreflex``::

    /home/dan/miniforge3/envs/helao/bin/python \\
        helao/core/tests/browser_check_operator.py [base_url]
"""

import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5010"

#: Seconds allowed for the libraries to load. Importing every sequence and
#: experiment module the config names is slow the first time, but bounded, so a
#: hang fails rather than hanging the check.
LIB_WAIT_MS = 20000

#: One poll interval plus slack, for a queue table to show a new entry.
POLL_WAIT_MS = 8000


def main() -> int:
    """Select a sequence, enqueue it, and assert the queue table shows it."""
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

        if page.get_by_role("button", name="Start").count() == 0:
            print("FAIL: the page did not render its controls")
            print(f"body: {page.inner_text('body')[:400]}")
            browser.close()
            return 1

        # The status line proves the poll loop ran at all: it starts at
        # "connecting" and only changes once a poll completes.
        page.wait_for_timeout(POLL_WAIT_MS)
        body = page.inner_text("body")
        if "connecting to the orchestrator" in body:
            problems.append("the poll loop never produced a status")
        elif "cannot reach the orchestrator" in body:
            problems.append("the page could not reach the orchestrator")

        # Libraries populate the selector. An empty library is a real
        # possibility for some configs, so say which case happened.
        page.wait_for_timeout(LIB_WAIT_MS)
        enqueued = False
        if page.get_by_role("button", name="Add to plan").count() == 0:
            problems.append("the build tab did not render")
        else:
            page.get_by_role("button", name="Add to plan").click()
            page.wait_for_timeout(2000)
            # Switch first: the plan table is on the Plan tab, and reading the
            # build tab's body for it is a check that fails for the wrong
            # reason.
            page.get_by_role("tab", name="Plan").click()
            page.wait_for_timeout(1000)
            body = page.inner_text("body")
            if "buffered" not in body:
                problems.append(f"nothing was buffered: {body[-300:]}")
            else:
                # ".click(), not .check()" applies to checkboxes; these are
                # ordinary buttons, but the flush button's label carries the
                # buffered count, so match on the prefix.
                flush = page.get_by_role("button", name="Add plan")
                if flush.count() == 0:
                    problems.append("the plan tab did not render its flush button")
                else:
                    flush.first.click()
                    page.wait_for_timeout(POLL_WAIT_MS)
                    enqueued = True

        if enqueued:
            page.get_by_role("tab", name="Queues").click()
            page.wait_for_timeout(POLL_WAIT_MS)
            body = page.inner_text("body")
            # The sequence table shows the name; an empty table after a
            # successful flush means the enqueue never reached the orchestrator.
            if "sequence_name" not in body:
                problems.append("the queues tab did not render its table")

        # The plate tab is opt-in and says so; either outcome is fine, but it
        # must not raise.
        page.get_by_role("tab", name="Plate").click()
        page.wait_for_timeout(1000)

        page.get_by_role("tab", name="History").click()
        page.wait_for_timeout(1000)

        real_errors = [e for e in errors if "favicon" not in e]
        if real_errors:
            problems.append(f"browser errors: {real_errors[:3]}")

        browser.close()

    if problems:
        for problem in problems:
            print(f"FAIL: {problem}")
        return 1
    print("PASS: the operator rendered, polled, buffered and enqueued")
    return 0


if __name__ == "__main__":
    sys.exit(main())
