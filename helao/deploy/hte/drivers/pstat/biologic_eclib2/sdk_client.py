"""Execute an :class:`~.technique.ActionPlan` against the EC-Lib 2.0 SDK.

Two things this layer exists for.

**Serialization.** The SDK is documented as *not thread-safe*, "neither in
Python nor in C", and handles "cannot be shared among different threads". A
HELAO action server is asyncio plus executor threads, so nothing about the call
site guarantees one thread. Every vendor call is therefore marshalled onto one
dedicated worker thread owned by this client, and the guarantee holds no matter
which thread or coroutine calls in. It is enforced here rather than documented
as a caller obligation because a violation would show up as corrupted
acquisitions, not as an exception.

**Interpretation.** :mod:`technique` emits parameter *names*; this resolves them
against the loaded SDK's enums and calls the matching ``BL_Set*Parameter``. A
name this SDK build does not have is an error, never a silent skip.

Failures are re-raised as :class:`Eclib2Error`, which carries the vendor error
code's *name* -- the licensing codes in particular (-99900 not valid, -99902 EIS
not authorised) are the difference between "the cable is wrong" and "this
license does not cover impedance", and are otherwise a bare negative number.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

from helao.deploy.hte.drivers.pstat.biologic_eclib2 import data as ec2data
from helao.deploy.hte.drivers.pstat.biologic_eclib2 import vendor
from helao.deploy.hte.drivers.pstat.biologic_eclib2.technique import ActionPlan
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

#: ``ParamSet.kind`` -> (API method, vendor parameter enum).
_SETTERS: dict[str, tuple[str, str]] = {
    "float": ("BL_SetFloatParameter", "FloatParameter"),
    "float_array": ("BL_SetFloatArrayParameter", "FloatArrayParameter"),
    "int": ("BL_SetIntParameter", "IntParameter"),
    "bool": ("BL_SetBoolParameter", "BoolParameter"),
    "enum": ("BL_SetEnumParameter", "EnumParameter"),
    "enum_array": ("BL_SetEnumArrayParameter", "EnumArrayParameter"),
}

#: Which vendor enum an ``enum``/``enum_array`` parameter's *value* belongs to.
#: Keyed by parameter name because the parameter enums carry no such link, and
#: guessing would resolve a sweep mode against ``VsInitial`` -- where value 0
#: exists in both, so it would succeed and mean something else entirely.
_VALUE_ENUMS: dict[str, str] = {
    "EC_SDK_SWEEP_MODE": "SweepMode",
    "EC_SDK_VS_INITIAL": "VsInitial",
}

#: Vendor error codes worth naming a cause for.
_ERROR_HINTS: dict[str, str] = {
    "EC_SDK_ERROR_LICENSE_NOT_VALID": (
        "no valid license: put license_biologic_<hexblob>.lic at the SDK root"
    ),
    "EC_SDK_ERROR_LICENSE_NOT_AUTHORISED": (
        "the license does not authorise this command"
    ),
    "EC_SDK_ERROR_LICENSE_TECHNIQUE_EIS_NOT_AUTHORISED": (
        "the license does not cover EIS; PEIS/GEIS need the EIS option"
    ),
    "EC_SDK_ERROR_LICENSE_TECHNIQUE_NOT_AUTHORISED": (
        "the license does not cover this technique"
    ),
    "EC_SDK_ERROR_EIS_NOT_SUPPORTED_BY_CHANNEL": ("this channel has no EIS board"),
}


class Eclib2Error(RuntimeError):
    """A vendor call failed, with the error code's name where one was given."""

    def __init__(self, operation: str, message: str, code_name: str | None = None):
        self.operation = operation
        self.code_name = code_name
        hint = _ERROR_HINTS.get(code_name or "")
        parts = [f"{operation} failed", message]
        if code_name:
            parts.append(f"[{code_name}]")
        if hint:
            parts.append(f"-- {hint}")
        super().__init__(": ".join(parts[:2]) + " " + " ".join(parts[2:]).strip())


@dataclass
class PollResult:
    """One ``BL_DownloadRawData`` round, mapped to the action's columns.

    Attributes:
        running: Whether the channel is still running. A poll that returns no
            rows while running is the normal "nothing yet" state, not an error.
        rows: How many rows this poll carried.
        table: Column-oriented data over the action's full column contract, so
            successive polls of a composite action concatenate cleanly.
        technique_index: Which technique in the experiment produced the rows.
        technique_identifier: Its ``TechniqueIdentifier`` member name.
    """

    running: bool
    rows: int
    table: dict[str, list]
    technique_index: int = 0
    technique_identifier: str = "EC_SDK_TECHNIQUE_NONE"


@dataclass
class _LoadedPlan:
    plan: ActionPlan
    experiment_handle: int
    technique_handles: list[int] = field(default_factory=list)


class SdkClient:
    """Serialized access to one EC-Lib 2.0 instrument.

    Args:
        modules: The loaded vendor package (or :func:`~.sim.sim_modules`).
        dll_path: Path handed to the vendor ``ECLibAPI`` constructor.
    """

    def __init__(self, modules: vendor.SdkModules, dll_path: str):
        self._modules = modules
        self._constants = modules.constants
        self._error_class = modules.error_class
        # One worker, forever. Not a pool: the point is that exactly one thread
        # ever touches the SDK.
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="eclib2-sdk"
        )
        self._worker_id: int | None = None
        self._closed = False
        self._api = self._call("construct", lambda: modules.api_class(dll_path))
        self._connection: int | None = None
        self._device_info: Any = None
        self._loaded: dict[int, _LoadedPlan] = {}

    # -- thread discipline -------------------------------------------------

    def _call(self, operation: str, fn: Callable):
        """Run ``fn`` on the client's single worker thread."""
        if self._closed:
            raise Eclib2Error(operation, "client is closed")

        def wrapped():
            self._worker_id = threading.get_ident()
            try:
                return fn()
            except self._error_class as exc:  # type: ignore[misc]
                code = getattr(exc, "code", None)
                code_name = getattr(code, "name", None) or (
                    str(code) if code is not None else None
                )
                raise Eclib2Error(operation, str(exc), code_name) from exc

        return self._executor.submit(wrapped).result()

    @property
    def worker_thread_id(self) -> int | None:
        """Thread every vendor call has run on, for tests to assert against."""
        return self._worker_id

    def close(self) -> None:
        """Stop the worker thread. The client is unusable afterwards."""
        if self._closed:
            return
        self._closed = True
        self._executor.shutdown(wait=True)

    # -- enum resolution ---------------------------------------------------

    def _member(self, enum_name: str, member_name: str):
        return vendor.member(self._constants, enum_name, member_name)

    # -- connection --------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._connection is not None

    def connect(self, address: str, timeout_s: int = 120) -> Any:
        """``BL_Connect``. Ethernet only; EClib2 does not support USB."""
        handle, info = self._call(
            "BL_Connect", lambda: self._api.BL_Connect(address, timeout_s)
        )
        self._connection = handle
        self._device_info = info
        LOGGER.info(
            "eclib2 connected to %s (device_code=%s serial=%s)",
            address,
            getattr(info, "device_code", "?"),
            getattr(info, "serial_number", "?"),
        )
        return info

    def load_firmware(self, channel: int, force_reload: bool = False) -> None:
        """``BL_LoadFirmware`` for one channel.

        The per-channel results come back as a list of codes rather than as a
        raised error, so a channel that failed to load has to be checked
        explicitly -- otherwise the first acquisition fails instead.
        """
        conn = self._require_connection("BL_LoadFirmware")
        mask = [i == channel for i in range(self._max_channels())]
        results = self._call(
            "BL_LoadFirmware",
            lambda: self._api.BL_LoadFirmware(conn, mask, force_reload),
        )
        code = results[channel]
        name = getattr(code, "name", str(code))
        if name != "EC_SDK_ERROR_NOERROR":
            raise Eclib2Error(
                "BL_LoadFirmware", f"channel {channel} did not load firmware", name
            )

    def test_connection(self) -> None:
        conn = self._require_connection("BL_TestConnection")
        self._call("BL_TestConnection", lambda: self._api.BL_TestConnection(conn))

    def disconnect(self) -> None:
        if self._connection is None:
            return
        conn = self._connection
        # Cleared first, so a failing disconnect does not leave the client
        # believing it still owns a connection it cannot use.
        self._connection = None
        self._loaded.clear()
        self._call("BL_Disconnect", lambda: self._api.BL_Disconnect(conn))

    def _require_connection(self, operation: str) -> int:
        if self._connection is None:
            raise Eclib2Error(operation, "not connected")
        return self._connection

    def _max_channels(self) -> int:
        return int(getattr(self._api, "MAX_NUMBER_OF_CHANNELS", 16))

    # -- plan application --------------------------------------------------

    def apply_plan(self, channel: int, plan: ActionPlan) -> None:
        """Build the experiment for ``plan`` and load it onto ``channel``."""
        conn = self._require_connection("BL_CreateExperiment")
        self.clear(channel)

        floating = self._member("FloatingMode", "EC_SDK_FLOATING_MODE_FLOATING")
        connection_mode = self._member(
            "ConnectionMode", "EC_SDK_CONNECTION_MODE_STANDARD"
        )
        experiment = self._call(
            "BL_CreateExperiment",
            lambda: self._api.BL_CreateExperiment(
                self._device_info, floating, connection_mode
            ),
        )

        handles: list[int] = []
        try:
            for tech in plan.techniques:
                identifier = self._member("TechniqueIdentifier", tech.identifier)
                handle = self._call(
                    "BL_AddTechnique",
                    lambda i=identifier: self._api.BL_AddTechnique(experiment, i),
                )
                handles.append(handle)
                self._apply_params(handle, tech)
            self._call(
                "BL_LoadExperiment",
                lambda: self._api.BL_LoadExperiment(conn, channel, experiment),
            )
        except BaseException:
            # A half-built experiment left on the instrument would be loaded by
            # the next start and run something nobody asked for.
            try:
                self._call(
                    "BL_DeleteExperiment",
                    lambda: self._api.BL_DeleteExperiment(experiment),
                )
            except Exception:
                LOGGER.warning(
                    "eclib2 could not delete a half-built experiment", exc_info=True
                )
            raise

        self._loaded[channel] = _LoadedPlan(
            plan=plan, experiment_handle=experiment, technique_handles=handles
        )

    def _apply_params(self, handle: int, tech) -> None:
        for param in tech.params:
            try:
                method_name, param_enum = _SETTERS[param.kind]
            except KeyError:
                raise Eclib2Error(
                    "set_parameter", f"unknown parameter kind {param.kind!r}"
                ) from None
            parameter = self._member(param_enum, param.name)
            value = param.value
            if param.kind in ("enum", "enum_array"):
                value_enum = _VALUE_ENUMS.get(param.name)
                if value_enum is None:
                    raise Eclib2Error(
                        "set_parameter",
                        f"no value enum known for {param.name!r}",
                    )
                value = (
                    [self._member(value_enum, v) for v in param.value]
                    if param.kind == "enum_array"
                    else self._member(value_enum, param.value)
                )
            method = getattr(self._api, method_name)
            self._call(
                method_name,
                lambda m=method, p=parameter, v=value: m(handle, p, v),
            )

        if tech.irange is not None:
            mode_name, value_name = tech.irange
            mode = self._member("IRangeMode", mode_name)
            value = self._member("IRangeValue", value_name)
            self._call(
                "BL_SetIRange", lambda: self._api.BL_SetIRange(handle, mode, value)
            )
        if tech.erange is not None:
            erange = self._member("ERangeValue", tech.erange)
            self._call("BL_SetERange", lambda: self._api.BL_SetERange(handle, erange))
        if tech.bandwidth is not None:
            bandwidth = self._member("BandwidthValue", tech.bandwidth)
            self._call(
                "BL_SetBandwidth",
                lambda: self._api.BL_SetBandwidth(handle, bandwidth),
            )

    def clear(self, channel: int) -> None:
        """Forget and delete the experiment loaded on ``channel``, if any."""
        loaded = self._loaded.pop(channel, None)
        if loaded is None:
            return
        try:
            self._call(
                "BL_DeleteExperiment",
                lambda: self._api.BL_DeleteExperiment(loaded.experiment_handle),
            )
        except Exception:
            LOGGER.warning("eclib2 could not delete experiment", exc_info=True)

    def plan_for(self, channel: int) -> ActionPlan | None:
        loaded = self._loaded.get(channel)
        return loaded.plan if loaded is not None else None

    # -- run / read --------------------------------------------------------

    def start(self, channel: int) -> None:
        conn = self._require_connection("BL_StartChannel")
        if channel not in self._loaded:
            raise Eclib2Error("BL_StartChannel", f"no plan loaded on channel {channel}")
        self._call("BL_StartChannel", lambda: self._api.BL_StartChannel(conn, channel))

    def stop(self, channel: int) -> None:
        conn = self._require_connection("BL_StopChannel")
        self._call("BL_StopChannel", lambda: self._api.BL_StopChannel(conn, channel))

    def live_values(self, channel: int):
        conn = self._require_connection("BL_GetLiveValues")
        return self._call(
            "BL_GetLiveValues", lambda: self._api.BL_GetLiveValues(conn, channel)
        )

    def is_running(self, channel: int) -> bool:
        """Whether ``channel`` reports RUNNING.

        Compared by enum *name*, never by integer: the two shipped examples
        disagree on the polarity, and only the enum is authoritative.
        """
        state = getattr(self.live_values(channel), "channel_state", None)
        return getattr(state, "name", "") == "EC_SDK_CHANNEL_STATE_RUNNING"

    _READER_METHODS = {
        "ocv": ("BL_ProcessRawToOcvData", ec2data.ocv_rows),
        "step": (None, ec2data.step_rows),
        "eis": ("BL_ProcessRawToEisData", ec2data.eis_rows),
    }

    _STEP_METHODS = {
        "EC_SDK_TECHNIQUE_CA": "BL_ProcessRawToCaData",
        "EC_SDK_TECHNIQUE_CP": "BL_ProcessRawToCpData",
        "EC_SDK_TECHNIQUE_CV": "BL_ProcessRawToCvData",
    }

    def poll(self, channel: int) -> PollResult:
        """One ``BL_DownloadRawData`` round, mapped to the action's columns.

        The instrument erases data once downloaded, so this must be called
        often enough that its memory does not fill.
        """
        conn = self._require_connection("BL_DownloadRawData")
        loaded = self._loaded.get(channel)
        if loaded is None:
            raise Eclib2Error(
                "BL_DownloadRawData", f"no plan loaded on channel {channel}"
            )
        columns = loaded.plan.columns

        info, buffer = self._call(
            "BL_DownloadRawData",
            lambda: self._api.BL_DownloadRawData(conn, channel),
        )
        identifier = getattr(info.technique_identifier, "name", "")
        state = getattr(info.channel_state, "name", "")
        running = state == "EC_SDK_CHANNEL_STATE_RUNNING"
        rows_available = int(info.number_of_rows)

        if rows_available == 0:
            return PollResult(
                running=running,
                rows=0,
                table={c: [] for c in columns},
                technique_index=int(info.technique_index),
                technique_identifier=identifier,
            )

        from helao.deploy.hte.drivers.pstat.biologic_eclib2.technique import (
            READER_BY_IDENTIFIER,
        )

        reader = READER_BY_IDENTIFIER.get(identifier)
        if reader is None:
            raise Eclib2Error(
                "BL_DownloadRawData",
                f"no reader for technique {identifier!r}; the instrument "
                "produced rows this backend cannot map",
            )
        method_name, mapper = self._READER_METHODS[reader]
        if method_name is None:
            method_name = self._STEP_METHODS[identifier]
        method = getattr(self._api, method_name)
        rows = self._call(method_name, lambda: method(buffer, info))
        # `concat` over the action's contract, not the technique's, so a
        # composite's legs line up: a CA batch inside a PEIS action gets
        # process=0 and NaN in the frequency columns.
        table = ec2data.concat([mapper(rows)], columns=columns)
        return PollResult(
            running=running,
            rows=len(rows),
            table=table,
            technique_index=int(info.technique_index),
            technique_identifier=identifier,
        )


def open_client(
    *, simulate: bool, sdk_path: str | None = None, fail_on: dict | None = None
) -> SdkClient:
    """Build a client over the real SDK or the simulator.

    Args:
        simulate: Use :mod:`sim` instead of the vendor package. The vendor
            package is not imported at all in this case, which is what lets
            this backend load on Linux.
        sdk_path: Required unless simulating.
        fail_on: Simulator-only; see :class:`~.sim.SimECLibAPI`.
    """
    if simulate:
        from helao.deploy.hte.drivers.pstat.biologic_eclib2 import sim

        return SdkClient(sim.sim_modules(fail_on=fail_on), "<simulated>")
    if not sdk_path:
        raise ValueError("sdk_path is required when simulate is false")
    if not vendor.has_license(sdk_path):
        # Not fatal -- the license could legitimately live elsewhere on a
        # future SDK -- but every call failing with -99900 is worth predicting.
        LOGGER.warning(
            "no %s at %s; EC-Lib 2.0 calls will fail with "
            "EC_SDK_ERROR_LICENSE_NOT_VALID unless the license is installed",
            vendor.LICENSE_GLOB,
            sdk_path,
        )
    modules = vendor.load_sdk(sdk_path)
    return SdkClient(modules, str(vendor.dll_path(sdk_path)))
