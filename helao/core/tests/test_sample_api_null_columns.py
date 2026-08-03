"""SQL NULLs on the sqlite sample read path must validate, not raise.

``pd.read_sql_query`` renders a NULL as ``NaN`` -- not ``None`` -- for every
column that is NULL in *all* returned rows: pandas infers ``float64`` for an
all-null object column (``lib.maybe_convert_objects(try_float=True)``), which
is what pandas 2.x does on the stations. Pydantic v2 then rejects ``NaN`` for
``Optional[str]`` and ``Optional[date]``, so ``list_new_samples`` blew up with
"9 validation errors for union[...]" on an ordinary liquid sample whose
``prep_date``/``comment``/``electrolyte`` were simply never set.

The bug is data-dependent (a single non-null row in the batch keeps the column
``object``, and the NaNs never appear), so the frames here are built with the
explicit ``float64`` NaN columns pandas 2.x hands back, and one test does the
real sqlite round trip on whatever pandas is installed.

``_df_to_sample``/``_df_to_samples`` only need ``self._jsonkeys``, so the tests
drive them on an uninitialized instance rather than standing up a whole server.
"""

import datetime
import json
import sqlite3

import pandas as pd
import pytest

from helao.core.models.sample import LiquidSample
from helao.helpers.sample_api import SampleModelAPI

JSONKEYS = [
    "chemical",
    "partial_molarity",
    "supplier",
    "lot_number",
    "source",
    "status",
    "action_uuid",
]

# One real liquid-sample row as the station logged it, minus the NaN columns.
ROW = {
    "idx": 3097,
    "hlo_version": "262fe240",
    "global_label": "hte-adss-03__liquid__3097",
    "sample_type": "liquid",
    "sample_no": 3097,
    "sample_creation_timecode": 1774906617082774528,
    "sample_position": "tray",
    "machine_name": "hte-adss-03",
    "sample_hash": None,
    "last_update": 1774906651235724544,
    "inheritance": "receive_only",
    "status": json.dumps(["created"]),
    "action_uuid": json.dumps(["069caed2-c9d9-78c1-800d-39eb3eb67e09"]),
    "sample_creation_experiment_uuid": "069caeb4-a65d-784f-8000-021d8d6785de",
    "sample_creation_action_uuid": "069caed2-c9d9-78c1-800d-39eb3eb67e09",
    "server_name": "PAL",
    "chemical": json.dumps(["potassium phosphate monobasic", "sodium sulfate"]),
    "partial_molarity": json.dumps(["0.05 M", "0.25 M"]),
    "supplier": json.dumps(["Sigma Life Science", "Fisher Chemical"]),
    "lot_number": json.dumps(["SLCC0585", "#170859"]),
    "source": json.dumps(["hte-adss-03__assembly__cell1_we__1774906358707265024"]),
    "volume_ml": 0.2,
    "dilution_factor": 1.0,
}

# Columns whose queried rows were all NULL, hence float64 NaN out of pandas 2.
NAN_COLUMNS = ["prep_date", "comment", "electrolyte", "ph"]


def _api():
    """A ``SampleModelAPI`` with only what the df->sample conversion touches."""
    api = SampleModelAPI.__new__(SampleModelAPI)
    api._jsonkeys = list(JSONKEYS)
    return api


def _frame(rows, nan_columns=NAN_COLUMNS, jsonkeys_null=()):
    """Build the frame pandas 2.x returns: NaN float64 for all-null columns."""
    data: dict[str, object] = {key: [row[key] for row in rows] for key in rows[0]}
    for col in nan_columns:
        data[col] = pd.Series([float("nan")] * len(rows), dtype="float64")
    for col in jsonkeys_null:
        data[col] = pd.Series([float("nan")] * len(rows), dtype="float64")
    return pd.DataFrame(data)


def test_df_to_samples_accepts_all_null_text_columns():
    """The station's failing row validates, with NULLs read back as None."""
    samples = _api()._df_to_samples(_frame([ROW]))

    assert len(samples) == 1
    sample = samples[0]
    assert isinstance(sample, LiquidSample)
    assert sample.global_label == "hte-adss-03__liquid__3097"
    assert sample.prep_date is None
    assert sample.comment is None
    assert sample.electrolyte is None
    # NaN would validate fine as a float and then poison JSON serialization.
    assert sample.ph is None
    assert sample.volume_ml == 0.2
    assert sample.chemical == [
        "potassium phosphate monobasic",
        "sodium sulfate",
    ]


def test_df_to_sample_accepts_all_null_text_columns():
    """Single-row conversion (``get_samples``, insert read-back) too."""
    sample = _api()._df_to_sample(_frame([ROW]))
    assert isinstance(sample, LiquidSample)

    assert sample.prep_date is None
    assert sample.comment is None
    assert sample.electrolyte is None
    assert sample.ph is None


def test_null_json_columns_become_empty_lists():
    """A NULL json column decodes to ``[]``; ``json.loads(nan)`` would raise."""
    sample = _api()._df_to_sample(_frame([ROW], jsonkeys_null=("supplier", "source")))
    assert isinstance(sample, LiquidSample)

    assert sample.supplier == []
    assert sample.source == []
    assert sample.chemical == [
        "potassium phosphate monobasic",
        "sodium sulfate",
    ]


def test_populated_columns_survive_sanitizing():
    """Nulling NaNs must not touch rows that actually carry values."""
    row = dict(ROW)
    row["comment"] = "third rinse"
    row["electrolyte"] = "KOH"
    row["prep_date"] = "2026-07-30"
    row["ph"] = 6.9
    frame = _frame([row], nan_columns=[])

    sample = _api()._df_to_sample(frame)
    assert isinstance(sample, LiquidSample)

    assert sample.comment == "third rinse"
    assert sample.electrolyte == "KOH"
    assert sample.prep_date == datetime.date(2026, 7, 30)
    assert sample.ph == 6.9


def test_integrity_check_still_raises():
    """The idx/sample_no mismatch guard is untouched by the sanitizing."""
    row = dict(ROW)
    row["idx"] = 42

    with pytest.raises(ValueError):
        _api()._df_to_sample(_frame([row]))


def test_sqlite_roundtrip_with_all_null_columns():
    """End to end through sqlite, on whatever pandas this env has."""
    con = sqlite3.connect(":memory:")
    columns = list(ROW) + NAN_COLUMNS
    con.execute(f"CREATE TABLE liquid_sample({', '.join(columns)})")
    con.execute(
        f"INSERT INTO liquid_sample({', '.join(ROW)}) "
        f"VALUES({', '.join('?' * len(ROW))})",
        tuple(ROW.values()),
    )
    con.commit()

    retdf = pd.read_sql_query("SELECT * FROM liquid_sample;", con=con)
    samples = _api()._df_to_samples(retdf)

    assert len(samples) == 1
    sample = samples[0]
    assert isinstance(sample, LiquidSample)
    assert sample.prep_date is None
    assert sample.comment is None
    assert sample.ph is None
