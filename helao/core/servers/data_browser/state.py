"""Pure selection/plot/table logic for the data browser (no Bokeh imports)."""
from dataclasses import dataclass

from helao.core.servers.data_browser.readers import read_dataset

SUMMARY_COLS = [
    "source", "sequence", "experiment", "node", "technique", "sample",
    "file_name", "n_points", "x_min", "x_max", "y_min", "y_max",
]


@dataclass
class SelectedDataset:
    locator: str
    label: str
    source: str
    sequence: str
    experiment: str
    node: str
    technique: str
    sample: str
    file_name: str
    meta: dict
    data: dict  # {column: list}

    @property
    def columns(self):
        return list(self.data.keys())


def available_columns(selected):
    """Sorted union of all column names across selected datasets."""
    cols = set()
    for ds in selected:
        cols.update(ds.columns)
    return sorted(cols)


def build_trace(ds, xcol, ycol):
    """Return {'x': [...], 'y': [...]} or None if either column is missing."""
    if xcol in ds.data and ycol in ds.data:
        x = list(ds.data[xcol])
        y = list(ds.data[ycol])
        n = min(len(x), len(y))
        return {"x": x[:n], "y": y[:n]}
    return None


def downsample(trace, max_points):
    """Uniformly downsample a trace dict to at most max_points."""
    n = len(trace["x"])
    if max_points and n > max_points:
        step = (n // max_points) + 1
        return {"x": trace["x"][::step], "y": trace["y"][::step]}
    return trace


def summary_row(ds, xcol, ycol):
    """One trace-summary row for the summary table."""
    x = ds.data.get(xcol, [])
    y = ds.data.get(ycol, [])
    n = min(len(x), len(y))

    def rng(v):
        nums = [z for z in v[:n] if isinstance(z, (int, float)) and not isinstance(z, bool)]
        return (min(nums), max(nums)) if nums else (None, None)

    xr, yr = rng(x), rng(y)
    return {
        "source": ds.source, "sequence": ds.sequence, "experiment": ds.experiment,
        "node": ds.node, "technique": ds.technique, "sample": ds.sample,
        "file_name": ds.file_name, "n_points": n,
        "x_min": xr[0], "x_max": xr[1], "y_min": yr[0], "y_max": yr[1],
    }


def load_selected(index_df, positions):
    """Read the chosen index rows (by integer position) into SelectedDataset list.

    Unavailable rows and unreadable files are skipped (logging is the caller's job).
    Returns (datasets, skipped) where skipped is a list of (label, reason).
    """
    datasets, skipped = [], []
    for pos in positions:
        row = index_df.iloc[pos]
        label = f"{row['source']}:{row['sequence']}/{row['node']}/{row['file_name']}"
        if not row["available"] or not row["locator"]:
            skipped.append((label, "not available locally"))
            continue
        try:
            meta, data = read_dataset(row["locator"], row["file_type"] or None)
        except Exception as exc:  # corrupt/unreadable file
            skipped.append((label, f"read error: {exc}"))
            continue
        datasets.append(SelectedDataset(
            locator=row["locator"], label=label, source=row["source"],
            sequence=row["sequence"], experiment=row["experiment"], node=row["node"],
            technique=row["technique"], sample=row["sample"],
            file_name=row["file_name"], meta=meta, data=data,
        ))
    return datasets, skipped
