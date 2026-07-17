# P0 Parity Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the golden-master parity harness, capture rig, and simulated DB/sync server for the HELAO-async hexagonal rewrite, and pass the P0 gate: two independent legacy runs of each golden scenario are normalized-identical (including the FINISHED→SYNCED→S3-recorded leg), and a deliberately perturbed tree fails the gate.

**Architecture:** A new `harness/` Python package at the repo root (normalizer library + parity/capture/endpoint CLIs + its own pytest suite), one new test-deployment action server (`sim_db_server`) hosting the real `HelaoSyncer` with an injectable recording S3 client, and two new capture configs (`golden.yml`, `goldenlocal.yml`). **No rewrite/hexagon code and zero edits to existing legacy source files** — P0 is purely additive tooling measured against legacy behavior.

**Tech Stack:** Python 3.12 (`helao` conda env), pytest (new, harness-only), ruamel.yaml / orjson / requests / aiohttp (already in env), stdlib `ast`/`zipfile`/`gzip`, existing helao helpers (`yml_load`, `read_hlo`, `private_dispatcher`, `premodels`).

**Master spec:** `docs/superpowers/specs/2026-07-16-framework-hexagonal-rewrite-design.md` — §5 (artifact inventory), §5.5 (volatile-field contract), §6 (golden-master procedure), §8.3 (endpoint checklists), §9 (logging/config/clock contracts), §12 P0. Section references below (§N) point there.

## Global Constraints

Copied verbatim from the spec + repo standing rules; every task implicitly includes these.

- All Python runs inside the conda env `helao` (Python 3.12): `conda run -n helao python …`. `PYTHONPATH` must point at the repo root (`/mnt/STORAGE/repos/helao/helao-async`); running from the repo root with `python -m …` also works because cwd lands on `sys.path`.
- `black` (default settings, line length 88) is run on every changed Python file as the final step before every commit: `conda run -n helao black <files>`.
- `pyright` (`pyrightconfig.json`, basic mode) remains the authoritative type checker; do not remove `# type: ignore` directives it needs.
- There is **no pytest harness in legacy** and none is added to legacy; the P0 harness introduces its own pytest suite under `harness/tests/` only.
- Parity is measured **post-`clean_dict`** (spec §5.3): the comparator treats "absent" and "empty" as equal; never compare `model_dump()` JSON.
- The normalizer's volatile-field list is **EXACTLY spec §5.5 — no additions** without a master-spec amendment. Per-scenario value-masking configuration (masked HLO columns, row-count tolerances, content-masked files) lives in each golden set's provenance manifest, never in harness code (§6.4).
- Privacy: no real private-deployment names, hostnames, IPs, credentials, or campaign/plate identifiers in tracked files. P0 touches only `test` + `helao/core`, but the rule is binding everywhere (spec header).
- Golden masters are captured from **real legacy runs only** (D4); the gate hard-fails on a golden set without a provenance manifest (§6.5). Synthetic trees appear ONLY inside `harness/tests/` as normalizer unit fixtures, never as parity goldens.
- Legacy source is read-only in P0. The S3 recording seam needs **no legacy patch**: `SyncDriver` sets `self.s3 = None` when no `aws_config_path` is configured, only ever calls `self.s3.upload_fileobj(fileobj, bucket, key)` / `self.s3.upload_file(filename, bucket, key)` (`helao/core/drivers/data/sync_driver.py:1759,1771,1776`), and never uses `self.s3r` beyond assignment — so a `HelaoSyncer` subclass in the new server module injects the recorder post-construction (verified against source 2026-07-16).
- Work happens on a fresh branch off `unstable`: `feat/p0-parity-harness`. Do not push or merge; the controller reviews.

---

## Why this exists (one-paragraph context for a zero-context engineer)

A HELAO run produces an on-disk artifact tree under the config's `root:`: sequence/experiment/action directories with `-seq.yml`/`-exp.yml`/`-act.yml` metadata files, streamed `.hlo` data files (YAML header, `%%` separator, one JSON object per line), `-prc.yml` process records under `PROCESSES/`, `.prg` sync-progress sidecars, and finally a destructive per-sequence `.zip` under `RUNS_SYNCED/` plus S3 uploads. The hexagonal rewrite (P1–P6) must reproduce this tree byte-for-byte modulo an exhaustive volatile-field list (uuids, timestamps, host identity — spec §5.5). A previous rewrite died because its "golden masters" were hand-written from reading code (failure F1). P0 therefore builds, **before any rewrite code exists**: (a) a normalizer + diff gate, (b) a rig that captures goldens from real legacy runs on Linux, (c) a simulated DB/sync server so the sync leg runs without AWS, and (d) a baseline proof that legacy reproduces its own goldens.

## File structure

```
harness/                                    # NEW package, repo root
├── __init__.py                             # HARNESS_VERSION
├── manifest.py                             # ProvenanceManifest (capture provenance, §6.5)
├── classify.py                             # ArtifactRow enum + §5.1 name grammar (timestamp strip)
├── uuidmap.py                              # uuid -> stable-ordinal mapping (+ uuid5 derivation check)
├── yaml_pass.py                            # §5.5 volatile normalization + canonical diff
├── treepass.py                             # tree snapshot, zip explode, mapper seeding, member-set diff
├── hlo_pass.py                             # .hlo header/body compare with per-scenario masking
├── s3_pass.py                              # recorded-S3 payload compare + FileInfo-rename assertions
├── normalize.py                            # façade re-exports + inventory CLI (spec names this module)
├── parity.py                               # THE GATE: python -m harness.parity --golden X --candidate Y
├── mutate.py                               # mutation self-test CLI
├── capture.py                              # capture rig: submit GM-1..GM-5, quiesce, snapshot, manifest
├── endpoints.py                            # AST route-set extractor + checklist diff (§8.3)
├── docs/
│   ├── q3-local-only-sync.md               # Q3 verification record (written in Task 12)
│   └── p0-gate-record.md                   # gate run IDs (written in Task 16)
└── tests/
    ├── __init__.py
    ├── synthtree.py                        # synthetic mini-trees (normalizer unit tests ONLY)
    ├── test_manifest.py
    ├── test_classify.py
    ├── test_uuidmap.py
    ├── test_yaml_pass.py
    ├── test_treepass.py
    ├── test_hlo_pass.py
    ├── test_s3_pass.py
    ├── test_parity_cli.py
    ├── test_mutations.py
    ├── test_sim_db_server.py
    ├── test_endpoints.py
    └── test_legacy_contracts.py            # logging/config/clock contracts vs legacy (§9)

helao/deploy/test/configs/golden.yml        # NEW capture config (recording sim DB)
helao/deploy/test/configs/goldenlocal.yml   # NEW capture config (local-only sim DB, Q3)
helao/deploy/test/servers/action/sim_db_server.py   # NEW sim DB/sync server (§6.3)
```

Golden sets live OUTSIDE the repo (Q2 default: untracked share) at `/home/dan/helao_goldens/<scenario>/<runN>/` with layout `provenance.yml` + `root/<RUNS_*, PROCESSES, S3_SIM>`. Capture roots are `/home/dan/INST_hlo_golden` (recording) and `/home/dan/INST_hlo_goldenlocal` (Q3).

---

### Task 1: Branch, package scaffold, provenance manifest

**Files:**
- Create: `harness/__init__.py`
- Create: `harness/manifest.py`
- Create: `harness/tests/__init__.py`
- Test: `harness/tests/test_manifest.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `HARNESS_VERSION: str` in `harness/__init__.py`; `harness.manifest.ProvenanceManifest` dataclass with fields `scenario, config_prefix, config_path, legacy_git_sha, launch_cmd, sequence_name, sequence_params, capture_timestamp, harness_version, masked_hlo_columns: Dict[str, List[str]], hlo_row_count_tolerance: Dict[str, int], content_masked_files: Dict[str, str], notes`, methods `save(golden_dir: Path) -> Path` and classmethod `load(golden_dir: Path) -> ProvenanceManifest`; exception `harness.manifest.ManifestMissingError`; constant `MANIFEST_NAME = "provenance.yml"`. Every later task uses these names exactly.

- [ ] **Step 1: Create the branch and install harness-only dev deps**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
git checkout unstable
git checkout -b feat/p0-parity-harness
conda run -n helao pip install pytest
conda run -n helao black --version
```

Expected: branch created; `Successfully installed … pytest-8.x` (or `Requirement already satisfied`); black prints a version (if it errors, also `conda run -n helao pip install black`).

- [ ] **Step 2: Write the failing test**

Create `harness/tests/__init__.py` (empty file) and `harness/tests/test_manifest.py`:

```python
"""ProvenanceManifest round-trip + the manifest-less hard-fail (spec §6.5 / F1)."""

import pytest

from harness import HARNESS_VERSION
from harness.manifest import ManifestMissingError, ProvenanceManifest, MANIFEST_NAME


def make_manifest() -> ProvenanceManifest:
    return ProvenanceManifest(
        scenario="GM-1",
        config_prefix="golden",
        config_path="/abs/path/golden.yml",
        legacy_git_sha="c3b80003" + "0" * 32,
        launch_cmd="conda run -n helao python launch.py golden --no-hot-reload",
        sequence_name="SIM_websocket_data_seq",
        sequence_params={"wait_time": 2.0},
        capture_timestamp="2026-07-16T12:00:00",
        harness_version=HARNESS_VERSION,
        masked_hlo_columns={"*WsSim*.hlo": ["epoch_s", "series_0"]},
        hlo_row_count_tolerance={"*WsSim*.hlo": 3},
        content_masked_files={"*.csv": "line-count"},
        notes="unit test",
    )


def test_save_and_load_roundtrip(tmp_path):
    m = make_manifest()
    saved = m.save(tmp_path)
    assert saved == tmp_path / MANIFEST_NAME
    loaded = ProvenanceManifest.load(tmp_path)
    assert loaded == m


def test_load_without_manifest_hard_fails(tmp_path):
    with pytest.raises(ManifestMissingError):
        ProvenanceManifest.load(tmp_path)


def test_optional_masking_fields_default_empty(tmp_path):
    m = make_manifest()
    m.masked_hlo_columns = {}
    m.hlo_row_count_tolerance = {}
    m.content_masked_files = {}
    m.save(tmp_path)
    loaded = ProvenanceManifest.load(tmp_path)
    assert loaded.masked_hlo_columns == {}
    assert loaded.hlo_row_count_tolerance == {}
    assert loaded.content_masked_files == {}
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
conda run -n helao python -m pytest harness/tests/test_manifest.py -v
```

Expected: FAIL/ERROR with `ModuleNotFoundError: No module named 'harness'` (or `harness.manifest`).

- [ ] **Step 4: Write the minimal implementation**

Create `harness/__init__.py`:

```python
"""Legacy-vs-candidate artifact parity harness for the HELAO hexagonal rewrite (P0).

See docs/superpowers/specs/2026-07-16-framework-hexagonal-rewrite-design.md
sections 5 (artifact inventory), 5.5 (volatile-field contract), and 6
(golden-master procedure). The harness is additive tooling: it never modifies
legacy source and never launches servers itself.
"""

HARNESS_VERSION = "0.1.0"
```

Create `harness/manifest.py`:

```python
"""Provenance manifest for golden-master capture sets (spec §6.1 / §6.5).

A golden set without a manifest is REJECTED by the parity gate — this is the
structural countermeasure to failure mode F1 (hand-built fixture trees have
no capture provenance and must fail loudly, not silently pass).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Dict, List

from ruamel.yaml import YAML

_yaml = YAML(typ="safe")
_yaml.default_flow_style = False

MANIFEST_NAME = "provenance.yml"


class ManifestMissingError(Exception):
    """Raised when a golden set lacks a provenance manifest."""


@dataclasses.dataclass
class ProvenanceManifest:
    """Records how a golden set was captured from a real legacy run.

    The three masking fields are the ONLY sanctioned per-scenario value-masking
    configuration (§6.4): they live here, in the capture record, never in
    harness code, so the §5.5 volatile list stays exhaustive and auditable.

    - masked_hlo_columns: fnmatch pattern on the normalized .hlo (or
      .hlo.json) path -> data columns whose VALUES are masked (structure,
      presence, and — within tolerance — row counts are still compared).
    - hlo_row_count_tolerance: fnmatch pattern -> max |row-count difference|
      allowed for masked columns (poll-paced sim executors jitter by a row
      or two run-to-run; 0 = exact).
    - content_masked_files: fnmatch pattern -> "line-count" (compare number
      of lines only; for files derived from masked random data, e.g. the
      hlo_to_csv output) or "skip" (presence only).
    """

    scenario: str
    config_prefix: str
    config_path: str
    legacy_git_sha: str
    launch_cmd: str
    sequence_name: str
    sequence_params: dict
    capture_timestamp: str
    harness_version: str
    masked_hlo_columns: Dict[str, List[str]] = dataclasses.field(default_factory=dict)
    hlo_row_count_tolerance: Dict[str, int] = dataclasses.field(default_factory=dict)
    content_masked_files: Dict[str, str] = dataclasses.field(default_factory=dict)
    notes: str = ""

    def save(self, golden_dir: Path) -> Path:
        path = Path(golden_dir) / MANIFEST_NAME
        with open(path, "w") as f:
            _yaml.dump(dataclasses.asdict(self), f)
        return path

    @classmethod
    def load(cls, golden_dir: Path) -> "ProvenanceManifest":
        path = Path(golden_dir) / MANIFEST_NAME
        if not path.exists():
            raise ManifestMissingError(
                f"golden set {golden_dir} has no {MANIFEST_NAME}; golden masters "
                "must be captured from real legacy runs (spec §6.5, D4) — "
                "hand-built fixture trees are forbidden in the parity suite"
            )
        with open(path) as f:
            data = _yaml.load(f)
        return cls(**{k: v for k, v in dict(data).items()})
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
conda run -n helao python -m pytest harness/tests/test_manifest.py -v
```

Expected: `3 passed`.

- [ ] **Step 6: Format and commit**

```bash
conda run -n helao black harness
git add harness/__init__.py harness/manifest.py harness/tests/__init__.py harness/tests/test_manifest.py
git commit -m "feat(harness): P0 scaffold + provenance manifest with hard-fail on missing provenance"
```

---

### Task 2: Artifact-row classifier + §5.1 name grammar

**Files:**
- Create: `harness/classify.py`
- Test: `harness/tests/test_classify.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `harness.classify.ArtifactRow` (Enum: `SEQ_YML=1, EXP_YML=2, ACT_YML=3, HLO=4, AUX_FILE=5, PRC_YML=7, PRG=8, PARQUET=9, SEQ_ZIP=10, LOCK=11, MICRO_MANIFEST=12, ANALYSIS=13, S3_RECORD=100, IGNORE=0`), `normalize_name(part: str) -> str`, `normalize_relpath(relpath: str) -> str`, `classify_file(relpath: str) -> ArtifactRow`, constant `TOP_IGNORED: set`.

- [ ] **Step 1: Write the failing test**

Create `harness/tests/test_classify.py`:

```python
"""§5.1 directory grammar (timestamp strip) + §5.2 artifact-row classification."""

from harness.classify import (
    ArtifactRow,
    classify_file,
    normalize_name,
    normalize_relpath,
)


def test_normalize_timestamp_dir_levels():
    assert normalize_name("25.28") == "YY.WW"          # %y.%U week dir
    assert normalize_name("0716") == "MMDD"
    # sequence dir: HHMMSS__name__label[-plate...]
    assert normalize_name("131415__SEQNAME__golden-27509") == "TS__SEQNAME__golden-27509"
    # experiment dir: YYMMDD.HHMMSS__name
    assert normalize_name("250716.131420__SIM_websocket_data") == "TS__SIM_websocket_data"


def test_normalize_meta_filenames():
    assert normalize_name("250716.131415123456-seq.yml") == "TS-seq.yml"
    assert normalize_name("250716.131420123456-exp.yml") == "TS-exp.yml"
    assert normalize_name("250716.131421123456-act.yml") == "TS-act.yml"
    assert normalize_name("250716.131421123456-act.prg") == "TS-act.prg"
    assert normalize_name("131415__SEQNAME__golden.zip") == "TS__SEQNAME__golden.zip"
    assert normalize_name("131415__SEQNAME__golden.zipdir") == "TS__SEQNAME__golden.zipdir"


def test_non_timestamp_names_pass_through():
    # action dirs and hlo filenames carry no wall-clock component
    assert normalize_name("0__0__SIM__acquire_data") == "0__0__SIM__acquire_data"
    assert normalize_name("WsSim-0.0.0.0__0.hlo") == "WsSim-0.0.0.0__0.hlo"
    assert normalize_name("MANIFEST.txt") == "MANIFEST.txt"


def test_normalize_relpath_walks_every_element():
    rel = "RUNS_FINISHED/25.28/0716/131415__S__golden/250716.131420__E/0__0__SIM__acquire_data/250716.131421123456-act.yml"
    assert (
        normalize_relpath(rel)
        == "RUNS_FINISHED/YY.WW/MMDD/TS__S__golden/TS__E/0__0__SIM__acquire_data/TS-act.yml"
    )


def test_classify_rows():
    assert classify_file("RUNS_FINISHED/a/b-seq.yml") is ArtifactRow.SEQ_YML
    assert classify_file("RUNS_FINISHED/a/b-exp.yml") is ArtifactRow.EXP_YML
    assert classify_file("RUNS_FINISHED/a/b-act.yml") is ArtifactRow.ACT_YML
    assert classify_file("PROCESSES/a/0__x__t-prc.yml") is ArtifactRow.PRC_YML
    assert classify_file("RUNS_SYNCED/a/b-act.prg") is ArtifactRow.PRG
    assert classify_file("RUNS_FINISHED/a/x.hlo") is ArtifactRow.HLO
    assert classify_file("RUNS_FINISHED/a/x.parquet") is ArtifactRow.PARQUET
    assert classify_file("RUNS_SYNCED/25.28/0716/x.zip") is ArtifactRow.SEQ_ZIP
    assert classify_file("RUNS_ACTIVE/a/x.lock") is ArtifactRow.LOCK
    assert classify_file("RUNS_FINISHED/a/MANIFEST.txt") is ArtifactRow.MICRO_MANIFEST
    assert classify_file("ANALYSES/25.28/0716/x/u.yml") is ArtifactRow.ANALYSIS
    assert classify_file("S3_SIM/helao-sim/action/u.json") is ArtifactRow.S3_RECORD
    assert classify_file("RUNS_FINISHED/a/extra_output.csv") is ArtifactRow.AUX_FILE
    assert classify_file("LOGS/ORCH.log") is ArtifactRow.IGNORE
    assert classify_file("STATES/pids_golden_.pck") is ArtifactRow.IGNORE
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
conda run -n helao python -m pytest harness/tests/test_classify.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'harness.classify'`.

- [ ] **Step 3: Write the implementation**

Create `harness/classify.py`:

```python
"""Artifact-row classification + timestamp-stripping name grammar.

Implements spec §5.1 (directory-path grammar) and §5.2 (artifact rows 1-13).
Row numbers match the master spec's artifact-inventory table; rows 4 and 5
share the `.hlo` suffix on disk, so streamed and one-shot hlo files both
classify as HLO and are compared by the same pass. UUID components in names
are LEFT INTACT here; harness.uuidmap substitutes them with stable ordinals
so uuid-encoded links are checked, not ignored (§6.4).
"""

from __future__ import annotations

import re
from enum import Enum
from pathlib import PurePosixPath


class ArtifactRow(Enum):
    IGNORE = 0          # LOGS/STATES/... — path-contractual but non-parity (row 14)
    SEQ_YML = 1
    EXP_YML = 2
    ACT_YML = 3
    HLO = 4             # streamed AND one-shot .hlo (rows 4/5 share the suffix)
    AUX_FILE = 5        # non-hlo one-shot/postprocess outputs (.csv, ...)
    PRC_YML = 7
    PRG = 8
    PARQUET = 9
    SEQ_ZIP = 10
    LOCK = 11
    MICRO_MANIFEST = 12
    ANALYSIS = 13
    S3_RECORD = 100     # files under S3_SIM/ (recorded uploads; S3 pass)


# --- §5.1 name grammar ----------------------------------------------------
RE_YYWW = re.compile(r"^\d{2}\.\d{2}$")                       # %y.%U
RE_MMDD = re.compile(r"^\d{4}$")
RE_SEQ_DIR = re.compile(r"^\d{6}(__.+)$")                     # HHMMSS__name__label...
RE_EXP_DIR = re.compile(r"^\d{6}\.\d{6}(__.+)$")              # %y%m%d.%H%M%S__name
RE_META_YML = re.compile(r"^\d{6}\.\d{12}-(seq|exp|act)\.yml$")   # %y%m%d.%H%M%S%f
RE_META_PRG = re.compile(r"^\d{6}\.\d{12}-(seq|exp|act)\.prg$")
RE_SEQ_ZIP = re.compile(r"^\d{6}(__.+)\.zip$")
RE_SEQ_ZIPDIR = re.compile(r"^\d{6}(__.+)\.zipdir$")          # explode_zips target

TOP_IGNORED = {"LOGS", "STATES", "DATABASE", "USER_CONFIG"}


def normalize_name(part: str) -> str:
    """Strip volatile timestamp components from ONE path element (§5.5).

    Everything derived from wall-clock time (week/date dirs, seq/exp dir
    prefixes, meta-yml filenames) collapses to a stable token; every other
    element (action dirs, hlo names, aux filenames) passes through unchanged.
    """
    if RE_YYWW.match(part):
        return "YY.WW"
    if RE_MMDD.match(part):
        return "MMDD"
    m = RE_META_YML.match(part)
    if m:
        return f"TS-{m.group(1)}.yml"
    m = RE_META_PRG.match(part)
    if m:
        return f"TS-{m.group(1)}.prg"
    m = RE_SEQ_ZIP.match(part)
    if m:
        return f"TS{m.group(1)}.zip"
    m = RE_SEQ_ZIPDIR.match(part)
    if m:
        return f"TS{m.group(1)}.zipdir"
    m = RE_EXP_DIR.match(part)
    if m:
        return f"TS{m.group(1)}"
    m = RE_SEQ_DIR.match(part)
    if m:
        return f"TS{m.group(1)}"
    return part


def normalize_relpath(relpath: str) -> str:
    """Normalize every element of a /-separated relative path."""
    return "/".join(normalize_name(p) for p in PurePosixPath(relpath).parts)


def classify_file(relpath: str) -> ArtifactRow:
    """Map a root-relative file path onto its spec §5.2 artifact row."""
    p = PurePosixPath(relpath)
    parts = p.parts
    name = p.name
    if parts and parts[0] in TOP_IGNORED:
        return ArtifactRow.IGNORE
    if parts and parts[0] == "S3_SIM":
        return ArtifactRow.S3_RECORD
    if name.endswith("-seq.yml"):
        return ArtifactRow.SEQ_YML
    if name.endswith("-exp.yml"):
        return ArtifactRow.EXP_YML
    if name.endswith("-act.yml"):
        return ArtifactRow.ACT_YML
    if name.endswith("-prc.yml"):
        return ArtifactRow.PRC_YML
    if name.endswith(".prg"):
        return ArtifactRow.PRG
    if name.endswith(".hlo"):
        return ArtifactRow.HLO
    if name.endswith(".parquet"):
        return ArtifactRow.PARQUET
    if name.endswith(".zip"):
        return ArtifactRow.SEQ_ZIP
    if name.endswith(".lock"):
        return ArtifactRow.LOCK
    if name == "MANIFEST.txt":
        return ArtifactRow.MICRO_MANIFEST
    if parts and parts[0] == "ANALYSES":
        return ArtifactRow.ANALYSIS
    return ArtifactRow.AUX_FILE
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
conda run -n helao python -m pytest harness/tests/test_classify.py -v
```

Expected: `5 passed`.

- [ ] **Step 5: Format and commit**

```bash
conda run -n helao black harness
git add harness/classify.py harness/tests/test_classify.py
git commit -m "feat(harness): artifact-row classifier + spec 5.1 timestamp-strip name grammar"
```

---

### Task 3: UUID → stable-ordinal mapper (links are checked, not ignored)

**Files:**
- Create: `harness/uuidmap.py`
- Test: `harness/tests/test_uuidmap.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `harness.uuidmap.RE_UUID` (compiled regex matching canonical 36-char uuids), class `UuidMapper` with methods `map(raw: str) -> str`, `register_derived(raw_process_uuid: str, experiment_uuid: str, pidx) -> bool`, `sub(text: str, strict: bool = False) -> str`, `sub_any(value)` (recursive over str/list/dict). Later tasks construct one `UuidMapper` per capture side.

- [ ] **Step 1: Write the failing test**

Create `harness/tests/test_uuidmap.py`:

```python
"""UUID -> ordinal mapping incl. the uuid5 process-derivation check (§5.5)."""

import uuid

import pytest

from harness.uuidmap import UuidMapper

U1 = "00000000-0000-0000-0000-000000000001"
U2 = "00000000-0000-0000-0000-000000000002"


def test_ordinals_follow_first_seen_order():
    m = UuidMapper()
    assert m.map(U1) == "UUID-0"
    assert m.map(U2) == "UUID-1"
    assert m.map(U1) == "UUID-0"          # stable on re-query
    assert m.map(U1.upper()) == "UUID-0"  # case-insensitive


def test_sub_replaces_embedded_uuids():
    m = UuidMapper()
    text = f"raw_data/{U1}/WsSim-0.0.0.0__0.hlo.json"
    assert m.sub(text) == "raw_data/UUID-0/WsSim-0.0.0.0__0.hlo.json"


def test_sub_strict_raises_on_unseeded_uuid():
    m = UuidMapper()
    with pytest.raises(KeyError):
        m.sub(f"x/{U1}/y", strict=True)
    m.map(U1)
    assert m.sub(f"x/{U1}/y", strict=True) == "x/UUID-0/y"


def test_process_uuid_derivation_is_checked():
    # spec §5.5: when an exp has no process_list,
    # process_uuid = uuid5(NAMESPACE_URL, f"{experiment_uuid}__{pidx}") —
    # normalize by tagging the derivation so the diff CHECKS it.
    m = UuidMapper()
    exp = U1
    derived = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{exp}__0"))
    assert m.register_derived(derived, exp, 0) is True
    assert m.map(derived) == "DERIVED:UUID-0__0"
    # a non-derived uuid is NOT tagged and falls through to ordinary mapping
    assert m.register_derived(U2, exp, 1) is False
    assert m.map(U2) == "UUID-1"


def test_sub_any_recurses_dicts_and_lists():
    m = UuidMapper()
    obj = {"a": [U1, {"b": U2}], "c": "no uuid here"}
    assert m.sub_any(obj) == {
        "a": ["UUID-0", {"b": "UUID-1"}],
        "c": "no uuid here",
    }
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
conda run -n helao python -m pytest harness/tests/test_uuidmap.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'harness.uuidmap'`.

- [ ] **Step 3: Write the implementation**

Create `harness/uuidmap.py`:

```python
"""UUID -> stable-ordinal mapping (spec §5.5, §6.4).

Runtime uuids are uuid7 (time-seeded) and always differ between captures,
but the LINKS they encode (parent/child action uuids, FileInfo.action_uuid,
per-sample action_uuid lists, S3 key prefixes, uuid5 process derivation) are
part of the parity contract. Mapping each capture's uuids to ordinals in a
deterministic order lets the diff CHECK link structure instead of blanket-
ignoring it — the F1 countermeasure applied to identity fields.

Ordinal determinism: any uuid that appears in a FILENAME must be seeded via
harness.treepass.seed_mapper (meta files in a capture-independent sort
order) before names are normalized; `sub(strict=True)` enforces this by
raising on an unseeded uuid in a name. Content-only uuids may map lazily —
given identical normalized structure, lazy first-seen order is identical on
both sides.
"""

from __future__ import annotations

import re
import uuid as uuid_mod
from typing import Dict

RE_UUID = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


class UuidMapper:
    """Assigns 'UUID-<n>' ordinals in first-seen order; one instance per capture."""

    def __init__(self) -> None:
        self._map: Dict[str, str] = {}
        self._derived: Dict[str, str] = {}

    def register_derived(
        self, raw_process_uuid: str, experiment_uuid: str, pidx
    ) -> bool:
        """Tag raw_process_uuid iff it equals uuid5(NAMESPACE_URL, exp__pidx).

        Returns True when the derivation held (spec §5.5 'exception with
        structure'); False leaves the uuid to ordinary ordinal mapping.
        """
        expected = str(
            uuid_mod.uuid5(uuid_mod.NAMESPACE_URL, f"{experiment_uuid}__{pidx}")
        )
        if raw_process_uuid.lower() == expected.lower():
            exp_ordinal = self.map(experiment_uuid)
            self._derived[raw_process_uuid.lower()] = f"DERIVED:{exp_ordinal}__{pidx}"
            return True
        return False

    def map(self, raw: str) -> str:
        key = raw.lower()
        if key in self._derived:
            return self._derived[key]
        if key not in self._map:
            self._map[key] = f"UUID-{len(self._map)}"
        return self._map[key]

    def sub(self, text: str, strict: bool = False) -> str:
        """Replace every uuid substring in ``text`` with its ordinal."""

        def repl(m: re.Match) -> str:
            key = m.group(0).lower()
            if strict and key not in self._map and key not in self._derived:
                raise KeyError(
                    f"unseeded uuid {m.group(0)} appears in a filename; extend "
                    "harness.treepass.seed_mapper so name ordinals stay "
                    "capture-independent"
                )
            return self.map(m.group(0))

        return RE_UUID.sub(repl, text)

    def sub_any(self, value):
        """Recursively substitute uuids inside str/list/dict values."""
        if isinstance(value, str):
            return self.sub(value)
        if isinstance(value, list):
            return [self.sub_any(v) for v in value]
        if isinstance(value, dict):
            return {self.sub(str(k)): self.sub_any(v) for k, v in value.items()}
        return value
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
conda run -n helao python -m pytest harness/tests/test_uuidmap.py -v
```

Expected: `5 passed`.

- [ ] **Step 5: Format and commit**

```bash
conda run -n helao black harness
git add harness/uuidmap.py harness/tests/test_uuidmap.py
git commit -m "feat(harness): uuid-to-ordinal mapper with uuid5 process-derivation check"
```

---

### Task 4: YAML pass — §5.5 volatile normalization + canonical diff

**Files:**
- Create: `harness/yaml_pass.py`
- Test: `harness/tests/test_yaml_pass.py`

**Interfaces:**
- Consumes: `harness.uuidmap.UuidMapper`; `harness.classify.normalize_relpath`.
- Produces: `to_plain(obj)` (ruamel CommentedMap/Seq → plain dict/list), `normalize_meta(obj, mapper: UuidMapper, key: str | None = None)` (returns the §5.5-normalized object), `canonicalize(d: dict) -> dict` (absent==empty pruning), `diff_meta(golden, candidate, path: str = "") -> list[dict]` (each diff entry is `{"key": str, "golden": Any, "candidate": Any}`), `diff_prg(golden: dict, candidate: dict) -> list[dict]`, `load_yml_plain(path) -> Any` (yml_load + to_plain). Constants exported for audit: `UUID_KEY_SUFFIXES`, `UUID_EXACT_KEYS`, `TIMESTAMP_KEY_SUFFIXES`, `TIMESTAMP_EXACT_KEYS`, `DROP_EXACT_KEYS`, `DROP_KEY_SUFFIXES`, `HOST_EXACT_KEYS`, `SORT_LIST_KEYS`.

- [ ] **Step 1: Write the failing test**

Create `harness/tests/test_yaml_pass.py`:

```python
"""§5.5 volatile normalization: exactly the spec list, nothing more."""

from harness.uuidmap import UuidMapper
from harness.yaml_pass import canonicalize, diff_meta, diff_prg, normalize_meta

U1 = "00000000-0000-0000-0000-000000000001"
U2 = "00000000-0000-0000-0000-000000000002"


def test_uuid_keys_are_mapped_not_dropped():
    m = UuidMapper()
    out = normalize_meta(
        {"action_uuid": U1, "experiment_uuid": U2, "run_id": U1}, m
    )
    assert out == {
        "action_uuid": "UUID-0",
        "experiment_uuid": "UUID-1",
        "run_id": "UUID-0",  # same raw uuid -> same ordinal: the LINK is checked
    }


def test_timestamps_and_code_identity():
    m = UuidMapper()
    out = normalize_meta(
        {
            "action_timestamp": "2025-07-16 13:14:21.123456",
            "action_finished_timestamp": "2025-07-16 13:15:00.000001",
            "epoch_ns": 1752671661000000000,
            "action_codehash": "abc123",
            "action_codepath": "/abs/host/path.py",
            "experiment_funcname": "SIM_websocket_data",
            "hlo_version": "2025.07.07",
            "exec_id": "acquire_data deadbeef",
            "dummy": True,
            "simulation": True,
            "access": "hte",
            "aux_file_paths": ["/abs/somewhere"],
            "orch_key": "ORCH",
            "orch_host": "127.0.0.1",
            "orch_port": 8001,
            "machine_name": "somehostname",
            "action_name": "acquire_data",
        },
        m,
    )
    assert out == {
        "action_timestamp": "TS",
        "action_finished_timestamp": "TS",
        "epoch_ns": "TS",
        "orch_key": "HOST",
        "orch_host": "HOST",
        "orch_port": "HOST",
        "machine_name": "HOST",
        "action_name": "acquire_data",
    }


def test_output_dir_paths_are_grammar_normalized():
    m = UuidMapper()
    out = normalize_meta(
        {
            "action_output_dir": "25.28/0716/131415__S__golden/250716.131420__E/0__0__SIM__acquire_data"
        },
        m,
    )
    assert out == {
        "action_output_dir": "YY.WW/MMDD/TS__S__golden/TS__E/0__0__SIM__acquire_data"
    }


def test_ordering_hazard_lists_are_sorted():
    m = UuidMapper()
    a = normalize_meta({"samples_in": [{"global_label": "b"}, {"global_label": "a"}]}, m)
    b = normalize_meta({"samples_in": [{"global_label": "a"}, {"global_label": "b"}]}, m)
    assert a == b


def test_absent_equals_empty():
    m = UuidMapper()
    a = normalize_meta({"action_params": {}, "files": [], "comment": "", "x": 1}, m)
    b = normalize_meta({"x": 1}, m)
    assert a == b == {"x": 1}
    assert canonicalize({"n": None, "s": "", "l": [], "d": {}, "keep": 0}) == {"keep": 0}


def test_non_volatile_content_diffs_are_reported():
    m1, m2 = UuidMapper(), UuidMapper()
    g = normalize_meta({"action_params": {"duration": 2.0}}, m1)
    c = normalize_meta({"action_params": {"duration": 3.0}}, m2)
    diffs = diff_meta(g, c)
    assert diffs == [
        {"key": "action_params.duration", "golden": 2.0, "candidate": 3.0}
    ]


def test_diff_meta_reports_absent_keys_and_list_lengths():
    assert diff_meta({"a": 1}, {}) == [
        {"key": "a", "golden": 1, "candidate": "<absent>"}
    ]
    assert diff_meta({"l": [1, 2]}, {"l": [1]}) == [
        {"key": "l.len", "golden": 2, "candidate": 1}
    ]


def test_prg_compares_only_terminal_booleans():
    g = {"yml": "/abs/a", "s3": True, "api": True, "files_pending": ["x"]}
    c = {"yml": "/abs/b", "s3": True, "api": True, "files_pending": []}
    assert diff_prg(g, c) == []
    c2 = dict(c, s3=False)
    assert diff_prg(g, c2) == [{"key": "s3", "golden": True, "candidate": False}]
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
conda run -n helao python -m pytest harness/tests/test_yaml_pass.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'harness.yaml_pass'`.

- [ ] **Step 3: Write the implementation**

Create `harness/yaml_pass.py`:

```python
"""YAML/meta content normalization + structural diff (spec §5.3, §5.5).

The volatile lists below are EXACTLY the spec §5.5 contract. Do NOT add
entries without a master-spec amendment: an over-broad normalizer re-creates
failure mode F1 by masking real diffs. Per-scenario VALUE masking (random sim
data) is manifest-driven and handled by hlo_pass/s3_pass, never here.

Normalization semantics per §5.5:
- identity fields (uuids, run_id, data_request_id): uuid-MAPPED via
  UuidMapper so parent/child links and the uuid5 process derivation are
  checked, not ignored;
- time fields (any *_timestamp, epoch_ns): collapsed to "TS";
- environment/code identity (codehash/codepath/funcname, hlo_version,
  exec_id, action_etc, dummy/simulation/access, aux_file_paths): DROPPED;
- host identity (orch_key/orch_host/orch_port, MachineModel.machine_name):
  collapsed to "HOST" (presence still checked);
- *_output_dir strings: timestamp components normalized via the §5.1 grammar;
- ordering hazards (samples_in/out, files, dispatched_*_abbr): stable-sorted
  before diffing;
- absent == empty (clean_dict pruning, §5.3): canonicalize drops
  None/''/[]/{} recursively on BOTH sides.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, List, Optional, Union

from helao.helpers.yml_tools import yml_load

from harness.classify import normalize_relpath
from harness.uuidmap import UuidMapper

# --- §5.5 volatile lists (exhaustive; keep in lockstep with the spec) ------
UUID_KEY_SUFFIXES = ("_uuid",)
UUID_EXACT_KEYS = {"run_id", "data_request_id"}
TIMESTAMP_KEY_SUFFIXES = ("_timestamp",)
TIMESTAMP_EXACT_KEYS = {"epoch_ns"}
DROP_KEY_SUFFIXES = ("_codehash", "_codepath", "_funcname")
DROP_EXACT_KEYS = {
    "hlo_version",
    "exec_id",
    "action_etc",
    "dummy",
    "simulation",
    "access",
    "aux_file_paths",
}
HOST_EXACT_KEYS = {"orch_key", "orch_host", "orch_port", "machine_name"}
OUTPUT_DIR_KEY_SUFFIX = "_output_dir"
# §5.5 ordering hazards: sort by a stable key before diffing.
SORT_LIST_KEYS = {
    "dispatched_actions_abbr",
    "dispatched_experiments_abbr",
    "files",
    "samples_in",
    "samples_out",
}


def to_plain(obj: Any) -> Any:
    """Convert ruamel round-trip containers to plain dict/list recursively."""
    if isinstance(obj, dict):
        return {str(k): to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_plain(v) for v in obj]
    return obj


def load_yml_plain(path: Union[str, Path]) -> Any:
    """Load a YAML file into plain Python containers."""
    return to_plain(yml_load(Path(path)))


def _stable_key(item: Any) -> str:
    return json.dumps(item, sort_keys=True, default=str)


def canonicalize(d: dict) -> dict:
    """absent == empty (§5.3): drop None/''/[]/{}; NaN -> None like clean_dict."""
    out = {}
    for k, v in d.items():
        if v is None or v == "" or v == [] or v == {}:
            continue
        if isinstance(v, float) and math.isnan(v):
            out[k] = None
            continue
        out[k] = v
    return out


def normalize_meta(obj: Any, mapper: UuidMapper, key: Optional[str] = None) -> Any:
    """Apply §5.5 normalization to a loaded YAML/JSON object, recursively."""
    if isinstance(obj, dict):
        out: dict = {}
        for k, v in obj.items():
            ks = str(k)
            if ks.endswith(DROP_KEY_SUFFIXES) or ks in DROP_EXACT_KEYS:
                continue
            if ks in HOST_EXACT_KEYS:
                out[ks] = "HOST"
                continue
            if ks.endswith(TIMESTAMP_KEY_SUFFIXES) or ks in TIMESTAMP_EXACT_KEYS:
                out[ks] = "TS"
                continue
            if ks.endswith(UUID_KEY_SUFFIXES) or ks in UUID_EXACT_KEYS:
                out[ks] = mapper.sub_any(v)
                continue
            out[ks] = normalize_meta(v, mapper, key=ks)
        for k in SORT_LIST_KEYS:
            if k in out and isinstance(out[k], list):
                out[k] = sorted(out[k], key=_stable_key)
        return canonicalize(out)
    if isinstance(obj, list):
        return [normalize_meta(v, mapper, key=key) for v in obj]
    if isinstance(obj, str):
        # embedded uuids (per-sample action_uuid strings, S3 key strings) map;
        # *_output_dir values additionally get the §5.1 grammar treatment.
        s = mapper.sub(obj)
        if key is not None and key.endswith(OUTPUT_DIR_KEY_SUFFIX):
            s = normalize_relpath(s)
        return s
    return obj


def diff_meta(golden: Any, candidate: Any, path: str = "") -> List[dict]:
    """Structural diff of two ALREADY-NORMALIZED objects; [] when identical."""
    diffs: List[dict] = []
    if isinstance(golden, bool) != isinstance(candidate, bool) or (
        type(golden) is not type(candidate)
        and not (
            isinstance(golden, (int, float)) and isinstance(candidate, (int, float))
        )
    ):
        diffs.append(
            {"key": path, "golden": repr(golden), "candidate": repr(candidate)}
        )
        return diffs
    if isinstance(golden, dict):
        for k in sorted(set(golden) | set(candidate)):
            kp = f"{path}.{k}" if path else str(k)
            if k not in golden:
                diffs.append(
                    {"key": kp, "golden": "<absent>", "candidate": candidate[k]}
                )
            elif k not in candidate:
                diffs.append(
                    {"key": kp, "golden": golden[k], "candidate": "<absent>"}
                )
            else:
                diffs.extend(diff_meta(golden[k], candidate[k], kp))
        return diffs
    if isinstance(golden, list):
        if len(golden) != len(candidate):
            diffs.append(
                {
                    "key": f"{path}.len" if path else "len",
                    "golden": len(golden),
                    "candidate": len(candidate),
                }
            )
            return diffs
        for i, (g, c) in enumerate(zip(golden, candidate)):
            diffs.extend(diff_meta(g, c, f"{path}[{i}]"))
        return diffs
    if golden != candidate:
        diffs.append({"key": path, "golden": golden, "candidate": candidate})
    return diffs


def diff_prg(golden: dict, candidate: dict) -> List[dict]:
    """.prg sidecars: only the terminal s3/api booleans are contractual (§5.7)."""
    diffs = []
    for k in ("s3", "api"):
        if golden.get(k) != candidate.get(k):
            diffs.append(
                {"key": k, "golden": golden.get(k), "candidate": candidate.get(k)}
            )
    return diffs
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
conda run -n helao python -m pytest harness/tests/test_yaml_pass.py -v
```

Expected: `8 passed`.

- [ ] **Step 5: Format and commit**

```bash
conda run -n helao black harness
git add harness/yaml_pass.py harness/tests/test_yaml_pass.py
git commit -m "feat(harness): YAML pass with the exhaustive spec-5.5 volatile-field contract"
```

---

### Task 5: Tree pass — snapshot, zip explode, mapper seeding, member-set diff

**Files:**
- Create: `harness/treepass.py`
- Create: `harness/tests/synthtree.py`
- Test: `harness/tests/test_treepass.py`

**Interfaces:**
- Consumes: `ArtifactRow`, `classify_file`, `normalize_relpath` (Task 2); `UuidMapper`, `RE_UUID` (Task 3); `load_yml_plain` (Task 4); `ProvenanceManifest`, `HARNESS_VERSION` (Task 1).
- Produces: `PARITY_TOPS: tuple` (`"RUNS_ACTIVE","RUNS_FINISHED","RUNS_SYNCED","RUNS_DIAG","RUNS_NOSYNC","PROCESSES","ANALYSES","S3_SIM"`), `explode_zips(root: Path, workdir: Path) -> Path`, `seed_mapper(root: Path, mapper: UuidMapper) -> None`, `snapshot(root: Path, mapper: UuidMapper) -> TreeSnapshot` (dataclass with `root: Path` and `files: dict[str, tuple[Path, ArtifactRow]]` keyed by normalized relpath), `diff_member_sets(golden: TreeSnapshot, candidate: TreeSnapshot) -> list[dict]` (entries `{"file": norm, "key": "<tree>", "golden": "present"|"absent", "candidate": ...}`). Test helper module `harness/tests/synthtree.py` with `build_tree(root: Path, seed: int = 0) -> dict` and `attach_manifest(golden_dir: Path, masked: dict | None = None, tolerance: dict | None = None, content_masked: dict | None = None) -> None` (used again by Tasks 8–9).

- [ ] **Step 1: Write the synthetic-tree helper (test infrastructure, not a parity fixture)**

Create `harness/tests/synthtree.py`:

```python
"""Synthetic mini-trees for NORMALIZER unit tests ONLY.

These trees are NOT parity fixtures: spec §6.1/D4 forbids hand-built golden
masters, and the gate enforces that with the provenance-manifest hard-fail.
Unit tests of the normalizer itself are the sanctioned exception; when a test
needs the gate to accept a synthetic tree it attaches a manifest EXPLICITLY
via attach_manifest(), whose notes field says exactly what it is.
"""

import uuid
from pathlib import Path

from harness import HARNESS_VERSION
from harness.manifest import ProvenanceManifest


def _u(n: int) -> str:
    return str(uuid.UUID(int=n))


def build_tree(root: Path, seed: int = 0) -> dict:
    """Create <root>/RUNS_FINISHED/... with 1 seq / 1 exp / 1 act / 1 hlo.

    ``seed`` offsets every uuid so two builds simulate two captures of the
    same run differing only in volatile identity. Returns the identifiers and
    directories used, for assertions.
    """
    seq_uuid = _u(seed + 1)
    exp_uuid = _u(seed + 2)
    act_uuid = _u(seed + 3)
    seq_dir = root / "RUNS_FINISHED" / "25.28" / "0716" / "131415__GMTEST__golden"
    exp_dir = seq_dir / "250716.131420__TEST_exp"
    act_dir = exp_dir / "0__0__SIM__acquire_data"
    act_dir.mkdir(parents=True)
    (seq_dir / "250716.131415123456-seq.yml").write_text(
        "file_type: sequence\n"
        f"sequence_uuid: {seq_uuid}\n"
        "sequence_name: GMTEST\n"
        "sequence_label: golden\n"
        "sequence_timestamp: 2025-07-16 13:14:15.123456\n"
        "sequence_status:\n  - finished\n"
        "dummy: true\n"
    )
    (exp_dir / "250716.131420123456-exp.yml").write_text(
        "file_type: experiment\n"
        f"experiment_uuid: {exp_uuid}\n"
        f"sequence_uuid: {seq_uuid}\n"
        "experiment_name: TEST_exp\n"
        "experiment_timestamp: 2025-07-16 13:14:20.123456\n"
        "experiment_status:\n  - finished\n"
    )
    (act_dir / "250716.131421123456-act.yml").write_text(
        "file_type: action\n"
        f"action_uuid: {act_uuid}\n"
        f"experiment_uuid: {exp_uuid}\n"
        f"sequence_uuid: {seq_uuid}\n"
        "action_name: acquire_data\n"
        "action_timestamp: 2025-07-16 13:14:21.123456\n"
        "action_status:\n  - finished\n"
        "action_params:\n  duration: 2.0\n"
    )
    (act_dir / "WsSim-0.0.0.0__0.hlo").write_text(
        "hlo_version: '2025.07.07'\n"
        "action_name: WsSim\n"
        "column_headings:\n"
        "  - t_s\n"
        "  - series_0\n"
        "epoch_ns: 1752671661000000000\n"
        "%%\n"
        '{"t_s": 0.0, "series_0": 0.5}\n'
        '{"t_s": 0.1, "series_0": 0.6}\n'
    )
    return {
        "seq_uuid": seq_uuid,
        "exp_uuid": exp_uuid,
        "act_uuid": act_uuid,
        "seq_dir": seq_dir,
        "exp_dir": exp_dir,
        "act_dir": act_dir,
    }


def attach_manifest(
    golden_dir: Path,
    masked: dict | None = None,
    tolerance: dict | None = None,
    content_masked: dict | None = None,
) -> None:
    ProvenanceManifest(
        scenario="SYNTH",
        config_prefix="synthetic-unit-test",
        config_path="synthetic-unit-test",
        legacy_git_sha="0" * 40,
        launch_cmd="synthetic-unit-test",
        sequence_name="GMTEST",
        sequence_params={},
        capture_timestamp="2026-07-16T00:00:00",
        harness_version=HARNESS_VERSION,
        masked_hlo_columns=masked or {},
        hlo_row_count_tolerance=tolerance or {},
        content_masked_files=content_masked or {},
        notes="synthetic tree for normalizer unit tests ONLY — never a parity golden",
    ).save(golden_dir)
```

- [ ] **Step 2: Write the failing test**

Create `harness/tests/test_treepass.py`:

```python
"""Tree snapshot, member-set diff, zip exploding, and capture-independent seeding."""

import zipfile

from harness.classify import ArtifactRow
from harness.tests.synthtree import build_tree
from harness.treepass import (
    diff_member_sets,
    explode_zips,
    seed_mapper,
    snapshot,
)
from harness.uuidmap import UuidMapper


def test_snapshot_normalizes_names_and_classifies(tmp_path):
    build_tree(tmp_path)
    m = UuidMapper()
    seed_mapper(tmp_path, m)
    snap = snapshot(tmp_path, m)
    key = (
        "RUNS_FINISHED/YY.WW/MMDD/TS__GMTEST__golden/TS__TEST_exp/"
        "0__0__SIM__acquire_data/TS-act.yml"
    )
    assert key in snap.files
    assert snap.files[key][1] is ArtifactRow.ACT_YML
    hlo_key = (
        "RUNS_FINISHED/YY.WW/MMDD/TS__GMTEST__golden/TS__TEST_exp/"
        "0__0__SIM__acquire_data/WsSim-0.0.0.0__0.hlo"
    )
    assert snap.files[hlo_key][1] is ArtifactRow.HLO


def test_two_seeds_produce_identical_member_sets(tmp_path):
    ga, gb = tmp_path / "a", tmp_path / "b"
    build_tree(ga, seed=0)
    build_tree(gb, seed=100)
    ma, mb = UuidMapper(), UuidMapper()
    seed_mapper(ga, ma)
    seed_mapper(gb, mb)
    assert diff_member_sets(snapshot(ga, ma), snapshot(gb, mb)) == []


def test_missing_file_shows_in_member_diff(tmp_path):
    ga, gb = tmp_path / "a", tmp_path / "b"
    ids_a = build_tree(ga, seed=0)
    build_tree(gb, seed=100)
    (ids_a["act_dir"] / "WsSim-0.0.0.0__0.hlo").unlink()
    ma, mb = UuidMapper(), UuidMapper()
    seed_mapper(ga, ma)
    seed_mapper(gb, mb)
    diffs = diff_member_sets(snapshot(ga, ma), snapshot(gb, mb))
    assert len(diffs) == 1
    assert diffs[0]["golden"] == "absent" and diffs[0]["candidate"] == "present"


def test_explode_zips_expands_sequence_zips(tmp_path):
    root = tmp_path / "root"
    ids = build_tree(root)
    # zip the sequence dir the way the syncer does (entries relative to it),
    # then delete the dir — RUNS_SYNCED end state (spec §5.2 row 10).
    synced = root / "RUNS_SYNCED" / "25.28" / "0716"
    synced.mkdir(parents=True)
    zpath = synced / "131415__GMTEST__golden.zip"
    seq_dir = ids["seq_dir"]
    with zipfile.ZipFile(zpath, "w") as zf:
        for f in sorted(seq_dir.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(seq_dir).as_posix())
    exploded = explode_zips(root, tmp_path / "work")
    zipdir = (
        exploded / "RUNS_SYNCED" / "25.28" / "0716" / "131415__GMTEST__golden.zipdir"
    )
    assert zipdir.is_dir()
    assert (zipdir / "250716.131415123456-seq.yml").is_file()
    assert not (
        exploded / "RUNS_SYNCED" / "25.28" / "0716" / "131415__GMTEST__golden.zip"
    ).exists()


def test_seeded_ordinals_are_capture_independent(tmp_path):
    # seq yml seeds before exp before act regardless of raw uuid sort order,
    # so links map to the same ordinals in both captures.
    ga, gb = tmp_path / "a", tmp_path / "b"
    build_tree(ga, seed=0)
    build_tree(gb, seed=500)
    ma, mb = UuidMapper(), UuidMapper()
    seed_mapper(ga, ma)
    seed_mapper(gb, mb)
    from harness.tests.synthtree import _u

    assert ma.map(_u(1)) == mb.map(_u(501))  # sequence_uuid -> same ordinal
    assert ma.map(_u(3)) == mb.map(_u(503))  # action_uuid -> same ordinal
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
conda run -n helao python -m pytest harness/tests/test_treepass.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'harness.treepass'`.

- [ ] **Step 4: Write the implementation**

Create `harness/treepass.py`:

```python
"""Tree pass (spec §6.4): capture snapshot -> normalized member set.

- explode_zips: RUNS_SYNCED sequence zips are expanded into sibling
  ``<name>.zipdir`` directories inside a working copy, so the zip MEMBER SET
  (the §5.7 contract for synced sequences, .prg sidecars included) is
  asserted by the ordinary tree compare, and members join the per-file passes.
- seed_mapper: assigns uuid ordinals from meta-file content in a
  capture-independent order (row order seq -> exp -> act -> prc; within a row,
  sorted by the uuid-blanked normalized path), so uuids appearing in
  FILENAMES (prc ymls, S3 keys) normalize identically on both sides.
- snapshot: normalized-relpath -> (real path, ArtifactRow) map;
  IGNORE and LOCK rows excluded (row 11: .lock is ignored everywhere).
"""

from __future__ import annotations

import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Tuple

from harness.classify import ArtifactRow, classify_file, normalize_relpath
from harness.uuidmap import RE_UUID, UuidMapper
from harness.yaml_pass import load_yml_plain

PARITY_TOPS = (
    "RUNS_ACTIVE",
    "RUNS_FINISHED",
    "RUNS_SYNCED",
    "RUNS_DIAG",
    "RUNS_NOSYNC",
    "PROCESSES",
    "ANALYSES",
    "S3_SIM",
)

ROW_SEED_ORDER = (
    ArtifactRow.SEQ_YML,
    ArtifactRow.EXP_YML,
    ArtifactRow.ACT_YML,
    ArtifactRow.PRC_YML,
)

SEED_UUID_KEYS = ("sequence_uuid", "experiment_uuid", "action_uuid", "process_uuid")


@dataclass
class TreeSnapshot:
    root: Path
    files: Dict[str, Tuple[Path, ArtifactRow]] = field(default_factory=dict)


def _iter_parity_files(root: Path) -> Iterator[Path]:
    for top in PARITY_TOPS:
        top_dir = root / top
        if not top_dir.is_dir():
            continue
        for f in sorted(top_dir.rglob("*")):
            if f.is_file():
                yield f


def explode_zips(root: Path, workdir: Path) -> Path:
    """Copy ``root`` into ``workdir`` and expand every .zip into ``.zipdir``."""
    dest = Path(workdir) / "exploded"
    shutil.copytree(root, dest)
    for zpath in sorted(dest.rglob("*.zip")):
        target = zpath.with_suffix(".zipdir")
        with zipfile.ZipFile(zpath) as zf:
            zf.extractall(target)
        zpath.unlink()
    return dest


def seed_mapper(root: Path, mapper: UuidMapper) -> None:
    """Assign uuid ordinals in a capture-independent order (meta files first).

    The sort key blanks raw uuids out of the normalized path so ordering is
    identical for two captures of the same scenario. prc ymls additionally
    attempt the uuid5 derivation registration (spec §5.5 exception-with-
    structure): register_derived is a checked no-op when the process uuid is
    not derived.
    """
    buckets: Dict[ArtifactRow, List[Tuple[str, Path]]] = {
        row: [] for row in ROW_SEED_ORDER
    }
    for f in _iter_parity_files(root):
        rel = f.relative_to(root).as_posix()
        row = classify_file(rel)
        if row in buckets:
            sort_key = RE_UUID.sub("UUID", normalize_relpath(rel))
            buckets[row].append((sort_key, f))
    for row in ROW_SEED_ORDER:
        for _, f in sorted(buckets[row]):
            d = load_yml_plain(f)
            if not isinstance(d, dict):
                continue
            if row is ArtifactRow.PRC_YML:
                pu = d.get("process_uuid")
                eu = d.get("experiment_uuid")
                pidx = d.get("process_group_index")
                if pu and eu and pidx is not None:
                    mapper.register_derived(str(pu), str(eu), pidx)
            for k in SEED_UUID_KEYS:
                if d.get(k):
                    mapper.map(str(d[k]))


def snapshot(root: Path, mapper: UuidMapper) -> TreeSnapshot:
    """Build the normalized member map; strict uuid substitution in names."""
    snap = TreeSnapshot(root=root)
    for f in _iter_parity_files(root):
        rel = f.relative_to(root).as_posix()
        row = classify_file(rel)
        if row in (ArtifactRow.IGNORE, ArtifactRow.LOCK):
            continue
        norm = mapper.sub(normalize_relpath(rel), strict=True)
        if norm in snap.files:
            raise ValueError(f"normalized-name collision: {norm} ({rel})")
        snap.files[norm] = (f, row)
    return snap


def diff_member_sets(golden: TreeSnapshot, candidate: TreeSnapshot) -> List[dict]:
    diffs: List[dict] = []
    gset, cset = set(golden.files), set(candidate.files)
    for missing in sorted(gset - cset):
        diffs.append(
            {"file": missing, "key": "<tree>", "golden": "present", "candidate": "absent"}
        )
    for extra in sorted(cset - gset):
        diffs.append(
            {"file": extra, "key": "<tree>", "golden": "absent", "candidate": "present"}
        )
    return diffs
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
conda run -n helao python -m pytest harness/tests/test_treepass.py -v
```

Expected: `5 passed`.

- [ ] **Step 6: Format and commit**

```bash
conda run -n helao black harness
git add harness/treepass.py harness/tests/synthtree.py harness/tests/test_treepass.py
git commit -m "feat(harness): tree pass with zip explode, capture-independent uuid seeding, member-set diff"
```

---

### Task 6: HLO pass — header/`%%`/JSON-lines body with manifest-driven masking

**Files:**
- Create: `harness/hlo_pass.py`
- Test: `harness/tests/test_hlo_pass.py`

**Interfaces:**
- Consumes: `UuidMapper` (Task 3); `normalize_meta`, `diff_meta` (Task 4); legacy `helao.helpers.hlo_data.read_hlo` (returns `(meta_dict, data_dict_of_column_lists)`, splits header from body on the `%%` line, tolerates NaN/Infinity tokens).
- Produces: `normalize_hlo_header(header: dict, mapper: UuidMapper) -> dict` (drops `epoch_ns` + `hlo_version` per §5.5/§5.4(10), then §5.5-normalizes), `masked_columns_for(norm_name: str, masked_hlo_columns: dict) -> set`, `row_tolerance_for(norm_name: str, tolerances: dict) -> int`, `diff_hlo_body(g_data: dict, c_data: dict, masked: set, tolerance: int) -> list[dict]`, `diff_hlo(golden_path, candidate_path, norm_name, mapper_g, mapper_c, manifest) -> list[dict]`. `diff_hlo_body` is reused by the S3 pass (Task 7) for `raw_data/.../*.hlo.json` payloads.

- [ ] **Step 1: Write the failing test**

Create `harness/tests/test_hlo_pass.py`:

```python
"""HLO compare: header normalized, %% split honored, masked columns by manifest."""

from pathlib import Path

from harness.hlo_pass import diff_hlo, diff_hlo_body, masked_columns_for
from harness.manifest import ProvenanceManifest
from harness import HARNESS_VERSION
from harness.uuidmap import UuidMapper


def write_hlo(path: Path, epoch_ns: int, rows: list[str]) -> None:
    path.write_text(
        "hlo_version: '2025.07.07'\n"
        "action_name: WsSim\n"
        "column_headings:\n"
        "  - epoch_s\n"
        "  - series_0\n"
        f"epoch_ns: {epoch_ns}\n"
        "%%\n" + "".join(r + "\n" for r in rows)
    )


def make_manifest(masked: dict, tolerance: dict) -> ProvenanceManifest:
    return ProvenanceManifest(
        scenario="SYNTH",
        config_prefix="x",
        config_path="x",
        legacy_git_sha="0" * 40,
        launch_cmd="x",
        sequence_name="x",
        sequence_params={},
        capture_timestamp="2026-07-16T00:00:00",
        harness_version=HARNESS_VERSION,
        masked_hlo_columns=masked,
        hlo_row_count_tolerance=tolerance,
    )


def test_epoch_ns_and_hlo_version_never_diff(tmp_path):
    a, b = tmp_path / "a.hlo", tmp_path / "b.hlo"
    write_hlo(a, 111, ['{"epoch_s": 1.0, "series_0": 0.5}'])
    write_hlo(b, 999, ['{"epoch_s": 1.0, "series_0": 0.5}'])
    diffs = diff_hlo(a, b, "x/a.hlo", UuidMapper(), UuidMapper(), make_manifest({}, {}))
    assert diffs == []


def test_unmasked_value_change_is_caught(tmp_path):
    a, b = tmp_path / "a.hlo", tmp_path / "b.hlo"
    write_hlo(a, 1, ['{"epoch_s": 1.0, "series_0": 0.5}'])
    write_hlo(b, 1, ['{"epoch_s": 1.0, "series_0": 0.7}'])
    diffs = diff_hlo(a, b, "x/a.hlo", UuidMapper(), UuidMapper(), make_manifest({}, {}))
    assert any(d["key"] == "body.series_0" for d in diffs)


def test_masked_column_values_are_ignored(tmp_path):
    a, b = tmp_path / "a.hlo", tmp_path / "b.hlo"
    write_hlo(a, 1, ['{"epoch_s": 1.0, "series_0": 0.5}'])
    write_hlo(b, 1, ['{"epoch_s": 2.0, "series_0": 0.7}'])
    manifest = make_manifest({"x/*.hlo": ["epoch_s", "series_0"]}, {})
    assert diff_hlo(a, b, "x/a.hlo", UuidMapper(), UuidMapper(), manifest) == []


def test_masked_column_row_count_respects_tolerance(tmp_path):
    a, b = tmp_path / "a.hlo", tmp_path / "b.hlo"
    write_hlo(a, 1, ['{"series_0": 0.5}'] * 10)
    write_hlo(b, 1, ['{"series_0": 0.7}'] * 12)
    strict = make_manifest({"x/*.hlo": ["series_0"]}, {})
    assert diff_hlo(a, b, "x/a.hlo", UuidMapper(), UuidMapper(), strict) != []
    tolerant = make_manifest({"x/*.hlo": ["series_0"]}, {"x/*.hlo": 3})
    assert diff_hlo(a, b, "x/a.hlo", UuidMapper(), UuidMapper(), tolerant) == []


def test_missing_column_is_structural_even_when_masked():
    diffs = diff_hlo_body({"a": [1]}, {}, masked={"a"}, tolerance=0)
    assert diffs == [{"key": "body.a", "golden": "present", "candidate": "<absent>"}]


def test_masked_columns_for_matches_fnmatch():
    cols = masked_columns_for(
        "RUNS_FINISHED/x/WsSim-0.0.0.0__0.hlo", {"*WsSim*.hlo": ["epoch_s"]}
    )
    assert cols == {"epoch_s"}
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
conda run -n helao python -m pytest harness/tests/test_hlo_pass.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'harness.hlo_pass'`.

- [ ] **Step 3: Write the implementation**

Create `harness/hlo_pass.py`:

```python
"""HLO pass (spec §5.2 row 4/5, §5.5, §6.4).

Header: parsed by the legacy reader (real consumer's decoder — §10.1 rule 3),
then epoch_ns is dropped (stamped at lazy-open OR header-finish, two legal
code paths — §5.4 item 10) and hlo_version dropped (release string), then
§5.5-normalized like any meta dict.

Body: one JSON object per line after ``%%``; compared column-by-column as
parsed values. Columns listed in the golden manifest's masked_hlo_columns
(matched by fnmatch on the NORMALIZED path) have their VALUES masked —
presence and row counts are still asserted, within the manifest's optional
hlo_row_count_tolerance (poll-paced sim executors jitter by a row or two).
"""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import List, Set

from helao.helpers.hlo_data import read_hlo

from harness.manifest import ProvenanceManifest
from harness.uuidmap import UuidMapper
from harness.yaml_pass import diff_meta, normalize_meta


def normalize_hlo_header(header: dict, mapper: UuidMapper) -> dict:
    hdr = {k: v for k, v in dict(header).items() if k not in ("epoch_ns", "hlo_version")}
    return normalize_meta(hdr, mapper)


def masked_columns_for(norm_name: str, masked_hlo_columns: dict) -> Set[str]:
    cols: Set[str] = set()
    for pattern, columns in (masked_hlo_columns or {}).items():
        if fnmatch.fnmatch(norm_name, pattern):
            cols.update(columns)
    return cols


def row_tolerance_for(norm_name: str, tolerances: dict) -> int:
    best = 0
    for pattern, tol in (tolerances or {}).items():
        if fnmatch.fnmatch(norm_name, pattern):
            best = max(best, int(tol))
    return best


def diff_hlo_body(
    g_data: dict, c_data: dict, masked: Set[str], tolerance: int
) -> List[dict]:
    diffs: List[dict] = []
    for col in sorted(set(g_data) | set(c_data)):
        if col not in g_data:
            diffs.append(
                {"key": f"body.{col}", "golden": "<absent>", "candidate": "present"}
            )
            continue
        if col not in c_data:
            diffs.append(
                {"key": f"body.{col}", "golden": "present", "candidate": "<absent>"}
            )
            continue
        g_col, c_col = g_data[col], c_data[col]
        if col in masked:
            if abs(len(g_col) - len(c_col)) > tolerance:
                diffs.append(
                    {
                        "key": f"body.{col}.len",
                        "golden": len(g_col),
                        "candidate": len(c_col),
                    }
                )
            continue
        diffs.extend(diff_meta(g_col, c_col, f"body.{col}"))
    return diffs


def diff_hlo(
    golden_path: Path,
    candidate_path: Path,
    norm_name: str,
    mapper_g: UuidMapper,
    mapper_c: UuidMapper,
    manifest: ProvenanceManifest,
) -> List[dict]:
    g_meta, g_data = read_hlo(str(golden_path))
    c_meta, c_data = read_hlo(str(candidate_path))
    diffs = diff_meta(
        normalize_hlo_header(g_meta, mapper_g),
        normalize_hlo_header(c_meta, mapper_c),
        path="header",
    )
    diffs.extend(
        diff_hlo_body(
            dict(g_data),
            dict(c_data),
            masked_columns_for(norm_name, manifest.masked_hlo_columns),
            row_tolerance_for(norm_name, manifest.hlo_row_count_tolerance),
        )
    )
    return diffs
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
conda run -n helao python -m pytest harness/tests/test_hlo_pass.py -v
```

Expected: `6 passed`.

- [ ] **Step 5: Format and commit**

```bash
conda run -n helao black harness
git add harness/hlo_pass.py harness/tests/test_hlo_pass.py
git commit -m "feat(harness): HLO pass with legacy reader, manifest-driven column masking"
```

---

### Task 7: S3 pass — recorded payloads, key templates, intentional-difference assertions

**Files:**
- Create: `harness/s3_pass.py`
- Test: `harness/tests/test_s3_pass.py`

**Interfaces:**
- Consumes: `UuidMapper` (Task 3); `normalize_meta`, `diff_meta`, `load_yml_plain` (Task 4); `normalize_hlo_header`, `diff_hlo_body`, `masked_columns_for`, `row_tolerance_for` (Task 6); `ProvenanceManifest` (Task 1).
- Produces: `diff_s3_record(norm: str, gpath: Path, cpath: Path, mg, mc, manifest) -> list[dict]` (dispatch for one paired file under `S3_SIM/`), `diff_s3_manifest(gpath, cpath, mg, mc) -> list[dict]` (the recorder's `manifest.jsonl`), `assert_s3_meta_rules(disk_act: dict, s3_act: dict) -> list[dict]` (per-capture internal-consistency check of the two INTENTIONAL on-disk-vs-S3 differences), `internal_s3_checks(root: Path) -> list[dict]` (walks one exploded capture root, pairs `S3_SIM/<bucket>/action/<uuid>.json` with its on-disk `-act.yml` by raw uuid, applies `assert_s3_meta_rules`). Recorder file layout consumed here is produced by Task 11: `S3_SIM/<bucket>/<key>` + `S3_SIM/manifest.jsonl` with lines `{"bucket","key","mode","gzip"}`.

- [ ] **Step 1: Write the failing test**

Create `harness/tests/test_s3_pass.py`:

```python
"""S3 payload compare + the intentional on-disk-vs-S3 difference assertions (§5.5)."""

import json

from harness.s3_pass import (
    assert_s3_meta_rules,
    diff_s3_manifest,
    diff_s3_record,
)
from harness.manifest import ProvenanceManifest
from harness import HARNESS_VERSION
from harness.uuidmap import UuidMapper

U1 = "00000000-0000-0000-0000-000000000001"
U2 = "00000000-0000-0000-0000-000000000002"


def manifest():
    return ProvenanceManifest(
        scenario="SYNTH",
        config_prefix="x",
        config_path="x",
        legacy_git_sha="0" * 40,
        launch_cmd="x",
        sequence_name="x",
        sequence_params={},
        capture_timestamp="2026-07-16T00:00:00",
        harness_version=HARNESS_VERSION,
    )


def test_meta_json_payloads_are_normalized_and_diffed(tmp_path):
    g, c = tmp_path / "g.json", tmp_path / "c.json"
    g.write_text(json.dumps({"action_uuid": U1, "action_params": {"duration": 2.0}}))
    c.write_text(json.dumps({"action_uuid": U2, "action_params": {"duration": 2.0}}))
    mg, mc = UuidMapper(), UuidMapper()
    norm = "S3_SIM/helao-sim/action/UUID-0.json"
    assert diff_s3_record(norm, g, c, mg, mc, manifest()) == []
    c.write_text(json.dumps({"action_uuid": U2, "action_params": {"duration": 9.0}}))
    diffs = diff_s3_record(norm, g, c, mg, mc, manifest())
    assert any("duration" in d["key"] for d in diffs)


def test_hlo_json_payload_uses_body_masking(tmp_path):
    payload_g = {"meta": {"action_name": "WsSim", "epoch_ns": 1},
                 "data": {"series_0": [0.5]}}
    payload_c = {"meta": {"action_name": "WsSim", "epoch_ns": 2},
                 "data": {"series_0": [0.9]}}
    g, c = tmp_path / "g.hlo.json", tmp_path / "c.hlo.json"
    g.write_text(json.dumps(payload_g))
    c.write_text(json.dumps(payload_c))
    m = manifest()
    m.masked_hlo_columns = {"*WsSim*.hlo.json": ["series_0"]}
    norm = "S3_SIM/helao-sim/raw_data/UUID-0/WsSim-0.0.0.0__0.hlo.json"
    assert diff_s3_record(norm, g, c, UuidMapper(), UuidMapper(), m) == []


def test_s3_manifest_jsonl_compares_mapped_key_sets(tmp_path):
    g, c = tmp_path / "g.jsonl", tmp_path / "c.jsonl"
    g.write_text(
        json.dumps({"bucket": "b", "key": f"action/{U1}.json", "mode": "fileobj", "gzip": False})
        + "\n"
    )
    c.write_text(
        json.dumps({"bucket": "b", "key": f"action/{U2}.json", "mode": "fileobj", "gzip": False})
        + "\n"
    )
    mg, mc = UuidMapper(), UuidMapper()
    mg.map(U1)
    mc.map(U2)
    assert diff_s3_manifest(g, c, mg, mc) == []
    c.write_text(
        json.dumps({"bucket": "b", "key": f"action/{U2}.json", "mode": "fileobj", "gzip": True})
        + "\n"
    )
    assert diff_s3_manifest(g, c, mg, mc) != []


def test_fileinfo_rename_rule_is_asserted():
    disk_act = {
        "files": [{"file_name": "WsSim-0.0.0.0__0.hlo", "file_type": "helao__file"}],
        "technique_name": ["t1", "t2"],
    }
    good_s3 = {
        "files": [
            {"file_name": "WsSim-0.0.0.0__0.hlo.json", "file_type": "helao__hlo_file"}
        ],
        "technique_name": "t1",
    }
    assert assert_s3_meta_rules(disk_act, good_s3) == []
    bad_type = {
        "files": [
            {"file_name": "WsSim-0.0.0.0__0.hlo.json", "file_type": "helao__file"}
        ],
        "technique_name": "t1",
    }
    assert assert_s3_meta_rules(disk_act, bad_type) != []
    bad_technique = dict(good_s3, technique_name=["t1", "t2"])
    assert assert_s3_meta_rules(disk_act, bad_technique) != []
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
conda run -n helao python -m pytest harness/tests/test_s3_pass.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'harness.s3_pass'`.

- [ ] **Step 3: Write the implementation**

Create `harness/s3_pass.py`:

```python
"""S3 pass (spec §5.6, §5.5, §6.4): recorded uploads from the sim DB server.

Recorder layout (Task 11 / sim_db_server.RecordingS3Client):
    S3_SIM/<bucket>/<key>          — the uploaded object bytes
    S3_SIM/manifest.jsonl          — one {"bucket","key","mode","gzip"} per upload

Key templates are asserted by the tree pass (uuid-mapped names); this module
compares payload CONTENT and the recorder manifest, and asserts the two
INTENTIONAL on-disk-vs-S3 differences that §5.5 requires the harness to
check as differences, not sameness:
  1. FileInfo rename rule in the S3 action meta:
     file_name  x.hlo        -> x.hlo.json
     file_type  helao__file  -> helao__<ext>_file  (hlo -> helao__hlo_file)
  2. technique_name list -> str split applied ONLY in the S3/prc copies.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path, PurePosixPath
from typing import List

from harness.hlo_pass import (
    diff_hlo_body,
    masked_columns_for,
    normalize_hlo_header,
    row_tolerance_for,
)
from harness.manifest import ProvenanceManifest
from harness.uuidmap import UuidMapper
from harness.yaml_pass import diff_meta, load_yml_plain, normalize_meta


def _load_bytes(path: Path) -> bytes:
    raw = Path(path).read_bytes()
    if str(path).endswith(".gz"):
        raw = gzip.decompress(raw)
    return raw


def diff_s3_manifest(
    gpath: Path, cpath: Path, mg: UuidMapper, mc: UuidMapper
) -> List[dict]:
    def entries(path: Path, mapper: UuidMapper) -> set:
        out = set()
        for line in Path(path).read_text().splitlines():
            if not line.strip():
                continue
            e = json.loads(line)
            out.add((e["bucket"], mapper.sub(e["key"]), bool(e.get("gzip"))))
        return out

    g, c = entries(gpath, mg), entries(cpath, mc)
    diffs: List[dict] = []
    for missing in sorted(g - c):
        diffs.append(
            {"key": f"s3_manifest{missing}", "golden": "present", "candidate": "absent"}
        )
    for extra in sorted(c - g):
        diffs.append(
            {"key": f"s3_manifest{extra}", "golden": "absent", "candidate": "present"}
        )
    return diffs


def diff_s3_record(
    norm: str,
    gpath: Path,
    cpath: Path,
    mg: UuidMapper,
    mc: UuidMapper,
    manifest: ProvenanceManifest,
) -> List[dict]:
    name = PurePosixPath(norm).name
    if name == "manifest.jsonl":
        return diff_s3_manifest(gpath, cpath, mg, mc)
    if ".hlo.json" in name:
        g = json.loads(_load_bytes(gpath))
        c = json.loads(_load_bytes(cpath))
        diffs = diff_meta(
            normalize_hlo_header(g.get("meta", {}), mg),
            normalize_hlo_header(c.get("meta", {}), mc),
            path="meta",
        )
        diffs.extend(
            diff_hlo_body(
                g.get("data", {}),
                c.get("data", {}),
                masked_columns_for(norm, manifest.masked_hlo_columns),
                row_tolerance_for(norm, manifest.hlo_row_count_tolerance),
            )
        )
        return diffs
    if name.endswith(".json") or name.endswith(".json.gz"):
        g = json.loads(_load_bytes(gpath))
        c = json.loads(_load_bytes(cpath))
        return diff_meta(normalize_meta(g, mg), normalize_meta(c, mc))
    # other raw_data misc uploads: exact bytes (content-masked files are
    # handled by the parity dispatcher's aux branch before reaching here)
    if _load_bytes(gpath) != _load_bytes(cpath):
        return [{"key": "<bytes>", "golden": "differs", "candidate": "differs"}]
    return []


def assert_s3_meta_rules(disk_act: dict, s3_act: dict) -> List[dict]:
    """Per-capture consistency: the intentional on-disk vs S3 differences hold."""
    diffs: List[dict] = []
    disk_files = {
        fi.get("file_name"): fi
        for fi in disk_act.get("files", [])
        if isinstance(fi, dict)
    }
    for fi in s3_act.get("files", []):
        if not isinstance(fi, dict):
            continue
        name = fi.get("file_name", "")
        if name.endswith(".hlo.json"):
            orig = name[: -len(".json")]
            if orig not in disk_files:
                diffs.append(
                    {
                        "key": f"files[{name}].file_name",
                        "golden": "rename rule: on-disk .hlo FileInfo expected",
                        "candidate": "no matching on-disk entry",
                    }
                )
            elif fi.get("file_type") != "helao__hlo_file":
                diffs.append(
                    {
                        "key": f"files[{name}].file_type",
                        "golden": "helao__hlo_file",
                        "candidate": fi.get("file_type"),
                    }
                )
    tn_disk = disk_act.get("technique_name")
    tn_s3 = s3_act.get("technique_name")
    if isinstance(tn_disk, list):
        if not isinstance(tn_s3, str) or tn_s3 not in tn_disk:
            diffs.append(
                {
                    "key": "technique_name",
                    "golden": f"str member of {tn_disk} (S3 split patch)",
                    "candidate": tn_s3,
                }
            )
    return diffs


def internal_s3_checks(root: Path) -> List[dict]:
    """Pair S3 action metas with on-disk act ymls (raw uuid) in ONE capture."""
    act_index: dict = {}
    for act_yml in Path(root).rglob("*-act.yml"):
        d = load_yml_plain(act_yml)
        if isinstance(d, dict) and d.get("action_uuid"):
            act_index[str(d["action_uuid"]).lower()] = d
    diffs: List[dict] = []
    s3_root = Path(root) / "S3_SIM"
    if not s3_root.is_dir():
        return diffs
    for meta_json in sorted(s3_root.glob("*/action/*.json")):
        raw_uuid = meta_json.stem.lower()
        disk_act = act_index.get(raw_uuid)
        if disk_act is None:
            diffs.append(
                {
                    "key": f"S3 action meta {meta_json.name}",
                    "golden": "matching on-disk -act.yml",
                    "candidate": "<absent>",
                }
            )
            continue
        s3_act = json.loads(_load_bytes(meta_json))
        for d in assert_s3_meta_rules(disk_act, s3_act):
            d["key"] = f"{meta_json.name}:{d['key']}"
            diffs.append(d)
    return diffs
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
conda run -n helao python -m pytest harness/tests/test_s3_pass.py -v
```

Expected: `4 passed`.

- [ ] **Step 5: Format and commit**

```bash
conda run -n helao black harness
git add harness/s3_pass.py harness/tests/test_s3_pass.py
git commit -m "feat(harness): S3 pass with payload normalization and intentional-difference assertions"
```

---

### Task 8: Parity gate CLI + normalizer façade

**Files:**
- Create: `harness/parity.py`
- Create: `harness/normalize.py`
- Test: `harness/tests/test_parity_cli.py`

**Interfaces:**
- Consumes: everything from Tasks 1–7 by the exact names in their Produces blocks.
- Produces: `harness.parity.run_parity(golden_set: Path, candidate: Path, report_path: Path | None = None) -> dict` (the report dict; `report["status"]` is `"pass"` or `"fail"`, `report["run_id"]` is a 12-hex id), module CLI `python -m harness.parity --golden <set> --candidate <set-or-root> [--report out.json]` with exit codes 0 pass / 1 diffs / 2 manifest-missing-or-usage; `harness.normalize` re-exports every pass symbol and provides `python -m harness.normalize --root <capture root>` (debug inventory). Task 9 (mutation) and Task 16 (gate) call `run_parity` / the CLI verbatim.

- [ ] **Step 1: Write the failing test**

Create `harness/tests/test_parity_cli.py`:

```python
"""End-to-end gate plumbing on synthetic manifested trees."""

import pytest

from harness.manifest import ManifestMissingError
from harness.parity import run_parity
from harness.tests.synthtree import attach_manifest, build_tree


def make_golden(base, name, seed):
    gdir = base / name
    build_tree(gdir / "root", seed=seed)
    attach_manifest(gdir)
    return gdir


def test_identical_runs_pass(tmp_path):
    a = make_golden(tmp_path, "runA", seed=0)
    b = make_golden(tmp_path, "runB", seed=100)
    report = run_parity(a, b)
    assert report["status"] == "pass"
    assert report["n_diffs"] == 0
    assert len(report["run_id"]) == 12


def test_candidate_may_be_a_raw_root(tmp_path):
    a = make_golden(tmp_path, "runA", seed=0)
    raw = tmp_path / "rawroot"
    build_tree(raw, seed=100)
    assert run_parity(a, raw)["status"] == "pass"


def test_manifestless_golden_hard_fails(tmp_path):
    gdir = tmp_path / "nomanifest"
    build_tree(gdir / "root", seed=0)
    b = make_golden(tmp_path, "runB", seed=100)
    with pytest.raises(ManifestMissingError):
        run_parity(gdir, b)


def test_content_diff_fails_gate(tmp_path):
    a = make_golden(tmp_path, "runA", seed=0)
    b = make_golden(tmp_path, "runB", seed=100)
    act = next((b / "root").rglob("*-act.yml"))
    act.write_text(act.read_text().replace("duration: 2.0", "duration: 9.0"))
    report = run_parity(a, b)
    assert report["status"] == "fail"
    assert report["n_diffs"] >= 1


def test_report_file_is_written(tmp_path):
    a = make_golden(tmp_path, "runA", seed=0)
    b = make_golden(tmp_path, "runB", seed=100)
    out = tmp_path / "report.json"
    run_parity(a, b, report_path=out)
    assert out.exists()
    import json

    loaded = json.loads(out.read_text())
    assert loaded["status"] == "pass"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
conda run -n helao python -m pytest harness/tests/test_parity_cli.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'harness.parity'`.

- [ ] **Step 3: Write the implementation**

Create `harness/parity.py`:

```python
"""THE parity gate (spec §6.5): python -m harness.parity --golden X --candidate Y.

Golden-set layout: <set>/provenance.yml + <set>/root/{RUNS_*,PROCESSES,S3_SIM}.
The candidate may be another golden set or a bare capture root. Any
unnormalized difference fails; phase gates cite the printed run_id.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from harness import HARNESS_VERSION
from harness.classify import ArtifactRow
from harness.hlo_pass import diff_hlo
from harness.manifest import ManifestMissingError, ProvenanceManifest
from harness.s3_pass import diff_s3_record, internal_s3_checks
from harness.treepass import (
    diff_member_sets,
    explode_zips,
    seed_mapper,
    snapshot,
)
from harness.uuidmap import UuidMapper
from harness.yaml_pass import (
    diff_meta,
    diff_prg,
    load_yml_plain,
    normalize_meta,
)

import fnmatch


def _content_mask_mode(norm: str, manifest: ProvenanceManifest) -> Optional[str]:
    for pattern, mode in (manifest.content_masked_files or {}).items():
        if fnmatch.fnmatch(norm, pattern):
            return mode
    return None


def _diff_aux(norm, gpath, cpath, manifest):
    mode = _content_mask_mode(norm, manifest)
    if mode == "skip":
        return []
    if mode == "line-count":
        g_n = len(Path(gpath).read_bytes().splitlines())
        c_n = len(Path(cpath).read_bytes().splitlines())
        if g_n != c_n:
            return [{"key": "line_count", "golden": g_n, "candidate": c_n}]
        return []
    if Path(gpath).read_bytes() != Path(cpath).read_bytes():
        return [{"key": "<bytes>", "golden": "differs", "candidate": "differs"}]
    return []


def _diff_lines_sorted(gpath, cpath, mg, mc):
    g = sorted(mg.sub(x) for x in Path(gpath).read_text().splitlines())
    c = sorted(mc.sub(x) for x in Path(cpath).read_text().splitlines())
    if g != c:
        return [{"key": "manifest_lines", "golden": g, "candidate": c}]
    return []


YAML_ROWS = (
    ArtifactRow.SEQ_YML,
    ArtifactRow.EXP_YML,
    ArtifactRow.ACT_YML,
    ArtifactRow.PRC_YML,
    ArtifactRow.ANALYSIS,
)


def compare_file(row, norm, gpath, cpath, mg, mc, manifest):
    if row in YAML_ROWS:
        g = normalize_meta(load_yml_plain(gpath), mg)
        c = normalize_meta(load_yml_plain(cpath), mc)
        return diff_meta(g, c)
    if row is ArtifactRow.PRG:
        return diff_prg(load_yml_plain(gpath), load_yml_plain(cpath))
    if row is ArtifactRow.HLO:
        return diff_hlo(gpath, cpath, norm, mg, mc, manifest)
    if row is ArtifactRow.PARQUET:
        from helao.helpers.hlo_data import read_helao_metadata

        return diff_meta(
            normalize_meta(read_helao_metadata(str(gpath)), mg),
            normalize_meta(read_helao_metadata(str(cpath)), mc),
            "helao_metadata",
        )
    if row is ArtifactRow.S3_RECORD:
        return diff_s3_record(norm, gpath, cpath, mg, mc, manifest)
    if row is ArtifactRow.MICRO_MANIFEST:
        return _diff_lines_sorted(gpath, cpath, mg, mc)
    return _diff_aux(norm, gpath, cpath, manifest)  # AUX_FILE and anything new


def _resolve_root(path: Path) -> Path:
    return path / "root" if (path / "root").is_dir() else path


def run_parity(
    golden_set: Path,
    candidate: Path,
    report_path: Optional[Path] = None,
) -> dict:
    golden_set, candidate = Path(golden_set), Path(candidate)
    manifest = ProvenanceManifest.load(golden_set)  # hard-fails when missing (F1)
    golden_root = golden_set / "root"
    cand_root = _resolve_root(candidate)
    run_id = uuid.uuid4().hex[:12]
    with tempfile.TemporaryDirectory(prefix="parity_") as td:
        g_ex = explode_zips(golden_root, Path(td) / "g")
        c_ex = explode_zips(cand_root, Path(td) / "c")
        mg, mc = UuidMapper(), UuidMapper()
        seed_mapper(g_ex, mg)
        seed_mapper(c_ex, mc)
        g_snap = snapshot(g_ex, mg)
        c_snap = snapshot(c_ex, mc)
        tree_diffs = diff_member_sets(g_snap, c_snap)
        file_diffs = {}
        for norm in sorted(set(g_snap.files) & set(c_snap.files)):
            gpath, row = g_snap.files[norm]
            cpath, _ = c_snap.files[norm]
            fdiffs = compare_file(row, norm, gpath, cpath, mg, mc, manifest)
            if fdiffs:
                file_diffs[norm] = fdiffs
        consistency = internal_s3_checks(g_ex) + internal_s3_checks(c_ex)
    n_diffs = (
        len(tree_diffs)
        + sum(len(v) for v in file_diffs.values())
        + len(consistency)
    )
    report = {
        "run_id": run_id,
        "harness_version": HARNESS_VERSION,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "scenario": manifest.scenario,
        "golden": str(golden_set),
        "candidate": str(candidate),
        "status": "pass" if n_diffs == 0 else "fail",
        "n_diffs": n_diffs,
        "tree_diffs": tree_diffs,
        "file_diffs": file_diffs,
        "consistency_diffs": consistency,
    }
    if report_path is not None:
        Path(report_path).write_text(json.dumps(report, indent=2, default=str))
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m harness.parity", description=__doc__
    )
    parser.add_argument("--golden", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        report = run_parity(args.golden, args.candidate, args.report)
    except ManifestMissingError as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    print(
        f"parity run {report['run_id']}: {report['status'].upper()} "
        f"({report['n_diffs']} diffs) scenario={report['scenario']}"
    )
    if report["status"] != "pass" and args.report is None:
        print(json.dumps(report, indent=2, default=str))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
```

Create `harness/normalize.py`:

```python
"""Normalizer façade (spec §6.4 names this module) + debug inventory CLI.

Re-exports every pass so callers can `from harness.normalize import ...`;
the implementation lives in focused modules (classify/uuidmap/yaml_pass/
treepass/hlo_pass/s3_pass).

CLI: python -m harness.normalize --root <capture root>
prints each parity file's normalized path, artifact row, and (for yml rows)
a sha256 of its normalized content — the debugging view of exactly what the
gate compares.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

from harness.classify import (  # noqa: F401  (façade re-exports)
    ArtifactRow,
    classify_file,
    normalize_name,
    normalize_relpath,
)
from harness.hlo_pass import (  # noqa: F401
    diff_hlo,
    diff_hlo_body,
    masked_columns_for,
    normalize_hlo_header,
    row_tolerance_for,
)
from harness.s3_pass import (  # noqa: F401
    assert_s3_meta_rules,
    diff_s3_manifest,
    diff_s3_record,
    internal_s3_checks,
)
from harness.treepass import (  # noqa: F401
    PARITY_TOPS,
    TreeSnapshot,
    diff_member_sets,
    explode_zips,
    seed_mapper,
    snapshot,
)
from harness.uuidmap import RE_UUID, UuidMapper  # noqa: F401
from harness.yaml_pass import (  # noqa: F401
    canonicalize,
    diff_meta,
    diff_prg,
    load_yml_plain,
    normalize_meta,
    to_plain,
)

YAML_ROWS = (
    ArtifactRow.SEQ_YML,
    ArtifactRow.EXP_YML,
    ArtifactRow.ACT_YML,
    ArtifactRow.PRC_YML,
    ArtifactRow.ANALYSIS,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m harness.normalize")
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="normalize_") as td:
        exploded = explode_zips(args.root, Path(td))
        mapper = UuidMapper()
        seed_mapper(exploded, mapper)
        snap = snapshot(exploded, mapper)
        for norm in sorted(snap.files):
            path, row = snap.files[norm]
            line = {"path": norm, "row": row.name}
            if row in YAML_ROWS:
                normalized = normalize_meta(load_yml_plain(path), mapper)
                digest = hashlib.sha256(
                    json.dumps(normalized, sort_keys=True, default=str).encode()
                ).hexdigest()[:16]
                line["normalized_sha256"] = digest
            print(json.dumps(line))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
conda run -n helao python -m pytest harness/tests/test_parity_cli.py -v
```

Expected: `5 passed`.

- [ ] **Step 5: Exercise both CLIs once by hand (plumbing check)**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
conda run -n helao python - <<'EOF'
from pathlib import Path
import tempfile
from harness.tests.synthtree import build_tree, attach_manifest
base = Path(tempfile.mkdtemp())
build_tree(base / "runA" / "root", seed=0); attach_manifest(base / "runA")
build_tree(base / "runB" / "root", seed=9); attach_manifest(base / "runB")
print(base)
EOF
# use the printed path:
conda run -n helao python -m harness.normalize --root <printed>/runA/root
conda run -n helao python -m harness.parity --golden <printed>/runA --candidate <printed>/runB
echo "exit code: $?"
```

Expected: the normalize CLI prints one JSON line per parity file; the parity CLI prints `parity run <12-hex>: PASS (0 diffs) scenario=SYNTH`; exit code 0.

- [ ] **Step 6: Format and commit**

```bash
conda run -n helao black harness
git add harness/parity.py harness/normalize.py harness/tests/test_parity_cli.py
git commit -m "feat(harness): parity gate CLI with run IDs + normalizer facade/inventory CLI"
```

---

### Task 9: Mutation self-test — a perturbed tree MUST fail

**Files:**
- Create: `harness/mutate.py`
- Test: `harness/tests/test_mutations.py`

**Interfaces:**
- Consumes: `run_parity` (Task 8); `explode_zips` (Task 5); synthtree helpers (Task 5).
- Produces: `MUTATIONS: dict[str, Callable[[Path], str]]` with keys `"param_value"`, `"drop_file"`, `"add_hlo_column"`, `"break_uuid_link"`; `run_self_test(golden_set: Path, workdir: Path) -> dict` (returns `{"sanity_pass": bool, "caught": {name: bool}, "ok": bool}`); CLI `python -m harness.mutate --golden <set> --workdir <dir>` exiting 0 only when the unmutated copy passes AND every mutation fails parity. Task 16 runs this CLI as a gate criterion.

- [ ] **Step 1: Write the failing test**

Create `harness/tests/test_mutations.py`:

```python
"""Over-normalization guard: every mutation class must be CAUGHT by the gate."""

from harness.mutate import MUTATIONS, run_self_test
from harness.tests.synthtree import attach_manifest, build_tree


def test_all_mutations_are_caught(tmp_path):
    gdir = tmp_path / "golden"
    build_tree(gdir / "root", seed=0)
    attach_manifest(gdir)
    result = run_self_test(gdir, tmp_path / "work")
    assert result["sanity_pass"] is True
    assert set(result["caught"]) == set(MUTATIONS)
    assert all(result["caught"].values()), result
    assert result["ok"] is True
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
conda run -n helao python -m pytest harness/tests/test_mutations.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'harness.mutate'`.

- [ ] **Step 3: Write the implementation**

Create `harness/mutate.py`:

```python
"""Mutation self-test (spec §6.1 determinism gate + §12 P0 gate line 3).

The harness must FAIL when fed a deliberately perturbed tree — this is the
guard against over-normalization silently recreating failure mode F1. Each
mutation is applied to a fresh EXPLODED copy of the golden root (zips are
expanded first so mutations can reach members inside RUNS_SYNCED sequence
zips; an exploded tree is itself a valid parity candidate because
explode_zips is idempotent over zip-less trees).

Exit contract: 0 only when the UNMUTATED exploded copy passes parity
against the golden (sanity) AND every mutation makes parity fail.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import uuid
from pathlib import Path
from typing import Callable, Dict

from harness.parity import run_parity
from harness.treepass import explode_zips


def mutate_param_value(root: Path) -> str:
    """Append a key to an -act.yml: action_params are bit-exact (D7)."""
    act = sorted(root.rglob("*-act.yml"))[0]
    act.write_text(act.read_text() + "mutation_marker: 1\n")
    return f"appended top-level key to {act.name}"


def mutate_drop_file(root: Path) -> str:
    hlos = sorted(root.rglob("*.hlo"))
    target = hlos[0] if hlos else sorted(p for p in root.rglob("*") if p.is_file())[0]
    target.unlink()
    return f"deleted {target.name}"


def mutate_add_hlo_column(root: Path) -> str:
    hlo = sorted(root.rglob("*.hlo"))[0]
    with open(hlo, "a") as f:
        f.write('{"mutated_col": 1}\n')
    return f"appended a row with a new column to {hlo.name}"


def mutate_break_uuid_link(root: Path) -> str:
    """Rewire ONE file's experiment_uuid: the ordinal mapping must notice."""
    act = sorted(root.rglob("*-act.yml"))[0]
    text = act.read_text()
    m = re.search(r"experiment_uuid: ([0-9a-fA-F-]{36})", text)
    if m is None:
        raise RuntimeError(f"no experiment_uuid found in {act}")
    replacement = str(uuid.uuid4())
    act.write_text(text.replace(m.group(1), replacement, 1))
    return f"rewired experiment_uuid in {act.name}"


MUTATIONS: Dict[str, Callable[[Path], str]] = {
    "param_value": mutate_param_value,
    "drop_file": mutate_drop_file,
    "add_hlo_column": mutate_add_hlo_column,
    "break_uuid_link": mutate_break_uuid_link,
}


def run_self_test(golden_set: Path, workdir: Path) -> dict:
    golden_set, workdir = Path(golden_set), Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    baseline = explode_zips(golden_set / "root", workdir / "baseline")
    sanity = run_parity(golden_set, baseline)
    caught: Dict[str, bool] = {}
    for name, fn in MUTATIONS.items():
        mut_root = workdir / name
        shutil.copytree(baseline, mut_root)
        desc = fn(mut_root)
        report = run_parity(golden_set, mut_root)
        caught[name] = report["status"] == "fail"
        print(f"mutation {name}: {desc} -> {report['status']}")
    result = {
        "sanity_pass": sanity["status"] == "pass",
        "caught": caught,
        "ok": sanity["status"] == "pass" and all(caught.values()),
    }
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m harness.mutate")
    parser.add_argument("--golden", required=True, type=Path)
    parser.add_argument("--workdir", required=True, type=Path)
    args = parser.parse_args(argv)
    result = run_self_test(args.golden, args.workdir)
    print(result)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
conda run -n helao python -m pytest harness/tests/test_mutations.py -v
```

Expected: `1 passed` (the test output also shows the four `mutation <name>: ... -> fail` lines).

- [ ] **Step 5: Run the whole harness suite so far**

```bash
conda run -n helao python -m pytest harness/tests -q
```

Expected: all tests pass, 0 failures.

- [ ] **Step 6: Format and commit**

```bash
conda run -n helao black harness
git add harness/mutate.py harness/tests/test_mutations.py
git commit -m "feat(harness): mutation self-test guarding against over-normalization"
```

---

### Task 10: Capture configs — `golden.yml` and `goldenlocal.yml`

**Files:**
- Create: `helao/deploy/test/configs/golden.yml`
- Create: `helao/deploy/test/configs/goldenlocal.yml`

**Interfaces:**
- Consumes: existing `helao/deploy/test/configs/test.yml` (copied and modified); the `sim_db_server` module name that Task 11 creates (`fast: sim_db_server`, server key `DB`).
- Produces: launchable config prefixes `golden` (recording sim DB) and `goldenlocal` (local-only sim DB, for Q3) used by Tasks 11–13 and 16. Capture roots: `/home/dan/INST_hlo_golden` and `/home/dan/INST_hlo_goldenlocal`.

Notes for the implementer (spec §6.2 step 1):
- These are copies of `test.yml` with (a) a Linux `root:` replacing `C:/INST_hlo`, (b) `launch_browser: true` removed from DATABROWSE (headless capture), (c) a `DB` server entry added — the literal key `DB` is what gates `HelaoSyncer` instantiation in the orchestrator (`helao/core/servers/orch.py:117-119`) and is the target of `move_dir`'s `/finish_yml` handoff (`helao/helpers/yml_tools.py:270`, `base.world_cfg["servers"]["DB"]`).
- Cross-deployment resolution is BY DESIGN: `async_orch2`, `standalone_operator`, `live_visualizer` live under `helao/deploy/hte/servers/...`; the launchers glob every deployment for the named module (`fast_launcher.py` / `bokeh_launcher.py` "generic app reused across deployments" fallback), so a `test` config launch pulls the production orchestrator/operator/visualizer code. Golden runs therefore exercise production orch code — intended (§6.2 step 1).
- Keeping the configs in-tree preserves launcher deployment auto-detection (config path → `test` deployment).
- `aws_bucket` must be set (the `SyncDriver` constructor reads `self.config_dict["aws_bucket"]` unconditionally — `sync_driver.py:728`); NO `aws_config_path` is set, so the boto3 session stays `None` and no AWS credentials are ever touched.
- The orchestrator also instantiates its own plain `HelaoSyncer` from the `DB` params (it ignores the extra `s3_record` key and stays local-only). Only the DB server's syncer receives `/finish_yml` handoffs; observed division of labor is identical across baseline runs, which is what the gate measures.

- [ ] **Step 1: Write `helao/deploy/test/configs/golden.yml`**

```yaml
dummy: true
simulation: true
show_debug: true
run_unit_tests: true
experiment_libraries:
  - simulatews_exp
  - helao/deploy/test/experiments/TEST_exp.py
sequence_libraries:
  - helao/deploy/test/sequences/TEST_seq.py
run_type: simulation
root: /home/dan/INST_hlo_golden
servers:
  ORCH:
    host: 127.0.0.1
    port: 8001
    group: orchestrator
    fast: async_orch2
    params: {}
    exp_postprocess_libs:
      - append_params
    seq_postprocess_libs:
      - append_params
  OPERATOR:
    group: operator
    bokeh: standalone_operator
    host: 127.0.0.1
    port: 5001
    params:
      orch_key: ORCH
      doc_name: "Operator (golden capture)"
      poll_interval: 5
  SIM:
    host: 127.0.0.1
    port: 8002
    group: action
    fast: ws_simulator
    live_vis: wssim_live_vis
    params: {}
    hlo_postprocess_libs:
      - hlo_to_csv
  LIVE:
    host: 127.0.0.1
    port: 5002
    group: visualizer
    bokeh: live_visualizer
    params:
      doc_name: Websocket Live Visualizer
  DATABROWSE:
    host: 127.0.0.1
    port: 5003
    group: visualizer
    bokeh: data_browser
    params:
      doc_name: Data Browser
      max_points: 50000
  DB:
    host: 127.0.0.1
    port: 8010
    group: action
    fast: sim_db_server
    params:
      aws_bucket: helao-sim
      s3_record: true
```

- [ ] **Step 2: Write `helao/deploy/test/configs/goldenlocal.yml`**

Identical except the root, the doc name, and `s3_record` absent (local-only mode — Q3):

```yaml
dummy: true
simulation: true
show_debug: true
run_unit_tests: true
experiment_libraries:
  - simulatews_exp
  - helao/deploy/test/experiments/TEST_exp.py
sequence_libraries:
  - helao/deploy/test/sequences/TEST_seq.py
run_type: simulation
root: /home/dan/INST_hlo_goldenlocal
servers:
  ORCH:
    host: 127.0.0.1
    port: 8001
    group: orchestrator
    fast: async_orch2
    params: {}
    exp_postprocess_libs:
      - append_params
    seq_postprocess_libs:
      - append_params
  OPERATOR:
    group: operator
    bokeh: standalone_operator
    host: 127.0.0.1
    port: 5001
    params:
      orch_key: ORCH
      doc_name: "Operator (goldenlocal capture)"
      poll_interval: 5
  SIM:
    host: 127.0.0.1
    port: 8002
    group: action
    fast: ws_simulator
    live_vis: wssim_live_vis
    params: {}
    hlo_postprocess_libs:
      - hlo_to_csv
  LIVE:
    host: 127.0.0.1
    port: 5002
    group: visualizer
    bokeh: live_visualizer
    params:
      doc_name: Websocket Live Visualizer
  DATABROWSE:
    host: 127.0.0.1
    port: 5003
    group: visualizer
    bokeh: data_browser
    params:
      doc_name: Data Browser
      max_points: 50000
  DB:
    host: 127.0.0.1
    port: 8010
    group: action
    fast: sim_db_server
    params:
      aws_bucket: helao-sim
```

- [ ] **Step 3: Verify the configs resolve and validate (no launch yet — Task 11 creates `sim_db_server`)**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
conda run -n helao python - <<'EOF'
from helao.helpers.config_loader import read_config
for prefix in ("golden", "goldenlocal"):
    cfg = read_config(prefix)
    assert cfg["root"].startswith("/home/dan/INST_hlo_golden"), cfg["root"]
    assert "DB" in cfg["servers"], "DB server entry missing"
    assert cfg["servers"]["DB"]["fast"] == "sim_db_server"
    assert cfg["servers"]["DB"]["params"]["aws_bucket"] == "helao-sim"
    ports = [(s["host"], s["port"]) for s in cfg["servers"].values()]
    assert len(ports) == len(set(ports)), "host:port collision"
    print(prefix, "OK:", sorted(cfg["servers"]))
EOF
```

Expected:
```
golden OK: ['DATABROWSE', 'DB', 'LIVE', 'OPERATOR', 'ORCH', 'SIM']
goldenlocal OK: ['DATABROWSE', 'DB', 'LIVE', 'OPERATOR', 'ORCH', 'SIM']
```

- [ ] **Step 4: Commit**

```bash
git add helao/deploy/test/configs/golden.yml helao/deploy/test/configs/goldenlocal.yml
git commit -m "feat(test): golden capture configs with sim DB server entry (recording + local-only)"
```

---

### Task 11: Sim DB/sync server (`sim_db_server`, key `DB`)

**Files:**
- Create: `helao/deploy/test/servers/action/sim_db_server.py`
- Test: `harness/tests/test_sim_db_server.py`

**Interfaces:**
- Consumes: legacy `helao.core.servers.base_api.BaseAPI` (constructor kwargs `server_key, server_title, description, version, driver_classes`; non-`HelaoDriver` classes are instantiated as `driver_class(self.base)` — `base_api.py:656-671`) and `helao.core.drivers.data.sync_driver.HelaoSyncer` (`__init__(self, action_serv: Base, db_server_name: str = "DB")`; attributes used by endpoints: `enqueue_yml(upath, rank)`, `list_pending()`, `finish_pending(actions_first=True)`, `reset_sync(path)`, `running_tasks`, `task_queue`, `progress`); config params from Task 10.
- Produces: `makeApp(server_key) -> BaseAPI` exposing the full dbpack HTTP surface (`/finish_yml`, `/list_pending`, `/finish_pending`, `/reset_sync`, `/tasks`, `/list_exceptions`, `/n_queue`, `/current_progress` — mirrored verbatim from `helao/deploy/hte/servers/action/dbpack_server.py` so `move_dir`'s `yml_finisher` handoff and the harness quiesce polls work unmodified); classes `RecordingS3Client(sim_root: Path)` (duck-typed boto3 surface: `upload_fileobj(fileobj, bucket, key, **kw)`, `upload_file(filename, bucket, key, **kw)`, writes `<root>/S3_SIM/<bucket>/<key>` + appends `{"bucket","key","mode","gzip"}` lines to `<root>/S3_SIM/manifest.jsonl`, thread-safe) and `SimHelaoSyncer(HelaoSyncer)` (injects the recorder when `params.s3_record` is truthy). **No legacy seam is required** (see Global Constraints); if review ever DOES demand a constructor-level override instead of the subclass, the minimal legacy diff is `SyncDriver.__init__(self, config, helaodirs, s3_client=None)` + `self.s3 = s3_client if s3_client is not None else …` with default `None` preserving current behavior — record that as a follow-up, do not apply it in P0.

- [ ] **Step 1: Write the failing test**

Create `harness/tests/test_sim_db_server.py`:

```python
"""RecordingS3Client contract + sim_db_server import sanity (Linux, no AWS)."""

import io
import json
from pathlib import Path


def test_recording_client_upload_fileobj(tmp_path):
    from helao.deploy.test.servers.action.sim_db_server import RecordingS3Client

    rec = RecordingS3Client(tmp_path / "S3_SIM")
    rec.upload_fileobj(io.BytesIO(b'{"a": 1}'), "helao-sim", "action/u1.json")
    stored = tmp_path / "S3_SIM" / "helao-sim" / "action" / "u1.json"
    assert stored.read_bytes() == b'{"a": 1}'
    entries = [
        json.loads(x)
        for x in (tmp_path / "S3_SIM" / "manifest.jsonl").read_text().splitlines()
    ]
    assert entries == [
        {"bucket": "helao-sim", "key": "action/u1.json", "mode": "fileobj", "gzip": False}
    ]


def test_recording_client_upload_file_and_gzip_flag(tmp_path):
    from helao.deploy.test.servers.action.sim_db_server import RecordingS3Client

    src = tmp_path / "payload.hlo"
    src.write_text("data")
    rec = RecordingS3Client(tmp_path / "S3_SIM")
    rec.upload_file(str(src), "helao-sim", "raw_data/u1/payload.hlo.json.gz")
    stored = tmp_path / "S3_SIM" / "helao-sim" / "raw_data" / "u1" / "payload.hlo.json.gz"
    assert stored.read_text() == "data"
    entry = json.loads(
        (tmp_path / "S3_SIM" / "manifest.jsonl").read_text().splitlines()[0]
    )
    assert entry["mode"] == "file" and entry["gzip"] is True


def test_module_imports_and_exposes_makeapp():
    import helao.deploy.test.servers.action.sim_db_server as mod

    assert callable(mod.makeApp)
    assert issubclass(mod.SimHelaoSyncer, object)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
conda run -n helao python -m pytest harness/tests/test_sim_db_server.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'helao.deploy.test.servers.action.sim_db_server'`.

- [ ] **Step 3: Write the implementation**

Create `helao/deploy/test/servers/action/sim_db_server.py`:

```python
"""Simulated data-packaging server for golden-master capture (spec §6.3, D5).

Hosts the REAL :class:`HelaoSyncer` with ``aws_bucket`` set and no
``aws_config_path``, so the full RUNS_FINISHED -> RUNS_SYNCED -> S3 sync leg
runs on Linux without AWS credentials. Two modes, selected by the server's
``params``:

- local-only (default): ``SyncDriver.to_s3`` returns True with ``self.s3``
  unset — sync completes locally (Q3 verification target).
- recording (``s3_record: true``): a duck-typed S3 client records every
  upload to ``<root>/S3_SIM/<bucket>/<key>`` and logs a manifest line, so
  the harness diffs S3 key templates + payload shapes (§5.6). The same
  recorder object later serves the hexagon syncer, recording both stacks
  identically.

No legacy patch is needed: ``SyncDriver`` leaves ``self.s3 = None`` without
``aws_config_path``, only calls ``self.s3.upload_fileobj(fileobj, bucket,
key)`` / ``self.s3.upload_file(filename, bucket, key)`` from a worker thread
(``asyncio.to_thread`` — sync_driver.py:1776), and never uses ``self.s3r``
beyond assignment, so post-construction injection is sufficient and
behavior-identical when ``s3_record`` is unset.

Endpoint surface mirrors the hte dbpack_server verbatim so ``move_dir``'s
``/finish_yml`` handoff and the harness quiesce polls (``/n_queue`` +
``/tasks``) work unmodified. Windows-tolerant (pathlib only) so at-station
captures (§6.6) can wire the same server.
"""

__all__ = ["makeApp"]

import json
import shutil
import threading
from pathlib import Path

from helao.core.servers.base_api import BaseAPI
from helao.core.drivers.data.sync_driver import HelaoSyncer


class RecordingS3Client:
    """Duck-typed stand-in for the boto3 S3 client surface SyncDriver uses.

    Both methods are called via ``asyncio.to_thread`` and must be
    thread-safe; a lock serializes manifest appends.
    """

    def __init__(self, sim_root: Path):
        self.sim_root = Path(sim_root)
        self.manifest_path = self.sim_root / "manifest.jsonl"
        self._lock = threading.Lock()
        self.sim_root.mkdir(parents=True, exist_ok=True)

    def _record(self, bucket: str, key: str, mode: str) -> None:
        entry = {
            "bucket": bucket,
            "key": key,
            "mode": mode,
            "gzip": key.endswith(".gz"),
        }
        with self._lock:
            with open(self.manifest_path, "a") as f:
                f.write(json.dumps(entry) + "\n")

    def upload_fileobj(self, fileobj, bucket: str, key: str, **kwargs) -> None:
        dest = self.sim_root / bucket / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            shutil.copyfileobj(fileobj, f)
        self._record(bucket, key, "fileobj")

    def upload_file(self, filename, bucket: str, key: str, **kwargs) -> None:
        dest = self.sim_root / bucket / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(str(filename), dest)
        self._record(bucket, key, "file")


class SimHelaoSyncer(HelaoSyncer):
    """HelaoSyncer that swaps in the recorder when ``params.s3_record`` is set."""

    def __init__(self, action_serv):
        super().__init__(action_serv)
        if self.config_dict.get("s3_record", False):
            sim_root = Path(action_serv.helaodirs.root) / "S3_SIM"
            self.s3 = RecordingS3Client(sim_root)


def makeApp(server_key) -> BaseAPI:
    """Build the sim data-packaging FastAPI app (dbpack surface, sim syncer)."""

    app = BaseAPI(
        server_key=server_key,
        server_title=server_key,
        description="Simulated data packaging server (golden capture)",
        version=0.1,
        driver_classes=[SimHelaoSyncer],
    )

    @app.post("/finish_yml", tags=["private"])
    async def finish_yml(yml_path: str) -> str:
        """Enqueue a finished YAML for sync (rank by -seq/-exp/-act suffix)."""
        clean_path = yml_path.strip('"').strip("'")
        if clean_path.endswith("-seq.yml"):
            rank = 2
        elif clean_path.endswith("-exp.yml"):
            rank = 1
        elif clean_path.endswith("-act.yml"):
            rank = 0
        else:
            rank = -1
        await app.driver.enqueue_yml(clean_path, rank)
        return yml_path

    @app.post("/list_pending", tags=["private"])
    def list_pending():
        """List sequence YAML files in RUNS_FINISHED awaiting sync."""
        return app.driver.list_pending()

    @app.post("/finish_pending", tags=["private"])
    async def finish_pending(actions_first: bool = True):
        """Discover RUNS_FINISHED YAML files and enqueue them for sync."""
        return await app.driver.finish_pending(actions_first=actions_first)

    @app.post("/reset_sync", tags=["private"])
    def reset_sync(sync_path: str) -> str:
        """Reset a synced sequence zip or partially-synced folder for re-sync."""
        app.driver.reset_sync(sync_path.strip('"').strip("'"))
        return sync_path

    @app.post("/tasks", tags=["private"])
    async def running() -> dict:
        """Return identifiers of running sync tasks and the queued count."""
        return {
            "running": list(app.driver.running_tasks.keys()),
            "num_queued": (app.driver.task_queue.qsize()),
        }

    @app.post("/list_exceptions", tags=["private"])
    async def list_exceptions() -> dict:
        """Return exceptions captured on currently running sync tasks."""
        return {k: d.exception() for k, d in app.driver.running_tasks.items()}

    @app.post("/n_queue", tags=["private"])
    async def n_queue() -> int:
        """Return the number of items waiting in the sync task queue."""
        return app.driver.task_queue.qsize()

    @app.post("/current_progress", tags=["private"])
    async def current_progress():
        """Return the syncer's progress dictionary."""
        return app.driver.progress

    return app
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
conda run -n helao python -m pytest harness/tests/test_sim_db_server.py -v
```

Expected: `3 passed`.

- [ ] **Step 5: Smoke-launch the golden group once (first live check of config + server)**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
rm -rf /home/dan/INST_hlo_golden
conda run -n helao python launch.py golden --no-hot-reload
```

Expected: the unit-test preflight passes, all 6 servers launch (watch for `DB` on port 8010 with no tracebacks; the syncer logs `creating syncer tasks`). In a second terminal verify the quiesce endpoints:

```bash
curl -s -X POST http://127.0.0.1:8010/n_queue        # expect: 0
curl -s -X POST http://127.0.0.1:8010/tasks          # expect: {"running":[],"num_queued":0}
```

Then CTRL-x in the launch terminal to shut the group down.

- [ ] **Step 6: Format and commit**

```bash
conda run -n helao black helao/deploy/test/servers/action/sim_db_server.py harness/tests/test_sim_db_server.py
git add helao/deploy/test/servers/action/sim_db_server.py harness/tests/test_sim_db_server.py
git commit -m "feat(test): sim DB/sync server hosting real HelaoSyncer with recording S3 sink"
```

---

### Task 12: Q3 verification — does local-only sync complete the RUNS_SYNCED move?

**Files:**
- Create: `harness/docs/q3-local-only-sync.md`

**Interfaces:**
- Consumes: `goldenlocal` config (Task 10), `sim_db_server` (Task 11), the GM-1 submission snippet below (self-contained; Task 13 later wraps the same pattern in `harness/capture.py`).
- Produces: a written verdict on spec Open Question Q3 that Task 16 cites. If the verdict is NO (local-only sync stalls before RUNS_SYNCED), the documented fallback applies: recorder mode (`golden.yml`) becomes the only capture config and `goldenlocal.yml` is marked non-viable in this doc — the gate then runs entirely on recorder mode, which is a superset.

- [ ] **Step 1: Launch the local-only group on a fresh root**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
rm -rf /home/dan/INST_hlo_goldenlocal
conda run -n helao python launch.py goldenlocal --no-hot-reload
```

Expected: all 6 servers up (as in Task 11 Step 5).

- [ ] **Step 2: Submit one GM-1-shaped sequence and wait for quiesce (second terminal)**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
conda run -n helao python - <<'EOF'
import time
import requests
from helao.core.error import ErrorCodes
from helao.helpers.dispatcher import private_dispatcher
from helao.helpers.premodels import ExperimentPlanMaker, Sequence
from helao.helpers.time_utils import gen_uuid

epm = ExperimentPlanMaker()
epm.add("SIM_websocket_data", {"wait_time": 2.0, "data_duration": 4.0})
seq = Sequence(
    sequence_name="SIM_websocket_data_seq",
    sequence_label="q3check",
    sequence_params={"wait_time": 2.0, "data_duration": 4.0},
    planned_experiments=epm.planned_experiments,
    sequence_uuid=gen_uuid(),
    dummy=True,
    simulation=True,
)
resp, err = private_dispatcher("ORCH", "127.0.0.1", 8001, "append_sequence",
                               params_dict={}, json_dict={"sequence": seq.as_dict()})
assert err == ErrorCodes.none, err
resp, err = private_dispatcher("ORCH", "127.0.0.1", 8001, "start",
                               params_dict={}, json_dict={})
assert err == ErrorCodes.none, err
print("submitted; polling for quiesce...")
for _ in range(300):
    gs = requests.post("http://127.0.0.1:8001/global_status", timeout=10).json()
    n = requests.post("http://127.0.0.1:8010/n_queue", timeout=10).json()
    tasks = requests.post("http://127.0.0.1:8010/tasks", timeout=10).json()
    stopped = str(gs.get("loop_state")).endswith("stopped") and not gs.get("active_dict")
    if stopped and n == 0 and not tasks.get("running"):
        print("quiesced")
        break
    time.sleep(2)
EOF
```

Expected: `submitted; polling for quiesce...` then `quiesced` within a few minutes.

- [ ] **Step 3: Inspect the tree and record the verdict**

```bash
find /home/dan/INST_hlo_goldenlocal/RUNS_SYNCED -name '*.zip'
find /home/dan/INST_hlo_goldenlocal/RUNS_FINISHED -name '*.yml'
find /home/dan/INST_hlo_goldenlocal/PROCESSES -name '*-prc.yml'
curl -s -X POST http://127.0.0.1:8010/list_exceptions
```

Interpretation:
- **YES (Q3 resolved positive):** a sequence `.zip` exists under `RUNS_SYNCED/<YY.WW>/<MMDD>/`, `RUNS_FINISHED` retains no `.yml` for the run, two `-prc.yml` files exist under `PROCESSES`, and `/list_exceptions` returns `{}`.
- **NO:** ymls remain stranded in `RUNS_FINISHED` or exceptions are reported — record exactly what stalled.

Shut down with CTRL-x afterwards.

- [ ] **Step 4: Write `harness/docs/q3-local-only-sync.md`**

```markdown
# Q3 verification — local-only sync completion (spec §14 Q3, §12 P0)

**Question:** does a no-S3, no-API `HelaoSyncer` (aws_bucket set, no
aws_config_path) complete the RUNS_FINISHED → RUNS_SYNCED move end-to-end,
including the destructive sequence zip?

**Procedure:** `goldenlocal` config (local-only sim DB server), one
`SIM_websocket_data_seq` run, quiesce via ORCH /global_status + DB
/n_queue + /tasks, then tree inspection (Task 12 steps 1–3).

**Run date:** <fill in>
**Legacy SHA:** <git rev-parse HEAD>
**Verdict:** <YES — RUNS_SYNCED zip present, RUNS_FINISHED emptied,
2 prc ymls, no exceptions | NO — details below>

**Evidence:**
- RUNS_SYNCED zip: <path found by the find command>
- RUNS_FINISHED residue: <empty | listing>
- PROCESSES: <the two -prc.yml paths>
- /list_exceptions: <output>

**Consequence:** <YES: both capture modes are viable; the gate uses
recording mode (golden.yml) for GM-1..GM-5 and this local-only result
stands as the Q3 record. | NO: goldenlocal.yml is non-viable; recorder
mode is the only capture path (spec §12 P0 fallback) and the master spec's
Q3 must be answered accordingly.>
```

Fill in every `<...>` with the observed values before committing.

- [ ] **Step 5: Commit**

```bash
git add harness/docs/q3-local-only-sync.md
git commit -m "docs(harness): Q3 verification record - local-only sync completion"
```

---

### Task 13: Capture rig — GM-1..GM-5 builders, quiesce, snapshot, manifest

**Files:**
- Create: `harness/capture.py`
- Test: `harness/tests/test_capture.py`

**Interfaces:**
- Consumes: `ProvenanceManifest`, `HARNESS_VERSION` (Task 1); `PARITY_TOPS` (Task 5); legacy `private_dispatcher(server_key, host, port, private_action, params_dict, json_dict)` → `(resp, ErrorCodes)`, `Sequence(sequence_name=…, sequence_label=…, sequence_params=…, planned_experiments=…, sequence_uuid=…, dummy=True, simulation=True)`, `ExperimentPlanMaker().add(experiment_name, experiment_params)`, `TEST_consecutive_noblocking(**params)` (a `@sequence` library function returning planned experiments — the `multi_orch_demo_helper.py` pattern), `gen_uuid()`; orch private endpoints `/append_sequence`, `/start`, `/stop`, `/skip_experiment`, `/estop_orch`, `/clear_estop`, `/global_status` and DB endpoints `/n_queue`, `/tasks`, `/reset_sync`, `/finish_pending` (all POST).
- Produces: CLI `python -m harness.capture --scenario {GM-1,GM-2,GM-3,GM-4,GM-5} --root <capture root> --out <golden set dir>` which (1) refuses a non-fresh root, (2) submits/drives the scenario, (3) quiesces per §5.7, (4) snapshots `PARITY_TOPS` into `<out>/root/` and writes `<out>/provenance.yml`. Library functions used by tests: `build_gm1_sequence()`, `build_gm2_sequence()`, `build_gm4_sequence(label)`, `SCENARIOS: dict`, `quiesce(...)`, `snapshot_capture(...)`. Task 16 runs this CLI twice per scenario.

Scenario map (spec §6.2):
- **GM-1 (primary):** two `SIM_websocket_data` experiments — streamed hlo per `acquire_data`, TWO `-prc.yml` per experiment (`process_contrib=[files, run_use]`, `process_finish=True` twice per experiment), `hlo_to_csv` postprocess csv (SIM's `hlo_postprocess_libs`), `append_params` seq/exp postprocessors (ORCH config), orch `wait` actions (no-data actions — no `.hlo`).
- **GM-2 (scheduling):** `TEST_consecutive_noblocking` — nonblocking waits, `wait_for_*` start conditions, cross-cycle `from_global_exp_params` handoff.
- **GM-3 (manual/diag):** one direct (non-orch) POST to `http://127.0.0.1:8002/SIM/acquire_data` — synthesized `seq--`/`exp--` parents, whole tree under RUNS_DIAG, never synced.
- **GM-4 (lifecycle edges):** three sequential legs on one launch: stop-intent drain + resume; `skip_experiment` truncation; `estop_orch` mid-experiment → `[finished, estopped]` artifacts + deferred promotion, then `clear_estop`. Long first waits (`wait_time=20.0`) make the 5 s-in control POSTs land deterministically inside action 0.
- **GM-5 (sync leg):** GM-1's sequence carried through the recording sim DB, then a `reset_sync` (zip → `.orig`, files back to FINISHED) + `finish_pending` round-trip, re-quiesce, snapshot — exercising `.prg` lifecycle, `-prc.yml`, RUNS_SYNCED zip member set, and the recorded S3 key/payload set twice over.

- [ ] **Step 1: Write the failing test** (pure parts only — no servers)

Create `harness/tests/test_capture.py`:

```python
"""Capture-rig pure parts: scenario builders + snapshot layout."""

from harness.capture import (
    SCENARIOS,
    build_gm1_sequence,
    build_gm2_sequence,
    build_gm4_sequence,
    snapshot_capture,
)


def test_gm1_sequence_shape():
    seq = build_gm1_sequence()
    assert seq.sequence_name == "SIM_websocket_data_seq"
    assert len(seq.planned_experiments) == 2
    d = seq.as_dict()
    assert d["planned_experiments"][0]["experiment_name"] == "SIM_websocket_data"
    assert d["planned_experiments"][0]["experiment_params"] == {
        "wait_time": 2.0,
        "data_duration": 4.0,
    }


def test_gm2_sequence_uses_library_function():
    seq = build_gm2_sequence()
    assert seq.sequence_name == "TEST_consecutive_noblocking"
    # 2 samples x 2 cycles = 4 experiments; cycles > 0 carry the global handoff
    assert len(seq.planned_experiments) == 4


def test_gm4_sequence_has_long_first_waits():
    seq = build_gm4_sequence("GM4_stop")
    d = seq.as_dict()
    assert all(
        e["experiment_params"]["wait_time"] == 20.0
        for e in d["planned_experiments"]
    )


def test_scenario_registry_is_complete():
    assert set(SCENARIOS) == {"GM-1", "GM-2", "GM-3", "GM-4", "GM-5"}


def test_snapshot_capture_layout_and_freshness(tmp_path):
    root = tmp_path / "captroot"
    (root / "RUNS_FINISHED" / "x").mkdir(parents=True)
    (root / "RUNS_FINISHED" / "x" / "a-seq.yml").write_text("file_type: sequence\n")
    (root / "LOGS").mkdir()
    (root / "LOGS" / "ORCH.log").write_text("not captured")
    out = tmp_path / "golden" / "run1"
    snapshot_capture(
        root=root,
        out_dir=out,
        scenario="GM-1",
        config_prefix="golden",
        sequence_name="SIM_websocket_data_seq",
        sequence_params={},
        masked_hlo={},
        tolerance={},
        content_masked={},
    )
    assert (out / "root" / "RUNS_FINISHED" / "x" / "a-seq.yml").exists()
    assert not (out / "root" / "LOGS").exists()  # non-parity tops excluded
    assert (out / "provenance.yml").exists()
    import pytest

    with pytest.raises(FileExistsError):
        snapshot_capture(
            root=root,
            out_dir=out,
            scenario="GM-1",
            config_prefix="golden",
            sequence_name="x",
            sequence_params={},
            masked_hlo={},
            tolerance={},
            content_masked={},
        )
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
conda run -n helao python -m pytest harness/tests/test_capture.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'harness.capture'`.

- [ ] **Step 3: Write the implementation**

Create `harness/capture.py`:

```python
"""Golden-master capture rig (spec §6.2): submit, quiesce, snapshot, manifest.

The rig NEVER launches or kills servers. Launch the group first, in another
terminal, from the repo root:

    rm -rf /home/dan/INST_hlo_golden          # captures start from a FRESH root
    conda run -n helao python launch.py golden --no-hot-reload

then run one scenario:

    conda run -n helao python -m harness.capture --scenario GM-1 \
        --root /home/dan/INST_hlo_golden \
        --out /home/dan/helao_goldens/GM-1/run1

and CTRL-x the launch terminal afterwards. One scenario per launch: the rig
refuses a root that already contains run artifacts, so re-launch (with a
fresh root) between scenarios and between the run1/run2 baseline captures.

Determinism levers (spec §6.1): fixed wait_time/data_duration; GM-4 uses
wait_time=20.0 so 5 s-in control POSTs always land inside action 0; WsSim
random values are masked via the manifest column lists; quiesce-before-
snapshot per §5.7 (orch stopped + DB queue drained + RUNS_ACTIVE settled,
three consecutive clean polls).
"""

from __future__ import annotations

import argparse
import datetime
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

import requests

from helao.core.error import ErrorCodes
from helao.helpers.dispatcher import private_dispatcher
from helao.helpers.premodels import ExperimentPlanMaker, Sequence
from helao.helpers.time_utils import gen_uuid

from harness import HARNESS_VERSION
from harness.manifest import ProvenanceManifest
from harness.treepass import PARITY_TOPS

ORCH_HOST, ORCH_PORT = "127.0.0.1", 8001
SIM_HOST, SIM_PORT = "127.0.0.1", 8002
DB_HOST, DB_PORT = "127.0.0.1", 8010

# WsExec streams epoch_s + series_0..5 (ws_simulator.py); values are unseeded
# np.random -> masked per §5.5 "unseeded sim data values", counts compared
# within a small poll-jitter tolerance recorded here (manifest-resident, §6.4).
WSSIM_COLUMNS = [
    "epoch_s",
    "series_0",
    "series_1",
    "series_2",
    "series_3",
    "series_4",
    "series_5",
]
WSSIM_MASKED = {
    "*WsSim*.hlo": WSSIM_COLUMNS,
    "*WsSim*.hlo.json*": WSSIM_COLUMNS,
}
WSSIM_TOLERANCE = {"*WsSim*.hlo": 3, "*WsSim*.hlo.json*": 3}
# hlo_to_csv output derives from the masked random columns: line-count only.
WSSIM_CONTENT_MASKED = {"*.csv": "line-count"}


# --- wire helpers -----------------------------------------------------------
def wait_for_server(host: str, port: int, timeout_s: float = 180.0) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            r = requests.post(f"http://{host}:{port}/get_status", timeout=2)
            if r.status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(2)
    raise TimeoutError(f"server {host}:{port} not up after {timeout_s}s")


def orch_post(endpoint: str, params: Optional[dict] = None, body: Optional[dict] = None):
    resp, err = private_dispatcher(
        "ORCH",
        ORCH_HOST,
        ORCH_PORT,
        endpoint,
        params_dict=params or {},
        json_dict=body or {},
    )
    if err != ErrorCodes.none:
        raise RuntimeError(f"ORCH /{endpoint} failed: {err}")
    return resp


def db_post(endpoint: str, params: Optional[dict] = None):
    r = requests.post(
        f"http://{DB_HOST}:{DB_PORT}/{endpoint}", params=params or {}, timeout=30
    )
    r.raise_for_status()
    return r.json()


def submit_and_start(seq: Sequence) -> None:
    orch_post("append_sequence", body={"sequence": seq.as_dict()})
    orch_post("start")


def loop_state() -> Tuple[str, bool]:
    gs = requests.post(
        f"http://{ORCH_HOST}:{ORCH_PORT}/global_status", timeout=10
    ).json()
    return str(gs.get("loop_state")), bool(gs.get("active_dict"))


def orch_stopped() -> bool:
    state, active = loop_state()
    return state.endswith("stopped") and not active


def db_drained() -> bool:
    n = db_post("n_queue")
    tasks = db_post("tasks")
    return n == 0 and not tasks.get("running")


def runs_active_empty(root: Path) -> bool:
    active = Path(root) / "RUNS_ACTIVE"
    if not active.is_dir():
        return True
    return next(active.rglob("*.yml"), None) is None


def wait_until(pred: Callable[[], bool], timeout_s: float = 600.0, poll_s: float = 2.0):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if pred():
            return
        time.sleep(poll_s)
    raise TimeoutError(f"condition {pred.__name__} not met after {timeout_s}s")


def quiesce(
    root: Path,
    require_orch: bool = True,
    require_active_empty: bool = True,
    settle_polls: int = 3,
    poll_s: float = 2.0,
    timeout_s: float = 1800.0,
) -> None:
    """§5.7 quiesce: fire-and-forget moves settled before snapshotting."""
    t0 = time.time()
    settled = 0
    while time.time() - t0 < timeout_s:
        ok = db_drained()
        if require_orch:
            ok = ok and orch_stopped()
        if require_active_empty:
            ok = ok and runs_active_empty(root)
        settled = settled + 1 if ok else 0
        if settled >= settle_polls:
            return
        time.sleep(poll_s)
    raise TimeoutError("group did not quiesce")


# --- scenario builders ------------------------------------------------------
def build_gm1_sequence() -> Sequence:
    epm = ExperimentPlanMaker()
    epm.add("SIM_websocket_data", {"wait_time": 2.0, "data_duration": 4.0})
    epm.add("SIM_websocket_data", {"wait_time": 2.0, "data_duration": 4.0})
    return Sequence(
        sequence_name="SIM_websocket_data_seq",
        sequence_label="golden",
        sequence_params={"wait_time": 2.0, "data_duration": 4.0},
        planned_experiments=epm.planned_experiments,
        sequence_uuid=gen_uuid(),
        dummy=True,
        simulation=True,
    )


GM2_PARAMS = {"wait_time": 2.0, "cycles": 2, "plate_sample_no_list": [1, 2]}


def build_gm2_sequence() -> Sequence:
    from helao.deploy.test.sequences.TEST_seq import TEST_consecutive_noblocking

    return Sequence(
        sequence_name="TEST_consecutive_noblocking",
        sequence_label="golden",
        sequence_params=GM2_PARAMS,
        planned_experiments=TEST_consecutive_noblocking(**GM2_PARAMS),
        sequence_uuid=gen_uuid(),
        dummy=True,
        simulation=True,
    )


def build_gm4_sequence(label: str) -> Sequence:
    epm = ExperimentPlanMaker()
    epm.add("SIM_websocket_data", {"wait_time": 20.0, "data_duration": 4.0})
    epm.add("SIM_websocket_data", {"wait_time": 20.0, "data_duration": 4.0})
    return Sequence(
        sequence_name="SIM_websocket_data_seq",
        sequence_label=label,
        sequence_params={"wait_time": 20.0, "data_duration": 4.0},
        planned_experiments=epm.planned_experiments,
        sequence_uuid=gen_uuid(),
        dummy=True,
        simulation=True,
    )


# --- scenario drivers (return sequence_name, sequence_params for provenance) -
def run_gm1(root: Path) -> Tuple[str, dict]:
    seq = build_gm1_sequence()
    submit_and_start(seq)
    quiesce(root)
    return seq.sequence_name, dict(seq.sequence_params)


def run_gm2(root: Path) -> Tuple[str, dict]:
    seq = build_gm2_sequence()
    submit_and_start(seq)
    quiesce(root)
    return seq.sequence_name, dict(seq.sequence_params)


def run_gm3(root: Path) -> Tuple[str, dict]:
    """Manual action: direct POST bypasses the orch (RUNS_DIAG tree)."""
    r = requests.post(
        f"http://{SIM_HOST}:{SIM_PORT}/SIM/acquire_data",
        params={"duration": 2.0, "acquisition_rate": 0.2},
        json={"fast_samples_in": []},
        timeout=60,
    )
    r.raise_for_status()
    # manual runs never touch the syncer; settle on RUNS_ACTIVE emptying only
    quiesce(root, require_orch=False)
    return "", {"duration": 2.0, "acquisition_rate": 0.2, "manual": True}


def run_gm4(root: Path) -> Tuple[str, dict]:
    # Leg 1 — stop-intent drain, then resume to completion.
    submit_and_start(build_gm4_sequence("GM4_stop"))
    time.sleep(5)  # inside experiment 1's first 20 s wait
    orch_post("stop")
    wait_until(orch_stopped, timeout_s=600)
    orch_post("start")  # resume: remaining experiment runs to completion
    quiesce(root)
    # Leg 2 — skip_experiment clears action_dq; running wait completes,
    # remaining actions of experiment 1 are dropped, experiment 2 runs fully.
    submit_and_start(build_gm4_sequence("GM4_skip"))
    time.sleep(5)
    orch_post("skip_experiment")
    quiesce(root)
    # Leg 3 — estop mid-experiment: [finished, estopped] artifacts, deferred
    # promotion (§5.4 items 5-6); wait past the 30 s child-dir window.
    submit_and_start(build_gm4_sequence("GM4_estop"))
    time.sleep(5)
    orch_post("estop_orch")
    wait_until(lambda: loop_state()[0].endswith("estopped"), timeout_s=300)
    time.sleep(40)
    quiesce(root, require_orch=False, require_active_empty=False)
    orch_post("clear_estop")
    return "SIM_websocket_data_seq", {
        "wait_time": 20.0,
        "data_duration": 4.0,
        "legs": ["stop+resume", "skip", "estop"],
    }


def run_gm5(root: Path) -> Tuple[str, dict]:
    """GM-1 through the sync leg + reset_sync/finish_pending round-trip."""
    seq = build_gm1_sequence()
    submit_and_start(seq)
    quiesce(root)
    zips = sorted((Path(root) / "RUNS_SYNCED").rglob("*.zip"))
    if not zips:
        raise RuntimeError("GM-5: no RUNS_SYNCED zip after quiesce")
    db_post("reset_sync", params={"sync_path": str(zips[0])})
    db_post("finish_pending", params={"actions_first": True})
    quiesce(root)
    if not sorted((Path(root) / "RUNS_SYNCED").rglob("*.zip")):
        raise RuntimeError("GM-5: re-sync did not restore the RUNS_SYNCED zip")
    return seq.sequence_name, dict(
        seq.sequence_params, round_trip="reset_sync+finish_pending"
    )


SCENARIOS: Dict[str, Callable[[Path], Tuple[str, dict]]] = {
    "GM-1": run_gm1,
    "GM-2": run_gm2,
    "GM-3": run_gm3,
    "GM-4": run_gm4,
    "GM-5": run_gm5,
}

SCENARIO_MASKS: Dict[str, tuple] = {
    # (masked_hlo_columns, hlo_row_count_tolerance, content_masked_files)
    "GM-1": (WSSIM_MASKED, WSSIM_TOLERANCE, WSSIM_CONTENT_MASKED),
    "GM-2": ({}, {}, {}),
    "GM-3": (WSSIM_MASKED, WSSIM_TOLERANCE, WSSIM_CONTENT_MASKED),
    "GM-4": (WSSIM_MASKED, WSSIM_TOLERANCE, WSSIM_CONTENT_MASKED),
    "GM-5": (WSSIM_MASKED, WSSIM_TOLERANCE, WSSIM_CONTENT_MASKED),
}


# --- snapshot ----------------------------------------------------------------
def assert_fresh(root: Path) -> None:
    finished = Path(root) / "RUNS_FINISHED"
    if finished.is_dir() and next(finished.rglob("*.yml"), None) is not None:
        raise RuntimeError(
            f"{root} already contains run artifacts; captures require a fresh "
            "root (rm -rf it, then re-launch)"
        )
    synced = Path(root) / "RUNS_SYNCED"
    if synced.is_dir() and next(synced.rglob("*"), None) is not None:
        raise RuntimeError(f"{root}/RUNS_SYNCED is not empty; use a fresh root")


def snapshot_capture(
    root: Path,
    out_dir: Path,
    scenario: str,
    config_prefix: str,
    sequence_name: str,
    sequence_params: dict,
    masked_hlo: dict,
    tolerance: dict,
    content_masked: dict,
    notes: str = "",
) -> Path:
    root, out_dir = Path(root), Path(out_dir)
    if out_dir.exists():
        raise FileExistsError(
            f"{out_dir} already exists; refusing to overwrite a capture"
        )
    out_root = out_dir / "root"
    out_root.mkdir(parents=True)
    for top in PARITY_TOPS:
        src = root / top
        if src.is_dir():
            shutil.copytree(src, out_root / top)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    config_path = (
        Path(__file__).resolve().parents[1]
        / "helao"
        / "deploy"
        / "test"
        / "configs"
        / f"{config_prefix}.yml"
    )
    ProvenanceManifest(
        scenario=scenario,
        config_prefix=config_prefix,
        config_path=str(config_path),
        legacy_git_sha=sha,
        launch_cmd=f"conda run -n helao python launch.py {config_prefix} --no-hot-reload",
        sequence_name=sequence_name,
        sequence_params=sequence_params,
        capture_timestamp=datetime.datetime.now().isoformat(timespec="seconds"),
        harness_version=HARNESS_VERSION,
        masked_hlo_columns=masked_hlo,
        hlo_row_count_tolerance=tolerance,
        content_masked_files=content_masked,
        notes=notes,
    ).save(out_dir)
    return out_dir


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m harness.capture", description=__doc__)
    parser.add_argument("--scenario", required=True, choices=sorted(SCENARIOS))
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--config-prefix", default="golden")
    parser.add_argument("--notes", default="")
    args = parser.parse_args(argv)
    assert_fresh(args.root)
    wait_for_server(ORCH_HOST, ORCH_PORT)
    wait_for_server(SIM_HOST, SIM_PORT)
    wait_for_server(DB_HOST, DB_PORT)
    seq_name, seq_params = SCENARIOS[args.scenario](args.root)
    masked, tolerance, content_masked = SCENARIO_MASKS[args.scenario]
    out = snapshot_capture(
        root=args.root,
        out_dir=args.out,
        scenario=args.scenario,
        config_prefix=args.config_prefix,
        sequence_name=seq_name,
        sequence_params=seq_params,
        masked_hlo=masked,
        tolerance=tolerance,
        content_masked=content_masked,
        notes=args.notes,
    )
    print(f"captured {args.scenario} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
conda run -n helao python -m pytest harness/tests/test_capture.py -v
```

Expected: `5 passed`. (`test_gm2_sequence_uses_library_function` imports `TEST_seq`, which is import-light; no gpflow trap here.)

- [ ] **Step 5: Live smoke — capture one GM-1 end to end**

Terminal A:
```bash
cd /mnt/STORAGE/repos/helao/helao-async
rm -rf /home/dan/INST_hlo_golden
conda run -n helao python launch.py golden --no-hot-reload
```

Terminal B (after servers are up):
```bash
cd /mnt/STORAGE/repos/helao/helao-async
conda run -n helao python -m harness.capture --scenario GM-1 \
    --root /home/dan/INST_hlo_golden \
    --out /home/dan/helao_goldens/GM-1/smoke
ls /home/dan/helao_goldens/GM-1/smoke
find /home/dan/helao_goldens/GM-1/smoke/root/PROCESSES -name '*-prc.yml' | wc -l
find /home/dan/helao_goldens/GM-1/smoke/root/S3_SIM -name 'manifest.jsonl'
```

Expected: `captured GM-1 -> /home/dan/helao_goldens/GM-1/smoke`; listing shows `provenance.yml root`; **4** prc ymls (two per experiment); the S3_SIM manifest exists. If the WsSim csv filename pattern differs from `*.csv`, adjust `WSSIM_CONTENT_MASKED` to the observed name pattern NOW and note it in the commit message (manifest-resident masking is per-capture configuration, §6.4). CTRL-x terminal A when done; the smoke capture may be deleted afterwards (`rm -rf /home/dan/helao_goldens/GM-1/smoke`).

- [ ] **Step 6: Format and commit**

```bash
conda run -n helao black harness
git add harness/capture.py harness/tests/test_capture.py
git commit -m "feat(harness): capture rig with GM-1..GM-5 scenario drivers, quiesce, provenance snapshot"
```

---

### Task 14: Endpoint-extraction tooling (§8.3 checklist generator)

**Files:**
- Create: `harness/endpoints.py`
- Test: `harness/tests/test_endpoints.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (stdlib `ast` only — extraction must work WITHOUT importing the target module, so Windows-only vendor imports never run).
- Produces: `extract_routes(module_path: Path, server_key: str | None = None) -> list[dict]` (each entry `{"path", "method", "tags", "handler", "params": [{"name","annotation","default"}]}` sorted by `(path, method)`), `diff_route_sets(frozen: list, current: list) -> list[dict]`; CLI `python -m harness.endpoints extract <module.py> [--server-key K] [--out routes.json]` and `python -m harness.endpoints diff <frozen.json> <current.json>` (exit 1 on any difference). P1+ phase plans freeze legacy extractions with `extract` and gate compositions with `diff`.

- [ ] **Step 1: Write the failing test**

Create `harness/tests/test_endpoints.py`:

```python
"""AST route extraction against a REAL legacy server module (ws_simulator)."""

from pathlib import Path

from harness.endpoints import diff_route_sets, extract_routes

WS_SIM = Path("helao/deploy/test/servers/action/ws_simulator.py")


def test_extracts_action_routes_with_server_key_substitution():
    routes = extract_routes(WS_SIM, server_key="SIM")
    by_path = {r["path"]: r for r in routes}
    assert "/SIM/acquire_data" in by_path
    acq = by_path["/SIM/acquire_data"]
    assert acq["method"] == "post"
    assert acq["tags"] == ["action"]
    params = {p["name"]: p for p in acq["params"]}
    assert params["duration"]["annotation"] == "float"
    assert params["duration"]["default"] == "-1"
    assert params["acquisition_rate"]["default"] == "0.2"
    assert "fast_samples_in" in params
    assert "/SIM/cancel_acquire_data" in by_path


def test_fstring_paths_keep_placeholder_without_server_key():
    routes = extract_routes(WS_SIM)
    paths = [r["path"] for r in routes]
    assert "/{server_key}/acquire_data" in paths


def test_diff_route_sets_reports_gaps():
    frozen = extract_routes(WS_SIM, server_key="SIM")
    assert diff_route_sets(frozen, frozen) == []
    shrunk = [r for r in frozen if r["path"] != "/SIM/acquire_data"]
    diffs = diff_route_sets(frozen, shrunk)
    assert any(
        d["path"] == "/SIM/acquire_data" and d["kind"] == "missing" for d in diffs
    )
    mutated = [dict(r) for r in frozen]
    for r in mutated:
        if r["path"] == "/SIM/acquire_data":
            r["params"] = [p for p in r["params"] if p["name"] != "duration"]
    diffs = diff_route_sets(frozen, mutated)
    assert any(d["kind"] == "changed" for d in diffs)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
conda run -n helao python -m pytest harness/tests/test_endpoints.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'harness.endpoints'`.

- [ ] **Step 3: Write the implementation**

Create `harness/endpoints.py`:

```python
"""AST route-set extractor + checklist diff (spec §8.3).

Extracts every route registered via ``@app.<method>(path, tags=[...])`` (or
``@self.<method>`` inside API classes) from a server module WITHOUT importing
it — so modules with Windows-only vendor imports extract fine on Linux, and
the frozen legacy extraction becomes the endpoint-parity checklist a later
phase's composition is diffed against.

Limits (by design, documented): decorator paths built from anything other
than constants and simple f-string ``{name}`` substitutions extract as
``{?}``; routes registered dynamically at runtime (BaseAPI system surface,
config-shaped dyn endpoints) are NOT visible statically — §8.3 pairs this
static pass with the runtime /openapi.json cross-check at preflight (P1+).
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import List, Optional

HTTP_METHODS = {"post", "get", "put", "delete", "head", "websocket"}


def _path_str(node: ast.expr) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: List[str] = []
        for v in node.values:
            if isinstance(v, ast.Constant):
                parts.append(str(v.value))
            elif isinstance(v, ast.FormattedValue) and isinstance(v.value, ast.Name):
                parts.append("{" + v.value.id + "}")
            else:
                parts.append("{?}")
        return "".join(parts)
    return None


def _decorator_route(dec: ast.expr) -> Optional[dict]:
    if not isinstance(dec, ast.Call):
        return None
    func = dec.func
    if not (isinstance(func, ast.Attribute) and func.attr in HTTP_METHODS):
        return None
    if not dec.args:
        return None
    path = _path_str(dec.args[0])
    if path is None:
        return None
    tags: List[str] = []
    for kw in dec.keywords:
        if kw.arg == "tags" and isinstance(kw.value, ast.List):
            tags = [e.value for e in kw.value.elts if isinstance(e, ast.Constant)]
    return {"path": path, "method": func.attr, "tags": tags}


def _params(fn) -> List[dict]:
    out: List[dict] = []
    args = fn.args
    defaults = [None] * (len(args.args) - len(args.defaults)) + list(args.defaults)
    for a, d in zip(args.args, defaults):
        if a.arg == "self":
            continue
        out.append(
            {
                "name": a.arg,
                "annotation": ast.unparse(a.annotation) if a.annotation else None,
                "default": ast.unparse(d) if d is not None else None,
            }
        )
    return out


def extract_routes(module_path: Path, server_key: Optional[str] = None) -> List[dict]:
    tree = ast.parse(Path(module_path).read_text())
    routes: List[dict] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                r = _decorator_route(dec)
                if r is None:
                    continue
                path = r["path"]
                if server_key is not None:
                    path = path.replace("{server_key}", server_key)
                routes.append(
                    {
                        "path": path,
                        "method": r["method"],
                        "tags": r["tags"],
                        "handler": node.name,
                        "params": _params(node),
                    }
                )
    return sorted(routes, key=lambda r: (r["path"], r["method"]))


def diff_route_sets(frozen: List[dict], current: List[dict]) -> List[dict]:
    """Checklist diff: every frozen route present with equal schema, no extras."""

    def key(r: dict):
        return (r["path"], r["method"])

    fmap = {key(r): r for r in frozen}
    cmap = {key(r): r for r in current}
    diffs: List[dict] = []
    for k in sorted(set(fmap) - set(cmap)):
        diffs.append({"path": k[0], "method": k[1], "kind": "missing"})
    for k in sorted(set(cmap) - set(fmap)):
        diffs.append({"path": k[0], "method": k[1], "kind": "extra"})
    for k in sorted(set(fmap) & set(cmap)):
        f, c = fmap[k], cmap[k]
        for field in ("tags", "params"):
            if f[field] != c[field]:
                diffs.append(
                    {
                        "path": k[0],
                        "method": k[1],
                        "kind": "changed",
                        "field": field,
                        "frozen": f[field],
                        "current": c[field],
                    }
                )
    return diffs


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m harness.endpoints")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_ext = sub.add_parser("extract")
    p_ext.add_argument("module", type=Path)
    p_ext.add_argument("--server-key", default=None)
    p_ext.add_argument("--out", type=Path, default=None)
    p_diff = sub.add_parser("diff")
    p_diff.add_argument("frozen", type=Path)
    p_diff.add_argument("current", type=Path)
    args = parser.parse_args(argv)
    if args.cmd == "extract":
        routes = extract_routes(args.module, server_key=args.server_key)
        text = json.dumps(routes, indent=2)
        if args.out:
            args.out.write_text(text)
        else:
            print(text)
        return 0
    frozen = json.loads(args.frozen.read_text())
    current = json.loads(args.current.read_text())
    diffs = diff_route_sets(frozen, current)
    for d in diffs:
        print(json.dumps(d))
    return 1 if diffs else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
conda run -n helao python -m pytest harness/tests/test_endpoints.py -v
```

Expected: `3 passed`.

- [ ] **Step 5: Exercise the CLI once against real modules**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
conda run -n helao python -m harness.endpoints extract \
    helao/deploy/test/servers/action/sim_db_server.py | head -20
conda run -n helao python -m harness.endpoints extract \
    helao/core/servers/orch_api.py | grep '"path"' | wc -l
```

Expected: the first prints JSON starting with the `/current_progress` or `/finish_yml` route; the second prints a route count > 40 (the OrchAPI private surface — this is how P1's orch checklist gets frozen).

- [ ] **Step 6: Format and commit**

```bash
conda run -n helao black harness
git add harness/endpoints.py harness/tests/test_endpoints.py
git commit -m "feat(harness): AST endpoint-extraction tool + route-set checklist diff"
```

---

### Task 15: Logging / config / clock behavior tests against LEGACY (§9 contracts)

**Files:**
- Test: `harness/tests/test_legacy_contracts.py`

**Interfaces:**
- Consumes: legacy `helao.helpers.helao_logging.make_logger(logger_name=None, log_dir=None, log_level=20, email_config={}, show_debug_console=False, dedup_interval=…)` and `NtpOffsetFormatter(*args, offset_seconds=0, use_utc=False, **kwargs)`; `helao.helpers.config_loader.read_config`, `install_global_config`, `read_validated_config`, module global `CONFIG`; `helao.helpers.time_utils.set_time(offset)`, `read_saved_offset(file_path)`; the `golden` config prefix (Task 10).
- Produces: pinned behavior tests that DEFINE the §9 contracts the later ports must meet. The hexagon Logging port (P1) must keep `test_log_file_lands_at_contract_path` green and must make the behavior documented by `test_tempdir_trap_exists_in_legacy` UNREACHABLE (the port raises instead — F3).

- [ ] **Step 1: Write the tests (they pass immediately against legacy — they are executable documentation, so write + run + commit)**

Create `harness/tests/test_legacy_contracts.py`:

```python
"""§9 contracts pinned against LEGACY: logging path, config identity, clock.

These tests define what the hexagon ports must reproduce (or, for the
tempdir trap, make unreachable). They run on legacy code only — no hexagon
imports exist in P0.
"""

import datetime
import logging as std_logging
import tempfile

from helao.helpers import config_loader
from helao.helpers.config_loader import (
    install_global_config,
    read_config,
    read_validated_config,
)
from helao.helpers.helao_logging import NtpOffsetFormatter, make_logger
from helao.helpers.time_utils import read_saved_offset, set_time


# --- §9.1 logging -----------------------------------------------------------
def test_log_file_lands_at_contract_path(tmp_path, monkeypatch):
    """<root>/LOGS/<server_key>.log — flat file, no per-server subdir, no /tmp."""
    mkdtemp_calls = []
    real_mkdtemp = tempfile.mkdtemp

    def spy_mkdtemp(*a, **k):
        mkdtemp_calls.append(1)
        return real_mkdtemp(*a, **k)

    monkeypatch.setattr(tempfile, "mkdtemp", spy_mkdtemp)
    log_dir = tmp_path / "LOGS"
    log_dir.mkdir()
    logger = make_logger("GOLDENKEY", log_dir=str(log_dir))
    logger.info("logging path contract check")
    assert (log_dir / "GOLDENKEY.log").exists()
    assert mkdtemp_calls == [], "/tmp must gain nothing when log_dir is provided"


def test_tempdir_trap_exists_in_legacy(monkeypatch, tmp_path):
    """DOCUMENTS the F3 trap: make_logger(log_dir=None) falls back to mkdtemp.

    The hexagon Logging port must RAISE here instead; when P1 lands, port
    conformance asserts this call path is unreachable through the port.
    """
    made = []

    def fake_mkdtemp(*a, **k):
        d = tmp_path / f"faketmp{len(made)}"
        d.mkdir()
        made.append(str(d))
        return str(d)

    monkeypatch.setattr(tempfile, "mkdtemp", fake_mkdtemp)
    make_logger("TRAPKEY_P0")  # log_dir=None -> legacy silently uses a temp dir
    assert made, "legacy trap fired (expected today; must be dead behind the port)"


def test_logger_handlers_gate_but_logger_is_debug():
    """Logger level min(10, log_level); handlers carry the effective gate."""
    logger = make_logger("LEVELKEY_P0", log_dir=tempfile.mkdtemp(), log_level=30)
    assert logger.level <= 10
    assert logger.propagate is False
    assert any(h.level == 30 for h in logger.handlers)


# --- §9.2 config raw-dict identity -------------------------------------------
def test_config_raw_dict_identity_and_augmentation():
    cfg = read_config("golden")
    installed = install_global_config(cfg)
    assert installed is cfg
    assert config_loader.CONFIG is cfg
    # --restore's same-object aliasing gate: the server sub-dict is THE object
    assert config_loader.CONFIG["servers"]["ORCH"] is cfg["servers"]["ORCH"]
    # launcher-added augmentation keys present on the raw dict
    assert "loaded_config_path" in cfg
    assert "helao_repo_root" in cfg


def test_typed_config_is_a_gate_not_a_replacement():
    raw, validated = read_validated_config("golden")
    dumped = validated.model_dump()
    # the schema drops launcher-added keys — installing it would break --restore
    assert "loaded_config_path" in raw
    assert "loaded_config_path" not in dumped


# --- §9.3 clock / NTP ---------------------------------------------------------
def test_offset_file_roundtrip(tmp_path):
    p = tmp_path / "ntpLastSync.txt"
    p.write_text("1752600000.0,2.5")
    last_sync, offset = read_saved_offset(str(p))
    assert last_sync == "1752600000.0"
    assert offset == 2.5


def test_set_time_shifts_by_offset():
    base = set_time(0)
    shifted = set_time(3600.0)
    delta = (shifted - base).total_seconds()
    assert 3599.0 < delta < 3601.0


def test_ntp_formatter_shifts_log_timestamps():
    rec = std_logging.LogRecord("x", 20, "f", 1, "msg", (), None)
    fmt0 = NtpOffsetFormatter("%(asctime)s", offset_seconds=0)
    fmt1 = NtpOffsetFormatter("%(asctime)s", offset_seconds=3600.0)
    t0 = datetime.datetime.strptime(
        fmt0.formatTime(rec, "%Y-%m-%d %H:%M:%S"), "%Y-%m-%d %H:%M:%S"
    )
    t1 = datetime.datetime.strptime(
        fmt1.formatTime(rec, "%Y-%m-%d %H:%M:%S"), "%Y-%m-%d %H:%M:%S"
    )
    assert abs((t1 - t0).total_seconds() - 3600.0) <= 1.0
```

- [ ] **Step 2: Run the tests**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
conda run -n helao python -m pytest harness/tests/test_legacy_contracts.py -v
```

Expected: `8 passed`. If any fails, STOP: either the contract reading is wrong (fix the test to match observed legacy behavior and note it) or legacy changed under us (re-read spec §9 and escalate) — these tests must pin real behavior, not intended behavior.

- [ ] **Step 3: Format and commit**

```bash
conda run -n helao black harness
git add harness/tests/test_legacy_contracts.py
git commit -m "test(harness): pin legacy logging/config/clock contracts (spec s9) incl. tempdir trap"
```

---

### Task 16: P0 GATE — legacy reproduces its own goldens

**Files:**
- Create: `harness/docs/p0-gate-record.md`
- (No source changes — this task runs the tooling built above and records evidence.)

**Interfaces:**
- Consumes: the capture CLI (Task 13), the parity CLI (Task 8), the mutation CLI (Task 9), the Q3 record (Task 12), configs (Task 10), sim DB server (Task 11).
- Produces: the recorded P0 gate evidence: per-scenario run IDs for legacy-vs-legacy PASS, a mutation self-test PASS on a real golden, and the golden sets under `/home/dan/helao_goldens/` that P1's gate will diff hexagon candidates against.

Gate definition (spec §12 P0): two independent legacy runs of each scenario GM-1..GM-5 are normalized-identical, including the FINISHED→SYNCED→S3-recorded leg; the harness fails a deliberately perturbed tree; Q3 is resolved with a documented run.

- [ ] **Step 1: Capture run1 and run2 for every scenario**

For EACH scenario `S` in `GM-1 GM-2 GM-3 GM-4 GM-5` and EACH run `R` in `run1 run2`, repeat this cycle (fresh root + fresh launch per capture — full independence):

Terminal A:
```bash
cd /mnt/STORAGE/repos/helao/helao-async
rm -rf /home/dan/INST_hlo_golden
conda run -n helao python launch.py golden --no-hot-reload
```

Terminal B (after servers settle):
```bash
cd /mnt/STORAGE/repos/helao/helao-async
conda run -n helao python -m harness.capture --scenario S \
    --root /home/dan/INST_hlo_golden \
    --out /home/dan/helao_goldens/S/R
```

Then CTRL-x in terminal A. Expected per capture: `captured S -> /home/dan/helao_goldens/S/R`. (10 captures total; GM-1/GM-2/GM-3/GM-5 take ~1–5 minutes each, GM-4 ~5–10 minutes because of the 20 s waits and the 40 s estop settle.)

- [ ] **Step 2: Run the legacy-vs-legacy baseline diff for every scenario**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
for S in GM-1 GM-2 GM-3 GM-4 GM-5; do
  conda run -n helao python -m harness.parity \
      --golden /home/dan/helao_goldens/$S/run1 \
      --candidate /home/dan/helao_goldens/$S/run2 \
      --report /home/dan/helao_goldens/$S/baseline-report.json
done
```

Expected: five lines `parity run <id>: PASS (0 diffs) scenario=<S>`, exit 0 each.

**If a scenario FAILS:** this is the gate doing its job — do not loosen the §5.5 list. Diagnose with the report + `python -m harness.normalize --root …`. Known determinism levers (spec §6.1): quiesce settling (raise `settle_polls`/`poll_s` in `quiesce`), WsSim row-count jitter (raise the scenario's `hlo_row_count_tolerance` in `SCENARIO_MASKS` — a manifest-resident lever), csv naming (adjust `content_masked_files` pattern), GM-4 timing (raise the leg waits). Any lever change requires re-capturing BOTH runs of that scenario and a note in the gate record. A diff that is not volatile-value masking (e.g. differing file sets, differing params) means a real nondeterminism or a normalizer bug — fix the harness or the scenario driver, never the volatile list.

- [ ] **Step 3: Run the mutation self-test against a real golden**

```bash
rm -rf /home/dan/helao_goldens/mutation-work
conda run -n helao python -m harness.mutate \
    --golden /home/dan/helao_goldens/GM-1/run1 \
    --workdir /home/dan/helao_goldens/mutation-work
echo "exit: $?"
```

Expected: four `mutation <name>: … -> fail` lines, a result dict with `'ok': True`, exit 0.

- [ ] **Step 4: Write `harness/docs/p0-gate-record.md`**

```markdown
# P0 gate record (spec §12 P0)

**Date:** <fill in>
**Legacy SHA:** <git rev-parse HEAD>
**Harness version:** 0.1.0
**Golden store:** /home/dan/helao_goldens/ (Q2 default: untracked share;
at-station goldens for private deployments must stay off the public repo)

## Legacy-vs-legacy baseline (two independent runs, normalized-identical)

| Scenario | run1 captured | run2 captured | parity run_id | status |
|---|---|---|---|---|
| GM-1 | <ts> | <ts> | <id> | PASS |
| GM-2 | <ts> | <ts> | <id> | PASS |
| GM-3 | <ts> | <ts> | <id> | PASS |
| GM-4 | <ts> | <ts> | <id> | PASS |
| GM-5 | <ts> | <ts> | <id> | PASS |

Sync leg (FINISHED→SYNCED→S3-recorded) covered by every recording-mode
capture and doubly by GM-5's reset_sync/finish_pending round-trip.

## Mutation self-test

Golden: GM-1/run1. Result: param_value / drop_file / add_hlo_column /
break_uuid_link all CAUGHT (parity failed each). Exit 0. <paste result dict>

## Q3

Resolved in harness/docs/q3-local-only-sync.md — verdict: <YES/NO + one line>.

## Determinism levers exercised (if any)

<none | list of manifest-resident lever changes + why + which scenarios were
re-captured>
```

Fill every `<...>` from the actual runs before committing.

- [ ] **Step 5: Full harness suite green + commit the gate record**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
conda run -n helao python -m pytest harness/tests -q
git add harness/docs/p0-gate-record.md
git commit -m "docs(harness): P0 gate record - legacy-vs-legacy baseline PASS + mutation self-test"
```

Expected: all harness tests pass; the branch now holds the complete P0 deliverable set. **Do not push** — the controller reviews the branch and the golden store.

---

## Self-Review

**1. Spec coverage (P0 requirements → tasks):**

| Spec §12 P0 deliverable | Task(s) |
|---|---|
| Normalizer (§6.4) — tree pass (timestamp-strip grammar, uuid→ordinal mapping so uuid5 derivation + links are checked) | 2, 3, 5 |
| Normalizer — YAML pass (§5.5 exact volatile list, absent==empty, ordering-hazard sorts, canonical re-dump/compare) | 4 |
| Normalizer — HLO pass (epoch_ns/hlo_version drop, `%%` split via legacy reader, JSON-lines body, manifest-resident masked columns) | 6 |
| Normalizer — S3 pass (key templates uuid-mapped via tree pass, payload normalization, FileInfo rename + technique-split asserted as intentional differences) | 5, 7 |
| Normalizer unit-tested with tiny synthetic trees + mutation self-test | 5 (synthtree), 2–7 tests, 9 |
| Diff CLI, machine-readable per-file/per-key report, exit code, hard-fail on manifest-less golden (§6.5) | 8 (+1 for the hard-fail itself) |
| `golden.yml` capture config (Linux root, no launch_browser, `--no-hot-reload` documented, DB entry; cross-deployment orch/operator/vis resolution noted) | 10 |
| Sim DB/sync server (§6.3): real HelaoSyncer, aws_bucket + no aws_config_path, local-only AND recording modes, full dbpack surface, Windows-tolerant; legacy seam analysis (none needed; fallback documented) | 11 |
| Capture rig (§6.2): programmatic append_sequence→start, `/global_status` + `/n_queue`+`/tasks` quiesce, snapshot + provenance manifest incl. per-scenario masked-column lists | 13 |
| Golden scenarios GM-1..GM-5 from legacy, with exact build/submit procedure per scenario | 13 (drivers), 16 (captures) |
| Endpoint-extraction tooling (§8.3 static pass) | 14 |
| Logging/config/clock behavior tests against legacy (§9; incl. `<root>/LOGS/<server_key>.log`, /tmp-gains-nothing, raw-dict `--restore` identity, NTP offset shift) | 15 |
| P0 gate: legacy-vs-legacy normalized-identical ×5 incl. sync leg; mutation self-test fails; Q3 resolved with documented run | 16, 12 |

Non-goals honored: no hexagon code, no legacy edits, no volatile-list additions (masking config is manifest-resident per §6.4), GM-6/GM-7 deferred exactly as the spec marks them (tier-2/optional — out of the P0 gate; the classifier already handles row 12 MANIFEST.txt for the day GM-7 lands).

**2. Placeholder scan:** the only `<fill in>`-style tokens are inside the two evidence-record TEMPLATES (Tasks 12/16) whose explicit step instruction is to replace them with observed values before committing — they are the deliverable's blank form, not plan gaps. One conditional instruction exists by design: Task 13 Step 5's "adjust `WSSIM_CONTENT_MASKED` to the observed csv name pattern" — a capture-time observation that cannot be pre-written without violating D4 (deriving artifacts from reading code); the default `*.csv` pattern is provided and functional. No TBD/TODO/"handle edge cases"/"similar to Task N" anywhere; every code step contains complete code.

**3. Type consistency:** verified across tasks — `ProvenanceManifest` field set (Task 1) matches every constructor call in synthtree (T5), hlo/s3 tests (T6/T7), and capture (T13), including the three masking fields; `UuidMapper.sub(text, strict=False)` (T3) matches treepass strict usage (T5) and s3/manifest lazy usage (T7/T8); `diff_meta` entry shape `{"key","golden","candidate"}` is uniform across yaml/hlo/s3/parity; `run_parity(golden_set, candidate, report_path=None) -> dict` (T8) is what mutate (T9) and the gate (T16) call; `snapshot(root, mapper)` two-arg form is used consistently after T5 introduced seeding; `SCENARIOS`/`SCENARIO_MASKS` keys match the CLI choices and Task 16's loop; sim_db_server endpoint names match `quiesce`'s `/n_queue`+`/tasks` polls and `move_dir`'s `/finish_yml` handoff.

**Known risks carried (with mitigations in-plan):** WsSim row-count jitter (manifest tolerance, T13/T16); GM-4 control-POST timing (20 s waits, T13); local-only sync completion unknown (Q3 task 12 with recorder-mode fallback); orch-side second HelaoSyncer instance (noted T10 — identical across baseline runs, so gate-neutral).
