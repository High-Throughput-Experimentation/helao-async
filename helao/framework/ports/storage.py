"""Storage port: persist and retrieve JSON-serializable documents by relative path."""
from typing import Any, Mapping, Protocol, runtime_checkable


class StorageKeyError(KeyError):
    """Raised when reading a relpath that was never written."""


@runtime_checkable
class Storage(Protocol):
    """Persists JSON documents under repo-relative paths (e.g. RUNS_* layout)."""

    def write_json(self, relpath: str, payload: Mapping[str, Any]) -> str:
        """Write payload as JSON at relpath; return the relpath written."""
        ...

    def read_json(self, relpath: str) -> Mapping[str, Any]:
        """Read and return the JSON document at relpath.

        Raises StorageKeyError if relpath was never written.
        """
        ...
