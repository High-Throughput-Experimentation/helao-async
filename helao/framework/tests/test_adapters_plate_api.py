"""Tests for helao.framework.adapters.plate_api (HTEPlateAPI).

Strategy
--------
HTEPlateAPI.__init__ checks for ``HELAO_CREDENTIALS`` env var and, if set
and the file exists, constructs a HelaoLoader.  When neither is present (the
normal CI state), ``self.loader`` stays None and no network connections are
made.  ``has_access`` therefore returns False (delegates to the legacy fallback
which also has no J:\\ access in CI).

Construction is safe without network access.

Verified without network:
  - Module import
  - Class and public-method surface (inspect/hasattr)
  - Construction with loader=None
  - Scalar-attribute values at construction time
  - has_access returns False
  - Legacy-delegating methods (check_plateid, check_printrecord_plateid,
    check_annealrecord_plateid, get_platemap_plateid, get_info_plateid,
    get_elements_plateid, get_rcp_plateid) for legacy plate ids < 10000
    return expected fallback values without raising

Skipped (require live HTE Plate API or AWS credentials):
  - get_info / get_print / get_print_plateid — POST/GET to PLATE_API endpoint
  - get_platemap / get_platemapdlist — S3 bucket access
  - get_elements_plateid for plateid >= 10000 — calls get_info + get_print
  - has_access with valid HelaoLoader — calls STS get_caller_identity
"""

import inspect

import pytest

from helao.framework.adapters.plate_api import HTEPlateAPI
from helao.framework.adapters.legacy_api import HTELegacyAPI


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def api():
    """HTEPlateAPI constructed without credentials (loader=None)."""
    return HTEPlateAPI()


# ---------------------------------------------------------------------------
# Module-level smoke
# ---------------------------------------------------------------------------


def test_import():
    """HTEPlateAPI is importable from its new framework path."""
    assert HTEPlateAPI is not None


def test_legacy_api_import_from_framework():
    """HTELegacyAPI dependency resolves to the framework copy."""
    from helao.framework.adapters.plate_api import HTELegacyAPI as _Cls
    assert _Cls.__module__ == "helao.framework.adapters.legacy_api"


def test_public_surface():
    """All expected public methods are present on HTEPlateAPI."""
    expected = [
        "has_access",
        "get_info",
        "get_print_plateid",
        "get_platemap",
        "get_platemapdlist",
        "get_info_plateid",
        "get_platemap_plateid",
        "get_rcp_plateid",
        "check_plateid",
        "check_printrecord_plateid",
        "check_annealrecord_plateid",
        "get_print",
        "get_elements_plateid",
    ]
    for name in expected:
        assert hasattr(HTEPlateAPI, name), f"Missing: {name}"


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_construction_no_credentials(api):
    """Constructs safely when no env file or HELAO_CREDENTIALS is set."""
    assert isinstance(api, HTEPlateAPI)


def test_loader_is_none_without_credentials(api):
    """loader attribute is None when no credentials file is available."""
    assert api.loader is None


def test_map_cache_empty_after_construction(api):
    assert api.map_cache == {}


def test_legacy_threshold(api):
    """Default legacy_plateid_threshold is 10000."""
    assert api.legacy_plateid_threshold == 10000


def test_legacy_api_instance(api):
    """legacy_api is an HTELegacyAPI instance."""
    assert isinstance(api.legacy_api, HTELegacyAPI)


# ---------------------------------------------------------------------------
# has_access
# ---------------------------------------------------------------------------


def test_has_access_false_no_creds_no_jdrive(api):
    """has_access returns False when loader=None and J:\\ paths are absent."""
    assert api.has_access is False


# ---------------------------------------------------------------------------
# Legacy delegation — plate ids below threshold
# ---------------------------------------------------------------------------
# These call through to HTELegacyAPI which returns None/False when J:\\ is
# absent.  The important thing is that no exception is raised and the return
# type is sensible.


def test_check_plateid_legacy_range(api):
    """check_plateid for a legacy id returns False (no J:\\ access)."""
    result = api.check_plateid(1234)
    assert result is False


def test_check_printrecord_legacy_range(api):
    """check_printrecord_plateid for a legacy id returns None/False without error."""
    result = api.check_printrecord_plateid(1234)
    assert result is False or result is None


def test_check_annealrecord_legacy_range(api):
    """check_annealrecord_plateid for a legacy id returns None/False without error."""
    result = api.check_annealrecord_plateid(1234)
    assert result is False or result is None


def test_get_platemap_plateid_legacy_range(api):
    """get_platemap_plateid for a legacy id returns [] (empty cache) without error."""
    result = api.get_platemap_plateid(1234)
    assert result == [] or result is None


def test_get_info_plateid_legacy_range(api):
    """get_info_plateid for a legacy id returns None when J:\\ is absent."""
    result = api.get_info_plateid(1234)
    assert result is None


def test_get_elements_plateid_legacy_range(api):
    """get_elements_plateid for a legacy id returns None when J:\\ is absent."""
    result = api.get_elements_plateid(1234)
    assert result is None


def test_get_rcp_plateid_returns_none(api):
    """get_rcp_plateid is a no-op that returns None (both legacy and new ids)."""
    assert api.get_rcp_plateid(1234) is None
    assert api.get_rcp_plateid(99999) is None


# ---------------------------------------------------------------------------
# Live API calls — skipped (no credentials / no network in CI)
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="Requires live HTE Plate API credentials and network access")
def test_get_info_live():
    api = HTEPlateAPI()
    result = api.get_info(10001)
    assert result is not None


@pytest.mark.skip(reason="Requires live HTE Plate API credentials and network access")
def test_get_platemap_live():
    api = HTEPlateAPI()
    result = api.get_platemap(1)
    assert result is not None


@pytest.mark.skip(reason="Requires S3 access via HelaoLoader")
def test_has_access_with_credentials():
    import os
    cred_path = os.environ.get("HELAO_CREDENTIALS", "")
    if not cred_path:
        pytest.skip("HELAO_CREDENTIALS not set")
    api = HTEPlateAPI(env_file=cred_path)
    assert api.has_access is True
