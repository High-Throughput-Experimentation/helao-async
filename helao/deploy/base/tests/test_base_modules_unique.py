"""Every module in helao/deploy/base resolves to base, and to no other deployment.

The launcher, preflight, the freezer and panel discovery all resolve a bare
module name across deployments (``helao.helpers.server_modules.locate``). A
name that also exists in another deployment makes the launcher warn and take
the first in sorted order, and makes panel lookup raise. So a framework
service must exist in exactly one place. The check is scoped to base: a few
deliberate cross-deployment duplicates exist elsewhere (a private deployment's
``ws_simulator``, pinned by test_preflight), and they are not base's business.
"""

from pathlib import Path

import pytest
import yaml

from helao.helpers import server_modules as sm

BASE = Path(__file__).resolve().parents[1]
MOVED = {
    "async_orch2",
    "standalone_operator",
    "action_visualizer",
    "live_visualizer",
    "control_visualizer",
    "data_browser",
    "sync_server",
}


def _base_modules() -> list[tuple[str, str]]:
    out = []
    for p in sorted((BASE / "servers").rglob("*.py")):
        if p.name == "__init__.py" or "__pycache__" in p.parts:
            continue
        for stack in sm.STACKS:
            found = sm.module_file("base", p.stem, stack)
            if found is not None and found.resolve() == p.resolve():
                out.append((p.stem, stack))
    return out


MODULES = _base_modules()


def test_base_holds_the_moved_services():
    assert MOVED <= {m for m, s in MODULES if s == "app"}


@pytest.mark.parametrize("module,stack", MODULES, ids=[f"{s}:{m}" for m, s in MODULES])
def test_module_exists_in_base_only(module, stack):
    assert sm.locate(module, stack)[1] == ["base"]


def test_no_config_pins_hte_for_a_base_module():
    """OQ-1 (a): an explicit ``deployment: hte`` on a base module is honoured
    unchecked by the launcher and imports a module that no longer exists.

    Scope: every deployment folder present under helao/deploy, nested
    repositories included."""
    bad = []
    scanned = {}
    deps = sorted(p.name for p in sm.DEPLOY_ROOT.iterdir() if p.is_dir())
    for dep in deps:
        cfgs = sorted((sm.DEPLOY_ROOT / dep).glob("**/configs/*.yml"))
        scanned[dep] = len(cfgs)
        for cfg in cfgs:
            data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
            servers = data.get("servers") if isinstance(data, dict) else None
            for key, s in (servers or {}).items():
                if not isinstance(s, dict):
                    continue
                module = s.get("fast") or s.get("bokeh")
                if module in MOVED and s.get("deployment") == "hte":
                    bad.append(f"{cfg.relative_to(sm.DEPLOY_ROOT)}:{key}")
    assert {"base", "hte", "test"} <= scanned.keys(), scanned
    assert scanned["hte"] and scanned["test"], scanned
    assert not bad, bad
