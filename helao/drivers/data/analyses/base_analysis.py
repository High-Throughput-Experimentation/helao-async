from typing import Optional
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel
from helaocore.models.analysis import (
    AnalysisOutputModel,
    AnalysisModel,
    AnalysisInput
)
from helaocore.models.s3locator import S3Locator
from helaocore.models.run_use import RunUse
from helao.helpers.set_time import set_time
from pydasher.serialization import hasher


class BaseAnalysis:
    analysis_name: str
    analysis_timestamp: datetime
    analysis_uuid: UUID
    analysis_params: dict
    process_uuid: UUID
    process_timestamp: datetime
    process_name: str
    run_type: str
    technique_name: str
    inputs: AnalysisInput
    outputs: BaseModel
    analysis_codehash: str
    
    def gen_uuid(self, global_sample_label: Optional[str] = None):
        input_data_models = self.inputs.get_datamodels(global_sample_label)
        if global_sample_label is None:
            ru_data = [x for x in input_data_models if x.run_use==RunUse.data]
            if ru_data:
                global_sample_label = ru_data[0].global_sample_label
        hash_rep = {
            "analysis_name": self.analysis_name,
            "analysis_params": self.analysis_params,
            "process_uuid": self.process_uuid,
            "global_sample_label": global_sample_label,
            "analysis_codehash": self.analysis_codehash,
        }
        return UUID(hasher(hash_rep))

    def export_analysis(
        self,
        bucket: str,
        region: str,
        dummy: bool = True,
        global_sample_label: Optional[str] = None,
    ):
        input_data_models = self.inputs.get_datamodels(global_sample_label)
        if global_sample_label is None:
            ru_data = [x for x in input_data_models if x.run_use==RunUse.data]
            if ru_data:
                global_sample_label = ru_data[0].global_sample_label

        scalar_outputs = [
            k for k, v in self.outputs.model_dump().items() if not isinstance(v, list)
        ]
        array_outputs = [
            k for k in self.outputs.model_dump().keys() if k not in scalar_outputs
        ]

        output_data_models = []

        for label, output_keys in [
            ("scalar", scalar_outputs),
            ("array", array_outputs),
        ]:
            if output_keys:
                out_model = AnalysisOutputModel(
                    analysis_output_path=S3Locator(
                        bucket=bucket,
                        # key=f"analysis/{self.analysis_uuid}_output_{label}.json.gz",
                        key=f"analysis/{self.analysis_uuid}_output_{label}.json",
                        region=region,
                    ),
                    content_type="application/json",
                    # content_encoding="gzip",
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
                output_data_models.append(out_model)

        if not output_data_models:
            print("!!! analysis does not contain any outputs")

        ana_model = AnalysisModel(
            analysis_name=self.analysis_name,
            analysis_timestamp=set_time(),
            analysis_params=self.analysis_params,
            analysis_codehash=self.analysis_codehash,
            global_sample_label=global_sample_label,
            analysis_uuid=self.analysis_uuid,
            process_uuid=self.process_uuid,
            process_params=self.inputs.process_params,
            inputs=input_data_models,
            outputs=output_data_models,
            dummy=dummy,
        )
        return ana_model.clean_dict(), self.outputs.model_dump()
