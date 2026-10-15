"""tray_get_next_full returns the first loaded vial after the given one."""

import asyncio
from types import SimpleNamespace

from helao.deploy.hte.drivers.data.archive_driver import Archive
from helao.helpers.sample_positions import VT15


def _archive():
    vt = VT15()
    vt.vials[2] = True
    vt.vials[5] = True
    archive = object.__new__(Archive)
    archive.positions = SimpleNamespace(trays_dict={1: {1: vt}})  # type: ignore
    return archive


def test_next_full_returns_first_loaded_vial_then_the_next():
    archive = _archive()
    first = asyncio.run(archive.tray_get_next_full())
    assert first == {"tray": 1, "slot": 1, "vial": 3}
    nxt = asyncio.run(archive.tray_get_next_full(1, 1, first["vial"]))
    assert nxt == {"tray": 1, "slot": 1, "vial": 6}
