""" A device class for the Axis M1103 webcam.

"""

__all__ = ["AxisCam", "AxisCamExec"]

import os
import time
import asyncio
import requests
import aiofiles
from helao.helpers import logging
if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER

from helao.core.error import ErrorCodes
from helao.servers.base import Base
from helao.helpers.executor import Executor
from helao.core.models.hlostatus import HloStatus


class AxisCam:
    def __init__(self, action_serv: Base):
        self.base = action_serv
        self.config_dict = action_serv.server_cfg.get("params", {})

    def acquire_image(self):
        """Save image stream."""
        LOGGER.info("creating http session")
        with requests.Session() as session:
            LOGGER.info(f"making get request to {self.config_dict['axis_ip']}")
            resp = session.get(f"http://{self.config_dict['axis_ip']}/jpg/1/image.jpg")
            img = resp.content
            LOGGER.info(f"acquired image {len(img)} at: {time.time()}")
        return img

    def shutdown(self):
        # this gets called when the server is shut down or reloaded to ensure a clean
        # disconnect ... just restart or terminate the server
        pass


class AxisCamExec(Executor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs, exec_id="axis")
        # current plan is 1 flow controller per COM
        LOGGER.info("AxisCamExec initialized.")
        self.start_time = time.time()
        self.duration = self.active.action.action_params.get("duration", -1)
        self.counter = 0
        self.output_dir = os.path.join(
            self.active.base.helaodirs.save_root, self.active.action.action_output_dir
        )

    async def _pre_exec(self):
        "Set flow rate."
        LOGGER.info("AxisCamExec running setup methods.")
        return {"error": ErrorCodes.none}

    async def write_image(self, imgbytes, epoch):
        """Write image to action output directory."""
        ymdhms = time.strftime("%Y%m%d.%H%M%S", time.localtime(epoch))
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

    async def _exec(self):
        "Acquire single image."
        self.start_time = time.time()
        # self.active.base.print_message(
        #     f"Image acquisition started at {self.start_time}"
        # )
        img = self.active.base.fastapp.driver.acquire_image()
        # LOGGER.info("image acquired")
        live_dict = await self.write_image(img, self.start_time)
        return {"error": ErrorCodes.none, "data": live_dict}

    async def _poll(self):
        """Acquire subsequent images."""
        iter_time = time.time()
        img = self.active.base.fastapp.driver.acquire_image()
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
