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
config["run_type"] = "uvis"
config["root"] = r"C:\INST_hlo"


# we define all the servers here so that the overview is a bit better
config["servers"] = dict(
    ##########################################################################
    # Orchestrator
    ##########################################################################
    ORCH=dict(
        host=hostip,
        port=8001,
        group="orchestrator",
        fast="async_orch2",
        params=dict(
            enable_op=True,
            bokeh_port=5002,
        ),
    ),
    ##########################################################################
    # Instrument Servers
    ##########################################################################
    SPEC_T=dict(
        host=hostip,
        port=8004,
        group="action",
        fast="spec_server",
        params=dict(
            dev_num=0,
            lib_path=r"C:\Spectral Products\SM32ProForUSB\SDK Examples\DLL\x64\stdcall\SPdbUSBm.dll",
            n_pixels=1024,
            start_margin=5,
            # id_vendor = 0x0547,
            # id_product = 0x0322,
        ),
    ),
    SPEC_R=dict(
        host=hostip,
        port=8008,
        group="action",
        fast="spec_server",
        params=dict(
            dev_num=1,
            lib_path=r"C:\Spectral Products\SM32ProForUSB\SDK Examples\DLL\x64\stdcall\SPdbUSBm.dll",
            n_pixels=1024,
            start_margin=5,
            # id_vendor = 0x0547,
            # id_product = 0x0322,
        ),
    ),
    MOTOR=dict(
        host=hostip,
        port=8003,
        group="action",
        fast="galil_motion",
        # cmd_print=False,
        params=dict(
            enable_aligner=True,
            bokeh_port=5003,
            # backup if f"{gethostname()}_instrument_calib.json" is not found
            # instrument specific calibration
            M_instr=[[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
            count_to_mm=dict(
                A=1.0 / 6396.11,
                B=1.0 / 6400.24,
            ),
            galil_ip_str="192.168.200.246",
            def_speed_count_sec=10000,
            max_speed_count_sec=25000,
            ipstr="192.168.200.23",
            axis_id=dict(
                x="A",
                y="B",
            ),
            axis_zero=dict(
                A=127,  # X
                B=72.5,  # Y
            ),
            timeout=10 * 60,  # timeout for axis stop in sec
        ),
    ),
    IO=dict(
        host=hostip,
        port=8005,
        group="action",
        fast="galil_io",
        params=dict(
            galil_ip_str="192.168.200.246",
            dev_ai={},
            dev_ao={},
            dev_di={
                "gamry_ttl0": 1,
            },
            dev_do={
                "gamry_aux": 4,
                "doric_wled": 1,
                "wl_source": 1,
                "spec_trig": 2,
                "spec_trig2": 3,
            },
        ),
    ),
    PAL=dict(
        host=hostip,
        port=8007,
        group="action",
        fast="pal_server",
        params=dict(
            positions={
                "custom": {
                    "cell1_we": "cell",
                }
            },
        ),
    ),
    # #########################################################################
    # Visualizers (bokeh servers)
    # #########################################################################
    VIS=dict(
        host=hostip,
        port=5001,
        group="visualizer",
        bokeh="bokeh_modular_visualizer",
        params=dict(
            doc_name="UVIS Visualizer",
        ),
    ),
    #
    # #########################################################################
    # DB package server
    # #########################################################################
    # DB=dict(
    #     host=hostip,
    #     port=8010,
    #     group="action",
    #     fast="dbpack_server",
    #     params=dict(
    #         aws_config_path="k:/users/hte/.credentials/aws_config.ini",
    #         aws_profile="default",
    #         aws_bucket="helao.data.testing",
    #         api_host="caltech-api.modelyst.com",
    #         testing=False,
    #     ),
    # ),
)
