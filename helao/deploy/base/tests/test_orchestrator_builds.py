"""The base orchestrator entrypoint builds a native OrchHost on Linux."""

import importlib

from helao.helpers.config_loader import install_global_config, read_validated_config


def test_the_orchestrator_builds_a_native_OrchHost() -> None:
    """B5.6 moved the orchestrator entrypoint from OrchAPI to OrchHost.

    Worth its own case rather than a row in BUILDS: the constructors differ.
    ``OrchAPI`` took ``driver_classes``, every hte config passed None, and
    ``OrchHost`` does not have the parameter at all -- so the port raised
    TypeError on a keyword that had only ever meant "this server has no
    driver". Nothing in the route checklist could see that; the orchestrator
    has no entry there, and the failure is at construction.
    """
    from helao.hexagon.app.orch_host import OrchHost

    install_global_config(read_validated_config("golden")[0])
    mod = importlib.import_module("helao.deploy.base.servers.orchestrator.async_orch2")
    app = mod.makeApp("ORCH")
    assert isinstance(app, OrchHost), f"orchestrator built a {type(app).__name__}"
    assert app.title == "ORCH"
    # The surface B3a froze against the live legacy orchestrator.
    # 84 frozen routes + /ws_orch and /get_object (the group-graph feed).
    assert len(app.routes) == 86, f"orchestrator has {len(app.routes)} routes"
