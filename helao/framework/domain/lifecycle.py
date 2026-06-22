"""Pure action-lifecycle functions (init / output-dir / split).

These port the behaviour formerly carried as methods on the legacy runtime
``Action(Experiment(Sequence), ActionModel)`` diamond
(``init_act``/``init_seq``/``init_exp``/``get_action_dir``/``get_experiment_dir``/
``get_sequence_dir``) and the ``Active.split`` machinery, restructured as **pure
functions** operating on :class:`RunAction` run-models.

The wall clock (``now``) and uuids are **injected as arguments** and never read
inside these functions, so output is fully deterministic given fixed inputs. The
directory functions reproduce the legacy path strings byte-for-byte.

Side-effecting work (file-connection opens/closes, status emits, meta writes) is
returned as command/result value objects (:mod:`helao.framework.domain.commands`)
for the caller to realise through ports.

Purity: this module imports only from ``helao.framework.models`` /
``helao.framework.domain`` and stdlib.
"""

__all__ = [
    "init_action",
    "action_output_dir",
    "experiment_output_dir",
    "sequence_output_dir",
    "split_action",
]

import os
from copy import deepcopy
from datetime import datetime
from typing import Optional
from uuid import UUID

from helao.framework.models.hlostatus import HloStatus
from helao.framework.domain.run_models import RunAction
from helao.framework.domain.commands import ActionInit, SplitResult


# --- output-dir computation (pure, byte-for-byte with legacy) ------------------


def sequence_output_dir(action: RunAction) -> str:
    """Build the relative sequence output directory.

    Layout: ``YY.WW/MMDD/HHMMSS__name__label[-plate-serial[-sampleno]]``, always
    returned with forward slashes. Ports ``premodels.Sequence.get_sequence_dir``.
    """
    HMS = action.sequence_timestamp.strftime("%H%M%S")
    year_week = action.sequence_timestamp.strftime("%y.%U")
    sequence_day = action.sequence_timestamp.strftime("%m%d")
    plate = action.sequence_params.get("plate_id", "")
    smpno = action.sequence_params.get("plate_sample_no_list", [])
    if plate:
        serial = f"{plate}{str(sum([int(x) for x in str(plate)]) % 10)}"
        if f"-{serial}" not in action.sequence_label:
            if len(smpno) == 1:
                append_plate = f"-{serial}-{smpno[0]}"
            else:
                append_plate = f"-{serial}"
    else:
        append_plate = ""

    return os.path.join(
        year_week,
        sequence_day,
        f"{HMS}__{action.sequence_name}__{action.sequence_label}{append_plate}",
    ).replace(r"\\", "/")


def experiment_output_dir(action: RunAction) -> str:
    """Return ``sequence_dir/YYMMDD.HHMMSS__experiment_name``.

    Ports ``premodels.Experiment.get_experiment_dir``.
    """
    experiment_time = action.experiment_timestamp.strftime("%y%m%d.%H%M%S")
    sequence_dir = action.sequence_output_dir
    return os.path.join(
        str(sequence_dir),
        f"{experiment_time}__{action.experiment_name}",
    ).replace(r"\\", "/")


def action_output_dir(action: RunAction) -> str:
    """Return the relative output directory for an action.

    Layout:
    ``experiment_dir/{orch_submit_order}__{action_split}__{server_name}__{action_name}``.
    Ports ``premodels.Action.get_action_dir``.
    """
    experiment_dir = action.experiment_output_dir
    return "/".join(
        [
            str(experiment_dir),
            f"{action.orch_submit_order}__"
            f"{action.action_split}__"
            f"{action.action_server.server_name}__{action.action_name}",
        ]
    )


# --- identity initialisation (pure; clock + uuid injected) ---------------------


def _init_sequence(action: RunAction, *, now: datetime, uuid: UUID, force: bool) -> None:
    """In-place port of ``premodels.Sequence.init_seq`` with injected now/uuid."""
    if force or action.sequence_timestamp is None:
        action.sequence_timestamp = now
    if force or action.sequence_uuid is None:
        action.sequence_uuid = uuid
    if force or not action.sequence_status:
        action.sequence_status = [HloStatus.active]
    if force or action.sequence_output_dir is None:
        action.sequence_output_dir = sequence_output_dir(action)


def _init_experiment(action: RunAction, *, now: datetime, uuid: UUID, force: bool) -> None:
    """In-place port of ``premodels.Experiment.init_exp`` with injected now/uuid."""
    if force or action.experiment_timestamp is None:
        action.experiment_timestamp = now
    if force or action.experiment_uuid is None:
        action.experiment_uuid = uuid
    if force or not action.experiment_status:
        action.experiment_status = [HloStatus.active]
    if force or action.experiment_output_dir is None:
        action.experiment_output_dir = experiment_output_dir(action)


def init_action(
    action: RunAction,
    *,
    now: datetime,
    uuid: UUID,
    seq_uuid: Optional[UUID] = None,
    exp_uuid: Optional[UUID] = None,
    manual_names: Optional[dict] = None,
    force: bool = False,
) -> ActionInit:
    """Initialise an action's identity, auto-promoting to a manual run if needed.

    Pure port of ``premodels.Action.init_act``. When the action has no parent
    sequence/experiment timestamps it is promoted to a manual run: ``manual_action``
    set, ``access="manual"``, and synthetic ``seq--``/``exp--`` identity generated.
    Action-level timestamp, uuid, status and output dir are then filled in.

    Args:
        action: The run-action to initialise (mutated in place; also returned in
            the result).
        now: Wall-clock timestamp to assign (injected — never read internally).
        uuid: Action UUID to assign.
        seq_uuid: Sequence UUID to assign when auto-promoting to manual. Defaults
            to ``uuid`` if not supplied.
        exp_uuid: Experiment UUID to assign when auto-promoting. Defaults to
            ``uuid`` if not supplied.
        manual_names: Optional ``{"sequence_name", "experiment_name",
            "sequence_label"}`` overrides for the synthetic manual identity. When
            absent, the legacy ``seq--{action_name}`` / ``exp--{action_name}`` /
            ``"manual"`` defaults are used.
        force: When true, overwrite pre-existing action-level values.

    Returns:
        :class:`ActionInit` carrying the initialised action and the ``manual`` flag.
    """
    manual = action.sequence_timestamp is None or action.experiment_timestamp is None
    if manual:
        action.manual_action = True
        action.access = "manual"
        manual_suffix = action.action_name
        names = manual_names or {}
        action.sequence_name = names.get("sequence_name", f"seq--{manual_suffix}")
        action.sequence_label = names.get("sequence_label", "manual")
        _init_sequence(
            action,
            now=now,
            uuid=seq_uuid if seq_uuid is not None else uuid,
            force=False,
        )
        action.experiment_name = names.get("experiment_name", f"exp--{manual_suffix}")
        _init_experiment(
            action,
            now=now,
            uuid=exp_uuid if exp_uuid is not None else uuid,
            force=False,
        )

    if force or action.action_timestamp is None:
        action.action_timestamp = now
    if force or action.action_uuid is None:
        action.action_uuid = uuid
    if force or not action.action_status:
        action.action_status = [HloStatus.active]
    if force or action.action_output_dir is None:
        action.action_output_dir = action_output_dir(action)

    return ActionInit(action=action, manual=manual)


# --- split ---------------------------------------------------------------------


def split_action(
    action: RunAction,
    *,
    now: datetime,
    uuid: UUID,
) -> SplitResult:
    """Fork the current action into a new sibling with fresh file connections.

    Pure port of the state-mutation portion of ``Active.split``. The previous
    action is snapshotted and marked ``HloStatus.split``; the current action's
    ``action_split`` is incremented and its identity re-initialised (new
    ``uuid``/``now``); parent/child links are wired; samples/files are reset; and
    one new file-connection key is allocated per prior file connection.

    The actual opening (header write) of the new connections and closing of the
    old ones is left to the caller — the keys are returned in the result.

    Args:
        action: The active run-action to split (mutated in place to the new state).
        now: Timestamp for the re-initialised action (injected).
        uuid: UUID for the re-initialised (new) action.

    Returns:
        :class:`SplitResult` with the new and previous action states and the
        file-connection open/close key lists.
    """
    # snapshot the previous action before mutating
    prev_action = deepcopy(action)
    if HloStatus.split not in prev_action.action_status:
        prev_action.action_status.append(HloStatus.split)
    prev_action.data_stream_status = HloStatus.split

    close_file_conns = list(prev_action.file_conn_keys)

    # mutate the current action into the new split state
    action.data_stream_status = HloStatus.active
    # increment split counter BEFORE re-init (it feeds the output dir name)
    action.action_split += 1
    init_action(action, now=now, uuid=uuid, force=True)

    # parent/child linkage
    prev_action.child_action_uuid = action.action_uuid
    action.parent_action_uuid = prev_action.action_uuid

    # reset per-run state on the new action
    action.samples_in = []
    action.samples_out = []
    action.child_action_uuid = None
    action.files = []
    action.file_conn_keys = []

    # one new file connection per prior connection; prepend (legacy order).
    # Key allocation is kept pure/deterministic: each new key is derived from the
    # injected action uuid + index. Production callers may instead mint keys via a
    # port and assign them onto the returned action.
    open_file_conns = []
    for idx in range(len(close_file_conns)):
        new_key = _derive_conn_key(uuid, idx)
        open_file_conns.append(new_key)
        action.file_conn_keys = [new_key] + action.file_conn_keys

    return SplitResult(
        new_action=action,
        prev_action=prev_action,
        open_file_conns=open_file_conns,
        close_file_conns=close_file_conns,
    )


def _derive_conn_key(base: UUID, index: int) -> UUID:
    """Deterministically derive a new file-connection key from a base uuid+index.

    Pure helper: same (base, index) always yields the same UUID, so split output
    is reproducible in tests. Production callers may instead allocate keys via a
    port and assign them onto the returned action; this default keeps the function
    self-contained and deterministic.
    """
    import uuid as _uuid

    return _uuid.uuid5(base, str(index))
