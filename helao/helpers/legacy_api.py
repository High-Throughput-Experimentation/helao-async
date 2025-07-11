__all__ = ["HTELegacyAPI"]

import os
import zipfile
from re import compile as regexcompile
from typing import Optional

import numpy

from helao.helpers import helao_logging as logging

if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER


class HTELegacyAPI:
    def __init__(self):

        self.PLATEMAPFOLDERS = [
            r"J:\hte_jcap_app_proto\map",
        ]

        self.PLATEFOLDERS = [
            r"J:\hte_jcap_app_proto\plate",
        ]

        self.info_cache = {}
        self.map_cache = {}
        self.infopath_cache = {}
        self.pmpath_pid_cache = {}
        self.els_cache = {}

    @property
    def has_access(self):
        return any([os.path.exists(mp) for mp in self.PLATEMAPFOLDERS]) and any(
            [os.path.exists(pp) for pp in self.PLATEFOLDERS]
        )

    def get_rcp_plateid(self, plateid: int):
        LOGGER.info(f" ... get rcp for plateid: {plateid}")
        return None

    def get_info_plateid(self, plateid: int):
        infod = self.importinfo(plateid)
        # 1. checks that the plate_id (info file) exists
        if infod is not None:

            # 2. gets the elements from the screening print in the info file (see getelements_plateid()) and presents them to user
            elements = self.get_elements_plateid(plateid)
            LOGGER.info(f" ... Elements: {elements}")

            # 3. checks that a print and anneal record exist in the info file
            if "prints" not in infod or "anneals" not in infod:
                LOGGER.warning("Warning: no print or anneal record exists")

            # 4. gets platemap and passes to alignment code
            # pmpath=getplatemappath_plateid(plateid, return_pmidstr=True)

            return self.get_platemap_plateid(plateid)

        else:
            return None

    def check_plateid(self, plateid: int):
        infod = self.importinfo(plateid)
        # 1. checks that the plate_id (info file) exists
        if infod is not None:
            return True
        else:
            return False

    def check_printrecord_plateid(self, plateid: int):
        infod = self.importinfo(plateid)
        if infod is not None:
            if "prints" not in infod:
                return False
            else:
                return True

    def check_annealrecord_plateid(self, plateid: int):
        infod = self.importinfo(plateid)
        if infod is not None:
            if "anneals" not in infod:
                return False
            else:
                return True

    def get_platemap_plateid(self, plateid: int):
        if plateid in self.map_cache.keys():
            return self.map_cache[plateid]
        else:
            pmpath = self.getplatemappath_plateid(plateid)
            if pmpath is None:
                return []
            pmdlist, fid = self.readsingleplatemaptxt(pmpath)
            self.map_cache[plateid] = pmdlist
            return pmdlist

    def get_elements_plateid(
        self,
        plateid,
        multielementink_concentrationinfo_bool=False,
        print_key_or_keyword="screening_print_id",
        exclude_elements_list=[""],
        return_defaults_if_none=False,
    ):  # print_key_or_keyword can be e.g. "print__3" or screening_print_id
        if isinstance(plateid, dict):
            infofiled = plateid
        else:
            infofiled = self.importinfo(plateid)
            if infofiled is None:
                return None
            if plateid in self.els_cache.keys():
                return self.els_cache[plateid]
        requiredkeysthere = lambda infofiled, print_key_or_keyword: (
            ("screening_print_id" in infofiled)
            if print_key_or_keyword == "screening_print_id"
            else (print_key_or_keyword in infofiled["prints"])
        )
        while not (
            "prints" in infofiled and requiredkeysthere(infofiled, "screening_print_id")
        ):
            if "lineage" not in infofiled or "," not in infofiled["lineage"]:
                return None
            parentplateidstr = infofiled["lineage"].split(",")[-2].strip()
            infofiled = self.importinfo(parentplateidstr)
        if print_key_or_keyword == "screening_print_id":
            printdlist = [
                printd
                for printd in infofiled["prints"].values()
                if "id" in printd and printd["id"] == infofiled["screening_print_id"]
            ]
            if len(printdlist) == 0:
                return None
            printd = printdlist[0]
        else:
            printd = infofiled["prints"][print_key_or_keyword]
        if "elements" not in printd:
            return None
        els = [
            x for x in printd["elements"].split(",") if x not in exclude_elements_list
        ]

        if multielementink_concentrationinfo_bool:
            self.els_cache[plateid] = (
                els,
                self.get_multielementink_concentrationinfo(
                    printd, els, return_defaults_if_none=return_defaults_if_none
                ),
            )
        else:
            self.els_cache[plateid] = els
        return self.els_cache[plateid]

    ##########################################################################
    # Helper functions
    ##########################################################################
    def getnumspaces(self, a):
        return len(a) - len(a.lstrip(" "))

    def rcp_to_dict(self, rcppath):  # read standard rcp/exp/ana/info structure to dict
        dlist = []

        def _tab_level(astr):
            """Count number of leading tabs in a string"""
            return (len(astr) - len(astr.lstrip("    "))) / 4

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

        def ttree_to_json(ttree, level=0):
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
                    dict_insert_or_append(result, cn["name"], cn["value"])
                elif nn["level"] > level:
                    rr = ttree_to_json(ttree[i + 1 :], level=nn["level"])
                    dict_insert_or_append(result, cn["name"], rr)
                else:
                    dict_insert_or_append(result, cn["name"], cn["value"])
                    return result
            return result

        def dict_insert_or_append(adict, key, val):
            """Insert a value in dict at key if one does not exist
            Otherwise, convert value to list and append
            """
            if key in adict:
                if type(adict[key]) != list:
                    adict[key] = [adict[key]]
                adict[key].append(val)
            else:
                adict[key] = val

        return ttree_to_json(dlist)

    def getplatemappath_plateid(
        self,
        plateid: int,
        erroruifcn=None,
        infokey="screening_map_id:",
        return_pmidstr=False,
        pmidstr=None,
    ):
        if plateid in self.pmpath_pid_cache.keys():
            p, pmidstr = self.pmpath_pid_cache[plateid]
        else:
            pmfold = self.tryprependpath(self.PLATEMAPFOLDERS, "")
            LOGGER.info(f"PM folder is {pmfold}")
            p = None
            if pmidstr is None:
                pmidstr = ""
                infop = self.getinfopath_plateid(plateid)
                if infop is None:
                    LOGGER.info("getinfopath_plateid returned None")
                    if erroruifcn is not None:
                        p = erroruifcn(
                            "", self.tryprependpath(self.PLATEMAPFOLDERS, "")
                        )
                    return (p, pmidstr) if return_pmidstr else p
                LOGGER.info(f"reading {infop}")
                with open(infop, mode="r") as f:
                    s = f.read(1000)
                if pmfold == "" or (infokey not in s and "prints" not in s):
                    LOGGER.info("PM folder is '' or info has no print.")
                    if erroruifcn is not None:
                        p = erroruifcn(
                            "", self.tryprependpath(self.PLATEMAPFOLDERS, "")
                        )
                    return (p, pmidstr) if return_pmidstr else p
                pmidstr = s.partition(infokey)[2].partition("\n")[0].strip()
                if pmidstr == "" and "prints" in s:
                    infod = self.rcp_to_dict(infop)
                    printdlist = [v for k, v in infod["prints"].items()]
                    printdlist.sort(key=lambda x: int(x["id"]), reverse=True)
                    printd = printdlist[0]
                    pmidstr = printd["map_id"]
            fns = [
                fn
                for fn in os.listdir(pmfold)
                if fn.startswith("0" * (4 - len(pmidstr)) + pmidstr + "-")
                and fn.endswith("-mp.txt")
            ]
            if len(fns) != 1:
                if erroruifcn is not None:
                    p = erroruifcn("", self.tryprependpath(self.PLATEMAPFOLDERS, ""))
            p = os.path.join(pmfold, fns[0])
            self.pmpath_pid_cache[plateid] = (p, pmidstr)
        return (p, pmidstr) if return_pmidstr else p

    def importinfo(self, plateid: int):
        if plateid in self.info_cache.keys():
            return self.info_cache[plateid]
        else:
            fn = str(plateid) + ".info"
            p = self.tryprependpath(
                self.PLATEFOLDERS,
                os.path.join(str(plateid), fn),
                testfile=True,
                testdir=False,
            )
            if not os.path.isfile(p):
                return None
            with open(p, mode="r") as f:
                lines = f.readlines()
            infofiled = self.filedict_lines(lines)
            self.info_cache[plateid] = infofiled
            return infofiled

    def tryprependpath(self, preppendfolderlist, p, testfile=True, testdir=True):
        # if (testfile and os.path.isfile(p)) or (testdir and os.path.isdir(p)):
        if os.path.isfile(p):
            return p
        p = p.strip(chr(47)).strip(chr(92))
        for folder in preppendfolderlist:
            pp = os.path.join(folder, p)
            if (testdir and os.path.isdir(pp)) or (testfile and os.path.isfile(pp)):
                return pp
        return ""

    def getinfopath_plateid(self, plateid: int, erroruifcn=None):
        if plateid in self.infopath_cache.keys():
            return self.infopath_cache[plateid]
        else:
            p = ""
            fld = os.path.join(self.tryprependpath(self.PLATEFOLDERS, ""), str(plateid))
            if os.path.isdir(fld):
                l = [fn for fn in os.listdir(fld) if fn.endswith("info")] + ["None"]
                p = os.path.join(fld, l[0])
            if (not os.path.isfile(p)) and erroruifcn is not None:
                p = erroruifcn("", "")
            if not os.path.isfile(p):
                return None
            self.infopath_cache[plateid] = p
            return p

    def filedict_lines(self, lines):
        lines = [l for l in lines if len(l.strip()) > 0]
        exptuplist = []
        while len(lines) > 0:
            exptuplist += [self.createnestparamtup(lines)]
        return dict([self.createdict_tup(tup) for tup in exptuplist])

    def createnestparamtup(self, lines):
        ln = str(lines.pop(0).rstrip())
        numspaces = self.getnumspaces(ln)
        subl = []
        while len(lines) > 0 and self.getnumspaces(lines[0]) > numspaces:
            tu = self.createnestparamtup(lines)
            subl += [tu]

        return (ln.lstrip(" "), subl)

    def createdict_tup(self, nam_listtup):
        k_vtup = self.partitionlineitem(nam_listtup[0])
        if len(nam_listtup[1]) == 0:
            return k_vtup
        d = dict([self.createdict_tup(v) for v in nam_listtup[1]])
        return (k_vtup[0], d)

    def get_multielementink_concentrationinfo(
        self, printd, els, return_defaults_if_none=False
    ):  # None if nothing to report, (True, str) if error, (False, (cels_set_ordered, conc_el_chan)) with the set of elements and how to caclualte their concentration from the platemap

        searchstr1 = "concentration_elements"
        searchstr2 = "concentration_values"
        if not (searchstr1 in printd and searchstr2 in printd):
            if return_defaults_if_none:
                nels_printchannels = [
                    len(regexcompile("[A-Z][a-z]*").findall(el)) for el in els
                ]
                if max(nels_printchannels) > 1:
                    return (
                        True,
                        "concentration info required when there are multi-ink channels",
                    )
                els_set = set(els)
                if len(els_set) < len(
                    els
                ):  # only known cases of this (same element used in multiple print channels and no concentration info provided) is when Co printed in library and as internal reference, in which case 2 channels never printed together but make code assume each ink with equal concentration regardless of duplicates
                    conc_el_chan = numpy.zeros(
                        (len(els_set), len(els)), dtype="float64"
                    )
                    cels_set_ordered = []
                    for j, cel in enumerate(els):  # assume
                        if cel not in cels_set_ordered:
                            cels_set_ordered += [cel]
                        i = cels_set_ordered.index(cel)
                        conc_el_chan[i, j] = 1
                else:  # this is generic case with no concentration info
                    cels_set_ordered = els
                    conc_el_chan = numpy.identity(len(els), dtype="float64")
                return False, (cels_set_ordered, conc_el_chan)
            else:
                return None
        cels = printd[searchstr1]
        concstr = printd[searchstr2]
        conclist = [float(s) for s in concstr.split(",")]

        cels = [cel.strip() for cel in cels.split(",")]
        cels_set = set(cels)
        if len(cels_set) < len(cels) or True in [
            conclist[0] != cv for cv in conclist
        ]:  # concentrations available where an element is used multiple times. or 1 of the concentrations is different from the rest
            els_printchannels = [regexcompile("[A-Z][a-z]*").findall(el) for el in els]
            els_tuplist = [
                (el, i, j)
                for i, l in enumerate(els_printchannels)
                for j, el in enumerate(l)
            ]
            cels_tuplist = []
            for cel in cels:
                while len(els_tuplist) > 0:
                    tup = els_tuplist.pop(0)
                    if tup[0] == cel:
                        cels_tuplist += [tup]
                        break
            if len(cels_tuplist) != len(cels):
                return (
                    True,
                    "could not find the concentration_elements in order in the elements list",
                )
            cels_set_ordered = []
            for cel, chanind, ind_elwithinchan in cels_tuplist:
                if cel not in cels_set_ordered:
                    cels_set_ordered += [cel]

            conc_el_chan = numpy.zeros(
                (len(cels_set_ordered), cels_tuplist[-1][1] + 1), dtype="float32"
            )  # tthe number of elements in the net composition space by the max ink channel
            for (cel, chanind, ind_elwithinchan), conc in zip(cels_tuplist, conclist):
                conc_el_chan[cels_set_ordered.index(cel), chanind] = conc
            # for a given platemap sample with x being the 8-component vecotr of ink channel intensity, the unnormalized concentration of cels_set_ordered is conc_el_chan*x[:conc_el_chan.shape[0]]
            return False, (cels_set_ordered, conc_el_chan)
        if (
            return_defaults_if_none
        ):  # this handles the case when the length of concentration_elements does not match elements,, which usually hapens when only partial concentration info is available
            return False, (els, numpy.identity(len(els), dtype="float64") * conclist[0])
        return None

    def partitionlineitem(self, ln):
        a, b, c = ln.strip().partition(":")
        return (a.strip(), c.strip())

    def myeval(self, c):
        if c == "None":
            c = None
        elif c == "nan" or c == "NaN":
            c = numpy.nan
        else:
            temp = c.lstrip("0")
            if (temp == "" or temp == ".") and "0" in c:
                c = 0
            else:
                c = eval(temp)
        return c

    def readsingleplatemaptxt(
        self,
        p,
        returnfiducials: Optional[bool] = False,
        erroruifcn=None,
        lines: Optional[list] = None,
    ):

        dlist = []
        fid = []
        if lines is None:
            try:
                f = open(p, mode="r")
            except:
                if erroruifcn is None:
                    return dlist, fid
                p = erroruifcn("bad platemap path")
                if len(p) == 0:
                    return dlist, fid
                f = open(p, mode="r")

            ls = f.readlines()
            f.close()
        else:
            ls = lines

        if returnfiducials:
            s = ls[0].partition("=")[2].partition("mm")[0].strip()
            if (
                "," not in s[s.find("(") : s.find(")")]
            ):  # needed because sometimes x,y in fiducials is comma delim and sometimes not
                LOGGER.warning(
                    "WARNING: commas inserted into fiducials line to adhere to format."
                )
                LOGGER.info(s)
                s = (
                    s.replace(
                        "(   ",
                        "(  ",
                    )
                    .replace(
                        "(  ",
                        "( ",
                    )
                    .replace(
                        "( ",
                        "(",
                    )
                    .replace(
                        "   )",
                        "  )",
                    )
                    .replace(
                        ",  ",
                        ",",
                    )
                    .replace(
                        ", ",
                        ",",
                    )
                    .replace(
                        "  )",
                        " )",
                    )
                    .replace(
                        " )",
                        ")",
                    )
                    .replace(
                        "   ",
                        ",",
                    )
                    .replace(
                        "  ",
                        ",",
                    )
                    .replace(
                        " ",
                        ",",
                    )
                )
                LOGGER.info(s)
            fid = eval("[%s]" % s)
            # fid = numpy.array(fid)

        for count, l in enumerate(ls):
            if not l.startswith("%"):
                break

        keys = ls[count - 1][1:].split(",")
        keys = [(k.partition("(")[0]).strip() for k in keys]

        samplelines = [l for l in ls[count:] if l.count(",") == (len(keys) - 1)]

        for l in samplelines:
            sl = l.split(",")
            d = dict([(k, self.myeval(s.strip())) for k, s in zip(keys, sl)])
            dlist += [d]

        if "sample_no" not in keys:
            dlist = [dict(d, sample_no=d["Sample"]) for d in dlist]

        return dlist, fid
