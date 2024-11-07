__all__ = ["HelaoDirs"]

from pydantic import BaseModel
from pathlib import Path
from typing import Optional

from helao.core.helaodict import HelaoDict


class HelaoDirs(BaseModel, HelaoDict):
    root: Optional[Path] = None
    save_root: Optional[Path] = None
    log_root: Optional[Path] = None
    states_root: Optional[Path] = None
    db_root: Optional[Path] = None
    user_exp: Optional[Path] = None
    user_seq: Optional[Path] = None
    ana_root: Optional[Path] = None
    process_root: Optional[Path] = None