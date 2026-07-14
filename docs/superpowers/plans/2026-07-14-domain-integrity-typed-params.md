# Domain-Integrity: Domain Enums + Dispatch Hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce shared electrochem-authoring StrEnums and coerce-at-boundary dispatch that raises a clear error on unknown values, eliminating the silent/opaque failure modes in `potential_versus`, `WE_versus`, and `ref_type` across the hte experiment library — with byte-identical wire output.

**Architecture:** One shared module `helao/core/models/echem_params.py` defines `RefType`/`PotentialVersus`/`WEVersus`/`BubbleGas` (all `str, Enum`, values verbatim) plus `resolve_*` coercion helpers and `ref_offset()`. hte experiment functions coerce each param **once, locally, before its dispatch branch** — the coerced value is never inserted into any recorded dict, so `action_params`/`experiment_params` wire bytes are unchanged; only the pre-existing silent/`KeyError`/`UnboundLocalError` paths become catalogued `ValueError`s.

**Tech Stack:** Python 3.12, pydantic v2 (enums only, no models here), stdlib `enum.Enum`. No pytest — standalone `unit_test_*` scripts using `helao.core.tests._test_utils.TestReporter`, aggregated by `run_unit_tests.py`.

## Global Constraints

- **Wire byte-identity is mandatory.** Enums are `class X(str, Enum)`; every member `.value` is copied verbatim from the current string literal. Coerced values are used only for local comparison/computation, never written into an `apm.add`/`epm.add` dict, `action_params`, or `experiment_params`. `X.oer == "oer"` and `REF_TABLE[X.rhe]` both hold because members are `str` instances.
- **Only intended behavior delta:** an out-of-catalog value that used to be silently mis-handled (`potential_versus`), raise `KeyError` (`ref_type`), or raise `UnboundLocalError` (`WE_versus`) now raises a catalogued `ValueError` naming valid members. Each hardened function is audited (grep tracked defaults) before the flip.
- **Env:** run everything via `conda run -n helao --no-capture-output <cmd>` from repo root (`PYTHONPATH=repo root`).
- **Gates every task:** `python helao/core/tests/test_orch_dispatch_golden_master.py --check` (9/9), `python helao/core/tests/test_active_golden_master.py --check` (13/13), `python run_unit_tests.py` (overall PASS), and a Python import smoke of every touched module. Golden-master baselines are gitignored under `.omc/artifacts/p5|p6/` — re-freeze locally if absent.
- **`black`** on all changed `.py` files as the final step before every commit. Commit + push per task.
- **Out of scope:** `helao/deploy/hte/experiments/archive/*` (DEMO_exp etc.), and every commented-out `WE_versus` block (`ECMS_exp.py:841-848`, `1505-1509`). Do not touch these.
- **Branch:** `feat/cards-domain-enums` (already created off `unstable`; spec committed at `ab56b2c8`).

---

### Task 1: Core enum module + resolvers + core unit test

**Files:**
- Create: `helao/core/models/echem_params.py`
- Create: `helao/core/tests/unit_test_echem_params.py`
- Modify: `run_unit_tests.py` (register the new test)

**Interfaces:**
- Produces:
  - `class RefType(str, Enum)` — `leakless="leakless"`, `inhouse="inhouse"`, `rhe="rhe"`
  - `class PotentialVersus(str, Enum)` — `rhe="rhe"`, `oer="oer"`
  - `class WEVersus(str, Enum)` — `ref="ref"`, `rhe="rhe"`
  - `class BubbleGas(str, Enum)` — `n2="N2"`, `o2="O2"`
  - `resolve_ref_type(value) -> RefType`, `resolve_potential_versus(value) -> PotentialVersus`, `resolve_we_versus(value) -> WEVersus`, `resolve_bubble_gas(value) -> BubbleGas` — each raises `ValueError` naming valid members on unknown input.
  - `ref_offset(value) -> float` — validates via `resolve_ref_type`, returns `REF_TABLE[<member>]`.

- [ ] **Step 1: Write the module**

Create `helao/core/models/echem_params.py`:

```python
"""Shared StrEnums + coercion helpers for electrochem authoring params.

CARDS Domain-Integrity lever. Each enum's member values are the verbatim
string literals used today in hte experiment signatures and REF_TABLE keys,
so `.value` on the wire is byte-identical to the strings they replace. The
`resolve_*` helpers coerce a wire value to its enum and raise a clear,
catalogued ValueError on an unknown value (replacing silent fallthrough /
KeyError / UnboundLocalError at the dispatch sites).

Import cost: stdlib enum + helao.helpers.constants only. MUST NOT import any
driver module (this is imported by the pre-launch unit-test suite).
"""

__all__ = [
    "RefType",
    "PotentialVersus",
    "WEVersus",
    "BubbleGas",
    "resolve_ref_type",
    "resolve_potential_versus",
    "resolve_we_versus",
    "resolve_bubble_gas",
    "ref_offset",
]

from enum import Enum

from helao.helpers.constants import REF_TABLE


class RefType(str, Enum):
    """Reference-electrode key into REF_TABLE (potential offset in volts)."""

    leakless = "leakless"
    inhouse = "inhouse"
    rhe = "rhe"


class PotentialVersus(str, Enum):
    """Reference frame for an authored potential (ECHE/ADSS)."""

    rhe = "rhe"
    oer = "oer"


class WEVersus(str, Enum):
    """Working-electrode reference frame (ANEC/ECMS)."""

    ref = "ref"
    rhe = "rhe"


class BubbleGas(str, Enum):
    """Solution bubbling gas identity."""

    n2 = "N2"
    o2 = "O2"


def _resolve(enum_cls, value):
    try:
        return enum_cls(value)
    except ValueError:
        valid = ", ".join(m.value for m in enum_cls)
        raise ValueError(
            f"invalid {enum_cls.__name__} {value!r}; valid: {valid}"
        ) from None


def resolve_ref_type(value) -> RefType:
    return _resolve(RefType, value)


def resolve_potential_versus(value) -> PotentialVersus:
    return _resolve(PotentialVersus, value)


def resolve_we_versus(value) -> WEVersus:
    return _resolve(WEVersus, value)


def resolve_bubble_gas(value) -> BubbleGas:
    return _resolve(BubbleGas, value)


def ref_offset(value) -> float:
    """Validate a ref_type and return its REF_TABLE potential offset (volts)."""
    return REF_TABLE[resolve_ref_type(value)]
```

- [ ] **Step 2: Write the failing test**

Create `helao/core/tests/unit_test_echem_params.py`:

```python
"""Equivalence + enforcement proof for the shared echem authoring enums.

Standalone script (not pytest), matching the other helao.core.tests
unit_test_* modules; invoked directly or via run_unit_tests.py. Exits
non-zero on any failure.
"""

__all__ = ["echem_params_unit_test"]

import sys
import traceback

from helao.helpers.constants import REF_TABLE
from helao.core.tests._test_utils import TestReporter
from helao.core.models.echem_params import (
    RefType,
    PotentialVersus,
    WEVersus,
    BubbleGas,
    resolve_ref_type,
    resolve_potential_versus,
    resolve_we_versus,
    resolve_bubble_gas,
    ref_offset,
)


def _raises_value_error(fn):
    try:
        fn()
    except ValueError:
        return True
    except Exception:
        return False
    return False


def _check_surface(reporter):
    reporter.section("enum surface freeze")
    reporter.check(
        "RefType values == ['leakless', 'inhouse', 'rhe']",
        lambda: [m.value for m in RefType] == ["leakless", "inhouse", "rhe"],
    )
    reporter.check(
        "PotentialVersus values == ['rhe', 'oer']",
        lambda: [m.value for m in PotentialVersus] == ["rhe", "oer"],
    )
    reporter.check(
        "WEVersus values == ['ref', 'rhe']",
        lambda: [m.value for m in WEVersus] == ["ref", "rhe"],
    )
    reporter.check(
        "BubbleGas values == ['N2', 'O2']",
        lambda: [m.value for m in BubbleGas] == ["N2", "O2"],
    )


def _check_str_equality(reporter):
    reporter.section("str-equality + dict-key identity (wire safety)")
    reporter.check(
        "PotentialVersus.oer == 'oer'", lambda: PotentialVersus.oer == "oer"
    )
    reporter.check("WEVersus.ref == 'ref'", lambda: WEVersus.ref == "ref")
    reporter.check(
        "REF_TABLE[RefType.rhe] == REF_TABLE['rhe']",
        lambda: REF_TABLE[RefType.rhe] == REF_TABLE["rhe"],
    )
    reporter.check("BubbleGas.n2 == 'N2'", lambda: BubbleGas.n2 == "N2")


def _check_resolvers(reporter):
    reporter.section("resolver coercion + errors")
    reporter.check(
        "resolve_potential_versus('oer') is PotentialVersus.oer",
        lambda: resolve_potential_versus("oer") is PotentialVersus.oer,
    )
    reporter.check(
        "resolve_we_versus('rhe') is WEVersus.rhe",
        lambda: resolve_we_versus("rhe") is WEVersus.rhe,
    )
    reporter.check(
        "resolve_ref_type('inhouse') is RefType.inhouse",
        lambda: resolve_ref_type("inhouse") is RefType.inhouse,
    )
    reporter.check(
        "resolve_bubble_gas('N2') is BubbleGas.n2",
        lambda: resolve_bubble_gas("N2") is BubbleGas.n2,
    )
    reporter.check(
        "ref_offset('inhouse') == REF_TABLE['inhouse']",
        lambda: ref_offset("inhouse") == REF_TABLE["inhouse"],
    )
    reporter.check(
        "ref_offset('rhe') == REF_TABLE['rhe']",
        lambda: ref_offset("rhe") == REF_TABLE["rhe"],
    )
    reporter.check(
        "resolve_potential_versus('RHE') [wrong case] raises ValueError",
        lambda: _raises_value_error(lambda: resolve_potential_versus("RHE")),
    )
    reporter.check(
        "resolve_we_versus('oer') [wrong domain] raises ValueError",
        lambda: _raises_value_error(lambda: resolve_we_versus("oer")),
    )
    reporter.check(
        "ref_offset('bogus') raises ValueError", lambda: _raises_value_error(lambda: ref_offset("bogus"))
    )

    msg = None
    try:
        resolve_ref_type("bogus")
    except ValueError as exc:
        msg = str(exc)
    reporter.check(
        "resolve_ref_type error names all three valid members",
        lambda: msg is not None
        and all(v in msg for v in ("leakless", "inhouse", "rhe")),
    )


def echem_params_unit_test() -> bool:
    reporter = TestReporter("echem_params")
    try:
        _check_surface(reporter)
        _check_str_equality(reporter)
        _check_resolvers(reporter)
        return reporter.success()
    except Exception as exc:  # noqa: BLE001
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        print(repr(exc), tb)
        return False


if __name__ == "__main__":
    ok = echem_params_unit_test()
    if ok:
        print("PASS: unit_test_echem_params — shared echem enums verified")
    sys.exit(0 if ok else 1)
```

- [ ] **Step 3: Run test to verify it currently fails**

Run: `conda run -n helao --no-capture-output python helao/core/tests/unit_test_echem_params.py`
Expected: FAIL — `ModuleNotFoundError: helao.core.models.echem_params` if Step 1 not saved, else PASS. (If Step 1 is already saved, this step instead confirms PASS; that is acceptable — the module and test are one deliverable.)

- [ ] **Step 4: Register in the aggregated runner**

In `run_unit_tests.py`, after the `unit_test_base_endpoints` import line add:

```python
from helao.core.tests.unit_test_echem_params import echem_params_unit_test
```

and in the `TESTS` list, after the `("base_endpoints", base_endpoints_unit_test),` entry add:

```python
    ("echem_params", echem_params_unit_test),
```

- [ ] **Step 5: Run the core test + full suite to verify PASS**

Run: `conda run -n helao --no-capture-output python helao/core/tests/unit_test_echem_params.py`
Expected: `PASS: unit_test_echem_params — shared echem enums verified`

Run: `conda run -n helao --no-capture-output python run_unit_tests.py`
Expected: summary table, `echem_params: PASS`, overall exit 0.

- [ ] **Step 6: Gates + black + commit + push**

```bash
conda run -n helao --no-capture-output python helao/core/tests/test_orch_dispatch_golden_master.py --check
conda run -n helao --no-capture-output python helao/core/tests/test_active_golden_master.py --check
conda run -n helao --no-capture-output black helao/core/models/echem_params.py helao/core/tests/unit_test_echem_params.py run_unit_tests.py
git add helao/core/models/echem_params.py helao/core/tests/unit_test_echem_params.py run_unit_tests.py
git commit -m "feat(core): shared echem authoring enums + resolve_* coercion (CARDS Domain-Integrity T1)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
git push -u origin feat/cards-domain-enums
```
Expected: dispatch GM 9/9, active GM 13/13, both green; push succeeds.

---

### Task 2: Harden `potential_versus` (ECHE ×2, ADSS ×2) + hte dispatch test

**Files:**
- Modify: `helao/deploy/hte/experiments/ECHE_exp.py` (dispatch at `:364`, `:568`)
- Modify: `helao/deploy/hte/experiments/ADSS_exp.py` (dispatch at `:977`, `:1181`)
- Create: `helao/deploy/hte/tests/test_echem_dispatch.py`

**Interfaces:**
- Consumes: `resolve_potential_versus` from `helao.core.models.echem_params` (Task 1).
- Produces: `helao/deploy/hte/tests/test_echem_dispatch.py` exposing `echem_dispatch_test() -> bool` (later tasks extend it).

**Behavior audit (do first, record in commit body):**

- [ ] **Step 1: Audit tracked `potential_versus` values**

Run: `grep -rn 'potential_versus' helao/deploy/hte/experiments/ | grep -v archive`
Expected: every assigned/compared literal is in `{rhe, oer}`. Record the distinct values seen in the commit body. If any out-of-catalog literal appears, STOP and report — it is either a latent bug or a missing enum member (add to `PotentialVersus` in Task 1 first).

- [ ] **Step 2: Write the failing dispatch test**

Create `helao/deploy/hte/tests/test_echem_dispatch.py`. The test calls the real experiment function offline, captures the `run_CA` action via a patched `ActionPlanMaker.add`, and asserts the computed `Vval__V` for a valid input equals the legacy formula, and that an unknown `potential_versus` raises `ValueError`:

```python
"""Dispatch-hardening proof for hte echem reference-frame params.

Standalone script. Calls hte experiment functions offline, captures the
PSTAT run_CA action_params via a patched ActionPlanMaker.add, and asserts:
(1) valid inputs produce the identical computed potential as before, and
(2) an out-of-catalog reference-frame value now raises a catalogued
ValueError instead of silently mis-handling / KeyError / UnboundLocalError.
"""

__all__ = ["echem_dispatch_test"]

import sys
import traceback

import helao.helpers.premodels as premodels_mod
from helao.helpers.constants import REF_TABLE
from helao.core.tests._test_utils import TestReporter
from helao.deploy.hte.experiments.ECHE_exp import ECHE_sub_CA


def _capture_actions(fn, **kwargs):
    captured = []
    orig_add = premodels_mod.ActionPlanMaker.add

    def patched_add(self, *a, **kw):
        orig_add(self, *a, **kw)
        captured.append(self.planned_actions[-1])

    premodels_mod.ActionPlanMaker.add = patched_add
    try:
        fn(**kwargs)
    finally:
        premodels_mod.ActionPlanMaker.add = orig_add
    return captured


def _action_by_name(actions, name):
    return next(a for a in actions if a.action_name == name)


def _raises_value_error(fn):
    try:
        fn()
    except ValueError:
        return True
    except Exception:
        return False
    return False


def _check_potential_versus(reporter):
    reporter.section("potential_versus dispatch (ECHE_sub_CA)")
    # Baseline kwargs: choose values so the computed potential is deterministic.
    base = dict(
        CA_potential=1.0,
        CA_duration_sec=1.0,
        samplerate_sec=0.1,
        ref_offset__V=0.0,
        solution_ph=7.0,
        ref_type="inhouse",
        gamrychannelwait=-1,
        gamrychannelsend=-1,
        gamry_i_range="auto",
    )

    # vs rhe (default), ref_type inhouse -> uses the else branch:
    # potential = CA_potential - ref_offset__V + versus(0) - 0.059*ph - REF_TABLE['inhouse']
    actions = _capture_actions(ECHE_sub_CA, potential_versus="rhe", **base)
    run_ca = _action_by_name(actions, "run_CA")
    expected_rhe = 1.0 - 0.0 + 0.0 - 0.059 * 7.0 - REF_TABLE["inhouse"]
    reporter.check(
        "potential_versus='rhe' -> identical Vval__V",
        lambda a=run_ca, e=expected_rhe: a.action_params["Vval__V"] == e,
    )

    # vs oer adds 1.23
    actions = _capture_actions(ECHE_sub_CA, potential_versus="oer", **base)
    run_ca = _action_by_name(actions, "run_CA")
    expected_oer = 1.0 - 0.0 + 1.23 - 0.059 * 7.0 - REF_TABLE["inhouse"]
    reporter.check(
        "potential_versus='oer' -> identical Vval__V (+1.23)",
        lambda a=run_ca, e=expected_oer: a.action_params["Vval__V"] == e,
    )

    # unknown value now raises (was silently treated as rhe)
    reporter.check(
        "potential_versus='bogus' raises ValueError",
        lambda: _raises_value_error(
            lambda: _capture_actions(ECHE_sub_CA, potential_versus="bogus", **base)
        ),
    )


def echem_dispatch_test() -> bool:
    reporter = TestReporter("echem_dispatch")
    try:
        _check_potential_versus(reporter)
        return reporter.success()
    except Exception as exc:  # noqa: BLE001
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        print(repr(exc), tb)
        return False


if __name__ == "__main__":
    ok = echem_dispatch_test()
    if ok:
        print("PASS: test_echem_dispatch — hte reference-frame dispatch verified")
    sys.exit(0 if ok else 1)
```

> **NOTE for implementer:** verify the real `ECHE_sub_CA` signature/param names at `ECHE_exp.py:265-290` before finalizing `base` — copy the actual kwarg names. If `ECHE_sub_CA` is not the function at `:364`, use whichever experiment function owns that dispatch block (check the `def` above line 364). The mechanism (capture `run_CA`, compare `Vval__V`) is unchanged.

- [ ] **Step 3: Run test to verify the `bogus` case fails**

Run: `conda run -n helao --no-capture-output python helao/deploy/hte/tests/test_echem_dispatch.py`
Expected: FAIL — the `potential_versus='bogus' raises ValueError` check fails (today it is silently treated as rhe, so no error is raised).

- [ ] **Step 4: Harden the four dispatch sites**

At each of `ECHE_exp.py:364`, `ECHE_exp.py:568`, `ADSS_exp.py:977`, `ADSS_exp.py:1181`, insert a coercion line immediately before the `if potential_versus == "oer":` line, at the same indentation:

```python
    potential_versus = resolve_potential_versus(potential_versus)
    if potential_versus == "oer":
        versus = 1.23
```

Add the import at the top of each file (next to the existing `from helao.helpers.constants import REF_TABLE`):

```python
from helao.core.models.echem_params import resolve_potential_versus
```

Do NOT change the `if` body, the `versus` value, or anything downstream — the coerced enum compares `== "oer"` identically.

- [ ] **Step 5: Run test to verify PASS**

Run: `conda run -n helao --no-capture-output python helao/deploy/hte/tests/test_echem_dispatch.py`
Expected: `PASS: test_echem_dispatch — hte reference-frame dispatch verified` (valid inputs identical, bogus now raises).

- [ ] **Step 6: Gates + black + commit + push**

```bash
conda run -n helao --no-capture-output python helao/core/tests/test_orch_dispatch_golden_master.py --check
conda run -n helao --no-capture-output python helao/core/tests/test_active_golden_master.py --check
conda run -n helao --no-capture-output python run_unit_tests.py
conda run -n helao --no-capture-output python -c "import helao.deploy.hte.experiments.ECHE_exp, helao.deploy.hte.experiments.ADSS_exp"
conda run -n helao --no-capture-output black helao/deploy/hte/experiments/ECHE_exp.py helao/deploy/hte/experiments/ADSS_exp.py helao/deploy/hte/tests/test_echem_dispatch.py
git add helao/deploy/hte/experiments/ECHE_exp.py helao/deploy/hte/experiments/ADSS_exp.py helao/deploy/hte/tests/test_echem_dispatch.py
git commit -m "refactor(hte): harden potential_versus dispatch via PotentialVersus coercion (CARDS Domain-Integrity T2)

Audited tracked potential_versus literals: {record values here}. Out-of-catalog
value now raises catalogued ValueError instead of silently defaulting to rhe.
Wire byte-identical (coercion is local; not written to action_params).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
git push
```

---

### Task 3: Harden `WE_versus` (ANEC ×7, ECMS ×4) + extend dispatch test

**Files:**
- Modify: `helao/deploy/hte/experiments/ANEC_exp.py` (dispatch at `:931`, `:997`, `:1153`, `:1253`, `:1357`, `:1517`, `:1800`)
- Modify: `helao/deploy/hte/experiments/ECMS_exp.py` (dispatch at `:759`, `:967`, `:1711`; plus any other live `if WE_versus == "ref":` found — NOT the commented blocks at `:841`, `:1505`)
- Modify: `helao/deploy/hte/tests/test_echem_dispatch.py` (add a WE_versus section)

**Interfaces:**
- Consumes: `resolve_we_versus` from `helao.core.models.echem_params` (Task 1); `echem_dispatch_test` reporter from Task 2.

- [ ] **Step 1: Audit tracked `WE_versus` values**

Run: `grep -rn 'WE_versus' helao/deploy/hte/experiments/ANEC_exp.py helao/deploy/hte/experiments/ECMS_exp.py | grep -v '#'`
Expected: every live literal is in `{ref, rhe}`. Record distinct values in the commit body. Out-of-catalog literal → STOP and report (widen `WEVersus` in Task 1 first).

- [ ] **Step 2: Enumerate the live dispatch sites**

Run: `grep -rn 'if WE_versus == "ref":' helao/deploy/hte/experiments/ANEC_exp.py helao/deploy/hte/experiments/ECMS_exp.py`
Confirm the set matches the Files list (exclude commented `#` lines). Each live site is an `if WE_versus == "ref": ... elif WE_versus == "rhe": ...` with **no else** (unknown → `potential_vsRef` unbound → `UnboundLocalError`).

- [ ] **Step 3: Add the failing test section**

In `helao/deploy/hte/tests/test_echem_dispatch.py`, import an ANEC function that owns the `:931` block (verify the `def` above `:931`; assume `ANEC_sub_CA` — correct to the real name) and add:

```python
from helao.deploy.hte.experiments.ANEC_exp import ANEC_sub_CA  # verify real name at :931


def _check_we_versus(reporter):
    reporter.section("WE_versus dispatch (ANEC)")
    base = dict(
        WE_potential__V=1.0,
        CA_duration_sec=1.0,
        SampleRate=0.1,
        ref_offset__V=0.0,
        pH=7.0,
        ref_type="inhouse",
        IErange="auto",
    )  # verify/copy the real signature at ANEC_exp.py:~907

    actions = _capture_actions(ANEC_sub_CA, WE_versus="ref", **base)
    run_ca = _action_by_name(actions, "run_CA")
    expected_ref = 1.0 - 1.0 * 0.0
    reporter.check(
        "WE_versus='ref' -> identical Vval__V",
        lambda a=run_ca, e=expected_ref: a.action_params["Vval__V"] == e,
    )

    actions = _capture_actions(ANEC_sub_CA, WE_versus="rhe", **base)
    run_ca = _action_by_name(actions, "run_CA")
    expected_rhe = 1.0 - 1.0 * 0.0 - 0.059 * 7.0 - REF_TABLE["inhouse"]
    reporter.check(
        "WE_versus='rhe' -> identical Vval__V",
        lambda a=run_ca, e=expected_rhe: a.action_params["Vval__V"] == e,
    )

    reporter.check(
        "WE_versus='bogus' raises ValueError",
        lambda: _raises_value_error(
            lambda: _capture_actions(ANEC_sub_CA, WE_versus="bogus", **base)
        ),
    )
```

and call it inside `echem_dispatch_test`:

```python
        _check_potential_versus(reporter)
        _check_we_versus(reporter)
```

- [ ] **Step 4: Run test to verify the `bogus` case fails**

Run: `conda run -n helao --no-capture-output python helao/deploy/hte/tests/test_echem_dispatch.py`
Expected: FAIL — today `WE_versus='bogus'` raises `UnboundLocalError`, not `ValueError`, so `_raises_value_error` returns `False`.

- [ ] **Step 5: Harden every live WE_versus site**

At each live site, insert immediately before the `if WE_versus == "ref":` line, at the same indentation:

```python
    WE_versus = resolve_we_versus(WE_versus)
    if WE_versus == "ref":
```

Add the import at the top of `ANEC_exp.py` and `ECMS_exp.py`:

```python
from helao.core.models.echem_params import resolve_we_versus
```

Coercion guarantees the value is `ref` or `rhe`, so the existing `if/elif` is now exhaustive and `potential_vsRef` is always bound. Do not add an `else` branch (unreachable) and do not alter the arithmetic.

- [ ] **Step 6: Run test to verify PASS**

Run: `conda run -n helao --no-capture-output python helao/deploy/hte/tests/test_echem_dispatch.py`
Expected: PASS (both WE_versus branches identical, bogus now raises `ValueError`).

- [ ] **Step 7: Gates + black + commit + push**

```bash
conda run -n helao --no-capture-output python helao/core/tests/test_orch_dispatch_golden_master.py --check
conda run -n helao --no-capture-output python helao/core/tests/test_active_golden_master.py --check
conda run -n helao --no-capture-output python run_unit_tests.py
conda run -n helao --no-capture-output python -c "import helao.deploy.hte.experiments.ANEC_exp, helao.deploy.hte.experiments.ECMS_exp"
conda run -n helao --no-capture-output black helao/deploy/hte/experiments/ANEC_exp.py helao/deploy/hte/experiments/ECMS_exp.py helao/deploy/hte/tests/test_echem_dispatch.py
git add helao/deploy/hte/experiments/ANEC_exp.py helao/deploy/hte/experiments/ECMS_exp.py helao/deploy/hte/tests/test_echem_dispatch.py
git commit -m "refactor(hte): harden WE_versus dispatch via WEVersus coercion (CARDS Domain-Integrity T3)

Audited tracked WE_versus literals: {record values here}. Out-of-catalog value
now raises catalogued ValueError instead of leaving potential_vsRef unbound
(UnboundLocalError). Wire byte-identical.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
git push
```

---

### Task 4: `ref_type` → `ref_offset()` sweep + extend dispatch test

**Files:**
- Modify: `helao/deploy/hte/experiments/ECHE_exp.py`, `ADSS_exp.py`, `ANEC_exp.py`, `ECMS_exp.py` — replace every `REF_TABLE[ref_type]` subscript (see full anchor list below)
- Modify: `helao/deploy/hte/tests/test_echem_dispatch.py` (add a ref_type section)

**Anchors (verify with grep at execution — line numbers drift as earlier tasks insert lines):**
Run `grep -rn 'REF_TABLE\[ref_type\]' helao/deploy/hte/experiments/ | grep -v archive` to get the live set. As surveyed: ECHE_exp (`:374,578,734,738,742,746,837,841,845,849`), ADSS_exp (`:987,1191,1378,1382,1386,1390`), ANEC_exp (`:935,1001,1263,1269,1275,1281,1367,1373,1379,1385,1527,1533,1539,1545,1808,1814`), ECMS_exp (`:763,977,983,989,995,1715`). ~38 live sites.

**Interfaces:**
- Consumes: `ref_offset` from `helao.core.models.echem_params` (Task 1).

- [ ] **Step 1: Audit tracked `ref_type` values**

Run: `grep -rn 'ref_type' helao/deploy/hte/experiments/ | grep -v archive | grep -v REF_TABLE`
Expected: every default/literal in `{leakless, inhouse, rhe}`. Record in commit body. Out-of-catalog → STOP (widen `RefType` in Task 1).

- [ ] **Step 2: Add the failing test section**

In `helao/deploy/hte/tests/test_echem_dispatch.py`, add a check that an unknown `ref_type` raises `ValueError` (not `KeyError`). Reuse `ECHE_sub_CA` + `base` from `_check_potential_versus` but override `ref_type`:

```python
def _check_ref_type(reporter):
    reporter.section("ref_type dispatch (ECHE_sub_CA)")
    base = dict(
        CA_potential=1.0,
        CA_duration_sec=1.0,
        samplerate_sec=0.1,
        ref_offset__V=0.0,
        solution_ph=7.0,
        gamrychannelwait=-1,
        gamrychannelsend=-1,
        gamry_i_range="auto",
        potential_versus="rhe",
    )
    # leakless and inhouse both map to 0.21 today — identical potential
    actions = _capture_actions(ECHE_sub_CA, ref_type="leakless", **base)
    run_ca = _action_by_name(actions, "run_CA")
    expected = 1.0 - 0.0 + 0.0 - 0.059 * 7.0 - REF_TABLE["leakless"]
    reporter.check(
        "ref_type='leakless' -> identical Vval__V",
        lambda a=run_ca, e=expected: a.action_params["Vval__V"] == e,
    )
    reporter.check(
        "ref_type='bogus' raises ValueError (was KeyError)",
        lambda: _raises_value_error(
            lambda: _capture_actions(ECHE_sub_CA, ref_type="bogus", **base)
        ),
    )
```

and call `_check_ref_type(reporter)` in `echem_dispatch_test`.

- [ ] **Step 3: Run test to verify the `bogus` case fails**

Run: `conda run -n helao --no-capture-output python helao/deploy/hte/tests/test_echem_dispatch.py`
Expected: FAIL — today `ref_type='bogus'` raises `KeyError`, so `_raises_value_error` returns `False`.

- [ ] **Step 4: Sweep the subscripts**

For every live `REF_TABLE[ref_type]` in the four files, replace exactly:

```python
- REF_TABLE[ref_type]
```
with
```python
- ref_offset(ref_type)
```

(The surrounding `- ` and expression stay; only the `REF_TABLE[ref_type]` token becomes `ref_offset(ref_type)`.) Add the import to each of the four files (fold into the existing `echem_params` import line where one was already added):

```python
from helao.core.models.echem_params import ref_offset
```

Then remove the now-unused `from helao.helpers.constants import REF_TABLE` import **only if** no other `REF_TABLE[...]` usage remains in that file (re-grep per file; ECHE/ADSS/ANEC/ECMS may have no other users — verify, do not assume).

- [ ] **Step 5: Run test to verify PASS**

Run: `conda run -n helao --no-capture-output python helao/deploy/hte/tests/test_echem_dispatch.py`
Expected: PASS (valid ref_type identical potential, bogus raises `ValueError`).

- [ ] **Step 6: Gates + black + commit + push**

```bash
conda run -n helao --no-capture-output python helao/core/tests/test_orch_dispatch_golden_master.py --check
conda run -n helao --no-capture-output python helao/core/tests/test_active_golden_master.py --check
conda run -n helao --no-capture-output python run_unit_tests.py
conda run -n helao --no-capture-output python -c "import helao.deploy.hte.experiments.ECHE_exp, helao.deploy.hte.experiments.ADSS_exp, helao.deploy.hte.experiments.ANEC_exp, helao.deploy.hte.experiments.ECMS_exp"
conda run -n helao --no-capture-output black helao/deploy/hte/experiments/ECHE_exp.py helao/deploy/hte/experiments/ADSS_exp.py helao/deploy/hte/experiments/ANEC_exp.py helao/deploy/hte/experiments/ECMS_exp.py helao/deploy/hte/tests/test_echem_dispatch.py
git add -u helao/deploy/hte/experiments/ helao/deploy/hte/tests/test_echem_dispatch.py
git commit -m "refactor(hte): route ref_type through ref_offset() for catalogued errors (CARDS Domain-Integrity T4)

Replace ~38 REF_TABLE[ref_type] subscripts with ref_offset(ref_type): same
float value, but an unknown ref_type now raises a catalogued ValueError instead
of an opaque KeyError. Audited tracked ref_type literals: {record values here}.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
git push
```

---

### Task 5 (OPTIONAL — reviewer may cut): BubbleGas / Electrolyte annotation adoption

**Rationale for optional:** the survey found no dispatch bug for `solution_bubble_gas` or `Electrolyte`; they are metadata-only today. This task provides the enums as future-facing types (annotation + optional validation) with zero behavior change. Skip if the reviewer prefers to keep Phase 1 to the bug-fix trio. `BubbleGas` and `resolve_bubble_gas` already exist from Task 1; `Electrolyte` already exists in `helao/core/models/electrolyte.py`.

**Files:**
- Modify (optional): `helao/deploy/hte/experiments/*.py` signatures annotating `solution_bubble_gas: BubbleGas = "N2"` where the param exists.

- [ ] **Step 1: Decide + (if adopting) annotate**

If adopting: change `solution_bubble_gas: str = "N2"` → `solution_bubble_gas: BubbleGas = "N2"` in the ~14 signatures that declare it (defaults stay the string). Do NOT coerce or validate in the body (no dispatch exists; keeps wire identical). Import `BubbleGas` where annotated.

If cutting: record the decision in the Task 6 review notes and proceed. No commit.

- [ ] **Step 2 (if adopted): Gates + black + commit + push**

```bash
conda run -n helao --no-capture-output python run_unit_tests.py
conda run -n helao --no-capture-output black <changed files>
git add -u helao/deploy/hte/experiments/
git commit -m "refactor(hte): annotate solution_bubble_gas with BubbleGas enum (CARDS Domain-Integrity T5)

Annotation only; defaults unchanged, no body dispatch, wire byte-identical.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
git push
```

---

### Task 6: Whole-branch review + e2e sanity + Phase-2 handoff note

**Files:**
- Modify: `docs/superpowers/specs/2026-07-14-domain-integrity-typed-params-design.md` (append a "Phase 1 outcome" note)

**Interfaces:** none (verification + docs).

- [ ] **Step 1: Full gate sweep**

```bash
conda run -n helao --no-capture-output python helao/core/tests/test_orch_dispatch_golden_master.py --check
conda run -n helao --no-capture-output python helao/core/tests/test_active_golden_master.py --check
conda run -n helao --no-capture-output python run_unit_tests.py
conda run -n helao --no-capture-output python helao/deploy/hte/tests/test_echem_dispatch.py
```
Expected: dispatch GM 9/9, active GM 13/13, suite overall PASS (incl. `echem_params`), dispatch test PASS.

- [ ] **Step 2: e2e no-regression sanity (shared-core import surface)**

Run: `.omc/artifacts/p3/run_e2e.sh domain_enums` then `.omc/artifacts/p3/compare_runs.py` on index-collapsed norms vs a pre-branch baseline (the `test`/OERSIM deployment does not use these hte enums, so this proves the shared-core module addition did not perturb the e2e path). If the harness/baseline is absent, record that e2e was skipped and why (Linux OERSIM only; hte dispatch is covered by `test_echem_dispatch.py`, not e2e).

- [ ] **Step 3: Opus code review**

Dispatch an `oh-my-claudecode:code-reviewer` (or `critic`) over the branch diff `git diff unstable...feat/cards-domain-enums`. Require 0 blocking findings; apply any fixes as follow-up commits and re-run Step 1.

- [ ] **Step 4: Append Phase-1 outcome to the spec + commit**

Add a short "Phase 1 outcome (YYYY-MM-DD)" section to the design doc recording: enums shipped, sites hardened per param, audit findings (the recorded literal sets), gates green, and the Phase-2 to-do (private deployments import the core enums; Deployment-C adds its own `RefElectrodeType` + `none`-bearing bubble-gas enums per the spec's Phase 2). Commit + push.

```bash
conda run -n helao --no-capture-output black docs/ 2>/dev/null || true
git add docs/superpowers/specs/2026-07-14-domain-integrity-typed-params-design.md
git commit -m "docs(cards): Domain-Integrity Phase 1 outcome + Phase 2 handoff

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
git push
```

- [ ] **Step 5: Report Phase-1 completion**

Summarize to the user: branch state, gates, audit evidence, and the Phase-2 (private-deployment) follow-on. Do NOT merge to `unstable` — merge is the user's call (hte-production is soak/station-gated, consistent with the CARDS program).

---

## Self-Review

**Spec coverage:**
- Core enums (RefType/PotentialVersus/WEVersus/BubbleGas) + resolvers → Task 1. ✓
- Dispatch hardening: potential_versus → T2, WE_versus → T3, ref_type → T4. ✓
- Electrolyte enforcement → T5 (optional, per spec "optional tail, not gating"). BubbleGas → T1 def + T5 adoption. ✓
- Behavior-delta gating (audit per site) → Steps 1 of T2/T3/T4. ✓
- Byte-identity proof (unit + e2e + GMs) → each task's gate + T6 e2e. ✓
- Phase 2 (private deploys) → T6 Step 4 handoff (execution is a separate future plan per spec). ✓

**Placeholder scan:** The `{record values here}` tokens in commit messages are intentional audit-output capture, not code placeholders. The `verify the real signature` notes are real instructions (line numbers drift; signatures must be copied from source) — the test *mechanism* is fully specified. No TODO/TBD in code.

**Type consistency:** `resolve_potential_versus`/`resolve_we_versus`/`resolve_ref_type`/`resolve_bubble_gas`/`ref_offset` names identical across Task 1 def, tests, and dispatch edits. Enum member names (`.oer`/`.ref`/`.rhe`/`.n2`) consistent. `echem_dispatch_test`/`echem_params_unit_test` callable names match their registrations.

**Known execution risk:** experiment-function signatures (kwarg names for the offline test `base` dicts) must be copied from source at execution — the plan flags this at every test-construction step. If a target function turns out not to be offline-importable (unexpected hardware import), the implementer reports it rather than stubbing.
