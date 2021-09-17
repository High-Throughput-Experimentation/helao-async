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
from helao.core.helper import print_message
from helao.core.model import liquid_sample_no, gas_sample_no, solid_sample_no, samples_inout

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
        self.machine_name = imports.get("machine_name", None)
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
            print_message({}, "decision", f"decision_uuid: {self.decision_uuid} already exists", info = True)
        else:
            self.decision_uuid = gen_uuid(label=machine_name, timestamp=self.decision_timestamp)
            print_message({}, "decision", f"decision_uuid: {self.decision_uuid} assigned", info = True)

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
        self.save_rcp = imports.get("save_rcp", True)
        self.save_data = imports.get("save_data", True)
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
        self.file_data_keys = imports.get("file_data_keys", None)
        self.file_sample_label = imports.get("file_sample_label", None)
        self.file_sample_keys = imports.get("file_sample_keys", None)
        self.file_group = imports.get("file_group", None)
        self.error_code = imports.get("error_code", "0")
        self.from_global_params = imports.get("from_global_params", {})
        self.to_global_params = imports.get("to_global_params", [])


        check_args = {"server": self.action_server, "name": self.action_name}
        missing_args = [k for k, v in check_args.items() if v is None]
        if missing_args:
            print_message({}, "action", 
                f'Action {" and ".join(missing_args)} not specified. Placeholder actions will only affect the action queue enumeration.',
                info = True
            )


    def gen_uuid_action(self, machine_name: str):
        if self.action_uuid:
            print_message({}, "action", f"action_uuid: {self.action_uuid} already exists", error = True)
        else:
            self.action_uuid = gen_uuid(label=f"{machine_name}_{self.action_name}", timestamp=self.action_queue_time)
            print_message({}, "action", f"action_uuid: {self.action_uuid} assigned", info = True)

    def set_atime(self, offset: float = 0.0):
        atime = datetime.now()
        if offset is not None:
            atime = datetime.fromtimestamp(atime.timestamp() + offset)
        self.action_queue_time = atime.strftime("%Y%m%d.%H%M%S%f")


    def get_sample_in(self):
        
        def dict_to_samples_inout(self, samples_in_dictlist):
            if type(samples_in_dictlist) is not list:
                samples_in_dictlist = [samples_in_dictlist]
            samples_in_retlist = []
    
            for samples_in_dict in samples_in_dictlist:
                solid = samples_in_dict.get("solid",None)
                if solid is not None:
                    solid = solid_sample_no(**solid)
                liquid = samples_in_dict.get("liquid",None)
                if liquid is not None:
                    liquid = liquid_sample_no(**liquid)
                gas = samples_in_dict.get("gas",None)
                if gas is not None:
                    gas = gas_sample_no(**gas)
                machine = samples_in_dict.get("machine",None)
                if machine is None:
                    machine = self.machine_name
        
                samples_in_retlist.append(samples_inout(
                           sample_type = samples_in_dict.get("sample_type",""),
                           in_out = samples_in_dict.get("in_out",""),
                           label = samples_in_dict.get("label",None),
                           solid = solid,
                           liquid = liquid,
                           gas = gas,
                           status = samples_in_dict.get("status",None),
                           inheritance = samples_in_dict.get("inheritance",None),
                           machine = machine
                    )
                )
            return samples_in_retlist


        samples_in = self.action_params.get("samples_in",None)
        if "samples_in" in self.action_params:
            del self.action_params["samples_in"]

        if samples_in is not None:
            samples_in = dict_to_samples_inout(self,samples_in)
        return samples_in
