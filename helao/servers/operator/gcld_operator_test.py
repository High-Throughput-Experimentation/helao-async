import sys
import os
import time
from dotenv import load_dotenv
from pathlib import Path
from pprint import pprint

from gcld_operator import seq_constructor, gen_ts, wait_for_orch, num_uploads
from helao.servers.operator.helao_operator import HelaoOperator

from data_request_client.client import DataRequestsClient, CreateDataRequestModel
from helao.helpers.config_loader import CONFIG
from helao.sequences.TEST_seq import TEST_consecutive_noblocking
from helao.core.models.orchstatus import LoopStatus

inst_config = sys.argv[1]
PLATE_ID = int(sys.argv[2])
env_config = sys.argv[3]
load_dotenv(dotenv_path=Path(env_config))


# print({k: v for k, v in os.environ.items() if k in ('API_KEY', 'BASE_URL')})
CLIENT = DataRequestsClient(
    base_url=os.environ["BASE_URL"], api_key=os.environ["API_KEY"]
)

TEST_defaults = {
    "wait_time": 5.0,
    "cycles": 3,
    "dummy_list": [[0.0, 1.0], [2.0, 3.0]],
}


def main():
    helao_repo_root = os.path.dirname(os.path.realpath(__file__))
    while "launch.py" not in os.listdir(helao_repo_root):
        helao_repo_root = os.path.dirname(helao_repo_root)
    operator = HelaoOperator(inst_config, "ORCH")

    world_cfg = read_config(inst_config, helao_repo_root)
    db_cfg = world_cfg["servers"]["DB"]

    while True:
        with CLIENT:
            pending_requests = CLIENT.read_data_requests(status="pending")

        if pending_requests:
            print(f"{gen_ts()} Pending data request count: {len(pending_requests)}")
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
            print(f"{gen_ts()} Got measurement request for plate {PLATE_ID}, sample {sample_no}.")
            print(f"{gen_ts()} Measurement parameters for sequence: {seq.sequence_uuid}:")
            pprint(seq.sequence_params)
            operator.add_sequence(seq.get_seq())
            print(f"{gen_ts()} Dispatching measurement sequence: {seq.sequence_uuid}")
            operator.start()

            time.sleep(5)

            # wait for sequence start (orch_state == "busy")
            current_state, active_seq, last_seq = wait_for_orch(
                operator, LoopStatus.started
            )
            print(f"{gen_ts()} Measurement sequence {active_seq['sequence_uuid']} has started.")
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
            elif str(active_seq["sequence_uuid"]) == str(seq.sequence_uuid):
                # Acknowledge the data request
                with CLIENT:
                    output = CLIENT.acknowledge_data_request(data_request.id)
                print(f"{gen_ts()} Data request status: {output.status}")

            # wait for sequence end (orch_state == "idle")
            current_state, active_seq, last_seq = wait_for_orch(
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

            print(f"{gen_ts()} Unconditional 30 second wait for upload tasks to process.")
            time.sleep(30)

            # when orchestrator has stopped, check DB server for upload state
            num_sync_tasks = num_uploads(db_cfg)
            while num_sync_tasks > 0:
                print(f"{gen_ts()} Waiting for {num_sync_tasks} sequence uploads to finish.")
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
            print(f"{gen_ts()} Dispatching analysis sequence: {seq2.sequence_uuid}")
            operator.start()

            time.sleep(5)

            # wait for analysis start (orch_state == "busy")
            current_state, active_seq, last_seq = wait_for_orch(
                operator, LoopStatus.started
            )
            print(f"{gen_ts()} Analysis sequence {active_seq['sequence_uuid']} has started.")
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
            elif active_seq["sequence_uuid"] == seq.sequence_uuid:
                # Acknowledge the data request
                with CLIENT:
                    output = CLIENT.acknowledge_data_request(data_request.id)
                print(f"{gen_ts()} Data request status: {output.status}")

            # wait for analysis end (orch_state == "idle")
            current_state, active_seq, last_seq = wait_for_orch(
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
            with CLIENT:
                print("{gen_ts()} Test mode: resetting data request status to pending.")
                output = CLIENT.set_status(
                    "pending", data_request_id=data_request.id
                )
        else:
            print(f"{gen_ts()} No data requests are pending, creating a new one.")
            test_req = CreateDataRequestModel(
                composition={"Mn": 0.5, "Sb": 0.5},
                score=1.0,
                parameters={},
                sample_label="legacy__solid__6083_0",
            )
            with CLIENT:
                output = CLIENT.create_data_request(test_req)
            time.sleep(15)


if __name__ == "__main__":
    main()
