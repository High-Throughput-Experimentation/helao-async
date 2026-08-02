"""Typed action/experiment parameter models for the test deployment (CARDS 3d pilot).

Pattern contract (deployment adopters copy this, not the sim internals):
- one model per authored params payload; fields declared in the legacy dict's key order
- model_config: extra="forbid" (kills authored-key typos), use_enum_values=True (dumps plain str)
- .model_dump() feeds apm.add / epm.add UNCHANGED — wire shape is byte-identical to the
  literal dict it replaces (proven by unit_test_oersim_params + the e2e gate)
- import cost: pydantic only; NEVER house these in a driver module (a driver can pull in
  a heavy optional stack -- gpsim_driver drags in gpytorch/torch)
"""

from enum import StrEnum
from typing import Union

from pydantic import BaseModel, ConfigDict


class StopCondition(StrEnum):
    """Stop-condition dispatch keys for GPSim.check_condition (legacy string values, verbatim)."""

    none = "none"
    max_iters = "max_iters"
    max_stdev = "max_stdev"
    max_ei = "max_ei"


def resolve_stop_condition(value) -> StopCondition:
    """Coerce a wire value to StopCondition; clear error on unknown (was: bare KeyError)."""
    try:
        return StopCondition(value)
    except ValueError:
        valid = ", ".join(m.value for m in StopCondition)
        raise ValueError(f"invalid stop_condition {value!r}; valid: {valid}") from None


class _ParamModel(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)


# --- action-level payloads (feed apm.add) ---
class CPSIMChangePlateParams(_ParamModel):
    plate_id: int = 0


class GPSIMInitializePlateParams(_ParamModel):
    num_random_points: int = 5
    reinitialize: bool = False


class GPSIMCheckConditionParams(_ParamModel):
    stop_condition: StopCondition = StopCondition.max_iters
    thresh_value: Union[int, float] = 10
    repeat_experiment_name: str = "OERSIM_sub_activelearn"
    repeat_experiment_params: dict = {}
    repeat_experiment_kwargs: dict = {}


# --- experiment-level payloads (validate exp-function inputs / feed epm.add) ---
class OERSIMSubLoadPlateParams(_ParamModel):
    plate_id: int = 0
    init_random_points: int = 5


class OERSIMSubActivelearnParams(_ParamModel):
    init_random_points: int = 5
    stop_condition: StopCondition = StopCondition.max_iters
    thresh_value: Union[int, float] = 10
    repeat_experiment_kwargs: dict = {}


class OERSIMActivelearnSeqParams(_ParamModel):
    init_random_points: int = 5
    stop_condition: StopCondition = StopCondition.max_iters
    thresh_value: Union[int, float] = 10
