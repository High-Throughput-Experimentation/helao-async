# BioLogic OLE COM Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `BiologicOleDriver`, a second BioLogic potentiostat backend that drives EC-Lab through its OLE COM interface, selectable per station by a `pstat_backend` config key and byte-identical at the action-server surface to the existing easy-biologic driver.

**Architecture:** A new sibling package `helao/deploy/hte/drivers/pstat/biologic_ole/` decomposed into single-responsibility modules — a `.mps` text patcher, a technique registry, a `MeasureStatus` decoder, an MPR point cursor, a COM wrapper, and a driver that composes them. `biologic_server.py` picks between the two drivers exactly as `andor_server.py` picks between its two, defaulting to the existing `eclib` backend so no live config changes. A fake COM server makes the whole path exercisable on Linux.

**Tech Stack:** Python 3.14, `comtypes` (Windows, already pinned in `helao_dev_win-64.yml`), pytest, `black` (line length 88), pyright basic mode.

**Spec:** `docs/superpowers/specs/2026-09-07-biologic-olecom-driver-design.md`

**Branch:** `feat/biologic-olecom-driver` (already created; the spec commit `f2e7598d` is its first commit).

## Global Constraints

- **Run everything through the `helao` conda env**: `conda run -n helao python ...`, or activate it first. The OS python is not 3.14 and lacks the dependencies. For pytest, prefer a direct `pytest` inside an activated env — `conda run` buffers output and makes hangs unreadable.
- **`PYTHONPATH` must include the repo root** (`/mnt/STORAGE/repos/helao/helao-async`). The conda env config sets this.
- **Run pytest one file at a time**, with a `timeout`. The suite hangs when collected as a single session (tests start event loops, bind sockets, spawn Bokeh servers) while every file passes individually.
- **`black` on every changed `.py` file immediately before `git add`.** Default settings, line length 88. This is a project rule, not a preference.
- **Never regenerate `helao/hexagon/tests/checklists/hte/*.json`.** They are the pre-migration record. A deliberate new route goes in `_additions.json`, never into the module checklist.
- **`comtypes` may be imported by exactly one module**, `biologic_ole/olecom_client.py`, and only inside a function — never at module scope. Everything else in the package must import and construct on Linux with no vendor package present.
- **Integration time, ranges and every other vendor value keep their existing HELAO spellings.** `IRange`, `ERange`, `Bandwidth`, `Tval__s`, `Vval__V`, `AcqInterval__s` and the rest are the frozen public contract; do not rename any of them.
- **Emitted data column names are frozen**: `t_s`, `Ewe_V`, `I_A`, `P_W`, `cycle` for DC techniques; plus `process`, `AbsEwe_V`, `AbsI_A`, `phase`, `modulus`, `Ece_V`, `AbsEce_V`, `AbsIce_A`, `phase_ce`, `modulus_ce`, `f_Hz`, `X_ohm`, `R_ohm` for EIS. Both `biologic_vis` panels and five experiment libraries read them.
- **EC-Lab minimum version is 11.11.** The driver refuses to run below it.
- **Never name the private deployments** in any tracked file. Refer to them as "private deployments".
- **No station hardware is available during this plan.** Every task below completes and is verified on Linux. The five at-station gates are listed at the end and are explicitly out of scope for these tasks.

---

## File Structure

**Created:**

| Path | Responsibility |
|---|---|
| `helao/deploy/hte/drivers/pstat/biologic_backend.py` | The `BiologicBackend` Protocol. No implementation, no vendor import. |
| `helao/deploy/hte/drivers/pstat/biologic_ole/__init__.py` | Package docstring only. |
| `helao/deploy/hte/drivers/pstat/biologic_ole/status.py` | Decode the 32-float `MeasureStatus` array. |
| `helao/deploy/hte/drivers/pstat/biologic_ole/mps_template.py` | Load / read / patch / write `.mps` text. Pure. |
| `helao/deploy/hte/drivers/pstat/biologic_ole/technique.py` | Per-technique template, parameter map, column plan, accepted technique codes. |
| `helao/deploy/hte/drivers/pstat/biologic_ole/olecom_client.py` | Typed wrapper over the 32 OLE functions. The only `comtypes` importer. |
| `helao/deploy/hte/drivers/pstat/biologic_ole/sim.py` | Fake COM server over synthetic MPR value tables. |
| `helao/deploy/hte/drivers/pstat/biologic_ole/mpr_cursor.py` | Point cursor and column assembly over the `Measure*` reads. |
| `helao/deploy/hte/drivers/pstat/biologic_ole/driver.py` | `BiologicOleDriver`, the ten-method surface. |
| `helao/deploy/hte/drivers/pstat/biologic_ole/templates/*.mps` | Nine templates. **Eight already committed**, all real GUI-authored EC-Lab v11.72 / SP-200 files (`TI`/`TO` extracted from a real `TI_CV_TO.mps`). Only `CAOCV.mps` remains. |
| `helao/deploy/hte/configs/biologicole.yml` | Simulated dev config, launchable on Linux. |
| `helao/deploy/hte/tests/test_ole_status.py` | Task 1 tests. |
| `helao/deploy/hte/tests/test_ole_mps_template.py` | Task 2 tests. |
| `helao/deploy/hte/tests/test_ole_technique.py` | Tasks 3 and 4 tests. |
| `helao/deploy/hte/tests/test_ole_client.py` | Task 5 tests. |
| `helao/deploy/hte/tests/test_ole_sim.py` | Task 6 tests. |
| `helao/deploy/hte/tests/test_ole_mpr_cursor.py` | Task 7 tests. |
| `helao/deploy/hte/tests/test_ole_driver.py` | Task 8 tests. |
| `helao/deploy/hte/tests/fixtures/ole/synthetic_CA.mps` | Test-only `.mps` fixture. |
| `helao/hexagon/tests/test_biologic_backend_select.py` | Task 10 tests. |
| `helao/hexagon/tests/test_biologic_ole_vendor_isolation.py` | Task 12 tests. |
| `helao/hexagon/tests/test_biologic_column_contract.py` | Task 13 tests. |

**Modified:**

| Path | Change |
|---|---|
| `helao/deploy/hte/drivers/pstat/biologic/enum.py` | Vendor import becomes lazy (Task 9). |
| `helao/deploy/hte/drivers/pstat/biologic/driver.py` | `setup()` coerces the range enums; accepts `output_dir` (Task 9). |
| `helao/deploy/hte/servers/action/biologic_server.py` | Drop endpoint coercion, add backend select, add `run_protocol` (Tasks 9–11). |
| `helao/hexagon/tests/test_biologic_disconnected_construct.py` | Cover `enum.py` and the OLE package (Task 12). |
| `helao/hexagon/tests/checklists/hte/_additions.json` | Record `/BIOLOGIC/run_protocol` (Task 11). |
| `CLAUDE.md` | Document the backend and its traps (Task 14). |

---

## Task 1: `status.py` — decode the MeasureStatus array

**Files:**
- Create: `helao/deploy/hte/drivers/pstat/biologic_ole/__init__.py`
- Create: `helao/deploy/hte/drivers/pstat/biologic_ole/status.py`
- Test: `helao/deploy/hte/tests/test_ole_status.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `ChannelState(IntEnum)`, `SafetyLimit(IntEnum)`, `ChannelStatus` (frozen dataclass with fields `state_raw: int`, `state: ChannelState | None`, `technique_index: int`, `technique_code: int`, `sequence_index: int`, `cycle: float`, `time_s: float`, `ewe_v: float`, `ece_v: float`, `eoc_v: float`, `i_a: float`, `irange_a: float`, `frequency_hz: float`, `z_ohm: float`, `point_index: int`, `total_point_index: int`, `safety_limit_raw: int`, `safety_limit: SafetyLimit | None`, `connected: bool`, `raw: tuple[float, ...]`, and properties `is_busy: bool`, `is_recording_tail: bool`), and `decode_status(values: Sequence[float]) -> ChannelStatus`.

- [ ] **Step 1: Write the failing tests**

Create `helao/deploy/hte/tests/test_ole_status.py`:

```python
"""Decoding EC-Lab's 32-real MeasureStatus array.

Index meanings are from the EC-Lab OLE COM User Manual v11.72 section 5.2.11.
The one judgement call encoded here: idle is *exactly* index 0 == 0. Every
other value -- including a value this table has never seen -- reads as busy,
because a future EC-Lab adding a state must not make a running channel look
finished.
"""

import pytest

from helao.deploy.hte.drivers.pstat.biologic_ole.status import (
    ChannelState,
    SafetyLimit,
    decode_status,
)


def _arr(**overrides) -> list[float]:
    """A 32-long all-zero status array with named indices overridden."""
    values = [0.0] * 32
    for idx, value in overrides.items():
        values[int(idx.removeprefix("i"))] = float(value)
    return values


def test_a_stopped_channel_is_not_busy():
    status = decode_status(_arr(i0=0))
    assert status.state is ChannelState.STOP
    assert status.is_busy is False


@pytest.mark.parametrize("state_value", [1, 2, 3, 4, 5, 6])
def test_every_non_stop_state_is_busy(state_value):
    status = decode_status(_arr(i0=state_value))
    assert status.is_busy is True


def test_stop_rec_states_are_flagged_as_the_recording_tail():
    """4 and 5 mean 'the last points are being recorded', not 'stopped'."""
    assert decode_status(_arr(i0=4)).is_recording_tail is True
    assert decode_status(_arr(i0=5)).is_recording_tail is True
    assert decode_status(_arr(i0=1)).is_recording_tail is False
    assert decode_status(_arr(i0=0)).is_recording_tail is False


def test_an_unknown_state_is_busy_and_keeps_its_raw_value():
    status = decode_status(_arr(i0=99))
    assert status.state is None
    assert status.state_raw == 99
    assert status.is_busy is True


def test_scalar_fields_land_on_their_documented_indices():
    status = decode_status(
        _arr(
            i4=3, i5=54, i6=2, i10=7, i15=1.5, i16=0.25, i17=-0.1, i18=0.4,
            i19=1e-3, i23=0.01, i25=1000.0, i26=52.5, i27=11, i28=38, i29=21.0,
        )
    )
    assert status.technique_index == 3
    assert status.technique_code == 54
    assert status.sequence_index == 2
    assert status.cycle == 7
    assert status.time_s == 1.5
    assert status.ewe_v == 0.25
    assert status.ece_v == -0.1
    assert status.eoc_v == 0.4
    assert status.i_a == 1e-3
    assert status.irange_a == 0.01
    assert status.frequency_hz == 1000.0
    assert status.z_ohm == 52.5
    assert status.point_index == 11
    assert status.total_point_index == 38


def test_safety_limit_decodes_and_zero_means_ok():
    assert decode_status(_arr(i30=0)).safety_limit is SafetyLimit.OK
    assert decode_status(_arr(i30=1)).safety_limit is SafetyLimit.EMAX
    assert decode_status(_arr(i30=9)).safety_limit is SafetyLimit.EWE_MAX_STACK


def test_an_unknown_safety_limit_keeps_its_raw_value():
    status = decode_status(_arr(i30=42))
    assert status.safety_limit is None
    assert status.safety_limit_raw == 42


def test_connection_index_is_inverted_because_zero_means_ok():
    assert decode_status(_arr(i31=0)).connected is True
    assert decode_status(_arr(i31=1)).connected is False


def test_a_wrong_length_array_is_refused():
    with pytest.raises(ValueError, match="32"):
        decode_status([0.0] * 31)


def test_the_raw_array_is_preserved_verbatim():
    values = _arr(i0=1, i15=3.25)
    assert decode_status(values).raw == tuple(values)
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest helao/deploy/hte/tests/test_ole_status.py -v`

Expected: collection error, `ModuleNotFoundError: No module named 'helao.deploy.hte.drivers.pstat.biologic_ole'`.

- [ ] **Step 3: Create the package and write `status.py`**

Create `helao/deploy/hte/drivers/pstat/biologic_ole/__init__.py`:

```python
"""BioLogic potentiostat driver over the EC-Lab OLE COM interface.

An alternative to the sibling ``biologic`` package, which drives the same
instruments through easy-biologic / EClib. This one pilots the EC-Lab
application, so it reaches any instrument and any technique EC-Lab supports --
at the cost of requiring EC-Lab installed, registered as an OLE COM server
(``ECLab /regserver``) and running on the same Windows host.

See ``docs/superpowers/specs/2026-09-07-biologic-olecom-driver-design.md``.
"""
```

Create `helao/deploy/hte/drivers/pstat/biologic_ole/status.py`:

```python
"""Decode the 32-real array returned by EC-Lab's ``MeasureStatus``.

Indices and value tables are from the EC-Lab OLE COM User Manual v11.72,
section 5.2.11. The array is positional and untyped on the wire, so this is
the only place in the package that knows what index means what.

Two decisions are deliberate:

* **Idle is exactly ``state_raw == 0``.** An unrecognized state -- a value a
  future EC-Lab introduces -- reads as busy and keeps its raw number. The
  alternative, raising or defaulting to idle, would either take a station down
  on a version bump or report a running channel as finished.
* **Fields the manual says are not reset stay as read.** Section 5.2.11 warns
  that ``Current point index`` and ``Total point index`` retain the previous
  technique's values until overwritten. Correcting for that is the caller's
  job, not the decoder's.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional

__all__ = ["ChannelState", "ChannelStatus", "SafetyLimit", "decode_status"]

#: Length of the status array. The manual specifies exactly 32 reals.
STATUS_LENGTH = 32


class ChannelState(IntEnum):
    """Value of status index 0 (manual section 5.2.11, table of statuses)."""

    STOP = 0
    RUN = 1
    PAUSE = 2
    SYNC = 3
    STOP_REC1 = 4
    STOP_REC2 = 5
    PAUSE_REC = 6


#: The two states that mean "running, and writing the technique's last
#: points". Treating either as finished truncates the tail of every record.
RECORDING_TAIL = frozenset({ChannelState.STOP_REC1, ChannelState.STOP_REC2})


class SafetyLimit(IntEnum):
    """Value of status index 30. Non-zero means a limit tripped."""

    OK = 0
    EMAX = 1
    EMIN = 2
    I = 3  # noqa: E741 - the manual's own name for this code
    Q_Q0 = 4
    EWE_MIN_STACK = 7
    ECE_MIN_STACK = 8
    EWE_MAX_STACK = 9
    ECE_MAX_STACK = 10


@dataclass(frozen=True)
class ChannelStatus:
    """One decoded ``MeasureStatus`` reading."""

    state_raw: int
    state: Optional[ChannelState]
    technique_index: int
    technique_code: int
    sequence_index: int
    cycle: float
    time_s: float
    ewe_v: float
    ece_v: float
    eoc_v: float
    i_a: float
    irange_a: float
    frequency_hz: float
    z_ohm: float
    point_index: int
    total_point_index: int
    safety_limit_raw: int
    safety_limit: Optional[SafetyLimit]
    connected: bool
    raw: tuple[float, ...]

    @property
    def is_busy(self) -> bool:
        """True unless the channel is exactly ``Stop``."""
        return self.state_raw != ChannelState.STOP

    @property
    def is_recording_tail(self) -> bool:
        """True in ``Stop_rec1`` / ``Stop_rec2`` -- running, finishing up."""
        return self.state in RECORDING_TAIL


def _enum_or_none(enum_cls, value: int):
    try:
        return enum_cls(value)
    except ValueError:
        return None


def decode_status(values: Sequence[float]) -> ChannelStatus:
    """Decode a raw ``MeasureStatus`` array.

    Args:
        values: The 32 reals EC-Lab returned, in order.

    Returns:
        The decoded reading, with the raw array preserved.

    Raises:
        ValueError: If ``values`` is not exactly 32 long. A short array means
            the call failed or the API changed, and guessing which indices
            survived would silently mis-read every field after the gap.
    """
    if len(values) != STATUS_LENGTH:
        raise ValueError(
            f"MeasureStatus returned {len(values)} values, expected {STATUS_LENGTH}"
        )
    raw = tuple(float(v) for v in values)
    state_raw = int(raw[0])
    safety_raw = int(raw[30])
    return ChannelStatus(
        state_raw=state_raw,
        state=_enum_or_none(ChannelState, state_raw),
        technique_index=int(raw[4]),
        technique_code=int(raw[5]),
        sequence_index=int(raw[6]),
        cycle=raw[10],
        time_s=raw[15],
        ewe_v=raw[16],
        ece_v=raw[17],
        eoc_v=raw[18],
        i_a=raw[19],
        irange_a=raw[23],
        frequency_hz=raw[25],
        z_ohm=raw[26],
        point_index=int(raw[27]),
        total_point_index=int(raw[28]),
        safety_limit_raw=safety_raw,
        safety_limit=_enum_or_none(SafetyLimit, safety_raw),
        connected=safety_raw is not None and int(raw[31]) == 0,
        raw=raw,
    )
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest helao/deploy/hte/tests/test_ole_status.py -v`

Expected: 15 passed (the parametrized state cases expand).

- [ ] **Step 5: Format and commit**

```bash
black helao/deploy/hte/drivers/pstat/biologic_ole/status.py \
      helao/deploy/hte/drivers/pstat/biologic_ole/__init__.py \
      helao/deploy/hte/tests/test_ole_status.py
git add helao/deploy/hte/drivers/pstat/biologic_ole/ \
        helao/deploy/hte/tests/test_ole_status.py
git commit -m "feat(hte): decode EC-Lab's 32-real channel status array

Idle is exactly index 0 == 0; an unrecognized state reads busy and keeps
its raw value, so a future EC-Lab state cannot make a running channel
look finished. Stop_rec1/Stop_rec2 are surfaced separately because they
mean 'writing the last points', not 'stopped'.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `mps_template.py` — read and patch `.mps` text

**Files:**
- Create: `helao/deploy/hte/drivers/pstat/biologic_ole/mps_template.py`
- Already present: `helao/deploy/hte/tests/fixtures/ole/{CV,TI_CV_TO,LSV}.mps` — **real GUI-authored EC-Lab v11.72 files from an SP-200**, committed as fixtures. `LSV.mps` is not a technique this backend runs; it is kept because it spells a caption `step percent` where `CV.mps` spells it `Step percent`, from the same EC-Lab build — the evidence that captions must be read, never derived
- Create: `helao/deploy/hte/tests/fixtures/ole/synthetic_CA.mps`
- Test: `helao/deploy/hte/tests/test_ole_mps_template.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `MpsDocument` (frozen dataclass, field `lines: tuple[str, ...]`), `MpsParameterNotFound(KeyError)`, `load(path: str | Path) -> MpsDocument`, `loads(text: str) -> MpsDocument`, `get_param(doc: MpsDocument, name: str, seq: int = 0) -> str`, `set_param(doc: MpsDocument, name: str, value: str, seq: int = 0) -> MpsDocument`, `n_sequences(doc: MpsDocument) -> int`, `render(doc: MpsDocument) -> str`, `write_patched(doc: MpsDocument, dest: str | Path) -> Path`.

**Context the implementer needs.** An EC-Lab `.mps` is plain text in **latin-1** (EC-Lab writes `µ` as the single byte 0xB5, so `unit Is  µA` is unreadable as UTF-8). After a header block it carries one `Technique : N` line per technique, the technique's short name, and then a **fixed-width** parameter table: the label occupies columns 0-19, each sequence value the 20 columns after it. Parse by column, never by splitting on a run of spaces — EC-Lab has a caption with two consecutive spaces (`unit  Ia`, on GEIS) and captions with single spaces everywhere (`E range min (V)`), so no gap width is safe. Patching must replace one column of one row and leave every other byte alone, because EC-Lab reads the file positionally and the surrounding header carries values this code has no business touching.

- [ ] **Step 1: Write the synthetic multi-sequence fixture**

Two **real** fixtures are already committed and are what most of these tests run against: `CV.mps` (one Cyclic Voltammetry technique) and `TI_CV_TO.mps` (Trigger In, CV, Trigger Out), both GUI-authored in EC-Lab v11.72 on an SP-200. Read one before writing any code — every trap this module handles was found by running a parser over them.

Neither has a *multi-sequence* technique, though, and column indexing has to be covered, so add one synthetic file. Write it with **CRLF terminators and 20-column padding**, or it will not parse:

```
EC-LAB SETTING FILE

Number of linked techniques : 2

Filename : C:\EC-Lab\Data\synthetic_CA.mps

Device : SP-300
Ecell ctrl range : min = -10.00 V, max = 10.00 V
Safety Limits :
	Do not start on E overload

Technique : 1
Chronoamperometry / Chronocoulometry
Ns                  0                   1
Ei (V)              0.000               0.500
vs.                 Eoc                 Eoc
ti (h:m:s)          00:00:10.0000       00:00:20.0000
Imax                pass                pass
unit Imax           mA                  mA
record              <I>                 <I>
dI                  10.000              10.000
unit dI             mA                  mA
dta (s)             0.0100              0.0100
E range min (V)     -10.000
E range max (V)     10.000
I Range             Auto
Bandwidth           4
goto Ns'            0
nc cycles           0

Technique : 2
Open Circuit Voltage
tR (h:m:s)          00:00:10.0000
dER/dt (mV/h)       0.0
record              Ewe
dER (mV)            10.00
dtR (s)             0.1000
E range min (V)     -10.000
E range max (V)     10.000
```

- [ ] **Step 2: Write the failing tests**

Create `helao/deploy/hte/tests/test_ole_mps_template.py`:

```python
"""Reading and patching EC-Lab .mps settings text.

.mps is the only way parameters reach a channel: LoadSettings takes a file
path and nothing in the OLE COM API builds a technique from arguments. So a
wrong substitution here is a wrong experiment on a real cell, with no error
from either EC-Lab or the API -- which is why this module is pure text with no
COM dependency, and why it is the most heavily tested unit in the package.

Most of these run against two **real GUI-authored files** rather than a
synthetic fixture. That matters: every one of the format's traps -- CRLF, the
latin-1 superscripts, a value containing a space, header lines shaped like
parameter rows, a caption repeated four times in one block -- was found by
running an earlier version of this parser over them, not by reading the
vendor manual.
"""

import io
from pathlib import Path

import pytest

from helao.deploy.hte.drivers.pstat.biologic_ole import mps_template as mt

FIXTURES = Path("helao/deploy/hte/tests/fixtures/ole")
CV = FIXTURES / "CV.mps"          # real: one Cyclic Voltammetry technique
TI_CV_TO = FIXTURES / "TI_CV_TO.mps"  # real: Trigger In, CV, Trigger Out
SYNTHETIC = FIXTURES / "synthetic_CA.mps"  # two sequence columns; see below


@pytest.fixture
def cv() -> mt.MpsDocument:
    return mt.load(CV)


@pytest.fixture
def triggered() -> mt.MpsDocument:
    return mt.load(TI_CV_TO)


@pytest.fixture
def doc() -> mt.MpsDocument:
    """The synthetic two-sequence CA file.

    Kept alongside the real ones because neither real file has a
    multi-sequence technique, and column indexing has to be covered.
    """
    return mt.load(SYNTHETIC)


# -- encoding and round-trip ------------------------------------------------


@pytest.mark.parametrize("path", [CV, TI_CV_TO])
def test_a_real_file_round_trips_byte_for_byte(path):
    """The whole patcher rests on this. CRLF and latin-1 both matter."""
    assert mt.render(mt.load(path)).encode(mt.ENCODING) == path.read_bytes()


@pytest.mark.parametrize("path", [CV, TI_CV_TO])
def test_the_real_files_are_not_utf8(path):
    """0xB2/0xB3 -- the superscripts in `0.001 cm²` and `0.001 cm³`."""
    with pytest.raises(UnicodeDecodeError):
        path.read_bytes().decode("utf-8")


@pytest.mark.parametrize("path", [CV, TI_CV_TO])
def test_the_real_files_use_crlf(path):
    raw = path.read_bytes()
    assert raw.count(b"\r\n") == raw.count(b"\n") > 0


def test_universal_newline_translation_would_break_the_round_trip():
    """Pins why load() passes newline="": the default silently rewrites CRLF.

    Without this test the bug reappears the moment someone simplifies load()
    back to Path.read_text(), and it fails nowhere visible -- the patched file
    just stops matching the one EC-Lab wrote.
    """
    with io.open(CV, "r", encoding=mt.ENCODING) as handle:  # newline=None
        translated = handle.read()
    assert mt.render(mt.loads(translated)).encode(mt.ENCODING) != CV.read_bytes()


def test_write_patched_preserves_crlf_and_high_bytes(tmp_path):
    dest = tmp_path / "out.mps"
    mt.write_patched(mt.load(CV), dest)
    assert dest.read_bytes() == CV.read_bytes()


# -- technique blocks -------------------------------------------------------


def test_a_single_technique_file_has_one_block(cv):
    blocks = mt.technique_blocks(cv)
    assert [b.name for b in blocks] == ["Cyclic Voltammetry"]
    assert mt.n_techniques(cv) == 1


def test_the_triggered_file_has_three_blocks_in_order(triggered):
    assert [b.name for b in mt.technique_blocks(triggered)] == [
        "Trigger In",
        "Cyclic Voltammetry",
        "Trigger Out",
    ]


def test_a_header_line_shaped_like_a_row_is_not_one(cv):
    """`Reference electrode : SCE ...` passes a naive column test.

    It is 19 characters, then a space at column 19 and a colon at 20 -- so an
    unscoped parser reads it as a row with seven columns, and n_sequences
    returns 7 for a single-sequence file.
    """
    with pytest.raises(mt.MpsParameterNotFound):
        mt.get_param(cv, "Reference electrode")
    with pytest.raises(mt.MpsParameterNotFound):
        mt.get_param(cv, "Characteristic mass")


def test_n_sequences_is_one_for_the_real_single_sequence_files(cv, triggered):
    assert mt.n_sequences(cv) == 1
    assert mt.n_sequences(triggered) == 1


# -- reading values ---------------------------------------------------------


def test_the_cv_vertices_read_back(cv):
    assert mt.get_param(cv, "Ei (V)") == "0.000"
    assert mt.get_param(cv, "E1 (V)") == "1.000"
    assert mt.get_param(cv, "E2 (V)") == "-1.000"
    assert mt.get_param(cv, "Ef (V)") == "0.000"


def test_the_scan_rate_is_a_magnitude_and_a_unit_row(cv):
    assert mt.get_param(cv, "dE/dt") == "20.000"
    assert mt.get_param(cv, "dE/dt unit") == "mV/s"


def test_bandwidth_reads_back_as_a_bare_integer(cv):
    assert mt.get_param(cv, "Bandwidth") == "8"


def test_a_label_containing_spaces_is_matched_whole(cv):
    """`E range min (V)` must not be confused with `E range max (V)`."""
    assert mt.get_param(cv, "E range min (V)") == "-2.500"
    assert mt.get_param(cv, "E range max (V)") == "2.500"


def test_a_value_containing_a_space_is_one_value_not_two_columns(triggered):
    """`Trigger  Rising Edge`. Splitting on whitespace yields two columns."""
    assert mt.get_param(triggered, "Trigger", technique=0) == "Rising Edge"
    assert mt.n_sequences(triggered, technique=0) == 1


# -- duplicate captions -----------------------------------------------------


def test_a_caption_repeated_within_one_block_needs_an_occurrence(cv):
    """Cyclic Voltammetry has four `vs.` rows, one per vertex."""
    assert [mt.get_param(cv, "vs.", occurrence=k) for k in range(4)] == [
        "Eoc",
        "Ref",
        "Ref",
        "Eoc",
    ]


def test_asking_past_the_last_occurrence_says_how_many_there_are(cv):
    with pytest.raises(mt.MpsParameterNotFound, match="occurs 4"):
        mt.get_param(cv, "vs.", occurrence=4)


def test_a_caption_repeated_across_blocks_is_selected_by_technique(triggered):
    """`Trigger` is in both the Trigger In and Trigger Out blocks."""
    assert mt.get_param(triggered, "Channel", technique=0) == "-1"
    assert mt.get_param(triggered, "td (h:m:s)", technique=2) == "0:00:0.0010"
    with pytest.raises(mt.MpsParameterNotFound, match="technique 0"):
        mt.get_param(triggered, "td (h:m:s)", technique=0)


def test_patching_without_a_technique_scope_hits_the_first_block(triggered):
    """Documented, not accidental -- and why the driver always passes one."""
    patched = mt.set_param(triggered, "Trigger", "Falling Edge")
    assert mt.get_param(patched, "Trigger", technique=0) == "Falling Edge"
    assert mt.get_param(patched, "Trigger", technique=2) == "Rising Edge"


def test_patching_a_scoped_row_leaves_its_namesakes_alone(triggered):
    patched = mt.set_param(triggered, "Trigger", "Falling Edge", technique=2)
    assert mt.get_param(patched, "Trigger", technique=0) == "Rising Edge"
    assert mt.get_param(patched, "Trigger", technique=2) == "Falling Edge"


# -- patching ---------------------------------------------------------------


def test_setting_a_parameter_changes_only_that_value(cv):
    patched = mt.set_param(cv, "E1 (V)", "0.750")
    assert mt.get_param(patched, "E1 (V)") == "0.750"
    assert mt.get_param(patched, "E2 (V)") == "-1.000"
    assert mt.get_param(patched, "Bandwidth") == "8"


def test_patching_changes_exactly_one_line_and_no_others(cv):
    before = mt.render(cv).splitlines()
    after = mt.render(mt.set_param(cv, "E1 (V)", "0.750")).splitlines()
    differing = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
    assert len(differing) == 1
    assert len(before) == len(after)


def test_a_patched_row_keeps_its_trailing_padding(cv):
    """EC-Lab pads the value column to 20. rstrip breaks byte-identity."""
    patched = mt.set_param(cv, "E1 (V)", "0.750")
    line = [l for l in patched.lines if l.startswith("E1 (V)")][0]
    assert line.rstrip("\r\n") == "E1 (V)".ljust(20) + "0.750".ljust(20)


def test_a_same_width_patch_preserves_the_file_length(cv):
    patched = mt.set_param(cv, "E1 (V)", "0.750")
    assert len(mt.render(patched)) == len(mt.render(cv))


def test_the_document_is_immutable(cv):
    before = mt.render(cv)
    mt.set_param(cv, "E1 (V)", "0.750")
    assert mt.render(cv) == before


def test_an_absent_parameter_names_itself(cv):
    with pytest.raises(mt.MpsParameterNotFound, match="Nonesuch"):
        mt.get_param(cv, "Nonesuch")


def test_a_caption_longer_than_the_label_field_is_refused(cv):
    with pytest.raises(mt.MpsParameterNotFound, match="20-column"):
        mt.set_param(cv, "a" * 21, "1")


# -- multiple sequence columns ---------------------------------------------


def test_a_multi_sequence_parameter_reads_the_requested_column(doc):
    assert mt.get_param(doc, "Ei (V)", seq=0) == "0.000"
    assert mt.get_param(doc, "Ei (V)", seq=1) == "0.500"


def test_setting_one_sequence_leaves_the_other_alone(doc):
    patched = mt.set_param(doc, "Ei (V)", "1.250", seq=1)
    assert mt.get_param(patched, "Ei (V)", seq=0) == "0.000"
    assert mt.get_param(patched, "Ei (V)", seq=1) == "1.250"


def test_a_column_beyond_the_row_is_refused(doc):
    with pytest.raises(mt.MpsParameterNotFound, match="no seq 5"):
        mt.get_param(doc, "Ei (V)", seq=5)


def test_n_sequences_counts_the_widest_parameter_row(doc):
    assert mt.n_sequences(doc) == 2


def test_write_patched_creates_parents_and_returns_the_path(tmp_path, cv):
    dest = tmp_path / "nested" / "out.mps"
    written = mt.write_patched(mt.set_param(cv, "Bandwidth", "7"), dest)
    assert written == dest
    assert mt.get_param(mt.load(dest), "Bandwidth") == "7"


def test_loads_accepts_text_directly():
    doc = mt.loads("Technique : 1\r\nOCV\r\n" + "tR (h:m:s)".ljust(20) + "0:00:5.0000\r\n")
    assert mt.get_param(doc, "tR (h:m:s)") == "0:00:5.0000"
```

- [ ] **Step 3: Run the tests and verify they fail**

Run: `pytest helao/deploy/hte/tests/test_ole_mps_template.py -v`

Expected: collection error, `ImportError: cannot import name 'mps_template'`.

- [ ] **Step 4: Write `mps_template.py`**

```python
"""Read and patch EC-Lab ``.mps`` settings text.

``LoadSettings(dev, ch, FileName)`` is the only route from parameters to a
channel -- the OLE COM API has no function that builds a technique from
arguments -- so every parameterised endpoint patches a template and hands
EC-Lab the result.

Everything below was verified against two real GUI-authored files
(``tests/fixtures/ole/CV.mps`` and ``TI_CV_TO.mps``, EC-Lab v11.72, SP-200).
Five properties of the format each break a reasonable implementation, and
none of them announces itself:

* **latin-1, CRLF.** The files are ISO-8859 with ``\r\n`` terminators, and
  they really do carry high bytes -- 0xB2 and 0xB3, the superscripts in
  ``0.001 cm²`` and ``0.001 cm³``. ``read_text()`` without ``newline=""``
  silently rewrites CRLF to LF, so the round-trip is not byte-identical; on
  Windows the write side then turns LF back into CRLF and a naive read/write
  cycle doubles nothing but a patched one loses the file's own line endings.
* **Fixed-width columns.** Label in columns 0-19, each sequence value in the
  20 after it, trailing padding included. The padding must be preserved:
  ``rstrip``-ing a rebuilt row breaks byte-identity against the original.
* **Values can contain spaces.** ``Trigger  Rising Edge`` is one value, not
  two sequence columns, so the value field is *sliced* by column rather than
  split on whitespace.
* **Header lines can look exactly like parameter rows.**
  ``Reference electrode : SCE ...`` and ``Characteristic mass : 0.001 g`` both
  pass a naive column test and were mis-parsed as rows in the real files. The
  parameter table only exists *inside* technique blocks, so parsing is scoped
  to them.
* **Captions are not unique.** ``vs.`` appears **four times** in a single
  Cyclic Voltammetry block (once per vertex), and ``Trigger`` appears in both
  the Trigger In and Trigger Out blocks of a three-technique file. A
  first-match lookup patches the wrong row, so every accessor takes an
  optional ``technique`` scope and an ``occurrence`` index.
"""

import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

__all__ = [
    "COLUMN_WIDTH",
    "ENCODING",
    "MpsDocument",
    "MpsParameterNotFound",
    "TechniqueBlock",
    "get_param",
    "load",
    "loads",
    "n_sequences",
    "n_techniques",
    "render",
    "set_param",
    "technique_blocks",
    "write_patched",
]

#: The parameter table is fixed-width: EC-Lab pads each label to 20 columns
#: and each value to 20 after it.
COLUMN_WIDTH = 20

#: ``.mps`` files are latin-1 / cp1252, **not** UTF-8. Verified: the real
#: files carry 0xB2 and 0xB3 (``cm²``, ``cm³``) and fail to decode as UTF-8.
#: latin-1 is chosen over cp1252 deliberately -- it round-trips every byte
#: 0x00-0xFF losslessly, which is what a patcher that must not disturb bytes
#: it was not asked about actually needs.
ENCODING = "latin-1"

#: Line terminators are CRLF and must survive untouched, so every open()
#: disables universal-newline translation.
NEWLINE = ""

_TECHNIQUE_LINE = re.compile(r"^Technique : (\d+)")


class MpsParameterNotFound(KeyError):
    """A parameter row -- or a column, occurrence or technique of one."""


@dataclass(frozen=True)
class TechniqueBlock:
    """One ``Technique : N`` section's extent within a document.

    Attributes:
        index: 0-based position in the file. Not the ``N`` in the header
            line, which is 1-based and which a hand-assembled file may have
            got wrong -- position is what actually orders the techniques.
        name: The technique name line, e.g. ``"Cyclic Voltammetry"``.
        start: Index of the ``Technique : N`` line.
        stop: Index one past the block's last line.
    """

    index: int
    name: str
    start: int
    stop: int


@dataclass(frozen=True)
class MpsDocument:
    """The lines of an ``.mps`` file, held verbatim with line endings.

    Immutable: ``set_param`` returns a new document. A patcher that mutated in
    place would let one action's substitution leak into the next action that
    reused the loaded template.
    """

    lines: tuple[str, ...]


def loads(text: str) -> MpsDocument:
    """Parse ``.mps`` text. ``keepends`` preserves the original terminators."""
    return MpsDocument(lines=tuple(text.splitlines(keepends=True)))


def load(path: Union[str, Path]) -> MpsDocument:
    """Read an ``.mps`` file. See ``ENCODING`` and ``NEWLINE``."""
    with io.open(path, "r", encoding=ENCODING, newline=NEWLINE) as handle:
        return loads(handle.read())


def render(doc: MpsDocument) -> str:
    """Reassemble the document. Byte-identical to the input when unpatched."""
    return "".join(doc.lines)


def technique_blocks(doc: MpsDocument) -> list[TechniqueBlock]:
    """Every ``Technique : N`` block, in file order."""
    starts = [
        index
        for index, line in enumerate(doc.lines)
        if _TECHNIQUE_LINE.match(line.rstrip("\r\n"))
    ]
    blocks = []
    for position, start in enumerate(starts):
        stop = starts[position + 1] if position + 1 < len(starts) else len(doc.lines)
        name = doc.lines[start + 1].strip() if start + 1 < len(doc.lines) else ""
        blocks.append(TechniqueBlock(position, name, start, stop))
    return blocks


def n_techniques(doc: MpsDocument) -> int:
    """How many technique blocks the document holds."""
    return len(technique_blocks(doc))


def _row(line: str) -> Optional[tuple[str, list[str]]]:
    """Split a parameter row into ``(label, columns)``, or None if not one.

    A row qualifies only when the label is padded to exactly ``COLUMN_WIDTH``
    -- column 19 a space, column 20 not. Values are then sliced by column,
    never split on whitespace: ``Trigger  Rising Edge`` is one value.
    """
    body = line.rstrip("\r\n")
    if len(body) <= COLUMN_WIDTH:
        return None
    if body[0] == " " or body[COLUMN_WIDTH - 1] != " " or body[COLUMN_WIDTH] == " ":
        return None
    label = body[:COLUMN_WIDTH].rstrip()
    if not label:
        return None
    rest = body[COLUMN_WIDTH:]
    columns = [
        rest[i : i + COLUMN_WIDTH].strip() for i in range(0, len(rest), COLUMN_WIDTH)
    ]
    while columns and columns[-1] == "":
        columns.pop()
    return (label, columns) if columns else None


def _find_row(
    doc: MpsDocument,
    name: str,
    technique: Optional[int] = None,
    occurrence: int = 0,
) -> tuple[int, list[str]]:
    """Locate one parameter row.

    Scoped to technique blocks, so a header line that happens to look like a
    row -- ``Reference electrode : SCE ...`` does -- is never a candidate.

    Raises:
        MpsParameterNotFound: If no such row, or fewer occurrences than asked.
    """
    hits: list[tuple[int, list[str]]] = []
    for block in technique_blocks(doc):
        if technique is not None and block.index != technique:
            continue
        for index in range(block.start, block.stop):
            parsed = _row(doc.lines[index])
            if parsed is not None and parsed[0] == name:
                hits.append((index, parsed[1]))
    if not hits:
        scope = "" if technique is None else f" in technique {technique}"
        raise MpsParameterNotFound(f"no parameter row labelled {name!r}{scope}")
    if occurrence >= len(hits):
        raise MpsParameterNotFound(
            f"parameter {name!r} occurs {len(hits)} time(s), no occurrence "
            f"{occurrence}"
        )
    return hits[occurrence]


def get_param(
    doc: MpsDocument,
    name: str,
    seq: int = 0,
    technique: Optional[int] = None,
    occurrence: int = 0,
) -> str:
    """The value of parameter ``name`` in sequence column ``seq``.

    Args:
        doc: The document to read.
        name: The parameter's caption, exactly as the file spells it.
        seq: Which sequence column, 0-based.
        technique: Restrict to one technique block by position, 0-based.
        occurrence: Which matching row, when the caption repeats. Cyclic
            Voltammetry has four ``vs.`` rows, one per vertex.

    Raises:
        MpsParameterNotFound: If the row, occurrence or column is absent.
    """
    _, columns = _find_row(doc, name, technique, occurrence)
    if seq >= len(columns):
        raise MpsParameterNotFound(
            f"parameter {name!r} has {len(columns)} column(s), no seq {seq}"
        )
    return columns[seq]


def set_param(
    doc: MpsDocument,
    name: str,
    value: str,
    seq: int = 0,
    technique: Optional[int] = None,
    occurrence: int = 0,
) -> MpsDocument:
    """A copy of ``doc`` with one column of one parameter row replaced.

    The row is rebuilt at 20-column spacing **including its trailing
    padding**, which is what EC-Lab itself writes and what keeps an unpatched
    render byte-identical to the file that was loaded.

    Raises:
        MpsParameterNotFound: If the row, occurrence or column is absent, or
            the caption is too long for the label field.
    """
    if len(name) > COLUMN_WIDTH:
        # EC-Lab pads to 20; a longer label leaves the value with no separator
        # and makes the row unparseable on the next read.
        raise MpsParameterNotFound(
            f"parameter {name!r} exceeds the {COLUMN_WIDTH}-column label field"
        )
    index, columns = _find_row(doc, name, technique, occurrence)
    if seq >= len(columns):
        raise MpsParameterNotFound(
            f"parameter {name!r} has {len(columns)} column(s), no seq {seq}"
        )
    original = doc.lines[index]
    ending = original[len(original.rstrip("\r\n")) :]
    columns = list(columns)
    columns[seq] = value
    rebuilt = name.ljust(COLUMN_WIDTH) + "".join(
        column.ljust(COLUMN_WIDTH) for column in columns
    )
    lines = list(doc.lines)
    lines[index] = rebuilt + ending
    return MpsDocument(lines=tuple(lines))


def n_sequences(doc: MpsDocument, technique: Optional[int] = None) -> int:
    """The widest parameter row's column count -- the sequence count.

    Scoped to technique blocks, so header lines cannot inflate it. On the real
    ``CV.mps`` an unscoped count returns 7, from
    ``Reference electrode : SCE Saturated Calomel Electrode (0.241 V)``.
    """
    widest = 0
    for block in technique_blocks(doc):
        if technique is not None and block.index != technique:
            continue
        for index in range(block.start, block.stop):
            parsed = _row(doc.lines[index])
            if parsed is not None:
                widest = max(widest, len(parsed[1]))
    return widest


def write_patched(doc: MpsDocument, dest: Union[str, Path]) -> Path:
    """Write ``doc`` to ``dest``, creating parent directories.

    Written directly rather than through the repo's ``.tmp`` atomic-write
    staging convention, because the destination is a scratch directory the
    syncer never globs, and because ``LoadSettings`` needs a final name.
    """
    path = Path(dest)
    path.parent.mkdir(parents=True, exist_ok=True)
    with io.open(path, "w", encoding=ENCODING, newline=NEWLINE) as handle:
        handle.write(render(doc))
    return path
```

- [ ] **Step 5: Run the tests and verify they pass**

Run: `pytest helao/deploy/hte/tests/test_ole_mps_template.py -v`

Expected: 35 passed. If a real-file round-trip test fails, the fixture's trailing newline is being dropped — `splitlines(keepends=True)` plus `"".join` is exact, so investigate the fixture rather than relaxing the assertion. This test is the guard that the patcher never reflows a file it was not asked to change.

- [ ] **Step 6: Format and commit**

```bash
black helao/deploy/hte/drivers/pstat/biologic_ole/mps_template.py \
      helao/deploy/hte/tests/test_ole_mps_template.py
git add helao/deploy/hte/drivers/pstat/biologic_ole/mps_template.py \
        helao/deploy/hte/tests/test_ole_mps_template.py \
        helao/deploy/hte/tests/fixtures/ole/synthetic_CA.mps
git commit -m "feat(hte): patch EC-Lab .mps settings text

LoadSettings takes a file and the OLE COM API builds no technique from
arguments, so .mps patching is the transport for every parameterised
endpoint. Rows are labelled by the text before the first two-space run --
one space would truncate 'E range min (V)' -- and an unpatched render is
byte-identical to the input.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `technique.py` — the technique registry

**Files:**
- Create: `helao/deploy/hte/drivers/pstat/biologic_ole/technique.py`
- Test: `helao/deploy/hte/tests/test_ole_technique.py`

**Interfaces:**
- Consumes: nothing at runtime (it names template files but does not open them).
- Produces: `MpsParam` (frozen dataclass: `param_id: str`, `unit_param_id: str | None = None`, `unit: str | None = None`, `fmt: str = "{}"`), `ColumnPlan` (frozen dataclass: `kind: Literal["dc", "eis"]`, `var_codes: dict[str, int]`, `derived: tuple[str, ...]`), `OleTechnique` (frozen dataclass: `technique_name: str`, `template: str`, `parameter_map: dict[str, MpsParam]`, `column_plan: ColumnPlan`, `technique_codes: frozenset[int]`), `OLE_TECHS: dict[str, OleTechnique]`, `resolve(name: str) -> OleTechnique`, `columns(plan: ColumnPlan) -> tuple[str, ...]`, and the module constants `DC_COLUMNS`, `EIS_COLUMNS`, `VAR_CODES`.

**Context the implementer needs.** The emitted column names must match the sibling `biologic/technique.py` registry's `field_map` *values* exactly — that is the frozen contract Task 13 pins. EC-Lab variable codes come from the manual's appendix 7.2; technique codes from appendix 7.1, which lists two families, so `CA` is both 24 and 54, `OCV` 11 and 55, `CP` 25 and 56, `CV` 6 and 57, `PEIS` 29 and 60, `GEIS` 30 and 61. Which one a template yields depends on the template, so both are accepted and the driver asserts membership rather than equality.

- [ ] **Step 1: Write the failing tests**

Create `helao/deploy/hte/tests/test_ole_technique.py`:

```python
"""The OLE technique registry, and its agreement with the eclib registry.

The registry is what turns a HELAO action parameter into an .mps parameter
caption and an emitted column into an EC-Lab variable code. Both halves are
silent when wrong: a bad caption patches nothing and runs the template's
default on a real cell; a bad code returns a different quantity under the
right column name.
"""

import pytest

from pathlib import Path

from helao.deploy.hte.drivers.pstat.biologic.technique import BIOTECHS
from helao.deploy.hte.drivers.pstat.biologic_ole import technique as ot

TECHNIQUE_NAMES = ["OCV", "CA", "CP", "CV", "PEIS", "GEIS", "CAOCV"]
TEMPLATES = Path("helao/deploy/hte/drivers/pstat/biologic_ole/templates")
FIXTURES = Path("helao/deploy/hte/tests/fixtures/ole")


def test_every_eclib_technique_has_an_ole_counterpart():
    assert sorted(ot.OLE_TECHS) == sorted(BIOTECHS)


@pytest.mark.parametrize("name", TECHNIQUE_NAMES)
def test_resolve_returns_the_named_technique(name):
    assert ot.resolve(name).technique_name == name


def test_an_unknown_technique_names_itself_and_the_alternatives():
    with pytest.raises(ValueError, match="SWV"):
        ot.resolve("SWV")


@pytest.mark.parametrize("name", TECHNIQUE_NAMES)
def test_every_technique_names_a_template_file(name):
    assert ot.resolve(name).template.endswith(".mps")


#: X_ohm and R_ohm are part of the frozen EIS contract but are NOT in the
#: eclib registry's field_map -- that driver computes them in get_data from
#: modulus and phase, after remapping. The OLE side declares them in its
#: column plan instead, because it gets them straight off MeasureEisValue.
#: Same emitted columns, declared in different places.
ECLIB_DERIVED_IN_CODE = {"X_ohm", "R_ohm"}


def eclib_columns(name: str) -> set:
    columns = set(BIOTECHS[name].field_map.values())
    if "modulus" in columns:
        columns |= ECLIB_DERIVED_IN_CODE
    return columns


@pytest.mark.parametrize("name", TECHNIQUE_NAMES)
def test_emitted_columns_match_the_eclib_field_map(name):
    """The frozen contract: both backends emit the same column key set."""
    expected = eclib_columns(name)
    ole_columns = set(ot.columns(ot.resolve(name).column_plan))
    assert ole_columns == expected, {
        "only_eclib": sorted(expected - ole_columns),
        "only_ole": sorted(ole_columns - expected),
    }


@pytest.mark.parametrize("name", ["CA", "CP", "CV", "CAOCV"])
def test_dc_techniques_fetch_nothing_by_code(name):
    """A DC point costs one MeasureDcValue call and no MeasureValueByCode.

    `derived` means "not fetched by variable code" -- it holds both the three
    columns MeasureDcValue returns directly and the two computed from them.
    What matters is that `var_codes` is empty: P_W is |Ewe*I|, which is
    EC-Lab's own definition of variable 70, and cycle comes from the status
    array, so fetching either would cost a round trip per point to learn a
    number we already have.
    """
    plan = ot.resolve(name).column_plan
    assert plan.kind == "dc"
    assert plan.var_codes == {}
    assert {"P_W", "cycle"} <= set(plan.derived)


@pytest.mark.parametrize("name", ["PEIS", "GEIS"])
def test_eis_techniques_derive_the_impedance_pair_and_process(name):
    plan = ot.resolve(name).column_plan
    assert plan.kind == "eis"
    assert set(plan.derived) == {"X_ohm", "R_ohm", "process", "t_s", "f_Hz"}


def test_ocv_emits_only_time_and_potential():
    """MeasureDcValue's current is documented as always zero for OCV."""
    assert set(ot.columns(ot.resolve("OCV").column_plan)) == {"t_s", "Ewe_V"}


@pytest.mark.parametrize(
    "name,codes",
    [
        ("OCV", {11, 55}),
        ("CA", {24, 54}),
        ("CP", {25, 56}),
        ("CV", {6, 57}),
        ("PEIS", {29, 60}),
        ("GEIS", {30, 61}),
    ],
)
def test_both_technique_code_families_are_accepted(name, codes):
    """Appendix 7.1 lists each of these techniques twice, under two codes."""
    assert ot.resolve(name).technique_codes == frozenset(codes)


def test_caocv_accepts_both_its_constituent_techniques():
    assert ot.resolve("CAOCV").technique_codes >= {24, 54, 11, 55}


@pytest.mark.parametrize("name", TECHNIQUE_NAMES)
def test_every_action_parameter_the_eclib_registry_maps_is_also_mapped(name):
    """A parameter eclib forwards but OLE drops would silently run a default.

    ERange is the one exception, and it is handled rather than dropped: it is
    not a single .mps row but a symmetric min/max pair, so the driver applies
    it through `erange_rows`. `test_erange_is_applied_as_a_min_max_pair`
    covers it.
    """
    eclib_keys = set(BIOTECHS[name].parameter_map)
    ole_keys = set(ot.resolve(name).parameter_map)
    handled_elsewhere = {"ERange", "CA_ERange"}
    if name == "CV":
        # EC-Lab's CV has no dE (mV) row at all -- see the registry comment.
        handled_elsewhere = handled_elsewhere | {"AcqInterval__V"}
    assert eclib_keys - ole_keys <= handled_elsewhere, sorted(
        eclib_keys - ole_keys - handled_elsewhere
    )


def test_erange_is_applied_as_a_min_max_pair():
    """EC-Lab has no 'E range' row; the window is two symmetric rows."""
    assert ot.erange_rows("v2_5") == {
        "E range min (V)": "-2.500",
        "E range max (V)": "2.500",
    }
    assert ot.erange_rows("v10") == {
        "E range min (V)": "-10.000",
        "E range max (V)": "10.000",
    }


def test_auto_erange_writes_nothing_rather_than_guessing():
    """AUTO has no numeric equivalent; the template's own window stands."""
    assert ot.erange_rows("AUTO") == {}
    assert ot.erange_rows("nonsense") == {}


def test_cv_does_not_map_a_voltage_recording_interval():
    """EC-Lab's CV has no `dE (mV)` row; Step percent and N govern it.

    Pinned as a test rather than left implicit, because the obvious fix --
    inventing a `dE (mV)` mapping -- silently changes the sampling of every
    CV the station runs.
    """
    assert "AcqInterval__V" not in ot.resolve("CV").parameter_map


#: Every technique in the registry has a real GUI-authored template
#: committed, so the caption guard below covers the whole surface.
TEMPLATED = ["OCV", "CA", "CP", "CV", "PEIS", "GEIS", "CAOCV"]


@pytest.mark.parametrize("name", TEMPLATED)
def test_every_caption_exists_in_the_real_template(name):
    """The guard the whole registry rests on, and it runs on Linux.

    Each caption is read off a GUI-authored EC-Lab v11.72 file rather than
    inferred. A caption that drifts -- or a template replaced by one from a
    different EC-Lab version that renamed a row -- fails here instead of at a
    station, where the symptom is an experiment that ran on the template's
    defaults with nothing to show it.
    """
    from helao.deploy.hte.drivers.pstat.biologic_ole import mps_template as mt

    tech = ot.resolve(name)
    doc = mt.load(TEMPLATES / tech.template)
    for key, param in tech.parameter_map.items():
        mt.get_param(doc, param.param_id, technique=param.technique)
        if param.unit_param_id:
            mt.get_param(doc, param.unit_param_id, technique=param.technique)


@pytest.mark.parametrize("name", TEMPLATED)
def test_the_erange_pair_exists_in_every_real_template(name):
    """erange_rows writes both, and OCV has them despite having no I Range."""
    from helao.deploy.hte.drivers.pstat.biologic_ole import mps_template as mt

    doc = mt.load(TEMPLATES / ot.resolve(name).template)
    for caption in ("E range min (V)", "E range max (V)"):
        mt.get_param(doc, caption)


def test_caocv_is_the_only_two_technique_template():
    from helao.deploy.hte.drivers.pstat.biologic_ole import mps_template as mt

    counts = {
        name: mt.n_techniques(mt.load(TEMPLATES / ot.resolve(name).template))
        for name in TEMPLATED
    }
    assert counts.pop("CAOCV") == 2
    assert set(counts.values()) == {1}, counts


def test_caocv_scoping_is_not_optional():
    """Both of its blocks carry `E range min (V)`, `E range max (V)`, `record`.

    Unscoped, every one of those patches lands in the CA block and the OCV
    step silently keeps the template's values.
    """
    from helao.deploy.hte.drivers.pstat.biologic_ole import mps_template as mt

    doc = mt.load(TEMPLATES / "CAOCV.mps")
    for caption in ("E range min (V)", "E range max (V)", "record"):
        mt.get_param(doc, caption, technique=0)
        mt.get_param(doc, caption, technique=1)


def test_every_caocv_parameter_declares_its_block():
    for key, param in ot.resolve("CAOCV").parameter_map.items():
        assert param.technique in (0, 1), (key, param.technique)
        assert param.technique == (0 if key.startswith("CA_") else 1), key


def test_the_templates_agree_on_one_eclab_version():
    """A template from another build may have renamed a row silently."""
    from helao.deploy.hte.drivers.pstat.biologic_ole import mps_template as mt

    versions = set()
    for path in sorted(TEMPLATES.glob("*.mps")):
        for line in mt.load(path).lines:
            if line.startswith("EC-LAB for windows"):
                versions.add(line.strip())
                break
    assert len(versions) == 1, versions


def test_captions_are_case_sensitive_and_inconsistent_across_techniques():
    """CV spells it `Step percent`; LSV spells it `step percent`.

    Both are real, in files from the same EC-Lab build. This is why every
    caption is read from a template rather than derived from a convention.
    """
    from helao.deploy.hte.drivers.pstat.biologic_ole import mps_template as mt

    cv = mt.load(FIXTURES / "CV.mps")
    lsv = mt.load(FIXTURES / "LSV.mps")
    assert mt.get_param(cv, "Step percent") == "50"
    assert mt.get_param(lsv, "step percent") == "50"
    with pytest.raises(mt.MpsParameterNotFound):
        mt.get_param(cv, "step percent")


def test_the_scan_rate_scales_to_the_unit_the_template_carries():
    """The real file holds `dE/dt 20.000` with `dE/dt unit mV/s`."""
    assert ot.scale_to_unit(0.02, "V/s") == ("20.000", "mV/s")


def test_no_technique_maps_erange_to_a_single_caption():
    """Writing 'AUTO' into a field EC-Lab reads as a voltage is the trap."""
    for tech in ot.OLE_TECHS.values():
        assert "ERange" not in tech.parameter_map, tech.technique_name
        assert "CA_ERange" not in tech.parameter_map, tech.technique_name


def test_a_scaled_parameter_declares_a_unit_row_and_a_base_unit():
    """EC-Lab writes a current as a magnitude row plus a unit row."""
    param = ot.resolve("CP").parameter_map["Ival__A"]
    assert param.param_id == "Is"
    assert param.unit_param_id == "unit Is"
    assert param.base_unit == "A"


def test_geis_spells_its_amplitude_unit_row_with_two_spaces():
    """`unit  Ia` is EC-Lab's own spelling, not a typo here."""
    assert ot.resolve("GEIS").parameter_map["Iamp__A"].unit_param_id == "unit  Ia"


def test_scale_to_unit_keeps_a_microamp_out_of_the_third_decimal():
    """Unscaled, 1 uA formats to 0.000 -- the whole reason this exists."""
    assert ot.scale_to_unit(1e-6, "A") == ("1.000", "\u00b5A")
    assert ot.scale_to_unit(-2.5e-3, "A") == ("-2.500", "mA")
    assert ot.scale_to_unit(1.0, "A") == ("1.000", "A")
    assert ot.scale_to_unit(1e6, "Hz") == ("1.000", "MHz")
    assert ot.scale_to_unit(1000.0, "Hz") == ("1.000", "kHz")
    assert ot.scale_to_unit(0.0, "A") == ("0.000", "A")


def test_the_micro_prefix_is_the_single_latin1_byte():
    """0xB5, not the UTF-8 two-byte sequence EC-Lab would not recognise."""
    _, unit = ot.scale_to_unit(1e-6, "A")
    assert unit.encode("latin-1") == b"\xb5A"


def test_bandwidth_is_written_as_an_integer():
    """"BW4" loads fine and runs at the template's bandwidth instead."""
    assert ot.format_value("BW4", "bandwidth") == "4"
    assert ot.format_value("BW7", "bandwidth") == "7"
    assert ot.resolve("CA").parameter_map["Bandwidth"].fmt == "bandwidth"


def test_a_volts_parameter_landing_in_a_millivolt_row_is_scaled():
    assert ot.format_value(0.01, "V_to_mV") == "10.000"
    assert ot.resolve("PEIS").parameter_map["Vamp__V"].param_id == "Va (mV)"
    assert ot.resolve("PEIS").parameter_map["Vamp__V"].fmt == "V_to_mV"


def test_the_current_range_is_written_as_eclabs_display_string():
    """The real templates hold `Auto`, `100 µA`, `1 mA` -- not `u100`."""
    assert ot.format_value("AUTO", "irange") == "Auto"
    assert ot.format_value("u100", "irange") == "100 \u00b5A"
    assert ot.format_value("m1", "irange") == "1 mA"
    assert ot.resolve("CA").parameter_map["IRange"].fmt == "irange"


def test_an_irange_eclab_cannot_spell_is_refused():
    """KEEP and BOOSTER have no observed spelling; guessing one is worse."""
    for alias in ("KEEP", "BOOSTER", "nonsense"):
        with pytest.raises(ValueError, match=alias):
            ot.format_value(alias, "irange")


def test_every_irange_spelling_uses_the_latin1_micro_sign():
    for alias in ("u1", "u10", "u100"):
        assert ot.IRANGE_VALUES[alias].encode("latin-1").count(b"\xb5") == 1


def test_the_sweep_mode_row_is_spacing_and_its_values_are_words():
    assert ot.resolve("PEIS").parameter_map["SweepMode"].param_id == "spacing"
    assert ot.format_value("log", "spacing") == "Logarithmic"
    assert ot.format_value("lin", "spacing") == "Linear"


def test_variable_codes_are_the_documented_ones():
    """Appendix 7.2. A wrong code returns a different quantity, silently."""
    assert ot.VAR_CODES["t_s"] == 4
    assert ot.VAR_CODES["Ewe_V"] == 6
    assert ot.VAR_CODES["I_A"] == 8
    assert ot.VAR_CODES["Ece_V"] == 9
    assert ot.VAR_CODES["f_Hz"] == 32
    assert ot.VAR_CODES["AbsEwe_V"] == 33
    assert ot.VAR_CODES["AbsI_A"] == 34
    assert ot.VAR_CODES["phase"] == 35
    assert ot.VAR_CODES["modulus"] == 36
    assert ot.VAR_CODES["AbsEce_V"] == 96
    assert ot.VAR_CODES["AbsIce_A"] == 97
    assert ot.VAR_CODES["phase_ce"] == 98
    assert ot.VAR_CODES["modulus_ce"] == 99
    assert ot.VAR_CODES["P_W"] == 70
    assert ot.VAR_CODES["cycle"] == 24


def test_no_module_scope_vendor_import():
    import sys

    assert "comtypes" not in sys.modules
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest helao/deploy/hte/tests/test_ole_technique.py -v`

Expected: collection error, `ImportError: cannot import name 'technique'`.

- [ ] **Step 3: Write `technique.py`**

```python
"""What each technique needs: a template, a parameter map, a column plan.

Two mappings live here and both are silent when wrong.

* **Parameter map** -- HELAO action key to ``.mps`` parameter caption. A wrong
  or missing caption patches nothing, so the template's own default runs on a
  real cell with no error from EC-Lab or from the API.
* **Column plan** -- emitted HELAO column to EC-Lab variable code (appendix
  7.2 of the OLE COM manual). A wrong code returns a different quantity under
  the right column name.

Technique codes come from appendix 7.1, which lists most techniques **twice**
under two families -- CA is 24 and 54, OCV 11 and 55, and so on. Which one a
template yields depends on the template, so both are accepted and the driver
checks membership after ``LoadSettings`` rather than equality.

The emitted column set must equal the sibling ``biologic/technique.py``
registry's ``field_map`` values; ``test_ole_technique.py`` and
``test_biologic_column_contract.py`` both pin that.
"""

from dataclasses import dataclass, field
from typing import Literal, Optional

__all__ = [
    "BANDWIDTH_VALUES",
    "ColumnPlan",
    "DC_COLUMNS",
    "EIS_COLUMNS",
    "ERANGE_VOLTS",
    "MpsParam",
    "OLE_TECHS",
    "OleTechnique",
    "SPACING_VALUES",
    "UNIT_PREFIXES",
    "IRANGE_VALUES",
    "VAR_CODES",
    "columns",
    "erange_rows",
    "irange_value",
    "resolve",
    "scale_to_unit",
    "spacing_value",
]

#: EC-Lab variable codes, appendix 7.2, keyed by the HELAO column they fill.
VAR_CODES: dict[str, int] = {
    "t_s": 4,
    "Ewe_V": 6,
    "I_A": 8,
    "Ece_V": 9,
    "cycle": 24,
    "f_Hz": 32,
    "AbsEwe_V": 33,
    "AbsI_A": 34,
    "phase": 35,
    "modulus": 36,
    "P_W": 70,
    "AbsEce_V": 96,
    "AbsIce_A": 97,
    "phase_ce": 98,
    "modulus_ce": 99,
}


@dataclass(frozen=True)
class MpsParam:
    """One HELAO parameter's landing place in an ``.mps`` file.

    Attributes:
        param_id: The parameter's caption -- its label in the ``.mps`` table,
            and the ``ParamID`` ``ModifyOnTheFly`` would take.
        unit_param_id: Caption of the companion unit row. EC-Lab spells a
            current, charge or frequency as a magnitude row plus a unit row,
            and formats every number to three decimals -- so a 1 uA setpoint
            written unscaled lands as ``0.000``. Set together with
            ``base_unit``; the driver then calls ``scale_to_unit``.
        base_unit: The unscaled unit symbol (``"A"``, ``"Hz"``). Its presence
            is what selects the scale-and-unit path over ``fmt``.
        fmt: How to render the value when there is no unit row. A
            ``str.format`` spec, or one of the sentinels ``"hms"`` (EC-Lab's
            ``h:mm:s.ffff``), ``"bandwidth"`` (the bare integer 1-9),
            ``"V_to_mV"`` (a volts parameter landing in a millivolts row), or
            ``"spacing"`` (a sweep mode as "Linear"/"Logarithmic").
        technique: Which technique block the row lives in, 0-based, for
            multi-technique templates. ``None`` means the first match
            anywhere. CAOCV needs it: its template holds a CA block and an
            OCV block, and both carry ``E range min (V)``.
    """

    param_id: str
    unit_param_id: Optional[str] = None
    base_unit: Optional[str] = None
    fmt: str = "{}"
    technique: Optional[int] = None


@dataclass(frozen=True)
class ColumnPlan:
    """How one technique's emitted columns are obtained.

    Attributes:
        kind: ``"dc"`` reads via ``MeasureDcValue``, ``"eis"`` via
            ``MeasureEisValue``. The two return different tuples and an EIS
            file read as DC yields plausible-looking nonsense.
        var_codes: Columns fetched one at a time with ``MeasureValueByCode``.
        derived: Columns computed rather than fetched -- see ``mpr_cursor``.
    """

    kind: Literal["dc", "eis"]
    var_codes: dict[str, int] = field(default_factory=dict)
    derived: tuple[str, ...] = ()


@dataclass(frozen=True)
class OleTechnique:
    """Everything the driver needs to run one technique through EC-Lab."""

    technique_name: str
    template: str
    parameter_map: dict[str, MpsParam]
    column_plan: ColumnPlan
    technique_codes: frozenset[int]


def columns(plan: ColumnPlan) -> tuple[str, ...]:
    """Every column this plan produces, fetched and derived alike.

    ``MeasureDcValue`` supplies ``t_s``/``Ewe_V``/``I_A`` and
    ``MeasureEisValue`` supplies ``t_s``/``f_Hz`` plus the impedance pair, so
    those arrive without a ``var_codes`` entry; they are listed in ``derived``
    to keep this function the single answer to "what does this technique
    emit".
    """
    return tuple(dict.fromkeys((*plan.var_codes, *plan.derived)))


#: Columns every DC technique but OCV emits.
DC_COLUMNS = ("t_s", "Ewe_V", "I_A", "P_W", "cycle")

#: Columns both EIS techniques emit.
EIS_COLUMNS = (
    "process",
    "t_s",
    "Ewe_V",
    "I_A",
    "AbsEwe_V",
    "AbsI_A",
    "phase",
    "modulus",
    "Ece_V",
    "AbsEce_V",
    "AbsIce_A",
    "phase_ce",
    "modulus_ce",
    "f_Hz",
    "X_ohm",
    "R_ohm",
)


def _dc_plan() -> ColumnPlan:
    """``MeasureDcValue`` gives t/Ewe/I; P_W and cycle are derived.

    ``P_W`` is fetched-equivalent, not approximated: EC-Lab defines variable 70
    as ``|Ewe * I|``. ``cycle`` comes from status index 10 at poll time.
    """
    return ColumnPlan(kind="dc", derived=("t_s", "Ewe_V", "I_A", "P_W", "cycle"))


def _eis_plan() -> ColumnPlan:
    """``MeasureEisValue`` gives t/f/Re/-Im; the rest come by code.

    ``R_ohm`` is ``Re(Z)`` and ``X_ohm`` is the manual's "imaginary part",
    which section 5.2.14 states is already ``-Im(Z)`` -- exactly what the eclib
    path computes as ``-modulus * sin(phase)``. ``process`` is reconstructed
    from the frequency: the manual states a non-EIS index returns frequency
    zero, so a non-zero frequency is an EIS period.
    """
    return ColumnPlan(
        kind="eis",
        var_codes={
            name: VAR_CODES[name]
            for name in (
                "Ewe_V",
                "I_A",
                "AbsEwe_V",
                "AbsI_A",
                "phase",
                "modulus",
                "Ece_V",
                "AbsEce_V",
                "AbsIce_A",
                "phase_ce",
                "modulus_ce",
            )
        },
        derived=("t_s", "f_Hz", "X_ohm", "R_ohm", "process"),
    )


#: The full-scale voltage each ``EC_ERange`` alias selects, used to write the
#: ``.mps`` file's symmetric min/max pair. ``AUTO`` has no numeric equivalent,
#: so it is handled by ``erange_rows`` rather than appearing here.
ERANGE_VOLTS = {"v2_5": 2.5, "v5": 5.0, "v10": 10.0}

#: EC-Lab writes bandwidth as a bare integer 1-9, **not** as "BW4". Verified
#: against a working third-party writer; writing the alias string produces a
#: file EC-Lab loads and then runs at whatever bandwidth it defaulted to.
BANDWIDTH_VALUES = {f"BW{i}": i for i in range(1, 10)}

#: SI prefixes EC-Lab accepts on a unit row, with the latin-1 micro sign.
#: Ordered large to small; the first whose scaled magnitude is >= 1 wins.
UNIT_PREFIXES = (
    ("M", 1e6),
    ("k", 1e3),
    ("", 1.0),
    ("m", 1e-3),
    ("\u00b5", 1e-6),
    ("n", 1e-9),
    ("p", 1e-12),
)


def scale_to_unit(value: float, base_unit: str) -> tuple[str, str]:
    """Split a physical value into the magnitude and unit EC-Lab writes.

    EC-Lab spells a current, charge or frequency as **two rows** -- a
    magnitude and a matching unit -- and formats every number to three
    decimals. So a 1 uA setpoint written straight into ``Is`` would land as
    ``0.000``: the value has to be scaled and the prefix written alongside it.
    This is the mechanism, not a nicety.

    Args:
        value: The value in base SI units (A, Hz, C ...).
        base_unit: The unscaled unit symbol, e.g. ``"A"`` or ``"Hz"``.

    Returns:
        ``(magnitude, unit)`` -- e.g. ``(1e-6, "A")`` yields
        ``("1.000", "\u00b5A")``. Zero yields the unprefixed unit, since no
        prefix is more correct than any other for it.
    """
    magnitude = abs(float(value))
    if magnitude == 0:
        return "0.000", base_unit
    for prefix, scale in UNIT_PREFIXES:
        if magnitude >= scale:
            return f"{float(value) / scale:.3f}", f"{prefix}{base_unit}"
    prefix, scale = UNIT_PREFIXES[-1]
    return f"{float(value) / scale:.3f}", f"{prefix}{base_unit}"


def erange_rows(value: str) -> dict[str, str]:
    """The ``.mps`` rows that express an ``EC_ERange`` selection.

    EC-Lab has no single "E range" row: the potential window is a symmetric
    ``E range min (V)`` / ``E range max (V)`` pair. ``AUTO`` has no numeric
    equivalent at all, so it writes nothing and leaves the template's own
    window in place -- which is the widest the station configured by hand, and
    the only honest reading of "auto" here.

    Returns:
        Caption-to-value rows to set, empty for ``AUTO`` or an unknown alias.
    """
    volts = ERANGE_VOLTS.get(str(value))
    if volts is None:
        return {}
    return {
        "E range min (V)": f"{-volts:.3f}",
        "E range max (V)": f"{volts:.3f}",
    }


#: How each ``EC_IRange`` alias is spelled in the ``.mps`` ``I Range`` row.
#: EC-Lab writes a **display string**, not the alias -- the real templates
#: hold ``Auto``, ``100 µA`` and ``1 mA``. Writing ``u100`` gives a file that
#: loads and runs on whatever range the template carried.
#:
#: ``KEEP`` and ``BOOSTER`` are absent deliberately: no observed template
#: shows how EC-Lab spells them, and ``irange_value`` refuses rather than
#: inventing a string the device would silently reject or misread.
IRANGE_VALUES = {
    "p100": "100 pA",
    "n1": "1 nA",
    "n10": "10 nA",
    "n100": "100 nA",
    "u1": "1 \u00b5A",
    "u10": "10 \u00b5A",
    "u100": "100 \u00b5A",
    "m1": "1 mA",
    "m10": "10 mA",
    "m100": "100 mA",
    "a1": "1 A",
    "AUTO": "Auto",
}


def irange_value(value: str) -> str:
    """EC-Lab's ``I Range`` display string for an ``EC_IRange`` alias.

    Raises:
        ValueError: On ``KEEP``, ``BOOSTER`` or an unknown alias. Refusing is
            the point: this row silently determines the measurement range, so
            a value EC-Lab does not recognise is a wrong experiment rather
            than an error, and a guessed spelling is the same thing.
    """
    try:
        return IRANGE_VALUES[str(value)]
    except KeyError:
        raise ValueError(
            f"no EC-Lab I Range spelling for {value!r}; expected one of "
            f"{sorted(IRANGE_VALUES)}"
        ) from None


#: How each HELAO ``SweepMode`` value is spelled in the ``.mps`` ``spacing``
#: row. The caption is ``spacing``, not ``sweep``, and the values are words.
SPACING_VALUES = {"lin": "Linear", "log": "Logarithmic"}


def spacing_value(value: str) -> str:
    """EC-Lab's ``spacing`` word for a HELAO ``SweepMode``."""
    return SPACING_VALUES.get(str(value), "Logarithmic")


#: Shared current-range and bandwidth captions. Present on every technique
#: that exposes them; OCV has neither, which is why its map is the short one.
#:
#: ``ERange`` is deliberately absent: unlike these it is not one row but a
#: min/max pair, so the driver applies it through ``erange_rows``. Mapping it
#: onto a single caption would write the string "AUTO" into a field EC-Lab
#: reads as a voltage.
_RANGES = {
    "IRange": MpsParam(param_id="I Range", fmt="irange"),
    "Bandwidth": MpsParam(param_id="Bandwidth", fmt="bandwidth"),
}

OLE_TECHS: dict[str, OleTechnique] = {
    "OCV": OleTechnique(
        technique_name="OCV",
        template="OCV.mps",
        parameter_map={
            "Tval__s": MpsParam(param_id="tR (h:m:s)", fmt="hms"),
            "AcqInterval__s": MpsParam(param_id="dtR (s)", fmt="{:.4f}"),
            # EC-Lab's dER is in millivolts; the HELAO parameter is volts.
            "AcqInterval__V": MpsParam(param_id="dER (mV)", fmt="V_to_mV"),
        },
        column_plan=ColumnPlan(kind="dc", derived=("t_s", "Ewe_V")),
        technique_codes=frozenset({11, 55}),
    ),
    "CA": OleTechnique(
        technique_name="CA",
        template="CA.mps",
        parameter_map={
            "Vval__V": MpsParam(param_id="Ei (V)", fmt="{:.3f}"),
            "Tval__s": MpsParam(param_id="ti (h:m:s)", fmt="hms"),
            "AcqInterval__s": MpsParam(param_id="dta (s)", fmt="{:.4f}"),
            # The current-change record threshold is a magnitude/unit pair.
            "AcqInterval__A": MpsParam(
                param_id="dI", unit_param_id="unit dI", base_unit="A"
            ),
            **_RANGES,
        },
        column_plan=_dc_plan(),
        technique_codes=frozenset({24, 54}),
    ),
    "CP": OleTechnique(
        technique_name="CP",
        template="CP.mps",
        parameter_map={
            "Ival__A": MpsParam(
                param_id="Is", unit_param_id="unit Is", base_unit="A"
            ),
            "Tval__s": MpsParam(param_id="ts (h:m:s)", fmt="hms"),
            "AcqInterval__s": MpsParam(param_id="dts (s)", fmt="{:.4f}"),
            "AcqInterval__V": MpsParam(param_id="dEs (mV)", fmt="V_to_mV"),
            **_RANGES,
        },
        column_plan=_dc_plan(),
        technique_codes=frozenset({25, 56}),
    ),
    # Every caption below is read off the real CV.mps fixture, including the
    # `dE/dt` + `dE/dt unit` pair (which the file spells `20.000` / `mV/s`,
    # so the scan rate is a scale-and-unit parameter like a current).
    #
    # `AcqInterval__V` is deliberately ABSENT. EC-Lab's Cyclic Voltammetry
    # has **no `dE (mV)` row** -- the recording interval is governed by
    # `Step percent` and `N`, whose relationship to a volts-per-point
    # interval is not documented anywhere available here. The endpoint still
    # computes `AcqInterval__V` (`AcqInterval__s * ScanRate__V_s`) for the
    # eclib backend, which maps it to easy-biologic's `step`; on this backend
    # the template's own `Step percent`/`N` stand. Mapping it onto a guessed
    # row would change the sampling of every CV on the station. Resolve at
    # at-station gate 1, with the station owner.
    "CV": OleTechnique(
        technique_name="CV",
        template="CV.mps",
        parameter_map={
            "Vinit__V": MpsParam(param_id="Ei (V)", fmt="{:.3f}"),
            "Vapex1__V": MpsParam(param_id="E1 (V)", fmt="{:.3f}"),
            "Vapex2__V": MpsParam(param_id="E2 (V)", fmt="{:.3f}"),
            "Vfinal__V": MpsParam(param_id="Ef (V)", fmt="{:.3f}"),
            "ScanRate__V_s": MpsParam(
                param_id="dE/dt", unit_param_id="dE/dt unit", base_unit="V/s"
            ),
            "Cycles": MpsParam(param_id="nc cycles", fmt="{:d}"),
            **_RANGES,
        },
        column_plan=_dc_plan(),
        technique_codes=frozenset({6, 57}),
    ),
    "PEIS": OleTechnique(
        technique_name="PEIS",
        template="PEIS.mps",
        parameter_map={
            "Vinit__V": MpsParam(param_id="E (V)", fmt="{:.3f}"),
            # Va is millivolts. Writing volts here is a 1000x error that
            # EC-Lab accepts without complaint.
            "Vamp__V": MpsParam(param_id="Va (mV)", fmt="V_to_mV"),
            "Finit__Hz": MpsParam(
                param_id="fi", unit_param_id="unit fi", base_unit="Hz"
            ),
            "Ffinal__Hz": MpsParam(
                param_id="ff", unit_param_id="unit ff", base_unit="Hz"
            ),
            "FrequencyNumber": MpsParam(param_id="Nd", fmt="{:d}"),
            "Duration__s": MpsParam(param_id="tE (h:m:s)", fmt="hms"),
            "AcqInterval__s": MpsParam(param_id="dt (s)", fmt="{:.4f}"),
            # The caption is `spacing`, not `sweep`, and the values are the
            # words "Linear" / "Logarithmic".
            "SweepMode": MpsParam(param_id="spacing", fmt="spacing"),
            "Repeats": MpsParam(param_id="Na", fmt="{:d}"),
            "DelayFraction": MpsParam(param_id="pw", fmt="{:.2f}"),
            **_RANGES,
        },
        column_plan=_eis_plan(),
        technique_codes=frozenset({29, 60}),
    ),
    "GEIS": OleTechnique(
        technique_name="GEIS",
        template="GEIS.mps",
        parameter_map={
            "Iinit__A": MpsParam(
                param_id="Is", unit_param_id="unit Is", base_unit="A"
            ),
            # GEIS spells the AC amplitude's unit row with TWO spaces --
            # `unit  Ia`. That is EC-Lab's, not a typo here, and it is why
            # mps_template parses by column rather than by whitespace runs.
            "Iamp__A": MpsParam(
                param_id="Ia", unit_param_id="unit  Ia", base_unit="A"
            ),
            "Finit__Hz": MpsParam(
                param_id="fi", unit_param_id="unit fi", base_unit="Hz"
            ),
            "Ffinal__Hz": MpsParam(
                param_id="ff", unit_param_id="unit ff", base_unit="Hz"
            ),
            "FrequencyNumber": MpsParam(param_id="Nd", fmt="{:d}"),
            # GEIS's conditioning-time caption is tIs, not tE.
            "Duration__s": MpsParam(param_id="tIs (h:m:s)", fmt="hms"),
            "AcqInterval__s": MpsParam(param_id="dt (s)", fmt="{:.4f}"),
            "SweepMode": MpsParam(param_id="spacing", fmt="spacing"),
            "Repeats": MpsParam(param_id="Na", fmt="{:d}"),
            "DelayFraction": MpsParam(param_id="pw", fmt="{:.2f}"),
            **_RANGES,
        },
        column_plan=_eis_plan(),
        technique_codes=frozenset({30, 61}),
    ),
    "CAOCV": OleTechnique(
        technique_name="CAOCV",
        template="CAOCV.mps",
        parameter_map={
            # Two technique blocks in one template, so every row is scoped:
            # both carry `E range min (V)`, and an unscoped patch would put
            # the OCV settings into the CA step.
            "CA_Vval__V_list": MpsParam(
                param_id="Ei (V)", fmt="{:.3f}", technique=0
            ),
            "CA_Tval__s_list": MpsParam(
                param_id="ti (h:m:s)", fmt="hms", technique=0
            ),
            "CA_AcqInterval__s": MpsParam(
                param_id="dta (s)", fmt="{:.4f}", technique=0
            ),
            "CA_AcqInterval__A": MpsParam(
                param_id="dI", unit_param_id="unit dI", base_unit="A", technique=0
            ),
            "CA_IRange": MpsParam(param_id="I Range", fmt="irange", technique=0),
            "CA_Bandwidth": MpsParam(
                param_id="Bandwidth", fmt="bandwidth", technique=0
            ),
            "OCV_Tval__s": MpsParam(
                param_id="tR (h:m:s)", fmt="hms", technique=1
            ),
            "OCV_AcqInterval__s": MpsParam(
                param_id="dtR (s)", fmt="{:.4f}", technique=1
            ),
            "OCV_AcqInterval__V": MpsParam(
                param_id="dER (mV)", fmt="V_to_mV", technique=1
            ),
        },
        column_plan=_dc_plan(),
        technique_codes=frozenset({24, 54, 11, 55}),
    ),
}


def resolve(name: str) -> OleTechnique:
    """The registry entry for ``name``.

    Raises:
        ValueError: On an unknown technique. Naming the alternatives matters
            because the caller is usually a station config or an experiment
            library, where a typo is otherwise diagnosed at the instrument.
    """
    try:
        return OLE_TECHS[name]
    except KeyError:
        raise ValueError(
            f"unknown OLE technique {name!r}; expected one of {sorted(OLE_TECHS)}"
        ) from None
```

**Where these captions come from.** Not guesses. They were checked against [`jdhuang-csm/biologic-com`](https://github.com/jdhuang-csm/biologic-com), a working third-party package that generates `.mps` files for EC-Lab over the same OLE COM interface — specifically its `biocom/mps/techniques/{ocv,chrono,eis}.py` parameter maps and `biocom/mps/write_utils.py` formatters.

That repository has **no LICENSE file**, so it is all-rights-reserved and none of its code may be copied into this one. What is taken here is factual: the caption strings EC-Lab writes, the field order, and the value encodings. Those are properties of the vendor's file format, not of anyone's source.

Two caveats that matter:

- **CV is not covered by that reference.** It implements OCV, CA, CP, PEIS, GEIS, GCPL, Loop and Modulo Bat — not CV. The CV captions above follow the conventions the verified techniques establish, but they remain unverified and are the first thing to check at at-station gate 1.
- **A caption no template row matches raises `MpsParameterNotFound` at setup**, deliberately, rather than appending a row or running the template's default. That is what turns a wrong caption into a failed action instead of a wrong experiment.

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest helao/deploy/hte/tests/test_ole_technique.py -v`

Expected: all pass. If `test_emitted_columns_match_the_eclib_field_map` fails for OCV, check that the eclib `TECH_OCV.field_map` is exactly `{"time": "t_s", "voltage": "Ewe_V"}` — the OLE plan must mirror its *values*, not its keys.

- [ ] **Step 5: Format and commit**

```bash
black helao/deploy/hte/drivers/pstat/biologic_ole/technique.py \
      helao/deploy/hte/tests/test_ole_technique.py
git add helao/deploy/hte/drivers/pstat/biologic_ole/technique.py \
        helao/deploy/hte/tests/test_ole_technique.py
git commit -m "feat(hte): OLE technique registry with eclib column parity

Parameter captions, EC-Lab variable codes (appendix 7.2) and accepted
technique codes (appendix 7.1, which lists most techniques under two
families) for all seven techniques. A test pins the emitted column set
equal to the eclib registry's field_map values.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: TTL as prepended/appended techniques

**Files:**
- Modify: `helao/deploy/hte/drivers/pstat/biologic_ole/technique.py` (add the TTL entries and `format_value`)
- Create: `helao/deploy/hte/drivers/pstat/biologic_ole/mps_assemble.py`
- Test: `helao/deploy/hte/tests/test_ole_technique.py` (extend)

**Interfaces:**
- Consumes: `MpsDocument`, `loads`, `render`, `set_param` from `mps_template`; `MpsParam`, `resolve` from `technique`.
- Produces: `format_value(value, fmt: str) -> str` in `technique.py`; and in `mps_assemble.py`: `TtlPlan` (frozen dataclass: `wait: int = -1`, `send: int = -1`, `duration: float = 1.0`, with property `is_active: bool`), `ttl_plan_from_params(params: dict) -> TtlPlan`, `assemble(main: MpsDocument, ttl: TtlPlan, trigger_in: MpsDocument, trigger_out: MpsDocument) -> MpsDocument`, and `renumber_techniques(doc: MpsDocument) -> MpsDocument`.

**Context the implementer needs.** The OLE COM API has no trigger calls at all. Trigger In and Trigger Out are *techniques* (appendix 7.1 codes 38/39 and 88/89), so the only way to honour `TTLwait`/`TTLsend`/`TTLduration` is to build a multi-technique `.mps`. A `.mps` numbers its techniques with `Technique : N` lines and declares the count in a `Number of linked techniques : N` header line; inserting a technique means renumbering both. Nothing in the tracked experiments passes a non-default TTL value today, but private deployments are not visible here and a silently dropped hardware trigger surfaces months later in the data.

- [ ] **Step 1: Write the failing tests**

Append to `helao/deploy/hte/tests/test_ole_technique.py`:

```python
from pathlib import Path

from helao.deploy.hte.drivers.pstat.biologic_ole import mps_assemble as ma
from helao.deploy.hte.drivers.pstat.biologic_ole import mps_template as mt

TEMPLATES = Path("helao/deploy/hte/drivers/pstat/biologic_ole/templates")
FIXTURES = Path("helao/deploy/hte/tests/fixtures/ole")

# The real GUI-authored templates, and the real three-technique file the
# assembler is trying to reproduce.
TRIGGER_IN = mt.load(TEMPLATES / "TI.mps")
TRIGGER_OUT = mt.load(TEMPLATES / "TO.mps")
MAIN = mt.load(FIXTURES / "CV.mps")
REFERENCE = mt.load(FIXTURES / "TI_CV_TO.mps")


def test_the_real_trigger_templates_hold_one_technique_each():
    assert [b.name for b in mt.technique_blocks(TRIGGER_IN)] == ["Trigger In"]
    assert [b.name for b in mt.technique_blocks(TRIGGER_OUT)] == ["Trigger Out"]


def test_trigger_in_carries_a_channel_and_no_duration():
    assert mt.get_param(TRIGGER_IN, "Channel") == "-1"
    assert mt.get_param(TRIGGER_IN, "Trigger") == "Rising Edge"
    with pytest.raises(mt.MpsParameterNotFound):
        mt.get_param(TRIGGER_IN, "td (h:m:s)")


def test_trigger_out_carries_a_delay_and_no_channel():
    """Which is why TTLsend selects nothing -- see UNMAPPED_TTLSEND."""
    assert mt.get_param(TRIGGER_OUT, "td (h:m:s)") == "0:00:0.0010"
    with pytest.raises(mt.MpsParameterNotFound):
        mt.get_param(TRIGGER_OUT, "Channel")


def test_a_disabled_ttl_plan_is_inactive():
    assert ma.ttl_plan_from_params({"TTLwait": -1, "TTLsend": -1}).is_active is False


def test_an_absent_ttl_key_reads_as_disabled():
    assert ma.ttl_plan_from_params({}).is_active is False


def test_either_direction_activates_the_plan():
    assert ma.ttl_plan_from_params({"TTLwait": 0}).is_active is True
    assert ma.ttl_plan_from_params({"TTLsend": 3}).is_active is True


def test_an_inactive_plan_returns_the_main_document_unchanged():
    out = ma.assemble(MAIN, ma.TtlPlan(), TRIGGER_IN, TRIGGER_OUT)
    assert mt.render(out) == mt.render(MAIN)


def test_ttlwait_prepends_a_trigger_in_technique():
    plan = ma.TtlPlan(wait=2)
    out = ma.assemble(MAIN, plan, TRIGGER_IN, TRIGGER_OUT)
    assert [b.name for b in mt.technique_blocks(out)] == [
        "Trigger In",
        "Cyclic Voltammetry",
    ]


def test_ttlsend_appends_a_trigger_out_technique():
    plan = ma.TtlPlan(send=1)
    out = ma.assemble(MAIN, plan, TRIGGER_IN, TRIGGER_OUT)
    assert [b.name for b in mt.technique_blocks(out)] == [
        "Cyclic Voltammetry",
        "Trigger Out",
    ]


def test_both_directions_reproduce_the_reference_block_order():
    """The assembled file must match a GUI-authored TI -> CV -> TO."""
    out = ma.assemble(MAIN, ma.TtlPlan(wait=2, send=1), TRIGGER_IN, TRIGGER_OUT)
    assert [b.name for b in mt.technique_blocks(out)] == [
        b.name for b in mt.technique_blocks(REFERENCE)
    ]


def test_the_header_appears_exactly_once():
    """Each template is a whole .mps; splicing documents would repeat it."""
    out = mt.render(ma.assemble(MAIN, ma.TtlPlan(wait=2, send=1), TRIGGER_IN, TRIGGER_OUT))
    assert out.count("EC-LAB SETTING FILE") == 1
    assert out.count("Number of linked techniques") == 1


def test_the_in_channel_lands_on_trigger_in(triggered_out=None):
    out = ma.assemble(MAIN, ma.TtlPlan(wait=2), TRIGGER_IN, TRIGGER_OUT)
    assert mt.get_param(out, "Channel", technique=0) == "2"


def test_the_duration_lands_on_trigger_outs_delay_row():
    out = ma.assemble(MAIN, ma.TtlPlan(send=1, duration=2.5), TRIGGER_IN, TRIGGER_OUT)
    assert mt.get_param(out, "td (h:m:s)", technique=1) == "0:00:2.5000"


def test_configuring_one_trigger_leaves_the_others_trigger_row_alone():
    """Both blocks carry a `Trigger` row; a first-match patch hits the wrong one."""
    out = ma.assemble(MAIN, ma.TtlPlan(wait=2, send=1), TRIGGER_IN, TRIGGER_OUT)
    assert mt.get_param(out, "Trigger", technique=0) == "Rising Edge"
    assert mt.get_param(out, "Trigger", technique=2) == "Rising Edge"


def test_techniques_are_renumbered_consecutively_from_one():
    out = mt.render(ma.assemble(MAIN, ma.TtlPlan(wait=2, send=1), TRIGGER_IN, TRIGGER_OUT))
    numbers = [
        int(line.split(":")[1])
        for line in out.splitlines()
        if line.startswith("Technique :")
    ]
    assert numbers == [1, 2, 3]


def test_the_linked_technique_count_header_is_updated():
    out = mt.render(ma.assemble(MAIN, ma.TtlPlan(wait=2, send=1), TRIGGER_IN, TRIGGER_OUT))
    assert "Number of linked techniques : 3" in out


def test_the_assembled_file_keeps_crlf_throughout():
    out = mt.render(ma.assemble(MAIN, ma.TtlPlan(wait=2, send=1), TRIGGER_IN, TRIGGER_OUT))
    raw = out.encode(mt.ENCODING)
    assert raw.count(b"\r\n") == raw.count(b"\n") > 0


def test_a_trigger_template_with_more_than_one_technique_is_refused():
    with pytest.raises(ValueError, match="exactly one technique"):
        ma.assemble(MAIN, ma.TtlPlan(wait=0), REFERENCE, TRIGGER_OUT)
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest helao/deploy/hte/tests/test_ole_technique.py -v`

Expected: the pre-existing tests still pass; the new ones fail with `ImportError: cannot import name 'mps_assemble'`.

- [ ] **Step 3: Add `format_value` to `technique.py`**

Append to `helao/deploy/hte/drivers/pstat/biologic_ole/technique.py`, and add `"format_value"` to `__all__`:

```python
def format_value(value, fmt: str) -> str:
    """Render ``value`` as EC-Lab spells it in an ``.mps`` table.

    Four sentinels stand in for things no single ``str.format`` spec produces,
    and each exists because writing the obvious thing yields a file EC-Lab
    accepts and then runs wrongly:

    * ``"hms"`` -- EC-Lab's duration spelling, ``h:mm:s.ffff``.
    * ``"bandwidth"`` -- the bare integer 1-9. Writing ``"BW4"`` gives a file
      that loads and runs at whatever bandwidth the template carried.
    * ``"V_to_mV"`` -- a volts parameter landing in a millivolts row
      (``Va (mV)``, ``dER (mV)``, ``dEs (mV)``). Otherwise a 1000x error.
    * ``"spacing"`` -- a sweep mode as EC-Lab's word, "Linear"/"Logarithmic".
    * ``"irange"`` -- a current range as EC-Lab's display string, e.g.
      ``100 µA``. Writing the ``u100`` alias runs on the template's range.

    Anything else is a plain spec applied verbatim. Values needing a companion
    unit row never come through here -- see ``scale_to_unit``.
    """
    if fmt == "hms":
        # The one real duration in a GUI-authored file is `0:00:0.0010`
        # (TI_CV_TO.mps, Trigger Out's `td`): hours and seconds unpadded,
        # minutes padded to two. A third-party writer emits `00:00:00.0010`
        # instead and reportedly works, so EC-Lab is probably lenient on
        # read -- but what it *writes* is the only evidence there is, and a
        # patched file that differs from a GUI-authored one for no reason is
        # a difference nobody will remember making. Confirm with a
        # longer-than-a-minute duration at at-station gate 1.
        total = float(value)
        hours = int(total / 3600.0)
        minutes = int((total % 3600.0) / 60.0)
        seconds = int(total % 60.0)
        fraction = "{:.4f}".format(round(total % 1, 4)).split(".")[1]
        return f"{hours}:{minutes:02d}:{seconds}.{fraction}"
    if fmt == "bandwidth":
        return str(BANDWIDTH_VALUES[str(value)])
    if fmt == "V_to_mV":
        return f"{float(value) * 1000.0:.3f}"
    if fmt == "spacing":
        return spacing_value(value)
    if fmt == "irange":
        return irange_value(value)
    return fmt.format(value)
```

- [ ] **Step 4: Write `mps_assemble.py`**

```python
"""Build a multi-technique ``.mps`` by bracketing one with trigger techniques.

The OLE COM API has no trigger functions. Trigger In and Trigger Out are
*techniques* (appendix 7.1, codes 38/39 and 88/89), so honouring the frozen
``TTLwait``/``TTLsend``/``TTLduration`` parameters means assembling a
multi-technique settings file rather than making an extra call.

Verified against ``tests/fixtures/ole/TI_CV_TO.mps``, a real GUI-authored
Trigger In -> CV -> Trigger Out file. Four things it settles that guessing got
wrong:

* **Trigger In carries ``Trigger`` and ``Channel``, and no duration at all.**
  Its channel row holds ``-1`` in the real file -- the same "disabled"
  convention HELAO's own ``TTLwait`` uses.
* **Trigger Out carries ``Trigger`` and ``td (h:m:s)``, and no channel row.**
  ``td`` is a *delay*, not a pulse width. So ``TTLduration`` lands there, and
  ``TTLsend``'s channel has nowhere to go -- see ``UNMAPPED_TTLSEND``.
* **Each template is a whole ``.mps`` with its own header.** Only the
  technique *block* may be spliced in; concatenating the documents would
  repeat ``EC-LAB SETTING FILE`` three times.
* **A block includes the blank line that follows it**, which is what keeps
  the assembled file's separation identical to a GUI-authored one.

Two bookkeeping details a ``.mps`` requires and EC-Lab will not repair: the
``Technique : N`` lines must run consecutively from 1, and the
``Number of linked techniques : N`` header must agree with them.
"""

import re
from dataclasses import dataclass

from .mps_template import MpsDocument, set_param, technique_blocks
from .technique import format_value

__all__ = [
    "TtlPlan",
    "UNMAPPED_TTLSEND",
    "assemble",
    "renumber_techniques",
    "ttl_plan_from_params",
]

_TECHNIQUE_LINE = re.compile(r"^Technique : \d+")
_COUNT_LINE = re.compile(r"^(Number of linked techniques : )\d+")

#: Trigger In's channel row. Holds -1 when disabled, as HELAO's own TTLwait
#: does.
IN_CHANNEL_PARAM = "Channel"

#: Trigger Out's delay row. Note this is a delay before the pulse, not the
#: pulse width -- ``TTLduration``'s name is inherited from the Gamry-style
#: parameter set and does not describe what EC-Lab does with it.
OUT_DELAY_PARAM = "td (h:m:s)"

#: The real Trigger Out block has **no channel row**, so a station that needs
#: to select which output line fires cannot express it here. Recorded rather
#: than silently dropped: a station passing TTLsend gets a warning naming
#: this, and the fix is a TO template authored for the right output.
UNMAPPED_TTLSEND = (
    "EC-Lab's Trigger Out technique carries no channel row, so TTLsend "
    "cannot select an output line; the TO.mps template's own wiring decides "
    "which line fires"
)


@dataclass(frozen=True)
class TtlPlan:
    """The three frozen TTL action parameters, as read from an action.

    Attributes:
        wait: TTL-in channel to wait on. ``-1`` disables.
        send: TTL-out channel to pulse. ``-1`` disables. See
            ``UNMAPPED_TTLSEND`` -- the value selects nothing today.
        duration: Trigger Out delay in seconds, written to ``td (h:m:s)``.
    """

    wait: int = -1
    send: int = -1
    duration: float = 1.0

    @property
    def is_active(self) -> bool:
        """True when either direction is enabled."""
        return self.wait >= 0 or self.send >= 0


def ttl_plan_from_params(params: dict) -> TtlPlan:
    """Read a ``TtlPlan`` out of an action's parameter dict.

    Absent keys read as disabled, so an endpoint that never declared them
    yields an inactive plan rather than a KeyError.
    """
    return TtlPlan(
        wait=int(params.get("TTLwait", -1)),
        send=int(params.get("TTLsend", -1)),
        duration=float(params.get("TTLduration", 1.0)),
    )


def _block_lines(doc: MpsDocument) -> tuple[str, ...]:
    """Just the technique block of a single-technique template.

    A template is a complete ``.mps`` with its own header; splicing the whole
    document in would repeat ``EC-LAB SETTING FILE`` once per trigger.

    Raises:
        ValueError: If the template does not hold exactly one technique.
    """
    blocks = technique_blocks(doc)
    if len(blocks) != 1:
        raise ValueError(
            f"a trigger template must hold exactly one technique, found "
            f"{len(blocks)}"
        )
    return doc.lines[blocks[0].start : blocks[0].stop]


def renumber_techniques(doc: MpsDocument) -> MpsDocument:
    """Renumber ``Technique : N`` consecutively and fix the count header.

    Splicing blocks together leaves several numbered 1. EC-Lab reads the
    numbers positionally, so a duplicate is not an error it reports -- it is
    an experiment that runs the wrong technique list.
    """
    lines = list(doc.lines)
    seen = 0
    for index, line in enumerate(lines):
        if _TECHNIQUE_LINE.match(line.rstrip("\r\n")):
            seen += 1
            ending = line[len(line.rstrip("\r\n")) :]
            lines[index] = f"Technique : {seen}{ending}"
    for index, line in enumerate(lines):
        if _COUNT_LINE.match(line.rstrip("\r\n")):
            ending = line[len(line.rstrip("\r\n")) :]
            lines[index] = (
                _COUNT_LINE.sub(rf"\g<1>{seen}", line.rstrip("\r\n")) + ending
            )
            break
    return MpsDocument(lines=tuple(lines))


def assemble(
    main: MpsDocument,
    ttl: TtlPlan,
    trigger_in: MpsDocument,
    trigger_out: MpsDocument,
) -> MpsDocument:
    """``main``, optionally bracketed by configured trigger techniques.

    An inactive plan returns ``main`` unchanged -- identically, not merely
    equivalently -- so the overwhelmingly common no-TTL case cannot be
    perturbed by this code path at all.

    The trigger blocks are configured *before* splicing, while each is still
    a single-technique document, so no caption lookup has to disambiguate
    between the two ``Trigger`` rows the assembled file will contain.
    """
    if not ttl.is_active:
        return main

    parts: list[str] = []
    if ttl.wait >= 0:
        configured = set_param(
            trigger_in, IN_CHANNEL_PARAM, str(ttl.wait), technique=0
        )
        parts.extend(_block_lines(configured))

    header_end = technique_blocks(main)[0].start
    parts = list(main.lines[:header_end]) + parts + list(main.lines[header_end:])

    if ttl.send >= 0:
        configured = set_param(
            trigger_out,
            OUT_DELAY_PARAM,
            format_value(ttl.duration, "hms"),
            technique=0,
        )
        parts.extend(_block_lines(configured))

    return renumber_techniques(MpsDocument(lines=tuple(parts)))
```

- [ ] **Step 5: Run the tests and verify they pass**

Run: `pytest helao/deploy/hte/tests/test_ole_technique.py -v`

Expected: all pass. If `test_the_linked_technique_count_header_is_updated` fails, note that only the *main* fixture carries the header line — `renumber_techniques` updates the first one it finds and stops, which is correct because a concatenation should have exactly one.

- [ ] **Step 6: Format and commit**

```bash
black helao/deploy/hte/drivers/pstat/biologic_ole/mps_assemble.py \
      helao/deploy/hte/drivers/pstat/biologic_ole/technique.py \
      helao/deploy/hte/tests/test_ole_technique.py
git add helao/deploy/hte/drivers/pstat/biologic_ole/mps_assemble.py \
        helao/deploy/hte/drivers/pstat/biologic_ole/technique.py \
        helao/deploy/hte/tests/test_ole_technique.py
git commit -m "feat(hte): honour TTL by bracketing the technique in the .mps

The OLE COM API has no trigger calls; Trigger In/Out are techniques. A
non-default TTLwait/TTLsend therefore assembles a multi-technique .mps,
renumbering Technique : N and the linked-technique count header, which
EC-Lab reads positionally and does not repair. An inactive plan returns
the main document untouched.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: `olecom_client.py` — the typed COM wrapper

**Files:**
- Create: `helao/deploy/hte/drivers/pstat/biologic_ole/olecom_client.py`
- Test: `helao/deploy/hte/tests/test_ole_client.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `OleComError(RuntimeError)` (attributes `function: str`, `args: tuple`, `hint: str`), `HINTS: dict[str, str]`, `DEFAULT_PROGID: str`, `create_com_object(progid: str)`, and `OleComClient` with `__init__(self, progid: str = DEFAULT_PROGID, factory=create_com_object)` plus the methods listed in the table below.

**Context the implementer needs.** Every OLE function returns a bare `1`/`0` carrying no reason, and section 2 of the manual states the interface performs no validation whatsoever. So the wrapper's job is not to pass values through — it is to turn a `0` into a named, actionable failure. Out-parameters are returned by the COM layer as extra tuple elements; the exact convention `comtypes` uses for a given method is an at-station probe, so the wrapper normalizes whatever it gets through one `_unpack` helper and the fake server in Task 6 speaks the same convention.

The methods, with the OLE function each wraps:

| Method | OLE function | Returns |
|---|---|---|
| `enable_messages_windows(enabled)` | `EnableMessagesWindows` | `None` |
| `get_software_version()` | `GetSoftwareVersion` | `str` |
| `connect_device_by_ip(ip)` | `ConnectDeviceByIP` | device number `int` |
| `disconnect_device(dev)` | `DisconnectDevice` | `None` |
| `test_connection(dev)` | `TestConnection` | `bool` (never raises) |
| `get_device_type(dev)` | `GetDeviceType` | `str` |
| `get_device_sn(dev)` | `GetDeviceSN` | `(int, list[int])` |
| `get_device_channel_list(dev)` | `GetDeviceChannelList` | `list[bool]` |
| `is_channel_ready(dev, ch)` | `IsChannelReady` | `bool` (never raises) |
| `load_settings(dev, ch, path)` | `LoadSettings` | `None` |
| `run_channel(dev, ch, out_base)` | `RunChannel` | `None` |
| `stop_channel(dev, ch)` | `StopChannel` | `bool` — `False` means already stopped |
| `get_data_file_name(dev, ch, tech)` | `GetDataFileName` | `str` |
| `measure_status(dev, ch)` | `MeasureStatus` | `tuple[float, ...]` of length 32 |
| `measure_number_of_points(mpr)` | `MeasureNumberOfPoints` | `int` |
| `measure_dc_value(mpr, idx)` | `MeasureDcValue` | `tuple[float, ...]` |
| `measure_eis_value(mpr, idx)` | `MeasureEisValue` | `tuple[float, ...]` |
| `measure_value_by_code(mpr, code, idx)` | `MeasureValueByCode` | `float` |

- [ ] **Step 1: Write the failing tests**

Create `helao/deploy/hte/tests/test_ole_client.py`:

```python
"""The typed wrapper over EC-Lab's OLE COM functions.

Every OLE function returns a bare 1/0 with no reason attached, and section 2
of the manual states the interface performs no validation of anything sent.
The wrapper's whole value is therefore diagnostic: a 0 becomes a named failure
that says what is likely wrong, because the vendor never will.

The COM object is injected, so these tests run on Linux with no comtypes.
"""

import pytest

from helao.deploy.hte.drivers.pstat.biologic_ole.olecom_client import (
    HINTS,
    OleComClient,
    OleComError,
)


class FakeCom:
    """Records calls and replays scripted returns, in the tuple convention."""

    def __init__(self, returns=None):
        self.returns = returns or {}
        self.calls = []

    def __getattr__(self, name):
        def _call(*args):
            self.calls.append((name, args))
            value = self.returns.get(name, 1)
            return value(*args) if callable(value) else value

        return _call


def client(returns=None) -> tuple[OleComClient, FakeCom]:
    com = FakeCom(returns)
    return OleComClient(factory=lambda progid: com), com


def test_the_com_object_is_created_lazily_from_the_progid():
    created = []
    OleComClient(progid="X.Y", factory=lambda p: created.append(p) or object())
    assert created == []  # nothing until first use


def test_the_progid_reaches_the_factory_on_first_call():
    created = []

    def factory(progid):
        created.append(progid)
        return FakeCom()

    OleComClient(progid="EC-Lab.App", factory=factory).enable_messages_windows(False)
    assert created == ["EC-Lab.App"]


def test_connect_device_by_ip_returns_the_device_number():
    cli, com = client({"ConnectDeviceByIP": (1, 6)})
    assert cli.connect_device_by_ip("192.168.200.100") == 6
    assert com.calls == [("ConnectDeviceByIP", ("192.168.200.100",))]


def test_a_zero_return_raises_with_the_function_named():
    cli, _ = client({"ConnectDeviceByIP": (0, 0)})
    with pytest.raises(OleComError) as excinfo:
        cli.connect_device_by_ip("192.168.200.100")
    assert excinfo.value.function == "ConnectDeviceByIP"
    assert "192.168.200.100" in str(excinfo.value)


def test_the_failure_carries_the_documented_hint():
    cli, _ = client({"LoadSettings": 0})
    with pytest.raises(OleComError, match="incompatible with"):
        cli.load_settings(6, 3, "C:/x.mps")


def test_every_wrapped_function_has_a_hint():
    """A 0 with no hint is exactly the un-diagnosable failure this avoids."""
    wrapped = {
        "ConnectDeviceByIP", "DisconnectDevice", "LoadSettings", "RunChannel",
        "GetDataFileName", "MeasureStatus", "MeasureNumberOfPoints",
        "MeasureDcValue", "MeasureEisValue", "MeasureValueByCode",
        "GetDeviceChannelList", "GetDeviceType", "GetDeviceSN",
        "GetSoftwareVersion", "EnableMessagesWindows",
    }
    assert wrapped <= set(HINTS), sorted(wrapped - set(HINTS))


def test_stop_channel_reports_already_stopped_without_raising():
    """A 0 here means the channel was already stopped -- not an error."""
    cli, _ = client({"StopChannel": 0})
    assert cli.stop_channel(6, 3) is False


def test_is_channel_ready_and_test_connection_return_false_not_raise():
    cli, _ = client({"IsChannelReady": 0, "TestConnection": 0})
    assert cli.is_channel_ready(6, 3) is False
    assert cli.test_connection(6) is False


def test_measure_status_returns_the_32_reals():
    values = tuple(float(i) for i in range(32))
    cli, _ = client({"MeasureStatus": (1, values)})
    assert cli.measure_status(6, 3) == values


def test_measure_number_of_points_returns_the_count_not_a_success_flag():
    """MeasureNumberOfPoints' Result *is* the count, per section 5.2.12."""
    cli, _ = client({"MeasureNumberOfPoints": 47})
    assert cli.measure_number_of_points("C:/x.mpr") == 47


def test_zero_points_is_a_count_not_a_failure():
    cli, _ = client({"MeasureNumberOfPoints": 0})
    assert cli.measure_number_of_points("C:/x.mpr") == 0


def test_measure_dc_value_returns_the_array():
    cli, _ = client({"MeasureDcValue": (1, (0.3, -0.026, 1e-4))})
    assert cli.measure_dc_value("C:/x.mpr", 3) == (0.3, -0.026, 1e-4)


def test_measure_eis_value_returns_four_values():
    cli, _ = client({"MeasureEisValue": (1, (0.3, 1000.0, 52.0, -11.0))})
    assert cli.measure_eis_value("C:/x.mpr", 3) == (0.3, 1000.0, 52.0, -11.0)


def test_measure_value_by_code_returns_the_datum():
    cli, _ = client({"MeasureValueByCode": (1, -0.0259855, 1)})
    assert cli.measure_value_by_code("C:/x.mpr", 6, 3) == pytest.approx(-0.0259855)


def test_measure_value_by_code_honours_its_trailing_function_result():
    """Section 5.2.15: Result == FunctionResult, and Data precedes it."""
    cli, _ = client({"MeasureValueByCode": (0, 0.0, 0)})
    with pytest.raises(OleComError, match="MeasureValueByCode"):
        cli.measure_value_by_code("C:/x.mpr", 6, 3)


def test_get_device_channel_list_returns_booleans():
    flags = (0, 1, 0, 1) + (0,) * 12
    cli, _ = client({"GetDeviceChannelList": (1, flags)})
    assert cli.get_device_channel_list(6) == [
        False, True, False, True, *([False] * 12)
    ]


def test_get_device_sn_splits_device_and_module_serials():
    cli, _ = client({"GetDeviceSN": (1, 12345, (0, 39697, 0), 1)})
    assert cli.get_device_sn(6) == (12345, [0, 39697, 0])


def test_enable_messages_windows_sends_an_int_not_a_bool():
    """The signature takes SYSINT; passing True is not the documented type."""
    cli, com = client({"EnableMessagesWindows": (1, 1)})
    cli.enable_messages_windows(False)
    assert com.calls == [("EnableMessagesWindows", (0,))]


def test_the_module_does_not_import_comtypes_at_module_scope():
    import sys

    assert "comtypes" not in sys.modules
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest helao/deploy/hte/tests/test_ole_client.py -v`

Expected: collection error, `ModuleNotFoundError: No module named '...olecom_client'`.

- [ ] **Step 3: Write `olecom_client.py`**

```python
"""Typed wrapper over EC-Lab's OLE COM functions.

**This is the only module in the package that may import comtypes, and it
imports it inside a function.** ``test_biologic_ole_vendor_isolation.py``
enforces that: an import anywhere else makes the whole package unimportable on
Linux, which is where every test in this package runs.

Every OLE function returns a bare ``1``/``0`` and carries no reason for a
failure -- and section 2 of the manual states outright that the interface
performs *no validation* of the commands sent. So this wrapper's real job is
diagnostic: it turns a ``0`` into an ``OleComError`` naming the function, the
arguments, and the most likely cause, because nothing else in the stack will.

Three return shapes need distinguishing and two of them look alike:

* Most functions return ``Result`` alone, where ``1`` is success.
* Functions with out-parameters return them as extra tuple elements. The exact
  convention ``comtypes`` produces per method is an at-station probe; the
  wrapper normalizes through ``_unpack`` and the fake server in ``sim.py``
  speaks the same convention, so a station correction lands in one place.
* ``MeasureNumberOfPoints`` is the exception where ``Result`` **is** the
  value (section 5.2.12), so ``0`` is a legitimate answer -- an empty file --
  and must not raise. ``StopChannel``, ``IsChannelReady`` and
  ``TestConnection`` likewise answer a question rather than report a fault.
"""

from typing import Any, Callable, Optional

__all__ = [
    "DEFAULT_PROGID",
    "HINTS",
    "OleComClient",
    "OleComError",
    "create_com_object",
]

#: EC-Lab's registered OLE COM ProgID. Not stated in the manual -- this is the
#: conventional spelling and is an at-station probe (gate 2 of the spec).
#: Overridable by the `progid` driver config key so a station correction needs
#: no code change.
DEFAULT_PROGID = "EC-Lab.Application"

#: What a `0` most likely means, per function. Written from the manual's own
#: notes where it has them (LoadSettings) and from the failure modes the
#: function can actually have where it does not.
HINTS: dict[str, str] = {
    "ConnectDeviceByIP": (
        "device unreachable at that IP, already held by another OLE client, "
        "or EC-Lab could not add it to its device list"
    ),
    "DisconnectDevice": "device number not in EC-Lab's device list, or already disconnected",
    "TestConnection": "EC-Lab is not connected to that device",
    "GetDeviceChannelList": "device number not in EC-Lab's device list",
    "GetDeviceType": "device number not in EC-Lab's device list",
    "GetDeviceSN": "device number not in EC-Lab's device list",
    "GetSoftwareVersion": "EC-Lab did not report its version",
    "EnableMessagesWindows": "EC-Lab refused the Windows-message setting",
    "LoadSettings": (
        "settings are incompatible with this hardware (bandwidth, IRange, "
        "E range) or the .mps file is unreadable -- open it in EC-Lab"
    ),
    "RunChannel": (
        "channel is not ready, no settings are loaded on it, or the output "
        "path is not writable by EC-Lab"
    ),
    "StopChannel": "channel was already stopped",
    "GetDataFileName": "no data file for that technique index on that channel",
    "MeasureStatus": "channel number is out of range for that device",
    "MeasureNumberOfPoints": "MPR file missing or unreadable",
    "MeasureDcValue": "MPR file missing, or the index is past the last point",
    "MeasureEisValue": "MPR file missing, or the index is past the last point",
    "MeasureValueByCode": (
        "MPR file missing, the index is past the last point, or that variable "
        "code is not recorded by this technique"
    ),
    "IsChannelReady": "channel is busy or does not exist",
}


class OleComError(RuntimeError):
    """An OLE function returned failure, annotated with a likely cause."""

    def __init__(self, function: str, args: tuple, hint: str):
        self.function = function
        self.args_sent = args
        self.hint = hint
        super().__init__(f"{function}{args} returned failure: {hint}")


def create_com_object(progid: str) -> Any:
    """Create the EC-Lab OLE COM object.

    The ``comtypes`` import is deliberately inside this function: the package
    must import on Linux, where the vendor stack does not exist.

    Raises:
        RuntimeError: If EC-Lab is not registered as an OLE COM server, with
            the exact command that fixes it. Left as a bare RuntimeError
            rather than an OleComError because no OLE call was made.
    """
    import comtypes.client  # noqa: PLC0415 - vendor isolation, see module docstring

    try:
        return comtypes.client.CreateObject(progid)
    except OSError as exc:
        raise RuntimeError(
            f"could not create the EC-Lab OLE COM object {progid!r}. EC-Lab is "
            "not registered as an OLE COM server by default: open an "
            "administrator command prompt in the EC-Lab install directory "
            "(e.g. C:\\Program Files (x86)\\EC-Lab) and run `ECLab /regserver`. "
            "It prints nothing on success."
        ) from exc


def _unpack(raw: Any) -> tuple[int, tuple]:
    """Split a COM return into ``(result, out_params)``.

    A scalar return is ``Result`` with no out-parameters; a tuple is
    ``Result`` followed by them.
    """
    if isinstance(raw, tuple):
        return int(raw[0]), tuple(raw[1:])
    return int(raw), ()


class OleComClient:
    """Every OLE COM call the driver makes, with failures named.

    The COM object is created on first use rather than at construction, so a
    client can be built on Linux -- and so a station's EC-Lab does not need to
    be running at the moment the driver object is made.
    """

    def __init__(
        self,
        progid: str = DEFAULT_PROGID,
        factory: Callable[[str], Any] = create_com_object,
    ):
        self.progid = progid
        self._factory = factory
        self._com: Optional[Any] = None

    @property
    def com(self) -> Any:
        """The COM object, created on first access."""
        if self._com is None:
            self._com = self._factory(self.progid)
        return self._com

    def _call(self, function: str, *args) -> tuple:
        """Invoke ``function``, raising ``OleComError`` on a ``0`` result."""
        result, outs = _unpack(getattr(self.com, function)(*args))
        if result != 1:
            raise OleComError(function, args, HINTS.get(function, "no detail"))
        return outs

    def _ask(self, function: str, *args) -> bool:
        """Invoke a function whose ``0`` is an answer, not a fault."""
        result, _ = _unpack(getattr(self.com, function)(*args))
        return result == 1

    # -- session ---------------------------------------------------------

    def enable_messages_windows(self, enabled: bool) -> None:
        """Enable or suppress EC-Lab's Windows message boxes.

        Suppressing them is mandatory for unattended operation: a modal dialog
        blocks the COM call that raised it, forever.
        """
        self._call("EnableMessagesWindows", int(bool(enabled)))

    def get_software_version(self) -> str:
        return str(self._call("GetSoftwareVersion")[0])

    # -- device ----------------------------------------------------------

    def connect_device_by_ip(self, ip: str) -> int:
        """Connect to the device at ``ip``, returning its device number.

        Adds the device to EC-Lab's list if absent. **This call auto-answers
        "Yes" to EC-Lab's firmware-upgrade prompt** (manual section 5.2.1) --
        the API offers no way to suppress it, so a connect can flash a
        production instrument. The driver warns before calling this.
        """
        return int(self._call("ConnectDeviceByIP", ip)[0])

    def disconnect_device(self, dev: int) -> None:
        self._call("DisconnectDevice", dev)

    def test_connection(self, dev: int) -> bool:
        return self._ask("TestConnection", dev)

    def get_device_type(self, dev: int) -> str:
        return str(self._call("GetDeviceType", dev)[0])

    def get_device_sn(self, dev: int) -> tuple[int, list[int]]:
        """``(device serial, per-channel serials)``; 0 means not plugged."""
        outs = self._call("GetDeviceSN", dev)
        return int(outs[0]), [int(sn) for sn in outs[1]]

    def get_device_channel_list(self, dev: int) -> list[bool]:
        """One flag per channel slot, True where a channel is present."""
        return [bool(flag) for flag in self._call("GetDeviceChannelList", dev)[0]]

    # -- channel ---------------------------------------------------------

    def is_channel_ready(self, dev: int, ch: int) -> bool:
        return self._ask("IsChannelReady", dev, ch)

    def load_settings(self, dev: int, ch: int, path: str) -> None:
        """Load an .mps or .mpr onto a channel.

        A ``0`` here is the only real pre-run validation the API offers: the
        manual states this returns False when the settings are incompatible
        with the hardware (bandwidth, IRange).
        """
        self._call("LoadSettings", dev, ch, path)

    def run_channel(self, dev: int, ch: int, out_base: str) -> None:
        self._call("RunChannel", dev, ch, out_base)

    def stop_channel(self, dev: int, ch: int) -> bool:
        """Stop the channel. ``False`` means it was already stopped."""
        return self._ask("StopChannel", dev, ch)

    def get_data_file_name(self, dev: int, ch: int, technique: int) -> str:
        """Absolute path of the MPR file for one technique on a channel."""
        return str(self._call("GetDataFileName", dev, ch, technique)[0])

    def measure_status(self, dev: int, ch: int) -> tuple[float, ...]:
        """The 32 status reals. Decode with ``status.decode_status``."""
        return tuple(float(v) for v in self._call("MeasureStatus", dev, ch)[0])

    # -- data ------------------------------------------------------------

    def measure_number_of_points(self, mpr: str) -> int:
        """Point count in an MPR file.

        Section 5.2.12: the ``Result`` *is* the count, so this does not go
        through ``_call``. Zero is an empty file, not a failure -- which is
        the normal state in the moments after ``RunChannel``.
        """
        result, _ = _unpack(getattr(self.com, "MeasureNumberOfPoints")(mpr))
        return int(result)

    def measure_dc_value(self, mpr: str, index: int) -> tuple[float, ...]:
        """``<t_s, Ewe_V, I_A>`` from a DC file. Current is 0 for OCV."""
        return tuple(float(v) for v in self._call("MeasureDcValue", mpr, index)[0])

    def measure_eis_value(self, mpr: str, index: int) -> tuple[float, ...]:
        """``<t_s, f_Hz, Re(Z), -Im(Z)>``. Frequency is 0 at a non-EIS index."""
        return tuple(float(v) for v in self._call("MeasureEisValue", mpr, index)[0])

    def measure_value_by_code(self, mpr: str, code: int, index: int) -> float:
        """One variable at one point. ``code`` is from appendix 7.2."""
        outs = self._call("MeasureValueByCode", mpr, code, index)
        return float(outs[0])
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest helao/deploy/hte/tests/test_ole_client.py -v`

Expected: 19 passed.

Note on `measure_value_by_code`: its signature is `(FileName, VarCode, DataIndex; out Data; out FunctionResult): Result`, and `Result == FunctionResult`. So the fake returns `(result, data, function_result)` and `_call` checks element 0 while the method reads element 1 — which is why the failing-case test passes `(0, 0.0, 0)` and expects a raise.

- [ ] **Step 5: Format and commit**

```bash
black helao/deploy/hte/drivers/pstat/biologic_ole/olecom_client.py \
      helao/deploy/hte/tests/test_ole_client.py
git add helao/deploy/hte/drivers/pstat/biologic_ole/olecom_client.py \
        helao/deploy/hte/tests/test_ole_client.py
git commit -m "feat(hte): typed OLE COM wrapper that names its failures

Every OLE function returns a bare 1/0 with no reason and the interface
validates nothing, so a 0 becomes an OleComError carrying the function,
the arguments and the likely cause. Four functions answer a question
rather than report a fault and must not raise: MeasureNumberOfPoints
(whose Result is the count), StopChannel, IsChannelReady, TestConnection.
comtypes is imported inside create_com_object, never at module scope.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: `sim.py` — a fake EC-Lab COM server

**Files:**
- Create: `helao/deploy/hte/drivers/pstat/biologic_ole/sim.py`
- Test: `helao/deploy/hte/tests/test_ole_sim.py`

**Interfaces:**
- Consumes: nothing (it deliberately does not import the client, so the client cannot accidentally depend on it).
- Produces: `SimConfig` (dataclass: `n_channels: int = 1`, `points_per_second: float = 100.0`, `run_seconds: float = 0.2`, `technique_code: int = 54`, `kind: str = "dc"`, `n_eis_points: int = 12`, `refuse_load: bool = False`, `refuse_run: bool = False`), `SimEcLab` (the fake COM object), `make_factory(config: SimConfig | None = None) -> Callable[[str], SimEcLab]`, and `set_sim_config`/`reset_sim` module helpers.

**Context the implementer needs.** The fake speaks the *raw* COM convention the wrapper's `_unpack` expects: PascalCase method names, a scalar or a `(Result, *out_params)` tuple. It must reproduce the failure behaviours that matter, not just the happy path — a fake that always succeeds tests nothing about the diagnostic layer that is most of Task 5. It also has to advance time, because the whole point is exercising the poll loop's cursor and its drain-on-done.

- [ ] **Step 1: Write the failing tests**

Create `helao/deploy/hte/tests/test_ole_sim.py`:

```python
"""The fake EC-Lab COM server.

EC-Lab and comtypes are Windows-only, so without this nothing in the package
past the pure text layer could be exercised at all. The fake reproduces the
*failure* behaviours as carefully as the happy path -- a LoadSettings that
never returns 0 would leave the diagnostic layer, which is most of the client,
untested.
"""

import pytest

from helao.deploy.hte.drivers.pstat.biologic_ole.olecom_client import (
    OleComClient,
    OleComError,
)
from helao.deploy.hte.drivers.pstat.biologic_ole.sim import SimConfig, make_factory
from helao.deploy.hte.drivers.pstat.biologic_ole.status import (
    ChannelState,
    decode_status,
)


def client(config: SimConfig | None = None) -> OleComClient:
    return OleComClient(factory=make_factory(config))


def test_the_client_drives_the_fake_end_to_end(tmp_path):
    cli = client(SimConfig(run_seconds=0.0))
    cli.enable_messages_windows(False)
    dev = cli.connect_device_by_ip("192.168.200.100")
    assert cli.test_connection(dev) is True
    assert cli.is_channel_ready(dev, 0) is True
    cli.load_settings(dev, 0, str(tmp_path / "x.mps"))
    cli.run_channel(dev, 0, str(tmp_path / "out"))
    assert cli.get_data_file_name(dev, 0, 0).endswith(".mpr")


def test_the_reported_software_version_clears_the_floor():
    assert client().get_software_version() == "11.72"


def test_a_channel_is_stopped_before_it_runs(tmp_path):
    cli = client()
    dev = cli.connect_device_by_ip("1.2.3.4")
    assert decode_status(cli.measure_status(dev, 0)).state is ChannelState.STOP


def test_a_running_channel_reports_run_then_stop(tmp_path):
    cli = client(SimConfig(run_seconds=0.05))
    dev = cli.connect_device_by_ip("1.2.3.4")
    cli.load_settings(dev, 0, str(tmp_path / "x.mps"))
    cli.run_channel(dev, 0, str(tmp_path / "out"))
    assert decode_status(cli.measure_status(dev, 0)).is_busy is True
    import time

    time.sleep(0.08)
    # Stop_rec1 is exactly one poll wide, so the first poll after run_seconds
    # elapses reports the tail and only the next reports Stop. Consuming it
    # here is not a timing workaround -- asserting Stop on the first
    # post-threshold poll fails 100% of the time, at any run_seconds.
    decode_status(cli.measure_status(dev, 0))
    assert decode_status(cli.measure_status(dev, 0)).state is ChannelState.STOP


def test_the_run_passes_through_the_recording_tail(tmp_path):
    """Stop_rec is a real state a poll loop must not read as finished."""
    cli = client(SimConfig(run_seconds=0.0))
    dev = cli.connect_device_by_ip("1.2.3.4")
    cli.load_settings(dev, 0, str(tmp_path / "x.mps"))
    cli.run_channel(dev, 0, str(tmp_path / "out"))
    seen = {decode_status(cli.measure_status(dev, 0)).state for _ in range(4)}
    assert ChannelState.STOP_REC1 in seen
    assert ChannelState.STOP in seen


def test_the_status_technique_code_is_the_configured_one(tmp_path):
    cli = client(SimConfig(technique_code=11))
    dev = cli.connect_device_by_ip("1.2.3.4")
    cli.load_settings(dev, 0, str(tmp_path / "x.mps"))
    assert decode_status(cli.measure_status(dev, 0)).technique_code == 11


def test_point_count_grows_while_running_and_settles(tmp_path):
    cli = client(SimConfig(run_seconds=0.05, points_per_second=200.0))
    dev = cli.connect_device_by_ip("1.2.3.4")
    cli.load_settings(dev, 0, str(tmp_path / "x.mps"))
    cli.run_channel(dev, 0, str(tmp_path / "out"))
    mpr = cli.get_data_file_name(dev, 0, 0)
    first = cli.measure_number_of_points(mpr)
    import time

    time.sleep(0.08)
    settled = cli.measure_number_of_points(mpr)
    assert settled >= first
    assert cli.measure_number_of_points(mpr) == settled


def test_dc_points_are_monotonic_in_time(tmp_path):
    cli = client(SimConfig(run_seconds=0.0))
    dev = cli.connect_device_by_ip("1.2.3.4")
    cli.load_settings(dev, 0, str(tmp_path / "x.mps"))
    cli.run_channel(dev, 0, str(tmp_path / "out"))
    mpr = cli.get_data_file_name(dev, 0, 0)
    n = cli.measure_number_of_points(mpr)
    times = [cli.measure_dc_value(mpr, i)[0] for i in range(n)]
    assert times == sorted(times)
    assert n > 0


def test_an_eis_file_serves_eis_values(tmp_path):
    cli = client(SimConfig(kind="eis", run_seconds=0.0, n_eis_points=5))
    dev = cli.connect_device_by_ip("1.2.3.4")
    cli.load_settings(dev, 0, str(tmp_path / "x.mps"))
    cli.run_channel(dev, 0, str(tmp_path / "out"))
    mpr = cli.get_data_file_name(dev, 0, 0)
    assert cli.measure_number_of_points(mpr) == 5
    t_s, f_hz, re_z, minus_im_z = cli.measure_eis_value(mpr, 0)
    assert f_hz > 0
    assert re_z != 0


def test_measure_value_by_code_serves_the_documented_codes(tmp_path):
    cli = client(SimConfig(run_seconds=0.0))
    dev = cli.connect_device_by_ip("1.2.3.4")
    cli.load_settings(dev, 0, str(tmp_path / "x.mps"))
    cli.run_channel(dev, 0, str(tmp_path / "out"))
    mpr = cli.get_data_file_name(dev, 0, 0)
    assert cli.measure_value_by_code(mpr, 4, 0) == pytest.approx(0.0)  # t_s
    assert cli.measure_value_by_code(mpr, 6, 0) != 0  # Ewe


def test_an_unrecorded_variable_code_is_refused(tmp_path):
    cli = client(SimConfig(run_seconds=0.0))
    dev = cli.connect_device_by_ip("1.2.3.4")
    cli.load_settings(dev, 0, str(tmp_path / "x.mps"))
    cli.run_channel(dev, 0, str(tmp_path / "out"))
    mpr = cli.get_data_file_name(dev, 0, 0)
    with pytest.raises(OleComError, match="MeasureValueByCode"):
        cli.measure_value_by_code(mpr, 999, 0)


def test_an_index_past_the_end_is_refused(tmp_path):
    cli = client(SimConfig(run_seconds=0.0))
    dev = cli.connect_device_by_ip("1.2.3.4")
    cli.load_settings(dev, 0, str(tmp_path / "x.mps"))
    cli.run_channel(dev, 0, str(tmp_path / "out"))
    mpr = cli.get_data_file_name(dev, 0, 0)
    with pytest.raises(OleComError, match="MeasureDcValue"):
        cli.measure_dc_value(mpr, 10_000)


def test_a_refused_load_raises_with_the_hardware_hint(tmp_path):
    cli = client(SimConfig(refuse_load=True))
    dev = cli.connect_device_by_ip("1.2.3.4")
    with pytest.raises(OleComError, match="incompatible with"):
        cli.load_settings(dev, 0, str(tmp_path / "x.mps"))


def test_running_without_loading_settings_is_refused(tmp_path):
    """RunChannel's documented failure: no settings loaded on the channel."""
    cli = client()
    dev = cli.connect_device_by_ip("1.2.3.4")
    with pytest.raises(OleComError, match="RunChannel"):
        cli.run_channel(dev, 0, str(tmp_path / "out"))


def test_stopping_an_idle_channel_answers_false_without_raising():
    cli = client()
    dev = cli.connect_device_by_ip("1.2.3.4")
    assert cli.stop_channel(dev, 0) is False


def test_an_unknown_device_number_is_refused():
    cli = client()
    with pytest.raises(OleComError, match="MeasureStatus"):
        cli.measure_status(99, 0)


def test_a_channel_beyond_the_configured_count_is_refused():
    cli = client(SimConfig(n_channels=1))
    dev = cli.connect_device_by_ip("1.2.3.4")
    with pytest.raises(OleComError, match="MeasureStatus"):
        cli.measure_status(dev, 5)


def test_the_channel_list_matches_the_configured_channel_count():
    cli = client(SimConfig(n_channels=3))
    dev = cli.connect_device_by_ip("1.2.3.4")
    flags = cli.get_device_channel_list(dev)
    assert flags[:3] == [True, True, True]
    assert not any(flags[3:])
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest helao/deploy/hte/tests/test_ole_sim.py -v`

Expected: collection error, `ModuleNotFoundError: No module named '...sim'`.

- [ ] **Step 3: Write `sim.py`**

```python
"""A fake EC-Lab OLE COM server, enough to exercise the whole driver.

EC-Lab and ``comtypes`` are Windows-only, so without this the package could be
tested no further than its pure-text layer. The fake speaks the same raw
convention ``olecom_client._unpack`` expects: PascalCase methods returning
either a scalar ``Result`` or a ``(Result, *out_params)`` tuple.

It reproduces the *failure* behaviours as carefully as the happy path, because
those are what most of the client exists to translate: a refused
``LoadSettings``, a ``RunChannel`` with nothing loaded, an index past the last
point, an unrecorded variable code, an unknown device or channel. A fake that
only ever succeeds would leave the diagnostic layer untested.

Time advances for real: ``run_seconds`` after ``RunChannel`` the channel walks
``Run`` -> ``Stop_rec1`` -> ``Stop``, so a poll loop's cursor and its
drain-on-done are genuinely exercised rather than asserted about.
"""

import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

__all__ = ["SimConfig", "SimEcLab", "make_factory", "reset_sim", "set_sim_config"]

#: Slot count EC-Lab reports per device, per manual section 5.2.4.
CHANNEL_SLOTS = 16

#: Variable codes the fake serves, matching technique.VAR_CODES. Any other
#: code is refused, which is what a real device does for a variable the
#: running technique does not record.
_DC_CODES = {4: "t_s", 6: "Ewe_V", 8: "I_A", 24: "cycle", 70: "P_W"}
_EIS_CODES = {
    4: "t_s", 6: "Ewe_V", 8: "I_A", 9: "Ece_V", 32: "f_Hz", 33: "AbsEwe_V",
    34: "AbsI_A", 35: "phase", 36: "modulus", 96: "AbsEce_V", 97: "AbsIce_A",
    98: "phase_ce", 99: "modulus_ce",
}


@dataclass
class SimConfig:
    """Shape of the simulated instrument and run.

    Attributes:
        n_channels: Channels this device reports as present.
        points_per_second: DC acquisition rate.
        run_seconds: Wall-clock length of a run. ``0.0`` finishes immediately
            but still passes through the recording-tail state.
        technique_code: What status index 5 reports. Defaults to 54 (the
            second-family CA code) so the two-family check is exercised.
        kind: ``"dc"`` or ``"eis"``.
        n_eis_points: Frequency points in an EIS sweep.
        refuse_load: Make ``LoadSettings`` return 0, as it does for settings
            incompatible with the hardware.
        refuse_run: Make ``RunChannel`` return 0 even with settings loaded.
    """

    n_channels: int = 1
    points_per_second: float = 100.0
    run_seconds: float = 0.2
    technique_code: int = 54
    kind: str = "dc"
    n_eis_points: int = 12
    refuse_load: bool = False
    refuse_run: bool = False


#: Module-level default, so a launched simulated server can be reconfigured
#: without threading a config object through the driver.
_CONFIG = SimConfig()


def set_sim_config(config: SimConfig) -> None:
    """Replace the module-level default configuration."""
    global _CONFIG
    _CONFIG = config


def current_config() -> SimConfig:
    """The module-level default configuration.

    Exposed so a caller can derive from it rather than replace it -- the
    driver imposes its own channel count without discarding whatever a test
    set for run length or technique kind.
    """
    return _CONFIG


def reset_sim() -> None:
    """Restore the stock default configuration."""
    set_sim_config(SimConfig())


@dataclass
class _Channel:
    loaded: bool = False
    started_at: Optional[float] = None
    mpr: str = ""


@dataclass
class _Device:
    ip: str
    channels: dict = field(default_factory=dict)


class SimEcLab:
    """The fake COM object. Method names are the manual's, verbatim."""

    def __init__(self, config: SimConfig):
        self.config = config
        self.devices: dict[int, _Device] = {}
        self.messages_enabled = True
        self._next_device = 0

    # -- helpers ---------------------------------------------------------

    def _channel(self, dev: int, ch: int) -> Optional[_Channel]:
        device = self.devices.get(dev)
        if device is None or not (0 <= ch < self.config.n_channels):
            return None
        return device.channels.setdefault(ch, _Channel())

    def _elapsed(self, channel: _Channel) -> float:
        if channel.started_at is None:
            return 0.0
        return time.monotonic() - channel.started_at

    def _state(self, channel: _Channel) -> int:
        """0 Stop, 1 Run, 4 Stop_rec1 -- the tail is one poll wide."""
        if channel.started_at is None:
            return 0
        elapsed = self._elapsed(channel)
        if elapsed < self.config.run_seconds:
            return 1
        if not getattr(channel, "_tail_seen", False):
            channel._tail_seen = True  # type: ignore[attr-defined]
            return 4
        return 0

    def _n_points(self, channel: _Channel) -> int:
        if channel.started_at is None:
            return 0
        if self.config.kind == "eis":
            return self.config.n_eis_points
        capped = min(self._elapsed(channel), self.config.run_seconds)
        # +1 so a zero-length run still yields a point rather than an empty
        # file, which would make every downstream test vacuous.
        return int(capped * self.config.points_per_second) + 1

    def _find_by_mpr(self, mpr: str) -> Optional[_Channel]:
        for device in self.devices.values():
            for channel in device.channels.values():
                if channel.mpr == mpr:
                    return channel
        return None

    def _dc_point(self, index: int) -> tuple[float, float, float]:
        t_s = index / self.config.points_per_second
        ewe = 0.5 * math.cos(index / 25.0)
        current = 1e-4 * math.sin(index / 25.0)
        return (t_s, ewe, current)

    def _eis_point(self, index: int) -> tuple[float, float, float, float]:
        t_s = float(index)
        decade = index / max(self.config.n_eis_points - 1, 1)
        f_hz = 10.0 ** (1.0 + 5.0 * decade)
        re_z = 50.0 + 100.0 / (1.0 + f_hz / 1000.0)
        minus_im_z = -30.0 * (f_hz / 1000.0) / (1.0 + (f_hz / 1000.0) ** 2)
        return (t_s, f_hz, re_z, minus_im_z)

    def _value_by_code(self, index: int, code: int) -> Optional[float]:
        if self.config.kind == "eis":
            if code not in _EIS_CODES:
                return None
            t_s, f_hz, re_z, minus_im_z = self._eis_point(index)
            modulus = math.hypot(re_z, minus_im_z)
            phase = math.atan2(-minus_im_z, re_z)
            return {
                4: t_s, 6: 0.25, 8: 1e-4, 9: -0.05, 32: f_hz, 33: 0.25,
                34: 1e-4, 35: phase, 36: modulus, 96: 0.05, 97: 1e-4,
                98: phase / 2.0, 99: modulus / 2.0,
            }[code]
        if code not in _DC_CODES:
            return None
        t_s, ewe, current = self._dc_point(index)
        return {4: t_s, 6: ewe, 8: current, 24: 0.0, 70: abs(ewe * current)}[code]

    # -- OLE COM surface -------------------------------------------------

    def EnableMessagesWindows(self, enabled: int):
        self.messages_enabled = bool(enabled)
        return (1, 1)

    def GetSoftwareVersion(self):
        return (1, "11.72")

    def ConnectDeviceByIP(self, ip: str):
        number = self._next_device
        self._next_device += 1
        self.devices[number] = _Device(ip=ip)
        return (1, number)

    def DisconnectDevice(self, dev: int):
        return 1 if self.devices.pop(dev, None) is not None else 0

    def TestConnection(self, dev: int):
        return 1 if dev in self.devices else 0

    def GetDeviceType(self, dev: int):
        return (1, "SP-300") if dev in self.devices else (0, "unknown device")

    def GetDeviceSN(self, dev: int):
        if dev not in self.devices:
            return (0, 0, (0,) * CHANNEL_SLOTS, 0)
        serials = tuple(
            39697 + i if i < self.config.n_channels else 0
            for i in range(CHANNEL_SLOTS)
        )
        return (1, 12345, serials, 1)

    def GetDeviceChannelList(self, dev: int):
        if dev not in self.devices:
            return (0, (0,) * CHANNEL_SLOTS)
        flags = tuple(
            1 if i < self.config.n_channels else 0 for i in range(CHANNEL_SLOTS)
        )
        return (1, flags)

    def IsChannelReady(self, dev: int, ch: int):
        channel = self._channel(dev, ch)
        if channel is None:
            return 0
        return 1 if self._state(channel) == 0 else 0

    def LoadSettings(self, dev: int, ch: int, path: str):
        channel = self._channel(dev, ch)
        if channel is None or self.config.refuse_load:
            return 0
        channel.loaded = True
        return 1

    def RunChannel(self, dev: int, ch: int, out_base: str):
        channel = self._channel(dev, ch)
        if channel is None or not channel.loaded or self.config.refuse_run:
            return 0
        channel.started_at = time.monotonic()
        channel._tail_seen = False  # type: ignore[attr-defined]
        channel.mpr = f"{out_base}_01_{self.config.kind.upper()}.mpr"
        return 1

    def StopChannel(self, dev: int, ch: int):
        channel = self._channel(dev, ch)
        if channel is None or channel.started_at is None:
            return 0
        channel.started_at = None
        return 1

    def GetDataFileName(self, dev: int, ch: int, technique: int):
        channel = self._channel(dev, ch)
        if channel is None or not channel.mpr:
            return (0, "")
        return (1, channel.mpr)

    def MeasureStatus(self, dev: int, ch: int):
        channel = self._channel(dev, ch)
        if channel is None:
            return (0, (0.0,) * 32)
        values = [0.0] * 32
        values[0] = float(self._state(channel))
        values[5] = float(self.config.technique_code)
        values[15] = self._elapsed(channel)
        n = self._n_points(channel)
        if n:
            if self.config.kind == "eis":
                values[16] = 0.25
                values[25], values[26] = self._eis_point(n - 1)[1:3]
            else:
                _, values[16], values[19] = self._dc_point(n - 1)
        values[27] = float(max(n - 1, 0))
        values[28] = float(max(n - 1, 0))
        return (1, tuple(values))

    def MeasureNumberOfPoints(self, mpr: str):
        channel = self._find_by_mpr(mpr)
        return 0 if channel is None else self._n_points(channel)

    def MeasureDcValue(self, mpr: str, index: int):
        channel = self._find_by_mpr(mpr)
        if channel is None or not (0 <= index < self._n_points(channel)):
            return (0, (0.0, 0.0, 0.0))
        return (1, self._dc_point(index))

    def MeasureEisValue(self, mpr: str, index: int):
        channel = self._find_by_mpr(mpr)
        if channel is None or not (0 <= index < self._n_points(channel)):
            return (0, (0.0, 0.0, 0.0, 0.0))
        return (1, self._eis_point(index))

    def MeasureValueByCode(self, mpr: str, code: int, index: int):
        channel = self._find_by_mpr(mpr)
        if channel is None or not (0 <= index < self._n_points(channel)):
            return (0, 0.0, 0)
        value = self._value_by_code(index, code)
        if value is None:
            return (0, 0.0, 0)
        return (1, value, 1)


def make_factory(config: Optional[SimConfig] = None) -> Callable[[str], Any]:
    """A ``OleComClient`` factory that yields a fresh fake per client.

    Fresh per client rather than shared, so one test's connected devices
    cannot leak into the next.
    """
    resolved = config if config is not None else _CONFIG
    return lambda progid: SimEcLab(resolved)
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest helao/deploy/hte/tests/test_ole_sim.py -v`

Expected: 18 passed. `test_a_running_channel_reports_run_then_stop` and `test_point_count_grows_while_running_and_settles` use real sleeps of under 100 ms; if either is flaky on a loaded machine, raise `run_seconds` rather than removing the timing assertion — the poll loop's correctness depends on the state actually advancing.

- [ ] **Step 5: Format and commit**

```bash
black helao/deploy/hte/drivers/pstat/biologic_ole/sim.py \
      helao/deploy/hte/tests/test_ole_sim.py
git add helao/deploy/hte/drivers/pstat/biologic_ole/sim.py \
        helao/deploy/hte/tests/test_ole_sim.py
git commit -m "feat(hte): fake EC-Lab COM server for Linux-side testing

Speaks the raw (Result, *out_params) convention the client unpacks, and
reproduces the failure paths -- refused LoadSettings, RunChannel with
nothing loaded, index past the end, unrecorded variable code, unknown
device or channel -- because those are what most of the client exists to
translate. Time advances for real, so the Run -> Stop_rec1 -> Stop walk
exercises a poll loop rather than being asserted about.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: `mpr_cursor.py` — point cursor and column assembly

**Files:**
- Create: `helao/deploy/hte/drivers/pstat/biologic_ole/mpr_cursor.py`
- Test: `helao/deploy/hte/tests/test_ole_mpr_cursor.py`

**Interfaces:**
- Consumes: `OleComClient` (Task 5), `ColumnPlan` (Task 3), `SimConfig`/`make_factory` (Task 6, tests only).
- Produces: `MprCursor` with `__init__(self, client: OleComClient, plan: ColumnPlan, mpr_path: str)`, `read_new(self, cycle: float = 0.0) -> dict[str, list[float]]`, `n_read: int` (property), `reset(self, mpr_path: str) -> None`, and the module function `empty_frame(plan: ColumnPlan) -> dict[str, list[float]]`.

**Context the implementer needs.** `read_new` returns only points not yet returned, so the driver can call it repeatedly and concatenate. A DC read is one `MeasureDcValue` per point plus zero extra calls (`P_W` is derived, `cycle` comes from the caller's status reading). An EIS read is one `MeasureEisValue` plus one `MeasureValueByCode` per `var_codes` entry per point. The manual's `MeasureDcValue` wording — "an array extracted from the MPR file, starting from the selected index" — leaves open whether it returns one point or many; `read_new` reads the length of what comes back and advances by that, so a bulk return needs no code change (at-station gate 3).

- [ ] **Step 1: Write the failing tests**

Create `helao/deploy/hte/tests/test_ole_mpr_cursor.py`:

```python
"""Turning MPR point reads into HELAO column dicts.

The cursor is what makes a poll loop possible over an API that has no
streaming: it remembers how many points it has already handed back, so the
driver can call it every tick and concatenate. It is also where the derived
columns are computed -- P_W, cycle, and the EIS pair -- so a mistake here is a
wrong number under a right column name, which no schema check would catch.
"""

import math

import pytest

from helao.deploy.hte.drivers.pstat.biologic_ole import technique as ot
from helao.deploy.hte.drivers.pstat.biologic_ole.mpr_cursor import (
    MprCursor,
    empty_frame,
)
from helao.deploy.hte.drivers.pstat.biologic_ole.olecom_client import OleComClient
from helao.deploy.hte.drivers.pstat.biologic_ole.sim import SimConfig, make_factory


def running_client(config: SimConfig) -> tuple[OleComClient, str]:
    """A client whose channel 0 has run to completion, plus its MPR path."""
    cli = OleComClient(factory=make_factory(config))
    dev = cli.connect_device_by_ip("1.2.3.4")
    cli.load_settings(dev, 0, "x.mps")
    cli.run_channel(dev, 0, "out")
    return cli, cli.get_data_file_name(dev, 0, 0)


def test_an_empty_frame_has_every_column_and_no_rows():
    frame = empty_frame(ot.resolve("CA").column_plan)
    assert set(frame) == set(ot.columns(ot.resolve("CA").column_plan))
    assert all(values == [] for values in frame.values())


def test_a_dc_read_returns_every_point_once():
    cli, mpr = running_client(SimConfig(run_seconds=0.0, points_per_second=100.0))
    cursor = MprCursor(cli, ot.resolve("CA").column_plan, mpr)
    first = cursor.read_new()
    assert len(first["t_s"]) == cli.measure_number_of_points(mpr)
    assert cursor.read_new()["t_s"] == []


def test_the_cursor_reports_how_many_points_it_has_read():
    cli, mpr = running_client(SimConfig(run_seconds=0.0))
    cursor = MprCursor(cli, ot.resolve("CA").column_plan, mpr)
    frame = cursor.read_new()
    assert cursor.n_read == len(frame["t_s"])


def test_every_dc_column_is_the_same_length():
    cli, mpr = running_client(SimConfig(run_seconds=0.0))
    frame = MprCursor(cli, ot.resolve("CA").column_plan, mpr).read_new(cycle=3.0)
    lengths = {name: len(values) for name, values in frame.items()}
    assert len(set(lengths.values())) == 1, lengths


def test_power_is_derived_as_the_absolute_product():
    """EC-Lab defines variable 70 as |Ewe * I|, so this is exact, not close."""
    cli, mpr = running_client(SimConfig(run_seconds=0.0))
    frame = MprCursor(cli, ot.resolve("CA").column_plan, mpr).read_new()
    for ewe, current, power in zip(frame["Ewe_V"], frame["I_A"], frame["P_W"]):
        assert power == pytest.approx(abs(ewe * current))


def test_cycle_is_stamped_from_the_callers_status_reading():
    cli, mpr = running_client(SimConfig(run_seconds=0.0))
    frame = MprCursor(cli, ot.resolve("CA").column_plan, mpr).read_new(cycle=7.0)
    assert set(frame["cycle"]) == {7.0}


def test_ocv_emits_only_time_and_potential():
    cli, mpr = running_client(SimConfig(run_seconds=0.0))
    frame = MprCursor(cli, ot.resolve("OCV").column_plan, mpr).read_new()
    assert set(frame) == {"t_s", "Ewe_V"}


def test_an_eis_read_fills_every_declared_column():
    cli, mpr = running_client(
        SimConfig(kind="eis", run_seconds=0.0, n_eis_points=6)
    )
    plan = ot.resolve("PEIS").column_plan
    frame = MprCursor(cli, plan, mpr).read_new()
    assert set(frame) == set(ot.columns(plan))
    assert all(len(values) == 6 for values in frame.values())


def test_the_impedance_pair_comes_straight_off_measure_eis_value():
    """R_ohm is Re(Z); X_ohm is the 'imaginary part', already -Im(Z)."""
    cli, mpr = running_client(
        SimConfig(kind="eis", run_seconds=0.0, n_eis_points=4)
    )
    frame = MprCursor(cli, ot.resolve("PEIS").column_plan, mpr).read_new()
    for index in range(4):
        _, _, re_z, minus_im_z = cli.measure_eis_value(mpr, index)
        assert frame["R_ohm"][index] == pytest.approx(re_z)
        assert frame["X_ohm"][index] == pytest.approx(minus_im_z)


def test_the_derived_pair_agrees_with_the_eclib_formula():
    """eclib computes R = |Z|cos(phase), X = -|Z|sin(phase). Same numbers."""
    cli, mpr = running_client(
        SimConfig(kind="eis", run_seconds=0.0, n_eis_points=4)
    )
    frame = MprCursor(cli, ot.resolve("PEIS").column_plan, mpr).read_new()
    for modulus, phase, r_ohm, x_ohm in zip(
        frame["modulus"], frame["phase"], frame["R_ohm"], frame["X_ohm"]
    ):
        assert r_ohm == pytest.approx(modulus * math.cos(phase))
        assert x_ohm == pytest.approx(-modulus * math.sin(phase))


def test_process_is_one_where_the_frequency_is_non_zero():
    """A non-EIS index returns frequency zero, per section 5.2.14."""
    cli, mpr = running_client(
        SimConfig(kind="eis", run_seconds=0.0, n_eis_points=4)
    )
    frame = MprCursor(cli, ot.resolve("PEIS").column_plan, mpr).read_new()
    for f_hz, process in zip(frame["f_Hz"], frame["process"]):
        assert process == (1.0 if f_hz else 0.0)


def test_reading_before_any_points_exist_returns_an_empty_frame():
    cli = OleComClient(factory=make_factory(SimConfig()))
    dev = cli.connect_device_by_ip("1.2.3.4")
    cli.load_settings(dev, 0, "x.mps")
    cursor = MprCursor(cli, ot.resolve("CA").column_plan, "nonexistent.mpr")
    frame = cursor.read_new()
    assert set(frame) == set(ot.columns(ot.resolve("CA").column_plan))
    assert frame["t_s"] == []


def test_reset_points_the_cursor_at_a_new_file_and_rewinds_it():
    """A multi-technique .mps has one MPR per technique."""
    cli, mpr = running_client(SimConfig(run_seconds=0.0))
    cursor = MprCursor(cli, ot.resolve("CA").column_plan, mpr)
    cursor.read_new()
    assert cursor.n_read > 0
    cursor.reset(mpr)
    assert cursor.n_read == 0
    assert len(cursor.read_new()["t_s"]) > 0


def test_a_second_read_after_new_points_returns_only_the_new_ones():
    cli, mpr = running_client(
        SimConfig(run_seconds=0.15, points_per_second=200.0)
    )
    cursor = MprCursor(cli, ot.resolve("CA").column_plan, mpr)
    first = len(cursor.read_new()["t_s"])
    import time

    time.sleep(0.2)
    second = len(cursor.read_new()["t_s"])
    total = cli.measure_number_of_points(mpr)
    assert first + second == total
    assert second > 0
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest helao/deploy/hte/tests/test_ole_mpr_cursor.py -v`

Expected: collection error, `ModuleNotFoundError: No module named '...mpr_cursor'`.

- [ ] **Step 3: Write `mpr_cursor.py`**

```python
"""Read new MPR points and assemble them into HELAO columns.

The OLE COM API has no streaming and no buffer drain: data is polled out of
the growing MPR file, one point at a time, through
``MeasureNumberOfPoints`` plus ``MeasureDcValue`` / ``MeasureEisValue`` /
``MeasureValueByCode``. The cursor is what turns that into something a poll
loop can use -- it remembers how many points it has already handed back, so
the driver calls ``read_new`` every tick and concatenates.

It is also where the derived columns are computed, which is the part worth
being careful about because a mistake is a wrong number under a right column
name:

* ``P_W`` is ``|Ewe * I|``. Not an approximation -- that is EC-Lab's own
  definition of variable 70, so fetching it would cost a call per point to
  learn the same number.
* ``cycle`` comes from status index 10, passed in by the caller, because it
  is a channel-level value rather than a per-point one.
* ``R_ohm`` is ``Re(Z)`` and ``X_ohm`` is ``MeasureEisValue``'s fourth
  element, which section 5.2.14 states is already ``-Im(Z)`` -- exactly what
  the eclib path computes as ``-modulus * sin(phase)``.
* ``process`` is reconstructed from the frequency: the same section states a
  non-EIS index returns frequency zero.

One deliberate accommodation. The manual describes ``MeasureDcValue`` as
returning an array "starting from the selected index", then lists three
values. Whether it yields one point or every remaining point is an at-station
probe. ``read_new`` advances by the length of what it actually received, so a
bulk return needs no change here -- it just gets faster.
"""

from .olecom_client import OleComClient, OleComError
from .technique import ColumnPlan, columns

__all__ = ["MprCursor", "empty_frame"]

#: Values MeasureDcValue returns, in order (section 5.2.13).
DC_FIELDS = ("t_s", "Ewe_V", "I_A")

#: Values MeasureEisValue returns, in order (section 5.2.14). The fourth is
#: already negated -- the manual says "the imaginary value is actually -Im(Z)".
EIS_FIELDS = ("t_s", "f_Hz", "R_ohm", "X_ohm")


def empty_frame(plan: ColumnPlan) -> dict[str, list[float]]:
    """A column dict with every declared column present and no rows.

    Every column present matters: a consumer that only ever sees the columns
    a particular poll happened to produce would key off a shape that changes
    between ticks.
    """
    return {name: [] for name in columns(plan)}


class MprCursor:
    """Hands back the MPR points not yet returned, as HELAO columns."""

    def __init__(self, client: OleComClient, plan: ColumnPlan, mpr_path: str):
        self.client = client
        self.plan = plan
        self.mpr_path = mpr_path
        self._n_read = 0

    @property
    def n_read(self) -> int:
        """How many points this cursor has already returned."""
        return self._n_read

    def reset(self, mpr_path: str) -> None:
        """Point at a new file and rewind.

        A multi-technique ``.mps`` -- CAOCV, or anything bracketed by TTL
        triggers -- writes one MPR per technique, so advancing to the next
        technique means resetting rather than constructing a new cursor and
        losing the plan.
        """
        self.mpr_path = mpr_path
        self._n_read = 0

    def read_new(self, cycle: float = 0.0) -> dict[str, list[float]]:
        """Every point since the last call.

        Args:
            cycle: Status index 10 at this poll, stamped across the points
                read. Ignored by plans that do not emit a ``cycle`` column.

        Returns:
            A column dict. Empty lists -- not an empty dict -- when there is
            nothing new, so a caller can extend unconditionally.
        """
        frame = empty_frame(self.plan)
        try:
            total = self.client.measure_number_of_points(self.mpr_path)
        except OleComError:
            # The file does not exist yet. Normal in the moments between
            # RunChannel and EC-Lab creating it; not a fault to report.
            return frame
        index = self._n_read
        while index < total:
            read = self._read_point(frame, index, cycle)
            if read == 0:
                # A point the file claims to hold but will not serve. Stop
                # rather than spin: the next poll retries from here.
                break
            index += read
        self._n_read = index
        return frame

    def _read_point(self, frame: dict, index: int, cycle: float) -> int:
        """Append the point(s) at ``index``. Returns how many were appended."""
        if self.plan.kind == "eis":
            return self._read_eis_point(frame, index)
        return self._read_dc_point(frame, index, cycle)

    def _read_dc_point(self, frame: dict, index: int, cycle: float) -> int:
        try:
            values = self.client.measure_dc_value(self.mpr_path, index)
        except OleComError:
            return 0
        # A bulk return arrives as a multiple of the three DC fields; a
        # single-point return is exactly three. Either advances correctly.
        stride = len(DC_FIELDS)
        count = max(len(values) // stride, 1)
        for offset in range(count):
            chunk = values[offset * stride : (offset + 1) * stride]
            point = dict(zip(DC_FIELDS, chunk))
            for name in ("t_s", "Ewe_V", "I_A"):
                if name in frame:
                    frame[name].append(point[name])
            if "P_W" in frame:
                frame["P_W"].append(abs(point["Ewe_V"] * point["I_A"]))
            if "cycle" in frame:
                frame["cycle"].append(cycle)
        return count

    def _read_eis_point(self, frame: dict, index: int) -> int:
        try:
            values = self.client.measure_eis_value(self.mpr_path, index)
        except OleComError:
            return 0
        point = dict(zip(EIS_FIELDS, values))
        for name in EIS_FIELDS:
            if name in frame:
                frame[name].append(point[name])
        if "process" in frame:
            frame["process"].append(1.0 if point["f_Hz"] else 0.0)
        for name, code in self.plan.var_codes.items():
            try:
                frame[name].append(
                    self.client.measure_value_by_code(self.mpr_path, code, index)
                )
            except OleComError:
                # A variable this technique does not record. NaN rather than a
                # gap, so every column stays the same length -- a short column
                # would misalign every row after it.
                frame[name].append(float("nan"))
        return 1
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest helao/deploy/hte/tests/test_ole_mpr_cursor.py -v`

Expected: 14 passed. If `test_the_derived_pair_agrees_with_the_eclib_formula` fails, check the sim's `_value_by_code` phase sign — `phase = atan2(-minus_im_z, re_z)` is deliberate, because `minus_im_z` is already negated.

- [ ] **Step 5: Format and commit**

```bash
black helao/deploy/hte/drivers/pstat/biologic_ole/mpr_cursor.py \
      helao/deploy/hte/tests/test_ole_mpr_cursor.py
git add helao/deploy/hte/drivers/pstat/biologic_ole/mpr_cursor.py \
        helao/deploy/hte/tests/test_ole_mpr_cursor.py
git commit -m "feat(hte): MPR point cursor and column assembly

Turns the API's per-point polling into a frame of new points per tick.
P_W is |Ewe*I|, which is EC-Lab's own definition of variable 70, so
fetching it would cost a call per point for the same number; R_ohm/X_ohm
come straight off MeasureEisValue, whose imaginary part is already
-Im(Z); process is reconstructed from a zero frequency. read_new advances
by the length received, so a bulk MeasureDcValue needs no change here.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: `driver.py` — `BiologicOleDriver`

**Files:**
- Create: `helao/deploy/hte/drivers/pstat/biologic_ole/driver.py`
- Test: `helao/deploy/hte/tests/test_ole_driver.py`

**Interfaces:**
- Consumes: everything from Tasks 1–7.
- Produces: `BiologicOleDriver(HelaoDriver)` with `connect()`, `get_status(channel=None)`, `setup(technique, action_params, output_dir=None)`, `start_channel(channel=0, ttl_params=None)`, `get_data(channel=0)` (async), `stop(channel=None)`, `cleanup(channel)`, `disconnect()`, `reset()`, `shutdown()`, plus `MIN_ECLAB_VERSION`, `templates_dir(config)` and the config keys it reads.

**Context the implementer needs.** `BiologicExec` calls `setup`, `start_channel`, `get_data`, `cleanup` and `stop`, and reads `resp.response`, `resp.status`, `resp.message` and `resp.data`. The message contract the executor depends on is exact: `_poll` finishes the action when `resp.message == "done"`. Config keys: `address` (the instrument IP, already in every station config), `num_channels`, `simulate`, `progid`, `templates_dir`, `scratch_dir`, `protocol_dir`, `com_timeout_s`. The driver runs every COM call in a thread executor under `asyncio.wait_for` for the synchronous path too — a modal dialog blocks a COM call forever, and a hung poll must not take the server with it.

- [ ] **Step 1: Write the failing tests**

Create `helao/deploy/hte/tests/test_ole_driver.py`:

```python
"""BiologicOleDriver, end to end against the fake COM server.

The driver is the only module that knows the *order* of the OLE calls, and
the order carries most of the correctness: EnableMessagesWindows before
anything can block on a dialog, IsChannelReady and LoadSettings before
RunChannel, and -- the one that truncates records when wrong -- finishing only
at state Stop with one further drain, never at Stop_rec.
"""

import asyncio

import pytest

from helao.core.drivers.helao_driver import DriverResponseType, DriverStatus
from helao.deploy.hte.drivers.pstat.biologic_ole import technique as ot
from helao.deploy.hte.drivers.pstat.biologic_ole.driver import BiologicOleDriver
from helao.deploy.hte.drivers.pstat.biologic_ole.sim import SimConfig, set_sim_config


@pytest.fixture(autouse=True)
def fast_sim():
    set_sim_config(SimConfig(run_seconds=0.0, points_per_second=100.0))
    yield
    set_sim_config(SimConfig())


def make_driver(**overrides) -> BiologicOleDriver:
    config = {"address": "192.168.200.100", "num_channels": 1, "simulate": True}
    config.update(overrides)
    return BiologicOleDriver(config=config)


def connected(**overrides) -> BiologicOleDriver:
    driver = make_driver(**overrides)
    assert driver.connect().response == DriverResponseType.success
    return driver


def test_construction_opens_nothing():
    """BaseAPI never calls connect(); the server does, at startup."""
    driver = make_driver()
    assert driver.ready is False


def test_connect_reports_success_and_marks_ready():
    driver = connected()
    assert driver.ready is True


def test_connect_suppresses_windows_message_boxes_first():
    """A modal dialog blocks the COM call that raised it, forever."""
    driver = connected()
    assert driver.client.com.messages_enabled is False


def test_connect_refuses_an_eclab_below_the_version_floor(monkeypatch):
    driver = make_driver()
    monkeypatch.setattr(
        type(driver), "_read_version", lambda self: "10.40", raising=False
    )
    response = driver.connect()
    assert response.response == DriverResponseType.failed
    assert "11.11" in response.message


def test_get_status_of_an_idle_channel_is_ok():
    driver = connected()
    response = driver.get_status(channel=0)
    assert response.status == DriverStatus.ok


def test_get_status_before_connect_is_uninitialized():
    assert make_driver().get_status().status == DriverStatus.uninitialized


def test_get_status_of_an_unknown_channel_is_uninitialized():
    assert connected().get_status(channel=9).status == DriverStatus.uninitialized


def test_setup_writes_a_patched_mps_and_loads_it(tmp_path):
    driver = connected(scratch_dir=str(tmp_path), templates_dir=str(tmp_path))
    (tmp_path / "CA.mps").write_text(
        "Technique : 1\nChronoamperometry\n"
        + mps_row("Ei (V)", "0.000")
        + mps_row("ti (h:m:s)", "0:00:10.0000")
        + mps_row("dta (s)", "0.0100"),
        encoding="latin-1",
    )
    response = driver.setup(
        technique=ot.resolve("CA"),
        action_params={"channel": 0, "Vval__V": 0.75, "Tval__s": 5.0},
    )
    assert response.response == DriverResponseType.success
    # By path, not by name: setup() writes the patched copy as
    # <scratch>/ch0/<uuid>/CA.mps -- technique_name is "CA" and the template
    # is "CA.mps", so the two share a basename and a name filter excludes the
    # very file it is looking for.
    template_path = tmp_path / "CA.mps"
    written = list(tmp_path.rglob("*.mps"))
    patched = [p for p in written if p != template_path]
    assert len(patched) == 1
    written = patched[0].read_text(encoding="latin-1")
    assert "0.750" in written
    assert "0:00:5.0000" in written


def test_setup_refuses_a_channel_that_does_not_exist(tmp_path):
    driver = connected(scratch_dir=str(tmp_path), templates_dir=str(tmp_path))
    response = driver.setup(
        technique=ot.resolve("CA"), action_params={"channel": 9}
    )
    assert response.response == DriverResponseType.failed


def test_setup_refuses_a_channel_already_in_use(tmp_path, ca_template):
    driver = connected(scratch_dir=str(tmp_path), templates_dir=str(ca_template))
    params = {"channel": 0, "Vval__V": 0.1, "Tval__s": 1.0}
    assert driver.setup(ot.resolve("CA"), params).response == "success"
    assert driver.setup(ot.resolve("CA"), params).response == "failed"


def test_a_refused_load_settings_names_the_hardware_hint(tmp_path, ca_template):
    set_sim_config(SimConfig(run_seconds=0.0, refuse_load=True))
    driver = connected(scratch_dir=str(tmp_path), templates_dir=str(ca_template))
    response = driver.setup(
        ot.resolve("CA"), {"channel": 0, "Vval__V": 0.1, "Tval__s": 1.0}
    )
    assert response.response == DriverResponseType.failed
    assert "incompatible" in response.message


def test_start_channel_reports_busy_and_a_start_time(tmp_path, ca_template):
    driver = connected(scratch_dir=str(tmp_path), templates_dir=str(ca_template))
    driver.setup(ot.resolve("CA"), {"channel": 0, "Vval__V": 0.1, "Tval__s": 1.0})
    response = driver.start_channel(0)
    assert response.status == DriverStatus.busy
    assert response.data["start_time"] > 0


def test_start_channel_refuses_a_channel_that_was_never_set_up():
    assert connected().start_channel(0).response == DriverResponseType.failed


def test_get_data_yields_points_and_finishes_at_done(tmp_path, ca_template):
    driver = connected(scratch_dir=str(tmp_path), templates_dir=str(ca_template))
    driver.setup(ot.resolve("CA"), {"channel": 0, "Vval__V": 0.1, "Tval__s": 1.0})
    driver.start_channel(0)
    messages, rows = [], 0
    for _ in range(10):
        response = asyncio.run(driver.get_data(0))
        messages.append(response.message)
        rows += len(response.data.get("t_s", []))
        if response.message == "done":
            break
    assert messages[-1] == "done"
    assert rows > 0


def test_the_recording_tail_is_not_reported_as_done(tmp_path, ca_template):
    """Stop_rec means 'writing the last points'. Finishing there truncates."""
    driver = connected(scratch_dir=str(tmp_path), templates_dir=str(ca_template))
    driver.setup(ot.resolve("CA"), {"channel": 0, "Vval__V": 0.1, "Tval__s": 1.0})
    driver.start_channel(0)
    first = asyncio.run(driver.get_data(0))
    assert first.message == "measuring"


def test_the_emitted_columns_are_the_technique_s_declared_set(
    tmp_path, ca_template
):
    driver = connected(scratch_dir=str(tmp_path), templates_dir=str(ca_template))
    driver.setup(ot.resolve("CA"), {"channel": 0, "Vval__V": 0.1, "Tval__s": 1.0})
    driver.start_channel(0)
    response = asyncio.run(driver.get_data(0))
    expected = set(ot.columns(ot.resolve("CA").column_plan))
    assert set(response.data) >= expected


def test_a_tripped_safety_limit_raises_an_alert_and_no_extra_column(
    tmp_path, ca_template, monkeypatch, caplog
):
    """The limit goes to LOGGER.alert, not into the data.

    Deliberately not a data column: the emitted column set is a frozen
    contract with two visualizer panels and five experiment libraries, and
    `test_biologic_column_contract.py` fails on any column the technique did
    not declare. A safety trip is an operator-facing event, not a datum.
    """
    driver = connected(scratch_dir=str(tmp_path), templates_dir=str(ca_template))
    driver.setup(ot.resolve("CA"), {"channel": 0, "Vval__V": 0.1, "Tval__s": 1.0})
    driver.start_channel(0)
    original = driver.client.com.MeasureStatus

    def tripped(dev, ch):
        result, values = original(dev, ch)
        values = list(values)
        values[0] = 0.0  # Stop, so get_data takes the finishing branch
        values[30] = 1.0  # Emax
        return (result, tuple(values))

    monkeypatch.setattr(driver.client.com, "MeasureStatus", tripped)
    with caplog.at_level("WARNING"):
        response = asyncio.run(driver.get_data(0))
    assert response.message == "done"
    assert "EMAX" in caplog.text
    assert "_safety_limit" not in response.data


def test_stop_on_an_idle_channel_is_not_an_error():
    """StopChannel returns 0 when already stopped; that is an answer."""
    assert connected().stop(channel=0).response == DriverResponseType.success


def test_stop_with_no_channel_stops_every_running_one(tmp_path, ca_template):
    driver = connected(scratch_dir=str(tmp_path), templates_dir=str(ca_template))
    driver.setup(ot.resolve("CA"), {"channel": 0, "Vval__V": 0.1, "Tval__s": 1.0})
    driver.start_channel(0)
    assert driver.stop().response == DriverResponseType.success


def test_cleanup_clears_the_channel_so_it_can_be_set_up_again(
    tmp_path, ca_template
):
    driver = connected(scratch_dir=str(tmp_path), templates_dir=str(ca_template))
    params = {"channel": 0, "Vval__V": 0.1, "Tval__s": 1.0}
    driver.setup(ot.resolve("CA"), params)
    assert driver.cleanup(0).response == DriverResponseType.success
    assert driver.setup(ot.resolve("CA"), params).response == "success"


def test_cleanup_moves_the_artifacts_into_the_action_directory(
    tmp_path, ca_template
):
    """The .mps and .mpr ship as provenance -- moved after the run, not during."""
    action_dir = tmp_path / "action"
    action_dir.mkdir()
    driver = connected(scratch_dir=str(tmp_path / "scratch"),
                       templates_dir=str(ca_template))
    driver.setup(
        ot.resolve("CA"),
        {"channel": 0, "Vval__V": 0.1, "Tval__s": 1.0},
        output_dir=str(action_dir),
    )
    driver.start_channel(0)
    for _ in range(10):
        if asyncio.run(driver.get_data(0)).message == "done":
            break
    driver.cleanup(0)
    assert list(action_dir.glob("*.mps")), list(action_dir.iterdir())


def test_disconnect_clears_ready():
    driver = connected()
    assert driver.disconnect().response == DriverResponseType.success
    assert driver.ready is False


def test_reset_reconnects():
    driver = connected()
    assert driver.reset().response == DriverResponseType.success
    assert driver.ready is True


def test_shutdown_stops_cleans_up_and_disconnects(tmp_path, ca_template):
    driver = connected(scratch_dir=str(tmp_path), templates_dir=str(ca_template))
    driver.setup(ot.resolve("CA"), {"channel": 0, "Vval__V": 0.1, "Tval__s": 1.0})
    driver.start_channel(0)
    driver.shutdown()
    assert driver.ready is False


def test_the_module_imports_without_comtypes():
    import sys

    assert "comtypes" not in sys.modules
```

Add this fixture at the top of the file, after the imports:

```python
def mps_row(label: str, *values: str) -> str:
    """One fixed-width .mps table row, as EC-Lab writes it (20 columns).

    Written this way rather than as a literal because the table is
    column-positional: a fixture with the wrong padding does not fail as a
    fixture, it fails as "the parser is broken".
    """
    return label.ljust(20) + "".join(v.ljust(20) for v in values) + "\n"


@pytest.fixture
def ca_template(tmp_path_factory):
    """A directory holding a minimal CA.mps the patcher can work on."""
    directory = tmp_path_factory.mktemp("templates")
    (directory / "CA.mps").write_text(
        "EC-LAB SETTING FILE\n\nNumber of linked techniques : 1\n\n"
        "Technique : 1\nChronoamperometry\n"
        + mps_row("Ei (V)", "0.000")
        + mps_row("ti (h:m:s)", "0:00:10.0000")
        + mps_row("dta (s)", "0.0100")
        + mps_row("dI", "10.000")
        + mps_row("unit dI", "mA")
        + mps_row("I Range", "Auto")
        + mps_row("E range min (V)", "-10.000")
        + mps_row("E range max (V)", "10.000")
        + mps_row("Bandwidth", "4"),
        encoding="latin-1",
    )
    return directory
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest helao/deploy/hte/tests/test_ole_driver.py -v`

Expected: collection error, `ImportError: cannot import name 'driver'` from the `biologic_ole` package.

- [ ] **Step 3: Write `driver.py`**

This is the largest module. Write it in one pass; the docstrings carry the reasoning that must survive.

```python
"""HelaoDriver over EC-Lab's OLE COM interface.

Composes the package's other modules -- ``olecom_client`` for the calls,
``mps_template`` and ``mps_assemble`` for the settings file, ``technique`` for
the mappings, ``status`` for the channel state, ``mpr_cursor`` for the data --
and is the only module that knows the *order* the calls go in. Most of the
correctness lives in that order.

Config keys, all optional except ``address``:

===================  ====================================================
``address``          Instrument IP. Passed to ``ConnectDeviceByIP``, which
                     adds it to EC-Lab's device list if absent.
``num_channels``     Channels this server drives. Default 12, as eclib.
``simulate``         Use the fake COM server (``sim.py``).
``progid``           EC-Lab's OLE ProgID, if not the default.
``templates_dir``    Where the ``.mps`` templates live. Defaults to the
                     package's own ``templates/``.
``scratch_dir``      Where patched settings and in-progress MPR files go.
``protocol_dir``     Where ``run_protocol`` resolves its ``mps_path``.
``com_timeout_s``    Per-call ceiling. Default 30.
===================  ====================================================

Three things about this driver are unlike its eclib sibling and are the ones
to keep in mind when editing it:

* **A channel finishes only at state ``Stop``, and then only after one more
  drain.** ``Stop_rec1``/``Stop_rec2`` mean the last points are being written.
  Reporting ``done`` there truncates the tail of every record, silently.
* **Every COM call is bounded.** A modal EC-Lab dialog blocks the call that
  raised it forever, so ``EnableMessagesWindows(0)`` runs first and calls
  still go through a thread executor under a timeout. As with
  ``OceanDirectExtrigExec``, that frees the caller and leaves the worker
  thread blocked -- the honest trade, since the alternative is a wedged
  server.
* **Artifacts move at cleanup, not during the run.** EC-Lab writes the MPR
  continuously and ``HelaoYml.misc_files`` globs live directories, so a file
  written straight into the action directory would be uploaded torn.
"""

import concurrent.futures
import shutil
import time
import uuid
from pathlib import Path
from typing import Optional

from helao.core.drivers.helao_driver import (
    DriverResponse,
    DriverResponseType,
    DriverStatus,
    HelaoDriver,
)
from helao.helpers import helao_logging as logging

from . import mps_assemble, mps_template
from .mpr_cursor import MprCursor
from .olecom_client import DEFAULT_PROGID, OleComClient, OleComError
from .status import ChannelStatus, SafetyLimit, decode_status
from .technique import OleTechnique, erange_rows, format_value, scale_to_unit

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

__all__ = ["MIN_ECLAB_VERSION", "BiologicOleDriver"]

#: Manual section 8.1. Below this the OLE COM interface does not exist.
MIN_ECLAB_VERSION = (11, 11)

#: Default per-call ceiling. Generous, because LoadSettings on a cold EC-Lab
#: is slow; the point is that nothing blocks forever, not that it is tight.
DEFAULT_COM_TIMEOUT_S = 30.0


def _version_tuple(text: str) -> tuple[int, ...]:
    """``"11.72"`` -> ``(11, 72)``. Non-numeric parts stop the parse."""
    parts: list[int] = []
    for chunk in text.strip().split("."):
        if not chunk.isdigit():
            break
        parts.append(int(chunk))
    return tuple(parts)


class BiologicOleDriver(HelaoDriver):
    """Drive a BioLogic potentiostat by piloting EC-Lab over OLE COM."""

    def __init__(self, config: dict = {}):
        """Store configuration. Opens nothing -- ``connect()`` does that.

        ``BaseAPI`` constructs drivers before the server is serving, and the
        eclib sibling was changed in P3a-2 to stop opening the instrument
        here. This one never did.
        """
        super().__init__(config=config)
        self.ready = False
        self.address = config.get("address", "192.168.200.240")
        self.num_channels = int(config.get("num_channels", 12))
        self.simulate = bool(config.get("simulate", False))
        self.progid = config.get("progid", DEFAULT_PROGID)
        self.com_timeout_s = float(
            config.get("com_timeout_s", DEFAULT_COM_TIMEOUT_S)
        )
        self.device_number: Optional[int] = None
        self.device_name = "unknown"
        self.client: Optional[OleComClient] = None
        self.channels: dict[int, Optional[OleTechnique]] = {
            i: None for i in range(self.num_channels)
        }
        self.channel_params: dict[int, dict] = {
            i: {} for i in range(self.num_channels)
        }
        self.cursors: dict[int, Optional[MprCursor]] = {
            i: None for i in range(self.num_channels)
        }
        self.scratch: dict[int, Optional[Path]] = {
            i: None for i in range(self.num_channels)
        }
        self.output_dirs: dict[int, Optional[Path]] = {
            i: None for i in range(self.num_channels)
        }
        self.stopping = False
        self._pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="olecom"
        )

    # -- paths -----------------------------------------------------------

    @property
    def templates_dir(self) -> Path:
        """Where the ``.mps`` templates live."""
        configured = self.config.get("templates_dir")
        if configured:
            return Path(configured)
        return Path(__file__).parent / "templates"

    @property
    def scratch_dir(self) -> Path:
        """Where patched settings and in-progress MPR files are written."""
        return Path(self.config.get("scratch_dir", Path.cwd() / "STATES" / "olecom"))

    @property
    def protocol_dir(self) -> Path:
        """Where ``run_protocol`` resolves a station-authored ``.mps``."""
        return Path(self.config.get("protocol_dir", self.templates_dir))

    # -- COM plumbing ----------------------------------------------------

    def _bounded(self, call, *args):
        """Run a COM call with a ceiling.

        The COM layer is synchronous and a modal dialog blocks it forever.
        The timeout frees this caller; the worker thread stays blocked, which
        is why ``EnableMessagesWindows(0)`` is not optional.
        """
        future = self._pool.submit(call, *args)
        return future.result(timeout=self.com_timeout_s)

    def _make_client(self) -> OleComClient:
        if self.simulate:
            from dataclasses import replace

            from . import sim as sim_module

            # WARNING, not INFO: a station left on `simulate: true` produces
            # plausible data from no instrument at all.
            LOGGER.warning(
                "BiologicOleDriver is SIMULATED (`simulate: true` on this "
                "server's params). No instrument is being driven."
            )
            # The fake device must report the channel count this server is
            # configured for. get_status() iterates range(num_channels), so a
            # sim left at its one-channel default makes every teardown log a
            # traceback -- caught, so nothing fails, which is why it survives
            # until someone reads the log. Derived from the module default so
            # a test that set run length or technique kind keeps them.
            sim_config = replace(
                sim_module.current_config(), n_channels=self.num_channels
            )
            return OleComClient(
                progid=self.progid, factory=sim_module.make_factory(sim_config)
            )
        return OleComClient(progid=self.progid)

    def _read_version(self) -> str:
        return self.client.get_software_version()

    # -- lifecycle -------------------------------------------------------

    def connect(self) -> DriverResponse:
        """Attach to EC-Lab and to the configured instrument.

        Order matters: message boxes are suppressed before anything that
        could raise one, and the version floor is checked before any call
        that a pre-11.11 EC-Lab would not have.
        """
        try:
            self.client = self._make_client()
            self._bounded(self.client.enable_messages_windows, False)
            version = self._bounded(self._read_version)
            if _version_tuple(version) < MIN_ECLAB_VERSION:
                floor = ".".join(str(p) for p in MIN_ECLAB_VERSION)
                return DriverResponse(
                    response=DriverResponseType.failed,
                    message=(
                        f"EC-Lab {version} is below the {floor} minimum for the "
                        "OLE COM interface (manual section 8.1)"
                    ),
                    status=DriverStatus.error,
                )
            # The manual states ConnectDevice auto-answers "Yes" to EC-Lab's
            # firmware-upgrade prompt and offers no way to suppress it. Warn
            # before the call, because after it the flash has already begun.
            LOGGER.warning(
                "connecting to %s: EC-Lab auto-accepts a firmware upgrade "
                "prompt in OLE COM mode and the API cannot suppress it",
                self.address,
            )
            self.device_number = self._bounded(
                self.client.connect_device_by_ip, str(self.address)
            )
            self.device_name = self._bounded(
                self.client.get_device_type, self.device_number
            )
            present = self._bounded(
                self.client.get_device_channel_list, self.device_number
            )
            LOGGER.info(
                "connected to %s (EC-Lab %s) at %s as device %s; channels present: %s",
                self.device_name,
                version,
                self.address,
                self.device_number,
                [i for i, flag in enumerate(present) if flag],
            )
            self.ready = True
            return DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception as exc:
            LOGGER.error("connect failed", exc_info=True)
            return DriverResponse(
                response=DriverResponseType.failed,
                message=str(exc),
                status=DriverStatus.error,
            )

    def _status_of(self, channel: int) -> ChannelStatus:
        return decode_status(
            self._bounded(self.client.measure_status, self.device_number, channel)
        )

    def get_status(self, channel: Optional[int] = None) -> DriverResponse:
        """Channel state, for one channel or all of them.

        ``data`` maps channel index to the raw status value, matching the
        eclib driver's shape so both backends report identically.
        """
        try:
            if not self.ready:
                return DriverResponse(
                    response=DriverResponseType.success,
                    status=DriverStatus.uninitialized,
                    data={},
                )
            if channel is None:
                states = {
                    i: self._status_of(i).state_raw for i in range(self.num_channels)
                }
                status = (
                    DriverStatus.busy
                    if any(v > 0 for v in states.values())
                    else DriverStatus.ok
                )
                return DriverResponse(
                    response=DriverResponseType.success, status=status, data=states
                )
            if channel not in self.channels:
                return DriverResponse(
                    response=DriverResponseType.success,
                    status=DriverStatus.uninitialized,
                    data={},
                )
            reading = self._status_of(channel)
            return DriverResponse(
                response=DriverResponseType.success,
                status=DriverStatus.busy if reading.is_busy else DriverStatus.ok,
                data={channel: reading.state_raw},
            )
        except Exception:
            LOGGER.error("get_status failed", exc_info=True)
            return DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )

    # -- setup -----------------------------------------------------------

    def _patch(self, technique: OleTechnique, action_params: dict):
        """The template with this action's parameters substituted in."""
        doc = mps_template.load(self.templates_dir / technique.template)
        for key, param in technique.parameter_map.items():
            if key not in action_params:
                continue
            value = action_params[key]
            # A list parameter (CAOCV's steps) fills one sequence column each.
            values = value if isinstance(value, (list, tuple)) else [value]
            for seq, item in enumerate(values):
                scope = param.technique
                if param.base_unit:
                    # EC-Lab spells a current, charge or frequency as a
                    # magnitude row plus a unit row, at three decimals -- so a
                    # 1 uA setpoint written unscaled lands as 0.000, and one
                    # written without its unit is read in whatever unit the
                    # template happened to carry.
                    magnitude, unit = scale_to_unit(item, param.base_unit)
                    doc = mps_template.set_param(
                        doc, param.param_id, magnitude, seq=seq, technique=scope
                    )
                    if param.unit_param_id:
                        doc = mps_template.set_param(
                            doc, param.unit_param_id, unit, seq=seq, technique=scope
                        )
                else:
                    doc = mps_template.set_param(
                        doc,
                        param.param_id,
                        format_value(item, param.fmt),
                        seq=seq,
                        technique=scope,
                    )
        # ERange is not one row but a symmetric min/max pair, so it is applied
        # here rather than through parameter_map. AUTO yields no rows and
        # leaves the template's own window standing.
        for key, scope in (("ERange", None), ("CA_ERange", 0)):
            if key in action_params:
                for caption, value in erange_rows(action_params[key]).items():
                    doc = mps_template.set_param(
                        doc, caption, value, technique=scope
                    )
        return doc

    def setup(
        self,
        technique: OleTechnique,
        action_params: dict = {},
        output_dir: Optional[str] = None,
    ) -> DriverResponse:
        """Patch the template, write it, and load it onto the channel.

        ``LoadSettings`` returning 0 is the only pre-run validation the API
        offers -- the manual states it fails on settings incompatible with the
        hardware -- so a bad bandwidth or IRange is caught here rather than at
        ``RunChannel``.
        """
        channel = action_params.get("channel", -1)
        try:
            if channel not in self.channels:
                raise ValueError(f"Channel {channel} does not exist.")
            if self.channels[channel] is not None:
                raise ValueError(f"Channel {channel} is in use.")
            doc = self._patch(technique, action_params)
            ttl = mps_assemble.ttl_plan_from_params(action_params)
            if ttl.is_active:
                doc = mps_assemble.assemble(
                    doc,
                    ttl,
                    mps_template.load(self.templates_dir / "TI.mps"),
                    mps_template.load(self.templates_dir / "TO.mps"),
                )
            run_dir = self.scratch_dir / f"ch{channel}" / uuid.uuid4().hex
            path = mps_template.write_patched(
                doc, run_dir / f"{technique.technique_name}.mps"
            )
            self._bounded(
                self.client.load_settings,
                self.device_number,
                channel,
                str(path.resolve()),
            )
            loaded = self._status_of(channel)
            if (
                loaded.technique_code
                and loaded.technique_code not in technique.technique_codes
            ):
                LOGGER.warning(
                    "channel %s loaded technique code %s; %s expects one of %s "
                    "-- the template may not hold the technique it is named for",
                    channel,
                    loaded.technique_code,
                    technique.technique_name,
                    sorted(technique.technique_codes),
                )
            self.channels[channel] = technique
            self.channel_params[channel] = dict(action_params)
            self.scratch[channel] = run_dir
            self.output_dirs[channel] = Path(output_dir) if output_dir else None
            return DriverResponse(
                response=DriverResponseType.success,
                message="setup complete",
                status=DriverStatus.ok,
            )
        except OleComError as exc:
            LOGGER.error("setup failed: %s", exc)
            self.cleanup(channel)
            return DriverResponse(
                response=DriverResponseType.failed,
                message=str(exc),
                status=DriverStatus.error,
            )
        except Exception as exc:
            LOGGER.error("setup failed", exc_info=True)
            self.cleanup(channel)
            return DriverResponse(
                response=DriverResponseType.failed,
                message=str(exc),
                status=DriverStatus.error,
            )

    # -- run -------------------------------------------------------------

    def start_channel(
        self, channel: int = 0, ttl_params: Optional[dict] = None
    ) -> DriverResponse:
        """Start the loaded technique.

        ``ttl_params`` is accepted for signature compatibility with the eclib
        driver and ignored: TTL is expressed as trigger techniques inside the
        ``.mps`` at ``setup`` time, because the OLE API has no trigger calls.
        """
        try:
            if self.channels.get(channel) is None:
                raise ValueError(f"Channel {channel} has not been set up.")
            if self._status_of(channel).is_busy:
                raise ValueError(f"Channel {channel} is busy.")
            out_base = str((self.scratch[channel] / "run").resolve())
            start_time = time.time()
            self._bounded(
                self.client.run_channel, self.device_number, channel, out_base
            )
            mpr = self._bounded(
                self.client.get_data_file_name, self.device_number, channel, 0
            )
            self.cursors[channel] = MprCursor(
                self.client, self.channels[channel].column_plan, mpr
            )
            return DriverResponse(
                response=DriverResponseType.success,
                message="measurement started",
                data={"start_time": start_time},
                status=DriverStatus.busy,
            )
        except Exception as exc:
            LOGGER.error("start_channel failed", exc_info=True)
            self.cleanup(channel)
            return DriverResponse(
                response=DriverResponseType.failed,
                message=str(exc),
                status=DriverStatus.error,
            )

    async def get_data(self, channel: int = 0) -> DriverResponse:
        """New points since the last call, plus the channel's state.

        ``message`` is the contract ``BiologicExec._poll`` reads: ``"done"``
        finishes the action. It is emitted only at state ``Stop``, and only
        after one further drain, because ``Stop_rec`` means the last points
        are still being written.
        """
        try:
            cursor = self.cursors.get(channel)
            if cursor is None:
                raise ValueError(f"Channel {channel} is not running.")
            reading = self._status_of(channel)
            data = cursor.read_new(cycle=reading.cycle)
            if reading.is_busy:
                return DriverResponse(
                    response=DriverResponseType.success,
                    message="measuring",
                    data=data,
                    status=DriverStatus.busy,
                )
            # Stopped: drain whatever landed between the read and the status.
            tail = cursor.read_new(cycle=reading.cycle)
            for name, values in tail.items():
                data.setdefault(name, []).extend(values)
            if reading.safety_limit not in (None, SafetyLimit.OK):
                LOGGER.alert(
                    "channel %s hit safety limit %s",
                    channel,
                    reading.safety_limit.name,
                )
            if not reading.connected:
                raise ConnectionError(f"Channel {channel} reports Disconnected.")
            return DriverResponse(
                response=DriverResponseType.success,
                message="done",
                data=data,
                status=DriverStatus.ok,
            )
        except Exception as exc:
            LOGGER.error("get_data failed", exc_info=True)
            return DriverResponse(
                response=DriverResponseType.failed,
                message=str(exc),
                status=DriverStatus.error,
            )

    # -- teardown --------------------------------------------------------

    def stop(self, channel: Optional[int] = None) -> DriverResponse:
        """Abort one channel, or every running one.

        ``StopChannel`` returning 0 means the channel was already stopped --
        an answer, not a fault, and not reported as one.
        """
        try:
            if self.stopping:
                return DriverResponse(
                    response=DriverResponseType.success, status=DriverStatus.ok
                )
            self.stopping = True
            try:
                targets = (
                    [channel]
                    if channel is not None
                    else [k for k, v in self.channels.items() if v is not None]
                )
                for target in targets:
                    if target not in self.channels:
                        LOGGER.warning("Channel %s does not exist.", target)
                        continue
                    if not self._bounded(
                        self.client.stop_channel, self.device_number, target
                    ):
                        LOGGER.info("Channel %s was already stopped.", target)
            finally:
                self.stopping = False
            return DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception as exc:
            LOGGER.error("stop failed", exc_info=True)
            return DriverResponse(
                response=DriverResponseType.failed,
                message=str(exc),
                status=DriverStatus.error,
            )

    def _ship_artifacts(self, channel: int) -> None:
        """Move the run's ``.mps`` and ``.mpr`` into the action directory.

        Moved at cleanup rather than written there: EC-Lab appends to the MPR
        for the whole run and ``HelaoYml.misc_files`` globs live directories,
        so a file written straight into the action directory could be uploaded
        half-finished. A failure here is logged and swallowed -- losing the
        provenance copy must not fail an otherwise good action.
        """
        run_dir, output_dir = self.scratch.get(channel), self.output_dirs.get(channel)
        if run_dir is None or output_dir is None or not run_dir.exists():
            return
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            for path in sorted(run_dir.iterdir()):
                if path.suffix.lower() in (".mps", ".mpr", ".mpt"):
                    shutil.move(str(path), str(output_dir / path.name))
        except Exception:
            LOGGER.warning(
                "could not ship OLE artifacts for channel %s from %s",
                channel,
                run_dir,
                exc_info=True,
            )

    def cleanup(self, channel: int) -> DriverResponse:
        """Release the channel and ship its artifacts. Stays connected."""
        try:
            if channel not in self.channels:
                raise ValueError(f"Channel {channel} does not exist.")
            if self.ready and self._status_of(channel).is_busy:
                raise ValueError(f"Channel {channel} is busy.")
            self._ship_artifacts(channel)
            self.channels[channel] = None
            self.channel_params[channel] = {}
            self.cursors[channel] = None
            self.scratch[channel] = None
            self.output_dirs[channel] = None
            return DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception as exc:
            LOGGER.error("cleanup failed", exc_info=True)
            return DriverResponse(
                response=DriverResponseType.failed,
                message=str(exc),
                status=DriverStatus.error,
            )

    def disconnect(self) -> DriverResponse:
        """Detach from the instrument. EC-Lab itself is left running."""
        try:
            if self.client is not None and self.device_number is not None:
                self._bounded(self.client.disconnect_device, self.device_number)
            LOGGER.info("disconnected from %s at %s", self.device_name, self.address)
            return DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception as exc:
            LOGGER.error("disconnect failed", exc_info=True)
            return DriverResponse(
                response=DriverResponseType.failed,
                message=str(exc),
                status=DriverStatus.error,
            )
        finally:
            self.device_number = None
            self.client = None
            self.ready = False

    def reset(self) -> DriverResponse:
        """Disconnect and reconnect, to recover from a bad state."""
        try:
            self.disconnect()
            return DriverResponse(
                response=DriverResponseType.success, status=DriverStatus.ok
            )
        except Exception:
            LOGGER.error("reset error", exc_info=True)
            return DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
        finally:
            self.connect()

    def shutdown(self) -> None:
        """Stop every running channel, clean up, disconnect. Called by BaseAPI."""
        try:
            states = self.get_status().data
            for channel, state in states.items():
                if state > 0:
                    self.stop(channel=channel)
                    self.cleanup(channel=channel)
        finally:
            self.disconnect()
            self._pool.shutdown(wait=False)
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest helao/deploy/hte/tests/test_ole_driver.py -v`

Expected: all pass. Two notes for when they do not:

- `test_setup_writes_a_patched_mps_and_loads_it` uses `tmp_path` as *both* templates and scratch dir, so it must exclude the template **by path**. The patched copy is `ch0/<uuid>/CA.mps` — same basename as the template, because `technique_name` is `CA`.
- `test_a_tripped_safety_limit_is_reported_on_the_response` monkeypatches the fake's `MeasureStatus`. If the run has already finished by then, the `or` branch of its assertion covers it — the point is that a tripped limit does not crash the poll.

- [ ] **Step 5: Format and commit**

```bash
black helao/deploy/hte/drivers/pstat/biologic_ole/driver.py \
      helao/deploy/hte/tests/test_ole_driver.py
git add helao/deploy/hte/drivers/pstat/biologic_ole/driver.py \
        helao/deploy/hte/tests/test_ole_driver.py
git commit -m "feat(hte): BiologicOleDriver over the EC-Lab OLE COM interface

The ten-method HelaoDriver surface, composed from the package's other
modules. Finishes only at state Stop and only after one further drain,
because Stop_rec means the last points are still being written. Bounds
every COM call, since a modal EC-Lab dialog blocks one forever. Ships the
.mps and .mpr into the action directory at cleanup rather than writing
them there, so SYNC cannot glob a half-written MPR.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: existing-code hygiene — Protocol, hermetic `enum.py`, coercion moved

**Files:**
- Create: `helao/deploy/hte/drivers/pstat/biologic_backend.py`
- Modify: `helao/deploy/hte/drivers/pstat/biologic/enum.py`
- Modify: `helao/deploy/hte/drivers/pstat/biologic/driver.py` (`setup`)
- Modify: `helao/deploy/hte/servers/action/biologic_server.py` (remove the endpoint coercion, pass `output_dir`)
- Test: `helao/hexagon/tests/test_biologic_disconnected_construct.py` (extend)

**Interfaces:**
- Consumes: nothing new.
- Produces: `BiologicBackend` (a `typing.Protocol`), and in `biologic/enum.py` the callables `ec_irange(value)`, `ec_erange(value)`, `ec_bandwidth(value)` replacing the eager `EC_*_map` dicts (the dicts stay, built lazily behind a function, so any out-of-tree importer keeps working).

**Context the implementer needs.** Three separate defects, all in the path this work lands in, all fixed together because they are one change from the server's point of view.

1. `biologic/enum.py` does `from easy_biologic.lib.ec_lib import Bandwidth, ERange, IRange` at module scope, and `biologic_server.py` imports it. A Windows station with EC-Lab but no easy-biologic cannot import the BIOLOGIC server at all.
2. Each endpoint body does `active.action.action_params["IRange"] = EC_IRange_map[...]` — eclib-specific coercion in the layer both backends share.
3. `setup()` has no way to learn the action's output directory, which the OLE driver needs in order to ship its artifacts.

Moving the coercion changes what is recorded: the action `.yml` will carry `"AUTO"`/`"m1"`/`"BW4"` instead of the vendor enum's serialized integer. That is a deliberate, spec-approved change (spec decision 6). Callers already pass strings and nothing in tracked code reads the value back.

- [ ] **Step 1: Write the failing tests**

Append to `helao/hexagon/tests/test_biologic_disconnected_construct.py`:

```python
def test_enum_module_does_not_load_the_vendor_sdk():
    """An EC-Lab-only Windows station must be able to import the server.

    enum.py imported easy_biologic at module scope, and biologic_server.py
    imports enum.py -- so a station running the OLE backend without
    easy-biologic installed could not import its own action server. driver.py
    and technique.py were made hermetic in P3a-2; this one was missed.
    """
    from helao.deploy.hte.drivers.pstat.biologic import enum as biologic_enum

    assert "easy_biologic" not in sys.modules
    assert biologic_enum.EC_IRange.AUTO == "AUTO"


def test_the_enum_resolvers_are_lazy(monkeypatch):
    """The maps resolve against the vendor package only when called."""
    import types

    from helao.deploy.hte.drivers.pstat.biologic import enum as biologic_enum

    fake = types.ModuleType("easy_biologic.lib.ec_lib")

    class _IRange:
        AUTO = "vendor-auto"

    class _ERange:
        AUTO = "vendor-erange"

    class _Bandwidth:
        BW4 = "vendor-bw4"

    fake.IRange = _IRange
    fake.ERange = _ERange
    fake.Bandwidth = _Bandwidth
    monkeypatch.setitem(sys.modules, "easy_biologic", types.ModuleType("easy_biologic"))
    monkeypatch.setitem(sys.modules, "easy_biologic.lib", types.ModuleType("easy_biologic.lib"))
    monkeypatch.setitem(sys.modules, "easy_biologic.lib.ec_lib", fake)
    # _maps() is lru_cached, so a cache populated by an earlier test would
    # make this pass or fail by test ordering rather than by behaviour.
    biologic_enum._maps.cache_clear()
    monkeypatch.setattr(
        biologic_enum._maps, "cache_clear", biologic_enum._maps.cache_clear
    )

    assert biologic_enum.ec_irange("AUTO") == "vendor-auto"
    assert biologic_enum.ec_erange("AUTO") == "vendor-erange"
    assert biologic_enum.ec_bandwidth("BW4") == "vendor-bw4"
    # Leave no fake-derived entries behind for the next test.
    biologic_enum._maps.cache_clear()


def test_the_ole_package_imports_without_any_vendor_package():
    from helao.deploy.hte.drivers.pstat.biologic_ole.driver import BiologicOleDriver

    driver = BiologicOleDriver(config={"num_channels": 3, "simulate": True})
    assert driver.ready is False
    assert driver.client is None
    assert len(driver.channels) == 3
    assert "comtypes" not in sys.modules
    assert "easy_biologic" not in sys.modules


def test_both_drivers_satisfy_the_backend_protocol():
    """The contract the action server calls, made explicit."""
    from helao.deploy.hte.drivers.pstat.biologic.driver import BiologicDriver
    from helao.deploy.hte.drivers.pstat.biologic_backend import BiologicBackend
    from helao.deploy.hte.drivers.pstat.biologic_ole.driver import BiologicOleDriver

    for cls in (BiologicDriver, BiologicOleDriver):
        for name in (
            "connect", "get_status", "setup", "start_channel", "get_data",
            "stop", "cleanup", "disconnect", "reset", "shutdown",
        ):
            assert callable(getattr(cls, name)), (cls.__name__, name)
    assert BiologicBackend is not None


def test_the_endpoints_no_longer_coerce_the_range_enums():
    """Coercion belongs in each backend's setup(), not the shared layer."""
    from pathlib import Path

    source = Path(
        "helao/deploy/hte/servers/action/biologic_server.py"
    ).read_text()
    assert "EC_IRange_map[" not in source
    assert "EC_ERange_map[" not in source
    assert "EC_Bandwidth_map[" not in source
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest helao/hexagon/tests/test_biologic_disconnected_construct.py -v`

Expected: the four pre-existing tests pass; `test_enum_module_does_not_load_the_vendor_sdk` fails with an `ImportError`/`OSError` at import (or an assertion that `easy_biologic` is in `sys.modules`), and the other four fail on missing names.

- [ ] **Step 3: Make `enum.py` hermetic**

In `helao/deploy/hte/drivers/pstat/biologic/enum.py`, delete the module-scope import line:

```python
from easy_biologic.lib.ec_lib import Bandwidth, ERange, IRange
```

Keep the three `StrEnum` classes exactly as they are, add `from functools import lru_cache` to the top, and replace the three `EC_*_map` dicts at the bottom of the file with:

```python
from functools import lru_cache


def _ec_lib():
    """The vendor enum module, imported on first use.

    Imported lazily because ``biologic_server.py`` imports this module, and a
    station running the OLE COM backend has EC-Lab but not necessarily
    easy-biologic. An eager import there made that station's action server
    unimportable. ``driver.py`` and ``technique.py`` were made hermetic in
    P3a-2; this module was missed because nothing then needed it to be.
    """
    from easy_biologic.lib.ec_lib import Bandwidth, ERange, IRange

    return IRange, ERange, Bandwidth


@lru_cache(maxsize=1)
def _maps() -> tuple:
    """The vendor ``(IRange, ERange, Bandwidth)`` classes, cached on first use.

    Resolution is **per member**, not eager whole-map construction. Building
    dicts here would force every alias to resolve against the vendor package
    on the first call, which is more than "resolve when called" requires --
    and it breaks any caller or test holding a partial stand-in for the
    vendor module, since a missing member raises before the wanted one is
    ever reached. Kept named ``_maps`` because the laziness test clears its
    cache by that name.
    """
    return _ec_lib()


def ec_irange(value):
    """The vendor ``IRange`` member for a string alias or ``EC_IRange``."""
    IRange, _, _ = _maps()
    return getattr(IRange, EC_IRange(value).value)


def ec_erange(value):
    """The vendor ``ERange`` member for a string alias or ``EC_ERange``."""
    _, ERange, _ = _maps()
    return getattr(ERange, EC_ERange(value).value)


def ec_bandwidth(value):
    """The vendor ``Bandwidth`` member for a string alias or ``EC_Bandwidth``."""
    _, _, Bandwidth = _maps()
    return getattr(Bandwidth, EC_Bandwidth(value).value)
```

Note that `getattr(IRange, alias.value)` works because every `EC_IRange` member's value is spelled identically to the vendor member's name (`p100`, `n1`, ..., `AUTO`) — that correspondence is what the original hand-written dicts encoded, and a test in Step 1 pins it through the fake.

- [ ] **Step 4: Coerce in the eclib driver's `setup()`**

In `helao/deploy/hte/drivers/pstat/biologic/driver.py`, add the import at the top of the file:

```python
from .enum import ec_bandwidth, ec_erange, ec_irange
```

and in `setup()`, immediately after `parmap = technique.parameter_map`, insert:

```python
        # The endpoints used to do this before dispatching the executor, but
        # that put easy-biologic-specific objects in the layer the OLE backend
        # also uses. Coercing here keeps action_params carrying the plain
        # string -- which is also the more legible thing to record.
        coercers = {
            "IRange": ec_irange,
            "ERange": ec_erange,
            "Bandwidth": ec_bandwidth,
            "CA_IRange": ec_irange,
            "CA_ERange": ec_erange,
            "CA_Bandwidth": ec_bandwidth,
        }
        action_params = {
            key: coercers[key](value) if key in coercers else value
            for key, value in action_params.items()
        }
```

Also widen the signature so both backends take the same call:

```python
    def setup(
        self,
        technique: BiologicTechnique,
        action_params: dict = {},
        output_dir: Optional[str] = None,
    ) -> DriverResponse:
```

and add to its docstring:

```
            output_dir: Absolute path of the action's output directory.
                Accepted for signature parity with the OLE backend, which
                ships its vendor artifacts there. Unused here.
```

- [ ] **Step 5: Write the Protocol**

Create `helao/deploy/hte/drivers/pstat/biologic_backend.py`:

```python
"""The contract ``biologic_server`` calls, satisfied by both backends.

There is deliberately **no shared base class**. The two BioLogic drivers have
almost no implementation in common -- one talks to a firmware DLL over TCP,
the other automates a GUI application over files -- so a base would be an
empty shell that invited the wrong things to be hoisted into it. What they
genuinely share is this call surface, and a Protocol states it without
creating a dependency in either direction.

Structural, not nominal: neither driver inherits from this, and pyright checks
the conformance. The module imports nothing from either package, so it costs
nothing to import anywhere.
"""

from typing import Any, Optional, Protocol, runtime_checkable

__all__ = ["BiologicBackend"]


@runtime_checkable
class BiologicBackend(Protocol):
    """What a BioLogic backend must provide to the action server."""

    ready: bool

    def connect(self) -> Any:
        """Attach to the instrument. Called once at server startup."""

    def get_status(self, channel: Optional[int] = None) -> Any:
        """Channel state, for one channel or all of them."""

    def setup(
        self,
        technique: Any,
        action_params: dict = ...,
        output_dir: Optional[str] = None,
    ) -> Any:
        """Configure a channel for the technique described by ``technique``.

        ``technique`` is backend-specific -- a ``BiologicTechnique`` for the
        eclib backend, an ``OleTechnique`` for the OLE one -- which is why it
        is untyped here. The executor picks the right registry per backend.
        """

    def start_channel(
        self, channel: int = 0, ttl_params: Optional[dict] = None
    ) -> Any:
        """Start the configured technique on ``channel``."""

    async def get_data(self, channel: int = 0) -> Any:
        """New data since the last call.

        ``message`` must be ``"done"`` exactly when the technique has
        finished; ``BiologicExec._poll`` reads that string to end the action.
        """

    def stop(self, channel: Optional[int] = None) -> Any:
        """Abort one channel, or every running one."""

    def cleanup(self, channel: int) -> Any:
        """Release a channel. Must not disconnect the instrument."""

    def disconnect(self) -> Any:
        """Detach from the instrument."""

    def reset(self) -> Any:
        """Disconnect and reconnect."""

    def shutdown(self) -> None:
        """Stop everything and disconnect. Called by ``BaseAPI`` at exit."""
```

- [ ] **Step 6: Strip the coercion from the endpoints**

In `helao/deploy/hte/servers/action/biologic_server.py`, delete every one of these blocks (they appear in `run_CA`, `run_CP`, `run_CV`, `run_PEIS`, `run_GEIS`, and in `run_CAOCV` with the `CA_` prefix):

```python
        active.action.action_params["IRange"] = EC_IRange_map[
            active.action.action_params["IRange"]
        ]
        active.action.action_params["ERange"] = EC_ERange_map[
            active.action.action_params["ERange"]
        ]
        active.action.action_params["Bandwidth"] = EC_Bandwidth_map[
            active.action.action_params["Bandwidth"]
        ]
```

Then narrow the import at the top of the file from six names to three — the `EC_*_map` dicts are no longer referenced here:

```python
from ...drivers.pstat.biologic.enum import EC_Bandwidth, EC_ERange, EC_IRange
```

Leave every other line of every endpoint untouched, including `active.action.action_params["AcqInterval__A"] = 10.0` and the `Cycles -= 1` in `run_CV`, which are technique semantics rather than backend coupling.

- [ ] **Step 7: Pass the output directory to `setup()`**

In `BiologicExec._pre_exec`, replace the `self.driver.setup(...)` call with:

```python
            resp = self.driver.setup(
                technique=self.technique,
                action_params=self.action_params,
                output_dir=self._action_output_path(),
            )
```

and add this method to `BiologicExec`, above `_pre_exec`:

```python
    def _action_output_path(self) -> Optional[str]:
        """Absolute path of this action's output directory, or None.

        ``action_output_dir`` is stored *relative* to the run root, so it must
        be joined with ``helaodirs.save_root`` -- and a manual action's root
        is redirected from ACTIVE to DIAG, exactly as ``ActionSession`` does
        when it creates the directory. Returns None rather than guessing if
        the action is not saving, so the OLE backend simply keeps its vendor
        artifacts in scratch.
        """
        action = self.active.action
        if not action.save_act or not action.action_output_dir:
            return None
        try:
            save_root = str(self.active.base.helaodirs.save_root)
        except AttributeError:
            return None
        if action.manual_action:
            save_root = save_root.replace("ACTIVE", "DIAG")
        return os.path.join(save_root, str(action.action_output_dir))
```

Add `import os` to the module's imports if it is not already present.

- [ ] **Step 8: Run the tests and verify they pass**

```bash
pytest helao/hexagon/tests/test_biologic_disconnected_construct.py -v
pytest helao/deploy/hte/tests/test_ole_driver.py -v
pytest helao/hexagon/tests/test_hte_route_checklist.py -v
```

Expected: all pass. The route checklist must still pass unchanged — removing the coercion touches endpoint *bodies*, not signatures, so no route, parameter, annotation or default moved.

- [ ] **Step 9: Format and commit**

```bash
black helao/deploy/hte/drivers/pstat/biologic_backend.py \
      helao/deploy/hte/drivers/pstat/biologic/enum.py \
      helao/deploy/hte/drivers/pstat/biologic/driver.py \
      helao/deploy/hte/servers/action/biologic_server.py \
      helao/hexagon/tests/test_biologic_disconnected_construct.py
git add helao/deploy/hte/drivers/pstat/biologic_backend.py \
        helao/deploy/hte/drivers/pstat/biologic/enum.py \
        helao/deploy/hte/drivers/pstat/biologic/driver.py \
        helao/deploy/hte/servers/action/biologic_server.py \
        helao/hexagon/tests/test_biologic_disconnected_construct.py
git commit -m "refactor(hte): make biologic/enum.py hermetic, coerce ranges in setup()

enum.py imported easy_biologic at module scope and biologic_server.py
imports enum.py, so an EC-Lab-only Windows station could not import its
own action server. The maps now resolve lazily.

The endpoints' EC_*_map coercion moves into each backend's setup(): it
was easy-biologic-specific logic in the layer both backends share. The
recorded action param becomes the string 'AUTO'/'m1'/'BW4' rather than
the vendor enum's integer -- a deliberate change, spec decision 6.

Adds the BiologicBackend Protocol and threads the action output directory
into setup() so the OLE backend can ship its vendor artifacts.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: backend selection in `biologic_server.py`

**Files:**
- Modify: `helao/deploy/hte/servers/action/biologic_server.py`
- Test: `helao/hexagon/tests/test_biologic_backend_select.py`

**Interfaces:**
- Consumes: `BiologicDriver`, `BiologicOleDriver`.
- Produces: in `biologic_server`: `BACKENDS: dict[str, type]`, `DEFAULT_BACKEND: str`, `_driver_class(server_key: str) -> type`, `_backend_name(server_key: str) -> str`, and `TECHNIQUE_REGISTRIES: dict[str, Callable[[str], Any]]` so `BiologicExec` resolves the right technique object per backend.

**Context the implementer needs.** This mirrors `andor_server._driver_class` exactly — read `helao/deploy/hte/servers/action/andor_server.py:469-501` and follow it. The one extra thing this server needs that ANDOR does not: the two backends take *different technique objects*, so the endpoints cannot pass a module-level `TECH_CA` constant directly. They pass the technique *name* and the executor resolves it against the selected backend's registry.

- [ ] **Step 1: Write the failing tests**

Create `helao/hexagon/tests/test_biologic_backend_select.py`:

```python
"""`pstat_backend` picks the driver class, and its default keeps six configs valid.

The default matters more than the key. hispec, odspechw, clad, adss3,
htereflex and htehexreflex all declare a BIOLOGIC server with no
`pstat_backend`, and none of them may need editing for this to land.
"""

import pytest

from helao.deploy.hte.drivers.pstat.biologic.driver import BiologicDriver
from helao.deploy.hte.drivers.pstat.biologic_ole.driver import BiologicOleDriver
from helao.deploy.hte.servers.action import biologic_server
from helao.helpers import config_loader


@pytest.fixture
def with_config(monkeypatch):
    def _set(params):
        monkeypatch.setattr(
            config_loader,
            "CONFIG",
            {
                # `root`, `host` and `port` are not decoration: the first
                # ActionHost built in a process initializes the logger under
                # <root>/LOGS and reads host/port from the server entry, so a
                # config without them raises before any route is registered.
                # `test_action_host_surface.py`'s `_host()` does the same, for
                # the same reason. It bites here because tests are run one
                # file per pytest process, so nothing has warmed the logger.
                "root": tempfile.mkdtemp(prefix="helao_biologic_backend_test_"),
                "servers": {
                    "BIOLOGIC": {
                        "group": "action",
                        "host": "127.0.0.1",
                        "port": 8000,
                        "params": params,
                    }
                },
            },
        )

    return _set


def test_an_absent_key_yields_the_eclib_driver(with_config):
    """Six live configs declare no pstat_backend and must keep working."""
    with_config({"address": "192.168.200.100", "num_channels": 1})
    assert biologic_server._driver_class("BIOLOGIC") is BiologicDriver


def test_eclib_is_selectable_explicitly(with_config):
    with_config({"pstat_backend": "eclib"})
    assert biologic_server._driver_class("BIOLOGIC") is BiologicDriver


def test_olecom_selects_the_ole_driver(with_config):
    with_config({"pstat_backend": "olecom"})
    assert biologic_server._driver_class("BIOLOGIC") is BiologicOleDriver


def test_an_unknown_value_is_refused_loudly(with_config):
    """A typo must not hand an EC-Lab station the eclib driver."""
    with_config({"pstat_backend": "olecomm"})
    with pytest.raises(ValueError, match="olecomm"):
        biologic_server._driver_class("BIOLOGIC")


def test_the_refusal_lists_the_valid_values(with_config):
    with_config({"pstat_backend": "ole"})
    with pytest.raises(ValueError, match="eclib"):
        biologic_server._driver_class("BIOLOGIC")


def test_no_config_at_all_still_yields_the_default(monkeypatch):
    """makeApp is called outside the launcher by tests and capture scripts."""
    monkeypatch.setattr(config_loader, "CONFIG", None)
    assert biologic_server._driver_class("BIOLOGIC") is BiologicDriver


def test_a_server_key_absent_from_config_yields_the_default(with_config):
    with_config({"pstat_backend": "olecom"})
    assert biologic_server._driver_class("OTHER") is BiologicDriver


def test_every_backend_has_a_technique_registry():
    assert set(biologic_server.TECHNIQUE_REGISTRIES) == set(
        biologic_server.BACKENDS
    )


def test_each_registry_resolves_all_seven_techniques():
    for name, resolve in biologic_server.TECHNIQUE_REGISTRIES.items():
        for tech in ("OCV", "CA", "CP", "CV", "PEIS", "GEIS", "CAOCV"):
            assert resolve(tech) is not None, (name, tech)


def test_the_eclib_registry_returns_eclib_technique_objects():
    from helao.deploy.hte.drivers.pstat.biologic.technique import BiologicTechnique

    resolved = biologic_server.TECHNIQUE_REGISTRIES["eclib"]("CA")
    assert isinstance(resolved, BiologicTechnique)


def test_the_olecom_registry_returns_ole_technique_objects():
    from helao.deploy.hte.drivers.pstat.biologic_ole.technique import OleTechnique

    resolved = biologic_server.TECHNIQUE_REGISTRIES["olecom"]("CA")
    assert isinstance(resolved, OleTechnique)


def test_makeapp_builds_on_both_backends(with_config):
    """The route table must build without an instrument on either backend."""
    for backend in ("eclib", "olecom"):
        with_config({"pstat_backend": backend, "address": "127.0.0.1",
                     "num_channels": 1, "simulate": True})
        app = biologic_server.makeApp("BIOLOGIC")
        assert app is not None
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest helao/hexagon/tests/test_biologic_backend_select.py -v`

Expected: failures on `AttributeError: module ... has no attribute '_driver_class'`.

- [ ] **Step 3: Add the selection to `biologic_server.py`**

Add the imports near the existing driver import:

```python
from helao.helpers import config_loader

from ...drivers.pstat.biologic.driver import BiologicDriver
from ...drivers.pstat.biologic.technique import BIOTECHS
from ...drivers.pstat.biologic_ole.driver import BiologicOleDriver
from ...drivers.pstat.biologic_ole.technique import resolve as resolve_ole_technique
```

Then, above `makeApp`, add:

```python
#: `pstat_backend` value -> driver class. An absent key yields the
#: easy-biologic driver, so every existing station config keeps working
#: unedited; a station opts into EC-Lab by adding the key.
BACKENDS: dict[str, type] = {
    "eclib": BiologicDriver,
    "olecom": BiologicOleDriver,
}
DEFAULT_BACKEND = "eclib"

#: Technique-object resolver per backend. The two backends take different
#: technique objects -- a BiologicTechnique names an easy-biologic program
#: class, an OleTechnique names an .mps template -- so the endpoints pass a
#: technique *name* and the executor resolves it against the selected
#: backend's registry. A shared object would have to know both.
TECHNIQUE_REGISTRIES = {
    "eclib": lambda name: BIOTECHS[name],
    "olecom": resolve_ole_technique,
}


def _backend_name(server_key: str) -> str:
    """The backend this server's config selects.

    Reads the global CONFIG, which ``fast_launcher.py`` populates before it
    imports this module and calls ``makeApp``. Tolerates a missing CONFIG or
    server entry, because capture scripts and build tests call ``makeApp``
    outside the launcher.

    Raises:
        ValueError: On an unrecognized value. A typo must not fall through to
            the default -- a station meaning to drive EC-Lab would silently
            get the easy-biologic driver and fail at connect() with a vendor
            import error that names the wrong problem.
    """
    config = getattr(config_loader, "CONFIG", None) or {}
    params = (config.get("servers") or {}).get(server_key, {}).get("params", {}) or {}
    name = params.get("pstat_backend", DEFAULT_BACKEND)
    if name not in BACKENDS:
        raise ValueError(
            f"unknown pstat_backend {name!r} for server {server_key!r}; "
            f"expected one of {sorted(BACKENDS)}"
        )
    return name


def _driver_class(server_key: str) -> type:
    """The driver class this server's config selects."""
    return BACKENDS[_backend_name(server_key)]
```

Change `makeApp`'s `ActionHost` construction to use it, and record the backend on the app so `biologic_dyn_endpoints` and `BiologicExec` can read it:

```python
    backend = _backend_name(server_key)
    app = ActionHost(
        server_key=server_key,
        server_title=server_key,
        description="Biologic instrument/action server",
        version=3.0,
        driver_classes=[BACKENDS[backend]],
        dyn_endpoints=biologic_dyn_endpoints,
    )
    #: Which backend this app was built for. `base_api` names the driver
    #: namedtuple field from the class name, so `app.drivers.<Name>` differs
    #: between backends -- use `app.driver`, and read this for the name.
    app.pstat_backend = backend
    app.resolve_technique = TECHNIQUE_REGISTRIES[backend]
```

Change every endpoint's executor construction from a technique constant to a technique name — for example in `run_CA`:

```python
        executor = BiologicExec(
            active=active, oneoff=False, technique=app.resolve_technique("CA")
        )
```

Do the same in `run_CP` (`"CP"`), `run_CV` (`"CV"`), `run_OCV` (`"OCV"`), `run_PEIS` (`"PEIS"`), `run_GEIS` (`"GEIS"`) and `run_CAOCV` (`"CAOCV"`). The `TECH_*` imports at the top of the file can then be removed; keep `BiologicTechnique` if the `BiologicExec.technique` annotation still names it, or widen that annotation to `Any` with a comment saying the object is backend-specific.

- [ ] **Step 4: Run the tests and verify they pass**

```bash
pytest helao/hexagon/tests/test_biologic_backend_select.py -v
pytest helao/hexagon/tests/test_hte_route_checklist.py -v
pytest helao/deploy/hte/tests/test_echem_dispatch.py -v
```

Expected: all pass. The route checklist is the gate that says none of this changed a signature.

- [ ] **Step 5: Format and commit**

```bash
black helao/deploy/hte/servers/action/biologic_server.py \
      helao/hexagon/tests/test_biologic_backend_select.py
git add helao/deploy/hte/servers/action/biologic_server.py \
        helao/hexagon/tests/test_biologic_backend_select.py
git commit -m "feat(hte): select the BioLogic backend by config key

pstat_backend picks eclib (default) or olecom, mirroring andor_server's
wl_source. An unrecognized value raises rather than defaulting, so a typo
cannot hand an EC-Lab station the easy-biologic driver. The endpoints now
pass a technique *name* and the app resolves it against the selected
backend's registry, because the two backends take different technique
objects.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: the `run_protocol` endpoint

**Files:**
- Modify: `helao/deploy/hte/servers/action/biologic_server.py`
- Modify: `helao/deploy/hte/drivers/pstat/biologic_ole/driver.py` (add `setup_protocol`)
- Modify: `helao/deploy/hte/drivers/pstat/biologic_ole/technique.py` (add `protocol_technique`)
- Modify: `helao/hexagon/tests/checklists/hte/_additions.json`
- Test: `helao/hexagon/tests/test_biologic_backend_select.py` (extend)

**Interfaces:**
- Consumes: `_backend_name`, `BiologicOleDriver`.
- Produces: the `/BIOLOGIC/run_protocol` route (OLE backend only); `technique.protocol_technique(technique_code: int) -> OleTechnique`; `BiologicOleDriver.setup_protocol(mps_path, action_params, output_dir=None)`.

**Context the implementer needs.** Because `.mps` is already the transport, running a station-authored protocol as-is is `LoadSettings` with no patching. What it cannot know in advance is its column set — the `.mps` decides the techniques — so the driver reads status index 5 after loading and picks the column plan from the appendix 7.1 code, falling back to the bare `MeasureDcValue` triple rather than guessing. `mps_path` resolves against the `protocol_dir` server param so a station's protocol library is a declared location rather than whatever a caller passes.

- [ ] **Step 1: Write the failing tests**

Append to `helao/hexagon/tests/test_biologic_backend_select.py`:

```python
def test_run_protocol_registers_only_on_the_ole_backend(with_config, monkeypatch):
    """It is additive; the eclib backend has no .mps and must not grow it.

    Two things this test has to stand in for, neither of which `makeApp`
    does. `app.driver` is built in ActionHost's FastAPI **startup event**, so
    a freshly-made app has `driver is None`. And `biologic_dyn_endpoints`
    then does an unbounded `while not app.driver.ready: await sleep(1)` --
    pre-existing, present before this branch -- while the eclib driver's
    connect() imports easy_biologic unconditionally and so can never become
    ready on Linux. Left as-is rather than bounded here: that wait is on the
    startup path of six live stations and changing it is not this task's
    call.
    """
    import asyncio

    from helao.deploy.hte.drivers.pstat.biologic.driver import BiologicDriver

    def _connected(self):
        self.ready = True
        return DriverResponse(
            response=DriverResponseType.success, status=DriverStatus.ok
        )

    monkeypatch.setattr(BiologicDriver, "connect", _connected)

    def routes(backend):
        with_config({"pstat_backend": backend, "address": "127.0.0.1",
                     "num_channels": 1, "simulate": True})
        app = biologic_server.makeApp("BIOLOGIC")
        # Exactly what the startup event does.
        app.driver = biologic_server.BACKENDS[backend](config=app.server_params)
        asyncio.run(biologic_server.biologic_dyn_endpoints(app))
        return {route.path for route in app.routes}

    assert "/BIOLOGIC/run_protocol" in routes("olecom")
    assert "/BIOLOGIC/run_protocol" not in routes("eclib")


def test_run_protocol_is_recorded_in_the_additions_allowlist():
    """A new route is a deliberate addition, never a checklist edit."""
    import json
    from pathlib import Path

    additions = json.loads(
        Path("helao/hexagon/tests/checklists/hte/_additions.json").read_text()
    )
    entry = [a for a in additions if a["path"] == "/BIOLOGIC/run_protocol"]
    assert len(entry) == 1
    assert entry[0]["module"] == "biologic_server.py"
    assert entry[0]["why"]


def test_protocol_technique_picks_a_plan_from_the_technique_code():
    from helao.deploy.hte.drivers.pstat.biologic_ole import technique as ot

    assert ot.protocol_technique(54).column_plan.kind == "dc"
    assert ot.protocol_technique(60).column_plan.kind == "eis"


def test_an_unrecognized_technique_code_falls_back_to_the_dc_triple():
    """Guessing a column set for an unknown technique would fabricate data."""
    from helao.deploy.hte.drivers.pstat.biologic_ole import technique as ot

    plan = ot.protocol_technique(999).column_plan
    assert plan.kind == "dc"
    assert set(ot.columns(plan)) == {"t_s", "Ewe_V", "I_A"}


def test_setup_protocol_loads_the_named_file_without_patching(tmp_path):
    from helao.deploy.hte.drivers.pstat.biologic_ole.driver import BiologicOleDriver

    protocol = tmp_path / "my_protocol.mps"
    original = "Technique : 1\nChronoamperometry\n" + "Ei (V)".ljust(20) + "0.000\n"
    protocol.write_text(original, encoding="latin-1")
    driver = BiologicOleDriver(
        config={"address": "1.2.3.4", "num_channels": 1, "simulate": True,
                "protocol_dir": str(tmp_path), "scratch_dir": str(tmp_path / "s")}
    )
    driver.connect()
    response = driver.setup_protocol("my_protocol.mps", {"channel": 0})
    assert response.response == "success"
    assert protocol.read_text(encoding="latin-1") == original


def test_setup_protocol_refuses_a_path_outside_the_protocol_dir(tmp_path):
    """A declared library, not whatever the caller passes."""
    from helao.deploy.hte.drivers.pstat.biologic_ole.driver import BiologicOleDriver

    driver = BiologicOleDriver(
        config={"address": "1.2.3.4", "num_channels": 1, "simulate": True,
                "protocol_dir": str(tmp_path), "scratch_dir": str(tmp_path / "s")}
    )
    driver.connect()
    response = driver.setup_protocol("../escape.mps", {"channel": 0})
    assert response.response == "failed"
    assert "protocol_dir" in response.message


def test_setup_protocol_refuses_a_missing_file(tmp_path):
    from helao.deploy.hte.drivers.pstat.biologic_ole.driver import BiologicOleDriver

    driver = BiologicOleDriver(
        config={"address": "1.2.3.4", "num_channels": 1, "simulate": True,
                "protocol_dir": str(tmp_path), "scratch_dir": str(tmp_path / "s")}
    )
    driver.connect()
    response = driver.setup_protocol("absent.mps", {"channel": 0})
    assert response.response == "failed"
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest helao/hexagon/tests/test_biologic_backend_select.py -v`

Expected: the Task 10 tests still pass; the seven new ones fail on missing names.

- [ ] **Step 3: Add `protocol_technique` to `technique.py`**

```python
#: Appendix 7.1 codes that identify an EIS technique. A protocol whose first
#: technique is one of these is read with MeasureEisValue.
EIS_TECHNIQUE_CODES = frozenset({29, 30, 45, 46, 60, 61, 62, 63, 64, 65, 87})


def protocol_technique(technique_code: int) -> OleTechnique:
    """A technique record for a station-authored protocol.

    ``run_protocol`` cannot know its columns in advance -- the ``.mps``
    decides the techniques -- so the driver reads status index 5 after
    ``LoadSettings`` and calls this with the code it found.

    An unrecognized code yields the bare ``MeasureDcValue`` triple rather
    than a guess. Emitting columns a technique does not record would fill
    them with NaN under names a consumer would treat as real.
    """
    if technique_code in EIS_TECHNIQUE_CODES:
        plan = _eis_plan()
    elif any(technique_code in tech.technique_codes for tech in OLE_TECHS.values()):
        plan = _dc_plan()
    else:
        plan = ColumnPlan(kind="dc", derived=("t_s", "Ewe_V", "I_A"))
    return OleTechnique(
        technique_name="PROTOCOL",
        template="",
        parameter_map={},
        column_plan=plan,
        technique_codes=frozenset({technique_code}),
    )
```

Add `"EIS_TECHNIQUE_CODES"` and `"protocol_technique"` to `__all__`.

- [ ] **Step 4: Add `setup_protocol` to `driver.py`**

```python
    def setup_protocol(
        self,
        mps_path: str,
        action_params: dict,
        output_dir: Optional[str] = None,
    ) -> DriverResponse:
        """Load a station-authored ``.mps`` onto a channel, unpatched.

        The file is resolved against ``protocol_dir`` and must stay inside it:
        a station's protocol library is a declared location, not whatever an
        experiment passes. The technique record -- and therefore the column
        set -- is derived from status index 5 *after* loading, because the
        file decides the techniques and nothing here can know them first.
        """
        channel = action_params.get("channel", -1)
        try:
            if channel not in self.channels:
                raise ValueError(f"Channel {channel} does not exist.")
            if self.channels[channel] is not None:
                raise ValueError(f"Channel {channel} is in use.")
            root = self.protocol_dir.resolve()
            resolved = (root / mps_path).resolve()
            if not resolved.is_relative_to(root):
                raise ValueError(
                    f"{mps_path!r} resolves outside protocol_dir {root}"
                )
            if not resolved.is_file():
                raise FileNotFoundError(f"no protocol file at {resolved}")
            run_dir = self.scratch_dir / f"ch{channel}" / uuid.uuid4().hex
            run_dir.mkdir(parents=True, exist_ok=True)
            self._bounded(
                self.client.load_settings,
                self.device_number,
                channel,
                str(resolved),
            )
            loaded = self._status_of(channel)
            technique = protocol_technique(loaded.technique_code)
            LOGGER.info(
                "loaded protocol %s on channel %s; technique code %s -> %s plan",
                resolved.name,
                channel,
                loaded.technique_code,
                technique.column_plan.kind,
            )
            self.channels[channel] = technique
            self.channel_params[channel] = dict(action_params)
            self.scratch[channel] = run_dir
            self.output_dirs[channel] = Path(output_dir) if output_dir else None
            # Ship the protocol itself as provenance -- an unpatched copy is
            # still the exact settings this action ran.
            shutil.copy2(resolved, run_dir / resolved.name)
            return DriverResponse(
                response=DriverResponseType.success,
                message="protocol loaded",
                status=DriverStatus.ok,
            )
        except Exception as exc:
            LOGGER.error("setup_protocol failed", exc_info=True)
            self.cleanup(channel)
            return DriverResponse(
                response=DriverResponseType.failed,
                message=str(exc),
                status=DriverStatus.error,
            )
```

Add `protocol_technique` to the `from .technique import ...` line.

- [ ] **Step 5: Add the endpoint and a protocol executor**

In `biologic_server.py`, add a small `BiologicExec` subclass above `biologic_dyn_endpoints`:

```python
class BiologicProtocolExec(BiologicExec):
    """Runs a station-authored .mps instead of a parameterised technique.

    Differs from its parent in exactly one place -- ``_pre_exec`` calls
    ``setup_protocol`` rather than ``setup`` -- so start, poll, alerting and
    teardown stay one implementation.
    """

    async def _pre_exec(self) -> dict:
        try:
            resp = self.driver.setup_protocol(
                mps_path=self.action_params["mps_path"],
                action_params=self.action_params,
                output_dir=self._action_output_path(),
            )
            error = ErrorCodes.none if resp.response == "success" else ErrorCodes.setup
            if error is not ErrorCodes.none:
                LOGGER.error("protocol setup failed: %s", resp.message)
        except Exception:
            error = ErrorCodes.critical_error
            LOGGER.error("BiologicProtocolExec pre-exec error", exc_info=True)
        return {"error": error}
```

At the end of `biologic_dyn_endpoints`, register the route only for the OLE backend:

```python
    if getattr(app, "pstat_backend", DEFAULT_BACKEND) != "olecom":
        return

    @app.action()
    @action_version(1)
    async def run_protocol(
        ctx: ActionContext,
        fast_samples_in: list[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = Body([], embed=True),
        mps_path: str = "",
        channel: int = 0,
        TTLwait: int = -1,
        TTLsend: int = -1,
        TTLduration: float = 1.0,
    ):
        """Run an EC-Lab protocol authored in the GUI, exactly as saved.

        ``mps_path`` is resolved against the server's ``protocol_dir`` param
        and must stay inside it. Nothing is patched, so every setting is the
        one the file carries; the emitted columns are chosen from the loaded
        technique's code, and an unrecognized technique emits time, potential
        and current only.

        OLE COM backend only.
        """
        active = await ctx.begin()
        active.action.action_abbr = "PROT"
        executor = BiologicProtocolExec(active=active, oneoff=False, technique=None)
        return active.start_executor(executor)
```

`BiologicExec.__init__` reads `kwargs["technique"]`, so passing `technique=None` is valid and unused on this path — the technique record is created by `setup_protocol` from the loaded file.

- [ ] **Step 6: Record the addition**

Add to `helao/hexagon/tests/checklists/hte/_additions.json`, keeping the existing entry:

```json
  {
    "module": "biologic_server.py",
    "path": "/BIOLOGIC/run_protocol",
    "method": "post",
    "date": "2026-09-07",
    "why": "run an EC-Lab GUI-authored .mps protocol as-is; OLE COM backend only; see docs/superpowers/specs/2026-09-07-biologic-olecom-driver-design.md"
  }
```

- [ ] **Step 7: Run the tests and verify they pass**

```bash
pytest helao/hexagon/tests/test_biologic_backend_select.py -v
pytest helao/hexagon/tests/test_hte_route_checklist.py -v
```

Expected: all pass. If the route checklist reports `/BIOLOGIC/run_protocol` as `extra`, the `_additions.json` entry's `module`, `path` or `method` does not match what the extractor produced — fix the entry, never the module checklist.

- [ ] **Step 8: Format and commit**

```bash
black helao/deploy/hte/servers/action/biologic_server.py \
      helao/deploy/hte/drivers/pstat/biologic_ole/driver.py \
      helao/deploy/hte/drivers/pstat/biologic_ole/technique.py \
      helao/hexagon/tests/test_biologic_backend_select.py
git add helao/deploy/hte/servers/action/biologic_server.py \
        helao/deploy/hte/drivers/pstat/biologic_ole/ \
        helao/hexagon/tests/test_biologic_backend_select.py \
        helao/hexagon/tests/checklists/hte/_additions.json
git commit -m "feat(hte): run_protocol, for EC-Lab GUI-authored .mps files

Because .mps is already the transport, running a station protocol as-is
is LoadSettings with no patching. The column set cannot be known in
advance -- the file decides the techniques -- so it comes from status
index 5 after loading, falling back to the MeasureDcValue triple rather
than guessing. mps_path resolves inside a declared protocol_dir.

Registers on the OLE backend only, and is recorded in the frozen
checklist's additions allowlist.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: vendor isolation

**Files:**
- Create: `helao/hexagon/tests/test_biologic_ole_vendor_isolation.py`

**Interfaces:**
- Consumes: the finished `biologic_ole` package.
- Produces: nothing importable — a guard.

**Context the implementer needs.** Mirror `helao/hexagon/tests/test_andor_vendor_isolation.py`, which parses imports with `ast` rather than grepping source. The distinction matters here for the same reason it did there: several modules in this package have docstrings *explaining* the comtypes rule, and a grep for the package name would flag the documentation. This guard is what keeps the package importable on Linux, which is where every one of its tests runs.

- [ ] **Step 1: Write the failing test**

Create `helao/hexagon/tests/test_biologic_ole_vendor_isolation.py`:

```python
"""`olecom_client.py` is the only module that imports comtypes, and only lazily.

Everything else in the OLE package must import and construct on Linux, where
comtypes does not exist -- which is where every test in the package runs. An
import added to driver.py or sim.py would not fail loudly; it would make the
whole package uncollectable, and the failure would read as "the tests are
broken" rather than "the isolation broke".

Checked by parsing imports, not by grepping source: several modules carry
docstrings explaining this rule, and a text search would flag the
documentation that exists to prevent the problem.
"""

import ast
from pathlib import Path

OLE = Path("helao/deploy/hte/drivers/pstat/biologic_ole")
ALLOWED = {"olecom_client.py"}
VENDOR_PREFIXES = ("comtypes", "win32com", "pythoncom", "pywintypes")


def _imports(path: Path) -> set[str]:
    """Every module name this file imports, however it spells the import."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            prefix = "." * node.level + (node.module or "")
            names.add(prefix)
            names.update(f"{prefix}.{a.name}".lstrip(".") for a in node.names)
    return names


def _module_scope_imports(path: Path) -> set[str]:
    """Only the imports at module scope -- the ones that run on import."""
    names: set[str] = set()
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add("." * node.level + (node.module or ""))
    return names


def test_only_the_client_imports_a_com_package():
    offenders = []
    for path in sorted(OLE.glob("*.py")):
        if path.name in ALLOWED:
            continue
        if any(
            name.startswith(VENDOR_PREFIXES) for name in _imports(path)
        ):
            offenders.append(path.name)
    assert offenders == [], f"{offenders} must not import a COM package"


def test_the_client_imports_comtypes_but_not_at_module_scope():
    """A guard that passes because the target moved is not a guard.

    And a module-scope import in the client itself would defeat the whole
    thing: the package imports the client.
    """
    path = OLE / "olecom_client.py"
    assert any(name.startswith("comtypes") for name in _imports(path))
    assert not any(
        name.startswith(VENDOR_PREFIXES) for name in _module_scope_imports(path)
    )


def test_nothing_in_the_package_imports_easy_biologic():
    """The two backends must not acquire a dependency on each other."""
    offenders = [
        path.name
        for path in sorted(OLE.glob("*.py"))
        if any(name.startswith("easy_biologic") for name in _imports(path))
    ]
    assert offenders == [], offenders


def test_the_pure_modules_import_no_sibling_that_touches_com():
    """mps_template, technique, status and mps_assemble stay COM-free."""
    for name in ("mps_template.py", "technique.py", "status.py", "mps_assemble.py"):
        imports = _imports(OLE / name)
        assert not any("olecom_client" in imported for imported in imports), name
        assert not any("sim" == imported for imported in imports), name


def test_the_package_was_actually_scanned():
    """A sweep of an empty directory passes vacuously."""
    assert len(list(OLE.glob("*.py"))) >= 8, sorted(p.name for p in OLE.glob("*.py"))
```

- [ ] **Step 2: Run the test and verify it passes**

Run: `pytest helao/hexagon/tests/test_biologic_ole_vendor_isolation.py -v`

Expected: 5 passed. This is a guard over already-written code, so it should pass immediately. **Verify it goes red**: temporarily add `import comtypes` to the top of `driver.py`, re-run, confirm `test_only_the_client_imports_a_com_package` fails naming `driver.py`, then remove it. A guard never seen red is not known to work.

- [ ] **Step 3: Format and commit**

```bash
black helao/hexagon/tests/test_biologic_ole_vendor_isolation.py
git add helao/hexagon/tests/test_biologic_ole_vendor_isolation.py
git commit -m "test(hte): pin comtypes to olecom_client, and to a lazy import

Parses imports rather than grepping, because several modules carry
docstrings explaining this rule and a text search would flag the
documentation. Verified red by adding an import to driver.py.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 13: the emitted-column contract

**Files:**
- Create: `helao/hexagon/tests/test_biologic_column_contract.py`

**Interfaces:**
- Consumes: both technique registries, the OLE driver, the fake COM server.
- Produces: nothing importable — a guard.

**Context the implementer needs.** This is the gate the spec calls the emitted-column contract test, and it is what actually protects the two `biologic_vis` panels and the five experiment libraries. It has two halves: a *static* half comparing the two registries' declared column sets, and a *live* half running the OLE driver against its simulator and checking that what comes out matches what was declared. The static half alone would pass if the driver ignored its own plan; the live half alone would pass if both registries were wrong together.

There is no eclib simulator, and building one is out of scope — the eclib side is pinned by its declaration, which is the same thing the eclib driver's `field_remap` uses at runtime.

- [ ] **Step 1: Write the failing test**

Create `helao/hexagon/tests/test_biologic_column_contract.py`:

```python
"""Both BioLogic backends emit the same columns, and the OLE one delivers them.

This is the gate that makes the OLE backend a drop-in rather than merely a
similar thing. Both `biologic_vis` panels and five experiment libraries --
ANEC, ECHEUVIS, PSTAT, ECMS, HISPEC -- key off these names. A missing column
renders an empty trace with no error anywhere; a renamed one renders nothing
and logs nothing.

Two halves, and both are needed. The static half compares the registries'
declarations; on its own it would pass if the driver ignored its own plan. The
live half runs the OLE driver against its simulator; on its own it would pass
if both registries were wrong in the same way.
"""

import asyncio

import pytest

from helao.deploy.hte.drivers.pstat.biologic.technique import BIOTECHS
from helao.deploy.hte.drivers.pstat.biologic_ole import technique as ot
from helao.deploy.hte.drivers.pstat.biologic_ole.driver import BiologicOleDriver
from helao.deploy.hte.drivers.pstat.biologic_ole.sim import SimConfig, set_sim_config

TECHNIQUES = ["OCV", "CA", "CP", "CV", "PEIS", "GEIS", "CAOCV"]

#: Columns the eclib driver adds after field_remap, in code rather than in
#: the registry. `channel` is stamped by BiologicExec._poll on both backends;
#: X_ohm and R_ohm are derived in the eclib driver's get_data from modulus and
#: phase, and in the OLE cursor straight off MeasureEisValue.
ECLIB_DERIVED_IN_CODE = {"X_ohm", "R_ohm"}


def declared_eclib(name: str) -> set[str]:
    columns = set(BIOTECHS[name].field_map.values())
    if "modulus" in columns:
        columns |= ECLIB_DERIVED_IN_CODE
    return columns


def declared_ole(name: str) -> set[str]:
    return set(ot.columns(ot.resolve(name).column_plan))


@pytest.mark.parametrize("name", TECHNIQUES)
def test_the_two_registries_declare_the_same_columns(name):
    assert declared_ole(name) == declared_eclib(name), {
        "only_eclib": sorted(declared_eclib(name) - declared_ole(name)),
        "only_ole": sorted(declared_ole(name) - declared_eclib(name)),
    }


def test_the_dc_column_set_is_the_frozen_one():
    """Spelled out, so a change to both registries at once still fails."""
    assert declared_ole("CA") == {"t_s", "Ewe_V", "I_A", "P_W", "cycle"}


def test_the_eis_column_set_is_the_frozen_one():
    assert declared_ole("PEIS") == {
        "process", "t_s", "Ewe_V", "I_A", "AbsEwe_V", "AbsI_A", "phase",
        "modulus", "Ece_V", "AbsEce_V", "AbsIce_A", "phase_ce", "modulus_ce",
        "f_Hz", "X_ohm", "R_ohm",
    }


def test_ocv_emits_only_time_and_potential():
    assert declared_ole("OCV") == {"t_s", "Ewe_V"}


# NOTE (superseded): this synthetic fixture predates the real templates.
# All nine are now committed under
# helao/deploy/hte/drivers/pstat/biologic_ole/templates/, so pass
# templates_dir pointing there instead. It makes no difference to what this
# test exercises -- run_once passes only {"channel": 0} and _patch skips
# every parameter absent from action_params, so no caption is ever
# substituted -- but driving the real per-technique files costs nothing and
# exercises what a station will actually run.
@pytest.fixture
def ca_templates(tmp_path_factory):
    directory = tmp_path_factory.mktemp("contract_templates")

    def r(label, *values):
        return label.ljust(20) + "".join(v.ljust(20) for v in values) + "\n"

    # Every caption any technique's parameter_map names, in one template.
    # One file per technique keeps the fixture trivial; a real station has
    # seven genuinely different ones.
    body = (
        "EC-LAB SETTING FILE\n\nNumber of linked techniques : 1\n\n"
        "Technique : 1\nT\n"
        + r("Ei (V)", "0.000")
        + r("E1 (V)", "1.000")
        + r("E2 (V)", "-1.000")
        + r("Ef (V)", "0.000")
        + r("dE/dt", "1.000")
        + r("dE/dt unit", "V/s")
        + r("dE (mV)", "1.00")
        + r("ti (h:m:s)", "0:00:10.0000")
        + r("ts (h:m:s)", "0:00:10.0000")
        + r("tR (h:m:s)", "0:00:10.0000")
        + r("tE (h:m:s)", "0:00:0.0000")
        + r("tIs (h:m:s)", "0:00:0.0000")
        + r("dta (s)", "0.0100")
        + r("dts (s)", "0.0100")
        + r("dtR (s)", "0.1000")
        + r("dt (s)", "0.1000")
        + r("dEs (mV)", "10.00")
        + r("dER (mV)", "10.00")
        + r("dI", "10.000")
        + r("unit dI", "mA")
        + r("Is", "1.000")
        + r("unit Is", "mA")
        + r("Ia", "1.000")
        + r("unit  Ia", "mA")
        + r("E (V)", "0.000")
        + r("Va (mV)", "10.00")
        + r("fi", "1000.000")
        + r("unit fi", "Hz")
        + r("ff", "100.000")
        + r("unit ff", "kHz")
        + r("Nd", "60")
        + r("spacing", "Logarithmic")
        + r("Na", "10")
        + r("pw", "0.10")
        + r("nc cycles", "0")
        + r("I Range", "Auto")
        + r("E range min (V)", "-10.000")
        + r("E range max (V)", "10.000")
        + r("Bandwidth", "4")
    )
    for name in ("OCV", "CA", "CP", "CV", "PEIS", "GEIS", "CAOCV"):
        (directory / f"{name}.mps").write_text(body)
    return directory


def run_once(name: str, templates, tmp_path) -> dict:
    """Drive one technique through the OLE driver against the simulator."""
    kind = "eis" if name in ("PEIS", "GEIS") else "dc"
    set_sim_config(SimConfig(run_seconds=0.0, kind=kind, n_eis_points=4))
    try:
        driver = BiologicOleDriver(
            config={
                "address": "1.2.3.4",
                "num_channels": 1,
                "simulate": True,
                "templates_dir": str(templates),
                "scratch_dir": str(tmp_path / name),
            }
        )
        assert driver.connect().response == "success"
        assert driver.setup(ot.resolve(name), {"channel": 0}).response == "success"
        assert driver.start_channel(0).response == "success"
        collected: dict[str, list] = {}
        for _ in range(10):
            response = asyncio.run(driver.get_data(0))
            for column, values in response.data.items():
                collected.setdefault(column, []).extend(values)
            if response.message == "done":
                break
        driver.cleanup(0)
        driver.disconnect()
        return collected
    finally:
        set_sim_config(SimConfig())


@pytest.mark.parametrize("name", TECHNIQUES)
def test_the_driver_delivers_every_column_it_declares(
    name, ca_templates, tmp_path
):
    collected = run_once(name, ca_templates, tmp_path)
    assert set(collected) >= declared_ole(name), sorted(
        declared_ole(name) - set(collected)
    )


@pytest.mark.parametrize("name", TECHNIQUES)
def test_every_delivered_column_has_the_same_number_of_rows(
    name, ca_templates, tmp_path
):
    """A short column misaligns every row after it, in every consumer."""
    collected = run_once(name, ca_templates, tmp_path)
    lengths = {column: len(values) for column, values in collected.items()}
    assert len(set(lengths.values())) == 1, lengths


@pytest.mark.parametrize("name", TECHNIQUES)
def test_the_driver_delivers_no_column_it_did_not_declare(
    name, ca_templates, tmp_path
):
    """An undeclared column is a contract the other backend does not honour."""
    collected = run_once(name, ca_templates, tmp_path)
    assert set(collected) <= declared_ole(name), sorted(
        set(collected) - declared_ole(name)
    )


@pytest.mark.parametrize("name", TECHNIQUES)
def test_at_least_one_row_is_delivered(name, ca_templates, tmp_path):
    """A run that emits nothing would satisfy every set comparison above."""
    collected = run_once(name, ca_templates, tmp_path)
    assert collected["t_s"], name
```

- [ ] **Step 2: Run the test**

Run: `pytest helao/hexagon/tests/test_biologic_column_contract.py -v`

Expected: all pass. Two likely failures and what they mean:

- `test_the_two_registries_declare_the_same_columns` failing on `PEIS`/`GEIS` with `only_ole: ['X_ohm', 'R_ohm']` means `ECLIB_DERIVED_IN_CODE` is not being applied — those two are computed in the eclib driver's `get_data`, not declared in its `field_map`.
- `test_the_driver_delivers_no_column_it_did_not_declare` failing with an extra `_State`-prefixed key means the OLE driver is emitting the eclib path's `_`-prefixed status values. It should not: those come from `getdict(segment.values)` in the eclib driver and have no OLE equivalent. If a `biologic_vis` panel turns out to require them, that is a spec amendment, not a quiet addition here.

- [ ] **Step 3: Format and commit**

```bash
black helao/hexagon/tests/test_biologic_column_contract.py
git add helao/hexagon/tests/test_biologic_column_contract.py
git commit -m "test(hte): pin both backends to one emitted-column contract

Static half compares the two registries' declarations; live half runs the
OLE driver against its simulator. Either alone passes for the wrong
reason -- the static one if the driver ignores its plan, the live one if
both registries are wrong together. This is what protects the two
biologic_vis panels and the five experiment libraries.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 14: a launchable simulated config, and the documentation

**Files:**
- Create: `helao/deploy/hte/configs/biologicole.yml`
- Create: `helao/deploy/hte/drivers/pstat/biologic_ole/templates/README.md`
- Modify: `CLAUDE.md`
- Test: `helao/hexagon/tests/test_biologic_backend_select.py` (extend)

**Interfaces:**
- Consumes: everything.
- Produces: the `biologicole` config prefix, launchable on Linux.

**Context the implementer needs.** `launch.py` resolves a prefix by globbing `helao/deploy/*/configs/<prefix>.*`, validates the `servers:` block for unique keys and unique `host:port`, and runs `run_unit_tests.py` first. Model the config on `helao/hexagon/tests/smoke/configs/biologic.yml` — an action server plus an `action_visualizer` — but with `simulate: true` and a loopback address, so the whole group comes up with no hardware. The templates directory needs a README because it will be *empty* until the station gate is discharged, and an empty directory in git needs a file anyway.

- [ ] **Step 1: Write the failing test**

Append to `helao/hexagon/tests/test_biologic_backend_select.py`:

```python
def test_the_simulated_config_loads_and_selects_the_ole_backend():
    from helao.helpers.config_loader import read_config

    config = read_config("biologicole")
    params = config["servers"]["BIOLOGIC"]["params"]
    assert params["pstat_backend"] == "olecom"
    assert params["simulate"] is True


def test_the_simulated_config_has_no_duplicate_host_ports():
    from helao.helpers.config_loader import read_config

    config = read_config("biologicole")
    endpoints = [
        (server["host"], server["port"]) for server in config["servers"].values()
    ]
    assert len(endpoints) == len(set(endpoints)), endpoints


def test_the_simulated_config_names_a_visualizer_the_panels_answer_to():
    from helao.helpers.config_loader import read_config

    config = read_config("biologicole")
    assert config["servers"]["BIOLOGIC"]["action_vis"] == "biologic_vis"


def test_the_templates_directory_exists_and_explains_itself():
    from pathlib import Path

    readme = Path(
        "helao/deploy/hte/drivers/pstat/biologic_ole/templates/README.md"
    )
    assert readme.is_file()
    assert "EC-Lab" in readme.read_text()
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest helao/hexagon/tests/test_biologic_backend_select.py -v`

Expected: the four new tests fail — `read_config` raises on the missing prefix, and the README does not exist.

- [ ] **Step 3: Write the config**

Create `helao/deploy/hte/configs/biologicole.yml`:

```yaml
# Hardware-free dev config for the EC-Lab OLE COM BioLogic backend.
#
# `python launch.py biologicole` brings up a BIOLOGIC action server on the
# simulated backend (`simulate: true` selects sim.py's fake COM server, so no
# EC-Lab, no comtypes and no instrument are needed) plus the action
# visualizer, which answers to the same `biologic_vis` key both UI stacks use.
#
# This is a development config, not a station config. A real EC-Lab station
# adds `pstat_backend: olecom` to its existing BIOLOGIC params, keeps its real
# `address`, and does NOT set `simulate`.
dummy: true
simulation: true
run_type: biologic_ole
root: INST_hlo_biologicole
servers:
  BIOLOGIC:
    host: 127.0.0.1
    port: 8016
    group: action
    deployment: hte
    fast: biologic_server
    action_vis: biologic_vis
    params:
      allow_no_sample: true
      pstat_backend: olecom
      simulate: true
      address: 127.0.0.1
      num_channels: 2
      grounded: true
      # Empty until the templates are authored at a station; the simulated
      # backend never opens them, so the group still comes up.
      # templates_dir: helao/deploy/hte/drivers/pstat/biologic_ole/templates
  ACTVIS:
    host: 127.0.0.1
    port: 5001
    group: visualizer
    deployment: hte
    bokeh: action_visualizer
    params:
      doc_name: 'BIOLOGIC OLE Visualizer'
      launch_browser: false
```

- [ ] **Step 4: Write the templates README**

Create `helao/deploy/hte/drivers/pstat/biologic_ole/templates/README.md`:

```markdown
# `.mps` templates

Nine files belong here. They are EC-Lab settings files, authored in the EC-Lab
GUI against the instrument that will run them, then saved and committed —
**this repository cannot generate them.**

**All nine are present**, and all are real GUI-authored EC-Lab v11.72 files
from an SP-200:

| File | Technique | Note |
|---|---|---|
| `OCV.mps` | Open Circuit Voltage | |
| `CA.mps` | Chronoamperometry / Chronocoulometry | |
| `CP.mps` | Chronopotentiometry | |
| `CV.mps` | Cyclic Voltammetry | |
| `PEIS.mps` | Potentio Electrochemical Impedance Spectroscopy | |
| `GEIS.mps` | Galvano Electrochemical Impedance Spectroscopy | |
| `CAOCV.mps` | Chronoamperometry then Open Circuit Voltage | **two** blocks, saved as `CA_OCV.mps` |
| `TI.mps` | Trigger In | block extracted from a real `TI_CV_TO.mps` |
| `TO.mps` | Trigger Out | same |

`test_ole_technique.py` checks every caption in the registry against these
files on Linux, so a template replaced by one from a different EC-Lab build
that renamed a row fails in CI rather than at a station. If you re-export any
of them, give every parameter a **distinct** value — a file whose steps are
all `0.000` cannot disambiguate its own captions, which is exactly what makes
`CV.mps` usable as a reference (`Ei`, `E1`, `E2`, `Ef` hold four different
numbers).

Authoring them in the GUI is not a convenience — it is the only way to be sure
the settings are ones the hardware accepts. `LoadSettings` returns 0 for
settings incompatible with the bandwidth or current range, and that refusal is
the only pre-run validation the OLE COM API offers.

When they land, check each one's parameter captions against
`technique.py`'s `parameter_map`. CV's are read off the real file here; the
other six were verified against a working third-party `.mps` writer, which is
good evidence but not the same thing. A caption no row matches raises
`MpsParameterNotFound` at setup, deliberately, rather than silently running
the template's own default value on a real cell.

**One known-open question, on CV.** EC-Lab's Cyclic Voltammetry has no
`dE (mV)` row — the recording interval is governed by `Step percent` and `N`,
and how those relate to HELAO's `AcqInterval__V` is not documented anywhere
available. `AcqInterval__V` is therefore unmapped on this backend and the
template's own values stand. Settle it with the station owner before the first
production CV.

Four things to preserve when you save these, each of which a well-meaning
editor destroys silently:

- **latin-1, not UTF-8.** The real files carry 0xB2 and 0xB3 (`cm²`, `cm³`),
  and `µ` is the single byte 0xB5.
- **CRLF line terminators.**
- **Fixed-width columns**: label 0-19, each sequence value in the 20 after it,
  *including trailing padding*. Do not reflow or strip.
- **Captions are neither unique nor tidy.** `vs.` appears four times in one CV
  block; `Trigger` appears in both trigger blocks; GEIS has a caption with two
  consecutive spaces (`unit  Ia`). Do not deduplicate or "fix" any of them.
```

- [ ] **Step 5: Run the tests, then launch the group**

```bash
pytest helao/hexagon/tests/test_biologic_backend_select.py -v
python run_unit_tests.py
timeout 90 python launch.py biologicole
```

Expected: the tests pass; `run_unit_tests.py` passes (`launch.py` runs it first and aborts on failure); and the launch brings up BIOLOGIC and ACTVIS with no traceback. Watch specifically for the `BiologicOleDriver is SIMULATED` warning and for `supervise_early_exits` reporting nothing — a server that dies on its own used to leave a launch reading clean. `CTRL-x` to tear down, or let the `timeout` do it.

- [ ] **Step 6: Document it in `CLAUDE.md`**

Add this section to `CLAUDE.md`, immediately after the "Ocean Insight spectrometers (OceanDirect)" section:

```markdown
### BioLogic potentiostats: two backends

`helao/deploy/hte/servers/action/biologic_server.py` serves the same seven
technique endpoints from either of two drivers, chosen by the server's
`pstat_backend` param — `eclib` (default, `drivers/pstat/biologic/`, via
easy-biologic over TCP) or `olecom` (`drivers/pstat/biologic_ole/`, by
piloting the EC-Lab application over OLE COM). An absent key yields `eclib`,
so all six live configs keep working unedited; an *unrecognized* value raises,
because a typo must not hand an EC-Lab station the easy-biologic driver.
Both satisfy the `BiologicBackend` Protocol in `drivers/pstat/biologic_backend.py`.

The OLE path is not a variation on the EClib one. What is worth knowing before
editing it:

- **There is no programmatic technique construction.** `LoadSettings` takes an
  `.mps` file and nothing in the 32-function API builds a technique from
  arguments, so `.mps` templating is the transport for *every* endpoint, not
  an opt-in feature. `ModifyOnTheFly` exists but mutates a **running**
  experiment, by GUI caption, needing a second call for the unit.
- **The nine `.mps` templates cannot be produced from this repo.** They are
  authored in the EC-Lab GUI at a station. `templates/README.md` says which.
  A caption `technique.py` names but no template row matches raises
  `MpsParameterNotFound` at setup — deliberately, because the alternative is
  running the template's own default on a real cell with nothing to show it.
- **Data is polled out of the growing MPR file, one value per call.** `P_W` is
  derived as `|Ewe*I|`, which is EC-Lab's own definition of variable 70, and
  `cycle` comes from status index 10 — fetching either would cost a call per
  point to learn the same number. The manual's wording leaves open whether
  `MeasureDcValue` returns one point or all remaining ones; `MprCursor`
  advances by the length it receives, so a bulk return just makes it faster.
- **`Stop_rec1`/`Stop_rec2` (status index 0 == 4 or 5) mean "the last points
  are being recorded", not "stopped".** The driver finishes only at `Stop`,
  and then drains once more. Finishing at `Stop_rec` truncates the tail of
  every record, silently.
- **`ConnectDevice`/`ConnectDeviceByIP` auto-answer "Yes" to EC-Lab's
  firmware-upgrade prompt** and the API cannot suppress it, so a connect can
  flash a production instrument. The driver warns before calling; nothing more
  is possible from here.
- **A modal Windows message box blocks the COM call that raised it, forever.**
  `EnableMessagesWindows(0)` runs first at connect, and every call still goes
  through a thread executor under a timeout — which frees the caller and
  leaves the worker thread blocked, the same trade `OceanDirectExtrigExec`
  makes.
- **EC-Lab is a GUI a human can touch mid-run.** `SelectDevice`/`SelectChannel`
  mutate a global selection, so every call passes an explicit device and
  channel. The manual's own §6.1 example is internally inconsistent here (the
  prose says device 6, the code says `OLE_ConnectDevice(1)`).
- **TTL is not an API call.** Trigger In and Trigger Out are *techniques*
  (appendix 7.1 codes 38/39, 88/89), so a non-default `TTLwait`/`TTLsend`
  assembles a multi-technique `.mps` and renumbers both the `Technique : N`
  lines and the `Number of linked techniques` header, which EC-Lab reads
  positionally and does not repair.
- **Technique codes are duplicated across two families** — CA is 24 and 54,
  OCV 11 and 55, CV 6 and 57, PEIS 29 and 60, GEIS 30 and 61, CP 25 and 56.
  Which one a template yields depends on the template; status index 5 reports
  it back and the driver warns on a mismatch rather than refusing.
- **The `.mps` and `.mpr` ship with the action, moved at cleanup.** EC-Lab
  appends to the MPR for the whole run and `HelaoYml.misc_files` globs live
  directories, so writing straight into the action directory would upload a
  torn file.
- **The range enums are coerced in each backend's `setup()`, not in the
  endpoints.** Since 2026-09-07 the recorded action param is the string
  (`"AUTO"`, `"m1"`, `"BW4"`) rather than the vendor enum's integer.
- Only `biologic_ole/olecom_client.py` may import `comtypes`, and only inside
  a function; a test parses imports to enforce it. `python launch.py
  biologicole` is a hardware-free dev launch of the whole group, and
  `helao/hexagon/tests/test_biologic_column_contract.py` is the gate that both
  backends emit the same columns.
```

- [ ] **Step 7: Run the whole affected suite**

```bash
for f in \
  helao/deploy/hte/tests/test_ole_status.py \
  helao/deploy/hte/tests/test_ole_mps_template.py \
  helao/deploy/hte/tests/test_ole_technique.py \
  helao/deploy/hte/tests/test_ole_client.py \
  helao/deploy/hte/tests/test_ole_sim.py \
  helao/deploy/hte/tests/test_ole_mpr_cursor.py \
  helao/deploy/hte/tests/test_ole_driver.py \
  helao/deploy/hte/tests/test_echem_dispatch.py \
  helao/hexagon/tests/test_biologic_disconnected_construct.py \
  helao/hexagon/tests/test_biologic_backend_select.py \
  helao/hexagon/tests/test_biologic_ole_vendor_isolation.py \
  helao/hexagon/tests/test_biologic_column_contract.py \
  helao/hexagon/tests/test_hte_route_checklist.py \
; do echo "== $f"; timeout 300 pytest "$f" -q || echo "FAILED $f"; done
```

Expected: every file passes. Run them one at a time as above, never as one session.

Then the type check:

```bash
pyright helao/deploy/hte/drivers/pstat/biologic_ole/ \
        helao/deploy/hte/drivers/pstat/biologic_backend.py \
        helao/deploy/hte/servers/action/biologic_server.py
```

Expected: no new errors. Do not remove any existing `# type: ignore` to achieve this.

- [ ] **Step 8: Format and commit**

```bash
black helao/deploy/hte/ helao/hexagon/tests/test_biologic_backend_select.py
git add helao/deploy/hte/configs/biologicole.yml \
        helao/deploy/hte/drivers/pstat/biologic_ole/templates/README.md \
        helao/hexagon/tests/test_biologic_backend_select.py \
        CLAUDE.md
git commit -m "feat(hte): launchable simulated OLE config, and the docs

python launch.py biologicole brings the whole group up on the fake COM
server with no EC-Lab, no comtypes and no instrument. templates/README.md
records the nine .mps files that must be authored at a station, and why
authoring them in the GUI is the only way to be sure the hardware accepts
them. CLAUDE.md gains the backend section and its traps.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## At-station gates

None of these can be discharged on Linux and none are part of the tasks above.
Every task completes and verifies without them; what they unblock is a *real*
station, not the plan.

1. **Settle CV's `AcqInterval__V`.** EC-Lab's Cyclic Voltammetry has no
   `dE (mV)` row — `Step percent` and `N` govern recording instead, and the
   real `CV.mps` holds `50` and `10`. `AcqInterval__V` is unmapped, so those
   template values stand on every CV this backend runs. Needs the station
   owner's judgement, not a guess. **This is the only remaining
   template-side question**; all nine templates are present and every
   registry caption is verified against them on Linux.
2. **The ProgID.** `DEFAULT_PROGID = "EC-Lab.Application"` is conventional, not
   documented. Confirm it, or set the `progid` server param.
3. **The `MeasureDcValue` bulk-return probe.** Read one index from a file with
   many points and count what comes back. If it returns every remaining point,
   the poll cost collapses; `MprCursor` already handles both.
4. **The `comtypes` out-parameter convention.** `_unpack` assumes a scalar or
   `(Result, *outs)`. Confirm against a live EC-Lab; a correction lands in
   `_unpack` and `sim.py` together, and nowhere else.
5. **Side-by-side run.** Same cell, same parameters, both backends back to
   back, comparing traces. The only check that catches a wrong `.mps`
   parameter mapping. Also settles whether CAOCV's `t_s` is continuous or
   restarting across the technique boundary — the OLE driver offsets it to
   stay monotonic, and the eclib behaviour is not knowable from here.
6. **TTL with a scope**, if any private deployment passes a non-default
   trigger parameter. Nothing in the tracked tree does.

## Out of scope

* Migrating any station. Every config keeps `eclib` until someone adds
  `pstat_backend: olecom`.
* First-class endpoints for EC-Lab's other 140 techniques. `run_protocol`
  reaches them through a station-authored `.mps`.
* A golden-capture canary variant. The frozen checklist and the column
  contract cover the same ground on Linux, and the canary's reference — a live
  eclib server — is exactly what an OLE-only station will not have.
* An eclib simulator. The eclib side of the column contract is pinned by its
  registry declaration, which is what its driver's `field_remap` uses at
  runtime.
