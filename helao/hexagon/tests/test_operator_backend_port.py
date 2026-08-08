"""P7h: the operator-backend port is a mirror of ``OrchBackend`` that cannot drift.

``OrchBackend`` is already a port in all but name -- an async ABC with one
implementation, injected into both operator UIs. P7h mirrors it rather than
moving it: moving would edit ``bokeh_operator.py`` (forbidden) and break the
59-test standalone-operator gate. What a mirror needs, and what these tests
provide, is a way to fail when it stops being one.
"""

import asyncio
import inspect

import pytest

from helao.core.error import ErrorCodes
from helao.core.servers.operator import helao_operator
from helao.core.servers.operator.orch_backend import OrchBackend, RemoteBackend
from helao.hexagon.ports.operator_backend import OperatorBackendPort
from helao.hexagon.tests.mirror_pin import abc_surface, protocol_members


class _FakeDirs:
    user_exp = None
    user_seq = None


class _FakeVis:
    """The two attributes ``RemoteBackend.__init__`` reads, and nothing else."""

    def __init__(self):
        self.world_cfg = {
            "servers": {
                "ORCH": {"group": "orchestrator", "host": "127.0.0.1", "port": 8001}
            }
        }
        self.helaodirs = _FakeDirs()


@pytest.fixture
def backend():
    """A ``RemoteBackend`` with empty libraries and no transport of its own."""
    return RemoteBackend(_FakeVis())


def _fake_transport(calls, resp, err=ErrorCodes.none):
    """A stand-in for ``async_private_dispatcher`` that records its calls."""

    async def _dispatch(
        orch_key, host, port, endpoint, params_dict=None, json_dict=None
    ):
        calls.append(
            {
                "orch_key": orch_key,
                "host": host,
                "port": port,
                "endpoint": endpoint,
                "params_dict": params_dict,
                "json_dict": json_dict,
            }
        )
        return resp, err

    return _dispatch


# --- the drift pin -----------------------------------------------------------


def test_the_port_and_the_abc_declare_the_same_members():
    """Set-equal **both ways**, which is the only version that works.

    A one-way check ("every ABC method is in the Protocol") misses a Protocol
    that has grown a method the backend never implements -- a contract naming
    something no implementation provides. The other one-way check misses the
    ABC growing a method the mirror never heard of. The equality reports both,
    and names them, so the failure says what to add and where.
    """
    legacy = abc_surface(OrchBackend)
    mirrored = protocol_members(OperatorBackendPort)
    assert legacy == mirrored, {
        "in the ABC only": sorted(legacy - mirrored),
        "in the port only": sorted(mirrored - legacy),
    }


def test_the_mirrored_surface_is_the_measured_one():
    """28 abstract methods and 4 library attributes, counted not assumed.

    The plan and Q8 both say "25-method ABC"; measured, it is 28 abstract
    methods (four of them synchronous) plus the four library dicts the class
    annotates, for 32 members. Pinning the count as well as the names catches
    a change that swaps one member for another -- the names would differ, but
    only the count says at a glance that the surface grew or shrank.
    """
    assert len(OrchBackend.__abstractmethods__) == 28
    assert set(OrchBackend.__annotations__) == {
        "sequence_lib",
        "experiment_lib",
        "sequence_codehash",
        "experiment_codehash",
    }
    assert len(protocol_members(OperatorBackendPort)) == 32


def test_each_mirrored_method_keeps_its_async_ness():
    """A name-set pin cannot see ``async``, and awaiting a sync method is a bug.

    Four of the 28 are synchronous -- ``unpack_sequence``, ``get_step_flags``,
    ``subscribe``, ``close`` -- because they touch no transport. If the mirror
    declared one of them ``async`` (or made an awaited method sync), every name
    would still match while a caller written against the port would either
    await a plain dict or drop a coroutine on the floor unawaited.
    """
    mismatched = {}
    for name in protocol_members(OperatorBackendPort):
        legacy_member = getattr(OrchBackend, name, None)
        mirrored = getattr(OperatorBackendPort, name, None)
        if not inspect.isfunction(legacy_member):
            continue  # the four annotated library dicts
        if inspect.iscoroutinefunction(legacy_member) != inspect.iscoroutinefunction(
            mirrored
        ):
            mismatched[name] = {
                "abc is async": inspect.iscoroutinefunction(legacy_member),
                "port is async": inspect.iscoroutinefunction(mirrored),
            }
    assert mismatched == {}
    # ...and the four synchronous ones are the four we think they are, so this
    # test cannot pass vacuously by finding no async methods at all.
    sync = {
        name
        for name in protocol_members(OperatorBackendPort)
        if inspect.isfunction(getattr(OrchBackend, name, None))
        and not inspect.iscoroutinefunction(getattr(OrchBackend, name))
    }
    assert sync == {"unpack_sequence", "get_step_flags", "subscribe", "close"}


def test_the_one_implementation_satisfies_the_port(backend):
    """``RemoteBackend`` is the face; there is no adapter to go stale.

    Checked on an *instance*: the four library attributes are set in
    ``__init__``, so the class object alone does not satisfy the Protocol --
    and ``issubclass`` against a Protocol carrying data members raises anyway.
    """
    assert isinstance(backend, OperatorBackendPort)


# --- a behavioural call, because the drift pin only compares names ----------


def test_get_orch_state_through_the_port_reaches_the_configured_orch(backend):
    """The mandatory non-vacuous call: names matching proves nothing works.

    ``isinstance`` against a ``runtime_checkable`` Protocol checks names only
    -- an object with 32 attributes set to ``None`` passes it. So drive one
    method through a port-typed reference and assert the wire call it makes.
    """
    calls = []
    backend._dispatch = _fake_transport(calls, {"orch_state": "idle"})
    port: OperatorBackendPort = backend

    state = asyncio.run(port.get_orch_state())

    assert state == {"orch_state": "idle"}
    assert len(calls) == 1
    assert calls[0]["endpoint"] == "get_orch_state"
    assert (calls[0]["orch_key"], calls[0]["host"], calls[0]["port"]) == (
        "ORCH",
        "127.0.0.1",
        8001,
    )


def test_a_failed_call_through_the_port_is_an_empty_state_not_a_raise(backend):
    """The operator polls this on a timer; a raise would take the page down.

    ``_call`` logs and returns ``None`` on a non-``none`` error code, and
    ``get_orch_state`` turns that into ``{}``. A caller renders "nothing known"
    rather than a traceback -- which matters because the commonest reason for
    the failure is the orchestrator restarting.
    """
    calls = []
    backend._dispatch = _fake_transport(calls, None, ErrorCodes.not_available)
    port: OperatorBackendPort = backend

    assert asyncio.run(port.get_orch_state()) == {}
    assert len(calls) == 1


# --- the serialization seam: pinned, deliberately not unified ---------------


def test_the_two_operator_serializations_are_measurably_different():
    """``as_dict`` and ``model_dump`` are a seam, not an inconsistency.

    ``helao_operator.py`` enqueues with ``.as_dict()`` (:118-138) where
    ``RemoteBackend`` uses ``.model_dump()`` (``orch_backend.py:266-277``).
    Nine callers depend on the headless form, seven of them batch scripts in a
    private deployment. The difference is real and this test measures it rather
    than asserting it: ``as_dict`` is a JSON-ready coercion (UUIDs stringified,
    floats rounded to 9 places) while ``model_dump`` returns live Python
    objects at full precision. Unifying them would change what those scripts
    put on the wire.
    """
    from uuid import UUID

    from helao.helpers.premodels import Sequence

    seq = Sequence(
        sequence_name="demo",
        sequence_params={"v": 0.12345678901234, "p": UUID(int=0xAB)},
    )
    seq.sequence_uuid = UUID("12345678-1234-5678-1234-567812345678")

    as_dict, model_dump = seq.as_dict(), seq.model_dump()

    assert as_dict["sequence_uuid"] == "12345678-1234-5678-1234-567812345678"
    assert model_dump["sequence_uuid"] == UUID("12345678-1234-5678-1234-567812345678")
    assert as_dict["sequence_params"]["v"] == 0.123456789  # rounded to 9 places
    assert model_dump["sequence_params"]["v"] == 0.12345678901234  # untouched
    assert as_dict["sequence_params"]["p"] == "00000000-0000-0000-0000-0000000000ab"
    assert model_dump["sequence_params"]["p"] == UUID(int=0xAB)


def test_each_operator_keeps_the_serialization_its_callers_expect():
    """Pin *which* side uses which, by reading the source of both enqueues.

    The measurement above shows the two shapes differ; this shows the split has
    not moved. A port adapter that "harmonised" them would flip one of these
    and nothing else in the suite would notice -- the wire stays well-formed
    either way, it just stops being the shape the consumer parses.
    """
    headless = inspect.getsource(helao_operator.HelaoOperator.add_sequence)
    remote = inspect.getsource(RemoteBackend.add_sequence)

    assert ".as_dict()" in headless and ".model_dump()" not in headless
    assert ".model_dump()" in remote and ".as_dict()" not in remote
