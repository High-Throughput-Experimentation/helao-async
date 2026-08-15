# B5 station gate runbook

**Branch:** `feat/legacy-separation-b5-hte`
**Spec:** `docs/superpowers/specs/2026-08-15-B5-hte-port-design.md` §5
**Status:** every Linux gate is green; **no station has run this yet.**

B5 ported all 23 hte action modules, the orchestrator entrypoint, and three
driver modules from `BaseAPI`/`OrchAPI`/`Base`/`Active` to the native
`ActionHost`/`OrchHost`. Nothing above this document proves it on hardware, and
seven stations have to. This is the procedure for each.

---

## Read this first

**Launching the non-`_hex` config is not a rollback.** `adss3.yml` and
`adss3_hex.py` both reach the same `makeApp`, and that function now returns an
`ActionHost` for every action server. The `_hex` variant's write graft is a
no-op on a native host and the plain `.yml` never had a graft. So both configs
serve the native host on this branch. **Rollback is `git checkout unstable`,
or `freeze/pre-legacy-removal_2608` if `unstable` has moved.**

**Capture the golden BEFORE checking the branch out.** Once a module builds a
native host there is no legacy build of it left on this working copy to capture
from. B1 learned this the expensive way.

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

**Order: `ccsi2`, `eche10`, `anec`, `adss3`, `clad`, `ecms1`, `hispec`.**

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

### 1. Capture the pre-change golden — before touching the branch

```
python -m harness.capture --scenario GM-1 \
    --root <the station's configured root> \
    --out <goldens>/<station>/pre \
    --config-prefix <station>_hex
```

Readiness probes must POST. Every HELAO private route is a POST, so a GET to
`/loaded_modules` returns 405, which a naive probe reports as "server down".

### 2. Switch to the branch

```
git status --short --branch          # confirm a clean tree first
git checkout feat/legacy-separation-b5-hte
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

### 6. Golden diff

```
python -m harness.capture --scenario GM-1 \
    --root <the station's configured root> \
    --out <goldens>/<station>/post \
    --config-prefix <station>_hex
python -m harness.parity --golden <goldens>/<station>/pre \
                         --candidate <goldens>/<station>/post
```

Expect **0 diffs**. Capture on a fresh root, as the rig requires.

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
git checkout unstable
```

Record what failed, on which server, with the log excerpt — not a summary.

---

## Sign-off

| station | date | golden diff | smoke | e-stop | by |
|---|---|---|---|---|---|
| `ccsi2` | | | | | |
| `eche10` | | | | | |
| `anec` | | | | | |
| `adss3` | | | | | |
| `clad` | | | | | |
| `ecms1` | | | | | |
| `hispec` | | | | | |

B5 merges to `unstable` when all seven rows are complete. B6 (the private
deployments) and B7 (the deletion) are gated behind that merge.
