from uuid import UUID
from datetime import datetime
from pydantic import BaseModel
from helaocore.models.analysis import (
    AnalysisDataModel,
    AnalysisOutputModel,
    AnalysisModel,
)
from helaocore.models.s3locator import S3Locator
from helao.helpers.set_time import set_time


class BaseAnalysis:
    analysis_timestamp: datetime
    analysis_uuid: UUID
    analysis_params: dict
    process_uuid: UUID
    inputs: object
    outputs: BaseModel

    def export_analysis(
        self,
        analysis_name: str,
        bucket: str,
        region: str,
        dummy: bool = True,
        global_sample_label: str = None,
        action_attr: str = "spec_act",
    ):
        action_keys = [k for k in vars(self.inputs).keys() if action_attr in k]
        inputs = []

        for ak in action_keys:
            euis = vars(self.inputs)[ak]
            ru = ak.split("_spec")[0].replace("insitu", "data")
            if not isinstance(euis, list):
                euis = [euis]
            for eui in euis:
                raw_data_path = f"raw_data/{eui.action_uuid}/{eui.hlo_file}.json"
                if global_sample_label is not None:
                    global_sample = global_sample_label
                elif ru in ["data", "baseline"]:
                    global_sample = (
                        f"legacy__solid__{int(self.plate_id):d}_{int(self.sample_no):d}"
                    )
                else:
                    global_sample = None
                adm = AnalysisDataModel(
                    action_uuid=eui.action_uuid,
                    run_use=ru,
                    raw_data_path=raw_data_path,
                    global_sample_label=global_sample,
                )
                inputs.append(adm)

        scalar_outputs = [
            k for k, v in self.outputs.model_dump().items() if not isinstance(v, list)
        ]
        array_outputs = [
            k for k in self.outputs.model_dump().keys() if k not in scalar_outputs
        ]

        outputs = []

        for label, output_keys in [
            ("scalar", scalar_outputs),
            ("array", array_outputs),
        ]:
            if output_keys:
                out_model = AnalysisOutputModel(
                    analysis_output_path=S3Locator(
                        bucket=bucket,
                        key=f"analysis/{self.analysis_uuid}_output_{label}.json",
                        region=region,
                    ),
                    content_type="application/json",
                    output_keys=output_keys,
                    output_name=label,
                    output={
                        k: self.outputs.model_dump()[k]
                        for k in output_keys
                        if not isinstance(
                            self.outputs.model_dump()[k], list
                        )  # only scalars
                    },
                )
                outputs.append(out_model)

        if not outputs:
            print("!!! analysis does not contain any outputs")

        ana_model = AnalysisModel(
            analysis_name=analysis_name,
            analysis_timestamp=set_time(),
            analysis_params=self.analysis_params,
            analysis_codehash=self.analysis_codehash,
            analysis_uuid=self.analysis_uuid,
            process_uuid=self.process_uuid,
            process_params=self.inputs.insitu.process_params,
            inputs=inputs,
            outputs=outputs,
            dummy=dummy,
        )
        return ana_model.clean_dict(), self.outputs.model_dump()
