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


# ---------------------------------------------------------------------------
# The same fast-path gap, in the two other shapes a sweep of every RPC-reachable
# POST route found live: list[Model] (the orchestrator's /prepend_sequences) and
# Enum (MOTOR's /move_axis).
# ---------------------------------------------------------------------------

import enum

import pytest

from helao.deploy.hte.drivers.motion.enum import MoveModes
from helao.helpers.premodels import Sequence


class _Units(str, enum.Enum):
    mm = "mm"
    counts = "counts"


def _sequence_dict() -> dict:
    return Sequence(sequence_name="ECHEUVIS_diagnostic_CV").model_dump()


async def _prepend(sequences: list[Sequence] = Body([], embed=True)):
    return sequences


async def _move_axis(
    axis: str,
    value: float,
    mode: MoveModes = MoveModes.relative,
    units: _Units = _Units.mm,
):
    return units


async def _optional_enum(units: Optional[_Units] = None):
    return units


def test_list_of_models_is_rehydrated():
    # native OrchHost handed these straight to _prep_sequence_meta, which does
    # attribute access on each; the legacy route had model_validate'd them.
    out = _coerce_args(_prepend, {"sequences": [_sequence_dict(), _sequence_dict()]})
    assert all(isinstance(s, Sequence) for s in out["sequences"])
    assert out["sequences"][0].sequence_name == "ECHEUVIS_diagnostic_CV"


def test_enum_is_rehydrated():
    # The motion panel sends str(units.value); move_axis then calls units.value.
    out = _coerce_args(
        _move_axis, {"axis": "x", "value": 1.0, "mode": "absolute", "units": "counts"}
    )
    assert out["units"] is _Units.counts
    assert out["mode"] is MoveModes.absolute
    assert out["units"].value == "counts"


def test_optional_enum_is_rehydrated_and_none_kept():
    assert _coerce_args(_optional_enum, {"units": "mm"})["units"] is _Units.mm
    assert _coerce_args(_optional_enum, {"units": None})["units"] is None


def test_an_invalid_enum_value_is_refused_not_passed_through():
    # FastAPI would answer 422. Raising here fails the RPC call, the dispatcher
    # falls back to HTTP, and FastAPI answers 422 -- so the fast path is not a
    # way around validation. A misspelt "count" must never reach move_axis.
    with pytest.raises(ValueError):
        _coerce_args(_move_axis, {"axis": "x", "value": 1.0, "units": "count"})


def test_an_already_typed_enum_is_left_alone():
    out = _coerce_args(_move_axis, {"axis": "x", "value": 1.0, "units": _Units.mm})
    assert out["units"] is _Units.mm
