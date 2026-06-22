# Framework Support Utilities Implementation Plan (Sub-project 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Vendor the leaf generic utilities into `helao/framework/support/`, cleaned to framework-only imports, pure where practical, ≥90% per-module coverage.

**Architecture:** `support/` = deployment-agnostic utilities. May import `models/` + other `support/`; never `adapters`/`app`/`domain`/web. See spec `docs/superpowers/specs/2026-06-22-framework-support-design.md`.

**Tech Stack:** Python 3.12 (helao conda env), pydantic v2, ruamel.yaml, ntplib, pytest.

---

## Conventions (read first)

- **helao conda env only:** prefix every command with `conda run -n helao`. Never OS python. Ignore the cosmetic `ERROR conda.cli.main_run` line on non-zero exit.
- **Branch:** `feat/framework-scaffold` (all sub-projects stack here). Confirm with `git branch --show-current`. Never commit to `unstable`/`main`.
- **No private-deployment names** in any added file.
- **Porting rule:** copy from the named source file, then: repoint imports to `helao.framework.*`; remove import-time side effects (no network/disk/subprocess at import or default-factory); pydantic v2 hygiene; keep public names/signatures deployments use. The source file IS the content spec — port faithfully, cleaned.
- **After every task:** `conda run -n helao python run_framework_tests.py` stays green; AST boundary test passes.

---

## Task 1: time_utils (leaf, pure)

**Files:** Create `helao/framework/support/time_utils.py` (from `helao/helpers/time_utils.py`); Test `helao/framework/tests/test_support_time.py`.

- [ ] **Step 1:** Read `helao/helpers/time_utils.py`.
- [ ] **Step 2:** Write failing tests: `gen_uuid()` returns a UUID and two calls differ; `set_time(offset=...)` returns a timezone-correct datetime that shifts with the offset; the NTP-offset read returns a float/default WITHOUT opening a socket (monkeypatch/inspect to prove no network at import). Run → FAIL.
- [ ] **Step 3:** Port the module. Ensure no socket/network call executes at import time (lazy/file-based offset read).
- [ ] **Step 4:** Run tests → PASS; full gate green.
- [ ] **Step 5:** Commit `git commit -m "feat(framework): port time_utils into support"`

## Task 2: make_str_enum + constants

**Files:** Create `helao/framework/support/make_str_enum.py` (from `helao/helpers/make_str_enum.py`), `helao/framework/support/constants.py` (from `helao/helpers/constants.py`); Test `helao/framework/tests/test_support_enum.py`, `test_support_constants.py`.

- [ ] **Step 1:** Read both source files.
- [ ] **Step 2:** Write failing tests: `make_str_enum("X", ["a","b"])` yields a str-enum whose members compare equal to their string values and serialize correctly in a pydantic model; `constants` exposes its expected names (assert the public constants exist with expected values). Run → FAIL.
- [ ] **Step 3:** Port both. In `constants.py` repoint `from helao.core.models.machine import MachineModel` → `from helao.framework.models.machine import MachineModel`.
- [ ] **Step 4:** Run tests → PASS; gate green.
- [ ] **Step 5:** Commit `git commit -m "feat(framework): port make_str_enum and constants into support"`

## Task 3: helao_logging

**Files:** Create `helao/framework/support/helao_logging.py` (from `helao/helpers/helao_logging.py`); Test `helao/framework/tests/test_support_logging.py`.

- [ ] **Step 1:** Read `helao/helpers/helao_logging.py` and `helao/core/tests/unit_test_logging.py`.
- [ ] **Step 2:** Write failing tests (port the meaningful assertions from unit_test_logging.py): `make_logger(__file__)` returns a configured `logging.Logger`; log level/format honored; logging to a tmp dir writes a file. No real email/network side effect at import. Run → FAIL.
- [ ] **Step 3:** Port. Repoint `from helao.helpers.time_utils import read_saved_offset` → `helao.framework.support.time_utils`. Keep `make_logger`/`LOGGER` public names.
- [ ] **Step 4:** Run tests → PASS; gate green.
- [ ] **Step 5:** Commit `git commit -m "feat(framework): port helao_logging into support"`

## Task 4: yml_tools

**Files:** Create `helao/framework/support/yml_tools.py` (from `helao/helpers/yml_tools.py`); Test `helao/framework/tests/test_support_yml.py`.

- [ ] **Step 1:** Read `helao/helpers/yml_tools.py`.
- [ ] **Step 2:** Write failing tests: round-trip a dict → yaml string → dict via the load/dump helpers against a tmp file; remote-fetch path is exercised with a monkeypatched aiohttp (NO real network). Run → FAIL.
- [ ] **Step 3:** Port. Keep public load/dump signatures.
- [ ] **Step 4:** Run tests → PASS; gate green.
- [ ] **Step 5:** Commit `git commit -m "feat(framework): port yml_tools into support"`

## Task 5: config_loader

**Files:** Create `helao/framework/support/config_loader.py` (from `helao/helpers/config_loader.py`); Test `helao/framework/tests/test_support_config.py`.

- [ ] **Step 1:** Read `helao/helpers/config_loader.py` and `helao/core/tests/unit_test_config_loader.py`.
- [ ] **Step 2:** Write failing tests (port unit_test_config_loader assertions): resolving a prefix to a tmp `.yml`/`.py` config returns the expected dict; bare prefix vs full path both work; importing the module performs NO file read (assert by importing in a subprocess/monkeypatch). Use tmp config files, not real deploy configs. Run → FAIL.
- [ ] **Step 3:** Port. Repoint imports to framework (`yml_tools`, models). Keep the public entry points; ensure import is side-effect-free (no module-level CONFIG read).
- [ ] **Step 4:** Run tests → PASS; gate green.
- [ ] **Step 5:** Commit `git commit -m "feat(framework): port config_loader into support"`

## Task 6: codehash + coverage close

**Files:** Create `helao/framework/support/codehash.py`; Test `helao/framework/tests/test_support_codehash.py`.

- [ ] **Step 1:** Read the codehash logic in `helao/helpers/import_autolibs.py` and `helao/core/version.py` (how sequence/experiment code is hashed for versioning).
- [ ] **Step 2:** Write failing tests: `code_hash(source: str)` is deterministic (same input → same hash), differs for different input, and a file-based variant hashes a tmp `.py` file's contents. Run → FAIL.
- [ ] **Step 3:** Implement a minimal, pure `codehash.py` capturing that hashing behavior (stable across runs; stdlib hashlib). No import of dispatcher/rpc.
- [ ] **Step 4:** Run the gate and read `.framework-cov.json`. For each `support/` module below 90%, add targeted tests. Enforce the ≥90% per-support-module bar (either extend the gate's gated prefixes to include `support/` in coverage_gate, or add an explicit per-module coverage assertion test — your choice; document it).
- [ ] **Step 5:** Commit `git commit -m "feat(framework): add codehash util; support coverage >=90%"`

## Task 7: Final verification

- [ ] **Step 1:** `conda run -n helao python run_framework_tests.py` → all pass, gate PASS.
- [ ] **Step 2:** Purity — `grep -rE "from helao\.(core|helpers)" helao/framework/support/` is empty.
- [ ] **Step 3:** Boundary test green; confirm `support/` imports no adapters/app/domain/web.
- [ ] **Step 4:** No private-deployment names — `git diff unstable --name-only | xargs grep -niE "lila|lila_gl|\\bmea\\b|\\bpriv\\b"` (ignore the plan/spec docs' own grep command text).
- [ ] **Step 5:** `git log --oneline unstable..HEAD` shows support commits stacked.

---

## Self-review notes

- Delivers SP2 spec §2 (time_utils, make_str_enum, constants, helao_logging, yml_tools, config_loader, codehash), §4 cleanups (framework-only imports, no import-time side effects, pydantic v2, preserved public names), §5 tests + ≥90% per-support-module.
- OUT of scope per spec §3: dispatcher + rpc (→ SP5 transport adapter).
- All commands `conda run -n helao`. No private-deployment names.
