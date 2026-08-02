"""Tests for the hte deployment's spectrometer and sample panels.

These two are the odd ones. ``spec_vis`` renders a whole spectrum per packet
rather than a time series, and ``sample_vis`` is not a chart at all -- it polls
the SAMPLE server's private endpoint and renders four tables.
"""

import numpy as np

from helao.deploy.hte.servers.reflex import _samples, _spectra


def _snap(**cols):
    return {k: np.asarray(v, dtype=float) for k, v in cols.items()}


# -- spectra -----------------------------------------------------------------


def test_channels_sort_numerically_not_lexically():
    """`ch_10` sorts before `ch_2` as text, which would shuffle the spectrum
    into nonsense while still looking like a plot."""
    snap = _snap(ch_0=[1.0], ch_10=[2.0], ch_2=[3.0], epoch_s=[0.0])
    assert _spectra.channel_columns(snap) == ["ch_0", "ch_2", "ch_10"]


def test_channel_columns_ignore_everything_else():
    snap = _snap(ch_0=[1.0], epoch_s=[0.0], t_s=[1.0])
    assert _spectra.channel_columns(snap) == ["ch_0"]


def test_the_latest_spectrum_is_the_last_row_across_the_channels():
    """One packet is one row and one spectrum: the channels are columns, not
    successive samples."""
    snap = _snap(ch_0=[1.0, 4.0], ch_1=[2.0, 5.0], ch_2=[3.0, 6.0])
    assert list(_spectra.latest_spectrum(snap)) == [4.0, 5.0, 6.0]


def test_a_spectrum_from_an_empty_buffer_is_empty():
    assert _spectra.latest_spectrum({}).size == 0
    assert _spectra.latest_spectrum(_snap(ch_0=[])).size == 0


def test_the_x_axis_is_the_wavelengths_when_they_are_known():
    x, label = _spectra.spectrum_axis([400.0, 401.0, 402.0], 3)
    assert list(x) == [400.0, 401.0, 402.0]
    assert "nm" in label


def test_the_x_axis_falls_back_to_channel_index():
    """The wavelength axis is fetched from the server and may not have arrived
    yet, or at all. Plotting against the index still shows the spectrum."""
    x, label = _spectra.spectrum_axis([], 3)
    assert list(x) == [0.0, 1.0, 2.0]
    assert "channel" in label.lower()


def test_a_wavelength_axis_of_the_wrong_length_is_not_used():
    """Zipping 1024 wavelengths against 512 channels silently misplots every
    point; falling back to the index is wrong but visibly so."""
    x, label = _spectra.spectrum_axis([400.0, 401.0], 3)
    assert list(x) == [0.0, 1.0, 2.0]
    assert "channel" in label.lower()


def test_downsampling_keeps_x_and_y_aligned():
    x, y = _spectra.downsample(np.arange(10.0), np.arange(10.0) * 2, stride=3)
    assert x.size == y.size
    assert list(x) == [0.0, 3.0, 6.0, 9.0]


def test_downsampling_by_one_changes_nothing():
    x, y = _spectra.downsample(np.arange(4.0), np.arange(4.0), stride=1)
    assert x.size == 4


def test_a_nonsense_stride_does_not_empty_the_plot():
    x, y = _spectra.downsample(np.arange(4.0), np.arange(4.0), stride=0)
    assert x.size == 4


# -- samples -----------------------------------------------------------------


def test_sample_rows_project_the_displayed_columns():
    samples = [
        {"global_label": "a", "sample_creation_timecode": 0, "ph": 7, "extra": "x"}
    ]
    rows = _samples.sample_rows(samples)
    assert rows[0][0] == "a"
    assert len(rows[0]) == len(_samples.SAMPLE_COLUMNS)


def test_a_missing_field_renders_blank_rather_than_dropping_the_sample():
    rows = _samples.sample_rows([{"global_label": "a"}])
    assert rows[0][0] == "a"
    assert rows[0][2] == ""


def test_the_creation_timecode_is_rendered_as_a_readable_time():
    """It arrives in nanoseconds; unconverted it is an unreadable integer."""
    rows = _samples.sample_rows(
        [{"sample_creation_timecode": 1_600_000_000_000_000_000}]
    )
    stamp = rows[0][1]
    assert stamp.startswith("20")
    assert ":" in stamp


def test_a_missing_timecode_does_not_raise():
    rows = _samples.sample_rows([{"global_label": "a"}])
    assert rows[0][1] == ""


def test_a_nonsense_timecode_is_shown_raw_rather_than_crashing_the_panel():
    rows = _samples.sample_rows([{"sample_creation_timecode": "not a number"}])
    assert rows[0][1] == "not a number"


def test_every_cell_is_a_string():
    rows = _samples.sample_rows([{"ph": 7.0, "volume_ml": 1}])
    assert all(isinstance(cell, str) for cell in rows[0])


def test_no_samples_is_no_rows():
    assert _samples.sample_rows([]) == []
    assert _samples.sample_rows(None) == []


def test_sample_types_cover_what_the_server_returns():
    assert set(_samples.SAMPLE_TYPES) == {"solid", "liquid", "gas", "assembly"}


def test_tables_for_reads_each_type_out_of_one_response():
    response = {"solid": [{"global_label": "s"}], "liquid": [{"global_label": "l"}]}
    tables = _samples.tables_for(response)
    assert tables["solid"][0][0] == "s"
    assert tables["liquid"][0][0] == "l"
    # A type the response omits is an empty table, not a missing key.
    assert tables["gas"] == []


def test_tables_for_survives_a_malformed_response():
    assert _samples.tables_for(None)["solid"] == []
    assert _samples.tables_for({"solid": "not a list"})["solid"] == []


# -- the panels --------------------------------------------------------------


def test_both_panels_expose_the_contract():
    from helao.deploy.hte.servers.reflex import sample_vis, spec_vis

    for module in (spec_vis, sample_vis):
        assert module.WS_PATH == "ws_data"
        assert callable(module.build)
        assert getattr(module.STATE_BASE, "_mixin", False), module.__name__


def test_they_do_not_share_a_state_class():
    from helao.deploy.hte.servers.reflex import sample_vis, spec_vis

    assert spec_vis.STATE_BASE is not sample_vis.STATE_BASE
