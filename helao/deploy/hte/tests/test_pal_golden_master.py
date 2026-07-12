"""Call-trace golden-master harness for the PAL driver (CARDS P4, Stage 1 of 3).

Extends the ``test_pal_ioloop_c1_guard.py`` pattern (``PAL.__new__`` bypass,
fake ``Active``, stubbed shim) to drive the REAL ``_PAL_IOloop`` /
``_sendcommand_main`` / 9-step ordered sample pipeline (spec
``CARDS_REFACTOR_P4_PAL.md`` :sec:`1.4`) across the 9-scenario matrix from
:sec:`4` ("Verification without hardware -- call-trace golden master").

What is REAL (driven, unmodified, byte-identical to the shipped driver):

* ``PAL._init_PAL_IOloop`` / ``PAL._PAL_IOloop`` / ``PAL._sendcommand_main``
  and every ``_sendcommand_check_*`` / ``_sendcommand_update_*`` helper.
* The 13 ``method_*`` builders (used directly where a scenario maps 1:1,
  else ``method_arbitrary`` for direct ``PalCam`` control -- ``repeat`` and
  multi-microcam combinations the 13 named builders don't expose).
* ``CAMS`` (only ``file_path`` is populated; real dispatch by
  ``_positiontype``/``sample_out_type`` per cam is untouched).

What is FAKED/STUBBED (the harness surface, matching the spec's
"Recorder fixtures" subsection):

* ``self.base``: a minimal fake exposing ``actionservermodel.estop``,
  ``dflt_file_conn_key()`` and an async ``contain_action`` that builds a
  ``RecordingActive`` -- exactly the K7b seam the C1 guard test also fakes.
* ``self.archive``: a ``RecordingShim`` standing in for
  ``SampleArchiveShim``, backed by an in-memory canned sample DB instead of
  an RPC to the SAMPLE server.
* ``PAL._sendcommand_submitjoblist_helper``: no SSH/Popen; still stamps
  ``palcam.joblist_time`` via the (fake) ``active.get_realtime_nowait()``.
* ``PAL._sendcommand_triggerwait``: injects fixed, counter-based timestamps
  instead of waiting on NI-DAQ trigger queues.
* ``time.time`` (module-global inside ``pal_driver``): pinned to a fixed
  constant so the ``_PAL_IOloop`` spacing-scheduler arithmetic
  (``cur_time - last_run_time``) is exactly reproducible.
* ``asyncio.sleep`` (module-global inside ``pal_driver``): records the
  REQUESTED duration and returns immediately (no real wait) -- this is what
  makes the mandatory 20s "wait for PAL to close" and the totalruns spacing
  waits fast AND deterministic.

No production code (``pal_driver.py``, ``pal_server.py``) is modified by
this file.

Run (conda env ``helao``, no pytest in this env -- run as a script, exactly
like ``test_pal_ioloop_c1_guard.py``)::

    conda run -n helao python helao/deploy/hte/tests/test_pal_golden_master.py

This writes baseline traces to ``.omc/artifacts/p4pal/baseline/<scenario>.json``
(gitignored) and prints a PASS/FAIL summary plus a determinism check (the
whole suite is captured twice in-process; the two JSON renderings must be
byte-identical).
"""

import asyncio
import itertools
import json
import time as time_module
import uuid
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from helao.core.error import ErrorCodes
from helao.core.models.data import DataModel
from helao.core.models.sample import (
    GasSample,
    LiquidSample,
    NoneSample,
    SampleInheritance,
    SampleStatus,
    SampleType,
)
from helao.helpers.premodels import Action
from helao.helpers.active_params import ActiveParams
from helao.deploy.hte.drivers.robot.enum import CAMS, Spacingmethod
from helao.deploy.hte.drivers.robot import pal_driver
from helao.deploy.hte.drivers.robot.pal_driver import PAL, PalCam

REPO_ROOT = Path(__file__).resolve().parents[4]
BASELINE_DIR = REPO_ROOT / ".omc" / "artifacts" / "p4pal" / "baseline"

_FIXED_CLOCK = 1_700_000_000.0
_DET_NS = uuid.UUID("00000000-0000-0000-0000-0000000000ab")


# ---------------------------------------------------------------------------
# determinism plumbing: pin time.time() and record (not perform) sleeps
# ---------------------------------------------------------------------------


class _SleepRecorder:
    """Records every ``asyncio.sleep`` delay requested inside ``pal_driver``.

    Never actually waits (beyond a single event-loop tick) so scenarios run
    in milliseconds instead of the real 20s+ the driver requests, while still
    faithfully capturing what WAS requested (spec: "captured as REQUESTED
    durations, not real sleeps").
    """

    def __init__(self):
        self.requests = []
        self._real_sleep = asyncio.sleep

    async def __call__(self, delay, result=None):
        self.requests.append(delay)
        await self._real_sleep(0)
        return result


class _patched_pal_driver_time_and_sleep:
    """Context manager pinning ``pal_driver.time.time`` and ``asyncio.sleep``.

    Both are module-global attributes (``time``/``asyncio`` are shared
    singletons), so this is scoped to one scenario drive at a time and always
    restored in ``finally`` -- scenarios run sequentially, never concurrently,
    inside this harness.
    """

    def __init__(self, sleep_recorder: _SleepRecorder):
        self._sleep_recorder = sleep_recorder
        self._real_time = time_module.time
        self._real_sleep = asyncio.sleep

    def __enter__(self):
        time_module.time = lambda: _FIXED_CLOCK
        asyncio.sleep = self._sleep_recorder
        return self

    def __exit__(self, *exc):
        time_module.time = self._real_time
        asyncio.sleep = self._real_sleep
        return False


# ---------------------------------------------------------------------------
# sample snapshot helper (deterministic, JSON-safe)
# ---------------------------------------------------------------------------


def _enum_val(value):
    if value is None:
        return None
    return getattr(value, "value", value)


def _sample_snapshot(sample) -> dict:
    if sample is None or isinstance(sample, NoneSample):
        return {"sample_type": None, "global_label": None}
    snap = {
        "sample_type": _enum_val(sample.sample_type),
        "global_label": sample.global_label,
        "sample_no": sample.sample_no,
        "sample_position": sample.sample_position,
        "status": [_enum_val(s) for s in sample.status],
        "inheritance": _enum_val(sample.inheritance),
        "sample_creation_timecode": sample.sample_creation_timecode,
        "action_uuid": [str(u) for u in sample.action_uuid],
    }
    if hasattr(sample, "volume_ml"):
        snap["volume_ml"] = sample.volume_ml
    if sample.sample_type == SampleType.assembly:
        snap["parts"] = [_sample_snapshot(p) for p in sample.parts]
    return snap


def _samples_snapshot(samples) -> list:
    return [_sample_snapshot(s) for s in (samples or [])]


def _liquid(label, sample_no, volume_ml=1.0, position=None):
    return LiquidSample(
        global_label=label,
        sample_no=sample_no,
        volume_ml=volume_ml,
        sample_position=position,
        status=[SampleStatus.preserved],
        machine_name="test",
    )


def _gas(label, sample_no, volume_ml=1.0, position=None):
    return GasSample(
        global_label=label,
        sample_no=sample_no,
        volume_ml=volume_ml,
        sample_position=position,
        status=[SampleStatus.preserved],
        machine_name="test",
    )


# ---------------------------------------------------------------------------
# RecordingShim -- stands in for SampleArchiveShim (S1)
# ---------------------------------------------------------------------------


class _UnifiedDBShim:
    def __init__(self, parent: "RecordingShim"):
        self._parent = parent

    async def get_samples(self, samples=None, *args, **kwargs):
        self._parent._maybe_raise("unified_db.get_samples")
        out = []
        for s in samples or []:
            label = getattr(s, "global_label", None)
            if label and label in self._parent.db:
                out.append(deepcopy(self._parent.db[label]))
            else:
                out.append(deepcopy(s))
        self._parent._log(
            "unified_db.get_samples",
            requested=[getattr(s, "global_label", None) for s in (samples or [])],
            result=_samples_snapshot(out),
        )
        return out

    async def new_samples(self, samples=None, *args, **kwargs):
        self._parent._maybe_raise("unified_db.new_samples")
        out = []
        for s in samples or []:
            s = deepcopy(s)
            if s.global_label is None:
                n = next(self._parent.ref_counter)
                s.global_label = f"canned__{_enum_val(s.sample_type)}__{n}"
            self._parent.db[s.global_label] = deepcopy(s)
            out.append(s)
        self._parent._log(
            "unified_db.new_samples", result=_samples_snapshot(out)
        )
        return out

    async def update_samples(self, samples=None, *args, **kwargs):
        self._parent._maybe_raise("unified_db.update_samples")
        for s in samples or []:
            if s.global_label:
                self._parent.db[s.global_label] = deepcopy(s)
        self._parent._log(
            "unified_db.update_samples", samples=_samples_snapshot(samples)
        )
        return None


class RecordingShim:
    """Scripted, in-memory stand-in for ``SampleArchiveShim`` that logs every call."""

    def __init__(self, trace: list, raise_on=None):
        self.trace = trace
        self.db = {}
        self.tray_db = {}
        self.custom_db = {}
        self.custom_dest_allowed_set = set()
        self.custom_assembly_allowed_set = set()
        self.custom_destroyed_set = set()
        self.ref_counter = itertools.count(1)
        self._tray_pos_counter = itertools.count(1)
        self._call_counts = {}
        # (method_name, 1-indexed call number) -> exception to raise (B6 probe)
        self._raise_on = raise_on
        self.unified_db = _UnifiedDBShim(self)

    # -- scenario setup helpers -------------------------------------------
    def seed_custom(self, position, sample):
        self.custom_db[position] = deepcopy(sample)
        if sample.global_label:
            self.db[sample.global_label] = deepcopy(sample)

    def allow_dest(self, position):
        self.custom_dest_allowed_set.add(position)

    def allow_assembly(self, position):
        self.custom_assembly_allowed_set.add(position)

    def mark_destroyed(self, position):
        self.custom_destroyed_set.add(position)

    # -- internals ----------------------------------------------------------
    def _maybe_raise(self, name):
        self._call_counts[name] = self._call_counts.get(name, 0) + 1
        if self._raise_on == (name, self._call_counts[name]):
            raise RuntimeError(f"scripted golden-master failure at {name}")

    def _log(self, name, **payload):
        self.trace.append({"domain": "shim", "call": name, **payload})

    # -- tray ---------------------------------------------------------------
    async def tray_query_sample(self, tray=None, slot=None, vial=None, *a, **k):
        self._maybe_raise("tray_query_sample")
        sample = self.tray_db.get((tray, slot, vial))
        self._log(
            "tray_query_sample",
            tray=tray,
            slot=slot,
            vial=vial,
            found=sample is not None,
        )
        if sample is None:
            return ErrorCodes.none, NoneSample()
        return ErrorCodes.none, deepcopy(sample)

    async def tray_get_next_full(
        self, after_tray=None, after_slot=None, after_vial=None, *a, **k
    ):
        self._maybe_raise("tray_get_next_full")
        result = {"tray": None, "slot": None, "vial": None}
        for (t, s, v), sample in sorted(self.tray_db.items()):
            if (t, s, v) > (after_tray or 0, after_slot or 0, after_vial or 0):
                result = {"tray": t, "slot": s, "vial": v}
                break
        self._log(
            "tray_get_next_full",
            after_tray=after_tray,
            after_slot=after_slot,
            after_vial=after_vial,
            result=result,
        )
        return result

    async def tray_new_position(self, req_vol=2.0, *a, **k):
        self._maybe_raise("tray_new_position")
        vial = next(self._tray_pos_counter)
        result = {"tray": 1, "slot": 1, "vial": vial}
        self._log("tray_new_position", req_vol=req_vol, result=result)
        return result

    async def tray_update_position(
        self, tray=None, slot=None, vial=None, sample=None, dilute=False, *a, **k
    ):
        self._maybe_raise("tray_update_position")
        self.tray_db[(tray, slot, vial)] = deepcopy(sample)
        if sample is not None and getattr(sample, "global_label", None):
            self.db[sample.global_label] = deepcopy(sample)
        self._log(
            "tray_update_position",
            tray=tray,
            slot=slot,
            vial=vial,
            dilute=dilute,
            sample=_sample_snapshot(sample),
        )
        return True

    # -- custom ---------------------------------------------------------------
    async def custom_query_sample(self, custom=None, *a, **k):
        self._maybe_raise("custom_query_sample")
        sample = self.custom_db.get(custom)
        self._log("custom_query_sample", custom=custom, found=sample is not None)
        if sample is None:
            return ErrorCodes.none, NoneSample()
        return ErrorCodes.none, deepcopy(sample)

    async def custom_update_position(
        self, custom=None, sample=None, dilute=False, *a, **k
    ):
        self._maybe_raise("custom_update_position")
        self.custom_db[custom] = deepcopy(sample)
        if sample is not None and getattr(sample, "global_label", None):
            self.db[sample.global_label] = deepcopy(sample)
        self._log(
            "custom_update_position",
            custom=custom,
            dilute=dilute,
            sample=_sample_snapshot(sample),
        )
        return True, sample

    async def custom_dest_allowed(self, custom=None, *a, **k):
        self._maybe_raise("custom_dest_allowed")
        result = custom in self.custom_dest_allowed_set
        self._log("custom_dest_allowed", custom=custom, result=result)
        return result

    async def custom_assembly_allowed(self, custom=None, *a, **k):
        self._maybe_raise("custom_assembly_allowed")
        result = custom in self.custom_assembly_allowed_set
        self._log("custom_assembly_allowed", custom=custom, result=result)
        return result

    async def custom_is_destroyed(self, custom=None, *a, **k):
        self._maybe_raise("custom_is_destroyed")
        result = custom in self.custom_destroyed_set
        self._log("custom_is_destroyed", custom=custom, result=result)
        return result

    # -- reference sample creation -------------------------------------------
    async def new_ref_samples(
        self,
        samples_in=None,
        sample_out_type="",
        sample_position="",
        action=None,
        combine_liquids=False,
        combine_gases=False,
        *a,
        **k,
    ):
        self._maybe_raise("new_ref_samples")
        n = next(self.ref_counter)
        cls = {
            SampleType.liquid: LiquidSample,
            "liquid": LiquidSample,
            SampleType.gas: GasSample,
            "gas": GasSample,
        }.get(sample_out_type, LiquidSample)
        ref = cls(sample_no=f"ref-{n}", sample_position=sample_position)
        self._log(
            "new_ref_samples",
            sample_out_type=_enum_val(sample_out_type),
            sample_position=sample_position,
            n_samples_in=len(samples_in or []),
        )
        return ErrorCodes.none, [ref]


# ---------------------------------------------------------------------------
# RecordingActive -- stands in for core.servers.base.Active (S2-S5)
# ---------------------------------------------------------------------------


class RecordingActive:
    def __init__(self, action: Action, trace: list, ts_counter: itertools.count):
        self.action = action
        self.trace = trace
        self._ts_counter = ts_counter
        self._fc_counter = itertools.count(1)
        self.finished = False
        self.error_code_at_finish = None
        self.split_count = 0
        self.action_uuid_history = [str(action.action_uuid)]
        if not action.file_conn_keys:
            action.file_conn_keys = [uuid.uuid5(_DET_NS, "dflt_file_conn_key")]

    def _log(self, name, **payload):
        self.trace.append({"domain": "active", "call": name, **payload})

    async def split(self):
        old_uuid = str(self.action.action_uuid)
        self.action.action_split = (self.action.action_split or 0) + 1
        new_uuid = uuid.uuid5(_DET_NS, f"split-{self.split_count}-{old_uuid}")
        self.action.action_uuid = new_uuid
        self.split_count += 1
        new_key = uuid.uuid5(_DET_NS, f"fc-{next(self._fc_counter)}-{old_uuid}")
        self.action.file_conn_keys = [new_key]
        self.action.samples_in = []
        self.action.samples_out = []
        self.action_uuid_history.append(str(new_uuid))
        self._log(
            "split",
            old_action_uuid=old_uuid,
            new_action_uuid=str(new_uuid),
            action_split=self.action.action_split,
            new_file_conn_key=new_key,
        )
        return [new_key]

    async def append_sample(self, samples, IO, action=None):
        action = action or self.action
        entries = []
        for sample in samples or []:
            if isinstance(sample, NoneSample):
                continue
            sample.action_uuid = [action.action_uuid]
            if sample.inheritance is None:
                sample.inheritance = SampleInheritance.allow_both
            if not sample.status:
                sample.reset_sample_status(SampleStatus.preserved)
            entries.append(_sample_snapshot(sample))
            if IO == "in":
                action.samples_in.append(sample)
            elif IO == "out":
                action.samples_out.append(sample)
        self._log("append_sample", IO=IO, samples=entries)

    def write_file_nowait(
        self,
        output_str,
        file_type,
        filename=None,
        file_group=None,
        header=None,
        sample_str=None,
        file_sample_label=None,
        json_data_keys=None,
        action=None,
    ):
        self._log("write_file_nowait", file_type=file_type, filename=filename)
        return f"/fake/RUNS/{filename or file_type}"

    def finish_hlo_header(self, file_conn_keys=None, realtime=None):
        self._log(
            "finish_hlo_header",
            file_conn_keys=[str(k) for k in (file_conn_keys or [])],
            realtime=realtime,
        )

    async def enqueue_data(self, datamodel: DataModel, action=None):
        self._log(
            "enqueue_data",
            data={str(k): v for k, v in datamodel.data.items()},
        )

    async def finish(self):
        self.finished = True
        self.error_code_at_finish = _enum_val(self.action.error_code)
        self._log(
            "finish",
            error_code=_enum_val(self.action.error_code),
            action_uuid=str(self.action.action_uuid),
            action_split=self.action.action_split,
        )
        return {}

    async def get_realtime(self, *a, **k):
        return next(self._ts_counter)

    def get_realtime_nowait(self, *a, **k):
        return next(self._ts_counter)

    def set_estop(self):
        pass


class _FakeBase:
    def __init__(self, trace: list, ts_counter: itertools.count):
        self.actionservermodel = SimpleNamespace(estop=False)
        self._trace = trace
        self._ts_counter = ts_counter
        self.created_actives = []

    def dflt_file_conn_key(self):
        return str(uuid.uuid5(_DET_NS, "dflt_file_conn_key"))

    async def contain_action(self, activeparams):
        active = RecordingActive(activeparams.action, self._trace, self._ts_counter)
        self.created_actives.append(active)
        return active


# ---------------------------------------------------------------------------
# PAL construction (mirrors test_pal_ioloop_c1_guard._make_pal, extended)
# ---------------------------------------------------------------------------

_CAMS_PATCHED = False


def _ensure_cam_paths():
    """Populate ``_cam.file_path`` (None by default outside real __init__).

    ``CAMS`` is a module-level singleton enum; this mutation is idempotent
    and mirrors what ``PAL.__init__`` does from server config, so it is safe
    to apply once per process.
    """
    global _CAMS_PATCHED
    if _CAMS_PATCHED:
        return
    for member in CAMS:
        member.value.file_path = "/dummy/cams"
    _CAMS_PATCHED = True


def _make_base(trace: list) -> _FakeBase:
    """Fresh fake ``app.base`` for one scenario (shares ``trace`` with the pal instance)."""
    ts_counter = itertools.count(1_000_000)
    return _FakeBase(trace, ts_counter)


def _make_pal(shim: RecordingShim) -> PAL:
    """Construct a bare ``PAL`` instance (Stage-2 seam: no ``self.base`` slot anymore --
    the job's ``Active`` is injected per-call via ``submit_job``, mirroring the endpoint's
    K7b ``contain_action`` + ``PALJobExec`` seam)."""
    _ensure_cam_paths()
    pal = PAL.__new__(PAL)
    pal.archive = shim
    pal.cams = CAMS
    pal.cam_config = None
    pal.cam_file_path = None
    pal.sshuser = ""
    pal.sshkey = ""
    pal.sshhost = "localhost"
    pal.timeout = 5.0
    pal.PAL_pid = None
    pal.triggers = False
    pal.IO_trigger_task = None
    pal.dev_trigger = None
    pal.triggerport_start = None
    pal.triggerport_continue = None
    pal.triggerport_done = None
    pal._job = None
    pal._worker_task = None
    pal.IO_measuring = False
    pal.IO_continue = False
    pal.IO_error = ErrorCodes.none
    pal.IO_action_run_counter = 0
    pal.FIFO_column_headings = [
        "samples_in",
        "samples_out",
        "epoch_PAL",
        "epoch_start",
        "epoch_continue",
        "epoch_done",
        "tool",
        "source",
        "volume_ul",
        "source_tray",
        "source_slot",
        "source_vial",
        "dest",
        "dest_tray",
        "dest_slot",
        "dest_vial",
        "logfile",
        "method",
    ]
    pal.palauxheader = [
        "Date",
        "Method",
        "Tool",
        "Source",
        "DestinationTray",
        "DestinationSlot",
        "DestinationVial",
        "Volume",
    ]
    pal.IOloop_run = False
    pal.IO_signalq = asyncio.Queue(1)
    pal.IO_trigger_startq = asyncio.Queue()
    pal.IO_trigger_continueq = asyncio.Queue()
    pal.IO_trigger_doneq = asyncio.Queue()

    async def _submitjoblist_stub(palcam):
        job = pal._job
        job.active.trace.append(
            {
                "domain": "driver",
                "call": "_sendcommand_submitjoblist_helper",
                "microcam_methods": [m.method for m in palcam.microcams],
            }
        )
        palcam.joblist_time = job.active.get_realtime_nowait()
        return ErrorCodes.none

    pal._sendcommand_submitjoblist_helper = _submitjoblist_stub
    pal._triggerwait_call_count = 0
    pal._triggerwait_stop_after = None  # 1-indexed call number to inject a stop
    ts = itertools.count(1)

    async def _triggerwait_stub(palaction):
        pal._triggerwait_call_count += 1
        base = next(ts) * 1_000_000
        palaction.start_time = base
        palaction.continue_time = base + 1
        palaction.done_time = base + 2
        pal.IO_continue = True
        pal._job.active.trace.append(
            {
                "domain": "driver",
                "call": "_sendcommand_triggerwait",
                "n": pal._triggerwait_call_count,
            }
        )
        if pal._triggerwait_stop_after == pal._triggerwait_call_count:
            pal.set_IO_signalq_nowait(False)
        return ErrorCodes.none

    pal._sendcommand_triggerwait = _triggerwait_stub
    return pal


def _make_action(name: str, action_params: dict, det_seed: str) -> Action:
    a = Action(
        action_name=name,
        action_params=action_params,
        samples_in=[],
        save_data=True,
    )
    a.action_uuid = uuid.uuid5(_DET_NS, det_seed)
    a.action_split = 0
    a.file_conn_keys = []
    return a


# ---------------------------------------------------------------------------
# generic single-job driver (Stage-2 seam)
#
# What changed vs. Stage 1: the endpoint's B4 guard (busy/estop/no-host,
# checked BEFORE contain_action) is now simulated explicitly here, matching
# pal_server.py's ``_pal_reject_busy``; a ``build_palcam_*`` helper replaces
# the old ``method_*`` call; ``contain_action`` happens in the harness (the
# endpoint's job) rather than inside the driver; ``submit_job`` replaces
# ``_init_PAL_IOloop`` for handing the job to the worker; and since this
# harness drives ``submit_job`` directly rather than the full
# ``PALJobExec``/``action_loop_task`` machinery (see the separate OQ-P3
# probe for that), the "framework tail" (stamp ``action.error_code`` from
# the job's terminal error, then call ``active.finish()``) is emulated here
# rather than happening for free inside ``action_loop_task``.
#
# What did NOT change: the RecordingActive/RecordingShim recorders and the
# trace/final JSON SHAPE are byte-identical to Stage 1 -- only how a job
# enters the loop changed, so a zero-delta diff against the Stage-1
# baseline genuinely proves the pipeline (S1-S6) is unchanged.
# ---------------------------------------------------------------------------


async def _drive_single_job(pal: PAL, base: _FakeBase, build_fn_name: str, A: Action):
    trace = base._trace
    sleep_recorder = _SleepRecorder()
    with _patched_pal_driver_time_and_sleep(sleep_recorder):
        task = asyncio.create_task(pal._PAL_IOloop())
        await asyncio.sleep(0)

        # -- B4 guard: mirrors pal_server.py's `_pal_reject_busy`, run BEFORE
        #    contain_action so a rejected call creates no artifact.
        rejected_dict = None
        if base.actionservermodel.estop:
            A.error_code = ErrorCodes.estop
            rejected_dict = A.as_dict()
        elif pal.sshhost is None:
            A.error_code = ErrorCodes.not_available
            rejected_dict = A.as_dict()
        elif pal.is_busy():
            A.error_code = ErrorCodes.in_progress
            rejected_dict = A.as_dict()

        active_ref = None
        endpoint_error_code = None
        if rejected_dict is None:
            palcam = getattr(pal, build_fn_name)(A.action_params, A.samples_in)
            active_ref = await base.contain_action(
                ActiveParams(action=A, file_conn_params_dict={})
            )
            job = await pal.submit_job(palcam, active_ref)
            # snapshot immediately after submit_job returns -- same instant
            # Stage 1 snapshotted `self.active.action.as_dict()`, i.e. before
            # the job has actually run.
            endpoint_error_code = _enum_val(active_ref.action.error_code)

            for _ in range(200_000):
                if job.done.is_set():
                    break
                await asyncio.sleep(0)

            # framework tail (normally `action_loop_task`): the last _poll()
            # error becomes action.error_code, then the framework finishes
            # the action. Emulated here since this harness bypasses the
            # Executor/action_loop_task machinery (direct submit_job).
            if job.error is not ErrorCodes.none:
                active_ref.action.error_code = job.error
            await active_ref.finish()
        else:
            endpoint_error_code = _enum_val(rejected_dict.get("error_code"))

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    final = {
        "io_error": _enum_val(pal.IO_error),
        "sleep_requests": list(sleep_recorder.requests),
        "endpoint_error_code": endpoint_error_code,
    }
    if active_ref is not None:
        final.update(
            {
                "finished": active_ref.finished,
                "error_code_at_finish": active_ref.error_code_at_finish,
                "split_count": active_ref.split_count,
                "action_uuid_history": active_ref.action_uuid_history,
            }
        )
    return {"trace": trace, "final": final}


# ---------------------------------------------------------------------------
# scenarios a - i
# ---------------------------------------------------------------------------


async def _scenario_a():
    """(a) single microcam, 1 run -- simple custom->custom transfer."""
    trace = []
    shim = RecordingShim(trace)
    shim.seed_custom("src_a", _liquid("src_a__liquid", "a1", volume_ml=5.0, position="src_a"))
    shim.allow_dest("dst_a")
    pal = _make_pal(shim)
    base = _make_base(trace)
    A = _make_action(
        "PAL_transfer_custom_custom",
        {
            "tool": "LS1",
            "volume_ul": 100,
            "source": "src_a",
            "dest": "dst_a",
            "sampleperiod": [0.0],
            "spacingmethod": Spacingmethod.linear,
            "spacingfactor": 1.0,
            "timeoffset": 0.0,
            "wash1": 0,
            "wash2": 0,
            "wash3": 0,
            "wash4": 0,
        },
        "scenario-a",
    )
    return await _drive_single_job(pal, base, "build_palcam_transfer_custom_custom", A)


async def _scenario_b():
    """(b) 3 microcams incl. an archive dest (next-empty-vial) -> 2 splits."""
    trace = []
    shim = RecordingShim(trace)
    shim.seed_custom("anec_src", _liquid("anec_src__liquid", "b1", volume_ml=10.0, position="anec_src"))
    shim.allow_dest("Injector 2")
    shim.allow_dest("Injector 1")
    pal = _make_pal(shim)
    base = _make_base(trace)
    A = _make_action(
        "PAL_ANEC_aliquot",
        {
            "toolGC": "LS1",
            "volume_ul_GC": 5,
            "toolarchive": "LS1",
            "volume_ul_archive": 20,
            "source": "anec_src",
            "wash1": 0,
            "wash2": 0,
            "wash3": 0,
            "wash4": 0,
        },
        "scenario-b",
    )
    return await _drive_single_job(pal, base, "build_palcam_ANEC_aliquot", A)


async def _scenario_c():
    """(c) microcam repeat=2 (B2 samples-reset quirk): built via method_arbitrary."""
    trace = []
    shim = RecordingShim(trace)
    shim.seed_custom("src_c", _liquid("src_c__liquid", "c1", volume_ml=8.0, position="src_c"))
    shim.allow_dest("dst_c")
    pal = _make_pal(shim)
    base = _make_base(trace)
    A = _make_action(
        "PAL_arbitrary",
        {
            "totalruns": 1,
            "sampleperiod": [],
            "spacingmethod": "linear",
            "spacingfactor": 1.0,
            "timeoffset": 0.0,
            "microcams": [
                {
                    "method": "transfer_custom_custom",
                    "tool": "LS1",
                    "volume_ul": 50,
                    "requested_source": {"position": "src_c"},
                    "requested_dest": {"position": "dst_c"},
                    "wash1": 0,
                    "wash2": 0,
                    "wash3": 0,
                    "wash4": 0,
                    "repeat": 2,
                }
            ],
        },
        "scenario-c",
    )
    return await _drive_single_job(pal, base, "build_palcam_arbitrary", A)


async def _scenario_d():
    """(d) totalruns=3, linear then geometric spacing (sleep-request arithmetic)."""
    result = {}
    for spacing_name, spacingmethod, spacingfactor in (
        ("linear", Spacingmethod.linear, 1.0),
        ("geometric", Spacingmethod.geometric, 2.0),
    ):
        trace = []
        shim = RecordingShim(trace)
        src, dst = f"src_d_{spacing_name}", f"dst_d_{spacing_name}"
        shim.seed_custom(src, _liquid(f"{src}__liquid", f"d_{spacing_name}", volume_ml=8.0, position=src))
        shim.allow_dest(dst)
        pal = _make_pal(shim)
        base = _make_base(trace)
        A = _make_action(
            "PAL_transfer_custom_custom",
            {
                "tool": "LS1",
                "volume_ul": 50,
                "source": src,
                "dest": dst,
                "sampleperiod": [0.0, 5.0, 10.0],
                "spacingmethod": spacingmethod,
                "spacingfactor": spacingfactor,
                "timeoffset": 0.0,
                "wash1": 0,
                "wash2": 0,
                "wash3": 0,
                "wash4": 0,
            },
            f"scenario-d-{spacing_name}",
        )
        result[spacing_name] = await _drive_single_job(
            pal, base, "build_palcam_transfer_custom_custom", A
        )
    return result


async def _scenario_e():
    """(e) assembly creation/update (pipeline steps 2/6 part handling)."""
    trace = []
    shim = RecordingShim(trace)
    shim.seed_custom("src_e", _liquid("src_e__liquid", "e1", volume_ml=6.0, position="src_e"))
    # a different sample TYPE already at dest -> assembly-creation branch
    shim.seed_custom("dst_e", _gas("dst_e__gas", "e2", volume_ml=2.0, position="dst_e"))
    shim.allow_dest("dst_e")
    shim.allow_assembly("dst_e")
    pal = _make_pal(shim)
    base = _make_base(trace)
    A = _make_action(
        "PAL_transfer_custom_custom",
        {
            "tool": "LS1",
            "volume_ul": 30,
            "source": "src_e",
            "dest": "dst_e",
            "sampleperiod": [0.0],
            "spacingmethod": Spacingmethod.linear,
            "spacingfactor": 1.0,
            "timeoffset": 0.0,
            "wash1": 0,
            "wash2": 0,
            "wash3": 0,
            "wash4": 0,
        },
        "scenario-e",
    )
    return await _drive_single_job(pal, base, "build_palcam_transfer_custom_custom", A)


async def _scenario_f():
    """(f) destroyed-dest (GC/HPLC inject)."""
    trace = []
    shim = RecordingShim(trace)
    shim.seed_custom("src_f", _liquid("src_f__liquid", "f1", volume_ml=4.0, position="src_f"))
    shim.allow_dest("hplc_injector")
    shim.mark_destroyed("hplc_injector")
    pal = _make_pal(shim)
    base = _make_base(trace)
    A = _make_action(
        "PAL_injection_custom_HPLC",
        {
            "tool": "LS1",
            "volume_ul": 10,
            "source": "src_f",
            "dest": "hplc_injector",
            "wash1": 0,
            "wash2": 0,
            "wash3": 0,
            "wash4": 0,
        },
        "scenario-f",
    )
    return await _drive_single_job(pal, base, "build_palcam_injection_custom_HPLC", A)


async def _scenario_g():
    """(g) shim raises mid-pipeline (B6 error funneling)."""
    trace = []
    shim = RecordingShim(trace, raise_on=("unified_db.update_samples", 1))
    shim.seed_custom("src_g", _liquid("src_g__liquid", "g1", volume_ml=5.0, position="src_g"))
    shim.allow_dest("dst_g")
    pal = _make_pal(shim)
    base = _make_base(trace)
    A = _make_action(
        "PAL_transfer_custom_custom",
        {
            "tool": "LS1",
            "volume_ul": 100,
            "source": "src_g",
            "dest": "dst_g",
            "sampleperiod": [0.0],
            "spacingmethod": Spacingmethod.linear,
            "spacingfactor": 1.0,
            "timeoffset": 0.0,
            "wash1": 0,
            "wash2": 0,
            "wash3": 0,
            "wash4": 0,
        },
        "scenario-g",
    )
    return await _drive_single_job(pal, base, "build_palcam_transfer_custom_custom", A)


async def _scenario_h():
    """(h) stop signal between palactions (repeat=1, same microcam, i=0)."""
    trace = []
    shim = RecordingShim(trace)
    shim.seed_custom("src_h", _liquid("src_h__liquid", "h1", volume_ml=9.0, position="src_h"))
    shim.allow_dest("dst_h")
    pal = _make_pal(shim)
    base = _make_base(trace)
    pal._triggerwait_stop_after = 1  # push a stop signal right after palaction #1
    A = _make_action(
        "PAL_arbitrary",
        {
            "totalruns": 1,
            "sampleperiod": [],
            "spacingmethod": "linear",
            "spacingfactor": 1.0,
            "timeoffset": 0.0,
            "microcams": [
                {
                    "method": "transfer_custom_custom",
                    "tool": "LS1",
                    "volume_ul": 25,
                    "requested_source": {"position": "src_h"},
                    "requested_dest": {"position": "dst_h"},
                    "wash1": 0,
                    "wash2": 0,
                    "wash3": 0,
                    "wash4": 0,
                    "repeat": 1,
                }
            ],
        },
        "scenario-h",
    )
    return await _drive_single_job(pal, base, "build_palcam_arbitrary", A)


async def _scenario_i():
    """(i) busy rejection (B4): guard fires before contain_action -- no artifact."""
    trace = []
    shim = RecordingShim(trace)
    pal = _make_pal(shim)
    base = _make_base(trace)
    pal.IO_measuring = True  # simulate "PAL method already in progress"
    A = _make_action(
        "PAL_transfer_custom_custom",
        {
            "tool": "LS1",
            "volume_ul": 100,
            "source": "src_i",
            "dest": "dst_i",
            "sampleperiod": [0.0],
            "spacingmethod": Spacingmethod.linear,
            "spacingfactor": 1.0,
            "timeoffset": 0.0,
            "wash1": 0,
            "wash2": 0,
            "wash3": 0,
            "wash4": 0,
        },
        "scenario-i",
    )
    # -- B4 guard only: mirrors pal_server.py's `_pal_reject_busy`, run
    #    BEFORE build_palcam_*/contain_action -- a busy rejection must touch
    #    neither the shim nor an Active.
    if base.actionservermodel.estop:
        A.error_code = ErrorCodes.estop
    elif pal.sshhost is None:
        A.error_code = ErrorCodes.not_available
    elif pal.is_busy():
        A.error_code = ErrorCodes.in_progress
    result = A.as_dict()
    return {
        "trace": trace,
        "final": {
            "endpoint_error_code": _enum_val(result.get("error_code")),
            "active_created": len(base.created_actives) > 0,
            "n_shim_or_active_calls": len(trace),
        },
    }


SCENARIOS = {
    "a_single_microcam_one_run": _scenario_a,
    "b_three_microcams_archive_dest_two_splits": _scenario_b,
    "c_microcam_repeat_two": _scenario_c,
    "d_totalruns_spacing": _scenario_d,
    "e_assembly_creation_update": _scenario_e,
    "f_destroyed_dest_injection": _scenario_f,
    "g_shim_raises_midpipeline": _scenario_g,
    "h_stop_signal_between_palactions": _scenario_h,
    "i_busy_rejection": _scenario_i,
}


async def run_all_scenarios(base_dir: Path) -> dict:
    base_dir.mkdir(parents=True, exist_ok=True)
    results = {}
    for name, coro_fn in SCENARIOS.items():
        data = await coro_fn()
        payload = {"scenario": name, **data} if "trace" in data else {
            "scenario": name,
            **data,
        }
        text = json.dumps(payload, indent=2, sort_keys=True, default=str)
        (base_dir / f"{name}.json").write_text(text)
        results[name] = text
    return results


# ---------------------------------------------------------------------------
# assertions (lightweight; the real "gate" is Stage-2 diffing against these
# baselines, not exhaustive behavioral proof here)
# ---------------------------------------------------------------------------


def _check(cond, msg, failures):
    if not cond:
        failures.append(msg)


async def _run_and_check() -> list:
    failures = []

    a = await _scenario_a()
    _check(a["final"]["finished"], "a: action did not finish", failures)
    _check(a["final"]["io_error"] == "none", "a: unexpected IO_error", failures)
    _check(a["final"]["split_count"] == 0, "a: expected no splits", failures)

    b = await _scenario_b()
    _check(b["final"]["finished"], "b: action did not finish", failures)
    _check(b["final"]["split_count"] == 2, "b: expected 2 splits", failures)

    c = await _scenario_c()
    _check(c["final"]["finished"], "c: action did not finish", failures)
    _check(c["final"]["split_count"] == 0, "c: repeat must not split", failures)
    append_calls = [
        e for e in c["trace"] if e.get("domain") == "active" and e["call"] == "append_sample"
    ]
    _check(len(append_calls) == 6, "c: expected 3 repeats x (in,out) = 6 append_sample calls", failures)

    d = await _scenario_d()
    for spacing_name in ("linear", "geometric"):
        sub = d[spacing_name]
        _check(sub["final"]["finished"], f"d[{spacing_name}]: did not finish", failures)
        _check(
            len(sub["final"]["sleep_requests"]) >= 3,
            f"d[{spacing_name}]: expected >=3 sleep requests (3x 20s drain + spacing)",
            failures,
        )

    e = await _scenario_e()
    _check(e["final"]["finished"], "e: action did not finish", failures)
    new_ref_calls = [
        ev for ev in e["trace"] if ev.get("domain") == "shim" and ev["call"] == "new_ref_samples"
    ]
    _check(len(new_ref_calls) >= 2, "e: assembly creation should call new_ref_samples >=2x", failures)

    f = await _scenario_f()
    _check(f["final"]["finished"], "f: action did not finish", failures)
    _check(f["final"]["io_error"] == "none", "f: unexpected IO_error", failures)

    g = await _scenario_g()
    _check(g["final"]["finished"], "g: action must still finish (B6 funnel)", failures)
    _check(
        g["final"]["io_error"] != "none",
        "g: shim raise must produce a terminal IO_error",
        failures,
    )
    _check(
        g["final"]["error_code_at_finish"] not in (None, "none"),
        "g: finalized action must carry non-none error_code (C1 contract)",
        failures,
    )

    h = await _scenario_h()
    _check(h["final"]["finished"], "h: action did not finish", failures)
    triggerwait_calls = [
        ev for ev in h["trace"] if ev.get("domain") == "driver" and ev["call"] == "_sendcommand_triggerwait"
    ]
    _check(
        len(triggerwait_calls) == 1,
        "h: stop signal should prevent the 2nd palaction's triggerwait",
        failures,
    )

    i = await _scenario_i()
    _check(
        i["final"]["endpoint_error_code"] == "in_progress",
        "i: busy call must reject with in_progress",
        failures,
    )
    _check(not i["final"]["active_created"], "i: busy rejection must not create an Active", failures)
    _check(
        i["final"]["n_shim_or_active_calls"] == 0,
        "i: busy rejection must produce zero shim/active calls (no artifact)",
        failures,
    )

    return failures


def main():
    failures = asyncio.run(_run_and_check())
    if failures:
        print("SCENARIO CHECKS FAILED:")
        for f in failures:
            print(f"  - {f}")
    else:
        print("ALL 9 SCENARIO CHECKS PASSED (a-i)")

    # capture baseline (single canonical copy under .omc, gitignored)
    baseline_texts = asyncio.run(run_all_scenarios(BASELINE_DIR))
    print(f"Baseline traces written to: {BASELINE_DIR}")

    # determinism: capture twice more (in separate dirs) and diff byte-for-byte
    import tempfile

    with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
        run1 = asyncio.run(run_all_scenarios(Path(d1)))
        run2 = asyncio.run(run_all_scenarios(Path(d2)))
        det_failures = []
        for name in SCENARIOS:
            if run1[name] != run2[name]:
                det_failures.append(name)
        if det_failures:
            print(f"DETERMINISM CHECK FAILED for: {det_failures}")
        else:
            print("DETERMINISM CHECK PASSED: two capture runs byte-identical for all 9 scenarios")

    # also cross-check the first baseline capture against a fresh run
    # (belt-and-suspenders against ordering bugs introduced by the checked
    # assertion pass mutating shared global state, e.g. the CAMS singleton)
    if failures or det_failures:
        raise SystemExit(1)
    print("ALL GOLDEN-MASTER HARNESS CHECKS PASSED")


if __name__ == "__main__":
    main()
