# Pairing external mass-spec recordings with HELAO records

Date: 2026-08-28
Status: design approved, not yet implemented
Amended: 2026-08-28 (Amendments 1, 2 and 3); 2026-08-29 (Amendments 4 and 5); 2026-08-30 (Amendment 6)

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
| 12 | Slice representation | Wide: `epoch_s` plus one column per mass, named from the scan table |
| 13 | MS calibration | Attach the slice to the archival MS record, scoped to calibration windows only (Amendment 5) |
| 14 | Anchor action | Whichever action `process_order_groups[pidx]` names — never a hardcoded action name (Amendment 5) |
| 15 | MS origin timezone | Pinned by an explicit station-configured parameter, and the raw header strings plus resolved offset recorded (Amendment 6) |

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

- ~~Whether every `ECMS_*` sequence in the backlog carries `process_list`.~~
  **Settled by Amendment 4: all of them do.**
- The lag and baseline-lead values for anchors other than `run_CA`, and whether
  they are stable across the backlog's date range.
- **New in Amendment 4:** whether MS calibration is in scope, given the
  calibration sequences materialise no processes to fold a slice into.

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

## Amendment 3 — 2026-08-28, the recording's file set

The instrument writes six files per recording, sharing a basename. All six were
decoded or accounted for. The conclusion is that **only the `.csv` needs to be
parsed**; the layouts of the others are recorded here so the work does not have
to be repeated if that ever changes.

| File | What it is | Needed? |
|------|-----------|---------|
| `.csv` | Vendor export: header + full-precision time series | **Yes — the only parser** |
| `.dat` | Binary time series, one record per mass per cycle | No; decoded below |
| `.exp` | ASCII cycle index into `.dat` | No; decoded below |
| `.scn` | Scan definitions | No; duplicated by the CSV header |
| `.env` | Full instrument/device property dump | No; superset of the CSV's environment block, static |
| `.ann` | MASsoft view state | No; contains no data |

### `.csv` — the parser target

A 25-line header (its own length is declared on line 2 as
`"header",0000000025,"lines"`), then a `"Data",N` line, a column-heading line, and
the rows. Header line 3 carries the absolute origin as
`"Date",<MM/DD/YYYY>,"Time",<h:mm:ss AM/PM>`. The scan table names the mass
channels; the example recording has five (2, 15, 22, 26, 28) at roughly 300 ms per
cycle, 53049 cycles, about 4.5 h.

Each row is `HH:MM:SS, elapsed_ms, <one float per mass>`. **Use `elapsed_ms`**;
the `HH:MM:SS` column is truncated to the second. Absolute time is the header
origin plus `elapsed_ms`.

### `.dat` — decoded, not needed

A 5-byte preamble, then fixed 46-byte records: a `V1` marker, a `float64`
timestamp in milliseconds at **offset 26**, and a `float64` intensity at
**offset 38**. One record per mass per cycle, in scan-table order. The example
holds 265,245 records — exactly 53,049 × 5 — and decodes to values identical to
the CSV's.

### `.exp` — decoded, not needed

ASCII, 15-character fixed fields, no line terminators, seven fields per cycle:
`[105, 5, <offset>, 5, 5, 1, 114]`. Six are constant; the varying one is the byte
offset of that cycle within `.dat`, stepping by 230 (= 46 bytes × 5 masses).
Verified for all 53,049 cycles with no mismatch, and `5 + 230 × 53049` is the
`.dat` file size exactly. It is a cycle index and carries nothing else.

### `.scn`, `.env`, `.ann` — a shared binary container

All three begin `3A 01 01 00 00` and are Delphi object streams: length-prefixed
strings and class-name tags (`TApexScan`, `TInstrument`, `TAllDeviceProperties`,
`TScanCanvas`, `TTrendView`). The structure is legible; the semantics would need
reverse-engineering, and there is no reason to.

`.ann` is worth naming explicitly because the extension invites a wrong guess: it
holds **no annotations**. Its contents are chart layout — canvas, trend view,
axes, legend items, a font name. There are no user-placed markers in it, so it is
not a candidate source of alignment events.

### What the CSV loses, and why it does not matter

The CSV reports one timestamp per cycle — the *first* mass's — so it implicitly
presents the channels as simultaneous. `.dat` shows they are not: 30, 90, 151,
212, 272 ms in the first cycle, about 60 ms apart, spanning 242 ms.

Against the 23 s lag and the 2 s analysis bins this is 0.26% of the lag and 3% of
a bin. It is recorded here rather than corrected. If per-mass timestamps ever
matter, `.dat` is a short reader given the layout above.

### Consequences for the design

- **The converter parses the `.csv` and nothing else.** Read the declared header
  length rather than hardcoding a row index — the one-off script's `text[29:]`
  silently drops two scans (Amendment 2).
- **The archival record holds the whole recording directory.** Decision 5's
  process-free record should carry all six files, not just the parsed one. They
  are one instrument output, the unparsed ones are small beside the `.csv` and
  `.dat`, and archiving them keeps the `.dat` route open without a second
  decision later.
- **Slice representation (decision 12, approved 2026-08-28).** Wide format, one row per cycle:
  `epoch_s` plus one column per mass channel, named from the scan table
  (`mass_2`, `mass_15`, …). `json_data_keys` is passed explicitly to `ctx.begin`
  so the column order is pinned rather than inferred. Wide rather than the long,
  array-packed shape used by the OceanDirect spectrometer stack, because a
  spectrum there is thousands of pixels with a wavelength axis that must survive
  reframing, whereas this is a handful of fixed named channels — and it matches
  the frame the existing analysis already builds. The channel set is read from the
  recording, not hardcoded, so a recording with different masses works unchanged.
  A recording whose scan table names a channel the column-naming rule cannot
  render is a refusal, not a silently dropped column.

## Amendment 4 — 2026-08-29, the backlog surveyed in full

The whole archive was walked, not sampled: 16 week directories, 38 day
directories, 539 sequence zips, of which **127 are `ECMS_*`**. Every one of the
127 was opened and its experiment ymls parsed. **Zero listing failures and zero
read errors** — coverage is total, not partial. That matters because this
archive is a FUSE network mount, and this repository already carries one
incident where a survey over such a mount silently swallowed errors and returned
a confident clean verdict at about 2% coverage.

### The identity ladder never fires. Coverage is the whole backlog.

Of the 127, **78 contain at least one experiment with a `process_order_groups`
entry, and every one of those experiments carries a populated `process_list`** —
zero exceptions across the archive. Amendment 2 established this for two
sequences; it holds for all of them. The converter's "refuse a record whose
identity cannot be recovered" rule is therefore dead code in practice. Keep it
as a guard, but do not size the work around it.

Those 78 sequences hold **226 processes** in total. Their names:

| Sequences | Name |
|---|---|
| 33 | `ECMS_series_CA_recirculation` |
| 24 | `ECMS_series_CA_recirculation_mixedreactant` |
| 11 | `ECMS_series_CA_recirculation_mixedthreereactant` |
| 7 | `ECMS_CV_recirculation_mixedreactant` |
| 3 | `ECMS_series_CA_change_gasflow` |

Note the CV sequences: the design and its example were built entirely around
`run_CA`. Seven sequences are cyclic voltammetry, whose anchor action and
meaningful window are not the same shape. They are in the 78 and must not be
assumed to behave like a CA.

### The other 49 are skips by design, not refusals

43 are `ECMS_initiation_*` and 6 are `ECMS_MS_calibration*`. None has a process
group. The converter should pass over them silently rather than treating them as
records it failed to process — a refusal count of 49 would read as a defect.

### Calibration has nothing to attach to — this is a real gap

`ECMS_MS_calibration_recirculation` holds five `ECMS_sub_cali` experiments and
**zero actions with `process_finish: true`**, so it materialises no processes by
either the declared or the legacy path. Decision 1 folds an MS slice into an
existing process; for calibration there is no such process, on any of the six
archived calibration sequences.

This is not an oversight in the archive — those sequences produce a calibration
curve, not a measurement. But the one-off analysis script builds that curve from
exactly these windows (anchoring on each `ECMS_sub_cali` experiment's `wait`
action and applying a **+41.0 s** offset, distinct from `run_CA`'s +23.0 s), so
the data is needed even though the record layer has nowhere to put it.

Three ways out, none yet chosen:
1. **Out of scope for the record layer.** The MS raw archival record (decision 5)
   plus the calibration sequence's own action timestamps are sufficient for an
   analysis to recompute the curve on demand. Nothing is added to the record
   layer and nothing is lost — the inputs are all archived.
2. **Give calibration experiments a process.** Correct-looking, but it is a
   change to the deployment's experiment library that only affects future runs;
   the six archived calibration sequences cannot be fixed retroactively without
   inventing processes that never existed.
3. **Attach the calibration slice to the archival MS record instead.** Keeps
   everything in the record layer, but decision 5 deliberately made that record
   process-free, and reversing it there would recreate the competing-process-set
   problem that decision avoided.

### Two smaller confirmations

**Both date layouts coexist in this one archive** — `25.27/20250709` (4-digit
year) beside `26.03/0120`. Discovery must handle both, which it does: the glob
depth is identical and only the directory name differs.

**No zip in the archive contains a `-prc.yml`** (0 across all 127). The archive
is entirely pre-cutover, so the colocation work merged in `bae36d19` benefits
these records only once this converter re-syncs them — which it does, as
Amendment 1 noted.

## Amendment 5 — 2026-08-29, CV inspected and calibration decided

### CV is structurally identical to CA, and that simplifies the design

`ECMS_CV_recirculation_mixedreactant` (7 sequences, 8 grouped experiments each):

```
ECMS_sub_CV   process_order_groups={0: [1]}   process_list=['0671fe71-…']
  order=0  archive_custom_query_sample   contrib=None   finish=False
  order=1  run_CV                        contrib=[action_params, files,
                                                  samples_in, samples_out]
                                         finish=True
  order=2  wait                          contrib=None   finish=False
```

The same slot, the same single-member group, the same contrib set, the same next
free `action_order` of 3, and `epoch_ns` present in its `.hlo` header exactly as
`run_CA`'s is. Only the action name and the duration differ — the inspected CV
measurement runs about 151 s against CA's 600 s.

**So the converter must not match on action name.** Decision 14: the anchor is
whichever action `process_order_groups[pidx]` names. That is data-driven, needs
no per-technique table, and covers CA, CV and `ECMS_series_CA_change_gasflow`
alike. Amendment 2's framing — "anchor on the measurement action" — was right;
this makes it precise and removes the last dependence on `run_CA` specifically.

Two consequences follow. The window LENGTH must be read from the record (the
span from the anchor to the next action, or the anchor's own data extent), never
from a constant: a 600 s CA constant applied to a 151 s CV would drag in four
minutes of unrelated signal. And the LAG stays a single value across measurement
sequences: +23.0 s is a gas-transport delay of the apparatus, not a property of
the technique. The script's +41.0 s was never a second apparatus delay — it was
the same physical lag measured from a different anchor, a `wait` action on the
calibration path. Anchoring uniformly on the measurement action's `epoch_ns`
removes that second constant entirely.

### Calibration attaches to the archival MS record

Decision 13. The six archived calibration sequences materialise no processes, so
there is nothing to fold into; the raw MS record becomes the home for those
slices instead.

This is a deliberate, bounded reversal of decision 5's process-free property, and
the bound is what keeps decision 5's actual purpose intact. **The archival record
materialises processes only for calibration windows — never for the whole
recording.** Decision 5 existed to stop a whole-day process set competing with
the sliced ones that cover the same signal; a calibration-window process covers
time no measurement slice covers, because calibration and measurement happen in
different sequences at different times. The two sets are disjoint by
construction, and the converter should assert that rather than assume it: a
calibration window overlapping a measurement window is a fault, not a merge.

The window rule is the same as everywhere else — anchor on the `ECMS_sub_cali`
experiment's own action, apply the lag, take the window from the record. What it
must NOT reuse is the one-off script's +41.0 s constant, which encodes the offset
from a `wait` action; with the anchor rule of decision 14 the ordinary lag
applies.

## Amendment 6 — 2026-08-30, the recording's timezone

Found by the ingest core's final review, and settled before the pairing work
makes it load-bearing.

The recording's header carries `"Date",11/13/2024,"Time",10:40:45 AM` — a naive
wall-clock stamp with no zone. Parsing it with `strptime(...).timestamp()`
interprets it in the **converting host's** timezone, which is not necessarily the
instrument's.

That is harmless while the raw recording stands alone. It stops being harmless in
the pairing work, which compares these epochs against HELAO action epochs recorded
at the station: a batch host in a different zone shifts every pairing by whole
hours, and the failure is silent — the slices are the right length, drawn from the
wrong part of the day.

**Unit tests structurally cannot catch this.** The fixtures build their expected
origin with the identical conversion, so parser and fixture agree in any
timezone. Nothing in the current test suite would move if the host moved.

**Decision 15, both halves:**

- **Pin it.** The converter takes an explicit timezone for the instrument, from
  station configuration, and interprets the header stamp in that zone regardless
  of where conversion runs. Correct by construction rather than by coincidence of
  deployment.
- **Record it.** The written record carries the raw `"Date"` and `"Time"` header
  strings verbatim alongside the resolved UTC offset. A wrong setting is then
  detectable and correctable after the fact, instead of being invisible in a
  column of plausible numbers.

The second half is what makes the first half safe to get wrong. A pinned zone that
is misconfigured fails exactly as silently as no pinning at all; carrying the
evidence is what turns that from an undetectable error into a recoverable one.

