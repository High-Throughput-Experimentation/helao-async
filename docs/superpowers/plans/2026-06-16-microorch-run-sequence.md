# MicroOrch run_sequence + yml persistence + loader wrap + zip Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `MicroOrch` a `run_sequence` method, full-fidelity Experiment/Sequence yml persistence to `RUNS_FINISHED`, loader-backed return values, run tracking, an artifact zipper, and make `LocalLoader` read MicroOrch zips.

**Architecture:** `MicroOrch` (`helao/core/runners/micro_orch.py`) is a standalone RPC orchestrator that does not inherit `Base`. We reproduce `Base`'s atomic yml writers locally, rooted at `RUNS_FINISHED` (or `RUNS_DIAG` for manual runs). Experiment/sequence identity is stamped *before* the experiment function runs so `ActionPlanMaker` propagates it into each `Action` automatically (matching `Orch`). Finished artifacts are read back via a pluggable loader (default `LocalLoader`, local filesystem). Every `run_*` call is tracked so all artifacts can be zipped relative to `RUNS_FINISHED`, and `LocalLoader`'s zip parser is generalized to read those multi-tree archives.

**Tech Stack:** Python 3.12, asyncio, `aiofiles`, pydantic premodels (`helao/helpers/premodels.py`), `yml_tools.yml_dumps`, ZeroMQ RPC (`helao/core/rpc.py`), pandas (`LocalLoader`). Tests are standalone scripts using `helao.core.tests._test_utils.TestReporter` (no pytest).

---

## Conventions for this plan

- **Conda env:** all commands run inside the `helao` conda env with `PYTHONPATH` at the repo root (configured by `setup_env.sh`).
- **Test entry point:** the existing module `helao/core/tests/unit_test_micro_orch.py` exposes `micro_orch_unit_test() -> bool`. We extend it. It is already registered in `run_unit_tests.py`.
- **Run the MicroOrch test module:**
  ```bash
  python -c "import sys; from helao.core.tests.unit_test_micro_orch import micro_orch_unit_test; sys.exit(0 if micro_orch_unit_test() else 1)"
  ```
  Exit code `0` = all checks passed, `1` = at least one failed (the per-check `failed:` lines name which).
- **Run the full suite (final gate):** `python run_unit_tests.py`
- **Test style:** `reporter.section("label")` then `reporter.check("description", lambda: <bool>)`. A check that raises counts as a failure. Return `reporter.success()`.

## File structure

- **Modify** `helao/core/runners/micro_orch.py` — all `MicroOrch` behavior (Tasks 1–7).
- **Modify** `helao/core/drivers/data/loaders/localfs.py` — zip parser generalization (Task 8).
- **Modify** `helao/core/tests/unit_test_micro_orch.py` — new test sections + shared fake-server/temp-root helpers (every task).

## Imports needed in `micro_orch.py`

The module currently imports (top of file):
```python
import asyncio
import inspect
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from uuid import UUID
import zmq
from helao.core.models.action_start_condition import ActionStartCondition
from helao.core.models.hlostatus import HloStatus
from helao.core.models.server import ActionServerModel
from helao.core.rpc import RPCClient, RPCDispatcher, RPCError, derive_rpc_port
from helao.helpers import helao_logging as logging
from helao.helpers.time_utils import gen_uuid
from helao.helpers.premodels import Action, Experiment
```
Across the tasks below we add these (do each addition in the task that first needs it, but they are listed here so the final state is unambiguous):
```python
import os
import glob as glob_module
import zipfile
from copy import deepcopy
from uuid import uuid1
import aiofiles
from helao.helpers.premodels import Sequence
from helao.core.models.experiment import ShortExperimentModel
from helao.helpers.yml_tools import yml_dumps
from helao.helpers.time_utils import set_time
from helao.core.drivers.data.loaders.localfs import (
    LocalLoader, HelaoAction, HelaoExperiment, HelaoSequence,
)
```

---

## Task 1: yml writers (direct to RUNS_FINISHED / RUNS_DIAG)

Reproduce `Base`'s atomic meta writers on `MicroOrch`, writing straight to the finished tree.

**Files:**
- Modify: `helao/core/runners/micro_orch.py`
- Test: `helao/core/tests/unit_test_micro_orch.py`

- [ ] **Step 1: Add the temp-root + builder helpers to the test module**

At the top of `unit_test_micro_orch.py`, after the existing imports, add:

```python
import os
import tempfile
import shutil
from helao.helpers.premodels import Experiment, Sequence
from helao.core.runners.micro_orch import MicroOrch as _MO  # alias to reach new methods
```

Then add these helpers (module level):

```python
def _make_orch(root: str, world_servers: dict = None) -> MicroOrch:
    """Build a MicroOrch with a filesystem root but without starting it."""
    return MicroOrch(
        server_key="micro",
        host="127.0.0.1",
        port=_free_port(),
        world_cfg={"root": root, "servers": world_servers or {}},
        default_timeout=3.0,
        finished_timeout=5.0,
        poll_interval=0.05,
    )


def _build_experiment(name: str = "exp_demo") -> Experiment:
    """A minimal Experiment with a manual sequence context, fully stamped."""
    exp = Experiment(experiment_name=name)
    exp.manual_action = True
    exp.access = "manual"
    exp.sequence_name = f"seq--{name}"
    exp.sequence_label = "manual"
    exp.init_seq(time_offset=0)
    exp.init_exp(time_offset=0)
    return exp
```

- [ ] **Step 2: Add a failing test section for the yml writers**

Add this function to `unit_test_micro_orch.py`:

```python
async def _drive_yml_writers(reporter: TestReporter) -> None:
    """_write_exp / _write_seq land yml under RUNS_DIAG for a manual experiment."""
    root = tempfile.mkdtemp(prefix="micro_yml_")
    try:
        orch = _make_orch(root)
        exp = _build_experiment("yml_exp")

        exp_file = await orch._write_exp(exp)
        reporter.check(
            "_write_exp returns an existing .yml path",
            lambda: isinstance(exp_file, str) and os.path.isfile(exp_file),
        )
        reporter.check(
            "exp yml is under RUNS_DIAG (manual_action)",
            lambda: os.sep + "RUNS_DIAG" + os.sep in exp_file,
        )
        from helao.helpers.yml_tools import yml_load
        reporter.check(
            "exp yml has file_type=experiment and matching uuid",
            lambda: (
                yml_load(open(exp_file).read())["file_type"] == "experiment"
                and str(yml_load(open(exp_file).read())["experiment_uuid"])
                == str(exp.experiment_uuid)
            ),
        )

        seq = Sequence(sequence_name="yml_seq", sequence_label="manual")
        seq.manual_action = True
        seq.init_seq(time_offset=0)
        seq_file = await orch._write_seq(seq)
        reporter.check(
            "_write_seq returns an existing .yml path under RUNS_DIAG",
            lambda: os.path.isfile(seq_file)
            and os.sep + "RUNS_DIAG" + os.sep in seq_file,
        )
        reporter.check(
            "seq yml has file_type=sequence",
            lambda: yml_load(open(seq_file).read())["file_type"] == "sequence",
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)
```

And invoke it inside `micro_orch_unit_test()`, right before `return reporter.success()`:

```python
        reporter.section("MicroOrch yml writers")
        asyncio.run(_drive_yml_writers(reporter))
```

- [ ] **Step 3: Run the test to verify it fails**

Run:
```bash
python -c "import sys; from helao.core.tests.unit_test_micro_orch import micro_orch_unit_test; sys.exit(0 if micro_orch_unit_test() else 1)"
```
Expected: FAIL — `_make_orch` passes `finished_timeout`/`poll_interval` kwargs that `MicroOrch.__init__` does not yet accept (TypeError), and `_write_exp`/`_write_seq` do not exist.

- [ ] **Step 4: Add the new `__init__` kwargs and the writer methods**

In `micro_orch.py`, add the imports `os`, `from uuid import uuid1`, `import aiofiles`, `from helao.helpers.premodels import Sequence`, `from helao.helpers.yml_tools import yml_dumps`.

Extend `MicroOrch.__init__` signature and body. Change the signature to:

```python
    def __init__(
        self,
        server_key: str,
        host: str,
        port: int,
        world_cfg: Optional[dict] = None,
        default_timeout: float = 5.0,
        finished_timeout: float = 60.0,
        poll_interval: float = 0.5,
        loader_factory: Optional[Callable[[str], Any]] = None,
    ) -> None:
```

At the end of `__init__` (after `self.last_action_uuid = None`), add:

```python
        # Artifact read-back configuration.
        self.finished_timeout = finished_timeout
        self.poll_interval = poll_interval
        # Default to the local-filesystem loader; importing lazily avoids a
        # hard pandas import at module load for callers that never read back.
        if loader_factory is None:
            from helao.core.drivers.data.loaders.localfs import LocalLoader
            loader_factory = LocalLoader
        self.loader_factory = loader_factory
        # Run tracking (Task 4 populates this).
        self.runs: List[dict] = []
```

Add the writer methods (place them after the `run_experiment` section, in a new "persistence" block):

```python
    # ------------------------------------------------------------------
    # artifact persistence (mirrors Base.write_exp / write_seq)
    # ------------------------------------------------------------------

    def _finished_root(self, manual: bool = False) -> str:
        """Return ``<root>/RUNS_FINISHED`` (or ``RUNS_DIAG`` for manual runs).

        Raises:
            RuntimeError: If ``world_cfg`` has no ``root`` key.
        """
        root = self.world_cfg.get("root")
        if not root:
            raise RuntimeError(
                "world_cfg['root'] is required to persist or read back artifacts"
            )
        return os.path.join(root, "RUNS_DIAG" if manual else "RUNS_FINISHED")

    async def _write_meta_atomic(self, output_file: str, output_str: str) -> None:
        """Atomically write ``output_str`` to ``output_file`` (temp + os.replace)."""
        if not output_str.endswith("\n"):
            output_str += "\n"
        output_path = os.path.dirname(output_file)
        os.makedirs(output_path, exist_ok=True)
        tmp_file = os.path.join(
            output_path, f".{os.path.basename(output_file)}.{uuid1().hex}.tmp"
        )
        async with aiofiles.open(tmp_file, mode="w") as f:
            await f.write(output_str)
        os.replace(tmp_file, output_file)

    async def _write_exp(self, experiment: Experiment) -> str:
        """Write ``<finished_root>/<exp_dir>/<ts>-exp.yml`` and return its path."""
        exp_dict = experiment.get_exp().clean_dict()
        root = self._finished_root(manual=bool(experiment.manual_action))
        output_path = os.path.join(root, experiment.get_experiment_dir())
        output_file = os.path.join(
            output_path,
            f"{experiment.experiment_timestamp.strftime('%y%m%d.%H%M%S%f')}-exp.yml",
        )
        output_dict = {"file_type": "experiment"}
        output_dict.update(exp_dict)
        await self._write_meta_atomic(output_file, yml_dumps(output_dict))
        return output_file

    async def _write_seq(self, sequence: Sequence) -> str:
        """Write ``<finished_root>/<seq_dir>/<ts>-seq.yml`` and return its path."""
        seq_dict = sequence.get_seq().clean_dict()
        root = self._finished_root(manual=bool(sequence.manual_action))
        output_path = os.path.join(root, sequence.get_sequence_dir())
        output_file = os.path.join(
            output_path,
            f"{sequence.sequence_timestamp.strftime('%y%m%d.%H%M%S%f')}-seq.yml",
        )
        output_dict = {"file_type": "sequence"}
        output_dict.update(seq_dict)
        await self._write_meta_atomic(output_file, yml_dumps(output_dict))
        return output_file
```

- [ ] **Step 5: Run the test to verify it passes**

Run:
```bash
python -c "import sys; from helao.core.tests.unit_test_micro_orch import micro_orch_unit_test; sys.exit(0 if micro_orch_unit_test() else 1)"
```
Expected: PASS (all checks, including the existing `run_action` ones and the new "MicroOrch yml writers" section).

- [ ] **Step 6: Commit**

```bash
git add helao/core/runners/micro_orch.py helao/core/tests/unit_test_micro_orch.py
git commit -m "feat(micro_orch): atomic exp/seq yml writers to RUNS_FINISHED"
```

---

## Task 2: experiment identity staging (`_stage_experiment`)

Stamp the experiment (and its sequence context) so that, when called *before* the experiment function, `ActionPlanMaker` propagates identity into each action — and the on-disk exp dir nests under the seq dir.

**Files:**
- Modify: `helao/core/runners/micro_orch.py`
- Test: `helao/core/tests/unit_test_micro_orch.py`

- [ ] **Step 1: Add a failing test section**

Add to `unit_test_micro_orch.py`:

```python
def _check_stage_experiment(reporter: TestReporter) -> None:
    """_stage_experiment synthesizes a manual sequence and nests the exp dir."""
    root = tempfile.mkdtemp(prefix="micro_stage_")
    try:
        orch = _make_orch(root)

        # standalone: no sequence supplied -> manual sequence synthesized
        exp = Experiment(experiment_name="stage_exp")
        orch._stage_experiment(exp, order=0, sequence=None)
        reporter.check(
            "standalone experiment is flagged manual",
            lambda: exp.manual_action is True and exp.access == "manual",
        )
        reporter.check(
            "experiment has a sequence_output_dir",
            lambda: bool(exp.sequence_output_dir),
        )
        reporter.check(
            "experiment_output_dir nests under sequence_output_dir",
            lambda: exp.get_experiment_dir().startswith(str(exp.sequence_output_dir)),
        )

        # with a supplied sequence -> identity copied, not manual
        seq = Sequence(sequence_name="parent_seq", sequence_label="lbl")
        seq.init_seq(time_offset=0)
        exp2 = Experiment(experiment_name="child_exp")
        orch._stage_experiment(exp2, order=0, sequence=seq)
        reporter.check(
            "child experiment inherits parent sequence_uuid",
            lambda: str(exp2.sequence_uuid) == str(seq.sequence_uuid),
        )
        reporter.check(
            "child experiment inherits parent sequence_output_dir",
            lambda: exp2.sequence_output_dir == seq.sequence_output_dir,
        )
        reporter.check(
            "child experiment is not manual",
            lambda: not exp2.manual_action,
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)
```

Invoke inside `micro_orch_unit_test()` before `return reporter.success()`:

```python
        reporter.section("MicroOrch _stage_experiment")
        _check_stage_experiment(reporter)
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
python -c "import sys; from helao.core.tests.unit_test_micro_orch import micro_orch_unit_test; sys.exit(0 if micro_orch_unit_test() else 1)"
```
Expected: FAIL — `_stage_experiment` does not exist (AttributeError).

- [ ] **Step 3: Implement `_stage_experiment`**

Add `from copy import deepcopy` and `from helao.helpers.time_utils import set_time` to `micro_orch.py` imports.

Add this method next to `_stage_action` in `micro_orch.py`:

```python
    # Sequence-identity fields copied parent->child when an experiment runs
    # inside a known sequence context.
    _SEQ_IDENTITY_FIELDS = (
        "sequence_uuid",
        "sequence_timestamp",
        "sequence_name",
        "sequence_label",
        "sequence_output_dir",
        "sequence_params",
        "sequence_status",
        "manual_action",
        "access",
    )

    def _stage_experiment(
        self,
        exp: Experiment,
        order: int,
        sequence: Optional["Sequence"] = None,
    ) -> None:
        """Stamp experiment + sequence identity before the experiment function runs.

        When ``sequence`` is given, the experiment inherits that sequence's
        identity. Otherwise the experiment is promoted to a manual run with a
        synthetic sequence (mirrors ``Action.init_act``'s manual promotion).
        ``init_exp`` then assigns the experiment timestamp/uuid/status and the
        nested ``experiment_output_dir``. Must run BEFORE the experiment
        function so ``ActionPlanMaker`` copies the stamped identity into each
        planned action.
        """
        exp.orch_key = self.server_key
        exp.orch_host = self.host
        exp.orch_port = self.port
        if sequence is not None:
            for field in self._SEQ_IDENTITY_FIELDS:
                setattr(exp, field, deepcopy(getattr(sequence, field)))
        elif exp.sequence_timestamp is None:
            exp.manual_action = True
            exp.access = "manual"
            exp.sequence_name = f"seq--{exp.experiment_name}"
            exp.sequence_label = "manual"
            exp.init_seq(time_offset=0)
        exp.init_exp(time_offset=0)
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
python -c "import sys; from helao.core.tests.unit_test_micro_orch import micro_orch_unit_test; sys.exit(0 if micro_orch_unit_test() else 1)"
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add helao/core/runners/micro_orch.py helao/core/tests/unit_test_micro_orch.py
git commit -m "feat(micro_orch): _stage_experiment stamps seq/exp identity"
```

---

## Task 3: loader read-back helpers (`_await_finished`, `_load_finished`)

Wait for a finished yml to appear (in `RUNS_FINISHED` or `RUNS_DIAG`), then load it through the pluggable loader.

**Files:**
- Modify: `helao/core/runners/micro_orch.py`
- Test: `helao/core/tests/unit_test_micro_orch.py`

- [ ] **Step 1: Add a failing test section**

Add to `unit_test_micro_orch.py`:

```python
async def _drive_load_finished(reporter: TestReporter) -> None:
    """_await_finished finds a written yml; _load_finished wraps it."""
    root = tempfile.mkdtemp(prefix="micro_load_")
    try:
        orch = _make_orch(root)
        exp = _build_experiment("load_exp")  # manual -> RUNS_DIAG
        await orch._write_exp(exp)

        rel_dir = exp.get_experiment_dir()
        found = await orch._await_finished(rel_dir, "exp")
        reporter.check(
            "_await_finished locates the manual exp yml in RUNS_DIAG",
            lambda: os.path.isfile(found)
            and os.sep + "RUNS_DIAG" + os.sep in found,
        )

        loaded = await orch._load_finished(rel_dir, "exp")
        from helao.core.drivers.data.loaders.localfs import HelaoExperiment
        reporter.check(
            "_load_finished returns a HelaoExperiment",
            lambda: isinstance(loaded, HelaoExperiment),
        )
        reporter.check(
            "loaded experiment_uuid matches",
            lambda: str(loaded.experiment_uuid) == str(exp.experiment_uuid),
        )

        # timeout path: a relative dir that never appears
        async def _expect_timeout():
            try:
                await orch._await_finished("99.99/9999/000000__nope__none", "exp")
                return False
            except TimeoutError:
                return True

        timed_out = await _expect_timeout()
        reporter.check(
            "_await_finished raises TimeoutError when nothing appears",
            lambda: timed_out,
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)
```

Invoke inside `micro_orch_unit_test()` before `return reporter.success()`:

```python
        reporter.section("MicroOrch loader read-back")
        asyncio.run(_drive_load_finished(reporter))
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
python -c "import sys; from helao.core.tests.unit_test_micro_orch import micro_orch_unit_test; sys.exit(0 if micro_orch_unit_test() else 1)"
```
Expected: FAIL — `_await_finished` / `_load_finished` do not exist.

- [ ] **Step 3: Implement the read-back helpers**

Add `import glob as glob_module` to `micro_orch.py` imports.

Add this block to `micro_orch.py` (new "read-back" section):

```python
    # ------------------------------------------------------------------
    # finished-artifact read-back
    # ------------------------------------------------------------------

    # suffix -> loader getter name
    _LOADER_GETTERS = {"act": "get_act", "exp": "get_exp", "seq": "get_seq"}

    def _candidate_yml(self, rel_dir: str, suffix: str) -> Optional[str]:
        """Return the first matching ``*-<suffix>.yml`` under FINISHED or DIAG."""
        root = self.world_cfg.get("root")
        if not root:
            raise RuntimeError("world_cfg['root'] is required to read back artifacts")
        for state in ("RUNS_FINISHED", "RUNS_DIAG"):
            pattern = os.path.join(root, state, rel_dir, f"*-{suffix}.yml")
            matches = sorted(glob_module.glob(pattern))
            if matches:
                return matches[0]
        return None

    async def _await_finished(self, rel_dir: str, suffix: str) -> str:
        """Poll until ``*-<suffix>.yml`` exists under ``rel_dir`` in FINISHED/DIAG.

        Raises:
            TimeoutError: If nothing appears within ``self.finished_timeout``.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.finished_timeout
        while True:
            found = self._candidate_yml(rel_dir, suffix)
            if found is not None:
                return found
            if loop.time() >= deadline:
                raise TimeoutError(
                    f"timed out after {self.finished_timeout}s waiting for "
                    f"*-{suffix}.yml under {rel_dir!r} in RUNS_FINISHED/RUNS_DIAG"
                )
            await asyncio.sleep(self.poll_interval)

    async def _load_finished(self, rel_dir: str, suffix: str) -> Any:
        """Wait for the finished yml then return the loader-wrapped object."""
        yml_path = await self._await_finished(rel_dir, suffix)
        loader = self.loader_factory(yml_path)
        getter = getattr(loader, self._LOADER_GETTERS[suffix])
        return getter(path=yml_path)
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
python -c "import sys; from helao.core.tests.unit_test_micro_orch import micro_orch_unit_test; sys.exit(0 if micro_orch_unit_test() else 1)"
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add helao/core/runners/micro_orch.py helao/core/tests/unit_test_micro_orch.py
git commit -m "feat(micro_orch): _await_finished/_load_finished read-back helpers"
```

---

## Task 4: run tracking (`_track_run`)

Record each finished artifact so it can be zipped later.

**Files:**
- Modify: `helao/core/runners/micro_orch.py`
- Test: `helao/core/tests/unit_test_micro_orch.py`

- [ ] **Step 1: Add a failing test section**

Add to `unit_test_micro_orch.py`:

```python
def _check_track_run(reporter: TestReporter) -> None:
    """_track_run appends a normalized RunRecord derived from a yml path."""
    root = tempfile.mkdtemp(prefix="micro_track_")
    try:
        orch = _make_orch(root)
        yml_path = os.path.join(
            root, "RUNS_DIAG", "26.24", "0616",
            "120000__seq--x__manual", "260616.120001000000__exp--x",
            "260616.120001000000-exp.yml",
        )
        os.makedirs(os.path.dirname(yml_path), exist_ok=True)
        open(yml_path, "w").write("file_type: experiment\n")

        rec = orch._track_run("experiment", "uuid-1", "exp--x", yml_path)
        reporter.check("_track_run returns the record", lambda: rec in orch.runs)
        reporter.check(
            "record state derived from path",
            lambda: rec["state"] == "RUNS_DIAG",
        )
        reporter.check(
            "record rel_dir is relative to the state root",
            lambda: rec["rel_dir"]
            == os.path.join(
                "26.24", "0616", "120000__seq--x__manual",
                "260616.120001000000__exp--x",
            ),
        )
        reporter.check("runs list has one entry", lambda: len(orch.runs) == 1)
    finally:
        shutil.rmtree(root, ignore_errors=True)
```

Invoke inside `micro_orch_unit_test()` before `return reporter.success()`:

```python
        reporter.section("MicroOrch run tracking")
        _check_track_run(reporter)
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
python -c "import sys; from helao.core.tests.unit_test_micro_orch import micro_orch_unit_test; sys.exit(0 if micro_orch_unit_test() else 1)"
```
Expected: FAIL — `_track_run` does not exist.

- [ ] **Step 3: Implement `_track_run`**

Add to `micro_orch.py` (new "run tracking" section):

```python
    # ------------------------------------------------------------------
    # run tracking
    # ------------------------------------------------------------------

    def _track_run(
        self, run_type: str, uuid: Any, name: str, yml_path: str
    ) -> dict:
        """Append a RunRecord for a finished artifact and return it.

        ``state`` (RUNS_FINISHED/RUNS_DIAG) and ``rel_dir`` (the artifact's
        directory relative to that state root) are derived from ``yml_path``.
        """
        norm = os.path.normpath(yml_path)
        parts = norm.split(os.sep)
        state = "RUNS_FINISHED"
        for candidate in ("RUNS_FINISHED", "RUNS_DIAG"):
            if candidate in parts:
                state = candidate
                break
        state_idx = parts.index(state)
        # rel_dir = directory of the yml, relative to <root>/<state>
        rel_dir = os.path.join(*parts[state_idx + 1 : -1]) if len(
            parts
        ) - 1 > state_idx + 1 else ""
        record = {
            "type": run_type,
            "uuid": uuid,
            "name": name,
            "state": state,
            "rel_dir": rel_dir,
            "yml_path": norm,
        }
        self.runs.append(record)
        return record
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
python -c "import sys; from helao.core.tests.unit_test_micro_orch import micro_orch_unit_test; sys.exit(0 if micro_orch_unit_test() else 1)"
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add helao/core/runners/micro_orch.py helao/core/tests/unit_test_micro_orch.py
git commit -m "feat(micro_orch): _track_run records finished artifacts"
```

---

## Task 5: wire run_action + run_experiment (parity, persistence, tracking, wrap)

Update the two existing run methods to stamp identity before unpacking, build full-fidelity yml, persist, track, and return loader-wrapped objects. This task introduces a data-writing fake action server so the read-back path is exercised end-to-end.

**Files:**
- Modify: `helao/core/runners/micro_orch.py`
- Test: `helao/core/tests/unit_test_micro_orch.py`

- [ ] **Step 1: Add the data-writing fake action server to the test module**

Add to `unit_test_micro_orch.py`:

```python
from datetime import datetime as _dt
from helao.helpers.yml_tools import yml_dumps as _yml_dumps


class _FakeDataActionServer:
    """Fake action server that writes a finished act.yml + .hlo to disk.

    Mirrors what a real action server does on finish: writes its action meta
    yml and one HLO data file into ``<root>/<state>/<action_output_dir>/`` and
    returns a terminal dump (so MicroOrch resolves off the reply).
    """

    def __init__(self, server_key: str, action_name: str, root: str):
        self.server_key = server_key
        self.action_name = action_name
        self.root = root
        self.dispatcher = RPCDispatcher(server_key)
        self.action_calls = []
        self.dispatcher.register(f"{server_key}/{action_name}", self._run_action)
        self.dispatcher.register("attach_client", self._noop)
        self.dispatcher.register("detach_client", self._noop)

    async def _noop(self, **kwargs) -> bool:
        return True

    async def _run_action(self, action: dict = None, **kwargs):
        action_dict = action or {}
        self.action_calls.append(deepcopy(action_dict))
        action_dict["action_status"] = [HloStatus.finished.value]
        # produce a sample_out so the experiment aggregates something
        action_dict.setdefault("samples_out", [])
        # write artifacts to disk like a real server would
        state = "RUNS_DIAG" if action_dict.get("manual_action") else "RUNS_FINISHED"
        out_dir = action_dict.get("action_output_dir")
        if out_dir:
            abs_dir = os.path.join(self.root, state, out_dir)
            os.makedirs(abs_dir, exist_ok=True)
            ts = _dt.now().strftime("%y%m%d.%H%M%S%f")
            hlo_name = f"{ts}__data.hlo"
            # the .hlo file (yml header + %% + one json line)
            with open(os.path.join(abs_dir, hlo_name), "w") as f:
                f.write("epoch_ns: 0\n%%\n")
                f.write('{"t": [0.0], "v": [1.0]}\n')
            # the act.yml, referencing the hlo file
            act_meta = {"file_type": "action"}
            act_meta.update(action_dict)
            act_meta["files"] = [
                {
                    "file_name": hlo_name,
                    "file_type": "helao__file",
                    "data_keys": ["t", "v"],
                    "action_uuid": action_dict.get("action_uuid"),
                }
            ]
            with open(os.path.join(abs_dir, f"{ts}-act.yml"), "w") as f:
                f.write(_yml_dumps(act_meta))
        return action_dict
```

- [ ] **Step 2: Add a failing end-to-end test section for run_experiment + run_action**

Add to `unit_test_micro_orch.py`:

```python
def _demo_exp_func(experiment, wait_time: float = 0.0):
    """Experiment function: plan two actions on the FAKE server via ActionPlanMaker."""
    from helao.helpers.premodels import ActionPlanMaker
    apm = ActionPlanMaker()
    apm.add("FAKE", "ping", {"wait_time": wait_time})
    apm.add("FAKE", "ping", {"wait_time": wait_time})
    return apm.planned_actions


async def _drive_run_experiment(reporter: TestReporter) -> None:
    root = tempfile.mkdtemp(prefix="micro_runexp_")
    fake_port = _free_port()
    fake = _FakeDataActionServer("FAKE", "ping", root)
    await fake.dispatcher.serve("127.0.0.1", derive_rpc_port(fake_port))
    try:
        async with _make_orch(
            root, {"FAKE": {"host": "127.0.0.1", "port": fake_port}}
        ) as orch:
            loaded = await orch.run_experiment(
                _demo_exp_func, experiment=Experiment(experiment_name="runexp")
            )
            from helao.core.drivers.data.loaders.localfs import HelaoExperiment
            reporter.check(
                "run_experiment returns a HelaoExperiment",
                lambda: isinstance(loaded, HelaoExperiment),
            )
            reporter.check(
                "fake server received two dispatches",
                lambda: len(fake.action_calls) == 2,
            )
            reporter.check(
                "both actions nested under the same experiment dir",
                lambda: all(
                    "__runexp" in c.get("action_output_dir", "")
                    for c in fake.action_calls
                ),
            )
            reporter.check(
                "exp run was tracked",
                lambda: any(r["type"] == "experiment" for r in orch.runs),
            )

            # standalone run_action -> HelaoAction
            act = Action(
                action_name="ping",
                action_server=MachineModel(server_name="FAKE"),
            )
            aloaded = await orch.run_action(act)
            from helao.core.drivers.data.loaders.localfs import HelaoAction
            reporter.check(
                "run_action returns a HelaoAction",
                lambda: isinstance(aloaded, HelaoAction),
            )
            reporter.check(
                "action run was tracked",
                lambda: any(r["type"] == "action" for r in orch.runs),
            )
    finally:
        await fake.dispatcher.close()
        shutil.rmtree(root, ignore_errors=True)
```

Invoke inside `micro_orch_unit_test()` before `return reporter.success()`:

```python
        reporter.section("MicroOrch run_experiment / run_action end-to-end")
        asyncio.run(_drive_run_experiment(reporter))
```

- [ ] **Step 3: Run the test to verify it fails**

Run:
```bash
python -c "import sys; from helao.core.tests.unit_test_micro_orch import micro_orch_unit_test; sys.exit(0 if micro_orch_unit_test() else 1)"
```
Expected: FAIL — `run_experiment` still returns `List[dict]` (not a `HelaoExperiment`) and does not stamp/persist/track; `run_action` returns a dict.

- [ ] **Step 4: Rewrite `run_action` and `run_experiment`**

Add to `micro_orch.py` imports (if not present): `from helao.core.drivers.data.loaders.localfs import HelaoAction, HelaoExperiment` is NOT added at top (avoid pandas-at-import); instead the wrappers are produced by the loader, so no direct import is needed in `run_*`.

Replace the body of `run_action` so it returns a wrapped object. Change its return section: after computing the terminal `result` dict, add staging of identity, then load. Replace the whole `run_action` method with:

```python
    async def run_action(
        self,
        action: Action,
        params: Optional[dict] = None,
        dispatch_timeout: float = 60.0,
        wait_timeout: Optional[float] = None,
        await_completion: bool = True,
    ) -> Any:
        """Dispatch ``action``, wait for terminal, then return a loaded HelaoAction.

        When ``await_completion`` is False the raw terminal/dispatch dump is
        returned instead (no finished artifact to load).
        """
        result = await self.dispatch_action(
            action, params=params, timeout=dispatch_timeout
        )
        action_status = (
            result.get("action_status") if isinstance(result, dict) else None
        )
        if not _is_terminal(action_status):
            action_uuid = action.action_uuid
            assert action_uuid is not None
            result = await self.wait_for_action(action_uuid, timeout=wait_timeout)

        if not await_completion:
            return result

        # init_act (run inside dispatch_action) has assigned the output dir.
        rel_dir = action.get_action_dir()
        loaded = await self._load_finished(rel_dir, "act")
        self._track_run("action", action.action_uuid, action.action_name, loaded.yml_path)
        return loaded
```

Now rewrite `run_experiment`. Replace the method body from the `if experiment is None:` line through the final `return terminal_results` with:

```python
        if experiment is None:
            experiment = Experiment()

        # Stamp experiment + sequence identity BEFORE calling exp_func so that
        # ActionPlanMaker copies the stamped identity into each planned action.
        self._stage_experiment(experiment, order=0, sequence=_sequence)

        func_args = inspect.getfullargspec(exp_func).args
        supplied = {k: v for k, v in exp_params.items() if k in func_args}
        exp_return = exp_func(experiment, **supplied)

        if isinstance(exp_return, Experiment):
            # apm.experiment returns a (deep)copy carrying the stamped identity;
            # adopt it as the canonical object to persist.
            experiment = exp_return
            actions = experiment.planned_actions
        elif isinstance(exp_return, list):
            actions = exp_return
        else:
            raise TypeError(
                f"exp_func {exp_func.__name__!r} returned "
                f"{type(exp_return).__name__}; expected list[Action] or Experiment"
            )

        if not actions:
            # still persist an (empty) experiment for a faithful record
            if await_completion:
                experiment.experiment_status = [HloStatus.finished]
                experiment.experiment_finished_timestamp = set_time(
                    offset=0
                )
                yml_path = await self._write_exp(experiment)
                loaded = await self._load_finished(
                    experiment.get_experiment_dir(), "exp"
                )
                self._track_run(
                    "experiment",
                    experiment.experiment_uuid,
                    experiment.experiment_name,
                    yml_path,
                )
                return loaded
            return []

        for i, act in enumerate(actions):
            self._stage_action(act, order=i)

        results: List[dict] = []
        for act in actions:
            self._apply_from_global(act)
            await self._wait_for_start_condition(act)
            result = await self.dispatch_action(act, timeout=dispatch_timeout)
            results.append(result)
            self._capture_to_global(result, act.to_global_params)

        if not await_completion:
            return results

        terminal_results: List[dict] = []
        for act, immediate in zip(actions, results):
            status = (
                immediate.get("action_status") if isinstance(immediate, dict) else None
            )
            if _is_terminal(status) or act.nonblocking:
                terminal_results.append(immediate)
            else:
                action_uuid = act.action_uuid
                assert action_uuid is not None
                terminal_results.append(
                    await self.wait_for_action(action_uuid, timeout=wait_timeout)
                )

        # Build full-fidelity ExperimentModel: fold each finished action back in.
        for dump in terminal_results:
            if isinstance(dump, dict):
                try:
                    experiment.dispatched_actions.append(Action(**dump))
                except Exception:
                    LOGGER.exception("could not rebuild Action from terminal dump")

        experiment.experiment_status = [HloStatus.finished]
        experiment.experiment_finished_timestamp = set_time(offset=0)
        yml_path = await self._write_exp(experiment)
        loaded = await self._load_finished(experiment.get_experiment_dir(), "exp")
        self._track_run(
            "experiment",
            experiment.experiment_uuid,
            experiment.experiment_name,
            yml_path,
        )
        return loaded
```

Also update the `run_experiment` signature to accept the internal `_sequence` context (used by `run_sequence` in Task 6). Change its signature to add `_sequence` as a keyword-only parameter before `**exp_params`:

```python
    async def run_experiment(
        self,
        exp_func: Callable[..., Union[List[Action], Experiment]],
        experiment: Optional[Experiment] = None,
        await_completion: bool = True,
        dispatch_timeout: float = 60.0,
        wait_timeout: Optional[float] = None,
        _sequence: Optional["Sequence"] = None,
        **exp_params: Any,
    ) -> Any:
```

> Note on `experiment_finished_timestamp`: this field exists on `ExperimentModel`. If a check reveals the field name differs, set the status only and rely on `init_exp`'s timestamp — but the field is present in the model, so set it as shown.

- [ ] **Step 5: Run the test to verify it passes**

Run:
```bash
python -c "import sys; from helao.core.tests.unit_test_micro_orch import micro_orch_unit_test; sys.exit(0 if micro_orch_unit_test() else 1)"
```
Expected: PASS (including the original `run_action` end-to-end section — note that section asserts `run_action` returns a dict; **update it**, see Step 6).

- [ ] **Step 6: Update the pre-existing run_action assertions for the new return type**

The original `_drive_micro_orch` asserts `run_action returns the finished action dump` (a dict). That fake server (`_FakeActionServer`) does not write artifacts to disk, so `run_action` (now always-wrap) would time out. Change that single call to opt out of wrapping:

In `_drive_micro_orch`, change:
```python
            result = await orch.run_action(action, wait_timeout=3.0)
```
to:
```python
            result = await orch.run_action(
                action, wait_timeout=3.0, await_completion=False
            )
```
The existing assertions about the returned dict then remain valid (raw dump returned when `await_completion=False`).

- [ ] **Step 7: Run the test again to verify everything passes**

Run:
```bash
python -c "import sys; from helao.core.tests.unit_test_micro_orch import micro_orch_unit_test; sys.exit(0 if micro_orch_unit_test() else 1)"
```
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add helao/core/runners/micro_orch.py helao/core/tests/unit_test_micro_orch.py
git commit -m "feat(micro_orch): run_action/run_experiment persist, track, return loaded objects"
```

---

## Task 6: `run_sequence`

Expand a sequence-library function into experiments, run each, persist + track the sequence, return a loaded `HelaoSequence`.

**Files:**
- Modify: `helao/core/runners/micro_orch.py`
- Test: `helao/core/tests/unit_test_micro_orch.py`

- [ ] **Step 1: Add a failing test section**

Add to `unit_test_micro_orch.py`:

```python
def _demo_seq_func(cycles: int = 2):
    """Sequence function: plan ``cycles`` demo experiments via ExperimentPlanMaker."""
    from helao.helpers.premodels import ExperimentPlanMaker
    epm = ExperimentPlanMaker()
    for _ in range(cycles):
        epm.add("demo_exp", {"wait_time": 0.0})
    return epm.planned_experiments


async def _drive_run_sequence(reporter: TestReporter) -> None:
    root = tempfile.mkdtemp(prefix="micro_runseq_")
    fake_port = _free_port()
    fake = _FakeDataActionServer("FAKE", "ping", root)
    await fake.dispatcher.serve("127.0.0.1", derive_rpc_port(fake_port))
    experiment_lib = {"demo_exp": _demo_exp_func}
    try:
        async with _make_orch(
            root, {"FAKE": {"host": "127.0.0.1", "port": fake_port}}
        ) as orch:
            loaded = await orch.run_sequence(
                _demo_seq_func, experiment_lib, cycles=2
            )
            from helao.core.drivers.data.loaders.localfs import HelaoSequence
            reporter.check(
                "run_sequence returns a HelaoSequence",
                lambda: isinstance(loaded, HelaoSequence),
            )
            reporter.check(
                "two experiments * two actions = four dispatches",
                lambda: len(fake.action_calls) == 4,
            )
            reporter.check(
                "sequence run tracked",
                lambda: any(r["type"] == "sequence" for r in orch.runs),
            )
            reporter.check(
                "all experiments nested under one sequence dir",
                lambda: len(
                    {c["action_output_dir"].split(os.sep)[2] for c in fake.action_calls}
                )
                == 1,
            )
    finally:
        await fake.dispatcher.close()
        shutil.rmtree(root, ignore_errors=True)
```

> The `split(os.sep)[2]` indexing assumes the action_output_dir is relative with layout `YY.WW/MMDD/<seq_dir>/...`; the `<seq_dir>` is index 2. If the action server echoes a path with different leading separators, adjust the index — the intent is "same sequence directory for all".

Invoke inside `micro_orch_unit_test()` before `return reporter.success()`:

```python
        reporter.section("MicroOrch run_sequence end-to-end")
        asyncio.run(_drive_run_sequence(reporter))
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
python -c "import sys; from helao.core.tests.unit_test_micro_orch import micro_orch_unit_test; sys.exit(0 if micro_orch_unit_test() else 1)"
```
Expected: FAIL — `run_sequence` does not exist.

- [ ] **Step 3: Implement `run_sequence`**

Add `from helao.core.models.experiment import ShortExperimentModel` to `micro_orch.py` imports.

Add the method after `run_experiment` in `micro_orch.py`:

```python
    # ------------------------------------------------------------------
    # sequence running
    # ------------------------------------------------------------------

    async def run_sequence(
        self,
        seq_func: Callable[..., List["ShortExperimentModel"]],
        experiment_lib: Dict[str, Callable[..., Union[List[Action], Experiment]]],
        sequence: Optional["Sequence"] = None,
        await_completion: bool = True,
        dispatch_timeout: float = 60.0,
        wait_timeout: Optional[float] = None,
        **seq_params: Any,
    ) -> Any:
        """Expand a sequence-library function and run its planned experiments.

        ``seq_func`` returns ``List[ShortExperimentModel]`` (via
        ``ExperimentPlanMaker``); ``experiment_lib`` maps each plan's
        ``experiment_name`` to its experiment function. Each experiment runs
        under this sequence's identity. The finished sequence is written to
        ``RUNS_FINISHED`` and returned loader-wrapped (or, when
        ``await_completion`` is False, the per-experiment raw dump lists).
        """
        if sequence is None:
            sequence = Sequence()
        if sequence.sequence_name is None:
            sequence.sequence_name = getattr(seq_func, "__name__", "sequence")

        func_args = inspect.getfullargspec(seq_func).args
        supplied = {k: v for k, v in seq_params.items() if k in func_args}

        sequence.init_seq(time_offset=0)

        planned = seq_func(**supplied)

        raw_results: List[Any] = []
        for plan in planned:
            exp_func = experiment_lib.get(plan.experiment_name)
            if exp_func is None:
                raise KeyError(
                    f"experiment {plan.experiment_name!r} not in experiment_lib"
                )
            exp = Experiment(
                experiment_name=plan.experiment_name,
                experiment_params=dict(plan.experiment_params or {}),
            )
            # experiment-level global hand-off (mirrors Orch)
            for k, v in (plan.from_global_exp_params or {}).items():
                if k in self.global_params:
                    val = self.global_params[k]
                    if isinstance(v, list):
                        for vv in v:
                            exp.experiment_params[vv] = val
                    else:
                        exp.experiment_params[v] = val

            exp_result = await self.run_experiment(
                exp_func,
                experiment=exp,
                await_completion=await_completion,
                dispatch_timeout=dispatch_timeout,
                wait_timeout=wait_timeout,
                _sequence=sequence,
                **(exp.experiment_params),
            )
            if await_completion:
                # exp_result is a HelaoExperiment; fold the persisted model in.
                sequence.dispatched_experiments.append(
                    Experiment(**exp_result.json).get_exp()
                )
            else:
                raw_results.append(exp_result)

        if not await_completion:
            return raw_results

        sequence.sequence_status = [HloStatus.finished]
        sequence.sequence_finished_timestamp = set_time(offset=0)
        yml_path = await self._write_seq(sequence)
        loaded = await self._load_finished(sequence.get_sequence_dir(), "seq")
        self._track_run(
            "sequence", sequence.sequence_uuid, sequence.sequence_name, yml_path
        )
        return loaded
```

> Note: `Experiment(**exp_result.json)` rebuilds an `Experiment` from the persisted exp yml dict so `.get_exp()` yields a clean `ExperimentModel` for `dispatched_experiments`. `exp_result.json` is the loader's parsed yml dict (`HelaoModel.json`). If the yml dict contains the `file_type` key, drop it first: `{k: v for k, v in exp_result.json.items() if k != "file_type"}`.

Apply that `file_type` guard — replace `Experiment(**exp_result.json)` with:
```python
                    Experiment(
                        **{k: v for k, v in exp_result.json.items() if k != "file_type"}
                    ).get_exp()
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
python -c "import sys; from helao.core.tests.unit_test_micro_orch import micro_orch_unit_test; sys.exit(0 if micro_orch_unit_test() else 1)"
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add helao/core/runners/micro_orch.py helao/core/tests/unit_test_micro_orch.py
git commit -m "feat(micro_orch): add run_sequence with seq yml persistence"
```

---

## Task 7: `zip_runs`

Archive every tracked artifact, preserving the directory structure relative to the state root (RUNS_FINISHED / RUNS_DIAG), deduplicated.

**Files:**
- Modify: `helao/core/runners/micro_orch.py`
- Test: `helao/core/tests/unit_test_micro_orch.py`

- [ ] **Step 1: Add a failing test section**

Add to `unit_test_micro_orch.py` (top imports already include `zipfile`? add `import zipfile` to the test module imports):

```python
import zipfile


async def _drive_zip_runs(reporter: TestReporter) -> None:
    root = tempfile.mkdtemp(prefix="micro_zip_")
    fake_port = _free_port()
    fake = _FakeDataActionServer("FAKE", "ping", root)
    await fake.dispatcher.serve("127.0.0.1", derive_rpc_port(fake_port))
    experiment_lib = {"demo_exp": _demo_exp_func}
    try:
        async with _make_orch(
            root, {"FAKE": {"host": "127.0.0.1", "port": fake_port}}
        ) as orch:
            await orch.run_sequence(_demo_seq_func, experiment_lib, cycles=1)
            zip_path = os.path.join(root, "artifacts.zip")
            out = orch.zip_runs(zip_path)
            reporter.check("zip_runs returns the zip path", lambda: out == zip_path)
            reporter.check("zip file exists", lambda: os.path.isfile(zip_path))
            with zipfile.ZipFile(zip_path) as zf:
                names = zf.namelist()
            reporter.check(
                "zip contains a seq yml entry",
                lambda: any(n.endswith("-seq.yml") for n in names),
            )
            reporter.check(
                "zip contains an exp yml entry",
                lambda: any(n.endswith("-exp.yml") for n in names),
            )
            reporter.check(
                "zip contains an act yml entry",
                lambda: any(n.endswith("-act.yml") for n in names),
            )
            reporter.check(
                "zip entries are relative (no RUNS_* prefix, no leading sep)",
                lambda: all(
                    not n.startswith("RUNS_") and not n.startswith(os.sep)
                    for n in names
                ),
            )
            reporter.check(
                "no duplicate entries",
                lambda: len(names) == len(set(names)),
            )
    finally:
        await fake.dispatcher.close()
        shutil.rmtree(root, ignore_errors=True)
```

Invoke inside `micro_orch_unit_test()` before `return reporter.success()`:

```python
        reporter.section("MicroOrch zip_runs")
        asyncio.run(_drive_zip_runs(reporter))
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
python -c "import sys; from helao.core.tests.unit_test_micro_orch import micro_orch_unit_test; sys.exit(0 if micro_orch_unit_test() else 1)"
```
Expected: FAIL — `zip_runs` does not exist.

- [ ] **Step 3: Implement `zip_runs`**

Add `import zipfile` to `micro_orch.py` imports. Add the method (new "archiving" section):

```python
    # ------------------------------------------------------------------
    # archiving
    # ------------------------------------------------------------------

    def zip_runs(self, zip_path: str, include_diag: bool = True) -> str:
        """Zip every tracked artifact, preserving structure relative to RUNS_FINISHED.

        Each file's archive name is its path relative to its state root
        (RUNS_FINISHED or RUNS_DIAG), so the archive reproduces the on-disk
        seq/exp/act tree without the ``RUNS_*`` prefix. Overlapping records
        (a sequence dir contains its experiment/action dirs) are deduplicated
        by archive name. ``.lock`` files are skipped.

        Args:
            zip_path: Destination ``.zip`` path.
            include_diag: When False, skip RUNS_DIAG (manual) artifacts.

        Returns:
            ``zip_path``.
        """
        root = self.world_cfg.get("root")
        if not root:
            raise RuntimeError("world_cfg['root'] is required to zip artifacts")

        seen: set = set()
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for record in self.runs:
                state = record["state"]
                if state == "RUNS_DIAG" and not include_diag:
                    continue
                state_root = os.path.join(root, state)
                rec_dir = os.path.join(state_root, record["rel_dir"])
                if not os.path.isdir(rec_dir):
                    continue
                for dirpath, _dirnames, filenames in os.walk(rec_dir):
                    for fn in filenames:
                        if fn.endswith(".lock"):
                            continue
                        abs_path = os.path.join(dirpath, fn)
                        arcname = os.path.relpath(abs_path, state_root)
                        if arcname in seen:
                            continue
                        seen.add(arcname)
                        zf.write(abs_path, arcname)
        return zip_path
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
python -c "import sys; from helao.core.tests.unit_test_micro_orch import micro_orch_unit_test; sys.exit(0 if micro_orch_unit_test() else 1)"
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add helao/core/runners/micro_orch.py helao/core/tests/unit_test_micro_orch.py
git commit -m "feat(micro_orch): zip_runs archives tracked artifacts"
```

---

## Task 8: LocalLoader reads MicroOrch zips

Generalize the `.zip` sequence parser to handle archives rooted at RUNS_FINISHED (entries nested under `YY.WW/MMDD/<seq_dir>/...`), keeping legacy single-sequence zips working.

**Files:**
- Modify: `helao/core/drivers/data/loaders/localfs.py:25-73` (`parse_seq_path`) and `localfs.py:469-489` (`get_bytes`)
- Test: `helao/core/tests/unit_test_micro_orch.py`

- [ ] **Step 1: Add a failing round-trip test section**

Add to `unit_test_micro_orch.py`:

```python
async def _drive_zip_roundtrip(reporter: TestReporter) -> None:
    """A MicroOrch zip loads back through LocalLoader."""
    root = tempfile.mkdtemp(prefix="micro_ziprt_")
    fake_port = _free_port()
    fake = _FakeDataActionServer("FAKE", "ping", root)
    await fake.dispatcher.serve("127.0.0.1", derive_rpc_port(fake_port))
    experiment_lib = {"demo_exp": _demo_exp_func}
    try:
        async with _make_orch(
            root, {"FAKE": {"host": "127.0.0.1", "port": fake_port}}
        ) as orch:
            seq_loaded = await orch.run_sequence(
                _demo_seq_func, experiment_lib, cycles=1
            )
            zip_path = os.path.join(root, "artifacts.zip")
            orch.zip_runs(zip_path)

        from helao.core.drivers.data.loaders.localfs import LocalLoader
        loader = LocalLoader(zip_path)
        reporter.check(
            "loader indexed exactly one sequence",
            lambda: len(loader.sequences) == 1,
        )
        reporter.check(
            "loader indexed one experiment",
            lambda: len(loader.experiments) == 1,
        )
        reporter.check(
            "loader indexed two actions",
            lambda: len(loader.actions) == 2,
        )
        seq = loader.get_seq(0)
        reporter.check(
            "round-tripped sequence_uuid matches",
            lambda: str(seq.sequence_uuid) == str(seq_loaded.sequence_uuid),
        )
        act = loader.get_act(0)
        meta, data = act.hlo
        reporter.check(
            "round-tripped action hlo data is readable",
            lambda: "v" in data and list(data["v"]) == [1.0],
        )
    finally:
        await fake.dispatcher.close()
        shutil.rmtree(root, ignore_errors=True)
```

Invoke inside `micro_orch_unit_test()` before `return reporter.success()`:

```python
        reporter.section("MicroOrch zip <-> LocalLoader round-trip")
        asyncio.run(_drive_zip_roundtrip(reporter))
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
python -c "import sys; from helao.core.tests.unit_test_micro_orch import micro_orch_unit_test; sys.exit(0 if micro_orch_unit_test() else 1)"
```
Expected: FAIL — `parse_seq_path` forces `yml_dir = basename(zip)` for zip targets, so the multi-tree archive's sequence dir is misparsed (sequence row count / uuid wrong, or a parse error).

- [ ] **Step 3: Fix `parse_seq_path` in `localfs.py`**

Replace the opening of `parse_seq_path` (the `if ymlp.endswith(".yml") or target.endswith(".zip"):` block, `localfs.py:38-46`) with logic that derives `yml_dir` from the entry's own in-zip dirname when present:

```python
    if ymlp.endswith(".yml") or target.endswith(".zip"):
        yml_dir = os.path.basename(os.path.dirname(ymlp))
        yml_file = os.path.basename(ymlp)
        if target.endswith(".zip"):
            # Legacy single-sequence zips store the seq yml at the archive root
            # (no parent dir), so fall back to the zip filename. MicroOrch zips
            # are rooted at RUNS_FINISHED, so the entry's own parent dir IS the
            # sequence dir and must be used.
            entry_dir = os.path.basename(os.path.dirname(ymlp))
            if entry_dir:
                yml_dir = entry_dir
            else:
                yml_dir = os.path.basename(target).replace(".zip", "")
            yml_file = os.path.basename(ymlp)
    else:
        yml_dir = os.path.basename(ymlp)
        yml_file = yml_dir
```

- [ ] **Step 4: Fix `get_bytes` in `localfs.py` for multi-sequence zips**

Replace the zip branch of `get_bytes` (`localfs.py:479-484`):

```python
        if self.target.endswith(".zip") and yml_path == "":
            rel_seqzip_path = fn.split(self.sequences.iloc[0].sequence_dir)[-1].lstrip(
                "/"
            )
            with ZipFile(self.target, "r") as zf:
                fbytes = zf.open(rel_seqzip_path).read()
```

with a version that matches whichever indexed sequence_dir the requested path contains:

```python
        if self.target.endswith(".zip") and yml_path == "":
            rel_seqzip_path = fn
            for seq_dir in self.sequences.sequence_dir:
                if seq_dir and seq_dir in fn:
                    rel_seqzip_path = fn.split(seq_dir, 1)[-1].lstrip("/")
                    rel_seqzip_path = f"{seq_dir}/{rel_seqzip_path}".rstrip("/")
                    break
            with ZipFile(self.target, "r") as zf:
                fbytes = zf.open(rel_seqzip_path).read()
```

> Rationale: MicroOrch zip entries are full paths relative to RUNS_FINISHED (`YY.WW/MMDD/<seq_dir>/...`), so the in-zip name retains the sequence dir prefix. We keep the prefix rather than stripping it (the legacy code stripped because its entries were relative to the seq dir). Reconstructing `<seq_dir>/<remainder>` yields the correct in-zip key for both layouts where the entry name contains the seq dir.

- [ ] **Step 5: Run the test to verify it passes**

Run:
```bash
python -c "import sys; from helao.core.tests.unit_test_micro_orch import micro_orch_unit_test; sys.exit(0 if micro_orch_unit_test() else 1)"
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add helao/core/drivers/data/loaders/localfs.py helao/core/tests/unit_test_micro_orch.py
git commit -m "feat(localfs): LocalLoader reads RUNS_FINISHED-rooted MicroOrch zips"
```

---

## Task 9: full-suite gate + docstring sweep

**Files:**
- Modify: `helao/core/runners/micro_orch.py` (module docstring example)

- [ ] **Step 1: Update the module docstring example**

In `micro_orch.py`, extend the docstring `Example:` block to show the new methods. Replace the existing example block with:

```python
Example:
    orch = MicroOrch(server_key="micro", host="127.0.0.1", port=9999,
                     world_cfg=world_cfg)
    await orch.start()
    try:
        action = await orch.run_action(action)              # -> HelaoAction
        experiment = await orch.run_experiment(my_exp_func) # -> HelaoExperiment
        sequence = await orch.run_sequence(                 # -> HelaoSequence
            my_seq_func, experiment_lib={"my_exp": my_exp_func})
        orch.zip_runs("artifacts.zip")                      # archive all of it
    finally:
        await orch.stop()
```

- [ ] **Step 2: Run the full unit-test suite**

Run:
```bash
python run_unit_tests.py
```
Expected: `overall: PASS` — every module, including `micro_orch`, passes. (`launch.py` runs this gate before launching, so it must be green.)

- [ ] **Step 3: Commit**

```bash
git add helao/core/runners/micro_orch.py
git commit -m "docs(micro_orch): document run_sequence/run_action wrap + zip_runs"
```

---

## Self-review notes (for the implementer)

- **Spec coverage:** Component 1 → Task 2 (`_stage_experiment`; `_stage_action` left as-is because `ActionPlanMaker` propagates identity from the pre-stamped experiment — verified in `premodels.py:521` where `ActionPlanMaker.add` builds `Action(**self._experiment.as_dict())`). Component 2 → Task 5 (`dispatched_actions` fold). Component 3 → Task 1. Component 4 → Task 6. Component 5 → Tasks 3+5 (always-wrap, `await_completion=False` returns raw). Component 6 → Task 4. Component 7 → Task 7. Component 8 → Task 8.
- **Manual vs finished:** standalone `run_action`/`run_experiment` produce manual artifacts under `RUNS_DIAG`; `_candidate_yml` checks both states; `zip_runs` includes both (toggle via `include_diag`).
- **If a field name surprises you:** `experiment_finished_timestamp` / `sequence_finished_timestamp` are set in Tasks 5/6. If a model rejects them at runtime, confirm the field name in `helao/core/models/experiment.py` / `sequence.py` and adjust; the status update alone is sufficient for a valid yml if needed.
- **Loader import timing:** `LocalLoader` (and pandas) is imported lazily inside `__init__`/return paths, not at module top, so importing `micro_orch` stays cheap for callers that never read back.
```
