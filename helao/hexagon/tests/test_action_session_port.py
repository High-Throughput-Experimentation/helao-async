"""The session Protocol is derived from the collaborators, not authored.

B1's spec first put the session's surface at the 18 members deployment code
uses. That is the deployment-facing contract; it is not the whole one. The three
native write collaborators were written against the legacy ``Active`` and reach
for 26 members, 19 of which are not in the 18. A session built to 18 imports,
registers, serves, and fails at the first ``enqueue_data`` with a bare
``AttributeError`` from inside a collaborator, while an action is writing data.

These tests re-run the derivation rather than trusting the Protocol's contents,
so a member added to a collaborator without being added to the port fails here
instead of at a station.
"""

import ast
from pathlib import Path
from typing import Final, get_type_hints

from helao.hexagon.ports.action_session import ActionSessionPort

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
COLLABORATORS: Final[tuple[str, ...]] = ("data_stream", "data_file", "finalizer")


def _members_read_off_the_back_reference() -> set[str]:
    """Every ``self.active.<name>`` the native collaborators touch."""
    found: set[str] = set()
    for mod in COLLABORATORS:
        path = REPO_ROOT / "helao/hexagon/adapters/native" / f"{mod}.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            inner = node.value
            if (
                isinstance(inner, ast.Attribute)
                and inner.attr == "active"
                and isinstance(inner.value, ast.Name)
                and inner.value.id == "self"
            ):
                found.add(node.attr)
    return found


def _protocol_members() -> set[str]:
    annotated = set(get_type_hints(ActionSessionPort).keys())
    callables = {
        name
        for name in vars(ActionSessionPort)
        if not name.startswith("__") and callable(vars(ActionSessionPort)[name])
    }
    return annotated | callables


def test_the_collaborators_still_read_exactly_what_the_port_declares() -> None:
    """The derivation, re-run. This is the whole point of the file.

    A member added to a collaborator without being added to the port shows up
    here as `missing`; a port member no collaborator uses shows up as `extra`
    and should be removed rather than kept "just in case" -- an unused member is
    an obligation on every future session implementation.
    """
    derived = _members_read_off_the_back_reference()
    declared = _protocol_members()
    assert derived == declared, (
        f"missing from ActionSessionPort: {sorted(derived - declared)}\n"
        f"declared but unused by any collaborator: {sorted(declared - derived)}"
    )


def test_the_derivation_is_not_vacuous() -> None:
    """A mis-rooted path would make the comparison above pass against nothing."""
    derived = _members_read_off_the_back_reference()
    assert len(derived) >= 20, f"only {len(derived)} members found; AST walk is inert"
    assert "enqueue_data" in derived
    assert "file_conn_dict" in derived


def test_the_legacy_active_satisfies_the_port() -> None:
    """The collaborators must keep working against a grafted legacy Active.

    Until B7 the graft is what production runs, so re-pointing the collaborators
    at the Protocol must not break the object they are bound to today.
    """
    from helao.core.servers.base import Active

    missing = [m for m in _protocol_members() if not hasattr(Active, m)]
    # Instance attributes set in __init__ are not class attributes; only the
    # methods are checkable this way, which is what matters for the binding.
    missing = [m for m in missing if callable(getattr(ActionSessionPort, m, None))]
    assert missing == [], f"legacy Active lacks port members: {missing}"


# ---------------------------------------------------------------------------
# ActionSession against the port (B1 Task 5)
# ---------------------------------------------------------------------------


def _session_class():
    from helao.hexagon.app.action_session import ActionSession

    return ActionSession


#: The 10 port members that are instance attributes assigned in __init__ rather
#: than class attributes, so `hasattr(cls, ...)` is False for them by design.
INSTANCE_ATTRS = {
    "action",
    "action_list",
    "active_uuid",
    "base",
    "data_logger",
    "file_conn_dict",
    "finish_lock",
    "listen_uuids",
    "num_data_queued",
    "num_data_written",
}


def test_action_session_implements_every_port_method() -> None:
    """The 16 callable members the collaborators invoke."""
    cls = _session_class()
    methods = _protocol_members() - INSTANCE_ATTRS
    missing = sorted(m for m in methods if not hasattr(cls, m))
    assert missing == [], f"ActionSession is missing port methods: {missing}"


def test_the_instance_attribute_split_is_exhaustive() -> None:
    """Guards the exemption above: every port member is a method or in the set.

    Without this, adding a member to INSTANCE_ATTRS would silently excuse a
    genuinely missing method from the test above.
    """
    cls = _session_class()
    unaccounted = sorted(
        m
        for m in _protocol_members()
        if not hasattr(cls, m) and m not in INSTANCE_ATTRS
    )
    assert (
        unaccounted == []
    ), f"port members neither method nor known attr: {unaccounted}"


def test_action_session_covers_the_deployment_facing_surface() -> None:
    """The 18 members deployment code uses, minus those set in __init__."""
    cls = _session_class()
    deployment = {
        "finish",
        "enqueue_data_dflt",
        "start_executor",
        "append_sample",
        "enqueue_data_nowait",
        "get_realtime_nowait",
        "finish_hlo_header",
        "write_file",
        "split",
        "track_file",
        "enqueue_data",
        "write_file_nowait",
        "set_estop",
        "oneoff_executor",
        "get_realtime",
    }
    missing = sorted(m for m in deployment if not hasattr(cls, m))
    assert missing == [], f"ActionSession is missing deployment members: {missing}"


def test_executor_entry_raises_rather_than_returning_none() -> None:
    """Task 6 is outstanding; a None return would record an action that never ran."""
    import pytest

    session = _session_class().__new__(_session_class())
    with pytest.raises(NotImplementedError, match="Task 6"):
        session.start_executor(object())


def test_a_session_can_actually_be_constructed(tmp_path) -> None:
    """Surface coverage is not construction. This is the difference.

    The class-level checks above passed while ``__init__`` still reached for
    ``host.get_realtime_nowait`` and ``host.dflt_file_conn_key``, neither of
    which existed. Only building one caught that.
    """
    import asyncio

    from helao.hexagon.adapters.native.artifact_store import (
        NativeArtifactStoreAdapter,
    )
    from helao.hexagon.app.action_host import ActionHost
    from helao.hexagon.app.action_session import ActionSession
    from helao.hexagon.app.wiring import PortWiring
    from helao.helpers.premodels import Action

    class _Clock:
        def now_ns(self):
            return 0

        def offset(self):
            return 0.0

    class _Stub:
        def __getattr__(self, name):
            raise AssertionError(f"port member {name!r} used unexpectedly")

    store = NativeArtifactStoreAdapter(config=_Stub(), clock=_Clock())
    host = ActionHost(
        server_key="SIM",
        server_title="SIM",
        description="session construction",
        version=1.0,
        wiring=PortWiring(
            config=_Stub(),
            logging=_Stub(),
            clock=_Clock(),
            transport=_Stub(),
            state_persistence=_Stub(),
            status=_Stub(),
            health=_Stub(),
            artifact_store=store,
            data_sink=_Stub(),
        ),
        helao_cfg={
            "root": str(tmp_path),
            "servers": {"SIM": {"host": "127.0.0.1", "port": 8002, "params": {}}},
        },
    )
    session = asyncio.run(ActionSession.open(host, Action(action_name="acquire_data")))

    assert isinstance(session, ActionSessionPort), "session does not satisfy the port"
    # the default file connection is keyed independently of the action uuid
    assert list(session.file_conn_dict) == [host.dflt_file_conn_key()]
    assert session.base is host
    # the native collaborators were constructed, not grafted on afterwards
    assert session.data_stream is not None
    assert session.data_file_writer is not None
    assert session.action_finalizer is not None
    # and the host is tracking it
    assert host._actives[session.action.action_uuid] is session
