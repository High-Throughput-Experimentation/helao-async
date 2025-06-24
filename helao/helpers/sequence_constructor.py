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
    """
    Constructs a Sequence object by invoking a sequence function with specified parameters.

    Args:
        sequence_function (callable): The function that generates the sequence of experiments.
        params (dict, optional): A dictionary of parameters to pass to the sequence function. Defaults to {}.
        sequence_label (str, optional): An optional label for the sequence. Defaults to None.
        data_request_id (UUID, optional): An optional UUID for data request identification. Defaults to None.

    Returns:
        Sequence: A Sequence object containing the generated sequence of experiments.
    """
    argspec = inspect.getfullargspec(sequence_function)
    seq_args = list(argspec.args)
    seq_defaults = list(argspec.defaults)
    seq_uuid = gen_uuid()
    seq_params = {k: v for k, v in zip(seq_args, seq_defaults)}
    for k, v in params.items():
        if k in seq_params:
            seq_params[k] = v
    unpacked_experiments = sequence_function(**seq_params)
    seq = Sequence(
        sequence_name=sequence_function.__name__,
        sequence_label=sequence_label,
        sequence_params=seq_params,
        sequence_uuid=seq_uuid,
        data_request_id=data_request_id,
        planned_experiments=unpacked_experiments,
        dispatched_experiments=[],
        dispatched_experiments_abbr=[],
    )
    seq.sequence_uuid = seq_uuid
    return seq
