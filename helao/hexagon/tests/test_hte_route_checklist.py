"""Every hte action module still declares its frozen route set (B5).

``helao/hexagon/tests/checklists/hte/*.json`` is a verbatim AST extraction of
the PRE-migration legacy source: 175 action routes and 81 private routes,
each with every parameter's name, annotation and default. B5 rewrites the
decorator form of all 175 action routes, so this is the gate that says the
rewrite changed nothing a client can see.

The extractor reads source, never imports, so a module whose vendor SDK is
Windows-only is checked here exactly like any other -- and so are routes
registered inside ``dyn_endpoints``, which are decorated in source but do not
exist on the app until startup.

**Never regenerate the checklists.** ``harness/hte_freeze.py`` writes that
directory from whatever the source currently says; running it after a port
replaces the record with the port's own output, and this test then passes by
construction, proving nothing. The frozen files are the pre-port record and
B5 is read-only against them.

Verified red before being trusted, on ``cam_server``:

* a parameter default moved (``= 1`` to ``= 2``) -> ``changed``/``params``;
* a ported route whose handler was misnamed -> ``missing`` + ``extra``;
* the same route ported correctly -> pass, so the native decorator form
  round-trips to the identical record.

One measured limit, from that exercise: ``diff_route_sets`` compares path,
method, ``tags`` and ``params``, **not** the ``handler`` field. In a legacy
module the path is spelled in the decorator, so renaming the function alone
is invisible here. In a ported module the path is *derived* from the handler
name, so the same rename is caught -- which is the direction B5 moves in.
"""

import json
from pathlib import Path
from typing import Optional

import pytest

from harness.endpoints import diff_route_sets, extract_routes
from harness.hte_freeze import HTE_ACTION, OUT, SERVERS


def test_the_checklist_directory_is_actually_populated() -> None:
    """A wrong OUT path would make every parametrised case pass over nothing."""
    frozen = sorted(OUT.glob("*.json"))
    assert len(frozen) >= len(SERVERS), f"only {len(frozen)} checklists in {OUT}"


@pytest.mark.parametrize("module,server_key", SERVERS, ids=[m for m, _ in SERVERS])
def test_module_matches_its_frozen_checklist(
    module: str, server_key: Optional[str]
) -> None:
    checklist = OUT / (Path(module).stem + ".json")
    frozen = json.loads(checklist.read_text())
    current = extract_routes(HTE_ACTION / module, server_key=server_key)
    diffs = diff_route_sets(frozen, current)
    assert (
        diffs == []
    ), f"{module}: {len(diffs)} route diff(s) against {checklist.name}\n" + json.dumps(
        diffs, indent=2
    )


def test_the_gate_covers_the_whole_measured_surface() -> None:
    """Pin the totals, so a module silently dropped from SERVERS is caught.

    168 and 79 are counted from the frozen JSONs. B5's spec first quoted 175
    and 81, from a grep for ``tags=["action"]`` over the source -- which counts
    seven commented-out decorators (``# @app.post(...)`` in diapump, nidaqmx,
    pal and mfc) and two mentions in ``sample_server``'s module docstring. The
    AST extractor ignores both, correctly. The grep number was wrong and this
    test failed on its first run against the untouched tree, which is what a
    gate seeded before the work is for.
    """
    action = private = 0
    for module, _ in SERVERS:
        for route in json.loads((OUT / (Path(module).stem + ".json")).read_text()):
            if "action" in route["tags"]:
                action += 1
            elif "private" in route["tags"]:
                private += 1
    assert (action, private) == (
        168,
        79,
    ), f"measured {action} action / {private} private"
