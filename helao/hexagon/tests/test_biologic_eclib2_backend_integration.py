"""The eclib2 backend as the action server's third backend.

Checks it against the *real* `BiologicBackend` protocol and the *real*
`BACKENDS` map rather than against a description of them, and pins the two
behaviours a third backend could plausibly break: the default must stay
`eclib` so every existing station config keeps working unedited, and a
technique name must resolve through each backend's own registry.
"""

import inspect

import pytest

from helao.deploy.hte.drivers.pstat.biologic_backend import BiologicBackend
from helao.deploy.hte.drivers.pstat.biologic_eclib2 import technique as ec2tech
from helao.deploy.hte.drivers.pstat.biologic_eclib2.driver import BiologicEclib2Driver
from helao.hexagon.tests.biologic_eclib2_sample_params import params

BACKEND_NAME = "eclib2"


def _static_conformance(driver: BiologicEclib2Driver) -> BiologicBackend:
    """Make pyright check the structural conformance, not just the names.

    ``BiologicBackend`` is ``runtime_checkable``, so ``isinstance`` verifies
    only that the method *names* exist -- a ``setup`` missing ``output_dir``,
    or a ``shutdown`` returning a value, passes it. Nothing else in the tree
    statically assigns a driver to the protocol, so this return is what makes
    the type checker compare signatures. Never called.
    """
    return driver


@pytest.fixture
def server_module():
    # Imported inside a fixture: the module pulls in the whole action-server
    # stack, and the pure-unit files in this suite must not depend on it.
    from helao.deploy.hte.servers.action import biologic_server

    return biologic_server


@pytest.fixture
def driver():
    d = BiologicEclib2Driver(
        {"address": "192.168.200.100", "num_channels": 1, "simulate": True}
    )
    try:
        yield d
    finally:
        d.shutdown()


# --------------------------------------------------------------------------
# protocol conformance
# --------------------------------------------------------------------------


def test_the_driver_satisfies_the_backend_protocol_at_runtime(driver):
    assert isinstance(driver, BiologicBackend)


def test_every_protocol_method_signature_is_call_compatible():
    # `runtime_checkable` only checks that the names exist, so the shapes have
    # to be compared explicitly -- a `setup` missing `output_dir` would pass
    # isinstance and then fail when BiologicExec calls it by keyword.
    for name, expected in inspect.getmembers(
        BiologicBackend, predicate=inspect.isfunction
    ):
        if name.startswith("_"):
            continue
        actual = getattr(BiologicEclib2Driver, name, None)
        assert actual is not None, f"missing {name}"
        expected_params = inspect.signature(expected).parameters
        actual_params = inspect.signature(actual).parameters
        for param in expected_params:
            assert param in actual_params, f"{name} is missing {param!r}"


def test_setup_is_callable_the_way_the_executor_calls_it(driver):
    # BiologicExec._pre_exec passes all three by keyword and reads the channel
    # from action_params, so a `channel=` parameter here would be unreachable.
    driver.connect()
    response = driver.setup(
        technique=ec2tech.resolve("OCV"),
        action_params=params("OCV", channel=0),
        output_dir=None,
    )
    assert response.response == "success"


def test_start_channel_is_callable_the_way_the_executor_calls_it(driver):
    # `self.driver.start_channel(self.channel, self.ttl_params)` -- positional.
    driver.connect()
    driver.setup(
        technique=ec2tech.resolve("OCV"), action_params=params("OCV", channel=0)
    )
    ttl = {"ttl": "none", "ttl_logic": 1, "ttl_duration": 1.0}
    assert driver.start_channel(0, ttl).response == "success"


def test_shutdown_returns_none_like_both_sibling_backends(driver):
    driver.connect()
    assert driver.shutdown() is None


def test_get_data_says_done_exactly_when_the_technique_finished(driver):
    # BiologicExec._poll ends the action on the literal string "done", so this
    # is load-bearing rather than cosmetic.
    import asyncio

    driver.connect()
    driver.setup(
        technique=ec2tech.resolve("OCV"), action_params=params("OCV", channel=0)
    )
    driver.start_channel(0)

    async def drain():
        seen = []
        for _ in range(50):
            response = await driver.get_data(0)
            seen.append(response.message)
            if response.message == "done":
                return seen
        raise AssertionError("never reported done")

    seen = asyncio.run(drain())
    assert seen[-1] == "done"
    assert "done" not in seen[:-1]


# --------------------------------------------------------------------------
# registration
# --------------------------------------------------------------------------


def test_the_backend_is_registered_under_its_own_name(server_module):
    assert server_module.BACKENDS[BACKEND_NAME] is BiologicEclib2Driver


def test_all_three_backends_are_distinct_drivers(server_module):
    # eclib and eclib2 are not two versions of one backend: EC-Lib 2.0 is not
    # backwards compatible with the EClib1 DLLs easy-biologic bundles.
    classes = list(server_module.BACKENDS.values())
    assert len(set(classes)) == len(classes)
    assert set(server_module.BACKENDS) == {"eclib", "olecom", "eclib2"}


def test_the_default_backend_is_unchanged(server_module):
    # Every existing station config omits `pstat_backend`; if adding a third
    # backend moved the default, all of them would switch instrument driver.
    assert server_module.DEFAULT_BACKEND == "eclib"


def test_every_backend_has_a_technique_registry(server_module):
    assert set(server_module.TECHNIQUE_REGISTRIES) == set(server_module.BACKENDS)


def test_the_registry_resolves_a_name_to_this_backends_technique_object(server_module):
    resolve = server_module.TECHNIQUE_REGISTRIES[BACKEND_NAME]
    technique = resolve("PEIS")
    assert isinstance(technique, ec2tech.Eclib2Technique)
    assert technique.technique_name == "PEIS"


def test_each_backend_resolves_the_same_name_to_its_own_technique_type(server_module):
    # A shared technique object would have to know all three SDKs.
    resolved = {
        name: server_module.TECHNIQUE_REGISTRIES[name]("CA")
        for name in server_module.BACKENDS
    }
    types = {type(v) for v in resolved.values()}
    assert len(types) == len(resolved)


def test_a_config_selecting_this_backend_picks_this_driver(server_module, monkeypatch):
    from helao.helpers import config_loader

    monkeypatch.setattr(
        config_loader,
        "CONFIG",
        {"servers": {"PSTAT": {"params": {"pstat_backend": BACKEND_NAME}}}},
    )
    assert server_module._backend_name("PSTAT") == BACKEND_NAME
    assert server_module._driver_class("PSTAT") is BiologicEclib2Driver


def test_a_config_with_no_backend_key_still_picks_eclib(server_module, monkeypatch):
    from helao.helpers import config_loader

    monkeypatch.setattr(config_loader, "CONFIG", {"servers": {"PSTAT": {"params": {}}}})
    assert server_module._backend_name("PSTAT") == "eclib"


def test_a_typo_is_refused_rather_than_falling_back(server_module, monkeypatch):
    from helao.helpers import config_loader

    monkeypatch.setattr(
        config_loader,
        "CONFIG",
        {"servers": {"PSTAT": {"params": {"pstat_backend": "eclib_2"}}}},
    )
    with pytest.raises(ValueError, match="eclib_2"):
        server_module._backend_name("PSTAT")


def test_every_technique_this_backend_advertises_resolves(server_module):
    resolve = server_module.TECHNIQUE_REGISTRIES[BACKEND_NAME]
    for name in ec2tech.TECHNIQUE_NAMES:
        assert resolve(name).technique_name == name


def test_the_endpoint_technique_names_are_the_same_across_backends(server_module):
    # The server's run_* endpoints are generated per technique name, so a
    # backend that spelled them differently would change the route table.
    from helao.deploy.hte.drivers.pstat.biologic.technique import BIOTECHS

    assert set(ec2tech.TECHNIQUE_NAMES) == set(BIOTECHS)
