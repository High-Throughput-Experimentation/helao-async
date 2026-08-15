"""OrchHost construction and route surface (B3a)."""

import tempfile


def _host():
    from helao.helpers import config_loader
    from helao.hexagon.app.orch_host import OrchHost

    config_loader.CONFIG = {
        "root": tempfile.mkdtemp(prefix="helao_orchhost_"),
        "dummy": True,
        "simulation": True,
        "run_type": "simulation",
        "servers": {
            "ORCH": {
                "host": "127.0.0.1",
                "port": 8001,
                "group": "orchestrator",
                "params": {},
            },
            "SIM": {
                "host": "127.0.0.1",
                "port": 8002,
                "group": "action",
                "params": {},
            },
        },
    }
    return OrchHost("ORCH", "ORCH", "test orchestrator", version=3.0)


def test_the_host_is_its_own_orch_and_its_own_base():
    """Legacy spells the back-reference both ways and both have call sites:
    orch_api reaches self.orch at 60 sites, and Orch extends Base."""
    host = _host()
    assert host.orch is host
    assert host.base is host


def test_construction_populates_the_three_queues_and_the_status_model():
    host = _host()
    assert list(host.sequence_dq) == []
    assert list(host.experiment_dq) == []
    assert list(host.action_dq) == []
    assert host.globalstatusmodel is not None
    assert host.active_experiment is None
    assert host.active_sequence is None
