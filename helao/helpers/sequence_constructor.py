import inspect
from typing import Optional
from uuid import UUID

from helao.helpers.premodels import Sequence
from helao.helpers.gen_uuid import gen_uuid


def constructor(
    sequence_function: callable,
    params: dict = {},
    sequence_label: Optional[str] = None,
    data_request_id: Optional[UUID] = None
) -> Sequence:
    """Return a sequence object with experiment list determined by sequence_function."""
    argspec = inspect.getfullargspec(sequence_function)
    seq_args = list(argspec.args)
    seq_defaults = list(argspec.defaults)
    seq_uuid = gen_uuid()
    seq_params = {k: v for k, v in zip(seq_args, seq_defaults)}
    for k, v in params.items():
        if k in seq_params:
            seq_params[k] = v
    experiment_list = sequence_function(**seq_params)
    seq = Sequence(
        sequence_name=sequence_function.__name__,
        sequence_label=sequence_label,
        sequence_params=seq_params,
        sequence_uuid=seq_uuid,
        data_request_id=data_request_id,
        experiment_list=experiment_list,
        experiment_plan_list=experiment_list,
        experimentmodel_list=experiment_list,
    )
    seq.sequence_uuid = seq_uuid
    return seq
