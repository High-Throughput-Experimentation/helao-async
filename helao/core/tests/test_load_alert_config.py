"""load_alert_config fails soft: a missing or malformed alert file must not stop
every server at startup (note1, 2026-11-11: an unmounted share took the file
away and make_logger crashed on a str)."""

from helao.helpers.launcher_bootstrap import load_alert_config


def test_no_path_gives_empty():
    assert load_alert_config({}) == {}


def test_missing_file_warns_and_gives_empty(tmp_path, capsys):
    path = tmp_path / "absent" / "alert.yml"
    assert load_alert_config({"alert_config_path": str(path)}) == {}
    err = capsys.readouterr().err
    assert "alert_config_path" in err and str(path) in err


def test_non_mapping_file_warns_and_gives_empty(tmp_path, capsys):
    path = tmp_path / "alert.yml"
    path.write_text("- just\n- a list\n", encoding="utf-8")
    assert load_alert_config({"alert_config_path": str(path)}) == {}
    assert "not a mapping" in capsys.readouterr().err


def test_valid_file_is_loaded(tmp_path):
    path = tmp_path / "alert.yml"
    path.write_text("mailhost: smtp.example.org\nmailport: 25\n", encoding="utf-8")
    cfg = load_alert_config({"alert_config_path": str(path)})
    assert cfg["mailhost"] == "smtp.example.org" and cfg["mailport"] == 25
