hostip = "127.0.0.1"
config = {}
config["dummy"] = True
config["simulation"] = True

# action library provides generator functions which produce actions
config["experiment_libraries"] = ["simulate_exp"]
config["sequence_libraries"] = []
config["run_type"] = "simulation"
config["root"] = "/mnt/STORAGE/INST_hlo"  # software log and run files saved here


# we define all the servers here so that the overview is a bit better
config["servers"] = {
    "ORCH": {
        "host": "127.0.0.1",
        "port": 8001,
        "group": "orchestrator",
        "fast": "async_orch2",
        "params": {"enable_op": True, "bokeh_port": 5002},
    },
    "PAL": {
        "host": "127.0.0.1",
        "port": 8003,
        "group": "action",
        "fast": "archive_simulator",
        "params": {"data_path": "/mnt/STORAGE/helao_tmp/20191108_multipH_OER_full.csv"},
    },
    "MOTOR": {
        "host": "127.0.0.1",
        "port": 8004,
        "group": "action",
        "fast": "motion_simulator",
        "params": {
            "platemap_path": "/mnt/STORAGE/helao_tmp/0069-04-0100-mp.txt",
            "count_to_mm": {"A": 0.00015632645340611895, "B": 0.00015648717587593696},
            "def_speed_count_sec": 10000,
            "max_speed_count_sec": 25000,
        },
    },
    "PSTAT": {
        "host": "127.0.0.1",
        "port": 8005,
        "group": "action",
        "fast": "pstat_simulator",
        "params": {"data_path": "/mnt/STORAGE/helao_tmp/20191108_multipH_OER_full.csv"},
    },
    "ANA": {
        "host": "127.0.0.1",
        "port": 8009,
        "group": "action",
        "fast": "analysis_simulator",
        "params": {"data_path": "/mnt/STORAGE/helao_tmp/20191108_multipH_OER_full.csv"},
    },
}
