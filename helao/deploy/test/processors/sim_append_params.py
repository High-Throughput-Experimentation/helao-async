"""Test-deployment meta post-processor: tag experiment/sequence params.

Appends ``appended_exp_param`` / ``appended_seq_param`` to the record's params at
finalization, so the framework tests and golden configs have a MetaProcessor that
does not depend on any instrument deployment.
"""

from helao.helpers.processors import MetaProcessor


class PostProcess(MetaProcessor):
    """MetaProcessor that injects a marker key into experiment/sequence params."""

    def process(self) -> None:
        if self.meta_type == "experiment":
            self.meta.experiment_params.update({"appended_exp_param": "yes"})
        elif self.meta_type == "sequence":
            self.meta.sequence_params.update({"appended_seq_param": "yes"})
