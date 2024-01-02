import sys
import os
import inspect
import time
from tqdm import tqdm
from dotenv import load_dotenv
from pathlib import Path

from helao.servers.operator.helao_operator import HelaoOperator

# from helao.helpers.gcld_client import DataRequestsClient
from data_request_client.client import DataRequestsClient
from data_request_client.models import Status
from helao.helpers.premodels import Sequence
from helao.helpers.dispatcher import private_dispatcher
from helao.helpers.config_loader import config_loader
from helao.helpers.gen_uuid import gen_uuid
from helao.sequences.TEST_seq import TEST_consecutive_noblocking
from helaocore.models.orchstatus import OrchStatus

inst_config = sys.argv[1]
PLATE_ID = int(sys.argv[2])
env_config = sys.argv[3]
load_dotenv(dotenv_path=Path(env_config))


# print({k: v for k, v in os.environ.items() if k in ('API_KEY', 'BASE_URL')})
CLIENT = DataRequestsClient(
    base_url=os.environ["BASE_URL"], api_key=os.environ["API_KEY"]
)

TEST_defaults = {
    "wait_time": 120.0,
    "cycles": 5,
    "dummy_list": [[0.0, 1.0], [2.0, 3.0]],
}


def seq_constructor(
    plate_id,
    sample_no,
    data_request_id,
    params={},
    seq_func=TEST_consecutive_noblocking,
    seq_name="TEST_consecutive_noblocking",
    seq_label="gcld-test",
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
    # seq.sequence_uuid = seq_uuid
    return seq


def gen_ts():
    return f"[{time.strftime('%H:%M:%S')}]"


def wait_for_orch(
    op: HelaoOperator, orch_state: OrchStatus = OrchStatus.busy, polling_time=5.0
):
    current_state = op.orch_state()
    current_orch = current_state["orch_state"]
    active_seq = current_state["active_sequence"]
    last_seq = current_state["last_sequence"]
    if current_orch != orch_state:
        print(f"orchestrator status {current_orch} != {orch_state}, waiting {polling_time} per iter:")
        progress = tqdm()
        while current_orch != orch_state:
            if current_orch in [OrchStatus.error, OrchStatus.estopped]:
                return current_orch, active_seq, last_seq
            time.sleep(polling_time)
            current_state = op.orch_state()
            current_orch = current_state["orch_state"]
            active_seq = current_state["active_sequence"]
            last_seq = current_state["last_sequence"]
            print(f"orchestrator status is now {current_orch}")
            progress.update()
    return orch_state, active_seq, last_seq


def num_uploads(db_cfg):
    resp, err = private_dispatcher("DB", db_cfg["host"], db_cfg["port"], "tasks")
    return len(resp.get("running", [])) + resp.get("num_queued", 0)


def main():
    helao_root = os.path.dirname(os.path.realpath(__file__))
    while "helao.py" not in os.listdir(helao_root):
        helao_root = os.path.dirname(helao_root)
    operator = HelaoOperator(inst_config, "ORCH")

    world_cfg = config_loader(inst_config, helao_root)
    db_cfg = world_cfg["servers"]["DB"]

    while True:
        with CLIENT:
            pending_requests = CLIENT.read_data_requests(status="pending")

        if pending_requests:
            print(f"Pending data request count: {len(pending_requests)}")
            data_request = pending_requests[0]
            sample_no = int(data_request.sample_label.split("_")[-1])

            # TEST SEQUENCE
            seq = seq_constructor(
                plate_id=PLATE_ID,
                sample_no=sample_no,
                data_request_id=data_request.id,
                params={},
                seq_func=TEST_consecutive_noblocking,
                seq_name="TEST_consecutive_noblocking",
                seq_label="gcld-test",
                param_defaults=TEST_defaults,
            )
            operator.add_sequence(seq.get_seq())
            print(f"Dispatching measurement sequence: {seq.sequence_uuid}")
            operator.start()

            time.sleep(5)

            # wait for sequence start (orch_state == "busy")
            current_state, active_seq, last_seq = wait_for_orch(
                operator, OrchStatus.busy
            )
            print("!!!")
            print(active_seq["sequence_uuid"])
            if current_state in [OrchStatus.error, OrchStatus.estopped]:
                with CLIENT:
                    output = CLIENT.set_status(
                        Status.failed, data_request_id=data_request.id
                    )
                    input(
                        "Press Enter to reset failed request to pending and exit operator..."
                    )
                    output = CLIENT.set_status(
                        Status.pending, data_request_id=data_request.id
                    )
                    return -1
            elif str(active_seq["sequence_uuid"]) == str(seq.sequence_uuid):
                # Acknowledge the data request
                with CLIENT:
                    output = CLIENT.acknowledge_data_request(data_request.id)
                print(f"Data request status: {output.status}")

            # wait for sequence end (orch_state == "idle")
            current_state, active_seq, last_seq = wait_for_orch(
                operator, OrchStatus.idle
            )
            if current_state in [OrchStatus.error, OrchStatus.estopped]:
                with CLIENT:
                    output = CLIENT.set_status(
                        Status.failed, data_request_id=data_request.id
                    )
                    input(
                        "Press Enter to reset failed request to pending and exit operator..."
                    )
                    output = CLIENT.set_status(
                        Status.pending, data_request_id=data_request.id
                    )
                    return -1

            time.sleep(30)

            # when orchestrator has stopped, check DB server for upload state
            num_sync_tasks = num_uploads(db_cfg)
            while num_sync_tasks > 0:
                print(f"Waiting for {num_sync_tasks} sequence uploads to finish.")
                time.sleep(10)
                num_sync_tasks = num_uploads(db_cfg)

            seq2 = seq_constructor(
                plate_id=PLATE_ID,
                sample_no=sample_no,
                data_request_id=data_request.id,
                params={},
                seq_func=TEST_consecutive_noblocking,
                seq_name="TEST_consecutive_noblocking",
                seq_label="gcld-test",
                param_defaults=TEST_defaults,
            )
            operator.add_sequence(seq2.get_seq())
            print(f"Dispatching analysis sequence: {seq2.sequence_uuid}")
            operator.start()

            time.sleep(5)

            # wait for analysis start (orch_state == "busy")
            current_state, active_seq, last_seq = wait_for_orch(
                operator, OrchStatus.busy
            )
            if current_state in [OrchStatus.error, OrchStatus.estopped]:
                with CLIENT:
                    output = CLIENT.set_status(
                        Status.failed, data_request_id=data_request.id
                    )
                    input(
                        "Press Enter to reset failed request to pending and exit operator..."
                    )
                    output = CLIENT.set_status(
                        Status.pending, data_request_id=data_request.id
                    )
                    return -1
            elif active_seq["sequence_uuid"] == seq.sequence_uuid:
                # Acknowledge the data request
                with CLIENT:
                    output = CLIENT.acknowledge_data_request(data_request.id)
                print(f"Data request status: {output.status}")

            # wait for analysis end (orch_state == "idle")
            current_state, active_seq, last_seq = wait_for_orch(
                operator, OrchStatus.idle
            )
            if current_state in [OrchStatus.error, OrchStatus.estopped]:
                with CLIENT:
                    output = CLIENT.set_status(
                        Status.failed, data_request_id=data_request.id
                    )
                    input(
                        "Press Enter to reset failed request to pending and exit operator..."
                    )
                    output = CLIENT.set_status(
                        Status.pending, data_request_id=data_request.id
                    )
                    return -1

        with CLIENT:
            print("Test mode: resetting data request status to pending.")
            output = CLIENT.set_status(Status.pending, data_request_id=data_request.id)
        print(
            f"{gen_ts()} Orchestrator is idle. Checking for data requests in 15 seconds."
        )
        time.sleep(15)


if __name__ == "__main__":
    main()
