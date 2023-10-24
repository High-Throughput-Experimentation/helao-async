import sys
import os
import inspect
import time
from tqdm import tqdm
from dotenv import load_dotenv
from pathlib import Path

from helao.servers.operator.operator import Operator
from helao.helpers.gcld_client import DataRequestsClient
from helao.helpers.premodels import Sequence
from helao.helpers.dispatcher import private_dispatcher
from helao.helpers.config_loader import config_loader
from helao.helpers.gen_uuid import gen_uuid
from helao.sequences.UVIS_T_seq import UVIS_T, UVIS_T_postseq

inst_config = sys.argv[1]
PLATE_ID = int(sys.argv[2])
env_config = sys.argv[3]
load_dotenv(dotenv_path=Path(env_config))


# print({k: v for k, v in os.environ.items() if k in ('API_KEY', 'BASE_URL')})
client = DataRequestsClient(
    base_url=os.environ["BASE_URL"], api_key=os.environ["API_KEY"]
)


def uvis_seq_constructor(plate_id, sample_no, data_request_id, params={}):
    argspec = inspect.getfullargspec(UVIS_T)
    seq_args = list(argspec.args)
    seq_defaults = list(argspec.defaults)
    seq_uuid = gen_uuid()
    seq_params = {k: v for k, v in zip(seq_args, seq_defaults)}
    seq_params.update(params)
    seq_params["plate_id"] = plate_id
    seq_params["plate_sample_no_list"] = [sample_no]
    seq_params.update(
        {
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
            "analysis_seq_uuid": str(seq_uuid),
        }
    )
    experiment_list = UVIS_T(**seq_params)
    seq = Sequence(
        sequence_name="UVIS_T",
        sequence_label="gcld-mvp-demo",
        sequence_params=seq_params,
        sequence_uuid=seq_uuid,
        data_request_id=data_request_id,
        experiment_list=[],
        experiment_plan_list=experiment_list,
        experimentmodel_list=experiment_list,
    )
    seq.sequence_uuid = seq_uuid
    return seq


def uvis_ana_constructor(plate_id, sequence_uuid, data_request_id, params={}):
    argspec = inspect.getfullargspec(UVIS_T_postseq)
    seq_args = list(argspec.args)
    seq_defaults = list(argspec.defaults)
    seq_uuid = gen_uuid()
    seq_params = {k: v for k, v in zip(seq_args, seq_defaults)}
    seq_params.update(params)
    seq_params["plate_id"] = plate_id
    seq_params.update(
        {"analysis_seq_uuid": sequence_uuid, "plate_id": plate_id, "recent": False}
    )
    experiment_list = UVIS_T_postseq(**seq_params)
    seq = Sequence(
        sequence_name="UVIS_T_postseq",
        sequence_label="gcld-mvp-demo-analysis",
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


if __name__ == "__main__":
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

            # MEASUREMENT
            seq = uvis_seq_constructor(PLATE_ID, sample_no, data_request.id)
            operator.add_sequence(seq.get_seq())
            print(f"Dispatching measurement sequence: {seq.sequence_uuid}")
            operator.start()

            # wait for sequence start (orch_state == "busy")
            current_state, active_seq, last_seq = wait_for_orch(operator, "busy")
            if current_state in ["error", "estop"]:
                with client:
                    # TODO: update data request with new status (measurement setup error)
                    output = client.update_data_request()
                # TODO: pause loop here and wait for user input then retry 
            elif active_seq["sequence_uuid"] == seq.sequence_uuid:
                # Acknowledge the data request
                with client:
                    output = client.acknowledge_data_request(data_request.id)
                print(f"Data request status: {output.status}")

            # wait for sequence end (orch_state == "idle")
            current_state, active_seq, last_seq = wait_for_orch(operator, "idle")
            if current_state in ["error", "estop"]:
                with client:
                    # TODO: update data request with new status (measurement insitu error)
                    output = client.update_data_request()
                # TODO: pause loop here and wait for user input then retry 

            time.sleep(30)

            # when orchestrator has stopped, check DB server for upload state
            num_sync_tasks = num_uploads()
            while num_sync_tasks > 0:
                print(f"Waiting for {num_sync_tasks} sequence uploads to finish.")
                time.sleep(10)
                num_sync_tasks = num_uploads()

            # ANALYSIS
            ana = uvis_ana_constructor(
                PLATE_ID, str(seq.sequence_uuid), data_request.id
            )
            operator.add_sequence(ana.get_seq())
            print(f"Dispatching analysis sequence: {ana.sequence_uuid}")
            operator.start()

            # wait for analysis start (orch_state == "busy")
            current_state, active_seq, last_seq = wait_for_orch(operator, "busy")
            if current_state in ["error", "estop"]:
                with client:
                    # TODO: update data request with new status (analysis error)
                    output = client.update_data_request()
                # TODO: pause loop here and wait for user input then retry 
            elif active_seq["sequence_uuid"] == seq.sequence_uuid:
                # Acknowledge the data request
                with client:
                    output = client.acknowledge_data_request(data_request.id)
                print(f"Data request status: {output.status}")

            # wait for analysis end (orch_state == "idle")
            current_state, active_seq, last_seq = wait_for_orch(operator, "idle")
            if current_state in ["error", "estop"]:
                with client:
                    # TODO: update data request with new status (analysis insitu error)
                    output = client.update_data_request()
                # TODO: pause loop here and wait for user input then retry 

        print(
            f"{gen_ts()} Orchestrator is idle. Checking for data requests in 15 seconds."
        )
        time.sleep(15)
