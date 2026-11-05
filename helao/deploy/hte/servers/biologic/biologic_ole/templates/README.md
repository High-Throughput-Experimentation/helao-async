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
