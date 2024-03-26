import sys
from copy import copy
from uuid import UUID
from datetime import datetime
from typing import List

from pydantic import BaseModel

from helaocore.version import get_filehash
from helao.helpers.gen_uuid import gen_uuid

from .base_analysis import BaseAnalysis
from helaocore.models.analysis import AnalysisDataModel
from helao.drivers.data.loaders.localfs import HelaoProcess, HelaoAction, LocalLoader

ANALYSIS_DEFAULTS = {
    "fom_key": "ExtCal.Concentration_ppb",
}


class IcpmsInputs:
    icpms: HelaoProcess
    icpms_act: HelaoAction
    global_sample_label: str
    process_params: dict

    def __init__(self, process_uuid: UUID, local_loader: LocalLoader):
        self.icpms = local_loader.get_prc(
            local_loader.processes.query("process_uuid==@process_uuid").index[0]
        )
        self.process_params = self.icpms.process_params
        filed = [
            d for d in self.icpms.json["files"] if d["file_type"] == "icpms_helao__file"
        ][0]
        self.global_sample_label = [x for x in filed["sample"] if "__liquid__" in x][0]
        action_uuid = filed["action_uuid"]
        action_dir = [
            d for d in self.icpms.json["action_list"] if d["action_uuid"] == action_uuid
        ][0]["action_output_dir"]
        action_reldir = "/".join(action_dir.split("/")[-2:])
        self.icpms_act = local_loader.get_act(
            local_loader.actions.query(
                "action_localpath.str.startswith(@action_reldir)"
            ).index[0]
        )

    @property
    def mass_spec(self):
        return self.icpms_act.hlo

    def get_datamodels(self, *args, **kwargs) -> List[AnalysisDataModel]:
        adm = AnalysisDataModel(
            action_uuid=self.icpms_act.action_uuid,
            run_use=self.icpms_act.run_use,
            raw_data_path=f"raw_data/{self.icpms_act.action_uuid}/{self.icpms_act.hlo_file}.json",
            global_sample_label=self.global_sample_label,
        )
        return [adm]

class IcpmsOutputs(BaseModel):
    element: list
    isotope: list
    value: list
    fom_key: str
    global_sample_label: str


class IcpmsAnalysis(BaseAnalysis):
    """Dry UVIS Analysis for GCLD demonstration."""

    analysis_timestamp: datetime
    analysis_uuid: UUID
    analysis_params: dict
    process_uuid: UUID
    inputs: IcpmsInputs
    outputs: IcpmsOutputs
    analysis_codehash: str
    global_sample_label: str

    def __init__(
        self,
        process_uuid: UUID,
        local_loader: LocalLoader,
        analysis_params: dict,
    ):
        self.analysis_timestamp = datetime.now()
        self.analysis_uuid = gen_uuid()
        self.analysis_params = copy(ANALYSIS_DEFAULTS)
        self.analysis_params.update(analysis_params)
        self.inputs = IcpmsInputs(process_uuid, local_loader)
        self.process_uuid = self.inputs.icpms.process_uuid
        self.analysis_codehash = get_filehash(sys._getframe().f_code.co_filename)
        self.global_sample_label = self.inputs.global_sample_label

    def calc_output(self):
        """Calculate stability FOMs and intermediate vectors."""

        fom_key = self.analysis_params["fom_key"]
        _, hlo_data = self.inputs.mass_spec

        # create output model
        self.outputs = IcpmsOutputs(
            element=hlo_data["element"],
            isotope=hlo_data["isotope"],
            value=hlo_data[fom_key],
            fom_key=fom_key,
            global_sample_label=self.global_sample_label,
        )
        return True
