"""Golden characterization of the SYNC default chain, written BEFORE the
finish-hooks refactor (spec §8: "the default chain produces the same S3 keys,
.prg fields and meta json as today").

One sequence / one experiment / two actions, driven through ``sync_yml`` in
child-first order with ``to_s3`` recorded and ``enqueue_yml`` stubbed. Every
literal below is what the pre-refactor code produced; the refactor may ADD
``hooks``/``synced`` to a .prg (compared through LEGACY_PRG_KEYS only) and
may not change anything else asserted here.

Wire-level strengthening over the brief: uploads are recorded as an ORDERED
log (every ``to_s3`` call, including a repeat upload to the same key) so a
per-``_drive``-step ordered key list can be asserted exactly, not just the
overall key set; and the ``action/``, ``experiment/``, ``sequence/`` and
``process/`` JSON bodies -- plus the experiment's ``.prg`` (legacy view) --
are asserted by FULL equality, recursively checking dict KEY ORDER at every
level in addition to `==` (``_assert_ordered_equal``), since `dict.__eq__`
ignores key order but the actual S3 upload bytes (``json.dumps`` of the same
dict) follow it. Two values are genuinely nondeterministic-by-policy and are
normalized (value replaced by a placeholder, key/position left alone) before
that equality check:

- ``hlo_version`` (every uploaded meta dict, and each entry of a nested
  ``dispatched_actions_abbr`` list) is the running code's git short SHA -- it
  changes on every commit (confirmed: it changed from ``580b254a`` to
  ``90ef5cee`` between two runs of this exploration, one commit apart) -- so
  its *value* is replaced with ``"<HLO_VERSION>"``, recursively, while the key
  itself stays at its observed position so presence + position are still
  pinned.
- ``process_uuid`` is generated (uuid5 over process-defining fields) rather
  than supplied by the test tree; it is replaced everywhere it appears
  (including nested under ``dispatched_actions_abbr`` and in
  ``experiment/....json``'s ``process_list``) with the placeholder
  ``"<PUUID>"``. It happens to come out stable for this fixed input tree, but
  the golden must not be coupled to the hash algorithm that produces it.

No other field is normalized: ``action_timestamp`` /``process_timestamp``
looking like ``"1970-01-04 00:23:30.120001"`` is not a clock reading -- it is
what the unchanged code does when it parses the fixture's
``action_timestamp`` string as a bare float and treats it as epoch seconds.
It is fully deterministic for this fixture and is pinned as observed, not
"fixed".

The experiment's `.prg` (``process_actions_done``, ``process_groups``,
``process_metas``) uses **int** keys (confirmed by ``repr()``, not
``json.dumps()``, which would have silently coerced them to strings) -- the
expected literal must use int keys too, or the ordered-key-list check would
spuriously fail on a type mismatch that isn't really there.
"""

import asyncio
import copy

import pytest

import helao.core.drivers.data.sync_driver as legacy_mod
import helao.hexagon.adapters.native.sync_driver as native_mod
from helao.helpers import dispatcher as dispatcher_mod
from helao.hexagon.tests.sync_fixtures import (
    act_meta,
    make_action,
    make_exp_tree,
    make_sync_driver,
    mk_uuid,
    teardown_driver,
    ts,
    write_yml,
)

try:  # exists only after the refactor (Task 9); see settled decision A13
    import helao.core.hooks.builtin.s3_upload as s3_upload_mod  # type: ignore[reportMissingImports]
except ImportError:  # pragma: no cover
    s3_upload_mod = None

HLO = "data-0.0.0.0__0.hlo"
MISC = "notes.txt"
SEQ_UUID = mk_uuid(999)
EXP_UUID = mk_uuid(1)
ACT0_UUID = mk_uuid(0)
ACT1_UUID = mk_uuid(1)  # act_meta(order) uses mk_uuid(order)
PUUID_PLACEHOLDER = "<PUUID>"
HLO_VERSION_PLACEHOLDER = "<HLO_VERSION>"
ANA = {
    "server_key": "ANA",
    "host": "127.0.0.1",
    "port": 8999,
    "endpoint": "analyze_test",
    "analysis_params": {"a": 1},
}
#: .prg keys that exist before the refactor; the refactor may add others.
LEGACY_PRG_KEYS = (
    "yml",
    "api",
    "s3",
    "files_pending",
    "files_s3",
    "process_actions_done",
    "process_groups",
    "process_metas",
    "process_s3",
    "process_api",
    "legacy_finisher_idxs",
    "legacy_experiment",
)

#: Golden bodies (post-normalization: ``hlo_version`` value replaced by
#: HLO_VERSION_PLACEHOLDER at its observed key position, ``process_uuid``
#: value replaced by PUUID_PLACEHOLDER everywhere) for the five record-level
#: S3 uploads. Key order below is the ACTUAL observed order (verified via
#: exploration against the unchanged code, not assumed) -- it is asserted by
#: ``_assert_ordered_equal``, not just ``==``.
ACT0_EXPECTED = {
    "hlo_version": HLO_VERSION_PLACEHOLDER,
    "action_uuid": ACT0_UUID,
    "action_actual_order": 0,
    "orch_submit_order": 0,
    "access": "hte",
    "dummy": False,
    "simulation": False,
    "run_use": "data",
    "action_timestamp": "1970-01-04 00:23:30.120001",
    "action_order": 0,
    "action_retry": 0,
    "action_split": 0,
    "action_name": "test_action",
    "action_params": {"p0": 0},
    "files": [
        {"file_name": MISC, "file_type": "aux__file", "nosync": False},
        {"file_name": f"{HLO}.json", "file_type": "helao__json_file", "nosync": False},
    ],
    "manual_action": False,
    "nonblocking": False,
    "technique_name": "test_tech",
    "process_finish": False,
    "process_contrib": ["action_params"],
    "error_code": "none",
    "sync_data": True,
    "start_condition": 3,
    "save_act": True,
    "save_data": True,
    "sequence_label": "noLabel",
}
ACT1_EXPECTED = {
    "hlo_version": HLO_VERSION_PLACEHOLDER,
    "action_uuid": ACT1_UUID,
    "action_actual_order": 1,
    "orch_submit_order": 1,
    "access": "hte",
    "dummy": False,
    "simulation": False,
    "run_use": "data",
    "action_timestamp": "1970-01-04 00:23:30.120002",
    "action_order": 1,
    "action_retry": 0,
    "action_split": 1,
    "action_name": "test_action",
    "action_params": {"p1": 1},
    "manual_action": False,
    "nonblocking": False,
    "technique_name": "tech_b",
    "process_finish": True,
    "process_contrib": ["action_params"],
    "error_code": "none",
    "sync_data": True,
    "start_condition": 3,
    "save_act": True,
    "save_data": True,
    "sequence_label": "noLabel",
}
PROCESS_EXPECTED = {
    "hlo_version": HLO_VERSION_PLACEHOLDER,
    "process_uuid": PUUID_PLACEHOLDER,
    "sequence_uuid": SEQ_UUID,
    "experiment_uuid": EXP_UUID,
    "access": "hte",
    "dummy": False,
    "simulation": False,
    "technique_name": "tech_b",
    "run_type": "test",
    "run_use": "data",
    "process_timestamp": "1970-01-04 00:23:30.120001",
    "process_params": {"foo": "bar", "p0": 0, "p1": 1},
    "process_group_index": 0,
    "dispatched_actions_abbr": [
        {
            "hlo_version": HLO_VERSION_PLACEHOLDER,
            "action_uuid": ACT0_UUID,
            "action_actual_order": 0,
            "orch_submit_order": 0,
        },
        {
            "hlo_version": HLO_VERSION_PLACEHOLDER,
            "action_uuid": ACT1_UUID,
            "action_actual_order": 1,
            "orch_submit_order": 1,
        },
    ],
}
EXP_EXPECTED = {
    "experiment_uuid": EXP_UUID,
    "experiment_name": "test_exp",
    "experiment_params": {"foo": "bar"},
    "hlo_version": HLO_VERSION_PLACEHOLDER,
    "access": "hte",
    "dummy": False,
    "simulation": False,
    "run_type": "test",
    "run_use": "data",
    "sequence_uuid": SEQ_UUID,
    "process_list": [PUUID_PLACEHOLDER],
    "sync_data": True,
    "sequence_label": "noLabel",
    "manual_action": False,
}
SEQ_EXPECTED = {
    "sequence_name": "test_seq",
    "sequence_params": {"p": 1},
    "sequence_label": "golden",
    "hlo_version": HLO_VERSION_PLACEHOLDER,
    "access": "hte",
    "dummy": False,
    "simulation": False,
    "sequence_uuid": SEQ_UUID,
    "sync_data": True,
    "manual_action": False,
}


def _exp_prg_expected(exp_yml_str: str) -> dict:
    """Full expected legacy-view ``.prg`` for the experiment (see module
    docstring re: int keys). Already in normalized form (placeholders, not
    real values) -- the caller compares this against
    ``_golden_body(_legacy_view(exp_prg), puuid)``, never the raw dict, so
    both sides carry the same placeholders."""
    return {
        "yml": exp_yml_str,
        "api": True,
        "s3": True,
        "process_actions_done": {0: f"{ts(1)}-act.yml", 1: f"{ts(2)}-act.yml"},
        "process_groups": {0: [0, 1]},
        "process_metas": {
            0: {
                "experiment_uuid": EXP_UUID,
                "sequence_uuid": SEQ_UUID,
                "run_type": "test",
                "process_params": {"foo": "bar", "p0": 0, "p1": 1},
                "technique_name": "tech_b",
                "process_uuid": PUUID_PLACEHOLDER,
                "process_group_index": 0,
                "dispatched_actions_abbr": [
                    {
                        "hlo_version": HLO_VERSION_PLACEHOLDER,
                        "action_uuid": ACT0_UUID,
                        "action_actual_order": 0,
                        "orch_submit_order": 0,
                    },
                    {
                        "hlo_version": HLO_VERSION_PLACEHOLDER,
                        "action_uuid": ACT1_UUID,
                        "action_actual_order": 1,
                        "orch_submit_order": 1,
                    },
                ],
                "process_timestamp": "1970-01-04 00:23:30.120001",
            }
        },
        "process_s3": [0],
        "process_api": [0],
        "legacy_finisher_idxs": [1],
        "legacy_experiment": True,
    }


def _legacy_view(prg_dict: dict) -> dict:
    return {k: v for k, v in prg_dict.items() if k in LEGACY_PRG_KEYS}


def _golden_body(payload, puuid: str):
    """Replace the run-generated ``hlo_version`` VALUE (the key stays, at its
    observed position -- see module docstring) and the run-generated process
    uuid with placeholders, recursively, so the rest of the body can be
    asserted by full equality including key order (``_assert_ordered_equal``)."""
    if isinstance(payload, dict):
        return {
            k: (
                HLO_VERSION_PLACEHOLDER
                if k == "hlo_version"
                else _golden_body(v, puuid)
            )
            for k, v in payload.items()
        }
    if isinstance(payload, list):
        return [_golden_body(v, puuid) for v in payload]
    if payload == puuid:
        return PUUID_PLACEHOLDER
    return payload


def _assert_ordered_equal(actual, expected, path: str = "$") -> None:
    """``==`` plus, recursively at every dict level, ``list(keys) ==
    list(keys)``: plain dict equality ignores key order, but the actual S3
    upload bytes (``json.dumps`` of the same dict) follow it, so this is what
    really pins the wire format rather than just its contents."""
    assert actual == expected, f"{path}: {actual!r} != {expected!r}"
    if isinstance(expected, dict):
        assert list(actual.keys()) == list(
            expected.keys()
        ), f"{path} key order: {list(actual.keys())} != {list(expected.keys())}"
        for k in expected:
            _assert_ordered_equal(actual[k], expected[k], f"{path}.{k}")
    elif isinstance(expected, list):
        for i, (a, e) in enumerate(zip(actual, expected)):
            _assert_ordered_equal(a, e, f"{path}[{i}]")


class _UploadLog(dict):
    """``{target: latest payload}`` (unchanged interface: still a plain dict
    for Task 9's reuse -- ``in``, ``[...]``, ``set(...)`` all work as before)
    PLUS an ordered ``.log`` of EVERY upload, including a repeat upload to the
    same key. The dict view alone can't show a duplicate (the second write
    just overwrites the first at the same key), so ``_drive`` slices
    ``.log`` -- not the dict -- to build each step's ordered key list."""

    def __init__(self):
        super().__init__()
        self.log: list[tuple] = []


def _record_uploads(drv) -> dict:
    """Stub ``to_s3`` to record ``{key: payload}`` plus an ordered upload
    log (see ``_UploadLog``); a dict payload is deep-copied."""
    uploads = _UploadLog()

    async def accept(msg=None, target=None, compress=False, retries=5):
        payload = copy.deepcopy(msg) if isinstance(msg, dict) else str(msg)
        uploads[target] = payload
        uploads.log.append((target, payload))
        return True

    drv.to_s3 = accept
    return uploads


def _build_tree(root):
    exp_yml = make_exp_tree(root, "RUNS", EXP_UUID)
    seq_dir = exp_yml.parent.parent
    seq_yml = seq_dir / f"{ts(0)}-seq.yml"
    write_yml(
        seq_yml,
        {
            "sequence_uuid": SEQ_UUID,
            "sequence_name": "test_seq",
            "sequence_label": "golden",
            "sequence_params": {"p": 1},
        },
    )
    act0 = make_action(exp_yml, 0)  # process_finish False
    (act0.parent / HLO).write_text("x")
    (act0.parent / MISC).write_text("note")
    act0.write_text(
        act0.read_text()
        + f"files:\n- file_name: {HLO}\n  file_type: helao__file\n"
        + f"- file_name: {MISC}\n  file_type: aux__file\n"
    )
    act1 = make_action(exp_yml, 1, process_finish=True)
    # Controller ruling: rewrite the whole yml from a merged dict instead of
    # appending duplicate `technique_name`/`action_split` keys as raw text --
    # the append made yml_load raise DuplicateKeyError.
    write_yml(
        act1,
        {
            **act_meta(1, True),
            "technique_name": ["tech_a", "tech_b"],
            "action_split": 1,
        },
    )
    return seq_yml, exp_yml, act0, act1


async def _drive(drv, ymls, uploads):
    """Drive ``sync_yml`` for each (yml, rank) pair; return the enqueue_yml
    calls plus, per step, the ordered list of upload keys made during that
    step -- sliced from ``uploads.log`` (every call, duplicates included),
    NOT from the dict's keys (which would collapse a duplicate upload to the
    same key and hide it)."""
    calls = []

    async def record(upath, rank=0, rank_limit=-5):
        calls.append((str(upath), rank))

    drv.enqueue_yml = record
    steps = []
    for yml, rank in ymls:
        log_before = len(uploads.log)
        await asyncio.wait_for(drv.sync_yml(yml_path=yml, rank=rank), timeout=30)
        steps.append([target for target, _ in uploads.log[log_before:]])
    return calls, steps


@pytest.mark.parametrize("mod", [legacy_mod, native_mod])
@pytest.mark.asyncio
async def test_default_chain_golden(tmp_path, mod, monkeypatch):
    fake_hlo = lambda fp: ({"k": "v"}, {"t_s": [0.0], "value": [1.0]})  # noqa: E731
    monkeypatch.setattr(mod, "read_hlo", fake_hlo, raising=False)
    if s3_upload_mod is not None:
        monkeypatch.setattr(s3_upload_mod, "read_hlo", fake_hlo)

    dispatched = []

    async def fake_dispatch(world_config_dict=None, A=None, **kw):
        dispatched.append((world_config_dict, A))
        return {}, None

    monkeypatch.setattr(mod, "async_action_dispatcher", fake_dispatch, raising=False)
    monkeypatch.setattr(dispatcher_mod, "async_action_dispatcher", fake_dispatch)

    drv = make_sync_driver(
        tmp_path,
        mod.SyncDriver,
        cfg_extra={"auto_analyze_sequences": {"test_seq": ANA}},
    )
    try:
        seq_yml, exp_yml, act0, act1 = _build_tree(tmp_path)
        uploads = _record_uploads(drv)
        calls, steps = await _drive(
            drv, [(act0, 0), (act1, 0), (exp_yml, 1), (seq_yml, 2)], uploads
        )

        # --- process uuid (generated; needed to build expected keys) ----
        exp_prg = mod.Progress(exp_yml).dict
        assert len(exp_prg["process_metas"]) == 1, exp_prg
        ((_pidx, pmeta),) = exp_prg["process_metas"].items()
        puuid = pmeta["process_uuid"]

        # --- S3 key set --------------------------------------------------
        assert set(uploads) == {
            f"raw_data/{ACT0_UUID}/{HLO}.json",
            f"raw_data/{ACT0_UUID}/{MISC}",
            f"action/{ACT0_UUID}.json",
            f"action/{ACT1_UUID}.json",
            f"process/{puuid}.json",
            f"experiment/{EXP_UUID}.json",
            f"sequence/{SEQ_UUID}.json",
        }, sorted(uploads)

        # --- ordered upload keys per _drive step (wire-level) ------------
        assert steps == [
            [
                f"raw_data/{ACT0_UUID}/{HLO}.json",
                f"raw_data/{ACT0_UUID}/{MISC}",
                f"action/{ACT0_UUID}.json",
            ],
            [f"action/{ACT1_UUID}.json", f"process/{puuid}.json"],
            [f"experiment/{EXP_UUID}.json"],
            [f"sequence/{SEQ_UUID}.json"],
        ], steps

        # --- bodies: raw_data (deterministic, no normalization needed) ---
        assert uploads[f"raw_data/{ACT0_UUID}/{HLO}.json"] == {
            "meta": {"k": "v"},
            "data": {"t_s": [0.0], "value": [1.0]},
        }
        assert uploads[f"raw_data/{ACT0_UUID}/{MISC}"] == str(act0.parent / MISC)

        # --- bodies: action/experiment/sequence/process (FULL equality, ---
        # --- key order included -- see _assert_ordered_equal) ------------
        _assert_ordered_equal(
            _golden_body(uploads[f"action/{ACT0_UUID}.json"], puuid),
            ACT0_EXPECTED,
            path=f"action/{ACT0_UUID}.json",
        )
        _assert_ordered_equal(
            _golden_body(uploads[f"action/{ACT1_UUID}.json"], puuid),
            ACT1_EXPECTED,
            path=f"action/{ACT1_UUID}.json",
        )
        _assert_ordered_equal(
            _golden_body(uploads[f"process/{puuid}.json"], puuid),
            PROCESS_EXPECTED,
            path=f"process/{puuid}.json",
        )
        _assert_ordered_equal(
            _golden_body(uploads[f"experiment/{EXP_UUID}.json"], puuid),
            EXP_EXPECTED,
            path=f"experiment/{EXP_UUID}.json",
        )
        _assert_ordered_equal(
            _golden_body(uploads[f"sequence/{SEQ_UUID}.json"], puuid),
            SEQ_EXPECTED,
            path=f"sequence/{SEQ_UUID}.json",
        )

        # --- .prg sidecars (legacy keys only) ----------------------------
        act0_prg = _legacy_view(mod.Progress(act0).dict)
        assert act0_prg == {
            "yml": str(act0),
            "api": True,
            "s3": True,
            "files_pending": [],
            "files_s3": {
                HLO: f"raw_data/{ACT0_UUID}/{HLO}.json",
                MISC: f"raw_data/{ACT0_UUID}/{MISC}",
            },
        }
        assert _legacy_view(mod.Progress(act1).dict) == {
            "yml": str(act1),
            "api": True,
            "s3": True,
            "files_pending": [],
            "files_s3": {},
        }
        # Experiment .prg: FULL equality (not spot checks), same
        # placeholder-normalization + key-order pinning as the S3 bodies.
        exp_view = _legacy_view(exp_prg)
        _assert_ordered_equal(
            _golden_body(exp_view, puuid),
            _exp_prg_expected(str(exp_yml)),
            path="exp.prg",
        )
        assert list(exp_yml.parent.glob("*-prc.yml")), "no local -prc.yml written"
        seq_view = _legacy_view(mod.Progress(seq_yml).dict)
        assert seq_view == {"yml": str(seq_yml), "api": True, "s3": True}

        # --- everything is judged synced --------------------------------
        for yml in (act0, act1, exp_yml, seq_yml):
            assert mod.HelaoYml(yml).status == "synced", yml

        # --- auto-analysis dispatch payload ------------------------------
        assert len(dispatched) == 1
        world, A = dispatched[0]
        assert world == {"servers": {"ANA": ANA}}
        assert A.action_name == "analyze_test"
        assert A.action_server.server_name == "ANA"
        assert A.action_params == {
            "sequence_path": str(seq_yml.parent),
            "params": {"a": 1},
        }
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", [legacy_mod, native_mod])
@pytest.mark.asyncio
async def test_default_chain_without_auto_analysis_dispatches_nothing(
    tmp_path, mod, monkeypatch
):
    monkeypatch.setattr(mod, "read_hlo", lambda fp: ({}, {}), raising=False)
    if s3_upload_mod is not None:
        monkeypatch.setattr(s3_upload_mod, "read_hlo", lambda fp: ({}, {}))
    dispatched = []

    async def fake_dispatch(world_config_dict=None, A=None, **kw):
        dispatched.append(A)
        return {}, None

    monkeypatch.setattr(mod, "async_action_dispatcher", fake_dispatch, raising=False)
    monkeypatch.setattr(dispatcher_mod, "async_action_dispatcher", fake_dispatch)
    drv = make_sync_driver(tmp_path, mod.SyncDriver)
    try:
        seq_yml, exp_yml, act0, act1 = _build_tree(tmp_path)
        uploads = _record_uploads(drv)
        await _drive(drv, [(act0, 0), (act1, 0), (exp_yml, 1), (seq_yml, 2)], uploads)
        assert dispatched == []
        assert mod.HelaoYml(seq_yml).status == "synced"
    finally:
        await teardown_driver(drv)
