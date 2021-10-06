def eval_array(x):
    ret = []
    for y in x:
        nv = eval_val(y)
        ret.append(nv)
    return ret


def eval_val(x):
    if isinstance(x, list):
        nv = eval_array(x)
    elif isinstance(x, dict):
        nv = {k: eval_val(dk) for k, dk in x.items()}
    elif isinstance(x, str):
        if x.replace(".", "", 1).lstrip("-").isdigit():
            if "." in x:
                nv = float(x)
            else:
                nv = int(x)
        else:
            nv = x
    else:
        nv = x
    return nv
