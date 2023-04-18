""" A device class for the Axis M1103 webcam.

"""

__all__ = ["AxisCam", "AxisCamExec"]

import os
import time
import asyncio
import aiohttp

from helaocore.error import ErrorCodes
from helao.servers.base import Base, Executor
from helaocore.models.hlostatus import HloStatus


class AxisCam:
    def __init__(self, action_serv: Base):
        self.base = action_serv
        self.config_dict = action_serv.server_cfg["params"]
        self.aloop = asyncio.get_running_loop()

    async def acquire_image(self):
        """Save image stream."""
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"http://{self.config_dict['axis_ip']}/jpg/1/image.jpg"
            ) as resp:
                img = await resp.read()
        return img

    def shutdown(self):
        # this gets called when the server is shut down or reloaded to ensure a clean
        # disconnect ... just restart or terminate the server
        pass


class AxisCamExec(Executor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs, exec_id="axis")
        # current plan is 1 flow controller per COM
        self.active.base.print_message("AxisCamExec initialized.")
        self.start_time = time.time()
        self.duration = self.active.action.action_params.get("duration", -1)
        self.counter = 0
        self.output_dir = self.active.action.action_output_dir

    def write_image(self, imgbytes, epoch):
        """Write image to action output directory."""
        filename = f"cam_{self.counter:06}.jpg"
        with open(os.path.join(self.output_dir, filename), "wb") as f:
            f.write(imgbytes)
        live_dict = {"epoch_s": epoch, "filename": filename}
        self.active.track_file(
            "webcam_image",
            os.path.join(self.output_dir, filename),
            samples=self.active.action.samples_in,
        )
        self.counter += 1
        return live_dict

    async def _exec(self):
        "Acquire single image."
        self.start_time = time.time()
        img = await self.active.base.driver.acquire_image()
        self.active.base.print_message(f"acquired image at: {self.start_time}")
        live_dict = self.write_image(img, self.start_time)
        return {"error": ErrorCodes.none, "data": live_dict}

    async def _poll(self):
        """Acquire subsequent images."""
        iter_time = time.time()
        img = await self.active.base.driver.acquire_image()
        live_dict = self.write_image(img, iter_time)
        elapsed_time = iter_time - self.start_time
        if (self.duration < 0) or (elapsed_time < self.duration):
            status = HloStatus.active
        else:
            status = HloStatus.finished
        await asyncio.sleep(0.001)
        return {
            "error": ErrorCodes.none,
            "status": status,
            "data": live_dict,
        }
