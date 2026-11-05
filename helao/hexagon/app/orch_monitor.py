"""Network subscription / heartbeat collaborator extracted from ``Orch`` (CARDS P5, Stage S3).

``Orch.subscribe_all``/``Orch.ping_action_servers``/``Orch.action_server_monitor``
implement the orchestrator's network-facing "cluster D": subscribing to every
non-Bokeh action server in the world config at startup, and the heartbeat loop
that periodically refreshes ``status_summary`` for the operator UI. This module
holds those method bodies in a ``ServerMonitor`` collaborator that ``Orch``
delegates to. (The heartbeat that stops the orchestrator when an active
action's endpoint goes unreachable is HexHealthMonitor's.)

Per the P5 constraints (:doc:`CARDS_REFACTOR_P5.md` sec 3.1 rule 3):
``ServerMonitor`` caches no shared mutable state -- it holds only the ``orch``
back-reference and reads ``world_cfg``, ``globalstatusmodel``,
``heartbeat_interval``, and writes ``init_success``/
``status_summary``/``current_stop_message`` through it at call time, so a
reassignment made between construction and a call (or between two calls, e.g.
by ``import_queues``) is always observed. Behavior is byte-identical to the
original inline methods, including retry/backoff timing and log message wording.

Task-creation semantics are unchanged: ``Orch.myinit`` still does
``asyncio.create_task(self.subscribe_all())`` etc. via the thin delegators on
``Orch`` -- this module only relocates the method bodies, not when/where the
background tasks are started.
"""

import asyncio

import aiohttp

from helao.core.error import ErrorCodes
from helao.helpers import helao_logging as logging
from helao.helpers.config_loader import is_ui_only_server
from helao.helpers.dispatcher import async_private_dispatcher
from helao.helpers.server_keys import SYNC_SERVER_KEY

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class ServerMonitor:
    """Network subscription and heartbeat/monitor loops for an ``Orch``.

    Holds only the ``orch`` back-reference (never a cached deque/attribute/task
    handle), per the call-time state resolution rule -- see module docstring.
    """

    def __init__(self, orch):
        self.orch = orch

    async def subscribe_all(self, retry_limit: int = 15):
        """Subscribe this orchestrator to every non-Bokeh action server in the world config.

        Args:
            retry_limit: Maximum subscription attempts per server.
        """
        orch = self.orch
        fails = []
        for serv_key, serv_dict in orch.world_cfg["servers"].items():
            if not is_ui_only_server(serv_dict):
                LOGGER.info(f"trying to subscribe to {serv_key} status")

                success = False
                serv_addr = serv_dict["host"]
                serv_port = serv_dict["port"]
                for _ in range(retry_limit):
                    try:
                        response, error_code = await async_private_dispatcher(
                            server_key=serv_key,
                            host=serv_addr,
                            port=serv_port,
                            private_action="attach_client",
                            params_dict={
                                "client_servkey": orch.server.server_name,
                                "client_host": orch.server_cfg["host"],
                                "client_port": orch.server_cfg["port"],
                            },
                            json_dict={},
                        )
                        # print(response)
                        # print(error_code)
                        if response is not None and error_code == ErrorCodes.none:
                            success = True
                            break
                    except aiohttp.client_exceptions.ClientConnectorError:
                        LOGGER.error(
                            f"failed to subscribe to {serv_key} at {serv_addr}:{serv_port}, trying again in 2 seconds",
                            exc_info=True,
                        )
                        await asyncio.sleep(2)

                if success:
                    LOGGER.info(f"Subscribed to {serv_key} at {serv_addr}:{serv_port}")
                else:
                    fails.append(serv_key)
                    LOGGER.info(
                        f"Failed to subscribe to {serv_key} at {serv_addr}:{serv_port}. Check connection."
                    )

        if len(fails) == 0:
            orch.init_success = True
        else:
            LOGGER.info(
                "Orchestrator cannot action experiment_dq unless all FastAPI servers in config file are accessible."
            )

    async def ping_action_servers(self) -> dict:
        """Query every action server for its endpoint and driver status.

        Returns:
            Mapping of ``server_key`` to ``(status_str, driver_status)`` where
            ``status_str`` is ``"idle"``, ``"busy [<endpoints>]"`` or
            ``"unreachable"``.
        """
        orch = self.orch
        status_summary = {}
        for serv_key, serv_dict in orch.world_cfg["servers"].items():
            if serv_key in [SYNC_SERVER_KEY, "ANA"]:
                continue
            if "ignore_heartbeats" in serv_dict.get("params", {}):
                continue
            if not is_ui_only_server(serv_dict):
                serv_addr = serv_dict["host"]
                serv_port = serv_dict["port"]
                try:
                    response, error_code = await async_private_dispatcher(
                        server_key=serv_key,
                        host=serv_addr,
                        port=serv_port,
                        private_action="get_status",
                        params_dict={
                            "client_servkey": orch.server.server_name,
                            "client_host": orch.server_cfg["host"],
                            "client_port": orch.server_cfg["port"],
                        },
                        json_dict={},
                    )
                    if response is not None and error_code == ErrorCodes.none:
                        busy_endpoints = []
                        driver_status = response.get("_driver_status", "unknown")
                        for endpoint_name, endpoint_dict in response.get(
                            "endpoints", {}
                        ).items():
                            if endpoint_dict["active_dict"]:
                                busy_endpoints.append(endpoint_name)
                        if busy_endpoints:
                            busy_str = ", ".join(busy_endpoints)
                            status_str = f"busy [{busy_str}]"
                        else:
                            status_str = "idle"
                        status_summary[serv_key] = (status_str, driver_status)
                    else:
                        status_summary[serv_key] = ("unreachable", "unknown")
                except aiohttp.client_exceptions.ClientConnectorError:
                    status_summary[serv_key] = ("unreachable", "unknown")
        return status_summary

    async def action_server_monitor(self):
        """Heartbeat loop that refreshes ``status_summary`` via :meth:`ping_action_servers`."""
        orch = self.orch
        while True:
            orch.status_summary = await self.ping_action_servers()
            await asyncio.sleep(orch.heartbeat_interval)
