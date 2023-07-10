# shell: uvicorn motion_server:app --reload
""" Analysis server

The analysis server produces and uploads ESAMP-style analyses to S3 and API,
it differs from calc_server.py which does not produce Analysis models.
"""

__all__ = ["makeApp"]

from uuid import UUID

from helao.servers.base import HelaoBase
from helao.drivers.data.analysis_driver import HelaoAnalysisSyncer
from helao.drviers.data.analysis.eche_uvis_stability import EcheUvisLoader
from helao.helpers.config_loader import config_loader


def makeApp(confPrefix, server_key, helao_root):
    config = config_loader(confPrefix, helao_root)

    # declare global loader for analysis models used by driver.batch_* methods
    global EUL
    EUL = EcheUvisLoader(
        config["servers"][server_key]["params"]["env_file"],
        cache_s3=True,
        cache_json=True,
    )

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
        """Generates ECHEUVIS stability analyses from sequence_uuid."""
        await app.driver.batch_calc_echeuvis(plate_id, UUID(sequence_uuid), params)
        return sequence_uuid

    @app.post("/batch_calc_echeuvis", tags=["private"])
    async def batch_calc_dryuvis(plate_id: int, sequence_uuid: str, params: dict):
        """Generates dry UVIS-T analyses from sequence_uuid."""
        await app.driver.batch_calc_dryuvis(plate_id, UUID(sequence_uuid), params)
        return sequence_uuid

    return app
