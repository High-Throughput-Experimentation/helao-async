"""Unloading writes back the db's copy of a sample, not the position's stale copy.

The archive JSON holds a snapshot of each loaded sample; the db holds the
current one (volume, status, ... updated by later actions). _finish_unload
refreshes from the db before appending "unloaded" and writing back, so the
stale snapshot never overwrites the db row.
"""

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from helao.core.models.sample import LiquidSample, SampleStatus
from helao.deploy.hte.drivers.data.archive_driver import Archive
from helao.helpers.sample_positions import VT15, Custom, CustomTypes


class _DB:
    def __init__(self, current):
        self.current = current
        self.written = []

    async def get_samples(self, samples):  # one sample in play
        return [deepcopy(self.current)]

    async def update_samples(self, samples):
        self.written.extend(deepcopy(samples))
        self.current = deepcopy(samples[-1]) if samples else self.current


def _liquid(volume_ml, comment):
    s = LiquidSample(sample_no=7, machine_name="host", volume_ml=volume_ml)
    s.global_label = s.get_global_label()
    s.comment = comment
    return s


def _archive(where):
    stale = _liquid(5.0, "archive snapshot")
    db = _DB(current=_liquid(2.5, "db row"))
    archive = object.__new__(Archive)
    archive.unified_db = db  # type: ignore
    archive.archivejson = None
    archive.write_config = lambda: None  # type: ignore
    customs, trays = {}, {}
    if where == "tray":
        vt = VT15()
        vt.samples[0] = stale
        vt.vials[0] = True
        trays = {1: {1: vt}}
    else:
        customs = {
            "cell1_we": Custom(
                custom_name="cell1_we", custom_type=CustomTypes.cell, sample=stale
            )
        }
    archive.positions = SimpleNamespace(customs_dict=customs, trays_dict=trays)  # type: ignore
    return archive, db


@pytest.mark.parametrize("where", ["tray", "custom"])
def test_unload_writes_back_the_db_copy(where):
    archive, db = _archive(where)
    if where == "tray":
        _, samples_in, _, _ = asyncio.run(archive.tray_unload(tray=1, slot=1))
    else:
        _, samples_in, _, _ = asyncio.run(archive.custom_unload(custom="cell1_we"))
    assert [(s.comment, s.volume_ml) for s in samples_in] == [("db row", 2.5)]
    assert SampleStatus.unloaded in samples_in[0].status
    assert db.written and all(s.comment == "db row" for s in db.written)
