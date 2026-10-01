"""Fakes shared by the plate-photo tests: a plate API, its loader, PNG bytes.

Not a test module (no ``test_`` prefix), so ``run_tests.py`` does not sweep it.
"""

import io
import json

import numpy as np
from PIL import Image

#: An extent like a real wafer's: y runs below 0, past the flat chord.
EXTENT = ((-50.0, 50.0), (-10.0, 90.0))


def png_bytes(rgba) -> bytes:
    """*rgba* (``(rows, cols, 4)`` uint8) encoded as a PNG."""
    buf = io.BytesIO()
    Image.fromarray(np.asarray(rgba, dtype=np.uint8), "RGBA").save(buf, "PNG")
    return buf.getvalue()


def top_row_red(rows: int = 8, cols: int = 6) -> np.ndarray:
    """Transparent black except an opaque red top row: a flip moves the red."""
    img = np.zeros((rows, cols, 4), dtype=np.uint8)
    img[0] = (255, 0, 0, 255)
    return img


def note(
    input_png: str = "102250_x_postanneal.png",
    variant: str = "stretched",
    state: str = "postanneal",
    created_at: str = "2026-09-30T12:00:00Z",
    uri: str = "",
    extent=EXTENT,
    kind: str = "wafer_photo_circle_crop",
) -> dict:
    """A plate note in the converter's format."""
    meta = {
        "kind": kind,
        "variant": variant,
        "input_png": input_png,
        "state": state,
        "sequence_uuid": None,
        "mm_per_px": 0.1,
        "crop_bbox_px": [0, 0, 10, 10],
        "extent_mm": {"x": list(extent[0]), "y": list(extent[1])},
    }
    return {
        "text": f"wafer photo {state} {variant}\n{json.dumps(meta)}",
        "image_s3_uri": uri or f"s3://example-bucket/{input_png}.{variant}.png",
        "created_at": created_at,
    }


class FakeLoader:
    """Serves ``s3://`` uris from a dict, counting every fetch."""

    def __init__(self, blobs=None, error=None):
        self.blobs = dict(blobs or {})
        self.error = error
        self.calls: list = []

    def get_bytes(self, bucket, key):
        self.calls.append((bucket, key))
        if self.error is not None:
            raise self.error
        return io.BytesIO(self.blobs[f"s3://{bucket}/{key}"])


class FakePlateAPI:
    """``lookup_plate`` over a fixed note list; ``loader=None`` = no credentials."""

    def __init__(self, notes=(), *, loader="fake", error=None, found=True):
        self.notes = list(notes)
        self.loader = FakeLoader() if loader == "fake" else loader
        self.error = error
        self.found = found
        self.lookups: list = []

    def lookup_plate(self, plateid):
        self.lookups.append(plateid)
        if self.error is not None:
            raise self.error
        if not self.found:
            return None
        return {"plate_id": plateid, "notes": list(self.notes)}


def serving(rgba, **note_kwargs):
    """A plate API with one wafer-photo note whose image is *rgba*."""
    entry = note(**note_kwargs)
    loader = FakeLoader({entry["image_s3_uri"]: png_bytes(rgba)})
    return FakePlateAPI([entry], loader=loader)


class FakePhotoState:
    """Carries ``PlatePhotoState``'s vars; its methods are the mixin's own.

    Not an ``rx.State``: Reflex forwards attribute assignment on a real state
    to a session that does not exist outside a running app. On a mixin the
    ``@rx.event`` methods are still plain functions, so they bind directly.
    The reflex imports are lazy so importing this module has no side effects.
    """

    def __init__(self):
        import types

        from helao.ui.reflex import plate_photo as rpp
        from helao.ui.reflex import plots

        self.photo_options = [rpp.PHOTO_OFF]
        self.photo_choice = rpp.PHOTO_OFF
        self.photo_opacity = plots.UNDERLAY_OPACITY
        self.photo_note = ""
        self._photos = []
        self.redraws = 0
        for name in (
            "_load_photos",
            "_underlay_arg",
            "set_photo_choice",
            "set_photo_opacity",
        ):
            fn = getattr(rpp.PlatePhotoState, name)
            setattr(self, name, types.MethodType(fn, self))

    def _redraw_photo(self):
        self.redraws += 1


def render_nodes(component) -> list:
    """*component* and every descendant."""
    out = [component]
    for child in getattr(component, "children", []) or []:
        out.extend(render_nodes(child))
    return out


def bound_events(component) -> set:
    """``(node type, trigger, handler name)`` for every bound event."""
    found = set()
    for node in render_nodes(component):
        for trigger, chain in (getattr(node, "event_triggers", {}) or {}).items():
            for event in getattr(chain, "events", None) or []:
                found.add((type(node).__name__, trigger, event.handler.fn.__name__))
    return found
