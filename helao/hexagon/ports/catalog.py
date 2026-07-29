"""TableCatalogPort: read-only keyed lookup over a tabular reference table
that a deployment's experiment/sequence library consults at plan time.

Motivation (spec §563, native-split phase): deployment libraries that resolve
per-run metadata from an operator-maintained table -- what a given hardware
position currently holds, say -- have historically done a module-scope
`pd.read_csv("<absolute station path>")`. That makes the library un-importable
anywhere the station path is absent, which breaks the library-import sweep,
the collision check, and every offline preflight on a non-station host.
Promoting the table to a port moves the read behind an injected seam that
resolves lazily and degrades to "no match" instead of an import-time crash.

Semantics reproduced from the legacy call shape:

    row = DF.loc[(DF["k1"] == v1) & (DF["k2"] == v2)]
    assert len(row) == 1
    value = row["col"].values[0]

`lookup_one` therefore returns a row ONLY on an unambiguous single match; no
match, several matches, an unknown key column, or an unreadable/missing source
all return None so the caller applies its own documented fallback. Cell values
are handed back exactly as the underlying table yields them (per-column
`.values[0]`), so metadata written onto the wire keeps its legacy dtype.

Boundary note (spec §4.1, locked): ports/ may only import stdlib +
`helao.hexagon.domain`/`ports` + the declared `helao_driver` exception. Row
mappings are typed with plain generics rather than a pandas type -- pandas is
an adapter-layer third party, per the `PlateInfoPort` precedent in
`auxiliary.py`.
"""

from typing import Any, Mapping, Optional, Protocol, Sequence, runtime_checkable

__all__ = ["TableCatalogPort"]


@runtime_checkable
class TableCatalogPort(Protocol):
    """Read-only keyed access to a tabular reference table."""

    def rows(self) -> Sequence[Mapping[str, Any]]:
        """Return every row as a column-keyed mapping.

        Returns an empty sequence when the source is missing or unreadable --
        an absent table is a runtime condition callers fall back from, not an
        import-time failure.
        """
        ...

    def lookup_one(self, **keys: Any) -> Optional[Mapping[str, Any]]:
        """Return the single row where every ``column == value`` pair holds.

        Returns None unless exactly one row matches, and also when a named key
        is not a column of the table or the source cannot be read.
        """
        ...

    def lookup_first(self, **keys: Any) -> Optional[Mapping[str, Any]]:
        """Return the first row where every ``column == value`` pair holds.

        The lenient sibling of `lookup_one`, for legacy call sites that took
        `.values[0]` off the match with no cardinality check and so silently
        accepted a duplicated key. Prefer `lookup_one` in new code: a duplicate
        row in an operator-maintained table is a mistake worth surfacing, not
        resolving arbitrarily.
        """
        ...
