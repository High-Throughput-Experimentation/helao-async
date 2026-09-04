"""AndorDriver variant whose wavelength axis comes from a lamp calibration.

For a station whose grating, central wavelength, slit and ND filter are set by
hand at the instrument and never written by HELAO. Imports nothing from
``spectrograph.py``, so ``pyAndorSpectrograph`` need not be installed.
"""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Optional

import numpy as np

from helao.helpers import helao_logging as logging

from . import wl_calibration as wlc
from .driver import AndorDriver

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class AndorCalibratedDriver(AndorDriver):
    """Andor Zyla whose wavelength axis is read from a persisted lamp fit."""

    def __init__(self, config: dict = {}, server_key: str = "ANDOR"):
        """Construct without opening the camera or reading the calibration.

        Args:
            config: Driver configuration. ``states_root`` and ``host`` locate
                the calibration file; both fall back to sane values so a
                construct-test needs no station config.
            server_key: This server's key, part of the calibration filename
                because one host can run more than one andor server.
        """
        super().__init__(config=config)
        self.server_key = server_key

    def calibration_file(self) -> Path:
        """Where this server's persisted wavelength calibration lives.

        ``states_root`` is resolved in three steps, in order:

        1. ``self._base_hook.helaodirs.states_root`` -- the production path,
           once the base-hook/server_key wiring lands in a later task.
        2. ``config["states_root"]`` -- lets a test or a config pin it.
        3. The bare relative string ``"STATES"``, resolved against the
           process cwd. This is a last resort, not a normal case: a driver
           constructed as ``driver_class(config=self.server_params)`` (no
           ``_base_hook``, no ``states_root`` in ``params:``) hits it on
           every station today, so it logs a WARNING naming the absolute
           path actually used rather than failing silently.
        """
        helaodirs = getattr(getattr(self, "_base_hook", None), "helaodirs", None)
        states_root = getattr(helaodirs, "states_root", None)
        if states_root is None:
            states_root = self.config.get("states_root")
        if states_root is None:
            states_root = "STATES"
            LOGGER.warning(
                "no states_root from _base_hook.helaodirs or config; falling "
                "back to cwd-relative %s",
                Path(states_root).resolve(),
            )
        host = self.config.get("host") or socket.gethostname()
        return wlc.calibration_path(states_root, host, self.server_key)

    def _wavelengths(self) -> Optional[np.ndarray]:
        """The calibrated axis, or ``None`` when none has been measured yet.

        ``None`` rather than a raise: ``connect()`` must succeed on an
        uncalibrated station, because the calibration action runs on this same
        server and a refusing connect() would make the station uncalibratable.
        ``acquire`` is where the refusal belongs, and it reads ``wl_arr``.

        An unreadable *model* is a different case and does raise -- a record
        this build cannot evaluate must not be silently guessed at.
        """
        path = self.calibration_file()
        if not path.exists():
            LOGGER.warning(
                "no wavelength calibration at %s; acquire will refuse until "
                "/ANDOR/calibrate_wl has been run on this station",
                path,
            )
            return None
        calib = wlc.load(path)
        LOGGER.info(
            "loaded wavelength calibration: %d px, %d lines, rms %.4f nm, lamp %s, "
            "created %s",
            calib.n_pixels,
            calib.n_lines,
            calib.fit_rms_nm,
            calib.lamp,
            calib.created,
        )
        return wlc.evaluate(calib)
