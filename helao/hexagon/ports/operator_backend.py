"""Operator-backend port (P7h; Q8 answer 3).

``helao/ui/shared/operator/orch_backend.py``'s ``OrchBackend`` is **already
a port in all but name**: a 25-method async ABC with one implementation
(``RemoteBackend``), constructor-injected into both UIs -- ``BokehOperator(vis,
backend)`` and a per-session build for the Reflex page. So this module is a
**structural mirror, not a move**. Moving the ABC would edit
``bokeh_operator.py`` -- forbidden, it is the production operator named by 32
configs -- and break the 59-test ``test_standalone_operator.py`` gate.

A mirror that can drift is worse than no mirror, because it reads as a contract
while describing something that no longer exists. ``test_operator_backend_port``
therefore pins the two surfaces **set-equal in both directions**: a method added
to the ABC and not to this Protocol fails, and a method added here and not to
the ABC fails too. ``runtime_checkable`` alone would not do it -- ``isinstance``
against a Protocol checks *names only*, and only the names the Protocol
declares, so a Protocol that had fallen behind would keep passing.

**What this seam does *not* cover, deliberately.** ``RemoteBackend`` owns the
operator's only ``ws_status`` subscription (``orch_backend.py:332``, read in
``_ws_loop:337-346``). That loop decodes nothing -- any message at all is
treated as "orch state may have changed" and fires the callback -- so there is
no payload contract to mirror. It surfaces here as :meth:`subscribe` /
:meth:`close`, a lifecycle pair, which is the whole of what a caller can say
about it.

Ports may import only ``helao.hexagon.domain.*``/``helao.hexagon.ports.*``/
``helao.core.drivers.helao_driver`` (test_boundaries.py:78-82). That excludes
``helao.helpers.premodels``, so ``Sequence`` never appears below: the sequence
arguments and the enqueue returns are ``object``. It also means this module
does **not** import ``OrchBackend`` -- structural typing is what relates them,
and the drift pin is what keeps that true.

There is no adapter class. ``RemoteBackend`` satisfies this Protocol as it
stands (asserted, not assumed), and a delegating wrapper would be a *third*
surface to keep aligned -- the failure this port exists to prevent.
"""

from collections.abc import Callable
from typing import Optional, Protocol, runtime_checkable

__all__ = ["OperatorBackendPort"]


@runtime_checkable
class OperatorBackendPort(Protocol):
    """Structural mirror of ``OrchBackend`` (``orch_backend.py:25-123``).

    List/state methods return *normalized plain dicts*, so no caller branches
    on object-vs-JSON. That normalization is the backend's job and is part of
    this contract: see the legacy docstrings for each method's key set.
    """

    #: name -> callable sequence library (local in every backend)
    sequence_lib: dict
    #: name -> callable experiment library (local in every backend)
    experiment_lib: dict
    #: name -> source-file hash for the sequence/experiment libraries
    sequence_codehash: dict
    experiment_codehash: dict

    def unpack_sequence(self, sequence_name: str, sequence_params: dict) -> list:
        """Expand a library sequence into a list of planned Experiment models."""
        ...

    def get_step_flags(self) -> dict:
        """Return {'actions': bool, 'experiments': bool, 'sequences': bool}."""
        ...

    async def set_step_flag(self, kind: str, value: bool) -> None:
        """Set one step-through flag ('actions'|'experiments'|'sequences')."""
        ...

    async def list_sequences(
        self, limit: Optional[int] = None, offset: int = 0
    ) -> list: ...

    async def list_experiments(
        self, limit: Optional[int] = None, offset: int = 0
    ) -> list: ...

    async def list_actions(
        self, limit: Optional[int] = None, offset: int = 0
    ) -> list: ...

    async def get_queue_object(self, kind: str, idx: int) -> dict: ...

    async def get_histories(self) -> dict: ...

    async def get_history_page(
        self, kind: str, limit: Optional[int] = None, offset: int = 0
    ) -> dict: ...

    async def get_status_summary(self) -> dict: ...

    async def get_orch_state(self) -> dict: ...

    async def add_sequence(self, sequence) -> object: ...

    async def add_split_sequences(self, sequence) -> object: ...

    async def prepend_sequences(self, sequences: list) -> object: ...

    async def move_sequence(self, from_idx: int, to_idx: int) -> None: ...

    async def remove_sequence(self, idx: int) -> None: ...

    async def move_experiment(self, from_idx: int, to_idx: int) -> None: ...

    async def remove_experiment(self, idx: int) -> None: ...

    async def move_action(self, from_idx: int, to_idx: int) -> None: ...

    async def remove_action(self, idx: int) -> None: ...

    async def start(self) -> None: ...

    async def stop(self, reset_run_id: bool = False) -> None: ...

    async def skip(self) -> None: ...

    async def estop(self) -> None: ...

    async def clear_sequences(self) -> None: ...

    async def clear_experiments(self) -> None: ...

    async def clear_actions(self) -> None: ...

    def subscribe(self, on_change: Callable[[], None]) -> None:
        """Register a callback fired whenever orch state may have changed."""
        ...

    def close(self) -> None:
        """Tear down subscriptions / background tasks."""
        ...
