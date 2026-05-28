"""FastAPI action server for the PAL autosampler.

Exposes the full PAL workflow surface as HELAO actions: stop/kill helpers,
method dispatchers backed by configured CAM entries (``PAL_run_method``,
ANEC liquid/gas aliquoting and injection, generic GC/HPLC injections,
tray/custom transfers, archive, deepclean, dilute, autodilute), and the
sample archive/database endpoints that load and unload trays and custom
positions, add liquids/gases, query samples, export tray data, and create
new sample rows.
"""

__all__ = ["makeApp"]


from socket import gethostname
from time import strftime

from fastapi import Body, Query
from typing import Optional, List, Union

from helao.core.servers.base_api import BaseAPI
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
from ...drivers.data.archive_driver import ScanDirection, ScanOperator

from helao.core.models.sample import (
    SampleType,
    LiquidSample,
    GasSample,
    AssemblySample,
    LiquidSample,
    GasSample,
    SolidSample,
    NoneSample,
    NoneSample,
    SolidSample,
)
from helao.core.models.data import DataModel
from helao.helpers.make_str_enum import make_str_enum
from helao.helpers.premodels import Action

from helao.helpers import helao_logging as logging  # get LOGGER from BaseAPI instance

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


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

    @app.post(f"/{server_key}/stop", tags=["action"])
    async def stop(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
    ):
        """Request a controlled stop on the PAL driver.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.

        Returns:
            The finished action dictionary including the driver stop result.
        """
        active = await app.base.setup_and_contain_action(action_abbr="stop")
        await active.enqueue_data_dflt(datadict={"stop": await app.driver.stop()})
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/kill_PAL", tags=["action"])
    async def kill_PAL(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
    ):
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

    @app.post(f"/{server_key}/convert_v1DB", tags=["action"])
    async def convert_v1DB(action: Action = Body({}, embed=True)) -> dict:
        """Convert the legacy liquid JSON database to the SQLite schema.

        Args:
            action: Action wrapper supplied by the orchestrator.

        Returns:
            An empty dictionary once the migration completes.
        """
        # await app.driver.convert_oldDB_to_sqllite()
        await app.driver.archive.unified_db.liquidAPI.old_jsondb_to_sqlitedb()
        return {}

    if _cams:

        @app.post(f"/{server_key}/PAL_run_method", tags=["action"])
        async def PAL_run_method(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            micropal: list = [
                PalMicroCam(
                    **{
                        "method": "fillfixed",
                        "tool": "LS3",
                        "volume_ul": 500,
                        "requested_source": PALposition(
                            **{
                                "position": "elec_res1",
                                "tray": None,
                                "slot": None,
                                "vial": None,
                            }
                        ),
                        "requested_dest": PALposition(
                            **{
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
                PalMicroCam(
                    **{
                        "method": "fillfixed",
                        "tool": "LS3",
                        "volume_ul": 500,
                        "requested_source": PALposition(
                            **{
                                "position": "elec_res1",
                                "tray": None,
                                "slot": None,
                                "vial": None,
                            }
                        ),
                        "requested_dest": PALposition(
                            **{
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
            sampleperiod: List[float] = [0.0],
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
            active_dict = await app.driver.method_arbitrary(A)
            return active_dict

    if (
        "injection_custom_GC_liquid_start" in _cams
        or "injection_custom_GC_liquid_wait" in _cams
        or "injection_custom_GC_gas_start" in _cams
        or "injection_custom_GC_gas_wait" in _cams
        and "archive"
    ):

        @app.post(f"/{server_key}/PAL_ANEC_aliquot", tags=["action"])
        async def PAL_ANEC_aliquot(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
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
            active_dict = await app.driver.method_ANEC_aliquot(A)
            return active_dict

    if (
        "injection_custom_GC_liquid_start" in _cams
        or "injection_custom_GC_liquid_wait" in _cams
        or "injection_custom_GC_gas_start" in _cams
        or "injection_custom_GC_gas_wait" in _cams
    ):

        @app.post(f"/{server_key}/PAL_ANEC_GC", tags=["action"])
        async def PAL_ANEC_GC(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
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
            active_dict = await app.driver.method_ANEC_GC(A)
            return active_dict

    if (
        "injection_tray_GC_liquid_start" in _cams
        or "injection_tray_GC_liquid_wait" in _cams
        or "injection_tray_GC_gas_start" in _cams
        or "injection_tray_GC_gas_wait" in _cams
    ):

        @app.post(f"/{server_key}/PAL_injection_tray_GC", tags=["action"])
        async def PAL_injection_tray_GC(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
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
            active_dict = await app.driver.method_injection_tray_GC(A)
            return active_dict

    if (
        "injection_custom_GC_liquid_start" in _cams
        or "injection_custom_GC_liquid_wait" in _cams
        or "injection_custom_GC_gas_start" in _cams
        or "injection_custom_GC_gas_wait" in _cams
    ):

        @app.post(f"/{server_key}/PAL_injection_custom_GC", tags=["action"])
        async def PAL_injection_custom_GC(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
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
            active_dict = await app.driver.method_injection_custom_GC(A)
            return active_dict

    if "injection_custom_HPLC" in _cams:

        @app.post(f"/{server_key}/PAL_injection_custom_HPLC", tags=["action"])
        async def PAL_injection_custom_HPLC(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
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
            active_dict = await app.driver.method_injection_custom_HPLC(A)
            return active_dict

    if "injection_tray_HPLC" in _cams:

        @app.post(f"/{server_key}/PAL_injection_tray_HPLC", tags=["action"])
        async def PAL_injection_tray_HPLC(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
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
            active_dict = await app.driver.method_injection_tray_HPLC(A)
            return active_dict

    #    if "transfer_tray_tray" in _cams:
    if "transfer_tray_tray" in _cams:

        @app.post(f"/{server_key}/PAL_transfer_tray_tray", tags=["action"])
        async def PAL_transfer_tray_tray(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            sampleperiod: List[float] = Body([0.0], embed=True),
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
            active_dict = await app.driver.method_transfer_tray_tray(A)
            return active_dict

    #    if "transfer_tray_custom" in _cams:
    if "transfer_tray_custom" in _cams:

        @app.post(f"/{server_key}/PAL_transfer_tray_custom", tags=["action"])
        async def PAL_transfer_tray_custom(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            sampleperiod: List[float] = Body([0.0], embed=True),
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
            active_dict = await app.driver.method_transfer_tray_custom(A)
            return active_dict

    #    if "transfer_custom_tray" in _cams:
    if "transfer_custom_tray" in _cams:

        @app.post(f"/{server_key}/PAL_transfer_custom_tray", tags=["action"])
        async def PAL_transfer_custom_tray(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            sampleperiod: List[float] = Body([0.0], embed=True),
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
            active_dict = await app.driver.method_transfer_custom_tray(A)
            return active_dict

    if "transfer_custom_custom" in _cams:

        @app.post(f"/{server_key}/PAL_transfer_custom_custom", tags=["action"])
        async def PAL_transfer_custom_custom(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            sampleperiod: List[float] = Body([0.0], embed=True),
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
            active_dict = await app.driver.method_transfer_custom_custom(A)
            return active_dict

    if "archive" in _cams:

        @app.post(f"/{server_key}/PAL_archive", tags=["action"])
        async def PAL_archive(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            tool: Optional[PALtools] = None,
            source: dev_customitems = None,
            volume_ul: int = 200,
            sampleperiod: List[float] = Body([0], embed=True),
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
            active_dict = await app.driver.method_archive(A)
            return active_dict

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
            action: Action = Body({}, embed=True),
            action_version: int = 1,
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
            active_dict = await app.driver.method_deepclean(A)
            return active_dict

    if "dilute" in _cams:

        @app.post(f"/{server_key}/PAL_dilute", tags=["action"])
        async def PAL_dilute(
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            tool: Optional[PALtools] = None,
            source: dev_customitems = None,
            volume_ul: int = 200,
            dest_tray: int = 0,
            dest_slot: int = 0,
            dest_vial: int = 0,
            sampleperiod: List[float] = Body([0.0], embed=True),
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
            action: Action = Body({}, embed=True),
            action_version: int = 1,
            tool: Optional[PALtools] = None,
            source: dev_customitems = None,
            volume_ul: int = 200,
            sampleperiod: List[float] = Body([0.0], embed=True),
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

    @app.post(f"/{server_key}/archive_tray_query_sample", tags=["action"])
    async def archive_tray_query_sample(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        tray: Optional[int] = None,
        slot: Optional[int] = None,
        vial: Optional[int] = None,
    ):
        """Look up the sample at a tray/slot/vial location.

        The retrieved sample is appended to ``samples_in`` and a data row
        with the sample dict and error code is enqueued; the sample dict is
        also mirrored into ``action_params['_fast_samples_in']``.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.
            tray: Vial tray number.
            slot: Slot within the tray.
            vial: Vial index within the slot.

        Returns:
            The finished action dictionary.
        """
        active = await app.base.setup_and_contain_action(action_abbr="query_sample")
        error_code, sample = await app.driver.archive.tray_query_sample(
            tray=active.action.action_params["tray"],
            slot=active.action.action_params["slot"],
            vial=active.action.action_params["vial"],
        )
        active.action.error_code = error_code
        await active.append_sample(samples=[sample], IO="in")
        datadict = {"sample": sample.as_dict(), "error_code": error_code}
        datamodel = DataModel(data={active.base.dflt_file_conn_key(): datadict})
        active.action.action_params.update({"_fast_samples_in": [sample.as_dict()]})
        active.enqueue_data_nowait(datamodel, action=active.action)
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/archive_tray_unloadall", tags=["action"])
    async def archive_tray_unloadall(action: Action = Body({}, embed=True)):
        """Unload every position from every tray and reset the vial table.

        The previously loaded samples are appended to ``samples_in`` and the
        outgoing samples (with destruction/keep handling) to ``samples_out``;
        the resulting tray map is enqueued in the action data.

        Args:
            action: Action wrapper supplied by the orchestrator.

        Returns:
            The finished action dictionary.
        """
        active = await app.base.setup_and_contain_action(action_abbr="unload_sample")
        (
            unloaded,
            samples_in,
            samples_out,
            tray_dict,
        ) = await app.driver.archive.tray_unloadall(**active.action.action_params)
        await active.append_sample(samples=samples_in, IO="in")
        await active.append_sample(samples=samples_out, IO="out")
        datadict = {"unloaded": unloaded, "tray_dict": tray_dict}
        datamodel = DataModel(data={active.base.dflt_file_conn_key(): datadict})
        active.enqueue_data_nowait(datamodel, action=active.action)
        finished_act = await active.finish()
        return finished_act.as_dict()

    @app.post(f"/{server_key}/archive_tray_load", tags=["action"])
    async def archive_tray_load(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        load_sample_in: Union[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample],
            dict,
        ] = Body(
            LiquidSample(**{"sample_no": 1, "machine_name": gethostname().lower()}),
            embed=True,
        ),
        tray: Optional[int] = None,
        slot: Optional[int] = None,
        vial: Optional[int] = None,
    ):
        """Load a sample into a specific tray/slot/vial position.

        On a successful load the sample is appended to ``samples_in``; the
        error code and resulting sample dict are enqueued in the action data.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.
            load_sample_in: The sample (or sample dict) to load.
            tray: Destination vial tray number.
            slot: Destination slot within the tray.
            vial: Destination vial index within the slot.

        Returns:
            The finished action dictionary.
        """
        active = await app.base.setup_and_contain_action(
            action_abbr="load_sample",
        )
        error_code, loaded_sample = await app.driver.archive.tray_load(
            **active.action.action_params
        )
        active.action.error_code = error_code
        if loaded_sample != NoneSample():
            await active.append_sample(samples=[loaded_sample], IO="in")
        datadict = {"error_code": error_code, "sample": loaded_sample.as_dict()}
        datamodel = DataModel(data={active.base.dflt_file_conn_key(): datadict})
        active.enqueue_data_nowait(datamodel, action=active.action)
        finished_act = await active.finish()
        return finished_act.as_dict()

    @app.post(f"/{server_key}/archive_tray_unload", tags=["action"])
    async def archive_tray_unload(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        tray: Optional[int] = None,
        slot: Optional[int] = None,
    ):
        """Unload one tray (optionally one slot) and update the vial table.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.
            tray: Vial tray number to unload.
            slot: Optional slot filter within the tray.

        Returns:
            The finished action dictionary.
        """
        active = await app.base.setup_and_contain_action(action_abbr="unload_sample")
        (
            unloaded,
            samples_in,
            samples_out,
            tray_dict,
        ) = await app.driver.archive.tray_unload(**active.action.action_params)
        await active.append_sample(samples=samples_in, IO="in")
        await active.append_sample(samples=samples_out, IO="out")
        datadict = {"unloaded": unloaded, "tray_dict": tray_dict}
        datamodel = DataModel(data={active.base.dflt_file_conn_key(): datadict})
        active.enqueue_data_nowait(datamodel, action=active.action)
        finished_act = await active.finish()
        return finished_act.as_dict()

    @app.post(f"/{server_key}/archive_tray_new_position", tags=["action"])
    async def archive_tray_new(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        req_vol: Optional[float] = None,
    ):
        """Find an empty vial position large enough to hold a given volume.

        Among empty vials, returns the one with the smallest capacity that
        still fits ``req_vol``.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.
            req_vol: Required volume in millilitres; ``None`` returns the
                first empty vial regardless of size.

        Returns:
            The finished action dictionary including the selected tray/slot
            /vial location.
        """
        active = await app.base.setup_and_contain_action()
        datadict = await app.driver.archive.tray_new_position(
            **active.action.action_params
        )
        datamodel = DataModel(data={active.base.dflt_file_conn_key(): datadict})
        active.enqueue_data_nowait(datamodel, action=active.action)
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/archive_tray_update_position", tags=["action"])
    async def archive_tray_update_position(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        sample: Union[
            AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample
        ] = Body(
            LiquidSample(**{"sample_no": 1, "machine_name": gethostname().lower()}),
            embed=True,
        ),
        tray: Optional[int] = None,
        slot: Optional[int] = None,
        vial: Optional[int] = None,
    ):
        """Write a sample reference into the driver's vial table.

        The update succeeds only if the target tray/slot/vial was empty.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.
            sample: Sample reference to attach to the position.
            tray: Vial tray number.
            slot: Slot within the tray.
            vial: Vial index within the slot.

        Returns:
            The finished action dictionary; the enqueued data dict contains
            ``update`` set to ``True`` if the position was empty, else
            ``False``.
        """
        active = await app.base.setup_and_contain_action()
        datadict = {
            "update": await app.driver.archive.tray_update_position(
                **active.action.action_params
            ),
        }
        datamodel = DataModel(data={active.base.dflt_file_conn_key(): datadict})
        active.enqueue_data_nowait(datamodel, action=active.action)
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/archive_tray_export_json", tags=["action"])
    async def archive_tray_export_json(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        tray: Optional[int] = None,
        slot: Optional[int] = None,
    ):
        """Export the current vial table for a tray/slot as a JSON data row.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.
            tray: Vial tray number to export.
            slot: Optional slot filter within the tray.

        Returns:
            The finished action dictionary.
        """
        active = await app.base.setup_and_contain_action(
            action_abbr="traytojson",
            file_type="palvialtable_helao__file",
        )
        datadict = await app.driver.archive.tray_export_json(
            **active.action.action_params
        )
        datamodel = DataModel(data={active.base.dflt_file_conn_key(): datadict})
        active.enqueue_data_nowait(datamodel, action=active.action)
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/archive_tray_export_icpms", tags=["action"])
    async def archive_tray_export_icpms(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        tray: Optional[int] = None,
        slot: Optional[int] = None,
        survey_runs: Optional[int] = None,
        main_runs: Optional[int] = None,
        rack: Optional[int] = None,
        dilution_factor: Optional[float] = None,
    ):
        """Export a tray/slot in the ICP-MS sample-list format.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.
            tray: Vial tray number to export.
            slot: Optional slot filter within the tray.
            survey_runs: Number of ICP-MS survey runs per vial.
            main_runs: Number of ICP-MS main runs per vial.
            rack: ICP-MS rack number to assign.
            dilution_factor: Dilution factor recorded in the sample list.

        Returns:
            The finished action dictionary.
        """
        active = await app.base.setup_and_contain_action(
            action_abbr="traytoicpms",
        )
        await app.driver.archive.tray_export_icpms(
            tray=active.action.action_params.get("tray", None),
            slot=active.action.action_params.get("slot", None),
            myactive=active,
            survey_runs=active.action.action_params.get("survey_runs", None),
            main_runs=active.action.action_params.get("main_runs", None),
            rack=active.action.action_params.get("rack", None),
            dilution_factor=active.action.action_params.get("dilution_factor", None),
        )
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/archive_tray_export_csv", tags=["action"])
    async def archive_tray_export_csv(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        tray: Optional[int] = None,
        slot: Optional[int] = None,
    ):
        """Export a tray/slot vial table as CSV.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.
            tray: Vial tray number to export.
            slot: Optional slot filter within the tray.

        Returns:
            The finished action dictionary.
        """
        active = await app.base.setup_and_contain_action(
            action_abbr="traytocsv",
        )

        await app.driver.archive.tray_export_csv(
            tray=active.action.action_params.get("tray", None),
            slot=active.action.action_params.get("slot", None),
            myactive=active,
        )
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/archive_custom_load_solid", tags=["action"])
    async def archive_custom_load_solid(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        custom: dev_customitems = None,
        sample_no: int = 1,
        plate_id: int = 1,
    ):
        """Load a :class:`SolidSample` reference into a custom position.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.
            custom: Custom position name.
            sample_no: Sample number on the referenced plate.
            plate_id: Plate id containing the solid sample.

        Returns:
            The finished action dictionary.
        """
        active = await app.base.setup_and_contain_action(
            action_abbr="load_sample",
        )
        active.action.action_params["load_sample_in"] = SolidSample(
            **active.action.action_params
        )
        loaded, loaded_sample, customs_dict = await app.driver.archive.custom_load(
            **active.action.action_params
        )
        if loaded:
            await active.append_sample(samples=[loaded_sample], IO="in")
        datadict = {"loaded": loaded, "customs_dict": customs_dict}
        datamodel = DataModel(data={active.base.dflt_file_conn_key(): datadict})
        active.enqueue_data_nowait(datamodel, action=active.action)
        finished_act = await active.finish()
        return finished_act.as_dict()

    @app.post(f"/{server_key}/archive_custom_load", tags=["action"])
    async def archive_custom_load(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        custom: dev_customitems = None,
        load_sample_in: Union[
            AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample
        ] = Body(
            LiquidSample(**{"sample_no": 1, "machine_name": gethostname().lower()}),
            embed=True,
        ),
    ):
        """Load a sample reference into a custom position.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.
            custom: Custom position name.
            load_sample_in: Sample to attach to the position; defaults to a
                bare local liquid sample reference.

        Returns:
            The finished action dictionary.
        """
        active = await app.base.setup_and_contain_action(
            action_abbr="load_sample",
        )
        loaded, loaded_sample, customs_dict = await app.driver.archive.custom_load(
            **active.action.action_params
        )
        if loaded:
            await active.append_sample(samples=[loaded_sample], IO="in")
        datadict = {"loaded": loaded, "customs_dict": customs_dict}
        datamodel = DataModel(data={active.base.dflt_file_conn_key(): datadict})
        active.enqueue_data_nowait(datamodel, action=active.action)
        finished_act = await active.finish()
        return finished_act.as_dict()

    @app.post(f"/{server_key}/archive_custom_unload", tags=["action"])
    async def archive_custom_unload(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        custom: dev_customitems = None,
        destroy_liquid: bool = False,
        destroy_gas: bool = False,
        destroy_solid: bool = False,
        keep_liquid: bool = False,
        keep_solid: bool = False,
        keep_gas: bool = False,
    ):
        """Unload a single custom position with phase-specific keep/destroy flags.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.
            custom: Custom position name.
            destroy_liquid: Destroy the liquid phase on unload.
            destroy_gas: Destroy the gas phase on unload.
            destroy_solid: Destroy the solid phase on unload.
            keep_liquid: Keep the liquid phase after unload.
            keep_solid: Keep the solid phase after unload.
            keep_gas: Keep the gas phase after unload.

        Returns:
            The finished action dictionary.
        """
        active = await app.base.setup_and_contain_action(
            action_abbr="unload_sample",
        )
        (
            unloaded,
            samples_in,
            samples_out,
            customs_dict,
        ) = await app.driver.archive.custom_unload(
            **active.action.action_params, action=active.action
        )
        await active.append_sample(samples=samples_in, IO="in")
        await active.append_sample(samples=samples_out, IO="out")
        datadict = {"unloaded": unloaded, "customs_dict": customs_dict}
        datamodel = DataModel(data={active.base.dflt_file_conn_key(): datadict})
        active.enqueue_data_nowait(datamodel, action=active.action)
        finished_act = await active.finish()
        return finished_act.as_dict()

    @app.post(f"/{server_key}/archive_custom_unloadall", tags=["action"])
    async def archive_custom_unloadall(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        destroy_liquid: bool = False,
        destroy_gas: bool = False,
        destroy_solid: bool = False,
        keep_liquid: bool = False,
        keep_solid: bool = False,
        keep_gas: bool = False,
    ):
        """Unload every custom position with phase-specific keep/destroy flags.

        Also stashes the first unloaded solid and the first unloaded liquid
        (and that liquid's volume) into ``action_params`` for downstream
        consumers.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.
            destroy_liquid: Destroy the liquid phase on unload.
            destroy_gas: Destroy the gas phase on unload.
            destroy_solid: Destroy the solid phase on unload.
            keep_liquid: Keep the liquid phase after unload.
            keep_solid: Keep the solid phase after unload.
            keep_gas: Keep the gas phase after unload.

        Returns:
            The finished action dictionary.
        """
        active = await app.base.setup_and_contain_action(
            action_abbr="unload_sample",
        )
        (
            unloaded,
            samples_in,
            samples_out,
            customs_dict,
        ) = await app.driver.archive.custom_unloadall(
            **active.action.action_params, action=active.action
        )
        await active.append_sample(samples=samples_in, IO="in")
        await active.append_sample(samples=samples_out, IO="out")
        await active.enqueue_data_dflt(
            datadict={"unloaded": unloaded, "customs_dict": customs_dict}
        )
        unloaded_solids = [s for s in samples_in if s.sample_type == SampleType.solid]
        # print(unloaded_solids)
        unloaded_liquids = [s for s in samples_in if s.sample_type == SampleType.liquid]
        # print(unloaded_liquids)
        first_unloaded_solid = unloaded_solids[0].as_dict() if unloaded_solids else None
        first_unloaded_liquid = (
            unloaded_liquids[0].as_dict() if unloaded_liquids else None
        )
        if first_unloaded_liquid is None:
            unloaded_vol = 0
        else:
            unloaded_vol = first_unloaded_liquid["volume_ml"]
        active.action.action_params.update({"_unloaded_solid": first_unloaded_solid})
        active.action.action_params.update({"_unloaded_liquid": first_unloaded_liquid})
        active.action.action_params.update({"_unloaded_liquid_vol": unloaded_vol})
        finished_act = await active.finish()
        return finished_act.as_dict()

    @app.post(f"/{server_key}/archive_custom_query_sample", tags=["action"])
    async def archive_custom_query_sample(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        custom: dev_customitems = None,
    ):
        """Look up the sample currently loaded at a custom position.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.
            custom: Custom position name.

        Returns:
            The finished action dictionary; the sample dict is mirrored into
            ``action_params['_fast_samples_in']``.
        """
        active = await app.base.setup_and_contain_action(
            action_abbr="query_sample",
        )
        error_code, sample = await app.driver.archive.custom_query_sample(
            **active.action.action_params
        )
        active.action.error_code = error_code
        await active.append_sample(samples=[sample], IO="in")
        datadict = {"sample": sample.as_dict(), "error_code": error_code}
        active.action.action_params.update({"_fast_samples_in": [sample.as_dict()]})
        datamodel = DataModel(data={active.base.dflt_file_conn_key(): datadict})
        active.enqueue_data_nowait(datamodel, action=active.action)
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/archive_custom_add_liquid", tags=["action"])
    async def archive_custom_add_liquid(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        custom: dev_customitems = None,
        source_liquid_in: LiquidSample = Body(
            LiquidSample(**{"sample_no": 1, "machine_name": gethostname().lower()}),
            embed=True,
        ),
        volume_ml: float = 0.0,
        combine_liquids: bool = False,
        dilute_liquids: bool = True,
    ):
        """Add ``volume_ml`` of ``source_liquid_in`` to a custom position.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.
            custom: Custom position where liquid will be added.
            source_liquid_in: Liquid sample from which volume is drawn.
            volume_ml: Volume to add in millilitres.
            combine_liquids: When true, merge the existing custom liquid and
                ``source_liquid_in`` into a new combined liquid.
            dilute_liquids: When true, compute a dilution factor; use
                together with ``combine_liquids``.

        Returns:
            The finished action dictionary.
        """

        active = await app.base.setup_and_contain_action(
            action_abbr="add_liquid",
        )
        (
            error_code,
            samples_in,
            samples_out,
        ) = await app.driver.archive.custom_add_liquid(
            custom=active.action.action_params["custom"],
            source_liquid_in=active.action.action_params["source_liquid_in"],
            volume_ml=active.action.action_params["volume_ml"],
            combine_liquids=active.action.action_params["combine_liquids"],
            dilute_liquids=active.action.action_params["dilute_liquids"],
            action=active.action,
        )
        active.action.error_code = error_code
        await active.append_sample(samples=samples_in, IO="in")
        await active.append_sample(samples=samples_out, IO="out")
        datadict = {"error_code": error_code}
        datamodel = DataModel(data={active.base.dflt_file_conn_key(): datadict})
        active.enqueue_data_nowait(datamodel, action=active.action)
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/archive_custom_add_gas", tags=["action"])
    async def archive_custom_add_gas(
        action: Action = Body({}, embed=True),
        action_version: int = 2,
        custom: dev_customitems = None,
        source_gas_in: GasSample = Body(
            GasSample(**{"sample_no": 1, "machine_name": gethostname().lower()}),
            embed=True,
        ),
        volume_ml: float = 0.0,
        combine_gases: bool = False,
        dilute_gases: bool = True,
    ):
        """Add ``volume_ml`` of ``source_gas_in`` to a custom position.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.
            custom: Custom position where gas will be added.
            source_gas_in: Gas sample from which volume is drawn.
            volume_ml: Volume to add in millilitres.
            combine_gases: When true, merge the existing custom gas and
                ``source_gas_in`` into a new combined gas.
            dilute_gases: When true, compute a dilution factor; use together
                with ``combine_gases``.

        Returns:
            The finished action dictionary.
        """

        active = await app.base.setup_and_contain_action(
            action_abbr="add_gas",
        )
        (
            error_code,
            samples_in,
            samples_out,
        ) = await app.driver.archive.custom_add_gas(
            custom=active.action.action_params["custom"],
            source_gas_in=active.action.action_params["source_gas_in"],
            volume_ml=active.action.action_params["volume_ml"],
            combine_gases=active.action.action_params["combine_gases"],
            dilute_gases=active.action.action_params["dilute_gases"],
            action=active.action,
        )
        active.action.error_code = error_code
        await active.append_sample(samples=samples_in, IO="in")
        await active.append_sample(samples=samples_out, IO="out")
        datadict = {"error_code": error_code}
        datamodel = DataModel(data={active.base.dflt_file_conn_key(): datadict})
        active.enqueue_data_nowait(datamodel, action=active.action)
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/db_get_samples", tags=["action"])
    async def db_get_samples(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        fast_samples_in: List[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = Body(
            [LiquidSample(**{"sample_no": 1, "machine_name": gethostname().lower()})],
            embed=True,
        ),
    ):
        """Resolve sample references against the unified sample database.

        Positive ``sample_no`` values address rows from the beginning of the
        table, negative values from the end.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.
            fast_samples_in: Sample references to resolve; replaces
                ``action.samples_in`` after the call.

        Returns:
            The finished action dictionary.
        """
        active = await app.base.setup_and_contain_action()
        samples = await app.driver.archive.unified_db.get_samples(
            samples=active.action.samples_in
        )
        # clear samples_in
        active.action.samples_in = []
        await active.append_sample(samples=samples, IO="in")
        datadict = {"samples": [sample.as_dict() for sample in samples]}
        datamodel = DataModel(data={active.base.dflt_file_conn_key(): datadict})
        active.enqueue_data_nowait(datamodel, action=active.action)
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/db_new_samples", tags=["action"])
    async def db_new_samples(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        fast_samples_in: List[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = Body(
            [
                LiquidSample(
                    **{
                        "machine_name": gethostname().lower(),
                        "source": [],
                        "volume_ml": 0.0,
                        "action_time": strftime("%y%m%d.%H%M%S"),
                        "chemical": [],
                        "partial_molarity": [],
                        "supplier": [],
                        "lot_number": [],
                    }
                )
            ],
            embed=True,
        ),
    ):
        """Create new sample rows in the unified database.

        Use CAS numbers for chemicals when available. For empty DUID and
        AUID values the underlying UID is generated automatically. For
        manual entries leave DUID, AUID, ``action_time`` and ``action_params``
        empty and set ``servkey`` to ``"data"``. For the first liquid in a
        chain (no upstream source in the database), leave ``source`` and
        ``source_ml`` empty.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.
            fast_samples_in: Reference sample dicts describing the new rows.

        Returns:
            The finished action dictionary; the first created sample is
            mirrored into ``action_params['_fast_sample_out']``.
        """
        active = await app.base.setup_and_contain_action()
        samples = await app.driver.archive.create_samples(
            reference_samples_in=active.action.samples_in, action=active.action
        )
        # clear samples_in and samples_out
        active.action.samples_in = []
        active.action.samples_out = []
        await active.append_sample(samples=samples, IO="out")
        sample_out_dicts = [sample.as_dict() for sample in samples]
        datadict = {"samples": sample_out_dicts}
        datamodel = DataModel(data={active.base.dflt_file_conn_key(): datadict})
        active.enqueue_data_nowait(datamodel, action=active.action)
        active.action.action_params["_fast_sample_out"] = sample_out_dicts[0]
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/generate_plate_sample_no_list", tags=["action"])
    async def generate_plate_sample_no_list(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
        plate_id: int = 1,
        sample_code: int = Query(0, ge=0, le=2),
        skip_n_samples: int = Query(0, ge=0),
        direction: Optional[ScanDirection] = None,
        sample_nos: List[int] = [],
        sample_nos_operator: Optional[ScanOperator] = None,
        # platemap_xys: List[Tuple[int, int]] = [],
        platemap_xys: list = [],
        platemap_xys_operator: Optional[ScanOperator] = None,
    ):
        """Generate a filtered list of sample numbers for a plate.

        Combines a scan direction with optional include/exclude operators on
        explicit sample numbers and platemap xy coordinates to produce the
        list. Results are written to the action via the driver helper.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.
            plate_id: Plate id to scan.
            sample_code: Sample-code filter (``0``-``2``).
            skip_n_samples: Number of leading samples to skip.
            direction: Plate scan direction.
            sample_nos: Explicit sample numbers to include or exclude.
            sample_nos_operator: Operator applied with ``sample_nos``.
            platemap_xys: List of ``(x, y)`` platemap coordinates.
            platemap_xys_operator: Operator applied with ``platemap_xys``.

        Returns:
            The finished action dictionary.
        """
        active = await app.base.setup_and_contain_action()
        await app.driver.archive.generate_plate_sample_no_list(
            active=active,
            plate_id=active.action.action_params.get("plate_id", None),
            sample_code=active.action.action_params.get("sample_code", None),
            skip_n_samples=active.action.action_params.get("skip_n_samples", None),
            direction=active.action.action_params.get("direction", None),
            sample_nos=active.action.action_params.get("sample_nos", None),
            sample_nos_operator=active.action.action_params.get(
                "sample_nos_operator", None
            ),
            platemap_xys=active.action.action_params.get("platemap_xys", None),
            platemap_xys_operator=active.action.action_params.get(
                "platemap_xys_operator", None
            ),
        )
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/get_loaded_positions", tags=["action"])
    async def get_positions(
        action: Action = Body({}, embed=True),
        action_version: int = 1,
    ):
        """Snapshot the archive's loaded positions into ``action_params``.

        Populates ``_positions`` (full archive dict), ``_tray_pos`` (loaded
        tray vials keyed by ``(tray, slot, vial)``), and ``_custom_pos``
        (loaded custom positions keyed by name) on the action.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.

        Returns:
            The finished action dictionary.
        """
        active = await app.base.setup_and_contain_action()
        positions = app.driver.archive.positions
        tray_positions = {
            (traynum, slotnum, vialidx + 1): sample.global_label
            for traynum, slotdict in positions.trays_dict.items()
            for slotnum, vialtray in slotdict.items()
            for vialidx, (vialbool, sample) in enumerate(
                zip(vialtray.vials, vialtray.samples)
            )
            if vialbool
        }
        custom_positions = {
            customkey: custom.sample.global_label
            for customkey, custom in positions.customs_dict.items()
        }
        active.action.action_params.update(
            {
                "_positions": positions.as_dict(),
                "_tray_pos": tray_positions,
                "_custom_pos": custom_positions,
            }
        )
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/list_new_samples", tags=["action"])
    async def list_new_samples(num_smps: int = 10, give_only: str = "false") -> dict:
        """List the most recent global sample labels from each local DB table.

        Args:
            num_smps: Maximum number of labels to return per sample type.
            give_only: When ``"true"``, restrict to labels marked as
                give-only.

        Returns:
            Dict keyed by ``"solid"``, ``"liquid"``, ``"gas"``, and
            ``"assembly"`` with lists of recent labels.
        """
        give_bool = True if give_only == "true" else False
        solids = await app.driver.archive.unified_db.solidAPI.list_new_samples(
            limit=num_smps, give_only=give_bool
        )
        liquids = await app.driver.archive.unified_db.liquidAPI.list_new_samples(
            limit=num_smps, give_only=give_bool
        )
        gases = await app.driver.archive.unified_db.gasAPI.list_new_samples(
            limit=num_smps, give_only=give_bool
        )
        assemblies = await app.driver.archive.unified_db.assemblyAPI.list_new_samples(
            limit=num_smps, give_only=give_bool
        )
        return {
            "solid": solids,
            "liquid": liquids,
            "gas": gases,
            "assembly": assemblies,
        }

    return app
