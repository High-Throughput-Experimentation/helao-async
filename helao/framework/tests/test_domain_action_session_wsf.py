"""WS-F tests: HLO header stamping + finish-time run-dir relocation.

Two deliverables from SP8 Wave-2 WS-F:

1. **HloHeaderModel stamping** -- when ``open_file`` is called with an empty/blank
   header (the host's ``contain_action`` auto-open path), ``ActionSession`` stamps
   a full :class:`HloHeaderModel` (``action_name`` / ``epoch_ns`` from the injected
   clock / ``hlo_version`` / ``column_headings`` from the action's json data keys)
   and serializes it (via the Storage port) into the file header. An explicit
   non-empty header is preserved verbatim.

2. **Whole-run-directory relocation at finish** -- a finished, non-manual action's
   output dir is relocated from the active location to the synced location
   (``RUNS_SYNCED/<action_output_dir>``). Manual actions are NOT moved, and a
   relocation failure is swallowed (logged, never crashes ``finish``).
"""

import asyncio
from datetime import datetime
from uuid import UUID

import pytest
import ruamel.yaml

from helao.framework.models.hlostatus import HloStatus
from helao.framework.domain.run_models import RunAction
from helao.framework.domain.executor import Executor
from helao.framework.domain.action_session import ActionSession

from helao.framework.adapters.fakes.storage import FakeStorage
from helao.framework.adapters.fakes.eventsink import FakeEventSink
from helao.framework.adapters.fakes.clock import FakeClock
from helao.framework.adapters.fakes.transport import FakeTransport

FIXED_NOW = datetime(2026, 6, 22, 14, 5, 6)
FINISH_NOW = datetime(2026, 6, 22, 14, 30, 0)
FIXED_UUID = UUID("00000000-0000-0000-0000-0000000000aa")
FILE_CONN = UUID("00000000-0000-0000-0000-0000000000ff")
EPOCH_NS = 1_700_000_000_000_000_000


def _run_action(**overrides):
    kwargs = dict(
        action_name="dummy_act",
        action_uuid=FIXED_UUID,
        action_timestamp=FIXED_NOW,
        sequence_timestamp=FIXED_NOW,
        experiment_timestamp=FIXED_NOW,
        sequence_uuid=FIXED_UUID,
        experiment_uuid=FIXED_UUID,
        sequence_name="seq",
        experiment_name="exp",
        action_output_dir="26.25/0622/x__0__srv__dummy_act",
        save_act=True,
        save_data=True,
        file_conn_keys=[FILE_CONN],
    )
    kwargs.update(overrides)
    return RunAction(**kwargs)


class _Wrap:
    def __init__(self, act):
        self.action = act


def _make_session(action=None, storage=None):
    storage = storage or FakeStorage()
    if action is None:
        action = _run_action()
    session = ActionSession(
        action,
        storage=storage,
        eventsink=FakeEventSink(),
        clock=FakeClock(start_ns=EPOCH_NS),
        executor=Executor(active=_Wrap(action)),
        transport=FakeTransport(),
        now_factory=lambda: FINISH_NOW,
        uuid_factory=lambda: FIXED_UUID,
    )
    return session, storage


def _parse_header(buf: str) -> dict:
    """Parse the YAML header preceding the '%%' separator into a dict."""
    header_text = buf.split("%%\n", 1)[0]
    if not header_text.strip():
        return {}
    yaml = ruamel.yaml.YAML(typ="safe")
    return yaml.load(header_text)


# --- 1. header stamping --------------------------------------------------------


def test_empty_header_autoopen_stamps_full_hloheader():
    session, storage = _make_session()
    asyncio.run(session.open_file(FILE_CONN, header=""))
    relpath = session._conn_relpath(FILE_CONN)
    parsed = _parse_header(storage.hlo_buffers[relpath])
    assert parsed.get("action_name") == "dummy_act"
    assert parsed.get("epoch_ns") == EPOCH_NS
    assert parsed.get("hlo_version")  # auto-stamped, non-empty


def test_empty_header_column_headings_from_json_data_keys():
    """When the action carries json_data_keys, they become column_headings."""
    action = _run_action()
    # the action model has no json_data_keys field; the host attaches it (e.g.
    # from the file-conn params) -- prove the wiring picks it up when present.
    object.__setattr__(action, "json_data_keys", ["t", "signal"])
    session, storage = _make_session(action=action)
    asyncio.run(session.open_file(FILE_CONN, header=""))
    parsed = _parse_header(storage.hlo_buffers[session._conn_relpath(FILE_CONN)])
    assert parsed.get("column_headings") == ["t", "signal"]


def test_blank_header_treated_as_empty_and_stamped():
    session, storage = _make_session()
    asyncio.run(session.open_file(FILE_CONN, header="   \n  "))
    relpath = session._conn_relpath(FILE_CONN)
    parsed = _parse_header(storage.hlo_buffers[relpath])
    assert parsed.get("action_name") == "dummy_act"
    assert parsed.get("epoch_ns") == EPOCH_NS


def test_explicit_header_preserved_verbatim():
    session, storage = _make_session()
    explicit = "epoch_ns: 1700000000000000000"
    asyncio.run(session.open_file(FILE_CONN, header=explicit))
    relpath = session._conn_relpath(FILE_CONN)
    buf = storage.hlo_buffers[relpath]
    # exact bytes preserved (header + newline + separator)
    assert buf == explicit + "\n%%\n"


# --- 2. finish-time run-dir relocation -----------------------------------------


def test_finish_promotes_run_dir_recursive_for_non_manual():
    """Task 5b: non-manual finish promotes the action leaf dir (recursive)
    via the file-granular ``promote_run_dir`` primitive, resolving manual/
    sync_data from the action (manual=False, sync_data=True here)."""
    session, storage = _make_session()
    out_dir = str(session.action.action_output_dir)
    asyncio.run(session.finish())
    assert len(storage.promote_calls) == 1
    called_out_dir, manual, sync_data, recursive = storage.promote_calls[0]
    assert called_out_dir == out_dir
    assert manual is False
    assert sync_data is True
    assert recursive is True


def test_finish_promotes_manual_action_to_diag():
    """Task 5b: manual finish still calls promote_run_dir but with manual=True
    (legacy move_dir routes manual to RUNS_DIAG, it does NOT skip)."""
    action = RunAction(action_name="manual_act", save_act=True, save_data=False)
    session, storage = _make_session(action=action)
    asyncio.run(session.promote_manual())
    asyncio.run(session.finish())
    assert len(storage.promote_calls) == 1
    _out_dir, manual, sync_data, recursive = storage.promote_calls[0]
    assert manual is True
    assert sync_data is True  # action only set save_data=False; sync_data default True
    assert recursive is True


def test_finish_swallows_promotion_failure():
    class _BoomStorage(FakeStorage):
        async def promote_run_dir(self, out_dir, *, manual, sync_data, recursive):
            raise OSError("disk gone")

    session, storage = _make_session(storage=_BoomStorage())
    # finish must complete despite the promotion raising
    result = asyncio.run(session.finish())
    assert HloStatus.finished in result.action_status


def test_finish_closes_handles_before_promoting():
    """Open handles are closed before the dir is promoted (no open files mid-move)."""
    order = []

    class _OrderStorage(FakeStorage):
        async def close_hlo(self, handle):
            order.append("close")
            await super().close_hlo(handle)

        async def promote_run_dir(self, out_dir, *, manual, sync_data, recursive):
            order.append("promote")
            return await super().promote_run_dir(
                out_dir, manual=manual, sync_data=sync_data, recursive=recursive
            )

    session, storage = _make_session(storage=_OrderStorage())
    asyncio.run(session.open_file(FILE_CONN, header=""))
    asyncio.run(session.finish())
    assert "close" in order and "promote" in order
    assert order.index("close") < order.index("promote")
