# Catalog Bug Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix every code defect the 2026-11-18 output-catalog pass found, one root-cause fix and one falsifiable test per bug, and remove each fixed defect bullet from its owning README.

**Architecture:** Seven work units across six repos (parent, hte, Deployment-A/B/C/E), in the spec's order: hte mfc first (live), then the parent shared fixes that hte and Deployment-A rely on, then each nested repo. hte work runs in a fresh worktree of `origin/main` nested inside a detached parent worktree, so the shared hte clone (another session's branch) is never switched. Every task is test-first with a mutation check, and ends with a README catalog update and a local commit made by the main session.

**Tech Stack:** Python 3.14 (`helao` conda env), pytest, pydantic v2, numpy, FastAPI action hosts (`ActionHost`), `black`.

**Spec:** `docs/superpowers/specs/2026-11-18-catalog-bugfixes-design.md` (read it with this plan; it holds the reach, effects and decision numbers for each bug).

**Private names.** This file lives in the public parent repo. Private deployments appear only as `<Deployment-A>`, `<Deployment-B>`, `<Deployment-C>`, `<Deployment-E>`, `<Deployment-F>` (in paths, `helao/deploy/<Deployment-X>/...`). Executors resolve the aliases from the memory file `cards-deployment-aliases.md` (in the project's Claude memory directory) and never write the resolved names into the parent repo or into hte (public).

## Global Constraints

- Python: `PY=/home/dan/miniforge3/envs/helao/bin/python`; formatter `BLACK=/home/dan/miniforge3/envs/helao/bin/black`. Parent and Deployment-X tests run from `/mnt/STORAGE/repos/helao/helao-async` with `PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async`.
- hte: never switch the shared hte clone's branch (it is on another session's `fix/alicat-meter-status`), and never touch the Deployment-F clone. hte edits and tests happen only in `/tmp/claude-1000/wt-parent/helao/deploy/hte` (branch `fix/catalog-bugfixes` off hte `origin/main` f4e8a368), run as `cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent $PY -m pytest helao/deploy/hte/...`.
  - Why nested: `helao.deploy.hte` must resolve to the worktree. `helao/deploy` is a regular package (`helao/deploy/__init__.py`), so the only clean way is a parent checkout whose `helao/deploy/hte` *is* the hte worktree. A symlinked or out-of-tree worktree breaks pytest's rootdir/package detection (module name would start at `/tmp/claude-1000`). The parent `.gitignore` excludes `helao/deploy/*`, so the nested hte worktree is invisible to the parent worktree. The suggested `/tmp/claude-1000/wt-hte-fix` path was therefore replaced by `/tmp/claude-1000/wt-parent/helao/deploy/hte`.
  - The parent worktree is detached at `unstable`; after the parent tasks (2-5) commit, Task 6 Step 0 re-detaches it at the new `unstable` so hte tests see P1-P4.
- Every git command is `git -C <repo>`. Repos: parent `/mnt/STORAGE/repos/helao/helao-async` (`unstable`); hte `/tmp/claude-1000/wt-parent/helao/deploy/hte` (`fix/catalog-bugfixes`); Deployment-X `/mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-X>` (`main`). Before every commit check `branch --show-current` and `status --short`; stop and report if the branch is not the expected one.
- Subagents never `git add`/`commit`/`push`/`stash`, never `checkout`/`switch`, and never write outside the working tree or `/tmp/claude-1000`. Commit steps are marked "(main session)". Commits are local; no push without user approval (a push to a default branch is a deploy).
- Commit messages end with the attribution trailer the executing session's system reminder gives. hte and parent commit messages never name a private deployment.
- `black` on changed `.py` files immediately before each commit.
- Mutation checks revert only the fix lines (`git diff -- <src>` then `git apply -R`), run the new test, confirm red, re-apply. Never `git stash`.
- Deployment-C: tests are static or fully monkeypatched. Never execute a pre-fix CLI or a converter with production defaults (they point at `/mnt/wd4`). The xafs inventory (Task 17 Step 8) is read-only over `ssh -o BatchMode=yes -i ~/.ssh/id_ed25519_note01 hte-note-01.caltech.edu '<cmd>'`, main session only, writes nothing.
- Never read or write `/mnt/wd4`, `/mnt/st2`, `/mnt/k`, `/mnt/j`, `/mnt/i` locally.
- Motion timeout (H3, A2): `RuntimeError`, never `TimeoutError` (the dispatcher treats `asyncio.TimeoutError` as an RPC transport failure, `helao/helpers/dispatcher.py:244`). Message format, identical in both drivers: `f"motion timeout: axes {axis} not stopped after {timeout} s"`. Busy flags/locks released before the raise. Deployment-A raises `MotionTimeoutError(RuntimeError)` so its `motor_move` wrapper's `except Exception` can re-raise it instead of returning `err_code: motor` (which E-STOPs); hte galil has no such wrapper and raises plain `RuntimeError`. Both match `pytest.raises(RuntimeError, match="motion timeout")`.
- `ErrorCodes` (P1): `__str__ = str.__str__`; existing rows stay as written; consumers accept both `"none"` and `"ErrorCodes.none"`.
- H5 trigger: SYNC `postfinish_hooks` `dispatch_analysis` in `eche10.yml`, ANA `port: 8014`, `local_only: true`; tags `spectrum.uvis_bkgsubnorm_ref` and `spectrum.echeuvis_stability`.
- Box notes crop name: `f"{stem}__{serial}__{sha256(png)[:12]}.png"`. Note dedupe prefix: `f"Box-notes scan {input_tif} (plate {serial},"`. No `force` flag.
- Robot arm: `robot_mode` double at byte offset 756, `qd_actual` 6 doubles at offset 300, `is_moving = max(abs(qd)) > eps`, eps default `1e-3` rad/s (config param).
- Each task ends by updating the owning README `## Outputs`/`## Notes` per the `helao-output-catalog` skill (remove the fixed-defect bullet, correct rows) and running that deployment's `tests/test_readme_outputs.py`.
- Spec "Delivery" asks one commit per repo per unit. This plan commits per task (local, finer-grained, easier to review and revert); squash per unit before push if the user prefers the spec's shape.

## Review Focus

Inputs the spec implies but its listed tests do not exercise, most likely first. Each line is pinned to a test in its owning task.

1. **mfc 2-field reply** (a controller answering with only pressure and setpoint-shaped fields): the next full 6-field reply must still give the real `setpoint` and `gas`, and `status_keys` stays pristine. Test: Task 1, `test_two_field_reply_does_not_rekey_later_replies`.
2. **`Mxy` as a real nested list or `None`** (the Action envelope can carry a list; the endpoint default is `None`): a list gives the same matrix as its JSON string, `None` raises `ValueError("Mxy required")` (500, pause and re-queue, no E-STOP). Tests: Task 3, `test_get_mplate_msystem_accepts_a_nested_list` and `test_get_mplate_msystem_none_raises_a_clear_error`.
3. **galil move whose every requested axis is unconfigured** (e.g. `["z"]` on an x-only station): the joint filter leaves nothing to move; no motion command, no raise, `motor_busy` released. Test: Task 7, `test_only_unconfigured_axes_sends_no_move_and_does_not_raise`.
4. **box_notes name collision** (a same-named tif already in `processing/` or back in `drop/`): the moved file gets `<stem>__1.tif`, still ends in `.tif`, and `discover_tifs` still finds it (a suffixed name then fails filename parsing and goes to `failed/`, never overwriting; see Task 21's escalation). Test: Task 21, `test_a_name_taken_in_processing_is_suffixed_and_still_discovered`.
5. **thorlabs move after a timeout raise**: the station check expects "the next move accepted"; the busy flag must be released so a following normal move returns `[none]`. Test: Task 29, `test_next_move_is_accepted_after_a_timeout_raise`.

## Escalations and notes for the executor

Read before starting; each is also written into its task.

- **Task 19 (Deployment-C):** the spec's `KNOWN_UNMIGRATED` entry for `servers/analysis/analyses/xrfs_local.py:235` is left out: the sweep in `tests/test_sources_root.py` covers only `scripts/`, and its ledger test resolves every key under `scripts/`, so the entry would fail it. Widening the sweep to `servers/` is a user decision; ask before doing it.
- **Task 21 (Deployment-C):** every colliding move now gets a `__n` suffix. A tif sent back to `drop/` as `<stem>__1.tif` fails `parse_box_note_filename` on the next pass and lands in `failed/`. Nothing is overwritten (today it is), but the operator must rename it to re-drop. Tell the user.
- **Task 29 (Deployment-A):** `ThorlabsMotor.motor_move` catches `Exception` (`thorlabs_kinesis.py:467`) and would turn the timeout raise into `err_code: motor` (E-STOP). The task adds `MotionTimeoutError(RuntimeError)` and re-raises only that. The spec's `qmove = {...}` initialization is unnecessary once the loop records `all_stopped`; the `UnboundLocalError` disappears with the deleted re-map (test (b) pins it).
- **Task 7 (hte):** `motor_busy`/`blocked` already reset in `finally` on `origin/main`; no new code for that, test (b) pins it. Test (c) and the RF3 test pass today (regression guards), so the mutation check expects only the new-behaviour tests to go red.
- **Task 10 (hte):** the LocalLoader port replaces the `plate_id`/`sample_no` lookup with the process's first `samples_in` `global_label`, sets `run_use="data"` on both classes, reads `CA_potential_vsRHE` with `.get`, and adds a shared `local_frame(local_loader)` helper in `echeuvis_stability.py`. These are choices the spec left open.
- **Task 11 (hte):** also removes the `hispec` key from `KNOWN_CONFIG_GAPS`, or `test_config_gap_allowlist_has_no_stale_entries` fails once the postseq sequences are gone.
- **Task 27 (Deployment-B):** new config param `moving_eps_rad_s` (default `1e-3`) gets one new row in the robotarm README `## Params`, the only `## Params` edit in this plan. `int(robot_mode)` is not NaN-guarded; the UR offsets need the station check anyway.
- **Task 33 (Deployment-E):** adds a server-side test for the empty-timestamp guard (`oceandirect_server.py:194`), which the spec left untested.
- **README line citations:** several fixes move lines. Tasks 9, 17 and 20 create scratch renumbering helpers under `/tmp/claude-1000/`; every README step re-derives moved citations with `grep -n` before the guard run.
- **Commit granularity:** per task, not per unit (see Global Constraints).

---
### Task 1: H1 mfc `FlowMeter.get_status` mutates `status_keys` (hte)

**Files:**
- Modify: `/tmp/claude-1000/wt-parent/helao/deploy/hte/servers/mfc/alicat_driver.py:1113-1131` (`is_connected`), `:1183-1192` (`get_status`), `:1652-1666` (`__main__` stream)
- Test: `/tmp/claude-1000/wt-parent/helao/deploy/hte/tests/test_alicat_status_keys.py` (new file; do not touch `tests/test_alicat_meter_status.py`, which another session's branch edits)
- Docs: `/tmp/claude-1000/wt-parent/helao/deploy/hte/servers/mfc/README.md`

**Interfaces:**
- Consumes: none
- Produces: the parent worktree `/tmp/claude-1000/wt-parent` (detached at the pre-U1 `unstable`) and the hte worktree `/tmp/claude-1000/wt-parent/helao/deploy/hte` on branch `fix/catalog-bugfixes`; `/tmp/claude-1000/parent-base.txt` (parent `unstable` sha before any task commits; Task 34 reads it). Every later hte task works in this worktree. The first hte task after Task 5 refreshes the parent worktree with `git -C /tmp/claude-1000/wt-parent checkout --detach unstable` so U1 is visible to hte tests.

- [ ] **Step 0: Worktree setup (main session)**

The shared hte clone is on another session's branch and must never be switched. The hte worktree is nested inside a detached parent worktree so that `helao.deploy.hte` imports from the worktree: `helao/deploy/hte` is gitignored in the parent, pytest's rootdir-based module naming resolves `helao.deploy.hte.tests.<x>` exactly as in the main clone, and no symlink is involved.

```bash
PY=/home/dan/miniforge3/envs/helao/bin/python
git -C /mnt/STORAGE/repos/helao/helao-async rev-parse unstable > /tmp/claude-1000/parent-base.txt
mkdir -p /tmp/claude-1000 && git -C /mnt/STORAGE/repos/helao/helao-async worktree add --detach /tmp/claude-1000/wt-parent unstable && git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/hte fetch origin && git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/hte worktree add /tmp/claude-1000/wt-parent/helao/deploy/hte -b fix/catalog-bugfixes origin/main
```

Sanity check:

```bash
cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent $PY -c "import helao.deploy.hte.servers.mfc.alicat_driver as m; print(m.__file__)"
```

Expected: `/tmp/claude-1000/wt-parent/helao/deploy/hte/servers/mfc/alicat_driver.py`. Any other path: stop and report; do not continue.

Baseline guard (expected PASS before any change):

```bash
cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent $PY -m pytest helao/deploy/hte/tests/test_readme_outputs.py -q
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte log --oneline -1
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/hte branch --show-current
```

Expected: guard passes; worktree HEAD is `origin/main` (f4e8a368 or later); the shared clone still reports `fix/alicat-meter-status` (untouched).

- [ ] **Step 1: Write the failing test**

Create `/tmp/claude-1000/wt-parent/helao/deploy/hte/tests/test_alicat_status_keys.py`:

```python
"""``FlowMeter.get_status`` must not change ``status_keys`` between replies.

A controller reply's field count can vary (a truncated read, a totalizer reply,
an unlisted status flag). Each reply is keyed on its own; one odd reply must
not re-key every later one.
"""

import helao.deploy.hte.servers.mfc.alicat_driver as alicat

BASE_KEYS = [
    "pressure",
    "temperature",
    "volumetric_flow",
    "mass_flow",
    "setpoint",
    "gas",
]
# Fields after the unit id, in order: pressure, temperature, volumetric flow,
# mass flow, setpoint, gas (the FlowMeter.__init__ status_keys order).
R6 = "B +014.70 +022.00 +003.00 +002.90 +003.00 CO2"
R5 = "B +014.70 +022.00 +003.00 +002.90 CO2"
R7 = "B +014.70 +022.00 +003.00 +002.90 +003.00 +010.00 CO2"
R2 = "B +014.70 +003.00"


def _fc(replies):
    fc = object.__new__(alicat.FlowController)
    fc.address, fc.port, fc.open = "B", "X", True
    fc.control_point = "mass flow"
    fc.status_keys = list(BASE_KEYS)
    it = iter(replies)
    fc._write_and_read = lambda command, retries=2: next(it)
    return fc


def test_short_reply_does_not_drop_setpoint_from_later_replies():
    fc = _fc([R6, R5, R6])
    fc.get_status(), fc.get_status()
    third = fc.get_status()
    assert third["setpoint"] == 3.0  # 5th field of R6
    assert third["gas"] == "CO2"
    assert fc.status_keys == BASE_KEYS


def test_long_reply_does_not_rekey_later_replies():
    fc = _fc([R6, R7, R6])
    fc.get_status(), fc.get_status()
    third = fc.get_status()
    assert third["gas"] == "CO2"
    assert "total flow" not in third
    assert fc.status_keys == BASE_KEYS


def test_two_field_reply_does_not_rekey_later_replies():
    # Review Focus RF1: the len(values) == 2 branch inserts "setpoint" at index 1.
    fc = _fc([R2, R6])
    first = fc.get_status()
    assert first["pressure"] == 14.7 and first["setpoint"] == 3.0
    second = fc.get_status()
    assert second["setpoint"] == 3.0 and second["gas"] == "CO2"
    assert fc.status_keys == BASE_KEYS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/tests/test_alicat_status_keys.py -v`

Expected: 3 FAIL. `test_short_reply...` with `KeyError: 'setpoint'`; `test_long_reply...` and `test_two_field_reply...` with `ValueError: could not convert string to float: 'CO2'` (verified against origin/main code).

- [ ] **Step 3: Write minimal implementation**

In `servers/mfc/alicat_driver.py`, `FlowMeter.get_status` (`:1183-1192`), replace:

```python
        if len(values) == 5 and len(self.status_keys) == 6:
            del self.status_keys[-2]
        elif len(values) == 7 and len(self.status_keys) == 6:
            self.status_keys.insert(5, "total flow")
        elif len(values) == 2 and len(self.status_keys) == 6:
            self.status_keys.insert(1, "setpoint")
        return_dict = {
            k: (v if k == self.status_keys[-1] else float(v))
            for k, v in zip(self.status_keys, values)
        }
```

with:

```python
        keys = list(self.status_keys)  # per reply; never mutate status_keys
        if len(values) == 5:
            del keys[-2]
        elif len(values) == 7:
            keys.insert(5, "total flow")
        elif len(values) == 2:
            keys.insert(1, "setpoint")
        return_dict = {
            k: (v if k == keys[-1] else float(v)) for k, v in zip(keys, values)
        }
```

`is_connected` (`:1113-1131`, no callers) relied on the mutation. Replace the docstring sentence and the two asserts:

```python
        `FlowMeter` and
        `FlowController` by whether `setpoint` appears in the status keys.
```
→
```python
        `FlowMeter` and
        `FlowController` by whether `setpoint` appears in the returned status.
```
and
```python
                    assert c and "setpoint" not in device.status_keys
                elif cls.__name__ == "FlowController":
                    assert c and "setpoint" in device.status_keys
```
→
```python
                    assert c and "setpoint" not in c
                elif cls.__name__ == "FlowController":
                    assert c and "setpoint" in c
```

`__main__` stream (`:1652-1666`) indexed `state[key]` over `status_keys`; a meter reply has no `setpoint`. Replace:

```python
            print("time\t" + "\t".join(flow_controller.status_keys))
            t0 = time.time()
            while True:
                state = flow_controller.get_status()
                print(
                    "{:.2f}\t".format(time.time() - t0)
                    + "\t\t".join(
                        "{:.2f}".format(state[key])
                        for key in flow_controller.status_keys[:-1]
                    )
                    + "\t\t"
                    + state["gas"]
                )
```

with:

```python
            skip = ("gas", "acquire_time", "hold_valve", "lock_display", "control_point")
            print("time\t" + "\t".join(k for k in state if k not in skip) + "\tgas")
            t0 = time.time()
            while True:
                state = flow_controller.get_status()
                print(
                    "{:.2f}\t".format(time.time() - t0)
                    + "\t\t".join(
                        "{:.2f}".format(v) for k, v in state.items() if k not in skip
                    )
                    + "\t\t"
                    + state["gas"]
                )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/tests/test_alicat_status_keys.py helao/deploy/hte/tests/test_alicat_meter_status.py -v`

Expected: PASS (3 new + the existing meter-status tests).

- [ ] **Step 5: Mutation check**

```bash
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte diff -- servers/mfc/alicat_driver.py > /tmp/claude-1000/mut-task1.patch && git -C /tmp/claude-1000/wt-parent/helao/deploy/hte apply -R /tmp/claude-1000/mut-task1.patch
cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/tests/test_alicat_status_keys.py -q
```
Expected: 3 failed (same errors as Step 2).
```bash
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte apply /tmp/claude-1000/mut-task1.patch
cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/tests/test_alicat_status_keys.py -q
```
Expected: 3 passed.

- [ ] **Step 6: README**

In `servers/mfc/README.md`:
- Delete the `## Notes` bullet that begins ``- `FlowMeter.get_status` changes the per-device `status_keys` list permanently``. If it is the only bullet, leave `## Notes` with the remaining bullets or drop the empty heading.
- `setpoint` row, meaning column: replace `control setpoint; `null` for a flow meter (MFM), which reports no setpoint.` with `control setpoint; `null` for a flow meter (MFM) and for any single 5-field reply, which carries no setpoint (each reply is keyed on its own).`
- In the live-data paragraph, replace `A device that reports 5 fields (a flow meter) has `setpoint` deleted by `get_status`` with `A reply with 5 fields (a flow meter) has no `setpoint` key from `get_status``.
- Line citations: the edit keeps `get_status` at the same length but `return_dict = {` moves down one line. After `black`, re-derive with `grep -n "return_dict = {\|return_dict.update(holdlockd)\|return_dict\[\"acquire_time\"\]\|del keys\[-2\]" servers/mfc/alicat_driver.py` and update every `alicat_driver.py:1189`, `:1193`, `:1194` and `:1183-1184` citation in the README to the new numbers (expected `:1190`, `:1194`, `:1195`, `:1184-1185`).

Run: `cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/tests/test_readme_outputs.py -q` → PASS. `git -C /tmp/claude-1000/wt-parent/helao/deploy/hte diff -- servers/mfc/README.md` shows only the edits above.

- [ ] **Step 7: Commit (main session; subagents never commit)**

```bash
/home/dan/miniforge3/envs/helao/bin/black /tmp/claude-1000/wt-parent/helao/deploy/hte/servers/mfc/alicat_driver.py /tmp/claude-1000/wt-parent/helao/deploy/hte/tests/test_alicat_status_keys.py
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte branch --show-current   # expect fix/catalog-bugfixes
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte status --short
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte add servers/mfc/alicat_driver.py servers/mfc/README.md tests/test_alicat_status_keys.py
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte commit -m "fix(mfc): key each status reply on its own, never mutate status_keys"
```

Local only, no push.

---

---

### Task 2: P1 `ErrorCodes` renders as `"ErrorCodes.none"` (parent)

**Files:**
- Modify: `/mnt/STORAGE/repos/helao/helao-async/helao/core/error.py:8` (class `ErrorCodes`)
- Test: `/mnt/STORAGE/repos/helao/helao-async/helao/core/tests/unit_test_error_codes.py` (reporter script run by `run_unit_tests.py`)
- Docs: none in the parent (see Step 6)

**Interfaces:**
- Consumes: none
- Produces: `str(ErrorCodes.x) == f"{ErrorCodes.x}" == "x"` for every member. hte aligner rows (`layouts/aligner.py:1266`), Deployment-A `layouts/plate_aligner.py:1027` and `helao/deploy/base/servers/reflex/_pstat.py:228` render the bare value with no edit there.

- [ ] **Step 1: Write the failing test**

In `helao/core/tests/unit_test_error_codes.py`, insert before `        return reporter.success()`:

```python
        reporter.section("ErrorCodes renders as its bare value (Python 3.12+ format)")
        # Independent expectation: the member values are the strings "none"/"stop".
        reporter.check(
            'f"{ErrorCodes.none}" == "none"',
            lambda: f"{ErrorCodes.none}" == "none",
        )
        reporter.check(
            'str(ErrorCodes.stop) == "stop"',
            lambda: str(ErrorCodes.stop) == "stop",
        )
```

The existing `"ErrorCodes."` text at `:61`, `:83`, `:87` and in `unit_test_dispatcher.py:393,397` is check-label text built from `.name`/`.value` or a literal; it never formats an enum, so it stays unchanged.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -c "from helao.core.tests.unit_test_error_codes import error_codes_unit_test as t; raise SystemExit(0 if t() else 1)"; echo rc=$?`

Expected: the two new checks reported failed, `rc=1` (on Python 3.14 `f"{ErrorCodes.none}"` is `"ErrorCodes.none"`, verified).

- [ ] **Step 3: Write minimal implementation**

In `helao/core/error.py`, after the class docstring (it ends at `    """` before `    none = "none"`), insert:

```python
    __str__ = str.__str__  # format()/str() give the value, as before Python 3.12
```

A descriptor assigned in an Enum body is not a member (verified: `list(X)` keeps only the value members), so the membership checks stay green.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -c "from helao.core.tests.unit_test_error_codes import error_codes_unit_test as t; raise SystemExit(0 if t() else 1)"; echo rc=$?` → `rc=0`.

Then: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python run_unit_tests.py` → `overall: PASS`.

- [ ] **Step 5: Mutation check**

```bash
git -C /mnt/STORAGE/repos/helao/helao-async diff -- helao/core/error.py > /tmp/claude-1000/mut-task2.patch && git -C /mnt/STORAGE/repos/helao/helao-async apply -R /tmp/claude-1000/mut-task2.patch
cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -c "from helao.core.tests.unit_test_error_codes import error_codes_unit_test as t; raise SystemExit(0 if t() else 1)"; echo rc=$?
```
Expected `rc=1`.
```bash
git -C /mnt/STORAGE/repos/helao/helao-async apply /tmp/claude-1000/mut-task2.patch
cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -c "from helao.core.tests.unit_test_error_codes import error_codes_unit_test as t; raise SystemExit(0 if t() else 1)"; echo rc=$?
```
Expected `rc=0`.

- [ ] **Step 6: README**

No parent README catalogs this. The hte `servers/galil_motion/README.md` aligner `err_code` row (`:175`) and `## Notes` bullet (`:192`), and the Deployment-A plate-aligner README equivalent, are corrected in their repos' tasks (Task 7 for hte galil_motion, Task 30 for Deployment-A): the row becomes "`f"{errorcode}"` renders the bare value `none` / `stop`; rows written on Python 3.12+ before this fix carry `ErrorCodes.none` / `ErrorCodes.stop`, so consumers accept both spellings", and the Notes bullet is deleted. Run the base guard to confirm nothing else moved: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/base/tests/test_readme_outputs.py -q` → PASS.

- [ ] **Step 7: Commit (main session; subagents never commit)**

```bash
/home/dan/miniforge3/envs/helao/bin/black /mnt/STORAGE/repos/helao/helao-async/helao/core/error.py /mnt/STORAGE/repos/helao/helao-async/helao/core/tests/unit_test_error_codes.py
git -C /mnt/STORAGE/repos/helao/helao-async branch --show-current   # expect unstable
git -C /mnt/STORAGE/repos/helao/helao-async status --short
git -C /mnt/STORAGE/repos/helao/helao-async add helao/core/error.py helao/core/tests/unit_test_error_codes.py
git -C /mnt/STORAGE/repos/helao/helao-async commit -m "fix(core): ErrorCodes str/format render the bare value on Python 3.12+"
```

Local only, no push.

---

---

### Task 3: P2 `get_Mplate_Msystem` rejects the JSON string its action callers send (parent)

**Files:**
- Modify: `/mnt/STORAGE/repos/helao/helao-async/helao/hexagon/domain/motion_transform.py:12-15` (imports), `:357-364` (`get_Mplate_Msystem`)
- Test: `/mnt/STORAGE/repos/helao/helao-async/helao/hexagon/tests/test_motion_transform.py`
- Docs: none in the parent

**Interfaces:**
- Consumes: none
- Produces: `TransformXY.get_Mplate_Msystem(Mxy: str | list | np.ndarray | None, *args, **kwargs) -> np.matrix | None`. A `str` is parsed with `json.loads`; `None` raises `ValueError("Mxy required")`; a singular `Minstr` still returns `None`. Return type stays `np.matrix` (the aligners call `.tolist()` on it). Tasks 14 (hte `MxytoMPlate`) and 30 (Deployment-A `MxytoMPlate`) rely on this and enqueue `M.tolist()`.

- [ ] **Step 1: Write the failing test**

Append to `helao/hexagon/tests/test_motion_transform.py`:

```python
import pytest


def test_get_mplate_msystem_parses_the_json_string_form():
    # The MxytoMPlate actions declare Mxy: Optional[str]; identity in -> identity out.
    t = _identity_transform(seq=None)
    result = t.get_Mplate_Msystem("[[1,0,0],[0,1,0],[0,0,1]]")
    assert np.allclose(result, np.identity(3))


def test_get_mplate_msystem_accepts_a_nested_list():
    # Review Focus RF2: an Action envelope can carry the matrix as a list.
    t = _identity_transform(seq=None)
    result = t.get_Mplate_Msystem([[1, 0, 0], [0, 1, 0], [0, 0, 1]])
    assert np.allclose(result, np.identity(3))


def test_get_mplate_msystem_none_raises_a_clear_error():
    # Review Focus RF2: a missing Mxy is a 500 (pause + re-queue), not an IndexError.
    t = _identity_transform(seq=None)
    with pytest.raises(ValueError, match="Mxy required"):
        t.get_Mplate_Msystem(None)
```

Put the `import pytest` line with the file's other imports at the top (after `import numpy as np`), not mid-file.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/hexagon/tests/test_motion_transform.py -v`

Expected: `test_get_mplate_msystem_parses_the_json_string_form` and `test_get_mplate_msystem_none_raises_a_clear_error` FAIL with `IndexError: too many indices for array: array is 0-dimensional, but 2 were indexed`; `test_get_mplate_msystem_accepts_a_nested_list` PASSES (regression guard, verified).

- [ ] **Step 3: Write minimal implementation**

In `helao/hexagon/domain/motion_transform.py`, imports (`:12-13`):

```python
import logging
import traceback
```
→
```python
import json
import logging
import traceback
```

(`json` is stdlib and not on `test_boundaries.py`'s `STDLIB_DENY`.)

In `get_Mplate_Msystem` replace:

```python
        plate-only calibration. Returns ``None`` (and leaves ``Minv``
        untouched) when `Minstr` is singular.
        """
        Mxy = np.asarray(Mxy)
```
with:
```python
        plate-only calibration. `Mxy` may be a JSON string (the
        ``MxytoMPlate`` action form), a nested list or an array. Returns
        ``None`` (and leaves ``Minv`` untouched) when `Minstr` is singular.

        Raises:
            ValueError: If `Mxy` is None.
        """
        if Mxy is None:
            raise ValueError("Mxy required")
        if isinstance(Mxy, str):
            Mxy = json.loads(Mxy)
        Mxy = np.asarray(Mxy)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/hexagon/tests/test_motion_transform.py helao/hexagon/tests/test_boundaries.py -v`

Expected: PASS (all, including the domain import allow-list).

- [ ] **Step 5: Mutation check**

```bash
git -C /mnt/STORAGE/repos/helao/helao-async diff -- helao/hexagon/domain/motion_transform.py > /tmp/claude-1000/mut-task3.patch && git -C /mnt/STORAGE/repos/helao/helao-async apply -R /tmp/claude-1000/mut-task3.patch
cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/hexagon/tests/test_motion_transform.py -q
```
Expected: 2 failed (`IndexError`).
```bash
git -C /mnt/STORAGE/repos/helao/helao-async apply /tmp/claude-1000/mut-task3.patch
cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/hexagon/tests/test_motion_transform.py -q
```
Expected: all passed.

- [ ] **Step 6: README**

No parent README covers `motion_transform.py`. The `MxytoMPlate` rows and notes in hte `servers/galil_motion/README.md` and the Deployment-A motion README are corrected in Tasks 14 and 30, which change the endpoints that write the row.

- [ ] **Step 7: Commit (main session; subagents never commit)**

```bash
/home/dan/miniforge3/envs/helao/bin/black /mnt/STORAGE/repos/helao/helao-async/helao/hexagon/domain/motion_transform.py /mnt/STORAGE/repos/helao/helao-async/helao/hexagon/tests/test_motion_transform.py
git -C /mnt/STORAGE/repos/helao/helao-async branch --show-current   # expect unstable
git -C /mnt/STORAGE/repos/helao/helao-async status --short
git -C /mnt/STORAGE/repos/helao/helao-async add helao/hexagon/domain/motion_transform.py helao/hexagon/tests/test_motion_transform.py
git -C /mnt/STORAGE/repos/helao/helao-async commit -m "fix(motion): get_Mplate_Msystem parses the JSON string form, rejects None"
```

Local only, no push.

---

---

### Task 4: P3 `HelaoDict` key guard crashes on non-str keys (parent)

**Files:**
- Modify: `/mnt/STORAGE/repos/helao/helao-async/helao/core/helaodict.py:42-44` (`_serialize_dict`)
- Test: `/mnt/STORAGE/repos/helao/helao-async/helao/core/tests/test_helaodict_keys.py` (new)
- Docs: none

**Interfaces:**
- Consumes: none
- Produces: `HelaoDict._serialize_dict` accepts any hashable non-str key with a str value. Every input that serialized before serializes identically. Task 15 (hte `_tray_pos` string keys) relies on it.

- [ ] **Step 1: Write the failing test**

Create `helao/core/tests/test_helaodict_keys.py`:

```python
"""``HelaoDict._serialize_dict`` must not call ``str`` methods on non-str keys.

The dunder filter skips ``"__x": <str>`` entries. It used to call
``k.startswith`` on every key whose value was a str, so an int key crashed.
"""

from helao.core.helaodict import HelaoDict


def test_int_key_with_str_value_serializes():
    assert HelaoDict()._serialize_dict({1: "a"}) == {1: "a"}


def test_dunder_str_entries_are_still_skipped():
    assert HelaoDict()._serialize_dict({"__x": "y", "a": "b"}) == {"a": "b"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/core/tests/test_helaodict_keys.py -v`

Expected: `test_int_key_with_str_value_serializes` FAIL with `AttributeError: 'int' object has no attribute 'startswith'`; the dunder test passes (regression guard).

- [ ] **Step 3: Write minimal implementation**

In `helao/core/helaodict.py` replace:

```python
            if not isinstance(v, types.FunctionType) and not (
                isinstance(v, str) and k.startswith("__")
            ):
```
with:
```python
            if not isinstance(v, types.FunctionType) and not (
                isinstance(v, str) and isinstance(k, str) and k.startswith("__")
            ):
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/core/tests/test_helaodict_keys.py -v` → PASS.
Then: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python run_unit_tests.py` → `overall: PASS` (includes `unit_test_helaodict`).

- [ ] **Step 5: Mutation check**

```bash
git -C /mnt/STORAGE/repos/helao/helao-async diff -- helao/core/helaodict.py > /tmp/claude-1000/mut-task4.patch && git -C /mnt/STORAGE/repos/helao/helao-async apply -R /tmp/claude-1000/mut-task4.patch
cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/core/tests/test_helaodict_keys.py -q
```
Expected: 1 failed (`AttributeError`).
```bash
git -C /mnt/STORAGE/repos/helao/helao-async apply /tmp/claude-1000/mut-task4.patch
cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/core/tests/test_helaodict_keys.py -q
```
Expected: 2 passed.

- [ ] **Step 6: README**

Core serializer; no README catalogs it. The hte sample README `_tray_pos` row and note change in Task 15.

- [ ] **Step 7: Commit (main session; subagents never commit)**

```bash
/home/dan/miniforge3/envs/helao/bin/black /mnt/STORAGE/repos/helao/helao-async/helao/core/helaodict.py /mnt/STORAGE/repos/helao/helao-async/helao/core/tests/test_helaodict_keys.py
git -C /mnt/STORAGE/repos/helao/helao-async branch --show-current   # expect unstable
git -C /mnt/STORAGE/repos/helao/helao-async status --short
git -C /mnt/STORAGE/repos/helao/helao-async add helao/core/helaodict.py helao/core/tests/test_helaodict_keys.py
git -C /mnt/STORAGE/repos/helao/helao-async commit -m "fix(core): HelaoDict dunder filter only tests str keys"
```

Local only, no push.

---

---

### Task 5: P4 `MetaProcessor` never sees orchestrator `global_params` (parent)

**Files:**
- Modify: `/mnt/STORAGE/repos/helao/helao-async/helao/helpers/processors.py:74-75` (docstring), `:89-91` (`MetaProcessor.__init__`)
- Test: `/mnt/STORAGE/repos/helao/helao-async/helao/core/tests/test_hooks_loader.py`
- Docs: none in the parent

**Interfaces:**
- Consumes: none
- Produces: `MetaProcessor.global_params == getattr(core, "global_params", None) or {}`. An `OrchHost` passes its `global_params`; an `ActionHost` (no such attribute) or `object()` gives `{}`. Deployment-A `processors/append_ref_vshe.py` then writes the float `last_OCP_V` (no edit in Deployment-A; its README note is updated in Task 30's README step).

- [ ] **Step 1: Write the failing test**

Append to `helao/core/tests/test_hooks_loader.py`:

```python
@pytest.mark.asyncio
async def test_meta_processor_sees_orchestrator_global_params():
    from helao.hexagon.app.orch_host import OrchHost

    seen = {}

    class PP(MetaProcessor):
        def process(self):
            seen.update(self.global_params)

    class Sequence:
        sequence_params = {}

    orch = object.__new__(OrchHost)  # class name "OrchHost", not the legacy "Orch"
    orch.global_params = {"last_OCP_V": 0.5}
    await MetaProcessorHook(PP).run(
        PrefinishContext(
            record=Sequence(), record_dir=Path("."), server=orch, args=None
        )
    )
    assert seen == {"last_OCP_V": 0.5}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/core/tests/test_hooks_loader.py::test_meta_processor_sees_orchestrator_global_params -v`

Expected: FAIL with `AssertionError: assert {} == {'last_OCP_V': 0.5}` (verified).

- [ ] **Step 3: Write minimal implementation**

In `helao/helpers/processors.py` replace:

```python
        self.global_params = (
            core.global_params if core.__class__.__name__.lower() == "orch" else {}
        )
```
with:
```python
        self.global_params = getattr(core, "global_params", None) or {}
```

and the class docstring lines:

```python
        global_params: Orchestrator global parameters dict when ``core`` is an
            orchestrator, otherwise an empty dict.
```
with:
```python
        global_params: ``core.global_params`` when ``core`` has one (the
            orchestrator), otherwise an empty dict.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/core/tests/test_hooks_loader.py -v`

Expected: PASS (new test plus `test_meta_adapter_mutates_in_place`, which passes `server=object()`).

- [ ] **Step 5: Mutation check**

```bash
git -C /mnt/STORAGE/repos/helao/helao-async diff -- helao/helpers/processors.py > /tmp/claude-1000/mut-task5.patch && git -C /mnt/STORAGE/repos/helao/helao-async apply -R /tmp/claude-1000/mut-task5.patch
cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/core/tests/test_hooks_loader.py::test_meta_processor_sees_orchestrator_global_params -q
```
Expected: 1 failed (`assert {} == ...`).
```bash
git -C /mnt/STORAGE/repos/helao/helao-async apply /tmp/claude-1000/mut-task5.patch
cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/core/tests/test_hooks_loader.py::test_meta_processor_sees_orchestrator_global_params -q
```
Expected: 1 passed.

- [ ] **Step 6: README**

No parent README covers `processors.py`. The Deployment-A `processors/README.md` note that `ref_vshe` is always `null` is removed in Task 30's README step (U1 has landed by then). Run the test-deployment guard (its `processors/sim_append_params.py` subclasses `MetaProcessor`): `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/test/tests/test_readme_outputs.py -q` → PASS.

- [ ] **Step 7: Commit (main session; subagents never commit)**

```bash
/home/dan/miniforge3/envs/helao/bin/black /mnt/STORAGE/repos/helao/helao-async/helao/helpers/processors.py /mnt/STORAGE/repos/helao/helao-async/helao/core/tests/test_hooks_loader.py
git -C /mnt/STORAGE/repos/helao/helao-async branch --show-current   # expect unstable
git -C /mnt/STORAGE/repos/helao/helao-async status --short
git -C /mnt/STORAGE/repos/helao/helao-async add helao/helpers/processors.py helao/core/tests/test_hooks_loader.py
git -C /mnt/STORAGE/repos/helao/helao-async commit -m "fix(processors): MetaProcessor reads global_params from any core that has them"
```

Local only, no push.

---

### Task 6: H2 sample `archive_tray_export_json` on an undefined slot (hte)

**Files:**
- Modify: `helao/deploy/hte/servers/sample/sample_server.py:20-50` (module logger), `:330-332` (endpoint body)
- Create: `helao/deploy/hte/servers/sample/tests/__init__.py` (empty; makes the new test dir a package like `servers/biologic/tests/`)
- Test: `helao/deploy/hte/servers/sample/tests/test_tray_export_json.py` (new)
- Docs: `helao/deploy/hte/servers/sample/README.md`

**Interfaces:**
- Consumes: none (parent Tasks 2-5 must be in the parent worktree only because later hte tasks import them; this task does not use them).
- Produces: `helao/deploy/hte/servers/sample/tests/` package (Tasks 15 and 16 add files to it); module-level `LOGGER` in `helao.deploy.hte.servers.sample.sample_server`.

- [ ] **Step 0 (main session): refresh the parent worktree to include Tasks 2-5**

Run: `git -C /tmp/claude-1000/wt-parent checkout --detach unstable` then `git -C /tmp/claude-1000/wt-parent log --oneline -1`
Expected: the Task 5 commit (`fix(core): MetaProcessor reads global_params from any orchestrator`, or whatever subject Task 5 committed) is HEAD. The nested hte worktree at `/tmp/claude-1000/wt-parent/helao/deploy/hte` is git-ignored by the parent and is not touched by this checkout; confirm with `git -C /tmp/claude-1000/wt-parent/helao/deploy/hte branch --show-current` → `fix/catalog-bugfixes`.

- [ ] **Step 1: Write the failing test**

Create `/tmp/claude-1000/wt-parent/helao/deploy/hte/servers/sample/tests/__init__.py` (empty file) and `/tmp/claude-1000/wt-parent/helao/deploy/hte/servers/sample/tests/test_tray_export_json.py`:

```python
"""archive_tray_export_json on an undefined slot: warn, write no row, finish none.

The driver answers ``None`` for "nothing to export" (no tray, no slot, or a
null slot, ``archive_driver.py:549-559``). The endpoint wrapped that in
``DataModel``, whose ``data`` is ``dict[UUID, dict]``, so an operator no-op
became a 500 after ``ctx.begin`` and the re-queued action failed again on
resume. ``archive_tray_export_csv`` already writes nothing and finishes.
"""

import asyncio
import types
import uuid

from helao.core.error import ErrorCodes
from helao.helpers.premodels import Action
from helao.helpers.sample_positions import Positions
from helao.deploy.hte.servers.sample import sample_server
from helao.deploy.hte.servers.sample.archive_driver import Archive


class _App:
    """Captures the routes ``makeApp`` registers; stands in for ActionHost."""

    def __init__(self, *args, **kwargs):
        self.server_params = {}
        self.routes = {}
        self.driver = None

    def action(self, **kw):
        def deco(fn):
            self.routes[fn.__name__] = fn
            return fn

        return deco

    def post(self, path, **kw):
        return lambda fn: fn


class _Active:
    def __init__(self, action_params):
        self.action = Action(
            action_name="archive_tray_export_json", action_params=action_params
        )
        self.base = types.SimpleNamespace(dflt_file_conn_key=lambda: uuid.uuid4())
        self.enqueued = []

    def enqueue_data_nowait(self, datamodel, action=None):
        self.enqueued.append(datamodel)

    async def finish(self):
        return self.action


class _Ctx:
    def __init__(self, active):
        self.active = active

    async def begin(self, **kw):
        return self.active


def _app(monkeypatch, trays_dict):
    monkeypatch.setattr(sample_server, "ActionHost", _App)
    app = sample_server.makeApp("SAMPLE")
    stub = types.SimpleNamespace(
        positions=Positions(trays_dict=trays_dict), write_config=lambda: None
    )
    # the real driver method, bound to a stub that holds only the tray table
    stub.tray_export_json = types.MethodType(Archive.tray_export_json, stub)
    app.driver = stub
    return app


def test_undefined_slot_writes_no_row_and_finishes_none(monkeypatch):
    # tray 1 slot 1 is defined as null, exactly like adss3.yml tray 1 slots 1-3
    app = _app(monkeypatch, {1: {1: None}})
    active = _Active({"tray": 1, "slot": 1})
    result = asyncio.run(
        app.routes["archive_tray_export_json"](ctx=_Ctx(active), tray=1, slot=1)
    )
    assert active.enqueued == []
    assert active.action.error_code is ErrorCodes.none
    assert result["error_code"] == "none"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/servers/sample/tests/test_tray_export_json.py -v`
Expected: FAIL with `pydantic_core._pydantic_core.ValidationError: 1 validation error for DataModel ... Input should be a valid dictionary [type=dict_type, input_value=None` raised at `sample_server.py:331`.

- [ ] **Step 3: Write minimal implementation**

In `/tmp/claude-1000/wt-parent/helao/deploy/hte/servers/sample/sample_server.py`, add the module logger right after `from helao.helpers.premodels import Action` (`:43`), using the idiom `archive_driver.py:26-28` already uses:

```python
from helao.helpers.premodels import Action
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
```

Replace the endpoint body at `:330-332`:

```python
        datadict = await app.driver.tray_export_json(**active.action.action_params)
        datamodel = DataModel(data={active.base.dflt_file_conn_key(): datadict})
        active.enqueue_data_nowait(datamodel, action=active.action)
```

with:

```python
        datadict = await app.driver.tray_export_json(**active.action.action_params)
        if datadict is None:
            # undefined tray/slot: nothing to export, as archive_tray_export_csv
            LOGGER.warning(
                f"archive_tray_export_json: no vial table at tray "
                f"{active.action.action_params.get('tray')} slot "
                f"{active.action.action_params.get('slot')}; no row written"
            )
        else:
            datamodel = DataModel(data={active.base.dflt_file_conn_key(): datadict})
            active.enqueue_data_nowait(datamodel, action=active.action)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/servers/sample/tests/test_tray_export_json.py -v`
Expected: PASS.
Regression: `cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/tests/test_hte_library_import.py -q` → PASS (the server module still imports).

- [ ] **Step 5: Mutation check**

```bash
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte diff -- servers/sample/sample_server.py > /tmp/claude-1000/mut-task6.patch && git -C /tmp/claude-1000/wt-parent/helao/deploy/hte apply -R /tmp/claude-1000/mut-task6.patch
cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/servers/sample/tests/test_tray_export_json.py -q
```
Expected: FAIL (`ValidationError`, as Step 2). Then `git -C /tmp/claude-1000/wt-parent/helao/deploy/hte apply /tmp/claude-1000/mut-task6.patch` and rerun → PASS.

- [ ] **Step 6: README**

In `/tmp/claude-1000/wt-parent/helao/deploy/hte/servers/sample/README.md`:
- In the `**archive_tray_export_json**` paragraph (`## Outputs` → `### Tray actions`), replace the sentence starting `The row is the vial tray dict of the slot (fields in the vial tray table above); when the slot is undefined the driver returns `None`, and ...` through `(see Notes).` with:
  `The row is the vial tray dict of the slot (fields in the vial tray table above). When the tray or slot is undefined or null the driver returns `None` (`helao/deploy/hte/servers/sample/archive_driver.py:549-559`); the endpoint then logs a WARNING, queues no row and finishes with `error_code` `none` (`helao/deploy/hte/servers/sample/sample_server.py:<line of the new if datadict is None>`).` Cite the row write as the `enqueue_data_nowait` line inside the new `else` (find both with `grep -n "datadict is None\|enqueue_data_nowait(datamodel" servers/sample/sample_server.py` in the hte worktree), and shift the `traytojson` citation `:327-328` if the logger lines moved it (`grep -n traytojson`).
- In `## Notes`, delete the bullet `- `archive_tray_export_json` with an undefined slot raises `pydantic.ValidationError` when it builds the `DataModel` ... so the action never finishes normally.`
- Every other `sample_server.py:<n>` citation in this README below `:43` moves down by 3 lines (the logger block). Update them: `grep -n "sample_server.py:" servers/sample/README.md` and add 3 to each line number greater than 43 (Tasks 15 and 16 edit this README again; keep the numbers true after each task).

Guard: `cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/tests/test_readme_outputs.py -q` → PASS.

- [ ] **Step 7: Commit (main session; subagents never commit)**

```bash
/home/dan/miniforge3/envs/helao/bin/black /tmp/claude-1000/wt-parent/helao/deploy/hte/servers/sample/sample_server.py /tmp/claude-1000/wt-parent/helao/deploy/hte/servers/sample/tests/test_tray_export_json.py /tmp/claude-1000/wt-parent/helao/deploy/hte/servers/sample/tests/__init__.py
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte branch --show-current   # expect fix/catalog-bugfixes
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte status --short
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte add servers/sample/sample_server.py servers/sample/tests/__init__.py servers/sample/tests/test_tray_export_json.py servers/sample/README.md
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte commit -m "fix(sample): export_json on an undefined slot writes no row and finishes"
```

---

---

### Task 7: H3 galil real move timeout, unconfigured axes, disabled-controller indexing (hte)

**Files:**
- Modify: `helao/deploy/hte/servers/galil_motion/galil_motion_native.py:29` (drop now-unused `deepcopy` import), `:597-601` (joint filter), `:606-616` (dead `else`), `:702-721` (settle loop)
- Test: `helao/deploy/hte/servers/galil_motion/tests/test_galil_motion_native.py` (append)
- Docs: `helao/deploy/hte/servers/galil_motion/README.md`

**Interfaces:**
- Consumes: Task 2 (`ErrorCodes.__str__ = str.__str__`) only for the README aligner-row correction in Step 6; no code dependency.
- Produces: the shared motion-timeout contract that Task 29 (Deployment-A thorlabs) must match exactly:
  - exception type `RuntimeError` (never `TimeoutError`/`asyncio.TimeoutError`);
  - message `f"motion timeout: axes {axis} not stopped after {self.motor_timeout} s"` (prefix exactly `"motion timeout: "`; `axis` is the list of requested, configured axis names; `self.motor_timeout` the configured `timeout`);
  - `stop_axis(axis)` is awaited before the raise; the busy flags are released by the existing `finally` blocks (`_motor_move` `:502-507` resets `motor_busy`, `motor_move` `:806-815` resets `blocked`), so no new release code is needed here.

Note: the spec's "Reset `motor_busy` in a `finally`" is already true on `origin/main`: `_motor_move` wraps `_motor_move_unguarded` in `try/finally: self.motor_busy = False` (`:500-507`) and every caller reaches `_motor_move_unguarded` only through it. Test (b) pins it.

- [ ] **Step 1: Write the failing test**

Append to `/tmp/claude-1000/wt-parent/helao/deploy/hte/servers/galil_motion/tests/test_galil_motion_native.py` (the file already defines `_drv`, `_move_responses`, `MOVE_CFG`, `_active`, and imports `asyncio`, `pytest`, `ErrorCodes`):

```python
# --------------------------------------------------------------------------
# catalog bugfixes H3: joint axis/d_mm filter, real timeout, scalar err_code
# --------------------------------------------------------------------------
def test_unconfigured_axis_is_dropped_with_its_distance():
    # x-only controller; "z" is unconfigured. x must get ITS distance:
    # 1.0 mm / 0.001 mm per count = 1000 counts (not z's 5.0 mm -> 5000).
    d, ch = _drv(responses=_move_responses(), config=dict(MOVE_CFG))
    d.connect()
    ch.commands.clear()
    out = asyncio.run(
        d._motor_move([5.0, 1.0], ["z", "x"], None, "absolute", "motorxy")
    )
    assert "PAA=1000" in ch.commands
    assert "PAA=5000" not in ch.commands
    assert out["supplied_rel_dist"] == [1.0]
    assert out["err_code"] == [ErrorCodes.none]


def test_only_unconfigured_axes_sends_no_move_and_does_not_raise():
    # Review Focus RF3: nothing left to move -> no SP/PA/PR/BG command (the
    # "PA ?" position query has no "="), no timeout raise, busy flag released.
    d, ch = _drv(responses=_move_responses(), config=dict(MOVE_CFG))
    d.connect()
    ch.commands.clear()
    out = asyncio.run(d._motor_move([5.0], ["z"], None, "absolute", "motorxy"))
    assert [c for c in ch.commands if "=" in c or c.startswith("BG")] == []
    assert out["err_code"] == []
    assert d.motor_busy is False


def test_move_still_running_at_deadline_halts_and_raises():
    # SC "0" == moving on every poll; the 0.01 s deadline passes during the
    # first 0.5 s poll sleep, so the loop exits without every axis stopped.
    d, ch = _drv(
        responses=_move_responses({"SC": "0"}), config=dict(MOVE_CFG, timeout=0.01)
    )
    d.connect()
    ch.commands.clear()
    params = {
        "d_mm": [1.0],
        "axis": ["x"],
        "mode": "absolute",
        "transformation": "motorxy",
    }
    with pytest.raises(RuntimeError, match="motion timeout"):
        asyncio.run(d.motor_move(_active(params)))
    assert "STA" in ch.commands  # halted before raising
    assert d.motor_busy is False and d.blocked is False  # next move accepted


def test_move_stopped_at_deadline_is_not_a_timeout():
    # SC "1" == stopped on the first poll: finishes none even with a tiny timeout
    d, ch = _drv(
        responses=_move_responses({"SC": "1"}), config=dict(MOVE_CFG, timeout=0.01)
    )
    d.connect()
    out = asyncio.run(d._motor_move([1.0], ["x"], None, "absolute", "motorxy"))
    assert out["err_code"] == [ErrorCodes.none]


def test_controller_disabled_mid_move_reports_not_available():
    # query_axis_moving answers a SCALAR not_available once galil_enabled is
    # False (galil_motion_native.py:400-401); the settle loop must not
    # character-index it ('n' != none -> timeout today).
    d, ch = _drv(responses=_move_responses(), config=dict(MOVE_CFG))
    d.connect()
    real_query = d.query_axis_moving

    async def _disabling_query(axis, *a, **k):
        d.galil_enabled = False
        return await real_query(axis, *a, **k)

    d.query_axis_moving = _disabling_query
    out = asyncio.run(d._motor_move([1.0], ["x"], None, "absolute", "motorxy"))
    assert out["err_code"] == [ErrorCodes.not_available]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/servers/galil_motion/tests/test_galil_motion_native.py -v -k "unconfigured or deadline or disabled_mid_move"`
Expected: 3 FAIL, 2 PASS:
- `test_unconfigured_axis_is_dropped_with_its_distance`: `AssertionError: assert 'PAA=1000' in [... 'PAA=5000', ...]`
- `test_move_still_running_at_deadline_halts_and_raises`: `Failed: DID NOT RAISE <class 'RuntimeError'>`
- `test_controller_disabled_mid_move_reports_not_available`: `[<ErrorCodes.timeout: 'timeout'>] == [<ErrorCodes.not_available: 'not_available'>]`
- `test_only_unconfigured_axes_sends_no_move_and_does_not_raise` and `test_move_stopped_at_deadline_is_not_a_timeout` PASS today: they are regression guards for the new raise path (an empty or stopped axis set must not raise).

- [ ] **Step 3: Write minimal implementation**

In `/tmp/claude-1000/wt-parent/helao/deploy/hte/servers/galil_motion/galil_motion_native.py`:

(1) `:29` delete `from copy import deepcopy` (its only use is the loop replaced in (2)).

(2) `:597-601` replace:

```python
        # remove not-configured axes
        for ax in deepcopy(axis):
            if ax not in self.axis_id:
                axis.pop(axis.index(ax))
```

with:

```python
        # drop not-configured axes together with their distances
        for ax in axis:
            if ax not in self.axis_id:
                LOGGER.warning(f"axis '{ax}' is not configured; dropped from the move")
        pairs = [(d, ax) for d, ax in zip(d_mm, axis) if ax in self.axis_id]
        d_mm = [d for d, _ in pairs]
        axis = [ax for _, ax in pairs]
```

(3) `:606-616` replace the dead branch:

```python
            if ax in self.axis_id:
                axl = self.axis_id[ax]
            else:
                ret_moved_axis.append(None)
                ret_speed.append(None)
                ret_accepted_rel_dist.append(None)
                ret_supplied_rel_dist.append(d)
                ret_err_dist.append(None)
                ret_err_code.append(ErrorCodes.setup)
                ret_counts.append(None)
                continue
```

with:

```python
            axl = self.axis_id[ax]
```

(4) `:702-721` replace:

```python
        qmove: dict = {"motor_status": [], "err_code": []}
        if not self._is_estopped():
            tstart = time.time()
            while (
                time.time() - tstart < self.motor_timeout
            ) and not self._is_estopped():
                qmove = await self.query_axis_moving(axis=axis)
                await asyncio.sleep(0.5)
                if all(status == "stopped" for status in qmove["motor_status"]):
                    break
            if not self._is_estopped():
                if time.time() - tstart > self.motor_timeout:
                    await self.stop_axis(axis)
                newret_err_code = []
                for erridx, err_code in enumerate(ret_err_code):
                    if qmove["err_code"][erridx] != ErrorCodes.none:
                        newret_err_code.append(ErrorCodes.timeout)
                    else:
                        newret_err_code.append(err_code)
                ret_err_code = newret_err_code
```

with:

```python
        qmove: dict = {"motor_status": [], "err_code": []}
        if not self._is_estopped():
            tstart = time.time()
            settled = False
            while (
                time.time() - tstart < self.motor_timeout
            ) and not self._is_estopped():
                qmove = await self.query_axis_moving(axis=axis)
                await asyncio.sleep(0.5)
                if all(status == "stopped" for status in qmove["motor_status"]):
                    settled = True
                    break
            if not self._is_estopped():
                if not settled:
                    # shared motion-timeout rule: halt, then raise so the
                    # orchestrator pauses and re-queues instead of E-STOPping;
                    # _motor_move/motor_move release motor_busy/blocked in finally
                    await self.stop_axis(axis)
                    raise RuntimeError(
                        f"motion timeout: axes {axis} not stopped after "
                        f"{self.motor_timeout} s"
                    )
                q_codes = qmove["err_code"]
                if not isinstance(q_codes, list):  # disabled mid-move: scalar
                    q_codes = [q_codes] * len(ret_err_code)
                ret_err_code = [
                    q_codes[i] if code == ErrorCodes.none and i < len(q_codes) else code
                    for i, code in enumerate(ret_err_code)
                ]
```

The `else: ret_err_code = [ErrorCodes.estop ...]` branches after it stay unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/servers/galil_motion/tests/test_galil_motion_native.py -v`
Expected: PASS (whole file: the new 5 plus the existing 41).
Regression: `cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/tests/test_motion_private_endpoints.py helao/hexagon/tests/test_motion_transform.py -q` → PASS.

- [ ] **Step 5: Mutation check**

```bash
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte diff -- servers/galil_motion/galil_motion_native.py > /tmp/claude-1000/mut-task7.patch && git -C /tmp/claude-1000/wt-parent/helao/deploy/hte apply -R /tmp/claude-1000/mut-task7.patch
cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/servers/galil_motion/tests/test_galil_motion_native.py -q -k "unconfigured or deadline or disabled_mid_move"
```
Expected: the same 3 FAIL as Step 2. Then `git -C /tmp/claude-1000/wt-parent/helao/deploy/hte apply /tmp/claude-1000/mut-task7.patch` and rerun → 5 PASS.

- [ ] **Step 6: README**

In `/tmp/claude-1000/wt-parent/helao/deploy/hte/servers/galil_motion/README.md` (line numbers in `galil_motion_native.py` shift after Step 3; re-derive every `galil_motion_native.py:` citation in the touched rows with `grep -n` on the edited file):
- Move result table, `supplied_rel_dist` row: meaning becomes `the requested distance of that axis; an axis not in `axis_id` is dropped together with its distance and logged as a WARNING`.
- Move result table, `err_code` row: replace the meaning with `ErrorCodes` value per axis: `none`, `numerical`, `motor`, or, when every axis reported `stopped`, the final `query_axis_moving` code for an axis whose move code was `none` (`unspecified` for an axis missing from the `SC` reply; `not_available` for every axis when the controller was disabled mid-move, where the query returns a scalar); `estop` for every axis if E-stopped. A move whose axes are not all `stopped` by `timeout` (config, default 60 s) is halted (`ST`) and the action raises `RuntimeError("motion timeout: ...")` instead of returning: no row is written, the request answers HTTP 500, and the orchestrator pauses and re-queues the move.` Cite the new `q_codes` comprehension line and the `raise RuntimeError` line.
- Move result paragraph `Data file ... one row` sentence: append `No row when the move times out (see above).`
- Aligner table, `err_code` row (per Task 2): meaning becomes `` `f"{errorcode}"`: `none` (submit, and "skip step", which writes the initial matrix, `helao/deploy/hte/layouts/aligner.py:1105`) or `stop` (stop). Rows written on Python >= 3.12 before `ErrorCodes.__str__` was fixed (`helao/core/error.py:8`) carry `ErrorCodes.none` / `ErrorCodes.stop`; readers must accept both spellings ``.
- `## Notes`: delete the three bullets that begin `- The aligner row's `err_code` is written with`, `- `move` never reports `timeout` for an axis still moving`, and `- The removal of unconfigured axes pops them from `axis``. Add one bullet: `- A move that times out raises `RuntimeError("motion timeout: ...")` after halting the axes (`helao/deploy/hte/servers/galil_motion/galil_motion_native.py:<raise line>`): the orchestrator pauses and re-queues the move (no E-STOP), and the raised action's server-side session stays open until the next server startup reconciles it (`helao/hexagon/app/action_host.py:1486-1505`).`

Guard: `cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/tests/test_readme_outputs.py -q` → PASS.

Review note: Task 29 implements the same rule in Deployment-A's thorlabs driver. Review Tasks 7 and 29 side by side (exception type, message prefix, halt-before-raise, busy release); they are pushed together.

- [ ] **Step 7: Commit (main session; subagents never commit)**

```bash
/home/dan/miniforge3/envs/helao/bin/black /tmp/claude-1000/wt-parent/helao/deploy/hte/servers/galil_motion/galil_motion_native.py /tmp/claude-1000/wt-parent/helao/deploy/hte/servers/galil_motion/tests/test_galil_motion_native.py
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte branch --show-current   # expect fix/catalog-bugfixes
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte status --short
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte add servers/galil_motion/galil_motion_native.py servers/galil_motion/tests/test_galil_motion_native.py servers/galil_motion/README.md
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte commit -m "fix(galil): raise on a real move timeout; drop unconfigured axes with their distances"
```

---

---

### Task 8: H4 PAL repeats and multi-run jobs get one action per palaction (hte)

**Files:**
- Modify: `helao/deploy/hte/servers/pal/pal_driver.py:535`
- Test: `helao/deploy/hte/tests/test_pal_golden_master.py` (script, run with `python <file>`; scenario c check at `:1118`, new scenario j)
- Docs: `helao/deploy/hte/servers/pal/README.md:69`, `:98`, `:138-140`

**Interfaces:**
- Consumes: none (independent of Tasks 1-7)
- Produces: none

Paths in this task: `WT=/tmp/claude-1000/wt-parent`, `H=$WT/helao/deploy/hte`, `PY=/home/dan/miniforge3/envs/helao/bin/python`.

Expected values (independent of the fix): one action per palaction, so `split_count == palactions - 1`. Scenario c has 1 microcam with `repeat: 2` = 3 palactions -> 2 splits. Scenario j has `totalruns: 2` x 2 microcams = 4 palactions -> 3 splits (today: 2, one per run at `i == 1`).

Already checked while writing this plan: `tests/test_pal_ioloop_c1_guard.py` sets `IO_action_run_counter = 0` (`:107`) but asserts no split count; `servers/pal/tests/*.py` contain no split-count assertion (the only `split` hits are the word "4-way split" in `test_pal_driver_api.py` docstrings). No edits there.

- [ ] **Step 1: Write the failing test**

Edit `$H/tests/test_pal_golden_master.py`: add scenario j after `_scenario_i`, change the scenario c check, add the j checks, and bump the banner. Exact patch (save as `/tmp/claude-1000/task8-test.patch`, then `git -C $H apply /tmp/claude-1000/task8-test.patch`):

```diff
diff --git a/tests/test_pal_golden_master.py b/tests/test_pal_golden_master.py
index c14ecd3..446021c 100644
--- a/tests/test_pal_golden_master.py
+++ b/tests/test_pal_golden_master.py
@@ -1096,6 +1096,42 @@ async def _scenario_i():
 # ---------------------------------------------------------------------------
 
 
+async def _scenario_j():
+    """(j) totalruns=2 x 2 microcams: one action per palaction -> 3 splits."""
+    trace = []
+    shim = RecordingShim(trace)
+    shim.seed_custom(
+        "src_j", _liquid("src_j__liquid", "j1", volume_ml=8.0, position="src_j")
+    )
+    shim.allow_dest("dst_j")
+    pal = _make_pal(shim)
+    base = _make_base(trace)
+    microcam = {
+        "method": "transfer_custom_custom",
+        "tool": "LS1",
+        "volume_ul": 50,
+        "requested_source": {"position": "src_j"},
+        "requested_dest": {"position": "dst_j"},
+        "wash1": 0,
+        "wash2": 0,
+        "wash3": 0,
+        "wash4": 0,
+    }
+    A = _make_action(
+        "PAL_arbitrary",
+        {
+            "totalruns": 2,
+            "sampleperiod": [0.0, 0.0],
+            "spacingmethod": "linear",
+            "spacingfactor": 1.0,
+            "timeoffset": 0.0,
+            "microcams": [dict(microcam), dict(microcam)],
+        },
+        "scenario-j",
+    )
+    return await _drive_single_job(pal, base, "build_palcam_arbitrary", A)
+
+
 def _check(cond, msg, failures):
     if not cond:
         failures.append(msg)
@@ -1115,7 +1151,11 @@ async def _run_and_check() -> list:
 
     c = await _scenario_c()
     _check(c["final"]["finished"], "c: action did not finish", failures)
-    _check(c["final"]["split_count"] == 0, "c: repeat must not split", failures)
+    _check(
+        c["final"]["split_count"] == 2,
+        "c: each repeat must get its own split action (3 palactions -> 2 splits)",
+        failures,
+    )
     append_calls = [
         e
         for e in c["trace"]
@@ -1197,6 +1237,14 @@ async def _run_and_check() -> list:
         failures,
     )
 
+    j = await _scenario_j()
+    _check(j["final"]["finished"], "j: action did not finish", failures)
+    _check(
+        j["final"]["split_count"] == 3,
+        "j: 2 runs x 2 microcams = 4 palactions -> 3 splits",
+        failures,
+    )
+
     return failures
 
 
@@ -1207,7 +1255,7 @@ def main():
         for f in failures:
             print(f"  - {f}")
         raise SystemExit(1)
-    print("ALL 9 SCENARIO CHECKS PASSED (a-i)")
+    print("ALL 10 SCENARIO CHECKS PASSED (a-j)")
 
 
 if __name__ == "__main__":

```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python helao/deploy/hte/tests/test_pal_golden_master.py 2>&1 | tail -4`
Expected: FAIL, exit 1, with exactly these two lines under `SCENARIO CHECKS FAILED:`
```
  - c: each repeat must get its own split action (3 palactions -> 2 splits)
  - j: 2 runs x 2 microcams = 4 palactions -> 3 splits
```

- [ ] **Step 3: Write minimal implementation**

`$H/servers/pal/pal_driver.py:535` (inside `_sendcommand_main`, the `for palaction in microcam.run:` loop). Restore the pre-cf1f5c45 guard; `IO_action_run_counter` is reset per job at `:962` and incremented after each palaction at `:633`.

```python
# before
                if i > 0:
                    _ = await job.active.split()
# after
                if self.IO_action_run_counter > 0:
                    _ = await job.active.split()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python helao/deploy/hte/tests/test_pal_golden_master.py 2>&1 | tail -1`
Expected: `ALL 10 SCENARIO CHECKS PASSED (a-j)`

Run: `cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/tests/test_pal_ioloop_c1_guard.py helao/deploy/hte/servers/pal/tests -q`
Expected: PASS (no failures).

- [ ] **Step 5: Mutation check**

```bash
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte diff -- servers/pal/pal_driver.py > /tmp/claude-1000/mut-task8.patch
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte apply -R /tmp/claude-1000/mut-task8.patch
cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python helao/deploy/hte/tests/test_pal_golden_master.py 2>&1 | tail -3   # expect the c and j failures of Step 2
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte apply /tmp/claude-1000/mut-task8.patch
cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python helao/deploy/hte/tests/test_pal_golden_master.py 2>&1 | tail -1   # expect ALL 10 ... PASSED
```

- [ ] **Step 6: README**

`$H/servers/pal/README.md` (the line count of `pal_driver.py` is unchanged, so no citation moves):

1. Line 69, replace the sentence
   `For every run of every micro-method after the first (`i > 0`) the action is split first (`job.active.split()`, once per run, inside the run loop, `helao/deploy/hte/servers/pal/pal_driver.py:535-536`), so each such run lands in its own split action and file; all runs (repeats, `repeat` at `helao/deploy/hte/servers/pal/models.py:172`, looped at `helao/deploy/hte/servers/pal/pal_reconciliation.py:1047`) of the first micro-method share the original action and file.`
   with
   `Before every run except the job's first (`IO_action_run_counter > 0`; the counter is reset per job at `helao/deploy/hte/servers/pal/pal_driver.py:962` and incremented after each run at `helao/deploy/hte/servers/pal/pal_driver.py:633`) the action is split (`job.active.split()`, `helao/deploy/hte/servers/pal/pal_driver.py:535-536`), so every run -- each repeat (`repeat` at `helao/deploy/hte/servers/pal/models.py:172`, looped at `helao/deploy/hte/servers/pal/pal_reconciliation.py:1047`) of each micro-method in each of the job's `totalruns` -- lands in its own action and file; only the job's first run uses the original action and file.`
2. Line 98, replace
   `so a split action's record holds only its run's samples, and the original action, which also covers every repeat of the first micro-method, keeps only the last of those repeats' samples while its data file has a row per repeat (see Notes).`
   with
   `so each action's record holds exactly its one run's samples.`
3. Delete lines 138-140 (the `## Notes` heading, the blank line after it, and its only bullet `- Repeats of the first micro-method are not split ...`), leaving the file ending after the last `## Outputs` paragraph with a single trailing newline.

Run: `cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/tests/test_readme_outputs.py -q`
Expected: PASS.

- [ ] **Step 7: Commit (main session; subagents never commit)**

```bash
/home/dan/miniforge3/envs/helao/bin/black /tmp/claude-1000/wt-parent/helao/deploy/hte/servers/pal/pal_driver.py /tmp/claude-1000/wt-parent/helao/deploy/hte/tests/test_pal_golden_master.py
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte branch --show-current   # expect fix/catalog-bugfixes
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte status --short
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte add servers/pal/pal_driver.py tests/test_pal_golden_master.py servers/pal/README.md
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte commit -m "fix(pal): split before every palaction after the first, as before cf1f5c45"
```

---

---

### Task 9: H5a analyses `output_type` tags, aggregation window, scalar fallback (hte)

**Files:**
- Modify: `helao/deploy/hte/servers/analysis/analyses/uvis_bkgsubnorm.py:16,22,25,215,349-384,405`
- Modify: `helao/deploy/hte/servers/analysis/analyses/echeuvis_stability.py:18,28,139 (new helper after `refadjust`),367,583-642,714`
- Create: `helao/deploy/hte/tests/test_uvis_analysis_export.py`
- Docs: `helao/deploy/hte/servers/analysis/README.md`

**Interfaces:**
- Consumes: none
- Produces: `echeuvis_stability.last_secs_start(ep, skip: int, secs: float) -> int` (index into the unsliced frame array; raises `ValueError` when `skip` leaves no frames); `DryUvisOutputs` and `EcheUvisOutputs` subclass `helao.core.models.analysis.AnalysisOutput`; tags `"spectrum.uvis_bkgsubnorm_ref"` and `"spectrum.echeuvis_stability"`. Task 10 builds on these exact files (its patch context assumes this task's result after `black`).

Expected values (independent of the fix): frame k of every spectrum = k (light refs k + 100), epochs 0..9 s, `skip_first_n=4`, `agg_last_secs=2`. Frames past the first 4 and within 2 s of the last epoch are 7, 8, 9 -> every aggregate = 8.0 (light 108.0). Today the index into `ep[4:]` is applied to the unsliced array, so frames 3..9 -> 6.0. Short in-situ: 3 frames (epochs 0..2) < `skip_first_n`; the whole vector spans 2 s <= `agg_last_secs`, so the fallback averages frames 0, 1, 2 -> 1.0; today the fallback calls `np.where` on a 0-d value and raises `ValueError`.

- [ ] **Step 1: Write the failing test**

Create `$H/tests/test_uvis_analysis_export.py`:

```python
"""uvis_bkgsubnorm / echeuvis_stability: output tag, aggregation window, fallback.

Frame k of every spectrum holds the value k (light references k + 100), epochs
0..9 s. With skip_first_n=4 and agg_last_secs=2 the window is the frames whose
epoch is within 2 s of the last one and past the first 4: frames 7, 8, 9, so
every aggregate is mean(7, 8, 9) = 8.0 (light: 108.0).
"""

from types import SimpleNamespace

import numpy as np

from helao.deploy.hte.servers.analysis.analyses import echeuvis_stability as eche
from helao.deploy.hte.servers.analysis.analyses import uvis_bkgsubnorm as dry

WL = np.linspace(400.0, 800.0, 60)
PARAMS = {
    "lower_wl": 420,
    "upper_wl": 780,
    "window_length": 5,
    "poly_order": 2,
    "skip_first_n": 4,
    "agg_last_secs": 2,
    "agg_method": "mean",
}


def _hlo(epochs, values):
    """Spectrometer payload: frame i has every channel equal to values[i]."""
    data = {"epoch_s": [float(e) for e in epochs]}
    data.update({f"ch_{i:03d}": [float(v) for v in values] for i in range(len(WL))})
    return {"meta": {"optional": {"wl": WL.tolist()}}, "data": data}


def _ramp(offset=0.0, n=10):
    return _hlo(np.arange(float(n)), np.arange(float(n)) + offset)


def test_dry_window_is_last_secs_after_skip():
    ana = object.__new__(dry.DryUvisAnalysis)
    ana.analysis_params = {**dry.ANALYSIS_DEFAULTS, **PARAMS}
    ana.inputs = SimpleNamespace(
        ref_dark_spec=[_ramp()],
        ref_light_spec=[_ramp(100.0)],
        insitu_spec=_ramp(),
    )
    assert ana.calc_output() is True
    assert ana.outputs.agg_insitu[0] == 8.0
    assert ana.outputs.mean_ref_dark[0] == 8.0
    assert ana.outputs.mean_ref_light[0] == 108.0
    assert ana.outputs.output_type == "spectrum.uvis_bkgsubnorm_ref"


def test_eche_window_is_last_secs_after_skip():
    ana = object.__new__(eche.EcheUvisAnalysis)
    ana.analysis_params = {**eche.ANALYSIS_DEFAULTS, **PARAMS}
    ana.inputs = SimpleNamespace(
        baseline_spec=_ramp(), insitu_spec=_ramp(), presitu_spec=_ramp()
    )
    assert ana.calc_output() is True
    out = ana.outputs
    assert (out.agg_baseline[0], out.agg_insitu[0], out.agg_presitu[0]) == (
        8.0,
        8.0,
        8.0,
    )
    assert out.output_type == "spectrum.echeuvis_stability"


def test_eche_short_insitu_falls_back_to_whole_epoch_vector():
    # 3 frames (epochs 0..2) are fewer than skip_first_n=4; the whole vector
    # spans 2 s <= agg_last_secs, so the fallback averages frames 0, 1, 2 -> 1.0
    ana = object.__new__(eche.EcheUvisAnalysis)
    ana.analysis_params = {**eche.ANALYSIS_DEFAULTS, **PARAMS}
    ana.inputs = SimpleNamespace(
        baseline_spec=_ramp(), insitu_spec=_ramp(n=3), presitu_spec=_ramp()
    )
    assert ana.calc_output() is True
    assert ana.outputs.agg_insitu[0] == 1.0

```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/tests/test_uvis_analysis_export.py -v`
Expected: 3 FAIL: `test_dry_window_is_last_secs_after_skip` with `assert np.float64(6.0) == 8.0`; `test_eche_window_is_last_secs_after_skip` with `assert (np.float64(6.0), ...) == (8.0, 8.0, 8.0)`; `test_eche_short_insitu_falls_back_to_whole_epoch_vector` with `ValueError: Calling nonzero on 0d arrays is not allowed`.

- [ ] **Step 3: Write minimal implementation**

Apply exactly this patch to the hte worktree (save as `/tmp/claude-1000/task9.patch`, then `git -C /tmp/claude-1000/wt-parent/helao/deploy/hte apply /tmp/claude-1000/task9.patch`). It: drops the unused `pydantic.BaseModel` import; imports `AnalysisOutput`; adds `last_secs_start` after `refadjust` in `echeuvis_stability.py`; makes both `*Outputs` subclass `AnalysisOutput` and passes their `output_type`; replaces the six window slices with `last_secs_start`; and makes both fallbacks use the whole epoch vector (`itup[1]`/`ptup[1]`, not the scalar `itup[1][0]`). The `noagg_*` slices (`[skip_first_n:]`) are already right and stay.

```diff
--- a/servers/analysis/analyses/uvis_bkgsubnorm.py
+++ b/servers/analysis/analyses/uvis_bkgsubnorm.py
@@ -13,16 +13,15 @@
 
 import numpy as np
 import pandas as pd
-from pydantic import BaseModel
 from scipy.signal import savgol_filter
 from scipy.stats import binned_statistic
 
 from helao.core.drivers.data.analyses.base_analysis import BaseAnalysis
 from helao.core.drivers.data.loaders.helao_loader import HelaoAction, HelaoProcess
-from helao.core.models.analysis import AnalysisDataModel, AnalysisInput
+from helao.core.models.analysis import AnalysisDataModel, AnalysisInput, AnalysisOutput
 from helao.core.version import get_filehash
 
-from .echeuvis_stability import parse_spechlo, refadjust
+from .echeuvis_stability import last_secs_start, parse_spechlo, refadjust
 
 ANALYSIS_DEFAULTS = {
     "ev_parts": [1.8, 2.2, 2.6, 3.0],
@@ -212,7 +211,7 @@
         return inputs
 
 
-class DryUvisOutputs(BaseModel):
+class DryUvisOutputs(AnalysisOutput):
     """Output payload for :class:`DryUvisAnalysis`.
 
     Attributes:
@@ -346,42 +345,19 @@
         wlindlo = np.where(wl > ap["lower_wl"])[0].min()
         wlindhi = np.where(wl < ap["upper_wl"])[0].max()
 
+        skip, secs = ap["skip_first_n"], ap["agg_last_secs"]
         # mean aggregate initial and final reference dark spectra
         mean_ref_dark = np.vstack(
-            [
-                arr[
-                    np.where(
-                        (ep[ap["skip_first_n"] :] - ep.max()) >= -ap["agg_last_secs"]
-                    )[0].min() :
-                ]
-                for wl, ep, arr in rdtups
-            ]
+            [arr[last_secs_start(ep, skip, secs) :] for wl, ep, arr in rdtups]
         ).mean(axis=0)
 
         # mean aggregate initial and final reference light spectra
         mean_ref_light = np.vstack(
-            [
-                arr[
-                    np.where(
-                        (ep[ap["skip_first_n"] :] - ep.max()) >= -ap["agg_last_secs"]
-                    )[0].min() :
-                ]
-                for wl, ep, arr in rltups
-            ]
+            [arr[last_secs_start(ep, skip, secs) :] for wl, ep, arr in rltups]
         ).mean(axis=0)
 
-        # aggregate baseline insitu OCV spectra over final t seconds, omitting first n
-        agg_insitu = aggfunc(
-            [
-                arr[
-                    np.where(
-                        (ep[ap["skip_first_n"] :] - ep.max()) >= -ap["agg_last_secs"]
-                    )[0].min() :
-                ]
-                for wl, ep, arr in (btup,)
-            ][0],
-            axis=0,
-        )
+        # aggregate the sample spectra over final t seconds, omitting first n
+        agg_insitu = aggfunc(btup[2][last_secs_start(btup[1], skip, secs) :], axis=0)
 
         inds = range(len(wl[wlindlo:wlindhi]))
         nbins = np.round(len(wl[wlindlo:wlindhi]) / ap["bin_width"]).astype(int)
@@ -403,6 +379,7 @@
 
         # create output model
         self.outputs = DryUvisOutputs(
+            output_type="spectrum.uvis_bkgsubnorm_ref",
             wavelength=list(wl),
             lower_wl_idx=wlindlo,
             upper_wl_idx=wlindhi,

--- a/servers/analysis/analyses/echeuvis_stability.py
+++ b/servers/analysis/analyses/echeuvis_stability.py
@@ -15,7 +15,6 @@
 
 import numpy as np
 import pandas as pd
-from pydantic import BaseModel
 from scipy.signal import savgol_filter
 from scipy.stats import binned_statistic
 
@@ -25,7 +24,7 @@
 LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
 from helao.core.drivers.data.analyses.base_analysis import BaseAnalysis
 from helao.core.drivers.data.loaders.helao_loader import HelaoAction, HelaoProcess
-from helao.core.models.analysis import AnalysisDataModel, AnalysisInput
+from helao.core.models.analysis import AnalysisDataModel, AnalysisInput, AnalysisOutput
 from helao.core.models.run_use import RunUse
 
 ANALYSIS_DEFAULTS = {
@@ -139,6 +138,14 @@
     return min_rescaled, max_rescaled, w
 
 
+def last_secs_start(ep, skip: int, secs: float) -> int:
+    """First frame index, into the UNSLICED frame array, past ``skip`` and inside the last ``secs``.
+
+    Raises ``ValueError`` when ``skip`` leaves no frames.
+    """
+    return skip + np.where((ep[skip:] - ep.max()) >= -secs)[0].min()
+
+
 class EcheUvisInputs(AnalysisInput):
     """Resolved baseline/in-situ/pre-situ processes and actions for one sample.
 
@@ -364,7 +371,7 @@
         return inputs
 
 
-class EcheUvisOutputs(BaseModel):
+class EcheUvisOutputs(AnalysisOutput):
     """Per-sample output payload for :class:`EcheUvisAnalysis`.
 
     Attributes:
@@ -580,27 +587,14 @@
         #     ]
         # ).mean(axis=0)
 
+        skip, secs = ap["skip_first_n"], ap["agg_last_secs"]
         # aggregate baseline insitu OCV spectra over final t seconds, omitting first n
-        agg_baseline = aggfunc(
-            btup[2][
-                np.where(
-                    (btup[1][ap["skip_first_n"] :] - btup[1].max())
-                    >= -ap["agg_last_secs"]
-                )[0].min() :
-            ],
-            axis=0,
-        )
+        agg_baseline = aggfunc(btup[2][last_secs_start(btup[1], skip, secs) :], axis=0)
 
         # aggregate insitu CA spectra over final t seconds, omitting first n
         try:
             agg_insitu = aggfunc(
-                itup[2][
-                    np.where(
-                        (itup[1][ap["skip_first_n"] :] - itup[1].max())
-                        >= -ap["agg_last_secs"]
-                    )[0].min() :
-                ],
-                axis=0,
+                itup[2][last_secs_start(itup[1], skip, secs) :], axis=0
             )
         except Exception:
             LOGGER.warning(
@@ -608,24 +602,14 @@
                 exc_info=True,
             )
             agg_insitu = aggfunc(
-                itup[2][
-                    np.where((itup[1][0] - itup[1].max()) >= -ap["agg_last_secs"])[
-                        0
-                    ].min() :
-                ],
+                itup[2][np.where((itup[1] - itup[1].max()) >= -secs)[0].min() :],
                 axis=0,
             )
 
         # aggregate presitu OCV spectra over final t seconds, omitting first n
         try:
             agg_presitu = aggfunc(
-                ptup[2][
-                    np.where(
-                        (ptup[1][ap["skip_first_n"] :] - ptup[1].max())
-                        >= -ap["agg_last_secs"]
-                    )[0].min() :
-                ],
-                axis=0,
+                ptup[2][last_secs_start(ptup[1], skip, secs) :], axis=0
             )
         except Exception:
             LOGGER.warning(
@@ -633,11 +617,7 @@
                 exc_info=True,
             )
             agg_presitu = aggfunc(
-                ptup[2][
-                    np.where((ptup[1][0] - ptup[1].max()) >= -ap["agg_last_secs"])[
-                        0
-                    ].min() :
-                ],
+                ptup[2][np.where((ptup[1] - ptup[1].max()) >= -secs)[0].min() :],
                 axis=0,
             )
 
@@ -712,6 +692,7 @@
 
         # create output model
         self.outputs = EcheUvisOutputs(
+            output_type="spectrum.echeuvis_stability",
             wavelength=list(wl),
             lower_wl_idx=wlindlo,
             upper_wl_idx=wlindhi,

```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/tests/test_uvis_analysis_export.py helao/deploy/hte/tests/test_echeuvis_presitu_arrays.py helao/deploy/hte/tests/test_low_w3_hte_fixes.py helao/deploy/hte/servers/analysis/tests/test_analysis_resolution.py -q`
Expected: PASS (all).

- [ ] **Step 5: Mutation check**

```bash
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte diff -- servers/analysis/analyses/uvis_bkgsubnorm.py servers/analysis/analyses/echeuvis_stability.py > /tmp/claude-1000/mut-task9.patch
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte apply -R /tmp/claude-1000/mut-task9.patch
cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/tests/test_uvis_analysis_export.py -q   # expect 3 failed, same reasons as Step 2
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte apply /tmp/claude-1000/mut-task9.patch
cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/tests/test_uvis_analysis_export.py -q   # expect 3 passed
```

- [ ] **Step 6: README**

First re-point the citations the code edit moved. Write this helper once (it is reused by Tasks 10 and 12; it lives in scratch, never in a repo):

```python
"""Re-point `<path>.py:<line>` citations in a README after an edit moved lines.

usage: recite.py <repo> <README> <rev> <path.py> [<path.py> ...]
For each single-line cite of a listed file, the cited line's text at <rev> is
looked up in the working-tree file; a unique match rewrites the number.
Anything not unique is printed and left alone (fix those by hand).
"""

import re
import subprocess
import sys
from pathlib import Path

repo, readme, rev, *paths = sys.argv[1:]
text = Path(readme).read_text(encoding="utf-8")
for rel in paths:
    old = subprocess.run(
        ["git", "-C", repo, "show", f"{rev}:{rel}"],
        check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    new = (Path(repo) / rel).read_text(encoding="utf-8").splitlines()
    full = f"helao/deploy/hte/{rel}"

    def fix(m):
        n = int(m.group(1))
        want = old[n - 1].strip()
        hits = [i + 1 for i, line in enumerate(new) if line.strip() == want]
        if len(hits) != 1:
            print(f"UNRESOLVED {rel}:{n} {want!r} -> {hits}")
            return m.group(0)
        return f"{full}:{hits[0]}"

    text = re.sub(re.escape(full) + r":(\d+)(?![\d-])", fix, text)
Path(readme).write_text(text, encoding="utf-8")

```

Save it as `/tmp/claude-1000/recite.py`, then run (HEAD is still the pre-edit commit):

```bash
cd /tmp/claude-1000/wt-parent/helao/deploy/hte && /home/dan/miniforge3/envs/helao/bin/python /tmp/claude-1000/recite.py . servers/analysis/README.md HEAD servers/analysis/analyses/uvis_bkgsubnorm.py servers/analysis/analyses/echeuvis_stability.py
```
Expected output: exactly two `UNRESOLVED` lines, for `uvis_bkgsubnorm.py:215` (`class DryUvisOutputs(BaseModel):`) and `echeuvis_stability.py:367` (`class EcheUvisOutputs(BaseModel):`). Fix those two by hand: `uvis_bkgsubnorm.py:215` -> `uvis_bkgsubnorm.py:214` and `echeuvis_stability.py:367` -> `echeuvis_stability.py:374` (check with `grep -n "^class DryUvisOutputs\|^class EcheUvisOutputs" servers/analysis/analyses/*.py`; expected 214 and 374).

Then edit `$H/servers/analysis/README.md` (line numbers below are as of origin/main; the edits do not add or remove lines before the Notes):

1. `uvis_bkgsubnorm` table (after the header row at `:48`): insert as the first data row
   `| `output_type` | str | scalar | none | always `spectrum.uvis_bkgsubnorm_ref` | `helao/deploy/hte/servers/analysis/analyses/uvis_bkgsubnorm.py:382` |`
2. Row `mean_ref_dark` (`:52`): meaning becomes `per-pixel mean of the frames past the first `skip_first_n` whose epoch is within `agg_last_secs` of the last frame (`last_secs_start`, `helao/deploy/hte/servers/analysis/analyses/echeuvis_stability.py:141`), then averaged over the dark references`.
3. Row `agg_insitu` (`:55`): meaning becomes `per-pixel `agg_method` over the frames past the first `skip_first_n` whose epoch is within `agg_last_secs` of the last frame (`last_secs_start`, `helao/deploy/hte/servers/analysis/analyses/echeuvis_stability.py:141`)`.
4. S3 artifacts rows `scalar` and `array` (`:67`, `:68`): the `output_type` cell `none: the outputs model has no `output_type` (see Notes)` becomes `` `spectrum.uvis_bkgsubnorm_ref` `` in both rows; in the `scalar` row's artifact cell append `(includes `output_type`)`.
5. Delete the paragraph at `:73` (`As shipped, neither outputs model carries an `output_type` attribute, ...`) and the blank line after it.
6. `echeuvis_stability` table (header at `:82`): insert as the first data row
   `| `output_type` | str | scalar | none | always `spectrum.echeuvis_stability` | `helao/deploy/hte/servers/analysis/analyses/echeuvis_stability.py:695` |`
7. Row `agg_baseline` (`:89`): meaning becomes `per-pixel `agg_method` of the baseline frames past the first `skip_first_n` whose epoch is within `agg_last_secs` of the last frame (`last_secs_start`, `helao/deploy/hte/servers/analysis/analyses/echeuvis_stability.py:141`)`.
8. Row `agg_insitu` (`:90`): meaning becomes `in-situ CA spectrum, same window rule; when `skip_first_n` leaves no frames, a WARNING is logged and the window is the frames within `agg_last_secs` of the last one, counted over all frames`.
9. Row `agg_presitu` (`:91`): meaning becomes `post-CA OCV spectrum, same window rule and fallback`.
10. `:121`: `with the same `output_type` caveat and the same shipping path` becomes `with `output_type` `spectrum.echeuvis_stability` and the same shipping path`.
11. `## Notes`: delete the two bullets starting `- Neither `DryUvisOutputs` nor `EcheUvisOutputs` has an `output_type` field` (`:127`) and `- Aggregation window index mismatch:` (`:128`).

Run: `cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/tests/test_readme_outputs.py -q`
Expected: PASS.

- [ ] **Step 7: Commit (main session; subagents never commit)**

```bash
/home/dan/miniforge3/envs/helao/bin/black /tmp/claude-1000/wt-parent/helao/deploy/hte/servers/analysis/analyses/uvis_bkgsubnorm.py /tmp/claude-1000/wt-parent/helao/deploy/hte/servers/analysis/analyses/echeuvis_stability.py /tmp/claude-1000/wt-parent/helao/deploy/hte/tests/test_uvis_analysis_export.py
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte branch --show-current   # expect fix/catalog-bugfixes
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte status --short
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte add servers/analysis/analyses/uvis_bkgsubnorm.py servers/analysis/analyses/echeuvis_stability.py tests/test_uvis_analysis_export.py servers/analysis/README.md
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte commit -m "fix(analysis): uvis output_type tags, aggregation window, whole-vector fallback"
```

---

---

### Task 10: H5b port `uvis_bkgsubnorm` / `echeuvis_stability` to the LocalLoader contract (hte)

**Files:**
- Modify: `helao/deploy/hte/servers/analysis/analyses/echeuvis_stability.py` (new `local_frame`; `EcheUvisInputs.__init__`; `EcheUvisAnalysis.select_process_uuids` + `__init__`; delete `SDCUVIS_QUERY`)
- Modify: `helao/deploy/hte/servers/analysis/analyses/uvis_bkgsubnorm.py` (`DryUvisInputs.__init__`; `DryUvisAnalysis.select_process_uuids` + `__init__`; delete `DRYUVIS_QUERY`)
- Test: `helao/deploy/hte/tests/test_uvis_analysis_export.py` (extend)
- Docs: `helao/deploy/hte/servers/analysis/README.md`

**Interfaces:**
- Consumes: Task 9's `last_secs_start`, `DryUvisOutputs`/`EcheUvisOutputs` with `output_type`.
- Consumes (core, unchanged): `LocalLoader(data_path)` with `.processes` (`process_uuid: UUID`, `experiment_name`), `.get_prc(index) -> HelaoProcess`, `.resolve_action(action_uuid, action_output_dir) -> HelaoAction` (`helao/core/drivers/data/loaders/localfs.py:183`, `:629`, `:508`); `HelaoAction.hlo -> HloPayload` (`{"meta", "data"}`), `.hlo_file_tup`; the driver contract `ana_func(process_uuid, local_loader, analysis_params)` and `cls.select_process_uuids(local_loader)` (`helao/core/drivers/data/analysis_driver.py:1161`, `:1273`); `BaseAnalysis.gen_uuid` reads `self.run_use`, which neither class set before (so `gen_uuid` could never have run).
- Produces: `echeuvis_stability.local_frame(local_loader) -> pd.DataFrame` with columns `process_uuid, run_use, experiment_name, global_label, action_uuid, action_name, action_timestamp, prc, act` (one row per dispatched action); `DryUvisInputs(insitu_process_uuid, frame)`, `EcheUvisInputs(insitu_process_uuid, frame)`; `DryUvisAnalysis(process_uuid, local_loader, analysis_params)`, `EcheUvisAnalysis(process_uuid, local_loader, analysis_params)`; `select_process_uuids` = `run_use == "data"` processes that dispatched `acquire_spec_adv` (dry) or `run_CA` (eche). Task 11 wires these routes (`analyze_uvis_bkgsubnorm`, `analyze_echeuvis_stability`) into eche10.

Design notes (no user decision needed; they follow from the old DB query semantics):
- `plate_id`/`sample_no` (DB columns) are gone; the sample identity is the process's first `samples_in` `global_label`, which also replaces the `legacy__solid__<plate>_<sample>` fallback label in `get_datamodels`.
- The dry inputs take every `ref_dark`/`ref_light` acquisition of the sequence (as the old `sdf.query("run_use=='ref_dark'")` did) and the target process's own acquisition.
- The eche inputs keep the old index rules (preceding OCV, its preceding spectrum, the sample's first OCV experiment as baseline) on the per-action frame.
- `ca_potential_vrhe` becomes `process_params.get("CA_potential_vsRHE")`: a CA process record need not carry it, and a missing key must not abort the analysis.

Expected values: the trees below are written by the test; the expected uuids are the ones the test wrote (dry: the two `run_use == "data"` processes, not the two references; eche: the CA process only, not the OCV process). Today `select_process_uuids` is the base-class default (every process) and the constructors call `query_df.query`, so `AttributeError: 'LocalLoader' object has no attribute 'query'`.

- [ ] **Step 1: Write the failing test**

In `$H/tests/test_uvis_analysis_export.py`, replace the import block

```python
from types import SimpleNamespace

import numpy as np

from helao.deploy.hte.servers.analysis.analyses import echeuvis_stability as eche
from helao.deploy.hte.servers.analysis.analyses import uvis_bkgsubnorm as dry
```
with
```python
import itertools
import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from helao.core.drivers.data.loaders.localfs import LocalLoader
from helao.deploy.hte.servers.analysis.analyses import echeuvis_stability as eche
from helao.deploy.hte.servers.analysis.analyses import uvis_bkgsubnorm as dry
```

and append to the end of the file:

```python
# ---------------------------------------------------------------------------
# LocalLoader contract: a sequence tree written in tmp_path, read
# through LocalLoader -> select_process_uuids -> constructor -> export.
# Layout follows helao/core/tests/test_loader_parity.py::_record.
# ---------------------------------------------------------------------------


ECHE_PARAMS = {**PARAMS, "skip_first_n": 1}


def _write_hlo(path: Path, payload: dict) -> None:
    """Legacy ``.hlo``: YAML header, ``%%``, one JSON data line (lists per key)."""
    wl = json.dumps(payload["meta"]["optional"]["wl"])
    body = json.dumps(payload["data"])
    path.write_text(f"optional:\n  wl: {wl}\n%%\n{body}\n", encoding="utf-8")


def _sequence(tmp_path: Path, seq_name: str, experiments: list) -> tuple:
    """Write one sequence and return ``(seq_dir, [process uuid, ...])``.

    ``experiments`` is ``[(experiment_name, [process, ...]), ...]`` in run
    order; a process is ``{"run_use", "label", "params", "actions"}`` with
    ``actions`` a list of ``(action_name, hlo payload or None)``. Every record
    gets a later timestamp than the one before it.
    """
    tick = itertools.count(1)
    seq_dir = tmp_path / "RUNS" / "2026" / "0925" / f"090000__{seq_name}__lab"
    seq_dir.mkdir(parents=True)
    (seq_dir / "20260925.090000000000-seq.yml").write_text(
        json.dumps({"sequence_name": seq_name}), encoding="utf-8"
    )
    puuids = []
    for exp_name, processes in experiments:
        ets = f"20260925.09{next(tick):04d}000000"
        exp_dir = seq_dir / f"{ets}__{exp_name}"
        exp_dir.mkdir()
        (exp_dir / f"{ets}-exp.yml").write_text(
            json.dumps({"experiment_name": exp_name}), encoding="utf-8"
        )
        for pidx, proc in enumerate(processes):
            puuid = str(uuid.uuid4())
            abbr, files = [], []
            for action_name, payload in proc["actions"]:
                n = next(tick)
                act_dir = exp_dir / f"{n}__0__SRV__{action_name}"
                act_dir.mkdir()
                auuid = str(uuid.uuid4())
                act_files = []
                if payload is not None:
                    fd = {
                        "file_name": "spec.hlo",
                        "file_type": "spec_helao__file",
                        "data_keys": sorted(payload["data"]),
                    }
                    _write_hlo(act_dir / "spec.hlo", payload)
                    act_files.append(fd)
                    files.append(dict(fd, action_uuid=auuid, run_use=proc["run_use"]))
                (act_dir / f"20260925.09{n:04d}000000-act.yml").write_text(
                    json.dumps(
                        {
                            "action_name": action_name,
                            "action_uuid": auuid,
                            "action_timestamp": f"2026-09-25T09:{n // 60:02d}:{n % 60:02d}",
                            "files": act_files,
                        }
                    ),
                    encoding="utf-8",
                )
                abbr.append(
                    {
                        "action_uuid": auuid,
                        "action_output_dir": act_dir.relative_to(
                            tmp_path / "RUNS"
                        ).as_posix(),
                    }
                )
            prc = {
                "technique_name": "tech",
                "process_uuid": puuid,
                "run_use": proc["run_use"],
                "run_type": "test",
                "process_params": proc.get("params", {}),
                "samples_in": [{"global_label": proc["label"]}],
                "dispatched_actions_abbr": abbr,
                "files": files,
            }
            (exp_dir / f"{pidx}__{puuid}__tech-prc.yml").write_text(
                json.dumps(prc), encoding="utf-8"
            )
            puuids.append(puuid)
    return seq_dir, puuids


def _dry_tree(tmp_path):
    spec = "acquire_spec_adv"
    ref = lambda ru, off: {
        "run_use": ru,
        "label": "ref",
        "actions": [(spec, _ramp(off))],
    }
    smp = lambda lab: {"run_use": "data", "label": lab, "actions": [(spec, _ramp())]}
    return _sequence(
        tmp_path,
        "UVIS_T",
        [
            ("UVIS_sub_measure", [ref("ref_dark", 0.0)]),
            ("UVIS_sub_measure", [ref("ref_light", 100.0)]),
            ("UVIS_sub_measure", [smp("plate__1")]),
            ("UVIS_sub_measure", [smp("plate__2")]),
        ],
    )


def _eche_tree(tmp_path):
    spec = "acquire_spec_extrig"
    lab = "plate__1"
    return _sequence(
        tmp_path,
        "ECHEUVIS_multiCA_led",
        [
            (
                "ECHEUVIS_sub_OCV_led",
                [
                    {
                        "run_use": "data",
                        "label": lab,
                        "actions": [(spec, _ramp()), ("run_OCV", None)],
                    }
                ],
            ),
            (
                "ECHEUVIS_sub_CA_led",
                [
                    {
                        "run_use": "data",
                        "label": lab,
                        "params": {"CA_potential_vsRHE": 1.23},
                        "actions": [(spec, _ramp()), ("run_CA", None)],
                    }
                ],
            ),
        ],
    )


def test_dry_selects_only_the_sequence_data_processes(tmp_path):
    seq_dir, puuids = _dry_tree(tmp_path)
    got = dry.DryUvisAnalysis.select_process_uuids(LocalLoader(str(seq_dir)))
    assert sorted(str(u) for u in got) == sorted(puuids[2:])


def test_eche_selects_only_the_ca_process(tmp_path):
    seq_dir, puuids = _eche_tree(tmp_path)
    got = eche.EcheUvisAnalysis.select_process_uuids(LocalLoader(str(seq_dir)))
    assert [str(u) for u in got] == [puuids[1]]


def test_dry_runs_and_exports_through_local_loader(tmp_path):
    seq_dir, _ = _dry_tree(tmp_path)
    loader = LocalLoader(str(seq_dir))
    puuid = dry.DryUvisAnalysis.select_process_uuids(loader)[0]
    ana = dry.DryUvisAnalysis(puuid, loader, PARAMS)
    assert ana.calc_output() is True
    model, _ = ana.export_analysis("b", "r")
    assert {o["output_type"] for o in model["outputs"]} == {
        "spectrum.uvis_bkgsubnorm_ref"
    }
    assert model["global_sample_label"] == "plate__1"


def test_eche_runs_and_exports_through_local_loader(tmp_path):
    seq_dir, _ = _eche_tree(tmp_path)
    loader = LocalLoader(str(seq_dir))
    puuid = eche.EcheUvisAnalysis.select_process_uuids(loader)[0]
    ana = eche.EcheUvisAnalysis(puuid, loader, ECHE_PARAMS)
    assert ana.calc_output() is True
    model, _ = ana.export_analysis("b", "r")
    assert {o["output_type"] for o in model["outputs"]} == {
        "spectrum.echeuvis_stability"
    }
    assert ana.ca_potential_vrhe == 1.23
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/tests/test_uvis_analysis_export.py -v`
Expected: 3 passed (Task 9's), 4 FAIL: `test_dry_selects_only_the_sequence_data_processes` and `test_eche_selects_only_the_ca_process` with an `AssertionError` showing extra uuids (the base `select_process_uuids` returns every process); `test_dry_runs_and_exports_through_local_loader` and `test_eche_runs_and_exports_through_local_loader` with `AttributeError: 'LocalLoader' object has no attribute 'query'`.

- [ ] **Step 3: Write minimal implementation**

Apply exactly this patch (context = Task 9's committed files after black). Save as `/tmp/claude-1000/task10.patch`, then `git -C /tmp/claude-1000/wt-parent/helao/deploy/hte apply /tmp/claude-1000/task10.patch`. If it does not apply cleanly, make the same edits by hand from the hunks; do not improvise semantics.

```diff
--- a/servers/analysis/analyses/uvis_bkgsubnorm.py
+++ b/servers/analysis/analyses/uvis_bkgsubnorm.py
@@ -1,6 +1,6 @@
 """Dry UV-Vis background-subtraction + normalisation analysis.
 
-Pulls UV-Vis spectrometer actions (query :data:`DRYUVIS_QUERY`),
+Reads a ``UVIS_T`` sequence through a ``LocalLoader`` (:func:`local_frame`),
 averages start/end dark and light reference spectra, normalises the
 sample spectrum, bins, smooths and reference-adjusts the result, and
 emits :class:`DryUvisOutputs` via :class:`DryUvisAnalysis`.
@@ -17,11 +17,20 @@
 from scipy.stats import binned_statistic
 
 from helao.core.drivers.data.analyses.base_analysis import BaseAnalysis
-from helao.core.drivers.data.loaders.helao_loader import HelaoAction, HelaoProcess
+from helao.core.drivers.data.loaders.localfs import (
+    HelaoAction,
+    HelaoProcess,
+    LocalLoader,
+)
 from helao.core.models.analysis import AnalysisDataModel, AnalysisInput, AnalysisOutput
 from helao.core.version import get_filehash
 
-from .echeuvis_stability import last_secs_start, parse_spechlo, refadjust
+from .echeuvis_stability import (
+    last_secs_start,
+    local_frame,
+    parse_spechlo,
+    refadjust,
+)
 
 ANALYSIS_DEFAULTS = {
     "ev_parts": [1.8, 2.2, 2.6, 3.0],
@@ -39,44 +48,6 @@
     "agg_last_secs": 2,
     "agg_method": "mean",
 }
-DRYUVIS_QUERY = """
-SELECT
-    hp.dummy,
-    hp.run_type,
-    hp.sequence_uuid,
-    hp.experiment_uuid,
-    hp.process_uuid,
-    hp.process_group_index,
-    hp.process_params,
-    hp.technique_name,
-    hp.run_use,
-    hp.process_timestamp,
-    hs.sequence_params,
-    hs.sequence_name,
-    hs.sequence_label,
-    hs.sequence_timestamp,
-    hs.sequence_status,
-    he.experiment_params,
-    he.experiment_name,
-    he.experiment_status,
-    ha.action_uuid,
-    ha.action_params,
-    ha.action_name,
-    ha.action_timestamp,
-    hsmp.global_label
-FROM
-    helao_process hp
-    JOIN helao_action ha on ha.process_id = hp.id
-    JOIN helao_sequence hs on hs.sequence_uuid = hp.sequence_uuid
-    JOIN helao_experiment he on he.experiment_uuid = hp.experiment_uuid
-    JOIN helao_sample_process hsmpp on hsmpp.process_id = hp.id
-    JOIN helao_sample hsmp on hsmp.id = hsmpp.sample_id
-WHERE
-    true
-    AND hs.sequence_name in ('UVIS_T')
-    AND hp.run_type='eche'
-    AND ha.action_name in ('acquire_spec_adv')
-"""
 
 
 class DryUvisInputs(AnalysisInput):
@@ -98,62 +69,27 @@
     insitu_spec_act: HelaoAction
     process_params: dict
 
-    def __init__(
-        self,
-        insitu_process_uuid: UUID,
-        plate_id: int,
-        sample_no: int,
-        query_df: pd.DataFrame,
-    ):
-        """Resolve ref-dark/light/sample actions from the sequence frame.
+    def __init__(self, insitu_process_uuid: UUID, frame: pd.DataFrame):
+        """Resolve ref-dark/light and sample spectrometer actions from ``frame``.
 
         Args:
             insitu_process_uuid: Process UUID of the sample acquisition.
-            plate_id: Plate id of the sample.
-            sample_no: Sample number on that plate.
-            query_df: Result frame produced by :data:`DRYUVIS_QUERY`.
+            frame: :func:`local_frame` of the sequence.
         """
-        self.plate_id = plate_id
-        self.sample_no = sample_no
-        suuid = (
-            query_df.query("process_uuid==@insitu_process_uuid").iloc[0].sequence_uuid
-        )
-        sdf = query_df.query("sequence_uuid==@suuid")
-        self.ref_darks = [
-            HelaoProcess(x, query_df)
-            for x in sdf.query("run_use=='ref_dark'").process_uuid
-        ]
-        self.ref_dark_spec_acts = [
-            HelaoAction(x, query_df)
-            for x in sdf.query("run_use=='ref_dark'").action_uuid
-        ]
-        self.ref_lights = [
-            HelaoProcess(x, query_df)
-            for x in sdf.query("run_use=='ref_light'").process_uuid
-        ]
-        self.ref_light_spec_acts = [
-            HelaoAction(x, query_df)
-            for x in sdf.query("run_use=='ref_light'").action_uuid
-        ]
-
-        ddf = sdf.query("run_use=='data'")
-        bdf = (
-            ddf.query("experiment_name=='UVIS_sub_measure'")
-            .query("plate_id==@plate_id")
-            .query("sample_no==@sample_no")
-        )
-        self.insitu = HelaoProcess(
-            bdf.sort_values("action_timestamp").iloc[0].process_uuid,
-            query_df,
+        spec = frame[frame.action_name == "acquire_spec_adv"].sort_values(
+            "action_timestamp", kind="stable"
         )
+        darks = spec[spec.run_use == "ref_dark"]
+        lights = spec[spec.run_use == "ref_light"]
+        self.ref_darks = list(darks.prc)
+        self.ref_dark_spec_acts = list(darks.act)
+        self.ref_lights = list(lights.prc)
+        self.ref_light_spec_acts = list(lights.act)
+        row = spec[spec.process_uuid == insitu_process_uuid].iloc[0]
+        self.insitu = row.prc
+        self.insitu_spec_act = row.act
+        self.global_label = row.global_label
         self.process_params = self.insitu.process_params
-        self.insitu_spec_act = HelaoAction(
-            bdf.query("action_name=='acquire_spec_adv'")
-            .sort_values("action_timestamp")
-            .iloc[0]
-            .action_uuid,
-            query_df,
-        )
 
     @property
     def ref_dark_spec(self) -> list:
@@ -193,9 +129,7 @@
                 if global_sample_label is not None:
                     global_sample = global_sample_label
                 elif ru in ["data", "baseline"]:
-                    global_sample = (
-                        f"legacy__solid__{int(self.plate_id):d}_{int(self.sample_no):d}"
-                    )
+                    global_sample = self.global_label
                 else:
                     global_sample = None
                 adm = AnalysisDataModel(
@@ -254,8 +188,6 @@
         analysis_uuid: Generated analysis UUID.
         analysis_params: Effective parameters (defaults merged with
             caller overrides).
-        plate_id: Plate id under analysis.
-        sample_no: Sample number on that plate.
         process_uuid: UUID of the sample-acquisition process.
         process_timestamp: Timestamp of that process.
         process_name: Technique name from the row.
@@ -273,8 +205,6 @@
     analysis_timestamp: datetime
     analysis_uuid: UUID
     analysis_params: dict
-    plate_id: int
-    sample_no: int
     process_uuid: UUID
     process_timestamp: datetime
     process_name: str
@@ -285,17 +215,24 @@
     action_attr: str
     analysis_codehash: str
 
+    @classmethod
+    def select_process_uuids(cls, local_loader) -> list:
+        """The sequence's ``run_use == data`` acquisitions (references excluded)."""
+        f = local_frame(local_loader)
+        sel = f[(f.run_use == "data") & (f.action_name == "acquire_spec_adv")]
+        return list(sel.process_uuid)
+
     def __init__(
         self,
         process_uuid: UUID,
-        query_df: pd.DataFrame,
+        local_loader: LocalLoader,
         analysis_params: dict,
     ):
-        """Build inputs from the query frame and stamp analysis metadata.
+        """Build inputs from the loader's sequence and stamp analysis metadata.
 
         Args:
             process_uuid: Target sample-acquisition process UUID.
-            query_df: Frame produced by :data:`DRYUVIS_QUERY`.
+            local_loader: ``LocalLoader`` bound to the sequence.
             analysis_params: Overrides merged into
                 :data:`ANALYSIS_DEFAULTS`.
         """
@@ -304,20 +241,17 @@
         self.analysis_timestamp = datetime.now()
         self.analysis_params = copy(ANALYSIS_DEFAULTS)
         self.analysis_params.update(analysis_params)
-        pdf = query_df.query("process_uuid==@process_uuid")
-        self.plate_id = pdf.iloc[0].plate_id
-        self.sample_no = pdf.iloc[0].sample_no
-
-        # additional attrs
-        self.process_timestamp = pdf.iloc[0].process_timestamp
-        self.process_name = pdf.iloc[0].technique_name
-        self.run_type = pdf.iloc[0].run_type
-        self.technique_name = pdf.iloc[0].technique_name
-
-        self.inputs = DryUvisInputs(
-            process_uuid, self.plate_id, self.sample_no, query_df
-        )
+        # ponytail: frame rebuilt per process; loader caches the ymls
+        self.inputs = DryUvisInputs(process_uuid, local_frame(local_loader))
+        prc = self.inputs.insitu
         self.process_uuid = process_uuid
+        self.process_timestamp = prc.process_timestamp
+        self.process_name = prc.technique_name
+        self.run_type = prc.json.get("run_type")
+        self.run_use = "data"
+        self.technique_name = prc.technique_name
+        self.campaign_name = prc.json.get("campaign_name")
+        self.campaign_uuid = prc.json.get("campaign_uuid")
         self.analysis_codehash = get_filehash(sys._getframe().f_code.co_filename)
         self.analysis_codepath = sys._getframe().f_code.co_filename
         self.analysis_classname = self.__class__.__name__

--- a/servers/analysis/analyses/echeuvis_stability.py
+++ b/servers/analysis/analyses/echeuvis_stability.py
@@ -1,7 +1,7 @@
 """In-situ ECHE-UV-Vis optical stability analysis.
 
-Pulls SDC-UVIS process/action records from the Modelyst postgres DB
-(query :data:`SDCUVIS_QUERY`), aligns baseline-OCV, in-situ-CA, and
+Reads an ``ECHEUVIS_multiCA_led`` sequence through a ``LocalLoader``
+(:func:`local_frame`), aligns baseline-OCV, in-situ-CA, and
 post-CA OCV spectra for a single ``(plate_id, sample_no)``, performs
 background-style normalisation, binning, Savitzky-Golay smoothing and
 reference clipping, and emits per-sample stability figures of merit via
@@ -23,7 +23,11 @@
 
 LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
 from helao.core.drivers.data.analyses.base_analysis import BaseAnalysis
-from helao.core.drivers.data.loaders.helao_loader import HelaoAction, HelaoProcess
+from helao.core.drivers.data.loaders.localfs import (
+    HelaoAction,
+    HelaoProcess,
+    LocalLoader,
+)
 from helao.core.models.analysis import AnalysisDataModel, AnalysisInput, AnalysisOutput
 from helao.core.models.run_use import RunUse
 
@@ -44,45 +48,6 @@
     "agg_method": "mean",
 }
 
-SDCUVIS_QUERY = """
-SELECT
-    hp.dummy,
-    hp.run_type,
-    hp.sequence_uuid,
-    hp.experiment_uuid,
-    hp.process_uuid,
-    hp.process_group_index,
-    hp.process_params,
-    hp.technique_name,
-    hp.run_use,
-    hp.process_timestamp,
-    hs.sequence_params,
-    hs.sequence_name,
-    hs.sequence_label,
-    hs.sequence_timestamp,
-    hs.sequence_status,
-    he.experiment_params,
-    he.experiment_name,
-    he.experiment_status,
-    ha.action_uuid,
-    ha.action_params,
-    ha.action_name,
-    ha.action_timestamp,
-    hsmp.global_label
-FROM
-    helao_process hp
-    JOIN helao_action ha on ha.process_id = hp.id
-    JOIN helao_sequence hs on hs.sequence_uuid = hp.sequence_uuid
-    JOIN helao_experiment he on he.experiment_uuid = hp.experiment_uuid
-    JOIN helao_sample_process hsmpp on hsmpp.process_id = hp.id
-    JOIN helao_sample hsmp on hsmp.id = hsmpp.sample_id
-WHERE
-    true
-    AND hs.sequence_name in ('ECHEUVIS_multiCA_led')
-    AND hp.run_type='echeuvis'
-    AND ha.action_name in ('run_OCV', 'run_CA', 'acquire_spec_adv', 'acquire_spec_extrig')
-"""
-
 
 def parse_spechlo(hlod: dict):
     """Decode a spectrometer hlo dict into ``(wavelength, epoch, spectra)``.
@@ -146,6 +111,49 @@
     return skip + np.where((ep[skip:] - ep.max()) >= -secs)[0].min()
 
 
+def local_frame(local_loader: LocalLoader) -> pd.DataFrame:
+    """One row per dispatched action of every process ``local_loader`` indexed.
+
+    Stands in for the retired DB query: the columns the input resolvers select
+    on, plus the loaded process (``prc``) and action (``act``) records.
+    """
+    rows = []
+    for idx, prow in local_loader.processes.iterrows():
+        prc = local_loader.get_prc(idx)
+        sample = (prc.json.get("samples_in") or [{}])[0]
+        for abbr in prc.json.get("dispatched_actions_abbr", []):
+            act = local_loader.resolve_action(
+                abbr["action_uuid"], abbr["action_output_dir"]
+            )
+            rows.append(
+                {
+                    "process_uuid": prow.process_uuid,
+                    "run_use": str(prc.json.get("run_use") or "data"),
+                    "experiment_name": prow.experiment_name,
+                    "global_label": sample.get("global_label"),
+                    "action_uuid": str(act.action_uuid),
+                    "action_name": act.action_name,
+                    "action_timestamp": str(act.action_timestamp),
+                    "prc": prc,
+                    "act": act,
+                }
+            )
+    return pd.DataFrame(
+        rows,
+        columns=[
+            "process_uuid",
+            "run_use",
+            "experiment_name",
+            "global_label",
+            "action_uuid",
+            "action_name",
+            "action_timestamp",
+            "prc",
+            "act",
+        ],
+    )
+
+
 class EcheUvisInputs(AnalysisInput):
     """Resolved baseline/in-situ/pre-situ processes and actions for one sample.
 
@@ -178,114 +186,48 @@
     process_params: dict
     # solid_samples: list
 
-    def __init__(
-        self,
-        insitu_process_uuid: UUID,
-        plate_id: int,
-        sample_no: int,
-        query_df: pd.DataFrame,
-    ):
-        """Resolve the baseline / in-situ / pre-situ acts from ``query_df``.
+    def __init__(self, insitu_process_uuid: UUID, frame: pd.DataFrame):
+        """Resolve the baseline / in-situ / pre-situ acts from ``frame``.
 
         Args:
             insitu_process_uuid: Process UUID of the in-situ CA run.
-            plate_id: Plate id of the sample under analysis.
-            sample_no: Sample number on that plate.
-            query_df: Query-result DataFrame produced by
-                :data:`SDCUVIS_QUERY`.
+            frame: :func:`local_frame` of the sequence.
         """
-        self.plate_id = plate_id
-        self.sample_no = sample_no
-        self.insitu = HelaoProcess(insitu_process_uuid, query_df)
+        frame = frame.sort_values("action_timestamp", kind="stable")
+        data = frame[frame.run_use == "data"]
+        ins = frame[frame.process_uuid == insitu_process_uuid]
+        self.insitu = ins.iloc[0].prc
+        self.global_label = ins.iloc[0].global_label
         self.process_params = self.insitu.process_params
-        self.insitu_spec_act = HelaoAction(
-            query_df.query(
-                "process_uuid==@insitu_process_uuid & action_name=='acquire_spec_extrig'"
-                # "process_uuid==@insitu_process_uuid & action_name=='acquire_spec_adv'"
-            )
-            .iloc[0]
-            .action_uuid,
-            query_df,
-        )
-        self.insitu_ca_act = HelaoAction(
-            query_df.query("process_uuid==@insitu_process_uuid & action_name=='run_CA'")
-            .iloc[0]
-            .action_uuid,
-            query_df,
-        )
-        keep_eche = ["run_OCV", "run_CA"]
-        eche_acts = query_df.query(
-            "run_use=='data' & action_name.isin(@keep_eche)"
-        ).sort_values("action_timestamp")
+        self.insitu_spec_act = ins[ins.action_name == "acquire_spec_extrig"].iloc[0].act
+        self.insitu_ca_act = ins[ins.action_name == "run_CA"].iloc[0].act
+
+        # the OCV run immediately before this CA is the post-CA (presitu) reference
+        eche_acts = data[data.action_name.isin(["run_OCV", "run_CA"])]
         presitu_ocv_idx = (
-            list(eche_acts.action_uuid).index(self.insitu_ca_act.action_uuid) - 1
-        )
-        self.presitu_ocv_act = HelaoAction(
-            list(eche_acts.action_uuid)[presitu_ocv_idx], query_df
+            list(eche_acts.action_uuid).index(str(self.insitu_ca_act.action_uuid)) - 1
         )
-        keep_ocv = ["run_OCV", "acquire_spec_extrig"]
-        ocv_specs = query_df.query(
-            "run_use=='data' & action_name.isin(@keep_ocv) & experiment_name=='ECHEUVIS_sub_OCV_led'"
-        ).sort_values("action_timestamp")
+        self.presitu_ocv_act = eche_acts.iloc[presitu_ocv_idx].act
+        self.presitu = eche_acts.iloc[presitu_ocv_idx].prc
+        ocv_specs = data[
+            data.action_name.isin(["run_OCV", "acquire_spec_extrig"])
+            & (data.experiment_name == "ECHEUVIS_sub_OCV_led")
+        ]
         presitu_spec_idx = (
-            list(ocv_specs.action_uuid).index(self.presitu_ocv_act.action_uuid) - 1
-        )
-        self.presitu_spec_act = HelaoAction(
-            list(ocv_specs.action_uuid)[presitu_spec_idx], query_df
+            list(ocv_specs.action_uuid).index(str(self.presitu_ocv_act.action_uuid)) - 1
         )
+        self.presitu_spec_act = ocv_specs.iloc[presitu_spec_idx].act
 
-        self.presitu = HelaoProcess(
-            query_df.query("action_uuid==@self.presitu_ocv_act.action_uuid")
-            .iloc[0]
-            .process_uuid,
-            query_df,
-        )
-        suuid = (
-            query_df.query("process_uuid==@insitu_process_uuid").iloc[0].sequence_uuid
-        )
-        sdf = query_df.query("sequence_uuid==@suuid")
-        # self.ref_darks = [
-        #     HelaoProcess(x, query_df)
-        #     for x in sdf.query("run_use=='ref_dark'").process_uuid
-        # ]
-        # self.ref_dark_spec_acts = [
-        #     HelaoAction(x, query_df)
-        #     for x in sdf.query("run_use=='ref_dark'").action_uuid
-        # ]
-        # self.ref_lights = [
-        #     HelaoProcess(x, query_df)
-        #     for x in sdf.query("run_use=='ref_light'").process_uuid
-        # ]
-        # self.ref_light_spec_acts = [
-        #     HelaoAction(x, query_df)
-        #     for x in sdf.query("run_use=='ref_light'").action_uuid
-        # ]
-
-        ddf = sdf.query("run_use=='data'")
-        bdf = (
-            ddf.query("experiment_name=='ECHEUVIS_sub_OCV_led'")
-            .query("plate_id==@plate_id")
-            .query("sample_no==@sample_no")
-        )
-        self.baseline = HelaoProcess(
-            bdf.sort_values("action_timestamp").iloc[0].process_uuid,
-            query_df,
-        )
-        self.baseline_spec_act = HelaoAction(
-            bdf.query("action_name=='acquire_spec_extrig'")
-            # bdf.query("action_name=='acquire_spec_adv'")
-            .sort_values("action_timestamp").iloc[0].action_uuid,
-            query_df,
-        )
-        self.baseline_ocv_act = HelaoAction(
-            ddf.query("action_name=='run_OCV'")
-            .sort_values("action_timestamp")
-            .iloc[0]
-            .action_uuid,
-            query_df,
+        # the sample's first OCV experiment is the optical baseline
+        bdf = data[
+            (data.experiment_name == "ECHEUVIS_sub_OCV_led")
+            & (data.global_label == self.global_label)
+        ]
+        self.baseline = bdf.iloc[0].prc
+        self.baseline_spec_act = (
+            bdf[bdf.action_name == "acquire_spec_extrig"].iloc[0].act
         )
-
-        # self.solid_samples = [f"legacy__solid__{plate_id}+{sample_no}"]
+        self.baseline_ocv_act = data[data.action_name == "run_OCV"].iloc[0].act
 
     # @property
     # def ref_dark_spec(self):
@@ -353,9 +295,7 @@
                 if global_sample_label is not None:
                     global_sample = global_sample_label
                 elif ru in ["data", "baseline", "preca_baseline"]:
-                    global_sample = (
-                        f"legacy__solid__{int(self.plate_id):d}_{int(self.sample_no):d}"
-                    )
+                    global_sample = self.global_label
                 else:
                     global_sample = None
                 adm = AnalysisDataModel(
@@ -460,8 +400,6 @@
         analysis_uuid: Generated analysis UUID.
         analysis_params: Effective parameters (defaults merged with
             caller overrides).
-        plate_id: Plate id under analysis.
-        sample_no: Sample number on that plate.
         ca_potential_vrhe: CA potential vs. RHE used in the in-situ
             process.
         process_uuid: UUID of the in-situ CA process.
@@ -479,9 +417,7 @@
     analysis_timestamp: datetime
     analysis_uuid: UUID
     analysis_params: dict
-    plate_id: int
-    sample_no: int
-    ca_potential_vrhe: float
+    ca_potential_vrhe: float | None
     process_uuid: UUID
     process_timestamp: datetime
     process_name: str
@@ -491,18 +427,23 @@
     outputs: EcheUvisOutputs
     analysis_codehash: str
 
+    @classmethod
+    def select_process_uuids(cls, local_loader) -> list:
+        """The sequence's ``run_use == data`` CA processes (the in-situ targets)."""
+        f = local_frame(local_loader)
+        return list(f[(f.run_use == "data") & (f.action_name == "run_CA")].process_uuid)
+
     def __init__(
         self,
         process_uuid: UUID,
-        query_df: pd.DataFrame,
+        local_loader: LocalLoader,
         analysis_params: dict,
     ):
-        """Build inputs, derive plate/sample identifiers, generate UUID.
+        """Build inputs from the loader's sequence and generate the UUID.
 
         Args:
             process_uuid: UUID of the in-situ CA process.
-            query_df: Query result frame produced by
-                :data:`SDCUVIS_QUERY`.
+            local_loader: ``LocalLoader`` bound to the sequence.
             analysis_params: Overrides merged into
                 :data:`ANALYSIS_DEFAULTS`.
         """
@@ -510,24 +451,18 @@
         self.analysis_timestamp = datetime.now()
         self.analysis_params = copy(ANALYSIS_DEFAULTS)
         self.analysis_params.update(analysis_params)
-        pdf = query_df.query("process_uuid==@process_uuid").reset_index(drop=True)
-        # print("filtered data has shape:", pdf.shape)
-        self.plate_id = int(pdf.iloc[0].plate_id)
-        self.sample_no = int(pdf.iloc[0].sample_no)
-
-        # additional attrs
-        self.process_timestamp = pdf.iloc[0].process_timestamp
-        self.process_name = pdf.iloc[0].technique_name
-        self.run_type = pdf.iloc[0].run_type
-        self.technique_name = pdf.iloc[0].technique_name
-
-        # print("assembling inputs")
-        self.inputs = EcheUvisInputs(
-            process_uuid, self.plate_id, self.sample_no, query_df
-        )
+        # ponytail: frame rebuilt per process; loader caches the ymls
+        self.inputs = EcheUvisInputs(process_uuid, local_frame(local_loader))
+        prc = self.inputs.insitu
         self.process_uuid = process_uuid
-        self.ca_potential_vrhe = self.inputs.insitu.process_params["CA_potential_vsRHE"]
-        # print("getting code hash")
+        self.process_timestamp = prc.process_timestamp
+        self.process_name = prc.technique_name
+        self.run_type = prc.json.get("run_type")
+        self.run_use = "data"
+        self.technique_name = prc.technique_name
+        self.campaign_name = prc.json.get("campaign_name")
+        self.campaign_uuid = prc.json.get("campaign_uuid")
+        self.ca_potential_vrhe = self.inputs.process_params.get("CA_potential_vsRHE")
         self.analysis_codehash = get_filehash(sys._getframe().f_code.co_filename)
         self.analysis_codepath = sys._getframe().f_code.co_filename
         self.analysis_classname = self.__class__.__name__

```

After applying, also correct the two `get_datamodels` docstrings that still describe the legacy label: in both files the `Args:` text `falls back to ``legacy__solid__<plate>_<sample>`` for ``data`` and ``baseline`` run uses.` (uvis) and `falls back to a legacy ``solid__<plate>_<sample>`` label for data/baseline inputs.` (eche) become `falls back to the analysed process's first ``samples_in`` ``global_label`` for data/baseline inputs.` (re-wrap to the surrounding docstring width).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/tests/test_uvis_analysis_export.py helao/deploy/hte/tests/test_echeuvis_presitu_arrays.py helao/deploy/hte/tests/test_low_w3_hte_fixes.py helao/deploy/hte/servers/analysis/tests/test_analysis_resolution.py -q`
Expected: PASS (all; 7 in the new file).

Run: `grep -rn "DRYUVIS_QUERY\|SDCUVIS_QUERY\|helao_loader" /tmp/claude-1000/wt-parent/helao/deploy/hte/servers/analysis`
Expected: no output.

- [ ] **Step 5: Mutation check**

```bash
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte diff -- servers/analysis/analyses/uvis_bkgsubnorm.py servers/analysis/analyses/echeuvis_stability.py > /tmp/claude-1000/mut-task10.patch
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte apply -R /tmp/claude-1000/mut-task10.patch
cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/tests/test_uvis_analysis_export.py -q   # expect 4 failed, 3 passed (Step 2)
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte apply /tmp/claude-1000/mut-task10.patch
cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/tests/test_uvis_analysis_export.py -q   # expect 7 passed
```

- [ ] **Step 6: README**

Re-point moved citations (HEAD = Task 9's commit):

```bash
cd /tmp/claude-1000/wt-parent/helao/deploy/hte && /home/dan/miniforge3/envs/helao/bin/python /tmp/claude-1000/recite.py . servers/analysis/README.md HEAD servers/analysis/analyses/uvis_bkgsubnorm.py servers/analysis/analyses/echeuvis_stability.py
```
Expected: no `UNRESOLVED` lines. (Spot check: `uvis_bkgsubnorm.py:382` -> `:316`, `echeuvis_stability.py:141` -> `:106`, `echeuvis_stability.py:87` -> `:52`.)

Then in `$H/servers/analysis/README.md` replace the `## Outputs` intro paragraph that starts `Both analyses are queued by an `analyze_<module>` endpoint, run `calc_output` once per sample process` with:

`Both analyses are queued by an `analyze_<module>` endpoint, which builds a `LocalLoader` on the synced sequence directory and enqueues one analysis per process returned by `select_process_uuids`: the sequence's `run_use == "data"` processes that dispatched `acquire_spec_adv` (`uvis_bkgsubnorm`, `helao/deploy/hte/servers/analysis/analyses/uvis_bkgsubnorm.py:219`) or `run_CA` (`echeuvis_stability`, `helao/deploy/hte/servers/analysis/analyses/echeuvis_stability.py:431`). Each runs `calc_output` once and assigns the result to `self.outputs`. Inputs are resolved from one row per dispatched action of every process in the sequence (`local_frame`, `helao/deploy/hte/servers/analysis/analyses/echeuvis_stability.py:114`); the spectra are the spectrometer actions' data files (`parse_spechlo`, `helao/deploy/hte/servers/analysis/analyses/echeuvis_stability.py:52`: `meta.optional.wl`, `data.epoch_s`, the `ch_*` columns). The model's `global_sample_label` is the analysed process's first `samples_in` `global_label`.`

(Verify the four numbers with `grep -n "def select_process_uuids\|^def local_frame\|^def parse_spechlo" servers/analysis/analyses/*.py`; expected uvis 219, eche 431, 114, 52. If black placed them differently, use what grep prints.)

Run: `cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/tests/test_readme_outputs.py -q`
Expected: PASS.

- [ ] **Step 7: Commit (main session; subagents never commit)**

```bash
/home/dan/miniforge3/envs/helao/bin/black /tmp/claude-1000/wt-parent/helao/deploy/hte/servers/analysis/analyses/uvis_bkgsubnorm.py /tmp/claude-1000/wt-parent/helao/deploy/hte/servers/analysis/analyses/echeuvis_stability.py /tmp/claude-1000/wt-parent/helao/deploy/hte/tests/test_uvis_analysis_export.py
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte branch --show-current   # expect fix/catalog-bugfixes
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte status --short
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte add servers/analysis/analyses/uvis_bkgsubnorm.py servers/analysis/analyses/echeuvis_stability.py tests/test_uvis_analysis_export.py servers/analysis/README.md
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte commit -m "fix(analysis): port uvis analyses to the LocalLoader contract"
```

---

---

### Task 11: H5c SYNC post-finish trigger on eche10; delete the dangling in-sequence analysis path (hte)

**Files:**
- Modify: `helao/deploy/hte/configs/eche10.yml:166-182` (SYNC `postfinish_hooks`; ANA replaces the commented block)
- Modify: `helao/deploy/hte/experiments/ECHEUVIS_exp.py:7,11,59,807-836` (delete `ECHEUVIS_analysis_stability`, its `EXPERIMENTS` entry, `ANA_server`)
- Modify: `helao/deploy/hte/experiments/UVIS_exp.py:6,10,46,559-590` (delete `UVIS_analysis_dry`, its entry, `ANA_server`)
- Modify: `helao/deploy/hte/sequences/ECHEUVIS_seq.py:5-6,15,1037-1065` (delete `ECHEUVIS_postseq`)
- Modify: `helao/deploy/hte/sequences/HISPEC_seq.py:5,480-506` (delete `ECHEUVIS_postseq`)
- Modify: `helao/deploy/hte/sequences/UVIS_T_seq.py:1,3,136-162` (delete `UVIS_T_postseq`)
- Modify: `helao/deploy/hte/tests/test_queued_experiments_exist.py:72,84-92`, `helao/deploy/hte/tests/test_hte_collisions.py:10-14`, `helao/deploy/hte/tests/test_hte_library_import.py:14-20,77-80`, `helao/deploy/hte/tests/checklists/_collisions.json`
- Test: `helao/deploy/hte/servers/analysis/tests/test_analysis_resolution.py` (extend)
- Docs: `helao/deploy/hte/servers/analysis/README.md`

**Interfaces:**
- Consumes: Task 10's routes `analyze_uvis_bkgsubnorm` / `analyze_echeuvis_stability` and their `sequence_path` contract; core `postfinish_config(postfinish_hooks, label, params=None) -> dict[str, HookMap]` (`helao/core/hooks/config.py:78`), `load_hook_set(cfg, phase, level) -> HookSet` (`helao/core/hooks/loader.py:137`), `HookSet.select(name) -> list[(hook_name, hook, args)]` (`helao/core/hooks/__init__.py:90-102`).
- Produces: eche10 config keys `servers.SYNC.postfinish_hooks` and `servers.ANA`; nothing else depends on the deleted functions (checked: outside hte only old plan/spec docs name them).

Checked for this task: ports in `eche10.yml` are 8001, 5002, 8003 (+ aligner Bokeh 5003), 8004, 8005, 8008, 8011, 5001, 5005, 8010, 8013, 8015, 5110/5111 -- 8014 is free, and the default `log_port` (one above the highest server port, 8016) is unchanged. `SyncDriver` reads `postfinish_hooks` from the SYNC entry's top level, sibling of `params` (`helao/hexagon/adapters/native/native_syncer.py:55`). `make_analysis_app` resolves the hte analyses package for `deployment` hte (`helao/core/drivers/data/analysis_driver.py:1386-1392`).

- [ ] **Step 1: Write the failing test**

Append to `$H/servers/analysis/tests/test_analysis_resolution.py` (it already defines `m` and `HTE_ENDPOINTS`; exact patch, apply with `git -C $H apply`):

```diff
diff --git a/servers/analysis/tests/test_analysis_resolution.py b/servers/analysis/tests/test_analysis_resolution.py
index 48f982a..f438db0 100644
--- a/servers/analysis/tests/test_analysis_resolution.py
+++ b/servers/analysis/tests/test_analysis_resolution.py
@@ -211,3 +211,46 @@ def test_app_build_fails_when_a_configured_analysis_is_missing(tmp_path, monkeyp
     world["servers"]["ANA"]["params"]["analyses"] = HTE_ANALYSES + ["no_such_analysis"]
     with pytest.raises(m.AnalysisLoadError):
         _analyze_routes(world, "ANA", monkeypatch)
+
+
+# ---------------------------------------------------------------------------
+# Station wiring: eche10's SYNC dispatches both analyses to its ANA server
+# ---------------------------------------------------------------------------
+
+
+def test_eche10_sync_dispatches_both_uvis_analyses_to_ana():
+    """The SYNC post-finish chain picks the right ANA route per sequence name.
+
+    A present ``postfinish_hooks`` owns the whole chain, so ``s3_upload`` must
+    still run at every level and for every other sequence.
+    """
+    from helao.core.hooks.config import postfinish_config
+    from helao.core.hooks.loader import load_hook_set
+    from helao.helpers.config_loader import read_config
+
+    cfg = read_config("eche10")
+    sync = cfg["servers"]["SYNC"]
+    chain = postfinish_config(
+        sync.get("postfinish_hooks"), "SYNC", params=sync.get("params")
+    )
+    seq_hooks = load_hook_set(chain["sequence"], phase="postfinish", level="sequence")
+    picked = {
+        name: {hook: args for hook, _, args in seq_hooks.select(name)}
+        for name in ("UVIS_T", "ECHEUVIS_multiCA_led", "SOME_OTHER_SEQUENCE")
+    }
+    assert picked["UVIS_T"]["dispatch_analysis"] == {
+        "server_key": "ANA",
+        "endpoint": "analyze_uvis_bkgsubnorm",
+    }
+    assert picked["ECHEUVIS_multiCA_led"]["dispatch_analysis"] == {
+        "server_key": "ANA",
+        "endpoint": "analyze_echeuvis_stability",
+    }
+    assert set(picked["SOME_OTHER_SEQUENCE"]) == {"s3_upload"}
+    for level in ("action", "experiment"):
+        assert set(chain[level]) == {"s3_upload"}
+    ana = cfg["servers"]["ANA"]
+    assert (ana["fast"], ana["params"]["local_only"]) == ("analysis_server", True)
+    assert (
+        set(m.load_analysis_classes(ana["params"]["analyses"], "hte")) == HTE_ENDPOINTS
+    )

```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest "helao/deploy/hte/servers/analysis/tests/test_analysis_resolution.py::test_eche10_sync_dispatches_both_uvis_analyses_to_ana" -v`
Expected: FAIL with `KeyError: 'dispatch_analysis'` (no `postfinish_hooks` -> the default chain is `s3_upload` only).

- [ ] **Step 3: Write minimal implementation**

Apply exactly this patch (save as `/tmp/claude-1000/task11.patch`, then `git -C /tmp/claude-1000/wt-parent/helao/deploy/hte apply /tmp/claude-1000/task11.patch`). It wires eche10 per the spec's "Analysis trigger" block (ANA `local_only: true` for the first station check), deletes `ECHEUVIS_analysis_stability`, both `ECHEUVIS_postseq`, `UVIS_T_postseq`, `UVIS_analysis_dry`, their `EXPERIMENTS`/`SEQUENCES` entries and the now-unused `ANA_server` constants, and updates the four tests/fixtures that pinned those names (`KNOWN_CONFIG_GAPS` loses the two eche10 postseq entries and the whole `hispec` key, which would otherwise fail `test_config_gap_allowlist_has_no_stale_entries`; the collision tests now pin "no sequence collisions" plus a non-vacuity copy test).

```diff
--- a/configs/eche10.yml
+++ b/configs/eche10.yml
@@ -172,14 +172,24 @@
     params:
       aws_profile: default
       testing: false
-  # ANA:
-  #   host: hte-eche-10.htejcap.caltech.edu
-  #   port: 8014
-  #   group: action
-  #   fast: analysis_server
-  #   params:
-  #     local_only: false
-  #     analyses: [icpms_local, xrfs_local]
+    # A present postfinish_hooks owns the whole chain: s3_upload is restated
+    # at every level. dispatch_analysis resolves ANA from this config.
+    postfinish_hooks:
+      action: {s3_upload: ["*"]}
+      experiment: {s3_upload: ["*"]}
+      sequence:
+        s3_upload: ["*"]
+        dispatch_analysis:
+          UVIS_T: {server_key: ANA, endpoint: analyze_uvis_bkgsubnorm}
+          ECHEUVIS_multiCA_led: {server_key: ANA, endpoint: analyze_echeuvis_stability}
+  ANA:
+    host: hte-eche-10.htejcap.caltech.edu
+    port: 8014
+    group: action
+    fast: analysis_server
+    params:
+      local_only: true  # first station check: no S3/API publish
+      analyses: [uvis_bkgsubnorm, echeuvis_stability]
   CAM:
     host: hte-eche-10.htejcap.caltech.edu
     port: 8013
--- a/experiments/ECHEUVIS_exp.py
+++ b/experiments/ECHEUVIS_exp.py
@@ -4,11 +4,10 @@
 function takes an ``Experiment`` and returns the list of actions to enqueue.
 Action targets are referenced by ``server_key`` strings (e.g. ``PSTAT``,
 ``MOTOR``, ``KMOTOR``, ``IO``, ``SPEC_T``, ``SPEC_R``, ``PAL``, ``CAM``,
-``ANA``, ``ORCH``).
+``ORCH``).
 """
 
 EXPERIMENTS = [
-    "ECHEUVIS_analysis_stability",
     "ECHEUVIS_sub_CA_led",
     "ECHEUVIS_sub_CP_led",
     "ECHEUVIS_sub_CV_led",
@@ -56,7 +55,6 @@
 SAMPLE_server = MM(server_name="SAMPLE", machine_name=gethostname().lower()).as_dict()
 CAM_server = MM(server_name="CAM", machine_name=gethostname().lower()).as_dict()
 KMOTOR_server = MM(server_name="KMOTOR", machine_name=gethostname().lower()).as_dict()
-ANA_server = MM(server_name="ANA", machine_name=gethostname().lower()).as_dict()
 
 TOGGLE_TRIGGERTYPE = TriggerType.risingedge
 
@@ -802,35 +800,3 @@
             },
         )
     return apm.planned_actions  # returns complete action list to orch
-
-
-@experiment(version=2)
-def ECHEUVIS_analysis_stability(
-    sequence_uuid: str = "",
-    plate_id: int = 0,
-    recent: bool = True,
-    params: dict = {},
-) -> list:
-    """Dispatch an ECHE+UVIS stability analysis action to the analysis server.
-
-    Args:
-        sequence_uuid: UUID of the sequence to analyze.
-        plate_id: Plate identifier.
-        recent: Operate on the most recent sequence when True.
-        params: Additional parameters forwarded to ``analyze_echeuvis``.
-
-    Returns:
-        List of planned actions for the orchestrator.
-    """
-    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
-    apm.add(
-        ANA_server,
-        "analyze_echeuvis",
-        {
-            "sequence_uuid": sequence_uuid,
-            "plate_id": plate_id,
-            "recent": recent,
-            "params": params,
-        },
-    )
-    return apm.planned_actions
--- a/experiments/UVIS_exp.py
+++ b/experiments/UVIS_exp.py
@@ -3,11 +3,10 @@
 Each `UVIS_sub_*` helper returns a list of planned actions assembled by an
 `ActionPlanMaker` that the orchestrator can dispatch. The action graph drives
 the SPEC_T/SPEC_R spectrometer servers, the motion and IO servers, the PAL
-sample archive, and the CAM/PDU/CALC/ANA helpers.
+sample archive, and the CAM/PDU/CALC helpers.
 """
 
 EXPERIMENTS = [
-    "UVIS_analysis_dry",
     "UVIS_calc_abs",
     "UVIS_measure_references",
     "UVIS_sub_load_solid",
@@ -43,7 +42,6 @@
 PAL_server = MM(server_name="PAL", machine_name=gethostname().lower()).as_dict()
 SAMPLE_server = MM(server_name="SAMPLE", machine_name=gethostname().lower()).as_dict()
 CALC_server = MM(server_name="CALC", machine_name=gethostname().lower()).as_dict()
-ANA_server = MM(server_name="ANA", machine_name=gethostname().lower()).as_dict()
 CAM_server = MM(server_name="CAM", machine_name=gethostname().lower()).as_dict()
 PDU_server = MM(server_name="PDU", machine_name=gethostname().lower()).as_dict()
 
@@ -557,38 +555,6 @@
 
 
 @experiment(version=2)
-def UVIS_analysis_dry(
-    sequence_uuid: str = "",
-    plate_id: int = 0,
-    recent: bool = True,
-    params: dict = {},
-) -> list:
-    """Run the ANA server's dry UV-Vis analysis for a sequence/plate.
-
-    Args:
-        sequence_uuid: Sequence UUID to analyse.
-        plate_id: Plate id to filter on.
-        recent: If True, restrict the analysis to recent runs.
-        params: Free-form parameter dict forwarded to the analyzer.
-
-    Returns:
-        List with a single ANA ``analyze_dryuvis`` action.
-    """
-    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
-    apm.add(
-        ANA_server,
-        "analyze_dryuvis",
-        {
-            "sequence_uuid": sequence_uuid,
-            "plate_id": plate_id,
-            "recent": recent,
-            "params": params,
-        },
-    )
-    return apm.planned_actions
-
-
-@experiment(version=2)
 def UVIS_measure_references(
     plate_id: int = 1,
     custom_position: str = "cell1_we",
--- a/sequences/ECHEUVIS_seq.py
+++ b/sequences/ECHEUVIS_seq.py
@@ -2,8 +2,7 @@
 
 Each public ``ECHEUVIS_*`` function builds an experiment list via
 ``ExperimentPlanMaker``. Sequences chain sample loading, reference
-measurements, LED-triggered electrochemistry (CV/CA/CP/multiCA), and a
-post-sequence analysis hook.
+measurements, LED-triggered electrochemistry (CV/CA/CP/multiCA).
 """
 
 SEQUENCES = [
@@ -12,7 +11,6 @@
     "ECHEUVIS_CV_led",
     "ECHEUVIS_diagnostic_CV",
     "ECHEUVIS_multiCA_led",
-    "ECHEUVIS_postseq",
 ]
 
 import random
@@ -1032,34 +1030,3 @@
     epm.add("ECHEUVIS_sub_shutdown", {})
 
     return epm.planned_experiments  # returns complete experiment list
-
-
-@sequence(version=1)
-def ECHEUVIS_postseq(
-    analysis_seq_uuid: str = "",
-    plate_id: int = 0,
-    recent: bool = False,
-) -> list:
-    """Post-sequence analysis hook for ECHEUVIS runs.
-
-    Forwards the sequence UUID and parameters to the ECHEUVIS analyzer.
-
-    Args:
-        analysis_seq_uuid: UUID of the sequence to analyze.
-        plate_id: Plate ID of the solid sample library.
-        recent: Whether to reuse the most recent calibration/state.
-
-    Returns:
-        List of planned experiments to dispatch.
-    """
-    epm = ExperimentPlanMaker()
-    epm.add(
-        "ECHEUVIS_analysis_stability",
-        {
-            "sequence_uuid": analysis_seq_uuid,
-            "plate_id": plate_id,
-            "recent": recent,
-        },
-    )
-
-    return epm.planned_experiments  # returns complete experiment list
--- a/sequences/HISPEC_seq.py
+++ b/sequences/HISPEC_seq.py
@@ -2,7 +2,6 @@
     # "ECHEUVIS_CA_led",
     # "ECHEUVIS_CP_led",
     # "ECHEUVIS_CV_led",
-    "ECHEUVIS_postseq",
     "HISPEC_CV",
     "HISPEC_EIS_only",
 ]
@@ -475,32 +474,3 @@
     epm.add("HISPEC_sub_shutdown", {})
 
     return epm.planned_experiments  # returns complete experiment list
-
-
-@sequence(version=1)
-def ECHEUVIS_postseq(
-    analysis_seq_uuid: str = "",
-    plate_id: int = 0,
-    recent: bool = False,
-) -> list:
-    """Build a post-sequence that runs the ECHEUVIS stability analysis.
-
-    Args:
-        analysis_seq_uuid: UUID of the source sequence to analyze.
-        plate_id: Plate identifier scoping the analysis.
-        recent: Restrict to the most recent matching run when True.
-
-    Returns:
-        list: Ordered list of planned ``Experiment`` objects.
-    """
-    epm = ExperimentPlanMaker()
-    epm.add(
-        "ECHEUVIS_analysis_stability",
-        {
-            "sequence_uuid": analysis_seq_uuid,
-            "plate_id": plate_id,
-            "recent": recent,
-        },
-    )
-
-    return epm.planned_experiments  # returns complete experiment list
--- a/sequences/UVIS_T_seq.py
+++ b/sequences/UVIS_T_seq.py
@@ -1,6 +1,6 @@
-"""Sequence library exposing UV-Vis transmission programs and a post-analysis."""
+"""Sequence library exposing UV-Vis transmission programs."""
 
-SEQUENCES = ["UVIS_T", "UVIS_T_postseq"]
+SEQUENCES = ["UVIS_T"]
 
 from helao.helpers.lib_decorators import sequence
 from helao.helpers.premodels import ExperimentPlanMaker
@@ -131,32 +131,3 @@
     refs(plate_sample_no_list[-1], first=False)
     epm.add("UVIS_sub_shutdown", {})
     return epm.planned_experiments
-
-
-@sequence(version=1)
-def UVIS_T_postseq(
-    analysis_seq_uuid: str = "",
-    plate_id: int = 0,
-    recent: bool = False,
-) -> list:
-    """Build a post-sequence that runs the dry UVIS analysis.
-
-    Args:
-        analysis_seq_uuid: UUID of the source sequence to analyze.
-        plate_id: Plate identifier scoping the analysis.
-        recent: Restrict to the most recent matching run when True.
-
-    Returns:
-        list: Ordered list of planned ``Experiment`` objects.
-    """
-    epm = ExperimentPlanMaker()
-    epm.add(
-        "UVIS_analysis_dry",
-        {
-            "sequence_uuid": analysis_seq_uuid,
-            "plate_id": plate_id,
-            "recent": recent,
-        },
-    )
-
-    return epm.planned_experiments  # returns complete experiment list
--- a/tests/checklists/_collisions.json
+++ b/tests/checklists/_collisions.json
@@ -1,9 +1,4 @@
 {
   "exp": {},
-  "seq": {
-    "ECHEUVIS_postseq": [
-      "ECHEUVIS_seq.py",
-      "HISPEC_seq.py"
-    ]
-  }
+  "seq": {}
 }
--- a/tests/test_hte_collisions.py
+++ b/tests/test_hte_collisions.py
@@ -7,11 +7,21 @@
 SEQ = HTE / "sequences"
 
 
-def test_known_seq_collision_detected():
-    cols = scan_collisions(SEQ)
-    # ECHEUVIS_postseq defined in both ECHEUVIS_seq.py and HISPEC_seq.py
-    assert "ECHEUVIS_postseq" in cols
-    assert {"ECHEUVIS_seq.py", "HISPEC_seq.py"} <= set(cols["ECHEUVIS_postseq"])
+def test_hte_seq_libraries_have_no_collisions():
+    # the one known collision, ECHEUVIS_postseq in ECHEUVIS_seq.py and
+    # HISPEC_seq.py, was deleted with the in-sequence analysis path
+    assert scan_collisions(SEQ) == {}
+
+
+def test_seq_collision_detected_in_real_dir_copy(tmp_path):
+    # non-vacuity: a copy of the real library plus one duplicate def must be caught
+    import shutil
+
+    shutil.copytree(SEQ, tmp_path / "s")
+    (tmp_path / "s" / "zz_seq.py").write_text(
+        "def UVIS_T():\n    return []\n", encoding="utf-8"
+    )
+    assert scan_collisions(tmp_path / "s") == {"UVIS_T": ["UVIS_T_seq.py", "zz_seq.py"]}
 
 
 def test_exp_collision_detected_in_synthetic_pair(tmp_path):
--- a/tests/test_hte_library_import.py
+++ b/tests/test_hte_library_import.py
@@ -11,13 +11,12 @@
    ``galil_motion_driver``/``pal_driver``). If a driver regresses to a
    module-top vendor import, the dependent libraries break here loudly.
 
-2. **Flat-namespace collision guard** (spec §4.3.12 Library port) — the known
-   known ``ECHEUVIS_seq``/``HISPEC_seq`` (``ECHEUVIS_postseq``) shadowing
-   hazard is asserted to still be detectable, and the detector itself is
+2. **Flat-namespace collision guard** (spec §4.3.12 Library port) — both
+   library directories are pinned collision-free, and the detector itself is
    exercised on a synthetic pair, so the eventual Library-port load-time
-   collision check has a frozen expected set. The collision is currently
-   **latent** — no hte config lists a colliding pair in one ``*_libraries:``
-   list — but the guard keeps it from silently going live.
+   collision check has a frozen expected set. The one former collision,
+   ``ECHEUVIS_postseq`` in ``ECHEUVIS_seq`` and ``HISPEC_seq``, was deleted
+   with the in-sequence analysis path.
 """
 
 from __future__ import annotations
@@ -74,7 +73,5 @@
     assert scan_collisions(EXP_DIR) == {}
 
 
-def test_known_seq_collision_still_detected():
-    cols = scan_collisions(SEQ_DIR)
-    assert "ECHEUVIS_postseq" in cols
-    assert {"ECHEUVIS_seq.py", "HISPEC_seq.py"} <= set(cols["ECHEUVIS_postseq"])
+def test_hte_seq_libraries_have_no_collisions():
+    assert scan_collisions(SEQ_DIR) == {}
--- a/tests/test_queued_experiments_exist.py
+++ b/tests/test_queued_experiments_exist.py
@@ -71,7 +71,7 @@
 
 # Known config gaps: published sequences that queue a server the config does not
 # launch. anec: heat experiments, not runnable until the TEC server returns.
-# eche10/hispec: CALC/ANA analysis steps whose servers those configs don't define.
+# eche10: CALC analysis steps whose server the config does not define.
 # Shrink-only: stale entries fail test_config_gap_allowlist_has_no_stale_entries.
 KNOWN_CONFIG_GAPS = {
     "anec": {
@@ -86,10 +86,7 @@
         "ECHEUVIS_CA_led",
         "ECHEUVIS_CP_led",
         "ECHEUVIS_CV_led",
-        "ECHEUVIS_postseq",
-        "UVIS_T_postseq",
     },
-    "hispec": {"ECHEUVIS_postseq"},
 }
 CONFIGS = sorted(
     p.stem

```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/servers/analysis/tests/test_analysis_resolution.py helao/deploy/hte/tests/test_queued_experiments_exist.py helao/deploy/hte/tests/test_hte_collisions.py helao/deploy/hte/tests/test_hte_library_import.py helao/deploy/hte/tests/test_preflight_hte.py -q`
Expected: PASS (all). `test_preflight_hte.py[eche10]` must still report `PREFLIGHT OK` with ANA resolved to `analysis_server`.

Run: `grep -rn "ECHEUVIS_analysis_stability\|ECHEUVIS_postseq\|UVIS_T_postseq\|UVIS_analysis_dry\|analyze_echeuvis\"\|analyze_dryuvis" /tmp/claude-1000/wt-parent/helao/deploy/hte --include='*.py' --include='*.yml' --include='*.json'`
Expected: no output except the docstring comment lines in `tests/test_hte_collisions.py` and `tests/test_hte_library_import.py` that name the deleted `ECHEUVIS_postseq` collision.

- [ ] **Step 5: Mutation check**

```bash
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte diff -- configs/eche10.yml > /tmp/claude-1000/mut-task11.patch
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte apply -R /tmp/claude-1000/mut-task11.patch
cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest "helao/deploy/hte/servers/analysis/tests/test_analysis_resolution.py::test_eche10_sync_dispatches_both_uvis_analyses_to_ana" -q   # expect FAIL, KeyError: 'dispatch_analysis'
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte apply /tmp/claude-1000/mut-task11.patch
cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest "helao/deploy/hte/servers/analysis/tests/test_analysis_resolution.py::test_eche10_sync_dispatches_both_uvis_analyses_to_ana" -q   # expect PASS
```

- [ ] **Step 6: README**

In `$H/servers/analysis/README.md`:
1. `## Notes` bullet `- The `hte` configs only carry this server commented out (`analyses: [icpms_local, xrfs_local]`).` becomes
   `- `eche10.yml` runs this server as `ANA` (`analyses: [uvis_bkgsubnorm, echeuvis_stability]`, `local_only: true` until its station check passes, so nothing is uploaded yet). Its `SYNC` entry's `postfinish_hooks` dispatch `analyze_uvis_bkgsubnorm` for each finished `UVIS_T` sequence and `analyze_echeuvis_stability` for each `ECHEUVIS_multiCA_led` sequence after the sequence syncs (`helao/core/hooks/builtin/dispatch_analysis.py`); no experiment or sequence dispatches these routes. Other hte configs do not run it.`
2. In the `## Outputs` intro paragraph (rewritten in Task 10), after `Both analyses are queued by an `analyze_<module>` endpoint` insert ` (on eche10, dispatched by the SYNC `dispatch_analysis` post-finish hook; see Notes)`.

Run: `cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/tests/test_readme_outputs.py -q`
Expected: PASS.

- [ ] **Step 7: Commit (main session; subagents never commit)**

```bash
/home/dan/miniforge3/envs/helao/bin/black /tmp/claude-1000/wt-parent/helao/deploy/hte/experiments/ECHEUVIS_exp.py /tmp/claude-1000/wt-parent/helao/deploy/hte/experiments/UVIS_exp.py /tmp/claude-1000/wt-parent/helao/deploy/hte/sequences/ECHEUVIS_seq.py /tmp/claude-1000/wt-parent/helao/deploy/hte/sequences/HISPEC_seq.py /tmp/claude-1000/wt-parent/helao/deploy/hte/sequences/UVIS_T_seq.py /tmp/claude-1000/wt-parent/helao/deploy/hte/tests/test_queued_experiments_exist.py /tmp/claude-1000/wt-parent/helao/deploy/hte/tests/test_hte_collisions.py /tmp/claude-1000/wt-parent/helao/deploy/hte/tests/test_hte_library_import.py /tmp/claude-1000/wt-parent/helao/deploy/hte/servers/analysis/tests/test_analysis_resolution.py
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte branch --show-current   # expect fix/catalog-bugfixes
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte status --short
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte add configs/eche10.yml experiments/ECHEUVIS_exp.py experiments/UVIS_exp.py sequences/ECHEUVIS_seq.py sequences/HISPEC_seq.py sequences/UVIS_T_seq.py tests/test_queued_experiments_exist.py tests/test_hte_collisions.py tests/test_hte_library_import.py tests/checklists/_collisions.json servers/analysis/tests/test_analysis_resolution.py servers/analysis/README.md
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte commit -m "feat(eche10): dispatch uvis analyses from SYNC; drop dangling postseq path"
```

The eche10 config change reaches the station only through the "hte analyses port" station check after deploy approval.

---

---

### Task 12: H7 biologic olecom registers `.mps/.mpr/.mpt` with `track_file` (hte)

**Files:**
- Modify: `helao/deploy/hte/servers/biologic/biologic_ole/driver.py:36-38` (module docstring), `:125-127` (new `self.shipped`), `:385` and `:474` (reset in `setup`/`setup_protocol`), `:686-709` (`_ship_artifacts`), `:711-726` (`cleanup` returns `data["files"]`)
- Modify: `helao/deploy/hte/servers/biologic/biologic_server.py:312` (`BiologicExec._post_exec`)
- Modify: `helao/deploy/hte/servers/biologic/CLAUDE.md:61-64`
- Test: `helao/deploy/hte/tests/test_ole_driver.py:257-276` (extend); Create: `helao/deploy/hte/servers/biologic/tests/test_biologic_ole_track_files.py`
- Docs: `helao/deploy/hte/servers/biologic/README.md` ("Files moved into the action directory" section, Notes)

**Interfaces:**
- Consumes: `ActionSession.track_file(file_type: str, file_path: str, samples, action=None)` (`helao/hexagon/app/action_session.py:469`; `FileInfo.file_name` made relative to the action dir by `helao/hexagon/adapters/native/data_file.py:446-484`); `Action.samples_in: list[SampleUnion]` (`helao/core/models/action.py:143`); `DriverResponse.data: dict` default `{}` (`helao/core/drivers/helao_driver.py:75`).
- Produces: `BiologicOleDriver.shipped: dict[int, list[str]]`; olecom `cleanup(channel)` returns `DriverResponse(..., data={"files": [<abs path>, ...]})`; file types `biologic_mps`, `biologic_mpr`, `biologic_mpt`. eclib/eclib2 `cleanup` return bare `DriverResponse` (`data == {}`), so `_post_exec` tracks nothing for them and the `BiologicBackend` Protocol is unchanged. `BiologicProtocolExec` inherits `_post_exec`, so `run_protocol` is covered.

Expected values (independent of the fix): the sim writes the patched `CA.mps` into the run dir; the test touches `run_01_CA.mpr` there. After `cleanup`, the action dir holds exactly those two files, and `data["files"]` must be their sorted absolute paths (the driver moves in `sorted(run_dir.iterdir())` order, and `C` < `r`). Today `resp.data == {}` -> `KeyError: 'files'`; today `_post_exec` never calls `track_file`.

Known residual (spec, not fixed here): a `setup`/`setup_protocol` failure ships the `.mps` but the runner skips `_post_exec`, so that file stays local and unregistered; an internal cleanup after a `start_channel` failure is covered because `shipped` is reset only at the next setup.

- [ ] **Step 1: Write the failing test**

(a) Extend the driver test (`git -C $H apply` this patch):

```diff
diff --git a/tests/test_ole_driver.py b/tests/test_ole_driver.py
index fdb755c..f541186 100644
--- a/tests/test_ole_driver.py
+++ b/tests/test_ole_driver.py
@@ -8,6 +8,7 @@ at state Stop with one further drain, never at Stop_rec.
 """
 
 import asyncio
+from pathlib import Path
 
 import pytest
 
@@ -270,8 +271,15 @@ def test_cleanup_moves_the_artifacts_into_the_action_directory(tmp_path, ca_temp
     for _ in range(10):
         if asyncio.run(driver.get_data(0)).message == "done":
             break
-    driver.cleanup(0)
+    (driver.scratch[0] / "run_01_CA.mpr").write_bytes(b"\x00")  # EC-Lab's record
+    resp = driver.cleanup(0)
     assert list(action_dir.glob("*.mps")), list(action_dir.iterdir())
+    shipped = sorted(
+        str(p) for p in action_dir.iterdir() if p.suffix in (".mps", ".mpr")
+    )
+    assert len(shipped) == 2
+    assert resp.data["files"] == shipped
+    assert all(Path(f).is_file() for f in resp.data["files"])
 
 
 def test_the_simulator_reports_the_configured_channel_count():

```

(b) Create `$H/servers/biologic/tests/test_biologic_ole_track_files.py`:

```python
"""BiologicExec registers the vendor files a backend's ``cleanup`` reports.

Only the OLE backend moves files into the action directory (``.mps``, ``.mpr``,
``.mpt``); the syncer uploads the record's ``files`` list, so each must be
tracked. eclib/eclib2 responses carry no ``files`` and must track nothing.
"""

import asyncio
from types import SimpleNamespace

from helao.core.drivers.helao_driver import (
    DriverResponse,
    DriverResponseType,
    DriverStatus,
)
from helao.core.error import ErrorCodes
from helao.deploy.hte.servers.biologic.biologic_server import BiologicExec


class _Driver:
    def __init__(self, data):
        self.data = data

    def cleanup(self, channel):
        return DriverResponse(
            response=DriverResponseType.success, status=DriverStatus.ok, data=self.data
        )


def _exec(data):
    calls = []

    async def track_file(file_type, file_path, samples, action=None):
        calls.append((file_type, file_path, samples))

    ex = object.__new__(BiologicExec)
    ex.driver = _Driver(data)
    ex.channel = 0
    ex.data_buffer = {}
    ex.action_params = {}
    ex.active = SimpleNamespace(
        action=SimpleNamespace(
            action_name="run_CA", action_params={}, samples_in=["sample"]
        ),
        track_file=track_file,
    )
    return ex, calls


def test_olecom_files_are_tracked_once_each_with_a_per_suffix_type():
    files = ["/run/CA.mps", "/run/run_01_CA.mpr", "/run/run_01_CA.mpt"]
    ex, calls = _exec({"files": files})
    out = asyncio.run(ex._post_exec())
    assert calls == [
        ("biologic_mps", "/run/CA.mps", ["sample"]),
        ("biologic_mpr", "/run/run_01_CA.mpr", ["sample"]),
        ("biologic_mpt", "/run/run_01_CA.mpt", ["sample"]),
    ]
    assert out["error"] == ErrorCodes.none


def test_an_eclib_shaped_cleanup_tracks_nothing():
    ex, calls = _exec({})
    asyncio.run(ex._post_exec())
    assert calls == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/tests/test_ole_driver.py::test_cleanup_moves_the_artifacts_into_the_action_directory helao/deploy/hte/servers/biologic/tests/test_biologic_ole_track_files.py -v`
Expected: `test_cleanup_moves_the_artifacts_into_the_action_directory` FAIL with `KeyError: 'files'`; `test_olecom_files_are_tracked_once_each_with_a_per_suffix_type` FAIL with `assert [] == [('biologic_mps', '/run/CA.mps', ['sample']), ...]`; `test_an_eclib_shaped_cleanup_tracks_nothing` PASS (regression guard).

- [ ] **Step 3: Write minimal implementation**

Apply exactly these patches (save as `/tmp/claude-1000/task12.patch`, `git -C /tmp/claude-1000/wt-parent/helao/deploy/hte apply /tmp/claude-1000/task12.patch`). The docstring edits remove the retired `HelaoYml.misc_files` glob wording (`driver.py:37`, `:690`).

```diff
diff --git a/servers/biologic/biologic_ole/driver.py b/servers/biologic/biologic_ole/driver.py
index d38adfb..0d4c89f 100644
--- a/servers/biologic/biologic_ole/driver.py
+++ b/servers/biologic/biologic_ole/driver.py
@@ -34,8 +34,9 @@ to keep in mind when editing it:
   thread blocked -- the honest trade, since the alternative is a wedged
   server.
 * **Artifacts move at cleanup, not during the run.** EC-Lab writes the MPR
-  continuously and ``HelaoYml.misc_files`` globs live directories, so a file
-  written straight into the action directory would be uploaded torn.
+  continuously, so the files ``cleanup`` moves into the action directory and
+  reports in ``data["files"]`` are complete; the executor registers them with
+  ``track_file`` and the syncer uploads them with the record.
 """
 
 import asyncio
@@ -125,6 +126,9 @@ class BiologicOleDriver(HelaoDriver):
         self.output_dirs: dict[int, Optional[Path]] = {
             i: None for i in range(self.num_channels)
         }
+        # artifacts moved into the action dir, per channel; reset at setup so
+        # an internal cleanup (start failure) does not lose them
+        self.shipped: dict[int, list[str]] = {i: [] for i in range(self.num_channels)}
         self.stopping = False
         self._pool = concurrent.futures.ThreadPoolExecutor(
             max_workers=1, thread_name_prefix="olecom"
@@ -389,6 +393,7 @@ class BiologicOleDriver(HelaoDriver):
                 raise ValueError(f"Channel {channel} does not exist.")
             if self.channels[channel] is not None:
                 raise ValueError(f"Channel {channel} is in use.")
+            self.shipped[channel] = []
             doc = self._patch(technique, action_params)
             ttl = mps_assemble.ttl_plan_from_params(action_params)
             if ttl.is_active:
@@ -467,6 +472,7 @@ class BiologicOleDriver(HelaoDriver):
                 raise ValueError(f"Channel {channel} does not exist.")
             if self.channels[channel] is not None:
                 raise ValueError(f"Channel {channel} is in use.")
+            self.shipped[channel] = []
             root = self.protocol_dir.resolve()
             resolved = (root / mps_path).resolve()
             if not resolved.is_relative_to(root):
@@ -687,9 +693,9 @@ class BiologicOleDriver(HelaoDriver):
         """Move the run's ``.mps`` and ``.mpr`` into the action directory.
 
         Moved at cleanup rather than written there: EC-Lab appends to the MPR
-        for the whole run and ``HelaoYml.misc_files`` globs live directories,
-        so a file written straight into the action directory could be uploaded
-        half-finished. A failure here is logged and swallowed -- losing the
+        for the whole run, so only a finished file is moved. Each moved path is
+        kept in ``self.shipped[channel]`` (until the next setup) for ``cleanup``
+        to report. A failure here is logged and swallowed -- losing the
         provenance copy must not fail an otherwise good action.
         """
         run_dir, output_dir = self.scratch.get(channel), self.output_dirs.get(channel)
@@ -700,6 +706,7 @@ class BiologicOleDriver(HelaoDriver):
             for path in sorted(run_dir.iterdir()):
                 if path.suffix.lower() in (".mps", ".mpr", ".mpt"):
                     shutil.move(str(path), str(output_dir / path.name))
+                    self.shipped[channel].append(str(output_dir / path.name))
         except Exception:
             LOGGER.warning(
                 "could not ship OLE artifacts for channel %s from %s",
@@ -722,7 +729,9 @@ class BiologicOleDriver(HelaoDriver):
             self.scratch[channel] = None
             self.output_dirs[channel] = None
             return DriverResponse(
-                response=DriverResponseType.success, status=DriverStatus.ok
+                response=DriverResponseType.success,
+                status=DriverStatus.ok,
+                data={"files": list(self.shipped[channel])},
             )
         except Exception as exc:
             LOGGER.error("cleanup failed", exc_info=True)

diff --git a/servers/biologic/biologic_server.py b/servers/biologic/biologic_server.py
index 70475e4..50648c3 100644
--- a/servers/biologic/biologic_server.py
+++ b/servers/biologic/biologic_server.py
@@ -310,6 +310,13 @@ class BiologicExec(Executor):
         """
         LOGGER.info("BiologicExec running post_exec.")
         resp = self.driver.cleanup(self.channel)
+        # only the OLE backend moves vendor files (.mps/.mpr/.mpt) into the
+        # action directory; register them so the syncer uploads them
+        for path in resp.data.get("files", []):
+            suffix = os.path.splitext(path)[1].lower().lstrip(".")
+            await self.active.track_file(
+                f"biologic_{suffix}", path, self.active.action.samples_in
+            )
 
         # parse calculate outputs from data buffer:
         for k in ["t_s", "Ewe_V", "I_A"]:

```

Then `$H/servers/biologic/CLAUDE.md`, replace the bullet

```
- **The `.mps` and `.mpr` ship with the action, moved at cleanup.** EC-Lab
  appends to the MPR for the whole run and `HelaoYml.misc_files` globs live
  directories, so writing straight into the action directory would upload a
  torn file.
```
with
```
- **The `.mps`, `.mpr` and `.mpt` ship with the action, moved at cleanup.**
  EC-Lab appends to the MPR for the whole run, so the driver moves the files
  only after it, keeps their paths in `shipped[channel]` until the next
  `setup`, and returns them from `cleanup` as `data["files"]`;
  `BiologicExec._post_exec` registers each with `track_file`
  (`biologic_mps`/`biologic_mpr`/`biologic_mpt`), so the syncer uploads them.
  A setup failure skips `_post_exec`, so its `.mps` stays local, unregistered.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/tests/test_ole_driver.py helao/deploy/hte/servers/biologic/tests -q`
Expected: PASS (all; `test_ole_driver.py` 27 passed).

- [ ] **Step 5: Mutation check**

```bash
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte diff -- servers/biologic/biologic_ole/driver.py servers/biologic/biologic_server.py > /tmp/claude-1000/mut-task12.patch
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte apply -R /tmp/claude-1000/mut-task12.patch
cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/tests/test_ole_driver.py::test_cleanup_moves_the_artifacts_into_the_action_directory helao/deploy/hte/servers/biologic/tests/test_biologic_ole_track_files.py -q   # expect 2 failed, 1 passed (Step 2)
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte apply /tmp/claude-1000/mut-task12.patch
cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/tests/test_ole_driver.py::test_cleanup_moves_the_artifacts_into_the_action_directory helao/deploy/hte/servers/biologic/tests/test_biologic_ole_track_files.py -q   # expect 3 passed
```

- [ ] **Step 6: README**

First re-point moved citations (HEAD = Task 11's commit):

```bash
cd /tmp/claude-1000/wt-parent/helao/deploy/hte && /home/dan/miniforge3/envs/helao/bin/python /tmp/claude-1000/recite.py . servers/biologic/README.md HEAD servers/biologic/biologic_server.py servers/biologic/biologic_ole/driver.py
```
Expected: no `UNRESOLVED` lines (range cites such as `driver.py:685-702` are skipped by design; they sit in the paragraph replaced next).

Then in `$H/servers/biologic/README.md`, section `### Files moved into the action directory (`olecom` only)`:
1. Replace the paragraph that starts `These files are moved into the action directory but never registered on the action:` with
   `At `cleanup` the driver moves the run's `.mps`, `.mpr` and `.mpt` files into the action output directory (`helao/deploy/hte/servers/biologic/biologic_ole/driver.py:692-716`, called from `cleanup` at `helao/deploy/hte/servers/biologic/biologic_ole/driver.py:725`) and returns their paths as `data["files"]` (`helao/deploy/hte/servers/biologic/biologic_ole/driver.py:734`). `BiologicExec._post_exec` registers each with `track_file` as file type `biologic_<suffix>` (`biologic_mps`, `biologic_mpr`, `biologic_mpt`) with the action's `samples_in` (`helao/deploy/hte/servers/biologic/biologic_server.py:315-319`), so they are in the record's `files` list and the syncer uploads them. `run_protocol` also copies the unpatched protocol file into the run directory first (`helao/deploy/hte/servers/biologic/biologic_ole/driver.py:505`), so it ships too. When `setup`/`setup_protocol` fails, the patched `.mps` is moved but no `_post_exec` runs, so that file stays local and unregistered. The `eclib` and `eclib2` backends ship no such files (their `setup` takes `output_dir` and never uses it: `helao/deploy/hte/servers/biologic/biologic/driver.py:436`, `helao/deploy/hte/servers/biologic/biologic_eclib2/driver.py:295`).`
2. Table rows: append to the `meaning` cell of the `patched settings` and `protocol copy` rows `; uploaded, file type `biologic_mps``; of `raw measurement` `; uploaded, file type `biologic_mpr``; of `text export` `; uploaded, file type `biologic_mpt``. The `written at` cells were already moved by `recite.py` (`driver.py:702` -> `:708` in both EC-Lab rows, `:402` -> `:407`, `:499` -> `:505`); confirm them.
3. `## Notes`: delete the bullet starting `- The olecom artifacts (`.mps`, `.mpr`, `.mpt`) are moved into the action directory with `shutil.move``.

(Verify the new numbers with `grep -n "def _ship_artifacts\|self._ship_artifacts(channel)\|data={\"files\"\|shutil.move\|copy2(resolved\|write_patched" servers/biologic/biologic_ole/driver.py` and `grep -n "track_file" servers/biologic/biologic_server.py`; expected 692, 725, 734, 708, 505, 407 and 317 (`await` line; the loop spans 315-319).)

Run: `cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/tests/test_readme_outputs.py -q`
Expected: PASS.

- [ ] **Step 7: Commit (main session; subagents never commit)**

```bash
/home/dan/miniforge3/envs/helao/bin/black /tmp/claude-1000/wt-parent/helao/deploy/hte/servers/biologic/biologic_ole/driver.py /tmp/claude-1000/wt-parent/helao/deploy/hte/servers/biologic/biologic_server.py /tmp/claude-1000/wt-parent/helao/deploy/hte/tests/test_ole_driver.py /tmp/claude-1000/wt-parent/helao/deploy/hte/servers/biologic/tests/test_biologic_ole_track_files.py
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte branch --show-current   # expect fix/catalog-bugfixes
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte status --short
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte add servers/biologic/biologic_ole/driver.py servers/biologic/biologic_server.py servers/biologic/CLAUDE.md tests/test_ole_driver.py servers/biologic/tests/test_biologic_ole_track_files.py servers/biologic/README.md
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte commit -m "fix(biologic): track olecom .mps/.mpr/.mpt so the syncer uploads them"
```

Station check (after deploy approval): "olecom" row -- a real EC-Lab run tracks and uploads `.mps/.mpr/.mpt`.

---

### Task 13: H8 power_supply endpoints keep the dispatched params (hte)

**Files:**
- Modify: `helao/deploy/hte/servers/power_supply/power_supply_server.py:510-512`, `:552-554`, `:602-606`
- Test: `helao/deploy/hte/tests/test_med_servers_fixes.py` (append)
- Docs: `helao/deploy/hte/servers/power_supply/README.md`

**Interfaces:**
- Consumes: none
- Produces: none

- [ ] **Step 1: Write the failing test**

Append to `/tmp/claude-1000/wt-parent/helao/deploy/hte/tests/test_med_servers_fixes.py` (already imports `types`, `pytest`, `power_supply_server`; `pytest-asyncio` is used by its neighbours):

```python
# power_supply_server: an endpoint must not overwrite the dispatched params
# with its own signature defaults. The orchestrator dispatches with no query
# params, so every kwarg holds its default while action_params (filled by
# build_action) holds the dispatched value.
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name, dispatched",
    [
        ("apply_voltage", {"voltage": 2.5, "sleep_time": 0.2}),
        ("square_wave", {"voltage": 2.5, "sleep_time": 0.2}),
        (
            "constant_current_square_wave",
            {"current": 0.5, "sleep_time": 3.0, "sleep_time1": 4.0, "sleep_time2": 5.0},
        ),
    ],
)
async def test_power_supply_keeps_dispatched_params(monkeypatch, name, dispatched):
    funcs = {}
    app = types.SimpleNamespace(
        server=types.SimpleNamespace(server_name="PS"),
        server_params={},
        action=lambda: lambda f: funcs.setdefault(f.__name__, f),
    )
    await power_supply_server.power_supply_dyn_endpoints(app)
    for cls in (
        "ApplyVoltageExecutor",
        "SquareWaveExecutor",
        "ConstantCurrentSquareWaveExecutor",
    ):
        monkeypatch.setattr(power_supply_server, cls, lambda active, oneoff: None)
    active = types.SimpleNamespace(
        action=types.SimpleNamespace(action_params=dict(dispatched), action_abbr=None),
        start_executor=lambda ex: {},
    )

    class Ctx:
        async def begin(self, **kw):
            return active

    await funcs[name](Ctx())  # kwargs take their defaults, as under the orchestrator
    assert active.action.action_params == dispatched
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/tests/test_med_servers_fixes.py -v -k keeps_dispatched_params`
Expected: 3 FAIL, e.g. `{'voltage': 1.0} != {'voltage': 2.5}` and `{'sleep_time': 0.05} != {'sleep_time': 0.2}`.

- [ ] **Step 3: Write minimal implementation**

In `/tmp/claude-1000/wt-parent/helao/deploy/hte/servers/power_supply/power_supply_server.py` delete these lines (`build_action` already put every key into `action_params`, `helao/hexagon/app/action_context.py:252-263`):

`:510-512` (in `apply_voltage`):
```python
        # Save parameters to action_params
        active.action.action_params["voltage"] = voltage
        active.action.action_params["sleep_time"] = sleep_time
```
`:552-554` (in `square_wave`):
```python
        # Save parameters to action_params
        active.action.action_params["voltage"] = voltage
        active.action.action_params["sleep_time"] = sleep_time
```
`:602-606` (in `constant_current_square_wave`):
```python
        # Save parameters to action_params
        active.action.action_params["current"] = current
        active.action.action_params["sleep_time"] = sleep_time
        active.action.action_params["sleep_time1"] = sleep_time1
        active.action.action_params["sleep_time2"] = sleep_time2
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/tests/test_med_servers_fixes.py -v`
Expected: PASS (whole file, including `test_power_supply_hlo_columns_match_polled_keys`).

- [ ] **Step 5: Mutation check**

```bash
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte diff -- servers/power_supply/power_supply_server.py > /tmp/claude-1000/mut-task13.patch && git -C /tmp/claude-1000/wt-parent/helao/deploy/hte apply -R /tmp/claude-1000/mut-task13.patch
cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/tests/test_med_servers_fixes.py -q -k keeps_dispatched_params
```
Expected: 3 FAIL. Then `git -C /tmp/claude-1000/wt-parent/helao/deploy/hte apply /tmp/claude-1000/mut-task13.patch` and rerun → 3 PASS.

- [ ] **Step 6: README**

In `/tmp/claude-1000/wt-parent/helao/deploy/hte/servers/power_supply/README.md`:
- `## Outputs` intro paragraph: delete the last sentence `Every `-act.json` also records the parameters the endpoint re-writes into `action_params`: the caller's value, or the endpoint default when the caller omitted it.`
- In each of `### `apply_voltage``, `### `square_wave``, `### `constant_current_square_wave``: delete the `Action results (in `-act.json`):` line and its whole table (the `voltage`/`sleep_time`, `voltage`/`sleep_time`, `current`/`sleep_time`/`sleep_time1`/`sleep_time2` rows) and put in its place the line `No action results (`voltage`, `sleep_time` etc. are inputs; the executor reads them from `action_params` as dispatched).` Signature params the action never rewrites are inputs, not results (output-catalog rule).
- Executor citations `:515`, `:557`, `:609` and `action_abbr` `:509`, `:551`, `:601`, and header citations `:541-548`, `:591-598` shift up by 3 / 6 / 11 lines; re-derive each with `grep -n "Executor(active=active\|action_abbr = \|hloheader=HloHeaderModel" servers/power_supply/power_supply_server.py`, and `:637-640` (`/stop_private`) shifts up by 11.
- `## Notes`: delete the bullet starting `- Defect (latent: no in-tree caller): `build_action` adds an endpoint kwarg to `action_params` only when the key is missing`.

Guard: `cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/tests/test_readme_outputs.py -q` → PASS.

- [ ] **Step 7: Commit (main session; subagents never commit)**

```bash
/home/dan/miniforge3/envs/helao/bin/black /tmp/claude-1000/wt-parent/helao/deploy/hte/servers/power_supply/power_supply_server.py /tmp/claude-1000/wt-parent/helao/deploy/hte/tests/test_med_servers_fixes.py
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte branch --show-current   # expect fix/catalog-bugfixes
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte status --short
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte add servers/power_supply/power_supply_server.py tests/test_med_servers_fixes.py servers/power_supply/README.md
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte commit -m "fix(power_supply): stop overwriting dispatched params with endpoint defaults"
```

---

---

### Task 14: H9 `MxytoMPlate` endpoint enqueues a serializable list (hte)

**Files:**
- Modify: `helao/deploy/hte/servers/galil_motion/galil_motion.py:262-268`
- Test: `helao/deploy/hte/tests/test_motion_private_endpoints.py` (append)
- Docs: `helao/deploy/hte/servers/galil_motion/README.md`

**Interfaces:**
- Consumes: Task 3: `TransformXY.get_Mplate_Msystem(Mxy, *args, **kwargs)` (`helao/hexagon/domain/motion_transform.py`) `json.loads` a `str` `Mxy`, raises `ValueError("Mxy required")` on `None`, returns `np.matrix` (3x3) or `None` for a singular `Minstr`. Must be in `/tmp/claude-1000/wt-parent` (Task 6 Step 0).
- Produces: none

- [ ] **Step 1: Write the failing test**

Append to `/tmp/claude-1000/wt-parent/helao/deploy/hte/tests/test_motion_private_endpoints.py` (uses its `_galil_app`, `GALIL_CFG`, `asyncio`):

```python
# --------------------------------------------------------------------------
# galil: MxytoMPlate (catalog bugfixes H9)
# --------------------------------------------------------------------------


def test_mxytomplate_enqueues_a_serializable_list():
    """The JSON-string ``Mxy`` the route declares must yield a list row.

    ``GALIL_CFG`` has no ``M_instr`` and the fake app no ``helaodirs``, so the
    driver's instrument matrix is the identity; factoring the identity out of
    an identity system matrix gives the identity plate matrix.
    """
    from helao.helpers.premodels import Action
    from helao.helpers.to_json import hlo_json_dumps

    app, _ = _galil_app()
    captured = []

    class _Active:
        action = Action(
            action_name="MxytoMPlate",
            action_params={"Mxy": "[[1,0,0],[0,1,0],[0,0,1]]"},
        )

        async def enqueue_data_dflt(self, datadict):
            captured.append(datadict)

        async def finish(self):
            return self.action

    class _Ctx:
        async def begin(self, **kw):
            return _Active()

    asyncio.run(app.routes["/MOTOR/MxytoMPlate"].fn(ctx=_Ctx()))
    assert len(captured) == 1
    hlo_json_dumps(captured[0])  # the data-stream serializer; np.matrix raises TypeError
    assert captured[0]["mplate"] == [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/tests/test_motion_private_endpoints.py -v -k mxytomplate`
Expected (Task 3 present in the parent worktree): FAIL with `TypeError: Type is not JSON serializable: matrix` from `hlo_json_dumps`. (Without Task 3 it fails earlier with `IndexError: too many indices for array: array is 0-dimensional` — if you see that, Step 0 of Task 6 was skipped; stop and refresh the parent worktree.)

- [ ] **Step 3: Write minimal implementation**

In `/tmp/claude-1000/wt-parent/helao/deploy/hte/servers/galil_motion/galil_motion.py` replace `:262-268`:

```python
            active = await ctx.begin(action_abbr="mxytomplate")
            await active.enqueue_data_dflt(
                datadict={
                    "mplate": app.driver.transform.get_Mplate_Msystem(
                        **active.action.action_params
                    )
                }
            )
```

with:

```python
            active = await ctx.begin(action_abbr="mxytomplate")
            M = app.driver.transform.get_Mplate_Msystem(**active.action.action_params)
            # np.matrix is not serializable; a singular Minstr gives None -> null
            await active.enqueue_data_dflt(
                datadict={"mplate": None if M is None else M.tolist()}
            )
```

The route signature (`Mxy: Optional[str] = None`) is frozen in `tests/checklists/galil_motion.json`; do not change it.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/tests/test_motion_private_endpoints.py -v`
Expected: PASS (whole file).
Regression (frozen route gate): `cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/tests/test_route_checklist.py -q` → PASS.

- [ ] **Step 5: Mutation check**

```bash
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte diff -- servers/galil_motion/galil_motion.py > /tmp/claude-1000/mut-task14.patch && git -C /tmp/claude-1000/wt-parent/helao/deploy/hte apply -R /tmp/claude-1000/mut-task14.patch
cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/tests/test_motion_private_endpoints.py -q -k mxytomplate
```
Expected: FAIL (`TypeError: Type is not JSON serializable: matrix`). Then `git -C /tmp/claude-1000/wt-parent/helao/deploy/hte apply /tmp/claude-1000/mut-task14.patch` and rerun → PASS.

- [ ] **Step 6: README**

In `/tmp/claude-1000/wt-parent/helao/deploy/hte/servers/galil_motion/README.md`:
- `### Plate-alignment and transform actions` table, `MxytoMPlate` row: replace the third/fourth-column text starting `none in practice: the `Mxy` param is `Optional[str]` ...` with `` `mplate`: `float \| null`, `list[list[float]]` (3x3): the plate matrix `Minstr^-1 · Mxy` from the JSON-string `Mxy` (`helao/hexagon/domain/motion_transform.py`, `get_Mplate_Msystem`); `null` when `Minstr` is singular. `Mxy` absent raises `ValueError("Mxy required")` (HTTP 500, no row) ``, and set the "written at" cell to the new `enqueue_data_dflt` line (`grep -n '"mplate"' servers/galil_motion/galil_motion.py`).
- `## Notes`: delete the bullet starting `- `MxytoMPlate` cannot work as registered:`.

Guard: `cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/tests/test_readme_outputs.py -q` → PASS.

- [ ] **Step 7: Commit (main session; subagents never commit)**

```bash
/home/dan/miniforge3/envs/helao/bin/black /tmp/claude-1000/wt-parent/helao/deploy/hte/servers/galil_motion/galil_motion.py /tmp/claude-1000/wt-parent/helao/deploy/hte/tests/test_motion_private_endpoints.py
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte branch --show-current   # expect fix/catalog-bugfixes
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte status --short
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte add servers/galil_motion/galil_motion.py tests/test_motion_private_endpoints.py servers/galil_motion/README.md
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte commit -m "fix(galil): MxytoMPlate enqueues the plate matrix as a list"
```

---

---

### Task 15: H10 sample `_tray_pos` string keys (hte)

**Files:**
- Modify: `helao/deploy/hte/servers/sample/sample_server.py:906-907` (`:909-910` after Task 6's 3-line logger block)
- Test: `helao/deploy/hte/servers/sample/tests/test_get_loaded_positions.py` (new)
- Docs: `helao/deploy/hte/servers/sample/README.md`

**Interfaces:**
- Consumes: Task 6's `servers/sample/tests/__init__.py`. Task 4's `HelaoDict` guard (`isinstance(k, str) and k.startswith("__")`) is the parent half of this pair; with string keys this test passes even without it, and Task 4's own test covers the core guard.
- Produces: `-act.json` `action_params._tray_pos` keys of the form `"<tray>,<slot>,<vial>"` (e.g. `"1,1,1"`).

- [ ] **Step 1: Write the failing test**

Create `/tmp/claude-1000/wt-parent/helao/deploy/hte/servers/sample/tests/test_get_loaded_positions.py`:

```python
"""get_loaded_positions must leave a JSON-serializable -act record.

``_tray_pos`` used ``(tray, slot, vial)`` tuple keys. JSON has no tuple keys,
and ``clean_dict`` (what writes ``-act.json``, meta_writer.py:111) raised for
any loaded vial, so the action could not finish.
"""

import asyncio
import types

from helao.core.models.sample import LiquidSample
from helao.helpers.premodels import Action
from helao.helpers.sample_positions import VT54, Positions
from helao.deploy.hte.servers.sample import sample_server

LABEL = "test__liquid__1"


class _App:
    """Captures the routes ``makeApp`` registers; stands in for ActionHost."""

    def __init__(self, *args, **kwargs):
        self.server_params = {}
        self.routes = {}
        self.driver = None

    def action(self, **kw):
        def deco(fn):
            self.routes[fn.__name__] = fn
            return fn

        return deco

    def post(self, path, **kw):
        return lambda fn: fn


class _Active:
    def __init__(self):
        self.action = Action(action_name="get_loaded_positions", action_params={})

    async def finish(self):
        return self.action


class _Ctx:
    def __init__(self, active):
        self.active = active

    async def begin(self, **kw):
        return self.active


def test_loaded_vial_serializes_with_string_key(monkeypatch):
    monkeypatch.setattr(sample_server, "ActionHost", _App)
    app = sample_server.makeApp("SAMPLE")
    vt = VT54()
    vt.vials[0] = True  # tray 1, slot 1, vial 1 loaded
    vt.samples[0] = LiquidSample(global_label=LABEL)
    app.driver = types.SimpleNamespace(positions=Positions(trays_dict={1: {1: vt}}))
    active = _Active()
    asyncio.run(app.routes["get_positions"](ctx=_Ctx(active)))
    clean = active.action.clean_dict()  # what the -act.json writer serializes
    assert clean["action_params"]["_tray_pos"] == {"1,1,1": LABEL}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/servers/sample/tests/test_get_loaded_positions.py -v`
Expected: FAIL. With Task 4 in the parent worktree: `TypeError: cannot use 'list' as a dict key` (the tuple key is serialized to a list, `helao/core/helaodict.py`); without Task 4: `AttributeError: 'tuple' object has no attribute 'startswith'` (`helao/core/helaodict.py:43`). Either is the tuple-key defect.

- [ ] **Step 3: Write minimal implementation**

In `/tmp/claude-1000/wt-parent/helao/deploy/hte/servers/sample/sample_server.py`, in `get_positions`, replace:

```python
        tray_positions = {
            (traynum, slotnum, vialidx + 1): sample.global_label
```

with:

```python
        tray_positions = {
            f"{traynum},{slotnum},{vialidx + 1}": sample.global_label
```

and in its docstring replace ``tray vials keyed by ``(tray, slot, vial)``)`` with ``tray vials keyed by ``"tray,slot,vial"``)``.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/servers/sample/tests/ -v`
Expected: PASS (this file and Task 6's).
Regression: `cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/tests/test_route_checklist.py helao/deploy/hte/tests/test_hte_library_import.py -q` → PASS.

- [ ] **Step 5: Mutation check**

```bash
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte diff -- servers/sample/sample_server.py > /tmp/claude-1000/mut-task15.patch && git -C /tmp/claude-1000/wt-parent/helao/deploy/hte apply -R /tmp/claude-1000/mut-task15.patch
cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/servers/sample/tests/test_get_loaded_positions.py -q
```
Expected: FAIL (as Step 2). Then `git -C /tmp/claude-1000/wt-parent/helao/deploy/hte apply /tmp/claude-1000/mut-task15.patch` and rerun → PASS. (Task 6 is already committed, so the diff holds only this task's lines.)

- [ ] **Step 6: README**

In `/tmp/claude-1000/wt-parent/helao/deploy/hte/servers/sample/README.md`:
- `get_loaded_positions` results table, `_tray_pos` row: meaning becomes `` `{"<tray>,<slot>,<vial>": global label}` for every loaded vial (e.g. `"1,1,1"`); `{}` when none is loaded ``; type stays `str \| null`, structure `dict`; cite the new key line (`grep -n 'f"{traynum},{slotnum}' servers/sample/sample_server.py`).
- `## Notes`: delete the bullet starting `- `get_loaded_positions` builds `_tray_pos` with `(tray, slot, vial)` tuple keys`.

Guard: `cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/tests/test_readme_outputs.py -q` → PASS.

- [ ] **Step 7: Commit (main session; subagents never commit)**

```bash
/home/dan/miniforge3/envs/helao/bin/black /tmp/claude-1000/wt-parent/helao/deploy/hte/servers/sample/sample_server.py /tmp/claude-1000/wt-parent/helao/deploy/hte/servers/sample/tests/test_get_loaded_positions.py
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte branch --show-current   # expect fix/catalog-bugfixes
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte status --short
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte add servers/sample/sample_server.py servers/sample/tests/test_get_loaded_positions.py servers/sample/README.md
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte commit -m "fix(sample): _tray_pos uses JSON-safe string keys"
```

---

---

### Task 16: H11 sample `tray_new_position` blocks only the returned vial (hte)

**Files:**
- Modify: `helao/deploy/hte/servers/sample/archive_driver.py:766-776`
- Test: `helao/deploy/hte/servers/sample/tests/test_tray_new_position.py` (new)
- Docs: `helao/deploy/hte/servers/sample/README.md`

**Interfaces:**
- Consumes: Task 6's `servers/sample/tests/__init__.py`.
- Produces: none

- [ ] **Step 1: Write the failing test**

Create `/tmp/claude-1000/wt-parent/helao/deploy/hte/servers/sample/tests/test_tray_new_position.py`:

```python
"""Archive.tray_new_position must block only the vial it returns.

The search set ``blocked`` on every new best-fit candidate inside the loop,
so a superseded larger vial stayed blocked (lost to later calls until a
reset or unload). The method touches only ``self.positions``.
"""

import asyncio
import types

from helao.helpers.sample_positions import VT15, VT54, Positions
from helao.deploy.hte.servers.sample.archive_driver import Archive


def test_only_the_returned_vial_is_blocked():
    # VT15 (10 mL, 15 vials) in tray 1 qualifies first for 1 mL; VT54 (2 mL,
    # 54 vials) in tray 2 is smaller and wins. Only the winner is blocked.
    stub = types.SimpleNamespace(
        positions=Positions(trays_dict={1: {1: VT15()}, 2: {1: VT54()}})
    )
    got = asyncio.run(Archive.tray_new_position(stub, req_vol=1.0))
    assert got == {"tray": 2, "slot": 1, "vial": 1}
    assert stub.positions.trays_dict[1][1].blocked == [False] * 15
    assert stub.positions.trays_dict[2][1].blocked[0] is True
    assert stub.positions.trays_dict[2][1].blocked[1:] == [False] * 53
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/servers/sample/tests/test_tray_new_position.py -v`
Expected: FAIL with `assert [True, False, ...] == [False, False, ...]` / `At index 0 diff: True != False` (the superseded VT15 vial 1 stays blocked).

- [ ] **Step 3: Write minimal implementation**

In `/tmp/claude-1000/wt-parent/helao/deploy/hte/servers/sample/archive_driver.py`, inside `tray_new_position`, replace `:766-776`:

```python
                                if position is not None:
                                    new_tray = tray_no
                                    new_slot = slot_no
                                    new_vial = position + 1
                                    new_vial_vol = self.positions.trays_dict[tray_no][
                                        slot_no
                                    ].max_vol_ml
                                    self.positions.trays_dict[tray_no][slot_no].blocked[
                                        position
                                    ] = True

            LOGGER.info(
```

with:

```python
                                if position is not None:
                                    new_tray = tray_no
                                    new_slot = slot_no
                                    new_vial = position + 1
                                    new_vial_vol = self.positions.trays_dict[tray_no][
                                        slot_no
                                    ].max_vol_ml

            if new_tray is not None:
                # reserve only the winner; superseded candidates stay free
                self.positions.trays_dict[new_tray][new_slot].blocked[
                    new_vial - 1
                ] = True

            LOGGER.info(
```

(The per-call `asyncio.Lock()` at `:745` and `req_vol=None` are out of scope per the spec.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/servers/sample/tests/ -v`
Expected: PASS (all three sample test files).
Regression (PAL archive-destination path uses `/tray_new_position`): `cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/servers/pal/tests -q` → PASS.

- [ ] **Step 5: Mutation check**

```bash
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte diff -- servers/sample/archive_driver.py > /tmp/claude-1000/mut-task16.patch && git -C /tmp/claude-1000/wt-parent/helao/deploy/hte apply -R /tmp/claude-1000/mut-task16.patch
cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/servers/sample/tests/test_tray_new_position.py -q
```
Expected: FAIL (as Step 2). Then `git -C /tmp/claude-1000/wt-parent/helao/deploy/hte apply /tmp/claude-1000/mut-task16.patch` and rerun → PASS.

- [ ] **Step 6: README**

In `/tmp/claude-1000/wt-parent/helao/deploy/hte/servers/sample/README.md`:
- `**archive_tray_new_position**` paragraph: replace `; `blocked` is set on each new best-fit candidate the search finds (`helao/deploy/hte/servers/sample/archive_driver.py:774-776`, inside the loop), so earlier, larger best-fit candidates stay blocked as well as the returned one (see Notes)` with `; only the returned vial is marked `blocked`, after the search (`helao/deploy/hte/servers/sample/archive_driver.py:<new blocked line>`)` (`grep -n "reserve only the winner" -A3 servers/sample/archive_driver.py`).
- `## Notes`: delete the bullet starting `- `archive_tray_new_position` sets `blocked[position] = True` inside the search loop`. In the `tray_load ... never calls write_config` bullet, change the trailing `(`helao/deploy/hte/servers/sample/archive_driver.py:774-776`)` citation to the new blocked line.

Guard: `cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/hte/tests/test_readme_outputs.py -q` → PASS.

- [ ] **Step 7: Commit (main session; subagents never commit)**

```bash
/home/dan/miniforge3/envs/helao/bin/black /tmp/claude-1000/wt-parent/helao/deploy/hte/servers/sample/archive_driver.py /tmp/claude-1000/wt-parent/helao/deploy/hte/servers/sample/tests/test_tray_new_position.py
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte branch --show-current   # expect fix/catalog-bugfixes
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte status --short
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte add servers/sample/archive_driver.py servers/sample/tests/test_tray_new_position.py servers/sample/README.md
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte commit -m "fix(sample): tray_new_position blocks only the returned vial"
```

---

### Task 17: C1 xafs non-GAIA campaign defaults + dead `sys.path` block (Deployment-C)

All paths below are relative to `/mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C>` unless absolute. The test is fully monkeypatched: `parse_xafs` (which writes the production standards registry) is never called, and every output lands under `tmp_path`.

**Files:**
- Modify: `scripts/xafs/converters.py:4` (delete `import sys`), `:24-34` (delete the dead `jmnt/kmnt/env_file` block and `sys.path.append`), `:103-104` (campaign defaults)
- Test: `scripts/xafs/tests/test_campaign_default.py` (new)
- Docs: `scripts/xafs/README.md` (`## Notes`, citation renumbering), `servers/analysis/README.md` and `servers/batch_convert/README.md` (citation renumbering only)

**Interfaces:**
- Consumes: none
- Produces: `make_xafs_processes(source_dir, machine_name="hte-xafs-01", save_root=None, campaign_uuid: str | None = None, campaign_name: str | None = None)`; `scripts/xafs/converters.py` no longer imports `sys` (Task 20's AST sweep relies on there being no `sys.path` mutation in this file).

- [ ] **Step 1: Write the failing test**

Create `scripts/xafs/tests/test_campaign_default.py`:

```python
"""A non-GAIA XAFS source (no campaign kwargs) must still write its analysis.

The model field is ``campaign_uuid: Optional[UUID]`` (helao/core/models/analysis.py:131),
so the expected record is derived from the model contract: no campaign given ->
no campaign recorded. ``clean_dict`` drops None, so the key is absent from the
-ana.json, which ``.get`` reads as None.

Everything that touches the network or production is monkeypatched:
``parse_xafs`` would write the standards registry under the production root,
``SESSION`` would build an S3 client, and ``local_only`` keeps the artifact
adapter from uploading.
"""

import asyncio
import datetime
import json
import uuid
from types import SimpleNamespace

import numpy as np
import pandas as pd

from helao.deploy.<Deployment-C>.scripts.xafs import converters
from helao.helpers import config_loader


def _parsed():
    ts = datetime.datetime(2026, 7, 1, 12, 0, 0)
    ref_cols = ["global_label", "save_name"]
    sample = pd.DataFrame(
        {
            "global_label": ["xafs-std__solid__CuO_0"],
            "sample_type": ["solid"],
            "run_use": ["data"],
            "action_uuid": [uuid.uuid4()],
            "experiment_uuid": [uuid.uuid4()],
            "process_uuid": [uuid.uuid4()],
            "action_timestamp": [ts],
            "experiment_timestamp": [ts],
        }
    )
    obj = lambda v: pd.Series([v], dtype=object)  # noqa: E731
    sample["scan_def"] = obj(
        {"estimated_time": 1.0, "zone_defs": [], "advanced_calibration": {}}
    )
    sample["meta"] = obj({})
    sample["data"] = obj(pd.DataFrame({"energy": [1.0, 2.0], "mu": [0.1, 0.2]}))
    sample["mca"] = obj(np.zeros(3))
    sample["processed"] = obj({})
    sample["flattened"] = obj({})
    sample["flat_args"] = obj({"pre1": -150.0})
    sample["flat_meta"] = obj({})
    parsed = {
        "Cu": {
            "calib": pd.DataFrame(columns=ref_cols),
            "izero": pd.DataFrame(columns=ref_cols),
            "sample": sample,
        }
    }
    # (parsed, plate_id, elsys, min_timestamp) -- plate_id None = standard-as-data
    return parsed, None, "Cu", ts


def test_non_gaia_source_writes_its_analysis_without_a_campaign(tmp_path, monkeypatch):
    monkeypatch.setattr(converters, "parse_xafs", lambda source_dir: _parsed())
    monkeypatch.setattr(
        converters,
        "build_xafs_values",
        lambda processed, flattened, flat_args, flat_meta: ({"a": 1.0}, {"b": [1.0]}),
    )
    monkeypatch.setattr(
        converters,
        "SESSION",
        SimpleNamespace(loader=SimpleNamespace(s3_bucket="b", s3_region="r")),
    )
    monkeypatch.setattr(config_loader, "CONFIG", {"local_only": True})
    src = tmp_path / "CuO_pellet_src"
    src.mkdir()

    # no campaign_uuid / campaign_name: exactly what BatchJob.build_converter
    # forwards for the non-GAIA EASYXAFS state root
    asyncio.run(converters.make_xafs_processes(src, save_root=str(tmp_path / "RUNS")))

    ana = sorted((tmp_path / "ANALYSES").rglob("*-ana.json"))
    assert len(ana) == 1, ana
    doc = json.loads(ana[0].read_text(encoding="utf-8"))
    assert doc.get("campaign_uuid") is None
    assert doc.get("campaign_name") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/<Deployment-C>/scripts/xafs/tests/test_campaign_default.py -v`
Expected: FAIL with `pydantic_core._pydantic_core.ValidationError` ... `campaign_uuid` ... `uuid_parsing` (raised by `AnalysisModel(... campaign_uuid="")` at `converters.py:496-512`).

- [ ] **Step 3: Write minimal implementation**

In `scripts/xafs/converters.py`:

1. Delete line 4:
```python
import sys
```
2. Delete lines 24-34 (the block between `from .parsers import parse_xafs` + blank line and `import helao.helpers.helao_logging as logging`), i.e. remove exactly:
```python
if sys.platform == "linux":
    jmnt = "/mnt/j"
    kmnt = "/mnt/k"
    env_file = "helao_data_nb.env"
else:
    jmnt = "j:"
    kmnt = "k:"
    env_file = "helao_data.env"

sys.path.append(jmnt + "/repos/helao-async")

```
so that `from .parsers import parse_xafs`, one blank line, then `import helao.helpers.helao_logging as logging  # get LOGGER from BaseAPI instance` follow each other. Leave the commented-out `# pgs3.LOADER = ...` line untouched.
3. Change the signature defaults (old lines 103-104):
```python
    campaign_uuid: str = "",
    campaign_name: str = "",
```
to
```python
    campaign_uuid: str | None = None,
    campaign_name: str | None = None,
```
The three `if campaign_uuid and campaign_name:` guards stay as they are.

Check: `grep -n "sys\.\|jmnt\|kmnt\|env_file" scripts/xafs/converters.py` prints only the commented `# pgs3.LOADER = ... {kmnt} ... {env_file}` line.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/<Deployment-C>/scripts/xafs/tests/test_campaign_default.py -v`
Expected: PASS.
Then the existing xafs suite: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/<Deployment-C>/scripts/xafs/tests/test_skip_recorded.py helao/deploy/<Deployment-C>/scripts/xafs/tests/test_normalize.py -q`
Expected: all pass.

- [ ] **Step 5: Mutation check**

`git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> diff -- scripts/xafs/converters.py > /tmp/claude-1000/mut-task17.patch && git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> apply -R /tmp/claude-1000/mut-task17.patch`
Run the Step 4 command for `test_campaign_default.py` -> Expected FAIL with the `uuid_parsing` ValidationError (same as Step 2).
`git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> apply /tmp/claude-1000/mut-task17.patch`; rerun -> PASS. (The reverted code is only imported by the monkeypatched test; no CLI or converter runs against production.)

- [ ] **Step 6: README**

1. `scripts/xafs/README.md` `## Notes`: delete the whole bullet that begins `- Non-campaign sources fail at the analysis step. Trace: the \`EASYXAFS\` source gets no campaign override` (currently line 151).
2. In the same README, the `campaign_name`, `campaign_uuid` row of `#### Analysis \`XAFS_normalize_flatten\`` currently ends `...; see Notes for the non-campaign case | \`helao/deploy/<Deployment-C>/scripts/xafs/converters.py:510-511\` |`. Replace the meaning cell with: `campaign metadata; present only for GAIA sources. Non-GAIA sources pass None (the converter default), and \`clean_dict\` drops None (\`helao/core/helaodict.py:146-150\`), so the keys are absent from the record`.
3. Renumber the converter citations shifted by the 12 deleted lines (old line 4 and old 24-34). Save this helper as `/tmp/claude-1000/renumber_citations.py` (scratch, not committed):

```python
"""Shift `<cited>:N` / `<cited>:N-M` citations after lines were deleted.

usage: python renumber_citations.py <cited path> <deleted old lines, e.g. 4,24-34> <md>...
Refuses (writes nothing) if a citation points into a deleted range.
"""

import re
import sys

cited, spec, *files = sys.argv[1:]
dels = []
for part in spec.split(","):
    a, _, b = part.partition("-")
    dels.append((int(a), int(b or a)))


def new(n):
    if any(a <= n <= b for a, b in dels):
        sys.exit(f"{cited}:{n} cites a deleted line; fix that citation by hand first")
    return n - sum(b - a + 1 for a, b in dels if b < n)


pat = re.compile(re.escape(cited) + r":(\d+)(-(\d+))?")
out = {}
for f in files:
    text = open(f, encoding="utf-8").read()
    out[f] = pat.sub(
        lambda m: f"{cited}:{new(int(m[1]))}" + (f"-{new(int(m[3]))}" if m[3] else ""),
        text,
    )
for f, text in out.items():
    open(f, "w", encoding="utf-8").write(text)
    print("rewrote", f)
```

Run (after the Notes bullet in item 1 is deleted, since it is the only citation into the deleted block):
`cd /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> && /home/dan/miniforge3/envs/helao/bin/python /tmp/claude-1000/renumber_citations.py helao/deploy/<Deployment-C>/scripts/xafs/converters.py 4,24-34 scripts/xafs/README.md servers/analysis/README.md servers/batch_convert/README.md`
Then verify by hand: `grep -n "xafs/converters.py:" scripts/xafs/README.md` and spot-check three citations with `sed -n '<N>p' scripts/xafs/converters.py` (e.g. the `campaign_name=campaign_name,` line must be the one the campaign row cites). Shorthand citations (`:NNN` without the path) next to a converters citation in `scripts/xafs/README.md` are not touched by the helper: `grep -n "converters.py" scripts/xafs/README.md` and subtract 12 by hand from any bare `:NNN` (NNN >= 35) in those lines. Do not touch `docs/` or `tests/fixtures/` READMEs (historical).
4. Guard: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/<Deployment-C>/tests/test_readme_outputs.py -q` -> PASS.

- [ ] **Step 7: Commit (main session; subagents never commit)**

```bash
/home/dan/miniforge3/envs/helao/bin/black /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C>/scripts/xafs/converters.py /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C>/scripts/xafs/tests/test_campaign_default.py
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> branch --show-current   # expect main
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> status --short
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> add scripts/xafs/converters.py scripts/xafs/tests/test_campaign_default.py scripts/xafs/README.md servers/analysis/README.md servers/batch_convert/README.md
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> commit -m "fix(xafs): non-GAIA sources default campaign to None; drop dead sys.path append"
```

- [ ] **Step 8: Read-only inventory on note1 (main session only, writes nothing)**

Only after Step 7, and only from the main session. Every command is read-only on note1 (`ls`, `grep -l`, `find`, a python script that only reads and prints); the output is captured locally. Nothing is deleted, moved or re-dropped; cleanup is decided by the user after reading the list.

```bash
ssh -o BatchMode=yes -i ~/.ssh/id_ed25519_note01 hte-note-01.caltech.edu 'bash -s' > /tmp/claude-1000/xafs-inventory.txt 2>&1 <<'EOF'
set -u
S=/mnt/wd4/SOURCES
echo "== 1. failed/ bundles whose state.json holds the uuid_parsing error"
for r in EASYXAFS EASYXAFS_GAIA; do
  for f in "$S/$r/failed/"*.state.json; do
    [ -e "$f" ] || continue
    grep -lE 'uuid_parsing|valid UUID' "$f"
  done
done
echo "== 2. anything in processing/ or drop/"
for r in EASYXAFS EASYXAFS_GAIA; do
  for st in processing drop; do
    echo "-- $r/$st"
    ls -la "$S/$r/$st" 2>&1
  done
done
echo "== 3. RUNS XAFS sequence dirs with no -seq record (partial trees)"
find /mnt/wd4/DATA/RUNS -maxdepth 6 -type d -name '*XAFS_wafer_grid_multiscan*' 2>/dev/null | while read -r d; do
  ls "$d"/*-seq.* >/dev/null 2>&1 || echo "$d"
done
echo "== 4. plate-corrected window check (sequences dated 2026-05-09..2026-05-28)"
cd /srv/scratch/repos/helao-async && PYTHONPATH=/srv/scratch/repos/helao-async /opt/tljh/user/envs/helao/bin/python - <<'PY'
import glob, os, re, subprocess
from helao.helpers.meta_io import read_meta

dirs = subprocess.run(
    ["find", "/mnt/wd4/DATA/RUNS", "-maxdepth", "6", "-type", "d",
     "-name", "*XAFS_wafer_grid_multiscan*"],
    capture_output=True, text=True,
).stdout.splitlines()
may = {}
partial = []
for d in dirs:
    seqs = glob.glob(os.path.join(glob.escape(d), "*-seq.*"))
    if not seqs:
        partial.append(d)
        continue
    doc = read_meta(seqs[0])
    ts = str(doc.get("sequence_timestamp", ""))[:10]
    if "2026-05-09" <= ts <= "2026-05-28":
        may[str(doc.get("sequence_params", {}).get("source_foldername"))] = d
failed = set()
for r in ("EASYXAFS", "EASYXAFS_GAIA"):
    for f in glob.glob(f"/mnt/wd4/SOURCES/{r}/failed/*.state.json"):
        failed.add(os.path.basename(f)[: -len(".state.json")])
print("May-window sequences (superset of the 14 plate-corrected):", len(may))
for name in sorted(may):
    print("  ", name)
print("OVERLAP failed/ x May-window source names:", sorted(set(may) & failed) or "none")
win = re.compile(r"20260(5(09|1\d|2[0-8]))")
print("partial trees inside the May window:", [d for d in partial if win.search(d)] or "none")
PY
EOF
cat /tmp/claude-1000/xafs-inventory.txt
```

Expected: the file lists (1) the failed bundles hit by this bug, (2) any stuck `processing/`/`drop/` entries, (3) partial RUNS trees, (4) `OVERLAP ... none` and `partial trees inside the May window: none`. The 14 plate-corrected sequences were recorded 2026-05-09..05-28 (memory `plate-id-serial-correction.md`), before this bug existed (2026-06-08), so any overlap is a finding to report, not to act on. Report the file's contents to the user; they decide cleanup and re-drop. Those 14 sources must never be re-dropped (`scripts/CLAUDE.md`).

---

---

### Task 18: C2a `reconvert_legacy` roots + dry run writes nothing (Deployment-C)

Static-only verification: the pre-fix CLI defaults to production and is never executed. The tests import the module (constants are strings; nothing runs) and call `_log` with `checkpoint=None`, which on the pre-fix code raises `TypeError` from `open(None, "a")` before any write.

**Files:**
- Modify: `scripts/bruker_gadds/reconvert_legacy.py:49-54` (imports + constants), `:68-73` (`_log`), `:286-460` (`run`: every `_log(args.checkpoint, ...)` call)
- Test: `scripts/bruker_gadds/tests/test_reconvert_legacy_roots.py` (new); existing gate `tests/test_sources_root.py::test_no_module_hardcodes_the_production_sources_root`
- Docs: `scripts/bruker_gadds/README.md`

**Interfaces:**
- Consumes: `scripts/common/roots.py` `sources_root() -> str`, `PRODUCTION_DATA_ROOT: str`
- Produces: `reconvert_legacy._log(checkpoint: str | None, **fields) -> None` (None = print only)

- [ ] **Step 1: Write the failing test**

Create `scripts/bruker_gadds/tests/test_reconvert_legacy_roots.py`:

```python
"""reconvert_legacy follows the guarded roots, and a dry run writes nothing.

Static/unit only: the CLI's defaults point at production, so `run`/`main` are
never executed here.
"""

import importlib
import inspect
import json

from helao.deploy.<Deployment-C>.scripts.bruker_gadds import reconvert_legacy as rl


def test_drop_tree_follows_the_sources_root_override(tmp_path, monkeypatch):
    monkeypatch.setenv("HELAO_SOURCES_ROOT", str(tmp_path))
    try:
        mod = importlib.reload(rl)
        # independent of the fix: <override>/<family>/<stage>, the layout every
        # BatchSource derives from its state_root
        assert mod.DROP == str(tmp_path / "BRUKER_GADDS_GAIA" / "drop")
        assert mod.PROCESSING == str(tmp_path / "BRUKER_GADDS_GAIA" / "processing")
    finally:
        monkeypatch.delenv("HELAO_SOURCES_ROOT")
        importlib.reload(rl)


def test_log_without_a_checkpoint_prints_and_writes_nothing(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rl._log(None, sequence_uuid="u1", status="no_source")
    row = json.loads(capsys.readouterr().out)
    assert row["status"] == "no_source" and row["sequence_uuid"] == "u1"
    assert list(tmp_path.iterdir()) == []


def test_run_never_logs_to_the_checkpoint_directly():
    # every log call in run() goes through the execute-gated checkpoint, so a
    # dry run (no --execute) cannot append to <ROOT>/STATES/...
    assert "_log(args.checkpoint" not in inspect.getsource(rl.run)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/<Deployment-C>/scripts/bruker_gadds/tests/test_reconvert_legacy_roots.py helao/deploy/<Deployment-C>/tests/test_sources_root.py::test_no_module_hardcodes_the_production_sources_root -v`
Expected: 4 FAIL — `assert '/mnt/wd4/SOURCES/BRUKER_GADDS_GAIA/drop' == '<tmp>/BRUKER_GADDS_GAIA/drop'`; `TypeError: expected str, bytes or os.PathLike object, not NoneType`; `assert '_log(args.checkpoint' not in ...`; and the gate's `the production drop-tree root is hardcoded ... bruker_gadds/reconvert_legacy.py`.

- [ ] **Step 3: Write minimal implementation**

In `scripts/bruker_gadds/reconvert_legacy.py`:

1. Lines 49-54, old:
```python
from helao.helpers.meta_io import read_meta
from helao.ui.shared import retire as retire_logic

DROP = "/mnt/wd4/SOURCES/BRUKER_GADDS_GAIA/drop"
PROCESSING = "/mnt/wd4/SOURCES/BRUKER_GADDS_GAIA/processing"
ROOT = "/mnt/wd4/DATA"
```
new:
```python
from helao.helpers.meta_io import read_meta
from helao.ui.shared import retire as retire_logic

from ..common.roots import PRODUCTION_DATA_ROOT, sources_root

DROP = os.path.join(sources_root(), "BRUKER_GADDS_GAIA", "drop")
PROCESSING = os.path.join(sources_root(), "BRUKER_GADDS_GAIA", "processing")
ROOT = PRODUCTION_DATA_ROOT
```
2. `_log` (lines 68-72), old:
```python
def _log(checkpoint: str, **fields) -> None:
    fields["ts"] = datetime.now(timezone.utc).isoformat()
    with open(checkpoint, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(fields) + "\n")
    print(json.dumps(fields), flush=True)
```
new:
```python
def _log(checkpoint: str | None, **fields) -> None:
    """Print one outcome row; append it to ``checkpoint`` only when one is given
    (``run`` passes None on a dry run, so a dry run writes nothing)."""
    fields["ts"] = datetime.now(timezone.utc).isoformat()
    if checkpoint:
        with open(checkpoint, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(fields) + "\n")
    print(json.dumps(fields), flush=True)
```
3. In `run`, directly after `done = _done(args.checkpoint)` (line 304) add:
```python
    ckpt = args.checkpoint if args.execute else None
```
and replace every `_log(\n            args.checkpoint,` / `_log(args.checkpoint, ` call in `run` with `ckpt` in place of `args.checkpoint` (seven call sites: `no_source` :313, `move_failed` (resumed) :333, `inventory_failed` :347, `retire_failed` :390, `move_failed` :403, `copy_failed` :417, `dropped` :430). `_done(args.checkpoint)` stays (read-only).

- [ ] **Step 4: Run test to verify it passes**

Run the Step 2 command. Expected: 4 PASS.
Then: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/<Deployment-C>/tests/test_sources_root.py helao/deploy/<Deployment-C>/scripts/bruker_gadds/tests/test_gadds_batch_process_offline.py -q` -> all pass.

- [ ] **Step 5: Mutation check**

`git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> diff -- scripts/bruker_gadds/reconvert_legacy.py > /tmp/claude-1000/mut-task18.patch && git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> apply -R /tmp/claude-1000/mut-task18.patch`
Run only the test file and the gate (Step 2 command) -> Expected the same 4 FAIL. Never run `reconvert_legacy` itself.
`git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> apply /tmp/claude-1000/mut-task18.patch`; rerun -> PASS.

- [ ] **Step 6: README**

In `scripts/bruker_gadds/README.md`:
- `## Notes`: delete the bullet beginning `- \`reconvert_legacy.py\` hardcodes \`/mnt/wd4/SOURCES/BRUKER_GADDS_GAIA/drop\``.
- Row `| metadata API rows of the old sequence ...`: change `under \`/mnt/wd4/DATA\`` to `under \`ROOT\` = \`roots.PRODUCTION_DATA_ROOT\` (\`/mnt/wd4/DATA\` on Linux)`.
- Row `| a copy of the source folder into \`/mnt/wd4/SOURCES/BRUKER_GADDS_GAIA/drop/<base>\` ...`: change the path to `\`<sources root>/BRUKER_GADDS_GAIA/drop/<base>\`` and append `; \`sources_root()\` is \`/mnt/wd4/SOURCES\` unless \`HELAO_SOURCES_ROOT\` is set (guarded by \`assert_not_production\`)`.
- Row `| checkpoint JSONL, one appended row per outcome ...`: append to the `what` cell `. Without \`--execute\` every row is printed only and the checkpoint is not written`.
- Re-derive the cited lines from the edited file (`grep -n "_log(\|ROOT\b\|copy_into_drop\|--checkpoint" scripts/bruker_gadds/reconvert_legacy.py`) and update the `reconvert_legacy.py:NNN` citations in those rows (the file grew by 4 lines above `_log` and by 1 line in `run`).
- Guard: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/<Deployment-C>/tests/test_readme_outputs.py -q` -> PASS.

- [ ] **Step 7: Commit (main session; subagents never commit)**

```bash
/home/dan/miniforge3/envs/helao/bin/black /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C>/scripts/bruker_gadds/reconvert_legacy.py /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C>/scripts/bruker_gadds/tests/test_reconvert_legacy_roots.py
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> branch --show-current   # expect main
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> status --short
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> add scripts/bruker_gadds/reconvert_legacy.py scripts/bruker_gadds/tests/test_reconvert_legacy_roots.py scripts/bruker_gadds/README.md
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> commit -m "fix(bruker_gadds): reconvert_legacy roots via common.roots; dry run writes no checkpoint"
```

---

---

### Task 19: C2b `/mnt/wd4/DATA` marker in the roots sweep + 7 repair CLIs (Deployment-C)

Static only. No CLI here is executed before or after the fix.

> **Escalation:** the spec lists `servers/analysis/analyses/xrfs_local.py:235` as a `KNOWN_UNMIGRATED` entry, but `find_production_literals` sweeps `scripts/` only (`SCRIPTS_ROOT`), and `test_recorded_residuals_are_still_present_where_recorded` resolves each key under `SCRIPTS_ROOT`, so an entry for a `servers/` file would fail that ledger test. Chosen: no `xrfs_local` entry (the file is outside the sweep, so it needs none); the plan does not widen the sweep root. Widening it to `servers/` is a separate decision for the user.
>
> **Escalation:** six docstring/usage lines also contain the marker (`edax/rebuild_journal_zips.py:10`, `xrfs_calibration/fix_standard_provenance.py:20`, `xrfs_calibration/reconvert_per_standard.py:37`, `xrfs_calibration/standards_registry.py:24`, `xrfs_quantification/backfill_analysis_calibration.py:25`, `xrfs_quantification/backfill_calibration.py:30`). The sweep is line-based, so they would turn the gate red. Chosen: reword those docstring lines (no behaviour change) rather than ledger them.

**Files:**
- Modify: `tests/test_sources_root.py:330` (`_PRODUCTION_MARKERS`), `:345-350` (`KNOWN_UNMIGRATED`), add one vacuity test after `:402`
- Modify: `scripts/edax/reconvert_duplicates.py:53-61`, `scripts/edax/retire_duplicate_records.py:98-106,536`, `scripts/edax/prune_process_sets.py:884` (+ import), `scripts/xrfs_calibration/fix_standard_provenance.py:20,42,246`, `scripts/xrfs_calibration/reconvert_per_standard.py:37,59,319`, `scripts/xrfs_quantification/backfill_calibration.py:30,51,213`, `scripts/xrfs_quantification/backfill_analysis_calibration.py:25,44,288`, docstrings `scripts/edax/rebuild_journal_zips.py:10`, `scripts/xrfs_calibration/standards_registry.py:24`
- Docs: `scripts/edax/README.md`, `scripts/xrfs_calibration/README.md`, `scripts/xrfs_quantification/README.md`

**Interfaces:**
- Consumes: `scripts/common/roots.py` `PRODUCTION_DATA_ROOT`; Task 18's `reconvert_legacy.ROOT = PRODUCTION_DATA_ROOT` (so `reconvert_legacy.py` no longer carries the literal)
- Produces: `_PRODUCTION_MARKERS = ("/mnt/wd4/SOURCES", "/inst_hlo/SOURCES", "/mnt/wd4/DATA")`

- [ ] **Step 1: Write the failing test**

In `tests/test_sources_root.py`:

1. Line 330, old:
```python
_PRODUCTION_MARKERS = ("/mnt/wd4/SOURCES", "/inst_hlo/SOURCES")
```
new:
```python
_PRODUCTION_MARKERS = ("/mnt/wd4/SOURCES", "/inst_hlo/SOURCES", "/mnt/wd4/DATA")
```
and add above it, after the existing comment block, the line:
```python
#: ``/mnt/wd4/DATA`` is the production *data* root; repair CLIs take it from
#: ``roots.PRODUCTION_DATA_ROOT`` so the literal lives in one place.
```
2. `KNOWN_UNMIGRATED` (lines 345-350), add the deny-list entry (a correct use: `legacy_jcap` refuses to write into these roots):
```python
KNOWN_UNMIGRATED: dict[str, set[str]] = {
    "xafs/parsers.py": {
        "{_KMNT}/inst_hlo/SOURCES/EASYXAFS/synced",
        "{_KMNT}/inst_hlo/SOURCES/EASYXAFS_GAIA/synced",
    },
    # deny-list of roots a --type must never write into; not a default
    "legacy_jcap/cli.py": {
        '"/mnt/wd4/DATA_LEGACY',
        '_PRODUCTION_ROOT = "/mnt/wd4/DATA"',
    },
}
```
3. After `test_the_sweep_catches_the_composed_form` add:
```python
def test_the_sweep_finds_a_planted_data_root_literal(tmp_path):
    """Vacuity check for the data-root marker: a repair CLI default."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "repair.py").write_text(
        'ap.add_argument("--root", default="/mnt/wd4/DATA")\n', encoding="utf-8"
    )
    assert "pkg/repair.py" in find_production_literals(tmp_path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/<Deployment-C>/tests/test_sources_root.py -k "hardcodes or planted or composed or residuals" -v`
Expected: `test_no_module_hardcodes_the_production_sources_root` FAILS listing `edax/reconvert_duplicates.py`, `edax/retire_duplicate_records.py`, `edax/prune_process_sets.py`, `edax/rebuild_journal_zips.py`, `xrfs_calibration/fix_standard_provenance.py`, `xrfs_calibration/reconvert_per_standard.py`, `xrfs_calibration/standards_registry.py`, `xrfs_quantification/backfill_calibration.py`, `xrfs_quantification/backfill_analysis_calibration.py`. The planted-literal tests and the residual ledger pass. (To see the new vacuity test fail, temporarily drop the new marker: it then FAILS with `assert 'pkg/repair.py' in {}`.)

- [ ] **Step 3: Write minimal implementation**

Each CLI keeps its default value on note1 byte-for-byte (`PRODUCTION_DATA_ROOT` is `"/mnt/wd4/DATA"` on Linux).

`scripts/edax/reconvert_duplicates.py` — after the `from ..common.sequence_identity import (...)` block (ends line 56) add `from ..common.roots import PRODUCTION_DATA_ROOT`; lines 60-61, old:
```python
DEFAULT_AUDIT = "/mnt/wd4/DATA/STATES/duplicate_records_audit.tsv"
DEFAULT_CHECKPOINT = "/mnt/wd4/DATA/STATES/reconvert_duplicates.jsonl"
```
new:
```python
DEFAULT_AUDIT = os.path.join(PRODUCTION_DATA_ROOT, "STATES", "duplicate_records_audit.tsv")
DEFAULT_CHECKPOINT = os.path.join(
    PRODUCTION_DATA_ROOT, "STATES", "reconvert_duplicates.jsonl"
)
```

`scripts/edax/retire_duplicate_records.py` — after `from .prune_process_sets import ARCHIVE_SUBDIR` (line 98) add `from ..common.roots import PRODUCTION_DATA_ROOT`; lines 102-106, old:
```python
DEFAULT_AUDIT = "/mnt/wd4/DATA/STATES/duplicate_records_audit.tsv"
DEFAULT_LEDGER = "/mnt/wd4/DATA/STATES/retired_records.jsonl"
#: ``reconvert_duplicates``' checkpoint. Read, never written, to refuse a
#: sequence whose local tree has already been rebuilt.
DEFAULT_RECONVERT_CHECKPOINT = "/mnt/wd4/DATA/STATES/reconvert_duplicates.jsonl"
```
new:
```python
DEFAULT_AUDIT = os.path.join(PRODUCTION_DATA_ROOT, "STATES", "duplicate_records_audit.tsv")
DEFAULT_LEDGER = os.path.join(PRODUCTION_DATA_ROOT, "STATES", "retired_records.jsonl")
#: ``reconvert_duplicates``' checkpoint. Read, never written, to refuse a
#: sequence whose local tree has already been rebuilt.
DEFAULT_RECONVERT_CHECKPOINT = os.path.join(
    PRODUCTION_DATA_ROOT, "STATES", "reconvert_duplicates.jsonl"
)
```
and line 536 `default="/mnt/wd4/DATA",` -> `default=PRODUCTION_DATA_ROOT,`.

`scripts/edax/prune_process_sets.py` — add `from ..common.roots import PRODUCTION_DATA_ROOT` after the last top-level import of the module's import block; line 884 `ap.add_argument("--data-root", default="/mnt/wd4/DATA")` -> `ap.add_argument("--data-root", default=PRODUCTION_DATA_ROOT)`.

`scripts/xrfs_calibration/fix_standard_provenance.py` — after line 42 `from . import parquet_library, standards_registry` add `from ..common.roots import PRODUCTION_DATA_ROOT`; line 246 `ap.add_argument("--root", default="/mnt/wd4/DATA", help="instrument data root")` -> `ap.add_argument("--root", default=PRODUCTION_DATA_ROOT, help="instrument data root")`; docstring line 20 `{library,records} [--root /mnt/wd4/DATA] [--dry-run]` -> `{library,records} [--root DATA_ROOT] [--dry-run]`.

`scripts/xrfs_calibration/reconvert_per_standard.py` — after line 59 `from . import parquet_library` add `from ..common.roots import PRODUCTION_DATA_ROOT`; line 319 `ap.add_argument("--root", default="/mnt/wd4/DATA")` -> `ap.add_argument("--root", default=PRODUCTION_DATA_ROOT)`; docstring line 37 `{convert,library} [--root /mnt/wd4/DATA] [--config note1] [--dry-run]` -> `{convert,library} [--root DATA_ROOT] [--config note1] [--dry-run]`. (Its `/mnt/i`, `/mnt/k` literals at :66,80-81 are out of scope.)

`scripts/xrfs_calibration/standards_registry.py` — docstring line 24 `--json-dir DIR --library /mnt/wd4/DATA/DATABASE/orbis_calibration_library.parquet` -> `--json-dir DIR --library <DATA_ROOT>/DATABASE/orbis_calibration_library.parquet`.

`scripts/xrfs_quantification/backfill_calibration.py` — after line 51 `from .backfill_contamination import _seq_member, write_seq_record` add `from ..common.roots import PRODUCTION_DATA_ROOT`; line 213 `ap.add_argument("--root", default="/mnt/wd4/DATA", help="instrument data root")` -> `ap.add_argument("--root", default=PRODUCTION_DATA_ROOT, help="instrument data root")`; docstring line 30 `[--dry-run] [--root /mnt/wd4/DATA] (--ledger LEDGER.jsonl | SEQUENCE ...)` -> `[--dry-run] [--root DATA_ROOT] (--ledger LEDGER.jsonl | SEQUENCE ...)`.

`scripts/xrfs_quantification/backfill_analysis_calibration.py` — after line 44 `from .backfill_contamination import _seq_member` add `from ..common.roots import PRODUCTION_DATA_ROOT`; line 288 `ap.add_argument("--root", default="/mnt/wd4/DATA", help="instrument data root")` -> `ap.add_argument("--root", default=PRODUCTION_DATA_ROOT, help="instrument data root")`; docstring line 25 `[--dry-run] [--root /mnt/wd4/DATA] [--workers 4] --ledger LEDGER.jsonl` -> `[--dry-run] [--root DATA_ROOT] [--workers 4] --ledger LEDGER.jsonl`.

`scripts/edax/rebuild_journal_zips.py` — docstring line 10 `/mnt/wd4/DATA/RUNS_SYNCED/26.05/0204/112327__XRFS_noStandards__SrHfV-101079_interp.zip;` -> `<DATA_ROOT>/RUNS_SYNCED/26.05/0204/112327__XRFS_noStandards__SrHfV-101079_interp.zip;`.

Confirm no literal remains: `grep -rn --include='*.py' '/mnt/wd4/DATA' /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C>/scripts | grep -v '/tests/\|common/roots.py\|legacy_jcap/cli.py'` prints nothing.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/<Deployment-C>/tests/test_sources_root.py -v` -> all PASS.
Import check (imports only, no CLI run): `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/<Deployment-C>/tests/test_import_sweep.py -q` -> PASS.

- [ ] **Step 5: Mutation check**

`git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> diff -- scripts/ > /tmp/claude-1000/mut-task19.patch && git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> apply -R /tmp/claude-1000/mut-task19.patch`
Run `... -m pytest helao/deploy/<Deployment-C>/tests/test_sources_root.py -k hardcodes -v` -> Expected FAIL listing the nine files of Step 2. (Only the test file runs; none of the CLIs.)
`git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> apply /tmp/claude-1000/mut-task19.patch`; rerun -> PASS.

- [ ] **Step 6: README**

- `scripts/edax/README.md` `## Notes`: replace the bullet beginning `- Three repair tools default to the production share:` with:
  `- Three repair tools default to the production data root through \`roots.PRODUCTION_DATA_ROOT\` (\`/mnt/wd4/DATA\` on Linux): \`DEFAULT_AUDIT\`, \`DEFAULT_CHECKPOINT\` (\`reconvert_duplicates.py\`), \`DEFAULT_AUDIT\`, \`DEFAULT_LEDGER\`, \`--data-root\` (\`retire_duplicate_records.py\`) and \`--data-root\` (\`prune_process_sets.py\`). That root is not overridable, so run them with \`--execute\` only on the conversion station; \`tests/test_sources_root.py\` keeps the literal out of these modules.` Re-derive the cited line numbers with `grep -n "PRODUCTION_DATA_ROOT" scripts/edax/*.py` and add them as full `helao/deploy/<Deployment-C>/scripts/edax/<file>.py:NNN` citations.
- `scripts/xrfs_quantification/README.md` `## Notes`: in the bullet beginning `- \`backfill_calibration.py\` and \`backfill_analysis_calibration.py\` default \`--root\` to \`/mnt/wd4/DATA\``, change `default \`--root\` to \`/mnt/wd4/DATA\`` to `default \`--root\` to \`roots.PRODUCTION_DATA_ROOT\` (\`/mnt/wd4/DATA\` on Linux)` and refresh the two `:213`/`:288` citations from `grep -n "PRODUCTION_DATA_ROOT" scripts/xrfs_quantification/backfill_*.py` (each file grew one import line).
- `scripts/xrfs_calibration/README.md` `## Notes` (the bullet at line 179): change `reconvert_per_standard.py\` (\`--root\`, \`STATION_DROPS\`, ...:66,319-321\`)` and `fix_standard_provenance.py\` (\`--root\`, ...:246\`)` so the `--root` defaults read `\`roots.PRODUCTION_DATA_ROOT\``, refreshing the citations by `grep -n "PRODUCTION_DATA_ROOT\|STATION_DROPS" scripts/xrfs_calibration/*.py`. Keep the rest of the bullet.
- Guard: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/<Deployment-C>/tests/test_readme_outputs.py -q` -> PASS.

- [ ] **Step 7: Commit (main session; subagents never commit)**

```bash
cd /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> && /home/dan/miniforge3/envs/helao/bin/black tests/test_sources_root.py scripts/edax/reconvert_duplicates.py scripts/edax/retire_duplicate_records.py scripts/edax/prune_process_sets.py scripts/edax/rebuild_journal_zips.py scripts/xrfs_calibration/fix_standard_provenance.py scripts/xrfs_calibration/reconvert_per_standard.py scripts/xrfs_calibration/standards_registry.py scripts/xrfs_quantification/backfill_calibration.py scripts/xrfs_quantification/backfill_analysis_calibration.py
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> branch --show-current   # expect main
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> status --short
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> add tests/test_sources_root.py scripts/edax/reconvert_duplicates.py scripts/edax/retire_duplicate_records.py scripts/edax/prune_process_sets.py scripts/edax/rebuild_journal_zips.py scripts/xrfs_calibration/fix_standard_provenance.py scripts/xrfs_calibration/reconvert_per_standard.py scripts/xrfs_calibration/standards_registry.py scripts/xrfs_quantification/backfill_calibration.py scripts/xrfs_quantification/backfill_analysis_calibration.py scripts/edax/README.md scripts/xrfs_calibration/README.md scripts/xrfs_quantification/README.md
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> commit -m "fix(scripts): repair CLIs take the data root from common.roots; sweep guards /mnt/wd4/DATA"
```

---

---

### Task 20: C2c no `sys.path` mutation outside tests + edax converter block (Deployment-C)

**Files:**
- Modify: `scripts/edax/converters.py:4` (delete `import sys`), `:32-42` (delete the dead block)
- Test: `tests/test_no_sys_path_mutation.py` (new)
- Docs: `scripts/edax/README.md` (`## Notes` bullet + citation renumbering)

**Interfaces:**
- Consumes: Task 17 already removed the xafs converter's block, so after this task the sweep is green
- Produces: none

- [ ] **Step 1: Write the failing test**

Create `tests/test_no_sys_path_mutation.py`:

```python
"""No module outside tests mutates ``sys.path`` at import.

An append of a network-mount checkout (``/mnt/j/repos/helao-async``) makes every
later failed import in the process stat that mount, and silently imports a
module missing here from the share's old checkout instead.
"""

from __future__ import annotations

import ast
from pathlib import Path

DEPLOY_ROOT = Path(__file__).resolve().parent.parent
_EXCLUDED_DIRS = {"tests", "notes", "docs", "__pycache__", ".omc"}
_MUTATORS = {"append", "insert", "extend"}


def find_sys_path_mutations(root: Path) -> list[str]:
    """``["rel/path.py:line", ...]`` for every ``sys.path.<append|insert|extend>(...)``."""
    hits = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root)
        if _EXCLUDED_DIRS.intersection(rel.parts[:-1]):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            f = node.func if isinstance(node, ast.Call) else None
            if (
                isinstance(f, ast.Attribute)
                and f.attr in _MUTATORS
                and isinstance(f.value, ast.Attribute)
                and f.value.attr == "path"
                and isinstance(f.value.value, ast.Name)
                and f.value.value.id == "sys"
            ):
                hits.append(f"{rel.as_posix()}:{node.lineno}")
    return hits


def test_no_module_mutates_sys_path():
    assert find_sys_path_mutations(DEPLOY_ROOT) == []


def test_the_sweep_finds_a_planted_append(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "conv.py").write_text(
        'import sys\nsys.path.append("/mnt/j/repos/helao-async")\n', encoding="utf-8"
    )
    assert find_sys_path_mutations(tmp_path) == ["pkg/conv.py:2"]


def test_the_sweep_skips_tests_dirs(tmp_path):
    (tmp_path / "pkg" / "tests").mkdir(parents=True)
    (tmp_path / "pkg" / "tests" / "test_x.py").write_text(
        "import sys\nsys.path.insert(0, '.')\n", encoding="utf-8"
    )
    assert find_sys_path_mutations(tmp_path) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/<Deployment-C>/tests/test_no_sys_path_mutation.py -v`
Expected: `test_no_module_mutates_sys_path` FAILS with `assert ['scripts/edax/converters.py:41'] == []` (Task 17 already removed `scripts/xafs/converters.py:33`; before Task 17 the list also holds that entry). The two vacuity tests PASS.

- [ ] **Step 3: Write minimal implementation**

In `scripts/edax/converters.py`:
1. Delete line 4 `import sys` (no other `sys.` use in the file: `grep -n "sys\." scripts/edax/converters.py` shows only lines 32 and 41).
2. Delete lines 32-42, exactly:
```python
if sys.platform == "linux":
    jmnt = "/mnt/j"
    kmnt = "/mnt/k"
    env_file = "helao_data_nb.env"
else:
    jmnt = "j:"
    kmnt = "k:"
    env_file = "helao_data.env"

sys.path.append(jmnt + "/repos/helao-async")

```
leaving the closing `)` of the `from .parsers import (...)` block, two blank lines, then `# from helao.drivers.data.loaders import pgs3`. Leave the commented `# pgs3.LOADER = ...` line untouched.

- [ ] **Step 4: Run test to verify it passes**

Run the Step 2 command -> 3 PASS.
Then: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/<Deployment-C>/scripts/edax/tests/test_parse_xrfs_legs_offline.py helao/deploy/<Deployment-C>/tests/test_import_sweep.py -q` -> PASS.

- [ ] **Step 5: Mutation check**

`git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> diff -- scripts/edax/converters.py > /tmp/claude-1000/mut-task20.patch && git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> apply -R /tmp/claude-1000/mut-task20.patch`
Run the Step 2 command -> Expected FAIL with `assert ['scripts/edax/converters.py:41'] == []` (static AST read; nothing imported).
`git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> apply /tmp/claude-1000/mut-task20.patch`; rerun -> PASS.

- [ ] **Step 6: README**

1. `scripts/edax/README.md` `## Notes`: delete the bullet `- \`helao/deploy/<Deployment-C>/scripts/edax/converters.py:41\` appends \`<jmnt>/repos/helao-async\` (\`/mnt/j\` on Linux) to \`sys.path\` at import, a path on a network mount.`
2. Renumber the other `edax/converters.py:` citations (12 lines deleted: old 4 and 32-42). Create `/tmp/claude-1000/renumber_citations.py` if it does not already exist, with this content:

```python
"""Shift `<cited>:N` / `<cited>:N-M` citations after lines were deleted.

usage: python renumber_citations.py <cited path> <deleted old lines, e.g. 4,24-34> <md>...
Refuses (writes nothing) if a citation points into a deleted range.
"""

import re
import sys

cited, spec, *files = sys.argv[1:]
dels = []
for part in spec.split(","):
    a, _, b = part.partition("-")
    dels.append((int(a), int(b or a)))


def new(n):
    if any(a <= n <= b for a, b in dels):
        sys.exit(f"{cited}:{n} cites a deleted line; fix that citation by hand first")
    return n - sum(b - a + 1 for a, b in dels if b < n)


pat = re.compile(re.escape(cited) + r":(\d+)(-(\d+))?")
out = {}
for f in files:
    text = open(f, encoding="utf-8").read()
    out[f] = pat.sub(
        lambda m: f"{cited}:{new(int(m[1]))}" + (f"-{new(int(m[3]))}" if m[3] else ""),
        text,
    )
for f, text in out.items():
    open(f, "w", encoding="utf-8").write(text)
    print("rewrote", f)
```

Run: `cd /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> && /home/dan/miniforge3/envs/helao/bin/python /tmp/claude-1000/renumber_citations.py helao/deploy/<Deployment-C>/scripts/edax/converters.py 4,32-42 scripts/edax/README.md`
Then `grep -n "edax/converters.py" scripts/edax/README.md`: subtract 12 by hand from any bare shorthand `:NNN` (NNN >= 43) that follows an `edax/converters.py` citation on the same line, and spot-check three citations with `sed -n '<N>p' scripts/edax/converters.py`.
3. Guard: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/<Deployment-C>/tests/test_readme_outputs.py -q` -> PASS.

- [ ] **Step 7: Commit (main session; subagents never commit)**

```bash
/home/dan/miniforge3/envs/helao/bin/black /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C>/scripts/edax/converters.py /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C>/tests/test_no_sys_path_mutation.py
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> branch --show-current   # expect main
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> status --short
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> add scripts/edax/converters.py tests/test_no_sys_path_mutation.py scripts/edax/README.md
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> commit -m "fix(edax): drop import-time sys.path append; sweep forbids sys.path mutation"
```

---

---

### Task 21: C3a box_notes stage moves via `move_bundle`, claim inside a guard (Deployment-C)

**Files:**
- Modify: `scripts/box_notes/batch_process.py:20-31` (imports), `:77-88` (`_move`), `:91-125` (`process_one`)
- Test: `scripts/box_notes/tests/test_batch_process_plate.py` (extend)
- Docs: `scripts/box_notes/README.md`

**Interfaces:**
- Consumes: `scripts/common/batch_converter.py` `move_bundle(src, dest) -> None` (raises `OSError`, leaves the filesystem unchanged; `dest` must not exist)
- Produces: `batch_process._move(path: str, dest_dir: str) -> str` (no `keep_both` parameter; always collision-suffixes `<stem>__<n><ext>`)

- [ ] **Step 1: Write the failing test**

Append to `scripts/box_notes/tests/test_batch_process_plate.py`:

```python
def test_a_failed_claim_leaves_the_tif_in_drop_and_no_copy(tmp_path, monkeypatch):
    """os.rename refused (share ACL / handle held) and the source cannot be
    deleted either: shutil.move's copy fallback would leave a duplicate in
    processing/; the claim must instead not happen at all."""
    dirs, tif = _staged(tmp_path)
    real_rename = os.rename

    def refuse_claim(src, dst, *a, **k):
        if os.path.dirname(str(dst)) == dirs["processing"]:
            raise PermissionError(13, "Permission denied", str(dst))
        return real_rename(src, dst, *a, **k)

    monkeypatch.setattr(os, "rename", refuse_claim)
    monkeypatch.setattr(os, "unlink", _raiser(PermissionError(13, "in use")))
    monkeypatch.setattr(os, "remove", _raiser(PermissionError(13, "in use")))
    monkeypatch.setattr(
        bp, "process_box_note_tif", _raiser(AssertionError("must not run"))
    )

    ok, detail = bp.process_one(tif, dirs)

    assert ok is False and "claim failed" in detail
    assert os.listdir(dirs["drop"]) == ["10232a.tif"]
    for leaf in ("processing", "failed", "done"):
        assert os.listdir(dirs[leaf]) == []


def test_a_name_taken_in_processing_is_suffixed_and_still_discovered(
    tmp_path, monkeypatch
):
    """A stale same-named tif in processing/ is not overwritten: the claim
    takes <stem>__1.tif, and the suffix stays before .tif so discover_tifs
    (which matches the extension) still sees it after it goes back to drop/."""
    dirs, tif = _staged(tmp_path)
    stale = os.path.join(dirs["processing"], "10232a.tif")
    with open(stale, "wb") as fh:
        fh.write(b"old")
    monkeypatch.setattr(
        bp, "process_box_note_tif", _raiser(PlateAPIUnavailable("HTTP 503"))
    )

    ok, _ = bp.process_one(tif, dirs)

    assert ok is False
    assert os.listdir(dirs["processing"]) == ["10232a.tif"]
    with open(stale, "rb") as fh:
        assert fh.read() == b"old"
    back = os.path.join(dirs["drop"], "10232a__1.tif")
    assert bp.discover_tifs(dirs["drop"]) == [back]
    with open(back, "rb") as fh:
        assert fh.read() == b"tif"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/<Deployment-C>/scripts/box_notes/tests/test_batch_process_plate.py -v`
Expected: `test_a_failed_claim_leaves_the_tif_in_drop_and_no_copy` FAILS with `PermissionError` raised out of `process_one` (the claim is outside the `try`, and `shutil.move` copied into `processing/` before its unlink failed); `test_a_name_taken_in_processing_is_suffixed_and_still_discovered` FAILS at `assert os.listdir(dirs["processing"]) == ["10232a.tif"]` (`[]`: the claim's `rename` overwrote the stale file, which then went back to drop as `10232a.tif`). The five existing tests pass.

- [ ] **Step 3: Write minimal implementation**

In `scripts/box_notes/batch_process.py`:

1. Imports (lines 20-31): delete `import shutil` (its only use is in `_move`), and after `from helao.deploy.<Deployment-C>.scripts.common.plate_check import PlateAPIUnavailable` add
```python
from helao.deploy.<Deployment-C>.scripts.common.batch_converter import move_bundle
```
2. `_move` (lines 77-88), old:
```python
def _move(path, dest_dir, keep_both=False):
    """Move ``path`` into ``dest_dir``; ``keep_both`` suffixes ``__<n>`` rather
    than overwrite an archived file of the same name."""
    dest = os.path.join(dest_dir, os.path.basename(path))
    if keep_both:
        stem, ext = os.path.splitext(dest)
        n = 0
        while os.path.exists(dest):
            n += 1
            dest = f"{stem}__{n}{ext}"
    shutil.move(path, dest)
    return dest
```
new:
```python
def _move(path, dest_dir):
    """Move ``path`` into ``dest_dir`` with ``move_bundle`` (never leaves a copy).

    A taken name gets ``<stem>__<n><ext>`` so nothing is overwritten; the suffix
    stays before the extension because ``discover_tifs`` matches ``.tif``.
    ``BatchConverter._collision_free_dest`` is not reused: it suffixes after it.
    """
    stem, ext = os.path.splitext(os.path.basename(path))
    dest = os.path.join(dest_dir, stem + ext)
    n = 0
    while os.path.exists(dest):
        n += 1
        dest = os.path.join(dest_dir, f"{stem}__{n}{ext}")
    move_bundle(path, dest)
    return dest
```
3. `process_one` claim (lines 94-95), old:
```python
    t_start = time.time()
    claimed = _move(tif_path, dirs["processing"])
```
new:
```python
    t_start = time.time()
    try:
        claimed = _move(tif_path, dirs["processing"])
    except OSError as e:
        # move_bundle left the filesystem unchanged: the tif is still in drop/
        LOGGER.error(f"[box_notes] {name}: claim failed, left in drop: {e}")
        return False, f"claim failed: {type(e).__name__}: {e}"
```
4. In `process_one`, drop the now-removed keyword at the two call sites: `_move(claimed, dirs["done"], keep_both=True)` -> `_move(claimed, dirs["done"])`, and `_move(claimed, dirs["failed"], keep_both=True)` -> `_move(claimed, dirs["failed"])`.

- [ ] **Step 4: Run test to verify it passes**

Run the Step 2 command -> 7 PASS.
Then: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/<Deployment-C>/scripts/box_notes/tests/test_watchdog.py helao/deploy/<Deployment-C>/tests/test_sources_root.py -q` -> PASS.

- [ ] **Step 5: Mutation check**

`git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> diff -- scripts/box_notes/batch_process.py > /tmp/claude-1000/mut-task21.patch && git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> apply -R /tmp/claude-1000/mut-task21.patch`
Run the Step 2 command -> Expected the two new tests FAIL as in Step 2 (everything is under `tmp_path`).
`git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> apply /tmp/claude-1000/mut-task21.patch`; rerun -> PASS.

- [ ] **Step 6: README**

In `scripts/box_notes/README.md`:
- `## Notes`: delete the bullet `- \`batch_process._move\` uses \`shutil.move\` for every stage transition ...`.
- Files table, row `| source tif (moved, not rewritten) | TIFF | ...`: replace the name-pattern cell with ``<root>/drop/<name>` to `processing/<name>`, then `done/<name>`, `failed/<name>` or, on `PlateAPIUnavailable`, back to `drop/<name>`; at every step a taken name gets `<stem>__1.tif`, `__2`, ... (suffix before the extension, so a returned tif is still discovered)``; replace the meaning cell with `claim, success, plate-API outage, any other exception; all four go through \`move_bundle\` (\`helao/deploy/<Deployment-C>/scripts/common/batch_converter.py\`), so a refused move leaves the tif where it was. A failed claim leaves it in \`drop/\` and returns \`claim failed: ...\``; refresh the written-at cell from `grep -n "_move(" scripts/box_notes/batch_process.py` (format `helao/deploy/<Deployment-C>/scripts/box_notes/batch_process.py:<_move def range>,<claim>,<done>,<drop>,<failed>`).
- Also refresh the `batch_process.py:` citations in the `process_one` paragraph (`:106-108` reduction string, `main` `:141-153`, roots `:36-46`) from `grep -n` on the edited file.
- Guard: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/<Deployment-C>/tests/test_readme_outputs.py -q` -> PASS.

- [ ] **Step 7: Commit (main session; subagents never commit)**

```bash
/home/dan/miniforge3/envs/helao/bin/black /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C>/scripts/box_notes/batch_process.py /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C>/scripts/box_notes/tests/test_batch_process_plate.py
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> branch --show-current   # expect main
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> status --short
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> add scripts/box_notes/batch_process.py scripts/box_notes/tests/test_batch_process_plate.py scripts/box_notes/README.md
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> commit -m "fix(box_notes): stage moves via move_bundle with stem__n suffix; failed claim stays in drop"
```

---

---

### Task 22: C3b+c box_notes re-drop dedupe + content-hashed crop names (Deployment-C)

**Files:**
- Modify: `scripts/box_notes/process.py:25-38` (imports), `:151-158` (live plate read), `:183-192` (crop name/write), loop head `:188` (skip)
- Test: `scripts/box_notes/tests/test_note_dedupe.py` (new); `scripts/box_notes/tests/test_batch_process_plate.py:60` (fake accepts `**k`)
- Docs: `scripts/box_notes/README.md`

**Interfaces:**
- Consumes: `scripts/common/plate_check.py` `require_plate(plate_id: int, *, live: bool = False) -> dict` (record embeds `notes[]` with `text`); Task 21's `_move` (unchanged here)
- Produces: crop path `<out_root>/<stem>/<stem>__<serial>__<sha256(png)[:12]>.png`; `process_box_note_tif` returns no entry for a skipped plate

- [ ] **Step 1: Write the failing test**

Create `scripts/box_notes/tests/test_note_dedupe.py`:

```python
"""A re-dropped scan posts only the plates that have no note for it yet, and
each crop is named by content so a later scan never overwrites the image
behind an earlier note (the API keys the upload by basename)."""

from __future__ import annotations

import hashlib
import os
import re

import numpy as np

from helao.deploy.<Deployment-C>.scripts.box_notes import process

TIF = "10232a-10230b.tif"


def test_redrop_skips_the_posted_plate_and_names_crops_by_content(
    tmp_path, monkeypatch
):
    # 10232 already carries this scan's note (the exact head _note_text writes
    # for every box note); 10230 has none
    records = {
        10232: {
            "notes": [
                {
                    "text": f"Box-notes scan {TIF} (plate 10232a, id 10232). "
                    "Attached image is the cropped annotation box for this plate. "
                }
            ]
        },
        10230: {"notes": []},
    }
    live_flags = []

    def fake_require_plate(pid, *, live=False):
        live_flags.append(live)
        return records[pid]

    img = np.zeros((40, 20, 3), np.uint8)
    img[20:, :] = 200  # second box differs from the first
    posted = []
    monkeypatch.setattr(process, "require_plate", fake_require_plate)
    monkeypatch.setattr(process.cv2, "imread", lambda path: img)
    monkeypatch.setattr(
        process, "detect_boxes", lambda im, n: [(0, 0, 20, 20), (0, 20, 20, 20)]
    )
    monkeypatch.setattr(
        process, "create_note_with_image", lambda **k: posted.append(k) or "cid"
    )

    process.process_box_note_tif(
        str(tmp_path / TIF),
        str(tmp_path / "crops"),
        create_notes=True,
        detect_positions=False,
        read_text=False,
    )

    assert live_flags == [True, True]
    assert [p["plate_id"] for p in posted] == [10230]
    path = posted[0]["image_path"]
    name = os.path.basename(path)
    m = re.fullmatch(r"10232a-10230b__10230b__([0-9a-f]{12})\.png", name)
    assert m, name
    # the hash is of the bytes actually uploaded
    with open(path, "rb") as fh:
        assert hashlib.sha256(fh.read()).hexdigest()[:12] == m.group(1)
```

And in `scripts/box_notes/tests/test_batch_process_plate.py` line 60, old:
```python
    monkeypatch.setattr(process, "require_plate", lambda pid: seen.append(pid))
```
new:
```python
    monkeypatch.setattr(process, "require_plate", lambda pid, **k: seen.append(pid))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/<Deployment-C>/scripts/box_notes/tests/test_note_dedupe.py -v`
Expected: FAIL with `assert [False, False] == [True, True]` (cached read; with that line removed the next failure is `assert [10232, 10230] == [10230]`, then the crop name `10230b.png` does not match).

- [ ] **Step 3: Write minimal implementation**

In `scripts/box_notes/process.py`:

1. Imports: add `import hashlib` before `import os` (line 27).
2. Up-front plate check (lines 153-158), old:
```python
    if create_notes:
        # Existence only: the token is <plate_id><letter>, not a serial, so there
        # is no check digit to test. Before any image work, and skipped for the
        # offline crops-only mode, which must stay network-free.
        for plate in bf.present_plates:
            require_plate(plate.plate_id)
```
new:
```python
    records = {}
    if create_notes:
        # Existence only: the token is <plate_id><letter>, not a serial, so there
        # is no check digit to test. Before any image work, and skipped for the
        # offline crops-only mode, which must stay network-free. Read live: the
        # embedded notes[] is what a re-drop is deduped against.
        for plate in bf.present_plates:
            records[plate.plate_id] = require_plate(plate.plate_id, live=True)
```
3. Loop head and crop (lines 188-192), old:
```python
    for pi, (plate, box) in enumerate(zip(bf.present_plates, boxes)):
        crop = crop_box(img, box)
        crop_path = os.path.join(crop_dir, f"{plate.serial}.png")
        if not cv2.imwrite(crop_path, crop):
            raise IOError(f"cv2.imwrite failed for {crop_path!r}")
```
new:
```python
    for pi, (plate, box) in enumerate(zip(bf.present_plates, boxes)):
        # A re-drop after a partial failure must not post a plate twice. Match
        # the exact head every box note carries (_note_text), so notes posted
        # before this check existed count too. A same-name rescan is skipped.
        head = f"Box-notes scan {bf.input_tif} (plate {plate.serial},"
        notes = (records.get(plate.plate_id) or {}).get("notes") or []
        if any(str(n.get("text", "")).startswith(head) for n in notes):
            LOGGER.info(
                f"[box_notes] {bf.input_tif}: plate {plate.plate_id} already has "
                f"this scan's note; skipped"
            )
            continue
        crop = crop_box(img, box)
        ok, buf = cv2.imencode(".png", crop)
        if not ok:
            raise IOError(f"cv2.imencode failed for plate {plate.serial}")
        png = buf.tobytes()
        # content-hashed: the note API keys the S3 image by basename
        digest = hashlib.sha256(png).hexdigest()[:12]
        crop_path = os.path.join(crop_dir, f"{stem}__{plate.serial}__{digest}.png")
        with open(crop_path, "wb") as fh:
            fh.write(png)
```

- [ ] **Step 4: Run test to verify it passes**

Run the Step 2 command -> PASS.
Then: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/<Deployment-C>/scripts/box_notes/tests -q` -> all pass (including the updated one-argument fake).

- [ ] **Step 5: Mutation check**

`git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> diff -- scripts/box_notes/process.py > /tmp/claude-1000/mut-task22.patch && git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> apply -R /tmp/claude-1000/mut-task22.patch`
Run the Step 2 command -> Expected FAIL as in Step 2 (all network calls are fakes).
`git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> apply /tmp/claude-1000/mut-task22.patch`; rerun -> PASS.

- [ ] **Step 6: README**

In `scripts/box_notes/README.md`:
- `## Notes`: delete the bullet beginning `- A scan with two plates that fails on the second plate` and the bullet beginning `- The crop's file name is the plate token with no scan identifier`; add one bullet: `- A re-dropped scan skips every plate whose live record already holds a note starting \`Box-notes scan <tif name> (plate <token>,\`, so a genuine rescan saved under the same file name gets no new note (there is no force option). Images behind notes posted before the content-hashed crop names may already have been overwritten.`
- Files table, `box crop` row: name pattern `\`<out_root>/<tif stem>/<tif stem>__<plate serial token>__<sha256(png)[:12]>.png\`, \`out_root\` = \`<BOX_NOTES root>/crops\``; meaning: `the cropped annotation box of one plate, PNG-encoded once and hashed; uploaded to S3 as the note image. The same crop always gets the same name, a different crop a new one`; written-at refreshed from `grep -n "crop_path\|imencode" scripts/box_notes/process.py`.
- API table, `POST /file/upload-url` `filename` row: meaning `basename of the crop (\`<tif stem>__<plate serial token>__<12 hex>.png\`)`.
- `process_one` paragraph: add `A plate skipped as already posted has no entry in the returned list.` and refresh the `process.py:252-261` citation from `grep -n "results.append" scripts/box_notes/process.py`.
- Guard: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/<Deployment-C>/tests/test_readme_outputs.py -q` -> PASS.

- [ ] **Step 7: Commit (main session; subagents never commit)**

```bash
/home/dan/miniforge3/envs/helao/bin/black /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C>/scripts/box_notes/process.py /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C>/scripts/box_notes/tests/test_note_dedupe.py /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C>/scripts/box_notes/tests/test_batch_process_plate.py
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> branch --show-current   # expect main
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> status --short
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> add scripts/box_notes/process.py scripts/box_notes/tests/test_note_dedupe.py scripts/box_notes/tests/test_batch_process_plate.py scripts/box_notes/README.md
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> commit -m "fix(box_notes): skip plates already noted for the scan; content-hashed crop names"
```

---

---

### Task 23: C4a ecms_ms `inject` reads and writes `-exp.json` (Deployment-C)

**Files:**
- Modify: `scripts/ecms_ms/inject.py:89-93` (imports), `:157-171` (`_find_exp_yml`), `:211`, `:226` (`_patch_process_order_groups`), `:313` (`inject_ms_action`)
- Test: `scripts/ecms_ms/tests/test_inject.py` (extend `_build_existing_experiment`, add one test)
- Docs: `scripts/ecms_ms/README.md`

**Interfaces:**
- Consumes: `helao/helpers/meta_io.py` `meta_glob(root, kind) -> list[Path]`, `read_meta(path) -> Any`, `write_meta(path, d) -> Path`
- Produces: `_find_exp_yml(exp_dir: Path) -> Path` now returns the one `-exp.json` or `-exp.yml`

- [ ] **Step 1: Write the failing test**

In `scripts/ecms_ms/tests/test_inject.py`:

1. Add `import json` to the imports (after `import datetime`).
2. Change the helper signature (line 26) `def _build_existing_experiment(save_root: Path):` to `def _build_existing_experiment(save_root: Path, legacy_yml: bool = True):` and guard the YAML rewrite block (lines 89-97), old:
```python
    for record in (act_record, exp_record):
        assert record is not None
        Path(record).with_suffix(".yml").touch()
        Path(record).unlink()
    writer.write_act(anchor_act)
    writer.write_exp(exp)
```
new:
```python
    if legacy_yml:
        for record in (act_record, exp_record):
            assert record is not None
            Path(record).with_suffix(".yml").touch()
            Path(record).unlink()
        writer.write_act(anchor_act)
        writer.write_exp(exp)
```
3. Add the test:
```python
def test_a_native_json_experiment_is_found_and_patched_as_json(tmp_path):
    """Records written since the JSON storage change are -exp.json; inject must
    find that record and keep it JSON (YAML text in a .json file would break
    every reader)."""
    exp_dir, exp_uuid, process_uuid, anchor_act = _build_existing_experiment(
        tmp_path, legacy_yml=False
    )
    assert not list(exp_dir.glob("*-exp.yml"))

    inject_ms_action(
        exp_dir,
        _grouped(exp_dir, exp_uuid, process_uuid),
        _frame(),
        str(anchor_act.action_uuid),
        MACHINE_NAME,
    )

    (exp_json,) = exp_dir.glob("*-exp.json")
    doc = json.loads(exp_json.read_text(encoding="utf-8"))
    # JSON object keys are strings; the anchor (order 0) plus the injected order 1
    assert doc["process_order_groups"]["0"] == [0, 1]
    assert doc["process_list"] == [str(process_uuid)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/<Deployment-C>/scripts/ecms_ms/tests/test_inject.py::test_a_native_json_experiment_is_found_and_patched_as_json -v`
Expected: FAIL with `FileNotFoundError: ... no -exp.yml found`.

- [ ] **Step 3: Write minimal implementation**

In `scripts/ecms_ms/inject.py`:

1. After `from helao.helpers.file_utils import staging_path` add:
```python
from helao.helpers.meta_io import meta_glob, read_meta, write_meta
```
2. `_find_exp_yml` (lines 157-171), old body:
```python
    matches = sorted(exp_dir.glob("*-exp.yml"))
    if not matches:
        raise FileNotFoundError(f"{exp_dir}: no -exp.yml found")
    if len(matches) > 1:
        raise ValueError(f"{exp_dir}: multiple -exp.yml found: {matches}")
    return matches[0]
```
new body (keep the docstring, change its first line to ``"""Return the one ``-exp`` record (``.json`` or legacy ``.yml``) in ``exp_dir``.``):
```python
    matches = meta_glob(exp_dir, "exp")
    if not matches:
        raise FileNotFoundError(f"{exp_dir}: no -exp record found")
    if len(matches) > 1:
        raise ValueError(f"{exp_dir}: multiple -exp records found: {matches}")
    return matches[0]
```
3. `_patch_process_order_groups` line 211, old `    doc = yml_load(exp_yml_path)` new:
```python
    is_yml = exp_yml_path.suffix == ".yml"
    # .yml keeps the round-trip loader (process_list byte-identical); .json is
    # read and written with the record helpers so it stays JSON
    doc = yml_load(exp_yml_path) if is_yml else read_meta(exp_yml_path)
```
and line 226, old `    _atomic_write_yml(exp_yml_path, doc)` new:
```python
    if is_yml:
        _atomic_write_yml(exp_yml_path, doc)
    else:
        write_meta(exp_yml_path, doc)
```
4. `inject_ms_action` line 313, old `    exp_meta = yml_load(exp_yml_path)` new `    exp_meta = read_meta(exp_yml_path)`.

- [ ] **Step 4: Run test to verify it passes**

Run the Step 2 command -> PASS.
Then the whole file (the YAML path, including `test_process_list_is_byte_identical_before_and_after`, must be unchanged): `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/<Deployment-C>/scripts/ecms_ms/tests/test_inject.py helao/deploy/<Deployment-C>/scripts/ecms_ms/tests/test_convert_backlog.py helao/deploy/<Deployment-C>/scripts/ecms_ms/tests/test_from_s3.py -q` -> all pass.

- [ ] **Step 5: Mutation check**

`git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> diff -- scripts/ecms_ms/inject.py > /tmp/claude-1000/mut-task23.patch && git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> apply -R /tmp/claude-1000/mut-task23.patch`
Run the Step 2 command -> Expected FAIL with `FileNotFoundError ... no -exp.yml found`.
`git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> apply /tmp/claude-1000/mut-task23.patch`; rerun -> PASS.

- [ ] **Step 6: README**

In `scripts/ecms_ms/README.md`:
- `## Notes`: delete the bullet beginning `- \`inject_ms_action\` finds the experiment record with \`glob("*-exp.yml")\` only` and the bullet beginning `- Consequence for \`convert_backlog\`: the \`FileNotFoundError\` above`. Add: `- \`convert_backlog\` only walks \`RUNS_SYNCED\` \`*__ECMS_*.zip\`, and the syncer stopped zipping before records became JSON, so post-2026-10-23 unpaired ECMS sequences (unzipped, \`-exp.json\`) can only be paired through \`from_s3.py\`.`
- `inject_ms_action` section: the `Rewritten record:` sentence becomes `the experiment's existing \`-exp.json\` (or legacy \`-exp.yml\`) gains \`action_order\` in \`process_order_groups[pidx]\` and nothing else; a \`.yml\` is written atomically as YAML through the round-trip loader, a \`.json\` atomically as JSON (\`write_meta\`)`; `Inputs parsed:` becomes `the experiment's \`-exp\` record, \`.json\` or \`.yml\` (\`_find_exp_yml\`, \`meta_glob\`)`. Refresh every `inject.py:` citation in that section from `grep -n` on the edited file (the file grew by 1 import line and by 6 lines inside `_patch_process_order_groups`).
- Guard: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/<Deployment-C>/tests/test_readme_outputs.py -q` -> PASS.

- [ ] **Step 7: Commit (main session; subagents never commit)**

```bash
/home/dan/miniforge3/envs/helao/bin/black /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C>/scripts/ecms_ms/inject.py /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C>/scripts/ecms_ms/tests/test_inject.py
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> branch --show-current   # expect main
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> status --short
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> add scripts/ecms_ms/inject.py scripts/ecms_ms/tests/test_inject.py scripts/ecms_ms/README.md
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> commit -m "fix(ecms_ms): inject finds and patches -exp.json records as JSON"
```

---

---

### Task 24: C4b ecms_ms `from_s3`: drop `--repair-legacy-keys`, never overwrite snapshots (Deployment-C)

**Files:**
- Modify: `scripts/ecms_ms/from_s3.py:30-37` (docstring), `:473-498` (`snapshot_metas`), `:673-680` (argparse), `:762-773` (install hint + repair block)
- Test: `scripts/ecms_ms/tests/test_from_s3.py` (extend)
- Docs: `scripts/ecms_ms/README.md` (`:92`, `:105`, `## Notes`)

**Interfaces:**
- Consumes: none (Task 23 is independent)
- Produces: `snapshot_metas(s3, bucket, record, dest) -> list[Path]` returns only newly written snapshot paths and never rewrites an existing one; `from_s3.main` no longer accepts `--repair-legacy-keys`

- [ ] **Step 1: Write the failing test**

Append to `scripts/ecms_ms/tests/test_from_s3.py`:

```python
def test_a_second_snapshot_never_overwrites_the_first(tmp_path):
    """The first snapshot is the pre-sync original; a later run (after the
    syncer re-uploaded and stripped experiment_list) must not replace it, or
    repair_legacy loses the only copy of the key."""
    s3 = FakeS3(_objects())
    record = fetch_record(s3, "helao.data", SEQ_UUID)
    snaps = tmp_path / "snap"
    snapshot_metas(s3, "helao.data", record, snaps)

    stripped = dict(s3.objects[f"sequence/{SEQ_UUID}.json"])
    stripped.pop("experiment_list")
    s3.objects[f"sequence/{SEQ_UUID}.json"] = stripped
    snapshot_metas(s3, "helao.data", record, snaps)

    doc = json.loads(
        (snaps / f"sequence__{SEQ_UUID}.json").read_text(encoding="utf-8")
    )
    assert len(doc["experiment_list"]) == 2


def test_the_in_run_repair_flag_is_gone(monkeypatch):
    # the flag ran before the syncer re-uploaded, so it never repaired anything;
    # repair_legacy.py is the post-sync tool. argparse rejects it before any S3
    # client is built.
    monkeypatch.setattr(
        from_s3, "_s3_client", lambda: (_ for _ in ()).throw(AssertionError("no s3"))
    )
    with pytest.raises(SystemExit) as exc:
        from_s3.main(
            ["rec.csv", SEQ_UUID, "--root", "r", "--lag-s", "23", "--repair-legacy-keys"]
        )
    assert exc.value.code == 2
```

(`_objects()` builds a sequence with two `experiment_list` entries; `test_legacy_keys_dropped_by_the_re_upload_are_restored` asserts the same length.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/<Deployment-C>/scripts/ecms_ms/tests/test_from_s3.py -k "second_snapshot or repair_flag" -v`
Expected: `test_a_second_snapshot_never_overwrites_the_first` FAILS with `KeyError: 'experiment_list'`; `test_the_in_run_repair_flag_is_gone` FAILS with `AssertionError: no s3` (the flag parses, so `main` reaches `_s3_client`).

- [ ] **Step 3: Write minimal implementation**

In `scripts/ecms_ms/from_s3.py`:

1. Module docstring lines 30-37, old:
```
**Re-syncing drops legacy keys, and this repairs that.** ``experiment_list``
(on the sequence) and ``action_list`` (on a process) are written by the
pre-merge uploader; today's ``SequenceModel``/``ProcessModel`` have no such
fields, so ``sync_yml``'s ``MOD_MAP[type](**meta)`` silently discards them and
the re-uploaded JSON loses the only S3-side index from a sequence to its
experiments. Every JSON this module touches is snapshotted before install, and
``--repair-legacy-keys`` merges any dropped top-level key back afterwards.
Nothing here writes to S3 itself; that is the syncer's job and the repair's.
```
new:
```
**Re-syncing drops legacy keys; ``repair_legacy`` puts them back.**
``experiment_list`` (on the sequence) and ``action_list`` (on a process) are
written by the pre-merge uploader; today's ``SequenceModel``/``ProcessModel``
have no such fields, so ``sync_yml``'s ``MOD_MAP[type](**meta)`` silently
discards them and the re-uploaded JSON loses the only S3-side index from a
sequence to its experiments. Every JSON this module touches is snapshotted
before install (an existing snapshot is never overwritten, so a re-run cannot
replace the original with the stripped re-upload). Once the station syncer has
re-uploaded the record, run ``python -m scripts.ecms_ms.repair_legacy`` on the
snapshots. Nothing here writes to S3 itself.
```
2. `snapshot_metas` loop (lines 487-497), old:
```python
    written = []
    for key in keys:
        try:
            doc = _get_json(s3, bucket, key)
        except Exception as exc:  # noqa: BLE001 -- a missing object is worth
            # recording as absent rather than aborting the snapshot.
            logger.warning(f"{key}: not snapshotted -- {exc}")
            continue
        out = dest / key.replace("/", "__")
        out.write_text(json.dumps(doc, indent=1), encoding="utf-8")
        written.append(out)
    return written
```
new:
```python
    written = []
    for key in keys:
        out = dest / key.replace("/", "__")
        if out.exists():
            # the first snapshot is the pre-sync original; a later one may
            # already be the stripped re-upload
            continue
        try:
            doc = _get_json(s3, bucket, key)
        except Exception as exc:  # noqa: BLE001 -- a missing object is worth
            # recording as absent rather than aborting the snapshot.
            logger.warning(f"{key}: not snapshotted -- {exc}")
            continue
        out.write_text(json.dumps(doc, indent=1), encoding="utf-8")
        written.append(out)
    return written
```
Also add to its docstring: `An existing snapshot file is kept as is.`
3. Delete the argparse block (lines 673-680):
```python
    parser.add_argument(
        "--repair-legacy-keys",
        action="store_true",
        help=(
            "after install, put back any top-level key the re-upload dropped "
            "(experiment_list, action_list). Run once the syncer has finished"
        ),
    )
```
4. After the install print (line 763), old:
```python
        dest = install_record(seq_dir, root)
        print(f"    installed: {dest} -- the station syncer takes it from here")
```
new:
```python
        dest = install_record(seq_dir, root)
        print(f"    installed: {dest} -- the station syncer takes it from here")
        print(
            f"    once it has synced: python -m scripts.ecms_ms.repair_legacy "
            f"--snapshot-root {snapshots} --only {uuid}"
        )
```
5. Delete the repair block (lines 765-771):
```python
    if args.repair_legacy_keys:
        print("\nlegacy-key repair:")
        for uuid in args.sequence_uuid:
            for key, restored in repair_legacy_keys(
                s3, bucket, snapshots / uuid, dry_run=args.dry_run
            ):
                print(f"  {key}: restored {', '.join(restored)}")

```
Keep `repair_legacy_keys` itself and its `__all__` entry (`repair_legacy.py` and the tests use it). Confirm the `repair_legacy` flag names with `grep -n "add_argument" scripts/ecms_ms/repair_legacy.py` (expect `--snapshot-root` and `--only`; if `--only` takes the sequence uuid positionally under a different name, use that name in the hint).

- [ ] **Step 4: Run test to verify it passes**

Run the Step 2 command -> 2 PASS.
Then: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/<Deployment-C>/scripts/ecms_ms/tests/test_from_s3.py helao/deploy/<Deployment-C>/scripts/ecms_ms/tests/test_repair_legacy.py -q` -> all pass.

- [ ] **Step 5: Mutation check**

`git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> diff -- scripts/ecms_ms/from_s3.py > /tmp/claude-1000/mut-task24.patch && git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> apply -R /tmp/claude-1000/mut-task24.patch`
Run the Step 2 command -> Expected both FAIL as in Step 2 (fake S3 only; `_s3_client` is patched to raise).
`git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> apply /tmp/claude-1000/mut-task24.patch`; rerun -> PASS.

- [ ] **Step 6: README**

In `scripts/ecms_ms/README.md`:
- Line 92 (usage): delete ` [--repair-legacy-keys]` from the command line; refresh the `main` range citation `from_s3.py:617-775` from `grep -n "^def main\|^if __name__" scripts/ecms_ms/from_s3.py`. Append: `After install it prints the \`repair_legacy\` command to run once the station syncer has re-uploaded the record.`
- `S3 snapshots` row: meaning becomes `copy of each S3 sequence, experiment, process and action object the re-sync will rewrite; an existing snapshot file is never overwritten, so the first (pre-sync) copy is kept`; refresh its `:473-498` citation.
- Line 105: replace the paragraph `API writes: with \`--repair-legacy-keys\`, ...` with `API writes: none. The legacy-key repair is \`repair_legacy.py\` (below), run once the syncer has re-uploaded the record.` and delete the S3 `PUT` table that follows it under `from_s3.py` (the identical writes are listed under `repair_legacy.py`; if that section only points to "the row above", move the `PUT` table row there and refresh its citation to `helao/deploy/<Deployment-C>/scripts/ecms_ms/from_s3.py` `repair_legacy_keys` lines from `grep -n "def repair_legacy_keys\|put_object" scripts/ecms_ms/from_s3.py`).
- `## Notes`: replace the bullet beginning `- \`from_s3.py\` cannot be re-run for a sequence after the syncer has re-uploaded it:` with `- A \`from_s3.py\` re-run for a sequence already installed in \`RUNS\` aborts the whole run: \`install_record\` raises \`FileExistsError\` (\`helao/deploy/<Deployment-C>/scripts/ecms_ms/from_s3.py:NNN\`), called outside the per-sequence \`try\` (\`:NNN\`). The snapshots survive the re-run (\`snapshot_metas\` keeps existing files), so \`repair_legacy.py\` still works.` with `NNN` from `grep -n "raise FileExistsError\|dest = install_record" scripts/ecms_ms/from_s3.py`.
- Guard: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/<Deployment-C>/tests/test_readme_outputs.py -q` -> PASS.

- [ ] **Step 7: Commit (main session; subagents never commit)**

```bash
/home/dan/miniforge3/envs/helao/bin/black /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C>/scripts/ecms_ms/from_s3.py /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C>/scripts/ecms_ms/tests/test_from_s3.py
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> branch --show-current   # expect main
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> status --short
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> add scripts/ecms_ms/from_s3.py scripts/ecms_ms/tests/test_from_s3.py scripts/ecms_ms/README.md
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-C> commit -m "fix(ecms_ms): from_s3 drops the pre-sync repair flag; snapshots never overwritten"
```

---

> **Alias note (Tasks 25-28, 32-33):** `<Deployment-B>` and `<Deployment-E>` stand for private deployment folder names, in paths **and** in Python import lines (`helao.deploy.<Deployment-B>...`). Executors resolve them from the memory file `cards-deployment-aliases.md` before typing code. Never write the resolved names into any parent-repo file.
>
> Shared shell variables for these tasks: `PY=/home/dan/miniforge3/envs/helao/bin/python`, `BLACK=/home/dan/miniforge3/envs/helao/bin/black`, `ROOT=/mnt/STORAGE/repos/helao/helao-async`, `B=$ROOT/helao/deploy/<Deployment-B>`, `E=$ROOT/helao/deploy/<Deployment-E>`. Every test command runs as `cd $ROOT && PYTHONPATH=$ROOT $PY -m pytest ...`.
### Task 25: B1 test_station `leak_test_passed` null and duplicated `set_mode` rows (Deployment-B)

**Files:**
- Modify: `helao/deploy/<Deployment-B>/servers/test_station/test_station_server.py:551-561` (pass path), `:576-589` (failure path)
- Test: `helao/deploy/<Deployment-B>/tests/test_station_executors.py`
- Docs: `helao/deploy/<Deployment-B>/servers/test_station/README.md`

**Interfaces:**
- Consumes: `_exec(cls, params, read)` (existing helper in `tests/test_station_executors.py:17-28`); `make_driver()` (existing, `servers/test_station/tests/test_leancat_driver.py:44-61`); `OpcUaStationDriver._multi_read(dict)` (unchanged).
- Produces: none.

- [ ] **Step 1: Write the failing tests**

Append to `helao/deploy/<Deployment-B>/tests/test_station_executors.py`. Add these imports at the top of the file, next to the existing ones:

```python
from helao.core.drivers.helao_driver import (
    DriverResponse,
    DriverResponseType,
    DriverStatus,
)
from helao.deploy.<Deployment-B>.servers.test_station.tests.test_leancat_driver import (
    make_driver,
)
```

Then append:

```python
def _leak_driver(mode: int):
    """The REAL driver, with every node the mode-5 path reads answering.

    All five reads succeed, so an honest row has error_code none; the only
    way to get `unspecified` is a read of an alias that is not a node.
    """
    driver = make_driver()
    driver.connect = AsyncMock(
        return_value=DriverResponse(
            response=DriverResponseType.success, status=DriverStatus.ok
        )
    )
    values = {
        "master.operationModeActive": mode,
        "master.alarms.errLeakTestFailed": False,
        "master.leakTest.status": 2,
        "master.leakTest.pressureDropPercentage": 0.1,
        "master.leakTest.timeRemaining": 0,
    }
    driver._nodes = {
        alias: AsyncMock(read_value=AsyncMock(return_value=v))
        for alias, v in values.items()
    }
    return driver


@pytest.mark.asyncio
async def test_a_reached_mode_5_records_the_leak_test_as_passed():
    driver = _leak_driver(mode=5)
    ex = _exec(ModeMonitorExec, {"mode": 5}, driver._multi_read)
    out = await ex._poll()
    assert out["status"] == HloStatus.finished
    # Mode 5 was reached, so the leak test passed; every node read succeeded.
    assert out["data"]["leak_test_passed"] is True
    assert out["data"]["error_code"] == ErrorCodes.none
    assert out["data"]["leak_status"] == 2


@pytest.mark.asyncio
async def test_a_fall_back_to_setup_records_the_leak_test_as_failed():
    driver = _leak_driver(mode=1)
    ex = _exec(ModeMonitorExec, {"mode": 5}, driver._multi_read)
    assert (await ex._poll())["status"] == HloStatus.active  # inside the 10 s grace
    ex._start_ts -= 11
    out = await ex._poll()
    assert out["status"] == HloStatus.errored
    assert out["data"]["leak_test_passed"] is False
    assert out["data"]["error_code"] == ErrorCodes.none


@pytest.mark.asyncio
async def test_the_finishing_set_mode_row_is_written_once():
    read = AsyncMock(
        return_value={
            "current_mode": 1,
            "leak_test_failed": False,
            "error_code": ErrorCodes.none,
        }
    )
    ex = _exec(ModeMonitorExec, {"mode": 1}, read)
    out = await ex._poll()
    assert out["status"] == HloStatus.finished
    # The executor runner queues the returned data once; an explicit
    # enqueue_data_dflt on top of it is a second copy of the same row.
    rows_written = ex.active.enqueue_data_dflt.await_count + (1 if out["data"] else 0)
    assert rows_written == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd $ROOT && PYTHONPATH=$ROOT $PY -m pytest helao/deploy/<Deployment-B>/tests/test_station_executors.py -v -k "leak_test or written_once"`
Expected: 3 FAIL — `assert None is True`, `assert None is False` (the log shows `Unknown alias for read: True` / `False`), and `assert (1 + 1) == 1`.

- [ ] **Step 3: Write minimal implementation**

In `test_station_server.py`, pass path (`:551-561`), replace:

```python
            if target_mode == 5:
                try:
                    leak_resp = await self.active.driver._multi_read(
                        {"leak_test_passed": True, **_LEAK_NODES}
                    )
                    resp.update(leak_resp)
                    LOGGER.info(f"[LEAK TEST RESULT] PASSED: {leak_resp}")
                except Exception as e:
                    LOGGER.warning(f"Failed to read leak test detailed results: {e!r}")

            await self.active.enqueue_data_dflt(datadict=resp)
            return {
```

with:

```python
            if target_mode == 5:
                try:
                    leak_resp = await self.active.driver._multi_read(
                        dict(_LEAK_NODES)
                    )
                    leak_err = leak_resp.pop("error_code", ErrorCodes.none)
                    resp.update(leak_resp, leak_test_passed=True)
                    if leak_err != ErrorCodes.none:
                        resp["error_code"] = leak_err
                    LOGGER.info(f"[LEAK TEST RESULT] PASSED: {leak_resp}")
                except Exception as e:
                    LOGGER.warning(f"Failed to read leak test detailed results: {e!r}")

            return {
```

Failure path (`:576-589`), replace:

```python
                try:
                    leak_resp = await self.active.driver._multi_read(
                        {"leak_test_passed": False, **_LEAK_NODES}
                    )
                    resp.update(leak_resp)  # データを合流
                    LOGGER.error(f"[LEAK TEST RESULT] FAILED: {leak_resp}")
                except Exception as e:
                    LOGGER.warning(
                        f"Failed to read leak test detailed results on failure: {e!r}"
                    )

                # 明示的にエラー時のデータをエンキューして .hlo に残す
                await self.active.enqueue_data_dflt(datadict=resp)
                return {
```

with:

```python
                try:
                    leak_resp = await self.active.driver._multi_read(
                        dict(_LEAK_NODES)
                    )
                    leak_err = leak_resp.pop("error_code", ErrorCodes.none)
                    resp.update(leak_resp, leak_test_passed=False)  # データを合流
                    if leak_err != ErrorCodes.none:
                        resp["error_code"] = leak_err
                    LOGGER.error(f"[LEAK TEST RESULT] FAILED: {leak_resp}")
                except Exception as e:
                    LOGGER.warning(
                        f"Failed to read leak test detailed results on failure: {e!r}"
                    )

                return {
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd $ROOT && PYTHONPATH=$ROOT $PY -m pytest helao/deploy/<Deployment-B>/tests/test_station_executors.py helao/deploy/<Deployment-B>/servers/test_station/tests/ -v`
Expected: PASS (all, including the pre-existing `test_the_mode_monitor_times_out_even_if_every_read_fails`).

- [ ] **Step 5: Mutation check**

```bash
git -C $B diff -- servers/test_station/test_station_server.py > /tmp/claude-1000/mut-task25.patch
git -C $B apply -R /tmp/claude-1000/mut-task25.patch
cd $ROOT && PYTHONPATH=$ROOT $PY -m pytest helao/deploy/<Deployment-B>/tests/test_station_executors.py -q -k "leak_test or written_once"   # Expected: 3 failed (same reasons as Step 2)
git -C $B apply /tmp/claude-1000/mut-task25.patch
cd $ROOT && PYTHONPATH=$ROOT $PY -m pytest helao/deploy/<Deployment-B>/tests/test_station_executors.py -q   # Expected: all passed
```

- [ ] **Step 6: README**

In `helao/deploy/<Deployment-B>/servers/test_station/README.md` (`### set_mode` section, line numbers re-derived with `grep -n "leak_resp\|return {" servers/test_station/test_station_server.py` after Step 3):
- Row `leak_test_passed` (currently `| null | ... always \`null\` (see Notes) |`): type `bool`; meaning "only on the finishing row of a mode-5 target (`true`) and on the leak-failure row (`false`); absent when the leak-node read raises"; written at = the two `resp.update(leak_resp, leak_test_passed=...)` lines.
- Row `error_code`: meaning becomes "`ErrorCodes` value: `none`, or `unspecified` when any node in the mode read returned no value; on leak rows, the leak-node read's code replaces it only when that read failed"; add the two `resp["error_code"] = leak_err` lines to "written at".
- In the paragraph under the table, replace the text from "The `leak_*` fields and an overwritten `error_code` are merged in" through "(`:589`, `:590-595`)." with: "The `leak_*` fields and `leak_test_passed` are merged in when the target is mode 5 and the mode is reached, or the leak test failed. Each row is queued once, by the executor runner from the returned `data` (`helao/hexagon/app/executor_runner.py:120-138`)." Keep the trailing timeout / failed-read / "No action results." sentences.
- `## Notes`: delete the two bullets beginning "- `leak_test_passed` in `set_mode` rows is always `null`" and "- `set_mode` finishing rows are queued twice". (The `OpcUaStationExec` bullet stays until Task 28.)

Run: `cd $ROOT && PYTHONPATH=$ROOT $PY -m pytest helao/deploy/<Deployment-B>/tests/test_readme_outputs.py -q` — Expected: PASS.

- [ ] **Step 7: Commit (main session; subagents never commit)**

```bash
$BLACK $B/servers/test_station/test_station_server.py $B/tests/test_station_executors.py
git -C $B branch --show-current   # expect: main
git -C $B status --short          # expect only the three files below
git -C $B add servers/test_station/test_station_server.py tests/test_station_executors.py servers/test_station/README.md
git -C $B commit -m "fix(test_station): record leak_test_passed and write the set_mode row once"
```

---

### Task 26: B2a actuator live keys `strain_adc`/`setpoint_adc` never populated (Deployment-B)

**Files:**
- Modify: `helao/deploy/<Deployment-B>/servers/actuator/actuator_driver.py:235-240`
- Test: `helao/deploy/<Deployment-B>/servers/actuator/tests/test_sim_actuator.py`
- Docs: `helao/deploy/<Deployment-B>/servers/actuator/README.md`

**Interfaces:**
- Consumes: none.
- Produces: none. (`load_act_lbs`/`load_set_lbs` stay unseeded: `wait_for_load` relies on them being absent → `None` before the first telemetry line, `actuator_server.py:317-325`.)

- [ ] **Step 1: Write the failing test**

Append to `servers/actuator/tests/test_sim_actuator.py` (it already imports `ActuatorDriver` and `KEYMAP_PATH`):

```python
def test_the_parser_fills_the_live_adc_keys_with_the_raw_load_values():
    """No serial port: __init__ does no I/O, and _parse_line is pure."""
    driver = ActuatorDriver({"actuator_keymap_path": str(KEYMAP_PATH)})
    assert driver._parse_line("STR_ACT:123 STR_SET:456") is True
    # Same raw lbf x 10 values the parser stores as load_act_lbs/load_set_lbs,
    # i.e. what the server's status mapping calls strain_adc/setpoint_adc.
    assert driver._state["strain_adc"] == 123
    assert driver._state["setpoint_adc"] == 456
    assert driver._state["load_act_lbs"] == 123
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd $ROOT && PYTHONPATH=$ROOT $PY -m pytest helao/deploy/<Deployment-B>/servers/actuator/tests/test_sim_actuator.py::test_the_parser_fills_the_live_adc_keys_with_the_raw_load_values -v`
Expected: FAIL with `assert 0 == 123`.

- [ ] **Step 3: Write minimal implementation**

`actuator_driver.py:235-240`, replace:

```python
        if m_load_act:
            self._state["load_act_lbs"] = int(m_load_act.group(1))
            updated = True
        if m_load_set:
            self._state["load_set_lbs"] = int(m_load_set.group(1))
            updated = True
```

with:

```python
        if m_load_act:
            self._state["load_act_lbs"] = self._state["strain_adc"] = int(
                m_load_act.group(1)
            )
            updated = True
        if m_load_set:
            self._state["load_set_lbs"] = self._state["setpoint_adc"] = int(
                m_load_set.group(1)
            )
            updated = True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd $ROOT && PYTHONPATH=$ROOT $PY -m pytest helao/deploy/<Deployment-B>/servers/actuator/tests/test_sim_actuator.py -v`
Expected: PASS (all; the sim tests still read `strain_adc`/`setpoint_adc` through the `var.load_*` aliases).

- [ ] **Step 5: Mutation check**

```bash
git -C $B diff -- servers/actuator/actuator_driver.py > /tmp/claude-1000/mut-task26.patch
git -C $B apply -R /tmp/claude-1000/mut-task26.patch
cd $ROOT && PYTHONPATH=$ROOT $PY -m pytest helao/deploy/<Deployment-B>/servers/actuator/tests/test_sim_actuator.py -q -k live_adc   # Expected: 1 failed (assert 0 == 123)
git -C $B apply /tmp/claude-1000/mut-task26.patch
cd $ROOT && PYTHONPATH=$ROOT $PY -m pytest helao/deploy/<Deployment-B>/servers/actuator/tests/test_sim_actuator.py -q   # Expected: all passed
```

- [ ] **Step 6: README**

In `helao/deploy/<Deployment-B>/servers/actuator/README.md`, `### Live data (status/ws stream)` table:
- Row `strain_adc` (currently "initial `0`, never updated (the telemetry goes to `load_act_lbs`)"): unit `lbf x 10 (raw)`; meaning "actual load, the last parsed `STR_ACT` (same value as `load_act_lbs`); `0` before the first telemetry line"; written at = the new `_parse_line` assignment line (init `:58`).
- Row `setpoint_adc`: unit `lbf x 10 (raw)`; meaning "load set point, the last parsed `STR_SET` (same value as `load_set_lbs`); `0` before the first telemetry line"; written at = the new assignment line (init `:59`).
- `## Notes`: delete the bullet "- The live-stream keys `strain_adc` and `setpoint_adc` stay at their initial `0` ...". It is the only bullet, so delete the `## Notes` heading too.

Run: `cd $ROOT && PYTHONPATH=$ROOT $PY -m pytest helao/deploy/<Deployment-B>/tests/test_readme_outputs.py -q` — Expected: PASS.

- [ ] **Step 7: Commit (main session; subagents never commit)**

```bash
$BLACK $B/servers/actuator/actuator_driver.py $B/servers/actuator/tests/test_sim_actuator.py
git -C $B branch --show-current   # expect: main
git -C $B status --short
git -C $B add servers/actuator/actuator_driver.py servers/actuator/tests/test_sim_actuator.py servers/actuator/README.md
git -C $B commit -m "fix(actuator): populate live strain_adc/setpoint_adc from telemetry"
```

---

### Task 27: B2b robot arm live keys `robot_mode`/`is_moving` never populated (Deployment-B)

**Files:**
- Modify: `helao/deploy/<Deployment-B>/servers/robotarm/robotarm_driver.py:59` (new config param), `:252-306` (`_parse_rtde_packet`)
- Test: `helao/deploy/<Deployment-B>/servers/robotarm/tests/test_sim_robotarm.py`
- Docs: `helao/deploy/<Deployment-B>/servers/robotarm/README.md`

**Interfaces:**
- Consumes: none.
- Produces: driver config param `moving_eps_rad_s` (float, default `1e-3`); `self._moving_eps: float`.

> **Station check:** offsets 300 (`qd_actual`, 6 doubles) and 756 (`robot_mode`, double) come from UR's real-time (port 30003) client-interface table, the same table the parser already uses for 252/444/588; nothing in the repo pins them. Station row "UR offsets" confirms them against the controller's PolyScope version.

- [ ] **Step 1: Write the failing test**

Append to `servers/robotarm/tests/test_sim_robotarm.py` (it already imports `asyncio`, `pytest`, `Ur10eRobotArmDriver`):

```python
import struct


def _rt_packet(robot_mode: float, qd_actual) -> bytes:
    """A 1060-byte real-time packet, big-endian like the wire.

    Everything is zero except the size header, qd_actual (6 doubles at
    offset 300) and robot_mode (double at offset 756).
    """
    buf = bytearray(1060)
    struct.pack_into(">I", buf, 0, 1060)
    struct.pack_into(">6d", buf, 300, *qd_actual)
    struct.pack_into(">d", buf, 756, robot_mode)
    return bytes(buf)


@pytest.mark.asyncio
async def test_robot_mode_and_motion_come_from_the_packet():
    # async: _parse_rtde_packet stamps last_update_ts from the running loop
    driver = Ur10eRobotArmDriver({"robot_ip": "127.0.0.1"})
    driver._parse_rtde_packet(_rt_packet(7.0, [0, 0, 0.1, 0, 0, 0]))
    assert driver._state["robot_mode"] == 7  # 7 = RUNNING in UR's table
    assert driver._state["is_moving"] is True  # 0.1 rad/s > default 1e-3

    driver._parse_rtde_packet(_rt_packet(7.0, [0.0] * 6))
    assert driver._state["is_moving"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd $ROOT && PYTHONPATH=$ROOT $PY -m pytest helao/deploy/<Deployment-B>/servers/robotarm/tests/test_sim_robotarm.py::test_robot_mode_and_motion_come_from_the_packet -v`
Expected: FAIL with `assert -1 == 7`.

- [ ] **Step 3: Write minimal implementation**

`robotarm_driver.py:59`, after
```python
        self._poll_timeout: float = float(self.config.get("poll_read_timeout", 0.1))
```
add:
```python
        #: joint-speed magnitude above which the arm counts as moving (rad/s)
        self._moving_eps: float = float(self.config.get("moving_eps_rad_s", 1e-3))
```

In `_parse_rtde_packet`, after
```python
        joint_angles = struct.unpack_from(">dddddd", data, 252)
```
add:
```python
        # Actual joint speeds (qd actual), 6 doubles at 300; robot mode, double at 756
        qd_actual = struct.unpack_from(">dddddd", data, 300)
        robot_mode = struct.unpack_from(">d", data, 756)[0]
```

and in the `self._state.update({...})` dict, before `"last_update_ts": ...`, add:
```python
                "is_moving": max(abs(v) for v in qd_actual) > self._moving_eps,
                "robot_mode": int(robot_mode),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd $ROOT && PYTHONPATH=$ROOT $PY -m pytest helao/deploy/<Deployment-B>/servers/robotarm/tests/test_sim_robotarm.py -v`
Expected: PASS (all; the simulator's packet is zero at 300 and 756, so the sim tests see `robot_mode == 0`, `is_moving False` and assert neither).

- [ ] **Step 5: Mutation check**

```bash
git -C $B diff -- servers/robotarm/robotarm_driver.py > /tmp/claude-1000/mut-task27.patch
git -C $B apply -R /tmp/claude-1000/mut-task27.patch
cd $ROOT && PYTHONPATH=$ROOT $PY -m pytest helao/deploy/<Deployment-B>/servers/robotarm/tests/test_sim_robotarm.py -q -k come_from_the_packet   # Expected: 1 failed (assert -1 == 7)
git -C $B apply /tmp/claude-1000/mut-task27.patch
cd $ROOT && PYTHONPATH=$ROOT $PY -m pytest helao/deploy/<Deployment-B>/servers/robotarm/tests/test_sim_robotarm.py -q   # Expected: all passed
```

- [ ] **Step 6: README**

In `helao/deploy/<Deployment-B>/servers/robotarm/README.md`:
- `## Params`: add one row after `poll_read_timeout`: `| \`moving_eps_rad_s\` | no | float | \`1e-3\` | joint-speed magnitude (rad/s) above which the live \`is_moving\` key is true | servers/robotarm/robotarm_driver.py:<line of self._moving_eps> |` (adding a param row is required here; the existing rows are not rewritten).
- `### Live data (status/ws stream)`: row `is_moving` meaning becomes "`max(|qd_actual|) > moving_eps_rad_s`, from the 6 joint-speed doubles at packet offset 300 (offset unverified against the controller's PolyScope version); `false` before the first packet"; row `robot_mode` meaning becomes "UR robot mode, the double at packet offset 756 truncated to int (offset unverified, see the station check); `-1` before the first packet"; written at = the two new `_state.update` lines (init `:69`, `:70`).
- `## Notes`: delete the bullet "- The live-stream keys `is_moving` and `robot_mode` are constants ...". Add: "- `qd_actual` (offset 300) and `robot_mode` (offset 756) follow UR's real-time client-interface table, like the parser's other offsets; confirm them on the controller's PolyScope version before relying on `is_moving`/`robot_mode`."

Run: `cd $ROOT && PYTHONPATH=$ROOT $PY -m pytest helao/deploy/<Deployment-B>/tests/test_readme_outputs.py -q` — Expected: PASS.

- [ ] **Step 7: Commit (main session; subagents never commit)**

```bash
$BLACK $B/servers/robotarm/robotarm_driver.py $B/servers/robotarm/tests/test_sim_robotarm.py
git -C $B branch --show-current   # expect: main
git -C $B status --short
git -C $B add servers/robotarm/robotarm_driver.py servers/robotarm/tests/test_sim_robotarm.py servers/robotarm/README.md
git -C $B commit -m "feat(robotarm): parse robot_mode and joint speeds into the live stream"
```

---

### Task 28: B3 first `start_record` poll reads `get_flow` twice (Deployment-B) — Optional, skip if the plan runs long

**Files:**
- Modify: `helao/deploy/<Deployment-B>/servers/test_station/test_station_server.py:643-670` (`OpcUaStationExec._poll`)
- Test: `helao/deploy/<Deployment-B>/tests/test_station_executors.py`
- Docs: `helao/deploy/<Deployment-B>/servers/test_station/README.md`

**Interfaces:**
- Consumes: `_exec` helper (Task 25 leaves it unchanged).
- Produces: none.

- [ ] **Step 1: Write the failing test**

In `tests/test_station_executors.py`, extend the existing import `from helao.deploy.<Deployment-B>.servers.test_station.test_station_server import (ModeMonitorExec, WaitForTemperatureExec,)` with `OpcUaStationExec`, then append:

```python
@pytest.mark.asyncio
async def test_the_first_record_poll_reads_each_composite_once():
    read = AsyncMock(return_value={"x": 1.0, "error_code": ErrorCodes.none})
    ex = _exec(OpcUaStationExec, {"duration": -1}, read)
    await ex._poll()
    # get_flow already ran to start the clock; the loop must not repeat it.
    assert [c.args[0] for c in read.await_args_list] == [
        "get_flow",
        "get_temperature",
        "get_pressure",
        "get_valves",
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd $ROOT && PYTHONPATH=$ROOT $PY -m pytest helao/deploy/<Deployment-B>/tests/test_station_executors.py::test_the_first_record_poll_reads_each_composite_once -v`
Expected: FAIL with "At index 1 diff: 'get_flow' != 'get_temperature'" (5 reads, `get_flow` twice).

- [ ] **Step 3: Write minimal implementation**

`test_station_server.py` `OpcUaStationExec._poll`: replace

```python
        record = {}
        if self._start_ts is None:
```
with
```python
        record = {}
        done = set()
        if self._start_ts is None:
```

after
```python
            self._start_ts = asyncio.get_running_loop().time()
            LOGGER.info("OpcUaStationExec: recording started")
```
add
```python
            done.add("flow")
```

and replace
```python
        # Read remaining nodes; skip keys already present in record (e.g., flow)
        for tag in ("flow", "temperature", "pressure", "valves"):
            if tag in record:
                continue
```
with
```python
        # Read remaining composites; skip the one the first poll already read
        for tag in ("flow", "temperature", "pressure", "valves"):
            if tag in done:
                continue
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd $ROOT && PYTHONPATH=$ROOT $PY -m pytest helao/deploy/<Deployment-B>/tests/test_station_executors.py -v`
Expected: PASS (all).

- [ ] **Step 5: Mutation check**

```bash
git -C $B diff -- servers/test_station/test_station_server.py > /tmp/claude-1000/mut-task28.patch
git -C $B apply -R /tmp/claude-1000/mut-task28.patch
cd $ROOT && PYTHONPATH=$ROOT $PY -m pytest helao/deploy/<Deployment-B>/tests/test_station_executors.py -q -k reads_each_composite_once   # Expected: 1 failed
git -C $B apply /tmp/claude-1000/mut-task28.patch
cd $ROOT && PYTHONPATH=$ROOT $PY -m pytest helao/deploy/<Deployment-B>/tests/test_station_executors.py -q   # Expected: all passed
```

(Task 25 is already committed, so this diff holds only the Task 28 hunks.)

- [ ] **Step 6: README**

In `helao/deploy/<Deployment-B>/servers/test_station/README.md`, `### start_record` paragraph: replace "every poll then reads `get_flow`, `get_temperature`, `get_pressure` and `get_valves` and merges them (`:694`), because the `if tag in record` skip at `:671` never matches (see Notes)" with "the first poll then reads `get_temperature`, `get_pressure` and `get_valves`; later polls read all four composites and merge them (`:694`)" (re-derive the cited line with `grep -n "record.update" servers/test_station/test_station_server.py`). `## Notes`: delete the bullet "- `OpcUaStationExec._poll` is meant to skip a composite whose data is already in `record` ...". If `## Notes` has no bullets left, delete the heading.

Run: `cd $ROOT && PYTHONPATH=$ROOT $PY -m pytest helao/deploy/<Deployment-B>/tests/test_readme_outputs.py -q` — Expected: PASS.

- [ ] **Step 7: Commit (main session; subagents never commit)**

```bash
$BLACK $B/servers/test_station/test_station_server.py $B/tests/test_station_executors.py
git -C $B branch --show-current   # expect: main
git -C $B status --short
git -C $B add servers/test_station/test_station_server.py tests/test_station_executors.py servers/test_station/README.md
git -C $B commit -m "fix(test_station): read get_flow once on the first start_record poll"
```

---

### Task 29: A2 motion timeout raises; `qmove` no longer read after the loop (Deployment-A)

Reviewed side by side with Task 7 before either is pushed.

**Files:**
- Modify: `helao/deploy/<Deployment-A>/servers/motion/thorlabs_kinesis.py:58` (new exception class above `cmd_exception`), `:462-467` (`motor_move` re-raises it), `:748-787` (settle-loop classification)
- Test: `helao/deploy/<Deployment-A>/servers/motion/tests/test_motor_move.py`
- Docs: `helao/deploy/<Deployment-A>/servers/motion/README.md`

**Interfaces:**
- Consumes: none.
- Produces: `class MotionTimeoutError(RuntimeError)` in `helao/deploy/<Deployment-A>/servers/motion/thorlabs_kinesis.py`. Message format, identical to Task 7's galil raise (same f-string, each driver's own timeout attribute): `f"motion timeout: axes {axis} not stopped after {self.motor_timeout} s"`. Both raise a `RuntimeError` (here a subclass) whose message starts `motion timeout:`. `ThorlabsMotor.motor_move(active)` now propagates `MotionTimeoutError` (all other exceptions are still caught and reported as `ErrorCodes.motor`).

> **Escalation (resolved in this task, flag at review):** the spec puts the raise in the settle loop, but the action route calls `ThorlabsMotor.motor_move` (`motion_server.py:300`, `:323`), whose `except Exception` (`thorlabs_kinesis.py:467-477`) would swallow a bare `RuntimeError` and return `err_code: motor`, which E-STOPs the station, the opposite of decision 1. Galil's `motor_move` (`galil_motion_native.py:792-815` on hte `origin/main`) has no such catch, so Task 7 needs nothing extra. Safest option chosen: a `RuntimeError` subclass that only `motor_move` re-raises, so every other unexpected fault keeps today's `motor` code. Re-raising all `RuntimeError`s was rejected: it would turn unrelated faults from E-STOP into pause and re-queue.
>
> The spec also says to initialize `qmove = {...}` before the loop. That is not needed here: after the fix nothing reads `qmove` after the loop, so the `UnboundLocalError` at `:770` goes away with the deleted re-map loop. Test (b) checks this.

- [ ] **Step 1: Write the failing tests**

Append to `helao/deploy/<Deployment-A>/servers/motion/tests/test_motor_move.py`. The imports go at the top, beside the existing ones:

```python
from types import SimpleNamespace

import pytest
```

The tests go at the end of the file:

```python
# --- motion timeout (shared rule with the hte galil driver) -----------------


class StuckKinesisMotor(FakeKinesisMotor):
    """Reports a MOVESTATUS_KEYS entry forever: the stage never settles."""

    def get_status(self) -> list:
        return ["moving_fw"]


def _relative_x_move(driver):
    return driver._motor_move(
        d_mm=[1.0],
        axis=["x"],
        speed=None,
        mode=MoveModes.relative,
        transformation=TransformationModes.motorxy,
    )


def test_motor_move_raises_on_a_real_timeout_and_halts_the_axis():
    # The axis still reports moving when timeout=1 s passes. The shared rule says:
    # stop the axis, then raise. Today the code returns err_code [none].
    driver, motors = _make_driver(axis_id={"x": "SN1"}, count_to_mm={"x": 1e-3}, timeout=1)
    stuck = StuckKinesisMotor()
    motors["x"] = stuck

    with pytest.raises(RuntimeError, match="motion timeout"):
        asyncio.run(_relative_x_move(driver))

    assert stuck.stop_calls, "stop_axis must halt the stage before raising"
    assert driver.motor_busy is False


def test_motor_move_route_entry_propagates_the_timeout():
    # The action routes call motor_move(active), not _motor_move. The timeout must
    # reach the route as an exception (HTTP 500 -> the orch pauses and re-queues),
    # not as a returned err_code (which E-STOPs).
    driver, motors = _make_driver(axis_id={"x": "SN1"}, count_to_mm={"x": 1e-3}, timeout=1)
    motors["x"] = StuckKinesisMotor()
    active = SimpleNamespace(
        action=SimpleNamespace(
            action_params={"d_mm": [1.0], "axis": ["x"], "mode": MoveModes.relative}
        )
    )

    with pytest.raises(RuntimeError, match="motion timeout"):
        asyncio.run(driver.motor_move(active))

    assert driver.blocked is False
    assert driver.motor_busy is False


def test_motor_move_with_zero_timeout_raises_the_timeout_not_unbound_local():
    # timeout=0: the settle loop body never runs, so no axis was ever seen stopped.
    # Today the post-loop re-map reads the unassigned qmove (UnboundLocalError).
    driver, _motors = _make_driver(axis_id={"x": "SN1"}, count_to_mm={"x": 1e-3}, timeout=0)

    with pytest.raises(RuntimeError, match="motion timeout"):
        asyncio.run(_relative_x_move(driver))


def test_motor_move_that_settles_in_time_still_reports_none():
    # Regression guard: FakeKinesisMotor reports stopped at the first poll.
    driver, _motors = _make_driver(axis_id={"x": "SN1"}, count_to_mm={"x": 1e-3}, timeout=5)

    result = asyncio.run(_relative_x_move(driver))

    assert result["err_code"] == [ErrorCodes.none]


def test_next_move_is_accepted_after_a_timeout_raise():
    # Review focus RF5: the raise must release motor_busy and blocked, so the
    # station's next move is accepted and not refused as in_progress.
    driver, motors = _make_driver(axis_id={"x": "SN1"}, count_to_mm={"x": 1e-3}, timeout=1)
    motors["x"] = StuckKinesisMotor()
    with pytest.raises(RuntimeError, match="motion timeout"):
        asyncio.run(_relative_x_move(driver))

    motors["x"] = FakeKinesisMotor()  # the stage is free again
    result = asyncio.run(_relative_x_move(driver))

    assert result["err_code"] == [ErrorCodes.none]
    assert result["moved_axis"] == ["x"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/<Deployment-A>/servers/motion/tests/test_motor_move.py -k "timeout or settles_in_time or next_move" -v`
Expected:
- FAIL `test_motor_move_raises_on_a_real_timeout_and_halts_the_axis` and `test_motor_move_route_entry_propagates_the_timeout` with `Failed: DID NOT RAISE <class 'RuntimeError'>`.
- FAIL `test_motor_move_with_zero_timeout_raises_the_timeout_not_unbound_local` with `UnboundLocalError: cannot access local variable 'qmove' where it is not associated with a value`.
- FAIL `test_next_move_is_accepted_after_a_timeout_raise` with `DID NOT RAISE`.
- PASS `test_motor_move_that_settles_in_time_still_reports_none` (the regression guard).

All three red results were confirmed against `e287ef1`.

- [ ] **Step 3: Write minimal implementation**

`thorlabs_kinesis.py:58`: insert this directly above `class cmd_exception(ValueError):`.

```python
class MotionTimeoutError(RuntimeError):
    """Axes still not ``stopped`` when ``motor_timeout`` ran out.

    Raised, not reported as an ``err_code``: an orchestrator E-STOPs the station
    on any non-``none`` action error code, but pauses and re-queues an action
    whose endpoint raises. ``motor_move`` re-raises only this class.
    """


```

`thorlabs_kinesis.py:462-467` (`motor_move`): add a re-raise ahead of the catch-all.

Old:
```python
            else:
                err_code = ErrorCodes.in_progress
                raise ValueError("motor is blocked or disabled")
        except Exception:
            logger.error("motor_move failed", exc_info=True)
```
New:
```python
            else:
                err_code = ErrorCodes.in_progress
                raise ValueError("motor is blocked or disabled")
        except MotionTimeoutError:
            raise
        except Exception:
            logger.error("motor_move failed", exc_info=True)
```

`thorlabs_kinesis.py:748-776` (`_motor_move_body` settle loop):

Old:
```python
        if not self._is_estopped():
            # check if all axis stopped
            tstart = time.time()

            while (
                time.time() - tstart < self.motor_timeout
            ) and not self._is_estopped():
                qmove = await self.query_axis_moving(axis=axis)
                await asyncio.sleep(0.5)
                # an empty list means the query failed, not that all stopped
                if qmove["motor_status"] and all(
                    status == "stopped" for status in qmove["motor_status"]
                ):
                    break

            if not self._is_estopped():
                # stop of motor movement (motor still on)
                if time.time() - tstart > self.motor_timeout:
                    await self.stop_axis(axis)
                # check which axis had the timeout
                newret_err_code = []
                for erridx, err_code in enumerate(ret_err_code):
                    if qmove["err_code"][erridx] != ErrorCodes.none:
                        newret_err_code.append(ErrorCodes.timeout)
                        logger.info("motor timeout error", exc_info=True)
                    else:
                        newret_err_code.append(err_code)

                ret_err_code = newret_err_code
            else:
```
New:
```python
        if not self._is_estopped():
            # check if all axis stopped
            tstart = time.time()
            all_stopped = False

            while (
                time.time() - tstart < self.motor_timeout
            ) and not self._is_estopped():
                qmove = await self.query_axis_moving(axis=axis)
                await asyncio.sleep(0.5)
                # an empty list means the query failed, not that all stopped
                if qmove["motor_status"] and all(
                    status == "stopped" for status in qmove["motor_status"]
                ):
                    all_stopped = True
                    break

            if not self._is_estopped():
                if not all_stopped:
                    # deadline passed, or the last query failed: halt the
                    # stages (motors stay on) and raise (see MotionTimeoutError)
                    await self.stop_axis(axis)
                    raise MotionTimeoutError(
                        f"motion timeout: axes {axis} not stopped after {self.motor_timeout} s"
                    )
                # every axis reported stopped, so each query code is none
                # (query_axis_moving) and the move's own per-axis codes stand
            else:
```
The `else:` branch (the estop path) and everything after it stay unchanged. `motor_busy` is released by the existing `finally` in `_motor_move` (`:524-529`), and `blocked` by the existing `finally` in `motor_move` (`:462-463`).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/<Deployment-A>/servers/motion/tests/ -v`
Expected: PASS, covering the 5 new tests and every existing test in `test_motor_move.py`, `test_motion_private_endpoints.py`, `test_estop.py`, `test_motion_counts.py`, `test_calibration_store.py` and `test_transform_equivalence.py`.

- [ ] **Step 5: Mutation check**

```bash
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-A> diff -- servers/motion/thorlabs_kinesis.py > /tmp/claude-1000/mut-task29.patch && git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-A> apply -R /tmp/claude-1000/mut-task29.patch
cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/<Deployment-A>/servers/motion/tests/test_motor_move.py -k "timeout or next_move" -q
```
Expected: 4 failed, with the same reasons as Step 2.

```bash
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-A> apply /tmp/claude-1000/mut-task29.patch
cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/<Deployment-A>/servers/motion/tests/test_motor_move.py -q
```
Expected: all pass.

A second, partial mutation: revert only the `except MotionTimeoutError: raise` two lines by hand. `test_motor_move_route_entry_propagates_the_timeout` must fail (`DID NOT RAISE`), which proves the route-level test guards the escalation. Restore the lines afterwards.

- [ ] **Step 6: README**

In `helao/deploy/<Deployment-A>/servers/motion/README.md`:

1. `### move, easymove (actions)` intro paragraph (line 75). Append this sentence at its end, before `No action results:`. `<L>` is the line of the `raise MotionTimeoutError(` statement after Step 3; get it with `grep -n "raise MotionTimeoutError" helao/deploy/<Deployment-A>/servers/motion/thorlabs_kinesis.py`.
   `If every configured axis has not reported stopped within the config timeout (motor_timeout), including when the last query failed, the driver halts the axes with stop_axis and raises MotionTimeoutError("motion timeout: ..."), helao/deploy/<Deployment-A>/servers/motion/thorlabs_kinesis.py:<L>. The action then ends with HTTP 500 and no row is queued, so an orchestrator pauses and re-queues it instead of E-STOPping.`
2. Replace the `err_code` row's meaning cell (line 84), which today reads: ``ErrorCodes` value per axis: `none`, `setup`, `numerical`, `motor`, `timeout` (only when the final `query_axis_moving` result carries a non-`none` code, i.e. that query failed: APT disabled or an exception, `thorlabs_kinesis.py:769-776`, `:961-967`), or `estop``. The new text is: ``ErrorCodes` value per axis: `none`, `setup`, `numerical`, `motor`, or `estop`. A timeout is never reported here: it raises (see above)`. In the row's `written at` cell, replace `` `:776`, `:779`, `:783` `` with the post-edit lines of the two `ret_err_code = [ErrorCodes.estop for _ in ret_err_code]` assignments (`grep -n "ErrorCodes.estop for _ in ret_err_code" .../thorlabs_kinesis.py`). Keep `:720`, which is the `ret_err_code.append(ErrorCodes.none)` line and is unchanged; re-check it with grep.
3. `## Notes`: delete the bullet that starts with ``- `move`/`easymove` never report `timeout` for an axis still moving after `motor_timeout``. Keep the heading; Task 30 removes the remaining bullets.

Guard: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/<Deployment-A>/tests/test_readme_outputs.py -q`. Expected: PASS.

- [ ] **Step 7: Commit (main session; subagents never commit)**

Hold this commit until Task 7 has been reviewed side by side with it (same exception type family, message prefix, busy release).

```bash
/home/dan/miniforge3/envs/helao/bin/black helao/deploy/<Deployment-A>/servers/motion/thorlabs_kinesis.py helao/deploy/<Deployment-A>/servers/motion/tests/test_motor_move.py
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-A> branch --show-current   # expect: main
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-A> status --short
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-A> add servers/motion/thorlabs_kinesis.py servers/motion/tests/test_motor_move.py servers/motion/README.md
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-A> commit -m "fix(motion): raise on a real move timeout instead of reporting none"
```
This is a local commit. Do not push.

---

---

### Task 30: A3 `MxytoMPlate` row serializes; README catch-up for P1/P4 (Deployment-A)

**Files:**
- Modify: `helao/deploy/<Deployment-A>/servers/motion/motion_server.py:266-272`
- Test: `helao/deploy/<Deployment-A>/servers/motion/tests/test_motion_private_endpoints.py`
- Docs: `helao/deploy/<Deployment-A>/servers/motion/README.md`, `helao/deploy/<Deployment-A>/processors/README.md`

**Interfaces:**
- Consumes: from Task 3 (parent P2), `TransformXY.get_Mplate_Msystem(Mxy, *args, **kwargs)` does `json.loads` on a `str` `Mxy`, raises `ValueError("Mxy required")` on `None`, and still returns `np.matrix` (or `None` when `Minstr` is singular). From Task 2 (parent P1), `f"{ErrorCodes.none}" == "none"`. From Task 5 (parent P4), `MetaProcessor.global_params = getattr(core, "global_params", None) or {}`. All three must be committed on parent `unstable` before this task runs: this repo's tests import the parent from `/mnt/STORAGE/repos/helao/helao-async`.
- Produces: none.

- [ ] **Step 1: Write the failing test**

Append to `helao/deploy/<Deployment-A>/servers/motion/tests/test_motion_private_endpoints.py`. Add the import at the top beside the existing imports:

```python
from helao.helpers.to_json import hlo_json_dumps
```

The test goes at the end of the file:

```python
class _MxyActive:
    """The slice of an active action that MxytoMPlate touches."""

    def __init__(self, action_params):
        self.action = types.SimpleNamespace(action_params=action_params)
        self.rows = []

    async def enqueue_data_dflt(self, datadict):
        self.rows.append(datadict)

    async def finish(self):
        return types.SimpleNamespace(as_dict=lambda: {})


class _MxyCtx:
    def __init__(self, active):
        self.active = active

    async def begin(self, action_abbr=None, **kwargs):
        return self.active


def test_mxytomplate_row_is_a_serialisable_list(make_app):
    # Identity Minstr (make_app) and an identity Mxy give Mplate = identity
    # (Minstr^-1 * Mglobal with Mglobal = identity). The value is derived by hand,
    # not from the transform.
    app = make_app()
    active = _MxyActive({"Mxy": "[[1,0,0],[0,1,0],[0,0,1]]"})

    asyncio.run(app.routes["/MOTION/MxytoMPlate"].fn(ctx=_MxyCtx(active)))

    (row,) = active.rows
    hlo_json_dumps(row)  # the data logger's serializer: np.matrix raises TypeError
    assert row["mplate"] == [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/<Deployment-A>/servers/motion/tests/test_motion_private_endpoints.py::test_mxytomplate_row_is_a_serialisable_list -v`
Expected: FAIL with `TypeError: Type is not JSON serializable: matrix` raised by `hlo_json_dumps`, because Task 3 already parses the string. If Task 3 is not yet on `unstable`, it instead fails with `IndexError: too many indices for array: array is 0-dimensional, but 2 were indexed`, which was confirmed against `e287ef1` plus parent `37738012`. Stop and land Task 3 first.

- [ ] **Step 3: Write minimal implementation**

`motion_server.py:266-272`

Old:
```python
        active = await ctx.begin(action_abbr="mxytomplate")
        await active.enqueue_data_dflt(
            datadict={
                "mplate": app.driver.transform.get_Mplate_Msystem(
                    **active.action.action_params
                )
            }
        )
```
New:
```python
        active = await ctx.begin(action_abbr="mxytomplate")
        M = app.driver.transform.get_Mplate_Msystem(**active.action.action_params)
        # np.matrix is not serialisable by the data logger; a singular Minstr gives None
        await active.enqueue_data_dflt(
            datadict={"mplate": None if M is None else M.tolist()}
        )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/<Deployment-A>/servers/motion/tests/ -v`
Expected: PASS, the new test and all existing motion tests.

- [ ] **Step 5: Mutation check**

```bash
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-A> diff -- servers/motion/motion_server.py > /tmp/claude-1000/mut-task30.patch && git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-A> apply -R /tmp/claude-1000/mut-task30.patch
cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/<Deployment-A>/servers/motion/tests/test_motion_private_endpoints.py::test_mxytomplate_row_is_a_serialisable_list -q
```
Expected: FAIL with `TypeError: Type is not JSON serializable: matrix`.

```bash
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-A> apply /tmp/claude-1000/mut-task30.patch
cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/<Deployment-A>/servers/motion/tests/test_motion_private_endpoints.py::test_mxytomplate_row_is_a_serialisable_list -q
```
Expected: PASS.

- [ ] **Step 6: README** (A3, plus the P1/P4 README catch-up that the spec assigns to this repo once U1 lands)

`helao/deploy/<Deployment-A>/servers/motion/README.md`:
1. The `mplate` row (line 143). Set the type to `float | null` and the structure to `list[list[float]]`, and replace the meaning with: `MxytoMPlate`: the plate matrix recovered from `Mxy`, a JSON nested-list string (3x3), parsed by `helao/hexagon/domain/motion_transform.py` (`get_Mplate_Msystem`), as a 3x3 nested list (`M.tolist()`); `null` when `Minstr` is singular. A missing `Mxy` raises `ValueError("Mxy required")` before any row (HTTP 500).`. Change the `written at` cell to the post-edit `datadict={"mplate": ...}` line in `helao/deploy/<Deployment-A>/servers/motion/motion_server.py` (find it with `grep -n '"mplate"' .../motion_server.py`).
2. The aligner `err_code` row (line 160). Replace the meaning with: `f"{errorcode}"` of an `ErrorCodes` member: the value (`none`, or `stop` from the stop path), because `ErrorCodes.__str__` is `str.__str__` (`helao/core/error.py`). Rows written under Python 3.12+ before that parent fix carry `ErrorCodes.none`/`ErrorCodes.stop`, so readers accept both spellings.`
3. `## Notes`: delete the bullet starting ``- `MxytoMPlate` queues a `numpy.matrix``, and the bullet starting ``- The aligner row's `err_code` renders as `ErrorCodes.none``. Task 29 already removed the timeout bullet, so the section is now empty: delete the `## Notes` heading and the blank line before it too.

`helao/deploy/<Deployment-A>/processors/README.md`:
4. The `ref_vshe` row (line 17). Set the type to `float | null`, and set the meaning to: the orchestrator's `global_params["last_OCP_V"]` (`self.global_params.get("last_OCP_V", None)`), the final mean open-circuit potential (V) of the last SDC OCV experiment that published it; `null` when no experiment has published it yet. `MetaProcessor` reads `global_params` off any server that has one (`helao/helpers/processors.py`).`
5. Delete the whole `## Notes` section (its only bullet describes the `"orch"` class-name check that Task 5 fixed).

Guard: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/<Deployment-A>/tests/test_readme_outputs.py -q`. Expected: PASS.

- [ ] **Step 7: Commit (main session; subagents never commit)**

```bash
/home/dan/miniforge3/envs/helao/bin/black helao/deploy/<Deployment-A>/servers/motion/motion_server.py helao/deploy/<Deployment-A>/servers/motion/tests/test_motion_private_endpoints.py
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-A> branch --show-current   # expect: main
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-A> status --short
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-A> add servers/motion/motion_server.py servers/motion/tests/test_motion_private_endpoints.py servers/motion/README.md processors/README.md
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-A> commit -m "fix(motion): MxytoMPlate queues the plate matrix as a list"
```
This is a local commit. Do not push.

---

---

### Task 31: A4 muxvalve `get_valve` names the valve on the queried MUX (Deployment-A)

**Files:**
- Modify: `helao/deploy/<Deployment-A>/servers/muxvalve/muxvalve_server.py:48-51`
- Test: `helao/deploy/<Deployment-A>/servers/muxvalve/tests/test_valve_name.py` (new; also create an empty `helao/deploy/<Deployment-A>/servers/muxvalve/tests/__init__.py`, as `servers/motion/tests/` has)
- Docs: `helao/deploy/<Deployment-A>/servers/muxvalve/README.md`

**Interfaces:**
- Consumes: none.
- Produces: none.

- [ ] **Step 1: Write the failing test**

Create `helao/deploy/<Deployment-A>/servers/muxvalve/tests/__init__.py`, empty. Then create `helao/deploy/<Deployment-A>/servers/muxvalve/tests/test_valve_name.py`:

```python
"""get_valve resolves valve_name on the queried MUX, as set_valve_number does.

The route is driven through mux_dyn_endpoints with a fake app and driver, so
no Elveflow SDK or hardware is involved.
"""

import asyncio
import types

from helao.deploy.<Deployment-A>.servers.muxvalve import muxvalve_server


class _Driver:
    mux_items = str
    valve_items = str
    # Two MUXes that both have a valve at position 1.
    mux_map = {"a": ("m0", 1), "b": ("m1", 1)}

    def get_valve(self, mux_id=None, **kwargs):
        return 1


class _App:
    def __init__(self):
        self.driver = _Driver()
        self.server = types.SimpleNamespace(server_name="MUX")
        self.routes = {}

    def action(self, **kwargs):
        def _register(fn):
            self.routes[fn.__name__] = fn
            return fn

        return _register

    def post(self, path, **kwargs):
        def _register(fn):
            self.routes[path] = fn
            return fn

        return _register


class _Active:
    def __init__(self, action_params):
        self.action = types.SimpleNamespace(action_params=action_params, error_code=None)
        self.rows = []

    async def enqueue_data_dflt(self, datadict):
        self.rows.append(datadict)

    async def finish(self):
        return types.SimpleNamespace(as_dict=lambda: {})


class _Ctx:
    def __init__(self, active):
        self.active = active

    async def begin(self, action_abbr=None, **kwargs):
        return self.active


def test_get_valve_names_the_valve_on_the_queried_mux():
    # Position 1 on MUX m1 is valve "b" in the config. Valve "a" is position 1 on m0.
    app = _App()
    asyncio.run(muxvalve_server.mux_dyn_endpoints(app))
    active = _Active({"mux_id": "m1"})

    asyncio.run(app.routes["get_valve"](ctx=_Ctx(active)))

    assert active.rows[0]["valve_name"] == "b"
    assert active.action.action_params["valve_name"] == "b"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/<Deployment-A>/servers/muxvalve/tests/test_valve_name.py -v`
Expected: FAIL with `AssertionError: assert 'a' == 'b'`. Confirmed against `e287ef1`.

- [ ] **Step 3: Write minimal implementation**

`muxvalve_server.py:48-51`

Old:
```python
        valve_name = next(
            (k for k, (_, v) in app.driver.mux_map.items() if v == valve_number),
            None,
        )
```
New:
```python
        valve_name = next(
            (
                k
                for k, (m, v) in app.driver.mux_map.items()
                if m == active.action.action_params["mux_id"] and v == valve_number
            ),
            None,
        )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/<Deployment-A>/servers/muxvalve/tests/test_valve_name.py helao/deploy/<Deployment-A>/tests/test_p4d_crash_fixes.py -v`
Expected: PASS.

- [ ] **Step 5: Mutation check**

```bash
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-A> diff -- servers/muxvalve/muxvalve_server.py > /tmp/claude-1000/mut-task31.patch && git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-A> apply -R /tmp/claude-1000/mut-task31.patch
cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/<Deployment-A>/servers/muxvalve/tests/test_valve_name.py -q
```
Expected: FAIL with `assert 'a' == 'b'`.

```bash
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-A> apply /tmp/claude-1000/mut-task31.patch
cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/<Deployment-A>/servers/muxvalve/tests/test_valve_name.py -q
```
Expected: PASS.

- [ ] **Step 6: README**

In `helao/deploy/<Deployment-A>/servers/muxvalve/README.md`:
1. The `valve_name` row of `get_valve` (line 43). Replace its meaning `first configured valve name whose position number equals `valve_number`, on any MUX; `null` when no configured valve has that number` with `configured valve name on the queried MUX (`mux_id`) whose position number equals `valve_number`; `null` when that MUX has no configured valve at that position`. Change the `written at` cell to the post-edit line span of the `valve_name = next(` expression (from `grep -n "valve_name = next" .../muxvalve_server.py`; it is the first hit), then `:55` shifted by the same 4 lines, which is the `"valve_name": valve_name` line. Re-check both with grep.
2. Row 50 (`valve_name` in `action_params`): update its cited line `:58` to the post-edit line (+4).
3. Delete the whole `## Notes` section. Its only bullet is the fixed `get_valve` defect.

Guard: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/deploy/<Deployment-A>/tests/test_readme_outputs.py -q`. Expected: PASS.

- [ ] **Step 7: Commit (main session; subagents never commit)**

```bash
/home/dan/miniforge3/envs/helao/bin/black helao/deploy/<Deployment-A>/servers/muxvalve/muxvalve_server.py helao/deploy/<Deployment-A>/servers/muxvalve/tests/test_valve_name.py
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-A> branch --show-current   # expect: main
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-A> status --short
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-A> add servers/muxvalve/muxvalve_server.py servers/muxvalve/tests/__init__.py servers/muxvalve/tests/test_valve_name.py servers/muxvalve/README.md
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/<Deployment-A> commit -m "fix(muxvalve): get_valve matches the valve on the queried MUX"
```
This is a local commit. Do not push.

---

### Task 32: E1 scaler refine keeps the source's `version`/`created_utc` (Deployment-E)

**Files:**
- Modify: `helao/deploy/<Deployment-E>/servers/calc/spectrum_utils.py:191-203` (`OceanScaler.from_dict`)
- Test: `helao/deploy/<Deployment-E>/servers/calc/tests/test_spectrum_utils.py`
- Docs: `helao/deploy/<Deployment-E>/servers/calc/README.md`

**Interfaces:**
- Consumes: `OceanScaler`, `load_scaler`, `scaler_path` (existing, already imported by the test file).
- Produces: scaler JSON key `source_created_utc: str` (present only on a scaler loaded from a file that carried `created_utc`).

- [ ] **Step 1: Write the failing test**

Append to `servers/calc/tests/test_spectrum_utils.py` (`json`, `np`, `OceanScaler`, `load_scaler`, `scaler_path`, `TARGET_WL`, `SCALE_VEC` are already there):

```python
def test_a_resaved_scaler_describes_itself_and_keeps_its_origin(tmp_path):
    path = scaler_path(tmp_path, "station", "OCEAN")
    OceanScaler(TARGET_WL, SCALE_VEC).save(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw.update(version=1, created_utc="2000-01-01T00:00:00+00:00")
    path.write_text(json.dumps(raw), encoding="utf-8")

    first = load_scaler(path).to_dict()
    # to_dict writes the v2 encoding now, so the label must say 2 and the
    # creation time must be now; the loaded file's time is the lineage origin.
    assert first["version"] == 2
    assert first["created_utc"] != "2000-01-01T00:00:00+00:00"
    assert first["source_created_utc"] == "2000-01-01T00:00:00+00:00"

    path.write_text(json.dumps(first), encoding="utf-8")
    second = load_scaler(path).to_dict()
    assert second["source_created_utc"] == "2000-01-01T00:00:00+00:00"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd $ROOT && PYTHONPATH=$ROOT $PY -m pytest helao/deploy/<Deployment-E>/servers/calc/tests/test_spectrum_utils.py::test_a_resaved_scaler_describes_itself_and_keeps_its_origin -v`
Expected: FAIL with `assert 1 == 2`.

- [ ] **Step 3: Write minimal implementation**

`spectrum_utils.py:191-203`, replace:

```python
    @classmethod
    def from_dict(cls, raw: dict) -> "OceanScaler":
        """Rebuild a scaler from :meth:`to_dict` output."""
        return cls(
            target_wl=raw["target_wl"],
            scale_vec=[np.nan if v is None else v for v in raw["scale_vec"]],
            target_columns=raw.get("target_columns"),
            meta={
                k: v
                for k, v in raw.items()
                if k not in ("target_wl", "target_columns", "scale_vec")
            },
        )
```

with:

```python
    @classmethod
    def from_dict(cls, raw: dict) -> "OceanScaler":
        """Rebuild a scaler from :meth:`to_dict` output.

        ``version`` and ``created_utc`` describe the file being written, so
        they are not carried in ``meta``; the first loaded ``created_utc`` is
        kept as ``source_created_utc`` across repeated refines.
        """
        meta = {
            k: v
            for k, v in raw.items()
            if k
            not in ("target_wl", "target_columns", "scale_vec", "version", "created_utc")
        }
        if "created_utc" in raw:
            meta.setdefault("source_created_utc", raw["created_utc"])
        return cls(
            target_wl=raw["target_wl"],
            scale_vec=[np.nan if v is None else v for v in raw["scale_vec"]],
            target_columns=raw.get("target_columns"),
            meta=meta,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd $ROOT && PYTHONPATH=$ROOT $PY -m pytest helao/deploy/<Deployment-E>/servers/calc/tests/ -v`
Expected: PASS (all, including `test_json_round_trip_preserves_the_scaler` and the refine tests).

- [ ] **Step 5: Mutation check**

```bash
git -C $E diff -- servers/calc/spectrum_utils.py > /tmp/claude-1000/mut-task32.patch
git -C $E apply -R /tmp/claude-1000/mut-task32.patch
cd $ROOT && PYTHONPATH=$ROOT $PY -m pytest helao/deploy/<Deployment-E>/servers/calc/tests/test_spectrum_utils.py -q -k keeps_its_origin   # Expected: 1 failed (assert 1 == 2)
git -C $E apply /tmp/claude-1000/mut-task32.patch
cd $ROOT && PYTHONPATH=$ROOT $PY -m pytest helao/deploy/<Deployment-E>/servers/calc/tests/ -q   # Expected: all passed
```

- [ ] **Step 6: README**

In `helao/deploy/<Deployment-E>/servers/calc/README.md`, scaler JSON schema table:
- Row `version`: meaning "scaler format version; always `2`, the encoding `to_dict` writes (a loaded file's value is dropped by `from_dict`)"; written at `utils:182` plus the `from_dict` exclusion line.
- Row `created_utc`: meaning "time this file was written (`to_dict`); a refined scaler gets the refine time"; written at `utils:183`.
- Add a row after `created_utc`: `| \`source_created_utc\` | str | scalar | ISO 8601 UTC, seconds | \`created_utc\` of the first file this scaler lineage was loaded from; kept across repeated refines; absent on a freshly derived scaler | \`utils:<line of meta.setdefault>\` |`.
- `## Notes`: delete the bullet "- The scaler JSON's `created_utc` is not refreshed by a refine ...". It is the only bullet, so delete the `## Notes` heading too.

Run: `cd $ROOT && PYTHONPATH=$ROOT $PY -m pytest helao/deploy/<Deployment-E>/tests/test_readme_outputs.py -q` — Expected: PASS.

- [ ] **Step 7: Commit (main session; subagents never commit)**

```bash
$BLACK $E/servers/calc/spectrum_utils.py $E/servers/calc/tests/test_spectrum_utils.py
git -C $E branch --show-current   # expect: main
git -C $E status --short
git -C $E add servers/calc/spectrum_utils.py servers/calc/tests/test_spectrum_utils.py servers/calc/README.md
git -C $E commit -m "fix(calc): refined scaler carries its own version/created_utc, origin as source_created_utc"
```

---

### Task 33: E2 oceandirect drops `dev_ts_ns` per packet; empty timestamp list raises (Deployment-E)

**Files:**
- Modify: `helao/deploy/<Deployment-E>/servers/oceandirect/oceandirect_driver.py:1415-1422` (`build_rows`); `helao/deploy/<Deployment-E>/servers/oceandirect/oceandirect_server.py:194` (`OceanDirectBufferExec._poll`)
- Test: `helao/deploy/<Deployment-E>/servers/oceandirect/tests/test_oceandirect_driver.py`, `helao/deploy/<Deployment-E>/servers/oceandirect/tests/test_oceandirect_server.py`
- Docs: `helao/deploy/<Deployment-E>/servers/oceandirect/README.md`

**Interfaces:**
- Consumes: `_connected()` (existing, `test_oceandirect_driver.py:56`); `_executor(driver, **params)` and the `built` fixture (existing, `test_oceandirect_server.py`).
- Produces: `OceanDirectSpec.build_rows(spectra, epochs, dev_timestamps=None)` contract: the `dev_ts_ns` column is present iff `dev_timestamps is not None`.

- [ ] **Step 1: Write the failing tests**

Append to `servers/oceandirect/tests/test_oceandirect_driver.py`:

```python
def test_build_rows_keeps_dev_ts_ns_when_the_caller_passed_stamps_even_if_none():
    """A caller that passes a stamp list declared the column; an unstamped
    packet must still carry it so read_hlo stays row-aligned across packets."""
    drv = _connected()
    spectrum, epoch_s = drv.acquire_spectrum()
    rows = drv.build_rows([spectrum], [epoch_s], dev_timestamps=[None])
    assert rows["dev_ts_ns"] == [None]
```

Append to `servers/oceandirect/tests/test_oceandirect_server.py`:

```python
def test_a_batch_with_no_device_stamps_falls_back_to_drain_time(built, monkeypatch):
    """Spectra with an empty stamp list must not index timestamps[-1]."""
    ex = _executor(built.driver, n_scans=10, dry_polls_to_finish=1)
    asyncio.run(ex._pre_exec())
    monkeypatch.setattr(
        built.driver,
        "drain_buffered",
        lambda n: ([[0.0] * built.driver.n_pixels], []),
    )
    out = asyncio.run(ex._poll())
    assert out["data"]["dev_ts_ns"] == [None]
    assert len(out["data"]["epoch_s"]) == 1
    asyncio.run(ex._post_exec())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd $ROOT && PYTHONPATH=$ROOT $PY -m pytest helao/deploy/<Deployment-E>/servers/oceandirect/tests/test_oceandirect_driver.py::test_build_rows_keeps_dev_ts_ns_when_the_caller_passed_stamps_even_if_none helao/deploy/<Deployment-E>/servers/oceandirect/tests/test_oceandirect_server.py::test_a_batch_with_no_device_stamps_falls_back_to_drain_time -v`
Expected: 2 FAIL — `KeyError: 'dev_ts_ns'` and `IndexError: list index out of range` at `oceandirect_server.py:196`.

- [ ] **Step 3: Write minimal implementation**

`oceandirect_driver.py:1415-1422`, replace:

```python
        if all(value is None for value in cols["dev_ts_ns"]):
            # Nothing in this payload has a device timestamp, which is the
            # normal case for the single-shot path and the case for any device
            # whose metadata feature is absent. Emitting the column anyway
            # tells a reader nothing it could not infer from the column's
            # absence. A partially-populated column is kept whole, so
            # positional alignment with the others is never disturbed.
            del cols["dev_ts_ns"]
```

with:

```python
        if dev_timestamps is None:
            # The single-shot and triggered paths pass no stamps and declare
            # no dev_ts_ns column. A caller that passed a list (the buffered
            # path) declared the column, so every packet keeps it, null where
            # a stamp is missing, and read_hlo stays row-aligned.
            del cols["dev_ts_ns"]
```

`oceandirect_server.py:194`, replace:

```python
        if all(t is not None for t in timestamps):
```

with:

```python
        if timestamps and all(t is not None for t in timestamps):
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd $ROOT && PYTHONPATH=$ROOT $PY -m pytest helao/deploy/<Deployment-E>/servers/oceandirect/tests/ -v`
Expected: PASS (all, including `test_build_rows_omits_dev_ts_ns_when_nothing_carries_one`, which passes no `dev_timestamps`).

- [ ] **Step 5: Mutation check**

```bash
git -C $E diff -- servers/oceandirect/oceandirect_driver.py servers/oceandirect/oceandirect_server.py > /tmp/claude-1000/mut-task33.patch
git -C $E apply -R /tmp/claude-1000/mut-task33.patch
cd $ROOT && PYTHONPATH=$ROOT $PY -m pytest helao/deploy/<Deployment-E>/servers/oceandirect/tests/ -q -k "even_if_none or falls_back_to_drain_time"   # Expected: 2 failed (KeyError, IndexError)
git -C $E apply /tmp/claude-1000/mut-task33.patch
cd $ROOT && PYTHONPATH=$ROOT $PY -m pytest helao/deploy/<Deployment-E>/servers/oceandirect/tests/ -q   # Expected: all passed
```

- [ ] **Step 6: README**

In `helao/deploy/<Deployment-E>/servers/oceandirect/README.md`:
- Row `dev_ts_ns` (buffered file table): replace "but a packet in which no spectrum carries a stamp omits the key from its line (`driver:1421-1422`)" with "and every buffered line carries it, `null` where the device gave no stamp (`driver:<line of the new dev_timestamps is None check>`)". Keep the rest of the row.
- `## Notes`: delete the bullet "- `build_rows` drops `dev_ts_ns` from a packet in which no spectrum carries a stamp ...". It is the only bullet, so delete the `## Notes` heading too.

Run: `cd $ROOT && PYTHONPATH=$ROOT $PY -m pytest helao/deploy/<Deployment-E>/tests/test_readme_outputs.py -q` — Expected: PASS.

- [ ] **Step 7: Commit (main session; subagents never commit)**

```bash
$BLACK $E/servers/oceandirect/oceandirect_driver.py $E/servers/oceandirect/oceandirect_server.py $E/servers/oceandirect/tests/test_oceandirect_driver.py $E/servers/oceandirect/tests/test_oceandirect_server.py
git -C $E branch --show-current   # expect: main
git -C $E status --short
git -C $E add servers/oceandirect/oceandirect_driver.py servers/oceandirect/oceandirect_server.py servers/oceandirect/tests/test_oceandirect_driver.py servers/oceandirect/tests/test_oceandirect_server.py servers/oceandirect/README.md
git -C $E commit -m "fix(oceandirect): keep dev_ts_ns whenever stamps are passed; guard empty stamp list"
```

---

### Task 34: Full sweeps, review hand-off, station-check rows

**Files:**
- Modify: none (verification only), except the station checklist rows below if the user approves adding them.

**Interfaces:**
- Consumes: every commit from Tasks 1-33.
- Produces: sweep logs under `$D` and the list of station-check rows for the user.

- [ ] **Step 1: Refresh the parent worktree (main session)**

```bash
git -C /tmp/claude-1000/wt-parent checkout --detach unstable
git -C /tmp/claude-1000/wt-parent log --oneline -1
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte log --oneline origin/main..fix/catalog-bugfixes
```
Expected: parent at the Task 5 commit (or later); hte lists the commits of Tasks 1, 6-16.

- [ ] **Step 2: Start the sweeps (main session; each job and its watcher are two separate background commands)**

Sweep dir: `D=${CLAUDE_JOB_DIR:-/tmp/claude-1000}/sweep-catalog-bugfixes` (`mkdir -p "$D"`). One job per tree; each writes a `done` marker whatever its exit code.

Job A (parent core + base + test + hte worktree; the parent worktree holds no private deployments):
```bash
( cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python run_unit_tests.py > "$D/A_unit.log" 2>&1; PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python run_tests.py > "$D/A_run.log" 2>&1; echo $? > "$D/A_done" )
```
Job B (the four private deployments, from the main clone, one filter each, sequential):
```bash
( cd /mnt/STORAGE/repos/helao/helao-async && for X in <Deployment-A> <Deployment-B> <Deployment-C> <Deployment-E>; do PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python run_tests.py --filter "helao/deploy/$X/" > "$D/B_$X.log" 2>&1; done; echo $? > "$D/B_done" )
```
(Resolve each `<Deployment-X>` from `cards-deployment-aliases.md` in the command only; never write the name into a tracked file.)

Job C (PAL golden master script, hte worktree):
```bash
( cd /tmp/claude-1000/wt-parent && PYTHONPATH=/tmp/claude-1000/wt-parent /home/dan/miniforge3/envs/helao/bin/python helao/deploy/hte/tests/test_pal_golden_master.py > "$D/C_pal.log" 2>&1; echo $? > "$D/C_done" )
```
Watcher per job (separate background command; never `pgrep`/`pkill`):
```bash
for i in $(seq 1 720); do [ -f "$D/A_done" ] && break; sleep 15; done; echo "rc=$(cat "$D/A_done" 2>/dev/null || echo TIMEOUT)"; tail -15 "$D/A_run.log"
```
(same with `B_done`/`B_*.log` and `C_done`/`C_pal.log`.)

- [ ] **Step 3: Read the results as soon as each watcher fires**

Expected: `run_unit_tests.py` all pass; every `run_tests.py` file `PASS`, `NOTESTS` or `ENV` (Windows-only vendor SDKs); the PAL script exits 0. The tree's baseline is 0 failures (xdist sweep since 2026-11-10). For any `FAIL`: if the file is one this plan touched, fix it in its task's repo and re-run; otherwise re-run that one file on the unmodified main clone (`cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD $PY -m pytest <file> -q`) and report it as pre-existing only if it fails there too. Check nested-repo WIP of other sessions before blaming a change.

- [ ] **Step 4: Privacy and placeholder scan of the change set**

```bash
NAMES=$(grep -oP '^- \*\*Deployment-[A-F]\*\* = \K[a-z0-9_]+' /home/dan/.claude/projects/-mnt-STORAGE-repos-helao-helao-async/memory/cards-deployment-aliases.md | paste -sd'|')
git -C /tmp/claude-1000/wt-parent/helao/deploy/hte log -p origin/main..HEAD | grep -nwE "$NAMES"
git -C /mnt/STORAGE/repos/helao/helao-async log -p "$(cat /tmp/claude-1000/parent-base.txt)"..unstable | grep -nwE "$NAMES"
```
Expected: no output. The grep is case-sensitive on purpose: uppercase `MEA` is the sample-type domain term and must stay. Then grep each repo's diff for `TODO`, `test.skip`, `pytest.mark.skip`, `.only`: expected none added.

- [ ] **Step 5: Review hand-off**

Dispatch one `reviewer` per unit (U0+U2 hte, U1 parent, U3 Deployment-C, U4 Deployment-B, U5 Deployment-A, U6 Deployment-E) with the unit's diff, the spec section, and this plan's tasks. Tasks 7 and 29 go to the same reviewer, side by side, for motion-timeout parity (exception type, message, busy release). Push nothing; report to the user and wait for approval.

- [ ] **Step 6: Station-check rows (report to the user; add to the station checklist only after approval)**

| row | station | check |
|---|---|---|
| motion timeout raise | one galil station; Deployment-A motion | a manual orchestrated move with a short `timeout`. Expect: the orch pauses and re-queues (no E-STOP); motors halted; the next move accepted; resume re-dispatches cleanly |
| hte analyses port | eche10, wired as in the spec's "Analysis trigger", `local_only: true` | finish one `UVIS_T` and one `ECHEUVIS_multiCA_led` sequence. After sync, the SYNC log shows both dispatches, and ANA writes one analysis per data process with the new `output_type` and plausible `agg_*` |
| UR offsets | Deployment-B robot arm | `robot_mode` matches the pendant, and `is_moving` toggles during a jog for the controller's PolyScope version |
| leak test | Deployment-B station | a mode-5 run writes `leak_test_passed: true` and one final row |
| mfc | ccsi2 or ecms3 | after a forced odd-length reply, a controller still publishes the real `gas` and `setpoint` |
| olecom | EC-Lab Windows host | a real run tracks and uploads `.mps/.mpr/.mpt` |

Also hand the user the Task 17 Step 8 xafs inventory (`/tmp/claude-1000/xafs-inventory.txt`) for the cleanup/re-drop decision.

- [ ] **Step 7: Clean up worktrees only after the user approves the push or abandons the branch**

```bash
git -C /mnt/STORAGE/repos/helao/helao-async/helao/deploy/hte worktree remove /tmp/claude-1000/wt-parent/helao/deploy/hte
git -C /mnt/STORAGE/repos/helao/helao-async worktree remove /tmp/claude-1000/wt-parent
```
The hte branch `fix/catalog-bugfixes` stays in the hte repo; removing the worktree does not delete commits.
