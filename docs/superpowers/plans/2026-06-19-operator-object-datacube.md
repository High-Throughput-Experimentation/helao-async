# Operator Object Datacube (HTML Tree) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two read-only HTML `<details>` object trees to the Bokeh operator (one beside each tabbed table block) that render the selected row's full object with `*_params` expanded; widen the app to full browser width with a 50/50 table|tree split; and prefix dynamic parameter labels with an enumeration index.

**Architecture:** A pure recursive renderer turns any dict/list/scalar into nested collapsible HTML assigned to `Div.text`. Plan/history/action-server objects resolve locally; queue objects are fetched lazily on row-select via a new backend method + OrchAPI endpoint. Selection and tab-change callbacks drive a per-side render function.

**Tech Stack:** Python 3.12, Bokeh 3.9.0 (`Div`, `DataTable`, `Tabs`, `row`/`column`, `sizing_mode`), FastAPI OrchAPI, the project's no-pytest standalone test runner.

**Spec:** `docs/superpowers/specs/2026-06-19-operator-object-datacube-design.md`

**Key files:**
- `helao/core/servers/operator/bokeh_operator.py` — renderer, header, widgets, wiring, layout, param enumeration.
- `helao/core/servers/operator/orch_backend.py` — `get_queue_object` on `OrchBackend`/`LocalBackend`/`RemoteBackend`.
- `helao/core/servers/orch_api.py` — `_queue_object_payload` helper + `/get_queue_object` endpoint.
- `helao/core/tests/test_standalone_operator.py` — all new tests + registration in `run_all()`.

**Test runner (used by every "run tests" step):**
```bash
PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async /home/dan/miniforge3/envs/helao/bin/python \
  -m helao.core.tests.test_standalone_operator
```

---

## Task 1: Parameter label enumeration (independent, ships first)

**Files:**
- Modify: `helao/core/servers/operator/bokeh_operator.py:1873-1874` (label `Div` inside `add_dynamic_inputs`)
- Test: `helao/core/tests/test_standalone_operator.py`

- [ ] **Step 1: Write the failing test**

Add to `helao/core/tests/test_standalone_operator.py`:

```python
def test_param_label_enumeration():
    from bokeh.document import Document
    from helao.core.servers.operator.bokeh_operator import BokehOperator

    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    op.sequence_dropdown.value = "seq0"  # selected in __init__; single param "x"
    # the label Div sits at param_layout[0] -> layout([[Div],[input],Spacer])
    label_div = op.seq_param_layout[0].children[0].children[0]
    assert label_div.text.startswith("0) x"), label_div.text
    # widget key unchanged (decoupled from display)
    assert op.seq_param_input[0].name == "x"
    op.cleanup_session(None)
    print("test_param_label_enumeration PASS")
```

- [ ] **Step 2: Register the test and run to verify it fails**

Add `test_param_label_enumeration()` to `run_all()` (after `test_find_input_matches_name()`).

Run the test runner.
Expected: FAIL — `AssertionError` (label is `"x [int]"`, not `"0) x …"`).

- [ ] **Step 3: Implement the enumeration prefix**

In `bokeh_operator.py`, the label `Div` text currently reads:

```python
                            Div(
                                text=f"{args[idx]} <i>[{str(argtypes[idx]).split()[-1].strip(chr(39) + '<>]').split('.')[-1].replace('[', ' of ')}]</i>",
                                width=self.max_width - 40,
                                height=18,
                            ),
```

Change the `text=` f-string to prefix `f"{idx}) "`:

```python
                            Div(
                                text=f"{idx}) {args[idx]} <i>[{str(argtypes[idx]).split()[-1].strip(chr(39) + '<>]').split('.')[-1].replace('[', ' of ')}]</i>",
                                width=self.max_width - 40,
                                height=18,
                            ),
```

- [ ] **Step 4: Run tests to verify pass**

Run the test runner.
Expected: `test_param_label_enumeration PASS` and `ALL STANDALONE_OPERATOR TESTS PASS`.

- [ ] **Step 5: Commit**

```bash
git add helao/core/servers/operator/bokeh_operator.py helao/core/tests/test_standalone_operator.py
git commit -m "feat(operator): enumerate dynamic param labels (0) name [type])

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `_object_to_html` renderer + `_tree_header_text` (pure functions)

**Files:**
- Modify: `helao/core/servers/operator/bokeh_operator.py` (add two module-level functions near the top, after the imports / before `class BokehOperator`)
- Test: `helao/core/tests/test_standalone_operator.py`

- [ ] **Step 1: Write the failing tests**

Add to the test file:

```python
def test_object_to_html():
    from helao.core.servers.operator.bokeh_operator import _object_to_html

    obj = {
        "sequence_name": "CA_led",
        "sequence_uuid": "0123456789abcdef",
        "sequence_params": {"plate_id": 4083, "led": 385},
        "experiment_list": [{"experiment_name": "e0"}, {"experiment_name": "e1"}],
    }
    html = _object_to_html(obj, open_keys=["sequence_params"])
    # params group open, others closed
    assert "<details open><summary>sequence_params</summary>" in html
    assert "<details><summary>sequence_uuid</summary>" in html or \
           "sequence_uuid: 0123456789abcdef" in html
    # nested scalar leaf
    assert "plate_id: 4083" in html
    # list shows length
    assert "experiment_list [2]" in html
    # empty + non-dict fallbacks
    assert "empty" in _object_to_html({})
    assert "scalar" in _object_to_html("scalar")
    print("test_object_to_html PASS")


def test_tree_header_text():
    from helao.core.servers.operator.bokeh_operator import (
        _tree_header_text, _server_header_text,
    )
    obj = {"sequence_name": "seq0", "sequence_uuid": "0123456789abcdef"}
    assert _tree_header_text("sequence", obj) == "seq0 · 89abcdef"
    # missing uuid -> name only
    assert _tree_header_text("action", {"action_name": "noop"}) == "noop"
    # server: name + host:port
    cfg = {"host": "127.0.0.1", "port": 8001}
    assert _server_header_text("MOTOR", cfg) == "MOTOR · 127.0.0.1:8001"
    print("test_tree_header_text PASS")
```

- [ ] **Step 2: Register and run to verify failure**

Add `test_object_to_html()` and `test_tree_header_text()` to `run_all()` (after `test_param_label_enumeration()`).

Run the test runner.
Expected: FAIL — `ImportError: cannot import name '_object_to_html'`.

- [ ] **Step 3: Implement the functions**

In `bokeh_operator.py`, add near the other module-level imports (top of file) and before `class BokehOperator`:

```python
import html as _html


def _render_node(key, val, top=False, open_keys=()):
    """Render one object node as collapsible HTML. Top-level nodes whose key is
    in ``open_keys`` start expanded; everything else starts collapsed."""
    open_attr = " open" if (top and key in open_keys) else ""
    label = _html.escape(str(key))
    if isinstance(val, dict):
        inner = "".join(
            _render_node(k, v, top=False, open_keys=open_keys) for k, v in val.items()
        )
        return f"<details{open_attr}><summary>{label}</summary>{inner}</details>"
    if isinstance(val, (list, tuple)):
        inner = "".join(
            _render_node(f"[{i}]", v, top=False, open_keys=open_keys)
            for i, v in enumerate(val)
        )
        return f"<details{open_attr}><summary>{label} [{len(val)}]</summary>{inner}</details>"
    return (
        f"<div style='margin-left:1em'>{label}: {_html.escape(str(val))}</div>"
    )


def _object_to_html(obj, open_keys=()):
    """Render a dict (or scalar) as a nested ``<details>`` tree string."""
    if not isinstance(obj, dict):
        return f"<div>{_html.escape(str(obj))}</div>"
    if not obj:
        return "<div><i>empty</i></div>"
    return "".join(
        _render_node(k, v, top=True, open_keys=open_keys) for k, v in obj.items()
    )


def _truncate_uuid(value):
    return str(value)[-8:] if value else ""


def _tree_header_text(kind, obj):
    """Header line for a sequence/experiment/action object: 'name · uuid8'."""
    name = obj.get(f"{kind}_name", "") if isinstance(obj, dict) else ""
    uuid8 = _truncate_uuid(obj.get(f"{kind}_uuid")) if isinstance(obj, dict) else ""
    return f"{name} · {uuid8}" if uuid8 else f"{name}"


def _server_header_text(server_name, cfg):
    """Header line for an action-server row: 'NAME · host:port'."""
    cfg = cfg or {}
    return f"{server_name} · {cfg.get('host', '')}:{cfg.get('port', '')}"
```

- [ ] **Step 4: Run tests to verify pass**

Run the test runner.
Expected: `test_object_to_html PASS`, `test_tree_header_text PASS`, and the full suite passes.

- [ ] **Step 5: Commit**

```bash
git add helao/core/servers/operator/bokeh_operator.py helao/core/tests/test_standalone_operator.py
git commit -m "feat(operator): object-to-HTML tree renderer + header helpers

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `get_queue_object` — orch helper + endpoint

**Files:**
- Modify: `helao/core/servers/orch_api.py` (module helper after `_prepend_sequences`, ~line 105; endpoint after `/remove_sequence`, ~line 405)
- Test: `helao/core/tests/test_standalone_operator.py`

- [ ] **Step 1: Write the failing test**

Add to the test file:

```python
def test_queue_object_payload():
    from helao.core.servers import orch_api

    class _Item:
        def __init__(self, name):
            self._name = name
        def as_dict(self):
            return {"sequence_name": self._name, "sequence_params": {"x": 1}}

    class _O(_FakeOrch):
        def __init__(self):
            super().__init__()
            self.sequence_dq = [_Item("A"), _Item("B")]
            self.experiment_dq = []
            self.action_dq = []

    orch = _O()
    assert orch_api._queue_object_payload(orch, "sequence", 1) == {
        "sequence_name": "B", "sequence_params": {"x": 1},
    }
    # out-of-range -> empty dict
    assert orch_api._queue_object_payload(orch, "sequence", 9) == {}
    # unknown kind -> empty dict
    assert orch_api._queue_object_payload(orch, "bogus", 0) == {}
    print("test_queue_object_payload PASS")
```

- [ ] **Step 2: Register and run to verify failure**

Add `test_queue_object_payload()` to `run_all()` (after `test_prepend_sequences_helper()`).

Run the test runner.
Expected: FAIL — `AttributeError: module ... has no attribute '_queue_object_payload'`.

- [ ] **Step 3: Implement the helper + endpoint**

In `orch_api.py`, add the module-level helper after `_prepend_sequences` (it ends ~line 105):

```python
def _queue_object_payload(orch, kind: str, idx: int) -> dict:
    """Return the full dict for the queued item of ``kind`` at ``idx``.

    Out-of-range indices or unknown kinds return ``{}`` (the queue may have
    mutated since the table was last polled — snapshot semantics)."""
    dq = {
        "sequence": getattr(orch, "sequence_dq", None),
        "experiment": getattr(orch, "experiment_dq", None),
        "action": getattr(orch, "action_dq", None),
    }.get(kind)
    if dq is None:
        return {}
    try:
        return dq[idx].as_dict()
    except (IndexError, KeyError, AttributeError):
        return {}
```

Then register the endpoint after the `/remove_sequence` block (~line 405):

```python
        @self.post("/get_queue_object", tags=["private"])
        def get_queue_object(kind: str, idx: int):
            """Return the full dict for a queued sequence/experiment/action."""
            return _queue_object_payload(self.orch, kind, idx)
```

- [ ] **Step 4: Run tests to verify pass**

Run the test runner.
Expected: `test_queue_object_payload PASS` and full suite passes.

- [ ] **Step 5: Commit**

```bash
git add helao/core/servers/orch_api.py helao/core/tests/test_standalone_operator.py
git commit -m "feat(orch-api): expose /get_queue_object for full queued objects

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: `get_queue_object` on the backends

**Files:**
- Modify: `helao/core/servers/operator/orch_backend.py` — abstract stub on `OrchBackend` (~after line 53, the `list_actions` stub), `LocalBackend` (~after line 171), `RemoteBackend` (~after line 332)
- Test: `helao/core/tests/test_standalone_operator.py`

- [ ] **Step 1: Write the failing tests**

Add to the test file:

```python
def test_local_backend_get_queue_object():
    from helao.core.servers.operator.orch_backend import LocalBackend

    class _Item:
        def as_dict(self):
            return {"action_name": "noop", "action_params": {"v": 2}}

    class _O(_FakeOrch):
        sequence_lib = {}
        experiment_lib = {}
        def __init__(self):
            super().__init__()
            self.action_dq = [_Item()]

    be = LocalBackend(_O())
    assert asyncio.run(be.get_queue_object("action", 0)) == {
        "action_name": "noop", "action_params": {"v": 2},
    }
    assert asyncio.run(be.get_queue_object("action", 5)) == {}
    print("test_local_backend_get_queue_object PASS")


def test_remote_backend_get_queue_object():
    from helao.core.servers.operator.orch_backend import RemoteBackend
    from helao.core.error import ErrorCodes

    calls = []

    async def fake_dispatch(server_key, host, port, endpoint, params_dict=None, json_dict=None, **kw):
        calls.append((endpoint, params_dict))
        return {"sequence_name": "B", "sequence_params": {"x": 1}}, ErrorCodes.none

    be = RemoteBackend.__new__(RemoteBackend)
    be.orch_key = "ORCH"
    be.host = "127.0.0.1"
    be.port = 8001
    be._dispatch = fake_dispatch

    out = asyncio.run(be.get_queue_object("sequence", 1))
    assert out == {"sequence_name": "B", "sequence_params": {"x": 1}}
    assert calls[0] == ("get_queue_object", {"kind": "sequence", "idx": 1})
    print("test_remote_backend_get_queue_object PASS")
```

- [ ] **Step 2: Register and run to verify failure**

Add both tests to `run_all()` (after `test_remote_backend_move_remove()`).

Run the test runner.
Expected: FAIL — `AttributeError: 'LocalBackend' object has no attribute 'get_queue_object'`.

- [ ] **Step 3: Implement on all three classes**

In `orch_backend.py`, add the abstract stub to `OrchBackend` right after the `list_actions` stub (~line 53):

```python
    @abstractmethod
    async def get_queue_object(self, kind: str, idx: int) -> dict: ...
```

Add to `LocalBackend` (after `list_actions`, ~line 171):

```python
    async def get_queue_object(self, kind, idx):
        dq = {
            "sequence": self.orch.sequence_dq,
            "experiment": self.orch.experiment_dq,
            "action": self.orch.action_dq,
        }.get(kind)
        if dq is None:
            return {}
        try:
            return dq[idx].as_dict()
        except (IndexError, KeyError, AttributeError):
            return {}
```

Add to `RemoteBackend` (after `list_actions`, ~line 332):

```python
    async def get_queue_object(self, kind, idx):
        resp = await self._call(
            "get_queue_object", params_dict={"kind": kind, "idx": idx}
        )
        return resp or {}
```

- [ ] **Step 4: Run tests to verify pass**

Run the test runner.
Expected: both new tests PASS and full suite passes.

> Note: `OrchBackend` is `ABC` with `@abstractmethod`. Adding an abstract method means any other concrete subclass must implement it — only `LocalBackend` and `RemoteBackend` exist, both done above.

- [ ] **Step 5: Commit**

```bash
git add helao/core/servers/operator/orch_backend.py helao/core/tests/test_standalone_operator.py
git commit -m "feat(backend): add get_queue_object to OrchBackend/Local/Remote

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Tree widgets + history-object retention

**Files:**
- Modify: `helao/core/servers/operator/bokeh_operator.py` — add `Div` widgets near line 449 (the existing description `Div`s); add `self._hist_objs` init near line 154 (`self.plan = []`); populate `self._hist_objs` in `get_history` (~line 1219)
- Test: `helao/core/tests/test_standalone_operator.py`

- [ ] **Step 1: Write the failing test**

Add to the test file:

```python
def test_history_objects_retained():
    from bokeh.document import Document
    from helao.core.servers.operator.bokeh_operator import BokehOperator

    class _BE(_MockBackend):
        async def get_histories(self):
            return {
                "action": [("au1", {"action_name": "noop", "action_uuid": "au1"})],
                "experiment": [],
                "sequence": [],
            }

    op = BokehOperator(_FakeVisOp(Document()), _BE())
    asyncio.run(op.get_history())
    assert op._hist_objs["action"][0]["action_name"] == "noop"
    # widgets exist
    assert op.planhistory_tree_div is not None
    assert op.queue_tree_div is not None
    assert op.planhistory_tree_header is not None
    assert op.queue_tree_header is not None
    op.cleanup_session(None)
    print("test_history_objects_retained PASS")
```

- [ ] **Step 2: Register and run to verify failure**

Add `test_history_objects_retained()` to `run_all()` (after `test_object_to_html()` group, before layout tests).

Run the test runner.
Expected: FAIL — `AttributeError: 'BokehOperator' object has no attribute '_hist_objs'`.

- [ ] **Step 3: Add init state**

In `__init__`, next to `self.plan = []` (line 154), add:

```python
        self.plan = []
        self._hist_objs = {"action": [], "experiment": [], "sequence": []}
```

- [ ] **Step 4: Add the four `Div` widgets**

Near the existing description `Div`s (~line 449, after `self.seqspec_descr_txt`), add:

```python
        self.planhistory_tree_header = Div(
            text="<b>select a row</b>", height=20, sizing_mode="stretch_width"
        )
        self.planhistory_tree_div = Div(
            text="", sizing_mode="stretch_width",
            styles={"overflow": "auto", "max-height": "200px"},
        )
        self.queue_tree_header = Div(
            text="<b>select a row</b>", height=20, sizing_mode="stretch_width"
        )
        self.queue_tree_div = Div(
            text="", sizing_mode="stretch_width",
            styles={"overflow": "auto", "max-height": "200px"},
        )
```

- [ ] **Step 5: Retain full history objects in `get_history`**

In `get_history` (~line 1219), the method builds `*_history_lists` in reverse-sorted order. Reset the object lists at the top and append the full dict alongside each row. After the existing line `for key in self.action_history_lists: self.action_history_lists[key] = []`, add a reset, and inside each loop append the full dict.

Add right after the function's first list-reset block (the action loop). Concretely, set the resets near the top of the method:

```python
        self._hist_objs = {"action": [], "experiment": [], "sequence": []}
```

Then inside the action loop (`for actuuid, actdict in ...`), add as the first line of the loop body:

```python
            self._hist_objs["action"].append(actdict)
```

Inside the experiment loop (`for expuuid, expdict in ...`):

```python
            self._hist_objs["experiment"].append(expdict)
```

Inside the sequence loop (`for sequuid, seqdict in ...`):

```python
            self._hist_objs["sequence"].append(seqdict)
```

This keeps `_hist_objs[kind][row_index]` aligned with the table rows (same order, same reverse sort).

- [ ] **Step 6: Run tests to verify pass**

Run the test runner.
Expected: `test_history_objects_retained PASS` and full suite passes.

- [ ] **Step 7: Commit**

```bash
git add helao/core/servers/operator/bokeh_operator.py helao/core/tests/test_standalone_operator.py
git commit -m "feat(operator): tree Divs + retain full history objects

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Render functions + selection/tab wiring

**Files:**
- Modify: `helao/core/servers/operator/bokeh_operator.py` — add render methods (near `update_tables`, ~line 2258); wire `on_change` after the `Tabs` are built and after `add_root` (~line 806)
- Test: `helao/core/tests/test_standalone_operator.py`

- [ ] **Step 1: Write the failing tests**

Add to the test file:

```python
def test_planhistory_tree_render_plan():
    from bokeh.document import Document
    from helao.core.servers.operator.bokeh_operator import BokehOperator
    from helao.helpers.premodels import Sequence

    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    s = Sequence(sequence_name="seqX")
    s.sequence_params = {"plate_id": 7}
    op.plan = [s]
    op.planhistory_tabs.active = 0  # Plan tab
    op.experiment_plan_source.selected.indices = [0]
    op._render_planhistory_tree()
    assert "seqX" in op.planhistory_tree_header.text
    assert "<details open><summary>sequence_params</summary>" in op.planhistory_tree_div.text
    assert "plate_id: 7" in op.planhistory_tree_div.text
    op.cleanup_session(None)
    print("test_planhistory_tree_render_plan PASS")


def test_queue_tree_render_action_server():
    from bokeh.document import Document
    from helao.core.servers.operator.bokeh_operator import BokehOperator

    vis = _FakeVisOp(Document())
    vis.world_cfg["servers"]["MOTOR"] = {
        "group": "action", "host": "10.0.0.1", "port": 8005,
        "params": {"axis": "x"},
    }
    op = BokehOperator(vis, _MockBackend())
    asyncio.run(op.get_orch_status_summary())
    op.action_server_source.data = {
        "action_server": ["MOTOR"], "server_status": ["idle"], "driver_status": ["ok"],
    }
    op.queue_tabs.active = 3  # Action Servers tab
    op.action_server_source.selected.indices = [0]
    op._render_queue_tree()
    assert "MOTOR · 10.0.0.1:8005" in op.queue_tree_header.text
    assert "<details open><summary>params</summary>" in op.queue_tree_div.text
    assert "axis: x" in op.queue_tree_div.text
    op.cleanup_session(None)
    print("test_queue_tree_render_action_server PASS")


def test_queue_tree_render_lazy_sequence():
    from bokeh.document import Document
    from helao.core.servers.operator.bokeh_operator import BokehOperator

    fetched = {}

    class _BE(_MockBackend):
        async def get_queue_object(self, kind, idx):
            fetched["args"] = (kind, idx)
            return {"sequence_name": "Q", "sequence_uuid": "ffff0000ffff1111",
                    "sequence_params": {"k": 9}}

    op = BokehOperator(_FakeVisOp(Document()), _BE())
    op.queue_tabs.active = 0  # Sequences tab
    op.sequence_source.selected.indices = [2]
    op._render_queue_tree()
    # lazy fetch is scheduled on next tick; drain it
    _drain_callbacks(op.vis.doc)
    assert fetched["args"] == ("sequence", 2)
    assert "Q · ffff1111" in op.queue_tree_header.text
    assert "<details open><summary>sequence_params</summary>" in op.queue_tree_div.text
    op.cleanup_session(None)
    print("test_queue_tree_render_lazy_sequence PASS")
```

- [ ] **Step 2: Register and run to verify failure**

Add the three tests to `run_all()` (after `test_history_objects_retained()`).

Run the test runner.
Expected: FAIL — `AttributeError: 'BokehOperator' object has no attribute '_render_planhistory_tree'`.

- [ ] **Step 3: Implement the render methods**

In `bokeh_operator.py`, add these methods to `BokehOperator` (near `update_tables`, ~line 2258). They use the module functions `_object_to_html`, `_tree_header_text`, `_server_header_text` from Task 2.

```python
    @staticmethod
    def _open_keys(obj):
        """Top-level keys to expand by default: any '*_params' key."""
        if not isinstance(obj, dict):
            return []
        return [k for k in obj if k.endswith("_params")]

    def _set_tree(self, header_div, tree_div, header_text, obj, open_keys):
        header_div.text = f"<b>{header_text}</b>" if header_text.strip() else "<b>—</b>"
        tree_div.text = _object_to_html(obj, open_keys=open_keys)

    def _clear_tree(self, header_div, tree_div):
        header_div.text = "<b>select a row</b>"
        tree_div.text = ""

    def _render_planhistory_tree(self):
        """Render the tree beside the non-queued (plan/history) tabs."""
        active = self.planhistory_tabs.active
        # (source, kind, object-getter) per tab index
        if active == 0:  # Plan
            src, kind, getter = self.experiment_plan_source, "sequence", \
                lambda i: self.plan[i].as_dict()
        elif active == 1:  # Action History
            src, kind, getter = self.action_history_source, "action", \
                lambda i: self._hist_objs["action"][i]
        elif active == 2:  # Experiment History
            src, kind, getter = self.experiment_history_source, "experiment", \
                lambda i: self._hist_objs["experiment"][i]
        else:  # Sequence History
            src, kind, getter = self.sequence_history_source, "sequence", \
                lambda i: self._hist_objs["sequence"][i]
        idxs = src.selected.indices
        if not idxs:
            self._clear_tree(self.planhistory_tree_header, self.planhistory_tree_div)
            return
        try:
            obj = getter(idxs[0])
        except (IndexError, KeyError, AttributeError):
            self._clear_tree(self.planhistory_tree_header, self.planhistory_tree_div)
            return
        self._set_tree(
            self.planhistory_tree_header, self.planhistory_tree_div,
            _tree_header_text(kind, obj), obj, self._open_keys(obj),
        )

    def _render_queue_tree(self):
        """Render the tree beside the queue tabs."""
        active = self.queue_tabs.active
        if active == 3:  # Action Servers -> config dict (local)
            idxs = self.action_server_source.selected.indices
            if not idxs:
                self._clear_tree(self.queue_tree_header, self.queue_tree_div)
                return
            names = self.action_server_source.data.get("action_server", [])
            try:
                name = names[idxs[0]]
            except IndexError:
                self._clear_tree(self.queue_tree_header, self.queue_tree_div)
                return
            cfg = self.vis.world_cfg["servers"].get(name, {})
            self._set_tree(
                self.queue_tree_header, self.queue_tree_div,
                _server_header_text(name, cfg), cfg, ["params"],
            )
            return
        # Sequences / Experiments / Actions -> lazy fetch full object
        kind = {0: "sequence", 1: "experiment", 2: "action"}[active]
        src = {0: self.sequence_source, 1: self.experiment_source,
               2: self.action_source}[active]
        idxs = src.selected.indices
        if not idxs:
            self._clear_tree(self.queue_tree_header, self.queue_tree_div)
            return
        self.vis.doc.add_next_tick_callback(
            partial(self._async_render_queue_obj, kind, idxs[0])
        )

    async def _async_render_queue_obj(self, kind, idx):
        obj = await self.backend.get_queue_object(kind, idx)
        if not obj:
            self._clear_tree(self.queue_tree_header, self.queue_tree_div)
            return
        self._set_tree(
            self.queue_tree_header, self.queue_tree_div,
            _tree_header_text(kind, obj), obj, self._open_keys(obj),
        )
```

- [ ] **Step 4: Wire the callbacks**

In `__init__`, after `self.vis.doc.add_root(self.dynamic_col)` (line 806), register selection + tab callbacks. The `on_change("indices", ...)` callback signature is `(attr, old, new)`; wrap with lambdas that ignore the args:

```python
        # Tree views react to row-selection in the active tab + tab switches.
        for _src in (
            self.experiment_plan_source, self.action_history_source,
            self.experiment_history_source, self.sequence_history_source,
        ):
            _src.selected.on_change(
                "indices", lambda a, o, n: self._render_planhistory_tree()
            )
        self.planhistory_tabs.on_change(
            "active", lambda a, o, n: self._render_planhistory_tree()
        )
        for _src in (
            self.sequence_source, self.experiment_source,
            self.action_source, self.action_server_source,
        ):
            _src.selected.on_change(
                "indices", lambda a, o, n: self._render_queue_tree()
            )
        self.queue_tabs.on_change(
            "active", lambda a, o, n: self._render_queue_tree()
        )
```

> `partial` and `column`/`row` are already imported in this module (used throughout). Confirm `partial` is imported at top; it is (used in `add_next_tick_callback(partial(...))` calls in `__init__`).

- [ ] **Step 5: Run tests to verify pass**

Run the test runner.
Expected: `test_planhistory_tree_render_plan PASS`, `test_queue_tree_render_action_server PASS`, `test_queue_tree_render_lazy_sequence PASS`, and full suite passes.

- [ ] **Step 6: Commit**

```bash
git add helao/core/servers/operator/bokeh_operator.py helao/core/tests/test_standalone_operator.py
git commit -m "feat(operator): render object trees on row-select + tab change

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Full-width layout + 50/50 table|tree split

**Files:**
- Modify: `helao/core/servers/operator/bokeh_operator.py` — `_make_table` (line 836), `layout4` queue/plan rows (lines 703-768), `dynamic_col` (line 799)
- Test: `helao/core/tests/test_standalone_operator.py`

- [ ] **Step 1: Write the failing test**

Add to the test file (asserts the structural wiring, not pixel layout):

```python
def test_layout_is_stretch_width():
    from bokeh.document import Document
    from helao.core.servers.operator.bokeh_operator import BokehOperator

    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    assert op.dynamic_col.sizing_mode == "stretch_width"
    # tables stretch instead of fixed width
    assert op.sequence_table.sizing_mode == "stretch_width"
    op.cleanup_session(None)
    print("test_layout_is_stretch_width PASS")
```

- [ ] **Step 2: Register and run to verify failure**

Add `test_layout_is_stretch_width()` to `run_all()` (after the Task 6 tests).

Run the test runner.
Expected: FAIL — `dynamic_col.sizing_mode` is the default (`None`/`"fixed"`), not `"stretch_width"`.

- [ ] **Step 3: Make tables stretch**

In `_make_table` (line 836), replace the fixed `width=self.max_width - 20` with stretch sizing. Change:

```python
        table = DataTable(
            source=source,
            columns=columns,
            width=self.max_width - 20,
            height=200,
            autosize_mode="force_fit" if "fit_columns" not in extra_kwargs else "none",
            **extra_kwargs,
        )
```

to:

```python
        table = DataTable(
            source=source,
            columns=columns,
            sizing_mode="stretch_width",
            height=200,
            autosize_mode="force_fit" if "fit_columns" not in extra_kwargs else "none",
            **extra_kwargs,
        )
```

- [ ] **Step 4: Put each tab block beside its tree (50/50)**

In `layout4` (lines 703-768), replace the single-child `[self.planhistory_tabs]` row and the `[self.queue_tabs]` row with `row(...)` pairs. Change the `[self.planhistory_tabs],` line to:

```python
                        [
                            row(
                                column(self.planhistory_tabs,
                                       sizing_mode="stretch_width"),
                                column(self.planhistory_tree_header,
                                       self.planhistory_tree_div,
                                       sizing_mode="stretch_width"),
                                sizing_mode="stretch_width",
                            ),
                        ],
```

and the `[self.queue_tabs],` line to:

```python
                        [
                            row(
                                column(self.queue_tabs,
                                       sizing_mode="stretch_width"),
                                column(self.queue_tree_header,
                                       self.queue_tree_div,
                                       sizing_mode="stretch_width"),
                                sizing_mode="stretch_width",
                            ),
                        ],
```

> `row` and `column` are imported at the top of the module (already used). Two `stretch_width` children in a `row` split the available width evenly.

- [ ] **Step 5: Make the root + wrapping layouts stretch**

In `__init__`, the `dynamic_col` (line 799) is built with `column(...)`. Add `sizing_mode="stretch_width"`:

```python
        self.dynamic_col = column(
            self.layout0,
            layout(height_policy="min"),
            self.select_tabs,
            layout(height_policy="min"),
            self.layout4,  # placeholder  # placeholder
            sizing_mode="stretch_width",
        )
```

Then change the `width=self.max_width` on the `layout4` inner blocks that hold the tabs to stretch. The block that wraps the tabs/buttons (the one with `background="#AED6F1"`, ends ~line 768) sets `width=self.max_width`. Replace that single `width=self.max_width,` argument with `sizing_mode="stretch_width",` so the blue panel fills the window:

```python
                    background="#AED6F1",
                    sizing_mode="stretch_width",
                    height_policy="min",
                ),
```

Leave the header/error/orch-section blocks at their fixed `max_width` (they read fine left-aligned). Only the tab-holding blue block needs to stretch for the 50/50 split to have room.

- [ ] **Step 6: Run tests to verify pass**

Run the test runner.
Expected: `test_layout_is_stretch_width PASS` and full suite passes.

- [ ] **Step 7: Visual smoke check (manual, non-blocking)**

The standalone test deployment renders the operator without hardware. Launch and eyeball the 50/50 split + trees:

```bash
./helao.sh <test_operator_prefix>
```

Confirm: app fills browser width; each tab block sits left with its tree on the right; selecting rows updates the tree; `*_params` is expanded. Watch for the known Bokeh Tabs "tallest-panel whitespace" gotcha around the param block — if a gap appears, it is pre-existing layout behavior, not introduced here. Note any issue but do not block the commit on pixel polish.

- [ ] **Step 8: Commit**

```bash
git add helao/core/servers/operator/bokeh_operator.py helao/core/tests/test_standalone_operator.py
git commit -m "feat(operator): full-width layout, 50/50 table|tree split

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Whole-branch verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full standalone-operator suite**

Run the test runner.
Expected: `ALL STANDALONE_OPERATOR TESTS PASS` (now including all tests added in Tasks 1-7).

- [ ] **Step 2: Run the project unit-test gate**

```bash
PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async /home/dan/miniforge3/envs/helao/bin/python run_unit_tests.py
```

Expected: exits 0 (the sample-model unit test that `launch.py` runs before launch).

- [ ] **Step 3: Confirm clean tree + review the diff range**

```bash
git status -s
git log --oneline unstable..HEAD | head -20
```

Expected: clean tree; the new commits from Tasks 1-7 present.

- [ ] **Step 4: Request code review**

Use `superpowers:requesting-code-review` against the branch diff before any merge/PR. Pay attention to: HTML escaping in `_object_to_html`, history-object/row alignment in `get_history`, lazy-fetch idx-shift handling, and the layout `sizing_mode` changes near the tuned param block.

---

## Self-Review Notes (author checklist — completed)

- **Spec coverage:** tree renderer (Task 2), header incl. server name+port (Task 2), data sourcing local/lazy (Tasks 3-6), backend method + endpoint (Tasks 3-4), selection/tab reactivity (Task 6), full-width 50/50 layout (Task 7), param enumeration (Task 1), testing across tasks, whole-branch gate (Task 8). All spec sections mapped.
- **Type/name consistency:** `_object_to_html(obj, open_keys)`, `_tree_header_text(kind, obj)`, `_server_header_text(name, cfg)`, `get_queue_object(kind, idx)`, `_queue_object_payload(orch, kind, idx)`, `_hist_objs`, `planhistory_tree_div`/`queue_tree_div`/`planhistory_tree_header`/`queue_tree_header`, `_render_planhistory_tree`/`_render_queue_tree`/`_async_render_queue_obj` — used identically across tasks.
- **Placeholders:** none; every code step shows full code.
- **Known risk (carried from spec):** poll refresh clears table selection → trees fall back to placeholder until reselect; lazy idx can shift if queue mutates between poll and click (returns `{}`); full-width near param block may surface the Bokeh Tabs whitespace gotcha — Task 7 Step 7 smoke-checks it.
