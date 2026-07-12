"""Output golden-master harness for the legacy ``Active`` action wrapper
(CARDS P6, Stage S0a -- the behaviour-preservation foundation for the full
``Base``/``Active`` decomposition specced in ``CARDS_REFACTOR_P6.md``).

This is the P6 analog of ``test_orch_dispatch_golden_master.py`` (P5): it
FREEZES the observable output of :class:`helao.core.servers.base.Active`
*before* any refactoring, so every later P6 stage can gate against a
byte/multiset-stable reference. Test/harness code only -- no production module
is modified by this file.

What is REAL (driven, unmodified, byte-identical to the shipped server):

* ``Active.__init__`` / ``myinit`` / ``enqueue_data`` / ``enqueue_data_dflt`` /
  ``log_data_task`` (the async data-stream file writer) /
  ``log_data_set_output_file`` / ``write_file`` / ``split`` /
  ``split_and_keep_active`` / ``finish_all`` / ``substitute`` / ``finish`` /
  ``_finish`` / ``set_error`` / ``set_estop`` / ``append_sample`` /
  ``finish_manual_action`` and their transitive calls into the REAL
  ``Base.write_act`` / ``write_exp`` / ``write_seq`` / ``get_realtime`` /
  ``new_file_conn_key`` / ``dflt_file_conn_key``.
* ``Base`` is built via ``Base.__new__`` + a minimal attribute fixture that
  bypasses ``Base.__init__`` entirely (no FastAPI app, no NTP, no WebSockets) --
  the same ``__new__``-bypass strategy the P5 harness uses for ``Orch``. The
  attribute set was discovered by running and filling AttributeErrors; every
  attribute the driven code path touches is set in ``_make_base``.

What is FAKED/STUBBED (the harness surface):

* ``status_q`` / ``data_q`` -- REAL ``MultisubscriberQueue`` subclasses
  (``_RecordingMSQ``) that additionally append a JSON-safe record of each
  ``put``/``put_nowait`` to the ordered side-effect trace. ``data_q`` still
  fans packets out to the REAL ``log_data_task`` subscriber (so .hlo files are
  written by production code); it only records data packets that actually
  carry data (``datamodel.data`` non-empty), because ``finish()``'s housekeeping
  "finished/empty" packets are emitted a nondeterministic number of times (its
  retry loop re-enqueues one until the data logger flips the stream status,
  which depends on event-loop scheduling relative to a real ``sleep(0.1)``).
  The .hlo file bytes remain the authoritative record of streamed data.
* ``move_dir`` / ``async_private_dispatcher`` / ``async_copy`` (module-globals
  on ``helao.core.servers.base``) -- recording no-ops (no real directory
  moves, no network RPC for global-param export, no aux-file copies).
* ``base.app.driver`` -- ``None`` (stored by ``Active.__init__`` but never
  exercised by the driven, executor-free lifecycle).

Determinism -- the whole game (see brief). Two independent nondeterminism
sources reach ``Active``'s output and are handled as follows:

1. UUIDs, wall-clock timestamps, epoch-ns header stamps, and the git-SHA
   ``hlo_version`` token. ``Active.split`` force-reinits a fresh action (new
   ``gen_uuid``/``set_time``), ``finish`` stamps ``action_finished_timestamp``
   from the wall clock, and HLO headers stamp ``epoch_ns`` from ``Base``'s
   ``Timer``. These cannot be pinned without editing ``base.py`` (forbidden
   this stage), so every captured artifact is NORMALIZED with a P3-style
   scrubber (copied from ``.omc/artifacts/p3/normalize_runs_tree.py``): each
   distinct uuid/timestamp/epoch token is mapped to a stable per-run,
   per-artifact sequential placeholder (``<UUID:0>``, ``<ISOTS:0>``,
   ``<EPOCHNS:0>`` ...) by first-appearance order, and ``hlo_version`` /
   ``*codehash`` values are elided to fixed placeholders. Structurally
   identical runs then normalize to identical text even though the underlying
   ids differ. Construction ids/timestamps are also seeded deterministically
   (``_mk_action``) for baseline readability, but correctness does not depend
   on that -- only on structural stability, which the normalizer captures.
2. Async flush/chunk boundaries in streamed ``.hlo`` data. The ``--check``
   gate compares ``.hlo`` files by (a) NORMALIZED header bytes (exact),
   (b) per-data-key VALUE MULTISETS of the JSON data lines (copied from
   ``.omc/artifacts/p3/compare_runs.py``), and (c) a WHOLE-RECORD MULTISET
   that explodes each parallel-list data line into position-paired per-index
   records and multisets the entire record dict -- never raw-line equality, so
   a chunk split at a different offset still compares equal. The whole-record
   check (added in S6) catches a cross-key transpose / split / regroup that
   leaves the per-key pools of (b) unchanged; both are kept because neither
   strictly subsumes the other. Non-``.hlo`` files (``-act.yml`` /
   ``-exp.yml`` / ``-seq.yml``) and the side-effect trace are compared as exact
   normalized bytes.

Frozen reference: ``.omc/artifacts/p6/baseline_S0a/`` holds one
``<scenario>.trace.jsonl`` (normalized side-effect trace) and one
``<scenario>.runs.norm`` (normalized snapshot of every file written under the
scenario's ``save_root``) per scenario. It is captured once (``--freeze``, on
unmodified ``base.py``) and must never be regenerated during later stages --
``run_freeze`` refuses to overwrite a non-empty ``baseline_S0a/`` and
``_write_baseline`` asserts against it, mirroring the P5 freeze guard.

Run (conda env ``helao``; no pytest harness in this repo -- run as a script)::

    conda run -n helao --no-capture-output python \\
        helao/core/tests/test_active_golden_master.py            # determinism self-test
    conda run -n helao --no-capture-output python \\
        helao/core/tests/test_active_golden_master.py --freeze   # one-time baseline freeze
    conda run -n helao --no-capture-output python \\
        helao/core/tests/test_active_golden_master.py --check     # hard gate for later P6 stages

Because it does real (temp-dir) file I/O and is not instantaneous, this module
is a standalone ``--check`` script and is intentionally NOT registered in
``run_unit_tests.py`` (matching the P5 golden master).
"""

import argparse
import asyncio
import hashlib
import json
import os
import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import helao.core.servers.base as base_module
import helao.core.servers.active_finalizer as finalizer_module
import helao.helpers.premodels as premodels_module
from helao.core.servers.base import Base, Active
from helao.core.error import ErrorCodes
from helao.core.models.data import DataModel
from helao.core.models.file import FileConnParams, HloFileGroup
from helao.core.models.hlostatus import HloStatus
from helao.core.models.machine import MachineModel
from helao.helpers.active_params import ActiveParams
from helao.helpers.dequedict import DequeDict
from helao.helpers.executor import Executor
from helao.helpers.multisubscriber_queue import MultisubscriberQueue
from helao.helpers.premodels import Action

REPO_ROOT = Path(__file__).resolve().parents[3]
ARTIFACT_DIR = REPO_ROOT / ".omc" / "artifacts" / "p6"
# Frozen S0a reference (captured once, on unmodified base.py). Never write here
# outside the one-time --freeze step -- it is the hard gate later P6 stages diff
# against.
BASELINE_S0A_DIR = ARTIFACT_DIR / "baseline_S0a"

SERVER_NAME = "ACTSRV"
MACHINE = "test-machine"
NTP_OFFSET = 0.0
# Fixed wall clock the harness pins `set_time` to. Manual actions synthesize
# their run-dir path from strftime components of the sequence/experiment
# timestamps (e.g. "YY.WW/MMDD/HHMMSS__..."); those date components are NOT
# caught by the ISOTS normalizer (which needs a full "YYYY-MM-DD HH:MM:SS"), so
# without pinning the manual-action baseline would silently rot across days.
# Pinning `set_time` makes every generated timestamp (and thus every derived
# path) date-independent; residual uuid/epoch tokens are still normalized.
_FIXED_DT = datetime(2026, 1, 2, 3, 4, 5, 678901)


# ---------------------------------------------------------------------------
# normalization (copied/adapted from .omc/artifacts/p3/normalize_runs_tree.py)
# ---------------------------------------------------------------------------

# (name, regex, grouped). grouped=False: whole match is a nondeterministic
# token, assigned stable per-artifact sequential indices by first-appearance
# order. grouped=True: group(1) is a stable prefix kept verbatim, the value is
# elided to a fixed placeholder.
_PATTERNS = [
    ("UUID", re.compile(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"), False),
    ("ISOTS", re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?"), False),
    # %y%m%d.%H%M%S(%f) dir/file stamps, e.g. 260102.030405123456
    ("DIRTS", re.compile(r"\b\d{6}\.\d{6,18}\b"), False),
    # bare %H%M%S sequence-dir stamp ("HMS__name__label"); no leading date/dot.
    ("SEQTS", re.compile(r"\b\d{6}(?=__)"), False),
    ("EPOCHNS", re.compile(r"\b1[6-9]\d{17}\b"), False),        # epoch nanoseconds
    ("EPOCH", re.compile(r"\b1[6-9]\d{8}(?:\.\d+)?\b"), False),  # epoch seconds
    # hlo_version embeds a git describe/short-SHA token that moves every commit
    ("HLOVER", re.compile(r"(hlo_version['\"]?\s*[:=]\s*)\S+"), True),
    # *_codehash fields are derived from source; change when authored source is edited
    ("CODEHASH", re.compile(r"([a-z_]*codehash['\"]?\s*[:=]\s*)['\"]?[0-9a-f]{6,40}['\"]?"), True),
]


class _Normalizer:
    """Stable per-artifact scrubber for uuids/timestamps/epochs/hlo_version."""

    def __init__(self):
        self.maps = {name: {} for name, _, _ in _PATTERNS}

    def sub(self, text: str) -> str:
        for name, rx, grouped in _PATTERNS:
            if grouped:
                def repl(m, name=name):
                    return m.group(1) + f"<{name}>"
            else:
                table = self.maps[name]

                def repl(m, table=table, name=name):
                    tok = m.group(0)
                    if tok not in table:
                        table[tok] = f"<{name}:{len(table)}>"
                    return table[tok]
            text = rx.sub(repl, text)
        return text


def _normalize_runs_tree(root: Path) -> str:
    """Emit a normalized ``===== relpath =====\\n<body>`` snapshot of every file
    under ``root`` (the P3 ``.norm`` format), walked in sorted order."""
    norm = _Normalizer()
    entries = []
    if root.is_dir():
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames.sort()
            for fn in sorted(filenames):
                full = os.path.join(dirpath, fn)
                entries.append((os.path.relpath(full, root), full))
    entries.sort(key=lambda e: e[0])
    out = []
    for rel, full in entries:
        try:
            with open(full, "r", encoding="utf-8") as f:
                body = norm.sub(f.read())
        except (UnicodeDecodeError, ValueError):
            with open(full, "rb") as f:
                body = "BINARY sha256=" + hashlib.sha256(f.read()).hexdigest()
        out.append(f"===== {norm.sub(rel.replace(os.sep, '/'))} =====\n{body}\n")
    return "".join(out)


# ---------------------------------------------------------------------------
# .norm parsing + .hlo multiset comparison (copied from compare_runs.py)
# ---------------------------------------------------------------------------

_HEADER_RE = re.compile(r"^===== (.+) =====$")


def _parse_norm(text: str) -> "dict[str, str]":
    """Parse a ``.norm`` snapshot into an ordered {relpath: body} dict."""
    entries = {}
    relpath = None
    body_lines = []
    for line in text.splitlines(keepends=True):
        m = _HEADER_RE.match(line.rstrip("\n"))
        if m is not None:
            if relpath is not None:
                entries[relpath] = "".join(body_lines)
            relpath = m.group(1)
            body_lines = []
        else:
            body_lines.append(line)
    if relpath is not None:
        entries[relpath] = "".join(body_lines)
    return entries


def _split_hlo(body: str):
    """Split an .hlo body into (header_text, [data_line, ...])."""
    lines = body.splitlines()
    if "%%" not in lines:
        return body, []
    idx = lines.index("%%")
    header = "\n".join(lines[:idx])
    data_lines = [line for line in lines[idx + 1:] if line.strip()]
    return header, data_lines


def _multiset_key(value):
    return json.dumps(value, sort_keys=True)


def _merge_data_multisets(data_lines):
    """Per-key value multisets of the JSON data lines (P3 rule). List-valued
    keys are flattened into a scalar pool when the file has >1 data line (a
    real chunk boundary to absorb), else compared atomically."""
    records = []
    for line in data_lines:
        rec = json.loads(line)
        if not isinstance(rec, dict):
            raise ValueError(f"data line is not a JSON object: {line!r}")
        records.append(rec)
    keys = set()
    for rec in records:
        keys.update(rec)
    chunked = len(records) > 1
    per_key = {}
    for key in keys:
        values = [rec[key] for rec in records if key in rec]
        counter = Counter()
        if chunked and any(isinstance(v, list) for v in values):
            for v in values:
                for element in (v if isinstance(v, list) else [v]):
                    counter[_multiset_key(element)] += 1
        else:
            for v in values:
                counter[_multiset_key(v)] += 1
        per_key[key] = counter
    return per_key


def _explode_records(rec: dict):
    """Explode one JSON data-line dict into per-index WHOLE records.

    A parallel-list line ``{"t_s":[0,1,2],"erhe_v":[10,11,12]}`` becomes the
    three records ``{"t_s":0,"erhe_v":10}``, ``{"t_s":1,"erhe_v":11}``,
    ``{"t_s":2,"erhe_v":12}`` -- values are POSITION-PAIRED within the line.
    Scalar-valued keys broadcast across every index (so a line mixing a scalar
    ``epoch`` with parallel arrays keeps ``epoch`` on each record); a line with
    no list values yields exactly one record (the dict itself).

    Raises:
        ValueError: if the line's list-valued keys have unequal lengths, so
            they cannot be position-paired (surfaced as a data diff by the
            caller rather than silently mispaired).
    """
    list_keys = {k: v for k, v in rec.items() if isinstance(v, list)}
    scalar_keys = {k: v for k, v in rec.items() if not isinstance(v, list)}
    if not list_keys:
        return [rec]
    lengths = {len(v) for v in list_keys.values()}
    if len(lengths) != 1:
        raise ValueError(
            "parallel-list keys have mismatched lengths: "
            f"{ {k: len(v) for k, v in list_keys.items()} }"
        )
    (n,) = tuple(lengths)
    records = []
    for i in range(n):
        r = dict(scalar_keys)
        for k, v in list_keys.items():
            r[k] = v[i]
        records.append(r)
    return records


def _whole_record_multiset(data_lines):
    """Multiset (``Counter``) of WHOLE per-index records across all data lines.

    Complements :func:`_merge_data_multisets` (which pools each key
    independently and so cannot see which values CO-OCCUR): exploding each line
    into position-paired records and keying the multiset on the entire record
    dict absorbs async chunk-boundary REGROUPING (records are matched by value,
    line order ignored) while still catching a drop, duplicate, transpose, or
    split-across-lines that leaves the per-key pools unchanged."""
    counter = Counter()
    for line in data_lines:
        rec = json.loads(line)
        if not isinstance(rec, dict):
            raise ValueError(f"data line is not a JSON object: {line!r}")
        for record in _explode_records(rec):
            counter[_multiset_key(record)] += 1
    return counter


def _compare_norm(name: str, ref_text: str, cur_text: str) -> "list[str]":
    """Apply the 3-part P3 contract between two ``.norm`` snapshots. Returns a
    list of human-readable failure strings (empty == match)."""
    ref = _parse_norm(ref_text)
    cur = _parse_norm(cur_text)
    failures = []
    ref_keys, cur_keys = set(ref), set(cur)
    if ref_keys != cur_keys:
        only_ref = sorted(ref_keys - cur_keys)
        only_cur = sorted(cur_keys - ref_keys)
        failures.append(
            f"[{name} manifest] only-in-baseline={only_ref} only-in-current={only_cur}"
        )
    for rel in sorted(ref_keys & cur_keys):
        body_ref, body_cur = ref[rel], cur[rel]
        if rel.endswith(".hlo"):
            h_ref, d_ref = _split_hlo(body_ref)
            h_cur, d_cur = _split_hlo(body_cur)
            if h_ref != h_cur:
                failures.append(f"[{name} .hlo header] {rel}")
                continue
            try:
                ms_ref = _merge_data_multisets(d_ref)
                ms_cur = _merge_data_multisets(d_cur)
            except (ValueError, json.JSONDecodeError) as exc:
                failures.append(f"[{name} .hlo data-parse] {rel}: {exc}")
                continue
            if set(ms_ref) != set(ms_cur):
                failures.append(
                    f"[{name} .hlo data-key set] {rel}: "
                    f"only-in-baseline={sorted(set(ms_ref) - set(ms_cur))} "
                    f"only-in-current={sorted(set(ms_cur) - set(ms_ref))}"
                )
                continue
            for key in sorted(ms_ref):
                if ms_ref[key] != ms_cur[key]:
                    failures.append(
                        f"[{name} .hlo data multiset] {rel} key={key!r}: "
                        f"baseline={dict(ms_ref[key])} current={dict(ms_cur[key])}"
                    )
            # whole-record multiset: catches cross-key transpose / split /
            # regroup that the per-key pools above are blind to (see
            # _whole_record_multiset). Kept alongside the per-key check
            # (belt-and-suspenders) since neither strictly subsumes the other's
            # failure message.
            try:
                wr_ref = _whole_record_multiset(d_ref)
                wr_cur = _whole_record_multiset(d_cur)
            except (ValueError, json.JSONDecodeError) as exc:
                failures.append(f"[{name} .hlo whole-record-parse] {rel}: {exc}")
            else:
                if wr_ref != wr_cur:
                    failures.append(
                        f"[{name} .hlo whole-record multiset] {rel}: "
                        f"only-in-baseline={sorted(set(wr_ref - wr_cur))} "
                        f"only-in-current={sorted(set(wr_cur - wr_ref))}"
                    )
        elif body_ref != body_cur:
            failures.append(f"[{name} text] {rel}")
    return failures


# ---------------------------------------------------------------------------
# JSON-safe recorder + recording MultisubscriberQueue
# ---------------------------------------------------------------------------


def _json_safe(obj):
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if hasattr(obj, "value") and not isinstance(obj, (str, int, float, bool)):
        return obj.value
    return obj


def _status_list(action) -> list:
    return [_json_safe(s) for s in action.action_status]


class _RecordingMSQ(MultisubscriberQueue):
    """Real fan-out queue that also records each put onto the shared trace.

    ``record_fn(data) -> Optional[dict]``: return a JSON-safe record to append
    to the trace, or ``None`` to skip (e.g. the ``StopAsyncIteration`` sentinel,
    or empty-data housekeeping packets)."""

    def __init__(self, record_fn, trace: list):
        super().__init__()
        self._record_fn = record_fn
        self._trace = trace

    def _maybe_record(self, data):
        if data is StopAsyncIteration:
            return
        rec = self._record_fn(data)
        if rec is not None:
            self._trace.append(rec)

    async def put(self, data):
        self._maybe_record(data)
        await super().put(data)

    def put_nowait(self, data):
        self._maybe_record(data)
        super().put_nowait(data)


def _status_record(actionmodel):
    return {
        "event": "status_packet",
        "action_name": actionmodel.action_name,
        "action_uuid": str(actionmodel.action_uuid),
        "action_status": [_json_safe(s) for s in actionmodel.action_status],
    }


def _data_record(datapackage):
    dm = datapackage.datamodel
    if not dm.data:
        # housekeeping finished/empty packet: emitted a nondeterministic number
        # of times by finish()'s retry loop -- excluded from the trace (the
        # .hlo bytes are the authoritative streamed-data record). See docstring.
        return None
    return {
        "event": "data_packet",
        "action_name": datapackage.action_name,
        "action_uuid": str(datapackage.action_uuid),
        "status": _json_safe(dm.status),
        "file_conn_keys": sorted(str(k) for k in dm.data.keys()),
        "data_keys": sorted(
            k for payload in dm.data.values() if isinstance(payload, dict) for k in payload
        ),
    }


# ---------------------------------------------------------------------------
# Base fixture (Base.__init__ bypass, mirrors P5's Orch.__new__)
# ---------------------------------------------------------------------------


def _make_base(save_root: Path, trace: list) -> Base:
    """Build a bare ``Base`` with every attribute the ``Active`` path touches."""
    base = Base.__new__(Base)
    base.app = SimpleNamespace(driver=None)
    base.server = MachineModel(
        server_name=SERVER_NAME, machine_name=MACHINE, hostname="127.0.0.1", port=8000
    )
    base.world_cfg = {"dummy": False, "simulation": False, "root": str(save_root.parent)}
    base.ntp_offset = NTP_OFFSET
    base.helaodirs = SimpleNamespace(save_root=str(save_root))
    base.aloop = asyncio.get_running_loop()

    base.status_q = _RecordingMSQ(_status_record, trace)
    base.data_q = _RecordingMSQ(_data_record, trace)
    base.status_clients = set()

    base.actives = {}
    base.history = DequeDict(maxlen=200)
    base.executors = {}
    base.local_action_task_queue = []
    base.hlo_postprocessors = []
    base.hlo_postprocess_libs = []
    base.live_q = MultisubscriberQueue()
    base.live_buffer = {}
    base._init_collaborators()
    return base


# ---------------------------------------------------------------------------
# module-global patches on helao.core.servers.base
# ---------------------------------------------------------------------------


class _PatchedBaseGlobals:
    """Patch the disk/network module-globals ``base.py`` calls in finalization."""

    def __init__(self, trace: list):
        self._trace = trace
        self._orig = {}

    def __enter__(self):
        def _fixed_set_time(offset: float = 0):
            return _FIXED_DT

        async def _fake_move_dir(hobj, base=None, retry_delay=5):
            self._trace.append(
                {"event": "move_dir", "action_uuid": str(getattr(hobj, "action_uuid", None))}
            )
            return None

        async def _fake_private_dispatcher(
            server_key, host, port, private_action, params_dict=None, json_dict=None, **kwargs
        ):
            self._trace.append(
                {
                    "event": "private_dispatch",
                    "action": private_action,
                    "json_keys": sorted((json_dict or {}).keys()),
                    # record the EXPORTED VALUES (not just key names) so the
                    # global-param fold-out is frozen by value, and the dict-form
                    # rename mapping (k1 -> k2) is observable (which OUTPUT key
                    # carries which value). JSON-safe + key-sorted for stable text.
                    "json_values": {
                        str(k): _json_safe(v)
                        for k, v in sorted((json_dict or {}).items())
                    },
                }
            )
            return {}, ErrorCodes.none

        async def _fake_async_copy(src, dst, **kwargs):
            self._trace.append({"event": "async_copy"})
            return None

        self._orig = {
            (base_module, "move_dir"): base_module.move_dir,
            (base_module, "async_private_dispatcher"): base_module.async_private_dispatcher,
            (base_module, "async_copy"): base_module.async_copy,
            (base_module, "set_time"): base_module.set_time,
            (premodels_module, "set_time"): premodels_module.set_time,
            # The finish/split close-out (move_dir / async_private_dispatcher /
            # set_time) was extracted to ``active_finalizer`` in P6 S8; the moved
            # ``_finish`` resolves these three from the finalizer module's own
            # namespace, so they must be patched there too (else the real
            # disk-move/RPC/wall-clock would run and the finish trace + fixed
            # timestamps would diverge from the frozen baseline).
            (finalizer_module, "move_dir"): finalizer_module.move_dir,
            (finalizer_module, "async_private_dispatcher"): finalizer_module.async_private_dispatcher,
            (finalizer_module, "set_time"): finalizer_module.set_time,
        }
        base_module.move_dir = _fake_move_dir
        base_module.async_private_dispatcher = _fake_private_dispatcher
        base_module.async_copy = _fake_async_copy
        base_module.set_time = _fixed_set_time
        premodels_module.set_time = _fixed_set_time
        finalizer_module.move_dir = _fake_move_dir
        finalizer_module.async_private_dispatcher = _fake_private_dispatcher
        finalizer_module.set_time = _fixed_set_time
        return self

    def __exit__(self, *exc):
        for (mod, name), val in self._orig.items():
            setattr(mod, name, val)
        return False


# ---------------------------------------------------------------------------
# construction helpers
# ---------------------------------------------------------------------------

_SEED_COUNTER = {"n": 0}


def _seed_uuid(tag: str):
    from uuid import UUID

    return UUID(hashlib.md5(tag.encode("utf-8")).hexdigest())


def _seed_ts(n: int) -> datetime:
    return datetime(2026, 1, 1, 0, 0, 0) + timedelta(seconds=n)


def _mk_action(action_name: str, manual: bool = False, **overrides) -> Action:
    """Construct an ``Action`` with deterministic identity seeded from the name.

    When ``manual`` is True the sequence/experiment timestamps are left unset so
    ``Active.__init__`` -> ``init_act`` promotes the action to a manual run.
    """
    fields = dict(
        action_name=action_name,
        action_abbr=action_name[:4],
        orch_key=SERVER_NAME,
        orch_host="127.0.0.1",
        orch_port=8000,
        action_uuid=_seed_uuid(f"act::{action_name}"),
        action_timestamp=_seed_ts(1),
    )
    if not manual:
        fields.update(
            sequence_uuid=_seed_uuid(f"seq::{action_name}"),
            sequence_name=f"seq_{action_name}",
            sequence_label="gm",
            sequence_timestamp=_seed_ts(0),
            experiment_uuid=_seed_uuid(f"exp::{action_name}"),
            experiment_name=f"exp_{action_name}",
            experiment_timestamp=_seed_ts(0),
        )
    fields.update(overrides)
    return Action(**fields)


def _active_params(base: Base, action: Action, aux_uuids=None) -> ActiveParams:
    """Build ActiveParams with one file connection on the default conn key."""
    dflt = base.dflt_file_conn_key()
    return ActiveParams(
        action=action,
        file_conn_params_dict={
            dflt: FileConnParams(
                file_conn_key=dflt,
                json_data_keys=["t", "v"],
                file_type="gm__test_file",
                file_group=HloFileGroup.helao_files,
            )
        },
        aux_listen_uuids=aux_uuids or [],
    )


async def _ticks(n: int = 6):
    for _ in range(n):
        await asyncio.sleep(0)


async def _drain_data(active: Active, timeout_s: float = 5.0):
    """Block (with real sleeps) until the async data logger has consumed every
    enqueued data packet, i.e. every lazy HLO-file open + write is complete.

    ``aiofiles`` opens/writes resolve on a threadpool, so bare ``sleep(0)``
    ticks do not reliably complete a file open; without this drain an open can
    slip past a later ``split()``/``substitute()`` and both the on-disk output
    and any file-connection inspection become scheduling-dependent. Draining on
    ``num_data_written``/``num_data_queued`` (production counters) makes the
    logger's progress a deterministic precondition of the next lifecycle step."""
    waited = 0.0
    while active.num_data_queued > active.num_data_written and waited < timeout_s:
        await asyncio.sleep(0.01)
        waited += 0.01
    # one more short settle so the threadpool open/write future fully resolves
    # and file_conn_dict[...].file is populated before inspection.
    await asyncio.sleep(0.02)


# ---------------------------------------------------------------------------
# fake Executor (GAP#1: the Active lifecycle is executor-free in scenarios 1-9,
# so start_executor / action_loop_task / oneoff_executor are otherwise
# unexercised by the golden master).
# ---------------------------------------------------------------------------


class _FakeExecutor(Executor):
    """Deterministic scripted :class:`Executor` for the golden master.

    Conforms to the four-phase contract in ``helao/helpers/executor.py`` by
    overriding ``_pre_exec`` / ``_exec`` / ``_poll`` / ``_post_exec`` /
    ``_manual_stop`` to return fixed ``{"data": {...}, "error": ...}`` /
    ``{"status": ...}`` dicts. Determinism is guaranteed WITHOUT wall-clock
    waits: ``poll_rate=0`` makes ``action_loop_task``'s inter-poll
    ``asyncio.sleep(poll_rate)`` a bare yield, and ``max_polls`` bounds the poll
    loop (the ``max_polls``-th ``_poll`` returns a terminal ``HloStatus`` so the
    loop exits after a fixed number of iterations). Data values are pinned
    functions of the phase / poll index so the enqueued packets and streamed
    ``.hlo`` rows are byte/multiset-stable run-to-run.
    """

    def __init__(self, active, *, oneoff: bool, max_polls: int = 0, **kwargs):
        super().__init__(active, poll_rate=0.0, oneoff=oneoff, concurrent=True, **kwargs)
        self._max_polls = max_polls
        self._poll_count = 0

    async def _pre_exec(self) -> dict:
        return {"error": ErrorCodes.none}

    async def _exec(self) -> dict:
        return {"data": {"t": 0, "v": 0}, "error": ErrorCodes.none}

    async def _poll(self) -> dict:
        self._poll_count += 1
        status = (
            HloStatus.active if self._poll_count < self._max_polls else HloStatus.finished
        )
        return {
            "data": {"t": self._poll_count, "v": self._poll_count * 10},
            "error": ErrorCodes.none,
            "status": status,
        }

    async def _post_exec(self) -> dict:
        return {"data": {"t": -1, "v": -1}, "error": ErrorCodes.none}

    async def _manual_stop(self) -> dict:
        return {"error": ErrorCodes.none}


# ---------------------------------------------------------------------------
# scenarios -- each returns {"trace": [...]} and writes files under save_root
# ---------------------------------------------------------------------------


async def _scenario_basic(save_root: Path) -> dict:
    trace: list = []
    base = _make_base(save_root, trace)
    with _PatchedBaseGlobals(trace):
        action = _mk_action("basic")
        active = Active(base, _active_params(base, action))
        await active.myinit()
        await _ticks()
        trace.append({"event": "post_myinit", "action_status": _status_list(active.action)})

        for i in range(3):
            await active.enqueue_data_dflt({"t": i, "v": i * 10})
            await _drain_data(active)

        path = await active.write_file(
            output_str="alpha\nbeta\ngamma\n",
            file_type="gm__blob",
            filename="known_blob.txt",
            file_group=HloFileGroup.aux_files,
            header="# a known header",
        )
        trace.append({"event": "write_file", "wrote": path is not None})

        await active.finish()
        await _ticks(10)
        trace.append({"event": "post_finish", "action_status": _status_list(active.action)})
    return {"trace": trace}


async def _scenario_save_data_false(save_root: Path) -> dict:
    trace: list = []
    base = _make_base(save_root, trace)
    with _PatchedBaseGlobals(trace):
        action = _mk_action("nosave", save_data=False)
        active = Active(base, _active_params(base, action))
        await active.myinit()
        await _ticks()
        trace.append(
            {
                "event": "post_myinit",
                "save_data": active.action.save_data,
                "save_act": active.action.save_act,
            }
        )
        # enqueue anyway; log_data_task returned early so nothing is written
        await active.enqueue_data_dflt({"t": 0, "v": 0})
        await _drain_data(active)
        await active.finish()
        await _ticks(10)
        trace.append({"event": "post_finish", "action_status": _status_list(active.action)})
    return {"trace": trace}


async def _scenario_split(save_root: Path) -> dict:
    trace: list = []
    base = _make_base(save_root, trace)
    with _PatchedBaseGlobals(trace):
        action = _mk_action("split")
        active = Active(base, _active_params(base, action))
        await active.myinit()
        await _ticks()

        for i in range(2):
            await active.enqueue_data_dflt({"t": i, "v": i})
            await _drain_data(active)

        # split_and_keep_active() == split(uuid_list=[]); call split directly to
        # capture the returned new file-connection keys for the child stream.
        new_keys = await active.split(uuid_list=[])
        await _ticks()
        trace.append(
            {
                "event": "post_split",
                "num_new_file_conn_keys": len(new_keys),
                "action_list_len": len(active.action_list),
                "cur_action_status": _status_list(active.action),
                "prev_action_status": _status_list(active.action_list[1]),
                "cur_file_conn_keys": len(active.action.file_conn_keys),
            }
        )

        # stream to the new split child's file connection
        for i in range(2):
            await active.enqueue_data(
                DataModel(
                    data={new_keys[0]: {"t": 100 + i, "v": 100 + i}},
                    errors=[],
                    status=HloStatus.active,
                )
            )
            await _drain_data(active)

        await active.finish_all()
        await _ticks(10)
        trace.append(
            {
                "event": "post_finish_all",
                "cur_action_status": _status_list(active.action),
                "prev_action_status": _status_list(active.action_list[1]),
            }
        )
    return {"trace": trace}


async def _scenario_substitute(save_root: Path) -> dict:
    trace: list = []
    base = _make_base(save_root, trace)
    with _PatchedBaseGlobals(trace):
        action = _mk_action("subst")
        active = Active(base, _active_params(base, action))
        await active.myinit()
        await _ticks()

        await active.enqueue_data_dflt({"t": 0, "v": 0})
        await _drain_data(active)
        trace.append(
            {
                "event": "pre_substitute",
                "open_files": sum(
                    1 for fc in active.file_conn_dict.values() if fc.file is not None
                ),
            }
        )

        await active.substitute()
        await _ticks()
        trace.append(
            {
                "event": "post_substitute",
                "open_files": sum(
                    1 for fc in active.file_conn_dict.values() if fc.file is not None
                ),
            }
        )

        await active.finish()
        await _ticks(10)
        trace.append({"event": "post_finish", "action_status": _status_list(active.action)})
    return {"trace": trace}


async def _scenario_error_estop(save_root: Path) -> dict:
    trace: list = []
    base = _make_base(save_root, trace)
    with _PatchedBaseGlobals(trace):
        action = _mk_action("errst")
        active = Active(base, _active_params(base, action))
        await active.myinit()
        await _ticks()

        await active.enqueue_data_dflt({"t": 0, "v": 0})
        await _drain_data(active)

        await active.set_error(ErrorCodes.critical_error)
        trace.append(
            {
                "event": "post_set_error",
                "action_status": _status_list(active.action),
                "error_code": _json_safe(active.action.error_code),
            }
        )
        active.set_estop()
        trace.append({"event": "post_set_estop", "action_status": _status_list(active.action)})

        await active.finish()
        await _ticks(10)
        trace.append({"event": "post_finish", "action_status": _status_list(active.action)})
    return {"trace": trace}


async def _scenario_manual(save_root: Path) -> dict:
    trace: list = []
    base = _make_base(save_root, trace)
    with _PatchedBaseGlobals(trace):
        action = _mk_action("manual", manual=True)
        active = Active(base, _active_params(base, action))
        await active.myinit()
        await _ticks()
        trace.append(
            {
                "event": "post_myinit",
                "manual_action": active.action.manual_action,
                "access": active.action.access,
            }
        )

        await active.enqueue_data_dflt({"t": 0, "v": 1})
        await _drain_data(active)

        await active.finish()
        await _ticks(10)
        trace.append({"event": "post_finish", "action_status": _status_list(active.action)})
    return {"trace": trace}


async def _scenario_multifile_aux(save_root: Path) -> dict:
    trace: list = []
    base = _make_base(save_root, trace)
    with _PatchedBaseGlobals(trace):
        action = _mk_action("multi")

        dflt = base.dflt_file_conn_key()
        second = base.new_file_conn_key("second-file-conn")
        aux_uuid = _seed_uuid("aux::listener")
        ap = ActiveParams(
            action=action,
            file_conn_params_dict={
                dflt: FileConnParams(
                    file_conn_key=dflt, json_data_keys=["t", "v"], file_type="gm__file_a"
                ),
                second: FileConnParams(
                    file_conn_key=second, json_data_keys=["a", "b"], file_type="gm__file_b"
                ),
            },
            aux_listen_uuids=[aux_uuid],
        )
        active = Active(base, ap)
        await active.myinit()
        await _ticks()
        trace.append(
            {
                "event": "post_myinit",
                "num_file_conn_keys": len(active.action.file_conn_keys),
                "num_listen_uuids": len(active.listen_uuids),
            }
        )

        for i in range(2):
            await active.enqueue_data(
                DataModel(data={dflt: {"t": i, "v": i}}, errors=[], status=HloStatus.active)
            )
            await _drain_data(active)
        for i in range(2):
            await active.enqueue_data(
                DataModel(
                    data={second: {"a": i * 2, "b": i * 3}}, errors=[], status=HloStatus.active
                )
            )
            await _drain_data(active)

        await active.finish()
        await _ticks(10)
        trace.append({"event": "post_finish", "action_status": _status_list(active.action)})
    return {"trace": trace}


async def _scenario_finalizer_global_params(save_root: Path) -> dict:
    trace: list = []
    base = _make_base(save_root, trace)
    with _PatchedBaseGlobals(trace):
        action = _mk_action(
            "gparm",
            to_global_params=["produced_key"],
            action_output={"produced_key": "PRODUCED_VALUE"},
        )
        active = Active(base, _active_params(base, action))
        await active.myinit()
        await _ticks()

        await active.enqueue_data_dflt({"t": 0, "v": 0})
        await _drain_data(active)

        await active.finish()
        await _ticks(10)
        trace.append({"event": "post_finish", "action_status": _status_list(active.action)})
    return {"trace": trace}


async def _scenario_finalizer_global_params_dict(save_root: Path) -> dict:
    """Dict-form ``to_global_params`` rename mapping (``k1 -> k2``).

    ``finish``/``_finish`` folds ``to_global_params`` out to the orch. The list
    form (scenario 8) exports each key under its own name; the DICT form renames
    ``src_key`` (read from ``action_output``) to ``dest_key`` on export. With the
    private-dispatch trace now recording VALUES, this freezes that the renamed
    OUTPUT key carries the source value -- an otherwise untested branch of the
    fold-out that a broken rename (wrong key, dropped value) would silently
    change."""
    trace: list = []
    base = _make_base(save_root, trace)
    with _PatchedBaseGlobals(trace):
        action = _mk_action(
            "gpdict",
            to_global_params={"src_key": "dest_key"},
            action_output={"src_key": "RENAMED_VALUE"},
        )
        active = Active(base, _active_params(base, action))
        await active.myinit()
        await _ticks()

        await active.enqueue_data_dflt({"t": 0, "v": 0})
        await _drain_data(active)

        await active.finish()
        await _ticks(10)
        trace.append({"event": "post_finish", "action_status": _status_list(active.action)})
    return {"trace": trace}


async def _scenario_finish_late_data_drain(save_root: Path) -> dict:
    """GAP#3: reach ``finish()`` with a data packet STILL IN FLIGHT.

    Every other scenario drains each enqueued packet (``_drain_data``) before the
    next lifecycle step, so ``num_data_queued == num_data_written`` at finish
    entry and the finished-packet write-drain loop in ``_finish`` (roughly
    base.py:1618-1645 -- the retry+``sleep(0.1)`` that lets the threadpool file
    writes complete BEFORE the file connections are closed) never has anything to
    flush: its late-data-vs-file-close race is unobservable.

    Here we open the file with one drained packet, then enqueue a SECOND packet
    with ``enqueue_data_nowait`` and IMMEDIATELY call ``finish()`` with NO drain
    in between. Because ``enqueue_data_nowait`` is fully synchronous, the data
    logger cannot have run yet, so ``num_data_queued > num_data_written`` holds
    deterministically at finish entry (recorded as ``undrained``). The OBSERVABLE
    consequence frozen here is the drained ``.hlo`` bytes: the late row
    (``t=1, v=111``) MUST be present in the file after finish -- i.e. the drain
    flushed it before ``_finish`` closed and cleared ``file_conn_dict``. If the
    drain were skipped/broken the late write would be lost (file closed first),
    the row would vanish from the ``.hlo`` whole-record multiset, and ``--check``
    would fail (the BITE)."""
    trace: list = []
    base = _make_base(save_root, trace)
    with _PatchedBaseGlobals(trace):
        action = _mk_action("fdrain")
        active = Active(base, _active_params(base, action))
        await active.myinit()
        await _ticks()

        dflt = base.dflt_file_conn_key()
        # first packet drained normally: opens the file + writes the header row
        await active.enqueue_data_dflt({"t": 0, "v": 0})
        await _drain_data(active)

        # late packet: enqueue synchronously (nowait) then finish immediately, so
        # it is still in flight at finish entry. No await between the enqueue and
        # the flag read => the data logger has not consumed it => strictly
        # undrained, deterministically.
        active.enqueue_data_nowait(
            DataModel(data={dflt: {"t": 1, "v": 111}}, errors=[], status=HloStatus.active)
        )
        undrained = active.num_data_queued > active.num_data_written
        trace.append({"event": "pre_finish", "undrained": undrained})

        await active.finish()
        await _ticks(10)
        trace.append({"event": "post_finish", "action_status": _status_list(active.action)})
    return {"trace": trace}


async def _scenario_nonblocking(save_root: Path) -> dict:
    """Non-blocking action: ``add_status`` short-circuits (no ``status_q`` put) and
    ``send_nonblocking_status`` fans one packet per subscriber out through
    ``base.send_nbstatuspackage``.

    ``base.send_nbstatuspackage`` is replaced with a RECORDING fake (records its
    args onto the trace, returns success). This freezes two things the other
    eight scenarios never touch: (1) the ABSENCE of ``status_packet`` events
    (every ``add_status`` call is suppressed because ``action.nonblocking`` is
    True), and (2) the ``nbstatus_packet`` records emitted per status client."""
    trace: list = []
    base = _make_base(save_root, trace)

    # >=1 status subscriber (single entry -> deterministic set iteration order)
    base.status_clients.add(("NBCLIENT", "127.0.0.1", 9000))

    async def _fake_send_nbstatuspackage(
        client_servkey, client_host, client_port, actionmodel
    ):
        trace.append(
            {
                "event": "nbstatus_packet",
                "client_servkey": client_servkey,
                "client_host": client_host,
                "client_port": client_port,
                "action_name": actionmodel.action_name,
                "action_uuid": str(actionmodel.action_uuid),
                "action_status": [_json_safe(s) for s in actionmodel.action_status],
                "nonblocking": actionmodel.nonblocking,
            }
        )
        return {"success": True}, ErrorCodes.none

    # instance-attribute override shadows the (later delegator) Base method, so
    # this baseline is stable across the S2 extraction.
    base.send_nbstatuspackage = _fake_send_nbstatuspackage

    with _PatchedBaseGlobals(trace):
        action = _mk_action("nonblock", nonblocking=True)
        active = Active(base, _active_params(base, action))
        # myinit() ends in add_status(); nonblocking suppresses the status_q put
        await active.myinit()
        await _ticks()
        trace.append(
            {
                "event": "post_myinit",
                "nonblocking": active.action.nonblocking,
                "action_status": _status_list(active.action),
            }
        )

        await active.enqueue_data_dflt({"t": 0, "v": 0})
        await _drain_data(active)

        # exercise the nonblocking sender directly (executor-free lifecycle)
        await active.send_nonblocking_status()
        await _ticks()
        trace.append(
            {
                "event": "post_send_nonblocking",
                "num_status_clients": len(base.status_clients),
                "action_status": _status_list(active.action),
            }
        )

        await active.finish()
        await _ticks(10)
        trace.append({"event": "post_finish", "action_status": _status_list(active.action)})
    return {"trace": trace}


async def _scenario_executor_concurrent(save_root: Path) -> dict:
    """Concurrent executor driven via ``start_executor`` + ``action_loop_task``.

    ``start_executor`` creates the ``action_task`` (and registers
    ``executor_done_callback``); awaiting it runs the full state machine:
    ``_pre_exec`` -> ``_exec`` (one data packet) -> a bounded ``_poll`` loop
    (``max_polls=3``, three more data packets, ``poll_rate=0``) -> ``_post_exec``
    (one data packet) -> ``finish``. Freezes the enqueued executor data + the
    ``action_loop_running`` transitions + the finish/status trace + streamed
    ``.hlo`` bytes."""
    trace: list = []
    base = _make_base(save_root, trace)
    with _PatchedBaseGlobals(trace):
        action = _mk_action("cexec")
        active = Active(base, _active_params(base, action))
        await active.myinit()
        await _ticks()

        executor = _FakeExecutor(active, oneoff=False, max_polls=3)
        returned = active.start_executor(executor)
        # start_executor only schedules the task (no await between create_task
        # and here) -> the loop has not run yet, so action_loop_running is still
        # False and action_task is a live Task. Deterministic snapshot.
        trace.append(
            {
                "event": "post_start_executor",
                "returned_action": returned is not None,
                "action_loop_running": active.action_loop_running,
                "has_action_task": active.action_task is not None,
            }
        )

        await active.action_task
        await _ticks(10)
        trace.append(
            {
                "event": "post_action_task",
                "action_loop_running": active.action_loop_running,
                "manual_stop": active.manual_stop,
                "action_status": _status_list(active.action),
            }
        )
    return {"trace": trace}


async def _scenario_executor_oneoff(save_root: Path) -> dict:
    """One-off executor driven via ``oneoff_executor`` (``oneoff=True``).

    ``oneoff_executor`` awaits ``action_loop_task`` inline with no poll loop:
    ``_pre_exec`` -> ``_exec`` (one data packet) -> ``_post_exec`` (one data
    packet) -> ``finish``. Freezes the enqueued data + terminal state + trace +
    streamed ``.hlo`` bytes."""
    trace: list = []
    base = _make_base(save_root, trace)
    with _PatchedBaseGlobals(trace):
        action = _mk_action("oexec")
        active = Active(base, _active_params(base, action))
        await active.myinit()
        await _ticks()

        executor = _FakeExecutor(active, oneoff=True)
        returned = await active.oneoff_executor(executor)
        await _ticks(10)
        trace.append(
            {
                "event": "post_oneoff_executor",
                "returned_action": returned is not None,
                "action_loop_running": active.action_loop_running,
                "action_status": _status_list(active.action),
            }
        )
    return {"trace": trace}


SCENARIOS = {
    "1_basic_data_and_file": _scenario_basic,
    "2_save_data_false": _scenario_save_data_false,
    "3_split_keep_active": _scenario_split,
    "4_substitute": _scenario_substitute,
    "5_error_estop": _scenario_error_estop,
    "6_manual_action": _scenario_manual,
    "7_multifile_aux_listen": _scenario_multifile_aux,
    "8_finalizer_global_params": _scenario_finalizer_global_params,
    "9_nonblocking_status": _scenario_nonblocking,
    "10_executor_concurrent": _scenario_executor_concurrent,
    "11_executor_oneoff": _scenario_executor_oneoff,
    "12_finalizer_global_params_dict": _scenario_finalizer_global_params_dict,
    "13_finish_late_data_drain": _scenario_finish_late_data_drain,
}


# ---------------------------------------------------------------------------
# capture / freeze / check
# ---------------------------------------------------------------------------


async def _capture_scenario(name: str, tmp_root: Path) -> "tuple[str, str]":
    """Run one scenario in an isolated save_root; return (trace_text, runs_norm)."""
    scenario_dir = tmp_root / name
    save_root = scenario_dir / "RUNS_ACTIVE"
    save_root.mkdir(parents=True, exist_ok=True)
    result = await SCENARIOS[name](save_root)
    trace_norm = _Normalizer()
    trace_text = trace_norm.sub(
        json.dumps(result["trace"], indent=2, sort_keys=True, default=str)
    )
    # Snapshot the scenario dir (not just RUNS_ACTIVE): manual actions write to a
    # sibling RUNS_DIAG tree (save_root .replace("RUNS_ACTIVE","RUNS_DIAG")), so
    # the whole run tree must be walked to capture every file Active produced.
    runs_norm = _normalize_runs_tree(scenario_dir)
    return trace_text, runs_norm


async def capture_all(tmp_root: Path) -> dict:
    """Capture every scenario; return {name: {"trace":..., "runs":...}}."""
    out = {}
    for name in SCENARIOS:
        trace_text, runs_norm = await _capture_scenario(name, tmp_root)
        out[name] = {"trace": trace_text, "runs": runs_norm}
    return out


def _write_baseline(target: Path, captured: dict) -> None:
    assert target.resolve() != BASELINE_S0A_DIR.resolve() or not any(
        BASELINE_S0A_DIR.glob("*")
    ), (
        "refusing to overwrite a non-empty frozen baseline_S0a/ reference; "
        "delete it deliberately first if a re-freeze is truly intended"
    )
    target.mkdir(parents=True, exist_ok=True)
    for name, data in captured.items():
        (target / f"{name}.trace.jsonl").write_text(data["trace"])
        (target / f"{name}.runs.norm").write_text(data["runs"])


def run_freeze() -> int:
    import tempfile

    if BASELINE_S0A_DIR.is_dir() and any(BASELINE_S0A_DIR.glob("*")):
        print(f"FATAL: frozen baseline already exists at {BASELINE_S0A_DIR}")
        print("refusing to re-freeze; remove it deliberately to regenerate.")
        return 1
    with tempfile.TemporaryDirectory() as tmp_root:
        captured = asyncio.run(capture_all(Path(tmp_root)))
    _write_baseline(BASELINE_S0A_DIR, captured)
    print(f"FROZE {len(captured)} scenarios into {BASELINE_S0A_DIR}")
    for name in captured:
        print(f"  {name}.trace.jsonl + {name}.runs.norm")
    return 0


def run_check() -> int:
    """Hard gate: recapture every scenario and diff against the frozen S0a
    reference (trace bytes exact; runs manifest+text exact; .hlo header exact +
    data multiset)."""
    import tempfile

    if not BASELINE_S0A_DIR.is_dir() or not any(BASELINE_S0A_DIR.glob("*")):
        print(f"FATAL: frozen S0a reference missing/empty: {BASELINE_S0A_DIR}")
        print("run with --freeze first (on unmodified base.py).")
        return 1

    with tempfile.TemporaryDirectory() as tmp_root:
        captured = asyncio.run(capture_all(Path(tmp_root)))

    any_fail = False
    for name in SCENARIOS:
        trace_ref_p = BASELINE_S0A_DIR / f"{name}.trace.jsonl"
        runs_ref_p = BASELINE_S0A_DIR / f"{name}.runs.norm"
        if not trace_ref_p.exists() or not runs_ref_p.exists():
            print(f"  MISSING  {name}: no frozen reference")
            any_fail = True
            continue
        failures = []
        if captured[name]["trace"] != trace_ref_p.read_text():
            failures.append(f"[{name} trace] byte diff vs {trace_ref_p}")
        failures.extend(
            _compare_norm(name, runs_ref_p.read_text(), captured[name]["runs"])
        )
        if failures:
            any_fail = True
            print(f"  DELTA    {name}")
            for f in failures:
                print(f"             {f}")
        else:
            print(f"  PASS     {name}")

    # report stale references
    expected = {f"{n}.trace.jsonl" for n in SCENARIOS} | {f"{n}.runs.norm" for n in SCENARIOS}
    for extra in sorted(p.name for p in BASELINE_S0A_DIR.glob("*") if p.name not in expected):
        print(f"  EXTRA    {extra}: no current scenario")
        any_fail = True

    if any_fail:
        print(f"CHECK FAILED: Active output diverged from {BASELINE_S0A_DIR}")
        return 1
    print(f"CHECK PASSED: all {len(SCENARIOS)} scenarios match {BASELINE_S0A_DIR}")
    return 0


def run_determinism_selftest() -> int:
    """Capture twice to independent temp roots and confirm the normalized output
    (trace bytes + runs multiset/text) is identical run-to-run. Never touches
    the frozen baseline."""
    import tempfile

    with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
        cap1 = asyncio.run(capture_all(Path(t1)))
        cap2 = asyncio.run(capture_all(Path(t2)))

    any_fail = False
    for name in SCENARIOS:
        failures = []
        if cap1[name]["trace"] != cap2[name]["trace"]:
            failures.append(f"[{name} trace] byte diff between two capture runs")
        failures.extend(_compare_norm(name, cap1[name]["runs"], cap2[name]["runs"]))
        if failures:
            any_fail = True
            print(f"  NONDETERMINISTIC  {name}")
            for f in failures:
                print(f"                    {f}")
        else:
            print(f"  STABLE            {name}")

    if any_fail:
        print("DETERMINISM SELF-TEST FAILED")
        return 1
    print(f"DETERMINISM SELF-TEST PASSED: {len(SCENARIOS)} scenarios byte/multiset-stable 2x")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="CARDS P6 S0a Active output golden-master harness."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--freeze",
        action="store_true",
        help="One-time capture of the frozen .omc/artifacts/p6/baseline_S0a/ reference "
        "(refuses if it already exists).",
    )
    group.add_argument(
        "--check",
        action="store_true",
        help="Hard gate: diff freshly captured Active output against the frozen "
        "baseline_S0a/ reference. Exit non-zero on any divergence.",
    )
    args = parser.parse_args()

    if args.freeze:
        raise SystemExit(run_freeze())
    if args.check:
        raise SystemExit(run_check())
    raise SystemExit(run_determinism_selftest())


if __name__ == "__main__":
    main()
