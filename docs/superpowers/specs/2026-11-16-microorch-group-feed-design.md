# MicroOrch runners on the /group page — design

Date: 2026-11-16
Status: draft, awaiting review
Scope: sub-project 1 of 2. Sub-project 2 (a `/runners` Reflex page that lists,
parameterizes, launches and stops runners) has its own spec and depends on this one.

## Goal

A `MicroOrch` runner (`helao/core/runners/micro_orch.py`) shows up on the Reflex
`/group` page with the same graph, timelines, pulses and info box an orchestrator
gets. A config may have zero, one or several orchestrators and any number of
runners; the page shows one at a time, chosen by a selector, and draws the others
as peer nodes.

Success: launch `goldenreflex`, run `python -m helao.deploy.test.runners.simulatews_runner`
against it, and on `/group` the runner appears in the selector and as a peer node,
its view shows dispatch/finish pulses on SIM and ORCH and its experiment and action
strips, and its E-stop latches SIM.

## Why it does not work today

1. MicroOrch is RPC-only and serves no `/ws_orch`; `/group` reads only that stream.
2. `configure_group` takes the first `group: orchestrator` entry of the config; a
   runner is created inside a script and is never in the config.
3. `build_snapshot` reads `OrchHost` state (`globalstatusmodel`, the three deques,
   `active_sequence`); MicroOrch keeps `_pending`, `_latest` and `runs` instead.
4. Start/Stop/E-stop are orchestrator HTTP endpoints; MicroOrch has no dispatch loop.
5. The page holds one process-wide `_CFG`/`_FEED`, so a second orchestrator is
   only logged as ignored.

## Decisions

| # | Decision | Reason |
|---|----------|--------|
| D1 | Transport: the runner **pushes** frames over HTTP to the Reflex backend. | No listener or port on MicroOrch, which is designed to have no HTTP server. One channel carries registration, data and heartbeat. |
| D2 | Discovery: the first frame POST registers a runner. Runners launched by the sub-project 2 page and runners launched from a terminal use the same path. | One code path. The page that launches a runner learns of it the same way as of any other. |
| D3 | Runner controls on `/group`: E-stop and Clear E-stop only. No Start/Stop. | MicroOrch has no loop to start or stop. Clear is needed because an action server's estop latches. Stopping a page-launched runner belongs to sub-project 2. |
| D4 | Peers as nodes: while one feed is viewed, every other orchestrator and runner is drawn as a node; clicking it switches the view. | Requested. |
| D5 | A runner frame has the same keys as a `/ws_orch` frame. | The page's graph, strip, pulse and selection code is reused unchanged. |
| D6 | The info box works the same for every orchestrator and runner: strip clicks show the full object tree, node clicks show server config. | Requested. A view without a working info box is half a view. |
| D7 | Runner object details are pulled on click over the runner's existing ZeroMQ `RPCDispatcher` (new `get_object` method). Frames stay summaries. | Full experiment and action models are too large to push at 10 Hz, and the dispatcher is already bound and reachable (action servers call it). No new port. |
| D8 | Server config shown in the info box is masked by key name before display. | Config params can hold credentials; the page must not render them. |

## Runner side

### State MicroOrch keeps

New attributes, set and cleared by `run_sequence` and `run_experiment`:

- `active_sequence: Optional[Sequence]`, `last_sequence`
- `active_experiment: Optional[Experiment]`, `last_experiment`
- `finished_experiments: list[Experiment]` for the current sequence (the
  experiment strip's done rows; windowed like `EXP_DONE_WINDOW`)
- `planned_actions: list[Action]` of the active experiment (queued rows of the
  action strip; staged actions carry their uuid before dispatch)
- `queued_experiments: list` of the active sequence not yet run

Events: `dispatch_action` appends a `dispatch` event and `_retire_locked`
appends a `finish` event (same dict shape as `OrchGraphFeed.diff_events`:
`kind, server, action_uuid, action_name, status, t`). No diffing is needed
because both sites already exist.

A bare `run_action` outside any experiment appears only as a busy node and a
pulse; it is not drawn on the strips.

### `build_runner_snapshot`

Lives in `helao/core/models/group_snapshot.py` beside `build_snapshot`, returns
the same keys:

- `loop_state`: `started` while a run call is in progress, else `stopped`;
  `estopped` once any attached server reports estop. `orch_state` maps to the
  page's `ORCH_TO_GROUP` keys: `busy` while running, `idle` otherwise,
  `estopped` as above. `loop_intent`: `none`. `closing_out`: `False`.
- `n_sequences_queued`: `0` (a runner has no queue).
- `seq`, `experiments`, `n_done`, `n_queued`, `act_exp`, `actions`: from the
  state above, with the same windows and row fields as the orchestrator
  builders. Queued experiment rows carry `qidx` = their index (the page's
  row ordinals need it) but no uuid; the page never sends a queue fetch for a
  runner, so such a row's info box says "not found".
- `servers`: the servers the runner has attached to (`_subscribed`) plus any in
  `_pending_meta`, each row `{key, status, active_action, host, port}`. `host`
  and `port` are new, optional fields, used by the page for runner E-stop.
  Status: `estop` from the latest status dump, `busy` while it has a pending
  action, `error` after an error finish until a clean one, else `idle`.
- `orch_action`: `None`.
- `kind`: `"runner"` (new field; absent on orchestrator frames, which read as
  `"orchestrator"`), plus `instance` (a uuid fixed per MicroOrch instance).
- `config`: the runner's own settings, shown when its node is clicked:
  `server_key`, `host`, `port`, `rpc_port` (`derive_rpc_port(port)`),
  `default_timeout`, `finished_timeout`, `poll_interval`, `group_urls`, the
  names of loaded experiment and sequence pre-finish hooks, and the server keys
  of `world_cfg["servers"]`. Small and static, so it rides in every frame;
  the registry keeps only the latest.

### `get_object` RPC

`MicroOrch.__init__` registers one more method on its dispatcher, next to
`update_status`: `get_object(kind, uuid) -> dict | None`, `kind` one of
`sequence | experiment | action`. It looks in `active_*`/`last_*`,
`finished_experiments`, `planned_actions`, and `_latest` (actions), and
returns `as_dict()` of the match or `None`. Read-only; it never awaits a run
lock.

### `RunnerGraphFeed`

New module `helao/core/runners/runner_feed.py`. Started by `MicroOrch.start()`
as a task, cancelled by `stop()`.

- Tick 100 ms; a frame is built only when a cheap fingerprint changed or a
  2 s heartbeat is due (same rule as `OrchGraphFeed.step`).
- Each frame is POSTed with `httpx.AsyncClient` to
  `{url}/runners/{server_key}/frame` for every target URL.
- Target URLs: the `reflex:` entries of `world_cfg["servers"]`, backend at
  `http://{host}:{port + 1}`. A new constructor argument
  `group_urls: Optional[list[str]]` overrides them; `[]` turns the feed off.
  With no target the task is not started.
- A failed POST is logged once per target until it succeeds again, and never
  raises into a run. Each POST has a short timeout (1 s) so a dead page cannot
  slow the tick.
- `409` from a target means another live instance holds the key: log a warning
  naming the key and stop posting to that target.
- `stop()` sends `DELETE {url}/runners/{server_key}?instance=<uuid>` to each
  target, best-effort.

## Page side

### Feeds

`group.py`'s `_CFG`/`_FEED` become a module-level registry
`FEEDS: dict[str, FeedEntry]`, where `FeedEntry` holds `kind`, `ingest`, and
for orchestrators `host`/`port`.

- `configure_group(world_cfg)` registers one `WsIngest` per `group: orchestrator`
  entry (no longer only the first). `start_feed`/`stop_feed` start and stop all of
  them.
- `PushIngest` (new, in `ingest.py`) exposes the attributes `new_frames`,
  `latest_frame` and `stream_lost` read from `WsIngest`: `raw`, `n_batches`,
  `status.message_count`, and the last-message time. `put(frame)` appends one
  batch.

### Registration routes

On the FastAPI app `app.py` already passes as `api_transformer`:

- `POST /runners/{key}/frame`, JSON body = one runner frame.
  - Unknown key: create a `PushIngest`, register it, store `instance`.
  - Known key, same `instance`: append.
  - Known key, different `instance`: if the entry is lost (no frame for more
    than `STALE_S`), replace it; else `409`.
  - A key equal to any server key in the page's config: `409` (node keys on
    the graph must be unique).
- `DELETE /runners/{key}?instance=...`: mark the entry ended (it reads as lost
  at once). Wrong instance: `404`.
- An ended or lost runner entry is removed 10 min after its last frame. The
  sweep runs on the existing 2 Hz tick; no extra task.
- The routes do no authentication, like every other helao endpoint.

### Selection

- `GroupState.selected: str` (per session). Default: the first config
  orchestrator, else the first runner, else the existing `NO_ORCH_NOTE`
  (reworded to say no orchestrator or runner is present).
- A dropdown above the graph lists every feed, orchestrators first, each with
  a live or unreachable badge. Changing it resets the page's frame cursor and
  selection, the same as a fresh page load.
- If the selected runner is removed, selection falls back to the default.

### Peer nodes

`group_layout(orch_key, server_keys, peer_keys=())` places peers on the centre
row: x alternating -0.55, +0.55, -0.85, +0.85, y = 0, no edges. Each peer's
colour is its own feed's status (`idle`/`busy`/`error`/`estop`/`unreachable`
from its latest frame). A click on a peer node sets `selected`. The layout carries
a `ponytail:` comment: more than 4 peers overlap; a second row is the upgrade.

### Controls

- Selected orchestrator: the four existing buttons, sent to that orchestrator's
  host/port (`_control_call` takes the feed entry instead of `_CFG`).
- Selected runner: E-stop and Clear E-stop only. Each POSTs
  `/{server}/estop?switch=true|false` to every row of the frame's `servers` that
  has `host`/`port`, in parallel; a failure names the server in the error toast.
  An idle action server's `/estop` sets its latch without sending a status
  update, so a runner frame may never show the estop. The page therefore keeps
  a process-wide latch per runner key, set when every estop call succeeded and
  cleared when every clear call succeeded; the runner's `estopped` flag is the
  frame's `_estopped` rule OR that latch. A runner button's pending state ends
  when its HTTP calls return, not on frame confirmation.

### Info box

The info box shows the last thing clicked: a strip item or a graph node. It
works the same whichever feed is selected.

**Strip item (experiment or action)** — the full object tree via `tree_for`,
as today. Source by feed kind:

- Orchestrator: a `RemoteBackend` built for that orchestrator. `session_backend`
  is keyed by `(token, orch_key)` instead of `token`, and `make_backend` gets
  the `orch_key` explicitly, so every config orchestrator has one. The `_backend`
  mismatch check stays, comparing against the selected key.
- Runner: `RPCClient(host, rpc_port).call("get_object", ...)` with `host` and
  `rpc_port` from the frame's `config`. One client per runner, cached in its
  registry entry and closed when the entry is removed.
- `fetched_info`'s not-found and queue-moved notes apply to both.

**Action server node** — header is the server key; body has two parts:

1. *Config*: the server's entry from the page's own `world_cfg["servers"]`.
   A server known only from a runner frame (not in the page's config) is
   fetched once with `POST /{server}/get_config` from the frame's host/port and
   its `servers[key]` entry kept. Masked per D8 before display.
2. *Endpoints*: an expandable list (collapsed by default, one row per endpoint)
   from `POST /{server}/get_status`. Each row shows the endpoint name, its
   status and the number of non-idle actions, i.e. `len(active_dict)`. Status:
   `estop` if the server's `estop` is set; `busy` when the count is above 0;
   otherwise the status of the newest finished action (`finished`, or an error
   status shown in the error colour); `idle` when it has never run. Expanding a
   row lists its active actions (name, uuid, start time). The driver status
   (`_driver_status`) is shown once above the list.

   The list refreshes when the node's status or `active_action` in the frame
   changes, plus a manual refresh button; never on a timer. The fetch runs in
   the background event, off the 2 Hz tick.

**Orchestrator node** — header is the orchestrator key; body is its entry from
the page's `world_cfg["servers"]`, masked per D8. No endpoint list.

**Runner node** — header is the runner key; body is the frame's `config`
(above), masked per D8. No endpoint list.

Clicking a peer node both switches the view (D4) and shows that node's config.

**Masking (D8)** — a new helper `mask_secrets(cfg: dict) -> dict` in
`helao/ui/shared/` replaces the value of any key, at any depth, whose name
matches `(?i)(secret|password|passwd|token|api_key|access_key|private_key|credential)`
with `"***"`. It returns a copy and never mutates the config. `server_key` and
other keys that merely end in `key` are not matched.

## Risks

- E-stop on a runner's servers also stops orchestrator work on any server they
  share. That is the intended meaning of an E-stop.
- Two scripts constructing MicroOrch with the same `server_key`: the second
  gets `409` and runs without a feed. The warning names the key.
- A Reflex page that restarts loses the registry; live runners re-register on
  their next frame (within 2 s, the heartbeat).
- `/get_status` returns every endpoint's `nonactive_dict`, which is unbounded
  (`max_uuids = None`) and can be large on a long-running server. It is fetched
  only on a node click or a status change of that node, never per tick; the page
  keeps only names, counts and the newest finished status from it.
- Masking is by key name only. A secret stored under an innocuous key name is
  shown. Keeping secrets out of config (as the sync driver does) remains the
  real fix.
- `get_object` runs on the runner's event loop. It only reads, so a slow
  run is not delayed, but a runner whose loop is blocked answers late; the click
  then times out (2 s) and shows "not found".

## Testing

Unit (pytest, run by `run_tests.py`):

- `build_runner_snapshot` on a MicroOrch driven by a fake RPC client through one
  experiment: keys equal `build_snapshot`'s plus `kind`/`instance`; strip rows
  move queued → active → done; an error finish makes the server `error`.
- `RunnerGraphFeed`: heartbeat and change-only framing; POST failure does not
  raise; `409` stops posting; no targets means no task.
- Registry routes (FastAPI `TestClient`): register, append, `409` on a live
  duplicate, replace a lost one, `DELETE` with right and wrong instance, removal
  after 10 min with an injected clock.
- `group_layout` with peers; selector fallback when the selected runner is removed;
  the existing `/group` render functions accept a runner frame.
- `get_object` returns the active, finished and planned objects by uuid, and
  `None` for an unknown uuid.
- Endpoint rows from a recorded `/get_status` dump: counts, `busy`/`idle`/
  finished/error/`estop` status, never-run endpoints listed as `idle`.
- `mask_secrets`: nested keys masked, `server_key` kept, input unchanged.
- Session backends keyed per orchestrator: two orchestrators, two backends.
- Every test must fail against a deliberate mutation of the code it covers
  before it is accepted.

Integration (manual, headless Playwright from the scratch venv):

- `./helao.sh goldenreflex`, then the simulatews runner. Check: runner listed and
  drawn as a peer; click switches; pulses on SIM and ORCH; strips fill; E-stop
  latches SIM; Clear E-stop releases it; killing the runner turns it
  unreachable within 5 s.
- Info box, with ORCH and with the runner selected: clicking an action strip item
  shows its tree; clicking SIM shows its config and endpoints, with
  `acquire_data` counting 1 while it runs; clicking the runner node shows its
  config; clicking ORCH shows ORCH's config.

## Out of scope

- Start/Stop of a runner from `/group`; launching runners (sub-project 2).
- Queued sequences on a runner (it has none).
- Live (timer-driven) endpoint refresh in the info box.
