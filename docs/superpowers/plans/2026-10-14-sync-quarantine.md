# Sync Quarantine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the syncer retrying a record that keeps failing, and make it visible: strikes in the `.prg`, quarantine at N strikes once the first failure is older than a window, one alert, re-queue via `/finish_yml`.

**Architecture:** State lives in a `quarantine:` block of the record's `.prg`. `run_state.py` gets a flat-text reader (`_prg_is_quarantined`) beside `_prg_is_complete`, used by both the enqueue gate and the journal rebuild. `Progress` gets the strike bookkeeping; `SyncDriver` records strikes on both failure channels, gates `enqueue_yml`, and lists quarantined records from the SYNC journal. The SYNC server's `/finish_yml` releases quarantine and `/tasks` lists it. One refinement of spec §4.5: the route calls a new `SyncDriver.release_quarantine(path)` instead of touching `Progress` itself, so the server never has to know which twin's `Progress` its driver uses.

**Tech Stack:** Python 3.14, pytest + pytest-asyncio, the `helao` conda env.

**Spec:** `docs/superpowers/specs/2026-10-14-sync-quarantine-design.md`

## Global Constraints

- Defaults: `quarantine_strikes = 5`, `quarantine_hours = 24`; `quarantine_strikes: 0` disables quarantine but strikes are still recorded.
- Quarantine iff `strikes >= N` **and** `now - first_failed >= window` (spec Q3).
- `last_error` is truncated to 500 characters.
- Timestamps: `datetime.isoformat(timespec="seconds")` strings.
- No new routes and no route-signature changes on `helao/deploy/hte/servers/action/sync_server.py` (frozen checklist `helao/hexagon/tests/checklists/hte/sync_server.json`).
- **Twin rule.** `helao/core/drivers/data/sync_driver.py` (legacy) and `helao/hexagon/adapters/native/sync_driver.py` (native) share a byte-identical region from the `LOGGER = logging.make_logger` line to the end of `class SyncDriver`. Every edit inside that region is made **identically in both files**; `helao/hexagon/tests/test_native_sync_pins.py` fails otherwise. The region must contain **no import statement**; imports go in each file's import block above it.
- **Never run `black` on either `sync_driver.py`** — both are excluded in `pyproject.toml` because reformatting breaks byte identity. Run `black` on every other changed file before each commit.
- Run tests with `conda run -n helao python -m pytest ...` from the repo root `/mnt/STORAGE/repos/helao/helao-async`.
- Known pre-existing failure, not ours: `test_hte_route_checklist.py::test_module_matches_its_frozen_checklist[sample_server.py]` fails on `unstable`. Ignore it; every other case must pass.
- **Subagents must not run `git add`, `git commit`, `git push` or `git stash`.** Commit steps below are executed by the main thread after the task's review passes. Use `git -C /mnt/STORAGE/repos/helao/helao-async` for any read-only git call.
- An implementer that meets a decision this plan does not settle stops and reports it rather than choosing.

## Review Focus

1. A hand-edited or malformed `quarantine:` block (strikes not an int, `first_failed` unparseable) must not crash the worker; `add_strike` treats it as a fresh block. Test: Task 2, `test_add_strike_recovers_from_a_malformed_block`.
2. A traceback-sized error string must not bloat the `.prg`. Test: Task 2, `test_last_error_is_truncated`.
3. A record whose yml disappears between enqueue and failure: `_strike` must swallow its own failure and the worker must keep serving. Test: Task 3, `test_strike_on_a_vanished_record_does_not_kill_the_worker`.
4. A server with no journal (`states_root` unset): strikes and alerts still work; `quarantined()` returns `[]`. Test: Task 3, `test_no_journal_still_quarantines_and_lists_nothing`.
5. `/finish_yml` on a record that is **not** quarantined behaves exactly as before. Test: Task 4, `test_finish_yml_on_a_healthy_record_just_enqueues`.

---

### Task 1: `run_state` — the `quarantined` state and its flat-text reader

**Files:**
- Modify: `helao/helpers/run_state.py` (constants near line 50, `__all__`, new function after `_prg_is_complete` ~line 275, `rebuild_from_tree` ~line 420)
- Test: `helao/core/tests/test_sync_quarantine.py` (create)

**Interfaces:**
- Produces: `QUARANTINED = "quarantined"` (exported); `_prg_is_quarantined(prg_path: Path) -> bool`; `rebuild_from_tree` emits `state: "quarantined"` for a record whose `.prg` is quarantined.

- [ ] **Step 1: Write the failing tests**

Create `helao/core/tests/test_sync_quarantine.py`:

```python
"""Sync quarantine (spec docs/superpowers/specs/2026-10-14-sync-quarantine-design.md)."""

import asyncio
import textwrap
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

import helao.core.drivers.data.sync_driver as legacy_mod
import helao.hexagon.adapters.native.sync_driver as native_mod
from helao.core.models.helaodirs import HelaoDirs
from helao.core.models.run_dir import RunDir
from helao.helpers.run_state import (
    QUARANTINED,
    UNSYNCED,
    _prg_is_quarantined,
    rebuild_from_tree,
)
from helao.hexagon.tests.sync_fixtures import (
    drain,
    make_action,
    make_exp_tree,
    make_sync_driver,
    mk_uuid,
    teardown_driver,
)

MODS = [legacy_mod, native_mod]
T0 = datetime(2026, 10, 14, 9, 0, 0)


def _write_prg(prg: Path, quarantined_at) -> None:
    qa = "null" if quarantined_at is None else f"'{quarantined_at}'"
    prg.write_text(
        textwrap.dedent(
            f"""\
            yml: x
            api: false
            s3: false
            quarantine:
              strikes: 5
              first_failed: '2026-10-13T09:00:00'
              last_failed: '2026-10-14T09:00:00'
              last_error: 'RuntimeError: boom'
              quarantined_at: {qa}
            """
        ),
        encoding="utf-8",
    )


def test_prg_is_quarantined_reads_the_flag(tmp_path):
    prg = tmp_path / "a-act.prg"
    _write_prg(prg, "2026-10-14T09:00:00")
    assert _prg_is_quarantined(prg) is True


def test_a_block_without_quarantined_at_is_not_quarantined(tmp_path):
    prg = tmp_path / "a-act.prg"
    _write_prg(prg, None)
    assert _prg_is_quarantined(prg) is False


def test_a_missing_prg_is_not_quarantined(tmp_path):
    assert _prg_is_quarantined(tmp_path / "nope-act.prg") is False


def test_rebuild_reports_a_quarantined_record_as_quarantined(tmp_path):
    exp_yml = make_exp_tree(tmp_path, "RUNS", mk_uuid(1))
    act_yml = make_action(exp_yml, 0)
    _write_prg(act_yml.with_suffix(".prg"), "2026-10-14T09:00:00")
    journal = rebuild_from_tree(tmp_path / "RUNS", tmp_path / "STATES", "SYNC")
    states = {r["kind"]: r["state"] for r in journal.working_set().values()}
    assert states == {"experiment": UNSYNCED, "action": QUARANTINED}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `conda run -n helao python -m pytest -q helao/core/tests/test_sync_quarantine.py`
Expected: collection ERROR, `ImportError: cannot import name 'QUARANTINED'`.

- [ ] **Step 3: Implement**

In `helao/helpers/run_state.py`:

Add `"QUARANTINED",` to `__all__` between `"DONE",` and `"UNSYNCED",`.

After `DONE = "done"` add:

```python
#: A SYNC-journal state for a record the syncer has stopped retrying (sync
#: quarantine spec). Not ``done``, so it stays in the working set and survives
#: compaction; ``/tasks`` lists it from there.
QUARANTINED = "quarantined"
```

After `_prg_is_complete` add:

```python
def _prg_is_quarantined(prg_path: Path) -> bool:
    """Whether a ``.prg`` sidecar records its record as quarantined.

    True when the sidecar holds a ``quarantined_at`` line with a value other
    than ``null``. Read as flat text, like :func:`_prg_is_complete`, for the
    same reasons: no helao imports here, and a malformed or unreadable sidecar
    degrades to "not quarantined" -- the safe direction, since a wrongly
    unquarantined record is merely retried.
    """
    try:
        lines = prg_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    for line in lines:
        key, _, value = line.strip().partition(":")
        if key == "quarantined_at":
            return value.strip() not in ("", "null", "~")
    return False
```

In `rebuild_from_tree`, replace `"state": UNSYNCED,` in the `entries.append(...)` dict with:

```python
                    "state": (
                        QUARANTINED
                        if _prg_is_quarantined(yml.with_suffix(".prg"))
                        else UNSYNCED
                    ),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `conda run -n helao python -m pytest -q helao/core/tests/test_sync_quarantine.py helao/core/tests/test_runs_layout.py helao/core/tests/test_run_state_wiring.py`
Expected: all pass.

- [ ] **Step 5: Mutation check**

Temporarily change `_prg_is_quarantined`'s return to `return False` for the matching key; confirm `test_prg_is_quarantined_reads_the_flag` and `test_rebuild_reports_...` fail; restore.

- [ ] **Step 6: Commit (main thread)**

```bash
black helao/helpers/run_state.py helao/core/tests/test_sync_quarantine.py
git add helao/helpers/run_state.py helao/core/tests/test_sync_quarantine.py
git commit -m "feat(sync): quarantined journal state and its .prg reader"
```

---

### Task 2: Strike bookkeeping — `quarantine_due` and `Progress`

**Files:**
- Modify (identically): `helao/core/drivers/data/sync_driver.py` and `helao/hexagon/adapters/native/sync_driver.py`
  - import block: `from datetime import datetime` → `from datetime import datetime, timedelta`
  - new module-level function immediately above `class Progress:`
  - new `Progress` members after `remove_prg`
- Test: `helao/core/tests/test_sync_quarantine.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces:
  - `quarantine_due(block: dict, n: int, hours: float, now: datetime) -> bool`
  - `QUARANTINE_ERROR_CHARS = 500` (module constant, inside the region)
  - `Progress.quarantine -> Optional[dict]` (property)
  - `Progress.is_quarantined -> bool` (property)
  - `Progress.add_strike(error: str, n: int, hours: float, now: datetime) -> bool` — True only on the strike that enters quarantine
  - `Progress.clear_quarantine() -> None`

- [ ] **Step 1: Write the failing tests**

Append to `helao/core/tests/test_sync_quarantine.py`:

```python
def _block(strikes, first_failed):
    return {"strikes": strikes, "first_failed": first_failed.isoformat(timespec="seconds")}


@pytest.mark.parametrize("mod", MODS)
def test_quarantine_due_needs_both_strikes_and_age(mod):
    due = mod.quarantine_due
    assert due(_block(4, T0), 5, 24, T0 + timedelta(hours=48)) is False
    assert due(_block(5, T0), 5, 24, T0 + timedelta(hours=23)) is False
    assert due(_block(5, T0), 5, 24, T0 + timedelta(hours=24)) is True
    assert due(_block(9, T0), 0, 24, T0 + timedelta(hours=48)) is False


@pytest.mark.parametrize("mod", MODS)
def test_outage_inside_the_window_never_quarantines(tmp_path, mod):
    act_yml = make_action(make_exp_tree(tmp_path, "RUNS", mk_uuid(1)), 0)
    prog = mod.Progress(act_yml)
    for i in range(10):
        assert prog.add_strike("S3 down", 5, 24, T0 + timedelta(hours=i)) is False
    assert prog.is_quarantined is False
    assert mod.Progress(act_yml).quarantine["strikes"] == 10


@pytest.mark.parametrize("mod", MODS)
def test_the_crossing_strike_returns_true_exactly_once(tmp_path, mod):
    act_yml = make_action(make_exp_tree(tmp_path, "RUNS", mk_uuid(1)), 0)
    prog = mod.Progress(act_yml)
    results = [
        prog.add_strike("boom", 5, 24, T0 + timedelta(hours=h))
        for h in (0, 1, 2, 3, 25, 26)
    ]
    assert results == [False, False, False, False, True, False]
    reread = mod.Progress(act_yml)
    assert reread.is_quarantined is True
    assert reread.quarantine["first_failed"] == T0.isoformat(timespec="seconds")
    assert reread.quarantine["last_error"] == "boom"


@pytest.mark.parametrize("mod", MODS)
def test_clear_quarantine_removes_the_block(tmp_path, mod):
    act_yml = make_action(make_exp_tree(tmp_path, "RUNS", mk_uuid(1)), 0)
    prog = mod.Progress(act_yml)
    prog.add_strike("boom", 1, 0, T0)
    assert prog.is_quarantined is True
    prog.clear_quarantine()
    assert mod.Progress(act_yml).quarantine is None


@pytest.mark.parametrize("mod", MODS)
def test_last_error_is_truncated(tmp_path, mod):
    act_yml = make_action(make_exp_tree(tmp_path, "RUNS", mk_uuid(1)), 0)
    prog = mod.Progress(act_yml)
    prog.add_strike("x" * 5000, 5, 24, T0)
    assert len(mod.Progress(act_yml).quarantine["last_error"]) == mod.QUARANTINE_ERROR_CHARS


@pytest.mark.parametrize("mod", MODS)
def test_add_strike_recovers_from_a_malformed_block(tmp_path, mod):
    act_yml = make_action(make_exp_tree(tmp_path, "RUNS", mk_uuid(1)), 0)
    prog = mod.Progress(act_yml)
    prog.dict["quarantine"] = {"strikes": "lots", "first_failed": "not a date"}
    prog.write_dict()
    assert prog.add_strike("boom", 5, 24, T0) is False
    block = mod.Progress(act_yml).quarantine
    assert block["strikes"] == 1
    assert block["first_failed"] == T0.isoformat(timespec="seconds")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `conda run -n helao python -m pytest -q helao/core/tests/test_sync_quarantine.py`
Expected: the new tests FAIL with `AttributeError: module ... has no attribute 'quarantine_due'` (Task 1 tests still pass).

- [ ] **Step 3: Implement — in BOTH sync_driver files, identically**

Import block (both files): change `from datetime import datetime` to `from datetime import datetime, timedelta`.

Immediately above `class Progress:` (both files), add:

```python
#: ``last_error`` is cut to this many characters so a traceback-sized message
#: cannot bloat the ``.prg`` (sync quarantine spec §3).
QUARANTINE_ERROR_CHARS = 500


def quarantine_due(block: dict, n: int, hours: float, now: datetime) -> bool:
    """Whether a ``quarantine`` block has earned quarantine (spec Q3).

    Both thresholds must hold: at least ``n`` strikes, and the first failure
    at least ``hours`` old. The age floor is what keeps an S3 or API outage
    from quarantining every record that happened to sync during it. ``n <= 0``
    disables quarantine. ``now`` is a parameter so the rule is testable
    without patching the clock.
    """
    if n <= 0 or block.get("strikes", 0) < n:
        return False
    first = datetime.fromisoformat(block["first_failed"])
    return now - first >= timedelta(hours=hours)
```

After `Progress.remove_prg` (both files), add:

```python
    @property
    def quarantine(self) -> Optional[dict]:
        """The ``quarantine`` block, or ``None`` if no failure is recorded."""
        return self.dict.get("quarantine")

    @property
    def is_quarantined(self) -> bool:
        """Whether this record is quarantined (``quarantined_at`` is set)."""
        return bool((self.quarantine or {}).get("quarantined_at"))

    def add_strike(self, error: str, n: int, hours: float, now: datetime) -> bool:
        """Record one failed sync pass; return True only on entering quarantine.

        A block that does not parse (a hand edit, a foreign writer) is replaced
        by a fresh one rather than raised on: a strike is bookkeeping, and
        failing here would turn a failed pass into a crashed worker.
        """
        stamp = now.isoformat(timespec="seconds")
        block = self.quarantine
        try:
            strikes = int(block["strikes"]) + 1
            datetime.fromisoformat(block["first_failed"])
            first = block["first_failed"]
            already = bool(block.get("quarantined_at"))
        except (TypeError, KeyError, ValueError):
            strikes, first, already = 1, stamp, False
        block = {
            "strikes": strikes,
            "first_failed": first,
            "last_failed": stamp,
            "last_error": str(error)[:QUARANTINE_ERROR_CHARS],
            "quarantined_at": block.get("quarantined_at") if already else None,
        }
        entered = not already and quarantine_due(block, n, hours, now)
        if entered:
            block["quarantined_at"] = stamp
        self.dict["quarantine"] = block
        self.write_dict()
        return entered

    def clear_quarantine(self) -> None:
        """Drop the ``quarantine`` block, so the next failure starts afresh."""
        if self.dict.pop("quarantine", None) is not None:
            self.write_dict()
```

Note `block.get(...)` in the `already` branch: `block` is the old dict there (the `try` succeeded). Write it exactly as shown.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `conda run -n helao python -m pytest -q helao/core/tests/test_sync_quarantine.py helao/hexagon/tests/test_native_sync_pins.py`
Expected: all pass. A pins failure means the two files differ inside the region — diff them and make them identical.

- [ ] **Step 5: Mutation check**

In both files, temporarily drop the age condition from `quarantine_due` (`return True` after the strikes check); confirm `test_outage_inside_the_window_never_quarantines` and `test_quarantine_due_needs_both_strikes_and_age` fail; restore. Temporarily remove `not already and`; confirm `test_the_crossing_strike_returns_true_exactly_once` fails; restore.

- [ ] **Step 6: Commit (main thread)** — no black on the sync drivers.

```bash
black helao/core/tests/test_sync_quarantine.py
git add helao/core/drivers/data/sync_driver.py helao/hexagon/adapters/native/sync_driver.py helao/core/tests/test_sync_quarantine.py
git commit -m "feat(sync): strike bookkeeping in the .prg quarantine block"
```

---

### Task 3: `SyncDriver` — strikes on both channels, the enqueue gate, the listing

**Files:**
- Modify (identically): both `sync_driver.py` files
  - import block: add `QUARANTINED,` and `_prg_is_quarantined,` to the `from helao.helpers.run_state import (...)` list (keep it sorted: `DONE, QUARANTINED, UNSYNCED, RunStateJournal, _prg_is_complete, _prg_is_quarantined, identify_record, ...`)
  - `SyncDriver.__init__` (after `self.max_tasks = ...`, legacy ~line 1180)
  - new methods `_strike`, `release_quarantine`, `quarantined` (place after `has_pending_work`)
  - `syncer` worker `except` (legacy ~line 1488)
  - `enqueue_yml` (legacy ~line 1541, the `-prc.yml` branch)
  - `sync_yml` `if not synced:` branch (legacy ~line 1780)
- Test: `helao/core/tests/test_sync_quarantine.py`

**Interfaces:**
- Consumes: Task 1 `QUARANTINED`, `_prg_is_quarantined`; Task 2 `Progress.add_strike`, `Progress.clear_quarantine`, `Progress.is_quarantined`.
- Produces:
  - `SyncDriver.quarantine_strikes: int`, `SyncDriver.quarantine_hours: float`
  - `SyncDriver._strike(yml_path: Path, error: str) -> None`
  - `SyncDriver.release_quarantine(yml_path: Union[Path, str]) -> bool` — True if a quarantine was cleared
  - `SyncDriver.quarantined() -> list[dict]` — each dict: `uuid`, `kind`, `path` (root-relative dir), `yml` (str or None), plus the `.prg` block's keys

- [ ] **Step 1: Write the failing tests**

Append to `helao/core/tests/test_sync_quarantine.py`:

```python
FAILING_HOOK = """
from helao.core.hooks import FinishHook
class Hook(FinishHook):
    blocking = True
    phase = "postfinish"
    async def run(self, ctx):
        raise RuntimeError("push failed")
"""

QUICK = {"quarantine_strikes": 1, "quarantine_hours": 0}


def _driver_with_journal(tmp_path, cls, cfg_extra=None, postfinish_hooks=None):
    hd = HelaoDirs(
        root=tmp_path,
        save_root=tmp_path / RunDir.ACTIVE.value,
        process_root=tmp_path / "PROCESSES",
        states_root=tmp_path / "STATES",
    )
    cfg = {"aws_bucket": "test-bucket", "max_tasks": 1, **(cfg_extra or {})}
    if postfinish_hooks is None:
        return cls(cfg, hd)
    return cls(cfg, hd, postfinish_hooks=postfinish_hooks)


def _count_alerts(monkeypatch, mod):
    alerts = []
    monkeypatch.setattr(mod.LOGGER, "alert", lambda msg, *a, **k: alerts.append(msg))
    return alerts


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_defaults_are_five_strikes_and_24_hours(tmp_path, mod):
    drv = make_sync_driver(tmp_path, mod.SyncDriver)
    try:
        assert (drv.quarantine_strikes, drv.quarantine_hours) == (5, 24)
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_an_exception_out_of_sync_yml_is_a_strike(tmp_path, mod, monkeypatch):
    alerts = _count_alerts(monkeypatch, mod)
    drv = _driver_with_journal(tmp_path, mod.SyncDriver, QUICK)
    try:
        act_yml = make_action(make_exp_tree(tmp_path, "RUNS", mk_uuid(1)), 0)

        async def explode(yml_path, rank=5, **kw):
            raise ValueError("bad yml")

        drv.sync_yml = explode
        await drv.enqueue_yml(act_yml, 0)
        await drain(drv, timeout=15)
        prog = mod.Progress(act_yml)
        assert prog.is_quarantined
        assert prog.quarantine["last_error"] == "ValueError: bad yml"
        assert len(alerts) == 1
        listed = drv.quarantined()
        assert [e["yml"] for e in listed] == [str(act_yml)]
        assert listed[0]["strikes"] == 1
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_a_failed_blocking_hook_is_a_strike(tmp_path, mod):
    hook = tmp_path / "push_api.py"
    hook.write_text(textwrap.dedent(FAILING_HOOK), encoding="utf-8")
    drv = _driver_with_journal(
        tmp_path,
        mod.SyncDriver,
        {"quarantine_strikes": 5, "quarantine_hours": 24},
        postfinish_hooks={"action": {str(hook): ["*"]}},
    )
    try:
        act_yml = make_action(make_exp_tree(tmp_path, "RUNS", mk_uuid(1)), 0)

        async def no_requeue(upath, rank=0, rank_limit=-5):
            return None

        drv.enqueue_yml = no_requeue
        assert await asyncio.wait_for(drv.sync_yml(yml_path=act_yml, rank=0), 15) is False
        block = mod.Progress(act_yml).quarantine
        assert block["strikes"] == 1
        assert "push failed" in block["last_error"]
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_a_quarantined_record_is_never_enqueued(tmp_path, mod):
    drv = make_sync_driver(tmp_path, mod.SyncDriver)
    try:
        exp_yml = make_exp_tree(tmp_path, RunDir.FINISHED.value, mk_uuid(1))
        sick = make_action(exp_yml, 0)
        healthy = make_action(exp_yml, 1)
        mod.Progress(sick).add_strike("boom", 1, 0, T0)
        mod.Progress(healthy).add_strike("blip", 5, 24, T0)  # strikes below N
        synced = []

        async def record(yml_path, rank=5, **kw):
            synced.append(str(yml_path))

        drv.sync_yml = record
        await drv.enqueue_yml(sick, 0)
        await drv.finish_pending(actions_first=True)
        await drain(drv, timeout=15)
        assert str(sick) not in synced
        assert str(healthy) in synced  # the sweep did find this tree
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_release_quarantine_clears_and_reports(tmp_path, mod):
    drv = make_sync_driver(tmp_path, mod.SyncDriver)
    try:
        act_yml = make_action(make_exp_tree(tmp_path, "RUNS", mk_uuid(1)), 0)
        assert drv.release_quarantine(act_yml) is False
        mod.Progress(act_yml).add_strike("boom", 1, 0, T0)
        assert drv.release_quarantine(str(act_yml)) is True
        assert mod.Progress(act_yml).quarantine is None
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_zero_strikes_disables_quarantine_but_records(tmp_path, mod, monkeypatch):
    alerts = _count_alerts(monkeypatch, mod)
    drv = make_sync_driver(
        tmp_path, mod.SyncDriver, {"quarantine_strikes": 0, "quarantine_hours": 0}
    )
    try:
        act_yml = make_action(make_exp_tree(tmp_path, "RUNS", mk_uuid(1)), 0)
        for _ in range(3):
            drv._strike(act_yml, "boom")
        prog = mod.Progress(act_yml)
        assert prog.quarantine["strikes"] == 3 and not prog.is_quarantined
        assert alerts == []
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_strike_on_a_vanished_record_does_not_kill_the_worker(tmp_path, mod):
    drv = make_sync_driver(tmp_path, mod.SyncDriver, QUICK)
    try:
        ghost = tmp_path / "RUNS" / "gone" / "260610.000001000000-act.yml"
        drv._strike(ghost, "boom")  # Progress raises loading the missing yml
        assert not ghost.with_suffix(".prg").exists()
        act_yml = make_action(make_exp_tree(tmp_path, "RUNS", mk_uuid(1)), 0)
        seen = []

        async def record(yml_path, rank=5, **kw):
            seen.append(str(yml_path))

        drv.sync_yml = record
        await drv.enqueue_yml(act_yml, 0)
        await drain(drv, timeout=15)
        assert seen == [str(act_yml)]
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_no_journal_still_quarantines_and_lists_nothing(tmp_path, mod, monkeypatch):
    alerts = _count_alerts(monkeypatch, mod)
    drv = make_sync_driver(tmp_path, mod.SyncDriver, QUICK)  # no states_root
    try:
        assert drv.run_journal is None
        act_yml = make_action(make_exp_tree(tmp_path, "RUNS", mk_uuid(1)), 0)
        drv._strike(act_yml, "boom")
        assert mod.Progress(act_yml).is_quarantined
        assert len(alerts) == 1
        assert drv.quarantined() == []
    finally:
        await teardown_driver(drv)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `conda run -n helao python -m pytest -q helao/core/tests/test_sync_quarantine.py`
Expected: the Task 3 tests FAIL (`AttributeError: ... 'quarantine_strikes'`, `'_strike'`, `'release_quarantine'`, `'quarantined'`; the enqueue test fails on `str(sick) not in synced`).

- [ ] **Step 3: Implement — in BOTH sync_driver files, identically**

Import block (both files): add `QUARANTINED,` and `_prg_is_quarantined,` to the `helao.helpers.run_state` import list as described under **Files**.

`SyncDriver.__init__`, right after `self.max_tasks = self.config_dict.get("max_tasks", 1)`:

```python
        #: Sync quarantine thresholds (spec Q3/Q4): a record is parked after
        #: this many failed passes once its first failure is this old.
        #: ``quarantine_strikes: 0`` disables parking; strikes still record.
        self.quarantine_strikes = int(self.config_dict.get("quarantine_strikes", 5))
        self.quarantine_hours = float(self.config_dict.get("quarantine_hours", 24))
```

After `has_pending_work`, add:

```python
    def _strike(self, yml_path: Path, error: str) -> None:
        """Record one failed pass for ``yml_path``; park it if it has earned it.

        Raises one ``LOGGER.alert`` on the strike that enters quarantine and
        journals the record as ``quarantined``. Never raises: a failure to
        record a strike is logged and dropped, so bookkeeping can never turn a
        failed pass into a dead worker.
        """
        try:
            prog = Progress(yml_path)
            entered = prog.add_strike(
                error, self.quarantine_strikes, self.quarantine_hours, datetime.now()
            )
            if not entered:
                return
            block = prog.quarantine or {}
            LOGGER.alert(
                f"SYNC quarantined {yml_path} after {block.get('strikes')} failed "
                f"passes ({block.get('first_failed')} .. {block.get('last_failed')}); "
                f"last error: {block.get('last_error')}. It will not be retried "
                "automatically. Fix the cause, then POST /finish_yml with this path."
            )
            self._journal(yml_path, QUARANTINED)
        except Exception:
            LOGGER.error(f"Could not record a sync strike for {yml_path}", exc_info=True)

    def release_quarantine(self, yml_path: Union[Path, str]) -> bool:
        """Clear ``yml_path``'s quarantine; True if there was one to clear."""
        yml_path = Path(yml_path)
        if not _prg_is_quarantined(yml_path.with_suffix(".prg")):
            return False
        Progress(yml_path).clear_quarantine()
        LOGGER.info(f"Operator released {yml_path} from sync quarantine.")
        return True

    def quarantined(self) -> list:
        """Quarantined records from the SYNC journal, with their ``.prg`` block.

        Empty when this server keeps no journal. The yml is found by kind
        suffix inside the journalled record directory; ``yml`` is ``None`` if
        it is gone.
        """
        if self.run_journal is None:
            return []
        suffix = {"action": "-act.yml", "experiment": "-exp.yml", "sequence": "-seq.yml"}
        out = []
        for rec in self.run_journal.working_set().values():
            if rec.get("state") != QUARANTINED:
                continue
            rec_dir = Path(str(self.helaodirs.root)) / rec["path"]
            ymls = sorted(rec_dir.glob(f"*{suffix.get(rec['kind'], '.yml')}"))
            entry = {
                "uuid": rec["uuid"],
                "kind": rec["kind"],
                "path": rec["path"],
                "yml": str(ymls[0]) if ymls else None,
            }
            if ymls:
                try:
                    prg = yml_load(ymls[0].with_suffix(".prg"), fast=True)
                    entry.update((prg or {}).get("quarantine") or {})
                except Exception:
                    LOGGER.warning(f"Could not read the .prg beside {ymls[0]}")
            out.append(entry)
        return out
```

`syncer` worker — replace:

```python
            except Exception:
                LOGGER.error(f"Error in syncer worker for {yml_path}", exc_info=True)
```

with:

```python
            except Exception as exc:
                LOGGER.error(f"Error in syncer worker for {yml_path}", exc_info=True)
                self._strike(yml_path, f"{type(exc).__name__}: {exc}")
```

`enqueue_yml` — immediately after the `-prc.yml` branch's closing `)` and before `elif rank < rank_limit:`, insert:

```python
        elif _prg_is_quarantined(yml_path.with_suffix(".prg")):
            # Sync quarantine: every automatic re-queue (startup sweep,
            # finish_pending, parent re-walks) routes through here, so this one
            # check is the whole gate. /finish_yml releases it first.
            LOGGER.info(
                f"{str(yml_path)} is in sync quarantine; skipping enqueue request. "
                "POST /finish_yml with this path once the cause is fixed."
            )
```

`sync_yml` — replace the `if not synced:` block:

```python
        if not synced:
            LOGGER.info(
                f"{str(prog.yml.target)} is not synced after this pass; it stays "
                "in place for the next scan."
            )
            return False
```

with:

```python
        if not synced:
            LOGGER.info(
                f"{str(prog.yml.target)} is not synced after this pass; it stays "
                "in place for the next scan."
            )
            chain = self.postfinish[prog.yml.type].hooks
            failed = [
                f"{name}: {entry.get('error')}"
                for name, entry in (prog.dict.get("hooks") or {}).items()
                if entry.get("state") == "failed"
                and getattr(chain.get(name), "blocking", False)
            ]
            self._strike(
                prog.yml.target,
                failed[0] if failed else "post-finish chain did not complete",
            )
            return False
```

`self.postfinish[level]` is a `HookSet` whose `.hooks` is `dict[str, FinishHook]` keyed by the same names as the `.prg` `hooks:` states (`helao/core/hooks/loader.py:139-155`).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `conda run -n helao python -m pytest -q helao/core/tests/test_sync_quarantine.py helao/hexagon/tests/test_native_sync_pins.py helao/core/tests/test_sync_postfinish_chain.py helao/core/tests/test_sync_parent_requeue.py helao/core/tests/test_run_state_wiring.py`
Expected: all pass.

- [ ] **Step 5: Mutation check**

One at a time, in both files, then restore: remove the `enqueue_yml` quarantine branch (expect `test_a_quarantined_record_is_never_enqueued` to fail); remove the worker's `_strike` call (expect `test_an_exception_out_of_sync_yml_is_a_strike` to fail); remove the `sync_yml` `_strike` call (expect `test_a_failed_blocking_hook_is_a_strike` to fail); delete the `try/except` around `_strike`'s body (expect `test_strike_on_a_vanished_record_does_not_kill_the_worker` to fail).

- [ ] **Step 6: Commit (main thread)** — no black on the sync drivers.

```bash
black helao/core/tests/test_sync_quarantine.py
git add helao/core/drivers/data/sync_driver.py helao/hexagon/adapters/native/sync_driver.py helao/core/tests/test_sync_quarantine.py
git commit -m "feat(sync): strike both failure channels, gate enqueue on quarantine"
```

---

### Task 4: SYNC server surface — `/finish_yml` releases, `/tasks` lists; docs

**Files:**
- Modify: `helao/deploy/hte/servers/action/sync_server.py` (`finish_yml` ~line 211, `running` ~line 251)
- Modify: `helao/core/drivers/data/CLAUDE.md` (append one section)
- Test: `helao/deploy/hte/tests/test_sync_server_recovery.py` (append)

**Interfaces:**
- Consumes: Task 3 `SyncDriver.release_quarantine(yml_path) -> bool`, `SyncDriver.quarantined() -> list`.
- Produces: `/tasks` response gains key `"quarantined"`.

- [ ] **Step 1: Write the failing tests**

Append to `helao/deploy/hte/tests/test_sync_server_recovery.py`:

```python
def _route(app, path):
    return next(r.endpoint for r in app.routes if getattr(r, "path", None) == path)


class _QuarantineDriver:
    """Records the order of release and enqueue calls."""

    def __init__(self, quarantined):
        self.calls = []
        self._quarantined = quarantined
        self.running_tasks = {}
        self.task_queue = asyncio.Queue()

    def release_quarantine(self, yml_path):
        self.calls.append(("release", str(yml_path)))
        return self._quarantined

    async def enqueue_yml(self, upath, rank=0, rank_limit=-5):
        self.calls.append(("enqueue", str(upath), rank))

    def quarantined(self):
        return [{"yml": "/x/a-act.yml", "strikes": 5}]


@pytest.mark.asyncio
async def test_finish_yml_releases_quarantine_before_enqueueing(installed_config):
    app = _make_app(installed_config)
    drv = _QuarantineDriver(quarantined=True)
    _prime(app, drv)
    await _route(app, "/finish_yml")(yml_path="/x/a-act.yml")
    assert drv.calls == [("release", "/x/a-act.yml"), ("enqueue", "/x/a-act.yml", 0)]


@pytest.mark.asyncio
async def test_finish_yml_on_a_healthy_record_just_enqueues(installed_config):
    app = _make_app(installed_config)
    drv = _QuarantineDriver(quarantined=False)
    _prime(app, drv)
    await _route(app, "/finish_yml")(yml_path="'/x/b-exp.yml'")
    assert drv.calls[-1] == ("enqueue", "/x/b-exp.yml", 1)


@pytest.mark.asyncio
async def test_tasks_lists_quarantined_records(installed_config):
    app = _make_app(installed_config)
    _prime(app, _QuarantineDriver(quarantined=False))
    body = await _route(app, "/tasks")()
    assert body["quarantined"] == [{"yml": "/x/a-act.yml", "strikes": 5}]
    assert set(body) == {"running", "num_queued", "last_startup_sweep", "quarantined"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `conda run -n helao python -m pytest -q helao/deploy/hte/tests/test_sync_server_recovery.py -k "quarantine or healthy"`
Expected: FAIL — no `release` call recorded; `KeyError: 'quarantined'`.

- [ ] **Step 3: Implement**

In `finish_yml`, insert right before `await app.driver.enqueue_yml(clean_path, rank)`:

```python
        # Sync quarantine: a hand-POSTed path is the operator's re-queue, so it
        # releases the record first; enqueue_yml would otherwise skip it.
        app.driver.release_quarantine(clean_path)
```

Update its docstring's first line to: `"""Enqueue a finished YAML for upload, releasing it from sync quarantine.`

In `running()` (the `/tasks` handler), add to the returned dict after `"last_startup_sweep": ...`:

```python
            "quarantined": app.driver.quarantined(),
```

and append to its docstring: `` ``quarantined`` lists records the syncer has stopped retrying (sync quarantine spec); POST ``/finish_yml`` with a listed ``yml`` to release one.``

Append to `helao/core/drivers/data/CLAUDE.md`:

```markdown
**A record that keeps failing is quarantined, not retried forever.** Each failed pass — an exception out of `sync_yml`, or a post-finish chain left unsynced by a blocking hook — adds a strike to the `quarantine:` block in the record's `.prg`. At `quarantine_strikes` (default 5) strikes *and* a first failure at least `quarantine_hours` (default 24) old, the record is parked: one `LOGGER.alert`, a `quarantined` SYNC-journal line, and `enqueue_yml` skips it from then on — that one check covers the startup sweep, `/finish_pending` and parent re-walks. The age floor is what keeps an S3/API outage from parking good records. `/tasks` lists parked records; POST `/finish_yml` with one releases and re-queues it. Spec: `docs/superpowers/specs/2026-10-14-sync-quarantine-design.md`.
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `conda run -n helao python -m pytest -q helao/deploy/hte/tests/test_sync_server_recovery.py helao/hexagon/tests/test_hte_route_checklist.py`
Expected: all pass except the known pre-existing `sample_server.py` checklist case. `test_no_route_is_added_by_the_recovery_wiring` and the `sync_server.py` checklist case must pass.

- [ ] **Step 5: Mutation check**

Remove the `release_quarantine` line; confirm `test_finish_yml_releases_quarantine_before_enqueueing` fails; restore.

- [ ] **Step 6: Commit (main thread)**

```bash
black helao/deploy/hte/servers/action/sync_server.py helao/deploy/hte/tests/test_sync_server_recovery.py
git add helao/deploy/hte/servers/action/sync_server.py helao/deploy/hte/tests/test_sync_server_recovery.py helao/core/drivers/data/CLAUDE.md
git commit -m "feat(sync): /finish_yml releases quarantine, /tasks lists it"
```

---

### Task 5: Full verification sweep

**Files:** none modified.

- [ ] **Step 1: Run the full sweep**

Run: `conda run -n helao python run_tests.py`
Expected: no `FAIL` beyond those already failing on `unstable` at `6f64950c`. To establish that baseline, run the same command in a scratch worktree of `unstable` (`git -C /mnt/STORAGE/repos/helao/helao-async worktree add /mnt/STORAGE/repos/helao/sq-baseline unstable`), compare the two FAIL lists, then remove the worktree.

- [ ] **Step 2: Type check the changed files**

Run: `conda run -n helao pyright helao/helpers/run_state.py helao/deploy/hte/servers/action/sync_server.py helao/core/tests/test_sync_quarantine.py`
Expected: no new errors versus `unstable`. Do not run pyright on paths under `.claude/worktrees/` (it analyzes zero files there).

- [ ] **Step 3: Report**

Report the sweep result, the baseline comparison, and the mutation-check outcomes from Tasks 1–4.
