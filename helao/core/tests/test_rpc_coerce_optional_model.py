"""The RPC fast path must rehydrate ``Optional[Model]`` parameters.

``_coerce_args`` rebuilt a pydantic model from its msgpack ``dict`` only when the
annotation was the bare class. ``action: Optional[Action] = Body(None,
embed=True)`` -- the usual FastAPI spelling for an optional model -- got the raw
dict instead, so at anec every PAL call to SAMPLE's ``new_ref_samples`` raised

    AttributeError: 'dict' object has no attribute 'action_uuid'

inside the handler over RPC, logged a traceback, and only succeeded because the
dispatcher then fell back to HTTP, where FastAPI validates the body itself. A
fast path that fails on every call is a slow path with a stack trace.
"""

from typing import Optional, Union

from fastapi import Body

from helao.core.models.machine import MachineModel
from helao.core.rpc.zmq_rpc import _coerce_args
from helao.helpers.premodels import Action


def _action_dict() -> dict:
    return Action(
        action_name="PAL_injection_tray_HPLC",
        action_server=MachineModel(server_name="PAL", machine_name="testhost"),
    ).as_dict()


async def _optional_model(action: Optional[Action] = Body(None, embed=True)):
    return action


async def _pipe_optional_model(action: Action | None = Body(None, embed=True)):
    return action


async def _bare_model(action: Action = Body(..., embed=True)):
    return action


def test_optional_model_is_rehydrated():
    out = _coerce_args(_optional_model, {"action": _action_dict()})
    assert isinstance(out["action"], Action)
    # Attribute access is the thing that raised at anec.
    assert out["action"].action_name == "PAL_injection_tray_HPLC"


def test_pep604_optional_model_is_rehydrated():
    out = _coerce_args(_pipe_optional_model, {"action": _action_dict()})
    assert isinstance(out["action"], Action)


def test_bare_model_still_rehydrated():
    out = _coerce_args(_bare_model, {"action": _action_dict()})
    assert isinstance(out["action"], Action)


def test_an_explicit_none_stays_none():
    out = _coerce_args(_optional_model, {"action": None})
    assert out["action"] is None


def test_a_union_of_several_models_is_left_raw():
    # Ambiguous: the live case is the sample union, whose endpoints coerce
    # explicitly with object_to_sample. Guessing here would pick a type.
    class _A(Action):
        pass

    async def _union(x: Union[Action, _A, None] = None):
        return x

    raw = _action_dict()
    out = _coerce_args(_union, {"x": raw})
    assert out["x"] is raw
