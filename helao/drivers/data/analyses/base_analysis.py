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
    """
    BaseAnalysis class for handling analysis data and exporting results.
    Attributes:
        analysis_name (str): Name of the analysis.
        analysis_timestamp (datetime): Timestamp of the analysis.
        analysis_uuid (UUID): Unique identifier for the analysis.
        analysis_params (dict): Parameters for the analysis.
        process_uuid (UUID): Unique identifier for the process.
        process_timestamp (datetime): Timestamp of the process.
        process_name (str): Name of the process.
        run_type (str): Type of the run.
        technique_name (str): Name of the technique used.
        inputs (AnalysisInput): Input data for the analysis.
        outputs (BaseModel): Output data from the analysis.
        analysis_codehash (str): Hash of the analysis code.
    Methods:
        gen_uuid(global_sample_label: Optional[str] = None) -> UUID:
            Generates a unique identifier for the analysis based on input data models and parameters.
        export_analysis(bucket: str, region: str, dummy: bool = True, global_sample_label: Optional[str] = None) -> Tuple[dict, dict]:
            Exports the analysis results to a specified S3 bucket and returns the analysis model and outputs.
    """
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
        """
        Generates a UUID for the analysis based on various attributes.

        Parameters:
        global_sample_label (Optional[str]): A label for the global sample. If not provided,
                             it will be derived from the input data models.

        Returns:
        UUID: A unique identifier generated from the hash representation of the analysis attributes.

        The UUID is generated using a hash representation that includes:
        - analysis_name: The name of the analysis.
        - analysis_params: The parameters of the analysis.
        - process_uuid: The UUID of the process.
        - global_sample_label: The global sample label.
        - analysis_codehash: The hash of the analysis code.
        """
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
        """
        Export the analysis results to a structured format.

        Args:
            bucket (str): The S3 bucket where the analysis output will be stored.
            region (str): The AWS region where the S3 bucket is located.
            dummy (bool, optional): A flag indicating whether this is a dummy run. Defaults to True.
            global_sample_label (Optional[str], optional): A label for the global sample. Defaults to None.

        Returns:
            Tuple[Dict, Dict]: A tuple containing the cleaned analysis model dictionary and the outputs model dump.

        Raises:
            ValueError: If the analysis does not contain any outputs.

        Notes:
            - The function retrieves input data models based on the global sample label.
            - It categorizes the outputs into scalar and array outputs.
            - It constructs output data models for each category and appends them to the output data models list.
            - If no output data models are found, a message is printed indicating the absence of outputs.
            - An AnalysisModel instance is created with the relevant details and returned as a cleaned dictionary along with the outputs model dump.
        """
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
