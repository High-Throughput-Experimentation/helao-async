"""Native AnalysisArtifact adapter (hexagon P6e).

The :class:`~helao.hexagon.ports.analysis.AnalysisArtifactPort` implementor a
post-hoc converter publishes an analysis through. It owns no grammar of its
own: every path, key and body it produces comes from
:mod:`helao.core.drivers.data.analysis_layout`, the same module the live
analysis server's ``sync_ana`` writes through. That is the whole point of the
slice -- before it, a private deployment's XAFS converter carried a second,
drifted implementation of the layout, the S3 keys, the uuid derivation and the
upload, and the two had diverged in eleven measurable ways.

Two things this face decides that the server does not:

**The directory stamp is per-conversion.** ``ANALYSES/<yy.ww>/<mmdd>/<HHMMSS>__
<name>[__<suffix>]/`` takes its time components from one timestamp, and with
``group_dir=True`` (the post-hoc default) that timestamp is the FIRST record
published through this adapter. A conversion emitting several analyses used to
name each directory from that analysis's own timestamp, so three analyses of one
source landed in one directory or two depending on whether the batch happened to
straddle a second boundary -- measured on real captures: two runs produced one
directory, a third produced two. The path template is unchanged; what changes is
that the tree no longer depends on timing. The live server keeps
``group_dir=False``: its analyses arrive independently over the server's
lifetime and grouping them would be meaningless.

**``local_only`` is the absence of an uploader.** Constructing with
``uploader=None`` writes the local tree and pushes nothing, gating the model
body and every output group through one switch. The forked writer gated only
the output groups, so a capture run published junk analysis models to the real
bucket.
"""

import asyncio
from typing import Optional

from helao.core.drivers.data.analysis_layout import (
    Uploader,
    analysis_dir,
    analysis_suffix,
    parse_analysis_timestamp,
    publish_outputs,
    sequence_part_of,
    write_model_yml,
)
from helao.helpers import helao_logging as logging
from helao.hexagon.ports.analysis import AnalysisRecord

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

__all__ = ["NativeAnalysisArtifact"]


class NativeAnalysisArtifact:
    """Publish analysis records into the §5 row-13 layout.

    Attributes:
        ana_root: The ``ANALYSES`` root every record is written under.
        uploader: Async ``(payload, key, compress=...)`` callable, or None for
            local-only operation.
        group_dir: Whether every record shares the first record's directory
            stamp.
    """

    def __init__(
        self,
        ana_root: str,
        uploader: Optional[Uploader] = None,
        group_dir: bool = True,
    ) -> None:
        """Bind the adapter to an ANALYSES root and an optional uploader.

        Args:
            ana_root: Directory analyses are written under.
            uploader: Async uploader, or None for local-only.
            group_dir: When True (the post-hoc default), the first record's
                timestamp names the directory for every record published
                through this instance.
        """
        self.ana_root = ana_root
        self.uploader = uploader
        self.group_dir = group_dir
        self._group_stamp = None
        self._pending: list[AnalysisRecord] = []

    @property
    def pending(self) -> list[AnalysisRecord]:
        """Records enqueued but not yet published, in enqueue order."""
        return list(self._pending)

    def local_dir(self, record: AnalysisRecord) -> str:
        """Return the directory ``record`` will be written into.

        Latches the group stamp on first use when ``group_dir`` is set, so the
        answer is stable for every later record of the same conversion.

        Args:
            record: The record to place.

        Returns:
            The absolute directory path (not created).
        """
        stamp = parse_analysis_timestamp(record.model)
        if self.group_dir:
            if self._group_stamp is None:
                self._group_stamp = stamp
            stamp = self._group_stamp
        return analysis_dir(
            self.ana_root,
            stamp,
            record.model["analysis_name"],
            analysis_suffix(
                sequence_part_of(record.source_action_dir),
                record.model.get("global_sample_label", ""),
            ),
        )

    async def publish(self, record: AnalysisRecord) -> bool:
        """Write ``record``'s model yml and output JSONs, and upload them.

        Republishing an identical record overwrites the same paths rather than
        adding a second one: the analysis uuid is a content hash, so the record
        is idempotent by construction and this method needs no de-duplication of
        its own.

        Args:
            record: The analysis to publish.

        Returns:
            True when every upload succeeded, or when there is no uploader.
        """
        local_ana_dir = self.local_dir(record)
        await asyncio.to_thread(
            write_model_yml,
            local_ana_dir,
            record.model["analysis_uuid"],
            record.model,
        )
        return await publish_outputs(
            record.model, record.values, local_ana_dir, uploader=self.uploader
        )

    async def enqueue(self, record: AnalysisRecord) -> None:
        """Hold ``record`` for a later :meth:`flush`.

        Deferred publication for callers that assemble a conversion's analyses
        before writing any of them. Enqueuing latches the group stamp in
        enqueue order, so a caller that enqueues and then flushes gets the same
        directory a caller that published immediately would have.

        Args:
            record: The analysis to hold.
        """
        if self.group_dir and self._group_stamp is None:
            self._group_stamp = parse_analysis_timestamp(record.model)
        self._pending.append(record)

    async def flush(self) -> bool:
        """Publish every enqueued record, in enqueue order, and clear the queue.

        Returns:
            True when every record published successfully.
        """
        pending, self._pending = self._pending, []
        results = [await self.publish(record) for record in pending]
        return all(results)
