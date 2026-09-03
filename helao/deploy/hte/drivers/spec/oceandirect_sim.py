"""Simulated OceanDirect SDK, sufficient to exercise the driver and server.

The vendor ``oceandirect`` package is a wheel shipped inside the Ocean Insight
SDK installer and is not present in the ``helao`` conda environment, so nothing
in the OceanDirect stack could otherwise be imported -- let alone tested -- off
a station. This module stands in for it: it exposes the same three names the
driver imports (``OceanDirectAPI``, ``OceanDirectError``, ``FeatureID``) with
the same call signatures and the same *failure* behaviour, which is the part
that actually matters. In particular:

* every method raises ``OceanDirectError`` rather than returning a status code,
* ``close_device()`` invalidates the device id, so a reconnect must re-run
  discovery,
* an unsupported feature raises instead of returning a sentinel,
* ``get_spectrum_with_metadata()`` honours the 15-spectra ceiling and returns
  the number of spectra it actually appended, which can be fewer than asked
  for and can be zero.

The synthetic spectrum is a fixed pair of Gaussian peaks over a linear
wavelength axis, scaled by integration time and clipped at the device's
maximum intensity, so an intensity-calibration loop has something monotonic to
converge on and saturation is reachable.
"""

__all__ = [
    "FeatureID",
    "OceanDirectAPI",
    "OceanDirectError",
    "SimConfig",
    "reset_sim",
    "set_sim_config",
]

import math
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


class OceanDirectError(Exception):
    """Mirror of the vendor error: an error code plus a message."""

    def __init__(self, errorCode: int, errorMsg: str):
        super().__init__(errorMsg)
        self._error_code = errorCode
        self._error_msg = errorMsg

    def get_error_details(self) -> tuple[int, str]:
        """Return the ``(code, message)`` pair carried by this error."""
        return (self._error_code, self._error_msg)


class FeatureID(Enum):
    """Feature identifiers, in the vendor's declaration order.

    The vendor warns that the order encodes the C enum's values, so the
    members below are spelled in the same order as the real SDK even though
    the simulation only ever compares them by identity.
    """

    SERIAL_NUMBER = 1
    SPECTROMETER = auto()
    THERMOELECTRIC = auto()
    IRRADIANCE_CAL = auto()
    EEPROM = auto()
    STROBE_LAMP = auto()
    WAVELENGTH_CAL = auto()
    NONLINEARITY_CAL = auto()
    STRAYLIGHT_CAL = auto()
    RAW_BUS_ACCESS = auto()
    CONTINUOUS_STROBE = auto()
    LIGHT_SOURCE = auto()
    TEMPERATURE = auto()
    OPTICAL_BENCH = auto()
    REVISION = auto()
    PROCESSING = auto()
    DATA_BUFFER = auto()
    ACQUISITION_DELAY = auto()
    PIXEL_BINNING = auto()
    GPIO = auto()
    SINGLE_STROBE = auto()
    QUERY_STATUS = auto()
    BACK_TO_BACK = auto()
    LED_ACTIVITY = auto()
    TIME_META = auto()
    DHCP = auto()
    IPV4_ADDRESS = auto()
    PIXEL = auto()
    AUTO_NULLING = auto()
    USER_STRING = auto()
    DEVICE_INFORMATION = auto()
    DEVICE_ALIAS = auto()
    SERIAL_PORT = auto()
    SPECTRUM_ACQUISITION_CONTROL = auto()
    NETWORK_CONFIGURATION = auto()
    ETHERNET = auto()
    SHUTTER = auto()
    HIGH_GAIN_MODE = auto()


#: Features an SR-series device reports as available. Deliberately excludes
#: ``SHUTTER`` and ``GPIO`` so the gating path is exercised by default rather
#: than only in a test that opts into it.
SR_SERIES_FEATURES = frozenset(
    {
        FeatureID.SERIAL_NUMBER,
        FeatureID.SPECTROMETER,
        FeatureID.THERMOELECTRIC,
        FeatureID.TEMPERATURE,
        FeatureID.NONLINEARITY_CAL,
        FeatureID.WAVELENGTH_CAL,
        FeatureID.REVISION,
        FeatureID.PROCESSING,
        FeatureID.DATA_BUFFER,
        FeatureID.BACK_TO_BACK,
        FeatureID.ACQUISITION_DELAY,
        FeatureID.SINGLE_STROBE,
        FeatureID.CONTINUOUS_STROBE,
        FeatureID.LIGHT_SOURCE,
        FeatureID.STROBE_LAMP,
        FeatureID.TIME_META,
        FeatureID.DEVICE_INFORMATION,
        FeatureID.HIGH_GAIN_MODE,
        FeatureID.SPECTRUM_ACQUISITION_CONTROL,
    }
)


@dataclass
class SimConfig:
    """Knobs describing the simulated device population.

    Attributes:
        serial_numbers: One entry per discoverable device, in discovery order.
        model: Model string every simulated device reports.
        n_pixels: Detector pixel count.
        wl_start: First wavelength, nm.
        wl_step: Wavelength increment per pixel, nm.
        int_time_min_us: Minimum integration time, microseconds.
        int_time_max_us: Maximum integration time, microseconds.
        int_time_increment_us: Integration-time granularity, microseconds.
        max_intensity: Saturation ceiling in counts.
        features: Feature identifiers the device reports as enabled.
        find_returns_nothing: When true, discovery reports no devices.
        open_raises: When true, ``open_device`` raises.
    """

    serial_numbers: tuple[str, ...] = ("SIM-SR2-0001",)
    # Prefixed "SIM-" deliberately. A bare "SR2" here is indistinguishable
    # from a real reading, and `/get_device_info` against a station still
    # configured `simulate: true` then looks like a device reporting the
    # wrong model rather than like the simulator answering.
    model: str = "SIM-SR2"
    n_pixels: int = 2048
    wl_start: float = 339.0
    wl_step: float = 0.22
    int_time_min_us: int = 1000
    int_time_max_us: int = 10_000_000
    int_time_increment_us: int = 1000
    max_intensity: int = 65535
    features: frozenset = SR_SERIES_FEATURES
    find_returns_nothing: bool = False
    open_raises: bool = False
    _next_device_id: int = field(default=1, repr=False)


_SIM_CONFIG = SimConfig()


def set_sim_config(cfg: SimConfig) -> None:
    """Install ``cfg`` as the population every later ``OceanDirectAPI`` sees."""
    global _SIM_CONFIG
    _SIM_CONFIG = cfg


def reset_sim() -> None:
    """Restore the default single-SR2 population."""
    set_sim_config(SimConfig())


class _Advanced:
    """Stand-in for ``Spectrometer.Advanced``.

    Only the members the driver calls are implemented; anything else is
    absent, so a driver method that reaches for an unimplemented vendor
    feature fails loudly in tests instead of silently passing.
    """

    def __init__(self, device: "Spectrometer"):
        self.device = device

    def _require(self, feature: FeatureID, caller: str) -> None:
        if feature not in self.device._features:
            raise OceanDirectError(
                -3, f"{caller}: feature {feature.name} not supported by this device"
            )

    # --- thermoelectric cooler ---
    def set_tec_enable(self, coolerEnable: bool) -> None:
        self._require(FeatureID.THERMOELECTRIC, "set_tec_enable")
        self.device._tec_enabled = bool(coolerEnable)

    def get_tec_enable(self) -> bool:
        self._require(FeatureID.THERMOELECTRIC, "get_tec_enable")
        return self.device._tec_enabled

    def set_temperature_setpoint_degrees_C(self, temp_C: float) -> None:
        self._require(FeatureID.THERMOELECTRIC, "set_temperature_setpoint_degrees_C")
        self.device._tec_setpoint = float(temp_C)

    def get_temperature_setpoint_degrees_C(self) -> float:
        self._require(FeatureID.THERMOELECTRIC, "get_temperature_setpoint_degrees_C")
        return self.device._tec_setpoint

    def get_tec_temperature_degrees_C(self) -> float:
        self._require(FeatureID.TEMPERATURE, "get_tec_temperature_degrees_C")
        # Simulated cooler sits half a degree off setpoint while enabled.
        if self.device._tec_enabled:
            return self.device._tec_setpoint + 0.5
        return 25.0

    def get_tec_stable(self) -> bool:
        self._require(FeatureID.THERMOELECTRIC, "get_tec_stable")
        return self.device._tec_enabled

    # --- shutter / lamp / light source ---
    def set_shutter_open(self, shutterState: bool) -> None:
        self._require(FeatureID.SHUTTER, "set_shutter_open")
        self.device._shutter_open = bool(shutterState)

    def get_shutter_state(self) -> bool:
        self._require(FeatureID.SHUTTER, "get_shutter_state")
        return self.device._shutter_open

    def set_enable_lamp(self, enable: bool) -> None:
        self._require(FeatureID.STROBE_LAMP, "set_enable_lamp")
        self.device._lamp_enabled = bool(enable)

    def get_enable_lamp(self) -> bool:
        self._require(FeatureID.STROBE_LAMP, "get_enable_lamp")
        return self.device._lamp_enabled

    def get_light_source_count(self) -> int:
        self._require(FeatureID.LIGHT_SOURCE, "get_light_source_count")
        return len(self.device._light_sources)

    def has_light_source_enable(self, light_source_index: int) -> bool:
        self._require(FeatureID.LIGHT_SOURCE, "has_light_source_enable")
        return 0 <= light_source_index < len(self.device._light_sources)

    def is_light_source_enabled(self, light_source_index: int) -> bool:
        self._require(FeatureID.LIGHT_SOURCE, "is_light_source_enabled")
        return self.device._light_sources[light_source_index]

    def enable_light_source(self, light_source_index: int, enable: bool) -> None:
        self._require(FeatureID.LIGHT_SOURCE, "enable_light_source")
        if not 0 <= light_source_index < len(self.device._light_sources):
            raise OceanDirectError(
                -4, f"enable_light_source: bad index {light_source_index}"
            )
        self.device._light_sources[light_source_index] = bool(enable)

    # --- strobes ---
    def set_single_strobe_enable(self, enable: bool) -> None:
        self._require(FeatureID.SINGLE_STROBE, "set_single_strobe_enable")
        self.device._single_strobe["enable"] = bool(enable)

    def set_single_strobe_delay(self, delayMicrosecond: int) -> None:
        self._require(FeatureID.SINGLE_STROBE, "set_single_strobe_delay")
        self.device._single_strobe["delay_us"] = int(delayMicrosecond)

    def set_single_strobe_width(self, widthMicrosecond: int) -> None:
        self._require(FeatureID.SINGLE_STROBE, "set_single_strobe_width")
        self.device._single_strobe["width_us"] = int(widthMicrosecond)

    def get_single_strobe_enable(self) -> bool:
        self._require(FeatureID.SINGLE_STROBE, "get_single_strobe_enable")
        return self.device._single_strobe["enable"]

    def get_single_strobe_delay(self) -> int:
        self._require(FeatureID.SINGLE_STROBE, "get_single_strobe_delay")
        return self.device._single_strobe["delay_us"]

    def get_single_strobe_width(self) -> int:
        self._require(FeatureID.SINGLE_STROBE, "get_single_strobe_width")
        return self.device._single_strobe["width_us"]

    def get_single_strobe_delay_minimum(self) -> int:
        self._require(FeatureID.SINGLE_STROBE, "get_single_strobe_delay_minimum")
        return 0

    def get_single_strobe_delay_maximum(self) -> int:
        self._require(FeatureID.SINGLE_STROBE, "get_single_strobe_delay_maximum")
        return 1_000_000

    def get_single_strobe_delay_increment(self) -> int:
        self._require(FeatureID.SINGLE_STROBE, "get_single_strobe_delay_increment")
        return 1

    def get_single_strobe_width_minimum(self) -> int:
        self._require(FeatureID.SINGLE_STROBE, "get_single_strobe_width_minimum")
        return 1

    def get_single_strobe_width_maximum(self) -> int:
        self._require(FeatureID.SINGLE_STROBE, "get_single_strobe_width_maximum")
        return 500_000

    def get_single_strobe_width_increment(self) -> int:
        self._require(FeatureID.SINGLE_STROBE, "get_single_strobe_width_increment")
        return 1

    def set_continuous_strobe_enable(self, enable: bool) -> None:
        self._require(FeatureID.CONTINUOUS_STROBE, "set_continuous_strobe_enable")
        self.device._cont_strobe["enable"] = bool(enable)

    def set_continuous_strobe_period(self, period: int) -> None:
        self._require(FeatureID.CONTINUOUS_STROBE, "set_continuous_strobe_period")
        self.device._cont_strobe["period_us"] = int(period)

    def set_continuous_strobe_width(self, widthMicrosecond: int) -> None:
        self._require(FeatureID.CONTINUOUS_STROBE, "set_continuous_strobe_width")
        self.device._cont_strobe["width_us"] = int(widthMicrosecond)

    def get_continuous_strobe_enable(self) -> bool:
        self._require(FeatureID.CONTINUOUS_STROBE, "get_continuous_strobe_enable")
        return self.device._cont_strobe["enable"]

    def get_continuous_strobe_period(self) -> int:
        self._require(FeatureID.CONTINUOUS_STROBE, "get_continuous_strobe_period")
        return self.device._cont_strobe["period_us"]

    def get_continuous_strobe_width(self) -> int:
        self._require(FeatureID.CONTINUOUS_STROBE, "get_continuous_strobe_width")
        return self.device._cont_strobe["width_us"]

    def get_continuous_strobe_period_minimum(self) -> int:
        self._require(
            FeatureID.CONTINUOUS_STROBE, "get_continuous_strobe_period_minimum"
        )
        return 1

    def get_continuous_strobe_period_maximum(self) -> int:
        self._require(
            FeatureID.CONTINUOUS_STROBE, "get_continuous_strobe_period_maximum"
        )
        return 60_000_000

    def get_continuous_strobe_period_increment(self) -> int:
        self._require(
            FeatureID.CONTINUOUS_STROBE, "get_continuous_strobe_period_increment"
        )
        return 1

    # --- data buffer / back-to-back ---
    def set_data_buffer_enable(self, enable: bool) -> None:
        self._require(FeatureID.DATA_BUFFER, "set_data_buffer_enable")
        self.device._buffer_enabled = bool(enable)
        if not enable:
            self.device._buffered.clear()

    def get_data_buffer_enable(self) -> bool:
        self._require(FeatureID.DATA_BUFFER, "get_data_buffer_enable")
        return self.device._buffer_enabled

    def set_data_buffer_capacity(self, capacity: int) -> None:
        self._require(FeatureID.DATA_BUFFER, "set_data_buffer_capacity")
        self.device._buffer_capacity = int(capacity)

    def get_data_buffer_capacity(self) -> int:
        self._require(FeatureID.DATA_BUFFER, "get_data_buffer_capacity")
        return self.device._buffer_capacity

    def get_data_buffer_capacity_minimum(self) -> int:
        self._require(FeatureID.DATA_BUFFER, "get_data_buffer_capacity_minimum")
        return 1

    def get_data_buffer_capacity_maximum(self) -> int:
        self._require(FeatureID.DATA_BUFFER, "get_data_buffer_capacity_maximum")
        return 50_000

    def get_hardware_buffer_capacity(self) -> int:
        self._require(FeatureID.DATA_BUFFER, "get_hardware_buffer_capacity")
        return 50_000

    def clear_data_buffer(self) -> None:
        self._require(FeatureID.DATA_BUFFER, "clear_data_buffer")
        self.device._buffered.clear()

    def get_data_buffer_number_of_elements(self) -> int:
        self._require(FeatureID.DATA_BUFFER, "get_data_buffer_number_of_elements")
        return len(self.device._buffered)

    def get_buffered_spectrum_count(self) -> int:
        self._require(FeatureID.DATA_BUFFER, "get_buffered_spectrum_count")
        return len(self.device._buffered)

    def set_number_of_backtoback_scans(self, numScans: int) -> None:
        self._require(FeatureID.BACK_TO_BACK, "set_number_of_backtoback_scans")
        self.device._b2b_scans = int(numScans)

    def get_number_of_backtoback_scans(self) -> int:
        self._require(FeatureID.BACK_TO_BACK, "get_number_of_backtoback_scans")
        return self.device._b2b_scans

    def acquire_spectra_to_buffer(self) -> None:
        self._require(
            FeatureID.SPECTRUM_ACQUISITION_CONTROL, "acquire_spectra_to_buffer"
        )
        self.device._idle = False
        # Fill the buffer with the requested back-to-back run so a drain has
        # something to read, capped by the configured capacity.
        n = min(self.device._b2b_scans, self.device._buffer_capacity)
        for _ in range(n):
            self.device._buffered.append(self.device._synth_spectrum())

    def abort_acquisition(self) -> None:
        self._require(FeatureID.SPECTRUM_ACQUISITION_CONTROL, "abort_acquisition")
        self.device._idle = True

    def abort_spectrum_acquisition(self) -> None:
        self._require(
            FeatureID.SPECTRUM_ACQUISITION_CONTROL, "abort_spectrum_acquisition"
        )
        self.device._idle = True

    def get_device_idle_state(self) -> bool:
        self._require(FeatureID.SPECTRUM_ACQUISITION_CONTROL, "get_device_idle_state")
        return self.device._idle

    def get_spectrum_with_metadata(
        self,
        list_spectra: list,
        list_timestamp: list,
        buffer_size: int,
    ) -> int:
        """Append at most ``buffer_size`` buffered spectra, returning the count.

        Mirrors the vendor contract: the caller supplies the output lists, the
        return value is how many spectra were actually appended, and that can
        be fewer than requested or zero.
        """
        self._require(FeatureID.DATA_BUFFER, "get_spectrum_with_metadata")
        if buffer_size > 15:
            raise OceanDirectError(
                -5, "get_spectrum_with_metadata: buffer_size maximum is 15"
            )
        count = 0
        while self.device._buffered and count < buffer_size:
            list_spectra.append(self.device._buffered.pop(0))
            self.device._timestamp_ns += 1_000_000
            list_timestamp.append(self.device._timestamp_ns)
            count += 1
        return count

    def get_buffered_spectrum_with_metadata(self) -> tuple[list, int]:
        self._require(FeatureID.DATA_BUFFER, "get_buffered_spectrum_with_metadata")
        if not self.device._buffered:
            return ([], 0)
        self.device._timestamp_ns += 1_000_000
        return (self.device._buffered.pop(0), self.device._timestamp_ns)

    # --- revisions ---
    def get_revision_firmware(self) -> str:
        self._require(FeatureID.REVISION, "get_revision_firmware")
        return "SIM-FW-1.2.3"

    def get_revision_fpga(self) -> str:
        self._require(FeatureID.REVISION, "get_revision_fpga")
        return "SIM-FPGA-4.5"


class Spectrometer:
    """Stand-in for the vendor per-device object."""

    def __init__(self, dev_id: int, serial_number: str, cfg: SimConfig):
        self.device_id = dev_id
        self._cfg = cfg
        self._serial = serial_number
        self._features = cfg.features
        self._open = False
        self.status = "closed"

        self._int_time_us = cfg.int_time_min_us
        self._scans_to_average = 1
        self._boxcar_width = 0
        self._trigger_mode = 0
        self._electric_dark = False
        self._nonlinearity = False
        self._saturation_check = False
        self._stored_dark: Optional[list] = None
        self._timestamp_ns = 0

        self._tec_enabled = False
        self._tec_setpoint = 10.0
        self._shutter_open = False
        self._lamp_enabled = False
        self._light_sources = [False]
        self._single_strobe = {"enable": False, "delay_us": 0, "width_us": 1}
        self._cont_strobe = {"enable": False, "period_us": 1000, "width_us": 100}

        self._buffer_enabled = False
        self._buffer_capacity = 50_000
        self._b2b_scans = 1
        self._buffered: list[list[float]] = []
        self._idle = True

        self.Advanced = _Advanced(device=self)

    # --- lifecycle ---
    def open_device(self) -> None:
        if self._cfg.open_raises:
            raise OceanDirectError(-1, "open_device: simulated open failure")
        self._open = True
        self.status = "open"

    def open_device2(self, retryCount: int, timeoutMs: int) -> None:
        self.open_device()

    def close_device(self) -> None:
        self._open = False
        self.status = "closed"

    def _check_open(self, caller: str) -> None:
        if not self._open:
            raise OceanDirectError(-2, f"{caller}: device is not open")

    # --- identity ---
    def get_serial_number(self) -> str:
        self._check_open("get_serial_number")
        return self._serial

    def get_model(self) -> str:
        self._check_open("get_model")
        return self._cfg.model

    def get_device_type(self) -> int:
        self._check_open("get_device_type")
        return 42

    def is_feature_id_enabled(self, featureID: FeatureID) -> bool:
        self._check_open("is_feature_id_enabled")
        return featureID in self._features

    # --- geometry ---
    def get_spectrum_length(self) -> int:
        self._check_open("get_spectrum_length")
        return self._cfg.n_pixels

    def get_formatted_spectrum_length(self) -> int:
        return self.get_spectrum_length()

    def get_wavelengths(self) -> list[float]:
        self._check_open("get_wavelengths")
        return [
            self._cfg.wl_start + i * self._cfg.wl_step
            for i in range(self._cfg.n_pixels)
        ]

    def get_max_intensity(self) -> int:
        self._check_open("get_max_intensity")
        return self._cfg.max_intensity

    def get_number_electric_dark_pixels(self) -> int:
        self._check_open("get_number_electric_dark_pixels")
        return 4

    def get_electric_dark_pixel_indices(self) -> list[int]:
        self._check_open("get_electric_dark_pixel_indices")
        return [0, 1, 2, 3]

    # --- integration time ---
    def get_minimum_integration_time(self) -> int:
        self._check_open("get_minimum_integration_time")
        return self._cfg.int_time_min_us

    def get_maximum_integration_time(self) -> int:
        self._check_open("get_maximum_integration_time")
        return self._cfg.int_time_max_us

    def get_integration_time_increment(self) -> int:
        self._check_open("get_integration_time_increment")
        return self._cfg.int_time_increment_us

    def get_minimum_averaging_integration_time(self) -> int:
        self._check_open("get_minimum_averaging_integration_time")
        return self._cfg.int_time_min_us

    def set_integration_time(self, int_time: int) -> None:
        self._check_open("set_integration_time")
        if not (self._cfg.int_time_min_us <= int_time <= self._cfg.int_time_max_us):
            raise OceanDirectError(
                -6, f"set_integration_time: {int_time} us out of device range"
            )
        self._int_time_us = int(int_time)

    def get_integration_time(self) -> int:
        self._check_open("get_integration_time")
        return self._int_time_us

    # --- processing ---
    def set_scans_to_average(self, newScanToAverage: int) -> None:
        self._check_open("set_scans_to_average")
        if newScanToAverage < 1:
            raise OceanDirectError(-7, "set_scans_to_average: must be >= 1")
        self._scans_to_average = int(newScanToAverage)

    def get_scans_to_average(self) -> int:
        self._check_open("get_scans_to_average")
        return self._scans_to_average

    def set_boxcar_width(self, newBoxcarWidth: int) -> None:
        self._check_open("set_boxcar_width")
        if newBoxcarWidth < 0:
            raise OceanDirectError(-8, "set_boxcar_width: must be >= 0")
        self._boxcar_width = int(newBoxcarWidth)

    def get_boxcar_width(self) -> int:
        self._check_open("get_boxcar_width")
        return self._boxcar_width

    def set_electric_dark_correction_usage(self, isEnabled: bool) -> None:
        self._require_feature(
            FeatureID.PROCESSING, "set_electric_dark_correction_usage"
        )
        self._electric_dark = bool(isEnabled)

    def get_electric_dark_correction_usage(self) -> bool:
        self._require_feature(
            FeatureID.PROCESSING, "get_electric_dark_correction_usage"
        )
        return self._electric_dark

    def set_nonlinearity_correction_usage(self, isEnabled: bool) -> None:
        self._require_feature(
            FeatureID.NONLINEARITY_CAL, "set_nonlinearity_correction_usage"
        )
        self._nonlinearity = bool(isEnabled)

    def get_nonlinearity_correction_usage(self) -> bool:
        self._require_feature(
            FeatureID.NONLINEARITY_CAL, "get_nonlinearity_correction_usage"
        )
        return self._nonlinearity

    def set_saturation_check(self, checkCorrectedCount: bool) -> None:
        self._check_open("set_saturation_check")
        self._saturation_check = bool(checkCorrectedCount)

    def get_saturation_check(self) -> bool:
        self._check_open("get_saturation_check")
        return self._saturation_check

    def get_saturated_spectrum(self) -> bool:
        self._check_open("get_saturated_spectrum")
        return max(self._synth_spectrum()) >= self._cfg.max_intensity

    def _require_feature(self, feature: FeatureID, caller: str) -> None:
        self._check_open(caller)
        if feature not in self._features:
            raise OceanDirectError(
                -3, f"{caller}: feature {feature.name} not supported by this device"
            )

    # --- dark spectra ---
    def set_stored_dark_spectrum(self, darkSpectrum: list) -> None:
        self._check_open("set_stored_dark_spectrum")
        if len(darkSpectrum) != self._cfg.n_pixels:
            raise OceanDirectError(
                -9,
                f"set_stored_dark_spectrum: expected {self._cfg.n_pixels} values, "
                f"got {len(darkSpectrum)}",
            )
        self._stored_dark = list(darkSpectrum)

    def get_stored_dark_spectrum(self) -> list:
        self._check_open("get_stored_dark_spectrum")
        if self._stored_dark is None:
            raise OceanDirectError(-10, "get_stored_dark_spectrum: no dark stored")
        return list(self._stored_dark)

    def get_dark_corrected_spectrum2(self) -> list:
        self._check_open("get_dark_corrected_spectrum2")
        if self._stored_dark is None:
            raise OceanDirectError(-10, "get_dark_corrected_spectrum2: no dark stored")
        spec = self._synth_spectrum()
        return [a - b for a, b in zip(spec, self._stored_dark)]

    def get_nonlinearity_corrected_spectrum2(self) -> list:
        self._require_feature(
            FeatureID.NONLINEARITY_CAL, "get_nonlinearity_corrected_spectrum2"
        )
        return self._synth_spectrum()

    # --- trigger ---
    def set_trigger_mode(self, mode: int) -> None:
        self._check_open("set_trigger_mode")
        if mode not in (0, 1, 2, 3, 4):
            raise OceanDirectError(-11, f"set_trigger_mode: unsupported mode {mode}")
        self._trigger_mode = int(mode)

    def get_trigger_mode(self) -> int:
        self._check_open("get_trigger_mode")
        return self._trigger_mode

    # --- wavelength lookup ---
    def get_index_at_wavelength(self, wavelength: float) -> tuple[int, float]:
        self._check_open("get_index_at_wavelength")
        wls = self.get_wavelengths()
        idx = min(range(len(wls)), key=lambda i: abs(wls[i] - wavelength))
        return (idx, wls[idx])

    def get_indices_at_wavelengths(self, wavelengths: list) -> tuple[list, list]:
        self._check_open("get_indices_at_wavelengths")
        pairs = [self.get_index_at_wavelength(w) for w in wavelengths]
        return ([p[0] for p in pairs], [p[1] for p in pairs])

    def get_indices_at_wavelength_range(
        self, lo: float, hi: float, length: int
    ) -> tuple[list, list]:
        self._check_open("get_indices_at_wavelength_range")
        wls = self.get_wavelengths()
        idxs = [i for i, w in enumerate(wls) if lo <= w <= hi][:length]
        return (idxs, [wls[i] for i in idxs])

    # --- acquisition ---
    def get_spectrum(self) -> list[float]:
        self._check_open("get_spectrum")
        return self._synth_spectrum()

    def get_formatted_spectrum(self) -> list[float]:
        return self.get_spectrum()

    def _synth_spectrum(self) -> list[float]:
        """Two Gaussian peaks scaled by integration time, clipped at saturation."""
        cfg = self._cfg
        # Scale linearly with integration time so a calibration loop converges.
        gain = self._int_time_us / max(cfg.int_time_min_us, 1)
        out = []
        for i in range(cfg.n_pixels):
            wl = cfg.wl_start + i * cfg.wl_step
            v = 40.0  # dark floor
            for center, height, width in ((450.0, 120.0, 18.0), (620.0, 70.0, 30.0)):
                v += height * math.exp(-(((wl - center) / width) ** 2))
            out.append(min(float(cfg.max_intensity), v * gain))
        return out


class OceanDirectAPI:
    """Stand-in for the vendor singleton API object."""

    def __init__(self):
        self._cfg = _SIM_CONFIG
        self._devices: dict[int, Spectrometer] = {}
        self._ids: list[int] = []
        self._shutdown = False

    def get_api_version_numbers(self) -> tuple[int, int, int]:
        return (2, 0, 0)

    def find_usb_devices(self) -> int:
        return self._find()

    def find_devices(self) -> int:
        return self._find()

    def _find(self) -> int:
        if self._cfg.find_returns_nothing:
            self._ids = []
            return 0
        # Discovery mints fresh ids, as the vendor does after a close.
        self._ids = []
        self._devices = {}
        for serial in self._cfg.serial_numbers:
            dev_id = self._cfg._next_device_id
            self._cfg._next_device_id += 1
            self._ids.append(dev_id)
            self._devices[dev_id] = Spectrometer(dev_id, serial, self._cfg)
        return len(self._ids)

    def get_number_devices(self) -> int:
        return len(self._ids)

    def get_device_ids(self) -> list[int]:
        return list(self._ids)

    def get_serial_number(self, dev_id: int) -> str:
        dev = self._devices.get(dev_id)
        if dev is None:
            raise OceanDirectError(-12, f"get_serial_number: unknown id {dev_id}")
        return dev._serial

    def open_device(self, device_id: int) -> Spectrometer:
        return self.open_device2(device_id, 1, 500)

    def open_device2(
        self, device_id: int, retryCount: int, timeoutMs: int
    ) -> Spectrometer:
        dev = self._devices.get(device_id)
        if dev is None:
            raise OceanDirectError(-12, f"open_device: unknown id {device_id}")
        dev.open_device2(retryCount, timeoutMs)
        return dev

    def get_open_device_status(self, device_id: int) -> bool:
        dev = self._devices.get(device_id)
        return bool(dev is not None and dev._open)

    def close_device(self, device_id: int) -> None:
        dev = self._devices.get(device_id)
        if dev is None:
            raise OceanDirectError(-12, f"close_device: unknown id {device_id}")
        dev.close_device()
        # The vendor invalidates the id on close; a reopen needs a fresh
        # discovery pass. Dropping it here is what makes the driver's
        # rediscover-on-reconnect path load-bearing in tests.
        self._devices.pop(device_id, None)
        if device_id in self._ids:
            self._ids.remove(device_id)

    def close_all_devices(self) -> None:
        for dev_id in list(self._devices):
            self.close_device(dev_id)

    def shutdown(self) -> None:
        self.close_all_devices()
        self._shutdown = True
