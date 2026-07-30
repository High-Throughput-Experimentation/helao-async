"""PAL sample-reconciliation domain service (P3a-PAL slice 3): the source/
dest position-resolution and post-trigger sample-pipeline algorithm lifted
out of ``helao/deploy/hte/drivers/robot/pal_driver.py``'s ``PAL`` driver --
the ``TransformXY``/``JsonFileCalibrationStore`` analogue for PAL (galil
D6/slice-2 precedent). Base-free: no ``helao_logging``, no
``helao.core.servers.base``, no vendor (paramiko/nidaqmx) imports -- stdlib
``logging`` only, mirroring ``motion_transform.py``'s allow-list.

Constructed with ``(sample_state: SampleStateProtocol, cams)`` (P3a-PAL plan
Decision 2): the collaborator contract is declared here in the domain
(``domain/sample_state.py``) and re-exported by ``ports/sample_state.py`` as
``SampleStatePort`` for adapters to bind to -- the domain must not import
``ports``. The port is injected rather than a ``DataSink``/``Active``
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
from typing import Optional, Union

from helao.hexagon.domain.sample_volume import update_vol
from helao.hexagon.domain.models import (
    Action,
    ErrorCodes,
    AssemblySample,
    GasSample,
    LiquidSample,
    NoneSample,
    PalCam,
    PALposition,
    PalAction,
    PalMicroCam,
    SampleInheritance,
    SampleStatus,
    SampleType,
    SolidSample,
    _positiontype,
)
from helao.hexagon.domain.sample_state import SampleStateProtocol

LOGGER = logging.getLogger(__name__)

__all__ = ["PalReconciliation"]


class PalReconciliation:
    """Resolves PAL source/dest positions and reconciles post-trigger sample
    state against a :class:`SampleStateProtocol` (exposed to adapters and
    composition as ``ports.sample_state.SampleStatePort``).

    Attributes:
        sample_state: Injected sample-state port (never a DataSink/Active
            handle -- see module docstring, Decision 2).
        cams: The driver's ``CAMS``-shaped cam table (duck-typed; only
            ``self.cams[method_name].value`` is ever read, in slice 3b).
    """

    def __init__(self, sample_state: SampleStateProtocol, cams):
        self.sample_state = sample_state
        self.cams = cams

    async def _next_full_vial(
        self,
        after_tray: int,
        after_slot: int,
        after_vial: int,
    ) -> tuple[
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

    async def _check_dest_tray(
        self, microcam: PalMicroCam, action: Optional[Action] = None
    ) -> tuple[
        PALposition,
        list[Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]],
    ]:
        """Resolve a tray destination, creating a new sample ref if the vial is empty.

        Args:
            microcam: Microcam carrying the requested tray/slot/vial dest.
            action: Job-context ``Action`` forwarded to
                ``sample_state.new_ref_samples`` (Decision 2: plain param,
                not a DataSink/Active handle).

        Returns:
            Tuple ``(palposition, samples_out_list)`` where ``samples_out_list``
            contains the newly created reference sample (or is empty if the
            vial already held a sample and is being diluted).
        """
        samples_out_list: list[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = []
        dest_samples_initial: list[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = []
        dest_samples_final: list[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = []

        dest = _positiontype.tray
        error, sample_in = await self.sample_state.tray_query_sample(
            microcam.requested_dest.tray,
            microcam.requested_dest.slot,
            microcam.requested_dest.vial,
        )

        if error != ErrorCodes.none:
            LOGGER.error("PAL_dest: Requested tray position does not exist.")
            return PALposition(error=ErrorCodes.critical_error), samples_out_list

        # check if a sample is present in destination
        if sample_in == NoneSample():
            # no sample in dest, create a new sample reference
            LOGGER.info(
                f"PAL_dest: No sample in tray {microcam.requested_dest.tray}, slot {microcam.requested_dest.slot}, vial {microcam.requested_dest.vial}"
            )
            if len(microcam.run[-1].samples_in) > 1:
                LOGGER.error(
                    f"PAL_dest: Found a BUG: Assembly not allowed for PAL dest '{dest}' for 'tray' position method."
                )
                return PALposition(error=ErrorCodes.bug), samples_out_list

            error, samples_out_list = await self.sample_state.new_ref_samples(
                samples_in=microcam.run[
                    -1
                ].samples_in,  # this should hold a sample already from "check source call"
                sample_out_type=microcam.cam.sample_out_type,
                sample_position=dest,
                action=action,
            )

            if error != ErrorCodes.none:
                return PALposition(error=error), samples_out_list

            # this will be a single sample anyway
            samples_out_list[0].volume_ml = microcam.volume_ul / 1000.0
            samples_out_list[0].sample_position = dest
            samples_out_list[0].inheritance = SampleInheritance.receive_only
            samples_out_list[0].reset_sample_status(SampleStatus.created)
            dest_samples_initial = []  # no sample here in the beginning
            dest_samples_final = deepcopy(samples_out_list)

        else:
            # a sample is already present in the tray position
            # we add more sample to it, e.g. dilute it
            LOGGER.info(
                f"PAL_dest: Got sample '{sample_in.global_label}' in position '{dest}'"
            )
            # we can only add liquid to vials (diluite them, no assembly here)
            sample_in.inheritance = SampleInheritance.receive_only
            sample_in.reset_sample_status(SampleStatus.preserved)

            dest_samples_initial = [deepcopy(sample_in)]
            dest_samples_final = [deepcopy(sample_in)]

            # add that sample to the current sample_in list
            microcam.run[-1].samples_in.append(deepcopy(sample_in))
            microcam.run[-1].samples_in_delta_vol_ml.append(microcam.volume_ul / 1000.0)
            microcam.run[-1].dilute.append(True)
            microcam.run[-1].dilute_type.append(sample_in.sample_type)

        return (
            PALposition(
                position=dest,
                samples_initial=dest_samples_initial,
                samples_final=dest_samples_final,
                tray=microcam.requested_dest.tray,
                slot=microcam.requested_dest.slot,
                vial=microcam.requested_dest.vial,
                error=error,
            ),
            samples_out_list,
        )

    async def _check_dest_custom(
        self, microcam: PalMicroCam, action: Optional[Action] = None
    ) -> tuple[
        PALposition,
        list[Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]],
    ]:
        """Resolve a custom destination, creating a new sample, diluting, or assembling.

        Handles the cases where the destination is empty, holds an assembly,
        holds the same sample type (dilute), or holds a different type
        (create an assembly when allowed).

        Args:
            microcam: Microcam carrying the requested custom destination name.
            action: Job-context ``Action`` forwarded to
                ``sample_state.new_ref_samples`` (Decision 2).

        Returns:
            Tuple of the resolved :class:`PALposition` and the new output samples.
        """
        samples_out_list: list[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = []
        dest_samples_initial: list[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = []
        dest_samples_final: list[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = []

        dest = microcam.requested_dest.position
        if dest is None:
            LOGGER.error(
                "PAL_dest: Invalid PAL dest 'NONE' for 'custom' position method."
            )
            return PALposition(error=ErrorCodes.critical_error), samples_out_list

        if not await self.sample_state.custom_dest_allowed(dest):
            LOGGER.error(f"PAL_dest: custom position '{dest}' cannot be dest.")
            return PALposition(error=ErrorCodes.critical_error), samples_out_list

        error, sample_in = await self.sample_state.custom_query_sample(dest)
        if error != ErrorCodes.none:
            LOGGER.error(
                f"PAL_dest: Invalid PAL dest '{dest}' for 'custom' position method."
            )
            return PALposition(error=error), samples_out_list

        # check if a sample is already present in the custom position
        if sample_in == NoneSample():
            # no sample in custom position, create a new sample reference
            LOGGER.info(
                f"PAL_dest: No sample in custom position '{dest}', creating new sample reference."
            )

            # cannot create an assembly
            if len(microcam.run[-1].samples_in) > 1:
                LOGGER.error(
                    "PAL_dest: Found a BUG: Too many input samples. Cannot create an assembly here."
                )
                return PALposition(error=ErrorCodes.bug), samples_out_list

            # this should actually never create an assembly
            error, samples_out_list = await self.sample_state.new_ref_samples(
                samples_in=microcam.run[-1].samples_in,
                sample_out_type=microcam.cam.sample_out_type,
                sample_position=dest,
                action=action,
            )

            if error != ErrorCodes.none:
                return PALposition(error=error), samples_out_list

            samples_out_list[0].volume_ml = microcam.volume_ul / 1000.0
            samples_out_list[0].sample_position = dest
            samples_out_list[0].inheritance = SampleInheritance.receive_only
            samples_out_list[0].reset_sample_status(SampleStatus.created)
            dest_samples_initial = []  # no sample here in the beginning
            dest_samples_final = deepcopy(samples_out_list)

        else:
            # sample is already present
            # either create an assembly or dilute it
            # first check what type is present
            LOGGER.info(
                f"PAL_dest: Got sample '{sample_in.global_label}' in position '{dest}'"
            )

            if sample_in.sample_type == SampleType.assembly:
                # need to check if we already go the same type in
                # the assembly and then would dilute too
                # else we add a new sample to that assembly

                # source input should only hold a single sample
                # but better check for sure
                if len(microcam.run[-1].samples_in) > 1:
                    LOGGER.error(
                        "PAL_dest: Found a BUG: Too many input samples. Cannot create an assembly here."
                    )
                    return PALposition(error=ErrorCodes.bug), samples_out_list

                test = False
                if microcam.run[-1].samples_in[-1].sample_type == SampleType.liquid:
                    test = await self._check_for_assemblytypes(
                        sample_type=SampleType.liquid, assembly=sample_in
                    )
                elif microcam.run[-1].samples_in[-1].sample_type == SampleType.solid:
                    test = False  # always add it as a new part
                elif microcam.run[-1].samples_in[-1].sample_type == SampleType.gas:
                    test = await self._check_for_assemblytypes(
                        sample_type=SampleType.gas, assembly=sample_in
                    )
                else:
                    LOGGER.error("PAL_dest: Found a BUG: unsupported sample type.")
                    return PALposition(error=ErrorCodes.bug), samples_out_list

                if test is True:
                    # we dilute the assembly sample
                    dest_samples_initial = deepcopy(samples_out_list)
                    dest_samples_final = deepcopy(samples_out_list)

                    # we can only add liquid to vials
                    # (diluite them, no assembly here)
                    sample_in.inheritance = SampleInheritance.receive_only
                    sample_in.reset_sample_status(SampleStatus.preserved)

                    # first add the dilute type
                    microcam.run[-1].dilute_type.append(
                        microcam.run[-1].samples_in[-1].sample_type
                    )
                    microcam.run[-1].samples_in_delta_vol_ml.append(
                        microcam.volume_ul / 1000.0
                    )
                    microcam.run[-1].dilute.append(True)
                    # then add the new sample_in
                    microcam.run[-1].samples_in.append(deepcopy(sample_in))
                else:
                    # add a new part to assembly
                    LOGGER.info("PAL_dest: Adding new part to assembly")
                    if len(microcam.run[-1].samples_in) > 1:
                        # sample_in should only hold one sample at that point
                        LOGGER.error(
                            f"PAL_dest: Found a BUG: Assembly not allowed for PAL dest '{dest}' for 'tray' position method."
                        )
                        return PALposition(error=ErrorCodes.bug), samples_out_list

                    # first create a new sample from the source sample
                    # which is then incoporarted into the assembly
                    error, samples_out_list = await self.sample_state.new_ref_samples(
                        samples_in=microcam.run[
                            -1
                        ].samples_in,  # this should hold a sample already from "check source call"
                        sample_out_type=microcam.cam.sample_out_type,
                        sample_position=dest,
                        action=action,
                    )

                    if error != ErrorCodes.none:
                        return PALposition(error=error), samples_out_list

                    samples_out_list[0].volume_ml = microcam.volume_ul / 1000.0
                    samples_out_list[0].sample_position = dest
                    samples_out_list[0].inheritance = SampleInheritance.allow_both
                    samples_out_list[0].reset_sample_status(
                        SampleStatus.created, SampleStatus.incorporated
                    )

                    # add new sample to assembly
                    sample_in.parts.append(samples_out_list[0])
                    # we can only add liquid to vials
                    # (diluite them, no assembly here)
                    sample_in.inheritance = SampleInheritance.allow_both
                    sample_in.reset_sample_status(SampleStatus.preserved)

                    dest_samples_initial = [deepcopy(sample_in)]
                    dest_samples_final = [deepcopy(sample_in)]
                    microcam.run[-1].samples_in.append(deepcopy(sample_in))

            elif sample_in.sample_type == microcam.run[-1].samples_in[-1].sample_type:
                # we dilute it if its the same sample type
                # (and not an assembly),
                # we can only add liquid to vials
                # (diluite them, no assembly here)
                sample_in.inheritance = SampleInheritance.receive_only
                sample_in.reset_sample_status(SampleStatus.preserved)

                dest_samples_initial = [deepcopy(sample_in)]
                dest_samples_final = [deepcopy(sample_in)]

                microcam.run[-1].dilute_type.append(sample_in.sample_type)
                microcam.run[-1].samples_in.append(deepcopy(sample_in))
                microcam.run[-1].samples_in_delta_vol_ml.append(
                    microcam.volume_ul / 1000.0
                )
                microcam.run[-1].dilute.append(True)

            else:
                # neither same sample type nor an assembly present.
                # we now create an assembly if allowed
                if not await self.sample_state.custom_assembly_allowed(dest):
                    # no assembly allowed
                    LOGGER.error(
                        f"PAL_dest: Assembly not allowed for PAL dest '{dest}' for 'custom' position method."
                    )
                    return PALposition(error=ErrorCodes.not_allowed), samples_out_list

                # cannot create an assembly from an assembly
                if len(microcam.run[-1].samples_in) > 1:
                    LOGGER.error(
                        "PAL_dest: Found a BUG: Too many input samples. Cannot create an assembly here."
                    )
                    return PALposition(error=ErrorCodes.bug), samples_out_list

                # dest_sample = sample_in
                # first create a new sample from the source sample
                # which is then incoporarted into the assembly
                error, samples_out_list = await self.sample_state.new_ref_samples(
                    samples_in=microcam.run[-1].samples_in,
                    sample_out_type=microcam.cam.sample_out_type,
                    sample_position=dest,
                    action=action,
                )

                if error != ErrorCodes.none:
                    return PALposition(error=error), samples_out_list

                samples_out_list[0].volume_ml = microcam.volume_ul / 1000.0
                samples_out_list[0].sample_position = dest
                samples_out_list[0].inheritance = SampleInheritance.allow_both
                samples_out_list[0].reset_sample_status(
                    SampleStatus.created, SampleStatus.incorporated
                )

                # only now add the sample which was found in the position
                # to the sample_in list for the exp/prg
                sample_in.inheritance = SampleInheritance.allow_both
                sample_in.reset_sample_status(SampleStatus.incorporated)

                microcam.run[-1].samples_in.append(deepcopy(sample_in))
                # we only add the sample to assembly so delta_vol is 0
                microcam.run[-1].samples_in_delta_vol_ml.append(0.0)
                microcam.run[-1].dilute.append(False)
                microcam.run[-1].dilute_type.append(None)

                # create now an assembly of both
                tmp_samples_in = [sample_in]
                # and also add the newly created sample ref to it
                tmp_samples_in.append(samples_out_list[0])
                LOGGER.info(
                    f"PAL_dest: Creating assembly from '{[sample.global_label for sample in tmp_samples_in]}' in position '{dest}'"
                )
                error, samples_out2_list = await self.sample_state.new_ref_samples(
                    samples_in=tmp_samples_in,
                    sample_out_type=SampleType.assembly,
                    sample_position=dest,
                    action=action,
                )

                if error != ErrorCodes.none:
                    return PALposition(error=error), samples_out_list

                samples_out2_list[0].sample_position = dest
                samples_out2_list[0].inheritance = SampleInheritance.allow_both
                samples_out2_list[0].reset_sample_status(SampleStatus.created)
                # add second sample out to samples_out
                samples_out_list.append(samples_out2_list[0])

                # intial is the sample initial in the position
                dest_samples_initial = [deepcopy(sample_in)]
                # this will be the new assembly
                dest_samples_final = deepcopy(samples_out2_list)

        return (
            PALposition(
                position=dest,
                samples_initial=dest_samples_initial,
                samples_final=dest_samples_final,
                tray=microcam.requested_dest.tray,
                slot=microcam.requested_dest.slot,
                vial=microcam.requested_dest.vial,
                error=error,
            ),
            samples_out_list,
        )

    async def _check_dest_next_empty(
        self, microcam: PalMicroCam, action: Optional[Action] = None
    ) -> tuple[
        PALposition,
        list[Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]],
    ]:
        """Find the next empty vial with enough volume capacity and create a sample ref.

        Args:
            microcam: Microcam supplying the volume requirement.
            action: Job-context ``Action`` forwarded to
                ``sample_state.new_ref_samples`` (Decision 2).
        """
        samples_out_list: list[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = []
        dest_samples_initial: list[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = []
        dest_samples_final: list[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = []

        dest_tray = None
        dest_slot = None
        dest_vial = None

        dest = _positiontype.tray
        newvialpos = await self.sample_state.tray_new_position(
            req_vol=microcam.volume_ul / 1000.0
        )

        if newvialpos["tray"] is None:
            LOGGER.error("PAL_dest: empty vial slot is not available")
            return PALposition(error=ErrorCodes.not_available), samples_out_list

        # dest = _positiontype.tray
        dest_tray = newvialpos["tray"]
        dest_slot = newvialpos["slot"]
        dest_vial = newvialpos["vial"]
        LOGGER.info(
            f"PAL_dest: archiving liquid sample to tray {dest_tray}, slot {dest_slot}, vial {dest_vial}"
        )

        error, samples_out_list = await self.sample_state.new_ref_samples(
            samples_in=microcam.run[
                -1
            ].samples_in,  # this should hold a sample already from "check source call"
            sample_out_type=microcam.cam.sample_out_type,
            sample_position=dest,
            action=action,
        )

        LOGGER.info(f"new reference sample for empty vial: {samples_out_list}")

        if error != ErrorCodes.none:
            return PALposition(error=error), samples_out_list

        samples_out_list[0].volume_ml = microcam.volume_ul / 1000.0
        samples_out_list[0].sample_position = dest
        samples_out_list[0].inheritance = SampleInheritance.receive_only
        samples_out_list[0].reset_sample_status(SampleStatus.created)
        dest_samples_initial = []  # no sample here in the beginning
        dest_samples_final = deepcopy(samples_out_list)

        return (
            PALposition(
                position=dest,
                samples_initial=dest_samples_initial,
                samples_final=dest_samples_final,
                tray=dest_tray,
                slot=dest_slot,
                vial=dest_vial,
                error=error,
            ),
            samples_out_list,
        )

    async def _check_dest_next_full(self, microcam: PalMicroCam) -> tuple[
        PALposition,
        list[Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]],
    ]:
        """Find the next full vial after the requested tray cursor as the destination.

        Args:
            microcam: Microcam carrying the requested tray-relative cursor.
        """
        samples_out_list: list[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = []
        dest_samples_initial: list[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = []
        dest_samples_final: list[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = []

        dest = _positiontype.tray
        (
            error,
            dest_tray,
            dest_slot,
            dest_vial,
            sample_in,
        ) = await self._next_full_vial(
            after_tray=microcam.requested_dest.tray,
            after_slot=microcam.requested_dest.slot,
            after_vial=microcam.requested_dest.vial,
        )
        if error != ErrorCodes.none:
            LOGGER.error("PAL_dest: No next full vial")
            return PALposition(error=ErrorCodes.not_available), samples_out_list
        if sample_in == NoneSample():
            LOGGER.error(
                "PAL_dest: More then one sample in source position. This is not allowed."
            )
            return PALposition(error=ErrorCodes.critical_error), samples_out_list

        # a sample is already present in the tray position
        # we add more sample to it, e.g. dilute it
        LOGGER.info(
            f"PAL_dest: Got sample '{sample_in.global_label}' in position '{dest}'"
        )
        sample_in.inheritance = SampleInheritance.receive_only
        sample_in.reset_sample_status(SampleStatus.preserved)

        microcam.run[-1].samples_in.append(sample_in)
        microcam.run[-1].samples_in_delta_vol_ml.append(microcam.volume_ul / 1000.0)
        microcam.run[-1].dilute.append(True)
        microcam.run[-1].dilute_type.append(sample_in.sample_type)

        dest_samples_initial = [deepcopy(sample_in)]
        dest_samples_final = [deepcopy(sample_in)]

        return (
            PALposition(
                position=dest,
                samples_initial=dest_samples_initial,
                samples_final=dest_samples_final,
                tray=dest_tray,
                slot=dest_slot,
                vial=dest_vial,
                error=error,
            ),
            samples_out_list,
        )

    async def _check_dest(
        self, microcam: PalMicroCam, action: Optional[Action] = None
    ) -> ErrorCodes:
        """Resolve the destination position and update the microcam's run entry.

        Dispatches to the destination-specific checker based on
        ``microcam.cam.dest``, marks samples as destroyed when the
        destination is configured as destructive, and accumulates input
        inheritance/status for samples not already assigned. Mutates
        ``microcam`` in place (matches the legacy driver's contract).

        Args:
            microcam: Microcam whose destination is being validated.
            action: Job-context ``Action`` forwarded to the tray/custom/
                next_empty checkers (Decision 2).

        Returns:
            ``ErrorCodes.none`` on success.
        """

        samples_out_list: list[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ] = []
        palposition = PALposition()

        if microcam.cam.dest == _positiontype.tray:
            palposition, samples_out_list = await self._check_dest_tray(
                microcam=microcam, action=action
            )
            if palposition.error != ErrorCodes.none:
                return palposition.error

        elif microcam.cam.dest == _positiontype.custom:
            palposition, samples_out_list = await self._check_dest_custom(
                microcam=microcam, action=action
            )
            if palposition.error != ErrorCodes.none:
                return palposition.error

        elif microcam.cam.dest == _positiontype.next_empty_vial:
            (
                palposition,
                samples_out_list,
            ) = await self._check_dest_next_empty(microcam=microcam, action=action)
            if palposition.error != ErrorCodes.none:
                return palposition.error

        elif microcam.cam.dest == _positiontype.next_full_vial:
            (
                palposition,
                samples_out_list,
            ) = await self._check_dest_next_full(microcam=microcam)
            if palposition.error != ErrorCodes.none:
                return palposition.error

        # done with destination checks

        # Set requested position to new position.
        # The new position will be the requested position for the
        # next full vial search as the new start position
        microcam.requested_dest.tray = palposition.tray
        microcam.requested_dest.slot = palposition.slot
        microcam.requested_dest.vial = palposition.vial

        # check if final samples would be destroyed directly after they
        # were created
        if await self.sample_state.custom_is_destroyed(custom=palposition.position):
            for sample in samples_out_list:
                sample.append_sample_status(SampleStatus.destroyed)
            for sample in palposition.samples_final:
                sample.append_sample_status(SampleStatus.destroyed)

        # add validated destination to run
        microcam.run[-1].dest = deepcopy(palposition)

        # update the rest of sample_in for the run
        for sample in microcam.run[-1].samples_in:
            if sample.inheritance is None:
                sample.inheritance = SampleInheritance.give_only
                sample.reset_sample_status(SampleStatus.preserved)

        # add the samples_out to the run
        for sample in samples_out_list:
            microcam.run[-1].samples_out.append(sample)

        # a quick message if samples will be diluted or not
        for i, sample in enumerate(microcam.run[-1].samples_in):
            if i >= len(microcam.run[-1].dilute):
                LOGGER.info(
                    f"PAL: Not diluting sample_in '{sample.global_label}' because dilute bool not specified."
                )
            elif microcam.run[-1].dilute[i]:
                LOGGER.info(f"PAL: Diluting sample_in '{sample.global_label}'.")
            else:
                LOGGER.info(f"PAL: Not diluting sample_in '{sample.global_label}'.")

        return ErrorCodes.none

    async def _check_for_assemblytypes(
        self, sample_type: str, assembly: AssemblySample
    ) -> bool:
        """Return whether ``assembly`` already contains a part of ``sample_type``.

        Args:
            sample_type: Sample type to search for.
            assembly: Assembly whose ``parts`` are inspected.
        """
        for part in assembly.parts:
            if part.sample_type == sample_type:
                return True
        return False

    async def plan(
        self,
        palcam: PalCam,
        action_uuid=None,
        action: Optional[Action] = None,
    ) -> ErrorCodes:
        """Resolve the cam template, source, and destination for every
        microcam/repeat in ``palcam``, mutating ``palcam.microcams`` in
        place (cam-table assembly + source/dest resolution folded together,
        P3a-PAL slice 3b).

        Mirrors the first half of the legacy driver's
        ``_sendcommand_prechecks`` loop (cam lookup + ``_check_source`` +
        ``_check_dest``) verbatim. Per Decision 1, this method does NOT
        build the ``_palcmd`` joblist strings or write the aux log file --
        the engine still owns joblist assembly and reads the resolved
        ``microcam.run[-1].source``/``.dest`` positions this method leaves
        behind.

        Args:
            palcam: Job descriptor whose ``microcams`` will be resolved.
            action_uuid: Accepted for signature symmetry with
                :meth:`reconcile_after_trigger` (Decision 2's job-context
                pair); not read by ``plan()`` itself -- no call in this
                method's lifted body stamps ``action_uuid`` directly.
            action: Job-context ``Action`` forwarded to
                ``sample_state.new_ref_samples`` via ``_check_dest*``.

        Returns:
            ``ErrorCodes.none`` on success or the first failure encountered.
        """
        for microcam in palcam.microcams:
            # get the correct cam definition which contains all params
            # for the correct submission of the job to the PAL
            if microcam.method in [e.name for e in self.cams]:
                if self.cams[microcam.method].value.file_name is not None:
                    microcam.cam = self.cams[microcam.method].value
                else:
                    LOGGER.error(f"cam method '{microcam.method}' is not available")
                    return ErrorCodes.not_available
            else:
                LOGGER.error(f"cam method '{microcam.method}' is not available")
                return ErrorCodes.not_available

            # set runs to empty list
            # shouldn't actually need it but better be sure its an empty list
            # at this point
            microcam.run = []

            for repeat in range(microcam.repeat + 1):
                # check source position
                error = await self._check_source(microcam)
                if error != ErrorCodes.none:
                    return error
                # check target position
                error = await self._check_dest(microcam, action=action)
                if error != ErrorCodes.none:
                    return error

        return ErrorCodes.none

    async def _update_archive_helper(
        self, palaction: PalAction, action_uuid=None
    ) -> ErrorCodes:
        """Push final source/dest samples for ``palaction`` back into the archive.

        Resolves ``samples_final`` against the unified sample DB (or the
        last sample in ``samples_out`` for unassigned reference samples) and
        updates tray or custom position entries accordingly.

        Args:
            palaction: Finished execution to write back.
            action_uuid: Job-context action UUID stamped onto resolved
                samples (Decision 2: plain param, not a DataSink/Active
                handle).

        Returns:
            ``ErrorCodes.none`` on success or ``ErrorCodes.not_available``
            if an archive update fails.
        """

        # update source and dest final samples
        palaction.source.samples_final = await self.sample_state.get_samples(
            samples=palaction.source.samples_initial
        )
        # update the action_uuid
        for sample in palaction.source.samples_final:
            sample.action_uuid = [action_uuid]

        if palaction.dest.samples_final:
            # should always only contain one sample
            if palaction.dest.samples_final[0].global_label is None:
                # dest_final contains a ref sample
                # the correct new sample should be always found
                # in the last position of palaction.samples_out
                # which should already be uptodate
                palaction.dest.samples_final = [palaction.samples_out[-1]]
            else:
                palaction.dest.samples_final = await self.sample_state.get_samples(
                    samples=palaction.dest.samples_final
                )

        # update the action_uuid
        for sample in palaction.dest.samples_final:
            sample.action_uuid = [action_uuid]

        error = ErrorCodes.none
        retval = False
        if palaction.source.samples_final:
            if palaction.source.position == "tray":
                retval = await self.sample_state.tray_update_position(
                    tray=palaction.source.tray,
                    slot=palaction.source.slot,
                    vial=palaction.source.vial,
                    sample=palaction.source.samples_final[0],
                )
            else:  # custom postion
                retval, sample = await self.sample_state.custom_update_position(
                    custom=palaction.source.position,
                    sample=palaction.source.samples_final[0],
                )
        else:
            LOGGER.info("No sample in PAL source.")

        if palaction.dest.samples_final:
            if palaction.dest.position == "tray":
                retval = await self.sample_state.tray_update_position(
                    tray=palaction.dest.tray,
                    slot=palaction.dest.slot,
                    vial=palaction.dest.vial,
                    sample=palaction.dest.samples_final[0],
                )
            else:  # custom postion
                retval, sample = await self.sample_state.custom_update_position(
                    custom=palaction.dest.position,
                    sample=palaction.dest.samples_final[0],
                )
        else:
            LOGGER.info("No sample in PAL dest.")

        if not retval:
            error = ErrorCodes.not_available

        return error

    async def _update_sample_volume(self, palaction: PalAction) -> None:
        """Apply per-input dilution volumes to input samples (or assembly parts).

        Output samples are skipped because they are always created fresh by
        the PAL action.

        Args:
            palaction: Execution carrying ``samples_in`` and the parallel
                ``dilute``, ``dilute_type`` and ``samples_in_delta_vol_ml``
                lists.
        """
        if len(palaction.samples_in_delta_vol_ml) != len(palaction.samples_in):
            LOGGER.error("len(samples_in) != len(delta_vol)")
            return
        if len(palaction.dilute) != len(palaction.samples_in):
            LOGGER.error("len(samples_in) != len(dilute)")
            return
        if len(palaction.dilute_type) != len(palaction.samples_in):
            LOGGER.error("len(samples_in) != len(sample_type)")
            return

        for i, sample in enumerate(palaction.samples_in):
            if sample.sample_type == SampleType.assembly:
                # if sample.sample_type == SampleType.assembly:
                for part in sample.parts:
                    if part.sample_type == palaction.dilute_type[i]:
                        update_vol(
                            part,
                            palaction.samples_in_delta_vol_ml[i],
                            palaction.dilute[i],
                        )
            else:
                update_vol(
                    sample, palaction.samples_in_delta_vol_ml[i], palaction.dilute[i]
                )

    async def reconcile_after_trigger(
        self,
        palaction: PalAction,
        action_uuid=None,
    ) -> tuple[ErrorCodes, bool, list, list]:
        """Reconcile sample state for one ``palaction`` after its PAL triggers
        fire: refresh input samples, materialize output samples, update
        volumes, persist to the sample DB, and write back archive positions
        (legacy steps (1)-(7),(9) -- P3a-PAL slice 3c).

        Step 8 (the HLO data-file write) stays engine-owned: it sits between
        steps 7 and 9 and uses ``file_conn_keys`` mutated by ``active.split()``,
        which this Base-free service never touches. Step 9 itself
        (``active.append_sample``) also stays engine-owned since it needs the
        ``DataSinkPort``/``Active`` handle (Decision 2) -- this method instead
        returns the exact deepcopy snapshot legacy step 4 accumulated into
        ``job.palcam.samples_in``/``samples_out`` (captured at the SAME point
        in the sequence, before step 5's volume mutation, so the recorded
        snapshot reflects pre-dilution volumes exactly like the legacy code)
        for the engine to hand to ``append_sample``.

        Args:
            palaction: Current execution; mutated in place (matches the
                legacy driver's contract).
            action_uuid: Job-context action UUID stamped onto resolved
                samples (Decision 2).

        Returns:
            Tuple ``(error, should_abort, samples_in_for_job,
            samples_out_for_job)``. ``should_abort=True`` mirrors the
            legacy code's early ``return ErrorCodes.critical_error``/
            ``return ErrorCodes.bug`` (an unresolvable dest ref sample) --
            the engine must abort ``_sendcommand_main`` entirely, not just
            this palaction. When ``False``, ``error`` is simply step 7's
            (``_update_archive_helper``) outcome, matching the legacy
            code's non-aborting step-7 failure path.
        """
        # -- (1) -- get most recent information for all samples_in
        # palaction.samples_in should always be non ref samples
        palaction.samples_in = await self.sample_state.get_samples(
            samples=palaction.samples_in
        )
        # update the action_uuid
        for sample in palaction.samples_in:
            sample.action_uuid = [action_uuid]
        # as palaction.samples_in contains both source and dest samples
        # we had them saved separately (this is for the hlo file)

        # palaction.source should also always contain non ref samples
        palaction.source.samples_initial = await self.sample_state.get_samples(
            samples=palaction.source.samples_initial
        )
        # update the action_uuid
        for sample in palaction.source.samples_initial:
            sample.action_uuid = [action_uuid]

        # dest can also contain ref samples, and these are not yet in the db
        for dest_i, dest_sample in enumerate(palaction.dest.samples_initial):
            if dest_sample.global_label is not None:
                dest_tmp = await self.sample_state.get_samples(samples=[dest_sample])
                if dest_tmp:
                    palaction.dest.samples_initial[dest_i] = deepcopy(dest_tmp[0])
                else:
                    LOGGER.error("Sample does not exist in db")
                    return ErrorCodes.critical_error, True, [], []
            else:
                LOGGER.error(
                    "palaction.dest.samples_initial should not contain ref samples"
                )
                return ErrorCodes.bug, True, [], []
        # update the action_uuid
        for sample in palaction.dest.samples_initial:
            sample.action_uuid = [action_uuid]

        # -- (2) -- update sample_out
        # only samples in sample_out should be new ones (ref samples)
        # convert these to real samples by adding them to the db
        # update sample creation time
        for sample_out in palaction.samples_out:
            LOGGER.info(f" converting ref sample {sample_out} to real sample")
            sample_out.sample_creation_timecode = palaction.continue_time

            # if the sample was destroyed during this run set its
            # volume to zero
            # destroyed: destination was waste or injector
            # for newly created samples
            if SampleStatus.destroyed in sample_out.status:
                sample_out.destroy_sample()

            # if sample_out is an assembly we need to update its parts
            if sample_out.sample_type == SampleType.assembly:
                # could also check if it has parts attribute?
                # reset source
                sample_out.source = []
                for part_i, part in enumerate(sample_out.parts):
                    if part.global_label is not None:
                        tmp_part = await self.sample_state.get_samples(samples=[part])
                        for sample in tmp_part:
                            sample.action_uuid = [action_uuid]
                        sample_out.parts[part_i] = deepcopy(tmp_part[0])
                    else:
                        # the assembly contains a ref sample which
                        # first need to be updated and converted
                        part.sample_creation_timecode = palaction.continue_time
                        part.action_uuid = [action_uuid]
                        tmp_part = await self.sample_state.new_samples(samples=[part])
                        sample_out.parts[part_i] = deepcopy(tmp_part[0])
                    # now add the real samples back to the source list
                    sample_out.source.append(part.get_global_label())
                # update the action_uuid
                for sample in sample_out.parts:
                    sample.action_uuid = [action_uuid]

        # update the action_uuid
        for sample in palaction.samples_out:
            sample.action_uuid = [action_uuid]

        # -- (3) -- convert samples_out references to real sample
        #           by adding them to the to db
        palaction.samples_out = await self.sample_state.new_samples(
            samples=palaction.samples_out
        )

        # -- (4) -- snapshot for the engine's job.palcam accumulation.
        # Legacy step 4 appended deepcopies of samples_in/samples_out into
        # job.palcam at EXACTLY this point (before step 5's volume mutation)
        # -- captured here so the engine gets the same pre-dilution values.
        samples_in_for_job = [deepcopy(s) for s in palaction.samples_in]
        samples_out_for_job = [deepcopy(s) for s in palaction.samples_out]

        # -- (5) -- convert pal action samples_in
        # from initial to final
        # update the sample volumes
        # (needed only for input samples, samples_out are always
        # new samples)
        await self._update_sample_volume(palaction)

        # -- (6) --
        # update all samples also in the local sample sqlite db
        await self.sample_state.update_samples(palaction.samples_in)

        for sample_out in palaction.samples_out:
            # if sample_out is an assembly we need to update its parts
            if sample_out.sample_type == SampleType.assembly:
                sample_out.parts = await self.sample_state.get_samples(
                    samples=sample_out.parts
                )
            # update the action_uuid
            sample_out.action_uuid = [action_uuid]
            # save it back to the db
            await self.sample_state.update_samples([sample_out])

        # -- (7) -- update the sample position db
        error = await self._update_archive_helper(palaction, action_uuid=action_uuid)

        return error, False, samples_in_for_job, samples_out_for_job
