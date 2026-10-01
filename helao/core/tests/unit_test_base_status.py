"""Unit tests for ``ActionHost``'s status-broadcast surface
(``send_statuspackage``/``send_nbstatuspackage``/``attach_client``/
``detach_client``/``replace_status``).

The action golden master drives the non-blocking sender path but never the
remote-subscriber registry or ``replace_status`` directly -- those are
normally orchestrator-driven. This module is the gate for that surface.
Ported from the legacy ``Base``/``StatusBroadcaster`` fixture by B7b; the
legacy ``_ws_relay`` check went with the engine, because the native WS
encoding is pinned by ``harness/tests/test_ws_frames.py``.

A bare ``ActionHost`` built with ``__new__`` (no FastAPI app, no disk I/O, no
NTP), populated only with the attributes these methods touch.

Hermetic: the private dispatcher (network RPC) is monkeypatched in the
``action_host`` module namespace, which binds it at import, with a recording
fake; no disk I/O.
"""

__all__ = ["base_status_unit_test"]

import asyncio
import traceback

import helao.hexagon.app.action_host as action_host_module
from helao.core.error import ErrorCodes
from helao.core.models.hlostatus import HloStatus
from helao.core.models.machine import MachineModel
from helao.core.models.server import ActionServerModel
from helao.core.tests._test_utils import TestReporter
from helao.helpers.premodels import Action
from helao.hexagon.app.action_host import ActionHost

SERVER_NAME = "STATSRV"
MACHINE = "test-machine"


def _make_base() -> ActionHost:
    """Build a bare ``ActionHost`` with every attribute the status methods touch."""
    base = ActionHost.__new__(ActionHost)
    base.server = MachineModel(
        server_name=SERVER_NAME, machine_name=MACHINE, hostname="127.0.0.1", port=8000
    )
    base.server_cfg = {"host": "127.0.0.1", "port": 8000}
    base.actionservermodel = ActionServerModel(action_server=base.server)
    base.actionservermodel.init_endpoints()
    base.status_clients = set()
    return base


class _PatchDispatcher:
    """Swap ``action_host.async_private_dispatcher`` for *fake* inside the block."""

    def __init__(self, fake):
        self._fake = fake

    def __enter__(self):
        self._orig = action_host_module.async_private_dispatcher
        action_host_module.async_private_dispatcher = self._fake
        return self

    def __exit__(self, *exc):
        action_host_module.async_private_dispatcher = self._orig
        return False


# ---------------------------------------------------------------------------
# send_statuspackage / send_nbstatuspackage
# ---------------------------------------------------------------------------


async def _check_send_statuspackage() -> bool:
    calls: list = []

    async def _fake_dispatch(
        server_key, host, port, private_action, params_dict=None, json_dict=None, **kw
    ):
        calls.append(
            {
                "server_key": server_key,
                "host": host,
                "port": port,
                "private_action": private_action,
                "params_dict": params_dict,
                "json_dict": json_dict,
            }
        )
        return {"ok": True}, ErrorCodes.none

    with _PatchDispatcher(_fake_dispatch):
        base = _make_base()
        resp, ec = await base.send_statuspackage(
            "CLIENT", "10.0.0.1", 9100, action_name=None
        )

    call = calls[-1]
    return (
        resp == {"ok": True}
        and ec == ErrorCodes.none
        and call["server_key"] == "CLIENT"
        and call["host"] == "10.0.0.1"
        and call["port"] == 9100
        and call["private_action"] == "update_status"
        # action_name None -> regular_task true
        and call["params_dict"] == {"regular_task": "true"}
        and "actionservermodel" in call["json_dict"]
    )


async def _check_send_nbstatuspackage() -> bool:
    calls: list = []

    async def _fake_dispatch(
        server_key, host, port, private_action, params_dict=None, json_dict=None, **kw
    ):
        calls.append(
            {
                "private_action": private_action,
                "params_dict": params_dict,
                "json_dict": json_dict,
            }
        )
        return {"success": True}, ErrorCodes.none

    with _PatchDispatcher(_fake_dispatch):
        base = _make_base()
        actionmodel = Action(action_name="nbtest").get_act()
        resp, ec = await base.send_nbstatuspackage(
            "CLIENT", "10.0.0.1", 9100, actionmodel
        )

    call = calls[-1]
    return (
        resp == {"success": True}
        and ec == ErrorCodes.none
        and call["private_action"] == "update_nonblocking"
        # server host/port come from base.server_cfg
        and call["params_dict"] == {"server_host": "127.0.0.1", "server_port": 8000}
        and "actionmodel" in call["json_dict"]
    )


# ---------------------------------------------------------------------------
# attach_client / detach_client (status_clients mutation)
# ---------------------------------------------------------------------------


async def _check_attach_detach() -> bool:
    calls: list = []

    async def _fake_dispatch(*a, **kw):
        calls.append(kw)
        return {"ok": True}, ErrorCodes.none

    with _PatchDispatcher(_fake_dispatch):
        base = _make_base()
        combo = ("CLIENT", "10.0.0.1", 9100)

        empty_before = len(base.status_clients) == 0
        ok = await base.attach_client("CLIENT", "10.0.0.1", 9100)
        added = combo in base.status_clients and ok is True
        dispatched_initial = len(calls) >= 1  # initial snapshot pushed

        await base.detach_client("CLIENT", "10.0.0.1", 9100)
        removed = combo not in base.status_clients

        # detaching a non-subscriber is a harmless no-op
        await base.detach_client("NOSUCH", "0.0.0.0", 1)
        noop_ok = combo not in base.status_clients

    return empty_before and added and dispatched_initial and removed and noop_ok


# ---------------------------------------------------------------------------
# replace_status (guarded status-list mutation)
# ---------------------------------------------------------------------------


def _check_replace_status() -> bool:
    base = _make_base()
    # present -> swapped in place
    status_list = [HloStatus.active]
    base.replace_status(status_list, HloStatus.active, HloStatus.finished)
    swapped = status_list == [HloStatus.finished]

    # absent old_status -> appended
    status_list2 = [HloStatus.active]
    base.replace_status(status_list2, HloStatus.errored, HloStatus.estopped)
    appended = HloStatus.estopped in status_list2

    return swapped and appended


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------


async def _run_checks() -> dict:
    return {
        "send_statuspackage": await _check_send_statuspackage(),
        "send_nbstatuspackage": await _check_send_nbstatuspackage(),
        "attach_detach": await _check_attach_detach(),
        "replace_status": _check_replace_status(),
    }


def base_status_unit_test() -> bool:
    reporter = TestReporter("base_status")
    try:
        res = asyncio.run(_run_checks())
    except Exception as exc:  # noqa: BLE001
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        print(repr(exc), tb)
        return False

    reporter.section("send_statuspackage / send_nbstatuspackage")
    reporter.check(
        "send_statuspackage builds the actionservermodel json_dict and dispatches "
        "'update_status' with regular_task=true to the target client",
        lambda: res["send_statuspackage"],
    )
    reporter.check(
        "send_nbstatuspackage builds the actionmodel json_dict + server host/port "
        "params and dispatches 'update_nonblocking'",
        lambda: res["send_nbstatuspackage"],
    )

    reporter.section("attach_client / detach_client")
    reporter.check(
        "attach_client adds the combo key to status_clients and pushes an initial "
        "snapshot; detach_client removes it and no-ops on a missing key",
        lambda: res["attach_detach"],
    )

    reporter.section("replace_status")
    reporter.check(
        "replace_status swaps an existing status in place and appends a missing one",
        lambda: res["replace_status"],
    )

    return reporter.success()


if __name__ == "__main__":
    import sys

    sys.exit(0 if base_status_unit_test() else 1)
