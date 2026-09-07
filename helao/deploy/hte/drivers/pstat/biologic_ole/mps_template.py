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
