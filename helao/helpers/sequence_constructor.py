"""Helper for materializing a :class:`Sequence` from a sequence-library function."""

import inspect
from typing import Optional
from uuid import UUID

from .premodels import Sequence
from .time_utils import gen_uuid


def constructor(
    sequence_function: callable,
    params: dict = {},
    sequence_label: Optional[str] = None,
    data_request_id: Optional[UUID] = None,
) -> Sequence:
    """Invoke a sequence-library function and wrap the result in a :class:`Sequence`.

    The function's introspected default arguments form the parameter baseline;
    keys provided in ``params`` override those defaults when they match a known
    argument name.

    Args:
        sequence_function: Library function that returns a list of planned
            experiments.
        params: Overrides for the function's default arguments.
        sequence_label: Optional human-readable label stored on the sequence.
        data_request_id: Optional UUID linking the sequence to an upstream
            data request.

    Returns:
        Newly constructed :class:`Sequence` with the planned experiments
        populated and a fresh ``sequence_uuid``.
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
