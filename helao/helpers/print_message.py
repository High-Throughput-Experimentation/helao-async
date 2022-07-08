__all__ = ["print_message"]

import os
from time import strftime

from colorama import Fore, Back, Style, colorama_text
from termcolor import cprint
from pyfiglet import figlet_format


def print_message(server_cfg, server_name, *args, **kwargs):
    def write_log_file(server_name=None, output_path=None, msg_part1=None, msg_part2=None):
        output_path = os.path.join(output_path, server_name)
        output_file = os.path.join(output_path, f"{server_name}_log_{strftime('%Y%m%d')}.txt")
        if not os.path.exists(output_path):
            os.makedirs(output_path, exist_ok=True)
        with open(output_file, "a+") as f:
            for arg in msg_part2:
                f.write(f"[{msg_type}{msg_part1}: {arg}\n")

    precolor = ""
    msg_type = ""
    if "error" in kwargs:
        precolor = f"{Style.BRIGHT}{Fore.WHITE}{Back.RED}"
        msg_type = "error_"
    elif "warning" in kwargs:
        precolor = f"{Fore.BLACK}{Back.YELLOW}"
        msg_type = "warning_"
    elif "info" in kwargs:
        precolor = f"{Fore.BLACK}{Back.GREEN}"
        msg_type = "info_"
    elif "sample" in kwargs:
        precolor = f"{Fore.BLUE}{Style.BRIGHT}{Back.CYAN}"
        msg_type = "sample_"
    else:
        precolor = f"{Style.RESET_ALL}"

    srv_type = server_cfg.get("group", "")
    cmd_print = server_cfg.get("cmd_print", True)
    style = ""
    if srv_type == "orchestrator":
        style = f"{Style.BRIGHT}{Fore.GREEN}"
    elif srv_type == "action":
        style = f"{Style.BRIGHT}{Fore.YELLOW}"
    elif srv_type == "operator":
        style = f"{Style.BRIGHT}{Fore.CYAN}"
    elif srv_type == "visualizer":
        style = f"{Style.BRIGHT}{Fore.CYAN}"
    else:
        style = ""

    msg_part1 = f"[{strftime('%H:%M:%S')}_{server_name}]:"

    if cmd_print:
        with colorama_text():
            if "error" in kwargs:
                cprint(figlet_format("ERROR", font="starwars"), "yellow", "on_red", attrs=["bold"])

            for arg in args:
                print(f"{precolor}{msg_part1}{Style.RESET_ALL} {style}{arg}{Style.RESET_ALL}")

    output_path = kwargs.get("log_dir", None)
    if output_path is not None:
        write_log_file(server_name=server_name, output_path=output_path, msg_part1=msg_part1, msg_part2=args)
        write_log_file(server_name="_MASTER_", output_path=output_path, msg_part1=msg_part1, msg_part2=args)
