"""Tests for the plate-photo mixin and its controls, without a running app."""

import numpy as np
import pytest
import reflex as rx

from helao.core.tests._plate_photo_fakes import (
    EXTENT,
    FakeLoader,
    FakePhotoState,
    FakePlateAPI,
    bound_events,
    note,
    serving,
    top_row_red,
)
from helao.ui.reflex import plate_photo as rpp
from helao.ui.reflex import plots
from helao.ui.shared import plate_photo


@pytest.fixture(autouse=True)
def _fresh_cache():
    plate_photo._fetch_rgba.cache_clear()
    yield
    plate_photo._fetch_rgba.cache_clear()


def _with_api(monkeypatch, api):
    monkeypatch.setattr(rpp, "_plate_api", lambda: api)
    return api


def test_load_photos_fills_the_options_off_first_and_resets_the_choice(monkeypatch):
    _with_api(
        monkeypatch,
        FakePlateAPI(
            [note(variant="raw"), note(variant="stretched")],
        ),
    )
    state = FakePhotoState()
    state.photo_choice = "a photo of the previous plate"
    state._load_photos(10197)
    assert state.photo_options == [
        "off",
        "postanneal stretched (102250_x_postanneal.png)",
        "postanneal raw (102250_x_postanneal.png)",
    ]
    assert state.photo_choice == "off"
    assert state.photo_note == ""
    assert len(state._photos) == 2


@pytest.mark.parametrize(
    "api, expected",
    [
        (None, "no plate API is configured"),
        (FakePlateAPI([note()], loader=None), "HELAO_CREDENTIALS"),
        (FakePlateAPI([]), rpp.NO_PHOTOS_NOTE),
        (FakePlateAPI(error=RuntimeError("HTTP 503")), "HTTP 503"),
    ],
    ids=["no-api", "no-credentials", "no-notes", "lookup-raises"],
)
def test_load_photos_offers_only_off_and_says_why(monkeypatch, api, expected):
    """A stale plate's photos must not survive, and a lookup error must not
    escape: ``retrieve`` calls this and has to finish."""
    _with_api(monkeypatch, api)
    state = FakePhotoState()
    state.photo_options = ["off", "a photo of the previous plate"]
    state._photos = ["stale"]
    state._load_photos(10197)
    assert state.photo_options == ["off"]
    assert state.photo_choice == "off"
    assert state._photos == []
    assert expected in state.photo_note


def test_no_credentials_never_calls_the_plate_api(monkeypatch):
    api = _with_api(monkeypatch, FakePlateAPI([note()], loader=None))
    FakePhotoState()._load_photos(10197)
    assert api.lookups == []


def test_underlay_arg_is_none_with_the_photo_off(monkeypatch):
    api = _with_api(monkeypatch, serving(top_row_red()))
    state = FakePhotoState()
    state._load_photos(10197)
    assert state._underlay_arg() is None
    assert api.loader.calls == []


def test_underlay_arg_returns_the_chosen_photo_and_its_extent(monkeypatch):
    _with_api(monkeypatch, serving(top_row_red(rows=8, cols=6)))
    state = FakePhotoState()
    state._load_photos(10197)
    state.set_photo_choice(state.photo_options[1])
    rgba, extent = state._underlay_arg()
    assert rgba.shape == (8, 6, 4)
    assert np.array_equal(rgba, top_row_red(rows=8, cols=6))
    assert extent == EXTENT


def test_a_failed_image_fetch_draws_without_a_photo_and_names_it(monkeypatch):
    api = serving(top_row_red())
    api.loader = FakeLoader(error=OSError("access denied"))
    _with_api(monkeypatch, api)
    state = FakePhotoState()
    state._load_photos(10197)
    label = state.photo_options[1]
    state.set_photo_choice(label)
    assert state._underlay_arg() is None
    assert label in state.photo_note and "access denied" in state.photo_note


def test_choosing_a_photo_or_off_redraws_and_an_unknown_choice_is_off(monkeypatch):
    _with_api(monkeypatch, serving(top_row_red()))
    state = FakePhotoState()
    state._load_photos(10197)
    label = state.photo_options[1]
    state.set_photo_choice(label)
    assert (state.photo_choice, state.redraws) == (label, 1)
    state.set_photo_choice("off")
    assert (state.photo_choice, state.redraws) == ("off", 2)
    state.set_photo_choice("not an option")
    assert state.photo_choice == "off"


def test_opacity_is_clamped_and_redraws_only_with_a_photo_shown(monkeypatch):
    _with_api(monkeypatch, serving(top_row_red()))
    state = FakePhotoState()
    state._load_photos(10197)
    state.set_photo_opacity([0.3])
    assert (state.photo_opacity, state.redraws) == (0.3, 0)
    state.set_photo_choice(state.photo_options[1])
    state.set_photo_opacity([1.7])
    assert (state.photo_opacity, state.redraws) == (1.0, 2)
    state.set_photo_opacity([-1.0])
    assert state.photo_opacity == 0.0


def test_photo_controls_bind_the_select_and_the_slider_at_render():
    """Event-binding errors appear at render, not at import."""

    class PhotoControlsProbeState(rpp.PlatePhotoState, rx.State):
        def _redraw_photo(self) -> None:
            pass

    bound = bound_events(rpp.photo_controls(PhotoControlsProbeState))
    assert ("SelectRoot", "on_change", "set_photo_choice") in bound
    assert ("Slider", "on_value_commit", "set_photo_opacity") in bound
