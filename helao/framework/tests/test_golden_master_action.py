"""Golden-master parity test for the action HLO/.act byte format.

HOW THIS GOLDEN MASTER WAS PRODUCED
-----------------------------------
Driving the legacy ``helao.core.servers.base.Active`` in-process is impractical:
``Active`` requires a fully constructed ``Base`` (a live FastAPI app with a
``.driver``, NTP offset state, ``helaodirs.save_root``, the ``data_q`` publisher,
status/data WebSocket publishers and the background ``log_data_task``). Standing
all of that up in a unit test would test the harness, not the format.

Instead the golden ``.hlo`` fixture below is a COMMITTED fixture asserted to be
byte-identical to the legacy HLO layout, which is fully specified (and cited
here) from ``helao/core/servers/base.py``:

* The header is written first, with a trailing newline ensured -- base.py
  ``Active.log_data_set_output_file`` lines 1567-1571.
* The HLO ``%%\n`` header/data separator is written once, before the first data
  row -- base.py ``Active.log_data_task`` lines 1653-1660.
* Each dict data row is serialised with ``json.dumps(sample_data)`` and written
  with a trailing newline ensured -- base.py lines 1662-1671 and
  ``Active.write_live_data`` lines 1429-1439.

So the canonical legacy bytes for header ``H`` and dict rows ``r1, r2, ...`` are::

    H\\n%%\\njson.dumps(r1)\\njson.dumps(r2)\\n...

The new framework path produces exactly these bytes:
``FsStorage.open_hlo`` writes ``header (+\\n) + "%%\\n"`` and ``append_hlo`` writes
``json.dumps(row) + "\\n"`` (driven by ``ActionSession._write_live_rows`` ->
``json.dumps(row)``). This test drives the NEW path end-to-end through the real
``FsStorage`` adapter and asserts the on-disk ``.hlo`` matches the committed
golden bytes constructed per the legacy spec above; it also asserts a ``.act``
meta file is produced. If the framework HLO byte layout ever drifts from the
legacy format, this test fails.
"""
import asyncio
import json
from datetime import datetime
from pathlib import Path
from uuid import UUID

from helao.framework.models.errors import ErrorCodes
from helao.framework.models.hlostatus import HloStatus
from helao.framework.domain.run_models import RunAction
from helao.framework.domain.executor import Executor
from helao.framework.domain.action_session import ActionSession
from helao.framework.adapters.fs_storage import FsStorage
from helao.framework.adapters.queue_eventsink import QueueEventSink
from helao.framework.adapters.fakes.clock import FakeClock
from helao.framework.adapters.fakes.transport import FakeTransport

FIXED_NOW = datetime(2026, 6, 22, 14, 5, 6)
ACTION_UUID = UUID("00000000-0000-0000-0000-0000000000aa")
FILE_CONN = UUID("00000000-0000-0000-0000-0000000000ff")

HEADER = "epoch_ns: 1700000000000000000"
ROWS = [{"t": 0.0, "signal": 1.5}, {"t": 0.1, "signal": 2.5}]


def _legacy_golden_bytes(header: str, rows: list[dict]) -> str:
    """Reconstruct the legacy HLO bytes per the base.py format cited in the module docstring."""
    out = header
    if not out.endswith("\n"):
        out += "\n"
    out += "%%\n"  # base.py:1653-1660
    for row in rows:
        out += json.dumps(row) + "\n"  # base.py:1662-1671 / write_live_data 1429-1439
    return out


def _run_action() -> RunAction:
    return RunAction(
        action_name="dummy_act",
        action_abbr="dummy_act",
        action_uuid=ACTION_UUID,
        action_timestamp=FIXED_NOW,
        sequence_timestamp=FIXED_NOW,
        experiment_timestamp=FIXED_NOW,
        sequence_name="seq",
        experiment_name="exp",
        action_output_dir="26.25/0622/0__0__srv__dummy_act",
        save_act=True,
        save_data=True,
        file_conn_keys=[FILE_CONN],
    )


def _drive_new_path(save_root: str) -> RunAction:
    storage = FsStorage(save_root=save_root)
    action = _run_action()
    session = ActionSession(
        action,
        storage=storage,
        eventsink=QueueEventSink(),
        clock=FakeClock(),
        executor=Executor(active=_Wrap(action)),
        transport=FakeTransport(),
        now_factory=lambda: FIXED_NOW,
    )

    async def _go():
        await session.myinit()
        await session.open_file(FILE_CONN, header=HEADER)
        for row in ROWS:
            await session.enqueue_data({FILE_CONN: row})
        return await session.finish()

    return asyncio.run(_go())


class _Wrap:
    def __init__(self, action):
        self.action = action


def test_new_path_hlo_matches_legacy_golden_bytes(tmp_path):
    result = _drive_new_path(str(tmp_path))
    assert HloStatus.finished in result.action_status

    hlo_files = list(Path(tmp_path).rglob("*.hlo"))
    assert len(hlo_files) == 1, f"expected exactly one .hlo, got {hlo_files}"
    actual = hlo_files[0].read_text(encoding="utf-8")

    expected = _legacy_golden_bytes(HEADER, ROWS)
    assert actual == expected, (
        "framework HLO bytes drifted from legacy format\n"
        f"--- expected ---\n{expected!r}\n--- actual ---\n{actual!r}"
    )


def test_new_path_writes_act_meta(tmp_path):
    _drive_new_path(str(tmp_path))
    act_files = list(Path(tmp_path).rglob("*.act"))
    assert len(act_files) == 1, f"expected exactly one .act meta, got {act_files}"
    # the .act meta round-trips as YAML carrying this action's uuid
    text = act_files[0].read_text(encoding="utf-8")
    assert str(ACTION_UUID) in text
    assert "action_name: dummy_act" in text


def test_golden_fixture_matches_committed_file(tmp_path):
    """Pin the golden bytes to a committed fixture so accidental format drift is loud."""
    fixture = Path(__file__).parent / "fixtures" / "golden_action.hlo"
    assert fixture.exists(), (
        "missing committed golden fixture "
        "helao/framework/tests/fixtures/golden_action.hlo"
    )
    result = _drive_new_path(str(tmp_path))
    assert HloStatus.finished in result.action_status
    actual = list(Path(tmp_path).rglob("*.hlo"))[0].read_text(encoding="utf-8")
    assert actual == fixture.read_text(encoding="utf-8")
