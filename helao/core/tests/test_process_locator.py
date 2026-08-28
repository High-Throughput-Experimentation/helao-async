"""find_process_ymls: colocated, legacy mirror, and both at once."""

from pathlib import Path

import pytest

from helao.core.drivers.data.process_locator import find_process_ymls

REL = Path("26.35") / "0828" / "260828.115959__seq" / "260828.120000__exp"
UUID_A = "06a5a2d6-b26c-7019-8000-4c2d967e5df1"
UUID_B = "06a5a2d6-b26c-7673-8000-9f38fe556fd6"


def _prc_name(pidx: int, uuid: str) -> str:
    return f"{pidx}__{uuid}__SIM_exp-prc.yml"


def _make(root: Path, colocated: list[str], legacy: list[str]) -> Path:
    exp_dir = root / "RUNS_SYNCED" / REL
    exp_dir.mkdir(parents=True)
    (exp_dir / "260828.120000000000-exp.yml").write_text("experiment_name: SIM_exp\n")
    for name in colocated:
        (exp_dir / name).write_text(f"process_uuid: {name.split('__')[1]}\n")
    if legacy:
        leg = root / "PROCESSES" / REL
        leg.mkdir(parents=True)
        for name in legacy:
            (leg / name).write_text(f"process_uuid: {name.split('__')[1]}\n")
    return exp_dir


def test_colocated_only(tmp_path):
    exp_dir = _make(tmp_path, [_prc_name(0, UUID_A)], [])
    found = find_process_ymls(exp_dir, process_root=tmp_path / "PROCESSES")
    assert [p.name for p in found] == [_prc_name(0, UUID_A)]
    assert found[0].parent == exp_dir


def test_legacy_mirror_only(tmp_path):
    exp_dir = _make(tmp_path, [], [_prc_name(0, UUID_A)])
    found = find_process_ymls(exp_dir, process_root=tmp_path / "PROCESSES")
    assert [p.name for p in found] == [_prc_name(0, UUID_A)]
    assert "PROCESSES" in found[0].parts


def test_colocated_wins_the_dedupe(tmp_path):
    exp_dir = _make(
        tmp_path, [_prc_name(0, UUID_A)], [_prc_name(0, UUID_A), _prc_name(1, UUID_B)]
    )
    found = find_process_ymls(exp_dir, process_root=tmp_path / "PROCESSES")
    by_uuid = {p.name.split("__")[1]: p for p in found}
    assert set(by_uuid) == {UUID_A, UUID_B}
    assert by_uuid[UUID_A].parent == exp_dir, "colocated must win"
    assert "PROCESSES" in by_uuid[UUID_B].parts, "the mirror still supplies B"


def test_accepts_an_exp_yml_path(tmp_path):
    exp_dir = _make(tmp_path, [_prc_name(0, UUID_A)], [])
    exp_yml = next(exp_dir.glob("*-exp.yml"))
    assert find_process_ymls(exp_yml, process_root=tmp_path / "PROCESSES") == (
        find_process_ymls(exp_dir, process_root=tmp_path / "PROCESSES")
    )


def test_neither_location_has_anything(tmp_path):
    exp_dir = _make(tmp_path, [], [])
    assert find_process_ymls(exp_dir, process_root=tmp_path / "PROCESSES") == []
