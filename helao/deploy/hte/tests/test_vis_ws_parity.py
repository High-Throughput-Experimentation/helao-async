"""P7b task 3: wire-consumer conformance for hte's `add_points` implementations,
fed the decoded payload the real `VisSubscriber.IOloop_data` would hand them,
built from `harness/ws_frames` (real encoder -> real WsSubscriber decoder,
never a hand-built dict standing in for the wire).

9 hte visualizer modules define `add_points`; **7** are conformance-tested
here. pressure_vis and temp_vis moved to helao/deploy/base (tests in
base/tests/test_live_vis_ws_parity.py). Two are excluded, both measured rather than assumed:

- `sample_vis.add_points(self)` takes no payload argument at all -- it is
  driven by a custom `IOloop_data` that does a `list_new_samples` *private
  dispatch* on message arrival, not the `add_points(datapackage_list)`
  contract every other panel shares. It has no wire-decode role for
  `/ws_data`/`/ws_live` to conform to.
- `spec_vis.__init__` calls the synchronous `private_dispatcher(..., "get_wl",
  ...)` against the live action server *during construction*, before
  `add_points` ever runs -- an RPC-then-HTTP round trip this test-and-harness
  slice has no server to answer (P7b is explicitly test-and-harness only, no
  production code). Its `add_points` logic is already characterized by the
  same pattern proven for gamry_vis/nidaqmx_vis/biologic_vis below (cherry-
  picks `epoch_s`/`ch_*` keys, ignores the rest without raising).

Two families, two different unrecognized-key tolerances, measured and pinned
rather than assumed uniform (a correction to the plan's implicit "does not
raise" premise for the ws_live family):

- ws_live (`LiveVisualizer`): `co2_vis`, `tec_vis`, `mfc_vis` (and base's
  `pressure_vis`, `temp_vis`) all initialize `data_dict = {k: [] for k in
  self.data_dict_keys}` then do an unconditional `data_dict[datalab].append`
  for any wire key that isn't `"sim_dict"`/`"tec_vals"` -- an unrecognized
  key is a `KeyError`. Only `power_supply_vis` guards with `if datalab in
  data_dict`.
- ws_data (`ActionVisualizer`): `biologic_vis`, `gamry_vis`, `nidaqmx_vis`
  all guard with `if data_label in self.data_dict_keys` -- an unrecognized
  column (e.g. a composition string) is silently ignored, matching the
  Reflex ingest layer's `normalize_data_package` semantics.

`power_supply_vis` carried a genuine defect, found by running its real code
rather than assumed: `data_dict_keys` was `["t_s", "current_a"]` with no
`"datetime"`, while `add_points` appends to `data_dict["datetime"]` once per
package and the panel's own plots use it as the x axis -- so it raised
`KeyError: 'datetime'` on **every** call, including the happy path. Fixed by
adding the key first in the list, matching all six sibling live panels; the
test below now asserts the payload lands instead of pinning the crash.

Run directly (`python -m pytest` on this file) -- the hte suite is not part
of `run_unit_tests.py`.
"""

import asyncio
import importlib

from helao.helpers.server_modules import import_path, locate, module_file

import pytest

from harness import ws_frames as wf
from helao.deploy.base.tests.test_live_vis_ws_parity import (
    _FakeVis,
    _servers,
    _build,
    _decoded_live,
    _decoded_data,
)


def _import(modname):
    owner = locate(modname, "bokeh", own="hte")[0]
    assert owner is not None, modname
    return importlib.import_module(import_path(module_file(owner, modname, "bokeh")))


# --- anti-vacuity guard -----------------------------------------------------


def test_targeted_module_set_matches_disk_and_is_documented():
    """9 hte modules define add_points; 7 are conformance-tested; the 2
    exclusions are named and justified in the module docstring above, not
    silently dropped."""
    from pathlib import Path

    hte = Path("helao/deploy/hte/servers")
    files = hte.glob("*/bokeh/*.py")
    found = {p.stem for p in files if "def add_points" in p.read_text(encoding="utf-8")}
    assert len(found) == 9, found
    excluded = {"sample_vis", "spec_vis"}
    tested = found - excluded
    assert len(tested) == 7, tested
    assert excluded <= found


# --- ws_live family: unconditional-append panels (KeyError on unknown key) --


def test_co2_vis_ingests_recognized_and_raises_on_unrecognized():
    module = _import("co2_vis")

    async def _run():
        vis = _build(module, "CO2")
        assert vis.connected
        before = len(vis.datasource.data["co2_ppm"])
        decoded = await _decoded_live({"co2_ppm": 410.0})
        vis.add_points([decoded])
        assert len(vis.datasource.data["co2_ppm"]) == before + 1
        assert vis.datasource.data["co2_ppm"][-1] == 410.0

        bad = await _decoded_live({}, strings={wf.LIVE_STRING_LABEL: "x"})
        with pytest.raises(KeyError):
            vis.add_points([bad])

    asyncio.run(_run())


def test_tec_vis_ingests_recognized_via_tec_vals_and_raises_on_unrecognized():
    module = _import("tec_vis")

    async def _run():
        vis = _build(module, "TEC0")
        assert vis.connected
        before = len(vis.datasource.data["object_temperature"])
        decoded = await _decoded_live(
            {
                "tec_vals": {
                    "enabled_status": 1,
                    "object_temperature": 25.0,
                    "target_object_temperature": 26.0,
                    "output_current": 0.5,
                    "temperature_is_stable": 1,
                }
            }
        )
        vis.add_points([decoded])
        assert len(vis.datasource.data["object_temperature"]) == before + 1
        assert vis.datasource.data["object_temperature"][-1] == 25.0

        bad = await _decoded_live({}, strings={wf.LIVE_STRING_LABEL: "x"})
        with pytest.raises(KeyError):
            vis.add_points([bad])

    asyncio.run(_run())


def test_mfc_vis_ingests_recognized_and_raises_on_unrecognized():
    """mfc_vis flattens a per-device nested dict (datalab -> {suffix: value})
    into `device__suffix` columns -- every suffix must be present for
    ColumnDataSource.stream's equal-length requirement, matching the real
    MFC driver's per-tick publish shape."""
    module = _import("mfc_vis")

    async def _run():
        vis = _build(module, "MFC0", action_params={"devices": {"MFC1": {}}})
        assert vis.connected
        key = "MFC1__mass_flow"
        before = len(vis.datasource.data[key])
        decoded = await _decoded_live(
            {
                "MFC1": {
                    "setpoint": 10.0,
                    "control_point": "mass flow",
                    "gas": "Ar",
                    "mass_flow": 5.0,
                    "pressure": 14.7,
                    "temperature": 25.0,
                    "volumetric_flow": 5.0,
                    "hold_valve": 0,
                    "lock_display": 0,
                    "acquire_time": 1.0,
                }
            }
        )
        vis.add_points([decoded])
        assert len(vis.datasource.data[key]) == before + 1
        assert vis.datasource.data[key][-1] == 5.0
        # rolling-mean columns self-compute to the same length
        assert len(vis.datasource.data["MFC1__mass_flow_mean"]) == before + 1

        bad = await _decoded_live({}, strings={wf.LIVE_STRING_LABEL: "x"})
        with pytest.raises(KeyError):
            vis.add_points([bad])

    asyncio.run(_run())


def test_power_supply_vis_ingests_a_recognized_payload():
    """Was a crash on every call: add_points appends one "datetime" per package
    and the plots use it as the x axis, but the key was missing from
    data_dict_keys. Asserts the streamed values, not merely that nothing raised
    -- a panel that silently dropped the payload would satisfy the latter."""
    module = _import("power_supply_vis")

    async def _run():
        vis = _build(module, "PWR0")
        assert vis.connected
        assert vis.data_dict_keys[0] == "datetime"
        decoded = await _decoded_live({"t_s": 0.5, "current_a": 1.2})
        vis.add_points([decoded])
        assert list(vis.datasource.data["current_a"]) == [1.2]
        assert list(vis.datasource.data["t_s"]) == [0.5]
        assert len(vis.datasource.data["datetime"]) == 1

    asyncio.run(_run())


# --- ws_data family: guarded panels (extra column silently ignored) --------


def test_biologic_vis_ingests_recognized_columns_and_drops_string():
    module = _import("biologic_vis")

    async def _run():
        vis = _build(module, "BIOLOGIC0", vis_params={"num_channels": 1})
        assert vis.connected
        ds = vis.channel_datasources[0]
        before = len(ds.data["t_s"])
        decoded = await _decoded_data(
            numeric={
                "channel": [0, 0],
                "t_s": [0.0, 1.0],
                "Ewe_V": [0.1, 0.2],
                "I_A": [0.01, 0.02],
            },
            strings={wf.STRING_COLUMN: [wf.STRING_VALUES[0]] * 2},
            action_name="run_CA",
        )
        vis.add_points([decoded])
        assert len(ds.data["t_s"]) == before + 2
        assert ds.data["Ewe_V"][-2:] == [0.1, 0.2]
        assert wf.STRING_COLUMN not in ds.data

    asyncio.run(_run())


def test_gamry_vis_ingests_recognized_columns_and_drops_string():
    module = _import("gamry_vis")

    async def _run():
        vis = _build(module, "GAMRY0", vis_params={"num_channels": 1})
        assert vis.connected
        before = len(vis.datasource.data["t_s"])
        decoded = await _decoded_data(
            numeric={"t_s": [0.0, 1.0], "I_A": [0.01, 0.02]},
            strings={wf.STRING_COLUMN: [wf.STRING_VALUES[0]] * 2},
            action_name="run_CA",
        )
        vis.add_points([decoded])
        assert len(vis.datasource.data["t_s"]) == before + 2
        assert vis.datasource.data["I_A"][-2:] == [0.01, 0.02]
        assert wf.STRING_COLUMN not in vis.datasource.data

    asyncio.run(_run())


def test_nidaqmx_vis_ingests_recognized_columns_and_drops_string():
    """Unlike gamry_vis/biologic_vis, nidaqmx_vis's data_dict is never
    backfilled for keys the message didn't carry -- ColumnDataSource.stream's
    equal-length requirement means every one of its 19 declared columns needs
    a same-length entry, matching the real 9-cell driver's per-tick shape."""
    module = _import("nidaqmx_vis")

    async def _run():
        vis = _build(module, "NIDAQMX0")
        assert vis.connected
        before = len(vis.datasource.data["t_s"])
        numeric = {"t_s": [0.0, 1.0]}
        for i in range(1, 10):
            numeric[f"Icell{i}_A"] = [0.1 * i, 0.2 * i]
            numeric[f"Ecell{i}_V"] = [1.0 * i, 1.1 * i]
        decoded = await _decoded_data(
            numeric=numeric,
            strings={wf.STRING_COLUMN: [wf.STRING_VALUES[0]] * 2},
            action_name="cellIV",
        )
        vis.add_points([decoded])
        assert len(vis.datasource.data["t_s"]) == before + 2
        assert vis.datasource.data["Icell1_A"][-2:] == [0.1, 0.2]
        assert wf.STRING_COLUMN not in vis.datasource.data

    asyncio.run(_run())


if __name__ == "__main__":
    test_targeted_module_set_matches_disk_and_is_documented()
    test_co2_vis_ingests_recognized_and_raises_on_unrecognized()
    test_tec_vis_ingests_recognized_via_tec_vals_and_raises_on_unrecognized()
    test_mfc_vis_ingests_recognized_and_raises_on_unrecognized()
    test_power_supply_vis_ingests_a_recognized_payload()
    test_biologic_vis_ingests_recognized_columns_and_drops_string()
    test_gamry_vis_ingests_recognized_columns_and_drops_string()
    test_nidaqmx_vis_ingests_recognized_columns_and_drops_string()
    print("ALL HTE TEST_VIS_WS_PARITY TESTS PASS")
