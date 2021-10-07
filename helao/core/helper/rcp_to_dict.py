
__all__ = ["rcp_to_dict"]

import os
import zipfile

def rcp_to_dict(rcppath: str):  # read common info/rcp/exp/ana structure into dict
    dlist = []

    def _tab_level(astr):
        """Count number of leading tabs in a string"""
        return (len(astr) - len(astr.lstrip("    "))) / 4

    def _ttree_to_json(ttree, level=0):
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