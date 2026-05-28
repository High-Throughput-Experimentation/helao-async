"""Small file I/O utilities.

Consolidates the former file_in_use, zip_dir, and zstd_io modules.
"""

__all__ = [
    "file_in_use",
    "rm_tree",
    "rm_tree_async",
    "zip_dir",
    "unzpickle",
    "zpickle",
]

import os
import zipfile
from pathlib import Path
from typing import Union

import _pickle as cPickle
import anyio
import pyzstd

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


def file_in_use(file_path) -> bool:
    """Return whether ``file_path`` is currently held open by another process.

    Probes the file by attempting a no-op rename onto itself; on Windows
    this raises :class:`PermissionError` while another process holds the
    handle.

    Args:
        file_path: Path-like pointing at the file to probe.

    Returns:
        ``True`` if the file exists and is locked, ``False`` otherwise
        (including when the file does not exist).
    """
    path = Path(file_path)

    if not path.exists():
        return False

    try:
        path.rename(path)
        return False
    except PermissionError:
        return True


async def rm_tree_async(pth: Union[anyio.Path, str]) -> None:
    """Recursively delete a directory and its contents using :mod:`anyio`.

    Args:
        pth: Directory to remove; strings and :class:`pathlib.Path`
            values are coerced to :class:`anyio.Path`.
    """
    if isinstance(pth, str):
        pth = anyio.Path(pth)
    elif isinstance(pth, Path):
        pth = anyio.Path(str(pth))

    async for child in pth.glob("*"):
        if await child.is_file():
            await child.unlink()
        else:
            await rm_tree_async(child)
    await pth.rmdir()


def rm_tree(pth) -> None:
    """Recursively delete a directory and its contents.

    Args:
        pth: Path-like pointing at the directory to remove.
    """
    pth = Path(pth)
    for child in pth.glob("*"):
        if child.is_file():
            child.unlink()
        else:
            rm_tree(child)
    pth.rmdir()


def zip_dir(target_dir: Union[Path, str], filename: Union[Path, str]) -> None:
    """Zip ``target_dir`` into ``filename`` and delete the source on success.

    Files with the ``.lock`` suffix are skipped. If zipping raises, the
    source directory is left in place.

    Args:
        target_dir: Directory whose contents should be archived.
        filename: Destination zip file path.
    """
    target_dir = Path(target_dir)
    success = False

    try:
        with zipfile.ZipFile(filename, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for entry in target_dir.rglob("*"):
                if entry.suffix == ".lock":
                    continue
                if entry.is_file():
                    zip_file.write(entry, entry.relative_to(target_dir))
        success = True
        LOGGER.info(f"Zipped {target_dir} to {filename}")
    except Exception:
        LOGGER.error("Error while zipping folder, cannot remove.", exc_info=True)

    if success:
        rm_tree(target_dir)


def unzpickle(fpath):
    """Load a zstandard-compressed pickle from disk.

    Args:
        fpath: Path to a file written by :func:`zpickle`.

    Returns:
        The deserialised Python object.
    """
    data = pyzstd.ZstdFile(fpath, "rb")
    data = cPickle.load(data)
    return data


def zpickle(fpath, data) -> bool:
    """Pickle ``data`` to ``fpath`` with zstandard compression.

    Args:
        fpath: Destination file path.
        data: Object to serialise.

    Returns:
        ``True`` once the write completes.
    """
    with pyzstd.ZstdFile(fpath, "wb") as f:
        cPickle.dump(data, f)
    print(f"wrote to {os.path.abspath(f)}")
    return True
