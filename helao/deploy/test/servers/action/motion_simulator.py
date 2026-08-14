"""Motion simulation server.

Hosts :class:`MotionSim`, a stage simulator that reads a platemap CSV and
returns ``(x, y)`` for queried samples. The ``move`` action currently
sleeps a fixed duration instead of computing a motion time.
"""

__all__ = ["makeApp"]

import asyncio
from typing import Optional

import pandas as pd

from helao.hexagon.app.action_context import ActionContext
from helao.hexagon.app.action_host import ActionHost
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class MotionSim:
    """Simulated motion stage backed by a platemap CSV.

    Loads a platemap of sample positions from ``params.platemap_path`` and
    serves ``(x, y)`` lookups by sample number. ``move`` is a stub.

    Attributes:
        base: Hosting action server.
        config_dict: ``params`` block from the server config.
        world_config: Full world configuration.
        present_x: Cached x position (unused).
        present_y: Cached y position (unused).
        pmdf: Platemap dataframe with sample positions and codes.
    """

    def __init__(self, action_serv: ActionHost):
        """Load the platemap CSV.

        Args:
            action_serv: Action server hosting this driver.
        """
        self.base = action_serv
        self.config_dict = action_serv.server_cfg.get("params", {})
        self.world_config = action_serv.world_cfg
        self.present_x = 0
        self.present_y = 0
        pm_cols = [
            "Sample",
            "x",
            "y",
            "dx",
            "dy",
            "A",
            "B",
            "C",
            "D",
            "E",
            "F",
            "G",
            "H",
            "code",
        ]
        self.pmdf = pd.read_csv(
            self.config_dict["platemap_path"], skiprows=2, header=None, names=pm_cols
        )

    def solid_get_samples_xy(
        self, plate_id: int, sample_no: int, *args, **kwargs
    ) -> dict:
        """Look up the (x, y) coordinates of a sample on a plate.

        Args:
            plate_id: Plate identifier (used in log messages only).
            sample_no: Sample number to look up.
            *args: Ignored extra positional arguments.
            **kwargs: Ignored extra keyword arguments.

        Returns:
            Dict with key ``"platexy"`` mapping to ``[x, y]`` or
            ``[None, None]`` if the sample is not found.
        """
        rowmatch = self.pmdf.query(f"Sample=={sample_no}")
        if len(rowmatch) == 0:
            LOGGER.info(
                f"Could not locate sample_no: {sample_no} on plate_id: {plate_id}"
            )
            retxy = [None, None]
        else:
            if len(rowmatch) > 1:
                LOGGER.info(
                    f"Found multiple locations matching plate_id: {plate_id}, sample_no: {sample_no}, returning first match."
                )
            else:
                LOGGER.info("Found x,y")
            firstmatch = rowmatch.iloc[0]
            retxy = [float(firstmatch.x), float(firstmatch.y)]
        return {"platexy": retxy}

    def move(self, d_mm: list[float], axis: list[str], speed: Optional[int] = None):
        """No-op move stub.

        Args:
            d_mm: Per-axis displacements in millimeters.
            axis: Axis labels matching ``d_mm``.
            speed: Optional motion speed.
        """
        pass

    def shutdown(self):
        """No-op shutdown hook."""
        pass


def makeApp(server_key):
    """Build the motion-simulator FastAPI app.

    Wires :class:`MotionSim` into a :class:`BaseAPI` and exposes
    ``solid_get_samples_xy`` (platemap lookup) and ``move`` (sleep stub).

    Args:
        server_key: Server name in the launched config.

    Returns:
        Configured :class:`HelaoFastAPI` app.
    """
    app = ActionHost(
        server_key=server_key,
        server_title=server_key,
        description="Motion simulator",
        version=2.0,
        driver_classes=[MotionSim],
    )

    @app.action()
    async def solid_get_samples_xy(
        ctx: ActionContext,
        plate_id: Optional[int] = None,
        sample_no: Optional[int] = None,
    ):
        """Look up the platemap coordinates for a sample and stamp them on the action."""
        active = await ctx.begin()
        platexy = app.driver.solid_get_samples_xy(**active.action.action_params)
        active.action.action_params.update({"_platexy": platexy})
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.action()
    async def move(
        ctx: ActionContext,
        d_mm: list[float] = [0, 0],
        axis: list[str] = ["x", "y"],
        speed: Optional[int] = None,
    ):
        """Simulate axis motion by sleeping for a fixed 3 seconds."""
        active = await ctx.begin(action_abbr="move")
        await asyncio.sleep(3)
        finished_action = await active.finish()
        return finished_action.as_dict()

    return app
