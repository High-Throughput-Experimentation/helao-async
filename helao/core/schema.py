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
from helao.core.model import liquid_sample, gas_sample, solid_sample, assembly_sample, sample_list


class cProcess_group(object):
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
        self.process_group_uuid = imports.get("process_group_uuid", None)
        self.process_group_timestamp = imports.get("process_group_timestamp", None)
        self.process_group_label = imports.get("process_group_label", "noLabel")
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


    def gen_uuid_process_group(self, machine_name: str):
        "server_name can be any string used in generating random uuid"
        if self.process_group_uuid:
            print_message({}, "process_group", f"process_group_uuid: {self.process_group_uuid} already exists", info = True)
        else:
            self.process_group_uuid = gen_uuid(label=machine_name, timestamp=self.process_group_timestamp)
            print_message({}, "process_group", f"process_group_uuid: {self.process_group_uuid} assigned", info = True)

    def set_dtime(self, offset: float = 0):
        dtime = datetime.now()
        dtime = datetime.fromtimestamp(dtime.timestamp() + offset)
        self.process_group_timestamp = dtime.strftime("%Y%m%d.%H%M%S%f")


class cProcess(cProcess_group):
    "Sample-process identifier class."

    def __init__(
        self,
        inputdict: dict = {},
    ):
        super().__init__(inputdict)  # grab process_group keys
        imports = {}
        imports.update(inputdict)
        self.process_uuid = imports.get("process_uuid", None)
        self.process_queue_time = imports.get("process_queue_time", None)
        self.process_server = imports.get("process_server", None)
        self.process_name = imports.get("process_name", None)
        self.process_params = imports.get("process_params", {})
        self.process_enum = imports.get("process_enum", None)
        self.process_abbr = imports.get("process_abbr", None)
        self.save_rcp = imports.get("save_rcp", True)
        self.save_data = imports.get("save_data", True)
        self.start_condition = imports.get("start_condition", 3)
        self.plate_id = imports.get("plate_id", None)
        # holds sample list of dict for rcp writing
        self.rcp_samples_in = []
        self.rcp_samples_out = []

        # holds samples basemodel for parsing between processes etc
        self.samples_in: sample_list = []
        self.samples_out: sample_list = []

        # self.samples_in = imports.get("samples_in", [])
        # the following attributes are set during process dispatch but can be imported
        # self.samples_out = imports.get("samples_out", [])
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


        check_args = {"server": self.process_server, "name": self.process_name}
        missing_args = [k for k, v in check_args.items() if v is None]
        if missing_args:
            print_message({}, "process", 
                f'process {" and ".join(missing_args)} not specified. Placeholder processes will only affect the process queue enumeration.',
                info = True
            )


    def gen_uuid_process(self, machine_name: str):
        if self.process_uuid:
            print_message({}, "process", f"process_uuid: {self.process_uuid} already exists", error = True)
        else:
            self.process_uuid = gen_uuid(label=f"{machine_name}_{self.process_name}", timestamp=self.process_queue_time)
            print_message({}, "process", f"process_uuid: {self.process_uuid} assigned", info = True)

    def set_atime(self, offset: float = 0.0):
        atime = datetime.now()
        if offset is not None:
            atime = datetime.fromtimestamp(atime.timestamp() + offset)
        self.process_queue_time = atime.strftime("%Y%m%d.%H%M%S%f")
