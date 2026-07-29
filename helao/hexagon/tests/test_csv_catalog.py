"""CsvTableCatalog behavior tests (TableCatalogPort).

The table below is fictional and belongs to no deployment: these tests pin the
port's contract, not any station's schema. A deployment that wires a catalog
keeps its own real-table parity tests in its own repo.

Three properties are load-bearing:

1. Construction is I/O-free and a missing file never raises, so a deployment
   library that wires a catalog at module scope stays importable on a host
   where the table is absent -- the whole point of the port, since a
   module-scope `pd.read_csv` of a station path crashed at import.
2. `lookup_one` reproduces the legacy
   `DF.loc[(DF[k1] == v1) & (DF[k2] == v2)]` + `assert len(match) == 1` +
   `match[col].values[0]` contract exactly, including the dtypes pandas
   inferred, so metadata reaching the wire is unchanged.
3. `lookup_first` reproduces the lenient variant of the same shape, where a
   call site took `.values[0]` with no cardinality check.
"""

import numpy as np
import pandas as pd
import pytest

from helao.hexagon.adapters.fakes import FakeTableCatalog
from helao.hexagon.adapters.native.csv_catalog import CsvTableCatalog
from helao.hexagon.ports.catalog import TableCatalogPort

# Fictional two-key reference table: (bank_id, slot_no) -> label + value.
TABLE = (
    "bank_id,slot_no,Contents label,Contents value\n"
    "bank_a,1,alpha,0.5\n"
    "bank_a,3,beta,13.0\n"
    "bank_b,3,gamma,7.0\n"
    "dupe,9,first,1.0\n"
    "dupe,9,second,2.0\n"
)


@pytest.fixture
def table_path(tmp_path):
    path = tmp_path / "reference_table.csv"
    path.write_text(TABLE)
    return path


def test_is_table_catalog_port(table_path):
    assert isinstance(CsvTableCatalog(table_path), TableCatalogPort)
    assert isinstance(FakeTableCatalog(), TableCatalogPort)


def test_construction_does_no_io_and_missing_file_never_raises(tmp_path):
    absent = tmp_path / "no_such_dir" / "reference_table.csv"
    catalog = CsvTableCatalog(absent)  # must not raise -- import-time safety

    assert catalog.lookup_one(bank_id="bank_a", slot_no=1) is None
    assert list(catalog.rows()) == []


def test_absolute_windows_path_is_safe_to_wire_on_linux():
    """A table path from another OS must not break a non-station host."""
    catalog = CsvTableCatalog("D:/instrument_tables/reference_table.csv")
    assert catalog.lookup_one(bank_id="bank_a", slot_no=3) is None


def test_lookup_one_returns_row_with_legacy_dtypes(table_path):
    frame = pd.read_csv(table_path)
    legacy = frame.loc[(frame["bank_id"] == "bank_a") & (frame["slot_no"] == 3)]

    row = CsvTableCatalog(table_path).lookup_one(bank_id="bank_a", slot_no=3)

    assert row is not None
    assert row["Contents label"] == legacy["Contents label"].values[0]
    assert row["Contents value"] == legacy["Contents value"].values[0]
    # dtype parity: a numeric column stays the numpy float pandas inferred
    assert isinstance(row["Contents value"], np.floating)
    assert isinstance(row["Contents label"], str)


def test_lookup_one_matches_on_every_key(table_path):
    catalog = CsvTableCatalog(table_path)

    row = catalog.lookup_one(bank_id="bank_b", slot_no=3)

    # same slot number, different bank -> a distinct row, not a collision
    assert row is not None
    assert row["Contents label"] == "gamma"


def test_no_match_returns_none(table_path):
    assert CsvTableCatalog(table_path).lookup_one(bank_id="nope", slot_no=1) is None


def test_ambiguous_match_returns_none(table_path):
    """Legacy asserted len(match) == 1, so 2 rows means 'unresolved'."""
    assert CsvTableCatalog(table_path).lookup_one(bank_id="dupe", slot_no=9) is None


def test_unknown_key_column_returns_none(table_path):
    catalog = CsvTableCatalog(table_path)
    assert catalog.lookup_one(not_a_column=1) is None
    assert catalog.lookup_first(not_a_column=1) is None


def test_lookup_first_resolves_duplicates_to_the_first_row(table_path):
    """For call sites that took .values[0] with no cardinality check."""
    catalog = CsvTableCatalog(table_path)

    row = catalog.lookup_first(bank_id="dupe", slot_no=9)

    assert row is not None
    assert row["Contents label"] == "first"
    # ...where lookup_one refuses to guess
    assert catalog.lookup_one(bank_id="dupe", slot_no=9) is None


def test_lookup_first_returns_none_on_no_match(table_path):
    catalog = CsvTableCatalog(table_path)
    assert catalog.lookup_first(bank_id="nope", slot_no=1) is None
    assert CsvTableCatalog(table_path.parent / "absent.csv").lookup_first(a=1) is None


def test_rows_returns_full_table(table_path):
    rows = CsvTableCatalog(table_path).rows()
    assert len(rows) == 5
    assert rows[0]["Contents label"] == "alpha"


def test_prime_reads_at_wiring_time_and_pins_that_snapshot(table_path):
    """Legacy read at import; a later external rewrite must not leak in."""
    catalog = CsvTableCatalog(table_path).prime()

    table_path.write_text(
        "bank_id,slot_no,Contents label,Contents value\n"
        "bank_a,1,REWRITTEN EXTERNALLY,9.9\n"
    )

    row = catalog.lookup_one(bank_id="bank_a", slot_no=1)
    assert row is not None and row["Contents label"] == "alpha"


def test_prime_on_absent_file_is_non_fatal(tmp_path):
    catalog = CsvTableCatalog(tmp_path / "absent.csv").prime()
    assert list(catalog.rows()) == []


def test_read_is_cached_until_reload(table_path):
    catalog = CsvTableCatalog(table_path)
    assert catalog.lookup_one(bank_id="bank_a", slot_no=1) is not None

    table_path.write_text(
        "bank_id,slot_no,Contents label,Contents value\nbank_a,1,EDITED,9.9\n"
    )
    cached = catalog.lookup_one(bank_id="bank_a", slot_no=1)
    assert cached is not None and cached["Contents label"] == "alpha"

    catalog.reload()
    fresh = catalog.lookup_one(bank_id="bank_a", slot_no=1)
    assert fresh is not None and fresh["Contents label"] == "EDITED"


def test_fake_catalog_mirrors_csv_semantics():
    fake = FakeTableCatalog(
        [
            {"bank_id": "bank_a", "slot_no": 1, "label": "alpha"},
            {"bank_id": "dupe", "slot_no": 9, "label": "first"},
            {"bank_id": "dupe", "slot_no": 9, "label": "second"},
        ]
    )

    hit = fake.lookup_one(bank_id="bank_a", slot_no=1)
    assert hit is not None and hit["label"] == "alpha"
    assert fake.lookup_one(bank_id="dupe", slot_no=9) is None  # ambiguous
    assert fake.lookup_one(bank_id="absent") is None
    assert fake.lookup_one(not_a_column=1) is None

    first = fake.lookup_first(bank_id="dupe", slot_no=9)
    assert first is not None and first["label"] == "first"
    assert fake.lookup_first(bank_id="absent") is None
    assert len(fake.rows()) == 3
    assert FakeTableCatalog().lookup_one(bank_id="x") is None
