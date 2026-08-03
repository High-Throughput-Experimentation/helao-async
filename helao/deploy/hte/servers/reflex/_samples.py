"""Sample-table rendering for the hte deployment's sample panel.

``sample_vis`` is not a chart. It asks the SAMPLE server for the newest
samples of each type and renders four tables, which is why its logic is table
projection rather than plotting.
"""

__all__ = ["SAMPLE_TYPES", "SAMPLE_COLUMNS", "sample_rows", "tables_for"]

from datetime import datetime

#: Sample types the server reports, and the order the panel stacks them.
SAMPLE_TYPES = ("solid", "liquid", "gas", "assembly")

#: Fields shown per sample, matching the Bokeh tables.
SAMPLE_COLUMNS = (
    "global_label",
    "sample_creation_timecode",
    "comment",
    "volume_ml",
    "ph",
    "electrolyte",
)

#: The creation timecode arrives in nanoseconds.
NS_PER_SECOND = 1e9


def _timecode(value) -> str:
    """Render a nanosecond creation timecode as a readable timestamp.

    A value that will not convert is shown as-is rather than raising: the
    panel exists to show what the server said, and one odd record must not
    take the table down.
    """
    if value in (None, ""):
        return ""
    try:
        return datetime.fromtimestamp(float(value) / NS_PER_SECOND).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    except (TypeError, ValueError, OSError, OverflowError):
        return str(value)


def sample_rows(samples) -> list:
    """Project samples onto the displayed columns as table rows.

    Every cell is a string: Reflex serialises state to JSON, and ``rx.foreach``
    needs a concrete element type. A missing field renders blank rather than
    dropping the sample, so a sample is never invisible because one field is
    absent.
    """
    rows = []
    for sample in samples or []:
        row = []
        for column in SAMPLE_COLUMNS:
            value = sample.get(column)
            if column == "sample_creation_timecode":
                row.append(_timecode(value))
            else:
                row.append("" if value is None else str(value))
        rows.append(row)
    return rows


def tables_for(response) -> dict:
    """Rows per sample type from one ``list_new_samples`` response.

    A type the response omits is an empty table rather than a missing key, so
    the panel always renders all four.
    """
    payload = response if isinstance(response, dict) else {}
    tables = {}
    for sample_type in SAMPLE_TYPES:
        samples = payload.get(sample_type)
        tables[sample_type] = sample_rows(samples if isinstance(samples, list) else [])
    return tables
