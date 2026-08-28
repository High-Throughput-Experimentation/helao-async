# Pairing external mass-spec recordings with HELAO records

Date: 2026-08-28
Status: design approved, not yet implemented
Amended: 2026-08-28 (Amendments 1 and 2)

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

**Identity recovery, before anything is written.** **Superseded by Amendment 2** —
identity turned out to be present in the archive all along. The paragraph below
is retained for the reasoning; read Amendment 2 for what the converter does. The archived legacy zips do **not** carry `-prc.yml` entries —
`sync_process` writes them to `root/PROCESSES`, outside the tree that gets zipped
— so the filename map is not recoverable from the archive. An API lookup by
`experiment_uuid` does exist. The ladder is therefore:

1. an API lookup by `experiment_uuid` — the primary source
2. recompute `gen_uuid(f"{experiment_uuid}__{pidx}")` as a **cross-check**;
   agreement with the API raises confidence, disagreement aborts the record
3. `-prc.yml` names in the zip, where present — empty for the current backlog,
   but populated for any sequence re-synced after the relocation of
   *2026-08-28-process-yml-colocation-design.md* ships, including the ones this
   converter itself re-syncs
4. otherwise **abort that sequence and leave it untouched**

Nothing is written until the map is in hand.

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

- Whether every `ECMS_*` sequence in the backlog has the same shape as the two
  inspected, or whether older ones predate `process_list` on the experiment yml.
  The converter refuses a record without it, so this bounds coverage rather than
  risking a wrong write.
- The lag and baseline-lead values for anchors other than `run_CA`, and whether
  they are stable across the backlog's date range.

## Out of scope

- Any change to `ProcessModel` — no dual parentage, no process versioning.
- A quarantine or `RUNS_FAILED` path for held records; decision 6 is
  hold-indefinitely, and quarantine remains deferred until after the hexagon
  migration.
- Re-typing legacy `ecms` records as `agde`.

## Amendment 1 — 2026-08-28

Two facts were confirmed after the design was approved, and one companion
sub-project was split out.

**Legacy zips carry no `-prc.yml`.** `sync_process` writes the process artifact
to `root/PROCESSES`, mirroring the record's relative path but sitting outside the
`RUNS_*` tree that `zip_dir` archives. The zip therefore has no record of process
identity at all. Rung 1 of the original identity ladder is empty for the entire
existing backlog.

**The API lookup by `experiment_uuid` exists**, so it becomes the primary source
and the `gen_uuid` recomputation demotes from a fallback to a cross-check. A
disagreement between the two aborts the record rather than picking a winner:
minting the wrong `process_uuid` would create a duplicate process rather than
update the intended one, which is the failure this whole ladder exists to prevent.

**The deficiency itself is being fixed**, in a separate sub-project specified in
`2026-08-28-process-yml-colocation-design.md`: `-prc.yml` moves to sit beside its
`-exp.yml` inside the `RUNS_*` tree, so it is carried by the sequence zip. The S3
key stays `process/{process_uuid}.json`; readers gain a shared resolver that falls
back to the legacy `PROCESSES` mirror.

Three consequences for this design:

- Future `agde` runs never need the identity ladder. Their zips carry their own
  process identity, so a later reopen reads it directly.
- The legacy `ecms` converter repairs the deficiency as a side effect. It already
  unzips and re-syncs; under the new write location the rebuilt zip gains its
  `-prc.yml` entries, so a sequence processed once by this converter is
  self-describing thereafter.
- Ordering: the colocation sub-project should land **before** the legacy
  converter runs in anger, so the backlog is repaired in one pass rather than
  two.

## Amendment 2 — 2026-08-28, after inspecting a real example

One MS recording and the two `ECMS_series_CA_recirculation_mixedthreereactant`
sequences it pairs with (`CA1` and `CA2`, one day's archive), plus the one-off
pairing script a colleague wrote against them. Findings, in descending order of
how much they change the design.

### The identity ladder is unnecessary. Delete it.

The CA experiment ymls **already carry both fields the converter needs**, inside
the zip:

```
experiment_name: ECMS_sub_CA
process_order_groups: {0: [1]}
process_list: ['06734f93-c4c2-7266-8000-5a70b9bf635b']
```

`process_list` holds the pre-minted uuid7 the orchestrator assigned at experiment
pop, and `process_order_groups` declares the group explicitly. What was missing
from the archive was only the `-prc.yml`, never the identity.

So decision 10 is a no-op rather than a reconstruction: the converter **appends
the MS `action_order` to `process_order_groups[0]` and leaves `process_list`
untouched**. No API lookup, no `gen_uuid` recomputation, no bucket recomputation
from `process_finish` flags. The risk raised before inspection — that an API
returning uuids without group indices would make a positional `process_list`
unbuildable — does not arise.

### These are not `legacy_experiment` records

`legacy_experiment` is true only when `process_order_groups` is absent
(`sync_driver.py:1744`). The CA experiments declare it, so the deterministic path
runs and the `legacy_finisher_idxs` logic is never reached. The design's
discussion of that path does not apply to this population.

### Only five experiments per sequence have a process at all

Each sequence holds 52 experiments across 12 names. Exactly five — the
`ECMS_sub_CA` ones — carry a process group. The other 47 declare no group **and
contain no action with `process_finish: true`**, verified across both sequences,
so they materialise no processes by either path. There is nothing for an MS slice
to attach to on them, and the converter should not try.

This also makes decision 11 unambiguous rather than a heuristic: "the last group"
is group `0`, the only group, containing only the measurement action.

### The CA experiment's shape

```
order=0  archive_custom_query_sample   contrib=None  finish=False
order=1  run_CA                        contrib=[action_params, files,
                                                samples_in, samples_out]
                                       finish=True
order=2  wait                          contrib=None  finish=False
```

Next free `action_order` is **3**. Action directories are named
`{order}__{split}__{SERVER_KEY}__{action_name}/`, which the injected action must
follow. `technique_name` is `None` on the experiment, so the process technique
falls back to `experiment_name` (`sync_driver.py:1819-1821`) — relevant because
the `-prc.yml` filename embeds it.

### Discovery must read an experiment yml, not the sequence yml

`run_type` is **`None` on the `-seq.yml`** and `ecms` on all 52 `-exp.yml` files.
The design's discovery filter (`run_type == "ecms"` on the sequence) would have
matched nothing. Discovery reads one experiment yml, or falls back to the
`sequence_name` prefix.

Sequence yml filenames use `%Y%m%d.%H%M%S%f` (`20241113.110230983651-seq.yml`), so
`HelaoYml.timestamp`'s 4-digit-year fallback (`:317`) is genuinely exercised.
Zip *basenames*, however, are `HHMMSS__<sequence_name>__<label>.zip` with the date
only in the parent directory — a zip basename is not parseable by that method, so
discovery must read the yml inside or compose the date from the parent directory.

### The window rule needs revising: anchor on the contributing action

Decision 4 set the bounds from the experiment timestamp to the terminal action's
timestamp. For this population that is wrong: the CA experiment spans
`11:08:44` to about `11:18:46` and includes a trailing `wait`, while the
measurement is `run_CA`'s 600 s. The colleague's script anchors on the
measurement action, and so should the converter.

The best available anchor is `epoch_ns` from the measurement's `.hlo` header, not
the action yml's `action_timestamp` — they differ by **0.219 s** on the inspected
action (yml stamp is action creation, `epoch_ns` is when acquisition began).
Against a 23 s lag that is about 1%, so the yml stamp is usable, but `epoch_ns`
is strictly better and is present in the zip.

The window also needs a **lead**, not just the measurement span. The script takes
a baseline from `[-71 s, -21 s]` relative to the aligned start, because the
analysis subtracts pre-measurement MS signal. A slice covering only the
measurement would be useless for that.

### The MS time origin is in the file header — do not use mtime

The recording is a HAL RC RGA 201 CSV: a 25-line header, five mass channels
(2, 15, 22, 26, 28), then rows of `HH:MM:SS, elapsed_ms, <5 floats>` at roughly
300 ms cadence — 53049 scans, about 4.5 h. The absolute origin is header line 3,
`"Date",11/13/2024,"Time",10:40:45 AM`. `elapsed_ms` is the precise time base; the
`HH:MM:SS` column is truncated to the second and should be ignored.

The colleague's script instead derives the origin from
`os.path.getmtime()` of the sidecar `.scn`. On this example the two agree to
**0.95 s** — but that is incidental. The `.scn` and `.env` are written at
recording start while the `.csv`, `.dat` and `.exp` mtimes all fall at recording
*end* (about 4.5 h later), and an mtime does not survive a copy without `-p`, an
archival move, or a checkout. **Use the header stamp.** This repository already
carries the same lesson in the Reflex bundle stamp, which refuses mtime for
exactly this reason.

### The lag is per-anchor, not per-station

The script uses **+23.0 s** from `run_CA`'s `epoch_ns` and **+41.0 s** from a
`wait` action's yml timestamp on the calibration path. Two different constants for
two different anchor actions in the same apparatus, because each anchor sits a
different distance from the moment gas reaches the spectrometer. A single
converter-wide `lag_s` would be wrong across experiment types; the parameter must
be keyed by the anchoring action, or supplied per experiment name.

### Two defects in the one-off script, not to be ported

- It reads `text[29:]` while the data rows begin at line 28 (1-indexed), so it
  **silently drops the first two scans**. Harmless at 300 ms cadence against a
  23 s offset, but it is a hardcoded index where the header declares its own
  length on line 2 (`"header",0000000025,"lines"`). Parse the declared length.
- The calibration path converts a yml timestamp with
  `time.mktime(time.strptime(...))`, which is local-time and therefore
  DST-sensitive. The CA path avoids this by using `epoch_ns` directly.

### Consequences for the plan

- Decision 10 shrinks to "append one `action_order` to an existing group".
- Decision 11 stops being a heuristic and becomes a fact about the data.
- The API lookup demoted in Amendment 1 to a cross-check is now not needed at all,
  though it remains available if a record is ever found without `process_list`.
  The converter should refuse such a record rather than reconstructing identity.
- The colocation sub-project is still worth doing on its own merits — it is what
  puts the `-prc.yml` in the zip for future runs — but it is **no longer a
  prerequisite** for the legacy converter, so the two can proceed independently.
