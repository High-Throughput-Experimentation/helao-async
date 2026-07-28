"""Long-duration Andor read-loop test script.

Drives the Andor SDK3 camera through a multi-hour acquisition loop that
writes one CSV spectrum per ``read_rate_s`` interval. Importing this
module runs the loop end-to-end (cool, set up spectroscope, periodic
acquire/save, warm down).
"""

from pyAndorSDK3 import AndorSDK3
from collections import deque
import numpy as np
import time as time
import pandas as pd
import matplotlib.pyplot as plt
from pyAndorSpectrograph.spectrograph import ATSpectrograph

sdk3 = AndorSDK3()
cam = sdk3.GetCamera(0)


# The following functions are listed roughly in the order they are called in the main function


def cool(cam):
    """Enable sensor cooling and block until the temperature stabilises.

    Args:
        cam: ``AndorSDK3`` camera object.

    Raises:
        RuntimeError: If the camera reports a temperature ``Fault``.
    """
    cam.SensorCooling = True
    while cam.TemperatureStatus != "Stabilised":
        time.sleep(5)
        print("Temperature: {:.5f}C".format(cam.SensorTemperature), end="  ")
        print("Status: '{}'".format(cam.TemperatureStatus))
        if cam.TemperatureStatus == "Fault":
            err_str = "Camera faulted when cooling to target temperature"
            raise RuntimeError(err_str)


def setup_shot(cam, exposure_time=0.0098):
    """Configure full-AOI software-triggered single-shot acquisition.

    Sets vertical binning over the full AOI, Mono32 encoding, rolling
    shutter with overlap mode, 280 MHz readout, fixed cycle mode and the
    requested exposure time.

    Args:
        cam: ``AndorSDK3`` camera object.
        exposure_time: Exposure time in seconds.
    """
    cam.TriggerMode = '"Software"'  # external start will start the camera upon 5V TTL signal. The camera will then aquire as fast as possible
    cam.AOIVBin = 2160  # full verrtical binning over the  AOI
    cam.SimplePreAmpGainControl = (
        "16-bit (low noise & high well capacity)"  # Single Pixel is 16 bit
    )
    cam.PixelEncoding = (
        "Mono32"  # After ADC conversion pixel values are added with size of 32 bit
    )
    cam.ElectronicShutteringMode = "Rolling"
    # Rolling shutter comes with health warnings but is the fastest.
    # take care with rolling shutter as technically the image is not taken at the same time but line by line
    # meaning the last row of one image is taken after the first row of the next image.
    # see section 5.11.5 and figure 21 of the Zyla manual for more information.
    cam.Overlap = True  # overlap mode also carries a health warning but is needed to collect quickly for long aquisitions.
    # see section 5.11.5 and figure 21 of the Zyla manual for more information.
    cam.PixelReadoutRate = "280 MHz"  # The fastest readout rate. This is 560 MHz in solis. I don't know why but these correspond to the same readout time
    cam.CycleMode = "Fixed"  # will go on forever until cam.AcquisitionStop() is called
    cam.ExposureTime = exposure_time  # Default to fastest exposure time permissible in this AOI is the readout time of 9.8 ms


def setup_image(cam, exposure_time=0.0098) -> float:
    """Configure the camera for a single, vertical-bin=1 image acquisition.

    Args:
        cam: ``AndorSDK3`` camera object.
        exposure_time: Exposure time in seconds.

    Returns:
        Detector pixel width used for spectrograph calibration.
    """
    cam.AOIVBin = 1  # readout on a single row
    cam.SimplePreAmpGainControl = "16-bit (low noise & high well capacity)"
    cam.AOILayout = "Image"
    cam.PixelEncoding = "Mono32"  # mono 32-bit encoding to get the full 32-bit range
    cam.CycleMode = "Fixed"  # fixed
    cam.ElectronicShutteringMode = "Rolling"  # rolling shutter
    cam.PixelReadoutRate = "280 MHz"  # 280 MHz readout rate
    cam.ExposureTime = exposure_time  # 50ms exposure time
    cam.MultitrackBinned = True
    cam.VerticallyCentreAOI = True
    # print('timestamp clock:')
    # print(sdkcamhandle.TimestampClock)
    # print('redout time:')
    # print(sdkcamhandle.ReadoutTime)
    # print('Pixel width:')
    # print(sdkcamhandle.PixelWidth)
    return cam.PixelWidth


def single_shot_vbinned(cam):
    """Run :func:`setup_shot` and return one vertically-binned acquisition."""
    _ = setup_shot(cam)
    return cam.acquire()


def image_and_check_dynamic_range(cam, WL=[], exposure_time=0.0098) -> tuple:
    """Acquire one image, plot it and evaluate dynamic-range optimality.

    Args:
        cam: ``AndorSDK3`` camera object.
        WL: Optional wavelength array used to label the plot x-axis.
        exposure_time: Exposure time in seconds.

    Returns:
        ``(acquisition, max_pixel, range_bool, optimality)``.
    """
    _ = setup_image(cam, exposure_time)
    print(cam.SerialNumber)
    test = cam.acquire()
    max = test.image.max()
    optimality = 1 + np.abs(63000 - max) / 63000
    range_bool = max < (2**16) and max > ((2**16) - 10000)
    if len(WL) == 0:
        plt.imshow(test.image, cmap="hot")
    else:
        # use imshow but set the x-axis to be the WL
        print("using the WL array")
        plt.figure(figsize=(8, 8))
        plt.imshow(test.image, cmap="hot", extent=[WL[0], WL[-1], 0, 2160])

    return test, max, range_bool, optimality


def GetMetaData(cam) -> tuple:
    """Enable metadata, acquire one image and print/return key frame fields.

    Args:
        cam: ``AndorSDK3`` camera object.

    Returns:
        ``(width, height, stride, timestamp_clock_frequency_hz)``.
    """
    cam.MetadataEnable = True  # Turn on Metadata
    setup_image(cam)
    # Turn IRIG on if implemented in camera
    irig_enabled = False
    try:
        cam.MetadataIRIG = True
        irig_enabled = True
    except AttributeError:
        print("MetaDateIRIG not implemented")

    # Acquire an image
    acq = cam.acquire()
    if cam.MetadataEnable:
        if cam.MetadataFrameInfo:
            print("\n-----------\nFrame Info\n-----------")
            print("Width:\t\t", acq.metadata.width)
            print("Height:\t\t", acq.metadata.height)
            print("Stride:\t\t", acq.metadata.stride)
            print("Pixel Encoding:\t", acq.metadata.pixelencoding)

        if cam.MetadataTimestamp:
            print("\n-----------\nTime Stamp\n-----------")
            print("TimeStamp (ticks):\t", acq.metadata.timestamp)
            print("frequency (Hz):\t        ", cam.TimestampClockFrequency)

        if irig_enabled:
            print("\n----------\nIRIG Data\n----------")
            print("Nanoseconds:\t", acq.metadata.irig_nanoseconds)
            print("Seconds:\t", acq.metadata.irig_seconds)
            print("Minutes:\t", acq.metadata.irig_minutes)
            print("Hours:\t\t", acq.metadata.irig_hours)
            print("Days:\t\t", acq.metadata.irig_days)
            print("Years:\t\t", acq.metadata.irig_years)
    print("\n-----------\nCooler Info\n-----------")
    print("Temperature: {:.5f}C".format(cam.SensorTemperature), end="  ")
    print("Status: '{}'".format(cam.TemperatureStatus))

    return (
        acq.metadata.width,
        acq.metadata.height,
        acq.metadata.stride,
        cam.TimestampClockFrequency,
    )


def SetupSpectroscope(
    PixelWidth, centralWL=672.26, NumHorizPixels=2560, ND_filer_num=1, slit_width_um=10
) -> np.ndarray:
    """Initialise the spectrograph and return its calibrated wavelength array.

    Args:
        PixelWidth: Detector pixel width.
        centralWL: Central wavelength in nm.
        NumHorizPixels: Number of horizontal pixels in the AOI.
        ND_filer_num: ND filter position in ``1..6``.
        slit_width_um: Slit width in micrometres (``10..100``).

    Returns:
        Wavelength array, or ``None`` if arguments are out of range.
    """
    ## the return from GetWavelengthLimits looks weird to me :Wavelength Min: 0.0 Wavelength Max: 11127.045898
    # everything else looks fine and will get calibrated in the next block
    if ND_filer_num > 6:
        print("Filter number is too high")
        return
    elif ND_filer_num < 1:
        print("Filter number is too low")
        return
    elif slit_width_um > 100:
        print("Slit width is too high")
        return
    elif slit_width_um < 10:
        print("Slit width is too low")
        return
    # Load libraries
    spc = ATSpectrograph()

    # Initialize libraries
    shm = spc.Initialize("")

    print(
        "Function Initialize returned {}".format(
            spc.GetFunctionReturnDescription(shm, 64)[1]
        )
    )

    print("Function Initialize returned {}".format(shm))

    if True:
        if ATSpectrograph.ATSPECTROGRAPH_SUCCESS == shm:

            # Configure Spectrograph
            shm = spc.SetGrating(0, 1)
            print(
                "Function SetGrating returned {}".format(
                    spc.GetFunctionReturnDescription(shm, 64)[1]
                )
            )

            shm, grat = spc.GetGrating(0)
            print("Function GetGrating returned: {} Grat".format(grat))

            shm = spc.SetWavelength(0, centralWL)
            print(
                "Function SetWavelength returned: {}".format(
                    spc.GetFunctionReturnDescription(shm, 64)[1]
                )
            )

            shm, wave = spc.GetWavelength(0)
            print(
                "Function GetWavelength returned: {} Wavelength: {}".format(
                    spc.GetFunctionReturnDescription(shm, 64)[1], wave
                )
            )

            shm, min, max = spc.GetWavelengthLimits(0, grat)
            print(
                "Function GetWavelengthLimits returned: {} Wavelength Min: {} Wavelength Max: {}".format(
                    spc.GetFunctionReturnDescription(shm, 64)[1], min, max
                )
            )

            # (shm, c0, c1, c2, c3) = spc.GetPixelCalibrationCoefficients(0) # these dont seem to be usefull for me
            # coeff = [c0,c1,c2,c3]
            if shm == 20202:
                print("return code is Success:")
            print(shm)
            print("::::::::::::::::::::::::")
            print(spc.IsFilterPresent(shm))
            if spc.IsSlitPresent(0, 1) == (20202, 1):
                spc.SetSlitWidth(0, 1, 10)
                print("slit set")
            if spc.IsFilterPresent(0) == (20202, 1):
                spc.SetFilter(0, ND_filer_num)
                print("filter set")

        else:
            print("Cannot continue, could not initialise Spectrograph")

        # important calibration stuff I keep out of the big block just to make it easier

        spc.SetNumberPixels(0, NumHorizPixels)
        print(PixelWidth)
        spc.SetPixelWidth(0, PixelWidth)
        print(spc.GetNumberPixels(0))
        print(spc.GetPixelWidth(0))
        WL_array = np.array(spc.GetCalibration(0, 2560)[1])
        shm = spc.Close()
        return WL_array


def adjust_ND(cam, WL_arr) -> tuple:
    """Sweep ND filter positions 1..6 and apply the best one.

    Args:
        cam: ``AndorSDK3`` camera object.
        WL_arr: Wavelength array used for plotting in the sweep.

    Returns:
        ``(max_array, optimality_array, ND_filer_num)``.
    """

    # Load libraries
    spc = ATSpectrograph()

    # Initialize libraries
    shm = spc.Initialize("")

    print(
        "Function Initialize returned {}".format(
            spc.GetFunctionReturnDescription(shm, 64)[1]
        )
    )

    print("Function Initialize returned {}".format(shm))

    if True:
        if ATSpectrograph.ATSPECTROGRAPH_SUCCESS == shm:

            # Configure Spectrograph
            shm = spc.SetGrating(0, 1)
            print(
                "Function SetGrating returned {}".format(
                    spc.GetFunctionReturnDescription(shm, 64)[1]
                )
            )

            shm, grat = spc.GetGrating(0)
            print("Function GetGrating returned: {} Grat".format(grat))

            shm = spc.SetWavelength(0, 672.26)
            print(
                "Function SetWavelength returned: {}".format(
                    spc.GetFunctionReturnDescription(shm, 64)[1]
                )
            )

            shm, wave = spc.GetWavelength(0)
            print(
                "Function GetWavelength returned: {} Wavelength: {}".format(
                    spc.GetFunctionReturnDescription(shm, 64)[1], wave
                )
            )

            shm, min, max = spc.GetWavelengthLimits(0, grat)
            print(
                "Function GetWavelengthLimits returned: {} Wavelength Min: {} Wavelength Max: {}".format(
                    spc.GetFunctionReturnDescription(shm, 64)[1], min, max
                )
            )

            shm, c0, c1, c2, c3 = spc.GetPixelCalibrationCoefficients(
                0
            )  # these dont seem to be usefull for me
            coeff = [c0, c1, c2, c3]
            if shm == 20202:
                print("return code is Success:")
            print(shm)
            print("::::::::::::::::::::::::")
            print(spc.IsFilterPresent(shm))
            if spc.IsSlitPresent(0, 1) == (20202, 1):
                spc.SetSlitWidth(0, 1, 10)
                print("slit set")
            if spc.IsFilterPresent(0) == (20202, 1):
                spc.SetFilter(0, 1)
                print("filter set")
                # create a np array of zeros of length 6
                optimality_array = np.zeros(6)
                max_array = np.zeros(6)
                # create a for loop iterating from 1 to 6, setting each filter and getting the optimality value
                for i in range(1, 7):
                    spc.SetFilter(0, i)
                    _, max, _, optimality = image_and_check_dynamic_range(cam, WL_arr)
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

                print(
                    "filter number set to ",
                    ND_filer_num,
                    " with optimality value of ",
                    optimality_array[ND_filer_num],
                    "and a max intensity of",
                    max_array[ND_filer_num],
                )
        else:
            print("Cannot continue, could not initialise Spectrograph")
    shm = spc.Close()
    return max_array, optimality_array, ND_filer_num


def setup_SEC_aquisition(cam, exp_time=0.0098, framerate=98):
    """Configure full-AOI continuous acquisition with external 5 V TTL start.

    Args:
        cam: ``AndorSDK3`` camera object.
        exp_time: Exposure time in seconds.
        framerate: Target framerate in Hz.
    """
    cam.TriggerMode = "External Start"  # external start will start the camera upon 5V TTL signal. The camera will then aquire as fast as possible
    cam.AOIVBin = 2160  # full verrtical binning over the  AOI
    cam.SimplePreAmpGainControl = (
        "16-bit (low noise & high well capacity)"  # Single Pixel is 16 bit
    )
    cam.PixelEncoding = (
        "Mono32"  # After ADC conversion pixel values are added with size of 32 bit
    )
    cam.ElectronicShutteringMode = "Rolling"
    # Rolling shutter comes with health warnings but is the fastest.
    # take care with rolling shutter as technically the image is not taken at the same time but line by line
    # meaning the last row of one image is taken after the first row of the next image.
    # see section 5.11.5 and figure 21 of the Zyla manual for more information.
    cam.Overlap = True  # overlap mode also carries a health warning but is needed to collect quickly for long aquisitions.
    # see section 5.11.5 and figure 21 of the Zyla manual for more information.
    cam.PixelReadoutRate = "280 MHz"  # The fastest readout rate. This is 560 MHz in solis. I don't know why but these correspond to the same readout time
    cam.CycleMode = (
        "Continuous"  # will go on forever until cam.AcquisitionStop() is called
    )
    cam.ExposureTime = exp_time  # Default to fastest exposure time permissible in this AOI is the readout time of 9.8 ms
    cam.FrameRate = framerate  # The fastest framerate permissible in this AOI is the readout time default to 98 Hz


def test_aquisition(
    cam, frame_count, timeout, buffer_count=10
) -> tuple:  # curently working with external trigger and a fixed nymber of aquisitions
    """Run a fixed-count acquisition while recording per-step timings.

    Args:
        cam: ``AndorSDK3`` camera object.
        frame_count: Number of frames to acquire.
        timeout: Buffer-fill timeout in milliseconds.
        buffer_count: Number of buffers to pre-queue.

    Returns:
        ``(acqs, times_df, measurement_time)`` or ``(None, None, None)`` if
        the camera is in fixed cycle mode.
    """

    if (
        cam.CycleMode == "Fixed"
    ):  # failsafe in case called with wrong cycle mode- that way the function will end
        "The camera is in fixed mode, please change to continuous mode"
        return None, None, None

    imgsize = (
        cam.ImageSizeBytes
    )  # Returns the buffer size in bytes required to store the data for one frame. This
    # will be affected by the Area of Interest size, binning and whether metadata is  appended to the data stream

    for _ in range(0, buffer_count):  # this makes buffer_count buffers in the camera
        buf = np.empty(
            (imgsize,), dtype="B"
        )  # each buffer is a numpy array of size imgsize containing unsigned bytes
        cam.queue(
            buf, imgsize
        )  # this creates a new buffer in the camera for the next image

    software_trigger = (
        cam.TriggerMode == "Software"
    )  # checking if the trigger mode is software - should return True
    print(software_trigger)
    frame = None  # initialise frame to None
    acqs = (
        deque()
    )  # initalise aquisition as a deque object so we can use the popleft() method

    # create a data frame with frame_count rows and collumns filled with NaN, the first collumn name is  triggering time (s), the second collumn is the time of buffering (s), the third collumn is the time of aquiring (s)
    times = pd.DataFrame(np.full((frame_count, 3), np.nan))
    times.columns = ["triggering time (s)", "wait buffer filling time (s)", " time (s)"]
    start = time.time()
    i = 0

    try:
        cam.AcquisitionStart()
        frame = 0
        # get start time

        while True:

            if software_trigger:
                start_time = time.time()
                cam.SoftwareTrigger()
                times.iloc[i, 0] = time.time() - start_time

            start_time = time.time()
            acq = cam.wait_buffer(
                timeout
            )  # this waits untill the buffer is filled by an image and returns it as acq
            times.iloc[i, 1] = time.time() - start_time

            # if frame >= buffer_count: # after we have accumulated more than buffer_count frames we need to start emptying the buffer

            #   acqs.popleft() # we remove the leftmost element of the deque object, as we already retreived it
            acqs.append(
                acq
            )  # we add the new aquisition to the right of the deque object
            start_time = time.time()
            cam.queue(
                acq._np_data, imgsize
            )  # this creates a new buffer in the camera for the next image
            times.iloc[i, 2] = time.time() - start_time

            frame += 1
            i = i + 1
            # print("{}% complete series".format(percent), end="\r")
            if frame == frame_count:
                print()
                break

    except Exception as e:
        if frame is not None:
            print()
            print("Error on frame " + str(frame))
        cam.AcquisitionStop()
        cam.flush()
        raise e
    cam.AcquisitionStop()
    cam.flush()
    measurment_time = time.time() - start
    print("measurment time: ", measurment_time)
    print("each measurment took: ", measurment_time / frame_count, "s")

    return acqs, times, measurment_time


def SEC_aquisition(cam, frame_count, timeout, buffer_count=10) -> tuple:
    """Run a fixed-count acquisition started by the external trigger.

    Args:
        cam: ``AndorSDK3`` camera object.
        frame_count: Number of frames to acquire.
        timeout: Buffer-fill timeout in milliseconds.
        buffer_count: Number of buffers to pre-queue.

    Returns:
        ``(acqs,)`` deque of acquisitions, or ``(None, None, None)`` if the
        camera is in fixed cycle mode.
    """

    if (
        cam.CycleMode == "Fixed"
    ):  # failsafe in case called with wrong cycle mode- that way the function will end
        "The camera is in fixed mode, please change to continuous mode"
        return None, None, None

    imgsize = (
        cam.ImageSizeBytes
    )  # Returns the buffer size in bytes required to store the data for one frame. This
    # will be affected by the Area of Interest size, binning and whether metadata is  appended to the data stream

    for _ in range(0, buffer_count):  # this makes buffer_count buffers in the camera
        buf = np.empty(
            (imgsize,), dtype="B"
        )  # each buffer is a numpy array of size imgsize containing unsigned bytes
        cam.queue(
            buf, imgsize
        )  # this creates a new buffer in the camera for the next image

    software_trigger = (
        cam.TriggerMode == "Software"
    )  # checking if the trigger mode is software - should return True
    print(software_trigger)
    frame = None  # initialise frame to None
    acqs = (
        deque()
    )  # initalise aquisition as a deque object so we can use the popleft() method

    try:
        cam.AcquisitionStart()
        frame = 0
        # get start time

        while True:

            if software_trigger:
                cam.SoftwareTrigger()

            acq = cam.wait_buffer(
                timeout
            )  # this waits untill the buffer is filled by an image and returns it as acq

            # if frame >= buffer_count: # after we have accumulated more than buffer_count frames we need to start emptying the buffer

            #   acqs.popleft() # we remove the leftmost element of the deque object, as we already retreived it
            acqs.append(
                acq
            )  # we add the new aquisition to the right of the deque object
            cam.queue(
                acq._np_data, imgsize
            )  # this creates a new buffer in the camera for the next image

            frame += 1
            # print("{}% complete series".format(percent), end="\r")
            if frame == frame_count:
                print()
                break

    except Exception as e:
        if frame is not None:
            print()
            print("Error on frame " + str(frame))
        cam.AcquisitionStop()
        cam.flush()
        raise e
    cam.AcquisitionStop()
    cam.flush()

    return (acqs,)


def WarmAndClose(cam, WarmupBool):
    """Optionally warm the camera back up, then close the SDK handle.

    Args:
        cam: ``AndorSDK3`` camera object.
        WarmupBool: Whether to perform the warm-up before closing.

    Raises:
        RuntimeError: If the camera reports a temperature fault.
    """
    if WarmupBool == True:
        cam.SensorCooling = False
        while cam.TemperatureStatus != "Stabilised" and cam.SensorTemperature < 20:
            time.sleep(5)
            print("Temperature: {:.5f}C".format(cam.SensorTemperature), end="  ")
            print("Status: '{}'".format(cam.TemperatureStatus))
            if cam.TemperatureStatus == "Fault":
                err_str = "Camera faulted when cooling to target temperature"
                raise RuntimeError(err_str)
        cam.close()
    else:
        print("Warmup is set to False, so the camera will not warm up. ")


def process_timings(timez, measurment_time):
    """Plot per-step and aggregated timings produced by :func:`test_aquisition`.

    Args:
        timez: DataFrame returned by :func:`test_aquisition`.
        measurment_time: Total measurement time in seconds.
    """
    # Create a figure and a 2-frame subplot
    fig, axs = plt.subplots(2)
    # plot the first collumn of timez as a a scatter plot
    axs[0].scatter(range(0, 100), timez.iloc[:, 0], c="g")
    axs[0].scatter(range(0, 100), timez.iloc[:, 1], c="r")
    axs[0].scatter(range(0, 100), timez.iloc[:, 2], c="b")
    # make ledgend entries
    axs[0].legend(
        ["triggering time", "wait buffer filling time", "aquiring time"],
        loc="upper left",
        bbox_to_anchor=(1, 1),
        ncol=1,
        frameon=False,
    )
    # set the y range to be between 0 and 0.001
    axs[0].set_ylim(0, 0.04)
    # label the x axis as the frame number
    axs[0].set_xlabel("frame number")
    # label the y axis as the time in seconds
    axs[0].set_ylabel("time (s)")
    # sum each collumn of timez and include the total measurment time of 6.7 s in a new data frame
    sum_times = pd.DataFrame(timez.sum())
    # append a 4th row of sum_times with the name total measurment time and value 6.7 s
    sum_times.loc["total measurment time"] = measurment_time
    # being by making a deep copy of sum_times
    times_breakdown = sum_times.copy(deep=True)

    # sum the first three rows of sum_times and subtract them from the total measurment time set this value equal to the last row of times_breakdown
    times_breakdown.iloc[3] = sum_times.iloc[3] - sum_times.iloc[0:3].sum()

    # given the third row is zero, we can remove it
    times_breakdown = times_breakdown.drop(times_breakdown.index[2])

    # create a histogramme where there is only one bar in a stacked manner
    # Create a bar plot in the second frame
    times_breakdown.T.plot.barh(stacked=True, legend=True, ax=axs[1])
    axs[1].set_xlabel("total time (s)")
    # remove the frame around the legend
    plt.legend(frameon=False)
    # make the ledgend horizontal
    plt.legend(loc="upper left", bbox_to_anchor=(1, 1), ncol=1, frameon=False)
    # set the x axis label to time taken up in seconds
    plt.xlabel("time taken up  (seconds)")
    plt.tight_layout()


def generate_spectral_array(WL_arr, acqs, clockHz) -> pd.DataFrame:
    """Stack acquisitions into a wavelength-vs-time spectra DataFrame.

    Args:
        WL_arr: Wavelength array (DataFrame index).
        acqs: Container of acquisition objects.
        clockHz: Camera timestamp clock frequency in Hz.

    Returns:
        DataFrame indexed by wavelength, columns by tick time.
    """

    acqs = list(acqs[0])

    print(acqs[0].image[0])
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


cool(cam)
PixelWidth = setup_image(cam)
WL_arr = SetupSpectroscope(PixelWidth)
horiz_pixels, vert_pixels, Stride, clockHz = GetMetaData(cam)

# test, max, range_bool, optimality=image_and_check_dynamic_range(cam, WL_arr)
# _, _, _=adjust_ND(cam, WL_arr)

# setup_SEC_aquisition(cam)
no_hours = 1.5
total_time_s = 3600 * no_hours
read_rate_s = 120
start_time = time.time()
setup_shot(cam)
while time.time() - start_time < total_time_s:
    aq = cam.acquire()
    time_elapsed = time.time() - start_time
    # round time elaped to nearest whole number
    time_elapsed = round(time_elapsed)
    spec = generate_spectral_array(WL_arr, [aq], clockHz)
    # write the spectrum to a csv file with a title of the time elapsed
    spec.to_csv(str(time_elapsed) + ".csv")
    # wait for the read rate
    time.sleep(read_rate_s)

# acqs, timez, measurment_time = test_aquisition(cam, 100, 5000)
# acqs2=SEC_aquisition(cam, 1000, 5000)
# spectra=generate_spectral_array(WL_arr, acqs2, clockHz)


# process_timings(timez, measurment_time)
WarmAndClose(cam, False)
