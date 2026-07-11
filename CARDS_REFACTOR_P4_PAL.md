# CARDS Refactor — P4 PAL Spec: decomposing the PAL job-loop driver for the `HelaoDriver` ABC

> Deployment aliasing: this doc lives in the **public** parent repo, so private deployments
> are referred to as **Deployment-A/B/C/D**. `hte` is public/tracked; PAL/archive names are
> fine. No config YAML content, hostnames, or credentials are reproduced here.

**Status:** DESIGN SPEC (companion to `CARDS_REFACTOR_P4.md` §"BLOCKED — pal_driver.py" and
`CARDS_REFACTOR_P4_WEANING.md`; **no code yet**). All line references verified on branch
`feat/cards-refactor` (2026-07-11). Execution requires a session with access to a live PAL
station for the final gate; everything up to the station smoke test is runnable on Linux.

**Files:**
- driver: `helao/deploy/hte/drivers/robot/pal_driver.py` (3199 lines)
- server: `helao/deploy/hte/servers/action/pal_server.py` (833 lines)
- shim: `helao/deploy/hte/drivers/robot/sample_shim.py` (`SampleArchiveShim`, RPC to the SAMPLE server)
- existing Linux harness: `helao/deploy/hte/tests/test_pal_ioloop_c1_guard.py`

---

## 0. Why PAL could not migrate mechanically, in one paragraph

Every other P4 driver had per-action work that could be re-homed into a per-action
`Executor` (K7/K7b) or an always-on loop that became a `DriverPoller` (K6b/K8). PAL has
neither: `_PAL_IOloop` (`pal_driver.py:2205`) is a **single, process-lifetime job engine**
that is the *sole* execution path for all 13 live `method_*` action handlers. The driver —
not the endpoint — creates the `Active` (`self.base.contain_action`, `:2161`), the endpoint
**returns before the job runs**, and the real `active.finish()` happens minutes later inside
the loop (`:2400`). In between, `_sendcommand_main` (`:474-782`) threads `self.active`
through ~20 **sequential, order-dependent** sample-DB mutations (get → mutate → new →
update → archive-position write → HLO row → `append_sample` in/out) inside a nested
microcam×repeat loop that also calls `active.split()` mid-loop (`:530`). A mechanical K7b
port would rewrite the physical sample-tracking pipeline of a production liquid-handling
robot — unverifiable without hardware. This spec maps the current architecture, states the
mismatch precisely, specs two candidate designs, and recommends one.

---

## 1. Current-architecture map (verified line refs)

### 1.1 Surface inventory

- **Endpoints** (`pal_server.py`): 17 total — `stop` (:74) and `kill_PAL` (:91) always;
  15 cam-gated method endpoints (`PAL_run_method` :112, `PAL_ANEC_aliquot` :210,
  `PAL_ANEC_GC` :252, `PAL_injection_tray_GC` :282, `PAL_injection_custom_GC` :330,
  `PAL_injection_custom_HPLC` :369, `PAL_injection_tray_HPLC` :404,
  `PAL_transfer_tray_tray` :444, `PAL_transfer_tray_custom` :496,
  `PAL_transfer_custom_tray` :544, `PAL_transfer_custom_custom` :591, `PAL_archive` :634,
  `PAL_deepclean` :713, `PAL_dilute` :747, `PAL_autodilute` :794).
- **Driver `method_*` handlers**: **13 live** (`method_arbitrary` :2402 through
  `method_ANEC_aliquot` :2996), each a pure `PalCam`-builder from `A.action_params` +
  `A.samples_in` that ends in `return await self._init_PAL_IOloop(A=A, palcam=palcam)`.
  4 more are **commented out** (`method_fill` :2609, `method_fillfixed` :2638,
  `method_dilute` :2695, `method_autodilute` :2727).
- ⚠️ **Pre-existing breakage found during this investigation:** `pal_server.py:789` and
  `:830` call `app.driver.method_dilute` / `method_autodilute`, which do **not exist**
  (commented out at driver `:2695`/`:2727`). Any config that lists the `dilute`/`autodilute`
  cams registers endpoints that raise `AttributeError` at request time. This is a dead-twin
  (weaning K8 / OQ-3 class) to resolve during migration, not silently port (→ OQ-P2).
- **Params already flow via `action_params`** — the endpoints call `app.base.setup_action()`
  and the driver methods read `A.action_params.get(...)` (e.g. `method_archive` :2576-2603).
  PAL is therefore NOT exposed to the K7 fn-args CRITICAL from the weaning spec; keep it
  that way (the endpoint fn-args exist only to define the API surface).

### 1.2 `__init__` (`:244-350`) — the K8 hazard map

- `:252-254` — `self.base = action_serv`, `config_dict = server_cfg["params"]`,
  `world_config = world_cfg` (K1 + K2).
- `:256` — `self.archive = SampleArchiveShim(self.world_config)`. **Post archive-hoist there
  is no local sample DB in this driver**: the shim RPCs every archive/unified_db call to the
  standalone SAMPLE action server, resolving host/port from world config *at call time*, and
  raises `RuntimeError` on transport failure (`sample_shim.py:1-33`). The old `sm` coupling
  (`UnifiedSampleDataAPI(self.base)`) is already gone.
- `:258-281` — SSH user/key/host, cam file path, `timeout` (default 30 min), NI-DAQ trigger
  port config (`dev_trigger == "NImax"`).
- `:284-298` — the shared mutable job state: `self.action`, `self.active`, `IO_do_meas`,
  `IO_measuring`, `IO_palcam`, `IO_continue`, `IO_error`, `IO_action_run_counter`.
- `:300-302` — **`asyncio.get_event_loop()` + `create_task(self._PAL_IOloop())`** — the K8
  hazard; the loop is born at construction and lives until process death.
- `:304-350` — HLO column headings (`FIFO_column_headings`), CAMS table merge from config,
  aux-log header, `IOloop_run` flag, `IO_signalq = asyncio.Queue(1)` plus the three trigger
  queues (`IO_trigger_startq/continueq/doneq`).

### 1.3 The endpoint → job-queue → loop → finish flow

```
orch / operator
   │  POST /<key>/PAL_archive (params in action_params)
   ▼
pal_server endpoint (:634-671)
   │  A = app.base.setup_action()
   │  return await app.driver.method_archive(A)          ← thin passthrough
   ▼
PAL.method_archive (:2576)  — builds PalCam from A.action_params
   ▼
PAL._init_PAL_IOloop (:2126-2203)
   │  guards: sshhost set, not IO_do_meas/IO_measuring, not estop (:2142-2147)
   │     busy      → A.error_code = in_progress, return A.as_dict()   (:2197-2200)
   │     estop     → A.error_code = estop                             (:2187-2190)
   │     no host   → A.error_code = not_available                     (:2192-2195)
   │  check_tool per microcam (:2151-2155)
   │  self.active = await self.base.contain_action(ActiveParams(...   (:2161-2172)
   │        file_conn: dflt key, file_type="pal_helao__file"))
   │  await self.set_IO_signalq(True)                                 (:2176)
   │  return self.active.action.as_dict()                             (:2185)
   ▼                                    ◄── ENDPOINT RETURNS HERE; action still ACTIVE.
   ▼                                        (orch observes completion via /ws_status only)
_PAL_IOloop (:2205-2339)   [process-lifetime task; job "queue" = IO_signalq(maxsize 1)
   │                        + the IO_palcam/action/active slots — capacity exactly 1 job]
   │  IO_do_meas = await IO_signalq.get()                             (:2216)
   │  _PAL_IOloop_meas_start_helper (:2341-2357)
   │        finish_hlo_header(file_conn_keys, realtime)               (:2347-2350)
   │        IO_palcam.samples_in = shim.unified_db.get_samples(...)   (:2355-2357)
   │  for run in range(IO_palcam.totalruns):                          (:2237)
   │        run_palcam = deepcopy(IO_palcam); run_palcam.cur_run=run  (:2242-2243)
   │        spacing wait: linear/geometric/custom (:2261-2302), sleep (:2306-2307)
   │        busy re-check via IO_signalq (:2310-2317)
   │        IO_error = await _sendcommand_main(run_palcam)            (:2322)
   │        cancel IO_trigger_task (:2325-2327)
   │  finally: _PAL_IOloop_meas_end_helper (:2359-2400)
   │        PAL_pid.communicate() (:2362-2365), cancel trigger task, reset IO flags,
   │        stamp active.action.error_code from IO_error (C1 guard, :2395-2396),
   │        self.active = None; await last_active.finish()            (:2397-2400)
   ▼
_sendcommand_main (:474-782)          [one PAL joblist == one run]
   │  _sendcommand_prechecks (:1684-1780)
   │        aux logfile via active.write_file_nowait(...)             (:1705-1711)
   │        per microcam × (repeat+1): check_source (:1735), check_dest (:1739)
   │           — both consult the shim (tray/custom query, new_ref_samples) and
   │             build microcam.run entries + palcam.joblist (_palcmd) (:1773-1778)
   │  _sendcommand_submitjoblist_helper (:1850-1991)
   │        kill_PAL first (:1866); _clear_trigger_qs (:1871);
   │        IO_trigger_task = create_task(_poll_trigger_task) (:1872)  [NI-DAQ edges → 3 queues,
   │           timestamps via active.get_realtime_nowait, :407-472]
   │        localhost: subprocess.Popen("PAL /loadmethod ... /start /quit") (:1888-1894)
   │        remote: paramiko SSH, mkdir/touch/echo aux header, tmux new-window PAL ... (:1898-1989)
   │        palcam.joblist_time = active.get_realtime_nowait() (:1892 / :1977)
   │  for i, microcam in enumerate(palcam.microcams):                 (:508)
   │     for palaction in microcam.run:                               (:518)
   │        stop check: drain IO_signalq → break (:510-523)
   │        if i > 0: await self.active.split()                       (:529-530)
   │        active.action.samples_in/out = [] ; action_sub_name = method (:532-534)
   │        _sendcommand_triggerwait (:1782-1838): await start/continue/done
   │           queues with self.timeout each; timeout → *_timeout error (:1810-1812)
   │        THE ORDERED SAMPLE PIPELINE (steps 1-9, :575-767 — see §1.4)
   │        IO_action_run_counter += 1                                (:769)
   │  20 s close wait + PAL_pid.communicate()                         (:771-780)
```

### 1.4 The ordered sample pipeline (LOAD-BEARING, byte-for-byte)

Inside the palaction loop, in exactly this order (comments at `:551-573` document intent):

1. `:577-616` — refresh `palaction.samples_in`, `source.samples_initial`,
   `dest.samples_initial` from the DB (shim `get_samples`); stamp
   `sample.action_uuid = [self.active.action.action_uuid]` on every sample (note: read
   **live** — after `split()` the uuid differs per segment).
2. `:622-665` — samples_out ref→real prep: `sample_creation_timecode = continue_time`
   (the **continue trigger** is the sampling timestamp), `destroy_sample()` if destroyed
   status, assembly part resolution (`get_samples`/`new_samples` per part, `:638-656`),
   rebuild `sample_out.source` from part labels.
3. `:669-671` — `samples_out = shim.unified_db.new_samples(samples_out)` (refs become real).
4. `:679-683` — deepcopy palaction samples into `IO_palcam.samples_in/out`.
5. `:690` — `_sendcommand_update_sample_volume(palaction)` (:2090) — source volumes
   decremented / dest incremented (initial → final).
6. `:694-705` — `update_samples(samples_in)`; per assembly sample_out: refresh parts,
   re-stamp uuid, `update_samples([sample_out])`.
7. `:708` — `_sendcommand_update_archive_helper(palaction)` (:2007-2088) — final samples
   pushed into tray/custom **positions** (`tray_update_position` / `custom_update_position`).
8. `:711-756` — if `active.action.save_data`: build the 18-column row
   (`FIFO_column_headings`, :304-323) and `active.enqueue_data(...)` keyed on
   `active.action.file_conn_keys[0]` (comment `:743-749`: split() rotates this key).
9. `:761-767` — `active.append_sample(IO_palcam.samples_in, IO="in")` then
   `append_sample(..., IO="out")` — **in before out, every palaction**.

**Behaviors that MUST be preserved byte-for-byte:**

- **B1 — Pipeline order.** Steps 1-9 above, including every uuid re-stamp and deepcopy.
  Reordering any `await` against the shim changes recorded sample lineage/volumes.
- **B2 — `split()` semantics.** Split happens **only for microcam index `i > 0`**
  (`:529`), i.e. once per palaction of every non-first microcam; **never between repeats
  of microcam 0 and never between `totalruns` runs** (each run re-enters the loop with
  `i = 0`). `Active.split()` (`base.py:1930-2027`) marks the old action `split`, force
  re-inits the action (new uuid, `action_split += 1`), resets `samples_in/out/files`, and
  opens fresh file conns — so each split segment carries only its own palaction's samples
  and HLO rows. Corollary (quirk, preserve as-is): repeats *within* one microcam reset
  `action.samples_in/out` (`:532-533`) without splitting, so the surviving action records
  only the **last** repeat's samples for that segment while the HLO file keeps one row per
  repeat (→ OQ-P6).
- **B3 — Endpoint-returns-before-job async contract.** The endpoint response is the
  **unfinished** active action dict (`:2185`); the orchestrator's tracking depends on
  status-WS updates culminating in the loop-side `finish()` (`:2400`). Any design must keep
  "HTTP 200 with active action now, finish later" — PAL actions run for minutes and the
  orch's `nonblocking`/status machinery expects it.
- **B4 — Busy/estop/no-host rejections** with exactly `in_progress`/`estop`/
  `not_available` error codes and **no** `contain_action` (`:2142-2200`): a rejected call
  writes no artifact.
- **B5 — Timing sources.** `joblist_time` from `active.get_realtime_nowait()` at submit
  (`:1892/:1977`); trigger timestamps from `get_realtime_nowait()` inside
  `_poll_trigger_task` (`:441/:450/:460`); `sample_creation_timecode = continue_time`
  (`:624`). These times land in the HLO row and in the sample DB.
- **B6 — Failure funnel.** Every loop exit path runs `_PAL_IOloop_meas_end_helper`
  (`finally`, `:2334-2337`) which stamps `IO_error` onto the action before `finish()`
  (`:2395-2396`, the C1 fail-loud guard covered by
  `helao/deploy/hte/tests/test_pal_ioloop_c1_guard.py`).
- **B7 — `kill_PAL` before every submit** (`:1866`) and the 20 s drain + pid wait after
  the microcam loop (`:771-780`).

### 1.5 Stop / estop / shutdown today

- `PAL.stop()` (`:3085-3089`) — async, pushes `False` on `IO_signalq` if measuring,
  **returns `None`**; `pal_server.py:87` enqueues `{"stop": await app.driver.stop()}`, i.e.
  records `{"stop": null}`.
- `PAL.estop()` (`:3091-3109`) — sets `self.base.actionservermodel.estop = switch`
  (`:3103`) which is **redundant**: the framework estop endpoint (`base_api.py:862`) already
  sets `actionservermodel.estop`, calls `driver.estop(...)` when present, stops all
  registered executors, and estops actives. The driver's unique contribution is
  `set_IO_signalq(False)` + `active.set_estop()` (`:3106-3108`).
- `PAL.shutdown()` (`:3071-3083`) — sync; signals stop, then **blocking**
  `time.sleep(1)`×10 waiting for `self.active` to clear, then `IOloop_run = False`.
- Vestigial state: `IO_continue` is **write-only** today (`:293,1811,1824,2233,2371`) —
  the "block endpoint until first continue trigger" wait it served is commented out
  (`:2177-2181`) (→ OQ-P5). `self.action` (`:284,2159,2399`) duplicates
  `self.active.action` and is never read elsewhere.

### 1.6 Residual `self.base` surface (the actual weaning scope)

Post archive-hoist, the driver touches `self.base` in exactly these places:
`:252-254` (K1/K2 config), `:2146/:2187/:2376` (estop **reads**), `:2161` (`contain_action`,
K7b), `:2165-2166` (`dflt_file_conn_key`), `:3103` (estop **write**). Everything else
already goes through `LOGGER` (K3 done) or the shim. Fingerprint (weaning §3 table row
confirmed): K1 ●, K2 ● (world config feeds the shim), K3 ○, K4 ○, K5 ○, K6a ●
(`enqueue_data`/`write_file_nowait` via `self.active`), K6b ○, K7b ●, K8 ● (`:300-302` +
`IO_trigger_task` create_task `:1872`), es ●.

---

## 2. The core problem statement

The standard K7b recipe (weaning §1-K7b) assumes: *one action ⇒ one `Executor` instance ⇒
the framework's `action_loop_task` owns the `Active` from `start_executor` to finish; the
driver becomes a stateless device API called from `_pre_exec/_poll/_post_exec`*. The two
completed live-K7b ports fit that shape exactly:

- **SM303** (`spec_server.py:48` `SM303Exec`, started at `:444-445`): per-action Exec,
  `_poll` waits a trigger edge and reads a spectrum; driver
  (`spectral_products_driver.py:36`) is a plain synchronous device wrapper.
- **cNIMAX CellIV** (`nidaqmx_driver.py:799` `CellIVExec`, started from
  `nidaqmx_server.py:526-533`): the driver's `arm_cell_iv` (`:494-521`) receives **injected
  callables** (`get_realtime_nowait`, `finish_hlo_header`, `enqueue_data_nowait`,
  `:874-877`) so the NI callback can stream data without the driver holding an `Active`.

PAL violates every assumption at once:

1. **Active ownership is inverted and long-lived.** The driver creates the `Active`
   (`:2161`), holds it across the whole job, splits it mid-job (`:530` — after which the
   action's *identity* changes: new uuid, new file_conn_keys per `base.py:1966-2019`), and
   finishes it asynchronously (`:2400`) long after the endpoint returned. An Exec-owned
   `Active` per action does not map 1:1: **one endpoint call produces N split actions**,
   all managed inside the job.
2. **The injected-callables trick doesn't scale here.** CellIV needed 3 narrow callables.
   The PAL pipeline needs `get_realtime{,_nowait}`, `write_file_nowait`, `enqueue_data`,
   `append_sample`, `split`, `finish_hlo_header`, `set_estop`, plus **live reads/writes of
   `active.action` fields** (`action_uuid` after split, `file_conn_keys[0]`, `samples_in/out`
   resets, `action_sub_name`, `error_code`, `save_data`). That surface *is* the `Active`
   object; enumerating it as callables is a fiction.
3. **The loop is also a scheduler.** `totalruns` × spacing methods (`:2237-2307`) and the
   single-job busy semantics (queue of size 1 + `in_progress` rejection, `:2144/:2198`)
   are cross-action policy living in the same coroutine as the per-action pipeline.
4. **Verification asymmetry.** The ~300-line pipeline mutates a *physical* sample ledger.
   Every other P4 driver could be gated by construction proof + data-file diff; a mistake
   here corrupts sample lineage silently. Without PAL hardware only the construction and
   call-trace behavior is checkable — which caps how much rewriting is prudent.

So the choice is not *whether* to keep the job engine but **who owns the `Active` and where
the engine lives**.

---

## 3. Candidate designs

### 3.1 Design 1 — "Executor injects Active at job-start" (partial K7b, least rewrite)

**Essence:** keep `_PAL_IOloop` + `_sendcommand_main` as the job engine, but the driver no
longer creates, finishes, or reaches `self.base` for the `Active`. The **endpoint** contains
the action; a thin **`PALJobExec(Executor)`** hands the `Active` to the driver inside a job
object and reports completion to the framework.

**New pieces:**

```python
# pal_driver.py — job container (plain dataclass; no server imports)
@dataclass
class PALJob:
    palcam: PalCam
    active: "Active"            # injected; driver treats it as an opaque action context
    done: asyncio.Event = field(default_factory=asyncio.Event)
    error: ErrorCodes = ErrorCodes.none

# pal_server.py — one Exec class serves all 13 method endpoints
class PALJobExec(Executor):
    def __init__(self, palcam, *args, **kwargs):
        super().__init__(*args, **kwargs)      # oneoff=False, poll_rate ~0.2
        self.driver = self.active.driver
        self.palcam = palcam
    async def _pre_exec(self):
        self.job = self.driver.submit_job(self.palcam, self.active)   # was _init_PAL_IOloop guts
        return {"error": self.job.error}       # busy/no-host/tool errors surface here
    async def _poll(self):
        status = HloStatus.finished if self.job.done.is_set() else HloStatus.active
        return {"error": self.job.error, "status": status, "data": {}}
    async def _manual_stop(self):
        resp = self.driver.stop()              # ABC stop → DriverResponse
        return {"error": ErrorCodes.none if resp.response == DriverResponseType.success else ...}
```

Endpoint shape (per method, replacing the `setup_action → driver.method_X(A)` passthrough):

```python
A = app.base.setup_action()
A.action_abbr = "archive"
palcam = app.driver.build_palcam_archive(A.action_params, A.samples_in)  # renamed method_*
active = await app.base.contain_action(ActiveParams(action=A,
    file_conn_params_dict={app.base.dflt_file_conn_key(): FileConnParams(
        file_conn_key=app.base.dflt_file_conn_key(), file_type="pal_helao__file")}))
return active.start_executor(PALJobExec(palcam=palcam, active=active, oneoff=False))
```

`start_executor` (`base.py:1259-1271`) returns `self.action.as_dict()` immediately — **B3
(endpoint-returns-before-job) is preserved by the framework itself**, no custom code.

**What changes vs. what stays:**

| Piece | Fate |
|---|---|
| 13 `method_*(A: Action)` builders (`:2402-3069`) | become pure `build_palcam_*(params: dict, samples_in) -> PalCam` — drop the `Action` argument, keep every `.get(...)` default byte-identical; the `_init_PAL_IOloop` tail is removed |
| `_init_PAL_IOloop` (`:2126-2203`) | dissolves: guards (B4) → `submit_job` returns the same error codes **before** `contain_action`… see ⚠️ below; `contain_action` block (`:2161-2172`) → endpoint; `set_IO_signalq(True)` → `submit_job` |
| `_PAL_IOloop` (`:2205-2339`) | body unchanged except: reads job from an `asyncio.Queue[PALJob]` (replacing the bool `IO_signalq` handshake + `IO_palcam`/`self.active` slots); `finally` no longer calls `active.finish()` — it stamps `job.error`, sets `job.done` (the framework's `action_loop_task` finishes the action when `_poll` reports finished) |
| `_sendcommand_main` + helpers (`:474-2124`) | **byte-identical** except the mechanical rename `self.active` → `self._job.active` (and `self.IO_palcam` → `self._job`-scoped state). The 9-step pipeline (§1.4), split rule (B2), trigger logic, SSH/submit paths are untouched |
| `__init__` (`:244-350`) | K8 purge: no `get_event_loop`/`create_task` (`:300-302` deleted); job-worker task started lazily by the first `submit_job` (or from `connect()`); K1 flip: `__init__(self, config: dict = {})` + `super().__init__(config=config)`; K2: `world_config` for the shim → lazy `config_loader.CONFIG` fallback with explicit config-key override (weaning K2 pattern) |
| `stop` (`:3085`) | ABC-shaped **sync** `stop() -> DriverResponse` (signal `False` on the job queue via `set_IO_signalq_nowait`); `pal_server.py:87` unwraps the `DriverResponse` instead of enqueueing `None` |
| `estop` (`:3091-3109`) | driver-side `actionservermodel.estop` **write deleted** (`:3103`; `base_api.py:862` owns it); estop reads (`:2146/:2187/:2376`) deleted — busy/abort policy moves to `PALJobExec`/framework (`stop_executor` → `_manual_stop`); the driver keeps only "abort current job + optionally `kill_PAL`" |
| `shutdown` (`:3071`) | `disconnect()` = stop worker + close; per weaning ⚠️ shutdown-ordering rule, keep abort-then-close in ONE `async_shutdown`-equivalent path (`stop()` then `disconnect()`); no blocking `time.sleep` |
| `connect/get_status/reset/disconnect` | new, thin: `connect` = validate ssh key/host config (+ optionally probe SSH), `get_status` = busy/idle from worker state, `reset` = drain queues + reset IO flags, `disconnect` = cancel worker + trigger task. All return `DriverResponse` |
| `pal_server.py` endpoints | each gains the 4-line contain+Exec block above; fn-arg declarations (API surface) unchanged |

**⚠️ B4 subtlety:** legacy rejects busy/estop/no-host **without creating an action artifact**
(`contain_action` never runs). With the endpoint containing first, a naive port would write
an artifact for rejected calls. Preserve B4 by checking `app.driver.is_busy()` /
`app.base.actionservermodel.estop` / host-config **in the endpoint before**
`contain_action`, returning `A.as_dict()` with the same error codes.

**Tradeoffs / risk / size:**

- ✅ Pipeline (B1/B2/B5/B6/B7) preserved byte-for-byte; diffable by call-trace golden master (§5).
- ✅ Framework integration for free: executor registry (estop via `base_api.py:862`
  `stop_executor` loop), `start_executor` async contract (B3), `_manual_stop` for `/stop`.
- ✅ ABC-compliant: config ctor, lifecycle methods, no `__init__` tasks — flips the
  `base_api.py:661-676` seam branch with `makeApp` unchanged (`driver_classes=[PAL]`).
- ⚠️ Residual CARDS debt (accepted, documented): the driver still *holds* an `Active`
  reference for the job's duration and calls `split()/enqueue_data/append_sample` on it.
  Separation improves from "driver owns server + lifecycle" to "driver is lent a per-job
  action context"; it is not the pure "driver knows only its device" end state.
- ⚠️ New interaction to verify: `Executor` + mid-job `split()`. `exec_id` is stamped on the
  action at Exec construction (`executor.py:76-78`) and `split()` force-re-inits the action
  (`base.py:1970`) — confirm the executor registry key and `stop_executor` routing survive N
  splits (Linux-testable with the §5 harness; the only in-repo precedent, `CellIVExec`
  `:855`, is flagged NEW/unverified in P4). (→ OQ-P3)
- **Rewrite size:** ~350-450 lines touched (endpoints + Exec + `__init__`/lifecycle +
  `_init_PAL_IOloop` dissolution + renames); the 1,650-line `_sendcommand_*` pipeline is
  rename-only.

### 3.2 Design 2 — full Executor state-machine decomposition

**Essence:** delete `_PAL_IOloop` entirely; one `PALMethodExec(Executor, oneoff=False,
concurrent=False)` per action reconstructs the job semantics in the framework; the driver
shrinks to a stateless device API (`HelaoDriver` over SSH/subprocess + trigger reads).

**State-machine mapping** (each `_poll` iteration advances at most one transition;
`_poll` must never block longer than `poll_rate` — the legacy `await`-driven flow becomes
explicit states so `stop_action_task`/estop can interrupt between any two):

| Legacy code | Exec home / state |
|---|---|
| `_init_PAL_IOloop` guards + `check_tool` (`:2142-2155`) | endpoint pre-check + `_pre_exec` |
| `contain_action` (`:2161-2172`) | endpoint (`setup_and_contain_action` shape) |
| `meas_start_helper` (`:2341-2357`) | `_pre_exec`: `finish_hlo_header` + samples_in refresh |
| totalruns × spacing scheduler (`:2237-2307`) | states `SPACING_WAIT(run)` — deadline arithmetic kept, `asyncio.sleep` replaced by deadline checks per `_poll` |
| `_sendcommand_prechecks` (`:1684`) | `_pre_exec` (per run: state `PRECHECK(run)` since positions are re-resolved per deepcopied run_palcam) |
| `_sendcommand_submitjoblist_helper` (`:1850`) | state `SUBMIT(run)` — driver method `submit_joblist(palcam) -> DriverResponse` (kill_PAL + Popen/SSH); trigger poller becomes a driver-owned task started/stopped by `arm_triggers()/disarm_triggers()` (CellIV `arm_*` shape, callables injected for timestamps) |
| `_sendcommand_triggerwait` (`:1782`) | states `WAIT_START/WAIT_CONTINUE/WAIT_DONE(run,i,rep)` with per-state timeout accounting (`self.timeout`) |
| split rule (`:529-530`) | state transition `(i>0, new palaction)` → `await self.active.split()` in the Exec |
| pipeline steps 1-9 (`:575-767`) | state `SAMPLE_PIPELINE(run,i,rep)` — moved verbatim into an Exec method (shim + `self.active` both available) |
| 20 s drain + pid wait (`:771-780`, `:2362-2365`) | state `DRAIN` → `_post_exec` |
| `meas_end_helper` error stamp + finish (`:2395-2400`) | framework `action_loop_task` (finish) + `_post_exec` (error propagation) |
| busy semantics (`:2198`) | `concurrent=False` queues on `local_action_task_queue` (`base.py:1266-1267`) — **behavior change**: legacy *rejects* with `in_progress`, framework *queues*; must add an explicit endpoint busy-rejection to preserve B4 (→ OQ-P1) |
| `stop`/`estop`/`shutdown` (`:3071-3109`) | `_manual_stop` + ABC `stop()/disconnect()`; estop fully framework-owned |

**Tradeoffs / risk / size:**

- ✅ The clean CARDS end state: driver = device I/O only (`submit_joblist`, `kill_PAL`,
  trigger arm/read, ssh probe); full Separation + Resilience; job logic testable per state.
- ✅ Estop/stop become uniformly framework-mediated (no bespoke queue signaling).
- ❌ The 9-step pipeline and the scheduler are **rewritten across an async boundary**: every
  state cut is an opportunity to reorder an `await` against the shim or lose a uuid
  re-stamp — exactly the class of error that corrupts the physical sample ledger and that
  only a live station would catch. The call-trace golden master (§5) mitigates but cannot
  cover trigger-timing interleavings (`_poll` cadence vs. NI-DAQ edge queues).
- ❌ `_poll`-based trigger waits add up to `poll_rate` latency per transition (3 triggers ×
  microcams × repeats × runs) and change `IO_signalq` drain timing — B5 timestamps come from
  the trigger queues (unchanged) but stop-responsiveness timing differs.
- ❌ Rewrite size: ~1,200-1,500 lines restructured (loop + main + init + all method plumbing),
  plus a new driver API surface. Review burden ≈ a full W-wave on its own.
- **Risk: HIGH without hardware in the loop; MEDIUM with a station-resident test budget.**

### 3.3 RECOMMENDATION — Design 1, with Design 2 as a post-migration follow-up

**Choose Design 1 (variant with `PALJobExec` owning finish via the framework).** Reasoning:

1. **P4's gate is behavior preservation, and PAL is the one driver where a behavior bug is
   physically destructive** (mis-tracked vials). Design 1 keeps the entire mutation pipeline
   rename-only; Design 2 rewrites it. The migration constraint "construction-proof only on
   Linux; station smoke mandatory" (P4 D7(d)) caps acceptable rewrite ambition at Design 1.
2. Design 1 still clears every P4 acceptance criterion: `HelaoDriver` subclass, pure
   `__init__` (K8), config ctor (K1/K2), no `self.base` (K7b weaned to injected-`Active`),
   estop→framework, `stop()`→`DriverResponse`, `dilute` dead-twin resolved.
3. Design 2's genuine wins (stateless driver, per-state tests) are **additive later**: after
   Design 1, the Exec already owns the `Active` boundary, so Design 2 becomes an internal
   refactor of `PALJobExec` + driver — executable incrementally *at the station*, and it
   composes with the separately-approved archive-hoist Phase-4 cutover (the shim RPC layer),
   which will already have PAL exercising SAMPLE-server round-trips there.
4. Precedent honesty: the repo's only mid-job `split()`-under-Executor (CellIVExec) is
   itself unverified on hardware; betting the *entire* PAL pipeline (Design 2) on framework
   mechanics that haven't seen a station yet stacks unknowns. Design 1 bets only the
   job-completion handshake on them.

---

## 4. Sample-record preservation contract

**Invariant (the migration MUST hold):** for an identical `PalCam` input, identical injected
trigger timestamps, and identical sample-DB state, the migrated code produces:

- **S1** the same **ordered sequence of shim calls** — method name + payload for every
  `unified_db.get_samples/new_samples/update_samples`, `tray_query_sample`,
  `custom_query_sample`, `new_ref_samples`, `tray_get_next_full`, `tray_new_position`,
  `tray_update_position`, `custom_update_position`, `custom_*_allowed`,
  `custom_is_destroyed` — in the same order;
- **S2** the same `active.action.samples_in` / `samples_out` contents **and order** per
  split segment (in before out, B1 step 9), with the same per-segment reset behavior (B2);
- **S3** the same split count, split points (only `i > 0`), and parent/child action chain;
- **S4** the same HLO rows: one 18-column row per palaction (`FIFO_column_headings` order,
  `:304-323`), keyed on the live `file_conn_keys[0]`;
- **S5** the same `action_uuid` stamping onto every touched sample (live uuid per segment);
- **S6** the same error-code funneling: any pipeline/shim failure lands on the finished
  action's `error_code` (B6), and busy/estop/no-host rejections return the same codes with
  no artifact (B4).

**Verification without hardware — call-trace golden master.** Extend the proven harness
pattern of `helao/deploy/hte/tests/test_pal_ioloop_c1_guard.py` (constructs `PAL` via
`__new__`, fakes `Active`, stubs the shim, drives the **real** loop):

1. **Recorder fixtures:** a `RecordingActive` (logs every `split/enqueue_data/append_sample/
   write_file_nowait/finish_hlo_header/finish` call + a live fake `action` whose uuid rotates
   on split, mirroring `base.py:1970`) and a `RecordingShim` (scripted canned samples;
   logs S1). Stub `_sendcommand_submitjoblist_helper` (no SSH/Popen; still calls the
   recorder for `joblist_time`) and `_sendcommand_triggerwait` (inject fixed timestamps).
2. **Scenario matrix** (drives every load-bearing branch): (a) single microcam, 1 run;
   (b) 3 microcams incl. an `archive` dest (next-empty-vial path) → 2 splits; (c) microcam
   with `repeat=2` (B2 quirk); (d) `totalruns=3` with linear + geometric spacing (spacing
   arithmetic asserted on recorded sleep requests, not wall time); (e) assembly
   creation/update (steps 2/6 part handling); (f) destroyed-dest (GC/HPLC inject); (g) shim
   raise mid-pipeline (B6); (h) stop signal between palactions; (i) busy rejection (B4).
3. **Procedure:** capture baseline traces (JSON) at the pre-migration tip → run identical
   scenarios post-migration (Design 1: same harness, `PALJob` + real `PALJobExec` against a
   fake `Base` where feasible, else direct `submit_job`) → `diff` traces. Store under
   `.omc/artifacts/p4pal/` beside the P3 harness conventions.
4. Existing gates ride along: `run_unit_tests.py`, `import_smoke` on `makeApp(pal_server)`
   (OpenAPI param-shape diff — endpoints keep their fn-args), the C1 guard test unmodified.

**This does not replace the station smoke test (§6.2) — it proves ordering/bookkeeping, not
the PAL binary, SSH, NI-DAQ edges, or real archive state.**

---

## 5. Migration recipe (Design 1, ordered; each step keeps the server bootable)

1. **Baseline (weaning step 1):** capture golden-master traces (§4) + `import_smoke`
   snapshot + OpenAPI param shapes for `pal_server`; commit fixtures first.
2. **Dead twins (weaning step 3):** resolve `PAL_dilute`/`PAL_autodilute` per OQ-P2
   (delete endpoints or restore `method_dilute`/`method_autodilute` from `:2695/:2727`);
   delete commented `method_fill`/`fillfixed` blocks and the vestigial `IO_continue` writes
   (OQ-P5) — each its own commit.
3. **Job object seam (no behavior change):** introduce `PALJob`; convert `IO_signalq(1)` +
   `IO_palcam`/`self.active`/`self.action` slots into a job queue; `_sendcommand_main` and
   helpers read `job.active`/`job.palcam` (mechanical rename). `_init_PAL_IOloop` still
   builds the job and calls `contain_action` — loop finish unchanged. Golden master must
   pass unchanged here.
4. **K7b flip:** move `contain_action` + `FileConnParams` block (`:2161-2172`) and the B4
   guards into `pal_server.py`; convert `method_*` → `build_palcam_*` (params-dict in,
   `PalCam` out — params still sourced from `action_params`, per the K7 ⚠️ rule); add
   `PALJobExec`; loop stops calling `finish()` (sets `job.done`; framework finishes).
   Golden master + a fake-`Base` executor round-trip must pass.
5. **estop/stop (weaning K7-adjacent):** delete `:3103` and the estop reads; wire
   `_manual_stop`; reshape `stop()` → sync `DriverResponse` and unwrap at
   `pal_server.py:87`.
6. **K8 purge + lifecycle:** delete `:300-302`; lazy worker start on first `submit_job`;
   implement `connect/get_status/stop/reset/disconnect` → `DriverResponse`;
   `shutdown` per the weaning ⚠️ ordering rule (abort job **then** close, one async path;
   sync `shutdown()` no-op).
7. **K1/K2 signature flip (weaning step 10):** `__init__(self, config: dict = {})` +
   `super().__init__(config=config)`; subclass `HelaoDriver` (flips `base_api.py:665`);
   shim world-config via lazy `config_loader.CONFIG` fallback. `makeApp` stays
   `driver_classes=[PAL]` verbatim.
8. **Gate:** golden master + unit suite + import_smoke + K8 construction proof (bare
   interpreter: `PAL(config={})` spawns nothing, opens nothing; grep gate for
   `create_task|get_event_loop|Thread(` outside the worker-start method) — then commit +
   push as its own wave (P4 W6 cadence: **never batched** with other drivers).
9. **Station smoke (mandatory, §6.2)** before any production sequence relies on it.

---

## 6. Verification checklists

### 6.1 Linux (construction-proof) gates — all via `conda run -n helao`

- [ ] `python run_unit_tests.py` green.
- [ ] Golden-master trace diff (§4 scenarios a-i) — zero deltas (S1-S6).
- [ ] `test_pal_ioloop_c1_guard.py` still passes (B6) — adapted only for the job seam.
- [ ] `import_smoke` on `makeApp(pal_server)`: constructs identically; OpenAPI param shapes
      unchanged for all 17 (or 15, post-OQ-P2) endpoints.
- [ ] K8 proof: bare-interpreter construction spawns no tasks/threads, opens no SSH.
- [ ] Executor/split interplay probe (OQ-P3): fake-`Base` run with 2 splits; assert
      registry key stable, `stop_executor` reaches `_manual_stop` mid-job, final action
      finished exactly once.
- [ ] Grep gates: no `self.base` in `pal_driver.py`; no `actionservermodel` writes; `stop`
      returns `DriverResponse`.

### 6.2 Station smoke-test checklist (live PAL, deferred to first hardware session)

- [ ] `connect()` → SSH reachability + `get_status` idle; `disconnect()` clean.
- [ ] `PAL_deepclean` (no sample mutations) end-to-end — action finishes, HLO + act.yml in
      RUNS tree, syncer accepts.
- [ ] `PAL_archive` single run — vial assigned matches archive state; sample volumes/
      lineage in SAMPLE server DB diffed against a pre-migration reference run.
- [ ] Multi-microcam method (`PAL_ANEC_aliquot`) — split chain: N actions, parent/child
      uuids, one HLO row each; GC injector triggers observed (B5 timestamps sane).
- [ ] `totalruns > 1` with linear spacing — inter-run timing within tolerance.
- [ ] `/stop` mid-job between palactions — loop drains, action finishes with clean status.
- [ ] `/estop` mid-trigger-wait — executor stopped via framework, PAL binary killed,
      action estopped, **no fabricated artifacts**, server recovers after estop clear.
- [ ] Busy rejection: second method call during a job → `in_progress`, no artifact (B4).
- [ ] `kill_PAL` endpoint on both localhost and SSH paths.
- [ ] Hot-reload/shutdown while idle: safe-state ordering (no write-after-close).

---

## 7. Open questions (append to `.omc/plans/open-questions.md`)

- **OQ-P1 (busy semantics):** preserve legacy *reject-with-`in_progress`* (recommended —
  experiments are authored around it) or adopt framework queueing via `concurrent=False`?
  Design 1 keeps rejection in the endpoint guard either way; decide before Design 2.
- **OQ-P2 (dilute/autodilute):** endpoints reference non-existent driver methods
  (`pal_server.py:789/:830` vs commented `:2695/:2727`). Delete the endpoints, or restore
  the methods? Requires checking live station configs for `dilute`/`autodilute` cam keys
  (config content not reproducible here) — if unused anywhere, delete (D5 retire rule).
- **OQ-P3 (split × Executor):** confirm `exec_id`/executor-registry behavior across
  `active.split()` re-init (`base.py:1970`); if the registry loses the handle, `PALJobExec`
  needs a stable `exec_id` override (constructor arg exists, `executor.py:71-75`). Linux-
  answerable; must be settled during step 4 of the recipe.
- **OQ-P4 (sequencing vs archive hoist):** the approved archive-hoist plan's Phase-4 cutover
  (SAMPLE server) shares this driver. Recommended order: land this ABC migration first
  (shim call sites are preserved byte-for-byte by Design 1, so the hoist's contract is
  undisturbed), and schedule both station smoke tests in the same hardware session.
- **OQ-P5 (`IO_continue`):** write-only vestige of the disabled "block until first continue
  trigger" behavior (`:2177-2181`). Recommended: delete in recipe step 2; if the station
  team still wants first-continue blocking for some sequence, it belongs in
  `PALJobExec._poll` as an explicit option, not driver state.
- **OQ-P6 (repeat-reset quirk):** repeats within one microcam reset `action.samples_in/out`
  without splitting (`:529-533`), so the segment's act.yml records only the last repeat's
  samples while the HLO keeps every row. Preserve as-is for the migration (recommended —
  byte-for-byte rule); file separately whether repeats *should* split like `i > 0`
  microcams do.
- **OQ-P7 (trigger poller home, Design 2 only):** if/when Design 2 executes, do NI-DAQ
  trigger edges stay a per-job driver task (`arm_triggers()` CellIV-style) or become a
  `DriverPoller`? Edges are job-scoped and consumed as queues, not live values — the poller
  is likely the wrong home; decide with station timing data.
