hostip = "127.0.0.1"
config = {}
config['dummy'] = True
config['simulation'] = True

# action library provides generator functions which produce actions
config["experiment_libraries"] = ["simulate_exp"]
config["sequence_libraries"] = []
config["run_type"] = "simulation"
config["root"] = "/mnt/BIGSTOR/INST"  # software log and run files saved here


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
    PAL=dict(
        host=hostip,
        port=8003,
        group="action",
        fast="archive_simulator",
        params=dict(
            data_path="/mnt/k/users/guevarra/20191108_multipH_OER_full.csv"
        ),
    ),
    MOTOR=dict(
        host=hostip,
        port=8004,
        group="action",
        fast="motion_simulator",
        params=dict(
            platemap_path="/mnt/j/hte_jcap_app_proto/map/0069-04-0100-mp.txt",
            count_to_mm=dict(
                A=1.0/6396.87,
                B=1.0/6390.30,
            ),
            def_speed_count_sec=10000,
            max_speed_count_sec=25000,
        ),
    ),
    PSTAT=dict(
        host=hostip,
        port=8005,
        group="action",
        fast="pstat_simulator",
        params=dict(
            data_path="/mnt/k/users/guevarra/20191108_multipH_OER_full.csv"
        ),
    ),
    ANA=dict(
        host=hostip,
        port=8009,
        group="action",
        fast="analysis_simulator",
        params=dict(
            data_path="/mnt/k/users/guevarra/20191108_multipH_OER_full.csv"
        ),
    ),
    # DB=dict(
    #     host=hostip,
    #     port=8010,
    #     group="action",
    #     fast="dbpack_server",
    #     params=dict(
    #         aws_config_path="/mnt/k/users/hte/.credentials/aws_config.ini",
    #         aws_profile="default",
    #         aws_bucket="helao.data.testing",
    #         api_host="caltech-api.modelyst.com",
    #         testing=False
    #     ),
    # ),
)
