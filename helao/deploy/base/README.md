# base: framework services

Tracked in helao-async. Holds the server modules every deployment launches:
`orchestrator/` (async_orch2), `operator/` (standalone_operator), `visualizer/`
(action/live/control visualizers, data_browser, shared Bokeh panels), `sync/`
(sync_server) and `reflex/` (shared Reflex panel helpers). Configs name these
modules bare (`fast: async_orch2`); the launcher finds them here. A module name
in `base` must exist in no other deployment (`tests/test_base_modules_unique.py`).
Instrument servers and drivers live in their deployments, not here.
