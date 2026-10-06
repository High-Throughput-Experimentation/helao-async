"""Archive combine paths: adding to a same-kind sample, and combining references.

- Adding a liquid (or gas) onto a cell that holds the same kind with
  combine off builds an assembly of the two, instead of raising on an
  assembly that has no volume_ml.
- new_ref_samples(combine_liquids=True) returns one combined liquid only;
  it used to also return an assembly, which the add path then wrote to the
  db as an orphan row on every liquid merge.
"""

import asyncio
import uuid
from copy import deepcopy
from types import SimpleNamespace

import pytest

from helao.core.error import ErrorCodes
from helao.core.models.sample import GasSample, LiquidSample, SampleType
from helao.deploy.hte.drivers.data.archive_driver import Archive
from helao.helpers.sample_positions import Custom, CustomTypes

ACTION = SimpleNamespace(action_uuid=uuid.UUID(int=1), experiment_uuid=uuid.UUID(int=2))
KIND = {"liquid": LiquidSample, "gas": GasSample}


class _DB:
    def __init__(self, *samples):
        self.rows = {}
        self.created = []
        self.n = 100
        for s in samples:
            self.rows[(str(s.sample_type), s.sample_no)] = deepcopy(s)

    async def get_samples(self, samples):
        keys = [(str(s.sample_type), s.sample_no) for s in samples]
        return [deepcopy(self.rows[k]) for k in keys if k in self.rows]

    async def new_samples(self, samples):
        out = []
        for s in samples:
            s = deepcopy(s)
            self.n += 1
            s.sample_no, s.machine_name = self.n, "host"
            s.global_label = s.get_global_label()
            self.rows[(str(s.sample_type), s.sample_no)] = deepcopy(s)
            self.created.append(s)
            out.append(s)
        return out

    async def update_samples(self, samples):
        return None


def _sample(kind, no, vol):
    s = KIND[kind](sample_no=no, machine_name="host", volume_ml=vol)
    s.global_label = s.get_global_label()
    return s


def _archive(kind, loaded):
    source = _sample(kind, 1511, 100.0)
    db = _DB(source, loaded)
    archive = object.__new__(Archive)
    archive.unified_db = db  # type: ignore
    archive.archivejson = None
    archive.write_config = lambda: None  # type: ignore
    cell = Custom(custom_name="cell1_we", custom_type=CustomTypes.cell, sample=loaded)
    archive.positions = SimpleNamespace(customs_dict={"cell1_we": cell})  # type: ignore
    return archive, db, source


def _add(archive, kind, source, combine):
    if kind == "liquid":
        call = archive.custom_add_liquid(
            custom="cell1_we",
            source_liquid_in=source,
            volume_ml=1.0,
            combine_liquids=combine,
            action=ACTION,
        )
    else:
        call = archive.custom_add_gas(
            custom="cell1_we",
            source_gas_in=source,
            volume_ml=1.0,
            combine_gases=combine,
            action=ACTION,
        )
    return asyncio.run(call)


@pytest.mark.parametrize("kind", ["liquid", "gas"])
def test_add_onto_same_kind_without_combine_builds_assembly(kind):
    archive, _, source = _archive(kind, _sample(kind, 40, 3.0))
    error, _, samples_out = _add(archive, kind, source, combine=False)
    assert error == ErrorCodes.none
    cell = archive.positions.customs_dict["cell1_we"].sample
    assert cell is not None
    assert cell.sample_type == SampleType.assembly
    assert sorted(p.sample_type for p in cell.parts) == [kind, kind]
    assert samples_out[-1].sample_type == SampleType.assembly


@pytest.mark.parametrize("kind", ["liquid", "gas"])
def test_add_onto_same_kind_with_combine_merges(kind):
    archive, db, source = _archive(kind, _sample(kind, 40, 3.0))
    error, _, samples_out = _add(archive, kind, source, combine=True)
    assert error == ErrorCodes.none
    cell = archive.positions.customs_dict["cell1_we"].sample
    assert cell is not None
    assert cell.sample_type == kind and cell.volume_ml == 4.0
    # the transferred portion and the merged sample; no orphan assembly row
    assert [s.sample_type for s in db.created] == [kind, kind]


@pytest.mark.parametrize(
    "kind,flag", [("liquid", "combine_liquids"), ("gas", "combine_gases")]
)
def test_new_ref_samples_combine_returns_one_sample(kind, flag):
    archive, _, _ = _archive(kind, _sample(kind, 40, 3.0))
    error, refs = asyncio.run(
        archive.new_ref_samples(
            samples_in=[_sample(kind, 40, 3.0), _sample(kind, 41, 1.0)],
            sample_out_type=SampleType.assembly,
            sample_position="cell1_we",
            action=ACTION,  # type: ignore
            **{flag: True},
        )
    )
    assert error == ErrorCodes.none
    assert [s.sample_type for s in refs] == [kind]
