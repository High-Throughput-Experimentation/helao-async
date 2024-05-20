""" Andor Camera driver for Helao
"""

from pyAndorSDK3 import AndorSDK3
from collections import deque
import numpy as np
import time as time
import pandas as pd
import matplotlib.pyplot as plt
from pyAndorSpectrograph.spectrograph import ATSpectrograph

# save a default log file system temp
from helao.helpers import logging

if logging.LOGGER is None:
    LOGGER = logging.make_logger(logger_name="andor_driver_standalone")
else:
    LOGGER = logging.LOGGER


from helao.drivers.helao_driver import (
    HelaoDriver,
    DriverResponse,
    DriverStatus,
    DriverResponseType,
)


class AndorDriver(HelaoDriver):
    cam: AndorSDK3
    pixel_width: float
    wl_arr: np.ndarray
    horiz_pixels: float
    vert_pixels: float
    stride: float
    clock_hz: float
    frame: int
    acqs: deque

    def __init__(self, config: dict = {}):
        super().__init__(config=config)
        # get params from config or use defaults
        self.cam = None
        self.pixel_width = None
        self.wl_arr = None
        self.horiz_pixels = None
        self.vert_pixels = None
        self.stride = None
        self.clock_hz = None

        self.sdk3 = AndorSDK3()
        self.device_id = self.config.get("dev_id", 0)
        LOGGER.info(f"using device_id {self.device_id} from config")
        # if single context is used and held for the entire session, connect here, otherwise have executor call self.connect() in self.setup()
        self.connect()
        self.ready = True

    def connect(self) -> DriverResponse:
        """Open connection to resource."""
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
        except Exception as exc:
            _, _, err_tup = exc.args
            if "In use by another script" in err_tup[0]:
                response = DriverResponse(
                    response=DriverResponseType.success, status=DriverStatus.busy
                )
            else:
                LOGGER.error("get_status connection", exc_info=True)
                response = DriverResponse(
                    response=DriverResponseType.failed, status=DriverStatus.error
                )

        return response

    def cool(self):
        """This function cools the camera to 20 degrees C below ambient temperature. The camera will not warm untill told unless self.cam.close() is called.
        The function will wait until the camera is at the target temperature before returning.
            args: cam: AndorSDK3 object
        """
        while self.self.cam.TemperatureStatus != "Stabilised":
            time.sleep(5)
            LOGGER.info(
                "Temperature: {:.5f}C".format(self.self.cam.SensorTemperature), end="  "
            )
            LOGGER.info("Status: '{}'".format(self.self.cam.TemperatureStatus))
            if self.self.cam.TemperatureStatus == "Fault":
                err_str = "Camera faulted when cooling to target temperature"
                raise RuntimeError(err_str)

    def setup_image(self, exposure_time=0.0098):
        """This function sets up the camera to take a single image with the desired framerate and exposure time. It returns the pixel width of the camera
        Which is used to convert pixels to wavelengths in the spectrograph fucntions. Start with framerate is 100 Hz and exposure time is 9.8 ms.
        args: cam: camera object, framerate: desired framerate , exposure_time: desired exposure time defaults are max values for the camera
        """
        self.self.cam.AOIVBin = 1  # readout on a single row
        self.self.cam.SimplePreAmpGainControl = (
            "16-bit (low noise & high well capacity)"
        )
        self.self.cam.AOILayout = "Image"
        self.self.cam.PixelEncoding = (
            "Mono32"  # mono 32-bit encoding to get the full 32-bit range
        )
        self.self.cam.CycleMode = "Fixed"  # fixed
        self.self.cam.ElectronicShutteringMode = "Rolling"  # rolling shutter
        self.self.cam.PixelReadoutRate = "280 MHz"  # 280 MHz readout rate
        self.self.cam.ExposureTime = exposure_time  # 50ms exposure time
        self.self.cam.MultitrackBinned = True
        self.self.cam.VerticallyCentreAOI = True
        # LOGGER.info('timestamp clock:')
        # LOGGER.info(sdkcamhandle.TimestampClock)
        # LOGGER.info('redout time:')
        # LOGGER.info(sdkcamhandle.ReadoutTime)
        # LOGGER.info('Pixel width:')
        # LOGGER.info(sdkcamhandle.PixelWidth)
        return self.self.cam.PixelWidth

    def image_and_check_dynamic_range(self, WL=[], exposure_time=0.0098):
        """This function collects a single image and checks that the maximum value is in the optimum dynamic range for the measurment.
        It returns the image, the maximum pixel value and a boolean that is true if the maximum value is in the optimum dynamic range
        defined by the range 65536-55536.
        An optimality value is calculated as 1- the absolute difference between the maximum value and an approximate optimum max value of 63000, normalised by 63000.
        An optimality close to 1 indicates that the maximum value is close to the optimum value.
        An optimality that is negative indicates that the source is too bright.  To search for the optimum value, the range bool and the optimality value can be used together.
        args: cam: AndorSDK3 object
        """
        _ = self.setup_image(exposure_time)
        LOGGER.info(self.self.cam.SerialNumber)
        test = self.self.cam.acquire()
        max = test.image.max()
        optimality = 1 + np.abs(63000 - max) / 63000
        range_bool = max < (2**16) and max > ((2**16) - 10000)
        if len(WL) == 0:
            plt.imshow(test.image, cmap="hot")
        else:
            # use imshow but set the x-axis to be the WL
            LOGGER.info("using the WL array")
            plt.figure(figsize=(8, 8))
            plt.imshow(test.image, cmap="hot", extent=[WL[0], WL[-1], 0, 2160])

        return test, max, range_bool, optimality

    def get_meta_data(self):
        """This function gets the metadata from the camera and prints it to the console.
        It returns the width, height and stride of the image, this is used later to convert pixels to wavelengths in the spectrograph functions.
        The clock frequency is also returned, which is used to convert the timestamp ticks to seconds.
        """
        self.self.cam.MetadataEnable = True  # Turn on Metadata
        self.setup_image()
        # Turn IRIG on if implemented in camera
        irig_enabled = False
        try:
            self.self.cam.MetadataIRIG = True
            irig_enabled = True
        except AttributeError:
            LOGGER.info("MetaDateIRIG not implemented")

        # Acquire an image
        acq = self.self.cam.acquire()
        if self.self.cam.MetadataEnable:
            if self.self.cam.MetadataFrameInfo:
                LOGGER.info("\n-----------\nFrame Info\n-----------")
                LOGGER.info("Width:\t\t", acq.metadata.width)
                LOGGER.info("Height:\t\t", acq.metadata.height)
                LOGGER.info("Stride:\t\t", acq.metadata.stride)
                LOGGER.info("Pixel Encoding:\t", acq.metadata.pixelencoding)

            if self.self.cam.MetadataTimestamp:
                LOGGER.info("\n-----------\nTime Stamp\n-----------")
                LOGGER.info("TimeStamp (ticks):\t", acq.metadata.timestamp)
                LOGGER.info(
                    "frequency (Hz):\t        ", self.self.cam.TimestampClockFrequency
                )

            if irig_enabled:
                LOGGER.info("\n----------\nIRIG Data\n----------")
                LOGGER.info("Nanoseconds:\t", acq.metadata.irig_nanoseconds)
                LOGGER.info("Seconds:\t", acq.metadata.irig_seconds)
                LOGGER.info("Minutes:\t", acq.metadata.irig_minutes)
                LOGGER.info("Hours:\t\t", acq.metadata.irig_hours)
                LOGGER.info("Days:\t\t", acq.metadata.irig_days)
                LOGGER.info("Years:\t\t", acq.metadata.irig_years)
        LOGGER.info("\n-----------\nCooler Info\n-----------")
        LOGGER.info(
            "Temperature: {:.5f}C".format(self.self.cam.SensorTemperature), end="  "
        )
        LOGGER.info("Status: '{}'".format(self.self.cam.TemperatureStatus))

        return (
            acq.metadata.width,
            acq.metadata.height,
            acq.metadata.stride,
            self.self.cam.TimestampClockFrequency,
        )

    def setup_spectroscope(
        PixelWidth,
        centralWL=672.26,
        NumHorizPixels=2560,
        ND_filer_num=1,
        slit_width_um=10,
    ):
        """
        This functionsets up the spectrograph with standard parameters as default.

        """
        ## the return from GetWavelengthLimits looks weird to me :Wavelength Min: 0.0 Wavelength Max: 11127.045898
        # everything else looks fine and will get calibrated in the next block
        if ND_filer_num > 6:
            LOGGER.info("Filter number is too high")
            return
        elif ND_filer_num < 1:
            LOGGER.info("Filter number is too low")
            return
        elif slit_width_um > 100:
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
                    spc.SetSlitWidth(0, 1, 10)
                    LOGGER.info("slit set")
                if spc.IsFilterPresent(0) == (20202, 1):
                    spc.SetFilter(0, ND_filer_num)
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

    def adjust_ND(self, WL_arr):

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
                        _, max, _, optimality = self.image_and_check_dynamic_range(
                            WL_arr
                        )
                        optimality_array[i - 1] = optimality
                        max_array[i - 1] = max
                    # find the filter with the maximum optimality value
                    ND_filer_num = np.argmin(optimality_array)
                    # if max_array[ND_filer_num] is above 54000, set optimality[ND_filer_num] to 999
                    for i in range(7):
                        if max_array[ND_filer_num] > 54000:
                            optimality_array[ND_filer_num] = 999
                            ND_filer_num = np.argmin(optimality_array)
                    else:
                        ND_filer_num = np.argmin(optimality_array)
                    spc.SetFilter(0, ND_filer_num)

                    LOGGER.info(
                        "filter number set to ",
                        ND_filer_num,
                        " with optimality value of ",
                        optimality_array[ND_filer_num],
                        "and a max intensity of",
                        max_array[ND_filer_num],
                    )
            else:
                LOGGER.info("Cannot continue, could not initialise Spectrograph")
        shm = spc.Close()
        return max_array, optimality_array, ND_filer_num

    def warm_and_close(self, warmup: bool):
        """
        This function warms the camera back up and closes the connection to the camera. Warmup will only occur if the WarmupBool is set to True.
        """
        if warmup:
            self.cam.SensorCooling = False
            while (
                self.cam.TemperatureStatus != "Stabilised"
                and self.cam.SensorTemperature < 20
            ):
                time.sleep(5)
                LOGGER.info(
                    "Temperature: {:.5f}C".format(self.cam.SensorTemperature), end="  "
                )
                LOGGER.info("Status: '{}'".format(self.cam.TemperatureStatus))
                if self.cam.TemperatureStatus == "Fault":
                    err_str = "Camera faulted when cooling to target temperature"
                    raise RuntimeError(err_str)
            self.cam.close()
        else:
            LOGGER.info("Warmup is set to False, so the camera will not warm up. ")

    def generate_spectral_array(WL_arr, acqs, clockHz):
        """This function takes an aquisition object, the wavelength array and the camera clock speed and returns a dataframe of spectra
        args: WL_arr: wavelength array, acqs: aquisition object, clockHz: camera clock speed
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
        """Return current driver status."""
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
        """This function sets the camera up for a continous aquisition at the fastest rate using the complete AOI which is 10 ms exposure time"""
        try:
            # external start will start the camera upon 5V TTL signal. The camera will then aquire as fast as possible
            self.cam.TriggerMode = "External Start"  
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
            # initalise aquisition as a deque object so we can use the popleft() method
            self.acqs = deque()  

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

    def set_external_trigger(self) -> DriverResponse:
        """Apply signal and begin data acquisition."""
        try:
            # call function to activate External Trigger mode
            self.cam.TriggerMode = "External Start"  
            self.cam.AcquisitionStart()
            response = DriverResponse(
                response=DriverResponseType.success,
                message="trigger set",
                status=DriverStatus.busy,
            )
        except Exception:
            LOGGER.error("set_external_trigger failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed,
                status=DriverStatus.error,
            )
            self.cleanup()
        return response

    def get_data(self) -> DriverResponse:
        """Retrieve data from device buffer."""
        try:
            acq = self.cam.wait_buffer(self.timeout)
            self.acqs.append(acq)
            self.cam.queue(acq._np_data, self.cam.ImageSizeBytes) # requeue the buffer
            # TODO: decide on dict format (key by timestamp, or wavelength...)
            data_dict = {}
            # status.busy will cause executor polling loop to continue
            status = DriverStatus.busy
            # status.ok will cause executor polling loop to exit
            status = DriverStatus.ok
            response = DriverResponse(
                response=DriverResponseType.success,
                message="",
                data=data_dict,
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
        """General stop method to abort all active methods e.g. motion, I/O, compute."""
        try:
            # call function to stop ongoing acquisition
            response = DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception:
            LOGGER.error("stop failed", exc_info=True)
            response = DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        return response

    def cleanup(self):
        """Release state objects."""
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
        """Release connection to resource."""
        try:
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
        """Reinitialize driver, force-close old connection if necessary."""
        try:
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
        """Pass-through shutdown events for BaseAPI."""
        self.cleanup()
        self.disconnect()
