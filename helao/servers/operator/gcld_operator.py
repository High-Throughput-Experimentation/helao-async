import sys
import os
import inspect
import time
from copy import copy
from tqdm import tqdm
from dotenv import load_dotenv
from pathlib import Path

from helao.servers.operator.operator import Operator

# from helao.helpers.gcld_client import DataRequestsClient
from data_request_client.client import DataRequestsClient
from data_request_client.models import Status
from helao.helpers.premodels import Sequence
from helao.helpers.dispatcher import private_dispatcher
from helao.helpers.config_loader import config_loader
from helao.helpers.gen_uuid import gen_uuid
from helao.sequences.UVIS_T_seq import UVIS_T, UVIS_T_postseq
from helao.sequences.ECHEUVIS_seq import ECHEUVIS_multiCA_led, ECHEUVIS_postseq

inst_config = sys.argv[1]
PLATE_ID = int(sys.argv[2])
env_config = sys.argv[3]
load_dotenv(dotenv_path=Path(env_config))


# print({k: v for k, v in os.environ.items() if k in ('API_KEY', 'BASE_URL')})
client = DataRequestsClient(
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
    "ref_vs_nhe": 0.21,
    "CA_potential_vsRHE": [
        0.4,
        1.0,
        1.6,
        2.2,
    ],
    # "CA_potential_vsRHE": [
    #     -0.2,
    #     0,
    #     0.2,
    #     0.4,
    #     0.6,
    #     0.8,
    #     1.0,
    #     1.2,
    #     1.4,
    #     1.6,
    #     1.8,
    #     2.0,
    #     2.2,
    #     2.4,
    # ],
    # "CA_duration_sec": 85,
    "CA_duration_sec": 15,
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
    "spec_int_time_ms": 25,
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
    "cell_fill_wait": 45.0,
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
    seq_params = {k: v for k, v in zip(seq_args, seq_defaults)}
    seq_params.update(params)
    seq_params["plate_id"] = plate_id
    seq_params["plate_sample_no_list"] = [sample_no]
    seq_params.update({k: v for k, v in param_defaults.items() if k not in seq_params})
    seq_params.update({"analysis_seq_uuid": str(seq_uuid)})
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
    )
    seq.sequence_uuid = seq_uuid
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
    seq_params = {k: v for k, v in zip(seq_args, seq_defaults)}
    seq_params.update(params)
    seq_params["plate_id"] = plate_id
    seq_params.update({k: v for k, v in param_defaults.items() if k not in seq_params})
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
    )
    seq.sequence_uuid = seq_uuid
    return seq


def gen_ts():
    return f"[{time.strftime('%H:%M:%S')}]"


    
def main():
    helao_root = os.path.dirname(os.path.realpath(__file__))
    while "helao.py" not in os.listdir(helao_root):
        helao_root = os.path.dirname(helao_root)
    operator = Operator(inst_config, "ORCH")

    world_cfg = config_loader(inst_config, helao_root)
    db_cfg = world_cfg["servers"]["DB"]

    def num_uploads():
        resp, err = private_dispatcher("DB", db_cfg["host"], db_cfg["port"], "tasks")
        return len(resp.get("running", [])) + resp.get("num_queued", 0)

    def wait_for_orch(op: Operator, orch_state: str = "busy", polling_time=5.0):
        progress = tqdm()
        current_state = op.orch_state()
        if current_state["orch_state"] != orch_state:
            print(
                f"orchestrator status != {orch_state}, waiting {polling_time} per iter:"
            )
        while current_state["orch_state"] != orch_state:
            current_orch = current_state["orch_state"]
            active_seq = current_state["active_sequence"]
            last_seq = current_state["last_sequence"]
            if current_orch in ["error", "estop"]:
                return current_orch, active_seq, last_seq
            progress.update()
            time.sleep(polling_time)
            current_state = op.orch_state()
        return orch_state, active_seq, last_seq

    while True:
        with client:
            pending_requests = client.read_data_requests(status="pending")

        if pending_requests:
            print(f"Pending data request count: {len(pending_requests)}")
            data_request = pending_requests[0]
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
            insitu_params = copy(ECHEUVIS_multiCA_led_defaults)
            insitu_params.update({"CA_potential_vsRHE": potential_list})

            # INSITU MEASUREMENT
            seq = seq_constructor(
                PLATE_ID,
                sample_no,
                data_request.id,
                ECHEUVIS_multiCA_led,
                "ECHEUVIS_multiCA_led",
                "gcld-wetdryrun",
                insitu_params,
            )
            operator.add_sequence(seq.get_seq())
            print(f"Dispatching measurement sequence: {seq.sequence_uuid}")
            operator.start()

            # wait for sequence start (orch_state == "busy")
            current_state, active_seq, last_seq = wait_for_orch(operator, "busy")
            if current_state in ["error", "estop"]:
                with client:
                    output = client.set_status(
                        Status.failed, data_request_id=data_request.id
                    )
                    input("Press Enter to reset failed request to pending and exit operator...")
                    output = client.set_status(
                        Status.pending, data_request_id=data_request.id
                    )
                    return -1
            elif active_seq["sequence_uuid"] == seq.sequence_uuid:
                # Acknowledge the data request
                with client:
                    output = client.acknowledge_data_request(data_request.id)
                print(f"Data request status: {output.status}")

            # wait for sequence end (orch_state == "idle")
            current_state, active_seq, last_seq = wait_for_orch(operator, "idle")
            if current_state in ["error", "estop"]:
                with client:
                    output = client.set_status(
                        Status.failed, data_request_id=data_request.id
                    )
                    input("Press Enter to reset failed request to pending and exit operator...")
                    output = client.set_status(
                        Status.pending, data_request_id=data_request.id
                    )
                    return -1

            time.sleep(30)

            # when orchestrator has stopped, check DB server for upload state
            num_sync_tasks = num_uploads()
            while num_sync_tasks > 0:
                print(f"Waiting for {num_sync_tasks} sequence uploads to finish.")
                time.sleep(10)
                num_sync_tasks = num_uploads()

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
            ana = ana_constructor(
                PLATE_ID,
                str(seq.sequence_uuid),
                data_request.id,
                ECHEUVIS_postseq,
                "ECHEUVIS_postseq",
                "gcld-wetdryrun-analysis",
                ECHEUVIS_postseq_defaults,
            )
            operator.add_sequence(ana.get_seq())
            print(f"Dispatching analysis sequence: {ana.sequence_uuid}")
            operator.start()

            # wait for analysis start (orch_state == "busy")
            current_state, active_seq, last_seq = wait_for_orch(operator, "busy")
            if current_state in ["error", "estop"]:
                with client:
                    output = client.set_status(
                        Status.failed, data_request_id=data_request.id
                    )
                    input("Press Enter to reset failed request to pending and exit operator...")
                    output = client.set_status(
                        Status.pending, data_request_id=data_request.id
                    )
                    return -1
            elif active_seq["sequence_uuid"] == seq.sequence_uuid:
                # Acknowledge the data request
                with client:
                    output = client.acknowledge_data_request(data_request.id)
                print(f"Data request status: {output.status}")

            # wait for analysis end (orch_state == "idle")
            current_state, active_seq, last_seq = wait_for_orch(operator, "idle")
            if current_state in ["error", "estop"]:
                with client:
                    output = client.set_status(
                        Status.failed, data_request_id=data_request.id
                    )
                    input("Press Enter to reset failed request to pending and exit operator...")
                    output = client.set_status(
                        Status.pending, data_request_id=data_request.id
                    )
                    return -1

        print(
            f"{gen_ts()} Orchestrator is idle. Checking for data requests in 15 seconds."
        )
        time.sleep(15)

if __name__ == "__main__":
    main()