"""restore_smoke finds and reads exp/act records in either storage format."""

import json
from pathlib import Path

import pytest

from helao.hexagon.tests.smoke import restore_smoke as rs

FILES = {
    "RUNS/2026/0929/s/e1/260929.1-exp.json": json.dumps(
        {"experiment_status": ["finished"]}
    ),
    "RUNS/2026/0929/s/e2/260929.2-exp.yml": "experiment_status:\n  - finished\n",
    "RUNS/2026/0929/s/e1/a/260929.3-act.json": json.dumps(
        {"action_name": "A", "action_status": ["skipped", "finished"]}
    ),
    "RUNS/2026/0929/s/e2/a/260929.4-act.yml": "action_name: B\naction_status:\n  - finished\n",
    # must never match: data header, jsonl, and a record outside RUNS
    "RUNS/2026/0929/s/e1/a/data-act.meta.json": "{}",
    "RUNS_SYNCED/2026/0929/s/e1/260929.5-exp.yml": "x: 1\n",
}


@pytest.fixture
def root(tmp_path):
    for rel, text in FILES.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return str(tmp_path)


def test_records_found_in_both_formats(root):
    exps = [Path(p).name for p in rs._exp_records(root)]
    acts = [Path(p).name for p in rs._act_records(root)]
    assert exps == ["260929.1-exp.json", "260929.2-exp.yml"]
    assert acts == ["260929.3-act.json", "260929.4-act.yml"]


def test_records_read_in_both_formats(root):
    docs = [rs.read_meta(p) for p in rs._act_records(root)]
    assert [d["action_name"] for d in docs] == ["A", "B"]
