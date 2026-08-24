"""HTE action-server package.

Each module in this package exposes a ``makeApp(server_key)`` factory that
returns a :class:`helao.hexagon.app.action_host.ActionHost` (``HelaoFastAPI``)
instance wrapping a specific hardware/data driver and publishing
``/<server_key>/<action>`` POST endpoints.
"""
