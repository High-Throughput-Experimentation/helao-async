hostip = "127.0.0.1"
config = {}
config["dummy"] = True
config['simulation'] = False

# action library provides generator functions which produce actions
config["experiment_libraries"] = ["ANEC_exp", "samples_exp"]
config["experiment_params"] ={
    "gamrychannelwait": -1,
    "gamrychannelsend": 1,
}
config["sequence_libraries"] = ["ANEC_seq"]
config["sequence_params"] = {
    "gamrychannelwait": -1,
    "gamrychannelsend": 1,
}
config["run_type"] = "ANEC"
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
        params=dict(
            enable_aligner=True,
            bokeh_port=5003,
            # backup if f"{gethostname()}_instrument_calib.json" is not found
            # instrument specific calibration
            M_instr=[[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
            count_to_mm=dict(
                A=1.0 / 16282.23,
                B=1.0 / 6397.56,
                C=1.0 / 6358.36,
            ),
            galil_ip_str="192.168.200.218",
            def_speed_count_sec=10000,
            max_speed_count_sec=25000,
            ipstr="192.168.200.23",
            axis_id=dict(
                x="C",
                y="B",
                z="A",
            ),
            axis_zero=dict(
                A=0.0,  # z
                B=52.0,  # y
                C=77.0,  # x
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
            dev_id=0,  # (default 0) Gamry device number in Gamry Instrument Manager (i-1)
            filterfreq_hz=1000.0,
            grounded=True,
        ),
    ),
    IO=dict(
        host=hostip,
        port=8005,
        group="action",
        fast="galil_io",
        params=dict(
            galil_ip_str="192.168.200.218",
            dev_ai={},
            dev_ao={},
            dev_di={
                "multichannel_valve_done": 1,
                "multichannel_valve_error":2,
            },
            dev_do={
                "gamry_aux": 1,
                "Thorlab_led": 7,
            },
        ),
    ),
    NI=dict(
        host="127.0.0.1",
        port=8006,
        group="action",
        fast="nidaqmx_server",
        params=dict(
            dev_liquidvalve={
                "1A": "cDAQ1Mod1/port0/line0",
                "1B": "cDAQ1Mod1/port0/line1",
                "2": "cDAQ1Mod1/port0/line2",
                "3A": "cDAQ1Mod1/port0/line3",
                "4A": "cDAQ1Mod1/port0/line4",
                "5A-cell": "cDAQ1Mod1/port0/line5",
                "5B-waste": "cDAQ1Mod1/port0/line6",
                "6A-waste": "cDAQ1Mod1/port0/line7",
                "6B": "cDAQ1Mod1/port0/line8",
                "blank": "cDAQ1Mod1/port0/line9",
                "multi_CMD0": "cDAQ1Mod1/port0/line28",
                "multi_CMD1": "cDAQ1Mod1/port0/line29",
                "multi_CMD2": "cDAQ1Mod1/port0/line30",
                "multi_CMD3": "cDAQ1Mod1/port0/line31",
            },
            dev_triggers={
                "pump1": "cDAQ1Mod1/port0/line16",
                "pump2": "cDAQ1Mod1/port0/line17",
                "pump3": "cDAQ1Mod1/port0/line18",
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
                },
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
        bokeh="action_visualizer",
        params=dict(
            doc_name="CCSI Visualizer",
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
