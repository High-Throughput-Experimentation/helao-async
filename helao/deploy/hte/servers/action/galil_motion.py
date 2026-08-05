# shell: uvicorn motion_server:app --reload
"""Galil motion action server.

Wraps the :class:`Galil` motion driver and exposes generic motion endpoints
(``move``, ``easymove``, ``easymove_to_solid``, ``query_position[s]``,
``query_moving``, ``axis_on``/``axis_off``, ``z_move``, ``disconnect``,
``stop``, ``reset``), plate-alignment endpoints (``setmotionref``,
``reset_plate_alignment``, ``load_plate_alignment``, ``run_aligner``,
``stop_aligner``), coordinate transforms (``toMotorXY``, ``toPlateXY``,
``MxytoMPlate``) and platemap-lookup helpers (``solid_get_platemap``,
``solid_get_samples_xy``, ``solid_get_builtin_specref``,
``solid_get_nearest_specref``). Endpoints are registered conditionally on the
configured ``axis_id`` set.

Motor calibration procedure for new instrument alignment:
Place alignment plate onto stage.
In c:\\inst_hlo\\database\\plate_calib, delete the instrument_calib.json
---
Open the MOTOR bokeh
----
In MOTOR swagger:
After performing setmotionref, verify/edit the x-y offsets in the config file.
Execute run_aligner.
----
In MOTOR bokeh, click on green "go" button.
On the map click on the samples, move to the corresponding positions and "Add Pt"
After 3 points, click "Calc" and then "Sub"mit
---
Exit helao, in the plat_calib directory, rename the plate_6353_calib.json to instrument_calib.json.

Back in helao, redo the alignment for 6353 plate or any 4x6 plate or round.

For rounds, type any map 57 plate number and align to the sample numbers on the round alignment plate.

Exit helao and restart.
"""

__all__ = ["makeApp"]

import asyncio
from enum import Enum
from typing import Optional, Union

import numpy as np

from helao.core.error import ErrorCodes
from helao.core.models.file import FileConnParams
from helao.core.servers.base_api import BaseAPI
from helao.core.servers.motion_control import Units
from helao.helpers import helao_logging as logging
from helao.helpers.active_params import ActiveParams
from helao.helpers.make_str_enum import make_str_enum
from helao.helpers.sample_api import UnifiedSampleDataAPI

# P3a galil-3 native cut-over (2026-07-23): the galil motion server is backed by
# the hexagon-native NativeGalilMotion (gclib behind a GalilCommandChannel port)
# instead of the legacy in-tree Galil driver. Validated at-station (PR #204).
from helao.hexagon.adapters.native.galil_motion_native import NativeGalilMotion

# P3a galil-split slice-4: the Bokeh plate-aligner is hosted by the vis layer,
# not the driver (D6 fix). The server constructs the host after connect().
from helao.hexagon.adapters.vis.galil_aligner_host import GalilAlignerHost

from ...drivers.motion.galil_motion_driver import (
    MoveModes,
    TransformationModes,
)

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


def _running_actions(app: BaseAPI) -> list:
    """Names of this server's endpoints that currently have a running action.

    Whether an action is running is knowable only server-side, from the
    ``Base`` object no shared module holds, so this check cannot live beside
    the rest of the panel logic in ``motion_control.py`` -- only the
    *rendering* of a refusal does. Same sweep the queueing middleware performs
    in ``base_api.py``, without its single-endpoint narrowing: a panel command
    for the stage cares that the server is moving something, not which route
    was asked to move it.
    """
    return [
        ep for ep, em in app.base.actionservermodel.endpoints.items() if em.active_dict
    ]


def _first_error(err_code) -> ErrorCodes:
    """Collapse ``_motor_move``'s per-axis error list to a single code.

    The driver reports one code per requested axis; these endpoints request
    exactly one, but the early-refusal branches return a bare code rather than
    a list, so both shapes arrive here. The first non-``none`` entry wins --
    a partial success on a single-axis move is still a failed move.
    """
    if isinstance(err_code, list):
        for code in err_code:
            if code != ErrorCodes.none:
                return code
        return ErrorCodes.none if err_code else ErrorCodes.unspecified
    return err_code if err_code is not None else ErrorCodes.unspecified


def _first_count(counts) -> Optional[int]:
    """Pull the commanded count out of ``_motor_move``'s per-axis list.

    ``None`` -- never ``0`` -- when the driver did not report one: zero is a
    legitimate count, so a missing value shown as zero would read as a
    deliberate no-op move.
    """
    if isinstance(counts, list):
        counts = counts[0] if counts else None
    if counts is None:
        return None
    try:
        return int(counts)
    except (TypeError, ValueError):
        return None


#: Panel moves currently in flight. A strong reference has to be held: the
#: event loop keeps only a weak one to a running task, so a bare
#: ``create_task`` whose result nobody stores can be collected mid-move.
PANEL_MOVE_TASKS: set = set()


def _dispatch_panel_move(coro, axis: str, value: float, units: str):
    """Run a panel move in the background and report what it eventually did.

    The endpoint that calls this has already answered the panel, so this
    callback is the only place a later failure can surface. Both failure
    shapes are covered, and the second is the common one:

    * an exception -- which without a done-callback becomes "Task exception
      was never retrieved" at collection time, i.e. nothing an operator sees;
    * a non-``none`` ``ErrorCodes`` in the returned dict, which is how
      ``_motor_move`` reports nearly every real fault. An exception-only
      callback would swallow those silently.

    The completed count is logged too. It used to be in the endpoint's return
    payload and cannot be now, so the log is where it lives.
    """
    task = asyncio.create_task(coro)
    PANEL_MOVE_TASKS.add(task)

    def _report(finished: asyncio.Task) -> None:
        PANEL_MOVE_TASKS.discard(finished)
        what = f"panel move on axis '{axis}' to {value} {units}"
        if finished.cancelled():
            LOGGER.error(f"{what} was cancelled before it completed")
            return
        exc = finished.exception()
        if exc is not None:
            LOGGER.error(f"{what} raised {exc!r}", exc_info=exc)
            return
        result = finished.result() or {}
        error_code = _first_error(result.get("err_code"))
        if error_code != ErrorCodes.none:
            LOGGER.error(f"{what} -> {error_code}")
        else:
            LOGGER.info(
                f"{what} completed, counts={_first_count(result.get('counts'))}"
            )

    task.add_done_callback(_report)
    return task


async def galil_dyn_endpoints(app: BaseAPI):
    """Wire the driver's ``_base_hook``, open the Galil connection, construct
    the shared sample-DB handle, and register motion endpoints once the
    driver reports itself enabled.

    ``BaseAPI``'s own startup handler (``base_api.py``) only constructs the
    driver with ``config=server_params``; it never assigns a live ``Base``
    reference nor opens the gclib connection (K1/K2/K4/K8). Unlike
    ``thorlabs_kinesis.py`` (whose sibling server registers all endpoints
    unconditionally, gated only on static config), this server's endpoints
    are gated on ``app.driver.galil_enabled`` -- a value only known *after*
    ``connect()`` runs. So ``_base_hook`` assignment and ``connect()`` are
    done here, at the top of this ``dyn_endpoints`` callback, mirroring
    ``nidaqmx_server.py``'s ``nidaqmx_dyn_endpoints`` (the codebase's other
    driver with a connection-gated dynamic endpoint set) rather than a
    separate ``@app.on_event("startup")`` hook -- this callback is itself
    invoked synchronously from ``Base.dyn_endpoints_init()``, which runs
    inside the *same* startup event that constructs the driver, guaranteeing
    ``connect()`` completes before the ``galil_enabled`` gate below is read.

    Args:
        app: The :class:`BaseAPI` instance being constructed by ``makeApp``.
    """
    server_key = app.base.server.server_name

    app.driver._base_hook = app.base
    # K7/sm: the sample DB is server/app-level state (mirrors
    # `nidaqmx_server.py`'s `app.unified_db`), never driver state.
    app.unified_db = UnifiedSampleDataAPI(app.base)
    connect_resp = app.driver.connect()
    LOGGER.info(f"Galil connect() returned status={connect_resp.status}")

    if app.driver.galil_enabled is True:

        # P3a galil-split slice-4: construct the Bokeh plate-aligner in the vis
        # layer (was `Galil.start_aligner` inside connect()). The host owns the
        # Bokeh Server + HelaoVis + the aligner-session Active, and wires the
        # driver's position-notify sink; gated on the `enable_aligner` config
        # exactly as the driver's old `aligner_enabled` gate was.
        app.aligner_host = None
        if app.server_params.get("enable_aligner", False):
            app.aligner_host = GalilAlignerHost(
                driver=app.driver,
                base=app.base,
                server_cfg=app.base.server_cfg,
                server_name=server_key,
                config=app.server_params,
            )
            app.aligner_host.start()

            @app.on_event("shutdown")
            async def _shutdown_aligner_host():
                if getattr(app, "aligner_host", None) is not None:
                    app.aligner_host.shutdown()

        dev_axis = app.server_params.get("axis_id", {})
        dev_axisitems = make_str_enum("axis_id", {key: key for key in dev_axis})

        if dev_axis:

            @app.post(f"/{server_key}/setmotionref", tags=["action"])
            async def setmotionref():
                """Establish the xyz reference position.

                Homes xyz, sets absolute zero, moves back by the configured
                centre counts and resets absolute zero again.
                """
                active = await app.base.setup_and_contain_action(
                    action_abbr="setmotionref"
                )
                await active.enqueue_data_dflt(
                    datadict={"setref": await app.driver.setaxisref()}
                )
                finished_action = await active.finish()
                return finished_action.as_dict()

        @app.post(f"/{server_key}/reset_plate_alignment", tags=["action"])
        async def reset_plate_alignment():
            """Reset the plate transform matrix back to identity."""
            active = await app.base.setup_and_contain_action()
            app.driver.reset_plate_transfermatrix()
            finished_action = await active.finish()
            return finished_action.as_dict()

        @app.post(f"/{server_key}/load_plate_alignment", tags=["action"])
        async def load_plate_alignment(
            matrix: list = [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        ):
            """Install ``matrix`` as the plate-to-motor transform matrix."""
            active = await app.base.setup_and_contain_action()
            newmatrix = app.driver.update_plate_transfermatrix(
                newtransfermatrix=np.matrix(active.action.action_params["matrix"])
            )
            await active.enqueue_data_dflt(datadict={"matrix": newmatrix.tolist()})
            finished_action = await active.finish()
            return finished_action.as_dict()

        @app.post(f"/{server_key}/run_aligner", tags=["action"])
        async def run_aligner(
            plateid_or_pmpath: int | str = 6353,  # None
        ):
            """Start the interactive plate-alignment routine.

            K7b: containing the action (``contain_action``) is done here,
            not by the driver. P3a slice-4: the precheck + run-start moved
            from the driver to the vis-layer ``GalilAlignerHost`` (which owns
            the Bokeh aligner UI + its Active); ``run_aligner_precheck``
            reports whether a new run may start and, if not, the exact
            rejection code. Only when it reports success is the ``Active``
            created and handed to ``host.start_aligner_run``; the final
            transfer matrix is delivered when the user submits the alignment.
            """
            A = app.base.setup_action()
            host = app.aligner_host
            if host is None:
                A.error_code = ErrorCodes.not_available
                return A.as_dict()
            ok, error_code = host.run_aligner_precheck()
            if ok:
                active = await app.base.contain_action(
                    ActiveParams(
                        action=A,
                        file_conn_params_dict={
                            app.base.dflt_file_conn_key(): FileConnParams(
                                # use dflt file conn key for first
                                # init
                                file_conn_key=app.base.dflt_file_conn_key(),
                                sample_global_labels=[],
                                file_type="aligner_helao__file",
                                # hloheader = HloHeaderModel(
                                #     optional = None
                                # ),
                            )
                        },
                    )
                )
                active_dict = await host.start_aligner_run(active)
            else:
                A.error_code = error_code
                active_dict = A.as_dict()
            return active_dict

        @app.post(f"/{server_key}/stop_aligner", tags=["action"])
        async def stop_aligner():
            """Abort an in-progress plate-alignment routine."""
            active = await app.base.setup_and_contain_action()
            host = app.aligner_host
            if host is None:
                active.action.error_code = ErrorCodes.not_available
            else:
                active.action.error_code = await host.stop_aligner()
            finished_action = await active.finish()
            return finished_action.as_dict()

        # parse as {'M':json.dumps(np.matrix(M).tolist()),'platexy':json.dumps(np.array(platexy).tolist())}
        @app.post(f"/{server_key}/toMotorXY", tags=["action"])
        async def toMotorXY(
            platexy: Optional[str] = None,
        ):
            """Transform plate (sample) XY coordinates into motor XY coordinates."""
            active = await app.base.setup_and_contain_action(action_abbr="tomotorxy")
            await active.enqueue_data_dflt(
                datadict={
                    "motorxy": app.driver.transform.transform_platexy_to_motorxy(
                        **active.action.action_params
                    ).tolist()
                }
            )
            finished_action = await active.finish()
            return finished_action.as_dict()

        # parse as {'M':json.dumps(np.matrix(M).tolist()),'platexy':json.dumps(np.array(motorxy).tolist())}
        @app.post(f"/{server_key}/toPlateXY", tags=["action"])
        async def toPlateXY(
            motorxy: Optional[str] = None,
        ):
            """Transform motor XY coordinates into plate (sample) XY coordinates."""
            active = await app.base.setup_and_contain_action(action_abbr="toplatexy")
            await active.enqueue_data_dflt(
                datadict={
                    "platexy": app.driver.transform.transform_motorxy_to_platexy(
                        **active.action.action_params
                    ).tolist()
                }
            )
            finished_action = await active.finish()
            return finished_action.as_dict()

        @app.post(f"/{server_key}/MxytoMPlate", tags=["action"])
        async def MxytoMPlate(
            Mxy: Optional[str] = None,
        ):
            """Strip the instrument matrix from a system matrix to obtain ``Mplate``."""
            active = await app.base.setup_and_contain_action(action_abbr="mxytomplate")
            await active.enqueue_data_dflt(
                datadict={
                    "mplate": app.driver.transform.get_Mplate_Msystem(
                        **active.action.action_params
                    )
                }
            )
            finished_action = await active.finish()
            return finished_action.as_dict()

        if dev_axis:

            @app.post(f"/{server_key}/move", tags=["action"])
            async def move(
                d_mm: list[float] = [0, 0],
                axis: list[str] = ["x", "y"],
                speed: Optional[int] = None,
                mode: MoveModes = MoveModes.relative,
                transformation: TransformationModes = TransformationModes.motorxy,  # default, nothing to do
            ):
                """Move the listed axes by per-axis distances.

                Uses ``mode`` (relative/absolute) and the chosen ``transformation``
                coordinate frame. ``Rx``/``Ry``/``Rz`` rotational axes may only
                be combined with ``x``/``y``/``z`` in the ``motorxy`` frame;
                only x/y are valid when ``platexy`` is selected.
                """
                active = await app.base.setup_and_contain_action(action_abbr="move")
                datadict = await app.driver.motor_move(active)
                active.action.error_code = app.base.get_main_error(
                    datadict.get("err_code", ErrorCodes.unspecified)
                )
                await active.enqueue_data_dflt(datadict=datadict)
                finished_action = await active.finish()
                return finished_action.as_dict()

        if dev_axis:

            @app.post(f"/{server_key}/easymove", tags=["action"])
            async def easymove(
                axis: Optional[dev_axisitems] = None,
                d_mm: float = 0,
                speed: Optional[int] = None,
                mode: MoveModes = MoveModes.relative,
                transformation: TransformationModes = TransformationModes.motorxy,  # default, nothing to do
            ):
                """Single-axis variant of ``move`` taking a single ``axis``/``d_mm`` pair.

                Same coordinate/rotation restrictions as ``move`` apply.
                """
                active = await app.base.setup_and_contain_action(action_abbr="move")
                datadict = await app.driver.motor_move(active)
                active.action.error_code = app.base.get_main_error(
                    datadict.get("err_code", ErrorCodes.unspecified)
                )
                await active.enqueue_data_dflt(datadict=datadict)
                finished_action = await active.finish()
                return finished_action.as_dict()

            @app.post(f"/{server_key}/easymove_to_solid", tags=["action"])
            async def easymove_to_solid(
                plate_id: Optional[int] = None,
                sample_no: Optional[int] = None,
                speed: Optional[int] = None,
            ):
                """Move xy to the platemap position of ``sample_no`` on ``plate_id``.

                Looks up the sample's plate XY via :meth:`Galil.solid_get_samples_xy`
                then performs an absolute move in the platexy frame. Sets
                ``error_code`` to ``not_available`` if the sample has no
                platemap coordinates.
                """
                active = await app.base.setup_and_contain_action()
                datadict0 = await app.driver.solid_get_samples_xy(
                    app.unified_db, **active.action.action_params
                )
                platexy = datadict0.get("platexy", [[None, None]])[0]
                if platexy[0] is None or platexy[1] is None:
                    active.action.error_code = ErrorCodes.not_available
                else:
                    active.action.action_params.update(
                        {
                            "d_mm": platexy,
                            "axis": ["x", "y"],
                            "mode": MoveModes.absolute,
                            "transformation": TransformationModes.platexy,
                        }
                    )
                    datadict1 = await app.driver.motor_move(active)
                    active.action.error_code = app.base.get_main_error(
                        datadict1.get("err_code", ErrorCodes.unspecified)
                    )
                    await active.enqueue_data_dflt(datadict=datadict1)
                finished_action = await active.finish()
                return finished_action.as_dict()

        @app.post(f"/{server_key}/disconnect", tags=["action"])
        async def disconnect():
            """Disconnect from the Galil motion controller."""
            active = await app.base.setup_and_contain_action(action_abbr="disconnect")
            await active.enqueue_data_dflt(datadict=await app.driver.motor_disconnect())
            finished_action = await active.finish()
            return finished_action.as_dict()

        if dev_axis:

            @app.post(f"/{server_key}/query_positions", tags=["action"])
            async def query_positions():
                """Return the current position of every configured axis."""
                active = await app.base.setup_and_contain_action(
                    action_abbr="query_position"
                )
                await active.enqueue_data_dflt(
                    datadict=await app.driver.query_axis_position(
                        axis=app.driver.get_all_axis()
                    )
                )
                finished_action = await active.finish()
                return finished_action.as_dict()

        if dev_axis:

            @app.post(f"/{server_key}/query_position", tags=["action"])
            async def query_position(
                # axis: Union[list[str], str] = None
                axis: Optional[dev_axisitems] = None,
            ):
                """Return the current position of a single named axis."""
                active = await app.base.setup_and_contain_action(
                    action_abbr="query_position"
                )
                await active.enqueue_data_dflt(
                    datadict=await app.driver.query_axis_position(
                        **active.action.action_params
                    )
                )
                finished_action = await active.finish()
                return finished_action.as_dict()

        if dev_axis:

            @app.post(f"/{server_key}/query_moving", tags=["action"])
            async def query_moving(
                axis: Union[list[str], str, None] = None,
            ):
                """Return whether the given axis or list of axes is currently moving."""
                active = await app.base.setup_and_contain_action(
                    action_abbr="query_moving"
                )
                datadict = await app.driver.query_axis_moving(
                    **active.action.action_params
                )
                active.action.error_code = app.base.get_main_error(
                    datadict.get("err_code", ErrorCodes.unspecified)
                )
                await active.enqueue_data_dflt(datadict=datadict)
                finished_action = await active.finish()
                return finished_action.as_dict()

        if dev_axis:

            @app.post(f"/{server_key}/axis_off", tags=["action"])
            async def axis_off(
                # axis: Union[list[str], str] = None
                axis: Optional[dev_axisitems] = None,
            ):
                """De-energise (turn off) the named motor axis."""
                # http://127.0.0.1:8001/motor/set/off?axis=x
                active = await app.base.setup_and_contain_action(action_abbr="axis_off")
                datadict = await app.driver.motor_off(**active.action.action_params)
                active.action.error_code = app.base.get_main_error(
                    datadict.get("err_code", ErrorCodes.unspecified)
                )
                await active.enqueue_data_dflt(datadict=datadict)
                finished_action = await active.finish()
                return finished_action.as_dict()

        if dev_axis:

            @app.post(f"/{server_key}/axis_on", tags=["action"])
            async def axis_on(
                axis: Optional[dev_axisitems] = None,
            ):
                """Energise (turn on) the named motor axis."""
                active = await app.base.setup_and_contain_action(action_abbr="axis_on")
                datadict = await app.driver.motor_on(**active.action.action_params)
                active.action.error_code = app.base.get_main_error(
                    datadict.get("err_code", ErrorCodes.unspecified)
                )
                await active.enqueue_data_dflt(datadict=datadict)
                finished_action = await active.finish()
                return finished_action.as_dict()

        @app.post(f"/{server_key}/solid_get_platemap", tags=["action"])
        async def solid_get_platemap(
            plate_id: Optional[int] = None,
        ):
            """Return the platemap rows for ``plate_id`` via the driver."""
            active = await app.base.setup_and_contain_action()
            datadict = await app.driver.solid_get_platemap(
                app.unified_db, **active.action.action_params
            )
            await active.enqueue_data_dflt(datadict=datadict)
            finished_action = await active.finish()
            return finished_action.as_dict()

        @app.post(f"/{server_key}/solid_get_samples_xy", tags=["action"])
        async def solid_get_samples_xy(
            plate_id: Optional[int] = None,
            sample_no: Optional[int] = None,
        ):
            """Return the plate XY position(s) for ``sample_no`` on ``plate_id``.

            Stores the first returned ``platexy`` pair back on the action
            params as ``_platexy`` and sets ``error_code`` to ``not_available``
            when the lookup yields no coordinates.
            """
            active = await app.base.setup_and_contain_action()
            datadict = await app.driver.solid_get_samples_xy(
                app.unified_db, **active.action.action_params
            )
            platexy = datadict.get("platexy", [[None, None]])[0]
            if platexy[0] is None or platexy[1] is None:
                active.action.error_code = ErrorCodes.not_available
            active.action.action_params.update({"_platexy": platexy})
            await active.enqueue_data_dflt(datadict=datadict)
            finished_action = await active.finish()
            return finished_action.as_dict()

        @app.post(f"/{server_key}/solid_get_builtin_specref", tags=["action"])
        async def solid_get_builtin_specref(
            specref_code: int = 1,
            ref_position_name: str = "builtin_ref_motorxy",
        ):
            """Return a pre-configured spectrometer reference position from world config.

            Looks up ``ref_position_name`` in :attr:`Base.world_cfg` and stores
            it on the action params as ``_refxy``.
            """
            active = await app.base.setup_and_contain_action()
            refxy = app.base.world_cfg[active.action.action_params["ref_position_name"]]
            active.action.action_params.update({"_refxy": refxy})
            await active.enqueue_data_dflt(datadict={"_refxy": refxy})
            finished_action = await active.finish()
            return finished_action.as_dict()

        @app.post(f"/{server_key}/solid_get_nearest_specref", tags=["action"])
        async def solid_get_nearest_specref(
            plate_id: Optional[int] = None,
            sample_no: Optional[int] = None,
            specref_code: int = 1,
        ):
            """Return the platemap reference sample nearest to ``sample_no``.

            Pulls the platemap for ``plate_id``, filters for rows whose
            ``code`` equals ``specref_code``, and picks the one closest to the
            target sample. Stores ``_refno`` and ``_refxy`` on the action params.
            """
            active = await app.base.setup_and_contain_action()
            datadict = await app.driver.solid_get_platemap(
                app.unified_db, active.action.action_params["plate_id"]
            )
            pmdlist = datadict["platemap"][0]
            pmkeys = ["sample_no", "x", "y"]

            smpd = [
                d
                for d in pmdlist
                if d["sample_no"] == active.action.action_params["sample_no"]
            ][0]
            refarr = np.array(
                [
                    [d[k] for k in pmkeys]
                    for d in pmdlist
                    if d["code"] == active.action.action_params["specref_code"]
                ]
            )
            print(refarr.shape)
            print(refarr[:2])
            refnos, refxys = refarr[:, 0], refarr[:, 1:]
            nearest = np.argmin(
                ((refxys - np.array([smpd["x"], smpd["y"]]).reshape(1, 2)) ** 2).sum(
                    axis=1
                )
            )
            refno = refnos[nearest]
            refxy = list(refxys[nearest])
            active.action.action_params.update({"_refno": refno, "_refxy": refxy})
            await active.enqueue_data_dflt(datadict={"_refno": refno, "_refxy": refxy})
            finished_action = await active.finish()
            return finished_action.as_dict()

        @app.post(f"/{server_key}/stop", tags=["action"])
        async def stop():
            """De-energise every configured motor axis."""
            active = await app.base.setup_and_contain_action(action_abbr="stop")
            datadict = await app.driver.motor_off(axis=app.driver.get_all_axis())
            active.action.error_code = app.base.get_main_error(
                datadict.get("err_code", ErrorCodes.unspecified)
            )
            await active.enqueue_data_dflt(datadict=datadict)
            finished_action = await active.finish()
            return finished_action.as_dict()

        @app.post(f"/{server_key}/reset", tags=["action"])
        async def reset():
            """Reset the Galil controller. Emergency use only.

            Calls :meth:`Galil.reset_controller` -- the pre-migration
            device-level ``RS`` command -- not the ``HelaoDriver`` ABC's
            ``reset()`` lifecycle method (which force-closes and reopens the
            whole connection); the two were given different names to
            resolve the K1 naming collision introduced by the ABC.
            """
            active = await app.base.setup_and_contain_action(action_abbr="reset")
            await active.enqueue_data_dflt(
                datadict={"reset": await app.driver.reset_controller()}
            )
            finished_action = await active.finish()
            return finished_action.as_dict()

        if dev_axis:

            zpos_dict = app.base.server_params.get("z_height_mm", {})
            zpos_dict["NA"] = None
            Zpos = Enum("Zpos", {k: k for k in zpos_dict.keys()})

            @app.post(f"/{server_key}/z_move", tags=["action"])
            async def z_move(
                z_position: Zpos = "NA",
            ):
                """Move the z-axis to a named cell height from the server config.

                ``z_position`` is one of the keys of the ``z_height_mm`` mapping
                in this server's config; ``NA`` is a no-op that returns
                ``not_available``.
                """
                active = await app.base.setup_and_contain_action(action_abbr="z_move")
                z_arg = active.action.action_params["z_position"]
                if isinstance(z_arg, Zpos):
                    z_key = z_arg.value
                else:
                    z_key = z_arg
                z_value = zpos_dict.get(z_key, "NA")
                if z_key != "NA":
                    active.action.action_params.update(
                        {
                            "d_mm": [z_value],
                            "axis": ["z"],
                            "mode": MoveModes.absolute,
                            "transofmration": TransformationModes.instrxy,
                        }
                    )
                    datadict = await app.driver.motor_move(active)
                    active.action.error_code = app.base.get_main_error(
                        datadict.get("err_code", ErrorCodes.unspecified)
                    )
                    await active.enqueue_data_dflt(datadict=datadict)
                else:
                    active.action.error_code = ErrorCodes.not_available
                finished_action = await active.finish()
                return finished_action.as_dict()

        if dev_axis:

            # Private motion controls for the engineering control panel. Same
            # driver calls as the action routes above, no action wrapper: a
            # panel click is a manual intervention, not a step of an
            # experiment, and routing it through the action machinery would
            # put a row in the run record for every click and queue that click
            # behind whatever the orchestrator is running on this server.
            #
            # Bare paths, not ``/{server_key}/...``: that prefix is the action
            # namespace. Reached with ``async_private_dispatcher``.
            #
            # ``mode`` and ``units`` are enums rather than strings on purpose.
            # A free-text ``units`` would let ``"count"`` -- the plausible
            # misspelling -- fall through to the millimetre branch and execute
            # a 10 000-*count* move as 10 000 *millimetres*. FastAPI answers
            # 422 instead. ``axis`` and ``value`` are required for the same
            # reason: a defaulted axis moves something nobody named.

            @app.post("/move_axis", tags=["private"])
            async def move_axis(
                axis: dev_axisitems,
                value: float,
                mode: MoveModes = MoveModes.relative,
                units: Units = Units.mm,
                speed: Optional[int] = None,
            ):
                """Start a move on one axis without creating an action.

                **Returns as soon as the move is dispatched, not when the
                stage arrives.** ``_motor_move`` settle-polls until motion
                ceases -- up to a 30-minute cap -- while the panel dispatches
                every private call with a 5 s timeout, so a blocking route
                reported any move longer than about five seconds as a failure
                while it was in fact succeeding. An operator shown "failed"
                on a successful move retries it, which issues a *second*
                move. Returning at once removes that, at the price stated
                below. The action routes are unaffected and still block: an
                experiment step must not continue before the stage arrives.

                Refused outright while an action is running on this server:
                unlike a stop, a concurrent move has no safety justification,
                and the refusal is reported as its own outcome rather than as
                a failure so the panel can name the remedy. No device call is
                made -- and no task is launched -- in that case.

                The value is dispatched in the domain ``units`` names. Under
                ``counts`` the driver hands the integer to ``PR``/``PA``
                undivided, so it reaches the stage exactly as typed; the
                conversion (or its deliberate absence) happens there, never
                here.

                Always the ``motorxy`` frame: this is a raw motor-axis
                control, so the plate and instrument transforms -- which are
                mm arithmetic and would silently garble a count -- are never
                involved.

                Args:
                    axis: Axis name from the server's ``axis_id`` config.
                    value: Move magnitude or absolute target, in ``units``.
                    mode: Relative or absolute interpretation of ``value``.
                    units: ``mm`` or ``counts``.
                    speed: Optional speed override in counts/sec.

                Returns:
                    ``(error_code, {"axis", "requested", "units", "counts"})``
                    -- the same shape as before, with a changed meaning. The
                    code now says **accepted and dispatched**, never
                    "completed": nothing about the move's outcome is known
                    yet. A failure after dispatch reaches the log (see
                    ``_dispatch_panel_move``) and the panel's position
                    readout, not this return value. That trade was made
                    deliberately -- a wrong "failed" is worse here than a
                    delayed "failed", because it provokes a duplicate move.

                    ``counts`` is likewise the integer this endpoint knows
                    will be commanded, which it has only for a counts move;
                    an mm move reports ``None`` rather than inventing a
                    plausible-looking figure, since the conversion happens in
                    the driver and has not run yet.
                """
                running = _running_actions(app)
                if running:
                    LOGGER.info(
                        f"refusing panel move on axis '{axis}': actions running "
                        f"on {running}"
                    )
                    return ErrorCodes.in_progress, {}

                # TOCTOU residual, stated rather than discovered at a station:
                # an action can start between the check above and the driver
                # call below -- a slightly wider window now that the call runs
                # in a task rather than inline. Galil closes it downstream --
                # ``_motor_move`` guards on ``self.motor_busy`` and returns
                # ``in_progress`` -- so the race here degrades to a refusal,
                # not to two simultaneous move commands. What the widened
                # window costs is only *where* the refusal is reported: it
                # lands in the log instead of in this endpoint's return.
                axis_name = getattr(axis, "value", axis)
                _dispatch_panel_move(
                    app.driver._motor_move(
                        d_mm=value,
                        axis=axis_name,
                        speed=speed,
                        mode=mode,
                        transformation=TransformationModes.motorxy,
                        units=units.value,
                    ),
                    axis=axis_name,
                    value=value,
                    units=units.value,
                )
                # np.floor, not int(): the driver floors, and int() truncates
                # towards zero, so a negative non-integral count would be
                # reported one count short of what the controller is given.
                return ErrorCodes.none, {
                    "axis": axis_name,
                    "requested": value,
                    "units": units.value,
                    "counts": int(np.floor(value)) if units == Units.counts else None,
                }

            @app.post("/stop_motion", tags=["private"])
            async def stop_motion():
                """Halt every axis, leaving the motors energized.

                ``ST`` only, never ``MO``: a de-energized vertical axis drops
                under gravity, so a panel stop that cut the holding current
                would be more dangerous than the motion it interrupted. That
                is also why this route is **not** named for an estop -- an
                estop must de-energize, and a halt-only route wearing that
                name would under-stop whatever cascade adopted it.

                **Unconditional, including mid-sequence, and the consequence
                is accepted rather than hidden.** A running action is not
                cancelled, failed, or notified: its executor keeps polling,
                observes that motion has ceased, and completes normally --
                reporting a position that is not the one it commanded. So the
                run record can end up describing a move that did not go where
                it says it went. That is the correct trade for an engineering
                escape hatch (halting a crashing stage must not depend on the
                orchestrator being responsive), but it is a data-integrity
                hazard, which is why the case is logged at WARNING here.

                Returns:
                    ``(error_code, {"stopped": [axis, ...]})`` listing the
                    axes the stop was issued to.
                """
                axes = app.driver.get_all_axis()
                running = _running_actions(app)
                if running:
                    LOGGER.warning(
                        f"panel stop_motion issued while actions are running on "
                        f"{running}; motion will halt without notifying them, so "
                        f"their recorded end position will not be the commanded one"
                    )
                ret = await app.driver.stop_axis(axes)
                return _first_error(ret.get("err_code")), {"stopped": axes}

            @app.post("/get_axis_positions", tags=["private"])
            async def get_axis_positions():
                """Return every axis's coordinate in both millimetres and counts.

                One position sample per axis, rendered twice. The counts are
                the controller's own integer and the millimetres are derived
                from that same integer, so the two halves always describe the
                same instant -- taking a second, scaled reading would give two
                round trips at two instants, which cannot describe one
                coordinate on a moving axis.

                Returns:
                    ``(error_code, {axis: {"mm": float|None,
                    "counts": int|None, "moving": bool|None}})``. ``None``
                    rather than ``0`` throughout: zero is a legitimate motor
                    coordinate, so a value shown as zero must mean zero.
                """
                axes = app.driver.get_all_axis()
                positions = await app.driver.query_axis_position_counts(axis=axes)
                # A separate exchange, but for a different quantity (the SC
                # stop-code register), not a second sample of the position.
                moving = await app.driver.query_axis_moving(axis=axes)
                statuses = moving.get("motor_status") or []
                state = {}
                for idx, ax in enumerate(axes):
                    mm = None
                    counts = None
                    if idx < len(positions.get("ax", [])):
                        mm = positions["position"][idx]
                        counts = positions["counts"][idx]
                    status = statuses[idx] if idx < len(statuses) else None
                    state[ax] = {
                        "mm": mm,
                        "counts": None if counts is None else int(counts),
                        "moving": (
                            None
                            if status not in ("moving", "stopped")
                            else (status == "moving")
                        ),
                    }
                return ErrorCodes.none, state


def makeApp(server_key) -> BaseAPI:
    """Build the Galil motion FastAPI app.

    Constructs a :class:`BaseAPI` backed by the native
    :class:`NativeGalilMotion` driver (gclib behind a command-channel port) and
    defers endpoint registration (plus the driver's ``connect()`` call) to
    :func:`galil_dyn_endpoints`.

    Args:
        server_key: Key identifying this server in the orchestration group.

    Returns:
        The configured :class:`BaseAPI` application.
    """

    app = BaseAPI(
        server_key=server_key,
        server_title=server_key,
        description="Galil motion server",
        version=2.0,
        driver_classes=[NativeGalilMotion],
        dyn_endpoints=galil_dyn_endpoints,
    )

    return app
