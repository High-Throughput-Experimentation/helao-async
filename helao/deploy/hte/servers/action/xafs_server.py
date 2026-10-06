"""FastAPI action server for the easyXAFS spectrometer (via the sidecar process).

``normal_scan`` runs one wafer-grid scan: the endpoint opens the action and
:class:`XafsScanExec` drives the sidecar through :class:`XafsSidecarDriver`,
streaming one data row per scan point and writing the MCA array and the
advanced-calibration json when the scan ends. Driver calls are sync HTTP and
go through ``asyncio.to_thread``.
"""

__all__ = ["makeApp"]

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Union

import aiofiles
from fastapi import Body

from helao.core.drivers.helao_driver import DriverResponseType
from helao.core.error import ErrorCodes
from helao.core.models.data import DataModel
from helao.core.models.file import HloHeaderModel
from helao.core.models.hlostatus import HloStatus
from helao.core.models.run_dir import redirect_manual_dir
from helao.core.models.sample import (
    AssemblySample,
    GasSample,
    LiquidSample,
    NoneSample,
    SolidSample,
)
from helao.hexagon.app.action_context import ActionContext
from helao.hexagon.app.action_host import ActionHost
from helao.helpers import helao_logging as logging
from helao.helpers.executor import Executor
from helao.helpers.sample_api import UnifiedSampleDataAPI

from ...drivers.xafs.driver import XafsSidecarDriver
from ...drivers.xafs.naming import (
    apply_affine,
    reference_name_from_label,
    reference_savename,
    sample_savename,
)

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

#: Executor backstop: stop and error after ``est_total * FACTOR + MARGIN`` s,
#: measured from the first non-queued sidecar state.
TIMEOUT_FACTOR = 2.0
TIMEOUT_MARGIN_S = 300.0
#: Seconds between ``GET /jobs/{id}`` polls while calibrating.
CALIBRATE_POLL_S = 1.0

_TERMINAL = {"done", "stopped", "error"}
_OK_END = {"done", "stopped"}


class ScanSetupError(Exception):
    """Pre-scan failure (sample/position/save_dir); no sidecar call is made."""

    def __init__(self, message: str, code: ErrorCodes = ErrorCodes.cmd_error):
        super().__init__(message)
        self.code = code


class XafsScanExec(Executor):
    """Executor for one sidecar scan.

    ``_pre_exec`` resolves the stage XY and savename and drops the
    ``.helao_recorded`` marker; ``_exec`` starts the scan; ``_poll`` streams new
    rows until the sidecar state is terminal; ``_post_exec`` writes the MCA npz
    and the track json. Rows are enqueued one per scan point from inside the
    poll (a poll can yield many rows; the runner would write only one dict).
    A stopped scan finishes with whatever status the runner assigns on manual
    stop.
    """

    def __init__(self, *args, server_params: dict, unified_db, **kwargs):
        super().__init__(*args, **kwargs)
        self.driver = self.active.driver
        self.server_params = server_params
        self.unified_db = unified_db
        self.scan_id = None
        self.n_rows = 0
        self.savename = ""
        self.xy = (0.0, 0.0)
        self._t0 = None
        self._failed = False

    # -- helpers ---------------------------------------------------------

    async def _to_thread(self, fn, *args, **kwargs):
        return await asyncio.to_thread(fn, *args, **kwargs)

    def _record_error(self, message: str) -> dict:
        """Mark the scan failed; the poll loop ends with ``cmd_error``."""
        LOGGER.error(f"xafs scan: {message}")
        self.active.action.action_params["sidecar_error"] = message
        self._failed = True
        return {"error": ErrorCodes.cmd_error, "status": HloStatus.errored, "data": {}}

    async def _resolve(self) -> None:
        """Set ``self.xy`` and ``self.savename`` from the sample, or raise."""
        p = self.active.action.action_params
        element, run_use = p["element"], p["run_use"]
        if not element:
            raise ScanSetupError("element is required")
        if not p["save_dir"]:
            raise ScanSetupError("save_dir is required")
        samples = self.active.action.samples_in
        if len(samples) != 1:
            raise ScanSetupError(
                f"expected exactly one sample, got {len(samples)}", ErrorCodes.no_sample
            )
        sample = samples[0]
        label = sample.get_global_label()
        refs = self.server_params.get("references", {})
        plate_id = getattr(sample, "plate_id", None)
        sample_no = getattr(sample, "sample_no", None)
        if label in refs:
            if run_use not in ("izero", "energy_calib"):
                raise ScanSetupError(
                    f"reference sample {label} needs run_use izero or energy_calib, "
                    f"got {run_use!r}"
                )
            ref = refs[label]
            self.xy = (float(ref["x_mm"]), float(ref["y_mm"]))
            self.savename = reference_savename(
                element, run_use, reference_name_from_label(label, refs)
            )
        elif plate_id is not None and sample_no is not None:
            if run_use != "data":
                raise ScanSetupError(
                    f"plate sample {label} needs run_use data, got {run_use!r}"
                )
            xylist = await self.unified_db.get_samples_xy([sample])
            platexy = xylist[0] if xylist else [None, None]
            if platexy[0] is None or platexy[1] is None:
                raise ScanSetupError(
                    f"no platemap xy for {label}", ErrorCodes.not_available
                )
            self.xy = apply_affine(
                self.server_params["platexy_to_stage"], platexy[0], platexy[1]
            )
            self.savename = sample_savename(
                element, p["scan_index"], sample_no, self.xy[0], self.xy[1]
            )
        else:
            raise ScanSetupError(
                f"sample {label} is neither a plate sample nor a registered reference",
                ErrorCodes.no_sample,
            )

    async def _drain(self) -> bool:
        """Enqueue every new sidecar row as one data row; False on HTTP failure."""
        r = await self._to_thread(self.driver.rows_since, self.scan_id, self.n_rows)
        if r.response != DriverResponseType.success:
            self._record_error(r.message)
            return False
        cols, rows = r.data["columns"], r.data["rows"]
        fck = self.active.action.file_conn_keys[0]
        for row in rows:
            self.active.enqueue_data_nowait(
                DataModel(
                    data={fck: dict(zip(cols, row))},
                    errors=[],
                    status=HloStatus.active,
                )
            )
        self.n_rows += len(rows)
        return True

    # -- executor phases -------------------------------------------------

    async def _pre_exec(self) -> dict:
        try:
            await self._resolve()
            save_dir = Path(self.active.action.action_params["save_dir"])
            save_dir.mkdir(parents=True, exist_ok=True)
            (save_dir / ".helao_recorded").touch()
        except ScanSetupError as exc:
            LOGGER.error(f"xafs scan setup: {exc}")
            self.active.action.action_params["sidecar_error"] = str(exc)
            return {"error": exc.code}
        except OSError as exc:
            LOGGER.error(f"xafs scan setup: cannot write marker: {exc}")
            self.active.action.action_params["sidecar_error"] = str(exc)
            return {"error": ErrorCodes.cmd_error}
        return {"error": ErrorCodes.none}

    async def _exec(self) -> dict:
        p = self.active.action.action_params
        r = await self._to_thread(
            self.driver.start_scan,
            scan_def=p["scan_def"],
            x_mm=self.xy[0],
            y_mm=self.xy[1],
            xchanger_station=p["xchanger_station"],
            savename=self.savename,
            save_dir=p["save_dir"],
            duration_scale=p["duration_scale"],
        )
        if r.response != DriverResponseType.success:
            self._record_error(r.message)  # next _poll ends the loop at once
            return {"error": ErrorCodes.cmd_error, "data": {}}
        self.scan_id = r.data["scan_id"]
        return {"error": ErrorCodes.none, "data": {}}

    async def _poll(self) -> dict:
        if self._failed or self.scan_id is None:
            return {
                "error": ErrorCodes.cmd_error,
                "status": HloStatus.errored,
                "data": {},
            }
        r = await self._to_thread(self.driver.scan_state, self.scan_id)
        if r.response != DriverResponseType.success:
            return self._record_error(r.message)
        st = r.data
        state = st["state"]
        now = time.monotonic()
        if self._t0 is None and state != "queued":
            self._t0 = now
        if self._t0 is not None:
            limit = (st.get("est_total") or 0.0) * TIMEOUT_FACTOR + TIMEOUT_MARGIN_S
            if now - self._t0 > limit:
                await self._to_thread(self.driver.stop)
                return self._record_error(f"scan timed out after {limit:.0f} s")
        if not await self._drain():
            return {
                "error": ErrorCodes.cmd_error,
                "status": HloStatus.errored,
                "data": {},
            }
        if state == "error":
            return self._record_error(st.get("error") or "sidecar scan error")
        if state in _OK_END:
            return {"error": ErrorCodes.none, "status": HloStatus.finished, "data": {}}
        return {"error": ErrorCodes.none, "status": HloStatus.active, "data": {}}

    async def _manual_stop(self) -> dict:
        r = await self._to_thread(self.driver.stop)
        if r.response != DriverResponseType.success:
            LOGGER.error(f"xafs stop failed: {r.message}")
            return {"error": ErrorCodes.cmd_error}
        return {"error": ErrorCodes.none}

    async def _wait_terminal(self):
        """Final scan-state dict once terminal (bounded), else None."""
        deadline = time.monotonic() + TIMEOUT_MARGIN_S
        while True:
            r = await self._to_thread(self.driver.scan_state, self.scan_id)
            if r.response != DriverResponseType.success:
                return None
            if r.data["state"] in _TERMINAL:
                return r.data
            if time.monotonic() >= deadline:
                return None
            await asyncio.sleep(self.poll_rate)

    async def _post_exec(self) -> dict:
        action = self.active.action
        if self.scan_id is None or self._failed:
            return {"error": ErrorCodes.none, "data": {}}
        final = await self._wait_terminal()
        if final is None or final["state"] not in _OK_END:
            action.error_code = ErrorCodes.cmd_error
            action.action_params["sidecar_error"] = (
                (final or {}).get("error") or "scan did not end cleanly"
            )
            return {"error": ErrorCodes.cmd_error, "data": {}}
        if not await self._drain():
            action.error_code = ErrorCodes.cmd_error
            return {"error": ErrorCodes.cmd_error, "data": {}}
        action.action_params["exd_path"] = final["exd_path"]

        mcas = await self._to_thread(self.driver.fetch_mcas, self.scan_id)
        arts = await self._to_thread(self.driver.fetch_artifacts, self.scan_id)
        if (
            mcas.response != DriverResponseType.success
            or arts.response != DriverResponseType.success
        ):
            LOGGER.error(f"xafs artifacts: {mcas.message}; {arts.message}")
            action.error_code = ErrorCodes.cmd_error
            return {"error": ErrorCodes.cmd_error, "data": {}}

        save_root = str(self.active.base.helaodirs.save_root)
        if action.manual_action:
            save_root = redirect_manual_dir(save_root)
        out_dir = os.path.join(save_root, action.action_output_dir)
        os.makedirs(out_dir, exist_ok=True)
        npz_path = os.path.join(out_dir, f"xafs_mca-{self.savename}.npz")
        async with aiofiles.open(npz_path, "wb") as f:
            await f.write(mcas.data["npz"])
        await self.active.track_file(
            "xafsmca__npz_file", npz_path, samples=action.samples_in
        )

        track = arts.data["scan_def"].get("advanced_calibration")
        if track is None:
            LOGGER.warning("scan_def has no advanced_calibration; no track json")
        else:
            await self.active.write_file(
                json.dumps(track),
                "xafstrack__json_file",
                filename=f"xafs_track-{self.savename}.json",
            )
        action.action_params.update(arts.data["metadata"])
        return {"error": ErrorCodes.none, "data": {}}


async def xafs_dyn_endpoints(app: ActionHost):
    """Connect the sidecar driver, build the sample DB, register the actions."""
    app.server_params["allow_concurrent_actions"] = False

    app.driver: XafsSidecarDriver
    # connect() may spawn the sidecar and wait for it; keep it off the loop.
    connect_resp = await asyncio.to_thread(app.driver.connect)
    LOGGER.info(f"xafs connect() returned status={connect_resp.status}")

    app.unified_db = UnifiedSampleDataAPI(app.base)

    async def finish_with(active, resp, key: str) -> dict:
        """Record a driver response, mark errored if it failed, finish."""
        if resp.response != DriverResponseType.success:
            LOGGER.error(f"xafs {key}: {resp.message}")
            active.action.append_action_status(HloStatus.errored)
            active.action.error_code = ErrorCodes.cmd_error
        await active.enqueue_data_dflt(datadict={key: resp.data, "message": resp.message})
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.action()
    async def normal_scan(
        ctx: ActionContext,
        scan_def: dict = {},
        element: str = "",
        run_use: str = "data",
        xchanger_station: int = 0,
        duration_scale: float = 1.0,
        scan_index: int = 0,
        save_dir: str = "",
        fast_samples_in: list[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = Body([], embed=True),
    ):
        """Run one wafer-grid scan on the sidecar and stream its rows.

        Args:
            scan_def: easyXAFS scan definition (passed to the sidecar as is).
            element: Element symbol used in the savename.
            run_use: ``data``, ``izero`` or ``energy_calib``.
            xchanger_station: xChanger station for the scan.
            duration_scale: Scale applied to the scan dwell times.
            scan_index: Grid index used in the sample savename.
            save_dir: Run folder the sidecar writes the exd archive into.
            fast_samples_in: The single sample (plate sample or reference).
        """
        A = ctx.action
        active = await ctx.begin(
            action_abbr="xafs_normal",
            file_type="xafsscan__helao_file",
            hloheader=HloHeaderModel(
                optional={"scan_def": A.action_params["scan_def"]}
            ),
            sample_global_labels=[s.get_global_label() for s in A.samples_in],
        )
        active.finish_hlo_header(
            realtime=active.get_realtime_nowait(),
            file_conn_keys=active.action.file_conn_keys,
        )
        executor = XafsScanExec(
            active=active,
            oneoff=False,
            poll_rate=0.2,
            server_params=app.server_params,
            unified_db=app.unified_db,
        )
        return active.start_executor(executor)

    @app.action()
    async def initialize(
        ctx: ActionContext,
        mono: bool = True,
        ketek: bool = True,
        wafer_stage: bool = True,
        xchanger: bool = True,
        proto: bool = True,
    ):
        """Run the sidecar start-up for the selected devices."""
        active = await ctx.begin()
        p = active.action.action_params
        flags = {k: p[k] for k in ("mono", "ketek", "wafer_stage", "xchanger", "proto")}
        resp = await asyncio.to_thread(app.driver.initialize, flags)
        return await finish_with(active, resp, "initialize")

    @app.action()
    async def calibrate(ctx: ActionContext, devices: list[str] = ["mono"]):
        """Calibrate the listed devices and wait for the sidecar job to end."""
        active = await ctx.begin()
        resp = await asyncio.to_thread(
            app.driver.calibrate, active.action.action_params["devices"]
        )
        if resp.response == DriverResponseType.success:
            job_id = resp.data["job_id"]
            while True:
                resp = await asyncio.to_thread(app.driver.job_state, job_id)
                if (
                    resp.response != DriverResponseType.success
                    or resp.data["state"] != "running"
                ):
                    break
                await asyncio.sleep(CALIBRATE_POLL_S)
            if (
                resp.response == DriverResponseType.success
                and resp.data["state"] == "error"
            ):
                resp.response = DriverResponseType.failed
                resp.message = f"calibration failed: {resp.data['error']}"
        return await finish_with(active, resp, "calibrate")

    @app.action()
    async def status(ctx: ActionContext):
        """Record the driver status (sidecar reachability / current scan)."""
        active = await ctx.begin()
        resp = await asyncio.to_thread(app.driver.get_status)
        return await finish_with(active, resp, "status")

    @app.action()
    async def set_xray(ctx: ActionContext, kv: float, ma: float):
        """Set the x-ray tube voltage and current."""
        active = await ctx.begin()
        p = active.action.action_params
        resp = await asyncio.to_thread(app.driver.xray, kv=p["kv"], ma=p["ma"])
        return await finish_with(active, resp, "set_xray")

    @app.action()
    async def shutter(ctx: ActionContext, state: str = "open"):
        """Open or close the x-ray shutter."""
        active = await ctx.begin()
        state = active.action.action_params["state"]
        if state not in ("open", "close"):
            LOGGER.error(f"xafs shutter: bad state {state!r}")
            active.action.append_action_status(HloStatus.errored)
            active.action.error_code = ErrorCodes.cmd_error
            finished_action = await active.finish()
            return finished_action.as_dict()
        resp = await asyncio.to_thread(app.driver.xray, shutter=state)
        return await finish_with(active, resp, "shutter")


def makeApp(server_key) -> ActionHost:
    """Build the ActionHost app for the easyXAFS sidecar action server."""
    return ActionHost(
        server_key=server_key,
        server_title=server_key,
        description="easyXAFS spectrometer server",
        version=0.1,
        driver_classes=[XafsSidecarDriver],
        dyn_endpoints=xafs_dyn_endpoints,
    )
