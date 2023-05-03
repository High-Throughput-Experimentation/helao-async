hostip = "hte-ccsi-01.htejcap.caltech.edu"
config = {}
config["dummy"] = True
config["simulation"] = False

# action library provides generator functions which produce actions
config["experiment_libraries"] = ["DEMO_exp"]
config["experiment_params"] = {
    "gamrychannelwait": -1,
    "gamrychannelsend": 1,
}
config["sequence_libraries"] = []
config["sequence_params"] = {
    "gamrychannelwait": -1,
    "gamrychannelsend": 1,
}
config["run_type"] = "demo"
config["root"] = r"C:\INST_hlo"


# we define all the servers here so that the overview is a bit better
config["servers"] = {
    "ORCH": {
        "host": hostip,
        "port": 8001,
        "group": "orchestrator",
        "fast": "async_orch2",
        "params": {"enable_op": True, "bokeh_port": 5002},
        "verbose": True,
    },
    "PSTAT": {
        "host": hostip,
        "port": 8004,
        "group": "action",
        "fast": "gamry_server",
        "params": {"dev_id": 0, "filterfreq_hz": 1000.0, "grounded": True},
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
        "verbose": True,
    },
    "CO2SENSOR": {
        "host": hostip,
        "port": 8012,
        "group": "action",
        "fast": "co2sensor_server",
        "params": {"port": "COM3", "start_margin": 0},
        "verbose": True,
    },
}
