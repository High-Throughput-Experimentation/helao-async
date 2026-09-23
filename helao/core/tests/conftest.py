"""Shared fixtures for helao/core/tests."""

import pytest

_LAST_CONTEXT: list = []


@pytest.fixture
def reflex_registration():
    """Give each test a Reflex registration context with no App in it.

    Importing ``helao.ui.reflex.app`` builds its module-level ``app``, and
    Reflex 0.9.12 allows only one App per registration context, so every
    ``build_app`` here raised "A RegistrationContext can only be associated
    with a single App". A fork carries the registrations but not the App.

    Each test forks the *previous* test's context, not the root one. Panel
    state classes are created once per process and register into whichever
    context is current at that moment; forking from the root every time would
    drop the ones an earlier test created, and the handler-registration checks
    would fail depending on test order. The import comes first so the
    module-level app lands in the root context, not in a fork.
    """
    from reflex_base.registry import RegistrationContext

    import helao.ui.reflex.app  # noqa: F401

    parent = (
        _LAST_CONTEXT[-1] if _LAST_CONTEXT else RegistrationContext.ensure_context()
    )
    context = parent.fork()
    _LAST_CONTEXT[:] = [context]
    with context:
        yield
