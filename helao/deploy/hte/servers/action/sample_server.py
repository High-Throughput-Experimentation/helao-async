"""FastAPI action server for the sample archive/database (SAMPLE).

Owns the sole :class:`Archive` instance (tray + custom position bookkeeping
and the unified sample database) hoisted out of the PAL autosampler server.
Exposes two surfaces:

* **Action endpoints** (``tags=["action"]``) -- the orchestrated
  tray/custom load/unload/query/export and DB create/resolve endpoints
  lifted verbatim from ``pal_server`` (Active lifecycle, ``append_sample``,
  ``enqueue_data`` and ``_fast_samples_in``/``_fast_sample_out`` mirroring
  preserved). Because ``app.driver`` is the :class:`Archive` itself here,
  the only mechanical change is ``app.driver.archive.X`` -> ``app.driver.X``.
* **Private RPC endpoints** (``tags=["private"]``) -- thin wrappers over the
  driver's bookkeeping methods, called by the PAL driver's dispatcher shim.
  Sample-receiving endpoints coerce their inputs with
  :func:`object_to_sample`, because the ZMQ-RPC fast path does not rehydrate
  ``List[SampleUnion]``/``Union[...]`` params (only genuine ``BaseModel``
  subclasses), so those arrive as raw dicts.
"""

__all__ = ["makeApp"]


from socket import gethostname
from time import strftime

from fastapi import Body, Query
from typing import Optional, List, Union

from helao.core.servers.base_api import BaseAPI, action_version
from ...drivers.data.archive_driver import Archive, ScanDirection, ScanOperator

from helao.core.models.sample import (
    SampleType,
    LiquidSample,
    GasSample,
    AssemblySample,
    SolidSample,
    NoneSample,
    object_to_sample,
)
from helao.core.models.data import DataModel
from helao.helpers.make_str_enum import make_str_enum
from helao.helpers.premodels import Action


def makeApp(server_key) -> BaseAPI:
    """Build the BaseAPI app for the SAMPLE archive/database server.

    Constructs a :class:`BaseAPI` backed by the sole :class:`Archive`
    (``driver_classes=[Archive]``; ``BaseAPI`` instantiates a non-HelaoDriver
    class as ``Archive(self.base)``) and registers the archive/db action
    surface plus the private RPC surface used by the PAL driver shim.

    Args:
        server_key: Unique key identifying this server in the orchestration
            group.

    Returns:
        The configured BaseAPI instance.
    """

    app = BaseAPI(
        server_key,
        server_key,
        "Sample Archive/Database Server",
        version=1.0,
        driver_classes=[Archive],
    )

    if "positions" in app.server_params:
        dev_custom = app.server_params["positions"].get("custom", {})
    else:
        dev_custom = {}
    dev_customitems = make_str_enum(
        "dev_custom", {key: key for key in dev_custom.keys()}
    )

    # ------------------------------------------------------------------
    # Surface (a): orchestrated action endpoints (lifted from pal_server)
    # ------------------------------------------------------------------

    @app.post(f"/{server_key}/convert_v1DB", tags=["action"])
    async def convert_v1DB() -> dict:
        """Convert the legacy liquid JSON database to the SQLite schema.

        Args:
            action: Action wrapper supplied by the orchestrator.

        Returns:
            An empty dictionary once the migration completes.
        """
        # await app.driver.convert_oldDB_to_sqllite()
        await app.driver.unified_db.liquidAPI.old_jsondb_to_sqlitedb()
        return {}

    @app.post(f"/{server_key}/archive_tray_query_sample", tags=["action"])
    async def archive_tray_query_sample(
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
        error_code, sample = await app.driver.tray_query_sample(
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
    async def archive_tray_unloadall():
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
        ) = await app.driver.tray_unloadall(**active.action.action_params)
        await active.append_sample(samples=samples_in, IO="in")
        await active.append_sample(samples=samples_out, IO="out")
        datadict = {"unloaded": unloaded, "tray_dict": tray_dict}
        datamodel = DataModel(data={active.base.dflt_file_conn_key(): datadict})
        active.enqueue_data_nowait(datamodel, action=active.action)
        finished_act = await active.finish()
        return finished_act.as_dict()

    @app.post(f"/{server_key}/archive_tray_load", tags=["action"])
    async def archive_tray_load(
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
        error_code, loaded_sample = await app.driver.tray_load(
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
        ) = await app.driver.tray_unload(**active.action.action_params)
        await active.append_sample(samples=samples_in, IO="in")
        await active.append_sample(samples=samples_out, IO="out")
        datadict = {"unloaded": unloaded, "tray_dict": tray_dict}
        datamodel = DataModel(data={active.base.dflt_file_conn_key(): datadict})
        active.enqueue_data_nowait(datamodel, action=active.action)
        finished_act = await active.finish()
        return finished_act.as_dict()

    @app.post(f"/{server_key}/archive_tray_new_position", tags=["action"])
    async def archive_tray_new(
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
        datadict = await app.driver.tray_new_position(
            **active.action.action_params
        )
        datamodel = DataModel(data={active.base.dflt_file_conn_key(): datadict})
        active.enqueue_data_nowait(datamodel, action=active.action)
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/archive_tray_update_position", tags=["action"])
    async def archive_tray_update_position(
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
            "update": await app.driver.tray_update_position(
                **active.action.action_params
            ),
        }
        datamodel = DataModel(data={active.base.dflt_file_conn_key(): datadict})
        active.enqueue_data_nowait(datamodel, action=active.action)
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/archive_tray_export_json", tags=["action"])
    async def archive_tray_export_json(
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
        datadict = await app.driver.tray_export_json(
            **active.action.action_params
        )
        datamodel = DataModel(data={active.base.dflt_file_conn_key(): datadict})
        active.enqueue_data_nowait(datamodel, action=active.action)
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/archive_tray_export_icpms", tags=["action"])
    async def archive_tray_export_icpms(
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
        await app.driver.tray_export_icpms(
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

        await app.driver.tray_export_csv(
            tray=active.action.action_params.get("tray", None),
            slot=active.action.action_params.get("slot", None),
            myactive=active,
        )
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/{server_key}/archive_custom_load_solid", tags=["action"])
    async def archive_custom_load_solid(
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
        loaded, loaded_sample, customs_dict = await app.driver.custom_load(
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
        loaded, loaded_sample, customs_dict = await app.driver.custom_load(
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
        ) = await app.driver.custom_unload(
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
        ) = await app.driver.custom_unloadall(
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
        error_code, sample = await app.driver.custom_query_sample(
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
        ) = await app.driver.custom_add_liquid(
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
    @action_version(2)
    async def archive_custom_add_gas(
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
        ) = await app.driver.custom_add_gas(
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
        samples = await app.driver.unified_db.get_samples(
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
        samples = await app.driver.create_samples(
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
        await app.driver.generate_plate_sample_no_list(
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
        positions = app.driver.positions
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

    @app.post(f"/list_new_samples", tags=["private"])
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
        solids = await app.driver.unified_db.solidAPI.list_new_samples(
            limit=num_smps, give_only=give_bool
        )
        liquids = await app.driver.unified_db.liquidAPI.list_new_samples(
            limit=num_smps, give_only=give_bool
        )
        gases = await app.driver.unified_db.gasAPI.list_new_samples(
            limit=num_smps, give_only=give_bool
        )
        assemblies = await app.driver.unified_db.assemblyAPI.list_new_samples(
            limit=num_smps, give_only=give_bool
        )
        return {
            "solid": solids,
            "liquid": liquids,
            "gas": gases,
            "assembly": assemblies,
        }

    # ------------------------------------------------------------------
    # Surface (b): private RPC endpoints (PAL driver shim call surface)
    #
    # Thin wrappers returning the raw Archive method result. Sample-receiving
    # endpoints coerce inbound params with object_to_sample() because the
    # ZMQ-RPC fast path delivers List[SampleUnion]/Union params as raw dicts
    # (only genuine BaseModel-subclass annotations are auto-rehydrated).
    # ------------------------------------------------------------------

    @app.post(f"/get_samples", tags=["private"])
    async def get_samples(
        samples: List[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = Body([], embed=True),
    ):
        """Resolve sample references against the unified sample database."""
        coerced = [object_to_sample(s) for s in samples]
        return await app.driver.unified_db.get_samples(samples=coerced)

    @app.post(f"/new_samples", tags=["private"])
    async def new_samples(
        samples: List[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = Body([], embed=True),
    ):
        """Persist new sample rows via the unified sample database."""
        coerced = [object_to_sample(s) for s in samples]
        return await app.driver.unified_db.new_samples(samples=coerced)

    @app.post(f"/update_samples", tags=["private"])
    async def update_samples(
        samples: List[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = Body([], embed=True),
    ):
        """Update existing sample rows via the unified sample database."""
        coerced = [object_to_sample(s) for s in samples]
        return await app.driver.unified_db.update_samples(samples=coerced)

    @app.post(f"/tray_query_sample", tags=["private"])
    async def tray_query_sample(
        tray: Optional[int] = None,
        slot: Optional[int] = None,
        vial: Optional[int] = None,
    ):
        """Return ``(error, sample)`` for the given tray/slot/vial location."""
        return await app.driver.tray_query_sample(tray=tray, slot=slot, vial=vial)

    @app.post(f"/tray_get_next_full", tags=["private"])
    async def tray_get_next_full(
        after_tray: Optional[int] = None,
        after_slot: Optional[int] = None,
        after_vial: Optional[int] = None,
    ):
        """Return the next loaded vial position after the given location."""
        return await app.driver.tray_get_next_full(
            after_tray=after_tray, after_slot=after_slot, after_vial=after_vial
        )

    @app.post(f"/tray_new_position", tags=["private"])
    async def tray_new_position(
        req_vol: float = 2.0,
    ):
        """Reserve the smallest empty vial that can hold ``req_vol`` mL."""
        return await app.driver.tray_new_position(req_vol=req_vol)

    @app.post(f"/tray_update_position", tags=["private"])
    async def tray_update_position(
        tray: Optional[int] = None,
        slot: Optional[int] = None,
        vial: Optional[int] = None,
        sample: Optional[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = Body(None, embed=True),
        dilute: bool = False,
    ):
        """Overwrite the sample at ``(tray, slot, vial)``; return success bool."""
        coerced = object_to_sample(sample) if sample is not None else None
        return await app.driver.tray_update_position(
            tray=tray, slot=slot, vial=vial, sample=coerced, dilute=dilute
        )

    @app.post(f"/custom_query_sample", tags=["private"])
    async def custom_query_sample(
        custom: Optional[str] = None,
    ):
        """Return ``(error, sample)`` for the sample at a custom position."""
        return await app.driver.custom_query_sample(custom=custom)

    @app.post(f"/custom_update_position", tags=["private"])
    async def custom_update_position(
        custom: Optional[str] = None,
        sample: Optional[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = Body(None, embed=True),
        dilute: bool = False,
    ):
        """Replace the sample at ``custom``; return ``(success, sample)``."""
        coerced = object_to_sample(sample) if sample is not None else None
        return await app.driver.custom_update_position(
            custom=custom, sample=coerced, dilute=dilute
        )

    @app.post(f"/new_ref_samples", tags=["private"])
    async def new_ref_samples(
        samples_in: List[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = Body([], embed=True),
        sample_out_type: str = "",
        sample_position: str = "",
        combine_liquids: bool = False,
        combine_gases: bool = False,
        action: Optional[Action] = Body(None, embed=True),
    ):
        """Build new reference samples from ``samples_in``; return ``(ok, list)``."""
        coerced = [object_to_sample(s) for s in samples_in]
        return await app.driver.new_ref_samples(
            samples_in=coerced,
            sample_out_type=sample_out_type,
            sample_position=sample_position,
            action=action,
            combine_liquids=combine_liquids,
            combine_gases=combine_gases,
        )

    @app.post(f"/custom_dest_allowed", tags=["private"])
    async def custom_dest_allowed(
        custom: Optional[str] = None,
    ):
        """Return whether ``custom`` is a valid destination position."""
        return app.driver.custom_dest_allowed(custom=custom)

    @app.post(f"/custom_assembly_allowed", tags=["private"])
    async def custom_assembly_allowed(
        custom: Optional[str] = None,
    ):
        """Return whether ``custom`` may hold an :class:`AssemblySample`."""
        return app.driver.custom_assembly_allowed(custom=custom)

    @app.post(f"/custom_is_destroyed", tags=["private"])
    async def custom_is_destroyed(
        custom: Optional[str] = None,
    ):
        """Return whether ``custom`` is a waste/injector-style position."""
        return app.driver.custom_is_destroyed(custom=custom)

    return app
