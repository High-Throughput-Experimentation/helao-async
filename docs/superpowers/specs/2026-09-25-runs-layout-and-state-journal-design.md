# RUNS layout unification and per-server state journals

Date: 2026-09-25
Status: design approved, plan not yet written
Supersedes on-disk behaviour of: `helao/core/models/run_dir.py`, `helao/helpers/yml_tools.py:move_dir`, the promotion half of `helao/core/drivers/data/sync_driver.py`

## 1. Problem

HELAO encodes a run's lifecycle state in the *name of the directory it lives in*.
A record is born in `RUNS_ACTIVE`, is physically copied to `RUNS_FINISHED` when it
finishes, and is physically moved again to `RUNS_SYNCED` when the syncer ships it.
Manual runs divert to `RUNS_DIAG`; `.hlo` files belonging to a record with
`sync_data: False` divert to `RUNS_NOSYNC`. Repair tooling adds three more names
(`RUNS_CORRUPT`, `RUNS_REBUILD`, `RUNS_SUPERSEDED` — `scan_prg_ghosts.py:99-101`),
for eight state directories in production at note1.

Four costs follow directly:

1. **Every reader must search.** `FileMapper` (`file_mapper.py:58-110`) walks the
   `RUNS_{state}` candidates in turn for a single file lookup. `HelaoData`
   rewrites the state segment to `RUNS_*` and globs (`helao_data.py:145-146`).
   A loader cannot name a file; it can only guess at up to eight places.
2. **State changes are bulk filesystem operations.** `move_dir`
   (`yml_tools.py:240-400`) is ~160 lines of copy-with-60-retries then
   remove-with-30-retries. A state transition that is conceptually one bit costs
   a full tree copy and can partially fail.
3. **Recorded paths rot.** Because the tree moves, anything that recorded an
   absolute path into it is invalidated by the very act of syncing — the root
   cause behind `sync-sidecar-absolute-paths`. The `.prg` sidecar lives under
   `RUNS_SYNCED` (`sync_driver.py:665`), a *different tree* from the record it
   describes.
4. **The week-numbered top level is unreadable.** `YY.WW` (`%y.%U`) means a human
   browsing the archive must convert an ISO-ish week number to a date.

## 2. Decisions taken

These were settled before this document and are not re-argued here.

| # | Decision |
|---|---|
| D1 | Legacy trees stay exactly where they are. Readers learn both layouts; nothing on disk is migrated. |
| D2 | State journals are append-only JSONL, one file per writing server, under `root/STATES`. |
| D3 | Only the live working set is persisted. A record that reaches a terminal state is **evicted**, not marked done. Absence == done. |
| D4 | Manual/diagnostic runs keep a separate top-level tree (`root/DIAG`). The per-file nosync rule becomes a flag, not a parallel tree. |
| D5 | Whether finished runs sync is a single config-root boolean. |
| D6 | The plate/sample suffix moves into `sequence_label` itself, so it reaches metadata and not just the directory name. |
| D7 | Ownership handoff: the producing server owns ACTIVE, the SYNC server owns UNSYNCED. Exactly one writer per journal file. |
| D8 | The `.prg` sidecar is promoted to the authoritative per-run receipt and moves beside its yml. The journal is a rebuildable index. |
| D9 | Synced sequences are no longer zipped. `sequence_zip_path` is renamed `sequence_path`; the old name survives as a deprecated alias. |

**The invariant that makes all of this work: a run tree is written once, in one
place, and never moves.**

## 3. On-disk layout

### 3.1 Roots

```
<root>/
  RUNS/      <- every real run, any lifecycle state
  DIAG/      <- manual/diagnostic runs, same internal layout
  STATES/    <- per-server journals (plus the existing pid/queue pickles)
  LOGS/ DATABASE/ USER_CONFIG/ ANALYSES/ PROCESSES/   (unchanged)
```

`RUNS_ACTIVE`, `RUNS_FINISHED`, `RUNS_SYNCED`, `RUNS_NOSYNC`, `RUNS_DIAG` are no
longer created. They remain on disk at existing stations, read-only, forever.

`helao_dirs()` creates `RUNS` and `DIAG` instead of `RUNS_ACTIVE`.
`HelaoDirs.save_root` now points at `<root>/RUNS`. The field keeps its name —
every consumer already means "where run trees go", and renaming it is churn
across ~40 call sites for no behaviour change.

### 3.2 Sequence directory

```
RUNS/%Y/%m%d/%H%M%S__{sequence_name}__{sequence_label}
```

Built with `os.path.join`, then normalized to **forward slashes**, exactly as
today. Every written and consumed run-relative path uses `/` on every platform;
the OS-native form exists only transiently, at the filesystem call itself. See
§9.

Experiment and action directories are unchanged:

```
RUNS/%Y/%m%d/%H%M%S__{seq_name}__{seq_label}/
    %y%m%d.%H%M%S__{experiment_name}/
        {orch_submit_order}__{action_split}__{server_name}__{action_name}/
```

Depth is preserved. `%Y/%m%d/seqdir` is the same three levels as `YY.WW/MMDD/seqdir`,
so the existing pending globs (`sync_driver.py:2263-2299`,
`RUNS_FINISHED/*/*/*/*-seq.yml`) keep working after a root swap rather than
needing re-derivation.

### 3.3 Sequence label rule (D6)

Today `get_sequence_dir()` computes a plate suffix and appends it **to the
directory name only** (`premodels.py:127-143`); `sequence_label` in the metadata
never sees it. That is why a plate cannot be found from a sequence record without
the API.

New rule, applied once when the sequence is constructed, **mutating
`sequence_label`**:

1. If `sequence_label` is `None`, set it to `"noLabel"`. (unchanged)
2. If `sequence_params["plate_id"]` is truthy:
   - `serial = f"{plate_id}{sum(int(d) for d in str(plate_id)) % 10}"` (unchanged
     check-digit arithmetic)
   - If `serial` is not already a substring of `sequence_label`, append
     `f"-{serial}"`.
   - Then, if exactly one sample number is available, append `f"-{sample_no}"`.
     Sources are consulted in order and the first that yields exactly one value
     wins: `sample_no`, `solid_sample_no`, `plate_sample_no`, and the existing
     list form `plate_sample_no_list`. A scalar counts as one value; a list
     counts only when `len == 1`.
3. If there is no plate, no sample suffix is appended **even when a sample number
   is present**. The sample suffix is meaningful only as a position on a plate.

`get_sequence_dir()` then interpolates `sequence_label` verbatim and computes no
suffix of its own.

Consequence worth stating plainly: the same sequence submitted with the same
label now produces a *different* `sequence_label` in its metadata than it did
before. This is the intent (the plate becomes findable from the record), but it
means label-equality comparisons against historical records will not match.

### 3.4 Manual/diagnostic runs (D4)

`redirect_manual_dir()` (`hexagon/domain/naming.py:77-85`) survives but stops
doing a string substitution on a path that already exists. Manual runs resolve
their save root to `<root>/DIAG` **at write time**, so a manual tree is never
written under `RUNS` and never has to be moved out of it.

This deletes the strangest part of `move_dir`: today a manual action writes into
`RUNS_ACTIVE`, is copied to `RUNS_DIAG`, and then *deletes its own parent
experiment and sequence directories* out of `RUNS_ACTIVE`
(`yml_tools.py:389-396`). None of that is needed when the write lands in the
right place.

`base.py:1019`'s existing `save_root.replace(ACTIVE, DIAG)` becomes a call to
`redirect_manual_dir(save_root)` returning `<root>/DIAG`.

### 3.5 nosync files, and the end of glob-driven upload (D4)

`.hlo` files for a record with `sync_data: False` stay where they are written.
They are not diverted to a parallel tree. `is_nosync_file()`
(`naming.py:87-89`) keeps its job of *setting* `FileInfo.nosync` at write time.

Folding `RUNS_NOSYNC` away removes the mechanism that currently enforces the
flag. The syncer decides what to upload by **globbing the record directory**
(`HelaoYml.misc_files` / `hlo_files`, `sync_driver.py:497-527`) — a glob cannot
see a per-file flag, so without a replacement the first run after cut-over would
silently ship data the station deliberately withholds.

**Resolution: the record's `files` list becomes the authority for what uploads.**
The glob stops deciding. This is the same defect recorded in
`sync-uploads-glob-not-action-files` (transient `.<hex>.tmp` staging files
reaching `raw_data/`, and one unuploadable name wedging the push loop) — fixing
it at the source rather than adding a second filter on top.

New rule for an action:

- Upload set = the `files` entries in the action's yml whose `nosync` is false.
- `_is_syncable_misc_file()` (`sync_driver.py:472-495`) is no longer the filter;
  its dotfile/`.tmp` exclusions become unnecessary, because a staging file was
  never registered in `files` in the first place. Keep the function until the
  audit below is clean, then delete it.
- `*-prc.yml` and `*.lock` keep their existing dedicated handling
  (`process_ymls`, `lock_files`); they are artifacts of the sync machinery
  itself, not action output, and are not in `files`.

Experiments and sequences have no `files` list; their upload set is the yml
itself plus the colocated `*-prc.yml`, which is what the non-action branch of
`misc_files` already approximates.

#### 3.5.1 The gap this opens, and how it is closed

`FileInfo.file_name` is written with `os.path.basename()`
(`active_data_file.py:423`, `hexagon/adapters/native/data_file.py:422`) — a bare
name. But `misc_files` **rglobs** for actions (`sync_driver.py:505-508`), so a
file a driver writes into a *subdirectory* of the action directory is uploaded
today and cannot be named by `files` at all.

Switching to `files` without addressing this would stop uploading those files,
silently. Two changes close it:

1. **`file_name` becomes record-relative, not a basename.** Forward-slash (§9),
   relative to the action directory, so a subdirectory file is addressable.
   A bare name is the degenerate case and existing ymls keep parsing.
2. **Runtime reconciliation warning.** After building the upload set, the syncer
   compares it against what a glob of the record directory would have found.
   Anything present on disk, not excluded as staging/bookkeeping, and absent
   from `files` is logged at WARNING with its path. The gap becomes visible at
   the station instead of becoming a silent data loss. This log is the migration
   aid; it is not a fallback and does not upload the file.

**The plan must run an audit before implementing this**, against real station
trees: for a representative sample of synced actions under note1's archive,
compute the glob-derived set and the `files`-derived set and diff them. That diff
is the list of writers that produce files without registering them. Each is then
either fixed to register, or consciously accepted as no-longer-uploaded. The
number is not guessable from the repo — vendor drivers copy instrument output in
by hand — so it must be measured, not assumed.

#### 3.5.2 Tests

Both directions must be pinned, and both must fail when their guard is removed:

- An action with `sync_data: False` produces `.hlo` files present on disk and
  **absent** from the upload set.
- An action with a registered file in a subdirectory has that file **in** the
  upload set.
- A `.<hex>.tmp` staging file present in the directory at scan time is absent
  from the upload set — the original defect, now prevented structurally.

## 4. State journals

### 4.1 Files and ownership (D7)

```
STATES/runstate_<SERVER_KEY>.jsonl
```

| Writer | Tracks | Evicts when |
|---|---|---|
| each action server, orchestrator | its own records in state `active` | the record finishes (handed off) |
| SYNC server (`runstate_SYNC.jsonl`) | records in state `unsynced` | the sync completes |

Exactly one process writes each file. No locking, no `FileLock`, no lock-file
ghosts. A reader (the operator UI, a repair tool) may read any file at any time;
a torn final line is discarded on parse (§4.4).

Handoff is an HTTP call, not a shared file. On finish the producing server
appends its eviction record and calls the SYNC server, which appends its own
`unsynced` record. If there is no SYNC server, or `sync_finished` is false
(§6), the record is simply evicted and is done — there is nothing to hand to.

### 4.2 Record schema

One JSON object per line, newline-terminated, no pretty-printing:

```json
{"ts": "2026-09-25T09:41:02.118431", "uuid": "...", "kind": "sequence",
 "state": "active", "path": "RUNS/2026/0925/094102__XRFS_noStandards__noLabel-101319",
 "parent": null}
```

| Field | Meaning |
|---|---|
| `ts` | ISO-8601 local timestamp of the transition |
| `uuid` | the record's `action_uuid` / `experiment_uuid` / `sequence_uuid` |
| `kind` | `action` \| `experiment` \| `sequence` |
| `state` | `active` \| `unsynced` \| `done` |
| `path` | **relative to `root`**, forward-slash separators (§9) |
| `parent` | parent record uuid, or `null` for a sequence |

`path` is relative to `root` deliberately. Absolute paths recorded into sidecars
are what made moving a station root strand records forever
(`sync-sidecar-absolute-paths`); the journal must not reintroduce that.

A `state: "done"` line is a **tombstone**, not a retained state. It exists only so
that a replay of the journal knows to drop the uuid, and it disappears at the
next compaction. Nothing ever queries for done records (D3).

### 4.3 Lifecycle

```
                    producing server's journal        SYNC's journal
sequence starts     append active
action starts       append active
action finishes     append done  ──HTTP──────────▶    append unsynced
                                                      (sync runs)
sync succeeds                                         append done
```

Current state of a uuid = the `state` of its **last** line. Current working set =
replay the file, drop every uuid whose last line is `done`.

### 4.4 Compaction and torn writes

Compaction runs on server startup, and during a run whenever

    lines > 1000 and lines > 10 * len(working_set)

The floor stops a station with a two-record working set from compacting
constantly; the ratio ties the trigger to how much dead weight the file is
actually carrying rather than to an absolute size. A journal grows by roughly
three lines per action, so a long campaign reaches the trigger within a day and
a quiet station never does. Both numbers are starting points to be checked
against a real campaign's line counts, not thresholds to defend.

Compaction itself:

1. Replay into an ordered dict keyed by uuid.
2. Drop uuids whose final state is `done`.
3. Write the survivors to `runstate_<KEY>.jsonl.tmp`, `fsync`, then
   `os.replace()` onto the live name.

A crash during an append can only truncate or corrupt the **last** line; every
prior record is intact, which is the whole reason for choosing an append-only
journal over a rewritten document. The replay parser discards a final line that
does not parse and logs it at WARNING. A malformed line anywhere other than the
last position is a real corruption and raises, falling through to §4.5.

### 4.5 Recovery: `.prg` is authoritative (D8)

The journal is an **index**, not the source of truth. Delete it and nothing is
lost.

The `.prg` sidecar moves from `yml.synced_path.with_suffix(".prg")` — under
`RUNS_SYNCED`, a tree the record is not in — to sitting **beside its own yml**
inside `RUNS`. It already records per-file sync progress; it now also serves as
the on-disk receipt that a record completed.

Rebuild procedure, run when a journal is missing or fails to replay:

1. Walk `RUNS` for `*-seq.yml`, `*-exp.yml`, `*-act.yml`.
2. For each, a sibling `.prg` that exists and reports complete ⇒ the record is
   done, emit nothing.
3. Otherwise ⇒ emit an `unsynced` record.
4. Write the rebuilt journal.

This is a full scan of `RUNS`, which is why `RUNS` is allowed to stay small: it
accumulates only from cut-over forward (D1 leaves years of history in the legacy
trees). The scan is not on any hot path — only cold start after a lost journal.

Leftover `active` records at startup mean the server died mid-run. They are
handed to the **existing** orphan-record path unchanged (the deferral behaviour
pinned by `test_orphan_record_defer.py`); this design does not redefine what an
orphan is.

## 5. What the syncer stops doing

Deleted outright:

- `move_to_synced()` / `revert_to_finished()` (`sync_driver.py:104-160`) — nothing
  moves, so there is nothing to revert.
- The promotion half of `sync_yml` (`sync_driver.py:1692-1715`).
- `zip_dir` on a synced sequence (D9). `try_remove_empty`
  (`sync_driver.py:1076-1145`) is no longer invoked on the sync path — nothing
  empties a source directory any more — but the function itself stays for its
  other callers.
- `move_dir`'s entire copy/retry/remove body (`yml_tools.py:240-400`). What
  remains is: append the state transition, then call `yml_finisher` exactly as
  today.

`HelaoYml.synced_path` and the `status`-segment rewriting
(`sync_driver.py:357-460`) collapse to identity for new-layout paths and are
retained only for legacy ones.

Unchanged: the priority queue, the hierarchical locks, upload retry, process
folding, `finish_pending`, `has_pending_work`. This design moves *where state
lives*, not how syncing works.

### 5.1 `sequence_path` (D9)

`sequence_zip_path` becomes `sequence_path`, accepting a directory **or** a zip.
The old parameter name is accepted as a deprecated alias so that live configs
(`auto_analyze_sequences` in `note1.yml:38-48`, `uvis4.yml`, `archive/icpm1.yml`)
and the six `*_postseq` sequences keep working with no edit.

`HelaoData` already accepts a run directory, a zip, or any of the three yml
levels, so the ANA endpoints need no logic change — only the parameter rename and
the alias.

Existing zips stay readable: `FileMapper._zip_lookup` (`file_mapper.py:119-160`)
is legacy-only from here, reached only for paths that carry a `RUNS_SYNCED`
segment.

## 6. Config surface

One new key at config root:

```yaml
sync_finished: true    # default true
```

`false` ⇒ a finishing record is evicted straight to done and never enters the
unsynced set. Distinct from the per-record `sync_data` field, which continues to
mean only "do not upload this record's `.hlo` payloads" (§3.5) and has never
meant "skip sync" (see `postfinish-extension-points`).

A group with **no SYNC server** behaves as `sync_finished: false` regardless of
the key. `resolve_sync_server_key` already returns `None` there and `yml_finisher`
already no-ops.

## 7. Legacy compatibility (D1)

`RunDir` stops being the enum of *where we write* and becomes the vocabulary of
*where we used to write*:

```python
LEGACY_RUN_DIRS = ("RUNS_ACTIVE", "RUNS_FINISHED", "RUNS_SYNCED", "RUNS_DIAG",
                   "RUNS_NOSYNC", "RUNS_CORRUPT", "RUNS_REBUILD", "RUNS_SUPERSEDED")
```

All eight, including the three that only `scan_prg_ghosts.py` knows about — a
reader that meets a `RUNS_CORRUPT` path today must keep meeting it.

A path is **legacy** iff any segment is in `LEGACY_RUN_DIRS`. This is a cheap,
exact test; no heuristics on the `YY.WW` week-directory shape are needed, and the
two layouts are trivially distinguishable because the run-root segment differs.

- `FileMapper.__init__` detects legacy once, at construction, and sets a flag.
  New-layout instances skip the state loop entirely — one candidate path, no
  search. Legacy instances behave exactly as today.
- `HelaoData` likewise: the `RUNS_[A-Z]+` regex and `RUNS_*` glob
  (`helao_data.py:145-146`) run only for legacy targets.
- `helao/core/drivers/data/loaders/localfs.py`, `process_locator.py`, and
  `ui/shared/data_browser/sources.py` get the same treatment: resolve against
  `RUNS` first, fall back to the legacy search.

No migration script. No dual-write. New runs are never written to a legacy path
and legacy runs are never rewritten.

## 8. Blast radius

Grep for `RUNS_` across `*.py`: **99 files**. They are not equal.

**Behaviour changes (~14 files):**

| File | Change |
|---|---|
| `helao/core/models/run_dir.py` | enum ⇒ `LEGACY_RUN_DIRS` + `run_root()` / `diag_root()` |
| `helao/helpers/helao_dirs.py` | create `RUNS`/`DIAG`, `save_root` ⇒ `<root>/RUNS` |
| `helao/helpers/premodels.py` | `get_sequence_dir()` + the §3.3 label rule |
| `helao/helpers/yml_tools.py` | `move_dir` body deleted; nosync divert removed |
| `helao/helpers/file_mapper.py` | legacy flag; single-candidate fast path |
| `helao/helpers/helao_data.py` | legacy flag |
| `helao/core/drivers/data/sync_driver.py` | promotion + zip deleted; `.prg` relocated; upload set driven by `files`, not globs (§3.5) |
| `helao/core/drivers/data/process_locator.py`, `loaders/localfs.py` | legacy fallback |
| `helao/core/servers/base.py`, `base_api.py`, `orch.py` | journal appends; manual redirect via `diag_root()` |
| `helao/hexagon/domain/naming.py` | `redirect_manual_dir` ⇒ `DIAG` |
| `helao/hexagon/adapters/native/sync_driver.py`, `meta_writer.py`, `posthoc_writer.py` | mirror the above |
| `helao/ui/shared/data_browser/sources.py` | legacy fallback |
| `helao/core/models/file.py` | `FileInfo.file_name` becomes record-relative (§3.5.1) |
| `helao/core/servers/active_data_file.py`, `hexagon/adapters/native/data_file.py` | stop calling `os.path.basename` on `file_name` |
| **new** `helao/helpers/run_state.py` | the journal: append, replay, compact, rebuild |

**Mechanical (~85 files):** tests and fixtures that construct literal
`RUNS_FINISHED/26.35/0828/...` trees, plus the four standalone repair utilities
under `helao/core/tests/`. Each needs its literal updated or, where the test is
*about* legacy handling, deliberately left alone. `harness/` (capture, mutate,
parity, treepass) reads real station trees and must keep understanding both.

## 9. Path separators

**Decided: `/` everywhere.** The existing normalization at the end of
`get_sequence_dir()` / `get_experiment_dir()` / `get_action_dir()` stays. Every
run-relative path that is written to a yml, recorded in a journal, compared,
split, or handed to another server is forward-slash. The OS-native form is
produced only at the point of a filesystem call and never stored.

This keeps `windows-rundir-separator-normalization` fixed rather than
re-litigated: run-dir methods returning native separators is precisely the
regression that memory records.

Two consequences for this design:

- The journal's `path` field (§4.2) is forward-slash, root-relative. A journal
  written on a Windows station is byte-identical to one written on Linux for the
  same run, so the repair and reporting tools are platform-free.
- `RUNS` is 5 characters shorter than `RUNS_FINISHED` while the §3.3 label suffix
  spends some of that back; net path length is roughly unchanged, so the
  `MAX_PATH` exposure that `check_long_paths` exists to monitor neither improves
  nor worsens. No new mitigation needed.

## 10. Testing

Each of these must be shown to fail when its guard is removed
(`plan-authored-tests-must-be-falsifiable`).

1. **Layout.** A sequence finishing writes exactly one tree, at
   `RUNS/%Y/%m%d/...`, and no `RUNS_ACTIVE`/`RUNS_FINISHED`/`RUNS_SYNCED`
   directory is created anywhere under root.
2. **No movement.** The absolute path of a `-seq.yml` is byte-identical before
   and after a successful sync.
3. **Label rule.** Table-driven over: no plate; plate absent from label; plate
   already in label; one sample via each of the four sources; a multi-element
   list; a sample with no plate (⇒ no suffix).
4. **Journal eviction.** After a full sequence syncs, both journals replay to an
   empty working set. A journal that still contains the uuid fails.
5. **Torn line.** Append a truncated final line; replay recovers every prior
   record and logs one warning.
6. **Rebuild.** Delete a journal, run the rebuild, assert the working set matches
   what the journal held. Then delete a `.prg` and assert its record reappears as
   unsynced.
7. **Upload set (§3.5).** The three cases in §3.5.2: nosync excluded, a
   registered subdirectory file included, a `.<hex>.tmp` staging file excluded.
   Highest-priority tests in the suite — the first one failing means a station
   ships data it withholds today.
8. **Legacy readers.** A synthetic legacy tree (`RUNS_SYNCED/26.35/0828/...`,
   including a sequence `.zip`) resolves through `FileMapper` and `HelaoData`
   unchanged.
9. **Depth.** `list_pending`/`list_pending_acts`/`list_pending_exps` find records
   in the new layout — i.e. the `*/*/*` depth assumption still holds.
10. **`sequence_path` alias.** An endpoint called with the old
    `sequence_zip_path` keyword still dispatches.

Plus the existing golden-master suites
(`test_active_golden_master.py`, `test_orch_dispatch_golden_master.py`,
`hexagon/tests/smoke/*`) re-baselined deliberately, not silently.

## 11. Out of scope

- **`postfinish_hooks` / `postfinish_analyses`.** Deferred behind this work; see
  `postfinish-extension-points`. The experiment-addressing question recorded
  there is *answered* by this design — a record's path no longer changes and its
  parent no longer archives it away — but building the hooks is separate.
- **Absorbing the act/exp/seq post-processors, SYNC, ANALYSIS and CALC into the
  per-server state tracker as pipeline steps.** Explicitly the eventual goal; the
  journal is the substrate it will need, and nothing here forecloses it. Not
  designed yet.
- **Migrating or re-dating legacy trees.** Never (D1).
- **Retiring the legacy reader branch.** Someday, when no station has a
  pre-cut-over archive mounted. Not scheduled.
- **`RUNS_CORRUPT`/`RUNS_REBUILD`/`RUNS_SUPERSEDED` as live states.** They stay
  repair-tool vocabulary. If quarantine ever becomes a real state it becomes a
  journal value, not a directory (`sync-quarantine-deferred`).
