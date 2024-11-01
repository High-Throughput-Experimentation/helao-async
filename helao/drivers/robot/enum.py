from enum import Enum
from pydantic import BaseModel
from helaocore.models.sample import SampleType


class _cam(BaseModel):
    name: str = None
    file_name: str = None
    file_path: str = None
    sample_out_type: str = None  # should not be assembly, only liquid, solid...
    ttl_start: bool = False
    ttl_continue: bool = False
    ttl_done: bool = False

    source: str = None
    dest: str = None

class _positiontype(str, Enum):
    tray = "tray"
    custom = "custom"
    next_empty_vial = "next_empty_vial"
    next_full_vial = "next_full_vial"

class GCsampletype(str, Enum):
    liquid = "liquid"
    gas = "gas"
    none = "none"
    # solid = "solid"
    # assembly = "assembly"


class CAMS(Enum):

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
    linear = "linear"  # 1, 2, 3, 4, 5, ...
    geometric = "gemoetric"  # 1, 2, 4, 8, 16
    custom = "custom"  # list of absolute times for each run


#    power = "power"
#    exponential = "exponential"


class PALtools(str, Enum):
    LS1 = "LS 1"
    LS2 = "LS 2"
    LS3 = "LS 3"
    LS4 = "LS 4"
    LS5 = "LS 5"
    HS1 = "HS 1"
    HS2 = "HS 2"