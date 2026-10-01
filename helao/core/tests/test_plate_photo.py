"""Tests for the wafer-photo plate notes: parse, pick, fetch (no app needed)."""

import io

import numpy as np
import pytest
from PIL import Image, UnidentifiedImageError

from helao.core.tests._plate_photo_fakes import (
    FakeLoader,
    FakePlateAPI,
    note,
    png_bytes,
    serving,
)
from helao.ui.shared import plate_photo


@pytest.fixture(autouse=True)
def _fresh_cache():
    plate_photo._fetch_rgba.cache_clear()
    yield
    plate_photo._fetch_rgba.cache_clear()


def test_parse_note_reads_the_json_after_the_first_newline():
    u = plate_photo.parse_note(
        note(
            input_png="a.png",
            variant="raw",
            state="asdep",
            extent=((-1.0, 2.0), (-3.0, 4.0)),
        )
    )
    assert u is not None
    assert u.key == "a.png|raw"
    assert u.label == "asdep raw (a.png)"
    assert (u.state, u.variant, u.input_png) == ("asdep", "raw", "a.png")
    assert u.extent == ((-1.0, 2.0), (-3.0, 4.0))
    assert u.image_s3_uri == "s3://example-bucket/a.png.raw.png"
    assert u.created_at == "2026-09-30T12:00:00Z"


@pytest.mark.parametrize(
    "bad",
    [
        note(kind="something_else"),
        {"text": "operator says: film looks hazy", "image_s3_uri": ""},
        {"text": "header\n{not json", "image_s3_uri": "s3://example-bucket/k.png"},
        {"text": "header\n[1, 2]", "image_s3_uri": "s3://example-bucket/k.png"},
        {**note(), "image_s3_uri": None},
        note(extent=((5.0, 1.0), (0.0, 1.0))),
        "not a dict",
    ],
    ids=[
        "other-kind",
        "plain-text",
        "malformed-json",
        "json-not-object",
        "no-image",
        "inverted-extent",
        "not-a-dict",
    ],
)
def test_parse_note_rejects_everything_but_a_wafer_photo(bad):
    assert plate_photo.parse_note(bad) is None


def test_underlays_keep_the_newest_note_per_input_png_and_variant():
    """Newest wins whichever end of the list it sits at: pair A's newer note
    comes first, pair B's last, so neither keep-first nor keep-last passes."""
    notes = [
        note(
            input_png="a.png",
            variant="raw",
            created_at="2026-09-30T12:00:05Z",
            uri="s3://example-bucket/a-new.png",
        ),
        note(
            input_png="a.png",
            variant="raw",
            created_at="2026-09-30T12:00:00Z",
            uri="s3://example-bucket/a-old.png",
        ),
        note(
            input_png="b.png",
            variant="raw",
            created_at="2026-09-30T11:00:00Z",
            uri="s3://example-bucket/b-old.png",
        ),
        note(
            input_png="b.png",
            variant="raw",
            created_at="2026-09-30T11:00:09Z",
            uri="s3://example-bucket/b-new.png",
        ),
    ]
    found = plate_photo.underlays_for(FakePlateAPI(notes), 10197)
    assert sorted(u.image_s3_uri for u in found) == [
        "s3://example-bucket/a-new.png",
        "s3://example-bucket/b-new.png",
    ]


def test_underlays_order_by_state_then_variant_then_input_png():
    spec = [
        ("b.png", "raw", "preanneal"),
        ("a.png", "raw", "asdep"),
        ("c.png", "stretched", "postanneal"),
        ("c.png", "raw", "postanneal"),
        ("a.png", "stretched", "asdep"),
        ("b.png", "stretched", "postanneal"),
    ]
    notes = [note(input_png=p, variant=v, state=s) for p, v, s in spec]
    labels = [u.label for u in plate_photo.underlays_for(FakePlateAPI(notes), 1)]
    assert labels == [
        "postanneal stretched (b.png)",
        "postanneal stretched (c.png)",
        "postanneal raw (c.png)",
        "asdep stretched (a.png)",
        "asdep raw (a.png)",
        "preanneal raw (b.png)",
    ]


def test_underlays_are_empty_without_an_api_a_plate_or_a_photo_note():
    plain = {"text": "plain words", "image_s3_uri": ""}
    assert plate_photo.underlays_for(None, 1) == []
    assert plate_photo.underlays_for(FakePlateAPI([]), 1) == []
    assert plate_photo.underlays_for(FakePlateAPI([note()], found=False), 1) == []
    assert plate_photo.underlays_for(FakePlateAPI([plain]), 1) == []


def test_underlays_let_an_api_error_propagate():
    with pytest.raises(RuntimeError, match="HTTP 503"):
        plate_photo.underlays_for(FakePlateAPI(error=RuntimeError("HTTP 503")), 1)


def _only(api):
    return plate_photo.parse_note(api.notes[0])


def test_load_image_is_rgba_uint8_with_the_long_edge_at_most_max_px():
    api = serving(np.full((600, 1000, 4), 200, dtype=np.uint8))
    rgba = plate_photo.load_image(api, _only(api), max_px=512)
    assert rgba.dtype == np.uint8
    assert rgba.shape == (307, 512, 4)


def test_load_image_never_upscales_and_gives_an_rgb_photo_opaque_alpha():
    entry = note()
    buf = io.BytesIO()
    Image.new("RGB", (100, 80), (10, 20, 30)).save(buf, "PNG")
    api = FakePlateAPI(
        [entry], loader=FakeLoader({entry["image_s3_uri"]: buf.getvalue()})
    )
    rgba = plate_photo.load_image(api, _only(api), max_px=512)
    assert rgba.shape == (80, 100, 4)
    assert (rgba[..., 3] == 255).all()


def test_load_image_downsamples_with_an_area_filter():
    """Alternating black and white columns average to grey under an area
    filter; nearest-neighbour would keep only one of the two."""
    img = np.zeros((2, 1024, 4), dtype=np.uint8)
    img[..., 3] = 255
    img[:, ::2, :3] = 255
    api = serving(img)
    rgba = plate_photo.load_image(api, _only(api), max_px=512)
    assert rgba.shape == (1, 512, 4)
    assert (np.abs(rgba[..., 0].astype(int) - 128) <= 1).all()


def test_load_image_caches_so_a_redraw_never_refetches():
    api = serving(np.zeros((4, 4, 4), dtype=np.uint8))
    first = plate_photo.load_image(api, _only(api))
    second = plate_photo.load_image(api, _only(api))
    assert len(api.loader.calls) == 1
    assert second is first
    assert not first.flags.writeable
    plate_photo.load_image(api, _only(api), max_px=2)
    assert len(api.loader.calls) == 2  # max_px is part of the key


def test_a_reposted_photo_at_the_same_uri_is_refetched():
    """S3 keys are deterministic and overwritten on re-post, so created_at keys it."""
    api = serving(np.zeros((4, 4, 4), dtype=np.uint8))
    same = plate_photo.parse_note(note(created_at="2026-09-30T12:00:00Z"))
    again = plate_photo.parse_note(note(created_at="2026-09-30T12:00:00Z"))
    newer = plate_photo.parse_note(note(created_at="2026-10-01T09:00:00Z"))
    plate_photo.load_image(api, same)
    plate_photo.load_image(api, again)
    assert len(api.loader.calls) == 1
    plate_photo.load_image(api, newer)
    assert len(api.loader.calls) == 2


@pytest.mark.parametrize(
    "loader, error",
    [
        (FakeLoader(error=OSError("access denied")), OSError),
        (None, RuntimeError),
    ],
    ids=["fetch-fails", "no-credentials"],
)
def test_load_image_lets_errors_propagate_and_does_not_cache_them(loader, error):
    api = FakePlateAPI([note()], loader=loader)
    with pytest.raises(error):
        plate_photo.load_image(api, _only(api))
    with pytest.raises(error):
        plate_photo.load_image(api, _only(api))
    if loader is not None:
        assert len(loader.calls) == 2


def test_load_image_lets_a_decode_error_propagate():
    entry = note()
    api = FakePlateAPI(
        [entry], loader=FakeLoader({entry["image_s3_uri"]: b"not a png"})
    )
    with pytest.raises(UnidentifiedImageError):
        plate_photo.load_image(api, _only(api))


def test_split_s3_uri():
    assert plate_photo.split_s3_uri("s3://bkt/a/b.png") == ("bkt", "a/b.png")
    for bad in ("s3://bkt", "s3:///key", "https://bkt/key"):
        with pytest.raises(ValueError):
            plate_photo.split_s3_uri(bad)


def test_png_fixture_round_trips():
    """Guards the fake itself: a broken encoder would make every test above
    vacuous."""
    img = np.arange(48, dtype=np.uint8).reshape(2, 6, 4)
    with Image.open(io.BytesIO(png_bytes(img))) as back:
        assert np.array_equal(np.asarray(back.convert("RGBA")), img)
