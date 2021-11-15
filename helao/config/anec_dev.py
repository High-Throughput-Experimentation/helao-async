hostip = "127.0.0.1"
config = dict()

# process library provides generator functions which produce processes
# lists from input sequence_id grouping
config["process_libraries"] = ["ANEC"]
config["technique_name"] = "anec"
config["save_root"] = r"C:\INST_dev2\RUNS"
config["local_db_path"] = r"C:\INST_dev2\DATABASE"


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
    ),
    ##########################################################################
    # Instrument Servers
    ##########################################################################
    # DATA=dict(
    #     host=hostip,
    #     port=8002,
    #     group="process",
    #     fast="HTEdata_server",
    #     mode="legacy",  # lagcy; modelyst
    #     params=dict(
    #     ),
    # ),
    MOTOR=dict(
        host=hostip,
        port=8003,
        group="process",
        fast="galil_motion",
        params=dict(
            Transfermatrix = [[1,0,0],[0,1,0],[0,0,1]], # default Transfermatrix for plate calibration
            
            # 4x6 plate, FIXME
            #M_instr = [[1,0,0,-76.525],[0,1,0,-50.875],[0,0,1,0],[0,0,0,1]], # instrument specific calibration
            # 100mm wafer, FIXME
            M_instr = [[1,0,0,-76.525+(3*25.4-50)-0.5+0.75+1.5+0.25],[0,1,0,-50.875+2.71+5-3+1],[0,0,1,0],[0,0,0,1]], # instrument specific calibration

            count_to_mm=dict(
                A=1.0/16282.23,
                B=1.0/6397.56,
                C=1.0/6358.36,
            ),
            galil_ip_str="192.168.99.222",
            def_speed_count_sec=10000,
            max_speed_count_sec=25000,
            ipstr="192.168.200.23",
            axis_id=dict(
                x="C",
                y="B",
                z="A",
                ),
            axis_zero=dict(
                A=0.0, #z
                B=52.0, #y
                C=77.0, #x
                ),
            timeout = 10*60, # timeout for axis stop in sec
        )
    ),
    PSTAT=dict(
        host=hostip,
        port=8004,
        group="process",
        fast="gamry_server",
        simulate=False,  # choose between simulator(default) or real device
        params=dict(
            dev_id=0,  # (default 0) Gamry device number in Gamry Instrument Manager (i-1)
        ),
    ),
    # aligner=dict(
    #     host=hostip,
    #     port=8005,
    #     group="process",
    #     fast="alignment_server",
    #     params=dict(
    #         data_server="data",  # will use this to get PM_map temporaily, else need to parse it as JSON later
    #         motor_server="motor",  # will use this to get PM_map temporaily, else need to parse it as JSON later
    #         vis_server="aligner_vis",  # will use this to get PM_map temporaily, else need to parse it as JSON later
    #         cutoff=6,  # cutoff of digits for TransferMatrix calculation
    #     ),
    # ),
    NI=dict(
        host="127.0.0.1",
        port=8006,
        group="process",
        fast="nidaqmx_server",
        params = dict(
            dev_pump = {
                'PeriPump1':'cDAQ1Mod1/port0/line9',
                'PeriPump2':'cDAQ1Mod1/port0/line7',
                'Direction':'cDAQ1Mod1/port0/line8',
                },

            dev_gasvalve = {
                "CO2":"cDAQ1Mod1/port0/line0",
                "Ar":"cDAQ1Mod1/port0/line2",
                "atm":"cDAQ1Mod1/port0/line5",
                },
            dev_liquidvalve = {
                "liquid":"cDAQ1Mod1/port0/line1",
                "up":"cDAQ1Mod1/port0/line4",
                "down":"cDAQ1Mod1/port0/line3",
                },
            dev_led = {
                "led":"cDAQ1Mod1/port0/line11",
                }
        )
    ),
    PAL=dict(
        host=hostip,
        port=8007,
        group="process",
        fast="pal_server",
        params = dict(
            #user = 'RSHS',
            #key = r'c:\helao\sshkeys\rshs_private3.ppk', # needs to be in new openssh file format
            host = "localhost",
            method_path = r'C:\Users\rshs\Desktop\ADSS\adss_psc_methods\lcfc',
            log_file = r'C:\Users\rshs\Desktop\ADSS\adss_logfile\210512_lcfc_manualwatertest\210512_LCFC_manualwatertest_logfile.txt',
            timeout = 30*60, # 30min timeout for waiting for TTL
            dev_NImax = { # TTL handshake via NImax
                'start':'cDAQ1Mod2/port2/line5', #TTL1
                'continue':'cDAQ1Mod2/port2/line7',  #TTL2
                'done':'cDAQ1Mod2/port2/line3',  #TTL3
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
            doc_name = "ANEC Visualizer",
            # ws_nidaqmx="NI",
            ws_potentiostat = 'PSTAT',
        )
    ),
    OP=dict(
        host=hostip,
        port=5002,
        group="operator",
        bokeh="async_operator",
        params = dict(
            doc_name = "ANEC Operator",
            orch = 'ORCH',
            # data_server = "data",
            # servicemode=False,
        )
    ),
    # aligner_vis=dict(
    #     host=hostip,
    #     port=5003,
    #     group="process",
    #     bokeh="bokeh_platealigner",
    #     params=dict(
    #         aligner_server="aligner",  # aligner and aligner_vis should be in tandem
    #     ),
    # ),
)
