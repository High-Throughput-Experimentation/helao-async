"""HelaoDriver for Biologic potentiostats, calling the EClib1 DLL directly.

Replaces the former easy-biologic-backed driver: connection, firmware, and
status now go through `eclib_client.EclibClient`, which serializes every
vendor call onto one worker thread and turns a vendor error code into
`EclibError`. This module owns the connection half of the driver --
``__init__``, ``connect``, ``get_status``, ``disconnect``, ``reset``, and
``shutdown``. The measurement half (``setup``, ``start_channel``,
``get_data``, ``stop``, ``cleanup``) is added alongside it, not stubbed here.

Unlike the easy-biologic driver, which opened a program per channel, this
driver claims a single channel at a time (``self.channel``) -- see the
measurement half for why.
"""

from typing import Optional

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

from helao.core.drivers.helao_driver import (
    DriverResponse,
    DriverResponseType,
    DriverStatus,
    HelaoDriver,
)
from helao.deploy.hte.drivers.pstat.biologic import vendor
from helao.deploy.hte.drivers.pstat.biologic.eclib_client import EclibClient, EclibError


def _kernel_loaded(ch: vendor.ChannelInfo) -> bool:
    """A channel with no firmware kernel loaded reports ``FirmwareCode == 0``.

    Same check as the vendor example's ``is_kernel_loaded`` property; kept
    here (not called from the example, which this repo does not vendor).
    """
    return ch.FirmwareCode != 0


class BiologicDriver(HelaoDriver):
    """HelaoDriver implementation for a multi-channel Biologic potentiostat,
    driven directly through the EClib1 DLL.

    Attributes:
        ready: Whether ``connect()`` has succeeded and not since been undone.
        address: Instrument IP address.
        num_channels: Number of channels the instrument exposes.
        sdk_path: Filesystem path to the EC-Lab Development Package's ``lib``
            directory (or, under simulation, an unused placeholder).
        simulate: Whether to load the in-process fake DLL instead of the
            real one.
        force_load_firmware: Reflash the channel's firmware kernel on every
            connect, even when one is already loaded. Off by default -- see
            module docstring for why the vendor example's ``force=True`` is
            not the default here.
        device_name: Human-readable identifier for the connected instrument.
        channel: The single channel currently claimed for a measurement, or
            ``None`` when free.
        board_type: The connected channel's ``vendor.BOARD_TYPE`` value, or
            ``None`` before a successful connect.
    """

    device_name: str

    def __init__(self, config: dict = {}):
        """Store configuration only. No device I/O here -- the action server
        calls ``connect()`` at startup (P3a-2 constructor-connect fix).

        Args:
            config: Driver configuration. Recognized keys: ``address``
                (default ``"192.168.200.240"``), ``num_channels`` (default
                ``12``), ``sdk_path`` (default ``vendor.DEFAULT_SDK_PATH``),
                ``simulate`` (default ``False``), ``force_load_firmware``
                (default ``False``), ``timeout`` (default ``5``).
        """
        super().__init__(config=config)
        self.address = config.get("address", "192.168.200.240")
        self.num_channels = config.get("num_channels", 12)
        self.sdk_path = config.get("sdk_path", vendor.DEFAULT_SDK_PATH)
        self.simulate = config.get("simulate", False)
        self.force_load_firmware = config.get("force_load_firmware", False)
        self.timeout = config.get("timeout", 5)

        self.ready = False
        self.channel: Optional[int] = None
        self.board_type: Optional[int] = None
        self.device_name = "unknown"
        self._client: Optional[EclibClient] = None
        self._tracker = None
        self._technique = None

    def connect(self) -> DriverResponse:
        """Open the connection to the instrument and load its firmware if
        needed.

        A second call on an already-live connection is a successful no-op,
        checked via ``EclibClient.test_connection`` rather than a flag set
        before the attempt -- a flag set early is what stranded the old
        driver after a throwing connect.

        Returns:
            ``DriverResponse`` with ``status=ok`` on success, ``status=busy``
            if EC-Lab already holds the instrument, otherwise
            ``status=error``. A failed attempt tears down any half-built
            client so the driver stays retryable.
        """
        if self.ready and self._client is not None and self._client.test_connection():
            return DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )

        client = None
        try:
            client = EclibClient(sdk_path=self.sdk_path, simulate=self.simulate)
            info = client.connect(self.address, self.timeout)
            self.device_name = f"{info.DeviceCode}/fw{info.FirmwareVersion}"
            self.board_type = client.board_type(0)
            LOGGER.info(
                f"connected to {self.device_name} at {self.address} "
                f"(board_type={vendor.BOARD_TYPE(self.board_type).name}, "
                f"family={vendor.board_family(self.board_type).value})"
            )

            ch = client.channel_info(0)
            if self.force_load_firmware or not _kernel_loaded(ch):
                kernel, fpga = vendor.firmware_assets(self.board_type)
                client.load_firmware(0, kernel, fpga, force=self.force_load_firmware)

            for message in client.drain_messages(0):
                LOGGER.warning(f"channel 0 firmware message: {message}")

            self._client = client
            self.ready = True
            return DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except EclibError as exc:
            LOGGER.error(f"connect failed: {exc}", exc_info=True)
            status = (
                DriverStatus.busy
                if exc.name == "ERR_GEN_ECLAB_LOADED"
                else DriverStatus.error
            )
            if client is not None:
                client.close()
            return DriverResponse(response=DriverResponseType.failed, status=status)
        except Exception:
            LOGGER.error("connect failed", exc_info=True)
            if client is not None:
                client.close()
            return DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )

    def get_status(self, channel: Optional[int] = None) -> DriverResponse:
        """Return the driver status, optionally for a single channel.

        Args:
            channel: Channel index to query. When ``None``, queries every
                channel and reports ``busy`` if any is not ``STOP``.

        Returns:
            ``DriverResponse`` whose ``data`` maps channel index to the raw
            ``State`` int. An out-of-range channel (or a driver that has
            never connected) reports ``uninitialized`` with ``data={}``.
        """
        if not self.ready or self._client is None:
            return DriverResponse(
                response=DriverResponseType.success,
                status=DriverStatus.uninitialized,
                data={},
            )
        if channel is None:
            channels = list(range(self.num_channels))
        elif 0 <= channel < self.num_channels:
            channels = [channel]
        else:
            return DriverResponse(
                response=DriverResponseType.success,
                status=DriverStatus.uninitialized,
                data={},
            )

        try:
            data = {}
            for ch in channels:
                info = self._client.channel_info(ch)
                data[ch] = info.State
                for message in self._client.drain_messages(ch):
                    LOGGER.warning(f"channel {ch} firmware message: {message}")
            status = (
                DriverStatus.busy
                if any(state != vendor.PROG_STATE.STOP for state in data.values())
                else DriverStatus.ok
            )
            return DriverResponse(
                response=DriverResponseType.success, status=status, data=data
            )
        except EclibError:
            LOGGER.error("get_status failed", exc_info=True)
            return DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )

    def disconnect(self) -> DriverResponse:
        """Close the connection to the instrument and clear connected state."""
        try:
            if self._client is not None:
                self._client.close()
            return DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception:
            LOGGER.error("disconnect failed", exc_info=True)
            return DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        finally:
            self._client = None
            self.ready = False
            self.channel = None
            self.board_type = None

    def stop(self, channel: Optional[int] = None) -> DriverResponse:
        """Not implemented here.

        `HelaoDriver` declares `stop` abstract, so a concrete method must
        exist for this class to be instantiable at all -- Task 14 (the
        measurement half) replaces this with the real per-channel stop.
        """
        return DriverResponse(response=DriverResponseType.not_implemented)

    def reset(self) -> DriverResponse:
        """Disconnect then reconnect, reporting the reconnect's own result.

        The previous implementation built a success response before
        reconnecting in a ``finally``, so a failed reconnect still reported
        success. This returns whatever ``connect()`` actually reports.
        """
        self.disconnect()
        return self.connect()

    def shutdown(self) -> None:
        """Release a claimed channel, if any, then disconnect.

        Safe to call on a driver that never connected. Stopping/cleaning up
        a claimed channel is the measurement half's responsibility
        (``stop``/``cleanup``); this only drives them when there is
        something to release.
        """
        if self.channel is not None:
            try:
                self.stop(self.channel)
            except Exception:
                LOGGER.error("shutdown: stop failed", exc_info=True)
            try:
                self.cleanup(self.channel)  # type: ignore[attr-defined]  # Task 14
            except Exception:
                LOGGER.error("shutdown: cleanup failed", exc_info=True)
        self.disconnect()
