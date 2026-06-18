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
    defaults = {c: "" for c in INDEX_COLUMNS}
    defaults["available"] = False
    defaults.update(kw)
    return defaults


def _meta_fields(meta):
    """Return (technique, sample, run_type) from an action yml dict."""
    return (
        meta.get("technique_name") or meta.get("action_name", ""),
        _first_sample(meta),
        meta.get("run_type", ""),
    )


def _rows_to_index_df(rows):
    df = pd.DataFrame(rows, columns=INDEX_COLUMNS)
    if len(df):
        # Keep Python bool identity (pandas would upcast to numpy.bool_).
        df["available"] = pd.Series(
            pd.array([bool(v) for v in df["available"]], dtype=object),
            dtype=object,
            index=df.index,
        )
    return df


class SourceIndex:
    """Base class for a date-scoped candidate-dataset indexer."""

    def list_dates(self):
        raise NotImplementedError

    def index(self, date_start=None, date_end=None):
        raise NotImplementedError


class RunsSourceIndex(SourceIndex):
    """Index RUNS_FINISHED (unzipped trees) or RUNS_SYNCED (sequence zips)."""

    def __init__(self, root, state):
        # state is "FINISHED" or "SYNCED"
        self.root = Path(root)
        self.state = state
        self.source = f"RUNS_{state}"
        self.base = self.root / self.source

    def list_dates(self):
        return [d for d, _ in _list_day_dirs(self.base)]

    def index(self, date_start=None, date_end=None):
        rows = []
        for date_str, day in _list_day_dirs(self.base):
            if not _in_range(date_str, date_start, date_end):
                continue
            if self.state == "SYNCED":
                rows.extend(self._index_zips(date_str, day))
            else:
                rows.extend(self._index_tree(date_str, day))
        return _rows_to_index_df(rows)

    def _index_tree(self, date_str, day):
        rows = []
        for seq_dir in sorted(p for p in day.iterdir() if p.is_dir()):
            seq_name = _seq_name(seq_dir.name)
            for act_yml in sorted(seq_dir.glob("*/*/*-act.yml")):
                act_dir = act_yml.parent
                exp_name = act_dir.parent.name
                meta = _safe_yaml(act_yml)
                technique, sample, run_type = _meta_fields(meta)
                for f in sorted(act_dir.iterdir()):
                    if f.is_file() and f.suffix.lower() in DATA_EXTS:
                        rows.append(_row(
                            source=self.source, sequence=seq_name,
                            experiment=exp_name, node=act_dir.name,
                            technique=technique, sample=sample, run_type=run_type,
                            file_name=f.name, file_type=f.suffix.lower().lstrip("."),
                            date=date_str, available=True, locator=str(f),
                        ))
        return rows

    def _index_zips(self, date_str, day):
        rows = []
        for zip_path in sorted(day.glob("*.zip")):
            seq_name = _seq_name(zip_path.stem)
            try:
                zf = zipfile.ZipFile(zip_path)
            except zipfile.BadZipFile:
                continue
            with zf:
                names = zf.namelist()
                act_meta = {}
                for n in names:
                    if n.endswith("-act.yml"):
                        act_meta[posixpath.dirname(n)] = _safe_yaml_bytes(zf.read(n))
                for n in names:
                    ext = posixpath.splitext(n)[1].lower()
                    if ext not in DATA_EXTS:
                        continue
                    actdir = posixpath.dirname(n)
                    meta = act_meta.get(actdir, {})
                    technique, sample, run_type = _meta_fields(meta)
                    rows.append(_row(
                        source=self.source, sequence=seq_name,
                        experiment=posixpath.basename(posixpath.dirname(actdir)),
                        node=posixpath.basename(actdir),
                        technique=technique, sample=sample, run_type=run_type,
                        file_name=posixpath.basename(n), file_type=ext.lstrip("."),
                        date=date_str, available=True,
                        locator=make_zip_locator(str(zip_path), n),
                    ))
        return rows


def _resolve_run_file(root, date_str, seq_dirname, exp_dirname, file_name):
    """Locate a data file by basename under RUNS_FINISHED tree or RUNS_SYNCED zip.

    Returns (locator, available).
    """
    root = Path(root)
    exp_path = root / "RUNS_FINISHED" / date_str / seq_dirname / exp_dirname
    if exp_path.is_dir():
        # direct action-dir children first (the normal layout)
        for act_dir in sorted(p for p in exp_path.iterdir() if p.is_dir()):
            cand = act_dir / file_name
            if cand.is_file():
                return str(cand), True
        # fallback: any depth within THIS experiment, exact basename match
        for cand in exp_path.rglob("*"):
            if cand.is_file() and cand.name == file_name:
                return str(cand), True
    zip_path = root / "RUNS_SYNCED" / date_str / f"{seq_dirname}.zip"
    if zip_path.is_file():
        try:
            with zipfile.ZipFile(zip_path) as zf:
                for n in zf.namelist():
                    if posixpath.basename(n) == file_name:
                        return make_zip_locator(str(zip_path), n), True
        except zipfile.BadZipFile:
            pass
    return "", False


class DerivedSourceIndex(SourceIndex):
    """Index PROCESSES (-prc.yml referencing run files) or ANALYSES (local outputs)."""

    def __init__(self, root, source):
        # source is "PROCESSES" or "ANALYSES"
        self.root = Path(root)
        self.source = source
        if source not in ("PROCESSES", "ANALYSES"):
            raise ValueError(f"unsupported source: {source!r}")
        self.base = self.root / source

    def list_dates(self):
        return [d for d, _ in _list_day_dirs(self.base)]

    def index(self, date_start=None, date_end=None):
        rows = []
        for date_str, day in _list_day_dirs(self.base):
            if not _in_range(date_str, date_start, date_end):
                continue
            if self.source == "PROCESSES":
                rows.extend(self._index_processes(date_str, day))
            else:
                rows.extend(self._index_analyses(date_str, day))
        return _rows_to_index_df(rows)

    def _index_processes(self, date_str, day):
        rows = []
        for prc_yml in sorted(day.glob("*/*/*-prc.yml")):
            exp_dir = prc_yml.parent
            seq_dir = exp_dir.parent
            meta = _safe_yaml(prc_yml)
            technique, sample, run_type = _meta_fields(meta)
            for fi in meta.get("files") or []:
                fn = (fi or {}).get("file_name", "")
                if not fn or posixpath.splitext(fn)[1].lower() not in DATA_EXTS:
                    continue
                locator, available = _resolve_run_file(
                    self.root, date_str, seq_dir.name, exp_dir.name, fn)
                rows.append(_row(
                    source="PROCESSES", sequence=_seq_name(seq_dir.name),
                    experiment=exp_dir.name, node=prc_yml.stem,
                    technique=technique, sample=sample, run_type=run_type,
                    file_name=fn, file_type=posixpath.splitext(fn)[1].lower().lstrip("."),
                    date=date_str, available=available, locator=locator,
                ))
        return rows

    def _index_analyses(self, date_str, day):
        rows = []
        for ana_dir in sorted(p for p in day.iterdir() if p.is_dir()):
            ymls = sorted(ana_dir.glob("*.yml"))
            # first yml is the AnalysisModel; missing or extra ymls fall through to local-json indexing
            meta = _safe_yaml(ymls[0]) if ymls else {}
            ana_name = meta.get("analysis_name", _seq_name(ana_dir.name))
            sample = meta.get("global_sample_label") or ""
            local_jsons = {p.name: p for p in ana_dir.glob("*.json")}
            outputs = meta.get("outputs") or []
            if outputs:
                for out in outputs:
                    key = ((out or {}).get("analysis_output_path") or {}).get("key", "")
                    fn = posixpath.basename(key) if key else ""
                    name = (out or {}).get("output_name") or fn
                    local = local_jsons.get(fn)
                    rows.append(_row(
                        source="ANALYSES", sequence=ana_name, experiment="",
                        node=name, technique=(out or {}).get("output_type", ""),
                        sample=sample, run_type="", file_name=fn or name,
                        file_type="json", date=date_str,
                        available=local is not None,
                        locator=str(local) if local is not None else "",
                    ))
            else:
                for fn, p in local_jsons.items():
                    rows.append(_row(
                        source="ANALYSES", sequence=ana_name, experiment="",
                        node=fn, technique="", sample=sample, run_type="",
                        file_name=fn, file_type="json", date=date_str,
                        available=True, locator=str(p),
                    ))
        return rows


SOURCES = ["RUNS_FINISHED", "RUNS_SYNCED", "PROCESSES", "ANALYSES"]
GROUPS = {"RUNS": ["RUNS_FINISHED", "RUNS_SYNCED"],
          "DERIVED": ["PROCESSES", "ANALYSES"]}


def build_source_index(root, source):
    """Return the SourceIndex for a source name."""
    if source == "RUNS_FINISHED":
        return RunsSourceIndex(root, "FINISHED")
    if source == "RUNS_SYNCED":
        return RunsSourceIndex(root, "SYNCED")
    if source in ("PROCESSES", "ANALYSES"):
        return DerivedSourceIndex(root, source)
    raise ValueError(f"unknown source: {source!r}")


def get_index(root, source, date_start=None, date_end=None):
    """Build and return the candidate-dataset index DataFrame for a source."""
    return build_source_index(root, source).index(date_start, date_end)
