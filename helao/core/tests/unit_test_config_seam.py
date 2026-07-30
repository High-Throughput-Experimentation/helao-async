"""Verify the 3b typed-config injection seam on ``Base``/``HelaoFastAPI``/``HelaoBokehAPI``.

Uses a duck-typed stub app instead of a real FastAPI instance: ``Base.__init__``
only reads ``app.server``, ``app.server_cfg``, ``app.server_params``, and
``app.helao_cfg`` (grep-verified), so no uvicorn/ASGI machinery is needed to
exercise the seam end-to-end.

Covers:
- Default path (``Base(app=stub)``) and injected path
  (``Base(app=stub, helao_cfg=validated)``) produce identical orch topology
  and ``run_type`` results, matching legacy inline dict navigation.
- ``world_cfg`` remains the same dict object the stub exposes (deployment
  code contract; the dict shim is not replaced by the typed view).
- ``typed_server_cfg`` reflects the per-server slice of the typed config.
- A config missing ``run_type`` raises ``ValueError`` (schema-validation wrap).
- ``HelaoFastAPI``/``HelaoBokehAPI`` accept an injected ``helao_cfg`` and use
  it instead of ``config_loader.CONFIG``.
"""

__all__ = ["config_seam_unit_test"]

import os
import tempfile
from types import SimpleNamespace

from helao.core.models.machine import MachineModel
from helao.core.servers.base import Base
from helao.core.tests._test_utils import TestReporter
from helao.helpers import config_loader
from helao.helpers.config_loader import HelaoConfig, read_validated_config
from helao.helpers.server_api import HelaoBokehAPI, HelaoFastAPI


def _repo_root() -> str:
    here = os.path.abspath(__file__)
    return os.path.abspath(os.path.join(here, "..", "..", "..", ".."))


def _demo0_path() -> str:
    return os.path.join(_repo_root(), "helao", "deploy", "test", "configs", "demo0.yml")


def _make_stub_app(config_dict: dict, server_name: str = "ORCH") -> SimpleNamespace:
    server_cfg = config_dict["servers"][server_name]
    stub = SimpleNamespace()
    stub.server = MachineModel(
        server_name=server_name,
        machine_name="testhost",
        hostname=server_cfg["host"],
        port=server_cfg["port"],
    )
    stub.server_cfg = server_cfg
    stub.server_params = server_cfg.get("params", {})
    stub.helao_cfg = config_dict
    return stub


def config_seam_unit_test() -> bool:
    reporter = TestReporter("config_seam")

    config_dict, _validated = read_validated_config(_demo0_path())
    tmp_root = tempfile.mkdtemp(prefix="config_seam_")
    config_dict["root"] = tmp_root
    # Re-validate against the tempdir root so the injected typed_cfg matches
    # the dict the stub app exposes (root differs from the on-disk value).
    validated = HelaoConfig.model_validate(config_dict)

    # Pre-seed LOGS/ntpLastSync.txt: Base.__init__ reads this file
    # unconditionally (pre-existing behavior, out of scope for the config
    # seam) and a brand-new tempdir has never had it written.
    logs_dir = os.path.join(tmp_root, "LOGS")
    os.makedirs(logs_dir, exist_ok=True)
    with open(os.path.join(logs_dir, "ntpLastSync.txt"), "w") as f:
        f.write("0,0.0")

    stub = _make_stub_app(config_dict, server_name="ORCH")

    # Legacy inline dict navigation, computed independently for comparison.
    legacy_orch_keys = [
        k
        for k, d in config_dict.get("servers", {}).items()
        if d["group"] == "orchestrator"
    ]
    legacy_orch_key = legacy_orch_keys[0]
    legacy_orch_host = config_dict["servers"][legacy_orch_key]["host"]
    legacy_orch_port = config_dict["servers"][legacy_orch_key]["port"]
    legacy_run_type = config_dict["run_type"].lower()

    b1 = Base(app=stub)
    b2 = Base(app=stub, helao_cfg=validated)

    reporter.check(
        "default and injected paths agree on orch_key",
        lambda: b1.orch_key == b2.orch_key == legacy_orch_key,
    )
    reporter.check(
        "default and injected paths agree on orch_host",
        lambda: b1.orch_host == b2.orch_host == legacy_orch_host,
    )
    reporter.check(
        "default and injected paths agree on orch_port",
        lambda: b1.orch_port == b2.orch_port == legacy_orch_port,
    )
    reporter.check(
        "default and injected paths agree on run_type",
        lambda: b1.run_type == b2.run_type == legacy_run_type,
    )
    reporter.check(
        "world_cfg shim is the same object as stub.helao_cfg",
        lambda: b1.world_cfg is stub.helao_cfg,
    )
    reporter.check(
        "typed_server_cfg.host matches world_cfg dict nav",
        lambda: b1.typed_server_cfg.host == b1.world_cfg["servers"]["ORCH"]["host"],
    )

    # Negative: missing run_type must raise ValueError (ValidationError wrap).
    bad_config = dict(config_dict)
    bad_config.pop("run_type", None)
    bad_stub = _make_stub_app(bad_config, server_name="ORCH")

    def _missing_run_type_raises() -> bool:
        try:
            Base(app=bad_stub)
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
