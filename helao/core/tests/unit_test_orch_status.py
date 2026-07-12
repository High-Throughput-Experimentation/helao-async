"""Unit tests for the orchestrator status model surface.

The full :class:`Orch` runtime needs running peer servers, a writable
``root`` directory and a Bokeh app, so these tests focus on the data
models and helper methods that orchestrator code drives directly:

* :class:`EndpointModel` / :class:`ActionServerModel` — registering an
  active action, then having ``sort_status`` move it into the finished
  bucket once its status set contains :attr:`HloStatus.finished`.
* :class:`GlobalStatusModel` — :meth:`actions_idle`,
  :meth:`server_free`, :meth:`endpoint_free`, :meth:`update_global_with_acts`,
  :meth:`new_experiment` / :meth:`finish_experiment`, and the
  ``server@machine`` key-flattening in :meth:`as_json`.
* :class:`OrchStatus` / :class:`LoopStatus` / :class:`LoopIntent` enum
  membership and string round-tripping.
"""

__all__ = ["orch_status_unit_test"]

import sys
import traceback
from uuid import uuid4

from helao.core.models.hlostatus import HloStatus
from helao.core.models.machine import MachineModel
from helao.core.models.orchstatus import LoopIntent, LoopStatus, OrchStatus
from helao.core.models.server import (
    ActionServerModel,
    EndpointModel,
    GlobalStatusModel,
)
from helao.helpers.premodels import Action
from helao.core.tests._test_utils import TestReporter


def _make_action(server_key: str, orchestrator: MachineModel) -> Action:
    """Build a fresh active Action attached to ``orchestrator``."""
    a = Action(
        action_name="step",
        action_server=MachineModel(server_name=server_key, machine_name="h"),
        orchestrator=orchestrator,
    )
    a.init_act()
    return a


def orch_status_unit_test() -> bool:
    """Run all orchestrator status model assertions and report pass/fail."""
    reporter = TestReporter("orch_status")

    try:
        reporter.section("OrchStatus / LoopStatus / LoopIntent enums")
        reporter.check(
            "OrchStatus.idle round-trips through its string value",
            lambda: OrchStatus(OrchStatus.idle.value) is OrchStatus.idle,
        )
        reporter.check(
            "LoopStatus has stopped/started/estopped/error members",
            lambda: {
                LoopStatus.stopped,
                LoopStatus.started,
                LoopStatus.estopped,
                LoopStatus.error,
            }
            == set(LoopStatus),
        )
        reporter.check(
            "LoopIntent default is none",
            lambda: LoopIntent("none") is LoopIntent.none,
        )

        reporter.section("EndpointModel.sort_status moves finished actions")
        orch_mm = MachineModel(server_name="ORCH", machine_name="orch_host")
        act_active = _make_action("DRV", orch_mm)
        endpoint = EndpointModel(endpoint_name="step")
        endpoint.active_dict[act_active.action_uuid] = act_active
        endpoint.sort_status()
        reporter.check(
            "active action stays in active_dict before being marked finished",
            lambda: act_active.action_uuid in endpoint.active_dict,
        )

        act_active.append_action_status(HloStatus.finished)
        endpoint.sort_status()
        reporter.check(
            "finished action moved out of active_dict",
            lambda: act_active.action_uuid not in endpoint.active_dict,
        )
        reporter.check(
            "finished action lives in nonactive_dict[finished]",
            lambda: act_active.action_uuid
            in endpoint.nonactive_dict.get(HloStatus.finished, {}),
        )
        endpoint.clear_finished()
        reporter.check(
            "clear_finished resets nonactive_dict to an empty finished bucket",
            lambda: endpoint.nonactive_dict == {HloStatus.finished: {}},
        )

        reporter.section("ActionServerModel.get_fastapi_json selects endpoints")
        as_model = ActionServerModel(
            action_server=MachineModel(server_name="DRV", machine_name="h")
        )
        as_model.endpoints["step"] = EndpointModel(endpoint_name="step")
        as_model.endpoints["other"] = EndpointModel(endpoint_name="other")
        full = as_model.get_fastapi_json()
        reporter.check(
            "get_fastapi_json() with no filter includes every endpoint",
            lambda: set(full["endpoints"].keys()) == {"step", "other"},
        )
        single = as_model.get_fastapi_json(action_name="step")
        reporter.check(
            "get_fastapi_json('step') restricts to one endpoint",
            lambda: list(single["endpoints"].keys()) == ["step"],
        )

        reporter.section("GlobalStatusModel basics")
        gsm = GlobalStatusModel(orchestrator=orch_mm)
        reporter.check(
            "freshly built GlobalStatusModel reports actions_idle()",
            lambda: gsm.actions_idle() is True,
        )

        # Build a server snapshot with one active action and feed it in.
        new_act = _make_action("DRV", orch_mm)
        as_model2 = ActionServerModel(
            action_server=MachineModel(server_name="DRV", machine_name="h"),
            endpoints={
                "step": EndpointModel(
                    endpoint_name="step",
                    active_dict={new_act.action_uuid: new_act},
                )
            },
        )
        recent_nonactive = gsm.update_global_with_acts(as_model2)
        reporter.check(
            "update_global_with_acts: no actions transitioned to finished yet",
            lambda: recent_nonactive == [],
        )
        reporter.check(
            "active action shows up in GlobalStatusModel.active_dict",
            lambda: new_act.action_uuid in gsm.active_dict,
        )
        reporter.check(
            "endpoint_free is False while an action is active on that endpoint",
            lambda: gsm.endpoint_free(
                MachineModel(server_name="DRV", machine_name="h"), "step"
            )
            is False,
        )
        reporter.check(
            "server_free is False while the server has an active action",
            lambda: gsm.server_free(
                MachineModel(server_name="DRV", machine_name="h")
            )
            is False,
        )

        reporter.section("Experiment lifecycle counters")
        exp_uuid = uuid4()
        gsm.new_experiment(exp_uuid)
        reporter.check(
            "new_experiment seeds the dispatched-action counter at 0",
            lambda: gsm.counter_dispatched_actions[exp_uuid] == 0,
        )
        # Tag the action with the experiment, mark it finished, and let
        # the global model promote it through update_global_with_acts.
        new_act.experiment_uuid = exp_uuid
        new_act.append_action_status(HloStatus.finished)
        recent_nonactive = gsm.update_global_with_acts(as_model2)
        reporter.check(
            "update_global_with_acts reports the newly finished action",
            lambda: any(t[0] == new_act.action_uuid for t in recent_nonactive),
        )
        reporter.check(
            "active_dict drains once the action is finished",
            lambda: gsm.actions_idle() is True,
        )
        finished_acts = gsm.finish_experiment(exp_uuid)
        reporter.check(
            "finish_experiment returns the experiment's finished actions",
            lambda: any(a.action_uuid == new_act.action_uuid for a in finished_acts),
        )
        reporter.check(
            "finish_experiment clears the dispatched-action counter",
            lambda: exp_uuid not in gsm.counter_dispatched_actions,
        )

        reporter.section("GlobalStatusModel.as_json flattens server_dict keys")
        json_dict = gsm.as_json()
        reporter.check(
            "as_json renders server_dict keys as 'server@machine' strings",
            lambda: all(isinstance(k, str) and "@" in k
                       for k in json_dict["server_dict"].keys()),
        )

        return reporter.success()

    except Exception as exc:  # noqa: BLE001
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        print(repr(exc), tb)
        return False
