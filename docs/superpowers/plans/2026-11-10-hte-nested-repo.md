# Split `hte` into its own public repository: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the framework services out of `helao/deploy/hte` into a new tracked `helao/deploy/base`, move the `hte`-dependent parent tests into `hte`, teach `setup_env`/`update_env` to clone or pull `hte`, then publish `hte` with its full history as `helao-hte-deployment` and stop tracking it in the parent.

**Architecture:** `base` is a deployment-shaped folder (`servers/<role>/`), so the launcher, preflight, the freezer and panel discovery all find the moved modules through the existing `helao.helpers.server_modules.locate` lookup, with no new resolution code. Imports are rewritten with the existing `harness/reorg_deploy.py --rewrite-only`. `helao_env.py` gains `hte_state` / `ensure_hte`, tested against a local bare repo. The history is moved with `git filter-repo --subdirectory-filter` and merged onto the new repo's initial commit with no force-push.

**Tech Stack:** Python 3.14, pytest + pytest-xdist, git, git-filter-repo (`/usr/bin/git-filter-repo`), conda (rattler solver), uv, black, pyright.

**Spec:** `docs/superpowers/specs/2026-11-10-hte-nested-repo-design.md` (commit 52137c5b). Executors read the spec and this plan.

---

## Open questions for the controller

These change behaviour and the spec does not settle them. Tasks that depend on one say **STOP: needs OQ-n** at the step concerned. Each one gives a recommended answer. The task is written for that answer, so a different ruling means editing only the step it names.

**Resolved 2026-11-10 (user rulings): all four take the recommended answer.** The STOP markers for OQ-1 to OQ-4 are therefore cleared, and the steps run as written.

- OQ-1: (a), rewrite pins to `deployment: base`.
- OQ-2: the recommended rule in Task 8.
- OQ-3: thin `hte` tests only for the two named-path tests.
- OQ-4: private-only packages stay in the root env.

The non-OQ STOP points still apply: private-repo uncommitted work, taken ports, the template `.gitignore`, and `hte` changing after extraction.

- **OQ-1: explicit `deployment: hte` pins on moved modules (contradicts §1 "Configs are untouched").** `launcher_bootstrap.resolve_app_deployment` honours an explicit `deployment:` key without checking it. After the move, every config that pins `deployment: hte` on a moved module makes the launcher import `helao.deploy.hte.servers.<role>.<module>`, which no longer exists, and makes preflight gate 2 report `deployment: hte has no servers/...`. Measured pins:
  - `hte`: 2 station configs (`configs/biologicole.yml`, `configs/biologiceclib2.yml`, server `ACTVIS`) and 17 smoke canaries in `tests/smoke/configs/` (`sync.yml` `SYNC`, and `ACTVIS` in `co2`, `co2gold`, `tec`, `tecgold`, `biologic`, `biologicgold`, `gamry`, `gamrygold`, `spec`, `specgold`, `galilio`, `galiliogold`, `powersupply`, `ni`, `mfc`, `mfcgold`);
  - Deployment-A: 1 entry; Deployment-B: 2 files; Deployment-C: 1 entry; Deployment-E: 3 entries in 1 file. The Task 4 scan lists them.

  Options: **(a, recommended)** rewrite each such pin to `deployment: base`, in the repo that owns the config. Smoke canaries outside `configs/` need an explicit key, because auto-detection reads the config's path, so the value is `base` rather than dropping the key. **(b)** Make the launcher and preflight fall back to auto-detection when an explicit deployment lacks the module. This changes a documented launcher rule (rule D-B7c.2) and preflight's gate 2. **(c)** Leave re-export shims in `hte`. This breaks the "one module, one deployment" invariant that §1 requires. Tasks 1 and 4 are written for (a).

- **OQ-2: when `setup_env`/`update_env` act while `hte` is absent.** §3 says "when a requested config launches or resolves any module from `hte`". With `hte` missing, that cannot be decided: an `hte` station config cannot even be resolved, and a private config's `hte` module names resolve nowhere. Two further gaps:
  1. After the parent pull, `update_env` with no arguments replays recorded config paths under `helao/deploy/hte/configs/`, which no longer exist. Today `stored_configs()` skips them with a warning, so the station would silently get the base env only.
  2. Reflex/Bokeh panels (`action_vis`/`live_vis`/`control_vis`) are `hte` code too, but `server_folders` only reads `fast:`/`bokeh:`.

  **Recommended rule (Tasks 7 and 8 implement it).** Act on `hte` only when one of these holds:
  - `hte` is a git repo and a resolved config uses an `hte` module or panel → pull;
  - `hte` is missing or a leftover, and (no prefix given, or a prefix does not resolve, or a recorded config path under `helao/deploy/hte` is missing, or a module/panel resolves in no deployment) → clone, then resolve again;
  - `hte` is tracked by the parent (every commit before the cutover) → never act.

- **OQ-3: "thin `hte` tests" for the sweeps.** `test_palette` (`helao/deploy/*/servers/**`), `test_reflex_bundle` and `helao/deploy/test/tests/test_vis_ws_parity.py` already glob `helao/deploy/*`, so they cover `hte` whenever it is cloned in place, exactly as they cover the private repos today. Only `test_driver_host_surface` (`ROOTS` names `helao/deploy/hte`) and `test_external_composition_contract`'s registrar pin read `hte` by name. **Recommended:** thin `hte` tests only for those two (Task 9). The palette's `SWEEP_EXEMPT_SITES` keeps its two `hte` `spec_vis.py` entries in the parent, because they are inert when `hte` is absent and needed when it is present.

- **OQ-4: packages used by private deployments but by no parent code.** The §4 audit classes cover framework, `hte`-server and `hte`-shared only. A package that only a private deployment (and maybe `hte`) imports would leave the root env, and a fresh install of that private station would then lose it. **Recommended:** it stays in the root env. The audit lists it as `private-only`, and nothing moves.

---

## Global Constraints

Every task's requirements include this section.

**Paths and tools**
- `REPO=/mnt/STORAGE/repos/helao/helao-async`, `ENV=/home/dan/miniforge3/envs/helao`, `PY=$ENV/bin/python`. Run every Python command as `PYTHONPATH=$REPO $PY ...`. Never use `conda run python - <<EOF` (it drops stdin).
- Private repo paths are written `helao/deploy/$DEP_A`, `$DEP_B`, `$DEP_C`, `$DEP_E`, `$DEP_F`. The controller supplies the values out of band. **Never write a private deployment's directory name into any tracked parent file, commit message or this plan.** Refer to private repos only as Deployment-A, B, C, E or F. `hte`, `test` and `base` may be named.
- Scratch and logs go under `D=$CLAUDE_JOB_DIR/<task-id>` (`mkdir -p $D`), never under shared `/tmp`.

**Public repo**
- The parent remote is public. No private deployment name, config filename or path in tracked files.

**Network mounts**
- Never read, list or write `/mnt/wd4`, `/mnt/st2`, `/mnt/k`, `/mnt/j` or `/mnt/i` locally. Anything there runs over `ssh -o BatchMode=yes -i ~/.ssh/id_ed25519_note01 hte-note-01.caltech.edu '<cmd>'`.
- Never execute pre-fix code against production defaults (a default data root such as `/mnt/wd4/DATA`). Nothing in this plan needs production data.

**Git**
- Subagents never run `git add`, `git commit`, `git push`, `git stash`, `git rm --cached`, `git mv` or any other index or remote write. Every git call is `git -C <repo> ...`.
- Commits and pushes are controller-only, after user approval. The "Commit" step of each task is a hand-off: the subagent lists the files and a proposed message, and the controller commits.
- Before cutover (Tasks 1-11), `helao/deploy/hte` is tracked by the parent, so its changes are parent commits. Private repos are separate repos at `helao/deploy/$DEP_*`, each with its own commit.
- Never force-push. The new repo already holds initial commit `cdaf724` (README/LICENSE/.gitignore). The `hte` history is merged onto it with `--allow-unrelated-histories`.
- Push order (spec §3):
  1. the `hte` repo, verified by a fresh clone;
  2. the parent `base` move (Tasks 1-3, plus Tasks 5-10);
  3. the private repos' import updates (Task 4);
  4. the parent cutover commit (Task 12).

  Never push a parent that drops `hte` while the new repo lacks it.
- If a subagent reports that it committed, pushed or wrote outside the tree, the controller checks with `git -C <repo> log -1` / `git -C <repo> status` and tells the user.

**Formatting, types, colours**
- Run `$PY -m black <changed .py files>` immediately before each commit, in the repo that owns the files.
- `$ENV/bin/pyright <changed .py files>`: no new errors. At task start, save `pyright` output for the files to be changed (old paths for moved files) to `$D/pyright-before.txt`, and compare error counts after.
- Colours live only in `helao/ui/shared/palette.py`. `helao/core/tests/test_palette.py` must stay green.

**Gates** (run at the end of every task that changes Python)
- Golden masters must stay byte-identical. Both commands must exit 0:
  ```bash
  cd $REPO && PYTHONPATH=$REPO $PY helao/core/tests/test_orch_dispatch_golden_master.py --check
  cd $REPO && PYTHONPATH=$REPO $PY helao/core/tests/test_active_golden_master.py --check
  ```
- **Standard sweep.** The baseline is 0 failures on 2026-11-10. Start the job and the watcher as **two separate** background commands. The main session runs the watcher, because a subagent is not woken by its own background job. Never detect the end with `pgrep`/`pkill`.
  ```bash
  # background command 1 (job)
  D=$CLAUDE_JOB_DIR/<task-id>; mkdir -p $D; cd $REPO
  PYTHONPATH=$REPO $PY run_tests.py --list | awk 'NF==2 && $2 ~ /\.py$/ {print $2}' > $D/files.txt
  ( PYTHONPATH=$REPO $PY -m pytest -n auto --dist loadfile -p no:cacheprovider -q $(cat $D/files.txt) > $D/run.log 2>&1; echo $? > $D/done )
  # background command 2 (watcher, 3 h cap)
  for i in $(seq 1 720); do [ -f "$D/done" ] && break; sleep 15; done; echo "rc=$(cat $D/done 2>/dev/null || echo TIMEOUT)"; tail -5 $D/run.log
  ```
  Expected: `rc=0`, and the summary line shows `0 failed` and no `error`. If something fails in a file under a private repo, first run `git -C helao/deploy/$DEP_x status --short`: another session's uncommitted work is not this task's failure.
- TDD with a mutation check for every behaviour change. Write the test, see it fail for the stated reason, implement, see it pass, then break the guarded behaviour once and see the test fail again. The plan names each mutation. Revert the mutation before moving on.

**Live groups**
- Before a launch, check the ports with `ss -ltnp`. Launch with `./helao.sh <prefix>` from the checkout being tested. Record the launcher PID.
- Stop with `kill -TERM <launcher PID>` (a graceful stop), and confirm with `ss -ltnp` that the ports are released.
- Never `pkill`/`pgrep` by pattern, and never `--force-relaunch`.

**Frozen route gates**
- Never run `python -m harness.freeze` to write checklists, and never regenerate a frozen JSON.
- Moving a checklist means moving its bytes. A manifest or list entry moves verbatim from one file to the other, checked by the Task 1 Step 6 script.

---

## Review Focus

These are the five conditions the spec implies but does not test, most likely to hurt first. Each has a pinning test in the task named.

1. **`ensure_hte` must never delete the developer's tracked `hte`.** Before the cutover, `helao/deploy/hte` has no `.git`, which is exactly the "leftover" shape. Expected: a folder tracked by the parent repo is left alone. Pinned by `test_ensure_hte_leaves_a_tracked_folder_alone` (Task 7).
2. **The `update_env` replay after the parent pull.** Recorded configs under `helao/deploy/hte/configs/` vanish with the pull. Expected: `update_env` with no arguments clones `hte` and reinstalls the station packages, instead of warning and installing the base env only. Pinned by `test_update_replay_clones_hte_when_a_recorded_config_vanished` (Task 8).
3. **A private config that uses only `hte` panels.** For example a `reflex:` group whose `action_vis` names an `hte` panel while every `fast:` module is in `base`. Expected: `hte` still counts as needed. Pinned by `test_config_hte_use_counts_panels` (Task 8).
4. **Explicit `deployment: hte` on a moved server** (OQ-1). Expected: preflight and the launcher resolve it to `base`. Pinned by `test_no_config_pins_hte_for_a_base_module` (Task 1) and by the private-repo scan in Task 4.
5. **`update.sh`/`update.bat` entering a leftover `hte` without `.git`.** `git pull` there walks up and acts on the parent repo. Expected: a deployment folder without `.git` is skipped with a message. Pinned by the Task 13 dry-run step "leftover is skipped by update.sh".

---

## File structure

| Path | Responsibility | Task |
|---|---|---|
| `helao/deploy/base/__init__.py`, `servers/__init__.py`, `tests/__init__.py` | new package shell | 1 |
| `helao/deploy/base/README.md` | what `base` is and why it is tracked | 1 |
| `helao/deploy/base/servers/{orchestrator,operator,visualizer,sync,reflex}/` | moved whole from `hte` | 1 |
| `harness/reorg/base.json` | move map used by `reorg_deploy --rewrite-only` in the parent and the private repos | 1 |
| `helao/deploy/base/tests/test_base_modules_unique.py` | every `base` module resolves to `base` only; no config pins `hte` for a `base` module | 1 |
| `helao/deploy/base/tests/checklists/{sync_server.json,servers.json,_at_b7c.json,_additions.json}` | sync_server's frozen route record, split verbatim from `hte` | 1 |
| `helao/deploy/base/tests/test_route_checklist.py` | `base`'s route gate | 1 |
| `helao/deploy/base/tests/test_*.py` (moved) | orchestrator/operator/visualizer/syncer tests | 2 |
| `helao/deploy/hte/tests/test_reflex_instrument_panels.py` | `hte` panel cases cut out of the moved reflex tests | 2 |
| `helao/hexagon/tests/checklists/_baseapi_system_surface.{json,md}` | base-API surface checklist, moved from `hte` | 3 |
| `docs/superpowers/plans/2026-11-10-hte-env-audit.md` | env audit result (aliases only) | 5 |
| `helao_env.py` | `HTE_URL`, `hte_state`, `ensure_hte`, `config_hte_use`, `wants_hte`, and the optional deployment-root env rule | 6, 7, 8 |
| `helao/deploy/hte/tests/test_*_hte.py` | `hte` parts of parent tests | 9 |
| `.gitignore`, `update.sh`, `update.bat`, `readme.md`, `CLAUDE.md`, `helao/deploy/__init__.py`, `helao/ui/{reflex,shared}/CLAUDE.md` | cutover | 12 |

---

## Stage 1: the `base` move (parent repo)

### Task 1: Move the five service folders into `base`, rewrite imports, split the sync route gate

**Dependency closure (measured; record it in the commit message).** These are everything the moved modules import from `helao.deploy.hte`, found by AST scan of every `.py` in the five folders:
- relative `._vis_host` and `._live_panel` (inside `visualizer/`);
- `helao.deploy.hte.servers.reflex._action`, `._pstat` and `._live` (inside `reflex/`).

All of them are inside the moving set. There are no dynamic imports (`import_module`/`__import__`) in the five folders. Every other import is framework (`helao.hexagon`, `helao.helpers`, `helao.ui`, `helao.core`) or third party. **The closure reaches no group-2 instrument code, so there is no STOP.**

`reflex/_pstat.py` and `_pstat_panel.py` import only framework code and `_action`, so they move with the folder, kept whole. Their only consumers are `hte`'s `gamry/reflex/gamry_vis.py` and `biologic/reflex/biologic_vis.py`, which then import from `base`. The same holds for `visualizer/{digital_out_control,motion_control_*_scale,pressure_vis,temp_vis}.py` and their `reflex/` twins: they import only `helao.ui.*`.

**Files:**
- Create: `helao/deploy/base/__init__.py`, `helao/deploy/base/servers/__init__.py`, `helao/deploy/base/tests/__init__.py`, `helao/deploy/base/README.md`, `harness/reorg/base.json`, `helao/deploy/base/tests/test_base_modules_unique.py`, `helao/deploy/base/tests/test_route_checklist.py`, `helao/deploy/base/tests/checklists/{servers.json,_at_b7c.json,_additions.json}`
- Move (filesystem `mv`, not `git mv`): `helao/deploy/hte/servers/{orchestrator,operator,visualizer,sync,reflex}` → `helao/deploy/base/servers/`; `helao/deploy/hte/tests/checklists/sync_server.json` → `helao/deploy/base/tests/checklists/sync_server.json`
- Modify: `.gitignore:22-25`; `helao/core/tests/test_framework_deployment_free.py:8`; `helao/core/tests/test_server_modules.py:97-98`; `helao/core/tests/test_resolve_app_deployment.py:52-58`; `helao/core/tests/test_reflex_config.py:121` (the `"hte" in order` assertion in `test_discovery_search_order_puts_configured_deployment_first`); `helao/deploy/test/tests/test_data_browser.py:741`; `helao/deploy/hte/tests/test_route_checklist.py:56,80,313`; `helao/deploy/hte/tests/checklists/{servers.json,_at_b7c.json,_additions.json}`; `helao/deploy/hte/tests/test_hte_builds_on_linux.py:80,107,126`; the 19 `hte` configs listed in OQ-1; and every file the rewrite tool reports
- Test: `helao/deploy/base/tests/test_base_modules_unique.py`, `helao/deploy/base/tests/test_route_checklist.py`

**Interfaces:**
- Produces: the import root `helao.deploy.base.servers.<role>.<module>` for every moved module; `harness/reorg/base.json` (used by Task 4); `preflight._checklist_dir("base") == helao/deploy/base/tests/checklists`.

- [ ] **Step 1: Write the failing gate tests**

`helao/deploy/base/tests/test_base_modules_unique.py`:
```python
"""Every module in helao/deploy/base resolves to base, and to no other deployment.

The launcher, preflight, the freezer and panel discovery all resolve a bare
module name across deployments (``helao.helpers.server_modules.locate``). A
name that also exists in another deployment makes the launcher warn and take
the first in sorted order, and makes panel lookup raise. So a framework
service must exist in exactly one place. The check is scoped to base: a few
deliberate cross-deployment duplicates exist elsewhere (a private deployment's
``ws_simulator``, pinned by test_preflight), and they are not base's business.
"""

from pathlib import Path

import pytest
import yaml

from helao.helpers import server_modules as sm

BASE = Path(__file__).resolve().parents[1]
MOVED = {
    "async_orch2",
    "standalone_operator",
    "action_visualizer",
    "live_visualizer",
    "control_visualizer",
    "data_browser",
    "sync_server",
}


def _base_modules() -> list[tuple[str, str]]:
    out = []
    for p in sorted((BASE / "servers").rglob("*.py")):
        if p.name == "__init__.py" or "__pycache__" in p.parts:
            continue
        for stack in sm.STACKS:
            found = sm.module_file("base", p.stem, stack)
            if found is not None and found.resolve() == p.resolve():
                out.append((p.stem, stack))
    return out


MODULES = _base_modules()


def test_base_holds_the_moved_services():
    assert MOVED <= {m for m, s in MODULES if s == "app"}


@pytest.mark.parametrize("module,stack", MODULES, ids=[f"{s}:{m}" for m, s in MODULES])
def test_module_exists_in_base_only(module, stack):
    assert sm.locate(module, stack)[1] == ["base"]


def test_no_config_pins_hte_for_a_base_module():
    """OQ-1 (a): an explicit ``deployment: hte`` on a base module is honoured
    unchecked by the launcher and imports a module that no longer exists."""
    bad = []
    for cfg in sorted(sm.DEPLOY_ROOT.glob("*/**/configs/*.yml")):
        data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
        servers = data.get("servers") if isinstance(data, dict) else None
        for key, s in (servers or {}).items():
            if not isinstance(s, dict):
                continue
            module = s.get("fast") or s.get("bokeh")
            if module in MOVED and s.get("deployment") == "hte":
                bad.append(f"{cfg.relative_to(sm.DEPLOY_ROOT)}:{key}")
    assert not bad, bad
```
The glob `*/**/configs/*.yml` covers `configs/` and `tests/smoke/configs/` in every deployment present, private repos included. The failure message prints private paths only on a local run, never into a tracked file.

`helao/deploy/base/tests/test_route_checklist.py`:
```python
"""base's frozen action-server route set: sync_server, split verbatim from hte's.

These checklist files were MOVED from helao/deploy/hte/tests/checklists, never
regenerated. Do not run ``python -m harness.freeze`` to rewrite them; see the
docstring of hte's test_route_checklist.py for why a regenerated record proves
nothing.
"""

import json
from pathlib import Path

from harness import freeze
from harness.endpoints import diff_route_sets, extract_routes, filter_allowed_additions
from helao.helpers.server_modules import module_file
from helao.hexagon import preflight

OUT = Path(__file__).resolve().parent / "checklists"
SERVERS = [(e["module"], e["representative_key"]) for e in freeze.load_manifest(OUT)]


def _json(name):
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def test_the_manifest_is_sync_server_only():
    assert SERVERS == [("sync_server.py", "DB")]


def test_sync_server_matches_its_frozen_checklist():
    additions = [a for a in _json("_additions.json") if a["module"] == "sync_server.py"]
    current = extract_routes(module_file("base", "sync_server", "app"), server_key="DB")
    diffs, _ = filter_allowed_additions(
        diff_route_sets(_json("sync_server.json"), current), additions
    )
    assert diffs == [], json.dumps(diffs, indent=2)


def test_the_frozen_record_is_eight_private_routes():
    rows = _json("sync_server.json")
    action = sum("action" in r["tags"] for r in rows)
    private = sum("private" in r["tags"] and "action" not in r["tags"] for r in rows)
    assert (action, private) == (0, 8)


def test_frozen_at_b7c_list_is_present_and_complete():
    cdir = preflight._checklist_dir("base")
    assert cdir == OUT
    assert preflight._frozen_checklists(cdir) == {"sync_server"}


def test_base_freeze_is_clean_and_skips_nothing():
    lines, blockers = freeze.freeze_deployment("base", dry_run=True)
    assert blockers == []
    assert not [ln for ln in lines if "skipped" in ln], lines
    assert all("would write" not in ln for ln in lines), lines
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd $REPO && PYTHONPATH=$REPO $PY -m pytest helao/deploy/base/tests -q -p no:cacheprovider`
Expected: FAIL or ERROR. `test_base_holds_the_moved_services` fails on an empty set. The route tests error with `no servers.json in .../base/tests/checklists`. `test_no_config_pins_hte_for_a_base_module` fails, listing the 19 `hte` pins and the private ones.

- [ ] **Step 3: Write the move map and move the folders**

`harness/reorg/base.json`:
```json
{
 "scan": ["helao", "harness", "*.py"],
 "moves": [
  ["helao/deploy/hte/servers/orchestrator", "helao/deploy/base/servers/orchestrator"],
  ["helao/deploy/hte/servers/operator", "helao/deploy/base/servers/operator"],
  ["helao/deploy/hte/servers/visualizer", "helao/deploy/base/servers/visualizer"],
  ["helao/deploy/hte/servers/sync", "helao/deploy/base/servers/sync"],
  ["helao/deploy/hte/servers/reflex", "helao/deploy/base/servers/reflex"]
 ]
}
```
Then move the folders on the filesystem. Do not use the tool's move mode, because it runs `git mv`, which writes the index:
```bash
cd $REPO
for r in orchestrator operator visualizer sync reflex; do
  find helao/deploy/hte/servers/$r -name __pycache__ -type d -prune -exec rm -rf {} +
done
rm -rf helao/deploy/hte/servers/visualizer/.ruff_cache   # untracked cache
mkdir -p helao/deploy/base/servers helao/deploy/base/tests/checklists
for r in orchestrator operator visualizer sync reflex; do
  mv helao/deploy/hte/servers/$r helao/deploy/base/servers/$r
done
mv helao/deploy/hte/tests/checklists/sync_server.json helao/deploy/base/tests/checklists/sync_server.json
```
Package shell. `helao/deploy/base/__init__.py`:
```python
"""Framework services every deployment launches.

The orchestrator (``async_orch2``), the standalone operator, the Bokeh
visualizers and data browser, the data syncer (``sync_server``) and the shared
Reflex panel helpers. They have the deployment shape (``servers/<role>/``) so
the launcher's cross-deployment module lookup finds them by bare name, and they
are tracked in this repository so a clone with no deployment checked out can
still launch a group.
"""
```
`helao/deploy/base/servers/__init__.py` and `helao/deploy/base/tests/__init__.py` are empty files.

`helao/deploy/base/README.md`:
```markdown
# base: framework services

Tracked in helao-async. Holds the server modules every deployment launches:
`orchestrator/` (async_orch2), `operator/` (standalone_operator), `visualizer/`
(action/live/control visualizers, data_browser, shared Bokeh panels), `sync/`
(sync_server) and `reflex/` (shared Reflex panel helpers). Configs name these
modules bare (`fast: async_orch2`); the launcher finds them here. A module name
in `base` must exist in no other deployment (`tests/test_base_modules_unique.py`).
Instrument servers and drivers live in their deployments, not here.
```
`.gitignore`: after `!helao/deploy/__init__.py`, add the line `!helao/deploy/base/`. The block becomes:
```
helao/deploy/*
!helao/deploy/__init__.py
!helao/deploy/base/
!helao/deploy/hte/
!helao/deploy/test/
```

- [ ] **Step 4: Rewrite imports, scanning only parent-owned roots**

`--rewrite-only` rewrites inside nested repos too, so never pass `--scan helao` here. That would edit the private repos, which is Task 4's job.
```bash
cd $REPO
for s in helao/deploy/base helao/deploy/hte helao/deploy/test helao/core helao/hexagon helao/helpers helao/ui harness; do
  PYTHONPATH=$REPO $PY -m harness.reorg_deploy --rewrite-only --scan $s harness/reorg/base.json
done | tee $D/rewrite.log
for d in $DEP_A $DEP_B $DEP_C $DEP_E $DEP_F; do git -C helao/deploy/$d status --short | head -3; done
```
Expected: the private repos show no new changes. The `LEFTOVER` lines in `$D/rewrite.log` are string literals and docstrings. Fix each one by hand: `helao.deploy.hte.servers.<moved role>` becomes `helao.deploy.base.servers.<moved role>`, and `deploy/hte/servers/<moved role>` becomes `deploy/base/servers/<moved role>`. The measured set:
- `helao/deploy/test/tests/test_data_browser.py:741` (`"helao.deploy.hte.servers.visualizer.data_browser"` → `"helao.deploy.base.servers.visualizer.data_browser"`);
- `helao/deploy/hte/tests/test_hte_builds_on_linux.py:126`;
- `helao/deploy/hte/tests/test_standalone_operator_mount.py:37`;
- `helao/deploy/hte/tests/test_standalone_operator.py:4,411`;
- `helao/deploy/base/servers/reflex/_pstat_panel.py:52`;
- `helao/deploy/hte/layouts/__init__.py:5`;
- the folder READMEs under `helao/deploy/base/servers/*/README.md`.

`helao/deploy/hte/tests/test_vis_gate_config.py:54,88-96` builds `helao.deploy.hte.servers.{group}.{bokeh}` and globs `hte/servers/visualizer`. Repoint both to `base` now, so the suite stays green. Task 2 moves that file.

Then run this check. Expected output: nothing.
```bash
cd $REPO; git -C $REPO ls-files -co --exclude-standard helao harness | grep '\.py$' | xargs grep -n -E "deploy[./]hte[./]servers[./](orchestrator|operator|visualizer|sync|reflex)\b"
```

- [ ] **Step 5: Fix the resolvers' parent tests that named `hte` for a moved or instrument module**

`helao/core/tests/test_framework_deployment_free.py:8`:
```python
ROOTS = ["helao/core", "helao/hexagon", "helao/helpers", "helao/ui", "harness", "helao/deploy/base"]
```
`helao/core/tests/test_server_modules.py:97-98`:
```python
def test_real_deploy_root_holds_base_and_test():
    assert {"base", "test"} <= set(sm.deployments())
```
`helao/core/tests/test_resolve_app_deployment.py:52-58`:
```python
def test_app_module_path_for_real_base_server():
    assert lb.app_module_path("base", "sync_server").endswith(".sync_server")


def test_app_module_path_missing_raises():
    with pytest.raises(FileNotFoundError, match="no_such_module"):
        lb.app_module_path("base", "no_such_module")
```
`helao/core/tests/test_reflex_config.py:121`: change `assert "hte" in order` to `assert "base" in order`. Leave line 379 alone, because it asserts over a planted fake tree.

`helao/deploy/hte/tests/test_hte_builds_on_linux.py`: `sync_server` is no longer an `hte` module. Add below the imports:
```python
from helao.helpers import server_modules


def _owner(module: str) -> str:
    """hte for instrument servers, base for the framework services hte configs launch."""
    return server_modules.locate(module, "app", own="hte")[0]
```
Then replace `app_module_path("hte", module)` at lines 80 and 107 with `app_module_path(_owner(module), module)`.

- [ ] **Step 6: Split the sync route record verbatim, and pin `base` in configs (STOP: needs OQ-1; written for (a))**

Remove sync_server's entries from `hte`'s lists and put the identical JSON values in `base`'s. Run this from `$REPO`. It reads the HEAD versions and writes only the four list files. `sync_server.json` has already been moved by `mv`:
```bash
cd $REPO && PYTHONPATH=$REPO $PY - <<'EOF'
import json, subprocess
from pathlib import Path
H, B = Path("helao/deploy/hte/tests/checklists"), Path("helao/deploy/base/tests/checklists")
def head(p): return json.loads(subprocess.run(["git","-C",".","show",f"HEAD:{p}"],capture_output=True,check=True,text=True).stdout)
def dump(p, v): p.write_text(json.dumps(v, indent=1 if p.name == "servers.json" else 2) + "\n", encoding="utf-8")
srv = head(H/"servers.json"); keep=[e for e in srv["servers"] if e["module"]!="sync_server.py"]; moved=[e for e in srv["servers"] if e["module"]=="sync_server.py"]
assert len(moved)==1 and len(keep)==22
dump(H/"servers.json", {**srv, "servers": keep})
dump(B/"servers.json", {"_description": "Manifest of base's action-server modules, split verbatim from helao/deploy/hte/tests/checklists/servers.json on 2026-11-10.", "servers": moved})
at = head(H/"_at_b7c.json"); assert "sync_server" in at and len(at)==23
dump(H/"_at_b7c.json", [n for n in at if n!="sync_server"]); dump(B/"_at_b7c.json", ["sync_server"])
add = head(H/"_additions.json")
dump(H/"_additions.json", [a for a in add if a["module"]!="sync_server.py"]); dump(B/"_additions.json", [a for a in add if a["module"]=="sync_server.py"])
EOF
```
Before keeping the output, match the indentation and key order of the original files: `git -C $REPO diff -U0 helao/deploy/hte/tests/checklists` must show **only removed lines**. If it shows rewritten lines, change the `indent=` and `ensure_ascii=False` arguments of `dump` until it does. Then check that every value is preserved:
```bash
cd $REPO && PYTHONPATH=$REPO $PY - <<'EOF'
import json, subprocess
from pathlib import Path
H, B = "helao/deploy/hte/tests/checklists", "helao/deploy/base/tests/checklists"
def head(p): return json.loads(subprocess.run(["git","-C",".","show",f"HEAD:{p}"],capture_output=True,check=True,text=True).stdout)
def now(p): return json.loads(Path(p).read_text(encoding="utf-8"))
assert now(f"{B}/sync_server.json") == head(f"{H}/sync_server.json")
for f in ("_at_b7c.json", "_additions.json"):
    assert sorted(map(json.dumps, now(f"{H}/{f}") + now(f"{B}/{f}"))) == sorted(map(json.dumps, head(f"{H}/{f}"))), f
split = now(f"{H}/servers.json")["servers"] + now(f"{B}/servers.json")["servers"]
assert sorted(map(json.dumps, split)) == sorted(map(json.dumps, head(f"{H}/servers.json")["servers"]))
assert now(f"{H}/servers.json")["_description"] == head(f"{H}/servers.json")["_description"]
print("split verified")
EOF
```
`hte`'s gate literals follow the record. In `helao/deploy/hte/tests/test_route_checklist.py`:
- line 56: `assert len(SERVERS) == 22`;
- line 80: `FROZEN_PRIVATE_TOTAL = 71`, with the comment `#: 79 before sync_server's 8 private routes moved with it to helao/deploy/base (2026-11-10).`;
- line 313: `assert len(names) == 22, sorted(names)`.

`FROZEN_ACTION_TOTAL` stays 166, because sync_server has 0 action routes.

Config pins under OQ-1 (a). In the 19 `hte` files listed in OQ-1, change `deployment: hte` to `deployment: base` **only on the server whose `fast:`/`bokeh:` is a moved module**:
```bash
cd $REPO && PYTHONPATH=$REPO $PY - <<'EOF'
import re
from pathlib import Path
from ruamel.yaml import YAML
MOVED = {"async_orch2","standalone_operator","action_visualizer","live_visualizer","control_visualizer","data_browser","sync_server"}
for p in sorted(Path("helao/deploy/hte").glob("**/configs/*.yml")):
    data = YAML(typ="safe").load(p.read_text(encoding="utf-8")) or {}
    keys = [k for k, s in (data.get("servers") or {}).items() if isinstance(s, dict) and (s.get("fast") or s.get("bokeh")) in MOVED and s.get("deployment") == "hte"]
    if keys: print(p, keys)
EOF
```
Edit each listed server block by hand (text edit, one line per block), so comments and order survive.

- [ ] **Step 7: Run the gate tests, the touched suites and the mutation checks**

Run:
```bash
cd $REPO && PYTHONPATH=$REPO $PY -m pytest -q -p no:cacheprovider helao/deploy/base/tests helao/deploy/hte/tests/test_route_checklist.py helao/deploy/hte/tests/test_hte_builds_on_linux.py helao/core/tests/test_framework_deployment_free.py helao/core/tests/test_server_modules.py helao/core/tests/test_resolve_app_deployment.py helao/core/tests/test_reflex_config.py helao/hexagon/tests/test_preflight.py harness/tests/test_freeze.py helao/deploy/test/tests/test_data_browser.py
```
Expected: PASS. Private-repo pins still fail `test_no_config_pins_hte_for_a_base_module` until Task 4. Run it with `-k "not pins"` now, and record that the remaining failures are only `$DEP_*` paths.

Mutation checks:
1. `cp helao/deploy/base/servers/sync/sync_server.py helao/deploy/test/servers/action/sync_server.py`. Expected: `test_module_exists_in_base_only[app:sync_server]` fails. Then `rm` the copy.
2. Add the line `    @app.post("/tasks_extra", tags=["private"])` above an existing private route in `base/servers/sync/sync_server.py`, with no `_additions.json` entry. Expected: `test_sync_server_matches_its_frozen_checklist` fails. Revert.

- [ ] **Step 8: Black, pyright, gates**

Run `black` and `pyright` on the changed `.py` files, both golden-master `--check` commands and the Standard sweep (Global Constraints). Expected: 0 failures, except the `pins` test, which waits for Task 4. If any other test fails, fix it before handing off.

- [ ] **Step 9: Commit (controller)**

Parent repo. Stage the deletions under `helao/deploy/hte/servers/{orchestrator,operator,visualizer,sync,reflex}` and the new `helao/deploy/base/` together, so git records renames. Message: `refactor(base): move framework services from hte into tracked helao/deploy/base`. The body carries the dependency-closure list above and the route-record split numbers (`hte` 23→22 modules, 79→71 private routes).

---

### Task 2: Move the tests that follow the services into `base/tests`

**Files:**
- Move to `helao/deploy/base/tests/` (filesystem `mv`): `helao/deploy/hte/tests/{test_sync_port_wiring,test_sync_server_recovery,test_standalone_operator,test_standalone_operator_mount,test_factory,test_prc_colocation,test_vis_gate_config,test_reflex_action_panels,test_reflex_live_panels,test_reflex_spec_sample_panels}.py`
- Create: `helao/deploy/hte/tests/test_reflex_instrument_panels.py`, `helao/deploy/base/tests/test_live_vis_ws_parity.py`, `helao/deploy/hte/tests/test_hte_vis_imports.py`
- Modify: `helao/deploy/hte/tests/test_vis_ws_parity.py:115-140,160-200,372-373`; `helao/deploy/base/tests/test_sync_port_wiring.py:280` (id `"hte"` → `"base"`)

**Interfaces:**
- Consumes: the Task 1 import root `helao.deploy.base.servers.*`.
- Produces: `helao.deploy.base.tests.test_live_vis_ws_parity` exports `_FakeVis`, `_servers`, `_build`, `_decoded_live`, `_decoded_data`, which `hte`'s `test_vis_ws_parity.py` imports.

Rule for every file moved here: after the move, it must import nothing from `helao.deploy.hte` (`test_framework_deployment_free` checks this now that `helao/deploy/base` is in its ROOTS). A test that needs an `hte` module goes to `hte`, as below.

- [ ] **Step 1: Move the files and run them where they now live**

```bash
cd $REPO
for f in test_sync_port_wiring test_sync_server_recovery test_standalone_operator test_standalone_operator_mount test_factory test_prc_colocation test_vis_gate_config test_reflex_action_panels test_reflex_live_panels test_reflex_spec_sample_panels; do
  mv helao/deploy/hte/tests/$f.py helao/deploy/base/tests/$f.py
done
PYTHONPATH=$REPO $PY -m pytest -q -p no:cacheprovider helao/core/tests/test_framework_deployment_free.py
```
Expected: FAIL. The messages list `import helao.deploy.hte.servers.{nidaqmx,power_supply,co2sensor,mfc,sample,spec}.reflex...` inside the three moved reflex-panel test files. These are the failing tests for the next step.

- [ ] **Step 2: Cut the instrument-panel cases out into `hte`**

Move these functions verbatim from the base files into `helao/deploy/hte/tests/test_reflex_instrument_panels.py`, keeping their bodies:
- from `test_reflex_action_panels.py`: `test_every_action_panel_exposes_the_contract`, `test_the_action_panels_do_not_share_a_state_class`, `test_action_panel_ids_are_distinct_per_panel_and_session`, `test_nidaqmx_declares_the_columns_its_server_streams`;
- from `test_reflex_live_panels.py`: `test_every_live_panel_exposes_the_contract`, `test_each_panel_declares_its_own_axis_label`, `test_the_panels_do_not_share_a_state_class`, `test_panel_ids_are_distinct_per_panel_and_session`;
- from `test_reflex_spec_sample_panels.py`: `test_both_panels_expose_the_contract`, `test_they_do_not_share_a_state_class`.

Give the new file a module docstring: `"""Reflex contract checks for hte's instrument panels; the shared helpers' own tests are in helao/deploy/base/tests."""`. Copy any module-level imports or helpers those functions use. Their in-function imports of `pressure_vis`/`temp_vis` already read `helao.deploy.base.servers.reflex` after Task 1.

The four live cases mix base and `hte` panels, so the base file keeps a base-only contract check. Append to `helao/deploy/base/tests/test_reflex_live_panels.py`:
```python
def test_the_base_live_panels_expose_the_contract():
    from helao.deploy.base.servers.reflex import pressure_vis, temp_vis

    for module in (pressure_vis, temp_vis):
        assert module.WS_PATH == "ws_live"
        assert callable(module.build)
        assert getattr(module.STATE_BASE, "_mixin", False), module.__name__
    assert pressure_vis.Y_LABEL != temp_vis.Y_LABEL
    assert pressure_vis.STATE_BASE is not temp_vis.STATE_BASE
    assert pressure_vis.panel_id("P", "tok") != temp_vis.panel_id("P", "tok")
```

- [ ] **Step 3: Split the two visualizer tests that sweep both trees**

`helao/deploy/base/tests/test_vis_gate_config.py`: set `_SERVERS` to `helao/deploy/base/servers` and keep only the `visualizer/*.py` glob in `_VIS_MODULES`. Remove the `*/bokeh/*.py` term, because `base` has no instrument bokeh folders.

Create `helao/deploy/hte/tests/test_hte_vis_imports.py`, which keeps the instrument half of that sweep:
```python
"""Every hte instrument Bokeh panel (servers/*/bokeh/*.py) imports on Linux.

The base visualizers have the same check in helao/deploy/base/tests/test_vis_gate_config.py.
"""

import importlib
from pathlib import Path

import pytest

from helao.helpers.server_modules import import_path

SERVERS = Path(__file__).resolve().parents[1] / "servers"
MODULES = sorted(p for p in SERVERS.glob("*/bokeh/*.py") if p.name != "__init__.py")


def test_the_sweep_is_not_vacuous():
    assert len(MODULES) >= 9, MODULES


@pytest.mark.parametrize("path", MODULES, ids=[p.stem for p in MODULES])
def test_hte_bokeh_panel_imports_on_linux(path):
    importlib.import_module(import_path(path))
```
Before writing the `>= 9` floor, check it against `ls helao/deploy/hte/servers/*/bokeh/*.py | grep -v __init__ | wc -l` and use the measured number.

`hte`'s `test_vis_ws_parity.py`: move `_FakeVis`, `_servers`, `_build`, `_decoded_live`, `_decoded_data`, `test_temp_vis_ingests_recognized_and_raises_on_unrecognized` and `test_pressure_vis_ingests_recognized_and_raises_on_unrecognized` into the new `helao/deploy/base/tests/test_live_vis_ws_parity.py`, with these changes in the base file:
```python
def _import(modname):
    return importlib.import_module(import_path(module_file("base", modname, "bokeh")))


def test_both_base_live_visualizers_define_add_points():
    servers = Path(__file__).resolve().parents[1] / "servers"
    found = {p.stem for p in servers.glob("visualizer/*.py") if "def add_points" in p.read_text(encoding="utf-8")}
    assert found == {"pressure_vis", "temp_vis"}, found
```
In `hte`'s file:
- add `from helao.deploy.base.tests.test_live_vis_ws_parity import _FakeVis, _servers, _build, _decoded_live, _decoded_data`;
- in `test_targeted_module_set_matches_disk_and_is_documented`, glob only `*/bokeh/*.py` and assert `len(found) == 9` and `len(tested) == 7`;
- reword its docstring and the module docstring's counts (11→9, 9→7), adding the sentence `pressure_vis and temp_vis moved to helao/deploy/base (tests in base/tests/test_live_vis_ws_parity.py).`;
- delete the two moved calls from the `__main__` block.

- [ ] **Step 4: Run and mutation-check**

Run:
```bash
cd $REPO && PYTHONPATH=$REPO $PY -m pytest -q -p no:cacheprovider helao/deploy/base/tests helao/deploy/hte/tests/test_reflex_instrument_panels.py helao/deploy/hte/tests/test_hte_vis_imports.py helao/deploy/hte/tests/test_vis_ws_parity.py helao/core/tests/test_framework_deployment_free.py
```
Expected: PASS. Then count tests: `PYTHONPATH=$REPO $PY -m pytest --collect-only -q <the moved, new and edited files>` at HEAD and now. The total must be equal plus the 3 new base checks (`test_the_base_live_panels_expose_the_contract`, `test_both_base_live_visualizers_define_add_points`, `test_the_sweep_is_not_vacuous`), with nothing lost.

Mutations:
- In `base/servers/reflex/temp_vis.py`, set `WS_PATH = "ws_data"`. Expected: `test_the_base_live_panels_expose_the_contract` fails. Revert.
- Add `from helao.deploy.hte.servers.mfc.reflex import mfc_vis` at the top of `base/tests/test_factory.py`. Expected: `test_framework_names_no_deployment` fails. Revert.

- [ ] **Step 5: Gates and commit (controller)**

Run black, pyright, the golden masters and the Standard sweep. Commit to the parent: `test(base): move orchestrator/operator/visualizer/syncer tests with their services`.

---

### Task 3: Base-API surface checklist and living-doc references

**Files:**
- Move: `helao/deploy/hte/tests/checklists/_baseapi_system_surface.json` and `.md` → `helao/hexagon/tests/checklists/`
- Modify: `helao/hexagon/tests/test_action_host_surface.py:19`; `helao/hexagon/app/action_host.py:1081`; `helao/hexagon/tests/checklists/_baseapi_system_surface.md:39,81-82`; `helao/deploy/base/servers/sync/sync_server.py:272-273`; `CLAUDE.md` (Three-layer layout, the paragraph "Known deployments: `hte` ... `test`"); `helao/deploy/__init__.py` docstring; `helao/deploy/hte/__init__.py` docstring

**Interfaces:**
- Produces: `helao/hexagon/tests/checklists/_baseapi_system_surface.json` (the same bytes).

- [ ] **Step 1: Point the test at the new location and see it fail**

`helao/hexagon/tests/test_action_host_surface.py:19`:
```python
    REPO_ROOT / "helao/hexagon/tests/checklists/_baseapi_system_surface.json"
```
Run: `PYTHONPATH=$REPO $PY -m pytest -q -p no:cacheprovider helao/hexagon/tests/test_action_host_surface.py`
Expected: FAIL, `FileNotFoundError` on the new path.

- [ ] **Step 2: Move the files**

```bash
cd $REPO
mv helao/deploy/hte/tests/checklists/_baseapi_system_surface.json helao/hexagon/tests/checklists/
mv helao/deploy/hte/tests/checklists/_baseapi_system_surface.md helao/hexagon/tests/checklists/
cmp helao/hexagon/tests/checklists/_baseapi_system_surface.json <(git -C $REPO show HEAD:helao/deploy/hte/tests/checklists/_baseapi_system_surface.json) && echo identical
```
Expected: `identical`. The `.md` lines 39 and 81-82 name the old path. Change line 39 to the new path. Change lines 81-82 to `helao/deploy/<deployment>/tests/checklists/<module>.json`. `action_host.py:1081` already reads `checklists/_baseapi_system_surface.json`; make it `helao/hexagon/tests/checklists/_baseapi_system_surface.json` so it names the file unambiguously.

`sync_server.py:272-273`:
```python
        (``helao/deploy/base/tests/checklists/sync_server.json``) pins the route
        set, so a new route needs an entry in ``checklists/_additions.json`` there.
```

- [ ] **Step 3: Living docs**

- `CLAUDE.md`, Three-layer layout, `helao/deploy/<deployment>/` bullet: change "Known deployments: `hte` (production HTE stations), `test` (sims and demos). Only `hte` and `test` are tracked in this repo" to "Known deployments: `base` (framework services every group launches: orchestrator, operator, visualizers, data syncer, shared Reflex helpers), `hte` (production HTE stations) and `test` (sims and demos). Only `base`, `hte` and `test` are tracked in this repo". Leave the rest of the bullet.
- `helao/deploy/__init__.py`: change "This repository tracks ``hte`` (production stations) and ``test`` (sims and demos)" to "This repository tracks ``base`` (framework services), ``hte`` (production stations) and ``test`` (sims and demos)".
- `helao/deploy/hte/__init__.py`: change "Houses the configs, FastAPI/Bokeh servers, drivers, experiment and sequence libraries" to "Houses the configs, instrument servers, drivers, experiment and sequence libraries". The orchestrator, operator and visualizers are now in `base`.

- [ ] **Step 4: Run, mutation-check, gates, commit**

Run: `PYTHONPATH=$REPO $PY -m pytest -q -p no:cacheprovider helao/hexagon/tests/test_action_host_surface.py`. Expected: PASS.

Mutation: delete one key from a copy of the JSON, put the copy in place, and expect FAIL. Restore it with `cp` from `git -C $REPO show HEAD:...`, applied to the new path.

Run black, pyright, the golden masters and the Standard sweep. Commit to the parent: `test(hexagon): base-API surface checklist lives beside its gate`.

---

## Stage 2: private repos

### Task 4: Private repos follow `helao.deploy.base`

One commit per private repo, in that repo: `helao/deploy/$DEP_A`, `$DEP_B`, `$DEP_C`, `$DEP_E`, `$DEP_F`. Measured: only Deployment-E's Python imports moved modules (`reflex._spectra` in 3 files, `reflex._action` in 1). Config pins exist in A (1), B (2 files), C (1) and E (3 entries).

**Files:** in each `helao/deploy/$DEP_x`, the files the commands below print.

**Interfaces:**
- Consumes: `harness/reorg/base.json` (Task 1).

- [ ] **Step 1: Failing check**

Run: `cd $REPO && PYTHONPATH=$REPO $PY -m pytest -q -p no:cacheprovider helao/deploy/base/tests/test_base_modules_unique.py::test_no_config_pins_hte_for_a_base_module`
Expected: FAIL, listing the private pins. Note them in `$D/pins.txt`, which is untracked.

Run for each repo:
```bash
for d in $DEP_A $DEP_B $DEP_C $DEP_E $DEP_F; do git -C $REPO/helao/deploy/$d status --short; git -C $REPO/helao/deploy/$d rev-parse --abbrev-ref HEAD; done
```
Expected: clean trees. A repo with uncommitted work belongs to another session; **STOP** and report it, and do not edit that repo.

- [ ] **Step 2: Rewrite imports per repo**

```bash
cd $REPO
for d in $DEP_A $DEP_B $DEP_C $DEP_E $DEP_F; do
  PYTHONPATH=$REPO $PY -m harness.reorg_deploy --rewrite-only --scan helao/deploy/$d harness/reorg/base.json | tee $D/rewrite-$d.log
done
grep -rn -E "deploy[./]hte[./]servers[./](orchestrator|operator|visualizer|sync|reflex)\b" helao/deploy/$DEP_A helao/deploy/$DEP_B helao/deploy/$DEP_C helao/deploy/$DEP_E helao/deploy/$DEP_F --include='*.py' --include='*.yml' --include='*.md' | grep -v -E '/(\.ua|docs|\.omc)/'
```
Fix each `LEFTOVER` and each remaining hit by hand. Leave historical dated docs (`docs/`) and generated graph files (`.ua/`) alone.

- [ ] **Step 3: Rewrite the config pins (STOP: needs OQ-1; written for (a))**

In each file listed in `$D/pins.txt`, change `deployment: hte` to `deployment: base` on the listed server only. In Deployment-E's config, also reword the comment block above `servers:` that explains the `hte` pins. It must say that framework services pin `deployment: base` and instrument servers pin `deployment: hte`. Its own `CLAUDE.md` sentence about the `ANDOR` pin stays, because ANDOR is an instrument.

- [ ] **Step 4: Verify each repo**

```bash
cd $REPO
PYTHONPATH=$REPO $PY -m pytest -q -p no:cacheprovider helao/deploy/base/tests/test_base_modules_unique.py
for d in $DEP_A $DEP_B $DEP_C $DEP_E $DEP_F; do
  PYTHONPATH=$REPO $PY -c "import importlib,pkgutil,helao.deploy.$d as m; [importlib.import_module(n) for _,n,_ in pkgutil.walk_packages(m.__path__, m.__name__+'.') if '.tests' not in n and '.notes' not in n]" 2>&1 | tail -1
done
PYTHONPATH=$REPO $PY -c "from helao.hexagon import preflight; import sys; sys.exit(preflight.main(['$(basename $(ls helao/deploy/$DEP_E/configs/*.yml | head -1) .yml)']))"
```
Expected: the pins test passes. Each import walk prints nothing, or only third-party `ModuleNotFoundError` for Windows-only vendor SDKs. Compare against the same walk at the repo's HEAD: no new `helao*` import error. Preflight exits 0 for Deployment-E's config. Then run the Standard sweep.

Mutation: revert one private pin to `hte`. Expected: the pins test fails. Restore it.

- [ ] **Step 5: Commit (controller), one per repo**

`refactor: import framework services from helao.deploy.base`. Push these only after the parent's Stage-1 commits are pushed (push order step 2 before step 3).

---

## Stage 3: environment split

### Task 5: Audit the root env against its importers

**Files:**
- Create: `docs/superpowers/plans/2026-11-10-hte-env-audit.md` (tracked; private deployments collapsed to `private`)
- Scratch: `$D/env_audit.py` (untracked)

**Interfaces:**
- Produces: the audit table that Task 6 applies. Each row is `package | source file | import names | used by | class | destination`, where class is one of `framework`, `base`, `hte-server:<folder>`, `hte-shared`, `private-only`, `tooling`, `unused`.

- [ ] **Step 1: Write the audit script**

`$D/env_audit.py`:
```python
"""Root env packages -> who imports them. Usage: python env_audit.py <repo>"""

import ast
import re
import sys
from collections import defaultdict
from importlib.metadata import packages_distributions
from pathlib import Path

from ruamel.yaml import YAML

REPO = Path(sys.argv[1])
DEPLOY = REPO / "helao" / "deploy"


def norm(n):
    return re.sub(r"[-_.]+", "-", n).lower()


def root_packages():
    pk = {}
    for f in ("helao_dev_linux-64.yml", "helao_dev_win-64.yml"):
        for d in YAML(typ="safe").load((REPO / f).read_text(encoding="utf-8"))["dependencies"]:
            if isinstance(d, str):
                name = re.split(r"[<>=! ]", d.split("::")[-1])[0]
                pk.setdefault(norm(name), set()).add(f)
            else:
                for p in d.get("pip", []):
                    pk.setdefault(norm(re.split(r"[<>=!\[ ]", p)[0]), set()).add(f + ":pip")
    for line in (REPO / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            name = line.rsplit("/", 3)[-3] if line.startswith("http") else re.split(r"[<>=!\[ ]", line)[0]
            pk.setdefault(norm(name), set()).add("requirements.txt")
    return pk


def zone(path: Path) -> str:
    rel = path.relative_to(REPO).parts
    if rel[:2] != ("helao", "deploy") or len(rel) < 4:
        return "framework"
    dep = rel[2]
    if dep in ("base", "test"):
        return dep
    if dep != "hte":
        return "private"
    if rel[3] == "servers" and len(rel) > 5:
        return f"hte-server:{rel[4]}"
    return "hte-shared"


def imports_by_zone():
    out = defaultdict(set)
    roots = [REPO / "helao", REPO / "harness", *REPO.glob("*.py")]
    files = [p for r in roots for p in ([r] if r.is_file() else r.rglob("*.py"))]
    for p in files:
        if {"__pycache__", "node_modules", ".web", ".omc", ".ua"} & set(p.parts):
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for n in ast.walk(tree):
            names = [a.name for a in n.names] if isinstance(n, ast.Import) else [n.module] if isinstance(n, ast.ImportFrom) and n.level == 0 and n.module else []
            for m in names:
                out[m.split(".")[0]].add(zone(p))
    return out


dist2imp = defaultdict(set)
for imp, dists in packages_distributions().items():
    for d in dists:
        dist2imp[norm(d)].add(imp)
used = imports_by_zone()
for pkg, src in sorted(root_packages().items()):
    imps = sorted(dist2imp.get(pkg, ())) or ["UNMAPPED"]
    zones = sorted({z for i in imps for z in used.get(i, ())})
    print(f"{pkg}\t{','.join(sorted(src))}\t{','.join(imps)}\t{','.join(zones) or '-'}")
```

- [ ] **Step 2: Run it**

Run: `cd $REPO && PYTHONPATH=$REPO $PY $D/env_audit.py $REPO > $D/audit.tsv; wc -l $D/audit.tsv; grep -c UNMAPPED $D/audit.tsv`
Expected: one row per root package (about 80). `UNMAPPED` rows are conda packages that are not Python distributions in this env, or whose distribution metadata differs.

- [ ] **Step 3: Resolve by hand and classify**

For each `UNMAPPED` or `-` row, find the importer by grep, for example `grep -rn "import serial" helao` for `pyserial`. Record how it was matched. Packages used as tools rather than imports are class `tooling` and stay in root: `python`, `pip`, `setuptools`, `uv`, `git`, `nodejs`, `black`, `docformatter`, `pyright`, `pytest-asyncio`, `pytest-xdist`, `ipykernel`, `jupyterlab`, `zeromq`, and any package the launcher or `helao_env.py` shells out to.

Apply the classes in this order:
1. Imported by any `framework`, `base` or `test` zone → `framework`/`base`, stays in root.
2. Imported only by `hte-server:<folder>` zones and no `hte-shared` code → `hte-server:<folder>`. If two server folders use it, both get an entry.
3. Imported by `hte-shared` code (experiments, sequences, processors, layouts, drivers, specifications, `hte/tests`) and no framework/base/test zone → `hte-shared`.
4. Imported by `private` zones and not by framework/base/test → `private-only`, stays in root (OQ-4).
5. Imported by nothing → `unused`, stays in root. Removal is out of scope.

A conda package keeps conda as its destination (`environment.yml`); a `requirements.txt` or pip package keeps pip (`requirements.txt`). A package listed only in `helao_dev_win-64.yml` (`comtypes`) goes to that folder's `environment_win-64.yml`. Check the folder's existing env files first, because Gamry, NI-DAQmx, TEC and PAL already carry some. If a package is already listed there, the move is only a removal from root.

- [ ] **Step 4: Write the audit doc**

`docs/superpowers/plans/2026-11-10-hte-env-audit.md` has:
- a one-paragraph method (this task's Steps 1-3);
- the full table;
- a "Moves" list (package → destination file);
- the decision for the deployment-root rule: "hte-shared packages: N; the `helao_env.py` deployment-root rule is (needed | skipped)".

Private deployments appear only as `private`. Check with `grep -n -i -E "$DEP_A|$DEP_B|$DEP_C|$DEP_E|$DEP_F" <doc>`, which must print nothing.

- [ ] **Step 5: Commit (controller)**

Parent: `docs: root env audit for the hte split`. This task changes no code, so there is no sweep.

---

### Task 6: Apply the env split (and the deployment-root rule only if the audit needs it)

**Files:**
- Modify: `helao_dev_linux-64.yml`, `helao_dev_win-64.yml`, `requirements.txt`, the `hte` server env files named in the audit's Moves list; `helao_pinned_linux-64.yml`, `helao_pinned_win-64.yml`, `requirements_pinned_linux-64.txt`, `requirements_pinned_win-64.txt` (re-solved, never hand-edited)
- If hte-shared > 0: create `helao/deploy/hte/environment.yml` and/or `helao/deploy/hte/requirements.txt`, modify `helao_env.py:84-109` (`server_folders`), test `helao/core/tests/test_helao_env.py`

**Interfaces:**
- Produces (only if hte-shared > 0): `helao_env.deployment_env_root(module_path: Path) -> Path | None`, the deployment root `module_path.parents[2]` when it holds `environment.yml`, `environment_<platform>.yml` or `requirements.txt`, else `None`.

- [ ] **Step 1 (only if hte-shared > 0): Failing test**

Append to `helao/core/tests/test_helao_env.py`:
```python
def test_a_deployment_root_with_env_files_is_an_env_folder(tmp_path):
    mod = tmp_path / "dep" / "servers" / "inst" / "inst_server.py"
    mod.parent.mkdir(parents=True)
    mod.write_text("", encoding="utf-8")
    assert he.deployment_env_root(mod) is None
    (tmp_path / "dep" / "requirements.txt").write_text("x\n", encoding="utf-8")
    assert he.deployment_env_root(mod) == tmp_path / "dep"
```
Run: `PYTHONPATH=$REPO $PY -m pytest -q -p no:cacheprovider helao/core/tests/test_helao_env.py -k deployment_root`
Expected: FAIL, `AttributeError: module 'helao_env' has no attribute 'deployment_env_root'`.

- [ ] **Step 2 (only if hte-shared > 0): Implement**

In `helao_env.py`, above `server_folders`:
```python
def deployment_env_root(module_path: Path) -> Path | None:
    """The deployment root of a server module, when it carries env files.

    A deployment's non-server code (experiments, sequences, processors) has no
    server folder of its own, so its packages live at the deployment root and
    are installed whenever a config launches any server from that deployment.
    """
    root = Path(module_path).parents[2]
    names = ("environment.yml", f"environment_{platform_tag()}.yml", "requirements.txt")
    return root if any((root / n).is_file() for n in names) else None
```
In `server_folders`, after `folders.add(path.parent)`:
```python
        root = deployment_env_root(path)
        if root is not None:
            folders.add(root)
```
Mutation: return `None` unconditionally, and the test fails. Revert.

- [ ] **Step 3: Move the packages**

Follow the audit's Moves list:
- remove each moved package line from `helao_dev_linux-64.yml`, `helao_dev_win-64.yml` and `requirements.txt`;
- add it to the destination file, creating that folder's `environment.yml` with `channels: [conda-forge]` and `dependencies: [...]`, or its `requirements.txt`, when absent.

Keep the version specifiers exactly as they were in root.

- [ ] **Step 4: Re-solve the pins**

```bash
cd $REPO
PYTHONPATH=$REPO $PY repin_envs.py | tee $D/repin-dry.txt          # report only
PYTHONPATH=$REPO $PY repin_envs.py --write | tee $D/repin-write.txt
for p in linux-64 win-64; do
  PYTHONPATH=$REPO $PY - "$p" > $D/pins-$p.txt <<'EOF'
import sys
from ruamel.yaml import YAML
d = YAML(typ="safe").load(open(f"helao_pinned_{sys.argv[1]}.yml", encoding="utf-8"))
print(" ".join(x if "==" in x or "=" not in x else x.replace("=", "==", 1) for x in d["dependencies"] if isinstance(x, str)))
EOF
  conda create --dry-run --solver=rattler --platform $p -n repin-check -c conda-forge $(cat $D/pins-$p.txt) > $D/solve-$p.log 2>&1; echo "$p rc=$?"
done
```
Expected: both `rc=0`. Every package removed from root is absent from the new pins, and nothing else changed version. Compare with `git -C $REPO diff helao_pinned_*.yml requirements_pinned_*.txt`. If an unrelated version moved, revert that line and note it in the commit. In `$D/solve-win-64.log`, check that the Windows-only vendor packages still solve.

- [ ] **Step 5: Verify the env behaviour**

```bash
cd $REPO
PYTHONPATH=$REPO $PY helao_env.py setup --dry-run hte/eche10 | tee $D/eche10-dry.txt
```
Expected: the printed `conda dependencies:` and `uv pip install -r` lines include every package the audit moved for eche10's servers. The fresh root-only env check is in Task 10 Step 3, where a parent-only clone exists. Run the Standard sweep and the golden masters.

- [ ] **Step 6: Commit (controller)**

Parent: `build(env): hte-only packages move to hte server folders; repin`.

---

## Stage 4: `setup_env` / `update_env` clone or pull `hte`

### Task 7: `hte_state` and `ensure_hte`, tested against a local bare repo

**Files:**
- Modify: `helao_env.py` (new constants and functions after `STATES_FILE`)
- Test: `helao/core/tests/test_helao_env.py`

**Interfaces:**
- Produces:
  - `HTE_URL: str = "https://github.com/High-Throughput-Experimentation/helao-hte-deployment.git"`. This is the URL's only definition.
  - `hte_state(deploy_root: Path = DEPLOY_ROOT, repo_root: Path = REPO_ROOT) -> str`, returning one of `"repo"`, `"tracked"`, `"leftover"`, `"missing"`.
  - `ensure_hte(deploy_root: Path = DEPLOY_ROOT, repo_root: Path = REPO_ROOT, url: str = HTE_URL, runner=_run, dry_run: bool = False) -> str`, returning one of `"pulled"`, `"cloned"`, `"replaced"`, `"tracked"`. It raises `subprocess.CalledProcessError` when git refuses.

- [ ] **Step 1: Write the failing tests**

Append to `helao/core/tests/test_helao_env.py`:
```python
import subprocess

_REAL_ENSURE_HTE = he.ensure_hte if hasattr(he, "ensure_hte") else None
_REAL_HTE_STATE = he.hte_state if hasattr(he, "hte_state") else None


@pytest.fixture(autouse=True)
def _no_network_hte(monkeypatch):
    """No test may clone or pull the real hte remote; opt in by calling _REAL_*."""

    def refuse(**kw):
        raise AssertionError("ensure_hte called without a test stub")

    if hasattr(he, "ensure_hte"):
        monkeypatch.setattr(he, "ensure_hte", refuse)
        monkeypatch.setattr(he, "hte_state", lambda *a, **k: "tracked")


def _git(*args, cwd):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-C", str(cwd), *args], check=True, capture_output=True)


@pytest.fixture()
def remote(tmp_path, monkeypatch):
    """A bare repo standing in for helao-hte-deployment, plus a work clone to push from.

    Restores the real hte_state, which the autouse fixture stubs: the real
    ensure_hte calls it through the module global."""
    monkeypatch.setattr(he, "hte_state", _REAL_HTE_STATE)
    src = tmp_path / "src"
    src.mkdir()
    _git("init", "-b", "main", cwd=src)
    (src / "servers").mkdir()
    (src / "servers" / "__init__.py").write_text("", encoding="utf-8")
    (src / "README.md").write_text("v1\n", encoding="utf-8")
    _git("add", "-A", cwd=src)
    _git("commit", "-m", "init", cwd=src)
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "clone", "--bare", str(src), str(bare)], check=True, capture_output=True)
    _git("remote", "add", "origin", str(bare), cwd=src)
    return bare, src


def _push(src, name, text):
    (src / name).write_text(text, encoding="utf-8")
    _git("add", "-A", cwd=src)
    _git("commit", "-m", name, cwd=src)
    _git("push", "origin", "main", cwd=src)


def test_hte_state_names_all_four_shapes(tmp_path, remote):
    deploy = tmp_path / "parent" / "helao" / "deploy"
    deploy.mkdir(parents=True)
    parent = tmp_path / "parent"
    _git("init", "-b", "main", cwd=parent)
    assert _REAL_HTE_STATE(deploy, parent) == "missing"
    (deploy / "hte").mkdir()
    (deploy / "hte" / "x.py").write_text("", encoding="utf-8")
    assert _REAL_HTE_STATE(deploy, parent) == "leftover"
    _git("add", "-A", cwd=parent)
    _git("commit", "-m", "track hte", cwd=parent)
    assert _REAL_HTE_STATE(deploy, parent) == "tracked"
    (deploy / "hte" / ".git").mkdir()
    assert _REAL_HTE_STATE(deploy, parent) == "repo"


def test_ensure_hte_clones_when_missing(tmp_path, remote):
    bare, _ = remote
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    assert _REAL_ENSURE_HTE(deploy, tmp_path, url=str(bare)) == "cloned"
    assert (deploy / "hte" / ".git").exists()
    assert (deploy / "hte" / "README.md").read_text(encoding="utf-8") == "v1\n"


def test_ensure_hte_pulls_an_existing_repo_and_never_deletes_it(tmp_path, remote):
    bare, src = remote
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    subprocess.run(["git", "clone", str(bare), str(deploy / "hte")], check=True, capture_output=True)
    marker = deploy / "hte" / "station_local.txt"  # untracked: survives a pull, not a re-clone
    marker.write_text("keep", encoding="utf-8")
    _push(src, "new.txt", "v2\n")
    assert _REAL_ENSURE_HTE(deploy, tmp_path, url=str(bare)) == "pulled"
    assert (deploy / "hte" / "new.txt").is_file()
    assert marker.read_text(encoding="utf-8") == "keep"


def test_ensure_hte_logs_and_replaces_a_leftover(tmp_path, remote, capsys):
    bare, _ = remote
    deploy = tmp_path / "deploy"
    left = deploy / "hte"
    (left / "servers" / "__pycache__").mkdir(parents=True)
    (left / "servers" / "__pycache__" / "a.cpython-314.pyc").write_bytes(b"\0")
    (left / "configs").mkdir()
    (left / "configs" / "station_local.yml").write_text("x: 1\n", encoding="utf-8")
    assert _REAL_ENSURE_HTE(deploy, tmp_path, url=str(bare)) == "replaced"
    err = capsys.readouterr().err
    assert "station_local.yml" in err and ".pyc" not in err
    assert (left / ".git").exists() and not (left / "configs" / "station_local.yml").exists()


def test_ensure_hte_dry_run_changes_nothing(tmp_path, remote, capsys):
    bare, _ = remote
    deploy = tmp_path / "deploy"
    (deploy / "hte").mkdir(parents=True)
    (deploy / "hte" / "keep.txt").write_text("k", encoding="utf-8")
    assert _REAL_ENSURE_HTE(deploy, tmp_path, url=str(bare), dry_run=True) == "replaced"
    assert (deploy / "hte" / "keep.txt").is_file() and not (deploy / "hte" / ".git").exists()
    assert "git clone" in capsys.readouterr().out


def test_ensure_hte_leaves_a_tracked_folder_alone(tmp_path, remote):
    """Before the cutover the developer's hte has no .git and is tracked: never touch it."""
    bare, _ = remote
    parent = tmp_path / "parent"
    deploy = parent / "helao" / "deploy"
    (deploy / "hte").mkdir(parents=True)
    (deploy / "hte" / "x.py").write_text("tracked\n", encoding="utf-8")
    _git("init", "-b", "main", cwd=parent)
    _git("add", "-A", cwd=parent)
    _git("commit", "-m", "track", cwd=parent)
    assert _REAL_ENSURE_HTE(deploy, parent, url=str(bare)) == "tracked"
    assert (deploy / "hte" / "x.py").read_text(encoding="utf-8") == "tracked\n"
    assert not (deploy / "hte" / ".git").exists()


def test_a_local_edit_that_conflicts_makes_the_pull_refuse(tmp_path, remote):
    bare, src = remote
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    subprocess.run(["git", "clone", str(bare), str(deploy / "hte")], check=True, capture_output=True)
    (deploy / "hte" / "README.md").write_text("station edit\n", encoding="utf-8")
    _push(src, "README.md", "v2\n")
    with pytest.raises(subprocess.CalledProcessError):
        _REAL_ENSURE_HTE(deploy, tmp_path, url=str(bare))
    assert (deploy / "hte" / "README.md").read_text(encoding="utf-8") == "station edit\n"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=$REPO $PY -m pytest -q -p no:cacheprovider helao/core/tests/test_helao_env.py`
Expected: the 7 new tests fail with `TypeError: 'NoneType' object is not callable`, because `_REAL_ENSURE_HTE`/`_REAL_HTE_STATE` are `None`. The existing tests pass.

- [ ] **Step 3: Implement**

`helao_env.py`, after `STATES_FILE = ...`:
```python
#: The one place the hte deployment's remote is named (spec §3).
HTE_URL = "https://github.com/High-Throughput-Experimentation/helao-hte-deployment.git"
```
After `_run` and `_warn`, which are already defined above `install`:
```python
def hte_state(deploy_root: Path = DEPLOY_ROOT, repo_root: Path = REPO_ROOT) -> str:
    """What helao/deploy/hte is: its own clone, part of this checkout, a leftover, or absent.

    "tracked" is every checkout before the split: the folder has no .git but
    this repo tracks it, so it is the deployment, not a leftover.
    """
    hte = Path(deploy_root) / "hte"
    if (hte / ".git").exists():
        return "repo"
    if not hte.exists():
        return "missing"
    tracked = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "--error-unmatch", str(hte)],
        capture_output=True,
    )
    return "tracked" if tracked.returncode == 0 else "leftover"


def ensure_hte(
    deploy_root: Path = DEPLOY_ROOT,
    repo_root: Path = REPO_ROOT,
    url: str = HTE_URL,
    runner=_run,
    dry_run: bool = False,
) -> str:
    """Pull hte if it is a clone, clone it if missing, replace a leftover with a clone.

    A leftover is what a parent pull leaves after the split: __pycache__ plus any
    station-local files. Every non-cache file is logged before the folder is
    removed (user ruling), so nothing disappears unrecorded. A git refusal
    (local edits in the way) raises CalledProcessError and changes nothing.
    """
    hte = Path(deploy_root) / "hte"
    state = hte_state(deploy_root, repo_root)
    if state == "tracked":
        return "tracked"
    if dry_run:
        def runner(cmd, env=None):  # noqa: ARG001
            print("+ " + " ".join(cmd), flush=True)
    if state == "repo":
        runner(["git", "-C", str(hte), "pull"])
        return "pulled"
    verdict = "cloned"
    if state == "leftover":
        for p in sorted(hte.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc":
                _warn(f"removing leftover {p}")
        if dry_run:
            print(f"+ rm -r {hte}", flush=True)
        else:
            shutil.rmtree(hte)
        verdict = "replaced"
    runner(["git", "clone", url, str(hte)])
    return verdict
```
`_warn` is defined after `install` today. Move it above `hte_state`, so the order is `_run`, `pip_env_overrides`, `_child_env`, `_warn`, `hte_state`, `ensure_hte`, `install`.

- [ ] **Step 4: Run them to verify they pass, then mutation-check**

Run: `PYTHONPATH=$REPO $PY -m pytest -q -p no:cacheprovider helao/core/tests/test_helao_env.py`
Expected: PASS.

Mutations, one at a time, reverting each:
1. Make `hte_state` return `"leftover"` in place of `"tracked"`. Expected: `test_ensure_hte_leaves_a_tracked_folder_alone` fails.
2. In the `"repo"` branch, do `shutil.rmtree(hte)` and fall through to clone. Expected: `..._never_deletes_it` fails on the marker.
3. Drop the `p.suffix != ".pyc"` test. Expected: `..._replaces_a_leftover` fails.

- [ ] **Step 5: Gates and commit (controller)**

Run black, pyright, the golden masters and the Standard sweep. Commit to the parent: `feat(env): helao_env can clone, pull or replace helao/deploy/hte`.

---

### Task 8: Decide when `setup`/`update` act (STOP: needs OQ-2; written for the recommended rule)

**Files:**
- Modify: `helao_env.py` (`main` and two new functions)
- Test: `helao/core/tests/test_helao_env.py`

**Interfaces:**
- Consumes: `hte_state`, `ensure_hte` (Task 7).
- Produces:
  - `config_hte_use(config_path: Path, deploy_root: Path = DEPLOY_ROOT) -> str`, returning one of `"hte"`, `"none"`, `"unresolved"`;
  - `wants_hte(state: str, *, no_prefix: bool, unresolved: bool, uses_hte: bool) -> bool`.

- [ ] **Step 1: Write the failing tests**

```python
def _tree(tmp_path):
    for rel in ("own/servers/a/own_server.py", "hte/servers/g/g_server.py", "hte/servers/g/reflex/g_vis.py", "base/servers/orchestrator/async_orch2.py"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("", encoding="utf-8")
    (tmp_path / "own" / "configs").mkdir()
    return tmp_path


def _cfg(root, body):
    p = root / "own" / "configs" / "c.yml"
    p.write_text("root: x\nservers:\n" + body, encoding="utf-8")
    return p


def test_config_hte_use_reads_fast_modules(tmp_path):
    root = _tree(tmp_path)
    assert he.config_hte_use(_cfg(root, "  O:\n    group: orchestrator\n    fast: async_orch2\n"), root) == "none"
    assert he.config_hte_use(_cfg(root, "  G:\n    group: action\n    fast: g_server\n"), root) == "hte"
    assert he.config_hte_use(_cfg(root, "  N:\n    group: action\n    fast: nowhere_server\n"), root) == "unresolved"


def test_config_hte_use_counts_panels(tmp_path):
    root = _tree(tmp_path)
    body = "  O:\n    group: orchestrator\n    fast: async_orch2\n  UI:\n    group: visualizer\n    reflex: ui\n    action_vis: g_vis\n"
    assert he.config_hte_use(_cfg(root, body), root) == "hte"


def test_wants_hte_truth_table():
    w = he.wants_hte
    assert not w("tracked", no_prefix=True, unresolved=True, uses_hte=True)
    assert w("repo", no_prefix=False, unresolved=False, uses_hte=True)
    assert not w("repo", no_prefix=True, unresolved=False, uses_hte=False)
    for s in ("missing", "leftover"):
        assert w(s, no_prefix=True, unresolved=False, uses_hte=False)
        assert w(s, no_prefix=False, unresolved=True, uses_hte=False)
        assert not w(s, no_prefix=False, unresolved=False, uses_hte=False)


def _stub_install(monkeypatch):
    monkeypatch.setattr(he, "server_folders", lambda c: set())
    monkeypatch.setattr(he, "install", lambda folders, **k: [])
    monkeypatch.setattr(he, "record", lambda configs, **k: [])


def test_main_clones_hte_when_a_prefix_only_resolves_after_the_clone(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(he, "hte_state", lambda *a, **k: "missing")
    monkeypatch.setattr(he, "ensure_hte", lambda **k: calls.append(k) or "cloned")
    cfg = tmp_path / "c.yml"
    cfg.write_text("root: x\nservers: {}\n", encoding="utf-8")
    answers = iter([he.EnvSetupError("no config named 'eche10'"), cfg])

    def fake_resolve(arg, *a, **k):
        r = next(answers)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(he, "resolve_config", fake_resolve)
    monkeypatch.setattr(he, "config_hte_use", lambda c: "hte")
    _stub_install(monkeypatch)
    assert he.main(["setup", "eche10"]) == 0
    assert len(calls) == 1


def test_main_never_touches_a_tracked_hte(monkeypatch):
    monkeypatch.setattr(he, "hte_state", lambda *a, **k: "tracked")
    assert he.main(["setup"]) == 0  # the autouse stub raises if ensure_hte is reached


def test_update_replay_clones_hte_when_a_recorded_config_vanished(monkeypatch, tmp_path):
    calls = []
    gone = he.DEPLOY_ROOT / "hte" / "configs" / "eche10.yml"
    states = tmp_path / "setup_env_prefixes.json"
    states.write_text(json.dumps([str(gone)]), encoding="utf-8")
    monkeypatch.setenv(he.ENV_VAR, str(states))
    monkeypatch.setattr(he, "hte_state", lambda *a, **k: "leftover")
    monkeypatch.setattr(he, "ensure_hte", lambda **k: calls.append(k) or "replaced")
    monkeypatch.setattr(he, "_recorded_paths_exist", lambda: False)
    _stub_install(monkeypatch)
    he.main(["update"])
    assert len(calls) == 1
```
If `json` is not already imported at the top of the test file, add the import. `test_update_replay_...` sets `_recorded_paths_exist` to keep `stored_configs()` from finding the config in a pre-cutover tree, where `eche10.yml` does exist.

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=$REPO $PY -m pytest -q -p no:cacheprovider helao/core/tests/test_helao_env.py -k "hte_use or wants_hte or main_ or update_replay"`
Expected: FAIL with `AttributeError` (`config_hte_use`, `wants_hte`, `_recorded_paths_exist`), or `ensure_hte` called 0 times.

- [ ] **Step 3: Implement**

```python
_PANEL_KEYS = ("action_vis", "live_vis", "control_vis")


def config_hte_use(config_path: Path, deploy_root: Path = DEPLOY_ROOT) -> str:
    """"hte" if the config launches an hte server or panel, "unresolved" if a
    module resolves in no deployment present, else "none"."""
    from helao.helpers import server_modules
    from helao.helpers.config_loader import read_config

    path = Path(config_path).resolve()
    own = path.parents[1].name
    if own == "hte":
        return "hte"
    verdict = "none"
    for entry in (read_config(str(path)).get("servers") or {}).values():
        if not isinstance(entry, dict):
            continue
        if entry.get("deployment") == "hte":
            verdict = "hte"
        wanted = []
        if entry.get("fast") or entry.get("bokeh"):
            wanted.append((entry.get("fast") or entry.get("bokeh"), ("app",)))
        for key in _PANEL_KEYS:
            v = entry.get(key)
            for name in v if isinstance(v, list) else [v] if isinstance(v, str) else []:
                wanted.append((name, ("bokeh", "reflex")))
        for module, stacks in wanted:
            try:
                found = {d for s in stacks for d in server_modules.locate(module, s, own=own, deploy_root=deploy_root)[1]}
            except server_modules.AmbiguousModule:
                continue  # server_folders reports it with the server key
            if not found:
                return "unresolved"
            if own not in found and "hte" in found:
                verdict = "hte"
    return verdict


def wants_hte(state: str, *, no_prefix: bool, unresolved: bool, uses_hte: bool) -> bool:
    """Spec §3 'When it acts', with OQ-2's rule for an absent hte."""
    if state == "tracked":
        return False
    if state == "repo":
        return uses_hte
    return no_prefix or unresolved or uses_hte


def _recorded_paths_exist(env=os.environ) -> bool:
    """False when a recorded config under helao/deploy/hte is gone (the parent pull removed it)."""
    hte = (DEPLOY_ROOT / "hte").resolve()
    for states in _states_files(env):
        if states.is_file():
            for p in _load_states(states):
                if Path(p).resolve().is_relative_to(hte) and not Path(p).is_file():
                    return False
    return True
```
In `main`, replace the block from `if a.prefixes:` down to the first `return 0` (the "base env only" branch) with:
```python
        state = hte_state()
        acted = False

        def act():
            nonlocal acted, state
            if not acted:
                print(f"hte: {ensure_hte(dry_run=a.dry_run)}", flush=True)
                acted, state = True, hte_state()

        if a.prefixes:
            try:
                configs = [resolve_config(x) for x in a.prefixes]
            except EnvSetupError:
                if not wants_hte(state, no_prefix=False, unresolved=True, uses_hte=False):
                    raise
                act()
                configs = [resolve_config(x) for x in a.prefixes]
        elif a.mode == "update":
            if not _recorded_paths_exist() and wants_hte(
                state, no_prefix=False, unresolved=True, uses_hte=False
            ):
                act()
            configs = stored_configs()
        else:
            configs = []
        if not configs:
            if wants_hte(state, no_prefix=True, unresolved=False, uses_hte=False):
                act()
            # existing "base env only" messages and `return 0`, unchanged
```
After that block, and before `folders: set[Path] = set()`:
```python
        uses = {config_hte_use(c) for c in configs}
        if wants_hte(state, no_prefix=False, unresolved="unresolved" in uses, uses_hte="hte" in uses):
            act()
```
Leave the existing `if not configs:` messages in place under the new `act()` call.

- [ ] **Step 4: Run them to verify they pass, then mutation-check**

Run: `PYTHONPATH=$REPO $PY -m pytest -q -p no:cacheprovider helao/core/tests/test_helao_env.py`
Expected: PASS.

Mutations:
1. Drop the `_PANEL_KEYS` loop. Expected: `test_config_hte_use_counts_panels` fails.
2. Delete the `elif a.mode == "update"` act. Expected: `test_update_replay_...` fails.
3. Make `wants_hte` return `True` for `"tracked"`. Expected: `test_main_never_touches_a_tracked_hte` fails on the autouse stub.

- [ ] **Step 5: Real-tree smoke, gates, commit**

Run: `cd $REPO && PYTHONPATH=$REPO $PY helao_env.py setup --dry-run hte/eche10`
Expected: no `hte:` line, because the state is `tracked`. The output is otherwise unchanged from Task 6 Step 5.

`setup_env.sh`/`.bat` and `update_env.sh`/`.bat` need no change: they already call `helao_env.py setup|update "$@"` after the base env exists, and the logic lives there.

Run black, pyright, the golden masters and the Standard sweep. Commit to the parent: `feat(env): setup/update clone or pull hte when a config needs it`.

---

## Stage 5: tests that need `hte` move into `hte`

### Task 9: Move the `hte` parts of parent tests, with thin `hte` tests (STOP: needs OQ-3; written for the recommended answer)

Every `hte` test below is a thin caller of a parent helper, so no sweep logic is copied.

**Files (parent → `hte`):**
- Move: `harness/tests/test_hte_collisions.py` → `helao/deploy/hte/tests/test_hte_collisions.py`; `harness/reorg/{hte,hte_tests,hte_tests2}.json` → `helao/deploy/hte/tests/reorg/`; `harness/tests/test_station_golden_capture.py` → `helao/deploy/hte/tests/test_station_golden_capture.py` (all 13 tests use the `hte` smoke helper)
- Create: `helao/deploy/hte/tests/test_motion_control_hte.py`, `helao/deploy/hte/tests/test_freeze_hte.py`, `helao/deploy/hte/tests/test_host_surfaces_hte.py`, `helao/deploy/hte/tests/test_preflight_hte.py`, `helao/deploy/hte/tests/test_hte_configs.py`
- Modify (parent):
  - `helao/core/tests/test_motion_control.py`: remove fixtures `adss3_motor`, `hispec_motor`, `eche10_kmotor`, `hispec_kmotor`, helpers `_tracked_hte_scales`, `_hte_server`, `HTE_CONFIG_GLOB`, and every test that uses them; fix the module docstring's "Fixture rule";
  - `harness/tests/test_freeze.py:153-210,232-252,289-299`;
  - `helao/hexagon/tests/test_driver_host_surface.py:28-32,82-85`;
  - `helao/hexagon/tests/test_external_composition_contract.py:160-226`;
  - `helao/hexagon/tests/test_preflight.py:13-17,294-327,355-399`;
  - `helao/core/tests/test_tooling_hygiene.py:53-57`;
  - `helao/hexagon/tests/test_reflex_gate_config.py:11-15,24-60`;
  - `helao/core/tests/unit_test_config_validation.py:26`;
  - `helao/core/tests/test_helao_env.py:72-81,84-93,228-234`

**Interfaces:**
- Consumes: parent helpers, imported by the `hte` tests:
  - `helao.hexagon.tests.test_driver_host_surface.scan(paths) -> tuple[list[str], int, set[str]]`;
  - `harness.hte_collisions.scan_collisions`;
  - `harness.freeze.freeze_deployment` and `freeze.verify_external`, with the `_external`/`_route` helpers from `harness.tests.test_freeze`;
  - `helao.hexagon.preflight.main` and `preflight_config`;
  - every non-fixture helper `test_motion_control.py` keeps.

- [ ] **Step 1: Failing check that the parent no longer needs `hte`**

Add to `helao/core/tests/test_framework_deployment_free.py`:
```python
def test_parent_tests_do_not_read_hte_by_path():
    """Tests that need hte live in hte (spec §2). Text mentions are allowed;
    a path or import a test would execute is not."""
    pat = re.compile(r"""["'][^"']*deploy[/\\]hte[/\\](configs|tests|servers|experiments|sequences)""")
    allowed = {"helao/core/tests/test_palette.py"}  # SWEEP_EXEMPT_SITES (OQ-3)
    hits = []
    for root in ("helao/core/tests", "helao/hexagon/tests", "harness/tests", "helao/deploy/base/tests", "helao/deploy/test/tests"):
        for p in (REPO / root).rglob("*.py"):
            rel = p.relative_to(REPO).as_posix()
            if rel in allowed:
                continue
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                if pat.search(line) or re.search(r"""["']hte/\w+["']""", line):
                    hits.append(f"{rel}:{i}")
    assert not hits, "\n".join(hits)
```
Run: `PYTHONPATH=$REPO $PY -m pytest -q -p no:cacheprovider helao/core/tests/test_framework_deployment_free.py::test_parent_tests_do_not_read_hte_by_path`
Expected: FAIL, listing at least `test_station_golden_capture.py:18`, `test_preflight.py:17`, `test_tooling_hygiene.py:54`, `test_helao_env.py:74-75,233` and `test_hte_collisions.py:5`. Path pieces joined by `os.path.join(..., "hte", "configs", ...)` are not caught by the regex, so also run `grep -rn '"hte"' helao/core/tests helao/hexagon/tests harness/tests` and handle each hit by the rules below.

- [ ] **Step 2: Move whole files**

```bash
cd $REPO
mkdir -p helao/deploy/hte/tests/reorg
mv harness/tests/test_hte_collisions.py helao/deploy/hte/tests/test_hte_collisions.py
mv harness/reorg/hte.json harness/reorg/hte_tests.json harness/reorg/hte_tests2.json helao/deploy/hte/tests/reorg/
mv harness/tests/test_station_golden_capture.py helao/deploy/hte/tests/test_station_golden_capture.py
```
In the moved `test_hte_collisions.py`: `HTE = Path(__file__).resolve().parents[1]`.

In the moved `test_station_golden_capture.py`: `HELPER = Path(__file__).resolve().parent / "smoke" / "station_golden_capture.py"`. Keep `from harness.tests.test_parity_legacy_remap import SEQ_NAME, _u, _write_run`.

- [ ] **Step 3: Write the thin `hte` tests**

`helao/deploy/hte/tests/test_host_surfaces_hte.py`:
```python
"""hte's share of two parent sweeps whose roots named hte (spec §2, OQ-3)."""

import pytest

from helao.hexagon.tests.test_driver_host_surface import scan
from helao.hexagon.tests.test_external_composition_contract import _registrar_reads
from pathlib import Path

HTE = Path(__file__).resolve().parents[1]


def _sources():
    return [p for p in sorted(HTE.rglob("*.py")) if "__pycache__" not in p.parts and "tests" not in p.parts]


def test_no_forbidden_host_read_in_hte():
    violations, _, _ = scan(_sources())
    assert not violations, "\n".join(violations)


def test_the_hte_scan_sees_every_measured_read():
    _, reads, files = scan(_sources())
    assert reads >= 29 and len(files) >= 14, (reads, len(files))  # measured 2026-11-10


#: Moved verbatim from the parent's REGISTRAR_CONTRACT: every app.<attr> an hte
#: *_dyn_endpoints registrar reads. A deployment outside this repo composes it.
REGISTRAR_CONTRACT = {
    "gamry_server2": {"action", "driver", "executors", "post", "server", "server_params", "stop_executor"},
}


@pytest.mark.parametrize("module_stem", sorted(REGISTRAR_CONTRACT))
def test_registrar_reads_exactly_the_pinned_attributes(module_stem):
    assert _registrar_reads(module_stem) == REGISTRAR_CONTRACT[module_stem]
```
The 29/14 floor was measured on 2026-11-10 by running `scan` over `helao/deploy/hte` alone. Re-measure after Task 1 and use the new numbers: the moved services had 0 reads.

In the parent's `test_external_composition_contract.py`, generalise `_hte_module(stem)` to `_registrar_module(stem)`, which looks in every deployment:
```python
def _registrar_module(stem: str) -> Path:
    return next(DEPLOY.glob(f"*/servers/*/{stem}.py"), Path(stem))
```
Call it from `_registrar_reads`. Remove `REGISTRAR_CONTRACT`, `test_registrar_reads_exactly_the_pinned_attributes` and `test_the_contract_probe_is_not_vacuous` from the parent; the pin now lives in the `hte` file above.

In the parent's `test_driver_host_surface.py`:
- `ROOTS = ("helao/deploy/base", "helao/hexagon/adapters/native", "helao/core/drivers")`;
- in `test_the_scan_sees_every_measured_read`, replace the assertion with `assert reads >= 1 and len(files) >= 1, (reads, len(files))`, plus the comment `# hte's 29 reads / 14 files moved to helao/deploy/hte/tests/test_host_surfaces_hte.py (2026-11-10)`. Re-measure first with the same `scan` call over the new ROOTS, and pin the measured numbers.

`helao/deploy/hte/tests/test_preflight_hte.py`, with cases moved from `test_preflight.py`, `test_tooling_hygiene.py` and `test_reflex_gate_config.py`:
```python
"""Preflight and config gates over hte's own configs (moved from parent tests)."""

import re
import shutil
from pathlib import Path

import pytest

from helao.helpers.config_loader import read_config
from helao.hexagon import preflight

HTE = Path(__file__).resolve().parents[1]
SMOKE_CONFIGS = HTE / "tests" / "smoke" / "configs"
STATION_CONFIGS = ["adss3", "anec", "ccsi2", "clad", "eche10", "ecms3", "hispec"]


@pytest.mark.parametrize("prefix", STATION_CONFIGS)
def test_every_hte_station_config_preflights_with_resolved_servers(prefix, capsys):
    assert preflight.main([prefix]) == 0
    m = re.search(r"PREFLIGHT OK: .* \(resolved (\d+) server\(s\)\)", capsys.readouterr().out)
    assert m and int(m.group(1)) >= 1
```
Then append, verbatim from the parent, with `SMOKE_CONFIGS` pointing as above:
- `test_the_reflex_configs_pin_ws_simulator_to_test`;
- `test_a_scratch_copy_of_a_config_still_exercises_the_checklist_gate`;
- `test_smoke_canary_configs_carry_no_alert_config_path` (with `cfgs = list(SMOKE_CONFIGS.glob("*.yml"))`);
- the `_HTE_HEX` parameter case of each of `test_reflex_gate_config.py`'s four parametrized tests (`test_gate_config_validates`, `test_gate_config_preflights_clean`, `test_the_reflex_key_still_names_the_bundle_not_a_module`, and the fourth at line 55), each parametrized over `[HTE / "configs" / "htehexreflex.yml"]`, together with the private helpers those tests call.

In the parent:
- `KNOWN_STATION_CONFIGS = ["test"]`;
- delete the two moved tests and the `SMOKE_CONFIGS` constant;
- in `test_checklist_dir_prefers_private_in_repo_then_central`, change `"hte"` to `"base"` (`base.parts[-3:] == ("base", "tests", "checklists")`);
- `PUBLIC_DEPLOYMENTS = ("base", "hte", "test")`;
- in `test_reflex_gate_config.py`, keep only the `[_HEX]` parameter and drop `_HTE_CONFIGS`, `_HTE_HEX` and `_HTE_LEGACY`.

`helao/deploy/hte/tests/test_hte_configs.py`:
```python
"""hte's config and env-resolution checks (moved from parent tests)."""

from pathlib import Path

import pytest

import helao_env as he
from helao.helpers.config_loader import HelaoConfig, ServerConfig, read_config
from helao.helpers.launcher_bootstrap import app_module_path

CONFIGS = sorted((Path(__file__).resolve().parents[1] / "configs").glob("*.yml"))


def test_hte_has_tracked_configs():
    assert CONFIGS


@pytest.mark.parametrize("path", CONFIGS, ids=[p.stem for p in CONFIGS])
def test_every_hte_config_validates(path):
    parsed = HelaoConfig.model_validate(read_config(str(path)))
    assert all(isinstance(v, ServerConfig) for v in (parsed.servers or {}).values())


def test_server_folders_of_a_real_hte_config():
    folders = {f.name for f in he.server_folders(he.resolve_config("hte/anec"))}
    assert {"gamry", "nidaqmx", "galil_motion"} <= folders


def test_app_module_path_for_real_hte_server():
    assert app_module_path("hte", "gamry_server2").endswith(".gamry_server2")
```
In the parent:
- in `unit_test_config_validation.py:26`, use `for deployment in ("test",):`;
- delete `test_server_folders_of_a_real_hte_config` (it skips without `hte`, and the spec allows no `hte` skips);
- in `test_unresolvable_module_names_the_server`, change `deployment: hte` to `deployment: test`;
- in `test_main_missing_tool_exits_2`, use `he.main(["setup", "test/goldenreflex"])`. Its modules resolve to `base`/`test`, so `install` is reached and the stubbed tool failure gives exit 2.

`helao/deploy/hte/tests/test_freeze_hte.py`: move verbatim, with their bodies, from `harness/tests/test_freeze.py`:
- `test_unnamed_removal_stays_a_blocker_and_says_how_to_name_it`;
- `test_key_override_substitutes_the_server_key`;
- `test_verify_external_confirms_the_route_in_its_registrar`;
- `test_hte_freeze_is_clean_and_skips_nothing`.

Import `from harness import freeze` and `from harness.tests.test_freeze import _external, _route`. The Gamry registrar case does not fit a `test` registrar: `control_sim`'s `dyn_endpoints` is nested inside `makeApp`, so `module:function` cannot name it. So the case moves, per spec §2's fallback.

`helao/deploy/hte/tests/test_motion_control_hte.py`: move from `helao/core/tests/test_motion_control.py`:
- `HTE_CONFIG_GLOB` (as `str(Path(__file__).resolve().parents[1] / "configs" / "*.yml")`);
- `_tracked_hte_scales`, `_hte_server` and the four fixtures;
- every test whose signature names one of the four fixtures, or whose body calls `_tracked_hte_scales` (measured: `test_no_tracked_scale_round_trips_cleanly_within_an_ordinary_jog`, `test_every_tracked_scale_is_a_plausible_millimetres_per_count`, `test_the_ceiling_outlasts_any_move_the_hardware_can_actually_perform`, `test_discovery_reads_the_letter_keyed_schema`, `test_the_letter_keyed_schema_resolves_through_the_controller_letter`, `test_discovery_reads_the_reciprocal_schema`, `test_the_reciprocal_schema_is_inverted_not_passed_through`, `test_the_accessor_is_a_single_consistent_scalar`, `test_the_default_clears_every_shipped_move_limit`, and every other user `grep -n "adss3_motor\|hispec_motor\|eche10_kmotor\|hispec_kmotor\|_tracked_hte_scales" helao/core/tests/test_motion_control.py` finds).

Import the remaining helpers from `helao.core.tests.test_motion_control`. The parent file's docstring "Fixture rule" becomes: `Live-config sweeps over hte configs live in helao/deploy/hte/tests/test_motion_control_hte.py.`

- [ ] **Step 4: Run both halves, count, mutation-check**

Run:
```bash
cd $REPO && PYTHONPATH=$REPO $PY -m pytest -q -p no:cacheprovider helao/deploy/hte/tests/test_hte_collisions.py helao/deploy/hte/tests/test_station_golden_capture.py helao/deploy/hte/tests/test_motion_control_hte.py helao/deploy/hte/tests/test_freeze_hte.py helao/deploy/hte/tests/test_host_surfaces_hte.py helao/deploy/hte/tests/test_preflight_hte.py helao/deploy/hte/tests/test_hte_configs.py helao/core/tests/test_motion_control.py harness/tests/test_freeze.py helao/hexagon/tests/test_driver_host_surface.py helao/hexagon/tests/test_external_composition_contract.py helao/hexagon/tests/test_preflight.py helao/core/tests/test_tooling_hygiene.py helao/hexagon/tests/test_reflex_gate_config.py helao/core/tests/test_helao_env.py helao/core/tests/test_framework_deployment_free.py
PYTHONPATH=$REPO $PY run_unit_tests.py
```
Expected: PASS and exit 0.

Then compare collected counts: `--collect-only -q` over the affected parent files at HEAD vs. now, plus the new `hte` files. Expected: parent-now + `hte`-new ≥ parent-at-HEAD. The net change is: +7 station configs minus the removed parent parametrization, +N `hte` config validations, +1 vacuity floor. Record the arithmetic in the hand-off.

Mutations, one at a time, reverting each:
1. Add `app.base` read to a copy of an `hte` driver. Expected: `test_no_forbidden_host_read_in_hte` fails.
2. Add `"extra"` to `REGISTRAR_CONTRACT["gamry_server2"]`. Expected: the registrar test fails.
3. Delete `alert_config_path` handling: add `alert_config_path: x` to a copy of one smoke config. Expected: `test_smoke_canary_configs_carry_no_alert_config_path` fails.
4. Break one `hte` config (`servers: 3`). Expected: `test_every_hte_config_validates[...]` fails.

- [ ] **Step 5: Gates and commit (controller)**

Run black, pyright, the golden masters and the Standard sweep. Commit to the parent: `test: tests that need hte instrument code move into hte`.

---

### Task 10: Prove a parent-only clone works

**Files:** none changed, unless this task finds a failure. A fix goes back to the task that owns the file, then this task re-runs.

- [ ] **Step 1: Build the parent-only scratch clone**

```bash
D=$CLAUDE_JOB_DIR/t10; mkdir -p $D
git clone --no-local --branch "$(git -C $REPO rev-parse --abbrev-ref HEAD)" $REPO $D/parent-only
rm -rf $D/parent-only/helao/deploy/hte           # scratch clone only; it has no private repos either
git -C $D/parent-only log -1 --format=%H
```

- [ ] **Step 2: Sweep it**

Run the Standard sweep with `REPO=$D/parent-only`, in both the job and the `PYTHONPATH`. Expected: `rc=0`, 0 failed, 0 errors.

Then check for `hte` skips:
```bash
grep -rn -i -E "skip.*\bhte\b|\bhte\b.*skip" $D/parent-only/helao $D/parent-only/harness --include='*.py' | grep -v '/deploy/hte/'
grep -c "SKIPPED\|skipped" $D/run.log
```
Expected: the first command prints nothing. The skip count equals the skip count of the full-tree sweep from Task 9 minus the skips inside `hte` and private files. A new skip is a failure of this task.

- [ ] **Step 3: Root-env-only check (spec §5.6)**

```bash
conda env create --solver=rattler -p $D/rootenv -f $D/parent-only/helao_dev_linux-64.yml
uv pip install --python $D/rootenv/bin/python -r $D/parent-only/requirements.txt
cd $D/parent-only && PYTHONPATH=$D/parent-only $D/rootenv/bin/python -c "import pkgutil, importlib, helao; [importlib.import_module(n) for _, n, _ in pkgutil.walk_packages(helao.__path__, 'helao.') if '.tests' not in n and not n.startswith('helao.deploy.') or n.startswith(('helao.deploy.base', 'helao.deploy.test'))]"
```
Expected: no error output. Then run the Standard sweep with `PY=$D/rootenv/bin/python` and `REPO=$D/parent-only`. Expected: 0 failures.

- [ ] **Step 4: `goldenreflex` launches from the parent-only clone**

```bash
ss -ltnp | grep -E ':(8001|8002|8003|8004|5001|5010|5011)\b' || echo free
```
If a port is taken, **STOP**: another group is running, and it is never killed. Otherwise launch it as a background command, recording the PID:
```bash
cd $D/parent-only && ( PYTHONPATH=$D/parent-only ./helao.sh goldenreflex > $D/launch.log 2>&1 & echo $! > $D/launcher.pid; wait )
```
Wait for `ss -ltnp` to show 5010 and 5011, polling every 5 s for up to 600 s. Then:
```bash
curl -sf -o /dev/null -w '%{http_code}\n' http://127.0.0.1:5010/group
curl -sf -o /dev/null -w '%{http_code}\n' http://127.0.0.1:5010/operator
grep -c "helao/deploy/base" $D/launch.log; grep -c "$REPO/helao" $D/launch.log
```
Expected: `200` and `200`. The log shows modules loaded from `$D/parent-only` and none from `$REPO`.

Stop and confirm:
```bash
kill -TERM "$(cat $D/launcher.pid)"
```
Then poll `ss -ltnp` until none of the ports above are listed (up to 60 s).

- [ ] **Step 5: Hand-off**

Report the sweep counts, the skip count and both HTTP codes. There is no commit.

---

## Stage 6: the new repository

### Task 11: Extract `hte` history and merge it onto `cdaf724` (no push)

**Files:** none in the parent. Scratch repos go under `$D`.

**Interfaces:**
- Produces: `$D/hte-new`, a clone of `helao-hte-deployment` whose `main` is the merge commit, ready for the controller's push. Also `$D/extract-src.txt`, the parent commit the history was cut from, which Task 12 checks.

- [ ] **Step 1: Pin the source commit**

```bash
D=$CLAUDE_JOB_DIR/t11; mkdir -p $D
git -C $REPO status --short helao/deploy/hte    # expected: empty
git -C $REPO rev-parse HEAD > $D/extract-src.txt
```
The source is the parent's tip with Tasks 1-10 committed. It must be the commit the cutover builds on (Task 12 Step 1 checks this).

- [ ] **Step 2: Filter a fresh clone, never the working repo**

```bash
git clone --no-local $REPO $D/hte-extract
git -C $D/hte-extract checkout -q "$(cat $D/extract-src.txt)"
git -C $D/hte-extract checkout -q -B main
git -C $D/hte-extract filter-repo --force --subdirectory-filter helao/deploy/hte --refs main
git -C $D/hte-extract ls-files | head -3
```
Expected: the paths now start at the deployment root (`__init__.py`, `configs/...`).

- [ ] **Step 3: Merge onto the new repo's initial commit**

```bash
git clone https://github.com/High-Throughput-Experimentation/helao-hte-deployment.git $D/hte-new
git -C $D/hte-new log --oneline | tail -1                 # expected: cdaf724 ...
git -C $D/hte-new remote add extracted $D/hte-extract
git -C $D/hte-new fetch -q extracted main
git -C $D/hte-new -c user.name="$(git -C $REPO config user.name)" -c user.email="$(git -C $REPO config user.email)" \
  merge --allow-unrelated-histories --no-edit -m "Merge hte history from helao-async (helao/deploy/hte)" extracted/main
git -C $D/hte-new remote remove extracted
```
Expected: no conflict, because `hte`'s tree has no root README.md, LICENSE or .gitignore. This merge is a local commit in a scratch clone, not in any working repo. The push is the controller's job (Task 14).

- [ ] **Step 4: Verify fidelity (spec §5.1)**

```bash
S=$(cat $D/extract-src.txt)
diff <(git -C $REPO ls-tree -r "$S:helao/deploy/hte") <(git -C $D/hte-new ls-tree -r HEAD | grep -v -P '\t(README\.md|LICENSE|\.gitignore)$') && echo TREE-EQUAL
echo "parent: $(git -C $REPO rev-list --count --no-merges "$S" -- helao/deploy/hte)  extracted: $(git -C $D/hte-extract rev-list --count --no-merges main)"
echo "with merges: parent $(git -C $REPO rev-list --count "$S" -- helao/deploy/hte)  extracted $(git -C $D/hte-extract rev-list --count main)"
git -C $D/hte-new log --follow --oneline -- servers/gamry/gamry_server2.py | wc -l
git -C $REPO log --follow --oneline "$S" -- helao/deploy/hte/servers/gamry/gamry_server2.py | wc -l
git -C $D/hte-new ls-files | git -C $D/hte-new check-ignore --no-index --stdin || echo NOTHING-IGNORED
```
Expected:
- `TREE-EQUAL`;
- equal `--no-merges` counts. Report the with-merges counts too; a difference there comes only from merge commits filter-repo pruned, and the report must say so;
- equal `--follow` counts for the sample file, a prefix-stable history;
- `NOTHING-IGNORED`. If a tracked `hte` path matches the template `.gitignore`, **STOP** and report the paths, because fixing that `.gitignore` is an `hte` repo commit the controller approves.

- [ ] **Step 5: Hand-off**

Report the extract source SHA, the merge commit SHA and the four verification outputs. There is no push.

---

## Stage 7: cutover

### Task 12: The parent cutover commit (prepared by the executor, index removal by the controller)

**Files:**
- Modify: `.gitignore:22-26`, `update.sh:9-18`, `update.bat:8-22`, `readme.md` (install and update sections), `CLAUDE.md` (Three-layer layout bullet), `helao/deploy/__init__.py`, `helao/ui/reflex/CLAUDE.md:44`, `helao/ui/shared/CLAUDE.md:17`
- Index: `helao/deploy/hte/` removed from the parent's index (controller: `git -C $REPO rm -r --cached -q helao/deploy/hte`)

- [ ] **Step 1: Check nothing changed `hte` since extraction**

Run: `git -C $REPO diff --stat "$(cat $CLAUDE_JOB_DIR/t11/extract-src.txt)" HEAD -- helao/deploy/hte`
Expected: empty. If it is not, **STOP**: re-run Task 11 from the new HEAD, or carry the change into `hte-new` first. Any `hte` commit landing after the extraction would otherwise be lost.

Also list unmerged parent branches that touch `hte`:
```bash
git -C $REPO for-each-ref --format='%(refname:short)' refs/heads refs/remotes | while read b; do n=$(git -C $REPO rev-list --count HEAD.."$b" -- helao/deploy/hte 2>/dev/null); [ "${n:-0}" -gt 0 ] && echo "$b $n"; done
```
Report them. Their `hte` changes must be re-applied in the new repo after the cutover, and this report is the list.

- [ ] **Step 2: Edit the tracked files**

`.gitignore`: delete the line `!helao/deploy/hte/`.

`update.sh` loop body:
```bash
for dir in */; do
    # test/ and base/ are tracked here; every other deployment is its own git repo
    if [[ "$dir" != "test/" && "$dir" != "base/" && "$dir" != "__pycache__/" ]]; then
        if [[ ! -e "$dir/.git" ]]; then
            echo "--- skipping ${dir%/}: not a git repo (run update_env to clone or replace it) ---"
            continue
        fi
        echo "--- updating ${dir%/} ---"
        cd "$dir" || exit
        git pull
        cd ..
        echo ""
    fi
done
```
`update.bat` loop: replace the `hte` and `hexagon` exclusions with `base`, and add the `.git` guard:
```bat
for /d %%d in (*) do (
    if /i not "%%d"=="test" (
        if /i not "%%d"=="base" (
            if /i not "%%d"=="__pycache__" (
                if exist "%%d\.git" (
                    echo --- updating "%%d" ---
                    cd "%%d"
                    git fetch --prune --all && git reset --hard && git pull
                    cd ..
                ) else (
                    echo --- skipping "%%d": not a git repo, run update_env ---
                )
            )
        )
    )
)
```
`readme.md`:
- In the install section after `git clone .../helao-async.git`, add: "`setup_env` clones the `hte` deployment (https://github.com/High-Throughput-Experimentation/helao-hte-deployment) into `helao/deploy/hte` when it is missing, and `update_env` pulls it when a station config uses it."
- In the utilities table, change the `update.bat / update.sh` row to: "`update.bat` resets and pulls every nested deployment repo; `update.sh` pulls them; `test` and `base` are tracked here and skipped; a deployment folder without `.git` is skipped with a message".
- Add a section "Upgrading a station across the `hte` split (2026-11)":
  1. Stop the group (`CTRL-x`). Otherwise the hot-reload watcher sees a pull that deletes every `hte` module.
  2. Run `git -C <repo> status --short helao/deploy/hte`. Local edits to tracked `hte` files make `git pull` refuse; copy them out first (`update.sh`/`update.bat` discard them with `reset --hard`).
  3. Pull the parent **and every private deployment repo** (`update.bat`/`update.sh` do both). A private repo still pinning `deployment: hte` on a framework service, or importing `helao.deploy.hte.servers.reflex`, breaks until it is pulled too.
  4. Run `update_env` (no arguments replays the recorded configs). It logs and removes the leftover `helao/deploy/hte` folder and clones the new repo.
  5. Relaunch. The Reflex bundle rebuilds once, because its module paths changed.

  Rollback: `git revert` the cutover commit. A station that already cloned `hte` keeps working, because the path is ignored either way.

Living docs:
- `CLAUDE.md`: change "Only `base`, `hte` and `test` are tracked in this repo; `.gitignore` excludes all other `helao/deploy/*` directories" to "Only `base` and `test` are tracked in this repo. `hte` is its own public repository (`helao-hte-deployment`), cloned in place at `helao/deploy/hte` by `setup_env`; `.gitignore` excludes every other `helao/deploy/*` directory". In the BioLogic and Andor subsections, change "`helao/deploy/hte/servers/...`" to "`helao/deploy/hte/servers/...` (in the `hte` repo)".
- `helao/deploy/__init__.py`: "This repository tracks ``base`` (framework services) and ``test`` (sims and demos); ``hte`` is its own public repository cloned in place; the remaining subpackages are private repositories nested in-tree and are not named in tracked sources."
- `helao/ui/reflex/CLAUDE.md:44` and `helao/ui/shared/CLAUDE.md:17`: append "(`hte` repo, cloned at `helao/deploy/hte`)" after the `hte` path.

- [ ] **Step 3: Controller removes `hte` from the index, then the executor checks**

Controller: `git -C $REPO rm -r --cached -q helao/deploy/hte`.

Executor:
```bash
git -C $REPO ls-files helao/deploy/hte | wc -l                          # expected: 0
git -C $REPO status --short --ignored helao/deploy/hte | head -2       # expected: "!! helao/deploy/hte/"
```

- [ ] **Step 4: Swap the dev checkout's `hte` for a clone, compare**

Before the push, clone the scratch `hte-new` rather than the remote:
```bash
mv $REPO/helao/deploy/hte $CLAUDE_JOB_DIR/t12/hte-pre-cutover
git clone $CLAUDE_JOB_DIR/t11/hte-new $REPO/helao/deploy/hte
diff -r -x __pycache__ -x .omc -x '*.pyc' -x .git -x README.md -x LICENSE -x .gitignore $CLAUDE_JOB_DIR/t12/hte-pre-cutover $REPO/helao/deploy/hte && echo SAME
```
Expected: `SAME`. The moved-aside copy stays for the user. After the Task 14 push, repoint the clone with `git -C $REPO/helao/deploy/hte remote set-url origin https://github.com/High-Throughput-Experimentation/helao-hte-deployment.git`.

- [ ] **Step 5: Gates on the post-cutover tree**

Run the Standard sweep on `$REPO`, where `hte` is now a nested clone. Expected: 0 failures, and the total pass count equals Task 9's full-tree total (spec §5.3).

Then run these two checks:
- `PYTHONPATH=$REPO $PY -m pytest -q -p no:cacheprovider helao/hexagon/tests/test_external_composition_contract.py -k engine_coupling`. Expected: PASS. `hte` is now walked as an external deployment; its `pal` modules mention `helao.core.servers` only in docstrings, which the AST scan ignores. If the count rises, report it rather than raise the ceiling.
- `PYTHONPATH=$REPO $PY -c "import launch; print(launch.discover_git_repos('$REPO'))"`. Expected: the list contains `.../helao/deploy/hte`.

Then the Reflex bundle stamp:
```bash
P=$(PYTHONPATH=$REPO $PY -c "from helao.helpers.config_loader import read_config; s=read_config('htereflex')['servers']; ps=sorted({int(v['port']) for v in s.values() if 'port' in v} | {int(v['port'])+1 for v in s.values() if 'reflex' in v}); print('|'.join(map(str,ps)))")
ss -ltnp | grep -E ":($P)\b" || echo free
```
Launch `htereflex` with the protocol from Task 10 Step 4, from `$REPO`. Check that `<root>/STATES/reflex-bundles/htereflex_<reflex key>/bundle.json` has `helao/deploy/hte` in `git_revs`. Stop by PID and confirm the ports are released.

Finally run the golden masters.

- [ ] **Step 6: Commit (controller)**

Parent: `chore!: stop tracking helao/deploy/hte; it is now helao-hte-deployment`. Do not push yet (Task 14).

---

### Task 13: Cutover dry run on a scratch station (spec §5.5)

**Files:** none. Everything is under `$D=$CLAUDE_JOB_DIR/t13`.

- [ ] **Step 1: Build the old station**

```bash
D=$CLAUDE_JOB_DIR/t13; mkdir -p $D
git clone --no-local $REPO $D/station
git -C $D/station checkout -q "$(cat $CLAUDE_JOB_DIR/t11/extract-src.txt)"   # pre-cutover: hte tracked
mkdir -p $D/station/helao/deploy/hte/servers/gamry/__pycache__
printf '\0' > $D/station/helao/deploy/hte/servers/gamry/__pycache__/x.cpython-314.pyc
echo "station: local" > $D/station/helao/deploy/hte/configs/station_local.yml
git clone --bare $CLAUDE_JOB_DIR/t11/hte-new $D/hte-remote.git
export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0="url.$D/hte-remote.git.insteadOf" GIT_CONFIG_VALUE_0="https://github.com/High-Throughput-Experimentation/helao-hte-deployment.git"
```
The `GIT_CONFIG_*` variables redirect the real `HTE_URL` to the local bare repo for this shell only. Nothing global changes.

- [ ] **Step 2: A locally modified tracked file makes the pull refuse**

```bash
echo "# station edit" >> $D/station/helao/deploy/hte/configs/anec.yml
git -C $D/station fetch -q $REPO "$(git -C $REPO rev-parse --abbrev-ref HEAD)"
git -C $D/station merge --ff-only FETCH_HEAD; echo "rc=$?"
```
Expected: `rc` is not 0, with "Your local changes ... would be overwritten". Then `git -C $D/station checkout -- helao/deploy/hte/configs/anec.yml`.

- [ ] **Step 3: Pull the cutover parent, then `update_env`'s logic**

```bash
git -C $D/station merge --ff-only FETCH_HEAD; echo "rc=$?"                  # expected rc=0
find $D/station/helao/deploy/hte -type f | sort                            # expected: only the .pyc and station_local.yml
( cd $D/station/helao/deploy && bash $D/station/update.sh 2>&1 | grep -i "skipping hte" )   # leftover is skipped by update.sh
cd $D/station && PYTHONPATH=$D/station $PY helao_env.py setup 2>&1 | tee $D/setup1.log
```
In the `update.sh` line, the reset and pull run against `$D/station` (the script resets its own checkout, which is the scratch clone). Expected output: `skipping hte`.

Expected in `setup1.log`: `warning: removing leftover .../configs/station_local.yml`, no `.pyc` line, and `hte: replaced`. Then:
```bash
test -d $D/station/helao/deploy/hte/.git && echo CLONED
cd $D/station && PYTHONPATH=$D/station $PY -c "import helao.deploy.hte.servers.gamry.gamry_server2, helao.deploy.base.servers.orchestrator.async_orch2; print('imports ok')"
```
Expected: `CLONED` and `imports ok`. Here `helao_env.py setup` with no prefix stops after the base-env message, so no conda command runs.

- [ ] **Step 4: An existing `hte` repo is pulled, not deleted**

```bash
echo keep > $D/station/helao/deploy/hte/untracked_marker.txt
cd $D/station && PYTHONPATH=$D/station $PY helao_env.py setup --dry-run hte/eche10 2>&1 | grep "^hte:"
cd $D/station && PYTHONPATH=$D/station $PY -c "import helao_env as he; print(he.ensure_hte())"
cat $D/station/helao/deploy/hte/untracked_marker.txt
```
Expected: `hte: pulled` from the dry run, which prints `+ git -C ... pull` and changes nothing; then `pulled`; then `keep`.

- [ ] **Step 5: Hand-off**

Report each expected line. There is no commit. Unset the `GIT_CONFIG_*` variables.

---

### Task 14: Push in order, verify, station rollout (controller only, after user approval)

- [ ] **Step 1: Push the `hte` repo, verify with a fresh clone**

```bash
git -C $CLAUDE_JOB_DIR/t11/hte-new push origin main          # no --force
git clone https://github.com/High-Throughput-Experimentation/helao-hte-deployment.git $CLAUDE_JOB_DIR/t14/fresh
test "$(git -C $CLAUDE_JOB_DIR/t14/fresh rev-parse HEAD^{tree})" = "$(git -C $CLAUDE_JOB_DIR/t11/hte-new rev-parse HEAD^{tree})" && echo FRESH-OK
```
Then `git -C $REPO/helao/deploy/hte remote set-url origin https://github.com/High-Throughput-Experimentation/helao-hte-deployment.git && git -C $REPO/helao/deploy/hte fetch`.

- [ ] **Step 2: Push the parent `base` move**

Push the commits of Tasks 1-3 and 5-10 (everything before the cutover commit): `git -C $REPO push origin <cutover-commit>^:refs/heads/unstable`. If the branch is not `unstable`, push it to its own branch and merge by PR per the repo's flow. No force.

- [ ] **Step 3: Push the private repos' updates (Task 4)**

`git -C $REPO/helao/deploy/$DEP_x push`, once per repo.

- [ ] **Step 4: Push the parent cutover commit**

`git -C $REPO push origin unstable`.

- [ ] **Step 5: Post-push checks, then the station rollout**

Clone the parent fresh into `$CLAUDE_JOB_DIR/t14/p`, run `bash setup_env.sh` there only if a scratch env is wanted, and otherwise run `PYTHONPATH=. $PY helao_env.py setup`. Expected: `hte: cloned`.

Update the project memory with the commit SHAs. Stations follow the readme section from Task 12.

Windows (spec §5.7) stays open. On one Windows station: `setup_env.bat <hte config>` and `update_env.bat`. Record the result in the memory note.

---

## Self-review notes

- **Spec coverage:**
  - §1 → Tasks 1-3, with the closure recorded in Task 1. The "no module in two deployments" test is scoped to `base`, as Task 1's docstring explains.
  - §2 → Tasks 2 and 9. Every listed file was verified; `test_freeze`'s galil_io cases and `test_preflight`'s station-config, reflex-pin, scratch-copy and checklist-dir cases were found beyond the spec's list.
  - §3 → Tasks 7, 8, 11, 12, 13, 14.
  - §4 → Tasks 5 and 6.
  - §5.1 → Task 11. §5.2 → Task 10. §5.3 → Task 12 Step 5. §5.4 → Task 4. §5.5 → Task 13. §5.6 → Tasks 6 and 10. §5.7 → Task 14 (open item).
  - Out-of-scope living docs → Tasks 3 and 12.
- **Not covered by design:** `run_browser_parity.py` and `helao/core/tests/browser_parity/check_reflex_routes.py` (`htereflex` entry) are tools (spec §2). They run only when `hte` is present. The `_member_surface.md`/`_dependent_surface.md` checklists in `hte` and the private repos are historical text and stay as they are.
- **Name consistency:** `hte_state`, `ensure_hte`, `config_hte_use`, `wants_hte`, `_recorded_paths_exist`, `deployment_env_root` and `HTE_URL` are defined in Tasks 6-8 and used by those names in Tasks 12-14.
