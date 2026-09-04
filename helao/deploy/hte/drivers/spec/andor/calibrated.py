"""AndorDriver variant whose wavelength axis comes from a lamp calibration.

For a station whose grating, central wavelength, slit and ND filter are set by
hand at the instrument and never written by HELAO. Imports nothing from
``spectrograph.py``, so ``pyAndorSpectrograph`` need not be installed.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from helao.helpers import helao_logging as logging

from . import wl_calibration as wlc
from .driver import AndorDriver

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class AndorCalibratedDriver(AndorDriver):
    """Andor Zyla whose wavelength axis is read from a persisted lamp fit.

    ``__init__``, ``calibration_file`` and the ``server_key`` argument live on
    :class:`AndorDriver`: a spectrograph station also measures a lamp, to
    compare the fit against ``GetCalibration``. What is different here is that
    the fit is what ``acquire`` actually uses, which is what
    ``uses_lamp_calibration`` says.
    """

    #: This variant's live wavelength axis IS the lamp fit.
    uses_lamp_calibration = True

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
