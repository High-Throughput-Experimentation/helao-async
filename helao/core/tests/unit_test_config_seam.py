"""Verify the typed-config injection seam on ``ActionHost``/``HelaoFastAPI``/``HelaoBokehAPI``.

``ActionHost`` takes ``helao_cfg`` (the same seam ``HelaoFastAPI`` offers) so a
test can build a host without a launched config. The ports are passed as
stubs: ``build_wiring`` reads the global ``CONFIG`` by design, and this module
checks the config seam, not the wiring one. Ported from the legacy
``Base(app=stub)`` fixture by B7b.

Covers:
- Default path (global ``CONFIG``) and injected path (``helao_cfg=``) produce
  identical orch topology and ``run_type`` results, matching inline dict
  navigation.
- ``world_cfg`` remains the same dict object that was injected (deployment
  code contract; the dict is not replaced by a typed view).
- A config missing ``run_type`` fails ``HelaoConfig`` validation with a
  ``ValueError``. The native host does not re-validate; ``fast_launcher``
  validates through ``read_validated_config`` before any app is built, so the
  check sits on that seam.
- ``HelaoFastAPI``/``HelaoBokehAPI`` accept an injected ``helao_cfg`` and use
  it instead of ``config_loader.CONFIG``.
"""

__all__ = ["config_seam_unit_test"]

import os
import tempfile
from types import SimpleNamespace
from typing import Any

from helao.core.tests._test_utils import TestReporter
from helao.helpers import config_loader
from helao.helpers.config_loader import HelaoConfig, read_validated_config
from helao.helpers.server_api import HelaoBokehAPI, HelaoFastAPI
from helao.hexagon.app.action_host import ActionHost
from helao.hexagon.app.wiring import PortWiring

SERVER_KEY = "CPSIM"


def _repo_root() -> str:
    here = os.path.abspath(__file__)
    return os.path.abspath(os.path.join(here, "..", "..", "..", ".."))


def _demo0_path() -> str:
    return os.path.join(_repo_root(), "helao", "deploy", "test", "configs", "demo0.yml")


class _Stub:
    """A port that only answers ``meta_writer_for``; anything else is a test bug."""

    def meta_writer_for(self, base):
        return object()

    def __getattr__(self, name):
        raise AssertionError(f"port member {name!r} used unexpectedly")


def _stub() -> Any:
    # typed Any: one stub stands in for every port Protocol
    return _Stub()


def _wiring() -> PortWiring:
    return PortWiring(
        config=_stub(),
        logging=_stub(),
        clock=_stub(),
        transport=_stub(),
        state_persistence=_stub(),
        status=_stub(),
        health=_stub(),
        artifact_store=_stub(),
        data_sink=_stub(),
    )


def _host(helao_cfg=None) -> ActionHost:
    return ActionHost(
        server_key=SERVER_KEY,
        server_title=SERVER_KEY,
        description="config seam",
        version=1.0,
        wiring=_wiring(),
        helao_cfg=helao_cfg,
    )


def config_seam_unit_test() -> bool:
    reporter = TestReporter("config_seam")

    config_dict, _validated = read_validated_config(_demo0_path())
    config_dict["root"] = tempfile.mkdtemp(prefix="config_seam_")

    # Inline dict navigation, computed independently for comparison.
    orch_keys = [
        k
        for k, d in config_dict.get("servers", {}).items()
        if d["group"] == "orchestrator"
    ]
    orch_key = orch_keys[0]
    orch_host = config_dict["servers"][orch_key]["host"]
    orch_port = config_dict["servers"][orch_key]["port"]
    run_type = config_dict["run_type"].lower()

    saved_config = config_loader.CONFIG
    try:
        config_loader.CONFIG = config_dict
        h1 = _host()
        config_loader.CONFIG = None
        h2 = _host(helao_cfg=config_dict)
    finally:
        config_loader.CONFIG = saved_config

    reporter.check(
        "default and injected paths agree on orch_key",
        lambda: h1.orch_key == h2.orch_key == orch_key,
    )
    reporter.check(
        "default and injected paths agree on orch_host",
        lambda: h1.orch_host == h2.orch_host == orch_host,
    )
    reporter.check(
        "default and injected paths agree on orch_port",
        lambda: h1.orch_port == h2.orch_port == orch_port,
    )
    reporter.check(
        "default and injected paths agree on run_type",
        lambda: h1.run_type == h2.run_type == run_type,
    )
    reporter.check(
        "world_cfg is the same object as the injected helao_cfg",
        lambda: h2.world_cfg is config_dict,
    )

    # Negative: missing run_type must raise ValueError (ValidationError wrap).
    bad_config = dict(config_dict)
    bad_config.pop("run_type", None)

    def _missing_run_type_raises() -> bool:
        try:
            HelaoConfig.model_validate(bad_config)
        except ValueError:
            return True
        return False

    reporter.check("missing run_type raises ValueError", _missing_run_type_raises)

    # HelaoFastAPI / HelaoBokehAPI: injected helao_cfg used instead of
    # config_loader.CONFIG. Save/restore module-level CONFIG around the check.
    saved_config = config_loader.CONFIG
    try:
        config_loader.CONFIG = None

        doc_stub = SimpleNamespace(title=None)
        bokeh_app = HelaoBokehAPI("ORCH", doc=doc_stub, helao_cfg=config_dict)
        reporter.check(
            "HelaoBokehAPI uses injected helao_cfg over config_loader.CONFIG",
            lambda: bokeh_app.helao_cfg is config_dict,
        )

        fast_app = HelaoFastAPI("ORCH", helao_cfg=config_dict)
        reporter.check(
            "HelaoFastAPI uses injected helao_cfg over config_loader.CONFIG",
            lambda: fast_app.helao_cfg is config_dict,
        )
    finally:
        config_loader.CONFIG = saved_config

    return reporter.success()


if __name__ == "__main__":
    raise SystemExit(0 if config_seam_unit_test() else 1)
