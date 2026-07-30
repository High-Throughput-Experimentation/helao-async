"""Fail-loud dispatcher shim standing in for the local ``Archive`` in PAL.

``SampleArchiveShim`` is a drop-in replacement for ``pal_driver``'s former
``self.archive`` (an :class:`Archive` instance). Instead of owning sample
state locally, every method issues a private RPC/HTTP call to the standalone
``SAMPLE`` action server (via :func:`async_private_dispatcher`) and reproduces
the *exact* return types the real ``Archive`` methods produced, so the PAL
driver's call sites are unchanged apart from three sync->async predicate
awaits added in Phase 4.

Contract (see plan Principle 5 / Pre-mortem #2/#3/#4):

* The SAMPLE host/port is resolved from ``world_cfg["servers"]["SAMPLE"]``
  **at call time**, not construction, because SAMPLE may not be up when PAL
  starts.
* Dispatcher args are pinned to ``timeout=5, retries=1`` so a transient RPC
  failure cannot stall the PAL IO loop on the long HTTP-fallback backoff.
* Every method **raises** ``RuntimeError`` when the returned ``error_code``
  is not :attr:`ErrorCodes.none` -- it never returns ``None``/``False`` on a
  transport failure. It does **not** raise merely because the response body
  is ``None`` (void endpoints such as ``update_samples`` succeed with a
  ``None`` body).
* Outbound ``Sample``/``list[SampleUnion]``/``Action`` arguments are
  serialized to plain dicts (``.as_dict()`` / ``model_dump(mode="json")``)
  before being placed in ``params_dict``/``json_dict``, because the HTTP
  fallback's JSON encoder cannot serialize raw pydantic models.
* Returned samples are re-hydrated with :func:`object_to_sample` (never a
  hand-rolled ``LiquidSample(**d)``) so nested ``AssemblySample.parts`` and
  subtype selection survive; ``ErrorCodes`` members are reconstructed from
  their wire value.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel

from helao.core.error import ErrorCodes
from helao.core.models.sample import object_to_sample
from helao.helpers.dispatcher import async_private_dispatcher
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

# Pinned per plan Pre-mortem #3: short timeout + single retry keeps a transient
# RPC failure from stalling the PAL IO loop on the HTTP-fallback backoff.
_TIMEOUT = 5
_RETRIES = 1
_SERVER_KEY = "SAMPLE"


def _to_jsonable(obj: Any) -> Any:
    """Serialize a Sample/Action/enum into a JSON-encodable plain value.

    The HTTP fallback (aiohttp default encoder) cannot serialize raw pydantic
    models, so any outbound model argument must be reduced to a dict first.
    """
    if obj is None:
        return None
    if hasattr(obj, "as_dict"):
        return obj.as_dict()
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if isinstance(obj, Enum):
        return obj.value
    return obj


def _samples_to_jsonable(samples: Optional[list]) -> list:
    """Serialize a ``list[SampleUnion]`` argument to a list of plain dicts."""
    if not samples:
        return []
    return [_to_jsonable(s) for s in samples]


def _clean_query_params(params: Optional[dict]) -> dict:
    """Sanitize a query-parameter dict for the HTTP fallback path.

    aiohttp's query-string encoder only accepts ``str``/``int``/``float`` and
    rejects raw ``bool``/``None``. We therefore:

    * drop ``None`` values -- the remote endpoint's declared default (also
      ``None``) is used, identical to the RPC fast path where the kwarg is
      simply absent; and
    * coerce ``bool`` -> ``int`` (0/1) -- aiohttp accepts it and both FastAPI
      query parsing and the RPC handler coerce ``0``/``1`` back to ``bool``.

    Any :class:`enum.Enum` is reduced to its ``.value``.
    """
    if not params:
        return {}
    cleaned: dict = {}
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, bool):
            cleaned[key] = int(value)
        elif isinstance(value, Enum):
            cleaned[key] = value.value
        else:
            cleaned[key] = value
    return cleaned


def _rehydrate_error(value: Any) -> ErrorCodes:
    """Reconstruct an :class:`ErrorCodes` member from its wire value."""
    if isinstance(value, ErrorCodes):
        return value
    return ErrorCodes(value)


def _rehydrate_samples(value: Optional[list]) -> list:
    """Re-hydrate a wire list of sample dicts into concrete Sample models."""
    if not value:
        return []
    return [object_to_sample(s) for s in value]


class _UnifiedDBShim:
    """Nested sub-client mirroring ``Archive.unified_db`` (``UnifiedSampleDataAPI``).

    Drives the nine ``self.archive.unified_db.*`` call sites in ``pal_driver``.
    """

    def __init__(self, parent: "SampleArchiveShim"):
        self._parent = parent

    async def get_samples(
        self,
        samples: Optional[list] = None,
        *args,
        **kwargs,
    ) -> list:
        """Resolve sample references; returns ``list[SampleUnion]``."""
        resp = await self._parent._dispatch(
            "get_samples",
            json_dict={"samples": _samples_to_jsonable(samples)},
        )
        return _rehydrate_samples(resp)

    async def new_samples(
        self,
        samples: Optional[list] = None,
        *args,
        **kwargs,
    ) -> list:
        """Persist new samples; returns the persisted ``list[SampleUnion]``."""
        resp = await self._parent._dispatch(
            "new_samples",
            json_dict={"samples": _samples_to_jsonable(samples)},
        )
        return _rehydrate_samples(resp)

    async def update_samples(
        self,
        samples: Optional[list] = None,
        *args,
        **kwargs,
    ) -> None:
        """Update existing sample rows. Void endpoint -- returns ``None``."""
        await self._parent._dispatch(
            "update_samples",
            json_dict={"samples": _samples_to_jsonable(samples)},
        )
        return None


class SampleArchiveShim:
    """Drop-in ``self.archive`` replacement backed by the SAMPLE server.

    Args:
        world_cfg: The loaded HELAO world config dict. The SAMPLE server's
            ``host``/``port`` are resolved from
            ``world_cfg["servers"]["SAMPLE"]`` fresh on every call.
    """

    def __init__(self, world_cfg: dict):
        self.world_cfg = world_cfg
        self.unified_db = _UnifiedDBShim(self)

    # -- internals -------------------------------------------------------
    def _addr(self) -> tuple[str, int]:
        """Resolve the SAMPLE server ``(host, port)`` at call time.

        Raises:
            KeyError: if the SAMPLE server block is absent from the config.
        """
        srv = self.world_cfg["servers"][_SERVER_KEY]
        return srv["host"], srv["port"]

    async def _dispatch(
        self,
        endpoint: str,
        params_dict: Optional[dict] = None,
        json_dict: Optional[dict] = None,
    ) -> Any:
        """Call a SAMPLE private endpoint and fail loud on a non-none error code.

        Returns the raw decoded response body (which may legitimately be
        ``None`` for void endpoints). Raises :class:`RuntimeError` when the
        dispatcher reports ``error_code != ErrorCodes.none``.
        """
        host, port = self._addr()
        resp, err = await async_private_dispatcher(
            _SERVER_KEY,
            host,
            port,
            endpoint,
            params_dict=_clean_query_params(params_dict),
            json_dict=json_dict or {},
            timeout=_TIMEOUT,
            retries=_RETRIES,
        )
        if err != ErrorCodes.none:
            raise RuntimeError(f"SAMPLE {endpoint} failed: {err}")
        return resp

    # -- tray methods ----------------------------------------------------
    async def tray_query_sample(
        self,
        tray: Optional[int] = None,
        slot: Optional[int] = None,
        vial: Optional[int] = None,
        *args,
        **kwargs,
    ) -> tuple[ErrorCodes, Any]:
        """Return ``(error, sample)`` for the given tray/slot/vial location."""
        resp = await self._dispatch(
            "tray_query_sample",
            params_dict={"tray": tray, "slot": slot, "vial": vial},
        )
        error = _rehydrate_error(resp[0])
        sample = object_to_sample(resp[1])
        return error, sample

    async def tray_get_next_full(
        self,
        after_tray: Optional[int] = None,
        after_slot: Optional[int] = None,
        after_vial: Optional[int] = None,
        *args,
        **kwargs,
    ) -> dict:
        """Return ``{"tray","slot","vial"}`` for the next loaded vial."""
        resp = await self._dispatch(
            "tray_get_next_full",
            params_dict={
                "after_tray": after_tray,
                "after_slot": after_slot,
                "after_vial": after_vial,
            },
        )
        return resp

    async def tray_new_position(
        self,
        req_vol: float = 2.0,
        *args,
        **kwargs,
    ) -> dict:
        """Reserve the smallest empty vial >= ``req_vol``; returns a dict."""
        resp = await self._dispatch(
            "tray_new_position",
            params_dict={"req_vol": req_vol},
        )
        return resp

    async def tray_update_position(
        self,
        tray: Optional[int] = None,
        slot: Optional[int] = None,
        vial: Optional[int] = None,
        sample: Optional[Any] = None,
        dilute: bool = False,
        *args,
        **kwargs,
    ) -> bool:
        """Overwrite the sample at ``(tray, slot, vial)``; returns a bool."""
        resp = await self._dispatch(
            "tray_update_position",
            params_dict={
                "tray": tray,
                "slot": slot,
                "vial": vial,
                "dilute": dilute,
            },
            json_dict={"sample": _to_jsonable(sample)},
        )
        return bool(resp)

    # -- custom methods --------------------------------------------------
    async def custom_query_sample(
        self,
        custom: Optional[str] = None,
        *args,
        **kwargs,
    ) -> tuple[ErrorCodes, Any]:
        """Return ``(error, sample)`` for the sample at a custom position."""
        resp = await self._dispatch(
            "custom_query_sample",
            params_dict={"custom": custom},
        )
        error = _rehydrate_error(resp[0])
        sample = object_to_sample(resp[1])
        return error, sample

    async def custom_update_position(
        self,
        custom: Optional[str] = None,
        sample: Optional[Any] = None,
        dilute: bool = False,
        *args,
        **kwargs,
    ) -> tuple[bool, Any]:
        """Replace the sample at ``custom``; returns ``(success, sample)``."""
        resp = await self._dispatch(
            "custom_update_position",
            params_dict={"custom": custom, "dilute": dilute},
            json_dict={"sample": _to_jsonable(sample)},
        )
        success = bool(resp[0])
        sample_out = object_to_sample(resp[1])
        return success, sample_out

    async def custom_dest_allowed(
        self,
        custom: Optional[str] = None,
        *args,
        **kwargs,
    ) -> bool:
        """Return whether ``custom`` is a valid destination position."""
        resp = await self._dispatch(
            "custom_dest_allowed",
            params_dict={"custom": custom},
        )
        return bool(resp)

    async def custom_assembly_allowed(
        self,
        custom: Optional[str] = None,
        *args,
        **kwargs,
    ) -> bool:
        """Return whether ``custom`` may hold an ``AssemblySample``."""
        resp = await self._dispatch(
            "custom_assembly_allowed",
            params_dict={"custom": custom},
        )
        return bool(resp)

    async def custom_is_destroyed(
        self,
        custom: Optional[str] = None,
        *args,
        **kwargs,
    ) -> bool:
        """Return whether ``custom`` is a waste/injector-style position."""
        resp = await self._dispatch(
            "custom_is_destroyed",
            params_dict={"custom": custom},
        )
        return bool(resp)

    # -- reference sample creation --------------------------------------
    async def new_ref_samples(
        self,
        samples_in: Optional[list] = None,
        sample_out_type: Any = "",
        sample_position: str = "",
        action: Optional[Any] = None,
        combine_liquids: bool = False,
        combine_gases: bool = False,
        *args,
        **kwargs,
    ) -> tuple[ErrorCodes, list]:
        """Build new reference samples; returns ``(error_code, samples)``."""
        resp = await self._dispatch(
            "new_ref_samples",
            params_dict={
                "sample_out_type": _to_jsonable(sample_out_type),
                "sample_position": sample_position,
                "combine_liquids": combine_liquids,
                "combine_gases": combine_gases,
            },
            json_dict={
                "samples_in": _samples_to_jsonable(samples_in),
                "action": _to_jsonable(action),
            },
        )
        error = _rehydrate_error(resp[0])
        samples_out = _rehydrate_samples(resp[1])
        return error, samples_out
