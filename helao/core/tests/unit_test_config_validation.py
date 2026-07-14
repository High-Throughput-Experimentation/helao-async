"""Validate every tracked deployment config against the HelaoConfig schema.

Guards the 3b invariant: the typed config model must accept every config the
launchers can be pointed at (helao/deploy/{hte,test}/configs/*.yml). Baseline
evidence 2026-07-10: 25/25 pass. Any future failure here is a schema/config
divergence that would break the launch-time validation path.
"""

__all__ = ["config_validation_unit_test"]

import os
from glob import glob

from helao.helpers.config_loader import HelaoConfig, ServerConfig, read_config
from helao.core.tests._test_utils import TestReporter


def _repo_root() -> str:
    here = os.path.abspath(__file__)
    return os.path.abspath(os.path.join(here, "..", "..", "..", ".."))


def config_validation_unit_test() -> bool:
    reporter = TestReporter("config_validation")
    root = _repo_root()
    for deployment in ("hte", "test"):
        paths = sorted(
            glob(os.path.join(root, "helao", "deploy", deployment, "configs", "*.yml"))
        )
        reporter.check(
            f"{deployment}: at least one tracked config found",
            lambda paths=paths: len(paths) >= 1,
        )
        for path in paths:
            name = f"{deployment}/{os.path.basename(path)}"
            try:
                parsed = HelaoConfig.model_validate(read_config(path))
                ok = all(
                    isinstance(v, ServerConfig) for v in (parsed.servers or {}).values()
                )
            except Exception as exc:  # noqa: BLE001
                print(f"  {name}: {exc!r}")
                ok = False
            reporter.check(f"{name} validates against HelaoConfig", lambda ok=ok: ok)
    return reporter.success()


if __name__ == "__main__":
    raise SystemExit(0 if config_validation_unit_test() else 1)
