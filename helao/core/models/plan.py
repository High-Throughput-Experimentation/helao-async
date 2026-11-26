"""Plan sidecars: what a sequence or experiment intended, written once at its start.

Spec ``docs/superpowers/specs/2026-11-24-record-schema-slimming-design.md`` §3.3.
Entries are stripped: no experiment/action params, no output dirs. The record's
``experiment_list``/``action_list`` say what actually ran.
"""

__all__ = [
    "ExperimentPlanEntry",
    "SequencePlanEntry",
    "experiment_plan",
    "plan_name",
    "sequence_plan",
]

from pathlib import Path
from typing import Optional
from uuid import UUID

from pydantic import BaseModel

from helao.core.helaodict import HelaoDict

from .action_start_condition import ActionStartCondition


class SequencePlanEntry(BaseModel, HelaoDict):
    """One planned experiment. Uuids are assigned at dispatch, so there is none here."""

    order: int
    experiment_name: Optional[str] = None
    experiment_comment: Optional[str] = None
    orch_key: Optional[str] = None
    orch_host: Optional[str] = None
    orch_port: Optional[int] = None
    data_request_id: Optional[UUID] = None
    from_global_exp_params: dict = {}


class ExperimentPlanEntry(BaseModel, HelaoDict):
    """One planned action, uuid included (assigned when the action is staged)."""

    action_order: int
    action_uuid: Optional[UUID] = None
    action_name: Optional[str] = None
    server_name: Optional[str] = None
    start_condition: Optional[ActionStartCondition] = None
    process_finish: bool = False


def plan_name(record_file: str) -> str:
    """``<dir>/<ts>-seq.json`` (or ``.yml``) -> ``<ts>-seq.plan.json``."""
    return Path(record_file).with_suffix("").name + ".plan.json"


def sequence_plan(sequence_uuid, planned: list) -> dict:
    """Payload for ``<ts>-seq.plan.json`` from a list of ``ShortExperimentModel``."""
    entries = [
        SequencePlanEntry.model_validate({**e.model_dump(), "order": i})
        for i, e in enumerate(planned)
    ]
    return {
        "file_type": "sequence_plan",
        "sequence_uuid": str(sequence_uuid),
        "planned": [e.as_dict() for e in entries],
    }


def experiment_plan(experiment_uuid, actions: list) -> dict:
    """Payload for ``<ts>-exp.plan.json`` from staged ``Action`` objects."""
    entries = [
        ExperimentPlanEntry(
            action_order=a.action_order if a.action_order is not None else i,
            action_uuid=a.action_uuid,
            action_name=a.action_name,
            server_name=a.action_server.server_name,
            start_condition=a.start_condition,
            process_finish=bool(a.process_finish),
        )
        for i, a in enumerate(actions)
    ]
    return {
        "file_type": "experiment_plan",
        "experiment_uuid": str(experiment_uuid),
        "planned": [e.as_dict() for e in entries],
    }
