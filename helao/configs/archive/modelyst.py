hostip = "127.0.0.1"
config = {}
config["dummy"] = True
config["simulation"] = False

# action library provides generator functions which produce actions
config["experiment_libraries"] = []
config["sequence_libraries"] = []
config["run_type"] = "modelyst_test"
config["root"] = "/mnt/BIGSTOR/INST"  ### software log and run files saved here


# we define all the servers here so that the overview is a bit better
config["servers"] = {
    "ORCH": {
        "host": "127.0.0.1",
        "port": 8001,
        "group": "orchestrator",
        "fast": "async_orch2",
        "params": {"enable_op": True, "bokeh_port": 5002},
    },
    "DB": {
        "host": "127.0.0.1",
        "port": 8010,
        "group": "action",
        "fast": "dbpack_server",
        "params": {
            "aws_config_path": "/mnt/k/users/hte/.credentials/aws_config.ini",
            "aws_profile": "default",
            "aws_bucket": "helao.data.testing",
            "api_host": "caltech-api.modelyst.com",
            "testing": False,
        },
    },
}
