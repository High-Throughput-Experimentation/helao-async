
__all__ = ["config"]


hostip = "127.0.0.1"
config = {}
config['dummy'] = True
config['simulation'] = False

# action library provides generator functions which produce actions
# lists from input experiment_id grouping
config["experiment_libraries"] = ["ADSS_exp", "samples_exp"]
config["sequence_libraries"] = ["ADSS_seq"]
config["run_type"] = "adss"
config["root"] = r"C:\INST_hlo"


# we define all the servers here so that the overview is a bit better
config["servers"] = dict(
    ##########################################################################
    # Orchestrator
    ##########################################################################
    ORCH=dict(
        host=hostip, 
        port=8001, 
        group="orchestrator", 
        fast="async_orch2",
        params=dict(
            enable_op = True,
            bokeh_port = 5002,
        )
    ),
    ##########################################################################
    # Instrument Servers
    ##########################################################################
    MOTOR=dict(
        host=hostip,
        port=8003,
        group="action",
        fast="galil_motion",
        params=dict(
            enable_aligner = True,
            bokeh_port = 5003,
            # backup if f"{gethostname()}_instrument_calib.json" is not found
            # instrument specific calibration
            M_instr = [
                       [1,0,0,0],
                       [0,1,0,0],
                       [0,0,1,0],
                       [0,0,0,1]
                       ],
            count_to_mm=dict(
                A=1.0/15835.31275,#1.0/15690.3,
                B=1.0/6398.771436,#1.0/6395.45,
                C=1.0/6396.315722,#1.0/6395.45,
                D=1.0/3154.787,#1.0/3154.787,
            ),
            galil_ip_str="192.168.200.23",
            def_speed_count_sec=10000,
            max_speed_count_sec=25000,
            ipstr="192.168.200.23",
            axis_id=dict(
                x="C",
                y="B",
                z="A",
                Rz="D",
                ),
            axis_zero=dict(
                A=0.0, #z
                B=52.0, #y
                C=77.0, #x
                D=0.0, #Rz
                ),
            timeout = 10*60, # timeout for axis stop in sec
        )
    ),
    PSTAT=dict(
        host=hostip,
        port=8004,
        group="action",
        fast="gamry_server",
        params=dict(
            allow_no_sample = True,
            dev_id=0,  # (default 0) Gamry device number in Gamry Instrument Manager (i-1)
        ),
    ),
    NI=dict(
        host="127.0.0.1",
        port=8006,
        group="action",
        fast="nidaqmx_server",
        params = dict(
            allow_no_sample = True,
            dev_cellcurrent_trigger = 'PFI1', #P1.1
            dev_cellvoltage_trigger = 'PFI1', #P1.1
            dev_cellcurrent = {
                '1':'PXI-6289/ai16',
                '2':'PXI-6289/ai17',
                '3':'PXI-6289/ai18',
                '4':'PXI-6289/ai19',
                '5':'PXI-6289/ai20',
                '6':'PXI-6289/ai21',
                '7':'PXI-6289/ai22',
                '8':'PXI-6289/ai23',
                #'9':'PXI-6289/ai0'
                '9':'PXI-6289/ai1'  # after rewire for thermocouple connection
                },
            dev_cellvoltage = {
                '1':'PXI-6284/ai16',
                '2':'PXI-6284/ai17',
                '3':'PXI-6284/ai18',
                '4':'PXI-6284/ai19',
                '5':'PXI-6284/ai20',
                '6':'PXI-6284/ai21',
                '7':'PXI-6284/ai22',
                '8':'PXI-6284/ai23',
                #'9':'PXI-6284/ai0'
                '9':'PXI-6284/ai1'  # after rewire for thermocouple connection
                },
            dev_temperature ={
                'type-S':'PXI-6289/ai0',
                'type-T':'PXI-6284/ai0'
                },   
            dev_heat = {
                'heater1':'PXI-6284/port2/line1', #P2.1
                'heater2':'PXI-6284/port2/line2'  #P2.2
                },
            # dev_activecell = {
            #     '1':'PXI-6289/port0/line23', #P0.23
            #     '2':'PXI-6289/port0/line24', #P0.24
            #     '3':'PXI-6289/port0/line25', #P0.25
            #     '4':'PXI-6289/port0/line26', #P0.26
            #     '5':'PXI-6289/port0/line27', #P0.27
            #     '6':'PXI-6289/port0/line28', #P0.28
            #     '7':'PXI-6289/port0/line29', #P0.29
            #     '8':'PXI-6289/port0/line30', #P0.30
            #     '9':'PXI-6289/port0/line31'  #P0.31
            #     },
            # dev_fswbcd = {
            #     '1':'PXI-6284/port0/line5', #P0.5
            #     '2':'PXI-6284/port0/line1', #P0.1
            #     '3':'PXI-6284/port0/line2', #P0.2
            #     '4':'PXI-6284/port0/line3'  #P0.3
            #     },
            dev_gasvalve = {
                '1':'PXI-6284/port1/line2', #P1.2
                '2':'PXI-6284/port1/line3', #P1.3
                '3':'PXI-6284/port1/line4', #P1.4
                '4':'PXI-6284/port1/line5', #P1.5
                '5':'PXI-6284/port1/line6', #P1.6
                '6':'PXI-6284/port1/line7', #P1.7
                '7':'PXI-6284/port2/line0', #P2.0
               # '8':'PXI-6284/port2/line1', #P2.1 repurposed for heaters
               # '9':'PXI-6284/port2/line2'  #P2.2 repurposed for heaters
               
                },
            # dev_mastercell = {
            #     '1':'PXI-6284/port0/line23', #P0.23
            #     '2':'PXI-6284/port0/line24', #P0.24
            #     '3':'PXI-6284/port0/line25', #P0.25
            #     '4':'PXI-6284/port0/line26', #P0.26
            #     '5':'PXI-6284/port0/line27', #P0.27
            #     '6':'PXI-6284/port0/line28', #P0.28
            #     '7':'PXI-6284/port0/line29', #P0.29
            #     '8':'PXI-6284/port0/line30', #P0.30
            #     '9':'PXI-6284/port0/line31', #P0.31
            #     'X':'PXI-6284/port0/line22'  #P0.22, two electrode
            #     },
            dev_pump = {
                'peripump':'PXI-6284/port0/line4	', #P0.4
                # 'MultiPeriPump':'PXI-6284/port0/line0' #P0.0
                'direction':'PXI-6284/port0/line0' #P0.0
                },
            dev_fsw = {
                'done':'PXI-6284/port2/line4',  #P2.4
                'error':'PXI-6284/port2/line6'  #P2.6
                },
            # dev_RSHTTLhandshake = {
            #     'RSH1':'PXI-6284/port2/line5',  #P2.5
            #     'RSH2':'PXI-6284/port2/line7',  #P2.7
            #     'RSH3':'PXI-6284/port2/line3',  #P2.3
            #     #'port':'PXI-6284/ctr0',
            #     #'term':'/PXI-6284/PFI8' #P2.0
            #     }
        )
    ),
    PAL=dict(
        host=hostip,
        port=8007,
        group="action",
        fast="pal_server",
        params = dict(
            user = 'RSHS',
            key = r'c:\helao\sshkeys\rshs_private3.ppk', # needs to be in new openssh file format
            host = "10.231.100.169",#r'hte-rshs-01.htejcap.caltech.edu',
            timeout = 30*60, # 30min timeout for waiting for TTL
            dev_trigger = "NImax",
            trigger = { # TTL handshake via NImax
                'start':'PXI-6284/port2/line5',  #P2.5, #PFI13
                'continue':'PXI-6284/port2/line7',  #P2.7 #PFI15
                'done':'PXI-6284/port2/line3',  #P2.3 #PFI11
                },
            cam_file_path = r'C:\Users\rshs\Desktop\ADSS\adss_psc_methods\HELAO',
            cams = {
                    "archive_tray_tray":"tray_to_tray_220214.cam",
                    "archive_custom_tray":"custom_to_tray_220214.cam",
                    "archive_tray_custom":"tray_to_custom_220214.cam",
                    # "archive":"lcfc_archive.cam",
                    # "archive_liquid":"lcfc_archive.cam",
                    # "fillfixed":"lcfc_fill_hardcodedvolume.cam",
                    # "fill":"lcfc_fill.cam",
                    # "test":"relay_actuation_test2.cam",
                    # "dilute":"lcfc_dilute.cam",
                    # "autodilute":"lcfc_dilute.cam",
                    "deepclean":"deep_clean_220214.cam",
                    },
            positions = {
                          "tray1":{
                                  "slot1":None,
                                  "slot2":None,
                                  "slot3":None,
                                  },
                          "tray2":{
                                  "slot1":"VT54",
                                  "slot2":"VT54",
                                  "slot3":"VT54",
                                  },
                          "custom":{
                                    "elec_res1":"reservoir",
                                    "elec_res2":"reservoir",
                                    "cell1_we":"cell",
                                    # "lcfc_res":"cell",
                                  }
                        },
        )
    ),
    # #########################################################################
    # Visualizers (bokeh servers)
    # #########################################################################
    VIS=dict(
        host=hostip,
        port=5001,
        group="visualizer",
        bokeh="bokeh_modular_visualizer",
        params = dict(
        )
    ),
    #
    # #########################################################################
    # DB package server
    # #########################################################################
    DB=dict(
        host=hostip,
        port=8010,
        group="action",
        fast="dbpack_server",
        params=dict(
            aws_config_path="k:/users/hte/.credentials/aws_config.ini",
            aws_profile="default",
            aws_bucket="helao.data.testing",
            api_host="caltech-api.modelyst.com",
            testing=False,
        ),
    ),
)
