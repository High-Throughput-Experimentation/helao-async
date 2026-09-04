"""Enums and constants for the OceanDirect spectrometer driver.

Trigger-mode values are **defined by each device's manual, not by the
OceanDirect SDK** -- ``Spectrometer.set_trigger_mode()`` takes a bare ``int``
and there is no vendor enum to import. :class:`SRTrigMode` therefore holds the
**Ocean SR series** values, taken from *Ocean SR Series* UM-SR-Series_1025
p.19, and is named for that family rather than for OceanDirect as a whole: an
FX or HDX on this driver would need its own mapping. The driver validates a
requested mode against this enum and reads the applied value back, so a device
that disagrees says so instead of silently acquiring in the wrong mode.
"""

__all__ = [
    "SRTrigMode",
    "HSAM_UNSUPPORTED_TRIGGER_MODES",
    "LONG_FORMAT_KEYS",
    "SINGLE_SHOT_KEYS",
    "MAX_METADATA_BUFFER_SIZE",
]

from enum import IntEnum


class SRTrigMode(IntEnum):
    """Ocean SR-series trigger source (manual p.19).

    These are the only three modes the SR series has. An earlier version of
    this enum carried the five-value FX/HDX convention
    (``normal``/``software``/``ext_synchronization``/``ext_hardware_edge``/
    ``ext_hardware_level``), under which the natural default for a triggered
    acquisition was ``3`` -- a value an SR device rejects outright.

    Attributes:
        software: The Trigger Event comes from a host software command, and
            integration time is whatever software configured. This is the
            device's power-on mode, and the mode a plain ``get_spectrum()``
            uses. It is **not** a free-running mode: each acquisition is
            triggered by the request.
        ext_edge: The Trigger Event is the rising edge of the External Trigger
            input on the 16-pin IO connector; integration time is still set by
            software. Minimum trigger pulse width is 10 ns.
        ext_level: The Trigger Event is the rising edge of the External Trigger
            input, and **the integration time is the pulse width** -- whatever
            software configured is ignored. The pulse must be at least the
            device's minimum integration time (3800 us on an SR4); a shorter
            pulse returns a spectrum of **all zeros** rather than raising.
    """

    software = 0
    ext_edge = 1
    ext_level = 2


#: Trigger modes that High Speed Averaging Mode cannot be combined with.
#:
#: HSAM is what ``set_scans_to_average(n > 1)`` selects: the device performs n
#: integrations back-to-back and returns one hardware-averaged spectrum. The
#: manual's Acquisition Mode Summary Table (p.20) lists HSAM as supporting only
#: Software and External Edge triggers -- with External Level the two features
#: are mutually exclusive, because the level trigger owns the integration time
#: that HSAM needs to repeat.
HSAM_UNSUPPORTED_TRIGGER_MODES = (SRTrigMode.ext_level,)


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

#: Column order for the paths that cannot produce a device timestamp.
#:
#: ``dev_ts_ns`` only exists on the buffered/metadata path
#: (``get_spectrum_with_metadata``); plain ``get_spectrum()`` carries no
#: metadata at all. Declaring the full five keys on a single-shot action wrote
#: an entire all-null column -- and because the encoding is array-packed, that
#: is one ``null`` per pixel per spectrum: ~17.8 KB per spectrum on a
#: 3648-pixel OCEANSR4, about 14% of the line, for zero information.
SINGLE_SHOT_KEYS = ["epoch_s", "spec_idx", "wl", "i"]

#: Hard cap on ``Advanced.get_spectrum_with_metadata()``'s ``buffer_size``.
#: The vendor documents a maximum of 15 spectra per read on FX/HDX; newer
#: OBP2 devices accept the call directly but the same ceiling applies, so the
#: buffered drain loops rather than asking for everything at once.
MAX_METADATA_BUFFER_SIZE = 15
