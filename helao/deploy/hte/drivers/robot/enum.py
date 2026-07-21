"""Enumerations and model classes describing PAL robot methods (``CAM`` files).

Defines the GC sample categories, the enumeration of all supported PAL
``CAM`` files, and the tool labels recognized by the PAL software.

``_cam``, ``_positiontype``, and ``Spacingmethod`` are re-exported here from
``helao.hexagon.domain.models`` (P3a-PAL slice 3: they moved there so the
Base-free ``PalReconciliation`` domain service can use them without
importing this deploy-tree module) -- CAMS's construction below is
unaffected, it just references the imported names instead of local ones.
"""

from enum import Enum
from helao.core.models.sample import SampleType
from helao.hexagon.domain.models import _cam, _positiontype, Spacingmethod

__all__ = [
    "_cam",
    "_positiontype",
    "Spacingmethod",
    "GCsampletype",
    "CAMS",
    "PALtools",
]


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
