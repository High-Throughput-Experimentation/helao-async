"""The plate-photo underlay wired into the four plate-map pages.

Rendered, not merely imported: an event-binding error appears only at render.
"""

import asyncio

import pytest

from helao.core.tests._plate_photo_fakes import (
    FakePlateAPI,
    bound_events,
    render_nodes,
    serving,
    top_row_red,
)
from helao.ui.reflex import composition, uvvis, xafs, xrds
from helao.ui.reflex import plate_photo as rpp
from helao.ui.reflex.spectra_page import SpectraPageState
from helao.ui.shared.composition import grouping

PAGES = {
    "composition": (composition, composition.CompositionState),
    "uvvis": (uvvis, uvvis.UvvisState),
    "xrds": (xrds, xrds.XrdsState),
    "xafs": (xafs, xafs.XafsState),
}
SPECTRA_PAGES = {k: v for k, v in PAGES.items() if k != "composition"}
PHOTO_VARS = ("photo_options", "photo_choice", "photo_opacity", "photo_note")


@pytest.mark.parametrize("name", PAGES)
def test_each_page_renders_photo_controls_and_no_extra_chart(name):
    """The photo is a trace on the existing map, so each page keeps its three
    charts: every chart is a WebGL context and the browser caps them."""
    module, _state = PAGES[name]
    page = module.build_page()
    bound = bound_events(page)
    assert ("SelectRoot", "on_change", "set_photo_choice") in bound
    assert ("Slider", "on_value_commit", "set_photo_opacity") in bound
    nodes = render_nodes(page)
    assert sum(type(n).__name__ == "XYChart" for n in nodes) == 3
    # Exactly one photo select: a duplicated control row would double it.
    chosen = [
        n
        for n in nodes
        if any(
            e.handler.fn.__name__ == "set_photo_choice"
            for chain in (getattr(n, "event_triggers", {}) or {}).values()
            for e in getattr(chain, "events", None) or []
        )
    ]
    assert len(chosen) == 1


@pytest.mark.parametrize("name", PAGES)
def test_each_page_state_owns_its_photo_vars_and_handlers(name):
    """Owned, not inherited: an inherited var would be one value shared by
    every page."""
    _module, state = PAGES[name]
    for var in PHOTO_VARS:
        assert var in state.vars
        assert var not in state.inherited_vars, f"{name} shares '{var}'"
    assert "_photos" in state.backend_vars
    for handler in ("set_photo_choice", "set_photo_opacity"):
        assert handler in state.event_handlers


def test_spectra_page_state_is_a_mixin_inheriting_the_photo_mixin():
    """The LiveVisState pattern: a mixin of a mixin, so the three spectra pages
    get the photo without listing it in their bases."""
    assert getattr(SpectraPageState, "_mixin", False)
    assert issubclass(SpectraPageState, rpp.PlatePhotoState)


def test_no_two_pages_share_photo_choice():
    """Each page's photo_choice is its own var under its own state path, so
    choosing a photo on /uvvis cannot change /xrds."""
    paths = {str(state.photo_choice) for _module, state in PAGES.values()}
    assert len(paths) == len(PAGES)


@pytest.mark.parametrize("name", SPECTRA_PAGES)
def test_spectra_pages_redraw_through_spectra_page_state(name):
    """Not the mixin's raising default. Both halves are needed: with the
    override deleted, the page and SpectraPageState would both still resolve
    to the same (raising) function."""
    _module, state = SPECTRA_PAGES[name]
    assert state._redraw_photo is SpectraPageState._redraw_photo
    assert state._redraw_photo is not rpp.PlatePhotoState._redraw_photo


def test_composition_supplies_its_own_redraw():
    state = composition.CompositionState
    assert state._redraw_photo is not rpp.PlatePhotoState._redraw_photo


class _PageFake:
    """Just what a spectra page's ``retrieve`` reads before it sets it."""

    def __init__(self):
        self.plate_id = "10197"
        self.error = self.status = ""
        self.run_use_choice = grouping.ALL
        self.photo_options = ["off"]
        self.photo_choice = "off"
        self.photo_note = ""
        self._photos: list = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _fake(state):
    attrs = {
        "retrieve": state.retrieve.fn,
        "_load_photos": state._load_photos,
        "_clear_charts": state._clear_charts,
    }
    for name in ("_refresh_options", "_refresh_run_uses"):
        method = getattr(state, name, None)
        if method is not None:
            attrs[name] = method
    return type(f"_Fake{state.__name__}", (_PageFake,), attrs)()


@pytest.mark.parametrize("name", SPECTRA_PAGES)
@pytest.mark.parametrize("failing", [False, True], ids=["photos", "lookup-raises"])
def test_spectra_retrieve_lists_photos_and_survives_a_failing_lookup(
    monkeypatch, name, failing
):
    module, state = SPECTRA_PAGES[name]
    shared = getattr(module, name)  # the page's helao.ui.shared lookup module

    async def no_records(client, plate_id):
        return []

    monkeypatch.setattr(shared, "records_for_plate", no_records)
    monkeypatch.setattr(module, "platemap_for", lambda pid: ([], "no platemap"))
    monkeypatch.setattr(module.api, "get_client", lambda: None)
    api = (
        FakePlateAPI(error=RuntimeError("HTTP 503"))
        if failing
        else serving(top_row_red())
    )
    monkeypatch.setattr(rpp, "_plate_api", lambda: api)

    fake = _fake(state)
    asyncio.run(fake.retrieve(""))
    assert fake.status.startswith("plate 10197")  # retrieve ran to the end
    if failing:
        assert fake.photo_options == ["off"]
        assert "HTTP 503" in fake.photo_note
    else:
        assert len(fake.photo_options) == 2
