"""Meta post-processor that tags experiment/sequence params with a marker.

Demonstrates the :class:`MetaProcessor` contract by appending an
``appended_exp_param``/``appended_seq_param`` key to the meta object's
params dict at finalization time.
"""

from helao.helpers import helao_logging as logging
from helao.helpers.processors import MetaProcessor

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class PostProcess(MetaProcessor):
    """MetaProcessor that injects a marker key into experiment/sequence params."""

    def process(self) -> None:
        """Append the marker key to the matching params dict on the meta."""
        if self.meta_type == "experiment":
            self.meta.experiment_params.update({"appended_exp_param": "yes"})
        elif self.meta_type == "sequence":
            self.meta.sequence_params.update({"appended_seq_param": "yes"})
