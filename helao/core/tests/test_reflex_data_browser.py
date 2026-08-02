"""Tests for the Reflex data browser page.

State transitions are driven directly. Reflex state cannot be instantiated
outside an app, so the page's logic lives in module-level functions and a cache
object that these exercise without app machinery -- the same split that let the
visualiser panels be tested at all.
"""

import json

import pytest

from helao.core.servers.data_browser import app_reflex as dbx


def _write_hlo(path):
    """Minimal HLO file: YAML header, %% marker, JSONL body."""
    with open(path, "w") as fh:
        fh.write("hlo_version: 1.0\n")
        fh.write("action_name: cv\n")
        fh.write("column_headings: [t_s, Ewe_V]\n")
        fh.write("%%\n")
        fh.write(json.dumps({"t_s": 0.0, "Ewe_V": 0.1}) + "\n")
        fh.write(json.dumps({"t_s": 1.0, "Ewe_V": 0.2}) + "\n")


@pytest.fixture
def run_tree(tmp_path):
    """A RUNS_FINISHED tree with one sequence, one experiment, one hlo file."""
    import yaml

    day = tmp_path / "RUNS_FINISHED" / "26.30" / "0801"
    seq = day / "120000__seq--cv__label"
    exp = seq / "260801.120000__exp--cv"
    act = exp / "0__0__PSTAT__cv"
    act.mkdir(parents=True)
    with open(seq / "260801.120000000000-seq.yml", "w") as fh:
        yaml.safe_dump({"sequence_name": "cv", "run_type": "test"}, fh)
    with open(exp / "260801.120000000000-exp.yml", "w") as fh:
        yaml.safe_dump({"experiment_name": "cv"}, fh)
    with open(act / "260801.120000000000-act.yml", "w") as fh:
        yaml.safe_dump({"action_name": "cv", "technique_name": "cv"}, fh)
    _write_hlo(str(act / "cv_data.hlo"))
    return str(tmp_path)


def test_source_options_follow_the_selected_group():
    from helao.core.servers.data_browser import sources

    assert dbx.options_for_group("RUNS") == sources.GROUPS["RUNS"]
    assert dbx.options_for_group("DERIVED") == sources.GROUPS["DERIVED"]


def test_options_for_an_unknown_group_is_empty_not_an_error():
    """A stale group string from a reconnecting session must not 500 the page."""
    assert dbx.options_for_group("NOPE") == []


def test_scan_index_returns_rows_for_a_real_tree(run_tree):
    df, error = dbx.scan_index(run_tree, "RUNS_FINISHED", None, None)
    assert error == ""
    assert len(df) == 1
    assert df.iloc[0]["file_name"] == "cv_data.hlo"


def test_scan_index_reports_a_bad_source_instead_of_raising(run_tree):
    """The Bokeh app catches this and writes it to a status line; a raised
    exception inside a Reflex background event just vanishes into the log."""
    df, error = dbx.scan_index(run_tree, "NOT_A_SOURCE", None, None)
    assert df is None
    assert "NOT_A_SOURCE" in error


def test_scan_index_on_an_empty_root_is_empty_not_an_error(tmp_path):
    df, error = dbx.scan_index(str(tmp_path), "RUNS_FINISHED", None, None)
    assert error == ""
    assert len(df) == 0


def test_filter_matches_across_every_filter_column(run_tree):
    df, _ = dbx.scan_index(run_tree, "RUNS_FINISHED", None, None)
    assert len(dbx.filter_index(df, "cv")) == 1
    assert len(dbx.filter_index(df, "PSTAT")) == 1
    assert len(dbx.filter_index(df, "zzzz")) == 0


def test_filter_is_case_insensitive(run_tree):
    df, _ = dbx.scan_index(run_tree, "RUNS_FINISHED", None, None)
    assert len(dbx.filter_index(df, "CV")) == 1


def test_empty_filter_returns_everything(run_tree):
    df, _ = dbx.scan_index(run_tree, "RUNS_FINISHED", None, None)
    assert len(dbx.filter_index(df, "   ")) == len(df)


def test_filter_on_no_index_is_none(run_tree):
    assert dbx.filter_index(None, "cv") is None


def test_index_rows_are_strings_for_the_table(run_tree):
    """Reflex serialises state to JSON; a numpy bool or NaN in a table cell
    renders as garbage or breaks the encoder."""
    df, _ = dbx.scan_index(run_tree, "RUNS_FINISHED", None, None)
    rows = dbx.index_rows(df)
    assert rows and all(isinstance(c, str) for c in rows[0])


def test_index_rows_on_no_index_is_empty():
    assert dbx.index_rows(None) == []


def test_cap_rows_passes_a_short_list_through():
    rows = [["a"], ["b"]]
    view, total, truncated = dbx.cap_rows(rows, 10)
    assert view == rows and total == 2 and truncated is False


def test_cap_rows_reports_that_it_capped():
    """A silent truncation reads as 'this is everything' when it is not."""
    rows = [[str(i)] for i in range(20)]
    view, total, truncated = dbx.cap_rows(rows, 5)
    assert len(view) == 5 and total == 20 and truncated is True


def test_cache_is_per_session():
    cache = dbx.IndexCache()
    cache.put("tok-a", "df-a")
    cache.put("tok-b", "df-b")
    assert cache.get("tok-a") == "df-a"
    assert cache.get("tok-b") == "df-b"


def test_cache_returns_none_for_an_unknown_session():
    assert dbx.IndexCache().get("nobody") is None


def test_cache_drop_frees_a_session():
    cache = dbx.IndexCache()
    cache.put("tok", "df")
    cache.drop("tok")
    assert cache.get("tok") is None


def _one_dataset(run_tree):
    df, _ = dbx.scan_index(run_tree, "RUNS_FINISHED", None, None)
    return dbx.load_positions(df, [0])


def test_load_positions_reads_the_chosen_rows(run_tree):
    selected, skipped = _one_dataset(run_tree)
    assert len(selected) == 1
    assert skipped == []
    assert "t_s" in selected[0].data


def test_load_positions_reports_skips_rather_than_dropping_them(run_tree):
    """A file that is missing or unreadable is the most common thing a user
    hits; silently omitting it from the plot is the worst presentation."""
    df, _ = dbx.scan_index(run_tree, "RUNS_FINISHED", None, None)
    df = df.copy()
    df.loc[0, "available"] = False
    selected, skipped = dbx.load_positions(df, [0])
    assert selected == []
    assert len(skipped) == 1 and "not available" in skipped[0][1]


def test_load_positions_with_no_index_is_empty():
    assert dbx.load_positions(None, [0]) == ([], [])


def test_axis_options_are_the_union_of_dataset_columns(run_tree):
    selected, _ = _one_dataset(run_tree)
    assert dbx.axis_options(selected) == ["Ewe_V", "t_s"]


def test_axis_options_with_nothing_selected_is_empty():
    assert dbx.axis_options([]) == []


def test_chart_series_builds_one_entry_per_dataset(run_tree):
    selected, _ = _one_dataset(run_tree)
    series = dbx.chart_series(selected, "t_s", "Ewe_V", 50000)
    assert len(series) == 1
    assert series[0]["label"] == selected[0].label
    assert len(series[0]["x"]) == 2


def test_chart_series_skips_a_dataset_missing_the_chosen_column(run_tree):
    """Overlaying datasets from unrelated files means some will not share
    columns; that is normal, not an error."""
    selected, _ = _one_dataset(run_tree)
    assert dbx.chart_series(selected, "t_s", "not_a_column", 50000) == []


def test_chart_series_downsamples_to_max_points(run_tree):
    selected, _ = _one_dataset(run_tree)
    ds = selected[0]
    ds.data["t_s"] = list(range(1000))
    ds.data["Ewe_V"] = list(range(1000))
    series = dbx.chart_series([ds], "t_s", "Ewe_V", 10)
    assert len(series[0]["x"]) <= 11


def test_chart_series_with_no_axes_chosen_is_empty(run_tree):
    selected, _ = _one_dataset(run_tree)
    assert dbx.chart_series(selected, "", "", 50000) == []


def test_summary_rows_match_the_shared_summary_columns(run_tree):
    from helao.core.servers.data_browser import state as dbstate

    selected, _ = _one_dataset(run_tree)
    rows = dbx.summary_rows(selected, "t_s", "Ewe_V")
    assert len(rows) == 1
    assert len(rows[0]) == len(dbstate.SUMMARY_COLS)
    assert all(isinstance(c, str) for c in rows[0])


def test_dataset_rows_returns_headers_and_string_cells(run_tree):
    selected, _ = _one_dataset(run_tree)
    headers, rows = dbx.dataset_rows(selected[0])
    assert sorted(headers) == ["Ewe_V", "t_s"]
    assert rows and all(isinstance(c, str) for c in rows[0])


def test_dataset_rows_on_nothing_is_empty():
    assert dbx.dataset_rows(None) == ([], [])
