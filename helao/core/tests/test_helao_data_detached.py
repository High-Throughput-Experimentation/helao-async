"""HelaoData reads a record copied out of its run tree.

A record copied into a shared data repository has no ``RUNS``/``RUNS_*``/
``DIAG``/``PROCESSES`` folder in its path. ``FileMapper`` anchors on that
folder, so ``HelaoData.data`` used to raise inside, log "Error reading data."
and return ``None`` while ``read_hlo`` on the same file worked.
"""

from pathlib import Path

from helao.helpers.helao_data import HelaoData

HLO = "column_headings: [t_s, I_A]\n%%\n" '{"t_s": [1.0, 2.0], "I_A": [0.5, 0.25]}\n'


def _act(base: Path) -> Path:
    d = base / "seqdir" / "expdir" / "1__0__PSTAT__run_CA"
    d.mkdir(parents=True)
    (d / "CA-1.1.0.0__0.hlo").write_text(HLO, encoding="utf-8")
    yml = d / "261006.122552210917-act.yml"
    yml.write_text("file_type: action\naction_name: run_CA\n", encoding="utf-8")
    return yml


def test_detached_record_data_is_readable(tmp_path: Path):
    yml = _act(tmp_path / "ECDataRepository" / "helao" / "CA")
    result = HelaoData(str(yml)).data
    assert result is not None
    meta, data = result
    assert meta["column_headings"] == ["t_s", "I_A"]
    assert data["I_A"] == [0.5, 0.25]


def test_record_in_a_run_tree_still_reads(tmp_path: Path):
    yml = _act(tmp_path / "RUNS" / "2026" / "1006")
    result = HelaoData(str(yml)).data
    assert result is not None
    _, data = result
    assert data["t_s"] == [1.0, 2.0]
