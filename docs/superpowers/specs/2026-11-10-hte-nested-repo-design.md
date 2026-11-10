# Split the `hte` deployment into its own public repository

Date: 2026-11-10. Status: approved in conversation; awaiting review of this written spec.

## Goal

Separate commit access. The `hte` deployment (HTE lab configs, experiments, sequences and instrument servers) moves to its own public repository, https://github.com/High-Throughput-Experimentation/helao-hte-deployment. Contributors to the HTE lab code and to the framework then no longer need write access to each other's repository. The `helao-async` parent stays public. A parent clone plus the `hte` clone gives exactly today's functionality.

## Decisions

| Question | Decision | Why |
|---|---|---|
| Submodule, subrepo or plain nested repo | **Plain nested repo** at `helao/deploy/hte`, gitignored by the parent, the same pattern as the private deployments. | A submodule pins a commit, so every `hte` change would need a parent pin bump. A subrepo needs a parent maintainer to sync the copy. Both put the parent back in the loop that separate access removes. The tooling already treats a nested `.git` as its own repo: `launch.discover_git_repos`, the hot-reload watcher, the Reflex bundle stamp and the test sweep. |
| How stations get `hte` updates | Pull `hte` on its own, like the private deployments. | User ruling. |
| Fresh installs | `setup_env` / `update_env` clone `hte` when needed. | User ruling (one-command install as today). |
| Framework services that live in `hte` today | **Move into the parent**, into a new tracked deployment-shaped folder `helao/deploy/base`. | They are framework, not HTE instrumentation, and every deployment launches them (table below). The launcher already resolves `fast:`/`bokeh:` modules across deployments, so no config changes. |
| Shared vendor instrument servers and drivers | **Stay in `hte`.** | User ruling. The parent stays framework-only. A lab that launches or imports an `hte` instrument module also needs the `hte` clone, and `setup_env` provides it. |
| Parent tests that need `hte` | Tests that need only framework or `base` code stay in the parent. Tests, or parts of tests, that need `hte` instrument code or configs **move into `hte`**. | User ruling, refined once it was clear most dependencies are group-1 framework code. |
| Environment files | Packages only `hte` uses move out of the root env into the narrowest `hte` folder: a server folder's env files, or new deployment-level files for non-server code. | User ruling (consistency with how server-folder env files already work). |
| History | `hte`'s full history is extracted with `git filter-repo --subdirectory-filter helao/deploy/hte` and merged onto the new repo's existing initial commit (`cdaf724`, README/LICENSE/.gitignore) with `--allow-unrelated-histories`. **No force-push.** | Keeps the 707 commits touching `hte` and the user's initial commit. Both repos are MIT. |

Private deployments are referred to by alias (Deployment-A, B, C, E, F), because this file is tracked in a public repository.

## Findings that shaped the design

**Framework services living only in `hte`** (group 1). Number of configs launching each one, outside `hte`:

| `hte` module | Configs outside `hte` |
|---|---|
| `async_orch2` (orchestrator server) | `test` 12; private deployments 11 |
| `standalone_operator` | `test` 8; private deployments 9 |
| `action_visualizer`, `live_visualizer`, `control_visualizer` | `test` 10; private deployments 7 |
| `data_browser` | `test` 3; private deployments 1 |
| `sync_server` (data syncer) | private deployments 8 |
| `servers/reflex/_spectra`, `_action` (shared panel helpers) | imported by Deployment-E |

Splitting `hte` out unchanged would leave a parent-only clone unable to launch any group, `goldenreflex` included.

**Shared vendor instrument code** (group 2). Gamry, Galil (motion, IO, enums, aligner host, `layouts/aligner`), BioLogic, Andor, Kinesis, NI-DAQmx, cam, PDU, spec, PAL, sample server, XAFS, `drivers/io/enum`. Deployments A, B, C and E import or launch these. **They stay in `hte`.**

**HTE-lab code** (group 3): `hte`'s configs, experiments, sequences, specifications, processors and lab-specific tests.

## Design

### 1. `helao/deploy/base` (framework services move into the parent)

- New tracked folder `helao/deploy/base/`, with the usual deployment shape (`servers/<role>/...`) and an `__init__.py`. The parent's `.gitignore` gains `!helao/deploy/base/`.
- Move from `hte` into `base`, keeping each server folder whole (its README, env files and `bokeh/`/`reflex/` subfolders):
  - `servers/orchestrator` (`async_orch2`)
  - `servers/operator` (`standalone_operator`)
  - `servers/visualizer` (`action_visualizer`, `live_visualizer`, `control_visualizer`, `data_browser`)
  - `servers/sync` (`sync_server`)
  - `servers/reflex`, the shared Reflex panel helpers. Its `_pstat.py`, `_pstat_panel.py` and `digital_out_control.py` may be instrument-specific; the dependency closure decides whether each one moves or stays with its instrument in `hte`.
- **Dependency closure first.** Compute everything these modules import from `helao.deploy.hte`. Framework-level modules move with them. If the closure reaches into group-2 instrument code, **stop and report**; don't move instrument code to make the closure close.
- Python imports of moved modules change from `helao.deploy.hte.…` to `helao.deploy.base.…`, in the parent, in `hte`, and in the private repos that import them (Deployment-E: `_spectra`, `_action`). Each repo gets its own commit. Imports of group-2 modules keep `helao.deploy.hte.…`.
- Configs are untouched. The launcher's cross-deployment lookup finds each moved module in exactly one deployment (`base`). Verify no module name ends up in two deployments; the launcher warns and takes the first in sorted order if one does.
- Frozen route gates and checklists that pin paths of moved servers follow their servers. Never regenerate a frozen JSON; see the route-gate rule in the repo's CLAUDE.md files.

### 2. Tests

- Tests that need only framework or `base` code stay in the parent: orchestrator, operator, visualizer and syncer tests, and the ActionHost base-API surface gate. The gate's `_baseapi_system_surface.json` (now under `hte/tests/checklists/`) moves into the parent beside `helao/hexagon/tests/test_action_host_surface.py`; `action_host.py`'s docstring reference follows it.
- Tests, or parts of tests, that need `hte` instrument code or configs move into `hte/tests/`:
  - `harness/tests/test_hte_collisions.py` with `harness/reorg/hte*.json`;
  - the `hte` cases of `harness/tests/test_station_golden_capture.py`;
  - `helao/core/tests/test_motion_control.py`'s live-config sweep over `hte/configs`;
  - the Gamry registrar example in `harness/tests/test_freeze.py`, repointed to a `base` or `test` registrar in the parent if one fits; otherwise the case moves;
  - the `hte` roots of `test_driver_host_surface.py` and `test_external_composition_contract.py`;
  - the smoke canary configs (`hte/tests/smoke/configs`) and the preflight and tooling-hygiene cases that read them, if those configs launch group-2 servers;
  - the `hte` case of `helao/deploy/test/tests/test_data_browser.py`, if `data_browser` still lives in `hte` after the closure (otherwise it repoints to `base`).
- **Sweeps.** `test_palette`, `test_reflex_bundle`, the host-surface sweeps and `test_vis_ws_parity` keep sweeping the parent tree. `hte` gets thin tests that call the same parent helpers on `hte`'s tree, so rules like "colours only in `palette.py`" still cover `hte` panels. No sweep logic is duplicated.
- Comment- or docstring-only mentions of `hte` (`test_motion_control_vis.py`, `test_orch_dispatch_golden_master.py`, `test_vis_ws_parity.py`) and the fake path key in `test_reflex_bundle.py` stay as text. Where they describe a location that changes, they are reworded.
- `harness/classify.py` and `run_browser_parity.py` are tools, not tests. They keep working on whichever deployments are present.

### 3. Repository, bootstrap and cutover

- **New repo content.** The filtered `hte` history merged onto `cdaf724`. The new repo's root is the deployment folder. It is cloned to `helao/deploy/hte`, so imports (`helao.deploy.hte…`) and config lookup are unchanged. Check that the template Python `.gitignore` excludes nothing `hte` tracks.
- **Parent cutover commit:**
  - remove `helao/deploy/hte/` from the index;
  - drop `!helao/deploy/hte/` from `.gitignore`, so the existing `helao/deploy/*` rule covers it.
- **`setup_env` / `update_env`** (`.sh` and `.bat`, with the logic in `helao_env.py`; the URL is defined once):
  - **When it acts:** when a requested config launches or resolves any module from `hte` (from any deployment, including the private ones), or when no prefix is given and `hte` is absent.
  - **`helao/deploy/hte` is a git repo:** `git pull`. It is never deleted.
  - **It exists without `.git`** (a leftover after the parent pull): log every file in it that is not `__pycache__`/`.pyc`, remove the folder, then clone. (User ruling.)
  - **It is missing:** clone.
- **Station cutover order:** stop the group (otherwise the hot-reload watcher sees a pull that deletes every `hte` module), `git pull` the parent, run `update_env`, relaunch. `git pull` refuses if the station has local edits to tracked `hte` files; document resolving those before the cutover.
- **Push order:**
  1. Push the `hte` repo and verify it with a fresh clone.
  2. Push the parent `base` move, whose import paths the private repos need.
  3. Push the private repos' import updates.
  4. Push the parent cutover commit.

  A station must never pull a parent that drops `hte` while the new repo lacks it.
- **Rollback.** Reverting the parent cutover commit restores the tracked files. A station already cloned keeps working, because `helao/deploy/hte` is an ignored path either way.

### 4. Environment split

- **Audit** every package in `helao_dev_linux-64.yml` / `helao_dev_win-64.yml` and `requirements.txt` against the code that imports it. Distribution and import names differ, so match those by hand where needed. Classify each package as framework/`base`, `hte`-server-specific or `hte`-shared (used by non-server `hte` code).
- **`hte`-server-specific packages** move into that server folder's `environment.yml` / `requirements.txt`, the existing per-server pattern (13 `hte` server folders already have env files).
- **`hte`-shared packages** go to new deployment-level files `helao/deploy/hte/environment.yml` / `requirements.txt`. `helao_env.py` gains one rule: a deployment's root folder counts as an env folder whenever a requested config launches any server from that deployment. If the audit finds no `hte`-shared packages, skip this rule and its files.
- **The root env keeps** framework packages and those of `base`.
- **Pinned files** (`helao_pinned_*.yml`, `requirements_pinned_*.txt`) are re-solved for both platforms with the per-platform dry-run solve used in the last repin. Windows-only vendor packages are checked from the solve output; a Windows station running `update_env` on an `hte` config is the real check (open item).
- `update_env` only adds packages, so existing station environments keep everything they have.

### 5. Verification

1. **History fidelity.** The new repo's tree at `HEAD`, minus the three initial-commit files, equals the parent's `helao/deploy/hte` tree at the cutover commit. The commit count matches the parent's history of that path. `git log --follow` on a sample file shows its full history.
2. **Parent only** (fresh clone in a temp folder, no `hte`):
   - the full xdist sweep has 0 failures and 0 errors, with no `hte` skips needed;
   - `goldenreflex` launches and `/group` and `/operator` serve.
3. **Parent plus `hte`:**
   - the total pass count equals today's, now split across the two repos;
   - every moved test still fails when the behaviour it guards is broken (spot mutation checks);
   - `htereflex.yml` launches;
   - the hot-reload watcher and the bundle stamp list `helao/deploy/hte` as a nested repo.
4. **Private deployments:** each imports cleanly, and its tests pass with the new `base` paths.
5. **Cutover dry run** on a scratch copy standing in for a station: an old parent checkout with `hte` tracked, plus `__pycache__` and a fake station-local file. Pull the new parent, then run `update_env`. Check that:
   - leftovers are logged and removed;
   - the clone lands and imports work;
   - an existing `hte` git repo is pulled, not deleted;
   - a locally modified tracked file makes `git pull` refuse.
6. **Environment:**
   - a fresh env from root files alone imports every parent module and runs the parent suite;
   - `setup_env <hte config>` adds the `hte` packages;
   - the dry-run solves succeed on both platforms.
7. **Windows:** `setup_env.bat` and `update_env` on a station (open item; cannot run here).

## Out of scope

- Moving the shared vendor instrument code out of `hte`. Ruled to stay; revisit only if another lab's dependence on `hte` becomes a problem.
- Splitting the `test` deployment out of the parent.
- Adding CI. The parent has none; if added later, it clones `hte` for the combined run.
- Rewriting the 64 dated specs and plans under `docs/` that mention `hte` paths. They are history. Living docs are updated: the root `CLAUDE.md` ("Only `hte` and `test` are tracked…"), `readme.md` install steps, `helao/ui/reflex/CLAUDE.md` and `helao/ui/shared/CLAUDE.md`.

## Staging

Each stage is independently useful and verifiable, in this order:

1. **`base` move**: services, tests that follow them, the base-API checklist, import updates in the parent and `hte`. Useful on its own, with no split yet.
2. **Private repos' import updates** to `helao.deploy.base`.
3. **Environment split** in the parent and `hte`, plus the `helao_env.py` rule if needed.
4. **`setup_env` / `update_env` clone/pull logic**, tested against a local bare repo standing in for the remote.
5. **Test moves** into `hte`, with the sweeps' thin `hte` tests.
6. **History extraction and merge into `helao-hte-deployment`**, verified with a fresh clone.
7. **Parent cutover commit**, cutover dry run, push in the stated order, and the station rollout note.
