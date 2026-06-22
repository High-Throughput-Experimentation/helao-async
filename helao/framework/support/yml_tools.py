"""YAML serialization helpers and post-run directory promotion logic.

Wraps :mod:`ruamel.yaml` with HELAO conventions (2/4/2 indent, ``null`` for
None, duplicate keys allowed) and provides the asynchronous :func:`move_dir`
that promotes ``RUNS_ACTIVE`` directories to ``RUNS_FINISHED`` (or
``RUNS_DIAG`` for manual actions) and notifies the DB server.
"""

import os
import asyncio
from glob import glob
from io import StringIO
from pathlib import Path
from typing import Optional, Union

import aiofiles
import aiofiles.os
import aiohttp
import aioshutil
import ruamel.yaml


def yml_dumps(obj, options=None) -> str:
    """Serialize ``obj`` to a YAML string using HELAO formatting conventions.

    The dumper is configured for 2/4/2 indentation, allows duplicate keys,
    and renders ``None`` as the literal ``null``.

    Args:
        obj: Python object to serialize.
        options: Extra keyword arguments forwarded to ``yaml.dump``.

    Returns:
        YAML-formatted string.
    """
    yaml = ruamel.yaml.YAML(typ="rt")
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.allow_duplicate_keys = True

    # show null
    def my_represent_none(self, data):
        """Render ``None`` as the literal scalar ``null``."""
        return self.represent_scalar("tag:yaml.org,2002:null", "null")

    yaml.representer.add_representer(type(None), my_represent_none)

    if options is None:
        options = {}

    string_stream = StringIO()
    yaml.dump(obj, string_stream, **options)
    output_str = string_stream.getvalue()
    string_stream.close()
    return output_str


def yml_load(input: Union[str, Path]):
    """Load YAML from a path, :class:`pathlib.Path`, or raw string.

    Args:
        input: Filesystem path, ``Path`` object, or YAML string.

    Returns:
        Parsed Python object (typically a dict).

    Raises:
        ruamel.yaml.YAMLError: If the YAML is malformed.
    """
    yaml = ruamel.yaml.YAML(typ="rt")
    yaml.version = (1, 2)
    if isinstance(input, Path):
        with input.open("r") as f:
            obj = yaml.load(f)
    elif os.path.exists(input):
        with open(input, "r") as f:
            obj = yaml.load(f)
    else:
        obj = yaml.load(input)
    return obj


async def yml_finisher(yml_path: str, db_config: dict = {}, retry: int = 3) -> bool:
    """POST a finished YAML path to the DB server's ``/finish_yml`` endpoint.

    Args:
        yml_path: Filesystem path to the finalized YAML.
        db_config: Mapping with at least ``host`` and ``port`` for the DB
            server; missing keys cause an immediate False return.
        retry: Maximum number of attempts on non-200 responses.

    Returns:
        True on a 200 response, False on missing config, missing file, or
        repeated failure.
    """
    from helao.framework.support import helao_logging as logging

    LOGGER = (
        logging.LOGGER if logging.LOGGER is not None else logging.make_logger(__file__)
    )

    yp = Path(yml_path)

    if "host" not in db_config or "port" not in db_config:
        return False
    else:
        dbp_port = db_config["port"]
        dbp_host = db_config["host"]

    if not yp.exists():
        LOGGER.info(f"{yml_path} was not found, was it already moved?")
        return False

    ymld = yml_load(yp)
    yml_type = ymld["file_type"]

    req_params = {"yml_path": yml_path}
    req_url = f"http://{dbp_host}:{dbp_port}/finish_yml"
    async with aiohttp.ClientSession() as session:
        for i in range(retry):
            try:
                async with session.post(req_url, params=req_params) as resp:
                    if resp.status == 200:
                        LOGGER.info(f"Finished {yml_type}: {yml_path}.")
                        return True
                    else:
                        LOGGER.info(
                            f"Retry [{i}/{retry}] finish {yml_type} {yml_path}."
                        )
                        await asyncio.sleep(1)
            except asyncio.TimeoutError:
                continue
        LOGGER.info(f"Could not finish {yml_path} after {retry} tries.")
        return False


async def move_dir(hobj, base: Optional[object] = None, retry_delay: int = 5):
    """Promote an Action/Experiment/Sequence's directory out of ``RUNS_ACTIVE``.

    The destination is ``RUNS_DIAG`` for manual actions or ``RUNS_FINISHED``
    otherwise; ``.hlo`` data files for objects with ``sync_data=False`` are
    diverted to ``RUNS_NOSYNC``. Copy and removal are retried up to 60 and 30
    times respectively, sleeping ``retry_delay`` seconds between attempts. On
    success of a non-manual move, :func:`yml_finisher` is invoked.

    Args:
        hobj: An ``Action``, ``Experiment``, or ``Sequence`` instance whose
            on-disk directory should be promoted.
        base: Server object providing ``helaodirs.save_root`` and config.
        retry_delay: Sleep between copy/remove retry rounds, in seconds.

    Returns:
        Empty dict when ``hobj`` is not a supported type; otherwise None.
    """
    from helao.framework.support import helao_logging as logging

    LOGGER = (
        logging.LOGGER if logging.LOGGER is not None else logging.make_logger(__file__)
    )

    obj_type = hobj.__class__.__name__.lower()
    dest_dir = "RUNS_FINISHED"
    save_dir = str(base.helaodirs.save_root)

    is_manual = False

    yml_dir = None

    if hobj.manual_action:
        dest_dir = "RUNS_DIAG"
        is_manual = True
    match obj_type:
        case "action":
            target_subdir = hobj.get_action_dir()
        case "experiment":
            target_subdir = hobj.get_experiment_dir()
        case "sequence":
            target_subdir = hobj.get_sequence_dir()
        case _:
            LOGGER.info(
                f"Invalid object {obj_type} was provided. Can only move Action, Experiment, or Sequence."
            )
            return {}

    yml_dir = os.path.normpath(os.path.join(save_dir, target_subdir))

    new_dir = os.path.join(yml_dir.replace("RUNS_ACTIVE", dest_dir))
    nosync_dir = os.path.join(yml_dir.replace("RUNS_ACTIVE", "RUNS_NOSYNC"))
    await aiofiles.os.makedirs(new_dir, exist_ok=True)
    await aiofiles.os.makedirs(nosync_dir, exist_ok=True)

    copy_success = False
    copy_retries = 0
    if obj_type == "action":
        src_list = glob(os.path.join(yml_dir, "**", "*"), recursive=True)
    else:
        src_list = glob(os.path.join(yml_dir, "*"))
    src_list = [x for x in src_list if os.path.isfile(x)]

    while (not copy_success) and copy_retries <= 60:
        dst_list = [
            p.replace(
                "RUNS_ACTIVE",
                (
                    "RUNS_NOSYNC"
                    if p.endswith(".hlo") and not hobj.sync_data
                    else dest_dir
                ),
            )
            for p in src_list
        ]
        for p in dst_list:
            os.makedirs(os.path.dirname(p), exist_ok=True)

        mvtups = []
        cptups = []
        for src, dst in zip(src_list, dst_list):
            if "RUNS_NOSYNC" in dst:
                mvtups.append((src, dst))
            else:
                cptups.append((src, dst))

        move_results = await asyncio.gather(
            *[aioshutil.move(src, dst) for src, dst in mvtups],
            return_exceptions=True,
        )

        copy_results = await asyncio.gather(
            *[aioshutil.copy(src, dst) for src, dst in cptups],
            return_exceptions=True,
        )

        exists_list = [f for f in dst_list if os.path.exists(f)]
        if len(exists_list) == len(src_list):
            copy_success = True
            LOGGER.info(f"Successfully copied {yml_dir} to FINISHED.")
        else:
            src_list = [f for f in src_list if f not in exists_list]
            LOGGER.info(
                f"Could not copy {len(src_list)} files to FINISHED, retrying after {retry_delay} seconds"
            )
            LOGGER.info(src_list)
            LOGGER.info(move_results)
            LOGGER.info(copy_results)
            copy_retries += 1
        await asyncio.sleep(retry_delay)

    if copy_success:
        rm_success = False
        rm_retries = 0
        rm_list = src_list
        while (not rm_success) and rm_retries <= 30:
            rm_files = [x for x in rm_list if os.path.isfile(x)]
            await asyncio.gather(
                *[aiofiles.os.remove(f) for f in rm_files], return_exceptions=True
            )
            rm_files_done = [f for f in rm_files if not os.path.exists(f)]
            if len(rm_files_done) == len(rm_files):
                if os.path.exists(yml_dir):
                    try:
                        await aioshutil.rmtree(yml_dir)
                    except FileNotFoundError:
                        LOGGER.warning(
                            f"Error removing {yml_dir}, perhaps removed by another operation.",
                            exc_info=False,
                        )
                if not os.path.exists(yml_dir):
                    rm_success = True
                    timestamp = getattr(hobj, f"{obj_type}_timestamp").strftime(
                        "%y%m%d.%H%M%S%f"
                    )
                    yml_path = os.path.join(new_dir, f"{timestamp}-{obj_type[:3]}.yml")
                    if not is_manual:
                        await yml_finisher(
                            yml_path,
                            db_config=base.world_cfg.get("servers", {}).get("DB", {}),
                        )
                    LOGGER.info(f"Successfully removed {yml_dir}")
                if rm_success and obj_type == "action" and is_manual:
                    # remove active sequence and experiment dirs
                    exp_dir = os.path.dirname(yml_dir)
                    if os.path.exists(exp_dir):
                        await aioshutil.rmtree(exp_dir)
                    seq_dir = os.path.dirname(exp_dir)
                    if os.path.exists(seq_dir):
                        await aioshutil.rmtree(seq_dir)
            else:
                rm_list = [f for f in rm_list if f not in rm_files_done]
                LOGGER.info(
                    f"Could not remove directory from ACTIVE, retrying after {retry_delay} seconds"
                )
                LOGGER.info(rm_list)
                rm_retries += 1
            await asyncio.sleep(retry_delay)
