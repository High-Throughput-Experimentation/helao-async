"""Pure expansion + global-param folding for sequence/experiment dispatch.

These functions port the sequence/experiment unpacking and global-parameter
plumbing that the legacy orchestrator performed inline inside its dispatch loops
(``Orch.unpack_sequence``, ``Orch.verify_plate_in_params``, and the
``from_global_*_params`` / ``to_global_params`` folding inside
``loop_task_dispatch_sequence`` / ``loop_task_dispatch_experiment`` /
``loop_task_dispatch_action``).

Everything here is **pure**: no I/O, no asyncio, no network. The library maps
(``sequence_lib`` / ``experiment_lib``) and the platemap resolver are *injected*
by the caller — the actual import/registration of library modules and the
platemap file lookup are app/adapter concerns. This mirrors how the rest of the
domain layer takes its dependencies as arguments (see
:mod:`helao.framework.domain.lifecycle`).

The global-param fold helpers (:func:`fold_in_global` / :func:`fold_out_global`)
deliberately share the list/dict semantics used by
``ActionSession._build_global_export``:

* a **list** selects keys *by name* (kept under the same name);
* a **dict** renames ``src -> dst``.

Purity: imports only from ``helao.framework.models`` / ``domain`` and stdlib.
"""

__all__ = [
    "unpack_sequence",
    "unpack_experiment",
    "fold_in_global",
    "fold_out_global",
    "verify_plate_in_params",
]

import inspect
from typing import Callable, List, Mapping, Union

from helao.framework.models.experiment import ExperimentModel
from helao.framework.domain.run_models import RunAction, RunExperiment

from helao.framework.support import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


# --- sequence / experiment unpacking -------------------------------------------


def unpack_sequence(
    sequence_name: str,
    sequence_params: dict,
    *,
    sequence_lib: Mapping[str, Callable],
) -> List[ExperimentModel]:
    """Invoke the named sequence factory and return its planned experiments.

    Ports ``Orch.unpack_sequence``. The factory lookup map is injected rather
    than read from a registry, keeping this function pure.

    Args:
        sequence_name: Sequence library entry to expand.
        sequence_params: Keyword arguments forwarded to the sequence factory.
        sequence_lib: Map of sequence name to factory callable. A factory
            returns the list of planned :class:`ExperimentModel` objects.

    Returns:
        The list of planned experiments, or ``[]`` when ``sequence_name`` is not
        present in ``sequence_lib``.
    """
    if sequence_name in sequence_lib:
        return sequence_lib[sequence_name](**sequence_params)
    return []


def unpack_experiment(
    experiment: RunExperiment,
    experiment_params: dict,
    *,
    experiment_lib: Mapping[str, Callable],
) -> List[RunAction]:
    """Invoke the named experiment factory and return its planned actions.

    Ports the experiment-unpacking block in ``loop_task_dispatch_experiment``.
    The factory is called as ``func(experiment, **supplied_params)`` where
    ``supplied_params`` is ``experiment_params`` filtered to the factory's
    declared positional/keyword arguments (legacy used ``inspect.getfullargspec``
    to drop params the factory does not accept).

    The factory may return either a list of planned actions (returned directly)
    or a mutated experiment whose ``planned_actions`` carry the result.

    Args:
        experiment: The active experiment passed as the factory's first
            positional argument; its ``planned_actions`` are read if the factory
            returns the experiment itself rather than a list.
        experiment_params: Candidate keyword arguments; filtered to the
            factory's declared argument names before the call.
        experiment_lib: Map of experiment name to factory callable.

    Returns:
        The list of planned actions (possibly empty). Returns ``[]`` when the
        experiment name is not present in ``experiment_lib``.
    """
    name = experiment.experiment_name
    if name not in experiment_lib:
        return []

    exp_func = experiment_lib[name]
    exp_func_args = inspect.getfullargspec(exp_func).args
    supplied_params = {
        k: v for k, v in experiment_params.items() if k in exp_func_args
    }
    exp_return = exp_func(experiment, **supplied_params)

    if isinstance(exp_return, list):
        return exp_return
    if isinstance(exp_return, ExperimentModel):
        return list(exp_return.planned_actions)
    return []


# --- global-param folding ------------------------------------------------------


def fold_in_global(
    target_params: dict,
    from_global: Union[list, dict],
    global_params: dict,
) -> dict:
    """Copy named global params into a target param dict (sequence/exp/action).

    Ports the ``from_global_*_params`` block shared by all three dispatch loops.
    For each entry ``global_key -> dest``:

    * if ``global_key`` is absent from ``global_params`` the entry is skipped;
    * if ``dest`` is a list, the global value is written to every named key;
    * otherwise ``dest`` is treated as a single destination key.

    The input ``target_params`` is not mutated; a shallow copy with the folded
    keys applied is returned.

    Args:
        target_params: The destination param dict (action/experiment/sequence
            params).
        from_global: Mapping of ``global_key -> dest`` where ``dest`` is a single
            key name or a list of key names. Empty/None-equivalent maps are a
            no-op.
        global_params: The current global-params store to pull values from.

    Returns:
        A new dict equal to ``target_params`` with the resolved global values
        merged in.
    """
    out = dict(target_params)
    for global_key, dest in dict(from_global).items():
        if global_key not in global_params:
            LOGGER.info(
                f"global parameter {global_key} not found in global_params, skipping"
            )
            continue
        value = global_params[global_key]
        if isinstance(dest, list):
            for dest_key in dest:
                out[dest_key] = value
        else:
            out[dest] = value
        LOGGER.info(
            f"global parameter {global_key} found in global_params, setting to {value}"
        )
    return out


def fold_out_global(
    to_global: Union[list, dict],
    source_params: dict,
    source_output: dict,
) -> dict:
    """Resolve ``to_global_params`` into a global-params delta.

    Ports the ``to_global_params`` write-back block in
    ``loop_task_dispatch_action`` and shares the exact list/dict semantics of
    ``ActionSession._build_global_export``:

    * a **list** selects keys by name (kept under the same name);
    * a **dict** renames ``src -> dst``.

    Values are looked up first in ``source_params`` then in ``source_output``;
    keys found in neither are skipped.

    Args:
        to_global: List of source keys (same-name export) or dict of
            ``src -> dst`` renames.
        source_params: Params to look up source keys in first.
        source_output: Output to fall back to when a key is not in params.

    Returns:
        A delta dict to merge into the global-params store. Empty when nothing
        resolved.
    """
    export: dict = {}
    if isinstance(to_global, list):
        for key in to_global:
            if key in source_params:
                export[key] = source_params[key]
            elif key in source_output:
                export[key] = source_output[key]
            else:
                LOGGER.info(f"key {key} not found in source output or params")
    elif isinstance(to_global, dict):
        for src, dst in to_global.items():
            if src in source_params:
                export[dst] = source_params[src]
            elif src in source_output:
                export[dst] = source_output[src]
            else:
                LOGGER.info(f"key {src} not found in source output or params")
    return export


# --- plate verification --------------------------------------------------------


def verify_plate_in_params(paramd: dict, *, resolver: Callable) -> bool:
    """Confirm any ``plate_id``/``solid_plate_id`` param resolves to a platemap.

    Ports ``Orch.verify_plate_in_params``. The platemap lookup is injected as
    ``resolver(plate_id) -> platemap | None`` so the actual file access lives in
    the adapter layer; this function is pure given the resolver.

    Args:
        paramd: Parameter dictionary to inspect.
        resolver: Callable mapping a plate id to a truthy platemap (or a
            falsy/None value when no map exists).

    Returns:
        ``True`` if no plate parameter is present, or if one of
        ``solid_plate_id`` / ``plate_id`` resolves to a valid platemap. ``False``
        when a plate parameter is present but no platemap could be resolved.
    """
    if "solid_plate_id" not in paramd and "plate_id" not in paramd:
        # no plate parameter, so act like it's fine
        return True

    for pid_key in ("solid_plate_id", "plate_id"):
        pid_val = paramd.get(pid_key, None)
        if pid_val is not None:
            platemap = resolver(pid_val)
            if platemap:
                LOGGER.info(f"plate_id {pid_val} was found with a valid platemap")
                return True
    return False
