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
"""

__all__ = ["dispatcher_unit_test"]

import asyncio
import socket
import traceback

from helao.core.error import ErrorCodes
from helao.core.rpc import (
    RPCClient,
    RPCDispatcher,
    RPCError,
    RPCSyncClient,
    derive_rpc_port,
)
from helao.helpers.dispatcher import (
    aclose_all_rpc_clients,
    async_private_dispatcher,
    close_all_sync_rpc_clients,
    endpoints_available,
)
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

        reporter.section("RPCDispatcher <-> RPCClient round-trip")
        asyncio.run(_exercise_rpc(reporter))

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
