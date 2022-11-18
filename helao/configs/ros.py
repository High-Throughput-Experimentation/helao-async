__all__ = ["config"]

# hostip = "131.215.44.107"
hostip = "127.0.0.1"
config = {}
config["dummy"] = True

# action library provides generator functions which produce action
# lists from input decision_id grouping
# config["action_libraries"] = ["lisa_eche_demo"]
# config["experiment_libraries"] = ["lisa_ANEC2"]
config["run_type"] = "rosdev"
config["root"] = r"C:\INST_dev2\RUNS"


# we define all the servers here so that the overview is a bit better
config["servers"] = {
    "orchestrator": {
        "host": hostip,
        "port": 8001,
        "group": "orchestrator",
        "fast": "async_orch2",
        "params": {"enable_op": True, "bokeh_port": 5002}
    },
    "SYRINGE": {
        "host": hostip,
        "port": 8002,
        "group": "action",
        "fast": "syringe_server",
        "params": {"port": "COM8", "pump_addrs": {"zero": 0, "one": 1}},
    },
    "SENSOR": {
        "host": hostip,
        "port": 8003,
        "group": "action",
        "fast": "sensor_server",
        "params": {"port": "COM9", "start_margin": 0},
    },
    "PAL": {
        "host": hostip,
        "port": 8004,
        "group": "action",
        "fast": "pal_server",
        "params": {"positions": {"custom": {"cell1_we": "cell"}}},
    },
    "VIS": {
        "host": hostip,
        "port": 5001,
        "group": "visualizer",
        "bokeh": "action_visualizer",
        "params": {"doc_name": "ROS-DEV Visualizer"},
    },
    "LIVE": {
        "host": hostip,
        "port": 5002,
        "group": "visualizer",
        "bokeh": "sensor_visualizer",
        "params": {"doc_name": "Sensor Visualizer"},
    },
    # "DB": {
    #     "host": hostip,
    #     "port": 8010,
    #     "group": "action",
    #     "fast": "dbpack_server",
    #     "params": {
    #         "aws_config_path": "k:/users/hte/.credentials/aws_config.ini",
    #         "aws_profile": "default",
    #         "aws_bucket": "helao.data",
    #         "api_host": "caltech-api.modelyst.com",
    #         "testing": False,
    #     }
    # }
}
