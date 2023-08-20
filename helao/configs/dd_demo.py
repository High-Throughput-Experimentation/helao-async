"""Helao instrument configuration for OER measurement simulator"""

HOSTIP = "127.0.0.1"
config = {}
config["dummy"] = True
config["simulation"] = True

# action library provides generator functions which produce actions
config["experiment_libraries"] = ["OERSIM_exp"]
config["sequence_libraries"] = ["OERSIM_seq"]
config["run_type"] = "simulation"
config["root"] = "/mnt/STORAGE/INST_hlo"  # software log and run files saved here


# we define all the servers here so that the overview is a bit better
config["servers"] = {
    "ORCH": {
        "host": HOSTIP,
        "port": 8001,
        "group": "orchestrator",
        "fast": "async_orch2",
        "params": {"enable_op": True, "bokeh_port": 5001},
    },
    "CPSIM": {
        "host": HOSTIP,
        "port": 8002,
        "group": "action",
        "fast": "cpsim_server",
        "params": {"plate_id": 2750},
    },
    "VIS": {
        "host": HOSTIP,
        "port": 5002,
        "group": "visualizer",
        "bokeh": "action_visualizer",
        "params": {"doc_name": "OER Simulation Visualizer"},
    },
    "GPSIM": {
        "host": HOSTIP,
        "port": 8003,
        "group": "action",
        "fast": "gpsim_server",
        "params": {}
    },
}
