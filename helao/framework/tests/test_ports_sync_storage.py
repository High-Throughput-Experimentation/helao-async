from pathlib import Path

from helao.framework.ports.sync_storage import SyncStorage


class DummySyncStorage:
    """Minimal structural implementation of every SyncStorage method."""

    def exists(self, path: Path) -> bool:
        return False

    def list_pending(
        self, finished_root: Path, kind: str, omit_manual: bool
    ) -> list[Path]:
        return []

    def list_children(self, parent_dir: Path) -> list[Path]:
        return []

    def hlo_files(self, dir_: Path) -> list[Path]:
        return []

    def misc_files(self, dir_: Path, node_type: str) -> list[Path]:
        return []

    def lock_files(self, dir_: Path) -> list[Path]:
        return []

    def file_size(self, path: Path) -> int:
        return 0

    def read_yml(self, path: Path) -> dict:
        return {}

    def write_yml(self, path: Path, data: dict) -> None:
        return None

    def write_process_meta(self, path: Path, data: dict) -> None:
        return None

    def read_prg(self, path: Path) -> dict:
        return {}

    def write_prg(self, path: Path, data: dict) -> None:
        return None

    def remove_prg(self, path: Path) -> None:
        return None

    def move_to_synced(self, path: Path) -> Path:
        return path

    def revert_to_finished(self, path: Path) -> Path:
        return path

    def move_tree(self, src: Path, dst: Path) -> Path:
        return dst

    def zip_dir(self, path: Path) -> Path:
        return path

    def cleanup_empty(self, path: Path) -> bool:
        return False

    def remove(self, path: Path) -> None:
        return None


class PartialSyncStorage:
    """Missing ``remove`` -- must NOT satisfy the protocol."""

    def exists(self, path: Path) -> bool:
        return False

    def list_pending(self, finished_root, kind, omit_manual):
        return []

    def list_children(self, parent_dir):
        return []

    def hlo_files(self, dir_):
        return []

    def misc_files(self, dir_, node_type):
        return []

    def lock_files(self, dir_):
        return []

    def file_size(self, path):
        return 0

    def read_yml(self, path):
        return {}

    def write_yml(self, path, data):
        return None

    def read_prg(self, path):
        return {}

    def write_prg(self, path, data):
        return None

    def remove_prg(self, path):
        return None

    def move_to_synced(self, path):
        return path

    def revert_to_finished(self, path):
        return path

    def move_tree(self, src, dst):
        return dst

    def zip_dir(self, path):
        return path

    def cleanup_empty(self, path):
        return False

    # remove(...) intentionally omitted


def test_dummy_satisfies_protocol():
    storage: SyncStorage = DummySyncStorage()
    assert isinstance(storage, SyncStorage)


def test_partial_implementation_is_not_an_instance():
    assert not isinstance(PartialSyncStorage(), SyncStorage)
