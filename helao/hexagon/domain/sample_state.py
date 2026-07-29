"""The sample-state collaborator contract, as the domain requires it.

This Protocol lives in `domain/` rather than `ports/` because it is a DRIVEN
(required) contract: `pal_reconciliation.PalReconciler` is written against it
and calls all of it, so the core is what defines the shape. `ports/` re-exports
it under the port name `SampleStatePort` for adapters and composition to bind
against -- `ports/` may import `domain/`, so that direction is the allowed one.
Declaring it here is what keeps the domain from importing `ports/`, which
reverses the dependency arrow and is rejected by
`tests/test_boundaries.py::test_domain_imports_only_allowlist`.

Narrowing was considered and rejected: the reconciler calls every member below,
so a slimmer domain-side view would be the same surface under a second name.

Behavioral contract (unchanged from the port): the boundary is the Archive
SAMPLE server behind RPC, and the signatures mirror the PAL sample shim's
public methods verbatim, dropping only its `*args, **kwargs` catch-alls, so an
adapter can be the shim itself. Archive is NEVER ported as a driver.
"""

from typing import Any, List, Optional, Protocol, Tuple, runtime_checkable

from helao.hexagon.domain.models import Action, ErrorCodes

__all__ = ["SampleStateProtocol"]


@runtime_checkable
class SampleStateProtocol(Protocol):
    # -- tray methods --
    async def tray_query_sample(
        self,
        tray: Optional[int] = None,
        slot: Optional[int] = None,
        vial: Optional[int] = None,
    ) -> Tuple[ErrorCodes, Any]: ...

    async def tray_get_next_full(
        self,
        after_tray: Optional[int] = None,
        after_slot: Optional[int] = None,
        after_vial: Optional[int] = None,
    ) -> dict: ...

    async def tray_new_position(self, req_vol: float = 2.0) -> dict: ...

    async def tray_update_position(
        self,
        tray: Optional[int] = None,
        slot: Optional[int] = None,
        vial: Optional[int] = None,
        sample: Optional[Any] = None,
        dilute: bool = False,
    ) -> bool: ...

    # -- custom-position methods --
    async def custom_query_sample(
        self, custom: Optional[str] = None
    ) -> Tuple[ErrorCodes, Any]: ...

    async def custom_update_position(
        self,
        custom: Optional[str] = None,
        sample: Optional[Any] = None,
        dilute: bool = False,
    ) -> Tuple[bool, Any]: ...

    async def custom_dest_allowed(self, custom: Optional[str] = None) -> bool: ...

    async def custom_assembly_allowed(self, custom: Optional[str] = None) -> bool: ...

    async def custom_is_destroyed(self, custom: Optional[str] = None) -> bool: ...

    # -- sample creation --
    async def new_ref_samples(
        self,
        samples_in: Optional[List] = None,
        sample_out_type: Any = "",
        sample_position: str = "",
        action: Optional[Action] = None,
        combine_liquids: bool = False,
        combine_gases: bool = False,
    ) -> Tuple[ErrorCodes, list]: ...

    # -- unified sample DB sub-surface (shim's .unified_db) --
    async def get_samples(self, samples: Optional[list] = None) -> list: ...

    async def new_samples(self, samples: Optional[list] = None) -> list: ...

    async def update_samples(self, samples: Optional[list] = None) -> None: ...
