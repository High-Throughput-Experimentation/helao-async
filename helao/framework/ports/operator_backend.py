"""Orchestrator-access backend port for the Bokeh operator UI.

The :class:`BokehOperator` UI talks only to an :class:`OrchBackend`.
This module defines the pure abstract seam; the concrete I/O implementation
(:class:`RemoteBackend`) lives in a separate adapter module.

List/state methods return *normalized plain dicts* so the UI never has to
branch on object-vs-JSON. See the method docstrings for the contract.
"""

from abc import ABC, abstractmethod
from typing import Callable, Optional


class OrchBackend(ABC):
    """Abstract orchestrator access used by :class:`BokehOperator`."""

    #: name -> callable sequence library (local in every backend)
    sequence_lib: dict
    #: name -> callable experiment library (local in every backend)
    experiment_lib: dict
    #: name -> source-file hash for the sequence/experiment libraries
    sequence_codehash: dict
    experiment_codehash: dict

    @abstractmethod
    def unpack_sequence(self, sequence_name: str, sequence_params: dict) -> list:
        """Expand a library sequence into a list of planned Experiment models."""

    @abstractmethod
    def get_step_flags(self) -> dict:
        """Return {'actions': bool, 'experiments': bool, 'sequences': bool}."""

    @abstractmethod
    async def set_step_flag(self, kind: str, value: bool) -> None:
        """Set one step-through flag ('actions'|'experiments'|'sequences')."""

    @abstractmethod
    async def list_sequences(self) -> list: ...

    @abstractmethod
    async def list_experiments(self) -> list: ...

    @abstractmethod
    async def list_actions(self) -> list: ...

    @abstractmethod
    async def get_queue_object(self, kind: str, idx: int) -> dict: ...

    @abstractmethod
    async def get_histories(self) -> dict: ...

    @abstractmethod
    async def get_status_summary(self) -> dict: ...

    @abstractmethod
    async def get_orch_state(self) -> dict: ...

    @abstractmethod
    async def add_sequence(self, sequence) -> object: ...

    @abstractmethod
    async def add_split_sequences(self, sequence) -> object: ...

    @abstractmethod
    async def prepend_sequences(self, sequences: list) -> object: ...

    @abstractmethod
    async def move_sequence(self, from_idx: int, to_idx: int) -> None: ...

    @abstractmethod
    async def remove_sequence(self, idx: int) -> None: ...

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    async def skip(self) -> None: ...

    @abstractmethod
    async def estop(self) -> None: ...

    @abstractmethod
    async def clear_sequences(self) -> None: ...

    @abstractmethod
    async def clear_experiments(self) -> None: ...

    @abstractmethod
    async def clear_actions(self) -> None: ...

    @abstractmethod
    def subscribe(self, on_change: Callable[[], None]) -> None:
        """Register a callback fired whenever orch state may have changed."""

    @abstractmethod
    def close(self) -> None:
        """Tear down subscriptions / background tasks."""
