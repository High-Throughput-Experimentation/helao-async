"""Browser-side measurement primitives for the rendered-parity lane.

Three things are measured here that nothing else in this repo measures:

1. **Computed colour, resolved to sRGB.** Tailwind v4's palette is OKLCH-native,
   so ``getComputedStyle(el).backgroundColor`` returns ``oklch(0.555 0.163
   48.998)`` rather than an ``rgb()`` triple -- CSS Color 4 colours compute to
   their own space. Comparing that string to a hex constant is meaningless, and
   re-implementing the OKLCH transform in Python would be a second
   implementation to disagree with the browser's. :func:`to_srgb` instead asks
   the browser: a 1x1 2D canvas parses any CSS colour and rasterizes it to the
   sRGB the compositor will actually paint. The number that comes back is the
   pixel, not a model of it.

2. **Drawn content, from a screenshot -- never ``toDataURL``.** ``toDataURL``
   on a WebGL canvas returns an empty buffer unless the context was created
   with ``preserveDrawingBuffer: true``, which ``xy`` does not set. Measured on
   a live ``/live`` page whose chart was visibly drawing six data series:
   ``toDataURL`` reported **1 distinct colour**, an element screenshot reported
   **16717**. A drawn-content gate built on ``toDataURL`` would therefore fail
   on every correctly-drawing WebGL chart, and -- worse -- a gate that then
   loosened its threshold to make that pass would assert nothing at all.
   :func:`canvas_ink` screenshots the element.

3. **Live WebGL contexts, by instrumenting their creation.** There is no
   browser API that reports how many contexts are alive, and counting
   ``<canvas>`` elements is not a substitute: measured on ``/live``, six canvas
   elements carried **two** WebGL contexts (``xy`` draws its axes and overlays
   on ordinary 2D canvases). :data:`INSTRUMENT_JS` wraps
   ``HTMLCanvasElement.prototype.getContext`` before any page script runs,
   counting WebGL context creations and subscribing each canvas to
   ``webglcontextlost``. Live count is created minus lost, and a non-zero lost
   count is the eviction signal itself.

The instrumentation must be installed with ``page.add_init_script`` (it has to
beat the page's own scripts to the prototype), which is why pages come from
:func:`new_page` rather than being built by callers.
"""

__all__ = [
    "INSTRUMENT_JS",
    "Measurement",
    "canvas_ink",
    "contrast",
    "element_colors",
    "gl_stats",
    "new_page",
    "page_problems",
    "to_srgb",
]

import base64
import io
from dataclasses import dataclass, field
from typing import Any, Optional

#: Installed before every page script. Two jobs, both of which must happen
#: before the application loads: wrapping ``getContext`` (a page that has
#: already made its contexts cannot be retro-instrumented) and defining the
#: sRGB rasterizer used by :func:`to_srgb`.
INSTRUMENT_JS = """
window.__helao_gl = {created: 0, lost: 0, restored: 0, types: []};
(() => {
  const original = HTMLCanvasElement.prototype.getContext;
  HTMLCanvasElement.prototype.getContext = function (type, ...rest) {
    const context = original.call(this, type, ...rest);
    // Only a *successful* WebGL request consumes one of the browser's 16
    // slots. Counting the request instead would count every probe that asked
    // a 2D canvas for a WebGL context and was refused.
    if (context && /webgl/i.test(String(type))) {
      if (!this.__helao_counted) {
        this.__helao_counted = true;
        window.__helao_gl.created += 1;
        window.__helao_gl.types.push(String(type));
        this.addEventListener('webglcontextlost', () => {
          window.__helao_gl.lost += 1;
        });
        this.addEventListener('webglcontextrestored', () => {
          window.__helao_gl.restored += 1;
        });
      }
    }
    return context;
  };
})();

// Rasterize any CSS colour to the sRGB bytes the compositor paints. The
// canvas is 1x1 and reused per call; `willReadFrequently` keeps Chrome from
// promoting it to the GPU, which would make it one more context to evict.
window.__helao_srgb = (value) => {
  const canvas = document.createElement('canvas');
  canvas.width = 1;
  canvas.height = 1;
  const ctx = canvas.getContext('2d', {willReadFrequently: true});
  ctx.clearRect(0, 0, 1, 1);
  // Paint white underneath: a translucent colour has to be composited against
  // something, and the surfaces these colours sit on are light. Without this
  // an rgba(255,255,255,0.85) field reads as pure white on transparent black.
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, 1, 1);
  ctx.fillStyle = value;
  ctx.fillRect(0, 0, 1, 1);
  const data = ctx.getImageData(0, 0, 1, 1).data;
  return [data[0], data[1], data[2]];
};
"""


@dataclass
class Measurement:
    """One route's or document's extracted values, plus its failures.

    ``values`` is what the legacy-vs-hexagon matrix diff compares; ``problems``
    is what makes the check exit non-zero. They are separate because a value
    can legitimately differ between two runs (a timestamp, a queue length)
    while still being a pass, and because a diff of *failures* would report the
    same defect twice.
    """

    name: str
    values: dict = field(default_factory=dict)
    problems: list = field(default_factory=list)

    def record(self, key: str, value: Any) -> None:
        """Store one comparable value."""
        self.values[key] = value

    def fail(self, message: str) -> None:
        """Record one failure against this route."""
        self.problems.append(f"{self.name}: {message}")

    def require(self, condition: bool, message: str) -> bool:
        """Record *message* unless *condition* holds; return the condition.

        Returning the condition is what lets a caller gate a style measurement
        on the content assertion that must precede it, in one expression:
        ``if m.require(count > 0, "..."): measure()``.
        """
        if not condition:
            self.fail(message)
        return condition


def new_page(browser, errors: Optional[list] = None):
    """Open an instrumented page, capturing page and console errors.

    Args:
        browser: A Playwright browser.
        errors: List to append captured browser errors to. One is created when
            omitted, but callers that want the errors pass their own.

    Returns:
        tuple: ``(page, errors)``.
    """
    if errors is None:
        errors = []
    page = browser.new_page()
    page.add_init_script(INSTRUMENT_JS)
    page.on("pageerror", lambda exc: errors.append(str(exc)[:300]))
    page.on(
        "console",
        lambda msg: errors.append(msg.text[:200]) if msg.type == "error" else None,
    )
    # The WebGL eviction warning arrives as a console *warning*, not an error,
    # and it is the single most important line this lane can see -- it is the
    # only server-visible trace of a chart that will never draw again.
    page.on(
        "console",
        lambda msg: (
            errors.append(f"WEBGL-EVICTION: {msg.text[:200]}")
            if msg.type == "warning" and "WebGL context" in msg.text
            else None
        ),
    )
    return page, errors


def page_problems(errors: list) -> list:
    """Filter captured browser noise down to real problems.

    A missing favicon is not a rendering defect and every page in both stacks
    reports one.
    """
    return [e for e in errors if "favicon" not in e]


def to_srgb(page, css_color: str) -> tuple:
    """Resolve a CSS colour string to the sRGB bytes the browser paints.

    Args:
        page: An instrumented page (see :func:`new_page`).
        css_color: Any CSS colour -- ``oklch(...)``, ``rgb(...)``, a keyword.

    Returns:
        tuple: ``(r, g, b)``, each 0-255.
    """
    return tuple(page.evaluate("(c) => window.__helao_srgb(c)", css_color))


def _linearize(channel: int) -> float:
    c = channel / 255.0
    # Same pinned constants as helao/core/tests/test_palette.py. Pinned rather
    # than imported because the two must be able to disagree: this file
    # measures the browser, that one measures the palette, and a shared
    # constant that drifted would move both readings together and hide it.
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _luminance(rgb: tuple) -> float:
    r, g, b = (_linearize(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: tuple, b: tuple) -> float:
    """WCAG 2.x contrast ratio between two measured sRGB triples.

    This is the assertion the OKLCH finding forces. A computed style will not
    equal ``palette.py``'s hex -- measured, Tailwind v4 renders ``red-900`` as
    ``rgb(130,24,26)`` against the pinned ``#7f1d1d`` = ``rgb(127,29,29)``, and
    saturated 600/700 shades diverge much further. Contrast is the property the
    palette actually promises, it is measurable on the pixels that shipped, and
    it comes out *better* in the browser than the published figure rather than
    worse -- so asserting it is both meaningful and safe.
    """
    la, lb = _luminance(a), _luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return round((lighter + 0.05) / (darker + 0.05), 2)


def element_colors(page, selector: str, index: int = 0) -> Optional[dict]:
    """Measured foreground and background sRGB of one element.

    Returns ``None`` when the selector matches nothing -- the caller must treat
    that as a failure rather than as a colour, which is the vacuity trap this
    whole package is built around.
    """
    locator = page.locator(selector)
    if locator.count() <= index:
        return None
    element = locator.nth(index)
    raw = element.evaluate("""(el) => {
            const s = getComputedStyle(el);
            return {fg: s.color, bg: s.backgroundColor, cls: el.className};
        }""")
    return {
        "fg": to_srgb(page, raw["fg"]),
        "bg": to_srgb(page, raw["bg"]),
        "class": str(raw["cls"]),
    }


def gl_stats(page) -> dict:
    """Live WebGL context counts for the current page.

    ``live`` is created minus lost. ``lost`` above zero means Chrome evicted a
    context: that chart is dead for the life of the page and nothing else --
    server-side or client-side -- will say so.
    """
    stats = page.evaluate("() => window.__helao_gl")
    stats["live"] = stats["created"] - stats["lost"]
    return stats


def canvas_ink(page, selector: str = "canvas", index: int = 0) -> dict:
    """How much a canvas actually drew, from its composited pixels.

    Screenshots the element and counts distinct colours plus the share of
    pixels differing from the modal (background) colour. An empty chart is not
    a blank image -- it still has axes, gridlines and labels -- so the useful
    signal is the *magnitude*: measured on one live page, a chart with six data
    series showed ~16700 distinct colours while its empty twin showed 3, and an
    axes-only frame showed 249.

    Returns:
        dict: ``{"distinct": int, "ink": float, "size": [w, h]}``, or
        ``{"error": str}`` if the element could not be captured.
    """
    from PIL import Image

    locator = page.locator(selector)
    if locator.count() <= index:
        return {"error": "no such canvas"}
    try:
        shot = locator.nth(index).screenshot()
    except Exception as exc:  # an element scrolled out of view, a zero-size box
        return {"error": f"{type(exc).__name__}: {exc}"}
    image = Image.open(io.BytesIO(shot)).convert("RGB")
    colors = image.getcolors(maxcolors=1 << 20)
    if colors is None:
        # More than a million distinct colours: unambiguously drawn.
        return {"distinct": 1 << 20, "ink": 1.0, "size": list(image.size)}
    total = sum(count for count, _ in colors)
    modal = max(count for count, _ in colors)
    return {
        "distinct": len(colors),
        "ink": round(1.0 - modal / total, 4),
        "size": list(image.size),
    }


def png_of(page, selector: str, index: int = 0) -> str:
    """Base64 PNG of one element, for a human looking at a failure.

    Never asserted on: screenshots diff on antialiasing, which is exactly why
    the matrix compares extracted *values*. This exists so a failing run can
    hand back something to look at.
    """
    locator = page.locator(selector)
    if locator.count() <= index:
        return ""
    return base64.b64encode(locator.nth(index).screenshot()).decode()
