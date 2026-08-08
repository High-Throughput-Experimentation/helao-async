# helao/core/tests/test_reflex_entry_resolver.py
"""P7f — the ``_app`` entry module resolves which app the Reflex CLI serves.

``reflex:`` is a bundle name, not a module, so a config cannot route a Reflex
server the way ``fast: graft``/``bokeh: graft`` route the other two. The seam
is ``HELAO_REFLEX_APP_MODULE``, read by ``_app/helao_ui/helao_ui.py`` and set
by ``reflex_launcher.build_env`` only for a ``deployment: hexagon`` server.

These tests load that entry module **for real** (by file path, the way the
Reflex CLI does), because the failure mode being guarded is a launcher that
exports a perfectly correct variable into a child process that never reads it:
asserting on ``build_env``'s output alone proves nothing about what serves.
The module named by the variable is stubbed into ``sys.modules`` so no Reflex
app is built here.
"""

import importlib
import importlib.util
import os
import sys
import types

import pytest

import reflex_bundle

_ENTRY = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "servers",
    "reflex",
    "_app",
    "helao_ui",
    "helao_ui.py",
)


def _load_entry(monkeypatch, recorder=None):
    """Import the real entry module under a fresh name.

    A fresh name each time, because the module executes its resolution at
    import and a cached one would answer with whatever the first test's
    environment said.
    """
    if recorder is not None:
        real = importlib.import_module

        def _spy(name, *args, **kwargs):
            recorder.append(name)
            return real(name, *args, **kwargs)

        monkeypatch.setattr(importlib, "import_module", _spy)
    name = f"_helao_ui_entry_probe_{len(sys.modules)}"
    spec = importlib.util.spec_from_file_location(name, _ENTRY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def stub_targets(monkeypatch):
    """Stand both routing targets up as stub modules carrying sentinels."""
    legacy = types.ModuleType(reflex_bundle.LEGACY_APP_MODULE)
    setattr(legacy, "app", object())
    hexagon = types.ModuleType(reflex_bundle.HEXAGON_APP_MODULE)
    setattr(hexagon, "app", object())
    monkeypatch.setitem(sys.modules, reflex_bundle.LEGACY_APP_MODULE, legacy)
    monkeypatch.setitem(sys.modules, reflex_bundle.HEXAGON_APP_MODULE, hexagon)
    monkeypatch.delenv(reflex_bundle.APP_MODULE_ENV, raising=False)
    return legacy, hexagon


def test_absent_variable_resolves_to_the_legacy_app(monkeypatch, stub_targets):
    """The rollback story: no variable, no change. Deleting the config key
    leaves this exact import, so a station that flips back runs the code it
    ran before the seam existed."""
    legacy, hexagon = stub_targets
    entry = _load_entry(monkeypatch)
    assert entry.app is legacy.app
    assert entry.app is not hexagon.app


def test_absent_variable_imports_nothing_but_the_legacy_module(
    monkeypatch, stub_targets
):
    """Byte-identical import path, asserted rather than asserted-about.

    The entry module must not reach a helper to decide what to import: a
    helper would join every legacy launcher's loaded-module map and move the
    bundle stamp of stations that do not use it. The only module name this
    resolves is the legacy app's.
    """
    seen: list = []
    _load_entry(monkeypatch, recorder=seen)
    assert seen == [reflex_bundle.LEGACY_APP_MODULE]


def test_the_variable_routes_to_the_hexagon_host(monkeypatch, stub_targets):
    legacy, hexagon = stub_targets
    monkeypatch.setenv(reflex_bundle.APP_MODULE_ENV, reflex_bundle.HEXAGON_APP_MODULE)
    seen: list = []
    entry = _load_entry(monkeypatch, recorder=seen)
    assert entry.app is hexagon.app
    assert entry.app is not legacy.app
    assert seen == [reflex_bundle.HEXAGON_APP_MODULE]


def test_an_empty_variable_is_treated_as_absent(monkeypatch, stub_targets):
    """``env["X"] = ""`` is a real shell accident, and ``import_module("")``
    raises ValueError deep inside the CLI with nothing naming the cause."""
    legacy, _ = stub_targets
    monkeypatch.setenv(reflex_bundle.APP_MODULE_ENV, "")
    entry = _load_entry(monkeypatch)
    assert entry.app is legacy.app


def test_the_entry_module_and_reflex_bundle_agree_on_the_spelling():
    """The two copies of these strings are deliberate -- see the entry
    module's docstring -- so they are pinned to each other instead.

    A drift here is silent in the worst way: the launcher sets a variable the
    entry module does not read, and the backend serves the legacy app while
    every log line says hexagon.
    """
    source = open(_ENTRY, encoding="utf8").read()
    assert f'"{reflex_bundle.APP_MODULE_ENV}"' in source
    assert f'"{reflex_bundle.LEGACY_APP_MODULE}"' in source
    # and it decides by reading the environment, not by importing a decider
    assert "import reflex_bundle" not in source
