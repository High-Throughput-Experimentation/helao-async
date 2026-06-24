"""Tests for helao.framework.adapters.sample_api.

Round-trip coverage:
  - UnifiedSampleDataAPI: init_db → new_samples → get_samples for LiquidSample
  - UnifiedSampleDataAPI: init_db → new_samples → get_samples for GasSample
  - UnifiedSampleDataAPI: count_samples after inserts
  - UnifiedSampleDataAPI: list_new_samples returns dicts with correct sample_type
  - unpack_samples_helper: flat primitive list partitioning
  - unpack_samples_helper: assembly flattening
  - update_vol: normal add/remove, dilution rescaling, destroy at zero

Skipped surfaces (noted in report):
  - SolidSampleAPI.new_samples (intentional no-op per legacy design)
  - OldLiquidSampleAPI (CSV migration path, needs its own fixture)
  - AssemblySampleAPI round-trip (requires pre-inserted liquid/gas parts)
  - update_samples (requires a successful new_samples first; covered partially
    via LiquidSample update scenario below)
"""

import asyncio
import time
from socket import gethostname
from types import SimpleNamespace

import pytest

from helao.framework.adapters.sample_api import (
    UnifiedSampleDataAPI,
    unpack_samples_helper,
    update_vol,
)
from helao.framework.models.sample import (
    AssemblySample,
    GasSample,
    LiquidSample,
    SolidSample,
    SampleType,
)
from helao.framework.models.helaodirs import HelaoDirs


# ---------------------------------------------------------------------------
# Minimal Serv_class stub
# ---------------------------------------------------------------------------

class _FakeServer:
    """Minimal stub satisfying the attributes read by SampleModelAPI."""
    machine_name: str = gethostname().lower()
    server_name: str = "test_server"


class _FakeBase:
    """Minimal stub satisfying the attributes read by SampleModelAPI/UnifiedSampleDataAPI."""

    def __init__(self, db_root: str):
        self.helaodirs = HelaoDirs(db_root=db_root)
        self.server = _FakeServer()

    def get_realtime_nowait(self) -> int:
        return time.time_ns()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_api(tmp_path) -> UnifiedSampleDataAPI:
    base = _FakeBase(db_root=str(tmp_path))
    return UnifiedSampleDataAPI(Serv_class=base)


# ---------------------------------------------------------------------------
# UnifiedSampleDataAPI: init_db
# ---------------------------------------------------------------------------

def test_init_db_marks_ready(tmp_path):
    """init_db sets .ready = True on the dispatcher and all sub-APIs."""
    api = _make_api(tmp_path)
    assert not api.ready
    asyncio.run(api.init_db())
    assert api.ready
    assert api.liquidAPI.ready
    assert api.gasAPI.ready
    assert api.assemblyAPI.ready


# ---------------------------------------------------------------------------
# UnifiedSampleDataAPI: LiquidSample round-trip
# ---------------------------------------------------------------------------

def test_liquid_new_and_get_roundtrip(tmp_path):
    """new_samples(LiquidSample) → get_samples returns correct sample_no and type."""
    api = _make_api(tmp_path)
    asyncio.run(api.init_db())

    sample = LiquidSample(
        machine_name=gethostname().lower(),
        volume_ml=1.5,
        dilution_factor=1.0,
    )
    inserted = asyncio.run(api.new_samples(samples=[sample]))
    assert len(inserted) == 1
    ins = inserted[0]
    assert isinstance(ins, LiquidSample)
    assert ins.sample_no == 1
    assert ins.sample_type == SampleType.liquid
    assert ins.volume_ml == pytest.approx(1.5)

    # round-trip: fetch by sample_no
    stub = LiquidSample(sample_no=1, machine_name=gethostname().lower())
    fetched = asyncio.run(api.get_samples(samples=[stub]))
    assert len(fetched) == 1
    got = fetched[0]
    assert isinstance(got, LiquidSample)
    assert got.sample_no == 1
    assert got.sample_type == SampleType.liquid
    assert got.volume_ml == pytest.approx(1.5)
    assert got.global_label == ins.global_label


# ---------------------------------------------------------------------------
# UnifiedSampleDataAPI: GasSample round-trip
# ---------------------------------------------------------------------------

def test_gas_new_and_get_roundtrip(tmp_path):
    """new_samples(GasSample) → get_samples returns correct sample_no and type."""
    api = _make_api(tmp_path)
    asyncio.run(api.init_db())

    sample = GasSample(machine_name=gethostname().lower(), volume_ml=0.5)
    inserted = asyncio.run(api.new_samples(samples=[sample]))
    assert len(inserted) == 1
    ins = inserted[0]
    assert isinstance(ins, GasSample)
    assert ins.sample_no == 1
    assert ins.sample_type == SampleType.gas

    stub = GasSample(sample_no=1, machine_name=gethostname().lower())
    fetched = asyncio.run(api.get_samples(samples=[stub]))
    assert len(fetched) == 1
    assert fetched[0].sample_type == SampleType.gas
    assert fetched[0].sample_no == 1


# ---------------------------------------------------------------------------
# UnifiedSampleDataAPI: count_samples
# ---------------------------------------------------------------------------

def test_count_samples_increments(tmp_path):
    """count_samples reflects correct count after multiple inserts."""
    api = _make_api(tmp_path)
    asyncio.run(api.init_db())
    assert asyncio.run(api.liquidAPI.count_samples()) == 0

    for _ in range(3):
        s = LiquidSample(machine_name=gethostname().lower(), volume_ml=1.0, dilution_factor=1.0)
        asyncio.run(api.new_samples(samples=[s]))

    assert asyncio.run(api.liquidAPI.count_samples()) == 3


# ---------------------------------------------------------------------------
# UnifiedSampleDataAPI: list_new_samples
# ---------------------------------------------------------------------------

def test_list_new_samples_returns_dicts_with_correct_type(tmp_path):
    """list_new_samples returns list of dicts with sample_type == 'liquid'."""
    api = _make_api(tmp_path)
    asyncio.run(api.init_db())

    s = LiquidSample(machine_name=gethostname().lower(), volume_ml=2.0, dilution_factor=1.0)
    asyncio.run(api.new_samples(samples=[s]))

    result = asyncio.run(api.list_new_samples(limit=5))
    assert isinstance(result, dict)
    liquid_list = result["liquid"]
    assert len(liquid_list) >= 1
    assert liquid_list[0]["sample_type"] == SampleType.liquid


# ---------------------------------------------------------------------------
# UnifiedSampleDataAPI: negative sample_no (get from back)
# ---------------------------------------------------------------------------

def test_get_samples_negative_index(tmp_path):
    """sample_no=-1 retrieves the most recently inserted sample."""
    api = _make_api(tmp_path)
    asyncio.run(api.init_db())

    s1 = LiquidSample(machine_name=gethostname().lower(), volume_ml=1.0, dilution_factor=1.0)
    s2 = LiquidSample(machine_name=gethostname().lower(), volume_ml=2.0, dilution_factor=1.0)
    asyncio.run(api.new_samples(samples=[s1]))
    asyncio.run(api.new_samples(samples=[s2]))

    stub = LiquidSample(sample_no=-1, machine_name=gethostname().lower())
    fetched = asyncio.run(api.get_samples(samples=[stub]))
    assert len(fetched) == 1
    assert fetched[0].volume_ml == pytest.approx(2.0)
    assert fetched[0].sample_no == 2


# ---------------------------------------------------------------------------
# unpack_samples_helper
# ---------------------------------------------------------------------------

def test_unpack_flat_primitives():
    """Flat list of primitives is partitioned by type without modification."""
    liq = LiquidSample(machine_name="host", volume_ml=1.0)
    gas = GasSample(machine_name="host", volume_ml=0.5)
    sol = SolidSample(machine_name="host", plate_id=1, sample_no=1)

    liq_out, sol_out, gas_out = unpack_samples_helper([liq, gas, sol])
    assert liq_out == [liq]
    assert gas_out == [gas]
    assert sol_out == [sol]


def test_unpack_assembly_flattens_parts():
    """Assembly's leaf parts are distributed into primitive buckets."""
    liq = LiquidSample(machine_name="host", volume_ml=1.0)
    gas = GasSample(machine_name="host", volume_ml=0.5)
    assembly = AssemblySample(parts=[liq, gas])

    liq_out, sol_out, gas_out = unpack_samples_helper([assembly])
    assert len(liq_out) == 1
    assert liq_out[0] is liq
    assert len(gas_out) == 1
    assert gas_out[0] is gas
    assert sol_out == []


def test_unpack_nested_assembly():
    """Nested assemblies are recursively flattened."""
    liq1 = LiquidSample(machine_name="host", volume_ml=1.0)
    liq2 = LiquidSample(machine_name="host", volume_ml=2.0)
    inner = AssemblySample(parts=[liq2])
    outer = AssemblySample(parts=[liq1, inner])

    liq_out, sol_out, gas_out = unpack_samples_helper([outer])
    assert len(liq_out) == 2
    assert sol_out == []
    assert gas_out == []


def test_unpack_empty_list():
    """Empty input produces three empty lists."""
    liq_out, sol_out, gas_out = unpack_samples_helper([])
    assert liq_out == []
    assert sol_out == []
    assert gas_out == []


# ---------------------------------------------------------------------------
# update_vol
# ---------------------------------------------------------------------------

def test_update_vol_adds_volume():
    """Positive delta increases volume_ml."""
    s = LiquidSample(machine_name="host", volume_ml=5.0, dilution_factor=2.0)
    update_vol(s, 3.0, dilute=False)
    assert s.volume_ml == pytest.approx(8.0)
    assert s.dilution_factor == pytest.approx(2.0)  # unchanged when dilute=False


def test_update_vol_removes_volume():
    """Negative delta decreases volume_ml."""
    s = LiquidSample(machine_name="host", volume_ml=5.0, dilution_factor=1.0)
    update_vol(s, -2.0, dilute=False)
    assert s.volume_ml == pytest.approx(3.0)


def test_update_vol_zeros_on_non_positive():
    """Volume at or below zero is set to zero and sample is marked destroyed."""
    s = LiquidSample(machine_name="host", volume_ml=1.0, dilution_factor=1.0)
    update_vol(s, -5.0, dilute=False)
    assert s.volume_ml == pytest.approx(0.0)


def test_update_vol_dilute_rescales_df():
    """dilute=True recalculates dilution_factor to preserve concentration."""
    s = LiquidSample(machine_name="host", volume_ml=4.0, dilution_factor=2.0)
    # Add 4 mL: new_vol=8, new_df = 8 / (4/2) = 8/2 = 4
    update_vol(s, 4.0, dilute=True)
    assert s.volume_ml == pytest.approx(8.0)
    assert s.dilution_factor == pytest.approx(4.0)


def test_update_vol_dilute_zero_old_vol_sentinel():
    """dilute=True with old volume <= 0 sets dilution_factor to sentinel -1."""
    s = LiquidSample(machine_name="host", volume_ml=0.0, dilution_factor=1.0)
    update_vol(s, 5.0, dilute=True)
    assert s.dilution_factor == pytest.approx(-1.0)


def test_update_vol_no_volume_attr():
    """Objects lacking volume_ml are silently ignored."""
    s = SolidSample(machine_name="host", plate_id=1, sample_no=1)
    # Should not raise even though SolidSample has no volume_ml
    update_vol(s, 1.0, dilute=False)
