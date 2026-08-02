"""Spectrum handling for the hte deployment's spectrometer panel.

``spec_vis`` is the one panel whose packets are not a time series. Each packet
carries a whole spectrum: ``ch_0``, ``ch_1``, ... one column per detector
channel, one row per acquisition. The latest spectrum is therefore the last
row *across* those columns, not the last N rows of one.

The wavelength axis is not in the stream at all -- the Bokeh panel fetches it
from the action server once at startup -- so the panel plots against the
channel index until it arrives.
"""

__all__ = [
    "CHANNEL_PREFIX",
    "channel_columns",
    "latest_spectrum",
    "spectrum_axis",
    "downsample",
]

import re

import numpy as np

#: Detector-channel column prefix the spectrometer server streams.
CHANNEL_PREFIX = "ch_"

_CHANNEL = re.compile(rf"^{CHANNEL_PREFIX}(\d+)$")


def channel_columns(snapshot: dict) -> list:
    """Detector-channel columns, in channel order.

    Sorted numerically: ``ch_10`` sorts before ``ch_2`` as text, which would
    shuffle the spectrum into nonsense while still looking like a plot.
    """
    found = []
    for name in snapshot:
        match = _CHANNEL.match(name)
        if match:
            found.append((int(match.group(1)), name))
    return [name for _, name in sorted(found)]


def latest_spectrum(snapshot: dict) -> np.ndarray:
    """The most recent spectrum, one value per channel."""
    columns = channel_columns(snapshot)
    values = [snapshot[name][-1] for name in columns if snapshot[name].size]
    return np.asarray(values, dtype=float)


def spectrum_axis(wavelengths, channel_count: int) -> tuple:
    """The x axis for a spectrum, and its label.

    Falls back to the channel index when the wavelength axis has not arrived
    or does not match the channel count. A mismatched axis is the dangerous
    case: zipping 1024 wavelengths against 512 channels misplots every point
    while looking entirely plausible.
    """
    if wavelengths is not None and len(wavelengths) == channel_count:
        return np.asarray(wavelengths, dtype=float), "Wavelength (nm)"
    return np.arange(float(channel_count)), "Detector channel"


def downsample(x: np.ndarray, y: np.ndarray, stride: int) -> tuple:
    """Take every ``stride``-th point of an aligned pair.

    A stride below 1 is treated as 1 rather than emptying the plot: it comes
    from a config value, and a typo should not blank the panel.
    """
    step = max(1, int(stride))
    return x[::step], y[::step]
