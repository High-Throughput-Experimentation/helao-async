from fastapi import FastAPI

class HelaoFastAPI(FastAPI):
    """Standard FastAPI class with HELAO config attached for simpler import."""

    def __init__(self, helao_cfg: dict, helao_srv: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helao_cfg = helao_cfg
        self.helao_srv = helao_srv


class HelaoBokehAPI:  # (curdoc):
    """Standard Bokeh class with HELAO config attached for simpler import."""

    def __init__(self, helao_cfg: dict, helao_srv: str, doc, *args, **kwargs):
        # super().__init__(*args, **kwargs)
        # self.helao_cfg = helao_cfg
        self.helao_srv = helao_srv
        self.world_cfg = helao_cfg

        self.srv_config = self.world_cfg["servers"][self.helao_srv]["params"]
        self.doc_name = self.srv_config.get("doc_name", "Bokeh App")
        self.doc = doc
        self.doc.title = self.doc_name