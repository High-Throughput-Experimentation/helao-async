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
