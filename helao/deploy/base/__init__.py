"""Framework services every deployment launches.

The orchestrator (``async_orch2``), the standalone operator, the Bokeh
visualizers and data browser, the data syncer (``sync_server``) and the shared
Reflex panel helpers. They have the deployment shape (``servers/<role>/``) so
the launcher's cross-deployment module lookup finds them by bare name, and they
are tracked in this repository so a clone with no deployment checked out can
still launch a group.
"""
