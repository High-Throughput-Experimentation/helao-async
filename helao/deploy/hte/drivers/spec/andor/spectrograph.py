"""AndorDriver variant driving an Andor ATSpectrograph.

The only module in the tree that names ``pyAndorSpectrograph``. A station
whose optics are set by hand runs a calibrated variant instead and does not
need the package installed at all.

``setup_spectroscope`` and ``adjust_ND`` are moved here verbatim from
``driver.py``; each opens and closes its own ``ATSpectrograph`` handle, so
there is no shared session between them.
"""

from __future__ import annotations

import numpy as np

from helao.core.drivers.helao_driver import (
    DriverResponse,
    DriverResponseType,
    DriverStatus,
)
from helao.helpers import helao_logging as logging

from .driver import AndorDriver

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


def _load_spectrograph():
    """Bind the spectrograph SDK. Called before the spectrograph is touched."""
    global ATSpectrograph
    from pyAndorSpectrograph.spectrograph import ATSpectrograph


class AndorSpectrographDriver(AndorDriver):
    """Andor Zyla coupled to an ATSpectrograph.

    The wavelength array comes from the spectrograph's own ``GetCalibration``
    after the grating, central wavelength, slit and ND filter are set.
    """

    def _wavelengths(self) -> np.ndarray:
        return self.setup_spectroscope(self.pixel_width)

    # setup_spectroscope and adjust_ND are moved verbatim from driver.py.

    def setup_spectroscope(
        self,
        PixelWidth,
        centralWL=697.26,
        NumHorizPixels=2560,
        ND_filter_num=1,
        slit_width_um=200,
    ) -> np.ndarray:
        """Initialise the ATSpectrograph and return the wavelength array.

        Sets the detector offset, grating, central wavelength, slit width
        and ND filter, then reads the calibrated wavelength array for the
        requested number of horizontal pixels.

        Args:
            PixelWidth: Detector pixel width (from :meth:`setup_image`).
            centralWL: Central wavelength in nm.
            NumHorizPixels: Number of horizontal pixels in the AOI.
            ND_filter_num: ND filter position in ``1..6``.
            slit_width_um: Slit width in micrometres (``10..200``).

        Returns:
            Calibrated wavelength array of length ``NumHorizPixels``, or
            ``None`` when the filter/slit arguments are out of range.
        """
        ## the return from GetWavelengthLimits looks weird to me :Wavelength Min: 0.0 Wavelength Max: 11127.045898
        # everything else looks fine and will get calibrated in the next block
        if ND_filter_num > 6:
            LOGGER.info("Filter number is too high")
            return
        elif ND_filter_num < 1:
            LOGGER.info("Filter number is too low")
            return
        elif slit_width_um > 200:
            LOGGER.info("Slit width is too high")
            return
        elif slit_width_um < 10:
            LOGGER.info("Slit width is too low")
            return
        # Load libraries
        _load_spectrograph()
        spc = ATSpectrograph()

        # Initialize libraries
        shm = spc.Initialize("")

        LOGGER.info(
            "Function Initialize returned {}".format(
                spc.GetFunctionReturnDescription(shm, 64)[1]
            )
        )

        LOGGER.info("Function Initialize returned {}".format(shm))

        if True:
            if ATSpectrograph.ATSPECTROGRAPH_SUCCESS == shm:

                shm = spc.GetDetectorOffset(0, 0, 0)
                LOGGER.info(
                    f"success code and detector offset is currently {spc.GetDetectorOffset(0, 0, 0)}"
                )
                shm = spc.SetDetectorOffset(0, 0, 0, 170)
                LOGGER.info(
                    f"Offset was set to {spc.GetDetectorOffset(0, 0, 0)} This is system specific and should be changed if the system changes"
                )

                # Configure Spectrograph
                shm = spc.SetGrating(0, 1)
                LOGGER.info(
                    "Function SetGrating returned {}".format(
                        spc.GetFunctionReturnDescription(shm, 64)[1]
                    )
                )

                shm, grat = spc.GetGrating(0)
                LOGGER.info("Function GetGrating returned: {} Grat".format(grat))

                shm = spc.SetWavelength(0, centralWL)
                LOGGER.info(
                    "Function SetWavelength returned: {}".format(
                        spc.GetFunctionReturnDescription(shm, 64)[1]
                    )
                )

                shm, wave = spc.GetWavelength(0)
                LOGGER.info(
                    "Function GetWavelength returned: {} Wavelength: {}".format(
                        spc.GetFunctionReturnDescription(shm, 64)[1], wave
                    )
                )

                shm, min, max = spc.GetWavelengthLimits(0, grat)
                LOGGER.info(
                    "Function GetWavelengthLimits returned: {} Wavelength Min: {} Wavelength Max: {}".format(
                        spc.GetFunctionReturnDescription(shm, 64)[1], min, max
                    )
                )

                # (shm, c0, c1, c2, c3) = spc.GetPixelCalibrationCoefficients(0) # these dont seem to be usefull for me
                # coeff = [c0,c1,c2,c3]
                if shm == 20202:
                    LOGGER.info("return code is Success:")
                LOGGER.info(shm)
                LOGGER.info("::::::::::::::::::::::::")
                LOGGER.info(spc.IsFilterPresent(shm))
                if spc.IsSlitPresent(0, 1) == (20202, 1):
                    spc.SetSlitWidth(0, 1, slit_width_um)
                    LOGGER.info("slit set")
                if spc.IsFilterPresent(0) == (20202, 1):
                    spc.SetFilter(0, ND_filter_num)
                    LOGGER.info("filter set")

            else:
                LOGGER.info("Cannot continue, could not initialise Spectrograph")

            # important calibration stuff I keep out of the big block just to make it easier

            spc.SetNumberPixels(0, NumHorizPixels)
            LOGGER.info(PixelWidth)
            spc.SetPixelWidth(0, PixelWidth)
            LOGGER.info(spc.GetNumberPixels(0))
            LOGGER.info(spc.GetPixelWidth(0))
            WL_array = np.array(spc.GetCalibration(0, 2560)[1])
            shm = spc.Close()
            return WL_array

    def adjust_ND(self) -> DriverResponse:
        """Sweep the ND filter wheel and pick the most optimal position.

        Iterates filters 1..6, evaluates each via
        :meth:`image_and_check_dynamic_range`, discards positions whose max
        pixel exceeds 54000, and applies the best filter. Returns the per-
        filter ``max_array``/``optimality_array`` and the chosen position.

        Returns:
            A :class:`DriverResponse` whose ``data`` contains ``max_array``,
            ``optimality_array`` and ``ND_filter_num``.
        """

        adjust_success = False
        try:
            # Load libraries
            _load_spectrograph()
            spc = ATSpectrograph()

            # Initialize libraries
            shm = spc.Initialize("")

            LOGGER.info(
                "Function Initialize returned {}".format(
                    spc.GetFunctionReturnDescription(shm, 64)[1]
                )
            )

            LOGGER.info("Function Initialize returned {}".format(shm))

            if ATSpectrograph.ATSPECTROGRAPH_SUCCESS == shm:

                shm = spc.GetDetectorOffset(0, 0, 0)
                LOGGER.info(
                    f"success code and detector offset is currently {spc.GetDetectorOffset(0, 0, 0)}"
                )
                shm = spc.SetDetectorOffset(0, 0, 0, 170)
                LOGGER.info(
                    f"Offset was set to {spc.GetDetectorOffset(0, 0, 0)} This is system specific and should be changed if the system changes"
                )

                # Configure Spectrograph
                shm = spc.SetGrating(0, 1)
                LOGGER.info(
                    "Function SetGrating returned {}".format(
                        spc.GetFunctionReturnDescription(shm, 64)[1]
                    )
                )

                shm, grat = spc.GetGrating(0)
                LOGGER.info("Function GetGrating returned: {} Grat".format(grat))

                shm = spc.SetWavelength(0, 672.26)
                LOGGER.info(
                    "Function SetWavelength returned: {}".format(
                        spc.GetFunctionReturnDescription(shm, 64)[1]
                    )
                )

                shm, wave = spc.GetWavelength(0)
                LOGGER.info(
                    "Function GetWavelength returned: {} Wavelength: {}".format(
                        spc.GetFunctionReturnDescription(shm, 64)[1], wave
                    )
                )

                shm, min, max = spc.GetWavelengthLimits(0, grat)
                LOGGER.info(
                    "Function GetWavelengthLimits returned: {} Wavelength Min: {} Wavelength Max: {}".format(
                        spc.GetFunctionReturnDescription(shm, 64)[1], min, max
                    )
                )

                shm, c0, c1, c2, c3 = spc.GetPixelCalibrationCoefficients(
                    0
                )  # these dont seem to be usefull for me
                coeff = [c0, c1, c2, c3]
                LOGGER.debug(f"pixel calibration coefficients: {coeff}")
                if shm == 20202:
                    LOGGER.info("return code is Success:")
                LOGGER.info(shm)
                LOGGER.info("::::::::::::::::::::::::")
                LOGGER.info(spc.IsFilterPresent(shm))
                if spc.IsSlitPresent(0, 1) == (20202, 1):
                    spc.SetSlitWidth(0, 1, 10)
                    LOGGER.info("slit set")
                if spc.IsFilterPresent(0) == (20202, 1):
                    spc.SetFilter(0, 1)
                    LOGGER.info("filter set")
                    # create a np array of zeros of length 6
                    optimality_array = np.zeros(6)
                    max_array = np.zeros(6)
                    # create a for loop iterating from 1 to 6, setting each filter and getting the optimality value
                    for i in range(1, 7):
                        spc.SetFilter(0, i)
                        _, max, _, optimality = self.image_and_check_dynamic_range()
                        optimality_array[i - 1] = optimality
                        max_array[i - 1] = max
                    # find the filter with the maximum optimality value
                    ND_filter_num = np.argmin(optimality_array)
                    # if max_array[ND_filter_num] is above 54000, set optimality[ND_filter_num] to 999
                    for i in range(7):
                        if max_array[ND_filter_num] > 54000:
                            optimality_array[ND_filter_num] = 999
                            ND_filter_num = np.argmin(optimality_array)
                    else:
                        ND_filter_num = np.argmin(optimality_array)
                    spc.SetFilter(0, ND_filter_num)

                    LOGGER.info(
                        f"filter number set to {ND_filter_num}, with optimality value of {optimality_array[ND_filter_num]} and a max intensity of {max_array[ND_filter_num]}"
                    )
                adjust_success = True
                data = {
                    "max_array": max_array,
                    "optimality_array": optimality_array,
                    "ND_filter_num": ND_filter_num,
                }
            else:
                LOGGER.info("Cannot continue, could not initialise Spectrograph")
                data = {}
            shm = spc.Close()
            response = DriverResponse(
                response=(
                    DriverResponseType.success
                    if adjust_success
                    else DriverResponseType.failed
                ),
                data=data,
                status=DriverStatus.ok,
            )
        except Exception:
            LOGGER.error("adjust_ND failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        return response
