"""Shared HLO/data-file accessors for HELAO record wrappers.

The local (:mod:`helao.core.drivers.data.loaders.localfs`) and remote
(:mod:`helao.core.drivers.data.loaders.helao_loader`) loaders each define their
own ``HelaoModel`` hierarchy with different constructors, but the data-file
accessors on their ``HelaoDataModel`` are identical. Those accessors live here
as a mixin so both hierarchies share one copy; each ``HelaoDataModel`` subclass
supplies its own ``json`` property (the record's metadata dict) and ``hlo``
accessor (which differs by backend).
"""

from io import BytesIO
from typing import Optional

from pydantic import PrivateAttr

from helao.core.models.file import FileInfo


class HelaoArtifact(FileInfo):
    """``FileInfo`` that can fetch its own bytes via the loader that produced it.

    A thin wrapper over one of a record's ``files`` entries that keeps a
    reference to the owning loader plus a backend-specific ``locator`` — an S3
    key for the remote loader, or a ``(yml_path, file_name)`` pair for the local
    loader. :meth:`get_bytes` delegates retrieval to the loader's
    ``read_artifact_bytes`` so the same class works for both backends and always
    returns a ``BytesIO``.
    """

    # Loader ref and locator kept off the pydantic schema (not serialized).
    _loader: Optional[object] = PrivateAttr(default=None)
    _locator: object = PrivateAttr(default=None)

    @classmethod
    def from_meta(
        cls, file_dict: dict, loader: object = None, locator: object = None
    ) -> "HelaoArtifact":
        """Build a ``HelaoArtifact`` from a serialized ``files`` entry.

        Args:
            file_dict: One entry from a record's ``files`` list.
            loader: Loader used later to retrieve the file bytes.
            locator: Backend-specific handle passed to ``loader.read_artifact_bytes``.

        Returns:
            A ``HelaoArtifact`` mirroring ``file_dict`` with loader/locator attached.
        """
        obj = cls.model_validate(file_dict)
        obj._loader = loader
        obj._locator = locator
        return obj

    @property
    def locator(self) -> object:
        """Backend-specific retrieval handle for ``loader.read_artifact_bytes``."""
        return self._locator

    def __getitem__(self, key: str):
        """Dict-style read access, for backward compatibility with ``files`` dicts."""
        return getattr(self, key)

    def get(self, key: str, default=None):
        """Dict-style ``.get``, for backward compatibility with ``files`` dicts."""
        return getattr(self, key, default)

    def get_bytes(self) -> BytesIO:
        """Fetch this file's body via the owning loader and return a ``BytesIO``.

        Raises:
            RuntimeError: If no loader reference is available.
        """
        if self._loader is None:
            raise RuntimeError("HelaoArtifact has no loader reference for retrieval.")
        return self._loader.read_artifact_bytes(self)


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
