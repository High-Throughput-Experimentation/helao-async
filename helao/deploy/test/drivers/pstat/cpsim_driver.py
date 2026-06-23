"""Chronopotentiometry simulator backed by a pickled OER measurement library.

Provides :class:`CPSim`, a driver that exposes the OER ``oer13_cps`` dataset as
a "loaded plate" with addressable compositions, and :class:`CPSimExec`, an
:class:`Executor` that streams a stored CP trace over the action server's
data buffer at the requested polling rate.
"""

import os
import time
import asyncio
import functools

from helao.framework.support import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
from helao.framework.models.errors import ErrorCodes
from helao.framework.models.hlostatus import HloStatus
from helao.framework.support.file_utils import unzpickle
from helao.framework.app.base_api import Base
from helao.framework.domain.executor import Executor
from ...drivers.data.gpsim_driver import calc_eta


class CPSim:
    """Simulated potentiostat that replays stored CP traces.

    Loads the ``oer13_cps.pzstd`` library at startup, keeps a single
    "loaded plate" active, and lets the hosting action server look up
    compositions and switch between plates.

    Attributes:
        base: Hosting action server.
        config_dict: ``params`` block from the server config.
        world_config: Full world configuration.
        loaded_plate: Identifier of the currently selected plate.
        all_data: Dict of every plate's composition-keyed CP records.
        data: View of ``all_data`` restricted to the loaded plate.
    """

    def __init__(self, action_serv: Base):
        """Load the OER dataset and select the initial plate.

        Args:
            action_serv: Action server hosting this driver.
        """
        self.base = action_serv
        self.config_dict = action_serv.server_cfg.get("params", {})
        self.world_config = action_serv.world_cfg
        self.loaded_plate = self.config_dict["plate_id"]
        self.data_file = os.path.join(
            os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
            ),
            "demos",
            "data",
            "oer13_cps.pzstd",
        )
        self.all_data = unzpickle(self.data_file)
        self.data = self.all_data[self.loaded_plate]

        self.event_loop = asyncio.get_event_loop()

    def change_plate(self, plate_id) -> bool:
        """Switch the loaded plate if the requested id exists.

        Args:
            plate_id: Identifier of the plate to load.

        Returns:
            True if the plate was found and loaded, False otherwise.
        """
        if plate_id in self.all_data:
            self.data = self.all_data[plate_id]
            LOGGER.info(f"loaded plate_id: {plate_id}")
            return True
        else:
            LOGGER.info(f"plate_id: {plate_id} does not exist in dataset")
            return False

    def list_plates(self) -> dict:
        """Enumerate plates and the elements present on each.

        Returns:
            Mapping of ``plate_id`` to the sorted set of element labels
            appearing in any composition on that plate.
        """
        plate_els = [
            (
                pid,
                functools.reduce(
                    lambda x, y: set(x).union(y),
                    [compd["el_str"].split("-") for compd in plated.values()],
                ),
            )
            for pid, plated in self.all_data.items()
            if pid != "els"
        ]
        return {k: sorted(v) for k, v in plate_els}

    def list_addressable(self, limit: int = 10, by_el: bool = False):
        """List the first compositions addressable on the loaded plate.

        Args:
            limit: Maximum number of composition tuples to return.
            by_el: If True, return columns keyed by element label;
                otherwise return a header row followed by composition rows.

        Returns:
            Either a dict keyed by element label (when ``by_el`` is True) or
            a list whose first entry is the element labels followed by
            composition tuples.
        """
        plate_comps = list(self.data.keys())[:limit]
        if by_el:
            el_vecs = list(zip(*plate_comps))
            return {k: v for k, v in zip(self.all_data["els"], el_vecs)}
        else:
            return [self.all_data["els"]] + plate_comps

    def shutdown(self):
        """No-op shutdown hook."""
        pass


class CPSimExec(Executor):
    """Executor that streams a stored CP trace as if measuring live.

    Selects the trace matching ``comp_vec`` on the loaded plate, hands its
    initial header (elements and atomic fractions) to the action data
    buffer in ``_exec``, then streams new ``CP3`` samples in ``_poll`` based
    on elapsed wall-clock time, finishing once the full trace has been
    emitted.
    """

    def __init__(self, *args, **kwargs):
        """Initialize the executor from the active action's parameters."""
        super().__init__(*args, **kwargs)
        LOGGER.info("EcheSimExec initialized.")
        self.last_idx = 0
        self.start_time = time.time()  # instantiation time
        self.duration = self.active.action.action_params.get("duration", -1)
        self.sample_data = self.active.driver.data[
            tuple(self.active.action.action_params["comp_vec"])
        ]
        self.cp = self.sample_data["CP3"]
        self.els = self.sample_data["el_str"].split("-")
        self.fracs = [self.sample_data[el] for el in self.els]

    async def _exec(self) -> dict:
        """Emit the header (elements/atfracs and empty CP series) at start.

        Returns:
            Dict with the header data dict and ``ErrorCodes.none``.
        """
        self.start_time = time.time()  # pre-polling iteration time
        data = {"elements": self.els, "atfracs": self.fracs}
        data.update({k: [] for k in self.cp})
        return {"data": data, "error": ErrorCodes.none}

    async def _poll(self) -> dict:
        """Stream the next slice of the stored CP trace.

        Returns:
            Dict with newly emitted samples, ``ErrorCodes.none``, and an
            ``HloStatus`` that transitions to ``finished`` after the last
            stored sample is emitted.
        """
        elapsed_time = time.time() - self.start_time
        new_idxs = [i for i, v in enumerate(self.cp["t_s"]) if v < elapsed_time]
        status = HloStatus.active
        live_dict = {}
        if new_idxs:
            newest_idx = max(new_idxs)
            live_dict = {k: v[self.last_idx : newest_idx] for k, v in self.cp.items()}
            self.last_idx = newest_idx
            if newest_idx == len(self.cp["t_s"]) - 1:
                status = HloStatus.finished
        await asyncio.sleep(0.001)
        return {
            "error": ErrorCodes.none,
            "status": status,
            "data": live_dict,
        }

    async def _post_exec(self) -> dict:
        """Compute the final-window eta and write it back to action params.

        Returns:
            Dict with ``ErrorCodes.none``.
        """
        # calculate final 4-second eta mean and pass to params
        self.active.action.action_params["mean_eta_vrhe"] = calc_eta(self.cp)
        return {"error": ErrorCodes.none}
