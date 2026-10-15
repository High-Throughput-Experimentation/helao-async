"""Every smoke script's ``rm -rf`` of a root must be preceded by a safe_root check."""

from pathlib import Path

import pytest

SMOKE = Path(__file__).parent / "smoke"


@pytest.mark.parametrize(
    "script", ["control_negative_run.sh", "parity_run.sh", "conc_run.sh"]
)
def test_rm_rf_is_guarded_by_safe_root(script):
    lines = (SMOKE / script).read_text(encoding="utf-8").splitlines()
    rms = [i for i, ln in enumerate(lines) if ln.startswith("rm -rf ")]
    assert rms
    for i in rms:
        target = lines[i].split(maxsplit=2)[2]
        assert any(
            "safe_root.py check-temp" in ln
            and ln.rstrip().endswith("|| exit 2")
            and target in ln
            for ln in lines[:i]
        ), f"{script}: {lines[i]} has no safe_root check-temp"


def test_check_temp_refuses_non_temp_root(tmp_path, capsys):
    from helao.hexagon.tests.smoke import safe_root

    assert safe_root.main(["check-temp", str(tmp_path / "scratch")]) == 0
    assert safe_root.main(["check-temp", "/var/lib/not_tmp_root"]) == 2
