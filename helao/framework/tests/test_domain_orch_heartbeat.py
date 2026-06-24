"""Pure orchestrator status-heartbeat helpers."""
from helao.framework.domain import orchestration as orch


def test_pingable_servers_skip_rules():
    cfg = {
        "MOTOR": {"host": "h1", "port": 1},
        "PSTAT": {"host": "h2", "port": 2, "params": {}},
        "DB": {"host": "h", "port": 3},                       # skip DB
        "ANA": {"host": "h", "port": 4},                      # skip ANA
        "VIS": {"host": "h", "port": 5, "bokeh": "x"},        # skip bokeh UI
        "LIVE": {"host": "h", "port": 6, "demovis": "y"},     # skip demovis UI
        "QUIET": {"host": "h", "port": 7, "params": {"ignore_heartbeats": True}},
        # legacy parity: skip on KEY PRESENCE regardless of value (even falsy)
        "QUIET2": {"host": "h", "port": 8, "params": {"ignore_heartbeats": False}},
    }
    out = orch.pingable_servers(cfg)
    assert sorted(out) == [("MOTOR", "h1", 1), ("PSTAT", "h2", 2)]


def test_parse_status_response_idle():
    resp = {"_driver_status": "ok", "endpoints": {"run": {"active_dict": {}}}}
    assert orch.parse_status_response(resp, True) == ("idle", "ok")


def test_parse_status_response_busy():
    resp = {"_driver_status": "ok",
            "endpoints": {"run": {"active_dict": {"a": 1}}, "idleep": {"active_dict": {}}}}
    status, driver = orch.parse_status_response(resp, True)
    assert status == "busy [run]"
    assert driver == "ok"


def test_parse_status_response_missing_driver_status():
    resp = {"endpoints": {}}
    assert orch.parse_status_response(resp, True) == ("idle", "unknown")


def test_parse_status_response_unreachable():
    assert orch.parse_status_response(None, True) == ("unreachable", "unknown")
    assert orch.parse_status_response({"_driver_status": "ok"}, False) == ("unreachable", "unknown")
