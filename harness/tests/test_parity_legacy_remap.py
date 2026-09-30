"""--remap-legacy-layout: a legacy-layout golden diffed against a unified capture."""

import json
import shutil
import zipfile

import pytest

from harness.classify import normalize_name
from harness.parity import main, run_parity
from harness.tests.synthtree import attach_manifest
from harness.treepass import remap_legacy_layout

SEQ_NAME = "131415__GMTEST__golden"


def _u(n):
    return f"00000000-0000-0000-0000-{n:012d}"


def _write_extra(root, act_dir, kind, first):
    """A non-yml metadata carrier whose ``action_output_dir`` starts ``first``."""
    value = f"{first}/0929/x"
    if kind == "s3":
        d = root / "S3_SIM" / "helao-sim" / "misc"
        d.mkdir(parents=True)
        (d / "info.json").write_text(json.dumps({"action_output_dir": value}))
    elif kind == "hlo":
        (act_dir / "WsSim-0.0.0.0__0.hlo").write_text(
            "hlo_version: '2025.07.07'\n"
            "action_name: WsSim\n"
            f"action_output_dir: {value}\n"
            "column_headings:\n  - t_s\n"
            "epoch_ns: 1752671661000000000\n"
            "%%\n"
            '{"t_s": 0.0}\n'
        )
    elif kind == "images_zip":  # an action's own zip output, not a sequence zip
        with zipfile.ZipFile(act_dir / "images.zip", "w") as zf:
            zf.writestr("a.txt", "frame")
    elif kind == "parquet":
        import pyarrow as pa
        import pyarrow.parquet as pq

        table = pa.table({"t_s": [0.0]}).replace_schema_metadata(
            {"helao_metadata": json.dumps({"action_output_dir": value})}
        )
        pq.write_table(table, str(act_dir / "data.parquet"))


def _write_run(
    root,
    top,
    week_or_year,
    seed=0,
    duration="2.0",
    yml_dirs=None,
    extra=None,
    mmdd="0929",
    seq_name=SEQ_NAME,
):
    """One seq/exp/act run under ``<root>/<top>/<week_or_year>/0929``.

    The *_output_dir values carry the layout's own date levels, exactly as a
    real capture does, unless ``yml_dirs`` overrides that first level.
    """
    yml_first = yml_dirs or week_or_year
    rel_seq = f"{week_or_year}/{mmdd}/{seq_name}"
    rel_exp = f"{rel_seq}/260929.131420__TEST_exp"
    rel_act = f"{rel_exp}/0__0__SIM__acquire_data"
    y_seq = f"{yml_first}/{mmdd}/{seq_name}"
    y_exp = f"{y_seq}/260929.131420__TEST_exp"
    y_act = f"{y_exp}/0__0__SIM__acquire_data"
    seq_dir = root / top / rel_seq
    exp_dir = root / top / rel_exp
    act_dir = root / top / rel_act
    act_dir.mkdir(parents=True)
    if extra:
        _write_extra(root, act_dir, *extra)
    (seq_dir / "260929.131415123456-seq.yml").write_text(
        "file_type: sequence\n"
        f"sequence_uuid: {_u(seed + 1)}\n"
        "sequence_name: GMTEST\n"
        f"sequence_output_dir: {y_seq}\n"
    )
    (exp_dir / "260929.131420123456-exp.yml").write_text(
        "file_type: experiment\n"
        f"experiment_uuid: {_u(seed + 2)}\n"
        f"sequence_uuid: {_u(seed + 1)}\n"
        f"experiment_output_dir: {y_exp}\n"
    )
    (act_dir / "260929.131421123456-act.yml").write_text(
        "file_type: action\n"
        f"action_uuid: {_u(seed + 3)}\n"
        f"experiment_uuid: {_u(seed + 2)}\n"
        f"sequence_uuid: {_u(seed + 1)}\n"
        "action_name: acquire_data\n"
        f"action_output_dir: {y_act}\n"
        f"action_params:\n  duration: {duration}\n"
    )
    return act_dir


def make_legacy_golden(base, extra=None):
    gdir = base / "golden"
    _write_run(gdir / "root", "RUNS_FINISHED", "26.39", extra=extra)
    attach_manifest(gdir)
    return gdir


def make_unified_candidate(base, seed=100, duration="2.0", extra=None):
    cdir = base / "cand"
    _write_run(cdir, "RUNS", "2026", seed=seed, duration=duration, extra=extra)
    return cdir


def test_a_without_flag_legacy_vs_unified_fails_on_tree(tmp_path):
    report = run_parity(make_legacy_golden(tmp_path), make_unified_candidate(tmp_path))
    assert report["status"] == "fail"
    assert report["tree_diffs"]
    assert report["remap_legacy_layout"] is False


def test_b_with_flag_legacy_vs_unified_passes(tmp_path):
    report = run_parity(
        make_legacy_golden(tmp_path),
        make_unified_candidate(tmp_path),
        remap_legacy_layout=True,
    )
    assert report["status"] == "pass", report
    assert report["n_diffs"] == 0
    assert report["remap_legacy_layout"] is True


def test_c_with_flag_a_real_content_change_still_fails(tmp_path):
    report = run_parity(
        make_legacy_golden(tmp_path),
        make_unified_candidate(tmp_path, duration="9.0"),
        remap_legacy_layout=True,
    )
    assert report["status"] == "fail"
    assert report["file_diffs"]


def test_d_same_file_in_finished_and_synced_raises(tmp_path):
    gdir = make_legacy_golden(tmp_path)
    _write_run(gdir / "root", "RUNS_SYNCED", "26.39")
    with pytest.raises(ValueError) as exc:
        run_parity(gdir, make_unified_candidate(tmp_path), remap_legacy_layout=True)
    # both full relative paths, not a substring the source alone satisfies
    src = f"RUNS_SYNCED/26.39/0929/{SEQ_NAME}/260929.131415123456-seq.yml"
    dst = f"RUNS/2026/0929/{SEQ_NAME}/260929.131415123456-seq.yml"
    assert src in str(exc.value)
    assert dst in str(exc.value)


def test_e_token_restored_after_run_and_after_exception(tmp_path):
    gdir = make_legacy_golden(tmp_path)
    cand = make_unified_candidate(tmp_path)
    run_parity(gdir, cand, remap_legacy_layout=True)
    assert normalize_name("26.39") == "YY.WW"
    _write_run(gdir / "root", "RUNS_SYNCED", "26.39")
    with pytest.raises(ValueError):
        run_parity(gdir, cand, remap_legacy_layout=True)
    assert normalize_name("26.39") == "YY.WW"


def test_f_cli_flag_returns_zero_on_matching_pair(tmp_path):
    gdir = make_legacy_golden(tmp_path)
    cand = make_unified_candidate(tmp_path)
    argv = ["--golden", str(gdir), "--candidate", str(cand)]
    assert main(argv) == 1
    assert main(argv + ["--remap-legacy-layout"]) == 0


def _candidate(base, shape):
    """A candidate that is unified EXCEPT for the one thing ``shape`` names.

    Every other output_dir value is unified (``2026``), so each shape can only
    be caught by the check it targets.
    """
    c = base / "cand"
    if shape == "legacy_top":
        _write_run(c, "RUNS_FINISHED", "26.39", seed=100, yml_dirs="2026")
    elif shape == "runs_week_dir":
        _write_run(c, "RUNS", "26.39", seed=100, yml_dirs="2026")
    elif shape == "yml_output_dir":
        _write_run(c, "RUNS", "2026", seed=100, yml_dirs="26.39")
    else:  # s3 / hlo / parquet: the legacy value lives only in that carrier
        _write_run(c, "RUNS", "2026", seed=100, extra=(shape, "26.39"))
    return c


#: shape -> text the finding's detail must contain
SHAPES = {
    "legacy_top": "legacy top RUNS_FINISHED",
    "runs_week_dir": "week dir RUNS/26.39",
    "yml_output_dir": "-seq.yml: output_dir 26.39/",
    "s3": "S3_SIM/helao-sim/misc/info.json: output_dir 26.39/",
    "hlo": ".hlo: output_dir 26.39/",
    "parquet": ".parquet: output_dir 26.39/",
}


@pytest.mark.parametrize("shape", list(SHAPES))
def test_flag_fails_a_candidate_that_is_not_unified(tmp_path, shape):
    extra = (shape, "26.39") if shape in ("s3", "hlo", "parquet") else None
    golden = make_legacy_golden(tmp_path, extra=extra)
    report = run_parity(golden, _candidate(tmp_path, shape), remap_legacy_layout=True)
    assert report["status"] == "fail"
    (finding,) = report["consistency_diffs"]
    assert finding["check"] == "candidate_legacy_layout"
    assert SHAPES[shape] in finding["detail"]
    if shape in ("legacy_top", "runs_week_dir"):
        assert "output_dir" not in finding["detail"]  # check (c) did not fire


def test_candidate_layout_finding_is_not_acceptable(tmp_path):
    gdir = make_legacy_golden(tmp_path)
    from harness.manifest import ProvenanceManifest

    m = ProvenanceManifest.load(gdir)
    m.accepted_consistency_divergences = [{"key_suffix": "", "candidate": None}]
    m.save(gdir)
    cand = _candidate(tmp_path, "legacy_top")
    report = run_parity(gdir, cand, remap_legacy_layout=True)
    assert any(
        c.get("check") == "candidate_legacy_layout" for c in report["consistency_diffs"]
    )


def test_remap_does_not_touch_the_callers_capture(tmp_path):
    gdir = make_legacy_golden(tmp_path)
    run_parity(gdir, make_unified_candidate(tmp_path), remap_legacy_layout=True)
    assert (gdir / "root" / "RUNS_FINISHED" / "26.39").is_dir()
    assert not (gdir / "root" / "RUNS").exists()


def test_remap_moves_diag_analyses_and_merges_run_trees(tmp_path):
    (tmp_path / "RUNS_ACTIVE/26.39/0929/a").mkdir(parents=True)
    (tmp_path / "RUNS_ACTIVE/26.39/0929/a/x.txt").write_text("x")
    (tmp_path / "RUNS_SYNCED/26.39/0929/b").mkdir(parents=True)
    (tmp_path / "RUNS_SYNCED/26.39/0929/b/y.txt").write_text("y")
    (tmp_path / "RUNS_DIAG/26.39/0929").mkdir(parents=True)
    (tmp_path / "RUNS_DIAG/26.39/0929/d.txt").write_text("d")
    (tmp_path / "RUNS_NOSYNC/notaweek").mkdir(parents=True)
    (tmp_path / "ANALYSES/26.39/0929").mkdir(parents=True)
    (tmp_path / "ANALYSES/26.39/0929/z.yml").write_text("z")
    remap_legacy_layout(tmp_path)
    assert (tmp_path / "RUNS/2026/0929/a/x.txt").read_text() == "x"
    assert (tmp_path / "RUNS/2026/0929/b/y.txt").read_text() == "y"
    assert (tmp_path / "DIAG/2026/0929/d.txt").read_text() == "d"
    assert (tmp_path / "RUNS/notaweek").is_dir()  # non-week entries move as is
    assert (tmp_path / "ANALYSES/2026/0929/z.yml").read_text() == "z"
    assert not (tmp_path / "ANALYSES/26.39").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "ANALYSES",
        "DIAG",
        "RUNS",
    ]


def test_remap_is_a_noop_on_a_unified_tree(tmp_path):
    (tmp_path / "RUNS/2026/0929").mkdir(parents=True)
    (tmp_path / "RUNS/2026/0929/f.txt").write_text("f")
    remap_legacy_layout(tmp_path)
    assert (tmp_path / "RUNS/2026/0929/f.txt").read_text() == "f"


@pytest.mark.parametrize(
    "rel, body",
    [
        ("RUNS/2026/0929/garbage.hlo", "not: [an hlo\n%%\n{{{"),
        ("S3_SIM/helao-sim/misc/broken.json", "this is not json"),
    ],
)
def test_candidate_only_unparsable_file_fails_and_report_is_written(
    tmp_path, rel, body
):
    cand = make_unified_candidate(tmp_path)
    bad = cand / rel
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text(body)
    out = tmp_path / "report.json"
    report = run_parity(
        make_legacy_golden(tmp_path), cand, out, remap_legacy_layout=True
    )
    assert report["status"] == "fail"
    assert out.exists()
    (finding,) = [
        c
        for c in report["consistency_diffs"]
        if c.get("check") == "candidate_legacy_layout"
    ]
    assert f"unparsable {rel}:" in finding["detail"]


# --- zipped legacy sequences ---------------------------------------------------
# The legacy syncer zips a fully synced sequence (members relative to the
# sequence dir) into RUNS_SYNCED/<yy.ww>/<mmdd>/<seq>.zip and removes the dir;
# the unified layout never zips.
PRC_IN, PRC_OUT = "0__0__t-prc.yml", "1__0__u-prc.yml"


def _prc(seed):
    return (
        "file_type: process\n"
        f"sequence_uuid: {_u(seed + 1)}\n"
        "process_name: acquire_data\n"
    )


def _zip_seq(seq_dir):
    shutil.make_archive(str(seq_dir), "zip", root_dir=seq_dir)
    shutil.rmtree(seq_dir)


def make_zipped_golden(base, week="26.39", mmdd="0929"):
    """Zipped RUNS_SYNCED sequence with a prc inside the zip and one outside."""
    gdir = base / "golden"
    root = gdir / "root"
    act_dir = _write_run(root, "RUNS_SYNCED", week, mmdd=mmdd)
    seq = root / "RUNS_SYNCED" / week / mmdd / SEQ_NAME
    (act_dir.parent / PRC_IN).write_text(_prc(0))
    _zip_seq(seq)
    proc = root / "PROCESSES" / week / mmdd / SEQ_NAME
    proc.mkdir(parents=True)
    (proc / PRC_OUT).write_text(_prc(0))
    attach_manifest(gdir)
    return gdir


def make_dir_candidate(base, year="2026", mmdd="0929"):
    cdir = base / "cand"
    act_dir = _write_run(cdir, "RUNS", year, seed=100, mmdd=mmdd)
    (act_dir.parent / PRC_IN).write_text(_prc(100))
    (act_dir.parent / PRC_OUT).write_text(_prc(100))
    return cdir


def test_i_zipped_legacy_golden_passes_against_unified_dir(tmp_path):
    report = run_parity(
        make_zipped_golden(tmp_path),
        make_dir_candidate(tmp_path),
        remap_legacy_layout=True,
    )
    assert report["status"] == "pass", report
    assert report["n_diffs"] == 0


def test_ii_zipped_legacy_golden_fails_without_the_flag(tmp_path):
    report = run_parity(make_zipped_golden(tmp_path), make_dir_candidate(tmp_path))
    assert report["status"] == "fail"
    assert report["tree_diffs"]


def test_iii_zip_and_leftover_dir_with_overlapping_file_raises(tmp_path):
    gdir = make_zipped_golden(tmp_path)
    _write_run(gdir / "root", "RUNS_SYNCED", "26.39")  # leftover <seq>/ dir
    with pytest.raises(ValueError) as exc:
        run_parity(gdir, make_dir_candidate(tmp_path), remap_legacy_layout=True)
    seq_yml = "260929.131415123456-seq.yml"
    assert f"RUNS/2026/0929/{SEQ_NAME}.zipdir/{seq_yml}" in str(exc.value)
    assert f"RUNS/2026/0929/{SEQ_NAME}/{seq_yml}" in str(exc.value)


def test_iv_year_boundary_zipped_golden_passes_against_dir(tmp_path):
    # %U week 00: the first days of a year sit in ``26.00``, not ``26.01``
    report = run_parity(
        make_zipped_golden(tmp_path, week="26.00", mmdd="0101"),
        make_dir_candidate(tmp_path, mmdd="0101"),
        remap_legacy_layout=True,
    )
    assert report["status"] == "pass", report


def test_origdir_and_non_sequence_zipdirs_are_left_alone(tmp_path):
    day = tmp_path / "RUNS/2026/0929"
    (day / "131415__S__l.origdir").mkdir(parents=True)
    (day / "131415__S__l.zipdir").mkdir()
    (day / "131415__S__l/260929.131420__E/0__0__A__x/images.zipdir").mkdir(parents=True)
    (day / "notaseq.zipdir").mkdir()  # right depth, wrong name shape
    remap_legacy_layout(tmp_path)
    assert (day / "131415__S__l.origdir").is_dir()
    assert (day / "131415__S__l").is_dir()
    assert not (day / "131415__S__l.zipdir").exists()
    assert (day / "131415__S__l/260929.131420__E/0__0__A__x/images.zipdir").is_dir()
    assert (day / "notaseq.zipdir").is_dir()


def test_z1_action_level_zip_is_not_collapsed(tmp_path):
    """An action's images.zip is not a sequence zip: it stays ``images.zipdir``
    on both sides. Also proves Z2 does not fire on an action-level zip."""
    extra = ("images_zip", None)
    report = run_parity(
        make_legacy_golden(tmp_path, extra=extra),
        make_unified_candidate(tmp_path, extra=extra),
        remap_legacy_layout=True,
    )
    assert report["status"] == "pass", report
    assert report["n_diffs"] == 0


def test_z2_zipped_sequence_in_the_candidate_fails(tmp_path):
    cand = make_dir_candidate(tmp_path)
    _zip_seq(cand / "RUNS" / "2026" / "0929" / SEQ_NAME)
    report = run_parity(make_zipped_golden(tmp_path), cand, remap_legacy_layout=True)
    assert report["status"] == "fail"
    (finding,) = [
        c
        for c in report["consistency_diffs"]
        if c.get("check") == "candidate_legacy_layout"
    ]
    assert f"zipped sequence RUNS/2026/0929/{SEQ_NAME}.zipdir" in finding["detail"]


def test_two_zipped_sequences_across_the_year_boundary(tmp_path):
    a = ("26.52", "1231", "131415__GMTEST__golden")
    b = ("27.00", "0101", "141516__OTHER__golden")
    gdir = tmp_path / "golden"
    for i, (week, mmdd, name) in enumerate((a, b)):
        _write_run(
            gdir / "root", "RUNS_SYNCED", week, seed=10 * i, mmdd=mmdd, seq_name=name
        )
        _zip_seq(gdir / "root" / "RUNS_SYNCED" / week / mmdd / name)
    attach_manifest(gdir)
    cand = tmp_path / "cand"
    for i, (year, (_, mmdd, name)) in enumerate((("2026", a), ("2027", b))):
        _write_run(cand, "RUNS", year, seed=100 + 10 * i, mmdd=mmdd, seq_name=name)
    report = run_parity(gdir, cand, remap_legacy_layout=True)
    assert report["status"] == "pass", report
