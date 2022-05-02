__all__ = ["config"]


hostip = "127.0.0.1"
config = {}

# action library provides generator functions which produce actions
# lists from input experiment_id grouping
config["experiment_libraries"] = []
# config["experiment_libraries"] = ["SDC_exp", "samples_exp"]
# config["experiment_params"] = {"wavelength_intensity_mw": 2,
# "wavelength_intensity_mwled2": 2,
# "wavelength_intensity_mwled3": 4,
# "wavelength_intensity_mwled4": 5,
#  "wavelength_intensity_date": "12/23/2020"
# 1.725 1.478 .585 .366
#                            }
config["sequence_libraries"] = []
# config["sequence_libraries"] = ["SDC_seq"]
# config["sequence_params"] = {"wavelength_intensity_mwled1": 1.725,
#                                "wavelength_intensity_mwled2": 1.478,
#                                "wavelength_intensity_mwled3": 0.585,
#                                "wavelength_intensity_mwled4": 0.366,
#                                "wavelength_intensity_date": "12/23/2020"
#                              # 1.725 1.478 .585 .366
#                              }
config["technique_name"] = "eche"
config["root"] = r"C:\INST_dev2"


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
            enable_op=True,
            bokeh_port=5002,
        ),
    ),
    ##########################################################################
    # Instrument Servers
    ##########################################################################
    SPEC=dict(
        host=hostip,
        port=8002,
        group="action",
        fast="spec_server",
        params=dict(
            dev_num=0,
            lib_path=r"C:\Users\eche\Downloads\SM32ProForUSB_2.34.34\SM32ProForUSB_2.34.34\SDKs\DLL\x64\stdcall\SPdbUSBm.dll",
            n_pixels=1024,
            wl_cal=[2537, 3132, 3650, 4047, 4358, 5461, 6965, 7635, 8115, 9123],
            px_cal=[173,  239,  299,  342,  376,  494,  652,  721,  769,  871],
            # px_cal=[269, 386, 488, 564, 624, 831, 1108, 1228, 1314, 1493],
        ),
    ),
    # MOTOR=dict(
    #     host=hostip,
    #     port=8003,
    #     group="action",
    #     fast="galil_motion",
    #     # cmd_print=False,
    #     params=dict(
    #         enable_aligner = True,
    #         bokeh_port = 5003,
    #         # backup if f"{gethostname()}_instrument_calib.json" is not found
    #         # instrument specific calibration
    #         M_instr = [
    #                    [1,0,0,0],
    #                    [0,1,0,0],
    #                    [0,0,1,0],
    #                    [0,0,0,1]
    #                    ],
    #         count_to_mm=dict(
    #             A=1.0/6396.11,
    #             B=1.0/6400.24,
    #         ),
    #         galil_ip_str="192.168.200.235",
    #         def_speed_count_sec=10000,
    #         max_speed_count_sec=25000,
    #         ipstr="192.168.200.23",
    #         axis_id=dict(
    #             x="B",
    #             y="A",
    #             ),
    #         axis_zero=dict(
    #             A=127.8, #z
    #             B=76.7, #y
    #             ),
    #         timeout = 10*60, # timeout for axis stop in sec
    #     )
    # ),
    # PSTAT=dict(
    #     host=hostip,
    #     port=8004,
    #     group="action",
    #     fast="gamry_server",
    #     params=dict(
    #         allow_no_sample = True,
    #         dev_id=0,  # (default 0) Gamry device number in Gamry Instrument Manager (i-1)
    #     ),
    # ),
    IO=dict(
        host=hostip,
        port=8005,
        group="action",
        fast="galil_io",
        params=dict(
            galil_ip_str="192.168.200.235",
            dev_ai = {
                },
            dev_ao = {
                },
            dev_di = {
                "gamry_ttl0":1,
                },
            dev_do = {
                "gamry_aux":1,
                # "led":8,
                "spec_trig":8,
                "pump_ref_flush":3,
                "doric_led1":4,
                "pump_supply":2,
                "doric_led2":5,
                "doric_led3":6,
                "doric_led4":7,
                },
        )
    ),
    # PAL=dict(
    #     host=hostip,
    #     port=8007,
    #     group="action",
    #     fast="pal_server",
    #     params = dict(
    #         positions = {
    #                       "custom":{
    #                                 "cell1_we":"cell",
    #                               }
    #                     },
    #     )
    # ),
    # # #########################################################################
    # # Visualizers (bokeh servers)
    # # #########################################################################
    # VIS=dict(
    #     host=hostip,
    #     port=5001,
    #     group="visualizer",
    #     bokeh="bokeh_modular_visualizer",
    #     params = dict(
    #         doc_name = "ECHE4 Visualizer",
    #     )
    # ),
)
