"""custom_add_liquid on an empty custom position: refused unless allow_empty.

The NoneSample guard keeps a liquid from being recorded without the solid it
was meant to wet; ANEC_sub_flush_fill_cell opts out with allow_empty=True so
a flush into an empty cell records a liquid-only sample instead of failing.
"""

import asyncio
from copy import deepcopy
from types import SimpleNamespace

from helao.core.error import ErrorCodes
from helao.core.models.sample import LiquidSample, NoneSample, SampleStatus
from helao.deploy.hte.drivers.data.archive_driver import Archive
from helao.helpers.sample_positions import Custom, CustomTypes


class _DB:
    """Knows only the reservoir; any other lookup comes back empty."""

    def __init__(self, reservoir):
        self.reservoir = reservoir

    async def get_samples(self, samples):
        s = samples[0]
        if s.sample_type == "liquid" and s.sample_no == self.reservoir.sample_no:
            return [deepcopy(self.reservoir)]
        return []

    async def new_samples(self, samples):
        return [deepcopy(s) for s in samples]

    async def update_samples(self, samples):
        return None


def _archive(loaded=None):
    reservoir = LiquidSample(sample_no=1511, machine_name="host", volume_ml=100.0)
    archive = object.__new__(Archive)
    archive.unified_db = _DB(reservoir)  # type: ignore
    archive.archivejson = None
    cell = Custom(custom_name="cell1_we", custom_type=CustomTypes.cell)
    if loaded is not None:
        cell.sample = loaded
    archive.positions = SimpleNamespace(customs_dict={"cell1_we": cell})  # type: ignore

    async def new_ref_samples(samples_in, sample_out_type, sample_position, **kw):
        return ErrorCodes.none, [
            LiquidSample(sample_no=1, machine_name="host", volume_ml=0.0)
        ]

    archive.new_ref_samples = new_ref_samples  # type: ignore
    return archive


def _add(archive, allow_empty):
    return asyncio.run(
        archive.custom_add_liquid(
            custom="cell1_we",
            source_liquid_in=LiquidSample(sample_no=1511, machine_name="host"),
            volume_ml=1.0,
            allow_empty=allow_empty,
        )
    )


def test_empty_position_refused_by_default():
    archive = _archive()
    error, _, samples_out = _add(archive, allow_empty=False)
    assert error == ErrorCodes.no_sample
    assert samples_out == []
    assert archive.positions.customs_dict["cell1_we"].sample == NoneSample()


def test_empty_position_gets_liquid_only_sample_with_allow_empty():
    archive = _archive()
    error, samples_in, samples_out = _add(archive, allow_empty=True)
    assert error == ErrorCodes.none
    assert [s.sample_type for s in samples_out] == ["liquid"]
    assert samples_out[0].volume_ml == 1.0
    loaded = archive.positions.customs_dict["cell1_we"].sample
    assert isinstance(loaded, LiquidSample) and loaded.volume_ml == 1.0
    assert samples_in[0].volume_ml == 100.0


def test_empty_position_persisted_by_older_commit_still_accepted():
    # the archive JSON keeps the hlo_version stamped when the cell was emptied
    archive = _archive(loaded=NoneSample(hlo_version="0ldc0mm"))
    error, _, samples_out = _add(archive, allow_empty=True)
    assert error == ErrorCodes.none
    assert [s.sample_type for s in samples_out] == ["liquid"]


def test_altered_none_sample_refused_even_with_allow_empty():
    archive = _archive(loaded=NoneSample(status=[SampleStatus.destroyed]))
    error, _, samples_out = _add(archive, allow_empty=True)
    assert error == ErrorCodes.no_sample
    assert samples_out == []
