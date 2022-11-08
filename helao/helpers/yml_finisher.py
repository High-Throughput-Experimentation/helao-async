__all__ = ["yml_finisher"]

import os
import asyncio
from typing import Union
from glob import glob
from pathlib import Path

import aiohttp
import aioshutil
import aiofiles
from ruamel.yaml import YAML

from helao.helpers.print_message import print_message
from helao.helpers.premodels import Sequence, Experiment, Action


async def yml_finisher(yml_path: str, base: object = None, retry: int = 3):
    yaml = YAML(typ="safe")
    ymld = yaml.load(Path(yml_path))
    yml_type = ymld["file_type"]

    def print_msg(msg):
        if base is not None:
            base.print_message(msg, info=True)
        else:
            print_message({}, "yml_finisher", msg, info=True)

    if "DB" in base.world_cfg["servers"].keys():
        dbp_host = base.world_cfg["servers"]["DB"]["host"]
        dbp_port = base.world_cfg["servers"]["DB"]["port"]
    else:
        print_msg("DB server not found in config. Cannot finish yml.")
        return False

    req_params = {"yml_path": yml_path}
    req_url = f"http://{dbp_host}:{dbp_port}/finish_yml"
    async with aiohttp.ClientSession() as session:
        for i in range(retry):
            async with session.post(req_url, params=req_params) as resp:
                if resp.status == 200:
                    print_msg(f"Finished {yml_type}: {yml_path}.")
                    return True
                else:
                    print_msg(f"Retry [{i}/{retry}] finish {yml_type} {yml_path}.")
                    await asyncio.sleep(1)
        print_msg(f"Could not finish {yml_path} after {retry} tries.")
        return False


async def move_dir(
    hobj: Union[Sequence, Experiment, Action], base: object = None, retry_delay: int = 5
):
    """Move directory from RUNS_ACTIVE to RUNS_FINISHED."""

    if base is not None:

        def print_msg(msg):
            base.print_message(msg, info=True)

    else:

        def print_msg(msg):
            print_message({}, "yml_finisher", msg, info=True)

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
    await aiofiles.os.makedirs(new_dir, exist_ok=True)

    copy_success = False
    copy_retries = 0
    src_list = glob(os.path.join(yml_dir, "*"))

    while (not copy_success) and copy_retries <= 60:
        dst_list = [p.replace("RUNS_ACTIVE", dest_dir) for p in src_list]
        await asyncio.gather(
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
                await asyncio.gather(
                    aiofiles.os.rmdir(yml_dir), return_exceptions=True
                )
                if not os.path.exists(yml_dir):
                    rm_success = True
                    timestamp = getattr(hobj, f"{obj_type}_timestamp").strftime(
                        "%Y%m%d.%H%M%S%f"
                    )
                    yml_path = os.path.join(new_dir, f"{timestamp}-{obj_type[:3]}.yml")
                    if not is_manual:
                        await yml_finisher(yml_path, base=base)
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
