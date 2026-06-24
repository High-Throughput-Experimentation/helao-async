"""Unit tests for the HelaoOperator programmatic orch client adapter."""
from helao.framework.adapters import helao_operator as ho
from helao.framework.models.errors import ErrorCodes


def _make_client():
    """Build a HelaoOperator without running __init__ (which needs a config)."""
    op = ho.HelaoOperator.__new__(ho.HelaoOperator)
    op.orch_key = "ORCH"
    op.orch_host = "127.0.0.1"
    op.orch_port = 8001
    return op


def test_request_dispatches_and_returns(monkeypatch):
    calls = []

    def fake_pd(server_key, host, port, endpoint, path_params, json_params):
        calls.append((server_key, endpoint, path_params, json_params))
        return {"ok": True, "endpoint": endpoint}, ErrorCodes.none

    monkeypatch.setattr(ho, "private_dispatcher", fake_pd)
    op = _make_client()
    resp = op.request("get_orch_state")
    assert resp == {"ok": True, "endpoint": "get_orch_state"}
    assert calls[0][1] == "get_orch_state"


def test_request_unreachable_returns_marker(monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("down")

    monkeypatch.setattr(ho, "private_dispatcher", boom)
    op = _make_client()
    resp = op.request("get_orch_state")
    assert resp["orch_state"] == "unreachable"
    assert resp["loop_state"] == "unreachable"


def test_add_experiment_append_payload(monkeypatch):
    captured = {}

    def fake_pd(server_key, host, port, endpoint, path_params, json_params):
        captured["endpoint"] = endpoint
        captured["json"] = json_params
        return {}, ErrorCodes.none

    monkeypatch.setattr(ho, "private_dispatcher", fake_pd)

    class _Exp:
        def as_dict(self):
            return {"experiment_name": "exp0"}

    op = _make_client()
    op.add_experiment(_Exp())  # index=-1 default → append
    assert captured["endpoint"] == "append_experiment"
    assert captured["json"] == {"experiment": {"experiment_name": "exp0"}}
