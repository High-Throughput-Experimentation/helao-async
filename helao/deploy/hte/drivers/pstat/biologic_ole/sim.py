"""A fake EC-Lab OLE COM server, enough to exercise the whole driver.

EC-Lab and ``comtypes`` are Windows-only, so without this the package could be
tested no further than its pure-text layer. The fake speaks the same raw
convention ``olecom_client._unpack`` expects: PascalCase methods returning
either a scalar ``Result`` or a ``(Result, *out_params)`` tuple.

It reproduces the *failure* behaviours as carefully as the happy path, because
those are what most of the client exists to translate: a refused
``LoadSettings``, a ``RunChannel`` with nothing loaded, an index past the last
point, an unrecorded variable code, an unknown device or channel. A fake that
only ever succeeds would leave the diagnostic layer untested.

Time advances for real: ``run_seconds`` after ``RunChannel`` the channel walks
``Run`` -> ``Stop_rec1`` -> ``Stop``, so a poll loop's cursor and its
drain-on-done are genuinely exercised rather than asserted about.
"""

import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

__all__ = [
    "SimConfig",
    "SimEcLab",
    "current_config",
    "make_factory",
    "reset_sim",
    "set_sim_config",
]

#: Slot count EC-Lab reports per device, per manual section 5.2.4.
CHANNEL_SLOTS = 16

#: Variable codes the fake serves, matching technique.VAR_CODES. Any other
#: code is refused, which is what a real device does for a variable the
#: running technique does not record.
_DC_CODES = {4: "t_s", 6: "Ewe_V", 8: "I_A", 24: "cycle", 70: "P_W"}
_EIS_CODES = {
    4: "t_s",
    6: "Ewe_V",
    8: "I_A",
    9: "Ece_V",
    32: "f_Hz",
    33: "AbsEwe_V",
    34: "AbsI_A",
    35: "phase",
    36: "modulus",
    96: "AbsEce_V",
    97: "AbsIce_A",
    98: "phase_ce",
    99: "modulus_ce",
}


@dataclass
class SimConfig:
    """Shape of the simulated instrument and run.

    Attributes:
        n_channels: Channels this device reports as present.
        points_per_second: DC acquisition rate.
        run_seconds: Wall-clock length of a run. ``0.0`` finishes immediately
            but still passes through the recording-tail state.
        technique_code: What status index 5 reports. Defaults to 54 (the
            second-family CA code) so the two-family check is exercised.
        kind: ``"dc"`` or ``"eis"``.
        n_eis_points: Frequency points in an EIS sweep.
        refuse_load: Make ``LoadSettings`` return 0, as it does for settings
            incompatible with the hardware.
        refuse_run: Make ``RunChannel`` return 0 even with settings loaded.
    """

    n_channels: int = 1
    points_per_second: float = 100.0
    run_seconds: float = 0.2
    technique_code: int = 54
    kind: str = "dc"
    n_eis_points: int = 12
    refuse_load: bool = False
    refuse_run: bool = False


#: Module-level default, so a launched simulated server can be reconfigured
#: without threading a config object through the driver.
_CONFIG = SimConfig()


def set_sim_config(config: SimConfig) -> None:
    """Replace the module-level default configuration."""
    global _CONFIG
    _CONFIG = config


def current_config() -> SimConfig:
    """The module-level default configuration.

    Exposed so a caller can derive from it rather than replace it -- the
    driver has to impose its own channel count without discarding whatever a
    test set for run length or technique kind.
    """
    return _CONFIG


def reset_sim() -> None:
    """Restore the stock default configuration."""
    set_sim_config(SimConfig())


@dataclass
class _Channel:
    loaded: bool = False
    started_at: Optional[float] = None
    mpr: str = ""


@dataclass
class _Device:
    ip: str
    channels: dict = field(default_factory=dict)


class SimEcLab:
    """The fake COM object. Method names are the manual's, verbatim."""

    def __init__(self, config: SimConfig):
        self.config = config
        self.devices: dict[int, _Device] = {}
        self.messages_enabled = True
        self._next_device = 0

    # -- helpers ---------------------------------------------------------

    def _channel(self, dev: int, ch: int) -> Optional[_Channel]:
        device = self.devices.get(dev)
        if device is None or not (0 <= ch < self.config.n_channels):
            return None
        return device.channels.setdefault(ch, _Channel())

    def _elapsed(self, channel: _Channel) -> float:
        if channel.started_at is None:
            return 0.0
        return time.monotonic() - channel.started_at

    def _state(self, channel: _Channel) -> int:
        """0 Stop, 1 Run, 4 Stop_rec1 -- the tail is one poll wide."""
        if channel.started_at is None:
            return 0
        elapsed = self._elapsed(channel)
        if elapsed < self.config.run_seconds:
            return 1
        if not getattr(channel, "_tail_seen", False):
            channel._tail_seen = True  # type: ignore[attr-defined]
            return 4
        return 0

    def _n_points(self, channel: _Channel) -> int:
        if channel.started_at is None:
            return 0
        if self.config.kind == "eis":
            return self.config.n_eis_points
        capped = min(self._elapsed(channel), self.config.run_seconds)
        # +1 so a zero-length run still yields a point rather than an empty
        # file, which would make every downstream test vacuous.
        return int(capped * self.config.points_per_second) + 1

    def _find_by_mpr(self, mpr: str) -> Optional[_Channel]:
        for device in self.devices.values():
            for channel in device.channels.values():
                if channel.mpr == mpr:
                    return channel
        return None

    def _dc_point(self, index: int) -> tuple[float, float, float]:
        t_s = index / self.config.points_per_second
        ewe = 0.5 * math.cos(index / 25.0)
        current = 1e-4 * math.sin(index / 25.0)
        return (t_s, ewe, current)

    def _eis_point(self, index: int) -> tuple[float, float, float, float]:
        t_s = float(index)
        decade = index / max(self.config.n_eis_points - 1, 1)
        f_hz = 10.0 ** (1.0 + 5.0 * decade)
        re_z = 50.0 + 100.0 / (1.0 + f_hz / 1000.0)
        minus_im_z = -30.0 * (f_hz / 1000.0) / (1.0 + (f_hz / 1000.0) ** 2)
        return (t_s, f_hz, re_z, minus_im_z)

    def _value_by_code(self, index: int, code: int) -> Optional[float]:
        if self.config.kind == "eis":
            if code not in _EIS_CODES:
                return None
            t_s, f_hz, re_z, minus_im_z = self._eis_point(index)
            modulus = math.hypot(re_z, minus_im_z)
            phase = math.atan2(-minus_im_z, re_z)
            return {
                4: t_s,
                6: 0.25,
                8: 1e-4,
                9: -0.05,
                32: f_hz,
                33: 0.25,
                34: 1e-4,
                35: phase,
                36: modulus,
                96: 0.05,
                97: 1e-4,
                98: phase / 2.0,
                99: modulus / 2.0,
            }[code]
        if code not in _DC_CODES:
            return None
        t_s, ewe, current = self._dc_point(index)
        return {4: t_s, 6: ewe, 8: current, 24: 0.0, 70: abs(ewe * current)}[code]

    # -- OLE COM surface -------------------------------------------------

    def EnableMessagesWindows(self, enabled: int):
        self.messages_enabled = bool(enabled)
        return (1, 1)

    def GetSoftwareVersion(self):
        return (1, "11.72")

    def ConnectDeviceByIP(self, ip: str):
        number = self._next_device
        self._next_device += 1
        self.devices[number] = _Device(ip=ip)
        return (1, number)

    def DisconnectDevice(self, dev: int):
        return 1 if self.devices.pop(dev, None) is not None else 0

    def TestConnection(self, dev: int):
        return 1 if dev in self.devices else 0

    def GetDeviceType(self, dev: int):
        return (1, "SP-300") if dev in self.devices else (0, "unknown device")

    def GetDeviceSN(self, dev: int):
        if dev not in self.devices:
            return (0, 0, (0,) * CHANNEL_SLOTS, 0)
        serials = tuple(
            39697 + i if i < self.config.n_channels else 0 for i in range(CHANNEL_SLOTS)
        )
        return (1, 12345, serials, 1)

    def GetDeviceChannelList(self, dev: int):
        if dev not in self.devices:
            return (0, (0,) * CHANNEL_SLOTS)
        flags = tuple(
            1 if i < self.config.n_channels else 0 for i in range(CHANNEL_SLOTS)
        )
        return (1, flags)

    def IsChannelReady(self, dev: int, ch: int):
        channel = self._channel(dev, ch)
        if channel is None:
            return 0
        return 1 if self._state(channel) == 0 else 0

    def LoadSettings(self, dev: int, ch: int, path: str):
        channel = self._channel(dev, ch)
        if channel is None or self.config.refuse_load:
            return 0
        channel.loaded = True
        return 1

    def RunChannel(self, dev: int, ch: int, out_base: str):
        channel = self._channel(dev, ch)
        if channel is None or not channel.loaded or self.config.refuse_run:
            return 0
        channel.started_at = time.monotonic()
        channel._tail_seen = False  # type: ignore[attr-defined]
        channel.mpr = f"{out_base}_01_{self.config.kind.upper()}.mpr"
        return 1

    def StopChannel(self, dev: int, ch: int):
        channel = self._channel(dev, ch)
        if channel is None or channel.started_at is None:
            return 0
        channel.started_at = None
        return 1

    def GetDataFileName(self, dev: int, ch: int, technique: int):
        channel = self._channel(dev, ch)
        if channel is None or not channel.mpr:
            return (0, "")
        return (1, channel.mpr)

    def MeasureStatus(self, dev: int, ch: int):
        channel = self._channel(dev, ch)
        if channel is None:
            return (0, (0.0,) * 32)
        values = [0.0] * 32
        values[0] = float(self._state(channel))
        values[5] = float(self.config.technique_code)
        values[15] = self._elapsed(channel)
        n = self._n_points(channel)
        if n:
            if self.config.kind == "eis":
                values[16] = 0.25
                values[25], values[26] = self._eis_point(n - 1)[1:3]
            else:
                _, values[16], values[19] = self._dc_point(n - 1)
        values[27] = float(max(n - 1, 0))
        values[28] = float(max(n - 1, 0))
        return (1, tuple(values))

    def MeasureNumberOfPoints(self, mpr: str):
        channel = self._find_by_mpr(mpr)
        return 0 if channel is None else self._n_points(channel)

    def MeasureDcValue(self, mpr: str, index: int):
        channel = self._find_by_mpr(mpr)
        if channel is None or not (0 <= index < self._n_points(channel)):
            return (0, (0.0, 0.0, 0.0))
        return (1, self._dc_point(index))

    def MeasureEisValue(self, mpr: str, index: int):
        channel = self._find_by_mpr(mpr)
        if channel is None or not (0 <= index < self._n_points(channel)):
            return (0, (0.0, 0.0, 0.0, 0.0))
        return (1, self._eis_point(index))

    def MeasureValueByCode(self, mpr: str, code: int, index: int):
        channel = self._find_by_mpr(mpr)
        if channel is None or not (0 <= index < self._n_points(channel)):
            return (0, 0.0, 0)
        value = self._value_by_code(index, code)
        if value is None:
            return (0, 0.0, 0)
        return (1, value, 1)


def make_factory(config: Optional[SimConfig] = None) -> Callable[[str], Any]:
    """A ``OleComClient`` factory that yields a fresh fake per client.

    Fresh per client rather than shared, so one test's connected devices
    cannot leak into the next.
    """
    resolved = config if config is not None else _CONFIG
    return lambda progid: SimEcLab(resolved)
