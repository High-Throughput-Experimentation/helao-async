# Data Browser Visualizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a config-enabled Bokeh visualizer that browses finished/derived HELAO data on disk (`RUNS_FINISHED`, `RUNS_SYNCED`, `PROCESSES`, `ANALYSES`), overlays arbitrary datasets on one plot with free axis assignment, and shows a linked filterable plot/table tab view.

**Architecture:** A deployment-agnostic package `helao/core/servers/data_browser/` split into four focused modules — `readers.py` (extension-dispatched file → `{column: list}` loader), `sources.py` (date-scoped indexers for each source that emit a uniform pandas index of candidate datasets), `state.py` (pure selection/axis/trace/summary logic), and `app.py` (`build_document(vis)` that builds the Bokeh UI and wires callbacks to the pure logic). Thin `makeBokehApp` shims under `hte` and `test` deployments delegate to `app.build_document`. Scoping is done by cheap `YY.WW/MMDD` directory listing rather than globbing whole roots.

**Tech Stack:** Python 3.12, Bokeh 3.9 (`from bokeh.models import Tabs, TabPanel, ...`), pandas 3.0, pyarrow 24, numpy 1.26; existing helpers `helao.helpers.hlo_data.read_hlo_bytes`, `helao.core.servers.vis.HelaoVis`/`Vis`. No pytest in repo — tests are standalone assert-based functions run with `conda run -n helao python`.

**Conventions for every command below:**
- Run from repo root `/mnt/STORAGE/repos/helao/helao-async`.
- Prefix Python with `PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao`.
- All commits land on the already-created branch `feat/data-browser-visualizer`.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `helao/core/servers/data_browser/__init__.py` | Package marker; re-export `build_document`. |
| `helao/core/servers/data_browser/readers.py` | Locator parsing + `read_dataset(locator, fmt)` for `.hlo`/`.json`/`.parquet`, loose files and zip members. |
| `helao/core/servers/data_browser/sources.py` | `INDEX_COLUMNS`, dir-walk helpers, `RunsSourceIndex`, `DerivedSourceIndex`, `build_source_index`, `get_index`. |
| `helao/core/servers/data_browser/state.py` | `SelectedDataset`, `available_columns`, `build_trace`, `downsample`, `summary_row`, `SUMMARY_COLS`, `load_selected`. |
| `helao/core/servers/data_browser/app.py` | `build_document(vis)` — Bokeh widgets, layout, callbacks. |
| `helao/deploy/hte/servers/visualizer/data_browser.py` | `makeBokehApp` shim (production). |
| `helao/deploy/test/servers/visualizer/data_browser.py` | `makeBokehApp` shim (sim/demo). |
| `helao/deploy/test/tests/__init__.py` | Package marker for the test dir. |
| `helao/deploy/test/tests/test_data_browser.py` | Fixture builders + assert-based tests + `__main__` runner. |
| `helao/deploy/test/configs/test.yml` | Add a `DATABROWSE` visualizer server entry (modify). |

**Uniform index schema** (every source emits these exact DataFrame columns):
```
source, sequence, experiment, node, technique, sample, run_type,
file_name, file_type, date, available, locator
```
- `source`: one of `RUNS_FINISHED`, `RUNS_SYNCED`, `PROCESSES`, `ANALYSES`.
- `file_type`: `hlo` | `json` | `parquet` (drives the reader `fmt` hint).
- `available`: `False` when the data file is not present locally (greyed, non-selectable).
- `locator`: a loose absolute path, or `zip::<zip_path>::<member>` for a zip member, or `""` when unavailable.

---

## Task 1: Package scaffold + `.hlo` reader

**Files:**
- Create: `helao/core/servers/data_browser/__init__.py`
- Create: `helao/core/servers/data_browser/readers.py`
- Create: `helao/deploy/test/tests/__init__.py`
- Create: `helao/deploy/test/tests/test_data_browser.py`

- [ ] **Step 1: Write the failing test**

Create `helao/deploy/test/tests/__init__.py` as an empty file, and create `helao/deploy/test/tests/test_data_browser.py`:

```python
"""Standalone tests for the data_browser package. No pytest; run with:

    PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao \
        python -m helao.deploy.test.tests.test_data_browser
"""
import io
import json
import os
import tempfile
import zipfile

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from helao.core.servers.data_browser import readers


def _write_hlo(path):
    """Write a minimal HLO file (YAML header, %% marker, JSONL body)."""
    with open(path, "w") as f:
        f.write("hlo_version: 1.0\n")
        f.write("action_name: cv\n")
        f.write("column_headings: [t_s, Ewe_V]\n")
        f.write("%%\n")
        f.write(json.dumps({"t_s": 0.0, "Ewe_V": 0.1}) + "\n")
        f.write(json.dumps({"t_s": 1.0, "Ewe_V": 0.2}) + "\n")


def test_read_hlo_file():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "cv_data.hlo")
        _write_hlo(p)
        meta, data = readers.read_dataset(p)
        assert data["t_s"] == [0.0, 1.0], data
        assert data["Ewe_V"] == [0.1, 0.2], data
    print("test_read_hlo_file PASS")


if __name__ == "__main__":
    test_read_hlo_file()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao python -m helao.deploy.test.tests.test_data_browser`
Expected: FAIL — `ModuleNotFoundError: No module named 'helao.core.servers.data_browser'`.

- [ ] **Step 3: Write minimal implementation**

Create `helao/core/servers/data_browser/__init__.py`:

```python
"""Post-hoc on-disk data browser visualizer for HELAO."""
```

Create `helao/core/servers/data_browser/readers.py`:

```python
"""Extension-dispatched dataset readers for the data browser.

A *locator* identifies one column-bearing data file:

- loose file: an absolute filesystem path, e.g. ``/data/.../cv_data.hlo``
- zip member: ``"zip::<zip_path>::<member_name>"``

``read_dataset(locator, fmt)`` returns ``(meta, data)`` where ``meta`` is a dict
of header/metadata and ``data`` is ``{column_name: list}``. ``fmt`` (one of
``"hlo"``, ``"json"``, ``"parquet"``) overrides extension-based dispatch; pass it
for files whose extension does not match their format (e.g. analysis JSON outputs
named after an S3 key).
"""
import io
import json
import os
import zipfile
from typing import Tuple

import pyarrow.parquet as pq

from helao.helpers.hlo_data import read_hlo_bytes

ZIP_PREFIX = "zip::"
ZIP_SEP = "::"


def make_zip_locator(zip_path: str, member: str) -> str:
    return f"{ZIP_PREFIX}{zip_path}{ZIP_SEP}{member}"


def parse_locator(locator: str):
    """Return ('file', path) or ('zip', zip_path, member)."""
    if locator.startswith(ZIP_PREFIX):
        zip_path, member = locator[len(ZIP_PREFIX):].split(ZIP_SEP, 1)
        return ("zip", zip_path, member)
    return ("file", locator)


def _read_bytes(locator: str) -> Tuple[str, bytes]:
    """Return (file_name, content_bytes) for any locator."""
    parsed = parse_locator(locator)
    if parsed[0] == "zip":
        _, zip_path, member = parsed
        with zipfile.ZipFile(zip_path) as zf:
            return os.path.basename(member), zf.read(member)
    with open(parsed[1], "rb") as f:
        return os.path.basename(parsed[1]), f.read()


def read_dataset(locator: str, fmt: str = None) -> Tuple[dict, dict]:
    """Read any supported column-bearing file into (meta, {column: list})."""
    file_name, content = _read_bytes(locator)
    if fmt is None:
        fmt = os.path.splitext(file_name)[1].lower().lstrip(".")
    if fmt == "hlo":
        return read_hlo_bytes(content)
    if fmt == "json":
        return _read_json(content)
    if fmt == "parquet":
        return _read_parquet(content)
    raise ValueError(f"unsupported data format: {fmt!r} ({file_name})")


def _read_json(content: bytes) -> Tuple[dict, dict]:
    """Parse a JSON data file into (meta, {column: list})."""
    obj = json.loads(content.decode("utf-8"))
    if isinstance(obj, dict):
        data = {k: list(v) for k, v in obj.items() if isinstance(v, (list, tuple))}
        meta = {k: v for k, v in obj.items() if k not in data}
        return meta, data
    if isinstance(obj, list):
        cols = {}
        for rec in obj:
            if isinstance(rec, dict):
                for k, v in rec.items():
                    cols.setdefault(k, []).append(v)
        return {}, cols
    return {}, {}


def _read_parquet(content: bytes) -> Tuple[dict, dict]:
    table = pq.read_table(io.BytesIO(content))
    data = {name: table.column(name).to_pylist() for name in table.column_names}
    meta = {}
    raw = (table.schema.metadata or {}).get(b"helao_metadata")
    if raw:
        try:
            meta = json.loads(raw.decode("utf-8"))
        except Exception:
            meta = {}
    return meta, data
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao python -m helao.deploy.test.tests.test_data_browser`
Expected: `test_read_hlo_file PASS`

- [ ] **Step 5: Commit**

```bash
git add helao/core/servers/data_browser/__init__.py \
        helao/core/servers/data_browser/readers.py \
        helao/deploy/test/tests/__init__.py \
        helao/deploy/test/tests/test_data_browser.py
git commit -m "feat(data_browser): package scaffold and .hlo dataset reader"
```

---

## Task 2: JSON and Parquet readers + zip member reading

**Files:**
- Modify: `helao/deploy/test/tests/test_data_browser.py`
- (readers already implemented in Task 1; this task proves json/parquet/zip paths)

- [ ] **Step 1: Write the failing tests**

Add to `helao/deploy/test/tests/test_data_browser.py` (after `test_read_hlo_file`):

```python
def test_read_json_columnar():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "out.json")
        with open(p, "w") as f:
            json.dump({"wl_nm": [400, 500], "abs": [0.1, 0.2], "note": "x"}, f)
        meta, data = readers.read_dataset(p, fmt="json")
        assert data == {"wl_nm": [400, 500], "abs": [0.1, 0.2]}, data
        assert meta == {"note": "x"}, meta
    print("test_read_json_columnar PASS")


def test_read_json_records():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "recs.json")
        with open(p, "w") as f:
            json.dump([{"a": 1, "b": 2}, {"a": 3, "b": 4}], f)
        _, data = readers.read_dataset(p, fmt="json")
        assert data == {"a": [1, 3], "b": [2, 4]}, data
    print("test_read_json_records PASS")


def test_read_parquet():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "pat.parquet")
        table = pa.table({"q": [1.0, 2.0], "I": [10.0, 20.0]})
        pq.write_table(table, p)
        _, data = readers.read_dataset(p)
        assert data == {"q": [1.0, 2.0], "I": [10.0, 20.0]}, data
    print("test_read_parquet PASS")


def test_read_hlo_from_zip():
    with tempfile.TemporaryDirectory() as d:
        hlo = os.path.join(d, "cv_data.hlo")
        _write_hlo(hlo)
        zip_path = os.path.join(d, "seq.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.write(hlo, "exp/act/cv_data.hlo")
        loc = readers.make_zip_locator(zip_path, "exp/act/cv_data.hlo")
        _, data = readers.read_dataset(loc, fmt="hlo")
        assert data["t_s"] == [0.0, 1.0], data
    print("test_read_hlo_from_zip PASS")
```

Update the `__main__` block to call all four new tests as well:

```python
if __name__ == "__main__":
    test_read_hlo_file()
    test_read_json_columnar()
    test_read_json_records()
    test_read_parquet()
    test_read_hlo_from_zip()
```

- [ ] **Step 2: Run tests to verify they fail or pass**

Run: `PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao python -m helao.deploy.test.tests.test_data_browser`
Expected: All four new lines print `PASS` (the readers were written in Task 1; if any fails, fix `readers.py` until green).

- [ ] **Step 3: Commit**

```bash
git add helao/deploy/test/tests/test_data_browser.py
git commit -m "test(data_browser): cover json, parquet, and zip-member readers"
```

---

## Task 3: Index schema + dir-walk helpers

**Files:**
- Create: `helao/core/servers/data_browser/sources.py`
- Modify: `helao/deploy/test/tests/test_data_browser.py`

- [ ] **Step 1: Write the failing test**

Add to `test_data_browser.py`:

```python
from helao.core.servers.data_browser import sources


def test_dir_walk_and_range():
    with tempfile.TemporaryDirectory() as d:
        base = os.path.join(d, "RUNS_FINISHED")
        for ww, mmdd in [("26.20", "0515"), ("26.25", "0618")]:
            os.makedirs(os.path.join(base, ww, mmdd))
        dates = [ds for ds, _ in sources._list_day_dirs(base)]
        assert dates == ["26.20/0515", "26.25/0618"], dates
        assert sources._in_range("26.25/0618", "26.22", "26.30") is True
        assert sources._in_range("26.20/0515", "26.22", "26.30") is False
        assert sources._in_range("26.25/0618", None, None) is True
    print("test_dir_walk_and_range PASS")
```

Add `test_dir_walk_and_range()` to `__main__`.

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao python -m helao.deploy.test.tests.test_data_browser`
Expected: FAIL — `ImportError: cannot import name 'sources'` or `AttributeError: _list_day_dirs`.

- [ ] **Step 3: Write minimal implementation**

Create `helao/core/servers/data_browser/sources.py`:

```python
"""Date-scoped indexers that emit a uniform candidate-dataset index.

Each source indexer walks the cheap ``YY.WW/MMDD`` directory layout, scoped to a
date range, and returns a pandas DataFrame with :data:`INDEX_COLUMNS`. Reading a
row's data is done separately via ``readers.read_dataset(row.locator, row.file_type)``.
"""
import posixpath
import zipfile
from pathlib import Path

import pandas as pd
import yaml

from helao.core.servers.data_browser.readers import make_zip_locator

INDEX_COLUMNS = [
    "source", "sequence", "experiment", "node", "technique", "sample",
    "run_type", "file_name", "file_type", "date", "available", "locator",
]

DATA_EXTS = (".hlo", ".json", ".parquet")


def _list_day_dirs(base):
    """Yield (date_str, day_path) for each YY.WW/MMDD under base, sorted."""
    base = Path(base)
    if not base.is_dir():
        return
    for ww in sorted(p.name for p in base.iterdir() if p.is_dir()):
        wwp = base / ww
        for mmdd in sorted(p.name for p in wwp.iterdir() if p.is_dir()):
            yield f"{ww}/{mmdd}", wwp / mmdd


def _in_range(date_str, start, end):
    """Lexicographic YY.WW/MMDD range test; None bounds are open."""
    if start and date_str < start:
        return False
    if end and date_str > end:
        return False
    return True


def _seq_name(dirname):
    """Extract the human-readable sequence name from a YY dir name."""
    parts = dirname.split("__")
    return parts[1] if len(parts) > 1 else dirname


def _first_sample(meta):
    """Return the first global_label found in an action/process yml dict."""
    for key in ("samples_out", "samples_in"):
        for s in meta.get(key) or []:
            lbl = (s or {}).get("global_label") if isinstance(s, dict) else None
            if lbl:
                return lbl
    return ""


def _safe_yaml(path):
    try:
        with open(path, "r") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _safe_yaml_bytes(content):
    try:
        return yaml.safe_load(content) or {}
    except Exception:
        return {}


def _row(**kw):
    """Build one index row dict with all INDEX_COLUMNS present."""
    return {c: kw.get(c, "") for c in INDEX_COLUMNS}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao python -m helao.deploy.test.tests.test_data_browser`
Expected: `test_dir_walk_and_range PASS`

- [ ] **Step 5: Commit**

```bash
git add helao/core/servers/data_browser/sources.py helao/deploy/test/tests/test_data_browser.py
git commit -m "feat(data_browser): index schema and date-scoped dir-walk helpers"
```

---

## Task 4: `RunsSourceIndex` — unzipped `RUNS_FINISHED` tree

**Files:**
- Modify: `helao/core/servers/data_browser/sources.py`
- Modify: `helao/deploy/test/tests/test_data_browser.py`

- [ ] **Step 1: Write the failing test**

Add to `test_data_browser.py`:

```python
def _make_finished_tree(root):
    """Create root/RUNS_FINISHED/26.25/0618/<seq>/<exp>/<act>/ with an .hlo + act.yml."""
    act_dir = os.path.join(
        root, "RUNS_FINISHED", "26.25", "0618",
        "141523__SDC_seq__lab1", "260618.141524__SDC_exp_CV",
        "1__0__sim__cv",
    )
    os.makedirs(act_dir)
    _write_hlo(os.path.join(act_dir, "cv_data.hlo"))
    with open(os.path.join(act_dir, "260618.141525-act.yml"), "w") as f:
        yaml.safe_dump({
            "technique_name": "CV",
            "run_type": "data",
            "samples_out": [{"global_label": "solid__lab1_1"}],
        }, f)


def test_runs_finished_index():
    import yaml  # noqa: F401 (used by _make_finished_tree)
    with tempfile.TemporaryDirectory() as d:
        _make_finished_tree(d)
        idx = sources.RunsSourceIndex(d, "FINISHED")
        df = idx.index()
        assert list(df.columns) == sources.INDEX_COLUMNS, list(df.columns)
        assert len(df) == 1, df
        r = df.iloc[0]
        assert r["source"] == "RUNS_FINISHED"
        assert r["sequence"] == "SDC_seq"
        assert r["technique"] == "CV"
        assert r["sample"] == "solid__lab1_1"
        assert r["file_name"] == "cv_data.hlo"
        assert r["file_type"] == "hlo"
        assert r["available"] is True
        _, data = readers.read_dataset(r["locator"], r["file_type"])
        assert data["t_s"] == [0.0, 1.0]
    print("test_runs_finished_index PASS")
```

Add `import yaml` to the top of the test file (alongside the other imports) and add `test_runs_finished_index()` to `__main__`.

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao python -m helao.deploy.test.tests.test_data_browser`
Expected: FAIL — `AttributeError: module ... has no attribute 'RunsSourceIndex'`.

- [ ] **Step 3: Write minimal implementation**

Append to `helao/core/servers/data_browser/sources.py`:

```python
class SourceIndex:
    """Base class for a date-scoped candidate-dataset indexer."""

    def list_dates(self):
        raise NotImplementedError

    def index(self, date_start=None, date_end=None):
        raise NotImplementedError


class RunsSourceIndex(SourceIndex):
    """Index RUNS_FINISHED (unzipped trees) or RUNS_SYNCED (sequence zips)."""

    def __init__(self, root, state):
        # state is "FINISHED" or "SYNCED"
        self.root = Path(root)
        self.state = state
        self.source = f"RUNS_{state}"
        self.base = self.root / self.source

    def list_dates(self):
        return [d for d, _ in _list_day_dirs(self.base)]

    def index(self, date_start=None, date_end=None):
        rows = []
        for date_str, day in _list_day_dirs(self.base):
            if not _in_range(date_str, date_start, date_end):
                continue
            if self.state == "SYNCED":
                rows.extend(self._index_zips(date_str, day))
            else:
                rows.extend(self._index_tree(date_str, day))
        return pd.DataFrame(rows, columns=INDEX_COLUMNS)

    def _index_tree(self, date_str, day):
        rows = []
        for seq_dir in sorted(p for p in day.iterdir() if p.is_dir()):
            seq_name = _seq_name(seq_dir.name)
            for act_yml in sorted(seq_dir.glob("*/*-act.yml")):
                act_dir = act_yml.parent
                exp_name = act_dir.parent.name
                meta = _safe_yaml(act_yml)
                technique = meta.get("technique_name") or meta.get("action_name", "")
                sample = _first_sample(meta)
                run_type = meta.get("run_type", "")
                for f in sorted(act_dir.iterdir()):
                    if f.is_file() and f.suffix.lower() in DATA_EXTS:
                        rows.append(_row(
                            source=self.source, sequence=seq_name,
                            experiment=exp_name, node=act_dir.name,
                            technique=technique, sample=sample, run_type=run_type,
                            file_name=f.name, file_type=f.suffix.lower().lstrip("."),
                            date=date_str, available=True, locator=str(f),
                        ))
        return rows
```

(The `_index_zips` method is added in Task 5; until then `RunsSourceIndex(..., "SYNCED").index()` would raise `AttributeError`, which is fine — no test exercises SYNCED yet.)

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao python -m helao.deploy.test.tests.test_data_browser`
Expected: `test_runs_finished_index PASS`

- [ ] **Step 5: Commit**

```bash
git add helao/core/servers/data_browser/sources.py helao/deploy/test/tests/test_data_browser.py
git commit -m "feat(data_browser): index unzipped RUNS_FINISHED trees"
```

---

## Task 5: `RunsSourceIndex` — synced sequence zips

**Files:**
- Modify: `helao/core/servers/data_browser/sources.py`
- Modify: `helao/deploy/test/tests/test_data_browser.py`

- [ ] **Step 1: Write the failing test**

Add to `test_data_browser.py`:

```python
def _make_synced_zip(root):
    """Create root/RUNS_SYNCED/26.25/0618/<seq>.zip with act.yml + .hlo members."""
    day = os.path.join(root, "RUNS_SYNCED", "26.25", "0618")
    os.makedirs(day)
    with tempfile.TemporaryDirectory() as tmp:
        hlo = os.path.join(tmp, "cv_data.hlo")
        _write_hlo(hlo)
        actyml = os.path.join(tmp, "act.yml")
        with open(actyml, "w") as f:
            yaml.safe_dump({"technique_name": "CV",
                            "samples_out": [{"global_label": "solid__lab1_1"}]}, f)
        zpath = os.path.join(day, "141523__SDC_seq__lab1.zip")
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.write(actyml, "260618.141524__SDC_exp_CV/1__0__sim__cv/260618.141525-act.yml")
            zf.write(hlo, "260618.141524__SDC_exp_CV/1__0__sim__cv/cv_data.hlo")


def test_runs_synced_index():
    with tempfile.TemporaryDirectory() as d:
        _make_synced_zip(d)
        df = sources.RunsSourceIndex(d, "SYNCED").index()
        assert len(df) == 1, df
        r = df.iloc[0]
        assert r["source"] == "RUNS_SYNCED"
        assert r["sequence"] == "SDC_seq"
        assert r["technique"] == "CV"
        assert r["sample"] == "solid__lab1_1"
        assert r["file_name"] == "cv_data.hlo"
        assert r["locator"].startswith("zip::")
        _, data = readers.read_dataset(r["locator"], r["file_type"])
        assert data["Ewe_V"] == [0.1, 0.2]
    print("test_runs_synced_index PASS")
```

Add `test_runs_synced_index()` to `__main__`.

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao python -m helao.deploy.test.tests.test_data_browser`
Expected: FAIL — `AttributeError: 'RunsSourceIndex' object has no attribute '_index_zips'`.

- [ ] **Step 3: Write minimal implementation**

Append the `_index_zips` method inside the `RunsSourceIndex` class in `sources.py`:

```python
    def _index_zips(self, date_str, day):
        rows = []
        for zip_path in sorted(day.glob("*.zip")):
            seq_name = _seq_name(zip_path.stem)
            try:
                zf = zipfile.ZipFile(zip_path)
            except zipfile.BadZipFile:
                continue
            with zf:
                names = zf.namelist()
                act_meta = {}
                for n in names:
                    if n.endswith("-act.yml"):
                        act_meta[posixpath.dirname(n)] = _safe_yaml_bytes(zf.read(n))
                for n in names:
                    ext = posixpath.splitext(n)[1].lower()
                    if ext not in DATA_EXTS:
                        continue
                    actdir = posixpath.dirname(n)
                    meta = act_meta.get(actdir, {})
                    rows.append(_row(
                        source=self.source, sequence=seq_name,
                        experiment=posixpath.basename(posixpath.dirname(actdir)),
                        node=posixpath.basename(actdir),
                        technique=meta.get("technique_name") or meta.get("action_name", ""),
                        sample=_first_sample(meta), run_type=meta.get("run_type", ""),
                        file_name=posixpath.basename(n), file_type=ext.lstrip("."),
                        date=date_str, available=True,
                        locator=make_zip_locator(str(zip_path), n),
                    ))
        return rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao python -m helao.deploy.test.tests.test_data_browser`
Expected: `test_runs_synced_index PASS`

- [ ] **Step 5: Commit**

```bash
git add helao/core/servers/data_browser/sources.py helao/deploy/test/tests/test_data_browser.py
git commit -m "feat(data_browser): index synced sequence zips"
```

---

## Task 6: `DerivedSourceIndex` — PROCESSES

**Files:**
- Modify: `helao/core/servers/data_browser/sources.py`
- Modify: `helao/deploy/test/tests/test_data_browser.py`

PROCESS yml files live at `PROCESSES/YY.WW/MMDD/<seq>/<exp>/<idx>__<uuid>__<tech>-prc.yml` and reference data files by basename in their `files` list. We resolve each referenced basename back to the actual data file in `RUNS_FINISHED/<date>/<seq>/<exp>/.../` (or the synced zip), marking `available=False` when not found locally.

- [ ] **Step 1: Write the failing test**

Add to `test_data_browser.py`:

```python
def _make_process(root):
    """Create a -prc.yml referencing the .hlo created by _make_finished_tree."""
    prc_dir = os.path.join(
        root, "PROCESSES", "26.25", "0618",
        "141523__SDC_seq__lab1", "260618.141524__SDC_exp_CV",
    )
    os.makedirs(prc_dir)
    with open(os.path.join(prc_dir, "0__abc__CV-prc.yml"), "w") as f:
        yaml.safe_dump({
            "technique_name": "CV",
            "run_type": "data",
            "samples_out": [{"global_label": "solid__lab1_1"}],
            "files": [{"file_name": "cv_data.hlo", "file_type": "helao__file"}],
        }, f)


def test_processes_index_resolves_to_runs():
    with tempfile.TemporaryDirectory() as d:
        _make_finished_tree(d)   # the actual cv_data.hlo
        _make_process(d)         # the -prc.yml that references it
        df = sources.DerivedSourceIndex(d, "PROCESSES").index()
        assert len(df) == 1, df
        r = df.iloc[0]
        assert r["source"] == "PROCESSES"
        assert r["technique"] == "CV"
        assert r["sample"] == "solid__lab1_1"
        assert r["file_name"] == "cv_data.hlo"
        assert r["available"] is True
        _, data = readers.read_dataset(r["locator"], r["file_type"])
        assert data["t_s"] == [0.0, 1.0]


def test_processes_index_missing_file_unavailable():
    with tempfile.TemporaryDirectory() as d:
        _make_process(d)  # prc.yml but NO RUNS_FINISHED data
        df = sources.DerivedSourceIndex(d, "PROCESSES").index()
        assert len(df) == 1
        assert df.iloc[0]["available"] is False
        assert df.iloc[0]["locator"] == ""
    print("test_processes_index PASS")
```

Update `__main__` to call `test_processes_index_resolves_to_runs()` then `test_processes_index_missing_file_unavailable()`.

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao python -m helao.deploy.test.tests.test_data_browser`
Expected: FAIL — `AttributeError: module ... has no attribute 'DerivedSourceIndex'`.

- [ ] **Step 3: Write minimal implementation**

Append to `helao/core/servers/data_browser/sources.py`:

```python
def _resolve_run_file(root, date_str, seq_dirname, exp_dirname, file_name):
    """Locate a data file by basename under RUNS_FINISHED tree or RUNS_SYNCED zip.

    Returns (locator, available).
    """
    root = Path(root)
    fin_seq = root / "RUNS_FINISHED" / date_str / seq_dirname
    if fin_seq.is_dir():
        for cand in fin_seq.glob(f"{exp_dirname}/*/{file_name}"):
            return str(cand), True
        for cand in fin_seq.rglob(file_name):
            if cand.is_file():
                return str(cand), True
    zip_path = root / "RUNS_SYNCED" / date_str / f"{seq_dirname}.zip"
    if zip_path.is_file():
        try:
            with zipfile.ZipFile(zip_path) as zf:
                for n in zf.namelist():
                    if posixpath.basename(n) == file_name:
                        return make_zip_locator(str(zip_path), n), True
        except zipfile.BadZipFile:
            pass
    return "", False


class DerivedSourceIndex(SourceIndex):
    """Index PROCESSES (-prc.yml referencing run files) or ANALYSES (local outputs)."""

    def __init__(self, root, source):
        # source is "PROCESSES" or "ANALYSES"
        self.root = Path(root)
        self.source = source
        self.base = self.root / source

    def list_dates(self):
        return [d for d, _ in _list_day_dirs(self.base)]

    def index(self, date_start=None, date_end=None):
        rows = []
        for date_str, day in _list_day_dirs(self.base):
            if not _in_range(date_str, date_start, date_end):
                continue
            if self.source == "PROCESSES":
                rows.extend(self._index_processes(date_str, day))
            else:
                rows.extend(self._index_analyses(date_str, day))
        return pd.DataFrame(rows, columns=INDEX_COLUMNS)

    def _index_processes(self, date_str, day):
        rows = []
        for prc_yml in sorted(day.glob("*/*/*-prc.yml")):
            exp_dir = prc_yml.parent
            seq_dir = exp_dir.parent
            meta = _safe_yaml(prc_yml)
            technique = meta.get("technique_name", "")
            sample = _first_sample(meta)
            run_type = meta.get("run_type", "")
            for fi in meta.get("files") or []:
                fn = (fi or {}).get("file_name", "")
                if not fn or posixpath.splitext(fn)[1].lower() not in DATA_EXTS:
                    continue
                locator, available = _resolve_run_file(
                    self.root, date_str, seq_dir.name, exp_dir.name, fn)
                rows.append(_row(
                    source="PROCESSES", sequence=_seq_name(seq_dir.name),
                    experiment=exp_dir.name, node=prc_yml.stem,
                    technique=technique, sample=sample, run_type=run_type,
                    file_name=fn, file_type=posixpath.splitext(fn)[1].lower().lstrip("."),
                    date=date_str, available=available, locator=locator,
                ))
        return rows
```

(The `_index_analyses` method is added in Task 7; PROCESSES tests do not touch it.)

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao python -m helao.deploy.test.tests.test_data_browser`
Expected: `test_processes_index PASS`

- [ ] **Step 5: Commit**

```bash
git add helao/core/servers/data_browser/sources.py helao/deploy/test/tests/test_data_browser.py
git commit -m "feat(data_browser): index PROCESSES and resolve files to runs"
```

---

## Task 7: `DerivedSourceIndex` — ANALYSES (new local reader)

**Files:**
- Modify: `helao/core/servers/data_browser/sources.py`
- Modify: `helao/deploy/test/tests/test_data_browser.py`

Local analysis dirs are `ANALYSES/YY.WW/MMDD/<HHMMSS__name[__suffix]>/` containing `<uuid>.yml` (full `AnalysisModel`) plus one JSON file per output, named after `basename(analysis_output_path.key)`. An output is `available` when its local JSON exists; S3-only outputs are listed with `available=False`.

- [ ] **Step 1: Write the failing test**

Add to `test_data_browser.py`:

```python
def _make_analysis(root, with_local_output=True):
    ana_dir = os.path.join(root, "ANALYSES", "26.25", "0618", "150305__icpms__plate1")
    os.makedirs(ana_dir)
    with open(os.path.join(ana_dir, "uuid1234.yml"), "w") as f:
        yaml.safe_dump({
            "analysis_name": "icpms",
            "global_sample_label": "solid__lab1_1",
            "outputs": [{
                "analysis_output_path": {"bucket": "b", "key": "analysis/uuid1234/conc.json", "region": "r"},
                "content_type": "application/json",
                "output_type": "concentration",
                "output_name": "conc",
            }],
        }, f)
    if with_local_output:
        with open(os.path.join(ana_dir, "conc.json"), "w") as f:
            json.dump({"element": ["Ni", "Fe"], "ppm": [12.0, 3.4]}, f)


def test_analyses_index_local():
    with tempfile.TemporaryDirectory() as d:
        _make_analysis(d, with_local_output=True)
        df = sources.DerivedSourceIndex(d, "ANALYSES").index()
        assert len(df) == 1, df
        r = df.iloc[0]
        assert r["source"] == "ANALYSES"
        assert r["sequence"] == "icpms"
        assert r["sample"] == "solid__lab1_1"
        assert r["file_type"] == "json"
        assert r["available"] is True
        _, data = readers.read_dataset(r["locator"], r["file_type"])
        assert data["ppm"] == [12.0, 3.4]


def test_analyses_index_s3_only_unavailable():
    with tempfile.TemporaryDirectory() as d:
        _make_analysis(d, with_local_output=False)
        df = sources.DerivedSourceIndex(d, "ANALYSES").index()
        assert len(df) == 1
        assert df.iloc[0]["available"] is False
        assert df.iloc[0]["locator"] == ""
    print("test_analyses_index PASS")
```

Add both to `__main__`.

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao python -m helao.deploy.test.tests.test_data_browser`
Expected: FAIL — `AttributeError: 'DerivedSourceIndex' object has no attribute '_index_analyses'`.

- [ ] **Step 3: Write minimal implementation**

Append the `_index_analyses` method inside the `DerivedSourceIndex` class in `sources.py`:

```python
    def _index_analyses(self, date_str, day):
        rows = []
        for ana_dir in sorted(p for p in day.iterdir() if p.is_dir()):
            ymls = sorted(ana_dir.glob("*.yml"))
            meta = _safe_yaml(ymls[0]) if ymls else {}
            ana_name = meta.get("analysis_name", _seq_name(ana_dir.name))
            sample = meta.get("global_sample_label") or ""
            local_jsons = {p.name: p for p in ana_dir.glob("*.json")}
            outputs = meta.get("outputs") or []
            if outputs:
                for out in outputs:
                    key = ((out or {}).get("analysis_output_path") or {}).get("key", "")
                    fn = posixpath.basename(key) if key else ""
                    name = (out or {}).get("output_name") or fn
                    local = local_jsons.get(fn)
                    rows.append(_row(
                        source="ANALYSES", sequence=ana_name, experiment="",
                        node=name, technique=(out or {}).get("output_type", ""),
                        sample=sample, run_type="", file_name=fn or name,
                        file_type="json", date=date_str,
                        available=local is not None,
                        locator=str(local) if local is not None else "",
                    ))
            else:
                for fn, p in local_jsons.items():
                    rows.append(_row(
                        source="ANALYSES", sequence=ana_name, experiment="",
                        node=fn, technique="", sample=sample, run_type="",
                        file_name=fn, file_type="json", date=date_str,
                        available=True, locator=str(p),
                    ))
        return rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao python -m helao.deploy.test.tests.test_data_browser`
Expected: `test_analyses_index PASS`

- [ ] **Step 5: Commit**

```bash
git add helao/core/servers/data_browser/sources.py helao/deploy/test/tests/test_data_browser.py
git commit -m "feat(data_browser): local ANALYSES reader with S3-only detection"
```

---

## Task 8: `get_index` factory dispatch

**Files:**
- Modify: `helao/core/servers/data_browser/sources.py`
- Modify: `helao/deploy/test/tests/test_data_browser.py`

- [ ] **Step 1: Write the failing test**

Add to `test_data_browser.py`:

```python
def test_get_index_dispatch():
    with tempfile.TemporaryDirectory() as d:
        _make_finished_tree(d)
        df = sources.get_index(d, "RUNS_FINISHED", None, None)
        assert df.iloc[0]["source"] == "RUNS_FINISHED"
        empty = sources.get_index(d, "ANALYSES", None, None)
        assert list(empty.columns) == sources.INDEX_COLUMNS
        assert len(empty) == 0
    print("test_get_index_dispatch PASS")
```

Add `test_get_index_dispatch()` to `__main__`.

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao python -m helao.deploy.test.tests.test_data_browser`
Expected: FAIL — `AttributeError: module ... has no attribute 'get_index'`.

- [ ] **Step 3: Write minimal implementation**

Append to `helao/core/servers/data_browser/sources.py`:

```python
SOURCES = ["RUNS_FINISHED", "RUNS_SYNCED", "PROCESSES", "ANALYSES"]
GROUPS = {"RUNS": ["RUNS_FINISHED", "RUNS_SYNCED"],
          "DERIVED": ["PROCESSES", "ANALYSES"]}


def build_source_index(root, source):
    """Return the SourceIndex for a source name."""
    if source == "RUNS_FINISHED":
        return RunsSourceIndex(root, "FINISHED")
    if source == "RUNS_SYNCED":
        return RunsSourceIndex(root, "SYNCED")
    if source in ("PROCESSES", "ANALYSES"):
        return DerivedSourceIndex(root, source)
    raise ValueError(f"unknown source: {source!r}")


def get_index(root, source, date_start=None, date_end=None):
    """Build and return the candidate-dataset index DataFrame for a source."""
    return build_source_index(root, source).index(date_start, date_end)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao python -m helao.deploy.test.tests.test_data_browser`
Expected: `test_get_index_dispatch PASS`

- [ ] **Step 5: Commit**

```bash
git add helao/core/servers/data_browser/sources.py helao/deploy/test/tests/test_data_browser.py
git commit -m "feat(data_browser): source-index factory and get_index dispatch"
```

---

## Task 9: Selection state — datasets, axes, traces, summaries

**Files:**
- Create: `helao/core/servers/data_browser/state.py`
- Modify: `helao/deploy/test/tests/test_data_browser.py`

- [ ] **Step 1: Write the failing test**

Add to `test_data_browser.py`:

```python
from helao.core.servers.data_browser import state as dbstate


def _ds(label, data, **kw):
    base = dict(locator="L", source="RUNS_FINISHED", sequence="s", experiment="e",
                node="n", technique="CV", sample="smp", file_name="f.hlo", meta={})
    base.update(kw)
    return dbstate.SelectedDataset(label=label, data=data, **base)


def test_available_columns_union_sorted():
    a = _ds("a", {"t_s": [0, 1], "Ewe_V": [0.1, 0.2]})
    b = _ds("b", {"t_s": [0, 1], "I_A": [1, 2]})
    assert dbstate.available_columns([a, b]) == ["Ewe_V", "I_A", "t_s"]


def test_build_trace_and_downsample():
    a = _ds("a", {"t_s": [0, 1, 2, 3], "Ewe_V": [0.1, 0.2, 0.3, 0.4]})
    tr = dbstate.build_trace(a, "t_s", "Ewe_V")
    assert tr == {"x": [0, 1, 2, 3], "y": [0.1, 0.2, 0.3, 0.4]}
    assert dbstate.build_trace(a, "t_s", "missing") is None
    ds = dbstate.downsample(tr, 2)
    assert len(ds["x"]) <= 2 and ds["x"][0] == 0


def test_summary_row():
    a = _ds("a", {"t_s": [0, 1, 2], "Ewe_V": [0.1, 0.5, 0.3]})
    s = dbstate.summary_row(a, "t_s", "Ewe_V")
    assert s["n_points"] == 3
    assert s["x_min"] == 0 and s["x_max"] == 2
    assert s["y_min"] == 0.1 and s["y_max"] == 0.5
    assert s["source"] == "RUNS_FINISHED" and s["technique"] == "CV"
    print("test_state PASS")
```

Add `test_available_columns_union_sorted()`, `test_build_trace_and_downsample()`, `test_summary_row()` to `__main__`.

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao python -m helao.deploy.test.tests.test_data_browser`
Expected: FAIL — `ImportError: cannot import name 'state'`.

- [ ] **Step 3: Write minimal implementation**

Create `helao/core/servers/data_browser/state.py`:

```python
"""Pure selection/plot/table logic for the data browser (no Bokeh imports)."""
from dataclasses import dataclass

from helao.core.servers.data_browser.readers import read_dataset

SUMMARY_COLS = [
    "source", "sequence", "experiment", "node", "technique", "sample",
    "file_name", "n_points", "x_min", "x_max", "y_min", "y_max",
]


@dataclass
class SelectedDataset:
    locator: str
    label: str
    source: str
    sequence: str
    experiment: str
    node: str
    technique: str
    sample: str
    file_name: str
    meta: dict
    data: dict  # {column: list}

    @property
    def columns(self):
        return list(self.data.keys())


def available_columns(selected):
    """Sorted union of all column names across selected datasets."""
    cols = set()
    for ds in selected:
        cols.update(ds.columns)
    return sorted(cols)


def build_trace(ds, xcol, ycol):
    """Return {'x': [...], 'y': [...]} or None if either column is missing."""
    if xcol in ds.data and ycol in ds.data:
        x = list(ds.data[xcol])
        y = list(ds.data[ycol])
        n = min(len(x), len(y))
        return {"x": x[:n], "y": y[:n]}
    return None


def downsample(trace, max_points):
    """Uniformly downsample a trace dict to at most max_points."""
    n = len(trace["x"])
    if max_points and n > max_points:
        step = (n // max_points) + 1
        return {"x": trace["x"][::step], "y": trace["y"][::step]}
    return trace


def summary_row(ds, xcol, ycol):
    """One trace-summary row for the summary table."""
    x = ds.data.get(xcol, [])
    y = ds.data.get(ycol, [])
    n = min(len(x), len(y))

    def rng(v):
        nums = [z for z in v[:n] if isinstance(z, (int, float)) and not isinstance(z, bool)]
        return (min(nums), max(nums)) if nums else (None, None)

    xr, yr = rng(x), rng(y)
    return {
        "source": ds.source, "sequence": ds.sequence, "experiment": ds.experiment,
        "node": ds.node, "technique": ds.technique, "sample": ds.sample,
        "file_name": ds.file_name, "n_points": n,
        "x_min": xr[0], "x_max": xr[1], "y_min": yr[0], "y_max": yr[1],
    }


def load_selected(index_df, positions):
    """Read the chosen index rows (by integer position) into SelectedDataset list.

    Unavailable rows and unreadable files are skipped (logging is the caller's job).
    Returns (datasets, skipped) where skipped is a list of (label, reason).
    """
    datasets, skipped = [], []
    for pos in positions:
        row = index_df.iloc[pos]
        label = f"{row['source']}:{row['sequence']}/{row['node']}/{row['file_name']}"
        if not row["available"] or not row["locator"]:
            skipped.append((label, "not available locally"))
            continue
        try:
            meta, data = read_dataset(row["locator"], row["file_type"] or None)
        except Exception as exc:  # corrupt/unreadable file
            skipped.append((label, f"read error: {exc}"))
            continue
        datasets.append(SelectedDataset(
            locator=row["locator"], label=label, source=row["source"],
            sequence=row["sequence"], experiment=row["experiment"], node=row["node"],
            technique=row["technique"], sample=row["sample"],
            file_name=row["file_name"], meta=meta, data=data,
        ))
    return datasets, skipped
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao python -m helao.deploy.test.tests.test_data_browser`
Expected: `test_state PASS`

- [ ] **Step 5: Commit**

```bash
git add helao/core/servers/data_browser/state.py helao/deploy/test/tests/test_data_browser.py
git commit -m "feat(data_browser): selection state, axis union, trace/summary logic"
```

---

## Task 10: `load_selected` integration over a real index

**Files:**
- Modify: `helao/deploy/test/tests/test_data_browser.py`

- [ ] **Step 1: Write the failing test**

Add to `test_data_browser.py`:

```python
def test_load_selected_end_to_end():
    with tempfile.TemporaryDirectory() as d:
        _make_finished_tree(d)
        _make_process(d)  # adds an unavailable-resolves-to-available process row too
        df = sources.get_index(d, "RUNS_FINISHED", None, None)
        datasets, skipped = dbstate.load_selected(df, [0])
        assert len(datasets) == 1 and not skipped, (datasets, skipped)
        ds = datasets[0]
        assert ds.data["t_s"] == [0.0, 1.0]
        assert dbstate.available_columns(datasets) == ["Ewe_V", "t_s"]

        # an unavailable row is skipped, not loaded
        ana = sources.get_index(d, "ANALYSES", None, None)  # empty
        ds2, sk2 = dbstate.load_selected(ana, [])
        assert ds2 == [] and sk2 == []
    print("test_load_selected_end_to_end PASS")
```

Add `test_load_selected_end_to_end()` to `__main__`.

- [ ] **Step 2: Run test to verify it passes**

Run: `PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao python -m helao.deploy.test.tests.test_data_browser`
Expected: `test_load_selected_end_to_end PASS` (all prior logic already implemented; if it fails, fix `state.load_selected` / `sources` until green).

- [ ] **Step 3: Commit**

```bash
git add helao/deploy/test/tests/test_data_browser.py
git commit -m "test(data_browser): end-to-end index + load_selected"
```

---

## Task 11: Bokeh app — `build_document` (control bar + left index)

**Files:**
- Create: `helao/core/servers/data_browser/app.py`
- Modify: `helao/core/servers/data_browser/__init__.py`
- Modify: `helao/deploy/test/tests/test_data_browser.py`

This task builds the document skeleton: header, control bar (group/source/date/scan), and the left filterable index table. Plot and table tabs are wired in Tasks 12–13. A `_FakeVis` lets us smoke-test headlessly.

- [ ] **Step 1: Write the failing test**

Add to `test_data_browser.py` (top-level imports):

```python
from bokeh.document import Document


class _FakeDirs:
    def __init__(self, root):
        from pathlib import Path
        self.root = Path(root)
        self.log_root = None


class _FakeVis:
    def __init__(self, root, doc):
        self.world_cfg = {}
        self.helaodirs = _FakeDirs(root)
        self.doc = doc
        self.server_cfg = {"params": {"max_points": 50000}}

    def print_message(self, *a, **k):
        pass
```

And the test:

```python
def test_build_document_smoke():
    from helao.core.servers.data_browser.app import build_document
    with tempfile.TemporaryDirectory() as d:
        _make_finished_tree(d)
        doc = Document()
        vis = _FakeVis(d, doc)
        build_document(vis)
        assert len(doc.roots) >= 1, "build_document added no roots"
    print("test_build_document_smoke PASS")
```

Add `test_build_document_smoke()` to `__main__`.

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao python -m helao.deploy.test.tests.test_data_browser`
Expected: FAIL — `ModuleNotFoundError: No module named 'helao.core.servers.data_browser.app'`.

- [ ] **Step 3: Write minimal implementation**

Create `helao/core/servers/data_browser/app.py`:

```python
"""Bokeh document builder for the data browser visualizer."""
from functools import partial
from socket import gethostname

from bokeh.layouts import column, row
from bokeh.models import (
    Button, ColumnDataSource, DataTable, Div, MultiSelect, RadioButtonGroup,
    Select, Spacer, TableColumn, Tabs, TabPanel, TextInput,
)
from bokeh.palettes import Category10
from bokeh.plotting import figure

from helao.core.servers.data_browser import sources, state as dbstate

INDEX_TABLE_COLS = ["source", "sequence", "experiment", "node", "technique",
                    "sample", "run_type", "file_name", "file_type", "available"]
PALETTE = Category10[10]


def build_document(vis):
    """Build the data-browser UI on vis.doc. Returns vis.doc."""
    doc = vis.doc
    root = str(vis.helaodirs.root)
    params = (getattr(vis, "server_cfg", {}) or {}).get("params", {})
    max_points = params.get("max_points", 50000)

    ui = _UI(vis, root, max_points)
    doc.add_root(ui.layout)
    return doc


class _UI:
    """Holds widgets + mutable selection state and wires callbacks."""

    def __init__(self, vis, root, max_points):
        self.vis = vis
        self.root = root
        self.max_points = max_points
        self.index_df = None
        self.selected = []  # list[SelectedDataset]

        # --- header ---
        header = Div(
            text=f"<b>Data Browser on {gethostname().lower()}</b>",
            styles={"font-size": "180%", "color": "#2471A3"}, width=1000, height=32)

        # --- control bar ---
        self.group_sel = RadioButtonGroup(labels=list(sources.GROUPS.keys()), active=0)
        self.source_sel = Select(title="Source",
                                 options=sources.GROUPS["RUNS"],
                                 value=sources.GROUPS["RUNS"][0], width=160)
        self.date_start = TextInput(title="From (YY.WW/MMDD)", width=140)
        self.date_end = TextInput(title="To (YY.WW/MMDD)", width=140)
        self.scan_btn = Button(label="Scan", button_type="primary", width=80)
        self.status = Div(text="", width=600)

        self.group_sel.on_change("active", self._on_group_change)
        self.scan_btn.on_click(self._on_scan)

        control = row(self.group_sel, self.source_sel, self.date_start,
                      self.date_end, column(Spacer(height=18), self.scan_btn))

        # --- left index ---
        self.filter_in = TextInput(title="Filter index", width=300)
        self.filter_in.on_change("value", lambda a, o, n: self._refresh_index_table())
        self.index_source = ColumnDataSource(data={c: [] for c in INDEX_TABLE_COLS})
        self.index_table = DataTable(
            source=self.index_source,
            columns=[TableColumn(field=c, title=c) for c in INDEX_TABLE_COLS],
            width=460, height=380, selectable="checkbox")
        self.add_btn = Button(label="+ Add selected to plot",
                              button_type="success", width=300)
        self.clear_btn = Button(label="Clear plot", width=300)
        self.add_btn.on_click(self._on_add)
        self.clear_btn.on_click(self._on_clear)
        left = column(self.filter_in, self.index_table, self.add_btn, self.clear_btn)

        # --- right region (filled by Tasks 12-13) ---
        self.right = self._build_right()

        self.layout = column(header, control, row(left, self.right))

    # placeholder; replaced in Task 12
    def _build_right(self):
        return Div(text="(plot/table tabs added in later tasks)")

    # ---- callbacks ----
    def _current_source(self):
        return self.source_sel.value

    def _on_group_change(self, attr, old, new):
        group = list(sources.GROUPS.keys())[new]
        opts = sources.GROUPS[group]
        self.source_sel.options = opts
        self.source_sel.value = opts[0]

    def _on_scan(self):
        ds = self.date_start.value.strip() or None
        de = self.date_end.value.strip() or None
        try:
            self.index_df = sources.get_index(self.root, self._current_source(), ds, de)
        except Exception as exc:
            self.index_df = None
            self.status.text = f"<span style='color:#c0392b'>scan failed: {exc}</span>"
            self.vis.print_message(f"data_browser scan failed: {exc}", error=True)
            return
        self.status.text = f"indexed {len(self.index_df)} datasets from {self._current_source()}"
        self._refresh_index_table()

    def _filtered_df(self):
        if self.index_df is None:
            return None
        q = self.filter_in.value.strip().lower()
        if not q:
            return self.index_df
        cols = ["source", "sequence", "experiment", "node", "technique",
                "sample", "run_type", "file_name", "date"]
        mask = self.index_df[cols].astype(str).apply(
            lambda r: q in " ".join(r.values).lower(), axis=1)
        return self.index_df[mask]

    def _refresh_index_table(self):
        df = self._filtered_df()
        if df is None:
            self.index_source.data = {c: [] for c in INDEX_TABLE_COLS}
            return
        self.index_source.selected.indices = []
        self.index_source.data = {c: list(df[c].astype(str)) for c in INDEX_TABLE_COLS}

    def _on_add(self):
        df = self._filtered_df()
        if df is None:
            return
        picks = list(self.index_source.selected.indices)
        datasets, skipped = dbstate.load_selected(df.reset_index(drop=True), picks)
        self.selected.extend(datasets)
        for label, reason in skipped:
            self.vis.print_message(f"data_browser skipped {label}: {reason}")
        self._on_selection_changed()

    def _on_clear(self):
        self.selected = []
        self._on_selection_changed()

    # replaced/extended in Tasks 12-13
    def _on_selection_changed(self):
        self.status.text = f"{len(self.selected)} dataset(s) selected"
```

Update `helao/core/servers/data_browser/__init__.py`:

```python
"""Post-hoc on-disk data browser visualizer for HELAO."""
from helao.core.servers.data_browser.app import build_document  # noqa: F401
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao python -m helao.deploy.test.tests.test_data_browser`
Expected: `test_build_document_smoke PASS`

- [ ] **Step 5: Commit**

```bash
git add helao/core/servers/data_browser/app.py helao/core/servers/data_browser/__init__.py \
        helao/deploy/test/tests/test_data_browser.py
git commit -m "feat(data_browser): bokeh document skeleton with control bar and index"
```

---

## Task 12: Plot tab — axis pickers + overlaid traces

**Files:**
- Modify: `helao/core/servers/data_browser/app.py`
- Modify: `helao/deploy/test/tests/test_data_browser.py`

- [ ] **Step 1: Write the failing test**

Add to `test_data_browser.py` a test that drives the UI logic directly (bypassing the browser) by constructing `_UI` and calling its callbacks:

```python
def test_plot_tab_builds_traces():
    from helao.core.servers.data_browser.app import _UI
    with tempfile.TemporaryDirectory() as d:
        _make_finished_tree(d)
        doc = Document()
        vis = _FakeVis(d, doc)
        ui = _UI(vis, d, 50000)
        ui.index_df = sources.get_index(d, "RUNS_FINISHED", None, None)
        ui._refresh_index_table()
        ui.index_source.selected.indices = [0]
        ui._on_add()
        assert len(ui.selected) == 1
        # axes were populated from the loaded dataset
        assert set(ui.x_sel.options) == {"t_s", "Ewe_V"}
        ui.x_sel.value, ui.y_sel.value = "t_s", "Ewe_V"
        ui._rebuild_plot()
        assert len(ui.plot.renderers) == 1, ui.plot.renderers
    print("test_plot_tab_builds_traces PASS")
```

Add `test_plot_tab_builds_traces()` to `__main__`.

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao python -m helao.deploy.test.tests.test_data_browser`
Expected: FAIL — `AttributeError: '_UI' object has no attribute 'x_sel'` (or `_rebuild_plot`).

- [ ] **Step 3: Write minimal implementation**

In `app.py`, replace `_build_right` and extend `_on_selection_changed`, and add axis widgets + `_rebuild_plot`. Replace the `_build_right` method body and add the new methods:

```python
    def _build_right(self):
        # axis controls
        self.x_sel = Select(title="X", options=[], width=180)
        self.y_sel = Select(title="Y", options=[], width=180)
        self.type_sel = Select(title="Type", options=["line", "scatter"],
                               value="line", width=120)
        for w in (self.x_sel, self.y_sel, self.type_sel):
            w.on_change("value", lambda a, o, n: self._rebuild_plot())
        self.plot = figure(height=380, width=560, tools="pan,box_zoom,wheel_zoom,reset,save")
        plot_panel = TabPanel(child=column(row(self.x_sel, self.y_sel, self.type_sel),
                                            self.plot), title="Plot")
        # table panel placeholder (Task 13 replaces this)
        self.table_panel_child = Div(text="(table added in Task 13)")
        table_panel = TabPanel(child=self.table_panel_child, title="Table")
        self.tabs = Tabs(tabs=[plot_panel, table_panel])
        return self.tabs

    def _refresh_axes(self):
        cols = dbstate.available_columns(self.selected)
        self.x_sel.options = cols
        self.y_sel.options = cols
        if cols:
            if self.x_sel.value not in cols:
                self.x_sel.value = cols[0]
            if self.y_sel.value not in cols:
                self.y_sel.value = cols[1] if len(cols) > 1 else cols[0]

    def _rebuild_plot(self):
        self.plot.renderers = []
        if self.plot.legend:
            self.plot.legend.items = []
        xcol, ycol = self.x_sel.value, self.y_sel.value
        if not xcol or not ycol:
            return
        for i, ds in enumerate(self.selected):
            tr = dbstate.build_trace(ds, xcol, ycol)
            if tr is None:
                continue
            tr = dbstate.downsample(tr, self.max_points)
            src = ColumnDataSource(data=tr)
            color = PALETTE[i % len(PALETTE)]
            if self.type_sel.value == "scatter":
                self.plot.scatter("x", "y", source=src, color=color, legend_label=ds.label)
            else:
                self.plot.line("x", "y", source=src, color=color, legend_label=ds.label)
        self.plot.xaxis.axis_label = xcol
        self.plot.yaxis.axis_label = ycol
```

Then change `_on_selection_changed` to refresh axes and plot:

```python
    def _on_selection_changed(self):
        self._refresh_axes()
        self._rebuild_plot()
        self._rebuild_tables()
        self.status.text = f"{len(self.selected)} dataset(s) selected"
```

Add a temporary no-op `_rebuild_tables` (replaced in Task 13) so `_on_selection_changed` is valid now:

```python
    def _rebuild_tables(self):
        pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao python -m helao.deploy.test.tests.test_data_browser`
Expected: `test_plot_tab_builds_traces PASS`

- [ ] **Step 5: Commit**

```bash
git add helao/core/servers/data_browser/app.py helao/deploy/test/tests/test_data_browser.py
git commit -m "feat(data_browser): plot tab with free axis pickers and overlay traces"
```

---

## Task 13: Table tab — linked trace summary + data rows

**Files:**
- Modify: `helao/core/servers/data_browser/app.py`
- Modify: `helao/deploy/test/tests/test_data_browser.py`

- [ ] **Step 1: Write the failing test**

Add to `test_data_browser.py`:

```python
def test_table_tab_summary_and_rows():
    from helao.core.servers.data_browser.app import _UI
    with tempfile.TemporaryDirectory() as d:
        _make_finished_tree(d)
        doc = Document()
        vis = _FakeVis(d, doc)
        ui = _UI(vis, d, 50000)
        ui.index_df = sources.get_index(d, "RUNS_FINISHED", None, None)
        ui._refresh_index_table()
        ui.index_source.selected.indices = [0]
        ui._on_add()
        ui.x_sel.value, ui.y_sel.value = "t_s", "Ewe_V"
        ui._rebuild_tables()
        # summary has one row
        assert ui.summary_source.data["n_points"] == [2], ui.summary_source.data
        # selecting the summary row populates the data-rows table
        ui.summary_source.selected.indices = [0]
        ui._on_summary_select("indices", [], [0])
        assert ui.rows_source.data["t_s"] == [0.0, 1.0], ui.rows_source.data
        assert ui.rows_source.data["Ewe_V"] == [0.1, 0.2]
    print("test_table_tab_summary_and_rows PASS")
```

Add `test_table_tab_summary_and_rows()` to `__main__`.

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao python -m helao.deploy.test.tests.test_data_browser`
Expected: FAIL — `AttributeError: '_UI' object has no attribute 'summary_source'`.

- [ ] **Step 3: Write minimal implementation**

In `app.py`, build the table widgets inside `_build_right` (replace the table-panel placeholder lines) and replace the no-op `_rebuild_tables` with the real one plus `_on_summary_select`.

Replace these two lines in `_build_right`:

```python
        # table panel placeholder (Task 13 replaces this)
        self.table_panel_child = Div(text="(table added in Task 13)")
        table_panel = TabPanel(child=self.table_panel_child, title="Table")
```

with:

```python
        self.summary_source = ColumnDataSource(data={c: [] for c in dbstate.SUMMARY_COLS})
        self.summary_table = DataTable(
            source=self.summary_source,
            columns=[TableColumn(field=c, title=c) for c in dbstate.SUMMARY_COLS],
            width=560, height=180, selectable=True)
        self.summary_source.selected.on_change("indices", self._on_summary_select)
        self.rows_source = ColumnDataSource(data={})
        self.rows_table = DataTable(source=self.rows_source, columns=[],
                                    width=560, height=200)
        table_panel = TabPanel(
            child=column(Div(text="<b>Trace summary</b> (select a row to view data)"),
                         self.summary_table,
                         Div(text="<b>Data rows</b>"), self.rows_table),
            title="Table")
```

Replace the no-op `_rebuild_tables` with:

```python
    def _rebuild_tables(self):
        xcol, ycol = self.x_sel.value, self.y_sel.value
        rows = [dbstate.summary_row(ds, xcol, ycol) for ds in self.selected]
        if rows:
            self.summary_source.data = {c: [r[c] for r in rows] for c in dbstate.SUMMARY_COLS}
        else:
            self.summary_source.data = {c: [] for c in dbstate.SUMMARY_COLS}
        self.rows_source.data = {}
        self.rows_table.columns = []

    def _on_summary_select(self, attr, old, new):
        if not new:
            return
        ds = self.selected[new[0]]
        self.rows_source.data = {k: list(v) for k, v in ds.data.items()}
        self.rows_table.columns = [TableColumn(field=k, title=k) for k in ds.data]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao python -m helao.deploy.test.tests.test_data_browser`
Expected: `test_table_tab_summary_and_rows PASS`

- [ ] **Step 5: Commit**

```bash
git add helao/core/servers/data_browser/app.py helao/deploy/test/tests/test_data_browser.py
git commit -m "feat(data_browser): linked trace-summary and data-row table tab"
```

---

## Task 14: Deployment shims (hte + test)

**Files:**
- Create: `helao/deploy/hte/servers/visualizer/data_browser.py`
- Create: `helao/deploy/test/servers/visualizer/data_browser.py`
- Modify: `helao/deploy/test/tests/test_data_browser.py`

- [ ] **Step 1: Write the failing test**

Add to `test_data_browser.py`:

```python
def test_shims_expose_makebokehapp():
    import importlib
    for mod in ("helao.deploy.hte.servers.visualizer.data_browser",
                "helao.deploy.test.servers.visualizer.data_browser"):
        m = importlib.import_module(mod)
        assert hasattr(m, "makeBokehApp"), mod
        import inspect
        params = list(inspect.signature(m.makeBokehApp).parameters)
        assert params == ["doc", "confPrefix", "server_key", "helao_repo_root"], (mod, params)
    print("test_shims_expose_makebokehapp PASS")
```

Add `test_shims_expose_makebokehapp()` to `__main__`.

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao python -m helao.deploy.test.tests.test_data_browser`
Expected: FAIL — `ModuleNotFoundError: No module named 'helao.deploy.hte.servers.visualizer.data_browser'`.

- [ ] **Step 3: Write minimal implementation**

Create both shims with identical content. `helao/deploy/hte/servers/visualizer/data_browser.py`:

```python
"""hte deployment shim for the data browser visualizer.

The browser logic is deployment-agnostic and lives in
``helao.core.servers.data_browser``; this module only provides the
``makeBokehApp`` factory the bokeh launcher imports.
"""
from helao.core.servers.vis import HelaoVis
from helao.core.servers.data_browser import build_document


def makeBokehApp(doc, confPrefix, server_key, helao_repo_root):
    """Build the data browser Bokeh document for this server key."""
    app = HelaoVis(server_key=server_key, doc=doc)
    build_document(app.vis)
    return doc
```

Create `helao/deploy/test/servers/visualizer/data_browser.py` with the same content but the docstring first line reading `"""test deployment shim for the data browser visualizer.`.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao python -m helao.deploy.test.tests.test_data_browser`
Expected: `test_shims_expose_makebokehapp PASS`

- [ ] **Step 5: Commit**

```bash
git add helao/deploy/hte/servers/visualizer/data_browser.py \
        helao/deploy/test/servers/visualizer/data_browser.py \
        helao/deploy/test/tests/test_data_browser.py
git commit -m "feat(data_browser): hte and test makeBokehApp deployment shims"
```

---

## Task 15: Config entry + full test-suite run

**Files:**
- Modify: `helao/deploy/test/configs/test.yml`
- Modify: `helao/deploy/test/tests/test_data_browser.py` (add `run_all`)

- [ ] **Step 1: Add the config entry**

In `helao/deploy/test/configs/test.yml`, under the `servers:` block (sibling to the existing `LIVE:` entry), add:

```yaml
  DATABROWSE:
    host: 127.0.0.1
    port: 5003
    group: visualizer
    bokeh: data_browser
    params:
      doc_name: Data Browser
      max_points: 50000
      launch_browser: true
```

- [ ] **Step 2: Add a single-entry test runner**

At the bottom of `test_data_browser.py`, replace the `if __name__ == "__main__":` block with a `run_all()` that calls every test in order and a guard that calls it:

```python
def run_all():
    test_read_hlo_file()
    test_read_json_columnar()
    test_read_json_records()
    test_read_parquet()
    test_read_hlo_from_zip()
    test_dir_walk_and_range()
    test_runs_finished_index()
    test_runs_synced_index()
    test_processes_index_resolves_to_runs()
    test_processes_index_missing_file_unavailable()
    test_analyses_index_local()
    test_analyses_index_s3_only_unavailable()
    test_get_index_dispatch()
    test_available_columns_union_sorted()
    test_build_trace_and_downsample()
    test_summary_row()
    test_load_selected_end_to_end()
    test_build_document_smoke()
    test_plot_tab_builds_traces()
    test_table_tab_summary_and_rows()
    test_shims_expose_makebokehapp()
    print("ALL DATA_BROWSER TESTS PASS")


if __name__ == "__main__":
    run_all()
```

- [ ] **Step 3: Run the full suite**

Run: `PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao python -m helao.deploy.test.tests.test_data_browser`
Expected: final line `ALL DATA_BROWSER TESTS PASS`

- [ ] **Step 4: Verify the config validates with the launcher's checks**

Run: `PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao python -c "from helao.helpers.config_loader import read_config; c=read_config('test'); s=c['servers']['DATABROWSE']; assert s['group']=='visualizer' and s['bokeh']=='data_browser'; print('config OK', s['port'])"`
Expected: `config OK 5003`

- [ ] **Step 5: Commit**

```bash
git add helao/deploy/test/configs/test.yml helao/deploy/test/tests/test_data_browser.py
git commit -m "feat(data_browser): enable DATABROWSE in test config; full suite runner"
```

---

## Task 16: Manual launch verification (human-in-the-loop)

**Files:** none (verification only)

This task confirms the server launches and renders against real data. It needs a HELAO `root` containing at least one `RUNS_FINISHED/YY.WW/MMDD/<seq>/` tree. The automated tests already cover the logic; this is the end-to-end smoke check.

- [ ] **Step 1: Point the test config at a real root (temporary, do not commit)**

If the machine has real data under a directory `DATA_ROOT`, temporarily set `root: <DATA_ROOT>` in `helao/deploy/test/configs/test.yml`. Otherwise generate a fixture root by running, from the repo root:

```
PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao python -c "import tempfile, helao.deploy.test.tests.test_data_browser as t; import os; d=os.path.expanduser('~/databrowse_demo'); os.makedirs(d, exist_ok=True); t._make_finished_tree(d); t._make_analysis(d); print('demo root:', d)"
```

Set `root:` in the config to the printed path.

- [ ] **Step 2: Launch only the data browser bokeh app**

Run: `PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao python bokeh_launcher.py test DATABROWSE`

(If `bokeh_launcher.py` expects different positional args, consult its `__main__`; the goal is to launch the single `DATABROWSE` server entry. Alternatively launch the whole group with `./helao.sh test` and open the DATABROWSE port.)

Expected: log line `started DATABROWSE ...`; the app is served at `http://127.0.0.1:5003/data_browser`.

- [ ] **Step 3: Exercise in the browser**

Open `http://127.0.0.1:5003/data_browser` and confirm:
1. Group toggle RUNS/DERIVED switches the Source dropdown options.
2. Scan with empty dates indexes the demo data; the left table fills.
3. Typing in "Filter index" narrows rows.
4. Check a row, click "Add selected to plot" — a trace appears on the Plot tab; X/Y dropdowns list the data columns; switching them re-renders; line/scatter toggle works.
5. Table tab shows one summary row per trace; selecting it fills the data-rows table.
6. ANALYSES source: a row with `available=false` is shown but cannot be added.

- [ ] **Step 4: Revert any temporary config change**

Run: `git checkout helao/deploy/test/configs/test.yml` only if you hand-edited `root:` beyond the committed `DATABROWSE` block. Confirm `git status` shows no stray changes.

- [ ] **Step 5: Final verification commit (if any doc/notes added)**

No code commit expected here. Record results in the PR description.

---

## Self-Review

**Spec coverage:**
- Browse/filter all four sources → Tasks 4–8 (`RunsSourceIndex`, `DerivedSourceIndex`, `get_index`); filtering UI Task 11.
- RUNS_SYNCED zipped + unzipped, RUNS_FINISHED → Tasks 4–5.
- Overlay with free axis assignment → Tasks 9 (`available_columns`, `build_trace`) + 12 (plot).
- Local-files-only ANALYSES, S3 greyed → Task 7 (`available=False`, locator `""`); non-selectable enforced by `load_selected` skipping unavailable (Task 9) — note: the index table still lists them; "non-selectable" is enforced at add time, matching the spec intent (greyed/skipped).
- Filterable table, both summary + linked rows → Tasks 9 (`summary_row`) + 13.
- Date-range scoping → Tasks 3–4 (`_list_day_dirs`, `_in_range`), wired in Task 11.
- Placement: core logic + hte/test shims → Tasks 1–13 (core) + 14 (shims).
- Config-enable → Task 15.
- Error handling (skip corrupt, never crash) → `load_selected` try/except (Task 9), `_on_scan` try/except (Task 11), `BadZipFile`/`_safe_yaml` guards (Tasks 5,7).
- Performance cap/downsample → `downsample` (Task 9) applied in `_rebuild_plot` (Task 12); `max_points` from config (Tasks 11,15).
- Testing → standalone suite Tasks 1–14 + manual Task 16.

**Placeholder scan:** No "TBD"/"implement later" left. Intermediate placeholders inside `app.py` (`_build_right`, `_rebuild_tables`) are explicitly replaced within Tasks 12–13 with full code shown.

**Type/name consistency:** `read_dataset(locator, fmt)`, `INDEX_COLUMNS`, `SUMMARY_COLS`, `SelectedDataset` fields, `get_index`, `build_source_index`, `_UI` attributes (`index_df`, `selected`, `x_sel`, `y_sel`, `type_sel`, `plot`, `summary_source`, `rows_source`) are used consistently across tasks and tests. `make_zip_locator`/`parse_locator` shared by readers and sources. Index column set used by sources matches what `state.load_selected` reads (`source`, `sequence`, `experiment`, `node`, `technique`, `sample`, `file_name`, `file_type`, `available`, `locator`).

**Known assumption to validate during Task 16:** real `-act.yml`/`-prc.yml`/analysis-`.yml` field names (`technique_name`, `samples_out[].global_label`, `run_type`, `files[].file_name`, `outputs[].analysis_output_path.key`, `analysis_name`, `global_sample_label`) match what the indexers read; these were taken from the model definitions but real files may carry extra nesting. The `_safe_yaml` guards prevent crashes; if a field is absent the column is just blank.
