hostip = "anec-03"
config = {}
config["dummy"] = False
config["simulation"] = False

# action library provides generator functions which produce actions
config["experiment_libraries"] = ["ANEC_exp", "samples_exp"]
config["experiment_params"] = {
    "gamrychannelwait": -1,
    "gamrychannelsend": 1,
}
config["sequence_libraries"] = ["ANEC_seq"]
config["sequence_params"] = {
    "gamrychannelwait": -1,
    "gamrychannelsend": 1,
}
config["run_type"] = "anec"
config["root"] = r"C:\INST_hlo"


# we define all the servers here so that the overview is a bit better
config["servers"] = {
    "ORCH": {
        "host": hostip,
        "port": 8001,
        "group": "orchestrator",
        "fast": "async_orch2",
        "params": {"enable_op": True, "bokeh_port": 5002},
    },
    "MOTOR": {
        "host": hostip,
        "port": 8003,
        "group": "action",
        "fast": "galil_motion",
        "params": {
            "enable_aligner": True,
            "bokeh_port": 5003,
            "M_instr": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
            "count_to_mm": {
                "A": 6.141664870229693e-05,
                "B": 0.00015630959303234357,
                "C": 0.00015727325914229457,
            },
            "galil_ip_str": "192.168.99.222",
            "def_speed_count_sec": 10000,
            "max_speed_count_sec": 25000,
            "ipstr": "192.168.200.23",
            "axis_id": {"x": "C", "y": "B", "z": "A"},
            "axis_zero": {"A": 0.0, "B": 52.0, "C": 77.0},
            "timeout": 600,
        },
    },
    "PSTAT": {
        "host": hostip,
        "port": 8004,
        "group": "action",
        "fast": "gamry_server",
        "params": {"dev_id": 0, "filterfreq_hz": 1000.0, "grounded": True},
    },
    "IO": {
        "host": hostip,
        "port": 8005,
        "group": "action",
        "fast": "galil_io",
        "params": {
            "galil_ip_str": "192.168.99.222",
            "dev_ai": {},
            "dev_ao": {},
            "dev_di": {"gamry_ttl0": 1},
            "dev_do": {"gamry_aux": 1, "Thorlab_led": 7},
        },
    },
    "NI": {
        "host": hostip,
        "port": 8006,
        "group": "action",
        "fast": "nidaqmx_server",
        "params": {
            "dev_pump": {
                "PeriPump1": "cDAQ1Mod1/port0/line9",
                "PeriPump2": "cDAQ1Mod1/port0/line7",
                "Direction": "cDAQ1Mod1/port0/line8",
            },
            "dev_gasvalve": {
                "CO2": "cDAQ1Mod1/port0/line0",
                "Ar": "cDAQ1Mod1/port0/line2",
                "atm": "cDAQ1Mod1/port0/line5",
            },
            "dev_liquidvalve": {
                "liquid": "cDAQ1Mod1/port0/line1",
                "up": "cDAQ1Mod1/port0/line4",
                "down": "cDAQ1Mod1/port0/line3",
            },
            "dev_led": {"led": "cDAQ1Mod1/port0/line11"},
        },
    },
    "PAL": {
        "host": hostip,
        "port": 8007,
        "group": "action",
        "fast": "pal_server",
        "params": {
            "host": "localhost",
            "timeout": 300,
            "dev_trigger": "NImax",
            "trigger": {
                "start": "cDAQ1Mod2/port0/line1",
                "continue": "cDAQ1Mod2/port0/line2",
                "done": "cDAQ1Mod2/port0/line3",
            },
            "cam_file_path": "C:\\Users\\anec\\Desktop\\psc_methods\\active_methods\\HELAO",
            "cams": {
                "deepclean": "HELAO_LiquidSyringe_DeepClean_220215.cam",
                "injection_tray_HPLC": "HELAO_HPLC_LiquidInjection_Tray_to_HPLCInjector_220215.cam",
                "injection_custom_GC_gas_wait": "HELAO_GCHeadspace_Injection1_220215.cam",
                "injection_custom_GC_gas_start": "HELAO_GCHeadspace_Injection2_220215.cam",
                "injection_tray_GC_liquid_start": "HELAO_GC_LiquidInjection_FromArchive_220215.cam",
                "archive": "HELAO_GCHeadspace_Liquid_Archive_220215.cam",
            },
            "positions": {
                "tray1": {"slot1": None, "slot2": None, "slot3": None},
                "tray2": {"slot1": "VT54", "slot2": "VT54", "slot3": "VT54"},
                "custom": {
                    "cell1_we": "cell",
                    "Injector 1": "injector",
                    "Injector 2": "injector",
                    "LCInjector1": "injector",
                },
            },
        },
    },
    "VIS": {
        "host": hostip,
        "port": 5001,
        "group": "visualizer",
        "bokeh": "action_visualizer",
        "params": {"doc_name": "ANEC Visualizer"},
    },
    "DB": {
        "host": hostip,
        "port": 8010,
        "group": "action",
        "fast": "dbpack_server",
        "params": {
            "aws_config_path": "k:/users/hte/.credentials/aws_config.ini",
            "aws_profile": "default",
            "aws_bucket": "helao.data",
            "api_host": "caltech-api.modelyst.com",
            "testing": False,
        },
    },
}
