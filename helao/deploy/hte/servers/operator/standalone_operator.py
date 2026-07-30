__all__ = ["makeBokehApp"]

from helao.core.servers.operator.bokeh_operator import BokehOperator
from helao.core.servers.operator.orch_backend import RemoteBackend
from helao.core.servers.vis import HelaoVis
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


def makeBokehApp(doc, confPrefix, server_key, helao_repo_root):
    """Build the standalone operator Bokeh document.

    Constructs a :class:`HelaoVis` host, a :class:`RemoteBackend` pointed at the
    orchestrator named by ``params.orch_key`` (or the lone group:orchestrator
    server), and a :class:`BokehOperator` UI bound to that backend.

    Args:
        doc: Bokeh document supplied by the Bokeh server for this session.
        confPrefix: Config prefix passed by ``bokeh_launcher.py``.
        server_key: Operator server key from the configuration.
        helao_repo_root: Absolute path to the HELAO repo root.

    Returns:
        Bokeh ``Document``: the same ``doc``, with the operator UI mounted.
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
