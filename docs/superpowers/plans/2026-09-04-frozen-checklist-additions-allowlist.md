# Frozen Checklist Additions Allowlist Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a deliberately added route pass the frozen hte route-checklist gate via a named allowlist entry, while removals and signature changes keep failing unconditionally.

**Architecture:** A pure helper in shared `harness/endpoints.py` splits a diff list into failing and allowed, keyed on the `extra` kind only. `helao/hexagon/tests/checklists/hte/_additions.json` holds the entries. `test_hte_route_checklist.py` routes its diffs through the helper and computes its pinned totals instead of carrying a literal. A new staleness test fails on an entry naming a route that no longer exists.

**Tech Stack:** Python 3.14, pytest, stdlib `json`/`pathlib`/`ast`. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-04-frozen-checklist-additions-allowlist-design.md`

## Global Constraints

- Run every Python command inside the `helao` conda env: `conda run -n helao python ...`. The OS python is not 3.14 and is not configured.
- `PYTHONPATH` must point at the repo root. The conda env config already sets this.
- **No existing `helao/hexagon/tests/checklists/hte/*.json` frozen record may be modified.** Verify with `git status` before every commit in this plan; only `_additions.json` is new.
- **Never run `harness/hte_freeze.py`.** It rewrites the frozen directory from current source and would destroy the pre-port record.
- `missing` and `changed` diffs must fail unconditionally. There is no allowlist for them.
- Run `black` on changed Python files immediately before `git add`, inside the `helao` env. Line length 88, default settings.
- Work on branch `feat/andor-driver-split`, already created.
- Do not push. Do not merge. Commits stay local.

---

### Task 1: The `filter_allowed_additions` helper

The pure function every other task builds on. It lives in `harness/` rather than in the hte test because a private deployment carries a near-identical gate that should later call the same function instead of reimplementing the rule.

**Files:**
- Modify: `harness/endpoints.py` (append after `diff_route_sets`, which ends at line 222)
- Test: `helao/hexagon/tests/test_checklist_additions.py` (create)

**Interfaces:**
- Consumes: `diff_route_sets(frozen, current) -> list[dict]` from `harness/endpoints.py:177`. Its diffs are dicts with keys `path`, `method`, `kind` (one of `"missing"`, `"extra"`, `"changed"`), and for `changed` also `field`, `frozen`, `current`.
- Produces: `filter_allowed_additions(diffs: list[dict], additions: list[dict]) -> tuple[list[dict], list[dict]]` returning `(failing, allowed)`. An addition entry is a dict with at least `path` and `method`; entries may carry `module`, `date`, `why`, which this function ignores.

- [ ] **Step 1: Write the failing tests**

Create `helao/hexagon/tests/test_checklist_additions.py`:

```python
"""`filter_allowed_additions` is asymmetric in exactly the way the risk is.

An `extra` route cannot break a client that relied on the frozen surface --
nobody knew it existed. A `missing` or `changed` route can. The frozen
checklist gate treats all three identically today, which is why a purely
additive change is as hard to land as a breaking one.

The tests that matter here are the two that pin a LISTED `missing` and a
LISTED `changed` still failing. They are the difference between an
asymmetric gate and a bypass.
"""

from harness.endpoints import filter_allowed_additions

EXTRA = {"path": "/ANDOR/calibrate_wl", "method": "post", "kind": "extra"}
MISSING = {"path": "/ANDOR/adjust_nd", "method": "post", "kind": "missing"}
CHANGED = {
    "path": "/ANDOR/acquire",
    "method": "post",
    "kind": "changed",
    "field": "params",
    "frozen": [],
    "current": [{"name": "x", "annotation": "int", "default": "1"}],
}
LISTS_CALIBRATE = [
    {
        "module": "andor_server.py",
        "path": "/ANDOR/calibrate_wl",
        "method": "post",
        "date": "2026-09-04",
        "why": "lamp wavelength calibration",
    }
]


def test_an_empty_allowlist_changes_nothing():
    failing, allowed = filter_allowed_additions([EXTRA, MISSING], [])
    assert failing == [EXTRA, MISSING]
    assert allowed == []


def test_a_listed_extra_is_allowed():
    failing, allowed = filter_allowed_additions([EXTRA], LISTS_CALIBRATE)
    assert failing == []
    assert allowed == [EXTRA]


def test_an_unlisted_extra_still_fails():
    other = {"path": "/ANDOR/something_else", "method": "post", "kind": "extra"}
    failing, allowed = filter_allowed_additions([other], LISTS_CALIBRATE)
    assert failing == [other]
    assert allowed == []


def test_a_listed_missing_still_fails():
    """An entry must not launder a removal into an addition."""
    listed = [{"path": MISSING["path"], "method": MISSING["method"]}]
    failing, allowed = filter_allowed_additions([MISSING], listed)
    assert failing == [MISSING]
    assert allowed == []


def test_a_listed_changed_still_fails():
    listed = [{"path": CHANGED["path"], "method": CHANGED["method"]}]
    failing, allowed = filter_allowed_additions([CHANGED], listed)
    assert failing == [CHANGED]
    assert allowed == []


def test_method_is_part_of_the_key():
    """A listed POST must not authorize a GET at the same path."""
    get_extra = {"path": "/ANDOR/calibrate_wl", "method": "get", "kind": "extra"}
    failing, allowed = filter_allowed_additions([get_extra], LISTS_CALIBRATE)
    assert failing == [get_extra]
    assert allowed == []


def test_mixed_diffs_split_cleanly():
    failing, allowed = filter_allowed_additions(
        [EXTRA, MISSING, CHANGED], LISTS_CALIBRATE
    )
    assert failing == [MISSING, CHANGED]
    assert allowed == [EXTRA]


def test_the_input_list_is_not_mutated():
    diffs = [EXTRA, MISSING]
    before = list(diffs)
    filter_allowed_additions(diffs, LISTS_CALIBRATE)
    assert diffs == before
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_checklist_additions.py -v`

Expected: all 8 fail at collection with `ImportError: cannot import name 'filter_allowed_additions' from 'harness.endpoints'`.

- [ ] **Step 3: Write the implementation**

Append to `harness/endpoints.py`, immediately after `diff_route_sets` (which ends at line 222) and before `def main`:

```python
def filter_allowed_additions(
    diffs: list[dict],
    additions: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Split checklist diffs into ``(failing, allowed)``.

    An ``extra`` diff whose ``(path, method)`` appears in ``additions`` is
    allowed: a route the frozen record never described cannot have been
    depended on by a client that read it. Every ``missing`` and ``changed``
    diff fails regardless of what is listed -- those break a caller, and a
    JSON entry must never be able to launder one into the other.

    ``additions`` entries need only ``path`` and ``method``; the ``module``,
    ``date`` and ``why`` fields carried for the reader are ignored here.
    """
    listed = {(a["path"], a["method"]) for a in additions}
    failing: list[dict] = []
    allowed: list[dict] = []
    for d in diffs:
        if d["kind"] == "extra" and (d["path"], d["method"]) in listed:
            allowed.append(d)
        else:
            failing.append(d)
    return failing, allowed
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_checklist_additions.py -v`

Expected: 8 passed.

- [ ] **Step 5: Confirm no frozen record moved, format, and commit**

```bash
git status --short
# must show ONLY: M harness/endpoints.py, ?? helao/hexagon/tests/test_checklist_additions.py
conda run -n helao black harness/endpoints.py helao/hexagon/tests/test_checklist_additions.py
git add harness/endpoints.py helao/hexagon/tests/test_checklist_additions.py
git commit -m "feat(harness): split checklist diffs into failing and allowed additions

diff_route_sets already separates missing/changed from extra, but the
gate treats all three the same. An extra route cannot break a client
that read the frozen surface; a missing or changed one can. This is the
helper that makes the gate as asymmetric as the risk, with the listed-
missing and listed-changed cases pinned so an entry can never launder a
removal into an addition."
```

---

### Task 2: The `_additions.json` record and the wired gate

Introduces the file (empty) and routes the existing gate through the helper. Empty means the gate's behaviour is provably unchanged at this point — that is the property Step 4 checks.

**Files:**
- Create: `helao/hexagon/tests/checklists/hte/_additions.json`
- Modify: `helao/hexagon/tests/test_hte_route_checklist.py:43-88` (the whole test body below the docstring)

**Interfaces:**
- Consumes: `filter_allowed_additions` from Task 1. `OUT`, `SERVERS`, `HTE_ACTION` from `harness/hte_freeze.py:14-18` — `OUT` is `Path("helao/hexagon/tests/checklists/hte")`, `SERVERS` is a `list[tuple[str, str | None]]` of `(module filename, server_key)`.
- Produces: module-level `ADDITIONS: list[dict]` and `_additions_for(module: str) -> list[dict]` in `test_hte_route_checklist.py`, both used by Task 3's staleness test.

- [ ] **Step 1: Create the empty record**

Create `helao/hexagon/tests/checklists/hte/_additions.json` with exactly:

```json
[]
```

The leading underscore matches `_collisions.json` and `_baseapi_system_surface.json` already in that directory, so it does not read as a per-module frozen record.

- [ ] **Step 2: Write the failing test**

Add to `helao/hexagon/tests/test_hte_route_checklist.py`, after the existing imports:

```python
from harness.endpoints import diff_route_sets, extract_routes, filter_allowed_additions

ADDITIONS_PATH = OUT / "_additions.json"

#: Action/private route totals measured from the frozen JSONs at B5. The
#: spec first quoted 175/81 from a grep over source, which counted seven
#: commented-out decorators and two docstring mentions; the AST extractor
#: ignores both. These are the measured numbers, and deliberate additions
#: are added to them rather than folded into them.
FROZEN_ACTION_TOTAL = 168
FROZEN_PRIVATE_TOTAL = 79


def _load_additions() -> list[dict]:
    return json.loads(ADDITIONS_PATH.read_text())


def _additions_for(module: str) -> list[dict]:
    return [a for a in _load_additions() if a["module"] == module]
```

Then add this test, which fails until `_additions.json` exists and every entry is well formed:

```python
def test_every_addition_entry_is_well_formed() -> None:
    """An entry without `why` is a bypass nobody can review in a diff."""
    for entry in _load_additions():
        missing = {"module", "path", "method", "date", "why"} - set(entry)
        assert not missing, f"{entry} is missing {sorted(missing)}"
        assert entry["why"].strip(), f"{entry['path']} has an empty `why`"
        assert entry["module"] in {
            m for m, _ in SERVERS
        }, f"{entry['module']} is not an hte action module"
```

- [ ] **Step 3: Run it to verify it passes on the empty file**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_hte_route_checklist.py::test_every_addition_entry_is_well_formed -v`

Expected: PASS, vacuously — the list is empty. This test only earns its keep once Task 4 of the Andor plan adds an entry, but it must exist before that entry does.

- [ ] **Step 4: Wire the helper into the two existing tests**

Replace the body of `test_module_matches_its_frozen_checklist` (currently at `:50-62`) with:

```python
@pytest.mark.parametrize("module,server_key", SERVERS, ids=[m for m, _ in SERVERS])
def test_module_matches_its_frozen_checklist(
    module: str, server_key: Optional[str]
) -> None:
    checklist = OUT / (Path(module).stem + ".json")
    frozen = json.loads(checklist.read_text())
    current = extract_routes(HTE_ACTION / module, server_key=server_key)
    diffs, _allowed = filter_allowed_additions(
        diff_route_sets(frozen, current), _additions_for(module)
    )
    assert (
        diffs == []
    ), f"{module}: {len(diffs)} route diff(s) against {checklist.name}\n" + json.dumps(
        diffs, indent=2
    )
```

Replace `test_the_gate_covers_the_whole_measured_surface` (currently at `:65-88`)
entirely with the version below. Its docstring keeps the existing text verbatim —
that paragraph records where 168 and 79 came from and why the first grep-derived
numbers were wrong — plus one new paragraph on why the literal is gone.

The frozen JSONs do **not** contain added routes, so `action` stays at 168 forever
and the additions are counted separately. Two assertions, not one sum: a single
combined number would hide which side moved.

```python
def test_the_gate_covers_the_whole_measured_surface() -> None:
    """Pin the totals, so a module silently dropped from SERVERS is caught.

    168 and 79 are counted from the frozen JSONs. B5's spec first quoted 175
    and 81, from a grep for ``tags=["action"]`` over the source -- which counts
    seven commented-out decorators (``# @app.post(...)`` in diapump, nidaqmx,
    pal and mfc) and two mentions in ``sample_server``'s module docstring. The
    AST extractor ignores both, correctly. The grep number was wrong and this
    test failed on its first run against the untouched tree, which is what a
    gate seeded before the work is for.

    The frozen counts are asserted separately from the deliberate additions.
    Editing a combined literal to make a diff pass is a re-freeze with extra
    steps: it leaves no record of what moved, and it cannot distinguish an
    intended addition from an accidental deletion that happens to net out.
    """
    action = private = 0
    for module, _ in SERVERS:
        for route in json.loads((OUT / (Path(module).stem + ".json")).read_text()):
            if "action" in route["tags"]:
                action += 1
            elif "private" in route["tags"]:
                private += 1
    assert (action, private) == (
        FROZEN_ACTION_TOTAL,
        FROZEN_PRIVATE_TOTAL,
    ), f"frozen record measures {action} action / {private} private"

    by_module = dict(SERVERS)
    resolved = 0
    for entry in _load_additions():
        current = extract_routes(
            HTE_ACTION / entry["module"], server_key=by_module[entry["module"]]
        )
        for route in current:
            if (route["path"], route["method"]) == (entry["path"], entry["method"]):
                resolved += 1
    assert resolved == len(
        _load_additions()
    ), f"{len(_load_additions()) - resolved} listed addition(s) resolve to no route"
```

- [ ] **Step 5: Run the full checklist gate to verify it is unchanged**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_hte_route_checklist.py -v`

Expected: every previously-passing case still passes, plus `test_every_addition_entry_is_well_formed`. With an empty `_additions.json` the helper is a no-op, so a failure here means the wiring changed behaviour and must be fixed before continuing.

- [ ] **Step 6: Confirm no frozen record moved, format, and commit**

```bash
git status --short
# must show ONLY: M helao/hexagon/tests/test_hte_route_checklist.py
#                 ?? helao/hexagon/tests/checklists/hte/_additions.json
git diff --stat helao/hexagon/tests/checklists/hte/
# must be empty: no frozen *.json record changed
conda run -n helao black helao/hexagon/tests/test_hte_route_checklist.py
git add helao/hexagon/tests/test_hte_route_checklist.py \
        helao/hexagon/tests/checklists/hte/_additions.json
git commit -m "feat(tests): route the hte checklist gate through the additions allowlist

_additions.json starts empty, so the helper is a no-op and the gate's
behaviour is provably unchanged by this commit. The pinned (168, 79)
literal becomes two separate assertions -- the frozen record's own count,
which never moves, and a check that every listed addition resolves in
source -- so a future diff shows which side changed instead of one
number that hides it."
```

---

### Task 3: The staleness guard

An allowlist nobody prunes becomes a permanent hole, and the hole is invisible precisely because the test is green. This is the test that keeps the mechanism honest.

**Files:**
- Modify: `helao/hexagon/tests/test_hte_route_checklist.py` (append)

**Interfaces:**
- Consumes: `_load_additions()`, `SERVERS`, `HTE_ACTION`, `extract_routes` from Task 2.
- Produces: nothing consumed downstream.

- [ ] **Step 1: Write the failing test**

Append to `helao/hexagon/tests/test_hte_route_checklist.py`:

```python
def test_no_addition_entry_is_stale() -> None:
    """An entry naming a route that is gone pre-authorizes a future one.

    A listed route that is later renamed or deleted leaves an entry that
    silently allows any future route appearing at the same path and method.
    Nothing else would catch that: the gate would be green, and the hole
    would be invisible because it is green.
    """
    by_module = dict(SERVERS)
    for entry in _load_additions():
        current = extract_routes(
            HTE_ACTION / entry["module"], server_key=by_module[entry["module"]]
        )
        present = {(r["path"], r["method"]) for r in current}
        assert (entry["path"], entry["method"]) in present, (
            f"{entry['path']} ({entry['method']}) is listed in _additions.json "
            f"but no longer exists in {entry['module']}; remove the entry"
        )
```

- [ ] **Step 2: Run it against the empty file**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_hte_route_checklist.py::test_no_addition_entry_is_stale -v`

Expected: PASS, vacuously.

- [ ] **Step 3: Prove it goes red**

A vacuous pass is not evidence. Temporarily put a bogus entry in `helao/hexagon/tests/checklists/hte/_additions.json`:

```json
[
  {
    "module": "andor_server.py",
    "path": "/ANDOR/no_such_route",
    "method": "post",
    "date": "2026-09-04",
    "why": "temporary staleness check, reverted in this same step"
  }
]
```

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_hte_route_checklist.py::test_no_addition_entry_is_stale -v`

Expected: FAIL with `/ANDOR/no_such_route (post) is listed in _additions.json but no longer exists in andor_server.py; remove the entry`.

Also run the whole file: `conda run -n helao python -m pytest helao/hexagon/tests/test_hte_route_checklist.py -v`. Expected: `test_no_addition_entry_is_stale` fails, and `test_module_matches_its_frozen_checklist[andor_server.py]` still **passes** — a bogus entry allows a diff that never appears, so it does not break the main gate. That is exactly why the staleness test is needed.

- [ ] **Step 4: Revert the bogus entry**

```bash
git checkout -- helao/hexagon/tests/checklists/hte/_additions.json
conda run -n helao python -m pytest helao/hexagon/tests/test_hte_route_checklist.py -v
```

Expected: all pass, and `_additions.json` is back to `[]`.

- [ ] **Step 5: Format and commit**

```bash
git status --short
# must show ONLY: M helao/hexagon/tests/test_hte_route_checklist.py
conda run -n helao black helao/hexagon/tests/test_hte_route_checklist.py
git add helao/hexagon/tests/test_hte_route_checklist.py
git commit -m "test: fail on a stale additions entry

An entry naming a route that no longer exists silently pre-authorizes
any future route at the same path and method, and the main gate stays
green while it does -- verified by watching the bogus-entry case fail
this test while test_module_matches_its_frozen_checklist still passed."
```

---

### Task 4: Whole-gate regression and the private-deployment note

The helper changed shared `harness/` code. Everything reading it must still pass, including the deployment gates outside `helao/hexagon/tests/`.

**Files:**
- Modify: `docs/superpowers/specs/2026-09-04-frozen-checklist-additions-allowlist-design.md` (append one line under Scope)

**Interfaces:**
- Consumes: everything from Tasks 1-3.
- Produces: nothing.

- [ ] **Step 1: Run every test that imports `harness.endpoints`**

```bash
conda run -n helao python -m pytest \
  helao/hexagon/tests/test_hte_route_checklist.py \
  helao/hexagon/tests/test_checklist_additions.py \
  helao/hexagon/tests/test_orch_host_surface.py \
  helao/hexagon/tests/test_action_host_surface.py -v
```

Expected: all pass. `test_orch_host_surface.py:117` reads `tests/checklists/orch_openapi_legacy.json` and is the other in-repo consumer of this machinery.

- [ ] **Step 2: Run the pre-launch unit gate**

Run: `conda run -n helao python run_unit_tests.py`

Expected: exit 0. `launch.py` runs this before launching anything and aborts on failure, so a break here breaks every station launch.

- [ ] **Step 3: Confirm the frozen records are untouched across the whole branch**

```bash
git diff --stat unstable...HEAD -- helao/hexagon/tests/checklists/hte/
```

Expected: only `_additions.json` appears, as an addition. If any `*_server.json` or `galil_*.json` shows up, a frozen record moved and the change must be undone — that record is the pre-port evidence and cannot be regenerated.

- [ ] **Step 4: Record the private-deployment follow-up**

Append to the Scope section of `docs/superpowers/specs/2026-09-04-frozen-checklist-additions-allowlist-design.md`:

```markdown
Implemented 2026-09-04. `filter_allowed_additions` is in `harness/endpoints.py`
and is called only by `test_hte_route_checklist.py`. The private deployment's
twin gate is unchanged and still fails on any `extra` diff; adopting the helper
there is a one-line change in that repository when it next needs it.
```

- [ ] **Step 5: Commit**

```bash
conda run -n helao black harness/endpoints.py
git add docs/superpowers/specs/2026-09-04-frozen-checklist-additions-allowlist-design.md
git commit -m "docs: record the allowlist as implemented and the twin-gate follow-up"
```

---

## Done when

- `conda run -n helao python -m pytest helao/hexagon/tests/test_hte_route_checklist.py helao/hexagon/tests/test_checklist_additions.py -v` passes.
- `conda run -n helao python run_unit_tests.py` exits 0.
- `git diff --stat unstable...HEAD -- helao/hexagon/tests/checklists/hte/` shows `_additions.json` and nothing else.
- `_additions.json` contains `[]`. The Andor plan adds the first real entry.
