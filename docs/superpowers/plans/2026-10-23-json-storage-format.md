# JSON Storage Format Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** New runs write `X__N.meta.json` + `X__N.jsonl` data pairs and `-act/-exp/-seq/-prc.json` / `-ana.json` metadata, while every reader dual-reads legacy `.hlo` / `.yml` / zipped trees and every S3 artifact stays byte-shape identical.

**Architecture:** Format knowledge lives in three places only: pure name grammar in `helao/hexagon/domain/naming.py`, metadata I/O in a new `helao/helpers/meta_io.py`, data I/O in `helao/helpers/hlo_data.py`. Every reader and writer is switched onto those helpers. Readers land first (Tasks 1-10), so the tree stays green while legacy fixtures and hand-built new-format fixtures are both read. Writers flip last (Tasks 11-12), then mixed-tree parity, SYNC golden and the gate (Tasks 13-14).

**Tech Stack:** Python 3.14, `orjson` (already a dependency), `ruamel.yaml` via `helao.helpers.yml_tools`, pytest, pyright, black. Conda env `helao`.

**Spec:** `docs/superpowers/specs/2026-10-23-json-storage-format-design.md` (read it fully before starting; it is the source of truth).

## Global Constraints

- **Rollout is a hard switch.** One writer path; readers dual-read. No config flag.
- **In-flight rule (spec Decisions):** "A writer updating an existing record keeps that record's format: if `<stem>.yml` exists it is rewritten as YAML; otherwise `.json`. New records are always `.json`." Implemented once, in `meta_io.resolve_meta_path`.
- **Pretty JSON:** `orjson` with `OPT_INDENT_2 | OPT_SERIALIZE_NUMPY | OPT_NON_STR_KEYS`, UTF-8, trailing newline. Data rows keep `hlo_json_dumps` unchanged: one compact object per line.
- **S3 unchanged:** `raw_data/<uuid>/X.hlo.json` = `{"meta", "data"}`, `{type}/{uuid}.json`, `process/{uuid}.json`. The `files[]` rename to `X.hlo.json` / `helao__json_file` is unchanged.
- **`.prg` stays YAML** at `record.with_suffix(".prg")` (`X-act.json` -> `X-act.prg`). Its flat-text scanners (`_prg_is_complete`, `_prg_is_quarantined`) are not touched.
- **Out of scope:** `aux_files` CSV format (still YAML header + `%%` + body), `.prg` format, converting on-disk data, one-off private-deployment backfill scripts, dead `HelaoYml.misc_files` / `_is_syncable_misc_file`.
- **Route parameter names keep "yml"** (`/finish_yml`, `/write_off`, `/quarantine`): frozen wire surface. They must accept `.json` record paths.
- **Environment:** conda env `helao`, run from the repo root `/mnt/STORAGE/repos/helao/helao-async`. One test file: `PYTHONPATH=$PWD python -m pytest <file> -q`. Full sweep: `python run_tests.py` (one file per process). Never run `conda run python - <<EOF` (it silently runs nothing); use a script file.
- **Formatter:** `black <changed files>` right before each commit, inside the repo that owns the files. **Type checker:** `pyright <changed files>` (authoritative; do not remove `# type: ignore` that pyright needs). Pyright reports 0 files analysed under `.claude/worktrees/`; if you work in a worktree, run pyright from the main checkout path or confirm the "N files analyzed" count is non-zero.
- **Public repo:** this plan and every tracked parent-repo file must not name private deployments. They are aliased: **Deployment-A**, **Deployment-C**, **Deployment-E**. The alias -> directory mapping is given to the executor out-of-band in the task prompt, never in a tracked file. Paths are written `helao/deploy/<Deployment-C>/...`.
- **Nested repos:** `helao/deploy/<Deployment-*>` are separate git repositories, invisible to the parent's `git status`. Commit there with `git -C helao/deploy/<dir> ...`. Use `git -C <repo>` on every git call.
- **Do not touch** `helao/deploy/hte/experiments/*.py`, `helao/deploy/hte/sequences/*.py`, `helao/deploy/hte/tests/test_single_action_merges.py`, `helao/deploy/hte/tests/test_we_versus_ocv.py` (a parallel session owns uncommitted edits there). `git add` only the files a task names; never `git add -A` / `git add .` / `git commit -a`.
- **Never read or write `/mnt/wd4`, `/mnt/st2`, `/mnt/k`, `/mnt/j`, `/mnt/i`** (sshfs mounts of production storage). Every test and the sim launch write under `tmp_path` or `/tmp/...`.
- **No outward actions without the user:** subagents never `git commit`/`push`/`stash`; commits listed in steps are made by the main thread after the user approves.
- **Ponytail:** reuse `staging_path` (`helao/helpers/file_utils.py`), `hlo_json_dumps` and `_hlo_json_default` (`helao/helpers/to_json.py`), `yml_load` / `yml_dumps` (`helao/helpers/yml_tools.py`). No new abstractions beyond the ones listed in "Additions beyond the spec's list" below.

### Additions beyond the spec's helper list (deliberate, small)

| Name | Where | Why the spec's four `meta_io` functions were not enough |
|---|---|---|
| `RECORD_KINDS = ("seq", "exp", "act")`, `data_sibling(path, suffix)` | `naming.py` | Every pair reader/writer swaps a data suffix for its partner; one pure helper instead of nine inline slices. `RECORD_KINDS` replaces the private `_META_KINDS`. |
| `resolve_meta_path(path)` | `meta_io.py` | The async meta writers (`NativeMetaFileWriter`, `MicroOrch`, `move_dir`) keep their own `replace_when_free` staging; they need the in-flight-resolved path without the sync write. `write_meta` calls it too, so the rule exists once. |
| `dumps_meta(d, path=None)` | `meta_io.py` | Same function the spec names; the optional `path` picks YAML for a `.yml` target (in-flight rule). |
| `read_hlo_via(where, get_bytes, name, ...)` | `hlo_data.py` | Zip members, `FileMapper` and the loaders read bytes, not paths; this is `resolve_data_file` + `read_hlo_pair_bytes` in one call so four call sites do not each re-implement the pair lookup. |
| `top_level_pair(line, is_json)` | `run_state.py` | The bounded top-level scan is needed by both `run_state._scan_top_level` and `ui/shared/retire.top_level` (which already imports from `run_state`). |

## Review Focus

1. **A record that started under the old build and finishes under the new one** (`-act.yml` already on disk when `write_act` runs at finish, or a reconcile rewrite) must be rewritten as YAML in place, never gain a `-act.json` twin — a twin makes `HelaoYml.check_paths` raise "multiple" on the directory and syncs the action twice. Pinned by `test_write_act_keeps_an_in_flight_yml` (Task 12) and `test_write_meta_rewrites_existing_yml` (Task 2).
2. **A `.jsonl` over 1 GB takes the parquet branch.** The old `str(fp).replace(".hlo", ".parquet")` is a no-op on `X.jsonl`, so `hlo_to_parquet` would write the parquet over the data file itself. Pinned by `test_large_jsonl_converts_to_a_sibling_parquet` (Task 6).
3. **Zipped `-act.json` with a non-ASCII value.** The legacy `.replace(b"\x89", b"%")` repair corrupts any UTF-8 multi-byte sequence containing the byte `0x89` (`Ɖ`, U+0189, is `C6 89`; any character whose UTF-8 encoding has a `0x89` continuation byte is hit). It must only run on `.yml` members. Pinned by `test_zipped_json_meta_keeps_non_ascii` (Task 4).
4. **`process_order_groups` read from a `-exp.json` has string keys** (`"0"`), while `.prg` bookkeeping, `action_order` and `written_off` compare ints; a mismatch leaves every process group unfinished forever. Pinned by `test_progress_from_json_exp_has_int_group_keys` (Task 6).
5. **A `.jsonl` whose first line is not a JSON object** (the stream logger writes non-dict payloads verbatim) must not be swallowed as a YAML header, and a header-less `.jsonl` reads as `meta == {}`. Pinned by `test_jsonl_first_line_is_never_a_header` (Task 3).

---

## File map

| File | Change | Task |
|---|---|---|
| `helao/hexagon/domain/naming.py` | constants, `meta_kind`, `data_stem`, `data_sibling`, `is_nosync_file` | 1 |
| `helao/helpers/meta_io.py` (new) | `read_meta`, `dumps_meta`, `resolve_meta_path`, `write_meta`, `meta_glob` | 2 |
| `helao/helpers/hlo_data.py` | dual `read_hlo`, `read_hlo_pair_bytes`, `resolve_data_file`, `read_hlo_via`, `keep_keys` fix, dual header/chunks | 3 |
| `helao/helpers/file_mapper.py`, `helao/helpers/helao_data.py`, `helao/core/drivers/data/loaders/{localfs,model_base,helao_loader}.py`, `helao/ui/shared/data_browser/{sources,readers}.py` | loaders | 4 |
| `helao/helpers/run_state.py`, `helao/hexagon/app/action_host.py` (`_reconcile_one`), `helao/ui/shared/retire.py`, `helao/core/drivers/data/process_locator.py`, `helao/helpers/processors.py`, `helao/deploy/hte/servers/action/sync_server.py`, `helao/deploy/test/servers/action/sim_db_server.py`, `helao/deploy/hte/specifications/week_window.py` | record discovery | 5 |
| `helao/hexagon/adapters/native/sync_driver.py`, `helao/core/hooks/builtin/s3_upload.py`, `helao/hexagon/adapters/native/CLAUDE.md` | SYNC | 6 |
| `harness/{classify,yaml_pass,hlo_pass,treepass,parity,normalize,capture,s3_pass}.py` | harness | 7 |
| hte `processors/*`, `drivers/data/calc_driver.py` | hte live paths | 8 |
| `helao/deploy/<Deployment-C>/...` | Deployment-C live paths | 9 |
| `helao/deploy/<Deployment-A>/...`, `helao/deploy/<Deployment-E>/...` | Deployment-A/E live paths | 10 |
| `helao/hexagon/adapters/native/{data_file,data_stream,posthoc_writer}.py`, `helao/core/models/file.py`, `helao/hexagon/app/action_host.py` (`_register_present_files`), hte `servers/action/{gamry_server2,calc_server}.py` | data writers | 11 |
| `helao/hexagon/adapters/native/{meta_writer,posthoc_writer}.py`, `helao/core/runners/micro_orch.py`, `helao/helpers/yml_tools.py` (`move_dir`), `helao/core/drivers/data/analysis_layout.py` + callers | meta writers | 12 |
| `harness/tests/synthtree.py`, `helao/core/tests/test_mixed_tree_readers.py` (new), `helao/core/tests/test_sync_postfinish_golden.py`, `helao/hexagon/tests/sync_fixtures.py` | parity + SYNC golden | 13 |
| — | gate | 14 |

---

### Task 0: Baseline (before any code change)

**Files:** none modified. Artifacts go to the job directory, not `/tmp` (shared `/tmp` scratch has vanished between sessions before).

- [ ] **Step 1: Record the starting commits**

```bash
D="${CLAUDE_JOB_DIR:-$HOME/.cache/helao-json-storage}/json-storage"; mkdir -p "$D"; echo "$D"
git -C /mnt/STORAGE/repos/helao/helao-async rev-parse HEAD > "$D/parent.sha"
for d in /mnt/STORAGE/repos/helao/helao-async/helao/deploy/*/; do
  [ -d "$d/.git" ] && echo "$(basename "$d") $(git -C "$d" rev-parse HEAD)"
done > "$D/nested.sha"
git -C /mnt/STORAGE/repos/helao/helao-async status --short > "$D/status.before"
```

Expected: `parent.sha` holds `cd2d6417...` or later; `status.before` lists only the parallel session's hte files.

- [ ] **Step 2: Start the baseline sweep (background command 1)**

Run with `run_in_background: true`. The job writes its own marker; never detect the end with `pgrep -f`.

```bash
D="${CLAUDE_JOB_DIR:-$HOME/.cache/helao-json-storage}/json-storage"
cd /mnt/STORAGE/repos/helao/helao-async && ( PYTHONPATH=$PWD python run_tests.py > "$D/baseline.log" 2>&1; echo $? > "$D/baseline.done" )
```

- [ ] **Step 3: Start the watcher (background command 2)**

```bash
D="${CLAUDE_JOB_DIR:-$HOME/.cache/helao-json-storage}/json-storage"
for i in $(seq 1 720); do [ -f "$D/baseline.done" ] && break; sleep 15; done; echo "rc=$(cat "$D/baseline.done" 2>/dev/null || echo TIMEOUT)"; tail -5 "$D/baseline.log"
```

- [ ] **Step 4: Extract the baseline failing set when the watcher fires**

```bash
D="${CLAUDE_JOB_DIR:-$HOME/.cache/helao-json-storage}/json-storage"
grep -E '^\s+(FAIL|TIMEOUT)\s' "$D/baseline.log" | awk '{print $2}' | sort -u > "$D/baseline.fail"
wc -l "$D/baseline.fail"
cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD python run_unit_tests.py > "$D/baseline.unit.log" 2>&1; echo "unit rc=$?"
```

Expected: a (possibly empty) list of pre-existing failures. These are the only failures allowed at the gate.

- [ ] **Step 5: Capture a pre-change GM-1 golden on the simulated group**

The `golden` test config writes under `root: /tmp/helao-golden` and SYNC is `sim_db_server` with a recording S3 client (`S3_SIM/`). Confirm nothing in it points at a production mount first:

```bash
cd /mnt/STORAGE/repos/helao/helao-async && grep -n '/mnt/' helao/deploy/test/configs/golden.yml; echo "grep rc=$? (1 = no /mnt paths, required)"
```

Then launch (background command, `run_in_background: true`). `setsid` makes the wrapper a process-group leader so teardown is a kill by PID, never by pattern:

```bash
D="${CLAUDE_JOB_DIR:-$HOME/.cache/helao-json-storage}/json-storage"
rm -rf /tmp/helao-golden
cd /mnt/STORAGE/repos/helao/helao-async && setsid bash -c 'echo $$ > "'"$D"'/group.pid"; exec script -qfec "./helao.sh golden --no-hot-reload" /dev/null' > "$D/group-pre.log" 2>&1
```

In a separate foreground command, capture (the capture waits for the ORCH/SIM/SYNC ports itself):

```bash
D="${CLAUDE_JOB_DIR:-$HOME/.cache/helao-json-storage}/json-storage"
cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD timeout 900 python -m harness.capture --scenario GM-1 --root /tmp/helao-golden --out "$D/gm1-pre" --config-prefix golden --notes "json-storage baseline"
kill -TERM -- -"$(cat "$D/group.pid")"; sleep 10
find /tmp/helao-golden/RUNS -name '*-act.yml' | head -3; find /tmp/helao-golden/RUNS -name '*.hlo' | head -3
```

Expected: `captured GM-1 -> .../gm1-pre`; legacy `-act.yml` and `.hlo` files listed. If the group fails to start, stop and report; do not continue to Task 1 without a baseline capture.

No commit for this task.

---

### Task 1: Naming grammar (`naming.py`)

**Files:**
- Modify: `helao/hexagon/domain/naming.py`
- Test: `helao/hexagon/tests/test_naming.py`

**Interfaces:**
- Produces (all pure, no I/O; `path` may be `str` or `os.PathLike`, `/` or `\` separated):
  - `RECORD_KINDS: tuple[str, ...] = ("seq", "exp", "act")`
  - `META_KINDS: tuple[str, ...] = ("seq", "exp", "act", "prc", "ana")`
  - `META_SUFFIXES: tuple[str, ...] = (".json", ".yml")`
  - `DATA_SUFFIX = ".jsonl"`, `HEADER_SUFFIX = ".meta.json"`
  - `meta_kind(path) -> Optional[str]` — kind from a `*-<kind>.json` / `*-<kind>.yml` name, else `None`.
  - `data_stem(path) -> str` — basename with `.hlo.json`, `.meta.json`, `.jsonl` or `.hlo` stripped (basename unchanged otherwise).
  - `data_sibling(path, suffix: str) -> str` — same directory, `data_stem(path) + suffix`.
  - `is_nosync_file(filename, sync_data) -> bool` — also true for `.jsonl`.
  - `meta_yml_filename(ts, kind)` now returns `<ts>-<kind>.json`; `hlo_filename(...)` default `file_ext="jsonl"` (pure mirrors of the writers, kept honest).

- [ ] **Step 1: Write the failing tests** — replace the three existing pins and append the new tables in `helao/hexagon/tests/test_naming.py`:

```python
def test_meta_yml_filename_grammar():
    ts = datetime(2026, 7, 17, 13, 5, 9, 123456)
    assert naming.meta_yml_filename(ts, "act") == "260717.130509123456-act.json"
    assert naming.meta_yml_filename(ts, "exp") == "260717.130509123456-exp.json"
    assert naming.meta_yml_filename(ts, "seq") == "260717.130509123456-seq.json"
```

```python
def test_hlo_filename_grammar():
    # active_data_file.py:139 template, filenum = index in file_conn_keys
    assert naming.hlo_filename("CA", 3, 0, 0, 1, 0) == "CA-3.0.0.1__0.jsonl"
    assert (
        naming.hlo_filename("OCV", 0, 2, 1, 0, 2, file_ext="csv")
        == "OCV-0.2.1.0__2.csv"
    )
```

```python
def test_is_nosync_file():
    # FileInfo.nosync=True for data files when action.sync_data is False
    assert naming.is_nosync_file("a__0.hlo", sync_data=False) is True
    assert naming.is_nosync_file("a__0.jsonl", sync_data=False) is True
    assert naming.is_nosync_file("a__0.jsonl", sync_data=True) is False
    assert naming.is_nosync_file("a__0.hlo", sync_data=True) is False
    assert naming.is_nosync_file("notes.csv", sync_data=False) is False


import pytest


@pytest.mark.parametrize(
    "path, kind",
    [
        ("260717.130509123456-act.json", "act"),
        ("260717.130509123456-act.yml", "act"),
        ("RUNS/x/260717.130509123456-seq.json", "seq"),
        ("C:\\INST\\RUNS\\x\\260717.130509123456-exp.yml", "exp"),
        ("0__0f1e__CV-prc.json", "prc"),
        ("0__0f1e__CV-prc.yml", "prc"),
        ("8a6f2c1e-1234-4abc-9def-0123456789ab-ana.json", "ana"),
        ("CA-3.0.0.1__0.meta.json", None),
        ("CA-3.0.0.1__0.jsonl", None),
        ("8a6f2c1e-1234-4abc-9def-0123456789ab_output_xrfs.json", None),
        ("act.json", None),
        ("260717.130509123456-act.prg", None),
        ("config.yml", None),
    ],
)
def test_meta_kind(path, kind):
    assert naming.meta_kind(path) == kind


@pytest.mark.parametrize(
    "path, stem",
    [
        ("CA-3.0.0.1__0.hlo", "CA-3.0.0.1__0"),
        ("CA-3.0.0.1__0.jsonl", "CA-3.0.0.1__0"),
        ("CA-3.0.0.1__0.meta.json", "CA-3.0.0.1__0"),
        ("CA-3.0.0.1__0.hlo.json", "CA-3.0.0.1__0"),
        ("sub/dir/ms_recording.jsonl", "ms_recording"),
        ("notes.csv", "notes.csv"),
    ],
)
def test_data_stem(path, stem):
    assert naming.data_stem(path) == stem


def test_data_sibling_keeps_the_directory():
    assert naming.data_sibling("a/b/X__0.jsonl", ".meta.json") == "a/b/X__0.meta.json"
    assert naming.data_sibling("a/b/X__0.meta.json", ".jsonl") == "a/b/X__0.jsonl"
    assert naming.data_sibling("X__0.hlo.json", ".jsonl") == "X__0.jsonl"
    assert naming.data_sibling("C:\\r\\X__0.hlo", ".jsonl") == "C:\\r\\X__0.jsonl"
```

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONPATH=$PWD python -m pytest helao/hexagon/tests/test_naming.py -q`
Expected: FAIL — `AttributeError: module 'helao.hexagon.domain.naming' has no attribute 'meta_kind'`, plus the `.json`/`.jsonl` grammar asserts.

- [ ] **Step 3: Implement** — in `helao/hexagon/domain/naming.py`:

Replace the `__all__` list, `_META_KINDS` and `meta_yml_filename`:

```python
__all__ = [
    "DATA_SUFFIX",
    "HEADER_SUFFIX",
    "META_KINDS",
    "META_SUFFIXES",
    "META_YML_TS_FMT",
    "RECORD_KINDS",
    "data_sibling",
    "data_stem",
    "dflt_file_conn_key",
    "hlo_filename",
    "is_nosync_file",
    "meta_kind",
    "meta_yml_filename",
    "new_file_conn_key",
    "redirect_manual_dir",
]

META_YML_TS_FMT = "%y%m%d.%H%M%S%f"

#: The three record kinds the sync hierarchy is built from.
RECORD_KINDS = ("seq", "exp", "act")
#: Every ``*-<kind>.<suffix>`` metadata file: records, processes, analysis models.
META_KINDS = ("seq", "exp", "act", "prc", "ana")
#: Metadata suffixes, current format first.
META_SUFFIXES = (".json", ".yml")
#: A data pair is ``X.meta.json`` (header, optional) + ``X.jsonl`` (rows).
DATA_SUFFIX = ".jsonl"
HEADER_SUFFIX = ".meta.json"
#: Longest first, so ``X.hlo.json`` is never read as ``X.hlo`` + ``.json``.
_DATA_SUFFIXES = (".hlo.json", HEADER_SUFFIX, DATA_SUFFIX, ".hlo")


def _basename(path) -> str:
    """Last path element of a ``/`` or ``\\`` separated path (pure, no os.path)."""
    return str(path).replace("\\", "/").rsplit("/", 1)[-1]


def meta_kind(path) -> Optional[str]:
    """``seq``/``exp``/``act``/``prc``/``ana`` from ``*-<kind>.json|.yml``, else None.

    A data header ``X.meta.json`` and an analysis output ``<uuid>_output_<g>.json``
    carry no ``-<kind>`` ending and return None.
    """
    name = _basename(path)
    for suffix in META_SUFFIXES:
        if name.endswith(suffix):
            _, sep, kind = name[: -len(suffix)].rpartition("-")
            return kind if sep and kind in META_KINDS else None
    return None


def data_stem(path) -> str:
    """Basename with ``.hlo.json``/``.meta.json``/``.jsonl``/``.hlo`` stripped."""
    name = _basename(path)
    for suffix in _DATA_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def data_sibling(path, suffix: str) -> str:
    """``path`` in the same directory with its data suffix replaced by ``suffix``."""
    p = str(path)
    return p[: len(p) - len(_basename(p))] + data_stem(p) + suffix


def meta_yml_filename(obj_timestamp: datetime, kind: str) -> str:
    """Return ``<ts>-{kind}.json`` for kind in {'act','exp','seq'}.

    The name is historical; records are JSON since the storage-format switch.
    """
    if kind not in RECORD_KINDS:
        raise ValueError(f"unknown meta kind {kind!r}; expected one of {RECORD_KINDS}")
    return f"{obj_timestamp.strftime(META_YML_TS_FMT)}-{kind}.json"
```

Change `hlo_filename`'s default `file_ext: str = "hlo"` to `file_ext: str = "jsonl"`, and replace `is_nosync_file`:

```python
def is_nosync_file(filename: str, sync_data: bool) -> bool:
    """FileInfo.nosync rule: True for a data file (``.hlo``/``.jsonl``) when sync_data is off."""
    return (not sync_data) and filename.endswith((".hlo", DATA_SUFFIX))
```

Add `from typing import Optional` to the imports. Update the module docstring's first bullet to read `<obj_timestamp:%y%m%d.%H%M%S%f>-{act,exp,seq}.json` and the second to `...__{filenum}.jsonl`.

- [ ] **Step 4: Run to verify they pass**

Run: `PYTHONPATH=$PWD python -m pytest helao/hexagon/tests/test_naming.py helao/hexagon/tests/test_boundaries.py -q`
Expected: PASS (the boundary test confirms `naming.py` still imports nothing impure).

- [ ] **Step 5: Commit**

```bash
black helao/hexagon/domain/naming.py helao/hexagon/tests/test_naming.py
pyright helao/hexagon/domain/naming.py
git -C /mnt/STORAGE/repos/helao/helao-async add helao/hexagon/domain/naming.py helao/hexagon/tests/test_naming.py
git -C /mnt/STORAGE/repos/helao/helao-async commit -m "feat(naming): JSON storage suffixes, meta_kind, data_stem, data_sibling"
```

---

### Task 2: Metadata I/O (`meta_io.py`)

**Files:**
- Create: `helao/helpers/meta_io.py`
- Create: `helao/core/tests/test_storage_format.py`

**Interfaces:**
- Consumes: `META_SUFFIXES` from Task 1; `staging_path`; `_hlo_json_default`; `yml_load`, `yml_dumps`.
- Produces:
  - `read_meta(path_or_bytes, name=None) -> Any` — `.json` via `orjson.loads`, anything else via `yml_load(fast=True)`. For `bytes`, `name` (the member/file name) is required and picks the format.
  - `dumps_meta(d, path=None) -> str` — pretty JSON + `"\n"`; YAML (`yml_dumps`) when `path` ends in `.yml`.
  - `resolve_meta_path(path) -> Path` — the in-flight rule: `<stem>.yml` if it exists, else `<stem>.json`. Accepts either suffix as input.
  - `write_meta(path, d) -> Path` — atomic (staging + `os.replace`) write to `resolve_meta_path(path)`; returns the path written.
  - `meta_glob(root, kind, prefix_pattern="*") -> list[Path]` — sorted union of `glob(root/<prefix_pattern>-<kind><suffix>, recursive=True)` over `META_SUFFIXES`; `kind` may be a str or a tuple of kinds; `root` may contain glob wildcards.

- [ ] **Step 1: Write the failing tests** — create `helao/core/tests/test_storage_format.py`:

```python
"""JSON storage format: meta_io and hlo_data dual-format behaviour (spec §5)."""

import json
from pathlib import Path

import pytest

from helao.helpers.meta_io import (
    dumps_meta,
    meta_glob,
    read_meta,
    resolve_meta_path,
    write_meta,
)
from helao.helpers.premodels import Experiment
from helao.helpers.yml_tools import yml_dumps

META = {
    "file_type": "action",
    "action_uuid": "06a5a2d6-b26c-7673-8000-9f38fe556fd6",
    "action_timestamp": "2026-10-23 12:00:00.123456",
    "action_params": {"duration": 2.0, "label": "µ-cell"},
    "files": [{"file_name": "CA-0.0.0.0__0.jsonl", "file_type": "helao__file"}],
    "nested": {"none": None, "list": [1, 2.5, "x"]},
}


def test_read_meta_yml_and_json_are_equal(tmp_path):
    y = tmp_path / "260717.130509123456-act.yml"
    y.write_text(yml_dumps(META), encoding="utf-8")
    j = write_meta(tmp_path / "260718.130509123456-act.json", META)
    assert read_meta(y) == read_meta(j) == META
    assert read_meta(j.read_bytes(), name=j.name) == META
    assert read_meta(y.read_bytes(), name=y.name) == META


def test_read_meta_bytes_needs_a_name():
    with pytest.raises(ValueError):
        read_meta(b"{}")


def test_dumps_meta_is_pretty_utf8_with_trailing_newline():
    out = dumps_meta({"a": 1, "b": {"c": "µ"}})
    assert out == '{\n  "a": 1,\n  "b": {\n    "c": "µ"\n  }\n}\n'
    assert dumps_meta({"a": 1}, path="x-act.yml") == yml_dumps({"a": 1})


def test_dumps_meta_handles_numpy_nan_and_sets():
    import numpy as np

    out = json.loads(dumps_meta({"v": np.float64(1.5), "n": float("nan"), "s": {3, 1}}))
    assert out == {"v": 1.5, "n": None, "s": [1, 3]}


def test_int_keys_round_trip_through_the_model(tmp_path):
    exp = Experiment(experiment_name="x", process_order_groups={0: [0, 1], 1: [2]})
    p = write_meta(tmp_path / "260717.130509123456-exp.json", exp.clean_dict())
    raw = read_meta(p)
    assert raw["process_order_groups"] == {"0": [0, 1], "1": [2]}
    assert Experiment.model_validate(raw).process_order_groups == {0: [0, 1], 1: [2]}


def test_write_meta_rewrites_existing_yml(tmp_path):
    """In-flight rule: a record begun as YAML stays YAML, no .json twin."""
    y = tmp_path / "260717.130509123456-act.yml"
    y.write_text(yml_dumps({"action_status": ["active"]}), encoding="utf-8")
    written = write_meta(tmp_path / "260717.130509123456-act.json", {"action_status": ["finished"]})
    assert written == y
    assert read_meta(y) == {"action_status": ["finished"]}
    assert not (tmp_path / "260717.130509123456-act.json").exists()
    assert resolve_meta_path(tmp_path / "260717.130509123456-act.json") == y


def test_write_meta_new_record_is_json_and_leaves_no_staging(tmp_path):
    written = write_meta(tmp_path / "d" / "260717.130509123456-seq.yml", {"a": 1})
    assert written.name == "260717.130509123456-seq.json"
    assert sorted(p.name for p in written.parent.iterdir()) == [written.name]


def test_meta_glob_mixed_suffixes_and_kinds(tmp_path):
    seq = tmp_path / "RUNS_FINISHED" / "25.28" / "0716" / "seq"
    exp = seq / "exp"
    act = exp / "act"
    act.mkdir(parents=True)
    (seq / "1-seq.yml").write_text("a: 1\n", encoding="utf-8")
    (exp / "2-exp.json").write_text("{}\n", encoding="utf-8")
    (exp / "0__u__T-prc.json").write_text("{}\n", encoding="utf-8")
    (act / "3-act.json").write_text("{}\n", encoding="utf-8")
    (act / "X__0.meta.json").write_text("{}\n", encoding="utf-8")
    assert meta_glob(seq, "seq") == [seq / "1-seq.yml"]
    assert meta_glob(seq, ("exp", "act"), "*") == []
    assert meta_glob(seq, ("exp", "act"), "*/*") == [exp / "2-exp.json"]
    assert meta_glob(seq, ("exp", "act"), "*/*/*") == [act / "3-act.json"]
    assert meta_glob(exp, "prc") == [exp / "0__u__T-prc.json"]
    assert meta_glob(tmp_path, "act", "**/*") == [act / "3-act.json"]
    wild = tmp_path / "RUNS_*" / "25.28" / "0716"
    assert meta_glob(wild, "seq", "*/*") == [seq / "1-seq.yml"]
```

The last path element of `prefix_pattern` is the filename prefix: `"*/*"` means `<root>/<one dir>/<name>-<kind>.*`, the same shape as the legacy `os.path.join(root, "*", "*-exp.yml")`.

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONPATH=$PWD python -m pytest helao/core/tests/test_storage_format.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'helao.helpers.meta_io'`.

- [ ] **Step 3: Implement** — create `helao/helpers/meta_io.py`:

```python
"""Record metadata I/O for both formats: ``.json`` (current) and ``.yml`` (legacy).

A record (``-seq/-exp/-act``), process (``-prc``) or analysis model (``-ana``)
is written as pretty JSON. A record that already exists as ``<stem>.yml`` keeps
that format when rewritten -- the in-flight rule of the JSON storage spec -- so
a run that straddles the upgrade never gains a second, ``.json`` twin.
"""

__all__ = ["dumps_meta", "meta_glob", "read_meta", "resolve_meta_path", "write_meta"]

import glob
import os
from pathlib import Path
from typing import Any, Optional, Union

import orjson

from helao.helpers.file_utils import staging_path
from helao.helpers.to_json import _hlo_json_default
from helao.helpers.yml_tools import yml_dumps, yml_load
from helao.hexagon.domain.naming import META_SUFFIXES

_JSON_OPTS = orjson.OPT_INDENT_2 | orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_NON_STR_KEYS


def _default(obj):
    """orjson fallback: sets (``HelaoDict`` keeps them) as sorted lists, then floats."""
    if isinstance(obj, (set, frozenset)):
        return sorted(obj, key=str)
    return _hlo_json_default(obj)


def read_meta(path_or_bytes: Union[str, os.PathLike, bytes], name: Optional[str] = None) -> Any:
    """Parse a metadata file: ``.json`` with orjson, anything else as YAML.

    Args:
        path_or_bytes: A path, or the raw bytes of a zip member.
        name: The file or member name; required with bytes, where it picks the
            format.
    """
    if isinstance(path_or_bytes, (bytes, bytearray)):
        if name is None:
            raise ValueError("read_meta(bytes) needs name= to pick a format")
        if str(name).endswith(".json"):
            return orjson.loads(path_or_bytes)
        return yml_load(bytes(path_or_bytes).decode("utf-8"), fast=True)
    path = Path(path_or_bytes)
    if path.name.endswith(".json"):
        return orjson.loads(path.read_bytes())
    return yml_load(path, fast=True)


def dumps_meta(d: Any, path: Union[str, os.PathLike, None] = None) -> str:
    """Pretty JSON (2-space, UTF-8, trailing newline); YAML for a ``.yml`` ``path``."""
    if path is not None and str(path).endswith(".yml"):
        return yml_dumps(d)
    return orjson.dumps(d, default=_default, option=_JSON_OPTS).decode("utf-8") + "\n"


def resolve_meta_path(path: Union[str, os.PathLike]) -> Path:
    """The file a write to ``path`` lands in: an existing ``<stem>.yml``, else ``<stem>.json``."""
    p = Path(path)
    legacy = p.with_suffix(".yml")
    return legacy if legacy.exists() else p.with_suffix(".json")


def write_meta(path: Union[str, os.PathLike], d: Any) -> Path:
    """Atomically write ``d`` to :func:`resolve_meta_path` ``(path)``; return that path."""
    target = resolve_meta_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = staging_path(target)
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(dumps_meta(d, target))
        os.replace(tmp, target)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return target


def meta_glob(
    root: Union[str, os.PathLike], kind: Union[str, tuple], prefix_pattern: str = "*"
) -> list[Path]:
    """``<root>/<prefix_pattern>-<kind>.json|.yml`` for each kind, sorted.

    ``root`` and ``prefix_pattern`` are glob patterns (``**`` recurses), so a
    caller that widens a legacy ``RUNS_*`` segment can pass it straight in.
    """
    kinds = (kind,) if isinstance(kind, str) else tuple(kind)
    found = {
        p
        for k in kinds
        for suffix in META_SUFFIXES
        for p in glob.glob(
            os.path.join(str(root), f"{prefix_pattern}-{k}{suffix}"), recursive=True
        )
    }
    return sorted(Path(p) for p in found)
```

Note: `staging_path` returns a `.<8hex>.tmp` dotfile, which is the shape `misc_files` and `_register_present_files` already exclude.

- [ ] **Step 4: Run to verify they pass**

Run: `PYTHONPATH=$PWD python -m pytest helao/core/tests/test_storage_format.py -q`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
black helao/helpers/meta_io.py helao/core/tests/test_storage_format.py
pyright helao/helpers/meta_io.py
git -C /mnt/STORAGE/repos/helao/helao-async add helao/helpers/meta_io.py helao/core/tests/test_storage_format.py
git -C /mnt/STORAGE/repos/helao/helao-async commit -m "feat(meta_io): dual-format record metadata read/write with the in-flight rule"
```

---

### Task 3: Data-file I/O (`hlo_data.py`)

**Files:**
- Modify: `helao/helpers/hlo_data.py`
- Test: `helao/core/tests/test_storage_format.py` (append)

**Interfaces:**
- Consumes: `DATA_SUFFIX`, `HEADER_SUFFIX`, `data_sibling` (Task 1).
- Produces (all return `(meta: dict, data: dict[str, list])`):
  - `read_hlo(path, keep_keys=[], omit_keys=[])` — dispatch by name: `.hlo` legacy parser; `.jsonl` meta from sibling `X.meta.json` if present else `{}`; `.meta.json` meta from the file and rows from `X.jsonl` (missing `.jsonl` raises `FileNotFoundError`); `.hlo.json` S3 shape `{"meta","data"}`; `bytes` -> legacy byte parser (unchanged).
  - `read_hlo_stream(stream, keep_keys=[], omit_keys=[], has_header=True)` — `has_header=False` treats every line as a row.
  - `read_hlo_pair_bytes(meta_bytes: Optional[bytes], data_bytes: bytes, keep_keys=[], omit_keys=[])`.
  - `resolve_data_file(where, name) -> Optional[str]` — `where` is a directory (`str`/`PathLike`), a container of names (zip `namelist()`), or an `exists(name) -> bool` callable. Tries `name`, then for a data name (`.hlo`, `.jsonl`, `.meta.json`, `.hlo.json`) `X.jsonl` then `X.hlo` in the same directory; returns the first that exists.
  - `read_hlo_via(where, get_bytes, name, keep_keys=[], omit_keys=[])` — `resolve_data_file` + the right parser over a byte source (`get_bytes(name) -> bytes`). Raises `FileNotFoundError` when nothing resolves or a header has no `.jsonl`.
  - `read_hlo_header(path) -> (header, data_start_index)` — for `.jsonl`/`.meta.json`: `(header or {}, 0)`.
  - `read_hlo_data_chunks(path, ...)` — a `.meta.json` path reads its `.jsonl`.
  - `hlo_to_parquet(path, out, ...)` — works on `.hlo`, `.jsonl` and `.meta.json` through the two above.
  - `keep_keys` now filters on every path: `keep_keys` wins when non-empty, else `omit_keys` drops.

- [ ] **Step 1: Write the failing tests** — append to `helao/core/tests/test_storage_format.py`:

```python
import zipfile

import orjson

from helao.helpers.hlo_data import (
    hlo_to_parquet,
    read_helao_metadata,
    read_hlo,
    read_hlo_header,
    read_hlo_pair_bytes,
    read_hlo_via,
    resolve_data_file,
)
from helao.helpers.to_json import hlo_json_dumps

HEADER = {
    "hlo_version": "2026.10.23",
    "action_name": "CA",
    "column_headings": ["t_s", "v"],
    "optional": {"wl": [400.0, 500.0]},
    "epoch_ns": 1761220800000000000,
}
ROWS = [{"t_s": 0.0, "v": 1.0}, {"t_s": 0.1, "v": [2.0, 3.0]}]
DATA = {"t_s": [0.0, 0.1], "v": [1.0, 2.0, 3.0]}


def write_legacy_hlo(path: Path, header: dict, rows: list) -> Path:
    body = "".join(hlo_json_dumps(r) + "\n" for r in rows)
    path.write_text(yml_dumps(header) + "%%\n" + body, encoding="utf-8")
    return path


def write_pair(dirpath: Path, stem: str, header, rows: list) -> Path:
    """New-format pair; ``header=None`` writes a header-less file. Returns the .jsonl."""
    dirpath.mkdir(parents=True, exist_ok=True)
    if header:
        (dirpath / f"{stem}.meta.json").write_text(dumps_meta(header), encoding="utf-8")
    data = dirpath / f"{stem}.jsonl"
    data.write_text("".join(hlo_json_dumps(r) + "\n" for r in rows), encoding="utf-8")
    return data


def test_read_hlo_every_shape_returns_the_same_pair(tmp_path):
    legacy = write_legacy_hlo(tmp_path / "L__0.hlo", HEADER, ROWS)
    jsonl = write_pair(tmp_path, "N__0", HEADER, ROWS)
    s3 = tmp_path / "S__0.hlo.json"
    s3.write_text(json.dumps({"meta": HEADER, "data": DATA}), encoding="utf-8")
    expected = (HEADER, DATA)
    for p in (legacy, jsonl, tmp_path / "N__0.meta.json", s3):
        meta, data = read_hlo(p)
        assert (meta, dict(data)) == expected, p.name


def test_header_less_jsonl_reads_empty_meta(tmp_path):
    p = write_pair(tmp_path, "H__0", None, ROWS)
    meta, data = read_hlo(p)
    assert meta == {} and dict(data) == DATA


def test_header_without_rows_is_a_lost_artifact(tmp_path):
    (tmp_path / "X__0.meta.json").write_text(dumps_meta(HEADER), encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        read_hlo(tmp_path / "X__0.meta.json")


def test_jsonl_first_line_is_never_a_header(tmp_path):
    """Review Focus 5: a non-object first row is a row, not YAML."""
    p = tmp_path / "R__0.jsonl"
    p.write_text('oops: 1\n{"a": 1}\n', encoding="utf-8")
    meta, data = read_hlo(p)
    assert meta == {} and dict(data) == {"a": [1]}


def test_keep_keys_filters_on_every_shape(tmp_path):
    """Mutation check: the old ``k in keep_keys or k not in omit_keys`` keeps ``v``."""
    legacy = write_legacy_hlo(tmp_path / "L__0.hlo", HEADER, ROWS)
    jsonl = write_pair(tmp_path, "N__0", HEADER, ROWS)
    for p in (legacy, jsonl):
        assert list(read_hlo(p, keep_keys=["t_s"])[1]) == ["t_s"]
        assert list(read_hlo(p, omit_keys=["t_s"])[1]) == ["v"]


def test_jsonl_rows_are_compact_one_object_per_line(tmp_path):
    p = write_pair(tmp_path, "C__0", HEADER, ROWS)
    lines = p.read_text(encoding="utf-8").splitlines()
    assert lines == ['{"t_s":0.0,"v":1.0}', '{"t_s":0.1,"v":[2.0,3.0]}']


@pytest.mark.parametrize(
    "present, name, expected",
    [
        ({"a/X__0.jsonl", "a/X__0.meta.json"}, "a/X__0.hlo.json", "a/X__0.jsonl"),
        ({"a/X__0.hlo"}, "a/X__0.hlo.json", "a/X__0.hlo"),
        ({"a/X__0.jsonl"}, "a/X__0.hlo", "a/X__0.jsonl"),
        ({"a/X__0.jsonl", "a/X__0.meta.json"}, "a/X__0.meta.json", "a/X__0.meta.json"),
        ({"a/X__0.hlo.json"}, "a/X__0.hlo.json", "a/X__0.hlo.json"),
        ({"a/notes.csv"}, "a/notes.csv", "a/notes.csv"),
        (set(), "a/X__0.hlo.json", None),
    ],
)
def test_resolve_data_file(present, name, expected, tmp_path):
    assert resolve_data_file(present, name) == expected
    assert resolve_data_file(present.__contains__, name) == expected
    for rel in present:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x", encoding="utf-8")
    assert resolve_data_file(tmp_path, name) == expected


def test_read_hlo_via_a_zip_reads_the_pair_by_its_s3_name(tmp_path):
    write_pair(tmp_path / "act", "N__0", HEADER, ROWS)
    write_legacy_hlo(tmp_path / "act" / "L__0.hlo", HEADER, ROWS)
    zp = tmp_path / "seq.zip"
    with zipfile.ZipFile(zp, "w") as zf:
        for f in (tmp_path / "act").iterdir():
            zf.write(f, f"exp/act/{f.name}")
    with zipfile.ZipFile(zp) as zf:
        names = set(zf.namelist())
        for logical in ("exp/act/N__0.hlo.json", "exp/act/L__0.hlo.json"):
            meta, data = read_hlo_via(names, zf.read, logical)
            assert (meta, dict(data)) == (HEADER, DATA), logical
        with pytest.raises(FileNotFoundError):
            read_hlo_via(names, zf.read, "exp/act/missing__0.hlo.json")


def test_read_hlo_pair_bytes_header_optional():
    rows = b'{"a": 1}\n{"a": 2}\n'
    assert read_hlo_pair_bytes(None, rows)[0] == {}
    assert dict(read_hlo_pair_bytes(orjson.dumps(HEADER), rows)[1]) == {"a": [1, 2]}


def test_header_and_parquet_from_a_pair(tmp_path):
    jsonl = write_pair(tmp_path, "P__0", HEADER, ROWS[:1] * 3)
    assert read_hlo_header(jsonl) == (HEADER, 0)
    assert read_hlo_header(tmp_path / "P__0.meta.json") == (HEADER, 0)
    out = tmp_path / "P__0.parquet"
    hlo_to_parquet(str(tmp_path / "P__0.meta.json"), str(out), chunk_size=2)
    assert read_helao_metadata(str(out)) == HEADER["optional"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONPATH=$PWD python -m pytest helao/core/tests/test_storage_format.py -q`
Expected: FAIL — `ImportError: cannot import name 'read_hlo_pair_bytes'`.

- [ ] **Step 3: Implement** — in `helao/helpers/hlo_data.py`:

Extend `__all__` with `"read_hlo_pair_bytes"`, `"resolve_data_file"`, `"read_hlo_via"`. Update the module docstring's first paragraph to: "Readers for HELAO data files: the legacy ``.hlo`` (YAML header, ``%%``, JSON lines), the current pair ``X.meta.json`` (header) + ``X.jsonl`` (rows), and the S3 ``X.hlo.json`` shape ``{"meta", "data"}``." Replace the imports block (lines 21-38) with:

```python
import json
import os
from collections import defaultdict
from collections.abc import Callable, Collection
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Union

if TYPE_CHECKING:
    from .helao_data import HelaoData

import orjson
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from ruamel.yaml import YAML

from helao.hexagon.domain.naming import DATA_SUFFIX, HEADER_SUFFIX, data_sibling

from .yml_tools import yml_load

_yaml = YAML()
#: Names that denote a data file and may be resolved to their ``.jsonl``/``.hlo``.
_DATA_NAMES = (".hlo", ".hlo.json", DATA_SUFFIX, HEADER_SUFFIX)


def _keep(key, keep_keys, omit_keys) -> bool:
    """``keep_keys`` wins when given; otherwise ``omit_keys`` drops."""
    return key in keep_keys if keep_keys else key not in omit_keys


def _loads(content: bytes):
    """orjson, falling back to stdlib for the NaN/Infinity tokens it rejects."""
    try:
        return orjson.loads(content)
    except orjson.JSONDecodeError:
        return json.loads(content)


def _read_s3_shape(content: bytes, keep_keys, omit_keys) -> tuple[dict, dict]:
    """The S3 ``X.hlo.json`` document ``{"meta": ..., "data": {col: [...]}}``."""
    doc = _loads(content)
    data = defaultdict(list)
    for k, v in (doc.get("data") or {}).items():
        if _keep(k, keep_keys, omit_keys):
            data[k] = v
    return dict(doc.get("meta") or {}), data
```

Replace `read_hlo` with:

```python
def read_hlo(
    path, keep_keys: list = [], omit_keys: list = []
) -> tuple[dict, dict]:
    """Read any data-file shape and return ``(meta, data)``.

    Dispatch is by name: ``.hlo`` (legacy, YAML header + ``%%`` + rows),
    ``.jsonl`` (rows; header from a sibling ``.meta.json`` when present),
    ``.meta.json`` (header; rows from the sibling ``.jsonl``, which must
    exist -- a missing header is legal, missing rows are a lost artifact),
    ``.hlo.json`` (the S3 ``{"meta", "data"}`` document). Raw ``bytes`` are
    parsed as a legacy ``.hlo``.

    Args:
        path: Filesystem path, or raw legacy ``.hlo`` bytes.
        keep_keys: When non-empty, only these keys are kept from the body.
        omit_keys: Keys to drop from the body when ``keep_keys`` is empty.

    Returns:
        ``(meta, data)``: the header dict and a dict of column lists.
    """
    if isinstance(path, (bytes, bytearray)):
        return read_hlo_bytes(path, keep_keys=keep_keys, omit_keys=omit_keys)
    p = str(path)
    if p.endswith(".hlo.json"):
        return _read_s3_shape(Path(p).read_bytes(), keep_keys, omit_keys)
    if p.endswith((DATA_SUFFIX, HEADER_SUFFIX)):
        header = data_sibling(p, HEADER_SUFFIX)
        meta = orjson.loads(Path(header).read_bytes()) if os.path.isfile(header) else {}
        with open(data_sibling(p, DATA_SUFFIX), "rb") as f:
            _, data = read_hlo_stream(
                f, keep_keys=keep_keys, omit_keys=omit_keys, has_header=False
            )
        return meta, data
    with open(p, "rb") as f:
        return read_hlo_stream(f, keep_keys=keep_keys, omit_keys=omit_keys)
```

In `read_hlo_stream`: add the parameter `has_header: bool = True` after `omit_keys`, document it ("``False`` for a ``.jsonl``: every line is a row, even one that does not start with ``{``"), change `if not header_end:` to `if has_header and not header_end:`, and change the filter line `if k in keep_keys or k not in omit_keys:` to `if _keep(k, keep_keys, omit_keys):`.

Add after `read_hlo_bytes`:

```python
def read_hlo_pair_bytes(
    meta_bytes: Optional[bytes],
    data_bytes: bytes,
    keep_keys: list = [],
    omit_keys: list = [],
) -> tuple[dict, dict]:
    """``(meta, data)`` from the bytes of a ``.meta.json`` (or None) and its ``.jsonl``."""
    meta = orjson.loads(meta_bytes) if meta_bytes else {}
    _, data = read_hlo_stream(
        BytesIO(data_bytes), keep_keys=keep_keys, omit_keys=omit_keys, has_header=False
    )
    return meta, data


Where = Union[str, os.PathLike, Collection[str], Callable[[str], bool]]


def _exists_fn(where: Where) -> Callable[[str], bool]:
    if callable(where):
        return where
    if isinstance(where, (str, os.PathLike)):
        return lambda n: os.path.isfile(os.path.join(where, n))
    names = set(where)
    return names.__contains__


def resolve_data_file(where: Where, name: str) -> Optional[str]:
    """The physical file a recorded data name refers to, or ``None``.

    ``name`` itself first; then, for any of ``X.hlo``/``X.jsonl``/
    ``X.meta.json``/``X.hlo.json``, ``X.jsonl`` and then ``X.hlo`` beside it.
    Metadata records the S3 name ``X.hlo.json``; the local artifact is the
    ``.jsonl`` (current) or ``.hlo`` (legacy).

    Args:
        where: A directory, a collection of names (e.g. a zip ``namelist()``),
            or an ``exists(name) -> bool`` callable.
        name: The recorded name, relative to ``where``.
    """
    exists = _exists_fn(where)
    candidates = [name]
    if name.endswith(_DATA_NAMES):
        candidates += [data_sibling(name, DATA_SUFFIX), data_sibling(name, ".hlo")]
    return next((c for c in dict.fromkeys(candidates) if exists(c)), None)


def read_hlo_via(
    where: Where,
    get_bytes: Callable[[str], bytes],
    name: str,
    keep_keys: list = [],
    omit_keys: list = [],
) -> tuple[dict, dict]:
    """:func:`read_hlo` for a byte source: a zip, a run-tree mapper, a loader.

    Raises:
        FileNotFoundError: ``name`` resolves to nothing, or to a header whose
            ``.jsonl`` is missing.
    """
    exists = _exists_fn(where)
    phys = resolve_data_file(exists, name)
    if phys is None:
        raise FileNotFoundError(name)
    if phys.endswith(".hlo.json"):
        return _read_s3_shape(get_bytes(phys), keep_keys, omit_keys)
    if phys.endswith((DATA_SUFFIX, HEADER_SUFFIX)):
        header, rows = data_sibling(phys, HEADER_SUFFIX), data_sibling(phys, DATA_SUFFIX)
        if not exists(rows):
            raise FileNotFoundError(rows)
        meta_bytes = get_bytes(header) if exists(header) else None
        return read_hlo_pair_bytes(meta_bytes, get_bytes(rows), keep_keys, omit_keys)
    return read_hlo_bytes(get_bytes(phys), keep_keys=keep_keys, omit_keys=omit_keys)
```

At the top of `read_hlo_header` body insert:

```python
    p = str(file_path)
    if p.endswith((DATA_SUFFIX, HEADER_SUFFIX)):
        header = data_sibling(p, HEADER_SUFFIX)
        meta = orjson.loads(Path(header).read_bytes()) if os.path.isfile(header) else {}
        return meta, 0
```

and update its docstring ("For a ``.jsonl``/``.meta.json`` pair the header comes from the ``.meta.json`` and the data start index is 0."). At the top of `read_hlo_data_chunks` body insert:

```python
    if str(file_path).endswith(HEADER_SUFFIX):
        file_path = data_sibling(file_path, DATA_SUFFIX)
```

- [ ] **Step 4: Run to verify they pass, then the existing reader suites**

Run: `PYTHONPATH=$PWD python -m pytest helao/core/tests/test_storage_format.py helao/core/tests/test_legacy_run_readers.py helao/core/tests/test_helao_data_detached.py -q && PYTHONPATH=$PWD python -m helao.core.tests.unit_test_artifact_generation`
Expected: PASS. (`unit_test_artifact_generation` calls `read_hlo(keep_keys=["t_s"], omit_keys=["v"])`; the fix keeps it green.)

- [ ] **Step 5: Commit**

```bash
black helao/helpers/hlo_data.py helao/core/tests/test_storage_format.py
pyright helao/helpers/hlo_data.py
git -C /mnt/STORAGE/repos/helao/helao-async add helao/helpers/hlo_data.py helao/core/tests/test_storage_format.py
git -C /mnt/STORAGE/repos/helao/helao-async commit -m "feat(hlo_data): read .meta.json/.jsonl pairs and S3 shape; fix keep_keys filtering"
```

---

### Task 4: Loaders read both formats

**Files:**
- Modify: `helao/helpers/file_mapper.py` (`locate` 101-142, `read_hlo` 193-217, `read_yml` 220-242)
- Modify: `helao/helpers/helao_data.py` (`__init__` 60-200, `yml` 210-222, `_detached_bytes` 290-304, `read_hlo` 321-348, `_resolve_zip_member` 405-426 deleted, `read_data_file` 440-457)
- Modify: `helao/core/drivers/data/loaders/localfs.py` (index 257-299, `parse_*_path` 44/99/124/155, `get_yml` 445-470, `get_hlo` 651-675, `HelaoProcess.hlo` 1014-1033)
- Modify: `helao/core/drivers/data/loaders/model_base.py` (`data_files` 107-117, `hlo_file_tup_type` 135)
- Modify: `helao/core/drivers/data/loaders/helao_loader.py` (`get_hlo` 464-471)
- Modify: `helao/ui/shared/data_browser/sources.py`, `helao/ui/shared/data_browser/readers.py`
- Test: `helao/core/tests/test_storage_format.py` (append)

**Interfaces:**
- Consumes: `meta_kind`, `RECORD_KINDS`, `HEADER_SUFFIX`, `DATA_SUFFIX` (Task 1); `read_meta`, `meta_glob` (Task 2); `read_hlo_via`, `resolve_data_file`, `read_hlo_pair_bytes` (Task 3).
- Produces: no new public names. Behaviour: every loader finds `-seq/-exp/-act/-prc.json` beside `.yml`, reads `X.jsonl` (+ `.meta.json`) wherever it read `X.hlo`, and resolves a recorded `X.hlo.json` name to `X.jsonl` or `X.hlo`. `HelaoData._resolve_zip_member` is removed (its only caller was `read_hlo`).

- [ ] **Step 1: Write the failing tests** — append to `helao/core/tests/test_storage_format.py`:

```python
from helao.core.drivers.data.loaders.localfs import LocalLoader
from helao.helpers.file_mapper import FileMapper
from helao.helpers.helao_data import HelaoData
from helao.ui.shared.data_browser.readers import make_zip_locator, read_dataset
from helao.ui.shared.data_browser.sources import RunsSourceIndex

U_SEQ = "00000000-0000-0000-0000-000000000001"
U_EXP = "00000000-0000-0000-0000-000000000002"
U_ACT = "00000000-0000-0000-0000-000000000003"


def _new_tree(root: Path) -> dict:
    """A one-seq/one-exp/one-act RUNS_FINISHED tree in the NEW format."""
    seq = root / "RUNS_FINISHED" / "25.28" / "0716" / "131415__GMTEST__golden"
    exp = seq / "250716.131420__TEST_exp"
    act = exp / "0__0__SIM__acquire_data"
    write_meta(seq / "250716.131415123456-seq.json", {
        "file_type": "sequence", "sequence_uuid": U_SEQ, "sequence_name": "GMTEST",
        "sequence_label": "golden", "sequence_timestamp": "2025-07-16 13:14:15.123456",
        "sequence_status": ["finished"], "sequence_params": {},
    })
    write_meta(exp / "250716.131420123456-exp.json", {
        "file_type": "experiment", "experiment_uuid": U_EXP, "sequence_uuid": U_SEQ,
        "experiment_name": "TEST_exp", "experiment_timestamp": "2025-07-16 13:14:20.123456",
        "experiment_status": ["finished"], "experiment_params": {},
    })
    write_meta(act / "250716.131421123456-act.json", {
        "file_type": "action", "action_uuid": U_ACT, "experiment_uuid": U_EXP,
        "sequence_uuid": U_SEQ, "action_name": "acquire_data",
        "action_timestamp": "2025-07-16 13:14:21.123456",
        "action_status": ["finished"], "action_params": {"label": "Ɖµ"},
        "files": [{"file_name": "WsSim-0.0.0.0__0.jsonl", "file_type": "helao__file"}],
    })
    write_pair(act, "WsSim-0.0.0.0__0", HEADER, ROWS)
    return {"seq": seq, "exp": exp, "act": act}


def test_file_mapper_reads_pair_and_json_meta(tmp_path):
    t = _new_tree(tmp_path)
    fm = FileMapper(t["act"])
    rel = os.path.join(*t["act"].relative_to(tmp_path / "RUNS_FINISHED").parts)
    meta, data = fm.read_hlo(os.path.join(rel, "WsSim-0.0.0.0__0.hlo.json"))
    assert (meta, dict(data)) == (HEADER, DATA)
    assert fm.read_yml(os.path.join(rel, "250716.131421123456-act.json"))["action_uuid"] == U_ACT


def test_helao_data_walks_a_json_tree(tmp_path):
    t = _new_tree(tmp_path)
    hd = HelaoData(str(t["seq"] / "250716.131415123456-seq.json"))
    assert hd.type == "seq" and hd.uuid == U_SEQ
    (exp,) = hd.exp
    (act,) = exp.act
    assert act.type == "act" and act.uuid == U_ACT
    assert [os.path.basename(p) for p in act.data_files] == ["WsSim-0.0.0.0__0.jsonl"]
    meta, data = act.read_data_file(act.data_files[0])
    assert (meta, dict(data)) == (HEADER, DATA)


def test_zipped_json_meta_keeps_non_ascii(tmp_path):
    """Review Focus 3: the legacy 0x89 repair must not touch a JSON member."""
    t = _new_tree(tmp_path)
    zp = tmp_path / "RUNS_SYNCED" / "25.28" / "0716" / "131415__GMTEST__golden.zip"
    zp.parent.mkdir(parents=True)
    with zipfile.ZipFile(zp, "w") as zf:
        for f in t["seq"].rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(t["seq"]).as_posix())
    # The act label is "Ɖµ": 'Ɖ' is C6 89 in UTF-8, so a blind 0x89 -> '%'
    # swap turns it into invalid UTF-8 and the read raises or garbles.
    act_member = "250716.131420__TEST_exp/0__0__SIM__acquire_data/250716.131421123456-act.json"
    ll = LocalLoader(data_path=str(zp))
    assert ll.get_yml(act_member)["action_params"]["label"] == "Ɖµ"
    hd = HelaoData(str(zp))
    (act,) = hd.exp[0].act
    assert act.yml["action_params"]["label"] == "Ɖµ"
    meta, data = act.read_hlo(act.data_files[0])
    assert (meta, dict(data)) == (HEADER, DATA)


def test_local_loader_indexes_and_reads_a_json_tree(tmp_path):
    t = _new_tree(tmp_path)
    ll = LocalLoader(data_path=str(t["seq"]))
    assert (len(ll.sequences), len(ll.experiments), len(ll.actions)) == (1, 1, 1)
    meta, data = ll.get_act(0).hlo
    assert (meta, dict(data)) == (HEADER, DATA)


def test_data_browser_indexes_and_reads_a_pair(tmp_path):
    t = _new_tree(tmp_path)
    rows = RunsSourceIndex(tmp_path, "FINISHED").index()
    assert list(rows.file_name) == ["WsSim-0.0.0.0__0.jsonl"]
    assert list(rows.file_type) == ["jsonl"]
    meta, data = read_dataset(rows.locator.iloc[0])
    assert (meta, dict(data)) == (HEADER, DATA)
    zp = tmp_path / "z.zip"
    with zipfile.ZipFile(zp, "w") as zf:
        for f in t["act"].iterdir():
            zf.write(f, f"a/{f.name}")
    meta, data = read_dataset(make_zip_locator(str(zp), "a/WsSim-0.0.0.0__0.jsonl"))
    assert (meta, dict(data)) == (HEADER, DATA)
```

Add `import os` at the top of the test module if not already imported. If `RunsSourceIndex.index()` returns a list rather than a DataFrame in this checkout, read `_rows_to_index_df` in `sources.py` first and adapt the two `rows.` accesses — do not change the production return type.

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONPATH=$PWD python -m pytest helao/core/tests/test_storage_format.py -q -k "file_mapper or helao_data or zipped or local_loader or data_browser"`
Expected: FAIL (FileNotFoundError / IndexError from `-seq.yml`-only globs).

- [ ] **Step 3: Implement `FileMapper`** (`helao/helpers/file_mapper.py`)

Imports: replace `from .hlo_data import read_hlo_bytes` and `from .yml_tools import yml_load` with:

```python
from .hlo_data import read_hlo_via, resolve_data_file
from .meta_io import read_meta
```

Replace the body of `locate` from `if "PROCESSES" in p:` to the end with:

```python
        if "PROCESSES" in p:
            return p
        # Metadata records a data file under its S3 name ``X.hlo.json``; the
        # local or zipped artifact is ``X.jsonl`` (current) or ``X.hlo``
        # (legacy). resolve_data_file tries the name as given, then those.
        hits: dict = {}

        def _probe(cand: str) -> bool:
            hits[cand] = self._locate_one(cand)
            return hits[cand] is not None

        found = resolve_data_file(_probe, p)
        return hits[found] if found is not None else None

    def _locate_one(self, p: str):
        """:meth:`locate` for exactly one candidate name."""
        for root in self.roots:
            testp = Path(os.path.join(self.prestr, root, p))
            if testp.exists():
                return testp
        # Only archives were ever zipped, and only they need the search.
        if self.is_legacy:
            return self._locate_in_zip(p)
        return None
```

Replace the `for` loop in `read_hlo` with:

```python
        for _ in range(retries + 1):
            try:
                return read_hlo_via(
                    lambda n: self.locate(n) is not None, self.read_bytes, p
                )
            except ValueError:  # retry in case file not fully written
                continue
        return None
```

and update its docstring's parser sentence to ":func:`read_hlo_via` (``.jsonl`` pair, legacy ``.hlo`` or S3 ``.hlo.json``)". Replace the body of `read_yml` after `if lp is None: raise FileNotFoundError` with:

```python
        elif isinstance(lp, tuple):
            zip_path, member = lp
            with ZipFile(zip_path, "r") as zf:
                raw = zf.read(member)
            if member.endswith(".yml"):
                # Legacy zips carry a stray 0x89 byte. Never on JSON: 0x89 is a
                # UTF-8 continuation byte there (Review Focus 3).
                raw = raw.replace(b"\x89", b"%")
            return dict(read_meta(raw, name=member))
        else:
            return dict(read_meta(lp))
```

Update its docstring: "Resolve and parse a metadata file (``.json`` or legacy ``.yml``)".

- [ ] **Step 4: Implement `HelaoData`** (`helao/helpers/helao_data.py`)

Imports: replace `from .hlo_data import read_hlo_bytes` and `from .yml_tools import yml_load` with:

```python
from helao.hexagon.domain.naming import HEADER_SUFFIX, meta_kind

from .hlo_data import read_hlo_via, resolve_data_file
from .meta_io import meta_glob, read_meta
```

Add a module-level helper after `LOGGER`:

```python
def _is_data_member(p: str) -> bool:
    """A data file: not a record/process/analysis meta, header, ``.yml`` or ``.prg``."""
    return (
        p.split(".")[-1] not in ("yml", "prg")
        and meta_kind(p) is None
        and not p.endswith(HEADER_SUFFIX)
    )
```

In `__init__`, delete `skip_exts = ["yml", "prg"]` and apply these replacements:

| Line(s) | Before | After |
|---|---|---|
| zip `ymlpath` (82-84) | `[p for p in self.zflist if p.endswith("-seq.yml")][0]` | `[p for p in self.zflist if meta_kind(p) == "seq"][0]` |
| zip `type` (86) and dir `type` (144) | `self.ymlpath.split("-")[-1].replace(".yml", "")` | `meta_kind(self.ymlpath)` |
| zip `sub_exps` (95) | `if p.endswith("-exp.yml") and p.startswith(self.ymldir)` | `if meta_kind(p) == "exp" and p.startswith(self.ymldir)` |
| zip `sub_acts` (109) | `if p.endswith("-act.yml") and p.startswith(self.ymldir)` | `if meta_kind(p) == "act" and p.startswith(self.ymldir)` |
| zip `_data_files` (121) | `if p.split(".")[-1] not in skip_exts and p.startswith(self.ymldir)` | `if _is_data_member(p) and p.startswith(self.ymldir)` |
| dir `ymlpath` (134-138) | `[x for x in sorted(glob(os.path.join(self.target, "*.yml"))) if x.endswith(("-seq.yml", "-exp.yml", "-act.yml"))][0]` | `str(meta_glob(self.target, ("seq", "exp", "act"))[0])` |
| dir target test (139) | `elif target.endswith(".yml"):` | `elif meta_kind(target) is not None:` |
| dir `self.seq` glob (162) | `glob(os.path.join(yml_reldir, "*", "*-seq.yml"))` | `[str(p) for p in meta_glob(yml_reldir, "seq", "*/*")]` |
| dir `self.exp` glob (171) | `glob(os.path.join(yml_reldir, "*", "*-exp.yml"))` | `[str(p) for p in meta_glob(yml_reldir, "exp", "*/*")]` |
| dir `self.act` glob (180) | `glob(os.path.join(yml_reldir, "*", "*-act.yml"))` | `[str(p) for p in meta_glob(yml_reldir, "act", "*/*")]` |
| dir `_data_files` (189) | `if x.split(".")[-1] not in skip_exts and os.path.isfile(x)` | `if _is_data_member(x) and os.path.isfile(x)` |

`meta_glob(root, kind, "*/*")` matches `root/*/*-kind.*` — the old `os.path.join(yml_reldir, "*", "*-seq.yml")` shape — and accepts the `RUNS_*` wildcard in `yml_reldir`. Keep the `sorted(..., key=...)` wrappers as they are. If `glob` is no longer used in the module after this, remove its import.

Replace the `yml` property body:

```python
        if self._yml_cache:
            return self._yml_cache
        if self.target.endswith(".zip"):  # this will always be a zipped sequence
            with zipfile.ZipFile(self.target, "r") as zf:
                yml_dict = read_meta(zf.read(self.ymlpath), name=self.ymlpath)
        else:
            yml_dict = read_meta(self.ymlpath)
        self._yml_cache = yml_dict
        return yml_dict
```

(and its docstring: "Return the parsed record metadata (``.json`` or legacy ``.yml``), cached."). If `builtins` is now unused, remove its import.

In `_detached_bytes` replace the two lines from `names = ...` through the `for` loop with:

```python
        name = resolve_data_file(os.path.isfile, p)
        if name is not None:
            with open(name, "rb") as f:
                return f.read()
        raise FileNotFoundError(p)
```

and change its docstring's last sentence to "A recorded ``X.hlo.json`` resolves to ``X.jsonl`` or ``X.hlo`` (:func:`resolve_data_file`)."

Replace the body of `read_hlo` (after the docstring) with:

```python
        if self.target.endswith(".zip") and RunDir.NOSYNC.value not in hlotarget:
            return read_hlo_via(
                set(self.zflist), self.read_file, hlotarget, keep_keys, omit_keys
            )
        if not any(is_run_root(v) for v in Path(hlotarget).parts):
            # Detached: a record copied out of any run tree is read where it is.
            return read_hlo_via(
                os.path.isfile,
                lambda n: Path(n).read_bytes(),
                hlotarget,
                keep_keys,
                omit_keys,
            )
        fm = FileMapper(hlotarget)
        return fm.read_hlo(self._runs_relpath(hlotarget))
```

Delete `_resolve_zip_member` entirely. In `read_data_file` replace the first condition with:

```python
        if target_data_file.endswith((".hlo", ".hlo.json", ".jsonl", ".meta.json")):
            return self.read_hlo(target_data_file)
```

and update the comment above it to name both the `.jsonl` pair and legacy `.hlo`.

- [ ] **Step 5: Implement `LocalLoader`** (`helao/core/drivers/data/loaders/localfs.py`)

Imports: replace `from helao.helpers.hlo_data import read_hlo_bytes` and `from helao.helpers.yml_tools import yml_load` with:

```python
from helao.helpers.hlo_data import read_hlo_via
from helao.helpers.meta_io import meta_glob, read_meta
from helao.hexagon.domain.naming import meta_kind
```

Replacements:

| Site | Before | After |
|---|---|---|
| `parse_seq_path` 44 | `if ymlp.endswith(".yml") or target.endswith(".zip"):` | `if meta_kind(ymlp) is not None or target.endswith(".zip"):` |
| `parse_exp_path` 99 | `if ymlp.endswith(".yml"):` | `if meta_kind(ymlp) is not None:` |
| `parse_act_path` 124 | `if ymlp.endswith(".yml"):` | `if meta_kind(ymlp) is not None:` |
| `parse_prc_path` 155 | `idx, prc_uuid, techname = yml_file.replace("-prc.yml", "").split("__")` | `idx, prc_uuid, techname = yml_file.rsplit("-prc.", 1)[0].split("__")` |
| index zip 261 | `_yml_paths = [x for x in zip_contents if x.endswith(".yml")]` | `_yml_paths = [x for x in zip_contents if meta_kind(x) is not None]` |
| index zip 267 | `process_uuid_of(x) for x in _yml_paths if x.endswith("-prc.yml")` | `process_uuid_of(x) for x in _yml_paths if meta_kind(x) == "prc"` |
| index zip 271-273 | `for x in glob(os.path.join(process_dir, "**", "*-prc.yml"), recursive=True)` | `for x in map(str, meta_glob(process_dir, "prc", "**/*"))` |
| index dir 279-281 | `_yml_paths += glob(os.path.join(check_dir, "**", "*.yml"), recursive=True)` | `_yml_paths += [str(p) for p in meta_glob(check_dir, ("seq", "exp", "act", "prc"), "**/*")]` |
| index file 285-288 | `_yml_paths += glob(os.path.join(os.path.dirname(check_dir), "**", "*.yml"), recursive=True,)` | `_yml_paths += [str(p) for p in meta_glob(os.path.dirname(check_dir), ("seq", "exp", "act", "prc"), "**/*")]` |
| index classify 297-299 | `x for x in _yml_paths if x.endswith(f"-{suffix}.yml")` | `x for x in _yml_paths if meta_kind(x) == suffix` |

`get_yml`: replace the zip branch body with

```python
            with ZipFile(self.target, "r") as zf:
                raw = zf.read(path)
            if path.endswith(".yml"):
                raw = raw.replace(b"\x89", b"%")  # legacy repair; never on JSON
            metad = dict(read_meta(raw, name=path))
```

`get_hlo`: replace the zip branch with

```python
        if self.target.endswith(".zip"):
            hlotarget = "/".join([os.path.dirname(yml_path), hlo_fn])
            with ZipFile(self.target, "r") as zf:
                return HloPayload(*read_hlo_via(set(zf.namelist()), zf.read, hlotarget))
```

`HelaoProcess.hlo`: replace from the comment `# Through get_bytes("", ...)` to the end of the method with

```python
        # Through get_bytes("", ...) like ``artifacts``, so a synced sequence
        # zip works too. Process files name the S3 ``.hlo.json``; on disk and
        # in the zip it is the ``.jsonl`` pair or the legacy ``.hlo``.
        cache: dict = {}

        def _get(name: str) -> bytes:
            if name not in cache:
                cache[name] = self.loader.get_bytes("", name).read()
            return cache[name]

        def _has(name: str) -> bool:
            try:
                _get(name)
            except (FileNotFoundError, KeyError):
                return False
            return True

        try:
            return HloPayload(*read_hlo_via(_has, _get, rel))
        except FileNotFoundError:
            raise FileNotFoundError(f"{rel} not found under {self.loader.target}")
```

Update the module docstring line 3 to "Indexes ``*-{seq,exp,act,prc}.json`` (and legacy ``.yml``) files". If `glob` / `yml_load` are no longer used, remove the imports.

- [ ] **Step 6: Implement `model_base` and `helao_loader`**

`helao/core/drivers/data/loaders/model_base.py` `data_files`: add `or x["file_name"].endswith(".jsonl")` after the `.hlo` test. `hlo_file_tup_type`: change `x["file_name"].endswith(".hlo")` to `x["file_name"].endswith((".hlo", ".jsonl"))`.

`helao/core/drivers/data/loaders/helao_loader.py` `get_hlo` (remote S3 keys): replace

```python
        if hlo_fn.endswith(".hlo"):
            keystr = f"raw_data/{str(action_uuid)}/{hlo_fn}.json"
```

with

```python
        if hlo_fn.endswith((".hlo", ".jsonl")):
            keystr = f"raw_data/{str(action_uuid)}/{data_stem(hlo_fn)}.hlo.json"
```

and add `from helao.hexagon.domain.naming import data_stem` to its imports.

- [ ] **Step 7: Implement the data browser**

`helao/ui/shared/data_browser/sources.py`:
- `DATA_EXTS = (".hlo", ".jsonl", ".hlo.json", ".parquet")` with the comment "Bare ``.json`` is not a data extension: records (``-act.json``) and headers (``.meta.json``) are JSON too."
- Replace `import yaml` with `from helao.helpers.meta_io import meta_glob, read_meta` and `from helao.hexagon.domain.naming import meta_kind`.
- Replace `_safe_yaml` / `_safe_yaml_bytes` with:

```python
def _safe_meta(path):
    try:
        return read_meta(path) or {}
    except Exception:
        return {}


def _safe_meta_bytes(content, name):
    try:
        return read_meta(content, name=name) or {}
    except Exception:
        return {}
```

- Site replacements:

| Line | Before | After |
|---|---|---|
| 254 | `for act_yml in sorted(seq_dir.glob("*/*/*-act.yml")):` | `for act_yml in meta_glob(seq_dir, "act", "*/*/*"):` |
| 257, 421, 446 | `_safe_yaml(<p>)` | `_safe_meta(<p>)` |
| 260 | `if f.is_file() and f.suffix.lower() in DATA_EXTS:` | `if f.is_file() and f.name.lower().endswith(DATA_EXTS):` |
| 291-292 | `if n.endswith("-act.yml"):` / `act_meta[...] = _safe_yaml_bytes(zf.read(n))` | `if meta_kind(n) == "act":` / `act_meta[...] = _safe_meta_bytes(zf.read(n), n)` |
| 294-296 | `ext = posixpath.splitext(n)[1].lower()` / `if ext not in DATA_EXTS:` | `if not n.lower().endswith(DATA_EXTS):` (keep `ext = posixpath.splitext(n)[1].lower()` if the row below uses it) |
| 415, 440 | `for prc_yml in sorted(day.glob("*/*/*-prc.yml")):` | `for prc_yml in meta_glob(day, "prc", "*/*/*"):` |
| 477 | `if not n.endswith("-prc.yml"):` | `if meta_kind(n) != "prc":` |
| 482 | `meta = _safe_yaml_bytes(zf.read(n))` | `meta = _safe_meta_bytes(zf.read(n), n)` |
| 501 | `if not fn or posixpath.splitext(fn)[1].lower() not in DATA_EXTS:` | `if not fn or not fn.lower().endswith(DATA_EXTS):` |

`file_type` stays `splitext(...)[1].lstrip(".")`, so a `.jsonl` row is `jsonl` and an S3-named `X.hlo.json` stays `json` as before.

- `_index_analyses` (spec §3): replace the first three lines of the loop body with

```python
            models = meta_glob(ana_dir, "ana")
            legacy = sorted(p for p in ana_dir.glob("*.yml"))
            # The AnalysisModel: <uuid>-ana.json, else the legacy first <uuid>.yml.
            model = models[0] if models else (legacy[0] if legacy else None)
            meta = _safe_meta(model) if model is not None else {}
```

and the `local_jsons` line with

```python
            local_jsons = {
                p.name: p for p in ana_dir.glob("*.json") if meta_kind(p) != "ana"
            }
```

`helao/ui/shared/data_browser/readers.py`: add the `jsonl` format to `read_dataset` (before `if fmt == "json":`):

```python
    if fmt == "jsonl":
        return read_hlo_pair_bytes(_header_bytes(locator), content)
```

and add, with the import changed to `from helao.helpers.hlo_data import read_hlo_bytes, read_hlo_pair_bytes` plus `from helao.hexagon.domain.naming import HEADER_SUFFIX, data_sibling`:

```python
def _header_bytes(locator: str) -> Optional[bytes]:
    """The sibling ``.meta.json`` of a ``.jsonl`` locator, or None when absent."""
    parsed = parse_locator(locator)
    try:
        if parsed[0] == "zip":
            _, zip_path, member = parsed
            return _read_bytes(make_zip_locator(zip_path, data_sibling(member, HEADER_SUFFIX)))[1]
        return _read_bytes(data_sibling(parsed[1], HEADER_SUFFIX))[1]
    except (FileNotFoundError, KeyError):
        return None
```

- [ ] **Step 8: Run to verify they pass, plus the existing loader suites**

Run: `PYTHONPATH=$PWD python -m pytest helao/core/tests/test_storage_format.py helao/core/tests/test_loader_parity.py helao/core/tests/test_legacy_run_readers.py helao/core/tests/test_helao_data_detached.py helao/core/tests/test_prc_readers.py helao/core/tests/test_reflex_data_browser.py helao/deploy/test/tests/test_data_browser.py helao/core/tests/test_runs_layout.py -q`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
F="helao/helpers/file_mapper.py helao/helpers/helao_data.py helao/core/drivers/data/loaders/localfs.py helao/core/drivers/data/loaders/model_base.py helao/core/drivers/data/loaders/helao_loader.py helao/ui/shared/data_browser/sources.py helao/ui/shared/data_browser/readers.py helao/core/tests/test_storage_format.py"
black $F && pyright $F
git -C /mnt/STORAGE/repos/helao/helao-async add $F
git -C /mnt/STORAGE/repos/helao/helao-async commit -m "feat(loaders): dual-read JSON records and .jsonl data pairs"
```

---

### Task 5: Record discovery (run_state, reconcile, retire, process_locator, processors, rank, week_window)

**Files:**
- Modify: `helao/helpers/run_state.py` (`_scan_top_level` 306-345, `rebuild_from_tree` 436-439; new `top_level_pair`)
- Modify: `helao/hexagon/app/action_host.py` (`_reconcile_one` 1426-1427)
- Modify: `helao/ui/shared/retire.py` (`top_level` 86-102, `locate` 119, `_scan_local` 250/254, `_analysis_dirs` 274)
- Modify: `helao/core/drivers/data/process_locator.py` (`process_uuid_of` 37-39, `_experiment_dir` 44, `find_process_ymls` 64-66 / 75-77)
- Modify: `helao/helpers/processors.py` (50-62)
- Modify: `helao/deploy/hte/servers/action/sync_server.py` (217-224), `helao/deploy/test/servers/action/sim_db_server.py` (112-119)
- Modify: `helao/deploy/hte/specifications/week_window.py` (53)
- Test: `helao/core/tests/test_storage_format.py` (append), `helao/deploy/hte/tests/test_week_window_lister.py`, `helao/deploy/hte/tests/test_sync_server_recovery.py`

**Interfaces:**
- Consumes: `meta_kind`, `META_SUFFIXES` (Task 1); `meta_glob`, `read_meta`, `write_meta` (Task 2).
- Produces: `run_state.top_level_pair(line: str, is_json: bool) -> tuple[Optional[str], Optional[str]]` — `(key, value)` of a top-level scalar line (YAML `key: value`, or pretty-JSON `  "key": value,`), else `(None, None)`. JSON `null` comes back as `"None"`.

- [ ] **Step 1: Write the failing tests** — append to `helao/core/tests/test_storage_format.py`:

```python
from helao.core.drivers.data.process_locator import find_process_ymls, process_uuid_of
from helao.helpers.run_state import (
    identify_record,
    rebuild_from_tree,
    top_level_pair,
)
from helao.ui.shared import retire


@pytest.mark.parametrize(
    "line, is_json, pair",
    [
        ("action_uuid: abc", False, ("action_uuid", "abc")),
        ('  "action_uuid": "abc",', True, ("action_uuid", "abc")),
        ('  "action_order": 3,', True, ("action_order", "3")),
        ('  "x": null', True, ("x", "None")),
        ('    "nested": "no",', True, (None, None)),
        ('  "params": {', True, (None, None)),
        ('  "list": [],', True, (None, None)),
        ("{", True, (None, None)),
    ],
)
def test_top_level_pair(line, is_json, pair):
    assert top_level_pair(line, is_json) == pair


def test_identify_record_reads_a_json_record_with_a_huge_head(tmp_path):
    """The uuid sits past the head window, as in a plate-sized -seq."""
    p = write_meta(
        tmp_path / "250716.131415123456-seq.json",
        {"sequence_params": {"big": ["x" * 80] * 2000}, "sequence_uuid": U_SEQ},
    )
    assert identify_record(p) == (U_SEQ, "sequence", None)


def test_rebuild_from_tree_counts_json_records(tmp_path):
    t = _new_tree(tmp_path)
    j = rebuild_from_tree(tmp_path / "RUNS_FINISHED", tmp_path / "STATES", "SYNC")
    assert sorted(r["kind"] for r in j.working_set().values()) == [
        "action", "experiment", "sequence",
    ]
    assert U_ACT in j.working_set()


def test_retire_locates_and_scans_json_records(tmp_path):
    t = _new_tree(tmp_path)
    (loc,) = retire.locate(str(tmp_path), U_SEQ)
    local, files = retire._scan_local([loc])
    assert files == 2 and local["EXPERIMENT"] == {U_EXP} and local["ACTION"] == {U_ACT}


def test_process_locator_finds_json_and_yml_processes(tmp_path):
    t = _new_tree(tmp_path)
    write_meta(t["exp"] / f"0__{U_EXP}__CV-prc.json", {"process_uuid": U_EXP})
    (t["exp"] / f"1__{U_ACT}__CA-prc.yml").write_text("process_uuid: x\n", encoding="utf-8")
    found = find_process_ymls(t["exp"] / "250716.131420123456-exp.json")
    assert [p.name for p in found] == [f"0__{U_EXP}__CV-prc.json", f"1__{U_ACT}__CA-prc.yml"]
    assert [process_uuid_of(p) for p in found] == [U_EXP, U_ACT]
```

Append to `helao/deploy/hte/tests/test_week_window_lister.py` (it already has `_seqdir`):

```python
def test_lists_json_sequence_dirs(tmp_path):
    now = datetime.now()
    path = os.path.join(tmp_path, now.strftime("%Y"), now.strftime("%m%d"), "120000__SEQ_J__lbl")
    os.makedirs(path)
    open(os.path.join(path, "SEQ_J-seq.json"), "w", encoding="utf-8").close()
    assert WeekWindowSpecParser().lister(str(tmp_path)) == [path]
```

Append to `helao/deploy/hte/tests/test_sync_server_recovery.py` (uses the file's own `_make_app`, `_prime`, `_route`, `_QuarantineDriver`):

```python
@pytest.mark.asyncio
async def test_finish_yml_ranks_json_records(installed_config):
    app = _make_app(installed_config)
    drv = _QuarantineDriver(quarantined=False)
    _prime(app, drv)
    for path, rank in (("/x/a-seq.json", 2), ("/x/b-exp.json", 1), ("/x/c-act.json", 0)):
        await _route(app, "/finish_yml")(yml_path=path)
        assert drv.calls[-1] == ("enqueue", path, rank)
```

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONPATH=$PWD python -m pytest helao/core/tests/test_storage_format.py helao/deploy/hte/tests/test_week_window_lister.py helao/deploy/hte/tests/test_sync_server_recovery.py -q`
Expected: FAIL — `ImportError: cannot import name 'top_level_pair'`, then the glob-based misses.

- [ ] **Step 3: Implement `run_state`** (`helao/helpers/run_state.py`)

Add after `_TAIL_BYTES`:

```python
def top_level_pair(line: str, is_json: bool) -> tuple:
    """``(key, value)`` of one top-level scalar line, else ``(None, None)``.

    YAML: ``key: value``. JSON as ``dumps_meta`` writes it (two-space indent):
    ``  "key": value,`` with a scalar value -- an opening ``{``/``[`` or a
    deeper indent is not top level. Values come back as strings, ``null`` as
    ``"None"``.
    """
    if not is_json:
        key, sep, value = line.partition(": ")
        return (key, value.strip()) if sep else (None, None)
    if not line.startswith('  "') or line.startswith("   "):
        return None, None
    key, sep, value = line[2:].partition(": ")
    if not sep:
        return None, None
    try:
        key, value = json.loads(key), json.loads(value.rstrip().rstrip(","))
    except ValueError:
        return None, None
    if isinstance(value, (dict, list)):
        return None, None
    return key, str(value)
```

In `_scan_top_level`, add `is_json = path.name.endswith(".json")` after the docstring and replace both partition sites:

```python
    for line in lines:
        key, value = top_level_pair(line, is_json)
        if key in keys:
            found.setdefault(key, value)
```

```python
                for line in f:
                    key, value = top_level_pair(line.rstrip("\n"), is_json)
                    if key in keys:
                        found.setdefault(key, value)
                        if found.keys() >= keys:
                            break
```

In `rebuild_from_tree` replace `if not name.endswith(".yml"):` with `if not name.endswith((".json", ".yml")):`. (The `_KIND_BY_SUFFIX.get(yml.stem[-4:])` gate already drops `X.meta.json`, `-prc`, `-ana`.) Update the `_HEAD_BYTES` comment's first line to "A record (yml or json) is read only at its two ends".

- [ ] **Step 4: Implement the rest**

`helao/hexagon/app/action_host.py` `_reconcile_one` (1426-1427): replace

```python
        for yml in sorted(glob(os.path.join(act_dir, "*-act.yml"))):
            candidate = Action.model_validate(yml_load(yml))
```

with

```python
        for yml in meta_glob(act_dir, "act"):
            candidate = Action.model_validate(read_meta(yml))
```

and the warning text `no -act.yml in` with `no -act record in`. Add `from helao.helpers.meta_io import meta_glob, read_meta`; drop `yml_load` from the `yml_tools` import if now unused. Update `helao/hexagon/tests/test_reconcile_interrupted.py:188` to `assert any("no -act record" in m for m in warnings)`.

`helao/ui/shared/retire.py`: import `top_level_pair` beside `_prg_is_complete` and `from helao.helpers.meta_io import meta_glob`, `from helao.hexagon.domain.naming import meta_kind`. Replace `top_level`'s loop:

```python
    is_json = path.endswith(".json")
    with open(path, errors="replace", encoding="utf-8") as f:
        for line in f:
            key, val = top_level_pair(line.rstrip("\n"), is_json)
            if key in want and key not in found:
                found[key] = val
                if len(found) == len(want):
                    break
```

(Docstring: "First top-level ``key: value`` line (YAML) or ``  "key": value`` line (JSON) per key".) Replace the globs:

| Line | Before | After |
|---|---|---|
| 119 | `glob.glob(os.path.join(root, "RUNS*", "*", "*", "*", "*-seq.yml"))` | `map(str, meta_glob(os.path.join(root, "RUNS*"), "seq", "*/*/*/*"))` |
| 250 | `glob.glob(os.path.join(seq_dir, "*", "*-exp.yml"))` | `map(str, meta_glob(seq_dir, "exp", "*/*"))` |
| 254 | `glob.glob(os.path.join(seq_dir, "*", "*", "*-act.yml"))` | `map(str, meta_glob(seq_dir, "act", "*/*/*"))` |
| 274 | `if not name.endswith(".yml") or not os.path.isfile(path):` | `if not (name.endswith(".yml") or meta_kind(name) == "ana") or not os.path.isfile(path):` |

`helao/core/drivers/data/process_locator.py`:

```python
def process_uuid_of(path: "str | os.PathLike[str]") -> str:
    """The process uuid a ``-prc.json`` / ``-prc.yml`` filename carries.
    ...keep the rest of the docstring...
    """
    name = Path(path).name
    parts = name.rsplit("-prc.", 1)[0].split("__") if meta_kind(name) == "prc" else []
    return parts[1] if len(parts) >= 3 else ""


def _experiment_dir(experiment: "str | os.PathLike[str]") -> Path:
    p = Path(experiment)
    return p.parent if p.is_file() or meta_kind(p) is not None else p
```

and in `find_process_ymls` replace both `(x for x in exp_dir.glob("*-prc.yml") if x.is_file())` / `(y for y in mirror.glob("*-prc.yml") if y.is_file())` with `(x for x in meta_glob(exp_dir, "prc") if x.is_file())` / `(y for y in meta_glob(mirror, "prc") if y.is_file())`. Imports: `from helao.helpers.meta_io import meta_glob`, `from helao.hexagon.domain.naming import meta_kind`. Docstrings: "``-prc.json`` (or legacy ``-prc.yml``)".

`helao/helpers/processors.py` (50-62):

```python
        exp_yml_paths = meta_glob(exp_dir, "exp")
        self.exp_yml_path = str(exp_yml_paths[0]) if exp_yml_paths else None
        seq_dir = os.path.dirname(exp_dir)
        seq_yml_paths = meta_glob(seq_dir, "seq")
        self.seq_yml_path = str(seq_yml_paths[0]) if seq_yml_paths else None
```

with `from helao.helpers.meta_io import meta_glob`; delete the now-stale comment about `-prc.yml` sort order (meta_glob filters by kind); remove `glob` import if unused.

`helao/deploy/hte/servers/action/sync_server.py` (217-224) and `helao/deploy/test/servers/action/sim_db_server.py` (112-119): replace the if/elif chain with

```python
        rank = {"seq": 2, "exp": 1, "act": 0}.get(meta_kind(clean_path), -1)
```

and add `from helao.hexagon.domain.naming import meta_kind`. Docstrings: "(``-seq``/``-exp``/``-act``, ``.json`` or legacy ``.yml``)".

`helao/deploy/hte/specifications/week_window.py:53`:

```python
            seqymls = [str(p) for p in meta_glob(os.path.join(folderpath, day), "seq", "*/*")]
```

with `from helao.helpers.meta_io import meta_glob`.

- [ ] **Step 5: Run to verify they pass, plus neighbours**

Run: `PYTHONPATH=$PWD python -m pytest helao/core/tests/test_storage_format.py helao/core/tests/test_run_state.py helao/core/tests/test_run_state_wiring.py helao/core/tests/test_retire.py helao/core/tests/test_process_locator.py helao/hexagon/tests/test_reconcile_interrupted.py helao/deploy/hte/tests/test_week_window_lister.py helao/deploy/hte/tests/test_sync_server_recovery.py harness/tests/test_sim_db_server.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
F="helao/helpers/run_state.py helao/hexagon/app/action_host.py helao/ui/shared/retire.py helao/core/drivers/data/process_locator.py helao/helpers/processors.py helao/deploy/hte/servers/action/sync_server.py helao/deploy/test/servers/action/sim_db_server.py helao/deploy/hte/specifications/week_window.py helao/core/tests/test_storage_format.py helao/hexagon/tests/test_reconcile_interrupted.py helao/deploy/hte/tests/test_week_window_lister.py helao/deploy/hte/tests/test_sync_server_recovery.py"
black $F && pyright $F
git -C /mnt/STORAGE/repos/helao/helao-async add $F
git -C /mnt/STORAGE/repos/helao/helao-async commit -m "feat(discovery): run_state, reconcile, retire, process locator and rank read JSON records"
```

---

### Task 6: SYNC reads JSON records, writes `-prc.json`, uploads pairs under the unchanged S3 names

**Files:**
- Modify: `helao/hexagon/adapters/native/sync_driver.py`
- Modify: `helao/core/hooks/builtin/s3_upload.py` (docstring 1-16, `.hlo` branch 103-151)
- Modify: `helao/hexagon/adapters/native/CLAUDE.md` (first paragraph)
- Test: `helao/core/tests/test_upload_set.py`, `helao/core/tests/test_s3_upload_parquet_failure.py`, `helao/core/tests/test_prc_colocation.py` (209-212, 253, 263), `helao/hexagon/tests/test_native_sync_process_recovery.py` (332, 388, 394), `helao/core/tests/test_sync_write_off.py` (150, 262), `helao/core/tests/test_sync_postfinish_golden.py` (520), `helao/core/tests/test_storage_format.py` (append)

**Interfaces:**
- Consumes: `RECORD_KINDS`, `HEADER_SUFFIX`, `DATA_SUFFIX`, `data_sibling`, `data_stem`, `meta_kind` (Task 1); `read_meta`, `dumps_meta`, `write_meta`, `meta_glob` (Task 2).
- Produces: no new names. `HelaoYml`/`Progress`/`SyncDriver` accept `.json` record paths everywhere they accepted `.yml`; `sync_process` writes `<pidx>__<uuid>__<tech>-prc.json` via `write_meta` (an existing `-prc.yml` for the same stem is rewritten as YAML — the in-flight rule); `Progress.dict["process_groups"]` always has `int` keys.

- [ ] **Step 1: Write the failing tests**

Append to `helao/core/tests/test_upload_set.py`:

```python
from helao.helpers.meta_io import write_meta


def _json_action_tree(tmp_path: Path, files: list) -> Path:
    act_dir = tmp_path / "RUNS" / "2026" / "1023" / "seqdir" / "expdir" / "0__0__SIM__do_thing"
    return write_meta(
        act_dir / "261023.120000000000-act.json",
        {
            "action_name": "do_thing",
            "action_uuid": "11111111-1111-1111-1111-111111111111",
            "action_status": ["finished"],
            "files": files,
        },
    )


def test_json_record_ships_the_jsonl_and_never_the_header(tmp_path: Path):
    act = _json_action_tree(
        tmp_path, [{"file_name": "CA-0.0.0.0__0.jsonl", "file_type": "helao__file"}]
    )
    (act.parent / "CA-0.0.0.0__0.jsonl").write_text('{"a":1}\n', encoding="utf-8")
    (act.parent / "CA-0.0.0.0__0.meta.json").write_text("{}\n", encoding="utf-8")
    yml = HelaoYml(act)
    assert yml.type == "action"
    assert [p.name for p in yml.upload_files] == ["CA-0.0.0.0__0.jsonl"]
    assert yml.warn_unregistered_files() == []


def test_an_orphan_header_is_still_reported(tmp_path: Path):
    act = _json_action_tree(tmp_path, [])
    (act.parent / "CA-0.0.0.0__0.meta.json").write_text("{}\n", encoding="utf-8")
    assert [p.name for p in HelaoYml(act).warn_unregistered_files()] == [
        "CA-0.0.0.0__0.meta.json"
    ]
```

Append to `helao/core/tests/test_s3_upload_parquet_failure.py` (add `from pathlib import Path` to its imports):

```python
@pytest.mark.asyncio
async def test_large_jsonl_converts_to_a_sibling_parquet(tmp_path, monkeypatch):
    """Review Focus 2: ``str(fp).replace(".hlo", ...)`` is a no-op on a .jsonl."""
    calls = []

    def fake(fp, parquet_path, *_a, **_k):
        calls.append((Path(fp), Path(parquet_path)))
        Path(parquet_path).write_bytes(b"PAR1")

    monkeypatch.setattr(s3_upload_mod, "hlo_to_parquet", fake)
    drv = make_sync_driver(tmp_path, native_mod.SyncDriver)
    try:
        act_yml = make_action(make_exp_tree(tmp_path, "RUNS", mk_uuid(1)), 0)
        big = act_yml.parent / "big-0.0.0.0__0.jsonl"
        big.write_text("x", encoding="utf-8")
        os.truncate(big, 1024**3 + 1)
        act_yml.write_text(
            act_yml.read_text(encoding="utf-8")
            + "action_status: [finished]\nfiles:\n- file_name: big-0.0.0.0__0.jsonl\n"
            + "  file_type: helao__file\n",
            encoding="utf-8",
        )
        sent = {}

        async def accept(msg=None, target=None, compress=False, retries=5):
            sent[target] = msg
            return True

        drv.to_s3 = accept
        try:
            await asyncio.wait_for(drv.sync_yml(yml_path=act_yml), timeout=15)
        except RuntimeError:
            pass
        parquet = act_yml.parent / "big-0.0.0.0__0.parquet"
        assert calls == [(big, parquet)]
        assert big.stat().st_size == 1024**3 + 1
        assert sent[f"raw_data/{mk_uuid(0)}/big-0.0.0.0__0.parquet"] == parquet
    finally:
        await teardown_driver(drv)
```

Append to `helao/core/tests/test_storage_format.py`:

```python
from types import SimpleNamespace

import helao.hexagon.adapters.native.sync_driver as sd


def test_progress_from_json_exp_has_int_group_keys(tmp_path):
    """Review Focus 4: JSON object keys are strings; .prg bookkeeping is int."""
    exp = write_meta(
        tmp_path / "RUNS" / "2026" / "1023" / "seq" / "exp" / "261023.120000000000-exp.json",
        {"experiment_uuid": U_EXP, "experiment_name": "e",
         "process_order_groups": {0: [0, 1], 1: [2]}},
    )
    assert sd.Progress(exp).dict["process_groups"] == {0: [0, 1], 1: [2]}
    assert sd.Progress(exp).dict["process_groups"] == {0: [0, 1], 1: [2]}  # re-read from .prg


def test_helao_yml_walks_a_mixed_json_tree(tmp_path):
    seq = tmp_path / "RUNS" / "2026" / "1023" / "120000__s__l"
    s = seq / "261023.120000000000-seq.yml"
    s.parent.mkdir(parents=True)
    s.write_text("sequence_uuid: x\nsequence_status: [finished]\n", encoding="utf-8")
    e = write_meta(seq / "261023.120001__e" / "261023.120001000000-exp.json", {"experiment_status": ["finished"]})
    a = write_meta(e.parent / "0__0__S__a" / "261023.120002000000-act.json", {"action_status": ["finished"]})
    write_meta(e.parent / "0__u__T-prc.json", {"process_uuid": "u"})
    assert sd.HelaoYml(seq).target == s
    assert [c.target for c in sd.HelaoYml(s).children] == [e]
    assert [c.target for c in sd.HelaoYml(e).children] == [a]
    assert sd.HelaoYml(a).parent_yml == e
    assert sd.HelaoYml(e).parent_yml == s
    assert [p.name for p in sd.HelaoYml(e).process_ymls] == ["0__u__T-prc.json"]
    drv = sd.SyncDriver.__new__(sd.SyncDriver)
    drv.helaodirs = SimpleNamespace(save_root=tmp_path / "RUNS")  # type: ignore[assignment]
    assert [Path(p) for p in drv.list_pending()] == [s]
    assert [Path(p) for p in drv.list_pending_exps()] == [e]
    assert [Path(p) for p in drv.list_pending_acts()] == [a]
```

`HelaoYml.children` (sync_driver.py ~505) is the deduplicated union over the state paths, which for a `RUNS` record are all the record itself. `list_pending` globs `<save_root>/*/*/*/*-seq.*` with `save_root` = `RUNS` (`test_runs_layout.py:397` shows the same stub).

Update the writer-side globs in existing tests (these tests run the real `sync_process`, which now writes JSON):

| File:line | Before | After |
|---|---|---|
| `helao/core/tests/test_prc_colocation.py:209` | `exp_yml.parent.glob("*-prc.yml")` | `exp_yml.parent.glob("*-prc.json")` |
| `helao/core/tests/test_prc_colocation.py:211-212` | `(tmp_path / "PROCESSES").rglob("*-prc.yml")` | `(tmp_path / "PROCESSES").rglob("*-prc.*")` |
| `helao/core/tests/test_prc_colocation.py:253, 263` | `exp_yml.parent.glob("*-prc.yml")` | `exp_yml.parent.glob("*-prc.json")` |
| `helao/hexagon/tests/test_native_sync_process_recovery.py:332, 388, 394` | `exp_yml.parent.glob("0__*-prc.yml")` | `exp_yml.parent.glob("0__*-prc.json")` |
| `helao/core/tests/test_sync_write_off.py:150, 262` | `exp_yml.parent.glob("*-prc.yml")` | `exp_yml.parent.glob("*-prc.json")` |
| `helao/core/tests/test_sync_postfinish_golden.py:520` | `assert list(exp_yml.parent.glob("*-prc.yml")), "no local -prc.yml written"` | `assert list(exp_yml.parent.glob("*-prc.json")), "no local -prc.json written"` |

In `test_sync_write_off.py` the loops after lines 150/262 parse each file; if they use `yml_load(p, ...)`, switch to `read_meta(p)` (`from helao.helpers.meta_io import read_meta`). Line 291's hand-written legacy `-prc.yml` stays: the in-flight rule rewrites it in place, which is exactly what line 312 asserts.

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONPATH=$PWD python -m pytest helao/core/tests/test_upload_set.py helao/core/tests/test_s3_upload_parquet_failure.py helao/core/tests/test_storage_format.py helao/core/tests/test_prc_colocation.py -q`
Expected: FAIL (json records invisible to `HelaoYml`; parquet written over the `.jsonl` path; `process_groups` keys are `"0"`; no `-prc.json`).

- [ ] **Step 3: Implement `sync_driver.py`**

Imports (line 74 area):

```python
from helao.helpers.meta_io import dumps_meta, meta_glob, read_meta, write_meta
from helao.helpers.yml_tools import yml_dumps, yml_load
from helao.hexagon.domain.naming import (
    DATA_SUFFIX,
    HEADER_SUFFIX,
    RECORD_KINDS,
    data_sibling,
    meta_kind,
)
```

(`yml_dumps`/`yml_load` stay for the `.prg` sidecar, which is YAML.)

Site edits:

| Line | Before | After |
|---|---|---|
| 211 | `self.meta = yml_load(self.target, fast=True)` | `self.meta = read_meta(self.target)` |
| 239-245 | `possible_ymls = [x for x in list(self.targetdir.glob("*.yml")) if x.stem.endswith("-seq") or x.stem.endswith("-exp") or x.stem.endswith("-act")]` | `possible_ymls = meta_glob(self.targetdir, RECORD_KINDS)` |
| 468-472 | `paths = [p for p in yml_path.parent.glob("*/*.yml") if p.stem.endswith(("-seq", "-exp", "-act"))]` | `paths = meta_glob(yml_path.parent, RECORD_KINDS, "*/*")` |
| 678-682 | `return [x for x in self.targetdir.glob("*-prc.yml") if x.is_file()]` | `return [x for x in meta_glob(self.targetdir, "prc") if x.is_file()]` |
| 702-706 | `found = [p for p in x.parent.parent.glob("*.yml") if p.stem.endswith(("-seq", "-exp", "-act"))]` | `found = meta_glob(x.parent.parent, RECORD_KINDS)` |
| 743-746 (`HelaoYml.write_meta`) | `yml_dumps(meta_dict),` | `dumps_meta(meta_dict, self.target),` |
| 823 | `if path.suffix == ".yml":` | `if path.suffix in (".json", ".yml"):` |
| 828 | `if path.endswith(".yml"):` | `if path.endswith((".json", ".yml")):` |
| 833 | `raise ValueError(f"{path} is not a valid Helao .yml or .prg file")` | `raise ValueError(f"{path} is not a valid Helao record (.json/.yml) or .prg file")` |
| 1087 | `for f in (yml_load(self.yml.target, fast=True).get("files") or [])` | `for f in (read_meta(self.yml.target).get("files") or [])` |
| 1548 | `not yml_path.name.endswith("-exp.yml")` | `meta_kind(yml_path) != "exp"` |
| 1926, 2004 | `if yml_path.name.endswith("-prc.yml"):` | `if meta_kind(yml_path) == "prc":` |
| 2028 | `if not yml_path.name.endswith("-act.yml"):` | `if meta_kind(yml_path) != "act":` |
| 2033 | `lambda: list(yml_path.parent.glob("*/*.yml"))` | `lambda: meta_glob(yml_path.parent, ("exp", "act"), "*/*")` |
| 2756 | `pending = glob(os.path.join(finished_dir, "*", "*", "*", "*-seq.yml"))` | `pending = [str(p) for p in meta_glob(finished_dir, "seq", "*/*/*/*")]` |
| 2775 | `pending = glob(os.path.join(finished_dir, "*", "*", "*", "*", "*", "*-act.yml"))` | `pending = [str(p) for p in meta_glob(finished_dir, "act", "*/*/*/*/*/*")]` |
| 2794 | `pending = glob(os.path.join(finished_dir, "*", "*", "*", "*", "*-exp.yml"))` | `pending = [str(p) for p in meta_glob(finished_dir, "exp", "*/*/*/*/*")]` |

`quarantined` (1663-1669): replace the `suffix = {...}` line and the `ymls = ...` line with

```python
        kind_abbr = {"action": "act", "experiment": "exp", "sequence": "seq"}
        ...
            ymls = meta_glob(rec_dir, kind_abbr.get(rec["kind"], RECORD_KINDS))
```

Progress init (868): replace `process_groups = self.yml.meta.get("process_order_groups", {})` with

```python
                # JSON object keys are strings; the .prg bookkeeping, action
                # orders and written-off groups are all compared as ints.
                process_groups = {
                    int(k): v
                    for k, v in (self.yml.meta.get("process_order_groups") or {}).items()
                }
```

This is the one place raw record keys enter the `.prg`; `process_metas`/`process_s3`/the `sorted(process_metas.items())` in `s3_upload` all derive from it, so no `int()` is needed at those later sites (spec §1 names them; the cast is applied at their common source instead).

`warn_unregistered_files` (625-637): after `if p.suffix in (".prg", ".lock"): continue`, add

```python
            # The record's own metadata, and a data header whose .jsonl partner
            # is registered (the header travels by stem, spec §4).
            if meta_kind(p) is not None:
                continue
            rel = p.relative_to(self.targetdir).as_posix()
            if rel.endswith(HEADER_SUFFIX) and data_sibling(rel, DATA_SUFFIX) in named:
                continue
```

and change the next check to use `rel` (`if rel in named: continue`).

`sync_process` (2632-2640): replace from `save_yml_path = os.path.join(` through `f.write(yml_dumps(model))` with

```python
                save_dir = str(exp_prog.yml.target.parent)
                write_meta(
                    os.path.join(
                        save_dir,
                        f"{pidx}__{uuid_key}__{meta['technique_name']}-prc.json",
                    ),
                    model,
                )
```

(`write_meta` creates the directory, writes atomically, and rewrites an existing `-prc.yml` of the same stem as YAML.) Update docstrings that name `-prc.yml` / `*-{seq,exp,act}.yml` in the edited functions to say "record (``.json`` or legacy ``.yml``)". `glob` stays imported (used by cleanup helpers).

- [ ] **Step 4: Implement `s3_upload.py`**

Add `from helao.hexagon.domain.naming import data_stem`. Replace the branch head and the two key/path lines:

```python
                    if fp.suffix in (".hlo", ".jsonl"):
                        if fp.stat().st_size < 1024**3:  # 1GB
                            file_s3_key = (
                                f"raw_data/{meta['action_uuid']}/{data_stem(fp)}.hlo.json"
                            )
```

```python
                            file_s3_key = (
                                f"raw_data/{meta['action_uuid']}/{data_stem(fp)}.parquet"
                            )
                            try:
                                parquet_path = str(
                                    fp.with_name(data_stem(fp) + ".parquet")
                                )
```

`read_hlo(fp)` already reads the pair's header from `X.meta.json`. Docstring line 4: "(``.hlo``/``.jsonl`` -> ``X.hlo.json`` under 1 GB, parquet above; anything else as-is)"; line 8: "``sync_process`` writes the local ``-prc.json``". The `files[]` rename block below is unchanged: `fp.name` (`X.jsonl`) differs from the key basename (`X.hlo.json`), so the entry is renamed to `X.hlo.json` / `helao__json_file` exactly as for `.hlo`.

- [ ] **Step 5: Correct `helao/hexagon/adapters/native/CLAUDE.md`**

Replace the first paragraph's first two sentences with:

```
**What the syncer uploads to `raw_data/` is the record's own `files` list, not a directory glob.** `HelaoYml.upload_files` resolves each `Action.files[].file_name` against the action directory and ships the ones on disk; nosync entries are skipped. A data pair `X.meta.json` + `X.jsonl` registers only the `.jsonl`; the header travels by stem and is folded into the `raw_data/<uuid>/X.hlo.json` payload. `warn_unregistered_files` still rglobs the directory, but only to *report* unregistered files (it skips the record's own `-act.json`/`.yml` and a header whose `.jsonl` is registered).
```

Keep the two bullets that follow; in the first bullet replace "A batch conversion running while SYNC globs the same directory therefore hands the uploader a name the rename has already consumed." with "A glob landing mid-write (the reconciliation warning, `_register_present_files`) would otherwise see a name the rename has already consumed."

- [ ] **Step 6: Run to verify they pass, plus the SYNC suites**

Run: `PYTHONPATH=$PWD python -m pytest helao/core/tests/test_upload_set.py helao/core/tests/test_s3_upload_parquet_failure.py helao/core/tests/test_storage_format.py helao/core/tests/test_prc_colocation.py helao/hexagon/tests/test_native_sync_process_recovery.py helao/core/tests/test_sync_write_off.py helao/core/tests/test_sync_postfinish_golden.py helao/core/tests/test_sync_quarantine.py helao/core/tests/test_sync_incomplete_process.py helao/core/tests/test_sync_hlo_rename_warning.py helao/core/tests/test_runs_layout.py helao/hexagon/tests/test_native_sync_driver.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
F="helao/hexagon/adapters/native/sync_driver.py helao/core/hooks/builtin/s3_upload.py helao/hexagon/adapters/native/CLAUDE.md helao/core/tests/test_upload_set.py helao/core/tests/test_s3_upload_parquet_failure.py helao/core/tests/test_storage_format.py helao/core/tests/test_prc_colocation.py helao/hexagon/tests/test_native_sync_process_recovery.py helao/core/tests/test_sync_write_off.py helao/core/tests/test_sync_postfinish_golden.py"
black $(echo $F | tr ' ' '\n' | grep '\.py$') && pyright helao/hexagon/adapters/native/sync_driver.py helao/core/hooks/builtin/s3_upload.py
git -C /mnt/STORAGE/repos/helao/helao-async add $F
git -C /mnt/STORAGE/repos/helao/helao-async commit -m "feat(sync): JSON records, -prc.json, .jsonl uploads under unchanged S3 names"
```

---

### Task 7: Harness classifies and compares the new suffixes

**Files:**
- Modify: `harness/classify.py` (`RE_META_YML` 41, `normalize_name` 93-95, `classify_file` 137-148)
- Modify: `harness/yaml_pass.py` (`load_yml_plain` 84-86, `normalize_meta` `file_name` handling)
- Modify: `harness/treepass.py` (`_meta_doc` 219-222)
- Modify: `harness/capture.py` (283-284, 292-299)
- Modify: `harness/s3_pass.py` (164, 261-263, 362-363)
- Modify: `harness/hlo_pass.py` — no code change (it calls `read_hlo`, which now dispatches)
- Test: `harness/tests/test_classify.py`, `harness/tests/test_hlo_pass.py`, `harness/tests/test_yaml_pass.py`

**Interfaces:**
- Consumes: `read_meta` (Task 2), `read_hlo` (Task 3), `data_stem` (Task 1).
- Produces: a new-format tree normalizes onto the legacy member names, so a legacy golden and a new capture pair file-by-file: `TS-act.json` -> `TS-act.yml` key, `X.jsonl` -> `X.hlo` key (row `HLO`), `X.meta.json` -> `IGNORE` (its content is compared through the `.jsonl`'s `read_hlo` meta), `-prc.json` -> `-prc.yml` key, `<uuid>-ana.json` -> `<uuid>.yml` key (row `ANALYSIS`); in record contents, `file_name` `X.jsonl` normalizes to `X.hlo`.

`harness/mutate.py` and `harness/control_negative.py` are left as they are: they mutate legacy goldens and synthetic legacy trees only.

- [ ] **Step 1: Write the failing tests** — append to `harness/tests/test_classify.py`:

```python
def test_new_suffixes_normalize_onto_legacy_names():
    assert normalize_name("250716.131421123456-act.json") == "TS-act.yml"
    assert normalize_name("250716.131415123456-seq.json") == "TS-seq.yml"
    assert normalize_name("WsSim-0.0.0.0__0.jsonl") == "WsSim-0.0.0.0__0.hlo"
    assert normalize_name("0__u__CV-prc.json") == "0__u__CV-prc.yml"
    assert normalize_name("u-ana.json") == "u.yml"
    assert normalize_name("u_output_xrfs.json") == "u_output_xrfs.json"


def test_classify_new_suffixes():
    assert classify_file("RUNS/a/b-seq.json") is ArtifactRow.SEQ_YML
    assert classify_file("RUNS/a/b-exp.json") is ArtifactRow.EXP_YML
    assert classify_file("RUNS/a/b-act.json") is ArtifactRow.ACT_YML
    assert classify_file("RUNS/a/0__x__t-prc.json") is ArtifactRow.PRC_YML
    assert classify_file("RUNS/a/x.jsonl") is ArtifactRow.HLO
    assert classify_file("RUNS/a/x.meta.json") is ArtifactRow.IGNORE
    assert classify_file("ANALYSES/25.28/0716/x/u-ana.json") is ArtifactRow.ANALYSIS
    assert classify_file("S3_SIM/helao-sim/raw_data/u/x.hlo.json") is ArtifactRow.S3_RECORD
```

Append to `harness/tests/test_hlo_pass.py` (it has a `write_hlo` helper and imports `diff_hlo`):

```python
def test_a_jsonl_pair_matches_its_legacy_twin(tmp_path):
    from helao.helpers.meta_io import dumps_meta

    rows = ['{"epoch_s": 1.0, "series_0": 0.5}', '{"epoch_s": 2.0, "series_0": 0.7}']
    a = tmp_path / "a.hlo"
    write_hlo(a, 111, rows)
    (tmp_path / "b.meta.json").write_text(
        dumps_meta(
            {
                "hlo_version": "2026.10.23",
                "action_name": "WsSim",
                "column_headings": ["epoch_s", "series_0"],
                "epoch_ns": 999,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "b.jsonl").write_text("".join(r + "\n" for r in rows), encoding="utf-8")
    diffs = diff_hlo(
        a, tmp_path / "b.jsonl", "x/a.hlo", UuidMapper(), UuidMapper(), make_manifest({}, {})
    )
    assert diffs == []


def test_a_changed_pair_value_is_caught(tmp_path):
    a = tmp_path / "a.hlo"
    write_hlo(a, 1, ['{"epoch_s": 1.0, "series_0": 0.5}'])
    (tmp_path / "b.jsonl").write_text('{"epoch_s": 1.0, "series_0": 0.6}\n', encoding="utf-8")
    from helao.helpers.meta_io import dumps_meta

    (tmp_path / "b.meta.json").write_text(
        dumps_meta({"action_name": "WsSim", "column_headings": ["epoch_s", "series_0"]}),
        encoding="utf-8",
    )
    diffs = diff_hlo(
        a, tmp_path / "b.jsonl", "x/a.hlo", UuidMapper(), UuidMapper(), make_manifest({}, {})
    )
    assert diffs  # the comparison is not vacuous across formats
```

Append to `harness/tests/test_yaml_pass.py`:

```python
def test_load_yml_plain_reads_json_and_names_normalize(tmp_path):
    from harness.uuidmap import UuidMapper
    from harness.yaml_pass import load_yml_plain, normalize_meta
    from helao.helpers.meta_io import write_meta

    y = tmp_path / "1-act.yml"
    y.write_text("files:\n  - file_name: X__0.hlo\n", encoding="utf-8")
    j = write_meta(tmp_path / "2-act.json", {"files": [{"file_name": "X__0.jsonl"}]})
    assert normalize_meta(load_yml_plain(y), UuidMapper()) == normalize_meta(
        load_yml_plain(j), UuidMapper()
    )
```

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONPATH=$PWD python -m pytest harness/tests/test_classify.py harness/tests/test_hlo_pass.py harness/tests/test_yaml_pass.py -q`
Expected: FAIL (`.json` records classify as `AUX_FILE`; `.jsonl` passes through unnormalized).

- [ ] **Step 3: Implement**

`harness/classify.py`:

```python
RE_META_YML = re.compile(r"^\d{6}\.\d{12}-(seq|exp|act)\.(?:yml|json)$")  # %y%m%d.%H%M%S%f
```

In `normalize_name`, before `m = RE_META_YML.match(part)` add nothing; after the `RE_META_YML` block (which now also maps `.json` records to `TS-<kind>.yml`) and before `return part`, add:

```python
    # New-format names collapse onto their legacy twins so a legacy golden and
    # a JSON-era capture pair member-by-member (JSON storage spec §3).
    if part.endswith(".jsonl"):
        return part[: -len(".jsonl")] + ".hlo"
    if part.endswith("-prc.json"):
        return part[: -len(".json")] + ".yml"
    if part.endswith("-ana.json"):
        return part[: -len("-ana.json")] + ".yml"
    return part
```

(The final `return part` replaces the existing one.) In `classify_file` change the four record tests to tuples, and add the pair rows before `.hlo`:

```python
    if name.endswith(("-seq.yml", "-seq.json")):
        return ArtifactRow.SEQ_YML
    if name.endswith(("-exp.yml", "-exp.json")):
        return ArtifactRow.EXP_YML
    if name.endswith(("-act.yml", "-act.json")):
        return ArtifactRow.ACT_YML
    if name.endswith(("-prc.yml", "-prc.json")):
        return ArtifactRow.PRC_YML
    if name.endswith(".prg"):
        return ArtifactRow.PRG
    if name.endswith(".meta.json"):
        # The header half of a pair; compared through the .jsonl's read_hlo meta.
        return ArtifactRow.IGNORE
    if name.endswith((".hlo", ".jsonl")):
        return ArtifactRow.HLO
```

Update the `HLO` enum comment to "streamed AND one-shot data (.hlo, or the .jsonl of a pair)".

`harness/yaml_pass.py`: replace `load_yml_plain`'s body with `return to_plain(read_meta(Path(path)))` and the import `from helao.helpers.yml_tools import yml_load` with `from helao.helpers.meta_io import read_meta` (docstring: "Load a record (``.json`` or ``.yml``) into plain Python containers."). `normalize_meta` already applies `normalize_name` to `file_name` values (`FILENAME_KEYS`), which now maps `X.jsonl` -> `X.hlo`; no further change.

`harness/treepass.py` `_meta_doc`: no change needed (`load_yml_plain` and `read_hlo` both dispatch). `harness/parity.py` / `harness/normalize.py`: no change (they dispatch through `load_yml_plain` / `diff_hlo`).

`harness/capture.py` lines 283-284 and 292-299:

```python
        return next(active.rglob("*.yml"), None) is None
    acts = [p for tree in ("RUNS", "DIAG") for p in meta_glob(root / tree, "act", "**/*")]
```

```python
def _act_is_terminal(act_yml: Path) -> bool:
    """Whether one ``-act`` record (``.json`` or ``.yml``) records a terminal ``action_status``."""
    try:
        from helao.helpers.meta_io import read_meta

        status = read_meta(act_yml).get("action_status")
    except Exception:
        return False
```

with `from helao.helpers.meta_io import meta_glob` at module top. (The legacy `RUNS_ACTIVE` probe at 283 stays: it only runs against legacy trees.) `WSSIM_MASKED` / `WSSIM_TOLERANCE` need no new keys: they are fnmatched against the *normalized* name, which maps `X.jsonl` to `X.hlo`.

`harness/s3_pass.py`:
- line 164: `if orig not in disk_files:` -> `if orig not in disk_files and orig[: -len(".hlo")] + ".jsonl" not in disk_files:`
- lines 261-263:

```python
    for yml in [*ana_root.rglob("*.yml"), *ana_root.rglob("*-ana.json")]:
        on_disk[yml.name.removesuffix("-ana.json").removesuffix(".yml").lower()] = yml
    local_outputs = {
        p.stem.lower(): p for p in ana_root.rglob("*.json") if not p.name.endswith("-ana.json")
    }
```

- lines 362-363: `for act_yml in meta_glob(Path(root), "act", "**/*"):` with `from helao.helpers.meta_io import meta_glob`.

- [ ] **Step 4: Run to verify they pass, plus the whole harness suite**

Run: `PYTHONPATH=$PWD python -m pytest harness/tests -q`
Expected: PASS (all harness tests; the new-name mapping must not change any legacy key, which the existing `test_classify`/`test_treepass` pins).

- [ ] **Step 5: Commit**

```bash
F="harness/classify.py harness/yaml_pass.py harness/capture.py harness/s3_pass.py harness/tests/test_classify.py harness/tests/test_hlo_pass.py harness/tests/test_yaml_pass.py"
black $F && pyright harness/classify.py harness/yaml_pass.py harness/capture.py harness/s3_pass.py
git -C /mnt/STORAGE/repos/helao/helao-async add $F
git -C /mnt/STORAGE/repos/helao/helao-async commit -m "feat(harness): classify and normalize JSON-era names onto legacy goldens"
```

---

### Task 8: hte live paths

**Files:**
- Modify: `helao/deploy/hte/processors/hlo_to_csv.py` (36-43), `helao/deploy/hte/processors/spec_melt_wls.py` (44), `helao/deploy/hte/processors/hispec_process_all.py` (67)
- Modify: `helao/deploy/hte/processors/libs/hispec_class_2.py` (787-864), `helao/deploy/hte/processors/libs/hispec_calibrate_downsample_parquet.py` (28-51)
- Modify: `helao/deploy/hte/drivers/data/calc_driver.py` (`gather_seq_data` 161-182, `gather_seq_exps` 204, `get_seq_dict` 214)
- Create: `helao/deploy/hte/tests/test_json_storage_live_paths.py`

`analyses/echeuvis_stability.py` and `analyses/uvis_bkgsubnorm.py` only call the loader's `.hlo` / `hlo_file_tup` accessors, which Task 4 made dual-format (`model_base.hlo_file_tup_type` accepts `.jsonl`); they need no edit. Their coverage is `test_local_loader_indexes_and_reads_a_json_tree` (Task 4).

**Interfaces:**
- Consumes: `data_sibling`, `meta_kind` (Task 1); `read_hlo`, `hlo_to_parquet` (Task 3); `FileMapper.read_hlo`/`read_yml` (Task 4).

- [ ] **Step 1: Write the failing tests** — create `helao/deploy/hte/tests/test_json_storage_live_paths.py`:

```python
"""hte live paths on JSON-format records (JSON storage spec §3)."""

import os
from types import SimpleNamespace

from helao.core.models.file import FileInfo
from helao.deploy.hte.drivers.data.calc_driver import Calc
from helao.deploy.hte.processors import hlo_to_csv, spec_melt_wls
from helao.helpers.meta_io import dumps_meta, write_meta
from helao.helpers.to_json import hlo_json_dumps


def _pair(d, stem, header, rows):
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{stem}.meta.json").write_text(dumps_meta(header), encoding="utf-8")
    (d / f"{stem}.jsonl").write_text(
        "".join(hlo_json_dumps(r) + "\n" for r in rows), encoding="utf-8"
    )


def _pp(module, tmp_path, file_info):
    pp = object.__new__(module.PostProcess)
    pp.files = [file_info]
    pp.output_dir = str(tmp_path)
    pp.action = SimpleNamespace(action_params={})
    return pp


def test_hlo_to_csv_converts_a_jsonl(tmp_path):
    _pair(tmp_path, "CA-0.0.0.0__0", {"column_headings": ["t_s"]}, [{"t_s": 0.0}, {"t_s": 1.0}])
    f = FileInfo(file_type="pstat_helao__file", file_name="CA-0.0.0.0__0.jsonl")
    out = _pp(hlo_to_csv, tmp_path, f).process()
    assert [x.file_name for x in out] == ["CA-0.0.0.0__0.csv", "CA-0.0.0.0__0.jsonl"]
    assert (tmp_path / "CA-0.0.0.0__0.csv").read_text(encoding="utf-8").splitlines() == [
        "t_s", "0.0", "1.0",
    ]


def test_spec_melt_writes_a_sibling_parquet_for_a_jsonl(tmp_path):
    row = {"epoch_s": 0.0, "error_code": 0, "peak_intensity": 1.0, "ch_0": 1.0, "ch_1": 2.0}
    _pair(tmp_path, "S-0.0.0.0__0", {"optional": {"wl": [400.0, 500.0]}}, [row, {**row, "epoch_s": 1.0}])
    f = FileInfo(file_type="spec_r_helao__file", file_name="S-0.0.0.0__0.jsonl")
    _pp(spec_melt_wls, tmp_path, f).process()
    assert (tmp_path / "S-0.0.0.0__0.parquet").exists()
    assert (tmp_path / "S-0.0.0.0__0.jsonl").exists()


def test_gather_seq_data_reads_json_records_and_pairs(tmp_path):
    seq = tmp_path / "RUNS" / "2026" / "1023" / "120000__s__l"
    exp = seq / "261023.120001__e"
    act = exp / "0__0__SPEC__acquire_spec"
    write_meta(seq / "261023.120000000000-seq.json", {"sequence_name": "s"})
    write_meta(exp / "261023.120001000000-exp.json", {"experiment_name": "e"})
    # A colocated process record must not be taken for the experiment record.
    write_meta(exp / "0__u__T-prc.json", {"process_uuid": "u"})
    write_meta(act / "261023.120002000000-act.json", {"action_name": "acquire_spec"})
    _pair(act, "S-0.0.0.0__0", {"optional": {"wl": [1.0]}}, [{"ch_0": 1.0}])
    calc = Calc(config={})
    (entry,) = calc.gather_seq_data(str(seq), "acquire_spec").values()
    assert entry["meta"] == {"optional": {"wl": [1.0]}}
    assert dict(entry["data"]) == {"ch_0": [1.0]}
    assert entry["actd"]["action_name"] == "acquire_spec"
    assert entry["expd"]["experiment_name"] == "e"
    assert list(calc.gather_seq_exps(str(seq), "*").values()) == [{"experiment_name": "e"}]
    assert calc.get_seq_dict(str(seq)) == {"sequence_name": "s"}
```

Before writing `test_hlo_to_csv_converts_a_jsonl`'s `out` assertion, read `hlo_to_csv.process` (lines 26-62): it appends the csv `FileInfo` then the original, which is the order asserted.

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONPATH=$PWD python -m pytest helao/deploy/hte/tests/test_json_storage_live_paths.py -q`
Expected: FAIL (`hlo_to_csv` skips `.jsonl`; `spec_melt_wls` writes the parquet to `S-0.0.0.0__0.jsonl`; `gather_seq_data` finds no `.hlo`/`.yml`).

- [ ] **Step 3: Implement**

`hlo_to_csv.py` (36-43): the condition becomes `and act_file.file_name.endswith((".hlo", ".jsonl")):` and `new_file_path = file_path.replace(".hlo", ".csv")` becomes `new_file_path = data_sibling(file_path, ".csv")`; docstrings "``.hlo``/``.jsonl`` data file". Import `from helao.hexagon.domain.naming import data_sibling`.

`spec_melt_wls.py:44`: `new_file_path = file_path.replace(".hlo", ".parquet")` -> `new_file_path = data_sibling(file_path, ".parquet")` (same import).

`hispec_process_all.py:67`: same replacement (same import).

`libs/hispec_class_2.py`: delete the local `yml_load` (787-810) and `read_hlo` (813-864) and add `from helao.helpers.hlo_data import read_hlo` to the imports; `read_CV_hlo` keeps calling `read_hlo(path, keep_keys=headers)` and now accepts a pair. If `ruamel.yaml`, `defaultdict` or `Union` become unused, remove those imports (`grep -n 'ruamel\|defaultdict\|Union' helao/deploy/hte/processors/libs/hispec_class_2.py`).

`libs/hispec_calibrate_downsample_parquet.py`: delete the uncalled local `yml_load` (28-51); it already imports `read_hlo` from `helao.helpers.hlo_data`. Remove `import ruamel.yaml` / `Union` if now unused (same grep).

`drivers/data/calc_driver.py` (add `from helao.hexagon.domain.naming import meta_kind`):

| Line | Before | After |
|---|---|---|
| 161 | `hlos = sorted([x for x in paths if x.endswith(".hlo")])` | `hlos = sorted([x for x in paths if x.endswith((".hlo", ".jsonl"))])` |
| 162 | `ymls = sorted([x for x in paths if x.endswith(".yml")])` | `ymls = sorted([x for x in paths if meta_kind(x) == "act"])` |
| 180 | `and x.endswith(".yml")` | `and meta_kind(x) == "exp"` |
| 204 | `ymls = sorted([x for x in paths if x.endswith("exp.yml")])` | `ymls = sorted([x for x in paths if meta_kind(x) == "exp"])` |
| 214 | `ymls = [x for x in FM.relstrs if x.endswith("seq.yml")]` | `ymls = [x for x in FM.relstrs if meta_kind(x) == "seq"]` |

(Line 180 also fixes a latent pick of a colocated `-prc.yml`, which sorts ahead of the `-exp.yml`.)

- [ ] **Step 4: Run to verify they pass, plus the hte suites that touch these files**

Run: `PYTHONPATH=$PWD python -m pytest helao/deploy/hte/tests/test_json_storage_live_paths.py helao/deploy/hte/tests/test_low_w3_hte_fixes.py helao/deploy/hte/tests/test_calc_uvis_trapezoid.py helao/deploy/hte/tests/test_calc_uvis_dr_only.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
F="helao/deploy/hte/processors/hlo_to_csv.py helao/deploy/hte/processors/spec_melt_wls.py helao/deploy/hte/processors/hispec_process_all.py helao/deploy/hte/processors/libs/hispec_class_2.py helao/deploy/hte/processors/libs/hispec_calibrate_downsample_parquet.py helao/deploy/hte/drivers/data/calc_driver.py helao/deploy/hte/tests/test_json_storage_live_paths.py"
black $F && pyright $F
git -C /mnt/STORAGE/repos/helao/helao-async add $F
git -C /mnt/STORAGE/repos/helao/helao-async commit -m "feat(hte): live processors and calc driver read JSON records and .jsonl pairs"
```

---

### Task 9: Deployment-C live paths (nested repo)

All paths are relative to `helao/deploy/<Deployment-C>/`; module paths are `helao.deploy.<Deployment-C>.…` (substitute the directory name from the task prompt). Commit inside that repo with `git -C helao/deploy/<Deployment-C>`.

**Files:**
- Modify: `drivers/data/analyses/xrfs_local.py` (`find_quant_file` 211)
- Modify: `scripts/common/session.py` (`get_action_data_local` 525-537)
- Modify: `scripts/common/batch_converter.py` (`remove_stale_prgs` 383-387, `convert` 1342-1346)
- Modify: `scripts/common/sequence_identity.py` (`assert_no_foreign_sequence` 195-200)
- Modify: `scripts/common/processing_recovery.py` (`_sequence_index` 738-746, `_uuids_in` 815-830, `_child_entities` 856-860)
- Modify: `scripts/ecms_ms/calibration.py` (`_calibration_wait` 161-164, `_scan_calibration_record` 204-205)
- Modify (writer names): `scripts/ecms_ms/converters.py` (345, 406), `scripts/bruker/converters.py` (633, 645), `scripts/bruker_gadds/converters.py` (1045, 1048)
- Test: `drivers/data/analyses/tests/test_xrfs_local_offline.py`, `tests/test_session_local_reader.py`, `scripts/tests/test_sequence_identity.py`, `scripts/common/tests/test_processing_recovery.py`, `scripts/ecms_ms/tests/test_calibration.py`, `scripts/ecms_ms/tests/test_ms_archive.py` (171), `scripts/bruker_gadds/tests/test_gadds_converter_offline.py` (159-162, 230-231), plus a new test for `remove_stale_prgs` in `scripts/common/tests/test_processing_recovery.py`.

Left legacy-only (one-off backfill, spec "Out of scope"): `scripts/ecms_ms/{inject,backlog,from_s3,convert_backlog,slicing}.py`, `scripts/edax/{prune_process_sets,rebuild_journal_zips,retire_duplicate_records,reconvert_duplicates}.py`. `scripts/xafs/converters.py:452-466` hardcodes `xafs_normal-…__0.hlo.json`: that is the S3 name, which `data_stem(X.jsonl) + ".hlo.json"` keeps identical, so it needs no change.

**Interfaces:**
- Consumes: `meta_kind`, `DATA_SUFFIX` (Task 1); `read_meta`, `meta_glob`, `write_meta`, `dumps_meta` (Task 2); `read_hlo_via` (Task 3); `top_level_pair` (Task 5).

- [ ] **Step 1: Write the failing tests** (use each test module's existing imports; add the ones shown)

`drivers/data/analyses/tests/test_xrfs_local_offline.py`:

```python
def test_find_quant_file_accepts_a_jsonl():
    from types import SimpleNamespace

    act = SimpleNamespace(
        json={"files": [{"file_name": "quant.jsonl", "file_type": "xrfs_quant_helao__file"}]}
    )
    assert X.find_quant_file(act) == "quant.jsonl"
```

`tests/test_session_local_reader.py`:

```python
def test_reads_a_jsonl_pair_from_a_directory(tmp_path):
    act = tmp_path / ACTION_DIR
    act.mkdir(parents=True)
    (act / "data.meta.json").write_text('{"a": 1}\n', encoding="utf-8")
    (act / "data.jsonl").write_text('{"x": 1}\n{"x": [2, 3]}\n', encoding="utf-8")
    df = get_action_data_local(ACTION_DIR, "data.jsonl", str(tmp_path))
    assert list(df["x"]) == [1, 2, 3]
```

`scripts/tests/test_sequence_identity.py` (it already imports `assert_no_foreign_sequence` and `SequenceCollisionError`; add `import pytest` if absent):

```python
def test_a_json_sequence_of_another_uuid_is_a_collision(tmp_path):
    from helao.helpers.meta_io import write_meta

    write_meta(tmp_path / "seqdir" / "261023.120000000000-seq.json", {"sequence_uuid": "other"})
    with pytest.raises(SequenceCollisionError):
        assert_no_foreign_sequence(tmp_path, "seqdir", "mine")
```

`scripts/common/tests/test_processing_recovery.py`:

```python
def test_uuids_in_reads_a_json_record(tmp_path):
    from helao.helpers.meta_io import write_meta

    p = write_meta(
        tmp_path / "1-act.json",
        {"action_uuid": "a", "process_uuid": "p", "action_params": {"experiment_uuid": "nested"}},
    )
    assert ProcessingRecovery._uuids_in(str(p)) == {"action_uuid": "a", "process_uuid": "p"}


def test_remove_stale_prgs_keeps_a_prg_beside_its_json_record(tmp_path):
    import os
    import time

    from helao.helpers.meta_io import write_meta

    rec = write_meta(tmp_path / "1-seq.json", {"a": 1})
    prg = tmp_path / "1-seq.prg"
    prg.write_text("s3: false\n", encoding="utf-8")
    later = time.time() + 5
    os.utime(prg, (later, later))
    assert remove_stale_prgs(tmp_path) == []
    assert prg.exists()
    os.utime(rec, (later + 5, later + 5))
    assert remove_stale_prgs(tmp_path) == [str(prg)]
```

Import `ProcessingRecovery` and `remove_stale_prgs` from `helao.deploy.<Deployment-C>.scripts.common.processing_recovery` / `.batch_converter` the way that test module already imports its subjects.

`scripts/ecms_ms/tests/test_calibration.py`:

```python
def test_calibration_wait_reads_json_actions():
    from helao.helpers.meta_io import dumps_meta

    members = {
        "e/0__0__X__wait/1-act.json": dumps_meta(
            {
                "action_order": 0,
                "action_name": cal.WAIT_ACTION_NAME,
                "action_params": {"waittime": 5},
                "action_timestamp": "2026-01-01 00:00:00.000000",
            }
        ).encode("utf-8"),
    }
    assert cal._calibration_wait(members.__getitem__, list(members), "e") == (
        "2026-01-01 00:00:00.000000",
        5.0,
    )
```

(`cal` = the calibration module, imported the way the test module already imports it.)

Writer-name tests: `scripts/ecms_ms/tests/test_ms_archive.py:171` `"ms_recording.hlo"` -> `"ms_recording.jsonl"`; `scripts/bruker_gadds/tests/test_gadds_converter_offline.py:159-162` `rglob("*.hlo")` -> `rglob("*.jsonl")` and `{"xy_original.hlo", "xy_bkgsub.hlo"}` -> `{"xy_original.jsonl", "xy_bkgsub.jsonl"}`, lines 230-231 `.hlo` -> `.jsonl`; update the docstring "One ``.hlo`` per ``.xy``" to "One ``.jsonl`` per ``.xy``".

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONPATH=$PWD python -m pytest helao/deploy/<Deployment-C>/drivers/data/analyses/tests/test_xrfs_local_offline.py helao/deploy/<Deployment-C>/tests/test_session_local_reader.py helao/deploy/<Deployment-C>/scripts/tests/test_sequence_identity.py helao/deploy/<Deployment-C>/scripts/common/tests/test_processing_recovery.py helao/deploy/<Deployment-C>/scripts/ecms_ms/tests/test_calibration.py helao/deploy/<Deployment-C>/scripts/ecms_ms/tests/test_ms_archive.py helao/deploy/<Deployment-C>/scripts/bruker_gadds/tests/test_gadds_converter_offline.py -q`
Expected: FAIL on each new test and on the renamed writer outputs.

- [ ] **Step 3: Implement**

`drivers/data/analyses/xrfs_local.py:211`: `and str(d.get("file_name", "")).endswith(".hlo")` -> `and str(d.get("file_name", "")).endswith((".hlo", ".jsonl"))`. (`.hlo.json` still excluded, as `test_find_quant_file_ignores_json_conversion` pins.)

`scripts/common/session.py` — replace the `elif filename.endswith(".hlo"):` branch (525-537) with:

```python
    elif filename.endswith((".hlo", ".jsonl")):

        def _get(name: str) -> bytes:
            return _read_sequence_member(sequence_path, name)

        def _has(name: str) -> bool:
            try:
                _get(name)
            except (FileNotFoundError, KeyError):
                return False
            return True

        _, data = read_hlo_via(_has, _get, target)
        return pd.DataFrame(data)
```

with `from helao.helpers.hlo_data import read_hlo_via`; docstring: "``.hlo`` and ``.jsonl`` (with its ``.meta.json``) are parsed by ``read_hlo_via``". Remove `defaultdict` / `json` imports if now unused.

`scripts/common/batch_converter.py`:

```python
    for prg in Path(seq_dir).rglob("*.prg"):
        rec = next(
            (p for p in (prg.with_suffix(".json"), prg.with_suffix(".yml")) if p.exists()),
            None,
        )
        if rec is None or prg.stat().st_mtime < rec.stat().st_mtime:
            prg.unlink()
            removed.append(str(prg))
```

and in `convert` (1342-1346):

```python
            seq_ymls = [str(p) for p in meta_glob(seq_dir, "seq")]
            if not seq_ymls:
                raise FileNotFoundError(
                    f"no -seq record found under {seq_dir} after conversion"
                )
```

with `from helao.helpers.meta_io import meta_glob`. (The record path goes to `yml_finisher`, whose `/finish_yml` rank accepts `-seq.json` since Task 5.)

`scripts/common/sequence_identity.py` (195-200): `existing = [f for f in sorted(os.listdir(target)) if meta_kind(f) == "seq"]` and `found = str((read_meta(path) or {}).get("sequence_uuid", ""))`; imports `from helao.helpers.meta_io import read_meta`, `from helao.hexagon.domain.naming import meta_kind`; drop `yml_load` if unused.

`scripts/common/processing_recovery.py`:
- `_sequence_index`: `from helao.helpers.meta_io import meta_glob, read_meta` (replacing the local `yml_load` import), `for yml_path in map(str, meta_glob(root, "seq", "*/*/*/*")):` and `meta = read_meta(yml_path) or {}`.
- `_uuids_in`:

```python
        found = {}
        is_json = path.endswith(".json")
        try:
            with open(path, "r", encoding="utf8", errors="replace") as handle:
                for line in handle:
                    key, value = top_level_pair(line.rstrip("\n"), is_json)
                    if key in ProcessingRecovery._UUID_KEYS and value not in (None, "", "None"):
                        found.setdefault(key, value)
                    if len(found) == len(ProcessingRecovery._UUID_KEYS):
                        break
        except OSError:
            return {}
        return found
```

  with `from helao.helpers.run_state import top_level_pair` (docstring: "one run record, ``.json`` or legacy ``.yml``").
- `_child_entities` (856-860):

```python
        for kind, depth, sink in (("act", "*/*/*", actions), ("exp", "*/*", experiments)):
            for yml_path in map(str, meta_glob(seq_dir, kind, depth)):
```

  (`meta_glob` returns sorted paths, which replaces the `sorted(glob(...))`).

`scripts/ecms_ms/calibration.py`: replace `n.endswith("-act.yml")` (162) with `meta_kind(n) == "act"`, `n.endswith("-exp.yml")` (204) with `meta_kind(n) == "exp"`, and both `yaml.safe_load(read(name))` / `yaml.safe_load(read(exp_name))` with `read_meta(read(name), name=name)` / `read_meta(read(exp_name), name=exp_name)`; imports `from helao.helpers.meta_io import read_meta`, `from helao.hexagon.domain.naming import meta_kind`; drop `import yaml` if unused.

Writer names: `scripts/ecms_ms/converters.py` `filename="ms_recording.hlo"` -> `"ms_recording.jsonl"`, `f"ms_calibration_{idx}.hlo"` -> `f"ms_calibration_{idx}.jsonl"`; `scripts/bruker/converters.py` `"xy_original.hlo"` / `"xy_bkgsub.hlo"` -> `.jsonl`; `scripts/bruker_gadds/converters.py` 1045/1048 the same. (Until Task 11 flips `PostHocRunWriter`, a `.jsonl` here still carries the legacy `%%` line; `read_hlo`'s row parser skips it, so these tests pass before and after Task 11.)

- [ ] **Step 4: Run to verify they pass, plus the whole Deployment-C sweep**

Run the Step 2 command (expect PASS), then `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD python run_tests.py --filter <Deployment-C>` and compare its FAIL list with `$D/baseline.fail` (Task 0): no new entries.

- [ ] **Step 5: Commit (inside the nested repo)**

```bash
R=helao/deploy/<Deployment-C>
F="drivers/data/analyses/xrfs_local.py scripts/common/session.py scripts/common/batch_converter.py scripts/common/sequence_identity.py scripts/common/processing_recovery.py scripts/ecms_ms/calibration.py scripts/ecms_ms/converters.py scripts/bruker/converters.py scripts/bruker_gadds/converters.py drivers/data/analyses/tests/test_xrfs_local_offline.py tests/test_session_local_reader.py scripts/tests/test_sequence_identity.py scripts/common/tests/test_processing_recovery.py scripts/ecms_ms/tests/test_calibration.py scripts/ecms_ms/tests/test_ms_archive.py scripts/bruker_gadds/tests/test_gadds_converter_offline.py"
(cd $R && black $F && pyright $F)
git -C $R add $F
git -C $R commit -m "feat: dual-read JSON records and .jsonl pairs on live paths; .jsonl converter names"
```

---

### Task 10: Deployment-A and Deployment-E live paths (two nested repos)

Paths relative to `helao/deploy/<Deployment-A>/` and `helao/deploy/<Deployment-E>/`; commit inside each repo.

**Files:**
- Modify: `<Deployment-A>/drivers/calc_driver.py` (`gather_exp_data` 167-168, 203)
- Test: `<Deployment-A>/tests/test_calc_gather.py`
- Modify: `<Deployment-E>/processors/hispec_scale_reference.py` (215), `<Deployment-E>/processors/hispec2_process_all.py` (161)
- Test: `<Deployment-E>/tests/test_hispec_scale_reference.py` (fixture `bench`, 27-100)

`<Deployment-A>/drivers/ml_driver.py` and `<Deployment-E>/helpers/spectrum_utils.py` read through `LocalLoader` / `HelaoData`, which Task 4 made dual-format; no edit. Their regression coverage is the core loader tests plus the Deployment-E bench below (its processor builds `HelaoData` on the experiment record).

**Interfaces:**
- Consumes: `meta_kind`, `data_sibling` (Task 1); `write_meta` (Task 2); `FileMapper` dual read (Task 4).

- [ ] **Step 1: Write the failing tests**

`<Deployment-A>/tests/test_calc_gather.py` — add after `_tree` (plain asserts, no pytest import, matching the module):

```python
def _json_tree(root: Path) -> Path:
    """The record ``_tree`` writes, in the JSON storage format."""
    from helao.helpers.meta_io import write_meta

    exp = root / "RUNS" / "2026" / "0925" / SEQ_DIR / EXP_DIR
    write_meta(
        exp.parent / "20260925.120000000000-seq.json",
        {
            "file_type": "sequence",
            "sequence_name": "SDC_seq",
            "sequence_label": "lbl",
            "sequence_timestamp": "2026-09-25 12:00:00.000000",
            "sequence_uuid": "00000000-0000-0000-0000-0000000000aa",
            "sequence_params": {"plate_id": 1234},
        },
    )
    write_meta(
        exp / "20260925.120100000000-exp.json",
        {"file_type": "experiment", "experiment_params": {"electrolyte_ph": 13.0}},
    )
    for name in ACTIONS:
        d = exp / name
        write_meta(
            d / f"20260925.12010{name[0]}000000-act.json",
            {
                "file_type": "action",
                "action_name": name.split("__")[-1],
                "action_params": {},
                "action_timestamp": "2026-09-25 12:01:00.000000",
                "action_uuid": "00000000-0000-0000-0000-00000000000" + name[0],
            },
        )
        stem = f"{name.split('__')[-1]}-0"
        (d / f"{stem}.meta.json").write_text(
            '{"hlo_version": "2024.01.01", "column_headings": ["t_s", "Ewe_V"]}\n',
            encoding="utf-8",
        )
        (d / f"{stem}.jsonl").write_text(
            '{"t_s": [0.0, 1.0], "Ewe_V": [0.1, 0.2]}\n', encoding="utf-8"
        )
    return exp


def test_json_tree_gathers_like_the_yml_tree():
    with tempfile.TemporaryDirectory() as td:
        legacy = Calc().gather_exp_data(exp_localdir=str(_tree(Path(td) / "a")))
        new = Calc().gather_exp_data(exp_localdir=str(_json_tree(Path(td) / "b")))
        assert new[0] == legacy[0]
        assert new[1] == legacy[1]

        def key(actions):
            return [(a["action_order"], a["action_name"], dict(a["data"])) for a in actions]

        assert key(new[2]) == key(legacy[2])
```

If the module's `__main__` block runs an explicit list of test names, append `test_json_tree_gathers_like_the_yml_tree` to it.

`<Deployment-E>/tests/test_hispec_scale_reference.py` — run the whole suite on both formats. Replace `HLO_NAME = "ocean.hlo"` with

```python
HLO_NAMES = {"hlo": "ocean.hlo", "jsonl": "ocean.jsonl"}
```

add after `_write_hlo`:

```python
def _write_pair(out_dir, wl, rows):
    """The JSON-era twin of ``_write_hlo``: ``ocean.meta.json`` + ``ocean.jsonl``."""
    header = {
        "hlo_version": "test",
        "action_name": "acquire_spec",
        "column_headings": ["spec_idx", "epoch_s"] + [f"ch_{i:04}" for i in range(len(wl))],
        "optional": {"wl": [float(x) for x in wl]},
    }
    (out_dir / "ocean.meta.json").write_text(json.dumps(header), encoding="utf-8")
    with open(out_dir / "ocean.jsonl", "w", encoding="utf-8") as f:
        for idx, row in enumerate(rows):
            line = {"spec_idx": idx, "epoch_s": 1000.0 + idx}
            line.update({f"ch_{i:04}": float(v) for i, v in enumerate(row)})
            f.write(json.dumps(line) + "\n")
```

and in `bench` change the decorator and the three format-dependent lines:

```python
@pytest.fixture(params=[(r, f) for r in RUN_ROOTS for f in ("hlo", "jsonl")])
def bench(tmp_path, monkeypatch, request):
    """A minimal run tree holding one Ocean action, plus its processor."""
    root_name, fmt = request.param
    save_root = tmp_path / root_name
```

```python
    if fmt == "hlo":
        _write_hlo(out_dir / HLO_NAMES[fmt], OCEAN_WL, spectra)
    else:
        _write_pair(out_dir, OCEAN_WL, spectra)
```

```python
                file_name=HLO_NAMES[fmt],
```

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONPATH=$PWD python -m pytest helao/deploy/<Deployment-A>/tests/test_calc_gather.py helao/deploy/<Deployment-E>/tests/test_hispec_scale_reference.py -q`
Expected: FAIL — Deployment-A `IndexError` (no `-exp.yml`); Deployment-E `jsonl` params fail because the scaled dataset path is `ocean.jsonl` itself.

- [ ] **Step 3: Implement**

`<Deployment-A>/drivers/calc_driver.py` (add `from helao.hexagon.domain.naming import meta_kind`):

| Line | Before | After |
|---|---|---|
| 167 | `action_paths = [x for x in fm.relstrs if x.endswith("-act.yml")]` | `action_paths = [x for x in fm.relstrs if meta_kind(x) == "act"]` |
| 168 | `exp_path = [x for x in fm.relstrs if x.endswith("-exp.yml")][0]` | `exp_path = [x for x in fm.relstrs if meta_kind(x) == "exp"][0]` |
| 203 | `if x.startswith(os.path.dirname(ap)) and x.endswith(".hlo")` | `if x.startswith(os.path.dirname(ap)) and x.endswith((".hlo", ".jsonl"))` |

`<Deployment-E>/processors/hispec_scale_reference.py:215`: `self.output_dir, act_file.file_name.replace(".hlo", "_scaled.parquet")` -> `self.output_dir, data_sibling(act_file.file_name, "_scaled.parquet")`.
`<Deployment-E>/processors/hispec2_process_all.py:161`: `new_file_path = file_path.replace(".hlo", ".parquet")` -> `new_file_path = data_sibling(file_path, ".parquet")`. Both add `from helao.hexagon.domain.naming import data_sibling`.

- [ ] **Step 4: Run to verify they pass, plus both deployments' sweeps**

Run the Step 2 command (expect PASS), then `PYTHONPATH=$PWD python run_tests.py --filter <Deployment-A>` and `--filter <Deployment-E>`; no FAIL entries beyond `$D/baseline.fail`.

- [ ] **Step 5: Commit (inside each nested repo)**

```bash
RA=helao/deploy/<Deployment-A>
(cd $RA && black drivers/calc_driver.py tests/test_calc_gather.py && pyright drivers/calc_driver.py)
git -C $RA add drivers/calc_driver.py tests/test_calc_gather.py
git -C $RA commit -m "feat: calc gather reads JSON records and .jsonl pairs"
RE=helao/deploy/<Deployment-E>
(cd $RE && black processors/hispec_scale_reference.py processors/hispec2_process_all.py tests/test_hispec_scale_reference.py && pyright processors/hispec_scale_reference.py processors/hispec2_process_all.py)
git -C $RE add processors/hispec_scale_reference.py processors/hispec2_process_all.py tests/test_hispec_scale_reference.py
git -C $RE commit -m "fix: derive parquet output names from the data stem, not a .hlo replace"
```

---

### Task 11: Data writers emit `X.meta.json` + `X.jsonl`

**Files:**
- Modify: `helao/hexagon/adapters/native/data_file.py` (`init_datafile` 80-159, `log_data_set_output_file` 194-275, `_resolve_output_path` 277-320 signature, `write_file` 322-356, `write_file_nowait` 358-390, module docstring)
- Modify: `helao/hexagon/adapters/native/data_stream.py` (separator block 358-370, module docstring line 9)
- Modify: `helao/core/models/file.py` (`FileConn` 82-117: drop `added_hlo_separator`; `FileConnParams.hloheader` comment 77)
- Modify: `helao/hexagon/adapters/native/posthoc_writer.py` (`_generated_filename` 287, `write_file` 296-390, module docstring bullets)
- Modify: `helao/hexagon/app/action_host.py` (`_register_present_files` 1495-1512)
- Modify: `helao/deploy/hte/servers/action/gamry_server2.py` (82-89), `helao/deploy/hte/servers/action/calc_server.py` (103)
- Modify: `helao/hexagon/ports/artifact_store.py` (docstring lines 10-15)
- Test: `helao/hexagon/tests/test_native_data_file.py`, `test_native_data_stream.py`, `test_posthoc_writer.py` (data-file tests), `test_native_finalizer.py` (77, 197-206), `test_finish_drain_marker.py` (`_rows` 56-60), `test_enqueue_nowait_marshals_to_loop.py` (`_hlo_rows` 60-65), `test_action_writes_artifacts.py` (152), `helao/deploy/hte/tests/test_gamry_versus_ocv.py` (176-178), `helao/core/tests/test_storage_format.py` (append)

**Interfaces:**
- Consumes: `DATA_SUFFIX`, `HEADER_SUFFIX`, `data_sibling`, `is_nosync_file`, `meta_kind` (Task 1); `write_meta`, `dumps_meta` (Task 2).
- Produces:
  - `init_datafile(...) -> (header, FileInfo)`: for `HloFileGroup.helao_files` `header` is a **dict** (`{}` = no header file); a list becomes `{"text": "\n".join(lines)}`; a str becomes the YAML mapping it spells, else `{"text": str}`. For `aux_files` it is the unchanged YAML/str text. Generated helao names end `__N.jsonl`; `nosync` uses `is_nosync_file`.
  - Stream file: `X__N.meta.json` written atomically (only for a non-empty header), then `X__N.jsonl` opened `w+`; rows only, no `%%`.
  - One-shot helao write (`write_file`, `write_file_nowait`, `PostHocRunWriter.write_file`): header overwritten atomically, body to `.jsonl` (native: appended; post-hoc: atomically replaced, and a stale `.meta.json` is removed when the new write has no header). The body is newline-terminated.
  - `FileConn` has no `added_hlo_separator`.

- [ ] **Step 1: Write the failing tests**

`helao/hexagon/tests/test_native_data_file.py` — replace the assertions of `test_init_datafile_autogen_filename` from `assert (` through `assert "a: 1" in header` with:

```python
    assert (
        file_info.file_name
        == f"{a.action_abbr}-{a.orch_submit_order}.{a.action_order}.{a.action_retry}.{a.action_split}__0.jsonl"
    )
    assert header == {"a": 1}
```

add after `test_init_datafile_empty_header_variants`:

```python
def test_init_datafile_helao_headers_are_always_dicts(tmp_path):
    _, active, _ = _native_active(tmp_path)
    cases = [
        ({}, {}),
        ([], {}),
        (None, {}),
        (["line one", "line two"], {"text": "line one\nline two"}),
        ("mean_ocv: 0.3\n", {"mean_ocv": 0.3}),
        ("free text", {"text": "free text"}),
    ]
    for given, expected in cases:
        header, info = active.init_datafile(
            header=given,
            file_type="t",
            json_data_keys=None,
            file_sample_label=None,
            filename=None,
            file_group=HloFileGroup.helao_files,
        )
        assert header == expected, given
        assert info.file_name.endswith(".jsonl")
```

replace the body of `test_log_data_set_output_file_truncates_stale_bytes` from `fname = ...` to the end with:

```python
    fname = f"{a.action_abbr}-{a.orch_submit_order}.{a.action_order}.{a.action_retry}.{a.action_split}__0.jsonl"
    stale = os.path.join(out_dir, fname)
    open(stale, "w", encoding="utf-8").write("STALE-CRASH-BYTES\n")
    active.file_conn_dict[dflt].params.hloheader.epoch_ns = 1234567890
    await active.log_data_set_output_file(file_conn_key=dflt)
    await active.file_conn_dict[dflt].file.close()
    assert open(stale, encoding="utf-8").read() == ""  # rows only, none yet
    header = read_meta(stale[: -len(".jsonl")] + ".meta.json")
    assert header["epoch_ns"] == 1234567890
    assert active.action.files and active.action.files[-1].file_name == fname


@pytest.mark.asyncio
async def test_one_shot_helao_write_overwrites_the_header_and_appends_rows(tmp_path):
    _, active, _ = _native_active(tmp_path)
    path = await active.write_file(
        output_str='{"a": 1}',
        file_type="x_helao__file",
        filename="one.jsonl",
        file_group=HloFileGroup.helao_files,
        header={"k": 1},
    )
    await active.write_file(
        output_str='{"a": 2}\n',
        file_type="x_helao__file",
        filename="one.jsonl",
        file_group=HloFileGroup.helao_files,
        header={"k": 2},
    )
    assert open(path, encoding="utf-8").read() == '{"a": 1}\n{"a": 2}\n'
    assert read_meta(path[: -len(".jsonl")] + ".meta.json") == {"k": 2}
    nowait = active.write_file_nowait(
        output_str='{"b": 1}',
        file_type="x_helao__file",
        filename="two.jsonl",
        file_group=HloFileGroup.helao_files,
    )
    assert open(nowait, encoding="utf-8").read() == '{"b": 1}\n'
    assert not os.path.exists(nowait[: -len(".jsonl")] + ".meta.json")
```

with `from helao.helpers.meta_io import read_meta` at the top. The two `.csv` tests (`test_write_file_one_shot_layout_and_gate`, `test_write_file_nowait_matches_async_layout`) stay unchanged: `aux_files` keep header + `%%` + body (spec "Out of scope").

`helao/hexagon/tests/test_native_data_stream.py` (78-82): replace

```python
    hlo = [f for f in os.listdir(out_dir) if f.endswith(".hlo")]
    assert len(hlo) == 1
    text = open(os.path.join(out_dir, hlo[0]), encoding="utf-8").read()
    assert text.count("%%\n") == 1  # separator exactly once
    body = text.split("%%\n", 1)[1]
    lines = body.splitlines()
```

with

```python
    data = [f for f in os.listdir(out_dir) if f.endswith(".jsonl")]
    assert len(data) == 1
    text = open(os.path.join(out_dir, data[0]), encoding="utf-8").read()
    assert "%%" not in text  # rows only; the header is the .meta.json
    lines = text.splitlines()
```

`helao/hexagon/tests/test_posthoc_writer.py` (data-file tests; add `from helao.helpers.meta_io import read_meta`):

| Test | Before | After |
|---|---|---|
| `test_write_file_produces_header_separator_body_exactly` (rename to `test_write_file_produces_header_and_rows_exactly`) | `assert _read(out) == "scan_index: 1\nlabel: demo\n%%\n" + payload` | `assert _read(out) == payload + "\n"` and `assert read_meta(out[: -len(".jsonl")] + ".meta.json") == {"scan_index": 1, "label": "demo"}` |
| `test_write_file_without_header_starts_at_the_separator` (rename to `test_write_file_without_header_writes_rows_only`) | `assert _read(out) == '%%\n{"a": 1}'` | `assert _read(out) == '{"a": 1}\n'` and `assert not os.path.exists(out[: -len(".jsonl")] + ".meta.json")` |
| `test_write_file_lands_under_the_actions_output_dir` | `"demo-0.0.0.0__0.hlo"` | `"demo-0.0.0.0__0.jsonl"` |
| `test_filenum_is_honoured_verbatim_in_the_generated_filename` | both `f"demo-0.0.0.0__{filenum}.hlo"` | `f"demo-0.0.0.0__{filenum}.jsonl"` (docstring: ``__2.jsonl``) |
| `test_three_filenums_produce_three_distinct_files` | `assert _read(outs[2]) == '%%\n{"n": 2}'` | `assert _read(outs[2]) == '{"n": 2}\n'` |
| `test_file_group_selects_the_extension` | `assert hlo.endswith("__0.hlo")` | `assert hlo.endswith("__0.jsonl")` |
| `test_write_file_records_a_fileinfo_on_the_action` (311) | `"demo-0.0.0.0__1.hlo"` | `"demo-0.0.0.0__1.jsonl"` |
| `test_probe4_repeat_write_overwrites_instead_of_appending` | `assert _read(first) == '%%\n{"n": 2}'` / `assert _read(first).count("%%") == 1` | `assert _read(first) == '{"n": 2}\n'` / `assert _read(first).count("\n") == 1` |
| `test_probe4_a_leftover_file_from_a_failed_run_is_replaced` | `"demo-0.0.0.0__0.hlo"` (378, 393), `'%%\n{"n": 1}'` (391) | `"demo-0.0.0.0__0.jsonl"`, `'{"n": 1}\n'` |
| `test_probe4_a_partial_run_can_be_reconverted_end_to_end` | `f"demo-0.0.0.0__{filenum}.hlo"`, `f'%%\n{{"attempt": 2, "n": {filenum}}}'`, `body.count("%%") == 1` | `f"demo-0.0.0.0__{filenum}.jsonl"`, `f'{{"attempt": 2, "n": {filenum}}}\n'`, `body.count("\n") == 1` |
| `test_data_files_are_written_atomically` | `["demo-0.0.0.0__0.hlo"]` | `["demo-0.0.0.0__0.jsonl"]` |
| `test_write_act_writes_a_parsable_act_yml_and_returns_its_path` (725 only, the rest is Task 12) | `["demo-0.0.0.0__0.hlo"]` | `["demo-0.0.0.0__0.jsonl"]` |

and add:

```python
def test_a_rewrite_without_header_removes_the_stale_header(run):
    act, writer = run["act"], run["writer"]
    kw = dict(file_type="demo_helao__file", filenum=0, file_group=HloFileGroup.helao_files)
    out = writer.write_file(act, output_str='{"n": 1}', header={"h": 1}, **kw)
    writer.write_file(act, output_str='{"n": 2}', **kw)
    assert not os.path.exists(out[: -len(".jsonl")] + ".meta.json")
    assert _read(out) == '{"n": 2}\n'
```

Reader-side test helpers that glob the streamed file:

| File | Before | After |
|---|---|---|
| `test_native_finalizer.py:77` | `hlo = [f for f in os.listdir(out_dir) if f.endswith(".hlo")]` | `hlo = [f for f in os.listdir(out_dir) if f.endswith(".jsonl")]` |
| `test_native_finalizer.py:197-203` | `if fn.endswith(".hlo"):` … `.read()` / `.split("%%\n", 1)[1]` / `.splitlines()` | `if fn.endswith(".jsonl"):` … `.read()` / `.splitlines()` (delete the `.split(...)` line) |
| `test_finish_drain_marker.py:57-60` | `(path,) = glob.glob(str(tmp_path / "**" / "*.hlo"), recursive=True)` … `text.split("%%\n", 1)[1].splitlines()` | `(path,) = glob.glob(str(tmp_path / "**" / "*.jsonl"), recursive=True)` … `text.splitlines()` |
| `test_enqueue_nowait_marshals_to_loop.py:62-64` | `(hlo,) = sorted(root.rglob("*.hlo"))` / `body = text.split("%%", 1)[1]` | `(hlo,) = sorted(root.rglob("*.jsonl"))` / `body = text` |
| `test_action_writes_artifacts.py:152` | `assert any(n.endswith(".hlo") for n in names)` | `assert any(n.endswith(".jsonl") for n in names)` |
| `helao/deploy/hte/tests/test_gamry_versus_ocv.py:176-178` | `assert written["filename"] == "init_ocv.hlo"` / `assert "mean_ocv: 0.3" in written["header"]` | `assert written["filename"] == "init_ocv.jsonl"` / `assert abs(written["header"]["mean_ocv"] - 0.3) < 1e-9` (rename the test `..._and_writes_jsonl`) |

Append to `helao/core/tests/test_storage_format.py`:

```python
def test_register_present_files_takes_the_jsonl_not_its_header(tmp_path):
    from helao.hexagon.app.action_host import ActionHost
    from helao.helpers.premodels import Action

    host = ActionHost.__new__(ActionHost)
    host.server_key = "PSTAT"
    act_dir = tmp_path / "a"
    write_pair(act_dir, "CA-0.0.0.0__0", HEADER, ROWS)
    write_meta(act_dir / "260102.030405678901-act.json", {"action_name": "x"})
    action = Action(action_name="x")
    host._register_present_files(action, str(act_dir))
    assert [(f.file_name, f.file_type) for f in action.files] == [
        ("CA-0.0.0.0__0.jsonl", "pstat_helao__file")
    ]
```

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONPATH=$PWD python -m pytest helao/hexagon/tests/test_native_data_file.py helao/hexagon/tests/test_native_data_stream.py helao/hexagon/tests/test_posthoc_writer.py helao/core/tests/test_storage_format.py -q`
Expected: FAIL (writers still emit `.hlo` with `%%`; `_register_present_files` registers the `.meta.json` and the `-act.json`).

- [ ] **Step 3: Implement `data_file.py`**

Imports: add

```python
from helao.helpers.meta_io import write_meta
from helao.helpers.yml_tools import yml_dumps, yml_load
from helao.hexagon.domain.naming import HEADER_SUFFIX, data_sibling, is_nosync_file
```

(replacing the existing `yml_dumps`-only import), and a module-level helper after `LOGGER`:

```python
def _header_dict(text: str) -> dict:
    """A str data header as a dict: the YAML mapping it spells, else ``{"text": ...}``.

    Pre-JSON callers handed a ``yml_dumps`` string; reading it back keeps the
    S3 ``meta`` they produced unchanged.
    """
    if not text.strip():
        return {}
    try:
        parsed = yml_load(text, fast=True)
    except Exception:
        parsed = None
    return dict(parsed) if isinstance(parsed, dict) else {"text": text}


def _rows(output_str: str) -> str:
    """A one-shot body as ``.jsonl`` rows: newline-terminated, empty stays empty."""
    return output_str if not output_str or output_str.endswith("\n") else output_str + "\n"
```

In `init_datafile`, replace the header normalisation block (`if isinstance(header, dict):` … `header = ""`) with:

```python
        if file_group == HloFileGroup.helao_files:
            # A data header is always a dict, written as X.meta.json (spec §1).
            if isinstance(header, list):
                header = {"text": "\n".join(header)} if header else {}
            elif isinstance(header, str):
                header = _header_dict(header)
            elif header is None:
                header = {}
        elif isinstance(header, dict):
            # {} is "{}\n" if not filtered
            if header:
                header = yml_dumps(header)
            else:
                header = ""
        elif isinstance(header, list):
            if header:
                header = "\n".join(header) + "\n"
            else:
                header = ""
        elif header is None:
            header = ""
```

`file_ext = "hlo"` -> `file_ext = "jsonl"`; the `nosync=(...)` argument -> `nosync=is_nosync_file(filename, action.sync_data),`; the trailing block

```python
        if header:
            if not header.endswith("\n"):
                header += "\n"
```

-> 

```python
        if isinstance(header, str) and header and not header.endswith("\n"):
            header += "\n"
```

Docstring: `header` "dict, list of lines, string, or ``None``"; `file_group` "Selects ``.jsonl`` (helao group) or ``.csv`` (aux group)"; Returns "``(header, FileInfo)``: a dict for ``helao_files`` (empty means no header file), header text for ``aux_files``."

In `log_data_set_output_file`, after `os.makedirs(output_path, exist_ok=True)` insert:

```python
        if isinstance(header, dict):
            # helao_files: the header is its own file, X.meta.json, written
            # atomically before the rows file exists. No header, no file.
            if header:
                write_meta(data_sibling(output_file, HEADER_SUFFIX), header)
            header = ""
```

(the existing `w+` open and the `if header:` text write below stay, for an `aux_files` stream). Update the comment above the open: "...would push stale bytes ahead of the first row."

`_resolve_output_path`: change the `header: Optional[str],` annotation to `header,`.

`write_file`: replace the `async with aiofiles.open(output_file, mode="a+", ...)` block with:

```python
        if isinstance(header, dict):
            # helao_files: header overwritten atomically, rows appended (spec §2).
            if header:
                write_meta(data_sibling(output_file, HEADER_SUFFIX), header)
            async with aiofiles.open(output_file, mode="a+", encoding="utf-8") as f:
                await f.write(_rows(output_str))
            return output_file
        async with aiofiles.open(output_file, mode="a+", encoding="utf-8") as f:
            if header:
                await f.write(header)
            await f.write("%%\n")
            await f.write(output_str)
        return output_file
```

`write_file_nowait`: the same split, synchronous:

```python
        if isinstance(header, dict):
            if header:
                write_meta(data_sibling(output_file, HEADER_SUFFIX), header)
            with open(output_file, mode="a+", encoding="utf-8") as f:
                f.write(_rows(output_str))
        else:
            with open(output_file, mode="a+", encoding="utf-8") as f:
                if header:
                    f.write(header)
                f.write("%%\n")
                f.write(output_str)
        action.files.append(file_info)
        return output_file
```

Change both signatures' `header: Optional[str] = None` to `header=None`. Module docstring: "...the streamed-file opener (``w+`` truncate-on-create; a ``helao_files`` header goes to ``X.meta.json``), the one-shot writers (``helao_files``: header file overwritten + rows appended to ``X.jsonl``; ``aux_files``: ``a+``, header + ``%%\\n`` + payload)...".

- [ ] **Step 4: Implement the stream, the model, the post-hoc face, reconcile registration and the two servers**

`data_stream.py`: delete the separator block (the `# check if separator was already written` comment through the `await self.active.write_live_data(output_str="%%\n", ...)` call, lines 358-370). Docstring line 9: drop "``%%`` separator exactly once via ``added_hlo_separator``,".

`helao/core/models/file.py` `FileConn`: delete the `added_hlo_separator: bool = False` field and its docstring line, `self.added_hlo_separator = False` in `reset_file_conn` (docstring: "Clear the file handle, leaving params intact."), and `added_hlo_separator=deepcopy(self.added_hlo_separator),` in `deepcopy`. `FileConnParams.hloheader` comment: "the data header as a dict (written as X.meta.json)". `HloHeaderModel` docstring: "Header of every HELAO data file (``X.meta.json``)."

`posthoc_writer.py`: `_generated_filename` `ext = "hlo" if ...` -> `ext = "jsonl" if ...`. In `write_file` replace the `body = (...)` expression and the `_atomic_write_text(output_file, body)` line with:

```python
        if isinstance(resolved_header, dict):
            header_file = data_sibling(output_file, HEADER_SUFFIX)
            if resolved_header:
                _atomic_write_text(header_file, dumps_meta(resolved_header))
            elif os.path.exists(header_file):
                # A rerun without a header must not keep the failed run's one.
                os.remove(header_file)
            body = _rows(output_str)
        else:
            body = (
                f"{resolved_header}%%\n{output_str}"
                if resolved_header
                else f"%%\n{output_str}"
            )
        _atomic_write_text(output_file, body)
```

with imports `from helao.helpers.meta_io import dumps_meta`, `from helao.hexagon.domain.naming import HEADER_SUFFIX, data_sibling`, `from helao.hexagon.adapters.native.data_file import _rows`. Docstrings: write_file "The ``helao_files`` file is ``X.jsonl`` (rows) plus ``X.meta.json`` (header, when there is one); an ``aux_files`` file is header + ``%%\\n`` + payload"; module bullet "Data files are written atomically, and always overwrite ... appending ... this face replaces the target instead" stays true.

`action_host._register_present_files` (1495-1512): extend the skip condition and the data test:

```python
            if (
                not path.is_file()
                or path.name.startswith(".")
                or path.suffix in (".yml", ".lock", ".tmp", ".prg")
                or path.name.endswith(HEADER_SUFFIX)
                or meta_kind(path) is not None
            ):
                continue
            ...
            is_hlo = path.suffix in (".hlo", DATA_SUFFIX)
```

with `from helao.hexagon.domain.naming import DATA_SUFFIX, HEADER_SUFFIX, meta_kind`. Docstring: "Skips what the finalizer never registers: records (``.json``/``.yml``), data headers (``.meta.json``), locks, staging and other dotfiles."

`helao/deploy/hte/servers/action/gamry_server2.py` (85-87): `filename="init_ocv.hlo",` -> `filename="init_ocv.jsonl",`; `header=yml_dumps({"mean_ocv": mean_ocv}),` -> `header={"mean_ocv": mean_ocv},`; remove `yml_dumps` from its imports if unused.

`helao/deploy/hte/servers/action/calc_server.py:103`: `suffix = f"{k}.hlo"` -> `suffix = f"{k}.jsonl"`.

`helao/hexagon/ports/artifact_store.py` docstring lines 10-15: "LAZY data open on first data item per file_conn_key (mode ``w+``); header (HloHeaderModel.clean_dict()) to ``X.meta.json`` at open; rows to ``X.jsonl``, one JSON object per line; NaN/Infinity tokens legal; NO DATA => NO FILE; close at finish (or substitute). One-shot helao files: header overwritten, rows appended; aux files: mode ``a+``, ``header + "%%\\n" + payload``. FileInfo appended at write; gated by ``save_data``."

- [ ] **Step 5: Run to verify they pass, plus every streamed-writer suite**

Run: `PYTHONPATH=$PWD python -m pytest helao/hexagon/tests/test_native_data_file.py helao/hexagon/tests/test_native_data_stream.py helao/hexagon/tests/test_posthoc_writer.py helao/hexagon/tests/test_native_finalizer.py helao/hexagon/tests/test_finish_drain_marker.py helao/hexagon/tests/test_enqueue_nowait_marshals_to_loop.py helao/hexagon/tests/test_action_writes_artifacts.py helao/hexagon/tests/test_reconcile_interrupted.py helao/deploy/hte/tests/test_gamry_versus_ocv.py helao/deploy/hte/tests/test_med_servers_fixes.py helao/core/tests/test_storage_format.py -q`
Expected: PASS. (`test_native_finalizer.py:84` and `test_action_writes_artifacts.py:151` still look for `-act.yml`, which is correct until Task 12 flips the meta writers.)

- [ ] **Step 6: Commit**

```bash
F="helao/hexagon/adapters/native/data_file.py helao/hexagon/adapters/native/data_stream.py helao/core/models/file.py helao/hexagon/adapters/native/posthoc_writer.py helao/hexagon/app/action_host.py helao/deploy/hte/servers/action/gamry_server2.py helao/deploy/hte/servers/action/calc_server.py helao/hexagon/ports/artifact_store.py helao/hexagon/tests/test_native_data_file.py helao/hexagon/tests/test_native_data_stream.py helao/hexagon/tests/test_posthoc_writer.py helao/hexagon/tests/test_native_finalizer.py helao/hexagon/tests/test_finish_drain_marker.py helao/hexagon/tests/test_enqueue_nowait_marshals_to_loop.py helao/hexagon/tests/test_action_writes_artifacts.py helao/deploy/hte/tests/test_gamry_versus_ocv.py helao/core/tests/test_storage_format.py"
black $F && pyright helao/hexagon/adapters/native/data_file.py helao/hexagon/adapters/native/data_stream.py helao/core/models/file.py helao/hexagon/adapters/native/posthoc_writer.py helao/hexagon/app/action_host.py helao/deploy/hte/servers/action/gamry_server2.py helao/deploy/hte/servers/action/calc_server.py
git -C /mnt/STORAGE/repos/helao/helao-async add $F
git -C /mnt/STORAGE/repos/helao/helao-async commit -m "feat(writers)!: data files are X.meta.json + X.jsonl; no %% separator"
```

---

### Task 12: Metadata writers emit `-act/-exp/-seq.json` and `-ana.json`

**Files:**
- Modify: `helao/hexagon/adapters/native/meta_writer.py` (`write_act` 76-101, `write_exp` 103-122, `write_seq` 124-144, docstrings)
- Modify: `helao/hexagon/adapters/native/posthoc_writer.py` (`write_act` 455-471, `write_exp`/`write_seq` 473-483, `_act_path`/`_exp_path`/`_seq_path` 500-521)
- Modify: `helao/core/runners/micro_orch.py` (`_write_exp` 1022-1038, `_write_seq` 1040-1053, `_candidate_yml` 1063-1073, `_await_finished` message 1088-1091)
- Modify: `helao/helpers/yml_tools.py` (`move_dir` 296-297)
- Modify: `helao/core/drivers/data/analysis_layout.py` (`write_model_yml` 291-305 -> `write_model_json`, `__all__` 50, docstring 13), `helao/core/drivers/data/analysis_driver.py` (84, 1256), `helao/hexagon/adapters/native/analysis_artifact.py` (43, 133)
- Modify (standalone golden master): `helao/core/tests/test_active_golden_master.py` (`_split_hlo` 269-276, dispatch 382) and its reference `helao/core/tests/golden/action/`
- Test: `helao/hexagon/tests/test_native_meta_writer.py`, `test_posthoc_writer.py` (meta tests), `test_native_finalizer.py` (84, 237-238), `test_action_writes_artifacts.py` (151), `test_prefinish_action.py` (28), `test_reconcile_interrupted.py` (114), `test_concurrency_live.py` (66-71, 162), `test_live_group.py` (33, 35), `test_finish_drain_marker.py` (339), `test_native_artifact_store.py` (60), `test_analysis_artifact.py` (234, 238, 257, 268), `helao/deploy/hte/tests/test_kinesis_estop.py` (277-282), `helao/core/tests/unit_test_micro_orch.py` (358-365)

**Interfaces:**
- Consumes: `resolve_meta_path`, `dumps_meta`, `write_meta`, `meta_glob`, `read_meta` (Task 2).
- Produces: `analysis_layout.write_model_json(local_ana_dir: str, analysis_uuid, model_dict: dict) -> str` (path of `<uuid>-ana.json`; replaces `write_model_yml`). Every record writer resolves its target through `resolve_meta_path`, so a record whose `.yml` already exists stays YAML; `PostHocRunWriter.write_*` and `MicroOrch._write_*` return the path actually written.

- [ ] **Step 1: Write the failing tests**

`helao/hexagon/tests/test_native_meta_writer.py` (add `from helao.helpers.meta_io import read_meta`):

| Test | Before | After |
|---|---|---|
| `test_write_act_layout` 29-32 | `f.endswith("-act.yml")`, `["260102.030405678901-act.yml"]`, `assert text.startswith("file_type: action\n")` | `f.endswith("-act.json")`, `["260102.030405678901-act.json"]`, `assert text.startswith('{\n  "file_type": "action",')` |
| `test_manual_action_diag_swap` 93 | `f.endswith("-act.yml")` | `f.endswith("-act.json")` |
| `test_write_exp_and_seq` 105, 106, 109, 113 | `"-exp.yml"`, `"-seq.yml"`, `"-exp.yml"`, `exp_text.startswith("file_type: experiment\n")` | `"-exp.json"`, `"-seq.json"`, `"-exp.json"`, `exp_text.startswith('{\n  "file_type": "experiment",')` |

`test_write_meta_atomic_tmp_shape` (66, 80) calls `_write_meta_atomic` with an explicit `-act.yml` path and string: unchanged, and it keeps the staging-length pin. Add:

```python
@pytest.mark.asyncio
async def test_write_act_keeps_an_in_flight_yml(tmp_path):
    """Review Focus 1: a record begun as YAML is finished as YAML, no twin."""
    save_root = str(tmp_path / "RUNS_ACTIVE")
    base = _swap(make_base(save_root), tmp_path)
    action = mk_action(save_act=True)
    out_dir = os.path.join(save_root, str(action.action_output_dir))
    os.makedirs(out_dir)
    legacy = os.path.join(out_dir, "260102.030405678901-act.yml")
    with open(legacy, "w", encoding="utf-8") as f:
        f.write("action_status: [active]\n")
    await base.write_act(action)
    assert sorted(f for f in os.listdir(out_dir) if not f.startswith(".")) == [
        "260102.030405678901-act.yml"
    ]
    assert read_meta(legacy)["file_type"] == "action"
```

(`make_base`, `_swap`, `mk_action` are this module's own helpers, as used by `test_write_act_layout`; copy its decorator if it is not `@pytest.mark.asyncio`.)

`helao/hexagon/tests/test_posthoc_writer.py` meta tests:

| Test | Before | After |
|---|---|---|
| `test_write_act_writes_a_parsable_act_yml_and_returns_its_path` (rename `..._act_json_...`) | `f"{TS_STAMP}-act.yml"`; `assert text.startswith("file_type: action\n")` | `f"{TS_STAMP}-act.json"`; `assert text.startswith('{\n  "file_type": "action",')` (`yaml.safe_load(text)` still parses the JSON) |
| `test_meta_writes_swap_a_complete_temp_file_into_place` | `assert staged.startswith("file_type: action\n")` | `assert staged.startswith('{\n  "file_type": "action",')` |
| `test_the_face_works_when_called_from_inside_a_running_loop` | `.endswith("-act.yml")` | `.endswith("-act.json")` |
| `test_write_act_with_save_act_false_returns_none_without_raising` | `n.endswith("-act.yml")` | `n.endswith(("-act.json", "-act.yml"))` (otherwise the check is vacuous) |
| `test_write_exp_and_write_seq_write_their_own_yml` (rename `..._own_record`) | `f"{TS_STAMP}-exp.yml"`, `f"{TS_STAMP}-seq.yml"`, `startswith("file_type: experiment\n")`, `startswith("file_type: sequence\n")` | `f"{TS_STAMP}-exp.json"`, `f"{TS_STAMP}-seq.json"`, `startswith('{\n  "file_type": "experiment",')`, `startswith('{\n  "file_type": "sequence",')` |
| `test_meta_yml_uses_the_indented_block_sequence_style` | whole test (pins YAML block style, divergence 6) | replace with the test below |

```python
def test_meta_json_is_two_space_indented(run):
    """The record is pretty JSON (spec §1): 2-space indent, trailing newline."""
    act, writer = run["act"], run["writer"]
    writer.write_file(
        act,
        output_str="{}",
        file_type="demo_helao__file",
        filenum=0,
        file_group=HloFileGroup.helao_files,
        file_sample_label=LABEL,
    )
    text = _read(writer.write_act(act))
    assert text.startswith('{\n  "file_type": "action",\n')
    assert '  "files": [\n    {\n' in text
    assert text.endswith("}\n")


def test_write_act_returns_the_in_flight_yml_it_rewrote(run):
    act, writer, save_root = run["act"], run["writer"], run["save_root"]
    legacy = os.path.join(save_root, str(act.action_output_dir), f"{TS_STAMP}-act.yml")
    os.makedirs(os.path.dirname(legacy), exist_ok=True)
    with open(legacy, "w", encoding="utf-8") as f:
        f.write("action_status: [active]\n")
    assert writer.write_act(act) == legacy
    assert yaml.safe_load(_read(legacy))["action_name"] == "run_demo"
```

If `yml_dumps` becomes unused in the module after replacing the block-style test, remove its import.

Writer-output globs in the other suites:

| File:line | Before | After |
|---|---|---|
| `test_native_finalizer.py:84` | `f.endswith("-act.yml")` | `f.endswith("-act.json")` |
| `test_native_finalizer.py:237, 238` | `"-exp.yml"`, `"-seq.yml"` | `"-exp.json"`, `"-seq.json"` |
| `test_action_writes_artifacts.py:151` | `n.endswith("-act.yml")` | `n.endswith("-act.json")` |
| `test_prefinish_action.py:28` | `Path(root).rglob("*-act.yml")` | `Path(root).rglob("*-act.json")` |
| `test_reconcile_interrupted.py:114` | `(yml,) = act_dir.glob("*-act.yml")` | `(yml,) = act_dir.glob("*-act.json")` |
| `test_concurrency_live.py:66, 67` | `rglob("*-exp.yml")` (RUNS and RUNS_FINISHED) | `rglob("*-exp.json")` for `RUNS`; keep `*-exp.yml` for the legacy `RUNS_FINISHED`/zip arms |
| `test_concurrency_live.py:162` | `Path(root).rglob("*-exp.yml")` | `Path(root).rglob("*-exp.json")` (the `yaml.safe_load` below parses JSON) |
| `test_live_group.py:33, 35` | `"*-seq.yml"`, `"*-exp.yml"` | `"*-seq.json"`, `"*-exp.json"` |
| `test_finish_drain_marker.py:339` | `"*-act.yml"` | `"*-act.json"` |
| `test_native_artifact_store.py:60` | `f.endswith("-act.yml")` | `f.endswith("-act.json")` |
| `test_analysis_artifact.py:234, 257` | `f"{UUID_A}.yml",` | `f"{UUID_A}-ana.json",` |
| `test_analysis_artifact.py:238` | `assert yml_load(d / f"{UUID_A}.yml")["analysis_uuid"] == UUID_A` | `assert read_meta(d / f"{UUID_A}-ana.json")["analysis_uuid"] == UUID_A` (import `read_meta`) |
| `test_analysis_artifact.py:268` | `rglob("*.yml")` | `rglob("*-ana.json")` |
| `helao/deploy/hte/tests/test_kinesis_estop.py:277, 282` | `if f.endswith("-act.yml")` / `assert "error_code: estop" in open(acts[0], encoding="utf-8").read()` | `if f.endswith("-act.json")` / `assert read_meta(acts[0])["error_code"] == "estop"` (import `from helao.helpers.meta_io import read_meta`) |
| `helao/core/tests/unit_test_micro_orch.py:358-365` | `n.endswith("-seq.yml")`, `n.endswith("-exp.yml")` | `n.endswith("-seq.json")`, `n.endswith("-exp.json")` (the `-act.yml` check at 366-369 stays: the fake server hand-writes a legacy action) |

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONPATH=$PWD python -m pytest helao/hexagon/tests/test_native_meta_writer.py helao/hexagon/tests/test_posthoc_writer.py helao/hexagon/tests/test_analysis_artifact.py -q`
Expected: FAIL (records still `.yml`; model still `<uuid>.yml`).

- [ ] **Step 3: Implement the record writers**

`meta_writer.py` (imports: replace `from helao.helpers.yml_tools import yml_dumps` with `from helao.helpers.meta_io import dumps_meta, resolve_meta_path`). In each of `write_act`/`write_exp`/`write_seq`, change the filename suffix to `-act.json` / `-exp.json` / `-seq.json` and the final write to:

```python
            target = resolve_meta_path(output_file)
            await self.base._write_meta_atomic(str(target), dumps_meta(output_dict, target))
```

(indent per method). Docstrings: "``<timestamp>-act.json`` (or the existing ``-act.yml`` it rewrites in place)". Module docstring: "Native record-metadata writer ... ``write_act``/``write_exp``/``write_seq`` (``file_type`` first key, pretty JSON or an in-flight YAML rewrite, trailing newline, ...)".

`posthoc_writer.py`: in `_act_path`/`_exp_path`/`_seq_path` change `-act.yml`/`-exp.yml`/`-seq.yml` to `.json`, and make `write_act`/`write_exp`/`write_seq` return the resolved path:

```python
        return str(resolve_meta_path(self._act_path(action, manual)))
```

(and the same with `_exp_path`/`_seq_path`), importing `resolve_meta_path` from `helao.helpers.meta_io`. Docstrings: "Write the action's ``-act.json`` (an existing ``-act.yml`` is rewritten in place)". Module bullet "Meta ymls are written atomically ... with the default YAML dumper" -> "Records are written atomically (temp file + ``os.replace``) as pretty JSON, matching the core writers."

`micro_orch.py`: in `_write_exp`/`_write_seq` change the suffixes to `.json`, and replace `await self._write_meta_atomic(output_file, yml_dumps(output_dict))` / `return output_file` with:

```python
        target = resolve_meta_path(output_file)
        await self._write_meta_atomic(str(target), dumps_meta(output_dict, target))
        return str(target)
```

`_candidate_yml`:

```python
        for state_root in (run_root(root), diag_root(root)):
            matches = meta_glob(os.path.join(str(state_root), rel_dir), suffix)
            if matches:
                return str(matches[0])
        return None
```

and the `_await_finished` docstring/message `*-{suffix}.yml` -> `*-{suffix}.json|.yml`. Imports: `from helao.helpers.meta_io import dumps_meta, meta_glob, resolve_meta_path`; keep `yml_finisher` from `yml_tools`, drop `yml_dumps` if unused; drop `glob_module` if unused.

`yml_tools.move_dir` (296-297):

```python
    timestamp = getattr(hobj, f"{obj_type}_timestamp").strftime("%y%m%d.%H%M%S%f")
    # Local import: meta_io imports this module. The handoff names the record
    # the writer actually produced -- .json, or an in-flight .yml.
    from helao.helpers.meta_io import resolve_meta_path

    yml_path = str(
        resolve_meta_path(os.path.join(yml_dir, f"{timestamp}-{obj_type[:3]}.json"))
    )
```

- [ ] **Step 4: Implement the analysis model writer**

`analysis_layout.py`: replace `write_model_yml` with

```python
def write_model_json(local_ana_dir: str, analysis_uuid, model_dict: dict) -> str:
    """Write ``<local_ana_dir>/<analysis_uuid>-ana.json`` atomically; return its path.

    Args:
        local_ana_dir: Directory from :func:`analysis_dir`.
        analysis_uuid: UUID naming the file.
        model_dict: The cleaned ``AnalysisModel`` dict to dump.
    """
    return str(write_meta(os.path.join(local_ana_dir, f"{analysis_uuid}-ana.json"), model_dict))
```

with `from helao.helpers.meta_io import write_meta`; rename in `__all__` and the module docstring (line 13); drop `yml_dumps` if unused. Rename the import and the call in `analysis_driver.py` (84, 1256) and `analysis_artifact.py` (43, 133). Run `grep -rn write_model_yml helao harness` — expect no output.

- [ ] **Step 5: Re-point the action golden master**

`helao/core/tests/test_active_golden_master.py` is a standalone `--check`/`--freeze` script (not collected by pytest). Make its comparator format-aware:

```python
def _split_hlo(body: str):
    """Split a data body into (header_text, [data_line, ...]).

    A legacy ``.hlo`` carries its header before ``%%``; a ``.jsonl`` is rows
    only (its header is the separate ``.meta.json`` member).
    """
    lines = body.splitlines()
    if "%%" not in lines:
        return "", [line for line in lines if line.strip()]
    idx = lines.index("%%")
    header = "\n".join(lines[:idx])
    data_lines = [line for line in lines[idx + 1 :] if line.strip()]
    return header, data_lines
```

and at line 382 `if rel.endswith(".hlo"):` -> `if rel.endswith((".hlo", ".jsonl")):`. Then:

```bash
D="${CLAUDE_JOB_DIR:-$HOME/.cache/helao-json-storage}/json-storage"
cd /mnt/STORAGE/repos/helao/helao-async
PYTHONPATH=$PWD python -m helao.core.tests.test_active_golden_master --check > "$D/golden-master-check.txt" 2>&1; echo "rc=$?"
grep -c 'only-in-baseline' "$D/golden-master-check.txt"
```

Expected: `rc=1`, and every failure line is a `manifest` line whose only-in-baseline members are `*.hlo` / `*-act.yml` / `*-exp.yml` / `*-seq.yml` and whose only-in-current members are the matching `*.jsonl` / `*.meta.json` / `*-act.json` / `*-exp.json` / `*-seq.json`. **Stop and report** if any other failure kind appears (a header/data/trace diff means behaviour changed, not just names). Only then re-freeze:

```bash
cp -r helao/core/tests/golden/action "$D/golden-action-before"   # keep the old reference for the reviewer
rm -r helao/core/tests/golden/action
PYTHONPATH=$PWD python -m helao.core.tests.test_active_golden_master --freeze
PYTHONPATH=$PWD python -m helao.core.tests.test_active_golden_master --check; echo "rc=$?"
PYTHONPATH=$PWD python -m helao.core.tests.test_active_golden_master; echo "selftest rc=$?"
```

Expected: `--check` rc=0 and the self-test rc=0. The re-freeze is a reviewer decision point: attach `$D/golden-master-check.txt` to the review.

- [ ] **Step 6: Run to verify they pass, plus every live-writer suite**

Run: `PYTHONPATH=$PWD python -m pytest helao/hexagon/tests/test_native_meta_writer.py helao/hexagon/tests/test_posthoc_writer.py helao/hexagon/tests/test_native_finalizer.py helao/hexagon/tests/test_action_writes_artifacts.py helao/hexagon/tests/test_prefinish_action.py helao/hexagon/tests/test_reconcile_interrupted.py helao/hexagon/tests/test_concurrency_live.py helao/hexagon/tests/test_live_group.py helao/hexagon/tests/test_finish_drain_marker.py helao/hexagon/tests/test_native_artifact_store.py helao/hexagon/tests/test_analysis_artifact.py helao/deploy/hte/tests/test_kinesis_estop.py helao/core/tests/test_micro_orch_finish.py helao/core/tests/test_yml_finisher.py -q && PYTHONPATH=$PWD python run_unit_tests.py`
Expected: PASS (`run_unit_tests.py` includes `micro_orch_unit_test`).

- [ ] **Step 7: Commit**

```bash
F="helao/hexagon/adapters/native/meta_writer.py helao/hexagon/adapters/native/posthoc_writer.py helao/core/runners/micro_orch.py helao/helpers/yml_tools.py helao/core/drivers/data/analysis_layout.py helao/core/drivers/data/analysis_driver.py helao/hexagon/adapters/native/analysis_artifact.py helao/core/tests/test_active_golden_master.py helao/hexagon/tests/test_native_meta_writer.py helao/hexagon/tests/test_posthoc_writer.py helao/hexagon/tests/test_native_finalizer.py helao/hexagon/tests/test_action_writes_artifacts.py helao/hexagon/tests/test_prefinish_action.py helao/hexagon/tests/test_reconcile_interrupted.py helao/hexagon/tests/test_concurrency_live.py helao/hexagon/tests/test_live_group.py helao/hexagon/tests/test_finish_drain_marker.py helao/hexagon/tests/test_native_artifact_store.py helao/hexagon/tests/test_analysis_artifact.py helao/deploy/hte/tests/test_kinesis_estop.py helao/core/tests/unit_test_micro_orch.py"
black $F && pyright helao/hexagon/adapters/native/meta_writer.py helao/hexagon/adapters/native/posthoc_writer.py helao/core/runners/micro_orch.py helao/helpers/yml_tools.py helao/core/drivers/data/analysis_layout.py helao/core/drivers/data/analysis_driver.py helao/hexagon/adapters/native/analysis_artifact.py
git -C /mnt/STORAGE/repos/helao/helao-async add -A helao/core/tests/golden/action
git -C /mnt/STORAGE/repos/helao/helao-async add $F
git -C /mnt/STORAGE/repos/helao/helao-async commit -m "feat(writers)!: records are -act/-exp/-seq.json, analysis models -ana.json; in-flight YAML kept"
```

---

### Task 13: Mixed-tree reader parity and the SYNC golden on a new-format record

**Files:**
- Modify: `harness/tests/synthtree.py` (`build_tree` 21-84; new `zip_sequence`)
- Create: `helao/core/tests/test_mixed_tree_readers.py`
- Modify: `helao/hexagon/tests/sync_fixtures.py` (`write_yml` 65-70, `make_exp_tree` 112-119, `make_action` 122-127)
- Modify: `helao/core/tests/test_sync_postfinish_golden.py` (`_build_tree` 343-377, `test_default_chain_golden` 400-541)

**Interfaces:**
- Consumes: everything above.
- Produces (test helpers only):
  - `build_tree(root, seed=0, fmt="legacy", extended=False) -> dict` — `fmt` in `legacy` (all `.yml`/`.hlo`), `new` (all `.json`, `.meta.json` + `.jsonl`), `mixed` (`-seq.yml` above `-exp.json`/`-act.json` and a pair). `extended=True` adds a `files` entry on the action and a colocated process record (`0__<uuid>__SIM-prc.yml|.json`). The default call writes exactly what it wrote before, so existing harness tests are untouched. Adds `"prc_uuid"` to the returned dict.
  - `zip_sequence(root, info) -> Path` — zips `info["seq_dir"]` into `<root>/RUNS_SYNCED/25.28/0716/<seq dir name>.zip` (members relative to the sequence dir, the `sync_driver` convention) and removes the directory.
  - `sync_fixtures.write_yml(path, meta)` writes JSON when `path` ends in `.json`; `make_exp_tree(..., ext=".yml")`, `make_action(..., ext=".yml")`.

- [ ] **Step 1: Extend the fixtures**

`harness/tests/synthtree.py` — change the signature and docstring, keep every legacy literal byte-identical, and branch the writes:

```python
import shutil
import zipfile

from helao.helpers.meta_io import write_meta
from helao.helpers.to_json import hlo_json_dumps

_HEADER = {
    "hlo_version": "2025.07.07",
    "action_name": "WsSim",
    "column_headings": ["t_s", "series_0"],
    "epoch_ns": 1752671661000000000,
}
_ROWS = [{"t_s": 0.0, "series_0": 0.5}, {"t_s": 0.1, "series_0": 0.6}]


def build_tree(root: Path, seed: int = 0, fmt: str = "legacy", extended: bool = False) -> dict:
    """Create <root>/RUNS_FINISHED/... with 1 seq / 1 exp / 1 act / 1 data file.

    ``seed`` offsets every uuid so two builds simulate two captures of the
    same run differing only in volatile identity. ``fmt`` picks the storage
    format: ``legacy`` (.yml records, .hlo data), ``new`` (.json records,
    .meta.json + .jsonl data) or ``mixed`` (a legacy -seq.yml above new
    -exp/-act records and a pair -- a sequence that straddled the upgrade).
    ``extended`` adds the action's ``files`` entry and a colocated process
    record, which reader-parity tests need and normalizer tests must not see.
    Returns the identifiers and directories used, for assertions.
    """
```

Body: keep the uuid/dir lines, add `prc_uuid = _u(seed + 4)`, then:

```python
    new_seq = fmt == "new"
    new_rest = fmt in ("new", "mixed")
    seq_meta = {
        "file_type": "sequence", "sequence_uuid": seq_uuid, "sequence_name": "GMTEST",
        "sequence_label": "golden", "sequence_timestamp": "2025-07-16 13:14:15.123456",
        "sequence_status": ["finished"], "dummy": True,
    }
    exp_meta = {
        "file_type": "experiment", "experiment_uuid": exp_uuid, "sequence_uuid": seq_uuid,
        "experiment_name": "TEST_exp", "experiment_timestamp": "2025-07-16 13:14:20.123456",
        "experiment_status": ["finished"],
    }
    act_meta = {
        "file_type": "action", "action_uuid": act_uuid, "experiment_uuid": exp_uuid,
        "sequence_uuid": seq_uuid, "action_name": "acquire_data",
        "action_timestamp": "2025-07-16 13:14:21.123456",
        "action_status": ["finished"], "action_params": {"duration": 2.0},
    }
    data_name = "WsSim-0.0.0.0__0" + (".jsonl" if new_rest else ".hlo")
    if extended:
        act_meta["files"] = [{"file_name": data_name, "file_type": "wssim_helao__file"}]
    if new_seq:
        write_meta(seq_dir / "250716.131415123456-seq.json", seq_meta)
    else:
        (seq_dir / "250716.131415123456-seq.yml").write_text(
            "file_type: sequence\n"
            f"sequence_uuid: {seq_uuid}\n"
            "sequence_name: GMTEST\n"
            "sequence_label: golden\n"
            "sequence_timestamp: 2025-07-16 13:14:15.123456\n"
            "sequence_status:\n  - finished\n"
            "dummy: true\n",
            encoding="utf-8",
        )
    if new_rest:
        write_meta(exp_dir / "250716.131420123456-exp.json", exp_meta)
        write_meta(act_dir / "250716.131421123456-act.json", act_meta)
        write_meta(act_dir / "WsSim-0.0.0.0__0.meta.json", _HEADER)
        (act_dir / "WsSim-0.0.0.0__0.jsonl").write_text(
            "".join(hlo_json_dumps(r) + "\n" for r in _ROWS), encoding="utf-8"
        )
    else:
        (exp_dir / "250716.131420123456-exp.yml").write_text(
            "file_type: experiment\n"
            f"experiment_uuid: {exp_uuid}\n"
            f"sequence_uuid: {seq_uuid}\n"
            "experiment_name: TEST_exp\n"
            "experiment_timestamp: 2025-07-16 13:14:20.123456\n"
            "experiment_status:\n  - finished\n",
            encoding="utf-8",
        )
        act_text = (
            "file_type: action\n"
            f"action_uuid: {act_uuid}\n"
            f"experiment_uuid: {exp_uuid}\n"
            f"sequence_uuid: {seq_uuid}\n"
            "action_name: acquire_data\n"
            "action_timestamp: 2025-07-16 13:14:21.123456\n"
            "action_status:\n  - finished\n"
            "action_params:\n  duration: 2.0\n"
        )
        if extended:
            act_text += f"files:\n  - file_name: {data_name}\n    file_type: wssim_helao__file\n"
        (act_dir / "250716.131421123456-act.yml").write_text(act_text, encoding="utf-8")
        (act_dir / "WsSim-0.0.0.0__0.hlo").write_text(
            "hlo_version: '2025.07.07'\n"
            "action_name: WsSim\n"
            "column_headings:\n"
            "  - t_s\n"
            "  - series_0\n"
            "epoch_ns: 1752671661000000000\n"
            "%%\n"
            '{"t_s": 0.0, "series_0": 0.5}\n'
            '{"t_s": 0.1, "series_0": 0.6}\n',
            encoding="utf-8",
        )
    if extended:
        prc = {"process_uuid": prc_uuid, "experiment_uuid": exp_uuid, "process_group_index": 0}
        if new_rest:
            write_meta(exp_dir / f"0__{prc_uuid}__SIM-prc.json", prc)
        else:
            (exp_dir / f"0__{prc_uuid}__SIM-prc.yml").write_text(
                f"process_uuid: {prc_uuid}\nexperiment_uuid: {exp_uuid}\nprocess_group_index: 0\n",
                encoding="utf-8",
            )
```

The legacy literals above are the ones at lines 35-76 today, byte for byte (only the `act_text` variable is new). Add `"prc_uuid": prc_uuid` to the returned dict. Then add:

```python
def zip_sequence(root: Path, info: dict) -> Path:
    """Archive ``info['seq_dir']`` as a synced sequence zip and remove the directory."""
    seq_dir = info["seq_dir"]
    zp = root / "RUNS_SYNCED" / "25.28" / "0716" / f"{seq_dir.name}.zip"
    zp.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zp, "w") as zf:
        for f in sorted(seq_dir.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(seq_dir).as_posix())
    shutil.rmtree(seq_dir)
    return zp
```

`helao/hexagon/tests/sync_fixtures.py`:

```python
def write_yml(path: Path, meta: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    dumped = yml_dumps(meta)
    if isinstance(dumped, bytes):
        dumped = dumped.decode("utf-8")
    if path.suffix == ".json":
        # A JSON record carrying exactly the values the YAML twin would load,
        # so a golden compares formats and not this fixture's scalar typing
        # (ts() stamps are numeric-looking and load from YAML as floats).
        path.write_text(dumps_meta(yml_load(dumped, fast=True)), encoding="utf-8")
        return
    path.write_text(dumped, encoding="utf-8")
```

(imports `from helao.helpers.meta_io import dumps_meta`, `yml_load` from `yml_tools`), and give `make_exp_tree` / `make_action` a trailing `ext: str = ".yml"` parameter used in `f"{ts(0)}-exp{ext}"` / `f"{ts(order + 1)}-act{ext}"`.

- [ ] **Step 2: Write the parity test** — create `helao/core/tests/test_mixed_tree_readers.py`:

```python
"""Every reader reports the same records and data on legacy, new and mixed trees.

JSON storage spec §5: HelaoData, LocalLoader, the data browser, run_state,
retire, process_locator and list_pending* must agree with a legacy-only twin.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from harness.tests.synthtree import build_tree, zip_sequence
from helao.core.drivers.data.loaders.localfs import LocalLoader
from helao.core.drivers.data.process_locator import find_process_ymls
from helao.helpers.helao_data import HelaoData
from helao.helpers.meta_io import meta_glob
from helao.helpers.run_state import rebuild_from_tree
from helao.hexagon.adapters.native import sync_driver as sd
from helao.ui.shared import retire
from helao.ui.shared.data_browser.sources import RunsSourceIndex

DATA = {"t_s": [0.0, 0.1], "series_0": [0.5, 0.6]}


def _observe(root: Path, info: dict) -> dict:
    """What every reader reports about one tree, in format-independent terms."""
    hd = HelaoData(str(meta_glob(info["seq_dir"], "seq")[0]))
    (exp,) = hd.exp
    (act,) = exp.act
    hd_meta, hd_data = act.read_data_file(act.data_files[0])
    ll = LocalLoader(data_path=str(info["seq_dir"]))
    ll_meta, ll_data = ll.get_act(0).hlo
    journal = rebuild_from_tree(root / "RUNS_FINISHED", root / "STATES", "SYNC")
    (loc,) = retire.locate(str(root), info["seq_uuid"])
    _, scanned = retire._scan_local([loc])
    drv = sd.SyncDriver.__new__(sd.SyncDriver)
    drv.helaodirs = SimpleNamespace(save_root=root / "RUNS_ACTIVE")  # type: ignore[assignment]
    return {
        "helao_data": (hd.uuid, exp.uuid, act.uuid, len(act.data_files), hd_meta, dict(hd_data)),
        "local_loader": (
            len(ll.sequences), len(ll.experiments), len(ll.actions), len(ll.processes),
            ll_meta, dict(ll_data),
        ),
        "browser_rows": len(RunsSourceIndex(root, "FINISHED").index()),
        "journal": sorted(r["kind"] for r in journal.working_set().values()),
        "retire_files": scanned,
        "processes": len(find_process_ymls(info["exp_dir"])),
        "pending": (
            len(drv.list_pending()), len(drv.list_pending_exps()), len(drv.list_pending_acts())
        ),
    }


@pytest.mark.parametrize("fmt", ["new", "mixed"])
def test_dir_tree_readers_match_the_legacy_twin(tmp_path, fmt):
    legacy = _observe(tmp_path / "a", build_tree(tmp_path / "a", fmt="legacy", extended=True))
    other = _observe(tmp_path / "b", build_tree(tmp_path / "b", fmt=fmt, extended=True))
    # not vacuous: the legacy twin itself sees one of everything
    header = {
        "hlo_version": "2025.07.07",
        "action_name": "WsSim",
        "column_headings": ["t_s", "series_0"],
        "epoch_ns": 1752671661000000000,
    }
    assert legacy["helao_data"][3:] == (1, header, DATA)
    assert legacy["local_loader"][:4] == (1, 1, 1, 1)
    assert legacy["journal"] == ["action", "experiment", "sequence"]
    assert legacy["pending"] == (1, 1, 1)
    assert other == legacy


@pytest.mark.parametrize("fmt", ["legacy", "new", "mixed"])
def test_a_zipped_sequence_reads_in_every_format(tmp_path, fmt):
    zp = zip_sequence(tmp_path, build_tree(tmp_path, fmt=fmt, extended=True))
    hd = HelaoData(str(zp))
    (act,) = hd.exp[0].act
    meta, data = act.read_hlo(act.data_files[0])
    assert dict(data) == DATA and meta["action_name"] == "WsSim"
    ll = LocalLoader(data_path=str(zp))
    assert (len(ll.sequences), len(ll.experiments), len(ll.actions), len(ll.processes)) == (1, 1, 1, 1)
    meta2, data2 = ll.get_act(0).hlo
    assert (meta2, dict(data2)) == (meta, dict(data))
    assert len(RunsSourceIndex(tmp_path, "SYNCED").index()) == 1
```

If the **legacy** twin raises inside `LocalLoader`/`HelaoData` (e.g. a field a loader requires that the synthetic record lacks), add that field to `seq_meta`/`exp_meta`/`act_meta` **and** to the matching legacy literal in `build_tree(extended=True)` only — never relax the parity assertion.

- [ ] **Step 3: Parametrize the SYNC golden on the record format**

In `helao/core/tests/test_sync_postfinish_golden.py` add `JSONL = "data-0.0.0.0__0.jsonl"` beside `HLO`, import `dumps_meta`, and replace `_build_tree` with:

```python
def _build_tree(root, fmt: str = "legacy"):
    ext = ".yml" if fmt == "legacy" else ".json"
    exp_yml = make_exp_tree(root, "RUNS", EXP_UUID, ext=ext)
    seq_dir = exp_yml.parent.parent
    seq_yml = seq_dir / f"{ts(0)}-seq{ext}"
    write_yml(
        seq_yml,
        {
            "sequence_uuid": SEQ_UUID,
            "sequence_name": "test_seq",
            "sequence_label": "golden",
            "sequence_params": {"p": 1},
        },
    )
    act0 = make_action(exp_yml, 0, ext=ext)  # process_finish False
    (act0.parent / MISC).write_text("note", encoding="utf-8")
    if fmt == "legacy":
        (act0.parent / HLO).write_text("x", encoding="utf-8")
        act0.write_text(
            act0.read_text(encoding="utf-8")
            + f"files:\n- file_name: {HLO}\n  file_type: helao__file\n"
            + f"- file_name: {MISC}\n  file_type: aux__file\n",
            encoding="utf-8",
        )
    else:
        # A real pair whose read_hlo payload equals the legacy fake's.
        (act0.parent / "data-0.0.0.0__0.meta.json").write_text(
            dumps_meta({"k": "v"}), encoding="utf-8"
        )
        (act0.parent / JSONL).write_text('{"t_s": 0.0, "value": 1.0}\n', encoding="utf-8")
        write_yml(
            act0,
            {
                **act_meta(0),
                "files": [
                    {"file_name": JSONL, "file_type": "helao__file"},
                    {"file_name": MISC, "file_type": "aux__file"},
                ],
            },
        )
    act1 = make_action(exp_yml, 1, process_finish=True, ext=ext)
    # Controller ruling: rewrite the whole yml from a merged dict instead of
    # appending duplicate `technique_name`/`action_split` keys as raw text --
    # the append made yml_load raise DuplicateKeyError.
    write_yml(
        act1,
        {
            **act_meta(1, True),
            "technique_name": ["tech_a", "tech_b"],
            "action_split": 1,
        },
    )
    return seq_yml, exp_yml, act0, act1
```

Change `test_default_chain_golden`:

```python
@pytest.mark.parametrize("fmt", ["legacy", "new"])
@pytest.mark.parametrize("mod", [native_mod])
@pytest.mark.asyncio
async def test_default_chain_golden(tmp_path, mod, monkeypatch, fmt):
    if fmt == "legacy":
        fake_hlo = lambda fp: ({"k": "v"}, {"t_s": [0.0], "value": [1.0]})  # noqa: E731
        monkeypatch.setattr(mod, "read_hlo", fake_hlo, raising=False)
        if s3_upload_mod is not None:
            monkeypatch.setattr(s3_upload_mod, "read_hlo", fake_hlo)
    local = HLO if fmt == "legacy" else JSONL
```

then `seq_yml, exp_yml, act0, act1 = _build_tree(tmp_path, fmt)`, and in the `act0_prg` expectation `HLO: f"raw_data/{ACT0_UUID}/{HLO}.json",` -> `local: f"raw_data/{ACT0_UUID}/{HLO}.json",`. Every other literal — S3 key set, per-step ordered keys, raw_data body, all four record bodies by ordered equality, the experiment `.prg` — stays as it is: that equality across both params **is** the spec's "S3 keys, payload JSON and renamed `files[]` equal to the legacy-record run".

- [ ] **Step 4: Run**

Run: `PYTHONPATH=$PWD python -m pytest helao/core/tests/test_mixed_tree_readers.py helao/core/tests/test_sync_postfinish_golden.py harness/tests -q`
Expected: PASS (5 parity cases, 2 golden params, harness suite unchanged).

- [ ] **Step 5: Commit**

```bash
F="harness/tests/synthtree.py helao/core/tests/test_mixed_tree_readers.py helao/hexagon/tests/sync_fixtures.py helao/core/tests/test_sync_postfinish_golden.py"
black $F && pyright $F
git -C /mnt/STORAGE/repos/helao/helao-async add $F
git -C /mnt/STORAGE/repos/helao/helao-async commit -m "test: mixed-tree reader parity and SYNC golden on a JSON-format record"
```

---

### Task 14: Gate

**Files:** none modified (fixes found here go back to the owning task's files and get their own commit).

- [ ] **Step 1: Full sweep after (two background commands, marker file)**

Job (`run_in_background: true`):

```bash
D="${CLAUDE_JOB_DIR:-$HOME/.cache/helao-json-storage}/json-storage"; rm -f "$D/after.done"
cd /mnt/STORAGE/repos/helao/helao-async && ( PYTHONPATH=$PWD python run_tests.py > "$D/after.log" 2>&1; echo $? > "$D/after.done" )
```

Watcher (`run_in_background: true`, separate command):

```bash
D="${CLAUDE_JOB_DIR:-$HOME/.cache/helao-json-storage}/json-storage"
for i in $(seq 1 720); do [ -f "$D/after.done" ] && break; sleep 15; done; echo "rc=$(cat "$D/after.done" 2>/dev/null || echo TIMEOUT)"; tail -5 "$D/after.log"
```

When the watcher fires, at once:

```bash
D="${CLAUDE_JOB_DIR:-$HOME/.cache/helao-json-storage}/json-storage"
grep -E '^\s+(FAIL|TIMEOUT)\s' "$D/after.log" | awk '{print $2}' | sort -u > "$D/after.fail"
echo "new failures:"; comm -13 "$D/baseline.fail" "$D/after.fail"
cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD python run_unit_tests.py > "$D/after.unit.log" 2>&1; echo "unit rc=$?"
```

Expected: `new failures:` followed by nothing; `unit rc=0` (or the same rc and failures as `baseline.unit.log`). Any new failure goes back to its owning task; do not proceed with one open.

- [ ] **Step 2: pyright on every changed Python file (parent + nested repos)**

```bash
D="${CLAUDE_JOB_DIR:-$HOME/.cache/helao-json-storage}/json-storage"
cd /mnt/STORAGE/repos/helao/helao-async
pyright $(git -C . diff --name-only "$(cat "$D/parent.sha")"..HEAD -- '*.py')
while read -r dir sha; do
  ( cd "helao/deploy/$dir" && files=$(git -C . diff --name-only "$sha"..HEAD -- '*.py'); [ -n "$files" ] && pyright $files )
done < "$D/nested.sha"
```

Expected: `0 errors` for each invocation, and a non-zero "files analyzed" count (a 0-file run is vacuous, not clean).

- [ ] **Step 3: Simulated group writes a new-format run that SYNC ships (GM-1 parity against the Task 0 capture)**

Same procedure as Task 0 Step 5 (re-check `grep -n '/mnt/' helao/deploy/test/configs/golden.yml` returns nothing), launching in the background and capturing to `gm1-post`:

```bash
D="${CLAUDE_JOB_DIR:-$HOME/.cache/helao-json-storage}/json-storage"
rm -rf /tmp/helao-golden
cd /mnt/STORAGE/repos/helao/helao-async && setsid bash -c 'echo $$ > "'"$D"'/group.pid"; exec script -qfec "./helao.sh golden --no-hot-reload" /dev/null' > "$D/group-post.log" 2>&1
```

```bash
D="${CLAUDE_JOB_DIR:-$HOME/.cache/helao-json-storage}/json-storage"
cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD timeout 900 python -m harness.capture --scenario GM-1 --root /tmp/helao-golden --out "$D/gm1-post" --config-prefix golden --notes "json-storage after"
kill -TERM -- -"$(cat "$D/group.pid")"; sleep 10
echo "legacy names (must be empty):"; find /tmp/helao-golden/RUNS -name '*.hlo' -o -name '*-act.yml' -o -name '*-exp.yml' -o -name '*-seq.yml'
echo "new names:"; find /tmp/helao-golden/RUNS -name '*-act.json' | head -3; find /tmp/helao-golden/RUNS -name '*.jsonl' | head -3
echo "S3 raw_data:"; find /tmp/helao-golden/S3_SIM -path '*raw_data*' -name '*.hlo.json*' | head -3
echo "synced records:"; grep -l '^synced: true' $(find /tmp/helao-golden/RUNS -name '*.prg') | wc -l
PYTHONPATH=$PWD python -m harness.parity --golden "$D/gm1-pre" --candidate "$D/gm1-post" --report "$D/gm1-parity.json"; echo "parity rc=$?"
```

Expected: no legacy names; `-act.json` and `.jsonl` present; `raw_data/<uuid>/X.hlo.json` present in `S3_SIM`; every `.prg` reports `synced: true`; `parity rc=0` — the legacy-format golden and the JSON-format capture are normalized-identical, record bodies and S3 payloads included. If the S3 key under `S3_SIM` is laid out differently (e.g. bucket prefix), adjust only the `find -path` filter, not the expectation.

- [ ] **Step 4: Public-repo hygiene**

```bash
D="${CLAUDE_JOB_DIR:-$HOME/.cache/helao-json-storage}/json-storage"
cd /mnt/STORAGE/repos/helao/helao-async
# PRIVATE_DIRS_RE is an alternation of the private deployment directory names,
# supplied in the task prompt (never written into a tracked file).
git -C . diff "$(cat "$D/parent.sha")"..HEAD | grep -nE "^\+.*\b(${PRIVATE_DIRS_RE})\b" ; echo "rc=$? (1 = clean)"
git -C . status --short
```

Expected: `rc=1`; `status` shows only the parallel session's hte files from `status.before`. A reviewer pass (separate from the author) audits the parent diff for private deployment names before anything is pushed.

- [ ] **Step 5: Hand-off**

Report to the user: the parent and nested commit ranges, `comm` output (empty), pyright summary, the GM-1 parity report path, and `$D/golden-master-check.txt` (Task 12 re-freeze evidence). Pushing and PRs happen only on the user's word.

---

## Deviations from the spec and open items

- **Extra helpers** (justified in Global Constraints): `RECORD_KINDS`, `data_sibling`, `resolve_meta_path`, `read_hlo_via`, `top_level_pair`.
- **`int()` placement:** spec §1 names the `s3_upload` sort and `sync_driver` ~2615-2640 sites. Both read keys that originate in one place, `Progress.__init__`'s copy of `process_order_groups` into the `.prg`; Task 6 casts there once. A `.prg` written before this change already holds int keys (it is YAML).
- **String data headers:** spec §1 defines list -> `{"text": ...}` and the `gamry_server2` fix, but not other str headers. Task 11 parses a str header as the YAML mapping it spells (what `read_hlo` returned for it before), else `{"text": str}`, so any remaining str-header caller keeps its S3 `meta`.
- **Sites the spec does not list but the format change reaches** (all included): `helao/helpers/yml_tools.move_dir` (builds the `/finish_yml` path), `MicroOrch._candidate_yml`, `HelaoYml.write_meta`, `harness/parity.py`/`normalize.py` (no edit: they dispatch through the updated loaders), `harness/capture.py` quiesce probe, `harness/s3_pass.py`, the `test_active_golden_master` comparator and reference re-freeze, and in Deployment-C `batch_converter` (`-seq` glob and `remove_stale_prgs`, which would otherwise delete every `.prg` beside a JSON record), `processing_recovery`, `sequence_identity`, `ecms_ms/calibration`.
- **Left legacy-only, flagged for a follow-up decision:** the core repair tools `helao/core/tests/{set_run_use,set_plate_id,_record_rewrite,scan_prg_ghosts}.py` and `audit_upload_sets.py` read and rewrite `.yml` members only; on a JSON-era record they find no `-seq.yml` and refuse (fail closed, nothing written). `harness/mutate.py` mutates legacy goldens only. The `hexagon/tests/smoke/golden_capture_*.py` station capture scripts settle on `-act.yml`; they run only against a live station and are not part of the sweep.
