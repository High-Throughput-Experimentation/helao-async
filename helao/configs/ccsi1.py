hostip = "127.0.0.1"
config = {}
config["dummy"] = True
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
config["run_type"] = "ANEC"
config["root"] = r"C:\INST_hlo"


# we define all the servers here so that the overview is a bit better
config["servers"] = {
    "ORCH": {
        "host": "127.0.0.1",
        "port": 8001,
        "group": "orchestrator",
        "fast": "async_orch2",
        "params": {"enable_op": True, "bokeh_port": 5002},
    },
    "MOTOR": {
        "host": "127.0.0.1",
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
            "galil_ip_str": "192.168.200.218",
            "def_speed_count_sec": 10000,
            "max_speed_count_sec": 25000,
            "ipstr": "192.168.200.23",
            "axis_id": {"x": "C", "y": "B", "z": "A"},
            "axis_zero": {"A": 0.0, "B": 52.0, "C": 77.0},
            "timeout": 600,
        },
    },
    "PSTAT": {
        "host": "127.0.0.1",
        "port": 8004,
        "group": "action",
        "fast": "gamry_server",
        "params": {"dev_id": 0, "filterfreq_hz": 1000.0, "grounded": True},
    },
    "IO": {
        "host": "127.0.0.1",
        "port": 8005,
        "group": "action",
        "fast": "galil_io",
        "params": {
            "galil_ip_str": "192.168.200.218",
            "dev_ai": {"cell_pressure_psi": 1},
            "dev_ao": {},
            "dev_di": {"multichannel_valve_done": 1, "multichannel_valve_error": 2},
            "dev_do": {"gamry_aux": 1, "Thorlab_led": 7},
            "monitor_ai": {"cell_pressure_psi": 5.0},  # scaling factor 5.0 psi/V
        },
    },
    "NI": {
        "host": "127.0.0.1",
        "port": 8006,
        "group": "action",
        "fast": "nidaqmx_server",
        "params": {
            "dev_liquidvalve": {
                "1A": "cDAQ1Mod1/port0/line0",
                "1B": "cDAQ1Mod1/port0/line1",
                "2": "cDAQ1Mod1/port0/line2",
                "3A": "cDAQ1Mod1/port0/line3",
                "4A": "cDAQ1Mod1/port0/line4",
                "5A-cell": "cDAQ1Mod1/port0/line5",
                "5B-waste": "cDAQ1Mod1/port0/line6",
                "6A-waste": "cDAQ1Mod1/port0/line7",
                "6B": "cDAQ1Mod1/port0/line8",
                "blank": "cDAQ1Mod1/port0/line9",
                "multi_CMD0": "cDAQ1Mod1/port0/line28",
                "multi_CMD1": "cDAQ1Mod1/port0/line29",
                "multi_CMD2": "cDAQ1Mod1/port0/line30",
                "multi_CMD3": "cDAQ1Mod1/port0/line31",
            },
            "dev_triggers": {
                "pump1": "cDAQ1Mod1/port0/line16",
                "pump2": "cDAQ1Mod1/port0/line17",
                "pump3": "cDAQ1Mod1/port0/line18",
            },
        },
    },
    "PAL": {
        "host": "127.0.0.1",
        "port": 8007,
        "group": "action",
        "fast": "pal_server",
        "params": {"positions": {"custom": {"cell1_we": "cell"}}},
    },
    "VIS": {
        "host": "127.0.0.1",
        "port": 5001,
        "group": "visualizer",
        "bokeh": "action_visualizer",
        "params": {"doc_name": "CCSI Visualizer"},
    },
    "DB": {
        "host": "127.0.0.1",
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
