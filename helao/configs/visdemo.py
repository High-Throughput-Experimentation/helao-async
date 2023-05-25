hostip = "hte-eche-04.htejcap.caltech.edu"
config = {}
config["dummy"] = True
config["simulation"] = True

# action library provides generator functions which produce actions
config["experiment_libraries"] = ["simulatews_exp", "TEST_exp"]
config["sequence_libraries"] = ["TEST_seq"]
config["run_type"] = "simulation"
# config["root"] = "/mnt/STORAGE/INST_hlo"  # software log and run files saved here
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
    "SIM": {
        "host": hostip,
        "port": 8002,
        "group": "action",
        "fast": "ws_simulator",
        "params": {},
    },
    "LIVE": {
        "host": hostip,
        "port": 5003,
        "group": "visualizer",
        "bokeh": "live_visualizer",
        "params": {"doc_name": "Websocket Live Visualizer"},
    },
}
