"""test_runner's ``scenario`` selects which scenario coroutines dispatch."""

import asyncio
from types import SimpleNamespace

import pytest

from helao.deploy.test.runners import test_runner as tr


class StubOrch:
    world_cfg = {"root": "/nonexistent"}
    runs: list = []

    def __init__(self):
        self.names = []

    async def run_action(self, action):
        self.names.append(action.action_name)
        params = dict(action.action_params)
        if action.action_name == "add_global_param":  # server stamps the value
            params[params["param_name"]] = params["param_value"]
        return SimpleNamespace(action_params=params)

    async def dispatch_action(self, action):
        self.names.append(action.action_name)
        return {"action_params": dict(action.action_params)}

    def zip_runs(self, path):
        pass


def _names(**kw):
    orch = StubOrch()
    asyncio.run(tr.run(orch, **kw))
    return set(orch.names)


def test_scenarios():
    assert _names(scenario="noblocking") == {"wait"}
    assert _names(scenario="conditional") == {"add_global_param", "conditional_stop"}
    assert _names(scenario="both") == {"wait", "add_global_param", "conditional_stop"}


def test_unknown_scenario_dispatches_nothing():
    orch = StubOrch()
    with pytest.raises(ValueError):
        asyncio.run(tr.run(orch, scenario="bogus"))
    assert orch.names == []


def test_string_samples_rejected():
    with pytest.raises(ValueError):
        asyncio.run(tr.run(StubOrch(), samples="1,2"))
