# Framework SP-VIS-3 Operator UI Port Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire-protocol-only port of the operator into the framework — `OrchBackend` ABC → `ports/operator_backend.py`, `RemoteBackend` + `HelaoOperator` → `adapters/`, `BokehOperator` (2800 LOC, as-is) → `app/operator/bokeh_operator.py` — with the operator-facing tests ported to pytest. Pure addition.

**Architecture:** Near-verbatim ports of `helao/core/servers/operator/`. The legacy `orch_backend.py` (which holds both the pure `OrchBackend` ABC and the I/O `RemoteBackend` in one file) is SPLIT: the ABC moves to `ports/` with only `abc`/`typing` imports; `RemoteBackend` moves to `adapters/` and imports the port. `BokehOperator` is repointed to framework `app/vis.py` + framework models and receives an injected backend (it never imports adapters). Missing deps (`premodels.Sequence/Experiment`, `to_json.parse_bokeh_input`, `import_autolibs`, `ws_utils`) are reused from `helao.helpers` as strangler-fig seams.

**Tech Stack:** Python 3.12 (conda env `helao`), Bokeh, pydantic, `pytest`.

## Global Constraints

- Run pytest via the `helao` conda env: `conda run -n helao python -m pytest <path> -v`. OS Python is 3.14; the project targets 3.12.
- Pure addition: do NOT modify any `helao/core/**` or `helao/deploy/**` file. Legacy `core/servers/operator/**` stays running for unmigrated deployments. (You may READ legacy files to copy them; never edit them.)
- Boundary contract: `ports/operator_backend.py` imports only `abc`/`typing` (pure). `app/operator/bokeh_operator.py` imports NO `helao.framework.adapters` (the backend is injected by the deployment factory). Adapters may do I/O. The AST boundary check (`helao/framework/tests/test_boundaries.py`) must stay green.
- Ports are near-verbatim: copy the legacy code, apply ONLY the import repoints named in each task. No logic edits, no renames, no restructuring (the 2800-LOC UI is NOT split).
- Reused legacy seams (import from `helao.helpers`, do NOT port): `premodels.Sequence`/`premodels.Experiment`, `to_json.parse_bokeh_input`, `import_autolibs.import_autolibs`, `ws_utils.WsSubscriber`.
- Framework dep homes (verified present): `async_private_dispatcher`/`private_dispatcher` in `helao.framework.support.dispatcher`; `read_config`/`CONFIG` in `helao.framework.support.config_loader`; `ErrorCodes` in `helao.framework.models.errors`; `LoopStatus` in `helao.framework.models.orchstatus`; `md5_string` in `helao.framework.support.time_utils`; `Vis` in `helao.framework.app.vis`.
- Test scope: port ONLY operator-facing tests from `helao/core/tests/test_standalone_operator.py`. SKIP the legacy-orch-internal tests (those importing `helao.core.servers.orch.Orch`, `helao.core.servers.orch_api`, or `helao.helpers.zdeque`) and the deploy-shim test — the framework orchestrator is out of scope for SP-VIS-3.
- New tests live under `helao/framework/tests/`.

---

### Task 1: `ports/operator_backend.py` (`OrchBackend` ABC)

**Files:**
- Create: `helao/framework/ports/operator_backend.py`
- Test: `helao/framework/tests/test_ports_operator_backend.py`

**Interfaces:**
- Produces: `OrchBackend` (ABC) with abstract methods `unpack_sequence`, `get_step_flags`, `set_step_flag`, `list_sequences`, `list_experiments`, `list_actions`, `get_queue_object`, `get_histories`, `get_status_summary`, `get_orch_state`, `add_sequence`, `add_split_sequences`, `prepend_sequences`, `move_sequence`, `remove_sequence`, `start`, `stop`, `skip`, `estop`, `clear_sequences`, `clear_experiments`, `clear_actions`, `subscribe`, `close`; class attrs `sequence_lib`, `experiment_lib`, `sequence_codehash`, `experiment_codehash`.

- [ ] **Step 1: Write the failing test**

```python
# helao/framework/tests/test_ports_operator_backend.py
"""Unit tests for the OrchBackend port (abstract seam)."""
import inspect

import pytest

from helao.framework.ports.operator_backend import OrchBackend


def test_orchbackend_is_abstract():
    with pytest.raises(TypeError):
        OrchBackend()  # abstract — cannot instantiate


def test_orchbackend_method_surface():
    expected = {
        "unpack_sequence", "get_step_flags", "set_step_flag", "list_sequences",
        "list_experiments", "list_actions", "get_queue_object", "get_histories",
        "get_status_summary", "get_orch_state", "add_sequence", "add_split_sequences",
        "prepend_sequences", "move_sequence", "remove_sequence", "start", "stop",
        "skip", "estop", "clear_sequences", "clear_experiments", "clear_actions",
        "subscribe", "close",
    }
    members = {n for n, _ in inspect.getmembers(OrchBackend, predicate=callable)}
    assert expected <= members


def test_port_is_pure():
    src = inspect.getsource(OrchBackend.__module__ and __import__(
        "helao.framework.ports.operator_backend", fromlist=["x"]))
    text = inspect.getsource(__import__(
        "helao.framework.ports.operator_backend", fromlist=["x"]))
    for forbidden in ("helao.framework.adapters", "helao.helpers", "helao.core",
                      "import bokeh", "dispatcher", "ws_utils"):
        assert forbidden not in text, f"port imports forbidden: {forbidden}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_ports_operator_backend.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'helao.framework.ports.operator_backend'`

- [ ] **Step 3: Write minimal implementation**

Read legacy `helao/core/servers/operator/orch_backend.py` lines 1-114 (the module docstring, imports, and the `OrchBackend(ABC)` class — everything BEFORE `class RemoteBackend`). Create `helao/framework/ports/operator_backend.py` containing:
- A module docstring (you may keep/adapt the legacy one, describing the abstract seam).
- ONLY these imports: `from abc import ABC, abstractmethod` and `from typing import Callable, Optional`. Do NOT copy the legacy module's other imports (`asyncio`, `async_private_dispatcher`, `import_autolibs`, `WsSubscriber`, `ErrorCodes`, `logging`) — those belong to `RemoteBackend` (Task 2).
- The `OrchBackend(ABC)` class body copied byte-for-byte from legacy (the abstract methods + the `sequence_lib`/`experiment_lib`/`sequence_codehash`/`experiment_codehash` class-attr annotations + the `subscribe`/`close` concrete-ish methods exactly as written).

> If the copied `OrchBackend` body references `asyncio` (e.g. a default in `subscribe`/`close`), add `import asyncio` — but ONLY if actually used by the ABC body. Keep the import set minimal and I/O-free.

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_ports_operator_backend.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add helao/framework/ports/operator_backend.py helao/framework/tests/test_ports_operator_backend.py
git commit -m "feat(framework): SP-VIS-3 — port OrchBackend ABC into ports/"
```

---

### Task 2: `adapters/operator_backend.py` (`RemoteBackend`)

**Files:**
- Create: `helao/framework/adapters/operator_backend.py`
- Test: `helao/framework/tests/test_adapters_operator_backend.py`

**Interfaces:**
- Consumes: `helao.framework.ports.operator_backend.OrchBackend` (Task 1); `helao.framework.support.dispatcher.async_private_dispatcher`; `helao.framework.models.errors.ErrorCodes`; legacy seams `helao.helpers.import_autolibs.import_autolibs`, `helao.helpers.ws_utils.WsSubscriber`.
- Produces: `RemoteBackend(OrchBackend)` — `RemoteBackend(vis, orch_key=None, poll_interval=5.0)`; methods per the port; helpers `_call`, `_detect_orch_key`; attrs `orch_key`/`host`/`port`/`_dispatch`/`_step_flags`.

- [ ] **Step 1: Write the failing test**

Port the RemoteBackend-facing tests from `helao/core/tests/test_standalone_operator.py` — specifically the bodies of `test_remote_backend_dispatch_and_serialize` (lines 106-156), `test_remote_backend_prepend` (lines 427-456), `test_remote_backend_move_remove` (lines 679-701), and `test_remote_backend_get_queue_object` (lines 918-939). Copy each function body BYTE-FOR-BYTE, changing ONLY the imports inside them:
- `from helao.core.servers.operator.orch_backend import RemoteBackend` → `from helao.framework.adapters.operator_backend import RemoteBackend`
- `from helao.core.error import ErrorCodes` → `from helao.framework.models.errors import ErrorCodes`

Add the file header:

```python
# helao/framework/tests/test_adapters_operator_backend.py
"""Unit tests for the RemoteBackend orchestrator adapter (ported)."""
import asyncio
```

Then paste the four ported test functions (each constructs `RemoteBackend.__new__(RemoteBackend)`, sets `orch_key`/`host`/`port`/`_dispatch`/`_step_flags`, and drives the methods with a canned `fake_dispatch` — no live orch). Do NOT alter the assertions.

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_adapters_operator_backend.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'helao.framework.adapters.operator_backend'`

- [ ] **Step 3: Write minimal implementation**

Read legacy `helao/core/servers/operator/orch_backend.py` IN FULL. Create `helao/framework/adapters/operator_backend.py` containing the `RemoteBackend` class (legacy lines ~117-end) plus the module-level `import`s and `LOGGER` it needs. Apply ONLY these import repoints (drop the `OrchBackend` class — it now lives in the port):
- `from helao.helpers.dispatcher import async_private_dispatcher` → `from helao.framework.support.dispatcher import async_private_dispatcher`
- `from helao.core.error import ErrorCodes` → `from helao.framework.models.errors import ErrorCodes`
- `from helao.helpers import helao_logging as logging` → `from helao.framework.support import helao_logging as logging`
- Add `from helao.framework.ports.operator_backend import OrchBackend` (so `class RemoteBackend(OrchBackend)` resolves).
- KEEP as seams (unchanged): `from helao.helpers.import_autolibs import import_autolibs`, `from helao.helpers.ws_utils import WsSubscriber as Wss`.

Every method body (`__init__`, `_detect_orch_key`, `_call`, `unpack_sequence`, `get_step_flags`, `set_step_flag`, the list/state/mutation methods, `subscribe`, `close`, etc.) is copied byte-for-byte. No logic changes.

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_adapters_operator_backend.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add helao/framework/adapters/operator_backend.py helao/framework/tests/test_adapters_operator_backend.py
git commit -m "feat(framework): SP-VIS-3 — port RemoteBackend into adapters/"
```

---

### Task 3: `adapters/helao_operator.py` (`HelaoOperator`)

**Files:**
- Create: `helao/framework/adapters/helao_operator.py`
- Test: `helao/framework/tests/test_adapters_helao_operator.py`

**Interfaces:**
- Consumes: `helao.framework.support.dispatcher.private_dispatcher`; `helao.framework.support.config_loader.read_config`; `helao.framework.models.errors.ErrorCodes`; legacy seam `helao.helpers.premodels.Sequence`/`Experiment` (for `add_sequence`/`add_experiment` `as_dict`).
- Produces: `HelaoOperator(config_arg, orch_key="ORCH")`; `request`, `start`, `stop`, `orch_state`, `get_active_experiment`, `get_active_sequence`, `add_experiment`, `add_sequence`, `get_latest_sequences`, `get_latest_experiments`, `get_latest_actions`.

- [ ] **Step 1: Write the failing test**

```python
# helao/framework/tests/test_adapters_helao_operator.py
"""Unit tests for the HelaoOperator programmatic orch client adapter."""
from helao.framework.adapters import helao_operator as ho
from helao.framework.models.errors import ErrorCodes


def _make_client():
    """Build a HelaoOperator without running __init__ (which needs a config)."""
    op = ho.HelaoOperator.__new__(ho.HelaoOperator)
    op.orch_key = "ORCH"
    op.orch_host = "127.0.0.1"
    op.orch_port = 8001
    return op


def test_request_dispatches_and_returns(monkeypatch):
    calls = []

    def fake_pd(server_key, host, port, endpoint, path_params, json_params):
        calls.append((server_key, endpoint, path_params, json_params))
        return {"ok": True, "endpoint": endpoint}, ErrorCodes.none

    monkeypatch.setattr(ho, "private_dispatcher", fake_pd)
    op = _make_client()
    resp = op.request("get_orch_state")
    assert resp == {"ok": True, "endpoint": "get_orch_state"}
    assert calls[0][1] == "get_orch_state"


def test_request_unreachable_returns_marker(monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("down")

    monkeypatch.setattr(ho, "private_dispatcher", boom)
    op = _make_client()
    resp = op.request("get_orch_state")
    assert resp["orch_state"] == "unreachable"
    assert resp["loop_state"] == "unreachable"


def test_add_experiment_append_payload(monkeypatch):
    captured = {}

    def fake_pd(server_key, host, port, endpoint, path_params, json_params):
        captured["endpoint"] = endpoint
        captured["json"] = json_params
        return {}, ErrorCodes.none

    monkeypatch.setattr(ho, "private_dispatcher", fake_pd)

    class _Exp:
        def as_dict(self):
            return {"experiment_name": "exp0"}

    op = _make_client()
    op.add_experiment(_Exp())  # index=-1 default → append
    assert captured["endpoint"] == "append_experiment"
    assert captured["json"] == {"experiment": {"experiment_name": "exp0"}}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_adapters_helao_operator.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'helao.framework.adapters.helao_operator'`

- [ ] **Step 3: Write minimal implementation**

Read legacy `helao/core/servers/operator/helao_operator.py` IN FULL. Create `helao/framework/adapters/helao_operator.py` as a byte-for-byte copy, applying ONLY these import repoints:
- `from helao.core.error import ErrorCodes` → `from helao.framework.models.errors import ErrorCodes`
- `from helao.helpers.dispatcher import private_dispatcher` → `from helao.framework.support.dispatcher import private_dispatcher`
- `from helao.helpers.config_loader import CONFIG, read_config` → `from helao.framework.support.config_loader import CONFIG, read_config`
- KEEP as seam: `from helao.helpers.premodels import Sequence, Experiment`.

All method bodies (`__init__`, `request`, `start`, `stop`, `orch_state`, `get_active_experiment`, `get_active_sequence`, `add_experiment`, `add_sequence`, `get_latest_*`) copied unchanged. The test monkeypatches `private_dispatcher` on this module, so it MUST be imported as a module-level name `private_dispatcher` (not aliased).

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_adapters_helao_operator.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add helao/framework/adapters/helao_operator.py helao/framework/tests/test_adapters_helao_operator.py
git commit -m "feat(framework): SP-VIS-3 — port HelaoOperator client into adapters/"
```

---

### Task 4: `app/operator/bokeh_operator.py` (`BokehOperator` UI)

**Files:**
- Create: `helao/framework/app/operator/__init__.py`
- Create: `helao/framework/app/operator/bokeh_operator.py`
- Test: `helao/framework/tests/test_app_operator.py`

**Interfaces:**
- Consumes: `helao.framework.app.vis.Vis` (type, SP-VIS-1); `helao.framework.models.orchstatus.LoopStatus`; `helao.framework.support.time_utils.md5_string`; `helao.framework.ports.operator_backend.OrchBackend` (type hint, if referenced); legacy seams `helao.helpers.premodels.Sequence`/`Experiment`, `helao.helpers.to_json.parse_bokeh_input`. The injected backend object satisfies the `OrchBackend` interface.
- Produces: `BokehOperator(vis, backend)`; module-level helpers used by tests: `_object_to_html`, and whatever `test_parse_arg_docs`/`test_tree_header_text` reference (e.g. `BokehOperator._parse_arg_docs`).

- [ ] **Step 1: Write the failing test**

Port the OPERATOR-FACING test functions from `helao/core/tests/test_standalone_operator.py`. Copy these into the new test file BYTE-FOR-BYTE except for the import repoints below. Also copy the shared fixtures `_exp0` (lines 12-14), `_FakeGlobalStatus` (17-24), `_FakeDirsOp` (54-62), `_FakeVisOp` (64-77), and the `_MockBackend` class (lines 167-243, defined inside `test_operator_accepts_backend` — lift it to module level so all tests share it, or keep it inline per test as the legacy does).

PORT these functions (operator UI tests): `test_operator_accepts_backend`, `test_operator_tables_from_backend`, `test_plate_api_disabled_by_default`, `test_plan_buffer_append_and_wrap`, `test_plan_buffer_order`, `test_plan_metadata_capture_at_insert`, `test_flush_add_dispatches_per_sequence`, `test_plan_table_rows`, `test_plan_reorder_and_remove`, `test_queue_controls_enable_gate`, `test_prepend_plan_callback_clears_and_dispatches`, `test_prepend_button_enable_gate`, `test_uuid_truncation_in_queue_tables`, `test_param_key_uses_name_not_title`, `test_find_input_matches_name`, `test_operator_label_sanitize_callback`, `test_save_restore_label_campaign`, `test_param_label_enumeration`, `test_object_to_html`, `test_parse_arg_docs`, `test_tree_header_text`, `test_history_objects_retained`, `test_planhistory_tree_render_plan`, `test_queue_tree_render_action_server`, `test_queue_tree_render_lazy_sequence`, `test_queue_tree_lazy_empty_clears`, `test_layout_is_stretch_width`.

SKIP these (out of scope — legacy orchestrator internals / deploy shim): `test_endpoint_helpers_shapes`, `test_shim_exposes_makebokehapp`, `test_orch_run_id_sharing`, `test_orch_resolve_active_run_id`, `test_orch_split_run_id`, `test_orch_prepend_order_and_run_id`, `test_queue_object_payload`, `test_prepend_sequences_helper`, `test_sanitize_sequence_label`, `test_orch_add_sequence_sanitizes_label`, `test_orch_move_and_remove_sequence`. (These import `helao.core.servers.orch`/`orch_api`/`zdeque`.) Also skip the RemoteBackend tests — they live in Task 2.

Import repoints to apply inside the ported test bodies:
- `from helao.core.servers.operator.bokeh_operator import BokehOperator` → `from helao.framework.app.operator.bokeh_operator import BokehOperator`
- `from helao.core.servers.operator.bokeh_operator import _object_to_html` → `from helao.framework.app.operator.bokeh_operator import _object_to_html`
- the multi-symbol import at legacy line 903 → repoint its module path to `helao.framework.app.operator.bokeh_operator`, same symbol list
- KEEP as seams: `from helao.helpers.premodels import Experiment as _ExpModel`, `from helao.helpers.premodels import Sequence` / `Sequence, Experiment`
- `bokeh.*` imports unchanged.

If lifting `_MockBackend` to module level, ensure every ported test that referenced it still resolves (it is the backend passed to `BokehOperator(vis, backend)`).

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_app_operator.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'helao.framework.app.operator'`

- [ ] **Step 3: Write minimal implementation**

Create `helao/framework/app/operator/__init__.py`:

```python
# helao/framework/app/operator/__init__.py
"""Framework Bokeh operator UI (app layer)."""
```

Read legacy `helao/core/servers/operator/bokeh_operator.py` IN FULL (2800 lines). Create `helao/framework/app/operator/bokeh_operator.py` as a byte-for-byte copy, applying ONLY these import repoints (legacy lines ~33-38):
- `from helao.core.servers.vis import Vis` → `from helao.framework.app.vis import Vis`
- `from helao.core.models.orchstatus import LoopStatus` → `from helao.framework.models.orchstatus import LoopStatus`
- `from helao.helpers.time_utils import md5_string` → `from helao.framework.support.time_utils import md5_string`
- KEEP as seams (unchanged): `from helao.helpers.to_json import parse_bokeh_input`, `from helao.helpers.premodels import Sequence, Experiment`
- `from helao.helpers import helao_logging as logging` → `from helao.framework.support import helao_logging as logging`
- All `bokeh.*`, stdlib, `numpy`, `pydantic`, `pybase64` imports unchanged.
- If the module imports `OrchBackend` (for a type hint), repoint to `from helao.framework.ports.operator_backend import OrchBackend`. If it does NOT import it, add nothing.

Every class/method/module-level-helper body (`BokehOperator`, `_object_to_html`, `_parse_arg_docs`, the tree/queue render helpers, all callbacks and layout code) is copied byte-for-byte. Do NOT split the file, rename symbols, or alter UI logic. Do NOT add a `makeBokehApp` (deployment wiring is out of scope).

> The file is large; copy it whole, then make the ~5 import edits at the top. After writing, grep the new file for any remaining `helao.core` or `helao.helpers.time_utils`/`helao.helpers.dispatcher` references and confirm only the intended seams (`helao.helpers.to_json`, `helao.helpers.premodels`) remain.

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_app_operator.py -v`
Expected: PASS (27 passed). If a ported test fails on an import of a symbol the legacy `bokeh_operator` exposes but you missed, re-check the repoint; do not change the test assertions.

- [ ] **Step 5: Commit**

```bash
git add helao/framework/app/operator/__init__.py helao/framework/app/operator/bokeh_operator.py helao/framework/tests/test_app_operator.py
git commit -m "feat(framework): SP-VIS-3 — port BokehOperator UI into app/operator/"
```

---

### Task 5: Full-suite + boundary verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full framework test suite**

Run: `conda run -n helao python -m pytest helao/framework/tests/ -p no:cacheprovider -q 2>&1 | tail -1`
Expected: all pass (new + pre-existing), no regressions.

- [ ] **Step 2: Confirm the AST boundary check is green**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_boundaries.py -v`
Expected: PASS. `ports/operator_backend.py` is pure (abc/typing only). `app/operator/bokeh_operator.py` imports no `helao.framework.adapters`.

- [ ] **Step 3: Confirm app/operator does not import adapters**

Run: `grep -n "helao.framework.adapters" helao/framework/app/operator/bokeh_operator.py || echo "NONE (clean)"`
Expected: `NONE (clean)` — the backend is injected, not imported.

- [ ] **Step 4: Confirm pure-addition (no legacy/deploy edits)**

Run: `git diff --name-only feat/framework-scaffold...HEAD | grep -E "helao/(core|deploy)/" || echo "NONE (clean)"`
Expected: `NONE (clean)` — only files under `helao/framework/**` and `docs/superpowers/**`.

- [ ] **Step 5: Commit (only if verification fixups were needed)**

```bash
git add -A
git commit -m "test(framework): SP-VIS-3 — verify full suite + boundary green"
```

---

## Self-Review

**Spec coverage:**
- §4.1 `ports/operator_backend.py` (OrchBackend ABC) → Task 1. ✓
- §4.2 `adapters/operator_backend.py` (RemoteBackend) → Task 2. ✓
- §4.3 `adapters/helao_operator.py` (HelaoOperator) → Task 3. ✓
- §4.4 `app/operator/bokeh_operator.py` (+ `__init__`) → Task 4. ✓
- §4.5 seams (premodels/to_json/import_autolibs/ws_utils reused) → enforced by the import-repoint rules in Tasks 2/4. ✓
- §2 wire-protocol-only (no orch endpoints), no deploy rewiring, no UI split, no makeBokehApp → Tasks honor; Task 5 Step 4 guards pure-addition. ✓
- §3 boundary (port pure, app/operator imports no adapters) → Task 1 purity test + Task 5 Steps 2-3. ✓
- §7 test strategy (port operator-facing tests, skip orch-internal/shim) → Tasks 2/4 explicit port/skip lists. ✓

**Placeholder scan:** No TBD/TODO. Large files use copy-verbatim-from-named-legacy-file + exact import-repoint lists (the legacy file is the authoritative source); test ports name exact functions + repoints. The conditional notes (OrchBackend asyncio import, OrchBackend type hint in bokeh_operator) are concrete guarded instructions, not placeholders.

**Type consistency:** `RemoteBackend(vis, orch_key=None, poll_interval=5.0)` and the `RemoteBackend.__new__` + `_dispatch`/`_step_flags` test setup are consistent Tasks 1/2. `OrchBackend` method surface consistent Tasks 1/2/4. `HelaoOperator` `add_experiment`/`request` consistent Task 3. `BokehOperator(vis, backend)` consistent Task 4. Seam imports (`premodels`, `to_json`) named identically across tasks.
