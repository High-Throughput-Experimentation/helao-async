
from pyAndorSDK3 import AndorSDK3
from collections import deque
import numpy as np
import time as time
import pandas as pd
import matplotlib.pyplot as plt
from pyAndorSpectrograph.spectrograph import ATSpectrograph

sdk3 = AndorSDK3()
cam = sdk3.GetCamera(0)



#The following functions are listed roughly in the order they are called in the main function


def cool(cam): 
    """This function cools the camera to 20 degrees C below ambient temperature. The camera will not warm untill told unless cam.close() is called.
    The function will wait until the camera is at the target temperature before returning.
        args: cam: AndorSDK3 object 
    """
    cam.SensorCooling = True
    while(cam.TemperatureStatus != "Stabilised"):
        time.sleep(5)
        print("Temperature: {:.5f}C".format(cam.SensorTemperature), end="  ")
        print("Status: '{}'".format(cam.TemperatureStatus))
        if cam.TemperatureStatus == "Fault":
            err_str = "Camera faulted when cooling to target temperature"
            raise RuntimeError(err_str)
        

def setup_shot(cam, exposure_time=0.0098):  
    """This function sets the camera up for a continous aquisition at the fastest rate using the complete AOI which is 10 ms exposure time
    args: cam: AndorSDK3 object 
    """
    cam.TriggerMode='"Software"' #external start will start the camera upon 5V TTL signal. The camera will then aquire as fast as possible
    cam.AOIVBin = 2160 # full verrtical binning over the  AOI
    cam.SimplePreAmpGainControl='16-bit (low noise & high well capacity)'# Single Pixel is 16 bit
    cam.PixelEncoding='Mono32' # After ADC conversion pixel values are added with size of 32 bit
    cam.ElectronicShutteringMode='Rolling'
     # Rolling shutter comes with health warnings but is the fastest. 
    # take care with rolling shutter as technically the image is not taken at the same time but line by line
    # meaning the last row of one image is taken after the first row of the next image.
    # see section 5.11.5 and figure 21 of the Zyla manual for more information. 
    cam.Overlap=True # overlap mode also carries a health warning but is needed to collect quickly for long aquisitions. 
    # see section 5.11.5 and figure 21 of the Zyla manual for more information.
    cam.PixelReadoutRate='280 MHz' # The fastest readout rate. This is 560 MHz in solis. I don't know why but these correspond to the same readout time
    cam.CycleMode='Fixed' # will go on forever until cam.AcquisitionStop() is called
    cam.ExposureTime = exposure_time # Default to fastest exposure time permissible in this AOI is the readout time of 9.8 ms





def setup_image(cam, exposure_time=0.0098):
    '''This function sets up the camera to take a single image with the desired framerate and exposure time. It returns the pixel width of the camera
    Which is used to convert pixels to wavelengths in the spectrograph fucntions. Start with framerate is 100 Hz and exposure time is 9.8 ms.
    args: cam: camera object, framerate: desired framerate , exposure_time: desired exposure time defaults are max values for the camera 
    '''
    cam.AOIVBin = 1 # readout on a single row
    cam.SimplePreAmpGainControl='16-bit (low noise & high well capacity)'
    cam.AOILayout='Image' 
    cam.PixelEncoding='Mono32' #mono 32-bit encoding to get the full 32-bit range
    cam.CycleMode='Fixed' #fixed
    cam.ElectronicShutteringMode='Rolling' #rolling shutter
    cam.PixelReadoutRate='280 MHz'#280 MHz readout rate  
    cam.ExposureTime = exposure_time # 50ms exposure time
    cam.MultitrackBinned = True
    cam.VerticallyCentreAOI = True
    #print('timestamp clock:')
    #print(sdkcamhandle.TimestampClock)
    #print('redout time:')
    #print(sdkcamhandle.ReadoutTime)
    #print('Pixel width:')
    #print(sdkcamhandle.PixelWidth)
    return cam.PixelWidth

def single_shot_vbinned(cam):
    _ = setup_shot(cam)
    return cam.acquire()




def image_and_check_dynamic_range(cam, WL=[], exposure_time=0.0098):
        """ This function collects a single image and checks that the maximum value is in the optimum dynamic range for the measurment.
          It returns the image, the maximum pixel value and a boolean that is true if the maximum value is in the optimum dynamic range
          defined by the range 65536-55536.
          An optimality value is calculated as 1- the absolute difference between the maximum value and an approximate optimum max value of 63000, normalised by 63000.
          An optimality close to 1 indicates that the maximum value is close to the optimum value.
          An optimality that is negative indicates that the source is too bright.  To search for the optimum value, the range bool and the optimality value can be used together.
          args: cam: AndorSDK3 object
          """
        _=setup_image(cam,exposure_time)
        print(cam.SerialNumber)
        test= cam.acquire()
        max=test.image.max()
        optimality=1+np.abs(63000-max)/63000
        range_bool=max<(2**16) and max>((2**16)-10000)
        if len(WL)==0:
          plt.imshow(test.image,cmap="hot")
        else:
          # use imshow but set the x-axis to be the WL
          print('using the WL array')
          plt.figure(figsize=(8, 8))
          plt.imshow(test.image,cmap="hot",extent=[WL[0],WL[-1],0,2160])
        
        return test, max, range_bool, optimality





def GetMetaData(cam):
        """This function gets the metadata from the camera and prints it to the console.
          It returns the width, height and stride of the image, this is used later to convert pixels to wavelengths in the spectrograph functions.
          The clock frequency is also returned, which is used to convert the timestamp ticks to seconds.
          """
        cam.MetadataEnable = True# Turn on Metadata
        setup_image(cam)
    # Turn IRIG on if implemented in camera
        irig_enabled = False
        try:
            cam.MetadataIRIG = True
            irig_enabled = True
        except AttributeError:
            print('MetaDateIRIG not implemented')

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

        return acq.metadata.width, acq.metadata.height, acq.metadata.stride, cam.TimestampClockFrequency




def SetupSpectroscope(PixelWidth, centralWL=672.26, NumHorizPixels=2560, ND_filer_num=1, slit_width_um=10):
    """
    This functionsets up the spectrograph with standard parameters as default.
    
    """
## the return from GetWavelengthLimits looks weird to me :Wavelength Min: 0.0 Wavelength Max: 11127.045898
# everything else looks fine and will get calibrated in the next block
    if ND_filer_num>6:
        print('Filter number is too high')
        return
    elif ND_filer_num<1:
        print('Filter number is too low')
        return
    elif slit_width_um>100:
        print('Slit width is too high')
        return
    elif slit_width_um<10:
        print('Slit width is too low')
        return
    #Load libraries
    spc = ATSpectrograph()

    #Initialize libraries
    shm = spc.Initialize("")

    print("Function Initialize returned {}".format(
        spc.GetFunctionReturnDescription(shm, 64)[1]))

    print("Function Initialize returned {}".format(shm))

    if True:    
        if ATSpectrograph.ATSPECTROGRAPH_SUCCESS==shm:
        
        #Configure Spectrograph
            shm = spc.SetGrating(0, 1)
            print("Function SetGrating returned {}".format(
                spc.GetFunctionReturnDescription(shm, 64)[1]))

            (shm, grat) = spc.GetGrating(0)
            print("Function GetGrating returned: {} Grat".format(grat))

            shm = spc.SetWavelength(0, centralWL)
            print("Function SetWavelength returned: {}".format(
                spc.GetFunctionReturnDescription(shm, 64)[1]))

            (shm, wave) = spc.GetWavelength(0)
            print("Function GetWavelength returned: {} Wavelength: {}".format(
                spc.GetFunctionReturnDescription(shm, 64)[1], wave))

            (shm, min, max) = spc.GetWavelengthLimits(0, grat)
            print("Function GetWavelengthLimits returned: {} Wavelength Min: {} Wavelength Max: {}".format(
                spc.GetFunctionReturnDescription(shm, 64)[1], min, max))
            
            #(shm, c0, c1, c2, c3) = spc.GetPixelCalibrationCoefficients(0) # these dont seem to be usefull for me
            #coeff = [c0,c1,c2,c3]
            if shm==20202:
                print('return code is Success:')
            print(shm)
            print('::::::::::::::::::::::::')
            print(spc.IsFilterPresent(shm))
            if spc.IsSlitPresent(0,1)==(20202, 1):
                spc.SetSlitWidth(0,1,10)
                print('slit set')
            if spc.IsFilterPresent(0)==(20202, 1):
                spc.SetFilter(0,ND_filer_num)
                print('filter set')
        

                
        else:
            print("Cannot continue, could not initialise Spectrograph")
            ()

        # important calibration stuff I keep out of the big block just to make it easier

        spc.SetNumberPixels(0, NumHorizPixels)
        print(PixelWidth)
        spc.SetPixelWidth(0, PixelWidth)
        print(spc.GetNumberPixels(0))
        print(spc.GetPixelWidth(0))
        WL_array=np.array(spc.GetCalibration(0, 2560)[1])
        shm = spc.Close()
        return WL_array



def adjust_ND(cam,WL_arr):

    #Load libraries
    spc = ATSpectrograph()

    #Initialize libraries
    shm = spc.Initialize("")

    print("Function Initialize returned {}".format(
        spc.GetFunctionReturnDescription(shm, 64)[1]))

    print("Function Initialize returned {}".format(shm))

    if True:    
        if ATSpectrograph.ATSPECTROGRAPH_SUCCESS==shm:
        
        #Configure Spectrograph
            shm = spc.SetGrating(0, 1)
            print("Function SetGrating returned {}".format(
                spc.GetFunctionReturnDescription(shm, 64)[1]))

            (shm, grat) = spc.GetGrating(0)
            print("Function GetGrating returned: {} Grat".format(grat))

            shm = spc.SetWavelength(0, 672.26)
            print("Function SetWavelength returned: {}".format(
                spc.GetFunctionReturnDescription(shm, 64)[1]))

            (shm, wave) = spc.GetWavelength(0)
            print("Function GetWavelength returned: {} Wavelength: {}".format(
                spc.GetFunctionReturnDescription(shm, 64)[1], wave))

            (shm, min, max) = spc.GetWavelengthLimits(0, grat)
            print("Function GetWavelengthLimits returned: {} Wavelength Min: {} Wavelength Max: {}".format(
                spc.GetFunctionReturnDescription(shm, 64)[1], min, max))
            
            (shm, c0, c1, c2, c3) = spc.GetPixelCalibrationCoefficients(0) # these dont seem to be usefull for me
            coeff = [c0,c1,c2,c3]
            if shm==20202:
                print('return code is Success:')
            print(shm)
            print('::::::::::::::::::::::::')
            print(spc.IsFilterPresent(shm))
            if spc.IsSlitPresent(0,1)==(20202, 1):
                spc.SetSlitWidth(0,1,10)
                print('slit set')
            if spc.IsFilterPresent(0)==(20202, 1):
                spc.SetFilter(0,1)
                print('filter set')
                # create a np array of zeros of length 6
                optimality_array=np.zeros(6)
                max_array=np.zeros(6)
                #create a for loop iterating from 1 to 6, setting each filter and getting the optimality value
                for i in range(1,7):
                    spc.SetFilter(0,i)
                    _, max, _, optimality=image_and_check_dynamic_range(cam,WL_arr)
                    optimality_array[i-1]=optimality
                    max_array[i-1]=max
                #find the filter with the maximum optimality value
                ND_filer_num=np.argmin(optimality_array)
                # if max_array[ND_filer_num] is above 54000, set optimality[ND_filer_num] to 999
                for i in range(7):
                    if max_array[ND_filer_num]>54000:
                        optimality_array[ND_filer_num]=999
                        ND_filer_num=np.argmin(optimality_array)
                else:
                    ND_filer_num=np.argmin(optimality_array)
                spc.SetFilter(0,ND_filer_num)

             
                print('filter number set to ', ND_filer_num, ' with optimality value of ', optimality_array[ND_filer_num],'and a max intensity of', max_array[ND_filer_num])
        else:
            print("Cannot continue, could not initialise Spectrograph")
    shm = spc.Close()
    return max_array, optimality_array, ND_filer_num


  




def setup_SEC_aquisition(cam, exp_time=0.0098, framerate=98):
    """This function sets the camera up for a continous aquisition at the fastest rate using the complete AOI which is 10 ms exposure time
    args: cam: AndorSDK3 object 
    """
    cam.TriggerMode='External Start' #external start will start the camera upon 5V TTL signal. The camera will then aquire as fast as possible
    cam.AOIVBin = 2160 # full verrtical binning over the  AOI
    cam.SimplePreAmpGainControl='16-bit (low noise & high well capacity)'# Single Pixel is 16 bit
    cam.PixelEncoding='Mono32' # After ADC conversion pixel values are added with size of 32 bit
    cam.ElectronicShutteringMode='Rolling'
     # Rolling shutter comes with health warnings but is the fastest. 
    # take care with rolling shutter as technically the image is not taken at the same time but line by line
    # meaning the last row of one image is taken after the first row of the next image.
    # see section 5.11.5 and figure 21 of the Zyla manual for more information. 
    cam.Overlap=True # overlap mode also carries a health warning but is needed to collect quickly for long aquisitions. 
    # see section 5.11.5 and figure 21 of the Zyla manual for more information.
    cam.PixelReadoutRate='280 MHz' # The fastest readout rate. This is 560 MHz in solis. I don't know why but these correspond to the same readout time
    cam.CycleMode='Continuous' # will go on forever until cam.AcquisitionStop() is called
    cam.ExposureTime = exp_time # Default to fastest exposure time permissible in this AOI is the readout time of 9.8 ms
    cam.FrameRate = framerate # The fastest framerate permissible in this AOI is the readout time default to 98 Hz


def test_aquisition(cam, frame_count, timeout, buffer_count=10): # curently working with external trigger and a fixed nymber of aquisitions
    """ This function runs a fixed number of aquisitions so the timing of the aquisition can be tested. 
    It returns a breakdown of times taken for each step of the aquisition.
    args: cam: AndorSDK3 object,
    frame_count: number of frames to aquire,
    timeout: time to wait in for a buffer to be filled in ms for the timeout to be activated,
     buffer_count: number of buffers to create, 10 is default
    """
    
    if cam.CycleMode == "Fixed":  # failsafe in case called with wrong cycle mode- that way the function will end 
        'The camera is in fixed mode, please change to continuous mode'
        return None, None, None

    imgsize = cam.ImageSizeBytes #Returns the buffer size in bytes required to store the data for one frame. This 
#will be affected by the Area of Interest size, binning and whether metadata is  appended to the data stream

    for _ in range(0, buffer_count):  # this makes buffer_count buffers in the camera
        buf = np.empty((imgsize,), dtype='B')   # each buffer is a numpy array of size imgsize containing unsigned bytes
        cam.queue(buf, imgsize) # this creates a new buffer in the camera for the next image

    software_trigger = cam.TriggerMode == "Software" # checking if the trigger mode is software - should return True
    print(software_trigger)
    frame = None # initialise frame to None
    acqs = deque() # initalise aquisition as a deque object so we can use the popleft() method

    # create a data frame with frame_count rows and collumns filled with NaN, the first collumn name is  triggering time (s), the second collumn is the time of buffering (s), the third collumn is the time of aquiring (s)
    times = pd.DataFrame(np.full((frame_count, 3), np.nan))
    times.columns = ['triggering time (s)', 'wait buffer filling time (s)', ' time (s)']
    start = time.time()
    i=0
    

    try:
        cam.AcquisitionStart()
        frame = 0
        # get start time
        
        while(True):
    
            if software_trigger:
                start_time = time.time()
                cam.SoftwareTrigger()
                times.iloc[i, 0] = time.time() - start_time

            start_time = time.time()
            acq = cam.wait_buffer(timeout) # this waits untill the buffer is filled by an image and returns it as acq
            times.iloc[i, 1] = time.time() - start_time
            
            #if frame >= buffer_count: # after we have accumulated more than buffer_count frames we need to start emptying the buffer

             #   acqs.popleft() # we remove the leftmost element of the deque object, as we already retreived it
            acqs.append(acq) # we add the new aquisition to the right of the deque object
            start_time = time.time()
            cam.queue(acq._np_data, imgsize) # this creates a new buffer in the camera for the next image
            times.iloc[i, 2] = time.time() - start_time

            frame += 1
            i=i+1
            #print("{}% complete series".format(percent), end="\r")
            if frame == frame_count:
                print()
                break
        
    except Exception as e:
        if frame is not None:
            print()
            print("Error on frame "+str(frame))
        cam.AcquisitionStop()
        cam.flush()
        raise e
    cam.AcquisitionStop()
    cam.flush()
    measurment_time = time.time()-start
    print("measurment time: ", measurment_time)
    print("each measurment took: ", measurment_time/frame_count, "s")

    return acqs, times, measurment_time



def SEC_aquisition(cam, frame_count, timeout, buffer_count=10):
    """ This function runs a fixed number of aquisitions upon recipt of external trigger. 
    It returns a breakdown of times taken for each step of the aquisition.
    args: cam: AndorSDK3 object,
    frame_count: number of frames to aquire,
    timeout: time to wait in for a buffer to be filled in ms for the timeout to be activated,
     buffer_count: number of buffers to create, 10 is default
    """
    
    if cam.CycleMode == "Fixed":  # failsafe in case called with wrong cycle mode- that way the function will end 
        'The camera is in fixed mode, please change to continuous mode'
        return None, None, None

    imgsize = cam.ImageSizeBytes #Returns the buffer size in bytes required to store the data for one frame. This 
#will be affected by the Area of Interest size, binning and whether metadata is  appended to the data stream

    for _ in range(0, buffer_count):  # this makes buffer_count buffers in the camera
        buf = np.empty((imgsize,), dtype='B')   # each buffer is a numpy array of size imgsize containing unsigned bytes
        cam.queue(buf, imgsize) # this creates a new buffer in the camera for the next image

    software_trigger = cam.TriggerMode == "Software" # checking if the trigger mode is software - should return True
    print(software_trigger)
    frame = None # initialise frame to None
    acqs = deque() # initalise aquisition as a deque object so we can use the popleft() method


    try:
        cam.AcquisitionStart()
        frame = 0
        # get start time
        
        while(True):
    
            if software_trigger:
                cam.SoftwareTrigger()

            acq = cam.wait_buffer(timeout) # this waits untill the buffer is filled by an image and returns it as acq
            
            #if frame >= buffer_count: # after we have accumulated more than buffer_count frames we need to start emptying the buffer

             #   acqs.popleft() # we remove the leftmost element of the deque object, as we already retreived it
            acqs.append(acq) # we add the new aquisition to the right of the deque object
            cam.queue(acq._np_data, imgsize) # this creates a new buffer in the camera for the next image

            frame += 1
            #print("{}% complete series".format(percent), end="\r")
            if frame == frame_count:
                print()
                break
        
    except Exception as e:
        if frame is not None:
            print()
            print("Error on frame "+str(frame))
        cam.AcquisitionStop()
        cam.flush()
        raise e
    cam.AcquisitionStop()
    cam.flush()

    return acqs, 



def WarmAndClose(cam, WarmupBool):
    """
    This function warms the camera back up and closes the connection to the camera. Warmup will only occur if the WarmupBool is set to True.
    """
    if WarmupBool==True: 
        cam.SensorCooling = False
        while(cam.TemperatureStatus != "Stabilised" and cam.SensorTemperature <20):
            time.sleep(5)
            print("Temperature: {:.5f}C".format(cam.SensorTemperature), end="  ")
            print("Status: '{}'".format(cam.TemperatureStatus))
            if cam.TemperatureStatus == "Fault":
                err_str = "Camera faulted when cooling to target temperature"
                raise RuntimeError(err_str)
        cam.close()
    else:
        print('Warmup is set to False, so the camera will not warm up. ')




def process_timings(timez, measurment_time):
    """This function takes the times dataframe of the test_aquisition function and plots up the time taken for each step of the aquisition
    args: 
    timez: dataframe of the test_aquisition function
    measurment_time: total time taken for the aquisition

    
    """
    # Create a figure and a 2-frame subplot
    fig, axs = plt.subplots(2)
     # plot the first collumn of timez as a a scatter plot
    axs[0].scatter(range(0,100), timez.iloc[:, 0], c = 'g')
    axs[0].scatter(range(0,100), timez.iloc[:, 1], c='r')
    axs[0].scatter(range(0,100), timez.iloc[:, 2], c='b')
    # make ledgend entries
    axs[0].legend(['triggering time', 'wait buffer filling time', 'aquiring time'], loc='upper left', bbox_to_anchor=(1, 1), ncol=1, frameon=False)
    # set the y range to be between 0 and 0.001
    axs[0].set_ylim(0,0.04)
    # label the x axis as the frame number
    axs[0].set_xlabel('frame number')
    #label the y axis as the time in seconds
    axs[0].set_ylabel('time (s)')
        # sum each collumn of timez and include the total measurment time of 6.7 s in a new data frame
    sum_times = pd.DataFrame(timez.sum())
    # append a 4th row of sum_times with the name total measurment time and value 6.7 s
    sum_times.loc['total measurment time'] = measurment_time
    # being by making a deep copy of sum_times
    times_breakdown = sum_times.copy(deep=True)

    # sum the first three rows of sum_times and subtract them from the total measurment time set this value equal to the last row of times_breakdown
    times_breakdown.iloc[3] = sum_times.iloc[3] - sum_times.iloc[0:3].sum()

    # given the third row is zero, we can remove it
    times_breakdown = times_breakdown.drop(times_breakdown.index[2])

    # create a histogramme where there is only one bar in a stacked manner
# Create a bar plot in the second frame
    times_breakdown.T.plot.barh(stacked=True, legend=True, ax=axs[1])
    axs[1].set_xlabel('total time (s)')
    # remove the frame around the legend
    plt.legend(frameon=False)
    # make the ledgend horizontal
    plt.legend(loc='upper left', bbox_to_anchor=(1, 1), ncol=1,frameon=False)
    # set the x axis label to time taken up in seconds
    plt.xlabel('time taken up  (seconds)')
    plt.tight_layout()





def generate_spectral_array(WL_arr, acqs, clockHz):
    """This function takes an aquisition object, the wavelength array and the camera clock speed and returns a dataframe of spectra
    args: WL_arr: wavelength array, acqs: aquisition object, clockHz: camera clock speed
    """

    acqs=list(acqs[0])

    print(acqs[0].image[0])
    # generate a numpy array with dimensions of len(acqs[0]) and len(acqs) and fill with zeros
    Spectra=np.zeros((len(acqs[0].image[0]), len(acqs)))
    ticks=np.zeros(len(acqs))

    # use list comprehension to fill the numpy array with the image data from the aquisition object 
    Spectra = np.array([acq.image[0] for acq in acqs]).T
    # use list comprehension to fill the numpy array with the timestamp data from the aquisition object 
    ticks = np.array([acq.metadata.timestamp for acq in acqs])


    Spectra=pd.DataFrame(Spectra)   
    # get the time elapsed in number of ticks of the clock
    ticks=ticks-ticks[0]    
    # convert the ticks to seconds
    Tick_time=ticks/clockHz

    # set the collumn names of the spectra dataframe to the tick_time
    Spectra.columns=Tick_time
    # set the index of the spectra dataframe to the WL_arr
    Spectra.index=WL_arr

    return Spectra



cool(cam)
PixelWidth=setup_image(cam)
WL_arr=SetupSpectroscope(PixelWidth)
horiz_pixels, vert_pixels, Stride, clockHz = GetMetaData(cam)

#test, max, range_bool, optimality=image_and_check_dynamic_range(cam, WL_arr)
#_, _, _=adjust_ND(cam, WL_arr)

#setup_SEC_aquisition(cam)
no_hours=1.5
total_time_s=3600*no_hours
read_rate_s=120
start_time=time.time()
setup_shot(cam)
while time.time()-start_time<total_time_s:
    aq=cam.acquire()
    time_elapsed=time.time()-start_time
# round time elaped to nearest whole number
    time_elapsed=round(time_elapsed)
    spec=generate_spectral_array(WL_arr, [aq], clockHz)
    # write the spectrum to a csv file with a title of the time elapsed
    spec.to_csv(str(time_elapsed)+'.csv')
    # wait for the read rate
    time.sleep(read_rate_s)
    
#acqs, timez, measurment_time = test_aquisition(cam, 100, 5000)
#acqs2=SEC_aquisition(cam, 1000, 5000)
#spectra=generate_spectral_array(WL_arr, acqs2, clockHz)



#process_timings(timez, measurment_time) 
WarmAndClose(cam, False)



