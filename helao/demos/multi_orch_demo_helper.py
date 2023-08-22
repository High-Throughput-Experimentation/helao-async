import os
import sys

repo_root = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
)
async_root = os.path.join(repo_root, "helao-async")
core_root = os.path.join(repo_root, "helao-core")

sys.path.append(async_root)
sys.path.append(core_root)

from helaocore.models.sequence import SequenceModel
from helaocore.error import ErrorCodes
from helao.helpers.dispatcher import private_dispatcher
from helao.configs.demo0 import config as config0
from helao.configs.demo1 import config as config1
from helao.configs.demo2 import config as config2

cfgd = {"demo0": config0, "demo1": config1, "demo2": config2}

if __name__ == "__main__":
    if len(sys.argv) == 1:
        print("no arguments specified: use 'demo0', 'demo1', or 'demo2'")
    elif sys.argv[1] not in ["demo0", "demo1", "demo2"]:
        print("invalid arguments specified: use 'demo0', 'demo1', or 'demo2'")
    seq_params = {
        "init_random_points": 5,
        "stop_condition": "max_iters",
        "thresh_value": 100,
    }
    demokey = sys.argv[1]
    orchcfg = cfgd[demokey]["servers"]["ORCH"]
    seq = SequenceModel(sequence_name="OERSIM_activelearn", sequence_params=seq_params)
    resp, err = private_dispatcher(
        "ORCH",
        orchcfg["host"],
        orchcfg["port"],
        "append_sequence",
        params_dict={},
        json_dict=seq.as_dict(),
    )
    if err == ErrorCodes.none:
        print(f"enqueue sequence for {demokey} was successful")
        print(f"starting orchestrator on {demokey}")
        resp, err = private_dispatcher(
            "ORCH",
            orchcfg["host"],
            orchcfg["port"],
            "start",
            params_dict={},
            json_dict={},
        )
        if err == ErrorCodes.none:
            print(f"orchestrator start on {demokey} was successful")
    else:
        print(f"could not enqueue sequence for {demokey}")
