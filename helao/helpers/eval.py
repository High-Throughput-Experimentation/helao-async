__all__ = ["eval_array", "eval_val"]


def eval_array(x):
    """
    Evaluates each element in the input array using the eval_val function and returns a new array with the evaluated values.

    Args:
        x (list): A list of elements to be evaluated.

    Returns:
        list: A list containing the evaluated values of the input elements.
    """
    ret = []
    for y in x:
        nv = eval_val(y)
        ret.append(nv)
    return ret


def eval_val(x):
    """
    Evaluates and converts a given value based on its type.

    Parameters:
    x (any): The value to be evaluated. It can be of type list, dict, str, or any other type.

    Returns:
    any: The evaluated value. The return type depends on the input:
        - If the input is a list, it calls eval_array on the list.
        - If the input is a dict, it recursively evaluates each value in the dict.
        - If the input is a str, it attempts to convert it to an int, float, boolean, or NaN if applicable.
        - Otherwise, it returns the input value as is.
    """
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
        elif x == "NaN":
            nv = float(x)
        elif x.lower() == "true":
            nv = True
        elif x.lower() == "false":
            nv = False
        else:
            nv = x
    else:
        nv = x
    return nv
