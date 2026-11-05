"""Status ingestion collaborator extracted from ``Orch`` (CARDS P5, Stage S4).

``StatusIngester`` now holds only ``Orch.clear_nonblocking``: it sends
``stop_executor`` to every tracked non-blocking executor. The status-ingestion
bodies (``update_status`` / ``update_nonblocking``) live in
``helao.hexagon.app.ingestion.HexStatusIngestion``. (This module also held
``ws_globstat`` and ``globstat_broadcast_task``, a ``/ws_globstat`` sender that
never had a route; B7b deleted both with ``globstat_q``.)

Per the P5 constraints (:doc:`CARDS_REFACTOR_P5.md` sec 3.1 rule 3):
``StatusIngester`` caches no shared mutable state -- it holds only the
``orch`` back-reference and reads ``nonblocking`` through it at call time.

Lock/queue ownership (rule 4) -- full map (also duplicated verbatim in
``orch_dispatch.py``, the other lock owner):

- ``aiolock`` -- acquired by ``HexStatusIngestion`` (status ingestion) and
  ``DispatchRunner`` (the dispatch critical section).
- ``interrupt_q`` -- written by ``HexStatusIngestion`` / ``ServerMonitor`` /
  e-stop; read by the dispatch loop.
"""

from helao.helpers import helao_logging as logging
from helao.helpers.dispatcher import async_private_dispatcher

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class StatusIngester:
    """Non-blocking executor cleanup for an ``Orch``.

    Holds only the ``orch`` back-reference (never a cached deque/attribute/task
    handle), per the call-time state resolution rule -- see module docstring.
    """

    def __init__(self, orch):
        self.orch = orch

    async def clear_nonblocking(self) -> list:
        """Send ``stop_executor`` to every tracked non-blocking action and return their responses."""
        orch = self.orch
        resp_tups = []
        for server_key, exec_id, server_host, server_port in orch.nonblocking:
            LOGGER.info(
                f"Sending stop_executor request to {server_key} on {server_host}:{server_port} for executor {exec_id}"
            )
            # print(server_key, exec_id, server_host, server_port)
            response, error_code = await async_private_dispatcher(
                server_key=server_key,
                host=server_host,
                port=server_port,
                private_action="stop_executor",
                params_dict={"executor_id": exec_id},
                json_dict={},
            )
            resp_tups.append((response, error_code))
        return resp_tups
