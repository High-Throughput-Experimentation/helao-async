"""``ActionHost`` must cover ``Base``'s member surface (B1).

B1 discovered missing host members one runtime crash at a time — `helaodirs`
(SYNC could not start), `begin_session` (every action POST 500'd), `write_act`
(the finalizer wrote nothing), `run_type`, `init_act`'s consequences. Each cost
a launch-and-diagnose cycle, and each was individually invisible to a suite of
seventy-odd passing unit tests.

The reason they stayed hidden is that
``helao/hexagon/tests/checklists/hte/_member_surface.md`` enumerates only what
*deployment code* touches. What ``Base``'s own collaborators and the write path
touch is a larger set that nobody had written down.

This module writes it down. It is a **ratchet**, not a pass/fail gate on
completeness:

* ``DELIBERATELY_ABSENT`` — members B1 replaces with a different mechanism, each
  with a reason. These are decisions, not debt.
* ``NOT_YET_PORTED`` — the real remaining work, frozen. Porting one means
  deleting it from this list; that edit is the point, because it makes progress
  visible and stops a member being quietly forgotten.

The test fails when the gap **grows** — a new ``Base`` member, or a host member
removed — rather than while it merely persists. A test that is permanently red
teaches people to ignore it; this repo already has one such case in
``test_palette``'s stale "EXPECTED TO FAIL" docstring.
"""

import ast
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
BASE_PY: Final[Path] = REPO_ROOT / "helao/core/servers/base.py"

#: Members B1 deliberately does not reproduce, grouped by why.
DELIBERATELY_ABSENT: Final[frozenset[str]] = frozenset(
    {
        # -- replaced by the explicit ActionContext (spec D-B1.1) ------------
        # The handler receives its action as a parameter; there is no
        # ContextVar and no setup_and_contain_action.
        "setup_action",
        "setup_and_contain_action",
        "contain_action",
        # -- the host IS the app; legacy's Base held a reference to it -------
        "app",
        # -- registered as routes, not as methods ----------------------------
        # ActionHost registers /ws_status, /ws_data and /ws_live directly on the
        # FastAPI app rather than exposing bound methods for them.
        "ws_status",
        "ws_data",
        "ws_live",
        # -- legacy collaborator objects whose surface the host implements ---
        # The host owns the queues and publishers directly instead of holding a
        # LiveBufferManager / StatusBroadcaster.
        "live_buffer_mgr",
        "status_broadcaster",
        # -- legacy lifecycle internals --------------------------------------
        # ActionHost uses FastAPI's startup event; these are Base's own task
        # handles and locks, not part of any caller's contract.
        "myinit",
        "aiolock",
        "bufferer",
        "dumper",
        "dumper_task",
        "status_logger",
        "regular_updater",
        # -- legacy config wrappers ------------------------------------------
        # The host reads world_cfg/server_cfg directly.
        "typed_cfg",
        "typed_server_cfg",
        # -- stored under a private name --------------------------------------
        # ActionHost keeps the callback as _dyn_endpoints and exposes
        # dyn_endpoints_init() instead.
        "dyn_endpoints",
        # -- legacy logging helper --------------------------------------------
        "print_message",
    }
)

#: The real remaining work. Frozen: porting one means deleting it from here.
NOT_YET_PORTED: Final[frozenset[str]] = frozenset(
    {
        # status fan-out to attached clients
        "attach_client",
        "detach_client",
        "detach_subscribers",
        "send_statuspackage",
        "send_nbstatuspackage",
        "status_clients",
        # NOTE: the host currently spells the first two
        # attach_status_client/detach_status_client. Legacy -- and therefore
        # every caller -- says attach_client/detach_client. Porting these means
        # renaming, not adding.
        # clock
        "ntp_offset",
        "ntp_last_sync",
        # action/executor surface deployment code reaches for
        "get_main_error",
        "stop_all_executor_prefix",
        "replace_status",
        "get_active_info",
        # background tasks
        "live_buffer_task",
        "log_status_task",
        "regular_status_task",
        # shutdown: the host has _shutdown; Base's public name is shutdown
        "shutdown",
        # hlo postprocessing
        "hlo_postprocess_libs",
        "hlo_postprocessors",
        "import_postprocessors",
        # orchestrator identity, set from config
        "orch_key",
        "orch_host",
        "orch_port",
        # misc legacy state
        "history",
    }
)


def _base_public_members() -> set[str]:
    """Every public method and ``self.x = ...`` attribute on legacy ``Base``."""
    tree = ast.parse(BASE_PY.read_text(encoding="utf-8"))
    members: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name == "Base"):
            continue
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not item.name.startswith("_"):
                    members.add(item.name)
        for sub in ast.walk(node):
            if (
                isinstance(sub, ast.Attribute)
                and isinstance(sub.value, ast.Name)
                and sub.value.id == "self"
                and isinstance(sub.ctx, ast.Store)
                and not sub.attr.startswith("_")
            ):
                members.add(sub.attr)
    return members


def _self_assigned(path: Path) -> set[str]:
    """Every ``self.x = ...`` attribute assigned in *path*."""
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


def _host_members() -> set[str]:
    """Class members plus instance attributes, including inherited ones.

    ``HelaoFastAPI.__init__`` assigns ``server``, ``server_cfg`` and
    ``server_params``; those are real members of every ActionHost but appear
    neither in ``dir()`` (they are instance attributes) nor in action_host.py
    (they are set by the parent). Missing this made the first run of this test
    report three phantom gaps -- the same hand-waving the module replaces.
    """
    from helao.hexagon.app.action_host import ActionHost

    members = {m for m in dir(ActionHost) if not m.startswith("__")}
    members |= _self_assigned(REPO_ROOT / "helao/hexagon/app/action_host.py")
    members |= _self_assigned(REPO_ROOT / "helao/helpers/server_api.py")
    return members


def test_the_base_member_extraction_is_not_vacuous() -> None:
    """A broken AST walk would make every coverage assertion pass for free."""
    members = _base_public_members()
    assert len(members) > 60, f"only {len(members)} Base members found; walk is inert"
    for known in ("write_act", "helaodirs", "world_cfg", "executors"):
        assert known in members, f"{known} missing from the extraction"


def test_no_new_gap_has_opened_in_the_host() -> None:
    """The ratchet.

    Fails when a ``Base`` member is neither covered, deliberately excluded, nor
    on the known-missing list — i.e. when someone adds to ``Base`` or removes
    from ``ActionHost``. It does not fail merely because NOT_YET_PORTED is
    non-empty; that set is the recorded remaining work.
    """
    missing = _base_public_members() - _host_members()
    unaccounted = sorted(missing - DELIBERATELY_ABSENT - NOT_YET_PORTED)
    assert unaccounted == [], (
        "Base members that ActionHost lacks and that are neither deliberately "
        f"excluded nor on the known-missing list: {unaccounted}\n"
        "Either port them, or add them to NOT_YET_PORTED with a reason."
    )


def test_the_known_missing_list_has_not_silently_grown() -> None:
    """Every entry in NOT_YET_PORTED must still actually be missing.

    Without this, a member could be ported and left on the list, and the list
    would slowly stop meaning anything. Porting one requires deleting it here,
    which is the edit that makes progress visible.
    """
    missing = _base_public_members() - _host_members()
    already_done = sorted(NOT_YET_PORTED - missing)
    assert already_done == [], (
        f"these are on NOT_YET_PORTED but ActionHost already has them: "
        f"{already_done}\nDelete them from the list."
    )


def test_deliberate_exclusions_are_actually_absent() -> None:
    """An exclusion that is no longer absent is a stale justification."""
    missing = _base_public_members() - _host_members()
    stale = sorted(DELIBERATELY_ABSENT - missing)
    assert stale == [], (
        f"listed as deliberately absent but present on ActionHost: {stale}\n"
        "Remove them from DELIBERATELY_ABSENT."
    )
