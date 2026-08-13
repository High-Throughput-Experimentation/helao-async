"""The ANA server's queued analyses survive the process that queued them.

``AnalysisSyncer.task_queue`` is an in-memory ``asyncio.Queue`` of tuples
holding a live ``LocalLoader``, and the action that requests an analysis returns
as soon as it has enqueued -- so a restart used to drop every queued analysis
while the action's own record read *done*, leaving no file and no log line
anywhere. These tests pin the durable request journal that closes that hole, and
in particular the parts of it where a plausible-looking implementation is silently
wrong:

* the entry must exist **before** the item reaches the queue (the other order
  loses exactly the crash window the journal is for), so one test intercepts
  ``task_queue.put`` and asserts from inside it;
* clearing must be keyed by the *journal key*, not by the task name -- the key
  carries the loader target and analysis class as well as the process uuid;
* the sweep must survive its own bad inputs: a corrupt entry, a vanished zip and
  an analysis this host does not serve each have a different disposition, and
  none of them may stop the other entries from recovering.

Everything here is hermetic: ``tmp_path`` only, no share, no network, no real
analysis, and no ``Base``. The syncer is built through ``object.__new__`` with
only the attributes under test set (the same seam priv's
``test_processing_recovery.py`` uses for ``BatchConverter``), because
``AnalysisSyncer.__init__`` builds an S3 loader and starts worker coroutines.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, cast
from uuid import UUID

import pytest

from helao.core.drivers.data import analysis_driver as m

PROC_A = UUID("11111111-1111-1111-1111-111111111111")
PROC_B = UUID("22222222-2222-2222-2222-222222222222")
ACTION_UUID = UUID("33333333-3333-3333-3333-333333333333")


class _StubLogger:
    """Logger stand-in recording what the code under test emitted.

    ``alert`` is a ``helao_logging`` addition attached to logger *instances*, so
    a stub has to carry it explicitly; the recovery sweep's alerts are the
    mechanism by which a lost analysis stops being invisible, and a stub without
    ``alert`` would turn each of them into an ``AttributeError`` and hide the
    thing being tested.
    """

    def __init__(self):
        self.alerts = []
        self.errors = []
        self.warnings = []
        self.infos = []

    def info(self, msg="", *a, **k):
        self.infos.append(str(msg))

    def debug(self, *a, **k):
        pass

    def warning(self, msg="", *a, **k):
        self.warnings.append(str(msg))

    def error(self, msg="", *a, **k):
        self.errors.append(str(msg))

    def alert(self, msg="", *a, **k):
        self.alerts.append(str(msg))


class _FakeLoader:
    """``LocalLoader`` stand-in: the one attribute the journal reads.

    ``LocalLoader.__init__`` stores the absolute data path on ``self.target``,
    which is the only piece of a loader a journal entry records and the only
    piece needed to rebuild one.
    """

    def __init__(self, data_path: str):
        self.target = os.path.abspath(data_path)


class _AnaA:
    """Analysis class stand-in. Only its ``__name__`` reaches the journal."""


class _AnaB:
    pass


@pytest.fixture
def logger(monkeypatch):
    """Replace the module logger for the duration of one test."""
    stub = _StubLogger()
    monkeypatch.setattr(m, "LOGGER", stub)
    return stub


def _syncer(journal_dir, logger=None) -> m.AnalysisSyncer:
    """Build a syncer with only the attributes the journal paths touch.

    ``object.__new__`` rather than ``__init__``: the real constructor installs a
    shared S3 loader (reading credentials) and creates ``max_tasks`` worker
    tasks, none of which any journal behaviour depends on.
    """
    syncer = object.__new__(m.AnalysisSyncer)
    syncer.journal_dir = str(journal_dir) if journal_dir else None
    syncer.task_queue = asyncio.Queue()
    syncer.task_set = set()
    syncer.running_tasks = {}
    syncer.config_dict = {}
    return syncer


def _tup(zip_path, process_uuid=PROC_A, ana_cls: type = _AnaA, params=None) -> tuple:
    """One calc tuple in the shape ``enqueue_calc`` accepts.

    Returned as a bare ``tuple`` because the real annotation names
    ``LocalLoader`` and ``BaseAnalysis``, neither of which a stand-in satisfies;
    spelling the stub types out would make every call site a type error.
    """
    return (
        process_uuid,
        _FakeLoader(str(zip_path)),
        {"foo": 1} if params is None else params,
        ana_cls,
        ACTION_UUID,
    )


def _zip(tmp_path, name="seq.zip"):
    """A stand-in data path. The sweep only asks whether it exists."""
    path = tmp_path / name
    path.write_bytes(b"not really a zip")
    return path


# ---------------------------------------------------------------------------
# Key derivation
# ---------------------------------------------------------------------------


def test_journal_key_is_deterministic_and_identifies_the_request():
    """Same request in, same file name out -- which is what makes re-journalling
    an overwrite -- and each of the three identity components changes it."""
    key = m.analysis_journal_key("/data/seq.zip", PROC_A, "AnaA")
    assert key == m.analysis_journal_key("/data/seq.zip", PROC_A, "AnaA")
    assert key.startswith(f"{PROC_A}__AnaA__")
    assert key.endswith(m.ANA_JOURNAL_SUFFIX)
    assert key != m.analysis_journal_key("/data/other.zip", PROC_A, "AnaA")
    assert key != m.analysis_journal_key("/data/seq.zip", PROC_B, "AnaA")
    assert key != m.analysis_journal_key("/data/seq.zip", PROC_A, "AnaB")


def test_journal_key_is_a_usable_file_name():
    """The target is folded into a digest precisely because it is a path; a key
    carrying a separator would silently write outside the journal dir."""
    key = m.analysis_journal_key(
        "/mnt/some/deep/path with spaces/seq.zip", PROC_A, "AnaA"
    )
    assert os.sep not in key and "/" not in key


# ---------------------------------------------------------------------------
# Journalling on enqueue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enqueue_writes_exactly_one_entry_with_the_rebuild_fields(
    tmp_path, logger
):
    """One queued analysis, one entry, carrying everything a rebuild needs."""
    journal = tmp_path / "ana_pending"
    syncer = _syncer(journal)
    zip_path = _zip(tmp_path)

    await syncer.enqueue_calc(_tup(zip_path))

    entries = m.list_journal_entries(str(journal))
    assert len(entries) == 1
    payload = json.loads((journal / entries[0]).read_text())
    assert payload["target"] == str(zip_path)
    assert payload["process_uuid"] == str(PROC_A)
    assert payload["analysis_class"] == "_AnaA"
    assert payload["params"] == {"foo": 1}
    assert payload["analysis_action_uuid"] == str(ACTION_UUID)
    assert payload["schema"] == m.ANA_JOURNAL_SCHEMA
    assert payload["queued_at"] > 0
    # The queue still got the item; journalling is additive.
    assert syncer.task_queue.qsize() == 1
    assert syncer.task_set == {PROC_A}


@pytest.mark.asyncio
async def test_entry_is_on_disk_before_the_queue_receives_the_item(tmp_path, logger):
    """The ordering, asserted from inside ``put``.

    A crash in the window between the two must leave a recoverable record. With
    the write second, that window loses the request entirely -- and no test that
    only inspects the end state can tell the two orders apart.
    """
    journal = tmp_path / "ana_pending"
    syncer = _syncer(journal)
    zip_path = _zip(tmp_path)
    seen = {}

    real_put = syncer.task_queue.put

    async def _spy_put(item):
        seen["entries_at_put"] = m.list_journal_entries(str(journal))
        await real_put(item)

    syncer.task_queue.put = _spy_put  # type: ignore[method-assign]
    await syncer.enqueue_calc(_tup(zip_path))

    assert len(seen["entries_at_put"]) == 1


@pytest.mark.asyncio
async def test_the_same_request_journalled_twice_is_one_file(tmp_path, logger):
    """Re-enqueueing the same request overwrites its entry.

    This is the recovery path's own behaviour -- it re-enqueues, which
    re-journals -- so an accumulating key would grow the journal by one file per
    restart forever.
    """
    journal = tmp_path / "ana_pending"
    syncer = _syncer(journal)
    zip_path = _zip(tmp_path)

    await syncer.enqueue_calc(_tup(zip_path))
    await syncer.enqueue_calc(_tup(zip_path))

    assert len(m.list_journal_entries(str(journal))) == 1


@pytest.mark.asyncio
async def test_two_different_requests_are_two_entries(tmp_path, logger):
    """Deduplication is per request, not per process uuid: the same process
    analysed by two different classes is two pieces of work."""
    journal = tmp_path / "ana_pending"
    syncer = _syncer(journal)
    zip_path = _zip(tmp_path)

    await syncer.enqueue_calc(_tup(zip_path, ana_cls=_AnaA))
    await syncer.enqueue_calc(_tup(zip_path, ana_cls=_AnaB))
    await syncer.enqueue_calc(_tup(zip_path, process_uuid=PROC_B))

    assert len(m.list_journal_entries(str(journal))) == 3


# ---------------------------------------------------------------------------
# Clearing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_completion_removes_the_entry(tmp_path, logger):
    """The real completion path: ``syncer``'s ``finally``, driven end to end
    with a stubbed ``sync_ana`` so no analysis runs."""
    journal = tmp_path / "ana_pending"
    syncer = _syncer(journal)
    zip_path = _zip(tmp_path)
    calls = []

    async def _fake_sync_ana(calc_tup, retries=3):
        calls.append(calc_tup[0])
        return True

    syncer.sync_ana = _fake_sync_ana  # type: ignore[method-assign]
    await syncer.enqueue_calc(_tup(zip_path))
    assert len(m.list_journal_entries(str(journal))) == 1

    worker = asyncio.create_task(syncer.syncer())
    await asyncio.wait_for(syncer.task_queue.join(), timeout=5)
    worker.cancel()

    assert calls == [PROC_A]
    assert m.list_journal_entries(str(journal)) == []
    assert syncer.task_set == set()


@pytest.mark.asyncio
async def test_a_failing_analysis_also_clears_its_entry(tmp_path, logger):
    """Completion, not success, is what clears an entry.

    Keeping a failed analysis journalled would re-run a permanently-failing
    analysis at every restart forever. The failure is already alerted by the
    worker, which this asserts so the entry's removal is not the only trace.
    """
    journal = tmp_path / "ana_pending"
    syncer = _syncer(journal)
    zip_path = _zip(tmp_path)

    async def _boom(calc_tup, retries=3):
        raise RuntimeError("analysis exploded")

    syncer.sync_ana = _boom  # type: ignore[method-assign]
    await syncer.enqueue_calc(_tup(zip_path))

    worker = asyncio.create_task(syncer.syncer())
    await asyncio.wait_for(syncer.task_queue.join(), timeout=5)
    worker.cancel()

    assert m.list_journal_entries(str(journal)) == []
    assert any("ana syncer worker" in a for a in logger.alerts)


@pytest.mark.asyncio
async def test_the_key_written_is_the_key_cleared(tmp_path, logger):
    """The write key and the clear key are the same string.

    If they diverged, entries would accumulate forever and every restart would
    re-enqueue analyses that had already completed -- a failure that looks like
    success from every other angle, since the analysis itself runs fine. Pinned
    three ways: the file the enqueue actually created is named by
    ``_journal_key``, that key round-trips through ``journal_entry_path``, and
    clearing with the same tuple empties the journal.
    """
    journal = tmp_path / "ana_pending"
    syncer = _syncer(journal)
    tup = _tup(_zip(tmp_path))

    await syncer.enqueue_calc(tup)
    written = m.list_journal_entries(str(journal))
    key = syncer._journal_key(tup)

    assert written == [key]
    assert os.path.isfile(m.journal_entry_path(str(journal), str(key)))
    syncer.journal_clear(tup)
    assert m.list_journal_entries(str(journal)) == []


@pytest.mark.asyncio
async def test_sync_exit_callback_keys_on_the_task_name_not_the_journal_key(
    tmp_path, logger
):
    """What the done-callback seam actually receives, pinned both ways.

    ``task.get_name()`` is an *asyncio task* name. For the only tasks this class
    creates it is ``syncer_loop__<i>``, which is not in ``running_tasks`` (keyed
    by process uuid), so the callback is inert on the live path -- the real clear
    is :meth:`journal_clear` from ``syncer``'s ``finally``. Handed a task named
    for a process uuid, as :class:`HelaoSyncer` names them, it does clear.
    """
    journal = tmp_path / "ana_pending"
    syncer = _syncer(journal)
    tup = _tup(_zip(tmp_path))
    await syncer.enqueue_calc(tup)

    async def _noop():
        return None

    # The live shape: a worker-loop task name, with running_tasks keyed by uuid.
    loop_task = asyncio.create_task(_noop(), name="syncer_loop__0")
    await loop_task
    syncer.running_tasks = {str(PROC_A): loop_task}
    syncer.sync_exit_callback(loop_task)
    assert m.list_journal_entries(str(journal)) == [syncer._journal_key(tup)]
    assert syncer.running_tasks == {str(PROC_A): loop_task}

    # The inherited shape: a task named for the process uuid.
    uuid_task = asyncio.create_task(_noop(), name=str(PROC_A))
    await uuid_task
    syncer.running_tasks = {str(PROC_A): uuid_task}
    syncer.task_set = {str(PROC_A)}
    syncer.sync_exit_callback(uuid_task)
    assert m.list_journal_entries(str(journal)) == []
    assert syncer.running_tasks == {}


@pytest.mark.asyncio
async def test_clearing_one_request_leaves_the_other_entries_alone(tmp_path, logger):
    """Keyed by the journal key, not the task name.

    Two requests sharing a process uuid differ only in their analysis class, so
    an implementation that cleared by task name (the process uuid, all a
    done-callback ever sees) would delete work that never ran.
    """
    journal = tmp_path / "ana_pending"
    syncer = _syncer(journal)
    zip_path = _zip(tmp_path)
    tup_a = _tup(zip_path, ana_cls=_AnaA)
    tup_b = _tup(zip_path, ana_cls=_AnaB)

    await syncer.enqueue_calc(tup_a)
    await syncer.enqueue_calc(tup_b)
    syncer.journal_clear(tup_a)

    remaining = m.list_journal_entries(str(journal))
    assert remaining == [m.analysis_journal_key(str(zip_path), PROC_A, "_AnaB")]


@pytest.mark.asyncio
async def test_clear_by_process_removes_every_entry_for_that_uuid(tmp_path, logger):
    """The done-callback seam's best-effort route, pinned as the superset it is."""
    journal = tmp_path / "ana_pending"
    syncer = _syncer(journal)
    zip_path = _zip(tmp_path)

    await syncer.enqueue_calc(_tup(zip_path, ana_cls=_AnaA))
    await syncer.enqueue_calc(_tup(zip_path, ana_cls=_AnaB))
    await syncer.enqueue_calc(_tup(zip_path, process_uuid=PROC_B))

    syncer.journal_clear_by_process(str(PROC_A))

    remaining = m.list_journal_entries(str(journal))
    assert len(remaining) == 1
    assert remaining[0].startswith(str(PROC_B))


# ---------------------------------------------------------------------------
# Degradation: journalling off, or failing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_journalling_disabled_still_enqueues(tmp_path, logger):
    """No ``STATES`` root means no journal and no behaviour change otherwise."""
    syncer = _syncer(None)
    await syncer.enqueue_calc(_tup(_zip(tmp_path)))

    assert syncer.task_queue.qsize() == 1
    assert syncer.task_set == {PROC_A}
    assert syncer.journal_pending_keys() == []


def test_no_states_root_disables_journalling_with_one_warning(logger):
    """Both shapes of "no STATES root": an all-``None`` ``HelaoDirs`` (a config
    without ``root``) and an object carrying no ``helaodirs`` at all."""

    class _Dirs:
        states_root = None

    class _ServWithDirs:
        helaodirs = _Dirs()

    class _ServWithout:
        pass

    assert m.AnalysisSyncer._resolve_journal_dir(cast(Any, _ServWithDirs())) is None
    assert m.AnalysisSyncer._resolve_journal_dir(cast(Any, _ServWithout())) is None
    assert len(logger.warnings) == 2


def test_states_root_resolves_to_the_subdir_and_creates_it(tmp_path, logger):
    """The journal lands under the server's own ``STATES``, and is created."""

    class _Dirs:
        states_root = str(tmp_path / "STATES")

    class _Serv:
        helaodirs = _Dirs()

    os.makedirs(_Dirs.states_root)
    resolved = m.AnalysisSyncer._resolve_journal_dir(cast(Any, _Serv()))
    assert resolved == os.path.join(_Dirs.states_root, m.ANA_JOURNAL_SUBDIR)
    assert resolved is not None and os.path.isdir(resolved)


@pytest.mark.asyncio
async def test_an_unwritable_journal_dir_does_not_break_enqueue(tmp_path, logger):
    """Bookkeeping may not break the real work.

    A journal that cannot be written costs the *recovery* guarantee, not the
    analysis -- so the failure is logged and the item is queued anyway. Driven by
    a real unwritable location (a plain file where the journal directory should
    be, which is what an operator pointing ``root`` at the wrong path produces)
    rather than by patching the writer, so the swallow being tested is the one in
    :func:`write_journal_entry` itself.
    """
    blocker = tmp_path / "ana_pending"
    blocker.write_text("not a directory")
    syncer = _syncer(blocker)

    await syncer.enqueue_calc(_tup(_zip(tmp_path)))

    assert syncer.task_queue.qsize() == 1
    assert syncer.task_set == {PROC_A}
    assert logger.errors, "a failed journal write must be logged"


@pytest.mark.asyncio
async def test_a_raising_journal_writer_does_not_break_enqueue(
    tmp_path, logger, monkeypatch
):
    """The same guarantee one layer up: even an exception escaping the writer
    entirely is caught by :meth:`AnalysisSyncer.journal_write`."""
    syncer = _syncer(tmp_path / "ana_pending")

    def _explode(*a, **k):
        raise RuntimeError("journal subsystem is broken")

    monkeypatch.setattr(m, "write_journal_entry", _explode)
    await syncer.enqueue_calc(_tup(_zip(tmp_path)))

    assert syncer.task_queue.qsize() == 1
    assert logger.errors


@pytest.mark.asyncio
async def test_a_loader_without_a_target_is_queued_but_not_journalled(tmp_path, logger):
    """A loader kind with no ``target`` cannot be rebuilt, so it is not recorded
    -- but it must still run, with the un-recoverability logged."""
    syncer = _syncer(tmp_path / "ana_pending")

    class _NoTarget:
        pass

    await syncer.enqueue_calc(cast(Any, (PROC_A, _NoTarget(), {}, _AnaA, None)))

    assert syncer.task_queue.qsize() == 1
    assert m.list_journal_entries(syncer.journal_dir) == []
    assert any("no loader target" in w for w in logger.warnings)


# ---------------------------------------------------------------------------
# Startup sweep
# ---------------------------------------------------------------------------


def _classes(*pairs) -> dict:
    """``analysis_classes`` mapping, as ``make_analysis_app`` builds it."""
    return {f"analyze_{i}": cls for i, cls in enumerate(pairs)}


@pytest.mark.asyncio
async def test_startup_reenqueues_a_journalled_entry(tmp_path, logger, monkeypatch):
    """The whole point: an entry written by one process is re-enqueued by the
    next, with its loader rebuilt from the recorded target."""
    journal = tmp_path / "ana_pending"
    zip_path = _zip(tmp_path)
    writer = _syncer(journal)
    await writer.enqueue_calc(_tup(zip_path))

    monkeypatch.setattr(m, "LocalLoader", _FakeLoader)
    syncer = _syncer(journal)
    summary = await syncer.recover_journal(_classes(_AnaA))

    assert summary == {
        "pending": 1,
        "recovered": 1,
        "dropped": 0,
        "unconfigured": 0,
        "failed": 0,
    }
    assert syncer.task_queue.qsize() == 1
    process_uuid, loader, params, ana_cls, action_uuid = syncer.task_queue.get_nowait()
    assert process_uuid == PROC_A
    assert loader.target == str(zip_path)
    assert params == {"foo": 1}
    assert ana_cls is _AnaA
    assert action_uuid == ACTION_UUID
    # The entry is still on disk: only a worker finishing with it clears it, so
    # a crash during the recovered run is itself recoverable.
    assert len(m.list_journal_entries(str(journal))) == 1
    # A silent restart is the failure mode; recovery must be loud.
    assert any("re-enqueued" in a for a in logger.alerts)


@pytest.mark.asyncio
async def test_recovery_shares_one_loader_per_zip(tmp_path, logger, monkeypatch):
    """Two processes of one sequence rebuild one loader between them, matching
    ``batch_calc``, where indexing the archive happens once."""
    journal = tmp_path / "ana_pending"
    zip_path = _zip(tmp_path)
    writer = _syncer(journal)
    await writer.enqueue_calc(_tup(zip_path, process_uuid=PROC_A))
    await writer.enqueue_calc(_tup(zip_path, process_uuid=PROC_B))

    built = []

    class _CountingLoader(_FakeLoader):
        def __init__(self, data_path):
            super().__init__(data_path)
            built.append(data_path)

    monkeypatch.setattr(m, "LocalLoader", _CountingLoader)
    syncer = _syncer(journal)
    summary = await syncer.recover_journal(_classes(_AnaA))

    assert summary["recovered"] == 2
    assert len(built) == 1
    first = syncer.task_queue.get_nowait()
    second = syncer.task_queue.get_nowait()
    assert first[1] is second[1]


@pytest.mark.asyncio
async def test_an_entry_whose_data_is_gone_is_deleted_and_alerted(
    tmp_path, logger, monkeypatch
):
    """A vanished zip can never run again, so retrying it every restart forever
    would be noise; it is dropped once, loudly, naming the path."""
    journal = tmp_path / "ana_pending"
    zip_path = _zip(tmp_path)
    writer = _syncer(journal)
    await writer.enqueue_calc(_tup(zip_path))
    os.remove(zip_path)

    monkeypatch.setattr(m, "LocalLoader", _FakeLoader)
    syncer = _syncer(journal)
    summary = await syncer.recover_journal(_classes(_AnaA))

    assert summary["dropped"] == 1 and summary["recovered"] == 0
    assert m.list_journal_entries(str(journal)) == []
    assert syncer.task_queue.qsize() == 0
    assert any(str(zip_path) in a for a in logger.alerts)


@pytest.mark.asyncio
async def test_an_unconfigured_analysis_class_is_left_in_place(
    tmp_path, logger, monkeypatch
):
    """``params.analyses`` is per server, so an entry naming a class this host
    does not serve may belong to another host; deleting it here would destroy
    that host's work."""
    journal = tmp_path / "ana_pending"
    writer = _syncer(journal)
    await writer.enqueue_calc(_tup(_zip(tmp_path), ana_cls=_AnaB))

    monkeypatch.setattr(m, "LocalLoader", _FakeLoader)
    syncer = _syncer(journal)
    summary = await syncer.recover_journal(_classes(_AnaA))

    assert summary["unconfigured"] == 1 and summary["recovered"] == 0
    assert len(m.list_journal_entries(str(journal))) == 1
    assert syncer.task_queue.qsize() == 0


@pytest.mark.asyncio
async def test_a_corrupt_entry_does_not_abort_the_sweep(tmp_path, logger, monkeypatch):
    """One bad json file must not strand every other queued analysis.

    Three unusable shapes at once -- unparseable, a json array rather than an
    object, and an object missing ``target`` -- alongside one good entry, which
    must still recover.
    """
    journal = tmp_path / "ana_pending"
    zip_path = _zip(tmp_path)
    writer = _syncer(journal)
    await writer.enqueue_calc(_tup(zip_path))

    (journal / f"aaa{m.ANA_JOURNAL_SUFFIX}").write_text("{not json at all")
    (journal / f"bbb{m.ANA_JOURNAL_SUFFIX}").write_text("[1, 2, 3]")
    (journal / f"ccc{m.ANA_JOURNAL_SUFFIX}").write_text(
        json.dumps({"process_uuid": str(PROC_B), "analysis_class": "_AnaA"})
    )

    monkeypatch.setattr(m, "LocalLoader", _FakeLoader)
    syncer = _syncer(journal)
    summary = await syncer.recover_journal(_classes(_AnaA))

    assert summary["pending"] == 4
    assert summary["recovered"] == 1
    assert summary["failed"] == 3
    assert syncer.task_queue.qsize() == 1
    # Unusable entries are left for a human rather than deleted.
    assert len(m.list_journal_entries(str(journal))) == 4


@pytest.mark.asyncio
async def test_a_newer_schema_is_refused_rather_than_guessed_at(
    tmp_path, logger, monkeypatch
):
    """An entry from a future build is left alone: its fields may not mean what
    this build would read them as."""
    journal = tmp_path / "ana_pending"
    journal.mkdir()
    zip_path = _zip(tmp_path)
    (journal / f"future{m.ANA_JOURNAL_SUFFIX}").write_text(
        json.dumps(
            {
                "schema": m.ANA_JOURNAL_SCHEMA + 1,
                "target": str(zip_path),
                "process_uuid": str(PROC_A),
                "analysis_class": "_AnaA",
                "params": {},
            }
        )
    )

    monkeypatch.setattr(m, "LocalLoader", _FakeLoader)
    syncer = _syncer(journal)
    summary = await syncer.recover_journal(_classes(_AnaA))

    assert summary["failed"] == 1 and summary["recovered"] == 0
    assert len(m.list_journal_entries(str(journal))) == 1


@pytest.mark.asyncio
async def test_a_loader_that_cannot_be_built_leaves_its_entry(
    tmp_path, logger, monkeypatch
):
    """The zip is there but unreadable: an alert, and the entry stays, because
    unlike a vanished path this may well succeed later."""
    journal = tmp_path / "ana_pending"
    writer = _syncer(journal)
    await writer.enqueue_calc(_tup(_zip(tmp_path)))

    def _bad_loader(path):
        raise ValueError("not a zip file")

    monkeypatch.setattr(m, "LocalLoader", _bad_loader)
    syncer = _syncer(journal)
    summary = await syncer.recover_journal(_classes(_AnaA))

    assert summary["failed"] == 1 and summary["recovered"] == 0
    assert len(m.list_journal_entries(str(journal))) == 1
    assert logger.alerts


@pytest.mark.asyncio
async def test_an_empty_or_disabled_journal_recovers_nothing_quietly(tmp_path, logger):
    """Neither an empty journal nor a disabled one may alert -- an alert on
    every clean startup is how a real one gets ignored."""
    empty = _syncer(tmp_path / "ana_pending")
    assert (await empty.recover_journal(_classes(_AnaA)))["recovered"] == 0

    off = _syncer(None)
    assert (await off.recover_journal(_classes(_AnaA)))["pending"] == 0
    assert logger.alerts == []


@pytest.mark.asyncio
async def test_tmp_files_from_an_interrupted_write_are_not_swept(
    tmp_path, logger, monkeypatch
):
    """The atomic write's leftover is not an entry; parsing one would read a
    half-written payload."""
    journal = tmp_path / "ana_pending"
    journal.mkdir()
    (journal / f"half{m.ANA_JOURNAL_SUFFIX}.tmp").write_text('{"target": "/x"')

    syncer = _syncer(journal)
    summary = await syncer.recover_journal(_classes(_AnaA))

    assert summary == {
        "pending": 0,
        "recovered": 0,
        "dropped": 0,
        "unconfigured": 0,
        "failed": 0,
    }
    assert (journal / f"half{m.ANA_JOURNAL_SUFFIX}.tmp").exists()


# ---------------------------------------------------------------------------
# Round trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_restart_round_trip_runs_the_lost_analysis(tmp_path, logger, monkeypatch):
    """End to end, as a station experiences it: enqueue, lose the process before
    any worker runs, start again, and the analysis actually executes."""
    journal = tmp_path / "ana_pending"
    zip_path = _zip(tmp_path)

    first = _syncer(journal)
    await first.enqueue_calc(_tup(zip_path))
    # "Restart": the queue, the task set and the syncer itself simply cease to
    # exist. Only the journal survives.
    del first

    monkeypatch.setattr(m, "LocalLoader", _FakeLoader)
    second = _syncer(journal)
    ran = []

    async def _fake_sync_ana(calc_tup, retries=3):
        ran.append((calc_tup[0], calc_tup[1].target, calc_tup[3]))
        return True

    second.sync_ana = _fake_sync_ana  # type: ignore[method-assign]
    await second.recover_journal(_classes(_AnaA))
    worker = asyncio.create_task(second.syncer())
    await asyncio.wait_for(second.task_queue.join(), timeout=5)
    worker.cancel()

    assert ran == [(PROC_A, str(zip_path), _AnaA)]
    assert m.list_journal_entries(str(journal)) == []


@pytest.mark.asyncio
async def test_a_replay_interrupted_partway_recovers_only_what_is_outstanding(
    tmp_path, logger, monkeypatch
):
    """A replay that dies partway must lose nothing and repeat nothing.

    Five entries are recovered and re-enqueued; two complete, the third is in
    flight when the process goes down, and two are still queued. The sweep must
    therefore not clear an entry merely because it enqueued it -- and the two
    survivors of the third case matter separately:

    * the **in-flight** analysis is cancelled by a graceful shutdown, so
      ``syncer``'s ``finally`` runs for it. Its entry must survive anyway: it is
      the one analysis that certainly did not finish.
    * the two **completed** analyses must be gone, or the next start would run
      them a second time.
    """
    journal = tmp_path / "ana_pending"
    zip_path = _zip(tmp_path)
    # Uuids that sort in a known order, since both the sweep (sorted file names,
    # which start with the uuid) and the queue are FIFO -- so "the third one" is
    # deterministic.
    uuids = [UUID(f"0000000{n}-0000-0000-0000-000000000000") for n in range(1, 6)]

    writer = _syncer(journal)
    for uuid in uuids:
        await writer.enqueue_calc(_tup(zip_path, process_uuid=uuid))
    assert len(m.list_journal_entries(str(journal))) == 5
    del writer

    monkeypatch.setattr(m, "LocalLoader", _FakeLoader)
    replay = _syncer(journal)
    started = []
    third_in_flight = asyncio.Event()

    async def _fake_sync_ana(calc_tup, retries=3):
        started.append(calc_tup[0])
        if len(started) == 3:
            third_in_flight.set()
            # The process dies here: this await never returns.
            await asyncio.Event().wait()
        return True

    replay.sync_ana = _fake_sync_ana  # type: ignore[method-assign]
    summary = await replay.recover_journal(_classes(_AnaA))
    assert summary["recovered"] == 5
    # Enqueued is not completed: nothing may have been cleared yet.
    assert len(m.list_journal_entries(str(journal))) == 5

    worker = asyncio.create_task(replay.syncer())
    await asyncio.wait_for(third_in_flight.wait(), timeout=5)
    worker.cancel()
    with pytest.raises(asyncio.CancelledError):
        await worker

    assert started == uuids[:3]
    remaining = m.list_journal_entries(str(journal))
    expected = [
        m.analysis_journal_key(str(zip_path), uuid, "_AnaA") for uuid in uuids[2:]
    ]
    assert sorted(remaining) == sorted(expected), (remaining, expected)

    # Next start: exactly the three outstanding analyses come back, and the two
    # that completed do not.
    survivor = _syncer(journal)
    second_summary = await survivor.recover_journal(_classes(_AnaA))
    assert second_summary["recovered"] == 3
    assert [item[0] for item in survivor.task_queue._queue] == uuids[2:]  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_shutdown_reports_what_it_is_leaving_behind(tmp_path, logger):
    """A graceful stop still discards the queue -- but no longer silently."""
    journal = tmp_path / "ana_pending"
    syncer = _syncer(journal)
    await syncer.enqueue_calc(_tup(_zip(tmp_path)))

    syncer.shutdown()
    assert any("re-enqueued at the next startup" in w for w in logger.warnings)


@pytest.mark.asyncio
async def test_shutdown_warns_when_queued_work_is_not_journalled(tmp_path, logger):
    """The journalling-disabled case is the one where work really is lost, and
    it must say so rather than reusing the reassuring message."""
    syncer = _syncer(None)
    await syncer.enqueue_calc(_tup(_zip(tmp_path)))

    syncer.shutdown()
    assert any("will be lost" in w for w in logger.warnings)


# ---------------------------------------------------------------------------
# Status endpoint / app wiring
# ---------------------------------------------------------------------------


def _app(tmp_path, monkeypatch):
    """A constructed analysis app, with no startup event ever fired.

    ``BaseAPI`` registers its routes at construction while the driver, its S3
    loader and ``Base`` are only built from the startup event -- so this needs
    neither network nor credentials. ``root``/``host``/``port`` are present only
    because ``HelaoFastAPI.__init__`` reads them unconditionally (the same reason
    priv's checklist test supplies them), and ``analyses`` is empty so no
    deployment's analysis modules are imported.
    """
    from helao.helpers import config_loader

    monkeypatch.setattr(
        config_loader,
        "CONFIG",
        {
            "deployment": "hte",
            "root": str(tmp_path),
            "servers": {
                "ANA": {
                    "host": "127.0.0.1",
                    "port": 8014,
                    "params": {"analyses": []},
                }
            },
        },
    )
    return m.make_analysis_app("ANA")


def _route_handler(app, path: str):
    """The function registered for ``path``, called directly.

    Direct rather than through a ``TestClient``, whose request would fire the
    startup events and with them a real ``Base``, S3 loader and NTP sync.
    """
    for route in app.routes:
        if getattr(route, "path", "") == path:
            return route.endpoint  # type: ignore[attr-defined]
    raise AssertionError(f"{path} is no longer registered")


def test_list_queued_tasks_reports_both_the_queue_and_the_journal(
    tmp_path, monkeypatch
):
    """The response body carries the in-memory queue under ``queued`` -- what the
    whole body used to be -- and the journal beside it, so a journal write
    failure or a disabled journal is visible from outside the process."""
    journal = tmp_path / "ana_pending"
    journal.mkdir()
    key = m.analysis_journal_key("/data/seq.zip", PROC_A, "AnaA")
    (journal / key).write_text("{}")

    app = _app(tmp_path, monkeypatch)
    syncer = _syncer(journal)
    syncer.task_set = {PROC_B}
    syncer.running_tasks = {str(PROC_A): object()}
    app.driver = syncer

    body = _route_handler(app, "/list_queued_tasks")()
    assert body["queued"] == [str(PROC_B)]
    assert body["running"] == [str(PROC_A)]
    assert body["journal_pending"] == 1
    assert body["journal_keys"] == [key]
    assert body["journal_dir"] == str(journal)


def test_no_route_was_added_renamed_or_removed(tmp_path, monkeypatch):
    """priv's frozen endpoint checklist lives in another git repository, and a
    new private route here would break that gate and force a cross-repo change.
    The journal is therefore exposed through the existing body, not a new path."""
    app = _app(tmp_path, monkeypatch)
    # Everything this module contributes to an app with an empty ``analyses``
    # list: exactly the two private routes priv's checklist froze. Compared as a
    # set difference against ``BaseAPI``'s own surface so the assertion stays
    # exact -- ``/list_executors`` and friends come from BaseAPI, not from here.
    from helao.core.servers.base_api import BaseAPI

    baseline = {
        getattr(route, "path", "")
        for route in BaseAPI(
            server_key="ANA", server_title="ANA", description="", version=1.0
        ).routes
    }
    contributed = {getattr(route, "path", "") for route in app.routes} - baseline
    assert contributed == {"/list_queued_tasks", "/list_running_tasks"}


def _startup_handler(app):
    """The registered journal-sweep startup handler."""
    handlers = [
        h
        for h in app.router.on_startup
        if getattr(h, "__name__", "") == "_recover_journalled_analyses"
    ]
    assert len(handlers) == 1, "the journal sweep is not wired into startup"
    return handlers[0]


class _StubDriver:
    """Driver stand-in exposing only what the startup handler touches."""

    def __init__(self, cfg):
        self.config_dict = cfg
        self.journal_dir = "/nowhere"
        self.swept = False

    def journal_pending_keys(self):
        return []

    async def recover_journal(self, analysis_classes):
        self.swept = True
        return {}


def test_recovery_sweep_is_armed_by_default_and_can_be_suppressed(
    tmp_path, monkeypatch
):
    """Armed by default -- an unswept journal is the silent loss it exists to end
    -- and suppressible per server with ``analysis_recovery_on_startup: false``,
    matching the batch server's knob."""
    app = _app(tmp_path, monkeypatch)
    handler = _startup_handler(app)

    async def _run(cfg):
        app.driver = _StubDriver(cfg)
        handler()
        task = getattr(app.driver, "recovery_task", None)
        if task is not None:
            await task
        return app.driver.swept

    assert asyncio.run(_run({})) is True
    assert asyncio.run(_run({"analysis_recovery_on_startup": False})) is False


def test_the_sweep_runs_as_a_task_rather_than_blocking_startup(tmp_path, monkeypatch):
    """Rebuilding a loader indexes a sequence zip; holding up startup for that
    would delay the port bind and every route with it."""
    app = _app(tmp_path, monkeypatch)
    handler = _startup_handler(app)

    async def _run():
        app.driver = _StubDriver({})
        handler()
        # The handler has returned and the sweep has NOT run yet -- it is a task.
        assert app.driver.swept is False
        assert isinstance(app.driver.recovery_task, asyncio.Task)
        await app.driver.recovery_task
        assert app.driver.swept is True

    asyncio.run(_run())


def test_a_missing_driver_at_startup_does_not_raise(tmp_path, monkeypatch):
    """The sweep runs from a startup handler, so raising there would take the
    server down before it binds its port. It warns instead."""
    app = _app(tmp_path, monkeypatch)
    app.driver = None
    _startup_handler(app)()  # must not raise
