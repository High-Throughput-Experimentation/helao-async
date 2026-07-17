"""Artifact-content assembly (spec §4.2.1/§4.2.3, D8).

The domain's artifact assembly is "model -> clean_dict -> dict", nothing
else. For action/experiment/sequence, the ``file_type`` key is prepended
first exactly as base_meta_writer.py write_act/write_exp/write_seq do
(:98-105 / :117-130 / :138-152); the ArtifactStore adapter (P1b) dumps these
dicts via yml_dumps with a trailing newline and atomic replace. Byte-parity
is measured post-clean_dict (spec §5.3), never on model_dump().

Drift fixed vs the P1a brief: the brief's draft prepended a ``file_type``
key to ``assemble_process`` too. The legacy ``-prc.yml`` writer
(sync_driver.py:1698/1726) does NOT do this -- it writes
``ProcessModel.model_validate(meta).clean_dict(strip_private=True)``
straight through with no wrapping key. Fixed here so process artifacts stay
byte-identical to legacy; see test_assembly.py for the pinned assertion.
"""

from helao.hexagon.domain.models import (
    Action,
    Experiment,
    ProcessModel,
    Sequence,
)

__all__ = [
    "assemble_act",
    "assemble_exp",
    "assemble_process",
    "assemble_seq",
]


def assemble_act(action: Action) -> dict:
    """-act.yml content: {"file_type": "action"} + ActionModel.clean_dict()."""
    out = {"file_type": "action"}
    out.update(action.get_act().clean_dict())
    return out


def assemble_exp(experiment: Experiment) -> dict:
    """-exp.yml content (get_exp() rebuilds samples/files aggregates)."""
    out = {"file_type": "experiment"}
    out.update(experiment.get_exp().clean_dict())
    return out


def assemble_seq(sequence: Sequence) -> dict:
    """-seq.yml content (get_seq() snapshots dispatched_experiments_abbr)."""
    out = {"file_type": "sequence"}
    out.update(sequence.get_seq().clean_dict())
    return out


def assemble_process(meta: dict) -> dict:
    """-prc.yml content: ProcessModel-validated, strip_private=True.

    sync_driver.py:1698/1726 -- the only artifact assembled with
    strip_private, and (unlike act/exp/seq) with no file_type prefix.
    """
    return ProcessModel.model_validate(meta).clean_dict(strip_private=True)
