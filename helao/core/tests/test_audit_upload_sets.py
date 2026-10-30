"""audit_upload_sets must not report 'no gap' for a tree it cannot scan."""

from helao.core.tests.audit_upload_sets import glob_set, main
from helao.helpers.meta_io import write_meta


def test_a_tree_with_no_action_records_scans_zero_actions_and_fails(tmp_path, capsys):
    (tmp_path / "260101.000000000000-exp.json").write_text("{}\n", encoding="utf-8")
    assert main([str(tmp_path)]) != 0
    assert "no gap" not in capsys.readouterr().out


def test_yml_tree_still_scans(tmp_path):
    (tmp_path / "260101.000000000000-act.yml").write_text("{}\n", encoding="utf-8")
    assert main([str(tmp_path)]) == 0


def test_a_mixed_tree_counts_both_formats_and_globs_no_records(tmp_path, capsys):
    legacy = tmp_path / "a" / "0__0__X__old"
    legacy.mkdir(parents=True)
    (legacy / "260101.000000000001-act.yml").write_text(
        "files:\n  - file_name: X-0.hlo\n", encoding="utf-8"
    )
    (legacy / "X-0.hlo").write_text("x\n", encoding="utf-8")
    new = tmp_path / "b" / "0__0__X__new"
    new.mkdir(parents=True)
    write_meta(
        new / "260101.000000000002-act.json",
        {"files": [{"file_name": "X-0.jsonl"}]},
    )
    (new / "X-0.jsonl").write_text("{}\n", encoding="utf-8")
    write_meta(new / "X-0.meta.json", {"column_headings": []})
    write_meta(new / "0__u__X-prc.json", {"process_uuid": "u"})
    (new / "260101.000000000002-act.prg").write_text("synced: true\n", "utf-8")

    assert glob_set(new) == {"X-0.jsonl"}
    assert main([str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "actions scanned : 2" in out
    assert "no gap" in out
