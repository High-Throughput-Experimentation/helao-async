
__all__ = ["print_message"]

from time import strftime

from colorama import Back, Fore, Style


def print_message(server_cfg, server_name, *args, **kwargs):
    precolor = ""
    if "error" in kwargs:
        precolor = f"{Style.BRIGHT}{Fore.RED}"
    if "warning" in kwargs:
        precolor = f"{Style.BRIGHT}{Fore.YELLOW}"
    if "info" in kwargs:
        precolor = f"{Style.BRIGHT}{Fore.GREEN}"

    srv_type = server_cfg.get("group", "")
    style = ""
    if srv_type == "orchestrator":
        style = f"{Style.BRIGHT}{Fore.GREEN}"
    elif srv_type == "process":
        style = f"{Style.BRIGHT}{Fore.YELLOW}"
    elif srv_type == "operator":
        style = f"{Style.BRIGHT}{Fore.CYAN}"
    elif srv_type == "visualizer":
        style = f"{Style.BRIGHT}{Fore.CYAN}"
    else:
        style = ""
    # style = server_cfg.get("msg_color",style)

    for arg in args:
        print(
            f"{precolor}[{strftime('%H:%M:%S')}_{server_name}]:{Style.RESET_ALL} {style}{arg}{Style.RESET_ALL}"
        )
