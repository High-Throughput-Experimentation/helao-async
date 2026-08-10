"""Derived `_hex` configs: fully composed, and identical to their base otherwise.

These variants exist so a station can be launched entirely on the hexagon app
layer without a second copy of its hardware params. Two properties carry that,
and neither is self-evident from reading a two-line config:

1. **Fully composed.** Every server carries `deployment: hexagon`. A variant
   that quietly left one server legacy would be a mixed composition wearing a
   name that says otherwise -- and the mixed case already has a
   representation, which is flipping the base per server.
2. **Composition-only.** Ports, `root:`, `params:` and every other key equal
   the base's. This is what makes the derivation safe where a copy would not
   be: the P4f/P5g objection to parallel configs is drift, and drift is
   impossible if the variant provably re-reads its base.

Discovery is by glob, so this file names no deployment. On a checkout without
the private nested repos it covers the public variants; with them, all of them.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from helao.helpers.config_loader import read_config
from helao.hexagon import preflight
from helao.hexagon.hexconfig import (
    HEXAGON,
    UnflippableServerError,
    hexagon_variant,
    plan_flip,
)

REPO_ROOT = preflight.REPO_ROOT
CODE_KEYS = ("fast", "bokeh", "reflex")

#: Keys the flip is ALLOWED to add or change on a server. Anything else
#: differing between a base and its variant is drift, which is the whole thing
#: these configs are designed not to have.
_COMPOSITION_KEYS = {"deployment", "legacy_module", *CODE_KEYS}

#: Top-level keys the variant adds for provenance.
_VARIANT_KEYS = {"hexagon_variant_of", "loaded_config_path"}


def _variants() -> list[Path]:
    found = [
        p
        for p in sorted((REPO_ROOT / "helao" / "deploy").glob("*/configs/*.py"))
        if "hexagon_variant(" in p.read_text(encoding="utf-8", errors="ignore")
    ]
    return found


def _base_of(variant: Path) -> Path:
    """The base a variant derives from, read out of its own source."""
    text = variant.read_text(encoding="utf-8")
    marker = 'hexagon_variant(os.path.join(os.path.dirname(__file__), "'
    start = text.index(marker) + len(marker)
    return variant.parent / text[start : text.index('"', start)]


def test_some_variants_exist():
    """Guard on every test below: an empty glob parametrizes to nothing, which
    pytest reports as passing."""
    assert _variants(), "no derived hexagon configs discovered -- inert glob?"


@pytest.mark.parametrize("variant", _variants(), ids=lambda p: p.stem)
def test_every_server_is_hexagon_composed(variant):
    config = read_config(str(variant))
    servers = config["servers"]
    legacy = [
        k
        for k, s in servers.items()
        if isinstance(s, dict)
        and any(c in s for c in CODE_KEYS)
        and s.get("deployment") != HEXAGON
    ]
    assert not legacy, f"{variant.stem} left these servers legacy: {sorted(legacy)}"
    assert servers, f"{variant.stem} composed an empty server set"


@pytest.mark.parametrize("variant", _variants(), ids=lambda p: p.stem)
def test_nothing_but_the_composition_differs_from_the_base(variant):
    base = read_config(str(_base_of(variant)))
    var = read_config(str(variant))

    for key in set(base) | set(var):
        if key in _VARIANT_KEYS or key == "servers":
            continue
        assert base.get(key) == var.get(key), f"{variant.stem}: top-level {key!r} moved"

    assert set(base["servers"]) == set(
        var["servers"]
    ), f"{variant.stem}: server set moved"
    for name, bsrv in base["servers"].items():
        vsrv = var["servers"][name]
        if not isinstance(bsrv, dict):
            continue
        for key in set(bsrv) | set(vsrv):
            if key in _COMPOSITION_KEYS:
                continue
            assert bsrv.get(key) == vsrv.get(key), (
                f"{variant.stem}/{name}: {key!r} differs from the base "
                f"({bsrv.get(key)!r} -> {vsrv.get(key)!r}) -- the variant may "
                f"only change composition"
            )


@pytest.mark.parametrize("variant", _variants(), ids=lambda p: p.stem)
def test_the_base_is_left_legacy(variant):
    """The pair is the point: flipping the variant must not flip the base.

    Without this, a variant that mutated the loaded base in place would satisfy
    every other test here while silently changing what the legacy config does.
    """
    base_path = _base_of(variant)
    read_config(str(variant))  # load the variant FIRST, then re-read the base
    base = read_config(str(base_path))
    composed = [
        k
        for k, s in base["servers"].items()
        if isinstance(s, dict) and s.get("deployment") == HEXAGON
    ]
    # A base may legitimately carry its own per-server flips (an earlier phase
    # may have flipped some); what it must never be is FULLY composed by having
    # had the variant loaded.
    flippable = [
        k
        for k, s in base["servers"].items()
        if isinstance(s, dict) and any(c in s for c in CODE_KEYS)
    ]
    assert len(composed) < len(flippable), (
        f"{base_path.name} is fully hexagon-composed after loading its variant "
        f"-- the variant mutated its base instead of deriving from it"
    )


@pytest.mark.parametrize("variant", _variants(), ids=lambda p: p.stem)
def test_every_grafted_server_names_a_real_module(variant):
    """A `graft` entry that names a module which does not exist fails at launch,
    not at preflight -- the graft resolves its target lazily."""
    config = read_config(str(variant))
    for name, srv in config["servers"].items():
        if not isinstance(srv, dict):
            continue
        if not any(srv.get(c) == "graft" for c in CODE_KEYS):
            continue
        legacy = srv.get("legacy_module")
        assert legacy, f"{variant.stem}/{name}: graft with no legacy_module"
        rel = Path(legacy.replace(".", "/") + ".py")
        assert (
            REPO_ROOT / rel
        ).is_file(), f"{variant.stem}/{name}: legacy_module {legacy} does not exist"


def test_a_server_naming_nothing_resolvable_is_refused():
    """The strictness is the feature: an unflippable server raises rather than
    being left legacy, so 'fully hexagon' is a fact about the file."""
    config = {
        "servers": {
            "NOPE": {
                "host": "127.0.0.1",
                "port": 8001,
                "group": "action",
                "fast": "no_such_module_anywhere",
            }
        }
    }
    with pytest.raises(UnflippableServerError, match="no_such_module_anywhere"):
        plan_flip(copy.deepcopy(config), "helao/deploy/hte/configs/x.yml")


def test_a_named_shim_is_preferred_over_the_graft():
    """One key beats three when the shim's hardcoded target is the real one --
    and the shim shares the legacy basename, so the code key must NOT move."""
    config = {
        "servers": {
            "MOTOR": {
                "host": "127.0.0.1",
                "port": 8001,
                "group": "action",
                "fast": "galil_motion",
            }
        }
    }
    plan = plan_flip(copy.deepcopy(config), "helao/deploy/hte/configs/x.yml")
    code_key, value, legacy = plan["MOTOR"]
    assert (code_key, value, legacy) == ("fast", "galil_motion", None)


def test_a_module_without_a_shim_falls_back_to_the_graft():
    config = {
        "servers": {
            "BROWSE": {
                "host": "127.0.0.1",
                "port": 5003,
                "group": "visualizer",
                "bokeh": "data_browser",
            }
        }
    }
    plan = plan_flip(copy.deepcopy(config), "helao/deploy/hte/configs/x.yml")
    code_key, value, legacy = plan["BROWSE"]
    assert (code_key, value) == ("bokeh", "graft")
    assert legacy == "helao.deploy.hte.servers.visualizer.data_browser"


def test_hexagon_variant_records_what_it_derived_from():
    """Provenance: a run captured from a variant must be traceable to the base
    whose params it actually used."""
    base = REPO_ROOT / "helao" / "deploy" / "test" / "configs" / "test.yml"
    config = hexagon_variant(str(base))
    assert config["hexagon_variant_of"] == str(base.resolve())
