from __future__ import annotations
from socket import gethostname
from uuid import UUID
from enum import Enum

from pydantic import BaseModel, validator, root_validator, Field
from pydantic.tools import parse_obj_as

import datetime
from typing import List, Optional, Union, Literal, Annotated
from typing import ForwardRef

from helao.core.version import get_hlo_version
from helao.core.helaodict import HelaoDict


"""Sample-type pydantic models (liquid, gas, solid, assembly, none) and helpers."""
__all__ = [
    "NoneSample",
    "SampleModel",
    "LiquidSample",
    "GasSample",
    "SolidSample",
    "AssemblySample",
    "SampleList",
    "SampleUnion",
    "TypedSampleUnion",
    "object_to_sample",
    "SampleInheritance",
    "SampleStatus",
]

SampleUnion = ForwardRef("SampleUnion")


class SampleType(str, Enum):
    """Discriminator naming the physical form of a sample."""

    liquid = "liquid"
    gas = "gas"
    solid = "solid"
    assembly = "assembly"


class SampleInheritance(str, Enum):
    """How a sample's identity propagates across actions.

    Members:
        none: No inheritance rule.
        give_only: The sample only provides material to descendants.
        receive_only: The sample only receives material.
        allow_both: Both giving and receiving are allowed.
        block_both: Neither giving nor receiving is allowed.
    """

    none = "none"
    give_only = "give_only"
    receive_only = "receive_only"
    allow_both = "allow_both"
    block_both = "block_both"


class SampleStatus(str, Enum):
    """Lifecycle state of a sample relative to the current action.

    Members:
        none: No status set.
        created: Sample was created during the action.
        destroyed: Sample was destroyed during the action.
        merged: Sample was merged with another sample.
        preserved: Sample exists before and after the action unchanged in identity.
        incorporated: Sample was combined into an assembly.
        recovered: Sample was extracted from an assembly.
        loaded: Sample was loaded into a station.
        unloaded: Sample was unloaded from a station.
    """

    none = "none"
    # pretty self-explanatory; the sample was created during the action.
    created = "created"
    # also self-explanatory
    destroyed = "destroyed"
    # merged with another liquid/gas/solid
    merged = "merged"
    # the sample exists before and after the action. e.g. an echem experiment
    preserved = "preserved"
    # the sample was combined with others in the action. E.g. the creation of an electrode assembly from electrodes and electrolytes
    incorporated = "incorporated"
    # the opposite of incorporated. E.g. an electrode assembly is taken apart, and the original electrodes are recovered, and further experiments may be done on those electrodes
    recovered = "recovered"
    loaded = "loaded"
    unloaded = "unloaded"


class SampleModel(BaseModel, HelaoDict):
    """Generic sample record with shared identifying and provenance fields.

    Subclassed by `LiquidSample`, `GasSample`, `SolidSample`, `AssemblySample`,
    and `NoneSample` to narrow `sample_type` and add type-specific fields.

    Attributes:
        hlo_version (Optional[str]): HELAO version stamped at construction.
        global_label (Optional[str]): Global identifier; `None` denotes a reference sample.
        sample_type (Optional[str]): Discriminator naming the sample form.
        sample_creation_timecode (Optional[int]): Creation time in nanoseconds since epoch.
        last_update (Optional[int]): Last-update time in nanoseconds since epoch.
        sample_no (Optional[int | str]): Local sample number or label.
        machine_name (Optional[str]): Source machine name.
        sample_hash (Optional[str]): Optional content hash.
        server_name (Optional[str]): Server that created the sample.
        action_uuid (List[UUID]): Actions that referenced this sample.
        sample_creation_action_uuid (Optional[UUID]): Action that created the sample.
        sample_creation_experiment_uuid (Optional[UUID]): Experiment that created the sample.
        sample_position (Optional[str]): Position label on the station.
        inheritance (Optional[SampleInheritance]): Inheritance rule (internal use).
        status (List[SampleStatus]): Lifecycle status flags (internal use).
        chemical (List[str]): Chemicals composing the sample.
        partial_molarity (List[str]): Per-chemical molarity entries.
        supplier (List[str]): Suppliers per chemical.
        lot_number (List[str]): Lot numbers per chemical.
        source (List[str]): Source labels.
        prep_date (Optional[datetime.date]): Preparation date.
        comment (Optional[str]): Free-form comment.
        etc (dict): Catch-all for additional fields not in the standard schema.
    """

    _hashinclude_ = {"global_label", "sample_type"}

    hlo_version: Optional[str] = Field(default_factory=get_hlo_version)
    global_label: Optional[str] = None  # is None for a ref sample
    sample_type: Optional[str] = None

    # time related fields
    sample_creation_timecode: Optional[int] = None  # epoch in ns
    last_update: Optional[int] = None  # epoch in ns
    # action_timestamp: Optional[str]  # "%y%m%d.%H%M%S%f"

    # labels
    sample_no: Optional[int | str] = None
    machine_name: Optional[str] = None
    sample_hash: Optional[str] = None
    server_name: Optional[str] = None

    # action related
    action_uuid: List[UUID] = Field(default=[])
    sample_creation_action_uuid: Optional[UUID] = None
    sample_creation_experiment_uuid: Optional[UUID] = None

    # metadata
    sample_position: Optional[str] = None
    inheritance: Optional[SampleInheritance] = None  # only for internal use
    status: List[SampleStatus] = Field(default=[])  # only for internal use
    chemical: List[str] = Field(default=[])
    partial_molarity: List[str] = Field(default=[])
    supplier: List[str] = Field(default=[])
    lot_number: List[str] = Field(default=[])
    source: List[str] = Field(default=[])
    prep_date: Optional[datetime.date] = None
    comment: Optional[str] = None
    etc: dict = Field(default={})

    def append_sample_status(self, new_status: "SampleStatus") -> None:
        """Append `new_status` to `status` via the guarded (log-only) transition."""
        from helao.core.models.status_transitions import sample_guarded_append

        sample_guarded_append(
            self.status, new_status, owner=f"sample {self.global_label or self.sample_type}"
        )

    def remove_sample_status(self, old_status: "SampleStatus") -> None:
        """Remove `old_status` from `status` via the guarded (log-only) transition."""
        from helao.core.models.status_transitions import sample_guarded_remove

        sample_guarded_remove(
            self.status, old_status, owner=f"sample {self.global_label or self.sample_type}"
        )

    def reset_sample_status(self, *new_statuses: "SampleStatus") -> None:
        """Replace `status` wholesale via the guarded (log-only) transition."""
        from helao.core.models.status_transitions import sample_guarded_reset

        sample_guarded_reset(
            self.status, new_statuses, owner=f"sample {self.global_label or self.sample_type}"
        )

    def create_initial_exp_dict(self) -> dict:
        """Return a dict of the shared sample fields used in experiment records."""
        if not isinstance(self.status, list):
            self.status = [self.status]  # not a lifecycle transition — list coercion

        return {
            "global_label": self.get_global_label(),
            "sample_type": self.sample_type,
            "sample_no": self.sample_no,
            "machine_name": (
                self.machine_name.lower()
                if self.machine_name is not None
                else gethostname().lower()
            ),
            "sample_creation_timecode": self.sample_creation_timecode,
            "last_update": self.last_update,
            "sample_position": self.sample_position,
            "inheritance": self.inheritance,
            "status": self.status,
        }

    def exp_dict(self) -> dict:
        """Return the experiment-record dict for this sample."""
        exp_dict = self.create_initial_exp_dict()
        return exp_dict

    def get_global_label(self) -> Optional[str]:
        """Return the stored global label."""
        return self.global_label

    def zero_volume(self):
        """Set `volume_ml` to 0 and update status to mark the sample destroyed."""
        if hasattr(self, "volume_ml"):
            self.volume_ml = 0
            if SampleStatus.destroyed not in self.status:
                self.append_sample_status(SampleStatus.destroyed)
            if SampleStatus.preserved in self.status:
                self.remove_sample_status(SampleStatus.preserved)

    def destroy_sample(self):
        """Mark the sample as destroyed (zeroing volume and updating status)."""
        self.zero_volume()
        if SampleStatus.preserved in self.status:
            self.remove_sample_status(SampleStatus.preserved)
        if SampleStatus.destroyed not in self.status:
            self.append_sample_status(SampleStatus.destroyed)

    def get_vol_ml(self) -> float:
        """Return `volume_ml` if defined on the subclass, else 0.0."""
        if hasattr(self, "volume_ml"):
            return self.volume_ml
        else:
            return 0.0

    def get_dilution_factor(self) -> float:
        """Return `dilution_factor` if defined on the subclass, else 1.0."""
        if hasattr(self, "dilution_factor"):
            return self.dilution_factor
        else:
            return 1.0


class NoneSample(SampleModel):
    """Sentinel sample representing the absence of a sample.

    Attributes:
        sample_type (Literal[None]): Always `None`.
        global_label (Literal[None]): Always `None`.
        inheritance (Optional[SampleInheritance]): Internal inheritance state.
        status (List[SampleStatus]): Internal lifecycle status flags.
    """

    sample_type: Literal[None] = None
    global_label: Literal[None] = None
    inheritance: Optional[SampleInheritance] = None  # only for internal use
    status: List[SampleStatus] = Field(default=[])  # only for internal use

    def get_global_label(self) -> None:
        """Always returns `None` for the sentinel sample."""
        return None

    def get_vol_ml(self) -> None:
        """Always returns `None`; no volume is associated with a `NoneSample`."""
        return None

    def exp_dict(self) -> dict:
        """Return the minimal experiment dict for the sentinel sample."""
        return {
            "global_label": self.get_global_label(),
            "sample_type": self.sample_type,
        }


class LiquidSample(SampleModel):
    """Liquid sample with volume, pH, dilution, and electrolyte fields.

    Attributes:
        sample_type (Literal[SampleType.liquid]): Discriminator pinned to ``liquid``.
        volume_ml (Optional[float]): Sample volume in millilitres.
        ph (Optional[float]): pH of the sample.
        dilution_factor (Optional[float]): Dilution factor relative to a stock.
        electrolyte (Optional[str]): Electrolyte identifier (see `Electrolyte`).
    """

    sample_type: Literal[SampleType.liquid] = SampleType.liquid
    volume_ml: Optional[float] = 0.0
    ph: Optional[float] = None
    dilution_factor: Optional[float] = 1.0
    electrolyte: Optional[str] = None

    def exp_dict(self) -> dict:
        """Return the liquid-sample experiment dict (with volume/pH/dilution)."""
        exp_dict = self.create_initial_exp_dict()
        exp_dict.update({"volume_ml": self.volume_ml})
        exp_dict.update({"ph": self.ph})
        exp_dict.update({"dilution_factor": self.dilution_factor})
        return exp_dict

    def get_global_label(self) -> Optional[str]:
        """Return the stored global label or derive one from machine name and `sample_no`."""
        if self.global_label is None:
            label = None
            machine_name = (
                self.machine_name.lower()
                if self.machine_name is not None
                else gethostname().lower()
            )
            label = f"{machine_name}__liquid__{self.sample_no}"
            return label
        else:
            return self.global_label


class SolidSample(SampleModel):
    """Solid sample tied to a plate id and sample number.

    Attributes:
        sample_type (Literal[SampleType.solid]): Discriminator pinned to ``solid``.
        machine_name (Optional[str]): Machine context for label formatting; defaults to ``"legacy"``.
        plate_id (Optional[int | str]): Plate identifier hosting the sample.
    """

    sample_type: Literal[SampleType.solid] = SampleType.solid
    machine_name: Optional[str] = "legacy"
    plate_id: Optional[int | str] = None

    def exp_dict(self) -> dict:
        """Return the solid-sample experiment dict (with `plate_id`)."""
        exp_dict = self.create_initial_exp_dict()
        exp_dict.update({"plate_id": self.plate_id})
        return exp_dict

    def get_global_label(self) -> Optional[str]:
        """Return the stored global label or derive one from machine, plate, and sample number."""
        if self.global_label is None:
            label = None
            machine_name = (
                self.machine_name.lower() if self.machine_name is not None else "legacy"
            )
            label = f"{machine_name}__solid__{self.plate_id}_{self.sample_no}"
            return label
        else:
            return self.global_label

    @root_validator(pre=False, skip_on_failure=True)
    def validate_global_label(cls, values):
        """Force `global_label` to ``{machine}__solid__{plate}_{sample}`` after validation."""
        machine_name = values.get("machine_name")
        plate_id = values.get("plate_id")
        sample_no = values.get("sample_no")
        values["global_label"] = f"{machine_name}__solid__{plate_id}_{sample_no}"
        return values


class GasSample(SampleModel):
    """Gas sample with volume and dilution-factor fields.

    Attributes:
        sample_type (Literal[SampleType.gas]): Discriminator pinned to ``gas``.
        volume_ml (Optional[float]): Volume in millilitres.
        dilution_factor (Optional[float]): Dilution factor relative to a stock.
    """

    sample_type: Literal[SampleType.gas] = SampleType.gas
    volume_ml: Optional[float] = 0.0
    dilution_factor: Optional[float] = 1.0

    def exp_dict(self) -> dict:
        """Return the gas-sample experiment dict (with volume and dilution)."""
        exp_dict = self.create_initial_exp_dict()
        exp_dict.update({"volume_ml": self.volume_ml})
        exp_dict.update({"dilution_factor": self.dilution_factor})
        return exp_dict

    def get_global_label(self) -> Optional[str]:
        """Return the stored global label or derive one from machine name and `sample_no`."""
        if self.global_label is None:
            label = None
            machine_name = (
                self.machine_name.lower()
                if self.machine_name is not None
                else gethostname().lower()
            )
            label = f"{machine_name}__gas__{self.sample_no}"
            return label
        else:
            return self.global_label


class AssemblySample(SampleModel):
    """Composite sample built from constituent samples.

    Attributes:
        sample_type (Literal[SampleType.assembly]): Discriminator pinned to ``assembly``.
        parts (List): Constituent samples (any sample subtype).
        sample_position (Optional[str]): Position label; default ``"cell1_we"``.
        parent_assembly_label (Optional[str]): Label of a parent assembly, if any.
    """

    sample_type: Literal[SampleType.assembly] = SampleType.assembly
    parts: List[SampleUnion] = Field(default=[])
    sample_position: Optional[str] = "cell1_we"  # usual default assembly position
    parent_assembly_label: Optional[str] = None

    def get_global_label(self) -> Optional[str]:
        """Return the stored global label or derive one from machine, position, and creation time."""
        if self.global_label is None:
            label = None
            machine_name = (
                self.machine_name.lower()
                if self.machine_name is not None
                else gethostname().lower()
            )
            label = f"{machine_name}__assembly__{self.sample_position}__{self.sample_creation_timecode}"
            return label
        else:
            return self.global_label

    @validator("parts", pre=True)
    def validate_parts(cls, value):
        """Coerce a `None` `parts` value into an empty list."""
        if value is None:
            return []
        return value

    def exp_dict(self) -> dict:
        """Return the assembly experiment dict including a parts label list."""
        exp_dict = self.create_initial_exp_dict()
        exp_dict.update({"assembly_parts": self.get_assembly_parts_exp_dict()})
        return exp_dict

    def get_assembly_parts_exp_dict(self) -> list:
        """Return the list of global labels for each non-`None` constituent part."""
        part_dict_list = []
        for part in self.parts:
            if part is not None:
                # return full dict
                # part_dict_list.append(part.exp_dict())
                # return only the label (preferred)
                part_dict_list.append(part.get_global_label())
            else:
                pass
        return part_dict_list


# TODO: this needs to be removed in the near future
# and all calls to SampleList replaced by SampleUnion
class SampleList(BaseModel, HelaoDict):
    """Container holding a list of samples of any supported type.

    Attributes:
        samples (Optional[List]): The contained samples (union of sample types).
    """

    samples: Optional[List[SampleUnion]] = Field(default=[])


# Design C, two-stage nested union (CARDS P3 3c, D1): the four enum-tagged
# subtypes get true discriminator routing; NoneSample and the SampleModel
# fallback sit in the outer (smart) union so today's acceptance surface is
# preserved by construction. See CARDS_REFACTOR_P3C.md D1.
TypedSampleUnion = Annotated[
    Union[AssemblySample, LiquidSample, GasSample, SolidSample],
    Field(discriminator="sample_type"),
]
SampleUnion = Union[TypedSampleUnion, NoneSample, SampleModel]


def object_to_sample(data):
    """Coerce a dict or `BaseModel` into the matching concrete sample type.

    Args:
        data: Mapping (or `BaseModel`) carrying the sample fields, including
            a `sample_type` discriminator.

    Returns:
        A concrete sample instance from `SampleUnion`.

    Raises:
        Exception: Propagated when `parse_obj_as` cannot match a sample type.
    """
    if isinstance(data, BaseModel):
        data = data.model_dump()
    try:
        sample = parse_obj_as(SampleUnion, data)
    except Exception as e:
        print(f"Error: {e}")
        print(f"Data: {data}")
        raise e
    return sample


AssemblySample.model_rebuild()
SampleList.model_rebuild()
