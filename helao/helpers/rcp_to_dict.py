__all__ = ["rcp_to_dict"]

import os
import zipfile


def rcp_to_dict(rcppath: str):
    """
    Convert a structured text file or a file within a zip archive into a nested dictionary.

    The function reads a file with a specific structure where each line contains a key-value pair
    separated by a colon and indented with tabs to indicate hierarchy levels. It supports reading
    from both plain text files and zip archives containing the file. The resulting dictionary
    reflects the hierarchical structure of the input file.

    Args:
        rcppath (str): The path to the input file. It can be a plain text file or a zip archive
                       containing the file.

    Returns:
        dict: A nested dictionary representing the hierarchical structure of the input file.
    """

    dlist = []

    def _tab_level(astr):
        """
        Calculate the tab level of a given string.

        Args:
            astr (str): The input string to evaluate.

        Returns:
            float: The tab level, calculated as the number of leading spaces divided by 4.
        """
        return (len(astr) - len(astr.lstrip("    "))) / 4

    def _ttree_to_json(ttree, level=0):
        """
        Converts a tree structure (list of dictionaries) into a nested JSON-like dictionary.

        Args:
            ttree (list): A list of dictionaries representing the tree structure. Each dictionary
                          should have at least 'level', 'name', and 'value' keys.
            level (int, optional): The current level of the tree being processed. Defaults to 0.

        Returns:
            dict: A nested dictionary representing the JSON structure of the input tree.
        """
        result = {}
        for i in range(0, len(ttree)):
            cn = ttree[i]
            try:
                nn = ttree[i + 1]
            except:
                nn = {"level": -1}

            # Edge cases
            if cn["level"] > level:
                continue
            if cn["level"] < level:
                return result
            # Recursion
            if nn["level"] == level:
                _dict_insert_or_append(result, cn["name"], cn["value"])
            elif nn["level"] > level:
                rr = _ttree_to_json(ttree[i + 1 :], level=nn["level"])
                _dict_insert_or_append(result, cn["name"], rr)
            else:
                _dict_insert_or_append(result, cn["name"], cn["value"])
                return result
        return result

    def _dict_insert_or_append(adict, key, val):
        """Insert a value in dict at key if one does not exist
        Otherwise, convert value to list and append
        """
        if key in adict:
            if type(adict[key]) != list:
                adict[key] = [adict[key]]
            adict[key].append(val)
        else:
            adict[key] = val

    if rcppath.endswith(".zip"):
        if "analysis" in os.path.dirname(rcppath):
            ext = ".ana"
        elif "experiment" in os.path.dirname(rcppath):
            ext = ".exp"
        else:
            ext = ".rcp"
        rcpfn = os.path.basename(rcppath).split(".copied")[0] + ext
        archive = zipfile.ZipFile(rcppath, "r")
        with archive.open(rcpfn, "r") as f:
            for l in f:
                k, v = l.decode("ascii").split(":", 1)
                lvl = _tab_level(l.decode("ascii"))
                dlist.append({"name": k.strip(), "value": v.strip(), "level": lvl})
    else:
        with open(rcppath, "r") as f:
            for l in f:
                k, v = l.split(":", 1)
                lvl = _tab_level(l)
                dlist.append({"name": k.strip(), "value": v.strip(), "level": lvl})

    return _ttree_to_json(dlist)
