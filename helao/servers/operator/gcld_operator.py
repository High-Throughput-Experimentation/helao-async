import sys
import os
import inspect
import time
from copy import copy
from tqdm import tqdm
from dotenv import load_dotenv
from pathlib import Path
from pprint import pprint

from helao.servers.operator.helao_operator import HelaoOperator

# from helao.helpers.gcld_client import DataRequestsClient
from data_request_client.client import DataRequestsClient, CreateDataRequestModel
from data_request_client.models import Status
from helao.helpers.premodels import Sequence
from helao.helpers.dispatcher import private_dispatcher
from helao.helpers.config_loader import config_loader
from helao.helpers.gen_uuid import gen_uuid
from helao.sequences.UVIS_T_seq import UVIS_T, UVIS_T_postseq
from helao.sequences.ECHEUVIS_seq import ECHEUVIS_multiCA_led, ECHEUVIS_postseq
from helaocore.models.orchstatus import LoopStatus

TEST = True

# TEST_SMPS_2286 = [
#     {
#         "sample_no": 14060,
#         "composition": {"Fe": 0.516317, "Sb": 0.483683},
#         "parameters": {"z_start": 1.0, "z_direction": "up"},
#     },
#     {
#         "sample_no": 10695,
#         "composition": {"Fe": 0.301409, "Sb": 0.698591},
#         "parameters": {"z_start": 0.2, "z_direction": "down"},
#     },
#     {
#         "sample_no": 3175,
#         "composition": {"Fe": 0.756378, "Sb": 0.243622},
#         "parameters": {"z_start": 0.6, "z_direction": "down"},
#     },
#     {
#         "sample_no": 9030,
#         "composition": {"Fe": 0.298030, "Sb": 0.701970},
#         "parameters": {"z_start": 2.0, "z_direction": "up"},
#     },
#     {
#         "sample_no": 18984,
#         "composition": {"Fe": 0.217839, "Sb": 0.782161},
#         "parameters": {"z_start": 1.4, "z_direction": "down"},
#     },
# ]

# print({k: v for k, v in os.environ.items() if k in ('API_KEY', 'BASE_URL')})

TEST_SMPS_2286 = [
    {
        "sample_no": 14060,
        "composition": {"Fe": 0.516317, "Sb": 0.483683},
        "parameters": {"z_start": 1.0, "z_direction": "up"},
    },
    {
        "sample_no": 10695,
        "composition": {"Fe": 0.301409, "Sb": 0.698591},
        "parameters": {"z_start": 0.2, "z_direction": "down"},
    },
    {
        "sample_no": 3175,
        "composition": {"Fe": 0.756378, "Sb": 0.243622},
        "parameters": {"z_start": 0.6, "z_direction": "down"},
    },
    {
        "sample_no": 9030,
        "composition": {"Fe": 0.298030, "Sb": 0.701970},
        "parameters": {"z_start": 2.0, "z_direction": "up"},
    },
    {
        "sample_no": 18984,
        "composition": {"Fe": 0.217839, "Sb": 0.782161},
        "parameters": {"z_start": 1.4, "z_direction": "down"},
    },
]

MEASURED_6083 = [766, 802, 1872, 3096, 3113, 3131, 4479, 4550, 7571, 7633, 9012, 9056, 9065, 9083, 9109, 10739, 12439, 13989, 13989, 14069, 14087, 14122, 15654, 15760, 17319, 17319, 17346, 17461, 19028, 19117, 20461, 22035, 22044, 22079, 23579, 23606, 23641, 24980, 26230, 26283, 27300, 27362,]

TEST_SMPS_6083 = [{"sample_no": s, "composition": {"Mn": 0.5, "Sb": 0.5}, "parameters": {"z_start": 1.2, "z_direction": "up"}} for s in MEASURED_6083]


UVIS_T_defaults = {
    "reference_mode": "builtin",
    "custom_position": "cell1_we",
    "spec_n_avg": 5,
    "spec_int_time_ms": 10,
    "duration_sec": 5,
    "specref_code": 1,
    "led_type": "front",
    "led_date": "4/28/2023",
    "led_names": ["doric_wled"],
    "led_wavelengths_nm": [-1],
    "led_intensities_mw": [-1],
    "toggle_is_shutter": False,
}
UVIS_T_postseq_defaults = {"recent": False}

ECHEUVIS_multiCA_led_defaults = {
    "reservoir_electrolyte": "OER10",
    "reservoir_liquid_sample_no": 198,
    "solution_bubble_gas": "O2",
    "solution_ph": 10,
    "measurement_area": 0.071,  # 3mm diameter droplet
    "liquid_volume_ml": 1.0,
    "ref_vs_nhe": 0.21 + 0.082,
    # "CA_potential_vsRHE": [
    #     0.4,
    #     1.0,
    #     1.6,
    #     2.2,
    # ],
    "CA_duration_sec": 85,
    "CA_potential_vsRHE": [
        -0.2,
        0,
        0.2,
        0.4,
        0.6,
        0.8,
        1.0,
        1.2,
        1.4,
        1.6,
        1.8,
        2.0,
        2.2,
        2.4,
    ],
    "CA_samplerate_sec": 0.05,
    "OCV_duration_sec": 5,
    "gamry_i_range": "auto",
    "led_type": "front",
    "led_date": "04/28/2023",
    "led_names": ["doric_wled"],
    "led_wavelengths_nm": [-1],
    "led_intensities_mw": [-1],
    "led_name_CA": "doric_wled",
    "toggleCA_illum_duty": 1.0,
    "toggleCA_illum_period": 1.0,
    "toggleCA_dark_time_init": 0,
    "toggleCA_illum_time": -1,
    "toggleSpec_duty": 0.5,
    "toggleSpec_period": 0.25,
    "toggleSpec_init_delay": 0.0,
    "toggleSpec_time": -1,
    "spec_ref_duration": 5,
    "spec_int_time_ms": 50,
    "spec_n_avg": 5,
    "spec_technique": "T_UVVIS",
    "calc_ev_parts": [1.8, 2.2, 2.6, 3.0],
    "calc_bin_width": 3,
    "calc_window_length": 45,
    "calc_poly_order": 4,
    "calc_lower_wl": 370.0,
    "calc_upper_wl": 700.0,
    "calc_skip_nspec": 4,
    "random_start_potential": False,
    "use_z_motor": True,
    "cell_engaged_z": 1.5,
    "cell_disengaged_z": 0,
    "cell_vent_wait": 10.0,
    "cell_fill_wait": 35.0,
}

ECHEUVIS_postseq_defaults = {"recent": False}


def seq_constructor(
    plate_id,
    sample_no,
    data_request_id,
    params={},
    seq_func=UVIS_T,
    seq_name="UVIS_T",
    seq_label="gcld-mvp-demo",
    param_defaults={},
):
    argspec = inspect.getfullargspec(seq_func)
    seq_args = list(argspec.args)
    seq_defaults = list(argspec.defaults)
    seq_uuid = gen_uuid()
    seq_params = copy(param_defaults)
    seq_params.update(params)
    seq_params["plate_id"] = plate_id
    seq_params["plate_sample_no_list"] = [sample_no]
    seq_params.update(
        {k: v for k, v in zip(seq_args, seq_defaults) if k not in seq_params}
    )
    experiment_list = seq_func(**seq_params)
    seq = Sequence(
        sequence_name=seq_name,
        sequence_label=seq_label,
        sequence_params=seq_params,
        sequence_uuid=seq_uuid,
        data_request_id=data_request_id,
        experiment_list=[],
        experiment_plan_list=experiment_list,
        experimentmodel_list=[],
        dummy=TEST,
    )
    return seq


def ana_constructor(
    plate_id,
    sequence_uuid,
    data_request_id,
    params={},
    seq_func=UVIS_T_postseq,
    seq_name="UVIS_T_postseq",
    seq_label="gcld-mvp-demo-analysis",
    param_defaults={},
):
    argspec = inspect.getfullargspec(seq_func)
    seq_args = list(argspec.args)
    seq_defaults = list(argspec.defaults)
    seq_uuid = gen_uuid()
    seq_params = copy(param_defaults)
    seq_params.update(params)
    seq_params["plate_id"] = plate_id
    seq_params.update(
        {k: v for k, v in zip(seq_args, seq_defaults) if k not in seq_params}
    )
    seq_params.update({"analysis_seq_uuid": sequence_uuid})
    experiment_list = seq_func(**seq_params)
    seq = Sequence(
        sequence_name=seq_name,
        sequence_label=seq_label,
        sequence_params=seq_params,
        sequence_uuid=seq_uuid,
        data_request_id=data_request_id,
        experiment_list=[],
        experiment_plan_list=experiment_list,
        experimentmodel_list=experiment_list,
        dummy=TEST,
    )
    return seq


def gen_ts():
    return f"[{time.strftime('%H:%M:%S')}]"


def wait_for_orch(
    op: HelaoOperator, loop_state: LoopStatus = LoopStatus.started, polling_time=5.0
):
    current_state = op.orch_state()
    current_loop = current_state["loop_state"]
    active_seq = current_state["active_sequence"]
    last_seq = current_state["last_sequence"]
    if current_loop != loop_state:
        print(f"orchestrator status != {loop_state}, waiting {polling_time} per iter:")
        progress = tqdm()
        while current_loop != loop_state:
            if current_loop in [LoopStatus.error, LoopStatus.estopped]:
                return current_loop, active_seq, last_seq
            progress.update()
            time.sleep(polling_time)
            current_state = op.orch_state()
            current_loop = current_state["loop_state"]
            active_seq = current_state["active_sequence"]
            last_seq = current_state["last_sequence"]
    return current_loop, active_seq, last_seq


def num_uploads(db_cfg):
    resp, err = private_dispatcher("DB", db_cfg["host"], db_cfg["port"], "tasks")
    return len(resp.get("running", [])) + resp.get("num_queued", 0)


def main():

    inst_config = sys.argv[1]
    PLATE_ID = int(sys.argv[2])
    env_config = sys.argv[3]
    RESUME_ID = False
    if len(sys.argv) == 5:
        RESUME_ID = sys.argv[4]
    load_dotenv(dotenv_path=Path(env_config))
    
    CLIENT = DataRequestsClient(
        base_url=os.environ["BASE_URL"], api_key=os.environ["API_KEY"]
    )

    helao_root = os.path.dirname(os.path.realpath(__file__))
    while "helao.py" not in os.listdir(helao_root):
        helao_root = os.path.dirname(helao_root)
    operator = HelaoOperator(inst_config, "ORCH")

    world_cfg = config_loader(inst_config, helao_root)
    db_cfg = world_cfg["servers"]["DB"]
    test_idx = 0
    resumed = False

    while True:
        data_request = False

        with CLIENT:
            pending_requests = CLIENT.read_data_requests(status="pending")
            acknowledged_requests = CLIENT.read_data_requests(status="acknowledged")

        if RESUME_ID and not resumed:
            matching_requests = [req for req in acknowledged_requests if str(req.id) == RESUME_ID]
            if matching_requests:
                data_request = matching_requests[0]
                resumed = True
        
        elif pending_requests or TEST:
            if TEST:
                smpd = TEST_SMPS_6083[test_idx]
                test_req = CreateDataRequestModel(
                    composition=smpd["composition"],
                    score=1.0,
                    parameters=smpd["parameters"],
                    sample_label=f"legacy__solid__6083_{smpd['sample_no']}",
                )
                with CLIENT:
                    data_request = CLIENT.create_data_request(test_req)
                test_idx += 1
            elif pending_requests:
                print(f"{gen_ts()} Pending data request count: {len(pending_requests)}")
                data_request = pending_requests[0]
            elif acknowledged_requests:
                print(f"{gen_ts()} Restarting acknowledged data request from beginning")
                data_request = acknowledged_requests[0]

            sample_no = int(data_request.sample_label.split("_")[-1])

            # # DRY MEASUREMENT
            # seq = seq_constructor(
            #     PLATE_ID,
            #     sample_no,
            #     data_request.id,
            #     UVIS_T,
            #     "UVIS_T",
            #     "gcld-mvp-demo",
            #     UVIS_T_defaults,
            # )

            # INSITU params
            z_start = data_request.parameters["z_start"]
            scan_down = (
                True if data_request.parameters["z_direction"] == "down" else False
            )
            ordered_vs = sorted(
                ECHEUVIS_multiCA_led_defaults["CA_potential_vsRHE"], reverse=scan_down
            )
            init_direction = ordered_vs[ordered_vs.index(z_start) :]
            rev_direction = ordered_vs[: ordered_vs.index(z_start)][::-1]
            potential_list = init_direction + rev_direction
            insitu_params = {"CA_potential_vsRHE": potential_list}

            # INSITU MEASUREMENT
            insitu_seq = seq_constructor(
                plate_id=PLATE_ID,
                sample_no=sample_no,
                data_request_id=data_request.id,
                params=insitu_params,
                seq_func=ECHEUVIS_multiCA_led,
                seq_name="ECHEUVIS_multiCA_led",
                seq_label="gcld-wetdryrun",
                param_defaults=ECHEUVIS_multiCA_led_defaults,
            )
            print(
                f"{gen_ts()} Got measurement request {data_request.id}"
            )
            print(
                f"{gen_ts()} Plate {PLATE_ID} sample {sample_no} has composition:"
            )
            pprint(data_request.composition)
            print(
                f"{gen_ts()} Measurement parameters for sequence: {insitu_seq.sequence_uuid}:"
            )
            pprint(data_request.parameters)
            operator.add_sequence(insitu_seq.get_seq())
            print(f"{gen_ts()} Dispatching measurement sequence: {insitu_seq.sequence_uuid}")
            operator.start()
            time.sleep(5)

            # wait for sequence start (orch_state == "busy")
            current_state, active_insitu_seq, last_seq = wait_for_orch(
                operator, LoopStatus.started
            )
            print(
                f"{gen_ts()} Measurement sequence {active_insitu_seq['sequence_uuid']} has started."
            )
            if current_state in [LoopStatus.error, LoopStatus.estopped]:
                with CLIENT:
                    output = CLIENT.set_status(
                        "failed", data_request_id=data_request.id
                    )
                    input(
                        "Press Enter to reset failed request to pending and exit operator..."
                    )
                    output = CLIENT.set_status(
                        "pending", data_request_id=data_request.id
                    )
                    return -1
            elif str(active_insitu_seq["sequence_uuid"]) == str(insitu_seq.sequence_uuid):
                # Acknowledge the data request
                with CLIENT:
                    output = CLIENT.acknowledge_data_request(data_request.id)
                print(f"{gen_ts()} Data request {data_request.id} status: {output.status}")

        if data_request:
            # wait for sequence end (orch_state == "idle")
            current_state, _, _ = wait_for_orch(
                operator, LoopStatus.stopped
            )
            if current_state in [LoopStatus.error, LoopStatus.estopped]:
                with CLIENT:
                    output = CLIENT.set_status(
                        "failed", data_request_id=data_request.id
                    )
                    input(
                        "Press Enter to reset failed request to pending and exit operator..."
                    )
                    output = CLIENT.set_status(
                        "pending", data_request_id=data_request.id
                    )
                    return -1

            # with CLIENT:
            #     output = CLIENT.set_status(
            #         "process_finished", data_request_id=data_request.id
            #     )
            #     print(f"{gen_ts()} Data request {data_request.id} status: {output.status}")

            print(
                f"{gen_ts()} Unconditional 30 second wait for upload tasks to process."
            )
            time.sleep(30)

            # when orchestrator has stopped, check DB server for upload state
            num_sync_tasks = num_uploads(db_cfg)
            while num_sync_tasks > 0:
                print(
                    f"{gen_ts()} Waiting for {num_sync_tasks} sequence uploads to finish."
                )
                time.sleep(10)
                num_sync_tasks = num_uploads(db_cfg)

            # # DRY ANALYSIS
            # ana = ana_constructor(
            #     PLATE_ID,
            #     str(seq.sequence_uuid),
            #     data_request.id,
            #     UVIS_T_postseq,
            #     "UVIS_T_postseq",
            #     "gcld-mvp-demo-analysis",
            #     UVIS_T_postseq_defaults,
            # )

            # INSITU ANALYSIS
            ana_seq = ana_constructor(
                plate_id=PLATE_ID,
                sequence_uuid=str(active_insitu_seq["sequence_uuid"]),
                data_request_id=data_request.id,
                params={},
                seq_func=ECHEUVIS_postseq,
                seq_name="ECHEUVIS_postseq",
                seq_label="gcld-wetdryrun-analysis",
                param_defaults=ECHEUVIS_postseq_defaults,
            )
            operator.add_sequence(ana_seq.get_seq())
            print(f"{gen_ts()} Dispatching analysis sequence: {ana_seq.sequence_uuid}")
            operator.start()

            time.sleep(5)

            # wait for analysis start (orch_state == "busy")
            current_state, active_seq, last_seq = wait_for_orch(
                operator, LoopStatus.started
            )
            print(
                f"{gen_ts()} Analysis sequence {active_seq['sequence_uuid']} has started."
            )
            if current_state in [LoopStatus.error, LoopStatus.estopped]:
                with CLIENT:
                    output = CLIENT.set_status(
                        "failed", data_request_id=data_request.id
                    )
                    input(
                        "Press Enter to reset failed request to pending and exit operator..."
                    )
                    output = CLIENT.set_status(
                        "pending", data_request_id=data_request.id
                    )
                    return -1

            # wait for analysis end (orch_state == "idle")
            current_state, active_ana_seq, last_seq = wait_for_orch(
                operator, LoopStatus.stopped
            )
            if current_state in [LoopStatus.error, LoopStatus.estopped]:
                with CLIENT:
                    output = CLIENT.set_status(
                        "failed", data_request_id=data_request.id
                    )
                    input(
                        "Press Enter to reset failed request to pending and exit operator..."
                    )
                    output = CLIENT.set_status(
                        "pending", data_request_id=data_request.id
                    )
                    return -1
            print(f"{gen_ts()} Analysis sequence complete.")

            # with CLIENT:
            #     output = CLIENT.set_status(
            #         "analysis_finished", data_request_id=data_request.id
            #     )
            #     print(f"{gen_ts()} Data request {data_request.id} status: {output.status}")

        else:
            print(
                f"{gen_ts()} Orchestrator is idle. Checking for data requests in 10 seconds."
            )
            time.sleep(10)
        if TEST & test_idx == len(TEST_SMPS_6083) - 1:
            return 0
        print("\n")


if __name__ == "__main__":
    main()
