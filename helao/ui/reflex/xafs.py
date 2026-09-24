# helao/ui/reflex/xafs.py
"""The `/xafs` page: XAFS scans across one plate.

The shared plate-spectra page (``spectra_page``) over ``xafsscan__helao_file``
scans: ROI count rate against energy, with the details table's statistics
taken over the energy window. Grouping is the composition page's -- run_use,
then sequence -- plus an element, because one sequence scans several edges
and averaging a Cu edge with a Co edge means nothing. Element has no ``All``.
"""

from __future__ import annotations

from typing import ClassVar

import reflex as rx

from helao.helpers import helao_logging as logging
from helao.ui.reflex import spectra_page
from helao.ui.reflex.composition import _kept_or_first, parse_plate_id, platemap_for
from helao.ui.reflex.spectra_page import SpectraPageState
from helao.ui.shared import xafs
from helao.ui.shared.composition import api, grouping

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

#: The run_use a selection defaults to when the plate has one.
DEFAULT_RUN_USE = "data"


def element_options(records) -> list:
    """Every element in *records*, sorted. No ``All``: edges do not mix."""
    return sorted({r.element for r in records if r.element})


def select_records(records, run_use: str, sequence: str, element: str) -> list:
    """The records matching all three selections."""
    return [
        r
        for r in grouping.filter_records(records, run_use=run_use, sequence=sequence)
        if r.element == element
    ]


class XafsState(SpectraPageState, rx.State):
    """The XAFS page: run_use, sequence and element over the shared page."""

    FILE_TYPE: ClassVar[str] = xafs.SPECTRUM_FILE_TYPE
    X_KEY: ClassVar[str] = xafs.X_KEY
    Y_KEY: ClassVar[str] = xafs.Y_KEY
    X_LABEL: ClassVar[str] = xafs.X_KEY
    Y_LABEL: ClassVar[str] = xafs.Y_KEY
    Y_NAME: ClassVar[str] = "ROI count rate"
    X_UNIT: ClassVar[str] = "eV"
    STATS_RANGE: ClassVar = None
    PANEL_PREFIX: ClassVar[str] = "xafs"

    run_use_choice: str = grouping.ALL
    sequence_choice: str = grouping.ALL
    element_choice: str = ""
    run_use_options: list[str] = []
    sequence_options: list[str] = []
    element_options: list[str] = []

    @rx.event
    def set_run_use(self, value: str):
        self.run_use_choice = value
        self._refresh_options()

    @rx.event
    def set_sequence(self, value: str):
        self.sequence_choice = value
        self._refresh_options()

    @rx.event
    def set_element(self, value: str):
        self.element_choice = value

    def _refresh_options(self) -> None:
        """run_use scopes sequences; both scope elements (composition's rule)."""
        by_run_use = grouping.filter_records(
            self._records, run_use=self.run_use_choice, sequence=grouping.ALL
        )
        self.sequence_options = grouping.sequence_options(by_run_use)
        if self.sequence_choice not in self.sequence_options:
            self.sequence_choice = grouping.ALL
        scoped = grouping.filter_records(
            by_run_use, run_use=grouping.ALL, sequence=self.sequence_choice
        )
        self.element_options = element_options(scoped)
        self.element_choice = _kept_or_first(self.element_choice, self.element_options)

    @rx.event(background=True)
    async def retrieve(self, _tick: str = ""):
        """List every XAFS scan on the entered plate; loads no spectra."""
        async with self:
            plate_id = parse_plate_id(self.plate_id)
            self.error, self.status = "", ""
            self._clear_charts()
        if plate_id is None:
            async with self:
                self.error = f"'{self.plate_id}' is not a plate id"
            return
        async with self:
            self.status = f"finding plate {plate_id}'s XAFS sequences..."
        try:
            records = await xafs.records_for_plate(api.get_client(), plate_id)
        except Exception as exc:
            LOGGER.warning(f"xafs could not list plate {plate_id}: {exc}")
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
            self.element_choice = ""
            self._refresh_options()
            sequences = len({r.sequence_uuid for r in records})
            self.status = (
                f"plate {plate_id}: {len(records)} XAFS scans in {sequences} "
                f"sequences"
                if records
                else f"plate {plate_id}: no XAFS scans found"
            )

    @rx.event(background=True)
    async def plot(self, _tick: str = ""):
        """Load every scan of the chosen run_use, sequence and element."""
        async with self:
            self.error = ""
            self._clear_charts()
            chosen = select_records(
                self._records,
                self.run_use_choice,
                self.sequence_choice,
                self.element_choice,
            )
            if not chosen:
                self.status = "nothing matches this run_use, sequence and element"
                return
            self.status = f"loading {len(chosen)} scans..."
        await self._load_and_draw(chosen, api.get_client())


def build_page():
    """Render the XAFS page.

    Returns:
        rx.Component: The page body.
    """
    S = XafsState
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
            spectra_page._muted("element"),
            rx.select(
                S.element_options,
                value=S.element_choice,
                on_change=S.set_element,
                width="6em",
            ),
            *spectra_page.plot_controls(S),
            spacing="3",
            align="center",
        ),
        *spectra_page.window_rows(S, "eV"),
        *spectra_page.charts(S),
        width="100%",
        spacing="4",
        padding_x="1em",
    )
