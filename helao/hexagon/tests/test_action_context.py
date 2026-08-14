"""The explicit action context (spec D-B1.1).

Legacy reconstructs an ``Action`` from FastAPI's resolved kwargs inside
``wrap_action_endpoint`` and stashes it in a ``ContextVar``, which is why
``setup_and_contain_action()`` takes no request argument. B1 makes the dependency
a parameter instead, so a handler is callable without a request -- which is what
these tests do.

The behaviours pinned here are ported from ``base_api._build_action_from_kwargs``
verbatim. Three of them are load-bearing in non-obvious ways and are called out
in the individual docstrings.
"""

import inspect

from helao.hexagon.app.action_context import (
    action_version,
    build_action,
    collect_default_params,
)
from helao.hexagon.domain.models import Action


def test_an_orchestrator_envelope_is_used_as_the_base_action() -> None:
    """The orchestrator POSTs a fully-formed Action; it must not be rebuilt.

    Rebuilding would mint a new action_uuid and orphan the record the
    orchestrator is already tracking.
    """
    envelope = Action(action_name="acquire_data")
    envelope.action_params["duration"] = 5.0
    got = build_action({"action": envelope, "duration": 5.0}, {}, None)
    assert got is envelope
    assert got.action_params["duration"] == 5.0


def test_loose_kwargs_fold_into_action_params() -> None:
    got = build_action({"duration": 2.0, "rate": 0.5}, {}, None)
    assert got.action_params == {"duration": 2.0, "rate": 0.5}


def test_an_envelope_value_wins_over_a_loose_kwarg() -> None:
    """The dispatcher already resolved these -- a kwarg must not overwrite one."""
    envelope = Action(action_name="x")
    envelope.action_params["duration"] = 9.0
    got = build_action({"action": envelope, "duration": 1.0}, {}, None)
    assert got.action_params["duration"] == 9.0


def test_defaults_not_supplied_by_the_caller_are_recorded() -> None:
    """The ZMQ-RPC fast path does not synthesize FastAPI's defaults.

    Without this the action record would omit parameters the endpoint actually
    ran with, which is a silent artifact difference rather than an error.
    """
    got = build_action({}, {"duration": -1, "rate": 0.2}, None)
    assert got.action_params == {"duration": -1, "rate": 0.2}


def test_a_missing_envelope_yields_a_blank_action_without_raising() -> None:
    """An action-tagged *query* endpoint reached over RPC supplies no envelope.

    Legacy logs this at debug and proceeds with a blank Action. Raising here
    would break PAL's ``list_new_samples`` and its kin, which are action-tagged
    but do not use the action machinery at all.
    """
    got = build_action({}, {}, None)
    assert isinstance(got, Action)


def test_code_identity_is_taken_from_the_endpoint_function() -> None:
    """These three fields are stripped by the golden normalizer.

    ``harness/yaml_pass.py`` lists ``_codehash``/``_codepath``/``_funcname`` in
    DROP_KEY_SUFFIXES, so no GM diff and no route-surface diff can see a
    regression here -- this test and test_action_code_identity are the only
    things watching them.

    ``action_codehash`` is asserted to be a ``str`` rather than non-empty on
    purpose: :func:`get_filehash` shells out to ``git log -n 1 -- <file>`` and
    returns ``""`` for a file with no commit touching it yet. Every action
    recorded from an uncommitted working file therefore carries an empty
    codehash -- legacy does the same, and B1 preserves it.
    """

    def sample_endpoint():
        return None

    got = build_action({}, {}, sample_endpoint)
    assert got.action_funcname == "sample_endpoint"
    assert isinstance(got.action_codehash, str)
    assert got.action_codepath.endswith("test_action_context.py")


def test_code_identity_is_absent_when_no_endpoint_is_supplied() -> None:
    """An RPC query call carries no endpoint function; the fields stay unset."""
    got = build_action({}, {}, None)
    assert got.action_funcname is None
    assert got.action_codepath is None


def test_action_version_marks_the_function() -> None:
    @action_version(3)
    def handler():
        return None

    assert getattr(handler, "__helao_action_version__") == 3


def test_collect_default_params_reads_the_signature() -> None:
    def handler(a, b=2, c="x"):
        return None

    assert collect_default_params(inspect.signature(handler)) == {"b": 2, "c": "x"}


def test_collect_default_params_skips_the_context_parameter() -> None:
    """``ctx`` is supplied by the host, not by the caller, and is not a param."""

    def handler(ctx, duration: float = -1):
        return None

    assert collect_default_params(inspect.signature(handler)) == {"duration": -1}
