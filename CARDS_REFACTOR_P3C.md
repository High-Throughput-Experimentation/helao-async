# CARDS Refactor — P3 sub-increment 3c: Discriminated sample union + sample-status lifecycle (Domain Integrity)

> Derived from `CARDS_AUDIT.md` Part 1 Domain Integrity ("Sample `Union` (action.py:142) not
> discriminated; untyped `SampleModel` fallback catches anything"; "base `SampleModel.sample_type:
> Optional[str]` not the enum"; "sample subtypes pin discriminator via `Literal`") and
> `CARDS_REFACTOR_P3.md` §3c sketch + §2.1 (sample-status lifecycle explicitly deferred from 3a to 3c).
> Branch: `feat/cards-refactor`, entry HEAD `9201059d` (clean tree, verified 2026-07-10). Parent repo
> only — **no nested-repo commits in 3c** (mea/priv code is cited as evidence, never edited).
>
> **Risk class: MEDIUM** — changes *validation routing* on the hottest domain models even where output
> shape is identical. Hard constraints: zero serialized-shape change (-act/-exp/-seq/-prc.yml, HLO,
> wire JSON); **no payload the current loose union accepts may be rejected**; hte validated by
> `py_compile`/`compileall` only (Windows drivers, no live hardware). Proof stack: corpus replay
> (the gate, §4), reusable e2e sim harness at `.omc/artifacts/p3/` (working; fresh baseline
> `fixcheck.norm` on this HEAD), suite (`conda run -n helao python run_unit_tests.py`), new unit test.
> Python via `conda run -n helao`. Pydantic **2.13.4** (verified).

---

## 1. Decisions (made, not asked — each backed by an experiment or grep run 2026-07-10)

### D1 — Fallback strategy: **neither (a) drop nor (b) Literal-tag it — use a two-stage nested union that keeps the fallback**

The two options in the P3 §3c sketch are both disproven by evidence:

- **(a) "drop the fallback after proving it's never exercised" is dead.** The fallback IS exercised
  by live in-repo producers: mea builds `SampleModel(..., sample_type="MEA", ...)`
  (`helao/deploy/mea/experiments/AMTS_exp.py:69`, `_mea_sample()` used in `fast_samples_in`) and priv
  builds `SampleModel(..., sample_type="xafs-std-pellet")`
  (`helao/deploy/priv/scripts/xafs/converters.py:188`). Those samples serialize into -exp/-act yml and
  must re-validate forever. Dropping the `SampleModel` member would reject them → violates the hard
  constraint outright, no corpus needed.
- **(b) "give SampleModel a Literal-tagged catch-all" is impossible as stated.** A discriminated union
  routes by *matching* the payload's tag to a member's pinned Literal. Real fallback payloads carry
  arbitrary tags (`"MEA"`, `"xafs-std-pellet"`); no single pinned Literal can catch them. And pinning
  base `SampleModel.sample_type` to a synthetic value would change the serialized `sample_type` of
  every directly-constructed `SampleModel` (`null` → the synthetic value) — a shape change.
- **Additional hard blocker for a flat discriminated union:** `NoneSample` pins
  `sample_type: Literal[None]`, and pydantic 2.13.4 discriminated unions cannot dispatch on a
  `None`/absent tag — verified empirically: including `NoneSample` in
  `Annotated[Union[...], Field(discriminator="sample_type")]` makes `{}`/`{"sample_type": None}` fail
  with `union_tag_not_found`.

**Decision — Design C, two-stage nested union**, defined once in `helao/core/models/sample.py` and
reused everywhere:

```python
TypedSampleUnion = Annotated[
    Union[AssemblySample, LiquidSample, GasSample, SolidSample],
    Field(discriminator="sample_type"),
]
SampleUnion = Union[TypedSampleUnion, NoneSample, SampleModel]
```

- The four enum-tagged subtypes get true discriminator routing (O(1), no smart-mode cross-matching).
- `NoneSample` and the `SampleModel` fallback sit in the outer (smart) union, preserving today's
  acceptance surface **by construction**: anything the discriminated core rejects falls through
  exactly where it falls through today.
- The existing `SampleUnion` name and `__all__` export are kept, so `object_to_sample()`
  (sample.py:485, `parse_obj_as(SampleUnion, data)`) and every importer upgrade for free.

**Empirical equivalence (pydantic 2.13.4, real models, run on this HEAD):** loose vs nested compared
by routed type + `model_dump()` + `model_dump_json()` byte equality over: full python-mode and
json-mode dumps of all five subtypes (enum-instance tags included), minimal/serialized `NoneSample`
(`{"sample_type": null}` and full dump), assembly-with-nested-parts, unknown tag `"weird"`,
`"MEA"`-style fallback dict, tag-present-but-invalid-payload (`volume_ml: "abc"` → degrades to
`SampleModel` under BOTH, identically), `sample_type: null` + `global_label` set (→ `SampleModel`
under both — note: NOT `NoneSample`, which requires `global_label: Literal[None]`). **All EQ except
exactly one case:** a **tag-absent** dict `{}` routes to `AssemblySample` today (smart mode fills the
Literal from its default!) but to `NoneSample` under the nested design (the discriminated core
requires the tag to be present). This is the single declared candidate delta, and it is corpus-gated:
**3c ships only if the corpus replay finds zero tag-absent sample blocks** (§4). Every serialized
sample always carries `sample_type` (model dumps emit all fields — confirmed in real 2023 ADSS
-act.yml blocks), so this is expected to be unexercised; today's `{} → AssemblySample` (an empty dict
silently becoming an assembly with a derived global_label) is precisely the audit's "fallback catches
anything" pathology.

### D2 — `SampleModel.sample_type: Optional[str]` stays. Do NOT tighten to the `SampleType` enum.

Behavior-visible and disproven by the same evidence as D1(a): `"MEA"` and `"xafs-std-pellet"` are
live non-enum values flowing through the base class today (plus historical yml already on disk).
Tightening would reject them at validation. Deferred until mea/priv migrate to declared subtypes or
the enum grows those members — logged as an open question (§9). The audit finding stands as
*documented-and-blocked-by-producers*, which is itself the finding to surface.

### D3 — Sample-status lifecycle: full in-repo routing, mirroring 3a exactly (log-only guards)

Complete mutation-site inventory (grep-verified 2026-07-10) is **larger than the P3 sketch's "×10 +
2"**: core `sample.py:196/198/204/206` (two appends AND two `.remove()` calls — 3a has no remove
primitive), **`base.py:1904`** (missed by the sketch: `sample.status = [SampleStatus.preserved]` in
`Active`'s sample-append normalization), hte `archive_driver.py` ×24, `pal_driver.py` ×20 (incl. the
sketch's 1660/1662), `nidaqmx_driver.py:772`, `spectral_products_driver.py:406`,
`sprintir_driver.py:430`. Full inventory in §6.3.

Decision: route **all** of them. Partial routing leaves the grep-zero gate permanently dirty and
splits telemetry. It is mechanical (~50 substitutions), hte sites are py_compile-gated, and the
routed chokepoint is exactly what the approved PAL/Archive-hoist plan (P4-adjacent) inherits.
Guards are **log-only** (3a policy; enforcement is 3e). Additions to
`helao/core/models/status_transitions.py`: a generic `guarded_remove` plus three sample-status
wrappers (`sample_guarded_append/remove/reset`) — the sample wrappers lazy-import `SampleStatus`
inside the function body to avoid a `sample.py ↔ status_transitions.py` import cycle (sample.py will
import the module for its methods). Sample contradiction pair for the warn: `destroyed` +
`preserved` coexisting (the pair the legacy code actively de-conflicts in `zero_volume`).
Exclusions: `sample.py:164` (`self.status = [self.status]` — a defensive list coercion inside
`create_initial_exp_dict`, not a lifecycle transition; keep verbatim with a comment);
`deploy/mea/notes/**`, `deploy/lila_gl/**` (excluded as in P1–P3); priv (constructor kwargs only —
same rule as 3a §2.1).

### D4 — Corpus replay is the gate, and it runs FIRST (before any code edit)

The replay script (§4) embeds **both** unions locally (it builds the loose and nested unions itself
from the sample classes, independent of what `sample.py` currently ships), so the identical script
proves the design on the pre-change HEAD (T0 go/no-go) and re-proves the shipped alias post-change
(`--use-repo-alias`). Corpus = real production data at `/mnt/STORAGE/INST_hlo/` (9,961 -act.yml +
1,467 -exp.yml + 157 -seq.yml across RUNS_FINISHED/ACTIVE/DIAG; 2023-era ADSS runs with real
solid/liquid sample blocks, verified) + the harness trees `/tmp/hlo_p3_baseline`,
`/tmp/hlo_p3_fixcheck` + a synthetic set covering every subtype and edge from D1. Any payload where
loose and nested disagree (routed type, dump bytes, or success/failure) is a FINDING: it either
blocks 3c or becomes an explicitly declared, evidence-cleared delta.

### D5 — e2e baseline reuse + its known blind spot

`fixcheck.norm` was captured on this exact HEAD (`9201059d`) with a clean tree — it IS the 3c
baseline (D5 purity rule of P3B satisfied; no fresh capture needed). Declared blind spot: **the
OERSIM harness run produces no sample blocks** (grep-verified: zero `sample_type:` in
`/tmp/hlo_p3_fixcheck` ymls) — the e2e diff guards collateral damage (models still validate every
empty `samples_in: []`, orch/base paths, serialization), while sample-payload behavior is gated by
the corpus replay and the new unit test. Both gates are mandatory; neither substitutes for the other.

---

## 2. Current-state evidence (all verified on HEAD 9201059d, 2026-07-10)

| Fact | Where |
|---|---|
| Loose union spelled inline ×6 in model fields: `Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample, SampleModel]` | action.py:143-148 (`samples_in`/`samples_out`), experiment.py:121-126, process.py:77-82 |
| **sequence.py has NO sample fields** — the "twin in sequence.py" from the task brief does not exist (grep-verified) | helao/core/models/sequence.py |
| Two more twins inside sample.py: `AssemblySample.parts` (382-391) and `SampleList.samples` (445-456); `SampleUnion` alias at 459-466; vestigial `ForwardRef` at :32; `from __future__ import annotations` at :1 → string annotations + `model_rebuild()` at 493-494 resolve lazily | helao/core/models/sample.py |
| `NoneSample` pins `sample_type: Literal[None]` AND `global_label: Literal[None]` | sample.py:233-234 |
| Subtypes pin `sample_type` via `Literal[SampleType.x]` with that value as default | sample.py:265, 303, 344, 380 |
| `object_to_sample` = `parse_obj_as(SampleUnion, data)` — single dict→sample chokepoint | sample.py:469-490 |
| Helper-layer unions in `sample_positions.py` (Custom.sample etc., ×8) and `sample_api.py` (×5) use a 5-member union WITHOUT the fallback — different acceptance surface, out of 3c scope | sample_positions.py:68..., sample_api.py:226... |
| Live fallback producers: `sample_type="MEA"`, `sample_type="xafs-std-pellet"` | mea AMTS_exp.py:69; priv xafs/converters.py:188 |
| pydantic 2.13.4; enum-Literal discriminator works (str AND enum-instance tags); `Literal[None]` member → `union_tag_not_found`; nested design dump-identical to loose on all tested classes except tag-absent `{}` | experiment `/tmp/p3c_disc_test{,2}.py`, re-runnable |
| Sample-status mutation inventory: ~50 sites (see §6.3), incl. `.remove()` (sample.py only) and `base.py:1904` | grep §6.3 |
| Corpus on disk: `/mnt/STORAGE/INST_hlo/` → RUNS_FINISHED 9,864 / RUNS_ACTIVE 81 / RUNS_DIAG 16 -act.yml; +1,467 -exp.yml, +157 -seq.yml, 0 -prc.yml; real sample blocks confirmed (solid/liquid, `hlo_version 2023.01.04`) | find/grep |
| Harness trees carry no sample blocks (OERSIM samples-free) | grep `/tmp/hlo_p3_fixcheck` |
| e2e harness working; fresh baseline `fixcheck.norm` on this HEAD; `run_e2e.sh <label>` produces `<label>.norm` | `.omc/artifacts/p3/` |
| 3a chokepoint exists: `status_transitions.py` with `guarded_append/replace/reset` (log-only, stdlib logger) | helao/core/models/status_transitions.py |

---

## 3. Declared deltas (exhaustive — anything else in a diff is a defect)

1. **None at the data layer.** No payload newly rejected (fallback retained, by construction); all
   dumps byte-identical (corpus-replay-proven + e2e-proven).
2. **Tag-absent dict routing** `{}` → `NoneSample` (was: accidental `AssemblySample`). Ships only if
   the corpus shows zero occurrences; documented in the unit test as the known divergence.
3. **JSON Schema / OpenAPI structure** for models embedding the union (ActionModel etc.) gains
   discriminator/`oneOf` structure — visible in FastAPI `/docs`/`openapi.json`, never in data files.
   (3a's `schema_baseline.json` freeze was a 3a gate; it does not carry into 3c.)
4. **New WARNING-level log lines** from `status_transitions` sample guards (duplicate append,
   destroyed+preserved coexistence) — telemetry for 3e, same policy as 3a.

---

## 4. Corpus-replay harness (T0 gate — exact design + commands)

**New file `.omc/artifacts/p3/corpus_replay.py`** (operational artifact, not committed under
`helao/`). Unlike the observation scripts it MUST import the sample classes — but it builds both
unions **locally** so it is version-agnostic across the 3c change:

```python
#!/usr/bin/env python
"""Corpus replay: prove nested discriminated sample union == loose union on real data.

Builds LOOSE and NESTED unions locally from the sample classes (version-agnostic).
For every sample block found in *-act.yml / *-exp.yml / *-seq.yml / *-prc.yml under
the given roots, validates against both and compares (routed type, model_dump_json).

Usage:
  conda run -n helao python .omc/artifacts/p3/corpus_replay.py \
      /mnt/STORAGE/INST_hlo /tmp/hlo_p3_baseline /tmp/hlo_p3_fixcheck \
      [--use-repo-alias] [--report OUT.json]

Exit 0 iff zero mismatches on the real corpus AND zero tag-absent blocks.
--use-repo-alias additionally validates every block against helao's shipped
SampleUnion and asserts it agrees with the locally-built NESTED union (post-change proof).
"""
import argparse, collections, glob, json, os, sys
from typing import Annotated, Union

import yaml  # fast path; ruamel fallback per file on error
from pydantic import Field, TypeAdapter

from helao.core.models.sample import (
    AssemblySample, GasSample, LiquidSample, NoneSample, SampleModel, SolidSample,
)

LOOSE = TypeAdapter(
    Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample, SampleModel]
)
_CORE = Annotated[
    Union[AssemblySample, LiquidSample, GasSample, SolidSample],
    Field(discriminator="sample_type"),
]
NESTED = TypeAdapter(Union[_CORE, NoneSample, SampleModel])

SYNTHETIC = [  # one of everything + every D1 edge; tag-absent {} is asserted as the ONLY known DIFF
    LiquidSample(sample_no=1).model_dump(), LiquidSample(sample_no=1).model_dump(mode="json"),
    GasSample(sample_no=2).model_dump(), SolidSample(plate_id=2750, sample_no=3).model_dump(),
    AssemblySample(parts=[LiquidSample(sample_no=1), SolidSample(plate_id=1, sample_no=2)]).model_dump(),
    NoneSample().model_dump(), {"sample_type": None},
    {"sample_type": "MEA", "global_label": "synthetic", "etc": {"k": 1}},
    {"sample_type": "weird", "global_label": "synthetic"},
    {"sample_type": "liquid", "volume_ml": "not-a-float"},
]

def iter_sample_blocks(root):
    for pat in ("*-act.yml", "*-exp.yml", "*-seq.yml", "*-prc.yml"):
        for path in glob.iglob(os.path.join(root, "**", pat), recursive=True):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    doc = yaml.safe_load(f)
            except Exception:
                try:
                    from helao.helpers.yml_tools import yml_load
                    doc = yml_load(open(path, encoding="utf-8").read())
                except Exception as e:
                    yield path, "PARSE_FAIL", repr(e)[:200]
                    continue
            if not isinstance(doc, dict):
                continue
            for key in ("samples_in", "samples_out"):
                for i, block in enumerate(doc.get(key) or []):
                    yield path, f"{key}[{i}]", block

def outcome(ta, block):
    try:
        m = ta.validate_python(block)
        return ("ok", type(m).__name__, m.model_dump_json())
    except Exception as e:
        return ("fail", type(e).__name__, None)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("roots", nargs="+")
    ap.add_argument("--use-repo-alias", action="store_true")
    ap.add_argument("--report", default=None)
    args = ap.parse_args()

    repo_ta = None
    if args.use_repo_alias:
        from helao.core.models.sample import SampleUnion
        repo_ta = TypeAdapter(SampleUnion)

    census = collections.Counter()      # (sample_type value, loose-routed class)
    fallback = collections.Counter()    # sample_type values that route to SampleModel
    mismatches, tag_absent, n = [], [], 0
    synthetic_blocks = [(f"synthetic[{i}]", "s", b) for i, b in enumerate(SYNTHETIC)]
    for path, loc, block in synthetic_blocks + [t for r in args.roots for t in iter_sample_blocks(r)]:
        if loc == "PARSE_FAIL":
            mismatches.append({"path": path, "loc": loc, "why": block}); continue
        if not isinstance(block, dict):
            continue
        n += 1
        synthetic = str(path).startswith("synthetic")
        if "sample_type" not in block and not synthetic:
            tag_absent.append({"path": path, "loc": loc})
        lo, hi = outcome(LOOSE, block), outcome(NESTED, block)
        census[(repr(block.get("sample_type")), lo[1])] += 1
        if lo == ("ok",) + lo[1:] and lo[1] == "SampleModel":
            fallback[repr(block.get("sample_type"))] += 1
        agree = lo == hi
        if not agree and synthetic and "sample_type" not in block:
            agree = True  # the ONE declared delta: tag-absent synthetic case
        if not agree:
            mismatches.append({"path": path, "loc": loc, "loose": lo[:2], "nested": hi[:2]})
        if repo_ta is not None:
            ri = outcome(repo_ta, block)
            if ri != hi:
                mismatches.append({"path": path, "loc": loc, "nested": hi[:2], "repo": ri[:2]})

    report = {"blocks": n, "census": {f"{k}": v for k, v in census.items()},
              "fallback_census": dict(fallback), "tag_absent": tag_absent,
              "mismatches": mismatches[:200], "mismatch_count": len(mismatches)}
    if args.report:
        json.dump(report, open(args.report, "w"), indent=1)
    print(json.dumps({k: report[k] for k in ("blocks", "fallback_census", "mismatch_count")}, indent=1))
    print(f"tag_absent real blocks: {len(tag_absent)}")
    sys.exit(1 if (mismatches or tag_absent) else 0)

if __name__ == "__main__":
    main()
```

(Executor: the sketch above is the contract — walk logic may be cleaned up, but the comparison
semantics, synthetic set, census outputs, exit criteria, and `--use-repo-alias` mode are fixed.
Include the same `yaml.safe_load`→ruamel fallback; PyYAML is in the env. Runtime over ~11.5k files
is minutes; run it foregrounded with a generous timeout or `run_in_background`.)

**Exact commands:**

```bash
# T0 — GATE (pre-change, clean HEAD): prove the design on real data
conda run -n helao python .omc/artifacts/p3/corpus_replay.py \
    /mnt/STORAGE/INST_hlo /tmp/hlo_p3_baseline /tmp/hlo_p3_fixcheck \
    --report .omc/artifacts/p3/corpus_report_baseline.json
# MUST exit 0: zero mismatches, zero real tag-absent blocks.
# Inspect fallback_census: expected keys ⊆ {'None'} ∪ non-enum tags; any non-empty entry is a
# FINDING to record in this file's §9 (it proves the fallback member must stay — already decided D1).

# T4 — re-prove on the changed tree, including the shipped alias
conda run -n helao python .omc/artifacts/p3/corpus_replay.py \
    /mnt/STORAGE/INST_hlo /tmp/hlo_p3_baseline /tmp/hlo_p3_fixcheck \
    --use-repo-alias --report .omc/artifacts/p3/corpus_report_post.json
# MUST exit 0; mismatch_count and fallback_census must equal the baseline report's.
```

**Escalation rule:** any real-corpus mismatch or tag-absent block ⇒ STOP; record the payload class
here; either extend the outer union ordering to preserve it (with a fresh replay proving the fix) or
defer 3c's union flip entirely (the sample-status work, T1/T3, is independent and may still land).

---

## 5. Per-file transformation — union (T1 + T2)

### 5.1 `helao/core/models/sample.py` (T1)
- Add `Annotated` to the `typing` import.
- Replace the alias block (currently :459-466) with the D1 two-stage definition; export
  `TypedSampleUnion` in `__all__`. Keep `object_to_sample` untouched (it inherits the new alias;
  `parse_obj_as` over an `Annotated`-bearing union works on 2.13.4 — verified via `TypeAdapter`).
- `AssemblySample.parts` (:382-391): inline 6-member union → `List[SampleUnion]` (string annotation
  via `from __future__ import annotations`; resolved by the existing `model_rebuild()` calls at
  :493-494). Same for `SampleList.samples` (:445-456) → `Optional[List[SampleUnion]]`. The vestigial
  `SampleUnion = ForwardRef("SampleUnion")` at :32 stays (harmless; it is overwritten before
  rebuild) — do not churn it.
- Recursion note: `AssemblySample` appears inside `TypedSampleUnion` inside its own `parts` — the
  unit test must construct + validate a nested assembly to prove `model_rebuild` resolves it.

### 5.2 `action.py:143-148`, `experiment.py:121-126`, `process.py:77-82` (T2)
Replace each inline `List[Union[AssemblySample, ..., SampleModel]]` with `List[SampleUnion]`; add
`SampleUnion` to the existing `from helao.core.models.sample import ...` line. Leave the individual
class imports alone if referenced elsewhere in the file; otherwise trim them (no-stray-diff rule:
annotation lines + import line only). **sequence.py: no change (no sample fields — verified).**
`sample_positions.py` / `sample_api.py` unions: untouched in 3c (different, narrower acceptance
surface; dedupe logged in §9).

---

## 6. Per-file transformation — sample-status lifecycle (T1 + T3)

### 6.1 `helao/core/models/status_transitions.py` additions (T1)
Keep the three HloStatus functions byte-identical. Append:

```python
def guarded_remove(status_list, old_status, *, owner: str = "?") -> None:
    """Remove exactly as legacy inline `.remove()` did (raises ValueError if absent, as legacy);
    warn first when absent so 3e telemetry sees it."""
    if old_status not in status_list:
        _LOGGER.warning("remove of absent status %s on %s: %s", old_status, owner, status_list)
    status_list.remove(old_status)


def _warn_sample_contradiction(status_list, owner: str) -> None:
    from helao.core.models.sample import SampleStatus  # lazy: avoid sample.py import cycle
    if SampleStatus.destroyed in status_list and SampleStatus.preserved in status_list:
        _LOGGER.warning("contradictory sample state (destroyed+preserved) on %s: %s", owner, status_list)


def sample_guarded_append(status_list, new_status, *, owner: str = "?") -> None:
    if new_status in status_list:
        _LOGGER.warning("duplicate sample status append %s on %s: %s", new_status, owner, status_list)
    status_list.append(new_status)          # unconditional — byte-identical to legacy
    _warn_sample_contradiction(status_list, owner)


def sample_guarded_remove(status_list, old_status, *, owner: str = "?") -> None:
    guarded_remove(status_list, old_status, owner=owner)


def sample_guarded_reset(status_list, new_statuses, *, owner: str = "?") -> None:
    status_list[:] = list(new_statuses)
    _warn_sample_contradiction(status_list, owner)
```

Update `__all__` and the module docstring (mention 3c). No pydantic/helao-infra imports at module
level beyond the existing ones (audit's "pydantic-pure models" strength preserved; the sample import
is function-local by design).

### 6.2 `SampleModel` methods (T1, sample.py)
Three thin delegates defined on `SampleModel` (inherited by every subtype incl. `NoneSample`):
`append_sample_status(s)`, `remove_sample_status(s)`, `reset_sample_status(*statuses)` — each calls
the corresponding `sample_guarded_*` with `owner=f"sample {self.global_label or self.sample_type}"`
(cheap, no label derivation — `get_global_label()` has side-effect-free but non-trivial logic; do
not call it in a log-path). Route sample.py's own sites: `zero_volume` (:195-198) and
`destroy_sample` (:203-206) bodies call the new methods, **keeping every outer `if ... in/not in`
guard verbatim** (byte-identical mutation sequence). `create_initial_exp_dict`'s `:164` list
coercion stays verbatim with a `# not a lifecycle transition — list coercion` comment.

### 6.3 Routing inventory (T1 core, T3 hte) — every site keeps its surrounding guards/loops verbatim

| File | Sites | Op → routed call |
|---|---|---|
| core/models/sample.py | 196, 206 append; 198, 204 remove | `append_sample_status` / `remove_sample_status` (T1) |
| core/servers/base.py | 1904 | `sample.reset_sample_status(SampleStatus.preserved)` (T1; inside existing `if not sample.status:` guard) |
| hte drivers/data/archive_driver.py | appends: 1031 (`newstatus` var), 1182, 1658, 1744, 1762, 1838, 2047, 2131, 2147, 2221; resets: 1289, 1312, 1330, 1335, 1339, 1553, 1656, 1783, 1837, 1944, 2045, 2168, 2220, 2364, 2370 | `append_sample_status(x)` / `reset_sample_status(x)` |
| hte drivers/robot/pal_driver.py | appends: 1660, 1662; resets: 842, 1042 (`= []` → `reset_sample_status()`), 1130, 1142, 1238, 1286, 1325 (multi-status → `reset_sample_status(a, b)`), 1335, 1347, 1392 (multi), 1400, 1427, 1506, 1574, 1671 | same mapping |
| hte drivers/io/nidaqmx_driver.py | 772 | `reset_sample_status(SampleStatus.preserved)` |
| hte drivers/spec/spectral_products_driver.py | 406 | same |
| hte drivers/sensor/sprintir_driver.py | 430 | same |

Line numbers are anchors, not gospel — T3's gate is the grep-zero sweep (§8), not the count.
Commented-out sites (archive 1326, pal 1040) stay commented. Out of scope: `deploy/mea/notes/**`,
`deploy/lila_gl/**`, priv constructor kwargs, plain local lists named `*status*`.

---

## 7. New unit test (T1): `helao/core/tests/unit_test_sample_union.py`

Standalone script (repo `TestReporter` convention) + one registry line in `run_unit_tests.py`.
Checks (all against the shipped `SampleUnion`):
1. **Routing equivalence** vs a locally-built loose union over the §4 synthetic set: routed type +
   `model_dump_json()` byte-equal for every case EXCEPT tag-absent `{}`, which is asserted to route
   to `NoneSample` (the declared delta, with a comment citing this plan).
2. **Model-level**: `ActionModel`, `ExperimentModel`, `ProcessModel` built with dict `samples_in`/
   `samples_out` (one of each subtype + a `"MEA"` fallback dict) — assert routed classes and that
   `model_dump()` round-trips byte-identically through re-validation.
3. **Assembly recursion**: nested `AssemblySample` (assembly-in-parts) validates and dumps
   identically pre-pattern (constructed instance) vs dict-validated.
4. **`object_to_sample`** returns the same types as direct validation for each subtype dict.
5. **Status-method equivalence** (mirror 3a's test): for append/remove/reset, apply legacy inline op
   to one instance and the guarded method to a clone; assert `model_dump_json()` byte-equal across
   subtypes × start states (`[]`, `[preserved]`, `[created, preserved]`, duplicate-append,
   remove-absent → both raise `ValueError` identically).
6. **Schema sanity**: `ActionModel.model_json_schema()` contains a discriminator mapping for the
   four typed members AND still admits the fallback (structure asserted loosely — presence, not
   bytes; the schema delta is declared in §3).

---

## 8. Task table

Executor model: **Sonnet** for all tasks. Every task's gate includes
`conda run -n helao python run_unit_tests.py` exit 0 (suite gate) and a no-stray-diff check
(`git diff` limited to the documented substitutions + imports). Waves: **T0 → T1 → (T2 ∥ T3) → T4.**

| ID | Title | Files (exclusive ownership) | Depends | Group | Verification |
|----|-------|------------------------------|---------|-------|--------------|
| 3c-T0 | Corpus-replay harness + baseline gate on clean HEAD | `.omc/artifacts/p3/corpus_replay.py`, `corpus_report_baseline.json` — **nothing under `helao/`** | — | Wave 1 (serial) | §4 T0 command exits 0; zero real mismatches + zero tag-absent; `fallback_census` recorded; `fixcheck.norm` confirmed present (e2e baseline reuse per D5); suite green at baseline. **GO/NO-GO for T2's union flip.** |
| 3c-T1 | sample.py nested union + status_transitions extension + SampleModel status methods + route core sites (sample.py, base.py:1904) + unit test | `helao/core/models/sample.py`, `helao/core/models/status_transitions.py`, `helao/core/servers/base.py` (one site), `helao/core/tests/unit_test_sample_union.py` (new), `run_unit_tests.py` (registry line) | T0 | Wave 2 (serial) | §7 test exits 0; suite gate; import smokes `python -c "import helao.core.models.sample, helao.core.servers.base"`; `python -c "from helao.core.models.sample import SampleUnion, TypedSampleUnion, object_to_sample"`; nested-assembly rebuild check (§5.1). |
| 3c-T2 | Route action/experiment/process fields to `SampleUnion` alias | `helao/core/models/action.py`, `helao/core/models/experiment.py`, `helao/core/models/process.py` | T1 | Wave 3 (∥ T3) | Import smoke all three; suite gate; grep gate: `grep -rn "SolidSample, NoneSample, SampleModel" --include='*.py' helao/ \| grep -v models/sample.py` → empty. |
| 3c-T3 | Route hte sample-status sites (5 files, §6.3) | `helao/deploy/hte/drivers/data/archive_driver.py`, `.../robot/pal_driver.py`, `.../io/nidaqmx_driver.py`, `.../spec/spectral_products_driver.py`, `.../sensor/sprintir_driver.py` | T1 | Wave 3 (∥ T2) | `conda run -n helao python -m py_compile` each file (do NOT fix unrelated Windows-import errors); suite gate; grep-zero (§8.1 pattern, hte scope). |
| 3c-T4 | Verification sweep: suite + corpus re-replay (repo-alias mode) + e2e diff + compileall + grep gates + commit + push | — (artifacts only: `corpus_report_post.json`, `p3c_post.norm`) | T2, T3 | Wave 4 (serial-post) | §8.1 below. |

### 8.1 3c-T4 sweep (all must pass)

```bash
conda run -n helao python run_unit_tests.py
conda run -n helao python helao/core/tests/unit_test_sample_union.py
conda run -n helao python helao/core/tests/unit_test_status_transitions.py   # 3a test still green

# corpus re-replay incl. shipped-alias agreement (§4 T4 command) — exit 0,
# mismatch_count + fallback_census identical to corpus_report_baseline.json

# e2e behavior identity (baseline = existing fixcheck.norm, same HEAD, per D5)
bash .omc/artifacts/p3/run_e2e.sh p3c_post
diff .omc/artifacts/p3/fixcheck.norm .omc/artifacts/p3/p3c_post.norm          # MUST be empty

# hte compile gate
conda run -n helao python -m compileall -q helao/deploy/hte/drivers helao/deploy/hte/servers

# grep gates
grep -rn "SolidSample, NoneSample, SampleModel" --include='*.py' helao/ | grep -v "models/sample.py"   # empty
grep -rnE "\.status\.(append|remove|extend|insert|clear)\(|\.status\s*=\s*\[" --include='*.py' \
  helao/core/ helao/helpers/ helao/deploy/hte/ helao/deploy/test/ \
  | grep -viE "action_status|experiment_status|sequence_status|driver_status|global_status|status_transitions\.py|^\s*#|sample\.py:164" \
  | grep -vE "models/sample.py:16[0-9]"                                                                 # empty
  # (allow-list: the :164 list coercion; commented-out legacy lines)
```

Then: **one parent-repo commit** on `feat/cards-refactor` (T1–T3 + tests; `.omc/` artifacts stay
untracked), message stating: corpus-replay result (N blocks, 0 mismatches, fallback census), the
e2e diff-empty proof, and the declared deltas (§3). Push (per-increment policy). **No nested-repo
commits** — mea/priv/lila untouched.

---

## 9. Risk and rollback

- **Validation-routing risk is THE risk**, and it is bounded by construction (fallback retained ⇒
  nothing newly rejected) and proven twice (corpus replay pre + post, 11.5k-file real corpus;
  smart-mode subtleties like the invalid-liquid→SampleModel degradation were tested explicitly and
  are preserved). The single routing delta (tag-absent) is corpus-gated to be unexercised.
- **Import cycle** `sample.py ↔ status_transitions.py`: broken by the function-local `SampleStatus`
  import (D3). T1's import smoke catches any regression.
- **Recursive rebuild** (`AssemblySample` in its own parts via the new alias): covered by the
  explicit nested-assembly unit check; if `model_rebuild()` fails to resolve, fall back to spelling
  `parts` inline as `List[Union[TypedSampleUnion, NoneSample, SampleModel]]` — semantically the same
  alias.
- **e2e blind spot** (harness has no sample blocks) — declared in D5; compensated by corpus replay +
  model-level tests. Do not claim e2e proves sample behavior.
- **hte exposure**: T3 sites are semantically identical list ops behind py_compile; PAL/Archive are
  slated for the approved hoist/rewrite, which inherits the routed chokepoint rather than fighting
  it. No hte launch, no config change.
- **Log noise**: sample guards fire only on duplicate/contradiction/absent-remove — same acceptance
  as 3a; logger name `helao.core.models.status_transitions` is the suppression knob.
- **Corpus staleness/PII**: the corpus is read-only local instrument data; reports contain counts,
  type names, and local paths only — keep reports in `.omc/artifacts/` (untracked), do not paste
  sample payload contents (which embed machine/host-derived labels) into committed docs.
- **Rollback**: single parent commit; `git revert` restores the loose union + inline mutations
  atomically. Corpus/e2e artifacts survive (reusable). No cross-repo ordering constraints.

---

## 10. Open questions (append to `.omc/plans/open-questions.md`)

- [ ] `SampleModel.sample_type` → `SampleType` enum tightening: blocked by live producers
      (mea `"MEA"` AMTS_exp.py:69; priv `"xafs-std-pellet"` xafs/converters.py:188). Decide with mea/priv
      owners: add enum members, or migrate those to declared subtypes; only then re-open (post-3c).
- [ ] Dropping the `SampleModel` fallback member outright (3e-style enforcement for samples): gated on
      T0's `fallback_census` from real data + producer migration above. If census is empty on hte data,
      the fallback exists solely for mea/priv — scope a per-deployment story.
- [ ] Tag-absent `{}` → `NoneSample` delta: confirmed-zero in corpus at T0? If any real occurrence
      surfaces later (private-deployment data not on this disk), re-evaluate outer-union ordering.
- [ ] `sample_positions.py` / `sample_api.py` 5-member unions (no fallback): dedupe onto
      `Union[TypedSampleUnion, NoneSample]` in a later increment (behavior-sensitive the same way; needs
      its own mini-replay over sample DB rows).
- [ ] Sample-status guard enforcement flip (dedup/raise) rides 3e with the HloStatus flip, same soak
      telemetry window.
- [ ] Carry-over from 3a (unchanged): base.py:1441 `set_error` field-target oddity; 3e soak window;
      mea `wait_for_temperature` divergence (3d).
