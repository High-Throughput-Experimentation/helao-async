"""Endpoint override composition (P4b step 1). Exercises
``overlay_dyn_endpoints`` against a synthetic ``BaseAPI``-shaped app -- a
plain ``FastAPI`` instance with a ``.base.server.server_name`` stand-in,
mirroring the bare-``Base`` fixture pattern in ``native_fixtures.py`` -- so
no legacy driver/config machinery is needed."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from helao.core.models.machine import MachineModel
from helao.hexagon.app.endpoint_overlay import (
    EndpointOverlayError,
    overlay_dyn_endpoints,
)

SERVER_KEY = "ACTSRV"


def make_app() -> FastAPI:
    app = FastAPI()
    app.base = SimpleNamespace(  # type: ignore[attr-defined]
        server=MachineModel(server_name=SERVER_KEY)
    )
    return app


def route_paths(app: FastAPI):
    return [r.path_format for r in app.router.routes]  # type: ignore[attr-defined]


def action_route_paths(app: FastAPI):
    """Just this server's action routes -- ``app.setup()`` unconditionally
    re-appends the docs/openapi/redoc bookkeeping routes every time it runs
    (both the overlay and the legacy sequence call it once), so those must
    be excluded to see the position that actually matters."""
    return [p for p in route_paths(app) if p.startswith(f"/{SERVER_KEY}/")]


async def base_registrar(app: FastAPI) -> None:
    """Stand-in for a shared driver family's standard ``dyn_endpoints`` hook:
    registers two routes, one of which a deployment will override."""

    @app.post(f"/{SERVER_KEY}/run_CP", tags=["action"])
    async def run_CP():
        return {"variant": "base"}

    @app.post(f"/{SERVER_KEY}/run_CA", tags=["action"])
    async def run_CA():
        return {"variant": "base"}


async def override_registrar(app: FastAPI) -> None:
    """Stand-in for a deployment's versioned replacement of one endpoint."""

    @app.post(f"/{SERVER_KEY}/run_CP", tags=["action"])
    async def run_CP_v3(alert_above: bool = True):
        return {"variant": "v3", "alert_above": alert_above}


async def legacy_style_override(app: FastAPI) -> None:
    """The ad hoc pattern ``overlay_dyn_endpoints`` replaces: run the base
    registrar, scan+delete the target route by path, register a
    replacement, force one schema rebuild. Used as the ground truth for the
    route-ORDER invariant test below."""
    await base_registrar(app=app)

    target = f"/{SERVER_KEY}/run_CP"
    for i, r in enumerate(app.router.routes):
        if r.path_format == target:  # type: ignore[attr-defined]
            del app.router.routes[i]
            break

    @app.post(target, tags=["action"])
    async def run_CP_v3(alert_above: bool = True):
        return {"variant": "v3", "alert_above": alert_above}

    app.openapi_schema = None
    app.setup()


@pytest.mark.asyncio
async def test_override_replaces_the_handler():
    app = make_app()
    dyn_endpoints = overlay_dyn_endpoints(
        base_registrar, {"run_CP": override_registrar}
    )
    await dyn_endpoints(app=app)

    target = f"/{SERVER_KEY}/run_CP"
    matches = [
        r for r in app.router.routes if r.path_format == target  # type: ignore[attr-defined]
    ]
    assert len(matches) == 1  # never two routes at the same path
    assert matches[0].endpoint.__name__ == "run_CP_v3"  # type: ignore[attr-defined]
    # the untouched sibling route from the base registrar survives unchanged
    assert any(
        r.path_format == f"/{SERVER_KEY}/run_CA" for r in app.router.routes  # type: ignore[attr-defined]
    )


@pytest.mark.asyncio
async def test_override_lands_at_the_position_the_legacy_sequence_produces():
    """Route order is part of the frozen OpenAPI bytes some deployments diff
    against (spec Wire-visible risk #2) -- so this proves ORDER, not just
    presence, by comparing against a real delete-then-re-register sequence
    built independently on a second app."""
    overlaid = make_app()
    dyn_endpoints = overlay_dyn_endpoints(
        base_registrar, {"run_CP": override_registrar}
    )
    await dyn_endpoints(app=overlaid)

    legacy = make_app()
    await legacy_style_override(legacy)

    assert route_paths(overlaid) == route_paths(legacy)
    # and explicitly: the override is last among the two action routes (the
    # setup()-appended docs/openapi/redoc routes trail both sequences alike)
    assert action_route_paths(overlaid)[-1] == f"/{SERVER_KEY}/run_CP"


@pytest.mark.asyncio
async def test_missing_target_fails_loud_and_adds_nothing():
    app = make_app()
    dyn_endpoints = overlay_dyn_endpoints(
        base_registrar, {"run_CP_typo": override_registrar}
    )
    before = route_paths(app)  # empty pre-call; captured for symmetry
    with pytest.raises(EndpointOverlayError):
        await dyn_endpoints(app=app)

    # the base registrar's own routes registered before the failing
    # override are still there, but no shadow route for the typo'd target
    # was ever added
    assert f"/{SERVER_KEY}/run_CP_typo" not in route_paths(app)
    assert len(route_paths(app)) == len(before) + 2  # just run_CP + run_CA


@pytest.mark.asyncio
async def test_schema_rebuilt_exactly_once_across_multiple_overrides(monkeypatch):
    app = make_app()

    calls = []
    original_setup = app.setup

    def spy_setup():
        calls.append(1)
        return original_setup()

    monkeypatch.setattr(app, "setup", spy_setup)

    async def override_registrar_2(app: FastAPI) -> None:
        @app.post(f"/{SERVER_KEY}/run_CA", tags=["action"])
        async def run_CA_v2():
            return {"variant": "v2"}

    dyn_endpoints = overlay_dyn_endpoints(
        base_registrar,
        {"run_CP": override_registrar, "run_CA": override_registrar_2},
    )
    await dyn_endpoints(app=app)

    assert len(calls) == 1  # not once per override


@pytest.mark.asyncio
async def test_overlay_with_no_overrides_still_rebuilds_schema_once(monkeypatch):
    app = make_app()
    calls = []
    original_setup = app.setup
    monkeypatch.setattr(app, "setup", lambda: (calls.append(1), original_setup()))

    dyn_endpoints = overlay_dyn_endpoints(base_registrar, {})
    await dyn_endpoints(app=app)

    assert len(calls) == 1
    assert action_route_paths(app) == [f"/{SERVER_KEY}/run_CP", f"/{SERVER_KEY}/run_CA"]
