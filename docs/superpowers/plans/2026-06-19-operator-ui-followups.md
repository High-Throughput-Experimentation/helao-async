# Operator UI Follow-ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply five operator UI follow-ups (A merged type-hint label, B label sanitization, C save/restore label+campaign, D row reorder/remove controls + one-row-per-sequence plan table, E uuid truncation) to `BokehOperator` and the supporting orch/backend/API layers.

**Architecture:** Builds directly on the merged plan-buffer feature already on `feat/standalone-operator`. Orch-side changes (B sanitizer, D `move_sequence`/`remove_sequence`) are added to `Orch`, surfaced through the `OrchBackend` ABC + `LocalBackend`/`RemoteBackend`, and exposed as OrchAPI endpoints. UI-side changes live entirely in `bokeh_operator.py`. The param-key/display decoupling (A) moves the param key from each widget's Bokeh `title` onto its free-form `name` so the title can render a custom merged label.

**Tech Stack:** Python 3.12, FastAPI, Bokeh, Pydantic (`helao.helpers.premodels.Sequence`/`Experiment`), `zdeque`. No pytest — plain assert-functions in `helao/core/tests/test_standalone_operator.py`, run with the commands shown below.

**Test commands (used in every task):**
- Module suite: `PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao python -m helao.core.tests.test_standalone_operator`
  Expected on success: ends with `ALL STANDALONE_OPERATOR TESTS PASS`.
- Full suite (final task only): `conda run -n helao python run_unit_tests.py`

**Important conventions:**
- Each new test function must be added to the `run_all()` body (near line 614) AND defined above it, or it will not execute.
- Tests print `"<test_name> PASS"` on success and use bare `assert`. Construct `BokehOperator` with `BokehOperator(_FakeVisOp(Document()), _MockBackend())` and always call `op.cleanup_session(None)` at the end.
- Pyright diagnostics in this env are noise (unresolved conda imports, test fakes not matching `Vis`). Ignore them; trust the test run.

---

### Task 1: B — `sanitize_sequence_label` in orch.py

**Files:**
- Modify: `helao/core/servers/orch.py` (add `import re` near line 22; add module-level helper; call it in `_prep_sequence_meta` ~1742 and `add_split_sequences` ~1820)
- Test: `helao/core/tests/test_standalone_operator.py`

- [ ] **Step 1: Write the failing tests**

Add these two functions above `run_all()` (near line 613):

```python
def test_sanitize_sequence_label():
    from helao.core.servers.orch import sanitize_sequence_label
    assert sanitize_sequence_label("a b__c d") == "a_b_c_d"
    assert sanitize_sequence_label("a_b") == "a_b"        # single underscore preserved
    assert sanitize_sequence_label("") == ""
    assert sanitize_sequence_label(None) is None
    print("test_sanitize_sequence_label PASS")


def test_orch_add_sequence_sanitizes_label():
    from helao.core.servers.orch import Orch
    from helao.helpers.premodels import Sequence
    from helao.helpers.zdeque import zdeque

    orch = Orch.__new__(Orch)
    orch.sequence_dq = zdeque([])
    orch.active_run_id = None
    orch.sequence_codehash_lib = {}
    orch.sequence_codepath_lib = {}
    orch.sequence_lib = {}

    seq = Sequence(sequence_name="seq0")
    seq.sequence_label = "x y__z"
    asyncio.run(orch.add_sequence(seq))
    assert list(orch.sequence_dq)[0].sequence_label == "x_y_z"
    print("test_orch_add_sequence_sanitizes_label PASS")
```

Register both in `run_all()` (add the two calls right after `test_orch_prepend_order_and_run_id()`).

- [ ] **Step 2: Run tests to verify they fail**

Run the module suite command.
Expected: FAIL with `ImportError: cannot import name 'sanitize_sequence_label'`.

- [ ] **Step 3: Add the helper and `import re`**

In `helao/core/servers/orch.py`, add `import re` with the other stdlib imports (after `import json` on line 22):

```python
import json
import re
```

Add this module-level function (place it just above the `class Orch` definition; if unsure, put it immediately after the imports block, near line 64):

```python
def sanitize_sequence_label(label):
    """Collapse whitespace/underscore runs to single underscores (None-safe)."""
    if not label:
        return label
    return re.sub(r"[\s_]+", "_", label)
```

- [ ] **Step 4: Apply it in `_prep_sequence_meta`**

In `_prep_sequence_meta` (starts ~line 1742), append one line at the end of the method body (after the codehash block):

```python
            sequence.sequence_funcname = self.sequence_lib[sequence.sequence_name].__name__
        sequence.sequence_label = sanitize_sequence_label(sequence.sequence_label)
```

(The new line is dedented one level so it runs unconditionally, not only inside the `if`.)

- [ ] **Step 5: Apply it per sub-sequence in `add_split_sequences`**

In `add_split_sequences` (~line 1820), right after `sub_sequence = deepcopy(sequence)` (line 1820), add:

```python
                    sub_sequence = deepcopy(sequence)
                    sub_sequence.sequence_label = sanitize_sequence_label(
                        sub_sequence.sequence_label
                    )
```

(The `else` branch of `add_split_sequences` delegates to `add_sequence`, which already sanitizes via `_prep_sequence_meta`.)

- [ ] **Step 6: Run tests to verify they pass**

Run the module suite command.
Expected: ends with `ALL STANDALONE_OPERATOR TESTS PASS` (now includes the two new tests).

- [ ] **Step 7: Commit**

```bash
git add helao/core/servers/orch.py helao/core/tests/test_standalone_operator.py
git commit -m "feat(orch): sanitize sequence labels on enqueue"
```

---

### Task 2: D — `move_sequence` / `remove_sequence` on Orch

**Files:**
- Modify: `helao/core/servers/orch.py` (add three methods after `prepend_sequences`, ~line 1868)
- Test: `helao/core/tests/test_standalone_operator.py`

- [ ] **Step 1: Write the failing test**

Add above `run_all()`:

```python
def test_orch_move_and_remove_sequence():
    from helao.core.servers.orch import Orch
    from helao.helpers.premodels import Sequence
    from helao.helpers.zdeque import zdeque

    orch = Orch.__new__(Orch)
    orch.sequence_dq = zdeque(
        [Sequence(sequence_name=n) for n in ("A", "B", "C")]
    )

    asyncio.run(orch.move_sequence(2, 0))
    assert [s.sequence_name for s in orch.sequence_dq] == ["C", "A", "B"]

    asyncio.run(orch.remove_sequence(0))
    assert [s.sequence_name for s in orch.sequence_dq] == ["A", "B"]
    assert len(orch.sequence_dq) == 2

    # out-of-range is a no-op
    asyncio.run(orch.move_sequence(5, 0))
    asyncio.run(orch.remove_sequence(9))
    assert [s.sequence_name for s in orch.sequence_dq] == ["A", "B"]
    print("test_orch_move_and_remove_sequence PASS")
```

Register it in `run_all()` after `test_orch_move_and_remove_sequence`'s logical neighbor (add the call right after `test_orch_add_sequence_sanitizes_label()`).

- [ ] **Step 2: Run test to verify it fails**

Run the module suite command.
Expected: FAIL with `AttributeError: 'Orch' object has no attribute 'move_sequence'`.

- [ ] **Step 3: Implement the three methods**

In `helao/core/servers/orch.py`, immediately after `prepend_sequences` ends (after line 1868, before `async def add_experiment`), add:

```python
    def _rebuild_sequence_dq(self, seqs) -> None:
        """Replace the sequence deque contents with ``seqs`` (re-compresses each)."""
        self.sequence_dq.clear()
        for s in seqs:
            self.sequence_dq.append(s)

    async def move_sequence(self, from_idx: int, to_idx: int) -> None:
        """Move the queued sequence at ``from_idx`` to ``to_idx`` (no-op if out of range)."""
        seqs = list(self.sequence_dq)
        n = len(seqs)
        if 0 <= from_idx < n and 0 <= to_idx < n:
            seq = seqs.pop(from_idx)
            seqs.insert(to_idx, seq)
            self._rebuild_sequence_dq(seqs)

    async def remove_sequence(self, idx: int) -> None:
        """Remove the queued sequence at ``idx`` (no-op if out of range)."""
        seqs = list(self.sequence_dq)
        if 0 <= idx < len(seqs):
            seqs.pop(idx)
            self._rebuild_sequence_dq(seqs)
```

- [ ] **Step 4: Run test to verify it passes**

Run the module suite command.
Expected: ends with `ALL STANDALONE_OPERATOR TESTS PASS`.

- [ ] **Step 5: Commit**

```bash
git add helao/core/servers/orch.py helao/core/tests/test_standalone_operator.py
git commit -m "feat(orch): add move_sequence/remove_sequence queue mutation"
```

---

### Task 3: D — backend `move_sequence` / `remove_sequence`

**Files:**
- Modify: `helao/core/servers/operator/orch_backend.py` (ABC ~line 71, `LocalBackend` ~line 198, `RemoteBackend` ~line 344)
- Test: `helao/core/tests/test_standalone_operator.py`

- [ ] **Step 1: Write the failing tests**

Add above `run_all()`:

```python
def test_local_backend_move_remove():
    from helao.core.servers.operator.orch_backend import LocalBackend

    class _O(_FakeOrch):
        sequence_lib = {}
        experiment_lib = {}
        def __init__(self):
            super().__init__()
            self.calls = []
        async def move_sequence(self, from_idx, to_idx):
            self.calls.append(("move", from_idx, to_idx))
        async def remove_sequence(self, idx):
            self.calls.append(("remove", idx))

    orch = _O()
    be = LocalBackend(orch)
    asyncio.run(be.move_sequence(2, 0))
    asyncio.run(be.remove_sequence(1))
    assert orch.calls == [("move", 2, 0), ("remove", 1)]
    print("test_local_backend_move_remove PASS")


def test_remote_backend_move_remove():
    from helao.core.servers.operator.orch_backend import RemoteBackend
    from helao.core.error import ErrorCodes

    calls = []

    async def fake_dispatch(server_key, host, port, endpoint, params_dict=None, json_dict=None, **kw):
        calls.append((endpoint, params_dict))
        return {"n_sequences": 0}, ErrorCodes.none

    be = RemoteBackend.__new__(RemoteBackend)
    be.orch_key = "ORCH"
    be.host = "127.0.0.1"
    be.port = 8001
    be._dispatch = fake_dispatch

    asyncio.run(be.move_sequence(2, 0))
    asyncio.run(be.remove_sequence(1))
    assert calls[0] == ("move_sequence", {"from_idx": 2, "to_idx": 0})
    assert calls[1] == ("remove_sequence", {"idx": 1})
    print("test_remote_backend_move_remove PASS")
```

Register both in `run_all()` right after `test_remote_backend_prepend()`.

- [ ] **Step 2: Run tests to verify they fail**

Run the module suite command.
Expected: FAIL — `TypeError: Can't instantiate abstract class ... move_sequence` (when `LocalBackend(orch)` is constructed against the updated ABC) OR `AttributeError`. Either way, the new tests fail.

- [ ] **Step 3: Add the abstract methods to `OrchBackend`**

In `orch_backend.py`, after the `prepend_sequences` abstractmethod (line 71), add:

```python
    @abstractmethod
    async def prepend_sequences(self, sequences: list) -> object: ...

    @abstractmethod
    async def move_sequence(self, from_idx: int, to_idx: int) -> None: ...

    @abstractmethod
    async def remove_sequence(self, idx: int) -> None: ...
```

- [ ] **Step 4: Implement on `LocalBackend`**

After `LocalBackend.prepend_sequences` (line 198), add:

```python
    async def move_sequence(self, from_idx, to_idx):
        await self.orch.move_sequence(from_idx, to_idx)

    async def remove_sequence(self, idx):
        await self.orch.remove_sequence(idx)
```

- [ ] **Step 5: Implement on `RemoteBackend`**

After `RemoteBackend.prepend_sequences` (line 344), add:

```python
    async def move_sequence(self, from_idx, to_idx):
        await self._call(
            "move_sequence", params_dict={"from_idx": from_idx, "to_idx": to_idx}
        )

    async def remove_sequence(self, idx):
        await self._call("remove_sequence", params_dict={"idx": idx})
```

- [ ] **Step 6: Run tests to verify they pass**

Run the module suite command.
Expected: ends with `ALL STANDALONE_OPERATOR TESTS PASS`.

- [ ] **Step 7: Commit**

```bash
git add helao/core/servers/operator/orch_backend.py helao/core/tests/test_standalone_operator.py
git commit -m "feat(backend): add move_sequence/remove_sequence to OrchBackend"
```

---

### Task 4: D — OrchAPI `/move_sequence` and `/remove_sequence` endpoints

**Files:**
- Modify: `helao/core/servers/orch_api.py` (add two endpoints after `/prepend_sequences`, ~line 394)

There is no Linux test for the live FastAPI routes (they need a running orch). This task is a faithful mirror of the existing `/append_sequence` / `/prepend_sequences` routes; verify by import + signature check.

- [ ] **Step 1: Add the endpoints**

In `orch_api.py`, immediately after the `/prepend_sequences` endpoint block (ends at line 394, the `return {"sequence_uuids": uuids}`), add:

```python
        @self.post("/move_sequence", tags=["private"])
        async def move_sequence(from_idx: int, to_idx: int):
            """Move a queued sequence from one index to another."""
            await self.orch.move_sequence(from_idx, to_idx)
            return {"n_sequences": len(self.orch.sequence_dq)}

        @self.post("/remove_sequence", tags=["private"])
        async def remove_sequence(idx: int):
            """Remove a queued sequence by index."""
            await self.orch.remove_sequence(idx)
            return {"n_sequences": len(self.orch.sequence_dq)}
```

(`from_idx`/`to_idx`/`idx` are scalar query params, matching how `RemoteBackend` sends them via `params_dict` — same pattern as the existing `/set_step_flag` route.)

- [ ] **Step 2: Verify the module imports cleanly**

Run: `conda run -n helao python -c "import helao.core.servers.orch_api as m; print('ok')"`
Expected: prints `ok` with no traceback.

- [ ] **Step 3: Run the module suite (regression check)**

Run the module suite command.
Expected: ends with `ALL STANDALONE_OPERATOR TESTS PASS`.

- [ ] **Step 4: Commit**

```bash
git add helao/core/servers/orch_api.py
git commit -m "feat(orch-api): expose /move_sequence and /remove_sequence"
```

---

### Task 5: E — UUID truncation in queue tables

**Files:**
- Modify: `helao/core/servers/operator/bokeh_operator.py` (`get_sequences` ~1134, `get_experiments` ~1141, `get_actions` ~1148)
- Modify: `helao/core/tests/test_standalone_operator.py` (extend `_MockBackend` list methods to return long uuids; add a test)

- [ ] **Step 1: Make the mock return long uuids and write the failing test**

In `test_standalone_operator.py`, change `_MockBackend.list_sequences`/`list_experiments`/`list_actions` (lines 240-248) to return long uuid values:

```python
    async def list_sequences(self):
        return [{"sequence_name": "seq0", "sequence_label": "l",
                 "sequence_uuid": "0123456789abcdef", "campaign_name": "c",
                 "campaign_uuid": "fedcba9876543210"}]

    async def list_experiments(self):
        return [{"experiment_name": "exp0", "experiment_uuid": "1111222233334444"}]

    async def list_actions(self):
        return [{"action_name": "noop", "action_server": "motor",
                 "action_uuid": "aaaabbbbccccdddd"}]
```

Add above `run_all()`:

```python
def test_uuid_truncation_in_queue_tables():
    from bokeh.document import Document
    from helao.core.servers.operator.bokeh_operator import BokehOperator

    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    asyncio.run(op.get_sequences())
    asyncio.run(op.get_experiments())
    asyncio.run(op.get_actions())
    assert op.sequence_source.data["sequence_uuid"] == ["89abcdef"]
    assert op.sequence_source.data["campaign_uuid"] == ["76543210"]
    assert op.sequence_source.data["sequence_name"] == ["seq0"]  # non-uuid untouched
    assert op.experiment_source.data["experiment_uuid"] == ["33334444"]
    assert op.action_source.data["action_uuid"] == ["ccccdddd"]
    op.cleanup_session(None)
    print("test_uuid_truncation_in_queue_tables PASS")
```

Register it in `run_all()` after `test_operator_tables_from_backend()`.

- [ ] **Step 2: Run tests to verify the new one fails**

Run the module suite command.
Expected: FAIL on `test_uuid_truncation_in_queue_tables` — `assert [...'0123456789abcdef'] == ['89abcdef']`.

- [ ] **Step 3: Truncate `*_uuid` columns in the three getters**

In `bokeh_operator.py`, replace `get_sequences` (lines 1134-1139):

```python
    async def get_sequences(self):
        """Refresh the queued-sequences table from the backend."""
        rows = await self.backend.list_sequences()
        for key in self.sequence_lists:
            vals = [r.get(key) for r in rows]
            if key.endswith("_uuid"):
                vals = [str(v)[-8:] if v else v for v in vals]
            self.sequence_lists[key] = vals
        self.sequence_source.data = self.sequence_lists
```

Replace `get_experiments` (lines 1141-1146):

```python
    async def get_experiments(self):
        """Refresh the queued-experiments table from the backend."""
        rows = await self.backend.list_experiments()
        for key in self.experiment_lists:
            vals = [r.get(key) for r in rows]
            if key.endswith("_uuid"):
                vals = [str(v)[-8:] if v else v for v in vals]
            self.experiment_lists[key] = vals
        self.experiment_source.data = self.experiment_lists
```

Replace `get_actions` (lines 1148-1153):

```python
    async def get_actions(self):
        """Refresh the queued-actions table from the backend."""
        rows = await self.backend.list_actions()
        for key in self.action_lists:
            vals = [r.get(key) for r in rows]
            if key.endswith("_uuid"):
                vals = [str(v)[-8:] if v else v for v in vals]
            self.action_lists[key] = vals
        self.action_source.data = self.action_lists
```

- [ ] **Step 4: Run tests to verify they pass**

Run the module suite command.
Expected: ends with `ALL STANDALONE_OPERATOR TESTS PASS`.

- [ ] **Step 5: Commit**

```bash
git add helao/core/servers/operator/bokeh_operator.py helao/core/tests/test_standalone_operator.py
git commit -m "feat(operator): truncate uuid columns in queue tables"
```

---

### Task 6: A — merged name + italic-type label via `.name` decoupling

**Files:**
- Modify: `helao/core/servers/operator/bokeh_operator.py` — `add_dynamic_inputs` (~1701-1887), `callback_enqueue_seqspec` (1256), `callback_to_seqtab` (1286, 1300-1301), `populate_sequence` (1543), `populate_experimentmodel` (1575), `update_xysamples` (1912/1914), `find_input` (2012)
- Test: `helao/core/tests/test_standalone_operator.py`

**Decoupling rule (resolves a literal-text inconsistency in the spec):** every parameter widget created in the main `add_dynamic_inputs` loop (the `TextInput`, and the `solid_custom_position`/`liquid_custom_position` `Select`s) carries its param key in `.name = args[idx]`. `x_mm`/`y_mm`/`solid_sample_no` are real params and go through this uniform path (they get the merged label like any other param). The only widgets that keep a visible `title` AND get an explicit `.name` are the private display inputs `elements`/`code`/`composition` (so `find_input(private, "elements")` keeps working). This is internally consistent: `.name` is the lookup/key everywhere, `.title` is display-only.

- [ ] **Step 1: Write the failing tests**

Add above `run_all()`:

```python
def test_param_key_uses_name_not_title():
    from bokeh.document import Document
    from helao.core.servers.operator.bokeh_operator import BokehOperator

    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    op.sequence_dropdown.value = "seq0"  # already selected in __init__; param is "x"
    # the param input should carry its key on .name, with no visible title
    inp = op.seq_param_input[0]
    assert inp.title is None
    assert inp.name == "x"
    op.populate_sequence(prepend=False)
    assert "x" in op.plan[0].sequence_params  # keyed by .name, not .title
    op.cleanup_session(None)
    print("test_param_key_uses_name_not_title PASS")


def test_find_input_matches_name():
    from bokeh.document import Document
    from bokeh.models.widgets.inputs import TextInput
    from helao.core.servers.operator.bokeh_operator import BokehOperator

    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    probe = TextInput(value="", title=None, name="solid_sample_no")
    assert op.find_input([probe], "solid_sample_no") is probe
    assert op.find_input([probe], "missing") is None
    op.cleanup_session(None)
    print("test_find_input_matches_name PASS")
```

Register both in `run_all()` after `test_plate_api_disabled_by_default()`.

- [ ] **Step 2: Run tests to verify they fail**

Run the module suite command.
Expected: FAIL on `test_param_key_uses_name_not_title` — `assert <title 'x'> is None`.

- [ ] **Step 3: Change the main `TextInput` construction + cell layout**

In `add_dynamic_inputs`, replace the `TextInput(...)` construction (lines 1708-1715) so the key moves to `name` and `title` is dropped:

```python
            text_input = TextInput(
                value=def_val,
                title=None,
                name=args[idx],
                disabled=True if args[idx].endswith("_version") else False,
                width=400,
                height=40,
                stylesheets=initial_stylesheet,
            )
```

Replace the `param_layout.append(...)` cell (lines 1731-1749) so the merged label `Div` sits **above** the input and the old separate type `Div` is removed:

```python
            param_layout.append(
                layout(
                    [
                        [
                            Div(
                                text=f"{args[idx]} <i>[{str(argtypes[idx]).split()[-1].strip(chr(39) + '<>]').split('.')[-1].replace('[', ' of ')}]</i>",
                                width=self.max_width - 40,
                                height=18,
                            ),
                        ],
                        [param_input[item]],
                        Spacer(height=10),
                    ],
                    background=self.color_sq_param_inputs,
                    width=self.max_width,
                )
            )
```

(`chr(39)` is a single quote; it avoids a nested-quote clash inside the f-string's `.strip(...)`. The type expression is the same one used previously, just inlined into the label text.)

- [ ] **Step 4: Set `.name` on the Select widgets and private display inputs**

For `solid_custom_position` (lines 1831-1834) change the `Select(...)` to add `name`:

```python
            elif args[idx] == "solid_custom_position":
                param_input[-1] = Select(
                    title=args[idx], value=None, options=self.dev_customitems,
                    name=args[idx],
                )
```

For `liquid_custom_position` (lines 1849-1852) likewise:

```python
            elif args[idx] == "liquid_custom_position":
                param_input[-1] = Select(
                    title=args[idx], value=None, options=self.dev_customitems,
                    name=args[idx],
                )
```

For the private display inputs in the `solid_plate_id` branch (lines 1789-1807) add `name=` matching each title:

```python
                private_input.append(
                    TextInput(
                        value="", title="elements", name="elements",
                        disabled=True, width=120, height=40
                    )
                )
                private_input.append(
                    TextInput(
                        value="", title="code", name="code",
                        disabled=True, width=60, height=40
                    )
                )
                private_input.append(
                    TextInput(
                        value="",
                        title="composition",
                        name="composition",
                        disabled=True,
                        width=220,
                        height=40,
                    )
                )
```

- [ ] **Step 5: Switch the param-key sites from `.title` to `.name`**

`callback_enqueue_seqspec` (line 1256):

```python
            paraminput.name: parse_bokeh_input(paraminput.value)
```

`callback_to_seqtab` params dict (line 1286):

```python
            paraminput.name: parse_bokeh_input(paraminput.value)
```

`callback_to_seqtab` loaded-params match (lines 1300-1301):

```python
        for i, x in enumerate(self.seq_param_input):
            if x.name in loaded_params:
                self.seq_param_input[i].value = str(loaded_params[x.name])
```

`populate_sequence` (line 1543):

```python
            paraminput.name: (
```

`populate_experimentmodel` (line 1575):

```python
            paraminput.name: (
```

`update_xysamples` (lines 1912 and 1914):

```python
            if paraminput.name == "x_mm":
                paraminput.value = xval
            if paraminput.name == "y_mm":
                paraminput.value = yval
```

`find_input` (line 2012) — update the body and docstring:

```python
    def find_input(self, inputs, name):
        """Return the ``TextInput`` in ``inputs`` whose ``name`` equals ``name``, or ``None``."""
        for inp in inputs:
            if isinstance(inp, TextInput):
                if inp.name == name:
                    return inp
        return None
```

- [ ] **Step 6: Run tests to verify they pass**

Run the module suite command.
Expected: ends with `ALL STANDALONE_OPERATOR TESTS PASS`.

- [ ] **Step 7: Commit**

```bash
git add helao/core/servers/operator/bokeh_operator.py helao/core/tests/test_standalone_operator.py
git commit -m "feat(operator): merge param name and italic type hint into one label"
```

> **HTE smoke-check note (carry into the final review):** the `solid_plate_id`/`solid_sample_no`/`x_mm`/`y_mm`/custom-position branches run only when `dataAPI` is configured (HTE), which the Linux tests do not exercise. The `.title`→`.name` substitution is faithful (same identifier strings), but flag an HTE smoke test before this lands in production.

---

### Task 7: B — operator-side label sanitization callback

**Files:**
- Modify: `helao/core/servers/operator/bokeh_operator.py` (add `import re` near line 27; add `_sanitize_label_callback`; wire it on `input_sequence_label`/`input_sequence_label2` near line 514)
- Test: `helao/core/tests/test_standalone_operator.py`

- [ ] **Step 1: Write the failing test**

Add above `run_all()`:

```python
def test_operator_label_sanitize_callback():
    from bokeh.document import Document
    from helao.core.servers.operator.bokeh_operator import BokehOperator

    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    # call the handler directly with a dirty value
    op._sanitize_label_callback(op.input_sequence_label, "value", "nolabel", "a b__c")
    # the callback schedules the cleaned value on the doc; run queued callbacks
    op.vis.doc.unhold()
    while op.vis.doc.session_callbacks:
        cb = op.vis.doc.session_callbacks[0]
        cb.callback()
        op.vis.doc.remove_next_tick_callback(cb)
    assert op.input_sequence_label.value == "a_b_c"
    op.cleanup_session(None)
    print("test_operator_label_sanitize_callback PASS")
```

> Note for the implementer: if draining `session_callbacks` is awkward with the installed Bokeh version, assert on the value the callback *computes* instead by having `_sanitize_label_callback` delegate to a tiny pure helper and testing that helper directly (e.g. `assert op._clean_label("a b__c") == "a_b_c"`). Keep whichever is simplest; both prove the sanitizer fires. The pure-helper form is the safer default — see Step 3.

- [ ] **Step 2: Run test to verify it fails**

Run the module suite command.
Expected: FAIL with `AttributeError: 'BokehOperator' object has no attribute '_sanitize_label_callback'`.

- [ ] **Step 3: Add `import re` and the callback**

In `bokeh_operator.py`, add `import re` with the stdlib imports (after `import builtins` on line 27, or near `import json`):

```python
import re
```

Add these methods near `_make_copy_callback` (after line 837):

```python
    def _clean_label(self, value):
        """Collapse whitespace/underscore runs to single underscores (None-safe)."""
        if not value:
            return value
        return re.sub(r"[\s_]+", "_", value)

    def _sanitize_label_callback(self, sender, attr, old, new):
        """Rewrite a label input's value to its sanitized form when they differ."""
        cleaned = self._clean_label(new)
        if cleaned != new:
            self.vis.doc.add_next_tick_callback(
                partial(self.update_input_value, sender, cleaned)
            )
```

If the test in Step 1 uses the pure-helper form, it calls `op._clean_label(...)`; the `_sanitize_label_callback` form (used for real wiring) is still added here.

- [ ] **Step 4: Wire the callback onto both label inputs**

In `__init__`, just after the existing label mirror callbacks (after line 514, the `input_sequence_label2.on_change(...)` block), add:

```python
        self.input_sequence_label.on_change(
            "value",
            partial(self._sanitize_label_callback, self.input_sequence_label),
        )
        self.input_sequence_label2.on_change(
            "value",
            partial(self._sanitize_label_callback, self.input_sequence_label2),
        )
```

(`_sanitize_label_callback`'s signature is `(sender, attr, old, new)`; `partial` binds `sender`, and Bokeh supplies `attr, old, new`. Sanitization is idempotent, so the re-fired `on_change` from the corrected value cleans to itself and terminates.)

- [ ] **Step 5: Run test to verify it passes**

Run the module suite command.
Expected: ends with `ALL STANDALONE_OPERATOR TESTS PASS`.

- [ ] **Step 6: Commit**

```bash
git add helao/core/servers/operator/bokeh_operator.py helao/core/tests/test_standalone_operator.py
git commit -m "feat(operator): sanitize sequence label field on edit"
```

---

### Task 8: C — save/restore global last-used label & campaign

**Files:**
- Modify: `helao/core/servers/operator/bokeh_operator.py` (`write_params` ~1506, `read_params` ~1524, `get_last_seq_pars` ~2166, `get_last_exp_pars` ~2175)
- Test: `helao/core/tests/test_standalone_operator.py`

- [ ] **Step 1: Write the failing test**

Add above `run_all()`:

```python
def test_save_restore_label_campaign():
    from bokeh.document import Document
    from helao.core.servers.operator.bokeh_operator import BokehOperator

    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    op.save_last_seq_pars.active = [0]  # save enabled
    op.input_sequence_label.value = "runA"
    op.input_campaign_name.value = "camp1"
    op.input_campaign_uuid.value = "uuid-1"
    op.write_params("seq", "seq0", {"x": 1})

    # clear the live fields, then restore from disk
    op.input_sequence_label.value = "x"
    op.input_campaign_name.value = ""
    op.input_campaign_uuid.value = ""
    op.sequence_dropdown.value = "seq0"
    op.get_last_seq_pars()
    op.vis.doc.unhold()
    while op.vis.doc.session_callbacks:
        cb = op.vis.doc.session_callbacks[0]
        cb.callback()
        op.vis.doc.remove_next_tick_callback(cb)
    assert op.input_sequence_label.value == "runA"
    assert op.input_campaign_name.value == "camp1"
    assert op.input_campaign_uuid.value == "uuid-1"
    op.cleanup_session(None)
    print("test_save_restore_label_campaign PASS")
```

> Implementer note: same callback-draining caveat as Task 7. If draining is fiddly, split `get_last_seq_pars` so the restore values are computed by a testable helper (e.g. `_read_last_meta()` returning the dict) and assert on that dict directly, while keeping the `add_next_tick_callback` wiring for the live UI.

Register it in `run_all()` after `test_operator_label_sanitize_callback()`.

- [ ] **Step 2: Run test to verify it fails**

Run the module suite command.
Expected: FAIL — restored label stays `"x"` (no `last_meta` written/read yet).

- [ ] **Step 3: Persist `last_meta` in `write_params`**

Replace `write_params` (lines 1506-1522) so the default dict carries `last_meta` and the save branch records it:

```python
    def write_params(self, ptype: str, name: str, pars: dict):
        """Persist the most recent sequence/experiment parameters to ``previous_params.json``."""
        param_file_path = os.path.join(
            self.vis.world_cfg["root"], "STATES", "previous_params.json"
        )
        if not os.path.exists(param_file_path):
            os.makedirs(os.path.dirname(param_file_path), exist_ok=True)
            pdict = {"seq": {}, "exp": {}, "last_meta": {}}
        else:
            with open(param_file_path, "r", encoding="utf8") as f:
                pdict = json.load(f)
        if (ptype == "seq" and self.save_last_seq_pars.active == [0]) or (
            ptype == "exp" and self.save_last_exp_pars.active == [0]
        ):
            pdict[ptype].update({name: pars})
            pdict["last_meta"] = {
                "sequence_label": self.input_sequence_label.value,
                "campaign_name": self.input_campaign_name.value,
                "campaign_uuid": self.input_campaign_uuid.value,
            }
            with open(param_file_path, "w", encoding="utf8") as f:
                json.dump(pdict, f)
```

- [ ] **Step 4: Add a `last_meta` reader**

Update the `read_params` "file missing" default to include `last_meta`, and add a sibling reader. Replace lines 1529-1535:

```python
        if not os.path.exists(param_file_path):
            os.makedirs(os.path.dirname(param_file_path), exist_ok=True)
            pdict = {"seq": {}, "exp": {}, "last_meta": {}}
        else:
            with open(param_file_path, "r", encoding="utf8") as f:
                pdict = json.load(f)
        return pdict.get(ptype, {}).get(name, {})

    def read_last_meta(self) -> dict:
        """Return the saved global label/campaign block, or ``{}`` if none/older file."""
        param_file_path = os.path.join(
            self.vis.world_cfg["root"], "STATES", "previous_params.json"
        )
        if not os.path.exists(param_file_path):
            return {}
        with open(param_file_path, "r", encoding="utf8") as f:
            pdict = json.load(f)
        return pdict.get("last_meta", {})
```

- [ ] **Step 5: Restore label/campaign in `get_last_seq_pars` / `get_last_exp_pars`**

Add a shared restore step. Replace `get_last_seq_pars` (lines 2166-2173) and `get_last_exp_pars` (lines 2175-2182):

```python
    def _restore_last_meta(self):
        """Schedule label/campaign fields to be filled from the saved global meta block."""
        meta = self.read_last_meta()
        field_map = {
            "sequence_label": self.input_sequence_label,
            "campaign_name": self.input_campaign_name,
            "campaign_uuid": self.input_campaign_uuid,
        }
        for key, widget in field_map.items():
            if key in meta and meta[key] is not None:
                self.vis.doc.add_next_tick_callback(
                    partial(self.update_input_value, widget, str(meta[key]))
                )

    def get_last_seq_pars(self):
        """Pre-fill the sequence parameter inputs and label/campaign from saved values."""
        loaded_pars = self.read_params("seq", self.sequence_dropdown.value)
        for k, v in loaded_pars.items():
            seq_input = self.find_input(self.seq_param_input, k)
            self.vis.doc.add_next_tick_callback(
                partial(self.update_input_value, seq_input, str(v))
            )
        self._restore_last_meta()

    def get_last_exp_pars(self):
        """Pre-fill the experiment parameter inputs and label/campaign from saved values."""
        loaded_pars = self.read_params("exp", self.experiment_dropdown.value)
        for k, v in loaded_pars.items():
            exp_input = self.find_input(self.exp_param_input, k)
            self.vis.doc.add_next_tick_callback(
                partial(self.update_input_value, exp_input, str(v))
            )
        self._restore_last_meta()
```

(Setting `input_sequence_label` flows through the mirror + sanitizer wired in Task 7; the sanitizer is idempotent so a clean stored label is unchanged.)

- [ ] **Step 6: Run test to verify it passes**

Run the module suite command.
Expected: ends with `ALL STANDALONE_OPERATOR TESTS PASS`.

- [ ] **Step 7: Commit**

```bash
git add helao/core/servers/operator/bokeh_operator.py helao/core/tests/test_standalone_operator.py
git commit -m "feat(operator): save/restore last-used label and campaign"
```

---

### Task 9: D — plan table one-row-per-sequence + reorder/remove controls

**Files:**
- Modify: `helao/core/servers/operator/bokeh_operator.py` — `experiment_plan_lists` keys (155), plan-table block of `update_tables` (2126-2135, 2161-2162), add six buttons in `__init__` (near 360), add reorder/remove callbacks, add control rows + gate
- Modify: `helao/core/tests/test_standalone_operator.py` — rewrite `test_plan_table_rows`; add reorder/remove + gate tests

- [ ] **Step 1: Rewrite `test_plan_table_rows` and add the new tests**

Replace the existing `test_plan_table_rows` (lines 561-576) with:

```python
def test_plan_table_rows():
    from bokeh.document import Document
    from helao.core.servers.operator.bokeh_operator import BokehOperator
    from helao.helpers.premodels import Sequence, Experiment

    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    manual = Sequence(sequence_name="m")
    manual.sequence_label = "L1"
    manual.planned_experiments = [Experiment(experiment_name="exp0")]
    multi = Sequence(sequence_name="big")
    multi.sequence_label = "L2"
    multi.planned_experiments = [
        Experiment(experiment_name="exp0"),
        Experiment(experiment_name="exp0"),
    ]
    op.plan = [manual, multi]
    asyncio.run(op.update_tables())
    data = op.experiment_plan_source.data
    assert data["sequence_name"] == ["m", "big"]
    assert data["sequence_label"] == ["L1", "L2"]
    assert data["num_experiments"] == [1, 2]
    assert op.button_add_expplan.label == "Add plan [2]"
    op.cleanup_session(None)
    print("test_plan_table_rows PASS")


def test_plan_reorder_and_remove():
    from bokeh.document import Document
    from helao.core.servers.operator.bokeh_operator import BokehOperator
    from helao.helpers.premodels import Sequence

    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    op.plan = [Sequence(sequence_name=n) for n in ("A", "B", "C")]
    op.experiment_plan_source.selected.indices = [2]
    op.callback_plan_move_up(None)
    assert [s.sequence_name for s in op.plan] == ["A", "C", "B"]

    op.experiment_plan_source.selected.indices = [0]
    op.callback_plan_move_down(None)
    assert [s.sequence_name for s in op.plan] == ["C", "A", "B"]

    op.experiment_plan_source.selected.indices = [1]
    op.callback_plan_remove(None)
    assert [s.sequence_name for s in op.plan] == ["C", "B"]
    op.cleanup_session(None)
    print("test_plan_reorder_and_remove PASS")


def test_queue_controls_enable_gate():
    from bokeh.document import Document
    from helao.core.servers.operator.bokeh_operator import BokehOperator

    be = _MockBackend()
    op = BokehOperator(_FakeVisOp(Document()), be)

    be.loop_state = "started"
    asyncio.run(op.update_tables())
    assert op.button_seq_move_up.disabled is True
    assert op.button_seq_move_down.disabled is True
    assert op.button_seq_remove.disabled is True

    be.loop_state = "stopped"
    asyncio.run(op.update_tables())
    assert op.button_seq_move_up.disabled is False
    assert op.button_seq_move_down.disabled is False
    assert op.button_seq_remove.disabled is False
    op.cleanup_session(None)
    print("test_queue_controls_enable_gate PASS")
```

Register `test_plan_reorder_and_remove` and `test_queue_controls_enable_gate` in `run_all()` right after `test_plan_table_rows()`.

- [ ] **Step 2: Run tests to verify they fail**

Run the module suite command.
Expected: FAIL on `test_plan_table_rows` — `KeyError: 'num_experiments'` (the source still has `experiment_name`).

- [ ] **Step 3: Change the plan-table column keys**

In `__init__`, replace `experiment_plan_lists` (lines 154-156):

```python
        self.experiment_plan_lists = {
            k: [] for k in ["sequence_name", "sequence_label", "num_experiments"]
        }
```

- [ ] **Step 4: Build one row per sequence in `update_tables`**

Replace the plan-table block of `update_tables` (lines 2126-2135):

```python
        for key in self.experiment_plan_lists:
            self.experiment_plan_lists[key] = []
        for seq in self.plan:
            self.experiment_plan_lists["sequence_name"].append(seq.sequence_name)
            self.experiment_plan_lists["sequence_label"].append(seq.sequence_label)
            self.experiment_plan_lists["num_experiments"].append(
                len(seq.planned_experiments)
            )
        self.experiment_plan_source.data = self.experiment_plan_lists
```

Then replace the `seq_count`/gate/label lines (2161-2162) — note `seq_count` no longer exists:

```python
        self.button_prepend_plan.disabled = loop_state != LoopStatus.stopped.value
        queue_disabled = loop_state != LoopStatus.stopped.value
        self.button_seq_move_up.disabled = queue_disabled
        self.button_seq_move_down.disabled = queue_disabled
        self.button_seq_remove.disabled = queue_disabled
        self.button_add_expplan.label = f"Add plan [{len(self.plan)}]"
```

- [ ] **Step 5: Add the six control buttons in `__init__`**

After `button_prepend_plan` is created (after line 360), add:

```python
        self.button_plan_move_up = self._make_button(
            "Plan ↑", "default", 70, self.callback_plan_move_up
        )
        self.button_plan_move_down = self._make_button(
            "Plan ↓", "default", 70, self.callback_plan_move_down
        )
        self.button_plan_remove = self._make_button(
            "Plan ✕", "default", 70, self.callback_plan_remove
        )
        self.button_seq_move_up = self._make_button(
            "Queue ↑", "default", 70, self.callback_seq_move_up
        )
        self.button_seq_move_down = self._make_button(
            "Queue ↓", "default", 70, self.callback_seq_move_down
        )
        self.button_seq_remove = self._make_button(
            "Queue ✕", "default", 70, self.callback_seq_remove
        )
```

- [ ] **Step 6: Add the plan + queue reorder/remove callbacks**

Add these methods next to the other plan callbacks (after `callback_prepend_plan`, ~line 1413):

```python
    def _selected_plan_idx(self):
        """Return the first selected plan-table row index, or ``None``."""
        idxs = list(self.experiment_plan_source.selected.indices)
        return idxs[0] if idxs else None

    def callback_plan_move_up(self, event):
        """Move the selected buffered sequence one row up."""
        i = self._selected_plan_idx()
        if i is not None and i > 0:
            self.plan[i - 1], self.plan[i] = self.plan[i], self.plan[i - 1]
            self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_plan_move_down(self, event):
        """Move the selected buffered sequence one row down."""
        i = self._selected_plan_idx()
        if i is not None and i < len(self.plan) - 1:
            self.plan[i + 1], self.plan[i] = self.plan[i], self.plan[i + 1]
            self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_plan_remove(self, event):
        """Remove the selected buffered sequence from the plan."""
        i = self._selected_plan_idx()
        if i is not None and 0 <= i < len(self.plan):
            del self.plan[i]
            self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_seq_move_up(self, event):
        """Move the selected queued sequence one position toward the front."""
        idxs = list(self.sequence_source.selected.indices)
        if idxs and idxs[0] > 0:
            i = idxs[0]
            self.vis.doc.add_next_tick_callback(
                partial(self.backend.move_sequence, i, i - 1)
            )
            self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_seq_move_down(self, event):
        """Move the selected queued sequence one position toward the back."""
        idxs = list(self.sequence_source.selected.indices)
        n = len(self.sequence_source.data.get("sequence_name", []))
        if idxs and idxs[0] < n - 1:
            i = idxs[0]
            self.vis.doc.add_next_tick_callback(
                partial(self.backend.move_sequence, i, i + 1)
            )
            self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_seq_remove(self, event):
        """Remove the selected queued sequence from the orch queue."""
        idxs = list(self.sequence_source.selected.indices)
        if idxs:
            i = idxs[0]
            self.vis.doc.add_next_tick_callback(
                partial(self.backend.remove_sequence, i)
            )
            self.vis.doc.add_next_tick_callback(partial(self.update_tables))
```

- [ ] **Step 7: Add the control rows to the layout**

In `layout4`, insert a plan-control row right after `[self.planhistory_tabs],` (line 685) and a queue-control row right after `[self.queue_tabs],` (line 693):

```python
                        [self.planhistory_tabs],
                        [
                            self.button_plan_move_up,
                            Spacer(width=5),
                            self.button_plan_move_down,
                            Spacer(width=5),
                            self.button_plan_remove,
                        ],
                        [
                            Div(
                                text="<b>Queues:</b>",
                                width=200 + 50,
                                height=15,
                            ),
                        ],
                        [self.queue_tabs],
                        [
                            self.button_seq_move_up,
                            Spacer(width=5),
                            self.button_seq_move_down,
                            Spacer(width=5),
                            self.button_seq_remove,
                        ],
```

- [ ] **Step 8: Run tests to verify they pass**

Run the module suite command.
Expected: ends with `ALL STANDALONE_OPERATOR TESTS PASS`.

- [ ] **Step 9: Run the full unit-test suite**

Run: `conda run -n helao python run_unit_tests.py`
Expected: passes (it runs the sample-model unit test; confirm no import errors surface from the edited modules).

- [ ] **Step 10: Commit**

```bash
git add helao/core/servers/operator/bokeh_operator.py helao/core/tests/test_standalone_operator.py
git commit -m "feat(operator): one-row-per-sequence plan table with reorder/remove controls"
```

---

## Self-review

**1. Spec coverage:**
- A (merged label + `.name` decoupling) → Task 6 (covers `add_dynamic_inputs`, all four param-dict sites, `update_xysamples`, `find_input`, `callback_to_seqtab` match). ✓
- B (sanitizer in orch + operator field) → Task 1 (orch) + Task 7 (operator). ✓
- C (save/restore global label+campaign) → Task 8. ✓
- D (orch move/remove, backend, API, plan-table one-row-per-seq, reorder/remove controls, gate) → Tasks 2, 3, 4, 9. ✓
- E (uuid truncation in queue tables) → Task 5. ✓
- Spec test list items 1-12 all map to a written test: 1→T6 `test_param_key_uses_name_not_title`; 2→T6 `test_find_input_matches_name`; 3→T1 `test_sanitize_sequence_label`; 4→T1 `test_orch_add_sequence_sanitizes_label`; 5→T7 `test_operator_label_sanitize_callback`; 6→T8 `test_save_restore_label_campaign`; 7→T9 `test_plan_table_rows`; 8→T9 `test_plan_reorder_and_remove`; 9→T2 `test_orch_move_and_remove_sequence`; 10→T3 `test_local_backend_move_remove`/`test_remote_backend_move_remove`; 11→T9 `test_queue_controls_enable_gate`; 12→T5 `test_uuid_truncation_in_queue_tables`. ✓

**2. Placeholder scan:** No TBD/TODO/"handle edge cases"; every code step shows full code. The two callback-drain "implementer notes" (Tasks 7/8) offer a concrete pure-helper fallback (`_clean_label`, `read_last_meta`/`_restore_last_meta` are real methods this plan defines), not a placeholder.

**3. Type/name consistency:** `move_sequence(from_idx, to_idx)`, `remove_sequence(idx)`, `_rebuild_sequence_dq(seqs)` consistent across orch/backend/API. Param key is `.name` at every site after Task 6. Plan-table key `num_experiments` consistent between Task 9 Steps 3/4 and the test. Buttons `button_plan_move_up/down/remove`, `button_seq_move_up/down/remove` named identically in `__init__`, callbacks, gate, and tests. `sanitize_sequence_label` (orch) vs `_clean_label` (operator) are intentionally distinct (module fn vs method) but identical regex.

**One resolved spec inconsistency (documented in Task 6):** the spec text lists `x_mm`/`y_mm`/`solid_sample_no` under both "give every param `title=None`+`name`" and "keep their visible title". This plan treats them uniformly as params (merged label, key on `.name`) and applies the keep-title rule only to the genuinely private display inputs `elements`/`code`/`composition`. This is the only internally consistent reading and preserves every load-bearing lookup. Flagged for the spec reviewer.
