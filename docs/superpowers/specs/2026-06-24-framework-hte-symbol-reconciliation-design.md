# Framework hte Migration — Symbol Reconciliation (design)

**Date:** 2026-06-24
**Branch:** `feat/framework-hte-symbol-recon`
**Cycle:** Gated hte production migration — the action-server prerequisite (between
Wave 0 and Wave 1/2). **No hte edits** — pure framework-side parity work so the
Wave-2 action-server import-swap is a clean path change.

## 1. Context

Wave 0's audit found 35 hte imports already mapped + flagged a symbol-level caveat:
module existence ≠ symbol parity for `premodels`, `helpers.executor`, and
`core.servers.base`/`base_api`. The symbol audit (across hte servers):

| Symbol(s) | hte uses | Framework status |
|---|---|---|
| `ActionPlanMaker`, `ExperimentPlanMaker` | 31 | ✓ `domain/plan_makers` (clean path swap) |
| `Executor` | 14 | ✓ `domain/executor` (clean path swap) |
| `Base`, `BaseAPI` | 38 | ✓ `app/base_api` (clean path swap) |
| `Action`, `Experiment`, `Sequence` | 48 | ✗ framework has `RunAction`/`RunExperiment`/`RunSequence` only |
| `Active` | 4 | ✗ replaced by `domain/action_session.ActionSession`; legacy name not exposed |
| `action_version` | 8 | ✗ deliberately deferred in SP7 (`base_api`:848) |

This sub-project closes the three ✗ rows so the action servers migrate by import-path
change only. Decisions (user): **build `action_version` into the framework BaseAPI**;
**expose an `Active` compat alias** to the framework active-session object.

## 2. Goal & non-goals

**Goal:** framework-side parity additions so `from helao.framework.domain.run_models
import Action, Experiment, Sequence`, `from helao.framework.app.base_api import BaseAPI,
Base, Active, action_version` resolve and behave as the legacy names did.

**Non-goals:** any `helao/deploy/**` or `helao/core/**` edit (Wave 1+); the deferred
dedicated ports (`sample_api`, analysis subsystem — their own sub-projects); changing
behavior beyond restoring the legacy symbol semantics.

## 3. Components

### 3.1 `domain/run_models.py` — legacy aliases

Add module-level aliases + extend `__all__`:
```python
Action = RunAction
Experiment = RunExperiment
Sequence = RunSequence
```
`__all__ = ["RunSequence", "RunExperiment", "RunAction", "Sequence", "Experiment", "Action"]`.
(The framework decorators already accept legacy instances — SP7; these aliases let hte
import the legacy names from the framework. The classes ARE the framework Run* classes.)

### 3.2 `app/base_api.py` — `action_version` decorator (port the deferred feature)

Port near-verbatim from legacy `base_api.py` (~185-232):
- `ACTION_VERSION_ATTR = "__helao_action_version__"`.
- `action_version(version: int) -> Callable` decorator that stashes `version` on the
  endpoint fn via `ACTION_VERSION_ATTR`.
- In the framework's `wrap_action_endpoint` / `_build_action_endpoint_signature` (the
  SP7 subset that omitted it), read `ACTION_VERSION_ATTR` and inject an
  `action_version: int = N` parameter so it is recorded on the action exactly as an
  inline `action_version: int = N` declaration would be (legacy parity).
- Export `action_version` + `ACTION_VERSION_ATTR` in `__all__`.

### 3.3 `domain/action_session.py` + `app/base_api.py` — `Active` + enqueue variants

- Add to `ActionSession` the two convenience methods hte uses (port legacy semantics):
  - `async def enqueue_data_dflt(self, datadict: dict)` → wrap `datadict` against the
    default file-conn key in an active `DataModel` and call `enqueue_data` (legacy
    `base.py:1441`). Needs the base's default-file-conn-key accessor; confirm the
    framework base exposes it (e.g. `dflt_file_conn_key()`), add if missing.
  - `enqueue_data_nowait(...)` → the sync (non-await) variant (legacy `base.py:1466`);
    match its signature + semantics.
- In `app/base_api.py`, export an `Active` alias to the active-session class
  (`Active = ActionSession`) + add to `__all__`, so hte's `from ...base_api import Active`
  (used for type hints / the object returned by `setup_and_contain_action`) resolves.
- Verify `ActionSession` already provides the other hte-used methods: `finish` ✓,
  `start_executor` ✓, `append_sample` ✓, `write_file` ✓, `enqueue_data` ✓.

## 4. Test strategy

- `run_models` aliases: `Action is RunAction`, `Experiment is RunExperiment`,
  `Sequence is RunSequence`; all in `__all__`.
- `action_version`: decorate a dummy endpoint with `@action_version(2)`; assert the
  attr is set and that the wrapped endpoint injects/records `action_version == 2`
  (mirror a legacy parity assertion; reuse an existing base_api action-endpoint test
  harness if present).
- `Active`/enqueue variants: `Active is ActionSession`; build an `ActionSession`
  (existing test fixtures) and assert `enqueue_data_dflt({...})` enqueues a DataModel
  against the default file-conn key, and `enqueue_data_nowait(...)` enqueues without
  awaiting; the other 4 methods exist (smoke).
- Full framework suite + boundary stay green.

## 5. Boundary

`run_models`/`action_session` are `domain/` — stay pure (aliases + dict/Data logic, no
I/O). `action_version`/`Active` live in `app/base_api` (app layer). AST boundary check
unaffected.

## 6. Done criteria

- `Action`/`Experiment`/`Sequence` aliases in `run_models`; `action_version` decorator +
  wiring + `Active` alias + `enqueue_data_dflt`/`enqueue_data_nowait` in the framework,
  all with parity tests.
- Full framework suite green; boundary green; no `helao/deploy/**` or `helao/core/**`
  modified.
- The Wave-2 action-server migration is now a pure import-path swap for all of
  `premodels`/`executor`/`base_api` symbols.
