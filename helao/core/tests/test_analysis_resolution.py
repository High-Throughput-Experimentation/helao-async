"""Which package an analysis server loads its ``analyze_*`` classes from, and
what happens when one of them cannot be loaded.

Both halves are regression tests for the same defect. ``fast_launcher`` sets
``CONFIG["deployment"]`` from the server's OWN ``deployment:`` value, so a
server grafted onto the hexagon composition (``deployment: hexagon`` plus a
``legacy_module:``) used to look for its analyses under
``helao.deploy.hexagon.drivers.data.analyses`` — a package that does not
exist. Every import missed, every miss was logged and skipped, and the server
started clean with all of its ``analyze_*`` routes missing.

Everything here runs against the tracked ``hte`` deployment, so it passes on a
checkout carrying no private deployments at all. No network, no hardware and no
credentials: ``BaseAPI`` registers its routes at construction, while the driver
(and its S3 client) is only built from a startup event these tests never fire.
"""

import pytest

from helao.core.drivers.data import analysis_driver as m

#: Two analysis modules that really live in the tracked ``hte`` deployment.
HTE_ANALYSES = ["echeuvis_stability", "uvis_bkgsubnorm"]

#: The endpoint names those two must produce, whatever the composition. Pinned
#: as a set rather than "non-empty": a length check would pass for the wrong
#: package the moment any one module happened to resolve.
HTE_ENDPOINTS = {"analyze_echeuvis_stability", "analyze_uvis_bkgsubnorm"}

HTE_PKG = "helao.deploy.hte.drivers.data.analyses"

#: What a hexagon-grafted hte analysis server carries in its config.
HTE_LEGACY_MODULE = "helao.deploy.hte.servers.action.analysis_server"


# ---------------------------------------------------------------------------
# Package resolution
# ---------------------------------------------------------------------------


def test_ungrafted_server_resolves_to_its_own_deployment():
    """The un-grafted path, pinned: deployment in, that deployment's package
    out — no ``legacy_module``, no config path, nothing else consulted."""
    assert m.resolve_analyses_package("hte") == HTE_PKG


def test_ungrafted_resolution_is_not_stolen_by_the_config_path():
    """A config living in another deployment must not redirect a server whose
    own deployment resolves fine (the launcher lets a config in deployment X
    host a server with an explicit ``deployment: Y``)."""
    assert (
        m.resolve_analyses_package(
            "hte", config_path="/repo/helao/deploy/test/configs/somecfg.yml"
        )
        == HTE_PKG
    )


def test_graft_resolves_through_its_legacy_module():
    """``fast: graft`` shape: the config names the wrapped legacy module, whose
    package identifies the deployment owning the analyses."""
    assert (
        m.resolve_analyses_package("hexagon", legacy_module=HTE_LEGACY_MODULE)
        == HTE_PKG
    )


def test_graft_without_legacy_module_resolves_through_the_config_path():
    """Hardcoded-shim shape: ``fast: analysis_server`` + ``deployment:
    hexagon`` puts no ``legacy_module:`` key in the config, so the config's own
    location is the only thing left that identifies the deployment."""
    assert (
        m.resolve_analyses_package(
            "hexagon", config_path="/repo/helao/deploy/hte/configs/somecfg.yml"
        )
        == HTE_PKG
    )


def test_candidate_order_prefers_legacy_module_then_deployment_then_config(
    monkeypatch,
):
    """Order pinned independently of which packages happen to exist on disk."""
    monkeypatch.setattr(m, "_package_importable", lambda pkg: True)
    resolved = m.resolve_analyses_package(
        "second",
        legacy_module="helao.deploy.first.servers.action.some_server",
        config_path="/repo/helao/deploy/third/configs/somecfg.yml",
    )
    assert resolved == "helao.deploy.first.drivers.data.analyses"

    # With no legacy_module the world deployment wins over the config path,
    # which is what keeps every un-grafted server resolving as it did before.
    resolved = m.resolve_analyses_package(
        "second", config_path="/repo/helao/deploy/third/configs/somecfg.yml"
    )
    assert resolved == "helao.deploy.second.drivers.data.analyses"


def test_a_later_candidate_is_used_only_when_the_earlier_package_is_absent(
    monkeypatch,
):
    """Existence is the discriminator, so the order only ever takes effect
    where the old resolution would have imported nothing at all."""
    monkeypatch.setattr(
        m, "_package_importable", lambda pkg: "second" not in pkg.split(".")
    )
    resolved = m.resolve_analyses_package(
        "second", config_path="/repo/helao/deploy/third/configs/somecfg.yml"
    )
    assert resolved == "helao.deploy.third.drivers.data.analyses"


def test_unresolvable_deployment_still_names_what_was_configured():
    """When nothing is importable the configured deployment is returned, so the
    error the caller raises reports the package the config actually asked for."""
    assert (
        m.resolve_analyses_package("no_such_deployment")
        == "helao.deploy.no_such_deployment.drivers.data.analyses"
    )


def test_no_deployment_at_all_resolves_to_nothing():
    assert m.resolve_analyses_package(None) is None


# ---------------------------------------------------------------------------
# Class loading: grafted == un-grafted
# ---------------------------------------------------------------------------


def test_ungrafted_load_returns_the_expected_class_set():
    loaded = m.load_analysis_classes(HTE_ANALYSES, "hte")
    assert set(loaded) == HTE_ENDPOINTS


def test_grafted_load_returns_the_same_classes_as_ungrafted():
    """The gate: the same names must map to the same class objects whether the
    server is composed directly or grafted. Under the old resolution the
    grafted call returned ``{}``."""
    ungrafted = m.load_analysis_classes(HTE_ANALYSES, "hte")
    grafted = m.load_analysis_classes(
        HTE_ANALYSES, "hexagon", legacy_module=HTE_LEGACY_MODULE
    )
    assert set(grafted) == HTE_ENDPOINTS
    assert grafted == ungrafted


def test_grafted_load_via_config_path_returns_the_same_classes():
    grafted = m.load_analysis_classes(
        HTE_ANALYSES,
        "hexagon",
        config_path="/repo/helao/deploy/hte/configs/somecfg.yml",
    )
    assert grafted == m.load_analysis_classes(HTE_ANALYSES, "hte")


# ---------------------------------------------------------------------------
# A miss is no longer silent
# ---------------------------------------------------------------------------


def test_missing_analysis_module_raises():
    with pytest.raises(m.AnalysisLoadError) as excinfo:
        m.load_analysis_classes(["no_such_analysis"], "hte")
    message = str(excinfo.value)
    assert "no_such_analysis" in message
    assert HTE_PKG in message


def test_one_bad_entry_among_good_ones_still_raises():
    """A partial miss is the case the old code hid best: two routes appear, the
    third does not, and startup looks healthy."""
    with pytest.raises(m.AnalysisLoadError) as excinfo:
        m.load_analysis_classes(HTE_ANALYSES + ["no_such_analysis"], "hte")
    assert "1 of 3" in str(excinfo.value)


def test_every_failure_is_reported_together():
    """One launch shows every broken entry, not the first one only."""
    with pytest.raises(m.AnalysisLoadError) as excinfo:
        m.load_analysis_classes(["no_such_analysis", "also_missing"], "hte")
    message = str(excinfo.value)
    assert "no_such_analysis" in message
    assert "also_missing" in message


def test_wrong_class_name_raises():
    with pytest.raises(m.AnalysisLoadError) as excinfo:
        m.load_analysis_classes(["echeuvis_stability:NotAClassHere"], "hte")
    assert "NotAClassHere" in str(excinfo.value)


def test_analyses_configured_without_a_deployment_raises():
    with pytest.raises(m.AnalysisLoadError):
        m.load_analysis_classes(HTE_ANALYSES, None)


def test_no_analyses_configured_is_not_a_failure():
    """An analysis server that requests nothing must still start."""
    assert m.load_analysis_classes([], None) == {}
    assert m.load_analysis_classes(None, "hte") == {}


# ---------------------------------------------------------------------------
# What the built app actually exposes
# ---------------------------------------------------------------------------


def _analyze_routes(world_cfg, server_key, monkeypatch) -> set:
    """The ``analyze_*`` route paths ``make_analysis_app`` really registers."""
    from helao.helpers import config_loader

    monkeypatch.setattr(config_loader, "CONFIG", world_cfg)
    app = m.make_analysis_app(server_key)
    paths = {getattr(route, "path", "") for route in app.routes}
    return {path for path in paths if "/analyze_" in path}


def _world(tmp_path, **server_extras) -> dict:
    world = {
        "root": str(tmp_path),
        "servers": {
            "ANA": {
                "host": "127.0.0.1",
                "port": 8014,
                "group": "action",
                "params": {"local_only": True, "analyses": HTE_ANALYSES},
                **server_extras,
            }
        },
    }
    return world


def test_app_registers_the_same_analyze_routes_grafted_and_ungrafted(
    tmp_path, monkeypatch
):
    ungrafted = _world(tmp_path, fast="analysis_server")
    ungrafted["deployment"] = "hte"
    grafted = _world(
        tmp_path, fast="graft", deployment="hexagon", legacy_module=HTE_LEGACY_MODULE
    )
    grafted["deployment"] = "hexagon"

    ungrafted_routes = _analyze_routes(ungrafted, "ANA", monkeypatch)
    grafted_routes = _analyze_routes(grafted, "ANA", monkeypatch)

    assert ungrafted_routes == {f"/ANA/{name}" for name in HTE_ENDPOINTS}
    assert grafted_routes == ungrafted_routes


def test_app_build_fails_when_a_configured_analysis_is_missing(tmp_path, monkeypatch):
    """What a station sees: the server never starts, instead of starting
    without the route."""
    world = _world(tmp_path, fast="analysis_server")
    world["deployment"] = "hte"
    world["servers"]["ANA"]["params"]["analyses"] = HTE_ANALYSES + ["no_such_analysis"]
    with pytest.raises(m.AnalysisLoadError):
        _analyze_routes(world, "ANA", monkeypatch)
