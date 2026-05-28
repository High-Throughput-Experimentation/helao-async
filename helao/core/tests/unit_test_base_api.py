"""Unit tests for ``helao.core.servers.base_api`` helper functions.

The full :class:`Base` / :class:`BaseAPI` runtime needs a real world
config, a writable root directory and a running FastAPI app, so these
tests focus on the pure helpers exposed by the module that orchestrate
the per-request ``Action`` context:

* :func:`_build_action_from_kwargs` — recovering an ``Action`` from
  FastAPI-resolved kwargs, including the "no action present" fallback and
  the kwarg-into-action_params merge.
* :func:`wrap_action_endpoint` — both the sync and async wrappers and
  the surrounding ``ACTION_CTX`` ``ContextVar`` plumbing.
* :data:`ACTION_PARAM_KEYS` — the canonical envelope-key list used by the
  action-queuing middleware to split envelope vs. action params.
* :class:`ActiveParams` — round-trip via ``as_dict``.
"""

__all__ = ["base_api_unit_test"]

import asyncio
import sys
import traceback

from helao.core.models.machine import MachineModel
from helao.core.models.file import FileConnParams
from helao.helpers.active_params import ActiveParams
from helao.helpers.premodels import Action
from helao.core.servers.base_api import (
    ACTION_CTX,
    ACTION_PARAM_KEYS,
    ActionInvocation,
    _build_action_from_kwargs,
    wrap_action_endpoint,
)
from helao.core.tests._test_utils import TestReporter


def base_api_unit_test() -> bool:
    """Run all base_api helper assertions and report pass/fail."""
    reporter = TestReporter("base_api")

    try:
        reporter.section("ACTION_PARAM_KEYS contains the envelope keys")
        for needed in (
            "start_condition",
            "from_global_act_params",
            "to_global_params",
            "manual_action",
            "process_finish",
            "save_act",
            "save_data",
            "campaign_uuid",
        ):
            reporter.check(
                f"ACTION_PARAM_KEYS includes '{needed}'",
                (lambda needed=needed: needed in ACTION_PARAM_KEYS),
            )

        reporter.section("_build_action_from_kwargs picks the Action kwarg")
        provided = Action(action_name="ping")
        kwargs = {
            "action": provided,
            "x": 1,
            "y": "two",
            "ratio": 0.5,
        }
        rebuilt = _build_action_from_kwargs(kwargs)
        reporter.check(
            "_build_action_from_kwargs returns the action that was passed in",
            lambda: rebuilt is provided,
        )
        reporter.check(
            "extra kwargs get folded into action.action_params",
            lambda: rebuilt.action_params.get("x") == 1
            and rebuilt.action_params.get("y") == "two"
            and rebuilt.action_params.get("ratio") == 0.5,
        )

        reporter.section("_build_action_from_kwargs preserves existing action_params")
        prepared = Action(
            action_name="ping",
            action_params={"x": 99},  # caller already set x; must not be overwritten
        )
        merged = _build_action_from_kwargs({"action": prepared, "x": 1, "y": "two"})
        reporter.check(
            "pre-existing action_params keys are not clobbered by kwargs",
            lambda: merged.action_params["x"] == 99,
        )
        reporter.check(
            "new kwargs are still merged when not already present",
            lambda: merged.action_params.get("y") == "two",
        )

        reporter.section("_build_action_from_kwargs without Action falls back")
        fallback = _build_action_from_kwargs({"x": 1, "y": "two"})
        reporter.check(
            "missing Action -> a blank Action instance is returned",
            lambda: isinstance(fallback, Action),
        )
        reporter.check(
            "blank-fallback Action still absorbs extra kwargs",
            lambda: fallback.action_params.get("x") == 1,
        )

        reporter.section("wrap_action_endpoint (sync) sets ACTION_CTX during call")
        captured = {}

        def sync_endpoint(action: Action, payload: str = "p"):
            captured["ctx"] = ACTION_CTX.get()
            return action.action_name, payload

        wrapped = wrap_action_endpoint(sync_endpoint)
        # The wrapper preserves the signature so FastAPI can introspect it.
        import inspect

        reporter.check(
            "wrap_action_endpoint preserves the wrapped signature",
            lambda: list(inspect.signature(wrapped).parameters.keys())
            == ["action", "payload"],
        )

        result = wrapped(action=Action(action_name="sync_call"), payload="hello")
        reporter.check(
            "wrapped sync endpoint returns its native result",
            lambda: result == ("sync_call", "hello"),
        )
        reporter.check(
            "ACTION_CTX was populated inside the call",
            lambda: isinstance(captured["ctx"], ActionInvocation)
            and captured["ctx"].action.action_name == "sync_call",
        )
        reporter.check(
            "ACTION_CTX is reset after the call returns",
            lambda: ACTION_CTX.get() is None,
        )

        reporter.section("wrap_action_endpoint (async) also sets ACTION_CTX")
        captured_async = {}

        async def async_endpoint(action: Action, value: int = 0):
            captured_async["ctx"] = ACTION_CTX.get()
            return value * 2

        async_wrapped = wrap_action_endpoint(async_endpoint)
        out = asyncio.run(
            async_wrapped(action=Action(action_name="async_call"), value=3)
        )
        reporter.check(
            "wrapped async endpoint returns its native awaited result",
            lambda: out == 6,
        )
        reporter.check(
            "async ACTION_CTX was populated inside the await",
            lambda: isinstance(captured_async["ctx"], ActionInvocation)
            and captured_async["ctx"].action.action_name == "async_call",
        )
        reporter.check(
            "async ACTION_CTX reset after the call returns",
            lambda: ACTION_CTX.get() is None,
        )

        reporter.section("ActiveParams round-trip")
        action = Action(action_name="do_stuff", action_server=MachineModel(server_name="S"))
        action.init_act()
        ap = ActiveParams(
            action=action,
            file_conn_params_dict={action.action_uuid: FileConnParams(
                file_conn_key=action.action_uuid,
                json_data_keys=["t_s", "v"],
            )},
        )
        reporter.check(
            "ActiveParams.action is the original Action",
            lambda: ap.action is action,
        )
        ap_dict = ap.as_dict()
        reporter.check(
            "ActiveParams.as_dict round-trips file_conn_params_dict",
            lambda: list(ap_dict.get("file_conn_params_dict", {}).values())[0][
                "json_data_keys"
            ]
            == ["t_s", "v"],
        )

        return reporter.success()

    except Exception as exc:  # noqa: BLE001
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        print(repr(exc), tb)
        return False
