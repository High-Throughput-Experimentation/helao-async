"""Flat runtime run-models for the action lifecycle.

The legacy orchestrator/action server held a triple-diamond runtime object,
``Action(Experiment(Sequence), ActionModel)`` (see
``helao.helpers.premodels``). That MRO diamond gave a single object the union
of sequence + experiment + action fields plus runtime-only fields, but made the
model hierarchy hard to reason about.

This module flattens the diamond to **single inheritance** and makes the
provenance explicit:

* :class:`RunSequence` ``(SequenceModel)`` — adds the ``dispatched_experiments``
  runtime tally.
* :class:`RunExperiment` ``(ExperimentModel)`` — adds the ``dispatched_actions``
  runtime tally.
* :class:`RunAction` ``(ActionModel)`` — adds the runtime-only fields
  (``file_conn_keys``, ``data_stream_status``) AND explicitly declares the
  sequence/experiment provenance fields the action server needs, which were
  previously inherited from the ``Sequence``/``Experiment`` bases. Denormalised
  provenance, same serialized shape — no MRO diamond.

Behaviour (init / output-dir / split) is NOT a method here; it lives as pure
functions in :mod:`helao.framework.domain.lifecycle`.

Purity: this module imports only from ``helao.framework.models`` and
``helao.framework.support`` (``time_utils`` for the legacy-compat identity init).
"""

__all__ = ["RunSequence", "RunExperiment", "RunAction", "Action", "Experiment", "Sequence"]

from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from uuid import UUID

from pydantic import Field

from helao.framework.models.action import ActionModel, ShortActionModel
from helao.framework.models.experiment import ExperimentModel, ShortExperimentModel
from helao.framework.models.sequence import SequenceModel
from helao.framework.models.hlostatus import HloStatus
from helao.framework.support.time_utils import set_time, gen_uuid


class RunSequence(SequenceModel):
    """Runtime sequence object held by the orchestrator.

    Single-inheritance flattening of the legacy ``Sequence`` runtime wrapper.

    Attributes:
        dispatched_experiments: Experiments that have already completed within
            this sequence, retained as a running tally for status reporting.
    """

    dispatched_experiments: List[ExperimentModel] = Field(default_factory=list)

    def get_seq(self) -> "SequenceModel":
        """Return a plain :class:`SequenceModel` snapshot. Mirrors ``RunAction.get_act``."""
        return SequenceModel(**self.model_dump())


class RunExperiment(ExperimentModel):
    """Runtime experiment object held by the orchestrator.

    Single-inheritance flattening of the legacy ``Experiment`` runtime wrapper.

    Attributes:
        dispatched_actions: Actions that have already completed within this
            experiment, retained as a running tally used to rebuild
            ``samples_in``/``samples_out`` and ``files`` aggregates.
    """

    dispatched_actions: List[ActionModel] = Field(default_factory=list)

    def get_exp(self) -> "ExperimentModel":
        """Return a plain :class:`ExperimentModel` snapshot. Mirrors ``RunAction.get_act``."""
        return ExperimentModel(**self.model_dump())


class RunAction(ActionModel):
    """Runtime action object processed by an action server.

    Flattens the legacy ``Action(Experiment(Sequence), ActionModel)`` diamond to
    a single ``ActionModel`` base. The sequence/experiment provenance fields that
    used to be inherited from the ``Sequence``/``Experiment`` bases are declared
    here explicitly (denormalised, same serialized shape), together with the
    runtime-only fields the data logger and split machinery rely on.

    Attributes:
        file_conn_keys: File-connection UUIDs the data logger uses to route this
            action's output streams to disk.
        data_stream_status: Last-seen ``HloStatus`` reported through the action's
            data stream; ``None`` signals default behaviour ("no explicit status
            yet").

    Sequence provenance (from the former ``Sequence`` base):
        ``sequence_uuid``, ``sequence_name``, ``sequence_params``,
        ``sequence_label``, ``sequence_comment``, ``sequence_timestamp``,
        ``sequence_status``, ``sequence_output_dir``, ``sequence_codehash``,
        ``sequence_codepath``, ``sequence_funcname``,
        ``sequence_finished_timestamp``, ``planned_experiments``,
        ``dispatched_experiments_abbr``, ``run_sequence_parameter_variable``,
        ``from_global_seq_params``.

    Experiment provenance (from the former ``Experiment`` base):
        ``experiment_name``, ``experiment_params``, ``experiment_comment``,
        ``experiment_label``, ``experiment_status``, ``experiment_output_dir``,
        ``experiment_codehash``, ``experiment_codepath``, ``experiment_funcname``,
        ``experiment_finished_timestamp``, ``planned_actions``,
        ``dispatched_actions_abbr``, ``process_list``, ``process_order_groups``,
        ``aux_files``, ``from_global_exp_params``.

    Shared run-level provenance:
        ``initial_global_params``, ``finished_global_params``.
    """

    # --- runtime-only fields (legacy Action additions) ---
    file_conn_keys: List[UUID] = Field(default_factory=list)
    # None signals default behaviour; updated by the data logger only when it
    # finds the status in the data stream.
    data_stream_status: Optional[HloStatus] = None

    # --- sequence provenance (formerly inherited from Sequence) ---
    sequence_uuid: Optional[UUID] = None
    sequence_name: Optional[str] = None
    sequence_params: dict = Field(default_factory=dict)
    sequence_label: Optional[str] = "noLabel"
    sequence_comment: Optional[str] = None
    sequence_timestamp: Optional[datetime] = None
    sequence_status: List[HloStatus] = Field(default_factory=list)
    sequence_output_dir: Optional[Path] = None
    sequence_codehash: Optional[str] = None
    sequence_codepath: Optional[str] = None
    sequence_funcname: Optional[str] = None
    sequence_finished_timestamp: Optional[datetime] = None
    planned_experiments: List[ShortExperimentModel] = Field(default_factory=list)
    dispatched_experiments_abbr: List[ShortExperimentModel] = Field(default_factory=list)
    run_sequence_parameter_variable: Optional[List[str]] = None
    from_global_seq_params: dict = Field(default_factory=dict)

    # --- experiment provenance (formerly inherited from Experiment) ---
    experiment_name: Optional[str] = None
    experiment_params: dict = Field(default_factory=dict)
    experiment_comment: Optional[str] = None
    experiment_label: Optional[str] = None
    experiment_status: List[HloStatus] = Field(default_factory=list)
    experiment_output_dir: Optional[Path] = None
    experiment_codehash: Optional[str] = None
    experiment_codepath: Optional[str] = None
    experiment_funcname: Optional[str] = None
    experiment_finished_timestamp: Optional[datetime] = None
    planned_actions: list = Field(default_factory=list)
    dispatched_actions_abbr: List[ShortActionModel] = Field(default_factory=list)
    process_list: List[UUID] = Field(default_factory=list)
    process_order_groups: Dict[int, List[int]] = Field(default_factory=dict)
    aux_files: List[str] = Field(default_factory=list)
    from_global_exp_params: dict = Field(default_factory=dict)

    # --- runtime tallies of completed children (legacy Sequence/Experiment) ---
    dispatched_experiments: List[ExperimentModel] = Field(default_factory=list)
    dispatched_actions: List[ActionModel] = Field(default_factory=list)

    # --- shared run-level global-param snapshots ---
    initial_global_params: dict = Field(default_factory=dict)
    finished_global_params: dict = Field(default_factory=dict)

    # --- legacy-compat identity init (strangler-fig: the live legacy
    # orchestrator drives a framework RunAction through these). Ports
    # helao.helpers.premodels.Action.{init_act,get_act,get_action_dir} and the
    # Sequence/Experiment.{init_seq,init_exp,get_*_dir} it delegates to. ---

    def get_act(self) -> ActionModel:
        """Return a plain :class:`ActionModel` snapshot. Ports ``Action.get_act``."""
        return ActionModel(**self.model_dump())

    def get_sequence_dir(self) -> str:
        """``YY.WW/MMDD/HHMMSS__name__label`` (forward slashes). Ports ``Sequence.get_sequence_dir``."""
        HMS = self.sequence_timestamp.strftime("%H%M%S")
        year_week = self.sequence_timestamp.strftime("%y.%U")
        sequence_day = self.sequence_timestamp.strftime("%m%d")
        return "/".join(
            [
                year_week,
                sequence_day,
                f"{HMS}__{self.sequence_name}__{self.sequence_label}",
            ]
        )

    def init_seq(self, time_offset: float = 0, force: Optional[bool] = False) -> None:
        """Fill sequence timestamp/uuid/status/dir if unset. Ports ``Sequence.init_seq``."""
        if force is None:
            force = False
        if force or self.sequence_timestamp is None:
            self.sequence_timestamp = set_time(offset=time_offset)
        if force or self.sequence_uuid is None:
            self.sequence_uuid = gen_uuid()
        if force or not self.sequence_status:
            self.sequence_status = [HloStatus.active]
        if force or self.sequence_output_dir is None:
            self.sequence_output_dir = self.get_sequence_dir()

    def get_experiment_dir(self) -> str:
        """``sequence_dir/YYMMDD.HHMMSS__experiment_name``. Ports ``Experiment.get_experiment_dir``."""
        experiment_time = self.experiment_timestamp.strftime("%y%m%d.%H%M%S")
        return "/".join(
            [str(self.sequence_output_dir), f"{experiment_time}__{self.experiment_name}"]
        )

    def init_exp(self, time_offset: float = 0, force: Optional[bool] = False) -> None:
        """Fill experiment timestamp/uuid/status/dir if unset. Ports ``Experiment.init_exp``."""
        if force is None:
            force = False
        if force or self.experiment_timestamp is None:
            self.experiment_timestamp = set_time(offset=time_offset)
        if force or self.experiment_uuid is None:
            self.experiment_uuid = gen_uuid()
        if force or not self.experiment_status:
            self.experiment_status = [HloStatus.active]
        if force or self.experiment_output_dir is None:
            self.experiment_output_dir = self.get_experiment_dir()

    def get_action_dir(self) -> str:
        """``experiment_dir/{order}__{split}__{server}__{name}``. Ports ``Action.get_action_dir``."""
        return "/".join(
            [
                str(self.experiment_output_dir),
                f"{self.orch_submit_order}__"
                f"{self.action_split}__"
                f"{self.action_server.server_name}__{self.action_name}",
            ]
        )

    def init_act(self, time_offset: float = 0, force: Optional[bool] = False) -> None:
        """Initialise action identity, promoting to a manual run if unparented.

        Ports ``Action.init_act``: with no parent sequence/experiment timestamps
        the action is flagged manual and synthetic seq/exp identities are
        generated; then action timestamp/uuid/status/output_dir are filled.
        """
        if self.sequence_timestamp is None or self.experiment_timestamp is None:
            self.manual_action = True
            self.access = "manual"
            manual_suffix = self.action_name
            self.sequence_name = f"seq--{manual_suffix}"
            self.sequence_label = "manual"
            self.init_seq(time_offset=time_offset)
            self.experiment_name = f"exp--{manual_suffix}"
            self.init_exp(time_offset=time_offset)

        if force or self.action_timestamp is None:
            self.action_timestamp = set_time(offset=time_offset)
        if force or self.action_uuid is None:
            self.action_uuid = gen_uuid()
        if force or not self.action_status:
            self.action_status = [HloStatus.active]
        if force or self.action_output_dir is None:
            self.action_output_dir = self.get_action_dir()


# --- legacy-name aliases for HTE symbol reconciliation ---
Action = RunAction
Experiment = RunExperiment
Sequence = RunSequence
