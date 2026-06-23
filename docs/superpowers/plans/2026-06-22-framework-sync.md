# SP6: Data Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port `HelaoSyncer` into `helao/framework/` following the hexagonal architecture — pure `SyncEngine` domain class injected with a `SyncStorage` port, real `FsSyncStorage` adapter, and S3 stub adapter.

**Architecture:** `domain/sync/sync_models.py` holds pure value objects (`HelaoYml`, `Progress`, `SyncJob`); `domain/sync/sync_logic.py` holds `SyncEngine` (stateful, injected with `SyncStorage`); `ports/sync_storage.py` defines the Protocol; `adapters/fs_sync_storage.py` implements it with real filesystem ops; `adapters/fakes/sync_storage.py` provides an in-memory fake for tests.

**Tech Stack:** Python 3.12, pytest, ruamel.yaml, shutil, zipfile, orjson, pandas, pyarrow

---

> **Parallel execution note:** Tasks 1–4 have no inter-dependencies and MUST be dispatched in parallel. Task 5 depends on Tasks 1–4. Tasks 6–7 depend on Task 3. Tasks 8–10 are test suites that depend on the implementation tasks above them. Task 11 is the gate run.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `helao/framework/support/async_utils.py` | Create | AsyncRWLock utility |
| `helao/framework/support/__init__.py` | Modify | Export AsyncRWLock |
| `helao/framework/domain/sync/__init__.py` | Create | Package init |
| `helao/framework/domain/sync/sync_models.py` | Create | HelaoYml, Progress, SyncJob value objects |
| `helao/framework/ports/sync_storage.py` | Create | SyncStorage Protocol |
| `helao/framework/adapters/fakes/sync_storage.py` | Create | FakeSyncStorage in-memory impl |
| `helao/framework/adapters/fakes/__init__.py` | Modify | Export FakeSyncStorage |
| `helao/framework/domain/sync/sync_logic.py` | Create | SyncEngine stateful class |
| `helao/framework/adapters/fs_sync_storage.py` | Create | FsSyncStorage real filesystem impl |
| `helao/framework/adapters/s3_sync_storage.py` | Create | S3SyncStorage stub |
| `helao/framework/adapters/loaders/__init__.py` | Create | Loaders package init |
| `helao/framework/adapters/loaders/hlo_loader.py` | Create | read_hlo, hlo_to_parquet |
| `helao/framework/tests/test_support_async_utils.py` | Create | AsyncRWLock tests |
| `helao/framework/tests/test_sync_models.py` | Create | Value object tests |
| `helao/framework/tests/test_sync_logic.py` | Create | SyncEngine tests |
| `helao/framework/tests/test_fs_sync_storage.py` | Create | FsSyncStorage tests |
| `helao/framework/tests/test_loaders_hlo.py` | Create | HLO loader tests |
| `helao/framework/tests/conftest.py` | Modify | Add fake_sync_storage fixture |
| `helao/framework/_devtools/boundary_check.py` | Modify | Add boto3/shutil/ruamel to DOMAIN_FORBIDDEN |

---

## Task 1: AsyncRWLock utility

**Files:**
- Create: `helao/framework/support/async_utils.py`
- Modify: `helao/framework/support/__init__.py`
- Test: `helao/framework/tests/test_support_async_utils.py`

- [ ] **Step 1: Write the failing test**

```python
# helao/framework/tests/test_support_async_utils.py
import asyncio
import pytest
from helao.framework.support.async_utils import AsyncRWLock


def test_single_reader_acquires():
    lock = AsyncRWLock()
    log = []

    async def run():
        async with lock.read_locked():
            log.append("read")

    asyncio.run(run())
    assert log == ["read"]


def test_single_writer_acquires():
    lock = AsyncRWLock()
    log = []

    async def run():
        async with lock.write_locked():
            log.append("write")

    asyncio.run(run())
    assert log == ["write"]


def test_writer_waits_for_active_reader():
    lock = AsyncRWLock()
    log = []

    async def run():
        async def reader():
            async with lock.read_locked():
                log.append("read_start")
                await asyncio.sleep(0.05)
                log.append("read_end")

        async def writer():
            await asyncio.sleep(0.01)
            async with lock.write_locked():
                log.append("write")

        await asyncio.gather(reader(), writer())

    asyncio.run(run())
    assert log.index("write") > log.index("read_end")


def test_multiple_readers_do_not_block_each_other():
    lock = AsyncRWLock()
    acquired = []

    async def run():
        async def reader(name):
            async with lock.read_locked():
                acquired.append(name)
                await asyncio.sleep(0.02)

        await asyncio.gather(reader("r1"), reader("r2"))

    asyncio.run(run())
    assert set(acquired) == {"r1", "r2"}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
conda run -n helao python -m pytest helao/framework/tests/test_support_async_utils.py -v
```

Expected: `ImportError: cannot import name 'AsyncRWLock'`

- [ ] **Step 3: Create `support/async_utils.py`**

```python
"""Async reader/writer lock utility."""
import asyncio
from contextlib import asynccontextmanager


class AsyncRWLock:
    """Minimal asyncio reader/writer lock.

    Reader-preferring: a waiting writer does not block new readers from entering.
    Any number of readers hold concurrently; a writer holds exclusively.
    """

    def __init__(self):
        self._cond = asyncio.Condition()
        self._readers = 0
        self._writer = False

    @asynccontextmanager
    async def read_locked(self):
        """Acquire shared (reader) access for the duration of the context."""
        async with self._cond:
            while self._writer:
                await self._cond.wait()
            self._readers += 1
        try:
            yield
        finally:
            async with self._cond:
                self._readers -= 1
                if self._readers == 0:
                    self._cond.notify_all()

    @asynccontextmanager
    async def write_locked(self):
        """Acquire exclusive (writer) access for the duration of the context."""
        async with self._cond:
            while self._writer or self._readers > 0:
                await self._cond.wait()
            self._writer = True
        try:
            yield
        finally:
            async with self._cond:
                self._writer = False
                self._cond.notify_all()
```

- [ ] **Step 4: Update `support/__init__.py`**

The current file contains only a docstring. Append one line:

```python
"""Vendored generic utilities (logging, yaml, config, time, codehash)."""
from helao.framework.support.async_utils import AsyncRWLock  # noqa: F401
```

(Replace the entire file content with the above two lines.)

- [ ] **Step 5: Run tests to verify they pass**

```bash
conda run -n helao python -m pytest helao/framework/tests/test_support_async_utils.py -v
```

Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add helao/framework/support/async_utils.py helao/framework/support/__init__.py helao/framework/tests/test_support_async_utils.py
git commit -m "feat(framework): SP6 wave 1 — AsyncRWLock utility"
```

---

## Task 2: Pure value objects — `sync_models.py`

**Files:**
- Create: `helao/framework/domain/sync/__init__.py`
- Create: `helao/framework/domain/sync/sync_models.py`
- Test: `helao/framework/tests/test_sync_models.py`

- [ ] **Step 1: Write the failing test**

```python
# helao/framework/tests/test_sync_models.py
from pathlib import Path
from datetime import datetime
from helao.framework.domain.sync.sync_models import (
    HelaoYml, Progress, SyncJob,
    ABR_MAP, PLURALS,
)

# ─── HelaoYml ────────────────────────────────────────────────────────────────

def test_helao_yml_type_action():
    p = Path("/runs/RUNS_FINISHED/seq1/exp1/act1/20240101T120000_uuid-act.yml")
    assert HelaoYml(p).type == "action"


def test_helao_yml_type_experiment():
    p = Path("/runs/RUNS_FINISHED/seq1/exp1/20240101T120001_uuid-exp.yml")
    assert HelaoYml(p).type == "experiment"


def test_helao_yml_type_sequence():
    p = Path("/runs/RUNS_FINISHED/seq1/20240101T120002_uuid-seq.yml")
    assert HelaoYml(p).type == "sequence"


def test_helao_yml_status_finished():
    p = Path("/runs/RUNS_FINISHED/seq1/20240101T120002_uuid-seq.yml")
    assert HelaoYml(p).status == "finished"


def test_helao_yml_status_synced():
    p = Path("/runs/RUNS_SYNCED/seq1/20240101T120002_uuid-seq.yml")
    assert HelaoYml(p).status == "synced"


def test_helao_yml_status_active():
    p = Path("/runs/RUNS_ACTIVE/seq1/20240101T120002_uuid-seq.yml")
    assert HelaoYml(p).status == "active"


def test_helao_yml_active_path_swaps_runs_dir():
    p = Path("/runs/RUNS_FINISHED/seq1/exp1/20240101T120001_uuid-exp.yml")
    active = HelaoYml(p).active_path
    assert "RUNS_ACTIVE" in str(active)
    assert "RUNS_FINISHED" not in str(active)


def test_helao_yml_finished_path_is_unchanged():
    p = Path("/runs/RUNS_FINISHED/seq1/20240101T120002_uuid-seq.yml")
    assert HelaoYml(p).finished_path == p


def test_helao_yml_synced_path_swaps_runs_dir():
    p = Path("/runs/RUNS_FINISHED/seq1/20240101T120002_uuid-seq.yml")
    assert "RUNS_SYNCED" in str(HelaoYml(p).synced_path)


def test_helao_yml_prg_path_has_prg_suffix_under_synced():
    p = Path("/runs/RUNS_FINISHED/seq1/20240101T120002_uuid-seq.yml")
    prg = HelaoYml(p).prg_path
    assert prg.suffix == ".prg"
    assert "RUNS_SYNCED" in str(prg)


def test_helao_yml_relative_path_strips_runs_prefix():
    p = Path("/runs/RUNS_FINISHED/seq1/exp1/20240101T120001_uuid-exp.yml")
    rel = HelaoYml(p).relative_path
    assert "RUNS_FINISHED" not in rel
    assert "seq1" in rel
    assert "exp1" in rel


def test_helao_yml_timestamp_parsed():
    p = Path("/runs/RUNS_FINISHED/s/20240115T083045_uuid-seq.yml")
    ts = HelaoYml(p).timestamp
    assert ts == datetime(2024, 1, 15, 8, 30, 45)


def test_helao_yml_timestamp_missing_returns_min():
    p = Path("/runs/RUNS_FINISHED/s/no_timestamp-seq.yml")
    assert HelaoYml(p).timestamp == datetime.min


# ─── Progress ────────────────────────────────────────────────────────────────

def test_progress_defaults():
    p = Progress.from_dict({})
    assert p.s3_done is False
    assert p.api_done is False
    assert p.proc_states == {}


def test_progress_reads_s3_api_flags():
    p = Progress.from_dict({"s3": True, "api": True, "yml": "/path"})
    assert p.s3_done is True
    assert p.api_done is True


def test_progress_extra_keys_go_to_proc_states():
    p = Progress.from_dict({"s3": False, "api": False, "yml": "/p", "proc_0": "done"})
    assert p.proc_states["proc_0"] == "done"


def test_progress_to_dict_round_trip():
    data = {"s3": True, "api": False, "yml": "/p.yml", "proc_1": "pending"}
    p = Progress.from_dict(data)
    out = p.to_dict("/p.yml")
    assert out["s3"] is True
    assert out["api"] is False
    assert out["yml"] == "/p.yml"
    assert out["proc_1"] == "pending"


# ─── SyncJob ─────────────────────────────────────────────────────────────────

def test_sync_job_priority_ordering():
    def make(stem, pri):
        return SyncJob(
            yml=HelaoYml(Path(f"/runs/RUNS_FINISHED/s/e/{stem}.yml")),
            progress=Progress.from_dict({}),
            priority=pri,
        )

    act = make("20240101T120000_u-act", 0)
    exp = make("20240101T120001_u-exp", 1)
    seq = make("20240101T120002_u-seq", 2)
    assert act < exp < seq


def test_constants_present():
    assert ABR_MAP["act"] == "action"
    assert PLURALS["sequence"] == "sequences"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
conda run -n helao python -m pytest helao/framework/tests/test_sync_models.py -v
```

Expected: `ModuleNotFoundError: No module named 'helao.framework.domain.sync'`

- [ ] **Step 3: Create `domain/sync/__init__.py`**

```python
"""Sync domain: walk/classify/decide logic for RUNS_FINISHED trees."""
```

- [ ] **Step 4: Create `domain/sync/sync_models.py`**

```python
"""Pure value objects for the sync domain: HelaoYml, Progress, SyncJob."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

ABR_MAP: dict[str, str] = {
    "act": "action",
    "exp": "experiment",
    "seq": "sequence",
}
MOD_PATCH: dict[str, str] = {"exid": "exec_id"}
PLURALS: dict[str, str] = {
    "action": "actions",
    "experiment": "experiments",
    "sequence": "sequences",
    "process": "processes",
}


def _swap_runs_dir(path: Path, target: str) -> Path:
    parts = list(path.parts)
    for i, part in enumerate(parts):
        if part.startswith("RUNS_"):
            parts[i] = target
            return Path(*parts)
    return path


@dataclass(frozen=True)
class HelaoYml:
    """Pure value object wrapping a single *.yml path inside a RUNS_* tree.

    All properties are computed from the path string — no filesystem access.
    """

    path: Path

    @property
    def type(self) -> str:
        """'action', 'experiment', or 'sequence' parsed from filename stem."""
        suffix = self.path.stem.rsplit("-", 1)[-1]
        return ABR_MAP.get(suffix, suffix)

    @property
    def timestamp(self) -> datetime:
        """Timestamp parsed from the YYYYMMDDTHHMMSS prefix of the filename."""
        match = re.match(r"(\d{8}T\d{6})", self.path.stem)
        if match:
            return datetime.strptime(match.group(1), "%Y%m%dT%H%M%S")
        return datetime.min

    @property
    def status(self) -> str:
        """'active', 'finished', or 'synced' derived from RUNS_* parent dir."""
        for part in self.path.parts:
            if part == "RUNS_ACTIVE":
                return "active"
            if part == "RUNS_FINISHED":
                return "finished"
            if part == "RUNS_SYNCED":
                return "synced"
        return "unknown"

    @property
    def active_path(self) -> Path:
        return _swap_runs_dir(self.path, "RUNS_ACTIVE")

    @property
    def finished_path(self) -> Path:
        return _swap_runs_dir(self.path, "RUNS_FINISHED")

    @property
    def synced_path(self) -> Path:
        return _swap_runs_dir(self.path, "RUNS_SYNCED")

    @property
    def prg_path(self) -> Path:
        """Sidecar .prg path under RUNS_SYNCED (same stem as yml)."""
        return self.synced_path.with_suffix(".prg")

    @property
    def relative_path(self) -> str:
        """Path relative to the RUNS_* root directory."""
        parts = list(self.path.parts)
        for i, part in enumerate(parts):
            if part.startswith("RUNS_"):
                return str(Path(*parts[i + 1 :]))
        return str(self.path)


@dataclass(frozen=True)
class Progress:
    """Immutable sync state loaded from a .prg sidecar file."""

    s3_done: bool = False
    api_done: bool = False
    proc_states: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "Progress":
        return cls(
            s3_done=d.get("s3", False),
            api_done=d.get("api", False),
            proc_states={
                k: v for k, v in d.items() if k not in ("s3", "api", "yml")
            },
        )

    def to_dict(self, yml_path: str = "") -> dict:
        return {
            "yml": yml_path,
            "s3": self.s3_done,
            "api": self.api_done,
            **self.proc_states,
        }


@dataclass
class SyncJob:
    """A HelaoYml paired with its Progress, ready for SyncEngine."""

    yml: HelaoYml
    progress: Progress
    priority: int = 0  # 0=action, 1=experiment, 2=sequence

    def __lt__(self, other: "SyncJob") -> bool:
        return self.priority < other.priority
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
conda run -n helao python -m pytest helao/framework/tests/test_sync_models.py -v
```

Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add helao/framework/domain/sync/ helao/framework/tests/test_sync_models.py
git commit -m "feat(framework): SP6 wave 1 — sync value objects (HelaoYml, Progress, SyncJob)"
```

---

## Task 3: `SyncStorage` Protocol + `FakeSyncStorage`

**Files:**
- Create: `helao/framework/ports/sync_storage.py`
- Create: `helao/framework/adapters/fakes/sync_storage.py`
- Modify: `helao/framework/adapters/fakes/__init__.py`
- Modify: `helao/framework/tests/conftest.py`

- [ ] **Step 1: Create `ports/sync_storage.py`**

```python
"""SyncStorage port: filesystem + cloud-upload operations for the sync domain.

All methods are synchronous. S3 upload methods are stubbed in FsSyncStorage
and implemented in S3SyncStorage (follow-on SP).
"""
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class SyncStorage(Protocol):
    """Abstract sync operations. Injected into SyncEngine."""

    # Tree inspection
    def list_ymls(self, root: Path) -> list[Path]: ...
    def list_files(self, dir_path: Path, pattern: str = "*") -> list[Path]: ...

    # YAML I/O
    def read_yml(self, path: Path) -> dict: ...
    def write_yml(self, path: Path, data: dict) -> None: ...

    # Progress sidecar I/O
    def read_prg(self, path: Path) -> dict: ...
    def write_prg(self, path: Path, data: dict) -> None: ...
    def remove_prg(self, path: Path) -> None: ...

    # Filesystem mutations
    def move_tree(self, src: Path, dst: Path) -> Path: ...
    def zip_dir(self, path: Path) -> Path: ...
    def try_remove_empty(self, path: Path) -> bool: ...

    # Cloud upload (stubs in FsSyncStorage; real in S3SyncStorage)
    def upload_file(self, local_path: Path, s3_key: str) -> bool: ...
    def upload_bytes(
        self, data: bytes, s3_key: str, content_type: str = "application/json"
    ) -> bool: ...
    def key_exists(self, s3_key: str) -> bool: ...
```

- [ ] **Step 2: Create `adapters/fakes/sync_storage.py`**

```python
"""In-memory SyncStorage for tests. Records all mutating calls."""
from pathlib import Path


class FakeSyncStorage:
    """In-memory SyncStorage recording every operation for assertions."""

    def __init__(self) -> None:
        self._ymls: dict[Path, dict] = {}
        self._prgs: dict[Path, dict] = {}
        self.moved: list[tuple[Path, Path]] = []
        self.zipped: list[Path] = []
        self.uploaded_files: list[tuple[Path, str]] = []
        self.uploaded_bytes: list[tuple[bytes, str]] = []

    # ── helpers for test setup ────────────────────────────────────────────

    def add_yml(self, path: Path, data: dict | None = None) -> None:
        self._ymls[path] = data or {}

    # ── SyncStorage protocol ──────────────────────────────────────────────

    def list_ymls(self, root: Path) -> list[Path]:
        root_str = str(root)
        return sorted(p for p in self._ymls if str(p).startswith(root_str))

    def list_files(self, dir_path: Path, pattern: str = "*") -> list[Path]:
        return []

    def read_yml(self, path: Path) -> dict:
        return dict(self._ymls.get(path, {}))

    def write_yml(self, path: Path, data: dict) -> None:
        self._ymls[path] = dict(data)

    def read_prg(self, path: Path) -> dict:
        return dict(self._prgs.get(path, {}))

    def write_prg(self, path: Path, data: dict) -> None:
        self._prgs[path] = dict(data)

    def remove_prg(self, path: Path) -> None:
        self._prgs.pop(path, None)

    def move_tree(self, src: Path, dst: Path) -> Path:
        for p in list(self._ymls):
            rel = None
            try:
                rel = p.relative_to(src)
            except ValueError:
                pass
            if rel is not None:
                new_p = dst / rel
                self._ymls[new_p] = self._ymls.pop(p)
        self.moved.append((src, dst))
        return dst

    def zip_dir(self, path: Path) -> Path:
        self.zipped.append(path)
        return path.with_suffix(".zip")

    def try_remove_empty(self, path: Path) -> bool:
        return True

    def upload_file(self, local_path: Path, s3_key: str) -> bool:
        self.uploaded_files.append((local_path, s3_key))
        return True

    def upload_bytes(
        self, data: bytes, s3_key: str, content_type: str = "application/json"
    ) -> bool:
        self.uploaded_bytes.append((data, s3_key))
        return True

    def key_exists(self, s3_key: str) -> bool:
        return False
```

- [ ] **Step 3: Update `adapters/fakes/__init__.py`**

Add to the existing file:

```python
from helao.framework.adapters.fakes.sync_storage import FakeSyncStorage
```

- [ ] **Step 4: Add `fake_sync_storage` fixture to `tests/conftest.py`**

Add to the existing conftest.py:

```python
from helao.framework.adapters.fakes.sync_storage import FakeSyncStorage

@pytest.fixture
def fake_sync_storage() -> FakeSyncStorage:
    return FakeSyncStorage()
```

- [ ] **Step 5: Verify SyncStorage is a runtime_checkable Protocol**

```bash
conda run -n helao python -c "
from pathlib import Path
from helao.framework.ports.sync_storage import SyncStorage
from helao.framework.adapters.fakes.sync_storage import FakeSyncStorage
assert isinstance(FakeSyncStorage(), SyncStorage), 'FakeSyncStorage does not satisfy SyncStorage'
print('OK')
"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add helao/framework/ports/sync_storage.py helao/framework/adapters/fakes/sync_storage.py helao/framework/adapters/fakes/__init__.py helao/framework/tests/conftest.py
git commit -m "feat(framework): SP6 wave 1 — SyncStorage port + FakeSyncStorage"
```

---

## Task 4: HLO Loader

**Files:**
- Create: `helao/framework/adapters/loaders/__init__.py`
- Create: `helao/framework/adapters/loaders/hlo_loader.py`
- Test: `helao/framework/tests/test_loaders_hlo.py`

- [ ] **Step 1: Write the failing test**

```python
# helao/framework/tests/test_loaders_hlo.py
from pathlib import Path
import pytest
from helao.framework.adapters.loaders.hlo_loader import read_hlo, hlo_to_parquet


def _write_hlo(path: Path, n_rows: int = 3) -> Path:
    header = "action_uuid: test-uuid-001\nfiles: []\n"
    rows = [f'{{"t": {i}, "v": {i * 2}}}\n' for i in range(n_rows)]
    path.write_text(header + "%%\n" + "".join(rows), encoding="utf-8")
    return path


def test_read_hlo_returns_meta_and_data(tmp_path):
    hlo = _write_hlo(tmp_path / "test.hlo")
    meta, data = read_hlo(str(hlo))
    assert meta["action_uuid"] == "test-uuid-001"
    assert "t" in data and "v" in data
    assert len(data["t"]) == 3


def test_read_hlo_keep_keys_filters_columns(tmp_path):
    hlo = _write_hlo(tmp_path / "test.hlo")
    _, data = read_hlo(str(hlo), keep_keys=["t"])
    assert "t" in data
    assert "v" not in data


def test_read_hlo_omit_keys_filters_columns(tmp_path):
    hlo = _write_hlo(tmp_path / "test.hlo")
    _, data = read_hlo(str(hlo), omit_keys=["v"])
    assert "t" in data
    assert "v" not in data


def test_hlo_to_parquet_creates_file(tmp_path):
    hlo = _write_hlo(tmp_path / "test.hlo", n_rows=5)
    parquet = tmp_path / "out.parquet"
    hlo_to_parquet(str(hlo), str(parquet))
    assert parquet.exists()
    assert parquet.stat().st_size > 0


def test_hlo_to_parquet_readable_with_pyarrow(tmp_path):
    import pyarrow.parquet as pq

    hlo = _write_hlo(tmp_path / "test.hlo", n_rows=4)
    parquet = tmp_path / "out.parquet"
    hlo_to_parquet(str(hlo), str(parquet))
    table = pq.read_table(str(parquet))
    assert table.num_rows == 4
    assert "t" in table.column_names
```

- [ ] **Step 2: Run test to verify it fails**

```bash
conda run -n helao python -m pytest helao/framework/tests/test_loaders_hlo.py -v
```

Expected: `ModuleNotFoundError: No module named 'helao.framework.adapters.loaders'`

- [ ] **Step 3: Create `adapters/loaders/__init__.py`**

```python
"""HLO and parquet loaders — concrete read functions, no domain injection."""
```

- [ ] **Step 4: Create `adapters/loaders/hlo_loader.py`**

```python
"""Readers and conversion helpers for the HELAO .hlo data file format.

Direct port from helao/helpers/hlo_data.py with import paths updated to
use helao.framework.support.yml_tools instead of helao.helpers.yml_tools.
HelaoData lazy re-export is omitted (out of SP6 scope).
"""
__all__ = [
    "read_hlo",
    "read_hlo_stream",
    "read_hlo_bytes",
    "read_hlo_header",
    "read_hlo_data_chunks",
    "hlo_to_parquet",
    "read_helao_metadata",
]

import json
from collections import defaultdict
from io import BytesIO
from pathlib import Path
from typing import Tuple

import orjson
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from ruamel.yaml import YAML

from helao.framework.support.yml_tools import yml_load

_yaml = YAML()


def read_hlo(path, keep_keys: list = [], omit_keys: list = []) -> Tuple[dict, dict]:
    """Read a .hlo file; return (header_dict, data_dict).

    `path` may be a filesystem path string or raw bytes.
    """
    if isinstance(path, (bytes, bytearray)):
        return read_hlo_bytes(path, keep_keys=keep_keys, omit_keys=omit_keys)
    with open(str(Path(path)), "rb") as f:
        return read_hlo_stream(f, keep_keys=keep_keys, omit_keys=omit_keys)


def read_hlo_stream(stream, keep_keys: list = [], omit_keys: list = []) -> Tuple[dict, dict]:
    """Parse a (meta, data) pair from an open binary stream."""
    header_lines = []
    header_end = False
    data: dict = defaultdict(list)

    for line in stream:
        if header_end:
            line_dict = orjson.loads(line)
            for k in line_dict:
                if keep_keys:
                    if k in keep_keys:
                        v = line_dict[k]
                        data[k] += v if isinstance(v, list) else [v]
                else:
                    if k not in omit_keys:
                        v = line_dict[k]
                        data[k] += v if isinstance(v, list) else [v]
        elif line.decode("utf-8").startswith("%%"):
            header_end = True
        else:
            header_lines.append(line)

    if header_lines:
        meta = dict(yml_load("".join(x.decode("utf-8") for x in header_lines)))
    else:
        meta = {}
    return meta, dict(data)


def read_hlo_bytes(content, keep_keys: list = [], omit_keys: list = []) -> Tuple[dict, dict]:
    """Parse a (meta, data) pair from raw .hlo bytes."""
    return read_hlo_stream(BytesIO(content), keep_keys=keep_keys, omit_keys=omit_keys)


def read_hlo_header(file_path) -> tuple:
    """Return (header_dict, data_start_index) for a .hlo file."""
    yml_lines = []
    data_start_index = -1
    with open(file_path) as f:
        for i, line in enumerate(f):
            if line.strip().startswith("%%"):
                data_start_index = i + 1
                break
            yml_lines.append(line)
    yd = dict(_yaml.load("\n".join(yml_lines)))
    return yd, data_start_index


def read_hlo_data_chunks(file_path, data_start_index, chunk_size=100):
    """Yield (chunk_dict, max_len) tuples from the body of a .hlo file."""
    with open(file_path) as f:
        chunkd: dict = defaultdict(list)
        for i, line in enumerate(f):
            if i < data_start_index:
                continue
            jd = json.loads(line.strip())
            for k, val in jd.items():
                if isinstance(val, list):
                    chunkd[k] += val
                else:
                    chunkd[k].append(val)
            if (i - data_start_index + 1) % chunk_size == 0:
                yield dict(chunkd), max(len(v) for v in chunkd.values())
                chunkd = defaultdict(list)
        if chunkd:
            yield dict(chunkd), max(len(v) for v in chunkd.values())


def hlo_to_parquet(
    input_hlo_path, output_parquet_path, chunk_size: int = 100, HISPEC: bool = False
) -> None:
    """Convert a .hlo file to Parquet, embedding the header in schema metadata."""
    writer: pq.ParquetWriter | None = None
    schema = None
    metadata = None
    current_idx = 0
    header, data_start = read_hlo_header(input_hlo_path)

    for chunk, chunklen in read_hlo_data_chunks(input_hlo_path, data_start, chunk_size=chunk_size):
        df0 = pd.DataFrame(chunk, index=range(current_idx, current_idx + chunklen))
        table = pa.Table.from_pandas(df0)
        current_idx += chunklen

        if schema is None:
            custom_metadata = json.dumps(header.get("optional", {})).encode("utf8")
            existing = table.schema.metadata or {}
            metadata = {**{"helao_metadata": custom_metadata}, **existing}
        table = table.replace_schema_metadata(metadata)
        schema = table.schema

        if writer is None:
            writer = pq.ParquetWriter(output_parquet_path, schema)
        writer.write_table(table)

    if writer:
        writer.close()


def read_helao_metadata(parquet_file_path) -> dict:
    """Return the helao_metadata dict embedded in a Parquet schema."""
    meta = pq.read_metadata(parquet_file_path)
    return json.loads(meta.metadata.get(b"helao_metadata", b"{}").decode())
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
conda run -n helao python -m pytest helao/framework/tests/test_loaders_hlo.py -v
```

Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add helao/framework/adapters/loaders/ helao/framework/tests/test_loaders_hlo.py
git commit -m "feat(framework): SP6 wave 1 — HLO loader adapter"
```

---

## Task 5: `SyncEngine` domain class

> Depends on Tasks 1, 2, and 3 being complete.

**Files:**
- Create: `helao/framework/domain/sync/sync_logic.py`
- Test: `helao/framework/tests/test_sync_logic.py`

- [ ] **Step 1: Write the failing test**

```python
# helao/framework/tests/test_sync_logic.py
import asyncio
from pathlib import Path
from helao.framework.adapters.fakes.sync_storage import FakeSyncStorage
from helao.framework.domain.sync.sync_models import HelaoYml, Progress, SyncJob
from helao.framework.domain.sync.sync_logic import SyncEngine

_FINISHED = Path("/runs/RUNS_FINISHED")
_SYNCED = Path("/runs/RUNS_SYNCED")


def _config():
    return {
        "use_s3": False,
        "s3_prefix": "bucket/prefix",
        "runs_finished_root": _FINISHED,
        "runs_synced_root": _SYNCED,
    }


def _act_path():
    return _FINISHED / "seq1" / "exp1" / "act1" / "20240101T120000_uuid-act.yml"


def _exp_path():
    return _FINISHED / "seq1" / "exp1" / "20240101T120001_uuid-exp.yml"


def _seq_path():
    return _FINISHED / "seq1" / "20240101T120002_uuid-seq.yml"


# ── list_pending ──────────────────────────────────────────────────────────────

def test_list_pending_returns_only_seqs():
    store = FakeSyncStorage()
    store.add_yml(_seq_path())
    store.add_yml(_exp_path())
    store.add_yml(_act_path())
    engine = SyncEngine(store, _config())
    jobs = engine.list_pending()
    assert len(jobs) == 1
    assert jobs[0].yml.type == "sequence"


def test_list_pending_acts():
    store = FakeSyncStorage()
    store.add_yml(_act_path())
    store.add_yml(_seq_path())
    engine = SyncEngine(store, _config())
    jobs = engine.list_pending_acts()
    assert len(jobs) == 1
    assert jobs[0].yml.type == "action"


def test_list_pending_exps():
    store = FakeSyncStorage()
    store.add_yml(_exp_path())
    store.add_yml(_seq_path())
    engine = SyncEngine(store, _config())
    jobs = engine.list_pending_exps()
    assert len(jobs) == 1
    assert jobs[0].yml.type == "experiment"


def test_list_pending_omits_manual():
    store = FakeSyncStorage()
    manual = _FINISHED / "manual_orch_seq_20240101" / "20240101T120000_uuid-seq.yml"
    store.add_yml(manual)
    store.add_yml(_seq_path())
    engine = SyncEngine(store, _config())
    assert len(engine.list_pending(omit_manual=True)) == 1
    assert len(engine.list_pending(omit_manual=False)) == 2


# ── sync_one ──────────────────────────────────────────────────────────────────

def test_sync_one_act_calls_move_tree():
    store = FakeSyncStorage()
    store.add_yml(_act_path())
    engine = SyncEngine(store, _config())
    yml = HelaoYml(_act_path())
    job = SyncJob(yml=yml, progress=Progress.from_dict({}), priority=0)
    asyncio.run(engine.sync_one(job))
    assert len(store.moved) == 1
    src, dst = store.moved[0]
    assert "RUNS_FINISHED" in str(src)
    assert "RUNS_SYNCED" in str(dst)


def test_sync_one_act_does_not_zip():
    store = FakeSyncStorage()
    store.add_yml(_act_path())
    engine = SyncEngine(store, _config())
    yml = HelaoYml(_act_path())
    job = SyncJob(yml=yml, progress=Progress.from_dict({}), priority=0)
    asyncio.run(engine.sync_one(job))
    assert store.zipped == []


def test_sync_one_seq_calls_zip():
    store = FakeSyncStorage()
    store.add_yml(_seq_path())
    engine = SyncEngine(store, _config())
    yml = HelaoYml(_seq_path())
    job = SyncJob(yml=yml, progress=Progress.from_dict({}), priority=2)
    asyncio.run(engine.sync_one(job))
    assert len(store.zipped) == 1


def test_sync_one_no_upload_when_use_s3_false():
    store = FakeSyncStorage()
    store.add_yml(_act_path())
    engine = SyncEngine(store, _config())
    yml = HelaoYml(_act_path())
    job = SyncJob(yml=yml, progress=Progress.from_dict({}), priority=0)
    asyncio.run(engine.sync_one(job))
    assert store.uploaded_files == []
    assert store.uploaded_bytes == []


def test_sync_one_writes_prg():
    store = FakeSyncStorage()
    store.add_yml(_act_path())
    engine = SyncEngine(store, _config())
    yml = HelaoYml(_act_path())
    job = SyncJob(yml=yml, progress=Progress.from_dict({}), priority=0)
    asyncio.run(engine.sync_one(job))
    assert yml.prg_path in store._prgs


def test_sync_one_concurrent_acts_do_not_block_each_other():
    """Two acts in the same seq can sync simultaneously (both hold read lock)."""
    store = FakeSyncStorage()
    act1 = _FINISHED / "seq1" / "exp1" / "act1" / "20240101T120000_u1-act.yml"
    act2 = _FINISHED / "seq1" / "exp1" / "act2" / "20240101T120001_u2-act.yml"
    store.add_yml(act1)
    store.add_yml(act2)
    engine = SyncEngine(store, _config())

    order = []

    async def run():
        async def sync_act(path):
            yml = HelaoYml(path)
            job = SyncJob(yml=yml, progress=Progress.from_dict({}), priority=0)
            order.append(f"start:{path.parent.name}")
            await engine.sync_one(job)
            order.append(f"done:{path.parent.name}")

        await asyncio.gather(sync_act(act1), sync_act(act2))

    asyncio.run(run())
    # Both started before either finished (concurrent execution)
    assert order.index("start:act1") < order.index("done:act2")
    assert order.index("start:act2") < order.index("done:act1")
    assert len(store.moved) == 2


# ── get_progress ──────────────────────────────────────────────────────────────

def test_get_progress_returns_progress():
    store = FakeSyncStorage()
    act_path = _act_path()
    prg_path = HelaoYml(act_path).prg_path
    store._prgs[prg_path] = {"s3": True, "api": False, "yml": str(act_path)}
    engine = SyncEngine(store, _config())
    p = engine.get_progress(act_path)
    assert p.s3_done is True


def test_get_progress_caches_on_second_call():
    store = FakeSyncStorage()
    act_path = _act_path()
    prg_path = HelaoYml(act_path).prg_path
    store._prgs[prg_path] = {"s3": False, "api": False}
    engine = SyncEngine(store, _config())
    p1 = engine.get_progress(act_path)
    p2 = engine.get_progress(act_path)
    assert p1 is p2


# ── reset_sync ────────────────────────────────────────────────────────────────

def test_reset_sync_moves_synced_to_finished():
    store = FakeSyncStorage()
    synced_dir = _SYNCED / "seq1" / "exp1" / "act1"
    store.add_yml(synced_dir / "20240101T120000_uuid-act.yml")
    engine = SyncEngine(store, _config())
    result = engine.reset_sync(synced_dir)
    assert result is True
    assert len(store.moved) == 1
    src, dst = store.moved[0]
    assert "RUNS_SYNCED" in str(src)
    assert "RUNS_FINISHED" in str(dst)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
conda run -n helao python -m pytest helao/framework/tests/test_sync_logic.py -v
```

Expected: `ModuleNotFoundError: No module named 'helao.framework.domain.sync.sync_logic'`

- [ ] **Step 3: Create `domain/sync/sync_logic.py`**

```python
"""SyncEngine: stateful sync coordinator injected with SyncStorage."""
import asyncio
import json
from pathlib import Path

from helao.framework.domain.sync.sync_models import HelaoYml, Progress, SyncJob
from helao.framework.ports.sync_storage import SyncStorage
from helao.framework.support.async_utils import AsyncRWLock


class SyncEngine:
    """Orchestrates RUNS_FINISHED → RUNS_SYNCED moves for one server root.

    Injected with a SyncStorage at construction; owns per-sequence AsyncRWLock
    instances and a Progress cache. All filesystem I/O goes through the port.
    """

    def __init__(self, storage: SyncStorage, config: dict) -> None:
        """
        config keys:
          use_s3 (bool): enable cloud upload (default False)
          s3_prefix (str): S3 key prefix
          runs_finished_root (Path): RUNS_FINISHED root directory
          runs_synced_root (Path): RUNS_SYNCED root directory
        """
        self.storage = storage
        self.config = config
        self._seq_locks: dict[str, AsyncRWLock] = {}
        self._progress_cache: dict[str, Progress] = {}

    # ── private helpers ───────────────────────────────────────────────────

    def _get_seq_lock(self, seq_key: str) -> AsyncRWLock:
        if seq_key not in self._seq_locks:
            self._seq_locks[seq_key] = AsyncRWLock()
        return self._seq_locks[seq_key]

    def _seq_key(self, yml: HelaoYml) -> str:
        """First directory component after the RUNS_* dir (the sequence folder name)."""
        parts = list(yml.path.parts)
        for i, part in enumerate(parts):
            if part.startswith("RUNS_"):
                return parts[i + 1] if i + 1 < len(parts) else str(yml.path)
        return str(yml.path)

    def _make_job(self, yml_path: Path) -> SyncJob:
        yml = HelaoYml(yml_path)
        prg_dict = self.storage.read_prg(yml.prg_path)
        progress = Progress.from_dict(prg_dict)
        priority = {"action": 0, "experiment": 1, "sequence": 2}.get(yml.type, 0)
        return SyncJob(yml=yml, progress=progress, priority=priority)

    # ── discovery ─────────────────────────────────────────────────────────

    def list_pending(self, omit_manual: bool = True) -> list[SyncJob]:
        """Return SyncJobs for all *-seq.yml files under runs_finished_root."""
        root = Path(self.config["runs_finished_root"])
        paths = [p for p in self.storage.list_ymls(root) if p.stem.endswith("-seq")]
        if omit_manual:
            paths = [p for p in paths if "manual_orch_seq" not in str(p)]
        return sorted(self._make_job(p) for p in paths)

    def list_pending_acts(self, omit_manual: bool = True) -> list[SyncJob]:
        """Return SyncJobs for all *-act.yml files under runs_finished_root."""
        root = Path(self.config["runs_finished_root"])
        paths = [p for p in self.storage.list_ymls(root) if p.stem.endswith("-act")]
        if omit_manual:
            paths = [p for p in paths if "manual_orch_seq" not in str(p)]
        return sorted(self._make_job(p) for p in paths)

    def list_pending_exps(self, omit_manual: bool = True) -> list[SyncJob]:
        """Return SyncJobs for all *-exp.yml files under runs_finished_root."""
        root = Path(self.config["runs_finished_root"])
        paths = [p for p in self.storage.list_ymls(root) if p.stem.endswith("-exp")]
        if omit_manual:
            paths = [p for p in paths if "manual_orch_seq" not in str(p)]
        return sorted(self._make_job(p) for p in paths)

    # ── progress cache ────────────────────────────────────────────────────

    def get_progress(self, yml_path: Path) -> Progress:
        """Return Progress for yml_path; read from storage on first call, then cache."""
        key = yml_path.name
        if key not in self._progress_cache:
            prg_dict = self.storage.read_prg(HelaoYml(yml_path).prg_path)
            self._progress_cache[key] = Progress.from_dict(prg_dict)
        return self._progress_cache[key]

    # ── core sync ─────────────────────────────────────────────────────────

    async def sync_one(self, job: SyncJob) -> SyncJob:
        """Sync one yml: (upload if use_s3) → move_tree → (zip if seq) → write_prg."""
        seq_key = self._seq_key(job.yml)
        lock = self._get_seq_lock(seq_key)
        is_seq = job.yml.type == "sequence"
        lock_ctx = lock.write_locked() if is_seq else lock.read_locked()

        async with lock_ctx:
            new_s3_done = job.progress.s3_done
            if self.config.get("use_s3", False):
                yml_meta = self.storage.read_yml(job.yml.path)
                s3_prefix = self.config.get("s3_prefix", "")
                s3_key = f"{s3_prefix}/{job.yml.relative_path}"
                self.storage.upload_bytes(
                    json.dumps(yml_meta).encode(),
                    s3_key,
                    "application/json",
                )
                new_s3_done = True

            src_dir = job.yml.path.parent
            dst_dir = job.yml.synced_path.parent
            self.storage.move_tree(src_dir, dst_dir)

            if is_seq:
                self.storage.zip_dir(dst_dir)

            new_progress = Progress(
                s3_done=new_s3_done,
                api_done=job.progress.api_done,
                proc_states=job.progress.proc_states,
            )
            self.storage.write_prg(
                job.yml.prg_path,
                new_progress.to_dict(str(job.yml.path)),
            )
            self._progress_cache.pop(job.yml.path.name, None)

        return SyncJob(yml=job.yml, progress=new_progress, priority=job.priority)

    async def update_process(self, act_job: SyncJob) -> SyncJob:
        """Patch process records after an action syncs. No-op in SP6 scope."""
        return act_job

    # ── state management ──────────────────────────────────────────────────

    def reset_sync(self, sync_path: Path) -> bool:
        """Revert a directory from RUNS_SYNCED back to RUNS_FINISHED."""
        try:
            finished_path = Path(str(sync_path).replace("RUNS_SYNCED", "RUNS_FINISHED"))
            self.storage.move_tree(sync_path, finished_path)
            for prg in self.storage.list_files(sync_path, "*.prg"):
                self.storage.remove_prg(prg)
            return True
        except Exception:
            return False

    def unsync_dir(self, sync_dir: Path) -> None:
        """Revert all ymls under sync_dir to RUNS_FINISHED."""
        for yml_path in self.storage.list_ymls(sync_dir):
            self.reset_sync(yml_path.parent)

    def cleanup_root(self, root: Path) -> None:
        """Remove empty directories under root."""
        ymls = self.storage.list_ymls(root)
        dirs = sorted(
            {p.parent for p in ymls},
            key=lambda x: len(x.parts),
            reverse=True,
        )
        for d in dirs:
            self.storage.try_remove_empty(d)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
conda run -n helao python -m pytest helao/framework/tests/test_sync_logic.py -v
```

Expected: all tests pass

- [ ] **Step 5: Verify boundary gate still passes (domain/sync must not import I/O libs)**

```bash
conda run -n helao python -m pytest helao/framework/tests/test_boundaries.py -v
```

Expected: PASSED

- [ ] **Step 6: Commit**

```bash
git add helao/framework/domain/sync/sync_logic.py helao/framework/tests/test_sync_logic.py
git commit -m "feat(framework): SP6 wave 2 — SyncEngine domain class"
```

---

## Task 6: `FsSyncStorage` + `S3SyncStorage` stub

> Depends on Task 3 (SyncStorage Protocol) being complete.

**Files:**
- Create: `helao/framework/adapters/fs_sync_storage.py`
- Create: `helao/framework/adapters/s3_sync_storage.py`
- Test: `helao/framework/tests/test_fs_sync_storage.py`

- [ ] **Step 1: Write the failing test**

```python
# helao/framework/tests/test_fs_sync_storage.py
import json
from pathlib import Path
from zipfile import ZipFile
import pytest
from helao.framework.adapters.fs_sync_storage import FsSyncStorage
from helao.framework.adapters.s3_sync_storage import S3SyncStorage


# ── FsSyncStorage ─────────────────────────────────────────────────────────────

def test_write_read_yml_round_trip(tmp_path):
    store = FsSyncStorage()
    path = tmp_path / "test-seq.yml"
    data = {"key": "value", "number": 42}
    store.write_yml(path, data)
    loaded = store.read_yml(path)
    assert loaded["key"] == "value"
    assert loaded["number"] == 42


def test_write_read_prg_round_trip(tmp_path):
    store = FsSyncStorage()
    path = tmp_path / "test.prg"
    data = {"s3": True, "api": False, "yml": "/some/path.yml"}
    store.write_prg(path, data)
    assert store.read_prg(path) == data


def test_read_prg_missing_returns_empty(tmp_path):
    store = FsSyncStorage()
    assert store.read_prg(tmp_path / "nonexistent.prg") == {}


def test_remove_prg_deletes_file(tmp_path):
    store = FsSyncStorage()
    path = tmp_path / "test.prg"
    store.write_prg(path, {"s3": False})
    store.remove_prg(path)
    assert not path.exists()


def test_remove_prg_missing_is_noop(tmp_path):
    store = FsSyncStorage()
    store.remove_prg(tmp_path / "no.prg")  # must not raise


def test_move_tree_transfers_contents(tmp_path):
    src = tmp_path / "RUNS_FINISHED" / "seq1"
    src.mkdir(parents=True)
    (src / "test-act.yml").write_text("key: value")
    dst = tmp_path / "RUNS_SYNCED" / "seq1"
    store = FsSyncStorage()
    result = store.move_tree(src, dst)
    assert result == dst
    assert not src.exists()
    assert (dst / "test-act.yml").exists()


def test_zip_dir_creates_archive_and_removes_source(tmp_path):
    target = tmp_path / "seq_dir"
    target.mkdir()
    (target / "a.yml").write_text("hello")
    (target / "b.hlo").write_text("data")
    store = FsSyncStorage()
    zip_path = store.zip_dir(target)
    assert zip_path.exists()
    assert zip_path.suffix == ".zip"
    assert not target.exists()
    with ZipFile(zip_path) as zf:
        names = zf.namelist()
    assert any("a.yml" in n for n in names)
    assert any("b.hlo" in n for n in names)


def test_zip_dir_skips_lock_files(tmp_path):
    target = tmp_path / "seq_dir"
    target.mkdir()
    (target / "data.hlo").write_text("x")
    (target / "data.hlo.lock").write_text("locked")
    store = FsSyncStorage()
    zip_path = store.zip_dir(target)
    with ZipFile(zip_path) as zf:
        names = zf.namelist()
    assert not any(".lock" in n for n in names)


def test_list_ymls_finds_nested_ymls(tmp_path):
    root = tmp_path / "RUNS_FINISHED"
    (root / "seq1" / "exp1").mkdir(parents=True)
    (root / "seq1" / "test-seq.yml").touch()
    (root / "seq1" / "exp1" / "test-act.yml").touch()
    store = FsSyncStorage()
    ymls = store.list_ymls(root)
    assert len(ymls) == 2


def test_list_files_with_pattern(tmp_path):
    d = tmp_path / "dir"
    d.mkdir()
    (d / "a.hlo").touch()
    (d / "b.yml").touch()
    store = FsSyncStorage()
    hlos = store.list_files(d, "*.hlo")
    assert len(hlos) == 1
    assert hlos[0].name == "a.hlo"


def test_try_remove_empty_removes_empty_dir(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    store = FsSyncStorage()
    assert store.try_remove_empty(empty) is True
    assert not empty.exists()


def test_try_remove_empty_returns_false_for_nonempty(tmp_path):
    nonempty = tmp_path / "full"
    nonempty.mkdir()
    (nonempty / "f.txt").write_text("x")
    store = FsSyncStorage()
    assert store.try_remove_empty(nonempty) is False
    assert nonempty.exists()


def test_upload_stubs_return_correct_values(tmp_path):
    store = FsSyncStorage()
    f = tmp_path / "f.txt"
    f.write_text("x")
    assert store.upload_file(f, "key/f.txt") is True
    assert store.upload_bytes(b"data", "key/data") is True
    assert store.key_exists("key/f.txt") is False


# ── S3SyncStorage stub ────────────────────────────────────────────────────────

def test_s3_upload_file_raises_not_implemented(tmp_path):
    store = S3SyncStorage()
    f = tmp_path / "f.txt"
    f.write_text("x")
    with pytest.raises(NotImplementedError):
        store.upload_file(f, "bucket/key")


def test_s3_upload_bytes_raises_not_implemented():
    store = S3SyncStorage()
    with pytest.raises(NotImplementedError):
        store.upload_bytes(b"data", "bucket/key")


def test_s3_key_exists_raises_not_implemented():
    store = S3SyncStorage()
    with pytest.raises(NotImplementedError):
        store.key_exists("bucket/key")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
conda run -n helao python -m pytest helao/framework/tests/test_fs_sync_storage.py -v
```

Expected: `ModuleNotFoundError: No module named 'helao.framework.adapters.fs_sync_storage'`

- [ ] **Step 3: Create `adapters/fs_sync_storage.py`**

```python
"""FsSyncStorage: real filesystem implementation of SyncStorage."""
import json
import os
import shutil
import zipfile
from pathlib import Path

from ruamel.yaml import YAML

from helao.framework.ports.sync_storage import SyncStorage

_yaml = YAML(typ="rt")
_yaml.indent(mapping=2, sequence=4, offset=2)
_yaml.allow_duplicate_keys = True


def _represent_none(self, data):
    return self.represent_scalar("tag:yaml.org,2002:null", "null")


_yaml.representer.add_representer(type(None), _represent_none)


class FsSyncStorage:
    """Filesystem-backed SyncStorage. Cloud upload methods are no-op stubs."""

    # ── tree inspection ───────────────────────────────────────────────────

    def list_ymls(self, root: Path) -> list[Path]:
        return sorted(root.rglob("*.yml")) if root.exists() else []

    def list_files(self, dir_path: Path, pattern: str = "*") -> list[Path]:
        return sorted(dir_path.glob(pattern)) if dir_path.exists() else []

    # ── YAML I/O ──────────────────────────────────────────────────────────

    def read_yml(self, path: Path) -> dict:
        from io import StringIO
        with open(path, encoding="utf-8") as f:
            return dict(_yaml.load(f) or {})

    def write_yml(self, path: Path, data: dict) -> None:
        """Atomic write via temp file + os.replace (byte-identical YAML conventions)."""
        from io import StringIO
        path.parent.mkdir(parents=True, exist_ok=True)
        buf = StringIO()
        _yaml.dump(dict(data), buf)
        tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
        tmp.write_text(buf.getvalue(), encoding="utf-8")
        os.replace(tmp, path)

    # ── progress sidecar I/O ──────────────────────────────────────────────

    def read_prg(self, path: Path) -> dict:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def write_prg(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")

    def remove_prg(self, path: Path) -> None:
        path.unlink(missing_ok=True)

    # ── filesystem mutations ──────────────────────────────────────────────

    def move_tree(self, src: Path, dst: Path) -> Path:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return dst

    def zip_dir(self, path: Path) -> Path:
        """Zip path into path.with_suffix('.zip'), skip .lock files, remove source."""
        zip_path = path.with_suffix(".zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for entry in sorted(path.rglob("*")):
                if entry.suffix == ".lock":
                    continue
                if entry.is_file():
                    zf.write(entry, entry.relative_to(path.parent))
        shutil.rmtree(path)
        return zip_path

    def try_remove_empty(self, path: Path) -> bool:
        try:
            os.rmdir(path)
            return True
        except OSError:
            return False

    # ── cloud upload stubs ────────────────────────────────────────────────

    def upload_file(self, local_path: Path, s3_key: str) -> bool:
        return True

    def upload_bytes(
        self, data: bytes, s3_key: str, content_type: str = "application/json"
    ) -> bool:
        return True

    def key_exists(self, s3_key: str) -> bool:
        return False
```

- [ ] **Step 4: Create `adapters/s3_sync_storage.py`**

```python
"""S3SyncStorage stub: inherits FsSyncStorage, raises on upload methods.

Real boto3 implementation is deferred to a follow-on sub-project.
Import paths are stable: S3SyncStorage will keep this module path when
the real implementation replaces the stubs.
"""
from pathlib import Path

from helao.framework.adapters.fs_sync_storage import FsSyncStorage


class S3SyncStorage(FsSyncStorage):
    """FsSyncStorage + NotImplementedError stubs for cloud upload."""

    def upload_file(self, local_path: Path, s3_key: str) -> bool:
        raise NotImplementedError("S3 adapter deferred to follow-on SP")

    def upload_bytes(
        self, data: bytes, s3_key: str, content_type: str = "application/json"
    ) -> bool:
        raise NotImplementedError("S3 adapter deferred to follow-on SP")

    def key_exists(self, s3_key: str) -> bool:
        raise NotImplementedError("S3 adapter deferred to follow-on SP")
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
conda run -n helao python -m pytest helao/framework/tests/test_fs_sync_storage.py -v
```

Expected: all tests pass

- [ ] **Step 6: Verify SyncStorage Protocol satisfaction**

```bash
conda run -n helao python -c "
from helao.framework.ports.sync_storage import SyncStorage
from helao.framework.adapters.fs_sync_storage import FsSyncStorage
from helao.framework.adapters.s3_sync_storage import S3SyncStorage
assert isinstance(FsSyncStorage(), SyncStorage)
assert isinstance(S3SyncStorage(), SyncStorage)
print('OK')
"
```

Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add helao/framework/adapters/fs_sync_storage.py helao/framework/adapters/s3_sync_storage.py helao/framework/tests/test_fs_sync_storage.py
git commit -m "feat(framework): SP6 wave 2 — FsSyncStorage adapter + S3 stub"
```

---

## Task 7: Boundary check update + full gate

> Depends on all previous tasks.

**Files:**
- Modify: `helao/framework/_devtools/boundary_check.py`

- [ ] **Step 1: Add I/O libs to `DOMAIN_FORBIDDEN`**

In `helao/framework/_devtools/boundary_check.py`, update `DOMAIN_FORBIDDEN`:

```python
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
    "boto3",
    "shutil",
    "ruamel",
    "helao.framework.adapters",
    "helao.framework.app",
}
```

- [ ] **Step 2: Run boundary test to verify domain/sync is clean**

```bash
conda run -n helao python -m pytest helao/framework/tests/test_boundaries.py -v
```

Expected: PASSED (domain/sync/ files must not import boto3, shutil, ruamel)

- [ ] **Step 3: Run the full test suite**

```bash
conda run -n helao python -m pytest helao/framework/tests/ -v --tb=short 2>&1 | tail -30
```

Expected: all tests pass, coverage gate passes

- [ ] **Step 4: Commit**

```bash
git add helao/framework/_devtools/boundary_check.py
git commit -m "feat(framework): SP6 wave 3 — tighten DOMAIN_FORBIDDEN + full gate"
```

---

## Task 8: Final commit — SP6 golden master

> Run after Task 7 completes clean.

- [ ] **Step 1: Run full test suite with coverage**

```bash
conda run -n helao python -m pytest helao/framework/tests/ -v --cov=helao/framework --cov-report=json 2>&1 | tail -20
```

Expected: all tests pass, domain+models+support coverage ≥ 95%

- [ ] **Step 2: Verify `domain/sync/` is in coverage output**

```bash
conda run -n helao python -m pytest helao/framework/tests/ --cov=helao/framework --cov-report=term-missing 2>&1 | grep "domain/sync"
```

Expected: lines for `sync_models.py` and `sync_logic.py` showing high coverage

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "feat(framework): SP6 wave 3 — app driver, loaders, golden master"
```
