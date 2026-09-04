"""Ocean Insight spectrometer driver built on the vendor OceanDirect API.

Wraps the vendor ``oceandirect`` package to operate an SR-series (OBP2-class)
spectrometer over USB. The :class:`OceanDirectSpec` driver owns only device
I/O; the action lifecycle (sample validation, ``ActionSession`` bookkeeping,
and the buffered-drain loop) lives in ``oceandirect_server.py``.

Four things about the vendor API shape the code below, and each one is a trap
if it is carried over from the SM303 driver next door:

* **``OceanDirectAPI`` is a process singleton** whose constructor loads the
  native SDK and calls ``odapi_initialize()``. It is therefore built in
  :meth:`OceanDirectSpec.connect`, never at import and never in ``__init__``
  (which the ``HelaoDriver`` ABC forbids anyway).
* **The lifecycle is two-level and ids are invalidated by close.** Discovery
  (``find_usb_devices`` → ``get_device_ids``) yields ids; ``open_device(id)``
  yields the per-device object. After ``close_device(id)`` the id is dead, so
  :meth:`reset` re-runs discovery rather than reopening a cached id.
* **Errors are raised, not returned.** Every vendor call can raise
  ``OceanDirectError``; there is no ``resp == 1`` success code to test. Each
  public method here converts that into a ``DriverResponse`` plus a logged
  message.
* **Integration time is microseconds**, and every optional feature is gated
  behind ``is_feature_id_enabled(FeatureID.X)``. Parameters are named
  ``*_us`` so no call site can inherit the SM303's millisecond assumption,
  and a request for an unsupported feature returns a failed response instead
  of raising out of an action.
"""

__all__ = ["OceanDirectSpec"]

import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

from helao.core.drivers.helao_driver import (
    DriverResponse,
    DriverResponseType,
    DriverStatus,
    HelaoDriver,
)
from helao.helpers import helao_logging as logging

from .oceandirect_enum import (
    HSAM_UNSUPPORTED_TRIGGER_MODES,
    LONG_FORMAT_KEYS,
    MAX_METADATA_BUFFER_SIZE,
    SRTrigMode,
)

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


@dataclass(frozen=True)
class _SDKNames:
    """The three SDK names the driver uses, from the vendor or the simulator.

    Normalizing both import branches into one holder is what keeps
    ``self.simulate`` out of the rest of the driver: every later call reads
    these attributes without caring which SDK supplied them.

    Attributes:
        FeatureID: The feature-identifier enum class, iterated to build the
            device's capability matrix.
        OceanDirectAPI: The singleton API class whose constructor loads the
            native SDK.
        OceanDirectError: The error class every vendor call may raise.
    """

    FeatureID: Any
    OceanDirectAPI: Any
    OceanDirectError: Any


class OceanDirectSpec(HelaoDriver):
    """Driver for an Ocean Insight spectrometer via the OceanDirect API.

    Attributes:
        api: The vendor ``OceanDirectAPI`` singleton, or ``None`` before
            :meth:`connect`.
        dev: The vendor per-device object, or ``None`` before :meth:`connect`.
        device_id: Vendor device id, invalidated whenever the device is closed.
        model: Device model string read from the device.
        serial: Device serial number read from the device.
        n_pixels: Detector pixel count read from ``get_spectrum_length()``.
        pxwl: Wavelength axis in nm read from ``get_wavelengths()``.
        features: ``{FeatureID name: bool}`` capability matrix.
        ready: Whether a device is open and interrogated.
    """

    def __init__(self, config: dict = {}):
        """Store config; no device or SDK I/O here (see :meth:`connect`).

        Args:
            config: Driver configuration (the server's ``params`` dict).
        """
        super().__init__(config=config)
        self.config_dict = self.config

        # Device selection. serial_number is preferred because it is stable
        # across reboots and unambiguous on a multi-device host; dev_index is
        # the positional fallback.
        self.serial_number: Optional[str] = self.config_dict.get("serial_number")
        self.dev_index: int = self.config_dict.get("dev_index", 0)

        self.simulate: bool = bool(self.config_dict.get("simulate", False))
        self.allow_no_sample: bool = bool(
            self.config_dict.get("allow_no_sample", False)
        )
        self.open_retries: int = int(self.config_dict.get("open_retries", 3))
        self.open_timeout_ms: int = int(self.config_dict.get("open_timeout_ms", 500))
        self.default_int_time_us: int = int(
            self.config_dict.get("int_time_us", 100_000)
        )

        # Populated by connect(); nothing here touches the device.
        self._sdk: Optional[_SDKNames] = None
        self.api: Any = None
        self.dev: Any = None
        self.device_id: Optional[int] = None
        self.model: Optional[str] = None
        self.serial: Optional[str] = None
        self.n_pixels: int = 0
        self.pxwl: list[float] = []
        self.int_time_min_us: Optional[int] = None
        self.int_time_max_us: Optional[int] = None
        self.int_time_increment_us: Optional[int] = None
        self.max_intensity: Optional[int] = None
        # Tri-state: True/False = the device answered, None = the probe failed
        # and availability is unknown. See _probe_features.
        self.features: dict[str, Optional[bool]] = {}
        #: {FeatureID name: error} for probes that raised, empty when all
        #: probes answered.
        self.feature_probe_errors: dict[str, str] = {}
        self.ready: bool = False

        # The vendor warns that discovery and open must be serialized across
        # threads. Acquisition runs through run_in_executor, so a second
        # thread genuinely can arrive here.
        self._lock = threading.RLock()

        # Buffered-capture state, owned by the server's executor.
        self.buffering: bool = False
        self.spec_idx: int = 0
        #: Trigger mode currently armed, or None when never armed. Tracked so
        #: teardown can put the device back: a device left armed on an external
        #: trigger answers no later acquisition until one arrives.
        self.armed_trigger_mode: Optional[int] = None
        #: Continuous-strobe period and enable state as last written through
        #: this driver, or None while it has never been configured here.
        #: Cached so an integration-time change can warn about silencing a
        #: live strobe without paying two vendor round trips per acquisition.
        self.continuous_strobe_period_us: Optional[int] = None
        self.continuous_strobe_enabled: Optional[bool] = None

        #: Unserialized vendor reads currently in flight. Only the externally
        #: triggered path (`acquire_spectrum(serialize=False)`) contributes,
        #: and it is exactly the path that can leave a worker thread blocked
        #: inside the vendor call after its action has finished -- the SDK has
        #: no acquisition timeout, so `asyncio.wait_for` frees the coroutine
        #: and not the thread. A later device write then shares the handle
        #: with a pending read, which is worth reporting because the vendor
        #: renders that collision as an unresolvable numeric error code.
        #: Guarded by its own lock: the read deliberately holds no other.
        self._reads_in_flight: int = 0
        self._flight_lock = threading.Lock()

    # ------------------------------------------------------------------
    # SDK loading
    # ------------------------------------------------------------------
    def _load_sdk(self) -> "_SDKNames":
        """Import the vendor SDK (or the simulator) and cache the three names.

        Imported here rather than at module scope so this module -- and its
        tests -- import cleanly on a machine without the vendor wheel, the
        same way the Galil (``gclib``) and Gamry (``comtypes``) drivers behave.
        ``run_tests.py`` reports a missing third-party package as ``ENV``
        rather than ``FAIL`` for exactly this case.

        Both branches are normalized into a :class:`_SDKNames` holder so the
        rest of the driver reads the same three attributes either way and
        never branches on ``self.simulate`` again.
        """
        if self._sdk is not None:
            return self._sdk
        if self.simulate:
            from . import oceandirect_sim as sim_sdk

            # WARNING, not INFO: a station left on `simulate: true` produces a
            # complete, plausible-looking device_info for a device that was
            # never opened. That has already been mistaken for a device
            # reporting the wrong model.
            LOGGER.warning(
                "OceanDirect driver is SIMULATED (`simulate: true` in this "
                "server's params) -- no hardware will be opened. Remove that "
                "key and set `serial_number` (or `dev_index`) to use the real "
                "spectrometer."
            )
            self._sdk = _SDKNames(
                FeatureID=sim_sdk.FeatureID,
                OceanDirectAPI=sim_sdk.OceanDirectAPI,
                OceanDirectError=sim_sdk.OceanDirectError,
            )
            return self._sdk
        from oceandirect.OceanDirectAPI import (  # type: ignore[import-not-found]
            FeatureID,
            OceanDirectAPI,
            OceanDirectError,
        )

        self._sdk = _SDKNames(
            FeatureID=FeatureID,
            OceanDirectAPI=OceanDirectAPI,
            OceanDirectError=OceanDirectError,
        )
        return self._sdk

    @property
    def _error_cls(self):
        """The SDK's error class, or ``Exception`` before the SDK is loaded."""
        if self._sdk is None:
            return Exception
        return self._sdk.OceanDirectError

    @staticmethod
    def _err_detail(exc: Exception) -> str:
        """Render an ``OceanDirectError`` (or any exception) for a log line."""
        getter = getattr(exc, "get_error_details", None)
        if callable(getter):
            try:
                details = getter()
            except Exception:
                details = None
            # The vendor documents a (code, message) pair; anything else is a
            # shape this build has not seen, so fall through to repr().
            if isinstance(details, tuple) and len(details) == 2:
                return f"[{details[0]}] {details[1]}"
        return repr(exc)

    # ------------------------------------------------------------------
    # HelaoDriver ABC
    # ------------------------------------------------------------------
    def connect(self) -> DriverResponse:
        """Load the SDK, discover and open the device, and interrogate it.

        Returns:
            ``DriverResponse`` reporting connection success or failure, with
            the device-info payload in ``data`` on success.
        """
        try:
            sdk = self._load_sdk()
        except ImportError as exc:
            LOGGER.error(f"oceandirect package is not importable: {exc}")
            return DriverResponse(
                response=DriverResponseType.failed,
                message=f"oceandirect not installed: {exc}",
                status=DriverStatus.uninitialized,
            )
        try:
            with self._lock:
                if self.api is None:
                    # Constructor loads the native SDK and calls
                    # odapi_initialize(); it is a singleton, so repeated
                    # construction returns the same underlying state.
                    self.api = sdk.OceanDirectAPI()
                self._open_selected_device()
                self._interrogate_device()
                self._apply_default_integration_time()
            self.ready = True
            LOGGER.info(
                f"OceanDirect connected: model={self.model} serial={self.serial} "
                f"pixels={self.n_pixels} id={self.device_id}"
            )
            return DriverResponse(
                response=DriverResponseType.success,
                message=f"connected to {self.model} ({self.serial})",
                data=self.device_info(),
                status=DriverStatus.ok,
            )
        except Exception as exc:
            LOGGER.error(
                f"OceanDirect connect failed: {self._err_detail(exc)}", exc_info=True
            )
            self.ready = False
            self.dev = None
            self.device_id = None
            return DriverResponse(
                response=DriverResponseType.failed,
                message=self._err_detail(exc),
                status=DriverStatus.error,
            )

    def get_status(self) -> DriverResponse:
        """Return whether a device is open and interrogated.

        Returns:
            ``DriverResponse`` with ``status=ok`` when ready, ``busy`` while a
            buffered capture is running, else ``uninitialized``.
        """
        if not (self.ready and self.dev is not None):
            return DriverResponse(
                response=DriverResponseType.success,
                message="no device open",
                status=DriverStatus.uninitialized,
            )
        # A triggered read inside the vendor call is reported but deliberately
        # does NOT make the status `busy`: that read can outlive its action,
        # and a stranded one would then pin the server at busy for the rest
        # of its life. Diagnosable, not load-bearing.
        return DriverResponse(
            response=DriverResponseType.success,
            data={
                "buffering": self.buffering,
                "reads_in_flight": self.reads_in_flight,
                "armed_trigger_mode": self.armed_trigger_mode,
            },
            status=DriverStatus.busy if self.buffering else DriverStatus.ok,
        )

    def stop(self) -> DriverResponse:
        """Abort any in-progress acquisition (ABC-required zero-arg stop)."""
        if self.dev is None:
            return DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.uninitialized
            )
        errors = []
        # Disarming comes first and is unconditional: it is the only one of the
        # two that a bufferless device supports, and the one that matters most
        # -- a device left armed blocks every later read. `abort_acquisition`
        # is buffer-only ("applicable to OBP2 enabled devices" per the vendor),
        # so on an SR4 it is expected to fail and must not mask the disarm.
        disarm = self.disarm_trigger()
        if disarm.response != DriverResponseType.success:
            errors.append(f"disarm_trigger: {disarm.message}")
        if self.buffering:
            try:
                self._abort_acquisition()
            except Exception as exc:
                errors.append(f"abort_acquisition: {self._err_detail(exc)}")
        if errors:
            LOGGER.error(f"OceanDirect stop incomplete: {'; '.join(errors)}")
            return DriverResponse(
                response=DriverResponseType.failed,
                message="; ".join(errors),
                status=DriverStatus.error,
            )
        return DriverResponse(
            response=DriverResponseType.success, status=DriverStatus.ok
        )

    def reset(self) -> DriverResponse:
        """Close and reopen the device.

        A plain reopen is impossible: ``close_device()`` invalidates the id,
        so :meth:`connect` must re-run discovery. Clearing ``device_id`` here
        is what forces that.
        """
        self.disconnect()
        self.device_id = None
        self.dev = None
        return self.connect()

    def disconnect(self) -> DriverResponse:
        """Close the device, releasing its id.

        Returns:
            ``DriverResponse`` reporting close success or failure.
        """
        try:
            with self._lock:
                if self.dev is not None and self.armed_trigger_mode is not None:
                    # Closing while armed leaves the hardware waiting on a
                    # trigger; the next open would inherit that state.
                    try:
                        self.disarm_trigger()
                    except Exception as exc:
                        LOGGER.warning(
                            "could not disarm trigger during disconnect: "
                            f"{self._err_detail(exc)}"
                        )
                if self.dev is not None and self.buffering:
                    # Leaving the hardware buffer armed would keep the device
                    # acquiring after the server is gone.
                    try:
                        self.stop_buffered()
                    except Exception as exc:
                        LOGGER.warning(
                            "could not stop buffered capture during disconnect: "
                            f"{self._err_detail(exc)}"
                        )
                if self.api is not None and self.device_id is not None:
                    self.api.close_device(self.device_id)
                self.dev = None
                self.device_id = None
                self.ready = False
            return DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception as exc:
            LOGGER.error(f"OceanDirect disconnect failed: {self._err_detail(exc)}")
            self.dev = None
            self.device_id = None
            self.ready = False
            return DriverResponse(
                response=DriverResponseType.failed,
                message=self._err_detail(exc),
                status=DriverStatus.error,
            )

    async def async_shutdown(self) -> DriverResponse:
        """Close the device on server shutdown."""
        return self.disconnect()

    async def estop(self, switch: bool, *args, **kwargs) -> bool:
        """Device-level e-stop: abort acquisition and darken any light source.

        Server-side estop bookkeeping (the ``actionservermodel.estop`` flag and
        terminating in-flight actions) belongs to the action-server framework,
        not here.

        Args:
            switch: ``True`` to engage e-stop, ``False`` to clear it.

        Returns:
            The applied boolean state.
        """
        switch = bool(switch)
        if switch and self.dev is not None:
            # Each leg is guarded separately: a device that lacks one of these
            # features must not prevent the others from firing.
            for label, fn in (
                ("abort acquisition", self._abort_acquisition),
                ("lamp off", lambda: self._set_lamp(False)),
                ("single strobe off", lambda: self._set_single_strobe_enable(False)),
                (
                    "continuous strobe off",
                    lambda: self._set_continuous_strobe_enable(False),
                ),
            ):
                try:
                    fn()
                except Exception as exc:
                    LOGGER.warning(f"estop leg '{label}': {self._err_detail(exc)}")
        return switch

    # ------------------------------------------------------------------
    # connect() helpers
    # ------------------------------------------------------------------
    def _open_selected_device(self) -> None:
        """Discover devices and open the configured one.

        Selection is by ``serial_number`` when configured, else by
        ``dev_index``. The vendor's own ``from_serial_number()`` is avoided
        deliberately: it opens every device to compare serials and its
        close-on-mismatch branch tests the wrong status value, leaking handles.
        """
        found = self.api.find_usb_devices()
        ids = self.api.get_device_ids()
        LOGGER.info(f"OceanDirect discovery found {found} device(s), ids={ids}")
        if not ids:
            raise RuntimeError("OceanDirect discovery found no devices")

        if self.serial_number is not None:
            match = None
            for dev_id in ids:
                try:
                    serial = self.api.get_serial_number(dev_id)
                except Exception as exc:
                    LOGGER.warning(
                        f"could not read serial of device {dev_id}: "
                        f"{self._err_detail(exc)}"
                    )
                    continue
                if isinstance(serial, bytes):
                    serial = serial.decode()
                if serial == self.serial_number:
                    match = dev_id
                    break
            if match is None:
                raise RuntimeError(
                    f"no OceanDirect device with serial_number "
                    f"'{self.serial_number}' among ids {ids}"
                )
            self.device_id = match
        else:
            if self.dev_index >= len(ids):
                raise RuntimeError(
                    f"dev_index {self.dev_index} out of range; "
                    f"discovery found {len(ids)} device(s)"
                )
            self.device_id = ids[self.dev_index]

        self.dev = self.api.open_device2(
            self.device_id, self.open_retries, self.open_timeout_ms
        )

    def _interrogate_device(self) -> None:
        """Read identity, geometry, integration-time bounds and capabilities."""
        dev = self.dev
        self.serial = self._decode(dev.get_serial_number())
        self.model = self._decode(dev.get_model())
        self.n_pixels = int(dev.get_spectrum_length())
        self.pxwl = [float(w) for w in dev.get_wavelengths()]
        if len(self.pxwl) != self.n_pixels:
            # Not fatal, but every row builder trims to the shorter of the two
            # rather than trusting either number.
            LOGGER.warning(
                f"wavelength array length {len(self.pxwl)} != pixel count "
                f"{self.n_pixels}; rows will be trimmed to the shorter"
            )
        self.int_time_min_us = int(dev.get_minimum_integration_time())
        self.int_time_max_us = int(dev.get_maximum_integration_time())
        try:
            self.int_time_increment_us = int(dev.get_integration_time_increment())
        except Exception as exc:
            LOGGER.warning(
                f"integration-time increment unavailable, assuming 1 us: "
                f"{self._err_detail(exc)}"
            )
            self.int_time_increment_us = 1
        try:
            self.max_intensity = int(dev.get_max_intensity())
        except Exception as exc:
            LOGGER.warning(f"max intensity unavailable: {self._err_detail(exc)}")
            self.max_intensity = None
        self.features = self._probe_features()
        LOGGER.info(
            "OceanDirect capabilities: "
            + ", ".join(sorted(k for k, v in self.features.items() if v))
        )

    def _probe_features(self) -> dict[str, Optional[bool]]:
        """Return the device's ``FeatureID`` matrix as an explicit tri-state.

        ``True``/``False`` mean the device answered; ``None`` means the probe
        itself failed and the feature's availability is **unknown**.

        That distinction is the whole point. This originally recorded a raised
        probe as ``False``, which made "the device says no" and "we could not
        ask" the same answer -- and since every optional endpoint gates on this
        matrix, an unreliable probe silently disabled features that work. A
        real OCEANSR4 reported all 38 features ``False`` while acquisition, the
        serial read and the firmware/FPGA revisions all plainly worked, and the
        old shape could not tell anyone which of the two it was looking at.
        """
        matrix: dict[str, Optional[bool]] = {}
        # Via _load_sdk() rather than self._sdk: it is already cached by the
        # time connect() gets here, and going through the accessor keeps this
        # method callable without asserting the cache is populated.
        feature_enum = self._load_sdk().FeatureID
        errors: dict[str, str] = {}
        for feature in feature_enum:
            try:
                matrix[feature.name] = bool(self.dev.is_feature_id_enabled(feature))
            except Exception as exc:
                matrix[feature.name] = None
                errors[feature.name] = self._err_detail(exc)
        self.feature_probe_errors = errors

        unknown = [name for name, state in matrix.items() if state is None]
        if unknown:
            sample = errors.get(unknown[0], "")
            LOGGER.warning(
                f"{len(unknown)} of {len(matrix)} feature probes failed on "
                f"{self.model}; those features are UNKNOWN, not absent, and "
                f"their endpoints will be attempted rather than refused. "
                f"First error: {sample}"
            )
        elif not any(matrix.values()):
            # Every probe answered, and every answer was no. Worth saying out
            # loud: it means this server can only do plain acquisition, and it
            # is also what a device with a broken capability report looks like
            # when the report does not raise.
            LOGGER.warning(
                f"{self.model} reports every FeatureID as unavailable. Plain "
                "acquisition still works; buffered capture, TEC, shutter, lamp "
                "and strobe endpoints will refuse. If a feature is known to "
                "work on this unit, its report is untrustworthy -- say so "
                "rather than trusting /get_device_info."
            )
        return matrix

    def _apply_default_integration_time(self) -> None:
        """Set the configured default integration time, clamped to the device."""
        applied = self._set_integration_time_unlocked(self.default_int_time_us)
        LOGGER.info(f"integration time set to {applied} us")

    @staticmethod
    def _decode(value) -> str:
        """Decode a vendor string that may arrive as ``bytes``."""
        if isinstance(value, bytes):
            return value.decode(errors="replace")
        return str(value)

    def _require(self, feature_name: str, caller: str) -> None:
        """Raise only when the device explicitly reported ``feature_name`` off.

        An **unknown** state (the probe raised, so the matrix holds ``None``)
        does not block the call. The vendor call is itself the real gate: an
        unsupported command raises ``OceanDirectError``, which every public
        method already turns into a failed ``DriverResponse``. So attempting
        it costs an error message, while refusing on an unknown would disable
        a feature that may work perfectly -- and on a device whose capability
        probe fails wholesale, refusing would disable all of them.
        """
        state = self.features.get(feature_name)
        if state is False:
            raise RuntimeError(
                f"{caller}: device {self.model} reports no support for "
                f"{feature_name}"
            )
        if state is None:
            LOGGER.info(
                f"{caller}: {feature_name} support is unknown on {self.model} "
                "(capability probe failed); attempting anyway"
            )

    def _require_ready(self, caller: str) -> None:
        """Raise unless a device is open."""
        if self.dev is None or not self.ready:
            raise RuntimeError(f"{caller}: no device is open")

    # ------------------------------------------------------------------
    # Device info
    # ------------------------------------------------------------------
    def device_info(self) -> dict:
        """Return the full identity/geometry/capability dump.

        This is the capability probe the whole endpoint surface is designed
        around: it is the only way to learn which ``Advanced`` features the
        physical device actually exposes.
        """
        info: dict[str, Any] = {
            "model": self.model,
            "serial_number": self.serial,
            "device_id": self.device_id,
            "n_pixels": self.n_pixels,
            "wl_min": min(self.pxwl) if self.pxwl else None,
            "wl_max": max(self.pxwl) if self.pxwl else None,
            "int_time_min_us": self.int_time_min_us,
            "int_time_max_us": self.int_time_max_us,
            "int_time_increment_us": self.int_time_increment_us,
            "max_intensity": self.max_intensity,
            "simulated": self.simulate,
            "features": dict(self.features),
            # A reader cannot otherwise tell "device said no" from "we could
            # not ask": both used to render as false. `features` now carries
            # null for unknown, and these two summarize it.
            "feature_report": (
                "unreliable"
                if self.feature_probe_errors
                else ("all_unavailable" if not any(self.features.values()) else "ok")
            ),
            "feature_probe_errors": dict(self.feature_probe_errors),
            "armed_trigger_mode": self.armed_trigger_mode,
            "trigger_modes": {m.name: int(m) for m in SRTrigMode},
            # As configured through this driver. Reported because a strobe
            # whose period is not shorter than the integration time is
            # silently inert, and this is where that is diagnosed.
            "continuous_strobe_enabled": self.continuous_strobe_enabled,
            "continuous_strobe_period_us": self.continuous_strobe_period_us,
            "reads_in_flight": self.reads_in_flight,
        }
        if self.dev is not None:
            try:
                info["int_time_us"] = int(self.dev.get_integration_time())
            except Exception as exc:
                LOGGER.warning(
                    f"could not read integration time: {self._err_detail(exc)}"
                )
            info["continuous_strobe_fires"] = self.continuous_strobe_fires(
                self.continuous_strobe_period_us, info.get("int_time_us")
            )
            # The SDK's only documented way to ask whether the device is idle.
            # Vendor-documented as "very few devices supported this command",
            # so None here means "could not ask", not "not idle" -- but on a
            # device that does answer it is the one direct read of the state
            # a colliding transfer would be caused by.
            info["idle_state"] = self._safe_bool(
                self.dev.Advanced, "get_device_idle_state"
            )
            info["trigger_mode"] = self._safe_int(self.dev, "get_trigger_mode")
            info.update(self.acquisition_delay_bounds())
            for key, getter in (
                ("revision_firmware", "get_revision_firmware"),
                ("revision_fpga", "get_revision_fpga"),
            ):
                try:
                    info[key] = self._decode(getattr(self.dev.Advanced, getter)())
                except Exception:
                    info[key] = None
        return info

    def get_device_info(self) -> DriverResponse:
        """``device_info()`` wrapped in a ``DriverResponse``."""
        try:
            self._require_ready("get_device_info")
            return DriverResponse(
                response=DriverResponseType.success,
                data=self.device_info(),
                status=DriverStatus.ok,
            )
        except Exception as exc:
            return self._failed("get_device_info", exc)

    def _failed(
        self,
        caller: str,
        exc: Exception,
        data: Optional[dict] = None,
        hint: Optional[str] = None,
    ) -> DriverResponse:
        """Log ``exc`` against ``caller`` and wrap it as a failed response.

        Args:
            caller: Name used in the log line.
            exc: The exception being reported.
            data: State worth carrying on the failure. The vendor's own error
                strings are bare codes, so what the device was doing is often
                the only diagnosable part.
            hint: Appended to the message. For a vendor error whose code this
                build cannot resolve, a named likely cause is the difference
                between a station diagnosing it and filing a bug.
        """
        detail = self._err_detail(exc)
        message = f"{detail} -- {hint}" if hint else detail
        LOGGER.error(f"{caller} failed: {message}")
        return DriverResponse(
            response=DriverResponseType.failed,
            message=message,
            data=dict(data or {}),
            status=DriverStatus.error,
        )

    # ------------------------------------------------------------------
    # Acquisition configuration
    # ------------------------------------------------------------------
    def clamp_integration_time_us(self, int_time_us: int) -> int:
        """Clamp to the device's range and snap down to its increment.

        Snapping is downward from the minimum so the result is always a value
        the device accepts; asking for an off-grid value raises on some
        models and is silently rounded on others, and the difference is not
        worth discovering at a station.
        """
        lo = self.int_time_min_us if self.int_time_min_us is not None else 1
        hi = self.int_time_max_us if self.int_time_max_us is not None else int_time_us
        step = self.int_time_increment_us or 1
        value = int(max(lo, min(hi, int(int_time_us))))
        if step > 1:
            value = lo + ((value - lo) // step) * step
        return int(max(lo, min(hi, value)))

    def _set_integration_time_unlocked(self, int_time_us: int) -> int:
        applied = self.clamp_integration_time_us(int_time_us)
        if applied != int(int_time_us):
            LOGGER.info(
                f"requested integration time {int_time_us} us adjusted to "
                f"{applied} us (device range "
                f"{self.int_time_min_us}-{self.int_time_max_us} us, increment "
                f"{self.int_time_increment_us} us)"
            )
        self.dev.set_integration_time(applied)
        self._warn_if_strobe_silenced(applied)
        return applied

    def set_integration_time_us(self, int_time_us: int) -> DriverResponse:
        """Set integration time in microseconds, clamped to the device.

        Args:
            int_time_us: Requested integration time in **microseconds**.

        Returns:
            ``DriverResponse`` whose ``data`` carries the requested and
            actually-applied values.
        """
        try:
            self._require_ready("set_integration_time_us")
            with self._lock:
                applied = self._set_integration_time_unlocked(int_time_us)
            return DriverResponse(
                response=DriverResponseType.success,
                data={"requested_us": int(int_time_us), "int_time_us": applied},
                status=DriverStatus.ok,
            )
        except Exception as exc:
            return self._failed("set_integration_time_us", exc)

    def set_processing(
        self,
        scans_to_average: Optional[int] = None,
        boxcar_width: Optional[int] = None,
    ) -> DriverResponse:
        """Configure on-device averaging and boxcar smoothing.

        Both are device-side operations in OceanDirect, unlike the SM303 where
        averaging was a read-call argument.

        Args:
            scans_to_average: Spectra the device averages per returned
                spectrum; ``None`` leaves it unchanged.
            boxcar_width: On-device boxcar half-width; ``None`` leaves it
                unchanged.

        Returns:
            ``DriverResponse`` carrying the values read back from the device.
        """
        try:
            self._require_ready("set_processing")
            if (
                scans_to_average is not None
                and int(scans_to_average) > 1
                and self.armed_trigger_mode in HSAM_UNSUPPORTED_TRIGGER_MODES
            ):
                # scans_to_average > 1 is what selects High Speed Averaging
                # Mode, and the manual's acquisition-mode table lists HSAM as
                # supporting only software and external-edge triggers. Refusing
                # is better than letting the device arbitrate: the two features
                # both want to own the integration time, and which one wins is
                # not documented.
                raise RuntimeError(
                    f"set_processing: scans_to_average={scans_to_average} "
                    "selects High Speed Averaging Mode, which cannot be "
                    f"combined with trigger mode "
                    f"{SRTrigMode(self.armed_trigger_mode).name} "
                    "(the level trigger owns the integration time). Use "
                    "scans_to_average=1, or arm software/external-edge instead."
                )
            with self._lock:
                if scans_to_average is not None:
                    self.dev.set_scans_to_average(int(scans_to_average))
                if boxcar_width is not None:
                    self.dev.set_boxcar_width(int(boxcar_width))
                data = {
                    "scans_to_average": int(self.dev.get_scans_to_average()),
                    "boxcar_width": int(self.dev.get_boxcar_width()),
                }
            return DriverResponse(
                response=DriverResponseType.success,
                data=data,
                status=DriverStatus.ok,
            )
        except Exception as exc:
            return self._failed("set_processing", exc)

    def set_trigger_mode(self, mode: int = SRTrigMode.software) -> DriverResponse:
        """Set the trigger source and report the value read back.

        Trigger-mode integers are defined by the device manual, not the SDK,
        so the write is verified by reading it back rather than assumed.

        Args:
            mode: Trigger mode integer (see :class:`SRTrigMode`).

        Returns:
            ``DriverResponse`` with the requested and read-back modes.
        """
        try:
            self._require_ready("set_trigger_mode")
            # Validated here rather than left to the device. An out-of-range
            # mode is a caller mistake, and the vendor's own error for one is
            # a bare code that names neither the value nor the alternatives.
            try:
                resolved = SRTrigMode(int(mode))
            except ValueError:
                raise RuntimeError(
                    f"set_trigger_mode: {mode!r} is not an SR-series trigger "
                    f"mode. {self.model} supports "
                    + ", ".join(f"{m.value}={m.name}" for m in SRTrigMode)
                ) from None
            pending = self.reads_in_flight
            if pending:
                # Not refused: the counter can only be cleared by the read
                # returning, so refusing would make a stranded thread an
                # unrecoverable lockout needing a server restart. Reported
                # instead, on the success path as well as the failure one.
                LOGGER.warning(
                    f"set_trigger_mode with {pending} triggered read(s) still "
                    "inside the vendor call; this write shares the device "
                    "handle with them and may fail at the transport level"
                )
            with self._lock:
                try:
                    self.dev.set_trigger_mode(int(resolved))
                except Exception as exc:
                    # The vendor's error is a numeric code this build cannot
                    # resolve -- the table ships only in the C SDK -- so the
                    # diagnosable part is what the device is doing and what
                    # mode it is actually left in.
                    return self._failed(
                        "set_trigger_mode",
                        exc,
                        data={
                            "requested": int(resolved),
                            "mode_name": resolved.name,
                            "trigger_mode": self._safe_int(
                                self.dev, "get_trigger_mode"
                            ),
                            "reads_in_flight": pending,
                        },
                        hint=self._trigger_write_hint(resolved, pending),
                    )
                try:
                    readback = int(self.dev.get_trigger_mode())
                except Exception as exc:
                    LOGGER.warning(
                        f"trigger mode not read-backable: {self._err_detail(exc)}"
                    )
                    readback = None
            if readback is not None and readback != int(resolved):
                LOGGER.warning(
                    f"trigger mode requested {int(resolved)} "
                    f"({resolved.name}) but device reports {readback}. On an "
                    "SR4 with the default (Option 1) firmware external "
                    "triggering is not supported at all and only mode 0 "
                    "(software) is available."
                )
            return DriverResponse(
                response=DriverResponseType.success,
                data={
                    "requested": int(resolved),
                    "mode_name": resolved.name,
                    "trigger_mode": readback,
                    # In level mode the pulse width *is* the integration time,
                    # so whatever set_integration_time_us applied is inert.
                    "int_time_from_pulse_width": resolved == SRTrigMode.ext_level,
                    "reads_in_flight": pending,
                },
                status=DriverStatus.ok,
            )
        except Exception as exc:
            return self._failed("set_trigger_mode", exc)

    @staticmethod
    def _trigger_write_hint(resolved: "SRTrigMode", pending: int) -> str:
        """Name the likely cause of a rejected trigger-mode write.

        The SDK documents no error for an unsupported mode -- unlike
        ``get_trigger_mode``, the setter carries no device-support note at
        all, and the numeric codes are defined only in the C SDK's
        ``OceanDirectAPIConstants.c``. So a transport-level failure is
        exactly what an unsupported mode is expected to look like, and a
        station has no way to reach that reading from the code alone.
        """
        if pending:
            return (
                f"{pending} triggered read(s) were still inside the vendor "
                "call, so this write shared the device handle with them; "
                "retry once they have returned, or restart the server if a "
                "read is stranded waiting for a trigger that never came"
            )
        if resolved == SRTrigMode.software:
            return (
                "mode 0 is the power-on mode and is supported by every SR "
                "device, so a failure here points at the link or the device "
                "rather than at the trigger configuration"
            )
        return (
            f"mode {int(resolved)} ({resolved.name}) is external triggering, "
            "which an SR4 with the default Option 1 firmware does not "
            "support at all (manual p.20: 'Only mode supported: Software "
            "Trigger Mode (0)'). The 16-pin connector is fitted regardless, "
            "so having the port and cable does not mean the firmware allows "
            "it. Try mode 0: if that succeeds, this unit is Option 1 and "
            "external triggering needs a firmware ordered for it"
        )

    def arm_trigger(self, mode: int) -> DriverResponse:
        """Put the device into ``mode`` and remember that it is armed.

        Args:
            mode: Trigger mode integer from the device manual. See
                :class:`SRTrigMode` for the SR-series values.

        Returns:
            ``DriverResponse`` with the requested and read-back modes.
        """
        resp = self.set_trigger_mode(mode)
        if resp.response == DriverResponseType.success:
            self.armed_trigger_mode = int(mode)
        return resp

    def disarm_trigger(self) -> DriverResponse:
        """Return the device to software-trigger mode (the power-on mode).

        Note this is not a "free-running" mode -- SR mode 0 still triggers per
        request; it is simply the mode in which a plain ``get_spectrum()``
        returns without waiting on an external signal.

        Called from the triggered executor's teardown, from :meth:`stop` and
        from :meth:`disconnect`. Leaving a device armed is not a cosmetic
        problem: every later ``get_spectrum()`` would block waiting for a
        trigger, so the next unrelated action on this server would hang.

        Returns:
            ``DriverResponse``; success when nothing was armed.
        """
        if self.armed_trigger_mode is None:
            return DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        resp = self.set_trigger_mode(int(SRTrigMode.software))
        # Cleared regardless of the outcome: a failed disarm must not leave the
        # driver believing it is still armed and skipping later attempts.
        self.armed_trigger_mode = None
        return resp

    def set_acquisition_delay_us(self, delay_us: int) -> DriverResponse:
        """Set the delay between the Trigger Event and the start of integration.

        ``t_ACQDLY`` in the manual's timing diagrams, documented for all three
        trigger modes (0 to 335,500 us at 1 us resolution on an SR4). This is
        the knob for skipping a flash lamp's rise, or for offsetting several
        instruments driven from one trigger, so a triggered setup without it is
        only usable when the trigger already lands exactly where wanted.

        Bounds come from the device rather than the manual: the vendor exposes
        min/max/increment, and reading them keeps this correct on an SR2 or SR6
        without a per-model table here.

        Args:
            delay_us: Requested delay in microseconds. Clamped to the device's
                range and snapped to its increment.

        Returns:
            ``DriverResponse`` carrying the requested and applied values.
        """
        try:
            self._require_ready("set_acquisition_delay_us")
            self._require("ACQUISITION_DELAY", "set_acquisition_delay_us")
            with self._lock:
                applied = self._clamp_device(
                    self.dev,
                    int(delay_us),
                    "get_acquisition_delay_minimum",
                    "get_acquisition_delay_maximum",
                    "get_acquisition_delay_increment",
                    "acquisition delay",
                )
                self.dev.set_acquisition_delay(applied)
                readback = self._safe_int(self.dev, "get_acquisition_delay")
            return DriverResponse(
                response=DriverResponseType.success,
                data={
                    "requested_us": int(delay_us),
                    "acquisition_delay_us": (
                        readback if readback is not None else applied
                    ),
                },
                status=DriverStatus.ok,
            )
        except Exception as exc:
            return self._failed("set_acquisition_delay_us", exc)

    def acquisition_delay_bounds(self) -> dict:
        """Device-reported acquisition-delay min/max/increment and current value.

        Every entry is ``None`` when the device does not answer, so a caller
        can tell "no delay support" from "delay of zero".
        """
        if self.dev is None:
            return {}
        return {
            "acquisition_delay_us": self._safe_int(self.dev, "get_acquisition_delay"),
            "acquisition_delay_min_us": self._safe_int(
                self.dev, "get_acquisition_delay_minimum"
            ),
            "acquisition_delay_max_us": self._safe_int(
                self.dev, "get_acquisition_delay_maximum"
            ),
            "acquisition_delay_increment_us": self._safe_int(
                self.dev, "get_acquisition_delay_increment"
            ),
        }

    def set_corrections(
        self,
        electric_dark: Optional[bool] = None,
        nonlinearity: Optional[bool] = None,
        saturation_check: Optional[bool] = None,
    ) -> DriverResponse:
        """Toggle the device's on-board correction stages.

        Each toggle is gated on its own ``FeatureID`` and applied
        independently, so a device that supports only one of them still gets
        that one set.

        Args:
            electric_dark: Electric-dark correction; ``None`` leaves it alone.
            nonlinearity: Nonlinearity correction; ``None`` leaves it alone.
            saturation_check: Saturation checking; ``None`` leaves it alone.

        Returns:
            ``DriverResponse`` whose ``data`` maps each requested toggle to
            its applied value or to an error string.
        """
        try:
            self._require_ready("set_corrections")
            applied: dict[str, Any] = {}
            with self._lock:
                if electric_dark is not None:
                    applied["electric_dark"] = self._try_toggle(
                        "PROCESSING",
                        "set_electric_dark_correction_usage",
                        "get_electric_dark_correction_usage",
                        bool(electric_dark),
                    )
                if nonlinearity is not None:
                    applied["nonlinearity"] = self._try_toggle(
                        "NONLINEARITY_CAL",
                        "set_nonlinearity_correction_usage",
                        "get_nonlinearity_correction_usage",
                        bool(nonlinearity),
                    )
                if saturation_check is not None:
                    applied["saturation_check"] = self._try_toggle(
                        None,
                        "set_saturation_check",
                        "get_saturation_check",
                        bool(saturation_check),
                    )
            failures = [k for k, v in applied.items() if isinstance(v, str)]
            return DriverResponse(
                response=(
                    DriverResponseType.failed
                    if failures
                    else DriverResponseType.success
                ),
                message=f"unsupported: {', '.join(failures)}" if failures else "",
                data=applied,
                status=DriverStatus.error if failures else DriverStatus.ok,
            )
        except Exception as exc:
            return self._failed("set_corrections", exc)

    def _try_toggle(
        self,
        feature_name: Optional[str],
        setter: str,
        getter: str,
        value: bool,
    ) -> Any:
        """Apply one boolean device toggle, returning the read-back or an error."""
        try:
            if feature_name is not None:
                self._require(feature_name, setter)
            getattr(self.dev, setter)(value)
            return bool(getattr(self.dev, getter)())
        except Exception as exc:
            detail = self._err_detail(exc)
            LOGGER.warning(f"{setter}({value}) failed: {detail}")
            return detail

    # ------------------------------------------------------------------
    # Single-shot acquisition
    # ------------------------------------------------------------------
    def acquire_spectrum(
        self, dark_corrected: bool = False, serialize: bool = True
    ) -> tuple[list[float], float]:
        """Read one spectrum from the device.

        Args:
            dark_corrected: When true, use the device's stored-dark path
                (``get_dark_corrected_spectrum2``) instead of the raw read.
            serialize: Hold the driver lock across the read. Pass ``False``
                **only** on an externally-triggered read -- see below.

        Returns:
            ``(spectrum, epoch_s)`` where ``spectrum`` is a list of floats.
        """
        self._require_ready("acquire_spectrum")
        if not serialize:
            # An externally-triggered read blocks inside the vendor call until
            # a trigger arrives, which may be minutes or never. Holding the
            # lock across it would serialize the entire driver behind that
            # wait -- including `disconnect()`, so server shutdown would hang
            # until someone fired a trigger. The server sets
            # `allow_concurrent_actions = False`, so no second action can race
            # this read; what must stay reachable is the private endpoints and
            # teardown, and those are exactly what the lock would block.
            #
            # That protection ends when the action does, and this path can
            # outlive its action: a read that timed out leaves the worker
            # thread in the vendor call until a trigger arrives or the device
            # closes. The counter is how a later call can say so, since the
            # lock cannot express it.
            with self._flight_lock:
                self._reads_in_flight += 1
            try:
                return self._read_spectrum(dark_corrected)
            finally:
                with self._flight_lock:
                    self._reads_in_flight -= 1
        with self._lock:
            return self._read_spectrum(dark_corrected)

    @property
    def reads_in_flight(self) -> int:
        """Unserialized triggered reads currently inside the vendor call."""
        with self._flight_lock:
            return self._reads_in_flight

    def _read_spectrum(self, dark_corrected: bool) -> tuple[list[float], float]:
        """The bare vendor read, with no locking of its own."""
        epoch_s = time.time()
        if dark_corrected:
            spectrum = self.dev.get_dark_corrected_spectrum2()
        else:
            spectrum = self.dev.get_spectrum()
        return ([float(x) for x in spectrum], epoch_s)

    def store_dark_spectrum(self) -> DriverResponse:
        """Acquire a spectrum and store it on the device as the dark reference.

        Returns:
            ``DriverResponse`` with the stored spectrum's length and its
            mean/min/max, which is enough to tell a shuttered dark from a
            forgotten-to-block-the-light one without shipping 2048 values.
        """
        try:
            self._require_ready("store_dark_spectrum")
            spectrum, epoch_s = self.acquire_spectrum(dark_corrected=False)
            with self._lock:
                self.dev.set_stored_dark_spectrum(spectrum)
            return DriverResponse(
                response=DriverResponseType.success,
                data={
                    "epoch_s": epoch_s,
                    "n_pixels": len(spectrum),
                    "dark_mean": sum(spectrum) / len(spectrum) if spectrum else None,
                    "dark_min": min(spectrum) if spectrum else None,
                    "dark_max": max(spectrum) if spectrum else None,
                },
                status=DriverStatus.ok,
            )
        except Exception as exc:
            return self._failed("store_dark_spectrum", exc)

    def peak_intensity(
        self,
        spectrum: list[float],
        peak_lower_wl: Optional[float] = None,
        peak_upper_wl: Optional[float] = None,
    ) -> Optional[float]:
        """Return the maximum intensity within a wavelength window.

        Uses the vendor's ``get_indices_at_wavelength_range`` where available
        instead of the SM303's hand-rolled index scan, falling back to a local
        scan of ``pxwl`` when the device does not implement it.

        Args:
            spectrum: Intensities aligned with ``pxwl``.
            peak_lower_wl: Lower bound in nm; ``None`` means the first pixel.
            peak_upper_wl: Upper bound in nm; ``None`` means the last pixel.

        Returns:
            The peak intensity, or ``None`` when the window selects no pixel.
        """
        if not spectrum:
            return None
        if peak_lower_wl is None and peak_upper_wl is None:
            return max(spectrum)
        lo = peak_lower_wl if peak_lower_wl is not None else min(self.pxwl)
        hi = peak_upper_wl if peak_upper_wl is not None else max(self.pxwl)
        idxs: list[int] = []
        try:
            idxs, _ = self.dev.get_indices_at_wavelength_range(
                float(lo), float(hi), len(spectrum)
            )
        except Exception as exc:
            LOGGER.debug(
                f"get_indices_at_wavelength_range unavailable, scanning locally: "
                f"{self._err_detail(exc)}"
            )
            idxs = [i for i, w in enumerate(self.pxwl) if lo <= w <= hi]
        window = [spectrum[i] for i in idxs if 0 <= i < len(spectrum)]
        if not window:
            LOGGER.warning(
                f"peak window [{lo}, {hi}] nm selected no pixels of "
                f"{len(spectrum)}; returning None"
            )
            return None
        return max(window)

    def is_saturated(self) -> Optional[bool]:
        """Whether the device reports the last spectrum as saturated."""
        try:
            self._require_ready("is_saturated")
            return bool(self.dev.get_saturated_spectrum())
        except Exception as exc:
            LOGGER.debug(f"saturation flag unavailable: {self._err_detail(exc)}")
            return None

    # ------------------------------------------------------------------
    # Long-format rows
    # ------------------------------------------------------------------
    def build_rows(
        self,
        spectra: list[list[float]],
        epochs: list[float],
        dev_timestamps: Optional[list[Optional[int]]] = None,
        start_idx: Optional[int] = None,
    ) -> dict:
        """Pack spectra into one long-format data payload.

        The columns are equal-length parallel arrays. Both HLO readers
        (``read_hlo_stream`` and ``read_hlo_data_chunks``) concatenate
        list-valued columns across lines, so this encoding reads back as
        one row per pixel -- exactly the long format -- while writing one
        line per spectrum instead of one line per pixel. ``spec_idx`` is what
        survives the flattening and carries the per-spectrum framing.

        Args:
            spectra: One list of intensities per spectrum.
            epochs: Host epoch seconds, one per spectrum.
            dev_timestamps: Device timestamps in ns, one per spectrum; ``None``
                (or a ``None`` entry) is emitted as JSON null.
            start_idx: First ``spec_idx`` to use; defaults to the driver's
                running counter, which it then advances.

        Returns:
            A dict keyed by :data:`LONG_FORMAT_KEYS`, minus ``dev_ts_ns`` when
            no spectrum in the batch carried a device timestamp. Empty when
            there is nothing to emit.
        """
        if not spectra:
            return {}
        idx = self.spec_idx if start_idx is None else start_idx
        n_wl = len(self.pxwl)
        cols: dict[str, list] = {k: [] for k in LONG_FORMAT_KEYS}
        for i, spectrum in enumerate(spectra):
            # Trim to the shorter of spectrum and wavelength axis so a
            # device whose two lengths disagree cannot emit ragged columns.
            n = min(len(spectrum), n_wl)
            if n == 0:
                continue
            epoch = epochs[i] if i < len(epochs) else time.time()
            dev_ts = None
            if dev_timestamps is not None and i < len(dev_timestamps):
                dev_ts = dev_timestamps[i]
            cols["epoch_s"].extend([float(epoch)] * n)
            cols["spec_idx"].extend([idx] * n)
            cols["dev_ts_ns"].extend([dev_ts] * n)
            cols["wl"].extend(self.pxwl[:n])
            cols["i"].extend(float(x) for x in spectrum[:n])
            idx += 1
        if start_idx is None:
            self.spec_idx = idx
        if not cols["spec_idx"]:
            return {}
        if all(value is None for value in cols["dev_ts_ns"]):
            # Nothing in this payload has a device timestamp, which is the
            # normal case for the single-shot path and the case for any device
            # whose metadata feature is absent. Emitting the column anyway
            # writes one `null` per pixel -- ~17.8 KB per spectrum at 3648
            # pixels -- and tells a reader nothing it could not infer from the
            # column's absence. A partially-populated column is kept whole, so
            # positional alignment with the others is never disturbed.
            del cols["dev_ts_ns"]
        return cols

    def reset_spec_idx(self) -> None:
        """Restart the per-action spectrum counter."""
        self.spec_idx = 0

    # ------------------------------------------------------------------
    # Buffered / back-to-back capture
    # ------------------------------------------------------------------
    def start_buffered(
        self,
        n_scans: int = 1,
        capacity: Optional[int] = None,
    ) -> DriverResponse:
        """Arm the device's hardware buffer for a back-to-back run.

        Args:
            n_scans: Back-to-back scans the device should acquire.
            capacity: Data-buffer capacity; ``None`` leaves the device's
                current setting alone.

        Returns:
            ``DriverResponse`` describing the armed buffer.
        """
        try:
            self._require_ready("start_buffered")
            # A device without these cannot buffer at all -- an OCEANSR4, for
            # one. The message names the alternative rather than leaving the
            # caller to discover that a bufferless device has another path.
            try:
                self._require("DATA_BUFFER", "start_buffered")
                self._require("BACK_TO_BACK", "start_buffered")
            except RuntimeError as exc:
                raise RuntimeError(
                    f"{exc}. This device cannot buffer; use acquire_spec_extrig "
                    "for triggered or long continuous acquisition instead."
                ) from exc
            with self._lock:
                adv = self.dev.Advanced
                adv.set_data_buffer_enable(True)
                if capacity is not None:
                    lo = adv.get_data_buffer_capacity_minimum()
                    hi = adv.get_data_buffer_capacity_maximum()
                    clamped = int(max(lo, min(hi, int(capacity))))
                    if clamped != int(capacity):
                        LOGGER.info(
                            f"buffer capacity {capacity} clamped to {clamped} "
                            f"(device range {lo}-{hi})"
                        )
                    adv.set_data_buffer_capacity(clamped)
                adv.clear_data_buffer()
                adv.set_number_of_backtoback_scans(int(n_scans))
                adv.acquire_spectra_to_buffer()
                data = {
                    "buffer_enabled": bool(adv.get_data_buffer_enable()),
                    "backtoback_scans": int(adv.get_number_of_backtoback_scans()),
                    "buffer_capacity": int(adv.get_data_buffer_capacity()),
                }
            self.buffering = True
            return DriverResponse(
                response=DriverResponseType.success,
                data=data,
                status=DriverStatus.busy,
            )
        except Exception as exc:
            self.buffering = False
            return self._failed("start_buffered", exc)

    def drain_buffered(
        self, buffer_size: int = MAX_METADATA_BUFFER_SIZE
    ) -> tuple[list[list[float]], list[Optional[int]]]:
        """Drain up to ``buffer_size`` spectra from the device buffer.

        The vendor caps ``get_spectrum_with_metadata``'s ``buffer_size`` at 15
        and returns how many spectra it actually appended, which can be zero.
        The caller loops; this reads once.

        Args:
            buffer_size: Spectra to request, capped at
                :data:`MAX_METADATA_BUFFER_SIZE`.

        Returns:
            ``(spectra, dev_timestamps_ns)`` with one entry per spectrum
            actually read.
        """
        self._require_ready("drain_buffered")
        size = int(max(1, min(MAX_METADATA_BUFFER_SIZE, buffer_size)))
        spectra: list[list[float]] = []
        timestamps: list[int] = []
        with self._lock:
            count = self.dev.Advanced.get_spectrum_with_metadata(
                spectra, timestamps, size
            )
        # Trust the returned count, not the list lengths: the vendor appends
        # into caller-owned lists and a partial read leaves them longer than
        # `count` on some paths.
        out_spectra = [[float(x) for x in s] for s in spectra[:count]]
        out_ts: list[Optional[int]] = [int(t) for t in timestamps[:count]]
        return (out_spectra, out_ts)

    def buffered_count(self) -> Optional[int]:
        """Spectra currently sitting in the device buffer, if reportable."""
        try:
            self._require_ready("buffered_count")
            with self._lock:
                return int(self.dev.Advanced.get_buffered_spectrum_count())
        except Exception as exc:
            LOGGER.debug(f"buffered count unavailable: {self._err_detail(exc)}")
            return None

    def stop_buffered(self) -> DriverResponse:
        """Abort the buffered run, clear the buffer and disable buffering."""
        try:
            self._require_ready("stop_buffered")
            errors = []
            with self._lock:
                adv = self.dev.Advanced
                # Independently guarded: aborting must still clear and
                # disable even if the abort itself is unsupported.
                for label, fn in (
                    ("abort_acquisition", adv.abort_acquisition),
                    ("clear_data_buffer", adv.clear_data_buffer),
                    ("disable_buffer", lambda: adv.set_data_buffer_enable(False)),
                ):
                    try:
                        fn()
                    except Exception as exc:
                        detail = self._err_detail(exc)
                        LOGGER.warning(f"stop_buffered/{label}: {detail}")
                        errors.append(f"{label}: {detail}")
            self.buffering = False
            return DriverResponse(
                response=(
                    DriverResponseType.failed if errors else DriverResponseType.success
                ),
                message="; ".join(errors),
                status=DriverStatus.error if errors else DriverStatus.ok,
            )
        except Exception as exc:
            self.buffering = False
            return self._failed("stop_buffered", exc)

    def _abort_acquisition(self) -> None:
        """Abort acquisition if the device supports the control feature."""
        self._require_ready("abort_acquisition")
        self._require("SPECTRUM_ACQUISITION_CONTROL", "abort_acquisition")
        with self._lock:
            self.dev.Advanced.abort_acquisition()
        self.buffering = False

    # ------------------------------------------------------------------
    # Device control (TEC / shutter / lamp / strobe)
    # ------------------------------------------------------------------
    def set_tec(
        self,
        enable: Optional[bool] = None,
        setpoint_degrees_c: Optional[float] = None,
    ) -> DriverResponse:
        """Enable/disable the TEC and set its setpoint.

        Args:
            enable: TEC enable state; ``None`` leaves it unchanged.
            setpoint_degrees_c: Target temperature in Celsius; ``None`` leaves
                it unchanged.

        Returns:
            ``DriverResponse`` carrying the TEC status read back afterwards.
        """
        try:
            self._require_ready("set_tec")
            self._require("THERMOELECTRIC", "set_tec")
            with self._lock:
                adv = self.dev.Advanced
                if setpoint_degrees_c is not None:
                    adv.set_temperature_setpoint_degrees_C(float(setpoint_degrees_c))
                if enable is not None:
                    adv.set_tec_enable(bool(enable))
            return self.get_tec_status()
        except Exception as exc:
            return self._failed("set_tec", exc)

    def get_tec_status(self) -> DriverResponse:
        """Report TEC enable state, setpoint, temperature and stability."""
        try:
            self._require_ready("get_tec_status")
            self._require("THERMOELECTRIC", "get_tec_status")
            data: dict[str, Any] = {}
            with self._lock:
                adv = self.dev.Advanced
                for key, getter in (
                    ("tec_enabled", "get_tec_enable"),
                    ("setpoint_degrees_c", "get_temperature_setpoint_degrees_C"),
                    ("temperature_degrees_c", "get_tec_temperature_degrees_C"),
                    ("tec_stable", "get_tec_stable"),
                ):
                    try:
                        data[key] = getattr(adv, getter)()
                    except Exception as exc:
                        LOGGER.debug(f"{getter} unavailable: {self._err_detail(exc)}")
                        data[key] = None
            return DriverResponse(
                response=DriverResponseType.success,
                data=data,
                status=DriverStatus.ok,
            )
        except Exception as exc:
            return self._failed("get_tec_status", exc)

    def set_shutter_open(self, open_shutter: bool) -> DriverResponse:
        """Open or close the device shutter.

        Args:
            open_shutter: ``True`` to open, ``False`` to close.

        Returns:
            ``DriverResponse`` with the shutter state read back.
        """
        try:
            self._require_ready("set_shutter_open")
            self._require("SHUTTER", "set_shutter_open")
            with self._lock:
                self.dev.Advanced.set_shutter_open(bool(open_shutter))
                try:
                    state = bool(self.dev.Advanced.get_shutter_state())
                except Exception as exc:
                    LOGGER.debug(
                        f"shutter readback unavailable: {self._err_detail(exc)}"
                    )
                    state = None
            return DriverResponse(
                response=DriverResponseType.success,
                data={"requested": bool(open_shutter), "shutter_open": state},
                status=DriverStatus.ok,
            )
        except Exception as exc:
            return self._failed("set_shutter_open", exc)

    def _set_lamp(self, enable: bool) -> None:
        self._require_ready("set_lamp_enable")
        self._require("STROBE_LAMP", "set_lamp_enable")
        with self._lock:
            self.dev.Advanced.set_enable_lamp(bool(enable))

    def set_lamp_enable(self, enable: bool) -> DriverResponse:
        """Enable or disable the device's lamp output.

        Args:
            enable: Lamp enable state.

        Returns:
            ``DriverResponse`` with the state read back where available.
        """
        try:
            self._set_lamp(enable)
            with self._lock:
                try:
                    state = bool(self.dev.Advanced.get_enable_lamp())
                except Exception:
                    state = None
            return DriverResponse(
                response=DriverResponseType.success,
                data={"requested": bool(enable), "lamp_enabled": state},
                status=DriverStatus.ok,
            )
        except Exception as exc:
            return self._failed("set_lamp_enable", exc)

    def set_light_source_enable(self, index: int, enable: bool) -> DriverResponse:
        """Enable or disable one of the device's light sources.

        Args:
            index: Light-source index.
            enable: Desired enable state.

        Returns:
            ``DriverResponse`` with the source count and the state read back.
        """
        try:
            self._require_ready("set_light_source_enable")
            self._require("LIGHT_SOURCE", "set_light_source_enable")
            with self._lock:
                adv = self.dev.Advanced
                count = int(adv.get_light_source_count())
                if not 0 <= int(index) < count:
                    raise RuntimeError(
                        f"light source index {index} out of range (device has {count})"
                    )
                if not bool(adv.has_light_source_enable(int(index))):
                    raise RuntimeError(
                        f"light source {index} has no software enable on this device"
                    )
                adv.enable_light_source(int(index), bool(enable))
                state = bool(adv.is_light_source_enabled(int(index)))
            return DriverResponse(
                response=DriverResponseType.success,
                data={
                    "index": int(index),
                    "light_source_count": count,
                    "enabled": state,
                },
                status=DriverStatus.ok,
            )
        except Exception as exc:
            return self._failed("set_light_source_enable", exc)

    def _set_single_strobe_enable(self, enable: bool) -> None:
        self._require_ready("set_single_strobe")
        self._require("SINGLE_STROBE", "set_single_strobe")
        with self._lock:
            self.dev.Advanced.set_single_strobe_enable(bool(enable))

    def set_single_strobe(
        self,
        enable: Optional[bool] = None,
        delay_us: Optional[int] = None,
        width_us: Optional[int] = None,
    ) -> DriverResponse:
        """Configure the single strobe, clamping delay and width to the device.

        Args:
            enable: Strobe enable state; ``None`` leaves it unchanged.
            delay_us: Strobe delay in microseconds; ``None`` leaves it alone.
            width_us: Strobe width in microseconds; ``None`` leaves it alone.

        Returns:
            ``DriverResponse`` carrying the values read back from the device.
        """
        try:
            self._require_ready("set_single_strobe")
            self._require("SINGLE_STROBE", "set_single_strobe")
            with self._lock:
                adv = self.dev.Advanced
                if delay_us is not None:
                    adv.set_single_strobe_delay(
                        self._clamp_device(
                            adv,
                            int(delay_us),
                            "get_single_strobe_delay_minimum",
                            "get_single_strobe_delay_maximum",
                            "get_single_strobe_delay_increment",
                            "single strobe delay",
                        )
                    )
                if width_us is not None:
                    adv.set_single_strobe_width(
                        self._clamp_device(
                            adv,
                            int(width_us),
                            "get_single_strobe_width_minimum",
                            "get_single_strobe_width_maximum",
                            "get_single_strobe_width_increment",
                            "single strobe width",
                        )
                    )
                if enable is not None:
                    adv.set_single_strobe_enable(bool(enable))
                data = self._read_back(
                    adv,
                    {
                        "enabled": "get_single_strobe_enable",
                        "delay_us": "get_single_strobe_delay",
                        "width_us": "get_single_strobe_width",
                    },
                )
            return DriverResponse(
                response=DriverResponseType.success,
                data=data,
                status=DriverStatus.ok,
            )
        except Exception as exc:
            return self._failed("set_single_strobe", exc)

    @staticmethod
    def continuous_strobe_fires(
        period_us: Optional[int], int_time_us: Optional[int]
    ) -> Optional[bool]:
        """Whether a continuous strobe of ``period_us`` will actually fire.

        The continuous strobe is only active while its period is **shorter
        than** the integration time (*Ocean SR Series* UM-SR-Series_1025,
        Tables 3/6/9, note on ``t_CSPER``). A longer period is accepted both
        by ``set_continuous_strobe_period`` and by the device's own bounds
        without complaint -- it simply never fires, which at a station reads
        as dead hardware rather than as a misconfiguration.

        Args:
            period_us: Configured strobe period in microseconds.
            int_time_us: Current integration time in microseconds.

        Returns:
            ``True`` if the strobe fires, ``False`` if the period silences it,
            and ``None`` when either value is unknown -- a device that will
            not report its period cannot be judged, and guessing either way
            would produce a warning nobody can act on.
        """
        try:
            return int(period_us) < int(int_time_us)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None

    def _warn_if_strobe_silenced(self, int_time_us: int) -> None:
        """Warn when a new integration time silences a configured strobe.

        Judged against the cached strobe configuration, never the device:
        this runs on the acquisition path, where reading the strobe back would
        cost two vendor round trips per acquisition on every device, including
        the ones with no strobe at all.
        """
        if not self.continuous_strobe_enabled:
            return
        fires = self.continuous_strobe_fires(
            self.continuous_strobe_period_us, int_time_us
        )
        if fires is False:
            LOGGER.warning(
                f"integration time {int_time_us} us is not longer than the "
                f"enabled continuous strobe period "
                f"{self.continuous_strobe_period_us} us, so the strobe will "
                "stop firing; lower the period or raise the integration time"
            )

    def _set_continuous_strobe_enable(self, enable: bool) -> None:
        self._require_ready("set_continuous_strobe")
        self._require("CONTINUOUS_STROBE", "set_continuous_strobe")
        with self._lock:
            self.dev.Advanced.set_continuous_strobe_enable(bool(enable))
            # Kept truthful here too, not only in set_continuous_strobe: this
            # is the leg estop and teardown use to switch the strobe off.
            self.continuous_strobe_enabled = bool(enable)

    def set_continuous_strobe(
        self,
        enable: Optional[bool] = None,
        period_us: Optional[int] = None,
        width_us: Optional[int] = None,
    ) -> DriverResponse:
        """Configure the continuous strobe, clamping period to the device.

        Args:
            enable: Strobe enable state; ``None`` leaves it unchanged.
            period_us: Strobe period in microseconds; ``None`` leaves it alone.
            width_us: Strobe width in microseconds; ``None`` leaves it alone.
                Width has no published min/max, so it is written as given.

        Returns:
            ``DriverResponse`` carrying the values read back from the device.
        """
        try:
            self._require_ready("set_continuous_strobe")
            self._require("CONTINUOUS_STROBE", "set_continuous_strobe")
            with self._lock:
                adv = self.dev.Advanced
                if period_us is not None:
                    adv.set_continuous_strobe_period(
                        self._clamp_device(
                            adv,
                            int(period_us),
                            "get_continuous_strobe_period_minimum",
                            "get_continuous_strobe_period_maximum",
                            "get_continuous_strobe_period_increment",
                            "continuous strobe period",
                        )
                    )
                if width_us is not None:
                    adv.set_continuous_strobe_width(int(width_us))
                if enable is not None:
                    adv.set_continuous_strobe_enable(bool(enable))
                data = self._read_back(
                    adv,
                    {
                        "enabled": "get_continuous_strobe_enable",
                        "period_us": "get_continuous_strobe_period",
                        "width_us": "get_continuous_strobe_width",
                    },
                )
                # The period is honoured only while it is shorter than the
                # integration time, and neither the SDK nor the device says
                # so. Report both numbers and which way they fell, rather
                # than refusing: configuring the strobe before lowering the
                # integration time is a legitimate order, and the device
                # itself accepts the write.
                int_time_us = self._safe_int(self.dev, "get_integration_time")
                data["int_time_us"] = int_time_us
                data["period_us"] = self._opt_int(data.get("period_us"))
                data["period_fires"] = self.continuous_strobe_fires(
                    data["period_us"], int_time_us
                )
                self.continuous_strobe_period_us = data["period_us"]
                self.continuous_strobe_enabled = (
                    None if data.get("enabled") is None else bool(data["enabled"])
                )
            if data["period_fires"] is False and self.continuous_strobe_enabled:
                LOGGER.warning(
                    f"continuous strobe period {data['period_us']} us is not "
                    f"shorter than the integration time {int_time_us} us, so "
                    "the strobe will not fire; lower the period below "
                    f"{int_time_us} us or raise the integration time"
                )
            return DriverResponse(
                response=DriverResponseType.success,
                data=data,
                status=DriverStatus.ok,
            )
        except Exception as exc:
            return self._failed("set_continuous_strobe", exc)

    def _clamp_device(
        self,
        adv,
        value: int,
        min_getter: str,
        max_getter: str,
        inc_getter: str,
        label: str,
    ) -> int:
        """Clamp ``value`` to a device-reported range, snapping to increment.

        A device that does not publish one of the three bounds is not an
        error: the missing bound is simply not enforced.
        """
        lo = self._safe_int(adv, min_getter)
        hi = self._safe_int(adv, max_getter)
        step = self._safe_int(adv, inc_getter)
        out = int(value)
        if lo is not None:
            out = max(lo, out)
        if hi is not None:
            out = min(hi, out)
        if step and step > 1:
            base = lo if lo is not None else 0
            out = base + ((out - base) // step) * step
            if lo is not None:
                out = max(lo, out)
        if out != int(value):
            LOGGER.info(
                f"{label} {value} adjusted to {out} (device range {lo}-{hi}, "
                f"increment {step})"
            )
        return out

    @staticmethod
    def _safe_int(obj, getter: str) -> Optional[int]:
        """Call ``getter`` and coerce to int, or return ``None`` if it fails."""
        try:
            return int(getattr(obj, getter)())
        except Exception:
            return None

    @staticmethod
    def _safe_bool(obj, getter: str) -> Optional[bool]:
        """Call ``getter`` and coerce to bool, or return ``None`` if it fails."""
        try:
            return bool(getattr(obj, getter)())
        except Exception:
            return None

    @staticmethod
    def _opt_int(value) -> Optional[int]:
        """Coerce ``value`` to int, or ``None`` when it is missing or not numeric."""
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _read_back(self, obj, getters: dict[str, str]) -> dict:
        """Read several device values, mapping each failure to ``None``."""
        out: dict[str, Any] = {}
        for key, getter in getters.items():
            try:
                out[key] = getattr(obj, getter)()
            except Exception as exc:
                LOGGER.debug(f"{getter} unavailable: {self._err_detail(exc)}")
                out[key] = None
        return out
