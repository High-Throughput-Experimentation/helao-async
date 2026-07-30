"""Native Galil motion HardwarePort adapter (P3a galil-split slice-3).

The native-cut-over seam for the hte Galil motion controller: a hexagon-side
adapter that satisfies :class:`~helao.hexagon.ports.hardware.HardwarePort` and
exposes the Galil motion verbs as first-class named methods, delegating to the
legacy ``Galil`` driver (``helao/deploy/hte/drivers/motion/galil_motion_driver.py``).

Design (roadmap ``2026-07-18-P3a-special-splits-roadmap.md`` §"galil slice 3"):

- **Pure delegation, behavior-preserving.** The adapter does NOT reimplement
  gclib command sequences; it forwards to the legacy driver so the motion
  verbs' legacy ``{err_code: ErrorCodes, ...}`` dict returns reach the server
  (``galil_motion.py`` via ``app.base.get_main_error``) **verbatim** (D6 §4.4).
  The ~900-LOC ``_motor_move`` device logic and the slice-2 CalibrationStore
  wiring stay in the legacy driver, unchanged.
- **Disconnected construct (port contract).** ``__init__`` does zero device
  I/O — it stores the already-constructed legacy driver. ``from_config`` builds
  the legacy ``Galil`` (whose own ``__init__`` is I/O-free after slices 1-2) and
  wraps it; ``import gclib`` stays lazy inside the legacy ``connect()``.
- **Async-first lifecycle.** The legacy ABC lifecycle methods
  (``connect``/``get_status``/``reset``/``disconnect``/``shutdown``) are sync;
  they are offloaded with :func:`asyncio.to_thread` (matching
  ``LegacyDriverHardwareAdapter``). ``stop``/``estop`` and every motion verb are
  already ``async`` on the legacy driver and are awaited directly.
- **Not runtime-wired.** The P3 graft-wrap path keeps ``app.driver`` pointed at
  the legacy driver; this adapter is the target for a later native cut-over, so
  nothing constructs it in the server yet. Construct-testable on Linux; motion
  behavior is an at-station gate (needs the controller + gclib).

CUT-OVER CHECKLIST (resolve before repointing ``app.driver`` at this adapter):

- ``shutdown`` await seam: ``base_api.py``'s shutdown handler calls
  ``driver.shutdown()`` **synchronously** and only ``await``\\s a separate
  ``async_shutdown``. This adapter's ``shutdown`` is ``async`` (HardwarePort
  is async-first, and the sibling ``LegacyDriverHardwareAdapter`` has the same
  shape), so a naive cut-over would leave the coroutine un-awaited and skip
  ``GClose()``. The cut-over must resolve this for the whole native-adapter
  family (expose ``async_shutdown``, or make ``base_api`` await a coroutine
  ``shutdown``) — it is a framework seam, not a per-driver fix. The
  ``disconnect()`` path is unaffected (it thread-offloads legacy ``disconnect``
  -> sync ``shutdown``).
- Transform-management / aligner / ``solid_get_*`` verbs the server also calls
  on ``app.driver`` (``transform``, ``reset_plate_transfermatrix``,
  ``update_plate_transfermatrix``, ``run_aligner_precheck``,
  ``start_aligner_run``, ``stop_aligner``, ``solid_get_platemap``,
  ``solid_get_samples_xy``) are intentionally out of this slice's scope
  (slice-4 aligner split + a later transform/platemap seam).
"""

import asyncio
from typing import Any, Optional

from helao.core.drivers.helao_driver import (
    DriverResponse,
    DriverResponseType,
    DriverStatus,
)
from helao.deploy.hte.drivers.motion.galil_motion_driver import Galil

__all__ = ["GalilMotionHardwareAdapter"]


class GalilMotionHardwareAdapter:
    """HardwarePort-conforming wrapper around the legacy ``Galil`` driver.

    Satisfies the HardwarePort lifecycle (``connect``/``get_status``/``reset``/
    ``disconnect``/``estop``/``shutdown``/``abort``) and re-exposes the Galil
    motion verbs (``motor_move``/``query_axis_position``/``query_axis_moving``/
    ``motor_off``/``motor_on``/``stop_axis``/``setaxisref``/``reset_controller``/
    ``get_all_axis``) with their legacy return values intact.
    """

    def __init__(self, driver: Galil):
        """Wrap an already-constructed legacy ``Galil`` (no device I/O)."""
        self._driver = driver

    @classmethod
    def from_config(
        cls, config: Optional[dict] = None, base_hook: Any = None
    ) -> "GalilMotionHardwareAdapter":
        """Build the legacy ``Galil`` from a server ``params`` dict and wrap it.

        Mirrors the server-startup handshake: the legacy driver's
        ``_base_hook`` (source of ``helaodirs``/``server_cfg`` read in
        ``connect()``) is assigned post-construction, never in ``__init__``
        (K8 disconnected-construct). No device I/O happens here.
        """
        driver = Galil(config=config or {})
        driver._base_hook = base_hook
        return cls(driver)

    @property
    def driver(self) -> Galil:
        """The wrapped legacy driver (cut-over / introspection escape hatch)."""
        return self._driver

    @property
    def galil_enabled(self) -> Optional[bool]:
        """Passthrough of the legacy connect-state flag.

        ``None`` before ``connect()``, ``True``/``False`` after. The action
        server gates its endpoints on this value.
        """
        return self._driver.galil_enabled

    @property
    def _base_hook(self):
        """Proxy the legacy driver's ``_base_hook``.

        The server startup handshake assigns the hook *after* construction
        (``app.driver._base_hook = app.base``); proxying keeps that live
        assignment reaching the wrapped ``Galil`` (whose ``connect()`` reads
        ``helaodirs``/``server_cfg`` off it) when this adapter is ``app.driver``.
        """
        return self._driver._base_hook

    @_base_hook.setter
    def _base_hook(self, value):
        self._driver._base_hook = value

    # --- HardwarePort lifecycle -------------------------------------------

    async def connect(self) -> DriverResponse:
        return await asyncio.to_thread(self._driver.connect)

    async def get_status(self) -> DriverResponse:
        return await asyncio.to_thread(self._driver.get_status)

    async def reset(self) -> DriverResponse:
        return await asyncio.to_thread(self._driver.reset)

    async def disconnect(self) -> DriverResponse:
        return await asyncio.to_thread(self._driver.disconnect)

    async def abort(self, **_kwargs) -> DriverResponse:
        """HardwarePort ``abort`` maps to the legacy ABC ``stop()`` (abort all
        motion, device stays enabled). Extra kwargs are accepted for protocol
        signature parity and ignored (legacy ``stop()`` takes none)."""
        return await self._driver.stop()

    # --- HardwarePort measurement phase (N/A for a motion controller) -----
    # A Galil motion controller has no arm/measure/drain/de-arm cycle. These
    # exist only so the adapter structurally satisfies the full HardwarePort
    # protocol; they fail loud rather than silently no-op, matching
    # ``LegacyDriverHardwareAdapter``'s "no legacy method -> raise" contract.

    async def arm(self, **_setup_params) -> DriverResponse:
        raise NotImplementedError(
            "galil motion controller has no measurement arm phase"
        )

    async def start(self, **_measure_params) -> DriverResponse:
        raise NotImplementedError(
            "galil motion controller has no measurement start phase"
        )

    async def drain(self, **_kwargs) -> DriverResponse:
        raise NotImplementedError(
            "galil motion controller has no measurement drain phase"
        )

    async def cleanup(self, **_kwargs) -> DriverResponse:
        raise NotImplementedError(
            "galil motion controller has no measurement cleanup phase"
        )

    async def estop(self, switch: bool) -> DriverResponse:
        """Engage/clear the motion e-stop.

        The legacy ``estop`` performs the stop + motor-off and returns the
        ``switch`` bool; the HardwarePort contract returns a ``DriverResponse``,
        so the bool is wrapped (the device side-effect is unchanged). Server
        estop-flag bookkeeping stays owned by ``base_api.py``'s ``/estop``.
        """
        await self._driver.estop(switch)
        return DriverResponse(
            response=DriverResponseType.success, status=DriverStatus.ok
        )

    async def shutdown(self) -> DriverResponse:
        """Close the gclib connection (legacy returns ``{"shutdown"}``; wrapped
        into a ``DriverResponse`` for the port)."""
        await asyncio.to_thread(self._driver.shutdown)
        return DriverResponse(
            response=DriverResponseType.success, status=DriverStatus.ok
        )

    # --- Galil motion verbs (legacy dict returns intact) ------------------

    async def motor_move(self, active) -> dict:
        return await self._driver.motor_move(active)

    async def motor_disconnect(self) -> dict:
        return await self._driver.motor_disconnect()

    async def query_axis_position(self, axis, *args, **kwargs) -> dict:
        return await self._driver.query_axis_position(axis, *args, **kwargs)

    async def query_axis_moving(self, axis, *args, **kwargs) -> dict:
        return await self._driver.query_axis_moving(axis, *args, **kwargs)

    async def stop_axis(self, axis) -> dict:
        return await self._driver.stop_axis(axis)

    async def motor_off(self, axis, *args, **kwargs) -> dict:
        return await self._driver.motor_off(axis, *args, **kwargs)

    async def motor_on(self, axis, *args, **kwargs) -> dict:
        return await self._driver.motor_on(axis, *args, **kwargs)

    async def setaxisref(self):
        return await self._driver.setaxisref()

    async def reset_controller(self):
        return await self._driver.reset_controller()

    def get_all_axis(self) -> list[str]:
        return self._driver.get_all_axis()
