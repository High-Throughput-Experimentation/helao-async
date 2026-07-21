"""Unit tests for `helao.hexagon.domain.pal_reconciliation.PalReconciliation`
(P3a-PAL slice 3a: source-position resolution only).

Pattern: fake `SampleStatePort` + plain pydantic model construction, no
Base/server/vendor fixtures needed (mirrors `test_motion_transform.py` /
`test_calibration_store.py` -- Base-free domain service, Linux-unit-testable).
`pytest-asyncio` is not installed in this env (confirmed: pre-existing
`test_native_data_sink.py`'s `@pytest.mark.asyncio` tests fail to collect
here), so async bodies are driven via `asyncio.run(...)` from plain
`def test_*` wrappers -- the `test_fakes.py` pattern.
"""

import asyncio

from helao.hexagon.domain.models import (
    ErrorCodes,
    LiquidSample,
    NoneSample,
    PalMicroCam,
    PALposition,
    SampleStatus,
    _cam,
    _positiontype,
)
from helao.hexagon.domain.pal_reconciliation import PalReconciliation
from helao.hexagon.ports.sample_state import SampleStatePort


class FakeSampleState:
    """Minimal in-memory `SampleStatePort` fake: tray/custom dicts only (the
    surface `_check_source*`/`_next_full_vial` actually call)."""

    def __init__(self):
        self.tray_db = {}
        self.custom_db = {}
        self.tray_query_calls = []
        self.custom_query_calls = []
        # (tray, slot, vial) keys whose query should report a lookup error
        # (simulates "requested tray position does not exist")
        self.tray_error_positions = set()
        self.custom_error_positions = set()

    def seed_tray(self, tray, slot, vial, sample):
        self.tray_db[(tray, slot, vial)] = sample

    def seed_custom(self, position, sample):
        self.custom_db[position] = sample

    async def tray_query_sample(self, tray=None, slot=None, vial=None):
        self.tray_query_calls.append((tray, slot, vial))
        if (tray, slot, vial) in self.tray_error_positions:
            return ErrorCodes.not_available, NoneSample()
        sample = self.tray_db.get((tray, slot, vial))
        if sample is None:
            return ErrorCodes.none, NoneSample()
        return ErrorCodes.none, sample

    async def tray_get_next_full(
        self, after_tray=None, after_slot=None, after_vial=None
    ):
        for (t, s, v), sample in sorted(self.tray_db.items()):
            if (t, s, v) > (after_tray or 0, after_slot or 0, after_vial or 0):
                return {"tray": t, "slot": s, "vial": v}
        return {"tray": None, "slot": None, "vial": None}

    async def tray_new_position(self, req_vol=2.0):
        raise NotImplementedError("not exercised by slice-3a source tests")

    async def tray_update_position(
        self, tray=None, slot=None, vial=None, sample=None, dilute=False
    ):
        raise NotImplementedError("not exercised by slice-3a source tests")

    async def custom_query_sample(self, custom=None):
        self.custom_query_calls.append(custom)
        if custom in self.custom_error_positions:
            return ErrorCodes.not_available, NoneSample()
        sample = self.custom_db.get(custom)
        if sample is None:
            return ErrorCodes.none, NoneSample()
        return ErrorCodes.none, sample

    async def custom_update_position(self, custom=None, sample=None, dilute=False):
        raise NotImplementedError("not exercised by slice-3a source tests")

    async def custom_dest_allowed(self, custom=None):
        raise NotImplementedError("not exercised by slice-3a source tests")

    async def custom_assembly_allowed(self, custom=None):
        raise NotImplementedError("not exercised by slice-3a source tests")

    async def custom_is_destroyed(self, custom=None):
        raise NotImplementedError("not exercised by slice-3a source tests")

    async def new_ref_samples(
        self,
        samples_in=None,
        sample_out_type="",
        sample_position="",
        action=None,
        combine_liquids=False,
        combine_gases=False,
    ):
        raise NotImplementedError("not exercised by slice-3a source tests")

    async def get_samples(self, samples=None):
        raise NotImplementedError("not exercised by slice-3a source tests")

    async def new_samples(self, samples=None):
        raise NotImplementedError("not exercised by slice-3a source tests")

    async def update_samples(self, samples=None):
        raise NotImplementedError("not exercised by slice-3a source tests")


def _liquid(label, volume_ml=1.0):
    return LiquidSample(
        global_label=label,
        sample_no=label,
        volume_ml=volume_ml,
        status=[SampleStatus.preserved],
        machine_name="test",
    )


def _microcam(source_kind, tray=None, slot=None, vial=None, position=None):
    return PalMicroCam(
        method="transfer_custom_custom",
        tool="LS1",
        volume_ul=100,
        requested_source=PALposition(
            position=position, tray=tray, slot=slot, vial=vial
        ),
        cam=_cam(source=source_kind, dest=_positiontype.custom),
    )


def test_is_sample_state_port_fake():
    # fakes SampleStatePort structurally -- confirms the fake matches the
    # port's runtime_checkable surface used elsewhere in the test suite.
    assert isinstance(FakeSampleState(), SampleStatePort)


def test_check_source_tray_found():
    async def _run():
        state = FakeSampleState()
        state.seed_tray(1, 2, 3, _liquid("liq_a"))
        recon = PalReconciliation(sample_state=state, cams=None)
        microcam = _microcam(_positiontype.tray, tray=1, slot=2, vial=3)

        err = await recon._check_source(microcam)

        assert err is ErrorCodes.none
        assert microcam.requested_source.tray == 1
        assert microcam.requested_source.slot == 2
        assert microcam.requested_source.vial == 3
        assert len(microcam.run) == 1
        run = microcam.run[0]
        assert run.samples_in[0].global_label == "liq_a"
        assert run.source is not None
        assert run.source.position == _positiontype.tray
        assert run.dilute == [False]
        assert run.samples_in_delta_vol_ml == [-0.1]
        # source resolution clears inheritance/status pending dest decision
        assert run.samples_in[0].inheritance is None

    asyncio.run(_run())


def test_check_source_tray_no_sample_is_not_available():
    async def _run():
        state = FakeSampleState()  # empty tray_db
        recon = PalReconciliation(sample_state=state, cams=None)
        microcam = _microcam(_positiontype.tray, tray=9, slot=9, vial=9)

        err = await recon._check_source(microcam)

        assert err is ErrorCodes.not_available
        assert microcam.run == []  # dispatcher returns early, no run appended

    asyncio.run(_run())


def test_check_source_tray_missing_position_is_critical_error():
    async def _run():
        state = FakeSampleState()
        state.tray_error_positions.add((5, 5, 5))
        recon = PalReconciliation(sample_state=state, cams=None)
        microcam = _microcam(_positiontype.tray, tray=5, slot=5, vial=5)

        err = await recon._check_source(microcam)

        assert err is ErrorCodes.critical_error

    asyncio.run(_run())


def test_check_source_custom_found():
    async def _run():
        state = FakeSampleState()
        state.seed_custom("cell1_we", _liquid("liq_b", volume_ml=3.0))
        recon = PalReconciliation(sample_state=state, cams=None)
        microcam = _microcam(_positiontype.custom, position="cell1_we")

        err = await recon._check_source(microcam)

        assert err is ErrorCodes.none
        assert len(microcam.run) == 1
        assert microcam.run[0].samples_in[0].global_label == "liq_b"
        run_source = microcam.run[0].source
        assert run_source is not None
        assert run_source.position == "cell1_we"

    asyncio.run(_run())


def test_check_source_custom_none_position_is_not_available():
    async def _run():
        state = FakeSampleState()
        recon = PalReconciliation(sample_state=state, cams=None)
        microcam = _microcam(_positiontype.custom, position=None)

        err = await recon._check_source(microcam)

        assert err is ErrorCodes.not_available
        assert state.custom_query_calls == []  # rejected before any query

    asyncio.run(_run())


def test_check_source_next_empty_always_rejected():
    async def _run():
        state = FakeSampleState()
        recon = PalReconciliation(sample_state=state, cams=None)
        microcam = _microcam(_positiontype.next_empty_vial)

        err = await recon._check_source(microcam)

        assert err is ErrorCodes.not_available

    asyncio.run(_run())


def test_check_source_next_full_vial_dispatch_preserves_legacy_bug():
    """Pre-existing shipped-driver bug (documented in pal_reconciliation.py):
    the `next_full_vial` dispatch branch calls the next_EMPTY checker, not
    `_check_source_next_full`/`_next_full_vial` -- so it always rejects,
    even when a full vial is seeded. Preserved verbatim; this test locks
    that (mis-)behavior in place so a future fix is a deliberate, visible
    diff rather than an accidental one."""

    async def _run():
        state = FakeSampleState()
        state.seed_tray(1, 1, 1, _liquid("liq_c"))
        recon = PalReconciliation(sample_state=state, cams=None)
        microcam = _microcam(_positiontype.next_full_vial, tray=0, slot=0, vial=0)

        err = await recon._check_source(microcam)

        assert err is ErrorCodes.not_available
        # the real _next_full_vial path (below) would have found the seeded
        # vial -- proving the dispatcher truly never reaches it.
        (
            direct_err,
            tray,
            slot,
            vial,
            sample,
        ) = await recon._next_full_vial(after_tray=0, after_slot=0, after_vial=0)
        assert direct_err is ErrorCodes.none
        assert (tray, slot, vial) == (1, 1, 1)
        assert sample.global_label == "liq_c"

    asyncio.run(_run())


def test_next_full_vial_finds_seeded_vial():
    async def _run():
        state = FakeSampleState()
        state.seed_tray(2, 1, 1, _liquid("liq_d"))
        recon = PalReconciliation(sample_state=state, cams=None)

        err, tray, slot, vial, sample = await recon._next_full_vial(
            after_tray=1, after_slot=0, after_vial=0
        )

        assert err is ErrorCodes.none
        assert (tray, slot, vial) == (2, 1, 1)
        assert sample.global_label == "liq_d"

    asyncio.run(_run())


def test_next_full_vial_none_args_is_not_available():
    async def _run():
        state = FakeSampleState()
        recon = PalReconciliation(sample_state=state, cams=None)

        err, tray, slot, vial, sample = await recon._next_full_vial(
            after_tray=None,  # type: ignore[reportArgumentType]  # deliberately
            # exercising the method's own `if after_tray is None` guard; the
            # legacy signature types this `int` (not `Optional[int]`) despite
            # handling None at runtime -- preserved verbatim, not this
            # slice's concern to fix.
            after_slot=0,
            after_vial=0,
        )

        assert err is ErrorCodes.not_available
        assert tray is None and slot is None and vial is None
        assert isinstance(sample, NoneSample)

    asyncio.run(_run())


def test_next_full_vial_no_more_vials_is_not_available():
    async def _run():
        state = FakeSampleState()  # empty
        recon = PalReconciliation(sample_state=state, cams=None)

        err, tray, slot, vial, sample = await recon._next_full_vial(
            after_tray=0, after_slot=0, after_vial=0
        )

        assert err is ErrorCodes.not_available

    asyncio.run(_run())
