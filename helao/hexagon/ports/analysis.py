"""AnalysisArtifact port (spec §4.3.10): ONE way to publish an AnalysisRecord.

Unifies a private analysis deployment's divergent analysis writers behind a
single "publish" seam producing the §5 row-13 layout
(``ANALYSES/<yy.ww>/<mmdd>/<HHMMSS>__<name>[__<suffix>]/`` + per-output JSONs +
``analysis/<uuid>.json`` S3 keys, content-hash UUIDs). Converters ENQUEUE
analyses; they never write the layout themselves.

Amendment 2 (2026-08-08) measured the scope at **two** writers, not three: the
XRF-quantification converter emits no analysis record at all -- its records
already reach the layout through the live analysis server -- so the port's
consumers are that server and the post-hoc converters whose inline copy it
replaced.
"""

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

__all__ = ["AnalysisArtifactPort", "AnalysisRecord"]


@dataclass(frozen=True)
class AnalysisRecord:
    """One analysis, complete enough to lay out on disk and push to a bucket.

    ``model`` is the CLEANED ``AnalysisModel`` dict -- what lands verbatim in
    ``<analysis_uuid>.yml`` -- rather than the model object, because a caller
    may legitimately add keys after validation (the live server copies
    campaign/run metadata off the source process onto it), and re-validating
    would risk the written body differing from the published one.

    ``values`` is the FLAT ``{output_key: value}`` mapping spanning every output
    group, including the arrays the model's ``outputs`` entries deliberately
    omit; each group's JSON body is selected out of it by ``output_keys``.

    ``source_action_dir`` is the ``action_output_dir`` of the first action of
    the analysed process. It is carried because the directory-name suffix rule
    reads the sequence directory out of it, and nothing else in the model does.

    Attributes:
        model: Cleaned analysis-model dict.
        values: Flat mapping of every output key to its value.
        source_action_dir: First source action's output directory.
    """

    model: dict
    values: dict = field(default_factory=dict)
    source_action_dir: str = ""


@runtime_checkable
class AnalysisArtifactPort(Protocol):
    async def publish(self, record: AnalysisRecord) -> bool: ...

    async def enqueue(self, record: AnalysisRecord) -> None: ...
