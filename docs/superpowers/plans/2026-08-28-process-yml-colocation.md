# `-prc.yml` Colocation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the `-prc.yml` write from `root/PROCESSES` to sit beside its `-exp.yml` inside the `RUNS_*` tree, so a sequence zip carries its own process identity, without changing the S3 layout or touching any archived data.

**Architecture:** Hard cutover on the write side; readers gain a shared resolver that falls back to the legacy `PROCESSES` mirror. `prc` becomes a known `HelaoYml` type guarded against ever entering the sync queue, and the two record-traversal globs that would otherwise wrap a process yml are tightened to the three record suffixes.

**Tech Stack:** Python 3.14, pytest, PyYAML/ruamel via `helao.helpers.yml_tools`, `zipfile`.

## Global Constraints

- **The two `sync_driver.py` files are byte-identical over a pinned region and must be edited identically.** `helao/core/drivers/data/sync_driver.py` is the legacy original; `helao/hexagon/adapters/native/sync_driver.py` is the native twin. `helao/hexagon/tests/sync_fixtures.py:assert_verbatim_region` pins legacy lines from `LOGGER = logging.make_logger` down to the last line of `class SyncDriver` (core line 63 through 2404, ending before `class HelaoSyncer(SyncDriver):` at 2405) as a byte-identical substring of the native file. **Every edit in this plan falls inside that region.** Apply the same patch text to both files in the same commit.
- **The pinned region must contain no `import` statement** (`sync_fixtures.py:assert_region_holds_no_imports`). Any new helper used inside it must be written inline, not imported.
- The native twin sits 4 lines below the legacy file. A legacy line `N` is native line `N + 4` for every site in this plan. Verify by content, never by line number alone.
- **The S3 key does not change.** `meta_s3_key = f"process/{uuid_key}.json"` stays exactly as it is.
- **`root/PROCESSES` is never written to, moved, or deleted.** `helao/helpers/helao_dirs.py:69,79` keeps creating it.
- **The `-prc.yml` filename format is fixed:** `{pidx}__{process_uuid}__{technique_name}-prc.yml`. `helao/core/drivers/data/loaders/localfs.py:153` splits it on `__` and breaks on any other shape.
- Run tests with the project env: `PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest <file> -q`. Do not use `conda run` — it buffers output.
- Run `black` on every changed file immediately before `git add`.
- Task 10 touches a **separate git repository** nested at `helao/deploy/priv/`. `cd` into it and use its own git; it is invisible to the parent repo's `git status`.

---

## File Structure

**Modified — parent repo:**

| File | Responsibility after this plan |
|------|-------------------------------|
| `helao/core/drivers/data/sync_driver.py` | `ABR_MAP` knows `prc`; guard in `enqueue_yml`/`sync_yml`; two globs tightened; `HelaoYml.process_ymls`; write relocated; prc included in the move set |
| `helao/hexagon/adapters/native/sync_driver.py` | Byte-identical twin of the above |
| `helao/core/drivers/data/process_locator.py` | **New.** `find_process_ymls()` — the one resolver every reader calls |
| `helao/core/drivers/data/loaders/localfs.py` | Dedupe the prc union; discriminate zip-vs-disk by origin, not suffix |
| `helao/helpers/helao_data.py` | Select the record yml by suffix instead of `glob(...)[0]` |
| `helao/helpers/processors.py` | Same, for the experiment and sequence yml lookups |
| `harness/treepass.py` | `-prc.yml` gets a location-independent comparison key |
| `helao/hexagon/tests/smoke/assert_smoke_tree.py` | Counts prc in the `RUNS_*` tree |

**Created — tests:**

| File | Covers |
|------|--------|
| `helao/core/tests/test_prc_colocation.py` | Tasks 1–5: type, guard, globs, property, write location, move set |
| `helao/core/tests/test_process_locator.py` | Task 6: the resolver's three cases |
| `helao/core/tests/test_prc_readers.py` | Tasks 7–8: `localfs`, `helao_data`, `processors` |
| `harness/tests/test_parity_prc_location.py` | Task 4: comparator location-independence |

**Modified — private repo (`helao/deploy/priv/`):** the six `scripts/edax/` tools listed in Task 10.

---

## Task 1: `prc` becomes a known type, and can never be synced

**Files:**
- Modify: `helao/core/drivers/data/sync_driver.py:64`, and `enqueue_yml` at `:1246`, and `sync_yml` at `:1274`
- Modify: `helao/hexagon/adapters/native/sync_driver.py:68`, `:1250`, `:1278` (identical text)
- Test: `helao/core/tests/test_prc_colocation.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `ABR_MAP["prc"] == "process"`, so `HelaoYml(path).type` returns `"process"` for a `*-prc.yml`. `enqueue_yml` and `sync_yml` return without acting on such a path.

**Why:** `ABR_MAP` currently holds only `act`/`exp`/`seq`, so `HelaoYml.type` raises `KeyError: 'prc'` on a process yml. That is reachable today: `helao/deploy/hte/servers/action/sync_server.py:185` exposes `POST /finish_yml`, which assigns `rank = -1` to an unrecognised suffix (`:198`), and `-1` is above `enqueue_yml`'s `rank_limit=-5`, so the path is enqueued rather than dropped.

- [ ] **Step 1: Write the failing test**

Create `helao/core/tests/test_prc_colocation.py`:

```python
"""Colocated -prc.yml: type, guard, globs, write location, move set."""

import asyncio
from pathlib import Path

import pytest

from helao.core.drivers.data.sync_driver import ABR_MAP, HelaoYml


def _tree(tmp_path: Path) -> Path:
    """A minimal RUNS_FINISHED experiment directory with one action child."""
    exp_dir = tmp_path / "RUNS_FINISHED" / "26.35" / "0828" / "seqdir" / "expdir"
    act_dir = exp_dir / "0__0__SIM__do_thing"
    act_dir.mkdir(parents=True)
    (exp_dir / "260828.120000000000-exp.yml").write_text(
        "experiment_uuid: 06a5a2d6-b26c-7019-8000-4c2d967e5df1\n"
        "experiment_name: SIM_exp\n"
    )
    (act_dir / "260828.120001000000-act.yml").write_text(
        "action_uuid: 06a5a2d6-b26c-7673-8000-9f38fe556fd6\naction_order: 0\n"
    )
    return exp_dir


def test_prc_is_a_known_record_type(tmp_path):
    assert ABR_MAP["prc"] == "process"
    exp_dir = _tree(tmp_path)
    prc = exp_dir / "0__06a5a2d6-b26c-7019-8000-4c2d967e5df1__SIM_exp-prc.yml"
    prc.write_text("process_uuid: 06a5a2d6-b26c-7019-8000-4c2d967e5df1\n")
    assert HelaoYml(prc).type == "process"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/core/tests/test_prc_colocation.py::test_prc_is_a_known_record_type -q`

Expected: FAIL with `KeyError: 'prc'`.

- [ ] **Step 3: Add `prc` to `ABR_MAP` in both twins**

In `helao/core/drivers/data/sync_driver.py:64` and `helao/hexagon/adapters/native/sync_driver.py:68`, replace:

```python
ABR_MAP = {"act": "action", "exp": "experiment", "seq": "sequence"}
```

with:

```python
ABR_MAP = {
    "act": "action",
    "exp": "experiment",
    "seq": "sequence",
    "prc": "process",
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/core/tests/test_prc_colocation.py::test_prc_is_a_known_record_type -q`

Expected: PASS.

- [ ] **Step 5: Write the failing guard test**

Append to `helao/core/tests/test_prc_colocation.py`:

```python
class _FakeQueue:
    def __init__(self):
        self.items = []

    async def put(self, item):
        self.items.append(item)


class _StubSyncer:
    """Just enough of SyncDriver to exercise enqueue_yml's guard."""

    def __init__(self):
        self.task_queue = _FakeQueue()
        self.task_set = set()
        self.running_tasks = {}

    from helao.core.drivers.data.sync_driver import SyncDriver

    enqueue_yml = SyncDriver.enqueue_yml


def test_enqueue_yml_refuses_a_process_yml(tmp_path):
    exp_dir = _tree(tmp_path)
    prc = exp_dir / "0__06a5a2d6-b26c-7019-8000-4c2d967e5df1__SIM_exp-prc.yml"
    prc.write_text("process_uuid: 06a5a2d6-b26c-7019-8000-4c2d967e5df1\n")
    syncer = _StubSyncer()
    asyncio.run(syncer.enqueue_yml(prc, rank=-1))
    assert syncer.task_queue.items == []
    assert syncer.task_set == set()


def test_enqueue_yml_still_accepts_an_action_yml(tmp_path):
    exp_dir = _tree(tmp_path)
    act = next((exp_dir / "0__0__SIM__do_thing").glob("*-act.yml"))
    syncer = _StubSyncer()
    asyncio.run(syncer.enqueue_yml(act, rank=0))
    assert len(syncer.task_queue.items) == 1
```

- [ ] **Step 6: Run to verify the guard test fails**

Run: `PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/core/tests/test_prc_colocation.py -q`

Expected: `test_enqueue_yml_refuses_a_process_yml` FAILS (the path is queued), the other two PASS.

- [ ] **Step 7: Add the guard to `enqueue_yml` in both twins**

In `helao/core/drivers/data/sync_driver.py`, inside `enqueue_yml`, the body currently begins:

```python
        yml_path = Path(upath) if isinstance(upath, str) else upath
        if rank < rank_limit:
```

Insert the guard between those two lines so it reads:

```python
        yml_path = Path(upath) if isinstance(upath, str) else upath
        if yml_path.name.endswith("-prc.yml"):
            # A process is an artifact of an experiment's sync, never a record
            # that syncs on its own. It reaches here only by mistake -- most
            # plausibly a hand-POSTed /finish_yml, which ranks an unrecognised
            # suffix -1, above rank_limit, and so enqueues rather than drops.
            LOGGER.info(
                f"{str(yml_path)} is a process artifact, not a syncable record; "
                "skipping enqueue request."
            )
        elif rank < rank_limit:
```

Apply the identical text to `helao/hexagon/adapters/native/sync_driver.py`.

- [ ] **Step 8: Add the same guard to `sync_yml` in both twins**

`enqueue_yml` is not the only entry point: `syncer()` pops the queue and calls `sync_yml` directly (`sync_driver.py:1206`), so a path queued before the guard existed would still run. In `sync_yml`, the body currently begins:

```python
        if not yml_path.exists():
            LOGGER.debug(
                f"{str(yml_path)} does not exist, assume yml has moved to synced."
            )
            return True
```

Insert immediately above it:

```python
        if yml_path.name.endswith("-prc.yml"):
            # Authoritative backstop to enqueue_yml's guard: syncer() calls this
            # directly off the queue, so anything queued before the guard
            # existed would otherwise run. Returning True retires it without a
            # requeue; finish_pending never offers it again because no
            # list_pending* glob matches a -prc.yml suffix.
            LOGGER.info(
                f"{str(yml_path)} is a process artifact, not a syncable record; "
                "not syncing."
            )
            return True
        if not yml_path.exists():
```

Apply the identical text to the native twin.

- [ ] **Step 8b: Test the `sync_yml` guard directly**

The `enqueue_yml` tests do not reach this guard, and it is the one that matters:
`syncer()` calls `sync_yml` straight off the queue, so `enqueue_yml`'s guard
alone leaves the hole this step closes. Without a test here, deleting the
`sync_yml` guard breaks nothing in the suite.

Append to `helao/core/tests/test_prc_colocation.py`:

```python
def test_sync_yml_refuses_a_process_yml(tmp_path):
    """syncer() calls sync_yml directly off the queue, so this guard is the
    authoritative one and needs its own coverage."""
    from helao.core.drivers.data.sync_driver import SyncDriver
    from helao.hexagon.tests.sync_fixtures import make_sync_driver

    driver = make_sync_driver(tmp_path, SyncDriver)
    exp_dir = _tree(tmp_path)
    prc = exp_dir / "0__06a5a2d6-b26c-7019-8000-4c2d967e5df1__SIM_exp-prc.yml"
    prc.write_text("process_uuid: 06a5a2d6-b26c-7019-8000-4c2d967e5df1\n")

    called = []
    driver.get_progress = lambda p: called.append(p)  # must never be reached

    assert asyncio.run(driver.sync_yml(yml_path=prc)) is True
    assert called == [], "sync_yml must return before touching progress"
```

Run it, confirm it passes, then confirm it is load-bearing: comment out the
`sync_yml` guard, re-run, see it FAIL, restore the guard.

- [ ] **Step 9: Run the guard tests and the twin-parity pin**

```bash
PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest \
  helao/core/tests/test_prc_colocation.py \
  helao/hexagon/tests/test_native_sync_pins.py \
  helao/hexagon/tests/test_native_sync_driver.py -q
```

Expected: all PASS. The byte-identity gate is `test_native_sync_pins.py` — `test_verbatim_region` and `test_region_holds_no_imports` plus eight per-member parity pins. `test_native_sync_driver.py` holds only a construction and an enqueue-dedup test and asserts nothing about the twins, so running it alone proves nothing about byte-identity. If a pin fails with "not byte-identical", the two twins differ — diff them and make the patch text match exactly.

- [ ] **Step 10: Commit**

```bash
/home/dan/miniforge3/envs/helao/bin/black \
  helao/core/drivers/data/sync_driver.py \
  helao/hexagon/adapters/native/sync_driver.py \
  helao/core/tests/test_prc_colocation.py
git add helao/core/drivers/data/sync_driver.py \
        helao/hexagon/adapters/native/sync_driver.py \
        helao/core/tests/test_prc_colocation.py
git commit -m "feat(sync): a process yml is a known type that can never be synced

ABR_MAP held only act/exp/seq, so HelaoYml.type raised KeyError on a
-prc.yml. That is reachable: /finish_yml ranks an unrecognised suffix -1,
which is above enqueue_yml's rank_limit of -5, so the path enqueues rather
than dropping. Adds prc to the map and refuses it in both enqueue_yml and
sync_yml -- both, because syncer() calls sync_yml straight off the queue."
```

---

## Task 2: Record traversal stops finding process ymls

**Files:**
- Modify: `helao/core/drivers/data/sync_driver.py:432` (`list_children`) and `:528` (`parent_path`)
- Modify: `helao/hexagon/adapters/native/sync_driver.py:436` and `:532` (identical text)
- Test: `helao/core/tests/test_prc_colocation.py`

**Interfaces:**
- Consumes: `ABR_MAP` from Task 1 (not strictly required, but the guard there is the backstop for anything this misses).
- Produces: `HelaoYml.list_children()` and `HelaoYml.parent_path` ignore `*-prc.yml`.

**Why:** `list_children` globs `yml_path.parent.glob("*/*.yml")`; from a sequence directory that is the experiment directories, so a colocated prc would be returned and wrapped in `HelaoYml`. `parent_path` globs `x.parent.parent.glob("*.yml")` and takes `p[0]`, which for an action is the experiment directory — where the prc now lives — so it could return the prc as the parent.

Note that `HelaoYml.__init__`'s directory glob at `:275` is **already** filtered to `-seq`/`-exp`/`-act` and needs no change. Do not touch it.

- [ ] **Step 1: Write the failing test**

Append to `helao/core/tests/test_prc_colocation.py`:

```python
def test_list_children_ignores_a_colocated_process_yml(tmp_path):
    exp_dir = _tree(tmp_path)
    seq_dir = exp_dir.parent
    (seq_dir / "260828.115959000000-seq.yml").write_text("sequence_name: SIM_seq\n")
    (exp_dir / "0__06a5a2d6-b26c-7019-8000-4c2d967e5df1__SIM_exp-prc.yml").write_text(
        "process_uuid: 06a5a2d6-b26c-7019-8000-4c2d967e5df1\n"
    )
    seq_yml = next(seq_dir.glob("*-seq.yml"))
    children = HelaoYml(seq_yml).list_children(seq_yml)
    assert [c.type for c in children] == ["experiment"]


def test_parent_path_of_an_action_is_the_experiment_not_the_process(tmp_path):
    exp_dir = _tree(tmp_path)
    # sorts before the -exp.yml, so a bare glob's [0] would pick it
    (exp_dir / "0__06a5a2d6-b26c-7019-8000-4c2d967e5df1__SIM_exp-prc.yml").write_text(
        "process_uuid: 06a5a2d6-b26c-7019-8000-4c2d967e5df1\n"
    )
    act = next((exp_dir / "0__0__SIM__do_thing").glob("*-act.yml"))
    assert HelaoYml(act).parent_path.name.endswith("-exp.yml")
```

- [ ] **Step 2: Run to verify both fail**

Run: `PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/core/tests/test_prc_colocation.py -q -k "list_children or parent_path"`

Expected: FAIL. `list_children` returns two entries; `parent_path` returns the prc.

- [ ] **Step 3: Tighten both globs in both twins**

In `list_children`, replace:

```python
        paths = yml_path.parent.glob("*/*.yml")
```

with:

```python
        # Record suffixes only. A colocated ``-prc.yml`` is a process artifact
        # sitting beside its experiment, not a child record, and wrapping one
        # in HelaoYml would put a process into the sync hierarchy.
        paths = [
            p
            for p in yml_path.parent.glob("*/*.yml")
            if p.stem.endswith(("-seq", "-exp", "-act"))
        ]
```

In `parent_path`, replace:

```python
                list(x.parent.parent.glob("*.yml"))
```

with:

```python
                [
                    p
                    for p in x.parent.parent.glob("*.yml")
                    if p.stem.endswith(("-seq", "-exp", "-act"))
                ]
```

Apply the identical text to the native twin.

- [ ] **Step 4: Run to verify they pass**

```bash
PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest \
  helao/core/tests/test_prc_colocation.py \
  helao/hexagon/tests/test_native_sync_pins.py \
  helao/hexagon/tests/test_native_sync_driver.py -q
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
/home/dan/miniforge3/envs/helao/bin/black \
  helao/core/drivers/data/sync_driver.py \
  helao/hexagon/adapters/native/sync_driver.py \
  helao/core/tests/test_prc_colocation.py
git add helao/core/drivers/data/sync_driver.py \
        helao/hexagon/adapters/native/sync_driver.py \
        helao/core/tests/test_prc_colocation.py
git commit -m "fix(sync): record traversal must not pick up a process artifact

list_children globs parent/*/*.yml, which from a sequence directory is the
experiment directories; parent_path globs two levels up and takes [0],
which for an action is the experiment directory. Both would return a
colocated -prc.yml -- parent_path preferentially, since the filename sorts
ahead of the timestamped -exp.yml. Filtered to the three record suffixes.
HelaoYml.__init__'s own glob was already filtered and is untouched."
```

---

## Task 3: `HelaoYml.process_ymls`

**Files:**
- Modify: `helao/core/drivers/data/sync_driver.py` (new property beside `hlo_files`, around `:510`)
- Modify: `helao/hexagon/adapters/native/sync_driver.py` (identical text)
- Test: `helao/core/tests/test_prc_colocation.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `HelaoYml.process_ymls -> list[Path]` — `*-prc.yml` files in the immediate target directory. Task 5 uses it.

**Why:** `move_to_synced` relocates `misc_files + hlo_files` and then the record yml. A `-prc.yml` is in none of those sets — `_is_syncable_misc_file` (`:481`) excludes `.yml` — so once the write moves, a prc would be stranded. This property names the set that has to travel.

Write it inline with no imports: it sits inside the pinned verbatim region, which `assert_region_holds_no_imports` requires to contain none.

- [ ] **Step 1: Write the failing test**

Append to `helao/core/tests/test_prc_colocation.py`:

```python
def test_process_ymls_lists_colocated_prc_only(tmp_path):
    exp_dir = _tree(tmp_path)
    (exp_dir / "0__06a5a2d6-b26c-7019-8000-4c2d967e5df1__SIM_exp-prc.yml").write_text(
        "process_uuid: 06a5a2d6-b26c-7019-8000-4c2d967e5df1\n"
    )
    (exp_dir / "1__06a5a2d6-b26c-7673-8000-9f38fe556fd6__SIM_exp-prc.yml").write_text(
        "process_uuid: 06a5a2d6-b26c-7673-8000-9f38fe556fd6\n"
    )
    exp_yml = next(exp_dir.glob("*-exp.yml"))
    found = HelaoYml(exp_yml).process_ymls
    assert sorted(p.name for p in found) == [
        "0__06a5a2d6-b26c-7019-8000-4c2d967e5df1__SIM_exp-prc.yml",
        "1__06a5a2d6-b26c-7673-8000-9f38fe556fd6__SIM_exp-prc.yml",
    ]


def test_process_ymls_is_empty_for_an_action(tmp_path):
    exp_dir = _tree(tmp_path)
    act = next((exp_dir / "0__0__SIM__do_thing").glob("*-act.yml"))
    assert HelaoYml(act).process_ymls == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/core/tests/test_prc_colocation.py -q -k process_ymls`

Expected: FAIL with `AttributeError: 'HelaoYml' object has no attribute 'process_ymls'`.

- [ ] **Step 3: Add the property to both twins**

Immediately after the `hlo_files` property, insert:

```python
    @property
    def process_ymls(self) -> list[Path]:
        """``*-prc.yml`` files in the immediate target directory.

        A process artifact is colocated with the ``-exp.yml`` it belongs to, so
        it is in neither :attr:`misc_files` (which excludes ``.yml``) nor
        :attr:`hlo_files`. It therefore has to be named explicitly in the set
        that moves to ``RUNS_SYNCED``; left behind, it both orphans the process
        and keeps :meth:`cleanup` reporting the directory as not empty forever.
        """
        return [
            x
            for x in self.targetdir.glob("*-prc.yml")
            if x.is_file()
        ]
```

Apply the identical text to the native twin.

- [ ] **Step 4: Run to verify it passes**

```bash
PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest \
  helao/core/tests/test_prc_colocation.py \
  helao/hexagon/tests/test_native_sync_pins.py \
  helao/hexagon/tests/test_native_sync_driver.py -q
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
/home/dan/miniforge3/envs/helao/bin/black \
  helao/core/drivers/data/sync_driver.py \
  helao/hexagon/adapters/native/sync_driver.py \
  helao/core/tests/test_prc_colocation.py
git add helao/core/drivers/data/sync_driver.py \
        helao/hexagon/adapters/native/sync_driver.py \
        helao/core/tests/test_prc_colocation.py
git commit -m "feat(sync): name the process artifacts that travel with a record

A colocated -prc.yml is in neither misc_files (which excludes .yml) nor
hlo_files, so nothing in move_to_synced would carry it. Adds the property
that names the set, ahead of the write relocation that needs it."
```

---

## Task 4: The parity comparator stops caring where a prc lives

**Files:**
- Modify: `harness/treepass.py:236-256` (`snapshot`)
- Test: `harness/tests/test_parity_prc_location.py`

**Interfaces:**
- Consumes: `ArtifactRow.PRC_YML` from `harness/classify.py:120`, which already classifies `*-prc.yml`.
- Produces: `snapshot()` keys a `-prc.yml` by filename alone, so golden and candidate agree whether the file came from `PROCESSES/...` or from an exploded sequence zip.

**Why, and why this task comes before the write moves:** `helao/hexagon/tests/test_native_sync_parity.py` compares `root/{RUNS_*,PROCESSES,S3_SIM}` against the committed GM-1 golden, which holds 33 `-prc.yml` under `root/PROCESSES/`. `run_parity` explodes zips in both trees and `diff_member_sets` compares normalized member sets, so relocating the write would show every prc as missing from `PROCESSES` and extra inside the zip. The golden stays immutable; the comparator learns both locations. Landing this first keeps the gate green throughout.

The process uuid is in the filename and `mapper.sub` already substitutes it, so a filename-derived key is unique — and `snapshot` raises on a normalized-name collision, so a mistake fails loud rather than silently merging two processes.

- [ ] **Step 1: Write the failing test**

Create `harness/tests/test_parity_prc_location.py`:

```python
"""A -prc.yml compares equal whether it sits in PROCESSES or inside a zip."""

from pathlib import Path

from harness.treepass import seed_mapper, snapshot
from harness.uuidmap import UuidMapper

PRC = "0__06a5a2d6-b26c-7019-8000-4c2d967e5df1__SIM_exp-prc.yml"
BODY = "process_uuid: 06a5a2d6-b26c-7019-8000-4c2d967e5df1\n"


def _legacy_tree(root: Path) -> Path:
    d = root / "PROCESSES" / "26.35" / "0828" / "260828.115959__seq" / "260828.120000__exp"
    d.mkdir(parents=True)
    (d / PRC).write_text(BODY)
    return root


def _colocated_tree(root: Path) -> Path:
    d = (
        root
        / "RUNS_SYNCED"
        / "26.35"
        / "0828"
        / "260828.115959__seq"
        / "260828.120000__exp"
    )
    d.mkdir(parents=True)
    (d / PRC).write_text(BODY)
    return root


def test_prc_key_is_the_same_in_both_locations(tmp_path):
    legacy = _legacy_tree(tmp_path / "legacy")
    colocated = _colocated_tree(tmp_path / "colocated")
    # snapshot() substitutes uuids with strict=True, so the mapper must be
    # seeded from the same tree first -- every existing call site in harness/
    # pairs seed_mapper with snapshot for exactly this reason. Without it the
    # test raises KeyError: unseeded uuid, before and after the fix alike.
    mg, mc = UuidMapper(), UuidMapper()
    seed_mapper(legacy, mg)
    seed_mapper(colocated, mc)
    g = snapshot(legacy, mg)
    c = snapshot(colocated, mc)
    assert set(g.files) == set(c.files), (
        f"prc keys differ: golden={sorted(g.files)} candidate={sorted(c.files)}"
    )
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest harness/tests/test_parity_prc_location.py -q`

Expected: FAIL — the two key sets differ by their directory prefixes.

- [ ] **Step 3: Give `-prc.yml` a location-independent key**

In `harness/treepass.py`, inside `snapshot`, the loop body currently reads:

```python
        parts = f.relative_to(root).parts
        norm_parts = []
        cur = root
        for name in parts[:-1]:
            cur = cur / name
            norm_parts.append(token_of[cur])
        norm_parts.append(normalize_name(parts[-1]))
        norm = mapper.sub("/".join(norm_parts), strict=True)
```

Replace it with:

```python
        parts = f.relative_to(root).parts
        if row is ArtifactRow.PRC_YML:
            # A process artifact is keyed by its filename alone, never by its
            # path. The write moved from root/PROCESSES into the RUNS_* tree
            # (and so into the sequence zip), and the golden sets predate that
            # move; keying by path would report every process as both missing
            # and extra. The filename is
            # {pidx}__{process_uuid}__{technique}-prc.yml, so the key is unique
            # by construction -- and snapshot raises on a collision, so a
            # mistake here fails loud rather than merging two processes.
            norm = mapper.sub(f"PRC/{normalize_name(parts[-1])}", strict=True)
        else:
            norm_parts = []
            cur = root
            for name in parts[:-1]:
                cur = cur / name
                norm_parts.append(token_of[cur])
            norm_parts.append(normalize_name(parts[-1]))
            norm = mapper.sub("/".join(norm_parts), strict=True)
```

If `ArtifactRow` is not already imported at the top of `harness/treepass.py`, add it — `treepass.py` is **not** subject to the no-imports pin, which applies only to the `sync_driver.py` verbatim region.

- [ ] **Step 4: Run to verify it passes, and that the golden gate is still green**

```bash
PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest \
  harness/tests/test_parity_prc_location.py -q
PYTHONPATH=$PWD timeout 600 /home/dan/miniforge3/envs/helao/bin/python -m pytest \
  helao/hexagon/tests/test_native_sync_parity.py -q
```

Expected: both PASS. The parity gate must be **green here, before the write moves** — that is the point of doing this task first. If it reports skipped, the GM-1 golden is missing at `$HELAO_GOLDENS` (default `/home/dan/helao_goldens`); a silent skip guts the gate, so resolve it rather than proceeding.

- [ ] **Step 5: Commit**

```bash
/home/dan/miniforge3/envs/helao/bin/black harness/treepass.py harness/tests/test_parity_prc_location.py
git add harness/treepass.py harness/tests/test_parity_prc_location.py
git commit -m "test(harness): compare a process artifact by identity, not by path

The golden sets hold their -prc.yml under root/PROCESSES; the write is
moving into the RUNS_* tree and so into the sequence zip. Keying the
comparison by path would report all 33 of GM-1's processes as both missing
and extra. Keys them by filename, which carries the process uuid and is
unique by construction -- and snapshot already raises on a normalized-name
collision, so a mistake fails loud. The goldens stay immutable."
```

---

## Task 5: Relocate the write, and carry the prc to `RUNS_SYNCED`

**Files:**
- Modify: `helao/core/drivers/data/sync_driver.py:2046-2053` (`sync_process`) and `:1616` (the move set)
- Modify: `helao/hexagon/adapters/native/sync_driver.py:2050-2057` and `:1620` (identical text)
- Test: `helao/core/tests/test_prc_colocation.py`

**Interfaces:**
- Consumes: `HelaoYml.process_ymls` from Task 3; the comparator change from Task 4.
- Produces: `sync_process` writes `{pidx}__{uuid}__{technique}-prc.yml` into `exp_prog.yml.target.parent`. Nothing is written under `helaodirs.process_root`.

**Why:** this is the change the whole plan exists for. It lands after Tasks 3 and 4 so the move set and the golden gate are ready for it.

- [ ] **Step 1: Write the failing test**

Append to `helao/core/tests/test_prc_colocation.py`:

```python
def test_sync_process_writes_beside_the_exp_yml(tmp_path):
    """The prc lands in the experiment directory and nowhere else.

    Drives the real sync_process through the fixture builders rather than
    stubbing it, so the assertion covers the path construction actually used.
    """
    from helao.core.drivers.data.sync_driver import SyncDriver
    from helao.hexagon.tests.sync_fixtures import (
        make_action,
        make_exp_tree,
        make_sync_driver,
        mk_uuid,
    )
    from helao.core.models.run_dir import RunDir

    driver = make_sync_driver(tmp_path, SyncDriver)
    exp_yml = make_exp_tree(
        tmp_path, RunDir.FINISHED.value, mk_uuid(1001), process_order_groups={0: [0]}
    )
    make_action(exp_yml, 0, process_finish=True)

    exp_prog = driver.get_progress(exp_yml)
    asyncio.run(driver.sync_process(exp_prog, force=True))

    written = list(exp_yml.parent.glob("*-prc.yml"))
    assert len(written) == 1, f"expected one prc beside the exp yml, got {written}"
    assert not list((tmp_path / "PROCESSES").rglob("*-prc.yml")), (
        "nothing may be written under process_root"
    )
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/core/tests/test_prc_colocation.py -q -k sync_process_writes`

Expected: FAIL — no prc beside the exp yml; one appears under `PROCESSES`.

Should the fixture helpers not compose as written, read `helao/hexagon/tests/sync_fixtures.py:173-280` and adapt; do not weaken the two assertions.

- [ ] **Step 3: Relocate the write in both twins**

In `sync_process`, replace:

```python
                save_dir = os.path.dirname(
                    os.path.join(
                        self.helaodirs.process_root,
                        exp_prog.yml.relative_path,
                    )
                )
```

with:

```python
                # Beside the -exp.yml, inside the RUNS_* tree, so the sequence
                # zip carries its own process identity. It used to go to
                # helaodirs.process_root, which zip_dir never reaches -- so an
                # archived sequence recorded no process identity at all and
                # every repair tool had to consult a parallel tree that might
                # no longer be beside the zip it was repairing.
                save_dir = str(exp_prog.yml.target.parent)
```

Leave the `save_yml_path`, `os.makedirs`, and `meta_s3_key` lines exactly as they are. Apply the identical text to the native twin.

- [ ] **Step 4: Run to verify the write test passes**

Run: `PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/core/tests/test_prc_colocation.py -q -k sync_process_writes`

Expected: PASS.

- [ ] **Step 5: Write the failing stranding test**

Append to `helao/core/tests/test_prc_colocation.py`:

```python
def test_the_prc_moves_with_the_record_and_the_directory_cleans_up(tmp_path):
    """Drive the real move and assert the outcome, not the set composition.

    A stranded prc is worse than an orphan: cleanup() walks up from the moved
    record and reports any non-empty directory as "failed", so the leftover
    would keep the experiment directory alive forever. Asserting
    ``prc in misc_files + hlo_files + process_ymls`` would only restate the
    production expression in the test and would pass before the fix -- so this
    drives move_to_synced and looks at where the file actually ends up.
    """
    from helao.core.drivers.data.sync_driver import SyncDriver
    from helao.core.models.run_dir import RunDir
    from helao.hexagon.tests.sync_fixtures import (
        make_action,
        make_exp_tree,
        make_sync_driver,
        mk_uuid,
    )

    driver = make_sync_driver(tmp_path, SyncDriver)
    exp_yml = make_exp_tree(
        tmp_path, RunDir.FINISHED.value, mk_uuid(3001), process_order_groups={0: [0]}
    )
    make_action(exp_yml, 0, process_finish=True)
    asyncio.run(driver.sync_process(driver.get_progress(exp_yml), force=True))
    written = list(exp_yml.parent.glob("*-prc.yml"))
    assert len(written) == 1

    asyncio.run(driver.sync_yml(yml_path=exp_yml))

    finished_leftovers = [
        p for p in (tmp_path / RunDir.FINISHED.value).rglob("*-prc.yml")
    ]
    assert not finished_leftovers, (
        f"the prc was stranded in RUNS_FINISHED: {finished_leftovers}"
    )
    synced = list((tmp_path / RunDir.SYNCED.value).rglob("*-prc.yml"))
    assert len(synced) == 1, f"the prc must travel to RUNS_SYNCED, found {synced}"
```

If `sync_yml` cannot be driven to completion in this fixture (it uploads and
moves), narrow the second half to the move step the driver exposes and assert
the same two outcomes — the prc absent from `RUNS_FINISHED` and present under
`RUNS_SYNCED`. Do not fall back to asserting the set composition.

- [ ] **Step 6: Run to verify it fails**

Run: `PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/core/tests/test_prc_colocation.py -q -k moves_with_the_record`

Expected: FAIL — the prc is left behind in `RUNS_FINISHED` because nothing moves it yet.

- [ ] **Step 7: Add the prc to the move set in both twins**

Replace:

```python
            for file_path in prog.yml.misc_files + prog.yml.hlo_files:
```

with:

```python
            for file_path in (
                prog.yml.misc_files + prog.yml.hlo_files + prog.yml.process_ymls
            ):
```

Apply the identical text to the native twin.

- [ ] **Step 8: Run the full local gate**

```bash
PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest \
  helao/core/tests/test_prc_colocation.py \
  helao/hexagon/tests/test_native_sync_pins.py \
  helao/hexagon/tests/test_native_sync_driver.py \
  helao/core/tests/unit_test_sync_process_recovery.py -q
PYTHONPATH=$PWD timeout 600 /home/dan/miniforge3/envs/helao/bin/python -m pytest \
  helao/hexagon/tests/test_native_sync_parity.py -q
```

Expected: all PASS, including the golden gate — which passes only because Task 4 landed first. If `unit_test_sync_process_recovery.py` reports NOTESTS it is a `__main__` script; run it directly with `PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m helao.core.tests.unit_test_sync_process_recovery`.

- [ ] **Step 9: Commit**

```bash
/home/dan/miniforge3/envs/helao/bin/black \
  helao/core/drivers/data/sync_driver.py \
  helao/hexagon/adapters/native/sync_driver.py \
  helao/core/tests/test_prc_colocation.py
git add helao/core/drivers/data/sync_driver.py \
        helao/hexagon/adapters/native/sync_driver.py \
        helao/core/tests/test_prc_colocation.py
git commit -m "feat(sync): write a process beside its experiment, not to PROCESSES

A process's only on-disk artifact went to root/PROCESSES, which zip_dir
never reaches, so a sequence zip carried no process identity at all. It now
writes into the experiment's own directory and travels with the record to
RUNS_SYNCED. The S3 key is untouched: process/{process_uuid}.json.

Carrying it matters twice over. A stranded prc is in neither misc_files nor
hlo_files, so nothing would have moved it -- and cleanup() walks up from the
moved record reporting any non-empty directory as failed, so the leftover
would have kept the experiment directory alive forever."
```

---

## Task 6: `find_process_ymls`, the one resolver

**Files:**
- Create: `helao/core/drivers/data/process_locator.py`
- Test: `helao/core/tests/test_process_locator.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:

```python
def find_process_ymls(
    experiment: str | os.PathLike,
    process_root: str | os.PathLike | None = None,
) -> list[Path]
```

`experiment` is an `-exp.yml` path or the experiment directory. Returns colocated `*-prc.yml` first, then any from the legacy `PROCESSES` mirror whose `process_uuid` is not already present. Tasks 7 and 10 call it.

**Why:** the readers all need the same two-location rule, and it must live in exactly one place. It is deliberately **not** used by `sync_driver.py`: the write side needs only the colocated set (Task 3's property), and the verbatim region forbids new imports.

- [ ] **Step 1: Write the failing test**

Create `helao/core/tests/test_process_locator.py`:

```python
"""find_process_ymls: colocated, legacy mirror, and both at once."""

from pathlib import Path

import pytest

from helao.core.drivers.data.process_locator import find_process_ymls

REL = Path("26.35") / "0828" / "260828.115959__seq" / "260828.120000__exp"
UUID_A = "06a5a2d6-b26c-7019-8000-4c2d967e5df1"
UUID_B = "06a5a2d6-b26c-7673-8000-9f38fe556fd6"


def _prc_name(pidx: int, uuid: str) -> str:
    return f"{pidx}__{uuid}__SIM_exp-prc.yml"


def _make(root: Path, colocated: list[str], legacy: list[str]) -> Path:
    exp_dir = root / "RUNS_SYNCED" / REL
    exp_dir.mkdir(parents=True)
    (exp_dir / "260828.120000000000-exp.yml").write_text("experiment_name: SIM_exp\n")
    for name in colocated:
        (exp_dir / name).write_text(f"process_uuid: {name.split('__')[1]}\n")
    if legacy:
        leg = root / "PROCESSES" / REL
        leg.mkdir(parents=True)
        for name in legacy:
            (leg / name).write_text(f"process_uuid: {name.split('__')[1]}\n")
    return exp_dir


def test_colocated_only(tmp_path):
    exp_dir = _make(tmp_path, [_prc_name(0, UUID_A)], [])
    found = find_process_ymls(exp_dir, process_root=tmp_path / "PROCESSES")
    assert [p.name for p in found] == [_prc_name(0, UUID_A)]
    assert found[0].parent == exp_dir


def test_legacy_mirror_only(tmp_path):
    exp_dir = _make(tmp_path, [], [_prc_name(0, UUID_A)])
    found = find_process_ymls(exp_dir, process_root=tmp_path / "PROCESSES")
    assert [p.name for p in found] == [_prc_name(0, UUID_A)]
    assert "PROCESSES" in found[0].parts


def test_colocated_wins_the_dedupe(tmp_path):
    exp_dir = _make(
        tmp_path, [_prc_name(0, UUID_A)], [_prc_name(0, UUID_A), _prc_name(1, UUID_B)]
    )
    found = find_process_ymls(exp_dir, process_root=tmp_path / "PROCESSES")
    by_uuid = {p.name.split("__")[1]: p for p in found}
    assert set(by_uuid) == {UUID_A, UUID_B}
    assert by_uuid[UUID_A].parent == exp_dir, "colocated must win"
    assert "PROCESSES" in by_uuid[UUID_B].parts, "the mirror still supplies B"


def test_accepts_an_exp_yml_path(tmp_path):
    exp_dir = _make(tmp_path, [_prc_name(0, UUID_A)], [])
    exp_yml = next(exp_dir.glob("*-exp.yml"))
    assert find_process_ymls(exp_yml, process_root=tmp_path / "PROCESSES") == (
        find_process_ymls(exp_dir, process_root=tmp_path / "PROCESSES")
    )


def test_neither_location_has_anything(tmp_path):
    exp_dir = _make(tmp_path, [], [])
    assert find_process_ymls(exp_dir, process_root=tmp_path / "PROCESSES") == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/core/tests/test_process_locator.py -q`

Expected: FAIL with `ModuleNotFoundError: helao.core.drivers.data.process_locator`.

- [ ] **Step 3: Write the module**

Create `helao/core/drivers/data/process_locator.py`:

```python
"""Locate a experiment's ``-prc.yml`` artifacts, in either of the two places
they have lived.

A process's only on-disk artifact used to be written to ``root/PROCESSES``,
mirroring the record's relative path but sitting outside the ``RUNS_*`` tree
that gets zipped. It is now written beside its ``-exp.yml``. Records synced
before that change keep their artifact in the mirror, and nothing migrates
them, so every reader needs the same two-location rule -- which is why it
lives here and not copied into each one.

The write side does not use this. It needs only the colocated set, and
``HelaoYml.process_ymls`` supplies that without an import, which the byte-pinned
region of ``sync_driver.py`` requires.
"""

import os
import re
from pathlib import Path

#: ``{pidx}__{process_uuid}__{technique_name}-prc.yml`` -- the shape
#: ``sync_process`` writes and ``localfs.parse_process_path`` splits on.
PRC_NAME = re.compile(r"^(?P<pidx>\d+)__(?P<uuid>[^_]+(?:_[^_]+)*?)__.*-prc\.yml$")


def process_uuid_of(path: "str | os.PathLike[str]") -> str:
    """The process uuid a ``-prc.yml`` filename carries.

    Args:
        path: Path to a ``-prc.yml``.

    Returns:
        The uuid segment, or ``""`` when the name does not match the format.
    """
    name = Path(path).name
    parts = name[: -len("-prc.yml")].split("__") if name.endswith("-prc.yml") else []
    return parts[1] if len(parts) >= 3 else ""


def _experiment_dir(experiment: "str | os.PathLike[str]") -> Path:
    p = Path(experiment)
    return p.parent if p.is_file() or p.name.endswith(".yml") else p


def find_process_ymls(
    experiment: "str | os.PathLike[str]",
    process_root: "str | os.PathLike[str] | None" = None,
) -> list[Path]:
    """Every ``-prc.yml`` belonging to one experiment, from both locations.

    Args:
        experiment: The experiment's ``-exp.yml`` path, or its directory.
        process_root: Root of the legacy ``PROCESSES`` mirror. When ``None``,
            only the colocated artifacts are returned.

    Returns:
        Colocated artifacts first, then any mirror artifact whose process uuid
        is not already present. Sorted by filename within each source, so the
        result is stable across filesystems.
    """
    exp_dir = _experiment_dir(experiment)
    found = sorted(
        (x for x in exp_dir.glob("*-prc.yml") if x.is_file()), key=lambda x: x.name
    )
    if process_root is None:
        return found

    seen = {process_uuid_of(x) for x in found}
    mirror = _mirror_dir(exp_dir, Path(process_root))
    if mirror is None or not mirror.is_dir():
        return found

    for x in sorted(
        (y for y in mirror.glob("*-prc.yml") if y.is_file()), key=lambda y: y.name
    ):
        uuid = process_uuid_of(x)
        if uuid and uuid in seen:
            continue  # the colocated copy wins
        seen.add(uuid)
        found.append(x)
    return found


def _mirror_dir(exp_dir: Path, process_root: Path) -> "Path | None":
    """The ``PROCESSES`` directory mirroring ``exp_dir``.

    The mirror reproduces the record's path below the ``RUNS_*`` segment, so
    that segment is where the two trees are rejoined. Returns ``None`` when
    ``exp_dir`` is not inside a ``RUNS_*`` tree, which is the only case where no
    correspondence exists.
    """
    parts = exp_dir.parts
    runs = [i for i, p in enumerate(parts) if p.startswith("RUNS_")]
    if not runs:
        return None
    return process_root.joinpath(*parts[runs[0] + 1 :])
```

- [ ] **Step 4: Run to verify it passes**

Run: `PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/core/tests/test_process_locator.py -q`

Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
/home/dan/miniforge3/envs/helao/bin/black \
  helao/core/drivers/data/process_locator.py helao/core/tests/test_process_locator.py
git add helao/core/drivers/data/process_locator.py helao/core/tests/test_process_locator.py
git commit -m "feat(data): one resolver for both places a -prc.yml can live

Records synced before the write moved keep their artifact in the PROCESSES
mirror and nothing migrates them, so every reader needs the same
two-location rule with the colocated copy winning the dedupe. Putting it in
one module is the point; copied into each reader it would drift.

Deliberately not used by sync_driver: the write side needs only the
colocated set, and HelaoYml.process_ymls supplies that without an import,
which the byte-pinned region forbids."
```

---

## Task 7: `localfs` reads processes from a zip

**Files:**
- Modify: `helao/core/drivers/data/loaders/localfs.py:242-245` (the zip branch's union) and `:368` (`get_yml`)
- Test: `helao/core/tests/test_prc_readers.py`

**Interfaces:**
- Consumes: `process_uuid_of` from Task 6.
- Produces: `HelaoLoader` indexes each process once whether it comes from the zip or the mirror, and reads each from the right place.

**Why:** two independent bugs surface once prc ymls live inside zips.

The zip branch already unions the zip's ymls with a `PROCESSES/**/*-prc.yml` disk glob, so a record with both a colocated copy and a mirror entry yields the process **twice**.

And `get_yml` decides where to read from with `self.target.endswith(".zip") and not path.endswith("-prc.yml")` — i.e. it treats "is a prc" as a proxy for "is on disk". That proxy dies the moment a prc is a zip member: the code would try `FileMapper` on a path that is relative to the zip root and does not exist on disk.

- [ ] **Step 1: Write the failing test**

Create `helao/core/tests/test_prc_readers.py`:

```python
"""Readers resolve a -prc.yml from either location, exactly once."""

import zipfile
from pathlib import Path

import pytest

PRC_A = "0__06a5a2d6-b26c-7019-8000-4c2d967e5df1__SIM_exp-prc.yml"
BODY_A = "process_uuid: 06a5a2d6-b26c-7019-8000-4c2d967e5df1\ntechnique_name: SIM_exp\n"


def _zip_with_prc(tmp_path: Path) -> Path:
    """A synced sequence zip carrying its own -prc.yml, plus an empty mirror."""
    synced = tmp_path / "RUNS_SYNCED" / "26.35" / "0828"
    synced.mkdir(parents=True)
    zpath = synced / "115959__SIM_seq__golden.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("260828.115959000000-seq.yml", "sequence_name: SIM_seq\n")
        zf.writestr("260828.120000__exp/260828.120000000000-exp.yml",
                    "experiment_name: SIM_exp\n")
        zf.writestr(f"260828.120000__exp/{PRC_A}", BODY_A)
    (tmp_path / "PROCESSES").mkdir()
    return zpath


def test_a_prc_inside_a_zip_is_read_from_the_zip(tmp_path):
    from helao.core.drivers.data.loaders.localfs import LocalLoader

    zpath = _zip_with_prc(tmp_path)
    loader = LocalLoader(str(zpath))
    prc_paths = loader._yml_paths["prc"]
    assert len(prc_paths) == 1, f"expected one process, got {prc_paths}"
    meta = loader.get_yml(prc_paths[0])
    assert meta["process_uuid"] == "06a5a2d6-b26c-7019-8000-4c2d967e5df1"


def test_a_process_present_in_both_places_is_indexed_once(tmp_path):
    from helao.core.drivers.data.loaders.localfs import LocalLoader

    zpath = _zip_with_prc(tmp_path)
    # LocalLoader derives process_dir itself: for a zip it replaces the
    # RUNS_<state> segment with PROCESSES and drops the .zip suffix, so the
    # mirror for this zip is PROCESSES/26.35/0828/115959__SIM_seq__golden/.
    mirror = (
        tmp_path
        / "PROCESSES"
        / "26.35"
        / "0828"
        / "115959__SIM_seq__golden"
        / "260828.120000__exp"
    )
    mirror.mkdir(parents=True)
    (mirror / PRC_A).write_text(BODY_A)
    loader = LocalLoader(str(zpath))
    assert len(loader._yml_paths["prc"]) == 1, "the same process must not appear twice"
```

`LocalLoader.__init__` takes only `data_path` (`localfs.py:195`) and derives `process_dir` itself by replacing the `RUNS_<state>` segment with `PROCESSES` (`:218-224`), which is why the fixture places the mirror at that exact path.

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/core/tests/test_prc_readers.py -q`

Expected: the read test FAILS (`FileMapper` cannot open a zip-relative path) and the dedupe test FAILS (two entries).

- [ ] **Step 3: Dedupe the union**

In `localfs.py`, the zip branch currently reads:

```python
            _yml_paths = [x for x in zip_contents if x.endswith(".yml")]
            _yml_paths += glob(
                os.path.join(process_dir, "**", "*-prc.yml"), recursive=True
            )
```

Replace with:

```python
            _yml_paths = [x for x in zip_contents if x.endswith(".yml")]
            self._zip_members = set(_yml_paths)
            # The mirror still holds the processes of records synced before the
            # write moved into the RUNS_* tree. Union both, but never index the
            # same process twice: the in-zip copy wins.
            in_zip_uuids = {
                process_uuid_of(x) for x in _yml_paths if x.endswith("-prc.yml")
            }
            _yml_paths += [
                x
                for x in glob(
                    os.path.join(process_dir, "**", "*-prc.yml"), recursive=True
                )
                if process_uuid_of(x) not in in_zip_uuids
            ]
```

Add to the imports at the top of `localfs.py`:

```python
from helao.core.drivers.data.process_locator import process_uuid_of
```

In the non-zip branches, set `self._zip_members = set()` so the attribute always exists.

- [ ] **Step 4: Discriminate by origin, not by suffix**

In `get_yml`, replace:

```python
        if self.target.endswith(".zip") and not path.endswith("-prc.yml"):
```

with:

```python
        # Read from the zip when the path IS a zip member. The old test asked
        # whether the path ended in -prc.yml, using "is a process" as a proxy
        # for "is on disk" -- true only while processes were written outside
        # the tree that gets zipped, and false as soon as one is a zip member.
        if self.target.endswith(".zip") and path in self._zip_members:
```

- [ ] **Step 5: Run to verify both pass**

```bash
PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest \
  helao/core/tests/test_prc_readers.py -q
PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest \
  helao/core/tests/test_reflex_data_browser.py -q
```

Expected: all PASS. The second command is the loader's existing consumer and must not regress.

- [ ] **Step 6: Commit**

```bash
/home/dan/miniforge3/envs/helao/bin/black \
  helao/core/drivers/data/loaders/localfs.py helao/core/tests/test_prc_readers.py
git add helao/core/drivers/data/loaders/localfs.py helao/core/tests/test_prc_readers.py
git commit -m "fix(loaders): a process in a zip is read from the zip, and only once

Two bugs surface once a -prc.yml can be a zip member. The zip branch unions
the zip's ymls with a PROCESSES glob, so a record with both copies indexed
the same process twice. And get_yml decided zip-vs-disk by asking whether
the path ended in -prc.yml -- using 'is a process' as a proxy for 'is on
disk', which held only while processes were written outside the zipped
tree. Discriminates by zip membership and dedupes by process uuid."
```

---

## Task 8: `helao_data` and `processors` stop taking `glob(...)[0]`

**Files:**
- Modify: `helao/helpers/helao_data.py:132`
- Modify: `helao/helpers/processors.py:48-52`
- Test: `helao/core/tests/test_prc_readers.py`

**Interfaces:**
- Consumes: nothing.
- Produces: both select the record yml by suffix, so a colocated prc cannot be mistaken for one.

**Why:** `helao_data.py:132` is `self.ymlpath = glob(os.path.join(self.target, "*.yml"))[0]` — and the very next line derives `self.type` from that filename, so picking the prc mistypes the whole object. This is not a theoretical path: `HelaoData` is what the existing ECMS analysis scripts use to walk these sequences.

`processors.py:48` globs `exp_dir/*.yml` and takes `[0]`, and `exp_dir` is exactly where the prc now lands. The `{pidx}__...` filename sorts ahead of a timestamped `-exp.yml`, so `[0]` would pick the prc more often than not.

- [ ] **Step 1: Write the failing test**

Append to `helao/core/tests/test_prc_readers.py`:

```python
def test_helao_data_picks_the_record_yml_not_the_process(tmp_path):
    from helao.helpers.helao_data import HelaoData

    exp_dir = tmp_path / "RUNS_SYNCED" / "26.35" / "0828" / "seq" / "260828.120000__exp"
    exp_dir.mkdir(parents=True)
    (exp_dir / "260828.120000000000-exp.yml").write_text("experiment_name: SIM_exp\n")
    (exp_dir / PRC_A).write_text(BODY_A)  # sorts first under a bare glob
    hd = HelaoData(str(exp_dir))
    assert hd.ymlpath.endswith("-exp.yml")
    assert hd.type == "exp"


def test_processors_picks_the_experiment_yml_not_the_process(tmp_path):
    """HloPostProcessor is abstract, so subclass it to instantiate."""
    from helao.core.models.file import FileInfo
    from helao.helpers.premodels import Action
    from helao.helpers.processors import HloPostProcessor

    rel = Path("26.35") / "0828" / "seq" / "260828.120000__exp"
    exp_dir = tmp_path / "RUNS_ACTIVE" / rel
    act_dir = exp_dir / "0__0__SIM__do_thing"
    act_dir.mkdir(parents=True)
    (exp_dir / "260828.120000000000-exp.yml").write_text("experiment_name: SIM_exp\n")
    (exp_dir / PRC_A).write_text(BODY_A)  # sorts first under a bare glob
    (exp_dir.parent / "260828.115959000000-seq.yml").write_text(
        "sequence_name: SIM_seq\n"
    )

    class _Proc(HloPostProcessor):
        def process(self) -> list[FileInfo]:
            return []

    action = Action(
        action_name="do_thing",
        action_output_dir=str(rel / "0__0__SIM__do_thing"),
    )
    proc = _Proc(action, str(tmp_path / "RUNS_ACTIVE"))
    assert proc.exp_yml_path.endswith("-exp.yml")
    assert proc.seq_yml_path.endswith("-seq.yml")
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/core/tests/test_prc_readers.py -q -k "helao_data or processors"`

Expected: FAIL — both pick the prc.

- [ ] **Step 3: Fix `helao_data.py`**

Replace:

```python
                    self.ymlpath = glob(os.path.join(self.target, "*.yml"))[0]
```

with:

```python
                    # Record suffixes only: a colocated -prc.yml sorts ahead of
                    # a timestamped -exp.yml, and the next line derives
                    # self.type from whichever name is picked.
                    self.ymlpath = [
                        x
                        for x in sorted(glob(os.path.join(self.target, "*.yml")))
                        if x.endswith(("-seq.yml", "-exp.yml", "-act.yml"))
                    ][0]
```

- [ ] **Step 4: Fix `processors.py`**

Replace:

```python
        exp_yml_paths = glob(os.path.join(exp_dir, "*.yml"))
        self.exp_yml_path = exp_yml_paths[0] if exp_yml_paths else None
        seq_dir = os.path.dirname(exp_dir)
        seq_yml_paths = glob(os.path.join(seq_dir, "*.yml"))
        self.seq_yml_path = seq_yml_paths[0] if seq_yml_paths else None
```

with:

```python
        # Record suffixes only. exp_dir is where a -prc.yml now lands, and its
        # {pidx}__ filename sorts ahead of a timestamped -exp.yml.
        exp_yml_paths = [
            x
            for x in sorted(glob(os.path.join(exp_dir, "*.yml")))
            if x.endswith("-exp.yml")
        ]
        self.exp_yml_path = exp_yml_paths[0] if exp_yml_paths else None
        seq_dir = os.path.dirname(exp_dir)
        seq_yml_paths = [
            x
            for x in sorted(glob(os.path.join(seq_dir, "*.yml")))
            if x.endswith("-seq.yml")
        ]
        self.seq_yml_path = seq_yml_paths[0] if seq_yml_paths else None
```

- [ ] **Step 5: Run to verify they pass**

```bash
PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest \
  helao/core/tests/test_prc_readers.py -q
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
/home/dan/miniforge3/envs/helao/bin/black \
  helao/helpers/helao_data.py helao/helpers/processors.py \
  helao/core/tests/test_prc_readers.py
git add helao/helpers/helao_data.py helao/helpers/processors.py \
        helao/core/tests/test_prc_readers.py
git commit -m "fix(helpers): select the record yml by suffix, not by glob order

Both took glob(dir/*.yml)[0] on a directory that now also holds a
-prc.yml, whose {pidx}__ filename sorts ahead of a timestamped -exp.yml.
helao_data then derives self.type from whichever name it picked, so the
whole object was mistyped -- and HelaoData is what the existing ECMS
analysis scripts use to walk these sequences."
```

---

## Task 9: The smoke tree counts processes where they now live

**Files:**
- Modify: `helao/hexagon/tests/smoke/assert_smoke_tree.py:20-21`

**Interfaces:**
- Consumes: the write relocation from Task 5.
- Produces: the smoke assertion counts the four `-prc.yml` in the `RUNS_*` tree.

**Why:** it currently asserts `(root_p / "PROCESSES").rglob("*-prc.yml")` has four entries. After Task 5 that directory is empty and the assertion fails for the right reason but at the wrong place.

- [ ] **Step 1: Read the current assertion and its surroundings**

Run: `sed -n 1,40p helao/hexagon/tests/smoke/assert_smoke_tree.py`

Note which root the four processes are expected under and whether the tree is `RUNS_FINISHED` or `RUNS_SYNCED` at assertion time.

- [ ] **Step 2: Retarget the count**

Replace:

```python
    prcs = list((root_p / "PROCESSES").rglob("*-prc.yml"))
    check(len(prcs) == 4, f"PROCESSES has 4 -prc.yml (got {len(prcs)})")
```

with:

```python
    # Processes are written beside their -exp.yml inside the RUNS_* tree, so
    # they travel in the sequence zip. PROCESSES is legacy-read-only and must
    # gain nothing.
    prcs = [p for p in root_p.rglob("*-prc.yml") if "PROCESSES" not in p.parts]
    check(len(prcs) == 4, f"RUNS_* tree has 4 -prc.yml (got {len(prcs)})")
    stale = list((root_p / "PROCESSES").rglob("*-prc.yml"))
    check(not stale, f"PROCESSES must gain nothing (got {len(stale)})")
```

- [ ] **Step 3: Run the smoke assertion if the harness is available**

Run: `PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/hexagon/tests/smoke/ -q -k smoke_tree`

Expected: PASS, or a skip if the smoke tree fixture is not present in this environment. A skip is acceptable here — record it in the commit body rather than claiming a pass.

- [ ] **Step 4: Commit**

```bash
/home/dan/miniforge3/envs/helao/bin/black helao/hexagon/tests/smoke/assert_smoke_tree.py
git add helao/hexagon/tests/smoke/assert_smoke_tree.py
git commit -m "test(smoke): count processes in the RUNS_* tree, and none elsewhere

The four -prc.yml now sit beside their -exp.yml. Asserts both halves: they
appear in the RUNS_* tree, and PROCESSES gains nothing."
```

---

## Task 10: The private repair tools read both locations

**Files (all in the nested repository at `helao/deploy/priv/`):**
- Modify: `scripts/edax/retire_duplicate_records.py:193`
- Modify: `scripts/edax/rebuild_journal_zips.py:236`
- Modify: `scripts/edax/prune_process_sets.py`
- Modify: `scripts/edax/requeue_held_journal.py:132`
- Modify: `scripts/edax/reconvert_duplicates.py`
- Modify: `scripts/edax/rebuild_sequence_analyses.py:251`

**Interfaces:**
- Consumes: `find_process_ymls` from Task 6.
- Produces: each tool sees processes written after the cutover as well as before.

**Why:** every one of these globs `PROCESSES/<rel>/**/*-prc.yml`. They are not legacy-only tools; run against a record synced after the cutover they would find nothing and, in `rebuild_journal_zips.py`'s case, refuse with "no `-prc.yml` under `PROCESSES/<rel>`" (`:564`) — a false negative that reads as missing data.

**This is a separate git repository.** `cd helao/deploy/priv` and use its own git. It has its own branch and remote and is invisible to the parent repo's `git status`. Do not commit these files from the parent repo.

- [ ] **Step 1: Confirm the repo boundary before touching anything**

```bash
cd helao/deploy/priv && git status --short --branch && git log --oneline -3
```

Confirm this is the private repo and not the parent. Note the branch name; do not switch branches.

- [ ] **Step 2: Find every prc glob**

```bash
cd helao/deploy/priv && grep -rn 'prc\.yml' scripts/edax/*.py
```

Expect the six files above. Record each glob's exact line.

**Name collision, read this before importing.** `scripts/edax/prune_process_sets.py:125` already defines its own `process_uuid_of(name) -> Optional[UUID]`. The resolver from Task 6 exports a function of the same name returning `str`. Do **not** let the import shadow the local one — import the module or alias the import (`from helao.core.drivers.data.process_locator import find_process_ymls`, and nothing else), and leave every existing call to the local `process_uuid_of` untouched.

- [ ] **Step 3: Write a failing test for one tool**

The existing suite is `scripts/tests/test_prune_process_sets.py`, which already builds `PROCESSES/<rel>/<exp>/0__<uuid>__xrfs-prc.yml` trees (its lines 80 and 179) and asserts on `load_records(os.path.join(root, "PROCESSES", REL))` (its lines 217, 277, 309). Add a case that builds the **colocated** shape — the prc beside the `-exp.yml` under `RUNS_SYNCED/<rel>` — and assert `load_records` still returns it. Mirror the existing test's construction exactly rather than inventing a new fixture.

- [ ] **Step 4: Run to verify it fails**

```bash
cd helao/deploy/priv && PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async \
  /home/dan/miniforge3/envs/helao/bin/python -m pytest scripts/tests/test_prune_process_sets.py -q
```

Expected: the new case FAILS; the existing cases PASS.

- [ ] **Step 5: Route each tool through the resolver**

In each of the six files, replace the direct `PROCESSES` glob with a call to the shared resolver:

```python
from helao.core.drivers.data.process_locator import find_process_ymls
```

For a tool that walks a whole sequence rather than one experiment, iterate the experiment directories and concatenate:

```python
def _all_process_ymls(seq_dir: str, process_root: str) -> list:
    """Every -prc.yml under one sequence, from both locations.

    A tool pointed at a record synced after the write moved into the RUNS_*
    tree finds nothing in the PROCESSES mirror -- which reads as missing data
    rather than as a relocated file.
    """
    out = []
    for exp_dir in sorted(Path(seq_dir).glob("*")):
        if exp_dir.is_dir():
            out.extend(find_process_ymls(exp_dir, process_root=process_root))
    return out
```

Keep each tool's existing ordering and error messages; only the discovery changes.

- [ ] **Step 6: Run the private suite**

```bash
cd helao/deploy/priv && PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async \
  /home/dan/miniforge3/envs/helao/bin/python -m pytest scripts/tests/ -q
```

Expected: all PASS, including the pre-existing cases — the mirror path must keep working.

- [ ] **Step 7: Commit in the private repo**

```bash
cd helao/deploy/priv
/home/dan/miniforge3/envs/helao/bin/black scripts/edax/ scripts/tests/
git add scripts/edax/ scripts/tests/
git commit -m "fix(edax): find processes in both locations, not just PROCESSES

The -prc.yml write moved beside its -exp.yml in the parent repo, so these
tools glob a mirror that gains nothing for any record synced after the
cutover. rebuild_journal_zips would refuse with 'no -prc.yml under
PROCESSES/<rel>' -- a false negative reading as missing data. Routes all
six through the shared find_process_ymls resolver, which keeps the mirror
working for the existing archive."
```

---

## Task 11: Pin the round-trip and the three near-misses

**Files:**
- Test: `helao/core/tests/test_prc_colocation.py` (append)

**Interfaces:**
- Consumes: everything from Tasks 1–5.
- Produces: no production change. Four assertions the spec calls for that no earlier task covers.

**Why:** each of these is a property the design depends on but that nothing yet checks. Three are near-misses — cases that work today for a reason narrower than it looks, and would break silently under a plausible future edit.

- [ ] **Step 1: Pin the zip round-trip**

Append:

```python
def test_the_zip_carries_the_prc_and_reset_sync_restores_it(tmp_path):
    """The whole point: a sequence zip records its own process identity.

    zip_dir takes the sequence directory, so a colocated prc is included with
    no change to the zip code; reset_sync extracts everything but .prg/.lock,
    so it comes back on a reopen.
    """
    import zipfile

    from helao.helpers.file_utils import zip_dir

    seq_dir = tmp_path / "RUNS_SYNCED" / "26.35" / "0828" / "260828.115959__seq"
    exp_dir = seq_dir / "260828.120000__exp"
    exp_dir.mkdir(parents=True)
    (seq_dir / "260828.115959000000-seq.yml").write_text("sequence_name: SIM_seq\n")
    (exp_dir / "260828.120000000000-exp.yml").write_text("experiment_name: SIM_exp\n")
    prc_name = "0__06a5a2d6-b26c-7019-8000-4c2d967e5df1__SIM_exp-prc.yml"
    (exp_dir / prc_name).write_text(
        "process_uuid: 06a5a2d6-b26c-7019-8000-4c2d967e5df1\n"
    )
    (exp_dir / "260828.120000000000-exp.prg").write_text("{}\n")

    zpath = seq_dir.parent / "260828.115959__seq.zip"
    zip_dir(seq_dir, zpath)
    members = zipfile.ZipFile(zpath).namelist()
    assert any(m.endswith(prc_name) for m in members), (
        f"the zip must carry the process artifact; members={members}"
    )
```

- [ ] **Step 2: Run it**

Run: `PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/core/tests/test_prc_colocation.py -q -k zip_carries`

Expected: PASS with no production change — `zip_dir` already takes the whole directory. If it fails, read `helao/helpers/file_utils.py:zip_dir` and adapt the call; do not weaken the assertion.

- [ ] **Step 3: Pin that the S3 key did not move**

Append:

```python
def test_the_process_s3_key_is_unchanged(tmp_path):
    """Relocating the local write must not touch the bucket layout.

    S3 destinations are uuid-keyed, not path-keyed, so nothing about where the
    yml lands on disk may reach the key.
    """
    from helao.core.drivers.data.sync_driver import SyncDriver
    from helao.core.models.run_dir import RunDir
    from helao.hexagon.tests.sync_fixtures import (
        make_action,
        make_exp_tree,
        make_sync_driver,
        mk_uuid,
    )

    driver = make_sync_driver(tmp_path, SyncDriver)
    seen: list[str] = []

    async def _record(msg, target, compress=False):
        seen.append(target)
        return True

    driver.to_s3 = _record
    exp_yml = make_exp_tree(
        tmp_path, RunDir.FINISHED.value, mk_uuid(2001), process_order_groups={0: [0]}
    )
    make_action(exp_yml, 0, process_finish=True)
    asyncio.run(driver.sync_process(driver.get_progress(exp_yml), force=True))

    prc_keys = [k for k in seen if k.startswith("process/")]
    assert prc_keys, f"expected a process/ key, saw {seen}"
    assert all(k.startswith("process/") and k.endswith(".json") for k in prc_keys)
```

- [ ] **Step 4: Pin the depth-vs-suffix hazard**

Append:

```python
def test_list_pending_exps_does_not_return_a_colocated_prc(tmp_path):
    """A colocated prc sits at exactly the depth list_pending_exps walks.

    week/date/seq/exp -- the same four levels. It is excluded by the -exp.yml
    suffix and by nothing else, so loosening that pattern to *.yml would feed
    process artifacts straight into the sync queue. This pins the suffix.
    """
    from helao.core.drivers.data.sync_driver import SyncDriver
    from helao.hexagon.tests.sync_fixtures import make_sync_driver

    driver = make_sync_driver(tmp_path, SyncDriver)
    exp_dir = tmp_path / "RUNS_FINISHED" / "26.35" / "0828" / "seqdir" / "expdir"
    exp_dir.mkdir(parents=True)
    (exp_dir / "260828.120000000000-exp.yml").write_text("experiment_name: SIM_exp\n")
    (exp_dir / "0__06a5a2d6-b26c-7019-8000-4c2d967e5df1__SIM_exp-prc.yml").write_text(
        "process_uuid: 06a5a2d6-b26c-7019-8000-4c2d967e5df1\n"
    )
    pending = driver.list_pending_exps()
    assert all(p.endswith("-exp.yml") for p in pending), pending
    assert not any("-prc.yml" in p for p in pending), pending
```

- [ ] **Step 5: Pin the `/finish_yml` route end to end**

Append:

```python
def test_finish_yml_route_drops_a_process_path(tmp_path):
    """The route that makes the guard necessary.

    /finish_yml assigns rank -1 to an unrecognised suffix, and -1 is above
    enqueue_yml's rank_limit of -5, so a prc path reaches the queue rather
    than being dropped by the rank floor. Exercises the same rank the route
    would pass.
    """
    exp_dir = _tree(tmp_path)
    prc = exp_dir / "0__06a5a2d6-b26c-7019-8000-4c2d967e5df1__SIM_exp-prc.yml"
    prc.write_text("process_uuid: 06a5a2d6-b26c-7019-8000-4c2d967e5df1\n")
    syncer = _StubSyncer()
    asyncio.run(syncer.enqueue_yml(str(prc), rank=-1))  # the route's rank
    assert syncer.task_queue.items == []
    assert syncer.task_set == set()
```

- [ ] **Step 6: Run all four**

```bash
PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest \
  helao/core/tests/test_prc_colocation.py -q
```

Expected: every test in the file PASSES. Any failure here is a real gap in Tasks 1–5, not a test to relax.

- [ ] **Step 7: Commit**

```bash
/home/dan/miniforge3/envs/helao/bin/black helao/core/tests/test_prc_colocation.py
git add helao/core/tests/test_prc_colocation.py
git commit -m "test(sync): pin the round-trip and three near-misses

The zip carrying its own process identity is the point of the change and
nothing asserted it. The other three are cases that hold today for reasons
narrower than they look: the S3 key must stay uuid-keyed while the local
path moves; list_pending_exps walks exactly the depth a colocated prc sits
at and is saved only by its -exp.yml suffix; and /finish_yml ranks an
unknown suffix -1, above rank_limit, which is the route that makes the
guard necessary in the first place."
```

---

## Final verification

- [ ] **Run every affected suite**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest \
  helao/core/tests/test_prc_colocation.py \
  helao/core/tests/test_process_locator.py \
  helao/core/tests/test_prc_readers.py \
  harness/tests/test_parity_prc_location.py \
  helao/hexagon/tests/test_native_sync_pins.py \
  helao/hexagon/tests/test_native_sync_driver.py \
  helao/hexagon/tests/test_native_sync_adapter.py \
  helao/core/tests/test_sync_staging_files.py \
  helao/core/tests/test_reflex_data_browser.py -q
PYTHONPATH=$PWD timeout 600 /home/dan/miniforge3/envs/helao/bin/python -m pytest \
  helao/hexagon/tests/test_native_sync_parity.py -q
```

Expected: all PASS. The parity gate must **not** report "skipped" — `test_native_sync_parity.py` says so itself: "T12 verifies this module ran (0 skipped) — a silent skip guts the gate."

- [ ] **Confirm the twins never drifted**

```bash
PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -c "
from helao.hexagon.tests.sync_fixtures import assert_verbatim_region, assert_region_holds_no_imports
assert_verbatim_region(); assert_region_holds_no_imports(); print('twins byte-identical, region import-free')
"
```

- [ ] **Confirm nothing new reaches `PROCESSES`, by inspection**

```bash
grep -n "process_root" helao/core/drivers/data/sync_driver.py \
                       helao/hexagon/adapters/native/sync_driver.py
```

Expected: no remaining **write** through `process_root` in either file. `helao/helpers/helao_dirs.py` still creates the directory, which is correct.

- [ ] **Run the broad sweep**

```bash
/home/dan/miniforge3/envs/helao/bin/python run_tests.py --filter sync
/home/dan/miniforge3/envs/helao/bin/python run_unit_tests.py
```

Report any `FAIL`. An `ENV` result is a missing third-party package and is not a failure.
