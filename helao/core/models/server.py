"""Models describing per-endpoint, per-server, and orchestrator-wide live status."""

__all__ = [
    "ActionServerModel",
    "GlobalStatusModel",
]

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from helao.core.helaodict import HelaoDict
from helao.helpers.premodels import Action

from .hlostatus import HloStatus
from .machine import MachineModel
from .orchstatus import LoopIntent, LoopStatus, OrchStatus

# additional finished categories which contain one of these
# will be added to their own categories, sequence defines priority
# all of these need additional "finish" else the action is still "active"
# main_finished_status = [HloStatus.estopped, HloStatus.errored]
main_finished_status = [HloStatus.errored]


class EndpointModel(BaseModel, HelaoDict):
    """Live status of one endpoint on an action server.

    Attributes:
        endpoint_name (str): Endpoint (action) name.
        active_dict (dict[UUID, Action]): Active actions keyed by UUID.
        nonactive_dict (dict[HloStatus, dict[UUID, Action]]): Finished actions
            bucketed by status (``finished`` plus any `main_finished_status`).
        max_uuids (Optional[int]): Optional cap on retained UUIDs; `None` means unbounded.
    """

    endpoint_name: str
    # status is a dict (keyed by action uuid)
    # which hold a dict of active actions
    active_dict: dict[UUID, Action] = Field(default={})

    # holds the finished uuids
    # keyed by either main_finished_status or "finished"
    nonactive_dict: dict[HloStatus, dict[UUID, Action]] = Field(default={})

    # none is infinite
    max_uuids: Optional[int] = None
    # todo: - add local queue and priority lists here?

    def __str__(self) -> str:
        """Return a compact ``active:[...], finished:[...]`` summary string."""
        finished_uuids = [
            uuid.hex for uuid in self.nonactive_dict.get(HloStatus.finished, {}).keys()
        ]
        return f"active:{[uuid.hex for uuid in self.active_dict.keys()]}, finished:{finished_uuids}"

    def __repr__(self) -> str:
        """Return the angle-bracketed `str()` rendering."""
        return f"<{self.__str__()}>"

    def sort_status(self):
        """Move finished actions out of `active_dict` into the appropriate `nonactive_dict` buckets."""
        del_keys = []
        if HloStatus.finished not in self.nonactive_dict:
            self.nonactive_dict[HloStatus.finished] = {}
        for uuid, status in self.active_dict.items():
            # print(uuid, status.action_status)
            # check if action is finished
            if HloStatus.finished in status.action_status:
                del_keys.append(uuid)

                # is_sub_status = False
                for hlostatus in main_finished_status:
                    if hlostatus in status.action_status:
                        if hlostatus not in self.nonactive_dict:
                            # is_sub_status = True
                            self.nonactive_dict[hlostatus] = {}
                            break
                        self.nonactive_dict[hlostatus].update({uuid: status})

                # # no main substatus, add it under finished key
                # if not is_sub_status:
                # also always add it to finished
                self.nonactive_dict[HloStatus.finished].update({uuid: status})

        # delete all finished actions from active_dict
        for key in del_keys:
            del self.active_dict[key]

    def clear_finished(self):
        """Reset `nonactive_dict` to an empty `finished` bucket, leaving `active_dict` untouched."""
        self.nonactive_dict = {}
        self.nonactive_dict[HloStatus.finished] = {}


class ActionServerModel(BaseModel, HelaoDict):
    """Live status snapshot of a single action server and its endpoints.

    Attributes:
        action_server (MachineModel): Identity of the server.
        endpoints (dict[str, EndpointModel]): Per-endpoint status keyed by endpoint name.
        estop (bool): True if the server has signalled an emergency stop.
        last_action_uuid (Optional[UUID]): UUID of the most recently dispatched action.
    """

    action_server: MachineModel
    # endpoints keyed by the name of the endpoint (action_name)
    endpoints: dict[str, EndpointModel] = Field(default={})
    # signals estop of the action server
    estop: bool = False
    last_action_uuid: Optional[UUID] = None

    def get_fastapi_json(self, action_name: Optional[str] = None) -> dict:
        """Return a serializable dict for the whole server or a single endpoint.

        Args:
            action_name: If given, restrict the payload to that endpoint;
                otherwise include all endpoints.

        Returns:
            Dict representation suitable for FastAPI JSON responses.
        """
        json_dict = {}
        if action_name is None:
            # send all
            json_dict = self.as_dict()
        else:
            # send only selected endpoint status
            if action_name in self.endpoints:
                json_dict = ActionServerModel(
                    action_server=self.action_server,
                    # status_msg should be a Action
                    endpoints={action_name: self.endpoints[action_name]},
                    last_action_uuid=self.last_action_uuid,
                ).as_dict()

        return json_dict

    def init_endpoints(self):
        """Reset finished buckets on every endpoint (called when (re)initializing the server)."""
        for _, endpoint in self.endpoints.items():
            endpoint.clear_finished()


class GlobalStatusModel(BaseModel, HelaoDict):
    """Per-orchestrator aggregate of all known action-server statuses.

    Attributes:
        orchestrator (MachineModel): Identity of the owning orchestrator.
        server_dict (dict[tuple, ActionServerModel]): Action server status keyed by
            `MachineModel.as_key()`.
        active_dict (dict[UUID, Action]): All active actions for this orch.
        nonactive_dict (dict[HloStatus, dict[UUID, Action]]): Finished actions
            bucketed by status.
        loop_intent (LoopIntent): Requested loop transition.
        loop_state (LoopStatus): Current dispatch-loop state.
        orch_state (OrchStatus): Orchestrator top-level state.
        counter_dispatched_actions (dict[UUID, int]): Dispatch counters keyed by experiment UUID.
    """

    orchestrator: MachineModel
    # a dict of actionserversmodels keyed by the server name
    # use MachineModel.as_key() for the dict key
    server_dict: dict[tuple, ActionServerModel] = Field(default={})

    # a dict of all active actions for this orch
    active_dict: dict[UUID, Action] = Field(default={})
    # a dict of all finished actions
    # keyed by either main_finished_status or "finished"
    nonactive_dict: dict[HloStatus, dict[UUID, Action]] = Field(default={})

    # some control parameters for the orch

    # new intented state for the dispatch loop
    loop_intent: LoopIntent = LoopIntent.none
    # the dispatch loop state
    loop_state: LoopStatus = LoopStatus.stopped
    # the state of the orch
    orch_state: OrchStatus = OrchStatus.idle
    # counter for dispatched actions, keyed by experiment uuid
    counter_dispatched_actions: dict[UUID, int] = Field(default={})

    def as_json(self) -> dict:
        """Return a JSON-friendly dict with `server_dict` keys flattened to ``server@machine`` strings."""
        json_dict = {
            k: vars(self)[k]
            for k in (
                "orchestrator",
                "active_dict",
                "nonactive_dict",
                "loop_intent",
                "loop_state",
                "orch_state",
                "counter_dispatched_actions",
            )
        }
        json_dict["server_dict"] = {
            f"{k[0]}@{k[1]}": v for k, v in self.server_dict.items()
        }
        return json_dict

    def actions_idle(self) -> bool:
        """Return True if no action is active for this orchestrator."""
        if self.active_dict:
            return False
        else:
            return True

    def server_free(
        self,
        action_server: MachineModel,
    ) -> bool:
        """Return True if `action_server` has no active actions belonging to this orchestrator."""
        free = True
        if action_server.as_key() in self.server_dict:
            actionservermodel = self.server_dict[action_server.as_key()]
            for _, endpointmodel in actionservermodel.endpoints.items():
                # loop through all of its active uuids
                for _, statusmodel in endpointmodel.active_dict.items():
                    if statusmodel.orchestrator == self.orchestrator:
                        # found an acive action for this orch
                        # endpoint is not yet free for this orch
                        free = False
                        break
        return free

    def endpoint_free(self, action_server: MachineModel, endpoint_name: str) -> bool:
        """Return True if `endpoint_name` on `action_server` has no active actions for this orchestrator."""
        free = True
        # check if the actio server is registered for this orch
        # if action_server.server_name in self.server_dict:
        if action_server.as_key() in self.server_dict:
            actionservermodel = self.server_dict[action_server.as_key()]
            # check if the action server has the requested endpoint
            if endpoint_name in actionservermodel.endpoints.keys():
                endpointmodel = actionservermodel.endpoints[endpoint_name]
                # loop through all of its active uuids
                for _, statusmodel in endpointmodel.active_dict.items():
                    if statusmodel.orchestrator == self.orchestrator:
                        # found an acive action for this orch
                        # endpoint is not yet free for this orch
                        free = False
                        break

        return free

    def _sort_status(self) -> list:
        """Move actions from `server_dict` endpoints into this orch's active/nonactive dicts.

        Returns:
            A list of ``(uuid, status_name)`` tuples for actions that newly
            transitioned out of `active_dict`.
        """
        recent_nonactive = []

        # loop through all servers
        for action_server, actionservermodel in self.server_dict.items():
            # loop through all endpoints on this server
            for action_name, endpointmodel in actionservermodel.endpoints.items():
                endpointmodel.sort_status()
                # loop through all active uuids on this endpoint
                for uuid, statusmodel in endpointmodel.active_dict.items():
                    if statusmodel.orchestrator == self.orchestrator:
                        self.active_dict.update({uuid: statusmodel})
                # loop through all finished uuids on this endpoint
                for hlostatus, status_dict in endpointmodel.nonactive_dict.items():
                    for uuid, statusmodel in status_dict.items():
                        if statusmodel.orchestrator == self.orchestrator:
                            # check if its in active and remove it from there first
                            if uuid in self.active_dict:
                                del self.active_dict[uuid]
                                recent_nonactive.append((uuid, hlostatus.name))
                            if hlostatus not in self.nonactive_dict:
                                self.nonactive_dict[hlostatus] = {}
                            self.nonactive_dict[hlostatus].update({uuid: statusmodel})
        return recent_nonactive

    def update_global_with_acts(self, actionservermodel: ActionServerModel) -> list:
        """Merge an incoming `ActionServerModel` into `server_dict` and re-sort statuses.

        Args:
            actionservermodel: Latest status snapshot from one action server.

        Returns:
            Same as `_sort_status`: tuples of newly-finished ``(uuid, status_name)``.
        """
        if actionservermodel.action_server.as_key() not in self.server_dict:
            # add it for the first time
            self.server_dict.update(
                {actionservermodel.action_server.as_key(): actionservermodel}
            )
        else:
            self.server_dict[actionservermodel.action_server.as_key()].endpoints.update(
                actionservermodel.endpoints
            )
        # sort it into active and finished
        recent_nonactive = self._sort_status()
        return recent_nonactive

    def find_hlostatus_in_finished(self, hlostatus: HloStatus) -> dict[UUID, Action]:
        """Return finished actions whose status set contains `hlostatus`."""
        uuid_dict = {}

        if hlostatus in self.nonactive_dict:
            # all of them have this status
            for uuid, statusmodel in self.nonactive_dict[hlostatus].items():
                uuid_dict.update({uuid: statusmodel})
        elif HloStatus.finished in self.nonactive_dict:
            # can only be in finsihed, but need to look for substatus
            for uuid, statusmodel in self.nonactive_dict[HloStatus.finished].items():
                if hlostatus in statusmodel.action_status:
                    uuid_dict.update({uuid: statusmodel})

        return uuid_dict

    def clear_in_finished(self, hlostatus: HloStatus):
        """Clear the bucket of finished actions associated with `hlostatus`."""
        if hlostatus in self.nonactive_dict:
            self.nonactive_dict[hlostatus] = {}
        elif HloStatus.finished in self.nonactive_dict:
            # can only be in finished; clear the whole finished bucket.
            # (Was: `for key in ....keys(): del ....[key]`, which raised
            # "dictionary changed size during iteration" whenever the bucket
            # was non-empty — a live RuntimeError on the clear_estop path.)
            self.nonactive_dict[HloStatus.finished] = {}

    def new_experiment(self, exp_uuid: UUID):
        """Initialize the dispatched-action counter for a new experiment."""
        self.counter_dispatched_actions[exp_uuid] = 0

    def finish_experiment(self, exp_uuid: UUID) -> list[Action]:
        """Return all finished actions for `exp_uuid` and clear the nonactive buckets and counter."""
        # we don't filter by orch as this should have happened already when they
        # were added to the finished_exps
        finished_acts = []
        finished_uuids = []
        for _, status_dict in self.nonactive_dict.items():
            for action_uuid, statusmodel in status_dict.items():
                if (
                    exp_uuid == statusmodel.experiment_uuid
                    and action_uuid not in finished_uuids
                ):
                    finished_acts.append(statusmodel)
                    finished_uuids.append(action_uuid)
        # TODO: properly clear actions from endpointstatusmodel only for exp_uuid

        # if self.active_dict:
        #     ERROR

        # clear finished
        self.nonactive_dict = {}
        if exp_uuid in self.counter_dispatched_actions:
            del self.counter_dispatched_actions[exp_uuid]

        return finished_acts
