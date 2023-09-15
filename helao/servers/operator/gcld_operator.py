import sys
import os
import inspect
from uuid import uuid4

from helao.servers.operator.operator import Operator
from helao.helpers.gcld_client import DataRequestsClient
from helao.helpers.premodels import Sequence
from helao.sequences.UVIS_T_seq import UVIS_T

client = DataRequestsClient()
inst_config = sys.argv[1]
plate_id = int(sys.argv[2])


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


if __name__ == "__main__":
    helao_root = os.path.dirname(os.path.realpath(__file__))
    while "helao.py" not in os.listdir(helao_root):
        helao_root = os.path.dirname(helao_root)
    operator = Operator(inst_config, "ORCH")

    seq = uvis_seq_constructor(1234, 4321, uuid4())
    print(seq.clean_dict())
    