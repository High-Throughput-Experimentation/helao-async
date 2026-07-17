"""AnalysisArtifact port (spec §4.3.10): ONE way to publish an AnalysisRecord.

Unifies a private analysis deployment's three divergent analysis writers behind a single
"publish" seam producing the §5 row-13 layout (ANALYSES/<yy.ww>/<mmdd>/... +
per-output JSONs + analysis/<uuid>.json S3 keys, content-hash UUIDs).
Converters ENQUEUE analyses; they never write the layout themselves.
"""

from typing import List, Protocol, runtime_checkable

from helao.hexagon.domain.models import AnalysisModel, AnalysisOutputModel

__all__ = ["AnalysisArtifactPort"]


@runtime_checkable
class AnalysisArtifactPort(Protocol):
    async def publish(
        self, analysis: AnalysisModel, outputs: List[AnalysisOutputModel]
    ) -> bool: ...

    async def enqueue(self, analysis: AnalysisModel) -> None: ...
