"""Tests for the UV-Vis page's pure logic and spectrum loading."""

import asyncio

import numpy as np
import pytest

from helao.ui.shared import uvvis

WL = np.linspace(300.0, 1100.0, 801)  # 1 nm grid


def _proc(
    n, run_use="data", plate=10201, run_id="06ab5756-81ff-733a-8000-81043372c76c"
):
    return {
        "process_name": "R_UVVIS",
        "process_uuid": f"p{n}",
        "run_id": run_id,
        "run_use": run_use,
        "sequence_uuid": "s1",
        "samples_in": [
            {
                "plate_id": plate,
                "sample_no": n,
                "global_label": f"legacy__solid__{plate}_{n}",
            }
        ],
        "files": [
            {
                "file_type": "spec_r_parquet__file",
                "file_name": f"f{n}.parquet",
                "action_uuid": f"a{n}",
            }
        ],
    }


def test_run_timestamp_reads_uuid_extensions_seconds_not_rfc_milliseconds() -> None:
    """RFC 9562 reads this run_id as 2202; its sequence ran 2026-09-24 12:10."""
    stamp = uvvis.run_timestamp("06ab5756-81ff-733a-8000-81043372c76c")
    assert stamp is not None and (stamp.year, stamp.month, stamp.day) == (2026, 9, 24)
    label = uvvis.run_label("06ab5756-81ff-733a-8000-81043372c76c")
    assert label.startswith("2026-09-24 ") and label.endswith(
        "06ab5756-81ff-733a-8000-81043372c76c"
    )
    assert uvvis.run_label("not-a-uuid") == "not-a-uuid"


def test_records_take_the_sample_on_this_plate_and_need_a_spectrum_file() -> None:
    other_plate = _proc(2, plate=999)
    no_file = {**_proc(3), "files": []}
    not_uvvis = {**_proc(4), "process_name": "xrfs_nostds"}
    records = uvvis.records_from_processes(
        [_proc(1), other_plate, no_file, not_uvvis], 10201
    )
    assert [(r.sample_no, r.action_uuid, r.file_name) for r in records] == [
        (1, "a1", "f1.parquet")
    ]


def test_window_mean_averages_inside_and_falls_back_to_the_nearest_point() -> None:
    intensity = WL.copy()  # intensity equals wavelength
    assert uvvis.window_mean(WL, intensity, 500.0, 600.0) == pytest.approx(550.0)
    assert uvvis.window_mean(WL, intensity, 600.0, 500.0) == pytest.approx(550.0)
    # Zero width between grid points: the nearest point, not NaN.
    assert uvvis.window_mean(WL, intensity, 700.4, 700.4) == pytest.approx(700.0)
    stack = np.vstack([intensity, 2 * intensity])
    assert uvvis.window_means(WL, stack, 500.0, 600.0) == pytest.approx([550.0, 1100.0])
    assert uvvis.window_means(WL, stack, 700.4, 700.4) == pytest.approx([700.0, 1400.0])


def test_range_stats_cover_350_to_1000_nm_only() -> None:
    stats = uvvis.range_stats(WL, WL.copy(), *uvvis.STATS_RANGE)
    assert stats["min"] == pytest.approx(350.0)
    assert stats["max"] == pytest.approx(1000.0)
    assert stats["mean"] == pytest.approx(675.0)
    assert stats["stdev"] == pytest.approx(np.std(np.arange(350.0, 1001.0)))
    # A range with no grid point takes the nearest one, like the window mean.
    assert uvvis.range_stats(WL, WL, 2000.0, 3000.0)["mean"] == pytest.approx(1100.0)


class _FakeClient:
    """Answers read_action and read_plottable_data like the metadata API."""

    def __init__(self, fail_shared_name_for=()):
        self.action_reads = 0
        self.fail_shared_name_for = set(fail_shared_name_for)

    async def read_action(self, action_uuid):
        self.action_reads += 1
        return {
            "action_name": (
                "special"
                if action_uuid in self.fail_shared_name_for
                else "acquire_spec_adv"
            )
        }

    async def read_plottable_data(self, request_body):
        if (
            request_body["action_uuid"] in self.fail_shared_name_for
            and request_body["action_name"] != "special"
        ):
            raise RuntimeError("500")
        n = int(request_body["action_uuid"][1:])
        return {
            "data": {"series": {"wl_nm": WL.tolist(), "intensity": (WL * n).tolist()}}
        }


def test_load_spectra_reads_one_action_name_and_caches() -> None:
    uvvis.reset_cache()
    records = uvvis.records_from_processes([_proc(1), _proc(2), _proc(3)], 10201)
    client = _FakeClient(fail_shared_name_for={"a3"})
    seen = []

    async def progress(done, total):
        seen.append((done, total))

    assert asyncio.run(uvvis.load_spectra(client, records, progress)) == 0
    # One shared lookup, plus one for the action that needed its own name.
    assert client.action_reads == 2
    assert seen[-1] == (3, 3)
    wl, stack, kept = uvvis.stack_for(records)
    assert [r.sample_no for r in kept] == [1, 2, 3]
    assert stack[:, 0] == pytest.approx([300.0, 600.0, 900.0])
    # A second load fetches nothing.
    assert asyncio.run(uvvis.load_spectra(client, records)) == 0
    assert client.action_reads == 2
    uvvis.reset_cache()
