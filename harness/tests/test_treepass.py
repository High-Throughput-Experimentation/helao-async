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
from helao.helpers.yml_tools import yml_dumps


def _write_analyses(root, records):
    """Write ``records`` as one conversion's analysis ymls under ``root``."""
    d = root / "ANALYSES" / "26.31" / "0808" / "181340__AN__lbl"
    d.mkdir(parents=True)
    for uuid_str, label, process_uuid in records:
        (d / f"{uuid_str}.yml").write_text(
            yml_dumps(
                {
                    "analysis_uuid": uuid_str,
                    "analysis_name": "AN",
                    "global_sample_label": label,
                    "process_uuid": process_uuid,
                    "analysis_params": {"a": 1},
                }
            )
        )
    return d


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


def test_analysis_ordinals_follow_record_identity_not_uuid_order(tmp_path):
    """Two captures of one conversion map the same RECORD to the same ordinal.

    Analysis uuids are content hashes, so they sort arbitrarily; every record of
    a conversion also blanks to the identical normalized path. Without an
    identity tiebreak the two sides would pair record A's ordinal with record
    B's file and report the mismatch as content diffs.
    """
    ga, gb = tmp_path / "a", tmp_path / "b"
    # Same three records, uuids in DELIBERATELY opposite lexical order.
    _write_analyses(
        ga,
        [
            ("aaaaaaaa-0000-4000-8000-000000000001", "s1", "p1"),
            ("bbbbbbbb-0000-4000-8000-000000000002", "s2", "p2"),
            ("cccccccc-0000-4000-8000-000000000003", "s3", "p3"),
        ],
    )
    _write_analyses(
        gb,
        [
            ("cccccccc-0000-4000-8000-000000000013", "s1", "p1"),
            ("bbbbbbbb-0000-4000-8000-000000000012", "s2", "p2"),
            ("aaaaaaaa-0000-4000-8000-000000000011", "s3", "p3"),
        ],
    )
    ma, mb = UuidMapper(), UuidMapper()
    seed_mapper(ga, ma)
    seed_mapper(gb, mb)
    for a_uuid, b_uuid in (
        (
            "aaaaaaaa-0000-4000-8000-000000000001",
            "cccccccc-0000-4000-8000-000000000013",
        ),
        (
            "bbbbbbbb-0000-4000-8000-000000000002",
            "bbbbbbbb-0000-4000-8000-000000000012",
        ),
        (
            "cccccccc-0000-4000-8000-000000000003",
            "aaaaaaaa-0000-4000-8000-000000000011",
        ),
    ):
        assert ma.map(a_uuid) == mb.map(b_uuid)
    assert diff_member_sets(snapshot(ga, ma), snapshot(gb, mb)) == []
