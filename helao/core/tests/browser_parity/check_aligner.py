"""Rendered check of the plate-aligner Bokeh document, hosted through P7d.

The aligner is the one Bokeh document in the tree that no launcher serves: its
``Server`` is built inside the Galil motion *action server* process. P7d moved
that construction behind ``ports.ui_host.UiHostPort`` so
``GalilAlignerHost`` no longer imports ``bokeh`` at all -- which is also what
makes this check possible, because the host can now be handed a ``ui_host`` and
a driver by a test instead of by a motion server holding a Galil card.

**What this does and does not prove, stated plainly.** ``gclib`` is
Windows-only and there is no Galil simulator, so nothing here drives real
motion. What it does cover is everything between the port and the pixels: the
P7d composition starts a document host, ``HelaoVis`` applies the theme to a
document that never passes through ``bokeh_launcher.py`` (the reason
``apply_theme`` lives in ``HelaoVis.__init__`` at all), ``Aligner`` builds its
1685-line layout, and a browser renders it. The plate-alignment *procedure* --
picking markers on a real plate and computing a transfer matrix against a
moving stage -- remains an at-station dry run and this check does not claim
otherwise.

The driver below is a stand-in, not a simulator: it answers the handful of
attributes ``AlignerMotorContext`` delegates and records what was asked of it.
It deliberately does **not** emulate motion -- a fake that pretended to move
would invite exactly the "it passed on Linux" conclusion this docstring exists
to prevent.

Run it standalone; it needs no orchestration group::

    python helao/core/tests/browser_parity/check_aligner.py
"""

import json
import logging
import sys
import threading
import time

#: Port the stand-in motion server's config claims. The aligner derives its own
#: port as ``port + 1000``, exactly as a station does.
MOTOR_PORT = 8092
ALIGNER_PORT = MOTOR_PORT + 1000

#: Bokeh needs a websocket round trip before its widgets exist.
SETTLE_MS = 12000


class StandInMotor:
    """The attributes ``AlignerMotorContext`` delegates to a Galil driver.

    Not a simulator. Every method records the call and returns the shape the
    aligner expects, so the document builds and renders; none of them move
    anything, and ``moved`` staying empty is part of the point.
    """

    def __init__(self):
        import numpy as np

        self.identity = np.matrix([[1.0, 0, 0], [0, 1.0, 0], [0, 0, 1.0]])
        self.transfermatrix = self.identity.copy()
        self.blocked = False
        self.motor_busy = False
        self.galil_enabled = True
        self.position_sink = None
        self.moved: list = []
        self.saved: list = []

    def set_position_sink(self, queue) -> None:
        """Receive the aligner's position queue, as the real driver does."""
        self.position_sink = queue

    @property
    def transform(self):
        """The transformer object the aligner reads matrices off."""
        return self

    def transform_motorxy_to_platexy(self, motorxy, *args, **kwargs):
        """Identity transform. The aligner's IO loop calls this every tick.

        Present because it is *called at runtime*, not because the document
        needs it to build: without it the layout renders perfectly and the IO
        loop then raises ``AttributeError`` on every tick, server-side, where
        no browser-side error capture can see it. That is why this check reads
        the log for exceptions as well as the page for elements.
        """
        import numpy as np

        return np.array(motorxy)

    def get_Mplate_Msystem(self, matrix, *args, **kwargs):
        """The plate-to-system matrix the aligner reads back after a calc."""
        return self.identity

    @property
    def file_backup_transfermatrix(self):
        return None

    @property
    def dflt_matrix(self):
        return self.identity

    @property
    def plate_transfermatrix(self):
        return self.transfermatrix

    def update_plate_transfermatrix(self, newtransfermatrix):
        self.transfermatrix = newtransfermatrix
        return self.transfermatrix

    def save_transfermatrix(self, file):
        self.saved.append(file)

    async def _motor_move(self, *args, **kwargs) -> dict:
        self.moved.append((args, kwargs))
        return {"err_code": 0}

    async def query_axis_position(self, *args, **kwargs) -> dict:
        return {"ax": [], "position": []}

    async def query_axis_moving(self, *args, **kwargs) -> dict:
        return {"motor_status": [], "err_code": 0}


class StandInBase:
    """The two attributes the aligner reads off a ``Base``."""

    def __init__(self, world_cfg: dict, server_key: str):
        from helao.helpers.helao_dirs import helao_dirs

        self.helaodirs = helao_dirs(world_cfg, server_key)
        self.world_cfg = world_cfg

    def get_main_error(self, *args, **kwargs):
        from helao.core.error import ErrorCodes

        return ErrorCodes.none


def build_config(root: str) -> dict:
    """The smallest world config the aligner's host will accept."""
    return {
        "dummy": True,
        "simulation": True,
        "run_type": "simulation",
        "root": root,
        "servers": {
            "MOTOR": {
                "host": "127.0.0.1",
                "port": MOTOR_PORT,
                "group": "action",
                "fast": "galil_motion",
                "params": {"doc_name": "Plate Aligner (P7j rendered check)"},
            }
        },
    }


def start_host(root: str):
    """Compose and start the P7d aligner host on a background IO loop.

    Returns:
        tuple: ``(host, motor)``.
    """
    from helao.helpers import config_loader
    from helao.hexagon.adapters.vis.galil_aligner_host import GalilAlignerHost
    from helao.hexagon.app.ui_host import BokehServerUiHost

    world_cfg = build_config(root)
    world_cfg["loaded_config_path"] = __file__
    config_loader.CONFIG = world_cfg

    motor = StandInMotor()
    base = StandInBase(world_cfg, "MOTOR")
    host = GalilAlignerHost(
        driver=motor,
        base=base,
        server_cfg=world_cfg["servers"]["MOTOR"],
        server_name="MOTOR",
        config=world_cfg["servers"]["MOTOR"]["params"],
        ui_host=BokehServerUiHost(),
    )

    # Bokeh's Server wants a running IO loop of its own. A station gets one
    # from the action server's event loop; here it gets a thread.
    started = threading.Event()
    failure: list = []

    def serve():
        import asyncio

        from tornado.ioloop import IOLoop

        asyncio.set_event_loop(asyncio.new_event_loop())
        try:
            host.start()
        except Exception as exc:  # surfaced to the caller, not swallowed
            failure.append(exc)
            started.set()
            return
        started.set()
        IOLoop.current().start()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    started.wait(timeout=60)
    if failure:
        raise failure[0]
    return host, motor


def measure(measurement, page) -> None:
    """Load the aligner document and assert it built and was themed."""
    from helao.core.servers.palette import PAGE_BG
    from helao.core.tests.browser_parity.probe import to_srgb

    page.goto(
        f"http://127.0.0.1:{ALIGNER_PORT}/Aligner", wait_until="load", timeout=60000
    )
    page.wait_for_timeout(SETTLE_MS)

    measurement.record("doc_title", page.title())

    # Content first: a document that failed to build still themes its <body>.
    divs = page.locator("div").count()
    buttons = page.locator("button").count()
    measurement.record("div_count_band", divs // 50)
    measurement.record("button_count", buttons)
    if not measurement.require(
        divs > 50 and buttons > 5,
        f"the aligner document did not build ({divs} divs, {buttons} buttons)",
    ):
        return

    # The theme reaches this document only because apply_theme is called from
    # HelaoVis.__init__ -- no per-factory call could, since this Server is
    # built inside an action-server process. That is the claim being checked.
    raw = page.evaluate("() => getComputedStyle(document.body).backgroundColor")
    canvas = to_srgb(page, raw)
    expected = tuple(int(PAGE_BG.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
    drift = max(abs(a - b) for a, b in zip(canvas, expected))
    measurement.record("page_bg_rgb", list(canvas))
    measurement.record("page_bg_drift", drift)
    measurement.require(
        drift <= 1,
        f"the aligner canvas renders {canvas}, expected PAGE_BG {expected}: "
        f"apply_theme did not reach a document no launcher serves",
    )

    # The marker chips are `default` buttons carrying a per-widget override.
    # They are the reason semantic_button_stylesheet() must never emit a
    # blanket .bk-btn-default rule, and this is the only document that has
    # them -- so it is the only place the collision could be observed.
    chips = page.locator(".bk-btn-default")
    measurement.record("default_button_count", chips.count())
    measurement.require(chips.count() > 0, "no marker chips rendered")

    # The plate map is a Bokeh figure: a canvas that has painted.
    canvases = page.locator("canvas")
    measurement.record("canvas_count", canvases.count())
    if measurement.require(canvases.count() > 0, "the plate map did not render"):
        from helao.core.tests.browser_parity.probe import canvas_ink

        inks = [
            canvas_ink(page, "canvas", index).get("distinct", -1)
            for index in range(canvases.count())
        ]
        measurement.record("canvas_any_painted", any(i > 20 for i in inks))
        measurement.record("canvas_ink_distinct", max(inks) if inks else -1)
        measurement.require(
            any(i > 20 for i in inks),
            f"no canvas on the aligner painted anything ({inks})",
        )


class ExceptionTrap(logging.Handler):
    """Collect every exception logged while the document is up.

    **The reason this exists is worth stating.** The first run of this check
    passed with ``AttributeError`` being raised on every tick of the aligner's
    IO loop: the layout had already rendered, the browser saw no error (the
    exception is server-side), and every element assertion was satisfied. A
    rendered check that only looks at the page cannot see a document whose
    update loop is dead -- which is the same shape as the WebGL-eviction
    failure, one process over.
    """

    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.records: list = []

    def emit(self, record) -> None:
        if record.exc_info or record.levelno >= logging.ERROR:
            self.records.append(record.getMessage()[:200])


def run(root: str = "/tmp/helao_aligner_check") -> tuple:
    """Host the aligner, measure it, and report."""
    import os

    from playwright.sync_api import sync_playwright

    from helao.core.tests.browser_parity.probe import (
        Measurement,
        new_page,
        page_problems,
    )

    os.makedirs(root, exist_ok=True)
    measurement = Measurement("aligner")
    trap = ExceptionTrap()
    logging.getLogger().addHandler(trap)
    host, motor = start_host(root)
    time.sleep(2)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page, errors = new_page(browser)
            measure(measurement, page)
            browser.close()
    finally:
        try:
            host.shutdown()
        except Exception:  # teardown of a stand-in host is best effort
            pass
        logging.getLogger().removeHandler(trap)

    measurement.record("logged_errors", len(trap.records))
    measurement.require(
        not trap.records,
        f"the aligner logged {len(trap.records)} error(s) while rendering, "
        f"which no browser-side check can see: {trap.records[:3]}",
    )

    # The stand-in must not have been driven. If the document's construction
    # started moving a stage, this check would be doing something at a station
    # that nobody asked for.
    measurement.record("motor_moves", len(motor.moved))
    measurement.require(
        not motor.moved, f"building the document issued {len(motor.moved)} moves"
    )

    problems = list(measurement.problems)
    real_errors = page_problems(errors)
    if real_errors:
        problems.append(f"browser errors: {real_errors[:5]}")
    return [measurement], problems


def main() -> int:
    """CLI: ``check_aligner.py [--json out.json]``."""
    out = None
    for index, arg in enumerate(sys.argv):
        if arg == "--json" and index + 1 < len(sys.argv):
            out = sys.argv[index + 1]
    measurements, problems = run()
    if out:
        from helao.core.tests.browser_parity.matrix import save_matrix

        save_matrix(out, "aligner", measurements)
        print(f"matrix written to {out}")
    for m in measurements:
        print(f"  {m.name}: {json.dumps(m.values, sort_keys=True)}")
    if problems:
        for problem in problems:
            print(f"FAIL: {problem}")
        return 1
    print("PASS: the aligner document rendered through the P7d ui_host port")
    return 0


if __name__ == "__main__":
    sys.exit(main())
