# helao/ui/reflex/uvvis.py
"""The `/uvvis` page: R_UVVIS reflectance spectra across one plate.

Retrieve lists the plate's R_UVVIS spectra (see ``helao.ui.shared.uvvis``
for how they are found); a run_id and a run_use pick which ones, and Plot
loads them all. Charts, window and selection are the shared plate-spectra
page (``spectra_page``); this module adds the run grouping and the 350-1000
nm statistics.
"""

from __future__ import annotations

from typing import ClassVar

import reflex as rx

from helao.helpers import helao_logging as logging
from helao.ui.reflex import spectra_page
from helao.ui.reflex.composition import parse_plate_id, platemap_for
from helao.ui.reflex.spectra_page import SpectraPageState
from helao.ui.shared import uvvis
from helao.ui.shared.composition import api, grouping

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

#: The run_use a run's selection defaults to when it has one.
DEFAULT_RUN_USE = "data"

#: Kept importable from here; the shared page builds the table.
detail_rows = spectra_page.detail_rows


def run_use_options(records, run_id: str) -> list:
    """``All`` plus every run_use in *run_id*, sorted."""
    uses = {r.run_use or grouping.NO_RUN_USE for r in records if r.run_id == run_id}
    return [grouping.ALL] + sorted(uses)


def select_records(records, run_id: str, run_use: str) -> list:
    """The records of one run, narrowed to one run_use unless ``All``."""
    return [
        r
        for r in records
        if r.run_id == run_id
        and (run_use == grouping.ALL or (r.run_use or grouping.NO_RUN_USE) == run_use)
    ]


class UvvisState(SpectraPageState, rx.State):
    """The UV-Vis page: runs and run_uses over the shared spectra page."""

    FILE_TYPE: ClassVar[str] = uvvis.SPECTRUM_FILE_TYPE
    X_KEY: ClassVar[str] = uvvis.X_KEY
    Y_KEY: ClassVar[str] = uvvis.Y_KEY
    X_LABEL: ClassVar[str] = "wavelength (nm)"
    Y_LABEL: ClassVar[str] = "intensity"
    Y_NAME: ClassVar[str] = "intensity"
    X_UNIT: ClassVar[str] = "nm"
    STATS_RANGE: ClassVar = uvvis.STATS_RANGE
    PANEL_PREFIX: ClassVar[str] = "uvvis"

    run_choice: str = ""
    run_use_choice: str = grouping.ALL
    run_options: list[str] = []
    run_use_options: list[str] = []

    _runs: dict = {}

    @rx.event
    def set_run(self, value: str):
        self.run_choice = value
        self._refresh_run_uses()

    @rx.event
    def set_run_use(self, value: str):
        self.run_use_choice = value

    def _refresh_run_uses(self) -> None:
        options = run_use_options(self._records, self._runs.get(self.run_choice, ""))
        self.run_use_options = options
        if self.run_use_choice not in options:
            self.run_use_choice = (
                DEFAULT_RUN_USE if DEFAULT_RUN_USE in options else grouping.ALL
            )

    @rx.event(background=True)
    async def retrieve(self, _tick: str = ""):
        """List every R_UVVIS spectrum on the entered plate; loads no spectra."""
        async with self:
            plate_id = parse_plate_id(self.plate_id)
            self.error, self.status = "", ""
            self._clear_charts()
        if plate_id is None:
            async with self:
                self.error = f"'{self.plate_id}' is not a plate id"
            return
        async with self:
            self.status = f"finding plate {plate_id}'s R_UVVIS runs..."
        try:
            records = await uvvis.records_for_plate(api.get_client(), plate_id)
        except Exception as exc:
            LOGGER.warning(f"uvvis could not list plate {plate_id}: {exc}")
            async with self:
                self.error = f"plate {plate_id} could not be listed: {exc}"
                self.status = ""
            return
        rows, note = platemap_for(plate_id)
        async with self:
            self._records = records
            self._pm_rows = rows
            self.platemap_note = note
            run_ids = sorted({r.run_id for r in records if r.run_id}, reverse=True)
            self._runs = {uvvis.run_label(run_id): run_id for run_id in run_ids}
            self.run_options = list(self._runs)
            self.run_choice = self.run_options[0] if self.run_options else ""
            self._refresh_run_uses()
            if records:
                self.status = (
                    f"plate {plate_id}: {len(records)} R_UVVIS spectra in "
                    f"{len(run_ids)} runs"
                )
            else:
                # Found through sequence_params.plate_id, which older
                # sequences only gain as the API backfill reaches them.
                self.status = (
                    f"plate {plate_id}: no R_UVVIS sequences found (older "
                    f"sequences appear once the API backfill reaches them)"
                )

    @rx.event(background=True)
    async def plot(self, _tick: str = ""):
        """Load every spectrum of the chosen run and run_use, then draw."""
        async with self:
            self.error = ""
            self._clear_charts()
            chosen = select_records(
                self._records, self._runs.get(self.run_choice, ""), self.run_use_choice
            )
            if not chosen:
                self.status = "nothing matches this run and run_use"
                return
            self.status = f"loading {len(chosen)} spectra..."
        await self._load_and_draw(chosen, api.get_client())


def build_page():
    """Render the UV-Vis page.

    Returns:
        rx.Component: The page body.
    """
    S = UvvisState
    return rx.vstack(
        spectra_page.plate_row(S),
        rx.hstack(
            spectra_page._muted("run_id"),
            rx.select(
                S.run_options, value=S.run_choice, on_change=S.set_run, width="32em"
            ),
            spectra_page._muted("run_use"),
            rx.select(
                S.run_use_options,
                value=S.run_use_choice,
                on_change=S.set_run_use,
                width="12em",
            ),
            *spectra_page.plot_controls(S),
            spacing="3",
            align="center",
        ),
        *spectra_page.window_rows(S, "nm"),
        *spectra_page.charts(S),
        width="100%",
        spacing="4",
        padding_x="1em",
    )
