__all__ = ["config"]


hostip = "127.0.0.1"
config = {}
config["dummy"] = True
config['simulation'] = False

config["experiment_libraries"] = ["samples_exp", "UVIS_exp"]
config["sequence_libraries"] = ["UVIS_seq"]
config["sequence_params"] = {
    "led_wavelengths_nm": [-1],
    "led_intensities_mw": [-1],
    "led_names": ["doric_wled"],
    "led_type": "front",
    "led_date": "n/a"
}
# config["experiment_libraries"] = ["ECHE_exp", "samples_exp"]
# config["experiment_params"] = {}
# config["sequence_libraries"] = ["ECHE_seq"]
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
                A=1.0 / 6396.11,
                B=1.0 / 6400.24,
            ),
            galil_ip_str="192.168.200.235",
            def_speed_count_sec=10000,
            max_speed_count_sec=25000,
            ipstr="192.168.200.23",
            axis_id=dict(
                x="B",
                y="A",
            ),
            axis_zero=dict(
                A=127.8,  # z
                B=76.7,  # y
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
            galil_ip_str="192.168.200.235",
            dev_ai={},
            dev_ao={},
            dev_di={
                "gamry_ttl0": 1,
            },
            dev_do={
                "gamry_aux": 1,
                "spec_trig": 1,
                "led": 8,
                "pump_ref_flush": 3,
                "pump_supply": 2,
                "doric_led1": 4,
                "doric_wled": 5,
                "doric_led2": 5,
                "doric_led3": 6,
                "doric_led4": 7,
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
    SPEC_T=dict(
        host=hostip,
        port=8011,
        group="action",
        fast="spec_server",
        params=dict(
            dev_num=0,
            lib_path=r"C:\Spectral Products\SM32ProForUSB\SDK Examples\DLL\x64\stdcall\SPdbUSBm.dll",
            n_pixels=1024,
            start_margin=5,
            # wl_cal=[2537, 3132, 3650, 4047, 4358, 5461, 6965, 7635, 8115, 9123],
            # px_cal=[173,  239,  299,  342,  376,  494,  652,  721,  769,  871],
            ## px_cal=[269, 386, 488, 564, 624, 831, 1108, 1228, 1314, 1493],
            # id_vendor = 0x0547,
            # id_product = 0x0322,
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
            doc_name="ECHE4 Visualizer",
        ),
    ),
    #########################################################################
    # DB package server
    #########################################################################
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
