"""Tests for helao.framework.domain.analysis.base_analysis.BaseAnalysis.

Exercises:
- gen_uuid: stable deterministic UUID from inputs/params/codehash
- export_analysis: returns (analysis_model_dict, outputs_dump) with correct
  AnalysisModel shape, scalar/array output split, and S3 locator keys.

Not exercised here:
- select_process_uuids (requires a LocalLoader with a .processes DataFrame;
  the method delegates entirely to the loader, tested at integration level).
"""

from typing import List, Optional
from uuid import UUID, uuid4

import pytest

from helao.framework.domain.analysis.base_analysis import BaseAnalysis
from helao.framework.models.analysis import (
    AnalysisDataModel,
    AnalysisInput,
    AnalysisOutput,
)
from helao.framework.models.run_use import RunUse


# ---------------------------------------------------------------------------
# Minimal concrete AnalysisInput
# ---------------------------------------------------------------------------

class _SimpleInput(AnalysisInput):
    """Concrete AnalysisInput backed by a single AnalysisDataModel."""

    process_params: dict = {}

    def __init__(self, data_model: AnalysisDataModel):
        self._data_model = data_model
        self.process_params = {"voltage": 1.5}

    def get_datamodels(self, *args, **kwargs) -> List[AnalysisDataModel]:
        return [self._data_model]


# ---------------------------------------------------------------------------
# Minimal concrete AnalysisOutput
# ---------------------------------------------------------------------------

class _SimpleOutput(AnalysisOutput):
    output_type: str = "simple"
    peak_current: float = 3.14
    raw_trace: list = [1.0, 2.0, 3.0]


# ---------------------------------------------------------------------------
# Minimal concrete BaseAnalysis subclass
# ---------------------------------------------------------------------------

PROCESS_UUID = uuid4()
ACTION_UUID = uuid4()
SAMPLE_LABEL = "assembly__test_sample__1"


def _make_analysis(*, run_use: RunUse = RunUse.data) -> "BaseAnalysis":
    """Construct and return a fully-populated minimal BaseAnalysis instance."""
    data_model = AnalysisDataModel(
        action_uuid=ACTION_UUID,
        run_use=run_use,
        raw_data_path="s3://test-bucket/raw/data.hlo",
        global_sample_label=SAMPLE_LABEL,
    )

    class MinimalAnalysis(BaseAnalysis):
        pass

    ana = MinimalAnalysis()
    ana.analysis_name = "test_analysis"
    ana.analysis_params = {"threshold": 0.5}
    ana.process_uuid = PROCESS_UUID
    ana.process_timestamp = None
    ana.process_name = "test_process"
    ana.run_type = "data"
    ana.run_use = RunUse.data.value
    ana.technique_name = "CV"
    ana.analysis_codehash = "abc123"
    ana.analysis_codepath = "/path/to/analysis.py"
    ana.analysis_classname = "MinimalAnalysis"
    ana.analysis_action_uuid = None
    ana.campaign_name = None
    ana.campaign_uuid = None
    ana.inputs = _SimpleInput(data_model)
    ana.outputs = _SimpleOutput()
    # gen_uuid to populate analysis_uuid
    ana.analysis_uuid = ana.gen_uuid()
    return ana


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGenUuid:
    def test_returns_uuid(self):
        ana = _make_analysis()
        assert isinstance(ana.analysis_uuid, UUID)

    def test_deterministic(self):
        """Same inputs/params/codehash must produce the same UUID every time."""
        a1 = _make_analysis()
        a2 = _make_analysis()
        assert a1.analysis_uuid == a2.analysis_uuid

    def test_changes_with_param(self):
        """Changing analysis_params must change the UUID."""
        ana1 = _make_analysis()
        ana2 = _make_analysis()
        ana2.analysis_params = {"threshold": 0.99}
        ana2.analysis_uuid = ana2.gen_uuid()
        assert ana1.analysis_uuid != ana2.analysis_uuid

    def test_explicit_sample_label_overrides_input_label(self):
        """Passing an explicit global_sample_label should produce a different
        UUID than the one resolved from the data model's label."""
        ana = _make_analysis()
        uuid_from_input = ana.gen_uuid()
        uuid_explicit = ana.gen_uuid(global_sample_label="assembly__other__99")
        assert uuid_from_input != uuid_explicit


class TestExportAnalysis:
    def test_returns_two_element_tuple(self):
        ana = _make_analysis()
        result = ana.export_analysis(bucket="test-bucket", region="us-east-1")
        assert isinstance(result, tuple) and len(result) == 2

    def test_model_dict_has_analysis_name(self):
        ana = _make_analysis()
        model_dict, _ = ana.export_analysis(bucket="b", region="r")
        assert model_dict["analysis_name"] == "test_analysis"

    def test_model_dict_has_correct_uuid(self):
        ana = _make_analysis()
        model_dict, _ = ana.export_analysis(bucket="b", region="r")
        assert UUID(model_dict["analysis_uuid"]) == ana.analysis_uuid

    def test_outputs_dump_contains_scalar_and_array_fields(self):
        ana = _make_analysis()
        _, outputs_dump = ana.export_analysis(bucket="b", region="r")
        assert "peak_current" in outputs_dump
        assert "raw_trace" in outputs_dump

    def test_scalar_output_model_has_s3_key(self):
        """Scalar outputs should produce an AnalysisOutputModel with an S3 key
        containing the analysis UUID and 'scalar'."""
        ana = _make_analysis()
        model_dict, _ = ana.export_analysis(bucket="mybucket", region="us-west-2")
        outputs = model_dict["outputs"]
        scalar_model = next(
            (o for o in outputs if o.get("output_name") == "scalar"), None
        )
        assert scalar_model is not None
        key = scalar_model["analysis_output_path"]["key"]
        assert str(ana.analysis_uuid) in key
        assert "scalar" in key

    def test_array_output_model_has_s3_key(self):
        """Array outputs should produce an AnalysisOutputModel with an S3 key
        containing the analysis UUID and 'array'."""
        ana = _make_analysis()
        model_dict, _ = ana.export_analysis(bucket="mybucket", region="us-west-2")
        outputs = model_dict["outputs"]
        array_model = next(
            (o for o in outputs if o.get("output_name") == "array"), None
        )
        assert array_model is not None
        key = array_model["analysis_output_path"]["key"]
        assert str(ana.analysis_uuid) in key
        assert "array" in key

    def test_scalar_output_excludes_lists(self):
        """The scalar AnalysisOutputModel's inline output dict must not
        contain list values."""
        ana = _make_analysis()
        model_dict, _ = ana.export_analysis(bucket="b", region="r")
        outputs = model_dict["outputs"]
        scalar_model = next(
            (o for o in outputs if o.get("output_name") == "scalar"), None
        )
        assert scalar_model is not None
        inline = scalar_model.get("output", {})
        for v in (inline or {}).values():
            assert not isinstance(v, list), f"list found in scalar output: {v}"

    def test_dummy_flag_propagated(self):
        ana = _make_analysis()
        model_dict, _ = ana.export_analysis(bucket="b", region="r", dummy=False)
        assert model_dict["dummy"] is False

    def test_process_params_in_model(self):
        ana = _make_analysis()
        model_dict, _ = ana.export_analysis(bucket="b", region="r")
        assert model_dict["process_params"] == {"voltage": 1.5}

    def test_explicit_sample_label_in_model(self):
        ana = _make_analysis()
        label = "assembly__override__7"
        model_dict, _ = ana.export_analysis(
            bucket="b", region="r", global_sample_label=label
        )
        assert model_dict["global_sample_label"] == label
