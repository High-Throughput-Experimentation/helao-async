"""schema.py
Standard classes for experiment queue objects.

"""

__all__ = ["Sequence", "Experiment", "Action", "ActionPlanMaker", "ExperimentPlanMaker"]

import os
import inspect
from copy import deepcopy
from typing import Optional
from pydantic import Field
from typing import List
from collections import defaultdict
from uuid import UUID

from helao.helpers.gen_uuid import gen_uuid
from helao.helpers.set_time import set_time
from helao.core.models.action import ActionModel, ShortActionModel
from helao.core.models.experiment import (
    ExperimentModel,
    ShortExperimentModel,
)
from helao.core.models.sequence import SequenceModel
from helao.core.models.hlostatus import HloStatus
from helao.core.models.action_start_condition import ActionStartCondition

from helao.helpers import helao_logging as logging

if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER


class Sequence(SequenceModel):
    "Experiment grouping class."
    # not in SequenceModel:
    completed_experiments: List[ExperimentModel] = (
        []
    )  # running tally of completed experiments

    def __repr__(self):
        return f"<sequence_name:{self.sequence_name}>"

    def __str__(self):
        return f"sequence_name:{self.sequence_name}"

    def get_seq(self):
        seq = SequenceModel(**self.model_dump())
        seq.completed_experiments_abbr = [
            ShortExperimentModel(**exp.model_dump())
            for exp in self.completed_experiments
        ]
        # either we have a plan at the beginning or not
        # don't add it later from the completed_experiments
        # seq.planned_experiments = [ExperimentTemplate(**exp.model_dump()) for exp in self.completed_experiments]
        return seq

    def init_seq(self, time_offset: float = 0, force: Optional[bool] = False):
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

    def get_sequence_dir(self):
        HMS = self.sequence_timestamp.strftime("%H%M%S")
        year_week = self.sequence_timestamp.strftime("%y.%U")
        sequence_day = self.sequence_timestamp.strftime("%Y%m%d")
        plate = self.sequence_params.get("plate_id", "")
        if plate:
            serial = f"{plate}{str(sum([int(x) for x in str(plate)]) % 10)}"
            append_plate = f"-{serial}"
        else:
            append_plate = ""

        return os.path.join(
            year_week,
            sequence_day,
            f"{HMS}__{self.sequence_name}__{self.sequence_label}{append_plate}",
        ).replace(r"\\", "/")


class Experiment(Sequence, ExperimentModel):
    "Sample-action grouping class."
    # not in ExperimentModel, completed_actions is a list of completed ActionModels:
    completed_actions: List[ActionModel] = []
    # not in ExperimentModel, planned_actions is a list of Actions to be executed:
    planned_actions: list = []

    def __repr__(self):
        return f"<experiment_name:{self.experiment_name}>"

    def __str__(self):
        return f"experiment_name:{self.experiment_name}"

    def init_exp(self, time_offset: float = 0, force: Optional[bool] = False):
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

    def get_experiment_dir(self):
        """accepts action or experiment object"""
        experiment_time = self.experiment_timestamp.strftime("%Y%m%d.%H%M%S")
        sequence_dir = self.get_sequence_dir()
        return os.path.join(
            sequence_dir,
            f"{experiment_time}__{self.experiment_name}",
        ).replace(r"\\", "/")

    def get_exp(self):
        exp = ExperimentModel(**self.model_dump())
        # now add all actions
        self._experiment_update_from_actlist(exp=exp)
        return exp

    def _experiment_update_from_actlist(self, exp: ExperimentModel):
        # reset sample list of exp
        exp.samples_in = []
        exp.samples_out = []
        # reset file list
        exp.files = []

        if self.completed_actions is None:
            self.completed_actions = []

        for actm in self.completed_actions:
            LOGGER.info(
                f"updating exp with act {actm.action_name} on {actm.action_server.disp_name()}, uuid:{actm.action_uuid}"
            )

            exp.action_list.append(ShortActionModel(**actm.model_dump()))
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
        for idx, sample in enumerate(sample_list):
            tmp_sample = deepcopy(sample)
            tmp_sample.action_uuid = []
            identical = tmp_sample == new_sample
            if identical:
                return idx
        return None

    def _check_sample_duplicates(self, exp: ExperimentModel):
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


class Action(Experiment, ActionModel):
    "Sample-action identifier class."
    # internal
    file_conn_keys: List[UUID] = Field(default=[])
    # flag for dataLOGGER
    # None will signal default behaviour as before
    # will be updated by data LOGGER only if it finds the status
    # in the data stream
    data_stream_status: Optional[HloStatus] = None

    def __repr__(self):
        return f"<action_name:{self.action_name}>"

    def __str__(self):
        return f"action_name:{self.action_name}"

    def get_act(self):
        return ActionModel(**self.model_dump())

    def init_act(self, time_offset: float = 0, force: Optional[bool] = False):
        if self.sequence_timestamp is None or self.experiment_timestamp is None:
            self.manual_action = True
            self.access = "manual"
            # -- (1) -- set missing sequence parameters
            manual_suffix = f"{self.action_server.server_name}-{self.action_name}"
            self.sequence_name = f"mseq-ACT_{manual_suffix}"
            if self.action_params.get("comment", ""):
                self.sequence_label = self.action_params["comment"]
            self.init_seq(time_offset=time_offset)
            # -- (2) -- set missing experiment parameters
            self.experiment_name = f"mexp-ACT_{manual_suffix}"
            self.init_exp(time_offset=time_offset)

        if force or self.action_timestamp is None:
            self.action_timestamp = set_time(offset=time_offset)
        if force or self.action_uuid is None:
            self.action_uuid = gen_uuid()
        if force or not self.action_status:
            self.action_status = [HloStatus.active]
        if force or self.action_output_dir is None:
            self.action_output_dir = self.get_action_dir()

    def get_action_dir(self):
        experiment_dir = self.get_experiment_dir()
        return "/".join(
            [
                experiment_dir,
                f"{self.orch_submit_order}__"
                f"{self.action_split}__"
                f"{self.action_server.server_name}__{self.action_name}",
            ]
        )


class ActionPlanMaker:
    def __init__(self):
        frame = inspect.currentframe().f_back
        _args, _varargs, _keywords, _locals = inspect.getargvalues(frame)
        self.expname = frame.f_code.co_name
        self._experiment = None
        self.action_list = []
        self.pars = self._C()

        exp_paramdict = {}

        LOGGER.debug(f"args {_args}")
        LOGGER.debug(f"locals {_locals}")

        # find the Experiment Basemodel
        # and add all other params to a dict
        for arg in _args:
            argparam = _locals.get(arg, None)
            if isinstance(argparam, Experiment):
                if self._experiment is None:
                    LOGGER.info(
                        f"{self.expname}: found Experiment BaseModel under parameter '{arg}'"
                    )
                    self._experiment = deepcopy(argparam)
                else:
                    LOGGER.error(
                        f"{self.expname}: critical error: found another Experiment BaseModel under parameter '{arg}', skipping it"
                    )
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
        pass

    def add_action(self, action_dict: dict):
        new_action_dict = self._experiment.as_dict()
        new_action_dict.update(action_dict)
        self.action_list.append(Action(**new_action_dict))

    def add_action_list(self, action_list: list):
        for action in action_list:
            self.action_list.append(action)

    def add(
        self,
        action_server: dict,
        action_name: str,
        action_params: dict,
        start_condition: ActionStartCondition = ActionStartCondition.wait_for_all,
        **kwargs,
    ):
        """Shorthand add_action()."""
        action_dict = self._experiment.as_dict()
        action_dict.update(
            {
                "action_server": action_server,
                "action_name": action_name,
                "action_params": action_params,
                "start_condition": start_condition,
            }
        )
        action_dict.update(kwargs)
        self.action_list.append(Action(**action_dict))

    @property
    def experiment(self):
        exp = self._experiment
        exp.planned_actions = self.action_list
        return exp


class ExperimentPlanMaker:
    def __init__(
        self,
    ):
        self.planned_experiments = []

    def add_experiment(self, selected_experiment, experiment_params, **kwargs):
        self.planned_experiments.append(
            Experiment(
                experiment_name=selected_experiment,
                experiment_params=experiment_params,
                **kwargs,
            ),
        )
