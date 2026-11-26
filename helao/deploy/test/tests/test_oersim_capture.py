"""``oersim_runner._capture`` reads output first, then params."""

import asyncio
from types import SimpleNamespace

from helao.deploy.test.runners import oersim_runner as r


class _Orch:
    async def run_action(self, action):
        return SimpleNamespace(
            meta_dict={"action_output": {"_feature": [1]}},
            action_params={"plate_id": 3},
        )


def test_capture_output_first_then_params():
    r.GLOBALS.clear()
    asyncio.run(
        r._capture(_Orch(), None, {"_feature": "_feature", "plate_id": "p"})  # type: ignore[arg-type]
    )
    assert r.GLOBALS == {"_feature": [1], "p": 3}
