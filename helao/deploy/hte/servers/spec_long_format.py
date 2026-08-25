"""Reframing long-format spectra for the hte deployment's OceanDirect panels.

Shared by both UI stacks: ``servers/visualizer/oceandirect_vis.py`` (Bokeh) and
``servers/reflex/oceandirect_vis.py`` (Reflex). It lives beside those packages
rather than inside either one so neither UI depends on the other — the same
rule the data browser and operator follow. Add behaviour here, not to one
panel.

**Why this module exists at all.** The SM303 server streams a spectrum *wide*:
one ``ch_NNNN`` column per detector channel, one row per acquisition, so the
latest spectrum is the last row across those columns (that is what
``reflex/_spectra.py`` does). The OceanDirect server streams the same
information *long*: five columns — ``epoch_s``, ``spec_idx``, ``dev_ts_ns``,
``wl``, ``i`` — where a whole spectrum occupies ``n_pixels`` consecutive rows
and ``spec_idx`` is the only thing identifying which rows belong together.
Reframing therefore means grouping rows by ``spec_idx``, not slicing a row.

Three properties of the stream shape the code below:

* **``spec_idx`` restarts at 0 on every action.** The highest ``spec_idx`` in a
  window is therefore *not* necessarily the newest spectrum: right after an
  action boundary the old action's frame 42 outranks the new action's frame 0.
  The last position where ``spec_idx`` decreases is the boundary, exactly as
  ``_action.split_on_restart`` treats a restarting ``t_s``.
* **Only the oldest spectrum in a window can be partial.** Packets are appended
  whole and the ring buffer drops rows from the front, so a truncated frame
  appears at the head, never the tail. A partial frame is dropped rather than
  plotted — half a spectrum plotted against half a wavelength axis looks like a
  real measurement.
* **The wavelength axis is in the stream.** Unlike the SM303 panels, nothing
  here needs an HTTP round trip to ``/get_wl`` to know its x axis.
"""

__all__ = [
    "FRAME_COLUMN",
    "WAVELENGTH_COLUMN",
    "INTENSITY_COLUMN",
    "EPOCH_COLUMN",
    "LONG_COLUMNS",
    "has_long_format",
    "current_action_offset",
    "frame_runs",
    "latest_spectra",
]

import numpy as np

#: Per-action spectrum counter; the framing key that survives the readers'
#: column flattening.
FRAME_COLUMN = "spec_idx"

#: Wavelength column, nm.
WAVELENGTH_COLUMN = "wl"

#: Intensity column, counts.
INTENSITY_COLUMN = "i"

#: Host acquisition time. Repeated across a spectrum's rows, so one value per
#: frame is all a caller wants. Optional: a caller asking only for traces need
#: not have it, so its absence is not an error.
EPOCH_COLUMN = "epoch_s"

#: The three columns a panel needs. ``epoch_s`` and ``dev_ts_ns`` ride along in
#: the stream but neither is plotted, so neither is required here.
LONG_COLUMNS = (FRAME_COLUMN, WAVELENGTH_COLUMN, INTENSITY_COLUMN)


def has_long_format(snapshot) -> bool:
    """Whether ``snapshot`` carries the three columns a spectrum needs.

    Args:
        snapshot: Mapping of column name to a sequence of values.

    Returns:
        ``True`` when every column in :data:`LONG_COLUMNS` is present.
    """
    if not isinstance(snapshot, dict):
        return False
    return all(name in snapshot for name in LONG_COLUMNS)


def _as_array(values) -> np.ndarray:
    """Coerce a column to a float array, tolerating scalars and ``None``."""
    if values is None:
        return np.empty(0, dtype=float)
    arr = np.asarray(values, dtype=float)
    if arr.ndim == 0:
        return arr.reshape(1)
    return arr.ravel()


def current_action_offset(frames: np.ndarray) -> int:
    """Index of the first row belonging to the newest action.

    ``spec_idx`` restarts at 0 per action, so the last position where it
    decreases begins the current action. Without this, the frame with the
    largest ``spec_idx`` — which is the *previous* action's last spectrum for
    as long as both actions sit in the window — would be drawn as the latest.

    Args:
        frames: The ``spec_idx`` column.

    Returns:
        Row offset of the current action's first row; ``0`` when the window
        holds only one action.
    """
    if frames.size < 2:
        return 0
    starts = np.flatnonzero(np.diff(frames) < 0) + 1
    return int(starts[-1]) if starts.size else 0


def frame_runs(frames: np.ndarray) -> list:
    """Contiguous runs of equal ``spec_idx``, in stream order.

    Args:
        frames: The ``spec_idx`` column for one action.

    Returns:
        list: ``[(frame_index, start, stop)]`` with ``stop`` exclusive.
    """
    if frames.size == 0:
        return []
    edges = np.flatnonzero(np.diff(frames) != 0) + 1
    bounds = np.concatenate(([0], edges, [frames.size])).astype(int)
    return [
        (int(frames[bounds[k]]), int(bounds[k]), int(bounds[k + 1]))
        for k in range(bounds.size - 1)
    ]


def latest_spectra(snapshot, max_spectra: int = 2) -> list:
    """Reframe a long-format window into whole spectra, newest first.

    Args:
        snapshot: Mapping with at least the :data:`LONG_COLUMNS` columns, each
            a sequence of equal length.
        max_spectra: Most spectra to return. Values below 1 are treated as 1 —
            it comes from config, and a typo should not blank the panel.

    Returns:
        list: ``[{"frame": int, "epoch_s": float | None, "wl": np.ndarray,
        "i": np.ndarray}]``, newest first, at most ``max_spectra`` long. The
        ``wl``/``i`` arrays all have the same length, so a caller may share one
        x axis across every entry. ``epoch_s`` is ``None`` when the snapshot
        does not carry that column. Empty when the window holds no complete
        spectrum.
    """
    limit = max(1, int(max_spectra))
    if not has_long_format(snapshot):
        return []

    frames = _as_array(snapshot[FRAME_COLUMN])
    wl = _as_array(snapshot[WAVELENGTH_COLUMN])
    intensity = _as_array(snapshot[INTENSITY_COLUMN])
    epochs = _as_array(snapshot.get(EPOCH_COLUMN))

    # The columns must stay positionally aligned; a mid-write packet or a
    # column that arrived late can leave them ragged, so trim rather than
    # index past the end of the shortest.
    length = min(frames.size, wl.size, intensity.size)
    if length == 0:
        return []
    frames, wl, intensity = frames[:length], wl[:length], intensity[:length]
    # Epoch is optional, so it is padded rather than allowed to shorten the
    # others: a caller wanting traces should not lose them to a missing label.
    if epochs.size < length:
        epochs = np.concatenate(
            (epochs, np.full(length - epochs.size, np.nan, dtype=float))
        )
    else:
        epochs = epochs[:length]

    # `normalize`/`normalize_data_package` pad a column with nan for any packet
    # that did not carry it. Such a row belongs to no spectrum, and leaving it
    # in would both break the run detection (nan compares false in either
    # direction) and inject a nan pixel into a trace. Epoch is deliberately
    # excluded from the mask -- a missing label must not drop the pixel.
    finite = np.isfinite(frames) & np.isfinite(wl) & np.isfinite(intensity)
    if not finite.any():
        return []
    frames, wl, intensity = frames[finite], wl[finite], intensity[finite]
    epochs = epochs[finite]

    offset = current_action_offset(frames)
    frames = frames[offset:]
    wl = wl[offset:]
    intensity = intensity[offset:]
    epochs = epochs[offset:]

    runs = frame_runs(frames)
    if not runs:
        return []

    # The newest run is always whole (packets append atomically and the buffer
    # drops from the front), so its length is the pixel count. Any run that
    # disagrees is the truncated head of the window.
    _, last_start, last_stop = runs[-1]
    expected = last_stop - last_start
    whole = [run for run in runs if run[2] - run[1] == expected]
    if not whole:
        return []

    selected = whole[-limit:]
    out = []
    for frame, start, stop in reversed(selected):
        epoch = float(epochs[start]) if np.isfinite(epochs[start]) else None
        out.append(
            {
                "frame": frame,
                EPOCH_COLUMN: epoch,
                WAVELENGTH_COLUMN: wl[start:stop],
                INTENSITY_COLUMN: intensity[start:stop],
            }
        )
    return out
