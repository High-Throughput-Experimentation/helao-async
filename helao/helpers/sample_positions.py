"""Pydantic models describing custom sample holders and vial trays.

Defines :class:`Custom` (named cell/reservoir/injector/waste positions),
:class:`_VT_template` and the concrete vial-tray models :class:`VT15`,
:class:`VT54`, :class:`VT70`, and the :class:`Positions` container that maps
``tray_num -> slot_num -> tray`` plus a name-keyed ``customs_dict``.
"""

__all__ = [
    "Custom",
    "CustomTypes",
    "VT15",
    "VT54",
    "VT70",
    "Positions",
]

from copy import deepcopy
from enum import Enum
from typing import ForwardRef, Literal, Optional, Union

from pydantic import BaseModel, Field, root_validator

from helao.core.helaodict import HelaoDict
from helao.core.models.sample import (
    AssemblySample,
    GasSample,
    LiquidSample,
    NoneSample,
    SolidSample,
    object_to_sample,
)
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
VTUnion = ForwardRef("VTUnion")


class CustomTypes(str, Enum):
    """Enumerated roles for :class:`Custom` sample positions."""

    cell = "cell"
    reservoir = "reservoir"
    injector = "injector"
    waste = "waste"


class Custom(BaseModel, HelaoDict):
    """Named single-sample holder of a particular :class:`CustomTypes` role.

    Attributes:
        sample: The currently loaded sample (or :class:`NoneSample` when empty).
        custom_name: Position label unique within the configuration.
        custom_type: Role determining assembly/dilution/destination behavior.
        blocked: True when the position is administratively blocked.
        max_vol_ml: Optional maximum holdup volume.
    """

    sample: Optional[
        Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
    ] = NoneSample()
    custom_name: str
    custom_type: CustomTypes
    blocked: bool = False
    max_vol_ml: Optional[float] = None

    def __repr__(self):
        return f"<custom_name:{self.custom_name} custom_type:{self.custom_type}>"

    def __str__(self):
        return f"custom_name:{self.custom_name}, custom_type:{self.custom_type}"

    def assembly_allowed(self) -> bool:
        """Return True if this position may participate in an assembly (cells only)."""
        if self.custom_type == CustomTypes.cell:
            return True
        elif self.custom_type == CustomTypes.reservoir:
            return False
        else:
            LOGGER.error(f"invalid 'custom_type': {self.custom_type}")
            return False

    def dilution_allowed(self) -> bool:
        """Return True if dilution updates are valid for this position (cells only)."""
        if self.custom_type == CustomTypes.cell:
            return True
        elif self.custom_type == CustomTypes.reservoir:
            return False
        else:
            LOGGER.error(f"invalid 'custom_type': {self.custom_type}")
            return False

    def is_destroyed(self) -> bool:
        """Return True for terminal positions (injector, waste)."""
        if self.custom_type == CustomTypes.injector:
            return True
        elif self.custom_type == CustomTypes.waste:
            return True
        else:
            return False

    def dest_allowed(self) -> bool:
        """Return True if this position is a valid transfer destination."""
        if self.custom_type == CustomTypes.cell:
            return True
        elif self.custom_type == CustomTypes.injector:
            return True
        elif self.custom_type == CustomTypes.reservoir:
            return False
        else:
            LOGGER.error(f"invalid 'custom_type': {self.custom_type}")
            return False

    def unload(
        self,
    ) -> Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]:
        """Remove and return the loaded sample, clearing block/volume state."""
        ret_sample = deepcopy(self.sample)
        self.blocked = False
        self.max_vol_ml = None
        self.sample = NoneSample()
        return ret_sample

    def load(
        self,
        sample_in: Union[
            AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample
        ],
    ) -> tuple[
        bool, Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
    ]:
        """Load a sample into this position if it is currently empty.

        Args:
            sample_in: Sample to load.

        Returns:
            ``(True, copy_of_loaded_sample)`` on success, or
            ``(False, NoneSample())`` if a sample is already loaded.
        """
        if self.sample != NoneSample():
            LOGGER.error("sample already loaded. Unload first to load new one.")
            return False, NoneSample()

        self.sample = deepcopy(sample_in)
        self.blocked = False
        LOGGER.info(f"loaded sample {sample_in.global_label}")
        return True, deepcopy(sample_in)


class _VT_template(BaseModel, HelaoDict):
    """Base model for a fixed-size vial tray of identical vial volumes.

    Attributes:
        max_vol_ml: Per-vial maximum volume.
        VTtype: Tray type tag (e.g. ``"VT15"``, ``"VT54"``, ``"VT70"``).
        positions: Number of vial slots in this tray.
        vials: Per-slot occupancy flags.
        blocked: Per-slot administrative block flags.
        samples: Per-slot sample contents (defaults to :class:`NoneSample`).
    """

    max_vol_ml: float
    VTtype: str
    positions: int  # = positions
    vials: list[bool] = Field(default=[])
    blocked: list[bool] = Field(default=[])
    samples: list[
        Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
    ] = Field(default=[])
    # reset_tray()

    @root_validator(skip_on_failure=True)
    def check_init_VT(cls, values):
        """Ensure ``vials``, ``blocked``, and ``samples`` are aligned to ``positions``.

        Reinitializes any list whose length disagrees with ``positions`` and
        coerces every sample entry through :func:`object_to_sample`.
        """
        positions = values.get("positions")
        vials = values.get("vials")
        blocked = values.get("blocked")
        samples = values.get("samples")
        if (
            len(vials) != positions
            or len(blocked) != positions
            or len(samples) != positions
        ):
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
        """Clear all vial, block, and sample state to the empty defaults."""
        self.vials: list[bool] = [False for i in range(self.positions)]
        self.blocked: list[bool] = [False for i in range(self.positions)]
        self.samples: list[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = [NoneSample() for i in range(self.positions)]

    def first_empty(self) -> Optional[int]:
        """Return the index of the first empty, non-blocked vial slot, or None."""
        res = next(
            (i for i, j in enumerate(self.vials) if not j and not self.blocked[i]), None
        )
        return res

    def first_full(self) -> Optional[int]:
        """Return the index of the first occupied vial slot, or None."""
        res = next((i for i, j in enumerate(self.vials) if j), None)
        return res

    def update_vials(self, vial_dict):
        """Set the occupancy flags from an iterable of boolean-like values.

        Args:
            vial_dict: Iterable of truthy values; entries that cannot be cast
                to ``bool`` are set to False.
        """
        for i, vial in enumerate(vial_dict):
            try:
                self.vials[i] = bool(vial)
            except Exception:
                self.vials[i] = False

    def update_samples(self, samples):
        """Replace per-slot samples from an iterable; fall back to :class:`NoneSample` on error."""
        for i, sample in enumerate(samples):
            try:
                self.samples[i] = deepcopy(sample)
            except Exception:
                self.samples[i] = NoneSample()

    def unload(
        self,
    ) -> list[Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]]:
        """Return copies of all non-empty samples and reset the tray."""
        ret_sample = []
        for sample in self.samples:
            if sample != NoneSample():
                ret_sample.append(deepcopy(sample))

        self.reset_tray()
        return ret_sample

    def load(
        self,
        sample: Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample],
        vial: Optional[int] = None,
    ) -> Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]:
        """Load ``sample`` into the 1-indexed ``vial`` slot, if empty.

        Args:
            sample: Sample to load; :class:`NoneSample` is a no-op.
            vial: 1-based vial index.

        Returns:
            A copy of the loaded sample on success, otherwise :class:`NoneSample`.
        """
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
    """15-position vial tray with 10 ml vials."""

    VTtype: Literal["VT15"] = "VT15"
    positions: Literal[15] = 15
    max_vol_ml: Literal[10] = 10.0


class VT54(_VT_template):
    """54-position vial tray with 2 ml vials."""

    VTtype: Literal["VT54"] = "VT54"
    positions: Literal[54] = 54
    max_vol_ml: Literal[2] = 2.0


class VT70(_VT_template):
    """70-position vial tray with 1 ml vials."""

    VTtype: Literal["VT70"] = "VT70"
    positions: Literal[70] = 70
    max_vol_ml: Literal[1] = 1.0


class Positions(BaseModel, HelaoDict):
    """Container mapping tray/slot to tray models and named custom positions.

    Attributes:
        trays_dict: Nested mapping ``tray_num -> slot_num -> VT instance``.
        customs_dict: Mapping of ``custom_name -> Custom`` position.
    """

    # a dict keyed by tray_num, then slot_num and then the VT as value
    trays_dict: dict[int, dict[int, Union[VTUnion, None]]] = Field(default={})
    customs_dict: dict[str, Custom] = Field(default={})


VTUnion = Union[
    VT15,
    VT54,
    VT70,
]

Positions.model_rebuild()
