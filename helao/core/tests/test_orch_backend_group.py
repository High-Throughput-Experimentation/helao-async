"""RemoteBackend additions used by the /group page."""

import pytest

from helao.core.error import ErrorCodes


def _backend(resp=None, err=ErrorCodes.none):
    from helao.ui.shared.operator.orch_backend import RemoteBackend

    calls = []

    async def dispatch(
        server_key, host, port, endpoint, params_dict=None, json_dict=None
    ):
        calls.append((endpoint, params_dict))
        return resp, err

    # only the transport fields _call reads
    b = RemoteBackend.__new__(RemoteBackend)
    b.orch_key, b.host, b.port = "ORCH", "127.0.0.1", 8001
    b._dispatch = dispatch  # pyright: ignore[reportAttributeAccessIssue]
    return b, calls


@pytest.mark.asyncio
async def test_get_object_posts_kind_and_uuid_as_strings():
    b, calls = _backend(resp={"action_name": "a"})
    assert await b.get_object("action", 123) == {"action_name": "a"}
    assert calls == [("get_object", {"kind": "action", "uuid": "123"})]


@pytest.mark.asyncio
async def test_get_object_miss_is_none():
    b, _ = _backend(resp=None)
    assert await b.get_object("experiment", "x") is None


@pytest.mark.asyncio
async def test_strict_control_calls_raise_and_default_ones_do_not():
    b, calls = _backend(err=ErrorCodes.http)
    await b.start()
    with pytest.raises(RuntimeError, match="start failed"):
        await b.start(strict=True)
    with pytest.raises(RuntimeError, match="stop failed"):
        await b.stop(strict=True)
    with pytest.raises(RuntimeError, match="estop_orch failed"):
        await b.estop(strict=True)
    with pytest.raises(RuntimeError, match="clear_estop failed"):
        await b.clear_estop(strict=True)
    assert ("stop", {"reset_run_id": False}) in calls


def test_tree_pane_is_shared_by_the_operator():
    from helao.ui.reflex import operator, tree_pane

    assert operator._tree_pane is tree_pane.tree_pane
