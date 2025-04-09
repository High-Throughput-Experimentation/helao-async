import os

from helao.core.error import ErrorCodes
from helao.helpers.premodels import Sequence, Experiment
from helao.helpers.dispatcher import private_dispatcher
from helao.helpers.config_loader import config_loader


class HelaoOperator:
    """
    HelaoOperator class to interact with the orchestrator server.

    Attributes:
        helao_config (dict): Configuration loaded for Helao.
        orch_key (str): Key for the orchestrator server.
        orch_host (str): Host address of the orchestrator server.
        orch_port (int): Port number of the orchestrator server.

    Methods:
        __init__(config_arg, orch_key):
            Initializes the HelaoOperator with the given configuration and orchestrator key.
        
        request(endpoint: str, path_params: dict = {}, json_params: dict = {}):
            Sends a request to the orchestrator server and returns the response.
        
        start():
            Dispatches a start request to the orchestrator server.
        
        stop():
            Dispatches a stop request to the orchestrator server.
        
        orch_state():
            Retrieves the current state of the orchestrator.
        
        get_active_experiment():
            Retrieves the currently active experiment.
        
        get_active_sequence():
            Retrieves the currently active sequence.
        
        add_experiment(experiment: Experiment, index: int = -1):
            Adds an experiment to the active sequence or creates a new sequence.
        
        add_sequence(sequence: Sequence):
            Adds a sequence to the orchestrator queue.
    """
    def __init__(self, config_arg: str, orch_key:str = "ORCH"):
        """
        Initializes the HelaoOperator instance.

        Args:
            config_arg (str): The configuration argument to load the configuration.
            orch_key (str): The key to identify the orchestrator server in the configuration.

        Raises:
            Exception: If the orchestrator server is not found in the configuration.
            Exception: If the orchestrator host or port is not fully specified.

        Attributes:
            helao_config (dict): The loaded configuration for Helao.
            orch_key (str): The key for the orchestrator server.
            orch_host (str): The host address of the orchestrator server.
            orch_port (int): The port number of the orchestrator server.
        """
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
            f"HelaoOperator initialized for orchestrator {self.orch_key} on {self.orch_host}:{self.orch_port}"
        )

    def request(self, endpoint: str, path_params: dict = {}, json_params: dict = {}):
        """
        Sends a request to the specified endpoint with given path and JSON parameters.

        Args:
            endpoint (str): The endpoint to send the request to.
            path_params (dict, optional): The path parameters to include in the request. Defaults to {}.
            json_params (dict, optional): The JSON parameters to include in the request. Defaults to {}.

        Returns:
            dict: The response from the request. If an exception occurs, returns a dictionary with 
                  "orch_state", "loop_state", and "loop_intent" set to "unreachable".
        """
        try:
            resp, error_code = private_dispatcher(
                self.orch_key,
                self.orch_host,
                self.orch_port,
                endpoint,
                path_params,
                json_params,
            )
        except Exception:
            resp = {
                k: "unreachable" for k in ("orch_state", "loop_state", "loop_intent")
            }
            error_code = ErrorCodes.not_available
        if error_code != ErrorCodes.none:
            print("HelaoOperator request got non-200 response.")
        return resp

    def start(self):
        """
        Initiates the 'start' request to the operator server.

        Returns:
            Response from the 'start' request.
        """
        return self.request("start")

    def stop(self):
        """
        Sends a request to stop the current operation.

        Returns:
            Response from the "stop" request.
        """
        return self.request("stop")

    def orch_state(self):
        """
        Retrieve the current state of the orchestrator.

        This method sends a request to get the current state of the orchestrator
        and returns the response.

        Returns:
            The current state of the orchestrator.
        """
        return self.request("get_orch_state")

    def get_active_experiment(self):
        """
        Retrieve the currently active experiment.

        This method sends a request to obtain the active experiment.

        Returns:
            The active experiment data.
        """
        return self.request("get_active_experiment")

    def get_active_sequence(self):
        """
        Retrieve the currently active sequence.

        This method sends a request to obtain the active sequence.

        Returns:
            The active sequence.
        """
        return self.request("get_active_sequence")

    def add_experiment(self, experiment: Experiment, index: int = -1):
        """
        Adds an experiment to the operator's experiment list.

        If the index is -1, the experiment is appended to the end of the list.
        Otherwise, the experiment is inserted at the specified index.

        Args:
            experiment (Experiment): The experiment to be added.
            index (int, optional): The position at which to insert the experiment. Defaults to -1.

        Returns:
            Response: The response from the request to add the experiment.
        """
        if index == -1:
            return self.request(
                "append_experiment", json_params={"experiment": experiment.as_dict()}
            )
        return self.request(
            "insert_experiment",
            path_params={"idx": index},
            json_params={"experiment": experiment.as_dict()},
        )

    def add_sequence(self, sequence: Sequence):
        """
        Adds a sequence to the operator.

        Args:
            sequence (Sequence): The sequence object to be added. It should have a method `as_dict` 
                                  that converts the sequence to a dictionary format.

        Returns:
            Response: The response from the request to append the sequence.
        """
        return self.request(
            "append_sequence", json_params={"sequence": sequence.as_dict()}
        )

    def get_latest_sequences(self):
        """
        Retrieve list of most recent sequence uuids.

        This method sends a request to obtain dispatched sequence uuids.

        Returns:
            List of 50 most recently dispatched sequence uuids.
        """
        return self.request("latest_sequence_uuids")
    
    def get_latest_experiments(self):
        """
        Retrieve list of most recent experiment uuids.

        This method sends a request to obtain dispatched experiment uuids.

        Returns:
            List of 50 most recently dispatched experiment uuids.
        """
        return self.request("latest_experiment_uuids")
    
    def get_latest_actions(self):
        """
        Retrieve list of most recent action uuids.

        This method sends a request to obtain dispatched action uuids.

        Returns:
            List of 50 most recently dispatched action uuids.
        """
        return self.request("latest_action_uuids")
    