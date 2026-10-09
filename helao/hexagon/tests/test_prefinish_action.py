"""Action-level pre-finish hooks through a real ActionHost (spec §5.1 row 1).

Same harness as test_action_writes_artifacts.py: the test deployment's
ws_simulator, startup handlers run by hand, one ``acquire_data`` action.
"""

import tempfile
import textwrap
from pathlib import Path

import pytest

from helao.core.hooks import HookConfigError
from helao.helpers.yml_tools import yml_load
from helao.hexagon.tests.test_action_writes_artifacts import _run_one_action

BOOM = """
from helao.core.hooks import FinishHook


class Hook(FinishHook):
    async def run(self, ctx):
        raise RuntimeError("boom from test hook")
"""


def _act_yml(root: str) -> dict:
    ymls = [p for p in Path(root).rglob("*-act.yml")]
    assert len(ymls) == 1, ymls
    return yml_load(ymls[0].read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_new_key_by_exact_action_name_runs_hlo_to_csv():
    root = tempfile.mkdtemp(prefix="helao_prefinish_")
    names = await _run_one_action(
        root, prefinish_hooks={"hlo_to_csv": ["acquire_data"]}
    )
    assert any(n.endswith(".csv") for n in names), names


@pytest.mark.asyncio
async def test_new_key_for_another_action_name_does_not_run():
    root = tempfile.mkdtemp(prefix="helao_prefinish_")
    names = await _run_one_action(
        root, prefinish_hooks={"hlo_to_csv": ["not_this_action"]}
    )
    assert not any(n.endswith(".csv") for n in names), names


@pytest.mark.asyncio
async def test_raising_hook_is_recorded_and_the_action_still_finishes(tmp_path):
    hook_path = tmp_path / "boom_hook.py"
    hook_path.write_text(textwrap.dedent(BOOM), encoding="utf-8")
    root = tempfile.mkdtemp(prefix="helao_prefinish_")
    await _run_one_action(root, prefinish_hooks={str(hook_path): ["*"]})
    meta = _act_yml(root)
    assert "finished" in str(meta["action_status"])
    assert meta["prefinish_errors"][0]["hook"] == str(hook_path)
    assert "boom from test hook" in meta["prefinish_errors"][0]["error"]


def test_old_and_new_key_together_refused_at_startup():
    from helao.deploy.test.servers.action.ws_simulator import makeApp
    from helao.helpers import config_loader

    config_loader.CONFIG = {
        "root": tempfile.mkdtemp(prefix="helao_prefinish_"),
        "dummy": True,
        "simulation": True,
        "run_type": "simulation",
        "servers": {
            "SIM": {
                "host": "127.0.0.1",
                "port": 8002,
                "group": "action",
                "params": {"columns": {"a": 1, "b": 2}},
                "hlo_postprocess_libs": ["hlo_to_csv"],
                "prefinish_hooks": {"hlo_to_csv": ["*"]},
            }
        },
    }
    with pytest.raises(HookConfigError):
        makeApp("SIM")
