# HELAO-async — CARDS Design Audit

> Audited against the **CARDS** design framework (Software Design Mastery):
> **C**larity · **A**lignment · **R**esilience · **D**omain Integrity · **S**eparation.
> CARDS are design *forces*, not rules — every finding is a trade-off, and the goal
> is balance, not maxing one force. Score scale: **strong / moderate / weak**.

Date: 2026-07-10 · Branch: `unstable`

---

## Part 1 — Framework core (`helao/core`, `helao/helpers`)

Scope: framework only; `hte`/`test` used as reference. Private deployments audited separately in Part 2.

### Scores + weakest-card ranking

| Rank | CARD | Verdict | Root driver |
|------|------|---------|-------------|
| **1 (weakest)** | **Separation** | **weak where it counts** | god-classes fuse networking + persistence + state-machine + broadcast |
| **1 (tie)** | **Clarity** | **weak → moderate** | 200–315-line multi-concern methods; control-coupling flag args |
| 3 | **Resilience** | moderate | run-dir + status magic strings leak across ~17 files |
| 3 | **Domain Integrity** | moderate | lifecycle = unguarded `List[HloStatus]`; all-`Optional` models |
| 3 | **Alignment** | moderate | global `CONFIG` singleton; core hard-codes deploy layout |

**Weakest CARD = Separation, tied with Clarity** (same root cause — they fail together).

### Core finding: a bifurcated codebase

HELAO-async is effectively two codebases in one repo:

- **New/framework code — genuinely strong.** `helao/core/drivers/helao_driver.py` (ABC + `DriverResponse` + `DriverPoller`, 231 lines) is textbook dependency inversion. `helpers/executor.py` = composable strategy hooks. `GamryDriver`/`GamryPoller` + `gamry_server2.py` prove the abstraction: thin executors wrap the driver, FastAPI endpoints are thin adapters. Domain models (`core/models/*`) are pydantic-pure, zero infra imports, enum-disciplined.
- **Load-bearing legacy core — weak.** The runtime that actually runs experiments is god-classes. Every AI-assisted or hand edit lands here, and CARDS explicitly warns that weak design + local edits → architectural erosion.

### Per-card evidence

#### Separation — **weak where it counts** (weakest)
- `Orch` god-class — `orch.py:80-2625`, **~2545 lines, ~70 methods**. Tangles queue CRUD + run state-machine (`loop_task_dispatch_*`, `dispatch_loop_task`) + network subscription (`subscribe_all`, `ping_action_servers`) + WS broadcast (`ws_globstat`, `globstat_broadcast_task`) + estop policy + persistence (`export_queues`/`import_queues`).
- `Base` `base.py:108-1142` + `Active` `base.py:1143-2508`. `Base.__init__` (`base.py:120-207`) parses config + computes orch topology + resolves dirs + builds 3 pub/sub queues + loads NTP offset from disk + dynamically imports plugins.
- Module-global mutable state: `config_loader.py:143` (`global CONFIG`), `dispatcher.py:46` (`_RPC_CLIENTS` pools).

#### Clarity — **weak → moderate**
- Worst function: `Orch.loop_task_dispatch_action` `orch.py:1012-1327` (**~315 lines**).
- `Active._finish` `base.py:2054-2275` (~221 lines).
- Name ambiguity: three "dispatch" methods = three meanings.
- Flag args (control coupling): `estop_actions(switch: bool)` `orch.py:1579`; `load_global_config(..., set_global=False)` `config_loader.py:129` (flag flips a pure read into a global mutation); `get_experiment(last=False)` `orch.py:2106`.

#### Resilience — **moderate**
- `RUNS_ACTIVE/FINISHED/SYNCED/DIAG/NOSYNC` never centralized — raw literals + `str.replace()` across **~17 files, 80+ sites** (`base.py` ~10×, `sync_driver.py` ~40×).
- `HelaoPath` path-state class copy-pasted between `sync_driver.py` and `dbpack_driver.py` (4× duplicated `valid_statuses` tuple).
- Status enum bypassed: dict payloads hardcode `"status":"active"` (`orch.py:677,693,863,879,...`), forcing `micro_orch.py:68` to defensively check both enum and string.
- **Strong here:** action-server factory + dynamic import (adding a server = one config entry + `makeApp` file, no central registry); central dispatcher (`helpers/dispatcher.py`); auto endpoint registration (`base_api.py:380`).

#### Domain Integrity — **moderate**
- Lifecycle modeled as `List[HloStatus]` (`action.py:126`, `experiment.py:112`, `sequence.py:101`) — nothing prevents `[active, finished, errored]` simultaneously; no state machine, transitions via scattered `.append()`.
- Every domain model all-`Optional` — `Action()` builds with no uuid/name; identity assigned lazily by `init_act` (`premodels.py:335`).
- Sample `Union` (`action.py:142`) not discriminated; untyped `SampleModel` fallback catches anything.
- `GlobalStatusModel` state split across 3 free enums that can drift (`server.py:176-180`); `finish_experiment` clears ALL finished actions (`server.py:350`, acknowledged TODO).
- World config = untyped dict, deep-navigated (`world_cfg["servers"][key]["host"]` `base.py:148`).
- **Strong here:** pervasive enums (`HloStatus`, `OrchStatus`, `SampleType`, ...); sample subtypes pin discriminator via `Literal`; `SolidSample` root_validator enforces derived label.

#### Alignment — **moderate** (strongest of the five)
- **Wins:** pure domain models (no infra imports); `HelaoDriver` ABC; driver injected, not imported (`base.py:1160`); ZMQ mostly behind `rpc/zmq_rpc.py`.
- **Drags:** `CONFIG` mutable singleton seeded at import, no injection boundary (acknowledged TODO `base.py:119`); core hard-codes `helao.deploy.{deployment}...` paths (`vis_subscriber.py:121`, `analysis_driver.py:116`, `base.py:1113`); `zmq` leaks past RPC abstraction (`dispatcher.py:25`, `micro_orch.py:40`).

### Genuinely strong spots (keep as reference patterns)
- `helao/core/drivers/helao_driver.py` — ABC + `DriverResponse` + `DriverPoller`.
- `helao/helpers/executor.py` — injectable `_pre_exec/_exec/_poll/_post_exec` hooks.
- `helao/deploy/hte/drivers/pstat/gamry/driver.py` — proves the ABC works (only wart: 188-line `setup`).
- `helao/core/servers/base_api.py` — decomposed into small free functions instead of a fat class.
- `config_loader.py:150-192` — `HelaoConfig`/`ServerConfig` pydantic models (exist but under-used).

### Highest-leverage fixes (CARDS-ordered)
1. **Split `Orch`** (Separation + Clarity) — extract state-machine / network / broadcast / persistence collaborators. Biggest win; mirrors the `base_api.py` decomposition already in-tree.
2. **Model lifecycle as a guarded state, not a list** (Domain Integrity) — kills contradictory-state + `finish_experiment` clear-all bug classes.
3. **Centralize run-state dir names in one enum** (Resilience) — collapses ~80 magic-string sites; delete duplicated `HelaoPath`.
4. **Typed config model + inject it** (Alignment) — thread existing `HelaoConfig` through instead of global Munch; retire `global CONFIG`.
5. **Migrate `PAL`/`Archive`/`Galil` onto `HelaoDriver` ABC** (Separation) — contract already proven by Gamry.

**Bottom line:** strong new architecture, weak legacy spine. No red card, but Separation is weakest, and refactoring `Orch` returns the most on every axis at once.

---

## Part 2 — Deployments

Scope: deploy-specific code only (drivers / servers / experiments / sequences / processors / specifications). `helao/core` not re-audited here. `deploy/Deployment-D` and `deploy/Deployment-B/notes` excluded per request. **No PII / hostnames / credentials from configs were read or reproduced — structure only.** Instrument `*.yml` configs were treated as sensitive and not opened.

### Cross-deployment scoreboard

| Deployment | Clarity | Alignment | Resilience | Domain Integrity | Separation | Character |
|-----------|:-------:|:---------:|:----------:|:----------------:|:----------:|-----------|
| **hte** (production) | weak | mod/weak | weak | weak | weak | 7 ABC drivers vs ~15 legacy god-classes; huge campaign files |
| **Deployment-A** | weak | moderate | weak | weak | weak | mid-migration; `ThorlabsMotor` god-class; 2/9 drivers on ABC |
| **Deployment-B** | weak | weak | weak | weak | moderate | god-weight in exp/seq scripts; 0/4 drivers on ABC |
| **Deployment-C** (analysis) | moderate | **strong** | moderate | weak | **strong** | no instrument drivers; analysis `BaseAnalysis` subclasses; stringly-typed numerics |
| **test** (sims) | moderate | mod/strong* | weak | weak | moderate | ABC-skip is *deliberate* (bare sim helpers); Executor contract honored |

\* `test` Alignment is sound in context: sim helpers intentionally skip `HelaoDriver`, but the load-bearing `Executor` contract IS honored (per project design decision — see memory).

### The master variable: `HelaoDriver` ABC migration

One factor explains almost every score. The cleanest signal is the **driver constructor**:
- **`config: dict` seam + typed `DriverResponse`** → aligned, separated, clear. (New drivers.)
- **`action_serv: Base` back-reference + raw `dict` returns** → inverted dependency, god-class, stringly-typed. (Legacy drivers.)

Migration counts:

| Deployment | On `HelaoDriver` ABC | Legacy `action_serv: Base` |
|-----------|---------------------|----------------------------|
| hte | 7 (gamry, biologic, kinesis, andor, power_supply, netbooter, leancat) | ~15 (PAL, Archive, DBPack, Calc, alicat, galil ×2, nidaqmx, SM303, mecom, legato, simdos, 3× sensor) |
| Deployment-A | 2 (stenner, advantech — exemplary) | 7 (ThorlabsMotor, USB5830, OerAL, MuxCom, Calc, 2× stenner variants) |
| Deployment-B | 0 | 4 (actuator, robotarm, opcua/leancat, stub) — small, not god-classes |
| test | n/a (deliberate bare sims) | 5 sims (GPSim, CPSim, ArchiveSim, MotionSim, WsSim) |
| Deployment-C | n/a (analysis) | uses core `BaseAnalysis` ABC correctly |

The four largest, most business-heavy hte drivers (PAL, Archive, alicat, galil_motion) are all still legacy. ABC adoption correlates directly with smaller, better-separated code.

### Per-deployment worst offenders

**hte (production — highest stakes):**
- `drivers/robot/pal_driver.py:234` — `PAL` god-class ~2870 lines; `_sendcommand_main:474` ~310 lines; 18 raw-dict returns.
- `drivers/data/archive_driver.py:79` — `Archive` ~2370 lines; `custom_add_liquid:1496` ~396 lines, `custom_add_gas:1892` ~381 lines; 25 raw-dict returns.
- `drivers/motion/galil_motion_driver.py:61` — `Galil`; `_motor_move` ~385 lines.
- `drivers/data/calc_driver.py:104` — 35 sites of 3+-level deep dict navigation (`d["actd"]["action_server"]["server_name"]`).
- `experiments/ADSS_exp.py` (3461 lines, 257 `apm.add`) + `sequences/ADSS_seq.py` (5651 lines) — action endpoints as magic strings, params as raw dicts; renaming an endpoint means hand-editing string literals across campaign files.
- `specifications/` — `last2weeks.py` and `bimonthly.py` byte-identical; `last3months.py` differs by one number. Should be one parameterized unit.
- **Reference-quality:** `drivers/pstat/gamry/`, `drivers/pstat/biologic/`, `drivers/motion/kinesis_driver.py` — ABC + `config` seam + `DriverPoller` split + enum/technique modules.

**Deployment-A (mid-migration):**
- `drivers/thorlabs_kinesis.py:460` — `ThorlabsMotor` god-class ~1100 lines mixing I/O + alignment logic + Bokeh UI + matrix persistence; `_motor_move:800` ~397 lines.
- `sequences/SDC_seq.py` — three near-duplicate ~430–516-line sequence variants (`:3487`, `:3972`, `:4488`).
- Duplicated driver families: stenner ×3, advantech ×2; parallel v1/v2 servers.
- Type bug: `SDC_seq.py:2252` `stop_ce_pump: bool = "True"` (string default on a bool).
- **Reference-quality:** `drivers/stenner/driver.py`, `drivers/advantech/driver.py` (ABC + poller + codec/states split) — the intended target.

**Deployment-B (god-weight in scripts, not drivers):**
- `experiments/AMTS_exp.py` — 2897 LOC; `configure_leancat:691` ~291 lines w/ ~35 flat params; near-duplicate `configure_leancat_for_ADVENT_MEA:983` ~239 lines.
- `SampleModel` construction block copy-pasted ~24–29× (magic strings `"MEA"`, `gethostname().lower()`).
- `sequences/AMTS_seq.py` — 1429 LOC; `AMTS_run_echem:30` ~287 lines + two structural clones.
- `servers/action/test_station_server.py:27` — `test_station_endpoints` ~410 lines.
- **Strong:** drivers small + focused; `Executor` subclassing honored; core `ErrorCodes` enum used in returns.

**Deployment-C (analysis / data-conversion — no instruments):**
- `drivers/data/analyses/uvis_local.py:444` — `calc_abs()` ~210 lines; entire dataflow built from f-string dict keys (`f"{k}_dsat_dnse"`) instead of typed structures.
- `scripts/common/helao_nbio.py` — 1118-line procedural grab-bag; duplicated `extract_parts`/`_old`/`_json`, S3-vs-local pairs, flag dispatcher `get_info(..., local=True)`.
- Four near-identical `/run_<instrument>` handlers hardcoding `"bruker"/"edax"/"xafs"/"icpms"`.
- **Strong (best deployment overall):** `batch_convert_server.py` clean single-purpose classes; `batch_converter.py` is the pydantic/typed-model exemplar; near-zero deep dict navigation.

**test (sims — ABC-skip deliberate):**
- `drivers/data/gpsim_driver.py:76` — `GPSim.__init__` ~84-line god-constructor that also launches a background asyncio task; `fit_model:322` ~120 lines w/ 8 magic-string parallel lists + dead `return data`.
- `check_condition:485` — stop condition as raw string dispatched through string-keyed dict; KeyErrors on invalid value (should be enum).
- Duplicated data-file path literal across `gpsim_driver.py:85` and `cpsim_driver.py:51`; per-plate state re-init in 3 sites.
- **Strong:** `*Exec` classes honor the core `Executor` contract; consistent `HloStatus`/`ErrorCodes` enums.

### Deployment-level fixes (CARDS-ordered)

1. **Finish the `HelaoDriver` ABC migration** (Alignment + Separation + Domain, all deployments). Priority order by risk × size: **hte PAL, hte Archive, Deployment-A ThorlabsMotor, hte galil_motion, hte alicat.** Flip `action_serv: Base` → `config: dict` + typed `DriverResponse`. Gamry/biologic/stenner/advantech are proven templates.
2. **Kill campaign-file duplication** (Resilience). hte `specifications/` → one parameterized class; Deployment-A triple sequences and Deployment-B `configure_leancat*` → parameterize; extract the repeated `SampleModel` block (Deployment-B ~24–29×) into a factory.
3. **Type the param/return layer** (Domain Integrity). Replace f-string-dict-key dataflows (Deployment-C `calc_abs`) and string-keyed dispatch (test `check_condition`) with enums / typed models. Push existing driver-internal enums up to the experiment layer.
4. **De-god the analysis grab-bag** (Separation). Deployment-C `helao_nbio.py` → split I/O vs parse vs DB; delete `_old` dead variants.

### Deployment bottom line

The **same fault line runs through every deployment**: a small, modern, ABC-conformant core-facing layer sitting next to large legacy god-classes and copy-pasted campaign scripts. Production **hte** has the most legacy mass and the highest stakes. **Deployment-C** is the healthiest (strong Alignment + Separation). **test**'s ABC-skip is a correct deliberate boundary, not a defect. Across the board, **finishing the driver-ABC migration is the single highest-leverage move** — it simultaneously lifts Alignment, Separation, Clarity, and Domain Integrity, mirroring the framework-core finding that the weakness is the un-refactored legacy spine, not the design vocabulary.

---

## Part 3 — Whole-system synthesis (does the deployment audit change Part 1?)

**Yes — materially.** Auditing the deployments in isolation is misleading, because the deployment weaknesses are not local: they are the **downstream fan-out of three core (Part 1) design decisions**. Read as a whole, two Part-1 verdicts should be re-weighted, and the top fix is confirmed.

### Core weaknesses propagate fractally into every deployment

| Core decision (Part 1) | Its blast radius across deployments (Part 2) |
|---|---|
| `Base`/`Active` invite a driver to hold a back-reference (`action_serv: Base`) rather than a `config` seam | Every legacy driver in **hte** (~15), **Deployment-A** (7), **Deployment-B** (4) inherits the god-class + inverted-dependency shape. The core affordance *is* the deployment Separation/Alignment weakness. |
| Domain params carried as untyped `dict` (`action_params`, `to_global_params`, `SampleModel.etc`) + all-`Optional` models + non-discriminated sample `Union` | **Deployment-C** f-string-dict-key dataflows (`calc_abs`), **Deployment-B** `SampleModel` block copy-pasted ~24–29×, **hte** 257 magic-string `apm.add` params, **test** string-keyed stop-condition dispatch. The core's untyped param contract *forces* stringly-typed deployment code. |
| `RUNS_*` names + status strings as raw literals, no single source of truth | Re-appears as deployment-level magic strings + duplicated `HelaoPath` (**hte** `dbpack_driver`) + copy-pasted campaign specs. Same "no SoT" class, one layer down. |

The lesson is exactly the CARDS "AI amplifies weak design" thesis at repo scale: a weak core affordance doesn't stay contained — every deployment author (human or AI) reproduces it, so the core's moderate-looking scores under-represent their true cost.

### Re-weighted whole-system scores

| CARD | Part 1 (core, isolated) | **Whole-system (core + all deployments)** | Why it moves |
|------|:-----------------------:|:-----------------------------------------:|--------------|
| Separation | weak (weakest) | **weak — confirmed weakest** | god-class pattern is core-seeded and deployment-multiplied |
| Clarity | weak → moderate | **weak** | mega-methods in core *and* 2900-line experiment scripts in deployments |
| **Domain Integrity** | moderate | **weak (re-weighted down)** | "moderate in the models" but the untyped-param contract makes it *weak everywhere it's used* — blast radius is every deployment |
| Resilience | moderate | **moderate → weak** | core magic strings + deployment campaign-file duplication compound |
| Alignment | moderate | **moderate** | unchanged: driver ABC + pure models still hold the line; the `action_serv` coupling is the one that spreads |

**Net:** the whole-system weakest card is still **Separation**, but **Domain Integrity is the biggest re-rating** — it looks moderate when you audit only `core/models`, but its untyped-dict param contract is the root cause of weak Domain Integrity in all five deployments. Fixing it at the core (typed action/experiment params) is higher-leverage than any single deployment fix.

### Confirmed top fix, now with two-layer justification

**Finishing the `HelaoDriver` ABC migration + typing the param/lifecycle layer** is the highest-leverage work because each lifts **both** layers at once:

1. **ABC migration** (`action_serv: Base` → `config` seam) — fixes core Separation/Alignment *and* de-god-classes ~26 legacy deployment drivers. Priority: hte PAL/Archive/galil, Deployment-A ThorlabsMotor.
2. **Lifecycle as a guarded state + typed params** — fixes core Domain Integrity *and* removes the stringly-typed pressure that produces `calc_abs`, the Deployment-B SampleModel copy-paste, and hte's magic-string `apm.add`.
3. **Central run-state enum + typed config** — fixes core Resilience *and* the deployment magic-string/duplication class.

Do these at the core first; the deployments largely heal by following the corrected pattern.

---

## Appendix — P5 outcome: `Orch` decomposition (2026-07-11)

Highest-leverage fix #1 ("Split `Orch`") is **done** on `feat/cards-refactor`. The `Orch` god-class was decomposed in nine behavior-preserving stages (S0–S9), each gated by a dispatch-decision golden master (byte-identical trace) and reviewed independently.

### What changed
- `helao/core/servers/orch.py`: **2622 → ~1036 lines** (−60%). It is now a thin composition root — `__init__`/`_init_collaborators` (constructs the collaborators), `exception_handler`, `myinit`, cluster E (e-stop, intentionally retained — see below), and ~75 one-to-three-line delegators that preserve the frozen external surface (the 117 `orch_api`/operator reach-ins and bound-method registrations are unchanged).
- Eight focused, unit-testable collaborator modules extracted beside it: `orch_global_params.py` (pure fold functions), `orch_persist.py` (`QueuePersister`), `orch_monitor.py` (`ServerMonitor`), `orch_status_sync.py` (`StatusIngester`), `orch_queues.py` (`RunQueues`), `orch_unpack.py` (expansion helpers + `PLATE_API`), `orch_lifecycle.py` (`RunLifecycle`), `orch_dispatch.py` (the FSM inversion: pure `DispatchPolicy` + async `DispatchRunner` + a closed `DispatchStep` union).
- The dispatch state-machine was **inverted**: decisions (a pure, unit-tested decision table over a read-only `DispatchSnapshot`) are now separated from effects (the async runner). The previously-implicit FSM buried across 200–315-line multi-concern methods is now explicit and testable.
- Behavior preservation: the dispatch golden master is byte-identical across all nine stages; a controller-run OERSIM end-to-end run confirmed real-server behavior equal through S6 (S7/S8 rest on the byte-identical decision trace + per-stage review — the real-server e2e for those two is pending an unrelated environment fix).

### Card re-score (framework core, `helao/core`)

| CARD | Part-1 (pre-P5) | **Post-P5 (core)** | Why it moves |
|------|:---------------:|:------------------:|--------------|
| **Separation** | weak (weakest) | **moderate → strong** | the core god-class is gone: networking, persistence, status-broadcast, queue-CRUD, run-lifecycle, and the dispatch FSM are now separate single-responsibility collaborators |
| **Clarity** | weak → moderate | **moderate → strong** | no more 200–315-line multi-concern methods; the dispatch loop reads as `snapshot → policy.next_step → execute`, and the decision table is directly unit-tested |
| Domain Integrity | moderate (whole-system: weak) | **unchanged** | untyped-param/lifecycle contract is a separate fix (still the top remaining core item) |
| Resilience | moderate | **moderate (slightly up)** | behavior pinned by a golden master + 8 new unit-test modules; magic-string run-state still open |
| Alignment | moderate | **moderate** | unchanged; ABC-migration + typed-param work is the remaining lever |

**Net:** the pre-P5 weakest-and-tied cards (Separation, Clarity) — which shared the single root cause "god-classes fuse networking + persistence + state-machine + broadcast" — are materially lifted for the framework core. The remaining core levers are the ones P5 deliberately did **not** touch: **Domain Integrity** (typed params + guarded lifecycle state) and the **`HelaoDriver` ABC migration** across deployments (fix #1's deployment half, tracked separately under P4). Whole-system Separation is still gated by the ~26 legacy deployment god-classes, so the deployment-level scoreboard is unchanged until those migrate.

### Deliberately deferred to P5b
Cluster E (e-stop: `estop_loop`/`estop_actions`/`estop_finish_active`) stays in `orch.py` — freshly redesigned + production-verified, extracted only after one production soak of the inverted dispatch shape. Also P5b: the `supplement_error_action` `actual_order`/`action_actual_order` field-name bug (fixed 2026-07-11), the `/latest_*_uuids` `last_50_*_uuids` AttributeError (fixed 2026-07-11), `dilute`/`autodilute`, and `Active._finish` (now folded into P6-S8).

---

## Appendix — P6 (planned): `Base` / `Active` decomposition (`base.py`)

Fix #1 ("split the god-classes") is only half done: P5 split `Orch`; `base.py` holds the **other** core god-class pair and is the same tier. Plan drafted in `CARDS_REFACTOR_P6.md` (not started; prereq-gated).

### The target
`base.py` = **2557 lines**, two god-classes:
- **`Base`** (~1054 lines, 47 methods) — parent of every action server; fuses endpoint setup + action containment + **status WS/broadcast** + **live buffer** + status tasks + action-queue dispatch + **file/meta output** + executor mgmt.
- **`Active`** (~1362 lines, 41 methods — *larger than `Base`*) — one per action, every deployment; fuses executor orchestration + **data streaming** + **file I/O** + sample tracking + the **finish/split lifecycle**.

This is exactly the audit's named root cause ("god-classes fuse networking + persistence + state-machine + broadcast"), and `base.py` is the #2 hot-path file in the repo.

### Why it's a separate, gated phase (not a P5b follow-on)
- **Blast radius = the whole fleet.** `Orch` touches only orchestrators; `Base` is the parent of every action server and `Active` is created for every action. Reach-in surface: **`active.*` in 91 files / 26 members** (`active.action` 909×, `active.finish` 265×, `active.enqueue_data_dflt` 165×), **`self.base.*` in 25 files / 48 members** — ~5× wider than P5's 117 (and spread across every deployment, not concentrated in one adapter).
- **No behavior harness exists** — one must be built first (P6-S0: an `Active` output golden master over hlo-file/meta bytes + status wire packets + finish/split transitions, plus the OERSIM action-server e2e). `Active`'s async data-enqueue→file→finish chain is harder to pin than P5's decision trace.
- **Must wait for the P5 production soak** — P6 stacks on P5's collaborator idiom; prove it in prod first.

### Card impact (projected)
Completing P6 would move core **Separation** and **Clarity** to strong across *both* core god-classes (P5 did the orchestrator half). Domain Integrity / Alignment unchanged (separate levers). Deployment-level scoreboard still gated on the driver-ABC migration. Recommended sequence: P5 merge → P5 soak → P6-S0 harness → P6 staged S1→S8 (cleanest first: `LiveBuffer`/`StatusBroadcaster`; hardest last: `Active` `DataStreamer` then `ActionFinalizer`).
