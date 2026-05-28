"""Enumerations and model classes describing PAL robot methods (``CAM`` files).

Defines the position kinds, GC sample categories, the per-method ``_cam`` model
holding the source/destination policy and TTL flags, the enumeration of all
supported PAL ``CAM`` files, sample-spacing methods, and the tool labels
recognized by the PAL software.
"""

from enum import Enum
from pydantic import BaseModel
from typing import Optional
from helao.core.models.sample import SampleType


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


class _positiontype(str, Enum):
    """Categories of source/destination positions understood by the PAL driver."""

    tray = "tray"
    custom = "custom"
    next_empty_vial = "next_empty_vial"
    next_full_vial = "next_full_vial"


class GCsampletype(str, Enum):
    """Sample phase categories accepted for GC injection methods."""

    liquid = "liquid"
    gas = "gas"
    none = "none"
    # solid = "solid"
    # assembly = "assembly"


class CAMS(Enum):
    """Catalog of supported PAL ``CAM`` methods keyed by method name.

    Each member's value is a :class:`_cam` template; ``file_name`` and
    ``file_path`` are populated by the driver from server configuration.
    """


    transfer_tray_tray = _cam(
        name="transfer_tray_tray",
        file_name="",  # filled in from config later
        sample_out_type=SampleType.liquid,
        source=_positiontype.tray,
        dest=_positiontype.tray,
    )

    transfer_custom_tray = _cam(
        name="transfer_custom_tray",
        file_name="",  # filled in from config later
        sample_out_type=SampleType.liquid,
        source=_positiontype.custom,
        dest=_positiontype.tray,
    )

    transfer_tray_custom = _cam(
        name="transfer_tray_custom",
        file_name="",  # filled in from config later
        sample_out_type=SampleType.liquid,
        source=_positiontype.tray,
        dest=_positiontype.custom,
    )

    transfer_custom_custom = _cam(
        name="transfer_tray_custom",
        file_name="",  # filled in from config later
        sample_out_type=SampleType.liquid,
        source=_positiontype.custom,
        dest=_positiontype.custom,
    )

    injection_custom_GC_gas_wait = _cam(
        name="injection_custom_GC_gas_wait",
        file_name="",  # filled in from config later
        sample_out_type=SampleType.gas,
        source=_positiontype.custom,
        dest=_positiontype.custom,
    )

    injection_custom_GC_gas_start = _cam(
        name="injection_custom_GC_gas_start",
        file_name="",  # filled in from config later
        sample_out_type=SampleType.gas,
        source=_positiontype.custom,
        dest=_positiontype.custom,
    )

    injection_custom_GC_liquid_wait = _cam(
        name="injection_custom_GC_liquid_wait",
        file_name="",  # filled in from config later
        sample_out_type=SampleType.liquid,
        source=_positiontype.custom,
        dest=_positiontype.custom,
    )

    injection_custom_GC_liquid_start = _cam(
        name="injection_custom_GC_liquid_start",
        file_name="",  # filled in from config later
        sample_out_type=SampleType.liquid,
        source=_positiontype.custom,
        dest=_positiontype.custom,
    )

    injection_tray_GC_liquid_wait = _cam(
        name="injection_tray_GC_liquid_wait",
        file_name="",  # filled in from config later
        sample_out_type=SampleType.liquid,
        source=_positiontype.tray,
        dest=_positiontype.custom,
    )

    injection_tray_GC_liquid_start = _cam(
        name="injection_tray_GC_liquid_start",
        file_name="",  # filled in from config later
        sample_out_type=SampleType.liquid,
        source=_positiontype.tray,
        dest=_positiontype.custom,
    )

    injection_tray_GC_gas_wait = _cam(
        name="injection_tray_GC_gas_wait",
        file_name="",  # filled in from config later
        sample_out_type=SampleType.gas,
        source=_positiontype.tray,
        dest=_positiontype.custom,
    )

    injection_tray_GC_gas_start = _cam(
        name="injection_tray_GC_gas_start",
        file_name="",  # filled in from config later
        sample_out_type=SampleType.gas,
        source=_positiontype.tray,
        dest=_positiontype.custom,
    )

    injection_custom_HPLC = _cam(
        name="injection_custom_HPLC",
        file_name="",  # filled in from config later
        sample_out_type=SampleType.liquid,
        source=_positiontype.custom,
        dest=_positiontype.custom,
    )

    injection_tray_HPLC = _cam(
        name="injection_tray_HPLC",
        file_name="",  # filled in from config later
        sample_out_type=SampleType.liquid,
        source=_positiontype.tray,
        dest=_positiontype.custom,
    )

    deepclean = _cam(
        name="deepclean",
        file_name="",  # filled in from config later
    )

    none = _cam(
        name="",
        file_name="",
    )

    # transfer_liquid = _cam(name="transfer_liquid",
    #                       file_name = "lcfc_transfer.cam", # from config later
    #                       sample_out_type = SampleType.liquid,
    #                       source = _positiontype.custom,
    #                       dest = _positiontype.next_empty_vial,
    #                      )

    archive = _cam(
        name="archive",
        file_name="",  # from config later
        sample_out_type=SampleType.liquid,
        source=_positiontype.custom,
        dest=_positiontype.next_empty_vial,
    )

    # fillfixed = _cam(name="fillfixed",
    #                   file_name = "lcfc_fill_hardcodedvolume.cam", # from config later
    #                   sample_out_type = SampleType.liquid,
    #                   source = _positiontype.custom,
    #                   dest = _positiontype.custom,
    #                 )

    # fill = _cam(name="fill",
    #             file_name = "lcfc_fill.cam", # from config later
    #             sample_out_type = SampleType.liquid,
    #             source = _positiontype.custom,
    #             dest = _positiontype.custom,
    #          )

    # test = _cam(name="test",
    #             file_name = "relay_actuation_test2.cam", # from config later
    #            )

    # autodilute = _cam(name="autodilute",
    #               file_name = "lcfc_dilute.cam", # from config later
    #               sample_out_type = SampleType.liquid,
    #               source = _positiontype.custom,
    #               dest = _positiontype.next_full_vial,
    #              )

    # dilute = _cam(name="dilute",
    #               file_name = "lcfc_dilute.cam", # from config later
    #               sample_out_type = SampleType.liquid,
    #               source = _positiontype.custom,
    #               dest = _positiontype.tray,
    #              )


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


#    power = "power"
#    exponential = "exponential"


class PALtools(str, Enum):
    """PAL syringe tool identifiers as recognized by the PAL software."""

    LS1 = "LS 1"
    LS2 = "LS 2"
    LS3 = "LS 3"
    LS4 = "LS 4"
    LS5 = "LS 5"
    HS1 = "HS 1"
    HS2 = "HS 2"
