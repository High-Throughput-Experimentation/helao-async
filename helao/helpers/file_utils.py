"""Small file I/O utilities.

Consolidates the former file_in_use, zip_dir, and zstd_io modules.
"""

__all__ = [
    "file_in_use",
    "staging_path",
    "rm_tree",
    "rm_tree_async",
    "zip_dir",
    "unzpickle",
    "zpickle",
]

import _pickle as cPickle
import os
import zipfile
from pathlib import Path
from typing import Union
from uuid import uuid1

import anyio
import pyzstd

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


def staging_path(output_file: Union[Path, str]) -> str:
    """Return a sibling temp path for atomically staging ``output_file``.

    The name is a fixed 13 characters (``.<8 hex>.tmp``) and deliberately does
    *not* echo the target's own name. The previous
    ``.{basename}.{uuid1().hex}.tmp`` convention added 38 characters to a path
    that on a station is already close to Windows' 260-character ``MAX_PATH``:
    an action whose final ``-act.yml`` fitted at 232 characters had its staging
    write fail at 270 with ``FileNotFoundError: [Errno 2]``, so atomic writing
    turned a writable path into an unwritable one. A staging name shorter than
    the file it stages cannot do that.

    Both the leading dot and the ``.tmp`` suffix are load-bearing: they are what
    keeps a transiently-present staging file out of ``HelaoYml.misc_files``'s
    upload glob, which ships anything in a record directory that is not
    ``.yml``/``.hlo``/``.lock``/``.tmp`` and not a dotfile.

    Args:
        output_file: Final destination path the caller will ``os.replace`` onto.

    Returns:
        A path in the same directory as ``output_file``, safe to write and then
        rename over it.
    """
    return str(Path(output_file).parent / f".{uuid1().hex[:8]}.tmp")


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
    print(f"wrote to {os.path.abspath(fpath)}")
    return True
