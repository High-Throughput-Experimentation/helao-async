"""Pure global-params fold functions extracted from ``Orch`` (CARDS P5, Stage S1).

``Orch.loop_task_dispatch_{sequence,experiment,action}`` each carried an inline
"fold-in" block that copies requested ``global_params`` entries into that
level's params dict (``from_global_seq_params`` / ``from_global_exp_params`` /
``from_global_act_params``), and ``loop_task_dispatch_action`` additionally
carried a "fold-out" block that copies a finished action's requested
``to_global_params`` back into ``global_params``. This module de-duplicates
the three near-identical fold-in copies and the fold-out block into pure,
unit-testable free functions.

Per the P5 constraints (:doc:`CARDS_REFACTOR_P5.md` sec 3.1 rule 3): these
functions cache no shared mutable state -- every caller passes the concrete
dict(s) to mutate/read at call time, so ``import_queues`` reassigning
``global_params`` (or any other attribute) cannot leave a stale reference
behind here. Fold-out resolution lives in
``helao.helpers.global_exports.resolve_global_exports``: ``action_output``
first, then ``action_params`` (record schema spec sec 4.5).
"""

from helao.helpers import helao_logging as logging
from helao.helpers.global_exports import resolve_global_exports

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


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

    exports = resolve_global_exports(
        result_action.to_global_params,
        result_action.action_params,
        result_action.action_output,
    )
    for k in exports:
        LOGGER.info(f"updating {k} in global vars")
    global_params.update(exports)
