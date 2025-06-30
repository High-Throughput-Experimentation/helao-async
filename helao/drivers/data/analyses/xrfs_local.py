import os
import re
import sys
from glob import glob
from uuid import UUID
from datetime import datetime
from typing import List

from pydantic import BaseModel
import numpy as np
import pandas as pd

from helao.core.version import get_filehash
from helao.core.models.analysis import AnalysisDataModel, AnalysisInput

from .base_analysis import BaseAnalysis
from ...data.loaders.localfs import HelaoProcess, HelaoAction, LocalLoader

CM_SCALE = {"nm": 1e-7, "um": 1e-4, "mm": 0.1, "cm": 1}


class XrfsInputs(AnalysisInput):
    xrfs: HelaoProcess
    xrfs_act: HelaoAction
    global_sample_label: str
    process_params: dict

    def __init__(self, process_uuid: UUID, local_loader: LocalLoader):
        self.xrfs = local_loader.get_prc(
            local_loader.processes.query("process_uuid==@process_uuid").index[0]
        )
        self.process_params = self.xrfs.process_params
        filed = [
            d
            for d in self.xrfs.json["files"]
            if d["file_type"]
            in [
                "xrfcount_helao__file",
                "xrfcount_json__file",
                "xrfcount_helao__json_file",
            ]
        ][0]
        self.global_sample_label = [x for x in filed["sample"] if "__solid__" in x][0]
        action_uuid = filed["action_uuid"]
        action_dir = [
            d
            for d in self.xrfs.json["dispatched_actions"]
            if d["action_uuid"] == action_uuid
        ][0]["action_output_dir"]
        action_reldir = "/".join(action_dir.split("/")[-2:])
        self.xrfs_act = local_loader.get_act(
            local_loader.actions.query(
                "action_localpath.str.startswith(@action_reldir)"
            ).index[0]
        )

    @property
    def counts(self):
        return self.xrfs_act.hlo

    def get_datamodels(self, *args, **kwargs) -> List[AnalysisDataModel]:
        filename, filetype, datakeys = self.xrfs_act.hlo_file_tup_type(
            "xrfcount_helao__file"
        )
        adm = AnalysisDataModel(
            action_uuid=self.xrfs_act.action_uuid,
            run_use=self.xrfs_act.json["run_use"],
            raw_data_path=f"raw_data/{self.xrfs_act.action_uuid}/{filename}",
            global_sample_label=self.global_sample_label,
            file_name=filename,
            file_type=filetype,
            data_keys=datakeys,
        )
        return [adm]


class XrfsOutputs(BaseModel):
    element: list
    transition: list
    counts: list
    nanomoles: list
    nanomoles_2sig: list
    nanomoles_per_cm2: list
    atomic_fraction: list
    global_sample_label: str


class XrfsAnalysis(BaseAnalysis):
    """XRF quantification with calibration standards."""

    analysis_name: str
    analysis_timestamp: datetime
    analysis_uuid: UUID
    analysis_params: dict
    process_uuid: UUID
    process_timestamp: datetime
    process_name: str
    run_type: str
    technique_name: str
    inputs: XrfsInputs
    outputs: XrfsOutputs
    analysis_codehash: str
    global_sample_label: str

    def __init__(
        self,
        process_uuid: UUID,
        local_loader: LocalLoader,
        analysis_params: dict,
    ):
        self.analysis_name = "XRFS_quantification_analysis"
        self.analysis_timestamp = datetime.now()
        self.analysis_params = analysis_params
        # from analysis params, need (1) list of elements to normalize, (2) calibration file path
        self.inputs = XrfsInputs(process_uuid, local_loader)
        self.process_uuid = self.inputs.xrfs.process_uuid

        # additional attrs
        self.process_timestamp = self.inputs.xrfs.process_timestamp
        self.process_name = self.inputs.xrfs.technique_name
        self.run_type = self.inputs.xrfs.meta_dict.get("run_type", "xrfs")
        self.technique_name = self.inputs.xrfs.technique_name

        self.analysis_codehash = get_filehash(sys._getframe().f_code.co_filename)
        self.global_sample_label = self.inputs.global_sample_label
        self.analysis_uuid = self.gen_uuid(self.inputs.global_sample_label)

    def calc_output(self):
        """Calculate stability FOMs and intermediate vectors."""

        _, hlo_data = self.inputs.counts
        hlo_els = hlo_data["element"]
        hlo_counts = hlo_data["cps"]

        area_str = self.inputs.process_params["spot_size"]
        kv = self.inputs.process_params["voltage_kv"]
        current = self.inputs.process_params["current_ma"]

        diam_str, unit = re.findall(r"([0-9]+)[\s]*([a-z]+)", area_str)[0]
        diam = float(diam_str)
        unit = unit.strip()

        area = CM_SCALE[unit] * (diam / 2) ** 2 * 3.14159

        calib_prefix = f"{kv:.0f}-{current:.0f}-{diam_str.strip()}-vacu-"
        calib_path = self.analysis_params.get("calibration_file_path", "")

        norm_els = self.analysis_params.get("norm_elements", [])
        seq_dir = os.path.basename(
            os.path.dirname(
                os.path.dirname(self.inputs.xrfs_act.meta_dict["action_output_dir"])
            )
        )
        ymd_dir = os.path.basename(
            os.path.dirname(
                os.path.dirname(
                    os.path.dirname(self.inputs.xrfs_act.meta_dict["action_output_dir"])
                )
            )
        )
        seq_label = seq_dir.split("__")[-1]
        if not norm_els:
            norm_els = [
                x
                for x in re.findall("([A-Z]+[a-z]*)", seq_label)
                if x not in ("O", "Ar", "N", "H")
            ]

        if not calib_path:
            calib_libs = glob(
                rf"K:\experiments\xrfs\user\calibration_libraries\{calib_prefix}*.csv"
            )
            filtered_libs = [
                x
                for x in calib_libs
                if int(x.split("__")[-1].split("-")[0]) < int(ymd_dir)
            ]
            latest_lib = sorted(
                filtered_libs, key=lambda x: int(x.split("__")[-1].split("-")[0])
            )[-1]
            calib_path = latest_lib

        self.analysis_params["calibration_file_path"] = calib_path
        self.analysis_params["norm_elements"] = norm_els

        calibd = pd.read_csv(calib_path).set_index("transition").to_dict("index")

        elements = []
        transitions = []
        counts = []
        nanomoles = []
        nanomoles_2sig = []
        nanomoles_per_cm2 = []

        for trans, count in zip(hlo_els, hlo_counts):
            elements.append(trans.split(".")[0])
            transitions.append(trans)
            counts.append(count)
            if trans in calibd:
                tdict = calibd[trans]
                nanomoles.append(count * tdict["nmol.CPS"])
                nanomoles_2sig.append(count * tdict["relerr_nmol.CPS"])
                nanomoles_per_cm2.append(count * tdict["nmol.CPS"] / area)
            else:
                nanomoles.append(np.nan)
                nanomoles_2sig.append(np.nan)
                nanomoles_per_cm2.append(np.nan)

        # atomic_fraction
        norm_nmoles = []
        norm_trans = []

        for el in norm_els:
            if len([x for x in elements if x == el]) > 1:
                el_trans = sorted(
                    [x for x in transitions if x.startswith(f"{el}.") and x in calibd]
                )
            else:
                el_trans = [
                    x for x in transitions if x.startswith(f"{el}.") and x in calibd
                ]
            norm_nmoles.append(nanomoles[transitions.index(el_trans[-1])])
            norm_trans.append(el_trans[-1])

        sum_nanomoles = sum(norm_nmoles)
        atomic_fraction = [
            np.nan if trans not in norm_trans else nmoles / sum_nanomoles
            for trans, nmoles in zip(transitions, nanomoles)
        ]

        # create output model
        self.outputs = XrfsOutputs(
            element=elements,
            transition=transitions,
            counts=counts,
            nanomoles=nanomoles,
            nanomoles_2sig=nanomoles_2sig,
            nanomoles_per_cm2=nanomoles_per_cm2,
            atomic_fraction=atomic_fraction,
            global_sample_label=self.global_sample_label,
        )
        return True
