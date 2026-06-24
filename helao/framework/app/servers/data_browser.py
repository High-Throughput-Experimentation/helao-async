# helao/framework/app/servers/data_browser.py
"""Deployment-agnostic framework data-browser entry point."""
__all__ = ["makeBokehApp"]

from helao.framework.app.vis import HelaoVis
from helao.framework.app.data_browser import build_document
from helao.framework.support import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


def makeBokehApp(doc, confPrefix, server_key, helao_repo_root):
    """Build the data-browser Bokeh document on framework modules."""
    app = HelaoVis(server_key=server_key, doc=doc)
    build_document(app.vis)
    return doc
