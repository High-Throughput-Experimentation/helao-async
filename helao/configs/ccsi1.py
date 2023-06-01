hostip = "hte-ccsi-01.htejcap.caltech.edu"
config = {}
config["dummy"] = False
config["simulation"] = False

# action library provides generator functions which produce actions
config["experiment_libraries"] = ["CCSI_exp", "samples_exp"]
config["experiment_params"] = {
    "gamrychannelwait": -1,
    "gamrychannelsend": 1,
}
config["sequence_libraries"] = ["CCSI_seq"]
config["sequence_params"] = {
    "gamrychannelwait": -1,
    "gamrychannelsend": 1,
}
config["run_type"] = "ccsi"
config["root"] = r"C:\INST_hlo"


# we define all the servers here so that the overview is a bit better
config["servers"] = {
    "ORCH": {
        "host": hostip,
        "port": 8001,
        "group": "orchestrator",
        "fast": "async_orch2",
        "params": {"enable_op": True, "bokeh_port": 5002},
        "verbose": False,
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
            "galil_ip_str": "192.168.200.232",
            "def_speed_count_sec": 10000,
            "max_speed_count_sec": 25000,
            "ipstr": "192.168.200.23",
            "axis_id": {"x": "C", "y": "B", "z": "A"},
            "axis_zero": {"A": 0.0, "B": 52.0, "C": 77.0},
            "timeout": 600,
        },
    },
    # "PSTAT": {
    #     "host": hostip,
    #     "port": 8004,
    #     "group": "action",
    #     "fast": "gamry_server",
    #     "params": {"dev_id": 0, "filterfreq_hz": 1000.0, "grounded": True},
    # },
    "IO": {
        "host": hostip,
        "port": 8005,
        "group": "action",
        "fast": "galil_io",
        "params": {
            "galil_ip_str": "192.168.200.232",
            "dev_ai": {"cell_pressure_psi": 1},
            "dev_ao": {},
            "dev_di": {"multichannel_valve_done": 1, "multichannel_valve_error": 2},
            "dev_do": {"gamry_aux": 1, "Thorlab_led": 7},
            "monitor_ai": {"cell_pressure_psi": 5.0},  # scaling factor 5.0 psi/V
        },
    },
    "NI": {
        "host": hostip,
        "port": 8006,
        "group": "action",
        "fast": "nidaqmx_server",
        "params": {
            "dev_gasvalve": {
                "1A": "cDAQ1Mod1/port0/line0",
                "1B": "cDAQ1Mod1/port0/line1",
                "7A": "cDAQ1Mod1/port0/line9",
                "7B": "cDAQ1Mod1/port0/line10",
                # "M4": ["cDAQ1Mod1/port0/line30"],
                # "M5": ["cDAQ1Mod1/port0/line30","cDAQ1Mod1/port0/line28"],
                # "M6": ["cDAQ1Mod1/port0/line30","cDAQ1Mod1/port0/line29"],
                # "M7": ["cDAQ1Mod1/port0/line30","cDAQ1Mod1/port0/line29","cDAQ1Mod1/port0/line28"],
            },
            "dev_multivalve": {
                "multi_CMD0": "cDAQ1Mod1/port0/line28",
                "multi_CMD1": "cDAQ1Mod1/port0/line29",
                "multi_CMD2": "cDAQ1Mod1/port0/line30",
                "multi_CMD3": "cDAQ1Mod1/port0/line31",
            },
            "dev_liquidvalve": {
                "2": "cDAQ1Mod1/port0/line2",
                "3": "cDAQ1Mod1/port0/line3",
                "4": "cDAQ1Mod1/port0/line4",
                "5A-cell": "cDAQ1Mod1/port0/line5",
                "5B-waste": "cDAQ1Mod1/port0/line6",
                "6A-waste": "cDAQ1Mod1/port0/line7",
                "6B": "cDAQ1Mod1/port0/line8",
                "8": "cDAQ1Mod1/port0/line11",
                "9": "cDAQ1Mod1/port0/line12",
            },
            "dev_pump": {
                "RecirculatingPeriPump1": "cDAQ1Mod1/port0/line12",
                # "pump2": "cDAQ1Mod1/port0/line17",
                # "pump3": "cDAQ1Mod1/port0/line18",
            },
        },
    },
    "PAL": {
        "host": hostip,
        "port": 8007,
        "group": "action",
        "fast": "pal_server",
        "params": {"positions": {"custom": {"cell1_we": "cell"}}},
    },
    "VIS": {
        "host": hostip,
        "port": 5001,
        "group": "visualizer",
        "bokeh": "action_visualizer",
        "params": {"doc_name": "CCSI Visualizer"},
    },
    "LIVE": {
        "host": hostip,
        "port": 5004,
        "group": "visualizer",
        "bokeh": "live_visualizer",
        "params": {"doc_name": "Sensor Visualizer"},
        "verbose": False,
    },
    "CO2SENSOR": {
        "host": hostip,
        "port": 8012,
        "group": "action",
        "fast": "co2sensor_server",
        "params": {"port": "COM3", "start_margin": 0},
        "verbose": False,
    },
    "SYRINGE0": {
        "host": hostip,
        "port": 8013,
        "group": "action",
        "fast": "syringe_server",
        "params": {"port": "COM5", "pumps": {"zero": {"address": 0, "diameter": 26.7}}},
    },
    "SYRINGE1": {
        "host": hostip,
        "port": 8014,
        "group": "action",
        "fast": "syringe_server",
        "params": {"port": "COM6", "pumps": {"one": {"address": 1, "diameter": 26.7}}},
    },
    "MFC": {
        "host": hostip,
        "port": 8009,
        "group": "action",
        "fast": "mfc_server",
        "params": {"devices": {"N2": {"port": "COM7", "unit_id": "A"}}},
        "verbose": False,

    },
    "CALC": {
        "host": hostip,
        "port": 8011,
        "group": "action",
        "fast": "calc_server",
        "params": {},
        "verbose": False,
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
