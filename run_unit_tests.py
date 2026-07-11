"""Aggregate unit-test runner for ``helao.core.tests``.

These are not pytest tests; each ``unit_test_*`` module under
``helao/core/tests/`` exposes a callable that prints per-assertion
results and returns ``True`` only when every assertion in that module
passed.

``launch.py`` invokes this script before launching an orchestration
group and aborts on a non-zero exit. To keep that gate honest, this
runner now collects the results of every test module, prints a summary
table, and exits with ``1`` if any module returned ``False``.
"""

__all__ = []

import sys

from helao.core.tests.unit_test_sample_models import sample_model_unit_test
from helao.core.tests.unit_test_action_experiment_sequence import (
    action_experiment_sequence_unit_test,
)
from helao.core.tests.unit_test_config_loader import config_loader_unit_test
from helao.core.tests.unit_test_config_validation import config_validation_unit_test
from helao.core.tests.unit_test_config_seam import config_seam_unit_test
from helao.core.tests.unit_test_logging import logging_unit_test
from helao.core.tests.unit_test_artifact_generation import (
    artifact_generation_unit_test,
)
from helao.core.tests.unit_test_dispatcher import dispatcher_unit_test
from helao.core.tests.unit_test_base_api import base_api_unit_test
from helao.core.tests.unit_test_orch_status import orch_status_unit_test
from helao.core.tests.unit_test_helaodict import helaodict_unit_test
from helao.core.tests.unit_test_version import version_unit_test
from helao.core.tests.unit_test_error_codes import error_codes_unit_test
from helao.core.tests.unit_test_extra_models import extra_models_unit_test
from helao.core.tests.unit_test_helao_driver import helao_driver_unit_test
from helao.core.tests.unit_test_micro_orch import micro_orch_unit_test
from helao.core.tests.unit_test_sync_to_thread import sync_to_thread_unit_test
from helao.core.tests.unit_test_sync_process_recovery import (
    sync_process_recovery_unit_test,
)
from helao.core.tests.unit_test_estop_sync import estop_sync_unit_test
from helao.core.tests.unit_test_sample_status import sample_status_unit_test
from helao.core.tests.unit_test_sample_union import sample_union_unit_test
from helao.core.tests.unit_test_orch_monitor import orch_monitor_unit_test
from helao.deploy.test.tests.unit_test_oersim_params import oersim_params_unit_test


TESTS = [
    ("sample_models", sample_model_unit_test),
    ("action_experiment_sequence", action_experiment_sequence_unit_test),
    ("config_loader", config_loader_unit_test),
    ("config_validation", config_validation_unit_test),
    ("config_seam", config_seam_unit_test),
    ("logging", logging_unit_test),
    ("artifact_generation", artifact_generation_unit_test),
    ("dispatcher", dispatcher_unit_test),
    ("base_api", base_api_unit_test),
    ("orch_status", orch_status_unit_test),
    ("helaodict", helaodict_unit_test),
    ("version", version_unit_test),
    ("error_codes", error_codes_unit_test),
    ("extra_models", extra_models_unit_test),
    ("helao_driver", helao_driver_unit_test),
    ("micro_orch", micro_orch_unit_test),
    ("sync_to_thread", sync_to_thread_unit_test),
    ("sync_process_recovery", sync_process_recovery_unit_test),
    ("estop_sync", estop_sync_unit_test),
    ("sample_status", sample_status_unit_test),
    ("sample_union", sample_union_unit_test),
    ("orch_monitor", orch_monitor_unit_test),
    ("oersim_params", oersim_params_unit_test),
]


def main() -> int:
    """Run every registered unit test, print a summary, return overall status."""
    results = []
    for name, fn in TESTS:
        print(f"\n===== running {name} =====")
        try:
            ok = bool(fn())
        except Exception as exc:  # noqa: BLE001
            print(f"{name} crashed: {exc!r}")
            ok = False
        results.append((name, ok))
        print(f"{name}: {'PASS' if ok else 'FAIL'}")

    print("\n===== summary =====")
    for name, ok in results:
        print(f"  {name}: {'PASS' if ok else 'FAIL'}")
    overall_ok = all(ok for _, ok in results)
    print(f"overall: {'PASS' if overall_ok else 'FAIL'}")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
