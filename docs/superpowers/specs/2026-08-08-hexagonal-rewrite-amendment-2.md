# Hexagonal Rewrite — Amendment 2: the wire that was never described, and one writer that never existed

**Date:** 2026-08-08
**Amends:** `docs/superpowers/specs/2026-07-16-framework-hexagonal-rewrite-design.md` (master
spec), as previously amended by
`docs/superpowers/specs/2026-08-04-hexagonal-rewrite-ui-amendment.md` (Amendment 1)
**Status:** Adopted. §13 of the master spec requires an amendment to change a phase's scope
or a wire contract. This does both.
**Baseline:** `unstable` @ `8372ce93`; the P6 and P7-UI plans measured against it.
**Privacy rule:** inherited verbatim from the master spec §8 preamble. The private
deployments are **Deployment-A/B/C** only.

---

## 1. Why this amendment exists

Two phase plans — P6 (Deployment-C) and P7-UI — were authored by measuring the code the spec
describes rather than trusting the description. Each turned up statements that a plan would
have implemented as written and been wrong to. Amendment 1 corrected the statements the UI
delta made stale; this one corrects three that were never right.

All three are things a phase would only discover by running into them:

1. **P6's scope is one writer smaller than the spec says.** The third "divergent analysis
   writer" does not write analysis records at all.
2. **The two WS producer families put different payload types under the same three route
   names.** The spec describes the channels and the encodings but never says the payload
   *type* differs by producer — which is the single most load-bearing fact for the P7 gate on
   wire-consumer parity, and the reason P7b exists.
3. **`/ws_globstat` is dead code.** §7.4 and §7.5 describe it as a live channel. It has a
   sender, a method, and no route registration and no consumer.

Nothing in §3 (locked decisions) is re-litigated. D9 stands as Amendment 1 wrote it.

---

## 2. §4.3.10 and §12 P6 — "three divergent analysis writers" is two

**The statement being amended**, §4.3.10 (and the matching scope sentence in §12 P6):

> Unifies Deployment-C's **three divergent analysis writers** — core
> `analysis_driver.sync_ana`, the XAFS converter's inline re-implementation (drifted copy:
> hardcoded `dummy=False`, scalar-only short outputs), and quantification's plain-HLO third
> way — into one "publish an AnalysisRecord" port …

**Measured, 2026-08-05.** The XRF-quantification converter writes three plain **action** HLO
files and emits no `AnalysisModel`, `AnalysisOutputModel`, or `AnalysisDataModel` at all. Its
analysis records are produced later, by the quantification analysis class running under the
core analysis driver — that is, they **already flow through writer 1**. There is no third
layout to unify, and no third-way write site to delete.

**Amended scope.** The unification is **two writers**: core `analysis_driver.sync_ana` (which
becomes the single adapter) and the XAFS converter's inline drifted copy (which is deleted).
The port's only new adapter consumer is that inline copy. The quantification converter's
plain-HLO output is **kept as an action artifact and is out of scope for the port** — it was
never an analysis-record writer, so routing it through the port would be a behaviour change,
not a unification.

**What does not change.** §5 row 13's layout, the `sole writer after P6 unification` note on
that row, and the "converters *enqueue* analyses; they never write the layout themselves"
rule all stand — they are statements about the terminal state, and the terminal state is
unaffected by there having been two sources rather than three.

**A divergence the spec's list omits, recorded here because it is parity-critical.** The XAFS
inline writer mints `analysis_uuid` from a **time-based uuid7**, not the content hash the
server path uses (`BaseAnalysis.gen_uuid`,
`helao/core/drivers/data/analyses/base_analysis.py:81-109`). Re-converting the same source
therefore yields a **new analysis record every run**, while the server path is idempotent.
Eleven divergences were measured in total and each is dispositioned in the P6 plan; this one
is called out at spec level because it is the one that makes a naive golden diff of that
family non-deterministic.

---

## 3. §4.3.6 and §7.5 — two producer families, same route names, different payload types

**What the spec says.** §4.3.6 enumerates the parallel WS mechanisms and, since Amendment 1
§8, the three consumer faces; §7.5 gives the per-channel encodings. Both are written as
though a channel name determines a payload shape.

**Measured.** It does not. `OrchAPI` is a **sibling** of `BaseAPI`, not a subclass
(`orch_api.py:109` vs `base_api.py:580`), so the two encodings are independent code that
happens to register the same three route names:

| Route | `BaseAPI` family | `OrchAPI` family |
|---|---|---|
| `/ws_status` | pickled **`ActionModel` object** | pickled **dict** (`as_dict()`) |
| `/ws_data` | pickled **`DataPackageModel` object** | pickled **dict** |
| `/ws_live` | dict `{datalab: (value, epoch)}` | dict |

`BaseAPI` publishes via `WsPublisher.broadcast` → `pyzstd.compress(pickle.dumps(...))`
(`helao/helpers/ws_utils.py:64-66`); `OrchAPI` publishes via `Base._ws_relay`
(`base_status.py:246-272`), which applies `as_dict()` first. §7.5's `_ws_relay` bullet is
correct about that family and silent about the other; the asymmetry between them is the part
that was never stated.

**Normative consequence — this is a wire contract, not a note.** The two families' encodings
are **independently frozen**. A phase may not converge them, and may not "fix" one to match
the other, because every existing remote subscriber of either family decodes exactly one
shape. Converging them would blank every subscriber of whichever family moved, with no error
on either side.

**Why it matters to the gate.** Amendment 1 §6 gate item 1 requires wire-consumer parity
across every real decoder. Before P7b, the hexagon tree's only WS producer test decoded with
`WsSubscriber` alone, and the orch `_ws_relay` encoding had **no wire test at all** — so a
convergence would have passed the suite. The substrate that closes this is
`harness/ws_frames.py` (canonical byte frames per channel × producer family, generated
through the **real** encoders, never a hand-rolled copy) and
`helao/hexagon/tests/test_ws_consumer_parity.py`, whose
`test_orch_relay_encoding_pinned` is the first wire test of the dict family.

**Consumer-side corollary, already half-stated in §4.3.6.** The Reflex normalizers are keyed
by `ws_path` and are **not** interchangeable: `ingest.normalize` diverts non-float values to
`rows` (the ring buffer is float64-only) while `normalize_data_package` **silently drops**
non-numeric columns. Both behaviours are deliberate and are now pinned, including the
cross-pair case (each normalizer over the other channel's frame yields nothing) — asserted
explicitly so that "returns empty" can never read as a pass.

---

## 4. §7.4 and §7.5 — `/ws_globstat` is dead code

**What the spec says.** §7.4: "drained models forward to `globstat_q` → `/ws_globstat`."
§7.5 lists "Orch `/ws_globstat` and any JSON channel" among the wire encodings.

**Measured.** The sender exists (`orch.py:355` → `orch_status_sync.py:289`) and sends JSON
text. There is **no route registration on either API class and no consumer anywhere in the
tree.** Pinned by `helao/hexagon/tests/test_ws_consumer_parity.py::test_ws_globstat_is_dead`,
which uses the repo's own static route extractor (`harness.endpoints`) rather than a grep, so
a future dynamic-route addition is exactly as visible to it as to the endpoint-parity
checklist that tool already gates.

**Amended reading.** Treat both mentions as describing a **latent** channel: the fold that
feeds `globstat_q` is live and contractual (§4.2.4 depends on it), the *publication* of it is
not. No phase gains a consumer for it as parity work.

**Deletion is post-parity, deliberately.** Removing the sender now would be a behaviour change
inside the status fold during the phases whose gates diff that fold. It goes on the
post-parity sweep alongside the other measured dead keys (`params.limit_vis`, read in three
places and declared in zero configs anywhere).

---

## 5. What this amendment does not change

- No locked decision of §3, including D9.
- No artifact-inventory row, including row 13 (the analysis layout) and row 15 (the
  control-surface negative row added by Amendment 1).
- No gate item. Amendment 1 §6's five items stand as written; §3 above strengthens the
  evidence item 1 requires rather than altering it.
- No phase boundary. P6 loses one work item from its scope sentence, not a slice.
