"""Date-scoped indexers that emit a uniform candidate-dataset index.

Each source indexer walks the cheap ``YY.WW/MMDD`` directory layout, scoped to a
date range, and returns a pandas DataFrame with :data:`INDEX_COLUMNS`. Reading a
row's data is done separately via ``readers.read_dataset(row.locator, row.file_type)``.
"""
import posixpath
import zipfile
from pathlib import Path

import pandas as pd
import yaml

from helao.core.servers.data_browser.readers import make_zip_locator

INDEX_COLUMNS = [
    "source", "sequence", "experiment", "node", "technique", "sample",
    "run_type", "file_name", "file_type", "date", "available", "locator",
]

DATA_EXTS = (".hlo", ".json", ".parquet")


def _list_day_dirs(base):
    """Yield (date_str, day_path) for each YY.WW/MMDD under base, sorted."""
    base = Path(base)
    if not base.is_dir():
        return
    for ww in sorted(p.name for p in base.iterdir() if p.is_dir()):
        wwp = base / ww
        for mmdd in sorted(p.name for p in wwp.iterdir() if p.is_dir()):
            yield f"{ww}/{mmdd}", wwp / mmdd


def _in_range(date_str, start, end):
    """Lexicographic YY.WW/MMDD range test; None bounds are open."""
    if start and date_str < start:
        return False
    if end and date_str > end:
        return False
    return True


def _seq_name(dirname):
    """Extract the human-readable sequence name from a YY dir name."""
    parts = dirname.split("__")
    return parts[1] if len(parts) > 1 else dirname


def _first_sample(meta):
    """Return the first global_label found in an action/process yml dict."""
    for key in ("samples_out", "samples_in"):
        for s in meta.get(key) or []:
            lbl = (s or {}).get("global_label") if isinstance(s, dict) else None
            if lbl:
                return lbl
    return ""


def _safe_yaml(path):
    try:
        with open(path, "r") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _safe_yaml_bytes(content):
    try:
        return yaml.safe_load(content) or {}
    except Exception:
        return {}


def _row(**kw):
    """Build one index row dict with all INDEX_COLUMNS present."""
    return {c: kw.get(c, "") for c in INDEX_COLUMNS}
