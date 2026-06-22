"""In-memory Storage backed by a dict, for tests."""
import copy
from typing import Any, Mapping

from helao.framework.ports.storage import Storage, StorageKeyError


class FakeStorage(Storage):
    """Stores deep-copied JSON documents keyed by relpath."""

    def __init__(self) -> None:
        self._docs: dict[str, dict[str, Any]] = {}

    def write_json(self, relpath: str, payload: Mapping[str, Any]) -> str:
        self._docs[relpath] = copy.deepcopy(dict(payload))
        return relpath

    def read_json(self, relpath: str) -> Mapping[str, Any]:
        try:
            return copy.deepcopy(self._docs[relpath])
        except KeyError as exc:
            raise StorageKeyError(relpath) from exc
