from abc import ABC, abstractmethod


class MetaProcessor(ABC):

    def __init__(self, meta, core):
        self.core = core
        self.meta = meta
        self.meta_type = meta.__class__.__name__.lower()
        self.global_params = (
            core.global_params if core.__class__.__name__.lower() == "orch" else {}
        )

    @abstractmethod
    def process(self) -> None:
        """Update object in-place."""
