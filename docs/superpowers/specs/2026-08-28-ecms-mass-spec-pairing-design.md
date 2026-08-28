# Pairing external mass-spec recordings with HELAO records

Date: 2026-08-28
Status: design approved, not yet implemented

## Problem

A mass spectrometer records continuously for a day. That single recording overlaps
many HELAO sequences. Its data must end up inside the HELAO processes those
sequences produced, paired by timestamp.

The obstacle is timing. The orchestrator declares an experiment's
`process_order_groups` when the experiment is popped from the queue, and
`HelaoSyncer` materialises the processes only after the contributing actions have
uploaded. By the time the MS recording is cut and converted, the HELAO records for
that day have already been finalised, and — for the legacy backlog — synced,
zipped and uploaded.

Two populations need solving, and they are different problems:

- **Future `agde` runs.** Records can be made to wait. The MS data is folded in
  before the record ever syncs.
- **Legacy `ecms` runs.** Records are already in `RUNS_SYNCED` as zips, already in
  S3 and the database. They must be reopened, patched, and re-synced without
  changing their identity.

## Decisions

| # | Decision | Chosen |
|---|----------|--------|
| 1 | What a MS slice *is* in the model | An action folded into an existing process (mutate in place) |
| 2 | When it is folded | Selective hold in `RUNS_FINISHED`, then one sync |
| 3 | Who declares the MS action's slot | A hold marker written by the experiment, carrying the contract |
| 4 | Slice bounds | Experiment timestamp to terminal-action timestamp, plus lag/lead offset |
| 5 | Raw day recording | Its own process-free archival record; slices reference it |
| 6 | Hold escape when MS never arrives | Hold indefinitely, alert only — nothing auto-cleared |
| 7 | Clock reconciliation | Both hosts NTP-synced; MS stamps taken as absolute epoch |
| 8 | Hold granularity | Sequence-scoped gate, experiment-authored marker |
| 9 | Legacy mutation | `reset_sync` → inject → full re-sync |
| 10 | Legacy process identity | Explicit `process_order_groups` plus a `process_list` pinned from the archive |
| 11 | Legacy group selection | The last process group of each experiment only |

### Notes on the ones that were close

**8 — sequence scope over experiment scope.** A record moves to `RUNS_SYNCED` on
its own as soon as `s3_done and api_done`, independent of its siblings, so an
experiment-scoped hold would leave a sequence half-drained across two trees at zip
time. That partial-tree shape is behind this repo's duplicate-record and
"process index missing" history. The MS recording spans whole sequences anyway, so
per-experiment granularity buys hours, not days.

**9 — full re-sync over a delta.** `reset_sync` strips `.prg` deliberately, so the
re-sync re-uploads the whole sequence rather than just the MS delta. That cost is
accepted in exchange for every invariant being the proven one and the renamed
`.orig` zip being a one-file rollback.

**11 — last group only.** This is an assumption about legacy experiment shape.
It is honoured, but made loud rather than silent: see *Failure handling*.

## Part 1 — Future `agde` runs

### Components

**The hold marker.** A dotfile, `.ms_hold.json`, in the *experiment* record
directory. Dotfile deliberately: `_is_syncable_misc_file`
(`helao/core/drivers/data/sync_driver.py:481`) excludes dotfiles and
`.yml`/`.hlo`/`.lock`/`.tmp`, so the marker is never uploaded as an artifact.

It carries:

- `process_groups` — the `process_group_index` values expecting MS data
- `action_order` — the order the injected MS action will take
- `t_start_epoch`, `t_end_epoch` — the region of interest
- `lag_s`, `lead_pad_s`, `trail_pad_s` — transport delay and padding
- `expected_source` — which MS stream should satisfy it
- `created_epoch`

`action_order` is derived, not chosen: the terminal action knows its own order,
so the marker reserves `own_order + 1`, which no dispatched action can hold
because the terminal action is the last one. Bounds are likewise derived rather
than hand-specified: `t_start_epoch` is the experiment timestamp, `t_end_epoch`
is the writing action's own timestamp. The action that
writes the marker is the experiment's terminal action, so it knows both. This
rule is chosen partly because it is also derivable *retroactively* from archived
ymls, which is what makes Part 2 possible.

**Who writes it.** A terminal action in the `agde` experiment
(`declare_ms_hold`) whose params carry the contract, writing the dotfile one level
up into its parent experiment directory. The write side stays entirely in
deployment experiment code.

**The syncer gate.** The only framework change. Two placements, because
`enqueue_yml` is not the sole choke point — `syncer()` pops the queue and calls
`sync_yml` directly (`sync_driver.py:1206`), so a record already queued when a
marker appears would still run:

- an early skip in `enqueue_yml` (`:1246`) to avoid queue churn
- an authoritative early return at the top of `sync_yml` (`:1274`)

Both resolve the *sequence* directory from the yml path and check for any
`.ms_hold.json` beneath it. The worker drops a gated record without requeuing; the
next `finish_pending` scan re-offers it. A memoized check keyed on sequence
directory plus directory mtime keeps this off the hot path.

**The MS batch converter.** A new converter on the existing `BatchConverter`
framework (drop → processing → done/failed, checkpoint sidecars, `move_bundle`),
producing two independent outputs:

- the **archival record** — the whole-day file as its own sequence/experiment/
  action with empty `process_contrib`. `update_process` is only reached for
  actions that declare one (`:1695`), so this record materialises **zero
  processes** and cannot compete with the `agde` ones.
- the **slice injections** into held experiments.

**The pairing resolver.** Inside the converter. Matches markers to the recording
by absolute epoch overlap, applies `lag_s` and padding, slices.

### Data flow

1. Orchestrator runs the `agde` sequence normally. The terminal action writes
   `.ms_hold.json`. Experiment and sequence finalise into `RUNS_FINISHED` with no
   special handling.
2. Syncer sees a marker under the sequence and skips the whole sequence. Repeats
   indefinitely; an alert fires once a hold exceeds an age threshold. Nothing is
   ever auto-cleared.
3. The day's recording is cut and dropped into the batch source drop directory.
4. Converter claims it and writes the archival record into `RUNS_FINISHED`. That
   record carries no marker, so it syncs immediately and independently.
5. Converter scans `RUNS_FINISHED` for markers the recording can satisfy. For each,
   **in this order**: write the sliced `.hlo`; write the MS `-act.yml` (with
   `process_contrib`, and the archival record's `action_uuid` plus time range in
   its params); patch `process_order_groups` in the `-exp.yml` to add the reserved
   `action_order`; **delete the marker last**.
6. Next scan finds no marker and enqueues the sequence. `update_process` folds the
   MS action into the declared group. One process materialises carrying both the
   electrochemistry and the MS contributions, single-parented to the orchestrated
   sequence, referencing the archival record for the raw.

The delete-last ordering is what makes step 5 safe against the syncer racing it:
the sequence is gated for the whole edit, and the gate lifts only after every
write has been renamed into place. Both the yml patch and the action write use the
established `.<name>.<uuid1hex>.tmp` + rename convention.

### Why parentage is not doubled

`ProcessModel.sequence_uuid` and `.experiment_uuid` are scalars
(`helao/core/models/process.py:65-66`); a process has exactly one sequence, and
dual parentage is not expressible without a model change. It is not needed. The
MS *slice action* lives inside the orchestrated experiment, so the process stays
single-parented there. The archival record is referenced one-way, by uuid, from
the slice action's params. It is a pointer, not a parent — and because it
materialises no processes, it cannot produce a competing process set covering the
same signal.

## Part 2 — Legacy `ecms` runs

A separate converter, but only the front half differs. Once a legacy sequence is
unzipped into `RUNS_FINISHED` and patched, it rejoins the identical injection and
sync path as Part 1.

### Two premises that turned out not to hold

**The folder-layout difference does not affect the syncer.** `list_pending` globs
`RUNS_FINISHED/*/*/*/*-seq.yml` (`sync_driver.py:2149`) — three levels above the
seq yml. Legacy `%y.%w/%Y%m%d/<seq>` and current `%y.%w/%m%d/<seq>` are the same
depth, so both match. `HelaoYml.timestamp` (`:317`) already falls back to a
4-digit-year filename parse. The layout only matters to the converter's own
discovery glob.

**S3 keys are uuid-keyed, not path-keyed** — `raw_data/{action_uuid}/{name}`,
`{type}/{uuid}.json`, `process/{uuid}.json` (`:1445`, `:1593`, `:2059`). Nothing
about the on-disk date layout reaches the bucket.

### Flow

**Discovery.** Glob `RUNS_SYNCED/*/*/*.zip` (matches both layouts), filter by
sequence timestamp against the recording window, open the candidate and confirm
`run_type == "ecms"`.

**Identity recovery, before anything is written.** `sync_process` names its local
artifact `{pidx}__{uuid_key}__{technique_name}-prc.yml` (`:2053`), so where the
zip carries `-prc.yml` entries the whole pidx→`process_uuid` map is readable from
the filenames alone. Source ladder:

1. `-prc.yml` names in the zip
2. an API lookup by `experiment_uuid`
3. recompute `gen_uuid(f"{experiment_uuid}__{pidx}")`, accepted only if it agrees
   with one of the above
4. otherwise **abort that sequence and leave it untouched**

Nothing is written until the map is in hand. Which rung actually applies to the
real backlog is to be settled against the example legacy sequences, not guessed.

**Unzip.** `reset_sync(zip_path)` (`:2262`) extracts everything but `.prg`/`.lock`
into the parallel `RUNS_FINISHED` directory and renames the zip to `.orig`. That
rename is the rollback.

**Window derivation.** No marker exists, so bounds come from the same rule as
Part 1, read retroactively out of the archived ymls: experiment timestamp for the
start, last action timestamp for the end. `lag_s` and padding are converter
parameters rather than per-record values.

**Group selection.** The last process group of each experiment only.

**Patch.** Write `process_list` verbatim from the recovered map and an explicit
`process_order_groups` reproducing the legacy buckets — recomputed from the
actions' `process_finish` flags — with the MS `action_order` added to the last
group. `process_list[pidx]` short-circuits the uuid formula (`:1824`), so identity
is pinned by data rather than re-derived.

Without this, a legacy experiment takes the `legacy_finisher_idxs` path (`:1744`),
where an MS action appended after the last finisher becomes `pidx = len(pf_idxs)`
— a new, MS-only process rather than a contribution to the electrochemistry one.

**Re-sync.** Drop the patched sequence into the normal pending scan. Full
re-upload, uuid-keyed S3 destinations, the same processes overwritten.

## Failure handling

**Held record never satisfied.** The hold persists. A throttled log line, and an
alert once the hold exceeds an age threshold. No auto-clear, no partial process
in the database, nothing written off. This is deliberate and matches the syncer's
existing philosophy; the cost is that a missed MS conversion parks a day of
electrochemistry data until a human resolves it.

**Partial recording.** Markers the recording covers are satisfied; the rest stay
held.

**Converter crash mid-injection.** The marker is deleted last, so the sequence is
still gated and the injection is retried. The MS action must therefore carry a
deterministic uuid5 derived from `experiment_uuid` plus the source recording, so a
retry overwrites rather than duplicates. `update_process`'s idempotency guard is
`action_uuid`-keyed (`:1731`), which makes a replayed fold safe.

**Legacy refusals — each leaves the record exactly as found.** A sequence whose
uuid map cannot be recovered; whose recomputed legacy buckets disagree with the
recovered map; whose window is not fully covered by the recording; or whose last
process group has no contributing actions or a span that does not overlap the
recording. That last one is what keeps decision 11 from failing silently: the
chosen `process_group_index` is also recorded in the injected MS action's params,
so the assumption is auditable after the fact.

**Interrupted legacy re-sync.** `reset_sync` strips `.prg`, so a re-sync restarts
rather than resuming from stale progress; and re-running it is safe because the
`.orig` rename is idempotent and the pinned `process_list` makes the minted
process identity independent of how many times it runs.

**Clock skew.** Assumed away by decision 7. The archival record should record the
MS file's own start stamp so a skew can at least be diagnosed after the fact.

## Invariants

- The hold marker must stay a dotfile, or the syncer uploads it as a misc file
  (`:481`).
- The gate must be added to **both** `sync_driver.py` twins —
  `helao/core/drivers/data/` and `helao/hexagon/adapters/native/`. They are
  byte-pinned and must change together.
- The archival record's action must declare no `process_contrib`, or it will
  materialise processes competing with the `agde` ones.
- Every write into a record directory uses the `.<name>.<uuid1hex>.tmp` + rename
  convention, or the syncer's glob can catch a half-written file.
- Marker deletion is always the last step of an injection.

## Testing

Temp trees built with `helao/hexagon/tests/sync_fixtures.py`, whose `make_exp_tree`
and `exp_meta` already construct these shapes.

**Gate.** A sequence with any marker beneath it enqueues nothing and syncs nothing;
one without does both normally; a marker never appears in `misc_files`; a record
already in the queue when a marker appears returns early from `sync_yml` without
requeuing.

**Injection.** The exp-yml patch adds the `action_order` to the intended pidx and
is idempotent under replay.

**End to end, future.** A held sequence plus a synthetic recording: run injection,
run the syncer, assert one process materialises carrying both the electrochemistry
and the MS contributions, and that the archival sequence materialises zero
processes.

**End to end, legacy.** A synthetic zipped legacy sequence round-trips through
unzip → patch → re-sync and materialises processes carrying **the same uuids** it
started with, with MS contributions added to the last group only.

**Negative.** A recording that misses the window leaves the marker in place and the
sequence unsynced. A legacy sequence with an unrecoverable uuid map is left
byte-identical.

## Open, to settle against example data

- Which rung of the legacy identity ladder the real backlog actually reaches —
  whether archived zips carry `-prc.yml` entries, and whether an API lookup by
  `experiment_uuid` exists.
- The MS recording's own format, and therefore the slice representation and
  `json_data_keys` of the injected action.
- Concrete `lag_s` and padding values per station.

## Out of scope

- Any change to `ProcessModel` — no dual parentage, no process versioning.
- A quarantine or `RUNS_FAILED` path for held records; decision 6 is
  hold-indefinitely, and quarantine remains deferred until after the hexagon
  migration.
- Re-typing legacy `ecms` records as `agde`.
