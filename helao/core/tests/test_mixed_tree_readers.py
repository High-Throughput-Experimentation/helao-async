"""Every reader reports the same records and data on legacy, new and mixed trees.

JSON storage spec §5: HelaoData, LocalLoader, the data browser, run_state,
retire, process_locator and list_pending* must agree with a legacy-only twin.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from harness.tests.synthtree import build_tree, zip_sequence
from helao.core.drivers.data.loaders.localfs import LocalLoader
from helao.core.drivers.data.process_locator import find_process_ymls
from helao.helpers.helao_data import HelaoData
from helao.helpers.meta_io import meta_glob
from helao.helpers.run_state import rebuild_from_tree
from helao.hexagon.adapters.native import sync_driver as sd
from helao.ui.shared import retire
from helao.ui.shared.data_browser.sources import RunsSourceIndex

DATA = {"t_s": [0.0, 0.1], "series_0": [0.5, 0.6]}


def _observe(root: Path, info: dict) -> dict:
    """What every reader reports about one tree, in format-independent terms."""
    hd = HelaoData(str(meta_glob(info["seq_dir"], "seq")[0]))
    (exp,) = hd.exp
    (act,) = exp.act
    hd_meta, hd_data = act.read_data_file(act.data_files[0])
    ll = LocalLoader(data_path=str(info["seq_dir"]))
    ll_meta, ll_data = ll.get_act(0).hlo  # type: ignore[attr-defined]
    journal = rebuild_from_tree(root / "RUNS_FINISHED", root / "STATES", "SYNC")
    (loc,) = retire.locate(str(root), info["seq_uuid"])
    _, scanned = retire._scan_local([loc])
    drv = sd.SyncDriver.__new__(sd.SyncDriver)
    drv.helaodirs = SimpleNamespace(save_root=root / "RUNS_ACTIVE")  # type: ignore[assignment]
    return {
        "helao_data": (
            hd.uuid,
            exp.uuid,
            act.uuid,
            len(act.data_files),
            hd_meta,
            dict(hd_data),
        ),
        "local_loader": (
            len(ll.sequences),
            len(ll.experiments),
            len(ll.actions),
            len(ll.processes),
            ll_meta,
            dict(ll_data),
        ),
        "browser_rows": len(RunsSourceIndex(root, "FINISHED").index()),
        "journal": sorted(r["kind"] for r in journal.working_set().values()),
        "retire_files": scanned,
        "processes": len(find_process_ymls(info["exp_dir"])),
        "pending": (
            len(drv.list_pending()),
            len(drv.list_pending_exps()),
            len(drv.list_pending_acts()),
        ),
    }


@pytest.mark.parametrize("fmt", ["new", "mixed"])
def test_dir_tree_readers_match_the_legacy_twin(tmp_path, fmt):
    legacy = _observe(
        tmp_path / "a", build_tree(tmp_path / "a", fmt="legacy", extended=True)
    )
    other = _observe(tmp_path / "b", build_tree(tmp_path / "b", fmt=fmt, extended=True))
    # not vacuous: the legacy twin itself sees one of everything
    header = {
        "hlo_version": "2025.07.07",
        "action_name": "WsSim",
        "column_headings": ["t_s", "series_0"],
        "epoch_ns": 1752671661000000000,
    }
    assert legacy["helao_data"][3:] == (1, header, DATA)
    assert legacy["local_loader"][:4] == (1, 1, 1, 1)
    assert legacy["journal"] == ["action", "experiment", "sequence"]
    assert legacy["pending"] == (1, 1, 1)
    assert other == legacy


@pytest.mark.parametrize("fmt", ["legacy", "new", "mixed"])
def test_a_zipped_sequence_reads_in_every_format(tmp_path, fmt):
    zp = zip_sequence(tmp_path, build_tree(tmp_path, fmt=fmt, extended=True))
    hd = HelaoData(str(zp))
    (act,) = hd.exp[0].act
    meta, data = act.read_hlo(act.data_files[0])
    assert dict(data) == DATA and meta["action_name"] == "WsSim"
    ll = LocalLoader(data_path=str(zp))
    assert (
        len(ll.sequences),
        len(ll.experiments),
        len(ll.actions),
        len(ll.processes),
    ) == (1, 1, 1, 1)
    meta2, data2 = ll.get_act(0).hlo  # type: ignore[attr-defined]
    assert (meta2, dict(data2)) == (meta, dict(data))
    assert len(RunsSourceIndex(tmp_path, "SYNCED").index()) == 1
