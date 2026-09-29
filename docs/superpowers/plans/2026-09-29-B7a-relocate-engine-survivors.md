# B7a — Relocate the engine survivors: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to carry this plan out task by task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move every symbol that native code still borrows from `helao/core/servers/` (the legacy engine) to one home outside it, leave a re-export behind in the engine, and prove with a two-half ratchet that nothing outside the engine imports it except the three files B7b deletes. Behaviour-neutral: the same functions run, imported from a different path.

**Architecture:** Four files move into `helao/hexagon/app/` (`orch_unpack.py`, `orch_global_params.py`, and two new modules `orch_payloads.py` and `orch_wait.py` cut out of `orch_api.py`). One function (`sanitize_sequence_label`) moves into `orch_queues.py`. Each engine module keeps a `# noqa: F401` re-export. The three golden-master patch seams (`async_action_dispatcher`, `move_dir`, `PLATE_API`) are read at call time from the modules that own them (`helao.helpers.dispatcher`, `helao.helpers.yml_tools`, `helao.hexagon.app.orch_unpack`), and the four tests that patch them move their patches to those modules. Red-checks prove each patch point intercepts. `HelaoFastAPI` stops installing `ActionAPIRoute`; `BaseAPI` and `OrchAPI` install it themselves. A new test, `helao/hexagon/tests/test_engine_import_ratchet.py`, enforces the result.

**Tech Stack:** Python 3.14 (conda env `helao`), FastAPI, pytest (one file per process), `ast`, pyright (basic mode), black.

**Spec:** `docs/superpowers/specs/2026-09-29-B7a-relocate-engine-survivors-design.md` (D-B7a.1–6, §4 destination map, §5 red-check, §6 ratchet, §7 gates, §9 out of scope). Where this plan departs from the spec, it says so in "Spec deviations" below, with the measurement behind the change.

---

## Global Constraints (every task carries these)

- **Worktree:** `/mnt/STORAGE/repos/helao/helao-b7a`, branch `feat/b7a-relocate-engine-survivors`, base commit `415c0bb2`. Never read from or write to `/mnt/STORAGE/repos/helao/helao-async` (the shared checkout). The one exception is the two read-only `cp` sources in Task 0.
- **Scratch:** `/home/dan/.claude/jobs/337df2c4/tmp/b7a/` (written below as `S/`, always typed out in full in commands). All scratch artifacts, logs and captures go there. Do not write anywhere outside the worktree and the scratch directory, except that pytest-created temporary directories are allowed.
- **Git: read-only.** Never run `git add`, `commit`, `push`, `stash`, `checkout`, `reset`, `branch`, `rm`, `mv` or `restore`, in any repo. Always use `git -C /mnt/STORAGE/repos/helao/helao-b7a ...`. Delete or move files with plain `rm`/`cp`. The controller (main thread) runs black and commits; each task ends with a "Controller commits" step that an implementer does **not** run.
- **Python:** only through the wrappers Task 0 creates. `/home/dan/.claude/jobs/337df2c4/tmp/b7a/py <args>` is the helao env interpreter, run from the worktree root with the worktree on `PYTHONPATH`. `/home/dan/.claude/jobs/337df2c4/tmp/b7a/pt <test file> [pytest args]` runs pytest on **one file** with a 600 s cap. Never use `conda run` (it buffers output and drops stdin). Never collect more than one test file per pytest process; the suites hang when collected as one session.
- **Shell:** commands are written to work in both zsh and bash. Do not rewrite them to use unquoted word-splitting variables.
- **Standalone scripts:** files under `helao/core/tests/` named `unit_test_*.py`, plus `test_orch_dispatch_golden_master.py`, are `__main__` scripts. `run_tests.py` does not collect `unit_test_*.py` at all, and reports the golden master as `NOTESTS`. Run them directly with `/home/dan/.claude/jobs/337df2c4/tmp/b7a/py <path>`.
- **Frozen golden-master reference:** never write to `.omc/artifacts/p5/baseline_S0/`. Never re-freeze it.
- **Public repo:** never name a private deployment (anything under `helao/deploy/` other than `hte`, `test`, `hexagon`) in any file or commit message. Say "a private deployment".
- **Escalate, don't choose.** If a command's output differs from the "Expected" given, or the task needs an edit it does not list, stop and report the exact output. Do not improvise a fix, widen the edit, or update an expected value.
- **Edit only the files your task lists.**

---

## Spec deviations and open questions (read before Task 0)

Each item gives the spec's claim, the measurement on `415c0bb2`, and the default this plan takes. The controller should confirm or overrule these before dispatching the task named. All thirteen were reviewed by the controller on 2026-09-29 and are accepted as written; item 6 was put to the user and approved.

1. **The dispatch golden master is already red; "nine of nine PASS" cannot be the gate (§5, §7.2, §10).** On `415c0bb2`, with `baseline_S0/` copied in from the shared checkout, `test_orch_dispatch_golden_master.py --check` prints 7 `PASS` and 2 `DELTA` (`2_every_action_start_condition`, `7_returned_action_error_estop_loop`), rc=1. Two fresh captures are byte-identical to each other, so the drift is deterministic and predates this branch. `docs/superpowers/plans/2026-09-25-runs-layout-and-state-journal.md` §A15 recorded the same two deltas at `658c94dc`. **Default:** the gate becomes "identical to the pre-move state". Task 0 records the `--check` output and a fresh capture of all nine traces on `415c0bb2`. Every later task requires the `--check` output to be byte-identical to that record, and all nine fresh traces to be byte-identical to that capture. The red-check keeps its meaning: with the patch left on the old seam, the run must differ from the reference (measured: it hangs; see item 2). `baseline_S0/` is not touched.
2. **The golden-master red step hangs rather than failing (§5.1).** Measured with the native reads repointed and the test still patching `helao.core.servers.orch`: `--check` printed nothing for more than 10 minutes, because the real `async_action_dispatcher` keeps retrying against `127.0.0.1:8001-8003`. `test_dispatch_lock_not_held_across_post.py` behaves the same way: its first test FAILS, its second hangs, and `timeout 90` gives rc=124. **Default:** every red run is wrapped in `timeout`. The red criterion is rc≠0 (124 or 1) with output that differs from the reference. The red run would POST to anything listening on 8000–8003, so Task 4 first checks that those ports are free.
3. **`gitignore`d inputs are missing from the worktree.** Both `.omc/artifacts/p5/baseline_S0/` and `pyrightconfig.json` are gitignored (`.gitignore:33`, `.gitignore:8`). Without the first, `--check` fails as `FATAL: frozen S0 reference dir missing`. Without the second, pyright runs in its default mode instead of the project's basic mode. **Default:** Task 0 copies both from the shared checkout (read-only source) and checks their sha256.
4. **A fifth test breaks, and the spec did not list it (§2 "Tests that patch", §9, §10 "the 33 test importers run unchanged").** `helao/core/tests/unit_test_orch_unpack.py` assigns `orch_unpack.PLATE_API = SimpleNamespace(...)` on `helao.core.servers.orch_unpack` and then calls `orch_unpack.verify_plate_in_params`. The spec's grep missed it because it uses plain assignment, not `setattr`. Once the engine module becomes a re-export, the function reads `PLATE_API` from its new home. Measured: test 5 ("valid platemap found -> True") fails and the script exits 1. **Default:** Task 3 repoints its import to `helao.hexagon.app.orch_unpack`, after a recorded red run.
5. **The engine `orch_unpack` re-export needs five names, not four (§4).** `orch.py:395` and `orch_host.py:260` call `orch_unpack.seq_unpacker`, which the spec's list leaves out. **Default:** the re-export covers `PLATE_API`, `get_sequence_codehash`, `seq_unpacker`, `unpack_sequence`, `verify_plate_in_params`.
6. **D-B7a.3 adds two pyright errors on `orch.py` (§7.5 "no new errors on every changed file").** `RunLifecycle` is also built by legacy `Orch`, which passes a legacy `Active`. Once `orch_lifecycle.py` annotates `active: "ActionSession"`, pyright reports `Argument of type "Active" cannot be assigned to parameter "active" of type "ActionSession"` at `orch.py:837` and `orch.py:850`. Measured: `orch.py` goes from 14 to 16 errors. **Default:** Task 10 adds `# pyright: ignore[reportArgumentType]` on the argument line of those two delegator calls (black-stable placement, measured back to 14). The alternative, a union annotation, would need `Active` imported under `TYPE_CHECKING`, and the static ratchet bans that. If the controller rejects the default, Task 10 stops before editing `orch.py`. **Resolved 2026-09-29: the user approved the default (suppress on the two legacy lines).**
7. **`run_tests.py` baseline: 3 failing files, not 12 (§7.4).** In this worktree `run_tests.py` sweeps 297 files: PASS 279, ENV 2, NOTESTS 13, FAIL 3. The three failures are `helao/hexagon/tests/test_hte_route_checklist.py`, `harness/tests/test_freeze.py` and `harness/tests/test_hte_checklist.py`. The spec's 12 counts files in private deployments. Those are separate gitignored repositories and are not checked out in a worktree. **Default:** Task 0 re-measures, stores the failing set, and Task 13 compares against it. Adding the ratchet makes the post-B7a sweep 298 files and PASS 280, measured in a dry run.
8. **More checklists drift than `andor` (§7.3 "Every other checklist: 0 diffs").** `harness/tests/test_hte_checklist.py` fails three parametrizations on `415c0bb2`: `andor_server.py-ANDOR` (`/ANDOR/calibrate_wl`…), `biologic_server.py-BIOLOGIC` (`/BIOLOGIC/run_CALIMIT`…) and `nidaqmx_server.py-NI` (`/NI/cancel_toggle_ttl`…). **Default:** gate 3 is "the set of failing checklist test IDs equals the Task 0 set exactly", with all five IDs listed in Task 13.
9. **Launch smoke: SIGTERM rather than CTRL-x, and "finished" may mean `RUNS_SYNCED` (§7.6).** A scripted launch has no terminal. `launch.py` then blocks and documents SIGINT/SIGTERM as the way to stop it. SIGTERM runs `teardown_group()`, the same path CTRL-x takes. The SIM syncer in `goldenhex` may promote a finished sequence past `RUNS_FINISHED` into `RUNS_SYNCED`. The config's root `/home/dan/INST_hlo_hexsmoke` is outside the worktree. **Default:** the controller runs gate 6 itself, and moves any existing root aside rather than deleting it.
10. **The route-class assertion: only `APIRoute`s, and legacy hosts in a separate probe (§8 bullet 4).** "Every `route.__class__`" would include FastAPI's docs and openapi routes (starlette `Route`) and the websocket routes (`APIWebSocketRoute`), which `route_class` never builds. Measured on `ActionHost`: 17 `BoundActionRoute`, 4 `Route`, 3 `APIWebSocketRoute`. Building `BaseAPI`/`OrchAPI` loads the engine, so their check cannot share the "engine-free" subprocess. **Default:** assert on `APIRoute` instances only, and probe the legacy hosts in a second subprocess.
11. **Smaller corrections, no action needed.** `orch_lifecycle.py` has 299 lines. The spec's "annotations (lines 266, 271, 406)" means lines 266 and 271 there, plus `orch_host.py:406`. `domain/global_params.py` differs from the engine copy in its docstring as well as its `LOGGER`. Spec §8's logger note is moot in production, because `fast_launcher.py:92-99` sets `logging.LOGGER` before importing any app module, so every moved module's `LOGGER` is the server's own logger. Where the stem does matter (in tests), it applies to all four `WaitExec` log calls, not only `_poll`.
12. **Out of scope, flagged only.** `helao/hexagon/app/endpoint_manager.py:38` binds `async_action_dispatcher` at import time, from `helao.helpers.dispatcher`. It is not an engine import and no test patches it, so B7a leaves it. It does break D-B7a.2's general rule, so B7b should decide what to do with it.
13. **`test_orch_host_member_coverage.py` is unaffected (measured).** The spec does not mention it. Its `SEARCH_DIRS` lists `helao/core/servers` first, so after the moves it reads the re-exports of `orch_unpack`/`orch_global_params`, and it no longer sees the payload/wait bodies. Measured after every stage of a full dry run, the contract stayed at 137 members with the same sha256 prefix `36e56e44875e5234`: every member those bodies use is used elsewhere too. **Default:** leave that test unchanged, and check the contract hash in each task that moves code. B7b must revisit `SEARCH_DIRS` when it deletes the engine directory.

### Measured: construction-time engine imports on `415c0bb2` (Task 1 re-measures)

Building the native hosts in a fresh interpreter under the `goldenhex` server entries loads the following. Counts: 2 engine modules after import, 14 after `ActionHost(...)`, 17 after `OrchHost(...)`. Each module is shown with its first non-engine importer:

```
helao.core.servers                   <- helao/hexagon/app/orch_host.py:35
helao.core.servers.orch_unpack       <- helao/hexagon/app/orch_host.py:35
helao.core.servers.base_api          <- helao/helpers/server_api.py:71
helao.core.servers.base              <- helao/helpers/server_api.py:71
helao.core.servers.active_data_file  <- helao/helpers/server_api.py:71
helao.core.servers.active_data_stream <- helao/helpers/server_api.py:71
helao.core.servers.active_executor   <- helao/helpers/server_api.py:71
helao.core.servers.active_finalizer  <- helao/helpers/server_api.py:71
helao.core.servers.base_action_queue <- helao/helpers/server_api.py:71
helao.core.servers.base_endpoints    <- helao/helpers/server_api.py:71
helao.core.servers.base_live_buffer  <- helao/helpers/server_api.py:71
helao.core.servers.base_primitives   <- helao/helpers/server_api.py:71
helao.core.servers.base_meta_writer  <- helao/helpers/server_api.py:71
helao.core.servers.base_status       <- helao/helpers/server_api.py:71
helao.core.servers.orch_global_params <- helao/hexagon/app/orch_dispatch.py:121
helao.core.servers.orch_api          <- helao/hexagon/app/orch_host.py:574
helao.core.servers.orch              <- helao/hexagon/app/orch_host.py:574
```

Every root importer is a §2/§4 entry. **Nothing outside §4 was found, so no scope change.** The first-importer view can hide a second importer: `orch_lifecycle.py:44` imports `base` too, but `base` is already loaded by then. The plan's dry run therefore re-measured after each relocation stage. The counts it expects are below, and the ratchet's runtime half reaches 0 only after Task 11.

| after task | runtime engine modules | non-allowlisted static offenders |
|---|---|---|
| 2 (base) | 17 | 8: `server_api`, `action_host`, `endpoint_overlay`, `orch_dispatch`, `orch_estop`, `orch_host`, `orch_lifecycle`, `orch_queues` |
| 3 | 17 | 8 (same) |
| 4 | 17 | 7 (`orch_estop` gone) |
| 5 | 16 | 6 (`orch_dispatch` gone) |
| 6 | 16 | 5 (`orch_queues` gone) |
| 7 | 16 | 5 |
| 8 | 13 | 5 |
| 9 | 13 | 4 (`action_host` gone) |
| 10 | 13 | 1 (`server_api` only) |
| 11 | 0 | 0 |

### Decision: the ratchet is committed `xfail(strict=True)`, then flipped

Task 2 commits the ratchet with its two "at zero" tests marked `@pytest.mark.xfail(strict=True)`. The detector, non-vacuity, shrink-only allowlist and route-class tests are *not* marked; they pass from Task 2 on. Two reasons. A committed red test would put a FAIL line into every intermediate `run_tests.py`, and that line would mask a new failure in the same file (the route-class tests live there). And `strict=True` means the marker cannot outlive the work: the moment both halves reach zero (Task 11), the file fails with `XPASS(strict)` until Task 12 deletes both markers. B7a ends green, with no xfail.

---

## File Structure

| path | action | task | responsibility |
|---|---|---|---|
| `helao/hexagon/tests/test_engine_import_ratchet.py` | create | 2, 12 | static and runtime engine-import ratchet, plus route-class pins |
| `helao/hexagon/app/orch_unpack.py` | create (moved) | 3 | sequence unpacking + `PLATE_API` (the only patch point for it) |
| `helao/core/servers/orch_unpack.py` | rewrite → re-export | 3 | engine shim, B7b deletes |
| `helao/core/tests/unit_test_orch_unpack.py` | modify (import) | 3 | patches `PLATE_API` on its real home |
| `helao/hexagon/app/orch_host.py` | modify | 3, 7, 8, 10 | imports from new homes; `ActionSession` annotation |
| `helao/hexagon/app/orch_dispatch.py` | modify | 4, 5 | seams read at call time; global-params import |
| `helao/hexagon/app/orch_estop.py` | modify | 4 | seams read at call time |
| `helao/hexagon/app/orch_lifecycle.py` | modify | 4, 10 | `yml_tools.move_dir`; `ActionSession` under `TYPE_CHECKING` |
| `helao/core/tests/test_orch_dispatch_golden_master.py` | modify | 4 | patches the three owning modules |
| `helao/core/tests/unit_test_orch_lifecycle.py` | modify | 4 | patches `helao.helpers.yml_tools.move_dir` |
| `helao/hexagon/tests/test_dispatch_lock_not_held_across_post.py` | modify | 4 | patches `helao.helpers.dispatcher` |
| `helao/hexagon/app/orch_global_params.py` | create (moved) | 5 | global-params fold, `helao_logging` LOGGER |
| `helao/core/servers/orch_global_params.py` | rewrite → re-export | 5 | engine shim |
| `helao/hexagon/domain/global_params.py` | delete | 5 | retired duplicate (D-B7a.5) |
| `helao/hexagon/tests/test_global_params.py` | modify | 5 | tests the app module |
| `helao/hexagon/app/orch_queues.py` | modify | 6 | owns `sanitize_sequence_label` |
| `helao/core/servers/orch.py` | modify | 6, 10 | re-exports `sanitize_sequence_label`; two pyright ignores |
| `helao/core/tests/test_standalone_operator.py` | modify (1 line) | 6 | imports from `orch_queues` |
| `helao/hexagon/app/orch_payloads.py` | create | 7 | seven payload builders |
| `helao/hexagon/app/orch_wait.py` | create | 8 | `WaitExec`, `checkcond` |
| `helao/core/servers/orch_api.py` | modify | 7, 8, 11 | re-exports; installs `ActionAPIRoute` |
| `helao/hexagon/app/action_host.py` | modify | 9, 11 | `guarded_replace` import; docstring/comment |
| `helao/hexagon/app/endpoint_overlay.py` | modify | 10 | `ActionHost` annotation under `TYPE_CHECKING` |
| `helao/helpers/server_api.py` | modify | 11 | no longer installs a route class |
| `helao/core/servers/base_api.py` | modify | 11 | `BaseAPI` installs `ActionAPIRoute` |

---

### Task 0: Scratch setup, gitignored inputs, and baselines on `415c0bb2`

**Files:** none tracked. Creates files under `/home/dan/.claude/jobs/337df2c4/tmp/b7a/`, plus two gitignored inputs in the worktree (`.omc/artifacts/p5/baseline_S0/`, `pyrightconfig.json`).

**Interfaces:**
- Consumes: nothing.
- Produces: the wrappers `py`, `pt`, `gm_gate.sh`, `unit_sweep.sh`; the helpers `gm_capture.py`, `progress.py`, `contract.py`, `verify_moved.py`, `pyright_cmp.py`; the pyright file lists; and the reference artifacts `gm_check_before.txt`, `gm_default_before.txt`, `gm_ref/`, `unit_before.txt`, `pyright_before.json`, `run_tests_before.txt`, `fail_before.txt`, `contract_before.txt`. Every later task consumes these.

- [ ] **Step 0.1: Confirm the starting point.**

```
git -C /mnt/STORAGE/repos/helao/helao-b7a rev-parse HEAD
git -C /mnt/STORAGE/repos/helao/helao-b7a status --porcelain
git -C /mnt/STORAGE/repos/helao/helao-b7a branch --show-current
```
Expected: `415c0bb2a76ef723d6a8906afa77ca2c4891759b`, then no output (clean tree), then `feat/b7a-relocate-engine-survivors`. If HEAD differs or the tree is dirty, STOP.

- [ ] **Step 0.2: Create the scratch directory and copy the two gitignored inputs.**

```
mkdir -p /home/dan/.claude/jobs/337df2c4/tmp/b7a
mkdir -p /mnt/STORAGE/repos/helao/helao-b7a/.omc/artifacts/p5
cp -r /mnt/STORAGE/repos/helao/helao-async/.omc/artifacts/p5/baseline_S0 /mnt/STORAGE/repos/helao/helao-b7a/.omc/artifacts/p5/
cp /mnt/STORAGE/repos/helao/helao-async/pyrightconfig.json /mnt/STORAGE/repos/helao/helao-b7a/pyrightconfig.json
cd /mnt/STORAGE/repos/helao/helao-async/.omc/artifacts/p5/baseline_S0 && sha256sum *.jsonl > /home/dan/.claude/jobs/337df2c4/tmp/b7a/baseline_S0.sha256
cd /mnt/STORAGE/repos/helao/helao-b7a/.omc/artifacts/p5/baseline_S0 && sha256sum -c /home/dan/.claude/jobs/337df2c4/tmp/b7a/baseline_S0.sha256
git -C /mnt/STORAGE/repos/helao/helao-b7a status --porcelain
```
Expected: nine lines ending `: OK`, then no output from `git status` (both inputs are ignored).

- [ ] **Step 0.3: Write the two wrappers.** Create `/home/dan/.claude/jobs/337df2c4/tmp/b7a/py`:

```bash
#!/bin/bash
# B7a: the helao env python, run from the worktree root with the worktree on PYTHONPATH.
cd /mnt/STORAGE/repos/helao/helao-b7a || exit 2
export PYTHONPATH=/mnt/STORAGE/repos/helao/helao-b7a
export PATH=/home/dan/miniforge3/envs/helao/bin:$PATH
exec /home/dan/miniforge3/envs/helao/bin/python "$@"
```

Create `/home/dan/.claude/jobs/337df2c4/tmp/b7a/pt`:

```bash
#!/bin/bash
# B7a: pytest on ONE file (the suites hang when collected as one session); 600 s cap.
cd /mnt/STORAGE/repos/helao/helao-b7a || exit 2
export PYTHONPATH=/mnt/STORAGE/repos/helao/helao-b7a
export PATH=/home/dan/miniforge3/envs/helao/bin:$PATH
exec timeout 600 /home/dan/miniforge3/envs/helao/bin/python -m pytest -q -p no:cacheprovider --color=no "$@"
```

Then:
```
chmod +x /home/dan/.claude/jobs/337df2c4/tmp/b7a/py /home/dan/.claude/jobs/337df2c4/tmp/b7a/pt
/home/dan/.claude/jobs/337df2c4/tmp/b7a/py -c "import sys, helao; print(sys.version.split()[0], helao.__file__)"
```
Expected: `3.14.6 /mnt/STORAGE/repos/helao/helao-b7a/helao/__init__.py` (the patch version may differ; the path must be the worktree's).

- [ ] **Step 0.4: Write the golden-master tools.** Create `/home/dan/.claude/jobs/337df2c4/tmp/b7a/gm_capture.py`:

```python
"""Capture the nine dispatch golden-master traces into a new directory (B7a scratch tool).

Usage: py gm_capture.py <out_dir>

Imports the worktree's harness by path and runs its run_all_scenarios() into
<out_dir>. The harness itself refuses to write into baseline_S0/.
"""

import asyncio
import importlib.util
import sys
import tempfile
from pathlib import Path

HARNESS = Path(
    "/mnt/STORAGE/repos/helao/helao-b7a/helao/core/tests/test_orch_dispatch_golden_master.py"
)
out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=False)
spec = importlib.util.spec_from_file_location("gm_harness", HARNESS)
gm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gm)
with tempfile.TemporaryDirectory() as tmp_root:
    asyncio.run(gm.run_all_scenarios(out, Path(tmp_root)))
print(f"captured {len(list(out.glob('*.jsonl')))} traces into {out}")
```

Create `/home/dan/.claude/jobs/337df2c4/tmp/b7a/gm_gate.sh`:

```bash
#!/bin/bash
# B7a golden-master gate. Usage: gm_gate.sh <tag>
# Exit 0 only if the --check output AND all nine fresh traces are byte-identical
# to the Task 0 record. (--check itself exits 1 before and after B7a: S2 and S7
# already DELTA against baseline_S0 on 415c0bb2.)
S=/home/dan/.claude/jobs/337df2c4/tmp/b7a
tag="$1"
[ -n "$tag" ] || { echo "usage: gm_gate.sh <tag>"; exit 2; }
rm -rf "$S/gm_$tag"
timeout 600 "$S/py" helao/core/tests/test_orch_dispatch_golden_master.py --check > "$S/gm_check_$tag.txt" 2>/dev/null
echo "check rc=$? (reference rc=1)"
timeout 600 "$S/py" "$S/gm_capture.py" "$S/gm_$tag" > /dev/null 2>&1 || { echo "GM-GATE FAIL $tag: capture errored or timed out"; exit 1; }
fail=0
diff "$S/gm_check_before.txt" "$S/gm_check_$tag.txt" || { echo "check output differs from Task 0"; fail=1; }
diff -r "$S/gm_ref" "$S/gm_$tag" || { echo "traces differ from Task 0"; fail=1; }
if [ $fail -eq 0 ]; then echo "GM-GATE PASS $tag"; else echo "GM-GATE FAIL $tag"; fi
exit $fail
```

```
chmod +x /home/dan/.claude/jobs/337df2c4/tmp/b7a/gm_gate.sh
```

- [ ] **Step 0.5: Record the golden master on `415c0bb2`.**

```
timeout 600 /home/dan/.claude/jobs/337df2c4/tmp/b7a/py helao/core/tests/test_orch_dispatch_golden_master.py --check > /home/dan/.claude/jobs/337df2c4/tmp/b7a/gm_check_before.txt 2>/dev/null; echo rc=$?
cat /home/dan/.claude/jobs/337df2c4/tmp/b7a/gm_check_before.txt
timeout 600 /home/dan/.claude/jobs/337df2c4/tmp/b7a/py helao/core/tests/test_orch_dispatch_golden_master.py > /home/dan/.claude/jobs/337df2c4/tmp/b7a/gm_default_before.txt 2>/dev/null; echo rc=$?
tail -2 /home/dan/.claude/jobs/337df2c4/tmp/b7a/gm_default_before.txt
timeout 600 /home/dan/.claude/jobs/337df2c4/tmp/b7a/py /home/dan/.claude/jobs/337df2c4/tmp/b7a/gm_capture.py /home/dan/.claude/jobs/337df2c4/tmp/b7a/gm_ref
timeout 600 /home/dan/.claude/jobs/337df2c4/tmp/b7a/py /home/dan/.claude/jobs/337df2c4/tmp/b7a/gm_capture.py /home/dan/.claude/jobs/337df2c4/tmp/b7a/gm_ref2
diff -r /home/dan/.claude/jobs/337df2c4/tmp/b7a/gm_ref /home/dan/.claude/jobs/337df2c4/tmp/b7a/gm_ref2 && echo DETERMINISTIC
```
Expected: `rc=1`; `gm_check_before.txt` holds exactly these 10 lines:
```
  PASS   1_plain_two_experiment_sequence_no_wait
  DELTA  2_every_action_start_condition: byte diff vs /mnt/STORAGE/repos/helao/helao-b7a/.omc/artifacts/p5/baseline_S0/2_every_action_start_condition.jsonl
  PASS   3_to_global_params_list_and_dict_fold_in
  PASS   4_loop_intent_stop_pending_requeue
  PASS   5_loop_intent_skip
  PASS   6_dispatch_failure_pause_requeue
  DELTA  7_returned_action_error_estop_loop: byte diff vs /mnt/STORAGE/repos/helao/helao-b7a/.omc/artifacts/p5/baseline_S0/7_returned_action_error_estop_loop.jsonl
  PASS   8_nonblocking_action_lifecycle
  PASS   9_step_thru_flags
CHECK FAILED: trace diverged from frozen reference (/mnt/STORAGE/repos/helao/helao-b7a/.omc/artifacts/p5/baseline_S0)
```
then `rc=0` with the tail `DETERMINISM CHECK PASSED: two capture runs byte-identical for all 9 scenarios` / `ALL GOLDEN-MASTER HARNESS CHECKS PASSED`; then `captured 9 traces into …/gm_ref` and `…/gm_ref2`; then `DETERMINISTIC`. The default mode writes scratch traces under the gitignored `.omc/artifacts/p5/baseline/`, which is expected.

- [ ] **Step 0.6: Record the standalone `unit_test_*.py` scripts.** Create `/home/dan/.claude/jobs/337df2c4/tmp/b7a/unit_sweep.sh`:

```bash
#!/bin/bash
# B7a: run every helao/core/tests/unit_test_*.py as a script; one "rc path" line each.
# Usage: unit_sweep.sh <out_file>
S=/home/dan/.claude/jobs/337df2c4/tmp/b7a
cd /mnt/STORAGE/repos/helao/helao-b7a || exit 2
: > "$1"
for f in $(/bin/ls helao/core/tests/unit_test_*.py | sort); do
  timeout 300 "$S/py" "$f" > /dev/null 2>&1
  echo "$? $f" >> "$1"
done
```

```
chmod +x /home/dan/.claude/jobs/337df2c4/tmp/b7a/unit_sweep.sh
/home/dan/.claude/jobs/337df2c4/tmp/b7a/unit_sweep.sh /home/dan/.claude/jobs/337df2c4/tmp/b7a/unit_before.txt
wc -l < /home/dan/.claude/jobs/337df2c4/tmp/b7a/unit_before.txt
grep -v '^0 ' /home/dan/.claude/jobs/337df2c4/tmp/b7a/unit_before.txt
```
Expected: `40`, then exactly one line, `1 helao/core/tests/unit_test_status_transitions.py`. That script needs the gitignored `.omc/artifacts/p3a/schema_baseline.json` and is red on `unstable` too; B7a neither copies nor fixes it.

- [ ] **Step 0.7: Record pyright.** Create `/home/dan/.claude/jobs/337df2c4/tmp/b7a/pyright_files_before.txt` (19 lines, exactly):

```
helao/core/servers/base_api.py
helao/core/servers/orch.py
helao/core/servers/orch_api.py
helao/core/servers/orch_global_params.py
helao/core/servers/orch_unpack.py
helao/helpers/server_api.py
helao/hexagon/app/action_host.py
helao/hexagon/app/endpoint_overlay.py
helao/hexagon/app/orch_dispatch.py
helao/hexagon/app/orch_estop.py
helao/hexagon/app/orch_host.py
helao/hexagon/app/orch_lifecycle.py
helao/hexagon/app/orch_queues.py
helao/core/tests/test_orch_dispatch_golden_master.py
helao/core/tests/test_standalone_operator.py
helao/core/tests/unit_test_orch_lifecycle.py
helao/core/tests/unit_test_orch_unpack.py
helao/hexagon/tests/test_dispatch_lock_not_held_across_post.py
helao/hexagon/tests/test_global_params.py
```

Create `/home/dan/.claude/jobs/337df2c4/tmp/b7a/pyright_files_after.txt`: the same 19 lines followed by these 5 (24 lines):

```
helao/hexagon/app/orch_global_params.py
helao/hexagon/app/orch_payloads.py
helao/hexagon/app/orch_unpack.py
helao/hexagon/app/orch_wait.py
helao/hexagon/tests/test_engine_import_ratchet.py
```

Create `/home/dan/.claude/jobs/337df2c4/tmp/b7a/pyright_cmp.py`:

```python
"""B7a: fail if any file has more pyright errors than on 415c0bb2, or if pyright analyzed the wrong number of files.

Usage: py pyright_cmp.py <before.json> <after.json> <expected files analyzed in after>
A worktree can make pyright analyze 0 files and "pass"; the count check stops that.
"""

import json
import sys

before = json.load(open(sys.argv[1], encoding="utf-8"))
after = json.load(open(sys.argv[2], encoding="utf-8"))
expected = int(sys.argv[3])


def per_file(doc):
    counts = {}
    for diag in doc["generalDiagnostics"]:
        if diag["severity"] == "error":
            rel = diag["file"].split("/helao-b7a/", 1)[1]
            counts[rel] = counts.get(rel, 0) + 1
    return counts


analyzed = after["summary"]["filesAnalyzed"]
assert analyzed == expected, f"pyright analyzed {analyzed} files, expected {expected}"
b, a = per_file(before), per_file(after)
worse = {rel: (b.get(rel, 0), n) for rel, n in sorted(a.items()) if n > b.get(rel, 0)}
print(f"errors before={before['summary']['errorCount']} after={after['summary']['errorCount']}")
print(f"files with more errors than on 415c0bb2: {worse}")
sys.exit(1 if worse else 0)
```

Record the baseline:
```
cd /mnt/STORAGE/repos/helao/helao-b7a && xargs -a /home/dan/.claude/jobs/337df2c4/tmp/b7a/pyright_files_before.txt pyright --outputjson > /home/dan/.claude/jobs/337df2c4/tmp/b7a/pyright_before.json; echo rc=$?
/home/dan/.claude/jobs/337df2c4/tmp/b7a/py -c "import json; d = json.load(open('/home/dan/.claude/jobs/337df2c4/tmp/b7a/pyright_before.json')); print(d['summary']['filesAnalyzed'], d['summary']['errorCount'])"
```
Expected: `rc=1` (pyright exits 1 when any error exists), then `19 169`. If the first number is not 19, STOP: pyright did not pick up `pyrightconfig.json`.

- [ ] **Step 0.8: Write the progress, contract and move-verification helpers.** Create `/home/dan/.claude/jobs/337df2c4/tmp/b7a/progress.py`:

```python
"""B7a progress: non-allowlisted static offenders, and engine modules loaded by building the native hosts."""

from helao.hexagon.tests.test_engine_import_ratchet import ALLOWLIST, _probe, offenders

static = sorted(set(offenders()) - ALLOWLIST)
runtime = _probe("native")["engine_modules"]
print(f"static offenders ({len(static)}): {static}")
print(f"runtime engine modules: {len(runtime)}")
```

Create `/home/dan/.claude/jobs/337df2c4/tmp/b7a/contract.py`:

```python
"""B7a: size and hash of the OrchHost member contract (test_orch_host_member_coverage)."""

import hashlib

from helao.hexagon.tests.test_orch_host_member_coverage import orch_contract

members = orch_contract()
digest = hashlib.sha256(" ".join(sorted(members)).encode()).hexdigest()[:16]
print(len(members), digest)
```

Create `/home/dan/.claude/jobs/337df2c4/tmp/b7a/verify_moved.py`:

```python
"""B7a: prove moved top-level definitions are verbatim copies of their 415c0bb2 source.

Usage: py verify_moved.py <old path at 415c0bb2> <new path in worktree> <name> [<name> ...]
Compares ast.get_source_segment text of each named def/class, byte for byte.
"""

import ast
import subprocess
import sys

W = "/mnt/STORAGE/repos/helao/helao-b7a"
old_rel, new_rel, names = sys.argv[1], sys.argv[2], sys.argv[3:]
old_src = subprocess.run(
    ["git", "-C", W, "show", f"415c0bb2:{old_rel}"],
    capture_output=True,
    text=True,
    check=True,
).stdout
new_src = open(f"{W}/{new_rel}", encoding="utf-8").read()


def segments(src):
    kinds = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    return {
        n.name: ast.get_source_segment(src, n)
        for n in ast.parse(src).body
        if isinstance(n, kinds)
    }


old, new = segments(old_src), segments(new_src)
bad = [n for n in names if n not in old or n not in new or old[n] != new[n]]
print("verbatim:", [n for n in names if n not in bad])
print("DIFFERENT OR MISSING:", bad)
sys.exit(1 if bad else 0)
```

```
/home/dan/.claude/jobs/337df2c4/tmp/b7a/py /home/dan/.claude/jobs/337df2c4/tmp/b7a/contract.py 2>/dev/null | tee /home/dan/.claude/jobs/337df2c4/tmp/b7a/contract_before.txt
```
Expected: `137 36e56e44875e5234`. (`progress.py` needs the ratchet file and is first run in Task 2.)

- [ ] **Step 0.9: Record the full `run_tests.py` sweep (~7 minutes).**

```
cd /mnt/STORAGE/repos/helao/helao-b7a && timeout 5400 /home/dan/.claude/jobs/337df2c4/tmp/b7a/py run_tests.py > /home/dan/.claude/jobs/337df2c4/tmp/b7a/run_tests_before.txt 2>&1; echo rc=$?
tail -12 /home/dan/.claude/jobs/337df2c4/tmp/b7a/run_tests_before.txt
grep -E '^  (FAIL|TIMEOUT) ' /home/dan/.claude/jobs/337df2c4/tmp/b7a/run_tests_before.txt | awk '{print $2}' | sort > /home/dan/.claude/jobs/337df2c4/tmp/b7a/fail_before.txt
cat /home/dan/.claude/jobs/337df2c4/tmp/b7a/fail_before.txt
```
Expected: `rc=1`; the summary reads `===== 297 files`, `PASS 279`, `ENV 2`, `NOTESTS 13`, `FAIL 3`; `fail_before.txt` holds exactly:
```
harness/tests/test_freeze.py
harness/tests/test_hte_checklist.py
helao/hexagon/tests/test_hte_route_checklist.py
```
If the set differs, STOP and report it: the baseline is whatever this step measures, but the controller must see it before any task compares against it.

- [ ] **Step 0.10: Nothing to commit.** Task 0 changes no tracked file. `git -C /mnt/STORAGE/repos/helao/helao-b7a status --porcelain` prints nothing.

---

### Task 1: Measure the construction-time engine imports

**Files:** none tracked. Creates `/home/dan/.claude/jobs/337df2c4/tmp/b7a/measure_engine_imports.py` and `measure_before.txt`.

**Interfaces:**
- Consumes: `S/py` (Task 0).
- Produces: `S/measure_before.txt`, the list the move clusters are checked against.

- [ ] **Step 1.1: Write the measurement script.** Create `/home/dan/.claude/jobs/337df2c4/tmp/b7a/measure_engine_imports.py`:

```python
"""B7a Task 1: which helao.core.servers modules does building the native hosts load, and who imports each?

Run with the worktree as cwd and on PYTHONPATH. Prints the engine-module count
after importing the hosts, after ActionHost(...), after OrchHost(...), then one
line per engine module: '<module> <- <first non-engine importer file>:<line>'.
"""

import importlib.abc
import sys
import tempfile
import traceback

import yaml

ROOT = "/mnt/STORAGE/repos/helao/helao-b7a/"
ENGINE_DIR = ROOT + "helao/core/servers/"
SCRATCH = "/home/dan/.claude/jobs/337df2c4/tmp/b7a"
first_importer = {}


class _Spy(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        is_engine = name == "helao.core.servers" or name.startswith(
            "helao.core.servers."
        )
        if is_engine and name not in first_importer:
            frames = [
                f
                for f in traceback.extract_stack()[:-1]
                if f.filename.startswith(ROOT) and not f.filename.startswith(ENGINE_DIR)
            ]
            f = frames[-1]
            first_importer[name] = f"{f.filename[len(ROOT):]}:{f.lineno}"
        return None


sys.meta_path.insert(0, _Spy())
from helao.helpers import config_loader  # noqa: E402

cfg = yaml.safe_load(
    open(ROOT + "helao/deploy/test/configs/goldenhex.yml", encoding="utf-8")
)
cfg["root"] = tempfile.mkdtemp(prefix="b7a_measure_", dir=SCRATCH)
config_loader.CONFIG = cfg
for phase in ("import", "ActionHost", "OrchHost"):
    if phase == "import":
        from helao.hexagon.app.action_host import ActionHost
        from helao.hexagon.app.orch_host import OrchHost
    elif phase == "ActionHost":
        ActionHost("SIM", "SIM", "measure", 1.0, helao_cfg=cfg)
    else:
        OrchHost("ORCH", "ORCH", "measure", version=3.0, helao_cfg=cfg)
    loaded = [
        m
        for m in sys.modules
        if m == "helao.core.servers" or m.startswith("helao.core.servers.")
    ]
    print(f"after {phase}: {len(loaded)} engine modules")
for name, where in first_importer.items():
    print(f"  {name} <- {where}")
```

- [ ] **Step 1.2: Run it.**

```
timeout 180 /home/dan/.claude/jobs/337df2c4/tmp/b7a/py -u /home/dan/.claude/jobs/337df2c4/tmp/b7a/measure_engine_imports.py 2>/dev/null | grep -E '^after|^  helao' > /home/dan/.claude/jobs/337df2c4/tmp/b7a/measure_before.txt
cat /home/dan/.claude/jobs/337df2c4/tmp/b7a/measure_before.txt
```
Expected, exactly:
```
after import: 2 engine modules
after ActionHost: 14 engine modules
after OrchHost: 17 engine modules
  helao.core.servers <- helao/hexagon/app/orch_host.py:35
  helao.core.servers.orch_unpack <- helao/hexagon/app/orch_host.py:35
  helao.core.servers.base_api <- helao/helpers/server_api.py:71
  helao.core.servers.base <- helao/helpers/server_api.py:71
  helao.core.servers.active_data_file <- helao/helpers/server_api.py:71
  helao.core.servers.active_data_stream <- helao/helpers/server_api.py:71
  helao.core.servers.active_executor <- helao/helpers/server_api.py:71
  helao.core.servers.active_finalizer <- helao/helpers/server_api.py:71
  helao.core.servers.base_action_queue <- helao/helpers/server_api.py:71
  helao.core.servers.base_endpoints <- helao/helpers/server_api.py:71
  helao.core.servers.base_live_buffer <- helao/helpers/server_api.py:71
  helao.core.servers.base_primitives <- helao/helpers/server_api.py:71
  helao.core.servers.base_meta_writer <- helao/helpers/server_api.py:71
  helao.core.servers.base_status <- helao/helpers/server_api.py:71
  helao.core.servers.orch_global_params <- helao/hexagon/app/orch_dispatch.py:121
  helao.core.servers.orch_api <- helao/hexagon/app/orch_host.py:574
  helao.core.servers.orch <- helao/hexagon/app/orch_host.py:574
```

- [ ] **Step 1.3: Apply the STOP rule.** Every importer on the right-hand side must be one of `helao/helpers/server_api.py`, `helao/hexagon/app/orch_host.py`, `helao/hexagon/app/orch_dispatch.py`, `helao/hexagon/app/orch_lifecycle.py`, `helao/hexagon/app/orch_estop.py`, `helao/hexagon/app/orch_queues.py`, `helao/hexagon/app/action_host.py`, `helao/hexagon/app/endpoint_overlay.py`. If any other file appears, **STOP and escalate**, naming the file and line. That importer is not in spec §4, and the spec requires it be added to the map (not to the allowlist) before anything moves. Do not extend scope yourself.

- [ ] **Step 1.4: Nothing to commit.**

---

### Task 2: The ratchet, committed red under `xfail(strict=True)`

**Files:**
- Create: `helao/hexagon/tests/test_engine_import_ratchet.py`

**Interfaces:**
- Consumes: `S/py`, `S/pt`.
- Produces: `ALLOWLIST`, `swept_files()`, `engine_imports(source, rel)`, `offenders()`, `_probe(mode)` ("native" | "legacy") → `{"engine_modules": [...], "hosts": {name: {"installed", "api_routes", "wrong_class"}}}`. `S/progress.py` and Tasks 3–13 import these.

- [ ] **Step 2.1: Write the test file.** Create `helao/hexagon/tests/test_engine_import_ratchet.py` with exactly:

````python
"""Nothing outside the legacy engine imports it (B7a, spec section 6).

``helao/core/servers/`` is the engine B7b deletes. B7a moved every symbol
native code still borrowed from it to one home outside it; this ratchet keeps
it that way and is the first test B7b runs.

Static half. Every tracked ``.py`` outside the engine and outside tests is
parsed, and any ``import``/``from`` that names ``helao.core.servers`` -- at
module top, in a function body, or under ``TYPE_CHECKING`` -- is an offender.
Three files may keep importing it, and only until B7b deletes them: the graft
machinery and the harness encoder that produces the legacy bytes the parity
tests compare against. The allowlist is shrink-only: an entry that stops
importing the engine fails, so B7b cannot leave a stale one behind.

Runtime half. A fresh interpreter constructs an ``ActionHost`` and an
``OrchHost`` under the ``goldenhex`` server entries and must end with no
``helao.core.servers`` module loaded. A subprocess, because this pytest
process may already hold the engine through other imports. On 415c0bb2 the
import-time count was 2 and the construction-time count 17: a helper that
imports the engine lazily is an importer even when no static read of the
hosts finds it.

The route-class tests pin D-B7a.4. ``HelaoFastAPI`` no longer installs
``ActionAPIRoute``, so each host installs its own route class before its first
route, and every ``APIRoute`` a host holds must be of that class. A route
registered before the install would be a plain ``APIRoute`` and would lose its
action wrapping without any other test noticing.
"""

import ast
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
ENGINE: Final[str] = "helao.core.servers"
CONFIG: Final[Path] = REPO_ROOT / "helao/deploy/test/configs/goldenhex.yml"

#: B7b's files, and nothing else: B7b deletes the graft (active_graft.py,
#: factory.py's makeOrchApp) and re-baselines the harness (ws_frames.py).
ALLOWLIST: Final[frozenset[str]] = frozenset(
    {
        "harness/ws_frames.py",
        "helao/hexagon/app/active_graft.py",
        "helao/hexagon/app/factory.py",
    }
)


def _is_engine(name: str) -> bool:
    return name == ENGINE or name.startswith(ENGINE + ".")


def _is_test_file(rel: str) -> bool:
    parts = rel.split("/")
    return "tests" in parts[:-1] or parts[-1].startswith(("test_", "unit_test_"))


def swept_files() -> list[str]:
    """Tracked ``.py`` files outside the engine and outside tests."""
    out = subprocess.run(
        ["git", "ls-files", "-z", "*.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sorted(
        rel
        for rel in out.split("\0")
        if rel and not rel.startswith("helao/core/servers/") and not _is_test_file(rel)
        # Tracked but deleted in the working tree and not yet committed.
        and (REPO_ROOT / rel).exists()
    )


def engine_imports(source: str, rel: str) -> list[str]:
    """``rel:lineno`` of every import in ``source`` that names the engine.

    Relative imports are resolved against ``rel``'s package, and
    ``from helao.core import servers`` counts, so neither spelling hides one.
    """
    package = rel[: -len(".py")].split("/")[:-1]
    found = []
    for node in ast.walk(ast.parse(source, filename=rel)):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - (node.level - 1)]
                module = ".".join(base + ([node.module] if node.module else []))
            else:
                module = node.module or ""
            names = [module] + [f"{module}.{alias.name}" for alias in node.names]
        else:
            continue
        if any(_is_engine(name) for name in names):
            found.append(f"{rel}:{node.lineno}")
    return found


def offenders() -> dict[str, list[str]]:
    """``{file: [site, ...]}`` for every swept file that imports the engine."""
    result = {}
    for rel in swept_files():
        sites = engine_imports((REPO_ROOT / rel).read_text(encoding="utf-8"), rel)
        if sites:
            result[rel] = sites
    return result


def test_the_detector_sees_every_spelling() -> None:
    """A detector that misses a spelling makes the sweep pass for free."""
    rel = "helao/hexagon/app/x.py"
    for source in (
        "import helao.core.servers.orch",
        "from helao.core.servers.orch import move_dir",
        "from helao.core.servers import orch_unpack",
        "from helao.core import servers",
        "def f():\n    from helao.core.servers.base import Active",
        "if TYPE_CHECKING:\n    from helao.core.servers.base import Active",
    ):
        assert engine_imports(source, rel), f"missed: {source!r}"
    assert engine_imports("from ...core.servers import orch", rel)
    assert not engine_imports("from helao.core.models import status_transitions", rel)
    assert not engine_imports("import helao.core.serversx", rel)


def test_the_sweep_is_not_vacuous() -> None:
    files = swept_files()
    assert len(files) > 500, f"swept only {len(files)} files"


def test_every_allowlisted_file_still_imports_the_engine() -> None:
    """Shrink-only: an entry whose file stopped importing the engine is stale."""
    found = offenders()
    stale = sorted(rel for rel in ALLOWLIST if rel not in found)
    assert (
        stale == []
    ), f"delete these from ALLOWLIST, they no longer import it: {stale}"


@pytest.mark.xfail(strict=True, reason="B7a in progress; Task 12 deletes this marker")
def test_nothing_outside_the_engine_imports_it() -> None:
    extra = {rel: sites for rel, sites in offenders().items() if rel not in ALLOWLIST}
    assert extra == {}, f"engine imports outside helao/core/servers/: {extra}"


_PROBE: Final[str] = r"""
import json, sys, tempfile
import yaml
from fastapi.routing import APIRoute
from helao.helpers import config_loader

cfg = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
cfg["root"] = tempfile.mkdtemp(prefix="b7a_ratchet_")
config_loader.CONFIG = cfg
if sys.argv[2] == "native":
    from helao.hexagon.app.action_host import ActionHost
    from helao.hexagon.app.orch_host import OrchHost

    hosts = {
        "ActionHost": ActionHost("SIM", "SIM", "ratchet", 1.0, helao_cfg=cfg),
        "OrchHost": OrchHost("ORCH", "ORCH", "ratchet", version=3.0, helao_cfg=cfg),
    }
else:
    from helao.core.servers.base_api import BaseAPI
    from helao.core.servers.orch_api import OrchAPI

    hosts = {
        "BaseAPI": BaseAPI("SIM", "SIM", "ratchet", 1.0),
        "OrchAPI": OrchAPI("ORCH", "ORCH", "ratchet", 3.0),
    }
report = {
    "engine_modules": sorted(
        m for m in sys.modules
        if m == "helao.core.servers" or m.startswith("helao.core.servers.")
    ),
    "hosts": {},
}
for name, host in hosts.items():
    installed = host.router.route_class
    api_routes = [r for r in host.routes if isinstance(r, APIRoute)]
    report["hosts"][name] = {
        "installed": installed.__module__ + "." + installed.__name__,
        "api_routes": len(api_routes),
        "wrong_class": sorted(r.path for r in api_routes if type(r) is not installed),
    }
print("B7A-PROBE " + json.dumps(report))
"""


def _probe(mode: str) -> dict:
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE, str(CONFIG), mode],
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        capture_output=True,
        text=True,
        timeout=180,
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("B7A-PROBE ")]
    assert (
        proc.returncode == 0 and len(lines) == 1
    ), f"{mode} probe failed (rc={proc.returncode}):\n{proc.stderr[-4000:]}"
    return json.loads(lines[0][len("B7A-PROBE ") :])


@pytest.fixture(scope="module")
def native() -> dict:
    return _probe("native")


@pytest.fixture(scope="module")
def legacy() -> dict:
    return _probe("legacy")


@pytest.mark.xfail(strict=True, reason="B7a in progress; Task 12 deletes this marker")
def test_the_native_hosts_construct_without_the_engine(native) -> None:
    assert native["engine_modules"] == []


def test_every_native_route_is_built_by_the_host_bound_class(native) -> None:
    for name, host in native["hosts"].items():
        assert host["installed"] == "helao.hexagon.app.action_route.BoundActionRoute", (
            name,
            host["installed"],
        )
        assert host["api_routes"] > 0 and host["wrong_class"] == [], (name, host)


def test_every_legacy_route_is_built_by_action_api_route(legacy) -> None:
    for name, host in legacy["hosts"].items():
        assert host["installed"] == "helao.core.servers.base_api.ActionAPIRoute", (
            name,
            host["installed"],
        )
        assert host["api_routes"] > 0 and host["wrong_class"] == [], (name, host)
````

- [ ] **Step 2.2: Run it. The committed state is xfail.**

```
/home/dan/.claude/jobs/337df2c4/tmp/b7a/pt helao/hexagon/tests/test_engine_import_ratchet.py -rxX 2>&1 | tail -4
```
Expected: two `XFAIL` lines (`test_nothing_outside_the_engine_imports_it`, `test_the_native_hosts_construct_without_the_engine`) and `5 passed, 2 xfailed`.

- [ ] **Step 2.3: Show and record the red.**

```
/home/dan/.claude/jobs/337df2c4/tmp/b7a/pt helao/hexagon/tests/test_engine_import_ratchet.py --runxfail > /home/dan/.claude/jobs/337df2c4/tmp/b7a/ratchet_red.txt 2>&1; echo rc=$?
grep -E "^E       AssertionError|passed|failed" /home/dan/.claude/jobs/337df2c4/tmp/b7a/ratchet_red.txt | cut -c1-160
/home/dan/.claude/jobs/337df2c4/tmp/b7a/py /home/dan/.claude/jobs/337df2c4/tmp/b7a/progress.py 2>/dev/null
```
Expected: `rc=1`. The first assertion line starts `E       AssertionError: engine imports outside helao/core/servers/: {'helao/helpers/server_api.py': ['helao/helpers/server_api.py:71'], 'helao/hexagon/app/action_host.py': ['helao/hexagon/app/action_host.py:426'], ...`, the second starts `E       AssertionError: assert ['helao.core.`, and the run ends `2 failed, 5 passed`. `progress.py` prints:
```
static offenders (8): ['helao/helpers/server_api.py', 'helao/hexagon/app/action_host.py', 'helao/hexagon/app/endpoint_overlay.py', 'helao/hexagon/app/orch_dispatch.py', 'helao/hexagon/app/orch_estop.py', 'helao/hexagon/app/orch_host.py', 'helao/hexagon/app/orch_lifecycle.py', 'helao/hexagon/app/orch_queues.py']
runtime engine modules: 17
```

- [ ] **Step 2.4: Controller commits.** Files: `helao/hexagon/tests/test_engine_import_ratchet.py`. Run `black` on it first. Message:
```
test(b7a): engine import ratchet, both zero-halves xfail(strict) until the relocation lands

Static half sweeps git ls-files outside helao/core/servers/ and tests; runtime
half builds ActionHost + OrchHost in a subprocess. Allowlist (shrink-only):
harness/ws_frames.py, helao/hexagon/app/active_graft.py, helao/hexagon/app/factory.py.
Route-class pins for native and legacy hosts pass from the start.
```

---

### Task 3: `orch_unpack` moves to `helao/hexagon/app/`

**Files:**
- Create: `helao/hexagon/app/orch_unpack.py` (moved code, two docstring paragraphs rewritten)
- Rewrite: `helao/core/servers/orch_unpack.py` (re-export only)
- Modify: `helao/hexagon/app/orch_host.py` (one import)
- Modify: `helao/core/tests/unit_test_orch_unpack.py` (one import)

**Interfaces:**
- Consumes: Task 0 references, `S/progress.py`.
- Produces: module `helao.hexagon.app.orch_unpack` with `PLATE_API`, `unpack_sequence`, `get_sequence_codehash`, `seq_unpacker`, `verify_plate_in_params`. Task 4 reads `orch_unpack.PLATE_API` from it.

- [ ] **Step 3.1: Copy the module.**
```
cp /mnt/STORAGE/repos/helao/helao-b7a/helao/core/servers/orch_unpack.py /mnt/STORAGE/repos/helao/helao-b7a/helao/hexagon/app/orch_unpack.py
```

- [ ] **Step 3.2: Rewrite two stale docstring paragraphs in `helao/hexagon/app/orch_unpack.py`.** Replace:
```
``HTEPlateAPI``/``PLATE_API`` also move here (their sole previous purpose was
backing ``verify_plate_in_params``): ``PLATE_API = HTEPlateAPI()`` is now a
module-level singleton on this module, and ``orch.py`` re-imports it
(``from helao.core.servers.orch_unpack import PLATE_API``) so the existing
monkeypatch point (tests patching ``helao.core.servers.orch.PLATE_API``)
keeps working unchanged -- ``orch.py``'s name is just a second reference to
the same object this module owns.
```
with:
```
``HTEPlateAPI``/``PLATE_API`` also move here (their sole previous purpose was
backing ``verify_plate_in_params``): ``PLATE_API = HTEPlateAPI()`` is a
module-level singleton on this module, and this module attribute is the one
patch point for it. Native code reads ``orch_unpack.PLATE_API`` at call time
(B7a, D-B7a.2); ``helao/core/servers/orch_unpack.py`` and ``orch.py`` only
re-export it, so patching either of those names reaches nothing.
```
and replace:
```
CIRCULAR-IMPORT NOTE: ``orch.py`` imports this module at module top
(``from helao.core.servers import orch_unpack``), so this module must never
import from ``orch.py`` at module top. None of the functions below need
anything from ``orch.py``.
```
with:
```
Moved here from ``helao/core/servers/orch_unpack.py`` by B7a, code
unchanged; that module is now a re-export B7b deletes. This module imports
nothing from ``helao/core/servers/`` and must not start: the engine imports
it (through its re-export and ``orch.py``), never the other way round.
```

- [ ] **Step 3.3: Replace the whole of `helao/core/servers/orch_unpack.py` with:**
```python
"""Re-export of :mod:`helao.hexagon.app.orch_unpack` (B7a); B7b deletes it.

The definitions moved to ``helao/hexagon/app/orch_unpack.py``. Patching a name
here reaches nothing: the functions read ``PLATE_API`` from the module that
defines them.
"""

from helao.hexagon.app.orch_unpack import (  # noqa: F401
    PLATE_API,
    get_sequence_codehash,
    seq_unpacker,
    unpack_sequence,
    verify_plate_in_params,
)
```

- [ ] **Step 3.4: Repoint `helao/hexagon/app/orch_host.py`.** Delete the line
```
from helao.core.servers import orch_unpack
```
and replace
```
from helao.hexagon.app.action_host import ActionHost
```
with
```
from helao.hexagon.app import orch_unpack
from helao.hexagon.app.action_host import ActionHost
```

- [ ] **Step 3.5: Red-check `unit_test_orch_unpack.py` before touching it.**
```
timeout 120 /home/dan/.claude/jobs/337df2c4/tmp/b7a/py helao/core/tests/unit_test_orch_unpack.py > /home/dan/.claude/jobs/337df2c4/tmp/b7a/red_unpack.txt 2>/dev/null; echo rc=$?
grep -E 'orch_unpack test [0-9]' /home/dan/.claude/jobs/337df2c4/tmp/b7a/red_unpack.txt
```
Expected: `rc=1`, with `orch_unpack test 5 failed: plate-id present, PLATE_API.has_access True, valid platemap found -> True`. Tests 1–4 and 6 pass; 6 passes vacuously, because the real `PLATE_API` has no access either. If rc=0, STOP: the test was not intercepting, or the functions still read the engine module's global.

- [ ] **Step 3.6: Repoint the test.** In `helao/core/tests/unit_test_orch_unpack.py` replace
```
from helao.core.servers import orch_unpack
```
with
```
from helao.hexagon.app import orch_unpack
```
Then:
```
timeout 120 /home/dan/.claude/jobs/337df2c4/tmp/b7a/py helao/core/tests/unit_test_orch_unpack.py > /home/dan/.claude/jobs/337df2c4/tmp/b7a/t3_unpack.txt 2>/dev/null; echo rc=$?
grep -c 'passed' /home/dan/.claude/jobs/337df2c4/tmp/b7a/t3_unpack.txt
```
Expected: `rc=0`, `6`.

- [ ] **Step 3.7: Prove the move is verbatim and the engine only re-exports.**
```
/home/dan/.claude/jobs/337df2c4/tmp/b7a/py /home/dan/.claude/jobs/337df2c4/tmp/b7a/verify_moved.py helao/core/servers/orch_unpack.py helao/hexagon/app/orch_unpack.py unpack_sequence get_sequence_codehash seq_unpacker verify_plate_in_params
/home/dan/.claude/jobs/337df2c4/tmp/b7a/py -c "import helao.core.servers.orch as o, helao.core.servers.orch_unpack as e, helao.hexagon.app.orch_unpack as n; names = ['PLATE_API', 'get_sequence_codehash', 'seq_unpacker', 'unpack_sequence', 'verify_plate_in_params']; assert all(getattr(e, x) is getattr(n, x) for x in names); assert o.PLATE_API is n.PLATE_API and o.orch_unpack is e; print('re-export identity OK')" 2>/dev/null
grep -c 'PLATE_API = HTEPlateAPI()' /mnt/STORAGE/repos/helao/helao-b7a/helao/hexagon/app/orch_unpack.py
```
Expected: `verbatim: ['unpack_sequence', 'get_sequence_codehash', 'seq_unpacker', 'verify_plate_in_params']`, `DIFFERENT OR MISSING: []`, `re-export identity OK`, `1`.

- [ ] **Step 3.8: Focused tests.**
```
/home/dan/.claude/jobs/337df2c4/tmp/b7a/pt helao/hexagon/tests/test_orch_host_surface.py 2>&1 | tail -1
/home/dan/.claude/jobs/337df2c4/tmp/b7a/pt helao/hexagon/tests/test_orch_host_member_coverage.py 2>&1 | tail -1
/home/dan/.claude/jobs/337df2c4/tmp/b7a/py /home/dan/.claude/jobs/337df2c4/tmp/b7a/contract.py 2>/dev/null
/home/dan/.claude/jobs/337df2c4/tmp/b7a/gm_gate.sh t3
/home/dan/.claude/jobs/337df2c4/tmp/b7a/pt helao/hexagon/tests/test_engine_import_ratchet.py 2>&1 | tail -1
/home/dan/.claude/jobs/337df2c4/tmp/b7a/py /home/dan/.claude/jobs/337df2c4/tmp/b7a/progress.py 2>/dev/null
```
Expected: `11 passed…`; `5 passed…`; `137 36e56e44875e5234`; `check rc=1 (reference rc=1)` then `GM-GATE PASS t3`; `5 passed, 2 xfailed…`; `static offenders (8): [...]` (same 8 as Task 2) and `runtime engine modules: 17`.

- [ ] **Step 3.9: Controller commits.** Files: `helao/hexagon/app/orch_unpack.py` (new), `helao/core/servers/orch_unpack.py`, `helao/hexagon/app/orch_host.py`, `helao/core/tests/unit_test_orch_unpack.py`. Message:
```
refactor(b7a): move orch_unpack to helao/hexagon/app; engine module re-exports it

Code unchanged (AST-verified). PLATE_API's one patch point is now
helao.hexagon.app.orch_unpack.PLATE_API; unit_test_orch_unpack repointed
after a recorded red run (test 5 failed while it patched the re-export).
```

---

### Task 4: The three seams are read at call time from their owners (D-B7a.2), with red-checks

**Files:**
- Modify: `helao/hexagon/app/orch_dispatch.py`, `helao/hexagon/app/orch_estop.py`, `helao/hexagon/app/orch_lifecycle.py`
- Modify (tests): `helao/core/tests/test_orch_dispatch_golden_master.py`, `helao/core/tests/unit_test_orch_lifecycle.py`, `helao/hexagon/tests/test_dispatch_lock_not_held_across_post.py`

**Interfaces:**
- Consumes: `helao.hexagon.app.orch_unpack` (Task 3); `helao.helpers.dispatcher.async_action_dispatcher`; `helao.helpers.yml_tools.move_dir`.
- Produces: the only patch points are now `helao.helpers.dispatcher.async_action_dispatcher`, `helao.helpers.yml_tools.move_dir` and `helao.hexagon.app.orch_unpack.PLATE_API`.

- [ ] **Step 4.1: Port guard.** The red runs below call the real dispatcher against `127.0.0.1:8000-8003` and `8002`. Nothing may be listening there.
```
timeout 30 /home/dan/.claude/jobs/337df2c4/tmp/b7a/py helao/hexagon/tests/smoke/wait_ports_free.py --timeout 5 8000 8001 8002 8003; echo rc=$?
```
Expected: `rc=0`. If rc≠0, STOP and report; another group is running on those ports.

- [ ] **Step 4.2: `helao/hexagon/app/orch_dispatch.py`.** Five edits.

(a) Replace the docstring paragraph
```
CIRCULAR-IMPORT / MONKEYPATCH NOTE: this module must NOT import
``helao.core.servers.orch`` at module top (import-cycle rule). The two
module-globals the dispatch golden-master harness rebinds
(``helao.core.servers.orch.async_action_dispatcher`` and
``helao.core.servers.orch.PLATE_API``) are imported lazily inside the effect
methods that use them, so the external patch points keep working exactly as
they did before extraction (the same technique ``orch_lifecycle.py`` uses for
``move_dir``).
```
with
```
PATCH-SEAM NOTE (B7a, D-B7a.2): ``async_action_dispatcher`` and
``PLATE_API`` are read at call time from the modules that own them --
``dispatcher.async_action_dispatcher`` and ``orch_unpack.PLATE_API`` -- and
never bound to a name here. Those two module attributes are the only patch
points; the dispatch golden master rebinds exactly them.
```
(b) Replace
```
from helao.helpers import helao_logging as logging
from helao.helpers.premodels import Action, Experiment
```
with
```
from helao.helpers import dispatcher
from helao.helpers import helao_logging as logging
from helao.helpers.premodels import Action, Experiment
```
and replace
```
from helao.helpers.zdeque import zdeque
```
with
```
from helao.helpers.zdeque import zdeque
from helao.hexagon.app import orch_unpack
```
(c) In `_dispatch_action_locked`, replace
```
        orch = self.orch
        from helao.core.servers.orch import async_action_dispatcher

```
with
```
        orch = self.orch

```
and replace
```
                result_actiondict, error_code = await async_action_dispatcher(
                    orch.world_cfg, A
                )
```
with
```
                result_actiondict, error_code = (
                    await dispatcher.async_action_dispatcher(orch.world_cfg, A)
                )
```
(d) The block
```
        orch = self.orch
        from helao.core.servers.orch import PLATE_API

```
occurs **twice** (in `_verify_experiment_plate` and `dispatch_sequence`). Replace both occurrences with
```
        orch = self.orch

```
(e) The line
```
if orch.verify_plates and PLATE_API.has_access:
```
occurs **twice** (8 and 12 spaces of indent). Replace the text `orch.verify_plates and PLATE_API.has_access` with `orch.verify_plates and orch_unpack.PLATE_API.has_access` in both, keeping their indentation.

- [ ] **Step 4.3: `helao/hexagon/app/orch_estop.py`.** Four edits.

(a) Replace the docstring paragraph
```
``async_action_dispatcher`` (estop fan-out) and ``move_dir`` (promotion) are
imported LAZILY from :mod:`helao.core.servers.orch` at call time -- the same
idiom :mod:`helao.core.servers.orch_dispatch` and
:mod:`helao.core.servers.orch_lifecycle` use -- so ``orch`` stays the single
module-global patch point the dispatch golden master rebinds.
```
with
```
``async_action_dispatcher`` (estop fan-out) and ``move_dir`` (promotion) are
read at call time from the modules that own them --
``dispatcher.async_action_dispatcher`` and ``yml_tools.move_dir`` (B7a,
D-B7a.2) -- the same rule :mod:`helao.hexagon.app.orch_dispatch` and
:mod:`helao.hexagon.app.orch_lifecycle` follow, so those module attributes
are the only patch points the dispatch golden master rebinds.
```
(b) Replace
```
from helao.helpers import helao_logging as logging
```
with
```
from helao.helpers import dispatcher, yml_tools
from helao.helpers import helao_logging as logging
```
(c) Replace
```
        # Lazy import so ``orch`` remains the single module-global patch point
        # the dispatch golden master rebinds (see module docstring).
        from helao.core.servers.orch import async_action_dispatcher

        orch = self.orch
```
with
```
        orch = self.orch
```
and replace `_ = await async_action_dispatcher(` with `_ = await dispatcher.async_action_dispatcher(`.
(d) Replace
```
        # Lazy import so ``orch`` remains the single module-global patch point
        # the dispatch golden master rebinds (see module docstring).
        from helao.core.servers.orch import move_dir

        try:
            await move_dir(hobj, base=self.orch)
```
with
```
        try:
            await yml_tools.move_dir(hobj, base=self.orch)
```

- [ ] **Step 4.4: `helao/hexagon/app/orch_lifecycle.py`.** Four edits.

(a) Replace the docstring paragraph
```
CIRCULAR-IMPORT / MONKEYPATCH NOTE: ``orch.py`` imports this module at
module top, so ``move_dir`` is imported lazily inside
``finish_active_sequence``/``finish_active_experiment`` from
``helao.core.servers.orch`` (rather than bound once at this module's top)
-- this preserves the pre-existing external patch point
(``helao.core.servers.orch.move_dir``, e.g. the dispatch golden-master
harness's module-global rebind) exactly as it worked before extraction.
```
with
```
PATCH-SEAM NOTE (B7a, D-B7a.2): ``move_dir`` is read at call time as
``yml_tools.move_dir`` inside ``finish_active_sequence``/
``finish_active_experiment`` and never bound to a name here, so
``helao.helpers.yml_tools.move_dir`` is its one patch point -- the one the
dispatch golden master and ``unit_test_orch_lifecycle`` rebind.
```
(b) Replace
```
from helao.helpers import helao_logging as logging
```
with
```
from helao.helpers import helao_logging as logging
from helao.helpers import yml_tools
```
(c) The block
```
        orch = self.orch
        from helao.core.servers.orch import move_dir

```
occurs **twice**. Replace both with
```
        orch = self.orch

```
(d) Replace `orch.aloop.create_task(move_dir(orch.last_sequence, base=orch))` with `orch.aloop.create_task(yml_tools.move_dir(orch.last_sequence, base=orch))`, and `orch.aloop.create_task(move_dir(orch.last_experiment, base=orch))` with `orch.aloop.create_task(yml_tools.move_dir(orch.last_experiment, base=orch))`.

Leave `from helao.core.servers.base import Active` in place (Task 10 handles it).

- [ ] **Step 4.5: Static proof that no seam name is bound in the three modules.**
```
/home/dan/.claude/jobs/337df2c4/tmp/b7a/py -c "
import ast
seams = {'async_action_dispatcher', 'move_dir', 'PLATE_API'}
for rel in ('helao/hexagon/app/orch_dispatch.py', 'helao/hexagon/app/orch_estop.py', 'helao/hexagon/app/orch_lifecycle.py'):
    tree = ast.parse(open(rel, encoding='utf-8').read())
    bare = sorted({n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id in seams})
    imported = sorted({a.asname or a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names if (a.asname or a.name) in seams})
    print(rel, 'bare:', bare, 'imported:', imported)
"
```
Expected, three lines, each ending `bare: [] imported: []`.

- [ ] **Step 4.6: Red-checks. Run all three with the tests still patching `helao.core.servers.orch`.**
```
timeout 120 /home/dan/.claude/jobs/337df2c4/tmp/b7a/py helao/core/tests/test_orch_dispatch_golden_master.py --check > /home/dan/.claude/jobs/337df2c4/tmp/b7a/red_gm.txt 2>&1; echo rc=$?
timeout 600 /home/dan/.claude/jobs/337df2c4/tmp/b7a/py helao/core/tests/unit_test_orch_lifecycle.py > /home/dan/.claude/jobs/337df2c4/tmp/b7a/red_lifecycle.txt 2>/dev/null; echo rc=$?
grep -E 'orch_lifecycle test [0-9]+ failed' /home/dan/.claude/jobs/337df2c4/tmp/b7a/red_lifecycle.txt | cut -c1-40
timeout 90 /home/dan/.claude/jobs/337df2c4/tmp/b7a/py -m pytest -v -p no:cacheprovider --color=no helao/hexagon/tests/test_dispatch_lock_not_held_across_post.py > /home/dan/.claude/jobs/337df2c4/tmp/b7a/red_lock.txt 2>&1; echo rc=$?
grep -E '::test_' /home/dan/.claude/jobs/337df2c4/tmp/b7a/red_lock.txt | cut -c1-140
ps -eo pid,comm,args | awk '$2 ~ /^python/ && /test_orch_dispatch_golden_master|unit_test_orch_lifecycle|test_dispatch_lock_not_held/'; echo leftover-check-done
```
Expected, as measured during planning:
- golden master: `rc=124`. It hangs, because the real dispatcher retries against absent servers. `rc=1` with fewer than seven `  PASS` lines is also a valid red. **If rc=0, STOP**: a native read was missed, or the scenario never reaches the seam.
- lifecycle: `rc=1`, with `orch_lifecycle test 1 failed` and `orch_lifecycle test 2 failed`. `rc=124` is also a valid red. **If rc=0, STOP.**
- dispatch lock: `rc=124`, with `...::test_update_status_can_take_the_lock_while_a_dispatch_is_in_flight FAILED`; the second test starts and never completes. **If rc=0, STOP.**
- then `leftover-check-done` with no process lines above it (`timeout` has killed every red run).

- [ ] **Step 4.7: Move the golden master's patches (`helao/core/tests/test_orch_dispatch_golden_master.py`).**

(a) Replace
```
import helao.core.servers.orch as orch_module
```
with
```
import helao.helpers.dispatcher as dispatcher_module
import helao.helpers.yml_tools as yml_tools_module
import helao.hexagon.app.orch_unpack as orch_unpack_module
```
(b) In `_PatchedOrchGlobals.__enter__`, replace
```
        self._orig_action_dispatcher = orch_module.async_action_dispatcher
```
with
```
        self._orig_action_dispatcher = dispatcher_module.async_action_dispatcher
```
then replace
```
        self._orig_move_dir = orch_module.move_dir
        self._orig_plate_api = orch_module.PLATE_API
        orch_module.async_action_dispatcher = self._action_dispatcher
```
with
```
        self._orig_move_dir = yml_tools_module.move_dir
        self._orig_plate_api = orch_unpack_module.PLATE_API
        dispatcher_module.async_action_dispatcher = self._action_dispatcher
```
then replace `        orch_module.move_dir = self._move_dir_fn` with `        yml_tools_module.move_dir = self._move_dir_fn`, and `        orch_module.PLATE_API = SimpleNamespace(has_access=False)` with `        orch_unpack_module.PLATE_API = SimpleNamespace(has_access=False)`.
(c) In `__exit__`, replace
```
        orch_module.async_action_dispatcher = self._orig_action_dispatcher
```
with
```
        dispatcher_module.async_action_dispatcher = self._orig_action_dispatcher
```
and replace
```
        orch_module.move_dir = self._orig_move_dir
        orch_module.PLATE_API = self._orig_plate_api
```
with
```
        yml_tools_module.move_dir = self._orig_move_dir
        orch_unpack_module.PLATE_API = self._orig_plate_api
```
(d) Docstring and comments (no effect on traces). Replace
```
* ``async_action_dispatcher`` (module-global rebind on
  ``helao.core.servers.orch``) -- records every call as ``(server,
```
with
```
* ``async_action_dispatcher`` (module-global rebind on
  ``helao.helpers.dispatcher``) -- records every call as ``(server,
```
replace
```
  (module-global on ``helao.core.servers.orch``), so the plate-verification
```
with
```
  (module-global on ``helao.hexagon.app.orch_unpack``), so the plate-verification
```
replace
```
* ``move_dir`` (module-global rebind) -- recording no-op (no real file
  moves).
```
with
```
* ``move_dir`` (module-global rebind on ``helao.helpers.yml_tools``) --
  recording no-op (no real file moves).
```
replace
```
# fake module-global dispatchers (patched onto helao.core.servers.orch)
```
with
```
# fake module-global seams (patched onto the modules that own them, B7a)
```
and replace
```
    """Context manager patching the module-globals ``orch.py`` imports by name."""
```
with
```
    """Context manager patching each seam on the module that owns it (D-B7a.2)."""
```
Then confirm nothing still names the old binding:
```
grep -n 'orch_module' /mnt/STORAGE/repos/helao/helao-b7a/helao/core/tests/test_orch_dispatch_golden_master.py; echo grep-rc=$?
```
Expected: `grep-rc=1` (no matches).

- [ ] **Step 4.8: Move the lifecycle test's patch (`helao/core/tests/unit_test_orch_lifecycle.py`).** Replace
```
import helao.core.servers.orch as orch_module
```
with
```
import helao.helpers.yml_tools as yml_tools_module
```
replace
```
        self._orig = orch_module.move_dir
        orch_module.move_dir = _fake_move_dir
```
with
```
        self._orig = yml_tools_module.move_dir
        yml_tools_module.move_dir = _fake_move_dir
```
replace
```
        orch_module.move_dir = self._orig
```
with
```
        yml_tools_module.move_dir = self._orig
```
Replace all **three** occurrences of ``` ``helao.core.servers.orch.move_dir`` ``` with ``` ``helao.helpers.yml_tools.move_dir`` ```. Then replace
```
    (``finish_active_sequence``/``finish_active_experiment`` import it lazily
    from ``helao.core.servers.orch`` specifically so this external patch
    point keeps working post-extraction)."""
```
with
```
    (``finish_active_sequence``/``finish_active_experiment`` read
    ``yml_tools.move_dir`` at call time, so this module attribute is the
    patch point -- B7a, D-B7a.2)."""
```
Leave `from helao.core.servers.orch import Orch` alone: the test still drives legacy `Orch`, which is B7b's to change.

- [ ] **Step 4.9: Move the dispatch-lock test's patch (`helao/hexagon/tests/test_dispatch_lock_not_held_across_post.py`).** Replace
```
    # _dispatch_action_locked imports the name from helao.core.servers.orch
    # at call time, so that module's attribute is the seam.
    import helao.core.servers.orch as orch_mod

    monkeypatch.setattr(orch_mod, "async_action_dispatcher", fn, raising=True)
```
with
```
    # _dispatch_action_locked reads dispatcher.async_action_dispatcher at
    # call time (B7a, D-B7a.2), so that module attribute is the seam.
    import helao.helpers.dispatcher as dispatcher_mod

    monkeypatch.setattr(dispatcher_mod, "async_action_dispatcher", fn, raising=True)
```

- [ ] **Step 4.10: Green.**
```
/home/dan/.claude/jobs/337df2c4/tmp/b7a/gm_gate.sh t4
timeout 600 /home/dan/.claude/jobs/337df2c4/tmp/b7a/py helao/core/tests/test_orch_dispatch_golden_master.py > /home/dan/.claude/jobs/337df2c4/tmp/b7a/gm_default_t4.txt 2>/dev/null; echo rc=$?
tail -2 /home/dan/.claude/jobs/337df2c4/tmp/b7a/gm_default_t4.txt
timeout 300 /home/dan/.claude/jobs/337df2c4/tmp/b7a/py helao/core/tests/unit_test_orch_lifecycle.py > /dev/null 2>&1; echo lifecycle rc=$?
/home/dan/.claude/jobs/337df2c4/tmp/b7a/pt helao/hexagon/tests/test_dispatch_lock_not_held_across_post.py 2>&1 | tail -1
timeout 120 /home/dan/.claude/jobs/337df2c4/tmp/b7a/py helao/core/tests/unit_test_orch_unpack.py > /dev/null 2>&1; echo unpack rc=$?
/home/dan/.claude/jobs/337df2c4/tmp/b7a/pt helao/hexagon/tests/test_estop_policy.py 2>&1 | tail -1
timeout 300 /home/dan/.claude/jobs/337df2c4/tmp/b7a/py helao/core/tests/unit_test_estop_sync.py > /dev/null 2>&1; echo estop_sync rc=$?
/home/dan/.claude/jobs/337df2c4/tmp/b7a/py /home/dan/.claude/jobs/337df2c4/tmp/b7a/contract.py 2>/dev/null
/home/dan/.claude/jobs/337df2c4/tmp/b7a/py /home/dan/.claude/jobs/337df2c4/tmp/b7a/progress.py 2>/dev/null
```
Expected: `GM-GATE PASS t4`; `rc=0` with `DETERMINISM CHECK PASSED: two capture runs byte-identical for all 9 scenarios` and `ALL GOLDEN-MASTER HARNESS CHECKS PASSED`; `lifecycle rc=0`; `2 passed…`; `unpack rc=0`; `test_estop_policy` all passed; `estop_sync rc=0`; `137 36e56e44875e5234`; `static offenders (7)` (no `orch_estop.py`) and `runtime engine modules: 17`.

- [ ] **Step 4.11: Controller commits.** Files: `helao/hexagon/app/orch_dispatch.py`, `helao/hexagon/app/orch_estop.py`, `helao/hexagon/app/orch_lifecycle.py`, `helao/core/tests/test_orch_dispatch_golden_master.py`, `helao/core/tests/unit_test_orch_lifecycle.py`, `helao/hexagon/tests/test_dispatch_lock_not_held_across_post.py`. Message:
```
refactor(b7a): read the three golden-master seams from their owning modules

orch_dispatch/orch_estop/orch_lifecycle read dispatcher.async_action_dispatcher,
yml_tools.move_dir and orch_unpack.PLATE_API at call time and bind no seam name.
The golden master, unit_test_orch_lifecycle and the dispatch-lock test patch
those modules. Red-checks recorded first with the patches still on
helao.core.servers.orch: GM hung (rc=124), lifecycle tests 1-2 failed,
dispatch-lock test 1 failed. After: --check output and all 9 traces
byte-identical to 415c0bb2.
```

---

### Task 5: `orch_global_params` moves to `app/`; the domain copy is retired (D-B7a.5)

**Files:**
- Create: `helao/hexagon/app/orch_global_params.py` (byte-identical copy)
- Rewrite: `helao/core/servers/orch_global_params.py` (re-export)
- Delete: `helao/hexagon/domain/global_params.py`
- Modify: `helao/hexagon/app/orch_dispatch.py` (one import), `helao/hexagon/tests/test_global_params.py` (docstring + import)

**Interfaces:**
- Consumes: nothing new.
- Produces: `helao.hexagon.app.orch_global_params.apply_from_globals`, `collect_to_globals` (the only definitions).

- [ ] **Step 5.1: Copy the module byte for byte, then prove it.**
```
cp /mnt/STORAGE/repos/helao/helao-b7a/helao/core/servers/orch_global_params.py /mnt/STORAGE/repos/helao/helao-b7a/helao/hexagon/app/orch_global_params.py
git -C /mnt/STORAGE/repos/helao/helao-b7a show 415c0bb2:helao/core/servers/orch_global_params.py | cmp - /mnt/STORAGE/repos/helao/helao-b7a/helao/hexagon/app/orch_global_params.py && echo BYTE-IDENTICAL
```
Expected: `BYTE-IDENTICAL`. The file keeps its `helao_logging` `LOGGER` line, as the spec requires.

- [ ] **Step 5.2: Replace the whole of `helao/core/servers/orch_global_params.py` with:**
```python
"""Re-export of :mod:`helao.hexagon.app.orch_global_params` (B7a); B7b deletes it."""

from helao.hexagon.app.orch_global_params import (  # noqa: F401
    apply_from_globals,
    collect_to_globals,
)
```

- [ ] **Step 5.3: Repoint `helao/hexagon/app/orch_dispatch.py`.** Replace
```
from helao.core.servers.orch_global_params import (
```
with
```
from helao.hexagon.app.orch_global_params import (
```

- [ ] **Step 5.4: Retire the domain copy.**
```
rm /mnt/STORAGE/repos/helao/helao-b7a/helao/hexagon/domain/global_params.py
grep -rn --include='*.py' 'domain.global_params\|domain import global_params' /mnt/STORAGE/repos/helao/helao-b7a/helao /mnt/STORAGE/repos/helao/helao-b7a/harness; echo grep-rc=$?
```
Expected before Step 5.5: exactly one hit, `/mnt/STORAGE/repos/helao/helao-b7a/helao/hexagon/tests/test_global_params.py:3:from helao.hexagon.domain.global_params import (`, and `grep-rc=0`.

- [ ] **Step 5.5: Repoint `helao/hexagon/tests/test_global_params.py`.** Replace
```
"""Fold-in/fold-out semantics (orch_global_params.py, byte-identical port)."""
```
with
```
"""Fold-in/fold-out semantics of ``helao/hexagon/app/orch_global_params.py``."""
```
and replace
```
from helao.hexagon.domain.global_params import (
```
with
```
from helao.hexagon.app.orch_global_params import (
```
Re-run the grep from Step 5.4. Expected: no hits, `grep-rc=1`.

- [ ] **Step 5.6: Checks.**
```
/home/dan/.claude/jobs/337df2c4/tmp/b7a/pt helao/hexagon/tests/test_global_params.py 2>&1 | tail -1
/home/dan/.claude/jobs/337df2c4/tmp/b7a/pt helao/hexagon/tests/test_boundaries.py 2>&1 | tail -1
/home/dan/.claude/jobs/337df2c4/tmp/b7a/py -c "import helao.core.servers.orch_global_params as e, helao.hexagon.app.orch_global_params as n; assert e.apply_from_globals is n.apply_from_globals and e.collect_to_globals is n.collect_to_globals; print('re-export identity OK')" 2>/dev/null
/home/dan/.claude/jobs/337df2c4/tmp/b7a/gm_gate.sh t5
/home/dan/.claude/jobs/337df2c4/tmp/b7a/py /home/dan/.claude/jobs/337df2c4/tmp/b7a/contract.py 2>/dev/null
/home/dan/.claude/jobs/337df2c4/tmp/b7a/py /home/dan/.claude/jobs/337df2c4/tmp/b7a/progress.py 2>/dev/null
```
Expected: `5 passed…`; `test_boundaries` all passed; `re-export identity OK`; `GM-GATE PASS t5` (scenario 3 exercises the fold, and its log wording is unchanged); `137 36e56e44875e5234`; `static offenders (6)` (no `orch_dispatch.py`) and `runtime engine modules: 16`.

- [ ] **Step 5.7: Controller commits.** Files: `helao/hexagon/app/orch_global_params.py` (new), `helao/core/servers/orch_global_params.py`, `helao/hexagon/app/orch_dispatch.py`, `helao/hexagon/tests/test_global_params.py`, and the deletion of `helao/hexagon/domain/global_params.py` (stage the removal). Message:
```
refactor(b7a): one global-params fold, in helao/hexagon/app (D-B7a.5)

orch_global_params.py moves byte-identically (helao_logging LOGGER kept, so the
fold-in/fold-out lines still reach the ORCH log); the engine module re-exports
it. The unused domain copy, whose stdlib logger had no HELAO handler, is deleted
and test_global_params points at the app module.
```

---

### Task 6: `sanitize_sequence_label` moves into `orch_queues.py`

**Files:**
- Modify: `helao/hexagon/app/orch_queues.py`, `helao/core/servers/orch.py`, `helao/core/tests/test_standalone_operator.py` (one line)

**Interfaces:**
- Produces: `helao.hexagon.app.orch_queues.sanitize_sequence_label(label)`, re-exported as `helao.core.servers.orch.sanitize_sequence_label`.

- [ ] **Step 6.1: `helao/hexagon/app/orch_queues.py`.** Four edits.

(a) Replace the docstring paragraph
```
``sanitize_sequence_label`` stays a module-level function on ``orch.py`` (its
single home); ``_prep_sequence_meta`` and ``add_split_sequences`` reach it via
a lazy import inside the method body to avoid a circular import (``orch.py``
imports this module at module top).
```
with
```
``sanitize_sequence_label`` lives here, moved from ``orch.py`` by B7a (its
only native consumers are ``_prep_sequence_meta`` and
``add_split_sequences``); ``orch.py`` re-exports it until B7b deletes the
engine.
```
(b) Replace
```
import asyncio
from copy import deepcopy
```
with
```
import asyncio
import re
from copy import deepcopy
```
(c) Replace (the `LOGGER` line followed by one blank line)
```
LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

```
with
```
LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


def sanitize_sequence_label(label):
    """Collapse whitespace/underscore runs to single underscores (None-safe)."""
    if not label:
        return label
    return re.sub(r"[\s_]+", "_", label)

```
(d) The block
```
        orch = self.orch
        from helao.core.servers.orch import sanitize_sequence_label

```
occurs **twice** (`_prep_sequence_meta`, `add_split_sequences`). Replace both with
```
        orch = self.orch

```

- [ ] **Step 6.2: `helao/core/servers/orch.py`.** Replace
```
from helao.hexagon.app.orch_queues import RunQueues
```
with
```
from helao.hexagon.app.orch_queues import (
    RunQueues,
    sanitize_sequence_label,  # noqa: F401  re-export: moved to orch_queues by B7a
)
```
and delete this block: the two blank lines before `def sanitize_sequence_label` and the five-line function itself.
```


def sanitize_sequence_label(label):
    """Collapse whitespace/underscore runs to single underscores (None-safe)."""
    if not label:
        return label
    return re.sub(r"[\s_]+", "_", label)
```
Afterwards the `LOGGER = ...` line in `orch.py` is followed by two blank lines and then the `# ANSI color codes converted to the Windows versions` comment. Leave `import re` in `orch.py` alone; B7b deletes the file.

- [ ] **Step 6.3: `helao/core/tests/test_standalone_operator.py`.** Replace
```
    from helao.core.servers.orch import sanitize_sequence_label
```
with
```
    from helao.hexagon.app.orch_queues import sanitize_sequence_label
```

- [ ] **Step 6.4: Checks.**
```
/home/dan/.claude/jobs/337df2c4/tmp/b7a/py /home/dan/.claude/jobs/337df2c4/tmp/b7a/verify_moved.py helao/core/servers/orch.py helao/hexagon/app/orch_queues.py sanitize_sequence_label
/home/dan/.claude/jobs/337df2c4/tmp/b7a/py -c "import helao.core.servers.orch as o, helao.hexagon.app.orch_queues as q; assert o.sanitize_sequence_label is q.sanitize_sequence_label; print('re-export identity OK')" 2>/dev/null
/home/dan/.claude/jobs/337df2c4/tmp/b7a/pt helao/core/tests/test_standalone_operator.py 2>&1 | tail -1
timeout 300 /home/dan/.claude/jobs/337df2c4/tmp/b7a/py helao/core/tests/unit_test_orch_queues.py > /dev/null 2>&1; echo orch_queues rc=$?
/home/dan/.claude/jobs/337df2c4/tmp/b7a/gm_gate.sh t6
/home/dan/.claude/jobs/337df2c4/tmp/b7a/py /home/dan/.claude/jobs/337df2c4/tmp/b7a/contract.py 2>/dev/null
/home/dan/.claude/jobs/337df2c4/tmp/b7a/py /home/dan/.claude/jobs/337df2c4/tmp/b7a/progress.py 2>/dev/null
```
Expected: `verbatim: ['sanitize_sequence_label']`, `DIFFERENT OR MISSING: []`; `re-export identity OK`; `59 passed…`; `orch_queues rc=0`; `GM-GATE PASS t6`; `137 36e56e44875e5234`; `static offenders (5)` (no `orch_queues.py`) and `runtime engine modules: 16`.

- [ ] **Step 6.5: Controller commits.** Files: `helao/hexagon/app/orch_queues.py`, `helao/core/servers/orch.py`, `helao/core/tests/test_standalone_operator.py`. Message:
```
refactor(b7a): sanitize_sequence_label lives in orch_queues, its only native consumer

orch.py re-exports it; the two lazy engine imports in RunQueues are gone.
```

---

### Task 7: The seven payload builders move to `helao/hexagon/app/orch_payloads.py`

**Files:**
- Create: `helao/hexagon/app/orch_payloads.py`
- Modify: `helao/core/servers/orch_api.py` (bodies out, re-export in), `helao/hexagon/app/orch_host.py` (docstring + two imports)

**Interfaces:**
- Produces: `helao.hexagon.app.orch_payloads` with `_histories_payload`, `_history_page_payload`, `_status_summary_payload`, `_step_flags_payload`, `_set_step_flag`, `_queue_counts`, `_queue_object_payload`; `orch_api` re-exports all seven. `_prepend_sequences` stays in `orch_api.py`.

- [ ] **Step 7.1: Write and run the mechanical move script.** Create `/home/dan/.claude/jobs/337df2c4/tmp/b7a/move_payloads.py`:

```python
"""B7a Task 7: cut the seven payload builders out of orch_api.py into orch_payloads.py, verbatim."""

from pathlib import Path

W = Path("/mnt/STORAGE/repos/helao/helao-b7a")
api = W / "helao/core/servers/orch_api.py"
dest = W / "helao/hexagon/app/orch_payloads.py"
assert not dest.exists(), f"{dest} already exists"
src = api.read_text(encoding="utf-8")
a = src.index("def _histories_payload(orch) -> dict:")
b = src.index("async def _prepend_sequences(orch, sequences) -> list:")
c = src.index("def _queue_object_payload(orch, kind: str, idx: int) -> dict:")
d = src.index("class OrchAPI(HelaoFastAPI):")
assert a < b < c < d
header = '''"""Read-only payload builders behind the orchestrator's queue and history routes.

Moved verbatim from ``helao/core/servers/orch_api.py`` by B7a. Each takes the
orchestrator -- ``OrchHost`` natively, legacy ``Orch`` through ``orch_api``'s
re-export -- and reads its queues, histories, ``status_summary`` and
``step_thru_*`` flags at call time. They shape what the Bokeh and Reflex
operators parse, so there is one implementation, here; ``orch_api`` re-exports
these names until B7b deletes it.
"""

from typing import Optional


'''
dest.write_text(header + src[a:b] + src[c:d].rstrip("\n") + "\n", encoding="utf-8")
reexport = '''from helao.hexagon.app.orch_payloads import (  # noqa: F401  re-export (B7a)
    _histories_payload,
    _history_page_payload,
    _queue_counts,
    _queue_object_payload,
    _set_step_flag,
    _status_summary_payload,
    _step_flags_payload,
)
'''
src = src[:a] + src[b:c] + src[d:]
anchor = "from helao.helpers.server_api import HelaoFastAPI\n"
assert src.count(anchor) == 1
api.write_text(src.replace(anchor, anchor + reexport), encoding="utf-8")
print(f"wrote {dest.relative_to(W)}; orch_api.py now re-exports seven names")
```

```
/home/dan/.claude/jobs/337df2c4/tmp/b7a/py /home/dan/.claude/jobs/337df2c4/tmp/b7a/move_payloads.py
wc -l /mnt/STORAGE/repos/helao/helao-b7a/helao/hexagon/app/orch_payloads.py /mnt/STORAGE/repos/helao/helao-b7a/helao/core/servers/orch_api.py
```
Expected: `wrote helao/hexagon/app/orch_payloads.py; orch_api.py now re-exports seven names`; `118 …/orch_payloads.py` and `917 …/orch_api.py`.

- [ ] **Step 7.2: `helao/hexagon/app/orch_host.py`.** Replace
```
        The three payload builders are imported from ``orch_api`` rather
        than reimplemented: they shape what the operator UIs parse, and a
        second implementation would drift from the one the Bokeh and Reflex
        operators are written against. B7 deletes the importer.
```
with
```
        The three payload builders are imported from ``orch_payloads``
        rather than reimplemented: they shape what the operator UIs parse,
        and ``orch_payloads`` is the one implementation -- legacy
        ``orch_api`` re-exports it.
```
then replace
```
        from helao.core.servers.orch_api import (
            _histories_payload,
```
with
```
        from helao.hexagon.app.orch_payloads import (
            _histories_payload,
```
and replace
```
        from helao.core.servers.orch_api import (
            _queue_counts,
```
with
```
        from helao.hexagon.app.orch_payloads import (
            _queue_counts,
```

- [ ] **Step 7.3: Checks.**
```
/home/dan/.claude/jobs/337df2c4/tmp/b7a/py /home/dan/.claude/jobs/337df2c4/tmp/b7a/verify_moved.py helao/core/servers/orch_api.py helao/hexagon/app/orch_payloads.py _histories_payload _history_page_payload _status_summary_payload _step_flags_payload _set_step_flag _queue_counts _queue_object_payload
/home/dan/.claude/jobs/337df2c4/tmp/b7a/py -c "import helao.core.servers.orch_api as e, helao.hexagon.app.orch_payloads as n; names = ['_histories_payload', '_history_page_payload', '_status_summary_payload', '_step_flags_payload', '_set_step_flag', '_queue_counts', '_queue_object_payload']; assert all(getattr(e, x) is getattr(n, x) for x in names); assert e._prepend_sequences.__module__ == 'helao.core.servers.orch_api'; print('re-export identity OK')" 2>/dev/null
/home/dan/.claude/jobs/337df2c4/tmp/b7a/pt helao/core/tests/test_orch_queue_paging.py 2>&1 | tail -1
/home/dan/.claude/jobs/337df2c4/tmp/b7a/pt helao/core/tests/test_standalone_operator.py 2>&1 | tail -1
/home/dan/.claude/jobs/337df2c4/tmp/b7a/pt helao/core/tests/test_reflex_operator.py 2>&1 | tail -1
/home/dan/.claude/jobs/337df2c4/tmp/b7a/pt helao/hexagon/tests/test_orch_host_surface.py 2>&1 | tail -1
/home/dan/.claude/jobs/337df2c4/tmp/b7a/pt helao/hexagon/tests/test_orch_host_member_coverage.py 2>&1 | tail -1
/home/dan/.claude/jobs/337df2c4/tmp/b7a/py /home/dan/.claude/jobs/337df2c4/tmp/b7a/contract.py 2>/dev/null
/home/dan/.claude/jobs/337df2c4/tmp/b7a/gm_gate.sh t7
/home/dan/.claude/jobs/337df2c4/tmp/b7a/py /home/dan/.claude/jobs/337df2c4/tmp/b7a/progress.py 2>/dev/null
```
Expected: `DIFFERENT OR MISSING: []`; `re-export identity OK`; `13 passed…`; `59 passed…`; `194 passed…`; `11 passed…`; `5 passed…`; `137 36e56e44875e5234`; `GM-GATE PASS t7`; `static offenders (5)` (unchanged: `orch_host.py` still imports `WaitExec` and `Active`) and `runtime engine modules: 16`.

- [ ] **Step 7.4: Controller commits.** Files: `helao/hexagon/app/orch_payloads.py` (new), `helao/core/servers/orch_api.py`, `helao/hexagon/app/orch_host.py`. Message:
```
refactor(b7a): payload builders move to helao/hexagon/app/orch_payloads.py

Seven functions cut verbatim out of orch_api.py (AST-verified), which re-exports
them; OrchHost imports from the new home. _prepend_sequences stays with OrchAPI.
```

---

### Task 8: `WaitExec` and `checkcond` move to `helao/hexagon/app/orch_wait.py`

**Files:**
- Create: `helao/hexagon/app/orch_wait.py`
- Modify: `helao/core/servers/orch_api.py` (bodies out, re-export in), `helao/hexagon/app/orch_host.py` (one import)

**Interfaces:**
- Produces: `helao.hexagon.app.orch_wait.WaitExec(Executor)` and `checkcond(str, Enum)`, re-exported by `orch_api`.

- [ ] **Step 8.1: Write and run the move script.** Create `/home/dan/.claude/jobs/337df2c4/tmp/b7a/move_wait.py`:

```python
"""B7a Task 8: cut WaitExec and checkcond (the tail of orch_api.py) into orch_wait.py, verbatim."""

from pathlib import Path

W = Path("/mnt/STORAGE/repos/helao/helao-b7a")
api = W / "helao/core/servers/orch_api.py"
dest = W / "helao/hexagon/app/orch_wait.py"
assert not dest.exists(), f"{dest} already exists"
src = api.read_text(encoding="utf-8")
a = src.index("class WaitExec(Executor):")
tail = src[a:]
assert "class checkcond(str, Enum):" in tail and tail.rstrip().endswith('uncond = "uncond"')
header = '''"""The orchestrator's ``wait`` executor and the conditional-endpoint enum.

Moved verbatim from ``helao/core/servers/orch_api.py`` by B7a. ``OrchHost``
runs its ``wait`` action on :class:`WaitExec` and types its conditional
endpoints with :class:`checkcond`; ``orch_api`` re-exports both names for the
legacy ``OrchAPI`` until B7b deletes it.
"""

import asyncio
import time
from enum import Enum

from helao.core.error import ErrorCodes
from helao.core.models.hlostatus import HloStatus
from helao.helpers import helao_logging as logging
from helao.helpers.executor import Executor

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


'''
dest.write_text(header + tail.rstrip("\n") + "\n", encoding="utf-8")
src = src[:a].rstrip("\n") + "\n"
anchor = "from helao.helpers.server_api import HelaoFastAPI\n"
assert src.count(anchor) == 1
reexport = (
    "from helao.hexagon.app.orch_wait import (  # noqa: F401  re-export (B7a)\n"
    "    WaitExec,\n"
    "    checkcond,\n"
    ")\n"
)
api.write_text(src.replace(anchor, anchor + reexport), encoding="utf-8")
print(f"wrote {dest.relative_to(W)}; orch_api.py now re-exports WaitExec, checkcond")
```

```
/home/dan/.claude/jobs/337df2c4/tmp/b7a/py /home/dan/.claude/jobs/337df2c4/tmp/b7a/move_wait.py
tail -3 /mnt/STORAGE/repos/helao/helao-b7a/helao/core/servers/orch_api.py
```
Expected: `wrote helao/hexagon/app/orch_wait.py; orch_api.py now re-exports WaitExec, checkcond`, and `orch_api.py` now ends with `            LOGGER.info("orch shutdown")` / `            await self.orch.shutdown()` / `            time.sleep(0.75)`.

- [ ] **Step 8.2: `helao/hexagon/app/orch_host.py`.** Replace
```
        from helao.core.servers.orch_api import WaitExec, checkcond
```
with
```
        from helao.hexagon.app.orch_wait import WaitExec, checkcond
```

- [ ] **Step 8.3: Checks.**
```
/home/dan/.claude/jobs/337df2c4/tmp/b7a/py /home/dan/.claude/jobs/337df2c4/tmp/b7a/verify_moved.py helao/core/servers/orch_api.py helao/hexagon/app/orch_wait.py WaitExec checkcond
/home/dan/.claude/jobs/337df2c4/tmp/b7a/py -c "import helao.core.servers.orch_api as e, helao.hexagon.app.orch_wait as n; assert e.WaitExec is n.WaitExec and e.checkcond is n.checkcond; print('re-export identity OK')" 2>/dev/null
/home/dan/.claude/jobs/337df2c4/tmp/b7a/pt helao/hexagon/tests/test_orch_host_surface.py 2>&1 | tail -1
/home/dan/.claude/jobs/337df2c4/tmp/b7a/pt helao/hexagon/tests/test_factory.py 2>&1 | tail -1
/home/dan/.claude/jobs/337df2c4/tmp/b7a/pt helao/core/tests/test_standalone_operator.py 2>&1 | tail -1
/home/dan/.claude/jobs/337df2c4/tmp/b7a/pt helao/hexagon/tests/test_orch_host_member_coverage.py 2>&1 | tail -1
/home/dan/.claude/jobs/337df2c4/tmp/b7a/py /home/dan/.claude/jobs/337df2c4/tmp/b7a/contract.py 2>/dev/null
/home/dan/.claude/jobs/337df2c4/tmp/b7a/gm_gate.sh t8
/home/dan/.claude/jobs/337df2c4/tmp/b7a/py /home/dan/.claude/jobs/337df2c4/tmp/b7a/progress.py 2>/dev/null
```
Expected: `verbatim: ['WaitExec', 'checkcond']`, `DIFFERENT OR MISSING: []`; `re-export identity OK`; `11 passed…` (this includes the parameter-schema diff against the live-captured orch checklist, so the `checkcond` enum schema is unchanged); `17 passed…`; `59 passed…`; `5 passed…`; `137 36e56e44875e5234`; `GM-GATE PASS t8`; `static offenders (5)` and `runtime engine modules: 13`.

- [ ] **Step 8.4: Controller commits.** Files: `helao/hexagon/app/orch_wait.py` (new), `helao/core/servers/orch_api.py`, `helao/hexagon/app/orch_host.py`. Message:
```
refactor(b7a): WaitExec and checkcond move to helao/hexagon/app/orch_wait.py

Verbatim (AST-verified); orch_api re-exports both. Building OrchHost no longer
loads orch_api or orch.
```

---

### Task 9: `guarded_replace` is imported from its definition

**Files:**
- Modify: `helao/hexagon/app/action_host.py` (one line)

- [ ] **Step 9.1:** In `helao/hexagon/app/action_host.py` replace
```
        from helao.core.servers.base_status import guarded_replace
```
with
```
        from helao.core.models.status_transitions import guarded_replace
```

- [ ] **Step 9.2: Checks.**
```
/home/dan/.claude/jobs/337df2c4/tmp/b7a/py -c "import helao.core.servers.base_status as e, helao.core.models.status_transitions as n; assert e.guarded_replace is n.guarded_replace; print('same object')" 2>/dev/null
/home/dan/.claude/jobs/337df2c4/tmp/b7a/pt helao/hexagon/tests/test_action_host_surface.py 2>&1 | tail -1
/home/dan/.claude/jobs/337df2c4/tmp/b7a/pt helao/hexagon/tests/test_action_host_member_coverage.py 2>&1 | tail -1
/home/dan/.claude/jobs/337df2c4/tmp/b7a/pt helao/hexagon/tests/test_action_session_port.py 2>&1 | tail -1
/home/dan/.claude/jobs/337df2c4/tmp/b7a/py /home/dan/.claude/jobs/337df2c4/tmp/b7a/progress.py 2>/dev/null
```
Expected: `same object`; the three pytest files all passed (no failures); `static offenders (4)` (no `action_host.py`) and `runtime engine modules: 13`.

- [ ] **Step 9.3: Controller commits.** Files: `helao/hexagon/app/action_host.py`. Message:
```
refactor(b7a): ActionHost imports guarded_replace from status_transitions, its definition
```

---

### Task 10: Annotations name the native types (D-B7a.3)

**Files:**
- Modify: `helao/hexagon/app/orch_lifecycle.py`, `helao/hexagon/app/orch_host.py`, `helao/hexagon/app/endpoint_overlay.py`, `helao/core/servers/orch.py` (two pyright ignores; see Spec deviation 6)

**Interfaces:**
- Consumes: `helao.hexagon.app.action_session.ActionSession`, `helao.hexagon.app.action_host.ActionHost` (typing only).

- [ ] **Step 10.1: `helao/hexagon/app/orch_lifecycle.py`.** Replace
```
from copy import deepcopy
```
with
```
from copy import deepcopy
from typing import TYPE_CHECKING
```
delete the line
```
from helao.core.servers.base import Active
```
replace
```
from helao.helpers.time_utils import set_time

```
with
```
from helao.helpers.time_utils import set_time

if TYPE_CHECKING:  # pragma: no cover - typing only
    from helao.hexagon.app.action_session import ActionSession

```
replace
```
    def start_wait(self, active: Active):
```
with
```
    def start_wait(self, active: "ActionSession"):
```
and replace
```
    async def dispatch_wait_task(self, active: Active, print_every_secs: int = 5):
```
with
```
    async def dispatch_wait_task(
        self, active: "ActionSession", print_every_secs: int = 5
    ):
```

- [ ] **Step 10.2: `helao/hexagon/app/orch_host.py`.** Replace
```
    from helao.core.servers.base import Active
```
with
```
    from helao.hexagon.app.action_session import ActionSession
```
and replace
```
        self, active: "Active", print_every_secs: int = 5
```
with
```
        self, active: "ActionSession", print_every_secs: int = 5
```

- [ ] **Step 10.3: `helao/hexagon/app/endpoint_overlay.py`.** Replace
```
from typing import Optional

from helao.core.servers.base_api import BaseAPI
```
with
```
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # pragma: no cover - typing only
    from helao.hexagon.app.action_host import ActionHost
```
Replace all **three** occurrences of `app: BaseAPI` with `app: ActionHost`, and replace ``` ``BaseAPI(..., dyn_endpoints=...)`` ``` with ``` ``ActionHost(..., dyn_endpoints=...)`` ```. The module already has `from __future__ import annotations`.

- [ ] **Step 10.4: Show the pyright red on `orch.py`.**
```
cd /mnt/STORAGE/repos/helao/helao-b7a && pyright --outputjson helao/core/servers/orch.py > /home/dan/.claude/jobs/337df2c4/tmp/b7a/pyright_t10_red.json; echo rc=$?
/home/dan/.claude/jobs/337df2c4/tmp/b7a/py -c "import json; d = json.load(open('/home/dan/.claude/jobs/337df2c4/tmp/b7a/pyright_t10_red.json')); print(d['summary']['filesAnalyzed'], d['summary']['errorCount']); [print(x['range']['start']['line'] + 1, x['message'].splitlines()[0]) for x in d['generalDiagnostics'] if 'ActionSession' in x['message']]"
```
Expected: `rc=1`, `1 16`, then two lines: `833 Argument of type "Active" cannot be assigned to parameter "active" of type "ActionSession" in function "start_wait"` and `846 Argument of type "Active" cannot be assigned to parameter "active" of type "ActionSession" in function "dispatch_wait_task"`. These are the `415c0bb2` lines 837/850, shifted up by 4 because Task 6 removed the function. (On `415c0bb2` `orch.py` has 14 errors.) If the controller rejected Spec deviation 6, STOP here.

- [ ] **Step 10.5: `helao/core/servers/orch.py`, two black-stable ignores.** Replace
```
        return self.run_lifecycle.start_wait(active)
```
with
```
        return self.run_lifecycle.start_wait(
            active,  # pyright: ignore[reportArgumentType]  legacy Active; B7b deletes this
        )
```
and replace
```
        return await self.run_lifecycle.dispatch_wait_task(
            active, print_every_secs=print_every_secs
        )
```
with
```
        return await self.run_lifecycle.dispatch_wait_task(
            active,  # pyright: ignore[reportArgumentType]  legacy Active; B7b deletes this
            print_every_secs=print_every_secs,
        )
```
The ignore sits on the argument line, which is where pyright reports the error. A trailing comment on the call line would be moved to the closing parenthesis by black and would stop working.

- [ ] **Step 10.6: Checks.**
```
cd /mnt/STORAGE/repos/helao/helao-b7a && pyright --outputjson helao/core/servers/orch.py helao/hexagon/app/orch_lifecycle.py helao/hexagon/app/orch_host.py helao/hexagon/app/endpoint_overlay.py > /home/dan/.claude/jobs/337df2c4/tmp/b7a/pyright_t10.json; echo rc=$?
/home/dan/.claude/jobs/337df2c4/tmp/b7a/py -c "import json, collections; d = json.load(open('/home/dan/.claude/jobs/337df2c4/tmp/b7a/pyright_t10.json')); print(d['summary']['filesAnalyzed'], dict(collections.Counter(x['file'].rsplit('/', 1)[1] for x in d['generalDiagnostics'] if x['severity'] == 'error')))"
/home/dan/.claude/jobs/337df2c4/tmp/b7a/pt helao/hexagon/tests/test_endpoint_overlay.py 2>&1 | tail -1
/home/dan/.claude/jobs/337df2c4/tmp/b7a/pt helao/hexagon/tests/test_orch_host_surface.py 2>&1 | tail -1
timeout 300 /home/dan/.claude/jobs/337df2c4/tmp/b7a/py helao/core/tests/unit_test_orch_lifecycle.py > /dev/null 2>&1; echo lifecycle rc=$?
/home/dan/.claude/jobs/337df2c4/tmp/b7a/gm_gate.sh t10
/home/dan/.claude/jobs/337df2c4/tmp/b7a/py /home/dan/.claude/jobs/337df2c4/tmp/b7a/progress.py 2>/dev/null
```
Expected: `rc=1`, then `4 {'orch.py': 14, 'orch_host.py': 13}` (both equal to `415c0bb2`; `orch_lifecycle.py` and `endpoint_overlay.py` have none); `5 passed…`; `11 passed…`; `lifecycle rc=0`; `GM-GATE PASS t10`; `static offenders (1): ['helao/helpers/server_api.py']` and `runtime engine modules: 13`.

- [ ] **Step 10.7: Controller commits.** Files: `helao/hexagon/app/orch_lifecycle.py`, `helao/hexagon/app/orch_host.py`, `helao/hexagon/app/endpoint_overlay.py`, `helao/core/servers/orch.py`. Message:
```
refactor(b7a): annotations name ActionSession/ActionHost, typing-only imports (D-B7a.3)

orch_lifecycle's module-top base import becomes a TYPE_CHECKING import of
ActionSession. Legacy Orch still passes a legacy Active into the shared
RunLifecycle, so its two delegator calls carry pyright ignores; orch.py stays
at 14 errors, as on 415c0bb2.
```

---

### Task 11: `HelaoFastAPI` stops installing `ActionAPIRoute` (D-B7a.4)

**Files:**
- Modify: `helao/helpers/server_api.py`, `helao/core/servers/base_api.py`, `helao/core/servers/orch_api.py`, `helao/hexagon/app/action_host.py` (docstring + comment)

**Interfaces:**
- Produces: `HelaoFastAPI` leaves FastAPI's default route class; `BaseAPI.__init__` and `OrchAPI.__init__` each set `self.router.route_class = ActionAPIRoute` right after `super().__init__(...)`; `ActionHost` is unchanged in code.

- [ ] **Step 11.1: `helao/helpers/server_api.py`.** Replace
```
        super().__init__(*args, **kwargs, openapi_tags=TAGS)
        # Install the action-aware route class so endpoints tagged
        # "action" are auto-wrapped to populate the per-request
        # ActionInvocation ContextVar. Defer the import to avoid
        # circular imports (base_api -> base -> server_api).
        from helao.core.servers.base_api import ActionAPIRoute

        self.router.route_class = ActionAPIRoute
        self.helao_cfg
```
with
```
        super().__init__(*args, **kwargs, openapi_tags=TAGS)
        self.helao_cfg
```
Replace
```
config, logger, machine model, action-aware route class, and co-located ZMQ
RPC dispatcher;
```
with
```
config, logger, machine model, and co-located ZMQ RPC dispatcher;
```
and replace
```
    Installs the action-aware ``ActionAPIRoute`` route class, attaches the
    server's HELAO config slice,
```
with
```
    Attaches the server's HELAO config slice,
```

- [ ] **Step 11.2: Red: both legacy hosts lose the route class.**
```
/home/dan/.claude/jobs/337df2c4/tmp/b7a/pt helao/hexagon/tests/test_engine_import_ratchet.py -k legacy 2>&1 | grep -E '^E +AssertionError|passed|failed'
```
Expected: `E           AssertionError: ('BaseAPI', 'fastapi.routing.APIRoute')` and `1 failed, 6 deselected…`. If it passes, STOP: the legacy probe is not measuring the installed class.

- [ ] **Step 11.3: `helao/core/servers/base_api.py`.** In `BaseAPI.__init__`, replace
```
            version=str(version),
        )
        self.drivers: Any = tuple()
```
with
```
            version=str(version),
        )
        # Before any route: HelaoFastAPI no longer installs this (B7a, D-B7a.4).
        self.router.route_class = ActionAPIRoute
        self.drivers: Any = tuple()
```
Re-run the Step 11.2 command. Expected now: `E           AssertionError: ('OrchAPI', 'fastapi.routing.APIRoute')` and `1 failed…`. This is the regression the spec's brief would have shipped: OrchAPI's nine `tags=["action"]` endpoints lose their wrapping.

- [ ] **Step 11.4: `helao/core/servers/orch_api.py`.** Replace
```
from helao.core.servers.base_api import (
    _add_default_head_endpoints,
```
with
```
from helao.core.servers.base_api import (
    ActionAPIRoute,
    _add_default_head_endpoints,
```
and in `OrchAPI.__init__` replace
```
            version=str(version),
        )
        self.drivers = tuple()
```
with
```
            version=str(version),
        )
        # Before any route: HelaoFastAPI no longer installs this (B7a, D-B7a.4).
        self.router.route_class = ActionAPIRoute
        self.drivers = tuple()
```
Re-run the Step 11.2 command. Expected: `1 passed, 6 deselected…`.

- [ ] **Step 11.5: `helao/hexagon/app/action_host.py`, the stale docstring paragraph and comment.** Replace
```
**One B7 follow-up, recorded not fixed:** ``HelaoFastAPI.__init__`` imports
``ActionAPIRoute`` from ``helao.core.servers.base_api`` unconditionally
(``server_api.py:71``). Nothing here uses it — Task 4 replaces the router's route
class — but the *import* still runs, so ``server_api.py`` must be made lazy or
parameterised before B7 can delete the engine.
```
with
```
``HelaoFastAPI`` installs no route class of its own (B7a, D-B7a.4): each host
installs the one it needs before its first route. This one installs a
``BoundActionRoute`` bound to itself; legacy ``BaseAPI``/``OrchAPI`` install
``ActionAPIRoute``.
```
and replace
```
        # HelaoFastAPI installs the legacy ActionAPIRoute; replace it with a
        # subclass bound to THIS host before any route is registered, so no
        # legacy wrapping is ever applied and two hosts in one process do not
        # share a binding. See the module docstring for the B7 follow-up on the
        # import itself, which still runs.
```
with
```
        # Install a route class bound to THIS host before any route is
        # registered, so every action route is wrapped by it and two hosts in
        # one process do not share a binding. HelaoFastAPI installs none.
```

- [ ] **Step 11.6: Checks. The ratchet now fails on purpose.**
```
/home/dan/.claude/jobs/337df2c4/tmp/b7a/pt helao/hexagon/tests/test_engine_import_ratchet.py -rxX 2>&1 | grep -E 'XPASS|passed|failed'
/home/dan/.claude/jobs/337df2c4/tmp/b7a/py /home/dan/.claude/jobs/337df2c4/tmp/b7a/progress.py 2>/dev/null
/home/dan/.claude/jobs/337df2c4/tmp/b7a/pt helao/hexagon/tests/test_factory.py 2>&1 | tail -1
/home/dan/.claude/jobs/337df2c4/tmp/b7a/pt helao/hexagon/tests/test_action_host_surface.py 2>&1 | tail -1
/home/dan/.claude/jobs/337df2c4/tmp/b7a/pt helao/hexagon/tests/test_action_route.py 2>&1 | tail -1
/home/dan/.claude/jobs/337df2c4/tmp/b7a/pt helao/hexagon/tests/test_adapter_transport.py 2>&1 | tail -1
/home/dan/.claude/jobs/337df2c4/tmp/b7a/pt helao/hexagon/tests/test_orch_host_surface.py 2>&1 | tail -1
/home/dan/.claude/jobs/337df2c4/tmp/b7a/pt helao/hexagon/tests/test_hte_builds_on_linux.py 2>&1 | tail -1
timeout 300 /home/dan/.claude/jobs/337df2c4/tmp/b7a/py helao/core/tests/unit_test_base_api.py > /dev/null 2>&1; echo base_api rc=$?
/home/dan/.claude/jobs/337df2c4/tmp/b7a/gm_gate.sh t11
```
Expected: `[XPASS(strict)]` for `test_nothing_outside_the_engine_imports_it` and for `test_the_native_hosts_construct_without_the_engine`, then `2 failed, 5 passed…`. Both halves are at zero, and `strict=True` is now forcing Task 12. Then `static offenders (0): []` and `runtime engine modules: 0`; every pytest file passed; `base_api rc=0`; `GM-GATE PASS t11`.

- [ ] **Step 11.7: Controller commits.** Files: `helao/helpers/server_api.py`, `helao/core/servers/base_api.py`, `helao/core/servers/orch_api.py`, `helao/hexagon/app/action_host.py`. Message:
```
refactor(b7a): HelaoFastAPI no longer installs ActionAPIRoute; BaseAPI and OrchAPI do (D-B7a.4)

server_api.py stops importing the engine. Both legacy hosts install the route
class right after super().__init__, before their first route; the ratchet's
legacy probe failed on BaseAPI, then on OrchAPI, before each install landed.
Both ratchet halves now read zero (XPASS strict until the next commit).
```

---

### Task 12: Flip the ratchet

**Files:**
- Modify: `helao/hexagon/tests/test_engine_import_ratchet.py`

- [ ] **Step 12.1:** Delete both occurrences of this exact line (and nothing else):
```
@pytest.mark.xfail(strict=True, reason="B7a in progress; Task 12 deletes this marker")
```

- [ ] **Step 12.2:**
```
/home/dan/.claude/jobs/337df2c4/tmp/b7a/pt helao/hexagon/tests/test_engine_import_ratchet.py -rxX 2>&1 | tail -1
grep -c 'xfail' /mnt/STORAGE/repos/helao/helao-b7a/helao/hexagon/tests/test_engine_import_ratchet.py
```
Expected: `7 passed…`; `0`.

- [ ] **Step 12.3: Controller commits.** Files: `helao/hexagon/tests/test_engine_import_ratchet.py`. Message:
```
test(b7a): engine import ratchet at zero in both halves; drop the xfail markers
```

---

### Task 13: Gates (spec §7, as amended by the Spec deviations)

Run in this order on the branch head, after Task 12's commit. An implementer runs 13.1–13.5 and records the outputs in the scratch directory; the controller runs 13.6 and 13.7.

- [ ] **Step 13.1 — Gate 1: ratchet at zero, both halves.**
```
git -C /mnt/STORAGE/repos/helao/helao-b7a status --porcelain
/home/dan/.claude/jobs/337df2c4/tmp/b7a/pt helao/hexagon/tests/test_engine_import_ratchet.py -v 2>&1 | grep -E 'PASSED|FAILED|passed|failed'
/home/dan/.claude/jobs/337df2c4/tmp/b7a/py -c "from helao.hexagon.tests.test_engine_import_ratchet import ALLOWLIST, offenders, swept_files, _probe; o = offenders(); print(len(swept_files()), sorted(o) == sorted(ALLOWLIST), _probe('native')['engine_modules'])" 2>/dev/null
```
Expected: no `git status` output (everything committed); seven `PASSED` lines and `7 passed`; then `603 True []`. The 603 is the 600 of `415c0bb2`, plus the four new app modules, minus the deleted domain module.

- [ ] **Step 13.2 — Gate 2: golden master, and the recorded red-checks.**
```
/home/dan/.claude/jobs/337df2c4/tmp/b7a/gm_gate.sh final
timeout 600 /home/dan/.claude/jobs/337df2c4/tmp/b7a/py helao/core/tests/test_orch_dispatch_golden_master.py > /home/dan/.claude/jobs/337df2c4/tmp/b7a/gm_default_final.txt 2>/dev/null; echo rc=$?
tail -2 /home/dan/.claude/jobs/337df2c4/tmp/b7a/gm_default_final.txt
/bin/ls /home/dan/.claude/jobs/337df2c4/tmp/b7a/red_gm.txt /home/dan/.claude/jobs/337df2c4/tmp/b7a/red_lifecycle.txt /home/dan/.claude/jobs/337df2c4/tmp/b7a/red_lock.txt /home/dan/.claude/jobs/337df2c4/tmp/b7a/red_unpack.txt
grep -c 'failed' /home/dan/.claude/jobs/337df2c4/tmp/b7a/red_lifecycle.txt /home/dan/.claude/jobs/337df2c4/tmp/b7a/red_unpack.txt
grep -c 'FAILED' /home/dan/.claude/jobs/337df2c4/tmp/b7a/red_lock.txt
```
Expected: `GM-GATE PASS final` (the `--check` output is the same 7 PASS / 2 DELTA as `415c0bb2`, and all nine traces are byte-identical to `gm_ref/`); `rc=0` with `DETERMINISM CHECK PASSED…` / `ALL GOLDEN-MASTER HARNESS CHECKS PASSED`; all four red files listed; `red_lifecycle.txt:2`, `red_unpack.txt:1`; `1` (or more) for `red_lock.txt`. `red_gm.txt` records the hang (its rc was noted in the Task 4 report). Confirm `baseline_S0/` was not written:
```
cd /mnt/STORAGE/repos/helao/helao-b7a/.omc/artifacts/p5/baseline_S0 && sha256sum -c /home/dan/.claude/jobs/337df2c4/tmp/b7a/baseline_S0.sha256
```
Expected: nine `: OK`.

- [ ] **Step 13.3 — Gate 3: route checklists, no new diffs.**
```
/home/dan/.claude/jobs/337df2c4/tmp/b7a/pt harness/tests/test_hte_checklist.py 2>&1 | grep -E '^FAILED' | sort > /home/dan/.claude/jobs/337df2c4/tmp/b7a/checklist_fail_after.txt
/home/dan/.claude/jobs/337df2c4/tmp/b7a/pt helao/hexagon/tests/test_hte_route_checklist.py 2>&1 | grep -E '^FAILED' | sort >> /home/dan/.claude/jobs/337df2c4/tmp/b7a/checklist_fail_after.txt
/home/dan/.claude/jobs/337df2c4/tmp/b7a/pt harness/tests/test_freeze.py 2>&1 | grep -E '^FAILED' | sort >> /home/dan/.claude/jobs/337df2c4/tmp/b7a/checklist_fail_after.txt
cut -d' ' -f2 /home/dan/.claude/jobs/337df2c4/tmp/b7a/checklist_fail_after.txt
/home/dan/.claude/jobs/337df2c4/tmp/b7a/pt helao/hexagon/tests/test_orch_host_surface.py 2>&1 | tail -1
/home/dan/.claude/jobs/337df2c4/tmp/b7a/pt helao/hexagon/tests/test_action_host_surface.py 2>&1 | tail -1
```
Expected, exactly these five IDs (the drift that predates B7a: `andor` since PR #217 `366995c8`, plus `biologic` and `nidaqmx`, per Spec deviation 8):
```
harness/tests/test_hte_checklist.py::test_frozen_matches_regenerated[andor_server.py-ANDOR]
harness/tests/test_hte_checklist.py::test_frozen_matches_regenerated[biologic_server.py-BIOLOGIC]
harness/tests/test_hte_checklist.py::test_frozen_matches_regenerated[nidaqmx_server.py-NI]
helao/hexagon/tests/test_hte_route_checklist.py::test_module_matches_its_frozen_checklist[andor_server.py]
harness/tests/test_freeze.py::test_hte_freeze_is_clean_and_skips_nothing
```
then `11 passed…` and `8 passed…`. Any other FAILED ID blocks the merge.

- [ ] **Step 13.4 — Gate 4: full `run_tests.py`, baseline comparison (~8 minutes).**
```
cd /mnt/STORAGE/repos/helao/helao-b7a && timeout 5400 /home/dan/.claude/jobs/337df2c4/tmp/b7a/py run_tests.py > /home/dan/.claude/jobs/337df2c4/tmp/b7a/run_tests_after.txt 2>&1; echo rc=$?
tail -12 /home/dan/.claude/jobs/337df2c4/tmp/b7a/run_tests_after.txt
grep -E '^  (FAIL|TIMEOUT) ' /home/dan/.claude/jobs/337df2c4/tmp/b7a/run_tests_after.txt | awk '{print $2}' | sort > /home/dan/.claude/jobs/337df2c4/tmp/b7a/fail_after.txt
diff /home/dan/.claude/jobs/337df2c4/tmp/b7a/fail_before.txt /home/dan/.claude/jobs/337df2c4/tmp/b7a/fail_after.txt && echo FAIL-SET-UNCHANGED
grep -E 'test_engine_import_ratchet' /home/dan/.claude/jobs/337df2c4/tmp/b7a/run_tests_after.txt
```
Expected: `rc=1`; `===== 298 files`, `PASS 280`, `ENV 2`, `NOTESTS 13`, `FAIL 3` (measured in the planning dry run); `FAIL-SET-UNCHANGED`; `PASS     helao/hexagon/tests/test_engine_import_ratchet.py  7 passed`. `ENV` results are not failures. Any file in `fail_after.txt` that is not in `fail_before.txt` blocks the merge.

- [ ] **Step 13.5 — Gate 5: `run_unit_tests.py`, the standalone scripts, pyright.**
```
timeout 600 /home/dan/.claude/jobs/337df2c4/tmp/b7a/py run_unit_tests.py > /home/dan/.claude/jobs/337df2c4/tmp/b7a/run_unit_tests_after.txt 2>&1; echo rc=$?
/home/dan/.claude/jobs/337df2c4/tmp/b7a/unit_sweep.sh /home/dan/.claude/jobs/337df2c4/tmp/b7a/unit_after.txt
diff /home/dan/.claude/jobs/337df2c4/tmp/b7a/unit_before.txt /home/dan/.claude/jobs/337df2c4/tmp/b7a/unit_after.txt && echo UNIT-SCRIPTS-UNCHANGED
timeout 600 /home/dan/.claude/jobs/337df2c4/tmp/b7a/py helao/core/tests/test_active_golden_master.py --check > /home/dan/.claude/jobs/337df2c4/tmp/b7a/active_gm_after.txt 2>&1; echo active_gm rc=$?
cd /mnt/STORAGE/repos/helao/helao-b7a && xargs -a /home/dan/.claude/jobs/337df2c4/tmp/b7a/pyright_files_after.txt pyright --outputjson > /home/dan/.claude/jobs/337df2c4/tmp/b7a/pyright_after.json; echo pyright rc=$?
/home/dan/.claude/jobs/337df2c4/tmp/b7a/py /home/dan/.claude/jobs/337df2c4/tmp/b7a/pyright_cmp.py /home/dan/.claude/jobs/337df2c4/tmp/b7a/pyright_before.json /home/dan/.claude/jobs/337df2c4/tmp/b7a/pyright_after.json 24; echo cmp rc=$?
```
Expected: `rc=0` for `run_unit_tests.py`; `UNIT-SCRIPTS-UNCHANGED` (the 40 scripts give the same rc as on `415c0bb2`: only `unit_test_status_transitions.py` is 1); `active_gm rc=0`. The active golden master is green on `unstable` and has no fixture that B7a touches, so treat any non-zero rc as a regression and STOP. Then `pyright rc=1`; `errors before=169 after=169`, `files with more errors than on 415c0bb2: {}`, `cmp rc=0`. If `pyright_cmp.py` raises `pyright analyzed N files, expected 24`, the pass is vacuous: STOP.

- [ ] **Step 13.6 — Gate 6 (controller): `goldenhex` launch smoke with clean teardown.** This writes to the config's root `/home/dan/INST_hlo_hexsmoke`, which is outside the worktree, so the controller runs it.
```
timeout 30 /home/dan/.claude/jobs/337df2c4/tmp/b7a/py helao/hexagon/tests/smoke/wait_ports_free.py --timeout 10 8001 8002 8010; echo ports rc=$?
test -e /home/dan/INST_hlo_hexsmoke && mv /home/dan/INST_hlo_hexsmoke /home/dan/INST_hlo_hexsmoke.pre-b7a-$(date +%Y%m%d%H%M%S); echo root-ready
```
Expected: `ports rc=0`, `root-ready`. Start the launcher as a **background** command (the Bash tool's `run_in_background: true`). `exec` makes the recorded PID the launcher's own, and `launch.py`'s children die with it (`PR_SET_PDEATHSIG`), so the launcher must outlive the tool call:
```
bash -c 'echo $$ > /home/dan/.claude/jobs/337df2c4/tmp/b7a/smoke_launch.pid; date +%s > /home/dan/.claude/jobs/337df2c4/tmp/b7a/smoke_t0; cd /mnt/STORAGE/repos/helao/helao-b7a && PATH=/home/dan/miniforge3/envs/helao/bin:$PATH PYTHONPATH=/mnt/STORAGE/repos/helao/helao-b7a exec /home/dan/miniforge3/envs/helao/bin/python launch.py goldenhex < /dev/null > /home/dan/.claude/jobs/337df2c4/tmp/b7a/smoke_launch.log 2>&1'
```
Then, in a separate foreground call, wait until all three servers answer (up to 120 s):
```
for i in $(seq 1 60); do /home/dan/.claude/jobs/337df2c4/tmp/b7a/py -c "import urllib.request; [urllib.request.urlopen(f'http://127.0.0.1:{p}/openapi.json', timeout=3).read() for p in (8001, 8002, 8010)]" 2>/dev/null && { echo ALL-BOUND; break; }; sleep 2; done
```
Expected: `ALL-BOUND`. Then run one `goldenhex` sequence end to end through the capture rig. It submits, quiesces, and requires a fresh root, which the `mv` above guarantees:
```
cd /mnt/STORAGE/repos/helao/helao-b7a && timeout 900 /home/dan/.claude/jobs/337df2c4/tmp/b7a/py -m harness.capture --scenario GM-1 --root /home/dan/INST_hlo_hexsmoke --out /home/dan/.claude/jobs/337df2c4/tmp/b7a/smoke_gm1 --config-prefix goldenhex > /home/dan/.claude/jobs/337df2c4/tmp/b7a/smoke_capture.log 2>&1; echo capture rc=$?
find /home/dan/INST_hlo_hexsmoke/RUNS_FINISHED /home/dan/INST_hlo_hexsmoke/RUNS_SYNCED \( -name '*-seq.yml' -o -name '*.zip' \) 2>/dev/null | head -3
find /home/dan/INST_hlo_hexsmoke/RUNS_ACTIVE -type f 2>/dev/null | head -3; echo active-listed
```
Expected: `capture rc=0`; at least one `*-seq.yml` or `*.zip` under `RUNS_FINISHED/` or `RUNS_SYNCED/` (the SIM syncer may already have promoted it; Spec deviation 9); no files under `RUNS_ACTIVE/`. Make sure at least 90 s have passed since `smoke_t0`, then check that no child exited early:
```
echo elapsed=$(( $(date +%s) - $(cat /home/dan/.claude/jobs/337df2c4/tmp/b7a/smoke_t0) ))
grep -c 'exited on its own' /home/dan/.claude/jobs/337df2c4/tmp/b7a/smoke_launch.log
```
Expected: `elapsed` ≥ 90 (if it is lower, wait the difference first); `0`. Tear down through `teardown_group()`, the path CTRL-x uses:
```
kill -TERM $(cat /home/dan/.claude/jobs/337df2c4/tmp/b7a/smoke_launch.pid)
for i in $(seq 1 60); do kill -0 $(cat /home/dan/.claude/jobs/337df2c4/tmp/b7a/smoke_launch.pid) 2>/dev/null || { echo LAUNCHER-EXITED; break; }; sleep 2; done
test -e /home/dan/INST_hlo_hexsmoke/STATES/pids_goldenhex_.pck && echo PID-PICKLE-LEFT || echo PID-PICKLE-CLEARED
timeout 60 /home/dan/.claude/jobs/337df2c4/tmp/b7a/py helao/hexagon/tests/smoke/wait_ports_free.py --timeout 30 8001 8002 8010; echo ports-after rc=$?
```
Expected: `LAUNCHER-EXITED`, `PID-PICKLE-CLEARED`, `ports-after rc=0`. If the pickle is left or a port stays bound, run `helao/hexagon/tests/smoke/kill_group.py /home/dan/INST_hlo_hexsmoke goldenhex` to clean up, and record gate 6 as FAILED.

- [ ] **Step 13.7 — Gate 7 (controller): black.** Already run before each commit. As a final check:
```
cd /mnt/STORAGE/repos/helao/helao-b7a && git -C /mnt/STORAGE/repos/helao/helao-b7a diff --name-only --diff-filter=d 415c0bb2 -- '*.py' | xargs /home/dan/miniforge3/envs/helao/bin/black --check; echo black rc=$?
```
Expected: `black rc=0`.

- [ ] **Step 13.8: Report.** The controller records these gate results in the PR description: the Task 0 baselines, the four red-check files, `fail_before.txt` = `fail_after.txt`, the five checklist IDs that predate B7a, and pyright 169 → 169. The branch is then ready for review and a PR to `unstable`.
