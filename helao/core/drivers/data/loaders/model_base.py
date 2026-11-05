"""Shared HLO/data-file accessors for HELAO record wrappers.

The local (:mod:`helao.core.drivers.data.loaders.localfs`) and remote
(:mod:`helao.core.drivers.data.loaders.helao_loader`) loaders each define their
own ``HelaoModel`` hierarchy with different constructors, but the data-file
accessors on their ``HelaoDataModel`` are identical. Those accessors live here
as a mixin so both hierarchies share one copy; each ``HelaoDataModel`` subclass
supplies its own ``json`` property (the record's metadata dict) and ``hlo``
accessor (which differs by backend).
"""

from typing import Optional


class HloPayload(dict):
    """An HLO file's ``{"meta": ..., "data": ...}``, also unpackable as ``(meta, data)``.

    The remote loader reads the S3 ``.hlo.json`` (that dict); the local loader
    used to return a ``(meta, data)`` tuple. This is both, so callers written
    against either keep working: every dict operation behaves as for the plain
    dict, except iteration, which yields ``meta`` then ``data`` rather than the
    keys. A plain dict would unpack to the key strings without raising.
    """

    def __init__(self, meta: Optional[dict] = None, data: Optional[dict] = None):
        super().__init__(meta=meta or {}, data=data or {})

    def __iter__(self):
        return iter((self["meta"], self["data"]))

    def copy(self) -> "HloPayload":
        """Shallow copy that stays an ``HloPayload`` (``{**p}`` and ``p | x`` do not)."""
        return HloPayload(self["meta"], self["data"])


class HelaoDataModelMixin:
    """HLO/data-file accessors shared by local and remote ``HelaoDataModel``.

    Subclasses must provide a ``json`` property returning the record's metadata
    dict, and an ``hlo`` accessor returning the primary HLO payload.
    """

    @property
    def data_files(self) -> list:
        """Entries in ``files`` that are HLO or JSON data payloads."""
        meta = self.json
        file_list = meta.get("files", [])
        return [
            x
            for x in file_list
            if x["file_name"].endswith(".hlo")
            or x["file_name"].endswith(".jsonl")
            or x["file_name"].endswith(".json")
            or x["file_type"] in ["helao__json_file", "json__file"]
        ]

    def hlo_file_tup_type(self, contains: str = "") -> list:
        """Return ``[file_name, file_type, data_keys]`` for the primary ``.hlo`` file.

        Args:
            contains: Optional substring filter applied to ``file_type``.

        Returns:
            A three-element list, or three empty values if no match.
        """
        hlo_files = [
            x for x in self.data_files if x["file_name"].endswith((".hlo", ".jsonl"))
        ]
        if contains:
            hlo_files = [x for x in hlo_files if contains in x["file_type"]]
        if not hlo_files:
            return "", "", []
        first_hlo = hlo_files[0]
        retkeys = ["file_name", "file_type", "data_keys"]
        return [first_hlo.get(k, "") for k in retkeys]

    @property
    def hlo_file_tup(self) -> list:
        """``hlo_file_tup_type()`` with no ``contains`` filter."""
        return self.hlo_file_tup_type()

    @property
    def hlo_file(self) -> dict:
        """First entry from ``data_files`` (the primary HLO/JSON file)."""
        return self.data_files[0]
