import sys
import os
import inspect
import time
from copy import copy
from tqdm import tqdm
from dotenv import load_dotenv
from pathlib import Path

from helao.servers.operator.helao_operator import HelaoOperator

# from helao.helpers.gcld_client import DataRequestsClient
from data_request_client.client import DataRequestsClient
from helao.helpers.premodels import Sequence
from helao.helpers.dispatcher import private_dispatcher
from helao.helpers.config_loader import CONFIG
from helao.helpers.gen_uuid import gen_uuid
from helao.sequences.UVIS_T_seq import UVIS_T, UVIS_T_postseq
from helao.sequences.ECHEUVIS_seq import ECHEUVIS_postseq
from helao.core.models.orchstatus import LoopStatus

inst_config = sys.argv[1]
PLATE_ID = 6083
env_config = sys.argv[2]
RESUME_ID = "76196ebd-00b6-4e3c-aa01-0a0e0326f6c2"
SEQUENCE_ID = "7549bd61-897f-409e-9977-c9f727e61121"
    
load_dotenv(dotenv_path=Path(env_config))

TEST = False
# print({k: v for k, v in os.environ.items() if k in ('API_KEY', 'BASE_URL')})
CLIENT = DataRequestsClient(
    base_url=os.environ["BASE_URL"], api_key=os.environ["API_KEY"]
)

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
    "ref_vs_nhe": 0.21 + 0.088,
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
    unpacked_experiments = seq_func(**seq_params)
    seq = Sequence(
        sequence_name=seq_name,
        sequence_label=seq_label,
        sequence_params=seq_params,
        sequence_uuid=seq_uuid,
        data_request_id=data_request_id,
        planned_experiments=unpacked_experiments,
        dispatched_experiments=[],
        dispatched_experiments_abbr=[],
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
    unpacked_experiments = seq_func(**seq_params)
    seq = Sequence(
        sequence_name=seq_name,
        sequence_label=seq_label,
        sequence_params=seq_params,
        sequence_uuid=seq_uuid,
        data_request_id=data_request_id,
        planned_experiments=unpacked_experiments,
        dispatched_experiments=[],
        dispatched_experiments_abbr=[],
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
    helao_repo_root = os.path.dirname(os.path.realpath(__file__))
    while "helao.py" not in os.listdir(helao_repo_root):
        helao_repo_root = os.path.dirname(helao_repo_root)
    operator = HelaoOperator(inst_config, "ORCH")

    world_cfg = read_config(inst_config, helao_repo_root)
    db_cfg = world_cfg["servers"]["DB"]
    test_idx = 0
    resumed = False

    with CLIENT:
        pending_requests = CLIENT.read_data_requests(status="pending")
        acknowledged_requests = CLIENT.read_data_requests(status="acknowledged")

    if RESUME_ID and not resumed:
        matching_requests = [req for req in pending_requests + acknowledged_requests if str(req.id) == RESUME_ID]
        if matching_requests:
            data_request = matching_requests[0]
            resumed = True

        ana_seq = ana_constructor(
            plate_id=PLATE_ID,
            sequence_uuid=str(SEQUENCE_ID),
            data_request_id=str(RESUME_ID),
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



if __name__ == "__main__":
    main()
