"""SampleStatePort adapter (spec §4.3.11): the SampleArchiveShim itself,
plus the FLATTENING facade (P1a review carry-note): the port is flat, but
the shim exposes get_samples/new_samples/update_samples on the nested
.unified_db sub-client — this adapter flattens that seam. Everything else is
1:1 pass-through of the shim's public methods.

Boundary note: this adapter takes the shim as a constructor argument and does
NOT import the deployment tree that defines the concrete shim at module top
(keeps the adapter importable without that deployment tree present); the
composition that constructs the real shim lives in later phases."""

from typing import Any, List, Optional, Tuple

from helao.hexagon.domain.models import Action, ErrorCodes

__all__ = ["SampleShimAdapter"]


class SampleShimAdapter:
    def __init__(self, shim):
        self._shim = shim

    # -- tray --
    async def tray_query_sample(
        self,
        tray: Optional[int] = None,
        slot: Optional[int] = None,
        vial: Optional[int] = None,
    ) -> Tuple[ErrorCodes, Any]:
        return await self._shim.tray_query_sample(tray=tray, slot=slot, vial=vial)

    async def tray_get_next_full(
        self,
        after_tray: Optional[int] = None,
        after_slot: Optional[int] = None,
        after_vial: Optional[int] = None,
    ) -> dict:
        return await self._shim.tray_get_next_full(
            after_tray=after_tray, after_slot=after_slot, after_vial=after_vial
        )

    async def tray_new_position(self, req_vol: float = 2.0) -> dict:
        return await self._shim.tray_new_position(req_vol=req_vol)

    async def tray_update_position(
        self,
        tray: Optional[int] = None,
        slot: Optional[int] = None,
        vial: Optional[int] = None,
        sample: Optional[Any] = None,
        dilute: bool = False,
    ) -> bool:
        return await self._shim.tray_update_position(
            tray=tray, slot=slot, vial=vial, sample=sample, dilute=dilute
        )

    # -- custom positions --
    async def custom_query_sample(
        self, custom: Optional[str] = None
    ) -> Tuple[ErrorCodes, Any]:
        return await self._shim.custom_query_sample(custom=custom)

    async def custom_update_position(
        self,
        custom: Optional[str] = None,
        sample: Optional[Any] = None,
        dilute: bool = False,
    ) -> Tuple[bool, Any]:
        return await self._shim.custom_update_position(
            custom=custom, sample=sample, dilute=dilute
        )

    async def custom_dest_allowed(self, custom: Optional[str] = None) -> bool:
        return await self._shim.custom_dest_allowed(custom=custom)

    async def custom_assembly_allowed(self, custom: Optional[str] = None) -> bool:
        return await self._shim.custom_assembly_allowed(custom=custom)

    async def custom_is_destroyed(self, custom: Optional[str] = None) -> bool:
        return await self._shim.custom_is_destroyed(custom=custom)

    # -- creation --
    async def new_ref_samples(
        self,
        samples_in: Optional[List] = None,
        sample_out_type: Any = "",
        sample_position: str = "",
        action: Optional[Action] = None,
        combine_liquids: bool = False,
        combine_gases: bool = False,
    ) -> Tuple[ErrorCodes, list]:
        return await self._shim.new_ref_samples(
            samples_in=samples_in,
            sample_out_type=sample_out_type,
            sample_position=sample_position,
            action=action,
            combine_liquids=combine_liquids,
            combine_gases=combine_gases,
        )

    # -- FLATTENED unified_db sub-surface --
    async def get_samples(self, samples: Optional[list] = None) -> list:
        return await self._shim.unified_db.get_samples(samples=samples)

    async def new_samples(self, samples: Optional[list] = None) -> list:
        return await self._shim.unified_db.new_samples(samples=samples)

    async def update_samples(self, samples: Optional[list] = None) -> None:
        return await self._shim.unified_db.update_samples(samples=samples)
