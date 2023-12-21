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

from helao.servers.operator.operator import HelaoOperator
from helao.helpers.gcld_client import DataRequestsClient, CreateDataRequestModel
from helao.helpers.premodels import Sequence, Experiment
from helao.helpers.dispatcher import private_dispatcher
from helao.helpers.config_loader import config_loader
from helao.helpers.gen_uuid import gen_uuid
from helao.sequences.UVIS_T_seq import UVIS_T, UVIS_T_postseq


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
        experiment_list=experiment_list,
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
        {
            "analysis_seq_uuid": sequence_uuid,
            "plate_id": plate_id,
            "recent": False
        }
    )
    experiment_list = UVIS_T_postseq(**seq_params)
    seq = Sequence(
        sequence_name="UVIS_T_postseq",
        sequence_label="gcld-mvp-demo-analysis",
        sequence_params=seq_params,
        sequence_uuid=seq_uuid,
        data_request_id=data_request_id,
        experiment_list=experiment_list,
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
    operator = HelaoOperator(inst_config, "ORCH")

    world_cfg = config_loader(inst_config, helao_root)
    db_cfg = world_cfg["servers"]["DB"]

    def num_running_uploads():
        resp, err = private_dispatcher("DB", db_cfg["host"], db_cfg["port"], "running")
        return len(resp)

    reqmodels = [
        CreateDataRequestModel(composition = {"Mn": 1.0, "Sb": 0.0}, score = 1.0, sample_label="sample_1000"),
        CreateDataRequestModel(composition = {"Mn": 0.5, "Sb": 0.5}, score = 1.0, sample_label="sample_3000"),
    ]

    for reqmod in reqmodels:
        with client:
            # get pending data requests
            output = client.create_data_request(reqmod)

        if output:
            data_request = output
            sample_no = int(data_request.sample_label.split("_")[-1])

            seq = uvis_seq_constructor(PLATE_ID, sample_no, data_request.id)
            operator.add_sequence(seq.get_seq())
            print(f"Dispatching measurement sequence: {seq.sequence_uuid}")
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

            time.sleep(30)
                
            # when orchestrator has stopped, check DB server for upload state
            num_uploads = num_running_uploads()
            while num_uploads > 0:
                print(f"Waiting for {num_uploads} sequence uploads to finish.")
                time.sleep(10)
                num_uploads = num_running_uploads()
            
            ana = uvis_ana_constructor(PLATE_ID, str(seq.sequence_uuid), data_request.id)
            operator.add_sequence(ana.get_seq())
            print(f"Dispatching analysis sequence: {ana.sequence_uuid}")
            operator.start()
            time.sleep(2)

            current_state = operator.orch_state()

            while current_state != "stopped":
                print(
                    f"{gen_ts()} Orchestrator loop status is {current_state}. Sleeping for 10s."
                )
                time.sleep(10)
                current_state = operator.orch_state()
                
        print(
            f"{gen_ts()} Orchestrator is idle. Checking for data requests in 15 seconds."
        )
        time.sleep(15)
