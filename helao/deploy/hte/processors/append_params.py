from helao.helpers.meta_processor import MetaProcessor
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class PostProcess(MetaProcessor):

    def process(self) -> None:
        if self.meta_type == "experiment":
            self.meta.experiment_params.update({"appended_exp_param": "yes"})
        elif self.meta_type == "sequence":
            self.meta.sequence_params.update({"appended_seq_param": "yes"})
