# Plan Buffer of Separate Sequences Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Bokeh operator "plan" from a single merged custom `Sequence` into an ordered buffer of independent `Sequence` objects that flush onto the orchestrator queue (append / split / prepend-to-front), with `run_id` stamped at plan-add time.

**Architecture:** `BokehOperator.sequence` (one `Sequence`) becomes `BokehOperator.plan: List[Sequence]`. Appending/prepending a library sequence inserts a whole `Sequence`; appending/prepending an experiment wraps it as a one-experiment "manual" sequence. Per-sequence metadata is captured at insert. Flush iterates the buffer onto the orch via the existing `OrchBackend`; a new `prepend_sequences` path inserts the whole buffer at the front of the orch `sequence_dq`. The orch stamps `Sequence.run_id` as sequences enter the queue (empty/cleared queue → new id; non-empty → reuse in-flight id).

**Tech Stack:** Python 3.12, Bokeh, FastAPI (orch HTTP/RPC), pydantic models (`helao.helpers.premodels.Sequence`/`Experiment`), `helao.helpers.zdeque`. Tests are plain assert-functions (no pytest) run via `python -m helao.core.tests.test_standalone_operator`.

**Test command (used in every task):**
```bash
PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao \
  python -m helao.core.tests.test_standalone_operator
```
Full suite (run once at the end): `conda run -n helao python run_unit_tests.py`

---

## File Structure

- `helao/core/servers/orch.py` — add `_prep_sequence_meta`, `_ensure_run_id`, `_resolve_active_run_id`, `prepend_sequences`; refactor `add_sequence` / `add_split_sequences` run_id stamping; change dequeue run_id attach.
- `helao/core/servers/orch_api.py` — add module-level `_prepend_sequences` helper + `/prepend_sequences` endpoint.
- `helao/core/servers/operator/orch_backend.py` — add `prepend_sequences` to `OrchBackend` ABC, `LocalBackend`, `RemoteBackend`.
- `helao/core/servers/operator/bokeh_operator.py` — `self.plan` buffer, `_capture_metadata`, rewritten insert ops, `_flush_plan`, flush callbacks, new "Prepend plan" button + gate, plan-table rewrite.
- `helao/core/tests/test_standalone_operator.py` — new test functions + `_MockBackend`/`_FakeOrch` extensions; register all new tests in `run_all()`.

Each task leaves the codebase in a working, test-passing state.

---

### Task 1: Orch run_id helpers + refactor add_sequence / add_split_sequences / dequeue

**Files:**
- Modify: `helao/core/servers/orch.py` (`add_sequence` ~1743-1768, `add_split_sequences` ~1770-1835, dequeue attach ~766-768)
- Test: `helao/core/tests/test_standalone_operator.py`

- [ ] **Step 1: Write the failing tests**

Add to `helao/core/tests/test_standalone_operator.py` (after the existing tests, before `run_all`):

```python
def test_orch_run_id_sharing():
    from helao.core.servers.orch import Orch
    from helao.helpers.premodels import Sequence
    from helao.helpers.zdeque import zdeque

    orch = Orch.__new__(Orch)
    orch.sequence_dq = zdeque([])
    orch.active_run_id = None
    orch.sequence_codehash_lib = {}
    orch.sequence_codepath_lib = {}
    orch.sequence_lib = {}

    s1 = Sequence(sequence_name="seq0")
    asyncio.run(orch.add_sequence(s1))
    assert s1.run_id is not None
    r1 = s1.run_id

    s2 = Sequence(sequence_name="seq0")
    asyncio.run(orch.add_sequence(s2))
    assert s2.run_id == r1, "non-empty queue should reuse in-flight run_id"

    # simulate clear_sequences emptying the dq -> next add gets a fresh run_id
    orch.sequence_dq = zdeque([])
    s3 = Sequence(sequence_name="seq0")
    asyncio.run(orch.add_sequence(s3))
    assert s3.run_id != r1, "cleared/empty queue should start a new run_id"
    print("test_orch_run_id_sharing PASS")


def test_orch_resolve_active_run_id():
    from helao.core.servers.orch import Orch
    from helao.helpers.premodels import Sequence
    from helao.helpers.time_utils import gen_uuid

    orch = Orch.__new__(Orch)
    orch.active_run_id = None

    rid = gen_uuid()
    s = Sequence(sequence_name="x")
    s.run_id = rid
    orch._resolve_active_run_id(s)
    assert orch.active_run_id == rid, "active_run_id should follow the sequence"

    s2 = Sequence(sequence_name="y")
    orch._resolve_active_run_id(s2)
    assert s2.run_id == rid, "sequence without run_id inherits active_run_id"
    print("test_orch_resolve_active_run_id PASS")


def test_orch_split_run_id():
    from helao.core.servers.orch import Orch
    from helao.helpers.premodels import Sequence
    from helao.helpers.zdeque import zdeque

    orch = Orch.__new__(Orch)
    orch.sequence_dq = zdeque([])
    orch.active_run_id = None
    orch.sequence_codehash_lib = {}
    orch.sequence_codepath_lib = {}
    orch.sequence_lib = {}
    orch.server_params = {"split_by_seq_params": ["plate_sample_no"]}

    seq = Sequence(sequence_name="seq0")
    seq.sequence_params = {"plate_sample_no": [1, 2, 3]}
    uuids = asyncio.run(orch.add_split_sequences(seq))
    assert len(uuids) == 3, uuids
    run_ids = {s.run_id for s in orch.sequence_dq}
    assert len(run_ids) == 1 and None not in run_ids, run_ids
    print("test_orch_split_run_id PASS")
```

Register them in `run_all()` (add the three calls before the final print).

- [ ] **Step 2: Run tests to verify they fail**

Run the test command above.
Expected: FAIL — `AttributeError: 'Orch' object has no attribute '_resolve_active_run_id'` (and `add_sequence` does not yet set `run_id`, so `test_orch_run_id_sharing` would also fail its assertions).

- [ ] **Step 3: Add the three helper methods**

In `helao/core/servers/orch.py`, add these methods to the `Orch` class (place them just above `add_sequence`, ~line 1742):

```python
    def _prep_sequence_meta(self, sequence: Sequence) -> None:
        """Populate uuid/codehash/codepath/funcname metadata on ``sequence`` in place."""
        if sequence.sequence_uuid is None:
            sequence.sequence_uuid = gen_uuid()
        if (
            sequence.sequence_codehash is None
            and sequence.sequence_name in self.sequence_codehash_lib
        ):
            sequence.sequence_codehash = self.sequence_codehash_lib[sequence.sequence_name]
            sequence.sequence_codepath = self.sequence_codepath_lib[sequence.sequence_name]
            sequence.sequence_funcname = self.sequence_lib[sequence.sequence_name].__name__

    def _ensure_run_id(self) -> UUID:
        """Return the run_id to stamp on a sequence entering the queue.

        Empty/just-cleared queue -> fresh run_id; non-empty -> reuse the
        in-flight ``active_run_id`` (back-to-back sharing).
        """
        if len(self.sequence_dq) == 0:
            self.active_run_id = gen_uuid()
        return self.active_run_id

    def _resolve_active_run_id(self, sequence: Sequence) -> None:
        """At dequeue, sync ``active_run_id`` with the active sequence's run_id."""
        if sequence.run_id is not None:
            self.active_run_id = sequence.run_id
        elif self.active_run_id is not None:
            sequence.run_id = self.active_run_id
```

- [ ] **Step 4: Refactor `add_sequence` to use the helpers**

Replace the body of `add_sequence` (~1743-1768) with:

```python
    async def add_sequence(self, sequence: Sequence) -> UUID:
        """Append ``sequence`` to the sequence deque, populating its metadata and run_id.

        Returns:
            The UUID of the added sequence.
        """
        self._prep_sequence_meta(sequence)
        sequence.run_id = self._ensure_run_id()
        self.sequence_dq.append(sequence)
        return sequence.sequence_uuid
```

(`_ensure_run_id` checks queue emptiness *before* the append, so the first
sequence of a flush gets/keeps the run_id and later ones reuse it.)

- [ ] **Step 5: Refactor `add_split_sequences` run_id stamping**

In `add_split_sequences`, immediately after `if possible_splits:` (~line 1791), capture the batch run_id once:

```python
        if possible_splits:
            run_id = self._ensure_run_id()
            split_key = possible_splits[0]
```

Then inside the sub-sequence build loop, **remove** the lines:

```python
                    if len(self.sequence_dq) == 0:
                        self.active_run_id = gen_uuid()
                    self.sequence_dq.append(sub_sequence)
```

and replace with:

```python
                    sub_sequence.run_id = run_id
                    self.sequence_dq.append(sub_sequence)
```

- [ ] **Step 6: Change the dequeue run_id attach**

In `loop_task_dispatch_sequence` (~line 766-768), replace:

```python
            # attach run_id
            if self.active_run_id is not None:
                self.active_sequence.run_id = self.active_run_id
```

with:

```python
            # attach run_id (derive active_run_id from the dequeued sequence)
            self._resolve_active_run_id(self.active_sequence)
```

- [ ] **Step 7: Run tests to verify they pass**

Run the test command.
Expected: `test_orch_run_id_sharing PASS`, `test_orch_resolve_active_run_id PASS`, `test_orch_split_run_id PASS`, and all previously-passing tests still pass.

- [ ] **Step 8: Commit**

```bash
git add helao/core/servers/orch.py helao/core/tests/test_standalone_operator.py
git commit -m "feat(orch): stamp run_id at plan-add via run_id helpers

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Orch.prepend_sequences

**Files:**
- Modify: `helao/core/servers/orch.py` (add method after `add_split_sequences`)
- Test: `helao/core/tests/test_standalone_operator.py`

- [ ] **Step 1: Write the failing test**

Add to the test file and register in `run_all()`:

```python
def test_orch_prepend_order_and_run_id():
    from helao.core.servers.orch import Orch
    from helao.helpers.premodels import Sequence
    from helao.helpers.zdeque import zdeque

    orch = Orch.__new__(Orch)
    orch.sequence_dq = zdeque([])
    orch.active_run_id = None
    orch.sequence_codehash_lib = {}
    orch.sequence_codepath_lib = {}
    orch.sequence_lib = {}

    existing = Sequence(sequence_name="existing")
    asyncio.run(orch.add_sequence(existing))
    inflight = existing.run_id

    a = Sequence(sequence_name="A")
    b = Sequence(sequence_name="B")
    c = Sequence(sequence_name="C")
    uuids = asyncio.run(orch.prepend_sequences([a, b, c]))
    assert len(uuids) == 3

    names = [s.sequence_name for s in orch.sequence_dq]
    assert names == ["A", "B", "C", "existing"], names
    assert a.run_id == b.run_id == c.run_id == inflight, "prepend reuses in-flight run_id"

    # empty prepend is a no-op and must not mint a stray run_id
    before = orch.active_run_id
    assert asyncio.run(orch.prepend_sequences([])) == []
    assert orch.active_run_id == before
    print("test_orch_prepend_order_and_run_id PASS")
```

- [ ] **Step 2: Run test to verify it fails**

Run the test command.
Expected: FAIL — `AttributeError: 'Orch' object has no attribute 'prepend_sequences'`.

- [ ] **Step 3: Implement `prepend_sequences`**

In `helao/core/servers/orch.py`, add after `add_split_sequences` (~line 1835):

```python
    async def prepend_sequences(self, sequences: List[Sequence]) -> List[UUID]:
        """Insert ``sequences`` at the front of the queue, preserving their order.

        Stamps uuid/codehash/run_id like :meth:`add_sequence`. Reuses the
        in-flight run_id when the queue is non-empty, else mints a fresh one.
        An empty list is a no-op (returns ``[]`` without touching run_id).

        Returns:
            The UUIDs of the prepended sequences, in buffer order.
        """
        if not sequences:
            return []
        run_id = self._ensure_run_id()
        uuids = []
        for i, sequence in enumerate(sequences):
            self._prep_sequence_meta(sequence)
            sequence.run_id = run_id
            self.sequence_dq.insert(i, sequence)
            uuids.append(sequence.sequence_uuid)
        return uuids
```

- [ ] **Step 4: Run test to verify it passes**

Run the test command.
Expected: `test_orch_prepend_order_and_run_id PASS`; all other tests still pass.

- [ ] **Step 5: Commit**

```bash
git add helao/core/servers/orch.py helao/core/tests/test_standalone_operator.py
git commit -m "feat(orch): add prepend_sequences front-insert preserving order

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: OrchAPI /prepend_sequences endpoint

**Files:**
- Modify: `helao/core/servers/orch_api.py` (module helper ~after line 72; endpoint near `/append_sequence` ~376)
- Test: `helao/core/tests/test_standalone_operator.py`

- [ ] **Step 1: Write the failing test**

Add to the test file and register in `run_all()`:

```python
def test_prepend_sequences_helper():
    from helao.core.servers import orch_api

    class _O(_FakeOrch):
        async def prepend_sequences(self, sequences):
            self.prepended = sequences
            return ["u1", "u2"]

    orch = _O()
    uuids = asyncio.run(orch_api._prepend_sequences(orch, [{}, {}]))
    assert uuids == ["u1", "u2"]
    assert len(orch.prepended) == 2
    # dict inputs are coerced to Sequence instances
    from helao.helpers.premodels import Sequence
    assert all(isinstance(s, Sequence) for s in orch.prepended)
    print("test_prepend_sequences_helper PASS")
```

- [ ] **Step 2: Run test to verify it fails**

Run the test command.
Expected: FAIL — `AttributeError: module 'helao.core.servers.orch_api' has no attribute '_prepend_sequences'`.

- [ ] **Step 3: Add the module-level helper**

In `helao/core/servers/orch_api.py`, add after the existing helpers (~line 72, after `_queue_counts`):

```python
async def _prepend_sequences(orch, sequences) -> list:
    """Coerce ``sequences`` to ``Sequence`` instances and prepend them on the orch."""
    seqs = [s if isinstance(s, Sequence) else Sequence(**s) for s in sequences]
    return await orch.prepend_sequences(sequences=seqs)
```

- [ ] **Step 4: Add the endpoint**

In `helao/core/servers/orch_api.py`, add immediately after the `/append_sequence` endpoint (~line 382), inside the same scope as the other `@self.post(...)` route definitions:

```python
        @self.post("/prepend_sequences", tags=["private"])
        async def prepend_sequences(sequences: List[Sequence] = Body([], embed=True)):
            """Prepend a list of sequences to the front of the orch queue."""
            uuids = await _prepend_sequences(self.orch, sequences)
            return {"sequence_uuids": uuids}
```

(`Sequence`, `List`, and `Body` are already imported in this module.)

- [ ] **Step 5: Run test to verify it passes**

Run the test command.
Expected: `test_prepend_sequences_helper PASS`; all other tests still pass.

- [ ] **Step 6: Commit**

```bash
git add helao/core/servers/orch_api.py helao/core/tests/test_standalone_operator.py
git commit -m "feat(orch-api): add /prepend_sequences endpoint

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Backend prepend_sequences (ABC + Local + Remote)

**Files:**
- Modify: `helao/core/servers/operator/orch_backend.py` (ABC ~after line 68; `LocalBackend` ~after 192; `RemoteBackend` ~after 332)
- Test: `helao/core/tests/test_standalone_operator.py`

- [ ] **Step 1: Write the failing tests**

Add to the test file and register in `run_all()`:

```python
def test_local_backend_prepend():
    from helao.core.servers.operator.orch_backend import LocalBackend

    class _O(_FakeOrch):
        sequence_lib = {}
        experiment_lib = {}
        async def prepend_sequences(self, sequences):
            self.prepended = sequences
            return ["u1"]

    orch = _O()
    be = LocalBackend(orch)
    out = asyncio.run(be.prepend_sequences(["s1", "s2"]))
    assert out == ["u1"]
    assert orch.prepended == ["s1", "s2"]
    print("test_local_backend_prepend PASS")


def test_remote_backend_prepend():
    from helao.core.servers.operator.orch_backend import RemoteBackend
    from helao.core.error import ErrorCodes

    calls = []

    async def fake_dispatch(server_key, host, port, endpoint, params_dict=None, json_dict=None, **kw):
        calls.append((endpoint, params_dict, json_dict))
        return {"sequence_uuids": ["u1", "u2"]}, ErrorCodes.none

    class _Seq:
        def __init__(self, name):
            self.name = name
        def model_dump(self):
            return {"sequence_name": self.name}

    be = RemoteBackend.__new__(RemoteBackend)
    be.orch_key = "ORCH"
    be.host = "127.0.0.1"
    be.port = 8001
    be._dispatch = fake_dispatch

    out = asyncio.run(be.prepend_sequences([_Seq("A"), _Seq("B")]))
    assert out == {"sequence_uuids": ["u1", "u2"]}
    ep, _, body = calls[0]
    assert ep == "prepend_sequences"
    assert body == {"sequences": [{"sequence_name": "A"}, {"sequence_name": "B"}]}
    print("test_remote_backend_prepend PASS")
```

- [ ] **Step 2: Run tests to verify they fail**

Run the test command.
Expected: FAIL — `TypeError: Can't instantiate abstract class` / `AttributeError: ... has no attribute 'prepend_sequences'`.

- [ ] **Step 3: Add the abstract method**

In `helao/core/servers/operator/orch_backend.py`, in the `OrchBackend` ABC after `add_split_sequences` (~line 68):

```python
    @abstractmethod
    async def prepend_sequences(self, sequences: list) -> object: ...
```

- [ ] **Step 4: Implement on LocalBackend**

After `LocalBackend.add_split_sequences` (~line 192):

```python
    async def prepend_sequences(self, sequences):
        return await self.orch.prepend_sequences(sequences=sequences)
```

- [ ] **Step 5: Implement on RemoteBackend**

After `RemoteBackend.add_split_sequences` (~line 332):

```python
    async def prepend_sequences(self, sequences):
        return await self._call(
            "prepend_sequences",
            json_dict={"sequences": [s.model_dump() for s in sequences]},
        )
```

- [ ] **Step 6: Run tests to verify they pass**

Run the test command.
Expected: `test_local_backend_prepend PASS`, `test_remote_backend_prepend PASS`; all other tests still pass.

- [ ] **Step 7: Commit**

```bash
git add helao/core/servers/operator/orch_backend.py helao/core/tests/test_standalone_operator.py
git commit -m "feat(operator-backend): add prepend_sequences to Orch backends

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: BokehOperator plan buffer — data model, insert ops, append/split flush, plan table

**Files:**
- Modify: `helao/core/servers/operator/bokeh_operator.py`
  - init (`self.sequence = None` ~153)
  - remove `_apply_sequence_to_orch` (~891-907)
  - `callback_add_expplan` (~1381-1383), `callback_add_split_sequences` (~1385-1387), `callback_clear_expplan` (~1417-1421)
  - `append_experiment` / `prepend_experiment` (~1462-1470)
  - `populate_sequence` (~1503-1547), `populate_experimentmodel` (~1549-1575)
  - `update_tables` plan block (~2110-2152)
- Modify: `helao/core/tests/test_standalone_operator.py` (extend `_MockBackend`; add tests)

- [ ] **Step 1: Extend `_MockBackend` and write the failing tests**

In `helao/core/tests/test_standalone_operator.py`, at the top of `_MockBackend.__init__`-time state add call-tracking and a settable loop_state, and add an annotated experiment so the experiment panel can be built. First add this near the top of the file (after the imports):

```python
from helao.helpers.premodels import Experiment as _ExpModel


def _exp0(experiment: _ExpModel, val: int = 1):
    """Mock experiment library function (Experiment arg is filtered out)."""
    return []
```

Then modify `_MockBackend.__init__` to set `self.experiment_lib = {"exp0": _exp0}` (was `{}`), and add tracking attributes:

```python
        self.experiment_lib = {"exp0": _exp0}
        self.loop_state = "stopped"
        self.added = []
        self.split_added = []
        self.prepended = None
```

Update `_MockBackend.get_orch_state` to use the settable state:

```python
    async def get_orch_state(self):
        return {"loop_state": self.loop_state, "active_sequence": {}, "active_experiment": {},
                "n_sequences": 1, "n_experiments": 1, "n_actions": 1,
                "current_stop_message": ""}
```

Replace `_MockBackend.add_sequence` / `add_split_sequences` and add `prepend_sequences`:

```python
    async def add_sequence(self, sequence):
        self.added.append(sequence)
        return "su"

    async def add_split_sequences(self, sequence):
        self.split_added.append(sequence)
        return ["su"]

    async def prepend_sequences(self, sequences):
        self.prepended = list(sequences)
        return ["su"]
```

Now add the new tests and register them in `run_all()`:

```python
def test_plan_buffer_append_and_wrap():
    from bokeh.document import Document
    from helao.core.servers.operator.bokeh_operator import BokehOperator

    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    op.sequence_dropdown.value = "seq0"
    op.populate_sequence(prepend=False)
    assert len(op.plan) == 1
    assert op.plan[0].sequence_name == "seq0"

    # wrap an experiment as its own manual sequence
    op.update_selector_layout("active", 0, 1)  # build the experiment panel + dropdown
    op.append_experiment()
    assert len(op.plan) == 2
    assert op.plan[1].sequence_name == "manual_orch_seq"
    assert len(op.plan[1].planned_experiments) == 1
    op.cleanup_session(None)
    print("test_plan_buffer_append_and_wrap PASS")


def test_plan_buffer_order():
    from bokeh.document import Document
    from helao.core.servers.operator.bokeh_operator import BokehOperator
    from helao.helpers.premodels import Sequence

    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    op.plan = [Sequence(sequence_name="A")]
    op.sequence_dropdown.value = "seq0"
    # prepend a real sequence, then append another
    op.populate_sequence(prepend=True)   # inserts seq0 at front
    op.plan.append(Sequence(sequence_name="C"))
    names = [s.sequence_name for s in op.plan]
    assert names == ["seq0", "A", "C"], names
    op.cleanup_session(None)
    print("test_plan_buffer_order PASS")


def test_plan_metadata_capture_at_insert():
    from bokeh.document import Document
    from helao.core.servers.operator.bokeh_operator import BokehOperator

    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    op.sequence_dropdown.value = "seq0"
    op.input_sequence_label.value = "first"
    op.populate_sequence(prepend=False)
    op.input_sequence_label.value = "second"
    op.populate_sequence(prepend=False)
    assert op.plan[0].sequence_label == "first"
    assert op.plan[1].sequence_label == "second"
    op.cleanup_session(None)
    print("test_plan_metadata_capture_at_insert PASS")


def test_flush_add_dispatches_per_sequence():
    from bokeh.document import Document
    from helao.core.servers.operator.bokeh_operator import BokehOperator
    from helao.helpers.premodels import Sequence

    be = _MockBackend()
    op = BokehOperator(_FakeVisOp(Document()), be)
    op.plan = [Sequence(sequence_name="A"), Sequence(sequence_name="B")]
    asyncio.run(op._flush_plan(op.plan, be.add_sequence))
    assert [s.sequence_name for s in be.added] == ["A", "B"]
    op.cleanup_session(None)
    print("test_flush_add_dispatches_per_sequence PASS")


def test_plan_table_rows():
    from bokeh.document import Document
    from helao.core.servers.operator.bokeh_operator import BokehOperator
    from helao.helpers.premodels import Sequence, Experiment

    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    seq = Sequence(sequence_name="s")
    seq.sequence_label = "L"
    seq.planned_experiments = [Experiment(experiment_name="exp0")]
    op.plan = [seq]
    asyncio.run(op.update_tables())
    assert op.experiment_plan_source.data["experiment_name"] == ["exp0"]
    assert op.experiment_plan_source.data["sequence_name"] == ["s"]
    assert op.button_add_expplan.label == "Add plan [1]"
    op.cleanup_session(None)
    print("test_plan_table_rows PASS")
```

- [ ] **Step 2: Run tests to verify they fail**

Run the test command.
Expected: FAIL — `AttributeError: 'BokehOperator' object has no attribute 'plan'` (and `_flush_plan`).

- [ ] **Step 3: Initialize the buffer**

In `bokeh_operator.py` `__init__`, replace `self.sequence = None` (~line 153) with:

```python
        self.plan = []
```

Also update the class annotation near the top of the class body (~line 92): change

```python
    sequence: Sequence
```

to

```python
    plan: List[Sequence]
```

- [ ] **Step 4: Add `_capture_metadata`, remove `_apply_sequence_to_orch`**

Delete the entire `_apply_sequence_to_orch` method (~891-907) and add in its place:

```python
    def _capture_metadata(self, seq: Sequence) -> None:
        """Stamp label / campaign / comment from the current inputs onto ``seq``."""
        seq.sequence_label = self.input_sequence_label.value
        if self.input_sequence_comment.value != "":
            seq.sequence_comment = self.input_sequence_comment.value
        campaign_name = self.input_campaign_name.value
        if campaign_name != "":
            seq.campaign_name = campaign_name
            if self.input_campaign_uuid.value.strip() == "":
                seq.campaign_uuid = md5_string(campaign_name)
            else:
                seq.campaign_uuid = self.input_campaign_uuid.value.strip()
```

- [ ] **Step 5: Add `_flush_plan` and rewrite the append/split/clear callbacks**

Replace `callback_add_expplan` (~1381-1383) and `callback_add_split_sequences` (~1385-1387) with:

```python
    async def _flush_plan(self, plan, method):
        """Dispatch each buffered sequence through ``method`` (add_sequence / add_split_sequences)."""
        for seq in plan:
            await method(seq)

    def callback_add_expplan(self, event):
        """Enqueue every buffered sequence on the orchestrator (append)."""
        plan = self.plan
        self.plan = []
        self.vis.doc.add_next_tick_callback(
            partial(self._flush_plan, plan, self.backend.add_sequence)
        )
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_add_split_sequences(self, event):
        """Enqueue every buffered sequence via the split-by-sample helper."""
        plan = self.plan
        self.plan = []
        self.vis.doc.add_next_tick_callback(
            partial(self._flush_plan, plan, self.backend.add_split_sequences)
        )
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))
```

Replace `callback_clear_expplan` (~1417-1421) with:

```python
    def callback_clear_expplan(self, event):
        """Discard the staged plan buffer and refresh the tables."""
        LOGGER.info("clearing plan buffer")
        self.plan = []
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))
```

- [ ] **Step 6: Rewrite the experiment insert ops**

Replace `append_experiment` / `prepend_experiment` (~1462-1470) with:

```python
    def append_experiment(self):
        """Wrap the current experiment selection as a manual sequence appended to the buffer."""
        experimentmodel = self.populate_experimentmodel()
        seq = Sequence(
            sequence_name="manual_orch_seq", planned_experiments=[experimentmodel]
        )
        self._capture_metadata(seq)
        self.plan.append(seq)

    def prepend_experiment(self):
        """Wrap the current experiment selection as a manual sequence prepended to the buffer."""
        experimentmodel = self.populate_experimentmodel()
        seq = Sequence(
            sequence_name="manual_orch_seq", planned_experiments=[experimentmodel]
        )
        self._capture_metadata(seq)
        self.plan.insert(0, seq)
```

- [ ] **Step 7: Rewrite `populate_sequence`**

Replace `populate_sequence` (~1503-1547) with:

```python
    def populate_sequence(self, prepend: bool = False):
        """Unpack the selected sequence with current params and add it to the plan buffer."""
        selected_sequence = self.sequence_dropdown.value
        LOGGER.info(f"selected sequence from list: {selected_sequence}")

        sequence_params = {
            paraminput.title: (
                input_type(parse_bokeh_input(paraminput.value))
                if input_type in BUILTIN_TYPES
                else parse_bokeh_input(paraminput.value)
            )
            for paraminput, input_type in zip(
                self.seq_param_input, self.seq_param_input_types
            )
        }
        for k, v in sequence_params.items():
            LOGGER.info(f"added sequence param '{k}' with value {v} and type {type(v)} ")

        self.write_params("seq", selected_sequence, sequence_params)
        expplan_list = self.backend.unpack_sequence(
            sequence_name=selected_sequence, sequence_params=sequence_params
        )
        seq = Sequence(
            sequence_name=selected_sequence,
            sequence_params=sequence_params,
            planned_experiments=expplan_list,
        )
        self._capture_metadata(seq)
        if prepend:
            self.plan.insert(0, seq)
        else:
            self.plan.append(seq)
```

- [ ] **Step 8: Rewrite `populate_experimentmodel`**

Replace `populate_experimentmodel` (~1549-1575) with (drop the `self.sequence` mutation block; return only the model):

```python
    def populate_experimentmodel(self) -> Experiment:
        """Build an ``Experiment`` from the experiment dropdown and current parameter inputs."""
        selected_experiment = self.experiment_dropdown.value
        LOGGER.info(f"selected experiment from list: {selected_experiment}")
        experiment_params = {
            paraminput.title: (
                input_type(parse_bokeh_input(paraminput.value))
                if input_type in BUILTIN_TYPES
                else parse_bokeh_input(paraminput.value)
            )
            for paraminput, input_type in zip(
                self.exp_param_input, self.exp_param_input_types
            )
        }
        for k, v in experiment_params.items():
            LOGGER.info(f"added experiment param '{k}' with value {v} and type {type(v)} ")
        self.write_params("exp", selected_experiment, experiment_params)
        return Experiment(
            experiment_name=selected_experiment, experiment_params=experiment_params
        )
```

- [ ] **Step 9: Rewrite the plan-table block in `update_tables`**

In `update_tables`, replace the block (~2110-2126) that clears `experiment_plan_lists`, loops `if self.sequence is not None: for D in self.sequence.planned_experiments:`, and assigns `experiment_plan_source.data` with:

```python
        for key in self.experiment_plan_lists:
            self.experiment_plan_lists[key] = []
        seq_count = 0
        for seq in self.plan:
            seq_count += 1
            for D in seq.planned_experiments:
                self.experiment_plan_lists["sequence_name"].append(seq.sequence_name)
                self.experiment_plan_lists["sequence_label"].append(seq.sequence_label)
                self.experiment_plan_lists["experiment_name"].append(D.experiment_name)
        self.experiment_plan_source.data = self.experiment_plan_lists
```

Then change the button label line (~2152) from `f"Add plan [{plan_count}]"` to:

```python
        self.button_add_expplan.label = f"Add plan [{seq_count}]"
```

(There is no remaining reference to `plan_count` — the old `plan_count` counter is replaced by `seq_count`.)

- [ ] **Step 10: Run tests to verify they pass**

Run the test command.
Expected: `test_plan_buffer_append_and_wrap PASS`, `test_plan_buffer_order PASS`, `test_plan_metadata_capture_at_insert PASS`, `test_flush_add_dispatches_per_sequence PASS`, `test_plan_table_rows PASS`, and all earlier tests still pass.

- [ ] **Step 11: Commit**

```bash
git add helao/core/servers/operator/bokeh_operator.py helao/core/tests/test_standalone_operator.py
git commit -m "feat(operator): plan becomes ordered buffer of separate sequences

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: "Prepend plan" button + callback + enable gate

**Files:**
- Modify: `helao/core/servers/operator/bokeh_operator.py`
  - button creation in `__init__` (near `button_add_smpseqs` ~355)
  - both button rows in `layout4` (~635 and ~690)
  - new `callback_prepend_plan` (near the other plan callbacks)
  - enable gate in `update_tables` (after `loop_state` is computed ~2139-2151)
- Modify: `helao/core/tests/test_standalone_operator.py`

- [ ] **Step 1: Write the failing tests**

Add to the test file and register in `run_all()`:

```python
def test_prepend_plan_callback_clears_and_dispatches():
    from bokeh.document import Document
    from helao.core.servers.operator.bokeh_operator import BokehOperator
    from helao.helpers.premodels import Sequence

    be = _MockBackend()
    op = BokehOperator(_FakeVisOp(Document()), be)
    plan = [Sequence(sequence_name="A"), Sequence(sequence_name="B")]
    op.plan = plan
    op.callback_prepend_plan(None)
    assert op.plan == [], "buffer should clear synchronously"
    # the backend prepend takes the whole list in one call (order preserved)
    asyncio.run(be.prepend_sequences(plan))
    assert [s.sequence_name for s in be.prepended] == ["A", "B"]
    op.cleanup_session(None)
    print("test_prepend_plan_callback_clears_and_dispatches PASS")


def test_prepend_button_enable_gate():
    from bokeh.document import Document
    from helao.core.servers.operator.bokeh_operator import BokehOperator

    be = _MockBackend()
    op = BokehOperator(_FakeVisOp(Document()), be)

    be.loop_state = "started"
    asyncio.run(op.update_tables())
    assert op.button_prepend_plan.disabled is True, "disabled while running"

    be.loop_state = "stopped"
    asyncio.run(op.update_tables())
    assert op.button_prepend_plan.disabled is False, "enabled while stopped/paused"
    op.cleanup_session(None)
    print("test_prepend_button_enable_gate PASS")
```

- [ ] **Step 2: Run tests to verify they fail**

Run the test command.
Expected: FAIL — `AttributeError: 'BokehOperator' object has no attribute 'callback_prepend_plan'` / `button_prepend_plan`.

- [ ] **Step 3: Create the button**

In `__init__`, after the `self.button_add_smpseqs = ...` block (~355-357), add:

```python
        self.button_prepend_plan = self._make_button(
            "Prepend plan", "default", 100, self.callback_prepend_plan
        )
```

- [ ] **Step 4: Add the callback**

Add near `callback_add_split_sequences` (in the callbacks region):

```python
    def callback_prepend_plan(self, event):
        """Prepend the whole plan buffer to the front of the orch sequence queue."""
        plan = self.plan
        self.plan = []
        self.vis.doc.add_next_tick_callback(
            partial(self.backend.prepend_sequences, plan)
        )
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))
```

- [ ] **Step 5: Place the button in both control rows**

In `layout4`, the first control row (~633-646) lists `self.button_add_expplan, Spacer, self.button_add_smpseqs, Spacer, self.button_start_orch, ...`. Insert the prepend button after `button_add_smpseqs`:

```python
                        [
                            self.button_add_expplan,
                            Spacer(width=10),
                            self.button_add_smpseqs,
                            Spacer(width=10),
                            self.button_prepend_plan,
                            Spacer(width=10),
                            self.button_start_orch,
                            Spacer(width=10),
                            self.button_stop_orch,
                            Spacer(width=10),
                            self.button_clear_expplan,
                            Spacer(width=10),
                            self.orch_status_button,
                        ],
```

Apply the identical insertion to the second control row (~689-701, the block beginning with `self.button_add_expplan,` inside the `background="#AED6F1"` layout).

- [ ] **Step 6: Add the enable gate in `update_tables`**

In `update_tables`, after the `if/elif/else` that sets `self.orch_status_button` from `loop_state` (~2139-2151) and before `self.button_add_expplan.label = ...`, add:

```python
        self.button_prepend_plan.disabled = loop_state != LoopStatus.stopped.value
```

- [ ] **Step 7: Run tests to verify they pass**

Run the test command.
Expected: `test_prepend_plan_callback_clears_and_dispatches PASS`, `test_prepend_button_enable_gate PASS`; all earlier tests still pass.

- [ ] **Step 8: Run the full unit suite**

Run:
```bash
conda run -n helao python run_unit_tests.py
```
Expected: PASS (sample-model unit test). Then re-run the standalone-operator module to confirm `ALL STANDALONE_OPERATOR TESTS PASS`.

- [ ] **Step 9: Commit**

```bash
git add helao/core/servers/operator/bokeh_operator.py helao/core/tests/test_standalone_operator.py
git commit -m "feat(operator): add Prepend plan button gated on stopped loop

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Spec coverage check

- Goal 1 (plan = `List[Sequence]`): Task 5 (init `self.plan`, table loop).
- Goal 2 (append/prepend library sequence inserts a whole `Sequence`): Task 5 (`populate_sequence`).
- Goal 3 (experiment wrapped as one manual sequence): Task 5 (`append_experiment`/`prepend_experiment`, `populate_experimentmodel`).
- Goal 4 (metadata captured at buffer-insert): Task 5 (`_capture_metadata` called in every insert op; `test_plan_metadata_capture_at_insert`).
- Goal 5 (Add / Split / Prepend / Clear flush): Task 5 (Add/Split/Clear), Task 6 (Prepend + gate).
- Goal 6 (run_id stamped at plan-add, back-to-back sharing, clear/drain → new): Task 1 (`_ensure_run_id`, `add_sequence`, `add_split_sequences`, dequeue), Task 2 (`prepend_sequences`).
- Backend/API surface for prepend: Task 3 (endpoint), Task 4 (ABC/Local/Remote).

## Notes for the implementer

- Tests use `Orch.__new__(Orch)` / `RemoteBackend.__new__(RemoteBackend)` to bypass heavy `__init__`; only the attributes the method under test reads are set. Do not add real `Orch` construction.
- `zdeque` pickles elements on write and returns *copies* on read/iteration. Tests that stamp a field then insert assert on the *original* object (which keeps the field); tests that read back order iterate the dq (copies) and read simple fields.
- `Experiment` is a subclass of `Sequence`, so storing `Experiment` instances in `planned_experiments` matches the pre-existing pattern.
- Bokeh tolerates the same button model appearing in both control rows of `layout4` (the existing code already does this for `button_add_expplan` etc.); mirror that for `button_prepend_plan`.
- The label/campaign/comment inputs are mirrored pairs kept in sync by `_make_copy_callback`, so `_capture_metadata` reading the primary inputs is correct regardless of which selector tab is active.
