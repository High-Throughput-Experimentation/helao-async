"""Enums and constants for the OceanDirect spectrometer driver.

Trigger-mode values are **defined by each device's manual, not by the
OceanDirect SDK** -- ``Spectrometer.set_trigger_mode()`` takes a bare ``int``
and there is no vendor enum to import. The values below are the Ocean Insight
convention shared by the SR/FX/HDX families; a device whose manual disagrees
needs its own mapping, which is why the driver logs the requested mode and the
value read back rather than assuming the write took.
"""

__all__ = [
    "ODTrigMode",
    "LONG_FORMAT_KEYS",
    "MAX_METADATA_BUFFER_SIZE",
]

from enum import IntEnum


class ODTrigMode(IntEnum):
    """Spectrometer trigger source.

    Attributes:
        normal: Free-running; the device acquires continuously.
        software: Acquire on a software request.
        ext_synchronization: External synchronization (level) trigger.
        ext_hardware_edge: External hardware edge trigger.
        ext_hardware_level: External hardware level trigger.
    """

    normal = 0
    software = 1
    ext_synchronization = 2
    ext_hardware_edge = 3
    ext_hardware_level = 4


#: Column order of the long-format ``.hlo`` body, pinned via ``json_data_keys``
#: so it does not depend on which data message happens to arrive first.
#:
#: The wire encoding packs one spectrum per line with these five keys as
#: parallel equal-length arrays. Both HLO readers (``read_hlo_stream`` and
#: ``read_hlo_data_chunks``, ``helao/helpers/hlo_data.py``) concatenate
#: list-valued columns across lines, so a reader reconstructs exactly the
#: one-row-per-pixel long format -- ``spec_idx`` carries the per-spectrum
#: framing that the flattening would otherwise destroy.
LONG_FORMAT_KEYS = ["epoch_s", "spec_idx", "dev_ts_ns", "wl", "i"]

#: Hard cap on ``Advanced.get_spectrum_with_metadata()``'s ``buffer_size``.
#: The vendor documents a maximum of 15 spectra per read on FX/HDX; newer
#: OBP2 devices accept the call directly but the same ceiling applies, so the
#: buffered drain loops rather than asking for everything at once.
MAX_METADATA_BUFFER_SIZE = 15
