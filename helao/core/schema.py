""" schemas.py
Standard classes for experiment queue objects.

"""
from collections import defaultdict
from datetime import datetime
from typing import Optional, Union
import types
import json

from helao.core.helper import gen_uuid
from helao.core.model import return_finishedact, return_runningact


class Decision(object):
    "Sample-process grouping class."

    def __init__(
        self,
        inputdict: dict = {},
    ):
        imports = {}
        imports.update(inputdict)
        self.orch_name = imports.get("orch_name", "orchestrator")
        self.technique_name = imports.get("technique_name", None)
        self.decision_uuid = imports.get("decision_uuid", None)
        self.decision_timestamp = imports.get("decision_timestamp", None)
        self.decision_label = imports.get("decision_label", "noLabel")
        self.access = imports.get("access", "hte")
        self.actualizer = imports.get("actualizer", None)
        self.actualizer_pars = imports.get("actualizer_pars", {})
        # this gets big really fast, bad for debugging
        self.result_dict = {}#imports.get("result_dict", {})
        self.global_params = {}

    def as_dict(self):
        d = vars(self)
        attr_only = {
            k: v
            for k, v in d.items()
            if type(v) != types.FunctionType and not k.startswith("__")
        }
        return attr_only


    def fastdict(self):
        d = vars(self)
        params_dict = {
            k: int(v) if type(v) == bool else v
            for k, v in d.items()
            if type(v) != types.FunctionType and 
            not k.startswith("__") and 
            (v is not None) and (type(v) != dict)  and (v != {})
        }
        json_dict = {
            k: v
            for k, v in d.items()
            if type(v) != types.FunctionType and 
            not k.startswith("__") and 
            (v is not None) and (type(v) == dict)
        }
        return params_dict, json_dict


    def gen_uuid_decision(self, machine_name: str):
        "server_name can be any string used in generating random uuid"
        if self.decision_uuid:
            print(f"decision_uuid: {self.decision_uuid} already exists")
        else:
            self.decision_uuid = gen_uuid(label=machine_name, timestamp=self.decision_timestamp)
            print(f"decision_uuid: {self.decision_uuid} assigned")

    def set_dtime(self, offset: float = 0):
        dtime = datetime.now()
        dtime = datetime.fromtimestamp(dtime.timestamp() + offset)
        self.decision_timestamp = dtime.strftime("%Y%m%d.%H%M%S%f")


class Action(Decision):
    "Sample-process identifier class."

    def __init__(
        self,
        inputdict: dict = {},
    ):
        super().__init__(inputdict)  # grab decision keys
        imports = {}
        imports.update(inputdict)
        self.action_uuid = imports.get("action_uuid", None)
        self.action_queue_time = imports.get("action_queue_time", None)
        self.action_server = imports.get("action_server", None)
        self.action_name = imports.get("action_name", None)
        self.action_params = imports.get("action_params", {})
        self.action_enum = imports.get("action_enum", None)
        self.action_abbr = imports.get("action_abbr", None)
        self.save_rcp = imports.get("save_rcp", False)
        self.save_data = imports.get("save_data", None)
        self.start_condition = imports.get("start_condition", 3)
        self.plate_id = imports.get("plate_id", None)
        self.samples_in = imports.get("samples_in", {})
        # the following attributes are set during Action dispatch but can be imported
        self.samples_out = imports.get("samples_out", {})
        self.file_dict = defaultdict(lambda: defaultdict(dict))
        self.file_dict.update(imports.get("file_dict", {}))
        self.file_paths = imports.get("file_paths", [])
        self.data = imports.get("data", [])
        self.output_dir = imports.get("output_dir", None)
        self.column_names = imports.get("column_names", None)
        self.header = imports.get("header", None)
        self.file_type = imports.get("file_type", None)
        self.filename = imports.get("filename", None)
        self.file_group = imports.get("file_group", None)
        self.error_code = imports.get("error_code", "0")
        self.from_global_params = imports.get("from_global_params", {})
        self.to_global_params = imports.get("to_global_params", [])


        check_args = {"server": self.action_server, "name": self.action_name}
        missing_args = [k for k, v in check_args.items() if v is None]
        if missing_args:
            print(
                f'Action {" and ".join(missing_args)} not specified. Placeholder actions will only affect the action queue enumeration.'
            )


    def gen_uuid_action(self, machine_name: str):
        if self.action_uuid:
            print(f"action_uuid: {self.action_uuid} already exists")
        else:
            self.action_uuid = gen_uuid(label=f"{machine_name}_{self.action_name}", timestamp=self.action_queue_time)
            print(f"action_uuid: {self.action_uuid} assigned")

    def set_atime(self, offset: float = 0.0):
        atime = datetime.now()
        if offset is not None:
            atime = datetime.fromtimestamp(atime.timestamp() + offset)
        self.action_queue_time = atime.strftime("%Y%m%d.%H%M%S%f")

