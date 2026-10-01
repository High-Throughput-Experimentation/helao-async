"""Status ingestion collaborator extracted from ``Orch`` (CARDS P5, Stage S4).

``Orch.update_status``/``Orch.update_nonblocking``/``Orch.clear_nonblocking``
implement the orchestrator's status-ingestion "cluster C": merging every
reported ``ActionServerModel`` into the ``GlobalStatusModel``, tracking
non-blocking executors, and reacting to e-stop/error conditions. This module
moves those method bodies into a ``StatusIngester`` collaborator that the
orchestrator delegates to. (It also held ``ws_globstat`` and
``globstat_broadcast_task``, a ``/ws_globstat`` sender that never had a
route; B7b deleted both with ``globstat_q``.)

Per the P5 constraints (:doc:`CARDS_REFACTOR_P5.md` sec 3.1 rule 3):
``StatusIngester`` caches no shared mutable state -- it holds only the
``orch`` back-reference and reads/writes ``globalstatusmodel``, ``nonblocking``,
``active_experiment``/``active_sequence`` and ``interrupt_q``
through it at call time, so a reassignment made between construction and a
call (e.g. ``import_queues`` reassigning ``globalstatusmodel``) is always
observed. Behavior is byte-identical to the original inline methods,
including the exact ``aiolock`` critical section in ``update_status`` and the
uuid-registration side effect shared with ``update_nonblocking``.

Lock/queue ownership (rule 4) -- full map (also duplicated verbatim in
``orch_dispatch.py``, the other lock owner):

- ``aiolock`` -- acquired by ``StatusIngester`` (status ingestion) and
  ``DispatchRunner`` (the dispatch critical section).
- ``interrupt_q`` -- written by ``StatusIngester`` / ``ServerMonitor`` /
  e-stop; read by ``DispatchRunner``.

Concretely here: ``aiolock`` is acquired inside ``update_status`` exactly
where the original method acquired it (no await added or removed);
``interrupt_q`` is written by ``update_status`` and ``update_nonblocking``
(read by ``Orch.wait_for_interrupt``, which ``DispatchRunner`` calls from its
dispatch loop -- ``wait_for_interrupt`` itself remains an ``Orch`` method,
cluster B, not yet extracted). ``update_status`` can trigger ``orch.estop_loop``
(cluster E, stays on ``Orch``) when an action's status carries
``HloStatus.estopped``.
"""

from typing import Optional

from helao.core.models.hlostatus import HloStatus
from helao.core.models.orchstatus import LoopStatus, OrchStatus
from helao.core.models.server import ActionServerModel
from helao.helpers import helao_logging as logging
from helao.helpers.dispatcher import async_private_dispatcher
from helao.helpers.premodels import Action

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class StatusIngester:
    """Status-ingestion and WS-broadcast methods for an ``Orch``.

    Holds only the ``orch`` back-reference (never a cached deque/attribute/task
    handle), per the call-time state resolution rule -- see module docstring.
    """

    def __init__(self, orch):
        self.orch = orch

    async def update_nonblocking(
        self, actionmodel: Action, server_host: str, server_port: int
    ) -> dict:
        """Record a non-blocking action transition and nudge the dispatch loop.

        Args:
            actionmodel: ``Action`` describing the non-blocking event.
            server_host: Host of the action server reporting the event.
            server_port: Port of the action server reporting the event.

        Returns:
            ``{"success": True}`` once the action's executor id has been
            added or removed from ``self.nonblocking``.
        """
        orch = self.orch
        # print(actionmodel.clean_dict())

        if (
            orch.active_experiment is not None
            and orch.active_experiment.experiment_uuid == actionmodel.experiment_uuid
        ):
            matching_experiment = True
        else:
            matching_experiment = False
        orch.register_action_uuid(
            actionmodel.action_uuid,
            {
                "action_name": actionmodel.action_name,
                "action_params": actionmodel.action_params,
                "action_status": actionmodel.action_status,
                "action_server": actionmodel.action_server.server_name,
                "action_timestamp": f"{actionmodel.action_timestamp: %m-%d %H:%M:%S}",
                "action_finished_timestamp": (
                    f"{actionmodel.action_finished_timestamp: %m-%d %H:%M:%S}"
                    if actionmodel.action_finished_timestamp is not None
                    else None
                ),
                "experiment_name": (
                    orch.active_experiment.experiment_name
                    if matching_experiment
                    else None
                ),
                "experiment_uuid": actionmodel.experiment_uuid,
                "sequence_name": (
                    orch.active_sequence.sequence_name
                    if orch.active_sequence is not None and matching_experiment
                    else None
                ),
                "sequence_label": (
                    orch.active_sequence.sequence_label
                    if orch.active_sequence is not None and matching_experiment
                    else None
                ),
                "sequence_uuid": (
                    orch.active_sequence.sequence_uuid
                    if orch.active_sequence is not None and matching_experiment
                    else None
                ),
            },
        )
        server_key = actionmodel.action_server.server_name
        server_exec_id = (server_key, actionmodel.exec_id, server_host, server_port)
        if "active" in actionmodel.action_status:
            orch.nonblocking.append(server_exec_id)
        else:
            orch.nonblocking.remove(server_exec_id)
        # put an empty object in interrupt_q to trigger orch dispatch loop
        await orch.interrupt_q.put(orch.globalstatusmodel)
        return {"success": True}

    async def clear_nonblocking(self) -> list:
        """Send ``stop_executor`` to every tracked non-blocking action and return their responses."""
        orch = self.orch
        resp_tups = []
        for server_key, exec_id, server_host, server_port in orch.nonblocking:
            LOGGER.info(
                f"Sending stop_executor request to {server_key} on {server_host}:{server_port} for executor {exec_id}"
            )
            # print(server_key, exec_id, server_host, server_port)
            response, error_code = await async_private_dispatcher(
                server_key=server_key,
                host=server_host,
                port=server_port,
                private_action="stop_executor",
                params_dict={"executor_id": exec_id},
                json_dict={},
            )
            resp_tups.append((response, error_code))
        return resp_tups

    async def update_status(
        self, actionservermodel: Optional[ActionServerModel] = None
    ) -> bool:
        """Merge an action-server status into the global status model and react to errors/estops.

        Updates the action history, tracks completed non-active actions in the
        live buffer, transitions the orchestrator to ``estopped``, ``error``,
        ``idle`` or ``busy`` as appropriate, and pushes the new status to the
        interrupt queue and Bokeh operator.

        Args:
            actionservermodel: Reported status from a remote action server.

        Returns:
            ``True`` if the model was applied, ``False`` if ``actionservermodel`` was ``None``.
        """
        orch = self.orch

        # LOGGER.debug(
        #     f"received status from server: {actionservermodel.action_server.server_name}"
        # )

        if actionservermodel is None:
            return False

        async with orch.aiolock:
            # update GlobalStatusModel with new ActionServerModel
            # and sort the new status dict
            if actionservermodel.last_action_uuid is not None:
                # find last action uuid in action server model:
                for (
                    endpoint_name,
                    endpoint_model,
                ) in actionservermodel.endpoints.items():
                    # ACTIVE packages register too. The dispatch loop polls
                    # action_history for the uuid it just dispatched, so
                    # registering only terminal actions makes every dispatch
                    # block until its own action finishes -- every
                    # start_condition then behaves like wait_for_all and
                    # no_wait can never overlap anything.
                    for act_dict in (
                        *endpoint_model.nonactive_dict.values(),
                        endpoint_model.active_dict,
                    ):
                        for act_uuid, act_model in act_dict.items():
                            if act_uuid == actionservermodel.last_action_uuid:
                                if (
                                    orch.active_experiment is not None
                                    and orch.active_experiment.experiment_uuid
                                    == act_model.experiment_uuid
                                ):
                                    matching_experiment = True
                                else:
                                    matching_experiment = False
                                orch.register_action_uuid(
                                    act_uuid,
                                    {
                                        "action_name": act_model.action_name,
                                        "action_params": act_model.action_params,
                                        "action_status": act_model.action_status,
                                        "action_server": act_model.action_server.server_name,
                                        "action_timestamp": f"{act_model.action_timestamp: %m-%d %H:%M:%S}",
                                        "action_finished_timestamp": (
                                            f"{act_model.action_finished_timestamp: %m-%d %H:%M:%S}"
                                            if act_model.action_finished_timestamp
                                            is not None
                                            else None
                                        ),
                                        "experiment_name": (
                                            orch.active_experiment.experiment_name
                                            if matching_experiment
                                            else None
                                        ),
                                        "experiment_uuid": act_model.experiment_uuid,
                                        "sequence_name": (
                                            orch.active_sequence.sequence_name
                                            if orch.active_sequence is not None
                                            and matching_experiment
                                            else None
                                        ),
                                        "sequence_label": (
                                            orch.active_sequence.sequence_label
                                            if orch.active_sequence is not None
                                            and matching_experiment
                                            else None
                                        ),
                                        "sequence_uuid": (
                                            orch.active_sequence.sequence_uuid
                                            if orch.active_sequence is not None
                                            and matching_experiment
                                            else None
                                        ),
                                    },
                                )
                                break

            recent_nonactive = orch.globalstatusmodel.update_global_with_acts(
                actionservermodel=actionservermodel
            )
            for act_uuid, act_status in recent_nonactive:
                await orch.put_lbuf({act_uuid: {"status": act_status}})

            # check if one action is in estop in the error list:
            estop_uuids = orch.globalstatusmodel.find_hlostatus_in_finished(
                hlostatus=HloStatus.estopped,
            )

            error_uuids = orch.globalstatusmodel.find_hlostatus_in_finished(
                hlostatus=HloStatus.errored,
            )

            if estop_uuids and orch.globalstatusmodel.loop_state == LoopStatus.started:
                await orch.estop_loop(reason=f"due to action uuid(s): {estop_uuids}")
            elif (
                error_uuids and orch.globalstatusmodel.loop_state == LoopStatus.started
            ):
                orch.globalstatusmodel.orch_state = OrchStatus.error
            elif not orch.globalstatusmodel.active_dict:
                # no uuids in active action dict
                orch.globalstatusmodel.orch_state = OrchStatus.idle
            else:
                orch.globalstatusmodel.orch_state = OrchStatus.busy
                LOGGER.info(f"running_states: {orch.globalstatusmodel.active_dict}")

            # now push it to the interrupt_q
            await orch.interrupt_q.put(orch.globalstatusmodel)

            return True
