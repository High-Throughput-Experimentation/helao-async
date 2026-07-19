# P3d — hte visualizers (mostly landed by P2d)

> Sub-project of P3. Linux-complete.

**Outcome (2026-07-18 — COMPLETE for the Linux surface).** Branch `feat/p3d-vis-import`.

- The two launched Bokeh **hosts** (`action_visualizer`, `live_visualizer`) already have hexagon shims under `helao/deploy/hexagon/servers/visualizer/` from P2d (`makeVisApp` compat-facade), and they already point at the hte legacy modules — no new host shims needed.
- The 12 per-instrument `*_vis` modules are mounted **in-process** by the hosts via `vis_subscriber`, selected by `action_vis:`/`live_vis:` config keys — they are not separately launched, so their whole Linux surface is *import*. All 15 hte visualizer modules import on Linux (0 fail).
- Added `helao/hexagon/tests/test_hte_vis_import.py` (18 passed): 15-module import sweep + host-shim assertions.

**Deferred / at-station:** actual Bokeh render + WS subscription behavior is a browser/station smoke item (per-station gate). Native vis hosting (ConfigPort/WsSubscriber adapters replacing the compat-facade) is post-parity native work, not a P3 parity gate. `data_browser` standalone launch (if a config launches it as its own bokeh app) uses the same compat-facade route if/when a config needs it.
