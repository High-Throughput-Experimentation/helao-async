from pathlib import Path

from harness.deploy_collisions import collisions


def _touch(root: Path, rel: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("", encoding="utf-8")


def test_reports_only_names_in_two_or_more_deployments(tmp_path):
    for dep in ("a", "b"):
        _touch(tmp_path, f"{dep}/servers/action/x.py")
    _touch(tmp_path, "a/processors/p1.py")
    _touch(tmp_path, "b/processors/p1.py")
    _touch(tmp_path, "a/experiments/E_exp.py")
    _touch(tmp_path, "a/servers/visualizer/v.py")
    _touch(tmp_path, "b/servers/gamry/bokeh/v.py")
    _touch(tmp_path, "b/servers/reflex/only_b.py")
    out = collisions(tmp_path)
    assert out["processors"] == {"p1": ["a", "b"]}
    assert out["bokeh"] == {"v": ["a", "b"]}
    assert out["experiments"] == {}
    assert out["reflex"] == {}
