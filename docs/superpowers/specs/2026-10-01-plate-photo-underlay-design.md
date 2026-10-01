# Plate-photo underlay for the Reflex x-y plate maps — design

Date: 2026-10-01. Status: approved (approach A, defaults below). Amended the
same day after planning: a per-panel byte budget for retained frames
(component 4), mixin placement through `SpectraPageState` (component 3), the
Task 0 stop rule, and the corrections listed at the end.

## Goal

Draw a plate's whole-wafer photo underneath the x-y plate-map scatter on the
four Reflex plate pages: Composition (`/composition`), UV-Vis (`/uvvis`), XRD
(`/xrds`) and XAFS (`/xafs`). Seeing the photo and the measurement map
together lets an operator check whether a weak-signal patch, such as near-flat
XRD, sits on visibly delaminated film or on intact film.

## The data contract (already in production)

A private deployment's wafer-photo converter posts two **plate notes** per
photo through the plate-management API. The plate record
(`HTEPlateAPI.lookup_plate(plate_id)`, i.e. `GET /live/plate/id/{id}`) embeds
them in `notes[]`, each with `text` and `image_s3_uri`. A note belongs to this
feature when its text parses as:

```
<one human-readable line>\n<JSON object>
{"kind": "wafer_photo_circle_crop", "variant": "raw" | "stretched",
 "input_png": str, "state": "preanneal" | "asdep" | "postanneal",
 "sequence_uuid": str | null, "mm_per_px": float,
 "crop_bbox_px": [x_lo, y_lo, x_hi, y_hi],
 "extent_mm": {"x": [x_min, x_max], "y": [y_min, y_max]}}
```

- The image is an RGBA PNG: transparent outside the wafer and below its flat
  chord.
- `extent_mm` gives the image's outer edges on platemap mm axes. The image's
  top-left corner sits at `(x_min, y_max)`. The extent is pixel-centre
  consistent with the sample mapping, so a sample's photo pixel lands on its
  own x/y. y runs below 0, because the circle extends past the flat chord at
  y = 0.
- **Duplicates exist.** Note creation is asynchronous, so a fast re-run can
  post a variant twice, and the API has no delete. Take the **newest note per
  `(input_png, variant)`**, newest by `created_at`.
- A plate can have more than one photo: different `state`, or a re-photo with
  a different `input_png`.
- The image bytes are read with the plate API's own credentialed loader,
  `HTEPlateAPI.loader.get_bytes(bucket, key)`. This path was verified readable
  on 2026-10-01. `image_s3_uri` is `s3://<bucket>/<key>`.

## Approach (A): an xy truecolor heatmap trace

xy 0.0.7's `heatmap(z, x=, y=, opacity=)` accepts an `(rows, cols, 4)` array
and draws it as an RGBA texture (`truecolor`). `x`/`y` are **cell centres**,
and xy derives the edges from them. Prepending that trace to the plate-map
marks draws the photo underneath the points. It travels through the existing
`/xy/buffers` route, so there is no JS, shim or patch work. The bundle stamp
moves with the edited modules and rebuilds itself. A photo frame is about
4 MiB, so the buffer store bounds what it retains per panel by bytes as well as
by count (component 4).

Rejected:
- **(B) a CSS background `<img>`** must track xy's internal plot rectangle
  (padding, colorbar room, zoom), so it misaligns silently.
- **(C) a custom shim layer** means JS on a pre-1.0 library, plus bundle churn.

## Components

### 1. `helao/ui/shared/plate_photo.py` (new; no reflex or xy imports)

- `Underlay`: a frozen dataclass with these fields:
  - `key` (stable id, e.g. `"<input_png>|<variant>"`) and `label` (e.g.
    `"postanneal stretched (102250_CuEuTaO_postanneal.png)"`)
  - `state`, `variant`, `input_png`, `created_at`
  - `extent` (`((x_min, x_max), (y_min, y_max))`)
  - `image_s3_uri`
- `parse_note(note: dict) -> Underlay | None`: the JSON after the first
  newline, else `None`. Notes of any other kind, plain-text notes and
  malformed JSON all give `None`.
- `underlays_for(plate_api, plate_id) -> list[Underlay]`:
  - Reads `lookup_plate(plate_id)["notes"]`, parses them, keeps the newest per
    `(input_png, variant)`, and orders them for the dropdown.
  - Order: by state (`postanneal`, then `asdep`, then `preanneal`), then by
    variant (`stretched` before `raw`), then by `input_png`.
  - No notes, or no plate API, returns `[]`.
  - API errors propagate; the page turns them into a muted note.
- `load_image(plate_api, underlay, max_px=UNDERLAY_MAX_PX) -> np.ndarray`:
  - Fetches the bytes, decodes them with PIL (always present via matplotlib),
    and converts to RGBA `uint8`.
  - Downsamples with an area filter, so the longer edge is at most `max_px`.
  - Results are cached per `(image_s3_uri, max_px)` in a small module-level
    LRU, so a redraw never refetches.
- `UNDERLAY_MAX_PX = 512` is the approved default. **Task 0 measures the
  per-redraw payload.** xy ingests each RGBA channel as float64 in Python but
  publishes f32, so a 512² photo is 4,194,304 B of planes and the whole frame
  4,194,400 B (measured), sent again on every redraw. Task 0 stops, and the
  implementer reports the numbers rather than picking a new value, only if
  the frame is over 8 MiB at 512 px or a correctness check fails.

### 2. `plots.scatter_map(..., underlay=None, underlay_opacity=0.6)`

`underlay` is `(rgba, extent)` or `None`. When given:
- Divide all four channels by 255 first. xy divides RGB by 255 only when it
  sees a value above 1, and **never divides alpha**: handed the uint8 image,
  every partial alpha would clip to opaque.
- Flip the rows (image row 0 is the top, xy rows go upward). Pass cell-centre
  coordinates:
  - `x_i = x_min + (i + 0.5)·(x_max − x_min)/cols`
  - `y_j = y_min + (j + 0.5)·(y_max − y_min)/rows`
- Prepend `xy.heatmap(rgba_flipped, x=..., y=..., opacity=underlay_opacity,
  name="photo")` as `marks[0]`, so it draws first, underneath.
- `_square_domain` covers the points **and** the extent rectangle, so the
  wafer is never clipped.
- `layout_extra` gains the underlay identity (key, shape, opacity). A new
  photo or opacity therefore forces a rebuild rather than an in-place column
  swap. The "key" is a content digest of the image, because `underlay` carries
  no key, and raw and stretched variants share shape and extent.
- `_publish_selectable` takes the identity as a new `extra_token=""` argument.
  It also serves `ternary`, which keeps calling it without one.
- Clicks are unchanged. Both pages snap a click to the nearest plotted sample.
- `underlay=None` must give a byte-identical spec and layout token to today.
  That covers a third caller beyond the two `_draw_map`s: the operator's
  plate map (`helao/ui/reflex/operator.py`, `plots.scatter_map`), which never
  passes an underlay.

Only `plots.py` and `xy_component.py` (plus their two test modules) may
import `xy`; `test_reflex_config.py` enforces this over every `*.py` in the
checkout, so probe scripts live outside it.

### 3. Page state: `PlatePhotoState` (a Reflex mixin, `mixin=True`)

It lives in `helao/ui/reflex/plate_photo.py`. Per the mixin rule in
`helao/ui/reflex/CLAUDE.md` it is never mixed into a concrete base.
- `CompositionState` mixes it in directly:
  `class CompositionState(PlatePhotoState, rx.State)`.
- `SpectraPageState`, itself a mixin, inherits it:
  `class SpectraPageState(PlatePhotoState, rx.State, mixin=True)`. This is the
  `LiveVisState(VisPanelState, mixin=True)` pattern. `UvvisState`, `XrdsState`
  and `XafsState` keep their bases and carry the photo through it.
- Each concrete page still owns its copy of the vars (`photo_choice` on
  `/uvvis` is not the one on `/xrds`). Task 0's probe and a page test both
  check this.
- The mixin's `_redraw_photo` default raises. `CompositionState` and
  `SpectraPageState` each override it, so a page that forgets fails on first
  use rather than drawing nothing.
- Vars:
  - `photo_options: list[str]` (labels, `"off"` first)
  - `photo_choice: str = "off"` (the default: plots unchanged until chosen)
  - `photo_opacity: float = 0.6`
  - `photo_note: str = ""`
  - backend-only `_photos: list` (`Underlay`)
- `_load_photos(plate_id)`, called from each page's `retrieve`, next to
  `platemap_for`. It resets the choice to `"off"`, fills the options, and puts
  any error in `photo_note`. It must not fail `retrieve`.
- `_underlay_arg()` returns `(rgba, extent)` for the current choice, or
  `None`. A failed image fetch sets `photo_note`, falls back to `None`, and
  leaves the map drawn without a photo.
- `set_photo_choice` and `set_photo_opacity` redraw the map through the page's
  existing map-redraw path.
- `photo_controls(S)`: a select plus an opacity slider (0–1), and the muted
  `photo_note`. It is placed beside the existing map controls (composition's
  "RBF interpolate" row; the spectra page's map controls).
- The two `_draw_map` call sites pass `underlay=self._underlay_arg()` and
  `underlay_opacity=self.photo_opacity`.

### 4. Retained frames: a per-panel byte budget

`xy_component.BufferStore` keeps recent frames per panel so a fetch of version
N still lands while N+1 is published. `FRAME_HISTORY = 512` was its only
bound: tens of KB per live frame, a few MB per chart. A photo frame is about
4 MiB, and the composition map redraws on every sample click (the spectra maps
on every click, window or point-size change). One open map tab could therefore
hold about 2 GiB (83,888,000 B measured after 20 redraws).
- After appending, `put` evicts the oldest frames while the panel's total
  encoded bytes exceed `FRAME_BUDGET_BYTES = 32 * 1024 * 1024`.
- It always keeps at least the newest `FRAME_MIN_KEEP = 4` frames, even over
  budget.
- `FRAME_HISTORY = 512` stays as the count cap, and its comment now names the
  byte budget as the memory bound and says why.
- A live stream of tens-of-KB frames still keeps all 512. A real photo frame
  (4,194,400 B) keeps `33,554,432 // 4,194,400 = 7`. Map redraws follow
  clicks rather than a 60 Hz tick, so seven versions is ample.

### 5. Out of scope

- The plate-crop viewer page (whole-wafer crops beside the per-sample crops)
  is the next, separate task.
- Overlaying XRD flatness metrics on the photo is analysis, not UI.

## Error handling

| Condition | Behaviour |
|---|---|
| No plate API configured or no credentials | Options are `["off"]`, plus a muted note (same wording family as `platemap_for`) |
| Plate has no circle-crop notes | Options are `["off"]`, plus the note "no wafer photo notes on this plate" |
| `lookup_plate` raises | Options are `["off"]`; the note gives the error; the rest of `retrieve` proceeds |
| Image fetch or decode fails | The map draws without a photo; the note names the photo and the error |
| No platemap rows | The map is not drawn (today's behaviour); the photo is irrelevant |

## Testing

- **Task 0 (probe, before any production code).** A throwaway script plus a
  headless Playwright check, `goldenreflex`-style, on a fixture:
  - xy truecolor heatmap plus scatter in one square chart.
  - Confirm alpha-0 pixels are see-through, the image is not vertically
    flipped (use an asymmetric fixture), cell-centre placement is correct, and
    clicks still resolve to points.
  - Measure the per-redraw frame bytes at 512 px, and the bytes retained after
    20 redraws.
  - Confirm the mixin shapes on all four pages: direct on composition, and
    through a mixin that inherits the mixin on the three spectra pages, with
    each concrete page owning its own `photo_choice`.
  - Report the findings, then continue. Stop only if the frame is over 8 MiB at
    512 px or a correctness check fails.
- **`BufferStore` tests** (`helao/core/tests/test_reflex_xy_component.py`):
  - a live-sized stream (32 KiB frames) still keeps 512 frames;
  - 4 MiB frames keep `FRAME_BUDGET_BYTES // frame` (7) of the newest;
  - an oversize frame stream keeps the newest 4;
  - `get()` of an evicted version is `None`;
  - the newest version is always retrievable.
- **`plate_photo` unit tests:** fake API and loader. Cover parse
  (good/other-kind/plain/malformed), newest-per-`(input_png, variant)` (the
  duplicate case), ordering, downsample bounds, the cache hit (no second
  fetch), and error propagation.
- **`plots` tests:**
  - `underlay=None` is byte-identical to today.
  - With an underlay, the heatmap is trace 0 with truecolor, and its x/y
    range equals the extent.
  - The domain contains the extent, and the layout token changes with
    opacity or photo.
  - An asymmetric fixture pixel's row lands at the correct y (falsifiable for
    the flip).
  - A half-transparent pixel's alpha arrives as 128/255, not 1.0 (the alpha
    trap).
- **Page tests:** render `build_page()` for each page (event-binding errors
  only appear at render). Today only composition's page is rendered by a
  test; `/uvvis`, `/xrds` and `/xafs` gain one each.
  - The existing state fakes in `test_reflex_composition.py`,
    `test_reflex_uvvis.py`, `test_xrds.py` and `test_xafs.py` bind
    `_draw_map` off the real classes. Once `_draw_map` reads
    `_underlay_arg()` and `photo_opacity`, each fake needs the photo vars and
    `_underlay_arg`.
  - Each page keeps exactly three charts: the photo is a trace, not a WebGL
    context.
  - `_load_photos` with fakes, including the no-notes and raise paths.
  - Choosing a photo redraws with an underlay; `"off"` redraws without.
- **Gates:** `helao/core/tests/test_reflex_config.py` (the xy-import rule),
  `test_palette.py` (no hardcoded colours), `test_reflex_xy_component.py`, and
  the existing composition and spectra page tests.
- **Visual:** a Playwright screenshot of `/xrds` for plate 10197 against the
  live API, when a station with internet is available. Otherwise use the
  fixture.

## Files

- New: `helao/ui/shared/plate_photo.py`, `helao/ui/reflex/plate_photo.py`, and
  tests beside the existing Reflex/shared tests (plus a non-test fakes module,
  `helao/core/tests/_plate_photo_fakes.py`).
- Edited:
  - `helao/ui/reflex/xy_component.py` (`FRAME_BUDGET_BYTES`,
    `FRAME_MIN_KEEP`, `BufferStore.put`, the `FRAME_HISTORY` comment)
  - `helao/ui/reflex/plots.py` (`scatter_map`, `_publish_selectable`,
    `_square_domain` caller)
  - `helao/ui/reflex/composition.py` (state bases, `retrieve`, `_draw_map`,
    `_map_panel`)
  - `helao/ui/reflex/spectra_page.py` (`SpectraPageState` bases,
    `_redraw_photo`, `_draw_map`, map controls)
  - `helao/ui/reflex/{uvvis,xrds,xafs}.py` (`retrieve` only)
  - `helao/ui/reflex/CLAUDE.md` (one bullet on the underlay and its traps)
  - Tests: `test_reflex_xy_component.py`, `test_reflex_plots.py`, the four
    existing page test modules' fakes, and `test_reflex_routes_e2e.py`'s
    handler lists

## Corrections recorded during planning (2026-10-01)

- **Payload.** The original "about 8 MB per redraw" was wrong. The published
  frame is f32: 4,194,304 B of photo planes, a 4,194,400 B frame at 512 px.
- **Retention.** `FRAME_HISTORY` alone let one map tab hold about 2 GiB of
  photo frames. Fixed by component 4.
- **Alpha.** xy never divides alpha by 255, and divides RGB only when a value
  exceeds 1, so `scatter_map` scales all four channels itself (component 2).
- **Callers.** `scatter_map` has a third caller (the operator's plate map in
  `operator.py`), and `_publish_selectable` also serves `ternary`. The
  byte-identical `underlay=None` test and the `extra_token=""` default cover
  both.
- **Test fakes.** The four existing page-test fakes must gain the photo vars
  and `_underlay_arg`; the original file list omitted them.
- **Render tests.** Only `/composition` had a `build_page()` render test;
  `/uvvis`, `/xrds` and `/xafs` gain one.
- **Mixin placement.** It goes through `SpectraPageState` rather than into each
  spectra page's bases (component 3). That removes two type-ignores and a
  load-bearing base order.
