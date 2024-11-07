__all__ = ["helao_dirs"]

import os
import zipfile
import re
from glob import glob

from helao.helpers.print_message import print_message
from helao.core.models.helaodirs import HelaoDirs


def helao_dirs(world_cfg: dict, server_name: str = None) -> HelaoDirs:
    """
    Initializes and verifies the directory structure for the Helao application based on the provided configuration.

    Args:
        world_cfg (dict): Configuration dictionary containing the root directory and other settings.
        server_name (str, optional): Name of the server. If provided, old log files will be compressed.

    Returns:
        HelaoDirs: An instance of the HelaoDirs class containing paths to various directories.

    Raises:
        Exception: If there is an error compressing old log files.
    """
    def check_dir(path):
        if not os.path.isdir(path):
            print_message(
                {},
                "DIR",
                f"Warning: directory '{path}' does not exist. Creating it.",
                warning=True,
            )
            os.makedirs(path)

    if "root" in world_cfg:
        root = world_cfg["root"]
        save_root = os.path.join(root, "RUNS_ACTIVE")
        log_root = os.path.join(root, "LOGS")
        states_root = os.path.join(root, "STATES")
        db_root = os.path.join(root, "DATABASE")
        user_exp = os.path.join(root, "USER_CONFIG", "EXP")
        user_seq = os.path.join(root, "USER_CONFIG", "SEQ")
        ana_root = os.path.join(root, "ANALYSES")
        process_root = os.path.join(root, "PROCESSES")
        print_message(
            {},
            "DIR",
            f"Found root directory in config: {world_cfg['root']}",
        )
        check_dir(root)
        check_dir(save_root)
        check_dir(log_root)
        check_dir(states_root)
        check_dir(db_root)
        check_dir(user_exp)
        check_dir(user_seq)
        check_dir(ana_root)
        check_dir(process_root)

        helaodirs = HelaoDirs(
            root=root,
            save_root=save_root,
            log_root=log_root,
            states_root=states_root,
            db_root=db_root,
            user_exp=user_exp,
            user_seq=user_seq,
            ana_root=ana_root,
            process_root=process_root,
        )

        if server_name is not None:
            # zip and remove old txt logs (start new log for every helao launch)
            old_log_txts = glob(os.path.join(log_root, server_name, "*.txt"))
            nots_counter = 0
            for old_log in old_log_txts:
                print_message({}, "launcher", f"Compressing: {old_log}")
                try:
                    timestamp_found = False
                    timestamp = ""
                    with open(old_log, "r") as f:
                        for line in f:
                            if line.replace("error_[", "[").strip().startswith("["):
                                timestamp_found = True
                                timestamp = re.findall("[0-9]{2}:[0-9]{2}:[0-9]{2}", line)[
                                    0
                                ].replace(":", "")
                                zipname = old_log.replace(".txt", f"{timestamp}.zip")
                                arcname = os.path.basename(old_log).replace(
                                    ".txt", f"{timestamp}.txt"
                                )
                                break
                    if not timestamp_found:
                        while os.path.exists(
                            old_log.replace(".txt", f"__{nots_counter}.zip")
                        ):
                            nots_counter += 1
                        zipname = old_log.replace(".txt", f"__{nots_counter}.zip")
                        arcname = os.path.basename(old_log).replace(
                            ".txt", f"__{nots_counter}.txt"
                        )
                    with zipfile.ZipFile(
                        zipname, "w", compression=zipfile.ZIP_DEFLATED
                    ) as zf:
                        zf.write(old_log, arcname)
                    os.remove(old_log)
                except Exception as e:
                    print_message({}, "launcher", f"Error compressing log: {old_log}, {e}")

    else:
        helaodirs = HelaoDirs(
            root=None,
            save_root=None,
            log_root=None,
            states_root=None,
            db_root=None,
            user_exp=None,
            user_seq=None,
            ana_root=None,
            process_root=None,
        )

    return helaodirs
