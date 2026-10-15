"""``validateConfig`` must return False with a correct message, never KeyError."""

from types import SimpleNamespace

import launch

PIDD = SimpleNamespace(reqKeys=["host", "port", "group"], codeKeys=["fast", "bokeh"])


def _capture(monkeypatch):
    msgs = []
    monkeypatch.setattr(launch, "_mux_log", lambda _lvl, m, **_k: msgs.append(m))
    return msgs


def test_missing_servers_key_returns_false(monkeypatch):
    msgs = _capture(monkeypatch)
    assert launch.validateConfig(PIDD, {}, ".") is False
    assert "'servers' key not defined" in msgs[0]


def test_missing_keys_message_lists_the_missing_keys(monkeypatch):
    msgs = _capture(monkeypatch)
    conf = {"servers": {"s1": {"host": "h", "group": "action"}}}
    assert launch.validateConfig(PIDD, conf, ".") is False
    assert msgs == ["s1 config is missing ['port']."]
