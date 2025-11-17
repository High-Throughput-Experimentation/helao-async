from typing import Union
from pathlib import Path
import zipfile
import aiofiles
import anyio

from zipstream import AsyncZipStream, ZIP_DEFLATED
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


async def rm_tree_async(pth: Union[anyio.Path, str]):
    """
    Recursively removes a directory and all its contents asynchronously.

    Args:
        pth (str or Path): The path to the directory to be removed.

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


def rm_tree(pth):
    """
    Recursively removes a directory and all its contents.

    Args:
        pth (str or Path): The path to the directory to be removed.

    Raises:
        FileNotFoundError: If the directory does not exist.
        PermissionError: If the user does not have permission to delete a file or directory.
        OSError: If an error occurs while deleting a file or directory.
    """
    pth = Path(pth)
    for child in pth.glob("*"):
        if child.is_file():
            child.unlink()
        else:
            rm_tree(child)
    pth.rmdir()


async def zip_dir_async(target_dir: Union[Path, str], filename: Union[Path, str]):
    success = False
    try:
        zs = AsyncZipStream(compress_type=ZIP_DEFLATED, compress_level=9)
        if isinstance(target_dir, str):
            target_dir = Path(target_dir)
        if isinstance(filename, Path):
            filename = str(filename)
        for entry in target_dir.glob("*"):
            await zs.add_path(str(entry))
        async with aiofiles.open(filename, "wb") as f:
            async for line in zs:
                await f.write(line)
        success = True
        LOGGER.info(f"Zipped {target_dir} to {filename}")
    except Exception:
        LOGGER.error("Error while zipping folder, cannot remove.", exc_info=True)
    if success:
        await rm_tree_async(str(target_dir))


def zip_dir(target_dir: Union[Path, str], filename: Union[Path, str]):
    """
    Compresses the contents of a directory into a zip file.

    Args:
        dir (Union[Path, str]): The directory to compress. Can be a Path object or a string.
        filename (Union[Path, str]): The name of the output zip file. Can be a Path object or a string.

    Returns:
        None

    Raises:
        Exception: If an error occurs during the zipping process, an exception is caught and its traceback is printed.

    Notes:
        - Files with the ".lock" suffix are excluded from the zip file.
        - If the zipping process is successful, the original directory is removed using the `rm_tree` function.
    """

    # Convert to Path object
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
