"""Tests for the ``.prg`` staging-file scanner.

Two properties carry the weight here, because both fail *silently* into a clean
result:

* the cheap prefilter must never reject a document a full parse would have
  flagged -- a false negative there reports an archive as clean without ever
  looking at it;
* an unreadable directory must make the scan incomplete and the exit non-zero --
  the original sweep of a production archive was run over a network mount, lost
  most of the tree to transient errors, and reported success.
"""

import os
import stat
import zipfile
from pathlib import Path

import pytest

from helao.core.drivers.data.sync_driver import HelaoYml
from helao.core.tests.scan_prg_ghosts import (
    Findings,
    _might_hold_ghost,
    is_staging_name,
    main,
    scan_prg_text,
    scan_root,
)

# The four names actually found in the production archive on 2026-08-27, plus
# the shapes the exclusion is written to catch in general.
REAL_GHOSTS = [
    ".xafs_normal-0.0.0.0__0.hlo.ec4443f6a1b411f1b62eb07b2514b8fc.tmp",
    ".xafs_normal-0.0.0.0__0.hlo.eb85dedea1b411f1bb30b07b2514b8fc.tmp",
    ".xafs_normal-0.0.0.0__0.hlo.ed5e4d90a1b411f1bb30b07b2514b8fc.tmp",
    ".xrfs_nostds-0.0.0.0__2.hlo.b6d18b5c95f211f1a688b07b2514b8fc.tmp",
]
OTHER_GHOSTS = [
    "staged.tmp",  # .tmp suffix without the dotfile convention
    ".hidden_bookkeeping",  # dotfile without the .tmp suffix
    "sub/dir/.partial.hlo.abc123.tmp",  # nested
    "/abs/path/.partial.hlo.abc123.tmp",  # absolute, pre-relocation shape
    r"C:\INST_hlo\RUNS\.partial.hlo.abc.tmp",  # Windows separators
]
REAL_DATA = [
    "xafs_normal-0.0.0.0__0.hlo",
    "xrfs_nostds-0.0.0.0__2.hlo",
    "raw_original.raw",
    "X0-098-0001.npz",
    "annealed12.SPC",
    "sub/dir/data.npz",
    "0.5.txt",  # a dotted number must not read as a dotfile
]


def _prg(files_s3=None, files_pending=None) -> str:
    """A ``.prg`` document shaped like the ones the syncer writes."""
    lines = ["yml: /data/RUNS_SYNCED/x/y-act.yml", "status: synced"]
    lines.append("files_s3:")
    for name, key in (files_s3 or {}).items():
        lines.append(f"  {name}: {key}")
    if not files_s3:
        lines[-1] = "files_s3: {}"
    lines.append("files_pending:")
    for name in files_pending or []:
        lines.append(f"  - {name}")
    if not files_pending:
        lines[-1] = "files_pending: []"
    return "\n".join(lines) + "\n"


class TestIsStagingName:
    @pytest.mark.parametrize("name", REAL_GHOSTS + OTHER_GHOSTS)
    def test_flags_staging_names(self, name):
        assert is_staging_name(name)

    @pytest.mark.parametrize("name", REAL_DATA)
    def test_leaves_real_data_alone(self, name):
        assert not is_staging_name(name)

    @pytest.mark.parametrize("name", REAL_GHOSTS + OTHER_GHOSTS + REAL_DATA)
    def test_agrees_with_the_uploader_exclusion(self, name, tmp_path):
        """Pin to ``HelaoYml._is_syncable_misc_file`` so the two cannot drift.

        The scanner reports what the uploader would now refuse to record. If
        that method's rule is ever loosened or tightened, this fails rather than
        letting the diagnostic quietly disagree with the code it diagnoses.
        """
        target = tmp_path / Path(name.replace("\\", "/")).name
        target.write_text("x")
        syncable = HelaoYml._is_syncable_misc_file(target)
        if is_staging_name(name):
            # Everything this reports must be something the uploader refuses.
            assert not syncable
        elif target.suffix not in (".yml", ".hlo", ".lock"):
            # And the converse, except for the three suffixes that method also
            # excludes for an unrelated reason -- they have their own upload
            # paths and are not staging files.
            assert syncable


class TestPrefilter:
    """The prefilter is an optimization; a false negative is a silent miss."""

    @pytest.mark.parametrize("name", REAL_GHOSTS + OTHER_GHOSTS)
    def test_never_rejects_a_document_holding_a_ghost(self, name):
        # Both shapes a ghost can appear in, checked independently.
        assert _might_hold_ghost(_prg(files_s3={name: "raw_data/uuid/x"}))
        assert _might_hold_ghost(_prg(files_pending=[name]))

    def test_rejects_an_ordinary_document(self):
        text = _prg(
            files_s3={n: f"raw_data/uuid/{n}" for n in REAL_DATA},
            files_pending=list(REAL_DATA),
        )
        assert not _might_hold_ghost(text)

    def test_a_dotted_number_is_not_a_dotfile(self):
        assert not _might_hold_ghost("progress: 0.5\nitems:\n  - 1.25\n")


class TestLoaderEquivalence:
    """The PyYAML fallback must read a .prg identically to the project loader.

    The fallback exists so the scanner runs on the host that owns the data,
    where only a stock python may be available. That is only sound if both
    loaders agree on the documents it reads.
    """

    def test_both_loaders_agree_on_a_prg_document(self):
        import yaml

        from helao.helpers.yml_tools import yml_load

        text = _prg(
            files_s3={
                REAL_GHOSTS[0]: "raw_data/a/x.tmp",
                "xafs_normal-0.0.0.0__0.hlo": "raw_data/real/x.json",
            },
            files_pending=[REAL_GHOSTS[3], "real_pending.npz"],
        )
        assert yaml.safe_load(text) == yml_load(text, fast=True)

    def test_the_scanner_finds_the_same_ghosts_under_the_fallback(self, monkeypatch):
        import yaml

        import helao.core.tests.scan_prg_ghosts as module

        text = _prg(
            files_s3={REAL_GHOSTS[0]: "raw_data/a/x.tmp"},
            files_pending=[REAL_GHOSTS[3]],
        )
        monkeypatch.setattr(module, "_parse_yaml", yaml.safe_load)
        found = Findings()
        module.scan_prg_text(text, "label", found)
        assert len(found.uploaded) == 1 and len(found.pending) == 1


class TestScanPrgText:
    def test_finds_an_uploaded_ghost_with_its_key(self):
        found = Findings()
        name = REAL_GHOSTS[0]
        scan_prg_text(_prg(files_s3={name: "raw_data/abc/x.tmp"}), "label", found)
        assert found.uploaded == [("label", name, "raw_data/abc/x.tmp")]
        assert not found.pending
        assert found.n_ghosts == 1

    def test_finds_a_pending_ghost(self):
        found = Findings()
        scan_prg_text(_prg(files_pending=[REAL_GHOSTS[3]]), "label", found)
        assert found.pending == [("label", REAL_GHOSTS[3])]
        assert found.n_ghosts == 1

    def test_finds_two_ghosts_in_one_record(self):
        """One action raced twice in production; both must be reported."""
        found = Findings()
        text = _prg(
            files_s3={
                "xafs_normal-0.0.0.0__0.hlo": "raw_data/real/x.json",
                REAL_GHOSTS[1]: "raw_data/a/x.tmp",
                REAL_GHOSTS[2]: "raw_data/b/x.tmp",
            }
        )
        scan_prg_text(text, "label", found)
        assert len(found.uploaded) == 2

    def test_ignores_a_clean_record(self):
        found = Findings()
        scan_prg_text(
            _prg(files_s3={"data.hlo": "raw_data/uuid/data.hlo.json"}), "l", found
        )
        assert found.n_ghosts == 0

    def test_a_damaged_document_is_a_finding_not_a_crash(self):
        found = Findings()
        scan_prg_text("files_s3: {\n  .x.tmp: [unclosed\n", "label", found)
        assert found.unparseable and found.n_ghosts == 0


class TestScanRoot:
    def test_reads_loose_prg_and_zipped_prg(self, tmp_path):
        (tmp_path / "a").mkdir()
        (tmp_path / "a" / "x-act.prg").write_text(
            _prg(files_s3={REAL_GHOSTS[0]: "raw_data/a/x.tmp"})
        )
        zip_path = tmp_path / "seq.zip"
        with zipfile.ZipFile(zip_path, "w") as archive:
            archive.writestr("inner/y-act.prg", _prg(files_pending=[REAL_GHOSTS[3]]))
            archive.writestr("inner/y-act.yml", "not: a prg\n")
        found = Findings()
        scan_root(str(tmp_path), found)
        assert (found.n_prg, found.n_zip) == (1, 1)
        assert len(found.uploaded) == 1 and len(found.pending) == 1
        assert found.complete

    def test_a_clean_tree_reports_complete_and_empty(self, tmp_path):
        (tmp_path / "x-act.prg").write_text(_prg(files_s3={"d.hlo": "raw_data/u/d"}))
        found = Findings()
        scan_root(str(tmp_path), found)
        assert found.n_ghosts == 0 and found.complete and found.n_prg == 1

    def test_a_damaged_zip_is_reported_not_raised(self, tmp_path):
        (tmp_path / "broken.zip").write_bytes(b"not a zip at all")
        found = Findings()
        scan_root(str(tmp_path), found)
        assert found.bad_zips and found.complete

    def test_nested_directories_are_walked(self, tmp_path):
        deep = tmp_path / "26.33" / "0820" / "seq" / "exp" / "act"
        deep.mkdir(parents=True)
        (deep / "z-act.prg").write_text(_prg(files_pending=[REAL_GHOSTS[1]]))
        found = Findings()
        scan_root(str(tmp_path), found)
        assert found.n_prg == 1 and len(found.pending) == 1

    @pytest.mark.skipif(os.geteuid() == 0, reason="root can read any directory")
    def test_an_unreadable_directory_makes_the_scan_incomplete(self, tmp_path):
        """The failure that made the first production sweep report a clean lie."""
        blocked = tmp_path / "blocked"
        blocked.mkdir()
        (blocked / "hidden-act.prg").write_text(
            _prg(files_s3={REAL_GHOSTS[0]: "raw_data/a/x.tmp"})
        )
        blocked.chmod(0o000)
        try:
            found = Findings()
            scan_root(str(tmp_path), found)
            assert not found.complete
            assert any("blocked" in path for path, _ in found.unreadable)
        finally:
            blocked.chmod(stat.S_IRWXU)


class TestMainExitStatus:
    def test_clean_tree_exits_zero(self, tmp_path, capsys):
        (tmp_path / "x-act.prg").write_text(_prg(files_s3={"d.hlo": "raw_data/u/d"}))
        assert main([str(tmp_path)]) == 0
        assert "No staging files recorded" in capsys.readouterr().out

    def test_a_ghost_exits_one(self, tmp_path, capsys):
        (tmp_path / "x-act.prg").write_text(
            _prg(files_s3={REAL_GHOSTS[0]: "raw_data/a/x.tmp"})
        )
        assert main([str(tmp_path)]) == 1
        out = capsys.readouterr().out
        assert "UPLOADED" in out and "must be removed by hand" in out

    def test_a_pending_ghost_names_the_self_healing_path(self, tmp_path, capsys):
        (tmp_path / "x-act.prg").write_text(_prg(files_pending=[REAL_GHOSTS[3]]))
        assert main([str(tmp_path)]) == 1
        assert "prune_missing_pending" in capsys.readouterr().out

    @pytest.mark.skipif(os.geteuid() == 0, reason="root can read any directory")
    def test_incomplete_coverage_exits_one_even_with_no_ghosts(self, tmp_path, capsys):
        """A partial sweep must never read as a clean one."""
        blocked = tmp_path / "blocked"
        blocked.mkdir()
        blocked.chmod(0o000)
        try:
            assert main([str(tmp_path)]) == 1
            assert "Coverage is INCOMPLETE" in capsys.readouterr().out
        finally:
            blocked.chmod(stat.S_IRWXU)

    def test_run_tree_roots_are_selected_when_present(self, tmp_path, capsys):
        synced = tmp_path / "RUNS_SYNCED"
        synced.mkdir()
        (synced / "x-act.prg").write_text(_prg(files_s3={"d.hlo": "raw_data/u/d"}))
        # Not a run tree, and so not scanned.
        other = tmp_path / "ANALYSES"
        other.mkdir()
        (other / "y-act.prg").write_text(
            _prg(files_s3={REAL_GHOSTS[0]: "raw_data/a/x.tmp"})
        )
        assert main([str(tmp_path)]) == 0
        assert "RUNS_SYNCED" in capsys.readouterr().out
