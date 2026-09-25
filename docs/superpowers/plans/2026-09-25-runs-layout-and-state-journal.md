# RUNS Layout Unification and Per-Server State Journals — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the eight `RUNS_*` state directories with a single `RUNS` tree whose records never move, holding lifecycle state in append-only per-server JSONL journals under `STATES` instead of in directory names.

**Architecture:** Three sequential phases, each independently shippable. Phase 1 makes the record's own `files` list the authority for what uploads, which is a prerequisite for deleting `RUNS_NOSYNC` and independently fixes a live defect. Phase 2 builds and wires the journal module while the existing folder-state machinery still runs, so nothing is yet load-bearing. Phase 3 flips the layout: `RUNS`/`DIAG` roots, the new date path, the label rule, and the deletion of every move.

**Tech Stack:** Python 3.14, pydantic v2, pytest, `black` (88 cols), stdlib `json` for the journal (no new dependency).

**Spec:** `docs/superpowers/specs/2026-09-25-runs-layout-and-state-journal-design.md`

## Global Constraints

- **Environment.** Run python and pytest via the `helao` conda env interpreter at `/home/dan/miniforge3/envs/helao/bin/python`, with `PYTHONPATH` set to the repo root. Never via `conda run` (it buffers output and hides hangs).
- **Pytest.** One file per pytest process, wrapped in `timeout`. Collecting the tree as a single session hangs indefinitely and ignores SIGINT. Example:
  `timeout 300 /home/dan/miniforge3/envs/helao/bin/python -m pytest <one_file> -v`
- **Formatting.** Run `black <changed_files>` immediately before every `git add`/`git commit`. Parent repo and each nested `helao/deploy/*` repo are formatted and committed independently.
- **Types.** `pyright` (basic mode, `pyrightconfig.json`) is authoritative. Do **not** remove `# type: ignore` directives it needs.
- **Colours.** Never hardcode a colour outside `helao/ui/shared/palette.py`. `helao/core/tests/test_palette.py` enforces this with an AST sweep.
- **Paths.** Every run-relative path that is stored, compared, split, or transmitted uses **forward slashes** on every platform (spec §9). OS-native separators are produced only at the filesystem call itself and never persisted.
- **Private deployments.** Nested `helao/deploy/*` directories other than `hte` and `test` are separate git repos and this repo is a public remote. Never name them in tracked parent-repo files; write "private deployments".
- **Git.** Never `git stash` in this repo (the stash stack carries other branches' work). Never commit directly to `unstable` or `main` from a task; all work lands on the feature branch. Never `git push` from a task.
- **Falsifiable tests.** Every test this plan adds must be shown to fail when its guard is deleted. Mutate, observe the failure, restore. A test that passes with the implementation removed is a plan defect, not a passing task.

## Branch

All phases land on one branch:

```bash
git checkout unstable
git pull
git checkout -b feat/runs-layout-unification
```

## File Structure

**New files**

| Path | Responsibility |
|---|---|
| `helao/helpers/run_state.py` | The journal. Append, replay, compact, rebuild-from-scan. Pure functions plus one `RunStateJournal` class. No HTTP, no server imports. |
| `helao/core/tests/audit_upload_sets.py` | Standalone report utility (Phase 1 Task 1). Diffs glob-derived vs `files`-derived upload sets over a real archive. `__main__` script, reported as `NOTESTS` by `run_tests.py`, like its four siblings. |
| `helao/core/tests/test_run_state.py` | Journal unit tests. |
| `helao/core/tests/test_upload_set.py` | Upload-set authority tests (spec §3.5.2). |
| `helao/core/tests/test_sequence_label.py` | Label rule table (spec §3.3). |
| `helao/core/tests/test_runs_layout.py` | Layout + no-movement + depth tests (spec §10.1, §10.2, §10.9). |
| `helao/core/tests/test_legacy_run_readers.py` | Legacy tree resolution through `FileMapper` and `HelaoData` (spec §10.8). |

**Modified files** — the ~14 behaviour changes enumerated in spec §8. Each task below names its own exact set.

---

# Amendments from the deployment impact survey (2026-09-25)

A read-only survey of all six deployments ran against this plan. Full report
(not committed — it names the private deployments, which tracked parent-repo
files may not): `/home/dan/.claude/jobs/a98b8858/tmp/deploy-impact-report.md`.

**Every task below is amended by this section. Read it before starting any
task, and treat the item for your task as part of that task's requirements.**

Verdicts: two deployments need real code changes, one is blocking, two are
mechanical, one is unaffected. Their own repos are amended separately — see
A3.

---

### A1 — Task 10: `list_pending` sweeps every record ever written

`sync_driver.py:2260-2267, 2277-2284, 2294-2301` build the search root as

```python
finished_dir = str(self.helaodirs.save_root).replace(
    RunDir.ACTIVE.value, RunDir.FINISHED.value
)
```

Once `save_root` is `<root>/RUNS` that replace is the **identity**, and records
never leave. So the startup sweep and `/finish_pending` would enqueue every
record ever written under `RUNS`, growing without bound.

Not destructive — `prog.s3_done` short-circuits the upload — but it floods
`task_queue`, and `has_pending_work()` reads exactly that queue, so the
hot-reload idle gate is wedged behind the sweep at every start.

**Spec §5 lists `finish_pending` and `has_pending_work` as "unchanged". That is
wrong and this amendment supersedes it.** Filter the three `list_pending*`
globs on the absence of a complete sibling `.prg` — the same predicate spec
§4.5 defines for the rebuild path. Share one helper with Task 5's
`_prg_is_complete`; do not write a second copy.

Add a test: a tree with one complete-`.prg` record and one without yields
exactly one pending entry. Mutate by removing the filter and confirm it returns
two.

### A2 — Task 9: `helao/helpers/processors.py:45` is missing

Every deployment's post-processors reach the action directory through it, and
it carries an ACTIVE→DIAG string replace. Add it to Task 9's file list and
convert it to `redirect_manual_dir()` with the others.

Related, same task: the manual redirect is a bare-substring
`save_root.replace("ACTIVE", "DIAG")` in several places that a `RunDir` grep
does not find, including `active_data_file.py:411` in `track_file` itself.
Grep for the bare string `"ACTIVE"` as well as `RunDir.ACTIVE`.

### A3 — Task 13: the six deployments need their own commits

Task 13 Step 1's sweep descends into `helao/deploy/*`, but four of those are
separate git repositories with their own branches and remotes — the parent
repo's `git status` cannot see changes there. One of them has ~50 files with
hits and its **production** batch pipeline in scope, not only fixtures.

Task 13 needs:
1. An explicit per-deployment commit step: `cd` into each deployment directory
   and commit within its own git repo.
2. A **fourth triage bucket, `legacy-tooling-by-design`** — live repair tooling
   pointed at a frozen archive. Neither fixture nor test; leave its literals
   alone.

### A4 — Task 3: a *driver* that writes into an action directory has no way to register — RESOLVED

The premise behind the current design is false. The OLE driver defers moving
EC-Lab's artifacts until `cleanup()` because, per its own docstring, "a file
written straight into the action directory could be uploaded half-finished".

**That cannot happen.** The syncer refuses any record whose status is not
`finished` (`sync_driver.py:1408`), and a record only reaches the syncer at
all through `yml_finisher`, after the action has finished. There is no window
in which a live action's directory is uploaded.

So the artifacts do not need to be shipped at `cleanup()` to be safe, and the
registration does not need a post-hoc enumeration: whatever writes them can
register them through the executor's `active` handle at the time it writes,
like every other producer in the codebase already does.

Task 3 is unblocked. The driver-side change belongs to that deployment's own
repo and is tracked in A3's per-deployment commit step, not here. What this
plan owes it is the guarantee in A11 — that `status` keeps meaning what it
says once the path stops encoding it.

### A5 — Task 12: the alias covers the name, not the zip assumptions

Two consumers are reached with the same value and open it with `ZipFile`
unconditionally; they will skip silently or raise on a directory. Task 12
extends to **every consumer of the value**, not just the keyword. Enumerate
them in Step 1 alongside the `sequence_zip_path` grep by also grepping for
`ZipFile`, `zipfile`, and `.zip` in any file that mentions a sequence path.

### A6 — Task 11: the operator's spec-lister goes silently empty

`week_window.py:47-59` globs `<folderpath>/<%y.%W>/**/*.zip` for each of the
last N weeks. It depends on **both** the week-numbered top level **and** on
synced sequences being zips — this plan removes both. The operator's "re-run a
previous sequence with overridden params" list goes permanently empty for new
runs at six live stations, and an empty list is indistinguishable from a quiet
station.

Glob `<folderpath>/%Y/%m%d/*/` for directories and keep the zip glob for the
legacy window. `HelaoData` already accepts a directory, so the downstream
`list_params` and `parser` need no change. **This needs a test**, precisely
because the failure is invisible.

Note while you are in that function: it uses `%y.%W` (Monday-start) while
`premodels.get_sequence_dir` writes `%y.%U` (Sunday-start). That is a
**pre-existing off-by-one-week bug**, not something this change introduces.
Fix it while the file is open, and say so in the commit message so it is not
mistaken for a regression.

Thirteen configs point `seqspec_folder_path` at the legacy tree. Repointing
them is a per-station decision at cut-over, not a code change — add it to the
cut-over checklist.

### A7 — Task 8: the label has consumers outside the record

Spec §10.3's table covers the *rule*. Nothing covers a consumer that compares
the label against something outside the record: one matches the recorded label
as a substring of a source folder name, another hashes it into a `uuid5`.

A `uuid5` over a changed label yields a **different identity for the same
sequence**, which is the duplicate-record failure mode this codebase has
already fought. Task 8 must enumerate label consumers and state, for each,
whether the D6 suffix changes its result.

### A8 — Task 5: the rebuild scan must not silently under-report

Some archive subdirectories raise `PermissionError: [Errno 1] Operation not
permitted`. `os.walk` swallows errors by default, so an unreadable subtree is
indistinguishable from an empty one — a short journal that looks complete.

`rebuild_from_tree` must pass `onerror=` (or catch per-directory), count what
it could not read, and log it at WARNING. A rebuild that skipped 400
directories must say so rather than quietly producing a short journal.

**Shipped contract** (`a17b55b3`): `os.walk(runs_root, onerror=errors.append)`
collects the `OSError` itself, so `e.filename` names the directory. The
warning gives the count, the first five paths, and says the journal may be
INCOMPLETE and that the missing records read as done and will never sync. It
does not raise.

The count is exposed as `RunStateJournal.unreadable_dirs` — a class attribute
defaulting to `0`, set on the instance by `rebuild_from_tree`. Chosen over a
tuple return so the signature and every call site stay unchanged. **Task 6
must check it**: on a corrupt-journal startup, `if journal.unreadable_dirs:`
should escalate louder than a log line, because a degraded rebuild means some
records will never sync.

Do **not** prune descent once a record's yml is found. Records nest — `act`
inside `exp` inside `seq` — so every record directory is also the parent of
the next level down, and pruning at a sequence yml would drop every experiment
and action under it. An earlier draft of this amendment suggested otherwise
and was wrong.

### A9 — Task 11: a path can carry *two* run-root segments

Superseded records are archived as whole nested legacy trees:

```
RUNS_SUPERSEDED/260818.091656/RUNS_FINISHED/26.25/0624/160156__.../...
```

Spec §7's rule ("legacy iff **any** segment is in `LEGACY_RUN_DIRS`") is
correct and unaffected. But:

- `file_mapper.py:56-59` takes the **first** matching segment.
- `helao_data.py:145-146` takes the first and then uses `str.replace`, which
  rewrites **all** occurrences.

The single-candidate fast path must take the **last** run-root segment, or
refuse to fast-path a multi-root path at all. Add a test with a two-root path.

Also: `FileMapper.__init__` special-cases the literal `PROCESSES`
(`file_mapper.py:56-59`) and will `IndexError` on a `PROCESSES_SUPERSEDED`
path. That directory mirrors `PROCESSES`, not `RUNS_*`, so spec §3.1 leaves it
alone — but the reader still has to survive meeting one.

### A10 — Task 3: the reconciliation warning (already fixed)

Recorded here for completeness: `_is_syncable_misc_file` excludes neither
`.prg` nor `.lock`, so once the sidecar sits beside its yml the warning fires
on every record. Task 3's listing and its mutation list were corrected in
commit `bc6607ce`.

### A11 — Task 10: `HelaoYml.status` and `status_idx` raise on a new-layout path

Found while verifying A4. This is the hardest item in this section: **the
syncer cannot process a single new-layout record until it is fixed**, and it
fails with an exception rather than silently.

```python
@property
def status(self) -> str:                                    # sync_driver.py:328
    path_parts = [x for x in self.targetdir.parts if x.startswith("RUNS_")]
    status = path_parts[0].split("_")[-1].lower()           # IndexError
```

No segment of `RUNS/2026/0925/...` starts with `RUNS_`, so `path_parts` is
empty and the subscript raises. `status_idx` (`:367-374`) has the same defect
one layer down — `.index(True)` raises `ValueError` — and `rename`,
`relative_path`, `active_path`, `finished_path` and `synced_path` all rest on
it.

`sync_yml` consults `status` twice, at `:1398` and `:1408`, to refuse a record
that is already synced and to refuse one that is still active. Both are on the
main path for every record.

**Fix: derive the status from `meta_status`, not from the path.** The yml's own
`<type>_status` list is the record's actual lifecycle; the path was only ever
an inference from where the record happened to sit, and there is no longer a
"where" to infer from. `meta_status` already exists (`:334-341`) and its
docstring already draws the distinction.

- `status` returns `"active"` / `"finished"` / `"synced"` from `meta_status`
  for a new-layout path, and keeps the path derivation for a legacy one so
  archives still classify.
- `status_idx`, `rename` and `relative_path` are legacy-only. Guard each with
  `is_legacy_path` and raise a clear error naming this amendment if a
  new-layout path reaches them, rather than letting an `IndexError` surface
  from three frames down.

Tests: a new-layout record whose meta says `active` is refused by `sync_yml`;
one whose meta says `finished` proceeds; a legacy record classifies from its
path exactly as today. Mutate by restoring the path derivation and confirm the
first two fail with `IndexError` rather than a clean refusal — that is the
production symptom.

### A12 — Task 5: read the real uuid, from both ends of the yml

Two corrections to this task, both found by measuring rather than reading. The
shipped implementation is `helao/helpers/run_state.py` (commits `da70cbae`,
`218aebe2`); it is the reference, not the listing in Task 5.

**1. A rebuilt record must be keyed by its real uuid.** The plan's stem
shortcut is a phantom-record generator: `working_set()` is keyed by uuid,
eviction is `records.pop(uuid, None)`, and the `done` tombstone the syncer
appends later carries the real `action_uuid` out of `prog.yml.meta`. The pop
misses, the stem record is never evicted, and the working set grows
monotonically across every rebuild — the precise failure spec §3 D3 exists to
prevent.

**2. A head-only read recovers no sequence uuid at all.** Measured across the
production archive:

| yml | own uuid | parent uuid | file size |
|---|---|---|---|
| `-act` | line 3 | line 19 | 1,134 lines |
| `-exp` | line 2 | line 1050 of 1071 | 1,071 lines |
| `-seq` | line 427442 of 427448 | n/a | 427k–560k lines |

`sequence_params` and `planned_experiments` serialize *before* the uuid, so a
sequence's own uuid sits seven lines from the end of a half-million-line file
and an experiment's parent ~21 lines from its end. So the read is **head +
tail** — 4 KB and 8 KB windows via `open("rb")` and `seek`, each chunk's
boundary line discarded because a fragment is a prefix of a real line. Flat
cost whether the yml is 20 lines or 560k.

`parent` falls out of the same windows: an action's `experiment_uuid` from the
head, an experiment's `sequence_uuid` from the tail, `None` for a sequence.

Values are validated with stdlib `uuid.UUID(...)` and stored as
`str(UUID(value))`. A yml with no uuid key, or an unparseable one, falls back
to the stem and logs at WARNING naming the file — a rebuild survives one bad
record.

**Consequence for Task 6:** normalize the tombstone uuid the same way, with
`str(UUID(value))`. An uppercase or braced uuid arriving from elsewhere would
not pop. The ymls on disk are already lowercase canonical, so this is a guard
rather than a live bug — but it is the same `pop` that item 1 is about.

### A13 — Task 2: `action_output_dir` is run-relative (already fixed)

Recorded because the same mistake is easy to repeat in Tasks 3, 9 and 10.

The plan's Task 2 call-site snippet read:

```python
file_name=_relative_file_name(file_path, self.action.action_output_dir),
```

Two defects. The class has no `self.action` (it is `self.active.action`, and
inside `track_file` the local is `action`). Worse, **`action_output_dir` is
run-relative** — `premodels.py:373` sets it from `get_action_dir()` — so
`Path(<relative>).resolve()` anchors on the process cwd, `relative_to` raises
`ValueError` for every real file, and the helper falls back to basename.

The change would have looked applied and done nothing, **with every test still
green**, because the tests pass an absolute `tmp_path` while the real call site
passes a relative one. The prescribed mutation would not have caught it either.

The record directory is `os.path.join(save_root, action.action_output_dir)`,
which the surrounding lines already compute; hoist it into a local and reuse
it. Shipped that way in `04e16759`.

**Rule for the remaining tasks:** `sequence_output_dir`, `experiment_output_dir`
and `action_output_dir` are all run-relative. Any task that calls `.resolve()`,
`.relative_to()` or `os.path.abspath()` on one of them without joining
`save_root` first has this bug, and a `tmp_path`-based test will not find it.

### A14 — Task 3: four findings from the Task 2 investigation

**1. `relocate_files` and `aux_file_paths` are dead.** Six occurrences
tree-wide across all six deployment repos, **no call site**; the `Active`
delegator at `base.py:1455` is itself never invoked. So `track_file`'s
`dirname != record_dir` branch writes into a queue nobody drains.

This matters mainly because it corrects a scarier reading: there is no
relocation, therefore no second copy at the record root, therefore no
duplicate for §3.5.1's reconciliation to false-positive on. Note also that
`relocate_files` is `async_copy` (`shutil.copy`), a copy and not a move, so
the source would survive even if it ran.

`posthoc_writer.py:402` documents the live path as "queues the source for the
finalizer to relocate at action end" — **that finalizer step does not exist.**
The post-hoc writer works only because it does the copy itself at `:424-440`.
That stale docstring is what made the first analysis wrong.

*Decision for Task 3:* either delete both as dead, or wire the finalizer to
call `relocate_files`. Leaving a queue that one adapter hand-works-around and
another never drains is how this got mis-analysed. Deleting is the smaller
change and this plan's default; say which you did.

**2. A `files` entry that does not resolve is silently dropped.** `track_file`
on a path *outside* the record directory records a bare basename and the file
is never copied in, so `record_dir / file_name` does not exist. Task 3's
`is_file()` check drops it — **and §3.5.1's reconciliation cannot flag it**,
because that compares against a glob of the record directory and the file is
not there. Silent in, silent out.

Task 3 does not regress this (the glob never uploaded it either — it is not in
the record directory). But the warning needs **a second arm** to make it
visible: a `files` entry that does not resolve to an existing file under the
record directory. Add it, and test it.

**3. The post-hoc writer has a live sub-directory mismatch.**
`posthoc_writer.py:440` copies to `os.path.join(dest_dir, basename(path))`
while the `FileInfo` it just built now says `"sub/x.spc"` for a source inside a
sub-directory. Under a files-driven upload set that entry resolves to nothing
and the file is dropped — a **real regression** for post-hoc-written records,
unlike item 2. Its docstring's "only its basename is recorded" contract
(`:416`) is no longer true. Not covered by any test:
`test_posthoc_writer.py` is 40 passed either way. Task 3 must fix the copy to
preserve the sub-path, or the writer to record the basename it actually used.

**4. Latent: `_resolve_output_path` makedirs only the record root.**
`active_data_file.py:332-336` builds `output_file = join(output_path,
file_info.file_name)` then `os.makedirs(output_path, exist_ok=True)` — the root
only. A multi-segment `file_name` reaching there fails with
`FileNotFoundError`. Not reachable today (that name comes from
`init_datafile`, which Task 2 deliberately left as a record-root name), but it
becomes reachable the moment anything registers a sub-directory name through
the one-shot writer. One line: `os.makedirs(os.path.dirname(output_file),
exist_ok=True)`.

### A15 — Two frozen baselines are ALREADY RED on `unstable`

Verified independently at the merge-base `658c94dc` (tip of `unstable` before
this branch), in a clean worktree with `.omc/artifacts/` copied in — the
artifacts directory is gitignored, so a bare worktree reports a missing
baseline rather than a failure:

```
PASS   1_plain_two_experiment_sequence_no_wait
DELTA  2_every_action_start_condition: byte diff vs .../baseline_S0/2_...jsonl
PASS   3..6
DELTA  7_returned_action_error_estop_loop: byte diff vs .../baseline_S0/7_...jsonl
PASS   8, 9
CHECK FAILED: trace diverged from frozen reference
```

Red before this branch existed:

| Gate | State |
|---|---|
| `test_active_golden_master.py --check` | **green** — 13/13 |
| `test_orch_dispatch_golden_master.py --check` | **RED** — scenarios 2 and 7 |
| `.omc/artifacts/p3a/schema_baseline.json` (via `unit_test_status_transitions.py`) | **RED** |

**Consequence for Task 13 Step 3.** That step says "re-baseline the golden
masters deliberately" and treats a diff as this change's doing. For the orch
harness that is false: two scenarios diverge already. Re-freezing it during
Task 13 would silently adopt a pre-existing regression as the new truth and
destroy the evidence of whatever caused it.

**Rules for Task 13:**

1. Before touching any baseline, run all three gates at the merge-base and
   record the result. `test_active_golden_master` must be green there; if it is
   not, stop — something changed under you.
2. **Do not re-freeze `baseline_S0` or `schema_baseline.json` in this plan.**
   They are red on arrival and their repair is separate work.
3. Only re-baseline a gate that is **green at the merge-base and red at your
   HEAD**, and then only after reading the diff field by field.
4. For the two already-red gates, the bar is "fails in exactly the same way as
   at the merge-base" — not "passes". Diff the diffs.

Nobody has been told about the pre-existing failures; they are noted here
because this plan trips over them, not because this plan owns them.

### A16 — There are TWO server stacks; the plan's file lists assume one

Task 6 could not be completed from its declared file list, and the reason
generalizes to **Tasks 9, 10 and 11**.

The plan writes as if `Base` / `Active` / `Orch` are the only implementations.
They are not. `helao/hexagon/app/` carries a native host/session pair that is
**not** a subclass of either:

| Legacy | Hexagon-native |
|---|---|
| `Base` (`core/servers/base.py`) | `ActionHost` (`hexagon/app/action_host.py`) |
| `Active` (`core/servers/base.py`) | `ActionSession` (`hexagon/app/action_session.py`) |
| `Orch` write_active_* (`core/servers/orch.py`) | `RunLifecycle` (`hexagon/app/orch_lifecycle.py`) |

The `golden` test config runs the hexagon stack — `ws_simulator` and
`sim_db_server` both build an `ActionHost` — and several production servers are
hexagon-composed via `fast: graft`. Task 6 had to add `run_journal`
construction to `ActionHost.__init__` and a `record_active(...)` call to
`ActionSession.myinit` mirroring `Active.myinit`, or the producer journal would
never have been written at all and Step 8 would have shown a SYNC journal with
no producer behind it.

**Rule for the remaining tasks: every edit to `Base`, `Active` or `Orch` needs
its hexagon counterpart checked.** Specifically:

- **Task 9** (manual → DIAG, `move_dir` gutted): `base.py:1017-1029` has a
  mirror in the hexagon session, and `helao/hexagon/domain/naming.py` is
  already in scope. Check `action_host.py` and `action_session.py` for their
  own save-root resolution.
- **Task 10** (syncer): `helao/hexagon/adapters/native/sync_driver.py` is
  already listed; confirm it does not also need `posthoc_writer.py` and
  `meta_writer.py`, which the survey named.
- **Task 11** (readers): the hexagon browser source port is a separate
  implementation from `ui/shared/data_browser/sources.py`.

Two corrections in the other direction — the plan over-listed:

- **`hte/servers/action/sync_server.py` needed no edit.** `/finish_yml`
  forwards to `SyncDriver.enqueue_yml`, so wiring the `unsynced` append in the
  driver covers hte and the sim syncer with one change.
- **`helao/core/servers/orch.py` needed no edit.** Its `write_active_*` methods
  are delegators to `RunLifecycle`; wiring the collaborator covers both
  orchestrator hosts.

Prefer the collaborator over the delegator wherever that choice exists — one
edit instead of two, and no risk of the two drifting.

### A17 — The only `RUNS_*` literal left in production code

`rebuild_from_tree`'s scan root is the one place Phase 2 hardcodes a legacy
name. Everything else derives its path from `root_relative(...)` against
whatever `save_root` happens to be, so Task 7 flipping `save_root` to
`<root>/RUNS` needs no edit anywhere else in the journal wiring. **Task 7 must
fix that one literal** — grep `run_state.py` and the Task 6 call sites for
`RUNS_` before declaring Task 7 done.

---

## Decision resolved (2026-09-25)

The driver-registration question in A4 is closed: the syncer never sees a live
action, so the race the current design guards against does not exist. See A4.

# Phase 1 — The upload set becomes `files`-driven

Ships alone. Fixes `sync-uploads-glob-not-action-files` at its source and is the
prerequisite for deleting `RUNS_NOSYNC` in Phase 3.

---

### Task 1: Measure what the glob uploads that `files` does not

The spec (§3.5.1) requires this measurement before any code changes, because the
offender list is vendor drivers copying instrument output in by hand and is not
derivable from the repo.

**Files:**
- Create: `helao/core/tests/audit_upload_sets.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `glob_set(action_dir: Path) -> set[str]` and `files_set(act_yml: Path) -> set[str]`, both returning forward-slash paths relative to the action directory. Task 3 reuses both names as the definition of the two sides it must reconcile.

- [ ] **Step 1: Write the audit script**

```python
"""Report files the syncer's directory glob would upload that ``files`` omits.

Standalone report utility, in the style of ``check_long_paths`` and
``scan_prg_ghosts``. Not a pytest module: ``run_tests.py`` reports it as
NOTESTS and it must be invoked directly.

    python helao/core/tests/audit_upload_sets.py <archive_root> [--limit N]

``archive_root`` is any directory containing action ymls -- a whole
``RUNS_SYNCED`` tree, or one sequence directory. The script pairs each
``*-act.yml`` with its own directory and prints every name that a glob would
have picked up but the yml's ``files`` list does not mention.

Spec: docs/superpowers/specs/2026-09-25-runs-layout-and-state-journal-design.md §3.5.1
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

from helao.helpers.yml_tools import yml_load


def _is_bookkeeping(path: Path) -> bool:
    """Staging and lock files that no upload set should ever contain.

    Mirrors ``HelaoYml._is_syncable_misc_file``'s exclusions: every meta and
    data writer here stages ``.<hex>.tmp`` beside its target and renames into
    place, so a scan landing mid-write sees a name that is not a run artifact.
    """
    return (
        path.suffix in (".lock", ".tmp")
        or path.name.startswith(".")
    )


def glob_set(action_dir: Path) -> set[str]:
    """What the syncer uploads today: every non-bookkeeping file, recursively.

    Returns forward-slash paths relative to ``action_dir``. Action ymls recurse
    (``sync_driver.HelaoYml.misc_files`` uses ``rglob`` for actions), so a file
    in a subdirectory is included.

    ``.hlo`` files are included here even though ``_is_syncable_misc_file``
    excludes them: the syncer's real upload set is ``misc_files + hlo_files``,
    and this function models that whole set, not just the misc half. Only
    ``.yml`` is dropped, because a record's own metadata is handled separately
    at every level.
    """
    out = set()
    for p in action_dir.rglob("*"):
        if not p.is_file() or _is_bookkeeping(p):
            continue
        if p.suffix == ".yml":
            continue
        out.add(p.relative_to(action_dir).as_posix())
    return out


def files_set(act_yml: Path) -> set[str]:
    """What the action's own ``files`` list names, nosync entries included.

    nosync entries are kept here deliberately: this audit measures
    *addressability*, not the upload decision. A nosync file that ``files``
    names is not a gap.
    """
    meta = yml_load(act_yml, fast=True) or {}
    out = set()
    for entry in meta.get("files") or []:
        name = (entry or {}).get("file_name")
        if name:
            out.add(str(name).replace("\\", "/"))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("archive_root", type=Path)
    ap.add_argument("--limit", type=int, default=0, help="stop after N actions")
    args = ap.parse_args(argv)

    if not args.archive_root.is_dir():
        print(f"not a directory: {args.archive_root}", file=sys.stderr)
        return 2

    scanned = 0
    with_gap = 0
    by_suffix: Counter = Counter()
    examples: dict[str, str] = {}

    for act_yml in args.archive_root.rglob("*-act.yml"):
        scanned += 1
        gap = glob_set(act_yml.parent) - files_set(act_yml)
        if gap:
            with_gap += 1
            for rel in gap:
                suffix = Path(rel).suffix or "<none>"
                by_suffix[suffix] += 1
                examples.setdefault(suffix, str(act_yml.parent / rel))
        if args.limit and scanned >= args.limit:
            break

    print(f"actions scanned : {scanned}")
    print(f"actions with gap: {with_gap}")
    print()
    if not by_suffix:
        print("no gap: every globbed file is named in its action's files list")
        return 0
    print(f"{'suffix':<12}{'count':>8}  example")
    for suffix, count in by_suffix.most_common():
        print(f"{suffix:<12}{count:>8}  {examples[suffix]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Smoke it against a synthetic tree first**

Build a two-action tree by hand so the script's own logic is verified before it
is trusted on real data.

```bash
cd /mnt/STORAGE/repos/helao/helao-async
export PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async
D=$CLAUDE_JOB_DIR/tmp/audit_smoke/expdir
mkdir -p $D/0__0__SIM__registered $D/1__0__SIM__unregistered/subdir

# action A: every file registered
printf 'x' > $D/0__0__SIM__registered/data-0.0.0.0__0.hlo
cat > $D/0__0__SIM__registered/260925.120000000000-act.yml <<'YML'
action_name: registered
files:
  - file_name: data-0.0.0.0__0.hlo
    nosync: false
YML

# action B: one registered file, one unregistered file in a subdirectory,
# one staging file that must never be reported
printf 'x' > $D/1__0__SIM__unregistered/data-1.0.0.0__0.hlo
printf 'x' > $D/1__0__SIM__unregistered/subdir/instrument.spc
printf 'x' > $D/1__0__SIM__unregistered/.a1b2c3.tmp
cat > $D/1__0__SIM__unregistered/260925.120001000000-act.yml <<'YML'
action_name: unregistered
files:
  - file_name: data-1.0.0.0__0.hlo
    nosync: false
YML

/home/dan/miniforge3/envs/helao/bin/python helao/core/tests/audit_upload_sets.py $CLAUDE_JOB_DIR/tmp/audit_smoke
```

Expected output: `actions scanned : 2`, `actions with gap: 1`, and exactly one
row, `.spc  1`, pointing at `subdir/instrument.spc`. The `.tmp` staging file
must **not** appear — if it does, `_is_bookkeeping` is wrong and the rest of the
audit is untrustworthy.

- [ ] **Step 3: Run it against the real station archive**

Two archives matter, and they answer different questions.

**Local, available now** — `/mnt/STORAGE/INST_hlo` is a real station archive on
this host (~9.9k action ymls under `RUNS_FINISHED`, weeks 23.08 and 23.34):

```bash
/home/dan/miniforge3/envs/helao/bin/python helao/core/tests/audit_upload_sets.py \
    /mnt/STORAGE/INST_hlo/RUNS_FINISHED | tee $CLAUDE_JOB_DIR/tmp/upload_audit_local.txt
```

This establishes a **floor**, not the answer: its actions are overwhelmingly
simulator (`GPSIM`/`CPSIM`) plus `NI`/`PAL`/`PSTAT`/`MOTOR`/`SYRINGE`. None of
the vendor drivers §3.5.1 exists to find — Andor, Bruker GADDS, Gamry, BioLogic,
OceanDirect — appear in it, and not one of its action directories contains a
subdirectory, so the specific defect is never exercised. A clean result here
means only that the framework's own writers register what they produce.

**Station, gating** — the vendor-driver population lives on the instrument
stations:

```bash
/home/dan/miniforge3/envs/helao/bin/python helao/core/tests/audit_upload_sets.py \
    <station_root>/RUNS_SYNCED --limit 2000 | tee $CLAUDE_JOB_DIR/tmp/upload_audit.txt
```

Check the mount before believing it:

```bash
[ -n "$(ls -A /mnt/wd4/DATA 2>/dev/null)" ] && echo MOUNTED || echo "empty or absent"
```

`/mnt/wd4` is an **empty mount point** on this host, not a missing path — a bare
`test -d /mnt/wd4/DATA` reports success and is wrong. If it is empty, say so and
stop rather than guessing. **The station measurement is the gate for Task 3** —
do not proceed on an assumed answer.

Note which station you measure. A data-processing station (SYNC/BATCH/ANA, no
hardware) cannot answer this question either; the audit must run somewhere the
vendor drivers actually wrote.

- [ ] **Step 4: Record the finding in the spec**

Append a `#### 3.5.3 Audit result` subsection to the spec. Which form depends on
what Step 3 actually produced — do not write the first form unless you ran the
audit against a population that contains vendor-driver actions.

**If the gating measurement succeeded**, head it `(measured YYYY-MM-DD)` and
give: which archive and host, actions scanned, actions with a gap, the suffix
table, and one line per suffix saying whether that writer will be fixed to
register its output or whether the file is consciously accepted as
no-longer-uploaded.

**If only the local floor was measured**, head it `(partial, measured
YYYY-MM-DD)`, give the same numbers, and state explicitly which populations were
absent and that the gate is still open.

**If nothing was measured**, head it `(NOT YET MEASURED)` and state the exact
command, the host and path it must run on, and that Tasks 2 and 3 are gated on
it.

In every case this is the record that the decision was measured rather than
assumed — including the record that it was not.

- [ ] **Step 5: Commit**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
black helao/core/tests/audit_upload_sets.py
git add helao/core/tests/audit_upload_sets.py docs/superpowers/specs/2026-09-25-runs-layout-and-state-journal-design.md
git commit -m "test(sync): audit tool for glob-vs-files upload set gap

Reports files the syncer's directory glob would upload that an action's own
files list does not name. Measurement gate for making files authoritative.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XwcM9LMRUctM69ktAp2VUD"
```

---

### Task 2: `FileInfo.file_name` becomes record-relative

**Files:**
- Modify: `helao/core/models/file.py:137`
- Modify: `helao/core/servers/active_data_file.py:423`
- Modify: `helao/hexagon/adapters/native/data_file.py:422`
- Test: `helao/core/tests/test_upload_set.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `FileInfo.file_name` is a forward-slash path relative to the record's own directory. A bare filename remains valid and is the common case. Task 3 relies on this to address files in action subdirectories.

- [ ] **Step 1: Write the failing test**

```python
"""FileInfo.file_name addresses a file relative to its record directory."""

from pathlib import Path

from helao.core.servers.active_data_file import _relative_file_name


def test_file_in_record_root_is_a_bare_name(tmp_path: Path):
    (tmp_path / "data.hlo").write_text("x")
    assert _relative_file_name(tmp_path / "data.hlo", tmp_path) == "data.hlo"


def test_file_in_subdirectory_keeps_its_subdirectory(tmp_path: Path):
    sub = tmp_path / "subdir"
    sub.mkdir()
    (sub / "instrument.spc").write_text("x")
    assert (
        _relative_file_name(sub / "instrument.spc", tmp_path)
        == "subdir/instrument.spc"
    )


def test_separator_is_always_forward_slash(tmp_path: Path):
    """Spec §9: stored paths are forward-slash on every platform."""
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)
    (sub / "c.spc").write_text("x")
    assert "\\" not in _relative_file_name(sub / "c.spc", tmp_path)


def test_file_outside_the_record_falls_back_to_its_basename(tmp_path: Path):
    """A writer handed an unrelated absolute path must not emit '../..' paths."""
    outside = tmp_path.parent / "elsewhere.spc"
    outside.write_text("x")
    assert _relative_file_name(outside, tmp_path) == "elsewhere.spc"
```

- [ ] **Step 2: Run it to see it fail**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
export PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async
timeout 300 /home/dan/miniforge3/envs/helao/bin/python -m pytest \
    helao/core/tests/test_upload_set.py -v
```

Expected: `ImportError: cannot import name '_relative_file_name'`.

- [ ] **Step 3: Add the helper and use it at both write sites**

In `helao/core/servers/active_data_file.py`, above the class that uses it:

```python
def _relative_file_name(file_path, record_dir) -> str:
    """The name recorded in ``FileInfo.file_name`` for a produced file.

    Relative to the record's own directory and forward-slash separated
    (spec §9), so a file a driver writes into a subdirectory of the action
    directory is addressable by name -- the syncer's upload set is built from
    ``files`` and cannot see anything the list does not name.

    A path outside ``record_dir`` degrades to its basename rather than
    emitting a ``../`` traversal, which would be meaningless to a reader
    resolving the name against the record.
    """
    fp = Path(file_path)
    rd = Path(record_dir)
    try:
        return fp.resolve().relative_to(rd.resolve()).as_posix()
    except ValueError:
        return fp.name
```

Then replace `file_name=os.path.basename(file_path),` at
`active_data_file.py:423` with:

```python
            file_name=_relative_file_name(file_path, self.action.action_output_dir),
```

Apply the identical change at `helao/hexagon/adapters/native/data_file.py:422`,
importing the helper from `helao.core.servers.active_data_file` rather than
duplicating it — the two writers must not drift.

Leave `active_data_file.py:148`'s `file_name=filename` alone: that path already
carries a name the writer constructed for the record root.

- [ ] **Step 4: Run the test to verify it passes**

```bash
timeout 300 /home/dan/miniforge3/envs/helao/bin/python -m pytest \
    helao/core/tests/test_upload_set.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Prove the tests are falsifiable**

Revert `_relative_file_name`'s body to `return Path(file_path).name` and re-run.
Expected: `test_file_in_subdirectory_keeps_its_subdirectory` FAILS. Restore.

- [ ] **Step 6: Check the writers still round-trip**

```bash
timeout 600 /home/dan/miniforge3/envs/helao/bin/python -m pytest \
    helao/hexagon/tests/test_native_data_file.py -v
timeout 900 /home/dan/miniforge3/envs/helao/bin/python \
    helao/core/tests/test_active_golden_master.py --check
```

Note the second is **not** run under pytest. Despite the `test_` prefix it is a
standalone `argparse` harness whose gate is `--check`; `pytest` collects zero
tests from it and exits **green vacuously**, which looks exactly like a pass.
`run_tests.py` reports it as `NOTESTS` for the same reason. Expect
`CHECK PASSED: all 13 scenarios match .../baseline_S0a`.

Both must pass unchanged. If the golden master fails, read the diff before
re-baselining — a `file_name` that gained a subdirectory is expected; anything
else is a regression.

- [ ] **Step 7: Commit**

```bash
black helao/core/models/file.py helao/core/servers/active_data_file.py \
      helao/hexagon/adapters/native/data_file.py helao/core/tests/test_upload_set.py
git add helao/core/models/file.py helao/core/servers/active_data_file.py \
        helao/hexagon/adapters/native/data_file.py helao/core/tests/test_upload_set.py
git commit -m "feat(models): FileInfo.file_name is record-relative, not a basename

A driver writing into a subdirectory of the action directory produced a file
the syncer's rglob uploaded but the files list could not name. Making the
upload set files-driven requires those files to be addressable.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XwcM9LMRUctM69ktAp2VUD"
```

---

### Task 3: The syncer's upload set comes from `files`

**Files:**
- Modify: `helao/core/drivers/data/sync_driver.py:472-527` (`_is_syncable_misc_file`, `misc_files`, `hlo_files`)
- Test: `helao/core/tests/test_upload_set.py`

**Interfaces:**
- Consumes: `FileInfo.file_name` record-relative (Task 2).
- Produces: `HelaoYml.upload_files -> list[Path]`, absolute paths, nosync entries excluded. Phase 3 Task 10 replaces the `misc_files + hlo_files + process_ymls` concatenation in `sync_yml` with this one property.

- [ ] **Step 1: Write the failing tests**

Append to `helao/core/tests/test_upload_set.py`:

```python
import textwrap

from helao.core.drivers.data.sync_driver import HelaoYml


def _action_tree(tmp_path: Path, files_block: str) -> Path:
    """An action directory with an -act.yml whose files list is ``files_block``."""
    act_dir = tmp_path / "RUNS_FINISHED" / "26.35" / "0925" / "seqdir" / "expdir"
    act_dir = act_dir / "0__0__SIM__do_thing"
    act_dir.mkdir(parents=True)
    act_yml = act_dir / "260925.120000000000-act.yml"
    act_yml.write_text(
        textwrap.dedent(
            f"""\
            action_name: do_thing
            action_uuid: 11111111-1111-1111-1111-111111111111
            action_status: [finished]
            files:
            {files_block}
            """
        )
    )
    return act_yml


def test_nosync_files_are_not_in_the_upload_set(tmp_path: Path):
    """Spec §3.5: RUNS_NOSYNC is gone, so the flag itself must exclude."""
    act_yml = _action_tree(
        tmp_path,
        "  - {file_name: keep.hlo, nosync: false}\n"
        "  - {file_name: withhold.hlo, nosync: true}",
    )
    (act_yml.parent / "keep.hlo").write_text("x")
    (act_yml.parent / "withhold.hlo").write_text("x")

    names = {p.name for p in HelaoYml(act_yml).upload_files}
    assert "keep.hlo" in names
    assert "withhold.hlo" not in names


def test_registered_subdirectory_file_is_in_the_upload_set(tmp_path: Path):
    act_yml = _action_tree(
        tmp_path, "  - {file_name: subdir/instrument.spc, nosync: false}"
    )
    sub = act_yml.parent / "subdir"
    sub.mkdir()
    (sub / "instrument.spc").write_text("x")

    rels = {
        p.relative_to(act_yml.parent).as_posix()
        for p in HelaoYml(act_yml).upload_files
    }
    assert rels == {"subdir/instrument.spc"}


def test_staging_file_is_not_in_the_upload_set(tmp_path: Path):
    """The sync-uploads-glob-not-action-files defect, prevented structurally."""
    act_yml = _action_tree(tmp_path, "  - {file_name: real.hlo, nosync: false}")
    (act_yml.parent / "real.hlo").write_text("x")
    (act_yml.parent / ".a1b2c3.tmp").write_text("x")

    names = {p.name for p in HelaoYml(act_yml).upload_files}
    assert names == {"real.hlo"}


def test_unregistered_file_is_reported_but_not_uploaded(tmp_path: Path, caplog):
    """Spec §3.5.1: the gap is made visible, not silently closed or uploaded."""
    act_yml = _action_tree(tmp_path, "  - {file_name: real.hlo, nosync: false}")
    (act_yml.parent / "real.hlo").write_text("x")
    (act_yml.parent / "orphan.spc").write_text("x")

    yml = HelaoYml(act_yml)
    names = {p.name for p in yml.upload_files}
    assert "orphan.spc" not in names

    with caplog.at_level("WARNING"):
        yml.warn_unregistered_files()
    assert "orphan.spc" in caplog.text


def test_sidecars_are_not_reported_as_unregistered(tmp_path: Path):
    """Spec §4.5 puts .prg beside the yml; it must not look like a gap.

    _is_syncable_misc_file excludes .yml, .hlo, .lock and .tmp -- but NOT
    .prg. The sidecar escapes it today purely because it is written into
    RUNS_SYNCED while the record being globbed is still in RUNS_FINISHED.
    Once the two are colocated, an unguarded reconciliation warning fires on
    every record ever synced.
    """
    act_yml = _action_tree(tmp_path, "  - {file_name: real.hlo, nosync: false}")
    (act_yml.parent / "real.hlo").write_text("x")
    (act_yml.parent / "260925.120000000000-act.prg").write_text("s3: true\napi: true\n")
    (act_yml.parent / "260925.120000000000-act.lock").write_text("")

    assert HelaoYml(act_yml).warn_unregistered_files() == []
```

- [ ] **Step 2: Run them to see them fail**

```bash
timeout 300 /home/dan/miniforge3/envs/helao/bin/python -m pytest \
    helao/core/tests/test_upload_set.py -v
```

Expected: `AttributeError: 'HelaoYml' object has no attribute 'upload_files'`.

- [ ] **Step 3: Add `upload_files` and `warn_unregistered_files`**

Insert into `HelaoYml` in `helao/core/drivers/data/sync_driver.py`, beside the
existing `misc_files` / `hlo_files` properties:

```python
    @property
    def upload_files(self) -> list[Path]:
        """Files this record ships, named by the record itself.

        The record's own ``files`` list is the authority, not a directory
        glob. A glob cannot see ``FileInfo.nosync``, which is the only thing
        keeping withheld data off S3 now that ``RUNS_NOSYNC`` no longer
        exists (spec §3.5); and a glob sweeps up whatever is transiently
        present, which is how ``.<hex>.tmp`` staging objects reached
        ``raw_data/``.

        Names are resolved relative to this record's directory and may name a
        subdirectory (spec §3.5.1). A named file that is not on disk is
        skipped here and surfaced by the existing pending-pruning path, not
        raised: a post-hoc converter can write the yml before its payloads.

        Experiments and sequences carry no ``files`` list; their payload is
        the yml plus the colocated ``*-prc.yml``, which :attr:`process_ymls`
        already handles.
        """
        if self.type != "action":
            return []
        meta = yml_load(self.target, fast=True) or {}
        out = []
        for entry in meta.get("files") or []:
            entry = entry or {}
            if entry.get("nosync"):
                continue
            name = entry.get("file_name")
            if not name:
                continue
            candidate = self.targetdir / str(name).replace("\\", "/")
            if candidate.is_file():
                out.append(candidate)
        return out

    def warn_unregistered_files(self) -> list[Path]:
        """Log files present on disk that ``files`` does not name.

        Migration aid for spec §3.5.1: a writer that produces output without
        registering it used to be carried by the glob and is now dropped.
        This makes that visible at the station rather than silent. It is not
        a fallback -- the returned files are reported, never uploaded.
        """
        if self.type != "action":
            return []
        meta = yml_load(self.target, fast=True) or {}
        named = {
            str((e or {}).get("file_name", "")).replace("\\", "/")
            for e in (meta.get("files") or [])
        }
        unregistered = []
        for p in self.targetdir.rglob("*"):
            if not p.is_file() or not self._is_syncable_misc_file(p):
                continue
            # _is_syncable_misc_file excludes neither .prg nor .lock. They
            # escape it today only because the sidecar is written under
            # RUNS_SYNCED while the record being globbed is under
            # RUNS_FINISHED -- two different trees. Spec §4.5 moves the
            # sidecar beside its own yml, so without this both would be
            # reported on every single record and the warning would be noise
            # from the first run.
            if p.suffix in (".prg", ".lock"):
                continue
            if p.relative_to(self.targetdir).as_posix() in named:
                continue
            unregistered.append(p)
        for p in unregistered:
            LOGGER.warning(
                f"{p} is present in {self.targetdir.name} but not named in its "
                "action's files list; it will not be uploaded. Register it in "
                "the producing driver or accept the loss (spec §3.5.1)."
            )
        return unregistered
```

Leave `_is_syncable_misc_file`, `misc_files` and `hlo_files` in place for now:
`warn_unregistered_files` uses the predicate, and Phase 3 Task 10 is what
removes the two properties from the sync path.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
timeout 300 /home/dan/miniforge3/envs/helao/bin/python -m pytest \
    helao/core/tests/test_upload_set.py -v
```

Expected: 9 passed (4 from Task 2, 5 from this task).

- [ ] **Step 5: Prove each guard is falsifiable**

Three separate mutations, each run and then restored:

1. Delete the `if entry.get("nosync"): continue` line.
   Expected: `test_nosync_files_are_not_in_the_upload_set` FAILS.
   **This is the most important mutation in the plan** — if this test still
   passes, a station will ship data it deliberately withholds.
2. Replace `self.targetdir / str(name)...` with `self.targetdir / Path(name).name`.
   Expected: `test_registered_subdirectory_file_is_in_the_upload_set` FAILS.
3. Delete the `LOGGER.warning(...)` loop body.
   Expected: `test_unregistered_file_is_reported_but_not_uploaded` FAILS.
4. Delete the `if p.suffix in (".prg", ".lock"): continue` guard.
   Expected: `test_sidecars_are_not_reported_as_unregistered` FAILS. Without
   it the station gets two spurious WARNINGs per record from the first run
   after cut-over, which trains everyone to ignore the one warning that
   matters.

- [ ] **Step 6: Confirm the existing syncer suite is unaffected**

```bash
for f in helao/core/tests/test_sync_staging_files.py \
         helao/core/tests/unit_test_sync_relative_paths.py \
         helao/core/tests/test_orphan_record_defer.py \
         helao/hexagon/tests/test_native_sync_parity.py; do
  timeout 600 /home/dan/miniforge3/envs/helao/bin/python -m pytest "$f" -v
done
```

All must pass. Nothing in this task changes the sync path yet — only adds two
members — so a failure here means the new property broke an import or a shared
fixture.

- [ ] **Step 7: Commit**

```bash
black helao/core/drivers/data/sync_driver.py helao/core/tests/test_upload_set.py
git add helao/core/drivers/data/sync_driver.py helao/core/tests/test_upload_set.py
git commit -m "feat(sync): HelaoYml.upload_files, driven by the record's files list

A directory glob cannot see FileInfo.nosync and sweeps up whatever is
transiently present. The record's own files list is the authority for what
ships. Adds warn_unregistered_files so a writer that produces output without
registering it is visible rather than silently dropped.

Not yet wired into sync_yml; that is Phase 3.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XwcM9LMRUctM69ktAp2VUD"
```

---

# Phase 2 — The journal module, built and wired but not yet load-bearing

The journal is written alongside the existing folder-state machinery. Nothing
reads it for a decision until Phase 3, so this phase is safe to ship and safe to
leave running at a station for a while before the cut-over.

---

### Task 4: `run_state.py` — append, replay, compact

**Files:**
- Create: `helao/helpers/run_state.py`
- Test: `helao/core/tests/test_run_state.py`

**Interfaces:**
- Consumes: nothing. This module imports only the stdlib and `helao.helpers.helao_logging`. It must not import a server, a model, or the syncer — Task 6 wires it in from the outside.
- Produces:
  - `RunStateJournal(states_root, server_key)` with `.path`, `.append(uuid, kind, state, path, parent=None)`, `.working_set() -> dict[str, dict]`, `.compact()`.
  - `root_relative(path, root) -> str` — root-relative, forward-slash. Tasks 6, 9 and 10 all record paths through this one function.
  - Module constants `ACTIVE = "active"`, `UNSYNCED = "unsynced"`, `DONE = "done"`.
  - `COMPACT_MIN_LINES = 1000`, `COMPACT_RATIO = 10`.

- [ ] **Step 1: Write the failing tests**

```python
"""The per-server run-state journal (spec §4)."""

import json
from pathlib import Path

import pytest

from helao.helpers.run_state import (
    ACTIVE,
    DONE,
    UNSYNCED,
    RunStateJournal,
)

UUID_A = "11111111-1111-1111-1111-111111111111"
UUID_B = "22222222-2222-2222-2222-222222222222"


def test_appended_record_is_in_the_working_set(tmp_path: Path):
    j = RunStateJournal(tmp_path, "SIM")
    j.append(UUID_A, "action", ACTIVE, "RUNS/2026/0925/094102__s__l/e/a")
    assert set(j.working_set()) == {UUID_A}
    assert j.working_set()[UUID_A]["state"] == ACTIVE


def test_last_line_wins(tmp_path: Path):
    j = RunStateJournal(tmp_path, "SIM")
    j.append(UUID_A, "action", ACTIVE, "RUNS/a")
    j.append(UUID_A, "action", UNSYNCED, "RUNS/a")
    assert j.working_set()[UUID_A]["state"] == UNSYNCED


def test_done_evicts_rather_than_marking(tmp_path: Path):
    """Spec §3 D3: absence means done; nothing queries for done records."""
    j = RunStateJournal(tmp_path, "SIM")
    j.append(UUID_A, "action", ACTIVE, "RUNS/a")
    j.append(UUID_B, "action", ACTIVE, "RUNS/b")
    j.append(UUID_A, "action", DONE, "RUNS/a")
    assert set(j.working_set()) == {UUID_B}


def test_stored_path_is_forward_slash(tmp_path: Path):
    """Spec §9: a journal is byte-identical across platforms."""
    j = RunStateJournal(tmp_path, "SIM")
    j.append(UUID_A, "action", ACTIVE, "RUNS\\2026\\0925\\seq")
    line = json.loads(j.path.read_text().splitlines()[0])
    assert line["path"] == "RUNS/2026/0925/seq"


def test_torn_final_line_is_discarded_and_warned(tmp_path: Path, caplog):
    """Spec §4.4: a crash mid-append can only damage the last line."""
    j = RunStateJournal(tmp_path, "SIM")
    j.append(UUID_A, "action", ACTIVE, "RUNS/a")
    j.append(UUID_B, "action", ACTIVE, "RUNS/b")
    with j.path.open("a") as f:
        f.write('{"uuid": "333', )  # truncated, no newline

    with caplog.at_level("WARNING"):
        ws = j.working_set()
    assert set(ws) == {UUID_A, UUID_B}
    assert "discarding" in caplog.text.lower()


def test_corruption_before_the_last_line_raises(tmp_path: Path):
    """A bad line anywhere else is real corruption, not a torn write."""
    j = RunStateJournal(tmp_path, "SIM")
    j.append(UUID_A, "action", ACTIVE, "RUNS/a")
    lines = j.path.read_text().splitlines()
    j.path.write_text("not json at all\n" + "\n".join(lines) + "\n")
    with pytest.raises(ValueError):
        j.working_set()


def _raw_append(journal: RunStateJournal, uuid: str, state: str, path: str) -> None:
    """Append a line without going through ``append``'s compaction check.

    Building a >1000-line file with ``append`` is impossible: the automatic
    compaction under test here fires partway through the setup and empties
    the file. This is the only place that matters, so the test writes the
    same record shape by hand rather than the module growing a seam for it.
    """
    journal.states_root.mkdir(parents=True, exist_ok=True)
    with journal.path.open("a", encoding="utf-8") as f:
        record = {
            "ts": "2026-09-25T09:41:02",
            "uuid": uuid,
            "kind": "action",
            "state": state,
            "path": path,
            "parent": None,
        }
        f.write(json.dumps(record, separators=(",", ":")) + "\n")


def test_compaction_drops_tombstones_and_preserves_survivors(tmp_path: Path):
    j = RunStateJournal(tmp_path, "SIM")
    for _ in range(600):
        _raw_append(j, UUID_A, ACTIVE, "RUNS/a")
        _raw_append(j, UUID_A, DONE, "RUNS/a")
    _raw_append(j, UUID_B, ACTIVE, "RUNS/b")
    before = len(j.path.read_text().splitlines())
    assert before > 1000

    j.compact()
    after = j.path.read_text().splitlines()
    assert len(after) == 1
    assert json.loads(after[0])["uuid"] == UUID_B
    assert set(j.working_set()) == {UUID_B}


def test_compaction_does_not_fire_below_the_line_floor(tmp_path: Path):
    """Spec §4.4: a two-record station must not compact constantly."""
    j = RunStateJournal(tmp_path, "SIM")
    for _ in range(20):
        j.append(UUID_A, "action", ACTIVE, "RUNS/a")
        j.append(UUID_A, "action", DONE, "RUNS/a")
    assert len(j.path.read_text().splitlines()) == 40


def test_compaction_fires_automatically_once_both_thresholds_are_met(tmp_path):
    j = RunStateJournal(tmp_path, "SIM")
    j.append(UUID_B, "action", ACTIVE, "RUNS/b")
    for _ in range(600):
        j.append(UUID_A, "action", ACTIVE, "RUNS/a")
        j.append(UUID_A, "action", DONE, "RUNS/a")
    # Compaction fires at line 1001 -- both thresholds are met (1001 > 1000,
    # and 1001 > 10 * 1 live record) -- so the file never reaches 1201.
    assert len(j.path.read_text().splitlines()) < 1000
    assert set(j.working_set()) == {UUID_B}


def test_missing_file_is_an_empty_working_set(tmp_path: Path):
    assert RunStateJournal(tmp_path, "NEVERWRITTEN").working_set() == {}
```

- [ ] **Step 2: Run them to see them fail**

```bash
timeout 300 /home/dan/miniforge3/envs/helao/bin/python -m pytest \
    helao/core/tests/test_run_state.py -v
```

Expected: `ModuleNotFoundError: No module named 'helao.helpers.run_state'`.

- [ ] **Step 3: Write the module**

```python
"""Append-only per-server journal of run records that are not yet done.

HELAO used to encode a record's lifecycle in the name of the directory it
lived in, so a state change meant copying a tree. This journal holds that
state as data instead: one file per writing server under ``<root>/STATES``,
one JSON object per line, appended.

Only the live working set is persisted. A record that reaches a terminal
state gets a ``done`` tombstone, and compaction drops it entirely -- absence
means done, and nothing ever queries for a done record (spec §3 D3). A
station's working set is therefore tens to hundreds of entries regardless of
how long it has been running.

Exactly one process writes each file (spec §4.1), so there is no locking
here. A crash during an append can only truncate the final line; every
earlier record is intact, which is the reason for an append-only journal
rather than a rewritten document.

The journal is an index, not the source of truth. ``rebuild_from_tree``
reconstructs it from the run tree (spec §4.5).

Spec: docs/superpowers/specs/2026-09-25-runs-layout-and-state-journal-design.md §4
"""

__all__ = [
    "ACTIVE",
    "COMPACT_MIN_LINES",
    "COMPACT_RATIO",
    "DONE",
    "UNSYNCED",
    "RunStateJournal",
    "root_relative",
]

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from helao.helpers import helao_logging as logging

LOGGER = logging.LOGGER if logging.LOGGER is not None else logging.make_logger(__file__)

ACTIVE = "active"
UNSYNCED = "unsynced"
DONE = "done"

#: Compaction fires only when the file is both absolutely large and mostly
#: dead weight. The floor stops a quiet station from compacting constantly;
#: the ratio ties the trigger to how much of the file is tombstones rather
#: than to a size someone guessed. Starting points, to be checked against a
#: real campaign's line counts (spec §4.4).
COMPACT_MIN_LINES = 1000
COMPACT_RATIO = 10


def root_relative(path, root) -> str:
    """A station-root-relative, forward-slash path (spec §4.2).

    Absolute paths recorded into sidecars are what made moving a station root
    strand records forever, so nothing this module persists is absolute. A
    path outside ``root`` is returned as-is rather than raising: the caller is
    recording, not validating, and a surprising path is more useful in the
    journal than an exception during a finish.
    """
    try:
        return Path(path).resolve().relative_to(Path(str(root)).resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()


class RunStateJournal:
    """One server's journal of records that are still active or unsynced.

    Args:
        states_root: The station's ``<root>/STATES`` directory.
        server_key: The writing server's config key, e.g. ``ORCH`` or ``SYNC``.
    """

    def __init__(self, states_root, server_key: str):
        self.states_root = Path(states_root)
        self.server_key = server_key
        self.path = self.states_root / f"runstate_{server_key}.jsonl"

    def append(
        self,
        uuid: str,
        kind: str,
        state: str,
        path: str,
        parent: Optional[str] = None,
    ) -> None:
        """Record one state transition and compact if the file has earned it.

        Args:
            uuid: The record's action/experiment/sequence uuid.
            kind: ``action`` | ``experiment`` | ``sequence``.
            state: ``active`` | ``unsynced`` | ``done``.
            path: The record's directory, **relative to the station root**,
                forward-slash separated. Absolute paths are what made moving
                a station root strand records forever; the journal must not
                reintroduce that (spec §4.2).
            parent: Parent record uuid, or ``None`` for a sequence.
        """
        record = {
            "ts": datetime.now().isoformat(),
            "uuid": str(uuid),
            "kind": kind,
            "state": state,
            "path": str(path).replace("\\", "/"),
            "parent": str(parent) if parent else None,
        }
        self.states_root.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, separators=(",", ":")) + "\n")
        self._maybe_compact()

    def working_set(self) -> dict:
        """Records that are not done, keyed by uuid, newest state per uuid.

        Raises:
            ValueError: A line other than the last one does not parse, which
                is real corruption rather than a torn write.
        """
        return self._replay()[0]

    def compact(self) -> None:
        """Rewrite the file as one line per surviving record.

        Written to a ``.tmp`` sibling, flushed and fsynced, then
        ``os.replace``'d onto the live name, so a reader either sees the whole
        old file or the whole new one.
        """
        survivors, _ = self._replay()
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        self.states_root.mkdir(parents=True, exist_ok=True)
        with tmp.open("w", encoding="utf-8") as f:
            for record in survivors.values():
                f.write(json.dumps(record, separators=(",", ":")) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)

    def _replay(self) -> tuple:
        """Return ``(working_set, line_count)``."""
        if not self.path.exists():
            return {}, 0
        lines = self.path.read_text(encoding="utf-8").splitlines()
        records: dict = {}
        for i, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                if i == len(lines) - 1:
                    LOGGER.warning(
                        f"Discarding torn final line of {self.path}: {exc}. "
                        "A crash during an append damages only the last record."
                    )
                    continue
                raise ValueError(
                    f"{self.path} line {i + 1} is corrupt: {exc}. Rebuild the "
                    "journal from the run tree (spec §4.5)."
                ) from exc
            uuid = record.get("uuid")
            if not uuid:
                continue
            if record.get("state") == DONE:
                records.pop(uuid, None)
            else:
                records[uuid] = record
        return records, len(lines)

    def _maybe_compact(self) -> None:
        if not self.path.exists():
            return
        survivors, line_count = self._replay()
        if line_count < COMPACT_MIN_LINES:
            return
        if line_count < COMPACT_RATIO * max(len(survivors), 1):
            return
        LOGGER.debug(
            f"Compacting {self.path.name}: {line_count} lines, "
            f"{len(survivors)} live records."
        )
        self.compact()
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
timeout 300 /home/dan/miniforge3/envs/helao/bin/python -m pytest \
    helao/core/tests/test_run_state.py -v
```

Expected: 10 passed. (`_raw_append` is a helper, not a test, so the count is
10 rather than 11.)

- [ ] **Step 5: Prove the guards are falsifiable**

Four mutations, each run then restored:

1. Change `records.pop(uuid, None)` to `records[uuid] = record`.
   Expected: `test_done_evicts_rather_than_marking` FAILS.
2. Delete `.replace("\\", "/")` in `append`.
   Expected: `test_stored_path_is_forward_slash` FAILS.
3. Change `if i == len(lines) - 1:` to `if True:`.
   Expected: `test_corruption_before_the_last_line_raises` FAILS.
4. Delete the `if line_count < COMPACT_MIN_LINES: return` guard.
   Expected: `test_compaction_does_not_fire_below_the_line_floor` FAILS.

- [ ] **Step 6: Commit**

```bash
black helao/helpers/run_state.py helao/core/tests/test_run_state.py
git add helao/helpers/run_state.py helao/core/tests/test_run_state.py
git commit -m "feat(helpers): append-only per-server run-state journal

One JSONL file per writing server under STATES, holding only records that
are still active or unsynced. A done record is tombstoned and dropped at
compaction; absence means done.

Single writer per file, so no locking. A crash mid-append can damage only
the final line, which replay discards with a warning; corruption anywhere
else raises and falls through to a rebuild.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XwcM9LMRUctM69ktAp2VUD"
```

---

### Task 5: Rebuild the journal from the run tree

**Files:**
- Modify: `helao/helpers/run_state.py`
- Test: `helao/core/tests/test_run_state.py`

**Interfaces:**
- Consumes: `RunStateJournal`, `UNSYNCED` (Task 4).
- Produces: `rebuild_from_tree(runs_root, states_root, server_key) -> RunStateJournal`. Task 6 calls it on startup when `working_set()` raises.

- [ ] **Step 1: Write the failing tests**

Append to `helao/core/tests/test_run_state.py`:

```python
from helao.helpers.run_state import rebuild_from_tree


def _record(runs_root: Path, rel: str, stem: str, prg: bool, complete: bool):
    """A record directory with a yml and optionally a .prg beside it."""
    d = runs_root / rel
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{stem}.yml").write_text("action_name: x\n")
    if prg:
        state = "true" if complete else "false"
        (d / f"{stem}.prg").write_text(f"s3: {state}\napi: {state}\n")
    return d


def test_record_with_a_complete_prg_is_done(tmp_path: Path):
    runs = tmp_path / "RUNS"
    _record(runs, "2026/0925/seq", "260925.120000000000-seq", prg=True, complete=True)
    j = rebuild_from_tree(runs, tmp_path / "STATES", "SYNC")
    assert j.working_set() == {}


def test_record_without_a_prg_is_unsynced(tmp_path: Path):
    runs = tmp_path / "RUNS"
    _record(runs, "2026/0925/seq", "260925.120000000000-seq", prg=False, complete=False)
    j = rebuild_from_tree(runs, tmp_path / "STATES", "SYNC")
    ws = j.working_set()
    assert len(ws) == 1
    assert next(iter(ws.values()))["state"] == UNSYNCED


def test_record_with_an_incomplete_prg_is_unsynced(tmp_path: Path):
    runs = tmp_path / "RUNS"
    _record(runs, "2026/0925/seq", "260925.120000000000-seq", prg=True, complete=False)
    assert len(rebuild_from_tree(runs, tmp_path / "STATES", "SYNC").working_set()) == 1


def test_rebuilt_paths_are_root_relative_and_forward_slash(tmp_path: Path):
    runs = tmp_path / "RUNS"
    _record(runs, "2026/0925/seq", "260925.120000000000-seq", prg=False, complete=False)
    j = rebuild_from_tree(runs, tmp_path / "STATES", "SYNC")
    stored = next(iter(j.working_set().values()))["path"]
    assert stored == "RUNS/2026/0925/seq"


def test_rebuild_classifies_all_three_kinds(tmp_path: Path):
    runs = tmp_path / "RUNS"
    base = "2026/0925/seq"
    _record(runs, base, "260925.120000000000-seq", prg=False, complete=False)
    _record(runs, f"{base}/exp", "260925.120001000000-exp", prg=False, complete=False)
    _record(runs, f"{base}/exp/act", "260925.120002000000-act", prg=False, complete=False)
    kinds = {r["kind"] for r in rebuild_from_tree(runs, tmp_path / "STATES", "SYNC").working_set().values()}
    assert kinds == {"sequence", "experiment", "action"}


def test_rebuild_overwrites_a_corrupt_journal(tmp_path: Path):
    runs = tmp_path / "RUNS"
    states = tmp_path / "STATES"
    states.mkdir()
    (states / "runstate_SYNC.jsonl").write_text("garbage\ngarbage\n")
    _record(runs, "2026/0925/seq", "260925.120000000000-seq", prg=False, complete=False)
    assert len(rebuild_from_tree(runs, states, "SYNC").working_set()) == 1
```

- [ ] **Step 2: Run them to see them fail**

```bash
timeout 300 /home/dan/miniforge3/envs/helao/bin/python -m pytest \
    helao/core/tests/test_run_state.py -v -k rebuild
```

Expected: `ImportError: cannot import name 'rebuild_from_tree'`.

- [ ] **Step 3: Implement `rebuild_from_tree`**

Add to `helao/helpers/run_state.py`, and add `"rebuild_from_tree"` to `__all__`:

```python
_KIND_BY_SUFFIX = {"-seq": "sequence", "-exp": "experiment", "-act": "action"}


def _prg_is_complete(prg_path: Path) -> bool:
    """Whether a ``.prg`` sidecar reports its record fully shipped.

    Read as flat text rather than through ``yml_load`` so that this module
    stays free of helao imports and a malformed sidecar degrades to
    "not complete" instead of raising mid-rebuild.
    """
    try:
        text = prg_path.read_text(encoding="utf-8")
    except OSError:
        return False
    return "s3: true" in text and "api: true" in text


def rebuild_from_tree(runs_root, states_root, server_key: str) -> "RunStateJournal":
    """Reconstruct a journal by scanning the run tree (spec §4.5).

    The journal is an index; the ``.prg`` sidecar beside each record's yml is
    the authoritative receipt. A record whose ``.prg`` is present and complete
    is done and is not emitted. Everything else is emitted as ``unsynced``.

    This is a full walk of ``runs_root``, which is affordable because the new
    tree accumulates only from cut-over forward -- years of history stay in the
    legacy ``RUNS_*`` trees and are never scanned. It runs on cold start after
    a lost or corrupt journal, never on a hot path.

    Args:
        runs_root: The station's ``<root>/RUNS`` directory.
        states_root: The station's ``<root>/STATES`` directory.
        server_key: Journal owner, e.g. ``SYNC``.

    Returns:
        The rebuilt, already-written journal.
    """
    runs_root = Path(runs_root)
    journal = RunStateJournal(states_root, server_key)
    root_name = runs_root.name
    entries = []

    for yml in sorted(runs_root.rglob("*.yml")):
        kind = _KIND_BY_SUFFIX.get(yml.stem[-4:])
        if kind is None:
            continue
        if _prg_is_complete(yml.with_suffix(".prg")):
            continue
        rel = yml.parent.relative_to(runs_root).as_posix()
        entries.append(
            {
                "ts": datetime.now().isoformat(),
                "uuid": yml.stem,
                "kind": kind,
                "state": UNSYNCED,
                "path": f"{root_name}/{rel}" if rel != "." else root_name,
                "parent": None,
            }
        )

    journal.states_root.mkdir(parents=True, exist_ok=True)
    tmp = journal.path.with_suffix(journal.path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for record in entries:
            f.write(json.dumps(record, separators=(",", ":")) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, journal.path)
    LOGGER.info(
        f"Rebuilt {journal.path.name} from {runs_root}: {len(entries)} unsynced record(s)."
    )
    return journal
```

**Superseded — see A12.** An earlier draft of this task keyed a rebuilt record
by the yml stem, on the grounds that the filesystem does not carry the uuid in
the path and the only consumer is addressed by path. That was wrong: the
*journal* is keyed by uuid and eviction is `pop(uuid)`, so a stem-keyed record
is never evicted by the syncer's real-uuid tombstone and survives every
compaction. Read the uuid out of the yml. A12 has the details, including why a
head-only read is not enough.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
timeout 300 /home/dan/miniforge3/envs/helao/bin/python -m pytest \
    helao/core/tests/test_run_state.py -v
```

Expected: 16 passed.

- [ ] **Step 5: Prove the guards are falsifiable**

1. Change `_prg_is_complete` to `return True`.
   Expected: `test_record_without_a_prg_is_unsynced` FAILS.
2. Change `"s3: true" in text and "api: true" in text` to `"s3:" in text`.
   Expected: `test_record_with_an_incomplete_prg_is_unsynced` FAILS.
3. Replace `.as_posix()` with `str(...)` — on Linux this will not fail, so
   instead assert the test by making `rel` absolute: change
   `yml.parent.relative_to(runs_root)` to `yml.parent`.
   Expected: `test_rebuilt_paths_are_root_relative_and_forward_slash` FAILS.

- [ ] **Step 6: Commit**

```bash
black helao/helpers/run_state.py helao/core/tests/test_run_state.py
git add helao/helpers/run_state.py helao/core/tests/test_run_state.py
git commit -m "feat(helpers): rebuild a run-state journal from the run tree

The journal is an index, not the source of truth. The .prg sidecar beside
each record's yml is the receipt; a record whose sidecar is missing or
incomplete is re-emitted as unsynced. Losing a journal costs a cold-start
scan, not data.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XwcM9LMRUctM69ktAp2VUD"
```

---

### Task 6: Wire the journal into the servers, add `sync_finished`

**Files:**
- Modify: `helao/core/servers/base.py` (append `active` on action start, `done` on finish)
- Modify: `helao/core/servers/orch.py` (same for experiments and sequences)
- Modify: `helao/deploy/hte/servers/action/sync_server.py` (append `unsynced` on `/finish_yml`, `done` on sync success)
- Modify: `helao/core/drivers/data/sync_driver.py` (call the SYNC journal at the two transition points)
- Modify: `helao/helpers/config_loader.py` (default `sync_finished` to `True`)
- Test: `helao/core/tests/test_run_state_wiring.py` (create)

**Interfaces:**
- Consumes: `RunStateJournal`, `ACTIVE`, `UNSYNCED`, `DONE`, `rebuild_from_tree` (Tasks 4-5).
- Produces: `Base.run_journal` and `Orch.run_journal` attributes, both `Optional[RunStateJournal]` (`None` when the config has no `root`). `world_cfg["sync_finished"]` as a bool, default `True`.

- [ ] **Step 1: Write the failing test**

```python
"""The journal records a record's life and evicts it at the end (spec §4.3)."""

from pathlib import Path

from helao.helpers.run_state import ACTIVE, DONE, UNSYNCED, RunStateJournal


def test_sync_finished_defaults_to_true():
    from helao.helpers.config_loader import sync_finished_enabled

    assert sync_finished_enabled({}) is True
    assert sync_finished_enabled({"sync_finished": False}) is False
    assert sync_finished_enabled({"sync_finished": True}) is True


def test_no_sync_server_means_sync_finished_is_false():
    """Spec §6: a group with no syncer behaves as sync_finished: false."""
    from helao.helpers.config_loader import sync_finished_enabled

    cfg = {"sync_finished": True, "servers": {"ORCH": {"group": "orchestrator"}}}
    assert sync_finished_enabled(cfg) is False


def test_a_record_that_finishes_without_syncing_is_evicted(tmp_path: Path):
    """sync_finished: false -> straight to done, never enters the unsynced set."""
    producer = RunStateJournal(tmp_path, "SIM")
    producer.append("u1", "action", ACTIVE, "RUNS/a")
    producer.append("u1", "action", DONE, "RUNS/a")
    assert producer.working_set() == {}


def test_handoff_moves_the_record_between_journals(tmp_path: Path):
    """Spec §4.1: exactly one writer per file; the producer hands off to SYNC."""
    producer = RunStateJournal(tmp_path, "SIM")
    syncer = RunStateJournal(tmp_path, "SYNC")

    producer.append("u1", "action", ACTIVE, "RUNS/a")
    assert set(producer.working_set()) == {"u1"}

    producer.append("u1", "action", DONE, "RUNS/a")
    syncer.append("u1", "action", UNSYNCED, "RUNS/a")
    assert producer.working_set() == {}
    assert set(syncer.working_set()) == {"u1"}

    syncer.append("u1", "action", DONE, "RUNS/a")
    assert syncer.working_set() == {}
    assert producer.path != syncer.path
```

- [ ] **Step 2: Run it to see it fail**

```bash
timeout 300 /home/dan/miniforge3/envs/helao/bin/python -m pytest \
    helao/core/tests/test_run_state_wiring.py -v
```

Expected: `ImportError: cannot import name 'sync_finished_enabled'`.

- [ ] **Step 3: Add the config helper**

In `helao/helpers/config_loader.py`:

```python
def sync_finished_enabled(world_cfg: Optional[dict]) -> bool:
    """Whether a finished record should enter the unsynced set (spec §6).

    Defaults to ``True``. A group with no syncer server is always ``False``
    regardless of the key: there is nothing to hand a record to, so the
    record is done the moment it finishes.

    Distinct from the per-record ``sync_data`` field, which has never meant
    "skip sync" -- it means "do not upload this record's .hlo payloads".
    """
    from helao.helpers.server_keys import resolve_sync_server_key

    cfg = world_cfg or {}
    if resolve_sync_server_key(cfg) is None:
        return False
    return bool(cfg.get("sync_finished", True))
```

- [ ] **Step 4: Construct the journal on each server**

In `Base.__init__` (`helao/core/servers/base.py`), after `self.helaodirs` is
resolved:

```python
        self.run_journal = (
            RunStateJournal(self.helaodirs.states_root, self.server.server_name)
            if self.helaodirs.states_root
            else None
        )
```

Do the same in `Orch.__init__`. Add the import
`from helao.helpers.run_state import ACTIVE, DONE, RunStateJournal` to both.

- [ ] **Step 5: Append at the transition points**

Action start, in `Base`'s active-creation path, immediately after the output
directory is created:

```python
        if self.base.run_journal is not None:
            self.base.run_journal.append(
                str(self.action.action_uuid),
                "action",
                ACTIVE,
                self._journal_path(),
                parent=str(self.action.experiment_uuid),
            )
```

with the path helper on the same class:

```python
    def _journal_path(self) -> str:
        """This record's directory relative to the station root, forward-slash.

        Absolute paths recorded into sidecars are what made moving a station
        root strand records forever (spec §4.2).
        """
        root = Path(str(self.base.helaodirs.root))
        full = Path(str(self.base.helaodirs.save_root)) / self.action.action_output_dir
        return full.resolve().relative_to(root.resolve()).as_posix()
```

Action finish, inside `move_dir`'s success path in `helao/helpers/yml_tools.py`
alongside the existing `yml_finisher` call — the producing server evicts, and
`yml_finisher` is what tells SYNC (which appends its own `unsynced`):

```python
                        if base is not None and getattr(base, "run_journal", None):
                            base.run_journal.append(
                                str(getattr(hobj, f"{obj_type}_uuid")),
                                obj_type,
                                DONE,
                                "",
                            )
```

Experiment and sequence start/finish get the same treatment in `Orch`, using
`experiment_output_dir` / `sequence_output_dir` and the matching uuid fields.

- [ ] **Step 6: Append on the SYNC side**

In `helao/core/drivers/data/sync_driver.py`, in `SyncDriver.__init__`:

```python
        self.run_journal = (
            RunStateJournal(self.base.helaodirs.states_root, "SYNC")
            if self.base.helaodirs.states_root
            else None
        )
```

On enqueue (in the method behind `/finish_yml`), append `UNSYNCED`. In
`sync_yml`, at the point where `prog.s3_done and prog.api_done` is satisfied,
append `DONE`. Both use the same root-relative, forward-slash path rule.

On `SyncDriver` startup, guard the replay:

```python
        if self.run_journal is not None:
            try:
                self.run_journal.working_set()
            except ValueError:
                LOGGER.warning(
                    "SYNC journal is corrupt; rebuilding from the run tree."
                )
                rebuild_from_tree(
                    Path(str(self.base.helaodirs.save_root)),
                    self.base.helaodirs.states_root,
                    "SYNC",
                )
```

- [ ] **Step 7: Run the wiring tests and the existing syncer suite**

```bash
timeout 300 /home/dan/miniforge3/envs/helao/bin/python -m pytest \
    helao/core/tests/test_run_state_wiring.py -v
for f in helao/core/tests/test_sync_staging_files.py \
         helao/core/tests/test_orphan_record_defer.py \
         helao/hexagon/tests/test_native_sync_parity.py \
         helao/deploy/hte/tests/test_sync_server_recovery.py; do
  timeout 600 /home/dan/miniforge3/envs/helao/bin/python -m pytest "$f" -v
done
```

All must pass. The journal is additive in this phase — no existing behaviour
changes — so any failure here is a wiring bug, not an expected re-baseline.

- [ ] **Step 8: Launch a real group and inspect the journals**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
/home/dan/miniforge3/envs/helao/bin/python launch.py simulate
# run one short sequence from the operator UI, then:
cat <root>/STATES/runstate_*.jsonl
```

Expected: the producing server's journal is empty at rest (every record
evicted), `runstate_SYNC.jsonl` is empty once the sequence syncs, and each file
grew and shrank during the run. A journal that still names a finished record
means an eviction is missing.

- [ ] **Step 9: Commit**

```bash
black helao/core/servers/base.py helao/core/servers/orch.py \
      helao/core/drivers/data/sync_driver.py helao/helpers/yml_tools.py \
      helao/helpers/config_loader.py helao/core/tests/test_run_state_wiring.py
git add -A
git commit -m "feat(servers): write run-state journals alongside folder state

Producing servers record their own records as active and evict on finish;
SYNC owns the unsynced set. Exactly one writer per file. Adds
sync_finished (config root, default true, always false when the group has
no syncer).

Nothing reads the journal for a decision yet -- the folder-state machinery
is still authoritative until Phase 3.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XwcM9LMRUctM69ktAp2VUD"
```

---

# Phase 3 — The layout cut-over

From here the journal becomes load-bearing and records stop moving. This phase
lands as one merge; a station on a half-applied Phase 3 has records in two
layouts with neither machinery fully responsible for them.

---

### Task 7: `RUNS` and `DIAG` roots

**Files:**
- Modify: `helao/core/models/run_dir.py` (whole file)
- Modify: `helao/helpers/helao_dirs.py:62-90`
- Test: `helao/core/tests/test_runs_layout.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `LEGACY_RUN_DIRS: tuple[str, ...]` — all eight historical names.
  - `run_root(root) -> Path` = `<root>/RUNS`; `diag_root(root) -> Path` = `<root>/DIAG`.
  - `is_legacy_path(path) -> bool` — true iff any path segment is in `LEGACY_RUN_DIRS`.
  - `RunDir` stays importable with its five members so the ~85 mechanical call sites keep resolving until Task 13 sweeps them.

- [ ] **Step 1: Write the failing tests**

```python
"""The single RUNS tree and the legacy vocabulary (spec §3.1, §7)."""

from pathlib import Path

import pytest

from helao.core.models.run_dir import (
    LEGACY_RUN_DIRS,
    diag_root,
    is_legacy_path,
    run_root,
)


def test_run_root_is_a_single_runs_directory():
    assert run_root("/data").name == "RUNS"


def test_diag_root_is_a_sibling_not_a_child_of_runs():
    """Spec §3.4: a manual tree is never written under RUNS."""
    assert diag_root("/data").name == "DIAG"
    assert diag_root("/data").parent == run_root("/data").parent


def test_all_eight_historical_names_are_legacy():
    """Including the three only scan_prg_ghosts knows about (spec §7)."""
    assert set(LEGACY_RUN_DIRS) == {
        "RUNS_ACTIVE",
        "RUNS_FINISHED",
        "RUNS_SYNCED",
        "RUNS_DIAG",
        "RUNS_NOSYNC",
        "RUNS_CORRUPT",
        "RUNS_REBUILD",
        "RUNS_SUPERSEDED",
    }


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/data/RUNS_SYNCED/26.35/0828/seq/f.yml", True),
        ("/data/RUNS_CORRUPT/26.35/0828/seq/f.yml", True),
        ("/data/RUNS/2026/0925/seq/f.yml", False),
        ("/data/DIAG/2026/0925/seq/f.yml", False),
        ("/data/RUNSOMETHING/2026/0925/f.yml", False),
    ],
)
def test_is_legacy_path_matches_whole_segments_only(path, expected):
    assert is_legacy_path(path) is expected


def test_helao_dirs_creates_runs_and_diag_and_no_legacy_dirs(tmp_path: Path):
    from helao.helpers.helao_dirs import _HELAO_DIRS_CACHE, helao_dirs

    _HELAO_DIRS_CACHE.clear()
    dirs = helao_dirs({"root": str(tmp_path)})
    assert (tmp_path / "RUNS").is_dir()
    assert (tmp_path / "DIAG").is_dir()
    assert not (tmp_path / "RUNS_ACTIVE").exists()
    assert Path(str(dirs.save_root)).name == "RUNS"
```

- [ ] **Step 2: Run them to see them fail**

```bash
timeout 300 /home/dan/miniforge3/envs/helao/bin/python -m pytest \
    helao/core/tests/test_runs_layout.py -v
```

Expected: `ImportError: cannot import name 'LEGACY_RUN_DIRS'`.

- [ ] **Step 3: Rewrite `run_dir.py`**

```python
"""The single run tree, and the vocabulary of the eight it replaced.

HELAO used to name a record's lifecycle state in the directory holding it, so
a reader had to search up to eight roots for one file and a state change meant
copying a tree. Records now live in one place, ``<root>/RUNS``, and never
move; state is held in the per-server journals (``helao.helpers.run_state``).

``LEGACY_RUN_DIRS`` is not dead vocabulary: existing station archives are left
exactly where they are and are never migrated (spec §7), so every reader must
keep resolving them.
"""

__all__ = [
    "ALL_RUN_DIRS",
    "LEGACY_RUN_DIRS",
    "RunDir",
    "SYNC_PROGRESSION",
    "diag_root",
    "is_legacy_path",
    "run_root",
]

from enum import Enum
from pathlib import Path

#: Every directory name a record was ever written under. The last three are
#: repair-tool vocabulary (``scan_prg_ghosts``) rather than states the servers
#: ever wrote, but a reader that meets one today must keep meeting it.
LEGACY_RUN_DIRS = (
    "RUNS_ACTIVE",
    "RUNS_FINISHED",
    "RUNS_SYNCED",
    "RUNS_DIAG",
    "RUNS_NOSYNC",
    "RUNS_CORRUPT",
    "RUNS_REBUILD",
    "RUNS_SUPERSEDED",
)


class RunDir(str, Enum):
    """Retained for the legacy read path only. Nothing writes these."""

    ACTIVE = "RUNS_ACTIVE"
    FINISHED = "RUNS_FINISHED"
    SYNCED = "RUNS_SYNCED"
    DIAG = "RUNS_DIAG"
    NOSYNC = "RUNS_NOSYNC"


SYNC_PROGRESSION = (RunDir.ACTIVE, RunDir.FINISHED, RunDir.SYNCED)
ALL_RUN_DIRS = tuple(RunDir)


def run_root(root) -> Path:
    """The station's single run tree."""
    return Path(root) / "RUNS"


def diag_root(root) -> Path:
    """Manual and diagnostic runs, kept out of RUNS entirely (spec §3.4)."""
    return Path(root) / "DIAG"


def is_legacy_path(path) -> bool:
    """Whether *path* lives under one of the pre-cut-over run trees.

    Matched on whole path segments, so ``RUNSOMETHING`` is not a false
    positive. The two layouts are trivially distinguishable because the run
    root segment differs, which is why no heuristic on the ``YY.WW``
    week-directory shape is needed.
    """
    return any(part in LEGACY_RUN_DIRS for part in Path(path).parts)
```

- [ ] **Step 4: Point `helao_dirs` at the new roots**

In `helao/helpers/helao_dirs.py`, replace

```python
        save_root = os.path.join(root, RunDir.ACTIVE.value)
```

with

```python
        save_root = str(run_root(root))
        diag_dir = str(diag_root(root))
```

add `check_dir(diag_dir)` beside the other `check_dir` calls, and change the
import to `from helao.core.models.run_dir import diag_root, run_root`.

Also update the module docstring's list of created directories: it names
`RUNS_ACTIVE` and must now name `RUNS` and `DIAG`.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
timeout 300 /home/dan/miniforge3/envs/helao/bin/python -m pytest \
    helao/core/tests/test_runs_layout.py -v
```

Expected: 9 passed.

- [ ] **Step 6: Prove the guards are falsifiable**

1. Change `is_legacy_path` to `return any(p in str(path) for p in LEGACY_RUN_DIRS)`
   and add `"/data/RUNS_SYNCEDX/f.yml"` — simpler: change the parametrize case
   `("/data/RUNSOMETHING/2026/0925/f.yml", False)` to exercise substring
   matching by renaming the segment to `RUNS_ACTIVEX`. With the substring
   implementation that case FAILS; with the segment implementation it passes.
2. Delete `check_dir(diag_dir)`.
   Expected: `test_helao_dirs_creates_runs_and_diag_and_no_legacy_dirs` FAILS.

- [ ] **Step 7: Commit**

```bash
black helao/core/models/run_dir.py helao/helpers/helao_dirs.py \
      helao/core/tests/test_runs_layout.py
git add helao/core/models/run_dir.py helao/helpers/helao_dirs.py \
        helao/core/tests/test_runs_layout.py
git commit -m "feat(core): single RUNS tree plus a DIAG sibling

run_root/diag_root replace RUNS_ACTIVE as the write targets. RunDir and the
eight historical names survive as LEGACY_RUN_DIRS for the read path; station
archives are never migrated.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XwcM9LMRUctM69ktAp2VUD"
```

---

### Task 8: The date path and the sequence label rule

**Files:**
- Modify: `helao/helpers/premodels.py:118-145`
- Test: `helao/core/tests/test_sequence_label.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `Sequence.apply_label_suffix() -> None`, mutating `sequence_label` in place. `get_sequence_dir()` returns `%Y/%m%d/%H%M%S__{name}__{label}` and computes no suffix of its own. Task 9 relies on `get_sequence_dir()` being root-relative, exactly as today.

- [ ] **Step 1: Write the failing tests**

```python
"""The plate/sample suffix lives in sequence_label itself (spec §3.3)."""

from datetime import datetime

import pytest

from helao.helpers.premodels import Sequence

TS = datetime(2026, 9, 25, 9, 41, 2)


def _seq(label, params):
    s = Sequence(sequence_name="XRFS_noStandards", sequence_label=label)
    s.sequence_params = params
    s.sequence_timestamp = TS
    s.apply_label_suffix()
    return s


@pytest.mark.parametrize(
    "label,params,expected",
    [
        # no plate -> untouched
        ("mylabel", {}, "mylabel"),
        (None, {}, "noLabel"),
        # plate absent from the label -> serial appended, check digit 1+0+1+3+1=6
        ("mylabel", {"plate_id": 10131}, "mylabel-101316"),
        # plate already named -> not appended twice
        ("run-101316", {"plate_id": 10131}, "run-101316"),
        # one sample, each of the four accepted sources
        ("m", {"plate_id": 10131, "sample_no": 42}, "m-101316-42"),
        ("m", {"plate_id": 10131, "solid_sample_no": 42}, "m-101316-42"),
        ("m", {"plate_id": 10131, "plate_sample_no": 42}, "m-101316-42"),
        ("m", {"plate_id": 10131, "plate_sample_no_list": [42]}, "m-101316-42"),
        # more than one sample -> plate only
        ("m", {"plate_id": 10131, "plate_sample_no_list": [1, 2]}, "m-101316"),
        # sample with no plate -> no suffix at all
        ("m", {"sample_no": 42}, "m"),
    ],
)
def test_label_suffix_rule(label, params, expected):
    assert _seq(label, params).sequence_label == expected


def test_source_precedence_is_first_that_yields_exactly_one():
    s = _seq(
        "m",
        {"plate_id": 10131, "sample_no": 7, "plate_sample_no_list": [1, 2, 3]},
    )
    assert s.sequence_label == "m-101316-7"


def test_applying_twice_is_idempotent():
    """init_seq may run more than once; the suffix must not stack."""
    s = _seq("m", {"plate_id": 10131, "sample_no": 42})
    s.apply_label_suffix()
    assert s.sequence_label == "m-101316-42"


def test_sequence_dir_is_year_monthday_and_uses_the_label_verbatim():
    s = _seq("m", {"plate_id": 10131})
    assert s.get_sequence_dir() == "2026/0925/094102__XRFS_noStandards__m-101316"


def test_sequence_dir_is_forward_slash():
    """Spec §9: stored run-relative paths are forward-slash on every platform."""
    assert "\\" not in _seq("m", {}).get_sequence_dir()
```

- [ ] **Step 2: Run them to see them fail**

```bash
timeout 300 /home/dan/miniforge3/envs/helao/bin/python -m pytest \
    helao/core/tests/test_sequence_label.py -v
```

Expected: `AttributeError: 'Sequence' object has no attribute 'apply_label_suffix'`.

- [ ] **Step 3: Implement the rule**

Replace `get_sequence_dir` in `helao/helpers/premodels.py` with:

```python
    #: Sequence-param keys consulted, in order, for a single sample number.
    #: The first that yields exactly one value wins; a scalar counts as one,
    #: a list only when it has one element.
    _SAMPLE_NO_KEYS = (
        "sample_no",
        "solid_sample_no",
        "plate_sample_no",
        "plate_sample_no_list",
    )

    def _single_sample_no(self):
        """The one sample number this sequence is about, or ``None``."""
        for key in self._SAMPLE_NO_KEYS:
            value = self.sequence_params.get(key)
            if value is None:
                continue
            if isinstance(value, (list, tuple)):
                if len(value) == 1:
                    return value[0]
                continue
            return value
        return None

    def apply_label_suffix(self) -> None:
        """Fold the plate (and single sample) into ``sequence_label`` itself.

        The suffix used to be computed into the directory name only, so the
        plate a sequence ran on could not be recovered from its metadata --
        the reason a plate lookup needs the API at all. Putting it in the
        label means the record carries it.

        Idempotent: ``init_seq`` can run more than once and the suffix must
        not stack. A sample number without a plate appends nothing, because
        a sample number is only meaningful as a position on a plate.
        """
        if self.sequence_label is None:
            self.sequence_label = "noLabel"
        plate = self.sequence_params.get("plate_id", "")
        if not plate:
            return
        serial = f"{plate}{sum(int(x) for x in str(plate)) % 10}"
        if serial in self.sequence_label:
            return
        self.sequence_label = f"{self.sequence_label}-{serial}"
        sample_no = self._single_sample_no()
        if sample_no is not None:
            self.sequence_label = f"{self.sequence_label}-{sample_no}"

    def get_sequence_dir(self) -> str:
        """Build the relative output directory for this sequence.

        Layout is ``%Y/%m%d/%H%M%S__name__label``, always forward-slash
        (spec §9). The plate/sample suffix is already part of
        ``sequence_label`` (:meth:`apply_label_suffix`) and is not computed
        here.
        """
        return os.path.join(
            self.sequence_timestamp.strftime("%Y"),
            self.sequence_timestamp.strftime("%m%d"),
            f"{self.sequence_timestamp.strftime('%H%M%S')}__"
            f"{self.sequence_name}__{self.sequence_label}",
        ).replace("\\", "/")
```

Note the separator fix: the existing code writes `.replace(r"\\", "/")`, which
is a two-character escape sequence and does **not** match a single Windows
backslash. Use `.replace("\\", "/")`. Apply the same correction to
`get_experiment_dir`.

Call the new method from `init_seq`, before the output dir is computed:

```python
        self.apply_label_suffix()
        if force or self.sequence_output_dir is None:
            self.sequence_output_dir = self.get_sequence_dir()
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
timeout 300 /home/dan/miniforge3/envs/helao/bin/python -m pytest \
    helao/core/tests/test_sequence_label.py -v
```

Expected: 15 passed.

- [ ] **Step 5: Prove the guards are falsifiable**

1. Delete `if serial in self.sequence_label: return`.
   Expected: the `("run-101316", ...)` case and `test_applying_twice_is_idempotent` FAIL.
2. Move `sample_no = self._single_sample_no()` above the `if not plate: return`
   and append it unconditionally.
   Expected: the `("m", {"sample_no": 42}, "m")` case FAILS.
3. Change `%Y` to `%y.%U`.
   Expected: `test_sequence_dir_is_year_monthday_and_uses_the_label_verbatim` FAILS.

- [ ] **Step 6: Commit**

```bash
black helao/helpers/premodels.py helao/core/tests/test_sequence_label.py
git add helao/helpers/premodels.py helao/core/tests/test_sequence_label.py
git commit -m "feat(premodels): RUNS/%Y/%m%d path and plate suffix in the label

The plate/sample suffix moves out of the directory name and into
sequence_label itself, so a sequence record carries the plate it ran on.
Replaces the YY.WW week directory with a readable year/monthday.

Also fixes the separator normalization, which used r'\\\\' and therefore
never matched a single backslash.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XwcM9LMRUctM69ktAp2VUD"
```

---

### Task 9: Manual runs land in DIAG; `move_dir` stops moving

**Files:**
- Modify: `helao/hexagon/domain/naming.py:77-85`
- Modify: `helao/core/servers/base.py:1017-1029`
- Modify: `helao/helpers/yml_tools.py:240-400`
- Test: `helao/core/tests/test_runs_layout.py`

**Interfaces:**
- Consumes: `diag_root`, `run_root` (Task 7); `run_journal`, `DONE` (Task 6).
- Produces: `redirect_manual_dir(save_root) -> str` returns `<root>/DIAG`. `move_dir(hobj, base, retry_delay)` keeps its signature and return contract but performs no filesystem move.

- [ ] **Step 1: Write the failing tests**

Append to `helao/core/tests/test_runs_layout.py`:

```python
def test_manual_redirect_swaps_the_root_not_a_substring(tmp_path: Path):
    from helao.hexagon.domain.naming import redirect_manual_dir

    assert redirect_manual_dir(str(tmp_path / "RUNS")) == str(tmp_path / "DIAG")


def test_manual_redirect_is_idempotent(tmp_path: Path):
    from helao.hexagon.domain.naming import redirect_manual_dir

    once = redirect_manual_dir(str(tmp_path / "RUNS"))
    assert redirect_manual_dir(once) == once


@pytest.mark.asyncio
async def test_move_dir_leaves_the_tree_exactly_where_it_is(tmp_path: Path):
    """Spec §2: a run tree is written once and never moves."""
    from helao.helpers.yml_tools import move_dir

    from helao.core.tests.run_layout_fixtures import finished_action

    hobj, base = finished_action(tmp_path)
    act_dir = Path(str(base.helaodirs.save_root)) / hobj.get_action_dir()
    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))

    await move_dir(hobj, base=base)

    after = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    assert before == after
    assert act_dir.is_dir()


@pytest.mark.asyncio
async def test_move_dir_creates_no_legacy_directory(tmp_path: Path):
    from helao.helpers.yml_tools import move_dir

    from helao.core.models.run_dir import LEGACY_RUN_DIRS
    from helao.core.tests.run_layout_fixtures import finished_action

    hobj, base = finished_action(tmp_path)
    await move_dir(hobj, base=base)

    created = {p.name for p in tmp_path.rglob("*") if p.is_dir()}
    assert created.isdisjoint(LEGACY_RUN_DIRS)
```

Create the shared fixture module `helao/core/tests/run_layout_fixtures.py`:

```python
"""A minimal finished action on disk, for layout and movement assertions."""

from pathlib import Path
from types import SimpleNamespace
from datetime import datetime

from helao.core.models.helaodirs import HelaoDirs
from helao.helpers.premodels import Action

TS = datetime(2026, 9, 25, 9, 41, 2)


def finished_action(tmp_path: Path):
    """Return ``(action, base)`` with the action's tree already written."""
    root = tmp_path
    dirs = HelaoDirs(
        root=root,
        save_root=root / "RUNS",
        states_root=root / "STATES",
    )
    act = Action(action_name="do_thing", action_server_name="SIM")
    act.action_timestamp = TS
    act.sequence_timestamp = TS
    act.experiment_timestamp = TS
    act.sequence_name = "seq"
    act.sequence_label = "noLabel"
    act.experiment_name = "exp"
    act.orch_submit_order = 0
    act.action_split = 0
    act.manual_action = False
    act.sync_data = True
    act.init_act()

    act_dir = Path(str(dirs.save_root)) / act.get_action_dir()
    act_dir.mkdir(parents=True)
    (act_dir / "260925.094102000000-act.yml").write_text("action_name: do_thing\n")

    base = SimpleNamespace(
        helaodirs=dirs,
        world_cfg={"root": str(root), "servers": {}},
        run_journal=None,
    )
    return act, base
```

- [ ] **Step 2: Run them to see them fail**

```bash
timeout 300 /home/dan/miniforge3/envs/helao/bin/python -m pytest \
    helao/core/tests/test_runs_layout.py -v
```

Expected: the two `move_dir` tests FAIL — the tree is copied and the source
removed, so `before != after`.

- [ ] **Step 3: Retarget the manual redirect**

In `helao/hexagon/domain/naming.py`:

```python
def redirect_manual_dir(path: str) -> str:
    """Point a save root at the station's DIAG tree instead of RUNS.

    Manual and diagnostic runs are written straight into ``<root>/DIAG`` and
    are never written under ``RUNS`` (spec §3.4). This replaces the old
    ``RUNS_ACTIVE`` -> ``RUNS_DIAG`` string substitution, which ran *after*
    the tree had already been written to the wrong place and then had to
    delete the parent experiment and sequence directories behind itself.

    Idempotent: a path already under DIAG is returned unchanged.
    """
    p = Path(path)
    if p.name == "DIAG":
        return str(p)
    if p.name == "RUNS":
        return str(p.parent / "DIAG")
    return str(p).replace("RUNS_ACTIVE", "RUNS_DIAG")
```

The final line is the legacy behaviour, kept so a caller handed a pre-cut-over
path still does something sane rather than silently returning it unchanged.

In `helao/core/servers/base.py`, replace lines 1017-1029:

```python
        save_root = str(self.base.helaodirs.save_root)
        if self.action.manual_action:
            save_root = redirect_manual_dir(save_root)
        if self.action.save_act:
            full_action_output_path = os.path.join(
                save_root,
                self.action.action_output_dir,
            )
            os.makedirs(full_action_output_path, exist_ok=True)
            await self.update_act_file()
```

The second, string-level `.replace("ACTIVE", "DIAG")` is deleted: the root is
already correct, and that substitution would corrupt any action whose name
happened to contain "ACTIVE".

- [ ] **Step 4: Gut `move_dir`**

Replace the whole body of `move_dir` in `helao/helpers/yml_tools.py` with:

```python
async def move_dir(hobj, base: Optional[object] = None, retry_delay: int = 5):
    """Mark an Action/Experiment/Sequence finished. Nothing moves.

    Records are written once, under ``RUNS`` (or ``DIAG`` for a manual run),
    and stay there for life; lifecycle state lives in the per-server journals
    (spec §2). What used to be ~160 lines of copy-with-60-retries followed by
    remove-with-30-retries is now an eviction from this server's journal and
    the same ``yml_finisher`` call as before.

    ``retry_delay`` is accepted and ignored: there is no longer anything to
    retry. It is kept so the ~30 call sites need no edit.

    Args:
        hobj: An ``Action``, ``Experiment``, or ``Sequence``.
        base: Server object providing ``helaodirs`` and ``world_cfg``.
        retry_delay: Unused. Retained for signature compatibility.

    Returns:
        Empty dict when ``hobj`` is not a supported type; otherwise None.
    """
    from helao.helpers import helao_logging as logging

    LOGGER = (
        logging.LOGGER if logging.LOGGER is not None else logging.make_logger(__file__)
    )

    obj_type = hobj.__class__.__name__.lower()
    if obj_type not in ("action", "experiment", "sequence"):
        LOGGER.info(
            f"Invalid object {obj_type} was provided. Can only move Action, "
            "Experiment, or Sequence."
        )
        return {}

    save_dir = str(base.helaodirs.save_root)
    if getattr(hobj, "manual_action", False):
        save_dir = redirect_manual_dir(save_dir)

    target_subdir = {
        "action": hobj.get_action_dir,
        "experiment": hobj.get_experiment_dir,
        "sequence": hobj.get_sequence_dir,
    }[obj_type]()
    yml_dir = os.path.normpath(os.path.join(save_dir, target_subdir))

    timestamp = getattr(hobj, f"{obj_type}_timestamp").strftime("%y%m%d.%H%M%S%f")
    yml_path = os.path.join(yml_dir, f"{timestamp}-{obj_type[:3]}.yml")

    journal = getattr(base, "run_journal", None)
    if journal is not None:
        journal.append(
            str(getattr(hobj, f"{obj_type}_uuid")),
            obj_type,
            DONE,
            root_relative(yml_dir, base.helaodirs.root),
        )

    if not getattr(hobj, "manual_action", False):
        await yml_finisher(
            yml_path,
            sync_config=get_sync_server_cfg(base.world_cfg),
        )
    LOGGER.info(f"Finished {yml_dir}")
```

Delete the now-unused `aioshutil` and `aiofiles.os` imports if nothing else in
the module uses them, and add
`from helao.hexagon.domain.naming import redirect_manual_dir` and
`from helao.helpers.run_state import DONE, root_relative`. Use the shared
`root_relative` from Task 4 — do not write a second copy here, or the journal
will disagree with itself about what a path looks like.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
timeout 300 /home/dan/miniforge3/envs/helao/bin/python -m pytest \
    helao/core/tests/test_runs_layout.py -v
```

Expected: 13 passed.

- [ ] **Step 6: Prove the guards are falsifiable**

1. Re-add a `shutil.copytree(yml_dir, yml_dir.replace("RUNS", "RUNS_FINISHED"))`
   to `move_dir`.
   Expected: both `test_move_dir_leaves_the_tree_exactly_where_it_is` and
   `test_move_dir_creates_no_legacy_directory` FAIL. Remove it.
2. Change `redirect_manual_dir` to `return str(path)`.
   Expected: `test_manual_redirect_swaps_the_root_not_a_substring` FAILS.

- [ ] **Step 7: Commit**

```bash
black helao/hexagon/domain/naming.py helao/core/servers/base.py \
      helao/helpers/yml_tools.py helao/core/tests/test_runs_layout.py \
      helao/core/tests/run_layout_fixtures.py
git add -A
git commit -m "feat(core): records finish in place; manual runs write to DIAG

move_dir no longer copies a tree and removes the source -- it evicts from
the journal and calls yml_finisher. Manual runs resolve their save root to
DIAG at write time instead of being written under RUNS and moved out,
which also removes the path that deleted its own parent directories.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XwcM9LMRUctM69ktAp2VUD"
```

---

### Task 10: The syncer stops promoting and stops zipping

**Files:**
- Modify: `helao/core/drivers/data/sync_driver.py` — delete `move_to_synced` (104-136), `revert_to_finished` (139-160), the promotion block (1692-1720); relocate `.prg` (665); swap the upload set (the `misc_files + hlo_files + process_ymls` concatenation)
- Modify: `helao/hexagon/adapters/native/sync_driver.py` — mirror
- Test: `helao/core/tests/test_runs_layout.py`

**Interfaces:**
- Consumes: `HelaoYml.upload_files`, `warn_unregistered_files` (Task 3); `run_journal`, `DONE` (Task 6); `is_legacy_path` (Task 7).
- Produces: `Progress.prg` sits beside its own yml. `HelaoYml.synced_path` returns `self.target` unchanged for a new-layout path.

- [ ] **Step 1: Write the failing tests**

Append to `helao/core/tests/test_runs_layout.py`:

```python
def test_prg_sits_beside_its_own_yml(tmp_path: Path):
    """Spec §4.5: the receipt lives with the record, not in another tree."""
    from helao.core.drivers.data.sync_driver import Progress

    d = tmp_path / "RUNS" / "2026" / "0925" / "seq"
    d.mkdir(parents=True)
    yml = d / "260925.094102000000-seq.yml"
    yml.write_text("sequence_name: s\nsequence_status: [finished]\n")

    prog = Progress(yml)
    assert prog.prg.parent == yml.parent
    assert prog.prg.name == "260925.094102000000-seq.prg"


def test_synced_path_is_identity_for_a_new_layout_record(tmp_path: Path):
    from helao.core.drivers.data.sync_driver import HelaoYml

    d = tmp_path / "RUNS" / "2026" / "0925" / "seq"
    d.mkdir(parents=True)
    yml = d / "260925.094102000000-seq.yml"
    yml.write_text("sequence_name: s\nsequence_status: [finished]\n")

    assert HelaoYml(yml).synced_path == yml


def test_synced_path_still_rewrites_a_legacy_record(tmp_path: Path):
    from helao.core.drivers.data.sync_driver import HelaoYml

    d = tmp_path / "RUNS_FINISHED" / "26.35" / "0925" / "seq"
    d.mkdir(parents=True)
    yml = d / "260925.094102000000-seq.yml"
    yml.write_text("sequence_name: s\nsequence_status: [finished]\n")

    assert "RUNS_SYNCED" in str(HelaoYml(yml).synced_path)


def test_no_zip_is_produced_for_a_synced_sequence(tmp_path: Path):
    """Spec D9. Paired with the sequence_path alias in Task 12."""
    import helao.core.drivers.data.sync_driver as sd

    assert not hasattr(sd, "move_to_synced")
    assert not hasattr(sd, "revert_to_finished")


def test_pending_globs_find_records_in_the_new_layout(tmp_path: Path):
    """Spec §10.9: RUNS/%Y/%m%d/seqdir is the same depth as RUNS_FINISHED/YY.WW/MMDD/seqdir.

    list_pending globs '*/*/*/*-seq.yml' relative to the run root. If the new
    layout were one level shallower or deeper, every pending record would
    become invisible to the syncer's startup sweep -- silently, because an
    empty glob is indistinguishable from an empty queue.
    """
    from glob import glob

    seq_dir = tmp_path / "RUNS" / "2026" / "0925" / "094102__s__noLabel"
    exp_dir = seq_dir / "260925.094103__exp"
    act_dir = exp_dir / "0__0__SIM__do_thing"
    act_dir.mkdir(parents=True)
    (seq_dir / "260925.094102000000-seq.yml").write_text("sequence_name: s\n")
    (exp_dir / "260925.094103000000-exp.yml").write_text("experiment_name: e\n")
    (act_dir / "260925.094104000000-act.yml").write_text("action_name: a\n")

    root = str(tmp_path / "RUNS")
    assert len(glob(os.path.join(root, "*", "*", "*", "*-seq.yml"))) == 1
    assert len(glob(os.path.join(root, "*", "*", "*", "*", "*-exp.yml"))) == 1
    assert len(glob(os.path.join(root, "*", "*", "*", "*", "*", "*-act.yml"))) == 1
```

The test needs `import os` at the top of `test_runs_layout.py` if it is not
already there.

- [ ] **Step 2: Run them to see them fail**

```bash
timeout 300 /home/dan/miniforge3/envs/helao/bin/python -m pytest \
    helao/core/tests/test_runs_layout.py -v -k "prg or synced_path or zip or pending"
```

Expected: `test_prg_sits_beside_its_own_yml` FAILS (the `.prg` is under
`RUNS_SYNCED`), and `test_no_zip_is_produced_for_a_synced_sequence` FAILS
(both helpers still exist).

- [ ] **Step 3: Make `synced_path` legacy-only**

```python
    @property
    def synced_path(self) -> Path:
        """Where this record ends up once shipped.

        A record written under ``RUNS`` never moves, so this is the record
        itself. Only a legacy path -- one still carrying a ``RUNS_*``
        segment -- is rewritten, and only so that archives predating the
        cut-over keep resolving.
        """
        if not is_legacy_path(self.target):
            return self.target
        return Path(self.rename(RunDir.SYNCED.value))
```

Apply the same guard to `active_path` and `finished_path`. Add
`from helao.core.models.run_dir import is_legacy_path` to the imports.

- [ ] **Step 4: Relocate the `.prg`**

At `sync_driver.py:665`, replace

```python
            self.prg = self.yml.synced_path.with_suffix(".prg")
```

with

```python
            # The receipt belongs with the record it describes. It used to be
            # written under RUNS_SYNCED -- a different tree from the record --
            # which is why moving a station root stranded .prg files forever.
            self.prg = self.yml.target.with_suffix(".prg")
```

For a legacy record `synced_path` still rewrites, so this changes nothing for
pre-cut-over trees beyond putting the sidecar in the same place the record is.

- [ ] **Step 5: Delete the promotion block and the movers**

Delete `move_to_synced` and `revert_to_finished` entirely, and every import of
them. Replace the `if prog.s3_done and prog.api_done:` block in `sync_yml`
(lines 1702-1720) with:

```python
        if prog.s3_done and prog.api_done:
            for lock_path in prog.yml.lock_files:
                lock_path.unlink()
            prog.yml.warn_unregistered_files()
            if self.run_journal is not None:
                self.run_journal.append(
                    str(prog.yml.meta.get(f"{prog.yml.type}_uuid", yml_target_name)),
                    prog.yml.type,
                    DONE,
                    root_relative(prog.yml.targetdir, self.base.helaodirs.root),
                )
            LOGGER.debug(f"{yml_target_name} synced in place.")
```

Remove the `zip_dir` call on the sequence branch below it and the `from
helao.helpers.file_utils import zip_dir` import if nothing else uses it.

- [ ] **Step 6: Swap the upload set**

Every place `prog.yml.misc_files + prog.yml.hlo_files` (or the three-way
concatenation) is used to decide what to **upload**, replace with
`prog.yml.upload_files + prog.yml.process_ymls`. Leave `lock_files` handling
alone. Then delete `misc_files` and `hlo_files` if the audit from Task 1 came
back clean; if it did not, keep them — `warn_unregistered_files` uses
`_is_syncable_misc_file`.

- [ ] **Step 7: Run the tests and the syncer suite**

```bash
timeout 300 /home/dan/miniforge3/envs/helao/bin/python -m pytest \
    helao/core/tests/test_runs_layout.py -v
for f in helao/core/tests/test_sync_staging_files.py \
         helao/core/tests/unit_test_sync_relative_paths.py \
         helao/core/tests/unit_test_sync_process_recovery.py \
         helao/core/tests/test_orphan_record_defer.py \
         helao/core/tests/test_process_locator.py \
         helao/hexagon/tests/test_native_sync_driver.py \
         helao/hexagon/tests/test_native_sync_parity.py; do
  timeout 600 /home/dan/miniforge3/envs/helao/bin/python -m pytest "$f" -v
done
```

Failures here are expected in the tests that build literal `RUNS_FINISHED`
trees and assert a promotion happened. Fix each by asserting the record stayed
put — do **not** restore the promotion to make a test pass.

- [ ] **Step 8: Prove the guards are falsifiable**

1. Restore `self.prg = self.yml.synced_path.with_suffix(".prg")`.
   Expected: `test_prg_sits_beside_its_own_yml` FAILS.
2. Remove the `if not is_legacy_path(...)` guard from `synced_path`.
   Expected: `test_synced_path_is_identity_for_a_new_layout_record` FAILS.
3. In `helao/helpers/premodels.py`, change `get_sequence_dir()` to emit
   `%Y%m%d` as a single segment instead of `%Y/%m%d`.
   Expected: `test_pending_globs_find_records_in_the_new_layout` FAILS. This is
   the depth assumption the syncer's startup sweep depends on, and it fails
   silently in production — an empty glob looks exactly like an empty queue.

- [ ] **Step 9: Commit**

```bash
black helao/core/drivers/data/sync_driver.py \
      helao/hexagon/adapters/native/sync_driver.py \
      helao/core/tests/test_runs_layout.py
git add -A
git commit -m "feat(sync): sync in place, no promotion and no sequence zip

Deletes move_to_synced, revert_to_finished and the promotion block; a
synced record stays where it was written. The .prg receipt moves beside its
own yml instead of living under RUNS_SYNCED. Upload set now comes from
HelaoYml.upload_files.

active_path/finished_path/synced_path are identity for a new-layout record
and rewrite only for legacy archives.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XwcM9LMRUctM69ktAp2VUD"
```

---

### Task 11: Readers resolve `RUNS` first, legacy second

**Files:**
- Modify: `helao/helpers/file_mapper.py:43-118`
- Modify: `helao/helpers/helao_data.py:120-190`
- Modify: `helao/core/drivers/data/loaders/localfs.py`
- Modify: `helao/core/drivers/data/process_locator.py`
- Modify: `helao/ui/shared/data_browser/sources.py`
- Test: `helao/core/tests/test_legacy_run_readers.py` (create)

**Interfaces:**
- Consumes: `is_legacy_path`, `LEGACY_RUN_DIRS` (Task 7).
- Produces: `FileMapper.is_legacy: bool`, set once in `__init__`. No signature changes anywhere — every method keeps its current name and return type.

- [ ] **Step 1: Write the failing tests**

```python
"""Both layouts resolve; the new one without searching (spec §7)."""

import zipfile
from pathlib import Path

from helao.helpers.file_mapper import FileMapper


def _legacy_tree(tmp_path: Path) -> Path:
    d = tmp_path / "RUNS_SYNCED" / "26.35" / "0828" / "seqdir" / "expdir"
    d = d / "0__0__SIM__do_thing"
    d.mkdir(parents=True)
    (d / "data-0.0.0.0__0.hlo").write_text("x")
    (d / "260828.120000000000-act.yml").write_text("action_name: do_thing\n")
    return d


def _new_tree(tmp_path: Path) -> Path:
    d = tmp_path / "RUNS" / "2026" / "0925" / "seqdir" / "expdir"
    d = d / "0__0__SIM__do_thing"
    d.mkdir(parents=True)
    (d / "data-0.0.0.0__0.hlo").write_text("x")
    (d / "260925.094102000000-act.yml").write_text("action_name: do_thing\n")
    return d


def test_new_layout_is_not_flagged_legacy(tmp_path: Path):
    assert FileMapper(str(_new_tree(tmp_path))).is_legacy is False


def test_legacy_layout_is_flagged_legacy(tmp_path: Path):
    assert FileMapper(str(_legacy_tree(tmp_path))).is_legacy is True


def test_new_layout_resolves_without_trying_other_roots(tmp_path: Path):
    d = _new_tree(tmp_path)
    fm = FileMapper(str(d))
    assert Path(fm.locate("data-0.0.0.0__0.hlo")).is_file()


def test_legacy_layout_still_resolves(tmp_path: Path):
    d = _legacy_tree(tmp_path)
    fm = FileMapper(str(d))
    assert Path(fm.locate("data-0.0.0.0__0.hlo")).is_file()


def test_legacy_sequence_zip_still_resolves(tmp_path: Path):
    """Pre-cut-over archives keep their zips; nothing rewrites them."""
    d = _legacy_tree(tmp_path)
    seq_dir = d.parent.parent
    rel = "expdir/0__0__SIM__do_thing/data-0.0.0.0__0.hlo"
    with zipfile.ZipFile(seq_dir.with_suffix(".zip"), "w") as zf:
        zf.writestr(rel, "x")
    for p in sorted(seq_dir.rglob("*"), reverse=True):
        p.unlink() if p.is_file() else p.rmdir()
    seq_dir.rmdir()

    fm = FileMapper(str(d))
    assert fm.locate("data-0.0.0.0__0.hlo") is not None
```

- [ ] **Step 2: Run them to see them fail**

```bash
timeout 300 /home/dan/miniforge3/envs/helao/bin/python -m pytest \
    helao/core/tests/test_legacy_run_readers.py -v
```

Expected: `AttributeError: 'FileMapper' object has no attribute 'is_legacy'`.

- [ ] **Step 3: Add the legacy flag to `FileMapper`**

In `__init__`, after `self.prestr` and `self.runpos` are computed:

```python
        self.is_legacy = is_legacy_path(save_path)
```

and in the resolve loop, short-circuit the search:

```python
        if not self.is_legacy:
            # A record written under RUNS never moves, so there is exactly one
            # candidate. The multi-root search below exists only for archives
            # that predate the cut-over.
            candidate = Path(os.path.join(self.prestr, "RUNS", p))
            return str(candidate) if candidate.exists() else None
```

`locate()` is the resolve entry point (`file_mapper.py:79`); the zip fallback is
`_locate_in_zip` (`file_mapper.py:118`) and stays reachable only when
`self.is_legacy` is true. `self.prestr` and `self.runpos` keep their current
meaning — `runpos` is the index of the run-root segment in `inputparts`, which
for a new-layout path is simply the index of `RUNS`.

Update the class docstring: it currently states that HELAO writes output beneath
`<root>/RUNS_<state>/...`, which is no longer true for new records.

- [ ] **Step 4: Apply the same guard to the other four readers**

`helao/helpers/helao_data.py:145-146` — run the `RUNS_[A-Z]+` regex and the
`RUNS_*` glob only `if is_legacy_path(self.ymldir)`; otherwise use `self.ymldir`
directly. `localfs.py`, `process_locator.py` and
`ui/shared/data_browser/sources.py` each resolve against `RUNS` first and fall
back to their existing legacy search.

Leave the `RunDir.NOSYNC` filters in `helao_data.py:233-249` alone — they are
correct for legacy trees, and for new records no path ever carries that segment,
so they are simply inert.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
timeout 300 /home/dan/miniforge3/envs/helao/bin/python -m pytest \
    helao/core/tests/test_legacy_run_readers.py -v
timeout 600 /home/dan/miniforge3/envs/helao/bin/python -m pytest \
    helao/core/tests/test_reflex_data_browser.py -v
timeout 600 /home/dan/miniforge3/envs/helao/bin/python -m pytest \
    helao/deploy/test/tests/test_data_browser.py -v
```

Expected: all pass.

- [ ] **Step 6: Prove the guards are falsifiable**

1. Change `self.is_legacy = is_legacy_path(save_path)` to `= True`.
   Expected: `test_new_layout_is_not_flagged_legacy` FAILS.
2. Change it to `= False`.
   Expected: `test_legacy_layout_still_resolves` and
   `test_legacy_sequence_zip_still_resolves` FAIL.

Mutation 2 is the important one: it is the exact shape of the bug where a
cut-over silently makes years of archive unreadable.

- [ ] **Step 7: Commit**

```bash
black helao/helpers/file_mapper.py helao/helpers/helao_data.py \
      helao/core/drivers/data/loaders/localfs.py \
      helao/core/drivers/data/process_locator.py \
      helao/ui/shared/data_browser/sources.py \
      helao/core/tests/test_legacy_run_readers.py
git add -A
git commit -m "feat(readers): resolve RUNS directly, search only for legacy trees

A record under RUNS has exactly one candidate path, so the multi-root
search collapses. The search is kept, unchanged, for archives that predate
the cut-over -- those are never migrated.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XwcM9LMRUctM69ktAp2VUD"
```

---

### Task 12: `sequence_zip_path` becomes `sequence_path`

**Files:**
- Modify: `helao/core/drivers/data/sync_driver.py` (the `auto_analyze_sequences` dispatch at ~1761)
- Modify: the six `*_postseq` sequence modules under the private deployments and `helao/deploy/hte/sequences/`
- Modify: the analysis endpoints that declare the parameter
- Test: `helao/core/tests/test_sequence_path_alias.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `sequence_path` as the parameter name everywhere; `sequence_zip_path` accepted as a deprecated alias that logs once per process.

- [ ] **Step 1: Find every declaration and call site**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
grep -rn "sequence_zip_path" --include='*.py' --include='*.yml' . | tee \
    $CLAUDE_JOB_DIR/tmp/seqzip_sites.txt
wc -l $CLAUDE_JOB_DIR/tmp/seqzip_sites.txt
```

Every hit is either a parameter declaration, a dispatch that fills it, or a
config. Classify each before editing; the private deployments have their own git
repos and are committed separately.

- [ ] **Step 2: Write the failing test**

```python
"""The old parameter name keeps working (spec §5.1, D9)."""

from helao.helpers.param_alias import resolve_sequence_path


def test_new_name_passes_through():
    assert resolve_sequence_path({"sequence_path": "/d/RUNS/2026/0925/seq"}) == (
        "/d/RUNS/2026/0925/seq"
    )


def test_old_name_is_accepted(caplog):
    with caplog.at_level("WARNING"):
        got = resolve_sequence_path({"sequence_zip_path": "/d/RUNS_SYNCED/s.zip"})
    assert got == "/d/RUNS_SYNCED/s.zip"
    assert "sequence_zip_path" in caplog.text


def test_new_name_wins_when_both_are_present():
    params = {
        "sequence_path": "/new",
        "sequence_zip_path": "/old",
    }
    assert resolve_sequence_path(params) == "/new"


def test_neither_present_is_none():
    assert resolve_sequence_path({}) is None
```

- [ ] **Step 3: Add the resolver**

Create `helao/helpers/param_alias.py`:

```python
"""Deprecated parameter-name aliases kept alive for live station configs."""

__all__ = ["resolve_sequence_path"]

from typing import Optional

from helao.helpers import helao_logging as logging

LOGGER = logging.LOGGER if logging.LOGGER is not None else logging.make_logger(__file__)

_WARNED = set()


def resolve_sequence_path(params: dict) -> Optional[str]:
    """The finished sequence's location, under either parameter name.

    A synced sequence is no longer zipped (spec D9), so ``sequence_zip_path``
    names something that is usually a directory. The honest name is
    ``sequence_path``; the old one stays accepted so live configs
    (``auto_analyze_sequences``) and the ``*_postseq`` sequences keep working
    with no edit. ``HelaoData`` already accepts a directory, a zip, or a yml,
    so callers need no other change.

    Warned once per process rather than per call: these fire on every synced
    sequence and would otherwise bury the log.
    """
    if params.get("sequence_path"):
        return params["sequence_path"]
    legacy = params.get("sequence_zip_path")
    if legacy:
        if "sequence_zip_path" not in _WARNED:
            _WARNED.add("sequence_zip_path")
            LOGGER.warning(
                "sequence_zip_path is deprecated; use sequence_path. A synced "
                "sequence is a directory, not a zip."
            )
        return legacy
    return None
```

- [ ] **Step 4: Rename the declarations and fill the new name**

In each analysis endpoint from Step 1, rename the declared parameter to
`sequence_path` and accept the old one through `resolve_sequence_path`. In
`sync_driver.py`'s `auto_analyze_sequences` dispatch, send `sequence_path`
carrying the sequence **directory** rather than a zip path.

- [ ] **Step 5: Run the tests**

```bash
timeout 300 /home/dan/miniforge3/envs/helao/bin/python -m pytest \
    helao/core/tests/test_sequence_path_alias.py -v
```

Expected: 4 passed.

- [ ] **Step 6: Prove the guard is falsifiable**

Delete the `legacy = params.get("sequence_zip_path")` branch.
Expected: `test_old_name_is_accepted` FAILS. This is the test standing between
the cut-over and three live station configs silently stopping their analyses.

- [ ] **Step 7: Commit, parent repo and each deployment separately**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
black helao/helpers/param_alias.py helao/core/drivers/data/sync_driver.py \
      helao/core/tests/test_sequence_path_alias.py
git add -A && git commit -m "feat(sync): sequence_path replaces sequence_zip_path

A synced sequence is a directory now, not a zip. The old parameter name is
accepted as a deprecated alias so live auto_analyze_sequences configs and
the *_postseq sequences keep working unedited.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XwcM9LMRUctM69ktAp2VUD"
```

Then, for each private deployment that Step 1 listed, `cd` into its directory
and commit within its own git repo. Do not name those deployments in any
tracked parent-repo file.

---

### Task 13: Sweep the mechanical call sites and re-baseline

**Files:**
- Modify: the ~85 test and fixture modules from spec §8 that construct literal `RUNS_*` trees
- Modify: `helao/core/tests/{check_long_paths,scan_prg_ghosts,set_run_use,check_queue_pcks}.py`
- Modify: `harness/{capture,mutate,parity,treepass}.py` and `harness/tests/synthtree.py`

**Interfaces:**
- Consumes: everything above.
- Produces: a green full sweep.

- [ ] **Step 1: Enumerate what is left**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
grep -rln "RUNS_" --include='*.py' . | sort > $CLAUDE_JOB_DIR/tmp/runs_sites.txt
wc -l $CLAUDE_JOB_DIR/tmp/runs_sites.txt
```

Classify every file into exactly one of three buckets and record the
classification in `$CLAUDE_JOB_DIR/tmp/runs_triage.txt`:

- **legacy-by-design** — the file is *about* reading pre-cut-over archives
  (`test_legacy_run_readers.py`, `scan_prg_ghosts.py`, the `harness/` readers).
  Leave the literals alone.
- **needs-update** — a fixture that builds a tree the servers no longer write.
  Change the literal to the new layout.
- **both** — must exercise legacy and new. Parametrize rather than pick one.

- [ ] **Step 2: Update the `needs-update` bucket**

Mechanical: `RUNS_FINISHED/26.35/0828/` becomes `RUNS/2026/0828/`, and any
assertion that a promotion happened becomes an assertion that the path did not
change. Work in batches of about ten files, running each file's tests as you go:

```bash
timeout 600 /home/dan/miniforge3/envs/helao/bin/python -m pytest <one_file> -v
```

- [ ] **Step 3: Re-baseline the golden masters deliberately**

```bash
timeout 900 /home/dan/miniforge3/envs/helao/bin/python \
    helao/core/tests/test_active_golden_master.py --check
timeout 900 /home/dan/miniforge3/envs/helao/bin/python \
    helao/core/tests/test_orch_dispatch_golden_master.py --check
```

**Neither is a pytest module.** Both carry a `test_` prefix but are standalone
`argparse` harnesses; `--check` is the gate. Run under `pytest` they collect
zero tests and exit green, so the whole layout change would appear to clear its
hardest gate without the gate ever running. Expect
`CHECK PASSED: all 13 scenarios match .../baseline_S0a` from the first and an
equivalent line from the second.

**Read every diff before accepting it.** Expected differences: the run root, the
`%Y/%m%d` date segment, `sequence_label` carrying a plate suffix, and
`file_name` values that gained a subdirectory. Anything else — a changed uuid, a
dropped file, a changed action ordering — is a regression, not a re-baseline.
Record in the commit message which fields changed and why.

- [ ] **Step 4: Run the full sweep**

```bash
timeout 5400 /home/dan/miniforge3/envs/helao/bin/python run_tests.py \
    2>&1 | tee $CLAUDE_JOB_DIR/tmp/full_sweep.txt
tail -40 $CLAUDE_JOB_DIR/tmp/full_sweep.txt
```

`ENV` results for Windows-only vendor SDKs are expected and are not failures.
Zero `FAIL` is the bar.

- [ ] **Step 5: Launch a real group end to end**

```bash
/home/dan/miniforge3/envs/helao/bin/python launch.py simulate
```

Run one sequence to completion, then verify all five properties at once:

```bash
R=<root>
ls $R                                  # RUNS, DIAG, STATES, LOGS, ... and no RUNS_*
find $R/RUNS -name '*-seq.yml'         # exactly one, under RUNS/%Y/%m%d/
find $R/RUNS -name '*.prg'             # beside its yml, not elsewhere
find $R -name '*.zip' -newer $R/STATES # no new sequence zip
cat $R/STATES/runstate_*.jsonl         # empty at rest
```

Then re-run with a manual action and confirm its tree is under `$R/DIAG` and
that `$R/RUNS` did not gain a directory that was later removed.

- [ ] **Step 6: Commit and open the PR**

```bash
black $(git diff --name-only unstable... | grep '\.py$')
git add -A
git commit -m "test: sweep RUNS_* literals to the new layout

Fixtures that build trees the servers no longer write are updated; files
that exist to read pre-cut-over archives keep their literals deliberately.
Golden masters re-baselined for the run root, the %Y/%m%d date segment, the
plate suffix in sequence_label, and record-relative file_name.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XwcM9LMRUctM69ktAp2VUD"
git push -u origin feat/runs-layout-unification
```

Open the PR against `unstable` only after Step 5 has passed on a real launch.
Do not merge without a station check: note1 is the station with eight live
`RUNS_*` states and the archive every legacy reader test is modelled on.

---

## Station cut-over checklist

Not a code task — the operational steps that must happen at each station after
the merge, in this order.

- [ ] Stop the running group cleanly (`CTRL-x`, not a kill).
- [ ] Confirm `RUNS_ACTIVE` and `RUNS_FINISHED` are **empty**. A record left in
      either is a pre-cut-over record that the new syncer will never see: it has
      no journal entry and does not live under `RUNS`. Let the old build drain
      them first.
- [ ] Pull and launch. `RUNS`, `DIAG` and the journals are created on startup.
- [ ] Run one short real sequence and walk Task 13 Step 5's five checks.
- [ ] Leave the legacy `RUNS_*` trees mounted and untouched. Every reader still
      resolves them and nothing migrates them.
