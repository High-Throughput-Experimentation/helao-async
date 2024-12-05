# helao.core.helpers __init__.py
import shutil
from aiofiles.os import wrap

async_copy = wrap(shutil.copy)
