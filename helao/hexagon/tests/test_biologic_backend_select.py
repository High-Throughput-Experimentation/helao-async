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
