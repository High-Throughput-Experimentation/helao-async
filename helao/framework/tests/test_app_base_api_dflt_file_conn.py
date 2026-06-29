"""TDD tests for the default file-connection key injection (task C1).

Bug: when a ``save_data=True`` action is dispatched with EMPTY ``file_conn_keys``,
``contain_action`` skips the auto-open block (``if action.save_data and
action.file_conn_keys``) so no .hlo is ever written and ``_enqueue_phase_data``
drops all data (key=None path).

Fix: before the auto-open guard, inject the legacy default file-connection key
(``UUID(md5("None".encode()).hexdigest())``) when ``save_data=True`` and
``file_conn_keys`` is empty.

RED test written BEFORE the fix — must FAIL before fix, PASS after.
Negative case: ``save_data=False`` must NOT get a default key.
"""
import asyncio
import hashlib
from pathlib import Path
from uuid import UUID
from datetime import datetime

import pytest

from helao.framework.domain.run_models import RunAction
from helao.framework.domain import lifecycle
from helao.framework.app.base_api import FrameworkBase
from helao.framework.adapters.fs_storage import FsStorage
from helao.framework.adapters.queue_eventsink import QueueEventSink
from helao.framework.adapters.ntp_clock import NtpClock
from helao.framework.adapters.fakes.transport import FakeTransport

FIXED_NOW = datetime(2026, 6, 27, 5, 0, 0)
DFLT_KEY = UUID(hashlib.md5(str(None).encode("utf-8")).hexdigest())


def _base(tmp_path) -> FrameworkBase:
    return FrameworkBase(
        server_key="SRV",
        storage=FsStorage(save_root=str(tmp_path)),
        eventsink=QueueEventSink(),
        clock=NtpClock(),
        transport=FakeTransport(),
    )


def _save_data_action_empty_keys(**overrides) -> RunAction:
    """A save_data=True action with NO file_conn_keys (the bug trigger)."""
    kwargs = dict(
        action_name="data_act",
        action_uuid=UUID("00000000-0000-0000-0000-0000000000d1"),
        action_timestamp=FIXED_NOW,
        sequence_timestamp=FIXED_NOW,
        experiment_timestamp=FIXED_NOW,
        sequence_name="seq",
        experiment_name="exp",
        save_act=True,
        save_data=True,
        file_conn_keys=[],  # EMPTY — triggers the bug
    )
    kwargs.update(overrides)
    a = RunAction(**kwargs)
    a.action_server.server_name = "SRV"
    a.sequence_output_dir = lifecycle.sequence_output_dir(a)
    a.experiment_output_dir = lifecycle.experiment_output_dir(a)
    a.action_output_dir = lifecycle.action_output_dir(a)
    return a


def _no_save_data_action() -> RunAction:
    """A save_data=False action with NO file_conn_keys (should get NO default key)."""
    a = RunAction(
        action_name="wait_act",
        action_timestamp=FIXED_NOW,
        sequence_timestamp=FIXED_NOW,
        experiment_timestamp=FIXED_NOW,
        sequence_name="seq",
        experiment_name="exp",
        save_act=True,
        save_data=False,
        file_conn_keys=[],
    )
    a.action_server.server_name = "SRV"
    a.sequence_output_dir = lifecycle.sequence_output_dir(a)
    a.experiment_output_dir = lifecycle.experiment_output_dir(a)
    a.action_output_dir = lifecycle.action_output_dir(a)
    return a


# ---------------------------------------------------------------------------
# RED test: save_data=True + empty file_conn_keys → default key injected + .hlo written
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_contain_action_with_empty_file_conn_keys_writes_hlo(tmp_path):
    """POSITIVE: contain_action must inject the default key when file_conn_keys is empty.

    Without the fix: the injected key is missing, so a subsequent data write has
    no connection to land in and no .hlo is ever produced.
    After the fix: the default key is appended, so data enqueued against it lands
    in an .hlo. (The file is opened lazily on first write — legacy parity — so the
    test enqueues one row before finishing.)
    """
    base = _base(tmp_path)
    action = _save_data_action_empty_keys()

    session = await base.contain_action(action)
    # data lands on the injected default key (file_conn_keys[0]); the .hlo is
    # created lazily on this first write.
    await session.enqueue_data({action.file_conn_keys[0]: {"epoch_s": 1.0, "v": 1}})
    await session.finish()

    # The .hlo must exist somewhere under the save_root
    hlo_files = list(Path(tmp_path).rglob("*.hlo"))
    assert hlo_files, (
        f"Expected at least one .hlo under {tmp_path} for save_data=True action "
        f"with empty file_conn_keys, but got none. "
        f"Files found: {list(Path(tmp_path).rglob('*'))}"
    )


@pytest.mark.asyncio
async def test_contain_action_default_key_matches_legacy_dflt_key(tmp_path):
    """The injected default key must be the same UUID as legacy dflt_file_conn_key()."""
    base = _base(tmp_path)
    action = _save_data_action_empty_keys()

    await base.contain_action(action)

    # After contain_action the key should have been appended to action.file_conn_keys
    assert action.file_conn_keys, "file_conn_keys still empty after contain_action"
    assert action.file_conn_keys[0] == DFLT_KEY, (
        f"Expected legacy dflt key {DFLT_KEY}, got {action.file_conn_keys[0]}"
    )


@pytest.mark.asyncio
async def test_contain_action_existing_key_not_replaced(tmp_path):
    """When file_conn_keys is already non-empty, no default is injected."""
    base = _base(tmp_path)
    existing_key = UUID("00000000-0000-0000-0000-0000000000ee")
    action = _save_data_action_empty_keys(file_conn_keys=[existing_key])

    await base.contain_action(action)

    assert action.file_conn_keys[0] == existing_key, (
        "Existing key must not be overwritten by default"
    )
    assert len(action.file_conn_keys) == 1, (
        f"Should have exactly 1 key, got {action.file_conn_keys}"
    )


# ---------------------------------------------------------------------------
# NEGATIVE test: save_data=False → NO default key injected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_contain_action_no_data_action_gets_no_default_key(tmp_path):
    """NEGATIVE: save_data=False actions must NOT get a spurious default key.

    This guards against accidentally writing .hlo for wait/no-data actions.
    """
    base = _base(tmp_path)
    action = _no_save_data_action()

    session = await base.contain_action(action)
    await session.finish()

    assert not action.file_conn_keys, (
        f"save_data=False action must have empty file_conn_keys after contain_action, "
        f"got {action.file_conn_keys}"
    )
    hlo_files = list(Path(tmp_path).rglob("*.hlo"))
    assert not hlo_files, (
        f"save_data=False action must NOT produce .hlo files, found: {hlo_files}"
    )
