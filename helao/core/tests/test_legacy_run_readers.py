"""Both layouts resolve; the new one without searching (spec §7).

Legacy is not one shape. Verified against two production archives on
2026-09-25: the week level is ``%y.%U`` throughout, but the day level is
``YYYYMMDD`` in the early era and ``MMDD`` later, and the era boundary is
per-station (``24.42``/``25.39`` on one archive, ``25.27``/``26.03`` on
another). Both shapes sit side by side in the same ``RUNS_SYNCED`` today, so a
reader built to one silently returns ``None`` for the other -- which is a miss,
not an error, and therefore invisible until years of archive are unreachable.
"""

import zipfile
from pathlib import Path

import pytest

from helao.core.drivers.data.process_locator import _mirror_dir
from helao.helpers.file_mapper import FileMapper
from helao.ui.shared.data_browser import sources


def _record(day: Path) -> Path:
    d = day / "seqdir" / "expdir" / "0__0__SIM__do_thing"
    d.mkdir(parents=True)
    (d / "data-0.0.0.0__0.hlo").write_text("x", encoding="utf-8")
    (d / "260828.120000000000-act.yml").write_text(
        "action_name: do_thing\n", encoding="utf-8"
    )
    return d


def _legacy_tree(tmp_path: Path, day: str = "0828") -> Path:
    return _record(tmp_path / "RUNS_SYNCED" / "26.35" / day)


def _new_tree(tmp_path: Path) -> Path:
    return _record(tmp_path / "RUNS" / "2026" / "0925")


def test_new_layout_is_not_flagged_legacy(tmp_path: Path):
    assert FileMapper(str(_new_tree(tmp_path))).is_legacy is False


def test_legacy_layout_is_flagged_legacy(tmp_path: Path):
    assert FileMapper(str(_legacy_tree(tmp_path))).is_legacy is True


def test_new_layout_resolves_without_trying_other_roots(tmp_path: Path):
    d = _new_tree(tmp_path)
    fm = FileMapper(str(d))
    assert Path(
        fm.locate("2026/0925/seqdir/expdir/0__0__SIM__do_thing/data-0.0.0.0__0.hlo")
    ).is_file()
    assert fm.roots == ["RUNS", "PROCESSES"]  # no RUNS_* search


def test_legacy_layout_still_resolves(tmp_path: Path):
    d = _legacy_tree(tmp_path)
    fm = FileMapper(str(d))
    rel = "26.35/0828/seqdir/expdir/0__0__SIM__do_thing/data-0.0.0.0__0.hlo"
    assert Path(fm.locate(rel)).is_file()


def test_legacy_eight_char_day_dir_still_resolves(tmp_path: Path):
    """The pre-25.39 era wrote ``YY.WW/YYYYMMDD`` (A18.1)."""
    d = _legacy_tree(tmp_path, day="20241022")
    fm = FileMapper(str(d))
    assert fm.is_legacy is True
    rel = "26.35/20241022/seqdir/expdir/0__0__SIM__do_thing/data-0.0.0.0__0.hlo"
    assert Path(fm.locate(rel)).is_file()


def test_legacy_sequence_zip_still_resolves(tmp_path: Path):
    """Pre-cut-over archives keep their zips; nothing rewrites them."""
    d = _legacy_tree(tmp_path)
    seq_dir = d.parent.parent
    rel = "expdir/0__0__SIM__do_thing/data-0.0.0.0__0.hlo"
    with zipfile.ZipFile(seq_dir.with_suffix(".zip"), "w") as zf:
        zf.writestr(rel, "x")
    for p in sorted(seq_dir.rglob("*"), reverse=True):
        p.unlink() if p.is_file() else p.rmdir()
    seq_dir.rmdir()

    fm = FileMapper(str(d))
    assert fm.locate(f"26.35/0828/seqdir/{rel}") is not None


def test_two_run_roots_anchor_on_the_inner_one(tmp_path: Path):
    """Superseded records are archived as whole nested legacy trees (A9).

    ``RUNS_SUPERSEDED/<ts>/RUNS_FINISHED/...`` -- anchoring on the *first*
    run-root segment makes every file under it unresolvable.
    """
    d = _record(
        tmp_path
        / "RUNS_SUPERSEDED"
        / "260818.091656"
        / "RUNS_FINISHED"
        / "26.25"
        / "0624"
    )
    fm = FileMapper(str(d))
    assert fm.is_legacy is True
    assert fm.prestr.endswith("260818.091656")
    rel = "26.25/0624/seqdir/expdir/0__0__SIM__do_thing/data-0.0.0.0__0.hlo"
    assert Path(fm.locate(rel)).is_file()


def test_processes_superseded_does_not_crash(tmp_path: Path):
    """``PROCESSES_SUPERSEDED`` is a real directory and matched nothing (A9)."""
    d = tmp_path / "PROCESSES_SUPERSEDED" / "26.25" / "0624" / "seqdir" / "expdir"
    d.mkdir(parents=True)
    (d / "a__b__c-prc.yml").write_text("process_name: x\n", encoding="utf-8")
    fm = FileMapper(str(d))  # used to raise IndexError
    assert fm.relstrs


def test_mirror_dir_uses_the_inner_run_root(tmp_path: Path):
    """The PROCESSES mirror rejoins at the *last* run root, not the first."""
    exp = (
        tmp_path
        / "RUNS_SUPERSEDED"
        / "260818.091656"
        / "RUNS_FINISHED"
        / "26.25"
        / "0624"
        / "seqdir"
        / "expdir"
    )
    mirror = _mirror_dir(exp, tmp_path / "PROCESSES")
    assert mirror == tmp_path / "PROCESSES" / "26.25" / "0624" / "seqdir" / "expdir"


def test_mirror_dir_is_none_for_the_new_layout(tmp_path: Path):
    """New records colocate their prc; there is no mirror to find."""
    assert (
        _mirror_dir(tmp_path / "RUNS" / "2026" / "0925" / "s" / "e", tmp_path) is None
    )


@pytest.mark.parametrize("source", ["RUNS", "DIAG"])
def test_browser_indexes_the_new_trees(tmp_path: Path, source: str):
    _record(tmp_path / source / "2026" / "0925")
    df = sources.get_index(str(tmp_path), source)
    assert len(df) == 1, df
    assert df.iloc[0]["source"] == source
    assert df.iloc[0]["date"] == "2026/0925"
    assert df.iloc[0]["available"] is True


def test_browser_still_indexes_eight_char_legacy_days(tmp_path: Path):
    _record(tmp_path / "RUNS_FINISHED" / "24.42" / "20241022")
    df = sources.get_index(str(tmp_path), "RUNS_FINISHED")
    assert list(df["date"]) == ["24.42/20241022"], df


def _sequence(day: Path, name: str, ts: str = "20260925.094102000000") -> Path:
    """One full seq/exp/act record with all three ymls under ``day``."""
    seq_dir = day / f"{ts.split('.')[1][:6]}__{name}__lab"
    exp_dir = seq_dir / f"{ts}__exp--{name}"
    act_dir = exp_dir / "0__0__SIM__do_thing"
    act_dir.mkdir(parents=True)
    (act_dir / "data-0.0.0.0__0.hlo").write_text("x", encoding="utf-8")
    (act_dir / f"{ts}-act.yml").write_text(f"action_name: {name}\n", encoding="utf-8")
    (exp_dir / f"{ts}-exp.yml").write_text(
        f"experiment_name: {name}\n", encoding="utf-8"
    )
    (seq_dir / f"{ts}-seq.yml").write_text(f"sequence_name: {name}\n", encoding="utf-8")
    return act_dir


def test_new_layout_loader_does_not_index_sibling_sequences(tmp_path: Path):
    """The legacy state fan-out collapses to the target's PARENT under RUNS.

    Every ``RUNS_*`` -> state substitution is a no-op there, and the
    ``PROCESSES`` one then points at the day directory -- so a loader that
    keeps the fan-out indexes every sibling sequence of that day as if it
    belonged to the one asked for.
    """
    from helao.core.drivers.data.loaders.localfs import LocalLoader

    day = tmp_path / "RUNS" / "2026" / "0925"
    _sequence(day, "seqA")
    _sequence(day, "seqB", ts="20260925.101500000000")

    loader = LocalLoader(str(day / "094102__seqA__lab"))
    assert list(loader.sequences["sequence_name"]) == ["seqA"], loader.sequences


def test_helao_data_reads_the_new_layout(tmp_path: Path):
    """The ``RUNS_[A-Z]+`` regex has no match under RUNS; running it raises."""
    from helao.helpers.helao_data import HelaoData

    day = tmp_path / "RUNS" / "2026" / "0925"
    _sequence(day, "seqA")
    hd = HelaoData(str(day / "094102__seqA__lab"))  # used to IndexError on the regex
    assert hd.type == "seq"
    assert [Path(p).name for p in hd.data_files] == ["data-0.0.0.0__0.hlo"]


@pytest.mark.parametrize(
    "root, expected",
    [
        (("RUNS", "2026", "1001"), ("2026", "1001")),
        (("DIAG", "2026", "1001"), ("2026", "1001")),
        (("RUNS_FINISHED", "26.40", "1001"), ("26.40", "1001")),
        (("PROCESSES", "26.40", "1001"), ("26.40", "1001")),
        (
            ("RUNS_SUPERSEDED", "260818.091656", "RUNS_FINISHED", "26.25", "0624"),
            ("26.25", "0624"),
        ),
    ],
)
def test_helao_data_runs_relpath_strips_every_run_root(tmp_path: Path, root, expected):
    """A post-processor reading a RUNS or DIAG record raised StopIteration here.

    ``read_hlo`` passes every on-disk path through ``_runs_relpath``; matching
    only ``RUNS_*``/``PROCESSES`` made each read of the new layout fail, and
    the hook saw an action with no data.
    """
    from helao.helpers.helao_data import HelaoData

    tail = ("seqdir", "expdir", "0__0__ANDOR__acquire", "ANDORSPEC-0.0.0.0__0.hlo")
    p = Path(tmp_path, *root, *tail)
    assert HelaoData._runs_relpath(str(p)) == str(Path(*expected, *tail))


def test_helao_data_widens_the_inner_run_root_only(tmp_path: Path):
    """Widening the OUTER root of a nested archive reaches a second archive.

    ``RUNS_SUPERSEDED`` and ``RUNS_REBUILD`` both hold whole nested legacy
    trees, so replacing the outer segment with ``RUNS_*`` globs the same
    record out of every archive at once and attaches the wrong children.
    """
    from helao.helpers.helao_data import HelaoData

    rel = Path("260818.091656") / "RUNS_FINISHED" / "26.25" / "0624"
    _sequence(tmp_path / "RUNS_SUPERSEDED" / rel, "seqA")
    _sequence(tmp_path / "RUNS_REBUILD" / rel, "seqA")  # same record, other archive

    seq_dir = tmp_path / "RUNS_SUPERSEDED" / rel / "094102__seqA__lab"
    hd = HelaoData(str(seq_dir))
    assert len(hd.exp) == 1, [x.ymldir for x in hd.exp]


def test_derived_processes_index_the_new_tree(tmp_path: Path):
    """A colocated prc under RUNS resolves its data file in the same tree."""
    act = _sequence(tmp_path / "RUNS" / "2026" / "0925", "seqA")
    (act.parent / "0__abc__20260925-prc.yml").write_text(
        "technique_name: CV\nfiles:\n- file_name: data-0.0.0.0__0.hlo\n",
        encoding="utf-8",
    )
    idx = sources.DerivedSourceIndex(str(tmp_path), "PROCESSES")
    assert idx.list_dates() == ["2026/0925"]
    df = idx.index()
    assert len(df) == 1, df
    assert df.iloc[0]["available"] is True, df.iloc[0]["locator"]
    assert Path(df.iloc[0]["locator"]).is_file()


def test_a_process_file_resolves_against_a_sequence_directory(tmp_path: Path):
    """``get_bytes("", fn)`` names a file by its run-relative path.

    A process lists its files as ``<action_output_dir>/<file_name>``. For a
    sequence zip, the zip branch strips everything up to the sequence dir. The
    syncer now hands analyses a directory instead (spec D9), and that branch
    fell through to ``FileMapper("")`` -- an IndexError on uvis4 for every
    reference spectrum parquet.
    """
    from helao.core.drivers.data.loaders.localfs import LocalLoader

    day = tmp_path / "RUNS" / "2026" / "0925"
    act_dir = _sequence(day, "seqA")
    (act_dir / "spec.parquet").write_bytes(b"PAR1")
    seq_dir = act_dir.parent.parent
    fn = act_dir.relative_to(tmp_path / "RUNS").as_posix() + "/spec.parquet"

    assert LocalLoader(str(seq_dir)).get_bytes("", fn).read() == b"PAR1"
