"""control_negative_check decides "already populated" from any record suffix."""

import pytest

from helao.hexagon.tests.smoke.control_negative_check import has_records


@pytest.mark.parametrize("name", ["a-act.json", "a-act.yml", "a-seq.json"])
def test_any_record_counts(tmp_path, name):
    d = tmp_path / "RUNS_FINISHED" / "x"
    d.mkdir(parents=True)
    (d / name).write_text("{}", encoding="utf-8")
    assert has_records(tmp_path / "RUNS_FINISHED")


def test_no_records_does_not_count(tmp_path):
    d = tmp_path / "RUNS_FINISHED" / "x"
    d.mkdir(parents=True)
    (d / "a.meta.json").write_text("{}", encoding="utf-8")
    (d / "a.jsonl").write_text("", encoding="utf-8")
    (d / "x.prg").write_text("synced: true\n", encoding="utf-8")
    assert not has_records(tmp_path / "RUNS_FINISHED")
    assert not has_records(tmp_path / "missing")
