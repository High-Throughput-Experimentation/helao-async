"""Orchestrator status subscriber — JSON ``/ws_status`` ingestion (SP-ORCH-5 Part b1).

For each action server in the CONFIG ``servers`` map, one long-lived asyncio
task connects to ``ws://{host}:{port}/ws_status``, JSON-decodes each frame
(action dict from ``BaseAPI._ws_relay`` / ``emit_status``), rebuilds it into
an :class:`~helao.framework.models.server.ActionServerModel`, and calls
``await driver.on_status_update(asm)``.

Wire-format note
----------------
``BaseAPI._ws_relay`` sends ``/ws_status`` frames as **JSON** via
``send_json`` (SP8 WS-B), NOT zstd+pickle.  Therefore this module uses a
plain ``websockets.connect`` + ``json.loads`` reader and does NOT use
``helao.helpers.ws_utils.WsSubscriber``.

Lifecycle
---------
``OrchStatusSubscriber.start(driver)`` spawns one asyncio task per action
server.  Tasks are cancelled on ``stop()``.  A dropped or failed WebSocket
logs a warning and retries after a short backoff — a socket failure must not
kill the orchestrator.  Tasks guard themselves: the reconnect loop is bounded
to ``_MAX_RECONNECT_WAIT`` seconds per attempt.

The subscriber is only started when ``servers_map`` contains at least one
entry with ``group == "action"``.  Unit tests that pass no ``servers_map`` do
not start any tasks.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Dict, List, Optional

from helao.framework.models.server import ActionServerModel, EndpointModel
from helao.framework.models.hlostatus import HloStatus

LOGGER = logging.getLogger(__name__)

__all__ = ["OrchStatusSubscriber", "asm_from_action_dict"]

# Reconnect back-off cap (seconds).  The loop sleeps this long after each
# failed / dropped connection before it tries again.
_MAX_RECONNECT_WAIT: float = 5.0


def asm_from_action_dict(payload: dict) -> Optional[ActionServerModel]:
    """Rebuild an :class:`ActionServerModel` from a raw ``/ws_status`` JSON payload.

    ``BaseAPI.emit_status`` pushes individual action dicts
    (``RunAction.as_dict()``).  This helper wraps the action dict into an
    ``ActionServerModel`` shaped exactly like ``_synthesize_finished_status``
    so that ``on_status_update`` can merge it into the global-status model.

    Returns ``None`` (and logs a warning) if the payload cannot be parsed.
    """
    from helao.framework.models.action import ActionModel
    from helao.framework.models.machine import MachineModel

    try:
        # Reconstruct an ActionModel from the raw payload dict.
        action = ActionModel(**{
            k: v for k, v in payload.items()
            if k in ActionModel.model_fields
        })
    except Exception as exc:
        LOGGER.warning("asm_from_action_dict: could not parse action dict: %r — %s", payload, exc)
        return None

    ep_name = action.action_name or "run_action"

    # Classify into active vs finished bucket.
    if HloStatus.finished in action.action_status:
        endpoint = EndpointModel(
            endpoint_name=ep_name,
            active_dict={},
            nonactive_dict={HloStatus.finished: {action.action_uuid: action}},
        )
    else:
        # active (started) or any intermediate status
        endpoint = EndpointModel(
            endpoint_name=ep_name,
            active_dict={action.action_uuid: action},
            nonactive_dict={},
        )

    return ActionServerModel(
        action_server=action.action_server,
        endpoints={ep_name: endpoint},
    )


class OrchStatusSubscriber:
    """Manages one JSON ``/ws_status`` subscriber task per action server.

    Args:
        servers_map: Full CONFIG ``servers`` dict (all groups).  Only entries
            with ``group == "action"`` get a subscriber task.

    Usage::

        sub = OrchStatusSubscriber(servers_map)
        sub.start(driver)     # call inside startup hook / after event loop is up
        ...
        sub.stop()            # call inside shutdown hook
    """

    def __init__(self, servers_map: Optional[Dict[str, dict]] = None) -> None:
        self._servers_map: Dict[str, dict] = dict(servers_map or {})
        self._tasks: List[asyncio.Task] = []

    def start(self, driver) -> None:
        """Start one subscriber task per action server.  No-op if no action servers.

        Args:
            driver: An :class:`~helao.framework.app.orch_api.OrchDriver` whose
                ``on_status_update`` coroutine is called for each frame.
        """
        action_servers = {
            key: cfg
            for key, cfg in self._servers_map.items()
            if isinstance(cfg, dict) and cfg.get("group") == "action"
        }
        if not action_servers:
            return
        for server_key, cfg in action_servers.items():
            host = cfg.get("host") or cfg.get("hostname") or "127.0.0.1"
            port = int(cfg.get("port") or 8000)
            task = asyncio.create_task(
                self._subscribe_loop(server_key, host, port, driver),
                name=f"orch_status_sub_{server_key}",
            )
            self._tasks.append(task)
        LOGGER.info(
            "OrchStatusSubscriber: started %d subscriber task(s) for action servers: %s",
            len(self._tasks),
            list(action_servers),
        )

    def stop(self) -> None:
        """Cancel all subscriber tasks (idempotent)."""
        for task in self._tasks:
            if not task.done():
                task.cancel()
        self._tasks.clear()

    async def _subscribe_loop(
        self, server_key: str, host: str, port: int, driver
    ) -> None:
        """Long-lived reconnect loop for one action server.

        Connects to ``ws://{host}:{port}/ws_status``, decodes each JSON frame,
        rebuilds it into an ``ActionServerModel``, and feeds it to
        ``driver.on_status_update``.  On any connection error the loop logs,
        waits ``_MAX_RECONNECT_WAIT`` seconds, then retries.  The task only
        exits when cancelled.
        """
        import websockets

        url = f"ws://{host}:{port}/ws_status"
        LOGGER.info("OrchStatusSubscriber: subscribing to %s (server_key=%s)", url, server_key)

        while True:
            try:
                async with websockets.connect(url, open_timeout=10.0) as ws:
                    LOGGER.info(
                        "OrchStatusSubscriber: connected to %s", url
                    )
                    while True:
                        raw = await ws.recv()
                        if isinstance(raw, bytes):
                            raw = raw.decode()
                        try:
                            payload = json.loads(raw)
                        except json.JSONDecodeError as exc:
                            LOGGER.warning(
                                "OrchStatusSubscriber[%s]: non-JSON frame — %s", server_key, exc
                            )
                            continue
                        # DIAGNOSTIC (SP-ORCH-5 live bring-up): log every frame so a
                        # stuck-orch can be traced to received / parsed / folded.
                        LOGGER.info(
                            "OrchStatusSubscriber[%s]: frame action_name=%r status=%r uuid=%r orchestrator=%r",
                            server_key,
                            payload.get("action_name"),
                            payload.get("action_status"),
                            payload.get("action_uuid"),
                            payload.get("orchestrator"),
                        )
                        asm = asm_from_action_dict(payload)
                        if asm is not None:
                            before = list(driver.state.globalstatusmodel.active_dict.keys())
                            await driver.on_status_update(asm)
                            after = list(driver.state.globalstatusmodel.active_dict.keys())
                            LOGGER.info(
                                "OrchStatusSubscriber[%s]: folded frame; gsm.orchestrator=%r active_dict %r -> %r",
                                server_key,
                                driver.state.globalstatusmodel.orchestrator,
                                before,
                                after,
                            )
                        else:
                            LOGGER.warning(
                                "OrchStatusSubscriber[%s]: asm_from_action_dict returned None (frame dropped)",
                                server_key,
                            )
            except asyncio.CancelledError:
                LOGGER.info("OrchStatusSubscriber: task cancelled for %s", server_key)
                raise
            except Exception as exc:
                LOGGER.warning(
                    "OrchStatusSubscriber[%s]: connection lost (%s); retrying in %.1fs",
                    server_key, exc, _MAX_RECONNECT_WAIT,
                )
                await asyncio.sleep(_MAX_RECONNECT_WAIT)
