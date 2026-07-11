# CARDS Refactor — P4 Weaning Spec: decoupling legacy drivers from `Base`

> Deployment aliasing: this doc lives in the **public** parent repo, so private deployments
> are referred to as **Deployment-A/B/C/D**. Public deployments keep their names (`hte`, `test`).
> The alias key is held privately, out of the repo. Private drivers are cited by bare file
> name + line only, never by path. No config YAML content is reproduced here.

**Status:** DESIGN SPEC (companion to `CARDS_REFACTOR_P4.md`; no code yet). P4's wave plan
says *which* drivers move *when*; this spec says **how to remove each kind of `self.base`
coupling** so a legacy god-class driver can become a `config: dict` + `HelaoDriver` driver.
All line references verified on branch `feat/cards-refactor` (2026-07-11).

---

## 0. The problem, in one paragraph

The construction seam (`helao/core/servers/base_api.py:661-676`) hands a migrated driver
**only** `config=self.server_params`; it never sees `self.base` again. Everything a legacy
driver reached through `self.base` — params, world config, logging, run-tree paths,
orchestrator wiring, the live buffer, `Active` objects, estop state, the sample DB, and the
running event loop — must therefore move to one of exactly three homes: **(a) the `config`
dict** (static wiring), **(b) an `Executor` in the action server** (per-action context), or
**(c) a `DriverPoller`** (always-on data). This spec enumerates the eight coupling kinds,
fixes one canonical target per kind, and fingerprints every remaining coupled driver.

The trivial case is already proven: `helao/deploy/hte/drivers/data/HTEdata_legacy.py:127-136`
(signature flip + no-op lifecycle, zero coupling). The hard cases are drivers like `hte`
`calc_driver.py` (orch dispatch + `Active` params + run-tree reads) and `sprintir_driver.py`
(serial open in `__init__`, two `create_task` loops, driver-created `Active`).

### Ground truth on the seam (do not re-derive)

- `base_api.py:666` — compliant path: `driver_class(config=self.server_params)`.
- `helao/helpers/server_api.py:74` — `self.server_params = self.server_cfg.get("params", {})`,
  i.e. the `config` a migrated driver receives **is the same dict** legacy drivers fetched via
  `action_serv.server_cfg.get("params", {})`.
- `helao/helpers/server_api.py:71` — `self.helao_cfg = helao_cfg if helao_cfg is not None else
  config_loader.CONFIG`, i.e. `self.base.app.helao_cfg` **is** the P1 global-config seam object.
- `helao/core/servers/base.py:146-147` (`server_cfg`/`server_params`), `:152` (`world_cfg`),
  `:170-179` (`orch_key`/`orch_host`/`orch_port`, `helaodirs`), `:274` (`print_message`).
- Poller wiring: `base_api.py:667-671` — `poller_class(driver_inst, polling_time)` +
  `poller._base_hook = self.base` → `DriverPoller._poll_sensor_loop` forwards `get_data().data`
  to `base.put_lbuf` (`helao/core/drivers/helao_driver.py:219-220`).
- Executor contract: `helao/helpers/executor.py:22-78`; reference shape
  `helao/deploy/hte/servers/action/gamry_server2.py:59` (`class GamryExec(Executor)`),
  `:99` (`self.driver = self.active.driver`), `:690` (`active.start_executor(executor)`).

---

## 1. Coupling taxonomy — canonical target per kind

Rule of thumb used throughout: **the driver may know its device and its `config` dict; the
Executor may know `active` (and through `active.base`, the server); nothing else.** Any
`self.base.X` in a driver is one of the kinds below.

### K1 — Config/params access (`self.base.server_cfg["params"]`) → the constructor's `config` dict

Because `base_api.py:666` passes `server_params` and `server_api.py:74` defines
`server_params = server_cfg.get("params", {})`, the flip is **identity-preserving**: the
migrated driver receives the exact dict it used to fetch. No config YAML changes, no value
drift.

```python
# BEFORE (calc_driver.py:104-111, sprintir_driver.py:52-60)
def __init__(self, action_serv: Base):
    self.base = action_serv
    self.config_dict = action_serv.server_cfg.get("params", {})

# AFTER (HTEdata_legacy.py:127-136 pilot shape)
def __init__(self, config: dict = {}):
    super().__init__(config=config)          # HelaoDriver stores self.config
    self.config_dict = self.config            # same dict, alias kept for low-churn diff
```

Reads like `self.config_dict.get("port")`, `("start_margin", 0)`, `("allow_no_sample", True)`
(`sprintir_driver.py:128,140`) are untouched.

### K2 — World/global config (`self.base.app.helao_cfg`) → explicit config key, falling back to the P1 seam

Drivers use world config almost exclusively for `root` (e.g. the Deployment-A active-learning
driver builds its state path as `<root>/DATABASE/AL/<plate_id>.csv`, `ml_driver.py:73-75`).
Canonical target: **an explicit driver-level config key wins; absent that, read
`helao.helpers.config_loader.CONFIG` lazily inside the method that needs it** — never at
import or construction. This is not a new global: `server_api.py:71` shows
`app.helao_cfg` *is already* `config_loader.CONFIG`, so the fallback is the same object minus
the `self.base` hop.

```python
# BEFORE (ml_driver.py:40, calc_driver.py:113)
self.world_config = self.base.app.helao_cfg          # in __init__
...
state_path = os.path.join(self.world_config["root"], "DATABASE", "AL", f"{plate_id}.csv")

# AFTER
from helao.helpers import config_loader
def _data_root(self) -> str:
    override = self.config.get("data_root")           # explicit wins (testable, no global)
    return override or config_loader.CONFIG["root"]   # P1 seam fallback (lazy)
...
state_path = os.path.join(self._data_root(), "DATABASE", "AL", f"{plate_id}.csv")
```

Rationale: keeps drivers unit-testable (`Driver(config={"data_root": tmpdir})`) without
forcing edits to every private deployment YAML on day one. **Open question OQ-1** (§5)
covers whether to later mandate the explicit key. Note: values that are *per-action* rather
than *per-process* (paths under a run tree) are **not** K2 — they are K4.

### K3 — Logging (`self.base.print_message`) → module-level `make_logger`

Repo convention (CLAUDE.md; already followed by `helao_driver.py:18` and by `hte`
`calc_driver.py:20`): one module-level `LOGGER`. `Base.print_message` (`base.py:274`) is just
a wrapper over the same logging factory, so routing/email-alert behavior is preserved.

```python
# BEFORE (ml_driver.py:113 and 6 more)
self.base.print_message("AL space has not been initialized.")
self.base.print_message("... was already acquired", warning=True)

# AFTER
from helao.helpers import helao_logging as logging
LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
LOGGER.info("AL space has not been initialized.")
LOGGER.warning("... was already acquired")
```

Mapping: bare call → `LOGGER.info`, `warning=True` → `LOGGER.warning`, `error=True` →
`LOGGER.error`. Mechanical; do it first in every migration (it shrinks the remaining
`self.base` surface and the diff noise).

### K4 — Run-output dirs (`self.base.helaodirs.save_root`) → caller-supplied absolute path; the server owns paths

`save_root` is `<root>/RUNS_ACTIVE` (`helao/helpers/helao_dirs.py:62`), i.e. *action-context*
knowledge: which run tree the current action lives in. That belongs to the action server.
Canonical target: **driver methods take an explicit directory argument; the endpoint/Executor
computes it from `active`** (which has both `base.helaodirs` and
`action.get_sequence_dir()`).

```python
# BEFORE (calc_driver.py:123-125, same pattern :165-167, :181-183)
def gather_seq_data(self, seq_reldir: str, action_name: str) -> dict:
    active_save_dir = self.base.helaodirs.save_root.__str__()
    seq_absdir = os.path.join(active_save_dir, seq_reldir)
    FM = FileMapper(seq_absdir)

# AFTER — driver is a pure function over a directory
def gather_seq_data(self, seq_absdir: str, action_name: str) -> dict:
    FM = FileMapper(seq_absdir)

# caller (endpoint or Executor._pre_exec) owns the path:
seq_absdir = os.path.join(
    str(self.active.base.helaodirs.save_root),
    self.active.action.get_sequence_dir(),
)
```

Rationale: `FileMapper` already walks ACTIVE/FINISHED/SYNCED from any anchor, so the driver
loses nothing; unit tests can point methods at a fixture tree. Drivers that use `helaodirs`
for *their own* state files (not run trees) are actually K2 — use `_data_root()`.

### K5 — Orchestrator dispatch (`self.base.orch_key/host/port` + `async_private_dispatcher`) → driver returns intent; Executor dispatches

Legacy shape: the driver itself HTTP-POSTs `insert_experiment` to the orchestrator
(`calc_driver.py:848-858` and `:918-928`; the Deployment-A active-learning driver's
`enqueue`, `ml_driver.py:324-334`). Orch topology lives on `Base` (`base.py:170-176`) —
server wiring, not device knowledge. Canonical target: **the driver computes and returns a
follow-up *request* in `DriverResponse.data`; the Executor (which owns `active`, and via
`active.base` the orch coordinates) performs the dispatch in `_post_exec`.**

```python
# BEFORE (calc_driver.py:842-860, inside the driver)
rep_exp = Experiment(experiment_name=..., experiment_params=..., **kwargs)
resp, error = await async_private_dispatcher(
    self.base.orch_key, self.base.orch_host, self.base.orch_port,
    "insert_experiment", params_dict={},
    json_dict={"idx": 0, "experiment": rep_exp.clean_dict()},
)

# AFTER — driver: decide, don't dispatch
return DriverResponse(
    response=DriverResponseType.success, status=DriverStatus.ok,
    data={
        "epoch": ..., "mean_co2_ppm": ..., "redo_purge": bool(loop_condition),
        "insert_experiment": (            # present only when a follow-up is warranted
            {"idx": 0, "experiment": rep_exp.clean_dict()} if loop_condition else None
        ),
    },
)

# AFTER — Executor._post_exec: dispatch on behalf of the driver
async def _post_exec(self) -> dict:
    req = self.result.data.pop("insert_experiment", None)
    if req:
        base = self.active.base
        resp, error = await async_private_dispatcher(
            base.orch_key, base.orch_host, base.orch_port,
            "insert_experiment", params_dict={}, json_dict=req,
        )
        LOGGER.info(f"insert_experiment response: {resp} error: {error}")
    return {"data": {}, "error": ErrorCodes.none}
```

Rationale: (a) Separation — no HTTP client inside a device driver; (b) testability — the
loop-control decision (`redo_purge`, thresholds, max_repeats) becomes assertable without a
network; (c) the enqueued-experiment observable is unchanged, so the P3 e2e harness can gate
it (§4). **Open question OQ-2**: whether loop-control should eventually be lifted out of the
action server entirely into experiment/orchestrator-side conditionals.

### K6 — Data enqueue / file writes during an action → Executor return values; live values → DriverPoller

Two sub-kinds:

- **K6a — action data (`active.enqueue_data*`, `active.write_file`).** Canonical: the driver
  returns data; the Executor's `_exec`/`_poll` return `{"data": ...}` and the framework
  streams it (this is exactly the existing `CO2MonExec._poll` shape,
  `sprintir_driver.py:489-516`). Ancillary file writes stay where they already are — in the
  endpoint/Executor (`calc_server.py:95-104` `active.write_file` does not move into the
  driver; it stays server-side and consumes the driver's returned arrays).

  ```python
  # BEFORE (sprintir_driver.py:362-368, inside the driver's recording loop)
  self.active.enqueue_data_nowait(datamodel=DataModel(
      data={self.active.action.file_conn_keys[0]: datadict}, ...))

  # AFTER (Executor; cf. CO2MonExec._poll returning {"data": live_dict, "status": ...})
  async def _poll(self) -> dict:
      resp = self.driver.get_data()           # or read poller live_dict via active.base.get_lbuf
      return {"error": ErrorCodes.none, "status": status, "data": resp.data}
  ```

- **K6b — always-on live values (`self.base.put_lbuf`).** Canonical: `DriverPoller.get_data`
  returns `DriverResponse(data={...})`; the poller forwards to `put_lbuf` through its
  `_base_hook` (`helao_driver.py:219-220`), wired by passing `poller_class=` to `BaseAPI`
  (`base_api.py:667-671`). The driver's loop body becomes a synchronous single read.

  ```python
  # BEFORE (sprintir_driver.py:284-322, task spawned in __init__ :152)
  async def poll_sensor_loop(self, frequency=4, ...):
      while True:
          co2_level = self.read_stream()
          ...
          await self.base.put_lbuf(msg_dict)

  # AFTER (new class next to the driver; no loop, no base)
  class SprintIRPoller(DriverPoller):
      def get_data(self) -> DriverResponse:
          co2_level = self.driver.read_stream()
          if not co2_level:
              return DriverResponse()          # empty data -> live_dict untouched
          return DriverResponse(data={"co2_ppm": int(co2_level) * self.driver.fw["scaling_factor"]})
  ```

  Loop niceties (reset-after-N-blanks, `sprintir_driver.py:299-304`) become poller state, or
  driver-internal counters inside `get_data`.

### K7 — Methods that take `Active` → (driver method over plain params → `DriverResponse`) + (Executor that owns `active`)

Split rule: everything the method **reads from** `active` (`action.action_params`,
`action.get_sequence_dir()`) becomes explicit arguments extracted by the Executor/endpoint;
everything the method **does to** `active` (enqueue, `append_sample`, `finish`) moves into
the Executor phases; what remains returns a `DriverResponse`.

```python
# BEFORE (calc_driver.py:747-762)
async def check_co2_purge_level(self, activeobj: Active) -> dict:
    params = activeobj.action.action_params
    ...
    seq_reldir = activeobj.action.get_sequence_dir()

# AFTER — driver: plain params in, DriverResponse out (also fixes K4/K5 in the same move)
def check_co2_purge_level(self, seq_absdir: str, co2_ppm_thresh: float,
                          purge_if: str | float, present_syringe_volume_ul: float,
                          repeat_experiment_name: str, repeat_experiment_params: dict,
                          repeat_experiment_kwargs: dict) -> DriverResponse: ...

# AFTER — action server: a oneoff Executor bridges Active <-> driver
class CalcExec(Executor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)     # oneoff=True default
        self.driver = self.active.driver
    async def _exec(self) -> dict:
        p = self.active.action.action_params
        seq_absdir = os.path.join(str(self.active.base.helaodirs.save_root),
                                  self.active.action.get_sequence_dir())
        self.result = self.driver.check_co2_purge_level(seq_absdir, **{k: p[k] for k in (...)})
        return {"data": self.result.data, "error": ErrorCodes.none}
    async def _post_exec(self) -> dict:
        ...  # K5 dispatch, see above
```

**Sub-kind K7b — the driver creates its own `Active`** (`self.base.contain_action` inside the
driver: `sprintir_driver.py:428`, plus `nidaqmx`, `pal`, `galil_motion`,
`spectral_products`, Deployment-A `thorlabs_kinesis.py`). This is the worst inversion: the
device backend runs the action lifecycle. Target: the endpoint calls
`app.base.setup_and_contain_action()` and `active.start_executor(<Exec>)` (the
`o2sensor_server.py:67-75` shape); the driver's active-creation block dissolves into
`Executor._pre_exec` (file headers, sample bookkeeping) and the driver keeps only device I/O.

Two adjacent couplings ride along with K7 and are resolved by the same move:
- **estop reads** (`self.base.actionservermodel.estop`, `sprintir_driver.py:188,197`): estop
  is server state. The Executor framework already terminates executors on estop, and the
  driver's contribution is its ABC `stop()`/`reset()` implementations plus the Executor's
  `_manual_stop`. Delete driver-side estop branches.
- **sample DB** (`UnifiedSampleDataAPI(self.base)`, `sprintir_driver.py:61,138`): sample
  validation/inheritance is action bookkeeping → endpoint/`_pre_exec`
  (cf. `fast_samples_in` handling in `o2sensor_server.py:50-52`), never the driver.

### K8 — Loops started in `__init__` → `DriverPoller` (always-on) or `Executor._poll` (action-scoped); the `__init__`-hazard removal rule

**Rule: a migrated driver's `__init__` may only call `super().__init__(config=config)` and
assign attributes derived from `config`. Forbidden in `__init__`: opening devices
(`serial.Serial(...)`, `sprintir_driver.py:66-74` → move to `connect()`); touching the event
loop (`asyncio.get_event_loop()` `:134`, `create_task` `:152-153`); fire-and-forget coroutines
(`asyncio.gather(self.unified_db.init_db())` `:139`); starting threads.** The ABC constructor
(`helao_driver.py:101-108`) is the template: timestamp + config, nothing else.

Routing the two loop kinds (per P4 D2):
- **always-on** (`poll_sensor_loop`, `sprintir_driver.py:284`) → `DriverPoller.get_data`
  (K6b sketch above); the poller owns its tasks (`helao_driver.py:178-179`) and is
  constructed by `base_api` **inside the running server**, which is what makes deleting the
  driver's `create_task` safe.
- **action-scoped** (`IOloop`, `sprintir_driver.py:175-228`, flag-driven via `IO_signalq`)
  → an `Executor` with `oneoff=False`; the loop body becomes `_poll`, the start/stop flags
  become `start_executor`/`_manual_stop`. **Check for dead twins first**: `sprintir`'s
  `acquire_co2`+`IOloop`+`continuous_record` path is already superseded — its endpoint
  (`co2sensor_server.py:45-65`) routes through `CO2MonExec` via `active.start_executor`.
  Hybrid drivers frequently carry such a dead legacy IOloop; after confirming no endpoint or
  experiment references it, **delete it rather than migrate it** (extends P4 D5's retire-
  don't-migrate principle to dead code paths inside kept drivers).

Finally, `shutdown()` (task-cancel + port close, `sprintir_driver.py:459-469`) maps onto the
ABC: device close → `disconnect()`; abort-activity → `stop()`; force-reopen → `reset()`;
task cancellation disappears (the poller/Executor own their tasks).

---

## 2. Weaning recipe (ordered steps for the implementer)

Per driver, in this order (each step keeps the server bootable; commit after 12):

1. **Baseline capture (D7):** run `conda run -n helao python .omc/artifacts/p3/import_smoke.py`
   for the affected server + (Linux-runnable) an e2e action capture via
   `.omc/artifacts/p3/run_e2e.sh` / `compare_runs.py`; save outputs.
2. **Fingerprint:** grep the driver for the K1–K8 markers (`server_cfg`, `helao_cfg|world_cfg`,
   `print_message`, `helaodirs`, `orch_key|async_private_dispatcher`, `enqueue_data|write_file`,
   `put_lbuf|get_lbuf`, `contain_action`, `: Active`, `create_task`, `actionservermodel`,
   `UnifiedSampleDataAPI`). Cross-check against the table in §3; investigate any marker the
   table doesn't list.
3. **Dead-twin check (K8):** if the action server already routes an endpoint through an
   `*Exec`, verify the driver's parallel IOloop path is unreferenced (endpoints, experiments,
   configs) and delete it.
4. **K3 logging swap** (`print_message` → module `LOGGER`). Pure churn; do it first.
5. **K7 split:** for each method taking `Active`/`Action`, rewrite as plain-params →
   `DriverResponse`; author/extend the `*Exec` in the action server that extracts params and
   owns `active` (reference: `gamry_server2.py:59,99,690`). Fold estop/sample-DB couplings
   into the Executor/endpoint here.
6. **K4 paths:** add explicit dir arguments; compute them in the Executor/endpoint from
   `active.base.helaodirs` + `action.get_sequence_dir()`.
7. **K5 dispatch:** driver returns `insert_experiment` intent in `DriverResponse.data`;
   Executor `_post_exec` dispatches via `active.base.orch_key/host/port`.
8. **K6b poller:** move always-on loop bodies into a `<Driver>Poller(DriverPoller).get_data`;
   pass `poller_class=` in the server's `BaseAPI(...)` call.
9. **K8 purge + lifecycle:** delete every `create_task`/`get_event_loop`/`gather` and device
   open from `__init__`; implement `connect`/`get_status`/`stop`/`reset`/`disconnect` →
   `DriverResponse` (device open in `connect()`; `shutdown()` logic redistributed).
10. **K1/K2 signature flip:** `__init__(self, action_serv: Base)` →
    `__init__(self, config: dict = {})` + `super().__init__(config=config)`; subclass
    `HelaoDriver` (this is what flips the `base_api.py:665` branch — `makeApp` stays
    `driver_classes=[X]` verbatim); world-config reads → `_data_root()` pattern.
11. **Endpoints:** replace `app.driver.<method>(active/**params)` with
    `active.start_executor(<Exec>(active, ...))` (or a plain synchronous call + unwrap for
    trivial query endpoints, per the HTEdata pilot); unwrap `DriverResponse`; pin any
    endpoint parameter annotations that referenced driver-owned dynamic types.
12. **Gate (§4):** re-run step-1 captures, diff, then commit + push per P4 wave cadence.

Steps 5–8 are independent of the signature flip (they only *reduce* the `self.base` surface),
which is why the flip lands second-to-last: after step 9 the only remaining `self.base` uses
are K1/K2, and step 10 is then mechanical and revertable on its own.

---

## 3. Per-driver coupling fingerprints (remaining coupled drivers)

Grep-based (2026-07-11) against the K-markers in §2 step 2, joined with the P4 §3 table.
Legend: ● = present, ○ = absent. `7b` = driver calls `contain_action` itself; `es` = estop
reads; `sm` = `UnifiedSampleDataAPI(self.base)`. **Linux-verif**: `e2e` = full behavior
runnable on this box; `constr` = construction/import proof only (device is Windows-only or
physical); per P4 D7(d) hardware-only drivers defer live smoke to first station run.

### hte (public)

| Driver | K1 | K2 | K3 | K4 | K5 | K6a | K6b | K7 | K8 | extra | Linux-verif | Wave |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `data/calc_driver.py` Calc | ● | ● | ○ | ● | ● | ○ | ○ | ● | ○ | — | **e2e** | W1 |
| `sensor/axiscam_driver.py` AxisCam | ● | ○ | ● | ● | ○ | ○ | ○ | ○ | ○ | — | constr (cam HW) | W2 |
| `sensor/cm0134_driver.py` CM0134 | ● | ○ | ○ | ○ | ○ | ○ | ● | ○ | ● | — | constr (serial) | W2 |
| `sensor/sprintir_driver.py` SprintIR | ● | ○ | ○ | ○ | ○ | ● | ● | ●7b | ● | es, sm | constr (serial) | W3 |
| `mfc/alicat_driver.py` AliCatMFC | ● | ● | ● | ○ | ○ | ○ | ● | ○ | ● | sm | constr (serial) | W3 |
| `pump/legato_driver.py` KDS100 | ● | ○ | ● | ○ | ○ | ○ | ● | ○ | ● | sm | constr (serial) | W3 |
| `pump/simdos_driver.py` SIMDOS | ● | ○ | ○ | ○ | ○ | ○ | ● | ○ | ● | sm | constr (serial) | W3 |
| `temperature_control/mecom_driver.py` TEC | ● | ○ | ○ | ○ | ○ | ○ | ● | ○ | ● | — | constr (serial) | W3 |
| `io/galil_io_driver.py` Galil-IO | ● | ○ | ● | ○ | ○ | ○ | ● | ○ | ● | es | constr (gclib/Win) | W4 |
| `io/nidaqmx_driver.py` cNIMAX | ● | ● | ○ | ○ | ○ | ● | ● | ●7b | ● | es, sm | constr (Win) | W5 |
| `motion/galil_motion_driver.py` Galil-M | ● | ○ | ○ | ● | ○ | ○ | ○ | ●7b | ● (thread) | es, sm | constr (gclib/Win) | W5 |
| `spec/spectral_products_driver.py` SM303 | ● | ○ | ● | ○ | ○ | ● | ○ | ●7b | ● | es, sm | constr (Win/ctypes) | W5 |
| `robot/pal_driver.py` PAL | ● | ● | ○ | ○ | ○ | ● | ○ | ●7b | ● | es | constr (Win, **PROD**) | W6 |
| `data/archive_driver.py` Archive | ● | ● | ○ | ● | ○ | ● | ○ | ● | ○ (threads) | sm | constr (**PROD**; see P4 §7) | W6 |

(`data/HTEdata_legacy.py` — migrated, pilot. `data/dbpack_driver.py` — frozen, per P4 D5.)

### Deployment-A (private)

| Driver | K1 | K2 | K3 | K4 | K5 | K6a | K6b | K7 | K8 | extra | Linux-verif | Wave |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `calc_driver.py` Calc | ● | ● | ○ | ○ | ○ | ○ | ○ | ○ | ○ | — | **e2e** | W1 |
| active-learning driver (`ml_driver.py`) | ● | ● | ● | ○ | ● | ○ | ○ | ● | ○ | — | **e2e** | W1 |
| `elveflow_driver.py` MuxDRI | ● | ○ | ● | ○ | ○ | ○ | ○ | ○ | ○ | — | constr (Win/ctypes) | W5 |
| `thorlabs_kinesis.py` ThorlabsMotor | ● | ● | ○ | ● | ○ | ○ | ○ | ●7b | ● (thread) | es, sm | constr (vendor lib) | W4 |

Note the Deployment-A active-learning driver is **not** "light" as the P4 §3 table graded it:
it exhibits K5 (its `enqueue`, dispatcher at `ml_driver.py:324-334`) and K7 (`add_point`/
`fit`/`acquire`/`random_acquire` all take `Active`). Re-grade to **medium**; it is precisely
why it belongs in the W1 pilot — it exercises K5+K7 with zero hardware.

### Deployment-B (private)

| Driver | K1 | K2 | K3 | K4 | K5 | K6a | K6b | K7 | K8 | extra | Linux-verif | Wave |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `actuator_driver.py` | ● | ○ | ○ | ○ | ○ | ○ | ● | ○ | ● | — | constr | W4 |
| `robotarm_driver.py` | ● | ○ | ○ | ○ | ○ | ○ | ● | ○ | ● | — | constr (net HW) | W4 |
| `leancat_driver.py` | ● | ●(heavy) | ○ | ○ | ● | ○ | ● | ○ | ● | — | constr (OPC-UA HW) | W4 |

Note `leancat_driver.py` is the only non-W1 driver with K5 (6 dispatcher references) and the
heaviest K2 user (10 world-config reads); its W4 slot should be executed **after** the W1
pilots have locked the K2/K5 patterns.

Fingerprint deltas vs. P4 §3 worth carrying back into that table: Deployment-A ml → medium
(above); `galil_motion` has K4 (3 `helaodirs` refs) not previously graded; `archive_driver`
confirms K2+K4+K6a+K7 but no `__init__` asyncio hazard (threads only) — consistent with the
P4 §7 open question that it may be a `HelaoDriver` in name only.

---

## 4. Verification per kind (behavior-preservation gates)

All commands via `conda run -n helao` (repo convention). Baseline is always captured **before**
touching the driver (recipe step 1).

| Kind | Gate | How |
|---|---|---|
| K1 | construction | `.omc/artifacts/p3/import_smoke.py` on the affected `makeApp`; assert `app.driver.config == <baseline server_params snapshot>` and OpenAPI param shapes unchanged. The `server_api.py:74` identity makes this sufficient. |
| K2 | unit + construction | Unit: `Driver(config={"data_root": tmpdir})` resolves paths under `tmpdir`; with no override and a stubbed `config_loader.CONFIG`, resolves under its `root`. Construction: import_smoke green with the real config (no YAML edits needed). |
| K3 | unit | Log-capture test: each migrated call site emits at the mapped level; grep gate: zero `print_message` left in the driver module. |
| K4 | unit (fixture tree) | Point the method at a captured RUNS fixture dir; diff returned dict against the pre-change capture of the same method run in-server. `hte` Calc: `gather_seq_data`/`calc_uvis_abs` output equality on a recorded sequence. |
| K5 | **e2e sim** | Through the `.omc/artifacts/p3` harness (`run_e2e.sh` + `enqueue_oersim.py` + `compare_runs.py`): drive an action whose params force the loop condition true, assert the orchestrator queue receives the same `insert_experiment` payload (idx, experiment_name, params) as baseline; and a false-condition run enqueues nothing. Plus a unit on the driver: intent present/absent in `DriverResponse.data` per condition. |
| K6a | e2e diff | Run the action end-to-end (sim/loopback where possible); `normalize_runs_tree.py` + diff of the produced `.hlo`/`-act.yml` against baseline (same columns, same row cadence within poll-rate tolerance). |
| K6b | live-buffer probe | With the poller wired, subscribe `/ws_live` (or read `base.get_lbuf(key)`) and compare key set + update cadence to baseline; hardware-only drivers substitute a stubbed `get_data` returning canned values to prove the wiring. |
| K7 | unit + e2e | Unit: driver method now importable and callable with **no server, no event loop** (this is the point). E2e: endpoint round-trip returns an action dict with same status/output files as baseline. |
| K8 | construction proof | In a bare interpreter (no running loop): `Driver(config={})` must not raise, must not open a port, must not spawn tasks (assert `asyncio.all_tasks` unchanged where a loop exists). Grep gate: no `create_task|get_event_loop|ensure_future|asyncio.gather|Thread(` in the driver module (poller classes exempt — they don't override `__init__`). Then `connect()` on real hardware at first station run (D7(d)). |

Wave-level: unit suite green + import_smoke on every server whose driver changed, per P4 D7.

---

## 5. Open questions (append to `.omc/plans/open-questions.md`)

- **OQ-1 (K2):** Is the `config`-key-override-with-`config_loader.CONFIG`-fallback the end
  state, or a transition? The pure end state is "drivers read only their `config` dict",
  which requires adding explicit keys (e.g. `data_root`) to every private deployment YAML
  that hosts a K2 driver — deployment churn P4 deliberately avoids. **Recommended: fallback
  pattern now; revisit after W4 when the K2 population (5 drivers) is known-final.**
- **OQ-2 (K5):** This spec keeps loop-control dispatch in the action server
  (`Executor._post_exec`). The alternative — driver/Executor merely *reports*
  (`redo_purge: true`) and the **experiment/orchestrator layer** decides to enqueue — is
  cleaner (action servers stop knowing about orchestrator queues at all) but changes
  experiment authoring for every conditional-loop sequence. **Recommended: Executor-owned
  dispatch for P4 (behavior-preserving); file the orch-side conditional as a post-P4 item.**
- **OQ-3 (K8 dead twins):** Confirm per-driver that flag-driven IOloop paths superseded by
  existing `*Exec` classes (starting with `sprintir` `acquire_co2`,
  `sprintir_driver.py:384-457`) have no remaining endpoint/experiment/config references
  before deletion; if any private deployment still routes through them, that driver's
  migration inherits a real IOloop→Executor port instead of a delete.
- **OQ-4 (Archive):** Unchanged from P4 §7 — settle the ABC boundary before W6; its
  fingerprint (K2+K4+K6a+K7, no device, no init-loop) suggests most of its "driver" is
  actually sample/data bookkeeping that may belong server-side.
