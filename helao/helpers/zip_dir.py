from typing import Union
from pathlib import Path
import traceback
import zipfile


def rm_tree(pth):
    pth = Path(pth)
    for child in pth.glob('*'):
        if child.is_file():
            child.unlink()
        else:
            rm_tree(child)
    pth.rmdir()


def zip_dir(dir: Union[Path, str], filename: Union[Path, str]):
    """Zip the provided directory without navigating to that directory using `pathlib` module"""

    # Convert to Path object
    dir = Path(dir)
    success = False

    try:
        with zipfile.ZipFile(filename, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for entry in dir.rglob("*"):
                zip_file.write(entry, entry.relative_to(dir))
        success = True
    except Exception as e:
        tb = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
        print("Error while zipping folder, cannot remove.")
        print(tb)

    if success:
        rm_tree(dir)
