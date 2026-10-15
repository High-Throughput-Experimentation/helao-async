"""LegacyPalTransport adapter (P3a-PAL slice 4): reproduces
``pal_driver.py``'s ``_sendcommand_submitjoblist_helper``/
``_sendcommand_write_local_rshs_aux_header``/``kill_PAL``/
``kill_PAL_cygwin``/``kill_PAL_local`` verbatim (same commands, same
quoting, same log wording).

``paramiko`` is imported LAZILY inside the SSH-path methods (not at module
top), per the plan's §11.1 import-isolation rule -- mirrors how
``nidaqmx`` is already lazy in the trigger poller. This is what lets this
module (and any composition root that constructs it) import cleanly on
Linux without paramiko installed; construction itself never opens a
socket, only ``ensure_aux_logfile``/``submit_joblist``/``kill`` do (when
``host`` is a remote SSH hostname).

Boundary note: constructed with plain values (host/user/key), no
deployment-tree import at module top -- mirrors
``sample_state.py``/``calibration_store.py``.
"""

import asyncio
import logging
import os
import subprocess
import time
from typing import Optional

import aiofiles
import psutil

from helao.core.error import ErrorCodes

_SSH_ATTEMPTS = 10
_SSH_TIMEOUT = 5  # seconds per connect/banner/auth phase

LOGGER = logging.getLogger(__name__)

__all__ = ["LegacyPalTransport"]


class LegacyPalTransport:
    def __init__(self, host: Optional[str], user: str = "", key: str = ""):
        self._host = host
        self._user = user
        self._key = key
        self._pal_pid: Optional[subprocess.Popen] = None

    @property
    def host(self) -> Optional[str]:
        return self._host

    def _ssh_connect(self):
        """Open a paramiko SSH client to ``self._host``, retrying every 1s
        up to ``_SSH_ATTEMPTS`` times; returns None when exhausted. Blocking:
        call via ``_connect`` from async code. Lazy import: only reached
        when ``host`` is a remote SSH hostname.
        """
        import paramiko

        for _ in range(_SSH_ATTEMPTS):
            try:
                k = paramiko.RSAKey.from_private_key_file(self._key)
                mysshclient = paramiko.SSHClient()
                mysshclient.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                # bound each attempt so 10 retries cannot stall for minutes
                mysshclient.connect(
                    hostname=self._host,
                    username=self._user,
                    pkey=k,
                    timeout=_SSH_TIMEOUT,
                    banner_timeout=_SSH_TIMEOUT,
                    auth_timeout=_SSH_TIMEOUT,
                )
                return mysshclient
            except Exception:
                LOGGER.error(
                    "SSH connection error. Retrying in 1 seconds.", exc_info=True
                )
                time.sleep(1)
        return None

    async def _connect(self):
        """`_ssh_connect` off the event loop (its retry sleep blocks)."""
        return await asyncio.to_thread(self._ssh_connect)

    async def ensure_aux_logfile(
        self, aux_output_filepath: str, auxheader: str
    ) -> ErrorCodes:
        error = ErrorCodes.none
        if self._host == "localhost":
            FIFO_rshs_dir, _rshs_logfile = os.path.split(aux_output_filepath)
            LOGGER.info(f"RSHS saving to: {FIFO_rshs_dir}")
            if not os.path.exists(FIFO_rshs_dir):
                os.makedirs(FIFO_rshs_dir, exist_ok=True)
            async with aiofiles.open(
                aux_output_filepath, mode="w+", encoding="utf-8"
            ) as f:
                await f.write(auxheader)
        elif self._host is not None:
            mysshclient = await self._connect()
            if mysshclient is None:
                return ErrorCodes.ssh_error
            try:
                FIFO_rshs_dir, rshs_logfile = os.path.split(aux_output_filepath)
                FIFO_rshs_dir = FIFO_rshs_dir.replace("C:\\", "")
                FIFO_rshs_dir = FIFO_rshs_dir.replace("\\", "/")
                LOGGER.info(f"RSHS saving to: /cygdrive/c/{FIFO_rshs_dir}")

                rshs_path = "/cygdrive/c"
                for path in FIFO_rshs_dir.split("/"):
                    rshs_path += "/" + path
                    if path != "":
                        mysshclient.exec_command(f"mkdir {rshs_path}")
                if not rshs_path.endswith("/"):
                    rshs_path += "/"
                LOGGER.info(f"final RSHS path: {rshs_path}")

                rshs_logfilefull = rshs_path + rshs_logfile
                mysshclient.exec_command(f"touch {rshs_logfilefull}")
                mysshclient.exec_command(f"echo -e '{auxheader}' > {rshs_logfilefull}")
                LOGGER.info(f"final RSHS logfile: {rshs_logfilefull}")
            except Exception:
                LOGGER.error(
                    "SSH connection error 1. Could not send commands.", exc_info=True
                )
                error = ErrorCodes.ssh_error
            finally:
                mysshclient.close()
        return error

    async def submit_joblist(self, joblist: list[tuple[str, str]]) -> ErrorCodes:
        error = ErrorCodes.none
        if self._host == "localhost":
            tmpjob = " ".join(
                f'/loadmethod "{method}" "{params}"' for method, params in joblist
            )
            cmd_to_execute = f"PAL {tmpjob} /start /quit"
            LOGGER.info(f"PAL command: '{cmd_to_execute}'")
            try:
                self._pal_pid = subprocess.Popen(cmd_to_execute, shell=True)
                LOGGER.info(f"PAL command send: {self._pal_pid}")
            except Exception:
                LOGGER.error("CMD error. Could not send commands.")
                error = ErrorCodes.cmd_error
        elif self._host is not None:
            mysshclient = await self._connect()
            if mysshclient is None:
                return ErrorCodes.ssh_error
            tmpjob = " ".join(
                f"/loadmethod '{method}' '{params}'" for method, params in joblist
            )
            cmd_to_execute = f"tmux new-window PAL {tmpjob} /start /quit"
            LOGGER.info(f"PAL command: '{cmd_to_execute}'")
            try:
                if error is ErrorCodes.none:
                    mysshclient.exec_command(cmd_to_execute)
                    mysshclient.close()
            except Exception:
                LOGGER.error(
                    "SSH connection error. Could not send commands.", exc_info=True
                )
                error = ErrorCodes.ssh_error
        return error

    async def reap_local_process(self) -> None:
        """No-op unless a local subprocess is outstanding (mirrors the
        legacy `if self.PAL_pid is not None:` guard at both of its call
        sites)."""
        if self._pal_pid is not None:
            LOGGER.info("waiting for PAL pid to finish")
            self._pal_pid.communicate()
            self._pal_pid = None

    async def kill(self) -> ErrorCodes:
        LOGGER.info("killing PAL")
        error_code = ErrorCodes.none
        if self._host == "localhost":
            error_code = await self._kill_local()
        elif self._host is not None:
            error_code = await self._kill_cygwin()
        if error_code is not ErrorCodes.none:
            LOGGER.error("Could not close PAL")
        return error_code

    async def _kill_cygwin(self) -> ErrorCodes:
        mysshclient = await self._connect()
        if mysshclient is None:
            return ErrorCodes.ssh_error
        try:
            sshcmd = "tmux new-window taskkill /F /FI 'WINDOWTITLE eq PAL*'"
            mysshclient.exec_command(sshcmd)
            mysshclient.close()
        except Exception:
            LOGGER.error(
                "SSH connection error. Could not send commands.", exc_info=True
            )
            return ErrorCodes.ssh_error
        return ErrorCodes.none

    async def _kill_local(self) -> ErrorCodes:
        pyPids = {
            p.pid: p
            for p in psutil.process_iter(["name"])
            if p.info["name"].startswith("PAL")
        }
        for pid in pyPids:
            LOGGER.info(f"killing PAL on PID: {pid}")
            p = psutil.Process(pid)
            for _ in range(3):
                p.terminate()
                time.sleep(0.5)
                if not psutil.pid_exists(p.pid):
                    LOGGER.info("Successfully terminated PAL.")
                    break
            if psutil.pid_exists(p.pid):
                LOGGER.error("Failed to terminate server PAL after 3 retries.")
                return ErrorCodes.critical_error
        return ErrorCodes.none
