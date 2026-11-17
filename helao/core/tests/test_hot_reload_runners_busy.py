"""Hot-reload must not restart a Reflex server that is running runners (spec D4)."""

import launch


class Resp:
    def __init__(self, status=200, body=None):
        self.status_code, self._body = status, body or {}
        self.ok = status < 400

    def json(self):
        return self._body


ENTRY = {"host": "h", "port": 8100, "reflex": "reflex_app"}


def test_reflex_server_idle_only_when_no_runner_busy(monkeypatch):
    urls = []

    def get(url, timeout):
        urls.append(url)
        return Resp(200, {"busy": busy[0]})

    busy = [True]
    monkeypatch.setattr(launch.requests, "get", get)
    assert launch.server_is_idle("visualizer", ENTRY) is False
    busy[0] = False
    assert launch.server_is_idle("visualizer", ENTRY) is True
    assert urls == ["http://h:8101/runners_busy"] * 2  # backend is port + 1


def _raising(exc):
    def f(url, timeout):
        raise exc

    return f


def test_reflex_timeout_is_not_idle(monkeypatch):
    monkeypatch.setattr(
        launch.requests, "get", _raising(launch.requests.exceptions.ReadTimeout())
    )
    assert launch.server_is_idle("visualizer", ENTRY) is False


def test_reflex_refused_connection_is_idle(monkeypatch):
    monkeypatch.setattr(
        launch.requests, "get", _raising(launch.requests.exceptions.ConnectionError())
    )
    assert launch.server_is_idle("visualizer", ENTRY) is True


def test_reflex_non_2xx_is_idle(monkeypatch):
    for status in (404, 500):
        monkeypatch.setattr(
            launch.requests, "get", lambda url, timeout, s=status: Resp(s)
        )
        assert launch.server_is_idle("visualizer", ENTRY) is True


def test_bokeh_visualizer_is_still_always_idle():
    assert launch.server_is_idle("visualizer", {"host": "h", "port": 1}) is True


def test_reflex_unreadable_reply_is_not_idle(monkeypatch):
    class Bad(Resp):
        def json(self):
            raise ValueError("not json")

    monkeypatch.setattr(launch.requests, "get", lambda url, timeout: Bad(200))
    assert launch.server_is_idle("visualizer", ENTRY) is False
