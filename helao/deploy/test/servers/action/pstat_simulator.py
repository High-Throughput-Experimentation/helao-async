"""Potentiostat simulation server.

Hosts :class:`PstatSim`, a minimal potentiostat stand-in that loads an OER
archive CSV to expose plate metadata. The ``run_CP`` action currently
sleeps for ``Tval__s`` seconds without streaming data.
"""

__all__ = ["makeApp"]


import asyncio
from typing import Optional

import pandas as pd

from helao.hexagon.app.action_context import ActionContext
from helao.hexagon.app.action_host import ActionHost


class PstatSim:
    """Simulated potentiostat backed by an OER eta archive CSV.

    Loads the CSV at ``params.data_path`` and precomputes per-plate
    descriptors (pH, element labels, composition fractions). Used only as a
    metadata source by the simulated CP action.

    Attributes:
        base: Hosting action server.
        config_dict: ``params`` block from the server config.
        world_config: Full world configuration.
        measure_status: Reserved placeholder.
        df: Raw measurement dataframe.
        loaded_df: View of ``df`` restricted to the loaded plate.
        platespaces: List of per-plate descriptors.
    """

    def __init__(self, action_serv: ActionHost):
        """Load the archive CSV and precompute plate descriptors.

        Args:
            action_serv: Action server hosting this driver.
        """
        self.base = action_serv
        self.config_dict = action_serv.server_cfg.get("params", {})
        self.world_config = action_serv.world_cfg
        self.measure_status = None
        self.df = pd.read_csv(self.config_dict["data_path"])
        self.loaded_df = None
        non_els = [
            "plate_id",
            "Sample",
            "solution_ph",
            "EtaV_CP3",
            "EtaV_CP10",
        ]
        plateparams = (
            self.df[non_els]
            .groupby(["plate_id", "solution_ph"])
            .count()
            .reset_index()[["plate_id", "solution_ph"]]
        )
        self.platespaces = []
        for plate_id in set(self.df.plate_id):
            platedf = self.df.query(f"plate_id=={plate_id}")
            els = [
                k
                for k, v in (platedf.drop(non_els, axis=1).sum(axis=0) > 0).items()
                if v > 0
            ]
            self.platespaces.append(
                {
                    "plate_id": plate_id,
                    "solution_ph": plateparams.query(
                        f"plate_id=={plate_id}"
                    ).solution_ph.to_list()[0],
                    "elements": els,
                    "element_fracs": platedf[els].to_numpy().tolist(),
                }
            )

    def shutdown(self):
        """No-op shutdown hook."""
        pass


def makeApp(server_key):
    """Build the potentiostat-simulator FastAPI app.

    Wires :class:`PstatSim` into a :class:`BaseAPI` and registers the
    ``run_CP`` action, which sleeps for ``Tval__s`` seconds.

    Args:
        server_key: Server name in the launched config.

    Returns:
        Configured :class:`HelaoFastAPI` app.
    """
    app = ActionHost(
        server_key=server_key,
        server_title=server_key,
        description="PSTAT simulator",
        version=2.0,
        driver_classes=[PstatSim],
    )

    @app.action()
    async def run_CP(
        ctx: ActionContext,
        Ival: float = 0.0,
        Tval__s: float = 10.0,
        AcqInterval__s: Optional[
            float
        ] = 1.0,  # Time between data acquisition samples in seconds.
    ):
        """Simulate a chronopotentiometry run by sleeping ``Tval__s`` seconds."""
        active = await ctx.begin()
        active.action.action_abbr = "CP"
        await asyncio.sleep(active.action.action_params["Tval__s"])
        finished_action = await active.finish()
        return finished_action.as_dict()

    return app
