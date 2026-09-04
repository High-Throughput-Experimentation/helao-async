"""``acquire`` refuses when the driver has no wavelength axis.

Worth its own tier of test rather than trusting inspection: ``app.driver`` is
UNTYPED throughout ``andor_server``. The module writes ``app.driver:
AndorDriver`` as a bare annotation on an attribute expression, which pyright
rejects (``reportInvalidTypeForm``) and never applies, so nothing in that file
type-checks against the driver contract.

The registrar is exercised against a synthetic ``ActionHost``-shaped app -- the
same pattern ``test_endpoint_overlay`` uses -- because the point is what the
handler does before ``ctx.begin``, not how the real host wires it up.
"""

from types import SimpleNamespace

import numpy as np
import pytest

from helao.core.error import ErrorCodes
from helao.deploy.hte.servers.action.andor_server import andor_dyn_endpoints

SERVER_KEY = "ANDOR"


class _ReachedBegin(Exception):
    """Raised by the fake ``begin`` on the non-refusing path."""


class _FakeApp:
    """The subset of ``ActionHost`` ``andor_dyn_endpoints`` actually reads."""

    def __init__(self, wl_arr):
        self.driver = SimpleNamespace(
            wl_arr=wl_arr,
            connect=lambda: SimpleNamespace(status="ok"),
        )
        self.server = SimpleNamespace(server_name=SERVER_KEY)
        self.server_params: dict = {}
        self.executors: dict = {}
        self.handlers: dict = {}

    def action(self, *args, **kwargs):
        def decorate(func):
            self.handlers[func.__name__] = func
            return func

        return decorate


class _FakeActive:
    def __init__(self):
        self.action = SimpleNamespace(error_code=ErrorCodes.none, action_abbr=None)
        self.finished = False

    async def finish(self):
        self.finished = True
        return SimpleNamespace(as_dict=lambda: {"error_code": self.action.error_code})


class _FakeCtx:
    def __init__(self, *, raise_on_begin=False):
        self.begin_kwargs = None
        self.active = _FakeActive()
        self._raise_on_begin = raise_on_begin

    async def begin(self, **kwargs):
        self.begin_kwargs = kwargs
        if self._raise_on_begin:
            raise _ReachedBegin
        return self.active


async def _registered_acquire(wl_arr):
    app = _FakeApp(wl_arr)
    await andor_dyn_endpoints(app)  # type: ignore[arg-type]
    return app, app.handlers["acquire"]


@pytest.mark.asyncio
async def test_acquire_refuses_without_a_wavelength_axis():
    """A fallback pixel index would record a run against a fabricated axis."""
    _app, acquire = await _registered_acquire(None)
    ctx = _FakeCtx()

    result = await acquire(ctx)

    assert ctx.begin_kwargs == {}, "the refusal opens a bare action, no data keys"
    assert ctx.active.action.error_code == ErrorCodes.critical_error
    assert ctx.active.finished, "the refused action is finished, not left active"
    assert result == {"error_code": ErrorCodes.critical_error}


@pytest.mark.asyncio
async def test_acquire_proceeds_when_a_wavelength_axis_exists():
    """The guard must not fire on a calibrated station."""
    _app, acquire = await _registered_acquire(np.linspace(400.0, 900.0, 4))
    ctx = _FakeCtx(raise_on_begin=True)

    with pytest.raises(_ReachedBegin):
        await acquire(ctx)

    assert ctx.begin_kwargs is not None
    assert ctx.begin_kwargs["json_data_keys"] == [
        "elapsed_time_s",
        "ch_0000",
        "ch_0001",
        "ch_0002",
        "ch_0003",
    ]
    assert ctx.begin_kwargs["hloheader"].optional["wl"] == [
        pytest.approx(v) for v in np.linspace(400.0, 900.0, 4)
    ]
