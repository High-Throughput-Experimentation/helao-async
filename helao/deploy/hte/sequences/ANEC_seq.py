"""Sequence library for ANEC (Aqueous Nitrate Electrolysis Cell).

Each public ``ANEC_*`` function builds an experiment list via
``ExperimentPlanMaker``. Sequences chain cell load, electrolyte fill,
electrochemistry (OCV/CA/CV), product sampling, GC/HPLC archiving, and
cleanup sub-experiments defined in the ANEC experiment library.
"""

__all__ = [
    "ANEC_sample_ready",
    "ANEC_series_CA",
    "ANEC_series_CAliquidOnly",
    "ANEC_OCV",
    "ANEC_photo_CA",
    "ANEC_photo_CAgasonly",
    "ANEC_photo_CV",
    "ANEC_cleanup_disengage",
    "ANEC_repeat_CA",
    "ANEC_repeat_TentHeatCAgasonly",
    "ANEC_heatOCV",
    "ANEC_repeat_TentHeatCA",
    "ANEC_repeat_HeatCA",
    "ANEC_repeat_CV",
    "ANEC_CA_pretreat",
    "ANEC_CA_DOE_demo",
    "ANEC_CA_DOE_demo_headspace",
    "ANEC_gasonly_CA",
    "ANEC_ferricyanide_simpleprotocol",
    "ANEC_ferricyanide_protocol",
    "ANEC_create_and_load_liquid_sample",
    # "ANEC_create_liquid_sample",
    # "ANEC_create_liquid_tray",
    "GC_Archiveliquid_analysis",
    "HPLC_Archiveliquid_analysis",
]

from typing import List
from typing import Optional
from helao.helpers.premodels import ExperimentPlanMaker


SEQUENCES = __all__


def ANEC_sample_ready(
    sequence_version: int = 2,
    num_repeats: int = 1,
    plate_id: int = 4534,
    solid_sample_no: int = 1,
    z_move_mm: float = 3.0,
    reservoir_liquid_sample_no: int = 1511,
    volume_ul_cell_liquid: float = 1000,
    WE_potential__V: float = 0.0,
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    CA_duration_sec: float = 0.1,
    SampleRate: float = 0.01,
    IErange: str = "auto",
    ref_offset__V: float = 0.0,
    liquidDrain_time: float = 80.0,
) -> list:
    """Sample-ready sequence: startup, clean cell, then loop fill/CA/drain.

    Runs :sub:`ANEC_sub_startup` to position the cell, ``ANEC_sub_normal_state``
    plus two ``ANEC_sub_cleanup`` passes, unloads the cell, loads the solid
    sample, then repeats fill/CA/drain ``num_repeats`` times.

    Args:
        sequence_version: Sequence version tag.
        num_repeats: Number of fill/CA/drain repeats.
        plate_id: Plate id of the solid sample.
        solid_sample_no: Sample number on the plate.
        z_move_mm: Z-stage engage height (mm).
        reservoir_liquid_sample_no: Reservoir liquid sample number.
        volume_ul_cell_liquid: Cell fill volume (uL).
        WE_potential__V: CA potential in the chosen frame.
        WE_versus: Frame label (``"ref"``/``"rhe"``).
        ref_type: Reference electrode type label.
        pH: Solution pH.
        CA_duration_sec: CA hold duration (s).
        SampleRate: Sample interval (s).
        IErange: Gamry current range string.
        ref_offset__V: Reference electrode offset (V).
        liquidDrain_time: Drain duration (s).

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # move to solid sample
    epm.add(
        "ANEC_sub_startup",
        {
            "solid_plate_id": plate_id,
            "solid_sample_no": solid_sample_no,
            "z_move_mm": z_move_mm,
        },
    )

    # clean the cell & purge with CO2
    epm.add("ANEC_sub_normal_state", {})
    epm.add("ANEC_sub_cleanup", {"reservoir_liquid_sample_no": 1})
    epm.add("ANEC_sub_cleanup", {"reservoir_liquid_sample_no": 1})
    # housekeeping
    epm.add("ANEC_sub_unload_cell", {})

    # epm.add("ANEC_sub_normal_state", {})

    epm.add(
        "ANEC_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )

    for _ in range(num_repeats):

        epm.add(
            "ANEC_sub_flush_fill_cell",
            {
                "liquid_flush_time": 90,
                "co2_purge_time": 15,
                "equilibration_time": 1.0,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
            },
        )

        epm.add(
            "ANEC_sub_CA",
            {
                "WE_potential__V": WE_potential__V,
                "WE_versus": WE_versus,
                "ref_type": ref_type,
                "pH": pH,
                "ref_offset__V": ref_offset__V,
                "CA_duration_sec": CA_duration_sec,
                "SampleRate": SampleRate,
                "IErange": IErange,
            },
        )

        epm.add("ANEC_sub_drain_cell", {"drain_time": liquidDrain_time})

    return epm.planned_experiments


def ANEC_series_CA(
    sequence_version: int = 1,
    plate_id: int = 4534,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 1511,
    volume_ul_cell_liquid: float = 1000,
    WE_potential__V: List[float] = [-0.9, -1.0, -1.1, -1.2, -1.3],
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    CA_duration_sec: List[float] = [900, 900, 900, 900, 900],
    SampleRate: float = 0.01,
    IErange: str = "auto",
    ref_offset__V: float = 0.0,
    toolGC: str = "HS 2",
    toolarchive: str = "LS 3",
    volume_ul_GC: int = 300,
    volume_ul_archive: int = 500,
    liquidDrain_time: float = 80.0,
    wash1: bool = True,
    wash2: bool = True,
    wash3: bool = True,
    wash4: bool = False,
) -> list:
    """CA series at each potential in ``WE_potential__V`` with GC+archive aliquots.

    Unloads the cell, loads the solid sample, then for each
    ``(potential, duration)`` pair runs ``ANEC_sub_flush_fill_cell``,
    ``ANEC_sub_CA``, ``ANEC_sub_aliquot`` (GC + liquid archive with the
    configured wash flags) and ``ANEC_sub_drain_cell``. Concludes with
    ``ANEC_sub_alloff``.

    Args:
        sequence_version: Sequence version tag.
        plate_id: Plate id of the solid sample.
        solid_sample_no: Sample number on the plate.
        reservoir_liquid_sample_no: Reservoir liquid sample number.
        volume_ul_cell_liquid: Cell fill volume (uL).
        WE_potential__V: Per-cycle potentials in the chosen frame.
        WE_versus: Frame label (``"ref"``/``"rhe"``).
        ref_type: Reference electrode type label.
        pH: Solution pH.
        CA_duration_sec: Per-cycle CA durations (s).
        SampleRate: Sample interval (s).
        IErange: Gamry current range string.
        ref_offset__V: Reference electrode offset (V).
        toolGC: PAL tool string for the GC injection.
        toolarchive: PAL tool string for the archive injection.
        volume_ul_GC: GC injection volume (uL).
        volume_ul_archive: Archive aliquot volume (uL).
        liquidDrain_time: Drain duration (s).
        wash1: Enable wash position 1.
        wash2: Enable wash position 2.
        wash3: Enable wash position 3.
        wash4: Enable wash position 4.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add("ANEC_sub_unload_cell", {})

    # epm.add("ANEC_sub_normal_state", {})

    epm.add(
        "ANEC_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )

    for cycle, (potential, time) in enumerate(zip(WE_potential__V, CA_duration_sec)):
        print(
            f" ... cycle {cycle} potential:",
            potential,
            f" ... cycle {cycle} duration:",
            time,
        )

        epm.add(
            "ANEC_sub_flush_fill_cell",
            {
                "liquid_flush_time": 80,
                "co2_purge_time": 15,
                "equilibration_time": 1.0,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
            },
        )

        epm.add(
            "ANEC_sub_CA",
            {
                "WE_potential__V": potential,
                "WE_versus": WE_versus,
                "ref_type": ref_type,
                "pH": pH,
                "ref_offset__V": ref_offset__V,
                "CA_duration_sec": time,
                "SampleRate": SampleRate,
                "IErange": IErange,
            },
        )

        epm.add(
            "ANEC_sub_aliquot",
            {
                "toolGC": toolGC,
                "toolarchive": toolarchive,
                "volume_ul_GC": volume_ul_GC,
                "volume_ul_archive": volume_ul_archive,
                "wash1": wash1,
                "wash2": wash2,
                "wash3": wash3,
                "wash4": wash4,
            },
        )

        epm.add("ANEC_sub_drain_cell", {"drain_time": liquidDrain_time})

    epm.add("ANEC_sub_alloff", {})

    return epm.planned_experiments


def ANEC_series_CAliquidOnly(
    sequence_version: int = 1,
    plate_id: int = 4534,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 1511,
    volume_ul_cell_liquid: float = 1000,
    WE_potential__V: List[float] = [-0.9, -1.0, -1.1, -1.2, -1.3],
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    CA_duration_sec: List[float] = [900, 900, 900, 900, 900],
    SampleRate: float = 0.01,
    IErange: str = "auto",
    ref_offset__V: float = 0.0,
    toolarchive: str = "LS 3",
    volume_ul_archive: int = 500,
    liquidDrain_time: float = 80.0,
    wash1: bool = True,
    wash2: bool = True,
    wash3: bool = True,
    wash4: bool = False,
) -> list:
    """CA series with liquid-only archive aliquots (no GC).

    Same flow as :func:`ANEC_series_CA` but each cycle uses
    ``ANEC_sub_liquidarchive`` instead of the GC+archive aliquot, so no
    headspace injection is taken.

    Args:
        sequence_version: Sequence version tag.
        plate_id: Plate id of the solid sample.
        solid_sample_no: Sample number on the plate.
        reservoir_liquid_sample_no: Reservoir liquid sample number.
        volume_ul_cell_liquid: Cell fill volume (uL).
        WE_potential__V: Per-cycle potentials in the chosen frame.
        WE_versus: Frame label (``"ref"``/``"rhe"``).
        ref_type: Reference electrode type label.
        pH: Solution pH.
        CA_duration_sec: Per-cycle CA durations (s).
        SampleRate: Sample interval (s).
        IErange: Gamry current range string.
        ref_offset__V: Reference electrode offset (V).
        toolarchive: PAL tool string for the archive injection.
        volume_ul_archive: Archive aliquot volume (uL).
        liquidDrain_time: Drain duration (s).
        wash1: Enable wash position 1.
        wash2: Enable wash position 2.
        wash3: Enable wash position 3.
        wash4: Enable wash position 4.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add("ANEC_sub_unload_cell", {})

    # epm.add("ANEC_sub_normal_state", {})

    epm.add(
        "ANEC_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )

    for cycle, (potential, time) in enumerate(zip(WE_potential__V, CA_duration_sec)):
        print(
            f" ... cycle {cycle} potential:",
            potential,
            f" ... cycle {cycle} duration:",
            time,
        )

        epm.add(
            "ANEC_sub_flush_fill_cell",
            {
                "liquid_flush_time": 80,
                "co2_purge_time": 15,
                "equilibration_time": 1.0,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
            },
        )

        epm.add(
            "ANEC_sub_CA",
            {
                "WE_potential__V": potential,
                "WE_versus": WE_versus,
                "ref_type": ref_type,
                "pH": pH,
                "ref_offset__V": ref_offset__V,
                "CA_duration_sec": time,
                "SampleRate": SampleRate,
                "IErange": IErange,
            },
        )

        epm.add(
            "ANEC_sub_liquidarchive",
            {
                "toolarchive": toolarchive,
                "volume_ul_archive": volume_ul_archive,
                "wash1": wash1,
                "wash2": wash2,
                "wash3": wash3,
                "wash4": wash4,
            },
        )

        epm.add("ANEC_sub_drain_cell", {"drain_time": liquidDrain_time})

    epm.add("ANEC_sub_alloff", {})

    return epm.planned_experiments


def ANEC_OCV(
    sequence_version: int = 1,
    plate_id: int = 4534,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 1511,
    volume_ul_cell_liquid: float = 1000,
    Tval__s: Optional[float] = 900.0,
    IErange: Optional[str] = "auto",
    toolarchive: str = "LS 3",
    volume_ul_archive: int = 500,
    liquidDrain_time: float = 80.0,
    wash1: bool = True,
    wash2: bool = True,
    wash3: bool = True,
    wash4: bool = False,
) -> list:
    """Load, fill, run a single OCV, take a liquid archive aliquot, then drain.

    Args:
        sequence_version: Sequence version tag.
        plate_id: Plate id of the solid sample.
        solid_sample_no: Sample number on the plate.
        reservoir_liquid_sample_no: Reservoir liquid sample number.
        volume_ul_cell_liquid: Cell fill volume (uL).
        Tval__s: OCV duration (s).
        IErange: Gamry current range string.
        toolarchive: PAL tool string for the archive injection.
        volume_ul_archive: Archive aliquot volume (uL).
        liquidDrain_time: Drain duration (s).
        wash1: Enable wash position 1.
        wash2: Enable wash position 2.
        wash3: Enable wash position 3.
        wash4: Enable wash position 4.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add("ANEC_sub_unload_cell", {})

    # epm.add("ANEC_sub_normal_state", {})

    epm.add(
        "ANEC_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )

    epm.add(
        "ANEC_sub_flush_fill_cell",
        {
            "liquid_flush_time": 80,
            "co2_purge_time": 15,
            "equilibration_time": 1.0,
            "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
            "volume_ul_cell_liquid": volume_ul_cell_liquid,
        },
    )

    epm.add(
        "ANEC_sub_OCV",
        {
            "Tval__s": Tval__s,
            "IErange": IErange,
        },
    )

    epm.add(
        "ANEC_sub_liquidarchive",
        {
            "toolarchive": toolarchive,
            "volume_ul_archive": volume_ul_archive,
            "wash1": wash1,
            "wash2": wash2,
            "wash3": wash3,
            "wash4": wash4,
        },
    )

    epm.add("ANEC_sub_drain_cell", {"drain_time": liquidDrain_time})
    return epm.planned_experiments


def ANEC_photo_CA(
    sequence_version: int = 3,
    plate_id: int = 4534,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 1511,
    volume_ul_cell_liquid: float = 1000,
    WE_potential__V: List[float] = [-0.9, -1.0, -1.1, -1.2, -1.3],
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    CA_duration_sec: List[float] = [900, 900, 900, 900, 900],
    SampleRate: float = 0.01,
    IErange: str = "auto",
    gamrychannelwait: int = -1,
    gamrychannelsend: int = 0,
    ref_offset__V: float = 0.0,
    led_wavelengths_nm: float = 450.0,
    led_type: str = "front",
    led_date: str = "01/01/2000",
    led_intensities_mw: float = 9.0,
    led_name_CA: str = "Thorlab_led",
    toggleCA_illum_duty: float = 0.5,
    toggleCA_illum_period: float = 1.0,
    toggleCA_dark_time_init: float = 0,
    toggleCA_illum_time: float = -1,
    toolGC: str = "HS 2",
    toolarchive: str = "LS 3",
    volume_ul_GC: int = 300,
    volume_ul_archive: int = 500,
    wash1: bool = True,
    wash2: bool = True,
    wash3: bool = True,
    wash4: bool = False,
    liquid_flush_time: float = 60.0,
    liquidDrain_time: float = 80.0,
) -> list:
    """Photo-CA series: load sample, fill, run photo-CA at each potential with aliquots, then drain.

    Iterates over ``WE_potential__V`` running ``ANEC_sub_photo_CA`` at each potential with the matching duration and LED toggle settings, taking a GC+archive aliquot between cycles.

    Args:
        sequence_version: Parameter passed through to the sub-experiments.
        plate_id: Parameter passed through to the sub-experiments.
        solid_sample_no: Parameter passed through to the sub-experiments.
        reservoir_liquid_sample_no: Parameter passed through to the sub-experiments.
        volume_ul_cell_liquid: Parameter passed through to the sub-experiments.
        WE_potential__V: Parameter passed through to the sub-experiments.
        WE_versus: Parameter passed through to the sub-experiments.
        ref_type: Parameter passed through to the sub-experiments.
        pH: Parameter passed through to the sub-experiments.
        CA_duration_sec: Parameter passed through to the sub-experiments.
        SampleRate: Parameter passed through to the sub-experiments.
        IErange: Parameter passed through to the sub-experiments.
        gamrychannelwait: Parameter passed through to the sub-experiments.
        gamrychannelsend: Parameter passed through to the sub-experiments.
        ref_offset__V: Parameter passed through to the sub-experiments.
        led_wavelengths_nm: Parameter passed through to the sub-experiments.
        led_type: Parameter passed through to the sub-experiments.
        led_date: Parameter passed through to the sub-experiments.
        led_intensities_mw: Parameter passed through to the sub-experiments.
        led_name_CA: Parameter passed through to the sub-experiments.
        toggleCA_illum_duty: Parameter passed through to the sub-experiments.
        toggleCA_illum_period: Parameter passed through to the sub-experiments.
        toggleCA_dark_time_init: Parameter passed through to the sub-experiments.
        toggleCA_illum_time: Parameter passed through to the sub-experiments.
        toolGC: Parameter passed through to the sub-experiments.
        toolarchive: Parameter passed through to the sub-experiments.
        volume_ul_GC: Parameter passed through to the sub-experiments.
        volume_ul_archive: Parameter passed through to the sub-experiments.
        wash1: Parameter passed through to the sub-experiments.
        wash2: Parameter passed through to the sub-experiments.
        wash3: Parameter passed through to the sub-experiments.
        wash4: Parameter passed through to the sub-experiments.
        liquid_flush_time: Parameter passed through to the sub-experiments.
        liquidDrain_time: Parameter passed through to the sub-experiments.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add("ANEC_sub_unload_cell", {})

    # epm.add("ANEC_sub_normal_state", {})

    epm.add(
        "ANEC_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )

    for cycle, (potential, time) in enumerate(zip(WE_potential__V, CA_duration_sec)):
        print(
            f" ... cycle {cycle} potential:",
            potential,
            f" ... cycle {cycle} duration:",
            time,
        )

        epm.add(
            "ANEC_sub_flush_fill_cell",
            {
                "liquid_flush_time": liquid_flush_time,
                "co2_purge_time": 15,
                "equilibration_time": 1.0,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
            },
        )

        epm.add(
            "ANEC_sub_photo_CA",
            {
                "WE_potential__V": potential,
                "WE_versus": WE_versus,
                "ref_type": ref_type,
                "pH": pH,
                "ref_offset__V": ref_offset__V,
                "CA_duration_sec": time,
                "SampleRate": SampleRate,
                "IErange": IErange,
                "gamrychannelwait": gamrychannelwait,
                "gamrychannelsend": gamrychannelsend,
                "illumination_source": led_name_CA,
                "illumination_wavelength": led_wavelengths_nm,
                "illumination_intensity": led_intensities_mw,
                "illumination_intensity_date": led_date,
                "illumination_side": led_type,
                "toggle_illum_duty": toggleCA_illum_duty,
                "toggle_illum_period": toggleCA_illum_period,
                "toggle_illum_time": toggleCA_illum_time,
                "toggle_dark_time_init": toggleCA_dark_time_init,
            },
        )

        epm.add(
            "ANEC_sub_aliquot",
            {
                "toolGC": toolGC,
                "toolarchive": toolarchive,
                "volume_ul_GC": volume_ul_GC,
                "volume_ul_archive": volume_ul_archive,
                "wash1": wash1,
                "wash2": wash2,
                "wash3": wash3,
                "wash4": wash4,
            },
        )

        epm.add("ANEC_sub_drain_cell", {"drain_time": liquidDrain_time})
    if len(WE_potential__V) > 1:
        epm.add("ANEC_sub_alloff", {})
    return epm.planned_experiments


def ANEC_photo_CAgasonly(
    sequence_version: int = 3,
    plate_id: int = 4534,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 1511,
    volume_ul_cell_liquid: float = 1000,
    WE_potential__V: List[float] = [-0.2, -0.3, -0.4, -0.5, -0.6],
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    CA_duration_sec: List[float] = [600, 600, 600, 600, 600],
    SampleRate: float = 0.01,
    IErange: str = "auto",
    gamrychannelwait: int = -1,
    gamrychannelsend: int = 0,
    ref_offset__V: float = 0.0,
    led_wavelengths_nm: float = 450.0,
    led_type: str = "front",
    led_date: str = "01/01/2000",
    led_intensities_mw: float = 9.0,
    led_name_CA: str = "Thorlab_led",
    toggleCA_illum_duty: float = 0.5,
    toggleCA_illum_period: float = 1.0,
    toggleCA_dark_time_init: float = 0,
    toggleCA_illum_time: float = -1,
    toolGC: str = "HS 2",
    volume_ul_GC: int = 300,
    liquid_flush_time: float = 60.0,
    liquidDrain_time: float = 80.0,
) -> list:
    """Photo-CA series taking only the GC (headspace) aliquot per cycle.

    Same flow as :func:`ANEC_photo_CA` but the aliquot step uses ``ANEC_sub_GCLiquid_archive`` for a GC-only sample.

    Args:
        sequence_version: Parameter passed through to the sub-experiments.
        plate_id: Parameter passed through to the sub-experiments.
        solid_sample_no: Parameter passed through to the sub-experiments.
        reservoir_liquid_sample_no: Parameter passed through to the sub-experiments.
        volume_ul_cell_liquid: Parameter passed through to the sub-experiments.
        WE_potential__V: Parameter passed through to the sub-experiments.
        WE_versus: Parameter passed through to the sub-experiments.
        ref_type: Parameter passed through to the sub-experiments.
        pH: Parameter passed through to the sub-experiments.
        CA_duration_sec: Parameter passed through to the sub-experiments.
        SampleRate: Parameter passed through to the sub-experiments.
        IErange: Parameter passed through to the sub-experiments.
        gamrychannelwait: Parameter passed through to the sub-experiments.
        gamrychannelsend: Parameter passed through to the sub-experiments.
        ref_offset__V: Parameter passed through to the sub-experiments.
        led_wavelengths_nm: Parameter passed through to the sub-experiments.
        led_type: Parameter passed through to the sub-experiments.
        led_date: Parameter passed through to the sub-experiments.
        led_intensities_mw: Parameter passed through to the sub-experiments.
        led_name_CA: Parameter passed through to the sub-experiments.
        toggleCA_illum_duty: Parameter passed through to the sub-experiments.
        toggleCA_illum_period: Parameter passed through to the sub-experiments.
        toggleCA_dark_time_init: Parameter passed through to the sub-experiments.
        toggleCA_illum_time: Parameter passed through to the sub-experiments.
        toolGC: Parameter passed through to the sub-experiments.
        volume_ul_GC: Parameter passed through to the sub-experiments.
        liquid_flush_time: Parameter passed through to the sub-experiments.
        liquidDrain_time: Parameter passed through to the sub-experiments.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add("ANEC_sub_unload_cell", {})

    # epm.add("ANEC_sub_normal_state", {})

    epm.add(
        "ANEC_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )

    for cycle, (potential, time) in enumerate(zip(WE_potential__V, CA_duration_sec)):
        print(
            f" ... cycle {cycle} potential:",
            potential,
            f" ... cycle {cycle} duration:",
            time,
        )

        epm.add(
            "ANEC_sub_flush_fill_cell",
            {
                "liquid_flush_time": liquid_flush_time,
                "co2_purge_time": 15,
                "equilibration_time": 1.0,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
            },
        )

        epm.add(
            "ANEC_sub_photo_CA",
            {
                "WE_potential__V": potential,
                "WE_versus": WE_versus,
                "ref_type": ref_type,
                "pH": pH,
                "ref_offset__V": ref_offset__V,
                "CA_duration_sec": time,
                "SampleRate": SampleRate,
                "IErange": IErange,
                "gamrychannelwait": gamrychannelwait,
                "gamrychannelsend": gamrychannelsend,
                "illumination_source": led_name_CA,
                "illumination_wavelength": led_wavelengths_nm,
                "illumination_intensity": led_intensities_mw,
                "illumination_intensity_date": led_date,
                "illumination_side": led_type,
                "toggle_illum_duty": toggleCA_illum_duty,
                "toggle_illum_period": toggleCA_illum_period,
                "toggle_illum_time": toggleCA_illum_time,
                "toggle_dark_time_init": toggleCA_dark_time_init,
            },
        )

        epm.add(
            "ANEC_sub_GC_preparation",
            {
                "toolGC": toolGC,
                "volume_ul_GC": volume_ul_GC,
            },
        )

        epm.add("ANEC_sub_drain_cell", {"drain_time": liquidDrain_time})
    if len(WE_potential__V) > 1:
        epm.add("ANEC_sub_alloff", {})
    return epm.planned_experiments


def ANEC_photo_CV(
    sequence_version: int = 1,
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    num_repeats: int = 1,
    plate_id: int = 4534,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 1511,
    volume_ul_cell_liquid: float = 1000,
    WE_potential_init__V: float = 0.0,
    WE_potential_apex1__V: float = -1.0,
    WE_potential_apex2__V: float = -1.0,
    WE_potential_final__V: float = 0.0,
    ScanRate_V_s: float = 0.01,
    Cycles: int = 1,
    SampleRate: float = 0.01,
    IErange: str = "auto",
    gamrychannelwait: int = -1,
    gamrychannelsend: int = 0,
    ref_offset: float = 0.0,
    led_wavelengths_nm: float = 450.0,
    led_type: str = "front",
    led_date: str = "01/01/2000",
    led_intensities_mw: float = 9.0,
    led_name_CA: str = "Thorlab_led",
    toggleCA_illum_duty: float = 0.5,
    toggleCA_illum_period: float = 1.0,
    toggleCA_dark_time_init: float = 0,
    toggleCA_illum_time: float = -1,
    liquid_flush_time: float = 60.0,
    liquidDrain_time: float = 80.0,
) -> list:
    """Photo-CV at the cell1_we position with optional LED toggle.

    Loads the sample, fills the cell, then runs ``ANEC_sub_photo_CV`` with the configured vertices and LED parameters before draining.

    Args:
        sequence_version: Parameter passed through to the sub-experiments.
        WE_versus: Parameter passed through to the sub-experiments.
        ref_type: Parameter passed through to the sub-experiments.
        pH: Parameter passed through to the sub-experiments.
        num_repeats: Parameter passed through to the sub-experiments.
        plate_id: Parameter passed through to the sub-experiments.
        solid_sample_no: Parameter passed through to the sub-experiments.
        reservoir_liquid_sample_no: Parameter passed through to the sub-experiments.
        volume_ul_cell_liquid: Parameter passed through to the sub-experiments.
        WE_potential_init__V: Parameter passed through to the sub-experiments.
        WE_potential_apex1__V: Parameter passed through to the sub-experiments.
        WE_potential_apex2__V: Parameter passed through to the sub-experiments.
        WE_potential_final__V: Parameter passed through to the sub-experiments.
        ScanRate_V_s: Parameter passed through to the sub-experiments.
        Cycles: Parameter passed through to the sub-experiments.
        SampleRate: Parameter passed through to the sub-experiments.
        IErange: Parameter passed through to the sub-experiments.
        gamrychannelwait: Parameter passed through to the sub-experiments.
        gamrychannelsend: Parameter passed through to the sub-experiments.
        ref_offset: Parameter passed through to the sub-experiments.
        led_wavelengths_nm: Parameter passed through to the sub-experiments.
        led_type: Parameter passed through to the sub-experiments.
        led_date: Parameter passed through to the sub-experiments.
        led_intensities_mw: Parameter passed through to the sub-experiments.
        led_name_CA: Parameter passed through to the sub-experiments.
        toggleCA_illum_duty: Parameter passed through to the sub-experiments.
        toggleCA_illum_period: Parameter passed through to the sub-experiments.
        toggleCA_dark_time_init: Parameter passed through to the sub-experiments.
        toggleCA_illum_time: Parameter passed through to the sub-experiments.
        liquid_flush_time: Parameter passed through to the sub-experiments.
        liquidDrain_time: Parameter passed through to the sub-experiments.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add("ANEC_sub_unload_cell", {})

    # epm.add("ANEC_sub_normal_state", {})

    epm.add(
        "ANEC_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )

    for _ in range(num_repeats):

        epm.add(
            "ANEC_sub_flush_fill_cell",
            {
                "liquid_flush_time": liquid_flush_time,
                "co2_purge_time": 15,
                "equilibration_time": 1.0,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
            },
        )

        epm.add(
            "ANEC_sub_photo_CV",
            {
                "WE_versus": WE_versus,
                "ref_type": ref_type,
                "pH": pH,
                "WE_potential_init__V": WE_potential_init__V,
                "WE_potential_apex1__V": WE_potential_apex1__V,
                "WE_potential_apex2__V": WE_potential_apex2__V,
                "WE_potential_final__V": WE_potential_final__V,
                "ScanRate_V_s": ScanRate_V_s,
                "Cycles": Cycles,
                "SampleRate": SampleRate,
                "IErange": IErange,
                "gamrychannelwait": gamrychannelwait,
                "gamrychannelsend": gamrychannelsend,
                "illumination_source": led_name_CA,
                "illumination_wavelength": led_wavelengths_nm,
                "illumination_intensity": led_intensities_mw,
                "illumination_intensity_date": led_date,
                "illumination_side": led_type,
                "toggle_illum_duty": toggleCA_illum_duty,
                "toggle_illum_period": toggleCA_illum_period,
                "toggle_illum_time": toggleCA_illum_time,
                "toggle_dark_time_init": toggleCA_dark_time_init,
            },
        )

        epm.add("ANEC_sub_drain_cell", {"drain_time": liquidDrain_time})

    return epm.planned_experiments


def ANEC_cleanup_disengage(sequence_version: int = 1) -> list:
    """Run two cleanup passes, switch everything off, and disengage the cell.

    Args:
        sequence_version: Sequence version tag.

    Returns:
        List of planned experiments performing two cleanups followed by
        ``ANEC_sub_alloff`` and ``ANEC_sub_disengage``.
    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add("ANEC_sub_cleanup", {})
    epm.add("ANEC_sub_cleanup", {})
    epm.add("ANEC_sub_alloff", {})
    epm.add("ANEC_sub_disengage", {})

    return epm.planned_experiments


def ANEC_CA_pretreat(
    sequence_version: int = 1,
    num_repeats: int = 1,
    plate_id: int = 4534,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 1511,
    volume_ul_cell_liquid: float = 1000,
    WE_potential__V: float = 0.0,
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    CA_duration_sec: float = 0.1,
    SampleRate: float = 0.01,
    IErange: str = "auto",
    ref_offset__V: float = 0.0,
    liquid_flush_time: float = 70.0,
    liquidDrain_time: float = 50.0,
) -> list:
    """Pre-treat the cell at a single CA potential then drain.

    Loads the solid sample, flushes/fills the cell, runs one ``ANEC_sub_CA`` at ``WE_potential__V`` for ``CA_duration_sec`` seconds, and drains.

    Args:
        sequence_version: Parameter passed through to the sub-experiments.
        num_repeats: Parameter passed through to the sub-experiments.
        plate_id: Parameter passed through to the sub-experiments.
        solid_sample_no: Parameter passed through to the sub-experiments.
        reservoir_liquid_sample_no: Parameter passed through to the sub-experiments.
        volume_ul_cell_liquid: Parameter passed through to the sub-experiments.
        WE_potential__V: Parameter passed through to the sub-experiments.
        WE_versus: Parameter passed through to the sub-experiments.
        ref_type: Parameter passed through to the sub-experiments.
        pH: Parameter passed through to the sub-experiments.
        CA_duration_sec: Parameter passed through to the sub-experiments.
        SampleRate: Parameter passed through to the sub-experiments.
        IErange: Parameter passed through to the sub-experiments.
        ref_offset__V: Parameter passed through to the sub-experiments.
        liquid_flush_time: Parameter passed through to the sub-experiments.
        liquidDrain_time: Parameter passed through to the sub-experiments.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add("ANEC_sub_unload_cell", {})

    # epm.add("ANEC_sub_normal_state", {})

    epm.add(
        "ANEC_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )

    for _ in range(num_repeats):

        epm.add(
            "ANEC_sub_flush_fill_cell",
            {
                "liquid_flush_time": liquid_flush_time,
                "co2_purge_time": 15,
                "equilibration_time": 1.0,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
            },
        )

        epm.add(
            "ANEC_sub_CA",
            {
                "WE_potential__V": WE_potential__V,
                "WE_versus": WE_versus,
                "ref_type": ref_type,
                "pH": pH,
                "ref_offset__V": ref_offset__V,
                "CA_duration_sec": CA_duration_sec,
                "SampleRate": SampleRate,
                "IErange": IErange,
            },
        )

        epm.add("ANEC_sub_drain_cell", {"drain_time": liquidDrain_time})

    return epm.planned_experiments


def ANEC_CA_DOE_demo(
    sequence_version: int = 1,
    plate_id: int = 4534,
    solid_sample_no: int = 1,
    WE_potential__V: float = 0.0,
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    CA_duration_sec: float = 0.1,
    SampleRate: float = 0.01,
    IErange: str = "auto",
    ref_offset__V: float = 0.0,
    toolGC: str = "HS 2",
    toolarchive: str = "LS 3",
    volume_ul_GC: int = 300,
    volume_ul_archive: int = 500,
    wash1: bool = True,
    wash2: bool = True,
    wash3: bool = True,
    wash4: bool = False,
    liquidDrain_time: float = 60.0,
) -> list:
    """DOE-style CA at a single point with optional headspace and archive aliquots.

    Single-shot variant used in the DOE demo: load sample, fill cell, run one CA, take optional aliquots, then drain.

    Args:
        sequence_version: Parameter passed through to the sub-experiments.
        plate_id: Parameter passed through to the sub-experiments.
        solid_sample_no: Parameter passed through to the sub-experiments.
        WE_potential__V: Parameter passed through to the sub-experiments.
        WE_versus: Parameter passed through to the sub-experiments.
        ref_type: Parameter passed through to the sub-experiments.
        pH: Parameter passed through to the sub-experiments.
        CA_duration_sec: Parameter passed through to the sub-experiments.
        SampleRate: Parameter passed through to the sub-experiments.
        IErange: Parameter passed through to the sub-experiments.
        ref_offset__V: Parameter passed through to the sub-experiments.
        toolGC: Parameter passed through to the sub-experiments.
        toolarchive: Parameter passed through to the sub-experiments.
        volume_ul_GC: Parameter passed through to the sub-experiments.
        volume_ul_archive: Parameter passed through to the sub-experiments.
        wash1: Parameter passed through to the sub-experiments.
        wash2: Parameter passed through to the sub-experiments.
        wash3: Parameter passed through to the sub-experiments.
        wash4: Parameter passed through to the sub-experiments.
        liquidDrain_time: Parameter passed through to the sub-experiments.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add("ANEC_sub_unload_cell", {})

    # epm.add("ANEC_sub_normal_state", {})

    epm.add(
        "ANEC_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )

    epm.add(
        "ANEC_sub_CA",
        {
            "WE_potential__V": WE_potential__V,
            "WE_versus": WE_versus,
            "ref_type": ref_type,
            "pH": pH,
            "ref_offset__V": ref_offset__V,
            "CA_duration_sec": CA_duration_sec,
            "SampleRate": SampleRate,
            "IErange": IErange,
        },
    )

    epm.add(
        "ANEC_sub_aliquot_nomixing",
        {
            "toolGC": toolGC,
            "toolarchive": toolarchive,
            "volume_ul_GC": volume_ul_GC,
            "volume_ul_archive": volume_ul_archive,
            "wash1": wash1,
            "wash2": wash2,
            "wash3": wash3,
            "wash4": wash4,
        },
    )
    epm.add("ANEC_sub_drain_cell", {"drain_time": liquidDrain_time})

    return epm.planned_experiments


def ANEC_CA_DOE_demo_headspace(
    sequence_version: int = 1,
    plate_id: int = 4534,
    solid_sample_no: int = 1,
    WE_potential__V: float = 0.0,
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    CA_duration_sec: float = 0.1,
    SampleRate: float = 0.01,
    IErange: str = "auto",
    ref_offset__V: float = 0.0,
    toolGC: str = "HS 2",
    volume_ul_GC: int = 300,
    liquidDrain_time: float = 60.0,
) -> list:
    """DOE-style CA producing only a GC headspace aliquot.

    Variant of the DOE demo that uses ``ANEC_sub_GCLiquid_archive`` for a single headspace sample after the CA.

    Args:
        sequence_version: Parameter passed through to the sub-experiments.
        plate_id: Parameter passed through to the sub-experiments.
        solid_sample_no: Parameter passed through to the sub-experiments.
        WE_potential__V: Parameter passed through to the sub-experiments.
        WE_versus: Parameter passed through to the sub-experiments.
        ref_type: Parameter passed through to the sub-experiments.
        pH: Parameter passed through to the sub-experiments.
        CA_duration_sec: Parameter passed through to the sub-experiments.
        SampleRate: Parameter passed through to the sub-experiments.
        IErange: Parameter passed through to the sub-experiments.
        ref_offset__V: Parameter passed through to the sub-experiments.
        toolGC: Parameter passed through to the sub-experiments.
        volume_ul_GC: Parameter passed through to the sub-experiments.
        liquidDrain_time: Parameter passed through to the sub-experiments.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add("ANEC_sub_unload_cell", {})

    # epm.add("ANEC_sub_normal_state", {})

    epm.add(
        "ANEC_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )

    epm.add(
        "ANEC_sub_CA",
        {
            "WE_potential__V": WE_potential__V,
            "WE_versus": WE_versus,
            "ref_type": ref_type,
            "pH": pH,
            "ref_offset__V": ref_offset__V,
            "CA_duration_sec": CA_duration_sec,
            "SampleRate": SampleRate,
            "IErange": IErange,
        },
    )

    epm.add(
        "ANEC_sub_GC_headspacealiquot_nomixing",
        {
            "toolGC": toolGC,
            "volume_ul_GC": volume_ul_GC,
        },
    )
    epm.add("ANEC_sub_drain_cell", {"drain_time": liquidDrain_time})

    return epm.planned_experiments


def ANEC_repeat_CA(
    sequence_version: int = 1,
    num_repeats: int = 1,
    plate_id: int = 4534,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 1511,
    volume_ul_cell_liquid: float = 1000,
    WE_potential__V: float = 0.0,
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    CA_duration_sec: float = 0.1,
    SampleRate: float = 0.01,
    IErange: str = "auto",
    ref_offset__V: float = 0.0,
    toolGC: str = "HS 2",
    toolarchive: str = "LS 3",
    volume_ul_GC: int = 300,
    volume_ul_archive: int = 500,
    wash1: bool = True,
    wash2: bool = True,
    wash3: bool = True,
    wash4: bool = False,
    liquid_flush_time: float = 70.0,
    liquidDrain_time: float = 60.0,
) -> list:
    """Repeat a single-potential CA followed by aliquot+drain.

    Loads the sample once, then repeats fill -> CA -> aliquot -> drain ``num_repeats`` times.

    Args:
        sequence_version: Parameter passed through to the sub-experiments.
        num_repeats: Parameter passed through to the sub-experiments.
        plate_id: Parameter passed through to the sub-experiments.
        solid_sample_no: Parameter passed through to the sub-experiments.
        reservoir_liquid_sample_no: Parameter passed through to the sub-experiments.
        volume_ul_cell_liquid: Parameter passed through to the sub-experiments.
        WE_potential__V: Parameter passed through to the sub-experiments.
        WE_versus: Parameter passed through to the sub-experiments.
        ref_type: Parameter passed through to the sub-experiments.
        pH: Parameter passed through to the sub-experiments.
        CA_duration_sec: Parameter passed through to the sub-experiments.
        SampleRate: Parameter passed through to the sub-experiments.
        IErange: Parameter passed through to the sub-experiments.
        ref_offset__V: Parameter passed through to the sub-experiments.
        toolGC: Parameter passed through to the sub-experiments.
        toolarchive: Parameter passed through to the sub-experiments.
        volume_ul_GC: Parameter passed through to the sub-experiments.
        volume_ul_archive: Parameter passed through to the sub-experiments.
        wash1: Parameter passed through to the sub-experiments.
        wash2: Parameter passed through to the sub-experiments.
        wash3: Parameter passed through to the sub-experiments.
        wash4: Parameter passed through to the sub-experiments.
        liquid_flush_time: Parameter passed through to the sub-experiments.
        liquidDrain_time: Parameter passed through to the sub-experiments.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add("ANEC_sub_unload_cell", {})

    # epm.add("ANEC_sub_normal_state", {})

    epm.add(
        "ANEC_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )

    for _ in range(num_repeats):

        epm.add(
            "ANEC_sub_flush_fill_cell",
            {
                "liquid_flush_time": liquid_flush_time,
                "co2_purge_time": 15,
                "equilibration_time": 1.0,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
            },
        )

        epm.add(
            "ANEC_sub_CA",
            {
                "WE_potential__V": WE_potential__V,
                "WE_versus": WE_versus,
                "ref_type": ref_type,
                "pH": pH,
                "ref_offset__V": ref_offset__V,
                "CA_duration_sec": CA_duration_sec,
                "SampleRate": SampleRate,
                "IErange": IErange,
            },
        )

        epm.add(
            "ANEC_sub_aliquot",
            {
                "toolGC": toolGC,
                "toolarchive": toolarchive,
                "volume_ul_GC": volume_ul_GC,
                "volume_ul_archive": volume_ul_archive,
                "wash1": wash1,
                "wash2": wash2,
                "wash3": wash3,
                "wash4": wash4,
            },
        )
        epm.add("ANEC_sub_heatoff", {})
        epm.add("ANEC_sub_drain_cell", {"drain_time": liquidDrain_time})

    return epm.planned_experiments


def ANEC_repeat_TentHeatCAgasonly(
    sequence_version: int = 1,
    num_repeats: int = 1,
    plate_id: int = 6284,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 1511,
    volume_ul_cell_liquid: float = 1000,
    WE_potential__V: float = 0.0,
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    CA_duration_sec: float = 0.1,
    SampleRate: float = 0.01,
    IErange: str = "auto",
    ref_offset__V: float = 0.0,
    toolGC: str = "HS 2",
    volume_ul_GC: int = 300,
    liquid_flush_time: float = 70.0,
    liquidDrain_time: float = 60.0,
    target_temperature_degc: float = 25.0,
) -> list:
    """Repeated tent-heated CA with GC headspace aliquots.

    For ``num_repeats`` iterations: heat the tent, fill, run CA, take a GC-only aliquot, drain.

    Args:
        sequence_version: Parameter passed through to the sub-experiments.
        num_repeats: Parameter passed through to the sub-experiments.
        plate_id: Parameter passed through to the sub-experiments.
        solid_sample_no: Parameter passed through to the sub-experiments.
        reservoir_liquid_sample_no: Parameter passed through to the sub-experiments.
        volume_ul_cell_liquid: Parameter passed through to the sub-experiments.
        WE_potential__V: Parameter passed through to the sub-experiments.
        WE_versus: Parameter passed through to the sub-experiments.
        ref_type: Parameter passed through to the sub-experiments.
        pH: Parameter passed through to the sub-experiments.
        CA_duration_sec: Parameter passed through to the sub-experiments.
        SampleRate: Parameter passed through to the sub-experiments.
        IErange: Parameter passed through to the sub-experiments.
        ref_offset__V: Parameter passed through to the sub-experiments.
        toolGC: Parameter passed through to the sub-experiments.
        volume_ul_GC: Parameter passed through to the sub-experiments.
        liquid_flush_time: Parameter passed through to the sub-experiments.
        liquidDrain_time: Parameter passed through to the sub-experiments.
        target_temperature_degc: Parameter passed through to the sub-experiments.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add("ANEC_sub_unload_cell", {})

    # epm.add("ANEC_sub_normal_state", {})

    epm.add(
        "ANEC_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )

    for _ in range(num_repeats):
        epm.add(
            "ANEC_sub_setheat",
            {
                "target_temperature_degc": target_temperature_degc,
            },
        )
        epm.add(
            "ANEC_sub_flush_fill_cell",
            {
                "liquid_flush_time": liquid_flush_time,
                "co2_purge_time": 15,
                "equilibration_time": 1.0,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
            },
        )

        epm.add(
            "ANEC_sub_CA",
            {
                "WE_potential__V": WE_potential__V,
                "WE_versus": WE_versus,
                "ref_type": ref_type,
                "pH": pH,
                "ref_offset__V": ref_offset__V,
                "CA_duration_sec": CA_duration_sec,
                "SampleRate": SampleRate,
                "IErange": IErange,
            },
        )

        epm.add(
            "ANEC_sub_GC_preparation",
            {
                "toolGC": toolGC,
                "volume_ul_GC": volume_ul_GC,
            },
        )

        epm.add("ANEC_sub_drain_cell", {"drain_time": liquidDrain_time})
    epm.add("ANEC_sub_heatoff", {})
    return epm.planned_experiments


def ANEC_heatOCV(
    sequence_version: int = 1,
    plate_id: int = 4534,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 1511,
    volume_ul_cell_liquid: float = 1000,
    Tval__s: Optional[float] = 900.0,
    IErange: Optional[str] = "auto",
    liquid_flush_time: float = 60.0,
    liquidDrain_time: float = 60.0,
    target_temperature_degc: float = 25.0,
) -> list:
    """Repeated heated OCV measurement with archive aliquots.

    For ``num_repeats`` iterations: heat the tent, fill, run OCV, take an archive aliquot, drain.

    Args:
        sequence_version: Parameter passed through to the sub-experiments.
        plate_id: Parameter passed through to the sub-experiments.
        solid_sample_no: Parameter passed through to the sub-experiments.
        reservoir_liquid_sample_no: Parameter passed through to the sub-experiments.
        volume_ul_cell_liquid: Parameter passed through to the sub-experiments.
        Tval__s: Parameter passed through to the sub-experiments.
        IErange: Parameter passed through to the sub-experiments.
        liquid_flush_time: Parameter passed through to the sub-experiments.
        liquidDrain_time: Parameter passed through to the sub-experiments.
        target_temperature_degc: Parameter passed through to the sub-experiments.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add("ANEC_sub_unload_cell", {})

    # epm.add("ANEC_sub_normal_state", {})

    epm.add(
        "ANEC_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )

    epm.add(
        "ANEC_sub_setheat",
        {
            "target_temperature_degc": target_temperature_degc,
        },
    )
    epm.add(
        "ANEC_sub_flush_fill_cell",
        {
            "liquid_flush_time": liquid_flush_time,
            "co2_purge_time": 15,
            "equilibration_time": 1.0,
            "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
            "volume_ul_cell_liquid": volume_ul_cell_liquid,
        },
    )

    epm.add(
        "ANEC_sub_OCV",
        {
            "Tval__s": Tval__s,
            "IErange": IErange,
        },
    )

    epm.add("ANEC_sub_drain_cell", {"drain_time": liquidDrain_time})
    epm.add("ANEC_sub_heatoff", {})
    return epm.planned_experiments


def ANEC_repeat_TentHeatCA(
    sequence_version: int = 1,
    num_repeats: int = 1,
    plate_id: int = 6284,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 1511,
    volume_ul_cell_liquid: float = 1000,
    WE_potential__V: float = 0.0,
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    CA_duration_sec: float = 0.1,
    SampleRate: float = 0.01,
    IErange: str = "auto",
    ref_offset__V: float = 0.0,
    toolGC: str = "HS 2",
    toolarchive: str = "LS 3",
    volume_ul_GC: int = 300,
    volume_ul_archive: int = 500,
    wash1: bool = True,
    wash2: bool = True,
    wash3: bool = True,
    wash4: bool = False,
    liquid_flush_time: float = 70.0,
    liquidDrain_time: float = 80.0,
    target_temperature_degc: float = 25.0,
) -> list:
    """Repeated tent-heated CA with combined GC+archive aliquots.

    For ``num_repeats`` iterations: heat the tent, fill, run CA, take GC+archive aliquots, drain.

    Args:
        sequence_version: Parameter passed through to the sub-experiments.
        num_repeats: Parameter passed through to the sub-experiments.
        plate_id: Parameter passed through to the sub-experiments.
        solid_sample_no: Parameter passed through to the sub-experiments.
        reservoir_liquid_sample_no: Parameter passed through to the sub-experiments.
        volume_ul_cell_liquid: Parameter passed through to the sub-experiments.
        WE_potential__V: Parameter passed through to the sub-experiments.
        WE_versus: Parameter passed through to the sub-experiments.
        ref_type: Parameter passed through to the sub-experiments.
        pH: Parameter passed through to the sub-experiments.
        CA_duration_sec: Parameter passed through to the sub-experiments.
        SampleRate: Parameter passed through to the sub-experiments.
        IErange: Parameter passed through to the sub-experiments.
        ref_offset__V: Parameter passed through to the sub-experiments.
        toolGC: Parameter passed through to the sub-experiments.
        toolarchive: Parameter passed through to the sub-experiments.
        volume_ul_GC: Parameter passed through to the sub-experiments.
        volume_ul_archive: Parameter passed through to the sub-experiments.
        wash1: Parameter passed through to the sub-experiments.
        wash2: Parameter passed through to the sub-experiments.
        wash3: Parameter passed through to the sub-experiments.
        wash4: Parameter passed through to the sub-experiments.
        liquid_flush_time: Parameter passed through to the sub-experiments.
        liquidDrain_time: Parameter passed through to the sub-experiments.
        target_temperature_degc: Parameter passed through to the sub-experiments.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add("ANEC_sub_unload_cell", {})

    # epm.add("ANEC_sub_normal_state", {})

    epm.add(
        "ANEC_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )

    for _ in range(num_repeats):
        epm.add(
            "ANEC_sub_setheat",
            {
                "target_temperature_degc": target_temperature_degc,
            },
        )
        epm.add(
            "ANEC_sub_flush_fill_cell",
            {
                "liquid_flush_time": liquid_flush_time,
                "co2_purge_time": 15,
                "equilibration_time": 1.0,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
            },
        )

        epm.add(
            "ANEC_sub_CA",
            {
                "WE_potential__V": WE_potential__V,
                "WE_versus": WE_versus,
                "ref_type": ref_type,
                "pH": pH,
                "ref_offset__V": ref_offset__V,
                "CA_duration_sec": CA_duration_sec,
                "SampleRate": SampleRate,
                "IErange": IErange,
            },
        )

        epm.add(
            "ANEC_sub_aliquot",
            {
                "toolGC": toolGC,
                "toolarchive": toolarchive,
                "volume_ul_GC": volume_ul_GC,
                "volume_ul_archive": volume_ul_archive,
                "wash1": wash1,
                "wash2": wash2,
                "wash3": wash3,
                "wash4": wash4,
            },
        )

        epm.add("ANEC_sub_drain_cell", {"drain_time": liquidDrain_time})
    epm.add("ANEC_sub_heatoff", {})
    return epm.planned_experiments


def ANEC_repeat_HeatCA(
    sequence_version: int = 1,
    num_repeats: int = 1,
    plate_id: int = 4534,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 1511,
    volume_ul_cell_liquid: float = 1000,
    WE_potential__V: float = 0.0,
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    CA_duration_sec: float = 0.1,
    SampleRate: float = 0.01,
    IErange: str = "auto",
    ref_offset__V: float = 0.0,
    toolGC: str = "HS 2",
    toolarchive: str = "LS 3",
    volume_ul_GC: int = 300,
    volume_ul_archive: int = 500,
    wash1: bool = True,
    wash2: bool = True,
    wash3: bool = True,
    wash4: bool = False,
    liquid_flush_time: float = 70.0,
    liquidDrain_time: float = 80.0,
    target_temperature_degc: float = 25.0,
) -> list:
    """Repeated heated CA without the tent step.

    For ``num_repeats`` iterations: heat the cell, fill, run CA, take aliquots, drain.

    Args:
        sequence_version: Parameter passed through to the sub-experiments.
        num_repeats: Parameter passed through to the sub-experiments.
        plate_id: Parameter passed through to the sub-experiments.
        solid_sample_no: Parameter passed through to the sub-experiments.
        reservoir_liquid_sample_no: Parameter passed through to the sub-experiments.
        volume_ul_cell_liquid: Parameter passed through to the sub-experiments.
        WE_potential__V: Parameter passed through to the sub-experiments.
        WE_versus: Parameter passed through to the sub-experiments.
        ref_type: Parameter passed through to the sub-experiments.
        pH: Parameter passed through to the sub-experiments.
        CA_duration_sec: Parameter passed through to the sub-experiments.
        SampleRate: Parameter passed through to the sub-experiments.
        IErange: Parameter passed through to the sub-experiments.
        ref_offset__V: Parameter passed through to the sub-experiments.
        toolGC: Parameter passed through to the sub-experiments.
        toolarchive: Parameter passed through to the sub-experiments.
        volume_ul_GC: Parameter passed through to the sub-experiments.
        volume_ul_archive: Parameter passed through to the sub-experiments.
        wash1: Parameter passed through to the sub-experiments.
        wash2: Parameter passed through to the sub-experiments.
        wash3: Parameter passed through to the sub-experiments.
        wash4: Parameter passed through to the sub-experiments.
        liquid_flush_time: Parameter passed through to the sub-experiments.
        liquidDrain_time: Parameter passed through to the sub-experiments.
        target_temperature_degc: Parameter passed through to the sub-experiments.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add("ANEC_sub_unload_cell", {})

    # epm.add("ANEC_sub_normal_state", {})

    epm.add(
        "ANEC_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )

    for _ in range(num_repeats):

        epm.add(
            "ANEC_sub_flush_fill_cell",
            {
                "liquid_flush_time": liquid_flush_time,
                "co2_purge_time": 15,
                "equilibration_time": 1.0,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
            },
        )

        epm.add(
            "ANEC_sub_HeatCA",
            {
                "WE_potential__V": WE_potential__V,
                "WE_versus": WE_versus,
                "ref_type": ref_type,
                "pH": pH,
                "ref_offset__V": ref_offset__V,
                "CA_duration_sec": CA_duration_sec,
                "SampleRate": SampleRate,
                "IErange": IErange,
                "target_temperature_degc": target_temperature_degc,
            },
        )

        epm.add(
            "ANEC_sub_aliquot",
            {
                "toolGC": toolGC,
                "toolarchive": toolarchive,
                "volume_ul_GC": volume_ul_GC,
                "volume_ul_archive": volume_ul_archive,
                "wash1": wash1,
                "wash2": wash2,
                "wash3": wash3,
                "wash4": wash4,
            },
        )

        epm.add("ANEC_sub_drain_cell", {"drain_time": liquidDrain_time})

    return epm.planned_experiments


def ANEC_gasonly_CA(
    sequence_version: int = 1,
    num_repeats: int = 1,
    plate_id: int = 4534,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 1511,
    volume_ul_cell_liquid: float = 1000,
    WE_potential__V: float = 0.0,
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    CA_duration_sec: float = 0.1,
    SampleRate: float = 0.01,
    IErange: str = "auto",
    ref_offset__V: float = 0.0,
    toolGC: str = "HS 2",
    volume_ul_GC: int = 300,
    liquid_flush_time: float = 70.0,
    liquidDrain_time: float = 60.0,
) -> list:
    """Single CA producing only a gas-phase (GC) aliquot.

    Loads the sample, fills the cell, runs one CA and one GC-only aliquot, then drains.

    Args:
        sequence_version: Parameter passed through to the sub-experiments.
        num_repeats: Parameter passed through to the sub-experiments.
        plate_id: Parameter passed through to the sub-experiments.
        solid_sample_no: Parameter passed through to the sub-experiments.
        reservoir_liquid_sample_no: Parameter passed through to the sub-experiments.
        volume_ul_cell_liquid: Parameter passed through to the sub-experiments.
        WE_potential__V: Parameter passed through to the sub-experiments.
        WE_versus: Parameter passed through to the sub-experiments.
        ref_type: Parameter passed through to the sub-experiments.
        pH: Parameter passed through to the sub-experiments.
        CA_duration_sec: Parameter passed through to the sub-experiments.
        SampleRate: Parameter passed through to the sub-experiments.
        IErange: Parameter passed through to the sub-experiments.
        ref_offset__V: Parameter passed through to the sub-experiments.
        toolGC: Parameter passed through to the sub-experiments.
        volume_ul_GC: Parameter passed through to the sub-experiments.
        liquid_flush_time: Parameter passed through to the sub-experiments.
        liquidDrain_time: Parameter passed through to the sub-experiments.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add("ANEC_sub_unload_cell", {})

    # epm.add("ANEC_sub_normal_state", {})

    epm.add(
        "ANEC_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )

    for _ in range(num_repeats):

        epm.add(
            "ANEC_sub_flush_fill_cell",
            {
                "liquid_flush_time": liquid_flush_time,
                "co2_purge_time": 15,
                "equilibration_time": 1.0,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
            },
        )

        epm.add(
            "ANEC_sub_CA",
            {
                "WE_potential__V": WE_potential__V,
                "WE_versus": WE_versus,
                "ref_type": ref_type,
                "pH": pH,
                "ref_offset__V": ref_offset__V,
                "CA_duration_sec": CA_duration_sec,
                "SampleRate": SampleRate,
                "IErange": IErange,
            },
        )

        epm.add(
            "ANEC_sub_GC_preparation",
            {
                "toolGC": toolGC,
                "volume_ul_GC": volume_ul_GC,
            },
        )

        epm.add("ANEC_sub_drain_cell", {"drain_time": liquidDrain_time})

    return epm.planned_experiments


def ANEC_repeat_CV(
    sequence_version: int = 1,
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    num_repeats: int = 1,
    plate_id: int = 4534,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 1511,
    volume_ul_cell_liquid: float = 1000,
    WE_potential_init__V: float = 0.0,
    WE_potential_apex1__V: float = -1.0,
    WE_potential_apex2__V: float = -1.0,
    WE_potential_final__V: float = 0.0,
    ScanRate_V_s: float = 0.01,
    Cycles: int = 1,
    SampleRate: float = 0.01,
    IErange: str = "auto",
    ref_offset: float = 0.0,
    liquidDrain_time: float = 80.0,
) -> list:
    """Repeated CV scans with optional aliquots between repeats.

    Loads the sample once and repeats fill -> CV -> drain ``num_repeats`` times.

    Args:
        sequence_version: Parameter passed through to the sub-experiments.
        WE_versus: Parameter passed through to the sub-experiments.
        ref_type: Parameter passed through to the sub-experiments.
        pH: Parameter passed through to the sub-experiments.
        num_repeats: Parameter passed through to the sub-experiments.
        plate_id: Parameter passed through to the sub-experiments.
        solid_sample_no: Parameter passed through to the sub-experiments.
        reservoir_liquid_sample_no: Parameter passed through to the sub-experiments.
        volume_ul_cell_liquid: Parameter passed through to the sub-experiments.
        WE_potential_init__V: Parameter passed through to the sub-experiments.
        WE_potential_apex1__V: Parameter passed through to the sub-experiments.
        WE_potential_apex2__V: Parameter passed through to the sub-experiments.
        WE_potential_final__V: Parameter passed through to the sub-experiments.
        ScanRate_V_s: Parameter passed through to the sub-experiments.
        Cycles: Parameter passed through to the sub-experiments.
        SampleRate: Parameter passed through to the sub-experiments.
        IErange: Parameter passed through to the sub-experiments.
        ref_offset: Parameter passed through to the sub-experiments.
        liquidDrain_time: Parameter passed through to the sub-experiments.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add("ANEC_sub_unload_cell", {})

    # epm.add("ANEC_sub_normal_state", {})

    epm.add(
        "ANEC_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )

    for _ in range(num_repeats):

        epm.add(
            "ANEC_sub_flush_fill_cell",
            {
                "liquid_flush_time": 80,
                "co2_purge_time": 15,
                "equilibration_time": 1.0,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
            },
        )

        epm.add(
            "ANEC_sub_CV",
            {
                "WE_versus": WE_versus,
                "ref_type": ref_type,
                "pH": pH,
                "WE_potential_init__V": WE_potential_init__V,
                "WE_potential_apex1__V": WE_potential_apex1__V,
                "WE_potential_apex2__V": WE_potential_apex2__V,
                "WE_potential_final__V": WE_potential_final__V,
                "ScanRate_V_s": ScanRate_V_s,
                "Cycles": Cycles,
                "SampleRate": SampleRate,
                "IErange": IErange,
            },
        )

        epm.add("ANEC_sub_drain_cell", {"drain_time": liquidDrain_time})

    return epm.planned_experiments


def ANEC_ferricyanide_simpleprotocol(
    sequence_version: int = 2,
    num_repeats: int = 1,
    plate_id: int = 5740,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 1511,
    volume_ul_cell_liquid: float = 1000,
    WE_potential__V: float = -0.8,
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    CA_duration_sec: float = 120.0,
    SampleRate_CA: float = 0.5,
    IErange: str = "3mA",
    ref_offset__V: float = 0.0,
    WE_potential_init__V: float = 0.5,
    WE_potential_apex1__V: float = -1.0,
    WE_potential_apex2__V: float = 0.5,
    WE_potential_final__V: float = 0.5,
    ScanRate_V_s: float = 0.1,
    Cycles: int = 1,
    SampleRate_CV: float = 0.1,
    target_temperature_degc: float = 25.0,
) -> list:
    """Simple ferricyanide diagnostic protocol.

    Runs a fixed fill/CA/aliquot/drain protocol used to validate the ANEC potentiostat with a ferricyanide standard.

    Args:
        sequence_version: Parameter passed through to the sub-experiments.
        num_repeats: Parameter passed through to the sub-experiments.
        plate_id: Parameter passed through to the sub-experiments.
        solid_sample_no: Parameter passed through to the sub-experiments.
        reservoir_liquid_sample_no: Parameter passed through to the sub-experiments.
        volume_ul_cell_liquid: Parameter passed through to the sub-experiments.
        WE_potential__V: Parameter passed through to the sub-experiments.
        WE_versus: Parameter passed through to the sub-experiments.
        ref_type: Parameter passed through to the sub-experiments.
        pH: Parameter passed through to the sub-experiments.
        CA_duration_sec: Parameter passed through to the sub-experiments.
        SampleRate_CA: Parameter passed through to the sub-experiments.
        IErange: Parameter passed through to the sub-experiments.
        ref_offset__V: Parameter passed through to the sub-experiments.
        WE_potential_init__V: Parameter passed through to the sub-experiments.
        WE_potential_apex1__V: Parameter passed through to the sub-experiments.
        WE_potential_apex2__V: Parameter passed through to the sub-experiments.
        WE_potential_final__V: Parameter passed through to the sub-experiments.
        ScanRate_V_s: Parameter passed through to the sub-experiments.
        Cycles: Parameter passed through to the sub-experiments.
        SampleRate_CV: Parameter passed through to the sub-experiments.
        target_temperature_degc: Parameter passed through to the sub-experiments.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add("ANEC_sub_unload_cell", {})

    # epm.add("ANEC_sub_normal_state", {})

    epm.add(
        "ANEC_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )

    for _ in range(num_repeats):

        epm.add(
            "ANEC_sub_HeatCV",
            {
                "WE_versus": WE_versus,
                "ref_type": ref_type,
                "pH": pH,
                "WE_potential_init__V": WE_potential_init__V,
                "WE_potential_apex1__V": WE_potential_apex1__V,
                "WE_potential_apex2__V": WE_potential_apex2__V,
                "WE_potential_final__V": WE_potential_final__V,
                "ScanRate_V_s": ScanRate_V_s,
                "Cycles": Cycles,
                "SampleRate": SampleRate_CV,
                "IErange": IErange,
                "target_temperature_degc": target_temperature_degc,
            },
        )
        epm.add(
            "ANEC_sub_HeatCA",
            {
                "WE_potential__V": WE_potential__V,
                "WE_versus": WE_versus,
                "ref_type": ref_type,
                "pH": pH,
                "ref_offset__V": ref_offset__V,
                "CA_duration_sec": CA_duration_sec,
                "SampleRate": SampleRate_CA,
                "IErange": IErange,
                "target_temperature_degc": target_temperature_degc,
            },
        )

    return epm.planned_experiments


def ANEC_ferricyanide_protocol(
    sequence_version: int = 2,
    plate_id: int = 5740,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 1511,
    volume_ul_cell_liquid: float = 1000,
    WE_potential__V: float = -0.8,
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    CA_duration_sec: float = 120.0,
    SampleRate_CA: float = 0.5,
    IErange: str = "3mA",
    ref_offset__V: float = 0.0,
    WE_potential_init__V: float = 0.5,
    WE_potential_apex1__V: float = -1.0,
    WE_potential_apex2__V: float = 0.5,
    WE_potential_final__V: float = 0.5,
    ScanRate_V_s: float = 0.1,
    Cycles: int = 1,
    SampleRate_CV: float = 0.1,
    liquidDrain_time: float = 80.0,
    target_temperature_degc: List[float] = [25.0],
    CV_only: str = "yes",
) -> list:
    """Full ferricyanide validation protocol with multi-step CA/CV.

    Extended ferricyanide diagnostic: fills the cell, runs CA and CV with archive aliquots, then drains and cleans.

    Args:
        sequence_version: Parameter passed through to the sub-experiments.
        plate_id: Parameter passed through to the sub-experiments.
        solid_sample_no: Parameter passed through to the sub-experiments.
        reservoir_liquid_sample_no: Parameter passed through to the sub-experiments.
        volume_ul_cell_liquid: Parameter passed through to the sub-experiments.
        WE_potential__V: Parameter passed through to the sub-experiments.
        WE_versus: Parameter passed through to the sub-experiments.
        ref_type: Parameter passed through to the sub-experiments.
        pH: Parameter passed through to the sub-experiments.
        CA_duration_sec: Parameter passed through to the sub-experiments.
        SampleRate_CA: Parameter passed through to the sub-experiments.
        IErange: Parameter passed through to the sub-experiments.
        ref_offset__V: Parameter passed through to the sub-experiments.
        WE_potential_init__V: Parameter passed through to the sub-experiments.
        WE_potential_apex1__V: Parameter passed through to the sub-experiments.
        WE_potential_apex2__V: Parameter passed through to the sub-experiments.
        WE_potential_final__V: Parameter passed through to the sub-experiments.
        ScanRate_V_s: Parameter passed through to the sub-experiments.
        Cycles: Parameter passed through to the sub-experiments.
        SampleRate_CV: Parameter passed through to the sub-experiments.
        liquidDrain_time: Parameter passed through to the sub-experiments.
        target_temperature_degc: Parameter passed through to the sub-experiments.
        CV_only: Parameter passed through to the sub-experiments.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add("ANEC_sub_unload_cell", {})

    # epm.add("ANEC_sub_normal_state", {})

    epm.add(
        "ANEC_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )
    epm.add(
        "ANEC_sub_flush_fill_cell",
        {
            "liquid_flush_time": 80,
            "co2_purge_time": 15,
            "equilibration_time": 1.0,
            "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
            "volume_ul_cell_liquid": volume_ul_cell_liquid,
        },
    )
    for cycle, temp in enumerate(target_temperature_degc):
        epm.add(
            "ANEC_sub_HeatCV",
            {
                "WE_versus": WE_versus,
                "ref_type": ref_type,
                "pH": pH,
                "WE_potential_init__V": WE_potential_init__V,
                "WE_potential_apex1__V": WE_potential_apex1__V,
                "WE_potential_apex2__V": WE_potential_apex2__V,
                "WE_potential_final__V": WE_potential_final__V,
                "ScanRate_V_s": ScanRate_V_s,
                "Cycles": Cycles,
                "SampleRate": SampleRate_CV,
                "IErange": IErange,
                "target_temperature_degc": temp,
            },
        )
        if CV_only == "no":
            epm.add(
                "ANEC_sub_HeatCA",
                {
                    "WE_potential__V": WE_potential__V,
                    "WE_versus": WE_versus,
                    "ref_type": ref_type,
                    "pH": pH,
                    "ref_offset__V": ref_offset__V,
                    "CA_duration_sec": CA_duration_sec,
                    "SampleRate": SampleRate_CA,
                    "IErange": IErange,
                    "target_temperature_degc": temp,
                },
            )
    epm.add("ANEC_sub_heatoff", {})
    epm.add("ANEC_sub_drain_cell", {"drain_time": liquidDrain_time})

    return epm.planned_experiments


def ANEC_create_and_load_liquid_sample(
    volume_ml: float = 0.84,
    source: List[str] = ["autoGDE"],
    partial_molarity: List[str] = ["unknown"],
    chemical: List[str] = ["unknown"],
    ph: float = 7.8,
    supplier: List[str] = ["N/A"],
    lot_number: List[str] = ["N/A"],
    electrolyte_name: str = "1M KHCO3",
    prep_date: str = "2024-03-19",
    tray: int = 2,
    slot: int = 1,
    vial: List[int] = [1, 2, 3, 4, 5],
) -> list:
    """Create and load identical liquid samples into a tray's vials.

    For each entry in ``vial`` adds one ``create_and_load_liquid_sample``
    experiment, all sharing the supplied chemistry metadata.

    Args:
        volume_ml: Per-vial sample volume (mL).
        source: Source labels recorded on the sample.
        partial_molarity: Per-constituent partial molarity strings.
        chemical: Per-constituent chemical identifier strings.
        ph: Solution pH.
        supplier: Per-constituent supplier strings.
        lot_number: Per-constituent lot-number strings.
        electrolyte_name: Electrolyte label.
        prep_date: Preparation date.
        tray: PAL tray index (the call site hard-codes tray=2).
        slot: PAL slot index.
        vial: Iterable of PAL vial indices to fill.

    Returns:
        List of planned create-and-load experiments.
    """
    epm = ExperimentPlanMaker()
    for num, vial_no in enumerate(vial):
        epm.add(
            "create_and_load_liquid_sample",
            {
                "volume_ml": volume_ml,
                "source": source,
                "partial_molarity": partial_molarity,
                "chemical": chemical,
                "ph": ph,
                "supplier": supplier,
                "lot_number": lot_number,
                "electrolyte_name": electrolyte_name,
                "prep_date": prep_date,
                "tray": 2,
                "slot": slot,
                "vial": vial_no,
            },
        )

    return epm.planned_experiments


# =============================================================================
# def ANEC_create_liquid_sample(
#     sequence_version: int = 1,
#     no_of_samples: int = 5,
#     volume_ml: float = 0.84,
#     source: List[str] = ["autoGDE"],
#     partial_molarity: List[str] = ["unknown"],
#     chemical: List[str] = ["unknown"],
#     ph: float = 7.8,
#     supplier: List[str] = ["N/A"],
#     lot_number: List[str] = ["N/A"],
#     electrolyte_name: str = "1M KHCO3",
#     prep_date: str = "2024-03-19",
#
#
# ):
#     epm = ExperimentPlanMaker()
#     for _ in range(no_of_samples):
#         epm.add(
#             "create_liquid_sample",
#             {"volume_ml": volume_ml, "source": source, "partial_molarity":partial_molarity, "chemical":chemical, "ph":ph, "supplier":supplier, "lot_number":lot_number,"electrolyte_name":electrolyte_name, "prep_date":prep_date},
#         )
#
#     return epm.planned_experiments
#
# def ANEC_create_liquid_tray(
#     sequence_version: int = 1,
#     liquid_sample_no: List[int] = [1, 1, 1, 1, 1],
#     machine_name: str = "hte-ecms-01",
#     slot: int = 1,
#     vial: List[int] = [1, 2, 3, 4, 5],
#
#
# ):
#     epm = ExperimentPlanMaker()
#     for num, (sample_no, vial_no) in enumerate(zip(liquid_sample_no, vial)):
#         epm.add(
#             "load_liquid_sample",
#             {"liquid_sample_no": sample_no, "machine_name": machine_name, "tray":2, "slot":slot, "vial":vial_no},
#         )
#
#     return epm.planned_experiments
# =============================================================================


def GC_Archiveliquid_analysis(
    experiment_version: int = 1,
    source_tray: int = 2,
    source_slot: int = 1,
    source_vial_from: int = 1,
    source_vial_to: int = 1,
    dest: str = "Injector 1",
    volume_ul: int = 2,
    GC_analysis_time: float = 520.0,
) -> list:
    """Inject archived liquid samples into the GC over a range of vials.

    Iterates ``source_vial`` from ``source_vial_from`` through ``source_vial_to``
    inclusive and queues one ``ANEC_sub_GCLiquid_analysis`` experiment per vial.

    Args:
        experiment_version: Experiment version tag (unused beyond bookkeeping).
        source_tray: PAL source tray index.
        source_slot: PAL source slot index.
        source_vial_from: First vial number (inclusive).
        source_vial_to: Last vial number (inclusive).
        dest: GC injection destination string.
        volume_ul: Injection volume per vial (uL).
        GC_analysis_time: GC analysis duration (s).

    Returns:
        List of planned ``ANEC_sub_GCLiquid_analysis`` experiments.
    """

    epm = ExperimentPlanMaker()

    for source_vial in range(source_vial_from, source_vial_to + 1):
        epm.add(
            "ANEC_sub_GCLiquid_analysis",
            {
                "source_tray": source_tray,
                "source_slot": source_slot,
                "source_vial": source_vial,
                "dest": dest,
                "volume_ul": volume_ul,
                "GC_analysis_time": GC_analysis_time,
            },
        )

    return epm.planned_experiments


def HPLC_Archiveliquid_analysis(
    experiment_version: int = 1,
    source_tray: int = 2,
    source_slot: int = 1,
    source_vial_from: int = 1,
    source_vial_to: int = 1,
    dest: str = "LCInjector1",
    volume_ul: int = 25,
) -> list:
    """Inject archived liquid samples into the HPLC over a range of vials.

    Iterates ``source_vial`` from ``source_vial_from`` through ``source_vial_to``
    inclusive and queues one ``ANEC_sub_HPLCLiquid_analysis`` experiment per
    vial with all wash positions enabled except wash4.

    Args:
        experiment_version: Experiment version tag (unused beyond bookkeeping).
        source_tray: PAL source tray index.
        source_slot: PAL source slot index.
        source_vial_from: First vial number (inclusive).
        source_vial_to: Last vial number (inclusive).
        dest: HPLC injection destination string.
        volume_ul: Injection volume per vial (uL).

    Returns:
        List of planned ``ANEC_sub_HPLCLiquid_analysis`` experiments.
    """

    epm = ExperimentPlanMaker()

    for source_vial in range(source_vial_from, source_vial_to + 1):
        epm.add(
            "ANEC_sub_HPLCLiquid_analysis",
            {
                "source_tray": source_tray,
                "source_slot": source_slot,
                "source_vial": source_vial,
                "dest": dest,
                "volume_ul": volume_ul,
                "wash1": True,
                "wash2": True,
                "wash3": True,
                "wash4": False,
            },
        )

    return epm.planned_experiments
