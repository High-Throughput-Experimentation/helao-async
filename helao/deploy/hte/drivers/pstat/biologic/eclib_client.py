"""The serialized gateway onto the EClib1 DLL, and the only thing that turns a
vendor error code into an exception.

Two reasons this layer exists:

**Serialization.** Every vendor call is marshalled onto one dedicated worker
thread owned by the client. ``easy_biologic``'s ``*_async`` functions are
``async def`` wrappers around the blocking sync calls -- generated in a loop
at ``lib/ec_lib.py:660`` -- so today every ``BL_GetData`` blocks the action
server's event loop at the executor's 10 ms poll rate, in a process also
serving HTTP and two WebSockets. Serializing here also settles DLL
re-entrancy without the manual having to answer it.

**Interpretation.** Exports return an int code; this raises `EclibError`
carrying the code's *name*, because ``ERR_GEN_ECLAB_LOADED`` (EC-Lab has the
instrument) and ``ERR_GEN_NOTCONNECTED`` call for different operator actions
and a bare ``-9`` distinguishes neither.
"""

import ctypes
import queue
import threading
from typing import Any, Optional

from helao.deploy.hte.drivers.pstat.biologic import vendor
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

#: A channel that keeps producing messages must not keep a poll in this loop.
MAX_MESSAGES_PER_DRAIN = 100

#: Capacity of the scratch buffer BL_GetMessage writes into per call.
_MESSAGE_BUF_SIZE = 4096


class EclibError(RuntimeError):
    def __init__(self, code: int, context: str = ""):
        self.code = int(code)
        self.name = vendor.ERROR_NAMES.get(self.code, f"unknown code {self.code}")
        super().__init__(
            f"{context}: {self.name} ({self.code})" if context else self.name
        )


class EclibClient:
    """One dedicated worker thread per instrument connection. Every vendor
    export -- real or simulated -- is called from that thread only.

    Only the DLL invocation itself (`self._dll[name](*args)`, inside `_call`)
    runs on the worker; a method's out-param structs/buffers and their
    `byref(...)` wrappers are built on the caller's thread, before the call
    is submitted. That is safe, not merely convenient: `_submit` blocks the
    calling thread on `result.get()` for the whole round trip, so nothing
    else ever touches those buffers while the worker is writing into them --
    there is no concurrent access to guard against. It also means allocation
    never contends with the DLL for the worker's attention, and there is
    nothing here slow enough for that to matter regardless (it's a handful of
    ctypes structs). The rule this leaves standing: anything added to this
    class that would itself touch the DLL, or block, while building
    arguments belongs *inside* the submitted call, not before it -- building
    plain Python/ctypes values in the caller is fine forever.
    """

    def __init__(self, sdk_path: str, simulate: bool = False):
        self.sdk_path = sdk_path
        self.simulate = simulate
        self.idn: Optional[int] = None
        self._closed = False
        self._requests: "queue.Queue[Any]" = queue.Queue()
        self._worker = threading.Thread(
            target=self._serve, name="eclib-worker", daemon=True
        )
        self._worker.start()
        if simulate:
            from helao.deploy.hte.drivers.pstat.biologic import sim

            self._dll = self._submit(sim.load_dll, sdk_path)
        else:
            self._dll = self._submit(vendor.load_dll, sdk_path)

    # -- the one thread ----------------------------------------------------

    def _serve(self) -> None:
        while True:
            item = self._requests.get()
            if item is None:
                return
            fn, args, result = item
            try:
                result.put((fn(*args), None))
            except BaseException as exc:  # returned to the caller's thread
                result.put((None, exc))

    def _submit(self, fn, *args):
        if self._closed:
            raise EclibError(-1, "client is closed")
        result: "queue.Queue[Any]" = queue.Queue(maxsize=1)
        self._requests.put((fn, args, result))
        value, exc = result.get()
        if exc is not None:
            raise exc
        return value

    def _call(self, name: str, *args) -> int:
        """Look up and invoke one vendor export. Never call this directly --
        it does the invoking, but only `_checked`/`test_connection` submit it
        onto the worker thread, which is what actually serializes it."""
        return self._dll[name](*args)

    def _checked(self, name: str, *args) -> None:
        code = self._submit(self._call, name, *args)
        if code != 0:
            raise EclibError(code, name)

    # -- connection ----------------------------------------------------

    def connect(self, address: str, timeout: int = 5) -> vendor.DeviceInfo:
        idn = ctypes.c_int32()
        info = vendor.DeviceInfo()
        self._checked(
            "BL_Connect",
            address.encode(),
            timeout,
            ctypes.byref(idn),
            ctypes.byref(info),
        )
        self.idn = idn.value
        return info

    def disconnect(self) -> None:
        if self.idn is not None:
            self._checked("BL_Disconnect", self.idn)
            self.idn = None

    def test_connection(self) -> bool:
        # A predicate, never an exception: `driver.connect` branches on this
        # for idempotency, and closed / never-connected / a failing probe all
        # mean the same thing to that caller -- "not connected".
        if self._closed or self.idn is None:
            return False
        try:
            return self._submit(self._call, "BL_TestConnection", self.idn) == 0
        except EclibError:
            return False

    # -- channel/board info ----------------------------------------------

    def channel_info(self, channel: int) -> vendor.ChannelInfo:
        info = vendor.ChannelInfo()
        self._checked("BL_GetChannelInfos", self.idn, channel, ctypes.byref(info))
        return info

    def board_type(self, channel: int) -> int:
        out = ctypes.c_uint32()
        self._checked("BL_GetChannelBoardType", self.idn, channel, ctypes.byref(out))
        return out.value

    def current_values(self, channel: int) -> vendor.CurrentValues:
        cv = vendor.CurrentValues()
        self._checked("BL_GetCurrentValues", self.idn, channel, ctypes.byref(cv))
        return cv

    # -- firmware and techniques ------------------------------------------

    def load_firmware(
        self, channel: int, kernel: str, fpga: str, force: bool = False
    ) -> None:
        channels = vendor.ChannelsArray()
        channels[channel] = True
        results = vendor.ResultsArray()
        self._checked(
            "BL_LoadFirmware",
            self.idn,
            channels,
            results,
            len(results),
            force,
            True,
            kernel.encode(),
            fpga.encode(),
        )
        # The call's own code covers the request; a per-channel firmware
        # failure is reported in its results slot instead.
        if results[channel] != 0:
            raise EclibError(results[channel], "BL_LoadFirmware")

    def load_technique(
        self,
        channel: int,
        ecc_path: str,
        params: vendor.EccParams,
        first: bool,
        last: bool,
    ) -> None:
        self._checked(
            "BL_LoadTechnique",
            self.idn,
            channel,
            ecc_path.encode(),
            params,
            first,
            last,
            False,
        )

    def define_params(self, entries: list[tuple[str, object, int]]) -> vendor.EccParams:
        array = (vendor.EccParam * len(entries))()
        for i, (label, value, index) in enumerate(entries):
            slot = ctypes.byref(array[i])
            # bool before int: isinstance(True, int) is True, so a naive
            # dispatch would send a flag to BL_DefineIntParameter.
            if isinstance(value, bool):
                self._checked(
                    "BL_DefineBoolParameter", label.encode(), value, index, slot
                )
            elif isinstance(value, float):
                self._checked(
                    "BL_DefineSglParameter", label.encode(), value, index, slot
                )
            elif isinstance(value, int):
                self._checked(
                    "BL_DefineIntParameter", label.encode(), value, index, slot
                )
            else:
                raise EclibError(
                    -4, f"{label}: no DLL setter for {type(value).__name__}"
                )
        params = vendor.EccParams(len(entries), ctypes.cast(array, vendor.ECC_PARM))
        # The struct holds a bare pointer into `array`; keep it alive on the
        # object that gets handed back, or a GC before BL_LoadTechnique reads
        # it is a wrong parameter value or a crash, not a Python exception.
        params._keepalive = array
        return params

    def technique_ids(self, channel: int, count: int) -> list[int]:
        ids = []
        info = vendor.TechniqueInfos()
        for i in range(count):
            self._checked(
                "BL_GetTechniqueInfos", self.idn, channel, i, ctypes.byref(info)
            )
            ids.append(info.Id)
        return ids

    # -- run control and data ----------------------------------------------

    def start_channel(self, channel: int) -> None:
        self._checked("BL_StartChannel", self.idn, channel)

    def stop_channel(self, channel: int) -> None:
        self._checked("BL_StopChannel", self.idn, channel)

    def get_data(
        self, channel: int
    ) -> tuple[vendor.CurrentValues, vendor.DataInfo, list[int]]:
        buf = vendor.DataBuffer()
        info = vendor.DataInfo()
        values = vendor.CurrentValues()
        self._checked(
            "BL_GetData",
            self.idn,
            channel,
            buf,
            ctypes.byref(info),
            ctypes.byref(values),
        )
        n = info.NbRows * info.NbCols
        return values, info, list(buf[:n])

    def drain_messages(self, channel: int) -> list[str]:
        messages: list[str] = []
        while len(messages) < MAX_MESSAGES_PER_DRAIN:
            buf = ctypes.create_string_buffer(_MESSAGE_BUF_SIZE)
            size = ctypes.c_uint32(_MESSAGE_BUF_SIZE)
            self._checked("BL_GetMessage", self.idn, channel, buf, ctypes.byref(size))
            if size.value == 0:
                break
            messages.append(buf.value[: size.value].decode(errors="replace"))
        return messages

    # -- unit conversions ---------------------------------------------------

    def to_single(self, word: int, board_type: int) -> float:
        out = ctypes.c_float()
        self._checked(
            "BL_ConvertChannelNumericIntoSingle", word, ctypes.byref(out), board_type
        )
        return out.value

    def to_seconds(
        self, t_high: int, t_low: int, timebase: float, board_type: int
    ) -> float:
        words = (ctypes.c_uint32 * 2)(t_high, t_low)
        out = ctypes.c_double()
        self._checked(
            "BL_ConvertTimeChannelNumericIntoSeconds",
            words,
            ctypes.byref(out),
            timebase,
            board_type,
        )
        return out.value

    # -- lifecycle -----------------------------------------------------

    def close(self) -> None:
        if self._closed:
            return
        try:
            if self.idn is not None:
                self.disconnect()
        except EclibError:
            LOGGER.warning("BL_Disconnect failed during close", exc_info=True)
        finally:
            # A failed disconnect must not leave the object claiming a
            # connection it no longer has -- `test_connection` and a later
            # `connect` retry both depend on `idn` being cleared regardless.
            self.idn = None
            self._closed = True
            self._requests.put(None)
            self._worker.join(timeout=5)
