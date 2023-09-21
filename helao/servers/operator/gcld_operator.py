import sys
import os
import inspect
import time
from dotenv import load_dotenv
from pathlib import Path

from helao.servers.operator.operator import Operator
from helao.helpers.gcld_client import DataRequestsClient
from helao.helpers.premodels import Sequence
from helao.sequences.UVIS_T_seq import UVIS_T


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
    seq_params = {k: v for k, v in zip(seq_args, seq_defaults)}
    seq_params.update(params)
    seq_params["plate_id"] = plate_id
    seq_params["plate_sample_no_list"] = [sample_no]
    seq = Sequence(
        sequence_name="UVIS_T",
        sequence_label="gcld-mvp-demo",
        sequence_params=seq_params,
        data_request_id=data_request_id,
    )
    seq.experiment_list = UVIS_T(**seq_params)
    return seq


def gen_ts():
    return f"[{time.strftime('%H:%M:%S')}]"


if __name__ == "__main__":
    helao_root = os.path.dirname(os.path.realpath(__file__))
    while "helao.py" not in os.listdir(helao_root):
        helao_root = os.path.dirname(helao_root)
    operator = Operator(inst_config, "ORCH")

    while True:
        with client:
            # get pending data requests
            output = client.read_data_requests(status="pending")

            if output:
                print(f"Pending data request count: {len(output)}")
                data_request = output[0]
                sample_no = int(data_request.sample_label.split("_")[-1])

                seq = uvis_seq_constructor(PLATE_ID, sample_no, data_request.id)
                operator.add_sequence(seq.get_seq())
                operator.start()

            current_state = operator.orch_state()

            if current_state != "stopped":
                # Acknowledge the data request
                output = client.acknowledge_data_request(data_request.id)
                print(f"Data request status: {output.status}")

                while current_state != "stopped":
                    print(
                        f"{gen_ts()} Orchestrator loop status is {current_state}. Sleeping for 10s."
                    )
                    time.sleep(10)
                    current_state = operator.orch_state()

            print(
                f"{gen_ts()} Orchestrator is idle. Checking for data requests in 30 seconds."
            )
            time.sleep(30)
