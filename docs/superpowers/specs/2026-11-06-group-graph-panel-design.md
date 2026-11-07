# Server-group graph and sequence timeline page (`/group`) — design

Date: 2026-11-06
Status: approved in brainstorming, pending written-spec review

## Goal

Give an operator one page that shows, at a glance, the state of a running
HELAO server group:

1. **Network graph.** The orchestrator node sits in the centre, with action
   servers above and below it. A curve joins each action server to the
   orchestrator. Node and curve colour follows each server's state
   (idle/busy/error/estop/unreachable). A triangle travels along a curve when
   an action is dispatched and again when it finishes.
2. **Timelines.** The active sequence's experiment queue and the current
   experiment's action queue are drawn as two ordinal bar strips with start and
   end times. The action strip clears when a new experiment starts.
3. **Header and controls.** The running sequence's name, start time and uuid,
   the loop and orch state, and Start / Stop / E-stop buttons.
4. **Info box.** Clicking a timeline segment shows that experiment's or
   action's full metadata as the same nested tree that the operator queue and
   history tables show.

Success: an operator can tell which server is busy, where the sequence is, and
when each step ran, without opening the operator page. The operator can also
start, stop or e-stop the loop from this page.

## Decisions taken in brainstorming

| Topic | Decision |
|---|---|
| State source | New orchestrator push stream `/ws_orch`. Nothing pushes orch state today: action servers POST `/update_status`, which is folded into `GlobalStatusModel` and never re-broadcast. |
| Stream shape | A full compact snapshot each frame, sent only on change and coalesced to at most 10 Hz, plus the dispatch/finish events since the previous frame. The client is stateless, so a reconnect or a dropped frame heals itself. |
| Timeline form | Ordinal bar strip: equal-width segments, partition lines, one label per segment, colour by state, progressive fill on the active segment. |
| Placement | Shared Reflex page `/group`, added automatically when the group config has an orchestrator. |
| Node label | Drawn **on** the node (overlay). |
| Controls | Start, Stop, E-stop / Clear E-stop. |

## Architecture

```
action servers --POST /update_status--> OrchHost (state unchanged)
                                           ^ read-only, every 100 ms
                                OrchGraphFeed (new task)
                                builds GroupSnapshot when its fingerprint changes
                                           | orch_graph_q
                                           v
                                WsPublisher -> /ws_orch (wire_dumps: msgpack+zstd)
                                           |
Reflex server: GroupState <-- WsSubscriber (existing ingest path)
               rx.moment tick: 60 Hz while a pulse is alive, 2 Hz otherwise
               pull() -> 3 xy charts: network graph | experiment strip | action strip
               buttons / info-box clicks -> RemoteBackend (HTTP, as the operator page does)
```

Three WebGL contexts per open page. The 16-context Chrome cap is described in
`helao/ui/reflex/CLAUDE.md`.

## Components

### 1. `GroupSnapshot` — `helao/core/models/group_snapshot.py`

A msgspec Struct (or a plain dict built by one function; the plan chooses
whichever `wire_dumps` already encodes without special cases).

```
seq_no: int                       # increases on every frame, heartbeats included
t: float                          # epoch seconds at build time
orch_state: str                   # OrchStatus value
loop_state: str                   # LoopStatus value
loop_intent: str                  # LoopIntent value
closing_out: bool                 # loop_state == stopped and active_experiment is not None
n_sequences_queued: int
seq: {uuid, name, label, t_start} | None     # t_start from sequence_timestamp
servers: [{key, status, active_action}]       # status in idle|busy|error|estop|unreachable
experiments: [{uuid, name, state, t_start, t_end}]   # windowed, see below
n_done: int; n_queued: int        # experiment totals beyond the window
actions: [{uuid, name, server, state, t_start, t_end}]  # current experiment only
events: [{kind: dispatch|finish, server, action_uuid, action_name, status, t}]
```

- `state` takes one of `queued | active | done | error`.
- Times are epoch seconds, or `None` until known.
  - Experiments use `experiment_timestamp` / `experiment_finished_timestamp`.
  - Actions use `action_timestamp` / `action_finished_timestamp`.
  - **To verify in the plan:** `action_timestamp` must be set at dispatch or at
    server start, not when the experiment is unpacked. If it is set at unpack,
    `t_start` is instead the feed's first observation of the uuid in
    `active_dict`.
- **Experiment window:** the last 20 done, the active one, and the next 50
  queued. `n_done` and `n_queued` carry the totals, because plate scans can
  queue thousands of experiments.
- **Server list:** every config server with `group: action`, merged with the
  orchestrator's `globalstatusmodel.server_dict`.
  - `unreachable` comes from the ping loop's `status_summary`
    `("unreachable", "unknown")`.
  - `busy` means the server has at least one uuid in `active_dict`.
  - `estop` comes from `ActionServerModel.estop`.
  - `error` means the server's last finish carried an error status.

### 2. `OrchGraphFeed` — `helao/hexagon/app/orch_graph_feed.py`

One asyncio task, started and stopped alongside the orchestrator's other
monitors (`orch_monitor.py` pattern).

- **No hooks in the dispatch path.** `orch_dispatch.py`, `orch_effects.py` and
  `ingestion.py` are not modified, so none of the four dispatch-loop traps in
  `helao/hexagon/app/CLAUDE.md` is touched. The feed only reads state. It never
  takes `aiolock` and never mutates.
- **Every 100 ms** it computes a cheap fingerprint from:
  - `loop_state`, `loop_intent`, `orch_state`
  - the `status_summary` items, `counter_dispatched_actions`
  - the uuid sets of `active_dict` and `nonactive_dict`
  - the active sequence and experiment uuids, and the deque lengths

  When the fingerprint is unchanged, nothing is sent.
- **Heartbeat:** a frame is sent every 2 s even when idle, so the client can
  detect a stale stream.
- **Events by diff:** a uuid that newly appears in `active_dict` yields
  `dispatch`. A uuid that leaves `active_dict` for `nonactive_dict` yields
  `finish` with its `HloStatus`, and an error status renders red.
- **`closing_out`** is explicit, because `loop_state == stopped` is published
  while the last experiment is still finishing (trap 3 in the hexagon/app
  CLAUDE.md).
- **Publishing** puts a *new* snapshot object on each publish (the
  `WsPublisher` identity-cache rule) and keeps the latest snapshot. On connect,
  the `/ws_orch` route sends that cached snapshot first.
- **Isolation:** the iteration body is wrapped in `try/except`. An exception is
  logged with `LOGGER.exception`, that frame is skipped, and the next tick
  retries. Nothing raises into the orchestrator.

### 3. Orchestrator routes — `helao/hexagon/app/orch_host.py`

- `/ws_orch` websocket, registered in `_register_orch_ws_routes` from a
  `WsPublisher` over `orch_graph_q`.
- `POST /get_object` with params `kind` (`experiment` | `action`) and `uuid`.
  - Searches, in order:
    1. the active experiment and its `dispatched_actions`
    2. the action and experiment deques
    3. the experiment and action history
  - Returns the model's `as_dict()`, or `null` when not found.
  - Read-only and takes no lock.

### 4. `NetGraph` — `helao/ui/reflex/netgraph.py`

Pure Python with no Reflex state. It produces xy marks for `plots.chart(...)`.

```python
g = NetGraph(height_px=360, domain=((-1, 1), (-1, 1)))
g.add_node(key, x, y, text="", color=..., size_px=28)
g.add_edge(edge_id, src_key, dst_key, text="", color=...)
g.add_arrowhead(edge_id, at="dst")          # or "src"
g.set_node_color(key, c);  g.set_node_text(key, s)
g.set_edge_color(edge_id, c); g.set_edge_text(edge_id, s)
g.pulse(edge_id, direction="fwd", t0=..., duration=0.6, color=...)   # or "rev"
g.marks(now) -> list                         # called from pull()
group_layout(orch_key, server_keys) -> dict[str, tuple[float, float]]
```

Geometry (markers cannot rotate, so every curve ends vertically):

- **Ports:** an edge leaves its source at the node's top or bottom, whichever
  faces the destination, and enters the destination the same way.
- **Curve:** a cubic Bézier `P0=port_a, P1=(xa, ya±d), P2=(xb, yb∓d),
  P3=port_b`, where `d = 0.5·|Δy|`. Both end tangents are vertical, so a
  `triangle` (up) or `triangle_down` arrowhead sits flush at either end. Each
  curve is sampled at 24 points into one `line` trace.
- **Fan-out:** when several edges end on one node, their ports are spread
  across ±0.7 r of its width.
- **Fixed view:** marker sizes are in px, ports in data units. The chart
  therefore has a fixed domain and pixel height, and pan/zoom are off.
  - The px-to-data conversion uses that fixed scale.
  - Axes and grid are hidden.
  - **To verify:** the plan opens with an `xy` API probe of the scatter
    `symbol=` kwarg, axis hiding, per-trace line colour and width, and text
    z-order over markers.
- **Text:**
  - The node label is centred on the node, drawn over the marker.
  - The secondary text (active action name) sits just outside the node, on
    the side away from the orchestrator.
  - Edge text sits at the curve midpoint, offset 6 px.
- **Pulse:** the position is the curve point at arc-length fraction
  `s = (now − t0)/duration`, read from a precomputed arc-length table.
  - Each curve is monotone in y, so the symbol is fixed per direction:
    `triangle` when moving up, `triangle_down` when moving down.
  - All live pulses share one scatter trace and are dropped at `s ≥ 1`.
- **Layout:** the orchestrator sits at (0, 0). Action servers are sorted by
  key and alternate between y = +0.7 and y = −0.7, evenly spaced in x. Above 8
  per row, a second band is added (±0.4 / ±0.9).
- **Group meaning:**
  - Each edge joins the orchestrator and one action server.
  - A `dispatch` event fires a forward pulse (orch to server) in the accent
    colour.
  - A `finish` event fires a reverse pulse in the done or error colour.
  - Edge colour follows the server state, and a busy edge is drawn thicker.

### 5. `timeline_strip` — `helao/ui/reflex/timeline_strip.py`

Pure Python. It builds the marks for one strip from a list of items.

- **Shapes:**
  - Each item is one equal-width segment (a filled `x_band` or rectangle),
    with a `vline` partition between segments.
  - A `+N` ellipsis segment marks each cut end of the window.
- **Colour** by `state`. The selected segment gets an outline.
- **Active progress fill:**
  - With a known expected duration, the fill is a band from the segment start
    to `elapsed/expected`.
  - Without one, it is a sawtooth sweep at 2 Hz.
- **Labels:** the name on line 1, the times on line 2.
  - done: `HH:MM:SS–HH:MM:SS`
  - active: `HH:MM:SS– (elapsed)`, with elapsed refreshed on the 2 Hz tick
  - queued: no time
- **Times** are in station local time. The date is prefixed when the start
  falls on a day other than today.
- **Narrow segments:** below about 90 px, only the start time is shown, and the
  info box carries the rest.
- **Clicks:** `xy:click` maps through `on_select` (needs `click=True`) to a
  segment index, then to the item's `(kind, uuid)`.

### 6. Reflex page — `helao/ui/reflex/group.py`, registered in `app.py`

```
┌──────────────────────────────────────────────────────────────────────────┐
│ SEQ <name>   started <date time>   uuid <short>… [copy]                  │
│ loop: <state>  orch: <state>  [closing out]   [Start] [Stop] [E-stop]    │
├───────────────────────────────────────────┬──────────────────────────────┤
│          network graph                    │ INFO                         │
├───────────────────────────────────────────┤ nested <details> tree of     │
│ EXP strip                                 │ the selected experiment or   │
│ ACT strip                                 │ action                       │
└───────────────────────────────────────────┴──────────────────────────────┘
```

- **Registration:** the route is always registered. A config with no
  orchestrator renders a "no orchestrator" note there; otherwise the
  orchestrator's host and port come from the config.
  - `GroupState` is a plain `rx.State`, because there is one page per
    orchestrator.
  - Its classes are created **before** `add_page`, because the page callable is
    lazy and never runs under `--backend-only` (`helao/ui/reflex/CLAUDE.md`).
  - Refreshes are driven by `rx.moment`, never a server-side loop.
- **Header:**
  - The sequence name and start time.
  - The uuid shown through `truncate_uuid` (`object_tree.py`), with the full
    uuid on hover and a copy button.
  - Badges for `loop_state`, `orch_state` and closing out.
  - With no active sequence, the header reads "idle — no active sequence".
  - After the last experiment finishes the orchestrator empties
    `active_sequence` within one tick, so the feed falls back to
    `last_sequence`: the header keeps the sequence name with a "finished" badge,
    the final experiment is framed as `done`, and no queued rows are listed.
    "idle" appears only when there is no sequence at all.
- **Buttons** call the orchestrator's endpoints directly through
  `async_private_dispatcher` with the configured orchestrator's host and port,
  not through `RemoteBackend`: constructing one runs `import_autolibs`
  synchronously, which would block the first click (E-stop included). A call
  the orchestrator accepts but ignores (`/estop_orch` acts only while the loop
  is started; a refused `/start` returns `{}`) is not an error on the wire, so
  a pending button that the next snapshots never confirm within 10 s shows
  "<button> not confirmed by the orchestrator" in the inline error line. The
  info box keeps using the operator's `RemoteBackend` (`session_backend(token)`);
  no new wire protocol.

  | Button | Enabled when | Calls |
  |---|---|---|
  | Start | `loop_state != started`, not estopped, `n_sequences_queued > 0` (or an active sequence with queued experiments) | `start()` |
  | Stop | `loop_state == started` | `stop()` (`reset_run_id=False`) |
  | E-stop | always, unless estopped | `estop()` |
  | Clear E-stop | in place of E-stop while estopped | `clear_estop()` |

  - None of the buttons has a confirm dialog, the same as the operator page.
  - A button shows a spinner until the next snapshot reflects the change.
  - A failed call shows its error text inline.
- **Info box:**
  - **Fetch:** a segment click calls `/get_object(kind, uuid)` on demand. It is
    never cached, so the last response wins, the same as `select_queue_row`.
  - **Rendering:** `object_tree.tree_for`.
  - **Pane reuse:** `_tree_pane` moves from `operator.py` into a shared module
    that both pages import. That move is the only change to `operator.py`.
  - **Stale selection:** when the selected item leaves the window, the box
    reads "selection no longer in view".
- **Connection loss:** the existing `WsSubscriber` reconnects. The page counts
  the stream as lost while disconnected or when no frame has arrived for over
  5 s. Every node then turns `GROUP_UNREACHABLE`, a banner reads "orchestrator
  unreachable", and the buttons are disabled.
- **Older orchestrator:** detected by heuristic, not by parsing a 404. If no
  frame arrives within 5 s while the orchestrator still answers over HTTP, the
  page shows "orchestrator lacks /ws_orch — update the orchestrator".
- **Frames and selection:**
  - Frames are watermarked by local arrival order, not by `seq_no`, so an
    orchestrator restart cannot freeze the page.
  - E-stop is never gated by another call's pending state, and stays enabled
    when the stream is lost.
  - A selection is identified by the sequence ordinal of the item, so it
    survives window shifts.
- **Unknown status:** an unknown status string uses the idle colour and shows
  the raw text on the node.

### 7. Palette — `helao/ui/shared/palette.py`

New semantic names, each mapped to existing Tailwind entries:

| Name | Colour |
|---|---|
| `GROUP_IDLE` | slate |
| `GROUP_BUSY` | sky |
| `GROUP_DONE` | emerald |
| `GROUP_ERROR` | red |
| `GROUP_ESTOP` | red-900 |
| `GROUP_UNREACHABLE` | amber |
| `GROUP_QUEUED` | muted slate |
| `GROUP_PULSE_DISPATCH` | accent |

No colour is written anywhere else. `test_palette.py` enforces this.

## Testing

- `helao/ui/reflex` tests:
  - `test_netgraph.py`:
    - The port side is chosen by relative y.
    - Bézier end tangents are vertical.
    - Arrowheads are `triangle` vs `triangle_down` by direction.
    - Pulse positions are correct at s = 0, 0.5 and 1, and the pulse expires
      at s ≥ 1.
    - Fan-out ports are distinct.
    - The layout alternates rows and adds a second band.
  - `test_timeline_strip.py`:
    - Label formats: done, active with elapsed, queued, narrow start-only, and
      the cross-day date prefix.
    - The `+N` window segments are drawn.
    - The click index maps to the right uuid.
- `helao/hexagon/tests/test_orch_graph_feed.py`, against a fake orch:
  - No frame is sent when the state is unchanged, and the heartbeat still
    arrives.
  - Dispatch and finish events are derived correctly, including an errored
    finish.
  - The window bounds and `n_done`/`n_queued` are correct.
  - `closing_out` is set correctly.
  - An exception in the build does not kill the task.
- `/get_object`: each search tier (active, queue, history) is found, and a miss
  returns `null`.
- **Live test** on a `test`-deployment simulator group:
  - Subscribe to `/ws_orch` and run a short sequence.
  - Assert one dispatch and one finish event per action.
  - Assert the experiment states run queued → active → done.
  - Assert Start/Stop through the page's backend calls change `loop_state`.
- **Mutation check:** each new feed test is checked against a deliberately
  broken implementation, so none of them passes vacuously.
- **UI check:** a headless Playwright check of `/group` (scratch venv). The
  existing `test_palette.py` gate must still pass.

## Out of scope

- Skip and queue editing on `/group`.
- History replay.
- More than one orchestrator per page.
- A Bokeh version.
- Pan/zoom of the graph.

## Rollout

The change is in the parent repo only: the orchestrator host, the Reflex UI and
the shared models. No deployment code changes. Stations get it with a normal
pull and restart of the orchestrator and the Reflex server. An orchestrator
without `/ws_orch` degrades to the "update the orchestrator" message; nothing
else breaks.
