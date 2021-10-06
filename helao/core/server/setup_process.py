import json
from socket import gethostname

from fastapi import Request
from helao.core.model import sample_list
from helao.core.schema import cProcess


async def setup_process(request: Request):
    servKey, _, process_name = request.url.path.strip("/").partition("/")
    body_bytes = await request.body()
    if body_bytes == b"":
        body_params = {}
    else:
        body_params = await request.json()

    process_dict = dict()
    # process_dict.update(request.query_params)
    if len(request.query_params) == 0:  # cannot check against {}
        # empty: orch
        process_dict.update(body_params)
    else:
        # not empty: swagger
        if "process_params" not in process_dict:
            process_dict.update({"process_params": {}})
        process_dict["process_params"].update(body_params)
        # process_dict["process_params"].update(request.query_params)
        for k, v in request.query_params.items():
            try:
                val = json.loads(v)
            except ValueError:
                val = v
            process_dict["process_params"][k] = val

    process_dict["process_server"] = servKey
    process_dict["process_name"] = process_name
    A = cProcess(process_dict)

    if "fast_samples_in" in A.process_params:
        tmp_fast_samples_in = A.process_params.get("fast_samples_in", [])
        del A.process_params["fast_samples_in"]
        if type(tmp_fast_samples_in) is dict:
            A.samples_in = sample_list(**tmp_fast_samples_in)
        elif type(tmp_fast_samples_in) is list:
            A.samples_in = sample_list(samples=tmp_fast_samples_in)

    # setting some default values if process was not submitted via orch
    if A.machine_name is None:
        A.machine_name = gethostname()
    if A.technique_name is None:
        A.technique_name = "MANUAL"
        A.orch_name = "MANUAL"
        A.process_group_label = "MANUAL"
    # sample_list cannot be serialized so needs to be updated here
    if A.samples_in == []:
        A.samples_in = sample_list()
    if A.samples_out == []:
        A.samples_out = sample_list()

    return A
