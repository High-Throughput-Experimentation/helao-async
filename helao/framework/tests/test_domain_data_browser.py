"""Unit tests for the pure data_browser domain transforms."""
import importlib.util

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
