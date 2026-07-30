"""PalTransportPort (P3a-PAL plan §Ports/domain bullet C, slice 4): PAL
joblist submission transport -- local subprocess or SSH/Cygwin remote
dispatch, plus process kill/reap. Lifted out of
``helao/deploy/hte/drivers/robot/pal_driver.py``'s
``_sendcommand_submitjoblist_helper``/``_sendcommand_write_local_rshs_aux_
header``/``kill_PAL``/``kill_PAL_cygwin``/``kill_PAL_local``.

Ships bytes only (Decision 1): the engine still builds the ``(method,
params)`` joblist entries (from the resolved ``_palcmd`` list) and the
aux-log header string; this port just gets them to the PAL program and
reports the outcome. Two cross-concern lines are deliberately NOT part of
this port and stay engine-owned: starting the trigger poller (that's
``PalTriggerPort``'s ``start_polling``) and stamping ``palcam.joblist_time``
(needs the ``DataSinkPort`` handle this port never holds).
"""

from typing import Optional, Protocol, runtime_checkable

from helao.hexagon.domain.models import ErrorCodes

__all__ = ["PalTransportPort"]


@runtime_checkable
class PalTransportPort(Protocol):
    @property
    def host(self) -> Optional[str]:
        """Resolved host: ``"localhost"``, a remote SSH hostname, or ``None``
        if unconfigured (mirrors the driver's own ``sshhost`` attribute,
        which stays a separate plain value on ``PAL`` since ``pal_server.py``
        reads ``app.driver.sshhost`` directly)."""
        ...

    async def ensure_aux_logfile(
        self, aux_output_filepath: str, auxheader: str
    ) -> ErrorCodes:
        """Create/overwrite the PAL auxiliary log file with its column
        header, locally or on the remote host, before the joblist is
        submitted. Returns ``ErrorCodes.ssh_error`` on a remote-host
        failure so the caller can skip ``submit_joblist`` (mirrors the
        legacy method's ``if error is ErrorCodes.none:`` short-circuit
        between its aux-log setup and the actual joblist dispatch)."""
        ...

    async def submit_joblist(self, joblist: list[tuple[str, str]]) -> ErrorCodes:
        """Dispatch the already-assembled ``(method, params)`` joblist
        entries to the PAL program, locally (subprocess) or over SSH/Cygwin
        (tmux)."""
        ...

    async def reap_local_process(self) -> None:
        """Wait for a locally-launched PAL subprocess to exit and release its
        handle, if one is outstanding (no-op otherwise)."""
        ...

    async def kill(self) -> ErrorCodes:
        """Terminate any running PAL process, locally (psutil) or over SSH
        (Cygwin ``taskkill``)."""
        ...
