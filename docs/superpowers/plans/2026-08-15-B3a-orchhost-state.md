# B3a — `OrchHost` construction, state and queue surface: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `OrchHost` — the hexagon-native orchestrator server — up to but not including the dispatch loop, so that it constructs, satisfies the measured member contract, and answers all 72 of `OrchAPI`'s routes with the 24 loop routes failing loudly at their call site.

**Architecture:** `OrchHost` subclasses `ActionHost`, mirroring legacy's `Orch(Base)`. It is the app *and* the orchestrator: `host.orch is host` and `host.base is host`. The four non-loop collaborators move from `helao/core/servers/` into `helao/hexagon/app/` with their back-reference retyped and their bodies untouched. The dispatch loop, status ingestion and monitors are B3b.

**Tech Stack:** Python 3.14, FastAPI, pytest, `black` (line length 88). Runs in the `helao` conda env.

## Global Constraints

- **`black` on every changed file immediately before `git add`.** Run inside the `helao` env.
- **Run python/pytest as `/home/dan/miniforge3/envs/helao/bin/python`**, never the OS python, and **not** via `conda run` (it buffers output).
- **`PYTHONPATH` must be the absolute repo root**: `/mnt/STORAGE/repos/helao/helao-async`.
- **Never run the test tree as one pytest session** — run per file, with `timeout`.
- **Never name the private deployment repos in tracked files.** Say "private deployments", or Deployment-A/B/C.
- **No behaviour change.** The post-parity backlog (`set_error`, the finish-drain window, the 0.3 s pacing sleep, `/ws_globstat`'s dead sender, `params.limit_vis`) is B7's, not this plan's. A behaviour change inside a parity port is indistinguishable from a port bug at the gate.
- **Nothing in `helao/core/servers/` is deleted by this plan.** Legacy remains the running engine. B7 deletes.
- Ports consumed are the existing `ORCH_REQUIRED` set — `config`, `logging`, `clock`, `transport`, `state_persistence`, `status`, `health`. B3a adds no port.

---

## Measured inputs (do not re-derive; verify if suspicious)

Measured on `unstable` at `03d03084`:

| fact | value |
|---|---|
| `Orch` methods that are ≤2-statement delegations | 73 of 79 |
| member contract (collaborators ∪ `orch_api`) | **135** |
| of those, already inherited from `ActionHost` | **23** |
| **new members `OrchHost` must supply** | **112** |
| `orch_api` routes | **72** = 63 bare private + **9 `/{server_key}/…` action routes** |
| B3a routes (implemented) | 48 = 39 private + 9 action |
| B3b routes (stubbed here, raising) | 24 |
| deployment files touching `.orch` | **0** — measured across hte and all three private deployments |

**The orchestrator is also an action server.** Its 9 action routes — `wait`, `cancel_wait`, `interrupt`, `estop`, `conditional_exp`, `conditional_stop`, `conditional_skip`, `add_global_param`, `clear_global_params` — are why GM captures contain `ORCH__wait` directories. They ride the `@host.action()` machinery B1 already proved.

---

## File Structure

**Create:**

| file | responsibility |
|---|---|
| `helao/hexagon/app/orch_host.py` | `OrchHost(ActionHost)` — construction, state, routes |
| `helao/hexagon/tests/test_orch_host_member_coverage.py` | the ratchet: contract vs host, with justified exclusions |
| `helao/hexagon/tests/test_orch_host_surface.py` | the 72-route surface, and that B3b routes raise rather than 404 |
| `helao/hexagon/tests/test_orch_queue_roundtrip.py` | queue mutation + export/import round trips |

**Move** (back-reference retyped, bodies otherwise untouched):

| from | to | lines |
|---|---|---|
| `helao/core/servers/orch_queues.py` | `helao/hexagon/app/orch_queues.py` | 562 |
| `helao/core/servers/orch_persist.py` | `helao/hexagon/app/orch_persist.py` | 293 |
| `helao/core/servers/orch_estop.py` | `helao/hexagon/app/orch_estop.py` | 307 |
| `helao/core/servers/orch_lifecycle.py` | `helao/hexagon/app/orch_lifecycle.py` | 264 |

**Copy, do not move** — B3b needs them and they must keep working under legacy meanwhile: `orch_dispatch.py`, `orch_status_sync.py`, `orch_monitor.py`.

**Do not touch:** `helao/core/servers/orch.py`, `orch_api.py`, or any legacy engine file.

---

## Task 1: The member-contract ratchet, before any host code

This task exists first on purpose. B1 discovered its 43 missing members one runtime crash at a
time — `helaodirs`, `begin_session`, `write_act`, `_write_meta_atomic` — each costing a
launch-and-diagnose cycle, each invisible to seventy passing unit tests, and several hidden
behind a caught exception so the server returned 200 and did nothing. The equivalent list for
`OrchHost` is computable from source. Compute it first and let it drive the work.

**Files:**
- Create: `helao/hexagon/tests/test_orch_host_member_coverage.py`

**Interfaces:**
- Produces: `orch_contract() -> set[str]`, `DELIBERATELY_ABSENT`, `NOT_YET_PORTED` — Task 2 onward delete names from `NOT_YET_PORTED` as they are implemented.

- [ ] **Step 1: Write the ratchet**

```python
"""``OrchHost`` must cover the member contract its collaborators require (B3a).

Legacy ``Orch`` is a delegation shell: 73 of its 79 methods are two
statements or fewer, and the work lives in seven collaborators that hold
only ``self.orch`` and resolve state through it at call time. That makes
the back-reference swappable -- and it makes the contract measurable, because
every member those collaborators reach for is an attribute access on a name
this module can find statically.

B1 had the same contract and did not measure it. It found 43 missing members
one runtime crash at a time, and the most expensive of them
(``_write_meta_atomic``) was underscore-prefixed, so a public-members-only
scan skipped it while its AttributeError fired inside a caught block. This
extraction counts attribute access rather than filtering by name, so
contractual privates are in the contract by construction -- there are six.

Ratchet semantics, unchanged from B1's version because they worked: fail when
the gap GROWS, not while it merely persists. A permanently red test teaches
people to ignore it.
"""

import ast
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CORE_SERVERS: Final[Path] = REPO_ROOT / "helao/core/servers"

#: Modules whose sole back-reference is the orchestrator.
CONSUMERS: Final[tuple[str, ...]] = (
    "orch_dispatch",
    "orch_queues",
    "orch_lifecycle",
    "orch_estop",
    "orch_persist",
    "orch_status_sync",
    "orch_monitor",
    "orch_global_params",
    "orch_unpack",
    "orch_api",
)


def orch_contract() -> set[str]:
    """Every ``Orch`` member a collaborator or the API layer reaches for.

    Two shapes, because the collaborators alias the back-reference before
    use (``orch = self.orch`` appears 21 times in orch_dispatch alone):
    ``orch.<name>`` and ``self.orch.<name>``.
    """
    found: set[str] = set()
    for mod in CONSUMERS:
        path = CORE_SERVERS / f"{mod}.py"
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            value = node.value
            if isinstance(value, ast.Name) and value.id == "orch":
                found.add(node.attr)
            elif isinstance(value, ast.Attribute) and value.attr == "orch":
                found.add(node.attr)
    return found


#: Members B3a answers a different way, each with a reason.
DELIBERATELY_ABSENT: Final[frozenset[str]] = frozenset(
    {
        # Registered as routes on the host, not exposed as bound methods --
        # the same decision ActionHost made. NOTE for B3b: these must
        # reproduce the ORCHAPI encoding family's bytes, not ActionHost's.
        # The two families are independently frozen (Amendment 2 section 3):
        # on /ws_status the base_api family delivers an ActionModel and the
        # orch_api family a plain dict, and a consumer that assumes either
        # blanks silently against the other.
        "ws_status",
        "ws_data",
        "ws_live",
        # Replaced by the explicit ActionContext (B1, D-B1.1).
        "setup_and_contain_action",
        # Legacy logging helper; the host uses LOGGER directly.
        "print_message",
        # Legacy lifecycle internal: OrchHost uses FastAPI's startup event.
        "myinit",
    }
)

#: The remaining work. Porting a member means DELETING it from here; that
#: edit is the point. B3b's members stay listed until B3b lands.
NOT_YET_PORTED: Final[frozenset[str]] = frozenset(
    {
        # --- B3b: the dispatch loop -------------------------------------
        "loop_task_dispatch_action",
        "loop_task_dispatch_experiment",
        "loop_task_dispatch_sequence",
        "orch_wait_for_all_actions",
        "wait_for_interrupt",
        "interrupt_q",
        "start",
        "stop",
        "skip",
        "stop_loop",
        "estop_loop",
        "estop_actions",
        "estop_finish_active",
        "intend_stop",
        "intend_none",
        "clear_error",
        "clear_estop",
        "clear_actions",
        "current_stop_message",
        "init_success",
        # --- B3b: status ingestion + monitors ---------------------------
        "update_status",
        "update_nonblocking",
        "clear_nonblocking",
        "nonblocking",
        "globstat_q",
        "status_summary",
        "last_dispatched_action_uuid",
        "step_thru_actions",
        "step_thru_experiments",
        "step_thru_sequences",
        "heartbeat_interval",
        "ignore_heartbeats",
        "register_obj_uuid",
        "register_action_uuid",
        "track_action_uuid",
        # --- B3a, filled in by Tasks 2-6 (delete as you go) -------------
        "sequence_dq",
        "experiment_dq",
        "action_dq",
        "action_history",
        "experiment_history",
        "sequence_history",
        "active_experiment",
        "active_sequence",
        "last_experiment",
        "last_sequence",
        "active_run_id",
        "active_seq_exp_counter",
        "last_action_uuid",
        "globalstatusmodel",
        "global_params",
        "aiolock",
        "wait_task",
        "current_wait_ts",
        "last_wait_ts",
        "dispatch_wait_task",
        "verify_plates",
        "verify_plate_in_params",
        "use_sync",
        "syncer",
        "executors",
        "exp_model",
        "seq_model",
        "exp_postprocessors",
        "exp_postprocess_libs",
        "seq_postprocessors",
        "seq_postprocess_libs",
        "experiment_lib",
        "sequence_lib",
        "experiment_codehash_lib",
        "sequence_codehash_lib",
        "experiment_codepath_lib",
        "sequence_codepath_lib",
        "unpack_sequence",
        "seq_unpacker",
        "add_sequence",
        "add_split_sequences",
        "add_experiment",
        "prepend_sequences",
        "move_sequence",
        "move_experiment",
        "move_action",
        "remove_sequence",
        "remove_experiment",
        "remove_action",
        "clear_sequences",
        "clear_experiments",
        "drop_experiment_inds",
        "list_sequences",
        "list_experiments",
        "list_all_experiments",
        "list_actions",
        "list_active_actions",
        "get_experiment",
        "get_sequence",
        "finish_active_experiment",
        "finish_active_sequence",
        "write_active_experiment_exp",
        "write_active_sequence_seq",
        "export_queues",
        "import_queues",
        "_ensure_run_id",
        "_resolve_active_run_id",
        "_prep_sequence_meta",
        "_rebuild_action_dq",
        "_rebuild_experiment_dq",
        "_rebuild_sequence_dq",
    }
)


def _host_members() -> set[str]:
    """Class members plus instance attributes, INCLUDING inherited ones.

    Walking only orch_host.py reports phantom gaps for everything OrchHost
    inherits from ActionHost -- 23 of the 135, and B1's first ratchet run
    made exactly this mistake with three HelaoFastAPI attributes.
    """
    import re

    from helao.hexagon.app.orch_host import OrchHost

    members = {m for m in dir(OrchHost) if not m.startswith("__")}
    for rel in (
        "helao/hexagon/app/orch_host.py",
        "helao/hexagon/app/action_host.py",
        "helao/helpers/server_api.py",
    ):
        src = (REPO_ROOT / rel).read_text(encoding="utf-8")
        members |= set(re.findall(r"self\.([A-Za-z_][A-Za-z0-9_]*)\s*=", src))
    return members


def test_the_contract_extraction_is_not_vacuous() -> None:
    """A broken AST walk would make every coverage assertion pass for free."""
    contract = orch_contract()
    assert len(contract) > 120, f"only {len(contract)} members found; walk is inert"
    for known in ("action_dq", "globalstatusmodel", "_ensure_run_id", "add_sequence"):
        assert known in contract, f"{known} missing from the extraction"


def test_no_new_gap_has_opened_in_the_host() -> None:
    missing = orch_contract() - _host_members()
    unaccounted = sorted(missing - DELIBERATELY_ABSENT - NOT_YET_PORTED)
    assert unaccounted == [], (
        "contract members OrchHost lacks that are neither deliberately excluded "
        f"nor on the known-missing list: {unaccounted}\n"
        "Either implement them, or add them to NOT_YET_PORTED with a reason."
    )


def test_the_known_missing_list_has_not_silently_grown() -> None:
    missing = orch_contract() - _host_members()
    already_done = sorted(NOT_YET_PORTED - missing)
    assert already_done == [], (
        f"on NOT_YET_PORTED but OrchHost already has them: {already_done}\n"
        "Delete them from the list."
    )


def test_deliberate_exclusions_are_actually_absent() -> None:
    missing = orch_contract() - _host_members()
    stale = sorted(DELIBERATELY_ABSENT - missing)
    assert stale == [], f"listed as deliberately absent but present: {stale}"
```

- [ ] **Step 2: Run it — it must fail on the import, not on an assertion**

Run: `PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/hexagon/tests/test_orch_host_member_coverage.py -q -p no:randomly`

Expected: `test_the_contract_extraction_is_not_vacuous` PASSES (it reads only legacy source);
the other three ERROR with `ModuleNotFoundError: helao.hexagon.app.orch_host`.

That split is the point: the contract is measurable before the host exists.

- [ ] **Step 3: Record the measured contract size in the docstring**

Add to the module docstring, using the number the run printed:

```
Measured on unstable at 03d03084: 135 members, of which 23 are inherited
from ActionHost and 112 are new.
```

- [ ] **Step 4: Commit**

```bash
black helao/hexagon/tests/test_orch_host_member_coverage.py
git add helao/hexagon/tests/test_orch_host_member_coverage.py
git commit -m "test(B3a): the OrchHost member-contract ratchet, seeded before the host"
```

---

## Task 2: `OrchHost` construction and state

**Files:**
- Create: `helao/hexagon/app/orch_host.py`
- Reference (read, do not edit): `helao/core/servers/orch.py:120-211`

**Interfaces:**
- Consumes: `ActionHost` (`helao/hexagon/app/action_host.py`), `PortWiring`, `ORCH_REQUIRED`.
- Produces: `OrchHost(server_key, server_title, description, version, wiring=None, helao_cfg=None)`; `host.orch is host`.

- [ ] **Step 1: Write the failing construction test**

Append to `helao/hexagon/tests/test_orch_host_surface.py` (create it):

```python
"""OrchHost construction and route surface (B3a)."""

import tempfile

import pytest


def _host():
    from helao.helpers import config_loader
    from helao.hexagon.app.orch_host import OrchHost

    config_loader.CONFIG = {
        "root": tempfile.mkdtemp(prefix="helao_orchhost_"),
        "dummy": True,
        "simulation": True,
        "run_type": "simulation",
        "servers": {
            "ORCH": {"host": "127.0.0.1", "port": 8001, "group": "orchestrator",
                     "params": {}},
            "SIM": {"host": "127.0.0.1", "port": 8002, "group": "action",
                    "params": {}},
        },
    }
    return OrchHost("ORCH", "ORCH", "test orchestrator", version=3.0)


def test_the_host_is_its_own_orch_and_its_own_base():
    """Legacy spells the back-reference both ways and both have call sites:
    orch_api reaches self.orch at 60 sites, and Orch extends Base."""
    host = _host()
    assert host.orch is host
    assert host.base is host


def test_construction_populates_the_three_queues_and_the_status_model():
    host = _host()
    assert list(host.sequence_dq) == []
    assert list(host.experiment_dq) == []
    assert list(host.action_dq) == []
    assert host.globalstatusmodel is not None
    assert host.active_experiment is None
    assert host.active_sequence is None
```

- [ ] **Step 2: Run it, expect ModuleNotFoundError**

Run: `PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/hexagon/tests/test_orch_host_surface.py -q -p no:randomly`

Expected: FAIL, `ModuleNotFoundError: helao.hexagon.app.orch_host`.

- [ ] **Step 3: Write `OrchHost.__init__`**

Port `orch.py:120-211` verbatim in content and order. Only the collaborator block changes,
and only in import path.

```python
"""Hexagon-native orchestrator host (B3a).

Legacy's shape is ``OrchAPI(HelaoFastAPI)`` holding ``self.orch =
Orch(Base)``. Two objects, and the API layer is a SIBLING of ``BaseAPI``
rather than a subclass -- which is why the two WS encoding families differ
and must stay independently frozen.

The native shape collapses that: ``OrchHost(ActionHost)`` is the app, the
orchestrator, and the action server it has always also been (9 of its 72
routes are ``/{server_key}/...`` action endpoints -- ``wait``, ``interrupt``,
``estop`` and friends -- which is why GM captures contain ``ORCH__wait``
directories). It answers to ``host.orch`` and ``host.base``, both of which
are ``self``: orch_api reaches ``self.orch.<member>`` at 60 sites and
``Orch`` inherits ``Base``, so inventing an indirection would buy nothing.

Scope: construction, state, the queue/persistence/estop/lifecycle
collaborators, and every route that does not run the loop. The dispatch
loop, status ingestion and the monitors are B3b; their routes are
registered here and raise, so a caller fails at the call site instead of
receiving a 404 that reads like a missing server.
"""

import asyncio
import time
from typing import Optional
from uuid import UUID

from helao.core.models.orchstatus import GlobalStatusModel
from helao.helpers import helao_logging as logging
from helao.helpers.dequedict import DequeDict
from helao.helpers.premodels import Experiment, Sequence
from helao.helpers.processors import MetaProcessor
from helao.helpers.multisubscriber_queue import MultisubscriberQueue
from helao.helpers.zdeque import zdeque
from helao.hexagon.app.action_host import ActionHost
from helao.hexagon.app.wiring import ORCH_REQUIRED, PortWiring

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

__all__ = ["OrchHost"]


class OrchHost(ActionHost):
    """The native orchestrator server."""

    def __init__(
        self,
        server_key: str,
        server_title: str,
        description: str,
        version: float = 3.0,
        wiring: Optional[PortWiring] = None,
        helao_cfg: Optional[dict] = None,
    ):
        super().__init__(
            server_key=server_key,
            server_title=server_title,
            description=description,
            version=version,
            driver_classes=None,
            wiring=wiring,
            helao_cfg=helao_cfg,
        )
        self.hexagon_wiring.require(*ORCH_REQUIRED)

        # --- orch.py:121-125 -------------------------------------------
        self.sequence_dq = zdeque([])
        self.experiment_dq = zdeque([])
        self.action_dq = zdeque([])
        self.dispatch_buffer = []
        self.nonblocking = []

        # --- orch.py:128-145 -------------------------------------------
        self.last_dispatched_action_uuid = None
        self.action_history = DequeDict(maxlen=1000)
        self.experiment_history = DequeDict(maxlen=1000)
        self.sequence_history = DequeDict(maxlen=1000)
        self.last_action_uuid = ""
        self.last_interrupt = time.time()
        self.active_experiment: Optional[Experiment] = None
        self.last_experiment: Optional[Experiment] = None
        self.active_sequence: Optional[Sequence] = None
        self.active_seq_exp_counter = 0
        self.last_sequence: Optional[Sequence] = None
        self.active_run_id: Optional[UUID] = None
        self.heartbeat_interval = self.server_params.get("heartbeat_interval", 10)
        self.ignore_heartbeats = self.server_params.get("ignore_heartbeats", [])
        self.verify_plates = self.server_params.get("verify_plates", True)

        # --- orch.py:146-150 -------------------------------------------
        self.globalstatusmodel = GlobalStatusModel(orchestrator=self.server)
        self.globalstatusmodel._sort_status()
        self.interrupt_q = asyncio.Queue()
        self.incoming_status = asyncio.Queue()
        self.incoming = None

        self.init_success = False

        # --- orch.py:155-176: task handles and wait state ---------------
        self.loop_task = None
        self.status_subscriber = None
        self.globstat_broadcaster = None
        self.heartbeat_monitor = None
        self.driver_monitor = None
        self.wait_task = None
        self.current_wait_ts = 0
        self.last_wait_ts = 0
        self.globstat_q = MultisubscriberQueue()
        self.globstat_clients = set()
        self.current_stop_message = ""
        self.aiolock = asyncio.Lock()

        # --- orch.py:172-177 -------------------------------------------
        self.step_thru_actions = False
        self.step_thru_experiments = False
        self.step_thru_sequences = False
        self.status_summary = {}
        self.global_params = {}

        # --- orch.py:178-188: meta post-processors ----------------------
        # import_postprocessors is inherited from ActionHost, where B1 fixed
        # it to resolve BARE NAMES against a deployment's processors/ dir --
        # a path-only loader skips them with a warning and the only visible
        # consequence is a missing output file.
        self.exp_postprocessors: list = []
        self.exp_postprocess_libs = self.server_cfg.get("exp_postprocess_libs", [])
        self.import_postprocessors(
            self.exp_postprocess_libs, self.exp_postprocessors, MetaProcessor
        )
        self.seq_postprocessors: list = []
        self.seq_postprocess_libs = self.server_cfg.get("seq_postprocess_libs", [])
        self.import_postprocessors(
            self.seq_postprocess_libs, self.seq_postprocessors, MetaProcessor
        )

        self._init_orch_collaborators()

    @property
    def orch(self) -> "OrchHost":
        """``app.orch`` and ``app`` are the same object here."""
        return self

    def _init_orch_collaborators(self) -> None:
        """Construct the B3a collaborators. B3b adds dispatch/status/monitor."""
        from helao.hexagon.app.orch_estop import EstopController
        from helao.hexagon.app.orch_lifecycle import RunLifecycle
        from helao.hexagon.app.orch_persist import QueuePersister
        from helao.hexagon.app.orch_queues import RunQueues

        self.queue_persister = QueuePersister(self)
        self.run_queues = RunQueues(self)
        self.run_lifecycle = RunLifecycle(self)
        self.estop_controller = EstopController(self)
```

- [ ] **Step 4: Run the construction test — it will fail on the collaborator imports**

Expected: `ModuleNotFoundError: helao.hexagon.app.orch_queues`. That is Task 3.
To confirm the construction block itself is sound first, temporarily comment out the
`self._init_orch_collaborators()` call, re-run, see both tests pass, then restore it.

- [ ] **Step 5: Commit**

```bash
black helao/hexagon/app/orch_host.py helao/hexagon/tests/test_orch_host_surface.py
git add helao/hexagon/app/orch_host.py helao/hexagon/tests/test_orch_host_surface.py
git commit -m "feat(B3a): OrchHost construction and state, ported from Orch.__init__"
```

---

## Task 3: Move the four non-loop collaborators

**Files:**
- Move: `helao/core/servers/{orch_queues,orch_persist,orch_estop,orch_lifecycle}.py` → `helao/hexagon/app/`

**Interfaces:**
- Produces: `RunQueues(host)`, `QueuePersister(host)`, `EstopController(host)`, `RunLifecycle(host)` — each holding only `self.orch`.

- [ ] **Step 1: Move with git, one file at a time, preserving history**

```bash
git mv helao/core/servers/orch_queues.py helao/hexagon/app/orch_queues.py
git mv helao/core/servers/orch_persist.py helao/hexagon/app/orch_persist.py
git mv helao/core/servers/orch_estop.py helao/hexagon/app/orch_estop.py
git mv helao/core/servers/orch_lifecycle.py helao/hexagon/app/orch_lifecycle.py
```

**These are moves, not copies, and legacy `Orch` imports them.** Update the four import sites
in `helao/core/servers/orch.py` to the new paths in the same commit, so legacy keeps working:

```python
from helao.hexagon.app.orch_estop import EstopController
from helao.hexagon.app.orch_lifecycle import RunLifecycle
from helao.hexagon.app.orch_persist import QueuePersister
from helao.hexagon.app.orch_queues import RunQueues
```

A legacy module importing from `helao/hexagon/` is the inverse of the usual direction and is
temporary — B7 deletes the importer. Check `helao/hexagon/tests/test_boundaries.py` for a rule
this violates; if one fires, add the four modules to its allowlist **with this reason**, not by
loosening the rule.

- [ ] **Step 2: Retype the back-reference in each moved file**

In each of the four, the constructor becomes:

```python
    def __init__(self, orch: "OrchHost"):
        self.orch = orch
```

with the forward reference imported under `TYPE_CHECKING`:

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from helao.hexagon.app.orch_host import OrchHost
```

**Change nothing else.** The bodies are byte-parity-pinned against their pre-decomposition
originals; a "while I'm here" edit forfeits that evidence.

- [ ] **Step 3: Verify legacy still constructs**

Run, per file:

```
PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async timeout 300 \
  /home/dan/miniforge3/envs/helao/bin/python -m pytest \
  helao/core/tests/unit_test_orch_status_sync.py helao/core/tests/unit_test_orch_monitor.py \
  helao/hexagon/tests/test_orchestration.py helao/hexagon/tests/test_dispatch_loop.py \
  helao/hexagon/tests/test_boundaries.py -q -p no:randomly
```

Expected: all pass. Any failure here is an import path missed, not a design problem.

- [ ] **Step 4: Run the construction test from Task 2**

Expected: 2 passed.

- [ ] **Step 5: Delete the four names' entries from `NOT_YET_PORTED` that construction now supplies**

Remove from the list: `verify_plates`, `aiolock`, `wait_task`, `current_wait_ts`,
`last_wait_ts`, `global_params`, `globalstatusmodel`, `sequence_dq`, `experiment_dq`,
`action_dq`, `action_history`, `experiment_history`, `sequence_history`, `active_experiment`,
`active_sequence`, `last_experiment`, `last_sequence`, `active_run_id`,
`active_seq_exp_counter`, `last_action_uuid`, `exp_postprocessors`, `exp_postprocess_libs`,
`seq_postprocessors`, `seq_postprocess_libs`.

Re-run the ratchet. If `test_the_known_missing_list_has_not_silently_grown` fails, a name you
deleted is still missing — put it back rather than adding it to `DELIBERATELY_ABSENT`.

- [ ] **Step 6: Commit**

```bash
black helao/hexagon/app/orch_queues.py helao/hexagon/app/orch_persist.py \
      helao/hexagon/app/orch_estop.py helao/hexagon/app/orch_lifecycle.py \
      helao/core/servers/orch.py helao/hexagon/tests/test_orch_host_member_coverage.py
git add -A helao/hexagon helao/core/servers/orch.py
git commit -m "refactor(B3a): move the four non-loop orch collaborators into hexagon

They hold only self.orch and resolve state through it at call time, so the
back-reference is swappable and the bodies move untouched -- the property
their own docstrings state as a rule. Legacy Orch imports them from their
new home until B7 deletes it."
```

---

## Task 4: The queue surface — 39 private routes

**Files:**
- Modify: `helao/hexagon/app/orch_host.py`

**Interfaces:**
- Consumes: `self.run_queues`, `self.queue_persister`, `self.run_lifecycle` from Task 3.

The 39 B3a private routes: `/append_experiment`, `/append_sequence`, `/append_split_sequences`,
`/attach_client`, `/clear_actions`, `/clear_experiments`, `/clear_global_params_private`,
`/clear_sequences`, `/detach_client`, `/drop_experiment_inds`, `/drop_experiment_range`,
`/endpoints`, `/export_queues`, `/get_global_params`, `/get_histories`, `/get_history_page`,
`/get_lbuf`, `/get_queue_object`, `/get_status`, `/global_status`, `/import_queues`,
`/insert_experiment`, `/latest_action_uuids`, `/list_actions`, `/list_all_experiments`,
`/list_executors`, `/list_experiments`, `/list_sequences`, `/move_action`, `/move_experiment`,
`/move_sequence`, `/prepend_experiment`, `/prepend_sequences`, `/remove_action`,
`/remove_experiment`, `/remove_sequence`, `/shutdown`, `/stop_executor`, `/update_global_params`.

`/attach_client`, `/detach_client`, `/endpoints`, `/get_lbuf`, `/get_status`, `/list_executors`,
`/shutdown` and `/stop_executor` are **already registered by `ActionHost`** — do not re-register
them; verify in Step 3 that they answer.

- [ ] **Step 1: Write the paged-index test first**

This is the trap this task exists to avoid. Append to `helao/hexagon/tests/test_orch_queue_roundtrip.py` (create it):

```python
"""Queue mutation round trips (B3a).

The index trap, documented in CLAUDE.md and found the hard way in the
operator pagination work: the orchestrator indexes its deques ABSOLUTELY
(get_queue_object, move_*, remove_* all do), while a rendered row index is
page-local. A handler that forgets to add the page offset deletes the wrong
queued item with nothing on screen looking wrong.
"""

import pytest


def test_list_sequences_defaults_to_the_whole_queue():
    """limit=None means the whole queue.

    It used to default to limit=10 while the /list_* endpoints called it
    bare, so no operator UI could ever see an eleventh queued item -- and
    the subtab counts reported that truncation as the queue's depth.
    """
    from helao.hexagon.tests.test_orch_host_surface import _host

    host = _host()
    for i in range(12):
        host.sequence_dq.append(_fake_sequence(i))
    assert len(host.list_sequences()) == 12
    assert len(host.list_sequences(limit=5)) == 5
    assert len(host.list_sequences(limit=5, offset=10)) == 2
```

with this helper at the top of the module:

```python
from helao.helpers.premodels import Sequence


def _fake_sequence(i: int) -> Sequence:
    """A queue entry distinguishable by name, with nothing else set.

    Deliberately minimal: this file tests QUEUE mechanics -- ordering,
    offsets, bounds -- and a fully-populated Sequence would make an
    ordering bug look like a model bug.
    """
    return Sequence(sequence_name=f"seq{i}", sequence_params={})
```

- [ ] **Step 2: Run it, expect failure**

Expected: `AttributeError: 'OrchHost' object has no attribute 'list_sequences'`.

- [ ] **Step 3: Add the delegating members and their routes**

Every one of these is a delegation, matching legacy `orch.py`. Example shape — write all of
them this way, and **do not add logic**:

```python
    # -- queue surface (delegations; legacy orch.py:560-720) -------------

    def list_sequences(self, limit=None, offset: int = 0):
        """Return queued sequences. ``limit=None`` means the whole queue."""
        return self.run_queues.list_sequences(limit=limit, offset=offset)

    def move_sequence(self, old_idx: int, new_idx: int):
        """Move a queued sequence. Indices are ABSOLUTE, not page-local."""
        return self.run_queues.move_sequence(old_idx, new_idx)
```

Register the routes in a `_register_orch_queue_routes()` called from `__init__`, mirroring
`orch_api.py`'s parameter names and types exactly — the `/openapi.json` diff in Task 7 compares
parameter schemas, not just paths.

- [ ] **Step 4: Run both test files**

Expected: queue round-trip tests pass; the ratchet's unaccounted list shrinks.

- [ ] **Step 5: Delete the now-implemented names from `NOT_YET_PORTED`, re-run the ratchet**

- [ ] **Step 6: Commit**

```bash
black helao/hexagon/app/orch_host.py helao/hexagon/tests/test_orch_queue_roundtrip.py
git add -A helao/hexagon
git commit -m "feat(B3a): the orchestrator queue surface, 39 private routes"
```

---

## Task 5: Persistence, and the loop routes that must fail loudly

**Files:**
- Modify: `helao/hexagon/app/orch_host.py`

- [ ] **Step 1: Write the export/import round-trip test**

```python
def test_export_then_import_restores_all_three_queues(tmp_path):
    """A queues.pck written by this host must read back into it.

    Cross-version restore is a real production path: --restore and
    restore_queues_on_startup both replay a pickle written by a previous
    launch, and `python -m helao.core.tests.check_queue_pcks` exists
    because a build that cannot restore its own file fails silently.
    """
    from helao.hexagon.tests.test_orch_host_surface import _host

    host = _host()
    host.sequence_dq.append(_fake_sequence(0))
    host.export_queues()
    host.sequence_dq.clear()
    host.import_queues()
    assert len(host.sequence_dq) == 1
```

- [ ] **Step 2: Run it, expect `AttributeError` on `export_queues`**

- [ ] **Step 3: Add the persistence delegations and the six contractual privates**

`export_queues`, `import_queues` delegate to `self.queue_persister`. The privates
`_ensure_run_id`, `_resolve_active_run_id`, `_prep_sequence_meta`, `_rebuild_action_dq`,
`_rebuild_experiment_dq`, `_rebuild_sequence_dq` are called by the collaborators through the
back-reference — port them from `orch.py` as delegations exactly as the public ones.

**They are underscore-prefixed and they are contract.** B1 lost most of a session to exactly
one such member: `_write_meta_atomic` was missing, its `AttributeError` fired inside a caught
block, and every action returned 200 having written nothing.

- [ ] **Step 4: Register the 24 B3b routes as raising stubs**

```python
    def _register_orch_loop_routes(self) -> None:
        """Register B3b's routes so the surface is complete and honest.

        They raise rather than 404. A 404 reads as a missing server and
        sends a caller looking at config and ports; a NotImplementedError
        naming B3b says what is actually true. This is the same choice B1
        made for start_executor/oneoff_executor before its Task 6.
        """

        @self.post("/start", tags=["private"])
        async def start():
            raise NotImplementedError("dispatch loop lands in B3b")
```

Do this for all 24: `/start`, `/stop`, `/estop_orch`, `/clear_estop`, `/clear_error`,
`/skip_experiment`, `/clear_actives`, `/update_status`, `/update_nonblocking`,
`/get_active_experiment`, `/get_active_sequence`, `/active_experiment`, `/last_experiment`,
`/list_active_actions`, `/list_nonblocking`, `/get_orch_state`, `/get_status_summary`,
`/get_step_flags`, `/set_step_flag`, `/latest_sequence_uuids`, `/latest_experiment_uuids`,
and the three websockets `/ws_status`, `/ws_data`, `/ws_live`.

**The three websockets are not simple stubs.** `ActionHost` already registers all three, and
its encoding is the **`BaseAPI` family**. The orchestrator's is the **`OrchAPI` family** —
independently frozen, and carrying a plain dict on `/ws_status` where the action family carries
an `ActionModel`. Override them here with handlers that raise, so B3b cannot silently inherit
the wrong family; record that reason in a comment at the override.

- [ ] **Step 5: Run every test file written so far**

- [ ] **Step 6: Commit**

```bash
black helao/hexagon/app/orch_host.py helao/hexagon/tests/test_orch_queue_roundtrip.py
git add -A helao/hexagon
git commit -m "feat(B3a): queue persistence, the six contractual privates, and raising B3b stubs"
```

---

## Task 6: The nine action routes

**Files:**
- Modify: `helao/hexagon/app/orch_host.py`

The orchestrator's own action endpoints: `wait`, `cancel_wait`, `interrupt`, `estop`,
`conditional_exp`, `conditional_stop`, `conditional_skip`, `add_global_param`,
`clear_global_params`. They ride `@host.action()` — the machinery B1 built and proved.

**Eight to write, not nine.** `ActionHost.__init__` already calls
`_register_estop_route(server_key)`, and its body is the same sequence `orch_api`'s
`/{server_key}/estop` performs — driver estop hook, latch `actionservermodel.estop`, stop every
executor, finalize in-flight actions. `OrchHost` inherits a correct `/ORCH/estop`.

**Do not re-register it.** FastAPI accepts a duplicate path without complaint and the first
registration wins, so a second `/ORCH/estop` would sit in the route table shadowed and never
execute — and the route-surface diff in Task 7 would still pass, because the path is present
either way. Verify instead: assert exactly one route has path `/ORCH/estop`.

- [ ] **Step 1: Write the artifact test**

An `ORCH__wait` action must leave `-act.yml` and a run directory. Model it on
`helao/hexagon/tests/test_action_writes_artifacts.py`, which is an **outcome** test — files on
disk, not collaborator calls. That module's own history is the argument: every earlier fix along
B1's write path satisfied a call-level expectation and still wrote nothing.

```python
import asyncio
from pathlib import Path

import httpx
import pytest


async def _run_one_orch_action(name: str, params: dict) -> list[str]:
    """POST one orchestrator action over ASGI and return the files it wrote.

    Startup handlers are invoked by hand because httpx.ASGITransport does
    not run lifespan events -- and _rpc_startup is skipped because it binds
    the ZMQ ROUTER on port+10000, which collides with anything already
    serving it.
    """
    host = _host()
    for handler in host.router.on_startup:
        if handler.__name__ == "_rpc_startup":
            continue
        result = handler()
        if hasattr(result, "__await__"):
            await result
    await host.init_endpoint_status()

    transport = httpx.ASGITransport(app=host)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.post(f"/ORCH/{name}", params=params, json={})
    assert resp.status_code == 200, resp.text

    for _ in range(600):
        if not host.actives:
            break
        await asyncio.sleep(0.05)
    assert not host.actives, f"action never finished: {list(host.actives)}"
    await asyncio.sleep(0.2)  # let the finalizer's writes land

    root = Path(host.world_cfg["root"])
    found: list[str] = []
    for tree in ("RUNS_ACTIVE", "RUNS_FINISHED", "RUNS_SYNCED", "RUNS_DIAG"):
        base = root / tree
        if base.exists():
            found += [p.name for p in base.rglob("*") if p.is_file()]
    return sorted(found)


@pytest.mark.asyncio
async def test_an_orch_wait_action_writes_its_meta_file():
    names = await _run_one_orch_action("wait", {"waittime": 0.5})
    assert any(n.endswith("-act.yml") for n in names), f"no act meta file: {names}"
```

- [ ] **Step 2: Run it, expect a 404 on `/ORCH/wait`**

- [ ] **Step 3: Register the nine, porting each body from `orch_api.py`**

```python
        @self.action()
        async def wait(ctx: ActionContext, waittime: float = 0.0):
            """Block the loop for ``waittime`` seconds."""
            active = await ctx.begin()
            ...
```

Port each body from `orch_api.py` unchanged apart from the context seam. `wait` uses
`start_wait`/`dispatch_wait_task`, which live in `orch_lifecycle` — already moved in Task 3.

- [ ] **Step 4: Run the artifact test, then every other test file**

- [ ] **Step 5: Delete the implemented names from `NOT_YET_PORTED`, re-run the ratchet**

- [ ] **Step 6: Commit**

```bash
black helao/hexagon/app/orch_host.py
git add -A helao/hexagon
git commit -m "feat(B3a): the orchestrator's nine action routes, on the B1 context machinery"
```

---

## Task 7: The gate — live route-surface diff

**Files:**
- Modify: `helao/hexagon/tests/test_orch_host_surface.py`

- [ ] **Step 1: Capture the legacy orchestrator's live surface**

Launch a legacy orchestrator and capture `/openapi.json` with `harness/openapi_capture.py`:

```bash
export PATH=/home/dan/miniforge3/envs/helao/bin:$PATH
export PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async
rm -rf /home/dan/INST_hlo_golden
python launch.py golden --no-hot-reload &
```

Wait for readiness by **POSTing** `/loaded_modules` — every HELAO private route is a POST, and a
GET returns 405, which a naive probe reports as "server down". That mistake cost a full
five-scenario capture run in B1: the group was healthy and the harness tore it down.

Capture to `helao/hexagon/tests/checklists/orch_openapi_legacy.json`, then kill the launcher **by
the PID captured at spawn** — never `pkill -f`, which matches the wrapper running it.

- [ ] **Step 2: Write the diff test**

```python
def test_the_route_surface_matches_the_legacy_orchestrator():
    """Live /openapi.json, not a hand-written checklist.

    B1 measured its hand-written surface checklist stale: it listed 9 routes
    with 5 GETs where the live server had 19, all POST. A frozen capture of
    the real thing cannot drift that way.
    """
    from harness import openapi_capture

    legacy = json.loads(CHECKLIST.read_text())
    current = openapi_capture.normalize(_host().openapi())
    assert _paths(current) == _paths(legacy)
```

Compare paths, methods, tags and parameter schemas. The 24 B3b routes must be **present** —
they raise at call time, they are not absent from the surface.

- [ ] **Step 3: Run it**

Expected: PASS at 72 routes. A missing route is a registration gap; an extra one is usually a
route `ActionHost` supplies that `OrchAPI` does not — decide deliberately and record which.

- [ ] **Step 4: Run the whole hexagon + harness suite, per file**

```bash
for f in helao/hexagon/tests/test_*.py harness/tests/test_*.py; do
  r=$(PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async timeout 420 \
      /home/dan/miniforge3/envs/helao/bin/python -m pytest "$f" -q -p no:randomly 2>&1 | tail -1)
  case "$r" in *" failed"*|*error*) echo "FAIL $(basename $f) :: $r";; esac
done; echo SWEEP COMPLETE
```

Expected: no FAIL lines.

- [ ] **Step 5: Commit**

```bash
black helao/hexagon/tests/test_orch_host_surface.py
git add -A helao/hexagon
git commit -m "test(B3a): gate OrchHost against the legacy orchestrator's live route surface"
```

---

## Done when

- The ratchet's `NOT_YET_PORTED` contains **only** B3b members, each with a reason.
- `/openapi.json` matches legacy at all 72 routes.
- Queue mutation, paging and export/import round trips pass.
- An `ORCH__wait` action writes its meta file.
- Full hexagon + harness sweep: no failures.

**Not done here, and not a gate:** the dispatch loop, GM parity, the concurrency suite, any
station. Those are B3b and B5.
