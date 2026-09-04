"""AndorDriver variant whose wavelength axis comes from a lamp calibration.

For a station whose grating, central wavelength, slit and ND filter are set by
hand at the instrument and never written by HELAO. Imports nothing from
``spectrograph.py``, so ``pyAndorSpectrograph`` need not be installed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import numpy as np

from helao.helpers import helao_logging as logging

from . import wl_calibration as wlc
from .driver import AndorDriver

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

#: Warn about a calibration older than this. Not a refusal and not a hard
#: expiry: a station whose optics have not been touched is still calibrated.
#: It is the operator who knows whether the grating moved, and this is the
#: prompt to ask them.
STALE_AFTER_DAYS: float = 90.0


def _age_days(created: str) -> Optional[float]:
    """Age of an ISO-8601 ``created`` stamp in days, or ``None`` if unreadable.

    Never raises: a calibration with a malformed timestamp is still a usable
    wavelength axis, and losing the axis over the age check would be a far
    worse outcome than not knowing the age.
    """
    try:
        stamp = datetime.fromisoformat(created)
    except (TypeError, ValueError):
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - stamp).total_seconds() / 86400.0


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
        self._warn_about_provenance(calib, path)
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

    def _warn_about_provenance(self, calib: wlc.WavelengthCalibration, path) -> None:
        """Say so, loudly, when the record on disk may not describe this setup.

        Both variants write the same filename, so a station that measured a
        lamp for comparison while running on its spectrograph, then changed
        gratings, then flipped to ``wl_source: calibration``, silently adopts
        a fit taken under different optics. Warn rather than refuse: refusing
        would strand a station that calibrated legitimately before
        ``wl_source`` was recorded at all, and the axis it has is more likely
        right than absent.
        """
        if calib.wl_source != "calibration":
            LOGGER.warning(
                "wavelength calibration at %s records wl_source=%r, not "
                "'calibration'. A record written by the spectrograph variant "
                "was taken for COMPARISON, not as a live axis, and may "
                "predate a change of grating or central wavelength; "
                "'unknown' means it predates the field entirely. Re-run "
                "/%s/calibrate_wl if the optics have moved since %s.",
                path,
                calib.wl_source,
                self.server_key,
                calib.created,
            )
        age = _age_days(calib.created)
        if age is not None and age > STALE_AFTER_DAYS:
            LOGGER.warning(
                "wavelength calibration at %s is %.0f days old (created %s, "
                "limit %.0f days). Nothing here can tell whether the optics "
                "have moved since; re-run /%s/calibrate_wl if they have.",
                path,
                age,
                calib.created,
                STALE_AFTER_DAYS,
                self.server_key,
            )
