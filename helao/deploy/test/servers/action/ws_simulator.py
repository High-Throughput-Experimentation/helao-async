"""Websocket simulation server.

Hosts :class:`WsSim`, which polls a synthetic 6-series random data
generator into the action server's live buffer, and exposes the
``acquire_data``/``cancel_acquire_data`` actions driven by
:class:`WsExec` to forward the live buffer to clients.
"""

__all__ = ["makeApp"]

import asyncio
import time
from typing import Union

import numpy as np
from fastapi import Body

from helao.core.error import ErrorCodes
from helao.core.models.hlostatus import HloStatus
from helao.core.models.sample import (
    AssemblySample,
    GasSample,
    LiquidSample,
    NoneSample,
    SolidSample,
)
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
from helao.core.servers.base import Base, Executor
from helao.core.servers.base_api import BaseAPI


class WsSim:
    """Synthetic multi-series data generator feeding the action server live buffer.

    Spawns a background polling task that emits a dict of series values scaled
    by ``self.scale_map`` and a random ``[0, 1)`` factor at 10 Hz. The series
    are ``series_<i>`` unless the config's ``columns`` block names others.

    Attributes:
        base: Hosting action server.
        config_dict: ``params`` block from the server config.
        world_config: Full world configuration.
        scale_map: Per-series multiplier, from the config's ``columns`` block
            or the default six (1, 2, 5, 10, 50, 100).
        event_loop: Reference to the running asyncio loop.
        polling_task: Background task running :meth:`poll_data_loop`.
    """

    def __init__(self, action_serv: Base):
        """Initialize the simulator and start the polling loop.

        Args:
            action_serv: Action server hosting this driver.
        """
        self.base = action_serv
        self.config_dict = action_serv.server_cfg.get("params", {})
        self.world_config = action_serv.world_cfg
        # Column names are configurable so a config can point this simulator at
        # a panel written for real hardware -- the hte live panels key their
        # rolling means off column names, and `series_0` would exercise none of
        # that. `columns` maps name -> scale; omitted, the original six stand.
        configured = self.config_dict.get("columns")
        if isinstance(configured, dict) and configured:
            self.scale_map = {str(k): float(v) for k, v in configured.items()}
        else:
            self.scale_map = {
                f"series_{i}": v for i, v in enumerate([1, 2, 5, 10, 50, 100])
            }

        self.event_loop = asyncio.get_event_loop()
        self.polling_task = self.event_loop.create_task(self.poll_data_loop())

    async def poll_data_loop(self, frequency_hz: float = 10):
        """Continuously push synthetic series data into the live buffer.

        Args:
            frequency_hz: Polling rate in Hz.
        """
        waittime = 1.0 / frequency_hz
        LOGGER.info("Starting polling loop")
        while True:
            data_msg = {k: v * np.random.uniform() for k, v in self.scale_map.items()}
            await self.base.put_lbuf({"sim_dict": data_msg})
            await asyncio.sleep(waittime)

    def shutdown(self):
        """No-op shutdown hook."""
        pass


class WsExec(Executor):
    """Executor that streams the websocket simulator's live buffer.

    Reads the latest ``sim_dict`` snapshot from the action server's live
    buffer on each poll and forwards it as the action's data. Terminates
    when ``duration`` seconds have elapsed, or runs indefinitely when
    ``duration`` is negative.
    """

    def __init__(self, *args, **kwargs):
        """Initialize the executor from the active action's parameters."""
        super().__init__(*args, **kwargs)
        LOGGER.info("WsExec initialized.")
        self.start_time = time.time()
        self.duration = self.active.action.action_params.get("duration", -1)

    async def _poll(self) -> dict:
        """Forward the latest live-buffer snapshot to the action.

        Returns:
            Dict with the snapshot data, ``ErrorCodes.none`` and an
            ``HloStatus`` that switches to ``finished`` once ``duration``
            seconds have elapsed (when ``duration`` is non-negative).
        """
        live_dict = {}
        sim_dict, epoch_s = self.active.base.get_lbuf("sim_dict")
        live_dict["epoch_s"] = epoch_s
        live_dict.update(sim_dict)
        iter_time = time.time()
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


def makeApp(server_key):
    """Build the websocket-simulator FastAPI app.

    Wires :class:`WsSim` into a :class:`BaseAPI` and exposes the
    ``acquire_data`` action (driven by :class:`WsExec`) and
    ``cancel_acquire_data``.

    Args:
        server_key: Server name in the launched config.

    Returns:
        Configured :class:`HelaoFastAPI` app.
    """
    app = BaseAPI(
        server_key=server_key,
        server_title=server_key,
        description="Websocket simulator",
        version=1.0,
        driver_classes=[WsSim],
    )

    @app.post(f"/{server_key}/acquire_data", tags=["action"])
    async def acquire_data(
        duration: float = -1,
        acquisition_rate: float = 0.2,
        fast_samples_in: list[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = Body([], embed=True),
    ):
        """Start a :class:`WsExec` that streams the simulator's live buffer."""
        active = await app.base.setup_and_contain_action()
        active.action.action_abbr = "WsSim"
        executor = WsExec(
            active=active,
            oneoff=False,
            poll_rate=active.action.action_params["acquisition_rate"],
        )
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post(f"/{server_key}/cancel_acquire_data", tags=["action"])
    async def cancel_acquire_data():
        """Stop any running ``acquire_data`` executor."""
        active = await app.base.setup_and_contain_action()
        for exec_id, executor in app.base.executors.items():
            if exec_id.split()[0] == "acquire_data":
                executor.stop_action_task()
        finished_action = await active.finish()
        return finished_action.as_dict()

    return app
