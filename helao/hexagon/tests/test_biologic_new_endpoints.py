"""The new routes exist on eclib, carry the parameters the techniques need,
and run_plan is registered on both SDK-backed backends."""

import asyncio
import tempfile

import pytest

from helao.deploy.hte.drivers.pstat.biologic.technique import BIOTECHS


@pytest.fixture
def app(monkeypatch):
    from helao.core.drivers.helao_driver import (
        DriverResponse,
        DriverResponseType,
        DriverStatus,
    )
    from helao.deploy.hte.drivers.pstat.biologic.driver import BiologicDriver
    from helao.helpers import config_loader
    from helao.deploy.hte.servers.action import biologic_server

    monkeypatch.setattr(
        config_loader,
        "CONFIG",
        {
            # A real directory: on the first ActionHost built in a process,
            # HelaoFastAPI initializes the process logger under <root>/LOGS
            # (see test_biologic_backend_select.py's with_config), so a
            # missing "root" fails in os.path.join before any route is
            # registered.
            "root": tempfile.mkdtemp(prefix="helao_biologic_new_endpoints_test_"),
            "servers": {
                "BIOLOGIC": {
                    "group": "action",
                    "host": "127.0.0.1",
                    "port": 8000,
                    "params": {
                        "pstat_backend": "eclib",
                        "address": "192.168.200.100",
                        "num_channels": 1,
                        "simulate": True,
                    },
                }
            },
        },
        raising=False,
    )

    # `run_CA`/`run_CALIMIT`/etc. are registered inside `biologic_dyn_endpoints`,
    # which the real launcher calls from ActionHost's FastAPI startup event
    # once `app.driver` exists and is ready -- so makeApp() alone builds an
    # app with none of them yet (see test_biologic_backend_select.py's
    # test_run_protocol_registers_only_on_the_ole_backend for the same
    # pattern). `connect()` is stubbed to report ready immediately, exactly
    # as a real EC-Lab station would, instead of hitting the network.
    def _fake_connect(self):
        self.ready = True
        return DriverResponse(
            response=DriverResponseType.success, status=DriverStatus.ok
        )

    monkeypatch.setattr(BiologicDriver, "connect", _fake_connect)

    built = biologic_server.makeApp("BIOLOGIC")
    built.driver = biologic_server.BACKENDS["eclib"](config=built.server_params)
    asyncio.run(biologic_server.biologic_dyn_endpoints(built))
    return built


def paths(app):
    return {route.path for route in app.routes}


def params_of(app, path):
    route = next(r for r in app.routes if r.path == path)
    return {p.name for p in route.dependant.query_params + route.dependant.body_params}


def test_the_four_new_routes_are_registered(app):
    assert {
        "/BIOLOGIC/run_CALIMIT",
        "/BIOLOGIC/run_CPLIMIT",
        "/BIOLOGIC/run_SPEIS",
        "/BIOLOGIC/run_SGEIS",
    } <= paths(app)


def test_run_plan_is_registered_on_eclib(app):
    assert "/BIOLOGIC/run_plan" in paths(app)


def test_the_seven_existing_routes_are_untouched(app):
    assert {
        f"/BIOLOGIC/run_{name}"
        for name in ("OCV", "CA", "CP", "CV", "PEIS", "GEIS", "CAOCV")
    } <= paths(app)


def test_run_protocol_is_still_olecom_only(app):
    assert "/BIOLOGIC/run_protocol" not in paths(app)


def test_every_new_route_resolves_a_registered_technique(app):
    for name in ("CALIMIT", "CPLIMIT", "SPEIS", "SGEIS"):
        assert name in BIOTECHS


def test_calimit_carries_the_limit_parameters(app):
    got = params_of(app, "/BIOLOGIC/run_CALIMIT")
    assert {"Test1", "Test2", "Test3", "ExitCondition", "Cycles"} <= got
    assert {"Vval__V", "Tval__s", "IRange", "ERange", "Bandwidth", "channel"} <= got


def test_cplimit_takes_current_steps_not_voltage(app):
    got = params_of(app, "/BIOLOGIC/run_CPLIMIT")
    assert "Ival__A" in got
    assert "Vval__V" not in got


def test_speis_takes_two_biases_and_a_step_count(app):
    got = params_of(app, "/BIOLOGIC/run_SPEIS")
    assert {"Vinit__V", "Vfinal__V", "StepNumber"} <= got


def test_sgeis_takes_two_currents_and_a_step_count(app):
    got = params_of(app, "/BIOLOGIC/run_SGEIS")
    assert {"Iinit__A", "Ifinal__A", "StepNumber"} <= got


def test_the_new_routes_do_not_advertise_ttl(app):
    """The trigger's electrical leg is untested; advertising it on four brand
    new endpoints widens the at-station gate for nothing."""
    for name in ("CALIMIT", "CPLIMIT", "SPEIS", "SGEIS"):
        got = params_of(app, f"/BIOLOGIC/run_{name}")
        assert not {"TTLwait", "TTLsend", "TTLduration"} & got


def test_run_cv_docstring_no_longer_claims_it_subtracts_a_cycle(app):
    route = next(r for r in app.routes if r.path == "/BIOLOGIC/run_CV")
    doc = route.endpoint.__doc__ or ""
    assert "Subtracts one" not in doc
    assert "derives" not in doc
