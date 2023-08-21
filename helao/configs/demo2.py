"""Helao instrument configuration for OER measurement simulator

Notes:
Simulated CP measurements are a subset of 3 mA/cm2 CP measurement data from 
https://doi.org/10.1039/C8MH01641K

The "plate_id" parameter for the CPSIM server accepts any of the following integer
values which map to 6!4 quaternary oxide composition spaces for a given plate library:
    {2750: {'Ce', 'Co', 'Fe', 'La', 'Ni', 'Ta'},
    3496: {'Ce', 'Co', 'Fe', 'La', 'Mn', 'Ni'},
    3851: {'Co', 'Cu', 'Fe', 'Mn', 'Ni', 'Ta'},
    3860: {'Co', 'Cu', 'Fe', 'Mn', 'Sn', 'Ta'},
    3875: {'Co', 'Cu', 'Fe', 'Mn', 'Sn', 'Ta'},
    4084: {'Ca', 'Co', 'Mg', 'Mn', 'Sn', 'Zn'},
    4098: {'Ca', 'Co', 'Mn', 'Ni', 'Sb', 'Sn'}}

The shared compute GPSIM server is launched with the demo0 configuration, and is only
linked via host and port as an available resournce in demo1 and demo2.

"""

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
        "port": 8021,
        "group": "orchestrator",
        "fast": "async_orch2",
        "params": {"enable_op": True, "bokeh_port": 5021},
    },
    "CPSIM": {
        "host": HOSTIP,
        "port": 8022,
        "group": "action",
        "fast": "cpsim_server",
        "params": {"plate_id": 4098},
    },
    "VIS": {
        "host": HOSTIP,
        "port": 5022,
        "group": "visualizer",
        "bokeh": "action_visualizer",
        "params": {"doc_name": "demo2: OER Simulation Visualizer"},
    },
    "GPSIM": {
        "host": HOSTIP,
        "port": 8003,
        "group": "action",
    },
}
