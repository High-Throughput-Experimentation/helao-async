# Wave-5 prerequisite — framework run-artifact output wiring (SP-ARTIFACT)

**Status:** scoped, not started. **Gates Wave 5** (no station may cut over until this lands + is live-verified).
**Branch:** `feat/framework-scaffold` (stack, per standing auth).
**Owner spec date:** 2026-06-26.

## 1. Problem

On the framework path, a real run produces **no run artifacts under the configured
`root`** — only log files appear. The scientific output (`*-act.yml`, `*-exp.yml`,
`*-seq.yml`, `*.hlo`) is the entire reason the system exists; without it a station
cut-over loses all data and breaks downstream sync/analysis/data-browser.

Earlier waves "passed" because the `test` deployment and every unit/golden test
write to throwaway temp dirs, and nobody inspected the temp output. The
`test`-deploy live runs (SP-ORCH-5) verified orchestration *control flow*, not
on-disk artifact parity. So this surfaced only now, looking at real output.

## 2. Evidence (current code)

**A. Output is rooted at a tempdir, not the config `root`.**
- `app/base_api.py:1199` — action-server `save_root` defaults to
  `tempfile.mkdtemp("helao_framework_baseapi_")` when not passed.
- `app/factory.py:121,170` — same tempdir default in `makeApp`/`makeActionApp`.
- **No hte action server passes `save_root`** (grep: zero hits) → all inherit the tempdir.
- `app/base_api.py:137-138` — `# TODO(SP8): full helao_dirs wiring (RUNS_*/STATES/LOGS roots)` → `self.helaodirs = None`.
- Legacy instead: `core/servers/base.py:156` `self.helaodirs = helao_dirs(world_cfg, server_name)`;
  `helpers/helao_dirs.py:48` `save_root = <root>/RUNS_ACTIVE`.

**B. Meta filenames diverge from legacy — and from the framework's OWN syncer.**
- Action meta writer: `domain/action_session.py:146` →
  `{action_output_dir}/{action_uuid}.act` (and `:165,:169` `{uuid}.seq` / `{uuid}.exp`).
- Legacy: `core/servers/base.py:920,946,968` →
  `{timestamp:%y%m%d.%H%M%S%f}-act.yml` / `-exp.yml` / `-seq.yml`.
- Framework syncer scans for `*-act.yml`/`*-exp.yml`/`*-seq.yml`
  (`domain/sync/paths.py:175-179` `stem.endswith("-act"/"-exp"/"-seq")`).
  → The framework writer produces files its **own** syncer will never pick up.
  (SP4 writer and SP6 syncer were golden-mastered independently against static
  fixtures, never end-to-end together — that's the integration gap.)

**C. Orchestrator exp/seq meta: right suffix, wrong stem + location.**
- `app/orch_api.py:297-303` writes `{experiment_uuid}-exp.yml` / `{sequence_uuid}-seq.yml`
  at the **save_root top level** (flat, no nested dir) with a uuid stem.
- Legacy writes them under the nested `<experiment_dir>` / `<sequence_dir>` with a
  **timestamp** stem and a `{"file_type": "experiment"|"sequence"}` content wrapper
  (`core/servers/base.py:943-970`).

**D. RUNS_DIAG / manual-action routing not honored.**
- Legacy: `manual_action` → `save_root.replace("RUNS_ACTIVE", "RUNS_DIAG")`
  (`core/servers/base.py:916,942,964`). Framework has no equivalent.

**E. ACTIVE→FINISHED relocate exists but is unverified end-to-end.**
- `domain/action_session.py:869-877` `relocate_dir` ports legacy `move_dir`
  (`core/servers/base.py:2218`), but with `helaodirs=None` + tempdir root it has
  never moved a real `RUNS_ACTIVE` tree to `RUNS_FINISHED` against a config root.

**What's already correct (do not touch):**
- HLO byte layout + filename: `action_session.py:346` `{action_output_dir}/{action_name}-{file_conn_key}.hlo` matches legacy; `fs_storage.py` is byte-identical.
- Nested run-dir path math: `domain/lifecycle.py:49-51` / `run_models.py:178-183` build the legacy `%y.%U/<date>/<seq>/<exp>/<act>` tree correctly.
- `fs_storage.write_meta` atomic-temp+replace + 2/4/2 YAML formatting.

## 3. Root cause

The SP4/SP8 action-base and SP-ORCH app layers compute the run-dir tree and write
meta/HLO, but the **output root was never bound to the config `root`** (left as an
explicit `TODO(SP8)`), and the **meta filenames were stubbed to a uuid form** that
the SP6 syncer doesn't recognize. Both slipped through because no test or live run
ever compared real on-disk output, under the real root, against a legacy run.

## 4. Scope

In: bind framework server output to the config root and bring meta artifacts to
byte/structure parity with legacy, end-to-end (write → relocate → sync-ready).

Out: changing the sync driver's S3/egress path (SP6, already correct); the
`dbpack_server` legacy-syncer seam (intentional until DB bring-up); data-browser
reader changes (it already reads legacy names — fixing the writer is enough);
deleting legacy `helao/core` (Gate D).

## 5. Work items

1. **helaodirs + save_root wiring (action servers).**
   - `FrameworkBase.__init__`: when `world_cfg` has `root`, set
     `self.helaodirs = helao_dirs(world_cfg, server_key)` and derive
     `save_root = <root>/RUNS_ACTIVE`. Keep tempdir fallback only when `root`
     absent (tests). Avoid double log-zip: launcher already rotates logs; call
     `helao_dirs` without `server_name`, or guard so logs aren't re-zipped on
     every Base construction.
   - `BaseAPI`/`factory.makeActionApp`: stop forcing the tempdir default; pass the
     config-derived `save_root` into `FsStorage`. Explicit `save_root=` arg still
     wins (tests/in-process runners).

2. **Action meta filename + content parity.**
   - `action_session._meta_relpath` → `{action_output_dir}/{ts:%y%m%d.%H%M%S%f}-act.yml`.
   - manual exp/seq writes (`:164-170`) → `-exp.yml`/`-seq.yml` with timestamp stem
     under the correct nested dir, content from `get_exp()/get_seq()` equivalents
     with the `{"file_type": ...}` wrapper.

3. **Orchestrator exp/seq meta parity.**
   - `orch_api` FinishExperiment/FinishSequence (`:297-303`) + `PersistMeta` (`:252`):
     write under the nested `<experiment_dir>`/`<sequence_dir>` with timestamp stems
     and the `file_type` wrapper; root at `<root>/RUNS_ACTIVE` (align `:1085`
     `RUNS_HLO/<server_key>` → `RUNS_ACTIVE`).

4. **RUNS_DIAG routing.** Honor `manual_action` → `RUNS_DIAG` substitution in the
   meta/HLO relpath resolution (action + orch).

5. **ACTIVE→FINISHED relocate.** Confirm `relocate_dir` dst resolves to the real
   `<root>/RUNS_FINISHED/<...>` once helaodirs is wired; fix dst if needed.

6. **save_data/save_act default parity.** Already mirrored
   (`action_session.py:135-140`); re-confirm against legacy `:1149-1162` incl. the
   "no save_root → save off" branch.

## 6. Verification (the part earlier waves skipped)

The existing SP4/SP6 golden masters are **static fixtures**, not real legacy runs —
do not rely on them for this. Required:

1. **Live `test`-deploy run, real root.** Point `test.yml` `root` at a clean dir,
   run a representative sequence end-to-end on the framework, and assert the
   on-disk tree under `<root>/RUNS_ACTIVE` (then `RUNS_FINISHED`) contains, with
   correct nested layout + names: `*-seq.yml`, `*-exp.yml`, `*-act.yml`, `*.hlo`.
2. **Legacy diff.** Run the same sequence on the legacy `test` path; diff the two
   trees — directory structure, filenames, and meta content (modulo
   uuids/timestamps). Capture the diff as the acceptance artifact.
3. **Syncer pickup.** Confirm the framework `HelaoSyncer` enqueues + promotes the
   produced tree `RUNS_ACTIVE`→`RUNS_FINISHED`→`RUNS_SYNCED` (names now match its
   `*-act.yml` scan).
4. **Regression test** at the app layer (real `FsStorage` on tmp, full
   seq→exp→act) asserting the legacy filenames/locations — so writer and syncer are
   exercised together, closing the integration gap.
5. Full framework suite green (currently 1589).

## 7. Risks

| Risk | Mitigation |
|---|---|
| Double log-zip when Base calls `helao_dirs` (launcher already zips) | call without `server_name`, or guard; verify logs not double-archived |
| Changing meta filenames breaks an existing framework reader/test that pinned uuid names | grep for `.act`/`.uuid` readers; update the static golden fixtures to legacy names (they were wrong) |
| In-process runners / tests rely on tempdir default | keep explicit `save_root=` override; only the *default* changes (config-root when `root` present, tempdir when absent) |
| `RUNS_DIAG`/manual edge untested | add a manual-action case to the regression test |

## 8. Gates

- **Spec/plan:** pre-approved (standing authorization) — proceed spec→plan→subagent-execute→merge.
- **Acceptance:** §6.1 + §6.2 diff must show parity before this is called done; then Wave 5 station bring-up may begin.
```
