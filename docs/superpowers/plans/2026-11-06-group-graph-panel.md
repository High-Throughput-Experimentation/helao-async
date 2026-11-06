# Server-group graph and sequence timeline page (`/group`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an orchestrator push stream `/ws_orch` and a Reflex page `/group` that shows the server group as a live network graph, two ordinal timeline strips (experiments and actions), a header with Start/Stop/E-stop, and an info box with the clicked item's full tree.

**Architecture:** A read-only `OrchGraphFeed` task inside `OrchHost` polls orchestrator state every 100 ms, builds a plain-dict `GroupSnapshot` when a fingerprint changes (or every 2 s as a heartbeat), and publishes it through a `WsPublisher` on `/ws_orch`. The Reflex server subscribes once per process (`WsIngest`). A plain `rx.State` (`GroupState`) ticks from `rx.moment` (60 Hz while a pulse is alive, 2 Hz otherwise) and turns the latest frames into three xy charts. The charts are built by two pure modules, `netgraph.py` and `timeline_strip.py`, which emit plain mark dicts; `plots.marks_chart` is the only place those become xy calls, because only `plots.py` and `xy_component.py` may import `xy`. Buttons and info-box fetches go over HTTP through the operator's `RemoteBackend`.

**Tech Stack:** Python 3.14 (`helao` conda env), FastAPI, msgspec+zstd wire frames (`ws_utils.wire_dumps`), Reflex 0.9.7, xy 0.0.8, pytest + pytest-asyncio, Playwright 1.62.0 (scratch venv only).

**Spec:** `docs/superpowers/specs/2026-11-06-group-graph-panel-design.md`

## Global Constraints

- Python: `PY=/home/dan/miniforge3/envs/helao/bin/python`. Every test command runs from the repo root as `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=. $PY -m pytest <file> -q`.
- "No hooks in the dispatch path. `orch_dispatch.py`, `orch_effects.py` and `ingestion.py` are not modified." The feed "only reads state. It never takes `aiolock` and never mutates."
- "Nothing raises into the orchestrator." Every feed iteration is wrapped in `try/except` with `LOGGER.exception`.
- Feed cadence: fingerprint "Every 100 ms", "Heartbeat: a frame is sent every 2 s even when idle", frames "coalesced to at most 10 Hz".
- "Experiment window: the last 20 done, the active one, and the next 50 queued." `n_done`/`n_queued` carry the totals beyond the window.
- `WsPublisher` rule: put a *new* object on every publish.
- Only `helao/ui/reflex/plots.py` and `helao/ui/reflex/xy_component.py` may `import xy` (`test_only_plots_module_imports_xy`).
- "No colour is written anywhere else" than `helao/ui/shared/palette.py`. `helao/core/tests/test_palette.py` enforces it.
- Reflex: state classes exist before `add_page`; refresh only from `rx.moment`, never a server-side loop; a handler bound to both a button and `rx.moment` gets its argument explicitly (`on_click=State.handler("")`).
- WebGL budget: three charts on `/group`.
- Parent repo is public: name only the `hte` and `test` deployments.
- No new dependency. `/group` changes only the parent repo.
- Every feed and snapshot test carries a mutation-check step (break the code, see the test fail, restore).
- Playwright runs in a scratch venv (`playwright==1.62.0`), never in the `helao` env.
- `conda run python - <<EOF` silently runs nothing: probes are script files run with `$PY -I <file>`.
- Background jobs (the Task 9 group launch) end on a marker file watched by a *separate* command; never `pgrep -f`/`pkill -f`; kill only by PID.
- `black` (line length 88) on the changed files is the last step before the final commit.

## Review Focus

1. **Orchestrator restart while `/group` is open.** `seq_no` restarts at 1, so a page that only accepts `seq_no > last` would freeze forever. Expected: the page resets its cursor. Pinned by `test_new_frames_resets_after_an_orchestrator_restart` (Task 8).
2. **An action that starts and finishes between two 100 ms feed ticks.** It never appears in `active_dict`. Expected: one `dispatch` then one `finish` event. Pinned by `test_an_action_seen_only_finished_still_yields_dispatch_then_finish` (Task 4).
3. **Clicking a queued experiment.** Queued experiments have `experiment_uuid=None` until `init_exp` runs at activation (`premodels.py:232`). Expected: the info box still fills, through `get_queue_object(kind, qidx)`. Pinned by `test_object_request_falls_back_to_the_queue_index` (Task 8).
4. **A driver status that is a dict.** `status_summary` values are `(status_str, driver_status)` and `driver_status` may be unhashable. Expected: the fingerprint does not raise. Pinned by `test_unhashable_driver_status_does_not_break_the_fingerprint` (Task 4).
5. **Feed starting on an orchestrator that already has finished actions.** Pre-existing `nonactive_dict` entries must not replay as a burst of pulses. Expected: the first frame carries no events. Pinned by `test_first_frame_primes_without_replaying_old_finishes` (Task 4).

---

## File map

| File | Status | Responsibility |
|---|---|---|
| `helao/ui/shared/palette.py` | modify | `GROUP_*` colours, badge classes, `/group` tint, `pink-50` |
| `helao/core/models/group_snapshot.py` | create | pure snapshot builder over a read-only orchestrator |
| `helao/hexagon/app/orch_graph_feed.py` | create | 100 ms read-only feed task, event diff, heartbeat |
| `helao/hexagon/app/orch_payloads.py` | modify | `_object_payload` for `/get_object` |
| `helao/hexagon/app/orch_host.py` | modify | queue, feed task, `/ws_orch`, `/get_object` |
| `helao/hexagon/tests/checklists/orch_openapi.json` | modify | hand-added `/get_object` entry (never regenerate) |
| `helao/ui/reflex/plots.py` | modify | `marks_chart`: mark dicts to xy |
| `helao/ui/reflex/netgraph.py` | create | pure graph geometry and marks |
| `helao/ui/reflex/timeline_strip.py` | create | pure strip marks, labels, click mapping |
| `helao/ui/reflex/tree_pane.py` | create | `_tree_pane` moved out of `operator.py` |
| `helao/ui/reflex/operator.py` | modify | import `tree_pane` (only change) |
| `helao/ui/shared/operator/orch_backend.py` | modify | `get_object`, `strict` on control calls |
| `helao/ui/reflex/ingest.py` | modify | `ws_orch` normalizer |
| `helao/ui/reflex/group.py` | create | `GroupState`, page, pure helpers |
| `helao/ui/reflex/app.py` | modify | `/group` route, nav link, feed lifespan |
| tests | create | see each task |

---

### Task 1: xy API probe for the graph and strip marks

The probe pins every xy fact later tasks rely on. Some were checked while planning (xy 0.0.8); the probe re-asserts them so a version bump fails loudly here, not in a blank chart.

**Files:**
- Create (scratch, not committed): `/tmp/claude-1000/group-probe/probe_group_xy.py`
- Modify: `docs/superpowers/notes/2026-08-01-xy-api-probe.md` (append a section)

**Interfaces:**
- Consumes: nothing.
- Produces: the recorded facts that Task 5 encodes in `plots.marks_chart`:
  - `symbol="triangle"` / `"triangle_down"` (underscore; `"triangle-down"` raises `ValueError`)
  - a per-point colour list of hex strings encodes as `direct_rgba` column data
  - an **empty** colour list silently becomes a `continuous`/viridis colour, so an empty trace needs an off-domain placeholder point
  - a per-point **size array** is mapped to `range_px (2, 18)`, so sizes must be scalar per trace
  - `x_axis(show=False, grid=False, domain=...)` hides the axis
  - `xy.chart(..., pan=False, zoom=False, click=True)`
  - `xy.text(x, y, value, dx=, dy=, color=, anchor="middle")`
  - `x_band` → annotation kind `band`, `vline` → annotation kind `rule`
  - a chart with only annotations has zero traces

- [ ] **Step 1: Write the probe script**

```python
# /tmp/claude-1000/group-probe/probe_group_xy.py
"""Pin the xy facts the /group charts rely on. Run with the helao env python -I."""
import importlib.metadata

import numpy as np
import xy


def split(*children, **props):
    return (
        xy.chart(*children, width="100%", height="100%", **props)
        .figure()
        .build_payload_split()
    )


print("xy", importlib.metadata.version("xy"))

for sym in ("triangle", "triangle_down"):
    spec, _ = split(xy.scatter(x=np.array([0.0]), y=np.array([0.0]), symbol=sym))
    assert spec["traces"][0]["style"]["symbol"] == sym, spec["traces"][0]
try:
    xy.scatter(x=np.array([0.0]), y=np.array([0.0]), symbol="triangle-down")
    raise AssertionError("triangle-down was accepted")
except ValueError:
    pass
print("SYMBOLS ok")

spec, _ = split(
    xy.scatter(
        x=np.array([0.0, 1.0]),
        y=np.array([0.0, 1.0]),
        color=["#ff0000", "#00ff00"],
        size=6.0,
        symbol="circle",
        opacity=1.0,
        name="n",
    )
)
assert spec["traces"][0]["color"]["mode"] == "direct_rgba", spec["traces"][0]
print("PER-POINT COLOUR ok (direct_rgba)")

spec, _ = split(xy.scatter(x=np.array([], float), y=np.array([], float), color=[]))
assert spec["traces"][0]["color"]["mode"] != "direct_rgba", spec["traces"][0]
print("EMPTY COLOUR LIST -> mode", spec["traces"][0]["color"]["mode"], "(needs placeholder)")

spec, _ = split(xy.scatter(x=np.array([0.0, 1.0]), y=np.array([0.0, 1.0]), size=np.array([10.0, 20.0])))
assert spec["traces"][0]["size"]["mode"] == "continuous", spec["traces"][0]
print("SIZE ARRAY is a mapped channel, not pixels")

spec, _ = split(
    xy.line(x=np.array([0.0, 1.0]), y=np.array([0.0, 1.0]), color="#ff0000", width=3.0, name="e"),
    xy.x_axis(show=False, grid=False, domain=(-1.0, 1.0)),
    xy.y_axis(show=False, grid=False, domain=(-1.0, 1.0)),
    xy.text(0.0, 0.0, "ORCH", dx=0.0, dy=0.0, color="#000000", anchor="middle"),
    xy.x_band(0.0, 1.0, color="#00ff00", opacity=1.0),
    xy.vline(1.0, color="#000000", width=2.0),
    padding=[8, 8, 8, 8],
    pan=False,
    zoom=False,
    click=True,
)
assert spec["traces"][0]["style"] == {"color": "#ff0000", "width": 3.0, "opacity": 1.0}
assert spec["axes"]["x"]["style"]["tick_label_color"] == "#00000000"
assert spec["interaction"] == {"pan": False, "zoom": False, "click": True}, spec["interaction"]
kinds = [a["kind"] for a in spec["annotations"]]
assert kinds == ["text", "band", "rule"], kinds
print("LINE STYLE / AXIS HIDE / INTERACTION / ANNOTATIONS ok")

spec, _ = split(xy.x_band(0.0, 1.0, color="#00ff00"))
assert spec["traces"] == []
print("BAND-ONLY CHART has no traces (strips add a hit trace)")
print("PROBE PASS")
```

- [ ] **Step 2: Run it**

Run: `mkdir -p /tmp/claude-1000/group-probe && /home/dan/miniforge3/envs/helao/bin/python -I /tmp/claude-1000/group-probe/probe_group_xy.py`
Expected: ends with `PROBE PASS`, and prints `xy 0.0.8`. If an assertion fails, stop and report the failing fact: Tasks 5 and 6 depend on each one.

- [ ] **Step 3: Record the findings**

Append to `docs/superpowers/notes/2026-08-01-xy-api-probe.md`:

```markdown
## Verified for the /group page (2026-11-06, xy 0.0.8)

Probe: a scratch script asserting each fact below (`/tmp`, run with the helao env python `-I`).

| Fact | Consequence |
|---|---|
| `xy.scatter(symbol=...)` takes `"triangle"` and `"triangle_down"`; `"triangle-down"` raises `ValueError` | arrowheads and pulses use the underscore names |
| a per-point `color=[hex, ...]` list encodes as `direct_rgba` column data | node, arrow and pulse colours update in place, no rebuild |
| an **empty** `color=[]` encodes as `continuous` (viridis), not `direct_rgba` | `plots.marks_chart` pads an empty trace with one off-domain point so its column layout never changes |
| a `size` array is a mapped channel (`range_px (2, 18)`), not pixels | one scalar size per trace |
| `x_axis(show=False, grid=False, domain=...)` paints the axis transparent | graph and strips hide axes this way |
| `xy.chart(..., pan=False, zoom=False, click=True)` lands in `spec["interaction"]` | fixed view; clicks still reach `on_select` |
| `xy.text(..., anchor="middle")`, `x_band` (`band`) and `vline` (`rule`) are annotations, not traces | they are spec, so `plots.ANNOTATIONS_IN_TOKEN` decides whether a changed label rebuilds the chart |
| a chart of annotations only has zero traces | each strip carries an invisible `hit` scatter |

Still unverified from Python alone: whether xy's append path applies a changed annotation without a rebuild, and whether text draws above WebGL markers. Task 9 of the /group plan checks both in a browser.
```

- [ ] **Step 4: Commit**

```bash
git -C /mnt/STORAGE/repos/helao/helao-async add docs/superpowers/notes/2026-08-01-xy-api-probe.md
git -C /mnt/STORAGE/repos/helao/helao-async commit -m "docs(xy): record the xy 0.0.8 facts the /group charts rely on

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Palette names for group states

**Files:**
- Modify: `helao/ui/shared/palette.py` (append after the `WINDOW_BAND` block near line 949, before `CHART_CHROME`)
- Test: `helao/core/tests/test_palette.py` (append)

**Interfaces:**
- Consumes: `TW`, `WHITE` (already in `palette.py`).
- Produces (all `Final`, all hex unless noted):
  - `GROUP_SHADES: Mapping[str, str]`: state → TW shade name, keys `idle busy active done error estop unreachable queued`
  - `GROUP_IDLE, GROUP_BUSY, GROUP_DONE, GROUP_ERROR, GROUP_ESTOP, GROUP_UNREACHABLE, GROUP_QUEUED, GROUP_PULSE_DISPATCH: str`
  - `GROUP_STATE_COLORS: Mapping[str, str]`: state → hex (same keys as `GROUP_SHADES`)
  - `GROUP_LABEL_COLORS: Mapping[str, str]`: state → hex of text drawn on that fill
  - `GROUP_SELECTED_OUTLINE: str`, `GROUP_PROGRESS: str`, `GROUP_EDGE_TEXT: str`
  - `GROUP_BADGE_CLASSES: Mapping[str, str]`: state → literal Tailwind classes (`"bg-sky-700 text-white"`)
  - `GROUP_ERROR_TEXT_CLASS: str` (Tailwind class)

The spec's shade families (slate, sky, emerald, red, red-900, amber, muted slate, accent) are kept. The 600/700 weights are chosen so the white node and segment labels clear the 4.5 body floor (asserted below). The accent is `violet-600`.

- [ ] **Step 1: Write the failing test**

Append to `helao/core/tests/test_palette.py`:

```python
# --- /group page ------------------------------------------------------------
GROUP_STATES = {"idle", "busy", "active", "done", "error", "estop", "unreachable", "queued"}


def test_group_state_maps_cover_exactly_the_states() -> None:
    assert set(palette.GROUP_SHADES) == GROUP_STATES
    assert set(palette.GROUP_STATE_COLORS) == GROUP_STATES
    assert set(palette.GROUP_LABEL_COLORS) == GROUP_STATES
    assert set(palette.GROUP_BADGE_CLASSES) == GROUP_STATES


def test_group_state_colours_are_tw_shades() -> None:
    for state, name in palette.GROUP_SHADES.items():
        assert palette.GROUP_STATE_COLORS[state] == TW[name]


def test_group_labels_clear_the_body_floor_on_their_fills() -> None:
    for state, fill in palette.GROUP_STATE_COLORS.items():
        label = palette.GROUP_LABEL_COLORS[state]
        measured = contrast_ratio(label, fill)
        assert measured >= FLOOR_BODY_TEXT, f"{state}: {measured:.2f}"


def test_group_badges_use_their_state_shade() -> None:
    for state, classes in palette.GROUP_BADGE_CLASSES.items():
        assert f"bg-{palette.GROUP_SHADES[state]}" in classes.split()


def test_group_named_constants_follow_the_map() -> None:
    assert palette.GROUP_IDLE == palette.GROUP_STATE_COLORS["idle"]
    assert palette.GROUP_BUSY == palette.GROUP_STATE_COLORS["busy"]
    assert palette.GROUP_DONE == palette.GROUP_STATE_COLORS["done"]
    assert palette.GROUP_ERROR == palette.GROUP_STATE_COLORS["error"]
    assert palette.GROUP_ESTOP == palette.GROUP_STATE_COLORS["estop"]
    assert palette.GROUP_UNREACHABLE == palette.GROUP_STATE_COLORS["unreachable"]
    assert palette.GROUP_QUEUED == palette.GROUP_STATE_COLORS["queued"]
    assert palette.GROUP_PULSE_DISPATCH == TW["violet-600"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=. $PY -m pytest helao/core/tests/test_palette.py -q -k group`
Expected: FAIL with `AttributeError: module 'helao.ui.shared.palette' has no attribute 'GROUP_SHADES'`.

- [ ] **Step 3: Implement**

In `helao/ui/shared/palette.py`, after the `WINDOW_BAND` line:

```python
# --- /group page: server-group graph and timelines ----------------------------
GROUP_SHADES: Final[Mapping[str, str]] = {
    "idle": "slate-600",
    "busy": "sky-700",
    "active": "sky-700",
    "done": "emerald-700",
    "error": "red-600",
    "estop": "red-900",
    "unreachable": "amber-700",
    "queued": "slate-300",
}
"""State -> TW shade name for the /group graph, strips and badges.

Server states (idle/busy/error/estop/unreachable) colour nodes and edges; item
states (queued/active/done/error) colour timeline segments. ``active`` is the
same shade as ``busy`` on purpose: the running action and the busy server are
one fact. Weights are 600/700 so the white label drawn on a node or segment
clears the 4.5 body floor; ``queued`` is the one light fill and takes dark text.
"""

GROUP_STATE_COLORS: Final[Mapping[str, str]] = {
    state: TW[name] for state, name in GROUP_SHADES.items()
}
GROUP_IDLE: Final[str] = GROUP_STATE_COLORS["idle"]
GROUP_BUSY: Final[str] = GROUP_STATE_COLORS["busy"]
GROUP_DONE: Final[str] = GROUP_STATE_COLORS["done"]
GROUP_ERROR: Final[str] = GROUP_STATE_COLORS["error"]
GROUP_ESTOP: Final[str] = GROUP_STATE_COLORS["estop"]
GROUP_UNREACHABLE: Final[str] = GROUP_STATE_COLORS["unreachable"]
GROUP_QUEUED: Final[str] = GROUP_STATE_COLORS["queued"]
#: Forward (dispatch) pulse along an edge.
GROUP_PULSE_DISPATCH: Final[str] = TW["violet-600"]
GROUP_LABEL_COLORS: Final[Mapping[str, str]] = {
    state: (TW["slate-900"] if state == "queued" else WHITE) for state in GROUP_SHADES
}
GROUP_SELECTED_OUTLINE: Final[str] = TW["slate-900"]
GROUP_PROGRESS: Final[str] = TW["sky-200"]
GROUP_EDGE_TEXT: Final[str] = TW["slate-700"]
#: Literal class strings, not built at runtime: Tailwind only emits utilities it
#: can see, and a class assembled from a state var would render unstyled.
GROUP_BADGE_CLASSES: Final[Mapping[str, str]] = {
    "idle": "bg-slate-600 text-white",
    "busy": "bg-sky-700 text-white",
    "active": "bg-sky-700 text-white",
    "done": "bg-emerald-700 text-white",
    "error": "bg-red-600 text-white",
    "estop": "bg-red-900 text-white",
    "unreachable": "bg-amber-700 text-white",
    "queued": "bg-slate-300 text-slate-900",
}
GROUP_ERROR_TEXT_CLASS: Final[str] = "text-red-700"
```

Check `sky-200` and `violet-600` exist in `TW` (they do at the time of writing). If one is missing, stop and report rather than adding a shade.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=. $PY -m pytest helao/core/tests/test_palette.py -q`
Expected: all pass, including the whole-tree sweep.

- [ ] **Step 5: Commit**

```bash
git -C /mnt/STORAGE/repos/helao/helao-async add helao/ui/shared/palette.py helao/core/tests/test_palette.py
git -C /mnt/STORAGE/repos/helao/helao-async commit -m "feat(palette): group-state colours for the /group page

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: `GroupSnapshot` builder (pure)

The snapshot is a plain dict of `str/int/float/bool/None/list/dict`. `wire_dumps` sends any non-pydantic object as `[None, obj]`, so it needs no special case.

Two facts were verified while planning:

- **`action_timestamp` is set at dispatch.** `orch_dispatch.py:239` (`_stage_action_for_dispatch`, called at `:140`, after the start-condition wait at `:119`) runs `A.init_act(...)`, which sets `action_timestamp` only if it is still `None` (`premodels.py:425`). The unpack path (`orch_dispatch.py:588`) assigns `action_uuid` only. The spec's fallback (first observation in `active_dict`) is kept for the `None` case, for example a status pushed before staging.
- **Queued experiments have no uuid** (`init_exp` runs at activation), so queued rows carry `qidx`, their absolute deque index.

**Files:**
- Create: `helao/core/models/group_snapshot.py`
- Create: `helao/hexagon/tests/group_fakes.py`
- Test: `helao/hexagon/tests/test_group_snapshot.py`

**Interfaces:**
- Consumes: an object shaped like `OrchHost`: `server_key`, `world_cfg`, `globalstatusmodel` (`loop_state`, `loop_intent`, `orch_state`, `server_dict`, `active_dict`, `nonactive_dict`, `counter_dispatched_actions`), `status_summary`, `active_sequence`, `active_experiment`, `sequence_dq`, `experiment_dq`, `action_dq`.
- Produces:
  - `ERROR_STATUSES: frozenset[str]` = `{"errored", "aborted", "estopped"}`
  - `EXP_DONE_WINDOW = 20`, `EXP_QUEUED_WINDOW = 50`
  - `epoch(ts) -> float | None`
  - `server_rows(orch, finish_errors: dict[str, bool]) -> list[dict]`: `{key, status, active_action}`
  - `experiment_rows(orch) -> tuple[list[dict], int, int]`: `(rows, n_done, n_queued)`; row `{uuid, name, state, t_start, t_end, qidx}`
  - `action_rows(orch, first_seen: dict[str, float]) -> list[dict]`: `{uuid, name, server, state, t_start, t_end}`
  - `build_snapshot(orch, *, seq_no: int, now: float, events: list[dict], finish_errors: dict[str, bool], first_seen: dict[str, float]) -> dict`, with keys `seq_no t orch_state loop_state loop_intent closing_out n_sequences_queued seq orch_action servers experiments n_done n_queued actions events`
  - `group_fakes.fake_orch()`, `fake_act(...)`, `fake_exp(...)`, `fake_seq(...)`, `T0`

- [ ] **Step 1: Write the fakes**

`helao/hexagon/tests/group_fakes.py`:

```python
"""Read-only fakes shaped like OrchHost, for the /ws_orch snapshot and feed tests.

Attribute names are pinned against the real models by
``test_fakes_use_real_model_field_names`` in test_group_snapshot.py.
"""

from collections import deque
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

from helao.core.models.hlostatus import HloStatus
from helao.core.models.orchstatus import LoopIntent, LoopStatus, OrchStatus

T0 = datetime(2026, 11, 6, 10, 0, 0)


def fake_act(server="SIM", name="acquire", exp_uuid=None, ts=T0, fin=None, status=(HloStatus.active,)):
    return SimpleNamespace(
        action_uuid=uuid4(),
        action_name=name,
        action_server=SimpleNamespace(server_name=server),
        experiment_uuid=exp_uuid,
        action_timestamp=ts,
        action_finished_timestamp=fin,
        action_status=list(status),
    )


def fake_exp(name="exp", with_uuid=True, ts=None, fin=None, status=()):
    return SimpleNamespace(
        experiment_uuid=uuid4() if with_uuid else None,
        experiment_name=name,
        experiment_timestamp=ts,
        experiment_finished_timestamp=fin,
        experiment_status=list(status),
        dispatched_actions=[],
    )


def fake_seq(name="seq", ts=T0):
    return SimpleNamespace(
        sequence_uuid=uuid4(),
        sequence_name=name,
        sequence_label="label",
        sequence_timestamp=ts,
        dispatched_experiments=[],
    )


def fake_orch(servers=("SIM", "PSTAT")):
    gsm = SimpleNamespace(
        loop_state=LoopStatus.stopped,
        loop_intent=LoopIntent.none,
        orch_state=OrchStatus.idle,
        server_dict={},
        active_dict={},
        nonactive_dict={},
        counter_dispatched_actions={},
    )
    world = {
        "servers": {
            "ORCH": {"group": "orchestrator"},
            **{key: {"group": "action"} for key in servers},
            "UI": {"group": "visualizer"},
        }
    }
    return SimpleNamespace(
        server_key="ORCH",
        world_cfg=world,
        globalstatusmodel=gsm,
        status_summary={},
        active_sequence=None,
        active_experiment=None,
        sequence_dq=deque(),
        experiment_dq=deque(),
        action_dq=deque(),
    )
```

- [ ] **Step 2: Write the failing tests**

`helao/hexagon/tests/test_group_snapshot.py`:

```python
"""GroupSnapshot builder: pure, read-only, plain-dict output."""

from datetime import timedelta
from types import SimpleNamespace

from helao.core.models.hlostatus import HloStatus
from helao.core.models.orchstatus import LoopStatus
from helao.hexagon.tests.group_fakes import T0, fake_act, fake_exp, fake_orch, fake_seq


def _snap(orch, **kw):
    from helao.core.models.group_snapshot import build_snapshot

    args = dict(seq_no=1, now=100.0, events=[], finish_errors={}, first_seen={})
    args.update(kw)
    return build_snapshot(orch, **args)


def test_fakes_use_real_model_field_names():
    from helao.core.models.machine import MachineModel
    from helao.core.models.server import ActionServerModel, GlobalStatusModel
    from helao.helpers.premodels import Action, Experiment, Sequence

    for name in ("action_uuid", "action_name", "action_server", "experiment_uuid",
                 "action_timestamp", "action_finished_timestamp", "action_status"):
        assert name in Action.model_fields, name
    for name in ("experiment_uuid", "experiment_name", "experiment_timestamp",
                 "experiment_finished_timestamp", "experiment_status", "dispatched_actions"):
        assert name in Experiment.model_fields, name
    for name in ("sequence_uuid", "sequence_name", "sequence_label",
                 "sequence_timestamp", "dispatched_experiments"):
        assert name in Sequence.model_fields, name
    assert "estop" in ActionServerModel.model_fields
    assert "server_name" in MachineModel.model_fields
    for name in ("loop_state", "loop_intent", "orch_state", "server_dict", "active_dict",
                 "nonactive_dict", "counter_dispatched_actions"):
        assert name in GlobalStatusModel.model_fields, name


def test_snapshot_is_plain_data_that_wire_dumps_round_trips():
    from helao.helpers.ws_utils import wire_dumps, wire_loads

    orch = fake_orch()
    orch.active_sequence = fake_seq()
    snap = _snap(orch)
    assert wire_loads(wire_dumps(snap)) == snap
    assert snap["seq"]["t_start"] == T0.timestamp()
    assert snap["loop_state"] == "stopped"


def test_server_status_precedence_and_config_filter():
    from helao.core.models.group_snapshot import server_rows

    orch = fake_orch(servers=("A", "B", "C", "D", "E"))
    gsm = orch.globalstatusmodel
    a = fake_act(server="A")
    b = fake_act(server="B")
    gsm.active_dict = {a.action_uuid: a, b.action_uuid: b}
    orch.status_summary = {"A": ("unreachable", "unknown")}
    gsm.server_dict = {("B", "m"): SimpleNamespace(estop=True), ("X", "m"): SimpleNamespace(estop=False)}
    rows = {r["key"]: r for r in server_rows(orch, finish_errors={"D": True, "E": False})}
    assert rows["A"]["status"] == "unreachable"  # beats busy
    assert rows["B"]["status"] == "estop"  # beats busy
    assert rows["C"]["status"] == "idle"
    assert rows["D"]["status"] == "error"
    assert rows["E"]["status"] == "idle"
    assert rows["X"]["status"] == "idle"  # known to the orch, not in config
    assert "ORCH" not in rows and "UI" not in rows
    busy = fake_act(server="C", name="move")
    gsm.active_dict = {busy.action_uuid: busy}
    rows = {r["key"]: r for r in server_rows(orch, finish_errors={})}
    assert rows["C"] == {"key": "C", "status": "busy", "active_action": "move"}


def test_experiment_window_bounds_and_totals():
    from helao.core.models.group_snapshot import experiment_rows

    orch = fake_orch()
    seq = fake_seq()
    seq.dispatched_experiments = [
        fake_exp(f"d{i}", ts=T0, fin=T0 + timedelta(seconds=1), status=(HloStatus.finished,))
        for i in range(25)
    ]
    seq.dispatched_experiments[-1].experiment_status = [HloStatus.errored]
    orch.active_sequence = seq
    orch.active_experiment = fake_exp("act", ts=T0)
    orch.experiment_dq.extend(fake_exp(f"q{i}", with_uuid=False) for i in range(60))
    rows, n_done, n_queued = experiment_rows(orch)
    states = [r["state"] for r in rows]
    assert states == ["done"] * 19 + ["error"] + ["active"] + ["queued"] * 50
    assert rows[0]["name"] == "d5"
    assert (n_done, n_queued) == (5, 10)
    assert rows[21]["uuid"] is None and rows[21]["qidx"] == 0
    assert rows[20]["t_start"] == T0.timestamp() and rows[20]["t_end"] is None


def test_active_experiment_already_in_done_is_not_listed_twice():
    from helao.core.models.group_snapshot import experiment_rows

    orch = fake_orch()
    seq = fake_seq()
    exp = fake_exp("e", ts=T0, fin=T0, status=(HloStatus.finished,))
    seq.dispatched_experiments = [exp]
    orch.active_sequence = seq
    orch.active_experiment = exp
    rows, _, _ = experiment_rows(orch)
    assert [r["state"] for r in rows] == ["done"]


def test_action_rows_states_times_and_fallback():
    from helao.core.models.group_snapshot import action_rows

    orch = fake_orch()
    exp = fake_exp("e", ts=T0)
    orch.active_experiment = exp
    gsm = orch.globalstatusmodel
    done = fake_act(name="a1", exp_uuid=exp.experiment_uuid, fin=T0 + timedelta(seconds=5))
    running = fake_act(name="a2", exp_uuid=exp.experiment_uuid, ts=None)
    failed = fake_act(name="a3", exp_uuid=exp.experiment_uuid, fin=T0)
    queued = fake_act(name="a4", exp_uuid=exp.experiment_uuid, ts=None)
    exp.dispatched_actions = [done, running, failed]
    gsm.active_dict = {running.action_uuid: running}
    gsm.nonactive_dict = {
        HloStatus.finished: {done.action_uuid: done},
        HloStatus.errored: {failed.action_uuid: failed},
    }
    orch.action_dq.append(queued)
    rows = action_rows(orch, first_seen={str(running.action_uuid): 42.0})
    assert [(r["name"], r["state"]) for r in rows] == [
        ("a1", "done"), ("a2", "active"), ("a3", "error"), ("a4", "queued")
    ]
    assert rows[0]["t_end"] == (T0 + timedelta(seconds=5)).timestamp()
    assert rows[1]["t_start"] == 42.0  # action_timestamp None -> first observation
    assert rows[3]["t_start"] is None and rows[3]["uuid"] == str(queued.action_uuid)


def test_active_action_not_yet_in_dispatched_actions_is_listed():
    from helao.core.models.group_snapshot import action_rows

    orch = fake_orch()
    exp = fake_exp("e", ts=T0)
    orch.active_experiment = exp
    early = fake_act(name="early", exp_uuid=exp.experiment_uuid)
    orch.globalstatusmodel.active_dict = {early.action_uuid: early}
    assert [r["state"] for r in action_rows(orch, first_seen={})] == ["active"]


def test_closing_out_only_while_stopped_with_an_active_experiment():
    orch = fake_orch()
    orch.active_experiment = fake_exp("e", ts=T0)
    assert _snap(orch)["closing_out"] is True
    orch.globalstatusmodel.loop_state = LoopStatus.started
    assert _snap(orch)["closing_out"] is False
    orch.globalstatusmodel.loop_state = LoopStatus.stopped
    orch.active_experiment = None
    assert _snap(orch)["closing_out"] is False


def test_orch_own_action_is_reported_on_the_orch_not_as_a_server():
    orch = fake_orch()
    wait = fake_act(server="ORCH", name="wait")
    orch.globalstatusmodel.active_dict = {wait.action_uuid: wait}
    snap = _snap(orch)
    assert snap["orch_action"] == "wait"
    assert "ORCH" not in {s["key"] for s in snap["servers"]}
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=. $PY -m pytest helao/hexagon/tests/test_group_snapshot.py -q`
Expected: `test_fakes_use_real_model_field_names` passes. Every other test fails with `ModuleNotFoundError: No module named 'helao.core.models.group_snapshot'`.

- [ ] **Step 4: Implement**

`helao/core/models/group_snapshot.py`:

```python
"""The ``/ws_orch`` frame: a plain-dict snapshot of a running orchestrator.

Built read-only by :class:`helao.hexagon.app.orch_graph_feed.OrchGraphFeed`.
Plain data (str/int/float/bool/None/list/dict) so ``ws_utils.wire_dumps`` sends
it as an untagged ``[None, dict]`` frame with no special case.

Times are epoch seconds, or ``None`` until known. Item ``state`` is one of
``queued | active | done | error``; server ``status`` one of
``idle | busy | error | estop | unreachable``.
"""

import itertools
from datetime import datetime
from typing import Optional

ERROR_STATUSES = frozenset({"errored", "aborted", "estopped"})
TERMINAL_OK = frozenset({"finished", "skipped", "split", "retired"})
EXP_DONE_WINDOW = 20
EXP_QUEUED_WINDOW = 50


def _v(value) -> str:
    """Enum member or plain value -> its string value."""
    return str(getattr(value, "value", value))


def epoch(ts) -> Optional[float]:
    """Epoch seconds of a (naive, local) datetime, or None."""
    return ts.timestamp() if isinstance(ts, datetime) else None


def _names(statuses) -> set:
    return {_v(s) for s in (statuses or [])}


def _item_state(statuses) -> str:
    """done/error for a finished record; active while nothing terminal is set."""
    names = _names(statuses)
    if names & ERROR_STATUSES:
        return "error"
    if names & TERMINAL_OK:
        return "done"
    return "active"


def server_rows(orch, finish_errors: dict) -> list:
    """Every config ``group: action`` server, plus any other the orch knows."""
    gsm = orch.globalstatusmodel
    estopped = {key[0] for key, model in gsm.server_dict.items() if model.estop}
    active = {}
    for act in gsm.active_dict.values():
        active.setdefault(act.action_server.server_name, act.action_name)
    servers = orch.world_cfg.get("servers") or {}
    keys = [k for k, cfg in servers.items() if isinstance(cfg, dict) and cfg.get("group") == "action"]
    extra = {key[0] for key in gsm.server_dict} - set(keys) - {orch.server_key}
    keys += sorted(k for k in extra if k not in servers)
    rows = []
    for key in keys:
        summary = orch.status_summary.get(key)
        if summary and summary[0] == "unreachable":
            status = "unreachable"
        elif key in estopped:
            status = "estop"
        elif key in active:
            status = "busy"
        elif finish_errors.get(key):
            status = "error"
        else:
            status = "idle"
        rows.append({"key": key, "status": status, "active_action": active.get(key)})
    return rows


def experiment_rows(orch) -> tuple:
    """Windowed experiments of the active sequence: ``(rows, n_done, n_queued)``.

    Queued experiments have no uuid until ``init_exp`` runs at activation, so a
    queued row carries ``qidx``, its ABSOLUTE index in ``experiment_dq``.
    """
    seq = orch.active_sequence
    done_all = list(getattr(seq, "dispatched_experiments", None) or []) if seq else []
    done = done_all[-EXP_DONE_WINDOW:]
    rows = [
        {
            "uuid": str(e.experiment_uuid),
            "name": e.experiment_name,
            "state": "error" if _item_state(e.experiment_status) == "error" else "done",
            "t_start": epoch(e.experiment_timestamp),
            "t_end": epoch(e.experiment_finished_timestamp),
            "qidx": None,
        }
        for e in done
    ]
    exp = orch.active_experiment
    if exp is not None and str(exp.experiment_uuid) not in {r["uuid"] for r in rows}:
        rows.append(
            {
                "uuid": str(exp.experiment_uuid),
                "name": exp.experiment_name,
                "state": "active",
                "t_start": epoch(exp.experiment_timestamp),
                "t_end": None,
                "qidx": None,
            }
        )
    for idx, e in enumerate(itertools.islice(orch.experiment_dq, EXP_QUEUED_WINDOW)):
        rows.append(
            {
                "uuid": str(e.experiment_uuid) if e.experiment_uuid else None,
                "name": e.experiment_name,
                "state": "queued",
                "t_start": None,
                "t_end": None,
                "qidx": idx,
            }
        )
    n_done = len(done_all) - len(done)
    n_queued = max(0, len(orch.experiment_dq) - EXP_QUEUED_WINDOW)
    return rows, n_done, n_queued


def action_rows(orch, first_seen: dict) -> list:
    """Actions of the active experiment: dispatched, then active-only, then queued."""
    exp = orch.active_experiment
    if exp is None:
        return []
    gsm = orch.globalstatusmodel
    active = {str(u): a for u, a in gsm.active_dict.items()}
    finished = {}
    for status, bucket in gsm.nonactive_dict.items():
        for u, a in bucket.items():
            finished[str(u)] = (_v(status), a)
    rows, seen = [], set()

    def add(uid, model, state, t_end):
        seen.add(uid)
        t_start = epoch(model.action_timestamp)
        rows.append(
            {
                "uuid": uid,
                "name": model.action_name,
                "server": model.action_server.server_name,
                "state": state,
                "t_start": t_start if t_start is not None else first_seen.get(uid),
                "t_end": t_end,
            }
        )

    for a in exp.dispatched_actions or []:
        uid = str(a.action_uuid)
        if uid in seen:
            continue
        if uid in active:
            add(uid, active[uid], "active", None)
        elif uid in finished:
            status, model = finished[uid]
            state = "error" if status in ERROR_STATUSES else "done"
            add(uid, model, state, epoch(model.action_finished_timestamp))
        else:
            add(uid, a, _item_state(a.action_status), epoch(a.action_finished_timestamp))
    for uid, a in active.items():
        if uid not in seen and a.experiment_uuid == exp.experiment_uuid:
            add(uid, a, "active", None)
    for a in orch.action_dq:
        uid = str(a.action_uuid) if a.action_uuid else None
        rows.append(
            {
                "uuid": uid,
                "name": a.action_name,
                "server": a.action_server.server_name,
                "state": "queued",
                "t_start": None,
                "t_end": None,
            }
        )
    return rows


def build_snapshot(orch, *, seq_no, now, events, finish_errors, first_seen) -> dict:
    """One ``/ws_orch`` frame. Reads only; never takes ``aiolock``."""
    gsm = orch.globalstatusmodel
    loop_state = _v(gsm.loop_state)
    seq = orch.active_sequence
    experiments, n_done, n_queued = experiment_rows(orch)
    orch_action = None
    for act in gsm.active_dict.values():
        if act.action_server.server_name == orch.server_key:
            orch_action = act.action_name
            break
    return {
        "seq_no": seq_no,
        "t": now,
        "orch_state": _v(gsm.orch_state),
        "loop_state": loop_state,
        "loop_intent": _v(gsm.loop_intent),
        "closing_out": loop_state == "stopped" and orch.active_experiment is not None,
        "n_sequences_queued": len(orch.sequence_dq),
        "seq": (
            None
            if seq is None
            else {
                "uuid": str(seq.sequence_uuid),
                "name": seq.sequence_name,
                "label": seq.sequence_label,
                "t_start": epoch(seq.sequence_timestamp),
            }
        ),
        "orch_action": orch_action,
        "servers": server_rows(orch, finish_errors),
        "experiments": experiments,
        "n_done": n_done,
        "n_queued": n_queued,
        "actions": action_rows(orch, first_seen),
        "events": list(events),
    }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=. $PY -m pytest helao/hexagon/tests/test_group_snapshot.py -q`
Expected: 9 passed.

- [ ] **Step 6: Mutation check**

Make each change below in turn, run the same command, confirm the named test FAILS, then restore with `git -C /mnt/STORAGE/repos/helao/helao-async checkout -- helao/core/models/group_snapshot.py` (the file is uncommitted, so instead keep a copy: `cp helao/core/models/group_snapshot.py /tmp/claude-1000/gs.py` before, `/usr/bin/cp /tmp/claude-1000/gs.py helao/core/models/group_snapshot.py` after).
1. `done_all[-EXP_DONE_WINDOW:]` → `done_all[:EXP_DONE_WINDOW]`. Expect `test_experiment_window_bounds_and_totals` to fail.
2. Swap the `elif key in estopped` and `elif key in active` branches. Expect `test_server_status_precedence_and_config_filter` to fail.
3. `else first_seen.get(uid)` → `else None`. Expect `test_action_rows_states_times_and_fallback` to fail.
4. `loop_state == "stopped" and` → `loop_state == "stopped" or`. Expect `test_closing_out_only_while_stopped_with_an_active_experiment` to fail.
After restoring, re-run and confirm 9 passed.

- [ ] **Step 7: Commit**

```bash
git -C /mnt/STORAGE/repos/helao/helao-async add helao/core/models/group_snapshot.py helao/hexagon/tests/group_fakes.py helao/hexagon/tests/test_group_snapshot.py
git -C /mnt/STORAGE/repos/helao/helao-async commit -m "feat(orch): GroupSnapshot builder for the /ws_orch stream

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: `OrchGraphFeed`, `/ws_orch` and `/get_object` on `OrchHost`

**Files:**
- Create: `helao/hexagon/app/orch_graph_feed.py`
- Modify: `helao/hexagon/app/orch_payloads.py` (append `_object_payload`)
- Modify: `helao/hexagon/app/orch_host.py`: imports (`:41`), `__init__` (after `self.global_params = {}`, `:178`), `_register_orch_payload_routes` (`:591-657`), `_register_orch_ws_routes` (`:1323-1382`), `_orch_startup` (`:1425-1445`), `orch_shutdown` (`:1467-1492`)
- Modify: `helao/hexagon/tests/checklists/orch_openapi.json` (hand-insert one entry; **never regenerate**)
- Test: `helao/hexagon/tests/test_orch_graph_feed.py`

**Interfaces:**
- Consumes: `build_snapshot`, `ERROR_STATUSES` (Task 3); `MultisubscriberQueue.put_nowait`; `WsPublisher`; `wire_dumps`.
- Produces:
  - `TICK_S = 0.1`, `HEARTBEAT_S = 2.0`
  - `fingerprint(orch) -> tuple`
  - `OrchGraphFeed(orch, queue, *, tick_s=TICK_S, heartbeat_s=HEARTBEAT_S, clock=time.time)` with `.latest: dict | None`, `.diff_events(now) -> list[dict]`, `.step(now) -> dict | None`, `async .run()`
  - event dict: `{kind: "dispatch"|"finish", server, action_uuid, action_name, status, t}`
  - `OrchHost.orch_graph_q`, `.graph_feed`, `.graph_feed_task`, `.orch_graph_publisher`
  - `POST /get_object?kind=experiment|action&uuid=<str>` returns a dict or `null`
  - `_object_payload(orch, kind: str, uuid: str) -> dict | None`

- [ ] **Step 1: Write the failing tests**

`helao/hexagon/tests/test_orch_graph_feed.py`:

```python
"""OrchGraphFeed against a fake orch, plus the OrchHost wiring and /get_object."""

import asyncio

import pytest

from helao.core.models.hlostatus import HloStatus
from helao.hexagon.tests.group_fakes import T0, fake_act, fake_exp, fake_orch, fake_seq


class _Q:
    def __init__(self):
        self.items = []

    def put_nowait(self, item):
        self.items.append(item)


def _feed(orch):
    from helao.hexagon.app.orch_graph_feed import OrchGraphFeed

    return OrchGraphFeed(orch, _Q())


def test_unchanged_state_sends_nothing_but_the_heartbeat_still_arrives():
    feed = _feed(fake_orch())
    first = feed.step(0.0)
    assert first is not None and first["seq_no"] == 1
    assert feed.step(0.1) is None
    assert feed.step(1.9) is None
    beat = feed.step(2.0)
    assert beat is not None and beat["seq_no"] == 2 and beat["events"] == []
    assert beat is not first  # WsPublisher identity cache: a new object per publish


def test_first_frame_primes_without_replaying_old_finishes():
    orch = fake_orch()
    old = fake_act()
    orch.globalstatusmodel.nonactive_dict = {HloStatus.finished: {old.action_uuid: old}}
    assert _feed(orch).step(0.0)["events"] == []


def test_dispatch_then_finish_events():
    orch = fake_orch()
    feed = _feed(orch)
    feed.step(0.0)
    a = fake_act(server="SIM", name="acquire")
    orch.globalstatusmodel.active_dict = {a.action_uuid: a}
    frame = feed.step(0.1)
    assert [(e["kind"], e["server"], e["action_name"]) for e in frame["events"]] == [
        ("dispatch", "SIM", "acquire")
    ]
    orch.globalstatusmodel.active_dict = {}
    orch.globalstatusmodel.nonactive_dict = {HloStatus.finished: {a.action_uuid: a}}
    frame = feed.step(0.2)
    assert [(e["kind"], e["status"]) for e in frame["events"]] == [("finish", "finished")]
    assert {s["key"]: s["status"] for s in frame["servers"]}["SIM"] == "idle"


def test_errored_finish_marks_the_server_error():
    orch = fake_orch()
    feed = _feed(orch)
    feed.step(0.0)
    a = fake_act(server="SIM")
    orch.globalstatusmodel.active_dict = {a.action_uuid: a}
    feed.step(0.1)
    orch.globalstatusmodel.active_dict = {}
    orch.globalstatusmodel.nonactive_dict = {HloStatus.errored: {a.action_uuid: a}}
    frame = feed.step(0.2)
    assert frame["events"][0]["status"] == "errored"
    assert {s["key"]: s["status"] for s in frame["servers"]}["SIM"] == "error"


def test_an_action_seen_only_finished_still_yields_dispatch_then_finish():
    orch = fake_orch()
    feed = _feed(orch)
    feed.step(0.0)
    a = fake_act()
    orch.globalstatusmodel.nonactive_dict = {HloStatus.finished: {a.action_uuid: a}}
    frame = feed.step(0.1)
    assert [e["kind"] for e in frame["events"]] == ["dispatch", "finish"]


def test_an_action_that_vanishes_without_a_terminal_bucket_still_finishes():
    orch = fake_orch()
    feed = _feed(orch)
    feed.step(0.0)
    a = fake_act()
    orch.globalstatusmodel.active_dict = {a.action_uuid: a}
    feed.step(0.1)
    orch.globalstatusmodel.active_dict = {}
    frame = feed.step(0.2)
    assert [(e["kind"], e["status"]) for e in frame["events"]] == [("finish", "finished")]


def test_unhashable_driver_status_does_not_break_the_fingerprint():
    orch = fake_orch()
    orch.status_summary = {"SIM": ("idle", {"axis": [1, 2]})}
    feed = _feed(orch)
    assert feed.step(0.0) is not None
    orch.status_summary = {"SIM": ("idle", {"axis": [1, 3]})}
    assert feed.step(0.1) is not None  # a changed driver status is a change


def test_window_and_closing_out_reach_the_frame():
    orch = fake_orch()
    seq = fake_seq()
    seq.dispatched_experiments = [fake_exp(f"d{i}", ts=T0, fin=T0, status=(HloStatus.finished,)) for i in range(22)]
    orch.active_sequence = seq
    orch.active_experiment = fake_exp("a", ts=T0)
    frame = _feed(orch).step(0.0)
    assert frame["n_done"] == 2 and frame["closing_out"] is True


@pytest.mark.asyncio
async def test_an_exception_in_the_build_does_not_kill_the_task():
    from helao.hexagon.app.orch_graph_feed import OrchGraphFeed

    q = _Q()
    feed = OrchGraphFeed(fake_orch(), q, tick_s=0.01, heartbeat_s=0.02)
    real_step = feed.step
    calls = {"n": 0}

    def flaky(now):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return real_step(now)

    feed.step = flaky
    task = asyncio.create_task(feed.run())
    await asyncio.sleep(0.2)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert calls["n"] > 2 and len(q.items) >= 1


def _host():
    from helao.hexagon.tests.test_orch_host_surface import _host as surface_host

    return surface_host()


def test_host_serves_ws_orch_once_with_identity_encoding():
    host = _host()
    assert [r for r in host.routes if getattr(r, "path", "") == "/ws_orch"].__len__() == 1
    assert "as_dict" not in host.orch_graph_publisher.xform_func.__code__.co_names
    assert host.graph_feed.orch is host


def test_get_object_finds_each_tier_and_misses_with_null():
    from uuid import uuid4

    from fastapi.testclient import TestClient

    from helao.core.models.machine import MachineModel
    from helao.helpers.premodels import Action, Experiment, Sequence

    host = _host()
    sim = MachineModel(server_name="SIM")
    act_active = Action(action_name="a_active", action_server=sim, action_uuid=uuid4())
    act_queued = Action(action_name="a_queued", action_server=sim, action_uuid=uuid4())
    exp_active = Experiment(experiment_name="e_active", experiment_uuid=uuid4())
    exp_active.dispatched_actions = [act_active]
    exp_queued = Experiment(experiment_name="e_queued", experiment_uuid=uuid4())
    exp_done = Experiment(experiment_name="e_done", experiment_uuid=uuid4())
    seq = Sequence(sequence_name="s", sequence_uuid=uuid4())
    seq.dispatched_experiments = [exp_done.get_exp()]
    host.active_sequence = seq
    host.active_experiment = exp_active
    host.experiment_dq.append(exp_queued)
    host.action_dq.append(act_queued)
    hist_uuid = uuid4()
    host.action_history[hist_uuid] = {"action_name": "a_hist"}

    client = TestClient(host)

    def get(kind, uid):
        r = client.post("/get_object", params={"kind": kind, "uuid": str(uid)})
        assert r.status_code == 200
        return r.json()

    assert get("experiment", exp_active.experiment_uuid)["experiment_name"] == "e_active"
    assert get("experiment", exp_done.experiment_uuid)["experiment_name"] == "e_done"
    assert get("experiment", exp_queued.experiment_uuid)["experiment_name"] == "e_queued"
    assert get("action", act_active.action_uuid)["action_name"] == "a_active"
    assert get("action", act_queued.action_uuid)["action_name"] == "a_queued"
    assert get("action", hist_uuid)["action_name"] == "a_hist"
    assert get("action", uuid4()) is None
    assert get("sequence", seq.sequence_uuid) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=. $PY -m pytest helao/hexagon/tests/test_orch_graph_feed.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'helao.hexagon.app.orch_graph_feed'`. The host tests fail with `AttributeError` on `orch_graph_publisher`.

- [ ] **Step 3: Implement the feed**

`helao/hexagon/app/orch_graph_feed.py`:

```python
"""Read-only feed behind ``/ws_orch``: orchestrator snapshots for the /group page.

Not a hook in the dispatch path. ``orch_dispatch.py``, ``orch_effects.py`` and
``ingestion.py`` are untouched, so none of the dispatch-loop traps in this
directory's CLAUDE.md is in play. Every 100 ms the feed reads state, never
takes ``aiolock`` and never mutates the orchestrator; a frame goes out only when
a cheap fingerprint changes, or every 2 s as a heartbeat so a client can tell a
quiet stream from a dead one. Events are derived by diffing ``active_dict`` and
``nonactive_dict`` uuid sets between ticks.
"""

import asyncio
import time
from typing import Optional

from helao.core.models.group_snapshot import ERROR_STATUSES, build_snapshot
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

TICK_S = 0.1
HEARTBEAT_S = 2.0


def fingerprint(orch) -> tuple:
    """Everything a frame shows, cheaply. ``repr`` keeps dict driver statuses hashable."""
    gsm = orch.globalstatusmodel
    return (
        str(gsm.loop_state),
        str(gsm.loop_intent),
        str(gsm.orch_state),
        tuple(sorted((k, repr(v)) for k, v in orch.status_summary.items())),
        tuple(sorted((str(k), v) for k, v in gsm.counter_dispatched_actions.items())),
        frozenset(str(u) for u in gsm.active_dict),
        frozenset((str(s), str(u)) for s, bucket in gsm.nonactive_dict.items() for u in bucket),
        tuple(sorted(str(key[0]) for key, m in gsm.server_dict.items() if m.estop)),
        str(getattr(orch.active_sequence, "sequence_uuid", None)),
        str(getattr(orch.active_experiment, "experiment_uuid", None)),
        len(orch.sequence_dq),
        len(orch.experiment_dq),
        len(orch.action_dq),
    )


class OrchGraphFeed:
    """Builds and publishes ``GroupSnapshot`` frames. One per ``OrchHost``."""

    def __init__(self, orch, queue, *, tick_s=TICK_S, heartbeat_s=HEARTBEAT_S, clock=time.time):
        self.orch = orch
        self.queue = queue
        self.tick_s = tick_s
        self.heartbeat_s = heartbeat_s
        self.clock = clock
        #: The last frame built; the /ws_orch route sends it first on connect.
        self.latest: Optional[dict] = None
        self._seq_no = 0
        self._last_fp = None
        self._last_sent = float("-inf")
        self._primed = False
        self._prev_active: dict = {}
        self._prev_nonactive: set = set()
        self._finish_errors: dict = {}
        self._first_seen: dict = {}
        self._pending: list = []

    def diff_events(self, now: float) -> list:
        """dispatch/finish events since the previous tick."""
        gsm = self.orch.globalstatusmodel
        active = {
            str(u): (a.action_server.server_name, a.action_name)
            for u, a in gsm.active_dict.items()
        }
        nonactive = {}
        for status, bucket in gsm.nonactive_dict.items():
            for u, a in bucket.items():
                nonactive[str(u)] = (
                    a.action_server.server_name,
                    a.action_name,
                    str(getattr(status, "value", status)),
                )
        events = []
        if self._primed:

            def ev(kind, uid, server, name, status):
                events.append(
                    {"kind": kind, "server": server, "action_uuid": uid,
                     "action_name": name, "status": status, "t": now}
                )

            for uid, (server, name) in active.items():
                if uid not in self._prev_active:
                    self._first_seen.setdefault(uid, now)
                    ev("dispatch", uid, server, name, "active")
            for uid, (server, name, status) in nonactive.items():
                if uid in self._prev_nonactive:
                    continue
                if uid not in self._prev_active:
                    # started and finished between two ticks
                    ev("dispatch", uid, server, name, "active")
                ev("finish", uid, server, name, status)
            for uid, (server, name) in self._prev_active.items():
                if uid not in active and uid not in nonactive:
                    ev("finish", uid, server, name, "finished")
            for e in events:
                if e["kind"] == "finish":
                    self._finish_errors[e["server"]] = e["status"] in ERROR_STATUSES
        else:
            for uid in active:
                self._first_seen.setdefault(uid, now)
            self._primed = True
        self._prev_active = active
        self._prev_nonactive = set(nonactive)
        live = set(active) | set(nonactive)
        self._first_seen = {u: t for u, t in self._first_seen.items() if u in live}
        return events

    def step(self, now: float) -> Optional[dict]:
        """Return a new frame when something changed or a heartbeat is due."""
        self._pending.extend(self.diff_events(now))
        fp = fingerprint(self.orch)
        if (
            fp == self._last_fp
            and not self._pending
            and now - self._last_sent < self.heartbeat_s
        ):
            return None
        snap = build_snapshot(
            self.orch,
            seq_no=self._seq_no + 1,
            now=now,
            events=self._pending,
            finish_errors=self._finish_errors,
            first_seen=self._first_seen,
        )
        self._seq_no += 1
        self._pending = []
        self._last_fp = fp
        self._last_sent = now
        self.latest = snap
        return snap

    async def run(self) -> None:
        """Tick until cancelled. A failed frame is logged and skipped."""
        while True:
            try:
                snap = self.step(self.clock())
                if snap is not None:
                    self.queue.put_nowait(snap)
            except Exception:
                LOGGER.exception("orch graph feed: frame skipped")
            await asyncio.sleep(self.tick_s)
```

- [ ] **Step 4: Implement `_object_payload`**

Append to `helao/hexagon/app/orch_payloads.py`:

```python
def _object_payload(orch, kind: str, uuid: str) -> Optional[dict]:
    """The experiment or action with ``uuid`` as a dict, or ``None``.

    Read-only and lock-free, like the other payload builders. Search order:
    the active run (active experiment, its dispatched actions, the live
    ``active_dict``, the active sequence's finished experiments), then the
    deques, then the history containers (whose values are meta dicts, not
    models, and are returned as they are).
    """
    target = str(uuid)
    seq = getattr(orch, "active_sequence", None)
    exp = getattr(orch, "active_experiment", None)
    if kind == "experiment":
        candidates = [exp] if exp is not None else []
        candidates += list(getattr(seq, "dispatched_experiments", None) or [])
        candidates += list(orch.experiment_dq)
        for e in candidates:
            if str(e.experiment_uuid) == target:
                return e.as_dict()
        history = orch.experiment_history
    elif kind == "action":
        candidates = list(getattr(exp, "dispatched_actions", None) or [])
        candidates += list(orch.globalstatusmodel.active_dict.values())
        candidates += list(orch.action_dq)
        for a in candidates:
            if str(a.action_uuid) == target:
                return a.as_dict()
        history = orch.action_history
    else:
        return None
    for key, meta in history.items():
        if str(key) == target:
            return dict(meta)
    return None
```

- [ ] **Step 5: Wire `OrchHost`**

In `helao/hexagon/app/orch_host.py`:

1. Change `from helao.helpers.ws_utils import WsPublisher` to `from helao.helpers.ws_utils import WsPublisher, wire_dumps`. After the `from helao.hexagon.app.action_host import ActionHost` line add `from helao.hexagon.app.orch_graph_feed import OrchGraphFeed`.
2. In `__init__`, directly after `self.global_params = {}`:

```python
        # /ws_orch: the read-only group-graph feed (orch_graph_feed.py). Built
        # here, started in _orch_startup, cancelled in orch_shutdown.
        self.orch_graph_q = MultisubscriberQueue()
        self.graph_feed = OrchGraphFeed(self, self.orch_graph_q)
        self.graph_feed_task = None
```

3. In `_register_orch_payload_routes`, add `_object_payload` to the `from helao.hexagon.app.orch_payloads import (...)` list. After the `get_history_page` route add:

```python
        @self.post("/get_object", tags=["private"])
        def get_object(kind: str, uuid: str):
            """One experiment or action by uuid, or null. Read-only, no lock."""
            return _object_payload(self, kind, uuid)
```

4. At the end of `_register_orch_ws_routes`, after `websocket_live`:

```python
        # /ws_orch is new, not inherited, so there is nothing to replace. Its
        # frames are plain dicts already (GroupSnapshot): identity xform.
        self.orch_graph_publisher = WsPublisher(self.orch_graph_q)

        @self.websocket("/ws_orch")
        async def websocket_orch(websocket: WebSocket):
            """Stream group snapshots; the cached latest one goes first."""
            await self.orch_graph_publisher.connect(websocket)
            try:
                if self.graph_feed.latest is not None:
                    await websocket.send_bytes(wire_dumps(self.graph_feed.latest))
                await self.orch_graph_publisher.broadcast(websocket)
            except (WebSocketDisconnect, ConnectionClosedOK):
                self.orch_graph_publisher.disconnect(websocket)
```

5. In `_orch_startup`, after `self.driver_monitor = asyncio.create_task(self.action_server_monitor())`:

```python
            self.graph_feed_task = asyncio.create_task(self.graph_feed.run())
```

6. In `orch_shutdown`, add `self.graph_feed_task,` to the `for task in (...)` tuple, and directly after that loop:

```python
        await self.orch_graph_q.close()
```

- [ ] **Step 6: Add the frozen surface entry by hand**

The frozen surface gate (`test_the_route_surface_matches_the_frozen_orchestrator_surface`) is exact both ways, so a new route needs its entry. Insert this object into `helao/hexagon/tests/checklists/orch_openapi.json` directly before the object whose `"path": "/get_orch_state"` (around line 820), matching the file's one-space indentation. Do not regenerate the file.

```json
  {
   "method": "post",
   "params": [
    {
     "in": "query",
     "name": "kind",
     "required": true,
     "type": "string"
    },
    {
     "in": "query",
     "name": "uuid",
     "required": true,
     "type": "string"
    }
   ],
   "path": "/get_object",
   "tags": [
    "private"
   ]
  },
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=. $PY -m pytest helao/hexagon/tests/test_orch_graph_feed.py helao/hexagon/tests/test_orch_host_surface.py helao/hexagon/tests/test_orch_host_member_coverage.py helao/hexagon/tests/test_group_snapshot.py -q`
Expected: all pass. If the surface params test reports drift on `/get_object`, the drift message shows the live params. Report it; do not edit the entry to match without saying so.

- [ ] **Step 8: Mutation check**

Back up the file first: `/usr/bin/cp helao/hexagon/app/orch_graph_feed.py /tmp/claude-1000/ogf.py`. Make each change, run `test_orch_graph_feed.py`, confirm the named test FAILS, then restore with `/usr/bin/cp /tmp/claude-1000/ogf.py helao/hexagon/app/orch_graph_feed.py`.
1. Delete the `if uid not in self._prev_active:` block that emits the early dispatch. Expect `test_an_action_seen_only_finished_still_yields_dispatch_then_finish` to fail.
2. Replace `if self._primed:` with `if True:`. Expect `test_first_frame_primes_without_replaying_old_finishes` to fail.
3. In `run`, remove the `try/except` (keep the body). Expect `test_an_exception_in_the_build_does_not_kill_the_task` to fail.
4. Replace `repr(v)` with `v` in `fingerprint`. Expect `test_unhashable_driver_status_does_not_break_the_fingerprint` to fail.
5. Change `now - self._last_sent < self.heartbeat_s` to `True`. Expect `test_unchanged_state_sends_nothing_but_the_heartbeat_still_arrives` to fail.
6. In `_object_payload`, delete the history loop. Expect `test_get_object_finds_each_tier_and_misses_with_null` to fail (restore from `git -C /mnt/STORAGE/repos/helao/helao-async diff`).
Re-run after restoring; all pass.

- [ ] **Step 9: Commit**

```bash
git -C /mnt/STORAGE/repos/helao/helao-async add helao/hexagon/app/orch_graph_feed.py helao/hexagon/app/orch_payloads.py helao/hexagon/app/orch_host.py helao/hexagon/tests/checklists/orch_openapi.json helao/hexagon/tests/test_orch_graph_feed.py
git -C /mnt/STORAGE/repos/helao/helao-async commit -m "feat(orch): read-only /ws_orch group feed and /get_object

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: `plots.marks_chart` and `netgraph.py`

`netgraph.py` must not import `xy`. It returns **mark dicts**, and `plots.marks_chart` is the one place they become xy calls.

Mark dict schema (shared by Tasks 5, 6 and 8):

| kind | keys |
|---|---|
| `line` | `name, x: list[float], y: list[float], color, width` |
| `scatter` | `name, x, y, colors: list[hex], size: float, symbol, opacity` |
| `text` | `x, y, value, dx, dy, color, anchor` |
| `band` | `x0, x1, color, opacity` |
| `vline` | `x, color, width` |

**Files:**
- Modify: `helao/ui/reflex/plots.py`: add `WHITE` to the `from helao.ui.shared.palette import (...)` block (`:36-42`); append `marks_chart`
- Create: `helao/ui/reflex/netgraph.py`
- Test: `helao/core/tests/test_reflex_plots.py` (append), `helao/core/tests/test_reflex_netgraph.py`

**Interfaces:**
- Consumes: Task 1 findings; `plots._publish`, `ChartPayload`; palette `GROUP_EDGE_TEXT`.
- Produces:
  - `plots.PLACEHOLDER_XY = 1e6`, `plots.ANNOTATIONS_IN_TOKEN = True`, `plots.CHART_PADDING_PX = 8`
  - `plots.marks_chart(marks, *, x_domain, y_domain, panel_id, version, click=False) -> ChartPayload`
  - `netgraph.NetGraph(height_px=360, width_px=720, domain=((-1.0, 1.0), (-1.0, 1.0)), padding_px=8)` with methods `add_node(key, x, y, *, color, label_color, text="", subtext="", size_px=28.0)`, `add_edge(edge_id, src, dst, *, color, text="", width=2.0)`, `add_arrowhead(edge_id, at="dst")`, `set_node_color(key, c)`, `set_node_text(key, s)`, `set_edge_color(edge_id, c)`, `set_edge_text(edge_id, s)`, `pulse(edge_id, *, t0, color, direction="fwd", duration=0.6)`, `ports() -> dict[str, tuple[tuple, tuple]]`, `marks(now) -> list[dict]`, attributes `sx`, `sy` (data units per px), `pulses: list[Pulse]`
  - `netgraph.Pulse(edge_id, direction, t0, duration, color)` dataclass
  - `netgraph.control_points(pa, pb)`, `bezier(pa, pb, n=24)`, `arc_table(pts, sx, sy)`, `point_at(pts, cum, s)`, `group_layout(orch_key, server_keys) -> dict[str, tuple[float, float]]`
  - constants `CURVE_SAMPLES = 24`, `FANOUT = 0.7`, `ARROW_PX = 10.0`, `PULSE_PX = 12.0`

- [ ] **Step 1: Write the failing `marks_chart` tests**

Append to `helao/core/tests/test_reflex_plots.py`:

```python
def _marks(color="#334155", text="ORCH", pulse_x=None):
    return [
        {"kind": "line", "name": "edge:A", "x": [0.0, 0.0], "y": [0.0, 0.7],
         "color": color, "width": 2.0},
        {"kind": "scatter", "name": "pulse:triangle", "x": [] if pulse_x is None else [pulse_x],
         "y": [] if pulse_x is None else [0.3], "colors": [] if pulse_x is None else ["#7c3aed"],
         "size": 12.0, "symbol": "triangle", "opacity": 1.0},
        {"kind": "text", "x": 0.0, "y": 0.0, "value": text, "dx": 0.0, "dy": 4.0,
         "color": "#ffffff", "anchor": "middle"},
    ]


def _mc(marks, **kw):
    return plots.marks_chart(marks, x_domain=(-1.0, 1.0), y_domain=(-1.0, 1.0),
                             panel_id="t-marks", version=1, **kw)


def test_marks_chart_maps_kinds_to_traces_and_annotations():
    p = _mc(_marks())
    assert [t["kind"] for t in p.spec["traces"]] == ["line", "scatter"]
    assert [a["kind"] for a in p.spec["annotations"]] == ["text"]
    assert p.spec["interaction"]["pan"] is False and p.spec["interaction"]["zoom"] is False


def test_marks_chart_pads_an_empty_scatter_so_its_colour_stays_direct():
    p = _mc(_marks())
    assert p.spec["traces"][1]["color"]["mode"] == "direct_rgba"
    assert p.spec["traces"][1]["n_points"] == 1


def test_a_moving_pulse_keeps_the_layout_but_a_new_colour_rebuilds():
    base = _mc(_marks(pulse_x=0.1)).layout
    assert _mc(_marks(pulse_x=0.5)).layout == base
    assert _mc(_marks(pulse_x=None)).layout == base
    assert _mc(_marks(color="#dc2626", pulse_x=0.1)).layout != base


def test_changed_annotation_text_rebuilds_while_annotations_are_in_the_token():
    assert plots.ANNOTATIONS_IN_TOKEN is True
    assert _mc(_marks(text="A")).layout != _mc(_marks(text="B")).layout


def test_marks_chart_rejects_an_unknown_kind():
    with pytest.raises(ValueError, match="unknown mark kind"):
        _mc([{"kind": "spiral"}])
```

The hex strings above live in a test file. The sweep's exemptions are exact paths and tests are swept too, so if `test_palette.py`'s whole-tree sweep flags them, replace each with a palette import (`from helao.ui.shared.palette import GROUP_IDLE, GROUP_ERROR, GROUP_PULSE_DISPATCH, WHITE`, used as `GROUP_IDLE`, `GROUP_ERROR`, `GROUP_PULSE_DISPATCH`, `WHITE`). Prefer the imports from the start.

- [ ] **Step 2: Run to verify failure**

Run: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=. $PY -m pytest helao/core/tests/test_reflex_plots.py -q -k marks`
Expected: FAIL with `AttributeError: module 'helao.ui.reflex.plots' has no attribute 'marks_chart'`.

- [ ] **Step 3: Implement `marks_chart`**

Add `WHITE,` to the palette import block in `plots.py`, then append:

```python
#: Off-domain stand-in for an empty scatter/line. xy encodes an EMPTY colour list
#: as a continuous colormap rather than direct RGBA, so a trace that empties
#: would change its column layout under an unchanged layout token.
PLACEHOLDER_XY = 1e6

#: Annotations (text, bands, rules) are spec, not columns. Until a browser check
#: shows xy's append path applies a changed annotation in place, their content
#: joins the layout token and a changed label rebuilds the chart.
ANNOTATIONS_IN_TOKEN = True

#: Plot padding on every side, in px. netgraph's px <-> data scale assumes it.
CHART_PADDING_PX = 8


def marks_chart(marks, *, x_domain, y_domain, panel_id, version, click=False) -> ChartPayload:
    """Render plain mark dicts (see ``netgraph``/``timeline_strip``) on a fixed view.

    Axes and grid hidden, pan/zoom off, domain fixed. Column data (x, y,
    per-point colours) updates in place; anything that is spec -- line colour
    and width, scatter symbol/size/opacity, and annotations while
    :data:`ANNOTATIONS_IN_TOKEN` -- joins the layout token.
    """
    children, style, notes = [], [], []
    for m in marks:
        kind = m.get("kind")
        if kind == "line":
            xs, ys = list(m["x"]), list(m["y"])
            if not xs:
                xs, ys = [PLACEHOLDER_XY] * 2, [PLACEHOLDER_XY] * 2
            children.append(
                xy.line(x=np.asarray(xs, float), y=np.asarray(ys, float),
                        name=m["name"], color=m["color"], width=float(m["width"]))
            )
            style.append(f"{m['name']}:{m['color']}:{m['width']}")
        elif kind == "scatter":
            xs, ys, cs = list(m["x"]), list(m["y"]), list(m["colors"])
            if not xs:
                xs, ys, cs = [PLACEHOLDER_XY], [PLACEHOLDER_XY], [WHITE]
            children.append(
                xy.scatter(x=np.asarray(xs, float), y=np.asarray(ys, float), color=cs,
                           size=float(m["size"]), symbol=m["symbol"],
                           opacity=float(m.get("opacity", 1.0)), name=m["name"])
            )
            style.append(f"{m['name']}:{m['symbol']}:{m['size']}:{m.get('opacity', 1.0)}")
        elif kind == "text":
            children.append(
                xy.text(float(m["x"]), float(m["y"]), str(m["value"]),
                        dx=float(m.get("dx", 0.0)), dy=float(m.get("dy", 0.0)),
                        color=m["color"], anchor=m.get("anchor", "middle"))
            )
            notes.append(repr(sorted(m.items())))
        elif kind == "band":
            children.append(
                xy.x_band(float(m["x0"]), float(m["x1"]), color=m["color"],
                          opacity=float(m.get("opacity", 1.0)))
            )
            notes.append(repr(sorted(m.items())))
        elif kind == "vline":
            children.append(xy.vline(float(m["x"]), color=m["color"], width=float(m.get("width", 1.0))))
            notes.append(repr(sorted(m.items())))
        else:
            raise ValueError(f"unknown mark kind {kind!r}")
    axes = [
        xy.x_axis(show=False, grid=False, domain=tuple(x_domain)),
        xy.y_axis(show=False, grid=False, domain=tuple(y_domain)),
        xy.legend(show=False),
    ]
    pad = CHART_PADDING_PX
    figure = xy.chart(*children, *axes, width="100%", height="100%",
                      padding=[pad, pad, pad, pad], pan=False, zoom=False, click=click)
    parts = style + (notes if ANNOTATIONS_IN_TOKEN else [])
    digest = hashlib.blake2b("|".join(parts).encode(), digest_size=8).hexdigest()
    return _publish(figure, panel_id, version,
                    layout_extra=f"marks={digest}{tuple(x_domain)}{tuple(y_domain)}{click}")
```

Confirm `hashlib` is already imported at the top of `plots.py` (it is used by `_underlay_mark`). If it is not, add `import hashlib`.

- [ ] **Step 4: Run to verify the plots tests pass**

Run: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=. $PY -m pytest helao/core/tests/test_reflex_plots.py -q`
Expected: all pass.

- [ ] **Step 5: Write the failing netgraph tests**

`helao/core/tests/test_reflex_netgraph.py`:

```python
"""netgraph: pure geometry for the /group network graph."""

import math

import pytest

from helao.ui.shared.palette import GROUP_IDLE, GROUP_PULSE_DISPATCH, WHITE


def _g():
    from helao.ui.reflex.netgraph import NetGraph

    g = NetGraph(height_px=360, width_px=720)
    g.add_node("ORCH", 0.0, 0.0, color=GROUP_IDLE, label_color=WHITE, text="ORCH")
    return g


def _trace(marks, name):
    return next(m for m in marks if m.get("name") == name)


def test_ports_face_each_other_by_relative_y():
    g = _g()
    g.add_node("UP", 0.0, 0.7, color=GROUP_IDLE, label_color=WHITE)
    g.add_node("DN", 0.5, -0.7, color=GROUP_IDLE, label_color=WHITE)
    g.add_edge("UP", "ORCH", "UP", color=GROUP_IDLE)
    g.add_edge("DN", "ORCH", "DN", color=GROUP_IDLE)
    ry = 14.0 * g.sy
    ports = g.ports()
    assert ports["UP"][0][1] == pytest.approx(ry)  # leaves ORCH from its top
    assert ports["UP"][1][1] == pytest.approx(0.7 - ry)  # enters UP from its bottom
    assert ports["DN"][0][1] == pytest.approx(-ry)
    assert ports["DN"][1][1] == pytest.approx(-0.7 + ry)


def test_bezier_end_tangents_are_vertical():
    from helao.ui.reflex.netgraph import bezier, control_points

    p0, p1, p2, p3 = control_points((-0.3, 0.1), (0.6, 0.6))
    assert p1[0] == p0[0] and p2[0] == p3[0]
    assert p1[1] > p0[1] and p2[1] < p3[1]
    pts = bezier((-0.3, 0.1), (0.6, 0.6))
    assert len(pts) == 24 and pts[0] == pytest.approx((-0.3, 0.1)) and pts[-1] == pytest.approx((0.6, 0.6))


def test_arrowhead_symbol_follows_direction():
    g = _g()
    g.add_node("UP", 0.0, 0.7, color=GROUP_IDLE, label_color=WHITE)
    g.add_node("DN", 0.0, -0.7, color=GROUP_IDLE, label_color=WHITE)
    g.add_edge("UP", "ORCH", "UP", color=GROUP_IDLE)
    g.add_edge("DN", "ORCH", "DN", color=GROUP_IDLE)
    g.add_arrowhead("UP", at="dst")
    g.add_arrowhead("DN", at="dst")
    marks = g.marks(0.0)
    assert len(_trace(marks, "arrow:triangle")["x"]) == 1
    assert len(_trace(marks, "arrow:triangle_down")["x"]) == 1


def test_pulse_positions_and_expiry():
    from helao.ui.reflex.netgraph import arc_table, bezier, point_at

    g = _g()
    g.add_node("UP", 0.4, 0.7, color=GROUP_IDLE, label_color=WHITE)
    g.add_edge("UP", "ORCH", "UP", color=GROUP_IDLE)
    g.pulse("UP", t0=10.0, duration=1.0, color=GROUP_PULSE_DISPATCH)
    pa, pb = g.ports()["UP"]
    pts = bezier(pa, pb)
    cum = arc_table(pts, g.sx, g.sy)

    at0 = _trace(g.marks(10.0), "pulse:triangle")
    assert (at0["x"][0], at0["y"][0]) == pytest.approx(pa)
    mid = _trace(g.marks(10.5), "pulse:triangle")
    assert (mid["x"][0], mid["y"][0]) == pytest.approx(point_at(pts, cum, 0.5))
    assert pa[1] < mid["y"][0] < pb[1]
    gone = g.marks(11.0)
    assert _trace(gone, "pulse:triangle")["x"] == [] and g.pulses == []


def test_reverse_pulse_starts_at_the_destination_and_points_down():
    g = _g()
    g.add_node("UP", 0.0, 0.7, color=GROUP_IDLE, label_color=WHITE)
    g.add_edge("UP", "ORCH", "UP", color=GROUP_IDLE)
    g.pulse("UP", t0=0.0, duration=1.0, color=GROUP_PULSE_DISPATCH, direction="rev")
    pa, pb = g.ports()["UP"]
    down = _trace(g.marks(0.0), "pulse:triangle_down")
    assert (down["x"][0], down["y"][0]) == pytest.approx(pb)


def test_fan_out_ports_are_distinct():
    g = _g()
    for i, x in enumerate((-0.6, 0.0, 0.6)):
        g.add_node(f"S{i}", x, 0.7, color=GROUP_IDLE, label_color=WHITE)
        g.add_edge(f"S{i}", "ORCH", f"S{i}", color=GROUP_IDLE)
    xs = [g.ports()[f"S{i}"][0][0] for i in range(3)]
    assert len(set(xs)) == 3 and xs == sorted(xs)
    assert max(abs(x) for x in xs) == pytest.approx(0.7 * 14.0 * g.sx)


def test_layout_alternates_rows_and_adds_a_second_band():
    from helao.ui.reflex.netgraph import group_layout

    pos = group_layout("ORCH", ["C", "A", "B"])
    assert pos["ORCH"] == (0.0, 0.0)
    assert [math.copysign(1, pos[k][1]) for k in ("A", "B", "C")] == [1, -1, 1]
    assert {abs(pos[k][1]) for k in "ABC"} == {0.7}
    many = group_layout("ORCH", [f"S{i:02d}" for i in range(20)])
    assert {round(y, 2) for k, (x, y) in many.items() if k != "ORCH"} == {0.4, 0.9, -0.4, -0.9}


def test_node_label_is_centred_and_subtext_sits_away_from_the_orch():
    g = _g()
    g.add_node("UP", 0.0, 0.7, color=GROUP_IDLE, label_color=WHITE, text="UP", subtext="move")
    texts = {m["value"]: m for m in g.marks(0.0) if m["kind"] == "text"}
    assert texts["UP"]["anchor"] == "middle" and texts["UP"]["y"] == 0.7
    assert texts["move"]["y"] > 0.7  # above an upper node


def test_netgraph_does_not_import_xy():
    import helao.ui.reflex.netgraph as ng

    assert "xy" not in vars(ng)
```

- [ ] **Step 6: Run to verify failure**

Run: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=. $PY -m pytest helao/core/tests/test_reflex_netgraph.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'helao.ui.reflex.netgraph'`.

- [ ] **Step 7: Implement `netgraph.py`**

```python
"""Pure geometry for the /group network graph.

No Reflex state and no xy import: :meth:`NetGraph.marks` returns plain mark
dicts that :func:`helao.ui.reflex.plots.marks_chart` renders. Marker sizes are
in px and ports in data units, so the chart has a fixed domain, a fixed pixel
size and padding (``plots.CHART_PADDING_PX``); ``sx``/``sy`` convert between
them. Markers cannot rotate, so every curve ends vertically: a cubic Bezier
whose end tangents are vertical, which lets a ``triangle`` (up) or
``triangle_down`` sit flush at either end.
"""

import bisect
import math
from dataclasses import dataclass, field

from helao.ui.shared.palette import GROUP_EDGE_TEXT

CURVE_SAMPLES = 24
FANOUT = 0.7
ARROW_PX = 10.0
PULSE_PX = 12.0
SYMBOLS = ("triangle", "triangle_down")


@dataclass
class Node:
    key: str
    x: float
    y: float
    color: str
    label_color: str
    text: str = ""
    subtext: str = ""
    size_px: float = 28.0


@dataclass
class Edge:
    edge_id: str
    src: str
    dst: str
    color: str
    text: str = ""
    width: float = 2.0
    arrow_at: set = field(default_factory=set)


@dataclass
class Pulse:
    edge_id: str
    direction: str
    t0: float
    duration: float
    color: str


def control_points(pa, pb):
    """P0..P3 with vertical end tangents: ``d = 0.5*|dy|`` toward the other end."""
    (xa, ya), (xb, yb) = pa, pb
    d = 0.5 * abs(yb - ya)
    s = 1.0 if yb >= ya else -1.0
    return (xa, ya), (xa, ya + s * d), (xb, yb - s * d), (xb, yb)


def bezier(pa, pb, n=CURVE_SAMPLES):
    """The curve sampled at ``n`` points, ends included."""
    p0, p1, p2, p3 = control_points(pa, pb)
    pts = []
    for i in range(n):
        t = i / (n - 1)
        u = 1.0 - t
        a, b, c, d = u**3, 3 * u * u * t, 3 * u * t * t, t**3
        pts.append(
            (a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
             a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1])
        )
    return pts


def arc_table(pts, sx, sy):
    """Cumulative arc length in px, so a pulse moves at even screen speed."""
    cum = [0.0]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        cum.append(cum[-1] + math.hypot((x1 - x0) / sx, (y1 - y0) / sy))
    return cum


def point_at(pts, cum, s):
    """The point at arc-length fraction ``s`` (clamped to [0, 1])."""
    s = min(max(s, 0.0), 1.0)
    target = s * cum[-1]
    i = bisect.bisect_left(cum, target)
    if i <= 0:
        return pts[0]
    if i >= len(cum):
        return pts[-1]
    seg = cum[i] - cum[i - 1]
    f = 0.0 if seg == 0 else (target - cum[i - 1]) / seg
    (x0, y0), (x1, y1) = pts[i - 1], pts[i]
    return (x0 + f * (x1 - x0), y0 + f * (y1 - y0))


def group_layout(orch_key, server_keys):
    """Orchestrator at (0, 0); servers sorted, alternating above/below.

    Up to 8 per row sit at y = +/-0.7, evenly spaced in x; above 8 a row splits
    into two bands at +/-0.4 and +/-0.9.
    """
    keys = sorted(server_keys)
    pos = {orch_key: (0.0, 0.0)}
    for row, sign in ((keys[0::2], 1.0), (keys[1::2], -1.0)):
        bands = [(row, 0.7)] if len(row) <= 8 else [(row[0::2], 0.4), (row[1::2], 0.9)]
        for band, y in bands:
            n = len(band)
            for i, key in enumerate(band):
                pos[key] = (-0.9 + 1.8 * (i + 0.5) / n, sign * y)
    return pos


class NetGraph:
    """Nodes, edges, arrowheads and pulses on a fixed view."""

    def __init__(self, height_px=360, width_px=720, domain=((-1.0, 1.0), (-1.0, 1.0)), padding_px=8):
        (x0, x1), (y0, y1) = domain
        self.domain = domain
        self.sx = (x1 - x0) / (width_px - 2 * padding_px)
        self.sy = (y1 - y0) / (height_px - 2 * padding_px)
        self.nodes: dict = {}
        self.edges: dict = {}
        self.pulses: list = []

    def add_node(self, key, x, y, *, color, label_color, text="", subtext="", size_px=28.0):
        self.nodes[key] = Node(key, float(x), float(y), color, label_color, text, subtext, float(size_px))

    def add_edge(self, edge_id, src, dst, *, color, text="", width=2.0):
        self.edges[edge_id] = Edge(edge_id, src, dst, color, text, float(width))

    def add_arrowhead(self, edge_id, at="dst"):
        self.edges[edge_id].arrow_at.add(at)

    def set_node_color(self, key, c):
        self.nodes[key].color = c

    def set_node_text(self, key, s):
        self.nodes[key].text = s

    def set_edge_color(self, edge_id, c):
        self.edges[edge_id].color = c

    def set_edge_text(self, edge_id, s):
        self.edges[edge_id].text = s

    def pulse(self, edge_id, *, t0, color, direction="fwd", duration=0.6):
        self.pulses.append(Pulse(edge_id, direction, float(t0), float(duration), color))

    def ports(self):
        """edge_id -> (src port, dst port), fanned out where ends share a side."""
        ends: dict = {}
        for e in self.edges.values():
            a, b = self.nodes[e.src], self.nodes[e.dst]
            ends.setdefault((a.key, "top" if b.y > a.y else "bottom"), []).append((b.x, e.edge_id, 0))
            ends.setdefault((b.key, "top" if a.y > b.y else "bottom"), []).append((a.x, e.edge_id, 1))
        out = {eid: [None, None] for eid in self.edges}
        for (key, side), items in ends.items():
            n = self.nodes[key]
            rx = n.size_px / 2 * self.sx
            ry = n.size_px / 2 * self.sy
            y = n.y + ry if side == "top" else n.y - ry
            items.sort()
            k = len(items)
            for i, (_, eid, end) in enumerate(items):
                off = 0.0 if k == 1 else (-FANOUT + 2 * FANOUT * i / (k - 1)) * rx
                out[eid][end] = (n.x + off, y)
        return {eid: (p[0], p[1]) for eid, p in out.items()}

    def marks(self, now):
        """Mark dicts for ``plots.marks_chart``. Drops pulses with s >= 1.

        Every scatter trace is always present (possibly empty), so the trace
        set -- and the layout token -- does not change as pulses come and go.
        """
        self.pulses = [p for p in self.pulses if (now - p.t0) / p.duration < 1.0]
        ports = self.ports()
        lines, texts, curves = [], [], {}
        arrows = {sym: ([], [], []) for sym in SYMBOLS}
        moving = {sym: ([], [], []) for sym in SYMBOLS}
        for eid in sorted(self.edges):
            e = self.edges[eid]
            pa, pb = ports[eid]
            pts = bezier(pa, pb)
            curves[eid] = (pts, arc_table(pts, self.sx, self.sy))
            lines.append({"kind": "line", "name": f"edge:{eid}", "x": [p[0] for p in pts],
                          "y": [p[1] for p in pts], "color": e.color, "width": e.width})
            for at in sorted(e.arrow_at):
                tip, other = (pb, pa) if at == "dst" else (pa, pb)
                up = tip[1] > other[1]
                half = ARROW_PX / 2 * self.sy
                xs, ys, cs = arrows["triangle" if up else "triangle_down"]
                xs.append(tip[0])
                ys.append(tip[1] - half if up else tip[1] + half)
                cs.append(e.color)
            if e.text:
                mx, my = pts[len(pts) // 2]
                texts.append({"kind": "text", "x": mx, "y": my, "value": e.text, "dx": 6.0,
                              "dy": 0.0, "color": GROUP_EDGE_TEXT, "anchor": "start"})
        for p in self.pulses:
            if p.edge_id not in curves:
                continue
            pts, cum = curves[p.edge_id]
            s = max(0.0, (now - p.t0) / p.duration)
            x, y = point_at(pts, cum, s if p.direction == "fwd" else 1.0 - s)
            up = (pts[-1][1] > pts[0][1]) == (p.direction == "fwd")
            xs, ys, cs = moving["triangle" if up else "triangle_down"]
            xs.append(x)
            ys.append(y)
            cs.append(p.color)
        by_size: dict = {}
        for n in self.nodes.values():
            xs, ys, cs = by_size.setdefault(n.size_px, ([], [], []))
            xs.append(n.x)
            ys.append(n.y)
            cs.append(n.color)
            if n.text:
                texts.append({"kind": "text", "x": n.x, "y": n.y, "value": n.text, "dx": 0.0,
                              "dy": 4.0, "color": n.label_color, "anchor": "middle"})
            if n.subtext:
                ry = n.size_px / 2 * self.sy
                above = n.y > 0
                texts.append({"kind": "text", "x": n.x, "y": n.y + ry if above else n.y - ry,
                              "value": n.subtext, "dx": 0.0, "dy": -6.0 if above else 14.0,
                              "color": GROUP_EDGE_TEXT, "anchor": "middle"})

        def scatter(name, xs, ys, cs, size, symbol):
            return {"kind": "scatter", "name": name, "x": xs, "y": ys, "colors": cs,
                    "size": size, "symbol": symbol, "opacity": 1.0}

        out = list(lines)
        out += [scatter(f"arrow:{s}", *arrows[s], ARROW_PX, s) for s in SYMBOLS]
        out += [scatter(f"nodes:{size:g}", *by_size[size], size, "circle") for size in sorted(by_size)]
        out += [scatter(f"pulse:{s}", *moving[s], PULSE_PX, s) for s in SYMBOLS]
        return out + texts
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=. $PY -m pytest helao/core/tests/test_reflex_netgraph.py helao/core/tests/test_reflex_plots.py helao/core/tests/test_reflex_config.py -q`
Expected: all pass (`test_reflex_config.py` holds `test_only_plots_module_imports_xy`).

- [ ] **Step 9: Commit**

```bash
git -C /mnt/STORAGE/repos/helao/helao-async add helao/ui/reflex/plots.py helao/ui/reflex/netgraph.py helao/core/tests/test_reflex_plots.py helao/core/tests/test_reflex_netgraph.py
git -C /mnt/STORAGE/repos/helao/helao-async commit -m "feat(reflex): marks_chart facade and pure netgraph geometry

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: `timeline_strip.py`

**Files:**
- Create: `helao/ui/reflex/timeline_strip.py`
- Test: `helao/core/tests/test_reflex_timeline_strip.py`

**Interfaces:**
- Consumes: the mark schema (Task 5); palette `GROUP_STATE_COLORS`, `GROUP_LABEL_COLORS`, `GROUP_SELECTED_OUTLINE`, `GROUP_PROGRESS`, `CHART_CHROME`; snapshot item dicts (Task 3).
- Produces:
  - `NARROW_PX = 90`, `SAWTOOTH_HZ = 2.0`
  - `fmt_hms(t: float, today: date) -> str`, `fmt_elapsed(sec: float) -> str`
  - `segment_label(item: dict, now: float, narrow: bool, today: date) -> tuple[str, str]` (line 1, line 2)
  - `item_key(item: dict) -> str | None`: uuid, else `f"q{qidx}"`
  - `strip_marks(items, *, n_before, n_after, now, width_px, selected=None, today=None) -> tuple[list[dict], list[dict | None]]`: `(marks, slots)`; a `None` slot is a `+N` ellipsis
  - `click_item(slots, x) -> dict | None`

The spec's "known expected duration" progress mode has no data source (no snapshot field carries an expected duration), so only the 2 Hz sawtooth is built. See Open questions.

- [ ] **Step 1: Write the failing tests**

```python
"""timeline_strip: pure marks, labels and click mapping for one strip."""

from datetime import date, datetime

T0 = datetime(2026, 11, 6, 10, 0, 0).timestamp()
TODAY = date(2026, 11, 6)


def _item(state, t0=T0, t1=None, name="exp", uuid="u1", qidx=None):
    return {"uuid": uuid, "name": name, "state": state, "t_start": t0, "t_end": t1, "qidx": qidx}


def test_done_label():
    from helao.ui.reflex.timeline_strip import segment_label

    assert segment_label(_item("done", t1=T0 + 65), T0 + 100, False, TODAY) == ("exp", "10:00:00–10:01:05")


def test_active_label_carries_elapsed():
    from helao.ui.reflex.timeline_strip import segment_label

    assert segment_label(_item("active"), T0 + 125, False, TODAY) == ("exp", "10:00:00– (2:05)")
    assert segment_label(_item("active"), T0 + 3725, False, TODAY)[1] == "10:00:00– (1:02:05)"


def test_queued_label_has_no_time():
    from helao.ui.reflex.timeline_strip import segment_label

    assert segment_label(_item("queued", t0=None), T0, False, TODAY) == ("exp", "")


def test_narrow_label_is_start_time_only():
    from helao.ui.reflex.timeline_strip import segment_label

    assert segment_label(_item("done", t1=T0 + 5), T0 + 9, True, TODAY) == ("", "10:00:00")


def test_cross_day_prefix():
    from helao.ui.reflex.timeline_strip import segment_label

    line2 = segment_label(_item("done", t1=T0 + 65), T0, False, date(2026, 11, 7))[1]
    assert line2 == "11-06 10:00:00–11-06 10:01:05"


def test_window_ellipses_and_click_mapping():
    from helao.ui.reflex.timeline_strip import click_item, strip_marks

    items = [_item("done", uuid="a", t1=T0 + 1), _item("active", uuid="b"), _item("queued", t0=None, uuid=None, qidx=0)]
    marks, slots = strip_marks(items, n_before=20, n_after=3, now=T0 + 5, width_px=720, today=TODAY)
    assert slots[0] is None and slots[-1] is None and len(slots) == 5
    values = [m["value"] for m in marks if m["kind"] == "text"]
    assert "+20" in values and "+3" in values
    assert click_item(slots, 2.4)["uuid"] == "b"
    assert click_item(slots, 0.5) is None  # ellipsis
    assert click_item(slots, 9.0) is None and click_item(slots, -0.1) is None


def test_selected_segment_is_outlined_and_unknown_state_is_queued_colour():
    from helao.ui.reflex.timeline_strip import strip_marks
    from helao.ui.shared.palette import GROUP_SELECTED_OUTLINE, GROUP_STATE_COLORS

    items = [_item("done", uuid="a", t1=T0 + 1), _item("weird", uuid="b")]
    marks, _ = strip_marks(items, n_before=0, n_after=0, now=T0, width_px=720, selected="b", today=TODAY)
    outlines = [m["x"] for m in marks if m["kind"] == "vline" and m["color"] == GROUP_SELECTED_OUTLINE]
    assert outlines == [1, 2]
    bands = [m["color"] for m in marks if m["kind"] == "band"]
    assert bands == [GROUP_STATE_COLORS["done"], GROUP_STATE_COLORS["queued"]]


def test_strip_always_has_the_progress_and_hit_traces():
    from helao.ui.reflex.timeline_strip import strip_marks

    marks, _ = strip_marks([], n_before=0, n_after=0, now=T0, width_px=720, today=TODAY)
    assert [m["name"] for m in marks if m["kind"] in ("line", "scatter")] == ["progress", "hit"]
    marks, _ = strip_marks([_item("active")], n_before=0, n_after=0, now=T0 + 0.25, width_px=720, today=TODAY)
    progress = next(m for m in marks if m.get("name") == "progress")
    assert progress["x"][0] == 0 and 0.0 <= progress["x"][1] - progress["x"][0] < 1.0


def test_item_key_prefers_uuid_then_queue_index():
    from helao.ui.reflex.timeline_strip import item_key

    assert item_key({"uuid": "x", "qidx": None}) == "x"
    assert item_key({"uuid": None, "qidx": 4}) == "q4"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=. $PY -m pytest helao/core/tests/test_reflex_timeline_strip.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'helao.ui.reflex.timeline_strip'`.

- [ ] **Step 3: Implement**

```python
"""Pure marks for one /group timeline strip (experiments or actions).

Ordinal: every item is one equal-width segment on x in [0, n), whatever its
duration. A ``None`` slot is a ``+N`` ellipsis marking a cut end of the window.
Times are station-local; a date prefix appears when a time is not today.
"""

import math
from datetime import date, datetime

from helao.ui.shared.palette import (
    CHART_CHROME,
    GROUP_LABEL_COLORS,
    GROUP_PROGRESS,
    GROUP_SELECTED_OUTLINE,
    GROUP_STATE_COLORS,
)

NARROW_PX = 90
SAWTOOTH_HZ = 2.0


def fmt_hms(t, today):
    d = datetime.fromtimestamp(t)
    hms = d.strftime("%H:%M:%S")
    return hms if d.date() == today else d.strftime("%m-%d ") + hms


def fmt_elapsed(sec):
    sec = max(0, int(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def segment_label(item, now, narrow, today):
    """``(line 1, line 2)``: name, then times. Narrow: start time only."""
    t0, t1 = item.get("t_start"), item.get("t_end")
    if narrow:
        return "", (fmt_hms(t0, today) if t0 is not None else "")
    name = item.get("name") or ""
    if t0 is None:
        return name, ""
    if item.get("state") == "active" or t1 is None:
        return name, f"{fmt_hms(t0, today)}– ({fmt_elapsed(now - t0)})"
    return name, f"{fmt_hms(t0, today)}–{fmt_hms(t1, today)}"


def item_key(item):
    """Selection identity: the uuid, else the queue index (queued experiments)."""
    if item.get("uuid"):
        return item["uuid"]
    return f"q{item['qidx']}" if item.get("qidx") is not None else None


def click_item(slots, x):
    """The item under data-space ``x``, or None for an ellipsis or a miss."""
    if x is None or not math.isfinite(float(x)):
        return None
    i = math.floor(float(x))
    return slots[i] if 0 <= i < len(slots) else None


def _text(x, y, value, color):
    return {"kind": "text", "x": x, "y": y, "value": value, "dx": 0.0, "dy": 4.0,
            "color": color, "anchor": "middle"}


def _vline(x, color, width):
    return {"kind": "vline", "x": x, "color": color, "width": width}


def strip_marks(items, *, n_before, n_after, now, width_px, selected=None, today=None):
    """``(marks, slots)`` for one strip; render with x_domain ``(0, max(len(slots), 1))``."""
    today = today or date.today()
    slots = ([None] if n_before else []) + list(items) + ([None] if n_after else [])
    n = max(len(slots), 1)
    narrow = width_px / n < NARROW_PX
    bands, outlines, texts = [], [], []
    progress = {"kind": "line", "name": "progress", "x": [], "y": [], "color": GROUP_PROGRESS, "width": 4.0}
    for i, it in enumerate(slots):
        cx = i + 0.5
        if it is None:
            count = n_before if (i == 0 and n_before) else n_after
            bands.append({"kind": "band", "x0": i, "x1": i + 1, "color": GROUP_STATE_COLORS["queued"], "opacity": 1.0})
            texts.append(_text(cx, 0.5, f"+{count}", GROUP_LABEL_COLORS["queued"]))
            continue
        state = it.get("state")
        if state not in GROUP_STATE_COLORS:
            state = "queued"
        bands.append({"kind": "band", "x0": i, "x1": i + 1, "color": GROUP_STATE_COLORS[state], "opacity": 1.0})
        line1, line2 = segment_label(it, now, narrow, today)
        if line1:
            texts.append(_text(cx, 0.68, line1, GROUP_LABEL_COLORS[state]))
        if line2:
            texts.append(_text(cx, 0.32, line2, GROUP_LABEL_COLORS[state]))
        if state == "active":
            frac = (now * SAWTOOTH_HZ) % 1.0
            progress["x"], progress["y"] = [i, i + frac], [0.08, 0.08]
        if selected is not None and item_key(it) == selected:
            outlines += [_vline(i, GROUP_SELECTED_OUTLINE, 3.0), _vline(i + 1, GROUP_SELECTED_OUTLINE, 3.0)]
    partitions = [_vline(i, CHART_CHROME["--chart-axis"], 1.0) for i in range(1, n)]
    hit = {"kind": "scatter", "name": "hit", "x": [i + 0.5 for i in range(len(slots))],
           "y": [0.5] * len(slots), "colors": [GROUP_STATE_COLORS["queued"]] * len(slots),
           "size": 4.0, "symbol": "circle", "opacity": 0.0}
    return bands + partitions + outlines + [progress, hit] + texts, slots
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=. $PY -m pytest helao/core/tests/test_reflex_timeline_strip.py helao/core/tests/test_palette.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git -C /mnt/STORAGE/repos/helao/helao-async add helao/ui/reflex/timeline_strip.py helao/core/tests/test_reflex_timeline_strip.py
git -C /mnt/STORAGE/repos/helao/helao-async commit -m "feat(reflex): pure ordinal timeline strip marks

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: `RemoteBackend.get_object`, strict control calls, shared tree pane

**Files:**
- Modify: `helao/ui/shared/operator/orch_backend.py` (`get_queue_object` at `:171`; `start`/`stop`/`estop`/`clear_estop` at `:250-263`)
- Create: `helao/ui/reflex/tree_pane.py`
- Modify: `helao/ui/reflex/operator.py`: delete `def _tree_pane` (`:2747-2765`) and import it instead. This is the only change to `operator.py`.
- Test: `helao/core/tests/test_orch_backend_group.py`

**Interfaces:**
- Produces:
  - `RemoteBackend.get_object(kind: str, uuid) -> dict | None`
  - `RemoteBackend.start(strict=False)`, `.stop(reset_run_id=False, strict=False)`, `.estop(strict=False)`, `.clear_estop(strict=False)`. With `strict=True` a failed call raises `RuntimeError("<endpoint> failed: <err>")`. The default is unchanged.
  - `helao.ui.reflex.tree_pane.tree_pane(header_var, html_var) -> rx.Component`

- [ ] **Step 1: Write the failing tests**

```python
"""RemoteBackend additions used by the /group page."""

import pytest

from helao.core.error import ErrorCodes


def _backend(resp=None, err=ErrorCodes.none):
    from helao.ui.shared.operator.orch_backend import RemoteBackend

    calls = []

    async def dispatch(server_key, host, port, endpoint, params_dict=None, json_dict=None):
        calls.append((endpoint, params_dict))
        return resp, err

    b = RemoteBackend.__new__(RemoteBackend)  # only the transport fields _call reads
    b.orch_key, b.host, b.port, b._dispatch = "ORCH", "127.0.0.1", 8001, dispatch
    return b, calls


@pytest.mark.asyncio
async def test_get_object_posts_kind_and_uuid_as_strings():
    b, calls = _backend(resp={"action_name": "a"})
    assert await b.get_object("action", 123) == {"action_name": "a"}
    assert calls == [("get_object", {"kind": "action", "uuid": "123"})]


@pytest.mark.asyncio
async def test_get_object_miss_is_none():
    b, _ = _backend(resp=None)
    assert await b.get_object("experiment", "x") is None


@pytest.mark.asyncio
async def test_strict_control_calls_raise_and_default_ones_do_not():
    b, calls = _backend(err=ErrorCodes.http)
    await b.start()
    with pytest.raises(RuntimeError, match="start failed"):
        await b.start(strict=True)
    with pytest.raises(RuntimeError, match="stop failed"):
        await b.stop(strict=True)
    with pytest.raises(RuntimeError, match="estop_orch failed"):
        await b.estop(strict=True)
    with pytest.raises(RuntimeError, match="clear_estop failed"):
        await b.clear_estop(strict=True)
    assert ("stop", {"reset_run_id": False}) in calls


def test_tree_pane_is_shared_by_the_operator():
    from helao.ui.reflex import operator, tree_pane

    assert operator._tree_pane is tree_pane.tree_pane
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=. $PY -m pytest helao/core/tests/test_orch_backend_group.py -q`
Expected: FAIL with `AttributeError: 'RemoteBackend' object has no attribute 'get_object'` and `ModuleNotFoundError ... tree_pane`.

- [ ] **Step 3: Implement the backend changes**

After `get_queue_object` in `orch_backend.py`:

```python
    async def get_object(self, kind, uuid):
        """One experiment or action by uuid (``/get_object``), or ``None``.

        ``None`` covers both "not found" and "orchestrator unreachable"; the
        /group info box shows the empty state either way.
        """
        return await self._call("get_object", params_dict={"kind": kind, "uuid": str(uuid)})
```

Replace the four control methods with:

```python
    async def start(self, strict: bool = False):
        await self._call("start", strict=strict)

    async def stop(self, reset_run_id: bool = False, strict: bool = False):
        await self._call("stop", params_dict={"reset_run_id": reset_run_id}, strict=strict)

    async def estop(self, strict: bool = False):
        await self._call("estop_orch", strict=strict)

    async def clear_estop(self, strict: bool = False):
        await self._call("clear_estop", strict=strict)
```

- [ ] **Step 4: Move the tree pane**

Create `helao/ui/reflex/tree_pane.py` with the body moved verbatim from `operator.py`:

```python
"""The attribute-tree pane shared by /operator and /group."""

import reflex as rx


def tree_pane(header_var, html_var):
    """The attribute tree beside a set of tables.

    Mirrors the Bokeh operator's header Div plus tree Div. The HTML is nested
    ``<details>``, so expanding a node needs no round trip.
    """
    return rx.vstack(
        rx.text(header_var, weight="bold", size="1"),
        rx.scroll_area(
            rx.html(html_var),
            type="auto",
            scrollbars="vertical",
            height="14em",
        ),
        width="100%",
        spacing="1",
        font_size="0.8em",
    )
```

In `operator.py`, delete the whole `def _tree_pane(header_var, html_var): ...` function and add next to `from helao.ui.reflex import plots`:

```python
from helao.ui.reflex.tree_pane import tree_pane as _tree_pane
```

- [ ] **Step 5: Run tests and the operator gates**

Run: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=. $PY -m pytest helao/core/tests/test_orch_backend_group.py helao/core/tests/test_reflex_operator.py helao/deploy/hte/tests/test_standalone_operator.py -q`
Expected: all pass, with `helao/ui/bokeh/operator.py` unedited (`git -C /mnt/STORAGE/repos/helao/helao-async diff --stat -- helao/ui/bokeh/operator.py` is empty).

- [ ] **Step 6: Commit**

```bash
git -C /mnt/STORAGE/repos/helao/helao-async add helao/ui/shared/operator/orch_backend.py helao/ui/reflex/tree_pane.py helao/ui/reflex/operator.py helao/core/tests/test_orch_backend_group.py
git -C /mnt/STORAGE/repos/helao/helao-async commit -m "feat(operator): get_object, strict control calls, shared tree pane

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: `/group` page, `GroupState`, app registration and nav

Per the coordinator, `/group` joins `SHELL_ROUTES` and is always registered, like every other shell route. With no orchestrator in the config it renders a note, so a page is "made empty by config, never absent". That makes it need a page tint. `pink-50` is the only unused Tailwind 50-shade that is not within ΔE 2.0 of an existing tint (ΔE 2.79 to `rose-50`; measured while planning). It is not yet in `TW`.

Re-read `helao/ui/reflex/app.py` around `NAV_LINKS` (`:457`), `NAV_ICONS` (`:464`), `_icon_label` (`:406`) and `_nav` (`:482`) before editing. The nav renders `NAV_LINKS` in order, each through `_icon_label(NAV_ICONS[text], text)`, followed by the `NAV_MENUS` dropdowns. `/group` becomes the **first** entry of `NAV_LINKS`, not a menu item and not a separate `rx.link`. It is **not** in `CREDENTIAL_ROUTES`.

**Files:**
- Create: `helao/ui/reflex/group.py`
- Modify: `helao/ui/reflex/ingest.py` (`NORMALIZERS`, `:261`)
- Modify: `helao/ui/reflex/app.py`: imports (`:130-142`), `SHELL_ROUTES` (`:149-163`), `NAV_LINKS` (`:457`), `NAV_ICONS` (`:464`), `build_app` state assertions and configure calls, `add_page` list, `_ingest_lifespan`. Line numbers drift; locate each by name.
- Modify: `helao/core/tests/test_reflex_credentials_gate.py`: `test_nav_renders_every_menu_and_top_level_link` (`:76-79`), expected label list
- Modify: `helao/ui/shared/palette.py`: `TW` gains `"pink-50": "#fdf2f8"`; `REFLEX_PAGE_TINTS` gains `"/group": "pink-50"`
- Modify: `helao/core/tests/test_palette.py`: `CANONICAL_TAILWIND`, `PAGE_TINT_TEXT_ROWS`, `SLATE_500_ON_TINT_ROWS`, the slate-500 failing-set test
- Test: `helao/core/tests/test_reflex_group.py`

**Interfaces:**
- Consumes: `WsIngest` (`ingest.py`); `session_backend`, `tree_for` (`operator.py:843,860`); `truncate_uuid` (`object_tree.py:86`); `tree_pane` (Task 7); `NetGraph`, `group_layout` (Task 5); `strip_marks`, `click_item`, `item_key` (Task 6); `plots.chart`, `plots.marks_chart`; `ERROR_STATUSES` (Task 3); palette `GROUP_*`, `REFLEX_MOTION_STOP_CLASS`.
- Produces:
  - `configure_group(world_cfg)`, `start_feed()`, `async stop_feed()`
  - pure: `new_frames(feed, last_seq) -> list[dict]`, `stream_lost(feed, now) -> bool`, `pulse_for(ev, now, orch_key) -> list | None`, `button_flags(snap, lost) -> dict`, `pending_done(name, snap) -> bool`, `object_request(kind, item) -> tuple | None`, `graph_marks(snap, pulses, now, orch_key, lost) -> tuple[list, list]`, `header_fields(snap) -> dict`
  - `GroupState(rx.State)`, `group_page() -> rx.Component`, `NO_ORCH_NOTE: str`

- [ ] **Step 1: Write the failing tests**

`helao/core/tests/test_reflex_group.py`:

```python
"""/group page: pure helpers, rendering and registration."""

from types import SimpleNamespace

import pytest

from helao.ui.shared.palette import GROUP_PULSE_DISPATCH, GROUP_STATE_COLORS

CFG = {
    "servers": {
        "ORCH": {"host": "127.0.0.1", "port": 8001, "group": "orchestrator"},
        "SIM": {"host": "127.0.0.1", "port": 8002, "group": "action"},
    }
}


def _feed(batches, count=1, last=100.0):
    return SimpleNamespace(raw=list(batches), status=SimpleNamespace(message_count=count, last_epoch=last))


def test_new_frames_returns_only_unseen_frames():
    from helao.ui.reflex.group import new_frames

    feed = _feed([[{"seq_no": 1}], [{"seq_no": 2}, {"seq_no": 3}]])
    assert [f["seq_no"] for f in new_frames(feed, 1)] == [2, 3]
    assert new_frames(None, 0) == []


def test_new_frames_resets_after_an_orchestrator_restart():
    from helao.ui.reflex.group import new_frames

    feed = _feed([[{"seq_no": 1}], [{"seq_no": 2}]])
    assert [f["seq_no"] for f in new_frames(feed, 900)] == [1, 2]


def test_stream_lost():
    from helao.ui.reflex.group import stream_lost

    assert stream_lost(None, 0.0)
    assert stream_lost(_feed([], count=0), 100.0)
    assert not stream_lost(_feed([], last=100.0), 104.0)
    assert stream_lost(_feed([], last=100.0), 105.5)


def test_pulse_for_direction_colour_and_self():
    from helao.ui.reflex.group import pulse_for

    d = pulse_for({"kind": "dispatch", "server": "SIM", "status": "active"}, 5.0, "ORCH")
    assert d == ["SIM", "fwd", 5.0, 0.6, GROUP_PULSE_DISPATCH]
    f = pulse_for({"kind": "finish", "server": "SIM", "status": "errored"}, 5.0, "ORCH")
    assert f[1] == "rev" and f[4] == GROUP_STATE_COLORS["error"]
    ok = pulse_for({"kind": "finish", "server": "SIM", "status": "finished"}, 5.0, "ORCH")
    assert ok[4] == GROUP_STATE_COLORS["done"]
    assert pulse_for({"kind": "dispatch", "server": "ORCH", "status": "active"}, 5.0, "ORCH") is None


def test_button_flags():
    from helao.ui.reflex.group import button_flags

    idle = {"loop_state": "stopped", "orch_state": "idle", "n_sequences_queued": 1, "seq": None, "experiments": []}
    assert button_flags(idle, False) == {"can_start": True, "can_stop": False, "estopped": False, "can_estop": True}
    assert button_flags({**idle, "n_sequences_queued": 0}, False)["can_start"] is False
    resumable = {**idle, "n_sequences_queued": 0, "seq": {"uuid": "s"}, "experiments": [{"state": "queued"}]}
    assert button_flags(resumable, False)["can_start"] is True
    running = {**idle, "loop_state": "started"}
    assert button_flags(running, False)["can_stop"] is True
    stopped = {**idle, "loop_state": "estopped"}
    assert button_flags(stopped, False)["estopped"] is True and button_flags(stopped, False)["can_start"] is False
    assert button_flags(running, True) == {"can_start": False, "can_stop": False, "estopped": False, "can_estop": False}


def test_pending_done():
    from helao.ui.reflex.group import pending_done

    assert pending_done("start", {"loop_state": "started"})
    assert not pending_done("start", {"loop_state": "stopped"})
    assert pending_done("stop", {"loop_state": "stopped"})
    assert pending_done("estop", {"loop_state": "estopped", "orch_state": "estopped"})
    assert pending_done("clear_estop", {"loop_state": "stopped", "orch_state": "idle"})


def test_object_request_falls_back_to_the_queue_index():
    from helao.ui.reflex.group import object_request

    assert object_request("experiment", {"uuid": "u", "qidx": None}) == ("get_object", "experiment", "u")
    assert object_request("experiment", {"uuid": None, "qidx": 3}) == ("get_queue_object", "experiment", 3)
    assert object_request("action", {"uuid": None, "qidx": None}) is None


def test_graph_marks_unknown_status_and_lost_stream():
    from helao.ui.reflex.group import graph_marks

    snap = {"orch_state": "busy", "servers": [
        {"key": "SIM", "status": "busy", "active_action": "acquire"},
        {"key": "X", "status": "weird", "active_action": None},
    ]}
    marks, pulses = graph_marks(snap, [["SIM", "fwd", 0.0, 0.6, GROUP_PULSE_DISPATCH]], 0.1, "ORCH", False)
    nodes = next(m for m in marks if m.get("name", "").startswith("nodes:"))
    assert nodes["colors"] == [GROUP_STATE_COLORS["busy"], GROUP_STATE_COLORS["busy"], GROUP_STATE_COLORS["idle"]]
    assert "X (weird)" in [m["value"] for m in marks if m["kind"] == "text"]
    assert len(pulses) == 1
    lost, _ = graph_marks(snap, [], 0.1, "ORCH", True)
    nodes = next(m for m in lost if m.get("name", "").startswith("nodes:"))
    assert set(nodes["colors"]) == {GROUP_STATE_COLORS["unreachable"]}


def test_header_fields_idle_and_running():
    from helao.ui.reflex.group import header_fields

    assert header_fields({})["seq_name"] == ""
    h = header_fields({"seq": {"name": "S", "uuid": "0123456789abcdef", "t_start": None},
                       "loop_state": "started", "orch_state": "busy", "closing_out": False})
    assert (h["seq_name"], h["seq_uuid_short"], h["loop_group"]) == ("S", "89abcdef", "busy")


def test_ws_orch_frames_are_not_numeric_normalized():
    from helao.ui.reflex.ingest import NORMALIZERS

    assert NORMALIZERS["ws_orch"]([{"seq_no": 1, "servers": []}]) == ({}, [])


def test_page_renders_with_and_without_an_orchestrator():
    from helao.ui.reflex import group

    group.configure_group(CFG)
    rendered = str(group.group_page().render())
    assert "E-stop" in rendered and "Start" in rendered
    group.configure_group({"servers": {}})
    assert group.NO_ORCH_NOTE in str(group.group_page().render())
    group.configure_group(CFG)


def test_group_route_nav_and_tint():
    from helao.ui.reflex import app
    from helao.ui.shared import palette

    assert "/group" in app.SHELL_ROUTES
    assert "/group" not in app.CREDENTIAL_ROUTES
    assert all(href != "/group" for _, items, gated in app.NAV_MENUS for _, href in items + gated)
    assert palette.REFLEX_PAGE_TINTS["/group"] == "pink-50"
    assert app.NAV_LINKS[0] == ("Group", "/group")
    assert app.NAV_ICONS["Group"] == "network"
    assert '"/group"' in str(app._nav())
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=. $PY -m pytest helao/core/tests/test_reflex_group.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'helao.ui.reflex.group'`.

- [ ] **Step 3: Add the `ws_orch` normalizer**

In `helao/ui/reflex/ingest.py`, above `NORMALIZERS`:

```python
def normalize_none(messages: list) -> tuple:
    """``ws_orch`` frames are whole snapshots read from ``raw``; nothing is numeric."""
    return {}, []
```

and change the dict to:

```python
NORMALIZERS = {"ws_live": normalize, "ws_data": normalize_data_package, "ws_orch": normalize_none}
```

- [ ] **Step 4: Implement `group.py`**

```python
"""The /group page: server-group graph, sequence timelines, controls, info box.

One process-wide ``WsIngest`` on the orchestrator's ``/ws_orch``; frames are
whole snapshots, read from ``ingest.raw``. ``GroupState`` is a plain
``rx.State`` (one page per orchestrator) ticked by ``rx.moment``: 60 Hz while
a pulse is alive, 2 Hz otherwise. Never a server-side loop. Buttons and the
info box go over HTTP through the operator's ``RemoteBackend``.
"""

import time
from datetime import datetime
from typing import Optional

import reflex as rx

from helao.core.models.group_snapshot import ERROR_STATUSES
from helao.helpers import helao_logging as logging
from helao.ui.reflex import plots
from helao.ui.reflex.ingest import WsIngest
from helao.ui.reflex.netgraph import NetGraph, group_layout
from helao.ui.reflex.operator import session_backend, tree_for
from helao.ui.reflex.timeline_strip import click_item, item_key, strip_marks
from helao.ui.reflex.tree_pane import tree_pane
from helao.ui.shared.operator.object_tree import truncate_uuid
from helao.ui.shared.palette import (
    GROUP_BADGE_CLASSES,
    GROUP_ERROR_TEXT_CLASS,
    GROUP_LABEL_COLORS,
    GROUP_PULSE_DISPATCH,
    GROUP_STATE_COLORS,
    REFLEX_MOTION_STOP_CLASS,
)

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

GRAPH_H, GRAPH_W = 360, 720
STRIP_H, STRIP_W = 70, 720
FAST_MS, SLOW_MS = 16, 500
STALE_S = 5.0
PULSE_S = 0.6
PENDING_TIMEOUT_S = 10.0
NO_ORCH_NOTE = "This config has no orchestrator, so there is no server group to show."
LOST_BANNER = "orchestrator unreachable"
OLD_ORCH_BANNER = "orchestrator lacks /ws_orch — update the orchestrator"
SELECTION_GONE = "selection no longer in view"
NOT_FOUND = "not found on the orchestrator"
LOOP_TO_GROUP = {"started": "busy", "stopped": "idle", "estopped": "estop", "error": "error"}
ORCH_TO_GROUP = {"idle": "idle", "busy": "busy", "error": "error", "estopped": "estop"}

_CFG: dict = {}
_FEED: Optional[WsIngest] = None


def configure_group(world_cfg: dict) -> None:
    """Record the group's orchestrator (the first ``group: orchestrator``)."""
    servers = (world_cfg or {}).get("servers") or {}
    keys = [k for k, v in servers.items() if isinstance(v, dict) and v.get("group") == "orchestrator"]
    _CFG.clear()
    if keys:
        key = keys[0]
        _CFG.update(orch_key=key, host=servers[key]["host"], port=servers[key]["port"])


def start_feed() -> None:
    """Subscribe to /ws_orch once per process. Called from the app lifespan."""
    global _FEED
    if _CFG and _FEED is None:
        _FEED = WsIngest(_CFG["host"], _CFG["port"], "ws_orch", raw_maxlen=200)
        _FEED.start()


async def stop_feed() -> None:
    global _FEED
    if _FEED is not None:
        await _FEED.stop()
        _FEED = None


def new_frames(feed, last_seq: int) -> list:
    """Snapshots newer than ``last_seq``. A lower newest ``seq_no`` means the
    orchestrator restarted, so the cursor resets."""
    if feed is None:
        return []
    frames = [m for batch in list(feed.raw) for m in batch if isinstance(m, dict) and "seq_no" in m]
    if frames and frames[-1]["seq_no"] < last_seq:
        last_seq = 0
    return [f for f in frames if f["seq_no"] > last_seq]


def stream_lost(feed, now: float) -> bool:
    """Lost while disconnected, never connected, or silent for over 5 s."""
    if feed is None or feed.status.message_count == 0:
        return True
    return now - feed.status.last_epoch > STALE_S


def pulse_for(ev: dict, now: float, orch_key: str):
    """``[edge_id, direction, t0, duration, colour]``; None for the orch's own actions.

    ``t0`` is when the page saw the event, not the event's own time: a 2 Hz
    page would otherwise start a 0.6 s pulse already half done.
    """
    server = ev.get("server")
    if not server or server == orch_key:
        return None
    if ev.get("kind") == "dispatch":
        return [server, "fwd", now, PULSE_S, GROUP_PULSE_DISPATCH]
    state = "error" if ev.get("status") in ERROR_STATUSES else "done"
    return [server, "rev", now, PULSE_S, GROUP_STATE_COLORS[state]]


def _estopped(snap: dict) -> bool:
    return snap.get("loop_state") == "estopped" or snap.get("orch_state") == "estopped"


def button_flags(snap: dict, lost: bool) -> dict:
    estopped = _estopped(snap)
    started = snap.get("loop_state") == "started"
    has_work = snap.get("n_sequences_queued", 0) > 0 or (
        snap.get("seq") is not None
        and any(e.get("state") == "queued" for e in snap.get("experiments", []))
    )
    return {
        "can_start": not lost and not started and not estopped and has_work,
        "can_stop": not lost and started,
        "estopped": estopped,
        "can_estop": not lost,
    }


def pending_done(name: str, snap: dict) -> bool:
    """True once a snapshot reflects the button's effect."""
    if name == "start":
        return snap.get("loop_state") == "started"
    if name == "stop":
        return snap.get("loop_state") != "started"
    if name == "estop":
        return _estopped(snap)
    return not _estopped(snap)


def object_request(kind: str, item: dict):
    """How to fetch a clicked item: by uuid, else by queue index, else nothing."""
    if item.get("uuid"):
        return ("get_object", kind, item["uuid"])
    if item.get("qidx") is not None:
        return ("get_queue_object", kind, item["qidx"])
    return None


def _color_key(status: str) -> str:
    return status if status in GROUP_STATE_COLORS else "idle"


def graph_marks(snap: dict, pulses: list, now: float, orch_key: str, lost: bool):
    """``(marks, live pulses)`` for the network graph."""
    servers = snap.get("servers", [])
    pos = group_layout(orch_key, [s["key"] for s in servers])
    g = NetGraph(height_px=GRAPH_H, width_px=GRAPH_W)
    orch_status = "unreachable" if lost else ORCH_TO_GROUP.get(snap.get("orch_state"), "idle")
    g.add_node(orch_key, *pos[orch_key], color=GROUP_STATE_COLORS[orch_status],
               label_color=GROUP_LABEL_COLORS[orch_status], text=orch_key,
               subtext=snap.get("orch_action") or "")
    for s in servers:
        status = "unreachable" if lost else s.get("status", "idle")
        key = _color_key(status)
        text = s["key"] if status in GROUP_STATE_COLORS else f"{s['key']} ({status})"
        g.add_node(s["key"], *pos[s["key"]], color=GROUP_STATE_COLORS[key],
                   label_color=GROUP_LABEL_COLORS[key], text=text,
                   subtext=s.get("active_action") or "")
        g.add_edge(s["key"], orch_key, s["key"], color=GROUP_STATE_COLORS[key],
                   width=4.0 if status == "busy" else 2.0)
        g.add_arrowhead(s["key"], at="dst")
    for edge_id, direction, t0, duration, color in pulses:
        if edge_id in g.edges:
            g.pulse(edge_id, t0=t0, color=color, direction=direction, duration=duration)
    marks = g.marks(now)
    return marks, [[p.edge_id, p.direction, p.t0, p.duration, p.color] for p in g.pulses]


def header_fields(snap: dict) -> dict:
    seq = snap.get("seq") or {}
    t = seq.get("t_start")
    loop_state = snap.get("loop_state", "")
    orch_state = snap.get("orch_state", "")
    return {
        "seq_name": seq.get("name") or "",
        "seq_started": datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S") if t else "",
        "seq_uuid": seq.get("uuid") or "",
        "seq_uuid_short": truncate_uuid(seq.get("uuid")),
        "loop_state": loop_state,
        "orch_state": orch_state,
        "loop_group": LOOP_TO_GROUP.get(loop_state, "idle"),
        "orch_group": ORCH_TO_GROUP.get(orch_state, "idle"),
        "closing_out": bool(snap.get("closing_out")),
    }


CONTROL_CALLS = {
    "start": lambda b: b.start(strict=True),
    "stop": lambda b: b.stop(reset_run_id=False, strict=True),
    "estop": lambda b: b.estop(strict=True),
    "clear_estop": lambda b: b.clear_estop(strict=True),
}


class GroupState(rx.State):
    """One /group page session. Created at import, before ``add_page``."""

    seq_name: str = ""
    seq_started: str = ""
    seq_uuid: str = ""
    seq_uuid_short: str = ""
    loop_state: str = ""
    orch_state: str = ""
    loop_group: str = "idle"
    orch_group: str = "idle"
    closing_out: bool = False
    can_start: bool = False
    can_stop: bool = False
    can_estop: bool = False
    estopped: bool = False
    lost: bool = True
    pending: str = ""
    action_error: str = ""
    banner: str = ""
    graph_spec: dict = {}
    graph_url: str = ""
    graph_layout: str = ""
    exp_spec: dict = {}
    exp_url: str = ""
    exp_layout: str = ""
    act_spec: dict = {}
    act_url: str = ""
    act_layout: str = ""
    tree_header: str = "select a row"
    tree_html: str = ""
    info_note: str = ""
    tick_ms: int = SLOW_MS
    _last_seq: int = 0
    _snap: dict = {}
    _pulses: list = []
    _version: int = 0
    _exp_slots: list = []
    _act_slots: list = []
    _selected: list = []
    _running: bool = False
    _pending_at: float = 0.0
    _probe_at: float = 0.0
    _old_orch: bool = False

    def _apply(self, now: float) -> bool:
        """Fold new frames in and render. Returns True when an old-orch probe is due."""
        frames = new_frames(_FEED, self._last_seq)
        for f in frames:
            for ev in f.get("events", []):
                p = pulse_for(ev, now, _CFG["orch_key"])
                if p is not None:
                    self._pulses.append(p)
            self._last_seq = f["seq_no"]
        if frames:
            self._snap = frames[-1]
            self._old_orch = False
        snap = self._snap
        lost = stream_lost(_FEED, now)
        for name, value in header_fields(snap).items():
            setattr(self, name, value)
        for name, value in button_flags(snap, lost).items():
            setattr(self, name, value)
        self.lost = lost
        self.banner = (OLD_ORCH_BANNER if self._old_orch else LOST_BANNER) if lost else ""
        if self.pending and (pending_done(self.pending, snap) or now - self._pending_at > PENDING_TIMEOUT_S):
            self.pending = ""
        self._render(now, lost)
        self.tick_ms = FAST_MS if self._pulses else SLOW_MS
        never_live = _FEED is not None and _FEED.status.message_count == 0
        return lost and never_live and now - self._probe_at > STALE_S

    def _render(self, now: float, lost: bool) -> None:
        token = self.router.session.client_token
        self._version += 1
        v = self._version
        snap = self._snap
        marks, self._pulses = graph_marks(snap, self._pulses, now, _CFG["orch_key"], lost)
        p = plots.marks_chart(marks, x_domain=(-1.0, 1.0), y_domain=(-1.0, 1.0),
                              panel_id=f"group-graph-{token}", version=v)
        self.graph_spec, self.graph_url, self.graph_layout = p.spec, p.buffer_url, p.layout
        sel_kind, sel_key = (list(self._selected) + [None, None])[:2]
        em, self._exp_slots = strip_marks(
            snap.get("experiments", []), n_before=snap.get("n_done", 0),
            n_after=snap.get("n_queued", 0), now=now, width_px=STRIP_W,
            selected=sel_key if sel_kind == "experiment" else None)
        p = plots.marks_chart(em, x_domain=(0.0, float(max(len(self._exp_slots), 1))),
                              y_domain=(0.0, 1.0), panel_id=f"group-exp-{token}", version=v, click=True)
        self.exp_spec, self.exp_url, self.exp_layout = p.spec, p.buffer_url, p.layout
        am, self._act_slots = strip_marks(
            snap.get("actions", []), n_before=0, n_after=0, now=now, width_px=STRIP_W,
            selected=sel_key if sel_kind == "action" else None)
        p = plots.marks_chart(am, x_domain=(0.0, float(max(len(self._act_slots), 1))),
                              y_domain=(0.0, 1.0), panel_id=f"group-act-{token}", version=v, click=True)
        self.act_spec, self.act_url, self.act_layout = p.spec, p.buffer_url, p.layout
        if sel_key is not None:
            slots = self._exp_slots if sel_kind == "experiment" else self._act_slots
            in_view = any(it is not None and item_key(it) == sel_key for it in slots)
            if not in_view:
                self.info_note = SELECTION_GONE
            elif self.info_note == SELECTION_GONE:
                self.info_note = ""

    @rx.event(background=True)
    async def tick(self, _tick: str = ""):
        """One render, driven by the page's ``rx.moment``."""
        if not _CFG:
            return
        async with self:
            if self._running:
                return
            self._running = True
            token = self.router.session.client_token
        try:
            async with self:
                probe = self._apply(time.time())
            if probe:
                backend = session_backend(token)
                state = await backend.get_orch_state() if backend is not None else {}
                async with self:
                    self._probe_at = time.time()
                    self._old_orch = bool(state)
        finally:
            async with self:
                self._running = False

    @rx.event(background=True)
    async def control(self, name: str):
        """Start / Stop / E-stop / Clear E-stop through RemoteBackend."""
        async with self:
            token = self.router.session.client_token
            self.pending = name
            self.action_error = ""
            self._pending_at = time.time()
        backend = session_backend(token)
        err = ""
        if backend is None:
            err = "cannot reach the orchestrator"
        else:
            try:
                await CONTROL_CALLS[name](backend)
            except Exception as exc:
                err = str(exc)
        async with self:
            self.action_error = err
            if err:
                self.pending = ""

    async def _select(self, kind: str, payload: dict):
        async with self:
            token = self.router.session.client_token
            slots = self._exp_slots if kind == "experiment" else self._act_slots
            item = click_item(slots, (payload or {}).get("x"))
            if item is None:
                return
            self._selected = [kind, item_key(item)]
            self.info_note = ""
        request = object_request(kind, item)
        backend = session_backend(token)
        obj = None
        if request is not None and backend is not None:
            method, k, ident = request
            try:
                obj = await getattr(backend, method)(k, ident)
            except Exception as exc:
                LOGGER.warning(f"/group could not fetch {kind} {ident}: {exc}")
        async with self:
            self.tree_header, self.tree_html = tree_for(kind, obj)
            if not obj:
                self.info_note = NOT_FOUND

    @rx.event(background=True)
    async def select_exp(self, payload: dict):
        await self._select("experiment", payload)

    @rx.event(background=True)
    async def select_act(self, payload: dict):
        await self._select("action", payload)


def _badge(prefix: str, label_var, group_var):
    """A state badge whose classes are all literal, so Tailwind emits them."""
    return rx.match(
        group_var,
        *[(state, rx.badge(prefix, label_var, class_name=cls)) for state, cls in GROUP_BADGE_CLASSES.items()],
        rx.badge(prefix, label_var, class_name=GROUP_BADGE_CLASSES["idle"]),
    )


def _button(label: str, name: str, enabled_var, class_name: str = ""):
    return rx.button(
        rx.cond(GroupState.pending == name, rx.spinner(size="1"), label),
        on_click=GroupState.control(name),
        disabled=~enabled_var,
        class_name=class_name,
    )


def group_page() -> rx.Component:
    if not _CFG:
        return rx.text(NO_ORCH_NOTE, padding_x="1em")
    S = GroupState
    seq_row = rx.cond(
        S.seq_name == "",
        rx.text("idle — no active sequence"),
        rx.hstack(
            rx.text("SEQ", weight="bold"),
            rx.text(S.seq_name),
            rx.text("started ", S.seq_started),
            rx.text("uuid"),
            rx.tooltip(rx.text(S.seq_uuid_short, "…", font_family="monospace"), content=S.seq_uuid),
            rx.button("copy", size="1", variant="soft", on_click=rx.set_clipboard(S.seq_uuid)),
            align="center",
            spacing="2",
        ),
    )
    controls = rx.hstack(
        _badge("loop: ", S.loop_state, S.loop_group),
        _badge("orch: ", S.orch_state, S.orch_group),
        rx.cond(S.closing_out, rx.badge("closing out", class_name=GROUP_BADGE_CLASSES["unreachable"])),
        rx.spacer(),
        _button("Start", "start", S.can_start),
        _button("Stop", "stop", S.can_stop),
        rx.cond(
            S.estopped,
            _button("Clear E-stop", "clear_estop", S.can_estop),
            _button("E-stop", "estop", S.can_estop, REFLEX_MOTION_STOP_CLASS),
        ),
        width="100%",
        align="center",
    )
    header = rx.vstack(
        seq_row,
        controls,
        rx.cond(S.action_error != "", rx.text(S.action_error, class_name=GROUP_ERROR_TEXT_CLASS)),
        rx.cond(S.banner != "", rx.callout(S.banner, icon="triangle_alert")),
        width="100%",
    )
    charts = rx.vstack(
        plots.chart(S.graph_spec, S.graph_url, S.graph_layout, height=GRAPH_H, width=GRAPH_W),
        rx.text("EXP", size="1", weight="bold"),
        plots.chart(S.exp_spec, S.exp_url, S.exp_layout, height=STRIP_H, width=STRIP_W, on_select=S.select_exp),
        rx.text("ACT", size="1", weight="bold"),
        plots.chart(S.act_spec, S.act_url, S.act_layout, height=STRIP_H, width=STRIP_W, on_select=S.select_act),
    )
    info = rx.vstack(
        rx.text("INFO", weight="bold"),
        rx.cond(S.info_note != "", rx.text(S.info_note, size="1")),
        tree_pane(S.tree_header, S.tree_html),
        width="100%",
    )
    return rx.vstack(
        header,
        rx.hstack(charts, info, width="100%", align="start", spacing="4"),
        rx.moment(interval=S.tick_ms, on_change=S.tick, display="none"),
        on_mount=S.tick(""),
        padding_x="1em",
        width="100%",
    )
```

If `rx.set_clipboard`, `rx.callout(..., icon=...)`, `rx.spinner` or `rx.match` raise at render under Reflex 0.9.7, `test_page_renders_with_and_without_an_orchestrator` shows it. Report the failing component rather than dropping the feature.

- [ ] **Step 5: Register in `app.py`**

1. Imports: `from helao.ui.reflex.group import GroupState, configure_group, group_page, start_feed, stop_feed`.
2. `SHELL_ROUTES`: add `"/group",` after `"/operator",`.
3. Nav: make `("Group", "/group"),` the **first** entry of `NAV_LINKS`, so it reads `NAV_LINKS = (("Group", "/group"), ("Operator", "/operator"), ("Action", "/action"), ("Live", "/live"))`. Add `"Group": "network",` to `NAV_ICONS`. Do not touch `_nav` or `NAV_MENUS`. In `helao/core/tests/test_reflex_credentials_gate.py`, `test_nav_renders_every_menu_and_top_level_link`'s expected list becomes `assert labels == ["Group", "Operator", "Action", "Live", "Data", "Admin"]`. Its `set(app.NAV_ICONS) == set(labels) | entries` check then needs the `NAV_ICONS` entry. If Lucide's icon name has changed (Reflex warns about an unknown icon at render), report it rather than choosing another name.
4. In `build_app`, beside the other state assertions: `assert GroupState is not None` with the comment `# And the /group page's state: created at import, before add_page.` After `configure_logs(world_cfg, server_key)`: `configure_group(world_cfg)`.
5. After the `/operator` `add_page`:

```python
    application.add_page(
        lambda: _page("Server group", group_page(), "/group"),
        route="/group",
        title="HELAO group",
    )
```

6. In `_ingest_lifespan`, after `registry.start()`: `start_feed()`. In its `finally`, before `await registry.stop()`: `await stop_feed()`.

- [ ] **Step 6: Tint and palette rows**

In `palette.py`, add `"pink-50": "#fdf2f8",` to `TW` beside `"pink-400"`, and `"/group": "pink-50",` to `REFLEX_PAGE_TINTS`.

In `test_palette.py`:
- `CANONICAL_TAILWIND`: add `"pink-50": "#fdf2f8",`
- `PAGE_TINT_TEXT_ROWS`: add `("slate-900", "pink-50"): 16.35,  # /group` and `("slate-600", "pink-50"): 6.94,`
- `SLATE_500_ON_TINT_ROWS`: add `("slate-500", "pink-50"): 4.36,  # /group`
- Rename `test_slate_500_fails_the_body_floor_on_six_of_the_thirteen_tints` to `test_slate_500_fails_the_body_floor_on_seven_of_the_fourteen_tints`. Add `"pink-50",` to its expected set, and append to its docstring: `` ``pink-50`` joined them with ``/group``, at 4.36.`` In `test_slate_500_is_measured_on_every_tint`'s docstring, change "Six of the thirteen" to "Seven of the fourteen".

Why `pink-50` and not `fuchsia-50`: of the unused Tailwind 50-shades, `pink-50` sits furthest from every existing tint (ΔE 2.79 to `rose-50`). `fuchsia-50` is next at ΔE 2.63 to `violet-50`, and `blue-50`, `purple-50` and `green-50` are under 2.0. Both pass every contrast row (`fuchsia-50`: 16.63 / 7.06 / slate-500 4.43, also failing), so swapping is a one-line change if preferred.

These values were measured while planning with the test file's own `contrast_ratio`. `_check` re-measures them at `abs=0.01`, so a wrong value fails loudly.

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=. $PY -m pytest helao/core/tests/test_reflex_group.py helao/core/tests/test_palette.py helao/core/tests/test_reflex_routes_e2e.py helao/core/tests/test_reflex_credentials_gate.py helao/core/tests/test_reflex_ingest.py helao/core/tests/test_reflex_operator.py helao/core/tests/test_reflex_config.py helao/hexagon/tests/test_status_consumer_faces.py -q`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git -C /mnt/STORAGE/repos/helao/helao-async add helao/ui/reflex/group.py helao/ui/reflex/ingest.py helao/ui/reflex/app.py helao/ui/shared/palette.py helao/core/tests/test_palette.py helao/core/tests/test_reflex_group.py helao/core/tests/test_reflex_credentials_gate.py
git -C /mnt/STORAGE/repos/helao/helao-async commit -m "feat(reflex): /group page with graph, timelines, controls and info box

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Live test, headless browser check, docs, black

**Files:**
- Create: `helao/hexagon/tests/test_orch_graph_feed_live.py`
- Create (scratch, not committed): `/tmp/claude-1000/group-pw/{queue_seq.py,check_group.py}`
- Modify: `helao/ui/reflex/CLAUDE.md`, `CLAUDE.md` (Reflex section)
- Possibly modify: `helao/ui/reflex/plots.py` (`ANNOTATIONS_IN_TOKEN`, Step 6)

**Interfaces:**
- Consumes: `live_group`, `orch_call`, `build_ws_sequence`, `wait_parked`, `ORCH_HOST`, `ORCH_PORT` (`helao/hexagon/tests/live_group.py`); `RemoteBackend` (Task 7).

- [ ] **Step 1: Write the live test**

```python
"""/ws_orch on a real in-process group: events, experiment states, Start/Stop."""

import asyncio
from collections import Counter

import pytest
import websockets

from helao.core.error import ErrorCodes  # noqa: F401  (transport errors surface as RuntimeError)
from helao.helpers.dispatcher import async_private_dispatcher
from helao.helpers.ws_utils import wire_loads
from helao.hexagon.tests.live_group import (
    ORCH_HOST,
    ORCH_PORT,
    build_ws_sequence,
    live_group,
    orch_call,
    wait_parked,
)


def _backend():
    from helao.ui.shared.operator.orch_backend import RemoteBackend

    b = RemoteBackend.__new__(RemoteBackend)  # only the transport fields _call reads
    b.orch_key, b.host, b.port, b._dispatch = "ORCH", ORCH_HOST, ORCH_PORT, async_private_dispatcher
    return b


async def _until(frames, pred, timeout=60.0):
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if frames and pred(frames[-1]):
            return frames[-1]
        await asyncio.sleep(0.1)
    raise TimeoutError(f"no frame matched; last={frames[-1] if frames else None}")


@pytest.mark.asyncio
async def test_ws_orch_reports_each_action_once_and_experiments_in_order(tmp_path):
    frames = []
    async with live_group(str(tmp_path)) as g:

        async def collect():
            async with websockets.connect(f"ws://{ORCH_HOST}:{ORCH_PORT}/ws_orch") as ws:
                while True:
                    frames.append(wire_loads(await ws.recv()))

        task = asyncio.create_task(collect())
        try:
            await _until(frames, lambda f: True, timeout=5.0)  # cached frame arrives on connect
            seq = build_ws_sequence(2, wait_time=0.5, data_duration=0.5)
            await orch_call("append_sequence", body={"sequence": seq.as_dict()})
            await orch_call("start")
            await wait_parked(g.orch)
            await asyncio.sleep(0.5)
            history = {str(u) for u in g.orch.action_history}

            events = [e for f in frames for e in f["events"]]
            dispatched = Counter(e["action_uuid"] for e in events if e["kind"] == "dispatch")
            finished = Counter(e["action_uuid"] for e in events if e["kind"] == "finish")
            assert history, "the run dispatched nothing"
            assert set(dispatched) == history and set(finished) == history
            assert set(dispatched.values()) == {1} and set(finished.values()) == {1}

            seqs = [f["seq_no"] for f in frames]
            assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)

            assert any(r["state"] == "queued" for f in frames for r in f["experiments"])
            per_uuid = {}
            for f in frames:
                for r in f["experiments"]:
                    if r["uuid"] is None:
                        continue
                    states = per_uuid.setdefault(r["uuid"], [])
                    if not states or states[-1] != r["state"]:
                        states.append(r["state"])
            assert len(per_uuid) == 2
            assert all(states == ["active", "done"] for states in per_uuid.values()), per_uuid

            backend = _backend()
            more = build_ws_sequence(3, wait_time=1.0, data_duration=1.0)
            await orch_call("append_sequence", body={"sequence": more.as_dict()})
            await backend.start(strict=True)
            await _until(frames, lambda f: f["loop_state"] == "started", timeout=15.0)
            await backend.stop(strict=True)
            await _until(frames, lambda f: f["loop_state"] != "started", timeout=60.0)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
```

- [ ] **Step 2: Run it**

Run: `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=. $PY -m pytest helao/hexagon/tests/test_orch_graph_feed_live.py -q`
Expected: 1 passed in under 2 minutes.

If the `set(dispatched) == history` assertion fails only for the orchestrator's own `wait` actions (uuids whose `action_server` is `ORCH`), stop and report. That would mean the orchestrator's own actions never reach its `active_dict`/`nonactive_dict`, which is a design question, not a test to loosen.

- [ ] **Step 3: Mutation check for the live test**

Back up with `/usr/bin/cp helao/hexagon/app/orch_graph_feed.py /tmp/claude-1000/ogf.py`. In `diff_events`, delete the `ev("finish", uid, server, name, status)` line inside the `nonactive` loop. Re-run Step 2 and expect a FAIL on `set(finished) == history`. Restore with `/usr/bin/cp /tmp/claude-1000/ogf.py helao/hexagon/app/orch_graph_feed.py` and re-run to a pass.

- [ ] **Step 4: Prepare the headless browser check**

```bash
python3 -m venv /tmp/claude-1000/pw-venv && /tmp/claude-1000/pw-venv/bin/pip install -q playwright==1.62.0
mkdir -p /tmp/claude-1000/group-pw
```

`/tmp/claude-1000/group-pw/queue_seq.py` (run with the helao env python, `PYTHONPATH=<repo>`):

```python
import asyncio

from helao.helpers.dispatcher import async_private_dispatcher
from helao.helpers.premodels import ExperimentPlanMaker, Sequence
from helao.helpers.time_utils import gen_uuid


async def main():
    epm = ExperimentPlanMaker()
    for _ in range(3):
        epm.add("SIM_websocket_data", {"wait_time": 4.0, "data_duration": 4.0})
    seq = Sequence(sequence_name="SIM_websocket_data_seq", sequence_label="group-page",
                   sequence_params={}, planned_experiments=epm.planned_experiments,
                   sequence_uuid=gen_uuid(), dummy=True, simulation=True)
    resp, err = await async_private_dispatcher("ORCH", "127.0.0.1", 8001, "append_sequence",
                                               {}, {"sequence": seq.as_dict()})
    print("append_sequence", err)


asyncio.run(main())
```

`/tmp/claude-1000/group-pw/check_group.py` (run with the scratch venv python):

```python
import re
import subprocess
import sys

from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:5010/group"
REPO = "/mnt/STORAGE/repos/helao/helao-async"
HELAO_PY = "/home/dan/miniforge3/envs/helao/bin/python"
OUT = "/tmp/claude-1000/group-pw"
console = []
results = {}

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1500, "height": 950})
    page.on("console", lambda m: console.append(m.text))
    page.goto(URL)
    page.wait_for_timeout(6000)
    body = page.inner_text("body")
    results["idle header"] = "idle — no active sequence" in body
    results["no lost banner"] = "orchestrator unreachable" not in body
    results["start disabled when idle"] = page.get_by_role("button", name="Start").is_disabled()
    results["nav link"] = page.get_by_role("link", name="Group").count() == 1
    page.screenshot(path=f"{OUT}/idle.png")

    subprocess.run([HELAO_PY, f"{OUT}/queue_seq.py"], cwd=REPO, env={"PYTHONPATH": REPO}, check=True)
    page.wait_for_timeout(1500)
    page.get_by_role("button", name="Start").click()
    page.wait_for_timeout(5000)
    body = page.inner_text("body")
    results["sequence header"] = "SIM_websocket_data_seq" in body
    page.screenshot(path=f"{OUT}/running.png")

    hosts = page.locator('div[style*="min-height: 70px"]')
    results["two strips"] = hosts.count() == 2
    box = hosts.nth(0).bounding_box()
    page.mouse.click(box["x"] + 20, box["y"] + box["height"] / 2)
    page.wait_for_timeout(2000)
    results["info filled"] = "select a row" not in page.inner_text("body")

    elapsed = page.get_by_text(re.compile(r"– \(\d+:\d\d\)"))
    results["elapsed label in DOM"] = elapsed.count() > 0
    if elapsed.count():
        first = elapsed.first.inner_text()
        page.wait_for_timeout(2500)
        results["elapsed label advanced"] = page.get_by_text(re.compile(r"– \(\d+:\d\d\)")).first.inner_text() != first

    page.get_by_role("button", name="E-stop").click()
    page.wait_for_timeout(3000)
    results["clear estop shown"] = page.get_by_role("button", name="Clear E-stop").count() == 1
    page.get_by_role("button", name="Clear E-stop").click()
    page.wait_for_timeout(3000)
    page.screenshot(path=f"{OUT}/after_estop.png")
    results["no webgl eviction"] = not any("Too many active WebGL contexts" in c for c in console)
    browser.close()

for k, v in results.items():
    print(("PASS" if v else "FAIL"), k)
print("console errors:", [c for c in console if "error" in c.lower()][:10])
sys.exit(0 if all(results.values()) else 1)
```

- [ ] **Step 5: Launch the group, run the check, stop the group**

Run as two separate background commands (the job, then the watcher), per the sweep-watcher rule:

```bash
# background command 1: the group
D=/tmp/claude-1000/group-pw; rm -f $D/done $D/launch.pid
( cd /mnt/STORAGE/repos/helao/helao-async && bash -c 'echo $$ > /tmp/claude-1000/group-pw/launch.pid; exec ./helao.sh goldenreflex --no-hot-reload' > $D/launch.log 2>&1 < /dev/null; echo $? > $D/done )
```

```bash
# background command 2: watcher, exits when the group exits (2 h cap)
D=/tmp/claude-1000/group-pw; for i in $(seq 1 480); do [ -f $D/done ] && break; sleep 15; done; echo "rc=$(cat $D/done 2>/dev/null || echo TIMEOUT)"; tail -20 $D/launch.log
```

Wait for the UI with a bounded poll: `for i in $(seq 1 60); do curl -sf http://127.0.0.1:5010/group >/dev/null && break; sleep 5; done`. Then run:

`/tmp/claude-1000/pw-venv/bin/python /tmp/claude-1000/group-pw/check_group.py`

Expected: every line `PASS`. Look at `idle.png`, `running.png` and `after_estop.png` with the Read tool. Node labels must sit visibly *on* the nodes, which is the text-over-marker z-order check. Then stop the group by PID: `kill -TERM $(cat /tmp/claude-1000/group-pw/launch.pid)`. The watcher prints `rc=`.

Do not run this while another goldenreflex launch holds ports 8001-8004/5010. The launcher refuses and lists the running servers; report that rather than passing `--force-relaunch` on someone else's group.

- [ ] **Step 6: Decide `ANNOTATIONS_IN_TOKEN` from the measurement**

If `elapsed label in DOM` passed, set `plots.ANNOTATIONS_IN_TOKEN = False`. Update `test_changed_annotation_text_rebuilds_while_annotations_are_in_the_token` to `assert plots.ANNOTATIONS_IN_TOKEN is False` and `assert _mc(_marks(text="A")).layout == _mc(_marks(text="B")).layout`, rename it `test_changed_annotation_text_updates_in_place`, rerun Steps 5-6, and confirm `elapsed label advanced` still passes with no rebuild. If it does not advance, revert to `True`. If the label is not in the DOM at all, leave `True` and note it in the docs bullet below. Record the outcome in the xy note's /group section.

- [ ] **Step 7: Docs**

Append to `helao/ui/reflex/CLAUDE.md`, before the "Only `plots.py` and `xy_component.py` may import `xy`" paragraph:

```markdown
- **`/group` reads a push stream, not the operator's polls.** The orchestrator's `OrchGraphFeed` (`helao/hexagon/app/orch_graph_feed.py`) publishes a plain-dict snapshot on `/ws_orch`: on change at most every 100 ms, and every 2 s as a heartbeat. It is read-only and outside the dispatch path. `group.py` keeps one process-wide `WsIngest` on it and reads whole frames from `ingest.raw` (`NORMALIZERS["ws_orch"]` deliberately yields nothing). `seq_no` restarts with the orchestrator, so `new_frames` resets its cursor when the newest frame is lower; without that a restarted orchestrator freezes the page. `netgraph.py` and `timeline_strip.py` are pure and return mark dicts; `plots.marks_chart` is their only path to xy. An empty scatter or line is padded with one off-domain point, because xy encodes an empty colour list as a colormap and the trace's column layout would change under an unchanged layout token. Queued experiments have no uuid until activation, so a click on one fetches by queue index.
```

In root `CLAUDE.md`, in the "Reflex UI stack" section, after the `/logs` sentence:

```markdown
`/group` shows the group's orchestrator as a live graph with experiment/action timelines and Start/Stop/E-stop, fed by the orchestrator's `/ws_orch` stream; a config with no orchestrator renders a note there.
```

- [ ] **Step 8: Full gate**

Run each and expect all pass:

```bash
cd /mnt/STORAGE/repos/helao/helao-async
PYTHONPATH=. $PY -m pytest helao/core/tests/test_palette.py helao/core/tests/test_reflex_group.py helao/core/tests/test_reflex_netgraph.py helao/core/tests/test_reflex_timeline_strip.py helao/core/tests/test_reflex_plots.py helao/core/tests/test_reflex_config.py helao/core/tests/test_reflex_routes_e2e.py helao/core/tests/test_reflex_credentials_gate.py helao/core/tests/test_reflex_ingest.py helao/core/tests/test_reflex_operator.py helao/core/tests/test_orch_backend_group.py -q
PYTHONPATH=. $PY -m pytest helao/hexagon/tests/test_group_snapshot.py helao/hexagon/tests/test_orch_graph_feed.py helao/hexagon/tests/test_orch_graph_feed_live.py helao/hexagon/tests/test_orch_host_surface.py helao/hexagon/tests/test_orch_host_member_coverage.py helao/hexagon/tests/test_no_wait_overlap_live.py helao/hexagon/tests/test_status_consumer_faces.py -q
PYTHONPATH=. $PY -m pytest helao/deploy/hte/tests/test_standalone_operator.py -q
```

Check the changed files for placeholders: `git -C /mnt/STORAGE/repos/helao/helao-async diff unstable --name-only | xargs grep -nE "TODO|FIXME|test\.skip|\.only\(|pytest\.mark\.skip" || true`. Expected: no hits in files this plan created.

- [ ] **Step 9: black, then commit**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
/home/dan/miniforge3/envs/helao/bin/black helao/core/models/group_snapshot.py helao/hexagon/app/orch_graph_feed.py helao/hexagon/app/orch_payloads.py helao/hexagon/app/orch_host.py helao/ui/reflex/plots.py helao/ui/reflex/netgraph.py helao/ui/reflex/timeline_strip.py helao/ui/reflex/tree_pane.py helao/ui/reflex/operator.py helao/ui/reflex/group.py helao/ui/reflex/ingest.py helao/ui/reflex/app.py helao/ui/shared/palette.py helao/ui/shared/operator/orch_backend.py helao/hexagon/tests/group_fakes.py helao/hexagon/tests/test_group_snapshot.py helao/hexagon/tests/test_orch_graph_feed.py helao/hexagon/tests/test_orch_graph_feed_live.py helao/core/tests/test_reflex_group.py helao/core/tests/test_reflex_netgraph.py helao/core/tests/test_reflex_timeline_strip.py helao/core/tests/test_reflex_plots.py helao/core/tests/test_orch_backend_group.py helao/core/tests/test_palette.py
```

Never `black` `helao/core/tests/fixtures/sweeper_calibration/`. Re-run Step 8's first two commands after `black`, then:

```bash
git -C /mnt/STORAGE/repos/helao/helao-async add -u
git -C /mnt/STORAGE/repos/helao/helao-async add helao/hexagon/tests/test_orch_graph_feed_live.py
git -C /mnt/STORAGE/repos/helao/helao-async commit -m "test(group): live /ws_orch gate, browser check, docs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-review (run while writing)

- **Spec coverage:** §1 snapshot → Task 3. §2 feed (100 ms, heartbeat, event diff, `closing_out`, cached first frame, isolation) → Task 4. §3 routes → Task 4. §4 NetGraph (ports, Bézier, fan-out, fixed view, text, pulse, layout, group meaning) → Task 5 and `graph_marks` in Task 8. §5 strip (shapes, `+N`, colour, outline, progress, labels, local time and date prefix, narrow, clicks) → Task 6. §6 page (registration, header, buttons with spinner and inline error, info box, pane reuse, stale selection, connection loss, older orchestrator, unknown status) → Tasks 7-8. §7 palette → Tasks 2 and 8. Testing → Tasks 3-9. The known-duration progress mode has no data source (Open question 2).
- **Placeholders:** none. Each code step carries its code.
- **Type consistency:** pulses are `[edge_id, direction, t0, duration, color]` lists everywhere (`pulse_for`, `graph_marks`, `GroupState._pulses`). Selection is `[kind, item_key]`. `marks_chart(marks, *, x_domain, y_domain, panel_id, version, click=False)` is the same in Tasks 5 and 8.
- **Review Focus:** the five lines each have a pinned test in their owning task.

## Open questions (defaults are in the plan)

1. **`/group` is always registered** (coordinator instruction, the repo's "empty by config, never absent" rule) rather than only when an orchestrator exists (spec §6). Without one it renders `NO_ORCH_NOTE`. Its tint is a new `pink-50`, and `slate-500` fails the body floor on it, so the slate-500 failing set grows to seven.
2. **The progress fill has no expected-duration source.** Nothing in the snapshot carries one, so only the 2 Hz sawtooth is built.
3. **Queued experiments have no uuid**, so their rows carry `qidx` and clicks use `get_queue_object`.
4. **`ANNOTATIONS_IN_TOKEN` defaults to rebuild-on-label-change.** Task 9 measures whether xy applies annotation edits in place and flips it if so.
5. **The orchestrator's own actions** (`wait`) have no edge. They show as the orch node's subtext and fire no pulse. If they never reach `active_dict`, the live test stops for a decision.
6. **The "older orchestrator" message** comes from never receiving a `/ws_orch` frame while `get_orch_state` answers, not from parsing a WebSocket 404.
7. **Error statuses** are `{errored, aborted, estopped}`. `skipped` counts as done.
