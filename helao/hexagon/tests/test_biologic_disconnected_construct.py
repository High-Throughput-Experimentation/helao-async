"""BiologicDriver disconnected-construct guard, EClib1-direct era.

The former easy-biologic-backed driver is gone: `biologic/driver.py` now
calls the EC-Lab Development Package (EClib1) DLL directly through
`eclib_client.EclibClient`, and `biologic/technique.py` holds eleven native
`BiologicTechnique` builds (no vendor program classes at all, lazy or
otherwise). `easy_biologic` no longer belongs anywhere in this package.

These tests pin the construct-tier invariant that has been true since P3a-2
and remains true after the EClib1 rewrite: importing the driver and building
one touches no DLL and claims no hardware, so the module and the class
construct on Linux with no vendor SDK installed. Real instrument behavior
remains an at-station gate (Task 17); construct-tier only.
"""

import ast
import sys
from pathlib import Path

from helao.deploy.hte.drivers.pstat.biologic import technique as biologic_technique
from helao.deploy.hte.drivers.pstat.biologic.driver import BiologicDriver

PACKAGE_DIR = Path("helao/deploy/hte/drivers/pstat/biologic")


def test_import_loads_no_dll():
    # ctypes.WinDLL does not exist on Linux, so if the DLL loader ran at
    # import time this module's own import above would already have failed
    # with AttributeError rather than getting here.
    assert "easy_biologic" not in sys.modules


def test_construct_reads_no_sdk_path_and_claims_no_channel():
    # A nonexistent sdk_path must not matter at construct time -- nothing
    # under it is opened until connect() runs.
    d = BiologicDriver(config={"sdk_path": "/no/such/path", "num_channels": 3})
    assert d.ready is False
    assert d.channel is None  # no channel claimed
    assert d._client is None  # no EclibClient -> no DLL bound
    assert d.num_channels == 3


def test_technique_registry_imports_without_an_sdk_and_holds_eleven_entries():
    assert len(biologic_technique.BIOTECHS) == 11
    for key in (
        "OCV",
        "CA",
        "CP",
        "CV",
        "PEIS",
        "GEIS",
        "CAOCV",
        "CALIMIT",
        "CPLIMIT",
        "SPEIS",
        "SGEIS",
    ):
        assert key in biologic_technique.BIOTECHS


def test_the_server_module_imports_on_linux_with_eclib_in_backends():
    from helao.deploy.hte.servers.action import biologic_server

    assert "eclib" in biologic_server.BACKENDS
    assert biologic_server.BACKENDS["eclib"] is BiologicDriver


def _imports_easy_biologic(path: Path) -> bool:
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(a.name.split(".")[0] == "easy_biologic" for a in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] == "easy_biologic":
                return True
    return False


def test_no_module_in_the_package_references_easy_biologic():
    # Parses imports rather than grepping source, so a docstring mentioning
    # "easy-biologic" (there are several, explaining what this driver
    # replaced) does not fail the check.
    offenders = [str(p) for p in PACKAGE_DIR.glob("*.py") if _imports_easy_biologic(p)]
    assert offenders == []


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
    source = Path("helao/deploy/hte/servers/action/biologic_server.py").read_text()
    assert "EC_IRange_map[" not in source
    assert "EC_ERange_map[" not in source
    assert "EC_Bandwidth_map[" not in source
