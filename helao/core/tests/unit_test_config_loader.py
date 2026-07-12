"""Unit tests for ``helao.helpers.config_loader``.

Exercises the four resolution paths of :func:`read_config`:

* explicit ``.yml`` path
* bare prefix matched against ``helao/deploy/*/configs``
* nonexistent explicit ``.yml`` path (should raise ``FileNotFoundError``)
* prefix that does not match any deployment (should raise
  ``FileNotFoundError``)

Also verifies that the returned dict gets the augmenting path keys
(``loaded_config_path``, ``helao_repo_root``, ``helao_credentials_path``)
and parses through the :class:`HelaoConfig` pydantic schema cleanly.
"""

__all__ = ["config_loader_unit_test"]

import os
import tempfile
import traceback

from helao.helpers import config_loader
from helao.helpers.config_loader import (
    HelaoConfig,
    ServerConfig,
    install_global_config,
    load_global_config,
    read_config,
    read_validated_config,
)
from helao.core.tests._test_utils import TestReporter


def _repo_root() -> str:
    """Return the absolute path of the helao-async repo root."""
    here = os.path.abspath(__file__)
    # tests/__file__ -> helao/core/tests/<file>
    return os.path.abspath(os.path.join(here, "..", "..", "..", ".."))


def config_loader_unit_test() -> bool:
    """Run all config-loader assertions and report pass/fail."""
    reporter = TestReporter("config_loader")

    try:
        reporter.section("HelaoConfig schema accepts the test demo0.yml shape")
        demo_path = os.path.join(
            _repo_root(),
            "helao",
            "deploy",
            "test",
            "configs",
            "demo0.yml",
        )
        reporter.check(
            "test/configs/demo0.yml exists",
            lambda: os.path.exists(demo_path),
        )

        config = read_config(demo_path)
        reporter.check(
            "read_config returns a dict",
            lambda: isinstance(config, dict),
        )
        reporter.check(
            "loaded config has 'servers' mapping",
            lambda: isinstance(config.get("servers"), dict),
        )
        reporter.check(
            "loaded config has augmented loaded_config_path",
            lambda: os.path.abspath(config["loaded_config_path"])
            == os.path.abspath(demo_path),
        )
        reporter.check(
            "loaded config has augmented helao_repo_root",
            lambda: os.path.isdir(config["helao_repo_root"]),
        )
        reporter.check(
            "loaded config has helao_credentials_path key",
            lambda: "helao_credentials_path" in config,
        )

        # validate via the HelaoConfig pydantic schema
        parsed = HelaoConfig(**config)
        reporter.check(
            "HelaoConfig parses demo0.yml without error",
            lambda: parsed.run_type == "simulation",
        )
        reporter.check(
            "HelaoConfig.servers entries are ServerConfig instances",
            lambda: all(
                isinstance(v, ServerConfig) for v in parsed.servers.values()
            ),
        )
        reporter.check(
            "Orchestrator entry round-trips OrchServerParams (dict or model)",
            lambda: parsed.servers["ORCH"].group == "orchestrator",
        )

        reporter.section("Prefix-based resolution against the deploy tree")
        prefix_config = read_config("demo0")
        reporter.check(
            "prefix 'demo0' resolves to a config dict",
            lambda: isinstance(prefix_config, dict)
            and prefix_config.get("run_type") == "simulation",
        )

        reporter.section("read_config error paths")

        def _missing_yml():
            read_config("/this/path/does/not/exist/__nope__.yml")

        reporter.check(
            "missing explicit .yml raises FileNotFoundError",
            lambda: _expect_raises(_missing_yml, FileNotFoundError),
        )

        def _missing_prefix():
            read_config("__definitely_not_a_real_prefix__")

        reporter.check(
            "unknown prefix raises FileNotFoundError",
            lambda: _expect_raises(_missing_prefix, FileNotFoundError),
        )

        reporter.section("HelaoConfig minimal acceptance")
        minimal = HelaoConfig(run_type="rt", root=tempfile.gettempdir())
        reporter.check(
            "HelaoConfig accepts a minimal run_type/root pair",
            lambda: minimal.dummy is True and minimal.simulation is True,
        )

        reporter.section("read_validated_config / install_global_config (D3 seam)")
        _saved_config = config_loader.CONFIG
        try:
            config_dict, validated = read_validated_config(demo_path)
            reporter.check(
                "read_validated_config returns a (dict, HelaoConfig) tuple",
                lambda: isinstance(config_dict, dict)
                and isinstance(validated, HelaoConfig),
            )
            reporter.check(
                "read_validated_config dict has loaded_config_path",
                lambda: os.path.abspath(config_dict["loaded_config_path"])
                == os.path.abspath(demo_path),
            )
            reporter.check(
                "read_validated_config validated view has run_type == simulation",
                lambda: validated.run_type == "simulation",
            )

            installed = install_global_config(config_dict)
            reporter.check(
                "install_global_config installs the RAW dict by object identity"
                " (D3 contract, not a model_dump)",
                lambda: config_loader.CONFIG is config_dict
                and installed is config_dict,
            )

            config_loader.CONFIG = None
            shim_returned = load_global_config(demo_path, set_global=True)
            reporter.check(
                "load_global_config shim returns the dict",
                lambda: isinstance(shim_returned, dict),
            )
            reporter.check(
                "load_global_config shim installs that same dict on CONFIG"
                " (shim parity with read_validated_config + install_global_config)",
                lambda: config_loader.CONFIG is shim_returned,
            )

            config_loader.CONFIG = None
            pure_returned = load_global_config(demo_path)
            reporter.check(
                "load_global_config default flag is a pure read (CONFIG unchanged)",
                lambda: config_loader.CONFIG is None
                and isinstance(pure_returned, dict),
            )
        finally:
            config_loader.CONFIG = _saved_config

        return reporter.success()

    except Exception as exc:  # noqa: BLE001
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        print(repr(exc), tb)
        return False


def _expect_raises(fn, exc_type) -> bool:
    """Return True if calling ``fn()`` raises an instance of ``exc_type``."""
    try:
        fn()
    except exc_type:
        return True
    except Exception:  # noqa: BLE001
        return False
    return False


if __name__ == "__main__":
    raise SystemExit(0 if config_loader_unit_test() else 1)
