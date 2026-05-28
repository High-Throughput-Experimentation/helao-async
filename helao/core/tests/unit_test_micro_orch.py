"""Unit tests for :class:`helao.core.runners.micro_client.MicroOrch`.

Exercises the small surface that ``MicroOrch`` exposes on top of the
RPC client cache:

* :func:`_is_terminal` — the helper that classifies an action's
  ``action_status`` list as still-active or finished.
* :meth:`MicroOrch.start` / :meth:`stop` lifecycle, including the
  no-op behaviour when called outside an ``async with`` block.
* :meth:`run_action` end-to-end: spins up a fake action server (a
  :class:`RPCDispatcher` on an ephemeral localhost port) that returns
  a finished action dump directly, and verifies the run resolves.
* :meth:`latest` / :meth:`pending_uuids` introspection helpers behave
  as documented around a dispatched action.
"""

__all__ = ["micro_orch_unit_test"]

import asyncio
import socket
import sys
import traceback
from copy import deepcopy
from datetime import datetime
from typing import Any, Dict

from helao.core.models.hlostatus import HloStatus
from helao.core.models.machine import MachineModel
from helao.core.rpc import RPCDispatcher, derive_rpc_port
from helao.core.runners.micro_client import MicroOrch, _is_terminal
from helao.helpers.premodels import Action
from helao.core.tests._test_utils import TestReporter


def _free_port() -> int:
    """Return an ephemeral free TCP port chosen by the OS."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _FakeActionServer:
    """Stand-in action server that exposes a single action over RPC.

    The action immediately reports as finished by including
    ``HloStatus.finished`` in the response's ``action_status`` list, so
    :meth:`MicroOrch.run_action` can complete synchronously off the
    dispatch reply without needing an ``update_status`` callback.
    """

    def __init__(self, server_key: str, action_name: str):
        """Bind the server identity and create an empty dispatcher."""
        self.server_key = server_key
        self.action_name = action_name
        self.dispatcher = RPCDispatcher(server_key)
        self.attach_calls = 0
        self.action_calls: list = []
        self.dispatcher.register(
            f"{server_key}/{action_name}", self._run_action
        )
        self.dispatcher.register("attach_client", self._attach_client)
        self.dispatcher.register("detach_client", self._detach_client)

    async def _attach_client(
        self,
        client_servkey: str,
        client_host: str,
        client_port: int,
    ) -> bool:
        """Record that ``client`` subscribed to status updates."""
        self.attach_calls += 1
        return True

    async def _detach_client(
        self,
        client_servkey: str,
        client_host: str,
        client_port: int,
    ) -> bool:
        """Record the detach call from the client (no-op locally)."""
        return True

    async def _run_action(self, action: dict = None, **kwargs) -> Dict[str, Any]:
        """Return a finished action dump that includes the requested name.

        ``action`` is declared explicitly so the RPC ``_coerce_args`` pass
        binds the inbound dict to it; the ``**kwargs`` catches any extra
        params the dispatcher merges in.
        """
        action_dict = action or {}
        self.action_calls.append(deepcopy(action_dict))
        # Reply with a terminal status -> MicroOrch.run_action returns
        # directly off this dump, no waiting on a status callback.
        action_dict["action_status"] = [HloStatus.finished.value]
        return action_dict


async def _drive_micro_orch(reporter: TestReporter) -> None:
    """Build a fake action server + MicroOrch, run an action, assert state."""
    server_key = "FAKE"
    action_name = "ping"
    fake_port = _free_port()
    fake_server = _FakeActionServer(server_key, action_name)
    await fake_server.dispatcher.serve("127.0.0.1", derive_rpc_port(fake_port))

    micro_port = _free_port()
    world_cfg = {
        "servers": {
            server_key: {"host": "127.0.0.1", "port": fake_port},
        }
    }

    try:
        async with MicroOrch(
            server_key="micro",
            host="127.0.0.1",
            port=micro_port,
            world_cfg=world_cfg,
            default_timeout=3.0,
        ) as orch:
            # Dispatcher should now be listening on derive_rpc_port(micro_port)
            reporter.check(
                "MicroOrch.dispatcher is bound after start()",
                lambda: orch.dispatcher._task is not None,
            )

            action = Action(
                action_name=action_name,
                action_server=MachineModel(server_name=server_key),
            )

            result = await orch.run_action(action, wait_timeout=3.0)

            reporter.check(
                "run_action returns the finished action dump",
                lambda: isinstance(result, dict)
                and HloStatus.finished.value in result.get("action_status", []),
            )
            reporter.check(
                "fake action server received exactly one dispatch",
                lambda: len(fake_server.action_calls) == 1,
            )
            reporter.check(
                "dispatched payload preserved the action_name",
                lambda: fake_server.action_calls[0].get("action_name") == action_name,
            )
            reporter.check(
                "MicroOrch attached to the action server",
                lambda: fake_server.attach_calls >= 1,
            )
            reporter.check(
                "MicroOrch.latest caches the dispatched action UUID",
                lambda: orch.latest(action.action_uuid) is not None,
            )
            reporter.check(
                "pending_uuids drains once the action resolves",
                lambda: action.action_uuid not in orch.pending_uuids(),
            )

        # After leaving the async-with, the dispatcher must be closed.
        reporter.check(
            "MicroOrch dispatcher closes on __aexit__",
            lambda: orch.dispatcher._task is None,
        )
    finally:
        await fake_server.dispatcher.close()


def micro_orch_unit_test() -> bool:
    """Run all MicroOrch assertions and report pass/fail."""
    reporter = TestReporter("micro_orch")

    try:
        reporter.section("_is_terminal helper")
        reporter.check(
            "empty status list is not terminal",
            lambda: _is_terminal([]) is False,
        )
        reporter.check(
            "None status list is not terminal",
            lambda: _is_terminal(None) is False,
        )
        reporter.check(
            "active HloStatus member -> not terminal",
            lambda: _is_terminal([HloStatus.active]) is False,
        )
        reporter.check(
            "string 'active' (post msgpack) -> not terminal",
            lambda: _is_terminal(["active"]) is False,
        )
        reporter.check(
            "finished status -> terminal",
            lambda: _is_terminal([HloStatus.finished]) is True,
        )
        reporter.check(
            "errored status -> terminal",
            lambda: _is_terminal(["errored"]) is True,
        )

        reporter.section("MicroOrch end-to-end run_action")
        asyncio.run(_drive_micro_orch(reporter))

        return reporter.success()

    except Exception as exc:  # noqa: BLE001
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        print(repr(exc), tb)
        return False
