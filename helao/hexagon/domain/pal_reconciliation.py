"""PAL sample-reconciliation domain service (P3a-PAL slice 3): the source/
dest position-resolution and post-trigger sample-pipeline algorithm lifted
out of ``helao/deploy/hte/drivers/robot/pal_driver.py``'s ``PAL`` driver --
the ``TransformXY``/``JsonFileCalibrationStore`` analogue for PAL (galil
D6/slice-2 precedent). Base-free: no ``helao_logging``, no
``helao.core.servers.base``, no vendor (paramiko/nidaqmx) imports -- stdlib
``logging`` only, mirroring ``motion_transform.py``'s allow-list.

Constructed with ``(sample_state: SampleStatePort, cams)`` (P3a-PAL plan
Decision 2): the port is injected rather than a ``DataSink``/``Active``
handle, and ``action_uuid``/``action`` are read only as PLAIN PARAMS on the
methods that need them -- never held as instance state. ``cams`` is the
same ``CAMS``-shaped table the driver builds from server config (an
``Enum`` whose members' ``.value`` is a ``_cam`` template); it is passed
through opaquely (duck-typed, not imported from the deploy tree) and used
for per-microcam cam-template lookup once cam-table assembly is folded in
(slice 3b).

Slice 3a scope: source-position resolution only (``_check_source*`` +
the shared ``_next_full_vial`` helper both source and dest use). This is
purely ADDITIVE -- ``pal_driver.py`` still carries its own copies of these
methods and is not yet wired to call into this service; the cutover (dest
resolution, ``plan()``, and the after-trigger reconciliation) lands in
slices 3b-3d.

Known pre-existing bug preserved verbatim (not this slice's concern to
fix): the legacy ``_sendcommand_check_source``'s ``next_full_vial`` branch
calls the ``next_empty_vial`` checker instead of ``_next_full_vial`` --
copied here unchanged in ``_check_source`` to keep behavior byte-identical
to the shipped driver.
"""

import logging
from copy import deepcopy
from typing import Tuple, Union

from helao.hexagon.domain.models import (
    ErrorCodes,
    AssemblySample,
    GasSample,
    LiquidSample,
    NoneSample,
    PALposition,
    PalAction,
    PalMicroCam,
    SampleInheritance,
    SampleStatus,
    SolidSample,
    _positiontype,
)
from helao.hexagon.ports.sample_state import SampleStatePort

LOGGER = logging.getLogger(__name__)

__all__ = ["PalReconciliation"]


class PalReconciliation:
    """Resolves PAL source/dest positions and reconciles post-trigger sample
    state against a :class:`SampleStatePort`.

    Attributes:
        sample_state: Injected sample-state port (never a DataSink/Active
            handle -- see module docstring, Decision 2).
        cams: The driver's ``CAMS``-shaped cam table (duck-typed; only
            ``self.cams[method_name].value`` is ever read, in slice 3b).
    """

    def __init__(self, sample_state: SampleStatePort, cams):
        self.sample_state = sample_state
        self.cams = cams

    async def _next_full_vial(
        self,
        after_tray: int,
        after_slot: int,
        after_vial: int,
    ) -> Tuple[
        ErrorCodes,
        int,
        int,
        int,
        Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample],
    ]:
        """Locate the next full vial after a given tray/slot/vial.

        Args:
            after_tray: Tray index to search after.
            after_slot: Slot index to search after.
            after_vial: Vial index to search after.

        Returns:
            Tuple ``(error, tray, slot, vial, sample)``. Position fields are
            ``None`` and ``sample`` is a :class:`NoneSample` if no vial is
            available.
        """
        error = ErrorCodes.none
        tray_pos = None
        slot_pos = None
        vial_pos = None
        sample = NoneSample()

        if after_tray is None or after_slot is None or after_vial is None:
            error = ErrorCodes.not_available
            return error, tray_pos, slot_pos, vial_pos, sample

        # if tray is None, find the global first full vial,
        # else find the next full after that one
        # this will add the sample to global sample_in
        newvialpos = await self.sample_state.tray_get_next_full(
            after_tray=after_tray, after_slot=after_slot, after_vial=after_vial
        )

        if newvialpos["tray"] is not None:
            tray_pos = newvialpos["tray"]
            slot_pos = newvialpos["slot"]
            vial_pos = newvialpos["vial"]

            LOGGER.info(
                f"diluting liquid sample in tray {tray_pos}, slot {slot_pos}, vial {vial_pos}"
            )

            # need to get the sample which is currently in this vial
            # and also add it to global samples_in
            error, sample = await self.sample_state.tray_query_sample(
                tray=tray_pos, slot=slot_pos, vial=vial_pos
            )
            if error != ErrorCodes.none:
                if sample != NoneSample():
                    sample.inheritance = SampleInheritance.allow_both
                    sample.reset_sample_status(SampleStatus.preserved)
                else:
                    error = ErrorCodes.not_available
                    LOGGER.error("error converting old liquid_sample to basemodel.")

        else:
            LOGGER.error("no full vial slots")
            error = ErrorCodes.not_available

        return error, tray_pos, slot_pos, vial_pos, sample

    async def _check_source_tray(self, microcam: PalMicroCam) -> PALposition:
        """Return the tray-source :class:`PALposition`, with an error if no sample.

        Args:
            microcam: Microcam carrying the requested tray/slot/vial.

        Returns:
            Resolved :class:`PALposition` whose ``error`` indicates whether
            a sample was found.
        """
        source = (
            _positiontype.tray
        )  # should be the same as microcam.requested_source.position
        error, sample_in = await self.sample_state.tray_query_sample(
            microcam.requested_source.tray,
            microcam.requested_source.slot,
            microcam.requested_source.vial,
        )

        if error != ErrorCodes.none:
            LOGGER.error("PAL_source: Requested tray position does not exist.")
            error = ErrorCodes.critical_error

        elif sample_in == NoneSample():
            LOGGER.error(
                f"PAL_source: No sample in tray {microcam.requested_source.tray}, slot {microcam.requested_source.slot}, vial {microcam.requested_source.vial}"
            )
            error = ErrorCodes.not_available

        return PALposition(
            position=source,
            samples_initial=[sample_in],
            tray=microcam.requested_source.tray,
            slot=microcam.requested_source.slot,
            vial=microcam.requested_source.vial,
            error=error,
        )

    async def _check_source_custom(self, microcam: PalMicroCam) -> PALposition:
        """Return the custom-source :class:`PALposition`, with an error if no sample.

        Args:
            microcam: Microcam carrying the requested custom position name.
        """
        source = microcam.requested_source.position  # custom position name

        if source is None:
            LOGGER.error(
                "PAL_source: Invalid PAL source 'NONE' for 'custom' position method."
            )
            return PALposition(error=ErrorCodes.not_available)

        error, sample_in = await self.sample_state.custom_query_sample(
            microcam.requested_source.position
        )

        if error != ErrorCodes.none:
            LOGGER.error("PAL_source: Requested custom position does not exist.")
            error = ErrorCodes.critical_error
        elif sample_in == NoneSample():
            LOGGER.error(f"PAL_source: No sample in custom position '{source}'")
            error = ErrorCodes.not_available

        return PALposition(position=source, samples_initial=[sample_in], error=error)

    async def _check_source_next_empty(self, microcam: PalMicroCam) -> PALposition:
        """Reject ``next_empty_vial`` as a PAL source position.

        Args:
            microcam: Unused; included for signature parity with siblings.
        """
        LOGGER.error("PAL_source: PAL source cannot be 'next_empty_vial'")
        return PALposition(error=ErrorCodes.not_available)

    async def _check_source_next_full(self, microcam: PalMicroCam) -> PALposition:
        """Find the next full vial after the requested tray/slot/vial source.

        Args:
            microcam: Microcam carrying the requested tray-relative cursor.
        """

        source = _positiontype.tray
        (
            error,
            source_tray,
            source_slot,
            source_vial,
            sample_in,
        ) = await self._next_full_vial(
            after_tray=microcam.requested_source.tray,
            after_slot=microcam.requested_source.slot,
            after_vial=microcam.requested_source.vial,
        )
        if error != ErrorCodes.none:
            LOGGER.error("PAL_source: No next full vial")
            return PALposition(error=ErrorCodes.not_available)

        elif sample_in == NoneSample():
            LOGGER.error(
                "PAL_source: More then one sample in source position. This is not allowed."
            )
            return PALposition(error=ErrorCodes.critical_error)

        return PALposition(
            position=source,
            samples_initial=[sample_in],
            tray=source_tray,
            slot=source_slot,
            vial=source_vial,
            error=error,
        )

    async def _check_source(self, microcam: PalMicroCam) -> ErrorCodes:
        """Resolve the source position and append a :class:`PalAction` run entry.

        Dispatches to the position-specific source checker based on
        ``microcam.cam.source``, sets the resolved tray/slot/vial back on
        ``microcam.requested_source``, and records the source sample on the
        microcam's runs list. Mutates ``microcam`` in place (matches the
        legacy driver's contract -- the engine reads ``microcam.run[-1]``
        afterwards).

        Args:
            microcam: Microcam whose source is being validated.

        Returns:
            ``ErrorCodes.none`` on success, otherwise the relevant error.
        """

        palposition = PALposition()

        # check against desired source type
        if microcam.cam.source == _positiontype.tray:
            palposition = await self._check_source_tray(microcam=microcam)
            if palposition.error != ErrorCodes.none:
                return palposition.error

        elif microcam.cam.source == _positiontype.custom:
            palposition = await self._check_source_custom(microcam=microcam)
            if palposition.error != ErrorCodes.none:
                return palposition.error

        elif microcam.cam.source == _positiontype.next_empty_vial:
            palposition = await self._check_source_next_empty(microcam=microcam)
            if palposition.error != ErrorCodes.none:
                return palposition.error

        elif microcam.cam.source == _positiontype.next_full_vial:
            # NOTE: pre-existing bug in the shipped driver -- this branch
            # calls the next_empty_vial checker, not _check_source_next_full.
            # Preserved verbatim (see module docstring); not this slice's
            # concern to fix.
            palposition = await self._check_source_next_empty(microcam=microcam)
            if palposition.error != ErrorCodes.none:
                return palposition.error

        # # Set requested position to new position.
        # # The new position will be the requested positin for the
        # # e.g. next full vial search as the new start position
        microcam.requested_source.tray = palposition.tray
        microcam.requested_source.slot = palposition.slot
        microcam.requested_source.vial = palposition.vial

        # if sample_in != NoneSample():
        # should never be the case as this will already throw an error before
        # but better check agin
        if (
            palposition.samples_initial
            and len(palposition.samples_initial) == 1
            and palposition.samples_initial[0] != NoneSample()
        ):

            LOGGER.info(
                f"PAL_source: Got sample '{palposition.samples_initial[0].global_label}' in position '{palposition.position}'"
            )
            # done with checking source type
            # setting inheritance and status to None for all samples
            # in sample_in (will be updated when dest is decided)
            # they all should actually be give only
            # but might not be preserved depending on target
            # sample_in.inheritance =  SampleInheritance.give_only
            # sample_in.status = [SampleStatus.preserved]
            palposition.samples_initial[0].inheritance = None
            palposition.samples_initial[0].reset_sample_status()
            palposition.samples_initial[0].sample_position = palposition.position

        else:
            # this should never happen
            # else we have a bug in the source checks
            if palposition.position is not None:
                LOGGER.error(
                    f"BUG check PAL_source: Got sample no sample in position '{palposition.position}'"
                )

        microcam.run.append(
            PalAction(
                samples_in=deepcopy(palposition.samples_initial),
                source=deepcopy(palposition),
                dilute=[False]
                * len(palposition.samples_initial),  # initial source is not diluted
                dilute_type=[microcam.cam.sample_out_type]
                * len(palposition.samples_initial),
                samples_in_delta_vol_ml=[-1.0 * microcam.volume_ul / 1000.0],
            )
        )

        return ErrorCodes.none
