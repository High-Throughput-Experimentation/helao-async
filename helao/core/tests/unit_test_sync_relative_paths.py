"""A relocated run tree must not strand the sidecars that describe it.

The production failure this closes, at a station whose ``root`` moved from
``<share>/inst_hlo`` to ``<share>/inst_hlo/DATA``:

    ValueError: '<share>/inst_hlo/RUNS_FINISHED/.../asdep99.SPC' is not in the
    subpath of '<share>/inst_hlo/DATA/RUNS_FINISHED/.../0__0__XRFS__run_XRF'

``asdep99.SPC`` was not missing. It was sitting in that action directory under
the new root the whole time. What was wrong was the ``.prg`` sidecar, written
six days before the move, recording every file by ABSOLUTE path -- a form that
is only true for the root it was written under.

Three things then compounded:

* ``sync_yml`` recomputed the S3 key with ``fp.relative_to(targetdir)``, which
  raises for an old-root path against a new-root targetdir;
* the exception escaped to the ``syncer`` worker, which logs and drops the
  record, leaving it in ``RUNS_FINISHED``;
* ``sweep_pending`` re-enqueues everything in ``RUNS_FINISHED`` at every SYNC
  start, so the same record failed identically at every launch, forever.

Nineteen-nine sidecars on that share carried the stale prefix. Only the three
still in ``RUNS_FINISHED`` could actually fail -- a finished record is never
re-read -- but the format was wrong in all of them.

So paths are recorded relative to the record's own directory now, and absolute
entries loaded from disk are re-anchored on read. Both halves are tested here:
the second is what heals the sidecars that already exist.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from helao.core.drivers.data.sync_driver import Progress  # noqa: E402
from helao.helpers.yml_tools import yml_dumps  # noqa: E402

ACT_YML = """access: hte
action_name: run_XRF
action_uuid: 06a58416-b1fa-79b3-8000-27fa911528b9
run_type: xrfs
technique_name: XRFS
"""


def _build_record(root: Path) -> Path:
    """A minimal finished action directory, and return its yml path."""
    actdir = (
        root
        / "RUNS_FINISHED/26.27/0707/111057__seq/260707.121718__exp/0__0__XRFS__run_XRF"
    )
    actdir.mkdir(parents=True, exist_ok=True)
    yml = actdir / "260707.121718509081-act.yml"
    yml.write_text(ACT_YML)
    (actdir / "asdep99.SPC").write_text("spectrum")
    (actdir / "data-0.hlo").write_text("{}\n")
    return yml


def _sidecar_for(yml: Path) -> Path:
    return Progress(yml).prg


# ---------------------------------------------------------------------------


def test_a_fresh_sidecar_records_paths_relative_to_the_record(tmp_path):
    """The half that stops the bug being created again."""
    yml = _build_record(tmp_path)
    prog = Progress(yml)
    prog.dict["files_pending"] = [prog.relpath(p) for p in yml.parent.glob("*.SPC")]
    assert prog.dict["files_pending"] == ["asdep99.SPC"], prog.dict["files_pending"]
    assert not Path(prog.dict["files_pending"][0]).is_absolute()


def test_relpath_handles_a_file_in_a_subdirectory(tmp_path):
    """Action records rglob, so a recorded path can carry components."""
    yml = _build_record(tmp_path)
    sub = yml.parent / "spectra"
    sub.mkdir()
    (sub / "scan.SPC").write_text("x")
    prog = Progress(yml)
    assert prog.relpath(sub / "scan.SPC") == "spectra/scan.SPC"
    assert prog.abspath("spectra/scan.SPC") == sub / "scan.SPC"


def test_abspath_resolves_against_the_current_root(tmp_path):
    yml = _build_record(tmp_path)
    prog = Progress(yml)
    assert prog.abspath("asdep99.SPC") == yml.parent / "asdep99.SPC"
    assert prog.abspath("asdep99.SPC").exists()


def test_a_sidecar_written_under_an_old_root_is_reanchored_on_read(tmp_path):
    """The migration half -- the production case, reproduced.

    The sidecar is written with the absolute paths a PRE-move syncer would
    have recorded, then opened against the relocated tree. Nothing about the
    record moved except the root prefix, which is exactly what happened on the
    share.
    """
    new_root = tmp_path / "inst_hlo" / "DATA"
    yml = _build_record(new_root)

    old_actdir = (
        tmp_path
        / "inst_hlo/RUNS_FINISHED/26.27/0707/111057__seq/260707.121718__exp/0__0__XRFS__run_XRF"
    )
    stale = {
        "yml": str(old_actdir / yml.name),
        "api": False,
        "s3": False,
        "files_pending": [str(old_actdir / "asdep99.SPC")],
        "files_s3": {str(old_actdir / "data-0.hlo"): "raw_data/uuid/data-0.hlo.json"},
    }
    prg = _sidecar_for(yml)
    prg.parent.mkdir(parents=True, exist_ok=True)
    prg.write_text(yml_dumps(stale))

    prog = Progress(yml)

    assert prog.dict["files_pending"] == ["asdep99.SPC"]
    assert prog.dict["files_s3"] == {"data-0.hlo": "raw_data/uuid/data-0.hlo.json"}
    # the yml pointer is restated against the root this Progress resolved
    assert prog.dict["yml"] == str(yml)
    # and the re-anchored entry now names a file that is really there
    assert prog.abspath(prog.dict["files_pending"][0]).exists()


def test_the_reanchored_entry_no_longer_raises_relative_to(tmp_path):
    """The precise call that failed in production.

    ``sync_yml`` built the S3 key with ``fp.relative_to(prog.yml.targetdir)``.
    Asserted directly, because a passing sync test could hide this behind a
    mock while the real arithmetic still threw.
    """
    new_root = tmp_path / "inst_hlo" / "DATA"
    yml = _build_record(new_root)
    old = (
        tmp_path
        / "inst_hlo/RUNS_FINISHED/26.27/0707/111057__seq/260707.121718__exp/0__0__XRFS__run_XRF"
        / "asdep99.SPC"
    )
    prg = _sidecar_for(yml)
    prg.parent.mkdir(parents=True, exist_ok=True)
    prg.write_text(
        yml_dumps(
            {
                "yml": str(yml),
                "api": False,
                "s3": False,
                "files_pending": [str(old)],
                "files_s3": {},
            }
        )
    )

    prog = Progress(yml)
    sp = prog.dict["files_pending"][0]
    # relative_to on the pre-fix path object is what raised
    try:
        Path(str(old)).relative_to(prog.yml.targetdir)
        raise AssertionError("precondition: the stale path should not be relative-able")
    except ValueError:
        pass
    # after re-anchoring, the recorded form IS the S3 key suffix, no arithmetic
    assert sp == "asdep99.SPC"
    assert prog.abspath(sp).relative_to(prog.yml.targetdir).as_posix() == sp


def test_an_unplaceable_path_is_left_alone_rather_than_guessed(tmp_path):
    """A wrong guess would point the uploader at another action's data.

    Left absolute, it fails loudly at the next ``stat``; rewritten to something
    plausible, it would upload the wrong bytes under this action's uuid.
    """
    yml = _build_record(tmp_path)
    prog = Progress(yml)
    alien = "/somewhere/else/entirely/unrelated.SPC"
    assert prog.relpath(alien) == alien
    assert prog.abspath(alien) == Path(alien)


def test_reanchor_reports_whether_it_changed_anything(tmp_path):
    """So a caller can tell a healed sidecar from an already-clean one."""
    yml = _build_record(tmp_path)
    prog = Progress(yml)
    prog.dict["files_pending"] = ["asdep99.SPC"]
    prog.dict["files_s3"] = {}
    assert prog.reanchor_recorded_paths() is False
    prog.dict["files_pending"] = [str(yml.parent / "asdep99.SPC")]
    assert prog.reanchor_recorded_paths() is True
    assert prog.dict["files_pending"] == ["asdep99.SPC"]


def sync_relative_path_unit_test() -> bool:
    """Runner for the standalone ``__main__`` style used across this directory."""
    import tempfile

    passed = 0
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        with tempfile.TemporaryDirectory() as td:
            fn(Path(td))
        passed += 1
    print(f"sync relative-path unit test: {passed}/{len(tests)} PASS")
    return passed == len(tests)


if __name__ == "__main__":
    raise SystemExit(0 if sync_relative_path_unit_test() else 1)
