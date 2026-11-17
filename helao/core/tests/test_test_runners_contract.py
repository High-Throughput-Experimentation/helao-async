"""The test deployment's runners follow the runner contract."""

import pytest

from helao.core.runners.launch import describe

EXPECTED = {
    "helao.deploy.test.runners.simulatews_runner": {
        "wait_time": 3.0,
        "data_duration": 5.0,
    },
    "helao.deploy.test.runners.oersim_runner": {
        "plate_id": 2750,
        "init_random_points": 5,
        "iterations": 8,
    },
    "helao.deploy.test.runners.test_runner": {
        "wait_time": 0.2,
        "cycles": 2,
        "samples": (1, 2),
        "scenario": "both",
    },
}


@pytest.mark.parametrize("module", sorted(EXPECTED))
def test_runner_contract(module):
    d = describe(module)
    got = dict(zip(d["args"], d["defaults"]))
    for name, default in EXPECTED[module].items():
        assert got[name] == default
    assert d["requires"], "REQUIRES declared"
    for server, actions in d["inferred"].items():
        assert set(actions) <= set(d["requires"].get(server, [])), (server, actions)
