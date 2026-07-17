"""Tree snapshot, member-set diff, zip exploding, and capture-independent seeding."""

import zipfile

from harness.classify import ArtifactRow
from harness.tests.synthtree import build_tree
from harness.treepass import (
    diff_member_sets,
    explode_zips,
    seed_mapper,
    snapshot,
)
from harness.uuidmap import UuidMapper


def test_snapshot_normalizes_names_and_classifies(tmp_path):
    build_tree(tmp_path)
    m = UuidMapper()
    seed_mapper(tmp_path, m)
    snap = snapshot(tmp_path, m)
    key = (
        "RUNS_FINISHED/YY.WW/MMDD/TS__GMTEST__golden/TS__TEST_exp/"
        "0__0__SIM__acquire_data/TS-act.yml"
    )
    assert key in snap.files
    assert snap.files[key][1] is ArtifactRow.ACT_YML
    hlo_key = (
        "RUNS_FINISHED/YY.WW/MMDD/TS__GMTEST__golden/TS__TEST_exp/"
        "0__0__SIM__acquire_data/WsSim-0.0.0.0__0.hlo"
    )
    assert snap.files[hlo_key][1] is ArtifactRow.HLO


def test_two_seeds_produce_identical_member_sets(tmp_path):
    ga, gb = tmp_path / "a", tmp_path / "b"
    build_tree(ga, seed=0)
    build_tree(gb, seed=100)
    ma, mb = UuidMapper(), UuidMapper()
    seed_mapper(ga, ma)
    seed_mapper(gb, mb)
    assert diff_member_sets(snapshot(ga, ma), snapshot(gb, mb)) == []


def test_missing_file_shows_in_member_diff(tmp_path):
    ga, gb = tmp_path / "a", tmp_path / "b"
    ids_a = build_tree(ga, seed=0)
    build_tree(gb, seed=100)
    (ids_a["act_dir"] / "WsSim-0.0.0.0__0.hlo").unlink()
    ma, mb = UuidMapper(), UuidMapper()
    seed_mapper(ga, ma)
    seed_mapper(gb, mb)
    diffs = diff_member_sets(snapshot(ga, ma), snapshot(gb, mb))
    assert len(diffs) == 1
    assert diffs[0]["golden"] == "absent" and diffs[0]["candidate"] == "present"


def test_explode_zips_expands_sequence_zips(tmp_path):
    root = tmp_path / "root"
    ids = build_tree(root)
    # zip the sequence dir the way the syncer does (entries relative to it),
    # then delete the dir — RUNS_SYNCED end state (spec §5.2 row 10).
    synced = root / "RUNS_SYNCED" / "25.28" / "0716"
    synced.mkdir(parents=True)
    zpath = synced / "131415__GMTEST__golden.zip"
    seq_dir = ids["seq_dir"]
    with zipfile.ZipFile(zpath, "w") as zf:
        for f in sorted(seq_dir.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(seq_dir).as_posix())
    exploded = explode_zips(root, tmp_path / "work")
    zipdir = (
        exploded / "RUNS_SYNCED" / "25.28" / "0716" / "131415__GMTEST__golden.zipdir"
    )
    assert zipdir.is_dir()
    assert (zipdir / "250716.131415123456-seq.yml").is_file()
    assert not (
        exploded / "RUNS_SYNCED" / "25.28" / "0716" / "131415__GMTEST__golden.zip"
    ).exists()


def test_seeded_ordinals_are_capture_independent(tmp_path):
    # seq yml seeds before exp before act regardless of raw uuid sort order,
    # so links map to the same ordinals in both captures.
    ga, gb = tmp_path / "a", tmp_path / "b"
    build_tree(ga, seed=0)
    build_tree(gb, seed=500)
    ma, mb = UuidMapper(), UuidMapper()
    seed_mapper(ga, ma)
    seed_mapper(gb, mb)
    from harness.tests.synthtree import _u

    assert ma.map(_u(1)) == mb.map(_u(501))  # sequence_uuid -> same ordinal
    assert ma.map(_u(3)) == mb.map(_u(503))  # action_uuid -> same ordinal
