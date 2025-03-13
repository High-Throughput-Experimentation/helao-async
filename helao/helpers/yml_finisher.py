__all__ = ["yml_finisher"]

import os
import asyncio
from typing import Union, Optional
from glob import glob
from pathlib import Path

import aiohttp
import aioshutil
import aiofiles

from helao.helpers.yml_tools import yml_load
from helao.helpers.print_message import print_message
from helao.helpers.premodels import Sequence, Experiment, Action

from helao.helpers import logging

if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER

async def yml_finisher(yml_path: str, db_config: dict = {}, retry: int = 3):
    """
    Asynchronously attempts to finish processing a YAML file by sending a request to a specified database server.

    Args:
        yml_path (str): The file path to the YAML file.
        db_config (dict, optional): A dictionary containing the database configuration with keys "host" and "port". Defaults to an empty dictionary.
        retry (int, optional): The number of retry attempts if the request fails. Defaults to 3.

    Returns:
        bool: True if the YAML file was successfully processed, False otherwise.
    """
    yp = Path(yml_path)

    def print_msg(msg):
        # if base is not None:
        #     base.print_message(msg, info=True)
        # else:
        print_message(LOGGER, "yml_finisher", msg, info=True)

    if "host" not in db_config or "port" not in db_config:
        # print_msg(f"DB server not defined in config, {yml_path} will not sync.")
        return False
    else:
        dbp_port = db_config["port"]
        dbp_host = db_config["host"]

    if not yp.exists():
        print_msg(f"{yml_path} was not found, was it already moved?")
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
                        print_msg(f"Finished {yml_type}: {yml_path}.")
                        return True
                    else:
                        print_msg(f"Retry [{i}/{retry}] finish {yml_type} {yml_path}.")
                        await asyncio.sleep(1)
            except asyncio.TimeoutError:
                continue
        print_msg(f"Could not finish {yml_path} after {retry} tries.")
        return False


async def move_dir(
    hobj: Union[Sequence, Experiment, Action], base: Optional[object] = None, retry_delay: int = 5
):
    """
    Move directory from RUNS_ACTIVE to RUNS_FINISHED or RUNS_DIAG based on the type and attributes of the provided object.

    Parameters:
    hobj (Union[Sequence, Experiment, Action]): The object whose directory is to be moved. Can be of type Sequence, Experiment, or Action.
    base (object, optional): The base object that provides the print_message method. Defaults to None.
    retry_delay (int, optional): The delay in seconds between retries for copying and removing files. Defaults to 5.

    Returns:
    dict: An empty dictionary if an invalid object type is provided.

    Raises:
    Exception: If there are issues with directory creation, file copying, or file removal.
    """

    if base is not None:

        def print_msg(msg):
            base.print_message(msg, info=True)

    else:

        def print_msg(msg):
            print_message(LOGGER, "yml_finisher", msg, info=True)

    obj_type = hobj.__class__.__name__.lower()
    dest_dir = "RUNS_FINISHED"
    save_dir = base.helaodirs.save_root.__str__()

    is_manual = False

    if obj_type == "action":
        yml_dir = os.path.join(save_dir, hobj.get_action_dir())
        if hobj.manual_action:
            dest_dir = "RUNS_DIAG"
            is_manual = True
    elif obj_type == "experiment":
        yml_dir = os.path.join(save_dir, hobj.get_experiment_dir())
        if hobj.experiment_name == "MANUAL":
            dest_dir = "RUNS_DIAG"
            is_manual = True
    elif obj_type == "sequence":
        yml_dir = os.path.join(save_dir, hobj.get_sequence_dir())
        if hobj.sequence_name == "manual_seq":
            dest_dir = "RUNS_DIAG"
            is_manual = True
    else:
        yml_dir = None
        print_msg(
            f"Invalid object {obj_type} was provided. Can only move Action, Experiment, or Sequence."
        )
        return {}

    new_dir = os.path.join(yml_dir.replace("RUNS_ACTIVE", dest_dir))
    nosync_dir = os.path.join(yml_dir.replace("RUNS_ACTIVE", "RUNS_NOSYNC"))
    await aiofiles.os.makedirs(new_dir, exist_ok=True)
    await aiofiles.os.makedirs(nosync_dir, exist_ok=True)

    copy_success = False
    copy_retries = 0
    src_list = glob(os.path.join(yml_dir, "**", "*"), recursive=True)
    src_list = [x for x in src_list if os.path.isfile(x)]

    while (not copy_success) and copy_retries <= 60:
        dst_list = [p.replace("RUNS_ACTIVE", "RUNS_NOSYNC" if p.endswith(".hlo") and not hobj.sync_data else dest_dir) for p in src_list]
        for p in dst_list:
            os.makedirs(os.path.dirname(p), exist_ok=True)
        copy_results = await asyncio.gather(
            *[aioshutil.copy(src, dst) for src, dst in zip(src_list, dst_list)],
            return_exceptions=True,
        )
        exists_list = [f for f in dst_list if os.path.exists(f)]
        if len(exists_list) == len(src_list):
            copy_success = True
        else:
            src_list = [f for f in src_list if f not in exists_list]
            print_msg(
                f"Could not copy {len(src_list)} files to FINISHED, retrying after {retry_delay} seconds"
            )
            print("\n".join(src_list))
            print(copy_results)
            copy_retries += 1
        await asyncio.sleep(retry_delay)

    if copy_success:
        rm_success = False
        rm_retries = 0
        rm_list = glob(os.path.join(yml_dir, "*"))
        while (not rm_success) and rm_retries <= 30:
            rm_files = [x for x in rm_list if os.path.isfile(x)]
            await asyncio.gather(
                *[aiofiles.os.remove(f) for f in rm_files], return_exceptions=True
            )
            rm_files_done = [f for f in rm_files if not os.path.exists(f)]
            if len(rm_files_done) == len(rm_files):
                await asyncio.gather(aiofiles.os.rmdir(yml_dir), return_exceptions=True)
                if not os.path.exists(yml_dir):
                    rm_success = True
                    timestamp = getattr(hobj, f"{obj_type}_timestamp").strftime(
                        "%Y%m%d.%H%M%S%f"
                    )
                    yml_path = os.path.join(new_dir, f"{timestamp}-{obj_type[:3]}.yml")
                    if not is_manual:
                        await yml_finisher(
                            yml_path,
                            db_config=base.world_cfg.get("servers", {}).get("DB", {}),
                        )
                if rm_success and obj_type == "action" and is_manual:
                    # remove active sequence and experiment dirs
                    exp_dir = os.path.dirname(yml_dir)
                    await asyncio.gather(aiofiles.os.rmdir(exp_dir))
                    seq_dir = os.path.dirname(exp_dir)
                    await asyncio.gather(aiofiles.os.rmdir(seq_dir))
            else:
                rm_list = [f for f in rm_list if f not in rm_files_done]
                print_msg(
                    f"Could not remove directory from ACTIVE, retrying after {retry_delay} seconds"
                )
                print("\n".join(rm_list))
                rm_retries += 1
            await asyncio.sleep(retry_delay)
