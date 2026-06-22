# Framework Scaffold + Test Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the `helao/framework/` package skeleton with hexagonal layer dirs, four message-shaped port Protocols, in-memory fake adapters, a real pytest+coverage harness, an AST import-boundary test, and a `run_framework_tests.py` merge gate.

**Architecture:** Layered hexagonal (per spec `docs/superpowers/specs/2026-06-22-helao-framework-core-rewrite-design.md`). This sub-project (#0) builds only the empty layer structure + the seams (ports), test doubles (fakes), and the test/quality infrastructure. No domain or app logic yet — those land in later sub-projects. The driver port is intentionally deferred to sub-project #3.

**Tech Stack:** Python 3.12 (helao conda env), pytest, pytest-cov, coverage.py, `typing.Protocol`, frozen dataclasses, `ast` stdlib module.

---

## Environment & conventions (read first)

- **Always run Python via the helao conda env.** Every command below uses `conda run -n helao ...`. Never use the OS `python` (it is 3.14, wrong version).
- **Branch:** all work on `feat/framework-scaffold` (already created off `unstable`). Never commit to `unstable`/`main`.
- **No private-deployment references** in any file added to this repo.
- The active `feat/framework-scaffold` branch already contains the design spec. Confirm with `git branch --show-current` before starting.

## File structure (what gets created)

```
pyproject.toml                                  # NEW: pytest + coverage config
helao/framework/__init__.py                     # package root
helao/framework/domain/__init__.py              # empty layer (filled by later sub-projects)
helao/framework/models/__init__.py              # empty layer (filled by later sub-projects)
helao/framework/app/__init__.py                 # empty layer
helao/framework/support/__init__.py             # empty layer
helao/framework/ports/__init__.py
helao/framework/ports/clock.py                  # Clock Protocol
helao/framework/ports/eventsink.py              # EventSink Protocol
helao/framework/ports/storage.py                # Storage Protocol
helao/framework/ports/transport.py              # Transport Protocol + Message/DeliveryResult
helao/framework/adapters/__init__.py
helao/framework/adapters/fakes/__init__.py
helao/framework/adapters/fakes/clock.py         # FakeClock
helao/framework/adapters/fakes/eventsink.py     # FakeEventSink
helao/framework/adapters/fakes/storage.py       # FakeStorage
helao/framework/adapters/fakes/transport.py     # FakeTransport
helao/framework/_devtools/__init__.py
helao/framework/_devtools/boundary_check.py     # AST import-boundary detector
helao/framework/_devtools/coverage_gate.py      # coverage-json threshold math
helao/framework/tests/conftest.py               # fixtures exposing the fakes
helao/framework/tests/test_ports_clock.py
helao/framework/tests/test_ports_eventsink.py
helao/framework/tests/test_ports_storage.py
helao/framework/tests/test_ports_transport.py
helao/framework/tests/test_fixtures.py
helao/framework/tests/test_boundaries.py
helao/framework/tests/test_coverage_gate.py
helao/framework/README.md                        # short orientation
run_framework_tests.py                           # NEW: merge gate at repo root
helao_dev_linux-64.yml / helao_dev_win-64.yml    # MODIFY: add pytest deps
```

**Responsibilities:**
- `ports/` — abstract seams (Protocols). Pure typing, no logic.
- `adapters/fakes/` — deterministic in-memory test doubles implementing the ports. Reused by every later sub-project's tests.
- `_devtools/` — repo-quality tooling (boundary detector, coverage math). Importable, omitted from coverage.
- `tests/` — pytest suite proving ports + fakes + tooling behave.
- `run_framework_tests.py` — runs the suite under coverage and enforces ≥90% on `domain/`+`models/`.

---

## Task 1: Install test deps into the helao env + record them

**Files:**
- Modify: `helao_dev_linux-64.yml`
- Modify: `helao_dev_win-64.yml`

- [ ] **Step 1: Install pytest + pytest-cov into the helao env**

Run:
```bash
conda install -n helao -c conda-forge -y pytest pytest-cov
```
Expected: completes; `coverage` is pulled in as a pytest-cov dependency.

- [ ] **Step 2: Verify they import under the helao env**

Run:
```bash
conda run -n helao python -c "import pytest, pytest_cov, coverage; print(pytest.__version__, pytest_cov.__version__, coverage.__version__)"
```
Expected: three version strings print, no traceback.

- [ ] **Step 3: Add the deps to both dev env files**

In `helao_dev_linux-64.yml` AND `helao_dev_win-64.yml`, under the top-level conda `dependencies:` list, add three entries in alphabetical position near `psutil`/`pyaml`:
```yaml
  - pytest
  - pytest-cov
  - coverage
```
(Insert each as its own `  - <name>` line, matching the existing 2-space indent of sibling entries.)

- [ ] **Step 4: Commit**

```bash
git add helao_dev_linux-64.yml helao_dev_win-64.yml
git commit -m "build(framework): add pytest/pytest-cov/coverage to dev env"
```

---

## Task 2: Package skeleton + pytest/coverage config

**Files:**
- Create: `helao/framework/__init__.py`, `helao/framework/domain/__init__.py`, `helao/framework/models/__init__.py`, `helao/framework/app/__init__.py`, `helao/framework/support/__init__.py`, `helao/framework/ports/__init__.py`, `helao/framework/adapters/__init__.py`, `helao/framework/adapters/fakes/__init__.py`, `helao/framework/_devtools/__init__.py`
- Create: `pyproject.toml`

- [ ] **Step 1: Create the package `__init__.py` files**

Each `__init__.py` listed above contains exactly this one line (a module docstring), except the layer packages get a descriptive docstring:

`helao/framework/__init__.py`:
```python
"""HELAO framework: deployment-agnostic hexagonal core (domain/ports/adapters/app)."""
```
`helao/framework/domain/__init__.py`:
```python
"""Pure domain logic — zero I/O. Imports only models and ports."""
```
`helao/framework/models/__init__.py`:
```python
"""Pydantic data models for the framework."""
```
`helao/framework/app/__init__.py`:
```python
"""Application wiring: composes domain + adapters into servers (FastAPI/Bokeh)."""
```
`helao/framework/support/__init__.py`:
```python
"""Vendored generic utilities (logging, yaml, config, time, codehash)."""
```
`helao/framework/ports/__init__.py`:
```python
"""Abstract seams (Protocols) the domain depends on; adapters implement them."""
```
`helao/framework/adapters/__init__.py`:
```python
"""Concrete port implementations (I/O lives here)."""
```
`helao/framework/adapters/fakes/__init__.py`:
```python
"""In-memory deterministic fakes implementing the ports, for tests."""
```
`helao/framework/_devtools/__init__.py`:
```python
"""Repo-quality tooling (import-boundary checks, coverage gate). Not shipped logic."""
```

- [ ] **Step 2: Create `pyproject.toml`**

`pyproject.toml`:
```toml
[tool.pytest.ini_options]
testpaths = ["helao/framework/tests"]
python_files = ["test_*.py"]
python_functions = ["test_*"]
addopts = "-q"

[tool.coverage.run]
source = ["helao/framework"]
branch = true
omit = [
    "helao/framework/tests/*",
    "helao/framework/_devtools/*",
    "helao/framework/adapters/fakes/*",
]

[tool.coverage.report]
show_missing = true
```

- [ ] **Step 3: Verify pytest collects an empty suite cleanly**

Run:
```bash
conda run -n helao python -m pytest
```
Expected: exits 0 (or 5 = "no tests collected"); no import/config errors. Either is acceptable at this step.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml helao/framework
git commit -m "feat(framework): add package skeleton and pytest/coverage config"
```

---

## Task 3: Clock port + FakeClock

**Files:**
- Create: `helao/framework/ports/clock.py`
- Create: `helao/framework/adapters/fakes/clock.py`
- Test: `helao/framework/tests/test_ports_clock.py`

- [ ] **Step 1: Write the failing test**

`helao/framework/tests/test_ports_clock.py`:
```python
from helao.framework.ports.clock import Clock
from helao.framework.adapters.fakes.clock import FakeClock


def test_fakeclock_satisfies_protocol():
    clock: Clock = FakeClock(start_ns=1000)
    assert isinstance(clock, Clock)


def test_fakeclock_reports_start_time():
    clock = FakeClock(start_ns=42)
    assert clock.now_ns() == 42


def test_fakeclock_advance_moves_time_forward():
    clock = FakeClock(start_ns=0)
    clock.advance(500)
    clock.advance(500)
    assert clock.now_ns() == 1000


def test_fakeclock_defaults_to_zero():
    assert FakeClock().now_ns() == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_ports_clock.py`
Expected: FAIL — `ModuleNotFoundError: helao.framework.ports.clock`.

- [ ] **Step 3: Write the port and the fake**

`helao/framework/ports/clock.py`:
```python
"""Clock port: monotonic-ish wall time in nanoseconds."""
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """Source of the current time in integer nanoseconds."""

    def now_ns(self) -> int:
        """Return the current time in nanoseconds since an arbitrary epoch."""
        ...
```

`helao/framework/adapters/fakes/clock.py`:
```python
"""Deterministic in-memory Clock for tests."""
from helao.framework.ports.clock import Clock


class FakeClock(Clock):
    """A clock whose time only changes when the test calls advance()."""

    def __init__(self, start_ns: int = 0) -> None:
        self._now_ns = start_ns

    def now_ns(self) -> int:
        return self._now_ns

    def advance(self, delta_ns: int) -> None:
        """Move time forward by delta_ns."""
        self._now_ns += delta_ns
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_ports_clock.py`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add helao/framework/ports/clock.py helao/framework/adapters/fakes/clock.py helao/framework/tests/test_ports_clock.py
git commit -m "feat(framework): add Clock port and FakeClock"
```

---

## Task 4: EventSink port + FakeEventSink

**Files:**
- Create: `helao/framework/ports/eventsink.py`
- Create: `helao/framework/adapters/fakes/eventsink.py`
- Test: `helao/framework/tests/test_ports_eventsink.py`

- [ ] **Step 1: Write the failing test**

`helao/framework/tests/test_ports_eventsink.py`:
```python
import pytest

from helao.framework.ports.eventsink import EventSink
from helao.framework.adapters.fakes.eventsink import FakeEventSink


def test_fake_satisfies_protocol():
    sink: EventSink = FakeEventSink()
    assert isinstance(sink, EventSink)


@pytest.mark.asyncio
async def test_emit_records_channel_and_payload():
    sink = FakeEventSink()
    await sink.emit("status", {"uuid": "abc", "state": "active"})
    await sink.emit("data", {"x": 1})
    assert sink.emitted == [
        ("status", {"uuid": "abc", "state": "active"}),
        ("data", {"x": 1}),
    ]


@pytest.mark.asyncio
async def test_emit_snapshots_payload():
    sink = FakeEventSink()
    payload = {"n": 1}
    await sink.emit("data", payload)
    payload["n"] = 999
    assert sink.emitted[0][1] == {"n": 1}
```

- [ ] **Step 2: Add asyncio support and run the failing test**

The fakes are async, so the suite needs an asyncio runner. Install the pytest plugin into the helao env:
```bash
conda install -n helao -c conda-forge -y pytest-asyncio
```
Then add it to `pyproject.toml` `[tool.pytest.ini_options]` so async tests run without per-test marks:
```toml
asyncio_mode = "auto"
```
(Add this line inside the existing `[tool.pytest.ini_options]` table.)
Also append `pytest-asyncio` to the conda `dependencies:` list in `helao_dev_linux-64.yml` and `helao_dev_win-64.yml` (one `  - pytest-asyncio` line each).

Run: `conda run -n helao python -m pytest helao/framework/tests/test_ports_eventsink.py`
Expected: FAIL — `ModuleNotFoundError: helao.framework.ports.eventsink`.

- [ ] **Step 3: Write the port and the fake**

`helao/framework/ports/eventsink.py`:
```python
"""EventSink port: async egress for status/data messages to subscribers."""
from typing import Any, Mapping, Protocol, runtime_checkable


@runtime_checkable
class EventSink(Protocol):
    """Sink that broadcasts a payload on a named channel."""

    async def emit(self, channel: str, payload: Mapping[str, Any]) -> None:
        """Publish payload to all subscribers of channel."""
        ...
```

`helao/framework/adapters/fakes/eventsink.py`:
```python
"""In-memory EventSink that records every emission for assertions."""
import copy
from typing import Any, Mapping

from helao.framework.ports.eventsink import EventSink


class FakeEventSink(EventSink):
    """Records (channel, payload) tuples; payloads are deep-copied on emit."""

    def __init__(self) -> None:
        self.emitted: list[tuple[str, Mapping[str, Any]]] = []

    async def emit(self, channel: str, payload: Mapping[str, Any]) -> None:
        self.emitted.append((channel, copy.deepcopy(dict(payload))))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_ports_eventsink.py`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add helao/framework/ports/eventsink.py helao/framework/adapters/fakes/eventsink.py helao/framework/tests/test_ports_eventsink.py pyproject.toml helao_dev_linux-64.yml helao_dev_win-64.yml
git commit -m "feat(framework): add EventSink port, FakeEventSink, pytest-asyncio"
```

---

## Task 5: Storage port + FakeStorage

**Files:**
- Create: `helao/framework/ports/storage.py`
- Create: `helao/framework/adapters/fakes/storage.py`
- Test: `helao/framework/tests/test_ports_storage.py`

- [ ] **Step 1: Write the failing test**

`helao/framework/tests/test_ports_storage.py`:
```python
import pytest

from helao.framework.ports.storage import Storage, StorageKeyError
from helao.framework.adapters.fakes.storage import FakeStorage


def test_fake_satisfies_protocol():
    storage: Storage = FakeStorage()
    assert isinstance(storage, Storage)


def test_write_returns_relpath_and_read_roundtrips():
    storage = FakeStorage()
    written = storage.write_json("runs/act/meta.json", {"a": 1, "b": [2, 3]})
    assert written == "runs/act/meta.json"
    assert storage.read_json("runs/act/meta.json") == {"a": 1, "b": [2, 3]}


def test_write_snapshots_payload():
    storage = FakeStorage()
    payload = {"n": 1}
    storage.write_json("x.json", payload)
    payload["n"] = 999
    assert storage.read_json("x.json") == {"n": 1}


def test_read_missing_raises_storagekeyerror():
    storage = FakeStorage()
    with pytest.raises(StorageKeyError):
        storage.read_json("nope.json")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_ports_storage.py`
Expected: FAIL — `ModuleNotFoundError: helao.framework.ports.storage`.

- [ ] **Step 3: Write the port and the fake**

`helao/framework/ports/storage.py`:
```python
"""Storage port: persist and retrieve JSON-serializable documents by relative path."""
from typing import Any, Mapping, Protocol, runtime_checkable


class StorageKeyError(KeyError):
    """Raised when reading a relpath that was never written."""


@runtime_checkable
class Storage(Protocol):
    """Persists JSON documents under repo-relative paths (e.g. RUNS_* layout)."""

    def write_json(self, relpath: str, payload: Mapping[str, Any]) -> str:
        """Write payload as JSON at relpath; return the relpath written."""
        ...

    def read_json(self, relpath: str) -> Mapping[str, Any]:
        """Read and return the JSON document at relpath.

        Raises StorageKeyError if relpath was never written.
        """
        ...
```

`helao/framework/adapters/fakes/storage.py`:
```python
"""In-memory Storage backed by a dict, for tests."""
import copy
from typing import Any, Mapping

from helao.framework.ports.storage import Storage, StorageKeyError


class FakeStorage(Storage):
    """Stores deep-copied JSON documents keyed by relpath."""

    def __init__(self) -> None:
        self._docs: dict[str, dict[str, Any]] = {}

    def write_json(self, relpath: str, payload: Mapping[str, Any]) -> str:
        self._docs[relpath] = copy.deepcopy(dict(payload))
        return relpath

    def read_json(self, relpath: str) -> Mapping[str, Any]:
        try:
            return copy.deepcopy(self._docs[relpath])
        except KeyError as exc:
            raise StorageKeyError(relpath) from exc
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_ports_storage.py`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add helao/framework/ports/storage.py helao/framework/adapters/fakes/storage.py helao/framework/tests/test_ports_storage.py
git commit -m "feat(framework): add Storage port and FakeStorage"
```

---

## Task 6: Transport port + Message/DeliveryResult + FakeTransport

**Files:**
- Create: `helao/framework/ports/transport.py`
- Create: `helao/framework/adapters/fakes/transport.py`
- Test: `helao/framework/tests/test_ports_transport.py`

Note: the transport port is **message-shaped** (publish a named Message / subscribe a handler), not RPC-call-shaped. This is the deliberate runway for a future event-bus adapter (spec §2 "A→C runway").

- [ ] **Step 1: Write the failing test**

`helao/framework/tests/test_ports_transport.py`:
```python
import pytest

from helao.framework.ports.transport import (
    Transport,
    Message,
    DeliveryResult,
)
from helao.framework.adapters.fakes.transport import FakeTransport


def test_message_is_frozen():
    msg = Message(name="dispatch_action", payload={"uuid": "abc"})
    with pytest.raises(Exception):
        msg.name = "other"  # type: ignore[misc]


def test_message_defaults_to_empty_payload():
    assert Message(name="ping").payload == {}


def test_fake_satisfies_protocol():
    transport: Transport = FakeTransport()
    assert isinstance(transport, Transport)


@pytest.mark.asyncio
async def test_publish_records_message_and_reports_delivered():
    transport = FakeTransport()
    result = await transport.publish(Message(name="dispatch", payload={"x": 1}))
    assert result == DeliveryResult(delivered=True, error=None)
    assert transport.published == [Message(name="dispatch", payload={"x": 1})]


@pytest.mark.asyncio
async def test_publish_can_be_configured_to_fail():
    transport = FakeTransport(fail_with="connection refused")
    result = await transport.publish(Message(name="dispatch"))
    assert result.delivered is False
    assert result.error == "connection refused"


@pytest.mark.asyncio
async def test_subscribed_handlers_receive_delivered_messages():
    transport = FakeTransport()
    seen: list[Message] = []

    async def handler(message: Message) -> None:
        seen.append(message)

    transport.subscribe(handler)
    await transport.deliver(Message(name="status", payload={"state": "active"}))
    assert seen == [Message(name="status", payload={"state": "active"})]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_ports_transport.py`
Expected: FAIL — `ModuleNotFoundError: helao.framework.ports.transport`.

- [ ] **Step 3: Write the port and the fake**

`helao/framework/ports/transport.py`:
```python
"""Transport port: message-shaped publish/subscribe between servers.

Deliberately message-shaped (not RPC-call-shaped) so a future event-bus
adapter can implement the same interface (spec A->C runway).
"""
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping, Protocol, runtime_checkable


@dataclass(frozen=True)
class Message:
    """A named message with a JSON-serializable payload."""

    name: str
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DeliveryResult:
    """Outcome of a publish attempt. Expected failures are values, not exceptions."""

    delivered: bool
    error: str | None = None


Handler = Callable[[Message], Awaitable[None]]


@runtime_checkable
class Transport(Protocol):
    """Publishes Messages and registers async handlers for incoming Messages."""

    async def publish(self, message: Message) -> DeliveryResult:
        """Send message; return a DeliveryResult (never raise for expected failures)."""
        ...

    def subscribe(self, handler: Handler) -> None:
        """Register handler to be invoked for each incoming message."""
        ...
```

`helao/framework/adapters/fakes/transport.py`:
```python
"""In-memory Transport for tests: records publishes, drives subscribers manually."""
from helao.framework.ports.transport import (
    DeliveryResult,
    Handler,
    Message,
    Transport,
)


class FakeTransport(Transport):
    """Records published messages; `deliver` invokes subscribed handlers.

    Pass fail_with=<str> to make every publish return a failed DeliveryResult.
    """

    def __init__(self, fail_with: str | None = None) -> None:
        self.published: list[Message] = []
        self._handlers: list[Handler] = []
        self._fail_with = fail_with

    async def publish(self, message: Message) -> DeliveryResult:
        self.published.append(message)
        if self._fail_with is not None:
            return DeliveryResult(delivered=False, error=self._fail_with)
        return DeliveryResult(delivered=True, error=None)

    def subscribe(self, handler: Handler) -> None:
        self._handlers.append(handler)

    async def deliver(self, message: Message) -> None:
        """Test helper: dispatch message to every subscribed handler in order."""
        for handler in self._handlers:
            await handler(message)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_ports_transport.py`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add helao/framework/ports/transport.py helao/framework/adapters/fakes/transport.py helao/framework/tests/test_ports_transport.py
git commit -m "feat(framework): add message-shaped Transport port and FakeTransport"
```

---

## Task 7: conftest fixtures exposing the fakes

**Files:**
- Create: `helao/framework/tests/conftest.py`
- Test: `helao/framework/tests/test_fixtures.py`

- [ ] **Step 1: Write the failing test**

`helao/framework/tests/test_fixtures.py`:
```python
from helao.framework.adapters.fakes.clock import FakeClock
from helao.framework.adapters.fakes.eventsink import FakeEventSink
from helao.framework.adapters.fakes.storage import FakeStorage
from helao.framework.adapters.fakes.transport import FakeTransport


def test_fixtures_provide_fresh_fakes(fake_clock, fake_eventsink, fake_storage, fake_transport):
    assert isinstance(fake_clock, FakeClock)
    assert isinstance(fake_eventsink, FakeEventSink)
    assert isinstance(fake_storage, FakeStorage)
    assert isinstance(fake_transport, FakeTransport)


def test_fake_storage_fixture_is_isolated_between_tests(fake_storage):
    # If this fixture leaked state from another test, this key would exist.
    from helao.framework.ports.storage import StorageKeyError
    import pytest
    with pytest.raises(StorageKeyError):
        fake_storage.read_json("leaked.json")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_fixtures.py`
Expected: FAIL — fixtures `fake_clock` etc. not found.

- [ ] **Step 3: Write conftest**

`helao/framework/tests/conftest.py`:
```python
"""Shared pytest fixtures: a fresh fake per port for every test."""
import pytest

from helao.framework.adapters.fakes.clock import FakeClock
from helao.framework.adapters.fakes.eventsink import FakeEventSink
from helao.framework.adapters.fakes.storage import FakeStorage
from helao.framework.adapters.fakes.transport import FakeTransport


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def fake_eventsink() -> FakeEventSink:
    return FakeEventSink()


@pytest.fixture
def fake_storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
def fake_transport() -> FakeTransport:
    return FakeTransport()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_fixtures.py`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add helao/framework/tests/conftest.py helao/framework/tests/test_fixtures.py
git commit -m "test(framework): add conftest fixtures for the fakes"
```

---

## Task 8: AST import-boundary detector + test

**Files:**
- Create: `helao/framework/_devtools/boundary_check.py`
- Test: `helao/framework/tests/test_boundaries.py`

The detector enforces spec §3: `domain/` must never import FastAPI/httpx/bokeh/web/filesystem libs or `helao.framework.adapters` / `helao.framework.app`. It works at the import level (a runtime `open()` is out of its reach and is caught in code review).

- [ ] **Step 1: Write the failing test**

`helao/framework/tests/test_boundaries.py`:
```python
from pathlib import Path

from helao.framework._devtools.boundary_check import (
    find_forbidden_imports,
    DOMAIN_FORBIDDEN,
    scan_dir,
)


def test_clean_source_has_no_violations():
    src = "import math\nfrom helao.framework.models import action\nfrom helao.framework.ports.clock import Clock\n"
    assert find_forbidden_imports(src, DOMAIN_FORBIDDEN) == []


def test_plain_import_of_forbidden_module_is_flagged():
    assert find_forbidden_imports("import httpx\n", DOMAIN_FORBIDDEN) == ["httpx"]


def test_from_import_of_forbidden_module_is_flagged():
    assert find_forbidden_imports("from fastapi import FastAPI\n", DOMAIN_FORBIDDEN) == ["fastapi"]


def test_submodule_of_forbidden_prefix_is_flagged():
    found = find_forbidden_imports("from helao.framework.adapters.fakes import x\n", DOMAIN_FORBIDDEN)
    assert found == ["helao.framework.adapters.fakes"]


def test_substring_lookalike_is_not_flagged():
    # 'osmosis' must not trip an 'os' rule; matching is on dotted boundaries.
    assert find_forbidden_imports("import osmosis\n", {"os"}) == []


def test_real_domain_package_is_clean():
    domain_dir = Path("helao/framework/domain")
    violations = scan_dir(domain_dir, DOMAIN_FORBIDDEN)
    assert violations == {}, f"domain/ has forbidden imports: {violations}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_boundaries.py`
Expected: FAIL — `ModuleNotFoundError: helao.framework._devtools.boundary_check`.

- [ ] **Step 3: Write the detector**

`helao/framework/_devtools/boundary_check.py`:
```python
"""AST-based import-boundary checker for the hexagonal layering.

`domain/` is pure and must not import I/O frameworks or the adapters/app layers.
"""
import ast
from pathlib import Path
from typing import Iterable

# Module prefixes the domain layer must never import.
DOMAIN_FORBIDDEN: set[str] = {
    "fastapi",
    "starlette",
    "uvicorn",
    "httpx",
    "aiohttp",
    "requests",
    "bokeh",
    "panel",
    "aiofiles",
    "helao.framework.adapters",
    "helao.framework.app",
}


def _matches(module: str, forbidden: Iterable[str]) -> str | None:
    """Return the forbidden prefix that `module` violates, or None.

    Matching is on dotted-path boundaries: 'os' matches 'os' and 'os.path'
    but not 'osmosis'.
    """
    for prefix in forbidden:
        if module == prefix or module.startswith(prefix + "."):
            return module
    return None


def find_forbidden_imports(source: str, forbidden: Iterable[str]) -> list[str]:
    """Parse `source` and return the imported module names that are forbidden.

    Names are returned in source order; the returned value is the *imported*
    dotted name (e.g. 'helao.framework.adapters.fakes'), not the matched prefix.
    """
    tree = ast.parse(source)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                hit = _matches(alias.name, forbidden)
                if hit is not None:
                    found.append(hit)
        elif isinstance(node, ast.ImportFrom):
            if node.module is None or node.level != 0:
                continue  # relative imports stay within the package; allowed
            hit = _matches(node.module, forbidden)
            if hit is not None:
                found.append(hit)
    return found


def scan_dir(directory: Path, forbidden: Iterable[str]) -> dict[str, list[str]]:
    """Scan every .py file under `directory`; return {relpath: [violations]}.

    Files with no violations are omitted. Missing directory yields {}.
    """
    forbidden = set(forbidden)
    results: dict[str, list[str]] = {}
    if not directory.exists():
        return results
    for path in sorted(directory.rglob("*.py")):
        violations = find_forbidden_imports(path.read_text(encoding="utf-8"), forbidden)
        if violations:
            results[str(path)] = violations
    return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_boundaries.py`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add helao/framework/_devtools/boundary_check.py helao/framework/tests/test_boundaries.py
git commit -m "feat(framework): add AST import-boundary checker"
```

---

## Task 9: Coverage gate math + test

**Files:**
- Create: `helao/framework/_devtools/coverage_gate.py`
- Test: `helao/framework/tests/test_coverage_gate.py`

The gate enforces spec §7: ≥90% coverage on `domain/`+`models/`. It parses coverage.py's JSON report. With those layers empty (this sub-project), there are zero measurable statements, so the gate passes vacuously — the math must treat "0 statements" as a pass.

- [ ] **Step 1: Write the failing test**

`helao/framework/tests/test_coverage_gate.py`:
```python
from helao.framework._devtools.coverage_gate import (
    summarize,
    gate_passes,
    GATED_PREFIXES,
)


SAMPLE = {
    "files": {
        "helao/framework/domain/orchestration.py": {
            "summary": {"num_statements": 80, "covered_lines": 76}
        },
        "helao/framework/models/action.py": {
            "summary": {"num_statements": 20, "covered_lines": 20}
        },
        # adapters are not gated and must be ignored by the math:
        "helao/framework/adapters/http.py": {
            "summary": {"num_statements": 50, "covered_lines": 0}
        },
    }
}


def test_summarize_counts_only_gated_prefixes():
    covered, total = summarize(SAMPLE, GATED_PREFIXES)
    assert (covered, total) == (96, 100)


def test_gate_passes_at_or_above_threshold():
    assert gate_passes(SAMPLE, threshold=90.0, prefixes=GATED_PREFIXES) is True


def test_gate_fails_below_threshold():
    data = {
        "files": {
            "helao/framework/domain/x.py": {
                "summary": {"num_statements": 100, "covered_lines": 50}
            }
        }
    }
    assert gate_passes(data, threshold=90.0, prefixes=GATED_PREFIXES) is False


def test_empty_gated_layers_pass_vacuously():
    data = {"files": {"helao/framework/adapters/x.py": {"summary": {"num_statements": 10, "covered_lines": 0}}}}
    covered, total = summarize(data, GATED_PREFIXES)
    assert total == 0
    assert gate_passes(data, threshold=90.0, prefixes=GATED_PREFIXES) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_coverage_gate.py`
Expected: FAIL — `ModuleNotFoundError: helao.framework._devtools.coverage_gate`.

- [ ] **Step 3: Write the gate math**

`helao/framework/_devtools/coverage_gate.py`:
```python
"""Coverage-threshold math for the framework merge gate.

Parses coverage.py JSON (`coverage json`) and enforces a minimum percentage
on the gated layers only (domain + models). Empty gated layers pass.
"""
from typing import Iterable, Mapping

# Path prefixes the coverage threshold applies to.
GATED_PREFIXES: tuple[str, ...] = (
    "helao/framework/domain/",
    "helao/framework/models/",
)


def _normalize(path: str) -> str:
    return path.replace("\\", "/")


def summarize(cov_json: Mapping, prefixes: Iterable[str]) -> tuple[int, int]:
    """Return (covered_lines, num_statements) summed over gated files.

    A file is gated if its normalized path starts with any of `prefixes`.
    """
    prefixes = tuple(prefixes)
    covered = 0
    total = 0
    for path, entry in cov_json.get("files", {}).items():
        if _normalize(path).startswith(prefixes):
            summary = entry.get("summary", {})
            covered += int(summary.get("covered_lines", 0))
            total += int(summary.get("num_statements", 0))
    return covered, total


def gate_passes(cov_json: Mapping, threshold: float, prefixes: Iterable[str]) -> bool:
    """True if gated coverage >= threshold percent (or no gated statements exist)."""
    covered, total = summarize(cov_json, prefixes)
    if total == 0:
        return True
    return (covered / total) * 100.0 >= threshold
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_coverage_gate.py`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add helao/framework/_devtools/coverage_gate.py helao/framework/tests/test_coverage_gate.py
git commit -m "feat(framework): add coverage gate math"
```

---

## Task 10: `run_framework_tests.py` merge gate + README

**Files:**
- Create: `run_framework_tests.py`
- Create: `helao/framework/README.md`

- [ ] **Step 1: Write the gate runner**

`run_framework_tests.py`:
```python
"""Framework merge gate.

Runs the helao/framework pytest suite under coverage, then enforces a
minimum coverage percentage on the gated layers (domain + models).

Run with the helao conda env, e.g.:
    conda run -n helao python run_framework_tests.py
"""
import json
import subprocess
import sys
from pathlib import Path

from helao.framework._devtools.coverage_gate import (
    GATED_PREFIXES,
    gate_passes,
    summarize,
)

THRESHOLD = 90.0
COV_JSON = Path(".framework-cov.json")


def main() -> int:
    pytest_cmd = [
        sys.executable, "-m", "pytest",
        "helao/framework/tests",
        "--cov=helao/framework",
        "--cov-report=", f"--cov-report=json:{COV_JSON}",
    ]
    result = subprocess.run(pytest_cmd)
    if result.returncode not in (0, 5):  # 5 == no tests collected
        print(f"[gate] pytest failed (exit {result.returncode})")
        return result.returncode

    if not COV_JSON.exists():
        print("[gate] no coverage report produced; nothing to gate")
        return 0

    cov_json = json.loads(COV_JSON.read_text(encoding="utf-8"))
    covered, total = summarize(cov_json, GATED_PREFIXES)
    if total == 0:
        print("[gate] gated layers (domain+models) have no statements yet — PASS")
        return 0

    pct = (covered / total) * 100.0
    ok = gate_passes(cov_json, THRESHOLD, GATED_PREFIXES)
    status = "PASS" if ok else "FAIL"
    print(f"[gate] domain+models coverage: {covered}/{total} = {pct:.1f}% (>= {THRESHOLD}%? {status})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the full gate**

Run:
```bash
conda run -n helao python run_framework_tests.py
```
Expected: all framework tests pass; final line reports the gated layers have no statements yet — PASS; exit 0.

- [ ] **Step 3: Verify the gate catches a forced failure (manual sanity check)**

Run:
```bash
conda run -n helao python -c "from helao.framework._devtools.coverage_gate import gate_passes, GATED_PREFIXES; print(gate_passes({'files': {'helao/framework/domain/x.py': {'summary': {'num_statements': 10, 'covered_lines': 1}}}}, 90.0, GATED_PREFIXES))"
```
Expected: prints `False` (confirms the gate would block a real under-covered domain).

- [ ] **Step 4: Write the framework README**

`helao/framework/README.md`:
```markdown
# helao.framework

Deployment-agnostic HELAO core, rebuilt as a layered hexagonal package.
See the design spec: `docs/superpowers/specs/2026-06-22-helao-framework-core-rewrite-design.md`.

## Layers

- `domain/` — pure logic, zero I/O. Imports only `models/` and `ports/`.
- `models/` — pydantic data models.
- `ports/` — abstract seams (Protocols): `clock`, `eventsink`, `storage`, `transport`. (`driver` lands in a later sub-project.)
- `adapters/` — concrete port implementations (I/O). `adapters/fakes/` holds in-memory test doubles.
- `app/` — wiring: composes domain + adapters into servers.
- `support/` — vendored generic utilities.

## Boundary rule

`domain/` may not import web/IO frameworks or `adapters`/`app`. Enforced by
`helao/framework/tests/test_boundaries.py`.

## Running tests

Always use the helao conda env (Python 3.12):

```bash
conda run -n helao python -m pytest          # run the suite
conda run -n helao python run_framework_tests.py   # suite + coverage gate (>=90% on domain+models)
```
```

- [ ] **Step 5: Add the coverage artifact to .gitignore**

Append to the repo-root `.gitignore`:
```
.framework-cov.json
.coverage
```

- [ ] **Step 6: Commit**

```bash
git add run_framework_tests.py helao/framework/README.md .gitignore
git commit -m "feat(framework): add merge gate runner and README"
```

---

## Task 11: Final verification

- [ ] **Step 1: Run the whole framework suite + gate one more time**

Run:
```bash
conda run -n helao python run_framework_tests.py
```
Expected: every test passes (clock, eventsink, storage, transport, fixtures, boundaries, coverage_gate), gate reports PASS, exit 0.

- [ ] **Step 2: Confirm the boundary test guards a real (empty) domain**

Run:
```bash
conda run -n helao python -m pytest helao/framework/tests/test_boundaries.py -v
```
Expected: `test_real_domain_package_is_clean` PASSED.

- [ ] **Step 3: Confirm no private-deployment names leaked into added files**

Run:
```bash
git diff unstable --name-only | xargs grep -niE "lila|lila_gl|\bmea\b|\bpriv\b" 2>/dev/null || echo "clean"
```
Expected: `clean`.

- [ ] **Step 4: Verify branch + final state**

Run:
```bash
git branch --show-current && git log --oneline unstable..HEAD
```
Expected: on `feat/framework-scaffold`; the log lists the scaffold commits (spec cherry-picks + the 10 task commits).

---

## Self-review notes (for the implementer)

- This plan delivers spec §3 (package layout), §2 A→C runway (message-shaped transport + frozen Message/DeliveryResult value objects), and §7 (pytest harness, fakes via conftest, AST boundary test, ≥90% domain+models coverage gate, gate runner). The golden-master safety net (§7) and the driver port (§4.6 / sub-project #3) are intentionally out of this sub-project's scope.
- All commands use `conda run -n helao`. No OS python.
- No private-deployment names appear anywhere in the added files.
