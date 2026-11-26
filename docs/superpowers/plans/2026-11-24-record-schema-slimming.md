# Record Schema Slimming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Shrink sequence and experiment records by replacing their list
attributes with uuid lists and write-once plan sidecars, make `action_params`
inputs-only by routing produced values through one `set_output` path, and record
which finish hooks touched each record.

**Architecture:** One exclusion set per record model plus a `record_dict()`
used by every record writer; a pure plan module and a write-once helper shared
by the orchestrator's `MetaWriter` and `MicroOrch`; `ActionModel.set_output` as
the only writer of `action_output`, with a session wrapper, an executor-start
params snapshot and a finish-time warning; `run_prefinish` and the `s3_upload`
hook stamp hook names.

**Tech Stack:** Python 3.14, pydantic 2, pytest + pytest-asyncio, orjson
(`dumps_meta`), the `helao` conda env.

**Spec:** `docs/superpowers/specs/2026-11-24-record-schema-slimming-design.md`
(commits `8079796d`..`ba4da881` on `feat/record-schema-slimming`).

## Global Constraints

- Python: `/home/dan/miniforge3/envs/helao/bin/python`. Run every test from the
  parent root with `PYTHONPATH=.`:
  `cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=. /home/dan/miniforge3/envs/helao/bin/python -m pytest <file> -q`
- Parent repo is public. Never write the private deployment folder names in a
  tracked parent file; use Deployment-A, Deployment-C, Deployment-E. Each private
  repo's exact sites are in its own addendum:
  `helao/deploy/<repo>/docs/superpowers/plans/2026-11-24-record-schema-slimming-sites.md`
  (the main thread gives implementers the repo name).
- Nested repos (`helao/deploy/*`) are separate git repos. Use `git -C <repo>` on
  every git call. Before editing one: confirm it is on its default branch with a
  clean status, then create `feat/record-schema-slimming` from it. If it is on
  another branch or dirty, stop and report; never stash or commit another
  session's work.
- Subagents never run `git add`, `commit`, `push` or `stash`, and never write
  outside the working tree or `$CLAUDE_JOB_DIR`. Commit steps below are run by
  the main thread after review. Nothing is pushed without the owner's approval;
  the archive host deploys on push.
- Run `black` on changed `.py` files right before each commit, in the repo that
  owns them.
- Never touch `/mnt/wd4`, `/mnt/st2`, `/mnt/k`, `/mnt/j`, `/mnt/i`.
- Never hardcode a colour (`helao/ui/shared/palette.py` rule); this work touches no UI.
- Every new test gets a mutation check: revert the code it guards, confirm it
  fails, restore. Record the failing output in the task report.
- Record kind strings for plan hashes: `seq_plan`, `exp_plan`.

## Review Focus

1. **A station record written before the upgrade, synced after it.** Its local
   `-seq`/`-exp` file still carries the lists; the S3 push must still drop them
   (`record_dict` in `s3_upload`). Test in Task 6.
2. **`aux_files` names a plan that is missing on disk** (deleted, never
   written). Sync must still finish and push the meta, with a warning, not wedge
   the record. Test in Task 6.
3. **A sequence or experiment with nothing planned.** The plan is still written,
   with `planned: []`, and the record has no `experiment_list` key. Test in Task 2.
4. **`--restore` re-dispatch of an experiment that already has a plan.** The
   original plan file must survive byte-for-byte. Test in Task 2 (helper) and
   Task 3 (`MetaWriter`).
5. **Output written after a split.** It lands on the running split, not the
   earlier split's copy that the finalizer also writes. Test in Task 7.

---

## Part 1 — list attributes to plan sidecars (parent repo, then Deployment-C tests)

### Task 1: `record_dict`, `experiment_list`, `action_list`

**Files:**
- Modify: `helao/core/helaodict.py` (class `HelaoDict`, line 29)
- Modify: `helao/core/models/sequence.py` (class `SequenceModel`)
- Modify: `helao/core/models/experiment.py` (class `ExperimentModel`)
- Modify: `helao/helpers/premodels.py:93-107` (`Sequence.get_seq`), `:257-267` (`Experiment.get_exp`)
- Modify: `helao/helpers/run_state.py:310-316` (comment)
- Test: `helao/core/tests/test_record_schema.py` (create)

**Interfaces:**
- Produces: `HelaoDict.RECORD_EXCLUDE: ClassVar[frozenset[str]]`;
  `HelaoDict.record_dict(self, strip_private: bool = False) -> dict`;
  `SequenceModel.experiment_list: list[UUID]`; `ExperimentModel.action_list: list[UUID]`.

- [ ] **Step 1: Write the failing tests**

```python
"""Record shape (spec §3.1-3.2): lists leave the record, uuid lists replace them."""

import json
from uuid import UUID

from helao.core.models.experiment import ExperimentModel, ShortExperimentModel
from helao.core.models.sequence import SequenceModel
from helao.helpers.premodels import Action, Experiment, Sequence

U1 = UUID("00000000-0000-0000-0000-000000000001")
U2 = UUID("00000000-0000-0000-0000-000000000002")


def test_record_dict_drops_sequence_lists_clean_dict_keeps_them():
    seq = SequenceModel(
        sequence_name="s",
        planned_experiments=[ShortExperimentModel(experiment_name="e")],
        dispatched_experiments_abbr=[ShortExperimentModel(experiment_name="e")],
    )
    assert "planned_experiments" in seq.clean_dict()
    rec = seq.record_dict()
    assert "planned_experiments" not in rec
    assert "dispatched_experiments_abbr" not in rec
    assert rec["sequence_name"] == "s"


def test_record_dict_drops_experiment_lists():
    exp = ExperimentModel(
        experiment_name="e",
        planned_actions=[{"action_name": "a"}],
        dispatched_actions_abbr=[{"action_uuid": U1}],
    )
    rec = exp.record_dict()
    assert "planned_actions" not in rec and "dispatched_actions_abbr" not in rec


def test_record_dict_keeps_private_keys_unless_asked():
    seq = SequenceModel(sequence_name="s", sequence_params={"_p": 1, "q": 2})
    assert seq.record_dict()["sequence_params"] == {"_p": 1, "q": 2}
    assert seq.record_dict(strip_private=True)["sequence_params"] == {"q": 2}


def test_get_seq_fills_experiment_list_in_dispatch_order():
    seq = Sequence(sequence_name="s")
    seq.dispatched_experiments = [
        ExperimentModel(experiment_name="b", experiment_uuid=U2),
        ExperimentModel(experiment_name="a", experiment_uuid=U1),
    ]
    assert seq.get_seq().experiment_list == [U2, U1]


def test_get_seq_falls_back_to_a_directly_set_abbr_list():
    """Deployment-C converters set the abbreviated list, never the full one."""
    seq = Sequence(sequence_name="s")
    seq.dispatched_experiments_abbr = [
        ShortExperimentModel(experiment_name="a", experiment_uuid=U1)
    ]
    assert seq.get_seq().experiment_list == [U1]


def test_get_exp_action_list_keeps_dispatch_order_and_splits():
    exp = Experiment(experiment_name="e")
    exp.dispatched_actions = [
        Action(action_name="a", action_uuid=U2, action_order=0, action_split=0),
        Action(action_name="a", action_uuid=U1, action_order=0, action_split=1),
    ]
    assert exp.get_exp().action_list == [U2, U1]


def test_empty_lists_are_absent_from_the_record():
    rec = Sequence(sequence_name="s").get_seq().record_dict()
    assert "experiment_list" not in rec


def test_sequence_record_size_is_flat_in_planned_count():
    def size(n):
        planned = [
            ShortExperimentModel(
                experiment_name="e", experiment_params={"x": list(range(50))}
            )
            for _ in range(n)
        ]
        rec = SequenceModel(sequence_name="s", planned_experiments=planned)
        return len(json.dumps(rec.record_dict(), default=str))

    assert size(1) == size(200)


def test_old_record_with_lists_still_validates():
    old = {
        "sequence_name": "s",
        "planned_experiments": [{"experiment_name": "e", "experiment_params": {}}],
        "dispatched_experiments_abbr": [{"experiment_uuid": str(U1)}],
    }
    assert "planned_experiments" not in SequenceModel(**old).record_dict()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=. /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/core/tests/test_record_schema.py -q`
Expected: FAIL, `AttributeError: 'SequenceModel' object has no attribute 'record_dict'`.

- [ ] **Step 3: Implement**

`helao/core/helaodict.py`: add `ClassVar` to the `typing` import, then inside `class HelaoDict:` above `as_dict`:

```python
    #: Fields a stored record omits (spec §3.2). Runtime models and transport
    #: (``clean_dict``) still carry them.
    RECORD_EXCLUDE: ClassVar[frozenset[str]] = frozenset()

    def record_dict(self, strip_private: bool = False) -> dict:
        """``clean_dict(strip_private)`` minus :attr:`RECORD_EXCLUDE`: what a record file or S3 meta holds."""
        d = self.clean_dict(strip_private=strip_private)
        for key in self.RECORD_EXCLUDE:
            d.pop(key, None)
        return d
```

`helao/core/models/sequence.py`: add `from typing import ClassVar` (keep `Optional`). In `SequenceModel`, after `orchestrator: MachineModel = MachineModel()`:

```python
    RECORD_EXCLUDE: ClassVar[frozenset[str]] = frozenset(
        {"planned_experiments", "dispatched_experiments_abbr"}
    )
    #: Dispatched experiment uuids in dispatch order; the record's link to its
    #: experiments (spec §3.1). The plan lives in ``<ts>-seq.plan.json``.
    experiment_list: list[UUID] = Field(default=[])
```

Add `experiment_list (list[UUID])` to the class docstring's Attributes.

`helao/core/models/experiment.py`: add `ClassVar` to the typing import. In `ExperimentModel`, after `dispatched_actions_abbr`:

```python
    RECORD_EXCLUDE: ClassVar[frozenset[str]] = frozenset(
        {"planned_actions", "dispatched_actions_abbr"}
    )
    #: Dispatched action uuids in dispatch order, splits and retries included
    #: (spec §3.1). The plan lives in ``<ts>-exp.plan.json``.
    action_list: list[UUID] = Field(default=[])
```

Add `action_list (list[UUID])` to the docstring.

`helao/helpers/premodels.py`, `Sequence.get_seq` — replace the body after `seq = SequenceModel.model_validate(...)`:

```python
        seq = SequenceModel.model_validate(self.model_dump())
        seq.dispatched_experiments_abbr = [
            ShortExperimentModel.model_validate(exp.model_dump())
            for exp in self.dispatched_experiments
        ]
        # A converter sets the abbreviated list directly and never fills
        # dispatched_experiments; fall back to it so its record keeps the link.
        source = seq.dispatched_experiments_abbr or self.dispatched_experiments_abbr
        seq.experiment_list = list(
            dict.fromkeys(e.experiment_uuid for e in source if e.experiment_uuid)
        )
        return seq
```

Keep the existing three comment lines about `planned_experiments` above `return`.

`Experiment.get_exp`:

```python
        exp = ExperimentModel.model_validate(self.model_dump())
        # now add all actions
        self._experiment_update_from_actlist(exp=exp)
        exp.action_list = list(
            dict.fromkeys(
                a.action_uuid for a in exp.dispatched_actions_abbr if a.action_uuid
            )
        )
        return exp
```

`helao/helpers/run_state.py:310-316`: replace the sentence "a sequence's own uuid sits seven lines from the *end* of a file measured in hundreds of thousands of lines -- ``sequence_params`` and ``planned_experiments`` are serialized before it" with "a sequence's own uuid sits near the *end* of the file, after ``sequence_params`` (records written before 2026-11 also carried ``planned_experiments`` there and ran to hundreds of thousands of lines)". Keep the rest.

- [ ] **Step 4: Run tests, then the neighbours**

Run: `PYTHONPATH=. /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/core/tests/test_record_schema.py helao/core/tests/unit_test_helaodict.py helao/core/tests/test_helaodict_keys.py -q`
Expected: PASS.

- [ ] **Step 5: Mutation check.** Delete the `d.pop(key, None)` line; `test_record_dict_drops_sequence_lists_clean_dict_keeps_them` must fail. Restore.

- [ ] **Step 6: Commit** (main thread)

```bash
black helao/core/helaodict.py helao/core/models/sequence.py helao/core/models/experiment.py helao/helpers/premodels.py helao/helpers/run_state.py helao/core/tests/test_record_schema.py
git -C /mnt/STORAGE/repos/helao/helao-async add <those files>
git -C /mnt/STORAGE/repos/helao/helao-async commit -m "feat(models): record_dict drops plan lists; experiment_list/action_list"
```

### Task 2: plan module and write-once helper

**Files:**
- Create: `helao/core/models/plan.py`
- Create: `helao/helpers/plan_io.py`
- Test: `helao/core/tests/test_plan_sidecar.py` (create)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces:
  - `plan_name(record_file: str) -> str` (`".../X-seq.json"` → `"X-seq.plan.json"`)
  - `sequence_plan(sequence_uuid, planned: list) -> dict`
  - `experiment_plan(experiment_uuid, actions: list) -> dict`
  - `async write_plan_once(target, payload: dict, write_atomic, *, kind: str, owner_uuid) -> bool`
    (`write_atomic` is `async (path: str, text: str) -> None`; returns `True` if it wrote).

- [ ] **Step 1: Write the failing tests**

```python
"""Plan sidecars (spec §3.3): stripped entries, write-once, invisible to record globs."""

import json
from uuid import UUID

import pytest

from helao.core.models.experiment import ShortExperimentModel
from helao.core.models.plan import experiment_plan, plan_name, sequence_plan
from helao.helpers.plan_io import write_plan_once
from helao.helpers.premodels import Action
from helao.hexagon.domain.naming import meta_kind

SU = UUID("00000000-0000-0000-0000-0000000000b1")
EU = UUID("00000000-0000-0000-0000-0000000000c1")
A1 = UUID("00000000-0000-0000-0000-0000000000a1")


def test_plan_name_from_json_and_legacy_yml():
    assert plan_name("/r/s/260101.010101000000-seq.json") == "260101.010101000000-seq.plan.json"
    assert plan_name("/r/s/260101.010101000000-exp.yml") == "260101.010101000000-exp.plan.json"


def test_plan_files_are_not_records():
    assert meta_kind("260101.010101000000-seq.plan.json") is None
    assert meta_kind("260101.010101000000-exp.plan.json") is None


def test_sequence_plan_strips_params_and_output_dir():
    planned = [
        ShortExperimentModel(
            experiment_name=n,
            experiment_params={"big": list(range(100))},
            experiment_output_dir="x/y",
            orch_key="ORCH",
        )
        for n in ("a", "b")
    ]
    p = sequence_plan(SU, planned)
    assert p["file_type"] == "sequence_plan"
    assert p["sequence_uuid"] == str(SU)
    assert [e["order"] for e in p["planned"]] == [0, 1]
    assert [e["experiment_name"] for e in p["planned"]] == ["a", "b"]
    for e in p["planned"]:
        assert "experiment_params" not in e and "experiment_output_dir" not in e
        assert e["orch_key"] == "ORCH"


def test_experiment_plan_strips_action_params():
    act = Action(
        action_name="acquire",
        action_uuid=A1,
        action_order=3,
        action_params={"huge": list(range(100))},
        process_finish=True,
    )
    act.action_server.server_name = "PSTAT"
    p = experiment_plan(EU, [act])
    assert p["file_type"] == "experiment_plan"
    (e,) = p["planned"]
    assert e["action_uuid"] == str(A1)
    assert e["action_order"] == 3
    assert e["server_name"] == "PSTAT"
    assert e["process_finish"] is True
    assert "action_params" not in e


def test_empty_plan_still_has_a_planned_list():
    assert sequence_plan(SU, [])["planned"] == []


@pytest.mark.asyncio
async def test_write_plan_once_writes_then_never_overwrites(tmp_path):
    async def write_atomic(path, text):
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    target = tmp_path / "sub" / "260101.010101000000-seq.plan.json"
    first = sequence_plan(SU, [ShortExperimentModel(experiment_name="a")])
    assert await write_plan_once(target, first, write_atomic, kind="seq_plan", owner_uuid=SU)
    before = target.read_bytes()
    second = sequence_plan(SU, [ShortExperimentModel(experiment_name="other")])
    assert not await write_plan_once(target, second, write_atomic, kind="seq_plan", owner_uuid=SU)
    assert target.read_bytes() == before
    assert json.loads(before)["planned"][0]["experiment_name"] == "a"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=. /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/core/tests/test_plan_sidecar.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'helao.core.models.plan'`.

- [ ] **Step 3: Implement `helao/core/models/plan.py`**

```python
"""Plan sidecars: what a sequence or experiment intended, written once at its start.

Spec ``docs/superpowers/specs/2026-11-24-record-schema-slimming-design.md`` §3.3.
Entries are stripped: no experiment/action params, no output dirs. The record's
``experiment_list``/``action_list`` say what actually ran.
"""

__all__ = [
    "ExperimentPlanEntry",
    "SequencePlanEntry",
    "experiment_plan",
    "plan_name",
    "sequence_plan",
]

from pathlib import Path
from typing import Optional
from uuid import UUID

from pydantic import BaseModel

from helao.core.helaodict import HelaoDict

from .action_start_condition import ActionStartCondition


class SequencePlanEntry(BaseModel, HelaoDict):
    """One planned experiment. Uuids are assigned at dispatch, so there is none here."""

    order: int
    experiment_name: Optional[str] = None
    experiment_comment: Optional[str] = None
    orch_key: Optional[str] = None
    orch_host: Optional[str] = None
    orch_port: Optional[int] = None
    data_request_id: Optional[UUID] = None
    from_global_exp_params: dict = {}


class ExperimentPlanEntry(BaseModel, HelaoDict):
    """One planned action, uuid included (assigned when the action is staged)."""

    action_order: int
    action_uuid: Optional[UUID] = None
    action_name: Optional[str] = None
    server_name: Optional[str] = None
    start_condition: Optional[ActionStartCondition] = None
    process_finish: bool = False


def plan_name(record_file: str) -> str:
    """``<dir>/<ts>-seq.json`` (or ``.yml``) -> ``<ts>-seq.plan.json``."""
    return Path(record_file).with_suffix("").name + ".plan.json"


def sequence_plan(sequence_uuid, planned: list) -> dict:
    """Payload for ``<ts>-seq.plan.json`` from a list of ``ShortExperimentModel``."""
    entries = [
        SequencePlanEntry.model_validate({**e.model_dump(), "order": i})
        for i, e in enumerate(planned)
    ]
    return {
        "file_type": "sequence_plan",
        "sequence_uuid": str(sequence_uuid),
        "planned": [e.as_dict() for e in entries],
    }


def experiment_plan(experiment_uuid, actions: list) -> dict:
    """Payload for ``<ts>-exp.plan.json`` from staged ``Action`` objects."""
    entries = [
        ExperimentPlanEntry(
            action_order=a.action_order if a.action_order is not None else i,
            action_uuid=a.action_uuid,
            action_name=a.action_name,
            server_name=a.action_server.server_name,
            start_condition=a.start_condition,
            process_finish=bool(a.process_finish),
        )
        for i, a in enumerate(actions)
    ]
    return {
        "file_type": "experiment_plan",
        "experiment_uuid": str(experiment_uuid),
        "planned": [e.as_dict() for e in entries],
    }
```

If `as_dict()` renders the enum `start_condition` as an object rather than its
value, confirm against `HelaoDict._serialize_item` and keep whatever JSON
`dumps_meta` writes for `-act.json` today; do not add a custom encoder.

- [ ] **Step 4: Implement `helao/helpers/plan_io.py`**

```python
"""Write-once plan sidecars (spec §3.3), shared by MetaWriter and MicroOrch."""

__all__ = ["write_plan_once"]

from pathlib import Path

from helao.helpers.artifact_hash import log_artifact_hashes
from helao.helpers.meta_io import dumps_meta


async def write_plan_once(target, payload: dict, write_atomic, *, kind: str, owner_uuid) -> bool:
    """Write ``payload`` to ``target`` unless a plan is already there.

    A plan records initial intent, so a ``--restore`` re-dispatch must not
    replace it. ``write_atomic(path, text)`` is the caller's staged-rename
    writer, which keeps the ``staging_path`` rule. Returns whether it wrote.
    """
    target = Path(target)
    if target.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    await write_atomic(str(target), dumps_meta(payload, target))
    await log_artifact_hashes([target], kind=kind, owner_uuid=owner_uuid)
    return True
```

- [ ] **Step 5: Run tests + the hash gate**

Run: `PYTHONPATH=. /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/core/tests/test_plan_sidecar.py helao/core/tests/test_artifact_hash_gate.py -q`
Expected: PASS.

- [ ] **Step 6: Mutation check.** Remove the `if target.exists(): return False` guard; `test_write_plan_once_writes_then_never_overwrites` must fail. Restore.

- [ ] **Step 7: Commit** (main thread): `feat(models): plan sidecar payloads and write-once helper`.

### Task 3: `MetaWriter` writes records with `record_dict` and writes plans

**Files:**
- Modify: `helao/hexagon/adapters/native/meta_writer.py:161-215` (`write_exp`, `write_seq`)
- Modify: `helao/hexagon/app/action_host.py:492-498` (delegates)
- Test: `helao/hexagon/tests/test_native_meta_writer.py` (append)

**Interfaces:**
- Consumes: `record_dict` (Task 1); `plan_name`, `sequence_plan`, `experiment_plan`, `write_plan_once` (Task 2).
- Produces: `NativeMetaFileWriter.write_seq_plan(sequence) -> str` and
  `write_exp_plan(experiment, actions: list) -> str`, both returning the plan's
  basename whether written now or earlier; `ActionHost.write_seq_plan` /
  `ActionHost.write_exp_plan` with the same signatures.

- [ ] **Step 1: Write the failing tests** (append to `test_native_meta_writer.py`)

```python
import json

from helao.core.models.experiment import ShortExperimentModel
from helao.helpers.premodels import Experiment, Sequence


def _seq_exp_from_action():
    dump = mk_action().model_dump()
    seq = Sequence.model_validate({k: v for k, v in dump.items() if k in Sequence.model_fields})
    exp = Experiment.model_validate({k: v for k, v in dump.items() if k in Experiment.model_fields})
    return seq, exp


@pytest.mark.asyncio
async def test_write_seq_record_omits_lists_and_plan_is_stripped(tmp_path):
    save_root = str(tmp_path / "RUNS_ACTIVE")
    base = _swap(make_base(save_root), tmp_path)
    seq, _ = _seq_exp_from_action()
    seq.planned_experiments = [
        ShortExperimentModel(experiment_name="e", experiment_params={"p": 1})
    ]
    name = await base.write_seq_plan(seq)
    assert name.endswith("-seq.plan.json")
    seq_dir = os.path.join(save_root, seq.get_sequence_dir())
    plan = json.loads(open(os.path.join(seq_dir, name), encoding="utf-8").read())
    assert plan["planned"][0]["experiment_name"] == "e"
    assert "experiment_params" not in plan["planned"][0]
    await base.write_seq(seq)
    rec_file = [f for f in os.listdir(seq_dir) if f.endswith("-seq.json")][0]
    rec = read_meta(os.path.join(seq_dir, rec_file))
    assert "planned_experiments" not in rec


@pytest.mark.asyncio
async def test_write_exp_plan_is_written_once(tmp_path):
    save_root = str(tmp_path / "RUNS_ACTIVE")
    base = _swap(make_base(save_root), tmp_path)
    _, exp = _seq_exp_from_action()
    acts = [mk_action(action_name="a1"), mk_action(action_name="a2")]
    name = await base.write_exp_plan(exp, acts)
    path = os.path.join(save_root, exp.get_experiment_dir(), name)
    before = open(path, "rb").read()
    assert await base.write_exp_plan(exp, acts[:1]) == name  # a restore re-dispatch
    assert open(path, "rb").read() == before
    assert len(json.loads(before)["planned"]) == 2
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=. /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/hexagon/tests/test_native_meta_writer.py -q`
Expected: the two new tests FAIL with `AttributeError: ... has no attribute 'write_seq_plan'`.

- [ ] **Step 3: Implement**

In `meta_writer.py` add imports:

```python
from helao.core.models.plan import experiment_plan, plan_name, sequence_plan
from helao.helpers.plan_io import write_plan_once
```

Add one path helper to the writer class and use it in `write_exp`/`write_seq` (replacing their inline `save_root`/`output_path`/`output_file` blocks; behaviour unchanged):

```python
    def _record_file(self, record, kind: str) -> str:
        """``<save_root>/<record dir>/<ts>-<kind>.json``; DIAG for a manual record."""
        save_root = str(self.base.helaodirs.save_root)
        if record.manual_action:
            save_root = redirect_manual_dir(save_root)
        if kind == "seq":
            rel, stamp = record.get_sequence_dir(), record.sequence_timestamp
        else:
            rel, stamp = record.get_experiment_dir(), record.experiment_timestamp
        return os.path.join(save_root, rel, f"{stamp.strftime('%y%m%d.%H%M%S%f')}-{kind}.json")
```

In `write_exp` use `exp_dict = experiment.get_exp().record_dict()` and
`output_file = self._record_file(experiment, "exp")`; keep the existing
`os.makedirs(os.path.dirname(output_file), exist_ok=True)` behaviour if the
inline block had it. Same in `write_seq` with `record_dict()` and `"seq"`.

Add:

```python
    async def write_seq_plan(self, sequence) -> str:
        """Write ``<ts>-seq.plan.json`` once (spec §3.3); return its basename."""
        record_file = self._record_file(sequence, "seq")
        target = os.path.join(os.path.dirname(record_file), plan_name(record_file))
        await write_plan_once(
            target,
            sequence_plan(sequence.sequence_uuid, sequence.planned_experiments),
            self.base._write_meta_atomic,
            kind="seq_plan",
            owner_uuid=sequence.sequence_uuid,
        )
        return os.path.basename(target)

    async def write_exp_plan(self, experiment, actions: list) -> str:
        """Write ``<ts>-exp.plan.json`` once from staged actions; return its basename."""
        record_file = self._record_file(experiment, "exp")
        target = os.path.join(os.path.dirname(record_file), plan_name(record_file))
        await write_plan_once(
            target,
            experiment_plan(experiment.experiment_uuid, actions),
            self.base._write_meta_atomic,
            kind="exp_plan",
            owner_uuid=experiment.experiment_uuid,
        )
        return os.path.basename(target)
```

In `action_host.py` after `write_seq`:

```python
    async def write_seq_plan(self, sequence) -> str:
        """Write the sequence's write-once ``-seq.plan.json``; return its basename."""
        return await self.meta_writer.write_seq_plan(sequence)

    async def write_exp_plan(self, experiment, actions) -> str:
        """Write the experiment's write-once ``-exp.plan.json``; return its basename."""
        return await self.meta_writer.write_exp_plan(experiment, actions)
```

- [ ] **Step 4: Run**

Run: `PYTHONPATH=. /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/hexagon/tests/test_native_meta_writer.py helao/core/tests/test_artifact_hash_gate.py -q`
Expected: PASS.

- [ ] **Step 5: Mutation check.** In `write_seq`, put `clean_dict()` back; the first new test must fail. Restore.

- [ ] **Step 6: Commit** (main thread): `feat(meta_writer): records via record_dict; write-once plan sidecars`.

### Task 4: orchestrator writes plans and uploads slim metas

**Files:**
- Modify: `helao/hexagon/app/orch_dispatch.py` (sequence block ~`:820-868`, experiment block `:521-529`, `_upload_exp_meta_s3` `:690-707`)
- Test: `helao/hexagon/tests/test_seq_experiment_filing_live.py` (update + extend)

**Interfaces:**
- Consumes: `ActionHost.write_seq_plan`, `ActionHost.write_exp_plan` (Task 3); `record_dict` (Task 1).
- Produces: plan names in the runtime `aux_files` of the active sequence/experiment.

- [ ] **Step 1: Update the live test** (`test_seq_experiment_filing_live.py`). Add `import json` and `from pathlib import Path`. Replace the `filed = {...}` comprehension with:

```python
            filed = {str(u) for u in recs[su]["experiment_list"]}
            assert "planned_experiments" not in recs[su]
            assert "dispatched_experiments_abbr" not in recs[su]
```

Append at the end of `test_each_sequence_files_only_its_own_experiments`:

```python
        # plan sidecars: one per sequence and per experiment, stripped
        seq_dirs = {
            str(read_meta(p)["sequence_uuid"]): Path(p).parent
            for p in meta_glob(tmp_path, "seq", "**/*")
        }
        for s in seqs:
            sdir = seq_dirs[str(s.sequence_uuid)]
            (plan_path,) = list(sdir.glob("*-seq.plan.json"))
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            assert len(plan["planned"]) == 2
            assert all("experiment_params" not in e for e in plan["planned"])
            assert plan_path.name in recs[str(s.sequence_uuid)]["aux_files"]
        for p in meta_glob(tmp_path, "exp", "**/*"):
            d = read_meta(p)
            (plan_path,) = list(Path(p).parent.glob("*-exp.plan.json"))
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            assert {e["action_uuid"] for e in plan["planned"]} == {
                str(u) for u in d["action_list"]
            }
            assert all("action_params" not in e for e in plan["planned"])
            assert plan_path.name in d["aux_files"]
            assert "planned_actions" not in d
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=. /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/hexagon/tests/test_seq_experiment_filing_live.py -q`
Expected: FAIL with `ValueError: not enough values to unpack` on the plan glob (no plan files yet). If it fails earlier on `experiment_list`, Task 1/3 is missing.

- [ ] **Step 3: Implement** in `orch_dispatch.py`. Add one helper method on the class that owns `_upload_exp_meta_s3`:

```python
    async def _record_plan(self, record, write) -> None:
        """Write a plan sidecar and list it in ``aux_files``; never stop the run."""
        try:
            name = await write()
        except Exception:
            LOGGER.error(f"could not write plan sidecar for {record!r}", exc_info=True)
            return
        if name not in record.aux_files:
            record.aux_files.append(name)
```

Sequence block: immediately before `orch.seq_model = orch.active_sequence.get_seq()`:

```python
            await self._record_plan(
                orch.active_sequence,
                lambda: orch.write_seq_plan(orch.active_sequence),
            )
```

In the initial sequence S3 upload, replace `orch.seq_model.clean_dict(strip_private=True)` with `orch.seq_model.record_dict(strip_private=True)`.

Experiment block, between `rc, staged_acts = await self._expand_experiment_actions()` / its `rc` check and `await self._upload_exp_meta_s3()`:

```python
        await self._record_plan(
            orch.active_experiment,
            lambda: orch.write_exp_plan(orch.active_experiment, staged_acts),
        )
```

In `_upload_exp_meta_s3`, replace `orch.exp_model.clean_dict(strip_private=True)` with `orch.exp_model.record_dict(strip_private=True)`.

- [ ] **Step 4: Run**

Run: `PYTHONPATH=. /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/hexagon/tests/test_seq_experiment_filing_live.py helao/hexagon/tests/test_restore_loop_flags.py helao/hexagon/tests/test_estop_fixes.py -q`
Expected: PASS.

- [ ] **Step 5: Mutation check.** Comment out the sequence `_record_plan` call; the live test must fail on the seq plan glob. Restore.

- [ ] **Step 6: Commit** (main thread): `feat(orch): write plan sidecars; slim initial S3 metas`.

### Task 5: `MicroOrch` writes plans and slim records

**Files:**
- Modify: `helao/core/runners/micro_orch.py` (`run_experiment` after the staging loop ~`:927`; `run_sequence` after `planned = list(...)` ~`:1058`; `_write_exp` `:1355`; `_write_seq` `:1381`)
- Test: `helao/core/tests/test_micro_orch_stop.py` (update lines 185, 209, 247 and extend)

**Interfaces:**
- Consumes: Tasks 1-2.
- Produces: `MicroOrch._record_file(record, kind) -> str`, `MicroOrch._write_plan(record, payload, kind) -> None`.

- [ ] **Step 1: Update the tests.** Add `import json` and `from pathlib import Path` to `test_micro_orch_stop.py`.

Line 185: replace `assert len(rec["dispatched_actions_abbr"]) == 1` with:

```python
    assert len(rec["action_list"]) == 1
    (plan_path,) = list(Path(orch.runs[-1]["yml_path"]).parent.glob("*-exp.plan.json"))
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assert len(plan["planned"]) == 2  # both staged, one ran
    assert all("action_params" not in e for e in plan["planned"])
```

Lines 209 and 247: replace `rec["dispatched_experiments_abbr"]` with `rec["experiment_list"]` and drop the `["experiment_uuid"]` index:

```python
    uuids = [str(u) for u in rec["experiment_list"]]
```

After line 210 (`test_stop_during_sequence_aborts_sequence_and_keeps_the_experiment`) add:

```python
    (plan_path,) = list(Path(orch.runs[-1]["yml_path"]).parent.glob("*-seq.plan.json"))
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assert [e["experiment_name"] for e in plan["planned"]] == ["demo", "demo"]
    assert "planned_experiments" not in rec
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=. /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/core/tests/test_micro_orch_stop.py -q`
Expected: FAIL (`KeyError: 'action_list'` until Task 1 lands, then no plan file).

- [ ] **Step 3: Implement.** Imports:

```python
from helao.core.models.plan import experiment_plan, plan_name, sequence_plan
from helao.helpers.plan_io import write_plan_once
```

Add helpers next to `_write_exp`:

```python
    def _record_file(self, record, kind: str) -> str:
        """``<record_root>/<record dir>/<ts>-<kind>.json`` (DIAG for a manual record)."""
        root = self._record_root(manual=bool(record.manual_action))
        if kind == "seq":
            rel, stamp = record.get_sequence_dir(), record.sequence_timestamp
        else:
            rel, stamp = record.get_experiment_dir(), record.experiment_timestamp
        return os.path.join(root, rel, f"{stamp.strftime('%y%m%d.%H%M%S%f')}-{kind}.json")

    async def _write_plan(self, record, payload: dict, kind: str) -> None:
        """Write-once plan sidecar beside the record, listed in ``aux_files``."""
        record_file = self._record_file(record, kind)
        target = os.path.join(os.path.dirname(record_file), plan_name(record_file))
        owner = getattr(record, f"{'sequence' if kind == 'seq' else 'experiment'}_uuid")
        try:
            await write_plan_once(
                target, payload, self._write_meta_atomic, kind=f"{kind}_plan", owner_uuid=owner
            )
        except Exception:
            LOGGER.error(f"could not write plan sidecar {target}", exc_info=True)
            return
        name = os.path.basename(target)
        if name not in record.aux_files:
            record.aux_files.append(name)
```

Use `_record_file` inside `_write_exp`/`_write_seq` for `output_file` (behaviour
unchanged), and switch both to `record_dict()` (no `strip_private`, matching
today's `clean_dict()`).

In `run_experiment`, right after `for i, act in enumerate(actions): self._stage_action(act, order=i)`:

```python
        await self._write_plan(
            experiment, experiment_plan(experiment.experiment_uuid, actions), "exp"
        )
```

In `run_sequence`, right after `planned = list(seq_func(**supplied))`:

```python
        await self._write_plan(
            sequence, sequence_plan(sequence.sequence_uuid, planned), "seq"
        )
```

If `LOGGER` is not the module logger name in `micro_orch.py`, use the one the module already defines.

- [ ] **Step 4: Run MicroOrch suites**

Run: `PYTHONPATH=. /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/core/tests/test_micro_orch_stop.py helao/core/tests/test_micro_orch_finish.py helao/core/tests/test_micro_orch_group_state.py helao/core/tests/unit_test_micro_orch.py helao/core/tests/test_artifact_hash_gate.py -q`
Expected: PASS.

- [ ] **Step 5: Mutation check.** Remove the `run_sequence` `_write_plan` call; the sequence test must fail. Restore.

- [ ] **Step 6: Commit** (main thread): `feat(micro_orch): plan sidecars and slim records`.

### Task 6: `s3_upload` ships plans and strips lists from legacy local records

**Files:**
- Modify: `helao/core/hooks/builtin/s3_upload.py:229-250`
- Modify: `CLAUDE.md` ("Data and state on disk": one bullet)
- Test: `helao/core/tests/test_sync_postfinish_chain.py` (append; add `exp_meta` to the `sync_fixtures` import)

**Interfaces:**
- Consumes: `record_dict` (Task 1).
- Produces: S3 keys `experiment/{uuid}.plan.json`, `sequence/{uuid}.plan.json`.

- [ ] **Step 1: Write the failing tests**

```python
def _capture(drv, sent):
    async def capture(msg=None, target=None, compress=False, retries=5):
        sent.append((target, msg))
        return True

    drv.to_s3 = capture


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_experiment_push_strips_lists_and_ships_plan_first(tmp_path, mod):
    drv = make_sync_driver(
        tmp_path, mod.SyncDriver, postfinish_hooks={"experiment": {"s3_upload": ["*"]}}
    )
    try:
        sent = []
        _capture(drv, sent)
        _no_requeue(drv)
        uuid = mk_uuid(1)
        exp_yml = make_exp_tree(tmp_path, "RUNS", uuid)
        plan = exp_yml.parent / f"{ts(0)}-exp.plan.json"
        plan.write_text('{"file_type": "experiment_plan", "planned": []}\n', encoding="utf-8")
        write_yml(
            exp_yml,
            {
                **exp_meta(uuid),
                "aux_files": [plan.name],
                "planned_actions": [{"action_name": "legacy"}],
                "dispatched_actions_abbr": [{"action_uuid": mk_uuid(2)}],
            },
        )
        await asyncio.wait_for(drv.sync_yml(yml_path=exp_yml, rank=1), timeout=15)
        targets = [t for t, _ in sent]
        assert targets.index(f"experiment/{uuid}.plan.json") < targets.index(
            f"experiment/{uuid}.json"
        )
        by_target = dict(sent)
        assert Path(by_target[f"experiment/{uuid}.plan.json"]) == plan
        meta = by_target[f"experiment/{uuid}.json"]
        assert "planned_actions" not in meta and "dispatched_actions_abbr" not in meta
    finally:
        await teardown_driver(drv)


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_missing_plan_file_does_not_block_the_meta_push(tmp_path, mod):
    drv = make_sync_driver(
        tmp_path, mod.SyncDriver, postfinish_hooks={"experiment": {"s3_upload": ["*"]}}
    )
    try:
        sent = []
        _capture(drv, sent)
        _no_requeue(drv)
        uuid = mk_uuid(1)
        exp_yml = make_exp_tree(tmp_path, "RUNS", uuid)
        write_yml(exp_yml, {**exp_meta(uuid), "aux_files": [f"{ts(0)}-exp.plan.json"]})
        await asyncio.wait_for(drv.sync_yml(yml_path=exp_yml, rank=1), timeout=15)
        targets = [t for t, _ in sent]
        assert f"experiment/{uuid}.json" in targets
        assert f"experiment/{uuid}.plan.json" not in targets
    finally:
        await teardown_driver(drv)
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=. /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/core/tests/test_sync_postfinish_chain.py -q`
Expected: first new test FAILS (`ValueError: 'experiment/...plan.json' is not in list`).

- [ ] **Step 3: Implement** in `s3_upload.py`. Replace
`meta = MOD_MAP[prog.yml.type](**patched_meta).clean_dict(strip_private=True)` with
`meta = MOD_MAP[prog.yml.type](**patched_meta).record_dict(strip_private=True)`.
Inside `if not prog.s3_done or force_s3:`, after `uuid_key = ...` and before the
meta `to_s3`:

```python
            # plan sidecars named in aux_files go up first (spec §3.3); a
            # missing one is reported, never retried forever
            if prog.yml.type in ("experiment", "sequence"):
                for name in meta.get("aux_files") or []:
                    if not str(name).endswith(".plan.json"):
                        continue
                    plan_path = prog.yml.targetdir / name
                    if not plan_path.is_file():
                        LOGGER.warning(
                            f"plan sidecar {name} named by {prog.yml.target.name} "
                            "is not on disk; skipped"
                        )
                        continue
                    plan_key = f"{prog.yml.type}/{uuid_key}.plan.json"
                    if not await syncer.to_s3(plan_path, plan_key):
                        raise RuntimeError(f"Failed to upload {plan_key}")
```

`CLAUDE.md`, under "Data and state on disk", after the "Record format" bullet, add:

```markdown
- Sequence and experiment records do not carry `planned_*` or `dispatched_*_abbr` (spec `docs/superpowers/specs/2026-11-24-record-schema-slimming-design.md`): every writer goes through `HelaoDict.record_dict()`. They carry `experiment_list` / `action_list` (dispatched uuids) instead, and a write-once `<ts>-seq.plan.json` / `<ts>-exp.plan.json` beside the record (named in `aux_files`, shipped to `<kind>/{uuid}.plan.json`) holds the stripped plan.
```

- [ ] **Step 4: Run** the chain suite plus `test_s3_upload_parquet_failure.py` and `test_sync_postfinish_golden.py`.
Expected: PASS. If the golden test fails only because records lost the four lists, regenerate nothing: update its expected dict to drop those keys and add `experiment_list`/`action_list` where its fixture dispatched items, and say so in the report.

- [ ] **Step 5: Mutation check.** Revert `record_dict` to `clean_dict` in the hook; the first new test must fail on `planned_actions`. Restore.

- [ ] **Step 6: Commit** (main thread): `feat(s3_upload): ship plan sidecars; strip record lists on push`.

### Task 6b: Deployment-C tests that read the dropped lists

**Files:** Deployment-C repo: six converters and three tests, listed in its addendum.

**Interfaces:** Consumes Task 1 (`experiment_list`, `action_list`).

- [ ] **Step 1:** Run each listed test; confirm it fails on a missing list key.
- [ ] **Step 2:** Apply the replacement each addendum row gives (read `experiment_list` / `action_list` instead of the dropped list; where the converter sets only `planned_*`, the addendum says which converter line also sets `dispatched_*_abbr`).
- [ ] **Step 3:** Run the Deployment-C `scripts/*/tests` and `tests/` suites. Expected: PASS.
- [ ] **Step 4: Commit** in the Deployment-C repo on `feat/record-schema-slimming` (main thread).

---

## Part 2 — `action_params` holds inputs only

### Task 7: `set_output`, executor-start snapshot, finish-time guard, single-writer sweep

**Files:**
- Modify: `helao/core/models/action.py` (`ActionModel`, after line 169)
- Modify: `helao/hexagon/app/action_session.py` (`__init__`, new method)
- Modify: `helao/hexagon/app/executor_runner.py:87-88`
- Modify: `helao/hexagon/adapters/native/finalizer.py` (`_finish`, before the `write_act` loop at ~`:398`)
- Modify: `helao/hexagon/app/action_host.py:1518`
- Test: `helao/hexagon/tests/test_action_output.py` (create), `helao/core/tests/test_action_output_single_writer.py` (create)

**Interfaces:**
- Produces: `ActionModel.set_output(**values) -> None`;
  `ActionSession.set_output(**values) -> None`;
  `ActionSession.params_snapshot: Optional[dict]` (None until an executor starts).

- [ ] **Step 1: Write the failing tests** — `helao/hexagon/tests/test_action_output.py`:

```python
"""set_output and the params guard (spec §4.2, §4.7)."""

import asyncio
import logging

import pytest

import helao.hexagon.adapters.native.finalizer as native_finalizer_mod
from helao.core.models.hlostatus import HloStatus
from helao.hexagon.tests.native_fixtures import make_base, mk_action, mk_active


async def _no_move(action, base=None):
    pass


async def _session(tmp_path, **over):
    base = make_base(str(tmp_path / "RUNS_ACTIVE"))
    active, _ = mk_active(base, action=mk_action(**over) if over else None)
    base.actives[active.action.action_uuid] = active
    base.aloop = asyncio.get_running_loop()
    active.data_logger = base.aloop.create_task(active.log_data_task())
    await asyncio.sleep(0.05)
    return base, active


def test_action_model_set_output_merges():
    a = mk_action()
    a.set_output(x=1)
    a.set_output(y=2, x=3)
    assert a.action_output == {"x": 3, "y": 2}


@pytest.mark.asyncio
async def test_session_set_output_targets_the_running_split(tmp_path, monkeypatch):
    monkeypatch.setattr(native_finalizer_mod, "move_dir", _no_move)
    _, active = await _session(tmp_path)
    prev_uuid = active.action.action_uuid
    await active.split(uuid_list=[])
    active.set_output(after_split=1)
    prev = next(a for a in active.action_list if a.action_uuid == prev_uuid)
    assert active.action.action_output["after_split"] == 1
    assert "after_split" not in prev.action_output
    active.data_logger.cancel()
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_session_set_output_on_finished_action_warns(tmp_path, caplog):
    _, active = await _session(tmp_path)
    active.action.action_status = [HloStatus.finished]
    with caplog.at_level(logging.WARNING):
        active.set_output(late=1)
    assert active.action.action_output["late"] == 1
    assert "late" in caplog.text and "finished" in caplog.text
    active.data_logger.cancel()
    await asyncio.sleep(0.05)


class _Probe:
    concurrent = True

    def __init__(self, active):
        self.active = active
        self.seen = None

    async def _pre_exec(self):
        self.seen = dict(self.active.params_snapshot)
        raise RuntimeError("probe stops here")


@pytest.mark.asyncio
async def test_snapshot_is_taken_at_executor_start(tmp_path):
    _, active = await _session(tmp_path, action_params={"a": 1})
    assert active.params_snapshot is None
    active.action.action_params["normalized_after_begin"] = 2
    probe = _Probe(active)
    try:
        await active.executor_runner.action_loop_task(probe)
    except RuntimeError as exc:  # the loop may re-raise or record the setup failure
        assert "probe" in str(exc)
    assert probe.seen == {"a": 1, "normalized_after_begin": 2}
    active.data_logger.cancel()
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_finish_warns_on_params_written_after_executor_start(
    tmp_path, monkeypatch, caplog
):
    monkeypatch.setattr(native_finalizer_mod, "move_dir", _no_move)
    _, active = await _session(tmp_path, action_params={"keep": 1, "changed": 1})
    active.params_snapshot = dict(active.action.action_params)
    active.action.action_params["changed"] = 2
    active.action.action_params["added"] = 3
    with caplog.at_level(logging.WARNING):
        await active.finish()
    msgs = [r.getMessage() for r in caplog.records if "wrote action_params" in r.getMessage()]
    assert len(msgs) == 1
    assert "added" in msgs[0] and "changed" in msgs[0] and "keep" not in msgs[0]
    assert "set_output" in msgs[0]


@pytest.mark.asyncio
async def test_finish_is_silent_without_snapshot_or_changes(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(native_finalizer_mod, "move_dir", _no_move)
    _, active = await _session(tmp_path, action_params={"keep": 1})
    active.action.action_params["added_no_executor"] = 1  # no snapshot: unguarded
    with caplog.at_level(logging.WARNING):
        await active.finish()
    assert "wrote action_params" not in caplog.text
```

`helao/core/tests/test_action_output_single_writer.py`:

```python
"""Only ActionModel.set_output writes action_output (spec §4.2)."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ALLOWED = {("helao/core/models/action.py", "set_output")}


def _hits(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    scopes = {}
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for node in ast.walk(fn):
                scopes.setdefault(id(node), fn.name)
    for node in ast.walk(tree):
        bad = False
        if isinstance(node, (ast.Assign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                base = t.value if isinstance(t, ast.Subscript) else t
                if isinstance(base, ast.Attribute) and base.attr == "action_output":
                    bad = True
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            owner = node.func.value
            if (
                node.func.attr in {"update", "setdefault", "pop", "clear"}
                and isinstance(owner, ast.Attribute)
                and owner.attr == "action_output"
            ):
                bad = True
        if bad:
            yield node.lineno, scopes.get(id(node), "<module>")


def test_action_output_has_one_writer():
    found = []
    for path in sorted((ROOT / "helao").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if "/tests/" in rel or "/notes/" in rel:
            continue
        for line, scope in _hits(path):
            if (rel, scope) not in ALLOWED:
                found.append(f"{rel}:{line} ({scope})")
    assert not found, "write action_output via set_output:\n" + "\n".join(found)
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=. /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/hexagon/tests/test_action_output.py helao/core/tests/test_action_output_single_writer.py -q`
Expected: FAIL — `AttributeError: 'Action' object has no attribute 'set_output'`, and the sweep lists `helao/hexagon/app/action_host.py:1518`.

- [ ] **Step 3: Implement**

`helao/core/models/action.py`, in `ActionModel`:

```python
    def set_output(self, **values) -> None:
        """Merge produced values into ``action_output``; its only writer (spec §4.2)."""
        self.action_output.update(values)
```

`action_session.py`, in `__init__` next to `self.manual_stop = False`:

```python
        #: ``action_params`` as of executor start; the finalizer warns on later
        #: writes (spec §4.7). None for actions that never start an executor.
        self.params_snapshot: Optional[dict] = None
```

(import `Optional` if missing) and a method near `finish`:

```python
    def set_output(self, **values) -> None:
        """Record produced values on the running split (spec §4.2)."""
        if HloStatus.finished in self.action.action_status:
            LOGGER.warning(
                f"set_output({sorted(values)}) on finished action "
                f"{self.action.action_name} ({self.action.action_uuid}); "
                "its record may already be written"
            )
        self.action.set_output(**values)
```

`executor_runner.py`, immediately before `setup_state = await executor._pre_exec()`:

```python
        self.active.params_snapshot = deepcopy(self.active.action.action_params)
```

(add `from copy import deepcopy`).

`finalizer.py`: add a method and call it right before the `for action in self.active.action_list:` loop that calls `write_act`:

```python
    def _warn_param_writes(self) -> None:
        """Warn on action_params keys added or changed after executor start (spec §4.7)."""
        snap = self.active.params_snapshot
        if snap is None:
            return
        for action in self.active.action_list:
            changed = []
            for k, v in action.action_params.items():
                try:
                    same = k in snap and bool(snap[k] == v)
                except Exception:
                    same = False
                if not same:
                    changed.append(k)
            if changed:
                LOGGER.warning(
                    f"action {action.action_name} ({action.action_uuid}) wrote "
                    f"action_params keys {sorted(changed)} during the run; produced "
                    "values belong in action_output via ActionSession.set_output"
                )
```

`action_host.py:1518`: replace the `action.action_output["error_message"] = (...)` assignment with `action.set_output(error_message=(...))`, keeping the message text.

- [ ] **Step 4: Run**

Run the two new files plus `helao/hexagon/tests/test_native_finalizer.py helao/hexagon/tests/test_action_session_port.py -q`.
Expected: PASS.

- [ ] **Step 5: Mutation checks.** (a) Make `ActionSession.set_output` write `self.action_list[0].set_output(...)`; the split test must fail. (b) Move the snapshot line to `ActionSession.__init__`; `test_snapshot_is_taken_at_executor_start` must fail. Restore both.

- [ ] **Step 6: Commit** (main thread): `feat(action): set_output single writer; executor-start params guard`.

### Task 8: one `to_global_params` resolver, output first

**Files:**
- Create: `helao/helpers/global_exports.py`
- Modify: `helao/hexagon/app/orch_global_params.py:65-100` (`collect_to_globals`)
- Modify: `helao/hexagon/adapters/native/finalizer.py:280-305`
- Modify: `helao/core/runners/micro_orch.py:1236-1255` (`_capture_to_global`)
- Modify: `helao/hexagon/app/orch_host.py:726` (`add_global_param`)
- Test: `helao/hexagon/tests/test_global_params.py` (update + add)

**Interfaces:**
- Produces: `resolve_global_exports(to_global_params, action_params: dict, action_output: dict) -> dict`.

- [ ] **Step 1: Update/add tests** in `test_global_params.py`. Rename `test_collect_to_globals_list_form_params_precede_output` to `test_collect_to_globals_list_form_output_precedes_params` and change its expectation to `{"x": 1, "y": 2, "shared": "from_output"}`. Add:

```python
from helao.helpers.global_exports import resolve_global_exports


def test_resolver_prefers_output_and_renames():
    assert resolve_global_exports(
        {"k": "renamed", "only_p": "p2"}, {"k": "stale_input", "only_p": 1}, {"k": "result"}
    ) == {"renamed": "result", "p2": 1}


def test_resolver_ignores_missing_and_bad_shapes():
    assert resolve_global_exports(["absent"], {}, {}) == {}
    assert resolve_global_exports(None, {"a": 1}, {}) == {}
```

- [ ] **Step 2: Run to verify failure** — `ModuleNotFoundError: helao.helpers.global_exports` and the renamed test asserting `from_output`.

- [ ] **Step 3: Implement** `helao/helpers/global_exports.py`:

```python
"""``to_global_params`` resolution shared by the orchestrator, the finalizer and MicroOrch."""

__all__ = ["resolve_global_exports"]

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


def resolve_global_exports(to_global_params, action_params: dict, action_output: dict) -> dict:
    """Values named by ``to_global_params``, ``action_output`` first (spec §4.5).

    Output first: an action may write a result under the name of one of its
    inputs (``calc_server``'s ``min_offset_ocv``), and params-first would
    export the stale input. A list exports under the same name; a dict maps
    source -> global name.
    """
    if isinstance(to_global_params, list):
        pairs = [(k, k) for k in to_global_params]
    elif isinstance(to_global_params, dict):
        pairs = list(to_global_params.items())
    else:
        return {}
    out = {}
    for src, dst in pairs:
        if src in action_output:
            out[dst] = action_output[src]
        elif src in action_params:
            out[dst] = action_params[src]
        else:
            LOGGER.info(f"key {src} not found in action output or params")
    return out
```

`collect_to_globals`: keep the identity guard verbatim; replace both branches with:

```python
    exports = resolve_global_exports(
        result_action.to_global_params,
        result_action.action_params,
        result_action.action_output,
    )
    for k in exports:
        LOGGER.info(f"updating {k} in global vars")
    global_params.update(exports)
```

`finalizer.py`: replace the `export_params = {}` + list/dict branches with
`export_params = resolve_global_exports(action.to_global_params, action.action_params, action.action_output)`;
keep the `if export_params:` dispatch and its comment.

`micro_orch._capture_to_global`: keep the first guard line; replace the rest with:

```python
        self.global_params.update(
            resolve_global_exports(
                to_global_params,
                result.get("action_params") or {},
                result.get("action_output") or {},
            )
        )
```

`orch_host.py:726`: replace `active.action.action_params.update(pdict)` with `active.set_output(**pdict)`.

- [ ] **Step 4: Run** `test_global_params.py`, `test_native_finalizer.py` (its `test_finish_exports_global_params` still passes: `gain` is only in params), `unit_test_micro_orch.py`, `test_action_output_single_writer.py`. Expected: PASS.

- [ ] **Step 5: Mutation check.** Swap the two `if` branches in the resolver; `test_resolver_prefers_output_and_renames` must fail. Restore.

- [ ] **Step 6: Commit** (main thread): `refactor(globals): one output-first to_global_params resolver`.

### Task 9: `hte` output sites (hte repo)

**Files (hte repo, `helao/deploy/hte/`):** `servers/{calc,andor,sample,syringe,gamry,biologic,spec,mfc,co2sensor,xafs,galil_motion}/...` as listed; their `tests/`.

**Interfaces:** Consumes `ActionSession.set_output` (Task 7) and the output-first resolver (Task 8). The parent tasks must be merged into the working tree first.

Rewrite rule: `X.action.action_params["k"] = v` → `X.set_output(k=v)`;
`X.action.action_params[f"..."] = v` → `X.set_output(**{f"...": v})`;
`X.action.action_params.update({...})` → `X.set_output(**{...})`, where `X` is
`active` or `self.active`. Where only a bare `action = self.active.action` is in
scope, call `self.active.set_output(...)`.

| file:line (current) | current write | replacement |
|---|---|---|
| `servers/calc/calc_server.py:261` | `active.action.action_params["min_offset_ocv"] = result` | `active.set_output(min_offset_ocv=result)` |
| `servers/calc/calc_server.py:312` | `...["CP_Ewe_V__mean_final"] = limted_Ewe_V__mean_final` | `active.set_output(CP_Ewe_V__mean_final=limted_Ewe_V__mean_final)` |
| `servers/andor/andor_server.py:224` | `self.active.action.action_params["action_path"] = str(...)` | `self.active.set_output(action_path=str(...))` |
| `servers/andor/andor_server.py:392` | `active.action.action_params["calibrated"] = bool(...)` | `active.set_output(calibrated=bool(...))`; change the read at `:395` to `active.action.action_output["calibrated"]` and rewrite the comment that says it is deliberately in params |
| `servers/sample/sample_server.py:124`, `:625` | `.update({"_fast_samples_in": [sample.as_dict()]})` | `active.set_output(_fast_samples_in=[sample.as_dict()])` |
| `servers/sample/sample_server.py:594-596` | three `.update({"_unloaded_*": ...})` | one `active.set_output(_unloaded_solid=..., _unloaded_liquid=..., _unloaded_liquid_vol=...)` |
| `servers/sample/sample_server.py:841` | `["_fast_sample_out"] = sample_out_dicts[0]` | `active.set_output(_fast_sample_out=sample_out_dicts[0])` |
| `servers/sample/sample_server.py:930` | `.update({...})` | `active.set_output(**{...})` |
| `servers/syringe/syringe_server.py:117` | `.update({"_present_volume_ul": present_volume})` | `active.set_output(_present_volume_ul=present_volume)` |
| `servers/gamry/gamry_server2.py:393` | `[f"{k}__mean_final"] = meanv` | `self.active.set_output(**{f"{k}__mean_final": meanv})` |
| `servers/gamry/gamry_server2.py:408` | `["has_bubble"] = has_bubble` | `self.active.set_output(has_bubble=has_bubble)` |
| `servers/biologic/biologic_server.py:325`, `:340` | same two as gamry | same two replacements |
| `servers/spec/spec_server.py:294` | `["peak_intensity"] = specdict.get(...)` | `active.set_output(peak_intensity=specdict.get(...))` |
| `servers/spec/spec_server.py:371-373` | `spec_params = active.action.action_params; spec_params.update({"int_time_ms": current_int_time}); specdict = app.driver.acquire_spec_adv(**spec_params)` | `specdict = app.driver.acquire_spec_adv(**{**active.action.action_params, "int_time_ms": current_int_time})` (input no longer overwritten) |
| `servers/spec/spec_server.py:379-380` | `peak_intensity`, `calibrated_int_time_ms` | one `active.set_output(peak_intensity=peak_int, calibrated_int_time_ms=current_int_time)` |
| `servers/mfc/alicat_driver.py:593`, `:752`, `:916` | `["total_scc"] = self.total_scc` | `self.active.set_output(total_scc=self.total_scc)` |
| `servers/co2sensor/sprintir_driver.py:305` | `["mean_co2_ppm"] = (...)` | `self.active.set_output(mean_co2_ppm=(...))` |
| `servers/xafs/xafs_server.py:106`, `:231`, `:235`, `:240`, `:335`, `:350` | `["sidecar_error"] = ...` | `self.active.set_output(sidecar_error=...)` |
| `servers/xafs/xafs_server.py:347` | `action.action_params[k] = final["state" if k == "scan_state" else k]` | `self.active.set_output(**{k: final["state" if k == "scan_state" else k]})` |
| `servers/xafs/xafs_server.py:357` | `["exd_path"] = final["exd_path"]` | `self.active.set_output(exd_path=final["exd_path"])` |
| `servers/xafs/xafs_server.py:393` | `action.action_params.update(arts.data["metadata"])` | `self.active.set_output(**arts.data["metadata"])` |
| `servers/galil_motion/galil_motion.py:493` | `.update({"_platexy": platexy})` | `active.set_output(_platexy=platexy)` |
| `servers/galil_motion/galil_motion.py:511` | `.update({"_refxy": refxy})` | `active.set_output(_refxy=refxy)` |
| `servers/galil_motion/galil_motion.py:558` | `.update({"_refno": refno, "_refxy": refxy})` | `active.set_output(_refno=refno, _refxy=refxy)` |

Not changed (input normalization, spec §4.4): `biologic_server.py:430-775` `AcqInterval__*`/`Cycles`, `gamry_server2.py:1147-1148`, `galil_motion.py:349,617`, `galil_io.py`, `nidaqmx_server.py`, `sample_server.py:438`.

- [ ] **Step 1:** Repo check (Global Constraints), branch `feat/record-schema-slimming` from the hte default branch.
- [ ] **Step 2:** Run the hte tests that assert these keys in `action_params` and confirm they still pass before the edit (baseline): `tests/test_get_loaded_positions.py`, `tests/test_low_w3_hte_fixes.py`, `servers/xafs/tests/test_xafs_server.py`, `servers/andor/tests/test_andor_acquire_guard.py` (use `find helao/deploy/hte -name <file>` for exact paths).
- [ ] **Step 3:** Change each of those assertions from `action_params[...]` to `action_output[...]` for the moved keys only. Run: they FAIL now (code not moved yet).
- [ ] **Step 4:** Apply the table. Run `rg -n 'action_params\[[^]]+\]\s*=[^=]|action_params\.update\(' helao/deploy/hte/servers` and confirm every remaining hit is in the "Not changed" list.
- [ ] **Step 5:** Run every test under `helao/deploy/hte` with `python run_tests.py --filter deploy/hte` (from the parent root). Expected: no new failures against the baseline. Run `helao/core/tests/test_action_output_single_writer.py`. Expected: PASS.
- [ ] **Step 6:** If `servers/<x>/README.md` `## Outputs` tables list any moved key as an `action_params` field, update its location to `action_output` (output catalog rule; `helao-output-catalog` skill).
- [ ] **Step 7: Mutation check.** Revert one row at a time for `sample_server.py:930` (`_positions`, asserted by `test_get_loaded_positions.py:64`) and `xafs_server.py:347` (`scan_state`, asserted in `test_xafs_server.py`); each must fail its test. The output-first rule for the calc clash keys is pinned by Task 8's resolver test; record in the report which other rows no hte test covers.
- [ ] **Step 8: Commit** in hte (main thread): `refactor(servers): produced values via set_output`.

### Task 10: `test` deployment sims (parent repo)

**Files:** `helao/deploy/test/servers/cpsim/cpsim_server.py:100,114`, `cpsim_driver.py:226`, `helao/deploy/test/servers/gpsim/gpsim_server.py:92,113`.

| site | replacement |
|---|---|
| `cpsim_server.py:100` `.update({f"_{k}": v for k, v in data_dict.items()})` | `active.set_output(**{f"_{k}": v for k, v in data_dict.items()})` |
| `cpsim_server.py:114` `["_loaded_plate_id"] = loaded_plate_id` | `active.set_output(_loaded_plate_id=loaded_plate_id)` |
| `cpsim_driver.py:226` `self.active.action.action_params["mean_eta_vrhe"] = calc_eta(self.cp)` | `self.active.set_output(mean_eta_vrhe=calc_eta(self.cp))` |
| `gpsim_server.py:92` `.update({f"_{k}": v for k, v in progress.items()})` | `active.set_output(**{f"_{k}": v for k, v in progress.items()})` |
| `gpsim_server.py:113` `["_feature"] = data["feature"]` | `active.set_output(_feature=data["feature"])` |

`gpsim_server.py:124` (`orch_str`) stays: it is built before the executor.

- [ ] **Step 1:** Baseline: `python run_tests.py --filter deploy/test`.
- [ ] **Step 2:** Apply the table.
- [ ] **Step 3:** Re-run; expected no new failures. `unit_test_oersim_params.py` still resolves `_loaded_plate_id`/`_feature` through the resolver.
- [ ] **Step 4: Mutation check.** Point the resolver back at params-only for one run; an OERSIM global-param test must fail. If none does, add `helao/deploy/test/tests/test_sim_outputs.py` asserting `active.action.action_output["_feature"]` after the gpsim acquire body.
- [ ] **Step 5: Commit** (main thread, parent repo): `refactor(test-sims): produced values via set_output`.

### Task 11: Deployment-E spectrometer server and processor (Deployment-E repo)

**Files:** listed in the Deployment-E addendum.

**Interfaces:** Consumes Tasks 7-8.

- [ ] **Step 1:** Repo check, branch.
- [ ] **Step 2:** Baseline the addendum's test files.
- [ ] **Step 3:** Update the addendum's test assertions (`action_params` → `action_output` for moved keys). Run: FAIL.
- [ ] **Step 4:** Apply the addendum's site table, including the pre-session `A.set_output(int_time_ignored=...)` with the local-variable read-back, and the processor's output-first reader.
- [ ] **Step 5:** Run every test under the repo. Expected: no new failures. Run the parent's `test_action_output_single_writer.py`. Expected: PASS.
- [ ] **Step 6: Mutation check** given in the addendum.
- [ ] **Step 7: Commit** in the Deployment-E repo (main thread).

### Task 12: Deployment-A servers (Deployment-A repo)

Same steps as Task 11, against the Deployment-A addendum (potentiostat, motion, DI server, mux valve). The mux valve rows keep the requested input untouched and publish the resolved identifiers with `set_output`; the addendum names the in-function reads that must switch to the local variables.

- [ ] **Step 1:** Repo check, branch.
- [ ] **Step 2:** Baseline the addendum's tests.
- [ ] **Step 3:** Update assertions; run: FAIL.
- [ ] **Step 4:** Apply the addendum table.
- [ ] **Step 5:** Run the repo's tests and the single-writer sweep. Expected: PASS / no new failures.
- [ ] **Step 6: Mutation check** given in the addendum.
- [ ] **Step 7: Commit** (main thread).

### Task 13: Deployment-C analysis reader (Deployment-C repo)

- [ ] **Step 1:** Write the addendum's failing test (a new-shape record with `scan_state` only in `action_output` must not be dropped).
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Apply the addendum's reader change (output first, params fallback).
- [ ] **Step 4:** Run the analysis tests; old-shape fixtures still pass.
- [ ] **Step 5: Mutation check:** drop the output lookup; the new test fails.
- [ ] **Step 6: Commit** (main thread; may share the Task 6b branch).

---

## Part 3 — hook provenance (parent repo)

### Task 14: `prefinish_hooks`

**Files:**
- Modify: `helao/core/models/action.py`, `experiment.py`, `sequence.py` (field next to `prefinish_errors`)
- Modify: `helao/core/hooks/prefinish.py:26-28`
- Modify: `helao/hexagon/app/orch_persist.py:64-80` (`_RUNTIME_ACTION_FIELDS`)
- Test: `helao/core/tests/test_hooks_prefinish.py` (append)

**Interfaces:** Produces `prefinish_hooks: list[str]` on `ActionModel`, `ExperimentModel`, `SequenceModel`.

- [ ] **Step 1: Write the failing tests**

```python
def test_prefinish_hooks_default_is_omitted_from_clean_dict():
    for model in (
        Action(action_name="a"),
        Experiment(experiment_name="e"),
        Sequence(sequence_name="s"),
    ):
        assert model.prefinish_hooks == []
        assert "prefinish_hooks" not in model.clean_dict()


@pytest.mark.asyncio
async def test_prefinish_hooks_lists_every_hook_that_ran_failures_included():
    hs = HookSet(
        cfg={"ok": {"*": None}, "boom": {"*": None}, "skip": {"other": None}},
        hooks={"ok": _Ok([], "ok"), "boom": _Boom(), "skip": _Ok([], "skip")},
    )
    exp = _exp()
    await run_prefinish(hs, exp, "exp1", Path("/tmp/x"), server=object())
    assert exp.prefinish_hooks == ["ok", "boom"]
    assert [e["hook"] for e in exp.prefinish_errors] == ["boom"]
```

- [ ] **Step 2: Run** `test_hooks_prefinish.py`. Expected: FAIL, `AttributeError: ... 'prefinish_hooks'`.

- [ ] **Step 3: Implement.** In each of the three models, next to `prefinish_errors`:

```python
    # Pre-finish hooks that ran on this record, failures included (record
    # schema spec §5.1). clean_dict drops the empty default.
    prefinish_hooks: list[str] = Field(default=[])
```

In `run_prefinish`, as the first line inside `for hook_name, hook, args in hook_set.select(name):`:

```python
        record.prefinish_hooks.append(hook_name)
```

In `_RUNTIME_ACTION_FIELDS`, add `"prefinish_hooks",` after `"prefinish_errors",`.

- [ ] **Step 4: Run** `test_hooks_prefinish.py`, `test_prefinish_action.py`, `test_micro_orch_finish.py`, and the queue-pickle tests (`find helao -name "*queue*pck*test*.py" -o -name "test_*persist*.py"`). Expected: PASS.

- [ ] **Step 5: Mutation check.** Move the append after the `try/except`, inside the success path only; the `["ok", "boom"]` test must fail. Restore.

- [ ] **Step 6: Commit** (main thread): `feat(hooks): record pre-finish hook names`.

### Task 15: `postfinish_hooks` stamped on the S3 meta

**Files:**
- Modify: the three models (field next to `prefinish_hooks`)
- Modify: `helao/core/hooks/builtin/s3_upload.py` (before the `MOD_MAP[...]` line)
- Test: `helao/core/tests/test_sync_postfinish_chain.py` (append)

**Interfaces:** Consumes Task 6's `_capture` helper. Produces `postfinish_hooks: list[str]` on the S3 meta only.

- [ ] **Step 1: Write the failing test**

```python
OK_HOOK = """
from helao.core.hooks import FinishHook
class Hook(FinishHook):
    blocking = False
    phase = "postfinish"
    async def run(self, ctx):
        return None
"""


@pytest.mark.parametrize("mod", MODS)
@pytest.mark.asyncio
async def test_s3_meta_names_the_selected_chain_and_local_record_is_untouched(
    tmp_path, mod
):
    ok = _hook_file(tmp_path, "ok_hook", OK_HOOK)
    drv = make_sync_driver(
        tmp_path,
        mod.SyncDriver,
        postfinish_hooks={"experiment": {"s3_upload": ["*"], ok: ["*"]}},
    )
    try:
        sent = []
        _capture(drv, sent)
        _no_requeue(drv)
        uuid = mk_uuid(1)
        exp_yml = make_exp_tree(tmp_path, "RUNS", uuid)
        before = exp_yml.read_bytes()
        await asyncio.wait_for(drv.sync_yml(yml_path=exp_yml, rank=1), timeout=15)
        meta = dict(sent)[f"experiment/{uuid}.json"]
        assert meta["postfinish_hooks"] == ["s3_upload", ok]
        assert exp_yml.read_bytes() == before
    finally:
        await teardown_driver(drv)
```

- [ ] **Step 2: Run.** Expected: FAIL, `KeyError: 'postfinish_hooks'`.

- [ ] **Step 3: Implement.** Field on each model:

```python
    # Post-finish chain SYNC selected for this record; set on the S3 meta only,
    # never on the local record (record schema spec §5.2).
    postfinish_hooks: list[str] = Field(default=[])
```

In `s3_upload.py`, right after `patched_meta = {MOD_PATCH.get(k, k): v ...}`:

```python
        level = prog.yml.type
        if level in syncer.postfinish:
            chain_name = prog.yml.meta.get(f"{level}_name", "NA")
            patched_meta["postfinish_hooks"] = [
                hook_name for hook_name, _, _ in syncer.postfinish[level].select(chain_name)
            ]
```

- [ ] **Step 4: Run** the chain suite and `test_sync_postfinish_golden.py`. Expected: PASS (update the golden's expected S3 meta to include `postfinish_hooks` if it compares S3 bodies; say so in the report).

- [ ] **Step 5: Mutation check.** Write the list into `prog.yml.meta` instead and persist it; the byte-identity assertion must fail. Restore.

- [ ] **Step 6: Commit** (main thread): `feat(s3_upload): stamp selected post-finish chain on S3 meta`.

---

## Task 16: whole-tree gate and handoff

- [ ] **Step 1:** Baseline already exists? If not, record one first on `unstable` in the job dir. Start the sweep and its watcher as two separate background commands (rule `background-sweep-watchers.md`):

```bash
D=$CLAUDE_JOB_DIR/sweep; mkdir -p $D
( cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=. /home/dan/miniforge3/envs/helao/bin/python run_tests.py > "$D/run.log" 2>&1; echo $? > "$D/done" )
```

```bash
D=$CLAUDE_JOB_DIR/sweep; for i in $(seq 1 720); do [ -f "$D/done" ] && break; sleep 15; done; echo "rc=$(cat "$D/done" 2>/dev/null || echo TIMEOUT)"; tail -20 "$D/run.log"
```

- [ ] **Step 2:** Compare the failing set with the baseline. Any new failure: diagnose before continuing (check nested-repo WIP first).
- [ ] **Step 3:** `pyright` on the changed parent files (not under `.claude/worktrees/`).
- [ ] **Step 4:** Privacy check on tracked parent changes: `git -C <parent> diff unstable --name-only | xargs grep -nwiE "<private names>"` must print nothing (the main thread supplies the names).
- [ ] **Step 5:** Request a whole-branch review (`superpowers:requesting-code-review`), separate privacy audit by the reviewer role.
- [ ] **Step 6:** Report: branches per repo, commits, sweep result vs baseline. Push only on owner approval, parent first, then hte, test (parent), Deployment-E, Deployment-A, Deployment-C. Station rule: update a station's orchestrator and action servers together.
- [ ] **Step 7 (after deploy, owner-run):** For one real station sequence, report `sequence/{uuid}.json` byte size before and after in the PR (spec acceptance).
