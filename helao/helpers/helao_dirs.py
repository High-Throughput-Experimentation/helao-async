__all__ = ["helao_dirs"]

import os
import zipfile
import re
from glob import glob

from helao.helpers.print_message import print_message
from helaocore.models.helaodirs import HelaoDirs


def helao_dirs(world_cfg: dict, server_name: str) -> HelaoDirs:
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

        helaodirs = HelaoDirs(
            root=root,
            save_root=save_root,
            log_root=log_root,
            states_root=states_root,
            db_root=db_root,
            user_exp=user_exp,
            user_seq=user_seq,
        )

        # zip and remove old txt logs (start new log for every helao launch)
        old_log_txts = glob(os.path.join(log_root, server_name, "*.txt"))
        for old_log in old_log_txts:
            try:
                timestamp_found = False
                with open(old_log, "r") as f:
                    while not timestamp_found:
                        line0 = f.readline()
                        if line0.strip().startswith("["):
                            timestamp_found = True
                            timestamp = re.findall("[0-9]{2}:[0-9]{2}:[0-9]{2}", line0)[
                                0
                            ].replace(":", "")
                zipname = old_log.replace(".txt", f"{timestamp}.zip")
                arcname = os.path.basename(old_log).replace(".txt", f"{timestamp}.txt")
                with zipfile.ZipFile(
                    zipname, "w", compression=zipfile.ZIP_DEFLATED
                ) as zf:
                    zf.write(old_log, arcname)
                os.remove(old_log)
            except:
                print_message({}, "launcher", f"Error compressing log: {old_log}")

    else:
        helaodirs = HelaoDirs(
            root=None,
            save_root=None,
            log_root=None,
            states_root=None,
            db_root=None,
            user_exp=None,
            user_seq=None,
        )

    return helaodirs
