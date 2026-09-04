# Frozen route checklists: an additions allowlist

**Date:** 2026-09-04
**Status:** design approved, no code written
**Lands before:** `2026-09-04-andor-driver-split-design.md`, which is the first
consumer but not the reason the gate needs this.

## Problem

`helao/hexagon/tests/checklists/hte/*.json` is a verbatim AST extraction of the
pre-migration legacy source: every action and private route with each parameter's
name, annotation and default. `test_hte_route_checklist.py` diffs every hte action
module against that record and pins the tree-wide totals at `(168, 79)`.

The record exists to prove the hexagon port changed nothing a client can see, and
its docstring states the rule that makes it worth anything:

> **Never regenerate the checklists.** `harness/hte_freeze.py` writes that
> directory from whatever the source currently says; running it after a port
> replaces the record with the port's own output, and this test then passes by
> construction, proving nothing.

That rule has no exception for deliberate change. Adding a route to any hte action
server today leaves three options, all bad: re-freeze the module and destroy its
pre-port record; edit the `(168, 79)` literal and the JSON by hand, which is a
re-freeze with extra steps; or do not add routes to hte while the migration runs.

The migration is long-lived. The third option is the one currently in force by
default, and it is not sustainable.

## The asymmetry this rests on

`diff_route_sets` (`harness/endpoints.py:206-222`) already reports three kinds:

- `missing` — a frozen route is gone from the source
- `changed` — a frozen route's `tags` or `params` differ
- `extra` — the source has a route the frozen record does not

The first two mean a client that relied on the frozen surface is broken. **The
third cannot.** A route nobody knew about cannot have been depended on. The gate
currently treats all three identically, which is why a purely additive change is
as hard to land as a breaking one.

The allowlist makes the gate as asymmetric as the risk already is. It does not
weaken the record: `missing` and `changed` keep failing unconditionally, and an
**unlisted** `extra` keeps failing too.

## Design

### The record

`_additions.json`, one per checklist directory, alongside the frozen records. The
leading underscore follows the convention already used there by `_collisions.json`
and `_baseapi_system_surface.json`, so it does not read as a per-module record and
is not mistaken for one.

```json
[
  {
    "module": "andor_server.py",
    "path": "/ANDOR/calibrate_wl",
    "method": "post",
    "date": "2026-09-04",
    "why": "lamp wavelength calibration; see 2026-09-04-andor-driver-split-design.md"
  }
]
```

`why` is required and is the point of the file. A reviewer seeing this line in a
diff should be able to tell whether the addition was intended without opening
anything else.

### The helper

`harness/endpoints.py` gains:

```python
def filter_allowed_additions(
    diffs: list[dict],
    additions: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Split diffs into (failing, allowed).

    An ``extra`` diff whose (path, method) is listed is allowed. Every
    ``missing`` and ``changed`` diff fails regardless of the list.
    """
```

It lives in `harness/` rather than inline in the hte test because a private
deployment carries a near-identical gate, modelled on the hte one and repeating
the same never-regenerate doctrine. Putting the semantics in shared code lets that
gate adopt the same rule later by calling one function, instead of a second
hand-written interpretation of what counts as a safe diff.

### The two test changes

`test_hte_route_checklist.py`:

- `test_module_matches_its_frozen_checklist` loads `_additions.json`, scoped to the
  module under test, and passes its diffs through `filter_allowed_additions`. It
  asserts on the failing list.
- `test_the_gate_covers_the_whole_measured_surface` computes its expected totals as
  `168 + <allowed action additions>` and `79 + <allowed private additions>` instead
  of carrying the literal `(168, 79)`. The base numbers stay pinned as named
  constants with the comment explaining where they came from, so the origin of the
  measurement is not lost behind arithmetic.

### The staleness guard

A new test fails when an `_additions.json` entry names a route that is **not**
currently present in its module's source. Without it the file rots: a route that is
later renamed or removed leaves an entry that silently pre-authorizes a future
route at the same path.

This is the part that keeps the mechanism honest. An allowlist nobody prunes
becomes a permanent hole, and the hole is invisible precisely because the test is
green.

### What does not change

- No existing `*.json` frozen record is touched. The pre-port record stays
  byte-identical, and this change is verifiable by confirming that.
- `harness/hte_freeze.py` is not run and not modified. Nothing in this change
  regenerates anything.
- `missing` and `changed` remain unconditional failures. There is no allowlist for
  them and none should be added — a removal or a signature change should require an
  argument, not a JSON entry.

## Verification

The mechanism must be shown red before it is trusted, the same way the original
gate was:

1. **Empty allowlist is a no-op.** With `_additions.json` as `[]`, the full hte
   checklist gate passes exactly as it does today, and the computed totals equal
   `(168, 79)`.
2. **An unlisted addition still fails.** Add a throwaway route to one hte action
   module with no allowlist entry; `test_module_matches_its_frozen_checklist`
   reports it as `extra` and fails. Revert.
3. **A listed addition passes.** Same route, now listed; the gate passes and the
   totals compute to `(169, 79)`. Revert both.
4. **A removal still fails while listed.** Delete a frozen route and add an
   allowlist entry naming it. The gate must still fail with `missing` — the entry
   must not launder a removal into an addition.
5. **A parameter change still fails while listed.** Change a frozen route's default
   and list that route. The gate must still fail with `changed`.
6. **A stale entry fails.** List a route that does not exist in the source. The
   staleness guard fails.

Steps 4 and 5 are the ones that matter. They are the difference between an
asymmetric gate and a bypass.

## Scope

Parent repo only. A private deployment's twin gate is a separate repository with
its own branch and remote; it can adopt `filter_allowed_additions` when it next
needs to add a route, and does not need to change for this. That follow-up is worth
recording where that deployment's own notes live, not here.
