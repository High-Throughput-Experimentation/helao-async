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

MEASURED_6083 = [
    766,
    802,
    1872,
    3096,
    3113,
    3131,
    4479,
    4550,
    7571,
    7633,
    9012,
    9056,
    9065,
    9083,
    9109,
    10739,
    12439,
    13989,
    13989,
    14069,
    14087,
    14122,
    15654,
    15760,
    17319,
    17319,
    17346,
    17461,
    19028,
    19117,
    20461,
    22035,
    22044,
    22079,
    23579,
    23606,
    23641,
    24980,
    26230,
    26283,
    27300,
    27362,
]

# TEST_SMPS_6083 = [
#     {
#         "sample_no": s,
#         "composition": {"Mn": 0.5, "Sb": 0.5},
#         "parameters": {"z_start": 1.2, "z_direction": "up"},
#     }
#     for s in MEASURED_6083
# ]

TEST_SMPS_6083 = [
    {
        "sample_no": 766,
        "composition": {"Mn": 0.730724324204254, "Sb": 0.2692756757957459},
        "parameters": {"z_start": 1.2, "z_direction": "up"},
    },
    {
        "sample_no": 802,
        "composition": {"Mn": 0.5563284103323283, "Sb": 0.4436715896676717},
        "parameters": {"z_start": 1.2, "z_direction": "up"},
    },
    {
        "sample_no": 1872,
        "composition": {"Mn": 0.5851885328408131, "Sb": 0.4148114671591871},
        "parameters": {"z_start": 1.2, "z_direction": "up"},
    },
    {
        "sample_no": 3096,
        "composition": {"Mn": 0.7340208256425407, "Sb": 0.2659791743574593},
        "parameters": {"z_start": 1.2, "z_direction": "up"},
    },
    {
        "sample_no": 3113,
        "composition": {"Mn": 0.6507736413207856, "Sb": 0.3492263586792143},
        "parameters": {"z_start": 1.2, "z_direction": "up"},
    },
    {
        "sample_no": 3131,
        "composition": {"Mn": 0.5570478779827862, "Sb": 0.44295212201721373},
        "parameters": {"z_start": 1.2, "z_direction": "up"},
    },
    {
        "sample_no": 4479,
        "composition": {"Mn": 0.7935558421700739, "Sb": 0.20644415782992603},
        "parameters": {"z_start": 1.2, "z_direction": "up"},
    },
    {
        "sample_no": 4550,
        "composition": {"Mn": 0.4314344778657142, "Sb": 0.5685655221342858},
        "parameters": {"z_start": 1.2, "z_direction": "up"},
    },
    {
        "sample_no": 7571,
        "composition": {"Mn": 0.7216625888365149, "Sb": 0.2783374111634851},
        "parameters": {"z_start": 1.2, "z_direction": "up"},
    },
    {
        "sample_no": 7633,
        "composition": {"Mn": 0.409317247736705, "Sb": 0.5906827522632949},
        "parameters": {"z_start": 1.2, "z_direction": "up"},
    },
    {
        "sample_no": 9012,
        "composition": {"Mn": 0.8150660942470382, "Sb": 0.1849339057529617},
        "parameters": {"z_start": 1.2, "z_direction": "up"},
    },
    {
        "sample_no": 9056,
        "composition": {"Mn": 0.5972417128495429, "Sb": 0.4027582871504571},
        "parameters": {"z_start": 1.2, "z_direction": "up"},
    },
    {
        "sample_no": 9065,
        "composition": {"Mn": 0.5416354058899252, "Sb": 0.4583645941100748},
        "parameters": {"z_start": 1.2, "z_direction": "up"},
    },
    {
        "sample_no": 9083,
        "composition": {"Mn": 0.44377339031650664, "Sb": 0.5562266096834935},
        "parameters": {"z_start": 1.2, "z_direction": "up"},
    },
    {
        "sample_no": 9109,
        "composition": {"Mn": 0.3310238330802191, "Sb": 0.6689761669197809},
        "parameters": {"z_start": 1.2, "z_direction": "up"},
    },
    {
        "sample_no": 10739,
        "composition": {"Mn": 0.49463858674689504, "Sb": 0.505361413253105},
        "parameters": {"z_start": 1.2, "z_direction": "up"},
    },
    {
        "sample_no": 12439,
        "composition": {"Mn": 0.30645190507819575, "Sb": 0.6935480949218042},
        "parameters": {"z_start": 1.2, "z_direction": "up"},
    },
    {
        "sample_no": 13989,
        "composition": {"Mn": 0.8604921447308469, "Sb": 0.13950785526915319},
        "parameters": {"z_start": 1.2, "z_direction": "up"},
    },
    {
        "sample_no": 13989,
        "composition": {"Mn": 0.8604921447308469, "Sb": 0.13950785526915319},
        "parameters": {"z_start": 1.2, "z_direction": "up"},
    },
    {
        "sample_no": 14069,
        "composition": {"Mn": 0.4718580053279528, "Sb": 0.5281419946720471},
        "parameters": {"z_start": 1.2, "z_direction": "up"},
    },
    {
        "sample_no": 14087,
        "composition": {"Mn": 0.3692931609486959, "Sb": 0.6307068390513042},
        "parameters": {"z_start": 1.2, "z_direction": "up"},
    },
    {
        "sample_no": 14122,
        "composition": {"Mn": 0.21980562672479462, "Sb": 0.7801943732752054},
        "parameters": {"z_start": 1.2, "z_direction": "up"},
    },
    {
        "sample_no": 15654,
        "composition": {"Mn": 0.8654259187536348, "Sb": 0.13457408124636525},
        "parameters": {"z_start": 1.2, "z_direction": "up"},
    },
    {
        "sample_no": 15760,
        "composition": {"Mn": 0.32772795014225714, "Sb": 0.6722720498577428},
        "parameters": {"z_start": 1.2, "z_direction": "up"},
    },
    {
        "sample_no": 17319,
        "composition": {"Mn": 0.8735533794663827, "Sb": 0.1264466205336174},
        "parameters": {"z_start": 1.2, "z_direction": "up"},
    },
    {
        "sample_no": 17319,
        "composition": {"Mn": 0.8735533794663827, "Sb": 0.1264466205336174},
        "parameters": {"z_start": 1.2, "z_direction": "up"},
    },
    {
        "sample_no": 17346,
        "composition": {"Mn": 0.7738664754469314, "Sb": 0.22613352455306865},
        "parameters": {"z_start": 1.2, "z_direction": "up"},
    },
    {
        "sample_no": 17461,
        "composition": {"Mn": 0.17397206897272835, "Sb": 0.8260279310272717},
        "parameters": {"z_start": 1.2, "z_direction": "up"},
    },
    {
        "sample_no": 19028,
        "composition": {"Mn": 0.6798048076654397, "Sb": 0.32019519233456034},
        "parameters": {"z_start": 1.2, "z_direction": "up"},
    },
    {
        "sample_no": 19117,
        "composition": {"Mn": 0.19617412805896464, "Sb": 0.8038258719410354},
        "parameters": {"z_start": 1.2, "z_direction": "up"},
    },
    {
        "sample_no": 20461,
        "composition": {"Mn": 0.8068568481593802, "Sb": 0.19314315184061973},
        "parameters": {"z_start": 1.2, "z_direction": "up"},
    },
    {
        "sample_no": 22035,
        "composition": {"Mn": 0.8532437944210047, "Sb": 0.14675620557899524},
        "parameters": {"z_start": 1.2, "z_direction": "up"},
    },
    {
        "sample_no": 22044,
        "composition": {"Mn": 0.8056384914759117, "Sb": 0.19436150852408832},
        "parameters": {"z_start": 1.2, "z_direction": "up"},
    },
    {
        "sample_no": 22079,
        "composition": {"Mn": 0.6306049979589127, "Sb": 0.36939500204108733},
        "parameters": {"z_start": 1.2, "z_direction": "up"},
    },
    {
        "sample_no": 23579,
        "composition": {"Mn": 0.6253356399926024, "Sb": 0.3746643600073976},
        "parameters": {"z_start": 1.2, "z_direction": "up"},
    },
    {
        "sample_no": 23606,
        "composition": {"Mn": 0.4442777685324733, "Sb": 0.5557222314675268},
        "parameters": {"z_start": 1.2, "z_direction": "up"},
    },
    {
        "sample_no": 23641,
        "composition": {"Mn": 0.2491646874526252, "Sb": 0.7508353125473748},
        "parameters": {"z_start": 1.2, "z_direction": "up"},
    },
    {
        "sample_no": 24980,
        "composition": {"Mn": 0.5702077645990102, "Sb": 0.4297922354009899},
        "parameters": {"z_start": 1.2, "z_direction": "up"},
    },
    {
        "sample_no": 26230,
        "composition": {"Mn": 0.6318979323991896, "Sb": 0.36810206760081055},
        "parameters": {"z_start": 1.2, "z_direction": "up"},
    },
    {
        "sample_no": 26283,
        "composition": {"Mn": 0.28514730606859073, "Sb": 0.7148526939314093},
        "parameters": {"z_start": 1.2, "z_direction": "up"},
    },
    {
        "sample_no": 27300,
        "composition": {"Mn": 0.6934476679912756, "Sb": 0.30655233200872445},
        "parameters": {"z_start": 1.2, "z_direction": "up"},
    },
    {
        "sample_no": 27362,
        "composition": {"Mn": 0.28996638258663954, "Sb": 0.7100336174133605},
        "parameters": {"z_start": 1.2, "z_direction": "up"},
    },
]

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
    # "reservoir_electrolyte": "OER10",
    # "reservoir_liquid_sample_no": 198,
    "reservoir_electrolyte": "H2O",
    "reservoir_liquid_sample_no": 1,
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
        experimentmodel_list=[],
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
            matching_requests = [
                req for req in acknowledged_requests if str(req.id) == RESUME_ID
            ]
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
            print(f"{gen_ts()} Got measurement request {data_request.id}")
            print(f"{gen_ts()} Plate {PLATE_ID} sample {sample_no} has composition:")
            pprint(data_request.composition)
            print(
                f"{gen_ts()} Measurement parameters for sequence: {insitu_seq.sequence_uuid}:"
            )
            pprint(data_request.parameters)
            operator.add_sequence(insitu_seq.get_seq())
            print(
                f"{gen_ts()} Dispatching measurement sequence: {insitu_seq.sequence_uuid}"
            )
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
            elif str(active_insitu_seq["sequence_uuid"]) == str(
                insitu_seq.sequence_uuid
            ):
                # Acknowledge the data request
                with CLIENT:
                    output = CLIENT.acknowledge_data_request(data_request.id)
                print(
                    f"{gen_ts()} Data request {data_request.id} status: {output.status}"
                )

        if data_request:
            # wait for sequence end (orch_state == "idle")
            current_state, _, _ = wait_for_orch(operator, LoopStatus.stopped)
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
