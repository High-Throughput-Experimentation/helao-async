"""station_golden_capture.py: a station run tree -> a golden set the parity gate accepts."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from harness.manifest import ProvenanceManifest
from harness.parity import run_parity
from harness.tests.test_parity_legacy_remap import SEQ_NAME, _u, _write_run

HELPER = (
    Path(__file__).resolve().parents[2]
    / "helao/hexagon/tests/smoke/station_golden_capture.py"
)
PRC = "0__0__t-prc.yml"


def _stamp_version(seq_dir, version):
    (next(seq_dir.glob("*-seq.yml"))).open("a").write(f"hlo_version: {version}\n")


def _prc(seed):
    return (
        "file_type: process\n"
        f"sequence_uuid: {_u(seed + 1)}\n"
        "process_name: acquire_data\n"
    )


def legacy_root(base, zipped=False, version="1e10"):
    """RUNS_SYNCED run + one matching and one unrelated PROCESSES prc."""
    root = base / "legacy_root"
    _write_run(root, "RUNS_SYNCED", "26.39")
    seq = root / "RUNS_SYNCED/26.39/0929" / SEQ_NAME
    _stamp_version(seq, version)
    proc = root / "PROCESSES/26.39/0929" / SEQ_NAME
    proc.mkdir(parents=True)
    (proc / PRC).write_text(_prc(0))
    (proc / "1__0__other-prc.yml").write_text(_prc(50))
    # a foreign process that merely mentions our sequence_uuid in its params
    (proc / "2__0__mention-prc.yml").write_text(
        _prc(50) + f"process_params:\n  sequence_uuid: {_u(1)}\n  ref: {_u(1)}\n"
    )
    if zipped:  # members stored relative to the sequence dir, as the syncer wrote
        shutil.make_archive(str(seq), "zip", root_dir=seq)
        shutil.rmtree(seq)
    return root


def unified_root(base, version="1e10"):
    """RUNS run of the same sequence, its prc inside the run tree."""
    root = base / "unified_root"
    _write_run(root, "RUNS", "2026")
    seq = root / "RUNS/2026/0929" / SEQ_NAME
    _stamp_version(seq, version)
    (seq / "260929.131420__TEST_exp" / PRC).write_text(_prc(0))
    return root


def capture(root, out, seq=SEQ_NAME, prefix="eche10_hex"):
    return subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "--root",
            str(root),
            "--seq",
            seq,
            "--out",
            str(out),
            "--config-prefix",
            prefix,
        ],
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("zipped", [False, True])
def test_legacy_pre_unified_post_passes_parity(tmp_path, zipped):
    pre, post = tmp_path / "pre", tmp_path / "post"
    r = capture(legacy_root(tmp_path, zipped), pre)
    assert r.returncode == 0, r.stderr
    assert "layout=legacy" in r.stdout and "prc=1" in r.stdout
    # the unified layout never zips: a zipped legacy golden meets a plain dir
    assert capture(unified_root(tmp_path), post).returncode == 0

    m = ProvenanceManifest.load(pre)  # (i)
    assert m.scenario == "eche10_hex-smoke"
    assert m.config_path == "helao/deploy/hte/configs/eche10_hex.py"
    assert m.launch_cmd == "python launch.py eche10_hex --no-hot-reload"
    assert m.sequence_name == "GMTEST"
    assert m.sequence_params == {}
    assert m.harness_version == "station_golden_capture"
    assert m.legacy_git_sha == "1e10"  # (v) a sha-like value stays a string
    assert isinstance(m.legacy_git_sha, str)

    prcs = sorted(p.name for p in (pre / "root/PROCESSES").rglob("*-prc.yml"))
    assert prcs == [PRC]  # (ii) the unrelated process is not copied

    report = run_parity(pre, post, remap_legacy_layout=True)  # (iii)
    assert report["status"] == "pass", report


def test_non_hex_prefix_gets_yml_config_path(tmp_path):
    r = capture(unified_root(tmp_path), tmp_path / "o", prefix="plain")
    assert r.returncode == 0, r.stderr
    m = ProvenanceManifest.load(tmp_path / "o")
    assert m.config_path == "helao/deploy/hte/configs/plain.yml"


def test_unified_dir_and_zip_both_copied(tmp_path):
    root = unified_root(tmp_path)
    seq = root / "RUNS/2026/0929" / SEQ_NAME
    shutil.make_archive(str(seq), "zip", seq.parent, SEQ_NAME)
    r = capture(root, tmp_path / "o")
    assert r.returncode == 0, r.stderr
    got = tmp_path / "o/root/RUNS/2026/0929"
    assert (got / SEQ_NAME).is_dir() and (got / f"{SEQ_NAME}.zip").is_file()
    assert "layout=unified" in r.stdout and "prc=0" in r.stdout


def _refused(r, text):
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert text in r.stderr


def test_refuses_existing_out(tmp_path):
    (tmp_path / "o").mkdir()
    _refused(capture(unified_root(tmp_path), tmp_path / "o"), "already exists")


def test_refuses_sequence_not_found(tmp_path):
    r = capture(unified_root(tmp_path), tmp_path / "o", seq="nope__x")
    _refused(r, "not found")
    assert not (tmp_path / "o").exists()


def test_refuses_sequence_in_runs_active(tmp_path):
    root = legacy_root(tmp_path)
    shutil.move(root / "RUNS_SYNCED", root / "RUNS_ACTIVE")
    r = capture(root, tmp_path / "o")
    _refused(r, "RUNS_ACTIVE")
    assert not (tmp_path / "o").exists()


def test_refuses_sequence_in_both_layouts(tmp_path):
    root = unified_root(tmp_path)
    _write_run(root, "RUNS_FINISHED", "26.39")
    r = capture(root, tmp_path / "o")
    _refused(r, "both layouts")
    assert not (tmp_path / "o").exists()


def test_refuses_out_inside_root(tmp_path):
    root = unified_root(tmp_path)
    r = capture(root, root / "goldens" / "pre")
    _refused(r, "inside")
    assert not (root / "goldens").exists()
    r = capture(root, root / "sub" / ".." / "pre")  # resolved before comparing
    _refused(r, "inside")


def test_seq_is_not_a_glob(tmp_path):
    r = capture(unified_root(tmp_path), tmp_path / "o", seq="*")
    _refused(r, "not found")
    assert not (tmp_path / "o").exists()


def test_cr_separated_seq_yml_in_zip_and_full_path_seq(tmp_path):
    """eche10, 2026-09-30: the zip's -seq.yml plainly held sequence_uuid, but a
    `^...$` re.M search only knows "\\n" and missed it; a full path was also
    globbed verbatim and crashed pathlib."""
    root = legacy_root(tmp_path)
    seq = root / "RUNS_SYNCED/26.39/0929" / SEQ_NAME
    yml = next(seq.glob("*-seq.yml"))
    yml.write_bytes(yml.read_bytes().replace(b"\n", b"\r"))
    shutil.make_archive(str(seq), "zip", root_dir=seq)
    shutil.rmtree(seq)
    r = capture(root, tmp_path / "out", seq=str(seq) + ".zip")
    assert r.returncode == 0, r.stderr
    assert "prc=1" in r.stdout


def test_nosync_dir_without_seq_yml_does_not_hide_the_zip(tmp_path):
    """eche10, 2026-09-30: a sync_data=False sequence leaves a same-name
    RUNS_NOSYNC dir holding only .hlo files; it sorted ahead of the zip and its
    missing -seq.yml read as "no sequence_uuid"."""
    root = legacy_root(tmp_path, zipped=True)
    nosync = root / "RUNS_NOSYNC/26.39/0929" / SEQ_NAME / "exp" / "act"
    nosync.mkdir(parents=True)
    (nosync / "data.hlo").write_text("x")
    r = capture(root, tmp_path / "out")
    assert r.returncode == 0, r.stderr
    assert "prc=1" in r.stdout
    assert (tmp_path / "out/root/RUNS_NOSYNC/26.39/0929" / SEQ_NAME).is_dir()
