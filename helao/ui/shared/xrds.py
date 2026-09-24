# helao/ui/shared/xrds.py
"""XRD frames across one plate, for the `/xrds` page.

Unlike R_UVVIS and XAFS, an ``xrds_frame`` process names its plate and sample
in ``process_params`` (``plate_id``, ``sample_no``, ``global_label``), so the
composition page's plate search finds them directly.

Each frame carries two integrated patterns -- as acquired and background
subtracted -- as separate files with the same series, ``twotheta_deg`` and
``intensity_au`` (10600 points). One record per pattern, keyed by process and
file type, so the page's file-type dropdown picks between them and both can
sit in the spectrum cache at once.
"""

from __future__ import annotations

from dataclasses import dataclass

from helao.ui.shared import spectra
from helao.ui.shared.composition import api

#: The process name of one XRD frame.
PROCESS_NAME = "xrds_frame"

#: Dropdown label -> file type of each integrated pattern.
FILE_TYPES = {
    "original": "bruker_gadds_xy_original__helao_file",
    "background subtracted": "bruker_gadds_xy_bkgsub__helao_file",
}

#: The plottable series holding two-theta and intensity.
X_KEY = "twotheta_deg"
Y_KEY = "intensity_au"


@dataclass(frozen=True)
class XrdsRecord:
    """One integrated pattern of one XRD frame."""

    plate_id: int
    sample_no: int
    global_label: str
    run_use: str
    sequence_uuid: str
    sequence_timestamp: str
    file_type: str
    process_uuid: str
    action_uuid: str
    file_name: str

    @property
    def spectrum_key(self) -> str:
        """Process and file type: a frame holds two patterns."""
        return f"{self.process_uuid}:{self.file_type}"


def records_from_processes(items, sequences=None) -> list:
    """One record per pattern file on each ``xrds_frame`` in *items*.

    Args:
        items: PROCESS search items.
        sequences: ``sequence_uuid -> SEQUENCE item``, for timestamps.
    """
    wanted = set(FILE_TYPES.values())
    out = []
    for item in items or []:
        if item.get("process_name") != PROCESS_NAME:
            continue
        params = item.get("process_params") or {}
        try:
            plate_id, sample_no = int(params["plate_id"]), int(params["sample_no"])
        except (KeyError, TypeError, ValueError):
            continue
        sequence_uuid = str(item.get("sequence_uuid") or "")
        stamp = ((sequences or {}).get(sequence_uuid) or {}).get("sequence_timestamp")
        for f in item.get("files") or []:
            if f.get("file_type") not in wanted:
                continue
            out.append(
                XrdsRecord(
                    plate_id=plate_id,
                    sample_no=sample_no,
                    global_label=str(params.get("global_label") or ""),
                    run_use=str(item.get("run_use") or ""),
                    sequence_uuid=sequence_uuid,
                    sequence_timestamp=str(stamp or ""),
                    file_type=str(f["file_type"]),
                    process_uuid=str(item.get("process_uuid") or ""),
                    action_uuid=str(f.get("action_uuid") or ""),
                    file_name=str(f.get("file_name") or ""),
                )
            )
    return out


async def records_for_plate(client, plate_id: int) -> list:
    """Every XRD pattern record on *plate_id*."""
    items = [
        i
        for i in await api.search_processes(client, plate_id)
        if i.get("process_name") == PROCESS_NAME
    ]
    uuids = sorted({str(i.get("sequence_uuid") or "") for i in items})
    sequences = await api.fetch_sequences(client, uuids)
    return records_from_processes(items, sequences)


async def load_spectra(client, records, file_type: str, progress=None) -> int:
    """Fetch every uncached pattern of *records*, all of *file_type*."""
    return await spectra.load_spectra(
        client,
        records,
        file_type=file_type,
        x_key=X_KEY,
        y_key=Y_KEY,
        progress=progress,
    )
