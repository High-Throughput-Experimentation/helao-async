__all__ = ["config"]


hostip = "hte-eche-04.htejcap.caltech.edu"
config = {}
config["dummy"] = True
config["simulation"] = False

config["builtin_ref_motorxy"] = [110, 12]  # absolute plate coords
config["experiment_libraries"] = ["samples_exp", "ECHE_exp", "ECHEUVIS_exp", "UVIS_exp", "TEST_exp"]
config["experiment_params"] = {
    "toggle_is_shutter": False,
    "gamrychannelwait": -1,
    "gamrychannelsend": 0,
}
config["sequence_libraries"] = ["ECHE_seq", "ECHEUVIS_seq", "UVIS_T_seq", "TEST_seq"]
config["sequence_params"] = {
    "led_wavelengths_nm": [-1],
    "led_intensities_mw": [0.432],
    "led_names": ["doric_wled"],
    "led_type": "front",
    "led_date": "8/16/2022",  # m/d/yyyy
    "toggle_is_shutter": False,
    "gamrychannelwait": -1,
    "gamrychannelsend": 0,
}
# config["sequence_params"] = {
#     "led_wavelengths_nm": [385, 455, 515, 590],
#     "led_intensities_mw": [1.725, 1.478, 0.585, 0.366],
#     "led_names": ["doric_led1", "doric_led2", "doric_led3", "doric_led4"],
#     "led_type": "front",
#     "led_date": "12/23/2020"
# }
config["run_type"] = "eche"
config["root"] = r"C:\INST_hlo"


# we define all the servers here so that the overview is a bit better
config["servers"] = {
    "ORCH": {
        "host": hostip,
        "port": 8001,
        "group": "orchestrator",
        "fast": "async_orch2",
        "params": {"enable_op": True, "bokeh_port": 5002},
    },
    "MOTOR": {
        "host": hostip,
        "port": 8003,
        "group": "action",
        "fast": "galil_motion",
        "params": {
            "enable_aligner": True,
            "bokeh_port": 5003,
            "M_instr": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
            "count_to_mm": {"A": 0.00015634502846261243, "B": 0.00015624414084471834},
            "galil_ip_str": "192.168.200.235",
            "def_speed_count_sec": 10000,
            "max_speed_count_sec": 25000,
            "ipstr": "192.168.200.23",
            "axis_id": {"x": "B", "y": "A"},
            "axis_zero": {"A": 127.8, "B": 76.7},
            "timeout": 600,
        },
    },
    "PSTAT": {
        "host": hostip,
        "port": 8004,
        "group": "action",
        "fast": "gamry_server",
        "params": {
            "allow_no_sample": True,
            "dev_id": 0,
            "filterfreq_hz": 1000.0,
            "grounded": True,
        },
    },
    "IO": {
        "host": hostip,
        "port": 8005,
        "group": "action",
        "fast": "galil_io",
        "params": {
            "galil_ip_str": "192.168.200.235",
            "dev_ai": {},
            "dev_ao": {},
            "dev_di": {"gamry_ttl0": 1},
            "dev_do": {
                "gamry_aux": 1,
                "spec_trig": 1,
                "led": 8,
                "pump_ref_flush": 3,
                "pump_supply": 2,
                "doric_led1": 4,
                "doric_wled": 5,
                "doric_led2": 5,
                "doric_led3": 6,
                # "doric_led4": 7,
                "ir_emitter": 7,
            },
        },
    },
    "PAL": {
        "host": hostip,
        "port": 8007,
        "group": "action",
        "fast": "pal_server",
        "params": {"positions": {"custom": {"cell1_we": "cell"}}},
    },
    "SPEC_T": {
        "host": hostip,
        "port": 8011,
        "group": "action",
        "fast": "spec_server",
        "params": {
            "dev_num": 0,
            "lib_path": "C:\\Spectral Products\\SM32ProForUSB\\SDK Examples\\DLL\\x64\\stdcall\\SPdbUSBm.dll",
            "n_pixels": 1024,
            "start_margin": 5,
        },
    },
    "MFC": {
        "host": hostip,
        "port": 8009,
        "group": "action",
        "fast": "mfc_server",
        "params": {"devices": {"N2": {"port": "COM6", "unit_id": "A"}}},
    },
    # "CALC": {
    #     "host": hostip,
    #     "port": 8012,
    #     "group": "action",
    #     "fast": "calc_server",
    #     "params": {},
    # },
    "VIS": {
        "host": hostip,
        "port": 5001,
        "group": "visualizer",
        "bokeh": "action_visualizer",
        "params": {"doc_name": "ECHE4 Visualizer"},
    },
    # "LIVE": {
    #     "host": hostip,
    #     "port": 5004,
    #     "group": "visualizer",
    #     "bokeh": "live_visualizer",
    #     "params": {"doc_name": "Sensor Visualizer"},
    # },
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
    #     },
    # },
    # "CAM": {
    #     "host": hostip,
    #     "port": 8013,
    #     "group": "action",
    #     "fast": "cam_server",
    #     "params": {
    #         "axis_ip": "192.168.200.210",
    #     },
    # },
}
