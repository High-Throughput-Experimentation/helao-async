
# shell: uvicorn motion_server:app --reload
""" Serial sensor server

"""

__all__ = ["makeApp"]

from typing import Optional, List
from fastapi import Body
from helao.helpers.premodels import Action
from helao.servers.base import makeActionServ
from helaocore.models.sample import SampleUnion
from helao.drivers.sensor.sprintir import SprintIR
from helao.helpers.config_loader import config_loader


def makeApp(confPrefix, servKey, helao_root):

    config = config_loader(confPrefix, helao_root)

    app = makeActionServ(
        config=config,
        server_key=servKey,
        server_title=servKey,
        description="Sensor server",
        version=0.1,
        driver_class=SprintIR,
    )

    @app.post(f"/{servKey}/acquire_co2")
    async def acquire_co2(
        action: Optional[Action] = Body({}, embed=True),
        action_version: int = 1,
        duration: Optional[float] = -1,
        acquisition_rate: Optional[float] = 0.2,
        fast_samples_in: Optional[List[SampleUnion]] = Body([], embed=True),
    ):
        """Acquire spectra based on external trigger."""
        A = await app.base.setup_action()
        A.action_abbr = "CO2"
        active_dict = await app.driver.acquire_co2(A)
        return active_dict

    return app
