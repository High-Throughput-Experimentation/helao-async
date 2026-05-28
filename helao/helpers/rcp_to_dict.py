"""Parser for legacy RCP/EXP/ANA hierarchical key-value files."""

__all__ = ["rcp_to_dict"]

import os
import zipfile


def rcp_to_dict(rcppath: str) -> dict:
    """Parse an indented ``key: value`` file into a nested dict.

    Lines use four-space indentation to encode nesting depth and a single
    colon to separate keys from values. When ``rcppath`` points to a zip
    archive, the inner file extension (``.ana``, ``.exp``, or ``.rcp``) is
    derived from the archive's parent directory name.

    Args:
        rcppath: Path to either a plain text file or a zip archive
            containing one such file.

    Returns:
        Nested dictionary mirroring the indentation hierarchy. Repeated keys
        at the same level are collapsed into a list.
    """

    dlist = []

    def _tab_level(astr) -> float:
        """Return the indentation depth of ``astr`` in units of four spaces.

        Args:
            astr: A single line whose leading four-space groups are counted.

        Returns:
            Number of leading four-space blocks as a float.
        """
        return (len(astr) - len(astr.lstrip("    "))) / 4

    def _ttree_to_json(ttree, level=0) -> dict:
        """Recursively fold a flat indented-token list into a nested dict.

        Args:
            ttree: Token entries with ``level``, ``name``, and ``value`` keys.
            level: Current depth being assembled.

        Returns:
            Nested dict for the requested level.
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
        """Set ``adict[key] = val``, promoting to a list on repeat assignment.

        Args:
            adict: Mapping to mutate.
            key: Target key.
            val: Value to insert or append.
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
