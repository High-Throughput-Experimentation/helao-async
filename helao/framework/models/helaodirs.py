"""Pydantic model holding the canonical on-disk directories used by HELAO servers."""

__all__ = ["HelaoDirs"]

from pydantic import BaseModel
from pathlib import Path
from typing import Optional

from helao.framework.models.helao_dict import HelaoDict


class HelaoDirs(BaseModel, HelaoDict):
    """Resolved on-disk locations rooted at a server's configured `root`.

    Attributes:
        root (Optional[Path]): Top-level root directory.
        save_root (Optional[Path]): Root for run/save output trees.
        log_root (Optional[Path]): Root for server log files.
        states_root (Optional[Path]): Root for pickled state files.
        db_root (Optional[Path]): Root for local database files.
        user_exp (Optional[Path]): User experiment library directory.
        user_seq (Optional[Path]): User sequence library directory.
        ana_root (Optional[Path]): Root for analysis outputs.
        process_root (Optional[Path]): Root for process outputs.
    """

    root: Optional[Path] = None
    save_root: Optional[Path] = None
    log_root: Optional[Path] = None
    states_root: Optional[Path] = None
    db_root: Optional[Path] = None
    user_exp: Optional[Path] = None
    user_seq: Optional[Path] = None
    ana_root: Optional[Path] = None
    process_root: Optional[Path] = None
