# helao/framework/app/servers/standalone_operator.py
"""Deployment-agnostic standalone operator host (framework app layer)."""
__all__ = ["makeBokehApp"]

from helao.framework.app.vis import HelaoVis
from helao.framework.adapters.operator_backend import RemoteBackend
from helao.framework.app.operator.bokeh_operator import BokehOperator
from helao.framework.support import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


def makeBokehApp(doc, confPrefix, server_key, helao_repo_root):
    """Build the standalone operator Bokeh document.

    Constructs a framework ``HelaoVis`` host, a ``RemoteBackend`` pointed at the
    orchestrator named by ``params.orch_key`` (or the lone ``group:orchestrator``
    server), and a ``BokehOperator`` UI bound to that backend.
    """
    app = HelaoVis(server_key=server_key, doc=doc)
    params = app.vis.server_cfg.get("params", {})
    backend = RemoteBackend(
        app.vis,
        orch_key=params.get("orch_key"),
        poll_interval=params.get("poll_interval", 5.0),
    )
    doc.operator = BokehOperator(app.vis, backend)
    return doc
