"""Unit tests for helao/ui/shared/retire.py line scans, locate, in_flight."""

import json
import os
from datetime import datetime, timedelta, timezone

from helao.core.tests.retire_fakes import make_run_tree
from helao.ui.shared import retire

U = "11111111-2222-3333-4444-555555555555"
REL = "26.40/1005/20261005.100000__SEQ"


def test_prefix_uuid_does_not_match(tmp_path):
    """Mutation: startswith/in instead of strip-equality in names_uuid/top_level."""
    root = str(tmp_path)
    make_run_tree(root, "RUNS_FINISHED", REL, sequence_uuid=U)
    make_run_tree(
        root, "RUNS_FINISHED", "26.40/1005/20261005.110000__SEQ", sequence_uuid=U + "0"
    )
    locs = retire.locate(root, U)
    assert [l.rel_dir for l in locs] == [REL]


def test_indented_sequence_uuid_creates_no_location(tmp_path):
    """Mutation: line.lstrip() before matching."""
    root = str(tmp_path)
    d = tmp_path / "RUNS" / "26.40" / "1005" / "s"
    d.mkdir(parents=True)
    (d / "a-seq.yml").write_text(f"sequence_name: x\n  sequence_uuid: {U}\n")
    assert retire.locate(root, U) == []


def test_runs_superseded_is_skipped(tmp_path):
    """Mutation: removing the RUNS_SUPERSEDED exclusion."""
    root = str(tmp_path)
    make_run_tree(
        root, "RUNS_SUPERSEDED", "20261005_retired/RUNS/26.40/1005/s", sequence_uuid=U
    )
    # also at a depth the RUNS*/*/*/*/*-seq.yml glob reaches, so the exclusion bites
    make_run_tree(root, "RUNS_SUPERSEDED", "a/b/s", sequence_uuid=U)
    make_run_tree(root, "RUNS_FINISHED", REL, sequence_uuid=U)
    locs = retire.locate(root, U)
    assert len(locs) == 1 and locs[0].run_tree == "RUNS_FINISHED"


def test_locate_reads_label_name_campaign(tmp_path):
    """Mutation: reading the indented line, or the first occurrence anywhere."""
    root = str(tmp_path)
    make_run_tree(
        root, "RUNS", REL, sequence_uuid=U, label="L1", name="N1", campaign="C1"
    )
    make_run_tree(root, "RUNS_SYNCED", REL, sequence_uuid=U, label="L2", name="N2")
    yml = os.path.join(root, "RUNS", REL, "20261001.000000-seq.yml")
    with open(yml) as f:
        text = f.read()
    with open(yml, "w") as f:  # a later top-level duplicate must not win
        f.write(text.replace("sequence_name:", "sequence_label: later\nsequence_name:"))
    a, b = retire.locate(root, U)
    assert (a.run_tree, a.label, a.name, a.campaign) == ("RUNS", "L1", "N1", "C1")
    assert (b.run_tree, b.label, b.name, b.campaign) == ("RUNS_SYNCED", "L2", "N2", "")
    assert a.rel_dir == REL and a.seq_yml.endswith("-seq.yml")


def _state(d, name, body):
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(body if isinstance(body, str) else json.dumps(body))
    return str(p)


def test_in_flight_matches_uuid_or_output_dir(tmp_path):
    """Mutation: dropping the sequence_output_dir comparison, or dropping the
    backslash normalisation."""
    src = tmp_path / "sources"
    proc = src / "host1" / "processing"
    claimed = {"sequence_uuid": None, "sequence_output_dir": None}
    _state(proc, "c.state.json", claimed)
    _state(proc, "m.state.json", "{not json")
    assert retire.in_flight(str(src), U, [REL]) is None
    by_uuid = _state(proc, "u.state.json", {"sequence_uuid": U})
    assert retire.in_flight(str(src), U, [REL]) == by_uuid
    os.remove(by_uuid)
    by_dir = _state(
        proc,
        "d.state.json",
        {
            "sequence_uuid": "other",
            "sequence_output_dir": "\\" + REL.replace("/", "\\"),
        },
    )
    assert retire.in_flight(str(src), U, [REL]) == by_dir


def test_ledger_path_for_is_utc_stamped():
    """Mutation: dropping astimezone(utc)."""
    now = datetime(2026, 10, 6, 1, 2, 3, tzinfo=timezone(timedelta(hours=-7)))
    assert (
        retire.ledger_path_for("/r", "u", now)
        == "/r/STATES/retire_u_20261006T080203Z.jsonl"
    )
