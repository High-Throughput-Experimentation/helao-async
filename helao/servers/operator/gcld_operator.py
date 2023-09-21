import sys
import os
import inspect
import time
from dotenv import load_dotenv
from pathlib import Path

inst_config = sys.argv[1]
PLATE_ID = int(sys.argv[2])
env_config = sys.argv[3]
load_dotenv(dotenv_path=Path(env_config))

from helao.servers.operator.operator import Operator
from helao.helpers.gcld_client import DataRequestsClient
from helao.helpers.premodels import Sequence
from helao.sequences.UVIS_T_seq import UVIS_T


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
            "calc_ev_parts": [1.8, 2.2, 2.6, 3.0],
            "calc_bin_width": 3,
            "calc_window_length": 45,
            "calc_poly_order": 4,
            "calc_lower_wl": 370.0,
            "calc_upper_wl": 700.0,
        }
    )

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
            time.sleep(2)

        current_state = operator.orch_state()

        if current_state != "stopped":
            # Acknowledge the data request
            with client:
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
