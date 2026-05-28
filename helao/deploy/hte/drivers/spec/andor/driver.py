"""HelaoDriver wrapping the Andor Zyla camera and Andor ATSpectrograph.

Combines the ``pyAndorSDK3`` camera SDK with the ``pyAndorSpectrograph``
spectrograph control library so the action server can capture spectra,
manage cooling and select grating/filter/slit settings.
"""

from pyAndorSDK3 import AndorSDK3, CameraException
import numpy as np
import time as time
import pandas as pd
from typing import Optional
from pyAndorSpectrograph.spectrograph import ATSpectrograph

# save a default log file system temp
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

from helao.core.drivers.helao_driver import (
    HelaoDriver,
    DriverResponse,
    DriverStatus,
    DriverResponseType,
)


class AndorDriver(HelaoDriver):
    """HelaoDriver for an Andor Zyla camera coupled to an ATSpectrograph.

    Opens a single camera context for the lifetime of the driver, sets up
    imaging defaults, configures the spectrograph (grating, central
    wavelength, slit, ND filter) and caches frame metadata (pixel width,
    wavelength array, AOI size, stride and timestamp clock frequency).

    Attributes:
        cam: The underlying ``AndorSDK3`` camera handle.
        pixel_width: Detector pixel width in micrometres.
        wl_arr: Calibrated wavelength array for the configured AOI.
        horiz_pixels: AOI width in pixels.
        vert_pixels: AOI height in pixels.
        stride: Buffer row stride in bytes.
        clock_hz: Timestamp clock frequency, used to convert ticks to seconds.
        frame: Last frame index produced by an acquisition loop.
    """

    cam: AndorSDK3
    pixel_width: float
    wl_arr: np.ndarray
    horiz_pixels: float
    vert_pixels: float
    stride: float
    clock_hz: float
    frame: int

    def __init__(self, config: dict = {}):
        """Construct the driver and immediately open the camera.

        Reads ``dev_id`` from ``config`` (default ``0``), instantiates the
        SDK, calls :meth:`connect`, and marks the driver ready on success.

        Args:
            config: Driver configuration dict from the action server.
        """
        super().__init__(config=config)
        # get params from config or use defaults
        self.cam = None
        self.pixel_width = None
        self.wl_arr = None
        self.horiz_pixels = None
        self.vert_pixels = None
        self.stride = None
        self.clock_hz = None

        self.timeout = 5000

        self.sdk3 = AndorSDK3()
        self.device_id = self.config.get("dev_id", 0)
        LOGGER.info(f"using device_id {self.device_id} from config")
        # if single context is used and held for the entire session, connect here, otherwise have executor call self.connect() in self.setup()
        self.connect()
        self.ready = True

    def connect(self) -> DriverResponse:
        """Open the camera, configure imaging and prime spectrograph metadata.

        Returns:
            A success :class:`DriverResponse` on connect, ``failed`` on error.
        """
        try:
            self.cam = self.sdk3.GetCamera(self.device_id)
            LOGGER.debug(f"connected to {self.device_id}")
            self.pixel_width = self.setup_image()
            self.wl_arr = self.setup_spectroscope(self.pixel_width)
            self.horiz_pixels, self.vert_pixels, self.stride, self.clock_hz = (
                self.get_meta_data()
            )
            response = DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception:
            LOGGER.error("get_status connection", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )

        return response

    def cool(self):
        """Enable sensor cooling and block until the temperature stabilises.

        Polls the sensor every 5 s until ``TemperatureStatus`` reports
        ``Stabilised``. The camera will not warm up again until either
        :meth:`warm_and_close` is invoked or ``self.cam.close()`` is called.

        Raises:
            RuntimeError: If the camera reports a ``Fault`` temperature
                status while cooling.
        """
        self.cam.SensorCooling = True
        while self.cam.TemperatureStatus != "Stabilised":
            time.sleep(5)
            LOGGER.info("Temperature: {:.5f}C".format(self.cam.SensorTemperature))
            LOGGER.info("Status: '{}'".format(self.cam.TemperatureStatus))
            if self.cam.TemperatureStatus == "Fault":
                err_str = "Camera faulted when cooling to target temperature"
                raise RuntimeError(err_str)

    def set_cooldown(self, cool: bool = True) -> DriverResponse:
        """Enable or disable sensor cooling without blocking.

        Args:
            cool: ``True`` to enable cooling, ``False`` to disable.

        Returns:
            A :class:`DriverResponse` indicating success/failure.
        """
        try:
            self.cam.SensorCooling = cool
            response = DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception:
            LOGGER.error("set_cooldown failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        return response

    def check_temperature(self) -> DriverResponse:
        """Return current sensor temperature and cooler status.

        Returns:
            A :class:`DriverResponse` whose ``data`` is
            ``{"temp": float, "status": str}``.
        """
        try:
            data = {
                "temp": self.cam.SensorTemperature,
                "status": self.cam.TemperatureStatus,
            }
            response = DriverResponse(
                response=DriverResponseType.success, data=data, status=DriverStatus.ok
            )
        except Exception:
            LOGGER.error("check_temperature failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        return response

    def setup_image(self, exposure_time=0.0098) -> float:
        """Configure the camera for single-image (vertical-bin=1) acquisition.

        Sets 16-bit Mono32 encoding, rolling shutter, 280 MHz pixel readout,
        fixed cycle mode and the requested exposure time, then returns the
        sensor pixel width used downstream by the spectrograph calibration.

        Args:
            exposure_time: Exposure time in seconds (default ``0.0098``).

        Returns:
            Detector pixel width in micrometres.
        """
        self.cam.AOIVBin = 1  # readout on a single row
        self.cam.SimplePreAmpGainControl = "16-bit (low noise & high well capacity)"
        self.cam.AOILayout = "Image"
        self.cam.PixelEncoding = (
            "Mono32"  # mono 32-bit encoding to get the full 32-bit range
        )
        self.cam.CycleMode = "Fixed"  # fixed
        self.cam.ElectronicShutteringMode = "Rolling"  # rolling shutter
        self.cam.PixelReadoutRate = "280 MHz"  # 280 MHz readout rate
        self.cam.ExposureTime = exposure_time  # 50ms exposure time
        self.cam.MultitrackBinned = True
        self.cam.VerticallyCentreAOI = True
        # LOGGER.info('timestamp clock:')
        # LOGGER.info(sdkcamhandle.TimestampClock)
        # LOGGER.info('redout time:')
        # LOGGER.info(sdkcamhandle.ReadoutTime)
        # LOGGER.info('Pixel width:')
        # LOGGER.info(sdkcamhandle.PixelWidth)
        return self.cam.PixelWidth

    def image_and_check_dynamic_range(self, exposure_time=0.0098) -> tuple:
        """Acquire one image and evaluate its dynamic-range optimality.

        The optimality value is ``1 + |63000 - max| / 63000``; values close
        to 1 are near-optimal, negative values indicate over-exposure. The
        range bool is ``True`` when the maximum lies in ``[55536, 65536)``.

        Args:
            exposure_time: Exposure time in seconds.

        Returns:
            ``(acquisition, max_pixel, range_bool, optimality)``.
        """
        _ = self.setup_image(exposure_time)
        LOGGER.info(self.cam.SerialNumber)
        test = self.cam.acquire()
        max = test.image.max()
        optimality = 1 + np.abs(63000 - max) / 63000
        range_bool = max < (2**16) and max > ((2**16) - 10000)
        # #
        # if len(self.wl_arr) == 0:
        #     plt.imshow(test.image, cmap="hot")
        # else:
        #     # use imshow but set the x-axis to be the WL
        #     LOGGER.info("using the WL array")
        #     plt.figure(figsize=(8, 8))
        #     plt.imshow(
        #         test.image,
        #         cmap="hot",
        #         extent=[self.wl_arr[0], self.wl_arr[-1], 0, 2160],
        #     )

        return test, max, range_bool, optimality

    def get_meta_data(self) -> tuple:
        """Enable metadata, take one image and log/return key frame fields.

        Turns on metadata (including IRIG if available), performs an
        acquisition and logs frame info, timestamp and cooler info.

        Returns:
            ``(width, height, stride, timestamp_clock_frequency_hz)``.
        """
        self.cam.MetadataEnable = True  # Turn on Metadata
        self.setup_image()
        # Turn IRIG on if implemented in camera
        irig_enabled = False
        try:
            self.cam.MetadataIRIG = True
            irig_enabled = True
        except AttributeError:
            LOGGER.info("MetaDateIRIG not implemented")

        # Acquire an image
        acq = self.cam.acquire()
        if self.cam.MetadataEnable:
            if self.cam.MetadataFrameInfo:
                LOGGER.info("\n-----------\nFrame Info\n-----------")
                LOGGER.info(f"Width:\t\t {acq.metadata.width}")
                LOGGER.info(f"Height:\t\t {acq.metadata.height}")
                LOGGER.info(f"Stride:\t\t {acq.metadata.stride}")
                LOGGER.info(f"Pixel Encoding:\t {acq.metadata.pixelencoding}")

            if self.cam.MetadataTimestamp:
                LOGGER.info("\n-----------\nTime Stamp\n-----------")
                LOGGER.info(f"TimeStamp (ticks):\t {acq.metadata.timestamp}")
                LOGGER.info(
                    f"frequency (Hz):\t        {self.cam.TimestampClockFrequency}"
                )

            if irig_enabled:
                LOGGER.info("\n----------\nIRIG Data\n----------")
                LOGGER.info(f"Nanoseconds:\t {acq.metadata.irig_nanoseconds}")
                LOGGER.info(f"Seconds:\t {acq.metadata.irig_seconds}")
                LOGGER.info(f"Minutes:\t {acq.metadata.irig_minutes}")
                LOGGER.info(f"Hours:\t\t {acq.metadata.irig_hours}")
                LOGGER.info(f"Days:\t\t {acq.metadata.irig_days}")
                LOGGER.info(f"Years:\t\t {acq.metadata.irig_years}")
        LOGGER.info("\n-----------\nCooler Info\n-----------")
        LOGGER.info("Temperature: {:.5f}C".format(self.cam.SensorTemperature))
        LOGGER.info("Status: '{}'".format(self.cam.TemperatureStatus))

        return (
            acq.metadata.width,
            acq.metadata.height,
            acq.metadata.stride,
            self.cam.TimestampClockFrequency,
        )

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

                (shm, grat) = spc.GetGrating(0)
                LOGGER.info("Function GetGrating returned: {} Grat".format(grat))

                shm = spc.SetWavelength(0, centralWL)
                LOGGER.info(
                    "Function SetWavelength returned: {}".format(
                        spc.GetFunctionReturnDescription(shm, 64)[1]
                    )
                )

                (shm, wave) = spc.GetWavelength(0)
                LOGGER.info(
                    "Function GetWavelength returned: {} Wavelength: {}".format(
                        spc.GetFunctionReturnDescription(shm, 64)[1], wave
                    )
                )

                (shm, min, max) = spc.GetWavelengthLimits(0, grat)
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
                ()

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

                (shm, grat) = spc.GetGrating(0)
                LOGGER.info("Function GetGrating returned: {} Grat".format(grat))

                shm = spc.SetWavelength(0, 672.26)
                LOGGER.info(
                    "Function SetWavelength returned: {}".format(
                        spc.GetFunctionReturnDescription(shm, 64)[1]
                    )
                )

                (shm, wave) = spc.GetWavelength(0)
                LOGGER.info(
                    "Function GetWavelength returned: {} Wavelength: {}".format(
                        spc.GetFunctionReturnDescription(shm, 64)[1], wave
                    )
                )

                (shm, min, max) = spc.GetWavelengthLimits(0, grat)
                LOGGER.info(
                    "Function GetWavelengthLimits returned: {} Wavelength Min: {} Wavelength Max: {}".format(
                        spc.GetFunctionReturnDescription(shm, 64)[1], min, max
                    )
                )

                (shm, c0, c1, c2, c3) = spc.GetPixelCalibrationCoefficients(
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

    def warm_and_close(self, warmup: bool):
        """Optionally warm the sensor then close the camera handle.

        When ``warmup`` is ``True``, disables sensor cooling and polls every
        5 s until the sensor reaches at least 20 C with a ``Stabilised``
        status, then calls ``cam.close()``. When ``False``, leaves the
        camera as-is.

        Args:
            warmup: Whether to warm the sensor before closing.

        Raises:
            RuntimeError: If the camera reports a temperature ``Fault``.
        """
        if warmup:
            self.cam.SensorCooling = False
            while (
                self.cam.TemperatureStatus != "Stabilised"
                and self.cam.SensorTemperature < 20
            ):
                time.sleep(5)
                LOGGER.info("Temperature: {:.5f}C".format(self.cam.SensorTemperature))
                LOGGER.info("Status: '{}'".format(self.cam.TemperatureStatus))
                if self.cam.TemperatureStatus == "Fault":
                    err_str = "Camera faulted when cooling to target temperature"
                    raise RuntimeError(err_str)
            self.cam.close()
        else:
            LOGGER.info("Warmup is set to False, so the camera will not warm up. ")

    def generate_spectral_array(self, WL_arr, acqs, clockHz) -> pd.DataFrame:
        """Stack acquisitions into a wavelength-vs-time spectra DataFrame.

        Builds a ``pandas.DataFrame`` whose rows are wavelengths from
        ``WL_arr`` and whose columns are clock-derived tick times in seconds
        relative to the first frame.

        Args:
            WL_arr: Wavelength array (DataFrame index).
            acqs: Container holding the acquisition objects.
            clockHz: Camera timestamp clock frequency in Hz.

        Returns:
            DataFrame of spectra indexed by wavelength, columns by tick time.
        """

        acqs = list(acqs[0])

        LOGGER.info(acqs[0].image[0])
        # generate a numpy array with dimensions of len(acqs[0]) and len(acqs) and fill with zeros
        Spectra = np.zeros((len(acqs[0].image[0]), len(acqs)))
        ticks = np.zeros(len(acqs))

        # use list comprehension to fill the numpy array with the image data from the aquisition object
        Spectra = np.array([acq.image[0] for acq in acqs]).T
        # use list comprehension to fill the numpy array with the timestamp data from the aquisition object
        ticks = np.array([acq.metadata.timestamp for acq in acqs])

        Spectra = pd.DataFrame(Spectra)
        # get the time elapsed in number of ticks of the clock
        ticks = ticks - ticks[0]
        # convert the ticks to seconds
        Tick_time = ticks / clockHz

        # set the collumn names of the spectra dataframe to the tick_time
        Spectra.columns = Tick_time
        # set the index of the spectra dataframe to the WL_arr
        Spectra.index = WL_arr

        return Spectra

    def get_status(self, retries: int = 5) -> DriverResponse:
        """Return the current driver status.

        Args:
            retries: Unused retry hint kept for interface symmetry.

        Returns:
            A :class:`DriverResponse` with status :class:`DriverStatus`.
        """
        try:
            response = DriverResponse(
                response=DriverResponseType.success,
                data={},
                status=DriverStatus.ok,
            )
        except Exception:
            LOGGER.error("get_status failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        return response

    def setup(
        self, exp_time: float = 0.0098, framerate: float = 98, buffer_count: int = 10
    ) -> DriverResponse:
        """Configure continuous full-AOI acquisition and queue frame buffers.

        Sets vertical binning over the full AOI, Mono32 encoding, rolling
        shutter with overlap mode, 280 MHz readout, continuous cycle mode,
        and the requested exposure/framerate, then queues ``buffer_count``
        buffers for the SDK to fill.

        Args:
            exp_time: Exposure time in seconds.
            framerate: Target framerate in Hz.
            buffer_count: Number of buffers to pre-queue.

        Returns:
            Success :class:`DriverResponse` once the camera is armed.
        """
        try:
            # external start will start the camera upon 5V TTL signal. The camera will then aquire as fast as possible
            self.cam.AOIVBin = 2160  # full verrtical binning over the  AOI
            self.cam.SimplePreAmpGainControl = (
                "16-bit (low noise & high well capacity)"  # Single Pixel is 16 bit
            )
            self.cam.PixelEncoding = "Mono32"  # After ADC conversion pixel values are added with size of 32 bit
            self.cam.ElectronicShutteringMode = "Rolling"
            # Rolling shutter comes with health warnings but is the fastest.
            # take care with rolling shutter as technically the image is not taken at the same time but line by line
            # meaning the last row of one image is taken after the first row of the next image.
            # see section 5.11.5 and figure 21 of the Zyla manual for more information.
            self.cam.Overlap = True  # overlap mode also carries a health warning but is needed to collect quickly for long aquisitions.
            # see section 5.11.5 and figure 21 of the Zyla manual for more information.
            self.cam.PixelReadoutRate = "280 MHz"  # The fastest readout rate. This is 560 MHz in solis. I don't know why but these correspond to the same readout time
            self.cam.CycleMode = "Continuous"  # will go on forever until self.cam.AcquisitionStop() is called
            self.cam.ExposureTime = exp_time  # Default to fastest exposure time permissible in this AOI is the readout time of 9.8 ms
            self.cam.FrameRate = framerate  # The fastest framerate permissible in this AOI is the readout time default to 98 Hz

            imgsize = (
                self.cam.ImageSizeBytes
            )  # Returns the buffer size in bytes required to store the data for one frame. This
            # will be affected by the Area of Interest size, binning and whether metadata is  appended to the data stream

            # this makes buffer_count buffers in the camera
            for _ in range(buffer_count):
                # each buffer is a numpy array of size imgsize containing unsigned bytes
                buf = np.empty((imgsize,), dtype="B")
                # this creates a new buffer in the camera for the next image
                self.cam.queue(buf, imgsize)

            self.frame = None  # initialise frame to None

            response = DriverResponse(
                response=DriverResponseType.success,
                message="setup complete",
                status=DriverStatus.ok,
            )
        except Exception:
            LOGGER.error("setup failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
            self.cleanup()
        return response

    def set_trigger(self, external: bool = True) -> DriverResponse:
        """Select trigger source and start the acquisition.

        Args:
            external: ``True`` for ``External Start``, ``False`` for
                ``Software`` triggering.

        Returns:
            :class:`DriverResponse` with ``busy`` status when armed.
        """
        try:
            # call function to activate External Trigger mode
            if external:
                self.cam.TriggerMode = "External Start"
            else:
                self.cam.TriggerMode = "Software"
            self.cam.AcquisitionStart()
            response = DriverResponse(
                response=DriverResponseType.success,
                message="trigger set",
                status=DriverStatus.busy,
            )
        except Exception:
            LOGGER.error("set_trigger failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.error,
            )
            self.cleanup()
        return response

    def get_data(
        self,
        frames: int,
        total_duration: float,
        external: bool = True,
        first_tick: Optional[float] = None,
    ) -> DriverResponse:
        """Pull up to ``frames`` spectra from queued buffers.

        Drains the camera buffer queue, optionally issuing software
        triggers, requeues each buffer, and stops early once the tick-time
        delta from ``first_tick`` reaches ``total_duration``.

        Args:
            frames: Maximum number of frames to read.
            total_duration: Stop once this many seconds (relative to
                ``first_tick``) have elapsed.
            external: ``False`` to issue a software trigger each frame.
            first_tick: Reference tick time for the duration check.

        Returns:
            :class:`DriverResponse` whose ``data`` is
            ``{"tick_time": [...], "ch_NNNN": [...]}``.
        """
        try:
            status = DriverStatus.busy
            data_dict = {"tick_time": []}
            data_dict.update({f"ch_{i:04}": [] for i in range(self.wl_arr.size)})
            for _ in range(frames):
                try:
                    if not external:
                        self.cam.SoftwareTrigger()
                    acq = self.cam.wait_buffer(self.timeout)
                    self.cam.queue(
                        np.zeros(acq._np_data.shape), self.cam.ImageSizeBytes
                    )  # requeue the buffer
                    spectrum = acq.image[0]
                    tick_time = acq.metadata.timestamp / self.clock_hz
                    data_dict["tick_time"].append(tick_time)
                    for i, x in enumerate(spectrum):
                        data_dict[f"ch_{i:04}"].append(int(x))
                    if first_tick is not None:
                        if tick_time - first_tick >= total_duration:
                            status = DriverStatus.ok
                            break
                    status = DriverStatus.busy
                except CameraException:
                    status = DriverStatus.error
                    break
            response = DriverResponse(
                response=DriverResponseType.success,
                message="",
                data=data_dict if data_dict["tick_time"] else {},
                status=status,
            )
        except Exception:
            LOGGER.error("get_data failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.error,
            )
        return response

    def stop(self) -> DriverResponse:
        """Abort the ongoing acquisition via ``AcquisitionStop``."""
        try:
            # call function to stop ongoing acquisition
            self.cam.AcquisitionStop()
            response = DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception:
            LOGGER.error("stop failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        return response

    def cleanup(self) -> DriverResponse:
        """Stop acquisition and flush queued buffers."""
        try:
            self.cam.AcquisitionStop()
            self.cam.flush()
            response = DriverResponse(
                response=DriverResponseType.success,
                message="cleanup complete",
                status=DriverStatus.ok,
            )
        except Exception:
            LOGGER.error("cleanup failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.error,
            )
        return response

    def disconnect(self) -> DriverResponse:
        """Close the camera handle if open and release the SDK resource."""
        try:
            if self.cam is not None:
                self.cam.close()
                self.cam = None
            response = DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception:
            LOGGER.error("disconnect failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        return response

    def reset(self) -> DriverResponse:
        """Clean up, disconnect and reconnect the camera."""
        try:
            if self.cam is not None:
                self.cleanup()
                self.disconnect()
                self.connect()
            response = DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception:
            LOGGER.error("reset error", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        return response

    def shutdown(self) -> None:
        """BaseAPI shutdown hook; disconnects the camera."""
        self.disconnect()
