""" schema.py
Standard classes for experiment queue objects.

"""

__all__ = ["Sequence", "Experiment", "Action", "ActionPlanMaker", "ExperimentPlanMaker"]

import os
import inspect
from copy import deepcopy
from pathlib import Path
from typing import Optional, Union
from pydantic import Field
from typing import List
from collections import defaultdict
from uuid import UUID

from helao.helpers.print_message import print_message
from helao.helpers.gen_uuid import gen_uuid
from helao.helpers.set_time import set_time
from helaocore.models.action import ActionModel, ShortActionModel
from helaocore.models.experiment import (
    ExperimentModel,
    ShortExperimentModel,
    ExperimentTemplate,
)
from helaocore.models.sequence import SequenceModel
from helaocore.models.hlostatus import HloStatus
from helaocore.models.action_start_condition import ActionStartCondition

# from helaocore.models.error import ErrorCodes


class Sequence(SequenceModel):
    "Experiment grouping class."

    # not in SequenceModel:
    globalseq_params: Optional[dict] = Field(default_factory=dict)
    experimentmodel_list: List[ExperimentModel] = Field(default_factory=list)

    def __repr__(self):
        return f"<sequence_name:{self.sequence_name}>"

    def __str__(self):
        return f"sequence_name:{self.sequence_name}"

    def get_seq(self):
        seq = SequenceModel(**self.dict())
        seq.experiment_list = [
            ShortExperimentModel(**exp.dict()) for exp in self.experimentmodel_list
        ]
        # either we have a plan at the beginning or not
        # don't add it later from the experimentmodel_list
        # seq.experiment_plan_list = [ExperimentTemplate(**exp.dict()) for exp in self.experimentmodel_list]
        return seq

    def init_seq(self, time_offset: float = 0, force: Optional[bool] = None):
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
        )


class Experiment(Sequence, ExperimentModel):
    "Sample-action grouping class."

    # not in ExperimentModel:
    globalexp_params: Optional[dict] = Field(default_factory=dict)
    actionmodel_list: List[ActionModel] = Field(default_factory=list)

    def __repr__(self):
        return f"<experiment_name:{self.experiment_name}>"

    def __str__(self):
        return f"experiment_name:{self.experiment_name}"

    def init_exp(self, time_offset: float = 0, force: Optional[bool] = None):
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
        experiment_time = self.experiment_timestamp.strftime("%Y%m%d.%H%M%S%f")
        sequence_dir = self.get_sequence_dir()
        return os.path.join(
            sequence_dir,
            f"{experiment_time}__{self.experiment_name}",
        )

    def get_exp(self):
        exp = ExperimentModel(**self.dict())
        # now add all actions
        self._experiment_update_from_actlist(exp=exp)
        return exp

    def _experiment_update_from_actlist(self, exp: ExperimentModel):
        # reset sample list of exp
        exp.samples_in = []
        exp.samples_out = []
        # reset file list
        exp.files = []

        if self.actionmodel_list is None:
            self.actionmodel_list = []

        for actm in self.actionmodel_list:
            print_message(
                {},
                "experiment",
                f"updating exp with act {actm.action_name} on "
                f"{actm.action_server.disp_name()}, uuid:{actm.action_uuid}",
                info=True,
            )

            exp.action_list.append(ShortActionModel(**actm.dict()))
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
        #         {},
        #         "experiment",
        #         "\n----------------------------------"
        #         "\nDuplicate but 'unique' samples."
        #         "\nExperiment needs to be split."
        #         "\n----------------------------------",
        #         error=True,
        #     )
        #     print_message({}, "experiment", f"samples_in labels: {in_labels}", error=True)
        #     print_message({}, "experiment", f"samples_out labels: {out_labels}", error=True)


class Action(Experiment, ActionModel):
    "Sample-action identifier class."
    # not in ActionModel:
    start_condition: Optional[ActionStartCondition] = ActionStartCondition.wait_for_all
    save_act: Optional[bool] = True  # default should be true
    save_data: Optional[bool] = True  # default should be true
    AUX_file_paths: Optional[List[Path]] = Field(default_factory=list)

    # moved to ActionModel
    # error_code: Optional[ErrorCodes] = ErrorCodes.none

    from_globalexp_params: Optional[dict] = Field(default_factory=dict)
    to_globalexp_params: Optional[Union[list, dict]] = Field(default_factory=list)

    # internal
    file_conn_keys: Optional[List[UUID]] = Field(default_factory=list)

    # flag for datalogger
    # None will signal default behaviour as before
    # will be updated by data logger only if it finds the status
    # in the data stream
    data_stream_status: Optional[HloStatus] = None

    def __repr__(self):
        return f"<action_name:{self.action_name}>"

    def __str__(self):
        return f"action_name:{self.action_name}"

    def get_act(self):
        return ActionModel(**self.dict())

    def init_act(self, time_offset: float = 0, force: Optional[bool] = None):
        if self.sequence_timestamp is None or self.experiment_timestamp is None:
            self.manual_action = True
            self.access = "manual"
            # -- (1) -- set missing sequence parameters
            self.sequence_name = "manual_seq"
            self.init_seq(time_offset=time_offset)
            # -- (2) -- set missing experiment parameters
            self.experiment_name = "MANUAL"
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
        return os.path.join(
            experiment_dir,
            f"{self.orch_submit_order}__"
            f"{self.action_split}__"
            f"{self.action_timestamp.strftime('%Y%m%d.%H%M%S%f')}__"
            f"{self.action_server.server_name}__{self.action_name}",
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

        # find the Experiment Basemodel
        # and add all other params to a dict
        for arg in _args:
            argparam = _locals.get(arg, None)
            if isinstance(argparam, Experiment):
                if self._experiment is None:
                    print_message(
                        {},
                        "actionplanmaker",
                        f"{self.expname}: found Experiment BaseModel under "
                        f"parameter '{arg}'",
                        info=True,
                    )
                    self._experiment = deepcopy(argparam)
                else:
                    print_message(
                        {},
                        "actionplanmaker",
                        f"{self.expname}: critical error: "
                        f"found another Experiment BaseModel"
                        f" under parameter '{arg}',"
                        f" skipping it",
                        error=True,
                    )
            else:
                exp_paramdict.update({arg: argparam})

        # check if an Experiment was detected
        if self._experiment is None:
            print_message(
                {},
                "actionplanmaker",
                f"{self.expname}: critical error: "
                f"no Experiment BaseModel was found "
                f"by ActionPlanMaker, "
                f"using blank Experiment.",
                error=True,
            )
            self._experiment = Experiment()

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
                print_message(
                    {},
                    "ActionPlanMaker",
                    f"{self.expname}: local var '{key}'"
                    f" not found in Experiment, "
                    f"adding it to self.pars",
                    info=True,
                )
                if isinstance(val, str):
                    if val.lower() == "true":
                        val = True
                    elif val.lower() == "false":
                        val = False
                setattr(self.pars, key, val)

        print_message(
            {},
            "ActionPlanMaker",
            f"{self.expname}: params in self.pars are:" f" {vars(self.pars)}",
            info=True,
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


class ExperimentPlanMaker:
    def __init__(
        self,
    ):
        self.experiment_plan_list = []

    def add_experiment(self, selected_experiment, experiment_params, **kwargs):
        self.experiment_plan_list.append(
            (
                ExperimentTemplate(
                    experiment_name=selected_experiment,
                    experiment_params=experiment_params,
                    **kwargs,
                ),
            )
        )
