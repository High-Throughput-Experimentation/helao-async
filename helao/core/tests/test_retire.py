"""Unit tests for helao/ui/shared/retire.py line scans, locate, in_flight."""

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from helao.core.tests.retire_fakes import FakeMetadataClient, make_run_tree
from helao.helpers.openapi_client import AsyncOpenAPIClient
from helao.ui.shared import retire

U = "11111111-2222-3333-4444-555555555555"
REL = "26.40/1005/20261005.100000__SEQ"


def test_prefix_uuid_does_not_match(tmp_path):
    """Mutation: startswith/in instead of strip-equality in names_uuid/top_level."""
    root = str(tmp_path)
    make_run_tree(root, "RUNS_FINISHED", REL, sequence_uuid=U)
    make_run_tree(
        root, "RUNS_FINISHED", "26.40/1005/20261005.110000__SEQ", sequence_uuid=U + "0"
    )
    locs = retire.locate(root, U)
    assert [l.rel_dir for l in locs] == [REL]


def test_indented_sequence_uuid_creates_no_location(tmp_path):
    """Mutation: line.lstrip() before matching."""
    root = str(tmp_path)
    d = tmp_path / "RUNS" / "26.40" / "1005" / "s"
    d.mkdir(parents=True)
    (d / "a-seq.yml").write_text(f"sequence_name: x\n  sequence_uuid: {U}\n")
    assert retire.locate(root, U) == []


def test_runs_superseded_is_skipped(tmp_path):
    """Mutation: removing the RUNS_SUPERSEDED exclusion."""
    root = str(tmp_path)
    make_run_tree(
        root, "RUNS_SUPERSEDED", "20261005_retired/RUNS/26.40/1005/s", sequence_uuid=U
    )
    # also at a depth the RUNS*/*/*/*/*-seq.yml glob reaches, so the exclusion bites
    make_run_tree(root, "RUNS_SUPERSEDED", "a/b/s", sequence_uuid=U)
    make_run_tree(root, "RUNS_FINISHED", REL, sequence_uuid=U)
    locs = retire.locate(root, U)
    assert len(locs) == 1 and locs[0].run_tree == "RUNS_FINISHED"


def test_locate_reads_label_name_campaign(tmp_path):
    """Mutation: reading the indented line, or the first occurrence anywhere."""
    root = str(tmp_path)
    make_run_tree(
        root, "RUNS", REL, sequence_uuid=U, label="L1", name="N1", campaign="C1"
    )
    make_run_tree(root, "RUNS_SYNCED", REL, sequence_uuid=U, label="L2", name="N2")
    yml = os.path.join(root, "RUNS", REL, "20261001.000000-seq.yml")
    with open(yml) as f:
        text = f.read()
    with open(yml, "w") as f:  # a later top-level duplicate must not win
        f.write(text.replace("sequence_name:", "sequence_label: later\nsequence_name:"))
    a, b = retire.locate(root, U)
    assert (a.run_tree, a.label, a.name, a.campaign) == ("RUNS", "L1", "N1", "C1")
    assert (b.run_tree, b.label, b.name, b.campaign) == ("RUNS_SYNCED", "L2", "N2", "")
    assert a.rel_dir == REL and a.seq_yml.endswith("-seq.yml")


def _state(d, name, body):
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(body if isinstance(body, str) else json.dumps(body))
    return str(p)


def test_in_flight_matches_uuid_or_output_dir(tmp_path):
    """Mutation: dropping the sequence_output_dir comparison, dropping the
    backslash normalisation, or removing the isinstance(dict) check."""
    src = tmp_path / "sources"
    proc = src / "host1" / "processing"
    claimed = {"sequence_uuid": None, "sequence_output_dir": None}
    _state(proc, "c.state.json", claimed)
    _state(proc, "m.state.json", "{not json")
    _state(proc, "l.state.json", [1])
    assert retire.in_flight(str(src), U, [REL]) is None
    by_uuid = _state(proc, "u.state.json", {"sequence_uuid": U})
    assert retire.in_flight(str(src), U, [REL]) == by_uuid
    os.remove(by_uuid)
    by_dir = _state(
        proc,
        "d.state.json",
        {
            "sequence_uuid": "other",
            "sequence_output_dir": "\\" + REL.replace("/", "\\"),
        },
    )
    assert retire.in_flight(str(src), U, [REL]) == by_dir


def test_ledger_path_for_is_utc_stamped():
    """Mutation: dropping astimezone(utc)."""
    now = datetime(2026, 10, 6, 1, 2, 3, tzinfo=timezone(timedelta(hours=-7)))
    assert (
        retire.ledger_path_for("/r", "u", now)
        == "/r/STATES/retire_u_20261006T080203Z.jsonl"
    )


def test_nothing_to_retire_property():
    """Mutation: any() -> all() over in_api, or dropping sequence_in_api."""

    def inv(in_api=None, seq=False):
        return retire.Inventory(
            sequence_uuid=U,
            locations=[],
            local={t: set() for t in retire.ENTITY_TYPES},
            in_api=in_api or {t: set() for t in retire.ENTITY_TYPES},
            sequence_in_api=seq,
            sequence_label="",
            campaign_name="",
            api_only=False,
            analysis_dirs=[],
        )

    assert inv().nothing_to_retire
    one = {t: set() for t in retire.ENTITY_TYPES}
    one["PROCESS"] = {"p"}
    assert not inv(one).nothing_to_retire
    assert not inv(seq=True).nothing_to_retire


def test_classifiers_read_the_real_client_error_format():
    """Mutation: matching "404" anywhere (uuid in the URL), or folding 5xx into
    not-found."""
    c = object.__new__(AsyncOpenAPIClient)

    def err(code):
        req = httpx.Request("GET", "https://h/api/sequence/404-uuid")
        with pytest.raises(RuntimeError) as ei:
            c._handle_response(
                "read_sequence", httpx.Response(code, json={"detail": "x"}, request=req)
            )
        return ei.value

    e404, e500, e504 = err(404), err(500), err(504)
    assert retire.is_not_found(e404) and not retire.is_timeout_or_504(e404)
    assert not retire.is_not_found(e500) and not retire.is_timeout_or_504(e500)
    assert not retire.is_not_found(e504) and retire.is_timeout_or_504(e504)
    fake = FakeMetadataClient({})
    fake.fail[("read", "t")] = "timeout"
    with pytest.raises(RuntimeError) as ei:
        asyncio.run(fake.read_action(action_uuid="t"))
    assert retire.is_timeout_or_504(ei.value) and not retire.is_not_found(ei.value)


async def _noprogress(*a):
    pass


EXPS: dict[str, list[tuple[str, str | None]]] = {
    "E1": [("A1", "P1"), ("A2", "P2")],
    "E2": [("A3", "P3")],
}


def _full_client():
    rows = {
        "SEQUENCE": {U},
        "EXPERIMENT": {"E1", "E2"},
        "ACTION": {"A1", "A2", "A3"},
        "PROCESS": {"P1", "P2", "P3", "P_api"},
        "ANALYSIS": {"AN1"},
    }
    return FakeMetadataClient(
        rows,
        seq_processes={U: ["P1", "P2", "P3", "P_api"]},
        analyses={"P_api": ["AN1"]},
    )


def test_inventory_counts_local_and_api_including_api_only_processes(tmp_path):
    """Mutation: dropping the read_processes_by_sequence union."""
    root = str(tmp_path)
    make_run_tree(root, "RUNS", REL, sequence_uuid=U, experiments=EXPS)
    ticks = []

    async def progress(*a):
        ticks.append(a)

    inv = asyncio.run(retire.inventory(_full_client(), root, U, progress))
    assert len(inv.local["PROCESS"]) == 3 and not inv.local["ANALYSIS"]
    assert len(inv.in_api["PROCESS"]) == 4
    assert len(inv.in_api["ANALYSIS"]) == 1 and inv.sequence_in_api
    assert not inv.api_only
    assert ticks[0] == ("scan", 5, 5)
    assert [t for t in ticks if t[0] == "probe"][-1] == ("probe", 12, 12)


def test_probe_500_raises_and_is_not_counted_absent(tmp_path):
    """Mutation: `except Exception: return False` in exists."""
    root = str(tmp_path)
    make_run_tree(root, "RUNS", REL, sequence_uuid=U, experiments=EXPS)
    client = _full_client()
    client.fail[("read", "A1")] = "500"
    with pytest.raises(RuntimeError, match="probe of ACTION A1 failed"):
        asyncio.run(retire.inventory(client, root, U, _noprogress))


def test_api_only_inventory(tmp_path):
    """Mutation: setting api_only from in_api alone."""
    client = FakeMetadataClient(
        {"SEQUENCE": {U}, "PROCESS": {"P_api"}}, seq_processes={U: ["P_api"]}
    )
    client.sequence_body = {"sequence_label": "APIL", "campaign_name": "APIC"}
    inv = asyncio.run(retire.inventory(client, str(tmp_path), U, _noprogress))
    assert inv.api_only and not inv.locations
    assert all(not v for v in inv.local.values())
    assert (inv.sequence_label, inv.campaign_name) == ("APIL", "APIC")
    # a local tree makes it not api_only
    root = str(tmp_path / "t")
    make_run_tree(root, "RUNS", REL, sequence_uuid=U)
    assert not asyncio.run(retire.inventory(client, root, U, _noprogress)).api_only


def test_nothing_to_retire(tmp_path):
    """Mutation: a property that ignores sequence_in_api."""
    inv = asyncio.run(
        retire.inventory(FakeMetadataClient({}), str(tmp_path), U, _noprogress)
    )
    assert inv.nothing_to_retire and not inv.api_only
    only_seq = FakeMetadataClient({"SEQUENCE": {U}})
    inv = asyncio.run(retire.inventory(only_seq, str(tmp_path), U, _noprogress))
    assert not inv.nothing_to_retire


def test_null_uuid_values_are_skipped(tmp_path):
    """Mutation: removing the null-value filter in top_level."""
    root = str(tmp_path)
    make_run_tree(
        root, "RUNS", REL, sequence_uuid=U, experiments={"E1": [("A1", None)]}
    )
    client = FakeMetadataClient({"EXPERIMENT": {"E1"}, "ACTION": {"A1"}})
    read = []
    orig = client.read_process

    async def spy(*, process_uuid):
        read.append(process_uuid)
        return await orig(process_uuid=process_uuid)

    client.read_process = spy
    inv = asyncio.run(retire.inventory(client, root, U, _noprogress))
    assert inv.local["PROCESS"] == set() and read == []
    assert not any("null" in v for v in inv.local.values())


def test_analysis_dirs_are_reported_not_required(tmp_path):
    """Mutation: globbing one level too shallow."""
    root = str(tmp_path)
    make_run_tree(root, "RUNS", REL, sequence_uuid=U, experiments=EXPS)
    client = _full_client()
    inv = asyncio.run(retire.inventory(client, root, U, _noprogress))
    assert inv.analysis_dirs == []
    d = tmp_path / "ANALYSES" / "2026" / "1005" / "120000__x"
    d.mkdir(parents=True)
    (d / "out.yml").write_text("process_uuid: P2\n")
    other = tmp_path / "ANALYSES" / "2026" / "1005" / "130000__y"
    other.mkdir()
    (other / "out.json").write_text('{"process_uuid": "unrelated"}')
    inv = asyncio.run(retire.inventory(client, root, U, _noprogress))
    assert inv.analysis_dirs == [str(d)]


def test_analysis_dirs_read_only_yml_and_skip_non_files(tmp_path):
    """Mutation: reading every file (drop the .yml filter), or treating a
    directory named *.yml as a file."""
    root = str(tmp_path)
    make_run_tree(root, "RUNS", REL, sequence_uuid=U, experiments=EXPS)
    base = tmp_path / "ANALYSES" / "2026" / "1005"
    only_json = base / "120000__j"
    only_json.mkdir(parents=True)
    (only_json / "out.json").write_text('{"process_uuid": "P2"}')
    bad = base / "130000__bad"
    bad.mkdir()
    (bad / "x.yml").mkdir()  # a directory named x.yml: not a file, skipped
    inv = asyncio.run(retire.inventory(_full_client(), root, U, _noprogress))
    assert inv.analysis_dirs == []


def test_unreadable_yml_oserror_is_skipped(tmp_path, monkeypatch):
    """Mutation: removing the except OSError in _analysis_dirs."""
    d = tmp_path / "ANALYSES" / "2026" / "1005" / "120000__x"
    d.mkdir(parents=True)
    (d / "a.yml").write_text("P2")
    real_open = open

    def boom(path, *a, **k):
        if str(path).endswith("a.yml"):
            raise PermissionError("denied")
        return real_open(path, *a, **k)

    monkeypatch.setattr("builtins.open", boom)
    assert retire._analysis_dirs(str(tmp_path), {"P2"}) == []


def test_failed_probe_cancels_pending_probes(tmp_path):
    """Mutation: dropping the cancel of pending tasks on failure (the raise then
    leaves the slow reads pending, so none records a cancellation)."""
    root = str(tmp_path)
    make_run_tree(root, "RUNS", REL, sequence_uuid=U, experiments=EXPS)
    client = _full_client()
    client.fail[("read", "A1")] = "500"
    never = asyncio.Event()
    cancelled: list[str] = []

    async def slow(*, experiment_uuid):
        try:
            await never.wait()
        except asyncio.CancelledError:
            cancelled.append(experiment_uuid)
            raise

    setattr(client, "read_experiment", slow)

    async def run():
        with pytest.raises(RuntimeError):
            await asyncio.wait_for(
                retire.inventory(client, root, U, _noprogress), timeout=5
            )
        # before loop teardown, whose shutdown would cancel the orphans anyway
        assert sorted(cancelled) == ["E1", "E2"]

    asyncio.run(run())


def test_processes_by_sequence_non_list_raises(tmp_path):
    """Mutation: dropping the isinstance(list) check."""
    client = _full_client()

    async def bad(*, sequence_uuid):
        return {"detail": "x"}

    setattr(client, "read_processes_by_sequence", bad)
    with pytest.raises(
        RuntimeError,
        match=r"read_processes_by_sequence returned dict; expected a list",
    ):
        asyncio.run(retire.inventory(client, str(tmp_path), U, _noprogress))


def test_processes_by_sequence_404_is_empty(tmp_path):
    """Mutation: letting the 404 from read_processes_by_sequence propagate."""
    client = _full_client()
    client.fail[("read", U)] = "404"  # read_sequence 404 too
    inv = asyncio.run(retire.inventory(client, str(tmp_path), U, _noprogress))
    assert inv.in_api["PROCESS"] == set() and not inv.sequence_in_api


def test_api_only_without_sequence_row_via_process(tmp_path):
    """Mutation: api_only ignoring in_api rows when the sequence row is absent."""
    client = FakeMetadataClient({"PROCESS": {"P_api"}}, seq_processes={U: ["P_api"]})
    inv = asyncio.run(retire.inventory(client, str(tmp_path), U, _noprogress))
    assert not inv.sequence_in_api and inv.api_only and not inv.nothing_to_retire


def test_null_uuid_in_api_list_rows_is_skipped(tmp_path):
    """Mutation: indexing ["process_uuid"]/["analysis_uuid"] without .get/skip."""
    client = FakeMetadataClient({"SEQUENCE": {U}})

    async def procs(*, sequence_uuid):
        return [{"process_uuid": None}, {"process_uuid": "P9"}]

    async def ans(*, process_uuid):
        return [{"analysis_uuid": None}, {}]

    client.read_processes_by_sequence = procs
    client.read_analysis_by_process = ans
    inv = asyncio.run(retire.inventory(client, str(tmp_path), U, _noprogress))
    assert inv.in_api["PROCESS"] == {"P9"} and inv.in_api["ANALYSIS"] == set()


# ---- retire() ---------------------------------------------------------------

TODAY = lambda: datetime.now(timezone.utc).strftime("%Y%m%d")  # noqa: E731


def _setup(tmp_path, run_trees=("RUNS_FINISHED",), client=None, experiments=EXPS):
    root = str(tmp_path)
    for rt in run_trees:
        make_run_tree(root, rt, REL, sequence_uuid=U, experiments=experiments)
    client = client or _full_client()
    inv = asyncio.run(retire.inventory(client, root, U, _noprogress))
    ledger = os.path.join(root, "STATES", "retire_test.jsonl")
    return root, client, inv, ledger


def _run(client, root, inv, ledger, progress=_noprogress):
    return asyncio.run(retire.retire(client, root, inv, progress, ledger))


def _lines(ledger):
    with open(ledger) as f:
        return [json.loads(x) for x in f]


def _src(root, rt="RUNS_FINISHED"):
    return os.path.join(root, rt, *REL.split("/"))


def _dst(root, rt="RUNS_FINISHED"):
    return os.path.join(
        root, "RUNS_SUPERSEDED", f"{TODAY()}_retired", rt, *REL.split("/")
    )


def _yielding(client):
    """Record ("start"|"end", type) around each delete, yielding in between so a
    delete that is not gated on the previous type can overlap it."""
    events: list[tuple[str, str]] = []
    real = client.delete_command

    async def delete(*, entity_type, primary_id, delete_connected_processes):
        events.append(("start", entity_type))
        await asyncio.sleep(0)
        try:
            return await real(
                entity_type=entity_type,
                primary_id=primary_id,
                delete_connected_processes=delete_connected_processes,
            )
        finally:
            events.append(("end", entity_type))

    setattr(client, "delete_command", delete)
    return events


def test_delete_order_is_children_first(tmp_path):
    """Mutation: swapping two entries of DELETE_ORDER, or one gather over all the
    rows (every type starts at once)."""
    root, client, inv, ledger = _setup(tmp_path)
    events = _yielding(client)
    res = _run(client, root, inv, ledger)
    assert res.ok, res.error
    order = ["ANALYSIS", "ACTION", "PROCESS", "EXPERIMENT", "SEQUENCE"]
    assert {t for _, t in events} == set(order)
    for k, t in enumerate(order[:-1]):
        last_end = max(i for i, e in enumerate(events) if e == ("end", t))
        later = [
            i
            for i, (kind, u) in enumerate(events)
            if kind == "start" and order.index(u) > k
        ]
        assert min(later) > last_end, (t, events)


def test_action_500_stops_before_sequence_and_move(tmp_path):
    """Mutation: `continue` instead of stop, moving before checking, or one gather
    over all the rows."""
    root, client, inv, ledger = _setup(tmp_path)
    client.fail[("delete", "A1")] = "500"
    _yielding(client)  # lets every other delete start before A1 fails
    res = _run(client, root, inv, ledger)
    assert not res.ok and "no files were moved" in res.error
    assert not {"PROCESS", "EXPERIMENT", "SEQUENCE"} & {c[1] for c in client.calls}
    assert os.path.isdir(_src(root)) and not os.path.exists(_dst(root))
    assert res.moved == []


def test_sequence_504_then_probe_404_succeeds(tmp_path):
    """Mutation: trusting the 504 as an error without probing."""
    root, client, inv, ledger = _setup(tmp_path)
    client.fail[("delete", U)] = "504"
    real = client.delete_command

    async def delete_then_504(*, entity_type, primary_id, delete_connected_processes):
        if entity_type == "SEQUENCE":
            client.rows["SEQUENCE"].discard(primary_id)
        return await real(
            entity_type=entity_type,
            primary_id=primary_id,
            delete_connected_processes=delete_connected_processes,
        )

    setattr(client, "delete_command", delete_then_504)
    res = _run(client, root, inv, ledger)
    assert res.ok, res.error
    seq = [x for x in _lines(ledger) if x["entity_type"] == "SEQUENCE"]
    assert seq[-1]["outcome"] == "deleted"
    assert seq[-1]["detail"] == "confirmed absent after timeout/504"
    assert os.path.isdir(_dst(root))


def test_sequence_timeout_then_probe_200_fails(tmp_path):
    """Mutation: treating any timeout as success."""
    root, client, inv, ledger = _setup(tmp_path)
    client.fail[("delete", U)] = "timeout"
    res = _run(client, root, inv, ledger)
    assert not res.ok and "no files were moved" in res.error
    assert os.path.isdir(_src(root)) and not os.path.exists(_dst(root))
    seq = [l for l in _lines(ledger) if l["entity_type"] == "SEQUENCE"]
    assert [l["outcome"] for l in seq] == ["start", "error"]


def test_persisting_experiment_action_warn_but_succeed(tmp_path):
    """Mutation: putting EXPERIMENT in MUST_404."""
    root, client, inv, ledger = _setup(tmp_path)
    client.persist = {"E1", "A1"}
    res = _run(client, root, inv, ledger)
    assert res.ok, res.error
    assert res.persisting == {"EXPERIMENT": ["E1"], "ACTION": ["A1"]}
    assert os.path.isdir(_dst(root)) and not os.path.exists(_src(root))
    assert {x["uuid"] for x in _lines(ledger) if x["outcome"] == "persists"} == {
        "E1",
        "A1",
    }


def test_persisting_process_fails_before_move(tmp_path):
    """Mutation: removing PROCESS from MUST_404."""
    root, client, inv, ledger = _setup(tmp_path)
    client.persist = {"P1"}
    res = _run(client, root, inv, ledger)
    assert not res.ok and "P1" in res.error and "no files were moved" in res.error
    assert os.path.isdir(_src(root))


def test_ledger_has_one_line_per_row_and_survives_failure(tmp_path, monkeypatch):
    """Mutation: buffering lines and writing them at the end."""
    monkeypatch.setattr(retire, "DELETE_CONCURRENCY", 1)
    exps = {"E1": [("A1", None), ("A2", None), ("A3", None)]}
    client = FakeMetadataClient(
        {
            "SEQUENCE": {U},
            "EXPERIMENT": {"E1"},
            "ACTION": {"A1", "A2", "A3"},
            "PROCESS": {"P_api"},
            "ANALYSIS": {"AN1"},
        },
        seq_processes={U: ["P_api"]},
        analyses={"P_api": ["AN1"]},
    )
    root, client, inv, ledger = _setup(tmp_path, client=client, experiments=exps)
    acts = sorted(inv.in_api["ACTION"])
    client.fail[("delete", acts[1])] = "500"
    seen = []
    real = client.delete_command

    async def checked(*, entity_type, primary_id, delete_connected_processes):
        if primary_id == acts[1]:
            seen.extend(_lines(ledger))  # earlier lines must already be on disk
        return await real(
            entity_type=entity_type,
            primary_id=primary_id,
            delete_connected_processes=delete_connected_processes,
        )

    setattr(client, "delete_command", checked)
    res = _run(client, root, inv, ledger)
    assert not res.ok
    assert [(x["entity_type"], x["outcome"]) for x in seen] == [
        ("SEQUENCE", "start"),
        ("ANALYSIS", "deleted"),
        ("ACTION", "deleted"),
    ]
    final = _lines(ledger)
    assert [(x["entity_type"], x["outcome"]) for x in final] == [
        ("SEQUENCE", "start"),
        ("ANALYSIS", "deleted"),
        ("ACTION", "deleted"),
        ("ACTION", "error"),
    ]
    assert {"ts", "entity_type", "uuid", "outcome", "detail"} <= set(final[-1])


def test_run_dir_lands_in_superseded_layout(tmp_path):
    """Mutation: dropping <run_tree> from the dst."""
    root, client, inv, ledger = _setup(tmp_path)
    res = _run(client, root, inv, ledger)
    assert res.ok, res.error
    assert res.moved == [(_src(root), _dst(root))]
    assert os.path.isdir(_dst(root)) and not os.path.exists(_src(root))
    moved = [x for x in _lines(ledger) if x["outcome"] == "moved"]
    assert moved[0]["entity_type"] == "DIR"
    assert (moved[0]["uuid"], moved[0]["detail"]) == (_src(root), _dst(root))


def test_changed_seq_yml_refuses_with_zero_deletes(tmp_path):
    """Mutation: removing the re-verify."""
    root, client, inv, ledger = _setup(tmp_path)
    yml = inv.locations[0].seq_yml
    with open(yml) as f:
        text = f.read()
    with open(yml, "w") as f:
        f.write(text.replace(f"\nsequence_uuid: {U}\n", "\nsequence_uuid: other\n"))
    res = _run(client, root, inv, ledger)
    assert not res.ok and "re-gather" in res.error
    assert client.calls == [] and os.path.isdir(_src(root))


def test_source_equal_to_run_tree_root_is_refused(tmp_path):
    """Mutation: `>=` containment instead of strict."""
    root, client, inv, ledger = _setup(tmp_path)
    inv.locations[0] = retire.SeqLocation(
        "RUNS_FINISHED", ".", inv.locations[0].seq_yml, "", "", ""
    )
    res = _run(client, root, inv, ledger)
    assert not res.ok and client.calls == [] and "no files were moved" in res.error
    assert os.path.isdir(os.path.join(root, "RUNS_FINISHED"))


def test_existing_destination_is_refused_before_deletes(tmp_path):
    """Mutation: deferring the dst check to move time."""
    root, client, inv, ledger = _setup(tmp_path)
    os.makedirs(_dst(root))
    res = _run(client, root, inv, ledger)
    assert not res.ok and client.calls == [] and "no files were moved" in res.error
    assert os.path.isdir(_src(root))


def test_cross_device_is_refused_before_deletes(tmp_path, monkeypatch):
    """Mutation: removing the device comparison."""
    root, client, inv, ledger = _setup(tmp_path)
    real = retire._st_dev
    monkeypatch.setattr(
        retire,
        "_st_dev",
        lambda p: real(p)
        + (1 if "RUNS_FINISHED" in p and "SUPERSEDED" not in p else 0),
    )
    res = _run(client, root, inv, ledger)
    assert not res.ok and client.calls == [] and "no files were moved" in res.error
    assert os.path.isdir(_src(root))


def test_two_locations_are_both_moved(tmp_path):
    """Mutation: moving locations[0] only."""
    root, client, inv, ledger = _setup(tmp_path, ("RUNS_SYNCED", "RUNS_FINISHED"))
    assert len(inv.locations) == 2
    res = _run(client, root, inv, ledger)
    assert res.ok, res.error
    for rt in ("RUNS_SYNCED", "RUNS_FINISHED"):
        assert os.path.isdir(_dst(root, rt)) and not os.path.exists(_src(root, rt))
    assert len(res.moved) == 2


def test_second_location_dest_clash_refuses_before_deletes(tmp_path):
    """Mutation: pre-checking only the first location."""
    root, client, inv, ledger = _setup(tmp_path, ("RUNS_FINISHED", "RUNS_SYNCED"))
    os.makedirs(_dst(root, inv.locations[1].run_tree))
    res = _run(client, root, inv, ledger)
    assert not res.ok and client.calls == [] and "no files were moved" in res.error


def test_retry_after_failure_moves_with_no_deletes(tmp_path):
    """Mutation: making retire refuse an inventory with no API rows."""
    root, client, inv, ledger = _setup(tmp_path)
    client.persist = {"P1"}
    assert not _run(client, root, inv, ledger).ok
    client.persist = set()
    client.rows = {t: set() for t in client.rows}
    client.seq_processes = {}
    client.analyses = {}
    inv2 = asyncio.run(retire.inventory(client, root, U, _noprogress))
    assert not any(inv2.in_api.values()) and not inv2.sequence_in_api
    client.calls.clear()
    res = _run(client, root, inv2, os.path.join(root, "STATES", "retry.jsonl"))
    assert res.ok, res.error
    assert client.calls == [] and os.path.isdir(_dst(root))


def test_unwritable_ledger_fails_before_any_delete(tmp_path):
    """Mutation: opening the ledger lazily on the first outcome."""
    root, client, inv, _ = _setup(tmp_path)
    blocker = tmp_path / "notadir"
    blocker.write_text("x")
    res = _run(client, root, inv, str(blocker / "sub" / "l.jsonl"))
    assert not res.ok and client.calls == []
    assert os.path.isdir(_src(root))


def test_ledger_dir_is_created(tmp_path):
    """Mutation: removing the makedirs."""
    root, client, inv, ledger = _setup(tmp_path)
    assert not os.path.exists(os.path.join(root, "STATES"))
    assert _run(client, root, inv, ledger).ok
    assert os.path.isfile(ledger)


def test_progress_raising_during_move_does_not_abort_moves(tmp_path):
    """Mutation: calling progress directly (unguarded) in the move phase."""
    root, client, inv, ledger = _setup(tmp_path, ("RUNS_SYNCED", "RUNS_FINISHED"))

    async def boom(phase, *_):
        if phase == "move":
            raise RuntimeError("ui state gone")

    res = _run(client, root, inv, ledger, boom)
    assert res.ok, res.error
    assert len(res.moved) == 2 and not os.path.exists(_src(root))


def test_failure_after_a_move_never_claims_nothing_moved(tmp_path, monkeypatch):
    """Mutation: appending "no files were moved" regardless of phase, or not
    listing the un-moved dirs."""
    root, client, inv, ledger = _setup(tmp_path, ("RUNS_SYNCED", "RUNS_FINISHED"))
    real = retire._append

    def flaky(path, rec):
        if rec["outcome"] == "moved":
            raise OSError("disk full")
        real(path, rec)

    monkeypatch.setattr(retire, "_append", flaky)
    res = _run(client, root, inv, ledger)
    assert not res.ok and len(res.moved) == 1
    assert "no files were moved" not in res.error
    unmoved = _src(root, "RUNS_SYNCED")  # sorted: FINISHED moved first
    assert os.path.isdir(unmoved) and unmoved in res.error
    assert "API rows are already deleted" in res.error
    assert any(
        x["outcome"] == "move_failed" and x["uuid"] == unmoved for x in _lines(ledger)
    )


def test_delete_failure_says_rows_may_be_deleted(tmp_path):
    """Mutation: dropping the delete-phase wording."""
    root, client, inv, ledger = _setup(tmp_path)
    client.fail[("delete", "A1")] = "500"
    res = _run(client, root, inv, ledger)
    assert "API rows may already be deleted" in res.error
    assert res.error.endswith("; no files were moved")


def test_progress_done_never_decreases(tmp_path):
    """Mutation: progress("move", i, total) with the bare location index, or
    readback reporting its own probe count."""
    root, client, inv, ledger = _setup(tmp_path, ("RUNS_SYNCED", "RUNS_FINISHED"))
    client.rows["ACTION"].discard("A2")  # absent: fewer read-back probes
    ticks = []

    async def progress(*a):
        ticks.append(a)

    res = _run(client, root, inv, ledger, progress)
    assert res.ok, res.error
    dones = [d for _, d, _ in ticks]
    assert dones == sorted(dones) and dones[-1] == ticks[-1][2]
    assert {p for p, _, _ in ticks} >= {"delete:ACTION", "readback", "move"}


def test_symlinked_source_is_refused_before_deletes(tmp_path):
    """Mutation: removing the islink check in _move_guard."""
    root, client, inv, ledger = _setup(tmp_path)
    link = os.path.join(root, "RUNS_FINISHED", "26.40", "1005", "linked")
    os.symlink(_src(root), link)
    inv.locations.append(
        retire.SeqLocation(
            "RUNS_FINISHED",
            "26.40/1005/linked",
            inv.locations[0].seq_yml,
            "",
            "",
            "",
        )
    )
    res = _run(client, root, inv, ledger)
    assert not res.ok and "symlink" in res.error and client.calls == []
    assert os.path.isdir(_src(root))


def test_absent_must404_row_is_probed_in_readback(tmp_path):
    """Mutation: skipping the read-back of rows whose delete read as absent."""
    root, client, inv, ledger = _setup(tmp_path)
    real = client.delete_command

    async def odd(*, entity_type, primary_id, delete_connected_processes):
        if primary_id == "P1":  # not a 404, but its text says so
            raise RuntimeError("API call failed: 500 - Could not find upstream")
        return await real(
            entity_type=entity_type,
            primary_id=primary_id,
            delete_connected_processes=delete_connected_processes,
        )

    setattr(client, "delete_command", odd)
    res = _run(client, root, inv, ledger)
    assert not res.ok and "P1" in res.error and "no files were moved" in res.error
    assert os.path.isdir(_src(root))


def test_raising_delete_task_is_logged(tmp_path, monkeypatch):
    """Mutation: dropping the logging of gather exception results."""
    root, client, inv, ledger = _setup(tmp_path)
    real = retire._append

    def bad(path, rec):
        if rec["uuid"] == "A1":
            raise ValueError("unserialisable")
        real(path, rec)

    warned = []

    class Spy:
        def warning(self, msg):
            warned.append(msg)

        def exception(self, msg):
            warned.append(msg)

    monkeypatch.setattr(retire, "_append", bad)
    monkeypatch.setattr(retire, "LOGGER", Spy())
    _run(client, root, inv, ledger)
    assert any("delete task for ACTION raised" in m for m in warned)
