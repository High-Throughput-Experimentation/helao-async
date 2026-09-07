"""`pstat_backend` picks the driver class, and its default keeps six configs valid.

The default matters more than the key. hispec, odspechw, clad, adss3,
htereflex and htehexreflex all declare a BIOLOGIC server with no
`pstat_backend`, and none of them may need editing for this to land.
"""

import tempfile

import pytest

from helao.deploy.hte.drivers.pstat.biologic.driver import BiologicDriver
from helao.deploy.hte.drivers.pstat.biologic_ole.driver import BiologicOleDriver
from helao.deploy.hte.servers.action import biologic_server
from helao.helpers import config_loader


@pytest.fixture
def with_config(monkeypatch):
    def _set(params):
        monkeypatch.setattr(
            config_loader,
            "CONFIG",
            {
                # A real directory: on the first ActionHost built in a
                # process, HelaoFastAPI initializes the process logger under
                # <root>/LOGS (see test_action_host_surface.py's _host()), so
                # a missing "root" fails in os.path.join before any route is
                # registered -- needed here because test_makeapp_builds_on_
                # both_backends is the first test in this file to call
                # makeApp().
                "root": tempfile.mkdtemp(prefix="helao_biologic_backend_test_"),
                "servers": {
                    "BIOLOGIC": {
                        "group": "action",
                        "host": "127.0.0.1",
                        "port": 8000,
                        "params": params,
                    }
                },
            },
        )

    return _set


def test_an_absent_key_yields_the_eclib_driver(with_config):
    """Six live configs declare no pstat_backend and must keep working."""
    with_config({"address": "192.168.200.100", "num_channels": 1})
    assert biologic_server._driver_class("BIOLOGIC") is BiologicDriver


def test_eclib_is_selectable_explicitly(with_config):
    with_config({"pstat_backend": "eclib"})
    assert biologic_server._driver_class("BIOLOGIC") is BiologicDriver


def test_olecom_selects_the_ole_driver(with_config):
    with_config({"pstat_backend": "olecom"})
    assert biologic_server._driver_class("BIOLOGIC") is BiologicOleDriver


def test_an_unknown_value_is_refused_loudly(with_config):
    """A typo must not hand an EC-Lab station the eclib driver."""
    with_config({"pstat_backend": "olecomm"})
    with pytest.raises(ValueError, match="olecomm"):
        biologic_server._driver_class("BIOLOGIC")


def test_the_refusal_lists_the_valid_values(with_config):
    with_config({"pstat_backend": "ole"})
    with pytest.raises(ValueError, match="eclib"):
        biologic_server._driver_class("BIOLOGIC")


def test_no_config_at_all_still_yields_the_default(monkeypatch):
    """makeApp is called outside the launcher by tests and capture scripts."""
    monkeypatch.setattr(config_loader, "CONFIG", None)
    assert biologic_server._driver_class("BIOLOGIC") is BiologicDriver


def test_a_server_key_absent_from_config_yields_the_default(with_config):
    with_config({"pstat_backend": "olecom"})
    assert biologic_server._driver_class("OTHER") is BiologicDriver


def test_every_backend_has_a_technique_registry():
    assert set(biologic_server.TECHNIQUE_REGISTRIES) == set(biologic_server.BACKENDS)


def test_each_registry_resolves_all_seven_techniques():
    for name, resolve in biologic_server.TECHNIQUE_REGISTRIES.items():
        for tech in ("OCV", "CA", "CP", "CV", "PEIS", "GEIS", "CAOCV"):
            assert resolve(tech) is not None, (name, tech)


def test_the_eclib_registry_returns_eclib_technique_objects():
    from helao.deploy.hte.drivers.pstat.biologic.technique import BiologicTechnique

    resolved = biologic_server.TECHNIQUE_REGISTRIES["eclib"]("CA")
    assert isinstance(resolved, BiologicTechnique)


def test_the_olecom_registry_returns_ole_technique_objects():
    from helao.deploy.hte.drivers.pstat.biologic_ole.technique import OleTechnique

    resolved = biologic_server.TECHNIQUE_REGISTRIES["olecom"]("CA")
    assert isinstance(resolved, OleTechnique)


def test_makeapp_builds_on_both_backends(with_config):
    """The route table must build without an instrument on either backend."""
    for backend in ("eclib", "olecom"):
        with_config(
            {
                "pstat_backend": backend,
                "address": "127.0.0.1",
                "num_channels": 1,
                "simulate": True,
            }
        )
        app = biologic_server.makeApp("BIOLOGIC")
        assert app is not None


def test_run_protocol_registers_only_on_the_ole_backend(with_config, monkeypatch):
    """It is additive; the eclib backend has no .mps and must not grow it.

    ``biologic_dyn_endpoints`` builds no driver itself -- in the real
    launcher, ``ActionHost``'s FastAPI startup event constructs ``app.driver``
    before calling it. Calling it directly (as this test must, to see the
    registered route table) therefore has to build the driver itself, the
    same way that startup event does: ``BACKENDS[backend](config=...)``.

    ``BiologicDriver.connect()`` (eclib) has no simulate branch at all -- it
    unconditionally imports ``easy_biologic``, which raises on Linux -- so a
    real ``connect()`` call never sets ``ready`` and the endpoint's `while not
    app.driver.ready` loop would hang forever. That is orthogonal to what
    this test checks (route registration is backend-gated), so ``connect``
    is stubbed to report ready immediately, exactly as a real EC-Lab station
    would.
    """
    import asyncio

    from helao.core.drivers.helao_driver import (
        DriverResponse,
        DriverResponseType,
        DriverStatus,
    )

    def _fake_connect(self):
        self.ready = True
        return DriverResponse(
            response=DriverResponseType.success, status=DriverStatus.ok
        )

    monkeypatch.setattr(BiologicDriver, "connect", _fake_connect)

    def routes(backend):
        with_config(
            {
                "pstat_backend": backend,
                "address": "127.0.0.1",
                "num_channels": 1,
                "simulate": True,
            }
        )
        app = biologic_server.makeApp("BIOLOGIC")
        app.driver = biologic_server.BACKENDS[backend](config=app.server_params)
        asyncio.run(biologic_server.biologic_dyn_endpoints(app))
        return {route.path for route in app.routes}

    assert "/BIOLOGIC/run_protocol" in routes("olecom")
    assert "/BIOLOGIC/run_protocol" not in routes("eclib")


def test_run_protocol_is_recorded_in_the_additions_allowlist():
    """A new route is a deliberate addition, never a checklist edit."""
    import json
    from pathlib import Path

    additions = json.loads(
        Path("helao/hexagon/tests/checklists/hte/_additions.json").read_text()
    )
    entry = [a for a in additions if a["path"] == "/BIOLOGIC/run_protocol"]
    assert len(entry) == 1
    assert entry[0]["module"] == "biologic_server.py"
    assert entry[0]["why"]


def test_protocol_technique_picks_a_plan_from_the_technique_code():
    from helao.deploy.hte.drivers.pstat.biologic_ole import technique as ot

    assert ot.protocol_technique(54).column_plan.kind == "dc"
    assert ot.protocol_technique(60).column_plan.kind == "eis"


def test_an_unrecognized_technique_code_falls_back_to_the_dc_triple():
    """Guessing a column set for an unknown technique would fabricate data."""
    from helao.deploy.hte.drivers.pstat.biologic_ole import technique as ot

    plan = ot.protocol_technique(999).column_plan
    assert plan.kind == "dc"
    assert set(ot.columns(plan)) == {"t_s", "Ewe_V", "I_A"}


def test_setup_protocol_loads_the_named_file_without_patching(tmp_path):
    from helao.deploy.hte.drivers.pstat.biologic_ole.driver import BiologicOleDriver

    protocol = tmp_path / "my_protocol.mps"
    original = "Technique : 1\nChronoamperometry\n" + "Ei (V)".ljust(20) + "0.000\n"
    protocol.write_text(original, encoding="latin-1")
    driver = BiologicOleDriver(
        config={
            "address": "1.2.3.4",
            "num_channels": 1,
            "simulate": True,
            "protocol_dir": str(tmp_path),
            "scratch_dir": str(tmp_path / "s"),
        }
    )
    driver.connect()
    response = driver.setup_protocol("my_protocol.mps", {"channel": 0})
    assert response.response == "success"
    assert protocol.read_text(encoding="latin-1") == original


def test_setup_protocol_refuses_a_path_outside_the_protocol_dir(tmp_path):
    """A declared library, not whatever the caller passes."""
    from helao.deploy.hte.drivers.pstat.biologic_ole.driver import BiologicOleDriver

    driver = BiologicOleDriver(
        config={
            "address": "1.2.3.4",
            "num_channels": 1,
            "simulate": True,
            "protocol_dir": str(tmp_path),
            "scratch_dir": str(tmp_path / "s"),
        }
    )
    driver.connect()
    response = driver.setup_protocol("../escape.mps", {"channel": 0})
    assert response.response == "failed"
    assert "protocol_dir" in response.message


def test_setup_protocol_refuses_a_missing_file(tmp_path):
    from helao.deploy.hte.drivers.pstat.biologic_ole.driver import BiologicOleDriver

    driver = BiologicOleDriver(
        config={
            "address": "1.2.3.4",
            "num_channels": 1,
            "simulate": True,
            "protocol_dir": str(tmp_path),
            "scratch_dir": str(tmp_path / "s"),
        }
    )
    driver.connect()
    response = driver.setup_protocol("absent.mps", {"channel": 0})
    assert response.response == "failed"
