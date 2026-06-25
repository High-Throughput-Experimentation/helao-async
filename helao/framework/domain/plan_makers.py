"""Author-facing plan-maker helpers for experiment/sequence libraries.

These two helpers are used *inside* experiment- and sequence-library functions
to register the work a function plans to perform:

* :class:`ActionPlanMaker` — constructed at the top of an experiment-library
  function. It recovers the enclosing :class:`RunExperiment` (from
  :data:`EXPERIMENT_CTX`, set by the ``@experiment`` decorator, falling back to
  scanning the caller's frame for a ``RunExperiment`` argument), exposes every
  other caller argument plus every ``experiment_params`` entry on ``self.pars``
  (string ``"true"``/``"false"`` values coerced to booleans), and builds
  :class:`RunAction` objects via :meth:`ActionPlanMaker.add`.
* :class:`ExperimentPlanMaker` — a thin collector used inside sequence-library
  functions to queue :class:`ShortExperimentModel` entries via
  :meth:`ExperimentPlanMaker.add`.

This is a near-verbatim port of ``helao.helpers.premodels``'s
``ActionPlanMaker``/``ExperimentPlanMaker`` onto the framework's pure
run-models. Method names, signatures, and semantics are preserved because they
are author-facing.

Purity: this module imports only from ``helao.framework.models`` /
``helao.framework.domain`` / ``helao.framework.support`` and stdlib
(``inspect``/``contextvars`` capture caller frames only — no I/O).
"""

__all__ = ["EXPERIMENT_CTX", "ActionPlanMaker", "ExperimentPlanMaker"]

import inspect
from contextvars import ContextVar
from copy import deepcopy
from socket import gethostname
from typing import Optional

from helao.framework.models.action_start_condition import ActionStartCondition
from helao.framework.models.experiment import ShortExperimentModel
from helao.framework.models.machine import MachineModel
from helao.framework.domain.run_models import RunAction, RunExperiment

from helao.framework.support import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
HOST = gethostname()

#: Active :class:`RunExperiment` for the currently executing experiment-library
#: function. The ``@experiment`` decorator sets this before invoking a library
#: function so the function body no longer needs to declare an
#: ``experiment: RunExperiment`` parameter and so :class:`ActionPlanMaker` can
#: recover the parent experiment without scanning the caller's frame.
EXPERIMENT_CTX: "ContextVar[Optional[RunExperiment]]" = ContextVar(
    "helao_active_experiment", default=None
)


class ActionPlanMaker:
    """Helper used inside experiment-library functions to plan actions.

    Construct an ``ActionPlanMaker`` at the top of an experiment function; it
    reads the parent :class:`RunExperiment` from :data:`EXPERIMENT_CTX` (set by
    the ``@experiment`` decorator), falling back to scanning the caller's frame
    for a ``RunExperiment`` argument for any function not routed through the
    decorator. It exposes every other caller argument plus every
    ``experiment_params`` entry on ``self.pars`` (string ``"true"``/``"false"``
    values are coerced to booleans). Calls to ``add`` append fully-built
    :class:`RunAction` objects to ``planned_actions``.

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

        # prefer the RunExperiment supplied by the @experiment decorator's context
        ctx_experiment = EXPERIMENT_CTX.get(None)
        if ctx_experiment is not None:
            self._experiment = deepcopy(ctx_experiment)

        # collect the caller's other params, and (for any function not routed
        # through the decorator) fall back to discovering the RunExperiment among
        # the declared arguments
        for arg in _args:
            argparam = _locals.get(arg, None)
            if isinstance(argparam, RunExperiment):
                if self._experiment is None:
                    LOGGER.info(
                        f"{self.expname}: found RunExperiment BaseModel under parameter '{arg}'"
                    )
                    self._experiment = deepcopy(argparam)
                # a RunExperiment-typed argument is never exposed as a param
            else:
                exp_paramdict.update({arg: argparam})
        LOGGER.debug(f"exp_paramdict {exp_paramdict}")

        # check if a RunExperiment was detected
        if self._experiment is None:
            LOGGER.warning(
                f"{self.expname}: warning: no RunExperiment BaseModel was found by ActionPlanMaker, using blank RunExperiment."
            )
            self._experiment = RunExperiment()

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
        for key, val in exp_paramdict.items():
            if key not in self._experiment.experiment_params.keys():
                LOGGER.info(
                    f"{self.expname}: local var '{key}' not found in RunExperiment, adding it to self.pars"
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
        """Append already-constructed :class:`RunAction` objects to the plan.

        Args:
            planned_action_list: Iterable of :class:`RunAction` instances.
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
        """Build a new :class:`RunAction` from the current experiment and queue it.

        Args:
            action_server: Target action server, given as a :class:`MachineModel`,
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
        # RunAction.orchestrator is non-Optional (default_factory=MachineModel).
        # ExperimentModel/RunExperiment carry orchestrator=None when the experiment
        # was built outside a live orch (e.g. headless test or pre-dispatch staging).
        # Passing None explicitly overrides the default_factory; drop the key so
        # Pydantic uses the factory instead.
        if action_dict.get("orchestrator") is None:
            action_dict.pop("orchestrator", None)
        self.planned_actions.append(RunAction(**action_dict))

    @property
    def experiment(self) -> RunExperiment:
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
        """Append a :class:`ShortExperimentModel` to the plan.

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
