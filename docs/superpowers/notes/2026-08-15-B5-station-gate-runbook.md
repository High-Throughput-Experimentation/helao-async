# B5 station gate runbook

**Merged to `unstable`** 2026-08-15, on Linux evidence alone.
**Spec:** `docs/superpowers/specs/2026-08-15-B5-hte-port-design.md` §5
**Status:** every Linux gate is green; **no station has run this yet.**

B5 ported all 23 hte action modules, the orchestrator entrypoint, and three
driver modules from `BaseAPI`/`OrchAPI`/`Base`/`Active` to the native
`ActionHost`/`OrchHost`. Nothing proves it on hardware.

**This is a first-launch checklist, not a campaign.** The decision was to merge
on the Linux gates and let each station gate itself the next time it is used,
rather than hold the branch for a whole-fleet sweep. So the work below is
what to do the *first* time each station comes up on this code — by whoever is
already using it, not by someone making a special trip.

Two consequences of that choice, worth being clear-eyed about:

* a station can now meet a defect during real work rather than during a drill,
  so the failure modes in "Read this first" matter more, not less;
* the pre-change capture in step 1 needs a revision **before** the B5 merge.
  Once a station has pulled, its own history no longer contains one. Use the
  merge's first parent, or `freeze/pre-legacy-removal_2608`.

Do steps 3, 4 and 5 every first launch. Steps 1 and 6 (the golden diff) need
planning ahead — if that is not practical for a given station, say so in the
table rather than leaving the row ambiguous.

---

## Read this first

**Launching the non-`_hex` config is not a rollback.** `adss3.yml` and
`adss3_hex.py` both reach the same `makeApp`, and that function now returns an
`ActionHost` for every action server. The `_hex` variant's write graft is a
no-op on a native host and the plain `.yml` never had a graft. So both configs
serve the native host on this branch. **Rollback is `git checkout unstable`,
or `freeze/pre-legacy-removal_2608` if `unstable` has moved.**

**Capture the golden BEFORE checking the branch out, and understand why.**
The reference for this phase is a **git revision**, not a config key. On
`unstable` hte's action modules still build a legacy `BaseAPI`; on this branch
they build an `ActionHost`. So the only legacy-vs-native comparison available
is "capture on `unstable`, checkout, capture again, diff". Once the branch is
checked out there is no legacy build of these modules left on this working copy
to capture from — B1 learned that the expensive way.

**The per-family canaries under `helao/hexagon/tests/smoke/` no longer prove
anything about this port, and a green run from them is not evidence.** Each is
a config pair — `<family>.yml` with `deployment: hte` against `<family>hex.yml`
with `deployment: hexagon` — built for P3a to compare the two compositions. The
`hexagon` side routes through a shim whose `LEGACY_MODULE` names the *same* hte
module the `hte` side imports directly, and B5 ported that module. Measured:
**29 of the 31 config pairs now build an `ActionHost` on both sides** (the two
exceptions are the biologic pair, which raises the same Windows-only import
error on both sides and would self-compare at hispec too). `co2_diff.bat PASS`
means a native host was diffed against itself and could not have failed.
`helao/hexagon/tests/test_hte_canary_reference_is_gone.py` pins this.

They remain useful for one thing: the **openapi canary** half still catches a
route-surface regression against the frozen per-server checklists, because that
comparison is against a checked-in file rather than against the other side of
the pair.

**A bad outcome here does not look like a crash at launch.** The route surface
is proven identical, so servers come up and answer. What a hardware fault would
look like is an action that starts and never finishes, an `.hlo` that is empty
or absent, or an e-stop leg that silently does nothing.

---

## What each station runs, and which of its servers B5 changed

Every server listed is changed — B5 ported all of them. The orchestrator
(`ORCH`) changed on all seven.

| station | servers |
|---|---|
| `ccsi2` | CALC, CLEANSYRINGE, CO2SENSOR, DOSEPUMP, MFC, N2MFC, NI, ORCH, SAMPLE, SYNC, WATERSYRINGE, WORKSYRINGE |
| `eche10` | CAM, IO, KMOTOR, MOTOR, ORCH, PSTAT (gamry), SAMPLE, SPEC_T, SYNC |
| `anec` | IO, MOTOR, NI, ORCH, PAL, PSTAT (gamry), SAMPLE, SYNC |
| `adss3` | CLEANSYRINGE, MOTOR, NI, ORCH, PAL, PSTAT (gamry), SAMPLE, SYNC, WORKSYRINGE |
| `clad` | CLEANSYRINGE, MOTOR, NI, ORCH, PAL, PSTAT (gamry), SAMPLE, SYNC, WATERSYRINGE, WORKSYRINGE |
| `ecms1` | CALC, CALIBRATIONMFC, CALIBRATIONMFCSECOND, MFC, NI, ORCH, PSTAT (gamry), SAMPLE, SYNC |
| `hispec` | ANDOR, CALC, IO, KMOTOR, MOTOR, ORCH, PSTAT (**biologic**), SAMPLE, SYNC |

### Four more stations, whose configs live in private deployments

**These were missed when this document was first written** and are affected
exactly as the seven above are. The station map was built by globbing
`helao/deploy/hte/configs/*.yml`; these configs live in a private deployment's
own `configs/` directory while their servers resolve to hte modules through the
launcher's deployment fallback. Nothing about them is special — the omission
was in how the list was gathered.

| station | B5-changed servers it runs |
|---|---|
| `uvis4` | CAM, IO, MOTOR, PAL, PDU, SAMPLE, SPEC_R, SYNC, ORCH |
| `amts` | PSTAT (gamry), SYNC, ORCH |
| `note1` | SYNC, ORCH |
| `electrode-demo` | ORCH, OPERATOR, VIS, CONTROL, UI |

`electrode-demo` was missed a second time, by a subtler version of the same
mistake: the three above were found by looking for stations running hte
**action** servers, and this one runs none. Its deployment owns only
`servers/action/`, so every *other* group falls back to hte — the orchestrator,
the operator, both Bokeh visualizers and the Reflex UI. Its action servers
(MOTION, IO, PSTAT, MUX) are the deployment's own, reached through the generic
graft, and are B6's business rather than B5's.

That makes it the only station here that exercises the B5 orchestrator, operator
and visualizer surface **without** any hte action server underneath, which is
worth having in the set: everywhere else those servers are validated incidentally,
alongside the action modules the smoke sequence is really driving.

**The route-checklist gate does not apply to it.** The frozen checklists under
`helao/hexagon/tests/checklists/hte/` cover action modules and the BaseAPI system
surface; there is no frozen checklist for `async_orch2`, `standalone_operator`,
`action_visualizer` or `control_visualizer`. For this station the gate is the
smoke sequence and the on-station golden diff, and the checklist column should be
read as not-applicable rather than skipped.

Its hexagon variant is `electrode-hex`, already present and derived from
`electrode-demo` through `hexagon_variant` rather than copied — so unlike the
paired `*_hex` YAMLs elsewhere in this programme there is no second copy of the
station's hardware params to go stale. Launch `electrode-hex` to validate;
launch `electrode-demo` to roll back.

`uvis4` carries the most of any station in the programme after ccsi2, and it is
the **only** live consumer of `pdu_server` anywhere — the module the B5 spec
recorded as having no station gate. It has one; it is here.

`SYNC` is worth calling out separately: it runs on all seven hte stations and
on all three of these, so it is the single highest-blast-radius module B5
touched. A `SYNC` fault is a fault everywhere.

**Preferred order, where there is a choice: `ccsi2`, `eche10`, `anec`, `adss3`,
`clad`, `ecms1`, `hispec`, then `uvis4`, `amts`, `note1`.** Stations will come
up in whatever order work demands; this is only what to prefer when two are
equally convenient.

`ccsi2` first because its unique modules (`co2sensor_server`, `diapump_server`)
are the smallest ports in the phase and it runs no motion or PAL. `hispec` last
because `biologic_server` is the only module in the deployment with **no Linux
build gate at all** — `easy_biologic` raises `OSError` at import off Windows —
so hispec is the first and only place its constructor has ever run.

**Six modules will still have no station gate when all seven pass**, and no
later station adds one. `analysis_server`, `HTEdata_server`, `o2sensor_server`,
`power_supply_server` and `tec_server` are in no live hte config (commented out
or archive-only), and `pdu_server`'s only live consumer is a station in a
private deployment, which is B6's gate. Those six rest on the frozen route
checklist and the ratchet. Do not let a "7/7 stations passed" summary imply
otherwise.

---

## Per-station procedure

Substitute `<station>` throughout.

### 1. Capture the pre-change golden — on `unstable`, before touching the branch

**Not `harness.capture --scenario GM-1`.** The built-in GM scenarios post to
`/SIM/acquire_data` — `ws_simulator`, from the `test` deployment — and no hte
station runs a SIM server. `harness/capture.py` takes `--scenarios <dotted
module>` for a deployment's own table, and hte has none, which is why the
capture here is of the station's *own* smoke sequence rather than a GM
scenario.

With `unstable` checked out, launch the station normally, run the smoke
sequence from step 5, let it drain, then snapshot the run tree:

```
git rev-parse HEAD                       # record it in the sign-off table
cp -a <root>/RUNS_FINISHED  <goldens>/<station>/pre/RUNS_FINISHED
cp -a <root>/RUNS_SYNCED    <goldens>/<station>/pre/RUNS_SYNCED   # if this station syncs
```

Readiness probes must POST. Every HELAO private route is a POST, so a GET to
`/loaded_modules` returns 405, which a naive probe reports as "server down" —
that cost a whole five-scenario run once, against a group whose own log showed
it healthy.

### 2. Pull

```
git status --short --branch          # confirm a clean tree first
git pull                             # unstable now carries B5
```

If the station's deployment directory is a nested private repo, it is not
affected by B5 and does not move.

### 3. Preflight

```
python -m helao.hexagon.preflight helao/deploy/hte/configs/<station>_hex.py
```

Expect no findings. This resolves the config without launching anything.

### 4. Launch and watch for a server that exits on its own

```
python launch.py <station>_hex --no-hot-reload
```

Every server must bind, and `supervise_early_exits` must report nothing exiting
within its 90 s window. A native host that fails in a startup event surfaces as
`SystemExit(3)` from uvicorn with no other message — if a server disappears,
read its own log under `LOGS/<server>/`, not the launcher's.

### 5. Run the station's own smoke sequence

Queue the sequence this station is normally exercised with and let it drain to
`RUNS_FINISHED`. What to watch:

- every action produces its `.hlo`, not just its `-act.yml`. An empty or
  missing `.hlo` with a completed action is the signature of a write path that
  is not running, and it is silent on both the wire and the UI;
- `SAMPLE` and `SYNC` behave — they are on all seven stations, so a fault here
  is a fault everywhere;
- the sequence reaches `RUNS_SYNCED` if this station syncs.

### 6. Golden diff — the branch's tree against `unstable`'s

Snapshot the run tree the step-5 sequence produced, exactly as in step 1:

```
cp -a <root>/RUNS_FINISHED  <goldens>/<station>/post/RUNS_FINISHED
cp -a <root>/RUNS_SYNCED    <goldens>/<station>/post/RUNS_SYNCED
python -m harness.parity --golden <goldens>/<station>/pre \
                         --candidate <goldens>/<station>/post
```

`harness.parity` accepts a bare capture root as the candidate, so the two
snapshots compare directly. Expect **0 diffs** beyond the normalizations the
differ already applies (uuids, timestamps, host names).

Both sides must come from the **same sequence on the same hardware**, run once
on `unstable` and once on the branch. A difference in what was submitted makes
the diff unreadable, and this is the only genuinely legacy-vs-native evidence
the phase gets.

### 7. E-stop drill

Trigger the station's e-stop with an action in flight and confirm the cascade
reached every server.

**Read `LIVE_VIS.log`, not the UI.** Each leg of the cascade has its own
`try/except`, so a leg that failed leaves nothing on screen — P5 recorded this
after an e-stop that looked clean and was not. "No error appeared" is not
evidence for a safety path.

### 8. Endpoints that only a station can exercise

Three endpoints were ported by hand rather than mechanically, because they take
the Action without opening a session — they must be able to reject with an
error code and **no artifacts on disk**. Where the station has the hardware,
exercise both branches:

- `MOTOR /run_aligner` — reject path: no aligner host, or a precheck rejection.
  Confirm the rejection writes no run directory.
- `NI /cellIV` — reject paths: driver already measuring, and no valid sample.
  On the success path confirm each cell's `.hlo` header still carries its own
  sample label (`sample_global_labels`), which is the one field the port had to
  add to the native session factory.
- `SPEC_T /acquire_spec_extrig` — reject paths: trigger configuration failure,
  and no valid sample. On success confirm the spectrum file header carries both
  the wavelength array and the sample labels.

PAL's fifteen endpoints share this shape through `_pal_start`; the busy guard
rejecting with `in_progress` and leaving no artifacts is the case to see once.

### 9. Rollback if anything fails

```
git checkout freeze/pre-legacy-removal_2608
```

`unstable` carries B5 now, so it is no longer the rollback. The freeze branch
is. Record what failed, on which server, with the log excerpt — not a summary.

---

## Sign-off

| station | date | `unstable` rev captured | golden diff | smoke | e-stop | by |
|---|---|---|---|---|---|---|
| `ccsi2` | | | | | | |
| `eche10` | | | | | | |
| `anec` | | | | | | |
| `adss3` | | | | | | |
| `clad` | | | | | | |
| `ecms1` | | | | | | |
| `hispec` | | | | | | |
| `uvis4` | 2026-08-17 | ≥ `118660ee` | prod run † | prod run † | prod run † | dang828 |
| `amts` | | | | | | |
| `note1` | 2026-08-17 | ≥ `762cd9f0` | soak ‡ | soak ‡ | soak ‡ | dang828 |
| `electrode-demo` | | | n/a — no hte action server | | | |

B5 is already on `unstable`; this table is the record of hardware confirmation
accumulating behind it. **B7 (the deletion) should not start until it is
full** — that is the phase which removes the engine these rows are evidence
against. B6 (the private deployments) is independent and can proceed.

### `uvis4`, 2026-08-17 — signed off on a production run († )

**† The three gate columns record what the sign-off actually rests on, which is
a full production sequence rather than the three scripted gates.** A complete
`UVIS_GAIA_preset` ran on `uvis4_hex` with no errors: the station's nine
B5-changed servers took a real plate end to end on the native `ActionHost`,
through CAM, IO, MOTOR, PAL, PDU, SAMPLE, SPEC_R, SYNC and ORCH. Signed off by
the station owner on that basis.

Worth knowing what that does and does not cover, for whoever reads this table
before B7. A production run exercises the composed system harder than any of the
three gates — it is real hardware, real samples, real artifacts. What it does
not do is compare this build's routes and outputs against the pre-migration
reference (the golden diff), or exercise the abort path (the e-stop drill). A
regression that only shows up in a *difference* from legacy, or only under
abort, would not have been caught here. If either becomes a concern later, this
row is the place to revisit.

Two defects were found and fixed during this session at this station, which is
why the captured rev matters:

- `118660ee` — `sync_yml` passed the record-**relative** path to `read_hlo`,
  which needs the absolute one. The read failed, and the `except` arm then
  uploaded `{"meta": {}, "data": {}}` and recorded the file in `files_s3` as a
  success. Every hlo written between `20cd5b0c` and `118660ee` was therefore
  marked synced while its data never left the station. Confirmed fixed here:
  zero `Failed to read hlo file` in SYNC's log across the completed sequence,
  and with the empty-payload fallback removed a read failure can no longer be
  recorded as a sync at all.
- The first, aborted attempt was caught during calibration, before any sample
  was measured, and that run's records were discarded rather than repaired.

### `note1`, 2026-08-17 — signed off on a continuous soak (‡)

**‡ `note1` ran continuously from 2026-08-15 through 2026-08-17** — batch
conversion, `SYNC` and `ANA` — across the whole deduplication campaign. It
carries `SYNC` and `ORCH`, and `SYNC` is the highest-blast-radius module B5
touched. Days of unattended operation against a live share is a soak, and a
soak catches a class of fault a scripted gate cannot: the slow leak, the
sidecar written under one root and read under another, the queue that only
saturates after thousands of items. Signed off by the station owner on that
basis.

Three defects surfaced here in that window. Recorded because a soak's value is
precisely what it finds, and because two of the three were *not* deduplication
artifacts — they were framework defects that the campaign merely provided the
volume to expose:

- `20c5cb5d` — `.prg` sidecars recorded **absolute** file paths, so relocating
  the run trees under a new root stranded every record written before the move.
  `SYNC` raised `ValueError: ... is not in the subpath of ...` on startup and
  the records never synced. Now recorded relative and re-anchored on read.
- `118660ee` — the fix above passed the record-relative path to `read_hlo`,
  which needs the absolute one; the `except` arm then uploaded an empty
  envelope and marked the file synced. Silent data loss, caught at `uvis4` but
  present anywhere `SYNC` ran in that window, `note1` included.
- `762cd9f0` — `ANA`'s startup journal sweep re-enqueued every pending entry
  unbounded. With 8,802 entries accumulated it queued thousands of analyses
  into a just-started server and `ANA` became unreachable. Now swept in bounded
  slices.

What a soak does not do is compare against the pre-migration reference or
exercise the abort path. As with `uvis4`, a regression visible only as a
*difference* from legacy, or only under e-stop, would not have surfaced here.

`uvis4` and `note1` are signed off. Two of eleven.
