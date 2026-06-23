"""FsSyncStorage: real filesystem implementation of SyncStorage."""
import json
import os
import shutil
import zipfile
from pathlib import Path

from ruamel.yaml import YAML

from helao.framework.ports.sync_storage import SyncStorage

_yaml = YAML(typ="rt")
_yaml.indent(mapping=2, sequence=4, offset=2)
_yaml.allow_duplicate_keys = True


def _represent_none(self, data):
    return self.represent_scalar("tag:yaml.org,2002:null", "null")


_yaml.representer.add_representer(type(None), _represent_none)


class FsSyncStorage:
    """Filesystem-backed SyncStorage. Cloud upload methods are no-op stubs."""

    # ── tree inspection ───────────────────────────────────────────────────

    def list_ymls(self, root: Path) -> list[Path]:
        return sorted(root.rglob("*.yml")) if root.exists() else []

    def list_files(self, dir_path: Path, pattern: str = "*") -> list[Path]:
        return sorted(dir_path.glob(pattern)) if dir_path.exists() else []

    # ── YAML I/O ──────────────────────────────────────────────────────────

    def read_yml(self, path: Path) -> dict:
        with open(path, encoding="utf-8") as f:
            return dict(_yaml.load(f) or {})

    def write_yml(self, path: Path, data: dict) -> None:
        """Atomic write via temp file + os.replace (byte-identical YAML conventions)."""
        from io import StringIO
        path.parent.mkdir(parents=True, exist_ok=True)
        buf = StringIO()
        _yaml.dump(dict(data), buf)
        tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
        tmp.write_text(buf.getvalue(), encoding="utf-8")
        os.replace(tmp, path)

    # ── progress sidecar I/O ──────────────────────────────────────────────

    def read_prg(self, path: Path) -> dict:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def write_prg(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")

    def remove_prg(self, path: Path) -> None:
        path.unlink(missing_ok=True)

    # ── filesystem mutations ──────────────────────────────────────────────

    def move_tree(self, src: Path, dst: Path) -> Path:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return dst

    def zip_dir(self, path: Path) -> Path:
        """Zip path into path.with_suffix('.zip'), skip .lock files, remove source."""
        zip_path = path.with_suffix(".zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for entry in sorted(path.rglob("*")):
                if entry.suffix == ".lock":
                    continue
                if entry.is_file():
                    zf.write(entry, entry.relative_to(path.parent))
        shutil.rmtree(path)
        return zip_path

    def try_remove_empty(self, path: Path) -> bool:
        try:
            os.rmdir(path)
            return True
        except OSError:
            return False

    # ── cloud upload stubs ────────────────────────────────────────────────

    def upload_file(self, local_path: Path, s3_key: str) -> bool:
        return True

    def upload_bytes(
        self, data: bytes, s3_key: str, content_type: str = "application/json"
    ) -> bool:
        return True

    def key_exists(self, s3_key: str) -> bool:
        return False
