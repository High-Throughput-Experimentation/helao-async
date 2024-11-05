from typing import Union
from pathlib import Path
import traceback
import zipfile


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


def zip_dir(dir: Union[Path, str], filename: Union[Path, str]):
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
    dir = Path(dir)
    success = False

    try:
        with zipfile.ZipFile(filename, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for entry in dir.rglob("*"):
                if entry.suffix == ".lock":
                    continue
                zip_file.write(entry, entry.relative_to(dir))
        success = True
    except Exception as e:
        tb = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
        print("Error while zipping folder, cannot remove.")
        print(tb)

    if success:
        rm_tree(dir)
