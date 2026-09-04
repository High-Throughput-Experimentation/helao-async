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

from harness.endpoints import diff_route_sets, extract_routes, filter_allowed_additions
from harness.hte_freeze import HTE_ACTION, OUT, SERVERS

ADDITIONS_PATH = OUT / "_additions.json"

#: Action/private route totals measured from the frozen JSONs at B5. The
#: spec first quoted 175/81 from a grep over source, which counted seven
#: commented-out decorators and two docstring mentions; the AST extractor
#: ignores both. These are the measured numbers, and deliberate additions
#: are added to them rather than folded into them.
FROZEN_ACTION_TOTAL = 168
FROZEN_PRIVATE_TOTAL = 79


def _load_additions() -> list[dict]:
    return json.loads(ADDITIONS_PATH.read_text())


def _additions_for(module: str) -> list[dict]:
    return [a for a in _load_additions() if a["module"] == module]


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
    diffs, _allowed = filter_allowed_additions(
        diff_route_sets(frozen, current), _additions_for(module)
    )
    assert (
        diffs == []
    ), f"{module}: {len(diffs)} route diff(s) against {checklist.name}\n" + json.dumps(
        diffs, indent=2
    )


def test_every_addition_entry_is_well_formed() -> None:
    """An entry without `why` is a bypass nobody can review in a diff."""
    for entry in _load_additions():
        missing = {"module", "path", "method", "date", "why"} - set(entry)
        assert not missing, f"{entry} is missing {sorted(missing)}"
        assert entry["why"].strip(), f"{entry['path']} has an empty `why`"
        assert entry["module"] in {
            m for m, _ in SERVERS
        }, f"{entry['module']} is not an hte action module"


def test_the_gate_covers_the_whole_measured_surface() -> None:
    """Pin the totals, so a module silently dropped from SERVERS is caught.

    168 and 79 are counted from the frozen JSONs. B5's spec first quoted 175
    and 81, from a grep for ``tags=["action"]`` over the source -- which counts
    seven commented-out decorators (``# @app.post(...)`` in diapump, nidaqmx,
    pal and mfc) and two mentions in ``sample_server``'s module docstring. The
    AST extractor ignores both, correctly. The grep number was wrong and this
    test failed on its first run against the untouched tree, which is what a
    gate seeded before the work is for.

    The frozen counts are asserted separately from the deliberate additions.
    Editing a combined literal to make a diff pass is a re-freeze with extra
    steps: it leaves no record of what moved, and it cannot distinguish an
    intended addition from an accidental deletion that happens to net out.
    """
    action = private = 0
    for module, _ in SERVERS:
        for route in json.loads((OUT / (Path(module).stem + ".json")).read_text()):
            if "action" in route["tags"]:
                action += 1
            elif "private" in route["tags"]:
                private += 1
    assert (action, private) == (
        FROZEN_ACTION_TOTAL,
        FROZEN_PRIVATE_TOTAL,
    ), f"frozen record measures {action} action / {private} private"

    by_module = dict(SERVERS)
    resolved = 0
    for entry in _load_additions():
        current = extract_routes(
            HTE_ACTION / entry["module"], server_key=by_module[entry["module"]]
        )
        for route in current:
            if (route["path"], route["method"]) == (entry["path"], entry["method"]):
                resolved += 1
    assert resolved == len(
        _load_additions()
    ), f"{len(_load_additions()) - resolved} listed addition(s) resolve to no route"
