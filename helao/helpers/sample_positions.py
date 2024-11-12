__all__ = [
    "Custom",
    "CustomTypes",
    "VT15",
    "VT54",
    "VT70",
    "Positions",
]

from copy import deepcopy
from typing import (
    List,
    Dict,
    Optional,
    Union,
    Literal,
    Tuple,
    ForwardRef,
)
from enum import Enum
from pydantic import BaseModel, Field, root_validator

from helaocore.models.sample import (
    SampleUnion,
    NoneSample,
    object_to_sample,
)
from helao.helpers.print_message import print_message
from helaocore.helaodict import HelaoDict

from helao.helpers import logging

if logging.LOGGER is None:
    LOGGER = logging.make_logger(logger_name="sample_positions_standalone")
else:
    LOGGER = logging.LOGGER

VTUnion = ForwardRef("VTUnion")


class CustomTypes(str, Enum):
    cell = "cell"
    reservoir = "reservoir"
    injector = "injector"
    waste = "waste"


class Custom(BaseModel, HelaoDict):
    sample: SampleUnion = NoneSample()
    custom_name: str
    custom_type: CustomTypes
    blocked: bool = False
    max_vol_ml: Optional[float] = None

    def __repr__(self):
        return f"<custom_name:{self.custom_name} custom_type:{self.custom_type}>"

    def __str__(self):
        return f"custom_name:{self.custom_name}, custom_type:{self.custom_type}"

    def assembly_allowed(self) -> bool:
        if self.custom_type == CustomTypes.cell:
            return True
        elif self.custom_type == CustomTypes.reservoir:
            return False
        else:
            print_message(LOGGER, "archive", f"invalid 'custom_type': {self.custom_type}", error=True)
            return False

    def dilution_allowed(self) -> bool:
        if self.custom_type == CustomTypes.cell:
            return True
        elif self.custom_type == CustomTypes.reservoir:
            return False
        else:
            print_message(LOGGER, "archive", f"invalid 'custom_type': {self.custom_type}", error=True)
            return False

    def is_destroyed(self) -> bool:
        if self.custom_type == CustomTypes.injector:
            return True
        elif self.custom_type == CustomTypes.waste:
            return True
        else:
            return False

    def dest_allowed(self) -> bool:
        if self.custom_type == CustomTypes.cell:
            return True
        elif self.custom_type == CustomTypes.injector:
            return True
        elif self.custom_type == CustomTypes.reservoir:
            return False
        else:
            print_message(LOGGER, "archive", f"invalid 'custom_type': {self.custom_type}", error=True)
            return False

    def unload(self) -> SampleUnion:
        ret_sample = deepcopy(self.sample)
        self.blocked = False
        self.max_vol_ml = None
        self.sample = NoneSample()
        return ret_sample

    def load(self, sample_in: SampleUnion) -> Tuple[bool, SampleUnion]:
        if self.sample != NoneSample():
            print_message(
                LOGGER, "archive", "sample already loaded. Unload first to load new one.", error=True
            )
            return False, NoneSample()

        self.sample = deepcopy(sample_in)
        self.blocked = False
        print_message(LOGGER, "archive", f"loaded sample {sample_in.global_label}", info=True)
        return True, deepcopy(sample_in)


class _VT_template(BaseModel, HelaoDict):
    max_vol_ml: float
    VTtype: str
    positions: int  # = positions
    vials: List[bool] = Field(default=[])
    blocked: List[bool] = Field(default=[])
    samples: List[SampleUnion] = Field(default=[])
    # reset_tray()

    @root_validator(skip_on_failure=True)
    def check_init_VT(cls, values):
        positions = values.get("positions")
        vials = values.get("vials")
        blocked = values.get("blocked")
        samples = values.get("samples")
        if len(vials) != positions or len(blocked) != positions or len(samples) != positions:
            values["vials"] = [False for i in range(positions)]
            values["blocked"] = [False for i in range(positions)]
            values["samples"] = [NoneSample() for i in range(positions)]
        tmp_samples = []
        for sample in values["samples"]:
            # validate all samples and convert to BaseModel
            tmp_samples.append(object_to_sample(sample))
        values["samples"] = tmp_samples
        return values

    def __repr__(self):
        return f"<{self.VTtype} vials:{self.positions} max_vol_ml:{self.max_vol_ml}>"

    def __str__(self):
        return f"{self.VTtype} with vials:{self.positions} and max_vol_ml:{self.max_vol_ml}"

    def reset_tray(self):
        self.vials: List[bool] = [False for i in range(self.positions)]
        self.blocked: List[bool] = [False for i in range(self.positions)]
        self.samples: List[SampleUnion] = [NoneSample() for i in range(self.positions)]

    def first_empty(self):
        res = next((i for i, j in enumerate(self.vials) if not j and not self.blocked[i]), None)
        return res

    def first_full(self):
        res = next((i for i, j in enumerate(self.vials) if j), None)
        return res

    def update_vials(self, vial_dict):
        for i, vial in enumerate(vial_dict):
            try:
                self.vials[i] = bool(vial)
            except Exception:
                self.vials[i] = False

    def update_samples(self, samples):
        for i, sample in enumerate(samples):
            try:
                self.samples[i] = deepcopy(sample)
            except Exception:
                self.samples[i] = NoneSample()

    def unload(self) -> List[SampleUnion]:
        ret_sample = []
        for sample in self.samples:
            if sample != NoneSample():
                ret_sample.append(deepcopy(sample))

        self.reset_tray()
        return ret_sample

    def load(
        self,
        sample: SampleUnion,
        vial: int = None,
    ) -> SampleUnion:
        vial -= 1
        ret_sample = NoneSample()
        if sample == NoneSample():
            return ret_sample

        if vial + 1 <= self.positions:
            if isinstance(self.samples[vial], NoneSample) and not self.vials[vial]:
                self.vials[vial] = True
                self.samples[vial] = deepcopy(sample)
                ret_sample = deepcopy(self.samples[vial])

        return ret_sample


class VT15(_VT_template):
    VTtype: Literal["VT15"] = "VT15"
    positions: Literal[15] = 15
    max_vol_ml: Literal[10] = 10.0


class VT54(_VT_template):
    VTtype: Literal["VT54"] = "VT54"
    positions: Literal[54] = 54
    max_vol_ml: Literal[2] = 2.0


class VT70(_VT_template):
    VTtype: Literal["VT70"] = "VT70"
    positions: Literal[70] = 70
    max_vol_ml: Literal[1] = 1.0


class Positions(BaseModel, HelaoDict):
    # a dict keyed by tray_num, then slot_num and then the VT as value
    trays_dict: Dict[int, Dict[int, Union[VTUnion, None]]] = Field(default={})
    customs_dict: Dict[str, Custom] = Field(default={})


VTUnion = Union[
    VT15,
    VT54,
    VT70,
]

Positions.model_rebuild()
