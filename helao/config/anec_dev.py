hostip = "127.0.0.1"
config = dict()

# action library provides generator functions which produce actions
config["experiment_libraries"] = ["ANEC_exp", "samples_exp"]
config["sequence_libraries"] = ["ANEC_seq"]
config["technique_name"] = "anec"
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
    MOTOR=dict(
        host=hostip,
        port=8003,
        group="action",
        fast="galil_motion",
        params=dict(
            enable_aligner=True,
            bokeh_port=5003,
            # backup if f"{gethostname()}_instrument_calib.json" is not found
            # instrument specific calibration
            M_instr=[[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
            count_to_mm=dict(
                A=1.0 / 16282.23,
                B=1.0 / 6397.56,
                C=1.0 / 6358.36,
            ),
            galil_ip_str="192.168.99.222",
            def_speed_count_sec=10000,
            max_speed_count_sec=25000,
            ipstr="192.168.200.23",
            axis_id=dict(
                x="C",
                y="B",
                z="A",
            ),
            axis_zero=dict(
                A=0.0,  # z
                B=52.0,  # y
                C=77.0,  # x
            ),
            timeout=10 * 60,  # timeout for axis stop in sec
        ),
    ),
    PSTAT=dict(
        host=hostip,
        port=8004,
        group="action",
        fast="gamry_server",
        params=dict(
            dev_id=0,  # (default 0) Gamry device number in Gamry Instrument Manager (i-1)
        ),
    ),
    NI=dict(
        host="127.0.0.1",
        port=8006,
        group="action",
        fast="nidaqmx_server",
        params=dict(
            dev_pump={
                "PeriPump1": "cDAQ1Mod1/port0/line9",
                "PeriPump2": "cDAQ1Mod1/port0/line7",
                "Direction": "cDAQ1Mod1/port0/line8",
            },
            dev_gasvalve={
                "CO2": "cDAQ1Mod1/port0/line0",
                "Ar": "cDAQ1Mod1/port0/line2",
                "atm": "cDAQ1Mod1/port0/line5",
            },
            dev_liquidvalve={
                "liquid": "cDAQ1Mod1/port0/line1",
                "up": "cDAQ1Mod1/port0/line4",
                "down": "cDAQ1Mod1/port0/line3",
            },
            dev_led={
                "led": "cDAQ1Mod1/port0/line11",
            },
        ),
    ),
    PAL=dict(
        host=hostip,
        port=8007,
        group="action",
        fast="pal_server",
        params=dict(
            host="localhost",
            timeout=5 * 60,  # 30min timeout for waiting for TTL
            dev_trigger="NImax",
            trigger={  # TTL handshake via NImax
                "start": "cDAQ1Mod2/port0/line1",  # TTL1
                "continue": "cDAQ1Mod2/port0/line2",  # TTL2
                "done": "cDAQ1Mod2/port0/line3",  # TTL3
            },
            cam_file_path=r"C:\Users\anec\Desktop\psc_methods\active_methods\HELAO",
            # cams={
            #     "deepclean": "HELAO_LiquidSyringe_DeepClean_220215.cam",  #
            #     # "injection_custom_HPLC":"HELAO_HPLC_LiquidInjection_Custom_to_HPLCInjector_220215.cam",
            #     "injection_tray_HPLC": "HELAO_LiquidSyringe_DeepClean_220215.cam",  #
            #     "injection_custom_GC_gas_wait": "HELAO_LiquidSyringe_DeepClean_220215.cam",  #
            #     "injection_custom_GC_gas_start": "HELAO_LiquidSyringe_DeepClean_220215.cam",  #
            #     "injection_tray_GC_liquid_start": "HELAO_LiquidSyringe_DeepClean_220215.cam",  #
            #     "archive": "HELAO_LiquidSyringe_DeepClean_220215.cam",  #
            # },
            cams={
                "deepclean": "HELAO_LiquidSyringe_DeepClean_220215.cam",  #
                # "injection_custom_HPLC":"HELAO_HPLC_LiquidInjection_Custom_to_HPLCInjector_220215.cam",
                "injection_tray_HPLC": "HELAO_HPLC_LiquidInjection_Tray_to_HPLCInjector_220215.cam",  #
                "injection_custom_GC_gas_wait": "HELAO_GCHeadspace_Injection1_220215.cam",  #
                "injection_custom_GC_gas_start": "HELAO_GCHeadspace_Injection2_220215.cam",  #
                "injection_tray_GC_liquid_start": "HELAO_GC_LiquidInjection_FromArchive_220215.cam",  #
                "archive": "HELAO_GCHeadspace_Liquid_Archive_220215.cam",  #
            },
            positions={
                "tray2": {
                    "slot1": "VT54",
                    "slot2": "VT54",
                    "slot3": "VT15",
                },
                "custom": {
                    "cell1_we": "cell",
                    "Injector 1": "injector",
                    "Injector 2": "injector",
                    "LCInjector1": "injector",
                },
            },
        ),
    ),
    # #########################################################################
    # Visualizers (bokeh servers)
    # #########################################################################
    VIS=dict(
        host=hostip,
        port=5001,
        group="visualizer",
        bokeh="bokeh_modular_visualizer",
        params=dict(
            doc_name="ANEC Visualizer",
        ),
    ),
    # #########################################################################
    # DB package server
    # #########################################################################
# =============================================================================
#     DB=dict(
#         host=hostip,
#         port=8010,
#         group="action",
#         fast="dbpack_server",
#         params=dict(
#             aws_config_path="k:/users/hte/.credentials/aws_config.ini",
#             aws_profile="default",
#             aws_bucket="helao.data.testing",
#             api_host="caltech-api.modelyst.com",
#         ),
#     ),
# =============================================================================
)
