"""Unit tests for helao/ui/shared/retire.py line scans, locate, in_flight."""

import asyncio
import json
import os
import time
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


def test_analysis_dirs_read_only_yml_and_skip_unreadable(tmp_path):
    """Mutation: reading every file (drop the .yml filter), or letting OSError
    from an unreadable yml propagate."""
    root = str(tmp_path)
    make_run_tree(root, "RUNS", REL, sequence_uuid=U, experiments=EXPS)
    base = tmp_path / "ANALYSES" / "2026" / "1005"
    only_json = base / "120000__j"
    only_json.mkdir(parents=True)
    (only_json / "out.json").write_text('{"process_uuid": "P2"}')
    bad = base / "130000__bad"
    bad.mkdir()
    (bad / "x.yml").mkdir()  # a directory named x.yml: not a file, skipped
    unreadable = base / "140000__perm"
    unreadable.mkdir()
    f = unreadable / "y.yml"
    f.write_text("process_uuid: P2\n")
    f.chmod(0)
    try:
        inv = asyncio.run(retire.inventory(_full_client(), root, U, _noprogress))
    finally:
        f.chmod(0o644)
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
    waits out the slow reads and their progress ticks)."""
    root = str(tmp_path)
    make_run_tree(root, "RUNS", REL, sequence_uuid=U, experiments=EXPS)
    client = _full_client()
    client.fail[("read", "A1")] = "500"
    orig = client.read_experiment

    async def slow(*, experiment_uuid):
        await asyncio.sleep(0.3)
        return await orig(experiment_uuid=experiment_uuid)

    client.read_experiment = slow
    ticks = []

    async def progress(*a):
        ticks.append(a)

    async def run():
        t0 = time.monotonic()
        with pytest.raises(RuntimeError):
            await retire.inventory(client, root, U, progress)
        assert time.monotonic() - t0 < 0.2  # did not wait out the slow reads
        n = len(ticks)
        await asyncio.sleep(0.6)
        return n

    assert asyncio.run(run()) == len(ticks)


def test_processes_by_sequence_non_list_raises(tmp_path):
    """Mutation: dropping the isinstance(list) check."""
    client = _full_client()

    async def bad(*, sequence_uuid):
        return {"detail": "x"}

    client.read_processes_by_sequence = bad  # type: ignore
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
