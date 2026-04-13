"""
Sequence library for UVIS
"""

__all__ = ["UVIS_R", "UVIS_R_postseq", "UVIS_R_shutoff", "UVIS_GAIA_preset"]

from helao.helpers.premodels import ExperimentPlanMaker


SEQUENCES = __all__


def UVIS_R(
    sequence_version: int = 5,
    plate_id: int = 1,
    plate_sample_no_list: list = [2],
    reference_after_sample_list: list = [],
    reference_mode: str = "builtin",
    custom_position: str = "cell1_we",
    spec_n_avg: int = 5,
    spec_int_time_ms: int = 300,
    duration_sec: float = -1,
    specref_code: int = 1,
    led_type: str = "front",
    led_date: str = "n/a",
    led_names: list = ["lamp_shutter"],
    led_wavelengths_nm: list = [-1],
    led_intensities_mw: list = [-1],
    toggle_is_shutter: bool = False,
):
    epm = ExperimentPlanMaker()
    epm.add(
        "UVIS_measure_references",
        {
            "plate_id": plate_id,
            "custom_position": custom_position,
            "spec_n_avg": spec_n_avg,
            "spec_int_time_ms": spec_int_time_ms,
            "duration_sec": duration_sec,
            "specref_code": specref_code,
            "led_type": led_type,
            "led_date": led_date,
            "led_names": led_names,
            "led_wavelengths_nm": led_wavelengths_nm,
            "led_intensities_mw": led_intensities_mw,
            "toggle_is_shutter": toggle_is_shutter,
        },
    )

    for plate_sample in plate_sample_no_list:
        epm.add("UVIS_sub_unloadall_customs", {})
        epm.add(
            "UVIS_sub_startup",  # move to solid sample, assign to cell position
            {
                "solid_custom_position": custom_position,
                "solid_plate_id": plate_id,
                "solid_sample_no": plate_sample,
            },
        )
        # perform transmission spec
        epm.add(
            "UVIS_sub_measure",
            {
                "spec_type": "R",
                "spec_int_time_ms": spec_int_time_ms,
                "spec_n_avg": spec_n_avg,
                "duration_sec": duration_sec,
                "toggle_source": led_names[0],
                "toggle_is_shutter": toggle_is_shutter,
                "illumination_wavelength": led_wavelengths_nm[0],
                "illumination_intensity": led_intensities_mw[0],
                "illumination_intensity_date": led_date,
                "illumination_side": led_type,
                "technique_name": "R_UVVIS",
                "run_use": "data",
                "reference_mode": reference_mode,
                "acquire_image": True,
            },
        )
        if plate_sample in reference_after_sample_list:
            epm.add(
                "UVIS_measure_references",
                {
                    "plate_id": plate_id,
                    "custom_position": custom_position,
                    "spec_n_avg": spec_n_avg,
                    "spec_int_time_ms": spec_int_time_ms,
                    "duration_sec": duration_sec,
                    "specref_code": specref_code,
                    "led_type": led_type,
                    "led_date": led_date,
                    "led_names": led_names,
                    "led_wavelengths_nm": led_wavelengths_nm,
                    "led_intensities_mw": led_intensities_mw,
                    "toggle_is_shutter": toggle_is_shutter,
                },
            )

    epm.add("UVIS_sub_unloadall_customs", {})
    epm.add("UVIS_sub_shutdown", {"toggle_source": led_names[0]})

    return epm.planned_experiments  # returns complete experiment list


def UVIS_R_postseq(
    sequence_version: int = 1,
    analysis_seq_uuid: str = "",
    plate_id: int = 0,
    recent: bool = False,
):
    epm = ExperimentPlanMaker()
    epm.add(
        "UVIS_analysis_dry",
        {
            "sequence_uuid": analysis_seq_uuid,
            "plate_id": plate_id,
            "recent": recent,
        },
    )

    return epm.planned_experiments  # returns complete experiment list


def UVIS_R_shutoff(
    sequence_version: int = 1,
    outlet_number: int = 1,
):
    epm = ExperimentPlanMaker()
    epm.add(
        "UVIS_sub_shutoff_lamp",
        {
            "outlet_number": outlet_number,
        },
    )

    return epm.planned_experiments  # returns complete experiment list


def UVIS_GAIA_preset(
    sequence_version: int = 5,
    plate_id: int = 1,
    reference_mode: str = "builtin",
    custom_position: str = "cell1_we",
    spec_n_avg: int = 30,
    spec_int_time_ms: int = 100,
    duration_sec: float = -1,
    specref_code: int = 1,
    led_type: str = "front",
    led_date: str = "n/a",
    led_names: list = ["lamp_shutter"],
    led_wavelengths_nm: list = [-1],
    led_intensities_mw: list = [-1],
    toggle_is_shutter: bool = False,
):
    MAP = [
        13983,
        13999,
        14015,
        14031,
        14047,
        14063,
        14079,
        14095,
        14111,
        14127,
        14143,
        796,
        2841,
        5348,
        8151,
        11103,
        17023,
        19975,
        22778,
        25285,
        27330,
    ]
    REF = [14143, 27330]
    REMAP = [
        13977,
        13993,
        14009,
        14025,
        14041,
        14057,
        14073,
        14089,
        14105,
        14121,
        14137,
        806,
        2851,
        5358,
        8161,
        11113,
        17033,
        19985,
        22788,
        25295,
        27340,
    ]
    REREF = [14137, 27340]
    REMAPPED_PLATES = [
        10051,
        10052,
        10057,
        10059,
        10062,
        10063,
        10064,
        10065,
        10066,
        10067,
        10068,
        10071,
        10072,
        10075,
        10076,
        10079,
        10080,
        10082,
        10083,
        10084,
        10085,
        10086,
        10087,
        10088,
        10089,
        10090,
        10091,
        10092,
        10093,
        10097,
        10098,
        10099,
        10100,
        10101,
        10102,
        10103,
        10104,
        10105,
        10106,
        10107,
        10108,
        10109,
        10110,
        10111,
        10112,
        10113,
        10114,
        10115,
        10116,
        10117,
        10118,
        10120,
        10121,
        10122,
        10123,
        10124,
        10126,
        10128,
        10129,
        10130,
        10131,
        10132,
        10133,
        10135,
        10137,
        10138,
        10140,
        10141,
        10142,
        10144,
        10145,
        10149,
    ]

    if plate_id in REMAPPED_PLATES:
        return UVIS_R(
            sequence_version=sequence_version,
            plate_id=plate_id,
            plate_sample_no_list=REMAP,
            reference_after_sample_list=REREF,
            reference_mode=reference_mode,
            custom_position=custom_position,
            spec_n_avg=spec_n_avg,
            spec_int_time_ms=spec_int_time_ms,
            duration_sec=duration_sec,
            specref_code=specref_code,
            led_type=led_type,
            led_date=led_date,
            led_names=led_names,
            led_wavelengths_nm=led_wavelengths_nm,
            led_intensities_mw=led_intensities_mw,
            toggle_is_shutter=toggle_is_shutter,
        )
    else:
        return UVIS_R(
            sequence_version=sequence_version,
            plate_id=plate_id,
            plate_sample_no_list=MAP,
            reference_after_sample_list=REF,
            reference_mode=reference_mode,
            custom_position=custom_position,
            spec_n_avg=spec_n_avg,
            spec_int_time_ms=spec_int_time_ms,
            duration_sec=duration_sec,
            specref_code=specref_code,
            led_type=led_type,
            led_date=led_date,
            led_names=led_names,
            led_wavelengths_nm=led_wavelengths_nm,
            led_intensities_mw=led_intensities_mw,
            toggle_is_shutter=toggle_is_shutter,
        )