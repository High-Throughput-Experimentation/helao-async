"""Unit tests for `helao.hexagon.domain.pal_reconciliation.PalReconciliation`
(P3a-PAL slice 3a source resolution + slice 3b dest resolution/cam-table
assembly/`plan()`).

Pattern: fake `SampleStatePort` + plain pydantic model construction, no
Base/server/vendor fixtures needed (mirrors `test_motion_transform.py` /
`test_calibration_store.py` -- Base-free domain service, Linux-unit-testable).
`pytest-asyncio` is not installed in this env (confirmed: pre-existing
`test_native_data_sink.py`'s `@pytest.mark.asyncio` tests fail to collect
here), so async bodies are driven via `asyncio.run(...)` from plain
`def test_*` wrappers -- the `test_fakes.py` pattern.
"""

import asyncio
import itertools
from typing import Any, Dict

from helao.hexagon.domain.models import (
    AssemblySample,
    ErrorCodes,
    LiquidSample,
    GasSample,
    NoneSample,
    PalCam,
    PalMicroCam,
    PALposition,
    SampleStatus,
    SampleType,
    _cam,
    _positiontype,
)
from helao.hexagon.domain.pal_reconciliation import PalReconciliation
from helao.hexagon.ports.sample_state import SampleStatePort


class FakeSampleState:
    """In-memory `SampleStatePort` fake covering the full surface
    `_check_source*`/`_check_dest*`/`_next_full_vial`/`plan()` call."""

    def __init__(self):
        self.tray_db = {}
        self.custom_db = {}
        self.tray_query_calls = []
        self.custom_query_calls = []
        self.new_ref_samples_calls = []
        # (tray, slot, vial) / custom-position keys whose query should
        # report a lookup error (simulates "requested position does not
        # exist")
        self.tray_error_positions = set()
        self.custom_error_positions = set()
        self.custom_dest_allowed_set = set()
        self.custom_assembly_allowed_set = set()
        self.custom_destroyed_set = set()
        self._ref_counter = itertools.count(1)
        self._tray_pos_counter = itertools.count(1)

    def seed_tray(self, tray, slot, vial, sample):
        self.tray_db[(tray, slot, vial)] = sample

    def seed_custom(self, position, sample):
        self.custom_db[position] = sample

    def allow_dest(self, position):
        self.custom_dest_allowed_set.add(position)

    def allow_assembly(self, position):
        self.custom_assembly_allowed_set.add(position)

    def mark_destroyed(self, position):
        self.custom_destroyed_set.add(position)

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
        vial = next(self._tray_pos_counter)
        return {"tray": 1, "slot": 1, "vial": vial}

    async def tray_update_position(
        self, tray=None, slot=None, vial=None, sample=None, dilute=False
    ):
        raise NotImplementedError("not exercised until slice 3c/3d")

    async def custom_query_sample(self, custom=None):
        self.custom_query_calls.append(custom)
        if custom in self.custom_error_positions:
            return ErrorCodes.not_available, NoneSample()
        sample = self.custom_db.get(custom)
        if sample is None:
            return ErrorCodes.none, NoneSample()
        return ErrorCodes.none, sample

    async def custom_update_position(self, custom=None, sample=None, dilute=False):
        raise NotImplementedError("not exercised until slice 3c/3d")

    async def custom_dest_allowed(self, custom=None):
        return custom in self.custom_dest_allowed_set

    async def custom_assembly_allowed(self, custom=None):
        return custom in self.custom_assembly_allowed_set

    async def custom_is_destroyed(self, custom=None):
        return custom in self.custom_destroyed_set

    async def new_ref_samples(
        self,
        samples_in=None,
        sample_out_type: Any = "",
        sample_position="",
        action=None,
        combine_liquids=False,
        combine_gases=False,
    ):
        self.new_ref_samples_calls.append(
            {"sample_out_type": sample_out_type, "sample_position": sample_position}
        )
        n = next(self._ref_counter)
        cls = {
            SampleType.liquid: LiquidSample,
            SampleType.gas: GasSample,
        }.get(sample_out_type, LiquidSample)
        ref = cls(sample_no=f"ref-{n}", sample_position=sample_position)
        return ErrorCodes.none, [ref]

    async def get_samples(self, samples=None):
        raise NotImplementedError("not exercised until slice 3c")

    async def new_samples(self, samples=None):
        raise NotImplementedError("not exercised until slice 3c")

    async def update_samples(self, samples=None):
        raise NotImplementedError("not exercised until slice 3c")


def _liquid(label, volume_ml=1.0):
    return LiquidSample(
        global_label=label,
        sample_no=label,
        volume_ml=volume_ml,
        status=[SampleStatus.preserved],
        machine_name="test",
    )


def _microcam(
    source_kind,
    tray=None,
    slot=None,
    vial=None,
    position=None,
    dest_kind=_positiontype.custom,
    dest_tray=None,
    dest_slot=None,
    dest_vial=None,
    dest_position=None,
    sample_out_type=SampleType.liquid,
):
    return PalMicroCam(
        method="transfer_custom_custom",
        tool="LS1",
        volume_ul=100,
        requested_source=PALposition(
            position=position, tray=tray, slot=slot, vial=vial
        ),
        requested_dest=PALposition(
            position=dest_position, tray=dest_tray, slot=dest_slot, vial=dest_vial
        ),
        cam=_cam(source=source_kind, dest=dest_kind, sample_out_type=sample_out_type),
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


# ---------------------------------------------------------------------------
# slice 3b: dest resolution + cam-table assembly / plan()
# ---------------------------------------------------------------------------


def test_check_dest_custom_creates_new_ref_sample_when_empty():
    async def _run():
        state = FakeSampleState()
        state.seed_custom("src", _liquid("src_liq"))
        state.allow_dest("dst")
        recon = PalReconciliation(sample_state=state, cams=None)
        microcam = _microcam(
            _positiontype.custom,
            position="src",
            dest_kind=_positiontype.custom,
            dest_position="dst",
        )

        assert await recon._check_source(microcam) is ErrorCodes.none
        err = await recon._check_dest(microcam, action=None)

        assert err is ErrorCodes.none
        run = microcam.run[0]
        assert run.dest is not None
        assert run.dest.position == "dst"
        assert len(run.samples_out) == 1
        assert run.samples_out[0].sample_type == SampleType.liquid
        assert state.new_ref_samples_calls == [
            {"sample_out_type": SampleType.liquid, "sample_position": "dst"}
        ]

    asyncio.run(_run())


def test_check_dest_custom_dilutes_same_type():
    async def _run():
        state = FakeSampleState()
        state.seed_custom("src", _liquid("src_liq"))
        state.seed_custom("dst", _liquid("dst_liq_existing"))
        state.allow_dest("dst")
        recon = PalReconciliation(sample_state=state, cams=None)
        microcam = _microcam(
            _positiontype.custom,
            position="src",
            dest_kind=_positiontype.custom,
            dest_position="dst",
        )

        assert await recon._check_source(microcam) is ErrorCodes.none
        err = await recon._check_dest(microcam, action=None)

        assert err is ErrorCodes.none
        run = microcam.run[0]
        # diluting: no NEW ref sample created, existing dest sample folded
        # into samples_in instead
        assert state.new_ref_samples_calls == []
        assert run.samples_out == []
        assert any(s.global_label == "dst_liq_existing" for s in run.samples_in)
        assert run.dilute[-1] is True

    asyncio.run(_run())


def test_check_dest_custom_creates_assembly_when_types_differ_and_allowed():
    async def _run():
        state = FakeSampleState()
        state.seed_custom("src", _liquid("src_liq"))
        state.seed_custom("dst", GasSample(sample_no="dst_gas", sample_position="dst"))
        state.allow_dest("dst")
        state.allow_assembly("dst")
        recon = PalReconciliation(sample_state=state, cams=None)
        microcam = _microcam(
            _positiontype.custom,
            position="src",
            dest_kind=_positiontype.custom,
            dest_position="dst",
        )

        assert await recon._check_source(microcam) is ErrorCodes.none
        err = await recon._check_dest(microcam, action=None)

        assert err is ErrorCodes.none
        # two new_ref_samples calls: the new liquid ref, then the assembly
        assert len(state.new_ref_samples_calls) == 2
        assert state.new_ref_samples_calls[1]["sample_out_type"] == SampleType.assembly

    asyncio.run(_run())


def test_check_dest_custom_rejects_when_assembly_not_allowed():
    async def _run():
        state = FakeSampleState()
        state.seed_custom("src", _liquid("src_liq"))
        state.seed_custom("dst", GasSample(sample_no="dst_gas", sample_position="dst"))
        state.allow_dest("dst")
        # deliberately NOT allow_assembly("dst")
        recon = PalReconciliation(sample_state=state, cams=None)
        microcam = _microcam(
            _positiontype.custom,
            position="src",
            dest_kind=_positiontype.custom,
            dest_position="dst",
        )

        assert await recon._check_source(microcam) is ErrorCodes.none
        err = await recon._check_dest(microcam, action=None)

        assert err is ErrorCodes.not_allowed

    asyncio.run(_run())


def test_check_dest_custom_rejects_none_dest():
    async def _run():
        state = FakeSampleState()
        recon = PalReconciliation(sample_state=state, cams=None)
        # dest resolution reads microcam.run[-1], so a source must exist
        state.seed_custom("src", _liquid("src_liq"))
        microcam = _microcam(
            _positiontype.custom,
            position="src",
            dest_kind=_positiontype.custom,
            dest_position=None,
        )

        assert await recon._check_source(microcam) is ErrorCodes.none
        err = await recon._check_dest(microcam, action=None)

        assert err is ErrorCodes.critical_error

    asyncio.run(_run())


def test_check_dest_custom_rejects_when_not_dest_allowed():
    async def _run():
        state = FakeSampleState()
        state.seed_custom("src", _liquid("src_liq"))
        # deliberately NOT allow_dest("dst")
        recon = PalReconciliation(sample_state=state, cams=None)
        microcam = _microcam(
            _positiontype.custom,
            position="src",
            dest_kind=_positiontype.custom,
            dest_position="dst",
        )

        assert await recon._check_source(microcam) is ErrorCodes.none
        err = await recon._check_dest(microcam, action=None)

        assert err is ErrorCodes.critical_error

    asyncio.run(_run())


def test_check_dest_tray_creates_new_ref_sample_when_empty():
    async def _run():
        state = FakeSampleState()
        state.seed_custom("src", _liquid("src_liq"))
        recon = PalReconciliation(sample_state=state, cams=None)
        microcam = _microcam(
            _positiontype.custom,
            position="src",
            dest_kind=_positiontype.tray,
            dest_tray=1,
            dest_slot=1,
            dest_vial=1,
        )

        assert await recon._check_source(microcam) is ErrorCodes.none
        err = await recon._check_dest(microcam, action=None)

        assert err is ErrorCodes.none
        run = microcam.run[0]
        assert len(run.samples_out) == 1
        assert state.new_ref_samples_calls

    asyncio.run(_run())


def test_check_dest_tray_dilutes_when_occupied():
    async def _run():
        state = FakeSampleState()
        state.seed_custom("src", _liquid("src_liq"))
        state.seed_tray(1, 1, 1, _liquid("tray_liq_existing"))
        recon = PalReconciliation(sample_state=state, cams=None)
        microcam = _microcam(
            _positiontype.custom,
            position="src",
            dest_kind=_positiontype.tray,
            dest_tray=1,
            dest_slot=1,
            dest_vial=1,
        )

        assert await recon._check_source(microcam) is ErrorCodes.none
        err = await recon._check_dest(microcam, action=None)

        assert err is ErrorCodes.none
        assert state.new_ref_samples_calls == []
        run = microcam.run[0]
        assert any(s.global_label == "tray_liq_existing" for s in run.samples_in)

    asyncio.run(_run())


def test_check_dest_next_empty_creates_ref_sample():
    async def _run():
        state = FakeSampleState()
        state.seed_custom("src", _liquid("src_liq"))
        recon = PalReconciliation(sample_state=state, cams=None)
        microcam = _microcam(
            _positiontype.custom,
            position="src",
            dest_kind=_positiontype.next_empty_vial,
        )

        assert await recon._check_source(microcam) is ErrorCodes.none
        err = await recon._check_dest(microcam, action=None)

        assert err is ErrorCodes.none
        run = microcam.run[0]
        assert run.dest is not None
        assert run.dest.tray == 1  # FakeSampleState.tray_new_position stub
        assert len(run.samples_out) == 1

    asyncio.run(_run())


def test_check_dest_marks_destroyed_when_custom_is_destroyed():
    async def _run():
        state = FakeSampleState()
        state.seed_custom("src", _liquid("src_liq"))
        state.allow_dest("waste")
        state.mark_destroyed("waste")
        recon = PalReconciliation(sample_state=state, cams=None)
        microcam = _microcam(
            _positiontype.custom,
            position="src",
            dest_kind=_positiontype.custom,
            dest_position="waste",
        )

        assert await recon._check_source(microcam) is ErrorCodes.none
        err = await recon._check_dest(microcam, action=None)

        assert err is ErrorCodes.none
        run = microcam.run[0]
        assert SampleStatus.destroyed in run.samples_out[0].status

    asyncio.run(_run())


def test_check_for_assemblytypes():
    async def _run():
        state = FakeSampleState()
        recon = PalReconciliation(sample_state=state, cams=None)
        assembly = AssemblySample(sample_no="a1", parts=[_liquid("part_liq")])

        assert await recon._check_for_assemblytypes(SampleType.liquid, assembly)
        assert not await recon._check_for_assemblytypes(SampleType.gas, assembly)

    asyncio.run(_run())


class _FakeCamEnumMember:
    def __init__(self, name: str, value):
        self.name = name
        self.value = value


class _FakeCamsTable:
    """Duck-typed stand-in for the `CAMS` Enum: iterable of members with
    `.name` + `.value` (a `_cam`), and subscriptable by method name."""

    def __init__(self, methods: Dict[str, Any]):
        self._members = {
            name: _FakeCamEnumMember(name, cam) for name, cam in methods.items()
        }

    def __iter__(self):
        return iter(self._members.values())

    def __getitem__(self, key):
        return self._members[key]


def _fake_cams_table(methods: Dict[str, Any]) -> _FakeCamsTable:
    return _FakeCamsTable(methods)


def test_plan_resolves_full_microcam_list():
    async def _run():
        state = FakeSampleState()
        state.seed_custom("src", _liquid("src_liq"))
        state.allow_dest("dst")
        cam_template = _cam(
            name="transfer_custom_custom",
            file_name="transfer.cam",
            file_path="/dummy",
            sample_out_type=SampleType.liquid,
            source=_positiontype.custom,
            dest=_positiontype.custom,
        )
        cams = _fake_cams_table({"transfer_custom_custom": cam_template})
        recon = PalReconciliation(sample_state=state, cams=cams)

        palcam = PalCam(
            microcams=[
                PalMicroCam(
                    method="transfer_custom_custom",
                    tool="LS1",
                    volume_ul=100,
                    requested_source=PALposition(position="src"),
                    requested_dest=PALposition(position="dst"),
                )
            ]
        )

        err = await recon.plan(palcam, action_uuid=None, action=None)

        assert err is ErrorCodes.none
        microcam = palcam.microcams[0]
        assert microcam.cam.file_name == "transfer.cam"
        assert len(microcam.run) == 1
        assert microcam.run[0].dest is not None
        assert microcam.run[0].dest.position == "dst"

    asyncio.run(_run())


def test_plan_unknown_method_is_not_available():
    async def _run():
        state = FakeSampleState()
        cams = _fake_cams_table({})
        recon = PalReconciliation(sample_state=state, cams=cams)
        palcam = PalCam(
            microcams=[
                PalMicroCam(method="no_such_method", requested_source=PALposition())
            ]
        )

        err = await recon.plan(palcam, action_uuid=None, action=None)

        assert err is ErrorCodes.not_available

    asyncio.run(_run())
