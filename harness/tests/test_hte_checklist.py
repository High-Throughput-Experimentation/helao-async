import json
from pathlib import Path

import pytest

from harness.endpoints import diff_route_sets, extract_routes
from harness.hte_freeze import HTE_ACTION, OUT, SERVERS


@pytest.mark.parametrize("module,key", SERVERS)
def test_frozen_matches_regenerated(module, key):
    frozen_path = OUT / (Path(module).stem + ".json")
    frozen = json.loads(frozen_path.read_text())
    current = extract_routes(HTE_ACTION / module, server_key=key)
    assert diff_route_sets(frozen, current) == []
