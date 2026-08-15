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
import re
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CORE_SERVERS: Final[Path] = REPO_ROOT / "helao/core/servers"

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
        path = CORE_SERVERS / f"{mod}.py"
        if not path.exists():
            continue
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
    }
)

#: The remaining work. Porting a member means DELETING it from here; that
#: edit is the point. B3b's members stay listed until B3b lands.
NOT_YET_PORTED: Final[frozenset[str]] = frozenset(
    {
        # --- B3b: the dispatch loop -------------------------------------
        "loop_task_dispatch_action",
        "loop_task_dispatch_experiment",
        "loop_task_dispatch_sequence",
        "orch_wait_for_all_actions",
        "wait_for_interrupt",
        "interrupt_q",
        "start",
        "stop",
        "skip",
        "stop_loop",
        "estop_loop",
        "estop_actions",
        "estop_finish_active",
        "intend_stop",
        "intend_none",
        "clear_error",
        "clear_estop",
        "clear_actions",
        "current_stop_message",
        "init_success",
        # --- B3b: status ingestion + monitors ---------------------------
        "update_status",
        "update_nonblocking",
        "clear_nonblocking",
        "nonblocking",
        "globstat_q",
        "status_summary",
        "last_dispatched_action_uuid",
        "step_thru_actions",
        "step_thru_experiments",
        "step_thru_sequences",
        "heartbeat_interval",
        "ignore_heartbeats",
        "register_obj_uuid",
        "register_action_uuid",
        "track_action_uuid",
        # --- B3a, filled in by Tasks 2-6 (delete as you go) -------------
        "sequence_dq",
        "experiment_dq",
        "action_dq",
        "action_history",
        "experiment_history",
        "sequence_history",
        "active_experiment",
        "active_sequence",
        "last_experiment",
        "last_sequence",
        "active_run_id",
        "active_seq_exp_counter",
        "last_action_uuid",
        "globalstatusmodel",
        "global_params",
        "aiolock",
        "wait_task",
        "current_wait_ts",
        "last_wait_ts",
        "dispatch_wait_task",
        "verify_plates",
        "verify_plate_in_params",
        "use_sync",
        "syncer",
        "executors",
        "exp_model",
        "seq_model",
        "exp_postprocessors",
        "exp_postprocess_libs",
        "seq_postprocessors",
        "seq_postprocess_libs",
        "experiment_lib",
        "sequence_lib",
        "experiment_codehash_lib",
        "sequence_codehash_lib",
        "experiment_codepath_lib",
        "sequence_codepath_lib",
        "unpack_sequence",
        "seq_unpacker",
        "add_sequence",
        "add_split_sequences",
        "add_experiment",
        "prepend_sequences",
        "move_sequence",
        "move_experiment",
        "move_action",
        "remove_sequence",
        "remove_experiment",
        "remove_action",
        "clear_sequences",
        "clear_experiments",
        "drop_experiment_inds",
        "list_sequences",
        "list_experiments",
        "list_all_experiments",
        "list_actions",
        "list_active_actions",
        "get_experiment",
        "get_sequence",
        "finish_active_experiment",
        "finish_active_sequence",
        "write_active_experiment_exp",
        "write_active_sequence_seq",
        "export_queues",
        "import_queues",
        "_ensure_run_id",
        "_resolve_active_run_id",
        "_prep_sequence_meta",
        "_rebuild_action_dq",
        "_rebuild_experiment_dq",
        "_rebuild_sequence_dq",
    }
)


def _host_members() -> set[str]:
    """Class members plus instance attributes, INCLUDING inherited ones.

    Walking only orch_host.py reports phantom gaps for everything OrchHost
    inherits from ActionHost -- 23 of the 135, and B1's first ratchet run
    made exactly this mistake with three HelaoFastAPI attributes.
    """
    from helao.hexagon.app.orch_host import OrchHost

    members = {m for m in dir(OrchHost) if not m.startswith("__")}
    for rel in (
        "helao/hexagon/app/orch_host.py",
        "helao/hexagon/app/action_host.py",
        "helao/helpers/server_api.py",
    ):
        src = (REPO_ROOT / rel).read_text(encoding="utf-8")
        members |= set(re.findall(r"self\.([A-Za-z_][A-Za-z0-9_]*)\s*=", src))
    return members


def test_the_contract_extraction_is_not_vacuous() -> None:
    """A broken AST walk would make every coverage assertion pass for free."""
    contract = orch_contract()
    assert len(contract) > 120, f"only {len(contract)} members found; walk is inert"
    for known in ("action_dq", "globalstatusmodel", "_ensure_run_id", "add_sequence"):
        assert known in contract, f"{known} missing from the extraction"


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
