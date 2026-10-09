"""The operator's re-run list must find sequences in both run layouts.

An empty list looks exactly like a quiet station, so a lister that stops
matching the on-disk layout fails silently. These tests pin both shapes:
unzipped sequence directories under ``RUNS/%Y/%m%d/`` and legacy sequence
zips under ``RUNS_SYNCED/%y.%U/``.
"""

import os
from datetime import datetime, timedelta

from helao.deploy.hte.specifications import week_window
from helao.deploy.hte.specifications.week_window import WeekWindowSpecParser


def _seqdir(root, when, name):
    path = os.path.join(root, when.strftime("%Y"), when.strftime("%m%d"), name)
    os.makedirs(path)
    open(
        os.path.join(path, f"{name.split('__')[1]}-seq.yml"), "w", encoding="utf-8"
    ).close()
    return path


def test_lists_runs_tree_sequence_dirs_newest_first(tmp_path):
    now = datetime.now()
    older = _seqdir(tmp_path, now - timedelta(days=1), "090000__SEQ_A__lbl")
    newer = _seqdir(tmp_path, now, "100000__SEQ_B__lbl")
    _seqdir(tmp_path, now - timedelta(weeks=3), "100000__SEQ_OLD__lbl")
    _seqdir(tmp_path, now, "110000__SEQ_M__lbl__manual_orch_seq__")
    # a day directory entry without a -seq.yml is not a sequence
    os.makedirs(os.path.join(tmp_path, now.strftime("%Y"), now.strftime("%m%d"), "x"))

    assert WeekWindowSpecParser().lister(str(tmp_path)) == [newer, older]


def test_lists_legacy_zips_under_sunday_start_week(tmp_path, monkeypatch):
    # On a Sunday %U (Sunday-start, what get_sequence_dir wrote) and %W
    # (Monday-start) name different weeks, so this pins the %U fix.
    now = datetime(2026, 10, 4, 12)
    assert now.strftime("%y.%U") != now.strftime("%y.%W")

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr(week_window, "datetime", _Frozen)
    week = os.path.join(tmp_path, now.strftime("%y.%U"), now.strftime("%Y%m%d"))
    os.makedirs(week)
    zpath = os.path.join(week, "seq.zip")
    open(zpath, "w", encoding="utf-8").close()

    assert WeekWindowSpecParser().lister(str(tmp_path)) == [zpath]
