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
    },
    "SYRINGE": {
        "host": hostip,
        "port": 8002,
        "group": "action",
        "fast": "legato_server",
        "params": {"port": "COM8", "pump_addrs": {"zero": 0, "one": 1}},
    },
    "SENSOR": {
        "host": hostip,
        "port": 8003,
        "group": "action",
        "fast": "sensor_server",
        "params": {"port": "COM9"},
    },
}
