"""Tests for HelaoLoader in the framework hlo_loader adapter.

HelaoLoader.__init__ calls self.connect(), which opens a boto3 session and a
sqlmodel engine.  Both require real credentials and network access.  These
tests therefore do NOT construct a live HelaoLoader instance — instead they:

  1. Verify the class is importable from the framework adapter (not from
     helao.core).
  2. Verify the expected public API (all methods that callers depend on) is
     present on the class.
  3. Verify the wrapper model classes (HelaoAction, HelaoExperiment,
     HelaoSequence, HelaoProcess) are importable alongside HelaoLoader.
  4. Verify HelaoLoader.__init__ signature accepts the documented keyword args
     (env_file, cache_s3, cache_json, cache_sql) via inspect — without
     actually calling the constructor.

Live-connection tests (S3 / Postgres) are explicitly out-of-scope here; they
belong in an integration-test suite run against the real backend.
"""

import inspect

import pytest

from helao.framework.adapters.loaders.hlo_loader import (
    HelaoLoader,
    HelaoAction,
    HelaoExperiment,
    HelaoSequence,
    HelaoProcess,
    HelaoModel,
    HelaoDataModel,
    HelaoSolid,
)


# ---------------------------------------------------------------------------
# 1. Import sanity
# ---------------------------------------------------------------------------


def test_helao_loader_importable():
    """HelaoLoader can be imported from the framework adapter."""
    assert HelaoLoader is not None


def test_wrapper_classes_importable():
    """All wrapper model classes are importable alongside HelaoLoader."""
    for cls in (HelaoAction, HelaoExperiment, HelaoSequence, HelaoProcess,
                HelaoModel, HelaoDataModel, HelaoSolid):
        assert cls is not None, f"{cls} not importable"


# ---------------------------------------------------------------------------
# 2. Public API surface
# ---------------------------------------------------------------------------

_EXPECTED_METHODS = [
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
]


@pytest.mark.parametrize("method_name", _EXPECTED_METHODS)
def test_helao_loader_has_method(method_name):
    """HelaoLoader exposes the expected public methods."""
    assert hasattr(HelaoLoader, method_name), (
        f"HelaoLoader missing expected method: {method_name}"
    )
    assert callable(getattr(HelaoLoader, method_name))


# ---------------------------------------------------------------------------
# 3. Constructor signature
# ---------------------------------------------------------------------------


def test_helao_loader_init_signature():
    """HelaoLoader.__init__ accepts the documented keyword arguments."""
    sig = inspect.signature(HelaoLoader.__init__)
    params = sig.parameters
    assert "env_file" in params
    assert "cache_s3" in params
    assert "cache_json" in params
    assert "cache_sql" in params
    # Defaults
    assert params["env_file"].default == ".env"
    assert params["cache_s3"].default is False
    assert params["cache_json"].default is False
    assert params["cache_sql"].default is False


# ---------------------------------------------------------------------------
# 4. Cache attribute names (class-level: verifiable without construction)
# ---------------------------------------------------------------------------


def test_helao_loader_is_a_class_with_del():
    """HelaoLoader defines __del__ (closes S3 client on GC)."""
    assert hasattr(HelaoLoader, "__del__")


# ---------------------------------------------------------------------------
# 5. HelaoDataModelMixin inheritance
# ---------------------------------------------------------------------------


def test_helao_data_model_inherits_mixin():
    """HelaoDataModel inherits from HelaoDataModelMixin (carries data-file accessors)."""
    from helao.framework.adapters.loaders.model_base import HelaoDataModelMixin

    assert issubclass(HelaoDataModel, HelaoDataModelMixin)


# ---------------------------------------------------------------------------
# 6. HelaoSolid stores sample_label
# ---------------------------------------------------------------------------


def test_helao_solid_stores_label():
    """HelaoSolid construction does not require network and stores sample_label."""
    solid = HelaoSolid("ag-pt-ag__1__1__1")
    assert solid.sample_label == "ag-pt-ag__1__1__1"
