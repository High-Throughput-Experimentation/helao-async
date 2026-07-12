"""FastAPI scaffolding for the HELAO orchestrator server.

Provides the ``OrchAPI`` application class plus the built-in ``wait``,
``cancel_wait``, ``interrupt``, ``estop`` and conditional flow-control
action endpoints exposed by every orchestrator deployment.
"""

import time
import asyncio
from enum import Enum
from typing import Union, Optional, List
from collections import namedtuple

from fastapi import Body, WebSocket
from starlette.exceptions import HTTPException as StarletteHTTPException
from helao.core.drivers.helao_driver import HelaoDriver
from helao.helpers.server_api import HelaoFastAPI
from helao.core.servers.orch import Orch
from helao.core.models.server import ActionServerModel
from helao.core.models.orchstatus import LoopStatus
from helao.helpers.premodels import Sequence, Experiment, Action
from helao.helpers.executor import Executor
from helao.core.error import ErrorCodes
from helao.core.models.hlostatus import HloStatus

from helao.helpers import helao_logging as logging
from helao.core.servers.base_api import (
    action_version,
    _make_app_entry_middleware,
    _make_http_exception_handler,
    _add_default_head_endpoints,
    _register_utility_endpoints,
)

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


def _histories_payload(orch) -> dict:
    """Return action/experiment/sequence history as JSON-safe (uuid, dict) item lists."""
    return {
        "action": list(orch.action_history.items()),
        "experiment": list(orch.experiment_history.items()),
        "sequence": list(orch.sequence_history.items()),
    }


def _status_summary_payload(orch) -> dict:
    """Return {server: [server_status, driver_status]} from orch.status_summary."""
    return {k: list(v) for k, v in orch.status_summary.items()}


def _step_flags_payload(orch) -> dict:
    """Return the orchestrator's three step-through flags."""
    return {
        "actions": orch.step_thru_actions,
        "experiments": orch.step_thru_experiments,
        "sequences": orch.step_thru_sequences,
    }


def _set_step_flag(orch, kind: str, value: bool) -> dict:
    """Set one step-through flag by kind ('actions'|'experiments'|'sequences')."""
    attr = {
        "actions": "step_thru_actions",
        "experiments": "step_thru_experiments",
        "sequences": "step_thru_sequences",
    }[kind]
    setattr(orch, attr, bool(value))
    return {kind: getattr(orch, attr)}


def _queue_counts(orch) -> dict:
    """Return true queue lengths for the three deques."""
    return {
        "n_sequences": len(orch.sequence_dq),
        "n_experiments": len(orch.experiment_dq),
        "n_actions": len(orch.action_dq),
    }


async def _prepend_sequences(orch, sequences) -> list:
    """Coerce ``sequences`` to ``Sequence`` instances and prepend them on the orch."""
    seqs = [s if isinstance(s, Sequence) else Sequence(**s) for s in sequences]
    return await orch.prepend_sequences(sequences=seqs)


def _queue_object_payload(orch, kind: str, idx: int) -> dict:
    """Return the full dict for the queued item of ``kind`` at ``idx``.

    Out-of-range indices or unknown kinds return ``{}`` (the queue may have
    mutated since the table was last polled — snapshot semantics).

    Mirrors ``RemoteBackend.get_queue_object``; keep the two in sync."""
    dq = {
        "sequence": getattr(orch, "sequence_dq", None),
        "experiment": getattr(orch, "experiment_dq", None),
        "action": getattr(orch, "action_dq", None),
    }.get(kind)
    if dq is None:
        return {}
    try:
        return dq[idx].as_dict()
    except (IndexError, KeyError, AttributeError):
        return {}


class OrchAPI(HelaoFastAPI):
    """FastAPI application class for the HELAO orchestrator server.

    Mirrors :class:`BaseAPI` but binds an :class:`Orch` controller, exposes
    orchestrator-specific endpoints (queue management, start/stop, conditional
    flow, global params, wait helpers), and runs the orchestrator's Bokeh
    operator UI when configured.
    """

    orch: Orch

    def __init__(
        self,
        server_key,
        server_title,
        description,
        version,
        driver_classes=None,
        poller_class=None,
    ):
        """Initialize the OrchAPI app and register its endpoints and lifecycle events.

        Args:
            server_key: Unique server key in the world config.
            server_title: Title surfaced to the OpenAPI docs.
            description: OpenAPI description string.
            version: Server/version string.
            driver_classes: Optional iterable of driver classes constructed at startup.
            poller_class: Optional ``DriverPoller`` subclass attached to the first driver.
        """
        super().__init__(
            helao_srv=server_key,
            title=server_title,
            description=description,
            version=str(version),
        )
        self.drivers = tuple()
        self.driver = None
        self.poller = None

        self.middleware("http")(_make_app_entry_middleware(server_key, lambda: self.orch))
        self.exception_handler(StarletteHTTPException)(
            _make_http_exception_handler(server_key, lambda: self.orch)
        )

        @self.on_event("startup")
        async def startup_event():
            """Construct the :class:`Orch` controller, drivers, poller and endpoint queues on startup."""
            self.orch = Orch(fastapp=self)

            self.orch.myinit()
            if driver_classes is not None:
                Drivers = namedtuple("Drivers", [d.__name__ for d in driver_classes])
                driver_dict = {}
                for i, driver_class in enumerate(driver_classes):
                    if issubclass(driver_class, HelaoDriver):
                        driver_inst = driver_class(config=self.server_params)
                        if i == 0 and poller_class is not None:
                            self.poller = poller_class(
                                driver_inst, self.server_cfg.get("polling_time", 0.1)
                            )
                            self.poller._base_hook = self.base
                    else:
                        driver_inst = driver_class(self.base)
                    driver_dict[driver_class.__name__] = driver_inst
                self.drivers = Drivers(**driver_dict)
                self.driver = self.drivers[0]
            self.orch.endpoint_queues_init()

        self.on_event("startup")(lambda: _add_default_head_endpoints(self))

        # --- BASE endpoints ---
        @self.websocket("/ws_status")
        async def websocket_status(websocket: WebSocket):
            """Stream compressed status messages over ``websocket`` until disconnect."""
            await self.orch.ws_status(websocket)

        @self.websocket("/ws_data")
        async def websocket_data(websocket: WebSocket):
            """Stream compressed data packets over ``websocket`` until disconnect."""
            await self.orch.ws_data(websocket)

        @self.websocket("/ws_live")
        async def websocket_live(websocket: WebSocket):
            """Stream compressed live-buffer updates over ``websocket`` until disconnect."""
            await self.orch.ws_live(websocket)

        @self.post("/get_status", tags=["private"])
        def get_status():
            """Return the orchestrator's action-server status with the driver status appended."""
            status_dict = self.orch.actionservermodel.model_dump()
            driver_status = "not_implemented"
            if isinstance(self.driver, HelaoDriver):
                resp = self.driver.get_status()
                driver_status = resp.status
            status_dict["_driver_status"] = driver_status
            return status_dict

        @self.post("/attach_client", tags=["private"])
        async def attach_client(
            client_servkey: str, client_host: str, client_port: int
        ):
            """Subscribe a remote client to this orchestrator's status updates."""
            return await self.orch.attach_client(
                client_servkey, client_host, client_port
            )

        @self.post("/detach_client", tags=["private"])
        def detach_client(client_servkey: str, client_host: str, client_port: int):
            """Remove a client from this orchestrator's status subscriber list."""
            return self.orch.detach_client(client_servkey, client_host, client_port)

        @self.post("/stop_executor", tags=["private"])
        def stop_executor(executor_id: str = ""):
            """Signal the executor with ``executor_id`` to stop, returning an error dict if missing."""
            if executor_id == "":
                return {"error": "executor_id was not specified"}
            return self.orch.stop_executor(executor_id)

        @self.post("/endpoints", tags=["private"])
        def get_all_urls():
            """Return the list of endpoints registered on this orchestrator."""
            return self.orch.get_endpoint_urls()

        @self.post("/get_lbuf", tags=["private"])
        def get_lbuf():
            """Return the orchestrator's current live buffer."""
            return self.orch.live_buffer

        @self.post("/list_executors", tags=["private"])
        def list_executors():
            """Return the keys of every executor currently running on the orchestrator."""
            return list(self.orch.executors.keys())

        @self.post("/shutdown", tags=["private"])
        async def post_shutdown():
            """Trigger the FastAPI shutdown handler via an HTTP request."""
            await shutdown_event()

        # --- ORCH-specific endpoints ---
        @self.post("/global_status", tags=["private"])
        def global_status():
            """Return the orchestrator's ``GlobalStatusModel`` as JSON."""
            return self.orch.globalstatusmodel.as_json()

        @self.post("/export_queues", tags=["private"])
        def export_queues(timestamp_pck: bool = False):
            """Persist the orchestrator's deques and current active/last state to a pickle file."""
            return self.orch.export_queues(timestamp_pck)

        @self.post("/import_queues", tags=["private"])
        def import_queues(pck_path: Optional[str] = None):
            """Restore the orchestrator's deques and active/last state from a pickle file."""
            return self.orch.import_queues(pck_path)

        @self.post("/update_status", tags=["private"])
        async def update_status(
            actionservermodel: ActionServerModel = Body({}, embed=True),
            regular_task: str = "false",
        ):
            """Apply a remote action-server status update to the global model.

            Args:
                actionservermodel: Reported status from a remote action server.
                regular_task: ``"true"`` for periodic heartbeats (suppresses noisy logs).
            """
            if actionservermodel is None:
                return False
            if regular_task == "false":
                LOGGER.debug(
                    f"orch '{self.orch.server.server_name}' got status from '{actionservermodel.action_server.server_name}': {actionservermodel.endpoints}"
                )
            return await self.orch.update_status(actionservermodel=actionservermodel)

        @self.post("/clear_actives", tags=["private"])
        async def clear_actives():
            """Move every active action across all servers into ``skipped`` and return their UUIDs."""
            cleared_actives = []
            for actionservermodel in self.orch.globalstatusmodel.server_dict.values():
                for endpointkey, endpointmodel in actionservermodel.endpoints.items():
                    active_items = list(endpointmodel.active_dict.items())
                    for uuid, statusmodel in active_items:
                        endpointmodel.active_dict.pop(uuid)
                        cleared_actives.append(uuid)
                        self.orch.globalstatusmodel.active_dict.pop(uuid)
                        if HloStatus.skipped not in endpointmodel.nonactive_dict:
                            endpointmodel.nonactive_dict[HloStatus.skipped] = {}
                        endpointmodel.nonactive_dict[HloStatus.skipped].update(
                            {uuid: statusmodel}
                        )
                    actionservermodel.endpoints[endpointkey] = endpointmodel
                await self.orch.update_status(actionservermodel=actionservermodel)
            return cleared_actives

        @self.post("/update_nonblocking", tags=["private"])
        async def update_nonblocking(
            actionmodel: Action = Body({}, embed=True),
            server_host: str = "",
            server_port: int = 9000,
        ):
            """Record a non-blocking action transition reported by ``server_host:server_port``."""
            LOGGER.info(
                f"'{self.orch.server.server_name.upper()}' got nonblocking status from '{actionmodel.action_server.server_name}': exec_id: {actionmodel.exec_id} -- status: {actionmodel.action_status} on {server_host}:{server_port}"
            )
            result_dict = await self.orch.update_nonblocking(
                actionmodel, server_host, server_port
            )
            return result_dict

        @self.post("/update_global_params", tags=["private"])
        async def update_global_params(params: dict = {}):
            """Merge ``params`` into the orchestrator's ``global_params`` dictionary.

            Keep the plain ``dict`` annotation (the RPC coercion layer only wraps a
            flat body into a body-style param when ``ann is dict``; ``Optional[dict]``
            would break that and silently drop non-empty payloads). The ``{}`` default
            tolerates an empty RPC body as a no-op without a missing-arg TypeError; it
            is only ever read (``.update`` FROM it), never mutated, so the shared
            default is safe.
            """
            params = params or {}
            LOGGER.info(f"Updated global params with {params}.")
            # if self.orch.active_experiment is not None:
            #     self.orch.active_experiment.global_params.update(params)
            #     return True
            # else:
            #     self.orch.print_message(
            #         "No active experiment, could not update global params."
            #     )
            #     return False
            self.orch.global_params.update(params)
            return True

        @self.post("/start", tags=["private"])
        async def start():
            """Start (or resume) the orchestrator's dispatch loop."""
            await self.orch.start()
            return {}

        @self.post("/get_active_experiment", tags=["private"])
        def get_active_experiment():
            """Return the active experiment as a cleaned dict (empty dict if none)."""
            if self.orch.active_experiment is None:
                return {}
            return self.orch.active_experiment.clean_dict()

        @self.post("/get_active_sequence", tags=["private"])
        def get_active_sequence():
            """Return the active sequence as a cleaned dict (empty dict if none)."""
            if self.orch.active_sequence is None:
                return {}
            return self.orch.active_sequence.clean_dict()

        @self.post("/estop_orch", tags=["private"])
        async def estop_orch():
            """Trigger an emergency stop if the loop is running, otherwise log and return."""
            if self.orch.globalstatusmodel.loop_state == LoopStatus.started:
                await self.orch.estop_loop()
            elif self.orch.globalstatusmodel.loop_state == LoopStatus.estopped:
                LOGGER.info("orchestrator E-STOP flag already raised")
            else:
                LOGGER.info("orchestrator is not running")
            return {}

        @self.post("/stop", tags=["private"])
        async def stop(reset_run_id: bool = False):
            """Request a graceful stop of the orchestrator's dispatch loop.

            ``reset_run_id`` also drops the active run_id so the next sequence
            starts a fresh run.
            """
            await self.orch.stop(reset_run_id=reset_run_id)
            return {}

        @self.post("/clear_estop", tags=["private"])
        async def clear_estop():
            """Clear the orchestrator's E-STOP latch when in the estopped state."""
            if self.orch.globalstatusmodel.loop_state != LoopStatus.estopped:
                LOGGER.info("orchestrator is not currently in E-STOP")
            else:
                await self.orch.clear_estop()

        @self.post("/clear_error", tags=["private"])
        async def clear_error():
            """Clear the orchestrator's error state when it is in the error state."""
            if self.orch.globalstatusmodel.loop_state != LoopStatus.error:
                LOGGER.info("orchestrator is not currently in ERROR")
            else:
                await self.orch.clear_error()

        @self.post("/skip_experiment", tags=["private"])
        async def skip_experiment():
            """Request the orchestrator to skip the current experiment."""
            await self.orch.skip()
            return {}

        @self.post("/clear_actions", tags=["private"])
        async def clear_actions():
            """Empty the orchestrator's action queue."""
            await self.orch.clear_actions()
            return {}

        @self.post("/clear_experiments", tags=["private"])
        async def clear_experiments():
            """Empty the orchestrator's experiment queue."""
            await self.orch.clear_experiments()
            return {}

        @self.post("/append_sequence", tags=["private"])
        async def append_sequence(sequence: Sequence = Body({}, embed=True)):
            """Append a sequence to the orchestrator and return its UUID."""
            if not isinstance(sequence, Sequence):
                sequence = Sequence(**sequence)
            seq_uuid = await self.orch.add_sequence(sequence=sequence)
            return {"sequence_uuid": seq_uuid}

        @self.post("/prepend_sequences", tags=["private"])
        async def prepend_sequences(sequences: List[Sequence] = Body([], embed=True)):
            """Prepend a list of sequences to the front of the orch queue."""
            uuids = await _prepend_sequences(self.orch, sequences)
            return {"sequence_uuids": uuids}

        @self.post("/move_sequence", tags=["private"])
        async def move_sequence(from_idx: int, to_idx: int):
            """Move a queued sequence from one index to another."""
            await self.orch.move_sequence(from_idx, to_idx)
            return {"n_sequences": len(self.orch.sequence_dq)}

        @self.post("/remove_sequence", tags=["private"])
        async def remove_sequence(idx: int):
            """Remove a queued sequence by index."""
            await self.orch.remove_sequence(idx)
            return {"n_sequences": len(self.orch.sequence_dq)}

        @self.post("/move_experiment", tags=["private"])
        async def move_experiment(from_idx: int, to_idx: int):
            """Move a queued experiment from one index to another."""
            await self.orch.move_experiment(from_idx, to_idx)
            return {"n_experiments": len(self.orch.experiment_dq)}

        @self.post("/remove_experiment", tags=["private"])
        async def remove_experiment(idx: int):
            """Remove a queued experiment by index."""
            await self.orch.remove_experiment(idx)
            return {"n_experiments": len(self.orch.experiment_dq)}

        @self.post("/move_action", tags=["private"])
        async def move_action(from_idx: int, to_idx: int):
            """Move a queued action from one index to another."""
            await self.orch.move_action(from_idx, to_idx)
            return {"n_actions": len(self.orch.action_dq)}

        @self.post("/remove_action", tags=["private"])
        async def remove_action(idx: int):
            """Remove a queued action by index."""
            await self.orch.remove_action(idx)
            return {"n_actions": len(self.orch.action_dq)}

        @self.post("/get_queue_object", tags=["private"])
        def get_queue_object(kind: str, idx: int):
            """Return the full dict for a queued sequence/experiment/action."""
            return _queue_object_payload(self.orch, kind, idx)

        @self.post("/append_experiment", tags=["private"])
        async def append_experiment(experiment: Experiment = Body({}, embed=True)):
            """Append an experiment to the active sequence and return its UUID."""
            exp_uuid = await self.orch.add_experiment(
                seq=self.orch.seq_model, experimentmodel=experiment.get_exp()
            )
            return {"experiment_uuid": exp_uuid}

        @self.post("/prepend_experiment", tags=["private"])
        async def prepend_experiment(experiment: Experiment = Body({}, embed=True)):
            """Prepend an experiment to the active sequence and return its UUID."""
            exp_uuid = await self.orch.add_experiment(
                seq=self.orch.seq_model,
                experimentmodel=experiment.get_exp(),
                prepend=True,
            )
            return {"experiment_uuid": exp_uuid}

        @self.post("/insert_experiment", tags=["private"])
        async def insert_experiment(
            experiment: Experiment = Body({}, embed=True),
            idx: int = 0,
        ):
            """Insert an experiment into the active sequence at ``idx`` and return its UUID."""
            exp_uuid = await self.orch.add_experiment(
                seq=self.orch.seq_model,
                experimentmodel=experiment.get_exp(),
                at_index=idx,
            )
            return {"experiment_uuid": exp_uuid}

        @self.post("/list_sequences", tags=["private"])
        def list_sequences():
            """Return the queued sequences."""
            return self.orch.list_sequences()

        @self.post("/list_experiments", tags=["private"])
        def list_experiments():
            """Return the queued experiments."""
            return self.orch.list_experiments()

        @self.post("/list_all_experiments", tags=["private"])
        def list_all_experiments():
            """Return ``(index, name)`` tuples for every queued experiment."""
            return self.orch.list_all_experiments()

        @self.post("/drop_experiment_inds", tags=["private"])
        def drop_experiment_inds(inds: List[int]):
            """Drop queued experiments at the given indices and return the remaining queue."""
            return self.orch.drop_experiment_inds(inds)

        @self.post("/drop_experiment_range", tags=["private"])
        def drop_experiment_range(lower: int, upper: int):
            """Drop queued experiments in the inclusive ``[lower, upper]`` range."""
            inds = list(range(lower, upper + 1))
            return self.orch.drop_experiment_inds(inds)

        @self.post("/active_experiment", tags=["private"])
        def active_experiment():
            """Return the orchestrator's currently active experiment."""
            return self.orch.get_experiment(last=False)

        @self.post("/last_experiment", tags=["private"])
        def last_experiment():
            """Return the orchestrator's most recently finished experiment."""
            return self.orch.get_experiment(last=True)

        @self.post("/list_actions", tags=["private"])
        def list_actions():
            """Return the queued actions."""
            return self.orch.list_actions()

        @self.post("/list_active_actions", tags=["private"])
        def list_active_actions():
            """Return the currently active actions."""
            return self.orch.list_active_actions()

        @self.post("/list_nonblocking", tags=["private"])
        def list_non_blocking():
            """Return tracked non-blocking executor identifiers."""
            return self.orch.nonblocking

        @self.post("/get_orch_state", tags=["private"])
        def get_orch_state() -> dict:
            """Return a snapshot of the orchestrator's loop state and active/last queues."""

            resp = {
                "orch_state": self.orch.globalstatusmodel.orch_state,
                "loop_state": self.orch.globalstatusmodel.loop_state,
                "loop_intent": self.orch.globalstatusmodel.loop_intent,
            }

            active_seq = self.orch.get_sequence()
            last_seq = self.orch.get_sequence(last=True)
            active_exp = self.orch.get_experiment()
            last_exp = self.orch.get_experiment(last=True)

            resp["active_sequence"] = active_seq.clean_dict() if active_seq else {}
            resp["last_sequence"] = last_seq.clean_dict() if last_seq else {}
            resp["active_experiment"] = active_exp.clean_dict() if active_exp else {}
            resp["last_experiment"] = last_exp.clean_dict() if last_exp else {}

            resp.update(_queue_counts(self.orch))
            resp["current_stop_message"] = self.orch.current_stop_message

            return resp

        @self.post("/get_histories", tags=["private"])
        def get_histories():
            """Return action/experiment/sequence history item lists."""
            return _histories_payload(self.orch)

        @self.post("/get_status_summary", tags=["private"])
        def get_status_summary():
            """Return the per-server (server_status, driver_status) summary."""
            return _status_summary_payload(self.orch)

        @self.post("/get_step_flags", tags=["private"])
        def get_step_flags():
            """Return the orchestrator's step-through flags."""
            return _step_flags_payload(self.orch)

        @self.post("/set_step_flag", tags=["private"])
        def set_step_flag(kind: str, value: bool):
            """Set a single step-through flag and return its new value."""
            return _set_step_flag(self.orch, kind, value)

        @self.post("/clear_sequences", tags=["private"])
        async def clear_sequences():
            """Empty the orchestrator's sequence queue."""
            await self.orch.clear_sequences()
            return {}

        @self.post("/append_split_sequences", tags=["private"])
        async def append_split_sequences(sequence: Sequence = Body({}, embed=True)):
            """Split a sequence by sample and append the sub-sequences; return their UUIDs."""
            if not isinstance(sequence, Sequence):
                sequence = Sequence(**sequence)
            result = await self.orch.add_split_sequences(sequence=sequence)
            return {"sequence_uuids": result}

        @self.post("/latest_sequence_uuids", tags=["private"])
        def latest_sequence_uuids():
            """Return the orchestrator's recent dispatched sequence UUIDs."""
            return list(self.orch.sequence_history.keys())[-50:]

        @self.post("/latest_experiment_uuids", tags=["private"])
        def latest_experiment_uuids():
            """Return the orchestrator's recent dispatched experiment UUIDs."""
            return list(self.orch.experiment_history.keys())[-50:]

        @self.post("/latest_action_uuids", tags=["private"])
        def latest_action_uuids():
            """Return the orchestrator's recent dispatched action UUIDs."""
            return list(self.orch.action_history.keys())[-50:]

        @self.post(f"/{server_key}/wait", tags=["action"])
        async def wait(
            waittime: float = 10.0,
        ):
            """Action endpoint that sleeps ``waittime`` seconds via a ``WaitExec`` executor."""
            active = await self.orch.setup_and_contain_action()
            active.action.action_abbr = "wait"
            executor = WaitExec(
                active=active,
                oneoff=False,
            )
            active_action_dict = active.start_executor(executor)
            return active_action_dict

        @self.post(f"/{server_key}/cancel_wait", tags=["action"])
        async def cancel_wait(
        ):
            """Action endpoint that stops every running ``wait`` executor and finishes the action."""
            active = await self.orch.setup_and_contain_action()
            for exec_id, executor in self.orch.executors.items():
                if exec_id.split()[0] == "wait":
                    executor.stop_action_task()
            finished_action = await active.finish()
            return finished_action.as_dict()

        @self.post(f"/{server_key}/interrupt", tags=["action"])
        async def interrupt(
            reason: str = "wait",
        ):
            """Action endpoint that stops the orchestrator with the supplied ``reason`` and finishes."""
            active = await self.orch.setup_and_contain_action()
            self.orch.current_stop_message = active.action.action_params["reason"]
            LOGGER.warning(active.action.action_params["reason"])
            await self.orch.stop()
            finished_action = await active.finish()
            return finished_action.as_dict()

        @self.post(f"/{server_key}/estop", tags=["action"])
        async def estop(
            switch: bool = True,
        ):
            """Trigger emergency stop on the orchestrator.

            Invokes the driver estop hook (if any), latches the E-STOP flag,
            stops all executors, and finalizes any in-flight actions with
            ``estopped`` status. Like the action-server ``/estop``, this no longer
            fabricates a placeholder ``estop`` action; the orchestrator is in its
            own ``server_dict`` and ``estop_actions`` dispatches here too, so
            fabricating would reintroduce the very artifact being removed.
            """
            has_estop = getattr(self.driver, "estop", None)
            driver_resp = None
            if has_estop is not None and callable(has_estop):
                LOGGER.info("driver has estop function")
                driver_resp = await self.driver.estop(switch=switch)
            else:
                LOGGER.info("driver has NO estop function")
            self.orch.actionservermodel.estop = switch
            for k in list(self.orch.executors):
                self.orch.stop_executor(k)
            estopped_actions = await self.orch.estop_actives()
            return {
                "estop": switch,
                "estopped_actions": estopped_actions,
                "driver": driver_resp,
            }

        @self.post(f"/{server_key}/conditional_exp", tags=["action"])
        async def conditional_exp(
            check_parameter: Optional[str] = "",
            check_condition: checkcond = checkcond.equals,
            check_value: Union[float, int, bool] = True,
            conditional_experiment_name: str = "",
            conditional_experiment_params: dict = {},
        ):
            """Action endpoint that prepends ``conditional_experiment_name`` when ``check_parameter`` satisfies ``check_condition`` against ``check_value``."""
            active = await self.orch.setup_and_contain_action()
            experiment_model = Experiment(
                experiment_name=active.action.action_params[
                    "conditional_experiment_name"
                ],
                experiment_params=active.action.action_params[
                    "conditional_experiment_params"
                ],
            )
            cond = active.action.action_params["check_condition"]
            check_key = active.action.action_params.get("check_parameter") or ""
            # Prefer orchestrator global_params (e.g. Ewe_V__mean_final from last run_CP);
            # action_params may omit values if the HTTP payload did not round-trip globals.
            param = None
            if check_key:
                param = self.orch.global_params.get(check_key)
                if param is None:
                    param = active.action.action_params.get(check_key)
            thresh = active.action.action_params["check_value"]
            check = False
            if cond == checkcond.uncond:
                check = True
            elif cond is None:
                check = False
            elif param is None:
                LOGGER.warning(
                    "conditional_exp: parameter %r is missing (not in global_params or "
                    "action_params); condition cannot be evaluated -> treating as False.",
                    check_key,
                )
                check = False
            elif cond == checkcond.equals:
                check = param == thresh
            elif cond == checkcond.above:
                check = param > thresh
            elif cond == checkcond.below:
                check = param < thresh
            elif cond == checkcond.isnot:
                check = param != thresh

            if check:
                await self.orch.add_experiment(
                    seq=self.orch.seq_model,
                    experimentmodel=experiment_model,
                    prepend=True,
                )
            finished_action = await active.finish()
            return finished_action.as_dict()

        @self.post(f"/{server_key}/conditional_stop", tags=["action"])
        @action_version(2)
        async def conditional_stop(
            stop_parameter: Optional[str] = "",
            stop_condition: checkcond = checkcond.equals,
            stop_value: Union[str, float, int, bool] = True,
            reason: str = "conditional stop",
            clear_queues: bool = False,
        ):
            """Action endpoint that stops the orchestrator (and optionally clears all queues) when ``stop_parameter`` satisfies ``stop_condition`` against ``stop_value``."""
            active = await self.orch.setup_and_contain_action()
            cond = active.action.action_params["stop_condition"]
            param = active.action.action_params.get(
                active.action.action_params["stop_parameter"], None
            )
            thresh = active.action.action_params["stop_value"]
            stop = False
            if cond == checkcond.equals:
                stop = param == thresh
            elif cond == checkcond.above:
                stop = param > thresh
            elif cond == checkcond.below:
                stop = param < thresh
            elif cond == checkcond.isnot:
                stop = param != thresh
            elif cond == checkcond.uncond:
                stop = True
            elif cond is None:
                stop = False

            if stop:
                if active.action.action_params["clear_queues"]:
                    await self.orch.clear_actions()
                    await self.orch.clear_experiments()
                    await self.orch.clear_sequences()
                await self.orch.stop()
                self.orch.current_stop_message = active.action.action_params["reason"]
                LOGGER.warning(active.action.action_params["reason"])
                LOGGER.alert(f"ORCH STOPPED ~ {active.action.action_params['reason']}")

            finished_action = await active.finish()
            return finished_action.as_dict()

        @self.post(f"/{server_key}/conditional_skip", tags=["action"])
        async def conditional_skip(
            skip_parameter: Optional[str] = "",
            skip_condition: checkcond = checkcond.equals,
            skip_value: Union[str, float, int, bool] = True,
            skip_queued_actions: bool = True,
            skip_queued_experiments: bool = False,
            reason: str = "conditional skip",
        ):
            """Action endpoint that clears queued actions and/or experiments when ``skip_parameter`` satisfies ``skip_condition`` against ``skip_value``."""
            active = await self.orch.setup_and_contain_action()
            cond = active.action.action_params["skip_condition"]
            param = active.action.action_params.get(
                active.action.action_params["skip_parameter"], None
            )
            thresh = active.action.action_params["skip_value"]
            skip = False
            if cond == checkcond.equals:
                skip = param == thresh
            elif cond == checkcond.above:
                skip = param > thresh
            elif cond == checkcond.below:
                skip = param < thresh
            elif cond == checkcond.isnot:
                skip = param != thresh
            elif cond == checkcond.uncond:
                skip = True
            elif cond is None:
                skip = False

            if skip:
                if active.action.action_params["skip_queued_actions"]:
                    await self.orch.clear_actions()
                if active.action.action_params["skip_queued_experiments"]:
                    await self.orch.clear_experiments()

            finished_action = await active.finish()
            return finished_action.as_dict()

        @self.post(f"/{server_key}/add_global_param", tags=["action"])
        async def add_global_param(
            param_name: str = "global_param_test",
            param_value: Union[str, float, int, bool] = True,
        ):
            """Action endpoint that writes ``param_name=param_value`` into the orchestrator's ``global_params``."""
            active = await self.orch.setup_and_contain_action()
            pdict = {
                active.action.action_params["param_name"]: active.action.action_params[
                    "param_value"
                ]
            }
            active.action.action_params.update(pdict)
            # active.action.to_global_params = list(pdict.keys())
            self.orch.global_params.update(pdict)
            finished_action = await active.finish()
            return finished_action.as_dict()

        _register_utility_endpoints(self)

        @self.post("/clear_global_params_private", tags=["private"])
        def clear_global_params_private():
            """Reset ``global_params`` to an empty dict and return a summary message."""
            current_params = list(self.orch.global_params.keys())
            self.orch.global_params = {}
            if current_params:
                return "\n".join(["removed:"] + current_params)
            else:
                return "global_params was empty"

        @self.post("/get_global_params", tags=["private"])
        def get_global_params():
            """Return the orchestrator's ``global_params`` dictionary."""
            return self.orch.global_params

        @self.post(f"/{server_key}/clear_global_params", tags=["action"])
        async def clear_global_params():
            """Action endpoint that clears the orchestrator's ``global_params`` and records the removed keys."""
            active = await self.orch.setup_and_contain_action()
            current_params = list(self.orch.global_params.keys())
            self.orch.global_params = {}
            if current_params:
                self.orch.print_message(
                    "\n".join(["removed:"] + current_params), info=True
                )
            else:
                LOGGER.info("global_params was empty")
            active.action.action_params.update({"cleared": current_params})
            finished_action = await active.finish()
            return finished_action.as_dict()

        @self.on_event("shutdown")
        async def shutdown_event():
            """Stop the orchestrator on application shutdown."""
            LOGGER.info("orch shutdown")
            await self.orch.shutdown()
            time.sleep(0.75)


class WaitExec(Executor):
    """Executor implementing the orchestrator's ``wait`` action via polled timing."""

    def __init__(self, *args, **kwargs):
        """Initialize the wait executor from the active action's ``waittime`` parameter.

        Args:
            *args: Positional arguments forwarded to :class:`Executor`.
            **kwargs: Keyword arguments forwarded to :class:`Executor`; recognises
                ``print_every_secs`` to control the progress log cadence.
        """
        super().__init__(*args, **kwargs)
        LOGGER.info("WaitExec initialized.")
        self.poll_rate = 0.01
        self.duration = self.active.action.action_params.get("waittime", -1)
        self.print_every_secs = kwargs.get("print_every_secs", 5)
        self.start_time = time.time()
        self.last_print_time = self.start_time

    async def _exec(self):
        """Log the wait duration and return an empty success result."""
        LOGGER.info(f" ... wait action: {self.duration}")
        return {"data": {}, "error": ErrorCodes.none}

    async def _poll(self):
        """Track elapsed time, log progress, and finish once the configured duration elapses."""
        check_time = time.time()
        elapsed_time = check_time - self.start_time
        if check_time - self.last_print_time > self.print_every_secs - 0.01:
            LOGGER.info(
                f" ... orch waited {elapsed_time:.1f} sec / {self.duration:.1f} sec"
            )
            self.last_print_time = check_time
        if (self.duration < 0) or (elapsed_time < self.duration):
            status = HloStatus.active
        else:
            status = HloStatus.finished
        await asyncio.sleep(0.001)
        return {"error": ErrorCodes.none, "status": status}

    async def _post_exec(self):
        """Log completion and return a success result."""
        LOGGER.info(" ... wait action done")
        return {"error": ErrorCodes.none}


class checkcond(str, Enum):
    """Comparison conditions supported by the orchestrator's conditional action endpoints."""

    equals = "equals"
    below = "below"
    above = "above"
    isnot = "isnot"
    uncond = "uncond"
