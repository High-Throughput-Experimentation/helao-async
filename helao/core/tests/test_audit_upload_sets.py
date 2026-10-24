"""audit_upload_sets must not report 'no gap' for a tree it cannot scan."""

from helao.core.tests.audit_upload_sets import main


def test_json_era_tree_scans_zero_actions_and_fails(tmp_path, capsys):
    (tmp_path / "260101.000000000000-act.json").write_text("{}\n", encoding="utf-8")
    assert main([str(tmp_path)]) != 0
    assert "no gap" not in capsys.readouterr().out


def test_yml_tree_still_scans(tmp_path):
    (tmp_path / "260101.000000000000-act.yml").write_text("{}\n", encoding="utf-8")
    assert main([str(tmp_path)]) == 0
