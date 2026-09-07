"""Typed wrapper over EC-Lab's OLE COM functions.

**This is the only module in the package that may import comtypes, and it
imports it inside a function.** ``test_biologic_ole_vendor_isolation.py``
enforces that: an import anywhere else makes the whole package unimportable on
Linux, which is where every test in this package runs.

Every OLE function returns a bare ``1``/``0`` and carries no reason for a
failure -- and section 2 of the manual states outright that the interface
performs *no validation* of the commands sent. So this wrapper's real job is
diagnostic: it turns a ``0`` into an ``OleComError`` naming the function, the
arguments, and the most likely cause, because nothing else in the stack will.

Three return shapes need distinguishing and two of them look alike:

* Most functions return ``Result`` alone, where ``1`` is success.
* Functions with out-parameters return them as extra tuple elements. The exact
  convention ``comtypes`` produces per method is an at-station probe; the
  wrapper normalizes through ``_unpack`` and the fake server in ``sim.py``
  speaks the same convention, so a station correction lands in one place.
* ``MeasureNumberOfPoints`` is the exception where ``Result`` **is** the
  value (section 5.2.12), so ``0`` is a legitimate answer -- an empty file --
  and must not raise. ``StopChannel``, ``IsChannelReady`` and
  ``TestConnection`` likewise answer a question rather than report a fault.
"""

from typing import Any, Callable, Optional

__all__ = [
    "DEFAULT_PROGID",
    "HINTS",
    "OleComClient",
    "OleComError",
    "create_com_object",
]

#: EC-Lab's registered OLE COM ProgID. Not stated in the manual -- this is the
#: conventional spelling and is an at-station probe (gate 2 of the spec).
#: Overridable by the `progid` driver config key so a station correction needs
#: no code change.
DEFAULT_PROGID = "EC-Lab.Application"

#: What a `0` most likely means, per function. Written from the manual's own
#: notes where it has them (LoadSettings) and from the failure modes the
#: function can actually have where it does not.
HINTS: dict[str, str] = {
    "ConnectDeviceByIP": (
        "device unreachable at that IP, already held by another OLE client, "
        "or EC-Lab could not add it to its device list"
    ),
    "DisconnectDevice": "device number not in EC-Lab's device list, or already disconnected",
    "TestConnection": "EC-Lab is not connected to that device",
    "GetDeviceChannelList": "device number not in EC-Lab's device list",
    "GetDeviceType": "device number not in EC-Lab's device list",
    "GetDeviceSN": "device number not in EC-Lab's device list",
    "GetSoftwareVersion": "EC-Lab did not report its version",
    "EnableMessagesWindows": "EC-Lab refused the Windows-message setting",
    "LoadSettings": (
        "settings are incompatible with this hardware (bandwidth, IRange, "
        "E range) or the .mps file is unreadable -- open it in EC-Lab"
    ),
    "RunChannel": (
        "channel is not ready, no settings are loaded on it, or the output "
        "path is not writable by EC-Lab"
    ),
    "StopChannel": "channel was already stopped",
    "GetDataFileName": "no data file for that technique index on that channel",
    "MeasureStatus": "channel number is out of range for that device",
    "MeasureNumberOfPoints": "MPR file missing or unreadable",
    "MeasureDcValue": "MPR file missing, or the index is past the last point",
    "MeasureEisValue": "MPR file missing, or the index is past the last point",
    "MeasureValueByCode": (
        "MPR file missing, the index is past the last point, or that variable "
        "code is not recorded by this technique"
    ),
    "IsChannelReady": "channel is busy or does not exist",
}


class OleComError(RuntimeError):
    """An OLE function returned failure, annotated with a likely cause."""

    def __init__(self, function: str, args: tuple, hint: str):
        self.function = function
        self.args_sent = args
        self.hint = hint
        super().__init__(f"{function}{args} returned failure: {hint}")


def create_com_object(progid: str) -> Any:
    """Create the EC-Lab OLE COM object.

    The ``comtypes`` import is deliberately inside this function: the package
    must import on Linux, where the vendor stack does not exist.

    Raises:
        RuntimeError: If EC-Lab is not registered as an OLE COM server, with
            the exact command that fixes it. Left as a bare RuntimeError
            rather than an OleComError because no OLE call was made.
    """
    import comtypes.client  # noqa: PLC0415 - vendor isolation, see module docstring

    try:
        return comtypes.client.CreateObject(progid)
    except OSError as exc:
        raise RuntimeError(
            f"could not create the EC-Lab OLE COM object {progid!r}. EC-Lab is "
            "not registered as an OLE COM server by default: open an "
            "administrator command prompt in the EC-Lab install directory "
            "(e.g. C:\\Program Files (x86)\\EC-Lab) and run `ECLab /regserver`. "
            "It prints nothing on success."
        ) from exc


def _unpack(raw: Any) -> tuple[int, tuple]:
    """Split a COM return into ``(result, out_params)``.

    A scalar return is ``Result`` with no out-parameters; a tuple is
    ``Result`` followed by them.
    """
    if isinstance(raw, tuple):
        return int(raw[0]), tuple(raw[1:])
    return int(raw), ()


class OleComClient:
    """Every OLE COM call the driver makes, with failures named.

    The COM object is created on first use rather than at construction, so a
    client can be built on Linux -- and so a station's EC-Lab does not need to
    be running at the moment the driver object is made.
    """

    def __init__(
        self,
        progid: str = DEFAULT_PROGID,
        factory: Callable[[str], Any] = create_com_object,
    ):
        self.progid = progid
        self._factory = factory
        self._com: Optional[Any] = None

    @property
    def com(self) -> Any:
        """The COM object, created on first access."""
        if self._com is None:
            self._com = self._factory(self.progid)
        return self._com

    def _call(self, function: str, *args) -> tuple:
        """Invoke ``function``, raising ``OleComError`` on a ``0`` result."""
        result, outs = _unpack(getattr(self.com, function)(*args))
        if result != 1:
            raise OleComError(function, args, HINTS.get(function, "no detail"))
        return outs

    def _ask(self, function: str, *args) -> bool:
        """Invoke a function whose ``0`` is an answer, not a fault."""
        result, _ = _unpack(getattr(self.com, function)(*args))
        return result == 1

    # -- session ---------------------------------------------------------

    def enable_messages_windows(self, enabled: bool) -> None:
        """Enable or suppress EC-Lab's Windows message boxes.

        Suppressing them is mandatory for unattended operation: a modal dialog
        blocks the COM call that raised it, forever.
        """
        self._call("EnableMessagesWindows", int(bool(enabled)))

    def get_software_version(self) -> str:
        return str(self._call("GetSoftwareVersion")[0])

    # -- device ----------------------------------------------------------

    def connect_device_by_ip(self, ip: str) -> int:
        """Connect to the device at ``ip``, returning its device number.

        Adds the device to EC-Lab's list if absent. **This call auto-answers
        "Yes" to EC-Lab's firmware-upgrade prompt** (manual section 5.2.1) --
        the API offers no way to suppress it, so a connect can flash a
        production instrument. The driver warns before calling this.
        """
        return int(self._call("ConnectDeviceByIP", ip)[0])

    def disconnect_device(self, dev: int) -> None:
        self._call("DisconnectDevice", dev)

    def test_connection(self, dev: int) -> bool:
        return self._ask("TestConnection", dev)

    def get_device_type(self, dev: int) -> str:
        return str(self._call("GetDeviceType", dev)[0])

    def get_device_sn(self, dev: int) -> tuple[int, list[int]]:
        """``(device serial, per-channel serials)``; 0 means not plugged."""
        outs = self._call("GetDeviceSN", dev)
        return int(outs[0]), [int(sn) for sn in outs[1]]

    def get_device_channel_list(self, dev: int) -> list[bool]:
        """One flag per channel slot, True where a channel is present."""
        return [bool(flag) for flag in self._call("GetDeviceChannelList", dev)[0]]

    # -- channel ---------------------------------------------------------

    def is_channel_ready(self, dev: int, ch: int) -> bool:
        return self._ask("IsChannelReady", dev, ch)

    def load_settings(self, dev: int, ch: int, path: str) -> None:
        """Load an .mps or .mpr onto a channel.

        A ``0`` here is the only real pre-run validation the API offers: the
        manual states this returns False when the settings are incompatible
        with the hardware (bandwidth, IRange).
        """
        self._call("LoadSettings", dev, ch, path)

    def run_channel(self, dev: int, ch: int, out_base: str) -> None:
        self._call("RunChannel", dev, ch, out_base)

    def stop_channel(self, dev: int, ch: int) -> bool:
        """Stop the channel. ``False`` means it was already stopped."""
        return self._ask("StopChannel", dev, ch)

    def get_data_file_name(self, dev: int, ch: int, technique: int) -> str:
        """Absolute path of the MPR file for one technique on a channel."""
        return str(self._call("GetDataFileName", dev, ch, technique)[0])

    def measure_status(self, dev: int, ch: int) -> tuple[float, ...]:
        """The 32 status reals. Decode with ``status.decode_status``."""
        return tuple(float(v) for v in self._call("MeasureStatus", dev, ch)[0])

    # -- data ------------------------------------------------------------

    def measure_number_of_points(self, mpr: str) -> int:
        """Point count in an MPR file.

        Section 5.2.12: the ``Result`` *is* the count, so this does not go
        through ``_call``. Zero is an empty file, not a failure -- which is
        the normal state in the moments after ``RunChannel``.
        """
        result, _ = _unpack(getattr(self.com, "MeasureNumberOfPoints")(mpr))
        return int(result)

    def measure_dc_value(self, mpr: str, index: int) -> tuple[float, ...]:
        """``<t_s, Ewe_V, I_A>`` from a DC file. Current is 0 for OCV."""
        return tuple(float(v) for v in self._call("MeasureDcValue", mpr, index)[0])

    def measure_eis_value(self, mpr: str, index: int) -> tuple[float, ...]:
        """``<t_s, f_Hz, Re(Z), -Im(Z)>``. Frequency is 0 at a non-EIS index."""
        return tuple(float(v) for v in self._call("MeasureEisValue", mpr, index)[0])

    def measure_value_by_code(self, mpr: str, code: int, index: int) -> float:
        """One variable at one point. ``code`` is from appendix 7.2."""
        outs = self._call("MeasureValueByCode", mpr, code, index)
        return float(outs[0])
