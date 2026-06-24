# Framework SP-VIS-2 data_browser Re-layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-layer the read-only data_browser onto the framework domain/adapters/app split — `domain/data_browser.py` (pure transforms), `adapters/data_browser/{readers,sources,loader}.py` (I/O, reusing the SP6 hlo loader), `app/data_browser.py` (Bokeh) — with the existing test suite ported to pytest. Pure addition.

**Architecture:** Near-verbatim ports of the legacy `helao/core/servers/data_browser/` package, relocated by layer. The only logic re-organization: `load_selected` moves out of the (otherwise pure) `state.py` into `adapters/data_browser/loader.py`, leaving the domain module pure. Readers reuse `helao/framework/adapters/loaders/hlo_loader.read_hlo_bytes` (SP6) instead of legacy `helpers.hlo_data`.

**Tech Stack:** Python 3.12 (conda env `helao`), Bokeh, pandas, pyarrow, yaml, `pytest`.

## Global Constraints

- Run pytest via the `helao` conda env: `conda run -n helao python -m pytest <path> -v`. OS Python is 3.14; the project targets 3.12.
- Pure addition: do NOT modify any `helao/core/**` or `helao/deploy/**` file. Legacy `core/servers/data_browser/**` stays running for unmigrated deployments.
- Boundary contract: `domain/data_browser.py` imports NO I/O (no Bokeh/pyarrow/pandas/zipfile/yaml) and NO `adapters/`. Adapters may import pandas/pyarrow/zipfile/yaml + sibling adapters + domain/models. `app/` holds Bokeh. The AST boundary check (`helao/framework/tests/test_boundaries.py`) must stay green.
- Ports are near-verbatim: copy the legacy file, apply ONLY the import edits named in the task (and, for the domain module, the documented `load_selected` removal). Do not refactor logic, rename symbols, or restructure.
- Preserve public names within each module (later deployment cut-over = import-path change only): `read_dataset`, `make_zip_locator`, `parse_locator`, `get_index`, `GROUPS`, `SOURCES`, `INDEX_COLUMNS`, `RunsSourceIndex`, `DerivedSourceIndex`, `SourceIndex`, `build_source_index`, `SelectedDataset`, `available_columns`, `build_trace`, `downsample`, `summary_row`, `SUMMARY_COLS`, `load_selected`, `build_document`, `_UI`.
- New tests live under `helao/framework/tests/`.

---

### Task 1: `domain/data_browser.py` (pure transforms)

**Files:**
- Create: `helao/framework/domain/data_browser.py`
- Test: `helao/framework/tests/test_domain_data_browser.py`

**Interfaces:**
- Produces: `SelectedDataset` dataclass (fields `locator, label, source, sequence, experiment, node, technique, sample, file_name, meta, data`; property `columns`); `available_columns(selected) -> list[str]`; `build_trace(ds, xcol, ycol) -> dict | None`; `downsample(trace, max_points) -> dict`; `summary_row(ds, xcol, ycol) -> dict`; `SUMMARY_COLS: list[str]`.

- [ ] **Step 1: Write the failing test**

```python
# helao/framework/tests/test_domain_data_browser.py
"""Unit tests for the pure data_browser domain transforms."""
import importlib

from helao.framework.domain import data_browser as dbstate


def _ds(label, data, **kw):
    base = dict(locator="L", source="RUNS_FINISHED", sequence="s", experiment="e",
                node="n", technique="CV", sample="smp", file_name="f.hlo", meta={})
    base.update(kw)
    return dbstate.SelectedDataset(label=label, data=data, **base)


def test_selecteddataset_columns():
    a = _ds("a", {"t_s": [0, 1], "Ewe_V": [0.1, 0.2]})
    assert a.columns == ["t_s", "Ewe_V"]


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


def test_module_is_pure_no_io_imports():
    """Domain module must not import I/O libs or adapters."""
    src = importlib.util.find_spec("helao.framework.domain.data_browser").origin
    text = open(src).read()
    for forbidden in ("import bokeh", "import pyarrow", "import pandas",
                      "import zipfile", "import yaml", "helao.framework.adapters",
                      "helao.core", "helao.helpers"):
        assert forbidden not in text, f"domain imports forbidden: {forbidden}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_domain_data_browser.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'helao.framework.domain.data_browser'`

- [ ] **Step 3: Write minimal implementation**

Create `helao/framework/domain/data_browser.py` with the pure contents of legacy `helao/core/servers/data_browser/state.py`, but (a) REMOVE the import line `from helao.core.servers.data_browser.readers import read_dataset`, and (b) REMOVE the entire `load_selected` function (it moves to Task 4). Keep everything else exactly. Full module:

```python
# helao/framework/domain/data_browser.py
"""Pure selection/plot/table logic for the data browser (no I/O imports)."""
from dataclasses import dataclass

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_domain_data_browser.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add helao/framework/domain/data_browser.py helao/framework/tests/test_domain_data_browser.py
git commit -m "feat(framework): SP-VIS-2 — port pure data_browser transforms into domain/"
```

---

### Task 2: `adapters/data_browser/readers.py` (+ package `__init__`)

**Files:**
- Create: `helao/framework/adapters/data_browser/__init__.py`
- Create: `helao/framework/adapters/data_browser/readers.py`
- Test: `helao/framework/tests/test_adapters_data_browser_readers.py`

**Interfaces:**
- Consumes: `helao.framework.adapters.loaders.hlo_loader.read_hlo_bytes(content: bytes) -> (meta: dict, data: dict)` (SP6, already on branch).
- Produces: `read_dataset(locator: str, fmt: Optional[str]=None) -> (meta: dict, data: dict)`; `make_zip_locator(zip_path, member) -> str`; `parse_locator(locator) -> tuple`; `ZIP_PREFIX`, `ZIP_SEP`.

- [ ] **Step 1: Write the failing test**

```python
# helao/framework/tests/test_adapters_data_browser_readers.py
"""Unit tests for the data_browser file readers adapter."""
import json
import os
import tempfile
import zipfile

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from helao.framework.adapters.data_browser import readers


def _write_hlo(path):
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
        assert data["t_s"] == [0.0, 1.0]
        assert data["Ewe_V"] == [0.1, 0.2]


def test_read_json_columnar():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "out.json")
        with open(p, "w") as f:
            json.dump({"wl_nm": [400, 500], "abs": [0.1, 0.2], "note": "x"}, f)
        meta, data = readers.read_dataset(p, fmt="json")
        assert data == {"wl_nm": [400, 500], "abs": [0.1, 0.2]}
        assert meta == {"note": "x"}


def test_read_json_records():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "recs.json")
        with open(p, "w") as f:
            json.dump([{"a": 1, "b": 2}, {"a": 3, "b": 4}], f)
        _, data = readers.read_dataset(p, fmt="json")
        assert data == {"a": [1, 3], "b": [2, 4]}


def test_read_parquet():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "pat.parquet")
        pq.write_table(pa.table({"q": [1.0, 2.0], "I": [10.0, 20.0]}), p)
        _, data = readers.read_dataset(p)
        assert data == {"q": [1.0, 2.0], "I": [10.0, 20.0]}


def test_read_hlo_from_zip():
    with tempfile.TemporaryDirectory() as d:
        hlo = os.path.join(d, "cv_data.hlo")
        _write_hlo(hlo)
        zip_path = os.path.join(d, "seq.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.write(hlo, "exp/act/cv_data.hlo")
        loc = readers.make_zip_locator(zip_path, "exp/act/cv_data.hlo")
        _, data = readers.read_dataset(loc, fmt="hlo")
        assert data["t_s"] == [0.0, 1.0]


def test_parse_locator_roundtrip():
    loc = readers.make_zip_locator("/a/b.zip", "exp/act/f.hlo")
    assert readers.parse_locator(loc) == ("zip", "/a/b.zip", "exp/act/f.hlo")
    assert readers.parse_locator("/a/b.hlo") == ("file", "/a/b.hlo")


def test_unsupported_format_raises():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "x.txt")
        with open(p, "w") as f:
            f.write("nope")
        with pytest.raises(ValueError):
            readers.read_dataset(p, fmt="txt")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_adapters_data_browser_readers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'helao.framework.adapters.data_browser'`

- [ ] **Step 3: Write minimal implementation**

Create the package marker:

```python
# helao/framework/adapters/data_browser/__init__.py
"""Framework data_browser adapters: file readers, source indexers, dataset loader."""
```

Create `helao/framework/adapters/data_browser/readers.py` as the verbatim contents of legacy `helao/core/servers/data_browser/readers.py`, changing ONLY the hlo import line:

- OLD: `from helao.helpers.hlo_data import read_hlo_bytes`
- NEW: `from helao.framework.adapters.loaders.hlo_loader import read_hlo_bytes`

Full module:

```python
# helao/framework/adapters/data_browser/readers.py
"""Extension-dispatched dataset readers for the data browser.

A *locator* identifies one column-bearing data file:

- loose file: an absolute filesystem path, e.g. ``/data/.../cv_data.hlo``
- zip member: ``"zip::<zip_path>::<member_name>"``

``read_dataset(locator, fmt)`` returns ``(meta, data)`` where ``meta`` is a dict
of header/metadata and ``data`` is ``{column_name: list}``.
"""
import io
import json
import os
import zipfile
from typing import Optional, Tuple

import pyarrow.parquet as pq

from helao.framework.adapters.loaders.hlo_loader import read_hlo_bytes

ZIP_PREFIX = "zip::"
ZIP_SEP = "::"


def make_zip_locator(zip_path: str, member: str) -> str:
    return f"{ZIP_PREFIX}{zip_path}{ZIP_SEP}{member}"


def parse_locator(locator: str) -> tuple:
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


def read_dataset(locator: str, fmt: Optional[str] = None) -> Tuple[dict, dict]:
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

> If `read_hlo_bytes` in the framework loader requires keyword args that the legacy one did not, call it positionally with just `content` — the SP6 signature is `read_hlo_bytes(content, keep_keys=..., omit_keys=...)` with defaults, so `read_hlo_bytes(content)` works. Verify the test data values match (the test asserts `t_s == [0.0, 1.0]`).

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_adapters_data_browser_readers.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add helao/framework/adapters/data_browser/__init__.py helao/framework/adapters/data_browser/readers.py helao/framework/tests/test_adapters_data_browser_readers.py
git commit -m "feat(framework): SP-VIS-2 — port data_browser readers into adapters/ (reuse hlo_loader)"
```

---

### Task 3: `adapters/data_browser/sources.py` (indexers)

**Files:**
- Create: `helao/framework/adapters/data_browser/sources.py`
- Test: `helao/framework/tests/test_adapters_data_browser_sources.py`

**Interfaces:**
- Consumes: `helao.framework.adapters.data_browser.readers.make_zip_locator` (Task 2).
- Produces: `INDEX_COLUMNS`, `SOURCES`, `GROUPS`, `SourceIndex`, `RunsSourceIndex(root, state)`, `DerivedSourceIndex(root, source)`, `build_source_index(root, source)`, `get_index(root, source, date_start=None, date_end=None) -> DataFrame`, and module helpers `_list_day_dirs`, `_in_range`.

- [ ] **Step 1: Write the failing test**

```python
# helao/framework/tests/test_adapters_data_browser_sources.py
"""Unit tests for the data_browser source indexers adapter."""
import json
import os
import tempfile
import zipfile

import yaml

from helao.framework.adapters.data_browser import sources, readers


def _write_hlo(path):
    with open(path, "w") as f:
        f.write("hlo_version: 1.0\naction_name: cv\ncolumn_headings: [t_s, Ewe_V]\n%%\n")
        f.write(json.dumps({"t_s": 0.0, "Ewe_V": 0.1}) + "\n")
        f.write(json.dumps({"t_s": 1.0, "Ewe_V": 0.2}) + "\n")


def _make_finished_tree(root):
    act_dir = os.path.join(
        root, "RUNS_FINISHED", "26.25", "0618",
        "141523__SDC_seq__lab1", "260618.141524__SDC_exp_CV", "1__0__sim__cv")
    os.makedirs(act_dir)
    _write_hlo(os.path.join(act_dir, "cv_data.hlo"))
    with open(os.path.join(act_dir, "260618.141525-act.yml"), "w") as f:
        yaml.safe_dump({"technique_name": "CV", "run_type": "data",
                        "samples_out": [{"global_label": "solid__lab1_1"}]}, f)


def _make_synced_zip(root):
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


def _make_process(root):
    prc_dir = os.path.join(root, "PROCESSES", "26.25", "0618",
                           "141523__SDC_seq__lab1", "260618.141524__SDC_exp_CV")
    os.makedirs(prc_dir)
    with open(os.path.join(prc_dir, "0__abc__CV-prc.yml"), "w") as f:
        yaml.safe_dump({"technique_name": "CV", "run_type": "data",
                        "samples_out": [{"global_label": "solid__lab1_1"}],
                        "files": [{"file_name": "cv_data.hlo", "file_type": "helao__file"}]}, f)


def _make_analysis(root, with_local_output=True):
    ana_dir = os.path.join(root, "ANALYSES", "26.25", "0618", "150305__icpms__plate1")
    os.makedirs(ana_dir)
    with open(os.path.join(ana_dir, "uuid1234.yml"), "w") as f:
        yaml.safe_dump({"analysis_name": "icpms", "global_sample_label": "solid__lab1_1",
                        "outputs": [{"analysis_output_path": {"bucket": "b", "key": "analysis/uuid1234/conc.json", "region": "r"},
                                     "content_type": "application/json",
                                     "output_type": "concentration", "output_name": "conc"}]}, f)
    if with_local_output:
        with open(os.path.join(ana_dir, "conc.json"), "w") as f:
            json.dump({"element": ["Ni", "Fe"], "ppm": [12.0, 3.4]}, f)


def test_dir_walk_and_range():
    with tempfile.TemporaryDirectory() as d:
        base = os.path.join(d, "RUNS_FINISHED")
        for ww, mmdd in [("26.20", "0515"), ("26.25", "0618")]:
            os.makedirs(os.path.join(base, ww, mmdd))
        dates = [ds for ds, _ in sources._list_day_dirs(base)]
        assert dates == ["26.20/0515", "26.25/0618"]
        assert sources._in_range("26.25/0618", "26.22", "26.30") is True
        assert sources._in_range("26.20/0515", "26.22", "26.30") is False
        assert sources._in_range("26.25/0618", None, None) is True


def test_runs_finished_index():
    with tempfile.TemporaryDirectory() as d:
        _make_finished_tree(d)
        df = sources.RunsSourceIndex(d, "FINISHED").index()
        assert list(df.columns) == sources.INDEX_COLUMNS
        assert len(df) == 1
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


def test_runs_synced_index():
    with tempfile.TemporaryDirectory() as d:
        _make_synced_zip(d)
        df = sources.RunsSourceIndex(d, "SYNCED").index()
        assert len(df) == 1
        r = df.iloc[0]
        assert r["source"] == "RUNS_SYNCED"
        assert r["sequence"] == "SDC_seq"
        assert r["locator"].startswith("zip::")
        _, data = readers.read_dataset(r["locator"], r["file_type"])
        assert data["Ewe_V"] == [0.1, 0.2]


def test_processes_index_resolves_to_runs():
    with tempfile.TemporaryDirectory() as d:
        _make_finished_tree(d)
        _make_process(d)
        df = sources.DerivedSourceIndex(d, "PROCESSES").index()
        assert len(df) == 1
        r = df.iloc[0]
        assert r["source"] == "PROCESSES"
        assert r["sample"] == "solid__lab1_1"
        assert r["available"] is True
        _, data = readers.read_dataset(r["locator"], r["file_type"])
        assert data["t_s"] == [0.0, 1.0]


def test_processes_index_missing_file_unavailable():
    with tempfile.TemporaryDirectory() as d:
        _make_process(d)
        df = sources.DerivedSourceIndex(d, "PROCESSES").index()
        assert len(df) == 1
        assert df.iloc[0]["available"] is False
        assert df.iloc[0]["locator"] == ""


def test_analyses_index_local():
    with tempfile.TemporaryDirectory() as d:
        _make_analysis(d, with_local_output=True)
        df = sources.DerivedSourceIndex(d, "ANALYSES").index()
        assert len(df) == 1
        r = df.iloc[0]
        assert r["source"] == "ANALYSES"
        assert r["sequence"] == "icpms"
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


def test_get_index_dispatch():
    with tempfile.TemporaryDirectory() as d:
        _make_finished_tree(d)
        df = sources.get_index(d, "RUNS_FINISHED", None, None)
        assert df.iloc[0]["source"] == "RUNS_FINISHED"
        empty = sources.get_index(d, "ANALYSES", None, None)
        assert list(empty.columns) == sources.INDEX_COLUMNS
        assert len(empty) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_adapters_data_browser_sources.py -v`
Expected: FAIL — `ImportError: cannot import name 'sources'` / `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

Create `helao/framework/adapters/data_browser/sources.py` as the verbatim contents of legacy `helao/core/servers/data_browser/sources.py`, changing ONLY the `make_zip_locator` import line:

- OLD: `from helao.core.servers.data_browser.readers import make_zip_locator`
- NEW: `from helao.framework.adapters.data_browser.readers import make_zip_locator`

Everything else (the `_list_day_dirs`, `_in_range`, `_seq_name`, `_first_sample`, `_safe_yaml`, `_safe_yaml_bytes`, `_row`, `_meta_fields`, `_rows_to_index_df`, `SourceIndex`, `RunsSourceIndex`, `_resolve_run_file`, `DerivedSourceIndex`, `SOURCES`, `GROUPS`, `build_source_index`, `get_index`) is copied byte-for-byte from the legacy module. Do not alter any logic.

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_adapters_data_browser_sources.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add helao/framework/adapters/data_browser/sources.py helao/framework/tests/test_adapters_data_browser_sources.py
git commit -m "feat(framework): SP-VIS-2 — port data_browser source indexers into adapters/"
```

---

### Task 4: `adapters/data_browser/loader.py` (`load_selected`)

**Files:**
- Create: `helao/framework/adapters/data_browser/loader.py`
- Test: `helao/framework/tests/test_adapters_data_browser_loader.py`

**Interfaces:**
- Consumes: `helao.framework.adapters.data_browser.readers.read_dataset` (Task 2); `helao.framework.domain.data_browser.SelectedDataset` (Task 1); `helao.framework.adapters.data_browser.sources.get_index` (Task 3, for the test).
- Produces: `load_selected(index_df, positions) -> (datasets: list[SelectedDataset], skipped: list[tuple[str, str]])`.

- [ ] **Step 1: Write the failing test**

```python
# helao/framework/tests/test_adapters_data_browser_loader.py
"""Unit tests for the data_browser dataset loader adapter."""
import json
import os
import tempfile

import yaml

from helao.framework.adapters.data_browser import sources, loader
from helao.framework.domain import data_browser as dbstate


def _write_hlo(path):
    with open(path, "w") as f:
        f.write("hlo_version: 1.0\naction_name: cv\ncolumn_headings: [t_s, Ewe_V]\n%%\n")
        f.write(json.dumps({"t_s": 0.0, "Ewe_V": 0.1}) + "\n")
        f.write(json.dumps({"t_s": 1.0, "Ewe_V": 0.2}) + "\n")


def _make_finished_tree(root):
    act_dir = os.path.join(
        root, "RUNS_FINISHED", "26.25", "0618",
        "141523__SDC_seq__lab1", "260618.141524__SDC_exp_CV", "1__0__sim__cv")
    os.makedirs(act_dir)
    _write_hlo(os.path.join(act_dir, "cv_data.hlo"))
    with open(os.path.join(act_dir, "260618.141525-act.yml"), "w") as f:
        yaml.safe_dump({"technique_name": "CV", "run_type": "data",
                        "samples_out": [{"global_label": "solid__lab1_1"}]}, f)


def test_load_selected_end_to_end():
    with tempfile.TemporaryDirectory() as d:
        _make_finished_tree(d)
        df = sources.get_index(d, "RUNS_FINISHED", None, None)
        datasets, skipped = loader.load_selected(df, [0])
        assert len(datasets) == 1 and not skipped
        ds = datasets[0]
        assert isinstance(ds, dbstate.SelectedDataset)
        assert ds.data["t_s"] == [0.0, 1.0]
        assert dbstate.available_columns(datasets) == ["Ewe_V", "t_s"]


def test_load_selected_empty_index():
    with tempfile.TemporaryDirectory() as d:
        ana = sources.get_index(d, "ANALYSES", None, None)  # empty
        ds2, sk2 = loader.load_selected(ana, [])
        assert ds2 == [] and sk2 == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_adapters_data_browser_loader.py -v`
Expected: FAIL — `ImportError: cannot import name 'loader'`

- [ ] **Step 3: Write minimal implementation**

Create `helao/framework/adapters/data_browser/loader.py` with `load_selected` moved verbatim from legacy `state.py` (lines 77-101), repointed at the framework readers + domain dataclass:

```python
# helao/framework/adapters/data_browser/loader.py
"""Read selected index rows into domain SelectedDataset objects (I/O adapter)."""
from helao.framework.adapters.data_browser.readers import read_dataset
from helao.framework.domain.data_browser import SelectedDataset


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

Run: `conda run -n helao python -m pytest helao/framework/tests/test_adapters_data_browser_loader.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add helao/framework/adapters/data_browser/loader.py helao/framework/tests/test_adapters_data_browser_loader.py
git commit -m "feat(framework): SP-VIS-2 — move load_selected into adapters/data_browser/loader"
```

---

### Task 5: `app/data_browser.py` (Bokeh UI)

**Files:**
- Create: `helao/framework/app/data_browser.py`
- Test: `helao/framework/tests/test_app_data_browser.py`

**Interfaces:**
- Consumes: `helao.framework.adapters.data_browser.sources` (Task 3); `helao.framework.adapters.data_browser.loader.load_selected` (Task 4); `helao.framework.domain.data_browser` as `dbstate` for `SUMMARY_COLS`/`available_columns`/`build_trace`/`downsample`/`summary_row` (Task 1). A `Vis`-like object exposing `.doc`, `.helaodirs.root`, `.server_cfg`, `.print_message` (SP-VIS-1 `app/vis.py`).
- Produces: `build_document(vis) -> doc`; `_UI` class.

- [ ] **Step 1: Write the failing test**

```python
# helao/framework/tests/test_app_data_browser.py
"""Unit tests for the framework data_browser Bokeh app."""
import json
import os
import tempfile
from pathlib import Path

import yaml

from bokeh.document import Document

from helao.framework.adapters.data_browser import sources


def _write_hlo(path):
    with open(path, "w") as f:
        f.write("hlo_version: 1.0\naction_name: cv\ncolumn_headings: [t_s, Ewe_V]\n%%\n")
        f.write(json.dumps({"t_s": 0.0, "Ewe_V": 0.1}) + "\n")
        f.write(json.dumps({"t_s": 1.0, "Ewe_V": 0.2}) + "\n")


def _make_finished_tree(root):
    act_dir = os.path.join(
        root, "RUNS_FINISHED", "26.25", "0618",
        "141523__SDC_seq__lab1", "260618.141524__SDC_exp_CV", "1__0__sim__cv")
    os.makedirs(act_dir)
    _write_hlo(os.path.join(act_dir, "cv_data.hlo"))
    with open(os.path.join(act_dir, "260618.141525-act.yml"), "w") as f:
        yaml.safe_dump({"technique_name": "CV", "run_type": "data",
                        "samples_out": [{"global_label": "solid__lab1_1"}]}, f)


class _FakeDirs:
    def __init__(self, root):
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


def test_build_document_smoke():
    from helao.framework.app.data_browser import build_document
    with tempfile.TemporaryDirectory() as d:
        _make_finished_tree(d)
        doc = Document()
        build_document(_FakeVis(d, doc))
        assert len(doc.roots) >= 1


def test_plot_tab_builds_traces():
    from helao.framework.app.data_browser import _UI
    with tempfile.TemporaryDirectory() as d:
        _make_finished_tree(d)
        doc = Document()
        ui = _UI(_FakeVis(d, doc), d, 50000)
        ui.index_df = sources.get_index(d, "RUNS_FINISHED", None, None)
        ui._refresh_index_table()
        ui.index_source.selected.indices = [0]
        ui._on_add()
        assert len(ui.selected) == 1
        assert set(ui.x_sel.options) == {"t_s", "Ewe_V"}
        ui.x_sel.value, ui.y_sel.value = "t_s", "Ewe_V"
        ui._rebuild_plot()
        assert len(ui.plot.renderers) == 1


def test_table_tab_summary_and_rows():
    from helao.framework.app.data_browser import _UI
    with tempfile.TemporaryDirectory() as d:
        _make_finished_tree(d)
        doc = Document()
        ui = _UI(_FakeVis(d, doc), d, 50000)
        ui.index_df = sources.get_index(d, "RUNS_FINISHED", None, None)
        ui._refresh_index_table()
        ui.index_source.selected.indices = [0]
        ui._on_add()
        ui.x_sel.value, ui.y_sel.value = "t_s", "Ewe_V"
        ui._rebuild_tables()
        assert ui.summary_source.data["n_points"] == [2]
        ui.summary_source.selected.indices = [0]
        ui._on_summary_select("indices", [], [0])
        assert ui.rows_source.data["t_s"] == [0.0, 1.0]
        assert ui.rows_source.data["Ewe_V"] == [0.1, 0.2]


def test_plot_replot_and_clear_safe():
    from helao.framework.app.data_browser import _UI
    with tempfile.TemporaryDirectory() as d:
        _make_finished_tree(d)
        doc = Document()
        ui = _UI(_FakeVis(d, doc), d, 50000)
        ui.index_df = sources.get_index(d, "RUNS_FINISHED", None, None)
        ui._refresh_index_table()
        ui.index_source.selected.indices = [0]
        ui._on_add()
        ui.x_sel.value, ui.y_sel.value = "t_s", "Ewe_V"
        ui._rebuild_plot()
        ui._rebuild_plot()  # replot: exercises legend-clear path twice
        assert len(ui.plot.renderers) == 1
        ui.summary_source.selected.indices = [0]
        ui._on_clear()
        ui._on_summary_select("indices", [], [0])  # stale index must not raise
        assert ui.selected == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_app_data_browser.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'helao.framework.app.data_browser'`

- [ ] **Step 3: Write minimal implementation**

Create `helao/framework/app/data_browser.py` as the verbatim contents of legacy `helao/core/servers/data_browser/app.py`, changing ONLY the imports at the top and the one `load_selected` call site:

- OLD (line 12): `from helao.core.servers.data_browser import sources, state as dbstate`
- NEW (three lines):
  ```python
  from helao.framework.adapters.data_browser import sources
  from helao.framework.domain import data_browser as dbstate
  from helao.framework.adapters.data_browser.loader import load_selected
  ```
- In `_on_add` (legacy line 234), change `dbstate.load_selected(df.reset_index(drop=True), picks)` → `load_selected(df.reset_index(drop=True), picks)`.

Every other reference (`dbstate.SUMMARY_COLS`, `dbstate.available_columns`, `dbstate.build_trace`, `dbstate.downsample`, `dbstate.summary_row`) resolves against the domain module unchanged. All widget construction, callbacks, layout, and the `INDEX_TABLE_COLS`/`FILTER_COLS`/`PALETTE` constants are copied byte-for-byte. Do not alter UI logic.

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_app_data_browser.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add helao/framework/app/data_browser.py helao/framework/tests/test_app_data_browser.py
git commit -m "feat(framework): SP-VIS-2 — port data_browser Bokeh app into app/"
```

---

### Task 6: Full-suite + boundary verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full framework test suite**

Run: `conda run -n helao python -m pytest helao/framework/tests/ -p no:cacheprovider -q 2>&1 | tail -1`
Expected: all pass (new + pre-existing), no regressions.

- [ ] **Step 2: Confirm the AST boundary check is green**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_boundaries.py -v`
Expected: PASS. `domain/data_browser.py` imports no Bokeh/pyarrow/pandas/zipfile/yaml/adapters; the adapters' I/O imports are at the adapter layer. (The `test_module_is_pure_no_io_imports` test in Task 1 also guards this.)

- [ ] **Step 3: Confirm pure-addition (no legacy/deploy edits)**

Run: `git diff --name-only feat/framework-scaffold...HEAD | grep -E "helao/(core|deploy)/" || echo "NONE (clean)"`
Expected: `NONE (clean)` — only files under `helao/framework/**` and `docs/superpowers/**`.

- [ ] **Step 4: Commit (only if verification fixups were needed)**

```bash
git add -A
git commit -m "test(framework): SP-VIS-2 — verify full suite + boundary green"
```

---

## Self-Review

**Spec coverage:**
- §4.1 `domain/data_browser.py` (pure transforms, load_selected removed) → Task 1. ✓
- §4.2 `adapters/data_browser/readers.py` (reuse hlo_loader) → Task 2. ✓
- §4.3 `adapters/data_browser/sources.py` → Task 3. ✓
- §4.4 `adapters/data_browser/loader.py` (load_selected moved) → Task 4. ✓
- §4.5 `app/data_browser.py` (Bokeh, import changes) → Task 5. ✓
- §4.6 package `__init__.py` → folded into Task 2. ✓
- §6 error handling (unsupported format raise, skip semantics, scan catch) → covered in Tasks 2/4/5 tests. ✓
- §7 test strategy (ported suite split by layer, drop shim test, boundary assert) → Tasks 1-6. ✓
- §3 boundary contract → Task 1 purity test + Task 6 boundary check. ✓
- §2 non-goals (no deploy rewiring, no legacy edits) → Task 6 Step 3. ✓

**Placeholder scan:** No TBD/TODO. Port instructions name exact old→new import lines; the one guarded note (Task 2 `read_hlo_bytes` positional call) is a concrete instruction with the SP6 signature, not a placeholder. Full code given for the new/edited modules.

**Type consistency:** `read_dataset(locator, fmt=None) -> (meta, data)` consistent Tasks 2/4. `load_selected(index_df, positions) -> (datasets, skipped)` consistent Tasks 4/5. `get_index(root, source, date_start, date_end)` consistent Tasks 3/4/5. `dbstate` alias maps to `domain.data_browser` consistently in Task 5. `SelectedDataset` fields identical in Tasks 1/4.
