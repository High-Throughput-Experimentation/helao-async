# Wave 5 — hte per-station hardware bring-up & cut-over runbook

Concretizes §5 of `docs/superpowers/specs/2026-06-24-framework-hte-production-migration-plan.md`.
Wave 5 is the **gated** final migration step: launch each hte station on the
framework-wired config against **real hardware**, run the smoke checklist, then
cut the station over. One station at a time, bake-in between, explicit go/no-go
(**Gate C**) per station.

All 21 hte configs are already framework-migrated (Wave 4): generic hosts (ORCH,
OPERATOR, VIS, LIVE) carry `deployment: framework`; action servers stay on the
import-swapped `helao.deploy.hte.servers.action.*` modules. The framework
orchestrator is live-proven on the `test` deployment (real RPC/HTTP dispatch,
real `/ws_status` ingestion, FINISH_EXPERIMENT/SEQUENCE, natural-completion stop).
Each hte station still needs a real launch — that is this runbook.

**Rollback is always a config flip:** legacy `helao/core` is untouched. Revert a
station's `deployment: framework` keys (and `orchestrator`→`async_orch2`) and
relaunch on the legacy path. See §6.

---

## 0. Pre-station (offline, do once per station, from any machine)

Run the static preflight validator. It mirrors the launcher's config validation
and module/factory resolution **without** starting servers or touching hardware:

```
python helao/deploy/hte/tests/wave5_preflight.py helao/deploy/hte/configs/<station>.yml
```

- `[ OK ]` — module resolves + imports + exposes the right factory here.
- `[DEFR]` (WINDOWS-DEFERRED) — module needs a Windows/hardware dep
  (gclib, comtypes, nidaqmx, minimalmodbus, pyAndorSDK3); **must** be re-checked
  ON the station (step 2 below).
- `[RMT ]` — action server runs on a remote host; import-check it on that host.
- `[FAIL]` — real config/resolution error; fix before launching.

Use the **full config path** (not a bare prefix): the bare-prefix glob collides
for `icpm1` (a private deployment also ships `icpm1.yml`).

---

## 1. Station inventory & suggested cut-over order

> **Actual cut-over order (operator-directed, 2026-07-01):**
> `power_supply_test` (canary, done) → `eche10` → `clad` → one private-deployment
> station. This diverges from the risk-ordered plan below: `eche10` and `clad`
> are order-5 motion+pstat rigs pulled forward because the lower-risk stations
> (`icpm1` etc.) are not currently accessible. Extra care on the estop smoke
> (§4.5) since these are the framework orch's first live motion+pstat + estop
> tests. `clad` shares host `hte-adss-03` with `adss3` — never run both at once.
> Private-deployment configs get the same generic-host cut-over as the hte
> configs (ORCH `orchestrator`+`deployment: framework`; OPERATOR/VIS/data_browser
> `deployment: framework`) before they will launch on the framework stack.

Order low-risk → high-risk so the framework orch is shaken out on simple stations
before estop-critical motion+pstat rigs. Hardware column lists estop-/safety-
relevant instruments.

| Order | Station | Action host | Safety-critical hardware |
|------:|---------|-------------|--------------------------|
| canary | `power_supply_test` | local | none (USB power supply) |
| 1 | `icpm1` | hte-icpm-01 | none (PAL/DB/analysis) |
| 1 | `xrfs1` | hte-xrfs-01 | none (PAL/DB/analysis) |
| 2 | `ccsi2` | hte-ccsi-02 | NI-DAQ |
| 2 | `ecms2` | hte-ecms-02 | NI-DAQ |
| 2 | `partialccsi1` | hte-ccsi-01 | NI-DAQ |
| 3 | `eche4` | hte-eche-04 | BioLogic pstat |
| 3 | `eche5` | hte-eche-05 | Gamry pstat |
| 4 | `ccsi1` | hte-ccsi-01 | Galil IO, NI-DAQ |
| 4 | `uvis` | local | Galil motion, Galil IO |
| 4 | `gamry` | local | Gamry pstat |
| 5 | `eche6` | hte-eche-06 | Galil motion+IO, Gamry pstat |
| 5 | `eche7` | hte-eche-07 | Galil motion+IO, Gamry pstat |
| 5 | `eche8` | hte-eche-08 | Galil motion+IO, Gamry pstat |
| 5 | `eche10` | hte-eche-10 | Galil motion+IO, Gamry pstat |
| 5 | `adss` | hte-adss-01 | Galil motion, Gamry pstat, NI-DAQ |
| 5 | `adss3` | hte-adss-03 | Galil motion, Gamry pstat, NI-DAQ |
| 5 | `clad` | hte-adss-03 | Galil motion, Gamry pstat, NI-DAQ |
| 5 | `anec` | hte-anec-03 | Galil motion+IO, Gamry pstat, NI-DAQ |
| 5 | `ecms1` | hte-ecms-03 | Gamry pstat, NI-DAQ |
| 5 | `hispec` | hte-eche-11 | Galil motion+IO, BioLogic, Andor |

> Stations sharing a host (e.g. `adss3`/`clad` on hte-adss-03; `ccsi1`/`partialccsi1`
> on hte-ccsi-01) must not run concurrently — same host:port. Bake-in one before
> the other.

---

## 2. On-station preflight (Windows action host, before launch)

On each host that runs Windows/hardware action servers, confirm the deferred
imports actually resolve there:

```
python helao/deploy/hte/tests/wave5_preflight.py helao/deploy/hte/configs/<station>.yml
```

Expect `[DEFR]`→`[ OK ]` for gclib/comtypes/nidaqmx/etc. on the real station.
Any remaining `[FAIL]` = a missing driver dep or env problem; fix before launch.

---

## 3. Launch

From the orchestrator host, in the `helao` conda env, PYTHONPATH at repo root:

```
./helao.sh <station>            # Linux
helao.bat <station>             # Windows
# or: python launch.py <station>
```

Hotkeys: `CTRL-r` restart one server, `CTRL-x` terminate group, `CTRL-d` detach.

---

## 4. Hardware smoke checklist (Gate C evidence) — run per station

Record pass/fail + notes for each. This is the §5 checklist made concrete.
Operator UI = `http://<operator-host>:<operator-port>` (standalone_operator).

**4.1 Servers up**
- [ ] Every server in the config reaches ready/healthy. Each action server's
      `GET http://<host>:<port>/get_status` returns 200.
- [ ] No estop on startup; no repeating 404/RPC-probe errors in logs
      (`<root>/LOGS/<server>/`).

**4.2 Driver round-trip (per instrument)**
- [ ] `connect` / `get_status` / `stop` / `reset` / `disconnect` each succeed
      against the real instrument (via the server's endpoints or operator).

**4.3 Orchestrator drives a real sequence end-to-end**
- [ ] Operator: pick a representative **non-destructive** sequence from the
      station's `sequence_libraries`, enqueue, `Start`.
- [ ] Dispatch → action runs **on hardware** → HLO data written under
      `<root>/RUNS_ACTIVE/...` → on finish moves to `RUNS_FINISHED`/synced.
- [ ] Operator shows experiment **and** sequence → `finished` with finish
      timestamps (not stuck `active` — the 6b8931ce parity fix); queued items
      show non-blank uuids.
- [ ] Action history table populates (server/name/status/timestamps).
- [ ] At drain, orchestrator returns to `stopped`/idle ("Orch has finished"),
      not stuck `running` (the complete_idle fix).
- [ ] Compare data/meta vs a known-good legacy run of the same sequence
      (golden-master / eyeball key HLO columns + .act/.exp/.seq meta).

**4.4 Operator UI parity**
- [ ] Renders promptly; queue ops (append, clear, move) work.
- [ ] Dropdown → parameter form populates correctly.
- [ ] Status WS updates live during the run.

**4.5 Estop (safety-critical — required on any station with motion/pstat)**
- [ ] Operator estop → all servers enter estop; motion halts; pstat output off.
- [ ] Recovery: clear estop / reset brings servers back to ready.

**4.6 Per-instrument (where present)**
- [ ] Galil: a bounded motion move reaches target; IO toggles read/write.
- [ ] Gamry/BioLogic: a short pstat technique (e.g. OCV or CV) produces
      expected data shape.
- [ ] Andor/spectrometer: an acquisition returns a spectrum.
- [ ] NI-DAQ / MFC / syringe / PAL: representative read/actuate succeeds.

**4.7 Parallel-run (optional, where the station can run both)**
- [ ] Run a non-destructive sequence on framework + legacy, diff outputs.

---

## 5. Gate C sign-off (record per station)

```
Station:            <station>.yml
Date / operator:    ____________________
Framework commit:   ____________________  (git rev-parse HEAD)
Preflight:          PASS / FAIL  (offline + on-station)
Smoke 4.1–4.6:      PASS / FAIL  (attach notes)
Parallel-run:       PASS / N-A
Data vs legacy:     MATCH / DIFF (notes)
GO / NO-GO:         ____________________
Bake-in until:      ____________________  (before next station)
```

Do not start the next station until the current one's bake-in passes.

---

## 6. Rollback (instant, per station)

1. In `helao/deploy/hte/configs/<station>.yml`, revert the generic-host keys:
   - ORCH: `fast: orchestrator` → `fast: async_orch2`; remove `deployment: framework`.
   - OPERATOR / VIS / LIVE: remove `deployment: framework`.
2. Relaunch the station. Legacy `helao/core` is intact, so this is a pure config
   flip + relaunch. No code revert needed.
3. File what failed (logs + checklist notes) before re-attempting.

---

## 7. Notes / known gotchas

- Action servers are **not** `deployment: framework` — they resolve to the
  import-swapped `helao.deploy.hte.servers.action.*` (Wave 2). Only generic
  hosts flip.
- `dbpack_server` still uses the **legacy** HelaoSyncer seam by design until DB
  bring-up, so the framework S3 path can be verified against real S3. Expect
  legacy sync imports on DB hosts; this is intentional (not a Wave-5 blocker).
- Bare-prefix `read_config` collides for `icpm1` (private `icpm1.yml` exists).
  Always launch/validate hte configs by full path or ensure the hte prefix wins.
- Per-server `ORCH.log` only captures `ORCH::`-named logs; framework module
  loggers (orch_api, subscriber) write to per-module files + terminal — grep the
  right file when debugging.
- **Gate D** (decommission legacy `helao/core`) happens only after the LAST
  station is migrated + baked-in — out of scope here.
```
