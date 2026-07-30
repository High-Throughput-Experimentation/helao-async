"""Galil plate-aligner vis-layer host (P3a galil-split slice-4).

Removes the D6 violation whereby the Galil motion *driver* constructed a Bokeh
``Server`` + ``HelaoVis`` and held an action ``Active``. Those responsibilities
move here, to the vis/server layer:

- :class:`GalilAlignerHost` owns the Bokeh ``Server`` construction (relocated
  ``start_aligner``/``makeBokehApp``) and the aligner-orchestration verbs the
  action server calls (``run_aligner_precheck``/``start_aligner_run``/
  ``stop_aligner``/``shutdown``).
- :class:`AlignerMotorContext` is handed to ``layouts.aligner.Aligner`` in
  place of the raw driver: it **delegates** motion/transform/calibration and the
  driver-owned motion flags (``blocked`` — a shared mutual-exclusion lock with
  ``_motor_move`` — and ``motor_busy``) to the legacy driver, while **owning**
  the aligner-session state the hardware driver should never hold (``base``,
  ``aligner_active``, ``aligner_plateid``, ``aligning_enabled``, and the
  ``aligner`` back-reference set by ``Aligner.__init__``). This keeps the
  1685-LOC ``aligner.py`` almost untouched — it still calls ``self.motor.<x>``.

**NOT Linux-runtime-verifiable** (needs a live Bokeh session + an at-station
plate-alignment dry-run). Construct-test tier only; see
``docs/superpowers/plans/2026-07-22-P3a-galil-slice4-aligner-extraction.md``.
The heavy imports (``bokeh``, ``HelaoVis``, ``Aligner``) are kept lazy inside
:meth:`GalilAlignerHost.start` so this module — and the action server that
constructs the host — import without a Bokeh document context.
"""

from functools import partial
from typing import Any, Optional

from helao.core.error import ErrorCodes

__all__ = ["AlignerMotorContext", "GalilAlignerHost"]


class AlignerMotorContext:
    """The ``motor`` object handed to ``Aligner`` — a driver façade that keeps
    aligner-session state off the hardware driver.

    Delegates motion/transform/calibration + the driver-owned ``blocked`` /
    ``motor_busy`` flags to the wrapped legacy driver; owns ``base`` /
    ``aligner_active`` / ``aligner_plateid`` / ``aligning_enabled`` / ``aligner``.
    """

    def __init__(self, driver: Any, base: Any):
        self._driver = driver
        # Owned here (was on the driver): the real Base handle the aligner reads
        # for helaodirs/get_main_error, and the action Active + its session ids.
        self.base = base
        self.aligner_active: Any = None
        self.aligner_plateid: Any = None
        self.aligning_enabled: bool = False
        # Back-reference target for `Aligner.__init__`'s `self.motor.aligner = self`.
        self.aligner: Any = None

    # --- delegated motion verbs -------------------------------------------
    async def _motor_move(self, *args, **kwargs) -> dict:
        return await self._driver._motor_move(*args, **kwargs)

    async def query_axis_position(self, *args, **kwargs) -> dict:
        return await self._driver.query_axis_position(*args, **kwargs)

    async def query_axis_moving(self, *args, **kwargs) -> dict:
        return await self._driver.query_axis_moving(*args, **kwargs)

    # --- delegated transform / calibration --------------------------------
    @property
    def transform(self):
        return self._driver.transform

    @property
    def dflt_matrix(self):
        return self._driver.dflt_matrix

    @property
    def plate_transfermatrix(self):
        return self._driver.plate_transfermatrix

    def update_plate_transfermatrix(self, *args, **kwargs):
        return self._driver.update_plate_transfermatrix(*args, **kwargs)

    def save_transfermatrix(self, *args, **kwargs):
        return self._driver.save_transfermatrix(*args, **kwargs)

    # --- delegated driver-owned motion flags (live r/w on the driver) -----
    @property
    def blocked(self) -> bool:
        return self._driver.blocked

    @blocked.setter
    def blocked(self, value: bool) -> None:
        self._driver.blocked = value

    @property
    def motor_busy(self) -> bool:
        return self._driver.motor_busy

    @motor_busy.setter
    def motor_busy(self, value: bool) -> None:
        self._driver.motor_busy = value


class GalilAlignerHost:
    """Vis-layer owner of the Bokeh aligner for a Galil motion server.

    Constructed by the action server after the driver connects (when
    ``enable_aligner`` is set). Owns the Bokeh ``Server`` and the
    aligner-orchestration verbs formerly on the driver.
    """

    def __init__(
        self,
        driver: Any,
        base: Any,
        server_cfg: dict,
        server_name: str,
        config: Optional[dict] = None,
    ):
        self._driver = driver
        self._base = base
        self._server_cfg = server_cfg
        self._server_name = server_name
        self._config = config or {}
        self.context = AlignerMotorContext(driver, base)
        self.bokehapp: Any = None

    def start(self) -> None:
        """Build and start the Bokeh ``Server`` hosting the ``/Aligner`` app.

        Relocated verbatim from the legacy ``Galil.start_aligner`` /
        ``makeBokehApp`` (D6 removal) — same host/port derivation
        (``bokeh_port`` config, else ``server_cfg['port'] + 1000``).
        """
        from bokeh.server.server import Server

        serv_host = self._server_cfg["host"]
        serv_port = self._config.get("bokeh_port", self._server_cfg["port"] + 1000)
        serv_py = "Aligner"
        self.bokehapp = Server(
            {f"/{serv_py}": partial(self._make_bokeh_app)},
            port=serv_port,
            address=serv_host,
            allow_websocket_origin=[f"{serv_host}:{serv_port}"],
        )
        self.bokehapp.start()

    def _make_bokeh_app(self, doc):
        """Bokeh document factory: attach an ``Aligner`` bound to the context.

        Wires the legacy driver's position-notify sink to the aligner's
        ``motorpos_q`` so ``Galil.update_aligner`` (called from
        ``query_axis_position``/``query_axis_moving``) keeps feeding live
        positions to the Bokeh widgets.
        """
        from helao.core.servers.vis import HelaoVis
        from helao.deploy.hte.layouts.aligner import Aligner

        app = HelaoVis(server_key=self._server_name, doc=doc)
        aligner = Aligner(app.vis, self.context)  # sets self.context.aligner = aligner
        self._driver.set_position_sink(aligner.motorpos_q)
        doc.aligner = aligner
        return doc

    # --- orchestration verbs (relocated from the driver) ------------------
    def run_aligner_precheck(self) -> tuple[bool, ErrorCodes]:
        if self._driver.blocked or not self._driver.galil_enabled:
            return False, ErrorCodes.in_progress
        if self.bokehapp is None or self.context.aligner is None:
            return False, ErrorCodes.not_available
        return True, ErrorCodes.none

    async def start_aligner_run(self, active) -> dict:
        self._driver.blocked = True
        self.context.aligner_plateid = active.action.action_params["plateid_or_pmpath"]
        self.context.aligner_active = active
        self.context.aligning_enabled = True
        active_dict = self.context.aligner_active.action.as_dict()
        _ = await self._driver.query_axis_moving(axis=self._driver.get_all_axis())
        return active_dict

    async def stop_aligner(self) -> ErrorCodes:
        if self.bokehapp is not None and self.context.aligner is not None:
            self.context.aligner.stop_align()
            return ErrorCodes.none
        return ErrorCodes.not_available

    def shutdown(self) -> None:
        """Cancel the aligner IO task on server shutdown (was ``Galil.shutdown``)."""
        aligner = self.context.aligner
        if aligner is not None:
            aligner.IOtask.cancel()
