# helao/ui/reflex/plate_photo.py
"""The wafer-photo underlay for the Reflex plate maps: state and controls.

:class:`PlatePhotoState` is a Reflex **mixin**, and that is load-bearing (see
``state.py``): vars declared on a concrete ``rx.State`` are shared by every
subclass. ``CompositionState`` mixes it in directly, and the ``SpectraPageState``
mixin takes it as ``SpectraPageState(PlatePhotoState, rx.State, mixin=True)``, as
``LiveVisState`` inherits ``VisPanelState``, so ``UvvisState``, ``XrdsState`` and
``XafsState`` each still own their copy. Never mix it into a concrete base.

A page supplies ``_redraw_photo``, its own map-redraw path:
``CompositionState`` and ``SpectraPageState`` each override it. The default
here raises, so a page that forgets fails on first use rather than drawing
nothing.
"""

from __future__ import annotations

import reflex as rx

from helao.helpers import helao_logging as logging
from helao.ui.reflex import plots
from helao.ui.shared import plate_photo, platemap
from helao.ui.shared.palette import reflex_muted_text_class

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

#: The dropdown entry that draws no photo, and the default.
PHOTO_OFF = "off"

#: The note when a plate has no wafer-photo note.
NO_PHOTOS_NOTE = "no wafer photo notes on this plate"


def _plate_api():
    """The configured plate API, or ``None``.

    Imported here, not at module scope: ``composition`` imports this module for
    the mixin, so a top-level import would be circular.
    """
    from helao.ui.reflex.composition import world_config

    return platemap.plate_api_for_config(world_config())


class PlatePhotoState(rx.State, mixin=True):
    """Which wafer photo, if any, the plate map draws underneath."""

    #: Dropdown labels, ``"off"`` first.
    photo_options: list[str] = [PHOTO_OFF]
    photo_choice: str = PHOTO_OFF
    photo_opacity: float = plots.UNDERLAY_OPACITY
    #: Why there is no photo, or why the chosen one is not drawn.
    photo_note: str = ""

    #: Backend only: the plate's ``Underlay`` records, in dropdown order.
    _photos: list = []

    def _redraw_photo(self) -> None:
        """Redraw the map; each page supplies its own."""
        raise NotImplementedError(
            f"{type(self).__name__} mixes in PlatePhotoState but defines no "
            f"_redraw_photo"
        )

    def _load_photos(self, plate_id: int) -> None:
        """List *plate_id*'s wafer photos. Never raises.

        Called from each page's ``retrieve`` inside its state lock, beside
        ``platemap_for``. ``lookup_plate`` is a blocking call, as
        ``platemap_for``'s is, so the lock costs nothing extra: the event loop
        is blocked either way.
        """
        self.photo_choice = PHOTO_OFF
        self.photo_options = [PHOTO_OFF]
        self.photo_note = ""
        self._photos = []
        plate_api = _plate_api()
        if plate_api is None:
            self.photo_note = (
                "no plate API is configured, so there is no wafer photo to show"
            )
            return
        if getattr(plate_api, "loader", None) is None:
            self.photo_note = (
                "wafer photos need credentials; set HELAO_CREDENTIALS to a "
                "readable environment file"
            )
            return
        try:
            photos = plate_photo.underlays_for(plate_api, plate_id)
        except Exception as exc:
            LOGGER.warning(f"could not list plate {plate_id}'s wafer photos: {exc}")
            self.photo_note = (
                f"plate {plate_id}'s wafer photos could not be listed: {exc}"
            )
            return
        if not photos:
            self.photo_note = NO_PHOTOS_NOTE
            return
        self._photos = photos
        self.photo_options = [PHOTO_OFF] + [u.label for u in photos]

    def _underlay_arg(self):
        """``(rgba, extent)`` for the chosen photo, or ``None``.

        A failed fetch or decode leaves the map drawn without a photo and says
        which photo and why in ``photo_note``.
        """
        if self.photo_choice == PHOTO_OFF:
            return None
        chosen = next((u for u in self._photos if u.label == self.photo_choice), None)
        if chosen is None:
            return None
        try:
            rgba = plate_photo.load_image(_plate_api(), chosen)
        except Exception as exc:
            LOGGER.warning(f"could not read wafer photo {chosen.image_s3_uri}: {exc}")
            self.photo_note = f"wafer photo '{chosen.label}' could not be read: {exc}"
            return None
        return rgba, chosen.extent

    @rx.event
    def set_photo_choice(self, value: str):
        """Draw the chosen photo (or none) under the map."""
        self.photo_choice = value if value in self.photo_options else PHOTO_OFF
        if self._photos:
            # Clears a previous photo's read error; "no notes" and "no API"
            # notes only occur with nothing to choose, so they stay.
            self.photo_note = ""
        self._redraw_photo()

    @rx.event
    def set_photo_opacity(self, value: list[float]):
        """Bound to the slider's ``on_value_commit``, so a drag redraws once."""
        opacity = float(value[0]) if value else plots.UNDERLAY_OPACITY
        self.photo_opacity = min(max(opacity, 0.0), 1.0)
        if self.photo_choice != PHOTO_OFF:
            self._redraw_photo()


def photo_controls(S):
    """The photo dropdown, its opacity slider and the photo note, in one row.

    Args:
        S: A concrete page state class that mixes in :class:`PlatePhotoState`.
    """
    return rx.hstack(
        rx.text("photo", size="1", class_name=reflex_muted_text_class()),
        rx.select(
            S.photo_options,
            value=S.photo_choice,
            on_change=S.set_photo_choice,
            width="26em",
        ),
        rx.text("opacity", size="1", class_name=reflex_muted_text_class()),
        # Commit, not change: each value republishes the whole photo.
        rx.slider(
            default_value=[plots.UNDERLAY_OPACITY],
            min=0.0,
            max=1.0,
            step=0.05,
            on_value_commit=S.set_photo_opacity,
            width="8em",
        ),
        rx.cond(
            S.photo_note != "",
            rx.text(S.photo_note, size="1", class_name=reflex_muted_text_class()),
        ),
        spacing="3",
        align="center",
        flex_wrap="wrap",
    )
