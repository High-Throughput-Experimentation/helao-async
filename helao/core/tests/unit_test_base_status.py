"""Unit tests for the ``StatusBroadcaster`` collaborator extracted from
``Base`` (CARDS P6, Stage S2): the status-WebSocket + broadcast cluster
(``send_statuspackage``/``send_nbstatuspackage``/``attach_client``/
``detach_client``/``_ws_relay``/``ws_status``/``ws_data``/``ws_live``/
``regular_status_task``/``log_status_task``/``detach_subscribers``/
``replace_status``).

``test_active_golden_master.py --check`` drives the non-blocking sender path
(via the new scenario 9) but never exercises the outbound WS relay, the
remote-subscriber registry, or ``replace_status`` directly -- those are
normally orchestrator/browser-driven. This module is the S2-specific
behavior-preservation gate for that surface.

Mirrors the ``Base.__new__`` bypass fixture used by
``test_active_golden_master.py`` and ``unit_test_base_live_buffer.py``: a bare
``Base`` built without ``Base.__init__`` (no FastAPI app, no disk I/O, no
NTP), populated only with the attributes ``StatusBroadcaster`` methods touch,
then ``_init_collaborators()`` is called so ``base.status_broadcaster`` exists
exactly as it would after the real ``__init__``.

Hermetic: the private dispatcher (network RPC) is monkeypatched in the
``base_status`` module namespace with a recording fake; a real
``MultisubscriberQueue`` is used so ``_ws_relay`` is checked against genuine
fan-out behavior; no disk I/O.
"""

__all__ = ["base_status_unit_test"]

import asyncio
import pickle
import traceback

import pyzstd

import helao.core.servers.base_status as base_status_module
from helao.core.error import ErrorCodes
from helao.core.models.hlostatus import HloStatus
from helao.core.models.machine import MachineModel
from helao.core.models.server import ActionServerModel
from helao.core.servers.base import Base
from helao.core.tests._test_utils import TestReporter
from helao.helpers.multisubscriber_queue import MultisubscriberQueue
from helao.helpers.premodels import Action

SERVER_NAME = "STATSRV"
MACHINE = "test-machine"


def _make_base(dispatch_calls: list) -> Base:
    """Build a bare ``Base`` with every attribute ``StatusBroadcaster`` touches."""
    base = Base.__new__(Base)
    base.server = MachineModel(
        server_name=SERVER_NAME, machine_name=MACHINE, hostname="127.0.0.1", port=8000
    )
    base.server_cfg = {"host": "127.0.0.1", "port": 8000}
    base.actionservermodel = ActionServerModel(action_server=base.server)
    base.actionservermodel.init_endpoints()
    base.status_q = MultisubscriberQueue()
    base.data_q = MultisubscriberQueue()
    base.live_q = MultisubscriberQueue()
    base.status_clients = set()
    base._init_collaborators()
    return base


class _FakeWebSocket:
    """Minimal WebSocket stand-in recording accept()/send_bytes() calls."""

    def __init__(self):
        self.client = ("127.0.0.1", 54321)
        self.accepted = False
        self.sent = []

    async def accept(self):
        self.accepted = True

    async def send_bytes(self, payload):
        self.sent.append(payload)


async def _ticks(n: int = 5):
    for _ in range(n):
        await asyncio.sleep(0)


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

    orig = base_status_module.async_private_dispatcher
    base_status_module.async_private_dispatcher = _fake_dispatch
    try:
        base = _make_base(calls)
        resp, ec = await base.send_statuspackage(
            "CLIENT", "10.0.0.1", 9100, action_name=None
        )
    finally:
        base_status_module.async_private_dispatcher = orig

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

    orig = base_status_module.async_private_dispatcher
    base_status_module.async_private_dispatcher = _fake_dispatch
    try:
        base = _make_base(calls)
        actionmodel = Action(action_name="nbtest").get_act()
        resp, ec = await base.send_nbstatuspackage(
            "CLIENT", "10.0.0.1", 9100, actionmodel
        )
    finally:
        base_status_module.async_private_dispatcher = orig

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

    orig = base_status_module.async_private_dispatcher
    base_status_module.async_private_dispatcher = _fake_dispatch
    try:
        base = _make_base(calls)
        combo = ("CLIENT", "10.0.0.1", 9100)

        empty_before = len(base.status_clients) == 0
        ok = await base.attach_client("CLIENT", "10.0.0.1", 9100)
        added = combo in base.status_clients and ok is True
        dispatched_initial = len(calls) >= 1  # initial snapshot pushed

        base.detach_client("CLIENT", "10.0.0.1", 9100)
        removed = combo not in base.status_clients

        # detaching a non-subscriber is a harmless no-op
        base.detach_client("NOSUCH", "0.0.0.0", 1)
        noop_ok = combo not in base.status_clients
    finally:
        base_status_module.async_private_dispatcher = orig

    return empty_before and added and dispatched_initial and removed and noop_ok


# ---------------------------------------------------------------------------
# replace_status (guarded status-list mutation)
# ---------------------------------------------------------------------------


def _check_replace_status() -> bool:
    base = _make_base([])
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
# _ws_relay (real fan-out relay over a MultisubscriberQueue)
# ---------------------------------------------------------------------------


async def _check_ws_relay() -> bool:
    base = _make_base([])
    ws = _FakeWebSocket()
    q = MultisubscriberQueue()

    # use_as_dict=False -> raw message is pickled+compressed and sent as bytes
    task = asyncio.create_task(
        base.status_broadcaster._ws_relay(ws, q, "test", use_as_dict=False)
    )
    # let the relay accept and register its subscriber queue before publishing
    await _ticks()
    accepted_ok = ws.accepted is True and len(q.subscribers) == 1

    message = {"hello": "world", "n": 7}
    await q.put(message)
    await _ticks()
    await q.put(StopAsyncIteration)  # end the relay's async-for
    await task

    relayed_ok = (
        len(ws.sent) == 1 and pickle.loads(pyzstd.decompress(ws.sent[0])) == message
    )
    # subscriber is removed only on error; normal StopAsyncIteration exit leaves
    # the queue_context to clean up -> no lingering subscribers either way
    return accepted_ok and relayed_ok


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------


async def _run_checks() -> dict:
    return {
        "send_statuspackage": await _check_send_statuspackage(),
        "send_nbstatuspackage": await _check_send_nbstatuspackage(),
        "attach_detach": await _check_attach_detach(),
        "replace_status": _check_replace_status(),
        "ws_relay": await _check_ws_relay(),
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

    reporter.section("_ws_relay")
    reporter.check(
        "_ws_relay accepts the socket, subscribes to the queue, and relays a "
        "put message as a zstd-compressed pickle over send_bytes",
        lambda: res["ws_relay"],
    )

    return reporter.success()


if __name__ == "__main__":
    import sys

    sys.exit(0 if base_status_unit_test() else 1)
