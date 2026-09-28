# Config-defined pre-finish and post-finish hooks — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the four unrelated finish-time mechanisms (`hlo_postprocess_libs`, `exp_/seq_postprocess_libs`, the hard-wired S3 upload, `auto_analyze_sequences`) with one `FinishHook` contract in two phases — pre-finish in the record's owning server, post-finish in SYNC — driven by config, with every existing config still working through aliases and the default post-finish chain producing byte-identical uploads to today.

**Architecture:** A new package `helao/core/hooks/` holds the contract (`FinishHook`, `PrefinishContext`, `PostfinishContext`, `HookSet`), config normalization + aliases + validation (`config.py`), a single loader that also wraps the existing `HloPostProcessor`/`MetaProcessor` classes (`loader.py`), the pre-finish runner (`prefinish.py`), the post-finish chain runner that keeps its state in the `.prg` sidecar (`postfinish.py`), and two built-in post-finish hooks (`builtin/s3_upload.py`, `builtin/dispatch_analysis.py`) that are today's `sync_yml` S3/analysis code moved verbatim. Call sites: both action finalizer twins, `orch_lifecycle.py` (both orchestrators, with the experiment `finished` emission moved after the hooks), both SYNC driver twins (parity-pinned, edited identically), and `MicroOrch` (fixed roots, hooks, `finish_yml` handoff). A golden characterization test of today's SYNC output is written and committed **before** any refactor and must stay green throughout.

**Tech Stack:** Python 3.14 in the `helao` conda env, pydantic v2 models, pytest + pytest-asyncio (hexagon/core suites), standalone `unit_test_*.py` scripts under `helao/core/tests/`, pyright (authoritative), black (with `force-exclude` for the parity-pinned twins), `inspect.getsource` parity pins (`helao/hexagon/tests/sync_fixtures.py`, `native_fixtures.py`).

**Spec:** `docs/superpowers/specs/2026-09-28-finish-hooks-design.md` (read it in full before any task; the plan argues from it). Background: `docs/superpowers/specs/2026-09-25-runs-layout-and-state-journal-design.md`, `helao/core/drivers/data/CLAUDE.md`, `helao/core/servers/CLAUDE.md`.

## Global Constraints

Every task's requirements implicitly include this section.

- **Python only via `conda run -n helao`** (Python 3.14), never the OS python. Add `--no-capture-output` for anything longer than a single test file. `conda run ... python - <<EOF` silently runs nothing — write a script file and run it.
- **`run_tests.py` runs one file per pytest process.** Never collect the whole tree in one pytest session (it hangs and ignores SIGINT). Use `conda run -n helao --no-capture-output python run_tests.py --filter <substr>` for sweeps; a single file with `conda run -n helao python -m pytest <file> -v`.
- **Standalone `helao/core/tests/unit_test_*.py` scripts are run directly**: `conda run -n helao python helao/core/tests/unit_test_orch_lifecycle.py` (exit code 0 = pass). `run_tests.py` reports them as `NOTESTS`; that is expected.
- **Run `black` on changed files immediately before every commit** — *except* the parity-pinned twins, which `pyproject.toml` `force-exclude`s: `helao/core/drivers/data/sync_driver.py`, `helao/hexagon/adapters/native/sync_driver.py`, `helao/core/servers/active_finalizer.py`, `helao/hexagon/adapters/native/finalizer.py`. Never format those by hand either; edit them minimally and identically.
- **Parity pins.** `helao/hexagon/tests/test_native_sync_pins.py` requires the legacy `sync_driver.py` region from the line `LOGGER = logging.make_logger` down to the last line of `class SyncDriver` to appear **byte-identically** inside the native twin, and forbids any `import` statement inside that region (new imports go in the import block above it, in both files). `helao/hexagon/tests/test_native_finalizer.py` pins `_finish` (and the other listed methods) of `NativeActionFinalizer` against `ActionFinalizer` per method. Every edit to a pinned member is made in the legacy file first and then copied to the native twin; the plan gives the copy command.
- **Never `git stash`.** Never commit while another agent's work may be staged. Commit only the files your task names.
- **Commit messages end with** `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **pyright is authoritative** (`conda run -n helao pyright <files>` must report 0 errors for changed files); do not remove `# type: ignore` directives. `LOGGER.alert` is installed onto `logging.Logger` by `setattr`, so every call site carries `# type: ignore[attr-defined]`.
- **Private deployments** (every `helao/deploy/*` other than `hte` and `test`) are separate git repos and must never be named in tracked parent-repo files, commit messages, or this plan. Say "private deployments". Their tests must still pass: "private deployments' tests via `run_tests.py`".
- **Logging:** `LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER` with `from helao.helpers import helao_logging as logging`. Never instantiate loggers directly.
- **Every new test must be shown to fail against the pre-change code (mutate-and-observe).** Each task states the expected failure. If a new test passes before the implementation step, STOP: the test is not falsifiable — fix the test.
- **Executors STOP and escalate on any decision this plan does not settle**, especially anything wire-visible: S3 keys, S3 bodies, `.prg` fields, meta json, `finish_yml` payloads, dispatch payloads. The default post-finish chain must produce byte-for-byte the uploads of today; the golden test in Task 1 pins that and is never weakened after Task 1.
- **Working directory is the repo root** (`/mnt/STORAGE/repos/helao/helao-async`) for every command; the loader resolves `helao/deploy/<d>/processors/` relative to it exactly as today's code does.
- **No config edits under `helao/deploy/*/configs/`**: the aliases must cover every live key (spec §9).
- Line numbers cited below were verified on 2026-09-28 at `unstable` `c3491bc0`; re-read the cited region before editing — anchors are given as code, not just numbers.

## Settled decisions the spec left open (executors follow these; do not re-decide)

| # | Question | Decision |
|---|---|---|
| A1 | `sync_process` writes the local `-prc.yml` **and** uploads the process json in one method; the spec puts "-prc.yml writing" in core and "process uploads" in `s3_upload`. | `sync_process` stays whole (it is parity-pinned as "MUST-PRESERVE") and is called from `s3_upload`. Core keeps only `reconcile_processes`. |
| A2 | The action-level `update_process` + `sync_process` runs after the `DONE` journal today and needs the patched `meta` that only the upload leg has. | It moves into `s3_upload`, after the `api` flag, guarded by `prog.s3_done and prog.api_done and type == action and meta.get("process_contrib")`. The S3 object set is unchanged; only the order relative to the journal entry changes. |
| A3 | `sync_yml`'s `force_s3` / `force_api` / `compress` / `retries` arguments are used by the moved code. | `PostfinishContext` gains `opts: dict` (keys `force_s3`, `force_api`, `compress`, `retries`) filled by `sync_yml` from its own arguments. The `sync_yml` signature is unchanged. |
| A4 | `dispatch_analysis` needs the analysis server's `host`/`port`; the spec's args are `{server_key, endpoint, params}` while the alias block carries `host`/`port`/`analysis_params`. | If `args` has both `host` and `port`, `world_config_dict = {"servers": {server_key: args}}` exactly as today; otherwise the entry is `syncer.world_config["servers"][server_key]` (a missing entry raises `HookConfigError`). `params` is read as `args.get("params", args.get("analysis_params", {}))`. |
| A5 | Completeness: a `.prg` with `s3: true` + `api: true` but an unfinished hook chain would read as complete under the spec's "either" rule. | `_prg_is_complete`: `synced: true` → complete; any `synced:` line present (i.e. `synced: false`) → incomplete; no `synced:` line → legacy rule `s3: true` and `api: true`. The chain runner writes `hooks: {}` and `synced: false` before running the first hook, so a record that ever entered the new chain is never judged by the legacy rule. |
| A6 | Where does SYNC's `postfinish_hooks` (top-level on the server entry) reach `SyncDriver`, which receives only `params`? | `SyncDriver.__init__(config, helaodirs, postfinish_hooks=None)` — a third keyword. `HelaoSyncer` and `NativeSyncer` pass the resolved server entry's `postfinish_hooks`. Test fixtures pass it directly. |
| A7 | `PostfinishContext.data: HelaoData` — constructing a `HelaoData` walks the record tree. | Kept as a lazy `@property data` that builds `HelaoData(str(self.yml.target))` on first access; zero cost for hooks that never read it. |
| A8 | `run_prefinish(hooks, record, name, record_dir, server)`: what is `hooks`? | A `HookSet` (normalized config + loaded instances, with `select(name)`). Servers store one `HookSet` per level: `prefinish_hooks` (action servers), `prefinish_experiment_hooks` / `prefinish_sequence_hooks` (orchestrators). |
| A9 | An `HloPostProcessor` configured at experiment level, or `dispatch_analysis` at action level, would fail at runtime. | Hooks declare `phase` (`"prefinish"`/`"postfinish"`/`None`) and `levels` (tuple or `None`); `load_hook_set(cfg, phase, level)` refuses a mismatch at startup naming the hook. |
| A10 | Empty list as a hook's record list. | Refused at startup (it would configure a hook that applies to nothing). |
| A11 | `MicroOrch._write_action_parent_exp` synthesizes a manual parent experiment for a standalone `run_action`. | No hooks, no `finish_yml` there (manual records are never handed to SYNC, matching `move_dir`). Hooks + handoff apply to `run_experiment`/`run_sequence` records only. |
| A12 | The spec's `import_hooks` name. | The public loader functions are `import_hook(name) -> FinishHook` and `load_hook_set(cfg, phase, level) -> HookSet`; `import_postprocessors` is deleted from `Base` and `ActionHost` (no callers remain). |
| A13 | `read_hlo` / `async_action_dispatcher` patch points move from the sync module into the hook modules; tests written before the refactor patch the sync module. | The golden test (Task 1) patches both locations (`raising=False` on the one that may not exist); `test_sync_hlo_rename_warning.py` is updated in Task 9 to patch `helao.core.hooks.builtin.s3_upload.read_hlo`. The hook modules import `hlo_data` / `dispatcher` **as modules** and call `hlo_data.read_hlo(...)` / `dispatcher.async_action_dispatcher(...)` so a module-attribute patch takes effect. |

## File structure

Created:
- `helao/core/hooks/__init__.py` — `HookConfigError`, `FinishHook`, `PrefinishContext`, `PostfinishContext`, `HookMap`, `HookSet`, `LEVELS`.
- `helao/core/hooks/config.py` — `normalize_hook_map`, `prefinish_config`, `postfinish_config`, `find_orchestrator_entry`.
- `helao/core/hooks/loader.py` — `import_hook`, `load_hook_set`, adapters `HloPostProcessorHook`, `MetaProcessorHook`.
- `helao/core/hooks/prefinish.py` — `run_prefinish`.
- `helao/core/hooks/postfinish.py` — `run_postfinish_chain`.
- `helao/core/hooks/builtin/__init__.py` (empty), `builtin/s3_upload.py`, `builtin/dispatch_analysis.py`.
- Tests: `helao/core/tests/test_sync_postfinish_golden.py`, `test_hooks_config.py`, `test_hooks_loader.py`, `test_hooks_prefinish.py`, `test_hooks_postfinish.py`, `test_sync_postfinish_chain.py`, `test_micro_orch_finish.py`; `helao/hexagon/tests/test_prefinish_action.py`.

Modified:
- Models: `helao/core/models/action.py`, `experiment.py`, `sequence.py` (+ `prefinish_errors`).
- Action servers: `helao/core/servers/base.py`, `helao/hexagon/app/action_host.py` (hook set attribute, delete `import_postprocessors`); finalizer twins `helao/core/servers/active_finalizer.py`, `helao/hexagon/adapters/native/finalizer.py`.
- Orchestrators: `helao/core/servers/orch.py`, `helao/hexagon/app/orch_host.py`, `helao/hexagon/app/orch_lifecycle.py`.
- SYNC: `helao/core/drivers/data/sync_driver.py`, `helao/hexagon/adapters/native/sync_driver.py`, `helao/hexagon/adapters/native/native_syncer.py`, `helao/helpers/run_state.py`.
- Runner: `helao/core/runners/micro_orch.py`.
- Fixtures/tests touched: `helao/hexagon/tests/native_fixtures.py`, `sync_fixtures.py`, `helao/core/tests/unit_test_active_finalizer.py`, `unit_test_active_executor.py`, `test_active_golden_master.py`, `unit_test_orch_lifecycle.py`, `test_orch_dispatch_golden_master.py`, `unit_test_micro_orch.py`, `test_run_state.py`, `test_sync_hlo_rename_warning.py`, `helao/hexagon/tests/test_action_writes_artifacts.py`.
- Docs: `helao/core/drivers/data/CLAUDE.md`, `docs/config-schema.md`, the spec's `Status:` line.

---

### Task 1: Golden characterization of today's SYNC output

**Files:**
- Create: `helao/core/tests/test_sync_postfinish_golden.py`
- Modify: `helao/hexagon/tests/sync_fixtures.py` (extend `make_sync_driver`)

**Interfaces:**
- Consumes: `helao/hexagon/tests/sync_fixtures.py` — `make_exp_tree(root, runs, exp_uuid)`, `make_action(exp_yml, order, process_finish)`, `mk_uuid(tag)`, `ts(second)`, `write_yml(path, meta)`, `teardown_driver(drv)`; both `SyncDriver` classes' `sync_yml(yml_path=..., rank=...)`, `to_s3(msg, target, compress, retries)`, `enqueue_yml`.
- Produces: `make_sync_driver(tmp_root, cls, cfg_extra: dict | None = None, postfinish_hooks: dict | None = None)` — `postfinish_hooks` is forwarded to the driver constructor **only when not None** (the constructor gains that keyword in Task 9; passing it before then would fail, and this test does not pass it). `LEGACY_PRG_KEYS` and the `_record_uploads(drv)` helper are reused by Task 9's tests.

This is a **characterization** test: it pins what the unchanged code does today. If an assertion fails against the UNCHANGED code, the literal expected value is wrong — replace it with the observed value and re-run. Never change the assertion *structure*, and never touch non-test code in this task.

- [ ] **Step 1: Extend `make_sync_driver`**

In `helao/hexagon/tests/sync_fixtures.py` replace the `make_sync_driver` function with:

```python
def make_sync_driver(tmp_root, cls, cfg_extra=None, postfinish_hooks=None):
    """Bare sync driver on a tempdir tree; hermetic (s3/api unset).

    Must be called with a running event loop (SyncDriver.__init__ spawns the
    syncer worker tasks). Callers are responsible for teardown_driver().

    ``cfg_extra`` is merged into the driver params (e.g. an
    ``auto_analyze_sequences`` alias block); ``postfinish_hooks`` is the SYNC
    entry's top-level hook config and is forwarded only when given, so this
    fixture works against a constructor without that keyword."""
    hd = HelaoDirs(
        root=Path(tmp_root),
        save_root=Path(tmp_root) / RunDir.ACTIVE.value,
        process_root=Path(tmp_root) / "PROCESSES",
    )
    cfg = {"aws_bucket": "test-bucket", "max_tasks": 1}
    cfg.update(cfg_extra or {})
    if postfinish_hooks is None:
        return cls(cfg, hd)
    return cls(cfg, hd, postfinish_hooks=postfinish_hooks)
```

- [ ] **Step 2: Write the golden test**

Create `helao/core/tests/test_sync_postfinish_golden.py`:

```python
"""Golden characterization of the SYNC default chain, written BEFORE the
finish-hooks refactor (spec §8: "the default chain produces the same S3 keys,
.prg fields and meta json as today").

One sequence / one experiment / two actions, driven through ``sync_yml`` in
child-first order with ``to_s3`` recorded and ``enqueue_yml`` stubbed. Every
literal below is what the pre-refactor code produced; the refactor may ADD
``hooks``/``synced`` to a .prg (compared through LEGACY_PRG_KEYS only) and
may not change anything else asserted here.
"""

import asyncio
import copy

import pytest

import helao.core.drivers.data.sync_driver as legacy_mod
import helao.hexagon.adapters.native.sync_driver as native_mod
from helao.helpers import dispatcher as dispatcher_mod
from helao.helpers.yml_tools import yml_load
from helao.hexagon.tests.sync_fixtures import (
    make_action,
    make_exp_tree,
    make_sync_driver,
    mk_uuid,
    teardown_driver,
    ts,
    write_yml,
)

try:  # exists only after the refactor (Task 9); see settled decision A13
    import helao.core.hooks.builtin.s3_upload as s3_upload_mod
except ImportError:  # pragma: no cover
    s3_upload_mod = None

HLO = "data-0.0.0.0__0.hlo"
MISC = "notes.txt"
SEQ_UUID = mk_uuid(999)
EXP_UUID = mk_uuid(1)
ACT0_UUID = mk_uuid(0)
ACT1_UUID = mk_uuid(1)  # act_meta(order) uses mk_uuid(order)
ANA = {
    "server_key": "ANA",
    "host": "127.0.0.1",
    "port": 8999,
    "endpoint": "analyze_test",
    "analysis_params": {"a": 1},
}
#: .prg keys that exist before the refactor; the refactor may add others.
LEGACY_PRG_KEYS = (
    "yml",
    "api",
    "s3",
    "files_pending",
    "files_s3",
    "process_actions_done",
    "process_groups",
    "process_metas",
    "process_s3",
    "process_api",
    "legacy_finisher_idxs",
    "legacy_experiment",
)


def _legacy_view(prg_dict: dict) -> dict:
    return {k: v for k, v in prg_dict.items() if k in LEGACY_PRG_KEYS}


def _record_uploads(drv) -> dict:
    """Stub ``to_s3`` to record ``{key: payload}``; a dict payload is deep-copied."""
    uploads: dict = {}

    async def accept(msg=None, target=None, compress=False, retries=5):
        uploads[target] = copy.deepcopy(msg) if isinstance(msg, dict) else str(msg)
        return True

    drv.to_s3 = accept
    return uploads


def _build_tree(root):
    exp_yml = make_exp_tree(root, "RUNS", EXP_UUID)
    seq_dir = exp_yml.parent.parent
    seq_yml = seq_dir / f"{ts(0)}-seq.yml"
    write_yml(
        seq_yml,
        {
            "sequence_uuid": SEQ_UUID,
            "sequence_name": "test_seq",
            "sequence_label": "golden",
            "sequence_params": {"p": 1},
        },
    )
    act0 = make_action(exp_yml, 0)  # process_finish False
    (act0.parent / HLO).write_text("x")
    (act0.parent / MISC).write_text("note")
    act0.write_text(
        act0.read_text()
        + f"files:\n- file_name: {HLO}\n  file_type: helao__file\n"
        + f"- file_name: {MISC}\n  file_type: aux__file\n"
    )
    act1 = make_action(exp_yml, 1, process_finish=True)
    act1.write_text(
        act1.read_text() + "technique_name: [tech_a, tech_b]\naction_split: 1\n"
    )
    return seq_yml, exp_yml, act0, act1


async def _drive(drv, ymls):
    calls = []

    async def record(upath, rank=0, rank_limit=-5):
        calls.append((str(upath), rank))

    drv.enqueue_yml = record
    for yml, rank in ymls:
        await asyncio.wait_for(drv.sync_yml(yml_path=yml, rank=rank), timeout=30)
    return calls


@pytest.mark.parametrize("mod", [legacy_mod, native_mod])
@pytest.mark.asyncio
async def test_default_chain_golden(tmp_path, mod, monkeypatch):
    fake_hlo = lambda fp: ({"k": "v"}, {"t_s": [0.0], "value": [1.0]})  # noqa: E731
    monkeypatch.setattr(mod, "read_hlo", fake_hlo, raising=False)
    if s3_upload_mod is not None:
        monkeypatch.setattr(s3_upload_mod, "read_hlo", fake_hlo)

    dispatched = []

    async def fake_dispatch(world_config_dict=None, A=None, **kw):
        dispatched.append((world_config_dict, A))
        return {}, None

    monkeypatch.setattr(mod, "async_action_dispatcher", fake_dispatch, raising=False)
    monkeypatch.setattr(dispatcher_mod, "async_action_dispatcher", fake_dispatch)

    drv = make_sync_driver(
        tmp_path, mod.SyncDriver, cfg_extra={"auto_analyze_sequences": {"test_seq": ANA}}
    )
    try:
        seq_yml, exp_yml, act0, act1 = _build_tree(tmp_path)
        uploads = _record_uploads(drv)
        await _drive(drv, [(act0, 0), (act1, 0), (exp_yml, 1), (seq_yml, 2)])

        # --- S3 key set -------------------------------------------------
        exp_prg = mod.Progress(exp_yml).dict
        assert len(exp_prg["process_metas"]) == 1, exp_prg
        (pidx, pmeta), = exp_prg["process_metas"].items()
        puuid = pmeta["process_uuid"]
        assert set(uploads) == {
            f"raw_data/{ACT0_UUID}/{HLO}.json",
            f"raw_data/{ACT0_UUID}/{MISC}",
            f"action/{ACT0_UUID}.json",
            f"action/{ACT1_UUID}.json",
            f"process/{puuid}.json",
            f"experiment/{EXP_UUID}.json",
            f"sequence/{SEQ_UUID}.json",
        }, sorted(uploads)

        # --- bodies -----------------------------------------------------
        assert uploads[f"raw_data/{ACT0_UUID}/{HLO}.json"] == {
            "meta": {"k": "v"},
            "data": {"t_s": [0.0], "value": [1.0]},
        }
        assert uploads[f"raw_data/{ACT0_UUID}/{MISC}"] == str(act0.parent / MISC)
        act0_meta = uploads[f"action/{ACT0_UUID}.json"]
        assert [(f["file_name"], f["file_type"]) for f in act0_meta["files"]] == [
            (MISC, "aux__file"),
            (f"{HLO}.json", "helao__json_file"),
        ]
        assert uploads[f"action/{ACT1_UUID}.json"]["technique_name"] == "tech_b"
        assert uploads[f"experiment/{EXP_UUID}.json"]["process_list"] == [puuid]
        assert uploads[f"process/{puuid}.json"]["process_uuid"] == puuid
        assert uploads[f"sequence/{SEQ_UUID}.json"]["sequence_name"] == "test_seq"

        # --- .prg sidecars (legacy keys only) ----------------------------
        act0_prg = _legacy_view(mod.Progress(act0).dict)
        assert act0_prg == {
            "yml": str(act0),
            "api": True,
            "s3": True,
            "files_pending": [],
            "files_s3": {
                HLO: f"raw_data/{ACT0_UUID}/{HLO}.json",
                MISC: f"raw_data/{ACT0_UUID}/{MISC}",
            },
        }
        assert _legacy_view(mod.Progress(act1).dict) == {
            "yml": str(act1),
            "api": True,
            "s3": True,
            "files_pending": [],
            "files_s3": {},
        }
        exp_view = _legacy_view(exp_prg)
        assert exp_view["api"] is True and exp_view["s3"] is True
        assert exp_view["process_s3"] == [pidx] and exp_view["process_api"] == [pidx]
        assert exp_view["legacy_experiment"] is True
        assert sorted(exp_view["process_actions_done"]) == [0, 1]
        assert list(exp_yml.parent.glob("*-prc.yml")), "no local -prc.yml written"
        seq_view = _legacy_view(mod.Progress(seq_yml).dict)
        assert seq_view == {"yml": str(seq_yml), "api": True, "s3": True}

        # --- everything is judged synced --------------------------------
        for yml in (act0, act1, exp_yml, seq_yml):
            assert mod.HelaoYml(yml).status == "synced", yml

        # --- auto-analysis dispatch payload ------------------------------
        assert len(dispatched) == 1
        world, A = dispatched[0]
        assert world == {"servers": {"ANA": ANA}}
        assert A.action_name == "analyze_test"
        assert A.action_server.server_name == "ANA"
        assert A.action_params == {
            "sequence_path": str(seq_yml.parent),
            "params": {"a": 1},
        }
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", [legacy_mod, native_mod])
@pytest.mark.asyncio
async def test_default_chain_without_auto_analysis_dispatches_nothing(tmp_path, mod, monkeypatch):
    monkeypatch.setattr(mod, "read_hlo", lambda fp: ({}, {}), raising=False)
    if s3_upload_mod is not None:
        monkeypatch.setattr(s3_upload_mod, "read_hlo", lambda fp: ({}, {}))
    dispatched = []

    async def fake_dispatch(world_config_dict=None, A=None, **kw):
        dispatched.append(A)
        return {}, None

    monkeypatch.setattr(mod, "async_action_dispatcher", fake_dispatch, raising=False)
    monkeypatch.setattr(dispatcher_mod, "async_action_dispatcher", fake_dispatch)
    drv = make_sync_driver(tmp_path, mod.SyncDriver)
    try:
        seq_yml, exp_yml, act0, act1 = _build_tree(tmp_path)
        _record_uploads(drv)
        await _drive(drv, [(act0, 0), (act1, 0), (exp_yml, 1), (seq_yml, 2)])
        assert dispatched == []
        assert mod.HelaoYml(seq_yml).status == "synced"
    finally:
        await teardown_driver(drv)
```

- [ ] **Step 3: Run against the UNCHANGED code — it must PASS**

Run: `conda run -n helao python -m pytest helao/core/tests/test_sync_postfinish_golden.py -v`
Expected: 4 passed. If a literal differs from what today's code produces (e.g. the process index key type, the misc-file `file_type` ordering), correct the literal to the observed value, re-run, and note the correction in the commit message. Do not loosen an equality into a containment check.

Also confirm the fixture change broke nothing: `conda run -n helao python -m pytest helao/core/tests/test_sync_parent_requeue.py helao/core/tests/test_sync_hlo_rename_warning.py helao/hexagon/tests/test_native_sync_driver.py -v` → all pass.

- [ ] **Step 4: Commit**

```bash
black helao/core/tests/test_sync_postfinish_golden.py helao/hexagon/tests/sync_fixtures.py
git add helao/core/tests/test_sync_postfinish_golden.py helao/hexagon/tests/sync_fixtures.py
git commit -m "test(sync): golden characterization of the default upload chain

Pins S3 keys, bodies, .prg legacy fields and the auto-analysis dispatch
payload of today's sync_yml before the finish-hooks refactor.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Hook contract, contexts, `HookSet`, and config normalization

**Files:**
- Create: `helao/core/hooks/__init__.py`, `helao/core/hooks/config.py`
- Test: `helao/core/tests/test_hooks_config.py`

**Interfaces:**
- Produces (in `helao.core.hooks`):
  - `class HookConfigError(ValueError)`
  - `LEVELS = ("action", "experiment", "sequence")`
  - `HookMap = dict[str, dict[str, Optional[dict]]]` — hook name → {record name or `"*"` → args or None}; dict order = execution order.
  - `class FinishHook(ABC)`: `blocking: bool = True`, `phase: Optional[str] = None`, `levels: Optional[tuple[str, ...]] = None`, `async def run(self, ctx) -> None` (abstract).
  - `@dataclass PrefinishContext(record: Any, record_dir: Path, server: Any, args: Optional[dict])`
  - `@dataclass PostfinishContext(yml: Any, prg: Any, syncer: Any, args: Optional[dict], opts: dict = {})` with lazy `data` property.
  - `@dataclass HookSet(cfg: HookMap, hooks: dict[str, FinishHook])`: `select(name) -> list[tuple[str, FinishHook, Optional[dict]]]`, `HookSet.empty()`.
- Produces (in `helao.core.hooks.config`):
  - `normalize_hook_map(raw, key: str) -> HookMap`
  - `prefinish_config(server_cfg: dict, key: str, alias: str, label: str) -> HookMap`
  - `postfinish_config(postfinish_hooks, auto_analyze, label: str) -> dict[str, HookMap]` (keys exactly `LEVELS`)
  - `find_orchestrator_entry(world_cfg) -> dict`

- [ ] **Step 1: Write the failing tests**

Create `helao/core/tests/test_hooks_config.py`:

```python
"""Config surface of the finish hooks (spec §3): shapes, aliases, refusals."""

import logging

import pytest

from helao.core.hooks import FinishHook, HookConfigError, HookSet, LEVELS
from helao.core.hooks.config import (
    find_orchestrator_entry,
    normalize_hook_map,
    postfinish_config,
    prefinish_config,
)


class _Noop(FinishHook):
    async def run(self, ctx):
        return None


def test_list_value_expands_to_none_args_in_order():
    out = normalize_hook_map({"b": ["x", "*"], "a": ["y"]}, key="k")
    assert list(out) == ["b", "a"]
    assert out == {"b": {"x": None, "*": None}, "a": {"y": None}}


def test_mapping_value_keeps_per_name_args():
    out = normalize_hook_map({"h": {"seq1": {"p": 1}}}, key="k")
    assert out == {"h": {"seq1": {"p": 1}}}


def test_none_is_empty():
    assert normalize_hook_map(None, key="k") == {}


@pytest.mark.parametrize(
    "raw",
    [["not", "a", "dict"], {"h": "x"}, {"h": [1]}, {"h": []}, {"h": {"n": 1}}, {"": ["*"]}],
)
def test_bad_shapes_raise_naming_the_key(raw):
    with pytest.raises(HookConfigError) as ei:
        normalize_hook_map(raw, key="SPEC_R.prefinish_hooks")
    assert "SPEC_R.prefinish_hooks" in str(ei.value)


def test_prefinish_alias_translates_and_warns(caplog):
    caplog.set_level(logging.WARNING)
    out = prefinish_config(
        {"hlo_postprocess_libs": ["hlo_to_csv", "spec_melt_wls"]},
        "prefinish_hooks",
        "hlo_postprocess_libs",
        "SPEC_R",
    )
    assert out == {"hlo_to_csv": {"*": None}, "spec_melt_wls": {"*": None}}
    assert "hlo_postprocess_libs" in caplog.text and "deprecated" in caplog.text


def test_prefinish_new_key_is_normalized_without_warning(caplog):
    caplog.set_level(logging.WARNING)
    out = prefinish_config(
        {"prefinish_hooks": {"hlo_to_csv": ["acquire"]}},
        "prefinish_hooks",
        "hlo_postprocess_libs",
        "SPEC_R",
    )
    assert out == {"hlo_to_csv": {"acquire": None}}
    assert "deprecated" not in caplog.text


def test_prefinish_old_and_new_together_refused_naming_both():
    with pytest.raises(HookConfigError) as ei:
        prefinish_config(
            {"prefinish_hooks": {"a": ["*"]}, "hlo_postprocess_libs": ["a"]},
            "prefinish_hooks",
            "hlo_postprocess_libs",
            "SPEC_R",
        )
    msg = str(ei.value)
    assert "prefinish_hooks" in msg and "hlo_postprocess_libs" in msg and "SPEC_R" in msg


def test_prefinish_absent_is_empty():
    assert prefinish_config({}, "prefinish_hooks", "hlo_postprocess_libs", "X") == {}


def test_postfinish_default_chain_without_analysis():
    out = postfinish_config(None, None, "SYNC")
    assert tuple(out) == LEVELS
    assert out == {level: {"s3_upload": {"*": None}} for level in LEVELS}


def test_postfinish_default_chain_adds_dispatch_analysis_alias(caplog):
    caplog.set_level(logging.WARNING)
    ana = {"server_key": "ANA", "endpoint": "e", "host": "h", "port": 1}
    out = postfinish_config(None, {"my_seq": ana}, "SYNC")
    assert out["sequence"] == {"s3_upload": {"*": None}, "dispatch_analysis": {"my_seq": ana}}
    assert out["action"] == {"s3_upload": {"*": None}}
    assert "auto_analyze_sequences" in caplog.text and "deprecated" in caplog.text


def test_postfinish_empty_alias_is_ignored(caplog):
    caplog.set_level(logging.WARNING)
    assert postfinish_config(None, {}, "SYNC")["sequence"] == {"s3_upload": {"*": None}}
    assert "deprecated" not in caplog.text


def test_postfinish_explicit_owns_the_chain():
    out = postfinish_config({"action": {"s3_upload": ["*"]}}, None, "SYNC")
    assert out == {"action": {"s3_upload": {"*": None}}, "experiment": {}, "sequence": {}}


def test_postfinish_stray_level_refused():
    with pytest.raises(HookConfigError) as ei:
        postfinish_config({"action": {}, "process": {"x": ["*"]}}, None, "SYNC")
    assert "process" in str(ei.value)


def test_postfinish_old_and_new_together_refused():
    with pytest.raises(HookConfigError) as ei:
        postfinish_config({"sequence": {"s3_upload": ["*"]}}, {"s": {"server_key": "A"}}, "SYNC")
    msg = str(ei.value)
    assert "auto_analyze_sequences" in msg and "postfinish_hooks" in msg


def test_hookset_select_exact_then_star_in_config_order():
    a, b, c = _Noop(), _Noop(), _Noop()
    hs = HookSet(
        cfg={"a": {"seq1": {"x": 1}}, "b": {"*": None}, "c": {"other": None}},
        hooks={"a": a, "b": b, "c": c},
    )
    assert hs.select("seq1") == [("a", a, {"x": 1}), ("b", b, None)]
    assert hs.select("zzz") == [("b", b, None)]
    assert HookSet.empty().select("seq1") == []


def test_hookset_star_args_apply_when_name_missing():
    a = _Noop()
    hs = HookSet(cfg={"a": {"*": {"d": 1}, "seq1": {"d": 2}}}, hooks={"a": a})
    assert hs.select("seq1") == [("a", a, {"d": 2})]
    assert hs.select("seq2") == [("a", a, {"d": 1})]


def test_find_orchestrator_entry():
    world = {"servers": {"SIM": {"group": "action"}, "ORCH": {"group": "orchestrator", "x": 1}}}
    assert find_orchestrator_entry(world) == {"group": "orchestrator", "x": 1}
    assert find_orchestrator_entry({}) == {}
    assert find_orchestrator_entry(None) == {}
```

- [ ] **Step 2: Run to verify failure**

Run: `conda run -n helao python -m pytest helao/core/tests/test_hooks_config.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'helao.core.hooks'`.

- [ ] **Step 3: Write `helao/core/hooks/__init__.py`**

```python
"""One contract for everything that runs around a record's ``finished`` transition.

Two phases (spec D1). **Pre-finish** runs inside the server that owns the
record -- the action server for an action, the orchestrator or ``MicroOrch``
for an experiment or sequence -- in config order, before the final yml is
written and before ``finished`` is emitted; it may change the record.
**Post-finish** runs in SYNC after the record is finished and may not change
it. Both phases use :class:`FinishHook`; the existing ``HloPostProcessor`` /
``MetaProcessor`` classes run unchanged through the adapters in
:mod:`helao.core.hooks.loader`.
"""

__all__ = [
    "FinishHook",
    "HookConfigError",
    "HookMap",
    "HookSet",
    "LEVELS",
    "PostfinishContext",
    "PrefinishContext",
]

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

#: Record levels a hook can be configured at; also the only keys
#: ``postfinish_hooks`` may have (spec §3.3).
LEVELS = ("action", "experiment", "sequence")

#: Normalized hook config: hook name -> {record name or "*": args or None}.
#: Dict order is execution order (spec D3).
HookMap = dict[str, dict[str, Optional[dict]]]


class HookConfigError(ValueError):
    """A hook config that must not degrade silently to "no hooks" (spec §3.3)."""


class FinishHook(ABC):
    """A unit of finish-time work (spec §4.1).

    ``blocking`` is consulted for post-finish only (spec D5): a blocking
    failure stops the chain and keeps the record unsynced; a non-blocking one
    is recorded and the chain continues. ``phase``/``levels`` let the loader
    refuse a hook configured where it cannot run (``None`` = anywhere). A hook
    that does blocking I/O or CPU work wraps it in ``asyncio.to_thread``
    itself. One instance per server, created at startup and reused.
    """

    blocking: bool = True
    phase: Optional[str] = None  # "prefinish" | "postfinish" | None
    levels: Optional[tuple[str, ...]] = None  # subset of LEVELS, or None

    @abstractmethod
    async def run(self, ctx) -> None:
        """Raise to signal failure."""


@dataclass
class PrefinishContext:
    record: Any  # Action | Experiment | Sequence -- live model, hooks may mutate
    record_dir: Path
    server: Any  # ActionHost / Base / Orch / MicroOrch
    args: Optional[dict]


@dataclass
class PostfinishContext:
    yml: Any  # HelaoYml of the finished record
    prg: Any  # Progress -- read-only for the hook; the runner owns prg.dict["hooks"]
    syncer: Any  # the SyncDriver: S3 client, world config, sync_process, ...
    args: Optional[dict]
    #: ``sync_yml`` call options handed through to the built-ins (settled
    #: decision A3): force_s3, force_api, compress, retries.
    opts: dict = field(default_factory=dict)

    @property
    def data(self):
        """``HelaoData`` over the finished record, built on first access (A7)."""
        from helao.helpers.helao_data import HelaoData

        return HelaoData(str(self.yml.target))


@dataclass
class HookSet:
    """Normalized config plus the loaded instances it names, for one level."""

    cfg: HookMap
    hooks: dict[str, FinishHook]

    @classmethod
    def empty(cls) -> "HookSet":
        return cls(cfg={}, hooks={})

    def select(self, name: str) -> list[tuple[str, FinishHook, Optional[dict]]]:
        """Hooks that apply to record ``name``, in config order (spec §5 step 1).

        An exact entry wins over ``"*"`` for the args; ``"*"`` matches every
        record.
        """
        out = []
        for hook_name, targets in self.cfg.items():
            if name in targets:
                out.append((hook_name, self.hooks[hook_name], targets[name]))
            elif "*" in targets:
                out.append((hook_name, self.hooks[hook_name], targets["*"]))
        return out
```

- [ ] **Step 4: Write `helao/core/hooks/config.py`**

```python
"""Config normalization, aliases and validation for finish hooks (spec §3).

Every violation raises :class:`HookConfigError` naming the offending key: a
bad hook config never degrades to "no hooks" (spec §3.3).
"""

__all__ = [
    "find_orchestrator_entry",
    "normalize_hook_map",
    "postfinish_config",
    "prefinish_config",
]

from typing import Any, Optional

from helao.core.hooks import LEVELS, HookConfigError, HookMap
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


def normalize_hook_map(raw: Any, key: str) -> HookMap:
    """``{hook: [names] | {name: args}}`` -> :data:`HookMap`, or raise naming ``key``."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise HookConfigError(
            f"{key} must be a mapping of hook name -> list of record names, "
            f"got {type(raw).__name__}"
        )
    out: HookMap = {}
    for hook_name, value in raw.items():
        if not isinstance(hook_name, str) or not hook_name:
            raise HookConfigError(
                f"{key}: hook names must be non-empty strings, got {hook_name!r}"
            )
        shape = (
            f"{key}.{hook_name} must be a non-empty list of record names "
            "(or '*'), or a mapping of record name -> mapping of args"
        )
        if isinstance(value, list):
            if not value or not all(isinstance(v, str) and v for v in value):
                raise HookConfigError(shape)
            out[hook_name] = {v: None for v in value}
        elif isinstance(value, dict):
            if not value or not all(
                isinstance(k, str) and k and isinstance(v, dict)
                for k, v in value.items()
            ):
                raise HookConfigError(shape)
            out[hook_name] = dict(value)
        else:
            raise HookConfigError(shape)
    return out


def prefinish_config(server_cfg: dict, key: str, alias: str, label: str) -> HookMap:
    """The pre-finish hook map of one server entry.

    ``key`` is the new dict key (``prefinish_hooks`` /
    ``prefinish_experiment_hooks`` / ``prefinish_sequence_hooks``); ``alias``
    the retired list key it replaces (``hlo_postprocess_libs`` /
    ``exp_postprocess_libs`` / ``seq_postprocess_libs``). An alias translates
    to ``{name: ["*"]}`` with one deprecation warning; both keys together are
    refused (spec §3.1). ``label`` names the server in messages.
    """
    server_cfg = server_cfg or {}
    if key in server_cfg and alias in server_cfg:
        raise HookConfigError(
            f"{label}: {alias!r} and {key!r} are both set; {alias!r} is a "
            f"deprecated alias of {key!r}, keep one"
        )
    if alias in server_cfg:
        names = server_cfg.get(alias) or []
        if not isinstance(names, list) or not all(
            isinstance(n, str) and n for n in names
        ):
            raise HookConfigError(f"{label}.{alias} must be a list of hook names")
        LOGGER.warning(
            f"{label}: {alias!r} is deprecated; use {key}: {{<hook>: ['*']}}"
        )
        return {n: {"*": None} for n in names}
    return normalize_hook_map(server_cfg.get(key), f"{label}.{key}")


def postfinish_config(
    postfinish_hooks: Any, auto_analyze: Any, label: str
) -> dict[str, HookMap]:
    """The post-finish chain per level for the SYNC entry (spec §3, §3.2).

    ``postfinish_hooks`` absent -> the default chain equivalent to today:
    ``s3_upload: ["*"]`` at every level, plus ``dispatch_analysis`` at
    sequence level translated from the ``auto_analyze_sequences`` params
    alias when that is present (one deprecation warning). A present
    ``postfinish_hooks`` owns the whole chain (spec D4); it may only have the
    keys in :data:`LEVELS`, and setting it together with the alias is refused.
    """
    if postfinish_hooks is not None and auto_analyze:
        raise HookConfigError(
            f"{label}: params.auto_analyze_sequences and postfinish_hooks are both "
            "set; auto_analyze_sequences is a deprecated alias of "
            "postfinish_hooks.sequence.dispatch_analysis, keep one"
        )
    if postfinish_hooks is None:
        chain: dict[str, HookMap] = {
            level: {"s3_upload": {"*": None}} for level in LEVELS
        }
        if auto_analyze:
            if not isinstance(auto_analyze, dict) or not all(
                isinstance(k, str) and isinstance(v, dict)
                for k, v in auto_analyze.items()
            ):
                raise HookConfigError(
                    f"{label}.params.auto_analyze_sequences must map sequence "
                    "name -> analysis config mapping"
                )
            LOGGER.warning(
                f"{label}: params.auto_analyze_sequences is deprecated; use "
                "postfinish_hooks.sequence.dispatch_analysis"
            )
            chain["sequence"]["dispatch_analysis"] = dict(auto_analyze)
        return chain
    if not isinstance(postfinish_hooks, dict):
        raise HookConfigError(
            f"{label}.postfinish_hooks must be a mapping with keys {list(LEVELS)}"
        )
    unknown = [k for k in postfinish_hooks if k not in LEVELS]
    if unknown:
        raise HookConfigError(
            f"{label}.postfinish_hooks has unknown keys {unknown}; "
            f"allowed: {list(LEVELS)}"
        )
    return {
        level: normalize_hook_map(
            postfinish_hooks.get(level), f"{label}.postfinish_hooks.{level}"
        )
        for level in LEVELS
    }


def find_orchestrator_entry(world_cfg: Optional[dict]) -> dict:
    """The first ``group: orchestrator`` server entry of a world config, or ``{}``.

    ``MicroOrch`` reads its experiment/sequence pre-finish hooks from here
    (spec §7.3).
    """
    servers = (world_cfg or {}).get("servers") or {}
    for entry in servers.values():
        if isinstance(entry, dict) and entry.get("group") == "orchestrator":
            return entry
    return {}
```

- [ ] **Step 5: Run to verify pass**

Run: `conda run -n helao python -m pytest helao/core/tests/test_hooks_config.py -v`
Expected: all pass. Then `conda run -n helao pyright helao/core/hooks` → 0 errors.

- [ ] **Step 6: Commit**

```bash
black helao/core/hooks helao/core/tests/test_hooks_config.py
git add helao/core/hooks/__init__.py helao/core/hooks/config.py helao/core/tests/test_hooks_config.py
git commit -m "feat(hooks): FinishHook contract, contexts, HookSet and config normalization

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Loader with adapters for existing processors

**Files:**
- Create: `helao/core/hooks/loader.py`, `helao/core/hooks/builtin/__init__.py` (empty file)
- Test: `helao/core/tests/test_hooks_loader.py`

**Interfaces:**
- Consumes: `helao.core.hooks` (Task 2); `helao.helpers.processors.HloPostProcessor` (`__init__(action, save_root)`, `process() -> list[FileInfo]`), `MetaProcessor` (`__init__(meta, core)`, `process() -> None`); `helao.helpers.config_loader.CONFIG` (may be `None`; carries `"deployment"` when launched).
- Produces (in `helao.core.hooks.loader`):
  - `import_hook(name: str) -> FinishHook` — resolution order spec §4.3: built-in `helao.core.hooks.builtin.<name>` → existing `.py` path → `helao/deploy/<CONFIG deployment>/processors/<name>.py` → `helao/deploy/hte/processors/<name>.py` → first (sorted) `helao/deploy/*/processors/<name>.py`. Class `Hook` or `PostProcess`. Raises `HookConfigError` when not found / no class / wrong base.
  - `load_hook_set(cfg: HookMap, phase: str, level: str) -> HookSet` — instantiates each hook once, refuses phase/level mismatch (A9).
  - `class HloPostProcessorHook(FinishHook)`: `phase = "prefinish"`, `levels = ("action",)`, `__init__(cls)`, `run` assigns `ctx.record.files`.
  - `class MetaProcessorHook(FinishHook)`: `phase = "prefinish"`, `__init__(cls)`.

- [ ] **Step 1: Write the failing tests**

Create `helao/core/tests/test_hooks_loader.py`:

```python
"""Hook loading (spec §4.3/§4.4): resolution order, class names, adapters."""

import asyncio
import textwrap
from glob import glob
from pathlib import Path
from types import SimpleNamespace

import pytest

from helao.core.hooks import FinishHook, HookConfigError, HookSet, PrefinishContext
from helao.core.hooks.loader import (
    HloPostProcessorHook,
    MetaProcessorHook,
    import_hook,
    load_hook_set,
)
from helao.helpers.processors import HloPostProcessor, MetaProcessor

REPO = Path(__file__).resolve().parents[3]


def _write(path: Path, body: str) -> str:
    path.write_text(textwrap.dedent(body))
    return str(path)


def test_path_form_with_hook_class(tmp_path):
    p = _write(
        tmp_path / "my_hook.py",
        """
        from helao.core.hooks import FinishHook
        class Hook(FinishHook):
            blocking = False
            async def run(self, ctx):
                ctx.record.touched = True
        """,
    )
    hook = import_hook(p)
    assert isinstance(hook, FinishHook) and hook.blocking is False


def test_path_form_with_postprocess_meta_processor_is_wrapped(tmp_path):
    p = _write(
        tmp_path / "meta_pp.py",
        """
        from helao.helpers.processors import MetaProcessor
        class PostProcess(MetaProcessor):
            def process(self):
                self.meta.experiment_params["marked"] = True
        """,
    )
    hook = import_hook(p)
    assert isinstance(hook, MetaProcessorHook)


def test_hte_processors_resolve_by_bare_name():
    assert isinstance(import_hook("hlo_to_csv"), HloPostProcessorHook)
    assert isinstance(import_hook("append_params"), MetaProcessorHook)


def test_every_deployment_processor_imports_and_wraps():
    """Spec §8: all existing processors import and wrap (private ones too,
    when their deployment is checked out; none is named here). A processor
    whose vendor package is not installed on this OS is reported as skipped,
    the way run_tests.py reports ENV; a missing helao module is a failure."""
    found = sorted(glob(str(REPO / "helao" / "deploy" / "*" / "processors" / "*.py")))
    names = [Path(p).stem for p in found if Path(p).stem != "__init__"]
    assert names, "no processors found; run from the repo root"
    skipped = []
    for name in names:
        try:
            hook = import_hook(name)
        except ModuleNotFoundError as exc:
            if (exc.name or "").startswith("helao"):
                raise
            skipped.append((name, exc.name))
            continue
        assert isinstance(hook, (HloPostProcessorHook, MetaProcessorHook, FinishHook)), name
    assert len(skipped) < len(names), skipped
    if skipped:
        pytest.skip(f"vendor packages missing for: {skipped} (others passed)")


def test_unknown_name_raises():
    with pytest.raises(HookConfigError) as ei:
        import_hook("definitely_not_a_hook_xyz")
    assert "definitely_not_a_hook_xyz" in str(ei.value)


def test_module_without_hook_or_postprocess_raises(tmp_path):
    p = _write(tmp_path / "empty_mod.py", "X = 1\n")
    with pytest.raises(HookConfigError) as ei:
        import_hook(p)
    assert "Hook" in str(ei.value) and "PostProcess" in str(ei.value)


def test_non_hook_class_raises(tmp_path):
    p = _write(tmp_path / "bad_cls.py", "class Hook:\n    pass\n")
    with pytest.raises(HookConfigError):
        import_hook(p)


def test_load_hook_set_refuses_hlo_processor_outside_action_level():
    with pytest.raises(HookConfigError) as ei:
        load_hook_set({"hlo_to_csv": {"*": None}}, phase="prefinish", level="experiment")
    assert "hlo_to_csv" in str(ei.value) and "experiment" in str(ei.value)


def test_load_hook_set_refuses_prefinish_hook_in_postfinish_phase():
    with pytest.raises(HookConfigError) as ei:
        load_hook_set({"append_params": {"*": None}}, phase="postfinish", level="sequence")
    assert "append_params" in str(ei.value)


def test_load_hook_set_builds_one_instance_per_hook():
    hs = load_hook_set(
        {"append_params": {"*": None}, "hlo_to_csv": {"acq": None}},
        phase="prefinish",
        level="action",
    )
    assert isinstance(hs, HookSet)
    assert list(hs.hooks) == ["append_params", "hlo_to_csv"]
    assert hs.select("acq")[1][1] is hs.hooks["hlo_to_csv"]


@pytest.mark.asyncio
async def test_hlo_adapter_replaces_files_and_reads_save_root_from_server(tmp_path):
    seen = {}

    class PP(HloPostProcessor):
        def process(self):
            seen["output_dir"] = self.output_dir
            return ["replaced"]

    record = SimpleNamespace(
        manual_action=False, action_output_dir="2026/0928/seq/exp/0__0__S__a", files=["orig"]
    )
    server = SimpleNamespace(helaodirs=SimpleNamespace(save_root=str(tmp_path / "RUNS")))
    await HloPostProcessorHook(PP).run(
        PrefinishContext(record=record, record_dir=tmp_path, server=server, args=None)
    )
    assert record.files == ["replaced"]
    assert seen["output_dir"] == str(tmp_path / "RUNS" / "2026/0928/seq/exp/0__0__S__a")


@pytest.mark.asyncio
async def test_meta_adapter_mutates_in_place():
    class PP(MetaProcessor):
        def process(self):
            self.meta.experiment_params["k"] = self.meta_type

    class Experiment:  # meta_type is the lowercased class name
        experiment_params = {}

    rec = Experiment()
    await MetaProcessorHook(PP).run(
        PrefinishContext(record=rec, record_dir=Path("."), server=object(), args=None)
    )
    assert rec.experiment_params == {"k": "experiment"}
```

- [ ] **Step 2: Run to verify failure**

Run: `conda run -n helao python -m pytest helao/core/tests/test_hooks_loader.py -v`
Expected: `ModuleNotFoundError: No module named 'helao.core.hooks.loader'`.

- [ ] **Step 3: Create the package and loader**

Create the empty file `helao/core/hooks/builtin/__init__.py` (zero bytes is fine; black leaves it).

Create `helao/core/hooks/loader.py`:

```python
"""Resolve hook names to :class:`FinishHook` instances (spec §4.3, §4.4).

Resolution order, shared by the action host, both orchestrators, ``MicroOrch``
and both SYNC drivers:

1. a built-in, ``helao/core/hooks/builtin/<name>.py``;
2. an existing ``.py`` path;
3. ``helao/deploy/<CONFIG deployment>/processors/<name>.py``;
4. ``helao/deploy/hte/processors/<name>.py``;
5. any ``helao/deploy/*/processors/<name>.py`` (sorted, first wins).

Deployment paths are relative to the repo root, exactly as the retired
``import_postprocessors`` resolved them. The module's class named ``Hook``
(new) or ``PostProcess`` (existing) is used: a ``FinishHook`` subclass
directly, an ``HloPostProcessor``/``MetaProcessor`` subclass through the
adapters below, anything else is a startup error.
"""

__all__ = ["HloPostProcessorHook", "MetaProcessorHook", "import_hook", "load_hook_set"]

import asyncio
import importlib
import os
from glob import glob
from importlib.util import module_from_spec, spec_from_file_location
from typing import Optional

from helao.core.hooks import (
    FinishHook,
    HookConfigError,
    HookMap,
    HookSet,
    PrefinishContext,
)
from helao.helpers import config_loader
from helao.helpers import helao_logging as logging
from helao.helpers.processors import HloPostProcessor, MetaProcessor

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

BUILTIN_PKG = "helao.core.hooks.builtin"


class HloPostProcessorHook(FinishHook):
    """Run an ``HloPostProcessor`` class; its result replaces ``record.files``."""

    phase = "prefinish"
    levels = ("action",)

    def __init__(self, cls):
        self.cls = cls

    async def run(self, ctx: PrefinishContext) -> None:
        # The processor joins save_root with action_output_dir itself and
        # redirects a manual action to DIAG, exactly as the finalizer's
        # ``hpp(action, save_root)`` call did.
        save_root = str(ctx.server.helaodirs.save_root)
        processor = self.cls(ctx.record, save_root)
        ctx.record.files = await asyncio.to_thread(processor.process)


class MetaProcessorHook(FinishHook):
    """Run a ``MetaProcessor`` class; it mutates the record in place."""

    phase = "prefinish"

    def __init__(self, cls):
        self.cls = cls

    async def run(self, ctx: PrefinishContext) -> None:
        await asyncio.to_thread(self.cls(ctx.record, ctx.server).process)


def _resolve_path(name: str) -> Optional[str]:
    if name.endswith(".py") and os.path.exists(name):
        return name
    deployment = (config_loader.CONFIG or {}).get("deployment", "")
    candidates = [
        (
            os.path.join("helao", "deploy", deployment, "processors", f"{name}.py")
            if deployment
            else ""
        ),
        os.path.join("helao", "deploy", "hte", "processors", f"{name}.py"),
    ]
    found = next((p for p in candidates if p and os.path.exists(p)), None)
    if found is None:
        any_paths = sorted(
            glob(os.path.join("helao", "deploy", "*", "processors", f"{name}.py"))
        )
        found = any_paths[0] if any_paths else None
    return found


def _load_module_from_path(path: str):
    mod_name = os.path.basename(path)[: -len(".py")]
    spec = spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise HookConfigError(f"cannot load hook module from {path!r}")
    mod = module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def import_hook(name: str) -> FinishHook:
    """Resolve ``name`` (§4.3 order) and return one hook instance."""
    mod = None
    if name.isidentifier():
        try:
            mod = importlib.import_module(f"{BUILTIN_PKG}.{name}")
        except ModuleNotFoundError as exc:
            if exc.name != f"{BUILTIN_PKG}.{name}":
                raise
    if mod is None:
        path = _resolve_path(name)
        if path is None:
            raise HookConfigError(
                f"hook {name!r} not found: not a built-in, not an existing .py "
                f"path, and no helao/deploy/*/processors/{name}.py"
            )
        LOGGER.info(f"Loading hook {name!r} from {path}")
        mod = _load_module_from_path(path)
    cls = getattr(mod, "Hook", None) or getattr(mod, "PostProcess", None)
    if cls is None:
        raise HookConfigError(
            f"hook module {name!r} defines neither a `Hook` nor a `PostProcess` class"
        )
    if isinstance(cls, type) and issubclass(cls, FinishHook):
        return cls()
    if isinstance(cls, type) and issubclass(cls, HloPostProcessor):
        return HloPostProcessorHook(cls)
    if isinstance(cls, type) and issubclass(cls, MetaProcessor):
        return MetaProcessorHook(cls)
    raise HookConfigError(
        f"hook {name!r}: {cls!r} is not a FinishHook, HloPostProcessor or MetaProcessor"
    )


def load_hook_set(cfg: HookMap, phase: str, level: str) -> HookSet:
    """Instantiate every hook named in ``cfg`` once and refuse a misplaced one."""
    hooks: dict[str, FinishHook] = {}
    for hook_name in cfg:
        hook = import_hook(hook_name)
        if hook.phase not in (None, phase):
            raise HookConfigError(
                f"hook {hook_name!r} is a {hook.phase} hook but is configured "
                f"for {phase}"
            )
        if hook.levels is not None and level not in hook.levels:
            raise HookConfigError(
                f"hook {hook_name!r} runs at {list(hook.levels)} level(s) but is "
                f"configured at {level!r}"
            )
        hooks[hook_name] = hook
    return HookSet(cfg=cfg, hooks=hooks)
```

- [ ] **Step 4: Run to verify pass**

Run: `conda run -n helao python -m pytest helao/core/tests/test_hooks_loader.py -v` → all pass. `conda run -n helao pyright helao/core/hooks` → 0 errors.

- [ ] **Step 5: Commit**

```bash
black helao/core/hooks helao/core/tests/test_hooks_loader.py
git add helao/core/hooks/loader.py helao/core/hooks/builtin/__init__.py helao/core/tests/test_hooks_loader.py
git commit -m "feat(hooks): shared loader with HloPostProcessor/MetaProcessor adapters

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 4: `prefinish_errors` model field and the pre-finish runner

**Files:**
- Modify: `helao/core/models/action.py` (after `process_contrib: list[ProcessContrib] = Field(default=[])`), `helao/core/models/experiment.py` (after `finished_global_params`), `helao/core/models/sequence.py` (after `finished_global_params`)
- Create: `helao/core/hooks/prefinish.py`
- Test: `helao/core/tests/test_hooks_prefinish.py`

**Interfaces:**
- Consumes: `HookSet`, `PrefinishContext`, `FinishHook` (Task 2).
- Produces: `prefinish_errors: list[dict] = Field(default=[])` on `ActionModel`, `ExperimentModel`, `SequenceModel` (inherited by `Action`/`Experiment`/`Sequence` in `helao/helpers/premodels.py`, whose `get_act/get_exp/get_seq` are `model_validate(self.model_dump())` so the field travels). `run_prefinish(hook_set: HookSet, record, name: str, record_dir, server) -> None` in `helao.core.hooks.prefinish` — never raises; a failing hook appends `{"hook", "error", "ts"}` to `record.prefinish_errors`.

- [ ] **Step 1: Write the failing tests**

Create `helao/core/tests/test_hooks_prefinish.py`:

```python
"""Pre-finish flow (spec §5, D6, §5.2)."""

from pathlib import Path

import pytest

from helao.core.hooks import FinishHook, HookSet
from helao.core.hooks.prefinish import run_prefinish
from helao.helpers.premodels import Action, Experiment, Sequence


class _Ok(FinishHook):
    def __init__(self, log, tag):
        self.log, self.tag = log, tag

    async def run(self, ctx):
        self.log.append((self.tag, ctx.args))
        ctx.record.experiment_params[self.tag] = True


class _Boom(FinishHook):
    async def run(self, ctx):
        raise RuntimeError("kaboom")


def _exp(name="exp1"):
    exp = Experiment(experiment_name=name, experiment_params={})
    exp.init_exp(time_offset=0)
    return exp


def test_prefinish_errors_default_is_omitted_from_clean_dict():
    for model in (Action(action_name="a"), Experiment(experiment_name="e"), Sequence(sequence_name="s")):
        assert model.prefinish_errors == []
        assert "prefinish_errors" not in model.clean_dict()


@pytest.mark.asyncio
async def test_runs_matching_hooks_in_config_order_with_args():
    log = []
    hs = HookSet(
        cfg={"second": {"exp1": {"n": 2}}, "skip": {"other": None}, "first": {"*": None}},
        hooks={"second": _Ok(log, "second"), "skip": _Ok(log, "skip"), "first": _Ok(log, "first")},
    )
    exp = _exp()
    await run_prefinish(hs, exp, "exp1", Path("/tmp/x"), server=object())
    assert log == [("second", {"n": 2}), ("first", None)]
    assert exp.experiment_params == {"second": True, "first": True}
    assert exp.prefinish_errors == []


@pytest.mark.asyncio
async def test_raising_hook_is_recorded_and_chain_continues(caplog):
    log = []
    hs = HookSet(
        cfg={"boom": {"*": None}, "after": {"*": None}},
        hooks={"boom": _Boom(), "after": _Ok(log, "after")},
    )
    exp = _exp()
    await run_prefinish(hs, exp, "exp1", Path("/tmp/x"), server=object())
    assert log == [("after", None)]
    assert len(exp.prefinish_errors) == 1
    err = exp.prefinish_errors[0]
    assert err["hook"] == "boom"
    assert err["error"] == "RuntimeError: kaboom"
    assert isinstance(err["ts"], str) and "T" in err["ts"]
    assert "boom" in caplog.text and "exp1" in caplog.text and str(exp.experiment_uuid) in caplog.text
    # the error travels with the record's yml/meta and nothing else changed
    assert exp.clean_dict()["prefinish_errors"] == exp.prefinish_errors


@pytest.mark.asyncio
async def test_empty_hookset_is_a_noop():
    exp = _exp()
    await run_prefinish(HookSet.empty(), exp, "exp1", Path("/tmp/x"), server=object())
    assert exp.prefinish_errors == []
```

- [ ] **Step 2: Run to verify failure**

Run: `conda run -n helao python -m pytest helao/core/tests/test_hooks_prefinish.py -v`
Expected: `ModuleNotFoundError: No module named 'helao.core.hooks.prefinish'`. (Then, after Step 4 alone, `test_prefinish_errors_default_is_omitted_from_clean_dict` would fail with `AttributeError: prefinish_errors` — Step 3 is what makes it pass.)

- [ ] **Step 3: Add the model field**

In `helao/core/models/action.py`, directly after the line `    process_contrib: list[ProcessContrib] = Field(default=[])` add:

```python
    # Pre-finish hook failures, {"hook", "error", "ts"} each (finish-hooks spec
    # §5.2). clean_dict drops the empty default, so ymls without failures are
    # byte-identical to before the field existed.
    prefinish_errors: list[dict] = Field(default=[])
```

In `helao/core/models/experiment.py` and `helao/core/models/sequence.py`, directly after `    finished_global_params: dict = Field(default={})` add the same four lines.

Check that nothing narrows the field set: `grep -n "prefinish_errors\|model_fields" helao/helpers/premodels.py` — `get_act`/`get_exp`/`get_seq` use `model_validate(self.model_dump())`, so no edit is needed there.

- [ ] **Step 4: Write the runner**

Create `helao/core/hooks/prefinish.py`:

```python
"""Pre-finish runner (spec §5): run the matching hooks, record failures, never raise."""

__all__ = ["run_prefinish"]

from datetime import datetime
from pathlib import Path

from helao.core.hooks import HookSet, PrefinishContext
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


async def run_prefinish(hook_set: HookSet, record, name: str, record_dir, server) -> None:
    """Run every hook in ``hook_set`` that applies to ``name``, in config order.

    A raising hook is alerted with its name, the record name and uuid, appended
    to ``record.prefinish_errors`` as ``{"hook", "error", "ts"}``, and the
    next hook still runs (D6). The caller then writes the final yml and emits
    ``finished``. No timeout (spec §5).
    """
    kind = record.__class__.__name__.lower()
    uuid = getattr(record, f"{kind}_uuid", None)
    for hook_name, hook, args in hook_set.select(name):
        LOGGER.info(f"Running pre-finish hook {hook_name!r} for {kind} {name}")
        try:
            await hook.run(
                PrefinishContext(
                    record=record, record_dir=Path(record_dir), server=server, args=args
                )
            )
        except Exception as exc:
            LOGGER.error(
                f"pre-finish hook {hook_name!r} failed for {kind} {name} ({uuid})",
                exc_info=True,
            )
            LOGGER.alert(  # type: ignore[attr-defined]
                f"pre-finish hook {hook_name!r} failed for {kind} {name} ({uuid}): "
                f"{type(exc).__name__}: {exc}"
            )
            record.prefinish_errors.append(
                {
                    "hook": hook_name,
                    "error": f"{type(exc).__name__}: {exc}",
                    "ts": datetime.now().isoformat(timespec="seconds"),
                }
            )
```

- [ ] **Step 5: Run to verify pass, plus the byte-identity gate**

Run: `conda run -n helao python -m pytest helao/core/tests/test_hooks_prefinish.py -v` → all pass.
Run the pre-launch model gate and the two golden masters, which serialize full records and would show any yml drift: `conda run -n helao python run_unit_tests.py` and `conda run -n helao python -m pytest helao/core/tests/test_active_golden_master.py helao/core/tests/test_orch_dispatch_golden_master.py -q` → pass.
`conda run -n helao pyright helao/core/hooks helao/core/models/action.py helao/core/models/experiment.py helao/core/models/sequence.py` → 0 errors.

- [ ] **Step 6: Commit**

```bash
black helao/core/hooks/prefinish.py helao/core/tests/test_hooks_prefinish.py helao/core/models/action.py helao/core/models/experiment.py helao/core/models/sequence.py
git add helao/core/hooks/prefinish.py helao/core/tests/test_hooks_prefinish.py helao/core/models/action.py helao/core/models/experiment.py helao/core/models/sequence.py
git commit -m "feat(hooks): pre-finish runner and prefinish_errors on the three record models

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Action servers run pre-finish hooks (both finalizer twins)

**Files:**
- Modify: `helao/core/servers/base.py` (`__init__` block at `self.hlo_postprocessors ...`, delete `import_postprocessors`, imports), `helao/hexagon/app/action_host.py` (same), `helao/core/servers/active_finalizer.py` (`_finish`, import), `helao/hexagon/adapters/native/finalizer.py` (`_finish`, import — identical bytes)
- Modify fixtures: `helao/hexagon/tests/native_fixtures.py:45-46`, `helao/core/tests/unit_test_active_finalizer.py:91-92`, `helao/core/tests/unit_test_active_executor.py:83-84`, `helao/core/tests/test_active_golden_master.py:521-522`
- Test: create `helao/hexagon/tests/test_prefinish_action.py`; keep `helao/hexagon/tests/test_action_writes_artifacts.py` green (alias path)

**Interfaces:**
- Consumes: `prefinish_config`, `load_hook_set`, `run_prefinish`, `HookSet` (Tasks 2–4).
- Produces: `Base.prefinish_hooks: HookSet` and `ActionHost.prefinish_hooks: HookSet` (built in `__init__` from `server_cfg["prefinish_hooks"]` / alias `hlo_postprocess_libs`); `Base.import_postprocessors` and `ActionHost.import_postprocessors` are **deleted** (`OrchHost` inherits from `ActionHost` and stops calling it in Task 6 — until then `OrchHost.__init__` would fail, so Tasks 5 and 6 must land in order and Task 5's commit message says so).

- [ ] **Step 1: Thread `prefinish_hooks` through the existing harness**

In `helao/hexagon/tests/test_action_writes_artifacts.py` the helpers `_app(root, postprocess_libs=None)`, `_started_app(root, postprocess_libs=None)` and `_run_one_action(root, postprocess_libs=None)` rebuild `config_loader.CONFIG` from scratch with only the alias key. Give all three a second keyword `prefinish_hooks: dict | None = None`, pass it down by name, and in `_app` add after the `hlo_postprocess_libs` line:

```python
    if prefinish_hooks is not None:
        server["prefinish_hooks"] = prefinish_hooks
```

No existing test changes; `_run_one_action(root, postprocess_libs=["hlo_to_csv"])` keeps working.

- [ ] **Step 2: Write the failing test**

Create `helao/hexagon/tests/test_prefinish_action.py`:

```python
"""Action-level pre-finish hooks through a real ActionHost (spec §5.1 row 1).

Same harness as test_action_writes_artifacts.py: the test deployment's
ws_simulator, startup handlers run by hand, one ``acquire_data`` action.
"""

import tempfile
import textwrap
from pathlib import Path

import pytest

from helao.core.hooks import HookConfigError
from helao.helpers.yml_tools import yml_load
from helao.hexagon.tests.test_action_writes_artifacts import _run_one_action

BOOM = """
from helao.core.hooks import FinishHook


class Hook(FinishHook):
    async def run(self, ctx):
        raise RuntimeError("boom from test hook")
"""


def _act_yml(root: str) -> dict:
    ymls = [p for p in Path(root).rglob("*-act.yml")]
    assert len(ymls) == 1, ymls
    return yml_load(ymls[0].read_text())


@pytest.mark.asyncio
async def test_new_key_by_exact_action_name_runs_hlo_to_csv():
    root = tempfile.mkdtemp(prefix="helao_prefinish_")
    names = await _run_one_action(root, prefinish_hooks={"hlo_to_csv": ["acquire_data"]})
    assert any(n.endswith(".csv") for n in names), names


@pytest.mark.asyncio
async def test_new_key_for_another_action_name_does_not_run():
    root = tempfile.mkdtemp(prefix="helao_prefinish_")
    names = await _run_one_action(root, prefinish_hooks={"hlo_to_csv": ["not_this_action"]})
    assert not any(n.endswith(".csv") for n in names), names


@pytest.mark.asyncio
async def test_raising_hook_is_recorded_and_the_action_still_finishes(tmp_path):
    hook_path = tmp_path / "boom_hook.py"
    hook_path.write_text(textwrap.dedent(BOOM))
    root = tempfile.mkdtemp(prefix="helao_prefinish_")
    await _run_one_action(root, prefinish_hooks={str(hook_path): ["*"]})
    meta = _act_yml(root)
    assert "finished" in str(meta["action_status"])
    assert meta["prefinish_errors"][0]["hook"] == str(hook_path)
    assert "boom from test hook" in meta["prefinish_errors"][0]["error"]


def test_old_and_new_key_together_refused_at_startup():
    from helao.deploy.test.servers.action.ws_simulator import makeApp
    from helao.helpers import config_loader

    config_loader.CONFIG = {
        "root": tempfile.mkdtemp(prefix="helao_prefinish_"),
        "dummy": True,
        "simulation": True,
        "run_type": "simulation",
        "servers": {
            "SIM": {
                "host": "127.0.0.1",
                "port": 8002,
                "group": "action",
                "params": {"columns": {"a": 1, "b": 2}},
                "hlo_postprocess_libs": ["hlo_to_csv"],
                "prefinish_hooks": {"hlo_to_csv": ["*"]},
            }
        },
    }
    with pytest.raises(HookConfigError):
        makeApp("SIM")
```

- [ ] **Step 3: Run to verify failure**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_prefinish_action.py -v`
Expected: the three hook tests FAIL (no csv / no `prefinish_errors` key — the `prefinish_hooks` key is ignored by today's code) and the refusal test FAILS with `DID NOT RAISE`.

- [ ] **Step 4: `ActionHost` — build the hook set, delete the old loader**

In `helao/hexagon/app/action_host.py` replace

```python
        self.hlo_postprocessors: list = []
        self.hlo_postprocess_libs = self.server_cfg.get("hlo_postprocess_libs", [])
        self.import_postprocessors(
            self.hlo_postprocess_libs, self.hlo_postprocessors, HloPostProcessor
        )
```

with

```python
        # Pre-finish hooks for this server's actions (finish-hooks spec §3,
        # §5.1). `hlo_postprocess_libs` is the deprecated alias; a bad config
        # raises here rather than degrading to "no hooks".
        self.prefinish_hooks = load_hook_set(
            prefinish_config(
                self.server_cfg, "prefinish_hooks", "hlo_postprocess_libs", server_key
            ),
            phase="prefinish",
            level="action",
        )
```

Delete the whole `import_postprocessors` method (`def import_postprocessors(self, name_list, class_list, proc_class) -> None:` through its final `class_list.append(ppclass)`). Replace the import `from helao.helpers.processors import HloPostProcessor` with

```python
from helao.core.hooks.config import prefinish_config
from helao.core.hooks.loader import load_hook_set
```

(keep import order alphabetical within the `helao.` block).

- [ ] **Step 5: Legacy `Base` — same change**

In `helao/core/servers/base.py` replace

```python
        self.hlo_postprocessors: list[HloPostProcessor] = []
        self.hlo_postprocess_libs = self.server_cfg.get("hlo_postprocess_libs", [])

        self.import_postprocessors(
            self.hlo_postprocess_libs, self.hlo_postprocessors, HloPostProcessor
        )
```

with

```python
        self.prefinish_hooks = load_hook_set(
            prefinish_config(
                self.server_cfg,
                "prefinish_hooks",
                "hlo_postprocess_libs",
                self.server.server_name,
            ),
            phase="prefinish",
            level="action",
        )
```

Delete the `import_postprocessors` method (base.py:827-881). Replace `from helao.helpers.processors import HloPostProcessor` with the two `helao.core.hooks` imports above. Leave `glob`, `SourceFileLoader`, `spec_from_file_location`, `module_from_spec` imports if anything else in the file uses them (`grep -n "glob(\|SourceFileLoader\|spec_from_file_location" helao/core/servers/base.py`); remove only the ones with no remaining use.

- [ ] **Step 6: The finalizer twins — identical `_finish` edit**

In `helao/core/servers/active_finalizer.py` replace this block inside `_finish`

```python
            try:
                # call custom hlo post-processor if it exists
                if self.active.base.hlo_postprocessors:
                    for hpp, libname in zip(
                        self.active.base.hlo_postprocessors, self.active.base.hlo_postprocess_libs
                    ):
                        LOGGER.info(
                            f"Running custom HLO post-processor: {os.path.basename(libname).split('.py')[0]}"
                        )
                        loop = asyncio.get_running_loop()
                        postprocessor = hpp(self.active.action, save_root)
                        updated_file_list = await loop.run_in_executor(
                            None, postprocessor.process
                        )
                        self.active.action.files = updated_file_list
            except Exception:
                LOGGER.error("Failed to run custom HLO post-processor", exc_info=True)
```

with

```python
            # Pre-finish hooks (finish-hooks spec §5.1): may rewrite
            # action.files; a raising hook is recorded in prefinish_errors and
            # the finish goes on. Only the current split is processed, as before.
            await run_prefinish(
                self.active.base.prefinish_hooks,
                record=self.active.action,
                name=self.active.action.action_name,
                record_dir=os.path.join(
                    save_root, str(self.active.action.action_output_dir)
                ),
                server=self.active.base,
            )
```

(`save_root` is the already-computed, manual-redirected variable two lines above.) Add `from helao.core.hooks.prefinish import run_prefinish` to the import block right after `from helao.core.error import ErrorCodes`.

Then make **exactly the same two edits** in `helao/hexagon/adapters/native/finalizer.py` (its `_finish` body is byte-identical to legacy, so the same `old_string` matches). Do not run black on either file.

Verify parity: `conda run -n helao python -m pytest helao/hexagon/tests/test_native_finalizer.py::test_source_parity_with_legacy -v` → pass.

- [ ] **Step 7: Update the bare-`Base` fixtures**

In each of `helao/hexagon/tests/native_fixtures.py`, `helao/core/tests/unit_test_active_finalizer.py`, `helao/core/tests/unit_test_active_executor.py`, `helao/core/tests/test_active_golden_master.py` replace the two lines

```python
    base.hlo_postprocessors = []
    base.hlo_postprocess_libs = []
```

with

```python
    base.prefinish_hooks = HookSet.empty()
```

and add `from helao.core.hooks import HookSet` to each file's imports.

- [ ] **Step 8: Run everything this touches**

```
conda run -n helao python -m pytest helao/hexagon/tests/test_prefinish_action.py helao/hexagon/tests/test_action_writes_artifacts.py helao/hexagon/tests/test_native_finalizer.py helao/core/tests/test_active_golden_master.py -v
conda run -n helao python helao/core/tests/unit_test_active_finalizer.py
conda run -n helao python helao/core/tests/unit_test_active_executor.py
conda run -n helao pyright helao/core/servers/base.py helao/hexagon/app/action_host.py helao/core/servers/active_finalizer.py helao/hexagon/adapters/native/finalizer.py
```
Expected: all pass / exit 0 / 0 errors. `test_a_bare_named_post_processor_runs_and_emits_its_file` (the alias path) must still produce the csv.

- [ ] **Step 9: Commit**

```bash
black helao/core/servers/base.py helao/hexagon/app/action_host.py helao/hexagon/tests/native_fixtures.py helao/hexagon/tests/test_prefinish_action.py helao/hexagon/tests/test_action_writes_artifacts.py helao/core/tests/unit_test_active_finalizer.py helao/core/tests/unit_test_active_executor.py helao/core/tests/test_active_golden_master.py
git add helao/core/servers/base.py helao/hexagon/app/action_host.py helao/core/servers/active_finalizer.py helao/hexagon/adapters/native/finalizer.py helao/hexagon/tests/native_fixtures.py helao/hexagon/tests/test_prefinish_action.py helao/hexagon/tests/test_action_writes_artifacts.py helao/core/tests/unit_test_active_finalizer.py helao/core/tests/unit_test_active_executor.py helao/core/tests/test_active_golden_master.py
git commit -m "feat(hooks): action servers run pre-finish hooks; hlo_postprocess_libs becomes an alias

Both finalizer twins call run_prefinish where the HLO post-processor loop was.
import_postprocessors is deleted; the orchestrators stop calling it in the
next commit (OrchHost.__init__ is broken between the two).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Orchestrators run pre-finish hooks; experiment `finished` emitted after them

**Files:**
- Modify: `helao/core/servers/orch.py:178-188`, `helao/hexagon/app/orch_host.py:190-204`, `helao/hexagon/app/orch_lifecycle.py` (`finish_active_sequence`, `finish_active_experiment`, imports)
- Modify tests: `helao/core/tests/unit_test_orch_lifecycle.py` (fixture + new ordering/error checks), `helao/core/tests/test_orch_dispatch_golden_master.py:257-260`

**Interfaces:**
- Consumes: `prefinish_config`, `load_hook_set`, `run_prefinish`, `HookSet`.
- Produces: `Orch.prefinish_experiment_hooks: HookSet`, `Orch.prefinish_sequence_hooks: HookSet` (and the same on `OrchHost`), from `prefinish_experiment_hooks`/alias `exp_postprocess_libs` and `prefinish_sequence_hooks`/alias `seq_postprocess_libs`. `RunLifecycle` reads them through `orch` at call time.

- [ ] **Step 1: Extend the standalone lifecycle test with failing checks**

In `helao/core/tests/unit_test_orch_lifecycle.py`:

Replace in `_make_orch`
```python
    orch.seq_postprocessors = []
    orch.seq_postprocess_libs = []
    orch.exp_postprocessors = []
    orch.exp_postprocess_libs = []
```
with
```python
    orch.prefinish_sequence_hooks = HookSet.empty()
    orch.prefinish_experiment_hooks = HookSet.empty()
    orch.helaodirs = SimpleNamespace(save_root=tempfile.mkdtemp(prefix="orch_lc_"))
```
and add imports `import tempfile`, `from types import SimpleNamespace`, `from helao.core.hooks import FinishHook, HookSet`.

Add two checks after `_check_finish_active_experiment`:

```python
class _ProbeHook(FinishHook):
    """Records how many `finished` lbuf puts had happened when it ran, and the
    record name it was handed."""

    def __init__(self, recorded):
        self.recorded = recorded
        self.seen = []

    async def run(self, ctx):
        self.seen.append((len(self.recorded["put_lbuf"]), ctx.record.experiment_name))


class _BoomHook(FinishHook):
    async def run(self, ctx):
        raise RuntimeError("exp hook boom")


async def _check_experiment_hooks_run_before_finished_is_emitted() -> bool:
    orch, recorded = _make_orch()
    orch.aloop = asyncio.get_running_loop()
    probe = _ProbeHook(recorded)
    orch.prefinish_experiment_hooks = HookSet(
        cfg={"probe": {"exp1": None}}, hooks={"probe": probe}
    )
    orch.active_sequence = _mk_sequence("seq1")
    orch.active_experiment = _mk_experiment("exp1")
    with _MoveDirRecorder():
        await orch.finish_active_experiment()
        await _drain_tasks()
    # the hook saw ZERO finished puts (spec §5.1: put_lbuf moves after hooks),
    # one put happened overall, and the experiment still finished and wrote.
    return (
        probe.seen == [(0, "exp1")]
        and len(recorded["put_lbuf"]) == 1
        and recorded["write_exp"] == ["exp1"]
        and orch.last_experiment.prefinish_errors == []
    )


async def _check_failing_hooks_are_recorded_and_finish_goes_on() -> bool:
    orch, recorded = _make_orch()
    orch.aloop = asyncio.get_running_loop()
    orch.prefinish_experiment_hooks = HookSet(cfg={"boom": {"*": None}}, hooks={"boom": _BoomHook()})
    orch.prefinish_sequence_hooks = HookSet(cfg={"boom": {"*": None}}, hooks={"boom": _BoomHook()})
    orch.active_sequence = _mk_sequence("seq1")
    orch.active_experiment = _mk_experiment("exp1")
    with _MoveDirRecorder():
        await orch.finish_active_experiment()
        await orch.finish_active_sequence()
        await _drain_tasks()
    return (
        [e["hook"] for e in orch.last_experiment.prefinish_errors] == ["boom"]
        and [e["hook"] for e in orch.last_sequence.prefinish_errors] == ["boom"]
        and recorded["write_exp"] == ["exp1"]
        and recorded["write_seq"] == ["seq1", "seq1"]
    )
```

Register them in `_run_checks` (`"exp_hooks_before_finished": await _check_experiment_hooks_run_before_finished_is_emitted(), "failing_hooks_recorded": await _check_failing_hooks_are_recorded_and_finish_goes_on(),`) and add two `reporter.check(...)` lines in `orch_lifecycle_unit_test` under a new `reporter.section("pre-finish hooks")`:

```python
    reporter.section("pre-finish hooks")
    reporter.check(
        "experiment hooks run BEFORE the finished lbuf put (spec 5.1 reorder)",
        lambda: res["exp_hooks_before_finished"],
    )
    reporter.check(
        "a raising exp/seq hook lands in prefinish_errors and the record still finishes",
        lambda: res["failing_hooks_recorded"],
    )
```

- [ ] **Step 2: Run to verify failure**

Run: `conda run -n helao python helao/core/tests/unit_test_orch_lifecycle.py`
Expected: the script fails before reaching the checks — `_init_collaborators()` is fine, but `finish_active_experiment` raises `AttributeError: 'Orch' object has no attribute 'exp_postprocessors'` (the fixture no longer sets it), printed by the `except Exception` in `orch_lifecycle_unit_test`, exit code 1. (After Step 3 alone the two new checks would print FAIL: the probe sees `(1, "exp1")` until the reorder in Step 4.)

- [ ] **Step 3: Both orchestrator `__init__`s**

In `helao/core/servers/orch.py` replace lines

```python
        self.exp_postprocessors: list[MetaProcessor] = []
        self.exp_postprocess_libs = self.server_cfg.get("exp_postprocess_libs", [])
        self.import_postprocessors(
            self.exp_postprocess_libs, self.exp_postprocessors, MetaProcessor
        )

        self.seq_postprocessors: list[MetaProcessor] = []
        self.seq_postprocess_libs = self.server_cfg.get("seq_postprocess_libs", [])
        self.import_postprocessors(
            self.seq_postprocess_libs, self.seq_postprocessors, MetaProcessor
        )
```

with

```python
        # Experiment/sequence pre-finish hooks (finish-hooks spec §3, §5.1);
        # exp_/seq_postprocess_libs are the deprecated aliases.
        label = self.server.server_name
        self.prefinish_experiment_hooks = load_hook_set(
            prefinish_config(
                self.server_cfg,
                "prefinish_experiment_hooks",
                "exp_postprocess_libs",
                label,
            ),
            phase="prefinish",
            level="experiment",
        )
        self.prefinish_sequence_hooks = load_hook_set(
            prefinish_config(
                self.server_cfg,
                "prefinish_sequence_hooks",
                "seq_postprocess_libs",
                label,
            ),
            phase="prefinish",
            level="sequence",
        )
```

Replace `from helao.helpers.processors import MetaProcessor` with `from helao.core.hooks.config import prefinish_config` and `from helao.core.hooks.loader import load_hook_set`.

In `helao/hexagon/app/orch_host.py` replace the block from the comment `# --- orch.py:178-188: meta post-processors ---` through the `seq_postprocess_libs` `import_postprocessors(...)` call with the same code, using `label = self.server_key`. Replace the `MetaProcessor` import the same way.

- [ ] **Step 4: `orch_lifecycle.py`**

Add `from helao.core.hooks.prefinish import run_prefinish` after `from helao.core.models.hlostatus import HloStatus`.

In `finish_active_sequence` replace

```python
            # post-process experiment object
            if orch.seq_postprocessors:
                for spp, libname in zip(
                    orch.seq_postprocessors, orch.seq_postprocess_libs
                ):
                    LOGGER.info(
                        f"Running custom SEQ post-processor: {os.path.basename(libname).split('.py')[0]}"
                    )
                    loop = asyncio.get_running_loop()
                    postprocessor = spp(orch.active_sequence, orch)
                    await loop.run_in_executor(None, postprocessor.process)
```

with

```python
            # pre-finish hooks (spec §5.1); may mutate the sequence
            await run_prefinish(
                orch.prefinish_sequence_hooks,
                record=orch.active_sequence,
                name=orch.active_sequence.sequence_name,
                record_dir=os.path.join(
                    str(orch.helaodirs.save_root),
                    orch.active_sequence.get_sequence_dir(),
                ),
                server=orch,
            )
```

In `finish_active_experiment`: **delete** the `await orch.put_lbuf({... "status": HloStatus.finished.value ...})` call that sits right after the `LOGGER.info(f"finished exp uuid is: ...")` line, and replace

```python
            # post-process experiment object
            if orch.exp_postprocessors:
                for epp, libname in zip(
                    orch.exp_postprocessors, orch.exp_postprocess_libs
                ):
                    LOGGER.info(
                        f"Running custom EXP post-processor: {os.path.basename(libname).split('.py')[0]}"
                    )
                    loop = asyncio.get_running_loop()
                    postprocessor = epp(orch.active_experiment, orch)
                    await loop.run_in_executor(None, postprocessor.process)
```

with

```python
            # pre-finish hooks (spec §5.1); may mutate the experiment
            await run_prefinish(
                orch.prefinish_experiment_hooks,
                record=orch.active_experiment,
                name=orch.active_experiment.experiment_name,
                record_dir=os.path.join(
                    str(orch.helaodirs.save_root),
                    orch.active_experiment.get_experiment_dir(),
                ),
                server=orch,
            )

            # `finished` is emitted only after the hooks have had their say
            # (spec §5.1: this used to sit above them, unlike actions and
            # sequences).
            await orch.put_lbuf(
                {
                    orch.active_experiment.experiment_uuid: {
                        "experiment_name": orch.active_experiment.experiment_name,
                        "status": HloStatus.finished.value,
                    }
                }
            )
```

Update the module docstring's "postprocessors" wording to "pre-finish hooks" (one phrase, no other prose changes).

- [ ] **Step 5: Golden-master fixture**

In `helao/core/tests/test_orch_dispatch_golden_master.py` replace

```python
    orch.exp_postprocessors = []
    orch.exp_postprocess_libs = []
    orch.seq_postprocessors = []
    orch.seq_postprocess_libs = []
```

with

```python
    orch.prefinish_experiment_hooks = HookSet.empty()
    orch.prefinish_sequence_hooks = HookSet.empty()
```

plus `from helao.core.hooks import HookSet`. (Its `_make_orch` already sets `orch.helaodirs`, line 188.)

- [ ] **Step 6: Verify**

```
conda run -n helao python helao/core/tests/unit_test_orch_lifecycle.py
conda run -n helao python -m pytest helao/core/tests/test_orch_dispatch_golden_master.py helao/hexagon/tests/test_orch_effects.py helao/hexagon/tests/test_orch_host_surface.py helao/hexagon/tests/test_orch_host_member_coverage.py -q
conda run -n helao pyright helao/core/servers/orch.py helao/hexagon/app/orch_host.py helao/hexagon/app/orch_lifecycle.py
```
Expected: exit 0, all pass, 0 errors. Then a real group with the alias configs: `conda run -n helao --no-capture-output python -m pytest helao/hexagon/tests/test_orch_legacy_parity_live.py -q` (uses the golden configs with `append_params` via `exp_/seq_postprocess_libs`) → pass.

- [ ] **Step 7: Commit**

```bash
black helao/core/servers/orch.py helao/hexagon/app/orch_host.py helao/hexagon/app/orch_lifecycle.py helao/core/tests/unit_test_orch_lifecycle.py helao/core/tests/test_orch_dispatch_golden_master.py
git add helao/core/servers/orch.py helao/hexagon/app/orch_host.py helao/hexagon/app/orch_lifecycle.py helao/core/tests/unit_test_orch_lifecycle.py helao/core/tests/test_orch_dispatch_golden_master.py
git commit -m "feat(hooks): orchestrators run exp/seq pre-finish hooks; experiment finished emitted after them

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 7: `.prg` completeness accepts `synced: true`

**Files:**
- Modify: `helao/helpers/run_state.py` (`_prg_is_complete`, ~:249)
- Test: `helao/core/tests/test_run_state.py` (append)

**Interfaces:**
- Produces: `_prg_is_complete(prg_path) -> bool` with the A5 rule. It is the single completeness check: `HelaoYml.status`, `enqueue_yml`'s guard and `rebuild_from_tree` all call it, so this one edit covers "SYNC's own already-synced check" (spec §6.3).

- [ ] **Step 1: Write the failing tests**

Append to `helao/core/tests/test_run_state.py` (it already imports `_prg_is_complete`-adjacent helpers; add `from helao.helpers.run_state import _prg_is_complete` to its imports if absent):

```python
def _prg(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "x.prg"
    p.write_text(text)
    return p


def test_prg_synced_true_is_complete(tmp_path: Path):
    assert _prg_is_complete(
        _prg(tmp_path, "yml: /r/x.yml\napi: false\ns3: false\nhooks:\n  push_api:\n    state: done\nsynced: true\n")
    )


def test_prg_synced_false_is_incomplete_even_with_legacy_flags(tmp_path: Path):
    """A record inside the new chain is judged by `synced`, never by s3+api
    (settled decision A5): s3_upload sets both flags before later hooks run."""
    assert not _prg_is_complete(
        _prg(tmp_path, "yml: /r/x.yml\napi: true\ns3: true\nhooks: {}\nsynced: false\n")
    )


def test_prg_without_synced_key_uses_legacy_rule(tmp_path: Path):
    assert _prg_is_complete(_prg(tmp_path, "yml: /r/x.yml\napi: true\ns3: true\n"))
    assert not _prg_is_complete(_prg(tmp_path, "yml: /r/x.yml\napi: false\ns3: true\n"))
```

- [ ] **Step 2: Run to verify failure**

Run: `conda run -n helao python -m pytest helao/core/tests/test_run_state.py -k prg -v`
Expected: `test_prg_synced_true_is_complete` and `test_prg_synced_false_is_incomplete_even_with_legacy_flags` FAIL; the legacy-rule test passes.

- [ ] **Step 3: Implement**

Replace the body of `_prg_is_complete` after the `try/except OSError` with:

```python
    # A record that entered the post-finish chain carries `synced` (the chain
    # runner writes `synced: false` before its first hook), and only that flag
    # decides: `s3`/`api` are set by the s3_upload hook while later hooks may
    # still be pending. A sidecar without the key predates the chain and is
    # judged by the legacy pair (finish-hooks spec 6.3).
    if "synced: true" in lines:
        return True
    if any(line.startswith("synced:") for line in lines):
        return False
    return "s3: true" in lines and "api: true" in lines
```

and extend the docstring's first paragraph with one sentence: "``synced: true`` (finish-hooks) or, for a sidecar without a ``synced`` key, the legacy ``s3: true`` + ``api: true`` pair."

- [ ] **Step 4: Verify**

`conda run -n helao python -m pytest helao/core/tests/test_run_state.py helao/core/tests/test_run_state_wiring.py helao/core/tests/test_sync_postfinish_golden.py -q` → pass. `conda run -n helao pyright helao/helpers/run_state.py` → 0 errors.

- [ ] **Step 5: Commit**

```bash
black helao/helpers/run_state.py helao/core/tests/test_run_state.py
git add helao/helpers/run_state.py helao/core/tests/test_run_state.py
git commit -m "feat(sync): .prg completeness reads synced:, falling back to s3+api for pre-hook sidecars

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Post-finish chain runner

**Files:**
- Create: `helao/core/hooks/postfinish.py`
- Test: `helao/core/tests/test_hooks_postfinish.py`

**Interfaces:**
- Consumes: `HookSet`, `PostfinishContext`, `FinishHook`; a `Progress` (`.dict`, `.write_dict()`, `.yml.type`, `.yml.meta`, `.yml.target`) from either sync twin; `syncer.postfinish: dict[str, HookSet]` (Task 9 adds it to `SyncDriver`; the tests here use a `SimpleNamespace`).
- Produces: `run_postfinish_chain(syncer, prog, opts: dict) -> bool` in `helao.core.hooks.postfinish`. Writes `prog.dict["hooks"][name] = {"state": "done"|"failed", "ts": iso, ["error": str]}` and `prog.dict["synced"]` atomically via `prog.write_dict()`. Returns `True` iff every **blocking** hook in the selected chain is `done`.

- [ ] **Step 1: Write the failing tests**

Create `helao/core/tests/test_hooks_postfinish.py`:

```python
"""Chain execution semantics (spec §6.2), on a real Progress over a tmp tree."""

from types import SimpleNamespace

import pytest

import helao.core.drivers.data.sync_driver as legacy_mod
import helao.hexagon.adapters.native.sync_driver as native_mod
from helao.core.hooks import FinishHook, HookSet
from helao.core.hooks.postfinish import run_postfinish_chain
from helao.hexagon.tests.sync_fixtures import make_action, make_exp_tree, mk_uuid


class _Hook(FinishHook):
    def __init__(self, blocking=True, fail=False):
        self.blocking, self.fail, self.calls = blocking, fail, 0

    async def run(self, ctx):
        self.calls += 1
        if self.fail:
            raise RuntimeError(f"nope {self.calls}")
        ctx.prg.dict.setdefault("touched", []).append(ctx.args)


def _syncer(action_chain: dict[str, FinishHook], cfg: dict):
    return SimpleNamespace(
        postfinish={
            "action": HookSet(cfg=cfg, hooks=action_chain),
            "experiment": HookSet.empty(),
            "sequence": HookSet.empty(),
        }
    )


def _prog(tmp_path, mod):
    act = make_action(make_exp_tree(tmp_path, "RUNS", mk_uuid(1)), 0)
    return mod.Progress(act)


@pytest.mark.parametrize("mod", [legacy_mod, native_mod])
@pytest.mark.asyncio
async def test_all_done_marks_synced_and_records_states(tmp_path, mod):
    a, b = _Hook(), _Hook(blocking=False)
    syncer = _syncer({"a": a, "b": b}, {"a": {"*": {"x": 1}}, "b": {"test_action": None}})
    prog = _prog(tmp_path, mod)
    assert await run_postfinish_chain(syncer, prog, opts={"compress": False}) is True
    on_disk = mod.Progress(prog.prg).dict
    assert on_disk["synced"] is True
    assert on_disk["hooks"]["a"]["state"] == "done" and "T" in on_disk["hooks"]["a"]["ts"]
    assert on_disk["hooks"]["b"]["state"] == "done"
    assert on_disk["touched"] == [{"x": 1}, None]


@pytest.mark.parametrize("mod", [legacy_mod, native_mod])
@pytest.mark.asyncio
async def test_blocking_failure_stops_chain_and_resumes_at_failed_hook(tmp_path, mod):
    a, b, c = _Hook(), _Hook(fail=True), _Hook()
    syncer = _syncer({"a": a, "b": b, "c": c}, {k: {"*": None} for k in "abc"})
    prog = _prog(tmp_path, mod)
    assert await run_postfinish_chain(syncer, prog, opts={}) is False
    d = mod.Progress(prog.prg).dict
    assert d["synced"] is False
    assert d["hooks"]["a"]["state"] == "done"
    assert d["hooks"]["b"] == {"state": "failed", "ts": d["hooks"]["b"]["ts"], "error": "RuntimeError: nope 1"}
    assert "c" not in d["hooks"] and c.calls == 0
    # next pass: a is not re-run, b is retried and now succeeds, c runs
    b.fail = False
    assert await run_postfinish_chain(syncer, mod.Progress(prog.prg), opts={}) is True
    d = mod.Progress(prog.prg).dict
    assert (a.calls, b.calls, c.calls) == (1, 2, 1)
    assert d["synced"] is True and d["hooks"]["b"]["state"] == "done"
    assert "error" not in d["hooks"]["b"]


@pytest.mark.parametrize("mod", [legacy_mod, native_mod])
@pytest.mark.asyncio
async def test_non_blocking_failure_is_recorded_alerted_and_does_not_block_synced(tmp_path, mod, caplog):
    a, b, c = _Hook(), _Hook(blocking=False, fail=True), _Hook()
    syncer = _syncer({"a": a, "b": b, "c": c}, {k: {"*": None} for k in "abc"})
    prog = _prog(tmp_path, mod)
    assert await run_postfinish_chain(syncer, prog, opts={}) is True
    d = mod.Progress(prog.prg).dict
    assert d["synced"] is True and c.calls == 1
    assert d["hooks"]["b"]["state"] == "failed" and "nope 1" in d["hooks"]["b"]["error"]
    assert "b" in caplog.text
    # not retried automatically on the next pass (spec 6.2)
    assert await run_postfinish_chain(syncer, mod.Progress(prog.prg), opts={}) is True
    assert b.calls == 1
    # clearing the entry re-arms it
    p = mod.Progress(prog.prg)
    del p.dict["hooks"]["b"]
    p.write_dict()
    b.fail = False
    assert await run_postfinish_chain(syncer, mod.Progress(prog.prg), opts={}) is True
    assert b.calls == 2 and mod.Progress(prog.prg).dict["hooks"]["b"]["state"] == "done"


@pytest.mark.parametrize("mod", [legacy_mod, native_mod])
@pytest.mark.asyncio
async def test_hooks_and_synced_false_are_written_before_the_first_hook_runs(tmp_path, mod):
    class Peek(FinishHook):
        async def run(self, ctx):
            self.on_disk = mod.Progress(ctx.prg.prg).dict

    peek = Peek()
    syncer = _syncer({"peek": peek}, {"peek": {"*": None}})
    prog = _prog(tmp_path, mod)
    assert "hooks" not in prog.dict and "synced" not in prog.dict
    await run_postfinish_chain(syncer, prog, opts={})
    assert peek.on_disk["hooks"] == {} and peek.on_disk["synced"] is False


@pytest.mark.parametrize("mod", [legacy_mod, native_mod])
@pytest.mark.asyncio
async def test_empty_chain_is_synced(tmp_path, mod):
    syncer = _syncer({}, {})
    prog = _prog(tmp_path, mod)
    assert await run_postfinish_chain(syncer, prog, opts={}) is True
    assert mod.Progress(prog.prg).dict["synced"] is True


@pytest.mark.parametrize("mod", [legacy_mod, native_mod])
@pytest.mark.asyncio
async def test_context_carries_yml_prg_syncer_args_opts(tmp_path, mod):
    seen = {}

    class Grab(FinishHook):
        async def run(self, ctx):
            seen.update(yml=ctx.yml, prg=ctx.prg, syncer=ctx.syncer, args=ctx.args, opts=ctx.opts)

    syncer = _syncer({"g": Grab()}, {"g": {"*": {"k": "v"}}})
    prog = _prog(tmp_path, mod)
    await run_postfinish_chain(syncer, prog, opts={"force_s3": True})
    assert seen["prg"] is prog and seen["syncer"] is syncer
    assert seen["yml"].target == prog.yml.target
    assert seen["args"] == {"k": "v"} and seen["opts"] == {"force_s3": True}
```

- [ ] **Step 2: Run to verify failure**

Run: `conda run -n helao python -m pytest helao/core/tests/test_hooks_postfinish.py -v`
Expected: `ModuleNotFoundError: No module named 'helao.core.hooks.postfinish'`.

- [ ] **Step 3: Implement**

Create `helao/core/hooks/postfinish.py`:

```python
"""Post-finish chain runner (spec §6.2). State lives in the ``.prg`` sidecar.

Per record, per ``sync_yml`` pass, for each matching hook in config order:
``done`` -> skip; non-blocking ``failed`` -> skip (clearing the entry re-arms
it); otherwise run it. Success -> ``done``; blocking failure -> ``failed`` and
stop (the record stays unsynced and the next pass re-runs this hook);
non-blocking failure -> ``failed`` + alert, continue. The chain reports synced
when every blocking hook in it is ``done``.

``hooks: {}`` and ``synced: false`` are written before the first hook so that
``_prg_is_complete`` (helao.helpers.run_state) judges this record by
``synced`` and never by the legacy ``s3``/``api`` pair the s3_upload hook
sets mid-chain (settled decision A5).
"""

__all__ = ["run_postfinish_chain"]

from datetime import datetime

from helao.core.hooks import HookSet, PostfinishContext
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


def _ts() -> str:
    return datetime.now().isoformat(timespec="seconds")


async def run_postfinish_chain(syncer, prog, opts: dict) -> bool:
    """Run the record's post-finish chain; return whether it is now synced."""
    level = prog.yml.type
    name = prog.yml.meta.get(f"{level}_name", "NA")
    hook_set = (getattr(syncer, "postfinish", None) or {}).get(level) or HookSet.empty()
    chain = hook_set.select(name)

    states = prog.dict.setdefault("hooks", {})
    if "synced" not in prog.dict:
        prog.dict["synced"] = False
    prog.write_dict()

    for hook_name, hook, args in chain:
        entry = states.get(hook_name) or {}
        if entry.get("state") == "done":
            continue
        if entry.get("state") == "failed" and not hook.blocking:
            continue
        LOGGER.info(f"Running post-finish hook {hook_name!r} for {level} {name}")
        ctx = PostfinishContext(yml=prog.yml, prg=prog, syncer=syncer, args=args, opts=opts)
        try:
            await hook.run(ctx)
        except Exception as exc:
            states[hook_name] = {
                "state": "failed",
                "ts": _ts(),
                "error": f"{type(exc).__name__}: {exc}",
            }
            prog.write_dict()
            if hook.blocking:
                LOGGER.error(
                    f"blocking post-finish hook {hook_name!r} failed for {level} "
                    f"{name} ({prog.yml.target.name}); chain stopped, record stays "
                    "unsynced for the next pass",
                    exc_info=True,
                )
                prog.dict["synced"] = False
                prog.write_dict()
                return False
            LOGGER.error(
                f"non-blocking post-finish hook {hook_name!r} failed for {level} {name}",
                exc_info=True,
            )
            LOGGER.alert(  # type: ignore[attr-defined]
                f"non-blocking post-finish hook {hook_name!r} failed for {level} "
                f"{name} ({prog.yml.target.name}): {type(exc).__name__}: {exc}; "
                "clear its entry in the .prg to re-arm it"
            )
            continue
        states[hook_name] = {"state": "done", "ts": _ts()}
        prog.write_dict()

    synced = all(
        states.get(hook_name, {}).get("state") == "done"
        for hook_name, hook, _ in chain
        if hook.blocking
    )
    prog.dict["synced"] = synced
    prog.write_dict()
    return synced
```

- [ ] **Step 4: Verify**

`conda run -n helao python -m pytest helao/core/tests/test_hooks_postfinish.py -v` → all pass. `conda run -n helao pyright helao/core/hooks` → 0 errors.

- [ ] **Step 5: Commit**

```bash
black helao/core/hooks/postfinish.py helao/core/tests/test_hooks_postfinish.py
git add helao/core/hooks/postfinish.py helao/core/tests/test_hooks_postfinish.py
git commit -m "feat(hooks): post-finish chain runner with .prg hooks/synced state

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 9: SYNC — `sync_yml` core/chain split, `s3_upload` and `dispatch_analysis` built-ins (both twins)

**Files:**
- Create: `helao/core/hooks/builtin/s3_upload.py`, `helao/core/hooks/builtin/dispatch_analysis.py`
- Modify: `helao/core/drivers/data/sync_driver.py` (imports; `SyncDriver.__init__`; `sync_yml`; `HelaoSyncer.__init__`), `helao/hexagon/adapters/native/sync_driver.py` (imports + verbatim region copied from legacy), `helao/hexagon/adapters/native/native_syncer.py` (`NativeSyncer.__init__`)
- Modify tests: `helao/core/tests/test_sync_hlo_rename_warning.py` (patch point, A13)
- Test: create `helao/core/tests/test_sync_postfinish_chain.py`; Task 1's golden and Task 8's runner tests must stay green

**Interfaces:**
- Consumes: `postfinish_config`, `load_hook_set`, `run_postfinish_chain`, `PostfinishContext` (`opts` keys `retries`, `force_s3`, `force_api`, `compress`), `HookConfigError`.
- Produces:
  - `SyncDriver.__init__(self, config: dict, helaodirs: HelaoDirs, postfinish_hooks: Optional[dict] = None)`; attribute `self.postfinish: dict[str, HookSet]` (keys `action`/`experiment`/`sequence`); attribute `self.auto_analyses` is **removed**.
  - `sync_yml` keeps its signature and return convention (`True` nothing to do, `False` not synced this pass, progress dict when synced) and now runs the chain instead of inline S3 code.
  - `helao.core.hooks.builtin.s3_upload.Hook` (`blocking = True`, `phase = "postfinish"`), `helao.core.hooks.builtin.dispatch_analysis.Hook` (`blocking = False`, `phase = "postfinish"`, `levels = ("experiment", "sequence")`).
  - `HelaoSyncer`/`NativeSyncer` pass the resolved SYNC entry's `postfinish_hooks` through.

Order of work inside this task: (a) built-ins, (b) legacy twin, (c) run golden + parity pins + new tests against legacy (native still fails parity), (d) copy the region into the native twin with the script, (e) `NativeSyncer`, (f) everything green.

- [ ] **Step 1: Write the failing tests**

Create `helao/core/tests/test_sync_postfinish_chain.py`:

```python
"""sync_yml runs the configured post-finish chain (spec §6), both drivers."""

import asyncio
import textwrap
from pathlib import Path

import pytest

import helao.core.drivers.data.sync_driver as legacy_mod
import helao.hexagon.adapters.native.sync_driver as native_mod
from helao.core.hooks import HookConfigError
from helao.helpers import dispatcher as dispatcher_mod
from helao.helpers.run_state import DONE
from helao.hexagon.tests.sync_fixtures import (
    make_action,
    make_exp_tree,
    make_sync_driver,
    mk_uuid,
    teardown_driver,
    ts,
    write_yml,
)

MODS = [legacy_mod, native_mod]

FAILING_HOOK = """
from helao.core.hooks import FinishHook
class Hook(FinishHook):
    blocking = {blocking}
    phase = "postfinish"
    async def run(self, ctx):
        raise RuntimeError("push failed")
"""

def _hook_file(tmp_path, name, body) -> str:
    p = tmp_path / f"{name}.py"
    p.write_text(textwrap.dedent(body))
    return str(p)


def _accept(drv):
    async def accept(msg=None, target=None, compress=False, retries=5):
        return True

    drv.to_s3 = accept


def _no_requeue(drv):
    async def record(upath, rank=0, rank_limit=-5):
        return None

    drv.enqueue_yml = record


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_driver_exposes_default_chain_and_no_auto_analyses(tmp_path, mod):
    drv = make_sync_driver(tmp_path, mod.SyncDriver)
    try:
        assert list(drv.postfinish) == ["action", "experiment", "sequence"]
        assert list(drv.postfinish["sequence"].cfg) == ["s3_upload"]
        assert not hasattr(drv, "auto_analyses")
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_explicit_config_owns_the_chain_and_bad_hook_raises_at_startup(tmp_path, mod):
    with pytest.raises(HookConfigError):
        make_sync_driver(
            tmp_path, mod.SyncDriver, postfinish_hooks={"action": {"no_such_hook": ["*"]}}
        )
    drv = make_sync_driver(tmp_path, mod.SyncDriver, postfinish_hooks={"action": {}})
    try:
        assert drv.postfinish["action"].cfg == {} and drv.postfinish["sequence"].cfg == {}
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_blocking_failure_after_s3_keeps_record_unsynced_and_retry_resumes(tmp_path, mod):
    failing = _hook_file(tmp_path, "push_api", FAILING_HOOK.format(blocking="True"))
    drv = make_sync_driver(
        tmp_path,
        mod.SyncDriver,
        postfinish_hooks={"action": {"s3_upload": ["*"], failing: ["*"]}},
    )
    try:
        _accept(drv)
        _no_requeue(drv)
        journal = []
        drv._journal = lambda yml_path, state: journal.append((yml_path.name, state))
        act = make_action(make_exp_tree(tmp_path, "RUNS", mk_uuid(1)), 0)
        assert await asyncio.wait_for(drv.sync_yml(yml_path=act), timeout=15) is False
        d = mod.Progress(act).dict
        assert d["s3"] is True and d["api"] is True  # s3_upload ran and finished
        assert d["hooks"]["s3_upload"]["state"] == "done"
        assert d["hooks"][failing]["state"] == "failed"
        assert d["synced"] is False
        assert mod.HelaoYml(act).status == "finished"  # not synced despite s3+api
        assert journal == []
        # retry: the hook instance is created once per server, so "fix" it by
        # swapping its run in place, then run the same record again.
        drv.postfinish["action"].hooks[failing].run = _ok_run  # type: ignore[assignment]
        result = await asyncio.wait_for(drv.sync_yml(yml_path=act), timeout=15)
        assert isinstance(result, dict)
        d = mod.Progress(act).dict
        assert d["synced"] is True and d["hooks"][failing]["state"] == "done"
        assert mod.HelaoYml(act).status == "synced"
        assert journal == [(act.name, DONE)]
    finally:
        await teardown_driver(drv)


async def _ok_run(ctx):
    return None


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_non_blocking_failure_still_syncs_journals_and_requeues_parent(tmp_path, mod, caplog):
    failing = _hook_file(tmp_path, "notify", FAILING_HOOK.format(blocking="False"))
    drv = make_sync_driver(
        tmp_path,
        mod.SyncDriver,
        postfinish_hooks={"action": {"s3_upload": ["*"], failing: ["*"]}},
    )
    try:
        _accept(drv)
        calls = []

        async def record(upath, rank=0, rank_limit=-5):
            calls.append((str(upath), rank))

        drv.enqueue_yml = record
        journal = []
        drv._journal = lambda yml_path, state: journal.append(state)
        exp_yml = make_exp_tree(tmp_path, "RUNS", mk_uuid(1))
        act = make_action(exp_yml, 0)
        result = await asyncio.wait_for(drv.sync_yml(yml_path=act), timeout=15)
        assert isinstance(result, dict) and result["synced"] is True
        d = mod.Progress(act).dict
        assert d["hooks"][failing]["state"] == "failed" and "push failed" in d["hooks"][failing]["error"]
        assert mod.HelaoYml(act).status == "synced"
        assert journal == [DONE]
        assert (str(exp_yml), 1) in calls
        assert "push failed" in caplog.text
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_legacy_complete_prg_runs_nothing(tmp_path, mod):
    """A record synced before the hooks existed (s3+api, no `synced` key) is
    complete: sync_yml returns True at the already-synced gate, the chain never
    starts (no hooks/synced keys appear), and a blocking hook that would have
    failed the record is never reached."""
    failing = _hook_file(tmp_path, "would_fail", FAILING_HOOK.format(blocking="True"))
    drv = make_sync_driver(
        tmp_path, mod.SyncDriver, postfinish_hooks={"action": {"s3_upload": ["*"], failing: ["*"]}}
    )
    try:
        act = make_action(make_exp_tree(tmp_path, "RUNS", mk_uuid(1)), 0)
        before = f"yml: {act}\napi: true\ns3: true\nfiles_pending: []\nfiles_s3: {{}}\n"
        act.with_suffix(".prg").write_text(before)
        assert await asyncio.wait_for(drv.sync_yml(yml_path=act), timeout=15) is True
        assert act.with_suffix(".prg").read_text() == before
        assert mod.HelaoYml(act).status == "synced"
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_dispatch_analysis_at_experiment_level_sends_experiment_path(tmp_path, mod, monkeypatch):
    sent = []

    async def fake_dispatch(world_config_dict=None, A=None, **kw):
        sent.append((world_config_dict, A))
        return {}, None

    monkeypatch.setattr(dispatcher_mod, "async_action_dispatcher", fake_dispatch)
    ana = {"server_key": "ANA", "host": "127.0.0.1", "port": 1, "endpoint": "ana_exp", "params": {"q": 2}}
    drv = make_sync_driver(
        tmp_path,
        mod.SyncDriver,
        postfinish_hooks={
            "experiment": {"s3_upload": ["*"], "dispatch_analysis": {"test_exp": ana}}
        },
    )
    try:
        _accept(drv)
        _no_requeue(drv)
        exp_yml = make_exp_tree(tmp_path, "RUNS", mk_uuid(1))
        result = await asyncio.wait_for(drv.sync_yml(yml_path=exp_yml, rank=1), timeout=15)
        assert isinstance(result, dict)
        assert len(sent) == 1
        world, A = sent[0]
        assert world == {"servers": {"ANA": ana}}
        assert A.action_name == "ana_exp"
        assert A.action_params == {"experiment_path": str(exp_yml.parent), "params": {"q": 2}}
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_dispatch_analysis_without_host_port_resolves_world_config_or_raises(tmp_path, mod):
    drv = make_sync_driver(
        tmp_path,
        mod.SyncDriver,
        postfinish_hooks={
            "sequence": {"dispatch_analysis": {"test_seq": {"server_key": "ANA", "endpoint": "e"}}}
        },
    )
    try:
        _no_requeue(drv)
        exp_yml = make_exp_tree(tmp_path, "RUNS", mk_uuid(1))
        seq_yml = exp_yml.parent.parent / f"{ts(0)}-seq.yml"
        write_yml(seq_yml, {"sequence_uuid": mk_uuid(999), "sequence_name": "test_seq"})
        # the exp under it is unsynced -> the sequence gate re-queues; write a
        # legacy-complete prg for it so the sequence proceeds to its chain.
        exp_yml.with_suffix(".prg").write_text(
            f"yml: {exp_yml}\napi: true\ns3: true\n"
        )
        await asyncio.wait_for(drv.sync_yml(yml_path=seq_yml, rank=2), timeout=15)
        d = mod.Progress(seq_yml).dict
        assert d["hooks"]["dispatch_analysis"]["state"] == "failed"
        assert "ANA" in d["hooks"]["dispatch_analysis"]["error"]
        assert d["synced"] is True  # non-blocking; the chain has no blocking hook
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_dispatch_analysis_refused_at_action_level(tmp_path, mod):
    with pytest.raises(HookConfigError) as ei:
        make_sync_driver(
            tmp_path,
            mod.SyncDriver,
            postfinish_hooks={
                "action": {"dispatch_analysis": {"a": {"server_key": "A", "endpoint": "e"}}}
            },
        )
    assert "dispatch_analysis" in str(ei.value)
```

Also update `helao/core/tests/test_sync_hlo_rename_warning.py`: replace `monkeypatch.setattr(mod, "read_hlo", lambda fp: ({}, {}))` with

```python
    import helao.core.hooks.builtin.s3_upload as s3_upload_mod

    monkeypatch.setattr(s3_upload_mod, "read_hlo", lambda fp: ({}, {}))
```

(import at module top). This test now fails until Step 3 lands (the module does not exist yet) — that is the expected pre-change failure for it.

- [ ] **Step 2: Run to verify failure**

`conda run -n helao python -m pytest helao/core/tests/test_sync_postfinish_chain.py helao/core/tests/test_sync_hlo_rename_warning.py -v`
Expected: every test errors or fails — `postfinish_hooks` is an unexpected keyword for `SyncDriver.__init__`, `drv.postfinish` does not exist, and `helao.core.hooks.builtin.s3_upload` cannot be imported.

- [ ] **Step 3: Write `helao/core/hooks/builtin/s3_upload.py`**

Every line of the upload leg below is moved from `sync_yml` (legacy `:1741-1975` at `c3491bc0`); only the `return False` exits become `raise RuntimeError(...)`, `self` becomes `syncer`, and the flag/opts plumbing is new.

```python
"""Built-in post-finish hook: today's S3 leg of ``sync_yml``, moved verbatim.

Blocking (spec §6.1). For an action: push every file the record names
(``.hlo`` -> ``.hlo.json`` under 1 GB, parquet above; anything else as-is),
record ``files_s3``/``files_pending`` as it goes so a partial upload resumes,
and rename the uploaded entries in the meta it is about to ship. For an
experiment: finish its pending processes (``sync_process`` writes the local
``-prc.yml`` and uploads ``process/<uuid>.json``) and set ``process_list``.
Then patch the meta through the pydantic model, split a list
``technique_name``, upload ``<type>/<uuid>.json`` and set the ``s3``/``api``
flags. For an action that contributes to a process, fold it into its parent's
process bookkeeping and push the process (settled decision A2).

Failure = raise: a pass that uploads nothing, processes that will not finish,
an unreadable ``.hlo``, or a failed meta upload all leave the record unsynced
for the next pass, exactly as ``return False`` did.
"""

import asyncio
import os
from copy import copy
from pathlib import Path

from helao.core.hooks import FinishHook, PostfinishContext
from helao.core.models.file import FileInfo
from helao.core.models.process import ProcessModel
from helao.helpers import helao_logging as logging
from helao.helpers import hlo_data
from helao.helpers.premodels import Action, Experiment, Sequence

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

# Same tables as the sync drivers'; duplicated rather than imported so this
# module depends on neither twin (they import the hooks package at module top).
MOD_MAP = {
    "action": Action,
    "experiment": Experiment,
    "sequence": Sequence,
    "process": ProcessModel,
}
MOD_PATCH = {"exid": "exec_id"}


# Looked up through the module so tests can patch it (settled decision A13).
def read_hlo(fp):
    return hlo_data.read_hlo(fp)


def hlo_to_parquet(fp, parquet_path):
    return hlo_data.hlo_to_parquet(fp, parquet_path)


class Hook(FinishHook):
    blocking = True
    phase = "postfinish"

    async def run(self, ctx: PostfinishContext) -> None:
        syncer = ctx.syncer
        prog = ctx.prg
        opts = ctx.opts or {}
        compress = bool(opts.get("compress", False))
        force_s3 = bool(opts.get("force_s3", False))
        force_api = bool(opts.get("force_api", False))
        retries = int(opts.get("retries", 3))

        meta = copy(prog.yml.meta)
        # Own the files list: the upload loop renames entries to their S3 names
        # (.hlo -> .hlo.json), and a shared list would leak that into
        # prog.yml.meta, where warn_unregistered_files reads it as missing.
        if "files" in meta:
            meta["files"] = list(meta["files"] or [])

        # next push files to S3 (actions only)
        if prog.yml.type == "action":
            LOGGER.debug(f"Checking file lists for {prog.yml.target.name}")
            prog.dict["files_pending"] += [
                rel
                for rel in (prog.relpath(p) for p in prog.yml.upload_files)
                if rel not in prog.dict["files_pending"]
                and rel not in prog.dict["files_s3"]
            ]
            while prog.dict.get("files_pending", []):
                pending_before = len(prog.dict["files_pending"])
                for sp in list(prog.dict["files_pending"]):
                    fp = prog.abspath(sp)
                    if not fp.exists():
                        LOGGER.error(
                            f"Pending file {sp} for {prog.yml.target.name} is not on "
                            "disk; dropping it from the upload list."
                        )
                        prog.dict["files_pending"].remove(sp)
                        prog.write_dict()
                        continue
                    LOGGER.debug(f"Pushing {sp} to S3 for {prog.yml.target.name}")
                    if fp.suffix == ".hlo":
                        if fp.stat().st_size < 1024**3:  # 1GB
                            file_s3_key = (
                                f"raw_data/{meta['action_uuid']}/{fp.name}.json"
                            )
                            if compress:
                                file_s3_key += ".gz"
                            LOGGER.debug("Parsing hlo dicts.")
                            try:
                                file_meta, file_data = await asyncio.to_thread(
                                    read_hlo, fp
                                )
                            except Exception:
                                LOGGER.error(
                                    f"Failed to read hlo file {fp}; leaving it "
                                    "pending rather than uploading an empty "
                                    "payload.",
                                    exc_info=True,
                                )
                                raise
                            msg = {"meta": file_meta, "data": file_data}
                        else:
                            LOGGER.debug(
                                "hlo file larger than 1GB, converting to parquet."
                            )
                            file_s3_key = (
                                f"raw_data/{meta['action_uuid']}/{fp.stem}.parquet"
                            )
                            try:
                                parquet_path = str(fp).replace(".hlo", ".parquet")
                                await asyncio.to_thread(
                                    hlo_to_parquet, fp, parquet_path
                                )
                                msg = Path(parquet_path)
                            except Exception:
                                LOGGER.error(
                                    f"Failed to convert hlo file {fp} to parquet, skipping upload.",
                                    exc_info=True,
                                )
                                msg = None
                    else:
                        file_s3_key = f"raw_data/{meta['action_uuid']}/{sp}"
                        msg = fp
                    LOGGER.debug(f"Destination: {file_s3_key}")
                    file_success = await syncer.to_s3(
                        msg=msg,
                        target=file_s3_key,
                        compress=compress,
                    )
                    if file_success:
                        LOGGER.debug("Removing file from pending list.")
                        prog.dict["files_pending"].remove(sp)
                        LOGGER.info(f"Adding file to S3 dict. {sp}: {file_s3_key}")
                        prog.dict["files_s3"].update({sp: file_s3_key})
                        LOGGER.debug(f"Updating progress: {prog.dict}")
                        prog.write_dict()

                        # update files list with uploaded filename
                        if fp.name != os.path.basename(file_s3_key):
                            file_idx = [
                                i
                                for i, x in enumerate(meta["files"])
                                if x["file_name"]
                                == str(fp.relative_to(prog.yml.targetdir))
                            ][0]
                            fileinfo = FileInfo.model_validate(
                                meta["files"].pop(file_idx)
                            )
                            fileinfo.file_name = str(
                                fp.relative_to(prog.yml.targetdir)
                            ).replace("\\", "/")
                            if "." in file_s3_key.split("/")[-1]:
                                fileinfo.file_name = os.path.basename(file_s3_key)
                            else:
                                fileinfo.file_name = fileinfo.file_name.replace(
                                    f"{fp.suffix}", ""
                                )
                            if fileinfo.file_type.endswith(
                                "helao__file"
                            ):  # generic file
                                fileinfo.file_type = fileinfo.file_type.replace(
                                    "helao__file",
                                    f"helao__{file_s3_key.split('.')[-1]}_file",
                                )
                            meta["files"].append(fileinfo.model_dump())
                if len(prog.dict["files_pending"]) == pending_before:
                    raise RuntimeError(
                        f"No file uploaded for {prog.yml.target.name} in a full pass; "
                        f"leaving {prog.dict['files_pending']} pending for the next scan."
                    )

        # experiments: finish processes before pushing the meta
        if prog.yml.type == "experiment":
            LOGGER.debug(f"Finishing processes for {prog.yml.target.name}")
            retry_count = 0
            s3_unf, api_unf = prog.list_unfinished_procs()
            while s3_unf or api_unf:
                if retry_count == retries:
                    break
                await syncer.sync_process(prog, force=True)
                s3_unf, api_unf = prog.list_unfinished_procs()
                retry_count += 1
            if s3_unf or api_unf:
                raise RuntimeError(
                    f"Processes in {str(prog.yml.target)} did not sync after "
                    f"{retries} tries."
                )
            if prog.dict["process_metas"]:
                meta["process_list"] = [
                    d["process_uuid"]
                    for _, d in sorted(prog.dict["process_metas"].items())
                ]

        LOGGER.debug(f"Patching model for {prog.yml.target.name}")
        patched_meta = {MOD_PATCH.get(k, k): v for k, v in meta.items()}
        meta = MOD_MAP[prog.yml.type](**patched_meta).clean_dict(strip_private=True)

        # patch technique lists in meta
        tech_name = meta.get("technique_name", "NA")
        if isinstance(tech_name, list):
            split_technique = tech_name[meta.get("action_split", 0)]
            meta["technique_name"] = split_technique

        # next push prog.yml to S3
        if not prog.s3_done or force_s3:
            LOGGER.debug(f"Pushing prog.yml->json to S3 for {prog.yml.target.name}")
            uuid_key = patched_meta[f"{prog.yml.type}_uuid"]
            meta_s3_key = f"{prog.yml.type}/{uuid_key}.json"
            s3_success = await syncer.to_s3(meta, meta_s3_key)
            if not s3_success:
                raise RuntimeError(f"Failed to upload {meta_s3_key}")
            prog.dict["s3"] = True
            prog.write_dict()

        # The API leg is retired: the SQL database is offline. The flag is
        # still set so legacy readers of the sidecar close the record out.
        if not prog.api_done or force_api:
            prog.dict["api"] = True
            prog.write_dict()

        # if action contributes processes, update processes (moved from after
        # the DONE journal entry: it needs the patched meta -- decision A2)
        if (
            prog.s3_done
            and prog.api_done
            and prog.yml.type == "action"
            and meta.get("process_contrib", False)
        ):
            exp_prog = syncer.update_process(prog.yml, meta)
            await syncer.sync_process(exp_prog)
```

- [ ] **Step 4: Write `helao/core/hooks/builtin/dispatch_analysis.py`**

```python
"""Built-in post-finish hook: today's ``auto_analyze_sequences`` dispatch.

Non-blocking (spec §6.1). ``args`` = the per-record analysis block:
``server_key`` and ``endpoint`` are required; ``params`` (or the alias
``analysis_params``) are forwarded; ``host``/``port`` are used as the target
server entry when both are present (that is what an ``auto_analyze_sequences``
block carries, and it keeps the dispatch payload identical to today), else the
entry comes from the syncer's world config (settled decision A4). The payload
names a directory -- ``sequence_path`` or ``experiment_path`` by level (D9).
"""

from helao.core.hooks import FinishHook, HookConfigError, PostfinishContext
from helao.core.models.machine import MachineModel
from helao.helpers import dispatcher
from helao.helpers import helao_logging as logging
from helao.helpers.premodels import Action

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class Hook(FinishHook):
    blocking = False
    phase = "postfinish"
    levels = ("experiment", "sequence")

    async def run(self, ctx: PostfinishContext) -> None:
        args = dict(ctx.args or {})
        for key in ("server_key", "endpoint"):
            if key not in args:
                raise HookConfigError(f"dispatch_analysis args need {key!r}: {args}")
        level = ctx.yml.type
        name = ctx.yml.meta.get(f"{level}_name", "NA")
        server_key = args["server_key"]
        if "host" in args and "port" in args:
            target_cfg = args
        else:
            servers = (getattr(ctx.syncer, "world_config", None) or {}).get("servers", {})
            if server_key not in servers:
                raise HookConfigError(
                    f"dispatch_analysis: no host/port in args and no server "
                    f"{server_key!r} in the world config"
                )
            target_cfg = servers[server_key]
        params = args.get("params", args.get("analysis_params", {}))
        LOGGER.info(f"dispatching auto-analysis {args['endpoint']} for {name}")
        await dispatcher.async_action_dispatcher(
            world_config_dict={"servers": {server_key: target_cfg}},
            A=Action(
                action_name=args["endpoint"],
                action_server=MachineModel(server_name=server_key),
                action_params={
                    f"{level}_path": str(ctx.yml.target.parent),
                    "params": params,
                },
            ),
        )
```

- [ ] **Step 5: Legacy `sync_driver.py` — imports and `__init__`**

Imports (above the `LOGGER = ...` line, in the `helao.` block): add

```python
from helao.core.hooks.config import postfinish_config
from helao.core.hooks.loader import load_hook_set
from helao.core.hooks.postfinish import run_postfinish_chain
```

and delete `from helao.helpers.dispatcher import async_action_dispatcher` and `from helao.core.models.machine import MachineModel` (both now unused; confirm with `grep -n "MachineModel\|async_action_dispatcher" helao/core/drivers/data/sync_driver.py` → only the deleted uses). Keep `FileInfo`, `hlo_to_parquet`, `read_hlo` imports only if still referenced elsewhere in the file (`grep -n`); remove the ones that are not.

`SyncDriver.__init__`: change the signature to

```python
    def __init__(
        self,
        config: dict,
        helaodirs: HelaoDirs,
        postfinish_hooks: Optional[dict] = None,
    ):
```

update its docstring `Args:` (`config` no longer supplies `auto_analyze_sequences` semantics on its own; add `postfinish_hooks: The SYNC entry's top-level hook config; ``None`` selects the default chain (finish-hooks spec §3.2).`), and replace

```python
        self.auto_analyses = self.config_dict.get("auto_analyze_sequences", {})
```

with

```python
        # Post-finish chain per record level (finish-hooks spec §6). Built at
        # startup so a bad hook config fails here, not on the first record.
        self.postfinish = {
            level: load_hook_set(hook_map, phase="postfinish", level=level)
            for level, hook_map in postfinish_config(
                postfinish_hooks,
                self.config_dict.get("auto_analyze_sequences"),
                "SYNC",
            ).items()
        }
```

- [ ] **Step 6: Legacy `sync_yml` body**

Replace everything in `sync_yml` from the line `        meta = copy(prog.yml.meta)` down to (and including) `        return return_dict` with the following. Keep the gates between them (`status == "synced"`, `"active"`, orphan action, children gate) exactly as they are — the new body below repeats them so the whole method can be checked against it.

```python
        if prog.yml.status == "synced":
            LOGGER.debug(
                f"Cannot sync {str(prog.yml.target)}, status is already 'synced'."
            )
            return True

        LOGGER.debug(
            f"{str(prog.yml.target)} status is not synced, checking for finished."
        )

        if prog.yml.status == "active":
            LOGGER.debug(
                f"Cannot sync {str(prog.yml.target)}, status is not 'finished'."
            )
            return False

        LOGGER.debug(f"{str(prog.yml.target)} status is finished, proceeding.")

        if prog.yml.type == "action" and prog.yml.parent_yml is None:
            <unchanged orphan block>
            return False

        if prog.yml.type != "action":
            <unchanged children gate block, ending in `return False`>

        LOGGER.debug(f"{str(prog.yml.target)} children are synced, proceeding.")

        if prog.yml.type == "experiment":
            # Rebuild process metas from the on-disk action ymls before the
            # chain flushes them (see reconcile_processes).
            prog = self.reconcile_processes(prog)

        # The S3 leg and the analysis dispatch are post-finish hooks now
        # (finish-hooks spec §6): s3_upload (blocking) and dispatch_analysis
        # (non-blocking) by default, whatever `postfinish_hooks` names
        # otherwise. The chain keeps its own state in the .prg.
        synced = await run_postfinish_chain(
            self,
            prog,
            opts={
                "retries": retries,
                "force_s3": force_s3,
                "force_api": force_api,
                "compress": compress,
            },
        )
        if not synced:
            LOGGER.info(
                f"{str(prog.yml.target)} is not synced after this pass; it stays "
                "in place for the next scan."
            )
            return False

        yml_target_name = prog.yml.target.name
        yml_type = prog.yml.type

        # Every blocking hook is done. Nothing moves and nothing is zipped: the
        # record stays where it was written, and the .prg sidecar beside its
        # yml -- now holding "synced: true" -- is the receipt that it shipped,
        # which is exactly what rebuild_from_tree reads back (spec 4.5 D8, D9).
        self._journal(yml_path, DONE)
        for lock_path in prog.yml.lock_files:
            lock_path.unlink()
        prog.yml.warn_unregistered_files()
        LOGGER.debug(f"{yml_target_name} synced in place.")

        if yml_target_name in self.running_tasks:
            LOGGER.debug(f"Removing {yml_target_name} from running_tasks.")
            async with self.aiolock:
                self.running_tasks.pop(yml_target_name)

        # Re-queue the parent at its entry rank (finish_yml's ranks). A
        # parent with unsynced children re-queues itself one rank lower per
        # pass, and enqueue_yml drops it below rank_limit -- silently, at
        # DEBUG. A sequence whose actions were still uploading spent that
        # budget and never synced (so never dispatched its auto-analysis)
        # until a restart swept it up. Shipping a child is the event the
        # parent was waiting on, so hand it a fresh budget here.
        if yml_type != "sequence":
            parent_yml = prog.yml.parent_yml
            if parent_yml is not None:
                parent_rank = 1 if yml_type == "action" else 2
                await self.enqueue_yml(parent_yml, parent_rank)

        return_dict = {k: d for k, d in prog.dict.items() if k != "process_metas"}
        return return_dict
```

Concretely: the deletions are the `meta = copy(...)`/`meta["files"] = list(...)` block, the whole `if prog.yml.type == "action":` upload block, the `retry_count`/`sync_process` loop and `process_list` assignment (keep only `prog = self.reconcile_processes(prog)` under the experiment branch), the `patched_meta`/`MOD_MAP`/technique split, the meta upload, the api flag, the `if prog.s3_done and prog.api_done:` wrapper (its body is now unconditional after the `synced` check), the `if yml_type == "sequence": ... auto_analyses ...` dispatch block, and the `if yml_type == "action" and meta.get("process_contrib", False):` block. Update the method docstring's "Steps:" paragraph to: "Steps: verify the yml is finished and its children are synced, reconcile an experiment's processes, run the record's post-finish chain (default: ``s3_upload`` then, for sequences, ``dispatch_analysis``), and when every blocking hook is done record ``DONE`` in the journal, drop lock files and re-queue the parent. Nothing moves and nothing is zipped."

`HelaoSyncer.__init__` (bottom of the file): replace its body from `self.base = action_serv` to the `super().__init__` call with

```python
        self.base = action_serv
        entry = action_serv.server_cfg
        self.config_dict = entry.get("params", {})
        self.world_config = action_serv.world_cfg
        # to load this driver on orch, we resolve the syncer server key (SYNC,
        # or the legacy DB alias) or take a manually-specified key
        resolved_key = resolve_sync_server_key(
            self.world_config, preferred=sync_server_name
        )
        if not self.config_dict.get("aws_config_path", False) and resolved_key:
            entry = self.world_config["servers"][resolved_key]
            self.config_dict = entry.get("params", {})
        LOGGER.info("initializing SyncDriver")
        super().__init__(
            self.config_dict,
            self.base.helaodirs,
            postfinish_hooks=entry.get("postfinish_hooks"),
        )
```

(`self.config_dict` stays the very same dict object as before — the AWS-profile merge in `SyncDriver.__init__` mutates it and callers may read it back.)

- [ ] **Step 7: Legacy-only checkpoint**

```
conda run -n helao python -m pytest helao/core/tests/test_sync_postfinish_golden.py helao/core/tests/test_sync_postfinish_chain.py helao/core/tests/test_sync_hlo_rename_warning.py helao/core/tests/test_sync_parent_requeue.py helao/core/tests/test_sync_staging_files.py -v -k legacy
conda run -n helao pyright helao/core/drivers/data/sync_driver.py helao/core/hooks
```
Expected: all legacy-parametrized tests pass; the `native` parametrizations still fail (not yet copied); pyright 0 errors (the legacy file has a file-scope `# pyright:` suppression line — leave it). If the golden fails here, the split changed wire-visible behaviour: STOP and compare the recorded uploads with the pre-change run before touching anything.

- [ ] **Step 8: Copy the region into the native twin**

Write `/tmp/copy_sync_region.py`:

```python
"""Replace the native sync twin's verbatim region with the live legacy one.
Both bounds come from the sentinels sync_fixtures derives its pin from."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
from helao.hexagon.tests.sync_fixtures import (  # noqa: E402
    LEGACY_SYNC_PATH,
    NATIVE_SYNC_PATH,
    REGION_START_SENTINEL,
    verbatim_region_end,
    verbatim_region_start,
)

legacy = LEGACY_SYNC_PATH.read_text().splitlines(keepends=True)
start, end = verbatim_region_start(legacy), verbatim_region_end(legacy)
region = "".join(legacy[start - 1 : end])

native = NATIVE_SYNC_PATH.read_text().splitlines(keepends=True)
hits = [i for i, l in enumerate(native) if l.startswith(REGION_START_SENTINEL)]
assert len(hits) == 1, hits
n_start = hits[0]
# The native module ends with SyncDriver (NativeSyncer lives in native_syncer.py),
# so the region runs to the last non-blank line.
n_end = len(native)
while n_end > n_start and not native[n_end - 1].strip():
    n_end -= 1
NATIVE_SYNC_PATH.write_text("".join(native[:n_start]) + region + "\n")
print(f"copied legacy {start}..{end} over native {n_start + 1}..{n_end}")
```

Run: `conda run -n helao python /tmp/copy_sync_region.py`.

Then edit the native module's **import block** (above `LOGGER = ...`) by hand to mirror the legacy one: add the three `helao.core.hooks.*` imports, delete `from helao.helpers.dispatcher import async_action_dispatcher` and `from helao.core.models.machine import MachineModel`, and drop the same now-unused imports you dropped in legacy. (`helao.core.hooks` is allowed in `adapters/native` by `test_boundaries.py`; `helao.core.servers` is not, and nothing here imports it.)

- [ ] **Step 9: `NativeSyncer`**

In `helao/hexagon/adapters/native/native_syncer.py` replace the `__init__` body with

```python
        self.host = action_serv
        entry = action_serv.server_cfg
        self.config_dict = entry.get("params", {})
        self.world_config = action_serv.world_cfg
        resolved_key = resolve_sync_server_key(
            self.world_config, preferred=sync_server_name
        )
        if not self.config_dict.get("aws_config_path", False) and resolved_key:
            entry = self.world_config["servers"][resolved_key]
            self.config_dict = entry.get("params", {})
        LOGGER.info("initializing SyncDriver")
        super().__init__(
            self.config_dict,
            self.host.helaodirs,
            postfinish_hooks=entry.get("postfinish_hooks"),
        )
```

- [ ] **Step 10: Everything green**

```
conda run -n helao python -m pytest helao/hexagon/tests/test_native_sync_pins.py helao/hexagon/tests/test_boundaries.py -v
conda run -n helao --no-capture-output python run_tests.py --filter sync
conda run -n helao python helao/core/tests/unit_test_sync_process_recovery.py
conda run -n helao python helao/core/tests/unit_test_sync_relative_paths.py
conda run -n helao python helao/core/tests/unit_test_sync_to_thread.py
conda run -n helao python -m pytest helao/core/tests/test_hooks_postfinish.py helao/core/tests/test_run_state.py -q
conda run -n helao pyright helao/core/drivers/data/sync_driver.py helao/hexagon/adapters/native/sync_driver.py helao/hexagon/adapters/native/native_syncer.py helao/core/hooks
```
Expected: pins pass (region byte-identical, no imports inside it, all per-member pins), `run_tests.py --filter sync` all PASS (this includes `test_native_sync_parity.py`, the P2c on-tree parity gate, and `test_sync_graft.py`), standalone scripts exit 0, pyright 0 errors. If `unit_test_sync_to_thread.py` or `test_native_sync_to_thread.py` assert that `read_hlo`/`hlo_to_parquet` are offloaded via the sync module's names, repoint their monkeypatches to `helao.core.hooks.builtin.s3_upload` exactly as done for `test_sync_hlo_rename_warning.py` (A13) and say so in the commit message.

- [ ] **Step 11: Commit**

```bash
black helao/core/hooks helao/hexagon/adapters/native/native_syncer.py helao/core/tests/test_sync_postfinish_chain.py helao/core/tests/test_sync_hlo_rename_warning.py
git add helao/core/hooks/builtin/s3_upload.py helao/core/hooks/builtin/dispatch_analysis.py helao/core/drivers/data/sync_driver.py helao/hexagon/adapters/native/sync_driver.py helao/hexagon/adapters/native/native_syncer.py helao/core/tests/test_sync_postfinish_chain.py helao/core/tests/test_sync_hlo_rename_warning.py
git commit -m "feat(sync): sync_yml runs a post-finish hook chain; S3 upload and auto-analysis become built-in hooks

s3_upload (blocking) is today's S3 leg moved verbatim; dispatch_analysis
(non-blocking) is auto_analyze_sequences, which stays as an alias. The .prg
gains hooks/synced; the default chain is pinned byte-identical to the
pre-refactor uploads by test_sync_postfinish_golden.py. Both sync twins
edited identically (verbatim-region pin green).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 10: `MicroOrch` — single-tree roots, `replace_when_free`, pre-finish hooks, `finish_yml`

**Files:**
- Modify: `helao/core/runners/micro_orch.py` (`__init__`, `start`, `run_experiment`, `run_sequence`, `_finished_root` → `_record_root`, `_write_meta_atomic`, `_write_exp`, `_write_seq`, `_candidate_yml`, `_await_finished`, `_track_run`, docstrings)
- Modify test: `helao/core/tests/unit_test_micro_orch.py` (`RunDir.DIAG` assertions → `"DIAG"`)
- Test: create `helao/core/tests/test_micro_orch_finish.py`

**Interfaces:**
- Consumes: `run_root(root)`, `diag_root(root)` (`helao.core.models.run_dir`), `replace_when_free(src, dst)` (`helao.helpers.file_utils`), `yml_finisher(yml_path, sync_config)` (`helao.helpers.yml_tools`), `get_sync_server_cfg(world_cfg)` (`helao.helpers.server_keys`), `find_orchestrator_entry`, `prefinish_config`, `load_hook_set`, `run_prefinish`, `HookSet`.
- Produces: `MicroOrch.__init__(..., prefinish_experiment_hooks: Optional[dict] = None, prefinish_sequence_hooks: Optional[dict] = None)`; attributes `experiment_hooks: HookSet`, `sequence_hooks: HookSet` (empty until `start()`, which validates and loads them before binding the dispatcher); `_record_root(manual: bool) -> str`; `_finish_experiment(experiment) -> str` and `_finish_sequence(sequence) -> str` (status → finished, hooks, write, `finish_yml` handoff for non-manual records when the world config has a SYNC server); `runs[*]["state"]` is now `"RUNS"` or `"DIAG"`.

- [ ] **Step 1: Write the failing tests**

Create `helao/core/tests/test_micro_orch_finish.py`:

```python
"""MicroOrch finish path (spec §7): roots, hooks, finish_yml, read-back."""

import os
from pathlib import Path

import pytest

import helao.core.runners.micro_orch as micro_mod
from helao.core.hooks import FinishHook, HookConfigError, HookSet
from helao.core.models.hlostatus import HloStatus
from helao.core.runners.micro_orch import MicroOrch
from helao.helpers.premodels import Experiment, Sequence
from helao.helpers.yml_tools import yml_load

SYNC = {"host": "127.0.0.1", "port": 8010, "group": "action", "fast": "sync_server"}
ORCH = {"group": "orchestrator", "prefinish_experiment_hooks": {"append_params": ["*"]}}


def _orch(root, servers=None, **kw) -> MicroOrch:
    return MicroOrch(
        server_key="micro",
        host="127.0.0.1",
        port=9999,
        world_cfg={"root": str(root), "servers": servers or {}},
        finished_timeout=2.0,
        poll_interval=0.05,
        **kw,
    )


def _exp(name="exp1", manual=False) -> Experiment:
    exp = Experiment(experiment_name=name, experiment_params={})
    if not manual:
        exp.sequence_name = "seq1"
        exp.sequence_label = "lbl"
        exp.init_seq(time_offset=0)
    else:
        exp.manual_action = True
        exp.sequence_name = f"seq--{name}"
        exp.sequence_label = "manual"
        exp.init_seq(time_offset=0)
    exp.init_exp(time_offset=0)
    return exp


class _Probe(FinishHook):
    def __init__(self):
        self.seen = []

    async def run(self, ctx):
        self.seen.append((ctx.record.experiment_name, str(ctx.record_dir)))
        ctx.record.experiment_params["hooked"] = True


def _patch_finisher(monkeypatch):
    calls = []

    async def fake(yml_path, sync_config={}, retry=3):
        calls.append((yml_path, sync_config))
        return True

    monkeypatch.setattr(micro_mod, "yml_finisher", fake)
    return calls


def test_record_roots(tmp_path):
    orch = _orch(tmp_path)
    assert orch._record_root(False) == str(tmp_path / "RUNS")
    assert orch._record_root(True) == str(tmp_path / "DIAG")


@pytest.mark.asyncio
async def test_finish_experiment_runs_hooks_writes_under_runs_and_hands_off(tmp_path, monkeypatch):
    calls = _patch_finisher(monkeypatch)
    orch = _orch(tmp_path, servers={"SYNC": SYNC})
    probe = _Probe()
    orch.experiment_hooks = HookSet(cfg={"probe": {"exp1": None}}, hooks={"probe": probe})
    exp = _exp()
    yml_path = await orch._finish_experiment(exp)
    assert yml_path.startswith(str(tmp_path / "RUNS") + os.sep)
    expected_dir = os.path.join(str(tmp_path / "RUNS"), exp.get_experiment_dir())
    assert probe.seen == [("exp1", expected_dir)]
    meta = yml_load(Path(yml_path).read_text())
    assert meta["experiment_params"] == {"hooked": True}
    assert "finished" in str(meta["experiment_status"])
    assert calls == [(yml_path, SYNC)]
    # read-back finds it in the new tree
    assert orch._candidate_yml(exp.get_experiment_dir(), "exp") == yml_path


@pytest.mark.asyncio
async def test_no_sync_server_means_no_handoff(tmp_path, monkeypatch):
    calls = _patch_finisher(monkeypatch)
    orch = _orch(tmp_path)
    await orch._finish_experiment(_exp())
    assert calls == []


@pytest.mark.asyncio
async def test_manual_experiment_lands_in_diag_and_is_not_handed_off(tmp_path, monkeypatch):
    calls = _patch_finisher(monkeypatch)
    orch = _orch(tmp_path, servers={"SYNC": SYNC})
    exp = _exp("man", manual=True)
    yml_path = await orch._finish_experiment(exp)
    assert yml_path.startswith(str(tmp_path / "DIAG") + os.sep)
    assert calls == []
    assert orch._candidate_yml(exp.get_experiment_dir(), "exp") == yml_path


@pytest.mark.asyncio
async def test_finish_sequence_runs_hooks_and_hands_off(tmp_path, monkeypatch):
    calls = _patch_finisher(monkeypatch)
    orch = _orch(tmp_path, servers={"SYNC": SYNC})
    seen = []

    class SeqProbe(FinishHook):
        async def run(self, ctx):
            seen.append(ctx.record.sequence_name)

    orch.sequence_hooks = HookSet(cfg={"p": {"*": None}}, hooks={"p": SeqProbe()})
    seq = Sequence(sequence_name="seq1", sequence_label="lbl")
    seq.init_seq(time_offset=0)
    yml_path = await orch._finish_sequence(seq)
    assert seen == ["seq1"]
    assert yml_path.startswith(str(tmp_path / "RUNS") + os.sep)
    assert calls == [(yml_path, SYNC)]
    assert seq.sequence_status == [HloStatus.finished]


@pytest.mark.asyncio
async def test_start_loads_hooks_from_world_orchestrator_entry(tmp_path, monkeypatch):
    orch = _orch(tmp_path, servers={"ORCH": ORCH})

    async def no_serve(host, port):
        return None

    monkeypatch.setattr(orch.dispatcher, "serve", no_serve)
    assert orch.experiment_hooks.cfg == {}
    await orch.start()
    assert list(orch.experiment_hooks.cfg) == ["append_params"]
    assert orch.sequence_hooks.cfg == {}


@pytest.mark.asyncio
async def test_constructor_override_wins_and_bad_hook_fails_in_start(tmp_path, monkeypatch):
    orch = _orch(
        tmp_path, servers={"ORCH": ORCH}, prefinish_experiment_hooks={"nope_hook": ["*"]}
    )
    served = []

    async def no_serve(host, port):
        served.append(port)

    monkeypatch.setattr(orch.dispatcher, "serve", no_serve)
    with pytest.raises(HookConfigError):
        await orch.start()
    assert served == []  # validated before the dispatcher binds


@pytest.mark.asyncio
async def test_track_run_state_is_runs_or_diag(tmp_path):
    orch = _orch(tmp_path)
    yml = tmp_path / "RUNS" / "2026" / "0928" / "120000__seq1__lbl" / "260928.120000__exp1" / "x-exp.yml"
    yml.parent.mkdir(parents=True)
    yml.write_text("file_type: experiment\n")
    rec = orch._track_run("experiment", "u", "exp1", str(yml))
    assert rec["state"] == "RUNS"
    assert rec["rel_dir"] == os.path.join("2026", "0928", "120000__seq1__lbl", "260928.120000__exp1")
```

- [ ] **Step 2: Run to verify failure**

`conda run -n helao python -m pytest helao/core/tests/test_micro_orch_finish.py -v`
Expected: `AttributeError: 'MicroOrch' object has no attribute '_record_root'` / `_finish_experiment` / `experiment_hooks`, `TypeError: unexpected keyword argument 'prefinish_experiment_hooks'`, and `rec["state"] == "RUNS_FINISHED"` in the last test.

- [ ] **Step 3: Implement in `micro_orch.py`**

Imports: replace `from helao.core.models.run_dir import RunDir` with `from helao.core.models.run_dir import diag_root, run_root`; replace `from helao.helpers.file_utils import staging_path` with `from helao.helpers.file_utils import replace_when_free, staging_path`; add

```python
from helao.core.hooks import HookSet
from helao.core.hooks.config import find_orchestrator_entry, prefinish_config
from helao.core.hooks.loader import load_hook_set
from helao.core.hooks.prefinish import run_prefinish
from helao.helpers.server_keys import get_sync_server_cfg
from helao.helpers.yml_tools import yml_dumps, yml_finisher
```

(`yml_finisher` joins the existing `yml_tools` import). Grep the file for any other `RunDir.` use and convert it (there should be none after the edits below).

`__init__`: add the two keywords after `loader_factory`:

```python
        prefinish_experiment_hooks: Optional[dict] = None,
        prefinish_sequence_hooks: Optional[dict] = None,
```

document them in the docstring (`Override the world config's orchestrator entry for experiment/sequence pre-finish hooks; same shape as the config key.`), and at the end of `__init__` add

```python
        # Experiment/sequence pre-finish hooks (finish-hooks spec §7.3): from
        # the world config's orchestrator entry, or the constructor override of
        # the same name. Resolved and validated in start(); empty until then.
        self._prefinish_overrides = {
            "prefinish_experiment_hooks": prefinish_experiment_hooks,
            "prefinish_sequence_hooks": prefinish_sequence_hooks,
        }
        self.experiment_hooks: HookSet = HookSet.empty()
        self.sequence_hooks: HookSet = HookSet.empty()
```

`start()`:

```python
    async def start(self) -> None:
        """Validate and load the pre-finish hooks, then bind the RPC dispatcher.

        Hooks first: a bad hook config must fail here, before any port is
        bound, and never degrade to "no hooks" (spec §3.3).
        """
        self.experiment_hooks = self._load_prefinish(
            "prefinish_experiment_hooks", "exp_postprocess_libs", "experiment"
        )
        self.sequence_hooks = self._load_prefinish(
            "prefinish_sequence_hooks", "seq_postprocess_libs", "sequence"
        )
        await self.dispatcher.serve(self.host, derive_rpc_port(self.port))

    def _load_prefinish(self, key: str, alias: str, level: str) -> HookSet:
        override = self._prefinish_overrides[key]
        source = (
            {key: override}
            if override is not None
            else find_orchestrator_entry(self.world_cfg)
        )
        return load_hook_set(
            prefinish_config(source, key, alias, self.server_key),
            phase="prefinish",
            level=level,
        )
```

Finish helpers (place them in the "artifact persistence" section, before `_record_root`):

```python
    async def _finish_experiment(self, experiment: Experiment) -> str:
        """Mark finished, run pre-finish hooks, write the yml, hand it to SYNC."""
        experiment.reset_experiment_status(HloStatus.finished)
        experiment.experiment_finished_timestamp = set_time(offset=0)
        manual = bool(experiment.manual_action)
        await run_prefinish(
            self.experiment_hooks,
            record=experiment,
            name=experiment.experiment_name,
            record_dir=os.path.join(
                self._record_root(manual), experiment.get_experiment_dir()
            ),
            server=self,
        )
        yml_path = await self._write_exp(experiment)
        await self._notify_sync(yml_path, manual)
        return yml_path

    async def _finish_sequence(self, sequence: Sequence) -> str:
        """Sequence twin of :meth:`_finish_experiment`."""
        sequence.reset_sequence_status(HloStatus.finished)
        sequence.sequence_finished_timestamp = set_time(offset=0)
        manual = bool(sequence.manual_action)
        await run_prefinish(
            self.sequence_hooks,
            record=sequence,
            name=sequence.sequence_name,
            record_dir=os.path.join(
                self._record_root(manual), sequence.get_sequence_dir()
            ),
            server=self,
        )
        yml_path = await self._write_seq(sequence)
        await self._notify_sync(yml_path, manual)
        return yml_path

    async def _notify_sync(self, yml_path: str, manual: bool) -> None:
        """The same ``finish_yml`` POST the orchestrator's ``move_dir`` makes.

        A no-op when the world config has no SYNC server (``get_sync_server_cfg``
        returns ``{}`` and ``yml_finisher`` returns False on a missing
        host/port), and skipped for a manual record exactly as ``move_dir``
        skips it (spec §7.4, decision A11).
        """
        if manual:
            return
        await yml_finisher(yml_path, sync_config=get_sync_server_cfg(self.world_cfg))
```

`run_experiment`: replace both occurrences of

```python
                experiment.reset_experiment_status(HloStatus.finished)
                experiment.experiment_finished_timestamp = set_time(offset=0)
                yml_path = await self._write_exp(experiment)
```

(one indented inside `if not actions: if await_completion:`, one at the end) with `yml_path = await self._finish_experiment(experiment)` at the same indentation. Leave `_write_action_parent_exp` as it is (A11).

`run_sequence`: replace

```python
        sequence.reset_sequence_status(HloStatus.finished)
        sequence.sequence_finished_timestamp = set_time(offset=0)
        yml_path = await self._write_seq(sequence)
```

with `yml_path = await self._finish_sequence(sequence)`. Update its docstring sentence "The finished sequence is written to ``RUNS_FINISHED``" → "written under ``RUNS`` (``DIAG`` for a manual run)".

Roots and writers: replace `_finished_root` with

```python
    def _record_root(self, manual: bool = False) -> str:
        """``<root>/RUNS``, or ``<root>/DIAG`` for a manual run (run_dir.py).

        Raises:
            RuntimeError: If ``world_cfg`` has no ``root`` key.
        """
        root = self.world_cfg.get("root")
        if not root:
            raise RuntimeError(
                "world_cfg['root'] is required to persist or read back artifacts"
            )
        return str(diag_root(root) if manual else run_root(root))
```

and change the two callers in `_write_exp`/`_write_seq` from `self._finished_root(manual=...)` to `self._record_root(manual=...)`; fix their docstrings (`<finished_root>` → `<record_root>`). In `_write_meta_atomic` replace `os.replace(tmp_file, output_file)` with `await replace_when_free(tmp_file, output_file)` and the docstring "(temp + os.replace)" with "(temp + replace_when_free)".

`_candidate_yml`:

```python
    def _candidate_yml(self, rel_dir: str, suffix: str) -> Optional[str]:
        """Return the first matching ``*-<suffix>.yml`` under RUNS or DIAG."""
        root = self.world_cfg.get("root")
        if not root:
            raise RuntimeError("world_cfg['root'] is required to read back artifacts")
        for state_root in (run_root(root), diag_root(root)):
            pattern = os.path.join(str(state_root), rel_dir, f"*-{suffix}.yml")
            matches = sorted(glob_module.glob(pattern))
            if matches:
                return matches[0]
        return None
```

`_await_finished`: docstring/message `RUNS_FINISHED/RUNS_DIAG` → `RUNS/DIAG`.

`_track_run`: replace the state derivation with

```python
        norm = os.path.normpath(yml_path)
        parts = norm.split(os.sep)
        state = "RUNS"
        for candidate in ("RUNS", "DIAG"):
            if candidate in parts:
                state = candidate
                break
        # last occurrence: the station root itself may contain a same-named segment
        state_idx = len(parts) - 1 - parts[::-1].index(state)
```

and in `zip_runs` change `if state == RunDir.DIAG.value and not include_diag:` to `if state == "DIAG" and not include_diag:`; update the `_track_run`/`zip_runs` docstrings (`RUNS_FINISHED/RUNS_DIAG` → `RUNS/DIAG`) and the module docstring line about `RUNS_FINISHED` if present.

- [ ] **Step 4: Update the standalone MicroOrch test**

In `helao/core/tests/unit_test_micro_orch.py` replace every `RunDir.DIAG.value` with `"DIAG"` and `rec["state"] == RunDir.DIAG` with `rec["state"] == "DIAG"`; fix the check labels (`RUNS_DIAG` → `DIAG`); drop the `RunDir` import if it becomes unused. `grep -n "RunDir\|RUNS_" helao/core/tests/unit_test_micro_orch.py` must then return nothing.

- [ ] **Step 5: Verify**

```
conda run -n helao python -m pytest helao/core/tests/test_micro_orch_finish.py -v
conda run -n helao python helao/core/tests/unit_test_micro_orch.py
conda run -n helao pyright helao/core/runners/micro_orch.py
grep -rn "RUNS_FINISHED\|RUNS_DIAG\|_finished_root" helao/core/runners/micro_orch.py
```
Expected: pass / exit 0 / 0 errors / no matches. Then the test deployment's runners: `conda run -n helao --no-capture-output python run_tests.py --filter deploy/test` → no FAIL (the runner scripts under `helao/deploy/test/runners/` only call `zip_runs`, whose archive names are unchanged).

- [ ] **Step 6: Commit**

```bash
black helao/core/runners/micro_orch.py helao/core/tests/unit_test_micro_orch.py helao/core/tests/test_micro_orch_finish.py
git add helao/core/runners/micro_orch.py helao/core/tests/unit_test_micro_orch.py helao/core/tests/test_micro_orch_finish.py
git commit -m "feat(runners): MicroOrch writes under RUNS/DIAG, runs exp/seq pre-finish hooks and hands finished ymls to SYNC

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Docs pointer and the full verification sweep

**Files:**
- Modify: `helao/core/drivers/data/CLAUDE.md`, `docs/config-schema.md`, `docs/superpowers/specs/2026-09-28-finish-hooks-design.md` (Status line only)

**Interfaces:** none new. This task gates the branch: nothing merges with a red line below.

- [ ] **Step 1: Docs**

Append to `helao/core/drivers/data/CLAUDE.md`:

```markdown
**What runs after a record finishes is a config-defined hook chain, not code in `sync_yml`.** `sync_yml` keeps the gates (already synced, still active, orphan action, unsynced children), `reconcile_processes`, and the close-out (journal `DONE`, lock files, parent re-queue); the S3 leg is the built-in `s3_upload` hook and `auto_analyze_sequences` is the built-in `dispatch_analysis` hook, both under `helao/core/hooks/builtin/`. The chain's state is `hooks:`/`synced:` in the `.prg`, and `synced: true` is what `_prg_is_complete` reads; a sidecar without a `synced` key is judged by the legacy `s3`+`api` pair. Config surface, aliases and failure semantics: `docs/superpowers/specs/2026-09-28-finish-hooks-design.md`. Both sync twins carry the same edit, always -- the verbatim-region pin in `helao/hexagon/tests/test_native_sync_pins.py` says so.
```

In `docs/config-schema.md` replace the `hlo_postprocess_libs` table row with

```markdown
| `prefinish_hooks` | dict[str, list[str] \| dict] | Action servers: pre-finish hooks by name → action names (`"*"` = all). `hlo_postprocess_libs: [a, b]` is a deprecated alias for `{a: ["*"], b: ["*"]}`. |
```

and the paragraph "Two more are orchestrator-only ... `exp_postprocess_libs` and `seq_postprocess_libs`, `MetaProcessor` modules run when an experiment or sequence finishes." with

```markdown
Two more are orchestrator-only but sit at the server level rather than under
`params:` — `prefinish_experiment_hooks` and `prefinish_sequence_hooks`, hook
name → experiment/sequence names (`"*"` = all); `exp_postprocess_libs` /
`seq_postprocess_libs` are their deprecated list aliases. The SYNC server takes
`postfinish_hooks` with `action`/`experiment`/`sequence` sub-dicts of the same
shape; when absent the chain is `s3_upload: ["*"]` at every level plus, for
sequences, `dispatch_analysis` translated from `params.auto_analyze_sequences`.
An entry that sets an old key and its replacement is refused at startup. Full
surface: `docs/superpowers/specs/2026-09-28-finish-hooks-design.md`.
```

In the spec, change `Status: design approved, plan not yet written` to `Status: implemented on unstable (plan: docs/superpowers/plans/2026-09-28-finish-hooks.md); station gate (§8.1) pending`.

- [ ] **Step 2: Full sweep**

```
conda run -n helao python run_unit_tests.py
conda run -n helao --no-capture-output python run_tests.py
for f in helao/core/tests/unit_test_active_finalizer.py helao/core/tests/unit_test_active_executor.py helao/core/tests/unit_test_orch_lifecycle.py helao/core/tests/unit_test_micro_orch.py helao/core/tests/unit_test_sync_process_recovery.py helao/core/tests/unit_test_sync_relative_paths.py helao/core/tests/unit_test_sync_to_thread.py helao/core/tests/unit_test_orch_status_sync.py; do conda run -n helao python "$f" || echo "FAILED $f"; done
conda run -n helao pyright helao/core/hooks helao/core/servers helao/hexagon/app helao/hexagon/adapters/native helao/core/runners helao/helpers/run_state.py helao/core/models
conda run -n helao black --check helao/core/hooks helao/core/runners/micro_orch.py helao/core/servers/base.py helao/core/servers/orch.py helao/hexagon/app helao/helpers/run_state.py
grep -rn "hlo_postprocessors\|exp_postprocessors\|seq_postprocessors\|import_postprocessors\|auto_analyses" helao --include='*.py'
```
Expected: unit gate passes; `run_tests.py` shows no `FAIL` (ENV for Windows-only vendor SDKs is fine; NOTESTS for the standalone scripts is fine) across this repo **and every deployment, including the private deployments' tests via `run_tests.py`**; every standalone script exits 0; pyright 0 errors; black clean; the grep returns only lines inside private deployments' own docs/tests or nothing (if a private deployment's *code* still references one of these names, STOP and report — it is a caller the recon missed).

- [ ] **Step 3: Live smoke on the golden configs (alias path end-to-end)**

`conda run -n helao --no-capture-output python -m pytest helao/hexagon/tests/test_orch_legacy_parity_live.py helao/hexagon/tests/test_sync_graft.py -q` → pass. Then launch `python launch.py goldenhex` for one sequence via the operator (or `helao/hexagon/tests/smoke/` if a scripted goldenhex run exists — check `ls helao/hexagon/tests/smoke`), confirm in `<root>/RUNS/...` that an action `.prg` carries `hooks: {s3_upload: {state: done, ...}}` and `synced: true`, that the `-exp.yml` carries `appended_exp_param: yes` (the `append_params` alias), and that a `.csv` sits beside the `.hlo` (the `hlo_to_csv` alias). Record the observed `.prg` in the commit message. If no local launch is possible, say so explicitly in the report — this is the Linux half of the station gate (§8.1), not a substitute for it.

- [ ] **Step 4: Commit**

```bash
git add helao/core/drivers/data/CLAUDE.md docs/config-schema.md docs/superpowers/specs/2026-09-28-finish-hooks-design.md
git commit -m "docs: finish hooks -- config schema rows, sync CLAUDE.md pointer, spec status

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 5: Report**

Report to the user: the commit list, the `run_tests.py` totals, the observed `.prg` from Step 3, and the still-open station gate from spec §8.1 (one full UV-Vis sequence with auto-analysis: identical S3 objects to a pre-change run, `.prg` with `hooks`/`synced`, analysis dispatched; CSV export on a spectroscopy station using `hlo_postprocess_libs`).

---

## Self-review

**Spec coverage.** D1/D2/D3 → Tasks 2 (contract, config shape, order, `"*"`, args mapping), 5, 6, 10 (pre-finish in the owning server), 9 (post-finish in SYNC). D4 → Task 2 (`postfinish_config` default chain / explicit ownership) + Task 9 built-ins. D5 → Task 8 (blocking semantics) + Task 9 tests. D6 → Tasks 4–6 (`prefinish_errors`, alert, continue). D7 → Task 3 adapters. D8 → Task 10. D9 → Task 9 `dispatch_analysis` passes a path. §3.1 aliases + refusal → Task 2. §3.2 → Task 2. §3.3 validation at startup for action server / orchestrator / SYNC / `MicroOrch.start()` → Tasks 5, 6, 9, 10. §4.1–4.4 → Tasks 2–3. §5 + §5.1 all five call sites (finalizer twins, exp with reorder, seq, MicroOrch exp/seq) → Tasks 5, 6, 10. §5.2 → Task 4. §6.1 split → Task 9 (with A1/A2). §6.2 `.prg` `hooks`/`synced` → Task 8. §6.3 → Task 7 (A5). §7.1–7.5 → Task 10. §8 tests: config (T2), loader incl. all processors (T3), pre-finish order/errors/adapter/reorder (T4–T6), post-finish golden (T1), blocking/non-blocking/resume (T8, T9), dispatch payload (T1, T9), legacy-complete prg (T9), MicroOrch (T10), `run_tests.py` sweep (T11). §8.1 station gate → reported open in T11. §9 docs pointer → T11. §10 out of scope untouched (`ports/sync.py` docstring left alone).

**Placeholder scan.** No TBD/TODO. Two places intentionally say "unchanged … block" inside the Task 9 `sync_yml` listing for code the executor must keep verbatim; the deletions are enumerated explicitly right after it. Every test and implementation step carries its code.

**Type consistency.** `HookSet(cfg, hooks)`, `HookSet.empty()`, `select()` → used identically in Tasks 4, 5, 6, 8, 9, 10. `load_hook_set(cfg, phase=..., level=...)` keyword form everywhere. `run_prefinish(hook_set, record=, name=, record_dir=, server=)` in Tasks 5, 6, 10. `run_postfinish_chain(syncer, prog, opts=...)` in Tasks 8, 9. `PostfinishContext.opts` keys `retries/force_s3/force_api/compress` in Tasks 2, 8, 9. `SyncDriver.__init__(config, helaodirs, postfinish_hooks=None)` in Tasks 1 (fixture), 9. `make_sync_driver(tmp_root, cls, cfg_extra=None, postfinish_hooks=None)` in Tasks 1, 8 (unused args), 9. Attribute names: `prefinish_hooks` (action servers), `prefinish_experiment_hooks`/`prefinish_sequence_hooks` (orchestrators), `experiment_hooks`/`sequence_hooks` (MicroOrch, whose constructor keywords keep the spec's names), `postfinish` (SyncDriver).
