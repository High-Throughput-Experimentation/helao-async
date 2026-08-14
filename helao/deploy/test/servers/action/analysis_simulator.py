"""Analysis simulation server.

Hosts :class:`AnalysisSim` behind a FastAPI app that exposes a single
``calc_cpfom`` action returning the stored CP overpotential (vs O2/H2O) for
a queried plate/sample/pH/current-density combination.
"""

__all__ = ["makeApp"]


import pandas as pd

from helao.hexagon.app.action_context import ActionContext
from helao.hexagon.app.action_host import ActionHost


class AnalysisSim:
    """Simulated analysis driver backed by a CSV archive of CP eta values.

    Loads the CSV at ``params.data_path``, groups it by ``plate_id`` and
    ``solution_ph``, and precomputes a per-plate description (elements
    present and their composition fractions). The ``calc_cpfom`` method
    returns the stored eta for the requested sample.

    Attributes:
        base: Hosting action server.
        config_dict: ``params`` block from the server config.
        world_config: Full world configuration.
        df: Raw measurement dataframe loaded from CSV.
        loaded_df: Reserved for future per-plate selections.
        platespaces: List of per-plate descriptors with elements and
            element fractions.
    """

    def __init__(self, action_serv: ActionHost):
        """Load the CSV archive and precompute plate descriptors.

        Args:
            action_serv: Action server hosting this driver.
        """
        self.base = action_serv
        self.config_dict = action_serv.server_cfg.get("params", {})
        self.world_config = action_serv.world_cfg
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

    def calc_cpfom(
        self, plate_id: int, sample_no: int, ph: int, jmacm2: int, *args, **kwargs
    ) -> float:
        """Return the stored CP overpotential for a queried sample.

        Args:
            plate_id: Plate identifier.
            sample_no: Sample number on the plate.
            ph: Solution pH used in the measurement.
            jmacm2: Current density in mA/cm^2 selecting the ``EtaV_CP<j>``
                column.
            *args: Ignored extra positional arguments.
            **kwargs: Ignored extra keyword arguments.

        Returns:
            Stored overpotential value for the first matching row.
        """
        match = self.df.query(
            f"plate_id=={plate_id} & Sample=={sample_no} & solution_ph=={ph}"
        )
        eta = float(match[f"EtaV_CP{jmacm2}"].iloc[0])
        return eta

    def shutdown(self):
        """No-op shutdown hook."""
        pass


def makeApp(server_key):
    """Build the analysis-simulator FastAPI app.

    Wires :class:`AnalysisSim` into a :class:`BaseAPI` instance and exposes
    a single ``/<server_key>/calc_cpfom`` action that returns the stored
    eta value for the queried sample.

    Args:
        server_key: Server name in the launched config.

    Returns:
        Configured :class:`HelaoFastAPI` app.
    """
    app = ActionHost(
        server_key=server_key,
        server_title=server_key,
        description="Analysis simulator",
        version=2.0,
        driver_classes=[AnalysisSim],
    )

    @app.action()
    async def calc_cpfom(
        ctx: ActionContext,
        plate_id: int = 0,
        sample_no: int = 0,
        ph: int = 0,
        jmacm2: int = 3,
    ):
        """Look up Eta vs O2/H2O for the queried sample and return the action."""
        active = await ctx.begin()
        eta = app.driver.calc_cpfom(**active.action.action_params)
        active.action.action_params.update({f"_eta": eta})
        finished_action = await active.finish()
        return finished_action.as_dict()

    return app
