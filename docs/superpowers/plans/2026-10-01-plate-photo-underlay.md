# Plate-photo underlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Draw a plate's whole-wafer photo underneath the x-y plate-map scatter on `/composition`, `/uvvis`, `/xrds` and `/xafs`, chosen from a dropdown that defaults to `off`.

**Architecture:** A dependency-free shared module (`helao/ui/shared/plate_photo.py`) parses the plate record's `wafer_photo_circle_crop` notes, keeps the newest per `(input_png, variant)`, and fetches and downsamples the RGBA PNG through the plate API's own loader. `plots.scatter_map(underlay=(rgba, extent))` prepends the photo as an xy truecolor `heatmap` (trace 0), so it travels through the existing `/xy/buffers` route with no JS work. Because a photo frame is about 4 MiB, `xy_component.BufferStore` first gains a per-panel byte budget (32 MiB, never fewer than the newest 4 frames). A Reflex mixin (`helao/ui/reflex/plate_photo.py`) holds the dropdown, the opacity slider and the note. `CompositionState` mixes it in directly; `SpectraPageState` mixes it into itself as a mixin of a mixin (the `LiveVisState` pattern), so `UvvisState`, `XrdsState` and `XafsState` get it without base edits, and each concrete page still owns its own vars.

**Tech Stack:** Python 3.14 (`helao` conda env), Reflex 0.9.x, xy 0.0.7, Pillow 12.3 (already in the env), numpy, pytest, Playwright (headless chromium, in the env).

**Spec:** `/mnt/STORAGE/repos/helao/helao-underlay/docs/superpowers/specs/2026-10-01-plate-photo-underlay-design.md` (approved; approach A). Read it before starting any task.

## Global Constraints

- **Worktree only.** Work in `/mnt/STORAGE/repos/helao/helao-underlay` on branch `feat/plate-photo-underlay` (from `unstable` cec43b68). Never write into `/mnt/STORAGE/repos/helao/helao-async`.
- **Every python/pytest command** runs as `cd /mnt/STORAGE/repos/helao/helao-underlay && conda run -n helao env PYTHONPATH=/mnt/STORAGE/repos/helao/helao-underlay python ...`. The env pins `PYTHONPATH` to the main checkout; without the override the tests silently test the wrong tree. `conda run` drops stdin, so never pipe a heredoc into python: write a script file and run it.
- **One pytest file per process**: `... python -m pytest -q -p no:cacheprovider <one file>`. The suite hangs when collected as one session.
- **No git writes by any subagent, ever:** no `git add`, `commit`, `push`, `stash`, `checkout`, `reset`, `branch`. Read-only git uses `git -C <repo>`. The controller commits.
- **Public repo:** never name a private deployment or a real bucket. Test fakes use `example-bucket`.
- **Colours:** none hardcoded anywhere outside `helao/ui/shared/palette.py` (`helao/core/tests/test_palette.py` sweeps `helao/ui/**`). Muted text is `reflex_muted_text_class()`.
- **xy imports:** only `helao/ui/reflex/plots.py`, `helao/ui/reflex/xy_component.py`, `test_reflex_plots.py` and `test_reflex_xy_component.py` may `import xy` (`test_reflex_config.py::test_only_plots_module_imports_xy` sweeps the whole worktree for `*.py`). Throwaway probe scripts therefore live under `/tmp`, never in the repo.
- **Mixin rule:** `PlatePhotoState` is `rx.State, mixin=True`. It is mixed into `CompositionState` and into the `SpectraPageState` mixin (`class SpectraPageState(PlatePhotoState, rx.State, mixin=True)`), never into a concrete base (`helao/ui/reflex/CLAUDE.md`).
- **Approved defaults (spec):** `UNDERLAY_MAX_PX = 512`; opacity `0.6`; photo choice `"off"` (maps unchanged until chosen); `underlay=None` gives a byte-identical spec and layout token.
- **Formatting:** `conda run -n helao black <changed files>` right before each commit. Never run black on `helao/core/tests/fixtures/sweeper_calibration/`.
- **pyright:** `cd /mnt/STORAGE/repos/helao/helao-underlay && conda run -n helao pyright --pythonpath /home/dan/miniforge3/envs/helao/bin/python --outputjson <files>`; report `filesAnalyzed` with `errorCount`. `filesAnalyzed` must equal the number of files passed (0 means a vacuous pass). There is no `pyrightconfig.json` in the repo, so pyright runs with its defaults.
- **Escalate, don't choose.** If a step's expected output does not match, or a decision is not settled here, stop and report to the controller.

## Decisions taken where the spec reads two ways

Each is the plan's reading. The controller accepted all of them on 2026-10-01.

1. **Layout-token identity of the photo.** The spec gives `scatter_map` an `underlay` of `(rgba, extent)` with no key, but asks for "key, shape, opacity" in the token. The token uses a content digest (`blake2b` of the uint8 image, 8 bytes) as the key, plus shape, extent and opacity. Raw and stretched variants have the same shape and extent, so shape alone would not force a rebuild.
2. **Image cache key** is `(plate_api, image_s3_uri, max_px)` via `functools.lru_cache(maxsize=8)`. The plate API is a process singleton (`platemap._PLATE_API_CACHE`), so this equals the spec's `(image_s3_uri, max_px)` in production.
3. **The opacity slider redraws on release** (`on_value_commit`), as the point-size slider does, because each redraw republishes the photo.
4. **Placement on the spectra pages:** they have no map-controls row, so `photo_controls(S)` is a row directly above the chart row in `spectra_page.charts(S)`. On composition it sits in the "RBF interpolate" row, as the spec says.
5. **Redraw paths:** composition bumps `version` and calls `_redraw_charts()` (map plus the composition chart, the same path the point-size slider uses). The spectra pages call `_redraw()` (all three charts). Both keep the selection.
6. **`_load_photos(plate_id)` runs inside each `retrieve`'s `async with self:` block**, next to `self.platemap_note = note`, because it assigns state. `lookup_plate` is a blocking call, like `platemap_for`'s, so holding the lock costs nothing extra: the event loop is blocked either way.
7. **"No credentials"** is detected as `plate_api.loader is None`, not via `has_access`, which costs an STS round trip and reports legacy access when there is no loader.
8. **`created_at`** is parsed with `datetime.fromisoformat`. Unparsable sorts oldest, and a tie goes to the later note in the list. Task 0 checks the live field when credentials are present.
9. A choice not in `photo_options` falls back to `"off"`. A failed fetch keeps the choice, and the next redraw retries, because failures are not cached.

## Escalations, resolved by the controller on 2026-10-01

- **E1. Server memory.** `xy_component.FRAME_HISTORY = 512` frames were the only bound per panel, and the panel id is per browser session. A photo frame is about 4 MiB, so the worst case was about 2 GiB per open map tab (83,888,000 B measured after 20 redraws). **Resolved by Task 2:** a per-panel byte budget, `FRAME_BUDGET_BYTES = 32 * 1024 * 1024`, never keeping fewer than the newest `FRAME_MIN_KEEP = 4` frames. `FRAME_HISTORY` stays as the count cap. A real photo frame is 4,194,400 B (4 MiB of planes plus header and the scatter), so the budget keeps **7** of them, not 8.
- **E2. Payload size.** The spec's "about 8 MB per redraw" was wrong: xy publishes f32, so a 512 px frame is 4,194,400 B. **Resolved:** Task 0 stops only if the frame exceeds 8 MiB or a correctness check fails.
- **E3. Mixin placement. Resolved:** `class SpectraPageState(PlatePhotoState, rx.State, mixin=True)`, the `LiveVisState(VisPanelState, mixin=True)` pattern. `CompositionState` mixes `PlatePhotoState` in directly. There are no type-ignores and no base edits in `uvvis.py`, `xrds.py` or `xafs.py`. Task 0 confirms that a mixin inheriting a mixin still gives each concrete page its own `photo_choice`.

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `helao/ui/reflex/xy_component.py` | edit | `FRAME_BUDGET_BYTES`, `FRAME_MIN_KEEP`, byte-budget eviction in `BufferStore.put`; `FRAME_HISTORY` comment |
| `helao/core/tests/test_reflex_xy_component.py` | edit | byte-budget tests |
| `helao/ui/shared/plate_photo.py` | new | `Underlay`, `parse_note`, `underlays_for`, `load_image`, `split_s3_uri`. No reflex, no xy. |
| `helao/ui/reflex/plots.py` | edit | `UNDERLAY_OPACITY`, `scatter_map(underlay=, underlay_opacity=)`, `_underlay_mark`, `_publish_selectable(extra_token=)` |
| `helao/ui/reflex/plate_photo.py` | new | `PlatePhotoState` mixin, `photo_controls(S)`, `_plate_api()` |
| `helao/ui/reflex/composition.py` | edit | state bases, `_redraw_photo`, `retrieve`, `_draw_map`, `_map_panel` |
| `helao/ui/reflex/spectra_page.py` | edit | `SpectraPageState(PlatePhotoState, rx.State, mixin=True)`, `_redraw_photo`, `_draw_map`, `charts(S)` |
| `helao/ui/reflex/{uvvis,xrds,xafs}.py` | edit | `retrieve` only (one line each) |
| `helao/ui/reflex/CLAUDE.md` | edit | one bullet |
| `helao/core/tests/_plate_photo_fakes.py` | new | fake plate API, loader, PNG and note builders (no `test_` prefix, so not swept) |
| `helao/core/tests/test_plate_photo.py` | new | shared-module tests |
| `helao/core/tests/test_reflex_plots.py` | edit | underlay tests |
| `helao/core/tests/test_reflex_plate_photo.py` | new | mixin tests |
| `helao/core/tests/test_reflex_plate_photo_pages.py` | new | four-page render, ownership, MRO, retrieve tests |
| `helao/core/tests/test_reflex_composition.py`, `test_reflex_uvvis.py`, `test_xrds.py`, `test_xafs.py` | edit | existing fakes gain the photo vars; two new page tests |
| `helao/core/tests/test_reflex_routes_e2e.py` | edit | photo handlers in the registration lists |

---

### Task 0: Probe (throwaway; nothing committed, nothing written in the repo)

**Files:**
- Create: `/tmp/plate-photo-probe/probe_xy.py`, `/tmp/plate-photo-probe/probe_mixin.py`, `/tmp/plate-photo-probe/probe_notes.py`
- Nothing under `/mnt/STORAGE/repos/helao/` is touched.

**Interfaces:**
- Consumes: xy 0.0.7 (`xy.heatmap`, `xy.chart`, `Figure.to_html`), `helao.ui.reflex.xy_component.{BufferStore, encode_buffers}`, `reflex`.
- Produces: a measurement report to the controller. No code that later tasks import.

**STOP rule.** STOP if the per-redraw frame is > 8 MiB at 512 px, or if any correctness check fails (any line printing `FAIL`). Then send the controller the full stdout of all three scripts, and do not pick a new `UNDERLAY_MAX_PX`. Either way, report every `MEASURE` line. If nothing fails, continue to Task 1.

- [ ] **Step 1: Write the xy browser probe**

Create `/tmp/plate-photo-probe/probe_xy.py`:

```python
"""Throwaway Task 0 probe: xy truecolor heatmap under a scatter, in a browser."""

import io
import json
import pathlib
import sys

import numpy as np
import xy
from PIL import Image
from playwright.sync_api import sync_playwright

from helao.ui.reflex.xy_component import BufferStore, encode_buffers

OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/plate-photo-probe/out")
OUT.mkdir(parents=True, exist_ok=True)
FAILS = []


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'} {name} {detail}")
    if not ok:
        FAILS.append(name)


# ---- 1. payload bytes at 512 px -------------------------------------------
img512 = np.random.default_rng(0).integers(0, 256, (512, 512, 4), dtype=np.uint8)
z = np.flipud(img512).astype(np.float64) / 255.0
cx = (np.arange(512) + 0.5) * 0.2
fig = xy.chart(
    xy.heatmap(z, x=cx, y=cx, opacity=0.6, name="photo"),
    xy.scatter(x=np.array([1.0, 2.0]), y=np.array([1.0, 2.0])),
    click=True,
)
spec, bufs = fig.figure().build_payload_split()
photo_bytes = sum(bufs[i].nbytes for i in spec["traces"][0]["heatmap"]["rgba_bufs"])
frame = encode_buffers(bufs)
print(f"MEASURE photo_buffer_bytes_512={photo_bytes} frame_bytes_512={len(frame)}")
store = BufferStore()
for v in range(20):
    store.put("probe", v, bufs)
retained = sum(len(p) for _, p in store._frames["probe"])
print(f"MEASURE retained_bytes_after_20_redraws={retained}")
check(
    "per-redraw frame <= 8 MiB at 512 px",
    len(frame) <= 8 * 1024 * 1024,
    str(len(frame)),
)

# ---- 2. asymmetric fixture in a square chart ------------------------------
# 12 rows x 16 cols. Image top half: left red, right green. Bottom half: left
# blue, right fully transparent. Extent x 0..64, y -8..40 (cells 4 mm square).
rows, cols = 12, 16
img = np.zeros((rows, cols, 4), dtype=np.uint8)
img[: rows // 2, : cols // 2] = (255, 0, 0, 255)
img[: rows // 2, cols // 2 :] = (0, 160, 0, 255)
img[rows // 2 :, : cols // 2] = (0, 0, 255, 255)
img[rows // 2 :, cols // 2 :] = (0, 0, 0, 0)
(x0, x1), (y0, y1) = (0.0, 64.0), (-8.0, 40.0)
xc = x0 + (np.arange(cols) + 0.5) * (x1 - x0) / cols
yc = y0 + (np.arange(rows) + 0.5) * (y1 - y0) / rows
z = np.flipud(img).astype(np.float64) / 255.0
half = 40.0  # square domain wider than the extent on every side
dom_x, dom_y = (32.0 - half, 32.0 + half), (16.0 - half, 16.0 + half)
chart = xy.chart(
    xy.heatmap(z, x=xc, y=yc, opacity=0.6, name="photo"),
    xy.scatter(
        x=np.array([16.0, 48.0]), y=np.array([28.0, 4.0]), size=8.0, name="samples"
    ),
    xy.x_axis(label="x (mm)", domain=dom_x),
    xy.y_axis(label="y (mm)", domain=dom_y),
    xy.legend(show=False),
    width=640,
    height=520,
    padding=[12, 116, 48, 64],
    click=True,
)
html = OUT / "probe.html"
chart.figure().to_html(str(html))

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 800, "height": 700})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(html.as_uri(), wait_until="load")
    page.wait_for_selector("canvas")
    page.wait_for_timeout(1500)
    page.evaluate(
        "window.__clicks = []; document.addEventListener('xy:click',"
        " e => window.__clicks.push(e.detail), true)"
    )
    box = page.locator("canvas").first.bounding_box()

    def click_data(px, py):
        page.mouse.click(px, py)
        page.wait_for_timeout(150)
        d = page.evaluate("window.__clicks[window.__clicks.length - 1] || null")
        return None if d is None else (d.get("x"), d.get("y"))

    # Two clicks fix the pixel <-> data mapping (linear on both axes).
    pa = (box["x"] + 0.30 * box["width"], box["y"] + 0.70 * box["height"])
    pb = (box["x"] + 0.60 * box["width"], box["y"] + 0.30 * box["height"])
    da, db = click_data(*pa), click_data(*pb)
    check(
        "click over the photo reports finite x/y",
        da is not None
        and db is not None
        and all(np.isfinite(v) for v in (*da, *db)),
        f"{da} {db}",
    )
    if da is None or db is None:
        print(json.dumps({"FAILS": FAILS + ["no clicks"], "errors": errors}))
        sys.exit(1)
    sx = (pb[0] - pa[0]) / (db[0] - da[0])
    sy = (pb[1] - pa[1]) / (db[1] - da[1])

    def to_px(x, y):
        return pa[0] + (x - da[0]) * sx, pa[1] + (y - da[1]) * sy

    shot = Image.open(io.BytesIO(page.screenshot())).convert("RGB")
    shot.save(OUT / "probe.png")

    def rgb(x, y):
        px, py = to_px(x, y)
        return shot.getpixel((int(round(px)), int(round(py))))

    def is_red(c):
        return c[0] > c[1] + 40 and c[0] > c[2] + 40

    bg = rgb(-20.0, 16.0)  # inside the plot, outside the extent
    red, green = rgb(6.0, 34.0), rgb(58.0, 34.0)
    blue, clear = rgb(6.0, -4.0), rgb(58.0, -4.0)
    print(f"MEASURE bg={bg} red={red} green={green} blue={blue} clear={clear}")
    check("not flipped: top-left is red", is_red(red))
    check("top-right is green", green[1] > green[0] + 40 and green[1] > green[2] + 40)
    check("bottom-left is blue", blue[2] > blue[0] + 40 and blue[2] > blue[1] + 40)
    check(
        "alpha 0 is see-through",
        max(abs(a - b) for a, b in zip(clear, bg)) <= 6,
        f"{clear} vs {bg}",
    )

    # Placement: scan along y=34 for the photo's left edge, and along x=6 for
    # its top edge. Edges passed as centres would shift them by half a cell
    # (2 mm, ~10 px here).
    def edge_x(y):
        for px in range(int(to_px(-10.0, y)[0]), int(to_px(10.0, y)[0])):
            if is_red(shot.getpixel((px, int(round(to_px(0, y)[1]))))):
                return da[0] + (px - pa[0]) / sx
        return None

    def edge_y(x):
        for py in range(int(to_px(x, 50.0)[1]), int(to_px(x, 30.0)[1])):
            if is_red(shot.getpixel((int(round(to_px(x, 0)[0])), py))):
                return da[1] + (py - pa[1]) / sy
        return None

    mm_per_px = abs(1.0 / sx)
    left, top = edge_x(34.0), edge_y(6.0)
    print(f"MEASURE left_edge={left} top_edge={top} mm_per_px={mm_per_px:.3f}")
    check("left edge at x_min", left is not None and abs(left - x0) <= 2 * mm_per_px)
    check("top edge at y_max", top is not None and abs(top - y1) <= 2 * mm_per_px)

    # A click on the transparent region still reports x/y.
    dc = click_data(*to_px(58.0, -4.0))
    check(
        "click on alpha-0 region reports x/y",
        dc is not None and abs(dc[0] - 58.0) < 2 and abs(dc[1] + 4.0) < 2,
        str(dc),
    )
    check("no page errors", not errors, str(errors))
    browser.close()

print(json.dumps({"FAILS": FAILS}))
sys.exit(1 if FAILS else 0)
```

- [ ] **Step 2: Run it**

Run: `cd /mnt/STORAGE/repos/helao/helao-underlay && conda run -n helao env PYTHONPATH=/mnt/STORAGE/repos/helao/helao-underlay python /tmp/plate-photo-probe/probe_xy.py /tmp/plate-photo-probe/out`

Expected (the planner's run on 2026-10-01, ignoring the INFO log lines):

```
MEASURE photo_buffer_bytes_512=4194304 frame_bytes_512=4194400
MEASURE retained_bytes_after_20_redraws=83888000
PASS per-redraw frame <= 8 MiB at 512 px 4194400
PASS click over the photo reports finite x/y ...
MEASURE bg=(255, 255, 255) red=(255, 102, 102) green=(102, 198, 102) blue=(102, 102, 255) clear=(255, 255, 255)
PASS not flipped: top-left is red
PASS top-right is green
PASS bottom-left is blue
PASS alpha 0 is see-through ...
MEASURE left_edge=0.0 top_edge=40.0... mm_per_px=0.174
PASS left edge at x_min
PASS top edge at y_max
PASS click on alpha-0 region reports x/y ...
PASS no page errors []
{"FAILS": []}
```

The probe is falsifiable: with `xc`/`yc` replaced by `np.linspace(x0, x1, cols)` (edges passed as centres) the planner measured `left_edge=-2.09 top_edge=42.26` and both placement checks FAIL. Look at `/tmp/plate-photo-probe/out/probe.png`: red top-left, green top-right, blue bottom-left, white bottom-right, two dots drawn over the photo.

- [ ] **Step 3: Write the mixin probe**

This probe mirrors the resolved E3 shape. `ProbeSpectraPage(PhotoProbe, rx.State, mixin=True)` stands in for `SpectraPageState(PlatePhotoState, rx.State, mixin=True)`, a mixin inheriting a mixin, and the three spectra probes subclass it as `X(ProbeSpectraPage, rx.State)`, as the real pages do.

Create `/tmp/plate-photo-probe/probe_mixin.py`:

```python
"""Throwaway Task 0 probe: the photo mixin on the four page shapes.

Composition mixes it in directly; the spectra pages get it through a mixin
that itself inherits it (SpectraPageState(PlatePhotoState, rx.State,
mixin=True), the LiveVisState pattern).
"""

import sys

import reflex as rx

FAILS = []
PHOTO_VARS = ("photo_options", "photo_choice", "photo_opacity", "photo_note")


class PhotoProbe(rx.State, mixin=True):
    photo_options: list[str] = ["off"]
    photo_choice: str = "off"
    photo_opacity: float = 0.6
    photo_note: str = ""
    _photos: list = []

    def _redraw_photo(self) -> None:
        raise NotImplementedError

    @rx.event
    def set_photo_choice(self, value: str):
        self.photo_choice = value
        self._redraw_photo()

    @rx.event
    def set_photo_opacity(self, value: list[float]):
        self.photo_opacity = float(value[0])


class ProbeSpectraPage(PhotoProbe, rx.State, mixin=True):
    """Shaped like the planned SpectraPageState: a mixin inheriting the mixin."""

    plate_id: str = ""
    redraws: int = 0

    def _redraw_photo(self) -> None:
        self.redraws += 1

    @rx.event
    def set_point_scale(self, value: list[float]):
        pass


class ProbeCompositionState(PhotoProbe, rx.State):
    plate_id: str = ""

    def _redraw_photo(self) -> None:
        pass


class ProbeUvvisState(ProbeSpectraPage, rx.State):
    pass


class ProbeXrdsState(ProbeSpectraPage, rx.State):
    pass


class ProbeXafsState(ProbeSpectraPage, rx.State):
    pass


STATES = (ProbeCompositionState, ProbeUvvisState, ProbeXrdsState, ProbeXafsState)
for cls in STATES:
    owned = all(v in cls.vars and v not in cls.inherited_vars for v in PHOTO_VARS)
    backend = "_photos" in cls.backend_vars
    handlers = {"set_photo_choice", "set_photo_opacity"} <= set(cls.event_handlers)
    redraw = cls._redraw_photo.__qualname__
    want = (
        "ProbeCompositionState._redraw_photo"
        if cls is ProbeCompositionState
        else "ProbeSpectraPage._redraw_photo"
    )
    ok = owned and backend and handlers and redraw == want
    print(
        f"{'PASS' if ok else 'FAIL'} {cls.__name__} owned={owned} backend={backend}"
        f" handlers={handlers} redraw={redraw}"
    )
    if not ok:
        FAILS.append(cls.__name__)

# Not shared: each concrete page's photo_choice is its own var, under its own
# state path, so choosing a photo on /uvvis cannot change /xrds.
paths = {str(cls.photo_choice) for cls in STATES}
print(f"MEASURE photo_choice_paths={sorted(paths)}")
ok = len(paths) == len(STATES)
print(f"{'PASS' if ok else 'FAIL'} no two pages share photo_choice")
if not ok:
    FAILS.append("photo_choice shared")
if len({cls.get_full_name() for cls in STATES}) != len(STATES):
    FAILS.append("full names collide")
print("FAILS", FAILS)
sys.exit(1 if FAILS else 0)
```

- [ ] **Step 4: Run it**

Run: `cd /mnt/STORAGE/repos/helao/helao-underlay && conda run -n helao env PYTHONPATH=/mnt/STORAGE/repos/helao/helao-underlay python /tmp/plate-photo-probe/probe_mixin.py`

Expected (planner's run):

```
PASS ProbeCompositionState owned=True backend=True handlers=True redraw=ProbeCompositionState._redraw_photo
PASS ProbeUvvisState owned=True backend=True handlers=True redraw=ProbeSpectraPage._redraw_photo
PASS ProbeXrdsState owned=True backend=True handlers=True redraw=ProbeSpectraPage._redraw_photo
PASS ProbeXafsState owned=True backend=True handlers=True redraw=ProbeSpectraPage._redraw_photo
MEASURE photo_choice_paths=[...four distinct paths, one per probe state...]
PASS no two pages share photo_choice
FAILS []
```

The probe is falsifiable. With `ProbeSpectraPage` made concrete (`mixin=True` dropped) and the three pages subclassing it alone, the planner measured `owned=False` on all three spectra probes and `FAIL no two pages share photo_choice`.

- [ ] **Step 5: Write the live note-contract check (runs only with credentials)**

Create `/tmp/plate-photo-probe/probe_notes.py`:

```python
"""Throwaway Task 0 check: does every wafer-photo note carry a parseable created_at?"""

import json
import os
import sys
from datetime import datetime

if not os.environ.get("HELAO_CREDENTIALS"):
    print("SKIP no HELAO_CREDENTIALS; the created_at contract stays unverified")
    sys.exit(0)

from helao.helpers.plate_api import HTEPlateAPI

plate_id = int(sys.argv[1]) if len(sys.argv) > 1 else 10197
record = HTEPlateAPI().lookup_plate(plate_id) or {}
notes = record.get("notes") or []
crop = []
for n in notes:
    text = n.get("text") or ""
    try:
        meta = json.loads(text.split("\n", 1)[1]) if "\n" in text else {}
    except ValueError:
        meta = {}
    if isinstance(meta, dict) and meta.get("kind") == "wafer_photo_circle_crop":
        crop.append(n)
print("MEASURE note_keys", sorted({k for n in notes for k in n}))
print("MEASURE circle_crop_notes", len(crop))
print("MEASURE created_at_sample", crop[0].get("created_at") if crop else None)
bad = []
for n in crop:
    try:
        datetime.fromisoformat(n["created_at"])
    except (KeyError, TypeError, ValueError):
        bad.append(n.get("created_at"))
print("FAIL" if bad else "PASS", "created_at parseable on every circle-crop note", bad[:3])
sys.exit(1 if bad else 0)
```

- [ ] **Step 6: Run it**

Run: `cd /mnt/STORAGE/repos/helao/helao-underlay && conda run -n helao env PYTHONPATH=/mnt/STORAGE/repos/helao/helao-underlay python /tmp/plate-photo-probe/probe_notes.py 10197`

Expected: either `SKIP ...` (no credentials on this machine; report that the contract is unverified) or `PASS created_at parseable ...` plus the three `MEASURE` lines. A `FAIL` line is a STOP.

- [ ] **Step 7: Report to the controller**

Send every `MEASURE`, `PASS`, `FAIL` and `SKIP` line from Steps 2, 4 and 6, plus the path `/tmp/plate-photo-probe/out/probe.png`. Stop here only if the STOP rule fired; otherwise Task 1 may start.

---

### Task 1: Shared plate-photo module

**Files:**
- Create: `helao/ui/shared/plate_photo.py`
- Create: `helao/core/tests/_plate_photo_fakes.py`
- Create: `helao/core/tests/test_plate_photo.py`

**Interfaces:**
- Consumes: nothing from earlier tasks. The duck-typed plate API: `.lookup_plate(plate_id) -> dict | None` (record with `notes[]`) and `.loader.get_bytes(bucket, key) -> io.BytesIO`, as on `helao.helpers.plate_api.HTEPlateAPI`.
- Produces:
  - `helao.ui.shared.plate_photo.Underlay`: frozen dataclass with `key: str`, `label: str`, `state: str`, `variant: str`, `input_png: str`, `created_at: str`, `extent: tuple` (`((x_min, x_max), (y_min, y_max))`), `image_s3_uri: str`
  - `parse_note(note) -> Underlay | None`
  - `underlays_for(plate_api, plate_id: int) -> list[Underlay]`
  - `load_image(plate_api, underlay: Underlay, max_px: int = UNDERLAY_MAX_PX) -> np.ndarray` (read-only `(rows, cols, 4)` uint8)
  - `split_s3_uri(uri: str) -> tuple[str, str]`
  - constants `NOTE_KIND`, `UNDERLAY_MAX_PX = 512`, `IMAGE_CACHE_SIZE = 8`, `STATE_ORDER`, `VARIANT_ORDER`
  - private `_fetch_rgba` (an `lru_cache`; tests call `_fetch_rgba.cache_clear()`)
  - fakes module: `EXTENT`, `png_bytes(rgba)`, `top_row_red(rows=8, cols=6)`, `note(...)`, `FakeLoader`, `FakePlateAPI`, `serving(rgba, **note_kwargs)`

- [ ] **Step 1: Write the fakes module**

Create `helao/core/tests/_plate_photo_fakes.py`:

```python
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
```

- [ ] **Step 2: Write the failing tests**

Create `helao/core/tests/test_plate_photo.py`:

```python
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
```

- [ ] **Step 3: Run the tests and watch them fail**

Run: `cd /mnt/STORAGE/repos/helao/helao-underlay && conda run -n helao env PYTHONPATH=/mnt/STORAGE/repos/helao/helao-underlay python -m pytest -q -p no:cacheprovider helao/core/tests/test_plate_photo.py`

Expected: a collection error, `ImportError: cannot import name 'plate_photo' from 'helao.ui.shared'`.

- [ ] **Step 4: Write the module**

Create `helao/ui/shared/plate_photo.py`:

```python
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
    Cached per ``(plate_api, image_s3_uri, max_px)``, so a redraw never
    refetches; a failure is not cached, so the next redraw retries.

    Raises:
        RuntimeError: When the plate API has no credentials loaded.
        Whatever the fetch or the decode raises.
    """
    return _fetch_rgba(plate_api, underlay.image_s3_uri, int(max_px))


@functools.lru_cache(maxsize=IMAGE_CACHE_SIZE)
def _fetch_rgba(plate_api, uri: str, max_px: int) -> np.ndarray:
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
```

- [ ] **Step 5: Run the tests and watch them pass**

Run: `cd /mnt/STORAGE/repos/helao/helao-underlay && conda run -n helao env PYTHONPATH=/mnt/STORAGE/repos/helao/helao-underlay python -m pytest -q -p no:cacheprovider helao/core/tests/test_plate_photo.py`

Expected: `21 passed`.

- [ ] **Step 6: Run the palette and xy-import gates**

Run each:
- `cd /mnt/STORAGE/repos/helao/helao-underlay && conda run -n helao env PYTHONPATH=/mnt/STORAGE/repos/helao/helao-underlay python -m pytest -q -p no:cacheprovider helao/core/tests/test_palette.py` (expected `183 passed`)
- `cd /mnt/STORAGE/repos/helao/helao-underlay && conda run -n helao env PYTHONPATH=/mnt/STORAGE/repos/helao/helao-underlay python -m pytest -q -p no:cacheprovider helao/core/tests/test_reflex_config.py` (expected `32 passed`)

- [ ] **Step 7: Controller commits (implementer does NOT run git add/commit)**

Implementer runs `cd /mnt/STORAGE/repos/helao/helao-underlay && conda run -n helao black helao/ui/shared/plate_photo.py helao/core/tests/_plate_photo_fakes.py helao/core/tests/test_plate_photo.py`, re-runs Step 5, and hands back. The controller then commits those three files as `feat(ui): parse and fetch wafer-photo plate notes for the plate-map underlay`.

**Reviewer gate (falsifiability, all measured by the planner on a scratch copy):** each mutation fails at least one test. Keep-first dedupe (`if key not in newest:`) and keep-last dedupe (`if True:`) each fail the newest test. Dropping `@functools.lru_cache` errors every test at the fixture's `cache_clear`. `Resampling.NEAREST` fails the area-filter test. Dropping the kind check fails `other-kind`. Dropping the variant rank fails the ordering test.

---

### Task 2: Per-panel byte budget in `BufferStore`

**Files:**
- Modify: `helao/ui/reflex/xy_component.py` (the `FRAME_HISTORY` comment and constant at :177-200; `BufferStore` docstring, `__init__` and `put` at :203-226)
- Modify: `helao/core/tests/test_reflex_xy_component.py` (new tests inserted before `test_store_history_is_per_panel`, at :93)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `xy_component.FRAME_BUDGET_BYTES = 32 * 1024 * 1024` and `xy_component.FRAME_MIN_KEEP = 4`; `FRAME_HISTORY = 512` is unchanged
  - `BufferStore(history: int = FRAME_HISTORY, budget_bytes: int = FRAME_BUDGET_BYTES, min_keep: int = FRAME_MIN_KEEP)`
  - `put` behaviour: after appending, drop the oldest beyond `history`, then drop the oldest while the panel's encoded bytes exceed `budget_bytes` and more than `min_keep` frames remain. `get`, `versions` and `drop` are unchanged.
  - `plots.STORE = BufferStore()` picks the budget up with no edit to `plots.py`.

Why here, before the plots task: a 512 px photo frame is 4,194,400 B, and `FRAME_HISTORY` alone let one map tab hold 512 of them (about 2 GiB). With the budget, a live stream of 32 KiB frames still keeps all 512 (16 MiB), and photo frames keep `33,554,432 // 4,194,400 = 7`.

- [ ] **Step 1: Write the failing tests**

In `helao/core/tests/test_reflex_xy_component.py`, insert directly above `def test_store_history_is_per_panel():`:

```python
def _frame_of(nbytes: int) -> list:
    """Column buffers carrying *nbytes* of payload."""
    return [memoryview(np.zeros(nbytes // 8, dtype=np.float64).tobytes())]


def test_store_keeps_every_frame_of_a_live_sized_stream():
    """Live frames are tens of KB: 512 of them fit the budget, so the byte
    budget never shortens the window the 60 Hz panels need."""
    store = xc.BufferStore()
    bufs = _frame_of(32 * 1024)
    for version in range(1, xc.FRAME_HISTORY + 89):
        store.put("panel-a", version, bufs)
    assert store.versions("panel-a") == list(range(89, xc.FRAME_HISTORY + 89))


def test_store_keeps_only_a_budget_of_4_mib_photo_frames():
    """A photo-underlay map frame is about 4 MiB. 512 of them would be 2 GiB
    per panel; the budget keeps floor(32 MiB / frame) of the newest."""
    store = xc.BufferStore()
    bufs = _frame_of(4 * 1024 * 1024)
    frame = len(xc.encode_buffers(bufs))
    for version in range(1, 21):
        store.put("panel-a", version, bufs)
    kept = xc.FRAME_BUDGET_BYTES // frame
    assert kept == 7  # 4 MiB of columns plus the frame header tops 4 MiB
    assert store.versions("panel-a") == list(range(21 - kept, 21))
    assert store.get("panel-a", 20 - kept) is None  # evicted
    assert store.get("panel-a", 20) is not None  # newest


def test_store_keeps_the_newest_few_frames_even_over_budget():
    """The browser fetches version N while N+1 is published, so a panel whose
    every frame is over budget still serves its newest FRAME_MIN_KEEP."""
    store = xc.BufferStore(budget_bytes=1000)
    bufs = _frame_of(2000)
    for version in range(1, 11):
        store.put("panel-a", version, bufs)
    assert store.versions("panel-a") == list(range(11 - xc.FRAME_MIN_KEEP, 11))
    assert xc.FRAME_MIN_KEEP == 4


def test_store_always_serves_the_newest_version():
    store = xc.BufferStore(budget_bytes=100_000)
    sizes = [10, 200_000, 50, 90_000, 300_000, 8, 60_000]
    for version, nbytes in enumerate(sizes, start=1):
        store.put("panel-a", version, _frame_of(max(nbytes, 8)))
        assert store.get("panel-a", version) is not None
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd /mnt/STORAGE/repos/helao/helao-underlay && conda run -n helao env PYTHONPATH=/mnt/STORAGE/repos/helao/helao-underlay python -m pytest -q -p no:cacheprovider helao/core/tests/test_reflex_xy_component.py`

Expected: `3 failed, 37 passed`. The live-sized test passes before the change (the count cap already gives it), and so do the 36 existing tests. The 4 MiB test fails with `AttributeError ... FRAME_BUDGET_BYTES`, the over-budget test with `TypeError ... budget_bytes`, and the newest-version test with the same `TypeError`.

- [ ] **Step 3: Implement**

In `helao/ui/reflex/xy_component.py`:

(a) Replace:

```python
#: 512 frames is ~8.5 s at 60 Hz, generous for a hiccup and still bounded at
#: order 10 MB per chart. Not derived from DEFAULT_UPDATE_RATE, which lives in
#: state -- state imports plots imports this module, so reading it back would
#: close an import cycle.
FRAME_HISTORY = 512
```

with:

```python
#: 512 frames is ~8.5 s at 60 Hz, generous for a hiccup. Not derived from
#: DEFAULT_UPDATE_RATE, which lives in state -- state imports plots imports
#: this module, so reading it back would close an import cycle.
#:
#: This is a count cap only. Memory is bounded by :data:`FRAME_BUDGET_BYTES`:
#: 512 live frames of tens of KB are a few MB, but a plate map with a photo
#: underlay publishes about 4 MiB per redraw, and 512 of those per panel per
#: browser tab is 2 GiB.
FRAME_HISTORY = 512

#: Encoded bytes retained per panel. After each put the oldest frames go while
#: the panel is over budget, so a live stream (tens of KB a frame) still keeps
#: all :data:`FRAME_HISTORY` frames, and a photo-underlay map (about 4 MiB a
#: frame) keeps about 7. Its redraws follow clicks, not a 60 Hz tick, so a
#: client is never that many versions behind.
FRAME_BUDGET_BYTES = 32 * 1024 * 1024

#: Frames kept whatever their size: a fetch of version N is in flight while
#: N+1 is published, so a panel whose single frame tops the budget must still
#: serve the frame the browser is asking for.
FRAME_MIN_KEEP = 4
```

(b) In the `BufferStore` docstring, replace:

```python
    A few recent versions are retained per panel, newest last; see
    :data:`FRAME_HISTORY`. An unknown panel or a version older than the
```

with:

```python
    A few recent versions are retained per panel, newest last: at most
    :data:`FRAME_HISTORY` of them, within :data:`FRAME_BUDGET_BYTES`, and never
    fewer than :data:`FRAME_MIN_KEEP`. An unknown panel or a version older than the
```

(c) Replace:

```python
    def __init__(self, history: int = FRAME_HISTORY):
        """Create an empty store retaining ``history`` frames per panel."""
        self._lock = threading.Lock()
        self._history = max(1, int(history))
        self._frames: dict = {}

    def put(self, panel_id: str, version: int, buffers) -> None:
        """Store a frame for ``panel_id``, dropping the oldest beyond the window."""
        encoded = encode_buffers(buffers)
        with self._lock:
            frames = self._frames.setdefault(panel_id, collections.deque())
            frames.append((int(version), encoded))
            while len(frames) > self._history:
                frames.popleft()
```

with:

```python
    def __init__(
        self,
        history: int = FRAME_HISTORY,
        budget_bytes: int = FRAME_BUDGET_BYTES,
        min_keep: int = FRAME_MIN_KEEP,
    ):
        """Create an empty store retaining at most ``history`` frames per panel,
        within ``budget_bytes``, and never fewer than ``min_keep``."""
        self._lock = threading.Lock()
        self._history = max(1, int(history))
        self._budget = int(budget_bytes)
        self._min_keep = max(1, int(min_keep))
        self._frames: dict = {}

    def put(self, panel_id: str, version: int, buffers) -> None:
        """Store a frame for ``panel_id``, dropping the oldest beyond the window."""
        encoded = encode_buffers(buffers)
        with self._lock:
            frames = self._frames.setdefault(panel_id, collections.deque())
            frames.append((int(version), encoded))
            while len(frames) > self._history:
                frames.popleft()
            # ponytail: O(frames) per put, at most FRAME_HISTORY; keep a running
            # total per panel if put ever shows up in a profile.
            size = sum(len(payload) for _, payload in frames)
            while len(frames) > self._min_keep and size > self._budget:
                size -= len(frames.popleft()[1])
```

The count cap still runs first, so `BufferStore(history=1)` and `history=2` (existing tests) keep 1 and 2 frames: the byte loop never adds frames back.

- [ ] **Step 4: Run the tests and watch them pass**

Run: `cd /mnt/STORAGE/repos/helao/helao-underlay && conda run -n helao env PYTHONPATH=/mnt/STORAGE/repos/helao/helao-underlay python -m pytest -q -p no:cacheprovider helao/core/tests/test_reflex_xy_component.py`

Expected: `40 passed`.

- [ ] **Step 5: Gates**

Run each, one process per file (`cd /mnt/STORAGE/repos/helao/helao-underlay && conda run -n helao env PYTHONPATH=/mnt/STORAGE/repos/helao/helao-underlay python -m pytest -q -p no:cacheprovider helao/core/tests/<file>`): `test_reflex_plots.py` (expected `44 passed`, still unchanged at this point), `test_reflex_panels.py` (`63 passed`), `test_reflex_config.py` (`32 passed`).

Then pyright: `cd /mnt/STORAGE/repos/helao/helao-underlay && conda run -n helao pyright --pythonpath /home/dan/miniforge3/envs/helao/bin/python --outputjson helao/ui/reflex/xy_component.py`. Expected: `filesAnalyzed: 1`, `errorCount: 1`, the pre-existing `add_imports` override error and nothing new.

- [ ] **Step 6: Controller commits (implementer does NOT run git add/commit)**

Implementer runs `cd /mnt/STORAGE/repos/helao/helao-underlay && conda run -n helao black helao/ui/reflex/xy_component.py helao/core/tests/test_reflex_xy_component.py`, re-runs Step 4, and hands back. The controller commits as `fix(xy): bound each panel's retained frames by bytes as well as count`.

**Reviewer gate (each mutation measured to fail on a scratch copy):**
- Count-only eviction (byte loop removed): 2 tests fail.
- No min-keep (`while frames and size > self._budget`): 2 tests fail.
- The budget in KiB (`32 * 1024`): 3 tests fail.
- `FRAME_MIN_KEEP = 1`: 1 test fails.

---

### Task 3: `plots.scatter_map` underlay

**Files:**
- Modify: `helao/ui/reflex/plots.py` (imports at top; constants beside `DEFAULT_POINT_SIZE` at ~:268; `scatter_map` at :552; `_publish_selectable` at :664)
- Modify: `helao/core/tests/test_reflex_plots.py` (top imports; tests appended)

**Interfaces:**
- Consumes: `helao.core.tests._plate_photo_fakes.{EXTENT, top_row_red}` (Task 1).
- Produces:
  - `plots.UNDERLAY_OPACITY = 0.6`
  - `plots.scatter_map(x, y, *, values=None, x_label="", y_label="", value_label="", size=DEFAULT_POINT_SIZE, rings=(), square=False, colormap="", colorbar=False, underlay=None, underlay_opacity: float = UNDERLAY_OPACITY, panel_id="scatter", version=0) -> ChartPayload`, where `underlay` is `(rgba, extent)`: `rgba` a `(rows, cols, 4)` uint8 array with row 0 at the top, `extent` `((x_min, x_max), (y_min, y_max))`.
  - With an underlay: `spec["traces"][0]` is `kind == "heatmap"`, `name == "photo"`, `style.truecolor is True`, `heatmap.x_range/y_range` equal to the extent. The layout token gains `|photo=<digest>:<rows>x<cols>:<x0>,<x1>,<y0>,<y1>:<opacity>`.
  - `_publish_selectable(..., extra_token: str = "")`. `ternary` keeps calling it without the kwarg.

- [ ] **Step 1: Add the test imports and the byte-identity test, and run it against the unmodified plots.py**

At the top of `helao/core/tests/test_reflex_plots.py`, change the import block to:

```python
import hashlib
import json

import numpy as np
import pytest
import xy.channel

from helao.core.tests._plate_photo_fakes import EXTENT, top_row_red
from helao.ui.reflex import plots
```

Append to the end of the file:

```python
# -- plate-photo underlay -------------------------------------------------------

#: Pinned from the unmodified ``scatter_map`` (parent cec43b68, xy 0.0.7).
#: Recompute on the pre-change commit only if xy itself is upgraded.
GOLDEN_SPEC_SHA256 = "f1d75f6f5e0b6e4f0aaeea8a083f23ea48af4496b838714dcaeec9f4a8f6b27d"
GOLDEN_FRAME_SHA256 = "704f01fa8cd000608e9735c4ecdc9833f06cf49053d0e770d5cb1619a799f2dc"
GOLDEN_LAYOUT = "0:scatter:v|1:scatter:selected_0|size=6.0(-6.5, 26.5)(-1.5, 31.5)True"


def _golden(panel_id, **extra):
    return plots.scatter_map(
        [0.0, 10.0, 20.0, 5.0],
        [0.0, 5.0, 30.0, 12.0],
        values=[1.0, 2.0, 3.0, 4.0],
        x_label="x (mm)",
        y_label="y (mm)",
        value_label="v",
        square=True,
        colormap="viridis",
        colorbar=True,
        rings=[(10.0, 5.0, 0)],
        size=6.0,
        panel_id=panel_id,
        version=7,
        **extra,
    )


@pytest.mark.parametrize("extra", [{}, {"underlay": None}], ids=["omitted", "none"])
def test_scatter_map_without_an_underlay_is_byte_identical_to_before(extra):
    """Spec, column buffers and layout token all match the pre-underlay
    output, so every existing plate map is untouched until a photo is
    chosen."""
    panel = f"golden-{len(extra)}"
    payload = _golden(panel, **extra)
    spec_digest = hashlib.sha256(
        json.dumps(payload.spec, sort_keys=True).encode()
    ).hexdigest()
    frame_digest = hashlib.sha256(plots.STORE.get(panel, 7)).hexdigest()
    assert spec_digest == GOLDEN_SPEC_SHA256
    assert frame_digest == GOLDEN_FRAME_SHA256
    assert payload.layout == GOLDEN_LAYOUT
```

Run: `cd /mnt/STORAGE/repos/helao/helao-underlay && conda run -n helao env PYTHONPATH=/mnt/STORAGE/repos/helao/helao-underlay python -m pytest -q -p no:cacheprovider helao/core/tests/test_reflex_plots.py -k byte_identical`

Expected: the `omitted` case **passes** on the unmodified `plots.py` (this is a characterization test), and the `none` case fails with `TypeError: scatter_map() got an unexpected keyword argument 'underlay'`. If `omitted` fails, the environment differs from the planner's (xy version, numpy): STOP and report the three actual values to the controller. Do not re-pin them.

- [ ] **Step 2: Write the underlay tests**

Append to `helao/core/tests/test_reflex_plots.py`:

```python
def _rgba_planes(panel_id, version, trace):
    """The heatmap's four f32 planes, decoded from the published frame."""
    frame = xy.channel.decode_frame(plots.STORE.get(panel_id, version))
    h, w = trace["heatmap"]["h"], trace["heatmap"]["w"]
    return [
        np.frombuffer(frame.buffers[i], dtype=np.float32).reshape(h, w)
        for i in trace["heatmap"]["rgba_bufs"]
    ]


def test_underlay_is_trace_zero_a_truecolor_heatmap_spanning_the_extent():
    payload = plots.scatter_map(
        [0.0, 1.0],
        [0.0, 1.0],
        values=[1.0, 2.0],
        value_label="v",
        colorbar=True,
        square=True,
        underlay=(top_row_red(), EXTENT),
        panel_id="u-trace",
        version=1,
    )
    first = payload.spec["traces"][0]
    assert first["kind"] == "heatmap" and first["name"] == "photo"
    assert first["style"]["truecolor"] is True
    assert first["style"]["opacity"] == pytest.approx(plots.UNDERLAY_OPACITY)
    assert first["heatmap"]["x_range"] == pytest.approx([-50.0, 50.0])
    assert first["heatmap"]["y_range"] == pytest.approx([-10.0, 90.0])
    assert payload.spec["traces"][1]["kind"] == "scatter"
    # The colour scale still describes the points, not the photo.
    assert payload.spec["colorbar"]["domain"] == pytest.approx([1.0, 2.0])


def test_underlay_rows_are_flipped_so_the_image_top_lands_at_y_max():
    payload = plots.scatter_map(
        [0.0],
        [0.0],
        underlay=(top_row_red(rows=8, cols=6), EXTENT),
        panel_id="u-flip",
        version=1,
    )
    red, _green, _blue, alpha = _rgba_planes("u-flip", 1, payload.spec["traces"][0])
    # xy's rows run upward from y_min, so the image's top row is xy's last.
    assert red[-1].tolist() == [1.0] * 6
    assert red[:-1].max() == 0.0
    assert alpha[-1].tolist() == [1.0] * 6
    assert alpha[:-1].max() == 0.0


def test_underlay_scales_alpha_as_well_as_colour():
    """xy never divides alpha by 255; handed uint8, 128 would clip to 1.0."""
    img = np.zeros((2, 2, 4), dtype=np.uint8)
    img[..., 3] = 128
    payload = plots.scatter_map(
        [0.0], [0.0], underlay=(img, EXTENT), panel_id="u-alpha", version=1
    )
    alpha = _rgba_planes("u-alpha", 1, payload.spec["traces"][0])[3]
    assert alpha == pytest.approx(np.full((2, 2), 128 / 255), abs=1e-6)


def test_square_domain_contains_the_extent_as_well_as_the_points():
    """The points sit off the extent's centre on both axes, so dropping the
    extent from either axis's domain leaves part of the wafer outside it."""
    payload = plots.scatter_map(
        [40.0, 41.0],
        [0.0, 1.0],
        square=True,
        underlay=(top_row_red(), EXTENT),
        panel_id="u-dom",
        version=1,
    )
    x_lo, x_hi = payload.spec["x_axis"]["domain"]
    y_lo, y_hi = payload.spec["y_axis"]["domain"]
    assert x_lo <= -50.0 and x_hi >= 50.0
    assert y_lo <= -10.0 and y_hi >= 90.0
    assert x_hi - x_lo == pytest.approx(y_hi - y_lo)  # still square


def test_layout_token_changes_with_the_photo_and_its_opacity():
    def token(**kwargs):
        return plots.scatter_map(
            [0.0], [0.0], square=True, panel_id="u-tok", version=1, **kwargs
        ).layout

    other = top_row_red()
    other[1] = (0, 0, 255, 255)  # same shape and extent, different photo
    photo = token(underlay=(top_row_red(), EXTENT))
    assert photo == token(underlay=(top_row_red(), EXTENT))
    tokens = {
        photo,
        token(underlay=(other, EXTENT)),
        token(underlay=(top_row_red(), EXTENT), underlay_opacity=0.3),
        token(),
    }
    assert len(tokens) == 4


def test_underlay_rejects_an_image_that_is_not_rgba():
    with pytest.raises(ValueError, match="RGBA"):
        plots.scatter_map(
            [0.0], [0.0], underlay=(np.zeros((4, 4, 3), dtype=np.uint8), EXTENT)
        )
```

- [ ] **Step 3: Run them and watch them fail**

Run: `cd /mnt/STORAGE/repos/helao/helao-underlay && conda run -n helao env PYTHONPATH=/mnt/STORAGE/repos/helao/helao-underlay python -m pytest -q -p no:cacheprovider helao/core/tests/test_reflex_plots.py`

Expected: `7 failed, 45 passed`. The 44 existing tests and the `omitted` golden case pass. The `none` golden case and the six new tests fail with `TypeError ... unexpected keyword argument 'underlay'`, or with `AttributeError ... UNDERLAY_OPACITY`.

- [ ] **Step 4: Implement**

In `helao/ui/reflex/plots.py`:

(a) Replace `import time\n` (top of file) with:

```python
import hashlib
import time
```

(b) Replace:

```python
#: xy's own default scatter marker size, in pixels.
DEFAULT_POINT_SIZE = 4.0
```

with:

```python
#: xy's own default scatter marker size, in pixels.
DEFAULT_POINT_SIZE = 4.0

#: Opacity of a plate-photo underlay unless the page says otherwise.
UNDERLAY_OPACITY = 0.6
```

(c) In `scatter_map`'s signature, replace:

```python
    colorbar: bool = False,
    panel_id: str = "scatter",
    version: int = 0,
):
    """Render a 2-D point cloud, optionally colored and selectable.
```

with:

```python
    colorbar: bool = False,
    underlay=None,
    underlay_opacity: float = UNDERLAY_OPACITY,
    panel_id: str = "scatter",
    version: int = 0,
):
    """Render a 2-D point cloud, optionally colored and selectable.
```

(d) In `scatter_map`'s docstring, replace:

```python
        colorbar: Show a colour scale for ``values``, titled ``value_label``.
        panel_id: Stable panel identity for the buffer route.
        version: Monotonic data version.

    Returns:
        ChartPayload: Assign into the panel state vars bound by :func:`chart`.

    Raises:
        ValueError: If ``x`` and ``y`` differ in length, or ``values`` does not
            match them.
    """
```

with:

```python
        colorbar: Show a colour scale for ``values``, titled ``value_label``.
        underlay: ``(rgba, extent)`` to draw underneath the points, or
            ``None``. ``rgba`` is a ``(rows, cols, 4)`` uint8 image whose row 0
            is its top edge; ``extent`` is ``((x_min, x_max), (y_min, y_max))``,
            the image's outer edges in data units. See :func:`_underlay_mark`.
        underlay_opacity: Opacity of the underlay, 0-1.
        panel_id: Stable panel identity for the buffer route.
        version: Monotonic data version.

    Returns:
        ChartPayload: Assign into the panel state vars bound by :func:`chart`.

    Raises:
        ValueError: If ``x`` and ``y`` differ in length, ``values`` does not
            match them, or ``underlay`` is not an RGBA image.
    """
```

(e) Replace the end of `scatter_map`:

```python
    marks.extend(_ring_marks(rings, size))
    return _publish_selectable(
        marks, xs, ys, x_label, y_label, square, panel_id, version, show_bar, size
    )
```

with:

```python
    marks.extend(_ring_marks(rings, size))
    dom_xs, dom_ys, photo_token = xs, ys, ""
    if underlay is not None:
        photo, photo_token, ex, ey = _underlay_mark(underlay, underlay_opacity)
        # First, so it draws underneath every point and ring.
        marks.insert(0, photo)
        # The square domain covers the photo too, so the wafer is never clipped.
        dom_xs = np.concatenate([xs, ex])
        dom_ys = np.concatenate([ys, ey])
    return _publish_selectable(
        marks,
        dom_xs,
        dom_ys,
        x_label,
        y_label,
        square,
        panel_id,
        version,
        show_bar,
        size,
        extra_token=photo_token,
    )


def _underlay_mark(underlay, opacity: float) -> tuple:
    """A photo as an xy truecolor heatmap, plus what identifies it.

    Three things here fail silently if changed:

    * Image row 0 is the top edge, but xy's rows run upward from y_min, so the
      rows are flipped first.
    * xy takes cell **centres** and derives the edges from them, so the
      positions passed are centres; passing the extent's edges would shift the
      photo half a cell.
    * xy divides RGB by 255 only when it sees a value above 1, and never
      divides alpha, so all four channels are scaled here. Handed uint8, every
      partial alpha would clip to opaque.

    Returns:
        tuple: ``(mark, layout_token_suffix, (x_min, x_max), (y_min, y_max))``.
        The token carries a content digest, the shape, the extent and the
        opacity: the in-place update path swaps columns only, so a different
        photo or opacity has to force a rebuild.
    """
    rgba, ((x0, x1), (y0, y1)) = underlay
    img = np.asarray(rgba)
    if img.ndim != 3 or img.shape[2] != 4:
        raise ValueError(
            f"underlay must be an RGBA (rows, cols, 4) image, got shape {img.shape}"
        )
    rows, cols = img.shape[:2]
    z = np.flipud(img).astype(np.float64) / 255.0
    xc = x0 + (np.arange(cols) + 0.5) * (x1 - x0) / cols
    yc = y0 + (np.arange(rows) + 0.5) * (y1 - y0) / rows
    digest = hashlib.blake2b(
        np.ascontiguousarray(img).tobytes(), digest_size=8
    ).hexdigest()
    token = (
        f"|photo={digest}:{rows}x{cols}:{x0:g},{x1:g},{y0:g},{y1:g}"
        f":{float(opacity):g}"
    )
    mark = xy.heatmap(z, x=xc, y=yc, opacity=float(opacity), name="photo")
    return mark, token, (float(x0), float(x1)), (float(y0), float(y1))
```

(f) In `_publish_selectable`'s signature, replace:

```python
    colorbar=False,
    size=DEFAULT_POINT_SIZE,
):
    """Publish a click-selectable point chart, optionally square.
```

with:

```python
    colorbar=False,
    size=DEFAULT_POINT_SIZE,
    extra_token: str = "",
):
    """Publish a click-selectable point chart, optionally square.
```

(g) In its docstring, replace:

```python
    column data, so the in-place update path would not apply a new one.
    """
    axes = _axes(x_label, y_label, False)
```

with:

```python
    column data, so the in-place update path would not apply a new one.
    *extra_token* is appended to the layout token as given (the underlay's
    identity); empty leaves the token as it always was.
    """
    axes = _axes(x_label, y_label, False)
```

(h) Replace:

```python
        extra += f"{x_dom}{y_dom}{colorbar}"
    figure = _chart(marks, axes, **kwargs)
```

with:

```python
        extra += f"{x_dom}{y_dom}{colorbar}"
    extra += extra_token
    figure = _chart(marks, axes, **kwargs)
```

- [ ] **Step 5: Run the tests and watch them pass**

Run: `cd /mnt/STORAGE/repos/helao/helao-underlay && conda run -n helao env PYTHONPATH=/mnt/STORAGE/repos/helao/helao-underlay python -m pytest -q -p no:cacheprovider helao/core/tests/test_reflex_plots.py`

Expected: `52 passed`.

- [ ] **Step 6: Gates**

Run each, one process per file:
- `... python -m pytest -q -p no:cacheprovider helao/core/tests/test_reflex_config.py` (expected `32 passed`)
- `... python -m pytest -q -p no:cacheprovider helao/core/tests/test_reflex_composition.py` (expected `37 passed`: `underlay=None` everywhere still)
- `... python -m pytest -q -p no:cacheprovider helao/core/tests/test_palette.py` (expected `183 passed`)

(`...` = `cd /mnt/STORAGE/repos/helao/helao-underlay && conda run -n helao env PYTHONPATH=/mnt/STORAGE/repos/helao/helao-underlay python`.)

- [ ] **Step 7: Controller commits (implementer does NOT run git add/commit)**

Implementer runs `cd /mnt/STORAGE/repos/helao/helao-underlay && conda run -n helao black helao/ui/reflex/plots.py helao/core/tests/test_reflex_plots.py`, re-runs Step 5, and hands back. The controller commits as `feat(plots): optional truecolor photo underlay on scatter_map`.

**Reviewer gate (each mutation measured to fail):** removing `np.flipud` fails the flip test. `marks.append(photo)` fails 3 tests. `np.linspace(x0, x1, cols)` for `xc` fails the extent test. Passing `np.flipud(img)` unscaled fails the alpha test. Dropping the extent from `dom_xs`, or separately from `dom_ys`, fails the domain test (an earlier draft with points at the extent's centre let the `dom_xs` mutation pass, which is why the points are at x=40). Dropping the digest from the token fails the token test. Making the `None` path add a token fails both golden cases.

---

### Task 4: `PlatePhotoState` mixin and controls

**Files:**
- Create: `helao/ui/reflex/plate_photo.py`
- Create: `helao/core/tests/test_reflex_plate_photo.py`

**Interfaces:**
- Consumes: `helao.ui.shared.plate_photo.{underlays_for, load_image}` (Task 1); `plots.UNDERLAY_OPACITY` (Task 3); `helao.ui.shared.platemap.plate_api_for_config`; `helao.ui.reflex.composition.world_config` (lazy import inside `_plate_api`, because composition and spectra_page import this module in Task 5).
- Produces:
  - `helao.ui.reflex.plate_photo.PHOTO_OFF = "off"`, `NO_PHOTOS_NOTE = "no wafer photo notes on this plate"`
  - `_plate_api()`: module-level; tests monkeypatch it
  - `class PlatePhotoState(rx.State, mixin=True)`:
    - vars `photo_options: list[str] = ["off"]`, `photo_choice: str = "off"`, `photo_opacity: float = 0.6`, `photo_note: str = ""`; backend var `_photos: list = []`
    - plain methods `_redraw_photo() -> None` (default raises `NotImplementedError`; the page overrides), `_load_photos(plate_id: int) -> None` (never raises), `_underlay_arg() -> tuple | None` (`(rgba, extent)`)
    - events `set_photo_choice(value: str)`, `set_photo_opacity(value: list[float])`
  - `photo_controls(S) -> rx.Component`: a select bound `on_change=S.set_photo_choice`, a slider bound `on_value_commit=S.set_photo_opacity`, and the muted note.

- [ ] **Step 1: Write the failing tests**

Create `helao/core/tests/test_reflex_plate_photo.py`:

```python
"""Tests for the plate-photo mixin and its controls, without a running app."""

import numpy as np
import pytest
import reflex as rx

from helao.core.tests._plate_photo_fakes import (
    EXTENT,
    FakeLoader,
    FakePlateAPI,
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


class _FakePhotoState:
    """Carries the mixin's vars; its methods are bound straight off the mixin.

    Not an ``rx.State``: Reflex forwards attribute assignment on a real state
    to a session that does not exist outside a running app. On a mixin the
    ``@rx.event`` methods are still plain functions, so they bind directly.
    """

    def __init__(self):
        self.photo_options = [rpp.PHOTO_OFF]
        self.photo_choice = rpp.PHOTO_OFF
        self.photo_opacity = plots.UNDERLAY_OPACITY
        self.photo_note = ""
        self._photos = []
        self.redraws = 0

    def _redraw_photo(self):
        self.redraws += 1

    _load_photos = rpp.PlatePhotoState._load_photos
    _underlay_arg = rpp.PlatePhotoState._underlay_arg
    set_photo_choice = rpp.PlatePhotoState.set_photo_choice
    set_photo_opacity = rpp.PlatePhotoState.set_photo_opacity


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
    state = _FakePhotoState()
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
    state = _FakePhotoState()
    state.photo_options = ["off", "a photo of the previous plate"]
    state._photos = ["stale"]
    state._load_photos(10197)
    assert state.photo_options == ["off"]
    assert state.photo_choice == "off"
    assert state._photos == []
    assert expected in state.photo_note


def test_no_credentials_never_calls_the_plate_api(monkeypatch):
    api = _with_api(monkeypatch, FakePlateAPI([note()], loader=None))
    _FakePhotoState()._load_photos(10197)
    assert api.lookups == []


def test_underlay_arg_is_none_with_the_photo_off(monkeypatch):
    api = _with_api(monkeypatch, serving(top_row_red()))
    state = _FakePhotoState()
    state._load_photos(10197)
    assert state._underlay_arg() is None
    assert api.loader.calls == []


def test_underlay_arg_returns_the_chosen_photo_and_its_extent(monkeypatch):
    _with_api(monkeypatch, serving(top_row_red(rows=8, cols=6)))
    state = _FakePhotoState()
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
    state = _FakePhotoState()
    state._load_photos(10197)
    label = state.photo_options[1]
    state.set_photo_choice(label)
    assert state._underlay_arg() is None
    assert label in state.photo_note and "access denied" in state.photo_note


def test_choosing_a_photo_or_off_redraws_and_an_unknown_choice_is_off(monkeypatch):
    _with_api(monkeypatch, serving(top_row_red()))
    state = _FakePhotoState()
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
    state = _FakePhotoState()
    state._load_photos(10197)
    state.set_photo_opacity([0.3])
    assert (state.photo_opacity, state.redraws) == (0.3, 0)
    state.set_photo_choice(state.photo_options[1])
    state.set_photo_opacity([1.7])
    assert (state.photo_opacity, state.redraws) == (1.0, 2)
    state.set_photo_opacity([-1.0])
    assert state.photo_opacity == 0.0


def _nodes(component) -> list:
    out = [component]
    for child in getattr(component, "children", []) or []:
        out.extend(_nodes(child))
    return out


def _bound(component) -> set:
    """``(node type, trigger, handler name)`` for every bound event."""
    found = set()
    for node in _nodes(component):
        for trigger, chain in (getattr(node, "event_triggers", {}) or {}).items():
            for event in getattr(chain, "events", None) or []:
                found.add((type(node).__name__, trigger, event.handler.fn.__name__))
    return found


def test_photo_controls_bind_the_select_and_the_slider_at_render():
    """Event-binding errors appear at render, not at import."""

    class PhotoControlsProbeState(rpp.PlatePhotoState, rx.State):
        def _redraw_photo(self) -> None:
            pass

    bound = _bound(rpp.photo_controls(PhotoControlsProbeState))
    assert ("SelectRoot", "on_change", "set_photo_choice") in bound
    assert ("Slider", "on_value_commit", "set_photo_opacity") in bound
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd /mnt/STORAGE/repos/helao/helao-underlay && conda run -n helao env PYTHONPATH=/mnt/STORAGE/repos/helao/helao-underlay python -m pytest -q -p no:cacheprovider helao/core/tests/test_reflex_plate_photo.py`

Expected: a collection error, `ImportError: cannot import name 'plate_photo' from 'helao.ui.reflex'`.

- [ ] **Step 3: Write the module**

Create `helao/ui/reflex/plate_photo.py`:

```python
# helao/ui/reflex/plate_photo.py
"""The wafer-photo underlay for the Reflex plate maps: state and controls.

:class:`PlatePhotoState` is a Reflex **mixin**, and that is load-bearing (see
``state.py``): vars declared on a concrete ``rx.State`` are shared by every
subclass. ``CompositionState`` mixes it in directly, and ``SpectraPageState``
-- itself a mixin -- inherits it, as ``LiveVisState`` inherits
``VisPanelState``, so ``UvvisState``, ``XrdsState`` and ``XafsState`` each
still own their copy. Never mix it into a concrete base.

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
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `cd /mnt/STORAGE/repos/helao/helao-underlay && conda run -n helao env PYTHONPATH=/mnt/STORAGE/repos/helao/helao-underlay python -m pytest -q -p no:cacheprovider helao/core/tests/test_reflex_plate_photo.py`

Expected: `12 passed`.

- [ ] **Step 5: Gates**

`test_palette.py` (expected `183 passed`) and `test_reflex_config.py` (expected `32 passed`), each as `cd /mnt/STORAGE/repos/helao/helao-underlay && conda run -n helao env PYTHONPATH=/mnt/STORAGE/repos/helao/helao-underlay python -m pytest -q -p no:cacheprovider helao/core/tests/<file>`.

- [ ] **Step 6: Controller commits (implementer does NOT run git add/commit)**

Implementer runs `cd /mnt/STORAGE/repos/helao/helao-underlay && conda run -n helao black helao/ui/reflex/plate_photo.py helao/core/tests/test_reflex_plate_photo.py`, re-runs Step 4, and hands back. The controller commits as `feat(reflex): PlatePhotoState mixin and photo controls`.

**Reviewer gate (measured):** narrowing `except Exception` in `_load_photos` fails `lookup-raises`. Dropping the choice reset fails the first test. Binding the slider with `on_change` fails the render test. Redrawing on every opacity change fails the opacity test.

---

### Task 5: Wire the four pages

**Files:**
- Modify: `helao/ui/reflex/composition.py` (imports :31-41, `class CompositionState` :357, after `_redraw_charts` :508-522, `retrieve` :619-623, `_draw_map` :696-711, `_map_panel` :1019-1031)
- Modify: `helao/ui/reflex/spectra_page.py` (imports :30, `class SpectraPageState` :78, after `_redraw` :223-228, `_draw_map` :316-330, `charts(S)` :561-563)
- Modify: `helao/ui/reflex/uvvis.py` (:108-111), `helao/ui/reflex/xrds.py` (:103-106), `helao/ui/reflex/xafs.py` (:192-195): one line each in `retrieve`; their state bases are unchanged
- Create: `helao/core/tests/test_reflex_plate_photo_pages.py`
- Modify: `helao/core/tests/test_reflex_composition.py`, `test_reflex_uvvis.py`, `test_xrds.py`, `test_xafs.py`, `test_reflex_routes_e2e.py`

**Interfaces:**
- Consumes: `PlatePhotoState`, `photo_controls`, `PHOTO_OFF`, `_plate_api` (Task 4); `scatter_map(underlay=, underlay_opacity=)` (Task 3); the fakes (Task 1).
- Produces:
  - `class CompositionState(PlatePhotoState, rx.State)` with `_redraw_photo() -> None` (version + 1, then `_redraw_charts()`)
  - `class SpectraPageState(PlatePhotoState, rx.State, mixin=True)` with `_redraw_photo() -> None` (calls `_redraw()`), which overrides the mixin's raising default by ordinary inheritance
  - `UvvisState(SpectraPageState, rx.State)`, `XrdsState(...)` and `XafsState(...)` unchanged: each gets its own copy of the photo vars through the mixin chain
  - each `retrieve` calls `self._load_photos(plate_id)` inside the `async with self:` block that sets `platemap_note`
  - both `_draw_map`s pass `underlay=self._underlay_arg(), underlay_opacity=self.photo_opacity`

- [ ] **Step 1: Update the existing test fakes**

`_draw_map` will read `self._underlay_arg()` and `self.photo_opacity`, and the four existing fakes bind `_draw_map` off the real classes. Each fake needs the mixin's vars and `_underlay_arg`.

(a) `helao/core/tests/test_reflex_composition.py`. Replace the import block's line `from helao.ui.reflex import composition` with:

```python
from helao.core.tests._plate_photo_fakes import FakePlateAPI, serving, top_row_red
from helao.ui.reflex import composition
from helao.ui.reflex import plate_photo as rpp
```

In `_FakeCompositionState.__init__`, replace:

```python
        self.sequence_options: list = []
        self.transition_options: list = []
        self.unit_options: list = []

    def panel_key(self) -> str:
        return "test-panel"
```

with:

```python
        self.sequence_options: list = []
        self.transition_options: list = []
        self.unit_options: list = []
        # PlatePhotoState's vars, as the real page state carries them.
        self.photo_options = ["off"]
        self.photo_choice = "off"
        self.photo_opacity = 0.6
        self.photo_note = ""
        self._photos: list = []

    def panel_key(self) -> str:
        return "test-panel"
```

and replace:

```python
    on_tern_select = composition.CompositionState.on_tern_select.fn  # type: ignore[attr-defined]
```

with:

```python
    on_tern_select = composition.CompositionState.on_tern_select.fn  # type: ignore[attr-defined]
    retrieve = composition.CompositionState.retrieve.fn  # type: ignore[attr-defined]
    _load_photos = composition.CompositionState._load_photos
    _underlay_arg = composition.CompositionState._underlay_arg
    _redraw_photo = composition.CompositionState._redraw_photo
    set_photo_choice = composition.CompositionState.set_photo_choice.fn  # type: ignore[attr-defined]
```

(b) `helao/core/tests/test_reflex_uvvis.py`. Replace the line `from helao.ui.reflex import plots` with:

```python
from helao.core.tests._plate_photo_fakes import serving, top_row_red
from helao.ui.reflex import plate_photo as rpp
from helao.ui.reflex import plots
```

In `_FakeUvvisState.__init__`, replace:

```python
            setattr(self, f"{name}_layout", "")

    def panel_key(self):
        return "test-uvvis"
```

with:

```python
            setattr(self, f"{name}_layout", "")
        # PlatePhotoState's vars, as the real page state carries them.
        self.photo_options = ["off"]
        self.photo_choice = "off"
        self.photo_opacity = 0.6
        self.photo_note = ""
        self._photos: list = []

    def panel_key(self):
        return "test-uvvis"
```

and replace:

```python
    set_overlay_spectra = page.UvvisState.set_overlay_spectra.fn  # type: ignore[attr-defined]
```

with:

```python
    set_overlay_spectra = page.UvvisState.set_overlay_spectra.fn  # type: ignore[attr-defined]
    _load_photos = page.UvvisState._load_photos
    _underlay_arg = page.UvvisState._underlay_arg
    _redraw_photo = page.UvvisState._redraw_photo
    set_photo_choice = page.UvvisState.set_photo_choice.fn  # type: ignore[attr-defined]
```

(c) `helao/core/tests/test_xrds.py`. In `_FakeXrdsState.__init__`, replace:

```python
            setattr(self, f"{name}_layout", "")

    def panel_key(self):
        return "test-xrds"
```

with:

```python
            setattr(self, f"{name}_layout", "")
        # PlatePhotoState's vars, as the real page state carries them.
        self.photo_options = ["off"]
        self.photo_choice = "off"
        self.photo_opacity = 0.6
        self.photo_note = ""
        self._photos: list = []

    def panel_key(self):
        return "test-xrds"
```

and replace:

```python
    on_map_select = page.XrdsState.on_map_select.fn  # type: ignore[attr-defined]
```

with:

```python
    on_map_select = page.XrdsState.on_map_select.fn  # type: ignore[attr-defined]
    _underlay_arg = page.XrdsState._underlay_arg
```

(d) `helao/core/tests/test_xafs.py`. In `_FakeXafsState.__init__`, replace:

```python
            setattr(self, f"{name}_layout", "")

    def panel_key(self):
        return "test-xafs"
```

with:

```python
            setattr(self, f"{name}_layout", "")
        # PlatePhotoState's vars, as the real page state carries them.
        self.photo_options = ["off"]
        self.photo_choice = "off"
        self.photo_opacity = 0.6
        self.photo_note = ""
        self._photos: list = []

    def panel_key(self):
        return "test-xafs"
```

and replace:

```python
    on_map_select = page.XafsState.on_map_select.fn  # type: ignore[attr-defined]
```

with:

```python
    on_map_select = page.XafsState.on_map_select.fn  # type: ignore[attr-defined]
    _underlay_arg = page.XafsState._underlay_arg
```

- [ ] **Step 2: Write the new page tests**

(a) Append to `helao/core/tests/test_reflex_composition.py`:

```python
def _kinds(spec) -> list:
    return [t["kind"] for t in spec.get("traces") or []]


def test_choosing_a_photo_redraws_the_map_over_it_and_off_removes_it(
    monkeypatch,
) -> None:
    monkeypatch.setattr(rpp, "_plate_api", lambda: serving(top_row_red()))
    state = _FakeCompositionState()
    state._records = RECORDS
    state._pm_rows = PM_ROWS
    state.transition_choice, state.unit_choice = "Co.K", "net_counts"
    state.vertex_a, state.vertex_b, state.vertex_c = "Co.K", "Y.K", "Pt.L"
    state.plot()
    assert "heatmap" not in _kinds(state.map_spec)
    state.selected_label = "sample 1"

    state._load_photos(10244)
    state.set_photo_choice(state.photo_options[1])
    assert _kinds(state.map_spec)[:2] == ["heatmap", "scatter"]
    # The ternary is not a plate map and never carries the photo.
    assert "heatmap" not in _kinds(state.tern_spec)
    assert state.selected_label == "sample 1"  # a redraw, not a re-plot

    state.set_photo_choice("off")
    assert "heatmap" not in _kinds(state.map_spec)


def test_retrieve_lists_the_photos_and_survives_a_failing_photo_lookup(
    monkeypatch,
) -> None:
    async def fake_load(plate_id):
        return composition.Loaded(records=RECORDS, failures=0)

    monkeypatch.setattr(composition, "load_records", fake_load)
    monkeypatch.setattr(composition, "platemap_for", lambda pid: (PM_ROWS, ""))

    monkeypatch.setattr(rpp, "_plate_api", lambda: serving(top_row_red()))
    state = _FakeCompositionState()
    state.plate_id = "10244"
    asyncio.run(state.retrieve(""))
    assert len(state.photo_options) == 2
    assert state.status.startswith("plate 10244: 2 XRF processes")

    failing = FakePlateAPI(error=RuntimeError("HTTP 503"))
    monkeypatch.setattr(rpp, "_plate_api", lambda: failing)
    state = _FakeCompositionState()
    state.plate_id = "10244"
    asyncio.run(state.retrieve(""))
    assert state.photo_options == ["off"]
    assert "HTTP 503" in state.photo_note
    assert state.status.startswith("plate 10244: 2 XRF processes")
    assert state._pm_rows == PM_ROWS
```

(b) Append to `helao/core/tests/test_reflex_uvvis.py`:

```python
def test_choosing_a_photo_redraws_the_map_and_clicks_still_pick_samples(
    loaded, monkeypatch
) -> None:
    """The photo is trace 0 and covers the map, but a click still resolves to
    the nearest plotted sample: both pages match on the click's x/y."""
    monkeypatch.setattr(rpp, "_plate_api", lambda: serving(top_row_red()))
    state = _FakeUvvisState(loaded)
    state._draw()
    state._load_photos(10201)
    state.set_photo_choice(state.photo_options[1])
    kinds = [t["kind"] for t in state.map_spec["traces"]]
    assert kinds[:2] == ["heatmap", "scatter"]
    state.on_map_select({"x": 2.1, "y": 0.1})
    assert "sample 2" in state.selected_label
    state.set_photo_choice("off")
    assert "heatmap" not in [t["kind"] for t in state.map_spec["traces"]]
```

(c) Create `helao/core/tests/test_reflex_plate_photo_pages.py`:

```python
"""The plate-photo underlay wired into the four plate-map pages.

Rendered, not merely imported: an event-binding error appears only at render.
"""

import asyncio

import pytest

from helao.core.tests._plate_photo_fakes import FakePlateAPI, serving, top_row_red
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


def _nodes(component) -> list:
    out = [component]
    for child in getattr(component, "children", []) or []:
        out.extend(_nodes(child))
    return out


def _bound(nodes) -> list:
    """``(node type, trigger, handler name)`` for every bound event."""
    found = []
    for node in nodes:
        for trigger, chain in (getattr(node, "event_triggers", {}) or {}).items():
            for event in getattr(chain, "events", None) or []:
                found.append((type(node).__name__, trigger, event.handler.fn.__name__))
    return found


@pytest.mark.parametrize("name", PAGES)
def test_each_page_renders_one_set_of_photo_controls_and_no_extra_chart(name):
    """The photo is a trace on the existing map, so each page keeps its three
    charts: every chart is a WebGL context and the browser caps them."""
    module, _state = PAGES[name]
    nodes = _nodes(module.build_page())
    bound = _bound(nodes)
    assert bound.count(("SelectRoot", "on_change", "set_photo_choice")) == 1
    assert bound.count(("Slider", "on_value_commit", "set_photo_opacity")) == 1
    assert sum(type(n).__name__ == "XYChart" for n in nodes) == 3


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
```

(d) `helao/core/tests/test_reflex_routes_e2e.py`: add the two photo handlers to each page's registration list. Replace:

```python
    for name in ("retrieve", "plot", "on_map_select", "set_plate_id"):
```

with:

```python
    for name in (
        "retrieve",
        "plot",
        "on_map_select",
        "set_plate_id",
        "set_photo_choice",
        "set_photo_opacity",
    ):
```

Replace:

```python
        "commit_wl_hi",
        "apply_wl_text",
    ):
```

with:

```python
        "commit_wl_hi",
        "apply_wl_text",
        "set_photo_choice",
        "set_photo_opacity",
    ):
```

Replace:

```python
    for name in ("retrieve", "plot", "on_map_select", "set_element", "commit_wl_lo"):
```

with:

```python
    for name in (
        "retrieve",
        "plot",
        "on_map_select",
        "set_element",
        "commit_wl_lo",
        "set_photo_choice",
        "set_photo_opacity",
    ):
```

Replace:

```python
    for name in ("retrieve", "plot", "on_map_select", "set_file_type", "commit_wl_hi"):
```

with:

```python
    for name in (
        "retrieve",
        "plot",
        "on_map_select",
        "set_file_type",
        "commit_wl_hi",
        "set_photo_choice",
        "set_photo_opacity",
    ):
```

- [ ] **Step 3: Run the tests and watch them fail**

Run each:
- `cd /mnt/STORAGE/repos/helao/helao-underlay && conda run -n helao env PYTHONPATH=/mnt/STORAGE/repos/helao/helao-underlay python -m pytest -q -p no:cacheprovider helao/core/tests/test_reflex_plate_photo_pages.py`. Expected: failures, because the page states have no photo vars or handlers yet.
- the same for `test_reflex_composition.py`, `test_reflex_uvvis.py`, `test_xrds.py` and `test_xafs.py`. Expected: a collection error, `AttributeError ... _underlay_arg`, raised in the fake's class body.
- the same for `test_reflex_routes_e2e.py`. Expected: 4 failures, `set_photo_choice not registered`.

- [ ] **Step 4: Wire `composition.py`**

(a) Replace `from helao.ui.reflex import plots\n` with:

```python
from helao.ui.reflex import plots
from helao.ui.reflex.plate_photo import PlatePhotoState, photo_controls
```

(b) Replace `class CompositionState(rx.State):` with `class CompositionState(PlatePhotoState, rx.State):`.

(c) Replace:

```python
        self._draw_map(records)
        self._draw_composition(records)

    def _rings(self, plotted, xs, ys) -> list:
```

with:

```python
        self._draw_map(records)
        self._draw_composition(records)

    def _redraw_photo(self) -> None:
        """PlatePhotoState's hook: a photo or opacity change keeps the selection."""
        self.version += 1
        self._redraw_charts()

    def _rings(self, plotted, xs, ys) -> list:
```

(d) In `retrieve`, replace:

```python
            self._pm_rows = rows
            self.platemap_note = note
            self.run_use_options = grouping.run_use_options(loaded.records)
```

with:

```python
            self._pm_rows = rows
            self.platemap_note = note
            self._load_photos(plate_id)
            self.run_use_options = grouping.run_use_options(loaded.records)
```

(e) In `_draw_map`, replace:

```python
            panel_id=f"{self.panel_key()}-map",
            version=self.version,
            size=self._point_size(),
            rings=rings,
        )
```

with:

```python
            panel_id=f"{self.panel_key()}-map",
            version=self.version,
            size=self._point_size(),
            rings=rings,
            underlay=self._underlay_arg(),
            underlay_opacity=self.photo_opacity,
        )
```

(f) In `_map_panel`, replace:

```python
                on_change=CompositionState.set_interpolate,
            ),
            spacing="3",
            align="center",
        ),
```

with:

```python
                on_change=CompositionState.set_interpolate,
            ),
            photo_controls(CompositionState),
            spacing="3",
            align="center",
            flex_wrap="wrap",
        ),
```

- [ ] **Step 5: Wire `spectra_page.py`**

(a) Replace `from helao.ui.reflex import plots\n` with:

```python
from helao.ui.reflex import plots
from helao.ui.reflex.plate_photo import PlatePhotoState, photo_controls
```

(b) Replace `class SpectraPageState(rx.State, mixin=True):` with `class SpectraPageState(PlatePhotoState, rx.State, mixin=True):`. This is a mixin inheriting a mixin, as `LiveVisState(VisPanelState, mixin=True)` already is in `state.py`. `UvvisState(SpectraPageState, rx.State)` and its two siblings stay as they are, and each still owns its copy of the photo vars.

(c) Replace:

```python
        self.version += 1
        self._draw()

    # -- window controls ----------------------------------------------------
```

with:

```python
        self.version += 1
        self._draw()

    def _redraw_photo(self) -> None:
        """PlatePhotoState's hook for the three spectra pages.

        This mixin inherits PlatePhotoState, so this overrides its raising
        default by ordinary inheritance.
        """
        self._redraw()

    # -- window controls ----------------------------------------------------
```

(d) In `_draw_map`, replace:

```python
            rings=rings,
            panel_id=f"{self.panel_key()}-map",
            version=self.version,
        )
```

with:

```python
            rings=rings,
            underlay=self._underlay_arg(),
            underlay_opacity=self.photo_opacity,
            panel_id=f"{self.panel_key()}-map",
            version=self.version,
        )
```

(e) In `charts(S)`, replace:

```python
        rx.cond(S.error != "", rx.text(S.error, class_name="text-red-600", size="1")),
        rx.hstack(
            map_panel,
```

with:

```python
        rx.cond(S.error != "", rx.text(S.error, class_name="text-red-600", size="1")),
        photo_controls(S),
        rx.hstack(
            map_panel,
```

- [ ] **Step 6: Wire `uvvis.py`, `xrds.py`, `xafs.py` (`retrieve` only)**

Their imports and state bases do not change: the photo arrives through `SpectraPageState`. In each of the three files, in `retrieve`, replace:

```python
            self._pm_rows = rows
            self.platemap_note = note
```

with:

```python
            self._pm_rows = rows
            self.platemap_note = note
            self._load_photos(plate_id)
```

(Each file has exactly one occurrence.)

- [ ] **Step 7: Run every touched test file and watch them pass**

Run each, one process per file (`cd /mnt/STORAGE/repos/helao/helao-underlay && conda run -n helao env PYTHONPATH=/mnt/STORAGE/repos/helao/helao-underlay python -m pytest -q -p no:cacheprovider helao/core/tests/<file>`):

| file | expected |
|---|---|
| `test_reflex_plate_photo_pages.py` | `20 passed` |
| `test_reflex_composition.py` | `39 passed` |
| `test_reflex_uvvis.py` | `7 passed` |
| `test_xrds.py` | `4 passed` |
| `test_xafs.py` | `10 passed` |
| `test_reflex_routes_e2e.py` | `21 passed` |
| `test_reflex_plate_photo.py` | `12 passed` |
| `test_reflex_plots.py` | `52 passed` |
| `test_palette.py` | `183 passed` |
| `test_reflex_config.py` | `32 passed` |
| `test_reflex_panels.py` | `63 passed` |

- [ ] **Step 8: pyright (no new errors)**

Run: `cd /mnt/STORAGE/repos/helao/helao-underlay && conda run -n helao pyright --pythonpath /home/dan/miniforge3/envs/helao/bin/python --outputjson helao/ui/shared/plate_photo.py helao/ui/reflex/plate_photo.py helao/ui/reflex/plots.py helao/ui/reflex/composition.py helao/ui/reflex/spectra_page.py helao/ui/reflex/uvvis.py helao/ui/reflex/xrds.py helao/ui/reflex/xafs.py > /tmp/plate-photo-pyright.json; python3 -c "import json; d=json.load(open('/tmp/plate-photo-pyright.json')); print(d['summary']); [print(x['file'].rsplit('/',1)[-1], x['range']['start']['line']+1, x['message'][:90]) for x in d['generalDiagnostics']]"`

Expected: `filesAnalyzed: 8`, `errorCount: 6`, all six pre-existing (on cec43b68 they are the same six): four in `composition.py` (`No overloads for "sum"` and `list[Unknown | None]` in `ternary_fractions`, and two `ConvertibleToFloat` in `_draw_binary`), and two in `plots.py` (`Tooltip` and `Colorbar` cannot be assigned to `Mark` in `scatter_map`'s `marks.append`). Any other error, or `filesAnalyzed` other than 8, is a STOP.

- [ ] **Step 9: Controller commits (implementer does NOT run git add/commit)**

Implementer runs `cd /mnt/STORAGE/repos/helao/helao-underlay && conda run -n helao black helao/ui/reflex/composition.py helao/ui/reflex/spectra_page.py helao/ui/reflex/uvvis.py helao/ui/reflex/xrds.py helao/ui/reflex/xafs.py helao/core/tests/test_reflex_plate_photo_pages.py helao/core/tests/test_reflex_composition.py helao/core/tests/test_reflex_uvvis.py helao/core/tests/test_xrds.py helao/core/tests/test_xafs.py helao/core/tests/test_reflex_routes_e2e.py`, re-runs Step 7, and hands back. The controller commits as `feat(reflex): wafer-photo underlay on the composition, UV-Vis, XRD and XAFS plate maps`.

**Reviewer gate (each mutation measured to fail `test_reflex_plate_photo_pages.py` on a scratch copy):**
- `SpectraPageState` without `PlatePhotoState` in its bases: 14 tests fail.
- `SpectraPageState._redraw_photo` deleted: the 3 redraw tests fail. A one-sided identity check passed this mutation, so the test asserts both halves.
- `self._load_photos(plate_id)` deleted from `xrds.retrieve`: both xrds retrieve cases fail.
- `photo_controls(S)` deleted from `charts`: the 3 spectra render tests fail.
- `CompositionState` without `PlatePhotoState`: 3 tests fail.

---

### Task 6: CLAUDE.md bullet, full gate run, visual check

**Files:**
- Modify: `helao/ui/reflex/CLAUDE.md` (new bullet after the one that starts ``- **`/uvvis`, `/xafs` and `/xrds` are one page with three lookups.**``)
- Create (throwaway, not committed): `/tmp/plate-photo-visual/visual.py`

**Interfaces:**
- Consumes: everything above.
- Produces: the doc bullet; a gate report and screenshots for the reviewer.

- [ ] **Step 1: Add the CLAUDE.md bullet**

Insert this bullet on its own line directly after the bullet that starts ``- **`/uvvis`, `/xafs` and `/xrds` are one page with three lookups.**`` in `helao/ui/reflex/CLAUDE.md`:

```markdown
- **The four plate maps can draw a wafer photo underneath, as trace 0 of the same chart, not as a second chart.** `helao/ui/shared/plate_photo.py` reads the plate record's `wafer_photo_circle_crop` notes, keeps the newest per `(input_png, variant)` by `created_at` (the API has no delete, and a fast re-run posts duplicates), and fetches the RGBA PNG with the plate API's own loader. `plots.scatter_map(underlay=(rgba, extent))` prepends it as an xy truecolor `heatmap`. Three things there fail silently if changed. Image row 0 is the *top*, so the rows are flipped before xy sees them. xy takes cell *centres* and derives the edges, so passing the extent's edges as positions shifts the photo half a cell. xy divides RGB by 255 only when it sees a value above 1 and **never divides alpha**, so `scatter_map` scales all four channels itself: handed `uint8`, every partial alpha clips to opaque. Every map redraw republishes the photo, about 4 MiB of f32 planes at the 512 px default. That is why `BufferStore` bounds each panel by `FRAME_BUDGET_BYTES` (32 MiB, never fewer than `FRAME_MIN_KEEP` = 4 frames) as well as by the `FRAME_HISTORY` count: 512 photo frames per tab would be 2 GiB, and the budget keeps 7. `PlatePhotoState` is a mixin. `CompositionState` mixes it in directly, and `SpectraPageState` inherits it as a mixin of a mixin (the `LiveVisState` pattern), so the three spectra pages carry it without listing it, and each page still owns its own `photo_choice`.
```

- [ ] **Step 2: Full gate run**

Run each, one process per file (`cd /mnt/STORAGE/repos/helao/helao-underlay && conda run -n helao env PYTHONPATH=/mnt/STORAGE/repos/helao/helao-underlay python -m pytest -q -p no:cacheprovider helao/core/tests/<file>`), and record the counts:

`test_reflex_xy_component.py` (40), `test_plate_photo.py` (21), `test_reflex_plate_photo.py` (12), `test_reflex_plate_photo_pages.py` (20), `test_reflex_plots.py` (52), `test_reflex_composition.py` (39), `test_reflex_uvvis.py` (7), `test_xrds.py` (4), `test_xafs.py` (10), `test_reflex_routes_e2e.py` (21), `test_reflex_config.py` (32), `test_palette.py` (183), `test_reflex_panels.py` (63).

Then:
- `cd /mnt/STORAGE/repos/helao/helao-underlay && conda run -n helao env PYTHONPATH=/mnt/STORAGE/repos/helao/helao-underlay python run_tests.py --filter reflex`. Expected: `25 files`, `PASS 25`, `ALL GREEN`. `run_tests.py` sets each child's `PYTHONPATH` to its own repo root, so it tests the worktree.
- `cd /mnt/STORAGE/repos/helao/helao-underlay && conda run -n helao env PYTHONPATH=/mnt/STORAGE/repos/helao/helao-underlay python run_unit_tests.py`. Expected: exit status 0, as on cec43b68 (the pre-launch gate). Its log carries `RuntimeError: exp hook boom` tracebacks; those come from a deliberate failing-hook fixture and are not a failure.
- Task 5 Step 8's pyright run again, with `helao/ui/reflex/xy_component.py` added to the file list. Expected: `filesAnalyzed: 9`, `errorCount: 7`: the same six, plus `xy_component.py`'s pre-existing `Method "add_imports" overrides class "Component" in an incompatible manner` (also present on cec43b68).

- [ ] **Step 3: Write the visual check**

Create `/tmp/plate-photo-visual/visual.py`. It drives the production path: `plate_photo.load_image` through `plots.scatter_map(underlay=...)`, exactly as `_draw_map` does. It exports the figure `scatter_map` built and checks it in headless chromium.

```python
"""Throwaway visual check of the production underlay path in a browser.

Fixture mode (default): an asymmetric RGBA PNG served by the fake loader goes
through plate_photo.load_image and plots.scatter_map(underlay=...), exactly as
a page's _draw_map does, and is checked for flip, alpha, edge placement and
clicks. --live PLATE: the same path against the real plate API; screenshot
only.
"""

import io
import json
import pathlib
import sys

import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright

from helao.core.tests._plate_photo_fakes import (
    FakeLoader,
    FakePlateAPI,
    note,
    png_bytes,
)
from helao.ui.reflex import plots
from helao.ui.shared import plate_photo

OUT = pathlib.Path("/tmp/plate-photo-visual")
OUT.mkdir(parents=True, exist_ok=True)
FAILS = []


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'} {name} {detail}")
    if not ok:
        FAILS.append(name)


# Capture the figure scatter_map builds, so the export is the production one.
captured = {}
_publish = plots._publish


def _spy(figure, panel_id, version, *, layout_extra=""):
    captured["figure"] = figure
    return _publish(figure, panel_id, version, layout_extra=layout_extra)


plots._publish = _spy

live = "--live" in sys.argv
if live:
    from helao.helpers.plate_api import HTEPlateAPI
    from helao.ui.shared import platemap

    plate_id = int(sys.argv[sys.argv.index("--live") + 1])
    api = HTEPlateAPI()
    photos = plate_photo.underlays_for(api, plate_id)
    print("PHOTOS", [u.label for u in photos])
    if not photos:
        sys.exit(f"plate {plate_id} has no wafer-photo notes")
    chosen = next((u for u in photos if u.variant == "stretched"), photos[0])
    rows = platemap.platemap_rows(api.get_platemap_plateid(plate_id))
    xs = [r["x"] for r in rows]
    ys = [r["y"] for r in rows]
    values = [float(r["sample_no"]) for r in rows]
else:
    # 12 x 16: top half red | green, bottom half blue | transparent.
    img = np.zeros((12, 16, 4), dtype=np.uint8)
    img[:6, :8] = (255, 0, 0, 255)
    img[:6, 8:] = (0, 160, 0, 255)
    img[6:, :8] = (0, 0, 255, 255)
    entry = note(extent=((0.0, 64.0), (-8.0, 40.0)))
    api = FakePlateAPI(
        [entry], loader=FakeLoader({entry["image_s3_uri"]: png_bytes(img)})
    )
    chosen = plate_photo.underlays_for(api, 1)[0]
    xs, ys, values = [16.0, 48.0], [28.0, 4.0], [1.0, 2.0]

rgba = plate_photo.load_image(api, chosen)
plots.scatter_map(
    xs,
    ys,
    values=values,
    x_label="x (mm)",
    y_label="y (mm)",
    value_label="v",
    square=True,
    colorbar=True,
    underlay=(rgba, chosen.extent),
    panel_id="visual",
    version=1,
)
width, height = plots.square_width(520), 520
html = OUT / "visual.html"
captured["figure"].figure().to_html(
    str(html), custom_css=f"#chart{{width:{width}px;height:{height}px;}}"
)

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": width + 40, "height": height + 40})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(html.as_uri(), wait_until="load")
    page.wait_for_selector("canvas")
    page.wait_for_timeout(1500)
    shot_path = OUT / ("live.png" if live else "fixture.png")
    page.screenshot(path=str(shot_path))
    print("SCREENSHOT", shot_path)
    if not live:
        page.evaluate(
            "window.__clicks = []; document.addEventListener('xy:click',"
            " e => window.__clicks.push(e.detail), true)"
        )
        box = page.locator("canvas").first.bounding_box()

        def click_data(px, py):
            page.mouse.click(px, py)
            page.wait_for_timeout(150)
            d = page.evaluate("window.__clicks[window.__clicks.length - 1] || null")
            return None if d is None else (d.get("x"), d.get("y"))

        pa = (box["x"] + 0.30 * box["width"], box["y"] + 0.70 * box["height"])
        pb = (box["x"] + 0.60 * box["width"], box["y"] + 0.30 * box["height"])
        da, db = click_data(*pa), click_data(*pb)
        check("clicks over the photo report x/y", da is not None and db is not None)
        if da is None or db is None:
            sys.exit(1)
        sx = (pb[0] - pa[0]) / (db[0] - da[0])
        sy = (pb[1] - pa[1]) / (db[1] - da[1])

        def to_px(x, y):
            return pa[0] + (x - da[0]) * sx, pa[1] + (y - da[1]) * sy

        shot = Image.open(io.BytesIO(page.screenshot())).convert("RGB")

        def rgb(x, y):
            px, py = to_px(x, y)
            return shot.getpixel((int(round(px)), int(round(py))))

        def is_red(c):
            return c[0] > c[1] + 40 and c[0] > c[2] + 40

        bg = rgb(-2.0, 16.0)  # inside the plot, left of the photo
        red, green, blue, clear = rgb(6, 34), rgb(58, 34), rgb(6, -4), rgb(58, -4)
        print(f"MEASURE bg={bg} red={red} green={green} blue={blue} clear={clear}")
        check("not flipped: top-left is red", is_red(red))
        check(
            "top-right is green", green[1] > green[0] + 40 and green[1] > green[2] + 40
        )
        check("bottom-left is blue", blue[2] > blue[0] + 40 and blue[2] > blue[1] + 40)
        check(
            "alpha 0 is see-through", max(abs(a - b) for a, b in zip(clear, bg)) <= 6
        )
        mm_per_px = abs(1.0 / sx)
        left = next(
            (
                da[0] + (px - pa[0]) / sx
                for px in range(int(to_px(-10, 34)[0]), int(to_px(10, 34)[0]))
                if is_red(shot.getpixel((px, int(round(to_px(0, 34)[1])))))
            ),
            None,
        )
        top = next(
            (
                da[1] + (py - pa[1]) / sy
                for py in range(int(to_px(6, 50)[1]), int(to_px(6, 30)[1]))
                if is_red(shot.getpixel((int(round(to_px(6, 0)[0])), py)))
            ),
            None,
        )
        print(f"MEASURE left_edge={left} top_edge={top} mm_per_px={mm_per_px:.3f}")
        check(
            "left edge at x_min", left is not None and abs(left - 0.0) <= 2 * mm_per_px
        )
        check(
            "top edge at y_max", top is not None and abs(top - 40.0) <= 2 * mm_per_px
        )
        dc = click_data(*to_px(58.0, -4.0))
        check(
            "click on the transparent region reports x/y",
            dc is not None and abs(dc[0] - 58.0) < 2 and abs(dc[1] + 4.0) < 2,
            str(dc),
        )
    check("no page errors", not errors, str(errors))
    browser.close()

print(json.dumps({"FAILS": FAILS}))
sys.exit(1 if FAILS else 0)
```

- [ ] **Step 4: Run the fixture visual**

Run: `cd /mnt/STORAGE/repos/helao/helao-underlay && conda run -n helao env PYTHONPATH=/mnt/STORAGE/repos/helao/helao-underlay python /tmp/plate-photo-visual/visual.py`

Expected (the planner's run of this script against a scratch copy carrying Tasks 1-4):

```
SCREENSHOT /tmp/plate-photo-visual/fixture.png
PASS clicks over the photo report x/y
MEASURE bg=(255, 255, 255) red=(255, 102, 102) green=(102, 198, 102) blue=(102, 102, 255) clear=(255, 255, 255)
PASS not flipped: top-left is red
PASS top-right is green
PASS bottom-left is blue
PASS alpha 0 is see-through
MEASURE left_edge=0.01... top_edge=40.02... mm_per_px=0.153
PASS left edge at x_min
PASS top edge at y_max
PASS click on the transparent region reports x/y ...
PASS no page errors []
{"FAILS": []}
```

Open `/tmp/plate-photo-visual/fixture.png`. Expected: a square map with the colorbar on the right, the photo's red top-left, green top-right and blue bottom-left at 0.6 opacity, the bottom-right quadrant white, and the two points drawn over it. Any `FAIL` is a STOP.

- [ ] **Step 5: Live visual (only where `HELAO_CREDENTIALS` is readable and the plate API is reachable)**

Run: `cd /mnt/STORAGE/repos/helao/helao-underlay && conda run -n helao env PYTHONPATH=/mnt/STORAGE/repos/helao/helao-underlay python /tmp/plate-photo-visual/visual.py --live 10197`

Expected: a `PHOTOS [...]` line listing the plate's photos in dropdown order, then `SCREENSHOT /tmp/plate-photo-visual/live.png`. In the screenshot the sample points should sit on the wafer, and the flat chord should sit at y = 0. Without credentials, report "live visual not run: no credentials on this machine". This is the spec's "otherwise use the fixture" branch. A full `/xrds` page check against the live API stays with the controller, on a station with internet.

- [ ] **Step 6: Report and hand back**

Report every count from Step 2, the pyright summary, the visual `PASS`/`MEASURE` lines, and the screenshot paths.

- [ ] **Step 7: Controller commits (implementer does NOT run git add/commit)**

Nothing to black (markdown only). The controller commits `helao/ui/reflex/CLAUDE.md` as `docs(reflex): note the plate-photo underlay and its three silent traps`.

---

## Self-review against the spec

| Spec item | Task |
|---|---|
| `Underlay` fields, `parse_note`, `underlays_for` (newest per `(input_png, variant)`, ordering, `[]` cases, errors propagate) | 1 |
| `load_image` (loader, PIL RGBA uint8, area-filter downsample, LRU, `UNDERLAY_MAX_PX = 512`) | 1 |
| Per-panel byte budget (`FRAME_BUDGET_BYTES`, `FRAME_MIN_KEEP`, `FRAME_HISTORY` as count cap) | 2 |
| `scatter_map(underlay, underlay_opacity=0.6)`: flip, cell centres, alpha scaling, `marks[0]`, domain covers extent, token identity, `None` byte-identical, clicks unchanged | 3 (clicks: 5 and 6) |
| `PlatePhotoState` vars, `_load_photos`, `_underlay_arg`, setters, `photo_controls` | 4 |
| Mixed into `CompositionState` and the `SpectraPageState` mixin; `retrieve` wiring; `_draw_map` call sites; controls placement | 5 |
| Error table: no API, no credentials, no notes, lookup raises, image fetch fails, no platemap rows (unchanged early return) | 4 (all five notes), 5 (retrieve proceeds) |
| Task 0 probe (alpha, flip, placement, clicks, frame bytes at 512 px, mixin-of-mixin on four page shapes) | 0 |
| Gates: `test_reflex_config.py`, `test_palette.py`, composition and spectra page tests, `test_reflex_xy_component.py` | 1-6 |
| Visual: fixture, plus live plate 10197 when credentials exist | 6 |
| CLAUDE.md bullet | 6 |
