"""C2 gate: queue export and ``--restore`` go through ``StatePersistencePort``.

The file contract lives in ``QueuePckStore`` (paths, pickle IO, the timestamped
series and its pruning, the ``_unreadable_`` quarantine, the ``_imported_``
archive). ``QueuePersister`` keeps building and applying the payload and calls
the port for everything that touches ``STATES``. Paths are ``os.path`` strings
throughout: ``/export_queues`` and ``/import_queues`` return them on the wire.
"""

import os
import pickle
from pathlib import Path

from helao.core.tests.test_orch_dispatch_golden_master import _make_orch
from helao.core.models.orchstatus import LoopStatus
from helao.helpers.premodels import Sequence
from helao.hexagon.adapters.shared.state_persistence import QueuePckStore
from helao.hexagon.app.orch_persist import QUEUE_PCK_SCHEMA


def _states(root) -> Path:
    states = Path(root) / "STATES"
    states.mkdir(exist_ok=True)
    return states


def _listing(states: Path) -> list:
    return sorted(p.name for p in states.iterdir())


# --------------------------------------------------------------------------
# the store
# --------------------------------------------------------------------------


def test_export_path_is_the_os_path_string(tmp_path):
    # os.path.join keeps the doubled slash, str(Path(...)) collapses it
    root = str(tmp_path) + "//x"
    os.makedirs(os.path.join(root, "STATES"))

    out = QueuePckStore(root).export_queues({"schema": 1})

    assert isinstance(out, str)
    assert out == os.path.join(root, "STATES", "queues.pck")
    with open(out, "rb") as f:
        assert pickle.load(f) == {"schema": 1}


def test_timestamped_export_prunes_to_retention(tmp_path):
    states = _states(tmp_path)
    seeds = [states / f"queues_2601{d:02d}.120000.pck" for d in range(1, 8)]
    for p in seeds:
        p.write_bytes(b"x")
    (states / "queues_imported_x.pck").write_bytes(b"x")
    (states / "queues_unreadable_x.pck").write_bytes(b"x")

    new = QueuePckStore(str(tmp_path)).export_queues({"a": 1}, timestamp_pck=True)

    series = [n for n in os.listdir(states) if n[7:9].isdigit()]
    assert len(series) == 5
    assert os.path.basename(new) in series  # the new one is the newest
    assert not seeds[0].exists()
    assert not seeds[1].exists()  # the second-oldest goes too
    assert not seeds[2].exists()
    assert seeds[3].exists()  # the 5th newest of 8 is kept
    assert (states / "queues_imported_x.pck").exists()
    assert (states / "queues_unreadable_x.pck").exists()


def test_load_quarantines_an_unreadable_pickle(tmp_path):
    states = _states(tmp_path)
    (states / "queues.pck").write_bytes(b"not a pickle")

    path, payload = QueuePckStore(str(tmp_path)).load_queues()

    assert (path, payload) == (str(states / "queues.pck"), None)
    assert not (states / "queues.pck").exists()
    assert len([n for n in os.listdir(states) if "_unreadable_" in n]) == 1


def test_load_missing_returns_none_and_touches_nothing(tmp_path):
    states = _states(tmp_path)
    (states / "other.txt").write_text("x", encoding="utf-8")
    before = _listing(states)

    path, payload = QueuePckStore(str(tmp_path)).load_queues()

    assert path == os.path.join(str(tmp_path), "STATES", "queues.pck")
    assert payload is None
    assert _listing(states) == before


def test_load_strips_quotes_from_an_explicit_path(tmp_path):
    states = _states(tmp_path)
    explicit = states / "elsewhere.pck"
    explicit.write_bytes(pickle.dumps({"k": 1}))

    path, payload = QueuePckStore(str(tmp_path)).load_queues(f'"{explicit}"')

    assert path == str(explicit)
    assert payload == {"k": 1}
    assert explicit.exists()  # loading never consumes


def test_archive_consumed_renames_to_imported(tmp_path):
    states = _states(tmp_path)
    src = states / "queues.pck"
    src.write_bytes(b"x")

    archived = QueuePckStore(str(tmp_path)).archive_consumed(str(src))

    assert archived is not None and "_imported_" in archived
    assert not src.exists() and os.path.exists(archived)


# --------------------------------------------------------------------------
# the persister, over the store
# --------------------------------------------------------------------------


def _orch(root: Path, store=None):
    """A golden-master orch whose ``world_cfg["root"]`` is ``str(root)``."""
    orch = _make_orch(root)
    orch.hexagon_wiring.state_persistence = store or QueuePckStore(str(root))
    return orch


def test_schema_mismatch_is_not_archived(tmp_path):
    orch = _orch(tmp_path / "o")
    states = _states(tmp_path / "o")
    (states / "queues.pck").write_bytes(pickle.dumps({"schema": 0}))

    orch.import_queues()

    assert (states / "queues.pck").exists()
    assert not [n for n in os.listdir(states) if "_imported_" in n]


def test_successful_default_import_archives_once(tmp_path):
    a = _orch(tmp_path / "a")
    a.sequence_dq.append(Sequence(sequence_name="seq1", sequence_params={}))
    a.export_queues()

    b = _orch(tmp_path / "b")
    # B reads the file A wrote: same root
    b.hexagon_wiring.state_persistence = QueuePckStore(str(tmp_path / "a"))
    b.import_queues()

    states = tmp_path / "a" / "STATES"
    assert not (states / "queues.pck").exists()
    assert len([n for n in os.listdir(states) if "_imported_" in n]) == 1
    assert [s.sequence_name for s in b.sequence_dq] == ["seq1"]
    assert b.globalstatusmodel.loop_state == LoopStatus.stopped


def test_explicit_path_import_is_not_archived(tmp_path):
    a = _orch(tmp_path / "a")
    a.sequence_dq.append(Sequence(sequence_name="seq1", sequence_params={}))
    pck = a.export_queues()

    b = _orch(tmp_path / "b")
    b.import_queues(pck)

    assert os.path.exists(pck)
    assert [s.sequence_name for s in b.sequence_dq] == ["seq1"]
    assert not [n for n in os.listdir(tmp_path / "b" / "STATES") if "_imported_" in n]


class _RecordingStore:
    def __init__(self, payload=None):
        self.calls = []
        self._payload = payload

    def export_queues(self, payload, timestamp_pck=False):
        self.calls.append(("export", payload, timestamp_pck))
        return "STUB/queues.pck"

    def load_queues(self, pck_path=None):
        self.calls.append(("load", pck_path))
        return "STUB/queues.pck", self._payload

    def archive_consumed(self, path):
        self.calls.append(("archive", path))
        return path + ".imported"


def test_persister_routes_through_the_port(tmp_path):
    stub = _RecordingStore()
    orch = _orch(tmp_path / "o", stub)

    out = orch.export_queues()

    assert out == "STUB/queues.pck"
    (call,) = stub.calls
    assert call[0] == "export" and call[1]["schema"] == QUEUE_PCK_SCHEMA

    # nothing to load: no archive
    stub.calls.clear()
    assert orch.import_queues() == "STUB/queues.pck"
    assert stub.calls == [("load", None)]

    # a good payload: loaded, applied, archived once
    good = _orch(tmp_path / "g")
    good.sequence_dq.append(Sequence(sequence_name="seq1", sequence_params={}))
    payload = pickle.loads(pickle.dumps(_payload_of(good)))
    stub2 = _RecordingStore(payload)
    dst = _orch(tmp_path / "d", stub2)
    dst.import_queues()
    assert stub2.calls == [("load", None), ("archive", "STUB/queues.pck")]


def _payload_of(orch) -> dict:
    rec = _RecordingStore()
    orch.hexagon_wiring.state_persistence = rec
    orch.export_queues()
    return rec.calls[0][1]
