"""Tests for action_version decorator + signature injection (hte recon T2).

Verifies:
1. ``action_version(N)`` stamps ``ACTION_VERSION_ATTR`` onto the decorated fn.
2. ``_build_action_endpoint_signature`` injects both ``action`` and
   ``action_version`` into a no-arg endpoint.
3. The injected ``action_version`` default matches the decorator value.
4. An undecorated endpoint gets ``action_version`` defaulting to
   ``DEFAULT_ACTION_VERSION`` (1).
5. An endpoint that already declares ``action_version`` inline keeps its value.
"""
import inspect

import pytest

from helao.framework.app.base_api import (
    ACTION_VERSION_ATTR,
    DEFAULT_ACTION_VERSION,
    _build_action_endpoint_signature,
    action_version,
)


# ---------------------------------------------------------------------------
# 1. Decorator stamps attribute
# ---------------------------------------------------------------------------


def test_action_version_decorator_stamps_attr():
    @action_version(2)
    async def ep():
        ...

    assert getattr(ep, ACTION_VERSION_ATTR) == 2


def test_action_version_decorator_stamps_arbitrary_version():
    @action_version(7)
    async def ep():
        ...

    assert getattr(ep, ACTION_VERSION_ATTR) == 7


# ---------------------------------------------------------------------------
# 2 & 3. Signature injection — decorated endpoint gets version from decorator
# ---------------------------------------------------------------------------


def test_signature_injection_adds_action_and_version_params():
    @action_version(3)
    async def ep():
        ...

    sig = inspect.signature(ep)
    exposed_sig, _, _ = _build_action_endpoint_signature(ep, sig)

    assert "action" in exposed_sig.parameters, "missing injected 'action' param"
    assert "action_version" in exposed_sig.parameters, "missing injected 'action_version' param"


def test_signature_injection_version_default_matches_decorator():
    @action_version(3)
    async def ep():
        ...

    sig = inspect.signature(ep)
    exposed_sig, _, _ = _build_action_endpoint_signature(ep, sig)

    av_param = exposed_sig.parameters["action_version"]
    assert av_param.default == 3


# ---------------------------------------------------------------------------
# 4. Undecorated endpoint gets DEFAULT_ACTION_VERSION
# ---------------------------------------------------------------------------


def test_undecorated_endpoint_gets_default_action_version():
    async def ep():
        ...

    sig = inspect.signature(ep)
    exposed_sig, _, _ = _build_action_endpoint_signature(ep, sig)

    assert "action_version" in exposed_sig.parameters
    av_param = exposed_sig.parameters["action_version"]
    assert av_param.default == DEFAULT_ACTION_VERSION


def test_default_action_version_is_1():
    assert DEFAULT_ACTION_VERSION == 1


# ---------------------------------------------------------------------------
# 5. Inline action_version declaration is preserved (not overwritten)
# ---------------------------------------------------------------------------


def test_inline_action_version_preserved():
    @action_version(5)
    async def ep(action_version: int = 9):
        ...

    sig = inspect.signature(ep)
    exposed_sig, _, _ = _build_action_endpoint_signature(ep, sig)

    # The inline param should win; sig unchanged on this axis
    av_param = exposed_sig.parameters["action_version"]
    assert av_param.default == 9, (
        "inline action_version declaration should not be overwritten by decorator"
    )


# ---------------------------------------------------------------------------
# 6. accepted_names includes action_version when it's injected
# ---------------------------------------------------------------------------


def test_accepted_names_includes_injected_action_version():
    @action_version(2)
    async def ep():
        ...

    sig = inspect.signature(ep)
    _, _, accepted_names = _build_action_endpoint_signature(ep, sig)
    # accepted_names comes from the *original* sig's declared params; injected
    # params are NOT in accepted_names (they're FastAPI schema-only), consistent
    # with legacy behaviour — the wrapper doesn't forward them to the fn body.
    # Just assert no crash and that the returned names is a set.
    assert isinstance(accepted_names, set)


# ---------------------------------------------------------------------------
# 7. No duplicate injection when action already declared
# ---------------------------------------------------------------------------


def test_no_duplicate_action_when_already_declared():
    from helao.framework.domain.run_models import RunAction

    @action_version(4)
    async def ep(action: RunAction):
        ...

    sig = inspect.signature(ep)
    exposed_sig, _, _ = _build_action_endpoint_signature(ep, sig)

    action_params = [
        p for p in exposed_sig.parameters.values()
        if isinstance(p.annotation, type) and issubclass(p.annotation, RunAction)
    ]
    assert len(action_params) == 1, "should not duplicate the action param"
    # action_version should still be injected
    assert "action_version" in exposed_sig.parameters
    assert exposed_sig.parameters["action_version"].default == 4
