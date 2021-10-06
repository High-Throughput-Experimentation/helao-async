import pyaml


def dict_to_prc(d: dict, level: int = 0):
    # lines = []
    # for k, v in d.items():
    #     if isinstance(v, dict):
    #         lines.append(f"{'    '*level}{k}:")
    #         lines.append(dict_to_prc(v, level + 1))
    #     else:
    #         lines.append(f"{'    '*level}{k}: {str(v).strip()}")
    # return "\n".join(lines)
    return pyaml.dump(d, sort_dicts=False, indent=level * 4)
