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


def _colocated_zipdir_tree(root: Path) -> Path:
    """The production shape: a synced sequence is zipped, so a live prc is
    never a bare file under RUNS_SYNCED (as ``_colocated_tree`` above builds)
    -- it sits inside the exploded zip. Directory name must match
    ``harness.classify.RE_SEQ_ZIPDIR`` (``\\d{6}__....zipdir``) so
    ``normalize_name`` actually tokenizes it as a zipdir, the way
    ``explode_zips`` produces one from a real ``.zip``."""
    d = (
        root
        / "RUNS_SYNCED"
        / "26.35"
        / "0828"
        / "115959__seq.zipdir"
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


def test_prc_key_matches_the_legacy_mirror_even_inside_an_exploded_zipdir(tmp_path):
    """The shape a real synced record actually has: a live prc reaches
    snapshot() only after explode_zips expands its sequence's ``.zip`` into a
    ``.zipdir`` (a bare-file colocated tree, as the previous test builds, is
    never what production produces -- the sequence directory is zipped and
    removed). This must still key identically to the legacy PROCESSES
    mirror, or the golden gate compares a real synced process against
    nothing (present/absent) instead of field-by-field.

    This is the case that a too-broad zipdir-or-origdir container prefix
    breaks: prefixing on ``.zipdir`` applies to every real post-move prc
    unconditionally (a live prc is ALWAYS inside a zipdir in production),
    making the legacy mirror's bare ``PRC/<name>`` key permanently
    unreachable. Only an ``.origdir`` ancestor (a reset_sync backup) should
    change the key.
    """
    legacy = _legacy_tree(tmp_path / "legacy")
    zipdir_tree = _colocated_zipdir_tree(tmp_path / "zipdir")
    mg, mc = UuidMapper(), UuidMapper()
    seed_mapper(legacy, mg)
    seed_mapper(zipdir_tree, mc)
    g = snapshot(legacy, mg)
    c = snapshot(zipdir_tree, mc)
    assert set(g.files) == set(
        c.files
    ), f"prc keys differ: legacy={sorted(g.files)} zipdir={sorted(c.files)}"
