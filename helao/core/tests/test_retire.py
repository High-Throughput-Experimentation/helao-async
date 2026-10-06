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
    # in_api alone (no sequence row, but a process row) must still be api_only,
    # while a local tree makes it not api_only
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
    (d / "out.json").write_text('{"process_uuid": "P2"}')
    other = tmp_path / "ANALYSES" / "2026" / "1005" / "130000__y"
    other.mkdir()
    (other / "out.json").write_text('{"process_uuid": "unrelated"}')
    inv = asyncio.run(retire.inventory(client, root, U, _noprogress))
    assert inv.analysis_dirs == [str(d)]
