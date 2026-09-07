"""BiologicDriver disconnected-construct + lazy technique-registry guard (P3a-2).

Before P3a-2, ``biologic/technique.py`` imported ``easy_biologic.base_programs``
at module scope and built ``BIOTECHS`` referencing ``blp.OCV`` etc., and
``BiologicDriver.__init__`` opened the instrument (``connect()``). Since the
easy-biologic SDK is Windows-only (``import easy_biologic.base_programs`` raises
``OSError`` on Linux), the driver could neither import nor construct off-Windows.

The fix (a) stores technique-name strings (``easy_class_name``) resolved lazily
via ``resolve_easy_class`` at ``setup()`` time, and (b) relocates ``connect()``
to ``biologic_server.biologic_dyn_endpoints``. These tests pin that the module
imports and the driver constructs without ever loading the vendor SDK.

Real instrument behavior remains an at-station gate; construct-tier only.
"""

import sys
import types

from helao.deploy.hte.drivers.pstat.biologic import driver as biologic_driver
from helao.deploy.hte.drivers.pstat.biologic import technique as biologic_technique
from helao.deploy.hte.drivers.pstat.biologic.driver import BiologicDriver


def test_import_does_not_load_vendor_sdk():
    # Importing the driver / technique registry must not pull easy_biologic
    # (Windows-only). If it did, this module's own import above would have
    # already failed on Linux — assert explicitly for a clear signal.
    assert "easy_biologic" not in sys.modules
    assert "easy_biologic.base_programs" not in sys.modules


def test_construct_without_hardware_or_sdk():
    d = BiologicDriver(config={"num_channels": 3})
    assert d.ready is False  # not connected at construction
    assert d.pstat is None
    assert d.num_channels == 3
    assert len(d.channels) == 3
    assert "easy_biologic" not in sys.modules  # construct stayed SDK-free


def test_registry_holds_names_not_vendor_classes():
    for key in ("OCV", "CA", "CP", "CV", "PEIS", "GEIS", "CAOCV"):
        tech = biologic_technique.BIOTECHS[key]
        assert isinstance(tech.easy_class_name, str)
    assert biologic_technique.TECH_OCV.easy_class_name == "OCV"


def test_resolve_easy_class_is_lazy(monkeypatch):
    # Inject a fake easy_biologic.base_programs so the resolver works without
    # the real (Windows-only) SDK; proves it looks the class up by name lazily.
    fake_bp = types.ModuleType("easy_biologic.base_programs")

    class _FakeOCV:
        pass

    setattr(fake_bp, "OCV", _FakeOCV)
    fake_pkg = types.ModuleType("easy_biologic")
    monkeypatch.setitem(sys.modules, "easy_biologic", fake_pkg)
    monkeypatch.setitem(sys.modules, "easy_biologic.base_programs", fake_bp)

    resolved = biologic_technique.resolve_easy_class("OCV")
    assert resolved is _FakeOCV
    # driver re-exports the resolver it uses in setup()
    assert biologic_driver.resolve_easy_class("OCV") is _FakeOCV


def test_enum_module_does_not_load_the_vendor_sdk():
    """An EC-Lab-only Windows station must be able to import the server.

    enum.py imported easy_biologic at module scope, and biologic_server.py
    imports enum.py -- so a station running the OLE backend without
    easy-biologic installed could not import its own action server. driver.py
    and technique.py were made hermetic in P3a-2; this one was missed.
    """
    from helao.deploy.hte.drivers.pstat.biologic import enum as biologic_enum

    assert "easy_biologic" not in sys.modules
    assert biologic_enum.EC_IRange.AUTO == "AUTO"


def test_the_enum_resolvers_are_lazy(monkeypatch):
    """The maps resolve against the vendor package only when called."""
    import types

    from helao.deploy.hte.drivers.pstat.biologic import enum as biologic_enum

    fake = types.ModuleType("easy_biologic.lib.ec_lib")

    class _IRange:
        AUTO = "vendor-auto"

    class _ERange:
        AUTO = "vendor-erange"

    class _Bandwidth:
        BW4 = "vendor-bw4"

    fake.IRange = _IRange
    fake.ERange = _ERange
    fake.Bandwidth = _Bandwidth
    monkeypatch.setitem(sys.modules, "easy_biologic", types.ModuleType("easy_biologic"))
    monkeypatch.setitem(
        sys.modules, "easy_biologic.lib", types.ModuleType("easy_biologic.lib")
    )
    monkeypatch.setitem(sys.modules, "easy_biologic.lib.ec_lib", fake)
    # _maps() is lru_cached, so a cache populated by an earlier test would
    # make this pass or fail by test ordering rather than by behaviour.
    biologic_enum._maps.cache_clear()
    monkeypatch.setattr(
        biologic_enum._maps, "cache_clear", biologic_enum._maps.cache_clear
    )

    assert biologic_enum.ec_irange("AUTO") == "vendor-auto"
    assert biologic_enum.ec_erange("AUTO") == "vendor-erange"
    assert biologic_enum.ec_bandwidth("BW4") == "vendor-bw4"
    # Leave no fake-derived entries behind for the next test.
    biologic_enum._maps.cache_clear()


def test_the_ole_package_imports_without_any_vendor_package():
    from helao.deploy.hte.drivers.pstat.biologic_ole.driver import BiologicOleDriver

    driver = BiologicOleDriver(config={"num_channels": 3, "simulate": True})
    assert driver.ready is False
    assert driver.client is None
    assert len(driver.channels) == 3
    assert "comtypes" not in sys.modules
    assert "easy_biologic" not in sys.modules


def test_both_drivers_satisfy_the_backend_protocol():
    """The contract the action server calls, made explicit."""
    from helao.deploy.hte.drivers.pstat.biologic.driver import BiologicDriver
    from helao.deploy.hte.drivers.pstat.biologic_backend import BiologicBackend
    from helao.deploy.hte.drivers.pstat.biologic_ole.driver import BiologicOleDriver

    for cls in (BiologicDriver, BiologicOleDriver):
        for name in (
            "connect",
            "get_status",
            "setup",
            "start_channel",
            "get_data",
            "stop",
            "cleanup",
            "disconnect",
            "reset",
            "shutdown",
        ):
            assert callable(getattr(cls, name)), (cls.__name__, name)
    assert BiologicBackend is not None


def test_the_endpoints_no_longer_coerce_the_range_enums():
    """Coercion belongs in each backend's setup(), not the shared layer."""
    from pathlib import Path

    source = Path("helao/deploy/hte/servers/action/biologic_server.py").read_text()
    assert "EC_IRange_map[" not in source
    assert "EC_ERange_map[" not in source
    assert "EC_Bandwidth_map[" not in source
