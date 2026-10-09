"""Headless check of the Reflex /retire page against a running group.

Not a pytest module: it needs a launched orchestration group and a real
browser, because the unit suite cannot execute a Reflex event handler.

The run tree is built from a freshly generated uuid that exists in no metadata
API, so Gather issues only GETs (which 404) and Retire issues **zero** API
deletes, while the whole UI path still runs through the directory move. The
check enforces that assumption: before typing the confirm text or clicking
Retire (after the first gather and after the re-gather) it refuses unless the
label is CHECK-<first 8 of the uuid>, the SEQUENCE row has 2 local locations
and every "in API" cell is 0 or absent; any earlier failed step also stops it
before Retire. Of the progress bar only "reaches 100" is enforced.

Steps (from the repo root, in the ``helao`` env)::

    python helao/core/tests/browser_check_retire.py prepare <workdir>
    bash ./helao.sh <workdir>/retirecheck.yml   # noexec mount: via bash
    python helao/core/tests/browser_check_retire.py check \\
        http://127.0.0.1:5010 <uuid> <label>
    # then CTRL-x in the launcher

``check`` needs Playwright (and its chromium) installed in the Python that runs
it; it is not in the ``helao`` env, so use a venv with ``pip install playwright``.
"""

import os
import re
import sys
import time
import uuid

import yaml

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(TESTS_DIR)))
SOURCE_CONFIG = os.path.join(
    REPO, "helao", "deploy", "test", "configs", "goldenreflex.yml"
)

#: Seconds allowed for a gather to show its table, and for retire to finish.
GATHER_WAIT_MS = 30000
RETIRE_WAIT_S = 10


def prepare(workdir: str) -> int:
    """Build <workdir>/root with one uuid at two locations, and the config."""
    sys.path.insert(0, REPO)
    from helao.core.tests.retire_fakes import make_run_tree

    workdir = os.path.abspath(workdir)
    root = os.path.join(workdir, "root")
    seq_uuid = str(uuid.uuid4())
    label = f"CHECK-{seq_uuid[:8]}"
    exp_uuid, act_uuid, proc_uuid = (str(uuid.uuid4()) for _ in range(3))
    for run_tree in ("RUNS_SYNCED", "RUNS_FINISHED"):
        make_run_tree(
            root,
            run_tree,
            "26.41/1006/20261006.000000__retirecheck",
            sequence_uuid=seq_uuid,
            label=label,
            experiments={exp_uuid: [(act_uuid, proc_uuid)]},
        )
    with open(SOURCE_CONFIG, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["root"] = root
    cfg["servers"]["UI"]["params"]["retire"] = True
    cfg_path = os.path.join(workdir, "retirecheck.yml")
    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)
    print(f"uuid:  {seq_uuid}")
    print(f"label: {label}")
    print(f"launch: bash ./helao.sh {cfg_path}")
    print(
        f"check:  python helao/core/tests/browser_check_retire.py check "
        f"http://127.0.0.1:5010 {seq_uuid} {label}"
    )
    return 0


def retire_guard(
    seq_uuid: str, shown_label: str, label_arg: str, local: str, in_api: list[str]
) -> str:
    """Why Retire must not be clicked, or "" when the inventory is the fresh one.

    Enforces the fresh-uuid assumption: label is CHECK-<first 8 of uuid>, the
    sequence has 2 local locations, the table has exactly 5 in-API cells (one per
    entity row, so a changed layout fails closed), and none is in the API.
    """
    want = f"CHECK-{seq_uuid[:8]}"
    why = []
    if shown_label != want or label_arg != want:
        why.append(f"label {shown_label!r}/{label_arg!r}, expected {want!r}")
    if local != "2":
        why.append(f"SEQUENCE local count {local!r}, expected '2'")
    if len(in_api) != 5:
        why.append(f"{len(in_api)} in-API cells, expected exactly 5")
    if any(c not in ("0", "absent") for c in in_api):
        why.append("some entity is present in the API")
    return "; ".join(why)


def _selftest() -> None:
    u = "843efefc-0980-47ef-b5c2-89a8daa84c9c"
    ok = ["0", "0", "0", "0", "absent"]
    assert retire_guard(u, "CHECK-843efefc", "CHECK-843efefc", "2", ok) == ""
    assert retire_guard(u, "REAL-LABEL", "CHECK-843efefc", "2", ok)
    assert retire_guard(u, "CHECK-843efefc", "CHECK-843efefc", "3", ok)
    assert retire_guard(u, "CHECK-843efefc", "CHECK-843efefc", "2", ["0", "1"])
    assert retire_guard(u, "CHECK-843efefc", "CHECK-843efefc", "2", ["present"])
    assert retire_guard(u, "CHECK-843efefc", "CHECK-843efefc", "2", [])
    assert retire_guard(u, "CHECK-843efefc", "CHECK-843efefc", "2", ok[:4])
    assert retire_guard(u, "CHECK-843efefc", "CHECK-843efefc", "2", ok + ["0"])


def _run(base: str, seq_uuid: str, label: str, page, errors: list[str]) -> int:
    problems: list[str] = []
    uuid_box = page.get_by_placeholder("sequence uuid")
    confirm_box = page.get_by_placeholder("type the label")
    retire_btn = page.get_by_role("button", name="Retire", exact=True)

    def gather() -> None:
        uuid_box.fill(seq_uuid)
        page.get_by_role("button", name="Gather").click()
        page.locator("tr", has_text="SEQUENCE").first.wait_for(timeout=GATHER_WAIT_MS)

    def refuse() -> int:
        """Guard on the inventory now on screen; 1 (after printing) if unsafe."""
        row = page.locator("tr", has_text="SEQUENCE").first
        local = row.locator("td").nth(1).inner_text().strip()
        cells = [
            c.strip()
            for c in page.locator("tbody tr")
            .locator("td:nth-child(3)")
            .all_inner_texts()
        ]
        m = re.search(r"label:\s*(\S*)\s+campaign:", page.inner_text("body"))
        shown = m.group(1) if m else ""
        why = retire_guard(seq_uuid, shown, label, local, cells)
        if why:
            print(
                f"FAIL: refusing to retire ({why}); label={shown!r} "
                f"in-API cells={cells}"
            )
            return 1
        return 0

    page.goto(f"{base}/retire", wait_until="load", timeout=60000)
    try:
        uuid_box.wait_for(timeout=20000)
    except Exception:
        print("FAIL: the page did not render its controls")
        print(f"body: {page.inner_text('body')[:400]}")
        return 1

    # 1-2. gather; guard before anything is typed
    try:
        gather()
    except Exception:
        print(f"FAIL: no counts table: {page.inner_text('body')[:400]}")
        return 1
    if refuse():
        return 1

    # 3-4. Retire is gated on the typed label
    if not retire_btn.is_disabled():
        problems.append("Retire enabled before any confirm text")
    confirm_box.fill("wrong-text")
    page.wait_for_timeout(500)
    if not retire_btn.is_disabled():
        problems.append("Retire enabled with the wrong confirm text")
    confirm_box.fill(label)
    page.wait_for_timeout(500)
    if retire_btn.is_disabled():
        problems.append("Retire still disabled with the right label")

    # 5. editing the uuid disarms; re-gather
    uuid_box.press_sequentially("a")
    page.wait_for_timeout(500)
    uuid_box.press("Backspace")
    page.wait_for_timeout(500)
    if page.get_by_placeholder("type the label").count() and not (
        retire_btn.is_disabled()
    ):
        problems.append("Retire still enabled after editing the uuid")
    gather()

    # Fail closed: stop before the confirm text on any earlier problem or any
    # unsafe inventory (the one Retire would act on).
    if refuse():
        return 1
    if problems:
        for problem in problems:
            print(f"FAIL: {problem}")
        return 1
    confirm_box.fill(label)
    page.wait_for_timeout(500)

    # 6. retire; the bar must reach 100 (a partial value is only reported)
    retire_btn.click()
    seen_partial = reached = False
    deadline = time.time() + RETIRE_WAIT_S
    while time.time() < deadline and not reached:
        bar = page.get_by_role("progressbar")
        if bar.count():
            now = bar.first.get_attribute("aria-valuenow")
            if now is not None:
                seen_partial |= float(now) < 100
                reached = float(now) >= 100
        page.wait_for_timeout(50)
    print(f"info: partial progress (<100) observed: {seen_partial}")
    if not reached:
        problems.append("progress bar never reached 100")

    # 7. result panel
    page.wait_for_timeout(1500)
    lines = page.inner_text("body").splitlines()
    ledger_lines = [ln for ln in lines if ln.startswith("ledger:")]
    if not ledger_lines or not ledger_lines[0].strip().endswith(".jsonl"):
        problems.append(f"no .jsonl ledger path in result: {ledger_lines}")
    moved = [ln for ln in lines if "->" in ln and "RUNS_SUPERSEDED" in ln]
    if len(moved) != 2:
        problems.append(f"expected 2 moved lines, saw {len(moved)}: {moved}")

    # 8. console
    real_errors = [e for e in errors if "favicon" not in e]
    if real_errors:
        problems.append(f"browser errors: {real_errors[:3]}")

    if problems:
        for problem in problems:
            print(f"FAIL: {problem}")
        return 1
    print("PASS: gather, confirm gating, retire progress and moved paths")
    return 0


def check(base: str, seq_uuid: str, label: str) -> int:
    """Drive /retire through gather, confirm gating, retire, and the result."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)[:300]))
            page.on(
                "console",
                lambda m: errors.append(m.text[:200]) if m.type == "error" else None,
            )
            return _run(base, seq_uuid, label, page, errors)
        except Exception as exc:
            print(f"FAIL: {exc!r}")
            return 1
        finally:
            browser.close()


if __name__ == "__main__":
    _selftest()
    argv = sys.argv[1:]
    if len(argv) == 2 and argv[0] == "prepare":
        sys.exit(prepare(argv[1]))
    if len(argv) == 4 and argv[0] == "check":
        sys.exit(check(*argv[1:]))
    print(__doc__)
    sys.exit(2)
