# helao/framework/tests/test_loaders_hlo.py
from pathlib import Path
import pytest
from helao.framework.adapters.loaders.hlo_loader import read_hlo, hlo_to_parquet


def _write_hlo(path: Path, n_rows: int = 3) -> Path:
    header = "action_uuid: test-uuid-001\nfiles: []\n"
    rows = [f'{{"t": {i}, "v": {i * 2}}}\n' for i in range(n_rows)]
    path.write_text(header + "%%\n" + "".join(rows), encoding="utf-8")
    return path


def test_read_hlo_returns_meta_and_data(tmp_path):
    hlo = _write_hlo(tmp_path / "test.hlo")
    meta, data = read_hlo(str(hlo))
    assert meta["action_uuid"] == "test-uuid-001"
    assert "t" in data and "v" in data
    assert len(data["t"]) == 3


def test_read_hlo_keep_keys_filters_columns(tmp_path):
    hlo = _write_hlo(tmp_path / "test.hlo")
    _, data = read_hlo(str(hlo), keep_keys=["t"])
    assert "t" in data
    assert "v" not in data


def test_read_hlo_omit_keys_filters_columns(tmp_path):
    hlo = _write_hlo(tmp_path / "test.hlo")
    _, data = read_hlo(str(hlo), omit_keys=["v"])
    assert "t" in data
    assert "v" not in data


def test_hlo_to_parquet_creates_file(tmp_path):
    hlo = _write_hlo(tmp_path / "test.hlo", n_rows=5)
    parquet = tmp_path / "out.parquet"
    hlo_to_parquet(str(hlo), str(parquet))
    assert parquet.exists()
    assert parquet.stat().st_size > 0


def test_hlo_to_parquet_readable_with_pyarrow(tmp_path):
    import pyarrow.parquet as pq

    hlo = _write_hlo(tmp_path / "test.hlo", n_rows=4)
    parquet = tmp_path / "out.parquet"
    hlo_to_parquet(str(hlo), str(parquet))
    table = pq.read_table(str(parquet))
    assert table.num_rows == 4
    assert "t" in table.column_names
