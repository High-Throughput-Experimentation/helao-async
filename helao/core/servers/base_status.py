"""Status-WebSocket + broadcast collaborator extracted from ``Base`` (CARDS
P6, Stage S2).

``Base``'s status "cluster" -- the outbound status/data/live WebSocket relays,
the remote-subscriber registry, the periodic and event-driven status
broadcasters, and the ``guarded_replace`` status shim -- is moved here into a
``StatusBroadcaster`` collaborator that ``Base`` delegates to. This is the
``Base`` analog of P5's ``orch_status_sync.StatusIngester`` and follows the
``LiveBuffer`` (S1) pattern exactly.

Methods relocated (bodies byte-identical to the original inline ``Base``
methods, with ``self.`` rewritten to ``self.base.``):

- ``send_statuspackage`` / ``send_nbstatuspackage`` -- push the action-server
  model (or a single non-blocking action) to a remote subscriber via the
  private dispatcher.
- ``attach_client`` / ``detach_client`` -- add/remove a remote subscriber in
  ``base.status_clients`` (and deliver an initial snapshot on attach).
- ``_ws_relay`` -- the shared zstd/pickle WebSocket relay used by...
- ``ws_status`` / ``ws_data`` / ``ws_live`` -- the three WS endpoints (over
  ``base.status_q`` / ``base.data_q`` / ``base.live_q`` respectively).
- ``regular_status_task`` / ``log_status_task`` -- the periodic and
  event-driven broadcast loops.
- ``detach_subscribers`` -- signal the status/data queues to terminate.
- ``replace_status`` -- the ``guarded_replace`` status-list shim.

State stays on ``Base`` (rule 3, same as ``LiveBuffer``): ``status_q``,
``data_q``, ``live_q``, ``status_clients``, the ``status_publisher`` and the
background task handles (``status_logger``, ``regular_updater``) remain
attributes of ``Base``, constructed exactly where they are today in
``Base.__init__`` / ``Base.myinit``. ``StatusBroadcaster`` caches none of them;
it holds only the ``base`` back-reference and reads/writes those attributes
through it at call time, so any reassignment between construction and a call is
observed.

Task-creation semantics are unchanged: ``Base.myinit`` still does
``create_task(self.log_status_task())`` / ``create_task(self.regular_status_task(...))``
through the thin ``Base`` delegators, so bound-method identity and launch
timing are identical -- this module only relocates the method bodies.

Lock/queue ownership map (Base-server data-plane; duplicated verbatim in
``base_status.py``, ``base_live_buffer.py``, and ``active_data_stream.py`` --
the three queue owners):

- ``status_q`` (on ``Base``) -- written by ``StatusBroadcaster`` (status
  packages) + ``Active.add_status``; subscribed by
  ``StatusBroadcaster.ws_status``.
- ``live_q`` (on ``Base``) -- written by ``LiveBuffer.put_lbuf``; drained by
  ``LiveBuffer.live_buffer_task``; relayed by ``StatusBroadcaster.ws_live``.
- ``data_q`` (on ``Base``) -- written by ``DataStreamer.enqueue_data*`` (via
  ``Active``); drained by ``DataStreamer.log_data_task``; relayed by
  ``StatusBroadcaster.ws_data``.
- Active per-action collaborators (``data_file_writer``/``data_stream``/
  ``executor_runner``/``action_finalizer``) hold only ``self.active``; Base
  collaborators hold only ``self.base``; all read shared state at call time.
"""

import asyncio
import pickle
import traceback
from time import sleep
from typing import Optional

import pyzstd
from fastapi import WebSocket

from helao.helpers import helao_logging as logging
from helao.helpers.dispatcher import async_private_dispatcher
from helao.helpers.multisubscriber_queue import MultisubscriberQueue
from helao.helpers.premodels import Action
from helao.core.models.hlostatus import HloStatus
from helao.core.models.status_transitions import guarded_replace
from helao.core.models.server import EndpointModel
from helao.core.error import ErrorCodes

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class StatusBroadcaster:
    """Status-WS + broadcast methods for a ``Base``.

    Holds only the ``base`` back-reference (never a cached queue/set/task
    handle), per the call-time state resolution rule -- see module docstring.
    """

    def __init__(self, base):
        self.base = base

    async def send_statuspackage(
        self,
        client_servkey: str,
        client_host: str,
        client_port: int,
        action_name: Optional[str] = None,
    ) -> tuple:
        """Send the current action-server model to a remote subscriber.

        Args:
            client_servkey: Service key of the target client.
            client_host: Host of the target client.
            client_port: Port of the target client.
            action_name: Optional endpoint name to restrict the payload.

        Returns:
            ``(response, error_code)`` from the dispatcher.
        """
        json_dict = {
            "actionservermodel": self.base.actionservermodel.get_fastapi_json(
                action_name=action_name,
            ),
        }
        response, error_code = await async_private_dispatcher(
            server_key=client_servkey,
            host=client_host,
            port=client_port,
            private_action="update_status",
            params_dict={"regular_task": "true" if action_name is None else "false"},
            json_dict=json_dict,
        )
        return response, error_code

    async def send_nbstatuspackage(
        self,
        client_servkey: str,
        client_host: str,
        client_port: int,
        actionmodel: Action,
    ) -> tuple:
        """Send a single non-blocking action status update to a remote subscriber.

        Args:
            client_servkey: Service key of the target client.
            client_host: Host of the target client.
            client_port: Port of the target client.
            actionmodel: ``Action`` describing the non-blocking event.

        Returns:
            ``(response, error_code)`` from the dispatcher.
        """
        # needs private dispatcher
        json_dict = {
            "actionmodel": actionmodel.as_dict(),
        }
        params_dict = {
            "server_host": self.base.server_cfg["host"],
            "server_port": self.base.server_cfg["port"],
        }
        LOGGER.info(f"sending non-blocking status: {json_dict}")
        response, error_code = await async_private_dispatcher(
            server_key=client_servkey,
            host=client_host,
            port=client_port,
            private_action="update_nonblocking",
            params_dict=params_dict,
            json_dict=json_dict,
        )
        LOGGER.info(f"update_nonblocking request got response: {response}")
        return response, error_code

    async def attach_client(
        self, client_servkey: str, client_host: str, client_port: int, retry_limit=5
    ) -> bool:
        """Register a remote client as a status subscriber and push an initial snapshot.

        Args:
            client_servkey: Service key of the client.
            client_host: Host of the client.
            client_port: Port of the client.
            retry_limit: Number of attempts to deliver the initial status.

        Returns:
            ``True`` if the initial snapshot was delivered, ``False`` otherwise.
        """
        success = False
        combo_key = (
            client_servkey,
            client_host,
            client_port,
        )
        LOGGER.info("attaching status subscriber")

        if combo_key in self.base.status_clients:
            LOGGER.info(
                f"Client {combo_key} is already subscribed to {self.base.server.server_name} status updates."
            )
            # self.detach_client(client_servkey, client_host, client_port)  # refresh
        self.base.status_clients.add(combo_key)

        # sends current status of all endpoints (action_name = None)
        for _ in range(retry_limit):
            response, error_code = await self.base.send_statuspackage(
                client_servkey=client_servkey,
                client_host=client_host,
                client_port=client_port,
                action_name=None,
            )
            if response is not None and error_code == ErrorCodes.none:
                LOGGER.info(
                    f"Added {combo_key} to {self.base.server.server_name} status subscriber list."
                )
                success = True
                break
            else:
                LOGGER.error(
                    f"Failed to add {combo_key} to {self.base.server.server_name} status subscriber list."
                )

            if success:
                LOGGER.info(
                    f"Attached {combo_key} to status ws on {self.base.server.server_name}."
                )
            else:
                LOGGER.error(
                    f"failed to attach {combo_key} to status ws on {self.base.server.server_name} after {retry_limit} attempts."
                )

        return success

    def detach_client(self, client_servkey: str, client_host: str, client_port: int):
        """Remove a remote client from this server's status subscriber set."""
        combo_key = (
            client_servkey,
            client_host,
            client_port,
        )
        if combo_key in self.base.status_clients:
            self.base.status_clients.remove(combo_key)
            LOGGER.info(f"Client {combo_key} will no longer receive status updates.")
        else:
            LOGGER.info(f"Client {combo_key} is not subscribed.")

    async def _ws_relay(
        self,
        websocket: WebSocket,
        queue: MultisubscriberQueue,
        label: str,
        use_as_dict: bool = True,
    ) -> None:
        """Accept ``websocket`` and stream zstd-compressed pickled messages from ``queue`` until disconnect.

        Args:
            websocket: WebSocket connection to serve.
            queue: Source queue providing messages.
            label: Short identifier used in log lines.
            use_as_dict: When True, call ``msg.as_dict()`` before serialising.
        """
        LOGGER.info(f"got new {label} subscriber")
        await websocket.accept()
        sub = queue.subscribe()
        try:
            async for msg in sub:
                payload = msg.as_dict() if use_as_dict else msg
                await websocket.send_bytes(pyzstd.compress(pickle.dumps(payload)))
        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            LOGGER.error(
                f"{label.capitalize()} websocket client "
                f"{websocket.client[0]}:{websocket.client[1]} disconnected. "
                f"{repr(e), tb,}"
            )
            if sub in queue.subscribers:
                queue.remove(sub)

    async def ws_status(self, websocket: WebSocket) -> None:
        """Stream compressed status messages over ``websocket`` until the client disconnects."""
        await self.base._ws_relay(websocket, self.base.status_q, "status")

    async def ws_data(self, websocket: WebSocket) -> None:
        """Stream compressed data packets over ``websocket`` until the client disconnects."""
        await self.base._ws_relay(websocket, self.base.data_q, "data")

    async def ws_live(self, websocket: WebSocket) -> None:
        """Stream compressed live-buffer updates over ``websocket`` until disconnect."""
        await self.base._ws_relay(
            websocket, self.base.live_q, "live_buffer", use_as_dict=False
        )

    async def regular_status_task(self, delay: float = 10, retry_limit: int = 5):
        """Periodically push the action-server status to every subscribed client."""
        while True:
            for combo_key in self.base.status_clients.copy():
                client_servkey, client_host, client_port = combo_key
                for _ in range(retry_limit):
                    response, error_code = await self.base.send_statuspackage(
                        action_name=None,
                        client_servkey=client_servkey,
                        client_host=client_host,
                        client_port=client_port,
                    )
                    if response and error_code == ErrorCodes.none:
                        break
            await asyncio.sleep(delay)

    async def log_status_task(self, retry_limit: int = 5):
        """Subscribe to the status queue, broadcast to subscribers, and drive endpoint/unified queues.

        Args:
            retry_limit: Number of attempts to deliver each status update to a subscriber.
        """
        LOGGER.info(f"{self.base.server.server_name} status log task created.")

        try:
            # get the new Action (status) from the queue
            async for status_msg in self.base.status_q.subscribe():
                # add it to the correct "EndpointModel"
                # in the "ActionServerModel"
                if status_msg.action_name not in self.base.actionservermodel.endpoints:
                    # a new endpoints became available
                    self.base.actionservermodel.endpoints[status_msg.action_name] = (
                        EndpointModel(endpoint_name=status_msg.action_name)
                    )
                self.base.actionservermodel.endpoints[
                    status_msg.action_name
                ].active_dict.update({status_msg.action_uuid: status_msg})
                self.base.actionservermodel.last_action_uuid = status_msg.action_uuid

                # sort the status (nonactive_dict is empty at this point)
                self.base.actionservermodel.endpoints[
                    status_msg.action_name
                ].sort_status()
                LOGGER.info(
                    f"log_status_task sending status {status_msg.action_status} for action {status_msg.action_name} with uuid {status_msg.action_uuid} on {status_msg.action_server.disp_name()} to subscribers ({self.base.status_clients})."
                )
                if (
                    len(self.base.status_clients) == 0
                    and self.base.orch_key is not None
                ):
                    await self.base.attach_client(
                        self.base.orch_key, self.base.orch_host, self.base.orch_port
                    )

                for combo_key in self.base.status_clients.copy():
                    client_servkey, client_host, client_port = combo_key
                    LOGGER.debug(
                        f"log_status_task trying to send status to {client_servkey}."
                    )
                    success = False
                    for _ in range(retry_limit):
                        response, error_code = await self.base.send_statuspackage(
                            action_name=status_msg.action_name,
                            client_servkey=client_servkey,
                            client_host=client_host,
                            client_port=client_port,
                        )

                        if response and error_code == ErrorCodes.none:
                            success = True
                            break

                    if success:
                        LOGGER.info(f"Pushed status message to {client_servkey}.")
                    else:
                        LOGGER.error(
                            f"Failed to push status message to {client_servkey} after {retry_limit} attempts."
                        )
                    sleep(0.3)
                # now delete the errored and finsihed statuses after
                # all are send to the subscribers
                self.base.actionservermodel.endpoints[
                    status_msg.action_name
                ].clear_finished()
                LOGGER.debug("all log_status_task messages sent.")

                active_nonqueued = {
                    endpoint: [
                        auuid
                        for auuid, act in endmod.active_dict.items()
                        if not act.action_params.get("queued_on_actserv", False)
                        or act.action_params.get("queued_launch", False)
                    ]
                    for endpoint, endmod in self.base.actionservermodel.endpoints.items()
                }
                active_nq = [x for y in active_nonqueued.values() for x in y]

                if not self.base.server_params.get("allow_concurrent_actions", True):
                    if len(self.base.local_action_queue) > 0 and not active_nq:
                        await self.base.process_unified_queue()
                else:
                    if len(
                        self.base.endpoint_queues[status_msg.action_name]
                    ) > 0 and not active_nonqueued.get(status_msg.action_name, []):
                        await self.base.process_endpoint_queue(status_msg)

            LOGGER.info("log_status_task done.")

        # except asyncio.CancelledError:
        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            LOGGER.error(f"status logger task was cancelled with error: {repr(e), tb,}")

    async def detach_subscribers(self):
        """Signal the status and data queues to terminate and yield long enough to drain them."""
        await self.base.status_q.put(StopAsyncIteration)
        await self.base.data_q.put(StopAsyncIteration)
        await asyncio.sleep(1)

    def replace_status(
        self, status_list: list[HloStatus], old_status: HloStatus, new_status: HloStatus
    ):
        """Swap ``old_status`` for ``new_status`` in ``status_list``, or append if missing.

        Prefer the model methods (``replace_action_status``/``replace_experiment_status``/
        ``replace_sequence_status``) for new call sites; this shim delegates to
        ``guarded_replace`` for callers still holding a bare ``status_list`` reference.
        """
        guarded_replace(status_list, old_status, new_status)
