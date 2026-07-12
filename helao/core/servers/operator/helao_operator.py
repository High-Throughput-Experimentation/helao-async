"""Lightweight client for issuing requests to a HELAO orchestrator server."""

import os

from helao.core.error import ErrorCodes
from helao.helpers.premodels import Sequence, Experiment
from helao.helpers.dispatcher import private_dispatcher
from helao.helpers.config_loader import read_config


class HelaoOperator:
    """Programmatic client for talking to an orchestrator server's private endpoints.

    Resolves the orchestrator's host/port from a HELAO config and exposes
    convenience methods that wrap ``private_dispatcher`` calls for starting,
    stopping, querying state, and enqueuing sequences/experiments.

    Attributes:
        helao_config: Resolved HELAO configuration dictionary.
        orch_key: Server key identifying the orchestrator in the config.
        orch_host: Host address of the orchestrator server.
        orch_port: Port number of the orchestrator server.
    """

    def __init__(self, config_arg: str, orch_key: str = "ORCH"):
        """Load the configuration and resolve the orchestrator endpoint.

        Args:
            config_arg: A config prefix or path accepted by ``read_config``.
            orch_key: Key of the orchestrator server within the config.

        Raises:
            Exception: If the orchestrator server is not present in the config
                or its host/port are not fully specified.
        """
        helao_repo_root = os.path.dirname(os.path.realpath(__file__))
        while "launch.py" not in os.listdir(helao_repo_root):
            helao_repo_root = os.path.dirname(helao_repo_root)
        self.helao_config = read_config(config_arg, helao_repo_root)
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

    def request(self, endpoint: str, path_params: dict = {}, json_params: dict = {}) -> dict:
        """Dispatch a request to the orchestrator and return its response.

        Args:
            endpoint: Orchestrator endpoint name to invoke.
            path_params: Mapping of path parameters to include in the URL.
            json_params: Mapping of JSON-body parameters to include.

        Returns:
            The decoded response from the orchestrator. If the orchestrator
            is unreachable, returns a dictionary marking ``orch_state``,
            ``loop_state`` and ``loop_intent`` as ``"unreachable"``.
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

    def start(self) -> dict:
        """Request the orchestrator to start its dispatch loop."""
        return self.request("start")

    def stop(self) -> dict:
        """Request the orchestrator to stop its dispatch loop."""
        return self.request("stop")

    def orch_state(self) -> dict:
        """Return the orchestrator's current state summary."""
        return self.request("get_orch_state")

    def get_active_experiment(self) -> dict:
        """Return the orchestrator's currently active experiment."""
        return self.request("get_active_experiment")

    def get_active_sequence(self) -> dict:
        """Return the orchestrator's currently active sequence."""
        return self.request("get_active_sequence")

    def add_experiment(self, experiment: Experiment, index: int = -1) -> dict:
        """Append or insert an experiment into the orchestrator's active sequence.

        Args:
            experiment: Experiment to enqueue.
            index: Insertion index. ``-1`` appends to the end; any other value
                inserts at that index.

        Returns:
            The orchestrator's response to the enqueue request.
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

    def add_sequence(self, sequence: Sequence) -> dict:
        """Append a sequence to the orchestrator's sequence queue.

        Args:
            sequence: Sequence object to enqueue.

        Returns:
            The orchestrator's response to the enqueue request.
        """
        return self.request(
            "append_sequence", json_params={"sequence": sequence.as_dict()}
        )

    def get_latest_sequences(self) -> dict:
        """Return the most recently dispatched sequence UUIDs from the orchestrator."""
        return self.request("latest_sequence_uuids")

    def get_latest_experiments(self) -> dict:
        """Return the most recently dispatched experiment UUIDs from the orchestrator."""
        return self.request("latest_experiment_uuids")

    def get_latest_actions(self) -> dict:
        """Return the most recently dispatched action UUIDs from the orchestrator."""
        return self.request("latest_action_uuids")
