"""Regression test: hte samples_exp.orch_sub_wait expansion via framework orch.

Before the Wave 3.5 import migration, hte experiment/sequence libraries used the
LEGACY ``@experiment`` decorator (``helao.helpers.lib_decorators``). The framework
orchestrator calls ``exp_func(experiment, **params)`` passing a ``RunExperiment``
as the first positional argument. The legacy decorator does not strip that
positional for exp-free functions, so the ``RunExperiment`` binds to the first
real parameter (``wait_time_s``) while ``wait_time_s`` is also supplied as a
keyword from ``experiment_params`` — raising:

    TypeError: orch_sub_wait() got multiple values for argument 'wait_time_s'

After the migration (framework decorator applied) the RunExperiment is stripped
and published on ``EXPERIMENT_CTX``; the call resolves cleanly and returns a
non-empty action list containing the ORCH ``wait`` action.
"""

import pathlib
import sys

import pytest

# ---------------------------------------------------------------------------
# Ensure repo root is on sys.path (mirrors test_hte_vis_operator_import.py)
# ---------------------------------------------------------------------------
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ---------------------------------------------------------------------------
# Load CONFIG so experiment libs that reference CONFIG at import time resolve.
# ---------------------------------------------------------------------------
from helao.helpers.config_loader import read_config

read_config("power_supply_test")


# ---------------------------------------------------------------------------
# Regression test: orch_sub_wait must not raise "multiple values"
# ---------------------------------------------------------------------------

def test_orch_sub_wait_expansion_no_crash():
    """orch_sub_wait must expand cleanly and return a non-empty action list.

    Pre-fix this raises ``TypeError: orch_sub_wait() got multiple values for
    argument 'wait_time_s'``.  Post-fix the framework decorator strips the
    positional ``RunExperiment`` before the body runs, so the call succeeds.
    """
    import helao.deploy.hte.experiments.samples_exp as se
    from helao.framework.domain.run_models import RunExperiment
    from helao.framework.domain import expansion

    exp = RunExperiment(
        experiment_name="orch_sub_wait",
        experiment_params={"wait_time_s": 3},
    )

    # Must NOT raise; pre-fix this is the crash site.
    actions = expansion.unpack_experiment(
        exp,
        dict(exp.experiment_params),
        experiment_lib={"orch_sub_wait": se.orch_sub_wait},
    )

    assert isinstance(actions, list), "unpack_experiment must return a list"
    assert len(actions) > 0, "orch_sub_wait must produce at least one action"

    # Confirm the action targets the ORCH wait endpoint
    first = actions[0]
    action_server = getattr(first, "action_server", None)
    action_name = getattr(first, "action_name", None)
    assert action_name == "wait", (
        f"Expected first action to be 'wait', got {action_name!r}"
    )

    # Confirm the framework decorator was applied (experiment_version attribute set)
    assert se.orch_sub_wait.experiment_version == 2, (
        "Framework @experiment decorator must set experiment_version=2 on "
        "orch_sub_wait (matches @experiment(version=2) in samples_exp.py)"
    )
