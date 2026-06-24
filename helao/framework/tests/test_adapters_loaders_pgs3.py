"""Tests for pgs3 adapter in helao.framework.adapters.loaders.pgs3.

EcheUvisLoader.__init__ calls HelaoLoader.__init__ which immediately calls
self.connect(), opening a boto3 session and a sqlmodel engine — both require
real credentials and network access.  These tests therefore do NOT construct a
live EcheUvisLoader instance.  Instead they:

  1. Verify the module imports cleanly (no side-effects at import time).
  2. Verify the module-level LOADER sentinel is present and None.
  3. Verify EcheUvisLoader is importable and is a subclass of HelaoLoader.
  4. Verify the expected public methods exist on EcheUvisLoader.
  5. Verify __init__ signature accepts the documented keyword args.
  6. Verify _annotate_plate_sample is importable (used by callers directly).

Live-connection tests (S3 / Postgres) are explicitly out-of-scope here; they
belong in an integration-test suite run against the real backend.
"""

import inspect

import pytest

import helao.framework.adapters.loaders.pgs3 as pgs3_mod
from helao.framework.adapters.loaders.pgs3 import EcheUvisLoader, _annotate_plate_sample
from helao.framework.adapters.loaders.hlo_loader import HelaoLoader


# ---------------------------------------------------------------------------
# 1. Module import sanity
# ---------------------------------------------------------------------------


def test_pgs3_module_importable():
    """The pgs3 adapter module imports without errors."""
    assert pgs3_mod is not None


def test_module_loader_sentinel_is_none():
    """pgs3.LOADER is None at import time (no live connection on import)."""
    assert pgs3_mod.LOADER is None


# ---------------------------------------------------------------------------
# 2. EcheUvisLoader class presence and inheritance
# ---------------------------------------------------------------------------


def test_echeuvislloader_importable():
    """EcheUvisLoader is importable from the pgs3 adapter."""
    assert EcheUvisLoader is not None


def test_echeuvislloader_is_helao_loader_subclass():
    """EcheUvisLoader is a subclass of HelaoLoader (from framework hlo_loader)."""
    assert issubclass(EcheUvisLoader, HelaoLoader)


# ---------------------------------------------------------------------------
# 3. Public method surface
# ---------------------------------------------------------------------------


_EXPECTED_METHODS = [
    # Inherited from HelaoLoader
    "connect",
    "reconnect",
    "run_raw_query",
    "clear_cache",
    "get_bytes",
    "get_json",
    "get_act",
    "get_exp",
    "get_seq",
    "get_prc",
    "get_hlo",
    "get_sql",
    # EcheUvisLoader-specific
    "get_sequence",
    "get_recent",
]


@pytest.mark.parametrize("method_name", _EXPECTED_METHODS)
def test_echeuvislloader_has_method(method_name):
    """EcheUvisLoader exposes the expected public methods (inherited + own)."""
    assert hasattr(EcheUvisLoader, method_name), (
        f"EcheUvisLoader missing expected method: {method_name}"
    )
    assert callable(getattr(EcheUvisLoader, method_name))


# ---------------------------------------------------------------------------
# 4. Constructor signature
# ---------------------------------------------------------------------------


def test_echeuvislloader_init_signature():
    """EcheUvisLoader.__init__ accepts the documented keyword arguments."""
    sig = inspect.signature(EcheUvisLoader.__init__)
    params = sig.parameters
    assert "env_file" in params
    assert "cache_s3" in params
    assert "cache_json" in params
    assert "cache_sql" in params
    assert params["env_file"].default == ".env"
    assert params["cache_s3"].default is False
    assert params["cache_json"].default is False
    assert params["cache_sql"].default is False


def test_get_sequence_signature():
    """EcheUvisLoader.get_sequence accepts query, sequence_uuid, sql_query_retries."""
    sig = inspect.signature(EcheUvisLoader.get_sequence)
    params = sig.parameters
    assert "query" in params
    assert "sequence_uuid" in params
    assert "sql_query_retries" in params
    assert params["sql_query_retries"].default == 5


def test_get_recent_signature():
    """EcheUvisLoader.get_recent accepts the documented keyword arguments."""
    sig = inspect.signature(EcheUvisLoader.get_recent)
    params = sig.parameters
    assert "query" in params
    assert "min_date" in params
    assert "plate_id" in params
    assert "sample_no" in params
    assert "sql_query_retries" in params
    assert params["min_date"].default == "2024-01-01"
    assert params["plate_id"].default is None
    assert params["sample_no"].default is None
    assert params["sql_query_retries"].default == 3


# ---------------------------------------------------------------------------
# 5. _annotate_plate_sample helper importable
# ---------------------------------------------------------------------------


def test_annotate_plate_sample_importable():
    """_annotate_plate_sample is importable from the pgs3 adapter."""
    assert _annotate_plate_sample is not None
    assert callable(_annotate_plate_sample)


def test_annotate_plate_sample_solid_labels():
    """_annotate_plate_sample correctly parses plate_id/sample_no from solid labels.

    The global label format for solid samples uses single underscores:
    ``solid_<assembly_prefix>_<plate_id>_<sample_no>`` — the lambda extracts
    [-2] (plate_id) and [-1] (sample_no) after split("_").
    """
    import pandas as pd

    # Use single-underscore format matching what the real query result contains.
    # "solid_somecode_1234_5" → split("_") → [..., "1234", "5"]
    data = {
        "global_label": ["solid_somecode_1234_5"],
        "sequence_uuid": ["test-uuid"],
        "sequence_params": [{"plate_id": 1234, "plate_sample_no_list": [5]}],
    }
    pdf = pd.DataFrame(data)
    result = _annotate_plate_sample(pdf)
    assert "plate_id" in result.columns
    assert "sample_no" in result.columns
    assert result.iloc[0]["plate_id"] == 1234
    assert result.iloc[0]["sample_no"] == 5


# ---------------------------------------------------------------------------
# 6. No live connection triggered at import
# ---------------------------------------------------------------------------


def test_no_live_connection_on_import():
    """Importing pgs3 does not open any S3 or database connection.

    Verified by the fact that EcheUvisLoader is a class (not an instance) and
    LOADER is None — no __init__ was invoked at module level.
    """
    assert isinstance(EcheUvisLoader, type)
    assert pgs3_mod.LOADER is None
