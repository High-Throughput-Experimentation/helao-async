__all__ = ["config"]


hostip = "hte-eche-08.htejcap.caltech.edu"
config = {}
config["dummy"] = False
config["simulation"] = False

# action library provides generator functions which produce actions
# lists from input experiment_id grouping
config["experiment_libraries"] = ["ECHE_exp", "samples_exp"]
config["experiment_params"] = {
    "gamrychannelwait": -1,
    "gamrychannelsend": -1,
}
config["sequence_libraries"] = ["ECHE_seq"]
config["sequence_params"] = {
    "gamrychannelwait": -1,
    "gamrychannelsend": -1,
}
config["run_type"] = "eche"
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
            "count_to_mm": {"A": 0.00015625756872598518, "B": 0.0001561880128823873},
            "galil_ip_str": "192.168.200.234",
            "def_speed_count_sec": 10000,
            "max_speed_count_sec": 25000,
            "ipstr": "192.168.200.234",
            "axis_id": {"x": "B", "y": "A"},
            "axis_zero": {"A": 152.9, "B": 102.1},
            "timeout": 600,
        },
    },
    "PSTAT": {
        "host": hostip,
        "port": 8004,
        "group": "action",
        "fast": "gamry_server",
        "params": {
            "allow_no_sample": True,
            "dev_id": 0,
            "filterfreq_hz": 1000.0,
            "grounded": True,
        },
    },
    "IO": {
        "host": hostip,
        "port": 8005,
        "group": "action",
        "fast": "galil_io",
        "params": {
            "galil_ip_str": "192.168.200.234",
            "dev_ai": {},
            "dev_ao": {},
            "dev_di": {"gamry_ttl0": 1},
            "dev_do": {"gamry_aux": 1, "led": 2, "pump_ref_flush": 3, "unknown2": 5},
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
        "params": {"doc_name": "ECHE8 Visualizer"},
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
