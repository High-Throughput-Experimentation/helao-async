__all__ = ["config"]


hostip = "127.0.0.1"
config = {}
config["dummy"] = True
config["simulation"] = False

# action library provides generator functions which produce actions
# lists from input experiment_id grouping
  
config["builtin_ref_motorxy"] = [110, 12]  # absolute plate coords
config["experiment_libraries"] = ["ADSS_exp", "samples_exp"]
config["experiment_params"] = {
    "gamrychannelwait": -1,
    "gamrychannelsend": -1,
}
config["sequence_libraries"] = ["ADSS_seq"]
config["sequence_params"] = {
    "gamrychannelwait": -1,
    "gamrychannelsend": -1,
}
config["run_type"] = "adss"
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
    "MOTOR": {
        "host": "127.0.0.1",
        "port": 8003,
        "group": "action",
        "fast": "galil_motion",
        "params": {
            "enable_aligner": True,
            "bokeh_port": 5003,
            "M_instr": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
            "count_to_mm": {
                "A": 0.00006314999998973812,
                "B": 0.00015627999999717445,
                "C": 0.00015634000000352077,
                "D": 0.0003169786106003353,
            },
            "z_height_mm": {
                "contact": 11.0,
                "seal": 13.0,
    #            "contact_si": 18.5,
    #            "seal_si": 21.5,
                "load": 5.0,
            },
            "galil_ip_str": "192.168.200.23",
            "def_speed_count_sec": 10000,
            "max_speed_count_sec": 25000,
            "ipstr": "192.168.200.23",
            "axis_id": {"x": "C", "y": "B", "z": "A", "Rz": "D"},
            "axis_zero": {"A": 0.0, "B": 52.0, "C": 77.0, "D": 0.0},
            "timeout": 600,
        },
    },
    "PSTAT": {
        "host": "127.0.0.1",
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
    "NI": {
        "host": "127.0.0.1",
        "port": 8006,
        "group": "action",
        "fast": "nidaqmx_server",
        "params": {
            "allow_no_sample": True,
            "dev_cellcurrent_trigger": "PFI1",
            "dev_cellvoltage_trigger": "PFI1",
            "dev_cellcurrent": {
                "1": "PXI-6289/ai16",
                "2": "PXI-6289/ai17",
                "3": "PXI-6289/ai18",
                "4": "PXI-6289/ai19",
                "5": "PXI-6289/ai20",
                "6": "PXI-6289/ai21",
                "7": "PXI-6289/ai22",
                "8": "PXI-6289/ai23",
                "9": "PXI-6289/ai3",
            },
            "dev_cellvoltage": {
                "1": "PXI-6284/ai16",
                "2": "PXI-6284/ai17",
                "3": "PXI-6284/ai18",
                "4": "PXI-6284/ai19",
                "5": "PXI-6284/ai20",
                "6": "PXI-6284/ai21",
                "7": "PXI-6284/ai22",
                "8": "PXI-6284/ai23",
                "9": "PXI-6284/ai1",
            },
            "dev_monitor": {
                "Ttemp_Ktc_in_cell_C": "PXI-6289/ai6",
                "Ttemp_Ttc_in_reservoir_C": "PXI-6289/ai7",
                "Ttemp_Ktc_out_cell_C": "PXI-6289/ai1",
                "Ttemp_Ktc_out_reservoir_C": "PXI-6289/ai2",
            },
            "dev_heat": {
                "cellheater": "PXI-6289/port0/line0",
                "res_heater": "PXI-6289/port0/line4",
            },
            "dev_gasvalve": {
                "V1": "PXI-6284/port1/line2", #1-6 white ground
                "V2": "PXI-6284/port1/line3", #7-9 grey ground
                "V3": "PXI-6284/port1/line4",
                "V4": "PXI-6284/port1/line5",
                "V5": "PXI-6284/port1/line6",
                "6": "PXI-6284/port1/line7",
                "7": "PXI-6284/port2/line0",
                "8": "PXI-6284/port2/line1",
                "9": "PXI-6284/port2/line2",
            },
            "dev_pump": {
                "peripump": "PXI-6284/port0/line4\t",
                "direction": "PXI-6284/port0/line0",
            },
            "dev_fsw": {
                "done": "PXI-6284/port2/line4",
                "error": "PXI-6284/port2/line6",
            },
        },
    },
    "PAL": {
        "host": "127.0.0.1",
        "port": 8007,
        "group": "action",
        "fast": "pal_server",
        "params": {
            "user": "RSHS",
            "key": "c:\\helao\\sshkeys\\rshs_private3.ppk",
            "host": "10.231.100.169",
            "timeout": 1800,
            "dev_trigger": "NImax",
            "trigger": {
                "start": "PXI-6284/port2/line5",
                "continue": "PXI-6284/port2/line7",
                "done": "PXI-6284/port2/line3",
            },
            "cam_file_path": "C:\\Users\\rshs\\Desktop\\ADSS\\adss_psc_methods\\HELAO",
            "cams": {
                "archive_tray_tray": "tray_to_tray_220214.cam",
                "archive_custom_tray": "custom_to_tray_220214.cam",
                "archive_tray_custom": "tray_to_custom_220214.cam",
                "deepclean": "deep_clean_220214.cam",
            },
            "positions": {
                "tray1": {"slot1": None, "slot2": None, "slot3": None},
                "tray2": {"slot1": "VT54", "slot2": "VT54", "slot3": "VT54"},
                "custom": {
                    "elec_res1": "reservoir",
                    "elec_res2": "reservoir",
                    "cell1_we": "cell",
                },
            },
        },
    },
    "VIS": {
        "host": "127.0.0.1",
        "port": 5001,
        "group": "visualizer",
        "bokeh": "action_visualizer",
        "params": {},
    },
    "SYRINGE0": {
        "host": hostip,
        "port": 8013,
        "group": "action",
        "fast": "syringe_server",
        "params": {"port": "COM7", "pumps": {"zero": {"address": 0, "diameter": 26.7}}},
    },
    "SYRINGE1": {
        "host": hostip,
        "port": 8014,
        "group": "action",
        "fast": "syringe_server",
        "params": {"port": "COM6", "pumps": {"one": {"address": 1, "diameter": 26.7}}},
    },
    "LIVE": {
        "host": hostip,
        "port": 5004,
        "group": "visualizer",
        "bokeh": "live_visualizer",
        "params": {"doc_name": "Sensor Visualizer"},
    },
    "DB": {
        "host": "127.0.0.1",
        "port": 8010,
        "group": "action",
        "fast": "dbpack_server",
        "params": {
            "aws_config_path": "k:/users/hte/.credentials/aws_config.ini",
            "aws_profile": "default",
            "aws_bucket": "helao.data.testing",
            "api_host": "caltech-api.modelyst.com",
            "testing": False,
        },
    },
}
