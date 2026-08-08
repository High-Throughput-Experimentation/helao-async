# P6 — Deployment-C Migration: Decomposition & Sequencing

> **Status:** authored 2026-08-05; **unstarted** (P6a is the first, blocking slice). **P5 closed
> 2026-08-05** — its flip, canaries, estop drill and full-group launch all passed — so this phase
> is unblocked and is the active one. Locks sub-project boundaries, dependency order, the
> diff-basis decision, and the gate structure for P6 of the hexagonal rewrite (master spec:
> `docs/superpowers/specs/2026-07-16-framework-hexagonal-rewrite-design.md` §12 P6, §4.3.10, §5
> row 13, §6.6, as amended by `2026-08-04-hexagonal-rewrite-ui-amendment.md` §10; mandated per
> §13).
>
> **This is the public mirror.** The executable plan — real file paths, line numbers, per-slice
> TDD task lists — lives in the private deployment repo. This document carries structure,
> decisions, gates and measured state in **Deployment-C** alias form so the phase-plan series is
> complete in the public repo. Where the two disagree, the private plan is authoritative on
> tactics and this one on gates.
>
> **Privacy (binding):** Deployment-C alias only. No real deployment or nested-repo names, no
> config filenames, hostnames, bucket names, credential paths, or campaign/plate identifiers.
> Technique names the master spec already uses publicly (XAFS, ICPMS, UV-Vis, XRF
> quantification/calibration) are permitted; vendor names of the conversion families are not.
> Real paths under `helao/core/`, `helao/hexagon/`, `harness/`, and
> `helao/deploy/{hte,test,hexagon}/` are public and cited freely.

## Goal

Finish Deployment-C's hexagon migration at parity, with the **analysis-artifact unification and
the god-module dismantling as the phase's centre of gravity**: collapse the deployment's two
divergent analysis writers into one `AnalysisArtifactPort` adapter, replace the drifting offline
fork of the core artifact writers with the ArtifactStore adapter, dismantle the notebook-I/O
god-module so nothing performs network or credential I/O at import, port the batch-conversion
server as the rewrite's reference "job manager as app service", and build the batch/analysis
capture rig the parity harness never grew. Terminal state: the deployment's production configs
run their conversion and analysis servers through the hexagon graft, gated end-to-end on Linux —
**this is the one deployment phase with no at-station hardware gate**.

## What P6 inherits (entry state, measured 2026-08-05)

Both recon passes ran against the live tree on the day of authoring. The spec (2026-07-16) and
the audit of record both predate everything in this list.

- **`AnalysisArtifactPort` exists with zero implementors**: `helao/hexagon/ports/analysis.py:1-22`
  (Protocol, `publish()` + `enqueue()`); its only reference is
  `helao/hexagon/tests/test_ports_import.py:94`. P6 supplies the adapter.
- **The ArtifactStore adapters exist**: `helao/hexagon/adapters/{legacy,native}/artifact_store.py`
  plus `adapters/native/data_file.py` and `adapters/native/meta_writer.py`. The replacement
  target for the offline writer fork is in place.
- **Both P6 blockers recorded in the deployment's blocker doc are RESOLVED**: the generic graft
  (`helao/deploy/hexagon/servers/action/graft.py`, 64 lines, config-driven, names nothing
  private) and per-deployment checklist resolution (`helao/hexagon/preflight.py:109-126`,
  `_checklist_dir` prefers the deployment's own `tests/checklists`). Enforcement was proven by
  negative probe (a missing checklist fails preflight with a named error). The blocker doc and
  two canary-config header comments still claim otherwise — stale, corrected in P6a.
- `python -m helao.hexagon.preflight` prints **PREFLIGHT OK** today on all four relevant configs
  (two hexagon canaries, the conversion-station config, the Windows spectrometer-station config).
- **Both hexagon canaries are green on Linux today**, non-destructive (`/tmp` roots, a safe-root
  gate, watchdog disabled, empty `analyses` list): batch canary 34 routes / 24 schemas identical,
  analysis canary 19 routes / 24 schemas identical. Coverage is **static openapi surface only** —
  no RUNS tree, no artifact, no analysis output, no `/finish_yml`.
- **The parity harness is fully real**: 14 modules + 17 test files, 118 tests green in 1.3 s;
  gate CLI `python -m harness.parity`; provenance manifests with hard-fail on manifest-less
  goldens; mutation self-test (4 classes); additive freezer (`harness/freeze.py`) with
  per-route `external_registrar` support (`harness/freeze.py:72-80`). GM-1, GM-4, GM-5
  re-verified green today. **Q3 is resolved YES** (`harness/docs/q3-local-only-sync.md`): a
  local-only syncer completes FINISHED→SYNCED including the destructive zip.
- **Artifact row 13 is already fully supported by the normalizer** — `ANALYSES` is a first-class
  parity top (`harness/treepass.py:32-41`), `ArtifactRow.ANALYSIS = 13`
  (`harness/classify.py:31,141-142`), routed through the YAML pass (`harness/parity.py:63-69`),
  grammar probed and matching. **Therefore no §5.5 amendment is needed for this phase.**
- The deployment's pytest sweep is green (12 files: 8 PASS, 4 NOTESTS, 6 s).
- **Gap (task 0):** the deployment has **no `tests/checklists/servers.json`**, which
  `harness/freeze.py:70` requires — hte, Deployment-A and Deployment-B all have one, so
  `python -m harness.freeze <deployment>` cannot run today. P6a fixes this first; it is cheap.

## Corrections to the spec and the audit, measured

Recorded per the standing rule (compute the gate numbers, don't assert them). Each entry states
whether it needs a master-spec amendment.

1. **Spec §4.3.10 and §12 P6 say "three divergent analysis writers". It is two, and the third
   item of work is already done.** Measured: the XRF-quantification converter writes three plain
   action HLO files and emits **no** `AnalysisModel`/`AnalysisOutputModel`/`AnalysisDataModel` at
   all; its analysis records are produced later by the quantification analysis class running
   under the core analysis driver — i.e. they **already flow through writer 1**. The unification
   is core `sync_ana` + the XAFS converter's inline drifted copy; the port's only new adapter
   consumer is that inline copy. **Amendment landed** 2026-08-08 —
   `docs/superpowers/specs/2026-08-08-hexagonal-rewrite-amendment-2.md` §2 amends the §4.3.10
   scope sentence to two writers and puts the quantification converter's plain-HLO output
   explicitly out of the port's scope (routing it through would be a behaviour change, not a
   unification). The uuid7 divergence in item 2 below is recorded there too, at spec level,
   because it is what makes a naive golden diff of that family non-deterministic.
2. **The XAFS inline writer's parity-critical divergence is not in the spec's list:** it mints
   `analysis_uuid` from a **time-based uuid7**, not the content hash the server path uses
   (`BaseAnalysis.gen_uuid`, `helao/core/drivers/data/analyses/base_analysis.py:81-109`), so
   re-converting the same source yields a **new analysis record every run** while the server
   path is idempotent. Eleven total divergences were measured; each is dispositioned in P6e.
   No amendment needed — §4.3.10 already calls the copy "drifted"; the plan records the full
   list.
3. **The audit's picture of the batch server and its spine is stale in ways that change port
   tactics** (no amendment — audits are dated ground truth, this plan supersedes them):
   the server grew from 559 to 798 lines and from 5 to 6 job families (a plate-imaging family was
   added; the second XRF vendor family is disabled but its manual route deliberately answers
   "unavailable"); the conversion spine grew from 712 to 1080 lines and moved from
   threads-under-`asyncio.run` to a **`ProcessPoolExecutor`** whose worker initializer receives
   the world config; the source lifecycle is now **four stages** (drop → processing → completed →
   failed); the watchdog now has a per-source lock **plus** a concurrency semaphore (hard ceiling
   8) and **two-observation quiescence** (file count + total size + newest mtime), not
   "one lock, single-shot mtime-age"; `watchdog_settle_seconds` defaults to 60, not 10; and
   **`watchdog_enabled` defaults to `False` while the module docstring says `true`** — a live
   doc/code divergence flagged (never silently "fixed" by flipping the default: that would turn
   on a production drop-folder scanner).
4. **The frozen checklist is 4 routes stale and no existing gate catches it.** The batch server
   has 17 live routes; the frozen checklist has 13; the four missing are the notes-ingest
   family's run/pause/resume/status routes. Neither the preflight presence check
   (`helao/hexagon/preflight.py:192-207`, existence only) nor the openapi canary (both legs
   import the same module) can see it. Additionally the analysis server's checklist was frozen
   with an **empty `analyses` list**, so it records only the two config-independent private
   routes and none of the `analyze_*` action endpoints the stations actually register — spec
   §8.3(1) requires extraction with the target config. P6a closes both, additively.
5. **The uvis defect the spec cites is real but mislocated, its blast radius is now measured,
   and there is a second defect the spec does not know about.** (a) The last-window-only bug is
   at the desaturation function's final statement (the fit assignment sits at function-body
   indentation, one line below where the audit placed it); demonstrated on a synthetic
   two-window spectrum; **output-changing iff a spectrum has ≥2 saturated windows, byte-identical
   for 0 or 1** — that bounds the fix-behind-a-flag blast radius exactly. (b) A second,
   independent defect: the flanking-peak selections are unguarded against empty arrays, so a
   saturated window with no second-derivative peak beyond it **crashes the whole analysis**
   (`ValueError: zero-size array to reduction`), contradicting the function's own "when possible"
   docstring. A crash produces *no* artifact, so fixing it is not parity-visible. Dispositions in
   P6i. No amendment needed (the spec's §12 requirement is that the decision be recorded in this
   plan; it is).
6. **Sundry stale audit numbers** (no amendment): the god-module is 1077 lines (audit: 1080) and
   its dead commented-out metadata-API predecessors are gone; 4 of its 6 module-level plate-API
   importers have already gone lazy; the offline writer fork is 368 lines (audit: 350); the XRF
   analysis module is 724 lines, not 389, and the audit's "calibration CSV filename as schema"
   claim is obsolete — the calibration source is now a parquet library; the XAFS standards
   registry is 301 lines (audit: 291) and remains the keep-as-is model.
7. **Stale harness/blocker docs** (no amendment; corrected as P6a tasks): the P0 gate record
   still lists GM-4 as deferred (it was captured 2026-07-17 and re-verified green today) and
   says "66/66 harness tests" (it is 118); the deployment's blocker doc and two canary-config
   headers claim checklist enforcement is missing (it is proven present).
8. **Amendment 1 §10's P6 inventory requirement is outstanding**: the Windows
   spectrometer-station config declares both `control_vis` and a `reflex:` server while the
   deployment ships no Reflex panel modules of its own — the panel resolves cross-deployment to
   hte's module — and the deployment's dependent-surface inventory records neither. That config
   has also grown servers the audit never saw (camera, PDU, data browser, control visualizer),
   and it carries a live `params.bokeh_port` claim that `helao/hexagon/preflight.py` does not
   check (spec §8.3(3d) calls this a first-class preflight check; `grep bokeh_port` over
   preflight returns nothing, and that config documents a real port collision as a comment
   workaround). P6a records the inventory; P6b adds the preflight check.

## Hard constraint: the gate split (all Linux, two tiers)

Spec §12 calls this phase **Linux-capturable end to end**, and that holds — **P6 has no
at-station hardware gate**. But "Linux" splits into two tiers, and the plan is explicit about
which work runs where:

- **Dev-box tier** (this repo's development machine): everything except live credentials. The
  XRF-quantification, calibration, and plate-imaging families import and run credential-free; the
  analysis server path runs against captured sequence zips; the whole harness, all checklist
  gates, the import sweep, and every code slice's tests run here.
- **Production-host tier** (the deployment's Linux conversion station — a data-processing
  machine, not an instrument): the XRD, XAFS, and ICPMS conversion families require live
  credentials, network mounts, S3, and the metadata DB **at runtime**, so their legacy golden
  captures run there — over sanitized fixture inputs in isolated drop directories, never over
  production drops, with the watchdog disabled and submission via the manual per-directory
  route. The recording seams built in P6c (SQL recorder, platemap recorder) capture those runs'
  external reads into fixtures, after which the **hexagon candidate leg replays anywhere** —
  the diff itself is dev-box-runnable from then on.

One consequence worth stating: a golden captured on the production host and the candidate run on
the dev box see identical inputs by construction (the candidate consumes the recording made
during the golden run), so the diff is apples-to-apples despite the host difference; absolute
paths and host identity are already §5.5 volatiles.

## The diff-basis decision (taken here, before any golden is captured)

The offline writer fork diverges from the core writers in eleven measured ways, one of which is
a **gate design constraint rather than a defect**: converted trees are intentionally not
byte-identical to live-server trees (different YAML serializer mode whose only visible difference
is block-sequence indentation, plus field-level drift). Decision, in three parts:

1. **The P6 diff basis is converted-tree vs converted-tree.** A golden is a legacy *conversion*
   output; the candidate is the hexagon *conversion* output over the same inputs. Converted
   trees are never diffed against live-server trees.
2. **No §5.5 amendment.** The serializer-indentation difference is already invisible to the
   harness: the YAML pass parses and re-dumps canonically (spec §6.4), so indentation folds
   without touching the volatile list. Row 13 needs nothing either (entry state above).
3. **Residual intentional diffs are asserted, never normalized away.** Where the unified writer
   legitimately changes a converted tree against its legacy golden (the enumerated field-level
   set in P6d/P6e — e.g. a sync-diversion flag becoming explicit, analysis outputs no longer
   scalar-stripped), the gate asserts each expected difference is present and that **nothing
   else** differs — the same mechanism §5.5 already uses for the FileInfo rename rule. An
   over-broad normalizer is the F1 failure mode; a signed, asserted difference list is not.

## Explicitly OUT of scope this phase

Carried as post-parity backlog, per spec §12 P6 and non-goal §1.3:

- **Typing the provenance algebra.** The UV-Vis suffix-encoded pipeline keys, the transition
  labels, the calibration keys, the global-label parsers — all ported as-is. The measured
  extras recorded for that later pass: the desaturation pipeline produces **83 keys against 61
  model fields** (the entire dark-reference arm — 25 keys — is computed on every normal run and
  reaches no artifact: ~30% dead compute), the un-suffixed means are shaped per-reference rather
  than per-wavelength by a deliberate axis choice, and the resample factor is a hardcoded 8×
  while the similarly-named parameter (default 4) only scales smoothing windows. A typed
  `SpectrumStage` rewrite must take those on deliberately, not inherit them.
- **The XAFS standards registry** — kept as-is (spec: "the model persistent-registry service");
  the only touch is deleting one dead docstring sentence referencing an env var no code reads.
- **The notes-ingest family's GPU/VLM internals.** It writes no HELAO artifacts (verified at the
  server's job table), so it contributes no artifact diff; P6 covers its four routes (checklist)
  and its watchdog lifecycle (server port), nothing inside its pipeline.
- **Rotating or editing the plaintext station credentials found in the spectrometer-station
  config's motion params.** Out of this phase entirely; the constraint they impose on capture is
  recorded in Risks and honoured (manifests reference configs by path, never by content).
- **The Reflex estop/control gaps and everything P7-UI** (D9).

## Sub-project decomposition & dependency order

```
P6a (checklist manifest + additive re-freeze + content gate + doc corrections)  Linux, BLOCKING
        │
P6b (gate infrastructure: import-sweep ledger, NOTESTS→pytest, preflight port-claim check)
        │
P6c (capture rig + sanitized fixtures + LEGACY goldens + determinism baseline)
        │            ← every behavior-changing slice is gated behind P6c's goldens
P6d (offline writer fork → ArtifactStore post-hoc face)
        │
P6e (analysis-writer unification; XAFS inline copy deleted)
        │
P6f (god-module dismantling, 5 waves)          P6i (UV-Vis defect disposition)
        │                                          ↑ independent after P6c; may run in parallel
P6g (ICPMS lineage port + recorded-fixture replay)
        │
P6h (batch server as the job-manager app service)
        │
P6j (assembly: config flips, ledger-empty, inventory/runbook closure)
```

### P6a — Checklist manifest, additive re-freeze, content gate, doc corrections *(Linux; BLOCKING)*

**Task 0, cheap, and everything else diffs against it.** Create the missing
`tests/checklists/servers.json` manifest (the freezer's hard requirement, mirroring the other
three deployments' schema); re-freeze **additively** — never `--accept-drift` — picking up the
four notes-ingest routes (13→17); re-freeze the analysis server's checklist with a
station-shaped `analyses` list so the `analyze_*` action endpoints enter the baseline (2→5).

**Two traps, both with existing mechanism:** (1) four of the batch server's frozen routes are
registered **programmatically** (a loop calling `app.post(f"/run_{name}")`), so AST extraction
provably cannot see them and a naive re-freeze would *delete them from the baseline* — they are
marked with the freezer's per-route `external_registrar` key (`harness/freeze.py:72-80`), naming
the registering callable, exactly as Deployment-A's checklist marks its 15 foreign-registrar
routes. (2) The analysis server's two private routes are registered by **core**
(`helao/core/drivers/data/analysis_driver.py:601,607`), not by the 25-line private module — the
same marker applies.

**Then a content gate that would have caught the staleness:** port Deployment-A's 47-line
checklist-content test (frozen path set vs `harness.endpoints.extract_routes` under the
manifest's `representative_key`, with `external_registrar`-marked routes exempted from the AST
comparison and asserted registered at runtime instead). Self-test: mutate a frozen file in a
temp copy and assert the gate fails — a content gate that cannot fail is the vacuity trap here.

**Also in this slice (doc corrections, all measured in "Corrections" above):** the deployment's
blocker doc rewritten to RESOLVED with the probe evidence; the two canary-config stale headers;
the watchdog docstring corrected to the code's `False` default; the registry's dead env-var
docstring; the parent repo's P0 gate record (GM-4 status, 118-test count); and the
dependent-surface inventory updated per Amendment 1 §10 — the cross-deployment Reflex/control
panel edge, the spectrometer-station config's grown server set, and its `bokeh_port` claim.

**Gate:** freezer dry-run reports zero drift; the four programmatic routes and the two
foreign-registrar routes survive byte-verbatim; the content gate is green and fails its
mutation self-test; deployment suite green.

### P6b — Gate infrastructure *(Linux)*

Three tools P6 needs that do not exist, built before the code they will gate:

1. **The import sweep, from scratch.** `helao/hexagon/tests/test_hardware_import_sweep.py` is
   *not* this gate — it is hte-driver-only and blocks neither sockets nor credential reads; no
   socket-blocking harness exists anywhere, and `pytest_socket` is not installed. Build a
   deployment-local sweep: a subprocess per batch of modules with a preamble that makes every
   socket operation raise and scrubs credential env/paths, importing every module under the
   deployment package and reporting per-module. Ships with an **expected-failure ledger** pinned
   by the test: the four modules in the god-module's import chain, plus the six CLI entry
   modules that read `sys.argv[1]` at import (measured; the seventh family reads argv inside
   `main()` and is clean). Later slices shrink the ledger; P6j asserts it empty. Self-test: a
   planted socket-at-import module must fail the sweep — a blocker that doesn't block reports
   green forever.
2. **NOTESTS conversion.** Four `__main__`-style test scripts (1,158 lines) collect zero tests
   under pytest and are invisible to `run_tests.py` — and they are the **only** coverage of the
   drop-settle hardening and the process pool, the two most behaviour-critical parts of the
   batch server P6h will port. Convert them to pytest-collectable form (direct invocation
   preserved). After this, `run_tests.py --filter <deployment>` reports 0 NOTESTS.
3. **The invisible-port-claim preflight check** (spec §8.3(3d)). `_config_sanity`
   (`helao/hexagon/preflight.py:128-161`) reserves the Reflex `port + 1` claim but not
   `params.bokeh_port`; the spectrometer-station config carries a live claim and documents a
   real collision as a comment. Extend the reservation set; negative-probe with a synthetic
   colliding config; all tracked configs must still preflight exit-0.

**Gate:** sweep green-with-ledger and failing its plant; 0 NOTESTS; preflight check proven by
negative probe.

### P6c — Capture rig + fixtures + legacy goldens *(Linux, both tiers; precedes all behavior changes)*

The harness has **no batch/analysis capture scenario**: every existing scenario submits via the
orchestrator (`append_sequence` + `start`, quiescing on `/global_status`), and capture ports are
hardcoded to the golden config's three servers (`harness/capture.py:47-49`). A batch conversion
is a different shape — seed a drop folder, POST the manual per-directory route, quiesce on the
watchdog-status and conversion-registry endpoints plus the DB server's `/n_queue`/`/tasks` —
and no canary config carries a DB server at all, so nothing exercises `/finish_yml` today.

**Deliverables:**
- A **batch scenario family** in `harness/capture.py` (config-derived ports; drop-seed →
  manual-route submission → quiesce predicate). Submission is via the manual route, **never** the
  watchdog, for determinism — watchdog timing is behavior-test territory (P6b's converted
  tests), not golden territory. Quiesce self-test: the predicate must be observed *false during
  a running conversion* at least once, else a wrong-port predicate that is vacuously true would
  snapshot half-written trees.
- A **capture config** for the deployment: batch + analysis servers on their real modules, a
  `DB` entry hosting the recording sim DB server (the P0 deliverable, reused — a hexagon twin
  already exists so the same config flips only `deployment:`), `/tmp` root, watchdog disabled.
  This closes the `/finish_yml` round-trip gap: the converter POSTs the finished sequence yml to
  the DB server exactly as production does, and the destructive-zip leg runs under Q3's verified
  local-only mode.
- An **analysis arm on the S3 consistency check**: `internal_s3_checks`
  (`harness/s3_pass.py:193-220`) today pairs only `action/*.json` uploads against on-disk
  act-ymls; row 13 gets the equivalent — `analysis/*.json` paired against the on-disk ANALYSES
  yml, with the intentional-difference assertions of the diff-basis decision.
- **Sanitized drop fixtures** for the five artifact-producing families (XRD, XAFS, ICPMS,
  XRF-quantification, plate-imaging — the fifth is newly in scope, measured wired into the job
  table; the calibration family writes a registry, not sequence trees, and is covered by its
  offline tests). Fixtures are minimal real exports with identifiers scrubbed, living in the
  private repo.
- **Recording seams**, each a minimal reviewed legacy patch in the A3 tradition (no behavior
  change when unset): a platemap recorder (captures the S3 platemap fetch to a fixture), the
  **two-level ICPMS SQL recorder** (the lineage lookup is two levels — a label-keyed DataFrame
  *plus* a per-creation-action JSON fetch performed inside the graph walker, a second network
  read the DataFrame does not serve; a fixture holding only level one would silently shrink the
  converted tree through the converter's catch-and-continue), and **one one-line legacy guard**:
  the XAFS inline writer's *model* upload ignores the local-only flag while its own output
  uploads honour it — unguarded, a capture run on the production host would upload junk analysis
  models to the real bucket. The guard is invisible to all production runs (they run with
  local-only false) and is itself one of P6e's dispositioned divergences, landed early for
  capture safety.
- **Legacy goldens GM-C1…GM-C6**, two independent runs each, legacy-vs-legacy
  normalized-identical (the P0 determinism rule): quantification, XRD, XAFS (conversion +
  inline analyses), ICPMS (with SQL recording), the analysis-server path (three `analyze_*`
  endpoints over a captured sequence zip, recording sink), plate-imaging. Dev-box tier for
  GM-C1/C5/C6; production-host tier for GM-C2/C3/C4, over fixture inputs in isolated drop dirs.
  Goldens live in the established untracked golden store, never in the public repo (Q2).
- **One mutation run against a real GM-C tree.** Honesty item: the CI-able mutation self-test
  runs against a synthetic tree, and the only real-golden mutation run was a one-time manual
  invocation recorded in the P0 gate record. Repeating it against a captured GM-C tree is cheap
  and closes the gap for this phase's tree shapes.

**Gate:** every GM-C pair normalized-identical; the `/finish_yml` leg exercised with the
recording sink's manifest showing the expected key set; the mutation run red on all 4 classes;
provenance manifests present (config referenced by path only — see Risks).

### P6d — Offline writer fork → ArtifactStore post-hoc face *(Linux)*

The 368-line offline re-implementation of the core artifact writers (8 importers, every
converter) is replaced by a thin **post-hoc composition face over the hexagon ArtifactStore
adapter** — one writer implementation, one grammar source. The face exists because batch
conversion legitimately differs in *call shape* (it assembles a finished tree after the fact:
no live file-conn registry, no finalizer to defer file relocation to), not in *grammar*.

Eleven measured divergences, each dispositioned (full table with line numbers in the private
plan): the **load-bearing call-shape differences are kept as explicit port parameters**
(caller-supplied file index — downstream analysis code locates files by that index in the
filename, so it must never be silently re-derived; immediate tracked-file copy; explicit file
group required rather than either side's divergent default); the **accidental drift is dropped
in favour of core behavior** (non-atomic meta writes → atomic; the fast-serializer indentation —
invisible post-normalization; a latent crash when act-saving is disabled; the missing None-sample
filter, probe-verified unexercised); and the **artifact-visible deltas are asserted as the
intentional-diff set** (the sync-diversion flag the fork omitted from every FileInfo entry, now
explicit — probe-verified for how the cleaner serializes it). One divergence gets a probe with
both outcomes specified: the fork's repeat-write branch appends **without** the header separator
(a reader would see both payloads as one body); if no converter exercises it (expected), the
face refuses repeat writes loudly; if one does, the byte grammar is reproduced and documented.

**Gate:** GM-C1…C6 diffs green with exactly the enumerated intentional-diff set asserted
present and nothing else; unit fixtures derived from golden fragments (`# fixture-source:`);
the fork module reduced to a deprecation shim or deleted once all 8 importers are re-pointed.

### P6e — Analysis-writer unification *(Linux; the §4.3.10 item)*

One `AnalysisArtifactPort` adapter producing the row-13 layout, its grammar delegated to the
core analysis driver's logic (writer 1 stays the single source; the sanctioned minimal legacy
refactor extracts its pure layout functions for the adapter to share — no behavior change to
the server path). The XAFS converter's inline re-implementation (11 divergences) is **deleted**;
it builds records and calls the port.

**The decision that matters: analysis identity moves from time-based to content-hash.** The
inline copy mints a fresh time-seeded uuid per run — re-conversion duplicates records forever —
while the server path hashes name + params + process + code identity. Unify on the content
hash. Parity-safe for any single capture (the normalizer maps UUIDs to ordinals; only *derived*
UUIDs are checked, and this one is opaque per-capture), wire-visible across *re-runs* in
exactly the direction consumers already handle (the server path has always overwritten rather
than duplicated) — signed off on that basis. Historical duplicate records remain in the bucket;
harmless.

Remaining dispositions (full table private): the hardcoded dummy flag → config-read (equal
under every production config, which set the flag explicitly); disabled code-provenance fields →
populated (normalizer-volatile); campaign fields → the server path's loader merge
(fixture-asserted equal); **scalar-stripped outputs in the local yml → the full output set**
(artifact-visible; asserted as an intentional diff; measured whether the S3 body shares the
stripping); the unguarded model upload → guarded (landed in P6c); the duplicate S3 uploader →
the port's single uploader (recorded payloads asserted identical on fixtures); root derivation,
path-component extraction, literal name/classname, inline JSON dump → core behavior (each equal
on production configs or normalizer-invisible, each with its assert).

**Gate:** GM-C3 green including the ANALYSES tree and the recorded `analysis/*` payloads;
idempotency test (same input twice → same UUID, same keys); the deleted inline layout provably
unreferenced; the analysis arm of the S3 check green.

### P6f — God-module dismantling *(Linux; 5 waves, ordered by the measured blocker chain)*

The 1077-line notebook-I/O module constructs four session singletons at import and performs an
**unguarded S3 platemap download at import time** — the measured raiser. The moment that line is
fixed, the *next* module-level construction (a metadata-API client that fetches its OpenAPI spec
at construction) becomes the new import-time blocker — **so the session/credentials wave and the
platemap wave land together**, or the import sweep goes green then red between waves.

Waves: **F1** evict the notebook analytics (~350 lines, pure deletion; they are the only
consumers of the import-time platemap besides one converter). **F2** session/credentials +
platemap service together (lazy cached session object; `get_platemap(id)` with the recorded
fixture as its test double; the last module-level importers re-pointed — measured: only one
converter and two library modules remain module-level, four former sites are already lazy).
**F3** metadata-API client (typed wrappers, lazily constructed; the audit's dead predecessors
are already gone). **F4** sample graph — with one behavior pin: the graph walker's recursive
descent is **dead by measurement** (its result is overwritten by a flat comprehension, so nested
assemblies never resolve); the flat behavior is *preserved* and the dead recursion deleted —
"fixing" it would change converted trees. **F5** parameterized SQL repository (the raw query
path, the schema-switching inline statement, the f-string-quoted ID interpolation — replaced by
parameterized equivalents asserted result-identical on the recorded fixtures). The module itself
survives as a **lazy re-export shim** — it is imported by user notebooks outside any repo, and
breaking them is scope this phase does not need; the shim performs no I/O at import.

**Gate:** the import-sweep ledger loses all four god-module-chain entries; every consumer's
tests green; GM-C2 (the platemap-consuming converter) re-diffed green.

### P6g — ICPMS lineage port + recorded-fixture replay *(Linux)*

> **Status correction, 2026-08-08 (owner).** This conversion family **has never been
> exercised**: it is neither retired nor shipped, but **work in progress**. Confirmed against
> the production source mount, where its drop / synced / failed trees are all empty while every
> other family carries 70–216 converted sources. Two consequences for this phase, and they pull
> in opposite directions from the rest of P6:
>
> - **There is no production behaviour to preserve, so there is no golden to capture.** The
>   parity argument that governs every other family — reproduce byte-for-byte, fix nothing
>   wire-visible — does not apply to code no run has depended on. Do not synthesise a golden
>   for it; a diff against invented input proves only that the refactor preserved a fiction.
> - **It is equally not dead code.** It stays wired into `JOB_MODULES` with a `/run_icpms`
>   route, and the endpoint checklist keeps it. Do not delete it as unused surface.
>
> So P6g ports it for *structure* — the lineage port, parameterized SQL, no import-time
> network — and its gate is the unit/fixture level only, explicitly not a golden diff. The
> injection-shaped label quoting and the `LIMIT 2000` truncation may therefore be fixed
> outright rather than preserved for parity, which is the one place in P6 where that is true.
> Whoever finishes the family owns the first real capture.

The mid-conversion live SQL becomes an explicit **lineage port** (label-set lookup + per-action
JSON fetch — both levels), with the live implementation over P6f's repository and a recorded
implementation over P6c's fixture. **The silent-shrink trap is closed at the gate, not by
changing behavior:** the converter's catch-and-continue on a lineage miss is legacy behavior and
is preserved (a live miss must keep shrinking the tree exactly as today); the *gate* gains a
positive row-count assertion — the converted tree must contain exactly the fixture's expected
action count, and the negative probe (delete one fixture row) must turn the gate red rather
than the tree quietly smaller.

**Gate:** GM-C4 replayed green on the dev box; row-count assertion + its negative probe; the
injection-shaped label quoting gone (parameterized), result-identical on fixture.

### P6h — Batch server as the job-manager app service *(Linux; the reference port)*

The batch server is the rewrite's named reference for "long-running job manager as an app
service". The port restructures composition, not behavior: lifecycle objects (watchdog, sibling
notes-ingest watchdog, pause controller, conversion registry, process pool) constructed by an
explicit factory the hexagon composition drives, with startup/shutdown owning the pool teardown
and the hot-reload busy hook preserved verbatim. **Non-negotiables carried whole:** the
`ProcessPoolExecutor` model with the worker initializer's world-config hand-off (workers import
against it); the four-stage source lifecycle; per-source lock + semaphore (ceiling 8);
two-observation settle quiescence; jobs degrading to "unavailable on this host" when their
imports fail (on a credential-less machine only 3 of 6 families exist — that degradation is
load-bearing dev-box behavior); the disabled family's manual route answering "not available"
rather than 404. **Also here:** the six CLI entry modules' import-time `sys.argv[1]` reads move
behind lazy module attributes (launcher behavior preserved; the import-sweep ledger drains to
zero for them).

**Gate:** freezer dry-run zero drift (17 routes, programmatic four intact); the converted
drop-settle and process-pool suites green; GM-C set re-diffed green; both canaries green;
import-sweep ledger empty of argv entries.

### P6i — UV-Vis defect disposition *(Linux; independent after P6c)*

Per spec §12, the suffix algebra ports as-is; two defects get recorded decisions:

1. **Last-window-only desaturation: preserve for parity; land the fix behind a default-off
   parameter in the same slice.** The spec's default stands, now with the measured bound:
   byte-identical for 0–1 saturated windows, output-changing only for ≥2. The fix ships behind
   an analysis parameter (default off — and because analysis identity hashes only *supplied*
   params, an unset default leaves every existing UUID untouched), with a pinning test for both
   paths on the synthetic two-window spectrum. Flipping the default is a post-parity act with
   its own sign-off.
2. **The empty-flank crash: fix now.** It is not output-changing in the parity sense — a crash
   yields no artifact, so no consumer can depend on it (the same reasoning P5 used for its
   404-ing leg). The guard skips an unreconstructable window, matching the function's own
   documented "when possible" contract, with a regression test on the reproducing spectrum.

The 83-keys/61-fields model mismatch, the dead dark-reference arm, and both preserved quirks
(per-reference mean shapes; the hardcoded 8× resample) are recorded post-parity backlog, listed
in Out of scope above.

**Gate:** GM-C5 green (default path byte-identical); both defect tests pinned; the flag path
exercised.

### P6j — Assembly: config flips + closure *(Linux; terminal)*

Flip the deployment's production configs **in place** (the P4f/P5g resolution: no parallel hex
configs) — batch/analysis servers to the generic graft, orchestrator/operator/DB entries
untouched, rollback per server (delete two keys). Order: the conversion-station config first
(it is the deployment's own canary-of-record shape), then the two analysis-station configs,
then the Windows spectrometer station's analysis server — a config-only change riding that
station's next restart, with its runbook carrying the Amendment-mandated bundle step and the
cross-deployment panel note even though the deployment ships no panel source. Preflight every
config by its **in-tree path** (the P4f silent-pass trap). Closure assertions: import-sweep
ledger **empty**; `run_tests.py` over the deployment fully green with 0 NOTESTS; both canaries
green; every GM-C diff green at head.

**Gate:** all of the above, plus the spec's rollback condition armed: legacy converter scripts
remain callable until the gate **and one real campaign cycle** pass.

## Gate map (spec §12 P6 → discharging slices)

| Spec gate item | Discharged by | Net-new? |
|---|---|---|
| Golden converted-sequence trees + ANALYSES trees + recorded `analysis/*` S3 payloads from sanitized real drop inputs, normalized diff green | P6c (goldens + analysis S3 arm) + P6d/e/f/g/h re-diffs | Scenario, capture config, fixtures, seams, S3 analysis arm all net-new; normalizer row-13 support pre-existing |
| Converter round-trip through the real DB server `/finish_yml` leg | P6c capture config (DB entry + recording sink), every GM-C scenario | Net-new (no canary config has a DB entry today) |
| Import sweep proves no module performs network/credential I/O at import | P6b (built from scratch — the existing hte sweep is not this gate) + P6f/P6h drain + P6j empty-ledger | Net-new |
| Endpoint checklists (§8.3) current and content-gated | P6a | Manifest + content gate net-new; freezer pre-existing |
| Preflight incl. §8.3(3d) invisible port claims | P6b | The `bokeh_port` reservation is net-new |
| **At-station hardware gate** | **None — P6 has no at-station hardware gate.** The production-host capture tier is a Linux data-processing machine; nothing in this phase requires an instrument window. | — |

## Decisions

1. **Diff basis: converted-tree vs converted-tree; no §5.5 amendment; residual intentional
   diffs asserted, never normalized.** Taken before any golden is captured. *Rejected:*
   folding indentation into the volatile list (needless — the YAML pass already parses and
   canonicalizes — and §5.5 additions require an amendment); diffing converted trees against
   live-server trees (measures the fork's history, not the port's correctness).
2. **Analysis identity unifies on the content hash, not the time-based UUID.** Idempotency is
   the server path's existing contract; normalizer-invisible per capture; cross-run behavior
   changes only in the direction consumers already handle. Signed off in P6e.
3. **Two writers, not three** — the spec's third writer already flows through writer 1
   (measured); scope corrected, master-spec amendment flagged.
4. **The desaturation bug is preserved for parity and fixed behind a default-off parameter;
   the newly-found crash defect is fixed outright** (a crash yields no artifact; no consumer
   can depend on it). Both with pinning tests; blast radius measured, not asserted.
5. **Golden capture splits by credential need**: dev-box for credential-free families,
   production-host (Linux, no instrument) for the credentialed three, with recording seams so
   the candidate leg replays anywhere. No at-station hardware gate exists in this phase.
6. **Scenario submission is via the manual per-directory route, never the watchdog** —
   determinism for goldens; watchdog timing is covered by the converted behavior tests.
7. **The plate-imaging family is scoped into parity** (it is wired into the job table and writes
   artifacts; the audit predates it); **the notes-ingest family is scoped as surface +
   lifecycle only** with a negative assertion that its conversions write no HELAO artifacts.
8. **The import sweep is subprocess socket-blocking + env-scrub with a pinned expected-failure
   ledger; no new test dependency.** Self-tested against a planted violation.
9. **The CLI entry modules' argv coupling is fixed by lazy module attributes**, not by exempting
   them from the sweep forever; ledgered until P6h.
10. **`watchdog_enabled` keeps its `False` code default; the docstring is corrected** — the
    other direction would silently turn on a production drop-folder scanner.
11. **The offline fork's divergences are dispositioned individually** (keep the load-bearing
    call shape, drop the accidental drift, assert the visible deltas) rather than reproduced
    wholesale or replaced wholesale. Table in P6d and the private plan.
12. **The god-module survives as a lazy re-export shim** for out-of-repo notebooks; the
    deployment's own code stops importing it.
13. **The ICPMS catch-and-continue is preserved; the gate gains the row-count assertion** —
    fixture holes must fail the gate, not shrink the tree.
14. **Provenance manifests keep their config-by-path-only reference, deliberately** — one
    station config carries plaintext credentials in its params, so config *content* must never
    be snapshotted into a manifest or golden. No credential rotation in this phase.
15. **The dead recursion in the sample-graph walker is deleted, its flat behavior preserved** —
    resolving nested assemblies "correctly" would change converted trees.

## Global constraints (inherited; apply to every slice)

- **Parity first.** No wire- or artifact-visible change without a recorded per-item sign-off in
  the commit message. The intentional-diff set is enumerated and asserted, never open-ended.
- **Goldens are captured from legacy before the slice that changes the behavior they pin** —
  P6c precedes P6d–P6h absolutely.
- **Run the deployment's tests per-file with a timeout**, with the env interpreter directly
  (not `conda run`, which buffers).
- **Format with the project formatter as the final step before every commit**, in the repo that
  owns the files. **Branch per sub-project; no commit or push without authorization.**
- **Never name the private deployment in a tracked parent-repo file**; parent-repo commits use
  the Deployment-C alias.

## Execution note

**Current state, verified 2026-08-05:** nothing in P6 has been started. The inherited inputs are
all in place and measured (entry-state section above): port + adapters exist, graft + checklist
resolution landed and enforcement proven, canaries and preflight green, harness 118/118 with
GM-1/4/5 re-verified, Q3 resolved. The first slice is **P6a** — it is the cheapest and every
later diff is against its baseline. The one genuinely new *kind* of work in this phase is P6c's
capture-rig build-out; everything after it is gated re-diffs of the same golden set.
