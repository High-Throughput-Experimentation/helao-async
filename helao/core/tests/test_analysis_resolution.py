"""Which package an analysis server loads its ``analyze_*`` classes from, and
what happens when one of them cannot be loaded.

``fast_launcher`` sets ``CONFIG["deployment"]`` from the server's OWN
``deployment:`` value; when that names a deployment with no analyses package,
the loaded config's own location identifies the deployment instead. A miss on
every import used to be logged and skipped, so a server started clean with all
of its ``analyze_*`` routes missing.

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


# ---------------------------------------------------------------------------
# Package resolution
# ---------------------------------------------------------------------------


def test_server_resolves_to_its_own_deployment():
    """Deployment in, that deployment's package out — no config path, nothing
    else consulted."""
    assert m.resolve_analyses_package("hte") == HTE_PKG


def test_resolution_is_not_stolen_by_the_config_path():
    """A config living in another deployment must not redirect a server whose
    own deployment resolves fine (the launcher lets a config in deployment X
    host a server with an explicit ``deployment: Y``)."""
    assert (
        m.resolve_analyses_package(
            "hte", config_path="/repo/helao/deploy/test/configs/somecfg.yml"
        )
        == HTE_PKG
    )


def test_deployment_without_analyses_resolves_through_the_config_path():
    """A deployment with no analyses package falls through to the deployment
    owning the loaded config file."""
    assert (
        m.resolve_analyses_package(
            "no_such_deployment",
            config_path="/repo/helao/deploy/hte/configs/somecfg.yml",
        )
        == HTE_PKG
    )


def test_candidate_order_prefers_deployment_then_config(monkeypatch):
    """Order pinned independently of which packages happen to exist on disk."""
    monkeypatch.setattr(m, "_package_importable", lambda pkg: True)
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
# Class loading
# ---------------------------------------------------------------------------


def test_load_returns_the_expected_class_set():
    loaded = m.load_analysis_classes(HTE_ANALYSES, "hte")
    assert set(loaded) == HTE_ENDPOINTS


def test_load_via_config_path_returns_the_same_classes():
    via_config = m.load_analysis_classes(
        HTE_ANALYSES,
        "no_such_deployment",
        config_path="/repo/helao/deploy/hte/configs/somecfg.yml",
    )
    assert via_config == m.load_analysis_classes(HTE_ANALYSES, "hte")


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


def test_app_registers_the_analyze_routes(tmp_path, monkeypatch):
    world = _world(tmp_path, fast="analysis_server")
    world["deployment"] = "hte"
    routes = _analyze_routes(world, "ANA", monkeypatch)
    assert routes == {f"/ANA/{name}" for name in HTE_ENDPOINTS}


def test_app_build_fails_when_a_configured_analysis_is_missing(tmp_path, monkeypatch):
    """What a station sees: the server never starts, instead of starting
    without the route."""
    world = _world(tmp_path, fast="analysis_server")
    world["deployment"] = "hte"
    world["servers"]["ANA"]["params"]["analyses"] = HTE_ANALYSES + ["no_such_analysis"]
    with pytest.raises(m.AnalysisLoadError):
        _analyze_routes(world, "ANA", monkeypatch)
