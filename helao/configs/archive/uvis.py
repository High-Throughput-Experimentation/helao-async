__all__ = ["config"]


hostip = "127.0.0.1"
config = {}
config["dummy"] = True

# action library provides generator functions which produce actions
# lists from input experiment_id grouping
config["experiment_libraries"] = ["UVIS_exp", "samples_exp"]
config["experiment_params"] = {"toggle_is_shutter": True}
config["sequence_libraries"] = ["UVIS_T_seq", "UVIS_TR_seq"]
config["sequence_params"] = {"toggle_is_shutter": True}
config["builtin_ref_motorxy"] = [100, 6]
config["run_type"] = "uvis"
config["root"] = r"C:\INST_hlo"


# we define all the servers here so that the overview is a bit better
config["servers"] = {
    "ORCH": {
        "host": "127.0.0.1",
        "port": 8001,
        "group": "orchestrator",
        "fast": "async_orch2",
        "params": {"enable_op": True, "bokeh_port": 5002},
    },
    "SPEC_T": {
        "host": "127.0.0.1",
        "port": 8004,
        "group": "action",
        "fast": "spec_server",
        "params": {
            "dev_num": 1,
            "lib_path": "C:\\Spectral Products\\SM32ProForUSB\\SDK Examples\\DLL\\x64\\stdcall\\SPdbUSBm.dll",
            "n_pixels": 1024,
            "start_margin": 5,
        },
    },
    "SPEC_R": {
        "host": "127.0.0.1",
        "port": 8008,
        "group": "action",
        "fast": "spec_server",
        "params": {
            "dev_num": 0,
            "lib_path": "C:\\Spectral Products\\SM32ProForUSB\\SDK Examples\\DLL\\x64\\stdcall\\SPdbUSBm.dll",
            "n_pixels": 1024,
            "start_margin": 5,
        },
    },
    "MOTOR": {
        "host": "127.0.0.1",
        "port": 8003,
        "group": "action",
        "fast": "galil_motion",
        "params": {
            "enable_aligner": True,
            "bokeh_port": 5003,
            "M_instr": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
            "count_to_mm": {"A": 0.00015634502846261243, "B": 0.00015624414084471834},
            "galil_ip_str": "192.168.200.246",
            "def_speed_count_sec": 10000,
            "max_speed_count_sec": 25000,
            "ipstr": "192.168.200.23",
            "axis_id": {"x": "A", "y": "B"},
            "axis_zero": {"A": 127, "B": 72.5},
            "timeout": 600,
        },
    },
    "IO": {
        "host": "127.0.0.1",
        "port": 8005,
        "group": "action",
        "fast": "galil_io",
        "params": {
            "galil_ip_str": "192.168.200.246",
            "dev_ai": {},
            "dev_ao": {},
            "dev_di": {"gamry_ttl0": 1},
            "dev_do": {
                "gamry_aux": 4,
                "doric_wled": 1,
                "wl_source": 1,
                "spec_trig": 2,
                "spec_trig2": 3,
            },
        },
    },
    "PAL": {
        "host": "127.0.0.1",
        "port": 8007,
        "group": "action",
        "fast": "pal_server",
        "params": {"positions": {"custom": {"cell1_we": "cell"}}},
    },
    "VIS": {
        "host": "127.0.0.1",
        "port": 5001,
        "group": "visualizer",
        "bokeh": "action_visualizer",
        "params": {"doc_name": "UVIS Visualizer"},
    },
}
