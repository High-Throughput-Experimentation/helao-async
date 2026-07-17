"""Import smoke tests: domain model surface + every port module (spec §4.3)."""

import importlib

MODEL_EXPORTS = [
    "Action",
    "Experiment",
    "Sequence",
    "ActionPlanMaker",
    "ExperimentPlanMaker",
    "ActionModel",
    "ShortActionModel",
    "ExperimentModel",
    "ShortExperimentModel",
    "SequenceModel",
    "ShortSequenceModel",
    "ProcessModel",
    "ShortProcessModel",
    "SampleModel",
    "NoneSample",
    "LiquidSample",
    "SolidSample",
    "GasSample",
    "AssemblySample",
    "SampleUnion",
    "object_to_sample",
    "SampleType",
    "SampleInheritance",
    "SampleStatus",
    "FileInfo",
    "FileConn",
    "FileConnParams",
    "HloHeaderModel",
    "HloFileGroup",
    "DataModel",
    "DataPackageModel",
    "GlobalStatusModel",
    "ActionServerModel",
    "EndpointModel",
    "MachineModel",
    "HloStatus",
    "OrchStatus",
    "LoopStatus",
    "LoopIntent",
    "ActionStartCondition",
    "RunUse",
    "ProcessContrib",
    "RunDir",
    "AnalysisModel",
    "AnalysisDataModel",
    "AnalysisOutputModel",
    "ShortAnalysisModel",
    "ErrorCodes",
    "HelaoDict",
]


def test_domain_models_reexports():
    mod = importlib.import_module("helao.hexagon.domain.models")
    missing = [n for n in MODEL_EXPORTS if not hasattr(mod, n)]
    assert not missing, f"missing re-exports: {missing}"


def test_domain_models_all_matches():
    mod = importlib.import_module("helao.hexagon.domain.models")
    assert sorted(mod.__all__) == sorted(MODEL_EXPORTS)
