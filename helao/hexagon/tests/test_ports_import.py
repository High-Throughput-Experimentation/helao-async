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
    # PAL algorithm models (P3a-PAL slice 3) -- see models.py module docstring
    # "Exception" note.
    "PALposition",
    "PalAction",
    "PalMicroCam",
    "PalCam",
    "Spacingmethod",
]


def test_domain_models_reexports():
    mod = importlib.import_module("helao.hexagon.domain.models")
    missing = [n for n in MODEL_EXPORTS if not hasattr(mod, n)]
    assert not missing, f"missing re-exports: {missing}"


def test_domain_models_all_matches():
    mod = importlib.import_module("helao.hexagon.domain.models")
    assert sorted(mod.__all__) == sorted(MODEL_EXPORTS)


PORT_MODULES = {
    "helao.hexagon.ports.hardware": [
        "HardwarePort",
        "ExclusiveAccess",
        "driver_response_to_error_code",
    ],
    "helao.hexagon.ports.data_sink": ["DataSinkPort"],
    "helao.hexagon.ports.artifact_store": ["ArtifactStorePort"],
    "helao.hexagon.ports.sync": ["SyncPort", "S3FacePort"],
    "helao.hexagon.ports.transport": ["TransportPort"],
    "helao.hexagon.ports.status": ["StatusPort"],
}

PORT_MODULES.update(
    {
        "helao.hexagon.ports.clock": ["ClockPort"],
        "helao.hexagon.ports.logging": ["LoggingPort"],
        "helao.hexagon.ports.config": ["ConfigPort"],
        "helao.hexagon.ports.analysis": ["AnalysisArtifactPort"],
        "helao.hexagon.ports.sample_state": ["SampleStatePort"],
        "helao.hexagon.ports.auxiliary": [
            "StatePersistencePort",
            "PlateInfoPort",
            "LibraryPort",
            "HealthPort",
            "NotifyPort",
        ],
    }
)


def test_core_port_modules_import():
    for modname, names in PORT_MODULES.items():
        mod = importlib.import_module(modname)
        for n in names:
            assert hasattr(mod, n), f"{modname} missing {n}"
