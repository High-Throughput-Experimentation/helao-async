# Domain-Integrity: Domain Enums + Dispatch Hardening

**Date:** 2026-07-14
**Status:** Approved design → implementation planning
**Branch (planned):** `feat/cards-domain-enums` off `unstable`
**CARDS lever:** Domain-Integrity (audit fix #2/#3). Top remaining core lever after Separation/Clarity landed strong (P4–P6).

## Problem

The CARDS audit named the untyped-dict param contract the root cause of stringly-typed
code across the fleet. The P3d pilot (`helao/deploy/test/param_models.py`) proved the
remedy on 6 sim payloads — a `StopCondition` StrEnum + `resolve_stop_condition` coercion
that raises a clear error instead of a bare `KeyError`, and caught a real bug (a
`stop_condtion` typo that silently defeated the authored stop condition).

A survey of the `hte` deployment shows the *literal* pilot pattern does not scale: ~3,200
`apm.add`/`epm.add` payload dicts across 243 experiment + 86 sequence functions (~39k
lines), and easily 6,000–8,000+ sites across all four deployments. Wrapping every payload
in a pydantic model would be a full rewrite of the experiment library × 4 repos, and would
duplicate the receiving action-server endpoint signatures as a second, drift-prone source
of truth. **We do not do that.**

Instead we target the same *failure family* the pilot caught: recurrent stringly domain
values with a small closed set of valid literals, dispatched with silent fallthrough. The
survey found several latent bugs of exactly this kind (anchors verified 2026-07-14):

- **`potential_versus`** (`ECHE_exp.py:364,568`; `ADSS_exp.py:977,1181`) — `if potential_versus == "oer": ...`
  with no `else`. Any value other than exactly `"oer"` silently means `"rhe"` (offset 0).
  A typo silently applies the wrong reference frame. **Genuinely silent.**
- **`WE_versus`** (`ANEC_exp.py:931,933,997,999,…`; `ECMS_exp.py`) — `if WE_versus == "ref": ... elif WE_versus == "rhe": ...`
  with no `else`. A mismatched literal silently skips **all** branches → no potential
  correction applied. Default is `"ref"`. **Genuinely silent.** Domain values are
  `{ref, rhe}` — distinct from `potential_versus`'s `{rhe, oer}`.
- **`ref_type`** (`ECHE_exp.py:366,374`; `ADSS_exp.py:979,1183`) — `REF_TABLE[ref_type]`
  where `REF_TABLE = {"leakless":0.21, "inhouse":0.21, "rhe":0.0}` (`helao/helpers/constants.py:20`).
  Unknown/mis-cased value → hard `KeyError` at lookup (a loud crash, not silent) — but with
  an opaque message. Coercion gives a clear, catalogued error at the boundary instead.
- **`Electrolyte`** — already a `class Electrolyte(str, Enum)` (`helao/core/models/electrolyte.py:7`,
  16 members incl. `other`), but experiment signatures annotate it as *informational only*
  and pass the raw `.value` string. Out-of-catalog electrolytes pass unvalidated.

## Goals / Non-Goals

**Goals**
- Introduce shared StrEnums as the single source of truth for the high-value stringly
  domain values, in `helao/core/models/` so every deployment imports the same type.
- Replace silent-fallthrough dispatch with enum coercion that raises a clear, catalogued
  error on unknown values (the bug-fix payload).
- Keep the wire byte-identical: enums are `str, Enum`, `== "rhe"` comparisons stay valid,
  `.value` on the wire is unchanged. Prove via the existing `.omc/artifacts/p3` e2e sim
  gate + unit equivalence, exactly as the pilot did.
- Apply across all deployments (Q1 decision), core-enum once, per-repo adoption.

**Non-Goals (explicitly cut — YAGNI)**
- Exhaustive `apm.add`/`epm.add` payload wrapping (~6-8k sites). Not viable, not desired.
- Per-endpoint action-server param models. (Considered; cut. May revisit as a separate
  spec if a concrete need appears.)
- `SampleModel.sample_type → enum` and the central run-state enum — deferred earlier
  (cross-producer-blocked; each its own future increment).
- Low-value stringly params (`illumination_source`, `toggle_source`, `spec_technique`,
  `gamry_i_range`) — optional tail, not gating. May be folded in opportunistically.

## Design

### 1. Core domain enums (`helao/core/models/`)

New `str, Enum` types (values verbatim from current literals, so `.value` is byte-identical):

| Enum | Members (value) | Replaces | Sites (hte) |
|---|---|---|---|
| `PotentialVersus` | `rhe`, `oer` | `potential_versus: str` in ECHE/ADSS | ~8 dispatch, ~4 sigs |
| `WEVersus` | `ref`, `rhe` | `WE_versus: str` in ANEC/ECMS | ~13 dispatch |
| `RefType` | `leakless`, `inhouse`, `rhe` | `ref_type: str` + `REF_TABLE` keys | ~50 |
| `BubbleGas` | `N2`, `O2` | `solution_bubble_gas`/gas defaults | ~14 |

`Electrolyte` already exists — reuse, do not redefine.

Each enum ships a `resolve_<name>(value) -> Enum` coercion helper following the pilot's
`resolve_stop_condition` shape:

```python
def resolve_potential_versus(value) -> PotentialVersus:
    try:
        return PotentialVersus(value)
    except ValueError:
        valid = ", ".join(m.value for m in PotentialVersus)
        raise ValueError(f"invalid potential_versus {value!r}; valid: {valid}") from None
```

Placement: one module per enum under `helao/core/models/` (matches the existing
`electrolyte.py` / `run_use.py` / `run_dir.py` one-type-per-file convention), or a single
`domain_enums.py` grouping the electrochem-frame trio + `BubbleGas`. **Decision for the
plan:** follow the existing one-file-per-enum convention; group only the coercion helpers
if that reads cleaner. `RefType` co-locates with a hardened `REF_TABLE` lookup keyed by the
enum (or a `resolve_ref_type` that both validates and returns the offset).

### 2. Dispatch hardening (hte, Phase 1)

At each identified dispatch site, coerce the incoming value through `resolve_*` at the top
of the branch region, then branch on the enum. Replace the silent no-`else` structure so an
unknown value raises the catalogued error rather than silently choosing a default or
skipping correction.

- `potential_versus` → `resolve_potential_versus`, branch on `PotentialVersus.oer`.
- `WE_versus` → `resolve_we_versus`, branch on `WEVersus.ref` / `.rhe`.
- `ref_type` → `resolve_ref_type` returning the offset (folds the `REF_TABLE` lookup),
  clear error on unknown instead of raw `KeyError`.
- `Electrolyte` → validate at the boundary (coerce; clear error on out-of-catalog).

Signatures may adopt the enum annotation (informational → enforced); **defaults stay the
same string values** so wire and schema defaults are unchanged.

### 3. Behavior-delta gating

Raise-on-unknown is an **intentional behavior change** (previously-silent bad value now
errors loudly; previously-`KeyError` now errors clearly). Same discipline as 3d's typo fix:
before flipping each site, audit that no production sequence/config passes an out-of-catalog
value. Method: grep the tracked sequence/experiment defaults + the corpus-replay harness
(`.omc/artifacts/p3/`) / production run indices for the affected param values. Any
out-of-catalog literal found is either a latent bug to report or a missing enum member to
add — resolved before the flip, not swallowed.

### 4. Byte-identity proof (unchanged from pilot)

- Unit equivalence: enum `.value` == the string it replaces, for every member.
- e2e: `.omc/artifacts/p3/run_e2e.sh` OERSIM run + `compare_runs.py` on index-collapsed
  norms (the `test` deployment doesn't use these hte enums, so the e2e gate proves *no
  regression* to the shared-core import surface, not the hte dispatch itself).
- hte dispatch behavior: targeted unit tests per hardened site (valid → same branch as
  before; unknown → raises catalogued `ValueError`). This is the primary correctness gate
  for Phase 1, since hte dispatch is not exercised by the OERSIM e2e.
- Standard CARDS gates every stage: dispatch golden master `--check` (9/9), active golden
  master `--check` (13/13), `python run_unit_tests.py` PASS, import check.

## Scope split

**Phase 1 (public parent repo, `hte`)**
1. Core enums + `resolve_*` helpers in `helao/core/models/`.
2. hte dispatch hardening at the surveyed sites (ECHE/ADSS/ANEC/ECMS).
3. Behavior-delta audit per site; unit tests; gates.

**Phase 2 (private deployments — aliased Deployment-A/B/C in this public spec)**

A survey of the private deployments (2026-07-14) settled the member-completeness risk for
the four Phase-1 enums: **none of them are extended by the private deployments.** Findings:

- Deployment-A/-B: no in-scope electrochemical `*_versus` / `ref_type` / gas-identity
  string params at all (non-electrochem workflows, or the tokens are bools/float
  temperatures, not stringly enums). Where a `ref_type` appears it uses `inhouse` (already
  a `RefType` member) and imports the shared `REF_TABLE`. Nothing to widen.
- Deployment-C (droplet cell): has two relevant literals, but on **differently-named,
  different-concept** params — a reference-*electrode-chemistry* field (`Ag/AgCl`, distinct
  from the REF_TABLE-offset `RefType`) and a bubble field carrying a `none` "no-bubbling"
  sentinel (distinct from N2/O2 gas identity). These are **their own** small enums
  (a `RefElectrodeType`, a nullable/`none`-bearing bubble-gas), not extensions of the
  Phase-1 four.

So Phase 2 is: each private deployment imports the Phase-1 core enums where the *same*
domain applies (mostly it doesn't), and Deployment-C separately introduces its own two
small enums for its distinct params. No Phase-1 enum member changes. Core stays the single
source of truth; no redefinition. Per-repo commits inside each nested repo's own git (never
named in tracked parent-repo files; see the deployment-alias convention).

## Risks / open questions

- **Enum member completeness.** Private deployments were surveyed (2026-07-14) and do NOT
  extend the four enums (see Phase 2). Remaining exposure is the **hte** production-config
  space: the survey captured literals from tracked defaults, not every value a saved
  sequence/config may carry. The Phase-1 audit (§3) must widen each enum's membership to
  cover any real hte config value before the raise-on-unknown flip, or a live run will crash
  on a value that used to "work" (silently wrong). This is the main remaining risk.
- **`ref_type` semantics.** `leakless` and `inhouse` both map to 0.21 today. Folding the
  offset into `resolve_ref_type` must preserve that exactly.
- **Experiment param arrival.** Experiment functions receive params via the decorator /
  `ExperimentPlanMaker` (`apm.pars`), not raw FastAPI fn-args. Coercion happens where the
  value is *read for dispatch*, so the P4 "read from action_params not fn-args" hazard does
  not directly apply here — but confirm the coercion site sees the authored value, not a
  signature default, before trusting it.
- **Phase-2 private surface unknown.** This spec sizes hte only. Each private deployment
  needs its own quick survey during Phase 2 execution.

## Verification summary

Per-stage: unit equivalence + per-site dispatch unit tests + dispatch GM 9/9 + active GM
13/13 + `run_unit_tests.py` PASS + import check. Behavior-delta audit evidence recorded per
hardened site. Run `black` on changed files before each commit; commit + push per increment.
