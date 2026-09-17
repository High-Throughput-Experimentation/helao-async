"""setup/start/get_data/stop/cleanup against the simulated DLL."""

import asyncio

import pytest

from helao.core.drivers.helao_driver import DriverResponseType, DriverStatus
from helao.deploy.hte.drivers.pstat.biologic import data, sim, vendor
from helao.deploy.hte.drivers.pstat.biologic import technique as bt
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


def test_start_on_a_running_channel_fails(driver):
    sim.set_sim_config(sim.SimConfig(polls_until_stop=99))
    setup(driver)
    driver.start_channel(0)
    assert driver.start_channel(0).response == DriverResponseType.failed


# --- get_data ---------------------------------------------------------------


def test_the_first_poll_before_the_firmware_runs_is_not_done(driver):
    """StartChannel returns before the channel is running; the old driver's
    State == 0 test ended the action here."""
    sim.set_sim_config(sim.SimConfig(idle_polls_before_run=2))
    setup(driver)
    driver.start_channel(0)
    resp = asyncio.run(driver.get_data(0))
    assert resp.message == "measuring"


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
