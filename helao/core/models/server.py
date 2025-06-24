__all__ = [
    "ActionServerModel",
    "GlobalStatusModel",
]

from typing import Dict, Optional, Tuple, List
from uuid import UUID
from pydantic import BaseModel, Field


from helao.core.models.orchstatus import OrchStatus, LoopStatus, LoopIntent
from helao.core.models.machine import MachineModel
from helao.helpers.premodels import Action
from helao.core.models.hlostatus import HloStatus
from helao.core.helaodict import HelaoDict


# additional finished categories which contain one of these
# will be added to their own categories, sequence defines priority
# all of these need additional "finish" else the action is still "active"
# main_finished_status = [HloStatus.estopped, HloStatus.errored]
main_finished_status = [HloStatus.errored]


class EndpointModel(BaseModel, HelaoDict):
    endpoint_name: str
    # status is a dict (keyed by action uuid)
    # which hold a dict of active actions
    active_dict: Dict[UUID, Action] = Field(default={})

    # holds the finished uuids
    # keyed by either main_finished_status or "finished"
    nonactive_dict: Dict[HloStatus, Dict[UUID, Action]] = Field(default={})

    # none is infinite
    max_uuids: Optional[int] = None
    # todo: - add local queue and priority lists here?

    def __str__(self):
        finished_uuids = [uuid.hex for uuid in self.nonactive_dict.get(HloStatus.finished, {}).keys()]
        return f"active:{[uuid.hex for uuid in self.active_dict.keys()]}, finished:{finished_uuids}"

    def __repr__(self):
        return f"<{self.__str__()}>"

    def sort_status(self):
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
        """clears all status dicts except active_dict"""
        self.nonactive_dict = {}
        self.nonactive_dict[HloStatus.finished] = {}


class ActionServerModel(BaseModel, HelaoDict):
    action_server: MachineModel
    # endpoints keyed by the name of the endpoint (action_name)
    endpoints: Dict[str, EndpointModel] = Field(default={})
    # signals estop of the action server
    estop: bool = False
    last_action_uuid: Optional[UUID] = None

    def get_fastapi_json(self, action_name: Optional[str] = None):
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
        for _, endpoint in self.endpoints.items():
            endpoint.clear_finished()


class GlobalStatusModel(BaseModel, HelaoDict):
    orchestrator: MachineModel
    # a dict of actionserversmodels keyed by the server name
    # use MachineModel.as_key() for the dict key
    server_dict: Dict[Tuple, ActionServerModel] = Field(default={})

    # a dict of all active actions for this orch
    active_dict: Dict[UUID, Action] = Field(default={})
    # a dict of all finished actions
    # keyed by either main_finished_status or "finished"
    nonactive_dict: Dict[HloStatus, Dict[UUID, Action]] = Field(default={})

    # some control parameters for the orch

    # new intented state for the dispatch loop
    loop_intent: LoopIntent = LoopIntent.none
    # the dispatch loop state
    loop_state: LoopStatus = LoopStatus.stopped
    # the state of the orch
    orch_state: OrchStatus = OrchStatus.idle
    # counter for dispatched actions, keyed by experiment uuid
    counter_dispatched_actions: Dict[UUID, int] = Field(default={})

    def as_json(self):
        json_dict = {
            k: vars(self)[k]
            for k in (
                'orchestrator',
                'active_dict',
                'nonactive_dict',
                'loop_intent',
                'loop_state',
                'orch_state',
                'counter_dispatched_actions',
            )
        }
        json_dict['server_dict'] = {f"{k[0]}@{k[1]}": v for k, v in self.server_dict.items()}
        return json_dict

    def actions_idle(self) -> bool:
        """checks if all action servers for this orch are idle"""
        if self.active_dict:
            return False
        else:
            return True

    def server_free(
        self,
        action_server: MachineModel,
    ) -> bool:
        """checks if action server is idle for this orch"""
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
        """checks if an action server endpoint is available
        for this orch"""
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

    def _sort_status(self):
        """sorts actions from server_dict
        into orch specific separate dicts"""
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

    def update_global_with_acts(self, actionservermodel: ActionServerModel):
        if actionservermodel.action_server.as_key() not in self.server_dict:
            # add it for the first time
            self.server_dict.update({actionservermodel.action_server.as_key(): actionservermodel})
        else:
            self.server_dict[actionservermodel.action_server.as_key()].endpoints.update(
                actionservermodel.endpoints
            )
        # sort it into active and finished
        recent_nonactive = self._sort_status()
        return recent_nonactive

    def find_hlostatus_in_finished(self, hlostatus: HloStatus) -> Dict[UUID, Action]:
        """returns a dict of uuids for actions which contain hlostatus"""
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
        if hlostatus in self.nonactive_dict:
            self.nonactive_dict[hlostatus] = {}
        elif HloStatus.finished in self.nonactive_dict:
            # can only be in finsihed, but need to look for substatus
            for key in self.nonactive_dict[HloStatus.finished].keys():
                del self.nonactive_dict[HloStatus.finished][key]

    def new_experiment(self, exp_uuid: UUID):
        self.counter_dispatched_actions[exp_uuid] = 0

    def finish_experiment(self, exp_uuid: UUID) -> List[Action]:
        """returns all finished actions"""
        # we don't filter by orch as this should have happened already when they
        # were added to the finished_exps
        finished_acts = []
        for hlostatus, status_dict in self.nonactive_dict.items():
            for uuid, statusmodel in status_dict.items():
                if exp_uuid == uuid:
                    finished_acts.append(statusmodel)
        # TODO: properly clear actions from endpointstatusmodel only for exp_uuid

        # if self.active_dict:
        #     ERROR

        # clear finished
        self.nonactive_dict = {}
        if exp_uuid in self.counter_dispatched_actions:
            del self.counter_dispatched_actions[exp_uuid]

        print(f"Finished actions for experiment {exp_uuid}: {finished_acts}")

        return finished_acts
