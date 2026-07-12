# CARDS Refactor Plan — HELAO-async

> Derived from `CARDS_AUDIT.md` (2026-07-10, Parts 1–3). Branch: `feat/cards-refactor`
> on the parent repo **and** each nested private deployment repo (Deployment-A, Deployment-B, Deployment-C).
> `deploy/Deployment-D` and `deploy/Deployment-B/notes` are **out of scope entirely**.
> Test gate: `conda run -n helao python run_unit_tests.py` (the only harness; launch.py runs it pre-launch).
> Production safety: `hte` runs live hardware (Windows-only Galil/gclib, Gamry/comtypes). Early increments are pure
> structural, validated on Linux against `helao/core`, `helao/helpers`, and the `test` deployment sims.

---

## 1. Phasing overview (ordered by leverage × safety)

| Phase | Name | CARDS card(s) strengthened | Risk | Audit evidence |
|-------|------|---------------------------|------|----------------|
| **P1 = INCREMENT 1** | **Single source of truth: `RunDir` enum + status-literal cleanup** | **Resilience** (primary), Clarity | **Minimal** — pure structural, byte-identical runtime strings, Linux-verifiable | Part 1 Resilience: "`RUNS_*` never centralized — raw literals across ~17 files, 80+ sites"; "status enum bypassed: dict payloads hardcode `\"status\":\"active\"` (orch.py:677,693,863,879)"; Part 3 fix #3 |
| P2 | Kill campaign/spec duplication (parameterize, extract factories) | Resilience, Clarity | Low — no control-path changes, no hardware | Part 2: hte `specifications/` byte-identical files; Deployment-A `SDC_seq.py` triple ~430–516-line clones; Deployment-B `SampleModel` block ×24–29; Deployment-B `configure_leancat*` near-duplicates |
| P3 | Guarded lifecycle + typed params + injected typed config | **Domain Integrity** (biggest Part-3 re-rating), Alignment | Medium — core models/config touched; wire/YAML shape must stay identical; validate on `test` sims | Part 1: lifecycle = unguarded `List[HloStatus]` (action.py:126, experiment.py:112, sequence.py:101); all-`Optional` models; untyped world config (base.py:148); `HelaoConfig` exists but under-used (config_loader.py:150-192); Part 3: "untyped param contract forces stringly-typed deployment code" |
| P4 | Finish `HelaoDriver` ABC migration (non-prod wave → hte production wave) | **Separation**, Alignment, Domain Integrity | Medium → **High** (hte wave gated on hardware smoke) | Part 2 master variable: ~26 legacy `action_serv: Base` drivers; priority hte PAL (~2870 LOC), hte Archive (~2370 LOC), Deployment-A ThorlabsMotor (~1100 LOC), hte galil_motion, hte alicat; Part 3 confirmed top fix |
| P5 | Split the `Orch` god-class into collaborators | **Separation**, Clarity | **Highest** — 2545-line production orchestrator; do last, with P1–P4 seams in place | Part 1 weakest card: orch.py:80-2625, ~70 methods; `loop_task_dispatch_action` ~315 lines |

**Why this order deviates from the audit's raw leverage order (ABC first):** the ABC migration's biggest targets are
production hte drivers on live Windows hardware — they cannot be increment 1 under the production-safety constraint.
The `RUNS_*`/status-literal centralization is the audit's fix #3 but is the *only* top fix that is 100 % mechanical,
100 % Linux-verifiable, and touches every layer (core + helpers + 4 deployments), making it the correct first slice.
It also lays the seam (`RunDir` enum) that P3's typed-config work and P4/P5's refactors consume.

---

## 2. INCREMENT 1 — full detail

### Scope statement (decisive, single option)

Create one canonical `RunDir` enum in `helao/core/models/run_dir.py` and mechanically replace **every**
`"RUNS_ACTIVE" / "RUNS_FINISHED" / "RUNS_SYNCED" / "RUNS_DIAG" / "RUNS_NOSYNC"` string literal in scope with enum
members, plus replace the hardcoded `"status": "active"/"finished"` dict payloads in `orch.py` with
`HloStatus.<member>.value`. **Zero behavior change**: every produced runtime string is byte-identical
(the enum values ARE the current literals).

**Explicit exclusions (do not touch):**
- `helao/deploy/hte/drivers/data/dbpack_driver.py` (16 sites, duplicated `HelaoPath`) and
  `helao/deploy/hte/servers/action/dbpack_server.py` (3 sites) — dbpack is **deprecated dead legacy** fully
  superseded by `sync_driver.py` (project memory). Still referenced by hte configs, so it stays untouched and
  frozen; its removal is a P2 decision item (see Open questions).
- `helao/deploy/Deployment-D/**` (excluded from the refactor entirely).
- `helao/deploy/Deployment-B/notes/**` (excluded per audit).
- `test` deployment **sim driver internals** beyond the literal swap — sims are deliberately bare helpers, NOT to
  be ABC-ified (standing project decision).
- The Deployment-A `SDC_seq.py:2252` `stop_ce_pump: bool = "True"` type bug — fixing it changes a serialized param value,
  so it is **not** pure-structural; deferred to P3 (logged in Open questions).

### The transformation

**New module `helao/core/models/run_dir.py`** (task C1-01):

```python
"""Canonical run-state directory names used across HELAO run trees."""

__all__ = ["RunDir", "SYNC_PROGRESSION", "ALL_RUN_DIRS"]

from enum import Enum


class RunDir(str, Enum):
    ACTIVE = "RUNS_ACTIVE"
    FINISHED = "RUNS_FINISHED"
    SYNCED = "RUNS_SYNCED"
    DIAG = "RUNS_DIAG"
    NOSYNC = "RUNS_NOSYNC"


# Order matters: the sync pipeline promotes ACTIVE -> FINISHED -> SYNCED.
SYNC_PROGRESSION = (RunDir.ACTIVE, RunDir.FINISHED, RunDir.SYNCED)
ALL_RUN_DIRS = tuple(RunDir)
```

Stdlib-only; no new dependencies; safe to import from any layer (core, helpers, deployments, Deployment-C scripts).

**Mechanical replacement rules (identical for every task):**
1. `import` line: `from helao.core.models.run_dir import RunDir` (add `SYNC_PROGRESSION` where the
   3-member `valid_statuses` tuple is replaced).
2. Equality/membership tests: `part == "RUNS_ACTIVE"` → `part == RunDir.ACTIVE` (str-subclass equality is exact).
3. String-building contexts — `os.path.join(...)`, f-strings, `str.replace(...)`, dict values that get serialized:
   use `RunDir.ACTIVE.value` explicitly. **Always `.value` in string-construction contexts** — no reliance on
   `str()`/`format()` enum semantics.
4. `sync_driver.py:359` `valid_statuses = ("RUNS_ACTIVE", "RUNS_FINISHED", "RUNS_SYNCED")` →
   `valid_statuses = SYNC_PROGRESSION` (preserve the 3-member set exactly; do NOT widen to 5 — `status_idx`
   behavior must not change). Do not "fix" the odd `any([x in valid_statuses])` expression — it is
   behavior-equivalent to `x in valid_statuses` and rewriting it is out of scope for a pure-mechanical pass.
5. `orch.py` status payloads: `"status": "active"` → `"status": HloStatus.active.value` (sites ~677, 863, 1209;
   plus any the audit lists at 693/879 under different spacing) and `"status": "finished"` →
   `"status": HloStatus.finished.value` (~2257, 2302). `HloStatus` is already imported in orch.py's dependency
   set (`helao/core/models/hlostatus.py`). Grep the whole file for `"status": "` — replace every literal hit.
6. Never change whitespace, comments, or logic beyond the substitution. No renames, no signature changes.

### Files to touch (verified by grep, 2026-07-10; count = literal sites)

| File | Sites | Task |
|------|------:|------|
| `helao/core/models/run_dir.py` (NEW) | — | C1-01 |
| `helao/core/drivers/data/sync_driver.py` | 66 | C1-02 |
| `helao/core/servers/base.py` | 10 | C1-03 |
| `helao/core/servers/orch.py` | 10 + ~5 status payloads | C1-03 |
| `helao/core/servers/base_api.py` | 1 | C1-03 |
| `helao/helpers/yml_tools.py` | 12 | C1-04 |
| `helao/helpers/helao_data.py` | 11 | C1-04 |
| `helao/helpers/file_mapper.py` | 4 | C1-04 |
| `helao/helpers/helao_dirs.py` | 2 | C1-04 |
| `helao/helpers/processors.py` | 2 | C1-04 |
| `helao/core/runners/micro_orch.py` | 12 | C1-05 |
| `helao/core/servers/data_browser/sources.py` | 9 | C1-05 |
| `helao/core/drivers/data/loaders/localfs.py` | 5 | C1-05 |
| `helao/core/tests/unit_test_micro_orch.py` | 11 | C1-06 |
| `helao/core/tests/unit_test_sync_process_recovery.py` | 10 | C1-06 |
| `helao/core/tests/unit_test_sync_to_thread.py` | 6 | C1-06 |
| `helao/core/tests/unit_test_estop_sync.py` | 3 | C1-06 |
| `helao/core/tests/unit_test_extra_models.py` | 2 | C1-06 |
| `helao/deploy/hte/drivers/sensor/axiscam_driver.py` | 1 | C1-07 |
| `helao/deploy/hte/processors/libs/hispec_calibrate_downsample_parquet.py` | 5 | C1-07 |
| `helao/deploy/test/tests/test_data_browser.py` | 16 | C1-08 |
| `helao/deploy/test/runners/oersim_runner.py` | 1 | C1-08 |
| `helao/deploy/Deployment-A/drivers/calc_driver.py` (nested repo) | 3 | C1-09 |
| `helao/deploy/Deployment-C/scripts/common/batch_converter.py` (nested repo) | 7 | C1-10 |
| `helao/deploy/Deployment-C/scripts/{bruker,edax,xafs,xrfs_calibration,xrfs_quantification}/converters.py` | 2+2+2+2+2 | C1-10 |
| `helao/deploy/Deployment-C/scripts/xrfs_calibration/parquet_library.py` | 1 | C1-10 |
| `helao/deploy/Deployment-C/scripts/icpms/{batch_process_icpms,convert_icpms_csv}.py` | 2+2 | C1-10 |

Deployment-B has zero in-scope sites (its only hit is under excluded `notes/`).

### Parallelization

- **Serialize first:** C1-01 (the enum module) must land before everything else.
- **Parallel group A (after C1-01):** C1-02 … C1-10 are fully disjoint by file and by repo — run all nine as
  concurrent Sonnet executors. C1-03 owns `base.py` + `orch.py` + `base_api.py` exclusively (the shared-file
  hot spots) so no other task may touch those three files.
- **Serialize last:** C1-11 (verification sweep + commits) runs after group A completes.

### Per-task acceptance criteria (apply to every task in group A)

1. `conda run -n helao python run_unit_tests.py` exits 0 (run from repo root; PYTHONPATH is set by the env).
2. Import smoke (Linux-safe modules) exits 0 — the exact command is in the task table.
   For deployment/Deployment-C files whose transitive deps may not import on Linux, the gate is
   `conda run -n helao python -m py_compile <file>` instead.
3. `git diff` for the task's files shows **only** import additions and literal→enum substitutions
   (no whitespace/logic churn).
4. Zero remaining quoted `RUNS_*` literals in the task's files:
   `grep -nE '["'\'']RUNS_(ACTIVE|FINISHED|SYNCED|DIAG|NOSYNC)["'\'']' <files>` returns nothing.

### Task table — Increment 1

| ID | Title | Repo | Files | Depends on | Parallel group | Verification command |
|----|-------|------|-------|-----------|----------------|----------------------|
| C1-01 | Create `RunDir` enum module | parent | `helao/core/models/run_dir.py` | — | serial-pre | `conda run -n helao python -c "from helao.core.models.run_dir import RunDir, SYNC_PROGRESSION; assert RunDir.ACTIVE.value=='RUNS_ACTIVE' and len(SYNC_PROGRESSION)==3"` then `conda run -n helao python run_unit_tests.py` |
| C1-02 | Swap literals in sync_driver (incl. `valid_statuses` → `SYNC_PROGRESSION`) | parent | `helao/core/drivers/data/sync_driver.py` | C1-01 | A | `conda run -n helao python -c "import helao.core.drivers.data.sync_driver"` + gate + grep-zero |
| C1-03 | Swap literals + status payloads in core servers | parent | `helao/core/servers/{base,orch,base_api}.py` | C1-01 | A | `conda run -n helao python -c "import helao.core.servers.base, helao.core.servers.orch, helao.core.servers.base_api"` + gate + grep-zero (also grep `'"status": "'` in orch.py returns nothing) |
| C1-04 | Swap literals in helpers | parent | `helao/helpers/{yml_tools,helao_data,file_mapper,helao_dirs,processors}.py` | C1-01 | A | `conda run -n helao python -c "import helao.helpers.yml_tools, helao.helpers.helao_data, helao.helpers.file_mapper, helao.helpers.helao_dirs, helao.helpers.processors"` + gate + grep-zero |
| C1-05 | Swap literals in core runners/browser/loaders | parent | `helao/core/runners/micro_orch.py`, `helao/core/servers/data_browser/sources.py`, `helao/core/drivers/data/loaders/localfs.py` | C1-01 | A | `conda run -n helao python -c "import helao.core.runners.micro_orch, helao.core.servers.data_browser.sources, helao.core.drivers.data.loaders.localfs"` + gate + grep-zero |
| C1-06 | Swap literals in core standalone tests | parent | `helao/core/tests/unit_test_{micro_orch,sync_process_recovery,sync_to_thread,estop_sync,extra_models}.py` | C1-01 | A | `conda run -n helao python -m py_compile` each file; run each standalone script that already passes on this branch and confirm it still passes; + gate |
| C1-07 | Swap literals in hte (non-dbpack) | parent | `helao/deploy/hte/drivers/sensor/axiscam_driver.py`, `helao/deploy/hte/processors/libs/hispec_calibrate_downsample_parquet.py` | C1-01 | A | `conda run -n helao python -m py_compile` both files + gate + grep-zero |
| C1-08 | Swap literals in test deployment | parent | `helao/deploy/test/tests/test_data_browser.py`, `helao/deploy/test/runners/oersim_runner.py` | C1-01 | A | `conda run -n helao python -m py_compile` both; run `helao/deploy/test/tests/test_data_browser.py` if it passes pre-change; + gate |
| C1-09 | Swap literals in Deployment-A | **Deployment-A (nested)** | `helao/deploy/Deployment-A/drivers/calc_driver.py` | C1-01 | A | `conda run -n helao python -m py_compile helao/deploy/Deployment-A/drivers/calc_driver.py` + gate + grep-zero; commit inside `helao/deploy/Deployment-A` |
| C1-10 | Swap literals in Deployment-C scripts | **Deployment-C (nested)** | 11 files under `helao/deploy/Deployment-C/scripts/` (see table above) | C1-01 | A | `conda run -n helao python -m py_compile` each file + gate + grep-zero; commit inside `helao/deploy/Deployment-C` |
| C1-11 | Whole-tree verification sweep + commits | all | — | C1-02…C1-10 | serial-post | See below |

**C1-11 verification sweep (must all pass):**
```bash
conda run -n helao python run_unit_tests.py
# zero raw literals outside allowed exclusions:
grep -rnE --include='*.py' '["'\'']RUNS_(ACTIVE|FINISHED|SYNCED|DIAG|NOSYNC)["'\'']' helao/ \
  | grep -vE 'run_dir\.py|dbpack_driver\.py|dbpack_server\.py|deploy/Deployment-D/|deploy/Deployment-B/notes/'
# expected: empty output (exit 1)
grep -n '"status": "' helao/core/servers/orch.py   # expected: empty
conda run -n helao python -c "import helao.core.servers.orch, helao.core.servers.base, helao.core.drivers.data.sync_driver, helao.helpers.yml_tools, helao.helpers.helao_data, helao.core.runners.micro_orch"
```
Then one commit per repo: parent (`feat/cards-refactor`), Deployment-A, Deployment-C — each nested repo committed from inside its
own directory (they are invisible to the parent repo's git).

---

## 3. Risk notes + rollback

- **No behavior change by construction.** Every enum `.value` is byte-identical to the literal it replaces;
  comparisons use str-subclass equality. The one semantic trap — relying on `str(enum)`/f-string formatting —
  is closed by the mandatory `.value`-in-string-contexts rule (rule 3).
- **Shared-file contention:** `base.py`/`orch.py`/`base_api.py` are the highest-churn files in the repo; C1-03
  owns them exclusively and no other increment-1 task may edit them. If a hotfix lands on `unstable` mid-flight,
  rebase `feat/cards-refactor` before C1-11.
- **dbpack frozen, not fixed:** the duplicated `HelaoPath`/`valid_statuses` in `dbpack_driver.py` (audit
  Resilience finding) is deliberately left; deleting dbpack outright needs a config sweep (10+ hte YAMLs still
  name it) and is a P2 decision, not an increment-1 side effect.
- **Windows-only imports:** hte driver files (axiscam) may import vendor libs unavailable on Linux — that is why
  their gate is `py_compile`, not import. Do not "fix" import errors encountered during py_compile; they are out
  of scope.
- **Nested-repo drift:** Deployment-A/Deployment-B/Deployment-C have their own remotes/branches. All are confirmed on
  `feat/cards-refactor` (checked 2026-07-10). Executors must `cd` into the nested repo to commit.
- **Rollback:** everything is on feature branches with one commit per repo per increment. Roll back with
  `git revert <sha>` (or branch reset pre-merge) independently per repo; the parent and nested commits have no
  cross-repo ordering dependency because the enum module lives in the parent and nested repos only *consume* it —
  reverting a nested repo never breaks the parent, and reverting the parent enum requires reverting the nested
  consumers too (do parent last).
- **Production exposure:** none in increment 1 — no hte control-path logic changes; hte edits are one sensor
  driver literal and one processor lib, both `py_compile`-gated. The hot-reload watcher only affects *running*
  groups on their deployed branch, which is not `feat/cards-refactor`.

---

## 4. Later phases (sketch)

### P2 — Kill duplication (Resilience, Clarity) — pure structural, still Linux/no-hardware
- hte `specifications/`: `last2weeks.py` + `bimonthly.py` byte-identical, `last3months.py` differs by one number
  (audit Part 2) → one parameterized spec unit + thin named wrappers (wrappers keep existing import paths).
- Deployment-A `SDC_seq.py`: collapse the three ~430–516-line near-duplicate sequence variants (`:3487, :3972, :4488`)
  into one parameterized implementation + wrappers preserving the public sequence names the configs reference.
- Deployment-B: extract the ~24–29× copy-pasted `SampleModel` construction block into a factory in the Deployment-B repo; extract
  `configure_leancat` vs `configure_leancat_for_ADVENT_MEA` common core.
- Deployment-C: delete `_old`/dead duplicate variants in `helao_nbio.py` (`extract_parts*`), unify the four `/run_<instrument>`
  handlers behind one parameterized handler.
- Decision item: retire dbpack (`dbpack_driver.py` + `dbpack_server.py` + config entries) — superseded by
  `sync_driver.py`; needs a config sweep and sign-off.
- Gate: `run_unit_tests.py` + py_compile + "wrappers produce identical experiment/sequence lists" spot checks on
  the `test` deployment where applicable.

### P3 — Domain Integrity core: guarded lifecycle, typed params, injected config (Domain Integrity, Alignment)
- Wrap `List[HloStatus]` lifecycle (action.py:126, experiment.py:112, sequence.py:101) behind guarded transition
  methods (centralizing the scattered `.append()` sites, e.g. `base.py:997`) **without changing the serialized
  field shape** — validators/methods only, so `.yml`/HLO output is unchanged.
- Thread the existing `HelaoConfig`/`ServerConfig` pydantic models (config_loader.py:150-192) through `Base.__init__`
  instead of deep dict navigation (`world_cfg["servers"][key]["host"]`, base.py:148); make `load_global_config`
  validation unconditional; add an injection seam to start retiring the `global CONFIG` Munch and the
  `set_global` control-coupling flag (config_loader.py:129).
- Discriminate the sample `Union` (action.py:142); begin typing `action_params` for the `test` deployment's
  experiments first (sims = safe proving ground; fixes the string-keyed `check_condition` dispatch class).
- Fold in the Deployment-A `stop_ce_pump: bool = "True"` fix here (behavior-visible, needs a param-serialization check).
- Gate: `run_unit_tests.py` + launching the `test` deployment group on Linux and running a sim sequence end-to-end.

### P4 — `HelaoDriver` ABC migration (Separation, Alignment, Domain Integrity)
- Templates: `helao/deploy/hte/drivers/pstat/gamry/driver.py`, `.../biologic/driver.py`,
  `helao/deploy/Deployment-A/drivers/stenner/driver.py`, `.../advantech/driver.py`; contract in
  `helao/core/drivers/helao_driver.py` + `helao/helpers/executor.py`.
- Transformation per driver: `action_serv: Base` back-reference → `config: dict` seam; raw-dict returns →
  `DriverResponse`; polling → `DriverPoller`; server endpoints become thin executor adapters (gamry_server2 pattern).
- **Wave 4a (non-production):** Deployment-A ThorlabsMotor (~1100 LOC, split I/O vs alignment vs Bokeh UI vs persistence),
  Deployment-A stenner-variant/advantech-duplicate consolidation onto the existing ABC drivers, Deployment-B's 4 small drivers.
- **Wave 4b (production hte, gated on per-station hardware smoke):** PAL → Archive → galil_motion → alicat →
  remaining sensors, one driver per station-window. Coordinate with the existing PAL/Archive-hoist consensus plan.
- **Never:** ABC-ify the `test` deployment sims (deliberate boundary).
- Gate: `run_unit_tests.py` + py_compile on Windows-only code + hardware smoke checklist per hte driver.

### P5 — Split `Orch` (Separation, Clarity) — last, highest risk
- Extract collaborators along the audit's fault lines: dispatch state-machine (`loop_task_dispatch_*`), network
  subscription (`subscribe_all`, `ping_action_servers`), WS broadcast (`ws_globstat`), queue persistence
  (`export_queues`/`import_queues`), estop policy (`estop_actions(switch)` flag → two named methods). Mirror the
  in-tree `base_api.py` free-function decomposition. Decompose `Active._finish` (~221 lines) similarly in `base.py`.
- Prereqs: P1 (literals), P3 (typed config/lifecycle) landed; validated by running the `test` deployment
  orchestrator through full sim sequences before any hte exposure.

---

## 5. Open questions

Tracked in `.omc/plans/open-questions.md`:
- [ ] Retire dbpack entirely in P2 (driver + server + ~10 hte config entries)? — determines whether its
      duplicated `HelaoPath` gets deleted or stays frozen.
- [ ] Push policy for nested-repo `feat/cards-refactor` branches (push after each increment vs. at phase end)?
- [ ] P4 wave-4b scheduling: which hte station gets the first ABC-migrated driver smoke test, and when?
- [ ] `stop_ce_pump: bool = "True"` (Deployment-A SDC_seq.py:2252): confirm no downstream consumer string-matches `"True"`
      before fixing in P3.
