"""FastAPI action server for the PAL autosampler.

Exposes the PAL hardware surface as HELAO actions: stop/kill helpers and
method dispatchers backed by configured CAM entries (``PAL_run_method``,
ANEC liquid/gas aliquoting and injection, generic GC/HPLC injections,
tray/custom transfers, archive, deepclean, dilute, autodilute). Sample
archive/database bookkeeping now lives on the standalone SAMPLE action
server.
"""

__all__ = ["makeApp"]


from fastapi import Body
from typing import Optional

from helao.core.servers.base_api import BaseAPI
from helao.core.error import ErrorCodes
from helao.core.models.hlostatus import HloStatus
from helao.core.models.file import FileConnParams
from helao.core.drivers.helao_driver import DriverResponseType
from helao.helpers.active_params import ActiveParams
from helao.helpers.executor import Executor
from ...drivers.robot.pal_driver import (
    PAL,
    Spacingmethod,
    PALtools,
    PalMicroCam,
    PALposition,
    GCsampletype,
    # SampleInheritance,
    # SampleStatus,
)
from helao.helpers.make_str_enum import make_str_enum
from helao.helpers.premodels import Action

from helao.helpers import helao_logging as logging  # get LOGGER from BaseAPI instance

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class PALJobExec(Executor):
    """Executor that submits a resolved ``PalCam`` job to the PAL driver's job-loop worker.

    Owns the ``Active`` created by the calling endpoint (K7b: the endpoint
    runs the busy/estop/no-host guard -- B4 -- BEFORE ``contain_action``, so
    a rejected call creates no artifact, then builds the ``PalCam`` via one
    of the driver's ``build_palcam_*`` helpers and calls ``contain_action``
    -- the same seam ``SM303Exec``/``CellIVExec`` use). ``_pre_exec`` hands
    the ``PalCam`` and this executor's ``Active`` to the driver's job-loop
    worker (``PAL.submit_job``); ``_poll`` reports the framework-visible
    status by watching the job's ``done`` event (the driver's job-loop
    ``finally`` stamps ``job.error`` and sets ``done`` instead of calling
    ``active.finish()`` directly -- the framework finishes the action once
    ``_poll`` reports a terminal status); ``_manual_stop`` routes an estop/
    ``/stop`` abort to the driver's synchronous ``stop()``.
    """

    def __init__(self, palcam, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.driver: PAL = self.active.driver
        self.palcam = palcam
        self.job = None

    async def _pre_exec(self) -> dict:
        self.job = await self.driver.submit_job(self.palcam, self.active)
        return {"error": self.job.error}

    async def _poll(self) -> dict:
        status = HloStatus.finished if self.job.done.is_set() else HloStatus.active
        return {"error": self.job.error, "status": status, "data": {}}

    async def _manual_stop(self) -> dict:
        resp = self.driver.stop()
        return {
            "error": (
                ErrorCodes.none
                if resp.response == DriverResponseType.success
                else ErrorCodes.critical_error
            )
        }


def makeApp(server_key) -> BaseAPI:
    """Build the BaseAPI app for the PAL autosampler.

    Reads the server's ``cams`` and ``positions`` blocks to decide which
    method endpoints to register. Custom-position endpoints typed against
    a configured custom-position enum are always available; method
    endpoints (run-method, ANEC, GC/HPLC injection, transfer, archive,
    deepclean, dilute, autodilute) are only attached when the
    corresponding CAM keys exist.

    Args:
        server_key: Unique key identifying this server in the orchestration
            group.

    Returns:
        The configured BaseAPI instance.
    """

    app = BaseAPI(
        server_key,
        server_key,
        "PAL Autosampler Server",
        version=2.0,
        driver_classes=[PAL],
    )

    _cams = app.server_params.get("cams", {})
    # _camsitems = make_str_enum("cams",{key:key for key in _cams.keys()})
    # app.base.print_message(_cams)

    if "positions" in app.server_params:
        dev_custom = app.server_params["positions"].get("custom", {})
    else:
        dev_custom = {}
    dev_customitems = make_str_enum(
        "dev_custom", {key: key for key in dev_custom.keys()}
    )

    def _pal_reject_busy(A: Action) -> Optional[dict]:
        """B4: busy/estop/no-host rejection, run BEFORE ``contain_action``.

        A rejected call must create no artifact (CARDS_REFACTOR_P4_PAL.md
        sec 3.1 warning): this mirrors the exact error codes the legacy
        ``_init_PAL_IOloop`` guard returned, just moved out of the driver.
        """
        if app.base.actionservermodel.estop:
            LOGGER.error("PAL is in estop.")
            A.error_code = ErrorCodes.estop
            return A.as_dict()
        if app.driver.sshhost is None:
            LOGGER.error("No PAL host specified.")
            A.error_code = ErrorCodes.not_available
            return A.as_dict()
        if app.driver.is_busy():
            LOGGER.error("PAL method already in progress.")
            A.error_code = ErrorCodes.in_progress
            return A.as_dict()
        return None

    async def _pal_start(A: Action, palcam) -> dict:
        """Contain the action and hand it off to a ``PALJobExec`` (K7b)."""
        active = await app.base.contain_action(
            ActiveParams(
                action=A,
                file_conn_params_dict={
                    app.base.dflt_file_conn_key(): FileConnParams(
                        file_conn_key=app.base.dflt_file_conn_key(),
                        file_type="pal_helao__file",
                    )
                },
            )
        )
        return active.start_executor(
            PALJobExec(palcam=palcam, active=active, oneoff=False)
        )

    @app.post(f"/{server_key}/stop", tags=["action"])
    async def stop():
        """Request a controlled stop on the PAL driver.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.

        Returns:
            The finished action dictionary including the driver stop result.
        """
        active = await app.base.setup_and_contain_action(action_abbr="stop")
        stop_resp = app.driver.stop()
        await active.enqueue_data_dflt(
            datadict={"stop": stop_resp.response == DriverResponseType.success}
        )
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/kill_PAL", tags=["action"])
    async def kill_PAL():
        """Kill the PAL process via the driver and record the error code.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.

        Returns:
            The finished action dictionary.
        """
        active = await app.base.setup_and_contain_action()
        error_code = await app.driver.kill_PAL()
        active.action.error_code = error_code
        await active.enqueue_data_dflt(datadict={"error_code": error_code})
        finished_action = await active.finish()
        return finished_action.as_dict()

    if _cams:

        @app.post(f"/{server_key}/PAL_run_method", tags=["action"])
        async def PAL_run_method(
            micropal: list = [
                PalMicroCam.model_validate(
                    {
                        "method": "fillfixed",
                        "tool": "LS3",
                        "volume_ul": 500,
                        "requested_source": PALposition.model_validate(
                            {
                                "position": "elec_res1",
                                "tray": None,
                                "slot": None,
                                "vial": None,
                            }
                        ),
                        "requested_dest": PALposition.model_validate(
                            {
                                "position": "lcfc_res",
                                "tray": None,
                                "slot": None,
                                "vial": None,
                            }
                        ),
                        "wash1": 0,
                        "wash2": 0,
                        "wash3": 0,
                        "wash4": 0,
                    }
                ),
                PalMicroCam.model_validate(
                    {
                        "method": "fillfixed",
                        "tool": "LS3",
                        "volume_ul": 500,
                        "requested_source": PALposition.model_validate(
                            {
                                "position": "elec_res1",
                                "tray": None,
                                "slot": None,
                                "vial": None,
                            }
                        ),
                        "requested_dest": PALposition.model_validate(
                            {
                                "position": "lcfc_res",
                                "tray": None,
                                "slot": None,
                                "vial": None,
                            }
                        ),
                        "wash1": 0,
                        "wash2": 0,
                        "wash3": 0,
                        "wash4": 0,
                    }
                ),
            ],
            totalruns: int = 1,
            # its a necessary param, but as its the only dict, it partially breaks swagger
            sampleperiod: list[float] = [0.0],
            spacingmethod: Spacingmethod = Spacingmethod.linear,
            spacingfactor: float = 1.0,
            timeoffset: float = 0.0,
        ):
            """Run an arbitrary PAL micro-method sequence.

            Each entry in ``micropal`` is a :class:`PalMicroCam` describing a
            single transfer (method, tool, volume, source/destination
            position, wash flags); the list is repeated ``totalruns`` times
            with timing controlled by ``sampleperiod``, ``spacingmethod``,
            ``spacingfactor``, and ``timeoffset``.

            Args:
                action: Action wrapper supplied by the orchestrator.
                action_version: Schema version for this endpoint.
                micropal: Ordered list of PAL micro-camera operations.
                totalruns: Number of times to repeat the micropal sequence.
                sampleperiod: Per-step delay schedule passed to the driver.
                spacingmethod: Spacing method for sampleperiod expansion.
                spacingfactor: Multiplier applied to the spacing series.
                timeoffset: Global time offset in seconds before the first run.

            Returns:
                The active action dictionary returned by the driver.
            """
            A = app.base.setup_action()
            rejected = _pal_reject_busy(A)
            if rejected is not None:
                return rejected
            palcam = app.driver.build_palcam_arbitrary(A.action_params, A.samples_in)
            return await _pal_start(A, palcam)

    if (
        "injection_custom_GC_liquid_start" in _cams
        or "injection_custom_GC_liquid_wait" in _cams
        or "injection_custom_GC_gas_start" in _cams
        or "injection_custom_GC_gas_wait" in _cams
        and "archive"
    ):

        @app.post(f"/{server_key}/PAL_ANEC_aliquot", tags=["action"])
        async def PAL_ANEC_aliquot(
            toolGC: PALtools = PALtools.HS2,
            toolarchive: PALtools = PALtools.LS3,
            source: dev_customitems = "cell1_we",
            volume_ul_GC: int = 300,
            volume_ul_archive: int = 500,
            wash1: bool = True,
            wash2: bool = True,
            wash3: bool = True,
            wash4: bool = False,
        ):
            """Aliquot from a custom position to both GC and archive sinks.

            Args:
                action: Action wrapper supplied by the orchestrator.
                action_version: Schema version for this endpoint.
                toolGC: PAL tool used for the GC injection.
                toolarchive: PAL tool used for the archive draw.
                source: Custom source position name.
                volume_ul_GC: Volume drawn for GC injection in microlitres.
                volume_ul_archive: Volume drawn for archive in microlitres.
                wash1: Whether to run wash station 1 after the operation.
                wash2: Whether to run wash station 2 after the operation.
                wash3: Whether to run wash station 3 after the operation.
                wash4: Whether to run wash station 4 after the operation.

            Returns:
                The active action dictionary returned by the driver.
            """
            A = app.base.setup_action()
            A.action_abbr = "GC_injection"
            rejected = _pal_reject_busy(A)
            if rejected is not None:
                return rejected
            palcam = app.driver.build_palcam_ANEC_aliquot(A.action_params, A.samples_in)
            return await _pal_start(A, palcam)

    if (
        "injection_custom_GC_liquid_start" in _cams
        or "injection_custom_GC_liquid_wait" in _cams
        or "injection_custom_GC_gas_start" in _cams
        or "injection_custom_GC_gas_wait" in _cams
    ):

        @app.post(f"/{server_key}/PAL_ANEC_GC", tags=["action"])
        async def PAL_ANEC_GC(
            toolGC: PALtools = PALtools.HS2,
            source: dev_customitems = "cell1_we",
            volume_ul_GC: int = 300,
        ):
            """Aliquot from a custom position straight into the GC.

            Args:
                action: Action wrapper supplied by the orchestrator.
                action_version: Schema version for this endpoint.
                toolGC: PAL tool used for the GC injection.
                source: Custom source position name.
                volume_ul_GC: Volume injected into the GC in microlitres.

            Returns:
                The active action dictionary returned by the driver.
            """
            A = app.base.setup_action()
            A.action_abbr = "GC_injection"
            rejected = _pal_reject_busy(A)
            if rejected is not None:
                return rejected
            palcam = app.driver.build_palcam_ANEC_GC(A.action_params, A.samples_in)
            return await _pal_start(A, palcam)

    if (
        "injection_tray_GC_liquid_start" in _cams
        or "injection_tray_GC_liquid_wait" in _cams
        or "injection_tray_GC_gas_start" in _cams
        or "injection_tray_GC_gas_wait" in _cams
    ):

        @app.post(f"/{server_key}/PAL_injection_tray_GC", tags=["action"])
        async def PAL_injection_tray_GC(
            startGC: bool = True,
            sampletype: GCsampletype = "liquid",
            tool: PALtools = PALtools.LS1,
            source_tray: int = 1,
            source_slot: int = 1,
            source_vial: int = 1,
            dest: dev_customitems = None,
            volume_ul: int = 2,
            wash1: bool = True,
            wash2: bool = True,
            wash3: bool = True,
            wash4: bool = False,
        ):
            """Inject a vial-tray sample into the GC.

            Args:
                action: Action wrapper supplied by the orchestrator.
                action_version: Schema version for this endpoint.
                startGC: If true, trigger the GC start signal after injection.
                sampletype: Sample phase (liquid or gas) being injected.
                tool: PAL tool used for the injection.
                source_tray: Source vial tray number.
                source_slot: Source slot within the tray.
                source_vial: Source vial index within the slot.
                dest: Custom destination port name.
                volume_ul: Volume to inject in microlitres.
                wash1: Whether to run wash station 1 after the operation.
                wash2: Whether to run wash station 2 after the operation.
                wash3: Whether to run wash station 3 after the operation.
                wash4: Whether to run wash station 4 after the operation.

            Returns:
                The active action dictionary returned by the driver.
            """
            A = app.base.setup_action()
            A.action_abbr = "GC_injection"
            rejected = _pal_reject_busy(A)
            if rejected is not None:
                return rejected
            palcam = app.driver.build_palcam_injection_tray_GC(
                A.action_params, A.samples_in
            )
            return await _pal_start(A, palcam)

    if (
        "injection_custom_GC_liquid_start" in _cams
        or "injection_custom_GC_liquid_wait" in _cams
        or "injection_custom_GC_gas_start" in _cams
        or "injection_custom_GC_gas_wait" in _cams
    ):

        @app.post(f"/{server_key}/PAL_injection_custom_GC", tags=["action"])
        async def PAL_injection_custom_GC(
            startGC: Optional[bool] = None,
            sampletype: Optional[GCsampletype] = None,
            tool: Optional[PALtools] = None,
            source: dev_customitems = None,
            dest: dev_customitems = None,
            volume_ul: int = 2,
            wash1: bool = True,
            wash2: bool = True,
            wash3: bool = True,
            wash4: bool = False,
        ):
            """Inject from a custom source position into the GC.

            Args:
                action: Action wrapper supplied by the orchestrator.
                action_version: Schema version for this endpoint.
                startGC: If true, trigger the GC start signal after injection.
                sampletype: Sample phase (liquid or gas) being injected.
                tool: PAL tool used for the injection.
                source: Custom source position name.
                dest: Custom destination port name.
                volume_ul: Volume to inject in microlitres.
                wash1: Whether to run wash station 1 after the operation.
                wash2: Whether to run wash station 2 after the operation.
                wash3: Whether to run wash station 3 after the operation.
                wash4: Whether to run wash station 4 after the operation.

            Returns:
                The active action dictionary returned by the driver.
            """
            A = app.base.setup_action()
            A.action_abbr = "GC_injection"
            rejected = _pal_reject_busy(A)
            if rejected is not None:
                return rejected
            palcam = app.driver.build_palcam_injection_custom_GC(
                A.action_params, A.samples_in
            )
            return await _pal_start(A, palcam)

    if "injection_custom_HPLC" in _cams:

        @app.post(f"/{server_key}/PAL_injection_custom_HPLC", tags=["action"])
        async def PAL_injection_custom_HPLC(
            tool: Optional[PALtools] = None,
            source: dev_customitems = None,
            dest: dev_customitems = None,
            volume_ul: int = 2,
            wash1: bool = True,
            wash2: bool = True,
            wash3: bool = True,
            wash4: bool = False,
        ):
            """Inject from a custom source into an HPLC port.

            Args:
                action: Action wrapper supplied by the orchestrator.
                action_version: Schema version for this endpoint.
                tool: PAL tool used for the injection.
                source: Custom source position name.
                dest: Custom HPLC destination port name.
                volume_ul: Volume to inject in microlitres.
                wash1: Whether to run wash station 1 after the operation.
                wash2: Whether to run wash station 2 after the operation.
                wash3: Whether to run wash station 3 after the operation.
                wash4: Whether to run wash station 4 after the operation.

            Returns:
                The active action dictionary returned by the driver.
            """
            A = app.base.setup_action()
            A.action_abbr = "HPLC_injection"
            rejected = _pal_reject_busy(A)
            if rejected is not None:
                return rejected
            palcam = app.driver.build_palcam_injection_custom_HPLC(
                A.action_params, A.samples_in
            )
            return await _pal_start(A, palcam)

    if "injection_tray_HPLC" in _cams:

        @app.post(f"/{server_key}/PAL_injection_tray_HPLC", tags=["action"])
        async def PAL_injection_tray_HPLC(
            tool: PALtools = PALtools.LS1,
            source_tray: int = 1,
            source_slot: int = 1,
            source_vial: int = 1,
            dest: dev_customitems = None,
            volume_ul: int = 25,
            wash1: bool = True,
            wash2: bool = True,
            wash3: bool = True,
            wash4: bool = False,
        ):
            """Inject a vial-tray sample into an HPLC port.

            Args:
                action: Action wrapper supplied by the orchestrator.
                action_version: Schema version for this endpoint.
                tool: PAL tool used for the injection.
                source_tray: Source vial tray number.
                source_slot: Source slot within the tray.
                source_vial: Source vial index within the slot.
                dest: Custom HPLC destination port name.
                volume_ul: Volume to inject in microlitres.
                wash1: Whether to run wash station 1 after the operation.
                wash2: Whether to run wash station 2 after the operation.
                wash3: Whether to run wash station 3 after the operation.
                wash4: Whether to run wash station 4 after the operation.

            Returns:
                The active action dictionary returned by the driver.
            """
            A = app.base.setup_action()
            A.action_abbr = "HPLC_injection"
            rejected = _pal_reject_busy(A)
            if rejected is not None:
                return rejected
            palcam = app.driver.build_palcam_injection_tray_HPLC(
                A.action_params, A.samples_in
            )
            return await _pal_start(A, palcam)

    #    if "transfer_tray_tray" in _cams:
    if "transfer_tray_tray" in _cams:

        @app.post(f"/{server_key}/PAL_transfer_tray_tray", tags=["action"])
        async def PAL_transfer_tray_tray(
            sampleperiod: list[float] = Body([0.0], embed=True),
            spacingmethod: Spacingmethod = Spacingmethod.linear,
            spacingfactor: float = 1.0,
            timeoffset: float = 0.0,
            tool: Optional[PALtools] = None,
            volume_ul: int = 2,
            source_tray: int = 1,
            source_slot: int = 1,
            source_vial: int = 1,
            dest_tray: int = 1,
            dest_slot: int = 1,
            dest_vial: int = 1,
            wash1: bool = True,
            wash2: bool = True,
            wash3: bool = True,
            wash4: bool = False,
        ):
            """Transfer ``volume_ul`` between two vial-tray positions.

            Args:
                action: Action wrapper supplied by the orchestrator.
                action_version: Schema version for this endpoint.
                sampleperiod: Per-step delay schedule passed to the driver.
                spacingmethod: Spacing method for sampleperiod expansion.
                spacingfactor: Multiplier applied to the spacing series.
                timeoffset: Global time offset in seconds before the run.
                tool: PAL tool used for the transfer.
                volume_ul: Volume to transfer in microlitres.
                source_tray: Source vial tray number.
                source_slot: Source slot within the tray.
                source_vial: Source vial index within the slot.
                dest_tray: Destination vial tray number.
                dest_slot: Destination slot within the tray.
                dest_vial: Destination vial index within the slot.
                wash1: Whether to run wash station 1 after the operation.
                wash2: Whether to run wash station 2 after the operation.
                wash3: Whether to run wash station 3 after the operation.
                wash4: Whether to run wash station 4 after the operation.

            Returns:
                The active action dictionary returned by the driver.
            """
            A = app.base.setup_action()
            A.action_abbr = "transfer"
            rejected = _pal_reject_busy(A)
            if rejected is not None:
                return rejected
            palcam = app.driver.build_palcam_transfer_tray_tray(
                A.action_params, A.samples_in
            )
            return await _pal_start(A, palcam)

    #    if "transfer_tray_custom" in _cams:
    if "transfer_tray_custom" in _cams:

        @app.post(f"/{server_key}/PAL_transfer_tray_custom", tags=["action"])
        async def PAL_transfer_tray_custom(
            sampleperiod: list[float] = Body([0.0], embed=True),
            spacingmethod: Spacingmethod = Spacingmethod.linear,
            spacingfactor: float = 1.0,
            timeoffset: float = 0.0,
            tool: Optional[PALtools] = None,
            volume_ul: int = 2,
            source_tray: int = 1,
            source_slot: int = 1,
            source_vial: int = 1,
            dest: dev_customitems = None,
            wash1: bool = True,
            wash2: bool = True,
            wash3: bool = True,
            wash4: bool = False,
        ):
            """Transfer ``volume_ul`` from a vial tray to a custom position.

            Args:
                action: Action wrapper supplied by the orchestrator.
                action_version: Schema version for this endpoint.
                sampleperiod: Per-step delay schedule passed to the driver.
                spacingmethod: Spacing method for sampleperiod expansion.
                spacingfactor: Multiplier applied to the spacing series.
                timeoffset: Global time offset in seconds before the run.
                tool: PAL tool used for the transfer.
                volume_ul: Volume to transfer in microlitres.
                source_tray: Source vial tray number.
                source_slot: Source slot within the tray.
                source_vial: Source vial index within the slot.
                dest: Custom destination position name.
                wash1: Whether to run wash station 1 after the operation.
                wash2: Whether to run wash station 2 after the operation.
                wash3: Whether to run wash station 3 after the operation.
                wash4: Whether to run wash station 4 after the operation.

            Returns:
                The active action dictionary returned by the driver.
            """
            A = app.base.setup_action()
            A.action_abbr = "transfer"
            rejected = _pal_reject_busy(A)
            if rejected is not None:
                return rejected
            palcam = app.driver.build_palcam_transfer_tray_custom(
                A.action_params, A.samples_in
            )
            return await _pal_start(A, palcam)

    #    if "transfer_custom_tray" in _cams:
    if "transfer_custom_tray" in _cams:

        @app.post(f"/{server_key}/PAL_transfer_custom_tray", tags=["action"])
        async def PAL_transfer_custom_tray(
            sampleperiod: list[float] = Body([0.0], embed=True),
            spacingmethod: Spacingmethod = Spacingmethod.linear,
            spacingfactor: float = 1.0,
            timeoffset: float = 0.0,
            tool: Optional[PALtools] = None,
            volume_ul: int = 2,
            source: dev_customitems = None,
            dest_tray: int = 1,
            dest_slot: int = 1,
            dest_vial: int = 1,
            wash1: bool = True,
            wash2: bool = True,
            wash3: bool = True,
            wash4: bool = False,
        ):
            """Transfer ``volume_ul`` from a custom position to a vial tray.

            Args:
                action: Action wrapper supplied by the orchestrator.
                action_version: Schema version for this endpoint.
                sampleperiod: Per-step delay schedule passed to the driver.
                spacingmethod: Spacing method for sampleperiod expansion.
                spacingfactor: Multiplier applied to the spacing series.
                timeoffset: Global time offset in seconds before the run.
                tool: PAL tool used for the transfer.
                volume_ul: Volume to transfer in microlitres.
                source: Custom source position name.
                dest_tray: Destination vial tray number.
                dest_slot: Destination slot within the tray.
                dest_vial: Destination vial index within the slot.
                wash1: Whether to run wash station 1 after the operation.
                wash2: Whether to run wash station 2 after the operation.
                wash3: Whether to run wash station 3 after the operation.
                wash4: Whether to run wash station 4 after the operation.

            Returns:
                The active action dictionary returned by the driver.
            """
            A = app.base.setup_action()
            A.action_abbr = "transfer"
            rejected = _pal_reject_busy(A)
            if rejected is not None:
                return rejected
            palcam = app.driver.build_palcam_transfer_custom_tray(
                A.action_params, A.samples_in
            )
            return await _pal_start(A, palcam)

    if "transfer_custom_custom" in _cams:

        @app.post(f"/{server_key}/PAL_transfer_custom_custom", tags=["action"])
        async def PAL_transfer_custom_custom(
            sampleperiod: list[float] = Body([0.0], embed=True),
            spacingmethod: Spacingmethod = Spacingmethod.linear,
            spacingfactor: float = 1.0,
            timeoffset: float = 0.0,
            tool: Optional[PALtools] = None,
            volume_ul: int = 2,
            source: dev_customitems = None,
            dest: dev_customitems = None,
            wash1: bool = True,
            wash2: bool = True,
            wash3: bool = True,
            wash4: bool = False,
        ):
            """Transfer ``volume_ul`` between two custom positions.

            Args:
                action: Action wrapper supplied by the orchestrator.
                action_version: Schema version for this endpoint.
                sampleperiod: Per-step delay schedule passed to the driver.
                spacingmethod: Spacing method for sampleperiod expansion.
                spacingfactor: Multiplier applied to the spacing series.
                timeoffset: Global time offset in seconds before the run.
                tool: PAL tool used for the transfer.
                volume_ul: Volume to transfer in microlitres.
                source: Custom source position name.
                dest: Custom destination position name.
                wash1: Whether to run wash station 1 after the operation.
                wash2: Whether to run wash station 2 after the operation.
                wash3: Whether to run wash station 3 after the operation.
                wash4: Whether to run wash station 4 after the operation.

            Returns:
                The active action dictionary returned by the driver.
            """
            A = app.base.setup_action()
            A.action_abbr = "transfer"
            rejected = _pal_reject_busy(A)
            if rejected is not None:
                return rejected
            palcam = app.driver.build_palcam_transfer_custom_custom(
                A.action_params, A.samples_in
            )
            return await _pal_start(A, palcam)

    if "archive" in _cams:

        @app.post(f"/{server_key}/PAL_archive", tags=["action"])
        async def PAL_archive(
            tool: Optional[PALtools] = None,
            source: dev_customitems = None,
            volume_ul: int = 200,
            sampleperiod: list[float] = Body([0], embed=True),
            spacingmethod: Spacingmethod = Spacingmethod.linear,
            spacingfactor: float = 1.0,
            timeoffset: float = 0.0,
            wash1: bool = False,
            wash2: bool = False,
            wash3: bool = False,
            wash4: bool = False,
        ):
            """Archive ``volume_ul`` from a custom position into storage.

            Args:
                action: Action wrapper supplied by the orchestrator.
                action_version: Schema version for this endpoint.
                tool: PAL tool used for the archive draw.
                source: Custom source position name.
                volume_ul: Volume to archive in microlitres.
                sampleperiod: Per-step delay schedule passed to the driver.
                spacingmethod: Spacing method for sampleperiod expansion.
                spacingfactor: Multiplier applied to the spacing series.
                timeoffset: Global time offset in seconds before the run.
                wash1: Whether to run wash station 1 after the operation.
                wash2: Whether to run wash station 2 after the operation.
                wash3: Whether to run wash station 3 after the operation.
                wash4: Whether to run wash station 4 after the operation.

            Returns:
                The active action dictionary returned by the driver.
            """
            A = app.base.setup_action()
            A.action_abbr = "archive"
            rejected = _pal_reject_busy(A)
            if rejected is not None:
                return rejected
            palcam = app.driver.build_palcam_archive(A.action_params, A.samples_in)
            return await _pal_start(A, palcam)

    # if "fill" in _cams:
    #     @app.post(f"/{server_key}/PAL_fill", tags=["action"])
    #     async def PAL_fill(
    #         action: Action = \
    #                 Body({}, embed=True),
    #         tool: Optional[PALtools] = None,
    #         source: dev_customitems = None,
    #         dest: dev_customitems = None,
    #         volume_ul: int = 200,
    #         wash1: bool = False,
    #         wash2: bool = False,
    #         wash3: bool = False,
    #         wash4: bool = False,
    #     ):
    #         A =  app.base.setup_action()
    #         A.action_abbr = "fill"
    #         active_dict = await app.driver.method_fill(A)
    #         return active_dict

    # if "fillfixed" in _cams:
    #     @app.post(f"/{server_key}/PAL_fillfixed", tags=["action"])
    #     async def PAL_fillfixed(
    #         action: Action = \
    #                 Body({}, embed=True),
    #         tool: Optional[PALtools] = None,
    #         source: dev_customitems = None,
    #         dest: dev_customitems = None,
    #         volume_ul: int = 200, # this value is only for exp, a fixed value is used
    #         wash1: bool = False,
    #         wash2: bool = False,
    #         wash3: bool = False,
    #         wash4: bool = False,
    #     ):
    #         A =  app.base.setup_action()
    #         A.action_abbr = "fillfixed"
    #         active_dict = await app.driver.method_fillfixed(A)
    #         return active_dict

    if "deepclean" in _cams:

        @app.post(f"/{server_key}/PAL_deepclean", tags=["action"])
        async def PAL_deepclean(
            tool: Optional[PALtools] = None,
            volume_ul: Optional[
                int
            ] = 200,  # this value is only for exp, a fixed value is used
            wash1: bool = True,
            wash2: bool = True,
            wash3: bool = True,
            wash4: bool = True,
        ):
            """Run the PAL deep-clean cycle on the chosen tool.

            Args:
                action: Action wrapper supplied by the orchestrator.
                action_version: Schema version for this endpoint.
                tool: PAL tool to clean.
                volume_ul: Wash volume reference (the driver uses a fixed
                    internal volume for the operation).
                wash1: Whether to run wash station 1.
                wash2: Whether to run wash station 2.
                wash3: Whether to run wash station 3.
                wash4: Whether to run wash station 4.

            Returns:
                The active action dictionary returned by the driver.
            """
            A = app.base.setup_action()
            A.action_abbr = "deepclean"
            rejected = _pal_reject_busy(A)
            if rejected is not None:
                return rejected
            palcam = app.driver.build_palcam_deepclean(A.action_params, A.samples_in)
            return await _pal_start(A, palcam)

    if "dilute" in _cams:

        @app.post(f"/{server_key}/PAL_dilute", tags=["action"])
        async def PAL_dilute(
            tool: Optional[PALtools] = None,
            source: dev_customitems = None,
            volume_ul: int = 200,
            dest_tray: int = 0,
            dest_slot: int = 0,
            dest_vial: int = 0,
            sampleperiod: list[float] = Body([0.0], embed=True),
            spacingmethod: Spacingmethod = Spacingmethod.linear,
            spacingfactor: float = 1.0,
            timeoffset: float = 0.0,
            wash1: bool = True,
            wash2: bool = True,
            wash3: bool = True,
            wash4: bool = True,
        ):
            """Dilute the source liquid into a specific destination vial.

            Args:
                action: Action wrapper supplied by the orchestrator.
                action_version: Schema version for this endpoint.
                tool: PAL tool used for the transfer.
                source: Custom source position name.
                volume_ul: Volume to transfer in microlitres.
                dest_tray: Destination vial tray number.
                dest_slot: Destination slot within the tray.
                dest_vial: Destination vial index within the slot.
                sampleperiod: Per-step delay schedule passed to the driver.
                spacingmethod: Spacing method for sampleperiod expansion.
                spacingfactor: Multiplier applied to the spacing series.
                timeoffset: Global time offset in seconds before the run.
                wash1: Whether to run wash station 1 after the operation.
                wash2: Whether to run wash station 2 after the operation.
                wash3: Whether to run wash station 3 after the operation.
                wash4: Whether to run wash station 4 after the operation.

            Returns:
                The active action dictionary returned by the driver.
            """
            A = app.base.setup_action()
            A.action_abbr = "dilute"
            active_dict = await app.driver.method_dilute(A)
            return active_dict

    if "autodilute" in _cams:

        @app.post(f"/{server_key}/PAL_autodilute", tags=["action"])
        async def PAL_autodilute(
            tool: Optional[PALtools] = None,
            source: dev_customitems = None,
            volume_ul: int = 200,
            sampleperiod: list[float] = Body([0.0], embed=True),
            spacingmethod: Spacingmethod = Spacingmethod.linear,
            spacingfactor: float = 1.0,
            timeoffset: float = 0.0,
            wash1: bool = True,
            wash2: bool = True,
            wash3: bool = True,
            wash4: bool = True,
        ):
            """Dilute the source liquid into a vial chosen by the driver.

            Args:
                action: Action wrapper supplied by the orchestrator.
                action_version: Schema version for this endpoint.
                tool: PAL tool used for the transfer.
                source: Custom source position name.
                volume_ul: Volume to transfer in microlitres.
                sampleperiod: Per-step delay schedule passed to the driver.
                spacingmethod: Spacing method for sampleperiod expansion.
                spacingfactor: Multiplier applied to the spacing series.
                timeoffset: Global time offset in seconds before the run.
                wash1: Whether to run wash station 1 after the operation.
                wash2: Whether to run wash station 2 after the operation.
                wash3: Whether to run wash station 3 after the operation.
                wash4: Whether to run wash station 4 after the operation.

            Returns:
                The active action dictionary returned by the driver.
            """
            A = app.base.setup_action()
            A.action_abbr = "autodilute"
            active_dict = await app.driver.method_autodilute(A)
            return active_dict

    return app
