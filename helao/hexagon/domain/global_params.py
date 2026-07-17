"""Pure global-params fold functions — hexagon domain copy (spec §4.2.2).

Ported byte-identically from helao/core/servers/orch_global_params.py
(CARDS P5 Stage S1) per Q6. Behavior including log wording, list-vs-dict
to_global_params handling, and key iteration order is preserved. The only
change: LOGGER is stdlib logging (helao.helpers.helao_logging is outside the
domain allow-list).
"""

import logging

LOGGER = logging.getLogger(__name__)


def apply_from_globals(
    params: dict,
    from_global_map: dict,
    global_params: dict,
    *,
    logger_ctx: str,
) -> None:
    """Fold requested global params into ``params`` (mutated in place).

    Mirrors the historical inline fold-in blocks in
    ``Orch.loop_task_dispatch_sequence`` (``logger_ctx="sequence"``),
    ``Orch.loop_task_dispatch_experiment`` (``logger_ctx="experiment --"``),
    and ``Orch.loop_task_dispatch_action`` (``logger_ctx="action"``).
    ``logger_ctx`` reproduces the exact wording used by each call site's
    "mapping from global params to ..." log line.
    """
    for k, v in from_global_map.items():
        LOGGER.info(f"mapping from global params to {logger_ctx} {k}:{v}")
        if k in global_params:
            if isinstance(v, list):
                for vv in v:
                    params[vv] = global_params[k]
            else:
                params[v] = global_params[k]
            LOGGER.info(
                f"global parameter {k} found in global_params, setting to {global_params[k]}"
            )
        else:
            LOGGER.info(f"global parameter {k} not found in global_params, skipping")


def collect_to_globals(
    result_action,
    global_params: dict,
    *,
    orch_key: str,
    orch_host: str,
    orch_port,
) -> None:
    """Fold a finished action's ``to_global_params`` back into ``global_params``.

    Mirrors the historical inline fold-out block in
    ``Orch.loop_task_dispatch_action``. Mutates ``global_params`` in place;
    a no-op unless ``result_action.to_global_params`` is truthy and the
    action's ``orch_key``/``orch_host``/``orch_port`` match the given
    identity (reproduces the original guard verbatim, including the
    ``int(...)`` port comparison).
    """
    if not (
        result_action.to_global_params
        and result_action.orch_key == orch_key
        and result_action.orch_host == orch_host
        and int(result_action.orch_port) == int(orch_port)
    ):
        return

    if isinstance(result_action.to_global_params, list):
        for k in result_action.to_global_params:
            if k in result_action.action_params:
                LOGGER.info(f"updating {k} in global vars")
                global_params[k] = result_action.action_params[k]
            elif k in result_action.action_output:
                LOGGER.info(f"updating {k} in global vars")
                global_params[k] = result_action.action_output[k]
            else:
                LOGGER.info(f"key {k} not found in action output or params")
    elif isinstance(result_action.to_global_params, dict):
        for k1, k2 in result_action.to_global_params.items():
            if k1 in result_action.action_params:
                LOGGER.info(f"updating {k2} in global vars")
                global_params[k2] = result_action.action_params[k1]
            elif k1 in result_action.action_output:
                LOGGER.info(f"updating {k2} in global vars")
                global_params[k2] = result_action.action_output[k1]
            else:
                LOGGER.info(f"key {k1} not found in action output or params")
