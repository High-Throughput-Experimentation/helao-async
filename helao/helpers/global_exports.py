"""``to_global_params`` resolution shared by the orchestrator, the finalizer and MicroOrch."""

__all__ = ["resolve_global_exports"]

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


def resolve_global_exports(
    to_global_params, action_params: dict, action_output: dict
) -> dict:
    """Values named by ``to_global_params``, ``action_output`` first (spec §4.5).

    Output first: an action may write a result under the name of one of its
    inputs (``calc_server``'s ``min_offset_ocv``), and params-first would
    export the stale input. A list exports under the same name; a dict maps
    source -> global name.
    """
    if isinstance(to_global_params, list):
        pairs = [(k, k) for k in to_global_params]
    elif isinstance(to_global_params, dict):
        pairs = list(to_global_params.items())
    else:
        return {}
    out = {}
    for src, dst in pairs:
        if src in action_output:
            out[dst] = action_output[src]
        elif src in action_params:
            out[dst] = action_params[src]
        else:
            LOGGER.info(f"key {src} not found in action output or params")
    return out
