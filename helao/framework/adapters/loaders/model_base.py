"""Shared HLO/data-file accessors for HELAO record wrappers.

The local and remote loaders each define their own ``HelaoModel`` hierarchy
with different constructors, but the data-file accessors on their
``HelaoDataModel`` are identical. Those accessors live here as a mixin so both
hierarchies share one copy; each ``HelaoDataModel`` subclass supplies its own
``json`` property (the record's metadata dict) and ``hlo`` accessor (which
differs by backend).
"""


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
            or x["file_name"].endswith(".json")
            or x["file_type"] in ["helao__json_file", "json__file"]
        ]

    @property
    def other_files(self) -> list:
        """Entries in ``files`` that are not classified as data files."""
        meta = self.json
        file_list = meta.get("files", [])
        return [x for x in file_list if x not in self.data_files]

    def hlo_file_tup_type(self, contains: str = "") -> list:
        """Return ``[file_name, file_type, data_keys]`` for the primary ``.hlo`` file.

        Args:
            contains: Optional substring filter applied to ``file_type``.

        Returns:
            A three-element list, or three empty values if no match.
        """
        hlo_files = [x for x in self.data_files if x["file_name"].endswith(".hlo")]
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
