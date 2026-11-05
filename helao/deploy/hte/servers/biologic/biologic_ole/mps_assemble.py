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
        configured = set_param(trigger_in, IN_CHANNEL_PARAM, str(ttl.wait), technique=0)
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
