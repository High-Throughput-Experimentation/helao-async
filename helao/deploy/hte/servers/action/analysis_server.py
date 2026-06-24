# shell: uvicorn motion_server:app --reload
"""Analysis action server.

Thin wrapper over the consolidated
:func:`helao.core.drivers.data.analysis_driver.make_analysis_app`. The set of
``analyze_<module>`` action endpoints exposed by this server is driven by the
``params.analyses`` list in the server config. Distinct from ``calc_server``
which performs in-sequence calculations without producing :class:`Analysis`
models.
"""

__all__ = ["makeApp"]

from helao.framework.app.base_api import BaseAPI
from helao.framework.app.analysis_driver import make_analysis_app


def makeApp(server_key) -> BaseAPI:
    """Build the analysis FastAPI app for ``server_key``.

    Args:
        server_key: Key identifying this server in the orchestration group.

    Returns:
        The configured :class:`BaseAPI` application.
    """
    return make_analysis_app(server_key)
