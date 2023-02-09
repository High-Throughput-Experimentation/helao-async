from fastapi import FastAPI

__all__ = ["HelaoBokehAPI", "HelaoFastAPI"]


TAGS = [
    {"name": "action", "description": "action endpoints will register status and block"},
    {"name": "private", "description": "private endpoints don't create actions"},
]


class HelaoFastAPI(FastAPI):
    """Standard FastAPI class with HELAO config attached for simpler import."""

    def __init__(self, helao_cfg: dict, helao_srv: str, *args, **kwargs):
        super().__init__(*args, **kwargs, openapi_tags=TAGS)
        self.helao_cfg = helao_cfg
        self.helao_srv = helao_srv
        self.server_cfg = self.helao_cfg["servers"][self.helao_srv]
        self.server_params = self.server_cfg.get("params", {})


class HelaoBokehAPI:
    """Standard Bokeh class with HELAO config attached for simpler import."""

    def __init__(self, helao_cfg: dict, helao_srv: str, doc):
        self.helao_srv = helao_srv
        self.helao_cfg = helao_cfg
        self.server_cfg = self.helao_cfg["servers"][self.helao_srv]
        self.server_params = self.server_cfg.get("params", {})

        self.doc_name = self.server_params.get(
            "doc_name", f"{self.helao_srv} Bokeh App"
        )
        self.doc = doc
        self.doc.title = self.doc_name
        self.vis = object()
