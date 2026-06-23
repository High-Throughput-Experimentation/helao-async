"""In-memory SyncStorage for tests. Records all mutating calls."""
from pathlib import Path


class FakeSyncStorage:
    """In-memory SyncStorage recording every operation for assertions."""

    def __init__(self) -> None:
        self._ymls: dict[Path, dict] = {}
        self._prgs: dict[Path, dict] = {}
        self.moved: list[tuple[Path, Path]] = []
        self.zipped: list[Path] = []
        self.uploaded_files: list[tuple[Path, str]] = []
        self.uploaded_bytes: list[tuple[bytes, str]] = []

    # ── helpers for test setup ────────────────────────────────────────────

    def add_yml(self, path: Path, data: dict | None = None) -> None:
        self._ymls[path] = data or {}

    # ── SyncStorage protocol ──────────────────────────────────────────────

    def list_ymls(self, root: Path) -> list[Path]:
        root_str = str(root)
        return sorted(p for p in self._ymls if str(p).startswith(root_str))

    def list_files(self, dir_path: Path, pattern: str = "*") -> list[Path]:
        return []

    def read_yml(self, path: Path) -> dict:
        return dict(self._ymls.get(path, {}))

    def write_yml(self, path: Path, data: dict) -> None:
        self._ymls[path] = dict(data)

    def read_prg(self, path: Path) -> dict:
        return dict(self._prgs.get(path, {}))

    def write_prg(self, path: Path, data: dict) -> None:
        self._prgs[path] = dict(data)

    def remove_prg(self, path: Path) -> None:
        self._prgs.pop(path, None)

    def move_tree(self, src: Path, dst: Path) -> Path:
        for p in list(self._ymls):
            rel = None
            try:
                rel = p.relative_to(src)
            except ValueError:
                pass
            if rel is not None:
                new_p = dst / rel
                self._ymls[new_p] = self._ymls.pop(p)
        self.moved.append((src, dst))
        return dst

    def zip_dir(self, path: Path) -> Path:
        self.zipped.append(path)
        return path.with_suffix(".zip")

    def try_remove_empty(self, path: Path) -> bool:
        return True

    def upload_file(self, local_path: Path, s3_key: str) -> bool:
        self.uploaded_files.append((local_path, s3_key))
        return True

    def upload_bytes(
        self, data: bytes, s3_key: str, content_type: str = "application/json"
    ) -> bool:
        self.uploaded_bytes.append((data, s3_key))
        return True

    def key_exists(self, s3_key: str) -> bool:
        return False
