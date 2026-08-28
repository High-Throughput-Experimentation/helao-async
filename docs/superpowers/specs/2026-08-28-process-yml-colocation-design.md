# Colocating `-prc.yml` with its experiment record

Date: 2026-08-28
Status: design approved, not yet implemented
Companion: `2026-08-28-ecms-mass-spec-pairing-design.md` (Amendment 1)

## Problem

A process has exactly one on-disk artifact: the `-prc.yml` that `sync_process`
writes. It is written to `root/PROCESSES`, mirroring the record's relative path
(`sync_driver.py:2046-2053`):

```
save_dir = os.path.dirname(os.path.join(self.helaodirs.process_root,
                                        exp_prog.yml.relative_path))
save_yml_path = os.path.join(save_dir,
                             f"{pidx}__{uuid_key}__{meta['technique_name']}-prc.yml")
```

`PROCESSES` sits *outside* the `RUNS_*` tree, and `zip_dir` archives the sequence
directory. So a sequence zip — the thing that is retained, moved, and reopened —
carries no record of process identity at all.

This is a recurring deficiency rather than a one-off. It is what forces the
legacy `ecms` converter in the companion spec onto an API lookup to recover
`process_uuid` values it should have been able to read out of the archive, and it
is why every `edax` repair tool has to reach sideways into a parallel tree that
may or may not still be beside the zip it is repairing.

The fix: write `-prc.yml` beside its `-exp.yml`, inside the `RUNS_*` tree, so it
travels with the record. Nothing about the upload changes — the S3 key stays
`process/{process_uuid}.json`.

## Decisions

| # | Decision | Chosen |
|---|----------|--------|
| 1 | Transition | Hard cutover; readers fall back to `PROCESSES` for legacy |
| 2 | Record type | `prc` added to `ABR_MAP`, plus a hard guard in `enqueue_yml`/`sync_yml` |

**On 1.** Readers need the legacy fallback regardless of how the write side
changes, so dual-writing buys nothing they do not already require — only doubled
files and a second write that can fail independently. `root/PROCESSES` is never
touched: no migration, no rewriting of archived zips. Rollback for a bad release
is reverting the write site; the data is reconstructible from S3 in any case.

**On 2.** Making `prc` a known type is what lets the readers about to be written
wrap a process yml in `HelaoYml`. The risk it introduces is that a record glob
missed during the sweep would silently treat a process as a syncable record
instead of raising `KeyError`. The guard removes that risk without giving up the
ergonomics.

## Design

### Write site

`sync_process` in both twins (`helao/core/drivers/data/sync_driver.py:2046`,
`helao/hexagon/adapters/native/sync_driver.py:2050`). `save_dir` becomes the
experiment's own record directory — `exp_prog.yml.target.parent` — instead of the
`process_root` mirror. The filename is unchanged, so
`localfs.parse_process_path` (`localfs.py:142-153`), which splits
`{idx}__{uuid}__{technique}-prc.yml` on `__`, keeps working untouched.
`meta_s3_key = f"process/{uuid_key}.json"` (`:2059`) is untouched.

`helao_dirs.py:69,79` continues to create `PROCESSES`. Nothing new is written
there; it stays readable for the legacy backlog.

### Stranding, and why the record would stop cleaning up

`move_to_synced` moves `misc_files + hlo_files` and then the record yml. A
`-prc.yml` is in none of those sets — `_is_syncable_misc_file` (`:481`) excludes
`.yml` — so a colocated one would be left behind in `RUNS_FINISHED`.

The consequence is worse than an orphan file. The empty-directory check at
`:408` walks up from the moved record and reports `"is not empty"` on any
directory still holding something, so the leftover prc would stop the experiment
directory from ever being cleaned up.

Fix: a `process_ymls` property on `HelaoYml` — glob `*-prc.yml` in the target
directory — included in the set that `move_to_synced` relocates alongside the
record.

### Type and guard

`ABR_MAP["prc"] = "process"` in both twins (`:64`, native `:68`).
`enqueue_yml` (`:1246`) and `sync_yml` (`:1274`) refuse a `process`-typed yml,
log it, and drop it without requeuing.

This is not hypothetical. `/finish_yml` (`helao/deploy/hte/servers/action/
sync_server.py:185`) ranks an unrecognised suffix `-1` (`:198`), and `-1` is above
`enqueue_yml`'s `rank_limit=-5`, so a hand-POSTed prc path *enqueues* rather than
dropping. Today it would reach `HelaoYml.type` and raise `KeyError: 'prc'`.

### Glob tightening

**Two** bare `*.yml` globs in each twin would otherwise wrap a colocated prc as a
record. They become suffix-filtered to `act`/`exp`/`seq`:

- `:432` — `list_children`, which globs `parent/*/*.yml`; from a sequence
  directory that is the experiment directories, so it would return both the
  `-exp.yml` and its prc siblings
- `:528` — `parent_path`, which globs two directories up and takes `p[0]`. A
  `{pidx}__…-prc.yml` sorts ahead of a timestamped `-exp.yml`, so it would win
  that index more often than not.

`HelaoYml.__init__`'s directory glob at `:275` needs **no** change — it is
already filtered to `-seq`/`-exp`/`-act` (an earlier draft of this spec
miscounted it as a third site).

The guard is the backstop; the tightening is what stops a prc being reached by
record traversal at all.

**The three pending-scan globs are already safe, but only by suffix.**
`list_pending` (`:2149`), `list_pending_exps` (`:2185`) and `list_pending_acts`
(`:2167`) end in `*-seq.yml`, `*-exp.yml` and `*-act.yml`. Note that a colocated
prc sits at `week/date/seq/exp/`, which is exactly the depth
`list_pending_exps` walks — it is excluded by the suffix, not the depth. That
pattern must never be loosened to `*.yml`, and a test should pin it.

### Zip round-trip

No change needed. `zip_dir` takes the whole sequence directory, so prc ymls enter
the zip automatically. `reset_sync` (`:2262`) extracts everything but
`.prg`/`.lock`, so they come back on a reopen.

### Readers

One shared resolver in core:

```
find_process_ymls(experiment_yml_or_dir) -> list[Path]
```

Colocated `*-prc.yml` first, then the `PROCESSES/<relative_path>` mirror,
deduplicated by `process_uuid` with the colocated copy winning. Every reader calls
it rather than globbing either location directly.

**`localfs.py` — mostly already correct.** It splits yml paths by suffix
including `prc` (`:258-261`), and its zip branch already unions the zip's own
ymls with a `PROCESSES/**/*-prc.yml` disk glob (`:242-245`). Two changes:

- deduplicate the union by `process_uuid`, so a record that has both a colocated
  copy and a legacy mirror entry does not yield the process twice
- `get_yml` (`:368`) decides zip-vs-disk with
  `self.target.endswith(".zip") and not path.endswith("-prc.yml")`. That is
  correct only while prc ymls never live inside zips. It must discriminate by
  whether the path is a member of the zip, not by its suffix.

**Other in-repo call sites.**

- `helao_data.py:132` takes `[0]` of a bare `glob(target/*.yml)`. Must select the
  record yml by suffix explicitly.
- `processors.py:48` globs `exp_dir/*.yml`. Must exclude prc.
- `hexagon/tests/smoke/assert_smoke_tree.py:20-21` asserts four `-prc.yml` under
  `PROCESSES`. Retargets to the `RUNS_*` tree.
- `hexagon/tests/test_native_sync_parity.py` compares `PROCESSES` prc ymls across
  the two twins. Retargets. Parity still holds because both twins change
  identically — which is also why they must change in the same commit.

**Private-repo call sites.** The `edax` tools read
`PROCESSES/<rel>/**/*-prc.yml`: `retire_duplicate_records.py`,
`rebuild_journal_zips.py`, `prune_process_sets.py`, `requeue_held_journal.py`,
`reconvert_duplicates.py`, `rebuild_sequence_analyses.py`. They live in a separate
git repository nested in-tree, so they land as their own commit there. They switch
to the shared resolver — they are not legacy-only tools and would otherwise stop
seeing processes on new data.

## Invariants

- Both `sync_driver.py` twins change in the same commit. They are byte-pinned.
- `meta_s3_key` stays `process/{process_uuid}.json`. The bucket layout does not
  move.
- The `-prc.yml` filename format stays `{pidx}__{uuid}__{technique}-prc.yml`;
  `localfs.parse_process_path` splits on `__` and would break on any other shape.
- No record-discovery glob may use a bare `*.yml` pattern inside a record
  directory.
- `root/PROCESSES` is never written to, moved, or deleted by this change.

## Failure handling and rollback

The write site is a single `os.path.join`; a release that gets it wrong is
reverted by reverting that. No data is migrated, so there is no half-migrated
state to recover from, and no archived zip is rewritten.

A prc yml that fails to write leaves `process_s3` unset for that `pidx`, so the
existing retry path handles it exactly as it does today — the local write and the
S3 push are already sequential in `sync_process`.

The one genuinely new failure is a prc stranded by a `move_to_synced` that missed
it, which surfaces as a record directory that never cleans up. The test below
pins it.

## Testing

- `sync_process` writes the prc beside the `-exp.yml` and nothing appears under
  `process_root`.
- The S3 key is unchanged — assert on the `to_s3` target.
- A synced experiment leaves **no** file behind in `RUNS_FINISHED`, and the
  directory cleanup reports success rather than `"is not empty"`.
- A sequence zip contains its `-prc.yml` entries, and `reset_sync` restores them.
- `HelaoYml` on a `-prc.yml` reports type `process`; `enqueue_yml` and `sync_yml`
  both refuse it; POSTing a prc path to `/finish_yml` is dropped rather than
  raising.
- `list_pending_exps` does not return a colocated `-prc.yml` — the pin on the
  depth-vs-suffix hazard.
- `find_process_ymls` resolves colocated, legacy-mirror, and both-present cases,
  with the colocated copy winning the dedupe.
- `localfs` loads processes from a zip that contains them, from a legacy zip plus
  its `PROCESSES` mirror, and from a mixed pair without duplication.

Fixtures: `helao/hexagon/tests/sync_fixtures.py` already builds these trees, and
`helao/core/tests/unit_test_sync_process_recovery.py` already exercises
`process_root`.

## Out of scope

- Migrating or backfilling the existing `PROCESSES` tree.
- Rewriting archived `RUNS_SYNCED` zips to insert prc ymls. The legacy `ecms`
  converter does this incidentally for the sequences it reopens; nothing else
  should.
- Any change to `ProcessModel`, to the S3 layout, or to the API push.
- Analysis artifacts, which have their own tree and are untouched.
