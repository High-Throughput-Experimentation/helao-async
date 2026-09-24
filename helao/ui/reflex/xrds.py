# helao/ui/reflex/xrds.py
"""The `/xrds` page: integrated XRD patterns across one plate.

The shared plate-spectra page (``spectra_page``) over ``xrds_frame``
patterns: intensity against two-theta, statistics over the two-theta window.
Grouping is the composition page's run_use and sequence; a file-type dropdown
picks the original or background-subtracted pattern. No element grouping.
"""

from __future__ import annotations

from typing import ClassVar

import reflex as rx

from helao.helpers import helao_logging as logging
from helao.ui.reflex import spectra_page
from helao.ui.reflex.composition import parse_plate_id, platemap_for
from helao.ui.reflex.spectra_page import SpectraPageState
from helao.ui.shared import xrds
from helao.ui.shared.composition import api, grouping

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

#: The run_use a selection defaults to when the plate has one.
DEFAULT_RUN_USE = "data"


def select_records(records, run_use: str, sequence: str, file_type: str) -> list:
    """The records matching run_use, sequence and file type."""
    return [
        r
        for r in grouping.filter_records(records, run_use=run_use, sequence=sequence)
        if r.file_type == file_type
    ]


class XrdsState(SpectraPageState, rx.State):
    """The XRD page: run_use, sequence and pattern type over the shared page."""

    X_KEY: ClassVar[str] = xrds.X_KEY
    Y_KEY: ClassVar[str] = xrds.Y_KEY
    X_LABEL: ClassVar[str] = xrds.X_KEY
    Y_LABEL: ClassVar[str] = xrds.Y_KEY
    Y_NAME: ClassVar[str] = "intensity"
    X_UNIT: ClassVar[str] = "deg"
    STATS_RANGE: ClassVar = None
    PANEL_PREFIX: ClassVar[str] = "xrds"
    SLIDER_STEP: ClassVar[float] = 0.05
    DECIMALS: ClassVar[int] = 2

    run_use_choice: str = grouping.ALL
    sequence_choice: str = grouping.ALL
    file_type_choice: str = next(iter(xrds.FILE_TYPES))
    run_use_options: list[str] = []
    sequence_options: list[str] = []
    file_type_options: list[str] = list(xrds.FILE_TYPES)

    @rx.event
    def set_run_use(self, value: str):
        self.run_use_choice = value
        self._refresh_options()

    @rx.event
    def set_sequence(self, value: str):
        self.sequence_choice = value

    @rx.event
    def set_file_type(self, value: str):
        self.file_type_choice = value

    def _refresh_options(self) -> None:
        """run_use scopes the sequences, as on the composition page."""
        by_run_use = grouping.filter_records(
            self._records, run_use=self.run_use_choice, sequence=grouping.ALL
        )
        self.sequence_options = grouping.sequence_options(by_run_use)
        if self.sequence_choice not in self.sequence_options:
            self.sequence_choice = grouping.ALL

    @rx.event(background=True)
    async def retrieve(self, _tick: str = ""):
        """List every XRD pattern on the entered plate; loads no spectra."""
        async with self:
            plate_id = parse_plate_id(self.plate_id)
            self.error, self.status = "", ""
            self._clear_charts()
        if plate_id is None:
            async with self:
                self.error = f"'{self.plate_id}' is not a plate id"
            return
        async with self:
            self.status = f"finding plate {plate_id}'s XRD frames..."
        try:
            records = await xrds.records_for_plate(api.get_client(), plate_id)
        except Exception as exc:
            LOGGER.warning(f"xrds could not list plate {plate_id}: {exc}")
            async with self:
                self.error = f"plate {plate_id} could not be listed: {exc}"
                self.status = ""
            return
        rows, note = platemap_for(plate_id)
        async with self:
            self._records = records
            self._pm_rows = rows
            self.platemap_note = note
            self.run_use_options = grouping.run_use_options(records)
            self.run_use_choice = (
                DEFAULT_RUN_USE
                if DEFAULT_RUN_USE in self.run_use_options
                else grouping.ALL
            )
            self.sequence_choice = grouping.ALL
            self._refresh_options()
            frames = len({r.process_uuid for r in records})
            self.status = (
                f"plate {plate_id}: {frames} XRD frames"
                if records
                else f"plate {plate_id}: no XRD frames found"
            )

    @rx.event(background=True)
    async def plot(self, _tick: str = ""):
        """Load every pattern of the chosen run_use, sequence and type."""
        async with self:
            self.error = ""
            self._clear_charts()
            file_type = xrds.FILE_TYPES.get(self.file_type_choice, "")
            chosen = select_records(
                self._records, self.run_use_choice, self.sequence_choice, file_type
            )
            if not chosen:
                self.status = "nothing matches this run_use, sequence and type"
                return
            self.status = f"loading {len(chosen)} patterns..."
        await self._load_and_draw(chosen, api.get_client(), file_type)


def build_page():
    """Render the XRD page.

    Returns:
        rx.Component: The page body.
    """
    S = XrdsState
    return rx.vstack(
        spectra_page.plate_row(S),
        rx.hstack(
            spectra_page._muted("run_use"),
            rx.select(
                S.run_use_options,
                value=S.run_use_choice,
                on_change=S.set_run_use,
                width="12em",
            ),
            spectra_page._muted("sequence"),
            rx.select(
                S.sequence_options,
                value=S.sequence_choice,
                on_change=S.set_sequence,
                width="24em",
            ),
            spectra_page._muted("pattern"),
            rx.select(
                S.file_type_options,
                value=S.file_type_choice,
                on_change=S.set_file_type,
                width="14em",
            ),
            *spectra_page.plot_controls(S),
            spacing="3",
            align="center",
        ),
        *spectra_page.window_rows(S, "deg"),
        *spectra_page.charts(S),
        width="100%",
        spacing="4",
        padding_x="1em",
    )
