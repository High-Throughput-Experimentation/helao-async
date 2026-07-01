"""mount_visualizers isolates a failing per-instrument visualizer.

A visualizer whose module fails to import or raises in its constructor must not
abort the whole mount and drop every later server's visualizer (a broken
pal_vis was swallowing spec_vis). Each mount is isolated; the rest still load.
"""
from helao.framework.adapters import vis_subscriber as vs


class _Good:
    def __init__(self, vis_serv, serv_key):
        self.serv_key = serv_key


class _Bad:
    def __init__(self, vis_serv, serv_key):
        raise RuntimeError("constructor boom")


class _Vis:
    # ordered so the failing PAL is mounted before SPEC_T
    world_cfg = {
        "servers": {
            "PAL": {"action_vis": "pal_vis"},
            "SPEC_T": {"action_vis": "spec_vis"},
        }
    }


class _App:
    server_params = {}
    vis = _Vis()


def test_failing_visualizer_does_not_drop_the_rest(monkeypatch):
    def fake_import(module_name, class_name=vs.VIS_CLASS_NAME):
        return _Bad if module_name == "pal_vis" else _Good

    monkeypatch.setattr(vs, "import_vis_class", fake_import)

    instances = vs.mount_visualizers(_App(), "action_vis")

    # PAL raised and was skipped; SPEC_T still mounted.
    assert len(instances) == 1
    assert instances[0].serv_key == "SPEC_T"
