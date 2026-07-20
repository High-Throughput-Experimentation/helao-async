# P3c — hte experiment/sequence libraries (Library layer)

> Sub-project of P3 (see `2026-07-18-P3-hte-decomposition.md`). Linux-complete.

**Goal:** Prove and gate that all 242 experiment + 86 sequence functions across 27 hte library modules import on Linux, and freeze the flat-namespace collision guard (spec §4.3.12 / §8.3(3) AVOID #8 — libraries in the wave from day one).

## Outcome (2026-07-18 — COMPLETE for the Linux-provable surface)

Branch `feat/p3c-library-import-sweep` (stacked on p3a2). Test `helao/hexagon/tests/test_hte_library_import.py` — **30 passed**:
- 27 library modules import on a vendor-less Linux box. This became possible only after P3a-1/P3a-2 made the driver modules lazily importable: ADSS/ANEC/CLAD/ECMS import `Spacingmethod`/`PALtools`/`MoveModes`/`TransformationModes` directly from `galil_motion_driver`/`pal_driver` (the rest import hardware-free `io.enum`/`motion.enum`/`spec.enum`). The user's read was correct: the coupling is enums, not hardware.
- Collision guard: `CCSI_sub_*` (CCSI_exp/CSIL_exp) + `ECHEUVIS_postseq` (ECHEUVIS_seq/HISPEC_seq) still detected via `harness.hte_collisions.scan_collisions`.

**Key finding:** the collisions are **latent** — no hte config lists a colliding pair in one `experiment_libraries:`/`sequence_libraries:` list (verified by scanning all 21 configs). So the shadowing is a dormant hazard, not an active bug. The §4.3.12 Library-port load-time collision check (config-overridable loud error) is a safety guard, and belongs in the **offline preflight validator** (P3e, spec line 234) where it checks a specific config's library list rather than the whole directory.

## Deferred to other sub-projects (not required for graft-wrap parity)

- **Config-aware collision preflight** (check a config's actual `*_libraries:` list, loud + `allow_shadow`-overridable) → P3e preflight validator. Reuse `scan_collisions` restricted to the config's listed modules.
- **Runtime Library port** (dynamic import + codehash/codepath provenance abstraction replacing the orch's legacy library import) → native composition work; the graft-wrap path (P3b) keeps the legacy orch library loading, so this is post-parity native hardening, not a P3 parity gate.
- **Specification parsers / meta+post processors** (`specifications/*.py` BaseParser, `processors/*.py` MetaProcessor with non-standard artifact outputs) — imported/exercised with the servers that use them (P3b) and the vis/analysis surface; their parity is per the endpoint/artifact checklists, not a library-import gate. Latent parser bugs at `week_window.py:77,110` documented, not fixed (wire/disk-visible parity).
