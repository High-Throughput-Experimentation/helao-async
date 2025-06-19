# shell: uvicorn motion_server:app --reload
""" Analysis server

The analysis server produces and uploads ESAMP-style analyses to S3 and API,
it differs from calc_server.py which does not produce Analysis models.
"""

__all__ = ["makeApp"]

from uuid import UUID
from typing import Union
from fastapi import Body

from helao.helpers.premodels import Action
from helao.servers.base_api import BaseAPI
from helao.drivers.data.analysis_driver import HelaoAnalysisSyncer
from helao.helpers.config_loader import CONFIG


def makeApp(server_key):
    config = CONFIG

    app = BaseAPI(
        config=config,
        server_key=server_key,
        server_title=server_key,
        description="Analysis server",
        version=0.1,
        driver_classes=[HelaoAnalysisSyncer],
    )

    @app.post("/batch_calc_echeuvis", tags=["private"])
    async def batch_calc_echeuvis(
        sequence_uuid: str,
        plate_id: Union[int, None] = None,
        recent: bool = True,
        params: dict = {},
    ):
        """Generates ECHEUVIS stability analyses from sequence_uuid."""
        await app.driver.batch_calc_echeuvis(
            plate_id=plate_id,
            sequence_uuid=UUID(sequence_uuid),
            params=params,
            recent=recent,
        )
        return sequence_uuid

    @app.post("/batch_calc_dryuvis", tags=["private"])
    async def batch_calc_dryuvis(
        sequence_uuid: Union[str, None] = None,
        plate_id: Union[int, None] = None,
        recent: bool = True,
        params: dict = {},
    ):
        """Generates dry UVIS-T analyses from sequence_uuid."""
        await app.driver.batch_calc_dryuvis(
            plate_id=plate_id,
            sequence_uuid=UUID(sequence_uuid),
            params=params,
            recent=recent,
        )
        return sequence_uuid

    @app.post(f"/{server_key}/analyze_dryuvis", tags=["action"])
    async def analyze_dryuvis(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        sequence_uuid: str = "",
        plate_id: Union[int, None] = None,
        recent: bool = False,
        params: dict = {},
    ):
        """Generates dry UVIS-T analyses from sequence_uuid."""
        active = await app.base.setup_and_contain_action()
            
        await app.driver.batch_calc_dryuvis(
            plate_id=active.action.action_params['plate_id'],
            sequence_uuid=UUID(active.action.action_params['sequence_uuid']),
            params=active.action.action_params['params'],
            recent=active.action.action_params['recent'],
        )
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/analyze_echeuvis", tags=["action"])
    async def analyze_echeuvis(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        sequence_uuid: str = "",
        plate_id: Union[int, None] = None,
        recent: bool = False,
        params: dict = {},
    ):
        """Generates ECHEUVIS stability analyses from sequence_uuid."""
        active = await app.base.setup_and_contain_action()
            
        await app.driver.batch_calc_echeuvis(
            plate_id=active.action.action_params['plate_id'],
            sequence_uuid=UUID(active.action.action_params['sequence_uuid']),
            params=active.action.action_params['params'],
            recent=active.action.action_params['recent'],
        )
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/analyze_icpms_local", tags=["action"])
    async def analyze_icpms_local(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        sequence_zip_path: str = "",
        params: dict = {},
    ):
        """Generates ICPMS concentration analyses from sequence zip path."""
        active = await app.base.setup_and_contain_action()
            
        await app.driver.batch_calc_icpms_local(
            sequence_zip_path=active.action.action_params['sequence_zip_path'],
            params=active.action.action_params['params'],
        )
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/analyze_xrfs_local", tags=["action"])
    async def analyze_xrfs_local(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        sequence_zip_path: str = "",
        params: dict = {},
    ):
        """Generates XRFS calibration analyses from sequence zip path."""
        active = await app.base.setup_and_contain_action()
            
        await app.driver.batch_calc_xrfs_local(
            sequence_zip_path=active.action.action_params['sequence_zip_path'],
            params=active.action.action_params['params'],
        )
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post("/list_running_tasks", tags=["private"])
    def list_current_tasks():
        return list(app.driver.running_tasks.keys())

    @app.post("/list_queued_tasks", tags=["private"])
    def list_queued_tasks():
        return list(app.driver.task_set)

    return app
