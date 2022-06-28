__all__ = ["config"]


hostip = "127.0.0.1"
config = {}
config["dummy"] = False
config['simulation'] = False

# action library provides generator functions which produce actions
# lists from input experiment_id grouping
config["experiment_libraries"] = ["ECHE_exp", "samples_exp"]
config["sequence_libraries"] = ["ECHE_seq"]
config["sequence_params"] = {
    "led_wavelengths_nm": [385, 450, 515, 595],
    "led_intensities_mw": [3.77, 2.77, 1.13, 1.0],
    "led_names": ["doric_led1", "doric_led2", "doric_led3", "doric_led4"],
    "led_type": "front",
    "led_date": "6/24/2020"
    #           backside 2.27, 1.91, .76, .667   6/29/2021
}
config["run_type"] = "eche"
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
                A=1.0 / 6395.30,
                B=1.0 / 6400.56,
            ),
            galil_ip_str="192.168.200.225",
            def_speed_count_sec=10000,
            max_speed_count_sec=25000,
            ipstr="192.168.200.23",
            axis_id=dict(
                x="B",
                y="A",
            ),
            axis_zero=dict(
                A=127.7,  # z
                B=76.9,  # y
            ),
            timeout=10 * 60,  # timeout for axis stop in sec
        ),
    ),
    PSTAT=dict(
        host=hostip,
        port=8004,
        group="action",
        fast="gamry_server",
        params=dict(
            allow_no_sample=True,
            dev_id=0,  # (default 0) Gamry device number in Gamry Instrument Manager (i-1)
        ),
    ),
    IO=dict(
        host=hostip,
        port=8005,
        group="action",
        fast="galil_io",
        params=dict(
            galil_ip_str="192.168.200.225",
            dev_ai={},
            dev_ao={},
            dev_di={
                "gamry_ttl0": 1,
            },
            dev_do={
                "gamry_aux": 1,
                "led": 2,
                "pump_ref_flush": 3,
                "doric_led1": 4,
                # "unknown2":5,
                "doric_led2": 5,
                "doric_led3": 7,
                "doric_led4": 8,
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
            doc_name="ECHE5 Visualizer",
        ),
    ),
    # #########################################################################
    # DB package server
    # #########################################################################
    DB=dict(
        host=hostip,
        port=8010,
        group="action",
        fast="dbpack_server",
        params=dict(
            aws_config_path="k:/users/hte/.credentials/aws_config.ini",
            aws_profile="default",
            aws_bucket="helao.data",
            api_host="caltech-api.modelyst.com",
            testing=False,
        ),
    ),
)
