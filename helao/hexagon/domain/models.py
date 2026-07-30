"""D8 model reuse surface (master spec §4.2.1).

The hexagon domain does NOT define run models. It re-exports the post-CARDS
pydantic models from helao.core.models / helao.helpers.premodels so that:
(a) artifact schemas stay byte-identical (model -> clean_dict -> dict), and
(b) ports/ can reference model types while importing only helao.hexagon.domain
    (boundary rule, spec §4.1).

Known accepted smells (Q4, master spec §14): core/models/server.py imports
premodels.Action; SampleUnion keeps the bare-SampleModel accept-anything
fallback; both are parity requirements, not bugs to fix here.

Exception (P3a-PAL slice 3): the PAL algorithm models (`_positiontype`,
`Spacingmethod`, `_cam`, `PALposition`, `PalAction`, `PalMicroCam`, `PalCam`)
are genuinely DEFINED here rather than re-exported, because the Base-free
`PalReconciliation` domain service (helao.hexagon.domain.pal_reconciliation)
needs them and cannot import from the deploy-tree modules that used to
define them (`helao.deploy.hte.drivers.robot.pal_driver`/`enum.py` -- the
former is the composition root that constructs `PalReconciliation`, so
importing back from it would be circular; the latter is deploy-tree, off
limits to a domain service). Both modules import these back and keep
re-exporting them from their own namespaces, so no import surface external
callers (`pal_server.py`) rely on changes.
"""

from enum import Enum
from typing import Optional, Union

from pydantic import BaseModel, Field

from helao.core.error import ErrorCodes
from helao.core.helaodict import HelaoDict
from helao.core.models.action import ActionModel, ShortActionModel
from helao.core.models.action_start_condition import ActionStartCondition
from helao.core.models.analysis import (
    AnalysisDataModel,
    AnalysisModel,
    AnalysisOutputModel,
    ShortAnalysisModel,
)
from helao.core.models.data import DataModel, DataPackageModel
from helao.core.models.experiment import ExperimentModel, ShortExperimentModel
from helao.core.models.file import (
    FileConn,
    FileConnParams,
    FileInfo,
    HloFileGroup,
    HloHeaderModel,
)
from helao.core.models.hlostatus import HloStatus
from helao.core.models.machine import MachineModel
from helao.core.models.orchstatus import LoopIntent, LoopStatus, OrchStatus
from helao.core.models.process import ProcessModel, ShortProcessModel
from helao.core.models.process_contrib import ProcessContrib
from helao.core.models.run_dir import RunDir
from helao.core.models.run_use import RunUse
from helao.core.models.sample import (
    AssemblySample,
    GasSample,
    LiquidSample,
    NoneSample,
    SampleInheritance,
    SampleModel,
    SampleStatus,
    SampleType,
    SampleUnion,
    SolidSample,
    object_to_sample,
)
from helao.core.models.sequence import SequenceModel, ShortSequenceModel
from helao.core.models.server import (
    ActionServerModel,
    EndpointModel,
    GlobalStatusModel,
)
from helao.helpers.premodels import (
    Action,
    ActionPlanMaker,
    Experiment,
    ExperimentPlanMaker,
    Sequence,
)

# ---------------------------------------------------------------------------
# PAL algorithm models (P3a-PAL slice 3) -- see the module docstring's
# "Exception" note. Lifted verbatim from helao/deploy/hte/drivers/robot/
# enum.py (_positiontype, Spacingmethod, _cam) and pal_driver.py (PALposition,
# PalAction, PalMicroCam, PalCam); both modules import these back.
# ---------------------------------------------------------------------------


class _positiontype(str, Enum):
    """Categories of source/destination positions understood by the PAL driver."""

    tray = "tray"
    custom = "custom"
    next_empty_vial = "next_empty_vial"
    next_full_vial = "next_full_vial"


class Spacingmethod(str, Enum):
    """Scheduling spacing options for repeated PAL runs.

    Attributes:
        linear: Equal intervals between runs.
        geometric: Intervals scaled by a geometric factor.
        custom: Caller-supplied list of absolute timestamps.
    """

    linear = "linear"  # 1, 2, 3, 4, 5, ...
    geometric = "gemoetric"  # 1, 2, 4, 8, 16
    custom = "custom"  # list of absolute times for each run


class _cam(BaseModel):
    """Describes a single PAL ``CAM`` method.

    Attributes:
        name: Method name as referenced by the orchestrator.
        file_name: Vendor ``.cam`` file name; filled in at runtime from config.
        file_path: Directory containing the ``.cam`` file.
        sample_out_type: Output sample type produced by the method.
        ttl_start: Whether the method emits the start TTL trigger.
        ttl_continue: Whether the method emits the continue TTL trigger.
        ttl_done: Whether the method emits the done TTL trigger.
        source: Source position kind (see :class:`_positiontype`).
        dest: Destination position kind (see :class:`_positiontype`).
    """

    name: Optional[str] = None
    file_name: Optional[str] = None
    file_path: Optional[str] = None
    sample_out_type: Optional[str] = (
        None  # should not be assembly, only liquid, solid...
    )
    ttl_start: bool = False
    ttl_continue: bool = False
    ttl_done: bool = False

    source: Optional[str] = None
    dest: Optional[str] = None


class PALposition(BaseModel, HelaoDict):
    """Source or destination position resolved against the archive.

    Attributes:
        position: Position kind (custom name or ``tray``).
        samples_initial: Samples present in the position before the action.
        samples_final: Samples present in the position after the action.
        tray: Tray index when ``position`` is a tray.
        slot: Slot index within the tray.
        vial: Vial index within the slot.
        error: Result of position checks.
    """

    position: Optional[str] = None  # dest can be cust. or tray
    samples_initial: list[
        Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
    ] = Field(default=[])
    samples_final: list[
        Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
    ] = Field(default=[])
    tray: Optional[int] = None
    slot: Optional[int] = None
    vial: Optional[int] = None
    error: Optional[ErrorCodes] = ErrorCodes.none


class PalAction(BaseModel, HelaoDict):
    """One concrete execution of a microcam, capturing samples and trigger times.

    Attributes:
        samples_in: Resolved input samples for this run.
        samples_out: Output samples (initially references; resolved when stored).
        dest: Final destination position descriptor.
        source: Final source position descriptor.
        dilute: Per-input flag indicating whether the sample is being diluted.
        dilute_type: Sample type associated with each dilution entry.
        samples_in_delta_vol_ml: Volume change in mL applied to each input sample.
        start_time: PAL ``start`` trigger timestamp.
        continue_time: PAL ``continue`` trigger timestamp.
        done_time: PAL ``done`` trigger timestamp.
    """

    samples_in: list[
        Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
    ] = Field(default=[])
    samples_out: list[
        Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
    ] = Field(default=[])

    dest: Optional[PALposition] = None
    source: Optional[PALposition] = None

    dilute: list[bool] = Field(default=[])
    dilute_type: list[Union[str, None]] = Field(default=[])
    samples_in_delta_vol_ml: list[float] = Field(default=[])

    start_time: Optional[int] = None
    continue_time: Optional[int] = None
    done_time: Optional[int] = None


class PalMicroCam(BaseModel, HelaoDict):
    """A single PAL method invocation, optionally repeated.

    Attributes:
        method: Name of the ``CAMS`` member to invoke.
        tool: PAL tool string (e.g. ``"LS 1"``).
        volume_ul: Aspirate/dispense volume in microliters.
        requested_dest: Caller-supplied destination position.
        requested_source: Caller-supplied source position.
        wash1: Whether to perform wash stage 1 after the action.
        wash2: Whether to perform wash stage 2.
        wash3: Whether to perform wash stage 3.
        wash4: Whether to perform wash stage 4.
        path_methodfile: Resolved absolute path to the method ``.cam`` file.
        rshs_pal_logfile: Path of the PAL auxiliary log file.
        cam: Resolved :class:`_cam` descriptor for the method.
        repeat: Number of additional repeats beyond the first run.
        run: Per-repeat list of :class:`PalAction` results.
    """

    method: Optional[str] = None  # name of methods
    tool: Optional[str] = None
    volume_ul: int = 0  # uL
    requested_dest: PALposition = PALposition()
    requested_source: PALposition = PALposition()

    wash1: bool = False
    wash2: bool = False
    wash3: bool = False
    wash4: bool = False

    path_methodfile: str = ""  # all should be in the same folder
    rshs_pal_logfile: str = ""  # one PAL action logs into one logfile
    cam: _cam = _cam()
    repeat: int = 0

    run: list[PalAction] = Field(default=[])


class PalCam(BaseModel, HelaoDict):
    """Composite PAL job: a list of microcams executed ``totalruns`` times.

    Attributes:
        samples_in: Input samples carried at the job level.
        samples_out: Output samples accumulated from microcams.
        microcams: Ordered list of :class:`PalMicroCam` invocations.
        totalruns: Number of full repetitions of the microcam list.
        sampleperiod: Per-run scheduling offsets in seconds.
        spacingmethod: Spacing strategy across runs.
        spacingfactor: Factor for geometric spacing.
        timeoffset: Offset (s) subtracted from the requested per-run delay.
        cur_run: Current run index during execution.
        joblist: Internal list of ``/loadmethod`` PAL commands.
        joblist_time: Timestamp when the joblist was submitted.
        aux_output_filepath: Path used for the PAL auxiliary log.
    """

    samples_in: list[
        Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
    ] = Field(default=[])
    samples_out: list[
        Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
    ] = Field(default=[])

    microcams: list[PalMicroCam] = Field(default=[])

    totalruns: int = 1
    sampleperiod: list[float] = Field(default=[])
    spacingmethod: Spacingmethod = "linear"
    spacingfactor: float = 1.0
    timeoffset: float = 0.0  # sec
    cur_run: int = 0

    joblist: list = Field(default=[])
    joblist_time: Optional[int] = None
    aux_output_filepath: Optional[str] = None


__all__ = [
    "Action",
    "ActionModel",
    "ActionPlanMaker",
    "ActionServerModel",
    "ActionStartCondition",
    "AnalysisDataModel",
    "AnalysisModel",
    "AnalysisOutputModel",
    "AssemblySample",
    "DataModel",
    "DataPackageModel",
    "EndpointModel",
    "ErrorCodes",
    "Experiment",
    "ExperimentModel",
    "ExperimentPlanMaker",
    "FileConn",
    "FileConnParams",
    "FileInfo",
    "GasSample",
    "GlobalStatusModel",
    "HelaoDict",
    "HloFileGroup",
    "HloHeaderModel",
    "HloStatus",
    "LiquidSample",
    "LoopIntent",
    "LoopStatus",
    "MachineModel",
    "NoneSample",
    "OrchStatus",
    "PALposition",
    "PalAction",
    "PalCam",
    "PalMicroCam",
    "ProcessContrib",
    "ProcessModel",
    "RunDir",
    "RunUse",
    "SampleInheritance",
    "SampleModel",
    "SampleStatus",
    "SampleType",
    "SampleUnion",
    "Sequence",
    "SequenceModel",
    "ShortActionModel",
    "ShortAnalysisModel",
    "ShortExperimentModel",
    "ShortProcessModel",
    "ShortSequenceModel",
    "SolidSample",
    "Spacingmethod",
    "object_to_sample",
]
