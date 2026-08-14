"""P7e — the generic config-driven Bokeh grafts, and the wiring makeVisApp
now attaches.

Two properties are under test and they pull in opposite directions, which is
why both halves are here:

* the graft must name NOTHING (its legacy target is a config value, so a
  private deployment can flip a Bokeh server without this public repo naming
  it), and must fail loudly when the config does not name one either;
* the graft must still produce the SAME document the legacy path produced —
  a spy-only test would pass against a facade that quietly dropped the doc, so
  one test drives a real legacy visualizer and a real legacy operator all the
  way into a live ``Document`` and asserts roots exist.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import re
from pathlib import Path

import pytest
from bokeh.document import Document

REPO_ROOT = Path(__file__).resolve().parents[3]
GRAFT_CONFIG = (
    REPO_ROOT / "helao" / "deploy" / "test" / "configs" / "goldenhexgraft.yml"
)

VIS_GRAFT = "helao.deploy.hexagon.servers.visualizer.graft"
OP_GRAFT = "helao.deploy.hexagon.servers.operator.graft"
GRAFT_SOURCES = (
    REPO_ROOT / "helao/deploy/hexagon/servers/visualizer/graft.py",
    REPO_ROOT / "helao/deploy/hexagon/servers/operator/graft.py",
    REPO_ROOT / "helao/deploy/hexagon/servers/action/graft.py",
)


def _import(modpath):
    from importlib import import_module

    return import_module(modpath)


def _world(tmp_path, **server_overrides):
    """A minimal two-bokeh-server world with an installed root."""
    world = {
        "root": str(tmp_path),
        "dummy": True,
        "simulation": True,
        "servers": {
            "LIVE": {
                "host": "127.0.0.1",
                "port": 5002,
                "group": "visualizer",
                "bokeh": "graft",
                "deployment": "hexagon",
                "legacy_module": "helao.deploy.hte.servers.visualizer.live_visualizer",
                "params": {},
            },
            "OPERATOR": {
                "host": "127.0.0.1",
                "port": 5001,
                "group": "operator",
                "bokeh": "graft",
                "deployment": "hexagon",
                "legacy_module": (
                    "helao.deploy.hte.servers.operator.standalone_operator"
                ),
                "params": {},
            },
        },
    }
    for key, patch in server_overrides.items():
        world["servers"][key].update(patch)
    return world


@pytest.fixture()
def installed(tmp_path, monkeypatch):
    from helao.helpers import config_loader

    world = _world(tmp_path)
    monkeypatch.setattr(config_loader, "CONFIG", world)
    return world


class _FakeLegacy:
    """Stands in for a legacy bokeh module; records the delegated call."""

    calls: dict = {}

    @staticmethod
    def makeBokehApp(doc, confPrefix, server_key, helao_repo_root):
        _FakeLegacy.calls["args"] = (doc, confPrefix, server_key, helao_repo_root)
        return doc


@pytest.fixture()
def spy_legacy(monkeypatch):
    """Intercept factory's import_module; return the recorded call dict."""
    from helao.hexagon.app import factory

    _FakeLegacy.calls = {}

    def fake_import(name):
        _FakeLegacy.calls["module"] = name
        return _FakeLegacy

    monkeypatch.setattr(factory, "import_module", fake_import)
    return _FakeLegacy.calls


# --------------------------------------------------------------------------
# the graft names nothing, and the config names everything
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "modpath,server_key,expected",
    [
        (VIS_GRAFT, "LIVE", "helao.deploy.hte.servers.visualizer.live_visualizer"),
        (OP_GRAFT, "OPERATOR", "helao.deploy.hte.servers.operator.standalone_operator"),
    ],
)
def test_graft_delegates_to_the_configured_legacy_module(
    installed, spy_legacy, modpath, server_key, expected
):
    """The graft resolves its target from config and hands the legacy module
    the EXACT 4-arg shape bokeh_launcher produces."""
    graft = _import(modpath)
    doc = Document()
    out = graft.makeBokehApp(
        doc, confPrefix="goldenhexgraft", server_key=server_key, helao_repo_root="/repo"
    )
    assert out is doc
    assert spy_legacy["module"] == expected
    assert spy_legacy["args"] == (doc, "goldenhexgraft", server_key, "/repo")


@pytest.mark.parametrize(
    "modpath,server_key,group",
    [(VIS_GRAFT, "LIVE", "visualizer"), (OP_GRAFT, "OPERATOR", "operator")],
)
def test_graft_without_legacy_module_raises_instructively(
    installed, spy_legacy, monkeypatch, modpath, server_key, group
):
    """No `legacy_module:` is a hard, self-explaining failure — the message
    has to say which key to add and where, because the operator reading it is
    flipping a config, not editing this repo."""
    installed["servers"][server_key].pop("legacy_module")
    graft = _import(modpath)
    with pytest.raises(KeyError) as ei:
        graft.makeBokehApp(
            Document(),
            confPrefix="goldenhexgraft",
            server_key=server_key,
            helao_repo_root="/repo",
        )
    msg = str(ei.value)
    assert "legacy_module" in msg
    assert "bokeh: graft" in msg
    assert f"servers.{group}.<module>" in msg
    assert server_key in msg
    # and it failed BEFORE any legacy import was attempted
    assert spy_legacy == {}


@pytest.mark.parametrize("modpath", [VIS_GRAFT, OP_GRAFT])
def test_graft_without_installed_config_raises(monkeypatch, modpath):
    from helao.helpers import config_loader

    monkeypatch.setattr(config_loader, "CONFIG", None)
    graft = _import(modpath)
    with pytest.raises(RuntimeError) as ei:
        graft.makeBokehApp(
            Document(),
            confPrefix="goldenhexgraft",
            server_key="LIVE",
            helao_repo_root="/repo",
        )
    assert "CONFIG is not installed" in str(ei.value)


def test_graft_reads_config_late_not_at_import_time(installed, spy_legacy):
    """The graft must read `config_loader.CONFIG` through the module.

    Bokeh imports a shim once per process but calls makeBokehApp once per
    browser SESSION. A module-level `from config_loader import CONFIG` freezes
    whatever was installed at import time — so a config installed (or, as here,
    edited) after import would be invisible.
    """
    graft = _import(VIS_GRAFT)
    installed["servers"]["LIVE"]["legacy_module"] = "helao.deploy.test.servers.other"
    graft.makeBokehApp(
        Document(),
        confPrefix="goldenhexgraft",
        server_key="LIVE",
        helao_repo_root="/repo",
    )
    assert spy_legacy["module"] == "helao.deploy.test.servers.other"


def test_graft_sources_name_no_legacy_deployment():
    """The privacy invariant the generic graft exists for.

    Every `helao.deploy.<X>.` written in a graft source must be `hexagon` (the
    shim's own package). A concrete legacy deployment appearing here — public
    or private — means the target was hardcoded again and a private deployment
    can no longer flip that server without this public repo naming it.
    """
    for src in GRAFT_SOURCES:
        text = src.read_text()
        named = set(re.findall(r"helao\.deploy\.([A-Za-z_][A-Za-z0-9_]*)\.", text))
        assert named <= {"hexagon"}, (src.name, sorted(named))


# --------------------------------------------------------------------------
# makeVisApp's wiring
# --------------------------------------------------------------------------


def test_graft_attaches_hexagon_wiring_to_the_document(installed, spy_legacy):
    """P7e: the hosted process is composed, not hexagon in name only. The
    wiring rides the per-session Document, and carries the ui_host port that
    makes this a UI-hosting composition (P7d)."""
    from helao.hexagon.app.ui_host import BokehServerUiHost
    from helao.hexagon.app.wiring import VIS_REQUIRED

    graft = _import(VIS_GRAFT)
    doc = Document()
    graft.makeBokehApp(
        doc, confPrefix="goldenhexgraft", server_key="LIVE", helao_repo_root="/repo"
    )
    wiring = doc.hexagon_wiring  # type: ignore[attr-defined]
    assert wiring is not None
    assert isinstance(wiring.ui_host, BokehServerUiHost)
    for name in VIS_REQUIRED:
        assert getattr(wiring, name) is not None, name
    # the legacy module saw the SAME doc the wiring was attached to
    assert spy_legacy["args"][0] is doc


def test_graft_on_an_unknown_server_key_fails_before_rendering(installed, spy_legacy):
    """A server key the config does not carry aborts the session rather than
    rendering a half-composed page."""
    graft = _import(VIS_GRAFT)
    with pytest.raises(KeyError):
        graft.makeBokehApp(
            Document(),
            confPrefix="goldenhexgraft",
            server_key="NOSUCH",
            helao_repo_root="/repo",
        )
    assert spy_legacy == {}


# --------------------------------------------------------------------------
# anti-vacuity: one real legacy module, end to end, into a live Document
# --------------------------------------------------------------------------


@pytest.fixture()
def real_config(tmp_path, monkeypatch):
    """The P7e gate config with its root redirected into tmp_path."""
    from helao.helpers import config_loader, helao_logging
    from helao.helpers.config_loader import read_config

    cfg = copy.deepcopy(read_config(str(GRAFT_CONFIG)))
    cfg["root"] = str(tmp_path)
    monkeypatch.setattr(config_loader, "CONFIG", cfg)
    # the legacy apps install a process-wide file logger; keep it out of the
    # rest of the session
    monkeypatch.setattr(helao_logging, "LOGGER", helao_logging.LOGGER, raising=False)
    return cfg


async def _cancel_new_tasks(before):
    for task in asyncio.all_tasks() - before:
        task.cancel()
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_visualizer_graft_builds_the_real_legacy_document(real_config, tmp_path):
    """The whole path, unspied: config -> graft -> makeVisApp -> the real hte
    live_visualizer -> a Document with roots.

    Also the hot-reload contract. bokeh_launcher writes
    STATES/loaded_modules_<key>.json BEFORE any session connects, and neither
    the graft nor the hardcoded shims import their legacy module until a
    session arrives — so the startup snapshot cannot list the panel modules.
    mount_visualizers refreshes it once the panels are mounted, and THAT
    snapshot is what the watcher must be able to map an edited panel back to.
    """
    graft = _import(VIS_GRAFT)
    before = asyncio.all_tasks()
    doc = Document()
    out = graft.makeBokehApp(
        doc,
        confPrefix="goldenhexgraft",
        server_key="LIVE",
        helao_repo_root=str(REPO_ROOT),
    )
    try:
        assert out is doc
        assert len(doc.roots) >= 3, [type(r).__name__ for r in doc.roots]
        assert doc.hexagon_wiring is not None  # type: ignore[attr-defined]

        snap = tmp_path / "STATES" / "loaded_modules_LIVE.json"
        assert snap.exists(), sorted(p.name for p in (tmp_path / "STATES").iterdir())
        loaded = {os.path.relpath(p, REPO_ROOT) for p in json.loads(snap.read_text())}
        assert "helao/deploy/hexagon/servers/visualizer/graft.py" in loaded
        assert "helao/deploy/hte/servers/visualizer/live_visualizer.py" in loaded
        # the per-instrument panel named by SIM's `live_vis:` key — the file an
        # operator actually edits, and the one the startup snapshot misses
        assert "helao/deploy/test/servers/visualizer/wssim_live_vis.py" in loaded
    finally:
        await _cancel_new_tasks(before)


@pytest.mark.asyncio
async def test_operator_graft_builds_the_real_legacy_document(real_config, tmp_path):
    """Same, for the operator: the real hte standalone_operator mounts its UI
    and binds a backend, through a graft that never names it."""
    graft = _import(OP_GRAFT)
    before = asyncio.all_tasks()
    doc = Document()
    out = graft.makeBokehApp(
        doc,
        confPrefix="goldenhexgraft",
        server_key="OPERATOR",
        helao_repo_root=str(REPO_ROOT),
    )
    try:
        assert out is doc
        assert len(doc.roots) >= 1, [type(r).__name__ for r in doc.roots]
        # BokehOperator mounted by the legacy app
        assert doc.operator is not None  # type: ignore[attr-defined]
        assert doc.hexagon_wiring is not None  # type: ignore[attr-defined]

        # The operator mounts no vis panels, so mount_visualizers never runs
        # and never refreshes the snapshot. Under LEGACY routing the launcher's
        # own import put standalone_operator.py in the startup snapshot; under
        # hexagon routing only the shim is imported there, so without
        # makeVisApp's refresh an edit to the operator maps to no server at all
        # and the watcher silently never restarts it.
        snap = tmp_path / "STATES" / "loaded_modules_OPERATOR.json"
        assert snap.exists()
        loaded = {os.path.relpath(p, REPO_ROOT) for p in json.loads(snap.read_text())}
        assert "helao/deploy/hexagon/servers/operator/graft.py" in loaded
        assert "helao/deploy/hte/servers/operator/standalone_operator.py" in loaded
        assert "helao/ui/bokeh/operator.py" in loaded
    finally:
        await _cancel_new_tasks(before)
