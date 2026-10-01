"""Whole-wafer photos posted as plate notes, for the plate-map underlay.

A wafer-photo converter posts two plate notes per photo (a ``raw`` and a
``stretched`` variant) through the plate-management API. Each note's text is
one human-readable line, a newline, then a JSON object of kind
``wafer_photo_circle_crop`` carrying the photo's ``extent_mm`` on platemap mm
axes; its ``image_s3_uri`` names an RGBA PNG, transparent outside the wafer.

Note creation is asynchronous and the API has no delete, so a fast re-run can
post one variant twice: :func:`underlays_for` keeps the newest note per
``(input_png, variant)``.

This module imports neither ``reflex`` nor ``xy``, so it is testable without an
app and usable by either UI stack.
"""

from __future__ import annotations

import functools
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import numpy as np
from PIL import Image

__all__ = [
    "NOTE_KIND",
    "UNDERLAY_MAX_PX",
    "Underlay",
    "load_image",
    "parse_note",
    "split_s3_uri",
    "underlays_for",
]

#: The ``kind`` a note's JSON must carry to be a wafer photo.
NOTE_KIND = "wafer_photo_circle_crop"

#: Longest image edge after downsampling. Each redraw republishes the photo
#: as four f32 planes, so 512 px is 4 MiB per redraw.
UNDERLAY_MAX_PX = 512

#: Decoded photos kept in memory. One 512 px RGBA photo is 1 MiB as uint8.
IMAGE_CACHE_SIZE = 8

#: Dropdown order: states first, then variants. Unknown values sort last.
STATE_ORDER = ("postanneal", "asdep", "preanneal")
VARIANT_ORDER = ("stretched", "raw")


@dataclass(frozen=True)
class Underlay:
    """One wafer photo a plate map can draw underneath its points.

    Attributes:
        key: Stable id, ``"<input_png>|<variant>"``.
        label: What the dropdown shows.
        state: ``postanneal``, ``asdep`` or ``preanneal``.
        variant: ``raw`` or ``stretched``.
        input_png: The source photo's file name.
        created_at: The note's ``created_at``, verbatim.
        extent: ``((x_min, x_max), (y_min, y_max))``, the image's outer edges
            in platemap mm. Its top-left corner sits at ``(x_min, y_max)``.
        image_s3_uri: ``s3://<bucket>/<key>`` of the RGBA PNG.
    """

    key: str
    label: str
    state: str
    variant: str
    input_png: str
    created_at: str
    extent: tuple
    image_s3_uri: str


def parse_note(note) -> Optional[Underlay]:
    """The wafer photo *note* describes, or ``None`` when it is not one.

    Plain-text notes, notes of any other kind, malformed JSON and notes
    without an ``s3://`` image all give ``None``.
    """
    if not isinstance(note, dict):
        return None
    text, uri = note.get("text"), note.get("image_s3_uri")
    if not isinstance(text, str) or "\n" not in text:
        return None
    if not isinstance(uri, str) or not uri.startswith("s3://"):
        return None
    try:
        meta = json.loads(text.split("\n", 1)[1])
    except ValueError:
        return None
    if not isinstance(meta, dict) or meta.get("kind") != NOTE_KIND:
        return None
    try:
        ext = meta["extent_mm"]
        (x0, x1), (y0, y1) = ext["x"], ext["y"]
        extent = ((float(x0), float(x1)), (float(y0), float(y1)))
        input_png = str(meta["input_png"])
        variant = str(meta["variant"])
        state = str(meta["state"])
    except (KeyError, TypeError, ValueError):
        return None
    # Also rejects NaN, which compares false either way.
    if not (extent[0][0] < extent[0][1] and extent[1][0] < extent[1][1]):
        return None
    return Underlay(
        key=f"{input_png}|{variant}",
        label=f"{state} {variant} ({input_png})",
        state=state,
        variant=variant,
        input_png=input_png,
        created_at=str(note.get("created_at") or ""),
        extent=extent,
        image_s3_uri=uri,
    )


def _created_ts(created_at: str) -> float:
    """``created_at`` as a timestamp; unparsable sorts oldest."""
    try:
        return datetime.fromisoformat(created_at).timestamp()
    except (TypeError, ValueError):
        return float("-inf")


def _rank(value: str, order: tuple) -> int:
    return order.index(value) if value in order else len(order)


def underlays_for(plate_api, plate_id: int) -> list:
    """Every wafer photo on *plate_id*, newest per photo and variant, ordered.

    Order: state (``postanneal``, ``asdep``, ``preanneal``), then variant
    (``stretched`` before ``raw``), then ``input_png``.

    Returns:
        list[Underlay]: Empty when there is no plate API, no such plate, or no
        wafer-photo note on it.

    Raises:
        Whatever ``plate_api.lookup_plate`` raises; the page turns it into a
        note.
    """
    if plate_api is None:
        return []
    record = plate_api.lookup_plate(plate_id)
    notes = (record or {}).get("notes") or []
    newest: dict = {}
    for position, raw in enumerate(notes):
        underlay = parse_note(raw)
        if underlay is None:
            continue
        # A tie on created_at goes to the later note in the list.
        rank = (_created_ts(underlay.created_at), position)
        key = (underlay.input_png, underlay.variant)
        if key not in newest or rank > newest[key][0]:
            newest[key] = (rank, underlay)
    return sorted(
        (underlay for _, underlay in newest.values()),
        key=lambda u: (
            _rank(u.state, STATE_ORDER),
            _rank(u.variant, VARIANT_ORDER),
            u.input_png,
        ),
    )


def split_s3_uri(uri: str) -> tuple:
    """``("bucket", "key")`` from ``s3://bucket/key``.

    Raises:
        ValueError: When *uri* names no bucket or no key.
    """
    bucket, _, key = uri.removeprefix("s3://").partition("/")
    if not uri.startswith("s3://") or not bucket or not key:
        raise ValueError(f"not an s3://<bucket>/<key> uri: {uri!r}")
    return bucket, key


def load_image(plate_api, underlay: Underlay, max_px: int = UNDERLAY_MAX_PX):
    """The photo as a read-only ``(rows, cols, 4)`` uint8 RGBA array.

    Fetched with the plate API's own credentialed loader and downsampled with
    an area filter so the longer edge is at most *max_px* (never upscaled).
    Cached per ``(plate_api, image_s3_uri, max_px, created_at)``, so a redraw never
    refetches; a failure is not cached, so the next redraw retries.

    Raises:
        RuntimeError: When the plate API has no credentials loaded.
        Whatever the fetch or the decode raises.
    """
    # created_at is in the key: a re-post overwrites the same S3 key.
    return _fetch_rgba(
        plate_api, underlay.image_s3_uri, int(max_px), underlay.created_at
    )


@functools.lru_cache(maxsize=IMAGE_CACHE_SIZE)
def _fetch_rgba(plate_api, uri: str, max_px: int, created_at: str) -> np.ndarray:
    loader = getattr(plate_api, "loader", None)
    if loader is None:
        raise RuntimeError("the plate API has no credentials loaded")
    bucket, key = split_s3_uri(uri)
    with Image.open(loader.get_bytes(bucket, key)) as img:
        rgba = img.convert("RGBA")
    rgba.thumbnail((max_px, max_px), Image.Resampling.BOX)
    array = np.array(rgba, dtype=np.uint8)
    # Shared by every caller through the cache, so no caller may edit it.
    array.setflags(write=False)
    return array
