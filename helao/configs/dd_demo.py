"""Helao instrument configuration for OER measurement simulator"""

hostip = "127.0.0.1"
config = {}
config["dummy"] = True
config["simulation"] = True

# action library provides generator functions which produce actions
config["experiment_libraries"] = ["TEST_exp"]
config["sequence_libraries"] = ["TEST_seq"]
config["run_type"] = "simulation"
config["root"] = "c:/INST_hlo"  # software log and run files saved here


# we define all the servers here so that the overview is a bit better
config["servers"] = {
    "ORCH": {
        "host": hostip,
        "port": 8001,
        "group": "orchestrator",
        "fast": "async_orch2",
        "params": {"enable_op": True, "bokeh_port": 5001},
    },
    "OERSIM": {
        "host": hostip,
        "port": 8002,
        "group": "action",
        "fast": "ws_simulator",
        "params": {},
    },
    "VIS": {
        "host": hostip,
        "port": 5002,
        "group": "visualizer",
        "bokeh": "action_visualizer",
        "params": {"doc_name": "OER Simulation Visualizer"},
    },
}
