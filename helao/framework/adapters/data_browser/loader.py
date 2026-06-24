"""Read selected index rows into domain SelectedDataset objects (I/O adapter)."""
from helao.framework.adapters.data_browser.readers import read_dataset
from helao.framework.domain.data_browser import SelectedDataset


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
