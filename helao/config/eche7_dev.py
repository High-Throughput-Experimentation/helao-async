
__all__ = ["config"]


hostip = "127.0.0.1"
config = dict()

# action library provides generator functions which produce actions
# lists from input experiment_id grouping
config["experiment_libraries"] = ["SDC_exp"]
# config["sequence_libraries"] = []
config["technique_name"] = "sdc"
config["root"] = r"C:\INST_dev2"
# config["local_db_path"] = r"C:\INST_dev2\DATABASE"


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
            enable_op = True,
            bokeh_port = 5002,
        )
        # cmd_print = False
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
            enable_aligner = True,
            bokeh_port = 5003,
            cutoff = 6,
            ref_plateid = 6353, # 63537
            # 4x6 plate
            # x, y, z, 1
            # M_plate are always x, y, 1
            M_instr = [
                       [1,0,0,0],
                       [0,1,0,0],
                       [0,0,1,0],
                       [0,0,0,1]
                       ], # instrument specific calibration
            count_to_mm=dict(
                A=1.0/6396.87,
                B=1.0/6390.30,
            ),
            galil_ip_str="192.168.200.236",
            # galil_ip_str="192.168.200.234",
            def_speed_count_sec=10000,
            max_speed_count_sec=25000,
            ipstr="192.168.200.23",
            axis_id=dict(
                x="B",
                y="A",
                ),
            axis_zero=dict(
                A=76.8, #z
                B=77.1, #y
                ),
            timeout = 10*60, # timeout for axis stop in sec
        )
    ),
    PSTAT=dict(
        host=hostip,
        port=8004,
        group="action",
        fast="gamry_server",
        simulate=False,  # choose between simulator(default) or real device
        # cmd_print=False,
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
        # cmd_print=False,
        params=dict(
            galil_ip_str="192.168.200.236",
            # galil_ip_str="192.168.200.234",
            dev_ai = {
                },
            dev_ao = {
                },
            dev_di = {
                "gamry_ttl0":1,
                },
            dev_do = {
                "gamry_aux":1,
                "led":2,
                "pump_ref_flush":3,
                "doric_led1":4,
                "unknown2":5,
                "doric_led2":6,
                "doric_led3":7,
                "doric_led4":8,
                },
        )
    ),
    PAL=dict(
        host=hostip,
        port=8007,
        group="action",
        fast="pal_server",
        params = dict(
            positions = {
                          "custom":{
                                    "cell1_we":"cell",
                                  }
                        },
        )
    ),
    # #########################################################################
    # Visualizers (bokeh servers)
    # #########################################################################
    VIS=dict(#simple dumb modular visualizer
        host=hostip,
        port=5001,
        group="visualizer",
        bokeh="bokeh_modular_visualizer",
        params = dict(
            doc_name = "ECHE7 Visualizer",
        )
    ),
)
