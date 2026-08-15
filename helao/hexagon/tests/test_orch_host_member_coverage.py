"""``OrchHost`` must cover the member contract its collaborators require (B3a).

Legacy ``Orch`` is a delegation shell: 73 of its 79 methods are two
statements or fewer, and the work lives in seven collaborators that hold
only ``self.orch`` and resolve state through it at call time. That makes
the back-reference swappable -- and it makes the contract measurable,
because every member those collaborators reach for is an attribute access
on a name this module can find statically.

B1 had the same contract and did not measure it. It found 43 missing
members one runtime crash at a time, and the most expensive of them
(``_write_meta_atomic``) was underscore-prefixed, so a public-members-only
scan skipped it while its AttributeError fired inside a caught block -- the
action returned 200 and wrote nothing. This extraction counts attribute
access rather than filtering by name, so contractual privates are in the
contract by construction. There are six.

Measured here: **136 members**, of which 24 come free from ``ActionHost``
and 112 are B3a's and B3b's to supply. The spec says 135 -- that figure
came from a one-off scan that counted ``self.orch.<name>`` in ``orch_api``
but not the bare ``orch.<name>`` alias, and missed one. This extraction is
the authority; the spec's number is the stale one.

Ratchet semantics, unchanged from B1's version because they worked: fail
when the gap GROWS, not while it merely persists. A permanently red test
teaches people to ignore it.
"""

import ast
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]

#: Where a consumer module may live. B3a MOVES four of them from the first
#: directory to the second, and the contract must not notice.
#:
#: It did notice, once. With only ``helao/core/servers`` listed, moving
#: orch_queues/orch_persist/orch_estop/orch_lifecycle dropped the measured
#: contract from 136 members to 115 -- the ratchet quietly got weaker at
#: exactly the moment work progressed, and 21 members it was tracking
#: turned into "already done" without anyone implementing them.
SEARCH_DIRS: Final[tuple[Path, ...]] = (
    REPO_ROOT / "helao/core/servers",
    REPO_ROOT / "helao/hexagon/app",
)

#: Modules whose sole back-reference is the orchestrator.
CONSUMERS: Final[tuple[str, ...]] = (
    "orch_dispatch",
    "orch_queues",
    "orch_lifecycle",
    "orch_estop",
    "orch_persist",
    "orch_status_sync",
    "orch_monitor",
    "orch_global_params",
    "orch_unpack",
    "orch_api",
)


def orch_contract() -> set[str]:
    """Every ``Orch`` member a collaborator or the API layer reaches for.

    Two shapes, because the collaborators alias the back-reference before
    use (``orch = self.orch`` appears 21 times in orch_dispatch alone):
    ``orch.<name>`` and ``self.orch.<name>``.
    """
    found: set[str] = set()
    for mod in CONSUMERS:
        path = next(
            (d / f"{mod}.py" for d in SEARCH_DIRS if (d / f"{mod}.py").exists()), None
        )
        assert path is not None, (
            f"consumer module {mod!r} found in neither {SEARCH_DIRS[0]} nor "
            f"{SEARCH_DIRS[1]}. Skipping it silently would shrink the contract "
            "and weaken this ratchet, which is the one failure it cannot afford."
        )
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            value = node.value
            if isinstance(value, ast.Name) and value.id == "orch":
                found.add(node.attr)
            elif isinstance(value, ast.Attribute) and value.attr == "orch":
                found.add(node.attr)
    return found


#: Members B3a answers a different way, each with a reason.
DELIBERATELY_ABSENT: Final[frozenset[str]] = frozenset(
    {
        # Registered as routes on the host, not exposed as bound methods --
        # the same decision ActionHost made. NOTE for B3b: these must
        # reproduce the ORCHAPI encoding family's bytes, not ActionHost's.
        # The two families are independently frozen (Amendment 2 section 3):
        # on /ws_status the base_api family delivers an ActionModel and the
        # orch_api family a plain dict, and a consumer that assumes either
        # blanks silently against the other.
        "ws_status",
        "ws_data",
        "ws_live",
        # Replaced by the explicit ActionContext (B1, D-B1.1).
        "setup_and_contain_action",
        # Legacy logging helper; the host uses LOGGER directly.
        "print_message",
        # Legacy lifecycle internal: OrchHost uses FastAPI's startup event.
        "myinit",
        # Assigned by the DISPATCH RUNNER at runtime (orch_dispatch.py:1170),
        # not by construction, on legacy Orch exactly as on OrchHost. A
        # static scan cannot see them on either, so tracking them as
        # outstanding work would keep this list permanently non-empty for
        # something that is already correct.
        "exp_model",
        "seq_model",
    }
)

#: The remaining work. Porting a member means DELETING it from here; that
#: edit is the point. B3b's members stay listed until B3b lands.
NOT_YET_PORTED: Final[frozenset[str]] = frozenset(set())


def _host_members() -> set[str]:
    """Class members plus instance attributes, INCLUDING inherited ones.

    Walking only orch_host.py reports phantom gaps for everything OrchHost
    inherits from ActionHost -- 24 of the 136, and B1's first ratchet run
    made exactly this mistake with three HelaoFastAPI attributes.
    """
    from helao.hexagon.app.orch_host import OrchHost

    members = {m for m in dir(OrchHost) if not m.startswith("__")}
    for rel in (
        "helao/hexagon/app/orch_host.py",
        "helao/hexagon/app/action_host.py",
        "helao/helpers/server_api.py",
    ):
        members |= _self_assigned(REPO_ROOT / rel)
    return members


def _self_assigned(path: Path) -> set[str]:
    """Every ``self.x`` assigned in *path*, by AST rather than by regex.

    A regex was tried twice and was wrong twice, in the same direction
    both times -- reporting a member as ABSENT while the source plainly
    assigns it, which in a coverage ratchet means work that looks
    outstanding after it is done:

    * anchored straight to ``=``, it missed every ANNOTATED assignment
      (``self.live_buffer: dict = {}``);
    * widened for annotations, it still missed every TUPLE-unpacked one
      (``(self.experiment_lib, self.experiment_codehash_lib, ...) = ...``),
      catching only the final target before the ``=``.

    ``ast.Store`` covers all of it -- plain, annotated, tuple, augmented,
    walrus -- and cannot drift as syntax varies.
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
            and isinstance(node.ctx, ast.Store)
        ):
            found.add(node.attr)
    return found


def test_the_contract_extraction_is_not_vacuous() -> None:
    """A broken AST walk would make every coverage assertion pass for free."""
    contract = orch_contract()
    assert len(contract) > 130, f"only {len(contract)} members found; walk is inert"
    for known in ("action_dq", "globalstatusmodel", "_ensure_run_id", "add_sequence"):
        assert known in contract, f"{known} missing from the extraction"


def test_every_tracked_name_is_actually_in_the_contract() -> None:
    """Both lists must be SUBSETS of the measured contract.

    Without this, a name that leaves the contract -- because its consumer
    module moved, was renamed, or stopped using it -- reads as "already
    done" in the staleness check below, and its entry gets deleted having
    never been implemented. That is not hypothetical: moving four
    collaborators out of helao/core/servers did exactly this to 21 names
    before SEARCH_DIRS existed.
    """
    contract = orch_contract()
    assert sorted(NOT_YET_PORTED - contract) == [], (
        "on NOT_YET_PORTED but not in the measured contract -- the extraction "
        "lost sight of a consumer module, or the name is misspelled"
    )
    assert sorted(DELIBERATELY_ABSENT - contract) == [], (
        "excluded but not in the contract -- nothing requires this member, so "
        "the exclusion is noise"
    )


def test_no_new_gap_has_opened_in_the_host() -> None:
    missing = orch_contract() - _host_members()
    unaccounted = sorted(missing - DELIBERATELY_ABSENT - NOT_YET_PORTED)
    assert unaccounted == [], (
        "contract members OrchHost lacks that are neither deliberately excluded "
        f"nor on the known-missing list: {unaccounted}\n"
        "Either implement them, or add them to NOT_YET_PORTED with a reason."
    )


def test_the_known_missing_list_has_not_silently_grown() -> None:
    missing = orch_contract() - _host_members()
    already_done = sorted(NOT_YET_PORTED - missing)
    assert already_done == [], (
        f"on NOT_YET_PORTED but OrchHost already has them: {already_done}\n"
        "Delete them from the list."
    )


def test_deliberate_exclusions_are_actually_absent() -> None:
    missing = orch_contract() - _host_members()
    stale = sorted(DELIBERATELY_ABSENT - missing)
    assert stale == [], f"listed as deliberately absent but present: {stale}"
