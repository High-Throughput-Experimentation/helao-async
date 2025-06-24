""" Archive simulation server

FastAPI server host for the analysis simulator driver. Loads historical data.
TODO: Returns FOM.
"""

__all__ = ["makeApp"]


from fastapi import Body
import pandas as pd

from helao.servers.base import Base
from helao.servers.base_api import BaseAPI
from helao.helpers.premodels import Action
from helao.helpers.config_loader import CONFIG


class AnalysisSim:
    def __init__(self, action_serv: Base):
        self.base = action_serv
        self.config_dict = action_serv.server_cfg.get("params", {})
        self.world_config = action_serv.world_cfg
        self.df = pd.read_csv(self.config_dict['data_path'])
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
            
    def calc_cpfom(self, plate_id:int, sample_no:int, ph:int, jmacm2:int, *args, **kwargs):
        match = self.df.query(f"plate_id=={plate_id} & Sample=={sample_no} & solution_ph=={ph}")
        eta = float(match[f"EtaV_CP{jmacm2}"].iloc[0])
        return eta
    
    def shutdown(self):
        pass


def makeApp(server_key):

    config = CONFIG

    app = BaseAPI(
        config=config,
        server_key=server_key,
        server_title=server_key,
        description="Analysis simulator",
        version=2.0,
        driver_classes=[AnalysisSim]
    )

    @app.post(f"/{server_key}/calc_cpfom", tags=["action"])
    async def calc_cpfom(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        plate_id: int = 0,
        sample_no: int = 0,
        ph: int = 0,
        jmacm2: int = 3
    ):
        """Calculate Eta vs O2/H2O potential."""
        active = await app.base.setup_and_contain_action()
        eta = app.driver.calc_cpfom(**active.action.action_params)
        active.action.action_params.update({f"_eta": eta})
        finished_action = await active.finish()
        return finished_action.as_dict()

    return app
