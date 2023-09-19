import os

from helaocore.error import ErrorCodes
from helaocore.models.experiment import ExperimentModel
from helaocore.models.sequence import SequenceModel
from helao.helpers.dispatcher import private_dispatcher
from helao.helpers.config_loader import config_loader


class Operator:
    def __init__(self, config_arg, orch_key):
        helao_root = os.path.dirname(os.path.realpath(__file__))
        while "helao.py" not in os.listdir(helao_root):
            helao_root = os.path.dirname(helao_root)
        self.helao_config = config_loader(config_arg, helao_root)
        self.orch_key = orch_key
        orch_config = self.helao_config.get("servers", {}).get(self.orch_key, {})
        if not orch_config:
            config_path = self.helao_config["loaded_config_path"]
            no_orch = f"Server {self.orch_key} not found in {config_path}"
            raise (Exception(no_orch))
        self.orch_host = orch_config.get("host", None)
        self.orch_port = orch_config.get("port", None)
        if self.orch_host is None or self.orch_port is None:
            raise (Exception("Orchestrator host and port not fully specified."))
        print(
            f"Operator initialized for orchestrator {self.orch_key} on {self.orch_host}:{self.orch_port}"
        )

    def request(self, endpoint: str, path_params: {}, json_params: {}):
        resp, error_code = private_dispatcher(
            self.orch_key,
            self.orch_host,
            self.orch_port,
            endpoint,
            path_params,
            json_params,
        )
        if error_code != ErrorCodes.none:
            print("Operator request got non-200 response.")
        return resp

    def start(self):
        """Dispatch start request on orch"""
        return self.request("start")

    def stop(self):
        """Dispatch stop request on orch"""
        return self.request("stop")

    def orch_state(self):
        """Dispatch stop request on orch"""
        return self.request("get_orch_state")

    def get_active_experiment(self):
        """Retrieve active experiment"""
        return self.request("get_active_experiment")

    def get_active_sequence(self):
        """Retrieve active sequence"""
        return self.request("get_active_sequence")

    def add_experiment(self, experiment: ExperimentModel, index: int = -1):
        """add experiment to active sequence or creates new sequence"""
        if index == -1:
            return self.request(
                "append_experiment", json_params=experiment.clean_dict()
            )
        return self.request(
            "insert_experiment",
            path_params={"idx": index},
            json_params=experiment.clean_dict(),
        )

    def add_sequence(self, sequence: SequenceModel):
        """add sequence to orch queue"""
        return self.request("append_sequence", json_params=sequence.clean_dict())
