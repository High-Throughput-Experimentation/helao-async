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
    async def batch_calc_echeuvis(plate_id: int, sequence_uuid: str, params: dict):
        """Pushes HELAO data to S3/API and moves files to RUNS_SYNCED."""
        await app.driver.batch_calc_echeuvis(plate_id, UUID(sequence_uuid), params)
        return sequence_uuid

    return app
