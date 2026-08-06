"""P7b task 3: wire-consumer conformance for hte's `add_points` implementations,
fed the decoded payload the real `VisSubscriber.IOloop_data` would hand them,
built from `harness/ws_frames` (real encoder -> real WsSubscriber decoder,
never a hand-built dict standing in for the wire).

12 hte visualizer modules define `add_points`; **10** are conformance-tested
here. Two are excluded, both measured rather than assumed:

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

- ws_live (`LiveVisualizer`): `co2_vis`, `syringe_vis`, `pressure_vis`,
  `tec_vis`, `temp_vis`, `mfc_vis` all initialize `data_dict = {k: [] for k in
  self.data_dict_keys}` then do an unconditional `data_dict[datalab].append`
  for any wire key that isn't `"sim_dict"`/`"tec_vals"` -- an unrecognized
  key is a `KeyError`. Only `power_supply_vis` guards with `if datalab in
  data_dict`.
- ws_data (`ActionVisualizer`): `biologic_vis`, `gamry_vis`, `nidaqmx_vis`
  all guard with `if data_label in self.data_dict_keys` -- an unrecognized
  column (e.g. a composition string) is silently ignored, matching the
  Reflex ingest layer's `normalize_data_package` semantics.

`power_supply_vis` carries a genuine pre-existing defect, found by running
its real code rather than assumed: `data_dict_keys = ["t_s", "current_a"]`
(no `"datetime"`), but `add_points` unconditionally does
`data_dict["datetime"].append(...)` once per package -- so it raises
`KeyError: 'datetime'` on **every** call, including the happy path. Pinned
below, not fixed (production code is out of scope for this slice); flag to
the team separately.

Run directly (`python -m pytest` on this file) -- the hte suite is not part
of `run_unit_tests.py`.
"""

import asyncio
import importlib

import pytest
from bokeh.document import Document

from harness import ws_frames as wf


class _FakeVis:
    """The attributes `VisSubscriber.__init__` reads, plus a document.

    `server_cfg["params"]` is the VIS server's own config (num_channels
    etc.); `world_cfg["servers"][key]["params"]` is the ACTION server's
    config (devices/dev_ai/dev_monitor etc.) -- two different injection
    points, per vis_subscriber.py:206 vs each panel's own
    `self.serv_config.get("params", ...)` reads.
    """

    def __init__(self, doc, vis_params=None, servers=None):
        self.doc = doc
        self.server_cfg = {"params": vis_params or {}}
        self.world_cfg = {"servers": servers or {}}


def _servers(serv_key: str, action_params: dict | None = None) -> dict:
    return {
        serv_key: {
            "host": "127.0.0.1",
            "port": 8004,
            "params": action_params or {},
        }
    }


def _build(module, serv_key: str, vis_params=None, action_params=None):
    """Construct a visualizer and stop its ingest task before it can open a
    socket to a server that is not there (recipe shared with
    test_pstat_vis_axis_selectors.py)."""
    vis = module.C_vis(
        _FakeVis(
            Document(), vis_params=vis_params, servers=_servers(serv_key, action_params)
        ),
        serv_key,
    )
    vis.IOloop_data_run = False
    vis.IOtask.cancel()
    return vis


async def _decoded_live(numeric: dict, strings: dict | None = None) -> dict:
    payload = wf.build_live_payload(numeric=numeric, strings=strings or {})
    _, decoded = await wf.roundtrip("ws_live", "base_api", payload=payload)
    return decoded


async def _decoded_data(numeric: dict, strings: dict, action_name: str) -> object:
    payload = wf.build_data_payload(
        numeric=numeric, strings=strings, action_name=action_name
    )
    _, decoded = await wf.roundtrip("ws_data", "base_api", payload=payload)
    return decoded


def _import(modname):
    return importlib.import_module(f"helao.deploy.hte.servers.visualizer.{modname}")


# --- anti-vacuity guard -----------------------------------------------------


def test_targeted_module_set_matches_disk_and_is_documented():
    """12 hte modules define add_points; 10 are conformance-tested; the 2
    exclusions are named and justified in the module docstring above, not
    silently dropped."""
    import subprocess

    out = subprocess.run(
        ["grep", "-rl", "def add_points", "helao/deploy/hte/servers/visualizer"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    found = {line.split("/")[-1][: -len(".py")] for line in out.strip().splitlines()}
    assert len(found) == 12, found
    excluded = {"sample_vis", "spec_vis"}
    tested = found - excluded
    assert len(tested) == 10, tested
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


def test_syringe_vis_ingests_recognized_and_raises_on_unrecognized():
    module = _import("syringe_vis")

    async def _run():
        vis = _build(module, "SYRINGE0")
        assert vis.connected
        before = len(vis.datasource.data["co2_ppm"])
        decoded = await _decoded_live({"co2_ppm": 1.5})
        vis.add_points([decoded])
        assert len(vis.datasource.data["co2_ppm"]) == before + 1

        bad = await _decoded_live({}, strings={wf.LIVE_STRING_LABEL: "x"})
        with pytest.raises(KeyError):
            vis.add_points([bad])

    asyncio.run(_run())


def test_temp_vis_ingests_recognized_and_raises_on_unrecognized():
    module = _import("temp_vis")

    async def _run():
        vis = _build(module, "TEMP0", action_params={"dev_monitor": {"TC0": {}}})
        assert vis.connected
        assert vis.data_dict_keys == ["datetime", "TC0"]
        before = len(vis.datasource.data["TC0"])
        decoded = await _decoded_live({"TC0": 22.5})
        vis.add_points([decoded])
        assert len(vis.datasource.data["TC0"]) == before + 1
        assert vis.datasource.data["TC0"][-1] == 22.5

        bad = await _decoded_live({}, strings={wf.LIVE_STRING_LABEL: "x"})
        with pytest.raises(KeyError):
            vis.add_points([bad])

    asyncio.run(_run())


def test_pressure_vis_ingests_recognized_and_raises_on_unrecognized():
    module = _import("pressure_vis")

    async def _run():
        vis = _build(module, "PRESSURE0", action_params={"dev_ai": {"AI0": {}}})
        assert vis.connected
        assert vis.ai_keys == ["AI0"]
        before = len(vis.datasource.data["AI0"])
        decoded = await _decoded_live({"AI0": 14.7})
        vis.add_points([decoded])
        assert len(vis.datasource.data["AI0"]) == before + 1
        assert vis.datasource.data["AI0"][-1] == 14.7
        # rolling-mean column self-computes to the same length, not raised
        assert len(vis.datasource.data["AI0_mean"]) == before + 1

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


def test_power_supply_vis_raises_on_every_call_preexisting_defect():
    """Measured, pinned pre-existing defect: data_dict_keys omits "datetime"
    but add_points unconditionally appends to it, so even a fully-recognized
    payload raises. This is NOT a P7b regression -- it is characterized here
    so the wire-conformance gate does not silently claim this panel works."""
    module = _import("power_supply_vis")

    async def _run():
        vis = _build(module, "PWR0")
        assert vis.connected
        assert "datetime" not in vis.data_dict_keys
        decoded = await _decoded_live({"current_a": 1.2})
        with pytest.raises(KeyError, match="datetime"):
            vis.add_points([decoded])

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
    test_syringe_vis_ingests_recognized_and_raises_on_unrecognized()
    test_temp_vis_ingests_recognized_and_raises_on_unrecognized()
    test_pressure_vis_ingests_recognized_and_raises_on_unrecognized()
    test_tec_vis_ingests_recognized_via_tec_vals_and_raises_on_unrecognized()
    test_mfc_vis_ingests_recognized_and_raises_on_unrecognized()
    test_power_supply_vis_raises_on_every_call_preexisting_defect()
    test_biologic_vis_ingests_recognized_columns_and_drops_string()
    test_gamry_vis_ingests_recognized_columns_and_drops_string()
    test_nidaqmx_vis_ingests_recognized_columns_and_drops_string()
    print("ALL HTE TEST_VIS_WS_PARITY TESTS PASS")
