# SP6: Data Sync — Design Spec (Opus redo)

**Date:** 2026-06-23
**Branch:** `feat/framework-scaffold` (stacked on SP5, commit `9952cf51`)
**Scope:** Port `HelaoSyncer` / `SyncDriver` (`helao/core/drivers/data/sync_driver.py`, 1933 LOC) into `helao/framework/` under the hexagonal architecture established in SP1–SP5.

> Supersedes the Sonnet-era `2026-06-22-framework-sync-design.md` (reachable at tag `sp6-sp8-sonnet-ref`). That spec is a useful reference but proposed a **stateful `SyncEngine` that performs I/O inside its own methods** (`sync_one` calls `storage.upload`/`move_tree`). That violates the pure-domain/command pattern SP4 (`action_lifecycle`) and SP5 (`orchestration.step`) established. This redo keeps **domain pure** (decision functions, zero I/O) and puts the imperative pipeline in `app/`.

---

## 1. Problem

`sync_driver.py` is a 1933-LOC module mixing seven responsibilities:

1. **Pure path/status math** — yml type/timestamp/status parsing, `RUNS_ACTIVE`/`RUNS_FINISHED`/`RUNS_SYNCED` path rewriting, lock-key derivation (`_node_keys`, `_rel_under_runs`).
2. **Pure sync-decision logic** — the `sync_yml` state machine (lines 1027–1106): skip if missing/already-synced, soft-block if still active, re-queue children-then-self if children unsynced, else proceed. Topological-order rank logic.
3. **Pure process-folding** — `update_process` (lines 1354–1502): legacy-vs-modern process-group lookup, process-meta construction, `process_contrib` merging, sample dedup.
4. **Filesystem mutation** — move trees FINISHED→SYNCED, zip sequences, read/write yml + `.prg` sidecars, cleanup empty dirs.
5. **Cloud upload** — blocking `boto3` S3 upload (`to_s3`), with gzip + retry.
6. **API registration** — `to_api` (currently a no-op stub in live code).
7. **Async concurrency** — per-sequence `AsyncRWLock`, per-experiment `asyncio.Lock`, a `PriorityQueue` + worker coroutine (`syncer`), task tracking.

The pure logic (1, 2, 3) is the highest-value, currently-untestable code. This SP extracts it into `domain/sync/`, behind two ports, with the imperative pipeline + concurrency in `app/sync_driver.py`.

---

## 2. Locked Decisions

| # | Decision | Choice | Rationale |
|---|---|---|---|
| D1 | Domain shape | **Pure functions + value objects**, no I/O, no async | Matches SP4/SP5; the map flagged the Sonnet `SyncEngine` as the hexagonal smell |
| D2 | Where the pipeline lives | `app/sync_driver.py` (async), like `app/orch_api.py` is to SP5's FSM | I/O + asyncio at the edge |
| D3 | Ports | **Two**: `ports/sync_storage.py` (local fs tree ops) + `ports/cloud_sink.py` (S3 upload + API register) | Local-fs movement and cloud egress are distinct concerns with distinct adapters |
| D4 | S3 | **Real adapter included** (`boto3` is in env), gated by config exactly like legacy | Master design §4.7 puts S3/fs adapters in SP6 scope; legacy no-ops when unconfigured → `NoopCloudSink` |
| D5 | API register | Port method exists; `S3CloudSink.register_api` ports legacy `to_api` **faithfully (no-op return True)** with a documented TODO | Live `to_api` never completed the POST; we do not invent new external behavior |
| D6 | AsyncRWLock | Vendored verbatim into `support/async_utils.py` | ~35 LOC, no logic change; used by app layer only |
| D7 | Loaders | `adapters/loaders/hlo_loader.py` — pure `read_hlo`/`hlo_to_parquet`, no port | Consumed by the pipeline, not injected into domain |
| D8 | Byte compatibility | `RUNS_*` layout, yml filenames, `.prg` schema, HLO/parquet, zip layout **unchanged** | Historical data + live `HelaoSyncer` + downstream analysis depend on them |
| D9 | Legacy untouched | `helao/core/drivers/data/sync_driver.py` is **not modified** | Strangler-fig; deployment cut-over is a later app-layer SP |
| D10 | Gate | `domain/sync/` scanned by existing AST boundary check; **no new forbidden entries** | Domain uses only `pathlib.PurePosixPath`/`datetime`/`dataclasses`/`json`/stdlib — all pure; no `asyncio`, no adapters |

---

## 3. Package Layout

```
helao/framework/
  domain/sync/
    __init__.py
    paths.py          # pure path/status math (PurePosixPath only)
    progress.py       # Progress value object: schema, predicates, push-conditions
    decide.py         # sync-decision FSM + file-list build + metadata patch
    process_fold.py   # update_process pure logic (group lookup, meta build, contrib merge, sample dedup)

  ports/
    sync_storage.py   # SyncStorage Protocol — local fs tree ops
    cloud_sink.py     # CloudSink Protocol — S3 upload + API register

  adapters/
    fs_sync_storage.py   # FsSyncStorage: real filesystem, byte-compatible
    noop_cloud_sink.py   # NoopCloudSink: returns True (unconfigured / use_s3=False)
    s3_cloud_sink.py     # S3CloudSink: boto3 upload (ported to_s3) + register_api stub
    loaders/
      __init__.py
      hlo_loader.py      # read_hlo, hlo_to_parquet (ported from helao/helpers/hlo_data.py)

  support/
    async_utils.py    # AsyncRWLock (verbatim port)

  app/
    sync_driver.py    # SyncDriver: PriorityQueue + AsyncRWLock hierarchy + syncer loop;
                      # calls domain deciders, executes via ports

  tests/
    test_domain_sync_paths.py
    test_domain_sync_progress.py
    test_domain_sync_decide.py
    test_domain_sync_process_fold.py
    test_ports_sync_storage.py
    test_ports_cloud_sink.py
    test_support_async_utils.py
    test_adapters_fs_sync_storage.py
    test_adapters_cloud_sink.py
    test_adapters_hlo_loader.py
    test_app_sync_driver.py
    test_golden_master_sync.py
```

**Not in SP6:** wiring `SyncDriver` into a running action server / `Base` (that is `HelaoSyncer.__init__`'s job — deferred to the deployment-migration SP); real `register_api` HTTP POST (legacy never finished it).

---

## 4. Component Designs

### 4.1 `domain/sync/paths.py` — pure path & status math

All functions take/return `PurePosixPath` or `str`; **no disk access**. Ported from `HelaoYml` properties + module funcs.

```python
RUNS = ("RUNS_ACTIVE", "RUNS_FINISHED", "RUNS_SYNCED")
ABR_MAP = {"act": "action", "exp": "experiment", "seq": "sequence"}

def node_type(yml_name: str) -> str        # "act"|"exp"|"seq" from filename suffix
def node_timestamp(yml_name: str) -> datetime
def status_of(parts: Sequence[str]) -> str # "active"|"finished"|"synced"
def status_idx(parts: Sequence[str]) -> int
def rename_status(path, new_status) -> PurePosixPath          # generalizes HelaoYml.rename
def active_path/finished_path/synced_path(path) -> PurePosixPath
def relative_under_runs(path) -> str | None                  # = _rel_under_runs
def compute_synced_path(path) -> PurePosixPath               # = move_to_synced path math
def compute_finished_path(path) -> PurePosixPath             # = revert_to_finished path math
def node_keys(yml_path) -> tuple[str|None, str|None]         # = _node_keys (seq_key, exp_key)
def prg_path(yml_path) -> PurePosixPath                      # .prg sidecar
```

Exhaustively unit-tested against the three tree variants × three node types.

### 4.2 `domain/sync/progress.py` — `Progress` value object

Pure dataclass + constructors; **no `read_dict`/`write_dict`** (those become storage calls in `app`).

```python
@dataclass
class Progress:
    yml_relpath: str
    dict_: dict          # the .prg payload (schema byte-identical to legacy)

    @classmethod
    def initial(cls, yml_relpath, node_type, meta) -> "Progress"   # = make_progress_dict
    @classmethod
    def from_dict(cls, yml_relpath, d) -> "Progress"
    def to_dict(self) -> dict

    @property
    def s3_done(self) -> bool
    @property
    def api_done(self) -> bool
    def list_unfinished_procs(self) -> tuple[list, list]           # legacy semantics

    def with_s3_done(self, ...) -> "Progress"   # functional updates (return new)
    def with_api_done(self, ...) -> "Progress"
```

Plus pure push-condition predicate:
```python
def should_push_process(pidx, process_groups, process_actions_done,
                        is_legacy, finisher_idxs, force) -> bool   # = sync_process gate
```

### 4.3 `domain/sync/decide.py` — sync-decision FSM

The pure core of `sync_yml` lines 1027–1106, expressed as a tagged decision (mirrors SP5 `OrchDecision`):

```python
class SyncAction(str, Enum):
    SKIP = "skip"                  # missing or already synced -> drop
    SOFT_BLOCK = "soft_block"      # still active -> do not sync yet
    REQUEUE_CHILDREN = "requeue"   # children unsynced -> enqueue children (rank-1) + self (rank-2)
    PROCEED = "proceed"            # ready to upload/move

@dataclass(frozen=True)
class SyncDecision:
    action: SyncAction
    requeue: list[RequeueItem] = ()   # (relpath, rank) pairs when REQUEUE_CHILDREN

def decide_sync(*, exists: bool, node_status: str,
                child_statuses: Sequence[tuple[str, str]],  # (relpath, status)
                already_synced: bool, rank: int) -> SyncDecision
```

Plus the other pure slices of the pipeline:
```python
def build_upload_file_list(pending, s3_dict, hlo_files, misc_files) -> list[str]
def patch_metadata(meta, node_type, technique_patch) -> dict
def hlo_upload_plan(file_size, is_hlo, threshold=1_000_000_000) -> "hlo"|"parquet"
```

### 4.4 `domain/sync/process_fold.py` — `update_process` pure logic

The complex legacy-vs-modern folding (lines 1354–1502), as pure functions over dicts:

```python
def find_process_group_index(action_order, process_groups, is_legacy, finisher_idxs) -> int
def make_process_meta(exp_meta, process_list, pidx, action_meta) -> dict
def merge_process_contrib(process_meta, action_meta, contrib_keys) -> dict
def deduplicate_samples(sample_list, dispatched_actions_abbr, is_input: bool) -> list[dict]
def fold_action_into_process(exp_meta, prog_dict, act_meta) -> dict   # top-level composition
```

No `Progress` I/O — caller (`app`) reads the prg, calls `fold_action_into_process`, writes back.

### 4.5 `ports/sync_storage.py` — `SyncStorage` Protocol (local fs)

Synchronous tree inspection + mutation. `runtime_checkable`.

```python
class SyncStorage(Protocol):
    # inspection
    def exists(self, path: Path) -> bool: ...
    def list_pending(self, finished_root: Path, kind: str, omit_manual: bool) -> list[Path]: ...
    def list_children(self, parent_dir: Path) -> list[Path]: ...     # */*.yml one level down
    def hlo_files(self, dir_: Path) -> list[Path]: ...
    def misc_files(self, dir_: Path, node_type: str) -> list[Path]: ...
    def lock_files(self, dir_: Path) -> list[Path]: ...
    def file_size(self, path: Path) -> int: ...
    # yml + prg
    def read_yml(self, path: Path) -> dict: ...
    def write_yml(self, path: Path, data: dict) -> None: ...
    def read_prg(self, path: Path) -> dict: ...      # {} if missing
    def write_prg(self, path: Path, data: dict) -> None: ...
    def remove_prg(self, path: Path) -> None: ...
    # mutation
    def move_to_synced(self, path: Path) -> Path: ...
    def revert_to_finished(self, path: Path) -> Path: ...
    def move_tree(self, src: Path, dst: Path) -> Path: ...
    def zip_dir(self, path: Path) -> Path: ...
    def cleanup_empty(self, path: Path) -> bool: ...
    def remove(self, path: Path) -> None: ...
```

### 4.6 `ports/cloud_sink.py` — `CloudSink` Protocol (egress)

Async (legacy `to_s3`/`to_api` are async; boto3 wrapped in `to_thread`).

```python
class CloudSink(Protocol):
    async def upload_bytes(self, data: bytes, key: str,
                           content_type: str = "application/json",
                           compress: bool = False) -> bool: ...
    async def upload_file(self, local_path: Path, key: str) -> bool: ...
    def key_exists(self, key: str) -> bool: ...
    async def register_api(self, req_model: dict, meta_type: str, retries: int = 5) -> bool: ...
```

### 4.7 Adapters

- **`FsSyncStorage`** — real filesystem. `move_to_synced`/`revert_to_finished` delegate path math to `domain.sync.paths` then `shutil.move`. `zip_dir` reuses `support`/`helao.helpers.file_utils` zip conventions. YAML via `support/yml_tools`. Byte-identical to legacy outputs.
- **`NoopCloudSink`** — `upload_*` / `register_api` return `True`; `key_exists` returns `False`. Used when `use_s3` is false or S3 unconfigured (legacy no-op behavior).
- **`S3CloudSink`** — ports `to_s3` (boto3 `Session`→`client('s3')`, `dict2json`, optional gzip, 30s retry via `asyncio.to_thread`). `register_api` ports `to_api` faithfully (returns `True`, documented TODO — legacy never POSTs). Constructed from an aws-config dict (pure `load_aws_config` merge extracted as a helper).
- **`adapters/loaders/hlo_loader.py`** — `read_hlo`, `hlo_to_parquet` ported from `helao/helpers/hlo_data.py` (pandas/pyarrow).

### 4.8 `support/async_utils.py` — `AsyncRWLock`

Verbatim port (lines 154–196). Reader-preferring. Exported from `support/__init__.py`.

### 4.9 `app/sync_driver.py` — `SyncDriver` (async orchestration)

The imperative engine, analogous to `app/orch_api.py`. Constructed with `(sync_storage: SyncStorage, cloud_sink: CloudSink, config: dict, helaodirs)`.

Responsibilities (thin glue; every *decision* delegates to `domain/sync`):
- `PriorityQueue` + N `syncer()` worker coroutines + task tracking (`sync_exit_callback`).
- `AsyncRWLock` per sequence + `asyncio.Lock` per experiment; `_acquire_hierarchy_locks` (lock *keys* from `domain.paths.node_keys`).
- `enqueue_yml` (rank-floor dedup — pure guard in domain, queue op here).
- `sync_yml` pipeline: `decide_sync(...)` → on `PROCEED`, loop `build_upload_file_list` → `cloud_sink.upload_*` → `patch_metadata` → `storage.move_to_synced` → `storage.zip_dir` (seq) → `storage.write_prg`.
- `update_process` / `sync_process`: read prg via storage → `fold_action_into_process` / `should_push_process` → upload → write prg.
- `finish_pending`, `reset_sync`, `unsync_dir`, `cleanup_root`, `get_progress`, `shutdown`.

`HelaoSyncer(action_serv)` equivalent (config extraction from server cfg, `Base` coupling) is **NOT** ported here — that is the deployment-wiring SP.

---

## 5. Tests

- **Domain (bulk, coverage gate):** `paths` (3 trees × 3 types, node_keys, prg_path), `progress` (initial/from_dict/to_dict round-trip, predicates, push-conditions), `decide` (every `SyncAction` branch incl. requeue ranks; file-list; metadata patch; hlo plan threshold), `process_fold` (legacy vs modern group lookup, meta build, contrib merge dict/list/scalar, sample dedup earliest-in/latest-out). Pure data in, command/dict out — no mocks.
- **Ports:** `runtime_checkable` Protocol conformance for `FsSyncStorage`, `NoopCloudSink`, `S3CloudSink`.
- **Adapters:** `FsSyncStorage` against `tmp_path` — yml/prg round-trip byte conventions, `move_to_synced` (src gone, dst at correct relpath), `move_tree`, `zip_dir`, `cleanup_empty`, `list_pending` glob depth. `NoopCloudSink` truthy. `S3CloudSink` with a fake boto3 client (monkeypatch) — upload payload + gzip + key; `register_api` returns True. `hlo_loader` round-trip on a tiny fixture.
- **App:** `test_app_sync_driver` with in-memory `FakeSyncStorage` + `FakeCloudSink` (call log) — full `sync_yml` happy path (upload→move→zip→prg), soft-block on active, requeue on unsynced children, lock concurrency (acts don't block each other, seq write-locks).
- **Golden master:** `test_golden_master_sync` — committed fixture RUNS tree (finished seq/exp/act + meta), run `SyncDriver.sync_yml` with `FakeCloudSink`, assert resulting synced-tree layout + `.prg` payloads match a committed golden snapshot, with cited `sync_driver.py` line mapping (legacy not run in-process — boto3/`Base` coupling too heavy, same approach as SP4/SP5).
- **Gate:** existing `test_boundaries.py` auto-scans `domain/sync/`; add an explicit assertion that `domain/sync/` is clean. No new `DOMAIN_FORBIDDEN` entries.

---

## 6. Boundaries Summary

| Layer | May import | May NOT import |
|---|---|---|
| `domain/sync/` | `models/`, `support/` (pure), stdlib (`pathlib`, `datetime`, `dataclasses`, `json`, `enum`) | fastapi/httpx/boto3/aiofiles/bokeh, `asyncio`, `adapters/`, `app/` |
| `ports/` | typing/Protocol only | implementations |
| `adapters/*` | `ports/`, I/O libs (boto3, shutil, pandas) | `domain/` |
| `support/async_utils` | `asyncio` only | rest of framework |
| `app/sync_driver` | `domain/sync`, `ports`, `support`, `asyncio` | adapters (injected, not imported) |

---

## 7. Waves

1. **Wave 1 — pure primitives + ports.** `support/async_utils.py`; `domain/sync/paths.py`; `domain/sync/progress.py`; `ports/sync_storage.py`; `ports/cloud_sink.py`. Tests for each. (3 independent worker tracks.)
2. **Wave 2 — pure decision logic.** `domain/sync/decide.py`; `domain/sync/process_fold.py`. Heavy unit tests. (2 worker tracks.)
3. **Wave 3 — adapters.** `fs_sync_storage.py`; `noop_cloud_sink.py` + `s3_cloud_sink.py`; `loaders/hlo_loader.py`. tmp_path / fake-boto3 tests. (3 worker tracks.)
4. **Wave 4 — app pipeline + golden master + gate.** `app/sync_driver.py`; `test_app_sync_driver.py`; `test_golden_master_sync.py` + fixture; gate assertion. (sequential — integrates everything.)

Run waves continuously (no inter-wave approval gate, per standing authorization). After Wave 4: full suite + boundary gate green, push to `feat/framework-scaffold`, report, update memory, prompt `/clear`.
