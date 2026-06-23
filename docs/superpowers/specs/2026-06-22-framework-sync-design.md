# SP6: Data Sync — Design Spec

**Date:** 2026-06-22  
**Branch:** `feat/framework-scaffold` (stacked on SP5)  
**Scope:** Port `HelaoSyncer` (`helao/core/drivers/data/sync_driver.py`, 1933 LOC) into `helao/framework/` following the hexagonal architecture established in SP1–SP5.

---

## 1. Problem

`sync_driver.py` is a 1933-LOC god class that mixes:
- Pure walk/classify/decide logic (testable, zero I/O)
- Filesystem mutations (move trees, zip dirs, read/write YAML + JSON)
- S3 upload via blocking `boto3`
- API registration via HTTP (`async_action_dispatcher`)
- Concurrency primitives (`AsyncRWLock` per sequence)
- Direct coupling to `helao.core.servers.base.Base`

The pure logic is untested and untestable as currently structured. This sub-project extracts it into the framework's hexagonal layers.

---

## 2. Locked Decisions

| Decision | Choice |
|---|---|
| Scope | Filesystem only — S3 adapter deferred to follow-on |
| Sync port | Separate `ports/sync_storage.py` (not an extension of `Storage`) |
| Domain granularity | Two files: `sync_models.py` (value objects) + `sync_logic.py` (SyncEngine) |
| Domain pattern | Stateful `SyncEngine` class injected with `SyncStorage` |
| Concurrency | `AsyncRWLock` vendored into `support/async_utils.py` |
| Byte compatibility | `RUNS_*` layout, HLO/parquet formats unchanged |
| Loaders | `adapters/loaders/hlo_loader.py` — no port needed, pure read functions |

---

## 3. Package Layout

```
helao/framework/
  domain/sync/
    __init__.py
    sync_models.py     # HelaoYml, Progress, SyncJob — pure value objects, zero I/O
    sync_logic.py      # SyncEngine — stateful, injected with SyncStorage

  ports/
    sync_storage.py    # SyncStorage Protocol

  adapters/
    fs_sync_storage.py # FsSyncStorage: real filesystem impl
    s3_sync_storage.py # S3SyncStorage: stub (NotImplementedError), boto3 dep deferred
    loaders/
      __init__.py
      hlo_loader.py    # read_hlo, hlo_to_parquet (ported from helao/helpers/hlo_data.py)

  support/
    async_utils.py     # AsyncRWLock (ported from sync_driver.py)

  tests/
    test_sync_domain.py   # pure domain tests; FakeSyncStorage in-memory
    test_fs_sync.py       # FsSyncStorage tests against tmp dirs
```

**Not in SP6:** real `S3SyncStorage`, API registration adapter, `app/` wiring (sync daemon ↔ `Base` belongs in app layer SP).

---

## 4. Component Designs

### 4.1 `domain/sync/sync_models.py`

Three pure value objects — no I/O, no filesystem calls.

**`HelaoYml`** — dataclass wrapping a single `.yml` path.

Pure computed properties:
- `type: str` — `"act"` / `"exp"` / `"seq"` parsed from filename suffix
- `timestamp: datetime` — parsed from filename
- `status: str` — `"active"` / `"finished"` / `"synced"` from parent directory name
- `active_path: Path` — sibling path under `RUNS_ACTIVE` (string substitution)
- `finished_path: Path` — sibling path under `RUNS_FINISHED`
- `synced_path: Path` — sibling path under `RUNS_SYNCED`
- `relative_path: str` — path relative to runs root
- `prg_path: Path` — `.prg` sidecar path (same dir, same stem, `.prg` suffix)

No directory listing (that goes through `SyncStorage`).

**`Progress`** — frozen dataclass holding per-yml sync state:
- `s3_done: bool`
- `api_done: bool`  
- `proc_states: dict[str, Any]` — process uuid → sync state mapping

Construction: `Progress.from_dict(d: dict)`. Serialization: `.to_dict() -> dict`. No read/write methods.

**`SyncJob`** — dataclass pairing a `HelaoYml` with its `Progress`:
- `yml: HelaoYml`
- `progress: Progress`
- `priority: int` — 0=act, 1=exp, 2=seq (actions sync before experiments before sequences)

**Module-level constants** (moved from `sync_driver.py` module scope):
- `ABR_MAP = {"act": "action", "exp": "experiment", "seq": "sequence"}`
- `MOD_MAP`, `PLURALS`, `MOD_PATCH`

### 4.2 `ports/sync_storage.py`

`SyncStorage` Protocol — all methods synchronous (S3 uploads in legacy are blocking `boto3`; async wrapping belongs in app layer).

```python
class SyncStorage(Protocol):
    # Tree inspection
    def list_ymls(self, root: Path) -> list[Path]: ...
    def list_files(self, dir_path: Path, pattern: str = "*") -> list[Path]: ...

    # YAML I/O
    def read_yml(self, path: Path) -> dict: ...
    def write_yml(self, path: Path, data: dict) -> None: ...

    # Progress sidecar I/O
    def read_prg(self, path: Path) -> dict: ...        # returns {} if missing
    def write_prg(self, path: Path, data: dict) -> None: ...
    def remove_prg(self, path: Path) -> None: ...

    # Filesystem mutations
    def move_tree(self, src: Path, dst: Path) -> Path: ...
    def zip_dir(self, path: Path) -> Path: ...
    def try_remove_empty(self, path: Path) -> bool: ...

    # Cloud upload (stubbed in FsSyncStorage; real in S3SyncStorage)
    def upload_file(self, local_path: Path, s3_key: str) -> bool: ...
    def upload_bytes(self, data: bytes, s3_key: str, content_type: str) -> bool: ...
    def key_exists(self, s3_key: str) -> bool: ...
```

### 4.3 `domain/sync/sync_logic.py` — `SyncEngine`

Stateful class. Injected with `SyncStorage` + `config: dict` at construction. Owns `AsyncRWLock` dict (one per sequence key) and progress cache.

**Constructor:**
```python
SyncEngine(storage: SyncStorage, config: dict)
# config keys: use_s3 (bool), s3_prefix (str),
#              runs_finished_root (Path), runs_synced_root (Path)
```

**Methods:**

| Method | Description |
|---|---|
| `list_pending(omit_manual: bool) -> list[SyncJob]` | Walk + classify + sort by priority |
| `list_pending_acts() -> list[SyncJob]` | Acts only |
| `list_pending_exps() -> list[SyncJob]` | Exps only |
| `async sync_one(job: SyncJob) -> SyncJob` | Acquire lock → upload (if use_s3) → move_tree → zip (seq only) → update prg |
| `async update_process(act_job: SyncJob) -> SyncJob` | Patch process records after action syncs |
| `get_progress(yml_path: Path) -> Progress` | Read from storage, cache |
| `reset_sync(sync_path: Path) -> bool` | Revert RUNS_SYNCED → RUNS_FINISHED |
| `unsync_dir(sync_dir: Path) -> None` | Bulk revert a directory |
| `cleanup_root(root: Path) -> None` | Remove empty dirs recursively |

**Boundary rule for `sync_one`:**
1. Acquire sequence-level `AsyncRWLock` (read lock for act/exp, write lock for seq)
2. Build upload payload (pure dict manipulation — no I/O)
3. If `config["use_s3"]`: call `storage.upload_file` / `storage.upload_bytes`
4. Call `storage.move_tree` (FINISHED → SYNCED)
5. If seq: call `storage.zip_dir`
6. Call `storage.write_prg` with updated state
7. Release lock; return updated `SyncJob`

All decision logic (what to upload, patch dict construction, process update rules) is in the method body — no I/O leaks into decision code.

### 4.4 `adapters/fs_sync_storage.py` — `FsSyncStorage`

| Method | Implementation |
|---|---|
| `list_ymls(root)` | `glob("**/*.yml", recursive=True)` |
| `list_files(dir, pattern)` | `glob(pattern)` in dir |
| `read_yml(path)` | `ruamel.yaml` load (matches `yml_load` conventions) |
| `write_yml(path, data)` | atomic temp-file + `os.replace` with `yml_dumps` formatting |
| `read_prg(path)` | `json.loads`; returns `{}` if file missing |
| `write_prg(path, data)` | `json.dump` |
| `remove_prg(path)` | `path.unlink(missing_ok=True)` |
| `move_tree(src, dst)` | `shutil.move`; creates dst parents |
| `zip_dir(path)` | `ZipFile` walk (matches legacy `zip_dir` from `file_utils`) |
| `try_remove_empty(path)` | `os.rmdir` in try/except |
| `upload_file` / `upload_bytes` | return `True` (no-op stubs) |
| `key_exists` | return `False` (no-op stub) |

### 4.5 `adapters/s3_sync_storage.py` — `S3SyncStorage` (stub)

Inherits `FsSyncStorage`. Overrides upload methods with `raise NotImplementedError("S3 adapter deferred to follow-on SP")`. Class exists so import paths are stable when S3 is implemented.

### 4.6 `adapters/loaders/hlo_loader.py`

Direct port of `read_hlo` and `hlo_to_parquet` from `helao/helpers/hlo_data.py`. No Protocol needed — these are pure read functions consumed by downstream analysis, not injected into domain. Dependencies: `pandas`, `pyarrow` (already in env).

### 4.7 `support/async_utils.py`

Direct port of `AsyncRWLock` (~35 LOC) from `sync_driver.py`. No logic changes. Exported from `support/__init__.py`.

---

## 5. Tests

### `tests/test_sync_domain.py`

Pure domain — no filesystem. Uses `FakeSyncStorage` (in-memory dict for yml/prg content, call log for `move_tree`/`zip_dir`).

Coverage:
- `HelaoYml` path computation (active/finished/synced siblings for each type)
- `HelaoYml.prg_path` derivation
- `Progress.from_dict` / `to_dict` round-trip
- `SyncJob` priority ordering (act < exp < seq)
- `SyncEngine.list_pending()` with mixed fake tree (some finished, some synced)
- `SyncEngine.sync_one()` with `use_s3=False` — verifies `move_tree` called, prg updated, `zip_dir` called for seq only
- `SyncEngine.sync_one()` lock behavior — concurrent act syncs do not block each other; seq sync blocks acts
- `SyncEngine.reset_sync()` — tree reverted, prg removed
- `SyncEngine.get_progress()` — cache hit after first read

### `tests/test_fs_sync.py`

Real tmp dirs (pytest `tmp_path` fixture). `FsSyncStorage` under test.

Coverage:
- `write_yml` → `read_yml` round-trip: YAML byte conventions preserved
- `write_prg` → `read_prg` round-trip
- `read_prg` on missing file returns `{}`
- `move_tree`: src disappears, dst appears at correct relative path
- `zip_dir`: zip created, contains expected files
- `try_remove_empty`: empty dir removed, non-empty dir preserved

### Architectural gate (`tests/test_framework_gate.py`)

Extend existing AST import check to include `domain/sync/sync_models.py` and `domain/sync/sync_logic.py`. Verified forbidden imports: `os`, `pathlib`, `boto3`, `aiofiles`, `shutil`, `ruamel`, `json`, `asyncio` (except `asyncio` in `sync_logic.py` for lock acquisition — add explicit allowlist entry for `asyncio` in `sync_logic` only).

---

## 6. Boundaries Summary

| Layer | May import | May NOT import |
|---|---|---|
| `domain/sync/` | `models/`, `ports/`, `support/async_utils` | FastAPI, httpx, filesystem libs, boto3, Bokeh, `adapters/` |
| `adapters/fs_sync_storage.py` | `ports/sync_storage`, I/O libs | `domain/` |
| `adapters/loaders/` | I/O libs, pandas | `domain/` |
| `support/async_utils.py` | `asyncio` only | everything else in framework |

---

## 7. Migration Note

`HelaoSyncer` in `helao/core/` remains untouched. The new `SyncEngine` is the strangler-fig replacement. Deployment migration (wiring `SyncEngine` into `Base`/`HelaoSyncer`) is a follow-on app-layer sub-project (SP7+).
