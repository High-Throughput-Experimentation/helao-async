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
    IGNORE = 0  # LOGS/STATES/... — path-contractual but non-parity (row 14)
    SEQ_YML = 1
    EXP_YML = 2
    ACT_YML = 3
    HLO = 4  # streamed AND one-shot .hlo (rows 4/5 share the suffix)
    AUX_FILE = 5  # non-hlo one-shot/postprocess outputs (.csv, ...)
    PRC_YML = 7
    PRG = 8
    PARQUET = 9
    SEQ_ZIP = 10
    LOCK = 11
    MICRO_MANIFEST = 12
    ANALYSIS = 13
    S3_RECORD = 100  # files under S3_SIM/ (recorded uploads; S3 pass)


# --- §5.1 name grammar ----------------------------------------------------
RE_YYWW = re.compile(r"^\d{2}\.\d{2}$")  # %y.%U
RE_MMDD = re.compile(r"^\d{4}$")
RE_SEQ_DIR = re.compile(r"^\d{6}(__.+)$")  # HHMMSS__name__label...
RE_EXP_DIR = re.compile(r"^\d{6}\.\d{6}(__.+)$")  # %y%m%d.%H%M%S__name
RE_META_YML = re.compile(r"^\d{6}\.\d{12}-(seq|exp|act)\.yml$")  # %y%m%d.%H%M%S%f
RE_META_PRG = re.compile(r"^\d{6}\.\d{12}-(seq|exp|act)\.prg$")
RE_SEQ_ZIP = re.compile(r"^\d{6}(__.+)\.zip$")
RE_SEQ_ZIPDIR = re.compile(r"^\d{6}(__.+)\.zipdir$")  # explode_zips target

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
