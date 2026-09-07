"""HelaoDriver over EC-Lab's OLE COM interface.

Composes the package's other modules -- ``olecom_client`` for the calls,
``mps_template`` and ``mps_assemble`` for the settings file, ``technique`` for
the mappings, ``status`` for the channel state, ``mpr_cursor`` for the data --
and is the only module that knows the *order* the calls go in. Most of the
correctness lives in that order.

Config keys, all optional except ``address``:

===================  ====================================================
``address``          Instrument IP. Passed to ``ConnectDeviceByIP``, which
                     adds it to EC-Lab's device list if absent.
``num_channels``     Channels this server drives. Default 12, as eclib.
``simulate``         Use the fake COM server (``sim.py``).
``progid``           EC-Lab's OLE ProgID, if not the default.
``templates_dir``    Where the ``.mps`` templates live. Defaults to the
                     package's own ``templates/``.
``scratch_dir``      Where patched settings and in-progress MPR files go.
``protocol_dir``     Where ``run_protocol`` resolves its ``mps_path``.
``com_timeout_s``    Per-call ceiling. Default 30.
===================  ====================================================

Three things about this driver are unlike its eclib sibling and are the ones
to keep in mind when editing it:

* **A channel finishes only at state ``Stop``, and then only after one more
  drain.** ``Stop_rec1``/``Stop_rec2`` mean the last points are being written.
  Reporting ``done`` there truncates the tail of every record, silently.
* **Every COM call is bounded.** A modal EC-Lab dialog blocks the call that
  raised it forever, so ``EnableMessagesWindows(0)`` runs first and calls
  still go through a thread executor under a timeout. As with
  ``OceanDirectExtrigExec``, that frees the caller and leaves the worker
  thread blocked -- the honest trade, since the alternative is a wedged
  server.
* **Artifacts move at cleanup, not during the run.** EC-Lab writes the MPR
  continuously and ``HelaoYml.misc_files`` globs live directories, so a file
  written straight into the action directory would be uploaded torn.
"""

import concurrent.futures
import shutil
import time
import uuid
from pathlib import Path
from typing import Optional

from helao.core.drivers.helao_driver import (
    DriverResponse,
    DriverResponseType,
    DriverStatus,
    HelaoDriver,
)
from helao.helpers import helao_logging as logging

from . import mps_assemble, mps_template
from .mpr_cursor import MprCursor
from .olecom_client import DEFAULT_PROGID, OleComClient, OleComError
from .status import ChannelStatus, SafetyLimit, decode_status
from .technique import (
    OleTechnique,
    erange_rows,
    format_value,
    protocol_technique,
    scale_to_unit,
)

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

__all__ = ["MIN_ECLAB_VERSION", "BiologicOleDriver"]

#: Manual section 8.1. Below this the OLE COM interface does not exist.
MIN_ECLAB_VERSION = (11, 11)

#: Default per-call ceiling. Generous, because LoadSettings on a cold EC-Lab
#: is slow; the point is that nothing blocks forever, not that it is tight.
DEFAULT_COM_TIMEOUT_S = 30.0


def _version_tuple(text: str) -> tuple[int, ...]:
    """``"11.72"`` -> ``(11, 72)``. Non-numeric parts stop the parse."""
    parts: list[int] = []
    for chunk in text.strip().split("."):
        if not chunk.isdigit():
            break
        parts.append(int(chunk))
    return tuple(parts)


class BiologicOleDriver(HelaoDriver):
    """Drive a BioLogic potentiostat by piloting EC-Lab over OLE COM."""

    def __init__(self, config: dict = {}):
        """Store configuration. Opens nothing -- ``connect()`` does that.

        ``BaseAPI`` constructs drivers before the server is serving, and the
        eclib sibling was changed in P3a-2 to stop opening the instrument
        here. This one never did.
        """
        super().__init__(config=config)
        self.ready = False
        self.address = config.get("address", "192.168.200.240")
        self.num_channels = int(config.get("num_channels", 12))
        self.simulate = bool(config.get("simulate", False))
        self.progid = config.get("progid", DEFAULT_PROGID)
        self.com_timeout_s = float(config.get("com_timeout_s", DEFAULT_COM_TIMEOUT_S))
        self.device_number: Optional[int] = None
        self.device_name = "unknown"
        self.client: Optional[OleComClient] = None
        self.channels: dict[int, Optional[OleTechnique]] = {
            i: None for i in range(self.num_channels)
        }
        self.channel_params: dict[int, dict] = {i: {} for i in range(self.num_channels)}
        self.cursors: dict[int, Optional[MprCursor]] = {
            i: None for i in range(self.num_channels)
        }
        self.scratch: dict[int, Optional[Path]] = {
            i: None for i in range(self.num_channels)
        }
        self.output_dirs: dict[int, Optional[Path]] = {
            i: None for i in range(self.num_channels)
        }
        self.stopping = False
        self._pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="olecom"
        )

    # -- paths -----------------------------------------------------------

    @property
    def templates_dir(self) -> Path:
        """Where the ``.mps`` templates live."""
        configured = self.config.get("templates_dir")
        if configured:
            return Path(configured)
        return Path(__file__).parent / "templates"

    @property
    def scratch_dir(self) -> Path:
        """Where patched settings and in-progress MPR files are written."""
        return Path(self.config.get("scratch_dir", Path.cwd() / "STATES" / "olecom"))

    @property
    def protocol_dir(self) -> Path:
        """Where ``run_protocol`` resolves a station-authored ``.mps``."""
        return Path(self.config.get("protocol_dir", self.templates_dir))

    # -- COM plumbing ----------------------------------------------------

    def _bounded(self, call, *args):
        """Run a COM call with a ceiling.

        The COM layer is synchronous and a modal dialog blocks it forever.
        The timeout frees this caller; the worker thread stays blocked, which
        is why ``EnableMessagesWindows(0)`` is not optional.
        """
        future = self._pool.submit(call, *args)
        return future.result(timeout=self.com_timeout_s)

    def _make_client(self) -> OleComClient:
        if self.simulate:
            from dataclasses import replace

            from . import sim as sim_module

            # WARNING, not INFO: a station left on `simulate: true` produces
            # plausible data from no instrument at all.
            LOGGER.warning(
                "BiologicOleDriver is SIMULATED (`simulate: true` on this "
                "server's params). No instrument is being driven."
            )
            # The fake device must report the channel count this server is
            # configured for. Otherwise get_status(), which iterates
            # range(num_channels), asks about a channel the sim does not have
            # and every teardown logs a traceback. Derived from the module
            # default rather than replacing it, so a test that set run length
            # or technique kind keeps them.
            sim_config = replace(
                sim_module.current_config(), n_channels=self.num_channels
            )
            return OleComClient(
                progid=self.progid, factory=sim_module.make_factory(sim_config)
            )
        return OleComClient(progid=self.progid)

    def _read_version(self) -> str:
        return self.client.get_software_version()

    # -- lifecycle -------------------------------------------------------

    def connect(self) -> DriverResponse:
        """Attach to EC-Lab and to the configured instrument.

        Order matters: message boxes are suppressed before anything that
        could raise one, and the version floor is checked before any call
        that a pre-11.11 EC-Lab would not have.
        """
        try:
            self.client = self._make_client()
            self._bounded(self.client.enable_messages_windows, False)
            version = self._bounded(self._read_version)
            if _version_tuple(version) < MIN_ECLAB_VERSION:
                floor = ".".join(str(p) for p in MIN_ECLAB_VERSION)
                return DriverResponse(
                    response=DriverResponseType.failed,
                    message=(
                        f"EC-Lab {version} is below the {floor} minimum for the "
                        "OLE COM interface (manual section 8.1)"
                    ),
                    status=DriverStatus.error,
                )
            # The manual states ConnectDevice auto-answers "Yes" to EC-Lab's
            # firmware-upgrade prompt and offers no way to suppress it. Warn
            # before the call, because after it the flash has already begun.
            LOGGER.warning(
                "connecting to %s: EC-Lab auto-accepts a firmware upgrade "
                "prompt in OLE COM mode and the API cannot suppress it",
                self.address,
            )
            self.device_number = self._bounded(
                self.client.connect_device_by_ip, str(self.address)
            )
            self.device_name = self._bounded(
                self.client.get_device_type, self.device_number
            )
            present = self._bounded(
                self.client.get_device_channel_list, self.device_number
            )
            LOGGER.info(
                "connected to %s (EC-Lab %s) at %s as device %s; channels present: %s",
                self.device_name,
                version,
                self.address,
                self.device_number,
                [i for i, flag in enumerate(present) if flag],
            )
            self.ready = True
            return DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception as exc:
            LOGGER.error("connect failed", exc_info=True)
            return DriverResponse(
                response=DriverResponseType.failed,
                message=str(exc),
                status=DriverStatus.error,
            )

    def _status_of(self, channel: int) -> ChannelStatus:
        return decode_status(
            self._bounded(self.client.measure_status, self.device_number, channel)
        )

    def get_status(self, channel: Optional[int] = None) -> DriverResponse:
        """Channel state, for one channel or all of them.

        ``data`` maps channel index to the raw status value, matching the
        eclib driver's shape so both backends report identically.
        """
        try:
            if not self.ready:
                return DriverResponse(
                    response=DriverResponseType.success,
                    status=DriverStatus.uninitialized,
                    data={},
                )
            if channel is None:
                states = {
                    i: self._status_of(i).state_raw for i in range(self.num_channels)
                }
                status = (
                    DriverStatus.busy
                    if any(v > 0 for v in states.values())
                    else DriverStatus.ok
                )
                return DriverResponse(
                    response=DriverResponseType.success, status=status, data=states
                )
            if channel not in self.channels:
                return DriverResponse(
                    response=DriverResponseType.success,
                    status=DriverStatus.uninitialized,
                    data={},
                )
            reading = self._status_of(channel)
            return DriverResponse(
                response=DriverResponseType.success,
                status=DriverStatus.busy if reading.is_busy else DriverStatus.ok,
                data={channel: reading.state_raw},
            )
        except Exception:
            LOGGER.error("get_status failed", exc_info=True)
            return DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )

    # -- setup -----------------------------------------------------------

    def _patch(self, technique: OleTechnique, action_params: dict):
        """The template with this action's parameters substituted in."""
        doc = mps_template.load(self.templates_dir / technique.template)
        for key, param in technique.parameter_map.items():
            if key not in action_params:
                continue
            value = action_params[key]
            # A list parameter (CAOCV's steps) fills one sequence column each.
            values = value if isinstance(value, (list, tuple)) else [value]
            for seq, item in enumerate(values):
                scope = param.technique
                if param.base_unit:
                    # EC-Lab spells a current, charge or frequency as a
                    # magnitude row plus a unit row, at three decimals -- so a
                    # 1 uA setpoint written unscaled lands as 0.000, and one
                    # written without its unit is read in whatever unit the
                    # template happened to carry.
                    magnitude, unit = scale_to_unit(item, param.base_unit)
                    doc = mps_template.set_param(
                        doc, param.param_id, magnitude, seq=seq, technique=scope
                    )
                    if param.unit_param_id:
                        doc = mps_template.set_param(
                            doc, param.unit_param_id, unit, seq=seq, technique=scope
                        )
                else:
                    doc = mps_template.set_param(
                        doc,
                        param.param_id,
                        format_value(item, param.fmt),
                        seq=seq,
                        technique=scope,
                    )
        # ERange is not one row but a symmetric min/max pair, so it is applied
        # here rather than through parameter_map. AUTO yields no rows and
        # leaves the template's own window standing.
        for key, scope in (("ERange", None), ("CA_ERange", 0)):
            if key in action_params:
                for caption, value in erange_rows(action_params[key]).items():
                    doc = mps_template.set_param(doc, caption, value, technique=scope)
        return doc

    def setup(
        self,
        technique: OleTechnique,
        action_params: dict = {},
        output_dir: Optional[str] = None,
    ) -> DriverResponse:
        """Patch the template, write it, and load it onto the channel.

        ``LoadSettings`` returning 0 is the only pre-run validation the API
        offers -- the manual states it fails on settings incompatible with the
        hardware -- so a bad bandwidth or IRange is caught here rather than at
        ``RunChannel``.
        """
        channel = action_params.get("channel", -1)
        try:
            if channel not in self.channels:
                raise ValueError(f"Channel {channel} does not exist.")
            if self.channels[channel] is not None:
                raise ValueError(f"Channel {channel} is in use.")
            doc = self._patch(technique, action_params)
            ttl = mps_assemble.ttl_plan_from_params(action_params)
            if ttl.is_active:
                doc = mps_assemble.assemble(
                    doc,
                    ttl,
                    mps_template.load(self.templates_dir / "TI.mps"),
                    mps_template.load(self.templates_dir / "TO.mps"),
                )
            run_dir = self.scratch_dir / f"ch{channel}" / uuid.uuid4().hex
            path = mps_template.write_patched(
                doc, run_dir / f"{technique.technique_name}.mps"
            )
            self._bounded(
                self.client.load_settings,
                self.device_number,
                channel,
                str(path.resolve()),
            )
            loaded = self._status_of(channel)
            if (
                loaded.technique_code
                and loaded.technique_code not in technique.technique_codes
            ):
                LOGGER.warning(
                    "channel %s loaded technique code %s; %s expects one of %s "
                    "-- the template may not hold the technique it is named for",
                    channel,
                    loaded.technique_code,
                    technique.technique_name,
                    sorted(technique.technique_codes),
                )
            self.channels[channel] = technique
            self.channel_params[channel] = dict(action_params)
            self.scratch[channel] = run_dir
            self.output_dirs[channel] = Path(output_dir) if output_dir else None
            return DriverResponse(
                response=DriverResponseType.success,
                message="setup complete",
                status=DriverStatus.ok,
            )
        except OleComError as exc:
            LOGGER.error("setup failed: %s", exc)
            self.cleanup(channel)
            return DriverResponse(
                response=DriverResponseType.failed,
                message=str(exc),
                status=DriverStatus.error,
            )
        except Exception as exc:
            LOGGER.error("setup failed", exc_info=True)
            self.cleanup(channel)
            return DriverResponse(
                response=DriverResponseType.failed,
                message=str(exc),
                status=DriverStatus.error,
            )

    def setup_protocol(
        self,
        mps_path: str,
        action_params: dict,
        output_dir: Optional[str] = None,
    ) -> DriverResponse:
        """Load a station-authored ``.mps`` onto a channel, unpatched.

        The file is resolved against ``protocol_dir`` and must stay inside it:
        a station's protocol library is a declared location, not whatever an
        experiment passes. The technique record -- and therefore the column
        set -- is derived from status index 5 *after* loading, because the
        file decides the techniques and nothing here can know them first.
        """
        channel = action_params.get("channel", -1)
        try:
            if channel not in self.channels:
                raise ValueError(f"Channel {channel} does not exist.")
            if self.channels[channel] is not None:
                raise ValueError(f"Channel {channel} is in use.")
            root = self.protocol_dir.resolve()
            resolved = (root / mps_path).resolve()
            if not resolved.is_relative_to(root):
                raise ValueError(f"{mps_path!r} resolves outside protocol_dir {root}")
            if not resolved.is_file():
                raise FileNotFoundError(f"no protocol file at {resolved}")
            run_dir = self.scratch_dir / f"ch{channel}" / uuid.uuid4().hex
            run_dir.mkdir(parents=True, exist_ok=True)
            self._bounded(
                self.client.load_settings,
                self.device_number,
                channel,
                str(resolved),
            )
            loaded = self._status_of(channel)
            technique = protocol_technique(loaded.technique_code)
            LOGGER.info(
                "loaded protocol %s on channel %s; technique code %s -> %s plan",
                resolved.name,
                channel,
                loaded.technique_code,
                technique.column_plan.kind,
            )
            self.channels[channel] = technique
            self.channel_params[channel] = dict(action_params)
            self.scratch[channel] = run_dir
            self.output_dirs[channel] = Path(output_dir) if output_dir else None
            # Ship the protocol itself as provenance -- an unpatched copy is
            # still the exact settings this action ran.
            shutil.copy2(resolved, run_dir / resolved.name)
            return DriverResponse(
                response=DriverResponseType.success,
                message="protocol loaded",
                status=DriverStatus.ok,
            )
        except Exception as exc:
            LOGGER.error("setup_protocol failed", exc_info=True)
            self.cleanup(channel)
            return DriverResponse(
                response=DriverResponseType.failed,
                message=str(exc),
                status=DriverStatus.error,
            )

    # -- run -------------------------------------------------------------

    def start_channel(
        self, channel: int = 0, ttl_params: Optional[dict] = None
    ) -> DriverResponse:
        """Start the loaded technique.

        ``ttl_params`` is accepted for signature compatibility with the eclib
        driver and ignored: TTL is expressed as trigger techniques inside the
        ``.mps`` at ``setup`` time, because the OLE API has no trigger calls.
        """
        try:
            if self.channels.get(channel) is None:
                raise ValueError(f"Channel {channel} has not been set up.")
            if self._status_of(channel).is_busy:
                raise ValueError(f"Channel {channel} is busy.")
            out_base = str((self.scratch[channel] / "run").resolve())
            start_time = time.time()
            self._bounded(
                self.client.run_channel, self.device_number, channel, out_base
            )
            mpr = self._bounded(
                self.client.get_data_file_name, self.device_number, channel, 0
            )
            self.cursors[channel] = MprCursor(
                self.client, self.channels[channel].column_plan, mpr
            )
            return DriverResponse(
                response=DriverResponseType.success,
                message="measurement started",
                data={"start_time": start_time},
                status=DriverStatus.busy,
            )
        except Exception as exc:
            LOGGER.error("start_channel failed", exc_info=True)
            self.cleanup(channel)
            return DriverResponse(
                response=DriverResponseType.failed,
                message=str(exc),
                status=DriverStatus.error,
            )

    async def get_data(self, channel: int = 0) -> DriverResponse:
        """New points since the last call, plus the channel's state.

        ``message`` is the contract ``BiologicExec._poll`` reads: ``"done"``
        finishes the action. It is emitted only at state ``Stop``, and only
        after one further drain, because ``Stop_rec`` means the last points
        are still being written.
        """
        try:
            cursor = self.cursors.get(channel)
            if cursor is None:
                raise ValueError(f"Channel {channel} is not running.")
            reading = self._status_of(channel)
            data = cursor.read_new(cycle=reading.cycle)
            if reading.is_busy:
                return DriverResponse(
                    response=DriverResponseType.success,
                    message="measuring",
                    data=data,
                    status=DriverStatus.busy,
                )
            # Stopped: drain whatever landed between the read and the status.
            tail = cursor.read_new(cycle=reading.cycle)
            for name, values in tail.items():
                data.setdefault(name, []).extend(values)
            if reading.safety_limit not in (None, SafetyLimit.OK):
                LOGGER.alert(
                    "channel %s hit safety limit %s",
                    channel,
                    reading.safety_limit.name,
                )
            if not reading.connected:
                raise ConnectionError(f"Channel {channel} reports Disconnected.")
            return DriverResponse(
                response=DriverResponseType.success,
                message="done",
                data=data,
                status=DriverStatus.ok,
            )
        except Exception as exc:
            LOGGER.error("get_data failed", exc_info=True)
            return DriverResponse(
                response=DriverResponseType.failed,
                message=str(exc),
                status=DriverStatus.error,
            )

    # -- teardown --------------------------------------------------------

    def stop(self, channel: Optional[int] = None) -> DriverResponse:
        """Abort one channel, or every running one.

        ``StopChannel`` returning 0 means the channel was already stopped --
        an answer, not a fault, and not reported as one.
        """
        try:
            if self.stopping:
                return DriverResponse(
                    response=DriverResponseType.success, status=DriverStatus.ok
                )
            self.stopping = True
            try:
                targets = (
                    [channel]
                    if channel is not None
                    else [k for k, v in self.channels.items() if v is not None]
                )
                for target in targets:
                    if target not in self.channels:
                        LOGGER.warning("Channel %s does not exist.", target)
                        continue
                    if not self._bounded(
                        self.client.stop_channel, self.device_number, target
                    ):
                        LOGGER.info("Channel %s was already stopped.", target)
            finally:
                self.stopping = False
            return DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception as exc:
            LOGGER.error("stop failed", exc_info=True)
            return DriverResponse(
                response=DriverResponseType.failed,
                message=str(exc),
                status=DriverStatus.error,
            )

    def _ship_artifacts(self, channel: int) -> None:
        """Move the run's ``.mps`` and ``.mpr`` into the action directory.

        Moved at cleanup rather than written there: EC-Lab appends to the MPR
        for the whole run and ``HelaoYml.misc_files`` globs live directories,
        so a file written straight into the action directory could be uploaded
        half-finished. A failure here is logged and swallowed -- losing the
        provenance copy must not fail an otherwise good action.
        """
        run_dir, output_dir = self.scratch.get(channel), self.output_dirs.get(channel)
        if run_dir is None or output_dir is None or not run_dir.exists():
            return
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            for path in sorted(run_dir.iterdir()):
                if path.suffix.lower() in (".mps", ".mpr", ".mpt"):
                    shutil.move(str(path), str(output_dir / path.name))
        except Exception:
            LOGGER.warning(
                "could not ship OLE artifacts for channel %s from %s",
                channel,
                run_dir,
                exc_info=True,
            )

    def cleanup(self, channel: int) -> DriverResponse:
        """Release the channel and ship its artifacts. Stays connected."""
        try:
            if channel not in self.channels:
                raise ValueError(f"Channel {channel} does not exist.")
            if self.ready and self._status_of(channel).is_busy:
                raise ValueError(f"Channel {channel} is busy.")
            self._ship_artifacts(channel)
            self.channels[channel] = None
            self.channel_params[channel] = {}
            self.cursors[channel] = None
            self.scratch[channel] = None
            self.output_dirs[channel] = None
            return DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception as exc:
            LOGGER.error("cleanup failed", exc_info=True)
            return DriverResponse(
                response=DriverResponseType.failed,
                message=str(exc),
                status=DriverStatus.error,
            )

    def disconnect(self) -> DriverResponse:
        """Detach from the instrument. EC-Lab itself is left running."""
        try:
            if self.client is not None and self.device_number is not None:
                self._bounded(self.client.disconnect_device, self.device_number)
            LOGGER.info("disconnected from %s at %s", self.device_name, self.address)
            return DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception as exc:
            LOGGER.error("disconnect failed", exc_info=True)
            return DriverResponse(
                response=DriverResponseType.failed,
                message=str(exc),
                status=DriverStatus.error,
            )
        finally:
            self.device_number = None
            self.client = None
            self.ready = False

    def reset(self) -> DriverResponse:
        """Disconnect and reconnect, to recover from a bad state."""
        try:
            self.disconnect()
            return DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception:
            LOGGER.error("reset error", exc_info=True)
            return DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        finally:
            self.connect()

    def shutdown(self) -> None:
        """Stop every running channel, clean up, disconnect. Called by BaseAPI."""
        try:
            states = self.get_status().data
            for channel, state in states.items():
                if state > 0:
                    self.stop(channel=channel)
                    self.cleanup(channel=channel)
        finally:
            self.disconnect()
            self._pool.shutdown(wait=False)
