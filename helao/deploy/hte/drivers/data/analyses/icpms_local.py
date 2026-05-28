"""Local-zip ICP-MS concentration extractor.

Reads ICP-MS HLO files inside a sequence zip via :class:`LocalLoader`,
selects the concentration column named by ``analysis_params["fom_key"]``
(defaulting to ``"ExtCal.Concentration_ppb"``), and emits
:class:`IcpmsOutputs` records suitable for the analysis syncer.
"""

import sys
from copy import copy
from uuid import UUID
from datetime import datetime
from typing import List

from pydantic import BaseModel

from helao.core.version import get_filehash
from helao.core.models.analysis import AnalysisDataModel, AnalysisInput, AnalysisOutput

from helao.core.drivers.data.analyses.base_analysis import BaseAnalysis
from helao.core.drivers.data.loaders.localfs import (
    HelaoProcess,
    HelaoAction,
    LocalLoader,
)

ANALYSIS_DEFAULTS = {
    "fom_key": "ExtCal.Concentration_ppb",
}


class IcpmsInputs(AnalysisInput):
    """Process/action pair backing a single ICP-MS analysis.

    Attributes:
        icpms: Process row carrying the ICP-MS json/meta.
        icpms_act: Action row whose HLO holds the mass-spectrum data.
        global_sample_label: Liquid-sample global label discovered in
            the process file list.
        process_params: ``process_params`` dict from the process row.
    """

    icpms: HelaoProcess
    icpms_act: HelaoAction
    global_sample_label: str
    process_params: dict

    def __init__(self, process_uuid: UUID, local_loader: LocalLoader):
        """Locate the ICP-MS process file and the action that produced it.

        Args:
            process_uuid: Target process UUID inside the zip.
            local_loader: :class:`LocalLoader` bound to the sequence
                zip.
        """
        self.icpms = local_loader.get_prc(
            local_loader.processes.query("process_uuid==@process_uuid").index[0]
        )
        self.process_params = self.icpms.process_params
        filed = [
            d
            for d in self.icpms.json["files"]
            if d["file_type"] in ["icpms_helao__file", "icpms_helao__json_file"]
        ][0]
        self.global_sample_label = [x for x in filed["sample"] if "__liquid__" in x][0]
        action_uuid = filed["action_uuid"]
        action_dir = [
            d
            for d in self.icpms.json["dispatched_actions_abbr"]
            if d["action_uuid"] == action_uuid
        ][0]["action_output_dir"]
        action_reldir = "/".join(action_dir.split("/")[-2:])
        self.icpms_act = local_loader.get_act(
            local_loader.actions.query(
                "action_localpath.str.startswith(@action_reldir)"
            ).index[0]
        )

    @property
    def mass_spec(self):
        """Loaded HLO payload for the ICP-MS action."""
        return self.icpms_act.hlo

    def get_datamodels(self, *args, **kwargs) -> List[AnalysisDataModel]:
        """Return a one-element list describing the ICP-MS HLO file."""
        filename, filetype, datakeys = self.icpms_act.hlo_file_tup
        adm = AnalysisDataModel(
            action_uuid=self.icpms_act.action_uuid,
            run_use=self.icpms_act.json["run_use"],
            raw_data_path=f"raw_data/{self.icpms_act.action_uuid}/{filename}",
            global_sample_label=self.global_sample_label,
            file_name=filename,
            file_type=filetype,
            data_keys=datakeys,
        )
        return [adm]


class IcpmsOutputs(AnalysisOutput):
    """ICP-MS concentration payload emitted by :class:`IcpmsAnalysis`.

    Attributes:
        element: Element labels per row.
        isotope: Isotope labels per row.
        value: Concentration value per row pulled from ``fom_key``.
        fom_key: Name of the figure-of-merit column.
        global_sample_label: Liquid sample the values belong to.
    """

    element: list
    isotope: list
    value: list
    fom_key: str
    global_sample_label: str


class IcpmsAnalysis(BaseAnalysis):
    """ICP-MS concentration analysis sourced from a local sequence zip.

    Attributes:
        inputs: Resolved :class:`IcpmsInputs`.
        outputs: Populated :class:`IcpmsOutputs` after
            :meth:`calc_output`.
        global_sample_label: Liquid sample under analysis.
    """

    inputs: IcpmsInputs
    outputs: IcpmsOutputs
    global_sample_label: str

    def __init__(
        self,
        process_uuid: UUID,
        local_loader: LocalLoader,
        analysis_params: dict,
    ):
        """Build inputs and generate the analysis UUID.

        Args:
            process_uuid: Target ICP-MS process UUID.
            local_loader: Zip-backed :class:`LocalLoader`.
            analysis_params: Overrides merged into
                :data:`ANALYSIS_DEFAULTS`.
        """
        self.analysis_name = "ICPMS_Concentration"
        self.analysis_timestamp = datetime.now()
        self.analysis_params = copy(ANALYSIS_DEFAULTS)
        self.analysis_params.update(analysis_params)
        self.inputs = IcpmsInputs(process_uuid, local_loader)
        self.process_uuid = self.inputs.icpms.process_uuid

        # additional attrs
        self.process_timestamp = self.inputs.icpms.process_timestamp
        self.process_name = self.inputs.icpms.technique_name
        self.run_type = self.inputs.icpms.meta_dict.get("run_type", "icpm")
        self.technique_name = self.inputs.icpms.technique_name
        self.sequence_uuid = self.inputs.icpms.meta_dict.get("sequence_uuid", None)

        self.analysis_codehash = get_filehash(sys._getframe().f_code.co_filename)
        self.analysis_codepath = sys._getframe().f_code.co_filename
        self.analysis_classname = self.__class__.__name__
        self.global_sample_label = self.inputs.global_sample_label
        self.analysis_uuid = self.gen_uuid(self.inputs.global_sample_label)

    def calc_output(self) -> bool:
        """Populate :attr:`outputs` from the ICP-MS HLO ``fom_key`` column."""

        fom_key = self.analysis_params["fom_key"]
        _, hlo_data = self.inputs.mass_spec

        # create output model
        self.outputs = IcpmsOutputs(
            element=hlo_data["element"],
            isotope=hlo_data["isotope"],
            value=hlo_data[fom_key],
            fom_key=fom_key,
            global_sample_label=self.global_sample_label,
            output_type="composition.icpms_concentration",
        )
        return True
