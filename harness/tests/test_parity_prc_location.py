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


def _mixed_zipdir_and_origdir_tree(root: Path) -> Path:
    """One tree holding BOTH the live in-zip copy of a process (already
    exploded to a ``.zipdir``) and its reset_sync pre-reset backup (already
    exploded to a ``.origdir``) -- the shape a real reset_sync round trip
    produces (see ``explode_zips``). The two copies are byte-identical, so
    only the container-prefix rule can tell them apart; this is the case
    the ``.origdir``-only prefix in ``snapshot`` exists for."""
    zipdir = (
        root
        / "RUNS_SYNCED"
        / "26.35"
        / "0828"
        / "115959__seq.zipdir"
        / "260828.120000__exp"
    )
    zipdir.mkdir(parents=True)
    (zipdir / PRC).write_text(BODY)

    origdir = (
        root
        / "RUNS_SYNCED"
        / "26.35"
        / "0828"
        / "115959__seq.origdir"
        / "260828.120000__exp"
    )
    origdir.mkdir(parents=True)
    (origdir / PRC).write_text(BODY)
    return root


def test_zipdir_and_origdir_copies_of_the_same_prc_key_distinctly(tmp_path):
    """Hermetic (no golden fixtures) counterpart to the two tests above: a
    byte-identical prc reachable through BOTH an exploded ``.zipdir`` (the
    live copy) and an exploded ``.origdir`` (its reset_sync backup) in the
    SAME tree must key to two DIFFERENT strings. The existing two tests
    above only ever put one container shape in a tree at a time, so neither
    exercises the collision this narrow ``.origdir``-only rule prevents:
    deleting the ``if tok.endswith(".origdir")`` guard (leaving `container`
    always ``""``) makes both copies key to the bare ``PRC/<name>`` string,
    and ``snapshot`` raises a normalized-name collision instead of quietly
    merging two real, distinct files.
    """
    tree = _mixed_zipdir_and_origdir_tree(tmp_path / "mixed")
    mapper = UuidMapper()
    seed_mapper(tree, mapper)
    snap = snapshot(tree, mapper)
    prc_keys = [k for k in snap.files if k.startswith("PRC/")]
    assert len(prc_keys) == 2, prc_keys
    assert len(set(prc_keys)) == 2, f"prc keys collided: {prc_keys}"
    bare = [k for k in prc_keys if not k.startswith("PRC/TS")]
    origdir_prefixed = [k for k in prc_keys if "origdir/" in k]
    assert len(bare) == 1, prc_keys
    assert len(origdir_prefixed) == 1, prc_keys
    assert not any("zipdir" in k for k in prc_keys), prc_keys


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
