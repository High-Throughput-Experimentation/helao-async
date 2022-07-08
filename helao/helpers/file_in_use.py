__all__ = ["file_in_use"]

from pathlib import Path


def file_in_use(file_path):
    path = Path(file_path)

    if not path.exists():
        # raise FileNotFoundError
        return False

    try:
        path.rename(path)
        return False
    except PermissionError:
        return True
