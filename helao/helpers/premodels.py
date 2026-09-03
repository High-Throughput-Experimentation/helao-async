"""Queue-side schemas for sequences, experiments and actions.

Extends the bare ``helao.core.models`` pydantic types with the runtime
behaviour the orchestrator needs while building and dispatching work:

* ``Sequence``: an ``ExperimentModel`` bag with a ``dispatched_experiments``
  tally and helpers that initialise timestamp/uuid/output-dir fields.
* ``Experiment`` (subclasses ``Sequence``): same idea one level down, with a
  ``dispatched_actions`` tally and logic that rolls completed actions back
  into ``samples_in``/``samples_out``/``files``.
* ``Action`` (subclasses ``Experiment``): a single action that can be
  auto-promoted to a manual sequence/experiment when launched standalone.
* ``ActionPlanMaker`` / ``ExperimentPlanMaker``: helpers used inside
  experiment- and sequence-library functions to register planned actions
  and experiments on the current frame.
"""

__all__ = ["Sequence", "Experiment", "Action", "ActionPlanMaker", "ExperimentPlanMaker"]

import inspect
import os
from collections import defaultdict
from contextvars import ContextVar
from copy import deepcopy
from socket import gethostname
from typing import Optional
from uuid import UUID

from pydantic import Field

from helao.core.models.action import ActionModel, ShortActionModel
from helao.core.models.action_start_condition import ActionStartCondition
from helao.core.models.experiment import (
    ExperimentModel,
    ShortExperimentModel,
)
from helao.core.models.hlostatus import HloStatus
from helao.core.models.machine import MachineModel
from helao.core.models.sequence import SequenceModel
from helao.helpers import helao_logging as logging

from .time_utils import gen_uuid, set_time

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
HOST = gethostname()

#: Active :class:`Experiment` for the currently executing experiment-library
#: function. The ``@experiment`` decorator (see
#: ``helao.helpers.lib_decorators``) sets this before invoking a library
#: function so the function body no longer needs to declare an
#: ``experiment: Experiment`` parameter and so :class:`ActionPlanMaker` can
#: recover the parent experiment without scanning the caller's frame.
EXPERIMENT_CTX: "ContextVar[Optional[Experiment]]" = ContextVar(
    "helao_active_experiment", default=None
)


class Sequence(SequenceModel):
    """Runtime sequence object held by the orchestrator.

    Augments ``SequenceModel`` with a live tally of completed experiments
    plus helpers that assign timestamps, UUIDs and output directories on
    demand.

    Attributes:
        dispatched_experiments: Experiments that have already completed
            within this sequence, retained for status reporting.
    """

    # not in SequenceModel:
    dispatched_experiments: list[ExperimentModel] = (
        []
    )  # running tally of completed experiments

    def __repr__(self) -> str:
        """Return ``<sequence_name:NAME>`` for log lines."""
        return f"<sequence_name:{self.sequence_name}>"

    def __str__(self) -> str:
        """Return ``sequence_name:NAME``."""
        return f"sequence_name:{self.sequence_name}"

    def get_seq(self) -> SequenceModel:
        """Return a plain ``SequenceModel`` snapshot of this sequence.

        The returned model carries ``dispatched_experiments_abbr`` populated
        from ``ShortExperimentModel`` views of the completed experiments.
        """
        seq = SequenceModel.model_validate(self.model_dump())
        seq.dispatched_experiments_abbr = [
            ShortExperimentModel.model_validate(exp.model_dump())
            for exp in self.dispatched_experiments
        ]
        # either we have a plan at the beginning or not
        # don't add it later from the dispatched_experiments
        # seq.planned_experiments = [ShortExperimentModel(**exp.model_dump()) for exp in self.dispatched_experiments]
        return seq

    def init_seq(self, time_offset: float = 0, force: Optional[bool] = False):
        """Populate timestamp, UUID, status and output dir if not already set.

        Args:
            time_offset: Seconds to add to the wall clock when generating
                ``sequence_timestamp``.
            force: When truthy, overwrite any pre-existing values.
        """
        if force is None:
            force = False
        if force or self.sequence_timestamp is None:
            self.sequence_timestamp = set_time(offset=time_offset)
        if force or self.sequence_uuid is None:
            self.sequence_uuid = gen_uuid()
        if force or not self.sequence_status:
            self.reset_sequence_status(HloStatus.active)
        if force or self.sequence_output_dir is None:
            self.sequence_output_dir = self.get_sequence_dir()

    def get_sequence_dir(self) -> str:
        """Build the relative output directory for this sequence.

        Layout is ``YY.WW/MMDD/HHMMSS__name__label[-plate-serial[-sampleno]]``
        and is always returned with forward slashes.
        """
        HMS = self.sequence_timestamp.strftime("%H%M%S")
        year_week = self.sequence_timestamp.strftime("%y.%U")
        sequence_day = self.sequence_timestamp.strftime("%m%d")
        plate = self.sequence_params.get("plate_id", "")
        smpno = self.sequence_params.get("plate_sample_no_list", [])
        append_plate = ""
        if self.sequence_label is None:
            self.sequence_label = "noLabel"
        if plate:
            serial = f"{plate}{str(sum([int(x) for x in str(plate)]) % 10)}"
            if f"-{serial}" not in self.sequence_label:
                if len(smpno) == 1:
                    append_plate = f"-{serial}-{smpno[0]}"
                else:
                    append_plate = f"-{serial}"

        return os.path.join(
            year_week,
            sequence_day,
            f"{HMS}__{self.sequence_name}__{self.sequence_label}{append_plate}",
        ).replace(r"\\", "/")


class Experiment(Sequence, ExperimentModel):
    """Runtime experiment object held by the orchestrator.

    Combines ``Sequence`` and ``ExperimentModel`` so the same instance can
    track its parent sequence's metadata and its own action queue.

    Attributes:
        dispatched_actions: Actions that have already completed within this
            experiment, used to rebuild ``samples_in``/``samples_out`` and
            ``files`` aggregates.
    """

    # not in ExperimentModel, dispatched_actions is a list of completed ActionModels:
    dispatched_actions: list[ActionModel] = []

    def __repr__(self) -> str:
        """Return ``<experiment_name:NAME>`` for log lines."""
        return f"<experiment_name:{self.experiment_name}>"

    def __str__(self) -> str:
        """Return ``experiment_name:NAME``."""
        return f"experiment_name:{self.experiment_name}"

    def init_exp(self, time_offset: float = 0, force: Optional[bool] = False):
        """Populate experiment timestamp, UUID, status and output dir if unset.

        Args:
            time_offset: Seconds to add to the wall clock when generating
                ``experiment_timestamp``.
            force: When truthy, overwrite any pre-existing values.
        """
        if force is None:
            force = False
        if force or self.experiment_timestamp is None:
            self.experiment_timestamp = set_time(offset=time_offset)
        if force or self.experiment_uuid is None:
            self.experiment_uuid = gen_uuid()
        if force or not self.experiment_status:
            self.reset_experiment_status(HloStatus.active)
        if force or self.experiment_output_dir is None:
            self.experiment_output_dir = self.get_experiment_dir()

    def get_experiment_dir(self) -> str:
        """Return ``sequence_dir/YYMMDD.HHMMSS__experiment_name``."""
        experiment_time = self.experiment_timestamp.strftime("%y%m%d.%H%M%S")
        sequence_dir = self.sequence_output_dir
        return os.path.join(
            str(sequence_dir),
            f"{experiment_time}__{self.experiment_name}",
        ).replace(r"\\", "/")

    def get_exp(self) -> ExperimentModel:
        """Return a plain ``ExperimentModel`` snapshot with aggregated actions.

        Builds an ``ExperimentModel`` from ``self.model_dump()`` and folds in
        the contents of ``dispatched_actions`` via
        ``_experiment_update_from_actlist``.
        """
        exp = ExperimentModel.model_validate(self.model_dump())
        # now add all actions
        self._experiment_update_from_actlist(exp=exp)
        return exp

    def _experiment_update_from_actlist(self, exp: ExperimentModel):
        """Rebuild ``exp``'s samples and files from ``dispatched_actions``.

        Resets ``exp.samples_in``, ``exp.samples_out`` and ``exp.files``,
        then walks every dispatched action and re-folds its samples and
        files into ``exp`` while preserving per-sample ``action_uuid`` lists.
        """
        # reset sample list of exp
        exp.samples_in = []
        exp.samples_out = []
        # reset file list
        exp.files = []

        if self.dispatched_actions is None:
            self.dispatched_actions = []

        for actm in self.dispatched_actions:
            LOGGER.debug(
                f"updating exp with act {actm.action_name} on {actm.action_server.disp_name()}, uuid:{actm.action_uuid}"
            )

            exp.dispatched_actions_abbr.append(
                ShortActionModel.model_validate(actm.model_dump())
            )
            for file in actm.files:
                if file.action_uuid is None:
                    file.action_uuid = actm.action_uuid
                exp.files.append(file)

            for _sample in actm.samples_in:
                identical = self._check_sample(
                    new_sample=_sample, sample_list=exp.samples_in
                )
                if identical is None:
                    _sample.action_uuid = []
                    _sample.action_uuid.append(actm.action_uuid)
                    exp.samples_in.append(_sample)
                else:
                    exp.samples_in[identical].action_uuid.append(actm.action_uuid)

            for _sample in actm.samples_out:
                identical = self._check_sample(
                    new_sample=_sample, sample_list=exp.samples_out
                )
                if identical is None:
                    _sample.action_uuid = []
                    _sample.action_uuid.append(actm.action_uuid)
                    exp.samples_out.append(_sample)
                else:
                    exp.samples_out[identical].action_uuid.append(actm.action_uuid)

        self._check_sample_duplicates(exp=exp)

    def _check_sample(self, new_sample, sample_list):
        """Return the index of ``new_sample`` inside ``sample_list`` if present.

        Equality ignores ``action_uuid`` so the same sample reported by
        multiple actions can be matched and merged.
        """
        for idx, sample in enumerate(sample_list):
            tmp_sample = deepcopy(sample)
            tmp_sample.action_uuid = []
            identical = tmp_sample == new_sample
            if identical:
                return idx
        return None

    def _check_sample_duplicates(self, exp: ExperimentModel):
        """Index samples in ``exp`` by global label (currently informational)."""
        out_labels = defaultdict(list)
        in_labels = defaultdict(list)
        for i, sample in enumerate(exp.samples_out):
            out_labels[sample.get_global_label()].append(i)
        for i, sample in enumerate(exp.samples_in):
            in_labels[sample.get_global_label()].append(i)

        # isunique = True
        # for key, locs in in_labels.items():
        #     if len(locs) > 1:
        #        isunique = False

        # if not isunique:
        #     print_message(
        #         LOGGER,
        #         "experiment",
        #         "\n----------------------------------"
        #         "\nDuplicate but 'unique' samples."
        #         "\nExperiment needs to be split."
        #         "\n----------------------------------",
        #         error=True,
        #     )
        #     LOGGER.error(f"samples_in labels: {in_labels}")
        #     LOGGER.error(f"samples_out labels: {out_labels}")


# when a server is working on an action it is important to
# see what experiment the action belongs to. This turns the
# action model into an instance of an Action
class Action(Experiment, ActionModel):
    """Runtime action object combining sequence, experiment and action data.

    Attributes:
        file_conn_keys: File-connection UUIDs the data logger uses to route
            this action's output streams to disk.
        data_stream_status: Last-seen ``HloStatus`` reported through the
            action's data stream; ``None`` means "no explicit status yet".
    """

    # internal
    file_conn_keys: list[UUID] = Field(default=[])
    # flag for dataLOGGER
    # None will signal default behaviour as before
    # will be updated by data LOGGER only if it finds the status
    # in the data stream
    data_stream_status: Optional[HloStatus] = None

    def __repr__(self) -> str:
        """Return ``<action_name:NAME>`` for log lines."""
        return f"<action_name:{self.action_name}>"

    def __str__(self) -> str:
        """Return ``action_name:NAME``."""
        return f"action_name:{self.action_name}"

    def get_act(self) -> ActionModel:
        """Return a plain ``ActionModel`` snapshot of this action."""
        return ActionModel.model_validate(self.model_dump())

    def init_act(self, time_offset: float = 0, force: Optional[bool] = False):
        """Initialise action identity, promoting it to a manual run if needed.

        When the action has no parent sequence/experiment timestamps it is
        flagged ``manual_action`` with ``access="manual"`` and synthetic
        sequence/experiment names are generated. Action-level timestamp,
        UUID, status and output directory are then filled in.

        Args:
            time_offset: Seconds added to the wall clock when generating
                timestamps.
            force: When truthy, overwrite pre-existing action-level values.
        """
        if self.sequence_timestamp is None or self.experiment_timestamp is None:
            self.manual_action = True
            self.access = "manual"
            # -- (1) -- set missing sequence parameters
            # manual_suffix = f"{self.action_server.server_name}-{self.action_name}"
            manual_suffix = self.action_name
            self.sequence_name = f"seq--{manual_suffix}"
            self.sequence_label = "manual"
            # if self.action_params.get("comment", ""):
            #     self.sequence_label = self.action_params["comment"]
            self.init_seq(time_offset=time_offset)
            # -- (2) -- set missing experiment parameters
            self.experiment_name = f"exp--{manual_suffix}"
            self.init_exp(time_offset=time_offset)

        if force or self.action_timestamp is None:
            self.action_timestamp = set_time(offset=time_offset)
        if force or self.action_uuid is None:
            self.action_uuid = gen_uuid()
        if force or not self.action_status:
            self.reset_action_status(HloStatus.active)
        if force or self.action_output_dir is None:
            self.action_output_dir = self.get_action_dir()

    def get_action_dir(self) -> str:
        """Return the relative output directory for this action.

        Layout is
        ``experiment_dir/{orch_submit_order}__{action_split}__{server_name}__{action_name}``.
        """
        experiment_dir = self.experiment_output_dir
        return "/".join(
            [
                str(experiment_dir),
                f"{self.orch_submit_order}__"
                f"{self.action_split}__"
                f"{self.action_server.server_name}__{self.action_name}",
            ]
        )


class ActionPlanMaker:
    """Helper used inside experiment-library functions to plan actions.

    Construct an ``ActionPlanMaker`` at the top of an experiment function;
    it reads the parent :class:`Experiment` from :data:`EXPERIMENT_CTX` (set by
    the ``@experiment`` decorator), falling back to scanning the caller's frame
    for an ``Experiment`` argument for any function not routed through the
    decorator. It exposes every other caller argument plus every
    ``experiment_params`` entry on ``self.pars`` (string ``"true"``/``"false"``
    values are coerced to booleans). Calls to ``add`` append fully-built
    ``Action`` objects to ``planned_actions``.

    Attributes:
        expname: Name of the enclosing experiment function.
        planned_actions: Actions queued up via ``add``/``add_actions``.
        pars: Object whose attributes mirror the merged parameter set.
    """

    def __init__(self):
        """Capture the enclosing frame and build ``self.pars`` from it."""
        frame = inspect.currentframe().f_back
        _args, _varargs, _keywords, _locals = inspect.getargvalues(frame)
        self.expname = frame.f_code.co_name
        self._experiment = None
        self.planned_actions = []
        self.pars = self._C()

        exp_paramdict = {}

        LOGGER.debug(f"args {_args}")
        LOGGER.debug(f"locals {_locals}")

        # prefer the Experiment supplied by the @experiment decorator's context
        ctx_experiment = EXPERIMENT_CTX.get(None)
        if ctx_experiment is not None:
            self._experiment = deepcopy(ctx_experiment)

        # collect the caller's other params, and (for any function not routed
        # through the decorator) fall back to discovering the Experiment among
        # the declared arguments
        for arg in _args:
            argparam = _locals.get(arg, None)
            if isinstance(argparam, Experiment):
                if self._experiment is None:
                    LOGGER.info(
                        f"{self.expname}: found Experiment BaseModel under parameter '{arg}'"
                    )
                    self._experiment = deepcopy(argparam)
                # an Experiment-typed argument is never exposed as a param
            else:
                exp_paramdict.update({arg: argparam})
        LOGGER.debug(f"exp_paramdict {exp_paramdict}")

        # check if an Experiment was detected
        if self._experiment is None:
            LOGGER.warning(
                f"{self.expname}: warning: no Experiment BaseModel was found by ActionPlanMaker, using blank Experiment."
            )
            self._experiment = Experiment()

        LOGGER.debug(
            f"experiment.experiment_params {self._experiment.experiment_params}"
        )

        # add all experiment_params under self.pars
        if self._experiment.experiment_params is not None:
            for key, val in self._experiment.experiment_params.items():
                if isinstance(val, str):
                    if val.lower() == "true":
                        val = True
                    elif val.lower() == "false":
                        val = False
                setattr(self.pars, key, val)

        # add all other params in exp_paramdict which were
        # not included in experiment_params to self.pars
        # for key, val in _locals.items():
        for key, val in exp_paramdict.items():
            if key not in self._experiment.experiment_params.keys():
                LOGGER.info(
                    f"{self.expname}: local var '{key}' not found in Experiment, adding it to self.pars"
                )
                if isinstance(val, str):
                    if val.lower() == "true":
                        val = True
                    elif val.lower() == "false":
                        val = False
                setattr(self.pars, key, val)

        LOGGER.info(
            f"{self.expname}: params in self.pars are:" f" {vars(self.pars)}",
        )

    class _C:
        """Bag object that holds merged experiment/local parameters as attributes."""

        pass

    def add_actions(self, planned_action_list: list):
        """Append already-constructed ``Action`` objects to the plan.

        Args:
            planned_action_list: Iterable of ``Action`` instances.
        """
        for action in planned_action_list:
            self.planned_actions.append(action)

    def add(
        self,
        action_server: dict | MachineModel | str,
        action_name: str,
        action_params: dict,
        start_condition: ActionStartCondition = ActionStartCondition.wait_for_all,
        to_global_params: dict | list = {},
        from_global_act_params: dict = {},
        **kwargs,
    ):
        """Build a new ``Action`` from the current experiment and queue it.

        Args:
            action_server: Target action server, given as a ``MachineModel``,
                a server-key string, or a pre-built ``as_dict()`` payload.
            action_name: Action endpoint name on the server.
            action_params: Parameter dictionary forwarded to the action.
            start_condition: Scheduling condition for the action.
            to_global_params: Names of action outputs to copy into the
                orchestrator's global parameter store.
            from_global_act_params: Mapping of global parameter names to
                inject into ``action_params`` at dispatch time.
            **kwargs: Additional fields merged into the action dict (notably
                ``run_use``, which defaults to the experiment's value).
        """
        action_dict = self._experiment.as_dict()
        if isinstance(action_server, MachineModel):
            action_server = action_server.as_dict()
        elif isinstance(action_server, str):
            action_server = MachineModel(
                server_name=action_server, machine_name=HOST
            ).as_dict()
        action_dict.update(
            {
                "action_server": action_server,
                "action_name": action_name,
                "action_params": action_params,
                "start_condition": start_condition,
                "to_global_params": to_global_params,
                "from_global_act_params": from_global_act_params,
            }
        )
        action_dict.update(kwargs)
        if "run_use" not in kwargs:
            action_dict["run_use"] = self._experiment.run_use
        self.planned_actions.append(Action.model_validate(action_dict))

    @property
    def experiment(self) -> Experiment:
        """Return the captured experiment with ``planned_actions`` attached."""
        exp = self._experiment
        exp.planned_actions = self.planned_actions
        return exp


class ExperimentPlanMaker:
    """Collector that lets a sequence-library function queue experiments.

    Attributes:
        planned_experiments: ``ShortExperimentModel`` entries queued via ``add``.
    """

    def __init__(
        self,
    ):
        """Initialise an empty experiment plan."""
        self.planned_experiments = []

    def add(
        self, experiment_name, experiment_params, from_global_exp_params={}, **kwargs
    ):
        """Append a ``ShortExperimentModel`` to the plan.

        Args:
            experiment_name: Name of the experiment library function.
            experiment_params: Parameter dictionary for the experiment.
            from_global_exp_params: Mapping of global parameter names to
                inject into ``experiment_params`` at runtime.
            **kwargs: Additional fields forwarded to ``ShortExperimentModel``.
        """
        self.planned_experiments.append(
            ShortExperimentModel(
                experiment_name=experiment_name,
                experiment_params=experiment_params,
                from_global_exp_params=from_global_exp_params,
                **kwargs,
            ),
        )
