"""A -prc.yml compares equal whether it sits in PROCESSES or inside a zip."""

from pathlib import Path

from harness.treepass import seed_mapper, snapshot
from harness.uuidmap import UuidMapper

PRC = "0__06a5a2d6-b26c-7019-8000-4c2d967e5df1__SIM_exp-prc.yml"
BODY = "process_uuid: 06a5a2d6-b26c-7019-8000-4c2d967e5df1\n"


def _legacy_tree(root: Path) -> Path:
    d = (
        root
        / "PROCESSES"
        / "26.35"
        / "0828"
        / "260828.115959__seq"
        / "260828.120000__exp"
    )
    d.mkdir(parents=True)
    (d / PRC).write_text(BODY)
    return root


def _colocated_tree(root: Path) -> Path:
    d = (
        root
        / "RUNS_SYNCED"
        / "26.35"
        / "0828"
        / "260828.115959__seq"
        / "260828.120000__exp"
    )
    d.mkdir(parents=True)
    (d / PRC).write_text(BODY)
    return root


def test_prc_key_is_the_same_in_both_locations(tmp_path):
    legacy = _legacy_tree(tmp_path / "legacy")
    colocated = _colocated_tree(tmp_path / "colocated")
    mg, mc = UuidMapper(), UuidMapper()
    seed_mapper(legacy, mg)
    seed_mapper(colocated, mc)
    g = snapshot(legacy, mg)
    c = snapshot(colocated, mc)
    assert set(g.files) == set(
        c.files
    ), f"prc keys differ: golden={sorted(g.files)} candidate={sorted(c.files)}"
