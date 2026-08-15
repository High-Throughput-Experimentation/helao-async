"""hte action modules still CONSTRUCT under a real config (B5).

The checklist gate (``test_hte_route_checklist.py``) reads source and never
imports, which is its strength -- it covers Windows-only modules and
``dyn_endpoints`` routes alike. Its blind spot is the constructor: a port that
renames a driver keyword, drops a poller class or breaks an import passes the
checklist and fails here.

Measured at ``5c05c8d2``, 16 of the 17 station-live modules build on Linux. The
one that does not is recorded by name and by the exception it raises, not
skipped: "it did not build" and "it built" must stay distinguishable, and a
bare skip makes a genuine breakage look like the known Windows case.

Deliberately NOT asserted: the number of routes on the built app. Most of these
servers register their action routes inside ``dyn_endpoints``, which runs at
startup, so ``galil_motion`` -- 24 action routes in source -- builds an app
carrying only the 24-route private surface. The two numbers coinciding is a
coincidence, and asserting on either would encode the confusion as a
requirement. Route coverage is the checklist gate's job.
"""

import importlib

import pytest

from helao.helpers.config_loader import load_global_config

#: (module, config prefix, server key) -- one representative station per module.
#: Measured by loading each station config and calling makeApp; every one of
#: these built at 5c05c8d2.
BUILDS: list[tuple[str, str, str]] = [
    ("andor_server", "hispec", "ANDOR"),
    ("calc_server", "ccsi2", "CALC"),
    ("cam_server", "eche10", "CAM"),
    ("co2sensor_server", "ccsi2", "CO2SENSOR"),
    ("diapump_server", "ccsi2", "DOSEPUMP"),
    ("galil_io", "anec", "IO"),
    ("galil_motion", "adss3", "MOTOR"),
    ("gamry_server2", "adss3", "PSTAT"),
    ("kinesis_server", "eche10", "KMOTOR"),
    ("mfc_server", "ccsi2", "MFC"),
    ("nidaqmx_server", "adss3", "NI"),
    ("pal_server", "adss3", "PAL"),
    ("sample_server", "adss3", "SAMPLE"),
    ("spec_server", "eche10", "SPEC_T"),
    ("sync_server", "adss3", "SYNC"),
    ("syringe_server", "adss3", "WORKSYRINGE"),
]

#: Module -> the substring of the exception it is EXPECTED to raise on Linux.
WINDOWS_ONLY: dict[str, str] = {
    "biologic_server": "can only be used on Windows",
}


def _not_yet_ported() -> frozenset[str]:
    from helao.hexagon.tests.test_hte_is_native import NOT_YET_PORTED

    return NOT_YET_PORTED


@pytest.mark.parametrize("module,config,server_key", BUILDS, ids=[b[0] for b in BUILDS])
def test_module_builds_under_its_station_config(
    module: str, config: str, server_key: str
) -> None:
    from helao.helpers.server_api import HelaoFastAPI
    from helao.hexagon.app.action_host import ActionHost

    load_global_config(config, set_global=True)
    mod = importlib.import_module(f"helao.deploy.hte.servers.action.{module}")
    app = mod.makeApp(server_key)

    # `title`, not `server_key`: a legacy BaseAPI has no `server_key` attribute
    # at all, and `app.base` does not exist until the startup handler runs, so
    # `base.server_name` reads None here. `title` is the one identity both host
    # kinds carry at build time, and the launcher's contract is HelaoFastAPI.
    assert isinstance(app, HelaoFastAPI), f"{module} built a {type(app).__name__}"
    assert app.title == server_key

    # Before this module's port the app is a legacy BaseAPI, and the ratchet is
    # what says which of the two to expect. After it, the host type IS the
    # assertion -- a port that left a BaseAPI behind would still pass the
    # checklist gate, which reads decorators rather than the constructor.
    if module not in _not_yet_ported():
        assert isinstance(app, ActionHost), f"{module} did not build an ActionHost"


@pytest.mark.parametrize("module,expected", sorted(WINDOWS_ONLY.items()))
def test_windows_only_module_fails_the_way_we_recorded(
    module: str, expected: str
) -> None:
    """Not a skip: the failure MODE is the assertion.

    If ``easy_biologic`` ever becomes importable on Linux this fails, and that
    is correct -- it would mean the module gained a Linux build gate it does
    not have today, and BUILDS should grow to claim it.
    """
    with pytest.raises(BaseException) as exc:
        importlib.import_module(f"helao.deploy.hte.servers.action.{module}")
    assert expected in str(
        exc.value
    ), f"{module} raised {exc.value!r}, not {expected!r}"


def test_the_orchestrator_builds_a_native_OrchHost() -> None:
    """B5.6 moved the hte orchestrator entrypoint from OrchAPI to OrchHost.

    Worth its own case rather than a row in BUILDS: the constructors differ.
    ``OrchAPI`` took ``driver_classes``, every hte config passed None, and
    ``OrchHost`` does not have the parameter at all -- so the port raised
    TypeError on a keyword that had only ever meant "this server has no
    driver". Nothing in the route checklist could see that; the orchestrator
    has no entry there, and the failure is at construction.
    """
    from helao.hexagon.app.orch_host import OrchHost

    load_global_config("adss3", set_global=True)
    mod = importlib.import_module("helao.deploy.hte.servers.orchestrator.async_orch2")
    app = mod.makeApp("ORCH")
    assert isinstance(app, OrchHost), f"orchestrator built a {type(app).__name__}"
    assert app.title == "ORCH"
    # The surface B3a froze against the live legacy orchestrator.
    assert len(app.routes) == 84, f"orchestrator has {len(app.routes)} routes"


def test_the_probe_covers_every_station_live_module() -> None:
    """17 modules appear in a live hte station config; all 17 are accounted for.

    The other six action modules -- analysis_server, HTEdata_server,
    o2sensor_server, pdu_server, power_supply_server, tec_server -- are in no
    live hte config (commented out, archive-only, or, for pdu_server, live only
    in a private deployment). They are ported by B5 but no station runs them,
    which is stated in the spec rather than implied away by a coverage count.
    """
    covered = {b[0] for b in BUILDS} | set(WINDOWS_ONLY)
    assert len(covered) == 17, f"probe covers {len(covered)} modules, expected 17"
