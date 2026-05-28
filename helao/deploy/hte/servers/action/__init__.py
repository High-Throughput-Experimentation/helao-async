"""HTE action-server package.

Each module in this package exposes a ``makeApp(server_key)`` factory that
returns a :class:`helao.core.servers.base_api.BaseAPI` (``HelaoFastAPI``)
instance wrapping a specific hardware/data driver and publishing
``/<server_key>/<action>`` POST endpoints.
"""
