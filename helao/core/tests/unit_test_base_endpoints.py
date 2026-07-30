"""Unit tests for the ``EndpointManager`` and ``ActionQueueDispatcher``
collaborators extracted from ``Base`` (CARDS P6, Stage S4): dynamic-endpoint
registration/status monitoring (``dyn_endpoints_init``/``endpoint_queues_init``/
``init_endpoint_status``/``get_endpoint_urls``) and queued-action dispatch
(``_dispatch_queued_action``/``process_unified_queue``/``process_endpoint_queue``).

``test_active_golden_master.py --check`` does not exercise either cluster --
they are server-setup and queue-dispatch machinery, not ``Active`` output --
so this module is the S4-specific behavior-preservation gate.

Mirrors the ``Base.__new__`` bypass fixture used by
``test_active_golden_master.py`` and the S1-S3 unit tests: a bare ``Base``
built without ``Base.__init__``, populated only with the attributes each
collaborator's methods touch, then ``_init_collaborators()`` is called so
``base.endpoint_mgr``/``base.action_queue`` exist exactly as they would after
the real ``__init__``.

Hermetic: no network, no disk I/O. ``async_action_dispatcher`` is
monkeypatched in the ``base_action_queue`` module namespace with a recording
fake (mirrors the ``async_private_dispatcher`` monkeypatch pattern in
``unit_test_base_status.py``); routes/app are minimal stand-ins.
"""

__all__ = ["base_endpoints_unit_test"]

import asyncio
import traceback
from types import SimpleNamespace

import helao.core.servers.base_action_queue as base_action_queue_module
from helao.core.models.action import ActionModel
from helao.core.models.action_start_condition import ActionStartCondition as ASC
from helao.core.models.machine import MachineModel
from helao.core.models.server import ActionServerModel
from helao.core.servers.base import Base
from helao.core.tests._test_utils import TestReporter
from helao.helpers.premodels import Action
from helao.helpers.zdeque import zdeque

SERVER_NAME = "ENDPSRV"
MACHINE = "test-machine"


class _FakeRoute:
    """Minimal stand-in for a FastAPI route: only ``path``/``name`` attributes.

    Deliberately has no ``dependant`` attribute so ``get_endpoint_urls``
    exercises its ``params = []`` branch -- exact route/dependant introspection
    is FastAPI's concern, not this collaborator's.
    """

    def __init__(self, path: str, name: str):
        self.path = path
        self.name = name


def _make_base() -> Base:
    """Build a bare ``Base`` with every attribute the two S4 collaborators touch."""
    base = Base.__new__(Base)
    base.server = MachineModel(
        server_name=SERVER_NAME, machine_name=MACHINE, hostname="127.0.0.1", port=8000
    )
    base.actionservermodel = ActionServerModel(action_server=base.server)
    base.actionservermodel.init_endpoints()
    base.app = SimpleNamespace(
        routes=[
            _FakeRoute(f"/{SERVER_NAME}/act_one", "act_one"),
            _FakeRoute(f"/{SERVER_NAME}/act_two", "act_two"),
            _FakeRoute("/other/unrelated", "unrelated"),
        ]
    )
    base.dyn_endpoints = None
    base.fast_urls = []
    base.endpoint_queues = {}
    base.local_action_queue = zdeque([])
    base.world_cfg = {}
    base._init_collaborators()
    return base


# ---------------------------------------------------------------------------
# get_endpoint_urls / endpoint_queues_init / init_endpoint_status / dyn_endpoints_init
# ---------------------------------------------------------------------------


def _check_get_endpoint_urls() -> bool:
    base = _make_base()
    urls = base.get_endpoint_urls()
    by_name = {u["name"]: u for u in urls}
    return (
        len(urls) == 3
        and by_name["act_one"]["path"] == f"/{SERVER_NAME}/act_one"
        and by_name["act_one"]["params"] == []
        and by_name["act_two"]["path"] == f"/{SERVER_NAME}/act_two"
        and by_name["unrelated"]["path"] == "/other/unrelated"
    )


def _check_endpoint_queues_init() -> bool:
    base = _make_base()
    base.fast_urls = base.get_endpoint_urls()
    base.endpoint_queues_init()
    return set(base.endpoint_queues.keys()) == {"act_one", "act_two"} and all(
        isinstance(q, zdeque) and len(q) == 0 for q in base.endpoint_queues.values()
    )


async def _check_init_endpoint_status() -> bool:
    base = _make_base()
    await base.init_endpoint_status(dyn_endpoints=None)
    endpoints_ok = (
        "act_one" in base.actionservermodel.endpoints
        and "act_two" in base.actionservermodel.endpoints
        and "unrelated" not in base.actionservermodel.endpoints
    )
    urls_ok = base.fast_urls == base.endpoint_mgr.get_endpoint_urls()
    queues_ok = set(base.endpoint_queues.keys()) == {"act_one", "act_two"}
    return endpoints_ok and urls_ok and queues_ok


async def _check_init_endpoint_status_dyn_endpoints_called() -> bool:
    base = _make_base()
    calls = []

    async def _fake_dyn_endpoints(app):
        calls.append(app)

    await base.init_endpoint_status(dyn_endpoints=_fake_dyn_endpoints)
    return calls == [base.app]


async def _check_dyn_endpoints_init() -> bool:
    """``dyn_endpoints_init`` fires ``init_endpoint_status`` via ``asyncio.gather``."""
    base = _make_base()
    base.dyn_endpoints_init()
    # asyncio.gather schedules a task; give the loop a tick to run it.
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    return set(base.endpoint_queues.keys()) == {"act_one", "act_two"}


# ---------------------------------------------------------------------------
# ActionQueueDispatcher: _dispatch_queued_action / process_unified_queue /
# process_endpoint_queue
# ---------------------------------------------------------------------------


async def _check_process_endpoint_queue_success() -> bool:
    base = _make_base()
    base.endpoint_queues["act_one"] = zdeque([])
    action = Action(action_name="act_one")
    base.endpoint_queues["act_one"].append((action, {"p": 1}))

    calls = []

    async def _fake_dispatch(world_cfg, qact, qpars):
        calls.append((world_cfg, qact, qpars))
        return {"ok": True}, None

    orig = base_action_queue_module.async_action_dispatcher
    base_action_queue_module.async_action_dispatcher = _fake_dispatch
    try:
        status_msg = ActionModel(action_name="act_one")
        await base.process_endpoint_queue(status_msg)
    finally:
        base_action_queue_module.async_action_dispatcher = orig

    if len(calls) != 1:
        return False
    world_cfg, qact, qpars = calls[0]
    return (
        world_cfg is base.world_cfg
        and qact.action_name == "act_one"
        and qact.start_condition == ASC.no_wait
        and qact.action_params.get("queued_launch") is True
        and qpars == {"p": 1}
        and len(base.endpoint_queues["act_one"]) == 0
    )


async def _check_process_endpoint_queue_requeues_on_failure() -> bool:
    base = _make_base()
    base.endpoint_queues["act_two"] = zdeque([])
    action = Action(action_name="act_two")
    base.endpoint_queues["act_two"].append((action, {}))

    async def _fake_dispatch(world_cfg, qact, qpars):
        raise RuntimeError("dispatch boom")

    orig = base_action_queue_module.async_action_dispatcher
    base_action_queue_module.async_action_dispatcher = _fake_dispatch
    try:
        status_msg = ActionModel(action_name="act_two")
        await base.process_endpoint_queue(status_msg)
    finally:
        base_action_queue_module.async_action_dispatcher = orig

    queue = base.endpoint_queues["act_two"]
    return len(queue) == 1 and queue[0][0].action_name == "act_two"


async def _check_process_unified_queue() -> bool:
    base = _make_base()
    action = Action(action_name="unified_act")
    base.local_action_queue.append((action, {}))

    calls = []

    async def _fake_dispatch(world_cfg, qact, qpars):
        calls.append(qact.action_name)
        return {"ok": True}, None

    orig = base_action_queue_module.async_action_dispatcher
    base_action_queue_module.async_action_dispatcher = _fake_dispatch
    try:
        await base.process_unified_queue()
    finally:
        base_action_queue_module.async_action_dispatcher = orig

    return calls == ["unified_act"] and len(base.local_action_queue) == 0


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------


async def _run_checks() -> dict:
    return {
        "get_endpoint_urls": _check_get_endpoint_urls(),
        "endpoint_queues_init": _check_endpoint_queues_init(),
        "init_endpoint_status": await _check_init_endpoint_status(),
        "init_endpoint_status_dyn_endpoints_called": await _check_init_endpoint_status_dyn_endpoints_called(),
        "dyn_endpoints_init": await _check_dyn_endpoints_init(),
        "process_endpoint_queue_success": await _check_process_endpoint_queue_success(),
        "process_endpoint_queue_requeues_on_failure": await _check_process_endpoint_queue_requeues_on_failure(),
        "process_unified_queue": await _check_process_unified_queue(),
    }


def base_endpoints_unit_test() -> bool:
    reporter = TestReporter("base_endpoints")
    try:
        res = asyncio.run(_run_checks())
    except Exception as exc:  # noqa: BLE001
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        print(repr(exc), tb)
        return False

    reporter.section("EndpointManager")
    reporter.check(
        "get_endpoint_urls returns path/name/params for every route",
        lambda: res["get_endpoint_urls"],
    )
    reporter.check(
        "endpoint_queues_init creates an empty zdeque per matching-prefix endpoint",
        lambda: res["endpoint_queues_init"],
    )
    reporter.check(
        "init_endpoint_status registers matching-prefix endpoints, sets fast_urls, "
        "and builds endpoint_queues",
        lambda: res["init_endpoint_status"],
    )
    reporter.check(
        "init_endpoint_status awaits the dyn_endpoints callback with the app",
        lambda: res["init_endpoint_status_dyn_endpoints_called"],
    )
    reporter.check(
        "dyn_endpoints_init schedules init_endpoint_status via asyncio.gather",
        lambda: res["dyn_endpoints_init"],
    )

    reporter.section("ActionQueueDispatcher")
    reporter.check(
        "process_endpoint_queue dispatches the queued action with no_wait + "
        "queued_launch and drains the queue",
        lambda: res["process_endpoint_queue_success"],
    )
    reporter.check(
        "process_endpoint_queue re-queues the action on dispatch failure",
        lambda: res["process_endpoint_queue_requeues_on_failure"],
    )
    reporter.check(
        "process_unified_queue dispatches from local_action_queue",
        lambda: res["process_unified_queue"],
    )

    return reporter.success()


if __name__ == "__main__":
    import sys

    sys.exit(0 if base_endpoints_unit_test() else 1)
