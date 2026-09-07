"""Loading the EC-Lib 2.0 Python layer from a path, without having it.

The SDK is not installable (no ``pyproject.toml``), and it must be registered
as top-level ``Python`` because ``Exceptions/EC_SDK_Runtime_Error.py`` imports
``Python.Constants.bl_constants`` absolutely -- every other import in the
package is relative, which is what made this easy to get wrong.

These tests build a synthetic package with the same shape, *including that
absolute import*, so the loader is pinned against the real constraint rather
than against a convenient one. The station's real SDK stays out of the test
dependencies; ``test_biologic_eclib2_vendor_real_sdk.py`` covers it when
present.
"""

import sys
from pathlib import Path

import pytest

from helao.deploy.hte.drivers.pstat.biologic_eclib2 import vendor


@pytest.fixture(autouse=True)
def _unload_between_tests():
    """The vendor package is a process singleton, so each test starts clean."""
    vendor.unload()
    yield
    vendor.unload()


def _write_fake_sdk(root: Path) -> Path:
    """An SDK-shaped tree matching the real package's import style."""
    pkg = root / "Python"
    (pkg / "Constants").mkdir(parents=True)
    (pkg / "Exceptions").mkdir(parents=True)

    (pkg / "Constants" / "bl_constants.py").write_text(
        "from enum import Enum\n"
        "\n"
        "class ErrorCode(Enum):\n"
        "    EC_SDK_ERROR_NOERROR = 0\n"
        "\n"
        "class IRangeValue(Enum):\n"
        "    EC_SDK_IRANGE_1mA = 8\n"
        "    EC_SDK_IRANGE_BOOSTER_3A0 = 14\n"
        "    EC_SDK_IRANGE_BOOSTER_30A = 14\n"
        "\n"
        "class VsInitial(Enum):\n"
        "    EC_SDK_VS_EREF = 0\n"
        "    EC_SDK_VS_IREF = 0\n"
    )
    (pkg / "Constants" / "__init__.py").write_text(
        "from .bl_constants import ErrorCode, IRangeValue, VsInitial\n"
    )
    # The one absolute import in the shipped package.
    (pkg / "Exceptions" / "EC_SDK_Runtime_Error.py").write_text(
        "from Python.Constants.bl_constants import ErrorCode\n"
        "\n"
        "class EC_SDK_Runtime_Error(Exception):\n"
        "    def __init__(self, message, code):\n"
        "        super().__init__(message)\n"
        "        self.code = code\n"
    )
    (pkg / "Exceptions" / "__init__.py").write_text(
        "from .EC_SDK_Runtime_Error import EC_SDK_Runtime_Error\n"
    )
    (pkg / "ECLibAPI.py").write_text(
        "from .Constants import IRangeValue\n"
        "from .Exceptions import EC_SDK_Runtime_Error\n"
        "\n"
        "class ECLibAPI:\n"
        "    def __init__(self, path):\n"
        "        self.path = path\n"
        "        self.MAX_NUMBER_OF_CHANNELS = 16\n"
    )
    (pkg / "__init__.py").write_text("from .ECLibAPI import ECLibAPI\n")

    (root / "lib").mkdir()
    (root / "lib" / "eclib64.dll").write_bytes(b"not really a dll")
    return root


@pytest.fixture
def fake_sdk(tmp_path: Path) -> Path:
    return _write_fake_sdk(tmp_path / "biologic_ec_sdk")


def test_the_package_loads_and_is_reachable_under_both_names(fake_sdk):
    modules = vendor.load_sdk(fake_sdk)
    # `Python` because the vendor's own absolute import needs it; the alias so
    # nothing downstream has to say `import Python`.
    assert (
        sys.modules[vendor.VENDOR_PACKAGE_NAME]
        is sys.modules[vendor.VENDOR_MODULE_NAME]
    )
    assert modules.api_class.__name__ == "ECLibAPI"
    assert modules.error_class.__name__ == "EC_SDK_Runtime_Error"
    assert modules.sdk_root == fake_sdk


def test_the_absolute_python_import_inside_the_package_resolves(fake_sdk):
    # This is the whole reason the package cannot be loaded under a private
    # name: Exceptions/EC_SDK_Runtime_Error.py imports Python.Constants
    # absolutely.
    modules = vendor.load_sdk(fake_sdk)
    assert modules.error_class("boom", 1).code == 1


def test_there_is_exactly_one_copy_of_every_enum(fake_sdk):
    # Importing the package twice (once per name) would give two ErrorCode
    # enums, and an `is` or `except` against the wrong copy would never match
    # while looking perfectly correct.
    modules = vendor.load_sdk(fake_sdk)
    from_alias = sys.modules[vendor.VENDOR_MODULE_NAME]
    inner = sys.modules[f"{vendor.VENDOR_PACKAGE_NAME}.Constants"]
    assert modules.constants is inner
    assert from_alias.ECLibAPI is modules.api_class
    assert (
        sys.modules[f"{vendor.VENDOR_PACKAGE_NAME}.Constants"].ErrorCode
        is modules.constants.ErrorCode
    )


def test_loading_the_same_root_twice_reuses_the_loaded_package(fake_sdk):
    first = vendor.load_sdk(fake_sdk)
    second = vendor.load_sdk(fake_sdk)
    assert first.constants is second.constants
    assert first.api_class is second.api_class


def test_a_second_sdk_root_in_one_process_is_refused(tmp_path):
    a = _write_fake_sdk(tmp_path / "a")
    b = _write_fake_sdk(tmp_path / "b")
    vendor.load_sdk(a)
    # Both roots want the name `Python`. Serving a's bindings under b's config
    # would be undiagnosable, so it is an error rather than a silent reuse.
    with pytest.raises(ImportError, match="already loaded from"):
        vendor.load_sdk(b)


def test_a_foreign_top_level_python_module_is_not_clobbered(fake_sdk):
    import types

    intruder = types.ModuleType(vendor.VENDOR_PACKAGE_NAME)
    intruder.__file__ = "/somewhere/else.py"
    sys.modules[vendor.VENDOR_PACKAGE_NAME] = intruder
    try:
        with pytest.raises(ImportError, match="foreign top-level"):
            vendor.load_sdk(fake_sdk)
        assert sys.modules[vendor.VENDOR_PACKAGE_NAME] is intruder
    finally:
        sys.modules.pop(vendor.VENDOR_PACKAGE_NAME, None)


def test_a_missing_sdk_directory_says_so(tmp_path):
    with pytest.raises(FileNotFoundError, match="not a directory"):
        vendor.load_sdk(tmp_path / "nope")


def test_a_directory_that_is_not_the_sdk_root_says_so(tmp_path):
    # Pointing sdk_path at the inner Python/ directory instead of the root is
    # the obvious mistake; it must not read as "SDK missing".
    with pytest.raises(FileNotFoundError, match="point sdk_path at"):
        vendor.load_sdk(tmp_path)


def test_a_failed_import_does_not_leave_a_half_built_module_registered(tmp_path):
    root = tmp_path / "broken"
    pkg = root / "Python"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("raise RuntimeError('boom')\n")
    with pytest.raises(RuntimeError, match="boom"):
        vendor.load_sdk(root)
    # A registered-but-unexecuted module would make the next load silently
    # return a stub whose attributes are all missing.
    assert vendor.VENDOR_PACKAGE_NAME not in sys.modules


def test_unload_releases_the_name_for_a_different_root(tmp_path):
    a = _write_fake_sdk(tmp_path / "a")
    b = _write_fake_sdk(tmp_path / "b")
    vendor.load_sdk(a)
    vendor.unload()
    assert vendor.VENDOR_PACKAGE_NAME not in sys.modules
    assert vendor.load_sdk(b).sdk_root == b


def test_the_dll_and_license_paths_are_derived_from_the_root(fake_sdk):
    assert vendor.dll_path(fake_sdk) == fake_sdk / "lib" / "eclib64.dll"
    assert vendor.has_license(fake_sdk) is False
    (fake_sdk / "license_biologic_deadbeef.lic").write_text("x")
    assert vendor.has_license(fake_sdk) is True


def test_open_api_constructs_the_api_over_the_dll(fake_sdk):
    api, modules = vendor.open_api(fake_sdk)
    assert api.path == str(fake_sdk / "lib" / "eclib64.dll")
    assert modules.constants is not None


def test_open_api_names_a_missing_library(fake_sdk):
    (fake_sdk / "lib" / "eclib64.dll").unlink()
    with pytest.raises(FileNotFoundError, match="no EC-Lib library"):
        vendor.open_api(fake_sdk)


def test_a_member_resolves_by_name(fake_sdk):
    modules = vendor.load_sdk(fake_sdk)
    got = vendor.member(modules.constants, "IRangeValue", "EC_SDK_IRANGE_1mA")
    assert got.value == 8


def test_an_aliased_member_still_resolves_by_the_name_asked_for(fake_sdk):
    # The shipped VsInitial gives EC_SDK_VS_IREF and EC_SDK_VS_EREF the same
    # value, so the second is a Python alias. Name lookup handles that; a
    # value round-trip would hand back the wrong name.
    modules = vendor.load_sdk(fake_sdk)
    eref = vendor.member(modules.constants, "VsInitial", "EC_SDK_VS_EREF")
    iref = vendor.member(modules.constants, "VsInitial", "EC_SDK_VS_IREF")
    assert eref is iref
    assert iref.value == 0


def test_an_unknown_enum_or_member_raises_rather_than_coercing(fake_sdk):
    modules = vendor.load_sdk(fake_sdk)
    with pytest.raises(ValueError, match="no enum 'NotAnEnum'"):
        vendor.member(modules.constants, "NotAnEnum", "X")
    # A member this SDK build lacks must not fall through to a neighbouring
    # current range.
    with pytest.raises(ValueError, match="EC_SDK_IRANGE_100pA"):
        vendor.member(modules.constants, "IRangeValue", "EC_SDK_IRANGE_100pA")
