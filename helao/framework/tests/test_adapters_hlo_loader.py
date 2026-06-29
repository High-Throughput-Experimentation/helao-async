"""Tests for the framework HLO loader adapter (read_hlo, hlo_to_parquet).

A ``.hlo`` file is a YAML header, a ``%%`` separator line, then one JSON object
per line of body data. These tests build a tiny but valid fixture and assert
round-trip fidelity through both readers.
"""

import json

import pandas as pd
import pyarrow.parquet as pq

from helao.framework.adapters.loaders.hlo_loader import read_hlo, hlo_to_parquet


HEADER = {
    "file_type": "helao__file",
    "epoch_ns": 1718741234567890123,
    "optional": {"wl": [400.0, 401.0, 402.0]},
}

# Body lines: a scalar column (t_s) and a list column (Ewe_V).
BODY_ROWS = [
    {"t_s": 0.0, "Ewe_V": [0.1, 0.2]},
    {"t_s": 1.0, "Ewe_V": [0.3, 0.4]},
    {"t_s": 2.0, "Ewe_V": [0.5, 0.6]},
]


def _write_hlo(tmp_path):
    """Write a minimal valid .hlo file and return its path."""
    from helao.framework.support.yml_tools import yml_dumps

    hlo_path = tmp_path / "fixture.hlo"
    lines = [yml_dumps(HEADER).rstrip("\n"), "%%"]
    for row in BODY_ROWS:
        lines.append(json.dumps(row))
    hlo_path.write_text("\n".join(lines) + "\n")
    return hlo_path


def test_read_hlo_parses_header_and_body(tmp_path):
    hlo_path = _write_hlo(tmp_path)

    meta, data = read_hlo(str(hlo_path))

    # Header round-trips faithfully.
    assert meta["file_type"] == "helao__file"
    assert meta["epoch_ns"] == 1718741234567890123
    assert list(meta["optional"]["wl"]) == [400.0, 401.0, 402.0]

    # Scalar column: one entry appended per body line.
    assert data["t_s"] == [0.0, 1.0, 2.0]

    # List column: lists are concatenated (extend, not append).
    assert data["Ewe_V"] == [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]


def test_read_hlo_keep_keys_precedence_over_omit(tmp_path):
    # Legacy filter is `k in keep_keys or k not in omit_keys`. keep_keys only
    # rescues a key from omit_keys; it does not by itself exclude others.
    hlo_path = _write_hlo(tmp_path)
    _, data = read_hlo(str(hlo_path), keep_keys=["Ewe_V"], omit_keys=["Ewe_V"])
    assert set(data.keys()) == {"t_s", "Ewe_V"}
    assert data["Ewe_V"] == [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]


def test_read_hlo_omit_keys(tmp_path):
    hlo_path = _write_hlo(tmp_path)
    _, data = read_hlo(str(hlo_path), omit_keys=["Ewe_V"])
    assert set(data.keys()) == {"t_s"}


def test_read_hlo_from_bytes(tmp_path):
    hlo_path = _write_hlo(tmp_path)
    raw = hlo_path.read_bytes()
    meta_b, data_b = read_hlo(raw)
    meta_p, data_p = read_hlo(str(hlo_path))
    assert meta_b == meta_p
    assert data_b == data_p


def test_read_hlo_skips_blank_and_unparseable_lines(tmp_path):
    # Regression (upstream 7013aaa6): a blank line or a non-JSON garbage line in
    # the body must be skipped rather than aborting the whole file.
    from helao.framework.support.yml_tools import yml_dumps

    hlo_path = tmp_path / "dirty.hlo"
    lines = [yml_dumps(HEADER).rstrip("\n"), "%%"]
    lines.append(json.dumps({"t_s": 0.0, "Ewe_V": [0.1, 0.2]}))
    lines.append("")  # blank line
    lines.append("this is not json {{{")  # unparseable garbage
    lines.append(json.dumps({"t_s": 1.0, "Ewe_V": [0.3, 0.4]}))
    hlo_path.write_text("\n".join(lines) + "\n")

    meta, data = read_hlo(str(hlo_path))

    # Header still parses, and only the two good rows are returned.
    assert meta["file_type"] == "helao__file"
    assert data["t_s"] == [0.0, 1.0]
    assert data["Ewe_V"] == [0.1, 0.2, 0.3, 0.4]


def test_hlo_to_parquet_roundtrip(tmp_path):
    # Use a scalar-only body so each line maps to exactly one DataFrame row,
    # matching the column-aligned schema hlo_to_parquet produces.
    hlo_path = tmp_path / "scalar.hlo"
    from helao.framework.support.yml_tools import yml_dumps

    rows = [
        {"t_s": 0.0, "Ewe_V": 0.10, "I_A": 1.0e-6},
        {"t_s": 1.0, "Ewe_V": 0.20, "I_A": 2.0e-6},
        {"t_s": 2.0, "Ewe_V": 0.30, "I_A": 3.0e-6},
    ]
    lines = [yml_dumps(HEADER).rstrip("\n"), "%%"]
    lines += [json.dumps(r) for r in rows]
    hlo_path.write_text("\n".join(lines) + "\n")

    parquet_path = tmp_path / "scalar.parquet"
    hlo_to_parquet(str(hlo_path), str(parquet_path))

    assert parquet_path.exists()

    # Round-trip values via pandas.
    df = pd.read_parquet(parquet_path)
    assert list(df.columns) == ["t_s", "Ewe_V", "I_A"]
    assert df["t_s"].tolist() == [0.0, 1.0, 2.0]
    assert df["Ewe_V"].tolist() == [0.10, 0.20, 0.30]
    assert df["I_A"].tolist() == [1.0e-6, 2.0e-6, 3.0e-6]

    # helao_metadata is embedded in the parquet schema and decodes to the
    # header's 'optional' section.
    meta = pq.read_metadata(str(parquet_path))
    helao_meta = json.loads(meta.metadata[b"helao_metadata"].decode("utf8"))
    assert helao_meta == {"wl": [400.0, 401.0, 402.0]}
