from typing import Union
from pathlib import Path
import zipfile

from helao.helpers import logging

if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER


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
    for child in pth.glob('*'):
        if child.is_file():
            child.unlink()
        else:
            rm_tree(child)
    pth.rmdir()


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
