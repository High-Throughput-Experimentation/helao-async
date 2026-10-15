"""Helper script for launching active-learning demo sequences on multiple orchestrators.

Resolves the demo config matching the ``demo0``/``demo1`` prefix supplied on
the command line, builds an ``OERSIM_activelearn`` sequence with the requested stop
criteria, enqueues it through the orchestrator's ``append_sequence`` endpoint, and
then starts the orchestrator.
"""

import sys

from helao.core.error import ErrorCodes
from helao.helpers.config_loader import read_config
from helao.helpers.dispatcher import private_dispatcher
from helao.helpers.premodels import Sequence
from helao.helpers.time_utils import gen_uuid

from helao.deploy.test.sequences.OERSIM_seq import OERSIM_activelearn

cfgd = {f"demo{i}": read_config(f"demo{i}") for i in range(2)}

if __name__ == "__main__":
    if len(sys.argv) == 1 or sys.argv[1] not in cfgd:
        print(f"missing or invalid argument: use one of {sorted(cfgd)}")
        sys.exit(1)
    if len(sys.argv) > 2:
        iters = int(sys.argv[2])
    else:
        iters = 10
    seq_params = {
        "init_random_points": 5,
        "stop_condition": "max_iters",
        "thresh_value": iters,
    }
    demokey = sys.argv[1]
    orchcfg = cfgd[demokey]["servers"]["ORCH"]
    exp_plan = OERSIM_activelearn(**seq_params)
    print(exp_plan)
    seq = Sequence(
        sequence_name="OERSIM_activelearn",
        sequence_label=f"{demokey}",
        sequence_params=seq_params,
        planned_experiments=exp_plan,
        sequence_uuid=gen_uuid(),
        dummy=True,
        simulation=True,
    )
    print(seq.as_dict())
    resp, err = private_dispatcher(
        "ORCH",
        orchcfg["host"],
        orchcfg["port"],
        "append_sequence",
        params_dict={},
        json_dict={"sequence": seq.as_dict()},
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
