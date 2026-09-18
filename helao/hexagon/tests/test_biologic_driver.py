"""setup/start/get_data/stop/cleanup against the simulated DLL."""

import asyncio

import pytest

from helao.core.drivers.helao_driver import DriverResponseType, DriverStatus
from helao.deploy.hte.drivers.pstat.biologic import data, sim, vendor
from helao.deploy.hte.drivers.pstat.biologic import technique as bt
from helao.deploy.hte.drivers.pstat.biologic import driver as driver_module
from helao.deploy.hte.drivers.pstat.biologic.driver import BiologicDriver

CONFIG = {
    "address": "192.168.200.100",
    "num_channels": 2,
    "simulate": True,
    "sdk_path": "/unused",
}

CA = dict(
    Vval__V=0.5,
    Tval__s=1.0,
    AcqInterval__s=0.01,
    AcqInterval__A=10.0,
    IRange="AUTO",
    ERange="AUTO",
    Bandwidth="BW4",
    channel=0,
)


@pytest.fixture
def driver():
    sim.set_sim_config(sim.SimConfig())
    d = BiologicDriver(dict(CONFIG))
    d.connect()
    try:
        yield d
    finally:
        d.shutdown()
        sim.set_sim_config(sim.SimConfig())


def setup(driver, name="CA", **overrides):
    return driver.setup(technique=bt.BIOTECHS[name], action_params={**CA, **overrides})


def run_to_completion(driver, channel=0, limit=50):
    """Poll until the driver says done, returning the concatenated columns."""
    collected: dict[str, list] = {}
    for _ in range(limit):
        resp = asyncio.run(driver.get_data(channel))
        for key, values in (resp.data or {}).items():
            collected.setdefault(key, []).extend(values)
        if resp.message == "done":
            return collected, resp
    raise AssertionError("never finished")


# --- setup ------------------------------------------------------------------


def test_setup_claims_the_channel(driver):
    assert setup(driver).response == DriverResponseType.success
    assert driver.channel == 0


def test_setup_refuses_a_second_claim_and_names_the_holder(driver):
    setup(driver)
    resp = driver.setup(technique=bt.BIOTECHS["CA"], action_params={**CA, "channel": 1})
    assert resp.response == DriverResponseType.failed
    assert resp.status == DriverStatus.busy
    assert "0" in (resp.message or "")


def test_setup_refuses_a_channel_outside_num_channels(driver):
    resp = driver.setup(technique=bt.BIOTECHS["CA"], action_params={**CA, "channel": 9})
    assert resp.status == DriverStatus.error


def test_setup_resolves_the_ecc_by_board_type(driver):
    sim.set_sim_config(sim.SimConfig(board_type=vendor.BOARD_TYPE.ESSENTIAL))
    d = BiologicDriver(dict(CONFIG))
    d.connect()
    try:
        setup(d)
        assert sim.loaded_ecc_files() == ["ca.ecc"]
    finally:
        d.shutdown()


def test_setup_on_a_premium_board_loads_the_four_suffixed_ecc(driver):
    setup(driver)
    assert sim.loaded_ecc_files() == ["ca4.ecc"]


def test_setup_loads_the_trigger_first_when_ttl_is_requested(driver):
    driver.setup(
        technique=bt.BIOTECHS["CA"],
        action_params={**CA, "TTLwait": 1},
    )
    driver.start_channel(0, {"ttl": "in", "ttl_logic": 1, "ttl_duration": 1.0})
    assert sim.loaded_ecc_files() == ["TI4.ecc", "ca4.ecc"]


def test_start_fails_when_the_technique_list_reads_back_wrong(driver):
    """easy-biologic loaded and hoped. If the trigger is not at index 0 the
    measurement would run untriggered."""
    sim.set_sim_config(sim.SimConfig(technique_ids_override=[vendor.TECH_ID.CA]))
    resp = driver.setup(technique=bt.BIOTECHS["CA"], action_params=CA)
    assert resp.response == DriverResponseType.success  # setup alone is fine
    start_resp = driver.start_channel(
        0, {"ttl": "in", "ttl_logic": 1, "ttl_duration": 1.0}
    )
    assert start_resp.response == DriverResponseType.failed


def test_a_failed_setup_releases_the_claim(driver):
    sim.set_sim_config(sim.SimConfig(fail_on={"BL_LoadTechnique": -400}))
    assert setup(driver).response == DriverResponseType.failed
    assert driver.channel is None


def test_setup_accepts_output_dir_and_ignores_it(driver):
    """Signature parity with the OLE backend, which ships vendor artifacts
    there. EClib1 writes no files."""
    resp = driver.setup(
        technique=bt.BIOTECHS["CA"], action_params=CA, output_dir="/tmp/nope"
    )
    assert resp.response == DriverResponseType.success


# --- start ------------------------------------------------------------------


def test_start_returns_a_start_time_and_busy(driver):
    setup(driver)
    resp = driver.start_channel(0)
    assert resp.status == DriverStatus.busy
    assert resp.data["start_time"] > 0


def test_start_without_setup_fails(driver):
    assert driver.start_channel(0).response == DriverResponseType.failed


def test_start_on_a_running_channel_reloads_it_and_proceeds(driver):
    """No longer a refusal. `start_channel` reloads the whole plan with
    `BL_LoadTechnique(first=True)` before starting, which halts whatever was
    running, so a non-STOP state at that point is a state the driver itself
    is about to replace. A channel EC-Lab holds is refused at `connect`
    (`ERR_GEN_ECLAB_LOADED`), not here."""
    sim.set_sim_config(sim.SimConfig(polls_until_stop=99))
    setup(driver)
    driver.start_channel(0)
    assert driver.start_channel(0).response == DriverResponseType.success


def test_a_failed_start_releases_the_claim_and_fails_get_data(driver):
    """The exception from BL_StartChannel must not leave the claim, technique
    or tracker set (see start_channel's except clause) -- left set, a
    subsequent get_data would believe a never-started channel is running and
    report "measuring" with no error, an empty success instead of a fault."""
    setup(driver)
    sim.set_sim_config(sim.SimConfig(fail_on={"BL_StartChannel": -13}))
    start_resp = driver.start_channel(0)
    assert start_resp.response == DriverResponseType.failed
    assert driver.channel is None
    resp = asyncio.run(driver.get_data(0))
    assert resp.response == DriverResponseType.failed


def test_an_untriggered_start_keeps_the_starting_cap(driver):
    setup(driver)
    driver.start_channel(0)
    assert driver._tracker.max_starting_polls == data.MAX_STARTING_POLLS


def test_a_trigger_in_start_lifts_the_starting_cap(driver):
    """A channel parked on a requested Trigger In waits on an external
    instrument, deliberately indefinitely -- MAX_STARTING_POLLS must not
    abort that wait."""
    setup(driver)
    driver.start_channel(0, {"ttl": "in", "ttl_logic": 1, "ttl_duration": 1.0})
    assert driver._tracker.max_starting_polls is None


def test_a_trigger_out_start_keeps_the_starting_cap(driver):
    """Trigger Out pulses for its own finite Trigger_Duration and returns --
    it waits on nothing, so the firmware-start-failure detector must stay
    armed for it, unlike Trigger In."""
    setup(driver)
    driver.start_channel(0, {"ttl": "out", "ttl_logic": 1, "ttl_duration": 1.0})
    assert driver._tracker.max_starting_polls == data.MAX_STARTING_POLLS


# --- get_data ---------------------------------------------------------------


def test_the_first_poll_before_the_firmware_runs_is_not_done(driver):
    """StartChannel returns before the channel is running; the old driver's
    State == 0 test ended the action here."""
    sim.set_sim_config(sim.SimConfig(idle_polls_before_run=2))
    setup(driver)
    driver.start_channel(0)
    resp = asyncio.run(driver.get_data(0))
    assert resp.message == "measuring"


def test_get_data_reports_a_bounded_tracker_as_a_failure(driver, monkeypatch):
    """RunTracker's "error" (the never-reaches-RUN bound) must turn into a
    failed DriverResponse, not "measuring" forever."""
    setup(driver)
    driver.start_channel(0)
    monkeypatch.setattr(driver._tracker, "observe", lambda *a: "error")
    resp = asyncio.run(driver.get_data(0))
    assert resp.response == DriverResponseType.failed


def test_a_ca_run_emits_exactly_the_frozen_columns(driver):
    setup(driver)
    driver.start_channel(0)
    columns, _ = run_to_completion(driver)
    assert set(columns) >= set(data.COLUMNS["CA"])


def test_the_underscore_prefixed_current_values_are_still_emitted(driver):
    setup(driver)
    driver.start_channel(0)
    columns, _ = run_to_completion(driver)
    assert "_State" in columns
    assert "_TimeBase" in columns


def test_every_column_has_the_same_length(driver):
    """A ragged dict makes the chart silently drop a trace."""
    setup(driver)
    driver.start_channel(0)
    columns, _ = run_to_completion(driver)
    lengths = {len(v) for v in columns.values()}
    assert len(lengths) == 1


def test_the_tail_is_drained_so_no_rows_are_lost(driver):
    sim.set_sim_config(sim.SimConfig(rows_per_poll=4, polls_until_stop=3))
    setup(driver)
    driver.start_channel(0)
    columns, _ = run_to_completion(driver)
    assert len(columns["t_s"]) == sim.rows_emitted()


def test_the_drain_is_bounded(driver):
    """A channel that keeps producing rows must not hold get_data forever."""
    sim.set_sim_config(
        sim.SimConfig(rows_per_poll=1, polls_until_stop=1, endless_tail=True)
    )
    setup(driver)
    driver.start_channel(0)
    resp = asyncio.run(driver.get_data(0))
    for _ in range(3):
        resp = asyncio.run(driver.get_data(0))
    assert len(resp.data["t_s"]) <= data.MAX_DRAINS_PER_CALL + 1


def test_an_eis_run_emits_both_processes_into_one_column_set(driver):
    setup(driver, "PEIS", **_PEIS)
    driver.start_channel(0)
    columns, _ = run_to_completion(driver)
    assert set(columns) >= set(data.COLUMNS["PEIS"])
    assert set(columns["process"]) == {0, 1}


def test_dropped_points_are_warned_about_and_not_a_column(driver, caplog):
    sim.set_sim_config(sim.SimConfig(irq_skipped=7))
    setup(driver)
    driver.start_channel(0)
    with caplog.at_level("WARNING"):
        columns, _ = run_to_completion(driver)
    assert any("7" in r.message for r in caplog.records)
    assert "IRQskipped" not in columns


def test_get_data_on_an_unclaimed_channel_fails(driver):
    assert asyncio.run(driver.get_data(1)).response == DriverResponseType.failed


def test_get_data_does_not_block_the_event_loop(driver):
    """Every vendor call goes to the client's worker thread; get_data awaits
    it. easy-biologic's *_async were async def wrappers around blocking calls."""
    setup(driver)
    driver.start_channel(0)

    async def racer():
        ticks = 0

        async def tick():
            nonlocal ticks
            for _ in range(20):
                ticks += 1
                await asyncio.sleep(0)

        await asyncio.gather(driver.get_data(0), tick())
        return ticks

    assert asyncio.run(racer()) == 20


# --- stop / cleanup ---------------------------------------------------------


def test_stop_ends_the_claimed_channel(driver):
    sim.set_sim_config(sim.SimConfig(polls_until_stop=99))
    setup(driver)
    driver.start_channel(0)
    assert driver.stop(0).response == DriverResponseType.success
    assert driver.get_status(0).status == DriverStatus.ok


def test_stop_with_none_stops_the_claimed_channel(driver):
    sim.set_sim_config(sim.SimConfig(polls_until_stop=99))
    setup(driver)
    driver.start_channel(0)
    assert driver.stop(None).response == DriverResponseType.success


def test_stop_with_none_and_nothing_claimed_is_a_successful_no_op(driver):
    assert driver.stop(None).response == DriverResponseType.success


def test_stop_is_reentrant(driver):
    """The old driver guarded this with a `self.stopping` flag; the client's
    worker thread is what makes it non-reentrant now."""
    sim.set_sim_config(sim.SimConfig(polls_until_stop=99))
    setup(driver)
    driver.start_channel(0)
    assert driver.stop(0).response == DriverResponseType.success
    assert driver.stop(0).response == DriverResponseType.success


def test_cleanup_releases_the_claim(driver):
    setup(driver)
    assert driver.cleanup(0).response == DriverResponseType.success
    assert driver.channel is None


def test_cleanup_refuses_while_the_channel_runs(driver):
    sim.set_sim_config(sim.SimConfig(polls_until_stop=99))
    setup(driver)
    driver.start_channel(0)
    assert driver.cleanup(0).response == DriverResponseType.failed


def test_cleanup_allows_the_next_action_to_claim(driver):
    setup(driver)
    driver.cleanup(0)
    assert setup(driver, channel=1).response == DriverResponseType.success


def test_shutdown_stops_and_releases_a_running_channel(driver):
    sim.set_sim_config(sim.SimConfig(polls_until_stop=99))
    setup(driver)
    driver.start_channel(0)
    driver.shutdown()
    assert driver.channel is None
    assert driver.ready is False


_PEIS = dict(
    Vinit__V=0.0,
    Vamp__V=0.01,
    Finit__Hz=1000.0,
    Ffinal__Hz=1e6,
    FrequencyNumber=60,
    Duration__s=0.0,
    AcqInterval__s=0.1,
    SweepMode="log",
    Repeats=10,
    DelayFraction=0.1,
)


def test_start_warns_but_proceeds_when_the_channel_never_stops(
    driver, caplog, monkeypatch
):
    """Station failure, 2026-09-18: `run_OCV` raised "channel 0 is busy" here.

    `setup`'s own `BL_LoadTechnique(first=True)` halts whatever the channel
    was running -- the firmware logged "halt experiment"/"end protocol"
    immediately before the refusal -- so the state this reads can be the tail
    of the driver's own load. Refusing after the destructive step protects
    nothing; `BL_StartChannel` is what gets to say no. This is also the
    branch where `_ensure_stopped`'s wait expires: a channel that never
    reports STOP is still loaded onto, and warned about twice.
    """
    monkeypatch.setattr(driver_module, "STOP_BEFORE_LOAD_TIMEOUT_S", 0.05)
    setup(driver)
    unpatched = driver._client.channel_info

    def still_running(channel):
        info = unpatched(channel)
        info.State = vendor.PROG_STATE.RUN
        return info

    driver._client.channel_info = still_running

    with caplog.at_level("WARNING"):
        response = driver.start_channel(0)

    assert response.response == DriverResponseType.success
    assert response.status == DriverStatus.busy
    assert "state 1 (RUN)" in caplog.text
    assert "still reports state 1" in caplog.text
    assert driver.channel == 0


def test_start_still_fails_when_the_channel_state_cannot_be_read(driver):
    """The other branch of that gate stays a refusal: an unreadable channel
    means the instrument is not answering, not that it is mid-halt."""
    from helao.deploy.hte.drivers.pstat.biologic.eclib_client import EclibError

    setup(driver)

    def unreadable(channel):
        raise EclibError(-1, "BL_GetChannelInfos")

    driver._client.channel_info = unreadable
    response = driver.start_channel(0)

    assert response.response == DriverResponseType.failed
    assert "encountered an error" in (response.message or "")
    assert driver.channel is None


# --- loading onto a channel that is still running ---------------------------


def _record_client_calls(driver, *names):
    """Names of the client calls a driver makes, in order."""
    calls: list[str] = []
    client = driver._client
    for name in names:
        original = getattr(client, name)

        def wrapper(*args, _name=name, _original=original, **kwargs):
            calls.append(_name)
            return _original(*args, **kwargs)

        setattr(client, name, wrapper)
    return calls


def test_a_load_stops_a_running_channel_first(driver):
    """Station failure, 2026-09-18, `run_OCV` with `TTLsend=0`: the trigger's
    `BL_LoadTechnique(first=True, last=False)` drew `cannot load experiment
    after make...` from the firmware while still returning 0, and the
    technique's load then failed -403. A list that spans two calls is not
    "made" between them, and the firmware will not begin one on a running
    channel."""
    setup(driver)
    driver.start_channel(0)  # channel is now RUN

    calls = _record_client_calls(driver, "stop_channel", "load_technique")
    assert driver.start_channel(0).response == DriverResponseType.success

    assert "stop_channel" in calls
    assert calls.index("stop_channel") < calls.index("load_technique")


def test_a_load_onto_a_stopped_channel_does_not_stop_it(driver):
    """One `BL_GetChannelInfos` and no `BL_StopChannel` -- the common path
    must not pay for the running one."""
    calls = _record_client_calls(driver, "stop_channel", "load_technique")
    setup(driver)

    assert "stop_channel" not in calls
    assert "load_technique" in calls


def test_a_failed_load_names_the_step_that_failed(driver):
    """`ERR_TECH_LOADTECHNIQUEFAILED` alone cannot say which technique of a
    linked plan the firmware rejected."""
    setup(driver)
    sim.set_sim_config(sim.SimConfig(fail_on={"BL_LoadTechnique": -403}))

    resp = driver.start_channel(0, {"ttl": "out", "ttl_logic": 1, "ttl_duration": 1.0})

    assert resp.response == DriverResponseType.failed
    message = resp.message or ""
    assert "step 1/2" in message
    assert "TO" in message
    assert "first=True, last=False" in message
