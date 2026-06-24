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
