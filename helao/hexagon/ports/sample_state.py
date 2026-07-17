"""SampleState port (spec §4.3.11): the Archive boundary.

The boundary is SAMPLE-server-behind-RPC -- exactly what PAL already consumes
via sample_shim.SampleArchiveShim (fail-loud RPC client, call-time address
resolution, typed rehydration). Signatures mirror the shim's public methods
verbatim (cross-checked against
helao/deploy/hte/drivers/robot/sample_shim.py, dropping only the shim's
`*args, **kwargs` catch-alls) so the P1b adapter is the shim itself. Archive
is NEVER ported as a driver. The shim's public surface has no methods beyond
those below (no custom_unloadall/custom_load exist on it).
"""

from typing import Any, List, Optional, Protocol, Tuple, runtime_checkable

from helao.hexagon.domain.models import Action, ErrorCodes

__all__ = ["SampleStatePort"]


@runtime_checkable
class SampleStatePort(Protocol):
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
