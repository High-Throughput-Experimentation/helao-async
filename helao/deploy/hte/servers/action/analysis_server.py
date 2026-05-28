# shell: uvicorn motion_server:app --reload
"""Analysis action server.

Wraps :class:`HelaoAnalysisSyncer` and exposes endpoints that compute
ESAMP-style ``Analysis`` records (UVIS, ICPMS, XRFS) from prior HELAO
sequences and synchronise them to S3 / the analysis API. Distinct from
``calc_server`` which performs in-sequence calculations without producing
:class:`Analysis` models.
"""

__all__ = ["makeApp"]

from uuid import UUID
from typing import Union
from fastapi import Body

from helao.helpers.premodels import Action
from helao.core.servers.base_api import BaseAPI
from ...drivers.data.analysis_driver import (
    HelaoAnalysisSyncer,
    LocalAnalysisExecutor,
    XrfsAnalysis,
    IcpmsAnalysis,
)


def makeApp(server_key) -> BaseAPI:
    """Build the analysis FastAPI app.

    Constructs a :class:`BaseAPI` backed by :class:`HelaoAnalysisSyncer` and
    registers public action endpoints (``analyze_*``) as well as private
    endpoints (``batch_calc_*``, ``list_running_tasks``, ``list_queued_tasks``)
    used by the syncer.

    Args:
        server_key: Key identifying this server in the orchestration group.

    Returns:
        The configured :class:`BaseAPI` application.
    """

    app = BaseAPI(
        server_key=server_key,
        server_title=server_key,
        description="Analysis server",
        version=0.1,
        driver_classes=[HelaoAnalysisSyncer],
    )
    app.driver: HelaoAnalysisSyncer  # type hint for driver attribute

    @app.post("/batch_calc_echeuvis", tags=["private"])
    async def batch_calc_echeuvis(
        sequence_uuid: str,
        plate_id: Union[int, None] = None,
        recent: bool = True,
        params: dict = {},
    ) -> str:
        """Generate ECHEUVIS stability analyses for actions in ``sequence_uuid``."""
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
    ) -> Union[str, None]:
        """Generate dry UVIS-T analyses for actions in ``sequence_uuid``."""
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
        """Action endpoint: generate dry UVIS-T analyses for a prior sequence.

        Wraps ``batch_calc_dryuvis`` inside an active action so the run is
        recorded in HELAO's action history.
        """
        active = await app.base.setup_and_contain_action()

        await app.driver.batch_calc_dryuvis(
            plate_id=active.action.action_params["plate_id"],
            sequence_uuid=UUID(active.action.action_params["sequence_uuid"]),
            params=active.action.action_params["params"],
            recent=active.action.action_params["recent"],
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
        """Action endpoint: generate ECHEUVIS stability analyses for a prior sequence.

        Wraps ``batch_calc_echeuvis`` inside an active action so the run is
        recorded in HELAO's action history.
        """
        active = await app.base.setup_and_contain_action()

        await app.driver.batch_calc_echeuvis(
            plate_id=active.action.action_params["plate_id"],
            sequence_uuid=UUID(active.action.action_params["sequence_uuid"]),
            params=active.action.action_params["params"],
            recent=active.action.action_params["recent"],
            analysis_action_uuid=active.action.action_uuid,
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
        """Action endpoint: run a local ICPMS concentration analysis on a sequence zip.

        Starts a :class:`LocalAnalysisExecutor` bound to :class:`IcpmsAnalysis`.
        """
        active = await app.base.setup_and_contain_action()

        executor = LocalAnalysisExecutor(
            analysis_class=IcpmsAnalysis, active=active, oneoff=True, concurrent=True
        )
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post(f"/{server_key}/analyze_xrfs_local", tags=["action"])
    async def analyze_xrfs_local(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        sequence_zip_path: str = "",
        params: dict = {},
    ):
        """Action endpoint: run a local XRFS calibration analysis on a sequence zip.

        Starts a :class:`LocalAnalysisExecutor` bound to :class:`XrfsAnalysis`.
        """
        active = await app.base.setup_and_contain_action()

        executor = LocalAnalysisExecutor(
            analysis_class=XrfsAnalysis, active=active, oneoff=True, concurrent=True
        )
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post("/list_running_tasks", tags=["private"])
    def list_current_tasks() -> list:
        """Return identifiers of analysis tasks currently executing in the syncer."""
        return list(app.driver.running_tasks.keys())

    @app.post("/list_queued_tasks", tags=["private"])
    def list_queued_tasks() -> list:
        """Return identifiers of analysis tasks queued but not yet running."""
        return list(app.driver.task_set)

    return app
