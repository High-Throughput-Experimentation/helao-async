"""SampleModelAPI._update binds values (apostrophes survive); SolidSampleAPI
rejects invalid legacy sample numbers."""

import asyncio
import sqlite3
from types import SimpleNamespace

from helao.helpers.sample_api import SampleModelAPI, SolidSampleAPI


def test_update_text_value_with_apostrophe():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE liquid (idx INTEGER, comment TEXT)")
    con.execute("INSERT INTO liquid VALUES (1, NULL)")
    api = SampleModelAPI.__new__(SampleModelAPI)
    api._cur = con.cursor()
    api._sample_type = "liquid"
    api.column_types = {"idx": "integer", "comment": "text"}
    api.column_notNULL = {"idx": True, "comment": False}

    api._update({"idx": 1, "comment": "it's '); DROP TABLE liquid;--"})

    assert con.execute("SELECT comment FROM liquid").fetchall() == [
        ("it's '); DROP TABLE liquid;--",)
    ]


def test_invalid_legacy_solid_sample_is_rejected():
    api = SolidSampleAPI.__new__(SolidSampleAPI)
    api.legacyAPI = SimpleNamespace(
        get_platemap_plateid=lambda plateid: [{"x": 0.0, "y": 0.0}]
    )
    api._sample_type = "solid"
    bad = SimpleNamespace(machine_name="legacy", plate_id=1, sample_no=5)
    assert asyncio.run(api.get_samples(samples=[bad])) == []


def _legacy_api(pmdata):
    api = SolidSampleAPI.__new__(SolidSampleAPI)
    api.legacyAPI = SimpleNamespace(get_platemap_plateid=lambda plateid: pmdata)
    api._sample_type = "solid"
    return api


def test_empty_platemap_accepts_with_warning(caplog):
    s = SimpleNamespace(machine_name="legacy", plate_id=1, sample_no=3)
    with caplog.at_level("WARNING"):
        out = asyncio.run(_legacy_api([]).get_samples(samples=[s]))
    assert [o.sample_no for o in out] == [3]
    assert "lookup failed" in caplog.text


def test_legacy_boundary_index():
    api = _legacy_api([{"x": 0.0, "y": 0.0}] * 2)
    ok = SimpleNamespace(machine_name="legacy", plate_id=1, sample_no=2)
    bad = SimpleNamespace(machine_name="legacy", plate_id=1, sample_no=3)
    assert len(asyncio.run(api.get_samples(samples=[ok]))) == 1
    assert asyncio.run(api.get_samples(samples=[bad])) == []


def test_legacy_sample_zero_is_the_plate_reference():
    # UVIS_measure_references loads sample_no 0 for the builtin black/white
    # targets; rejecting it left every reference process without a sample
    api = _legacy_api([{"x": 0.0, "y": 0.0}] * 2)
    ref = SimpleNamespace(machine_name="legacy", plate_id=1, sample_no=0)
    out = asyncio.run(api.get_samples(samples=[ref]))
    assert [o.global_label for o in out] == ["legacy__solid__1_0"]
