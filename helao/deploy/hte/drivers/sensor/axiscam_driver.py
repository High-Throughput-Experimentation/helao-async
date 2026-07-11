"""Axis M1103 webcam driver.

Provides :class:`AxisCam`, which fetches JPEG snapshots from the camera's
HTTP endpoint, and :class:`AxisCamExec`, an executor that periodically
acquires and writes images to the action output directory.
"""

__all__ = ["AxisCam", "AxisCamExec"]

import os
import time
import asyncio
import requests
import aiofiles
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
from helao.core.error import ErrorCodes
from helao.helpers.executor import Executor
from helao.core.models.hlostatus import HloStatus
from helao.core.models.run_dir import RunDir
from helao.core.drivers.helao_driver import (
    HelaoDriver,
    DriverResponse,
    DriverResponseType,
    DriverStatus,
)


class AxisCam(HelaoDriver):
    """Driver that pulls still JPEGs from an Axis M1103 IP camera over HTTP."""

    def __init__(self, config: dict = {}):
        """Store the driver config.

        Args:
            config: Driver-specific configuration dict, providing the
                ``axis_ip`` entry.
        """
        super().__init__(config=config)
        self.config_dict = self.config

    def connect(self) -> DriverResponse:
        """No persistent device connection; always succeeds."""
        return DriverResponse(
            response=DriverResponseType.success,
            message="no device",
            status=DriverStatus.ok,
        )

    def get_status(self) -> DriverResponse:
        """No physical device to poll; always reports ok."""
        return DriverResponse(response=DriverResponseType.success, status=DriverStatus.ok)

    def stop(self) -> DriverResponse:
        """No active activity to abort; always succeeds."""
        return DriverResponse(response=DriverResponseType.success, status=DriverStatus.ok)

    def reset(self) -> DriverResponse:
        """No device state to reinitialize; always succeeds."""
        return DriverResponse(response=DriverResponseType.success, status=DriverStatus.ok)

    def disconnect(self) -> DriverResponse:
        """No persistent connection to release; always succeeds."""
        return DriverResponse(response=DriverResponseType.success, status=DriverStatus.ok)

    def acquire_image(self) -> bytes:
        """Fetch a single JPEG snapshot from the camera.

        Returns:
            Raw JPEG bytes from the camera's ``/jpg/1/image.jpg`` endpoint.
        """
        LOGGER.info("creating http session")
        with requests.Session() as session:
            LOGGER.info(f"making get request to {self.config_dict['axis_ip']}")
            resp = session.get(f"http://{self.config_dict['axis_ip']}/jpg/1/image.jpg")
            img = resp.content
            LOGGER.info(f"acquired image {len(img)} at: {time.time()}")
        return img

    def shutdown(self):
        """No-op shutdown hook for the HTTP-only camera driver."""
        # this gets called when the server is shut down or reloaded to ensure a clean
        # disconnect ... just restart or terminate the server
        pass


class AxisCamExec(Executor):
    """Executor that captures a stream of webcam images for the action duration."""

    def __init__(self, *args, **kwargs):
        """Initialize counters and resolve the per-action output directory.

        Args:
            *args: Positional args forwarded to :class:`Executor`.
            **kwargs: Keyword args forwarded to :class:`Executor`.
        """
        super().__init__(*args, **kwargs, exec_id="axis")
        # current plan is 1 flow controller per COM
        LOGGER.info("AxisCamExec initialized.")
        self.counter = 0
        save_root = str(self.active.base.helaodirs.save_root)
        if self.active.action.manual_action:
            save_root = save_root.replace(RunDir.ACTIVE.value, RunDir.DIAG.value)
        self.output_dir = os.path.join(save_root, self.active.action.action_output_dir)

    async def _pre_exec(self) -> dict:
        """Pre-execution hook; no setup required for the camera."""
        LOGGER.info("AxisCamExec running setup methods.")
        return {"error": ErrorCodes.none}

    async def write_image(self, imgbytes, epoch) -> dict:
        """Write a JPEG to the action output directory and register the file.

        Args:
            imgbytes: Raw JPEG bytes to write.
            epoch: Acquisition timestamp in seconds since the epoch.

        Returns:
            Dict with ``epoch_s`` and ``filename`` entries describing the
            written image.
        """
        ymdhms = time.strftime("%y%m%d.%H%M%S", time.localtime(epoch))
        filename = f"cam_{self.counter:06}_{ymdhms}.jpg"
        LOGGER.info(f"Writing image to: {os.path.join(self.output_dir, filename)}")
        async with aiofiles.open(os.path.join(self.output_dir, filename), "wb") as f:
            await f.write(imgbytes)
        live_dict = {"epoch_s": epoch, "filename": filename}
        await self.active.track_file(
            "webcam_image",
            os.path.join(self.output_dir, filename),
            samples=self.active.action.samples_in,
        )
        self.counter += 1
        return live_dict

    async def _exec(self) -> dict:
        """Acquire the first image and write it to disk."""
        self.start_time = time.time()
        # self.active.base.print_message(
        #     f"Image acquisition started at {self.start_time}"
        # )
        img = self.active.driver.acquire_image()
        # LOGGER.info("image acquired")
        live_dict = await self.write_image(img, self.start_time)
        return {"error": ErrorCodes.none, "data": live_dict}

    async def _poll(self) -> dict:
        """Acquire the next image and report active/finished status.

        Returns:
            Dict with ``error``, ``status``, and ``data`` keys; status is
            ``finished`` once ``self.duration`` has elapsed (negative
            durations run indefinitely).
        """
        iter_time = time.time()
        img = self.active.driver.acquire_image()
        live_dict = await self.write_image(img, iter_time)
        elapsed_time = iter_time - self.start_time
        if (self.duration < 0) or (elapsed_time < self.duration):
            status = HloStatus.active
        else:
            status = HloStatus.finished
        await asyncio.sleep(0.01)
        return {
            "error": ErrorCodes.none,
            "status": status,
            "data": live_dict,
        }
