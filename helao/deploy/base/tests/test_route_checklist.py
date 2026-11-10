"""base's frozen action-server route set: sync_server, split verbatim from hte's.

These checklist files were MOVED from hte's tests/checklists, never
regenerated. Do not run ``python -m harness.freeze`` to rewrite them; see the
docstring of hte's test_route_checklist.py for why a regenerated record proves
nothing. The checks are ``harness.route_gate``'s, shared with hte's gate, so
base inherits its anti-vacuity guards instead of carrying a weaker copy.
"""

import json
import shutil
from pathlib import Path

from harness import freeze, route_gate
from helao.hexagon import preflight

OUT = Path(__file__).resolve().parent / "checklists"
SERVERS = route_gate.load_servers(OUT)


def test_the_manifest_is_sync_server_only():
    assert SERVERS == [("sync_server.py", "DB")]


def test_the_checklist_directory_is_actually_populated():
    assert not route_gate.missing_module_checklists(SERVERS, OUT)


def test_the_population_guard_notices_a_deleted_checklist(tmp_path: Path):
    for src in OUT.glob("*.json"):
        shutil.copy(src, tmp_path / src.name)
    assert route_gate.missing_module_checklists(SERVERS, tmp_path) == []
    (tmp_path / "sync_server.json").unlink()
    assert route_gate.missing_module_checklists(SERVERS, tmp_path) == ["sync_server.py"]


def test_sync_server_matches_its_frozen_checklist():
    diffs = route_gate.module_diffs("base", OUT, "sync_server.py", "DB")
    assert diffs == [], json.dumps(diffs, indent=2)


def test_additions_are_well_formed_and_not_stale():
    assert route_gate.malformed_additions(OUT, SERVERS) == []
    assert route_gate.unresolved_additions("base", OUT, SERVERS) == []


def test_the_frozen_record_is_eight_private_routes():
    assert route_gate.frozen_totals(OUT, SERVERS) == (0, 8)


def test_frozen_at_b7c_list_is_present_and_complete():
    cdir = preflight._checklist_dir("base")
    assert cdir is not None and cdir == OUT
    assert preflight._frozen_checklists(cdir) == {"sync_server"}


def test_base_freeze_is_clean_and_skips_nothing():
    lines, blockers = freeze.freeze_deployment("base", dry_run=True)
    assert blockers == []
    assert not [ln for ln in lines if "skipped" in ln], lines
    assert all("would write" not in ln for ln in lines), lines
