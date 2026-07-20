"""Unit tests for inter-server communication helpers.

Drives the ZMQ-backed :class:`helao.core.rpc.RPCDispatcher` plus its
async and sync clients end-to-end on a localhost ephemeral port, then
covers HTTP fallback behaviour from :mod:`helao.helpers.dispatcher`:

* :func:`derive_rpc_port` arithmetic and :class:`ErrorCodes` round-trip.
* :func:`async_private_dispatcher` HTTP retries when no peer is up
  (verifies the function still returns a ``(None, error_code)`` tuple
  rather than raising).
* :func:`endpoints_available` URL classification: unreachable URLs are
  reported as unavailable with a sensible state string.
* :func:`RPCDispatcher.serve` + :class:`RPCClient` round-trip including
  pydantic model rehydration via ``_coerce_args``.
* :func:`async_action_dispatcher` end-to-end over the RPC fast path,
  driving a real ``wrap_action_endpoint``-wrapped handler (mirrors what
  ``server_api._rpc_startup`` registers for a ``tags=["action"]`` route) so
  ``ACTION_CTX``/``action_params`` are asserted to be populated server-side
  -- not the generic echo handlers used by ``_exercise_rpc``. Covers the
  regression where an action param literally named ``timeout`` (e.g.
  ANDOR/acquire's ``timeout: float = 5000``) collided with
  ``RPCClient.call``'s own ``timeout`` kwarg (fixed in 4d11afe3); plus a
  down-peer case proving the fallback still returns promptly.
"""

__all__ = ["dispatcher_unit_test"]

import asyncio
import socket
import time
import traceback

from helao.core.error import ErrorCodes
from helao.core.rpc import (
    RPCClient,
    RPCDispatcher,
    RPCError,
    RPCSyncClient,
    derive_rpc_port,
)
from helao.core.rpc.zmq_rpc import RPC_PORT_OFFSET
from helao.core.servers.base_api import ACTION_CTX, wrap_action_endpoint
from helao.helpers.dispatcher import (
    _query_safe,
    aclose_all_rpc_clients,
    async_action_dispatcher,
    async_private_dispatcher,
    close_all_sync_rpc_clients,
    endpoints_available,
)
from helao.helpers.premodels import Action
from helao.core.models.machine import MachineModel
from helao.core.tests._test_utils import TestReporter


def _free_port() -> int:
    """Return an ephemeral free TCP port chosen by the OS."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _exercise_rpc(reporter: TestReporter) -> None:
    """Bind an RPCDispatcher to an ephemeral port and probe it from both clients."""
    dispatcher = RPCDispatcher(server_key="rpc_unit")
    port = _free_port()
    endpoint = f"tcp://127.0.0.1:{port}"

    # Registered methods: plain echo, pydantic-model echo, and a raiser.
    def echo(message: str = "hi", count: int = 1) -> dict:
        return {"message": message, "count": count}

    async def aecho(message: str) -> str:
        return message[::-1]

    def needs_machine(machine: MachineModel) -> str:
        # _coerce_args should rebuild this MachineModel from the inbound dict
        return machine.disp_name()

    def boom() -> None:
        raise RuntimeError("boom")

    def echo_timeout(timeout: int = 0, message: str = "") -> dict:
        # A remote method whose parameter name shadows RPCClient.call's own
        # `timeout` control kwarg. It must be forwarded via `args=` without a
        # "got multiple values for keyword argument 'timeout'" collision
        # (regression: ANDOR/acquire has a `timeout` param).
        return {"timeout": timeout, "message": message}

    dispatcher.register("echo", echo)
    dispatcher.register("aecho", aecho)
    dispatcher.register("needs_machine", needs_machine)
    dispatcher.register("boom", boom)
    dispatcher.register("echo_timeout", echo_timeout)

    await dispatcher.serve("127.0.0.1", port)
    try:
        client = RPCClient(endpoint=endpoint, default_timeout=2.0)
        try:
            result = await client.call("echo", message="ping", count=2)
            reporter.check(
                "RPCClient round-trip preserves args",
                lambda: result == {"message": "ping", "count": 2},
            )

            areverse = await client.call("aecho", message="abcd")
            reporter.check(
                "RPCClient handles async-registered methods",
                lambda: areverse == "dcba",
            )

            disp = await client.call(
                "needs_machine", machine={"server_name": "S", "machine_name": "M"}
            )
            reporter.check(
                "RPCClient rehydrates pydantic args via _coerce_args",
                lambda: disp == "S@M",
            )

            # A forwarded param named `timeout` must not collide with the
            # control `timeout` kwarg: the control timeout (2.0s) governs the
            # wait, while args={"timeout": 999} is forwarded to the remote fn.
            shadow = await client.call(
                "echo_timeout",
                timeout=2.0,
                args={"timeout": 999, "message": "z"},
            )
            reporter.check(
                "RPCClient forwards a param named 'timeout' via args= "
                "without colliding with the control timeout",
                lambda: shadow == {"timeout": 999, "message": "z"},
            )

            # Expect RPCError when the handler raises
            try:
                await client.call("boom")
                raised = False
            except RPCError:
                raised = True
            reporter.check("RPCError raised when remote handler errors", lambda: raised)

            # Unknown method should also raise RPCError
            try:
                await client.call("not_there")
                raised_missing = False
            except RPCError:
                raised_missing = True
            reporter.check(
                "RPCError raised for unknown remote method",
                lambda: raised_missing,
            )
        finally:
            await client.close()

        # Sync client should reach the same dispatcher. Drive it from a
        # thread pool so the blocking REQ.poll() does not starve the
        # dispatcher's recv loop running on this event loop.
        def _drive_sync():
            sync = RPCSyncClient(endpoint=endpoint, default_timeout=5.0)
            try:
                echoed = sync.call("echo", message="sync", count=3)
                shadowed = sync.call(
                    "echo_timeout", timeout=5.0, args={"timeout": 42, "message": "s"}
                )
                return echoed, shadowed
            finally:
                sync.close()

        loop = asyncio.get_running_loop()
        sync_result, sync_shadow = await loop.run_in_executor(None, _drive_sync)
        reporter.check(
            "RPCSyncClient round-trip preserves args",
            lambda: sync_result == {"message": "sync", "count": 3},
        )
        reporter.check(
            "RPCSyncClient forwards a param named 'timeout' via args= "
            "without colliding with the control timeout",
            lambda: sync_shadow == {"timeout": 42, "message": "s"},
        )
    finally:
        await dispatcher.close()


def _free_http_port() -> int:
    """Return an HTTP port whose derived RPC port is free and <= 65535.

    Binds the *RPC* socket first (so we know it's free) then derives the
    HTTP port downward, mirroring how a real server's ``host``/``port``
    config entry relates to its co-located RPC ROUTER (mirrors
    ``server_api.HelaoFastAPI``'s ``derive_rpc_port(server_cfg["port"])``).
    A tiny TOCTOU window exists but is acceptable for a test fixture.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    rpc_port = s.getsockname()[1]
    s.close()
    http_port = rpc_port - RPC_PORT_OFFSET
    assert 1024 < http_port <= 65535, f"derived http_port {http_port} out of range"
    assert derive_rpc_port(http_port) <= 65535
    return http_port


async def _exercise_action_dispatcher_rpc(reporter: TestReporter) -> None:
    """Drive ``async_action_dispatcher`` end-to-end over the real RPC fast path.

    Registers a ``wrap_action_endpoint``-wrapped handler -- the exact
    callable ``server_api._rpc_startup`` mirrors into the co-located
    ``RPCDispatcher`` for a ``tags=["action"]`` route -- under
    ``f"{server_name}/{action_name}"`` on a real bound ``RPCDispatcher``, then
    dispatches a real :class:`Action` through :func:`async_action_dispatcher`
    exactly as the orchestrator does. Asserts:

    * The call succeeds via RPC alone -- no HTTP server is listening on the
      paired HTTP port at all, so any HTTP fallback would fail outright;
      ``ErrorCodes.none`` therefore proves the RPC leg (not a fallback)
      produced the result.
    * ``ACTION_CTX`` was populated with the REAL action (not a blank
      ``Action()``) and ``action.action_params`` reached the handler --
      the mechanism ``_build_action_from_kwargs`` implements.
    * An action param literally named ``timeout`` (mirroring ANDOR/acquire's
      ``timeout: float = 5000``) round-trips correctly instead of colliding
      with ``RPCClient.call``'s own ``timeout`` control kwarg (4d11afe3).
    """
    server_name = "ACTIONRPC"
    action_name = "acquire"
    captured: dict = {}

    async def acquire_like(
        external_trigger: bool = True,
        duration: float = 10.0,
        timeout: float = 5000,
    ) -> dict:
        ctx = ACTION_CTX.get()
        captured["ctx_is_none"] = ctx is None
        if ctx is not None:
            captured["action_params"] = dict(ctx.action.action_params)
        captured["external_trigger"] = external_trigger
        captured["duration"] = duration
        captured["timeout"] = timeout
        return {"ok": True}

    # Mirrors ActionAPIRoute.__init__: a tags=["action"] endpoint is wrapped
    # with wrap_action_endpoint before it is ever registered anywhere --
    # including into the RPC dispatcher's method table.
    wrapped = wrap_action_endpoint(acquire_like)

    dispatcher = RPCDispatcher(server_key=server_name)
    http_port = _free_http_port()
    rpc_port = derive_rpc_port(http_port)
    dispatcher.register(f"{server_name}/{action_name}", wrapped)
    await dispatcher.serve("127.0.0.1", rpc_port)
    try:
        world_cfg = {
            "servers": {
                server_name: {"host": "127.0.0.1", "port": http_port},
            }
        }
        action_params = {
            "external_trigger": False,
            "duration": 2.5,
            "timeout": 5000,  # shadows RPCClient.call(timeout=...) by name
        }
        action = Action(
            action_name=action_name,
            action_server=MachineModel(
                server_name=server_name, machine_name="testhost"
            ),
            action_params=action_params,
        )

        t0 = time.monotonic()
        response, error_code = await async_action_dispatcher(
            world_cfg, action, params=action_params, timeout=10
        )
        elapsed = time.monotonic() - t0

        reporter.check(
            "async_action_dispatcher succeeds via RPC alone "
            "(no HTTP server is listening, so a fallback would fail)",
            lambda: error_code == ErrorCodes.none and response == {"ok": True},
        )
        reporter.check(
            "async_action_dispatcher took the RPC fast path (fast, no HTTP retry backoff)",
            lambda: elapsed < 3.0,
        )
        reporter.check(
            "ACTION_CTX was populated with the real Action, not left as None",
            lambda: captured.get("ctx_is_none") is False,
        )
        reporter.check(
            "server-side action.action_params carries the dispatched params",
            lambda: captured.get("action_params", {}).get("duration") == 2.5
            and captured.get("action_params", {}).get("external_trigger") is False,
        )
        reporter.check(
            "an action param literally named 'timeout' reaches the handler "
            "instead of colliding with RPCClient.call's own timeout kwarg",
            lambda: captured.get("timeout") == 5000,
        )
        reporter.check(
            "external_trigger (bool) round-trips through msgpack + _coerce_args",
            lambda: captured.get("external_trigger") is False,
        )
    finally:
        await dispatcher.close()

    # --- down-peer case: neither RPC nor HTTP is up; must fall back promptly ---
    down_http_port = _free_http_port()
    world_cfg_down = {
        "servers": {
            server_name: {"host": "127.0.0.1", "port": down_http_port},
        }
    }
    down_action = Action(
        action_name=action_name,
        action_server=MachineModel(server_name=server_name, machine_name="testhost"),
        action_params={"duration": 0.1},
    )
    t0 = time.monotonic()
    response, error_code = await async_action_dispatcher(
        world_cfg_down,
        down_action,
        params=down_action.action_params,
        timeout=1,
        retries=1,
    )
    elapsed = time.monotonic() - t0
    reporter.check(
        "async_action_dispatcher against a down peer returns a non-success "
        "ErrorCodes value instead of raising",
        lambda: error_code != ErrorCodes.none and response is None,
    )
    reporter.check(
        "async_action_dispatcher against a down peer returns promptly "
        "(RPC probe capped at _RPC_PROBE_TIMEOUT, then one short HTTP retry)",
        lambda: elapsed < 15.0,
    )


async def _exercise_http_fallback(reporter: TestReporter) -> None:
    """Drive ``async_private_dispatcher`` against an unreachable peer."""
    # Pick a port nothing is listening on. The RPC fast path will fail
    # quickly and the HTTP fallback should exhaust its retries.
    port = _free_port()
    response, error_code = await async_private_dispatcher(
        server_key="nope",
        host="127.0.0.1",
        port=port,
        private_action="ping",
        timeout=1,
        retries=1,
    )
    reporter.check(
        "async_private_dispatcher returns None response when peer is down",
        lambda: response is None,
    )
    reporter.check(
        "async_private_dispatcher returns a non-success ErrorCodes value",
        lambda: error_code != ErrorCodes.none,
    )


async def _exercise_endpoints_available(reporter: TestReporter) -> None:
    """Confirm ``endpoints_available`` classifies a dead URL as unreachable."""
    port = _free_port()
    available, unavailable = await endpoints_available(
        [f"http://127.0.0.1:{port}/__nothing__"]
    )
    reporter.check(
        "endpoints_available reports False for unreachable URL",
        lambda: available is False,
    )
    reporter.check(
        "endpoints_available returns the failing URL in the second slot",
        lambda: len(unavailable) == 1
        and unavailable[0][0].startswith("http://127.0.0.1:"),
    )


def dispatcher_unit_test() -> bool:
    """Run all inter-server communication assertions and report pass/fail."""
    reporter = TestReporter("dispatcher")

    try:
        reporter.section("derive_rpc_port + ErrorCodes")
        reporter.check(
            "derive_rpc_port adds RPC_PORT_OFFSET (10000) to the HTTP port",
            lambda: derive_rpc_port(8000) == 18000,
        )
        reporter.check(
            "ErrorCodes.none round-trips through its string value",
            lambda: ErrorCodes(ErrorCodes.none.value) is ErrorCodes.none,
        )
        reporter.check(
            "ErrorCodes.http is the dispatcher's failure flag",
            lambda: ErrorCodes.http.value == "http",
        )

        reporter.section("_query_safe coerces HTTP query params (yarl-safe)")
        # yarl rejects bool query values ("Invalid variable type") -- an action
        # param named external_trigger=False crashed the HTTP fallback POST and
        # got swallowed as an escalating-sleep hang. bool -> "true"/"false"
        # (FastAPI parses back to bool), None dropped, scalars passed through.
        safe = _query_safe(
            {
                "external_trigger": False,
                "flag": True,
                "n": 3,
                "x": 1.5,
                "s": "a",
                "z": None,
            }
        )
        reporter.check(
            "_query_safe maps bool -> 'true'/'false'",
            lambda: safe.get("external_trigger") == "false"
            and safe.get("flag") == "true",
        )
        reporter.check(
            "_query_safe drops None and passes str/int/float through",
            lambda: safe
            == {
                "external_trigger": "false",
                "flag": "true",
                "n": 3,
                "x": 1.5,
                "s": "a",
            },
        )

        reporter.section("RPCDispatcher <-> RPCClient round-trip")
        asyncio.run(_exercise_rpc(reporter))

        reporter.section("async_action_dispatcher over the real RPC fast path")
        asyncio.run(_exercise_action_dispatcher_rpc(reporter))

        reporter.section("async_private_dispatcher HTTP fallback returns gracefully")
        asyncio.run(_exercise_http_fallback(reporter))

        reporter.section("endpoints_available classifies unreachable URLs")
        asyncio.run(_exercise_endpoints_available(reporter))

        reporter.section("dispatcher module-level RPC client cache teardown")
        # These should not raise even after the tests above flushed the cache
        asyncio.run(aclose_all_rpc_clients())
        close_all_sync_rpc_clients()
        reporter.check(
            "aclose_all_rpc_clients + close_all_sync_rpc_clients are idempotent",
            lambda: True,
        )

        return reporter.success()

    except Exception as exc:  # noqa: BLE001
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        print(repr(exc), tb)
        return False
