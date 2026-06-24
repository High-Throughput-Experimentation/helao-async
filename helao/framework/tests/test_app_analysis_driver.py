"""Tests for helao.framework.app.analysis_driver (Wave C port).

Covers:
- ``_resolve_analysis_class``: resolves a known BaseAnalysis subclass by name
  and by scan; gracefully returns None for missing/ambiguous cases.
- ``load_analysis_classes``: returns empty dict when deployment is None or
  analyses list is empty; no live import needed for empty-list path.
- ``make_analysis_app``: returns a BaseAPI (FastAPI) instance with
  ``app.state.base`` wired, without triggering the FastAPI startup event
  (AnalysisSyncer is deferred to startup — no live S3/Postgres needed at
  build time).
- ``AnalysisExecutor``: importable and subclasses the framework Executor.
- ``AnalysisSyncer``: no HelaoSyncer base (bases == (object,)).

NOT covered here (require live S3/Postgres):
- ``AnalysisSyncer.get_loader`` (calls pgs3.EcheUvisLoader which hits the DB)
- ``AnalysisSyncer.sync_ana`` (calls self.loader.get_prc + S3 upload)
- ``AnalysisSyncer.batch_calc`` (calls LocalLoader on a real zip)
- ``AnalysisExecutor._exec`` (calls driver.batch_calc at runtime)
"""

import types
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI

from helao.framework.app.analysis_driver import (
    AnalysisExecutor,
    AnalysisSyncer,
    _resolve_analysis_class,
    load_analysis_classes,
    make_analysis_app,
)
from helao.framework.app.base_api import BaseAPI
from helao.framework.domain.analysis.base_analysis import BaseAnalysis
from helao.framework.domain.executor import Executor


# ---------------------------------------------------------------------------
# Helpers: a minimal concrete BaseAnalysis subclass for injection
# ---------------------------------------------------------------------------

class _ConcreteAnalysis(BaseAnalysis):
    """Minimal concrete analysis for resolver tests."""

    analysis_name = "concrete_test"


# ---------------------------------------------------------------------------
# AnalysisSyncer — base class audit
# ---------------------------------------------------------------------------

class TestAnalysisSyncerBaseDropped:
    def test_no_helao_syncer_base(self):
        """AnalysisSyncer must be a direct object subclass (HelaoSyncer dropped)."""
        assert AnalysisSyncer.__bases__ == (object,), (
            f"Expected (object,), got {AnalysisSyncer.__bases__}"
        )

    def test_has_to_s3_method(self):
        """to_s3 must be defined directly on AnalysisSyncer (inlined, not inherited)."""
        assert "to_s3" in AnalysisSyncer.__dict__, (
            "to_s3 not found in AnalysisSyncer.__dict__ — may not have been inlined"
        )


# ---------------------------------------------------------------------------
# _resolve_analysis_class
# ---------------------------------------------------------------------------

class TestResolveAnalysisClass:
    def _make_module(self, name: str, members: dict) -> types.ModuleType:
        """Create a fake module with the given member dict."""
        mod = types.ModuleType(name)
        mod.__name__ = name
        for attr, val in members.items():
            setattr(mod, attr, val)
            # Only set __module__ on user-defined classes (builtins like int
            # have an immutable __module__ and would raise TypeError).
            if isinstance(val, type) and val.__module__ != "builtins":
                try:
                    val.__module__ = name
                except (TypeError, AttributeError):
                    pass
        return mod

    def test_explicit_class_name_found(self):
        mod = self._make_module(
            "mymod", {"_ConcreteAnalysis": _ConcreteAnalysis}
        )
        result = _resolve_analysis_class(mod, "mymod", "_ConcreteAnalysis")
        assert result is _ConcreteAnalysis

    def test_explicit_class_name_not_found(self):
        mod = self._make_module("mymod", {})
        result = _resolve_analysis_class(mod, "mymod", "NonExistent")
        assert result is None

    def test_explicit_class_name_wrong_type(self):
        mod = self._make_module("mymod", {"NotAnAnalysis": int})
        result = _resolve_analysis_class(mod, "mymod", "NotAnAnalysis")
        assert result is None

    def test_scan_single_candidate(self):
        mod = self._make_module("mymod", {"_ConcreteAnalysis": _ConcreteAnalysis})
        # no class_name — scan mode
        result = _resolve_analysis_class(mod, "mymod", "")
        assert result is _ConcreteAnalysis

    def test_scan_no_candidates(self):
        mod = self._make_module("mymod", {"NotBase": int})
        result = _resolve_analysis_class(mod, "mymod", "")
        assert result is None

    def test_scan_multiple_candidates_returns_none(self):
        """When two BaseAnalysis subclasses are in a module, scan must refuse."""

        class _AltAnalysis(BaseAnalysis):
            analysis_name = "alt"

        _AltAnalysis.__module__ = "mymod"
        _ConcreteAnalysis.__module__ = "mymod"

        mod = self._make_module(
            "mymod",
            {"_ConcreteAnalysis": _ConcreteAnalysis, "_AltAnalysis": _AltAnalysis},
        )
        result = _resolve_analysis_class(mod, "mymod", "")
        assert result is None

        # restore __module__ so other tests are not affected
        _ConcreteAnalysis.__module__ = _ConcreteAnalysis.__module__


# ---------------------------------------------------------------------------
# load_analysis_classes
# ---------------------------------------------------------------------------

class TestLoadAnalysisClasses:
    def test_no_deployment_returns_empty(self):
        result = load_analysis_classes(["some_module"], deployment=None)
        assert result == {}

    def test_empty_analyses_list_returns_empty(self):
        result = load_analysis_classes([], deployment="test")
        assert result == {}

    def test_none_analyses_returns_empty(self):
        result = load_analysis_classes(None, deployment="test")
        assert result == {}

    def test_failed_import_skipped(self):
        """A module that cannot be imported is skipped gracefully."""
        result = load_analysis_classes(
            ["nonexistent_module_xyz"], deployment="test"
        )
        assert result == {}

    def test_successful_load_maps_endpoint_name(self):
        """When the import succeeds, result maps 'analyze_<module>' -> class."""
        fake_mod = types.ModuleType("fake_ana")
        fake_mod.__name__ = "helao.deploy.test.drivers.data.analyses.fake_ana"

        class _FakeAna(BaseAnalysis):
            analysis_name = "fake"

        _FakeAna.__module__ = fake_mod.__name__
        setattr(fake_mod, "_FakeAna", _FakeAna)

        with patch(
            "helao.framework.app.analysis_driver.import_module",
            return_value=fake_mod,
        ):
            result = load_analysis_classes(
                ["fake_ana:_FakeAna"], deployment="test"
            )

        assert "analyze_fake_ana" in result
        assert result["analyze_fake_ana"] is _FakeAna


# ---------------------------------------------------------------------------
# make_analysis_app
# ---------------------------------------------------------------------------

class TestMakeAnalysisApp:
    """make_analysis_app builds a BaseAPI without triggering startup.

    The AnalysisSyncer is instantiated in the FastAPI startup event, so the
    test never runs the startup hook — no live S3/Postgres is needed.
    """

    def _minimal_config(self, server_key: str, tmp_root: str) -> dict:
        return {
            "root": tmp_root,
            "deployment": "test",
            "servers": {
                server_key: {
                    "host": "localhost",
                    "port": 8765,
                    "group": "action",
                    "fast": "analysis_driver",
                    "params": {
                        "analyses": [],
                        "local_only": True,
                    },
                }
            },
        }

    def test_returns_baseapi_instance(self, tmp_path):
        server_key = "analysis_test_srv"
        cfg = self._minimal_config(server_key, str(tmp_path))

        import helao.framework.support.config_loader as fw_cfg
        original_cfg = fw_cfg.CONFIG

        try:
            from munch import munchify
            fw_cfg.CONFIG = munchify(cfg)

            app = make_analysis_app(server_key)

            assert isinstance(app, FastAPI), (
                f"Expected FastAPI instance, got {type(app)}"
            )
            assert isinstance(app, BaseAPI), (
                f"Expected BaseAPI instance, got {type(app)}"
            )
        finally:
            fw_cfg.CONFIG = original_cfg

    def test_app_state_base_wired(self, tmp_path):
        server_key = "analysis_state_srv"
        cfg = self._minimal_config(server_key, str(tmp_path))

        import helao.framework.support.config_loader as fw_cfg
        original_cfg = fw_cfg.CONFIG

        try:
            from munch import munchify
            fw_cfg.CONFIG = munchify(cfg)

            app = make_analysis_app(server_key)

            assert hasattr(app, "base"), "app.base not set"
            assert hasattr(app.state, "base"), "app.state.base not set"
        finally:
            fw_cfg.CONFIG = original_cfg

    def test_driver_none_before_startup(self, tmp_path):
        """Driver must be None before the startup event fires (deferred init)."""
        server_key = "analysis_deferred_srv"
        cfg = self._minimal_config(server_key, str(tmp_path))

        import helao.framework.support.config_loader as fw_cfg
        original_cfg = fw_cfg.CONFIG

        try:
            from munch import munchify
            fw_cfg.CONFIG = munchify(cfg)

            app = make_analysis_app(server_key)

            assert app.driver is None, (
                "app.driver should be None before startup (AnalysisSyncer deferred)"
            )
        finally:
            fw_cfg.CONFIG = original_cfg

    def test_private_endpoints_registered(self, tmp_path):
        """list_running_tasks and list_queued_tasks endpoints must exist."""
        server_key = "analysis_priv_srv"
        cfg = self._minimal_config(server_key, str(tmp_path))

        import helao.framework.support.config_loader as fw_cfg
        original_cfg = fw_cfg.CONFIG

        try:
            from munch import munchify
            fw_cfg.CONFIG = munchify(cfg)

            app = make_analysis_app(server_key)

            route_paths = {r.path for r in app.routes}
            assert "/list_running_tasks" in route_paths, (
                "/list_running_tasks not registered"
            )
            assert "/list_queued_tasks" in route_paths, (
                "/list_queued_tasks not registered"
            )
        finally:
            fw_cfg.CONFIG = original_cfg


# ---------------------------------------------------------------------------
# AnalysisExecutor
# ---------------------------------------------------------------------------

class TestAnalysisExecutorImportable:
    def test_is_importable(self):
        assert AnalysisExecutor is not None

    def test_subclasses_framework_executor(self):
        assert issubclass(AnalysisExecutor, Executor), (
            f"AnalysisExecutor does not subclass framework Executor; "
            f"MRO: {AnalysisExecutor.__mro__}"
        )
