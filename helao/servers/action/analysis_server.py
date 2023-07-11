# shell: uvicorn motion_server:app --reload
""" Analysis server

The analysis server produces and uploads ESAMP-style analyses to S3 and API,
it differs from calc_server.py which does not produce Analysis models.
"""

__all__ = ["makeApp"]

from uuid import UUID

from helao.servers.base import HelaoBase
from helao.drivers.data.analysis_driver import HelaoAnalysisSyncer
from helao.helpers.config_loader import config_loader


def makeApp(confPrefix, server_key, helao_root):
    config = config_loader(confPrefix, helao_root)

    app = HelaoBase(
        config=config,
        server_key=server_key,
        server_title=server_key,
        description="Analysis server",
        version=0.1,
        driver_class=HelaoAnalysisSyncer,
    )

    @app.post("/batch_calc_echeuvis", tags=["private"])
    async def batch_calc_echeuvis(
        plate_id: int, sequence_uuid: str, recent: bool = True, params: dict = {}
    ):
        """Generates ECHEUVIS stability analyses from sequence_uuid."""
        await app.driver.batch_calc_echeuvis(
            plate_id=plate_id,
            sequence_uuid=UUID(sequence_uuid),
            params=params,
            recent=recent,
        )
        return sequence_uuid

    @app.post("/batch_calc_echeuvis", tags=["private"])
    async def batch_calc_dryuvis(
        plate_id: int, sequence_uuid: str, recent: bool = True, params: dict = {}
    ):
        """Generates dry UVIS-T analyses from sequence_uuid."""
        await app.driver.batch_calc_dryuvis(
            plate_id=plate_id,
            sequence_uuid=UUID(sequence_uuid),
            params=params,
            recent=recent,
        )
        return sequence_uuid

    @app.post("/list_running_tasks", tags=["private"])
    def list_current_tasks():
        return list(app.driver.running_tasks.keys())

    @app.post("/list_queued_tasks", tags=["private"])
    def list_queued_tasks():
        return list(app.driver.task_set)
    
    return app
