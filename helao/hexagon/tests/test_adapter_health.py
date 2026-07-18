"""HealthPort adapter: port-shape conversion of the legacy HEAD-probe
helper, late-bound orch for ping/status_summary, fail-loud unbound access,
and the ORCH_REQUIRED/wiring growth (P2a Task 1)."""

import pytest

from helao.hexagon.adapters.legacy.health import LegacyHealthAdapter
from helao.hexagon.app.wiring import ORCH_REQUIRED, PortWiring, UnwiredPortError
from helao.hexagon.ports.auxiliary import HealthPort


def test_adapter_satisfies_health_port_protocol():
    assert isinstance(LegacyHealthAdapter(), HealthPort)


def test_orch_required_includes_health_and_wiring_has_slot():
    assert "health" in ORCH_REQUIRED
    w = PortWiring()
    assert w.health is None
    with pytest.raises(UnwiredPortError, match="health"):
        w.require("health")


def test_unbound_ping_and_summary_fail_loud():
    ad = LegacyHealthAdapter()
    with pytest.raises(RuntimeError, match="not bound"):
        ad.status_summary()


@pytest.mark.asyncio
async def test_endpoints_available_converts_to_port_shape(monkeypatch):
    async def fake_probe(req_list):
        # legacy helper shape: (all_available, [(url, [state]), ...])
        return False, [("http://h:1/S/bad", ["could not connect"])]

    monkeypatch.setattr(
        "helao.hexagon.adapters.legacy.health.legacy_endpoints_available",
        fake_probe,
    )
    ad = LegacyHealthAdapter()
    out = await ad.endpoints_available(["http://h:1/S/ok", "http://h:1/S/bad"])
    assert out == [("http://h:1/S/ok", True), ("http://h:1/S/bad", False)]


def test_status_summary_extracts_driver_status_from_bound_orch():
    class _O:
        status_summary = {"SIM": ("idle", "ok"), "MOTOR": ("idle", "unknown")}

    ad = LegacyHealthAdapter()
    ad.bind_orch(_O())
    assert ad.status_summary() == {"SIM": "ok", "MOTOR": "unknown"}
