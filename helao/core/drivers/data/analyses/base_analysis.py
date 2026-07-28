from typing import Optional
from uuid import UUID
from datetime import datetime
from helao.core.models.analysis import (
    AnalysisOutputModel,
    AnalysisModel,
    AnalysisInput,
    AnalysisOutput,
)
from helao.core.models.s3locator import S3Locator
from helao.core.models.run_use import RunUse
from helao.helpers.time_utils import set_time
from pydasher.serialization import hasher


class BaseAnalysis:
    """Common base for analysis classes that target a single HELAO process.

    Concrete subclasses fill in the declared attributes (name, params, the
    process being analyzed, the input/output containers) and rely on this
    base for deterministic UUID generation and S3 export packaging.

    Attributes:
        analysis_name: Human-readable analysis identifier.
        analysis_timestamp: When the analysis ran.
        analysis_uuid: Stable UUID derived from inputs/params/codehash.
        analysis_params: Parameter dict the analysis was invoked with.
        process_uuid: UUID of the source process.
        process_timestamp: Timestamp of the source process.
        process_name: Name of the source process.
        run_type: Run classification (e.g. data, calibration).
        run_use: Run-use enum value used for input matching.
        technique_name: Technique name from the source process.
        analysis_codehash: Hash of the analysis source.
        analysis_codepath: Filesystem path to the analysis module.
        analysis_classname: Class name of the concrete analysis.
        analysis_action_uuid: Optional originating action UUID.
        campaign_name: Optional campaign label.
        campaign_uuid: Optional campaign UUID.
        inputs: Input data container.
        outputs: Output data container.
    """

    analysis_name: str
    analysis_timestamp: datetime
    analysis_uuid: UUID
    analysis_params: dict
    process_uuid: UUID
    process_timestamp: datetime
    process_name: str
    run_type: str
    run_use: str
    technique_name: str
    analysis_codehash: str
    analysis_codepath: str
    analysis_classname: str
    analysis_action_uuid: Optional[UUID] = None
    campaign_name: Optional[str] = None
    campaign_uuid: Optional[UUID] = None
    inputs: AnalysisInput
    outputs: AnalysisOutput

    @classmethod
    def select_process_uuids(cls, local_loader) -> list:
        """Return the process UUIDs this analysis should run on for a loader.

        Default behaviour enqueues every process in the loader. Subclasses
        override this to filter (e.g. by ``run_use``) when only a subset of the
        sequence's processes are valid inputs.

        Args:
            local_loader: ``LocalLoader`` bound to a sequence zip.

        Returns:
            List of process UUIDs to enqueue for analysis.
        """
        return list(local_loader.processes.process_uuid)

    def gen_uuid(self, global_sample_label: Optional[str] = None) -> UUID:
        """Derive a stable analysis UUID from analysis identity and inputs.

        The UUID is the deterministic hash of ``analysis_name``,
        ``analysis_params``, ``process_uuid``, the resolved
        ``global_sample_label``, ``analysis_codehash``, and ``run_use``.

        Args:
            global_sample_label: Sample label to include in the hash. When
                None, the first input data model with ``run_use == data`` is
                used.

        Returns:
            The hashed UUID.
        """
        input_data_models = self.inputs.get_datamodels(global_sample_label)
        if global_sample_label is None:
            ru_data = [x for x in input_data_models if x.run_use == RunUse.data]
            if ru_data:
                global_sample_label = ru_data[0].global_sample_label
        hash_rep = {
            "analysis_name": self.analysis_name,
            "analysis_params": self.analysis_params,
            "process_uuid": self.process_uuid,
            "global_sample_label": global_sample_label,
            "analysis_codehash": self.analysis_codehash,
            "run_use": self.run_use,
        }
        return UUID(hasher(hash_rep))

    def export_analysis(
        self,
        bucket: str,
        region: str,
        dummy: bool = True,
        global_sample_label: Optional[str] = None,
    ) -> tuple:
        """Package the analysis into an ``AnalysisModel`` + raw outputs dict.

        Output values are split into a ``scalar`` and an ``array`` group, each
        wrapped in an ``AnalysisOutputModel`` pointing at the S3 key
        ``analysis/<uuid>_output_<group>.json`` in ``bucket``/``region``.

        Args:
            bucket: S3 bucket where outputs will be stored.
            region: AWS region for the bucket.
            dummy: Mark the produced model as a dummy run.
            global_sample_label: Sample label override; resolved from inputs
                when None.

        Returns:
            A ``(analysis_model_dict, outputs_dump)`` tuple.
        """
        input_data_models = self.inputs.get_datamodels(global_sample_label)
        if global_sample_label is None:
            ru_data = [x for x in input_data_models if x.run_use == RunUse.data]
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
                        key=f"analysis/{self.analysis_uuid}_output_{label}.json",
                        region=region,
                    ),
                    content_type="application/json",
                    # content_encoding="gzip",
                    output_type=self.outputs.output_type,
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
            analysis_codepath=self.analysis_codepath,
            analysis_classname=self.analysis_classname,
            global_sample_label=global_sample_label,
            analysis_uuid=self.analysis_uuid,
            process_uuid=self.process_uuid,
            process_params=self.inputs.process_params,
            inputs=input_data_models,
            outputs=output_data_models,
            dummy=dummy,
            campaign_name=self.campaign_name,
            campaign_uuid=self.campaign_uuid,
        )
        return ana_model.clean_dict(), self.outputs.model_dump()
