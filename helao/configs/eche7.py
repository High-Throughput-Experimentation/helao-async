__all__ = ["config"]


hostip = "127.0.0.1"
config = {}
config["dummy"] = False
config['simulation'] = False

# action library provides generator functions which produce actions
# lists from input experiment_id grouping
config["experiment_libraries"] = ["ECHE_exp", "samples_exp"]
config["experiment_params"] = { 
    "gamrychannelwait": -1,
    "gamrychannelsend": 0,
}
config["sequence_libraries"] = ["ECHE_seq"]
config["sequence_params"] = {
    "led_wavelengths_nm": [385, 450, 515, 595],
    "led_intensities_mw": [1.04, 0.86, 0.344, 0.267],
    "led_names": ["doric_led1", "doric_led2", "doric_led3", "doric_led4"],
    "led_type": "front",
    "led_date": "3/13/2019",
    "gamrychannelwait": -1,
    "gamrychannelsend": 0,
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
                A=1.0 / 6396.87,
                B=1.0 / 6390.30,
            ),
            galil_ip_str="192.168.200.236",
            def_speed_count_sec=10000,
            max_speed_count_sec=25000,
            ipstr="192.168.200.23",
            axis_id=dict(
                x="B",
                y="A",
            ),
            axis_zero=dict(
                A=76.8,  # z
                B=77.1,  # y
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
            # allow_no_sample = True,
            dev_id=0,  # (default 0) Gamry device number in Gamry Instrument Manager (i-1)
        ),
    ),
    IO=dict(
        host=hostip,
        port=8005,
        group="action",
        fast="galil_io",
        params=dict(
            galil_ip_str="192.168.200.236",
            dev_ai={},
            dev_ao={},
            dev_di={
                "gamry_ttl0": 1,
            },
            dev_do={
                "gamry_aux": 1,
                "spec_trig": 1,
                "led": 2,
                "pump_ref_flush": 3,
                "doric_led1": 4,
                "unknown2": 5,
                "doric_led2": 6,
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
            doc_name="ECHE7 Visualizer",
        ),
    ),
    #
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
