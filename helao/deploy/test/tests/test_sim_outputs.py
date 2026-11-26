"""The sim servers' produced values land in ``action_output``, not ``action_params``.

``makeApp`` is run with a stub ``ActionHost`` that hands back the decorated
bodies, so each body executes against a real ``Action`` and a session stub
whose ``set_output`` is ``Action.set_output``.
"""

import asyncio
from types import SimpleNamespace

import pytest

from helao.core.models.action import ActionModel as Action
from helao.deploy.test.servers.cpsim import cpsim_server
from helao.deploy.test.servers.gpsim import gpsim_server


class _StubHost:
    def __init__(self, **kw):
        self.funcs = {}
        self.driver = SimpleNamespace()
        self.base = SimpleNamespace(orch_key="o", orch_host="h", orch_port=1)

    def action(self, **kw):
        def deco(f):
            self.funcs[f.__name__] = f
            return f

        return deco

    def post(self, *a, **kw):
        return lambda f: f


class _Active:
    def __init__(self, action):
        self.action = action
        self.set_output = action.set_output

    async def enqueue_data_dflt(self, datadict):
        pass

    async def finish(self):
        return SimpleNamespace(as_dict=lambda: {})


def _run(module, monkeypatch, name, params, driver):
    holder = []

    def host(**kw):
        holder.append(_StubHost(**kw))
        holder[0].driver = driver
        return holder[0]

    monkeypatch.setattr(module, "ActionHost", host)
    app = module.makeApp("sim")
    action = Action(action_params=params)
    ctx = SimpleNamespace(begin=lambda: _async(_Active(action)))
    asyncio.run(app.funcs[name](ctx, **params))
    return action


async def _async(v):
    return v


def test_gpsim_acquire_point_feature_in_output(monkeypatch):
    class Drv:
        async def acquire_point(self, **kw):
            return {"feature": [1, 2]}

    a = _run(gpsim_server, monkeypatch, "acquire_point", {"plate_id": 1}, Drv())
    assert a.action_output["_feature"] == [1, 2]
    assert "_feature" not in a.action_params


def test_cpsim_change_plate_in_output(monkeypatch):
    drv = SimpleNamespace(change_plate=lambda p: None, loaded_plate=7)
    a = _run(cpsim_server, monkeypatch, "change_plate", {"plate_id": 7}, drv)
    assert a.action_output["_loaded_plate_id"] == 7
    assert "_loaded_plate_id" not in a.action_params


def test_cpsim_get_loaded_plate_in_output(monkeypatch):
    drv = SimpleNamespace(loaded_plate=7)
    a = _run(cpsim_server, monkeypatch, "get_loaded_plate", {}, drv)
    assert a.action_output["_loaded_plate_id"] == 7
    assert not any(k.startswith("_") for k in a.action_params)
