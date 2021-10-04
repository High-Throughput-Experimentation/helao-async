import os
import aiofiles
import json
import zipfile
from re import compile as regexcompile
import numpy
import asyncio
from pydantic import BaseModel
from typing import List
from datetime import datetime
from typing import Optional, Union, List
from socket import gethostname

import sqlite3

from helao.core.model import liquid_sample
from helao.core.server import Base
from helao.core.model import liquid_sample, gas_sample, solid_sample, assembly_sample, sample_list

class HTE_legacy_API:
    def __init__(self, Serv_class):
        self.base = Serv_class

        self.PLATEMAPFOLDERS = [
            r"\\htejcap.caltech.edu\share\data\hte_jcap_app_proto\map",
            r"J:\hte_jcap_app_proto\map",
            r"\\htejcap.caltech.edu\share\home\users\hte\platemaps",
            r"ERT",
            r"K:\users\hte\platemaps",
        ]

        self.PLATEFOLDERS = [
            r"\\htejcap.caltech.edu\share\data\hte_jcap_app_proto\plate",
            r"J:\hte_jcap_app_proto\plate",
        ]


    def get_rcp_plateid(self, plateid: int):
        self.base.print_message(f" ... get rcp for plateid: {plateid}")
        return None

    def get_info_plateid(self, plateid: int):
        infod = self.importinfo(str(plateid))
        # 1. checks that the plate_id (info file) exists
        if infod is not None:
            # self.base.print_message(infod)

            # 2. gets the elements from the screening print in the info file (see getelements_plateid()) and presents them to user
            elements = self.get_elements_plateid(plateid)
            self.base.print_message(f" ... Elements: {elements}")

            # 3. checks that a print and anneal record exist in the info file
            if not "prints" or not "anneals" in infod.keys():
                self.base.print_message("Warning: no print or anneal record exists", warning = True)

            # 4. gets platemap and passes to alignment code
            # pmpath=getplatemappath_plateid(plateid, return_pmidstr=True)

            return self.get_platemap_plateid(plateid)

        else:
            return None

    def check_plateid(self, plateid: int):
        infod = self.importinfo(str(plateid))
        # 1. checks that the plate_id (info file) exists
        if infod is not None:
            return True
        else:
            return False

    def check_printrecord_plateid(self, plateid: int):
        infod = self.importinfo(str(plateid))
        if infod is not None:
            if not "prints" in infod.keys():
                return False
            else:
                return True

    def check_annealrecord_plateid(self, plateid: int):
        infod = self.importinfo(str(plateid))
        if infod is not None:
            if not "anneals" in infod.keys():
                return False
            else:
                return True

    def get_platemap_plateid(self, plateid: int):
        pmpath = self.getplatemappath_plateid(plateid)
        if pmpath is None:
            return json.dumps({})
        pmdlist = self.readsingleplatemaptxt(pmpath)
        return json.dumps(pmdlist)


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
        requiredkeysthere = (
            lambda infofiled, print_key_or_keyword=print_key_or_keyword: (
                "screening_print_id" in infofiled.keys()
            )
            if print_key_or_keyword == "screening_print_id"
            else (print_key_or_keyword in infofiled["prints"].keys())
        )
        while not ("prints" in infofiled.keys() and requiredkeysthere(infofiled)):
            if not "lineage" in infofiled.keys() or not "," in infofiled["lineage"]:
                return None
            parentplateidstr = infofiled["lineage"].split(",")[-2].strip()
            infofiled = self.importinfo(parentplateidstr)
        if print_key_or_keyword == "screening_print_id":
            printdlist = [
                printd
                for printd in infofiled["prints"].values()
                if "id" in printd.keys()
                and printd["id"] == infofiled["screening_print_id"]
            ]
            if len(printdlist) == 0:
                return None
            printd = printdlist[0]
        else:
            printd = infofiled["prints"][print_key_or_keyword]
        if not "elements" in printd.keys():
            return None
        els = [
            x for x in printd["elements"].split(",") if x not in exclude_elements_list
        ]

        if multielementink_concentrationinfo_bool:
            return (
                els,
                self.get_multielementink_concentrationinfo(
                    printd, els, return_defaults_if_none=return_defaults_if_none
                ),
            )

        return els

    ##########################################################################
    # Helper functions
    ##########################################################################
    getnumspaces = lambda self, a: len(a) - len(a.lstrip(" "))

    def rcp_to_dict(self, rcppath):  # read standard rcp/exp/ana/info structure to dict
        dlist = []

        def tab_level(astr):
            """Count number of leading tabs in a string
            """
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
                    lvl = tab_level(l.decode("ascii"))
                    dlist.append({"name": k.strip(), "value": v.strip(), "level": lvl})
        else:
            with open(rcppath, "r") as f:
                for l in f:
                    k, v = l.split(":", 1)
                    lvl = tab_level(l)
                    dlist.append({"name": k.strip(), "value": v.strip(), "level": lvl})

    def getplatemappath_plateid(
        self,
        plateid: int,
        erroruifcn=None,
        infokey="screening_map_id:",
        return_pmidstr=False,
        pmidstr=None,
    ):
        pmfold = self.tryprependpath(self.PLATEMAPFOLDERS, "")
        p = None
        if pmidstr is None:
            pmidstr = ""
            infop = self.getinfopath_plateid(plateid)
            if infop is None:
                if not erroruifcn is None:
                    p = erroruifcn("", self.tryprependpath(self.PLATEMAPFOLDERS, ""))
                return (p, pmidstr) if return_pmidstr else p
            with open(infop, mode="r") as f:
                s = f.read(1000)

            if pmfold == "" or (not infokey in s and not "prints" in s):
                if not erroruifcn is None:
                    p = erroruifcn("", self.tryprependpath(self.PLATEMAPFOLDERS, ""))
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
            if not erroruifcn is None:
                p = erroruifcn("", self.tryprependpath(self.PLATEMAPFOLDERS, ""))
            return (p, pmidstr) if return_pmidstr else p
        p = os.path.join(pmfold, fns[0])
        return (p, pmidstr) if return_pmidstr else p

    def importinfo(self, plateid: int):
        fn = plateid + ".info"
        p = self.tryprependpath(
            self.PLATEFOLDERS,
            os.path.join(plateid, fn),
            testfile=True,
            testdir=False,
        )
        if not os.path.isfile(p):
            return None
        with open(p, mode="r") as f:
            lines = f.readlines()
        infofiled = self.filedict_lines(lines)
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
        p = ""
        fld = os.path.join(self.tryprependpath(self.PLATEFOLDERS, ""), plateid)
        if os.path.isdir(fld):
            l = [fn for fn in os.listdir(fld) if fn.endswith("info")] + ["None"]
            p = os.path.join(fld, l[0])
        if (not os.path.isfile(p)) and not erroruifcn is None:
            p = erroruifcn("", "")
        if not os.path.isfile(p):
            return None
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
        if not (searchstr1 in printd.keys() and searchstr2 in printd.keys()):
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
                        if not cel in cels_set_ordered:
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
                if not cel in cels_set_ordered:
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
        self, p, returnfiducials=False, erroruifcn=None, lines=None
    ):
        if lines is None:
            try:
                f = open(p, mode="r")
            except:
                if erroruifcn is None:
                    return []
                p = erroruifcn("bad platemap path")
                if len(p) == 0:
                    return []
                f = open(p, mode="r")

            ls = f.readlines()
            f.close()
        else:
            ls = lines
        if returnfiducials:
            s = ls[0].partition("=")[2].partition("mm")[0].strip()
            if (
                not "," in s[s.find("(") : s.find(")")]
            ):  # needed because sometimes x,y in fiducials is comma delim and sometimes not
                self.base.print_message(
                    "WARNING: commas inserted into fiducials line to adhere to format.",
                    warning = True
                )
                self.base.print_message(s)
                s = (
                    s.replace("(   ", "(  ",)
                    .replace("(  ", "( ",)
                    .replace("( ", "(",)
                    .replace("   )", "  )",)
                    .replace(",  ", ",",)
                    .replace(", ", ",",)
                    .replace("  )", " )",)
                    .replace(" )", ")",)
                    .replace("   ", ",",)
                    .replace("  ", ",",)
                    .replace(" ", ",",)
                )
                self.base.print_message(s)
            fid = eval("[%s]" % s)
            fid = numpy.array(fid)
        for count, l in enumerate(ls):
            if not l.startswith("%"):
                break
        keys = ls[count - 1][1:].split(",")
        keys = [(k.partition("(")[0]).strip() for k in keys]
        dlist = []
        samplelines = [l for l in ls[count:] if l.count(",") == (len(keys) - 1)]
        for l in samplelines:
            sl = l.split(",")
            d = dict([(k, self.myeval(s.strip())) for k, s in zip(keys, sl)])
            dlist += [d]
        if not "sample_no" in keys:
            dlist = [dict(d, sample_no=d["Sample"]) for d in dlist]
        if returnfiducials:
            return dlist, fid
        return dlist
    

class liquid_sample_API:
    def __init__(self, Serv_class, DBpath):
        self.DBfile = "local_liquid.db"
        self.DBfilepath = DBpath
        self.base = Serv_class
        self.DB = os.path.join(self.DBfilepath, self.DBfile)
        self.con = None
        self.cur = None
        self.open_DB()
        
        # check if table exists
        listOfTables = self.cur.execute(
          """SELECT name FROM sqlite_master WHERE type='table'
          AND name='liquid_sample'; """).fetchall()
         
        if listOfTables == []:
            self.base.print_message(' ... Liquid_sample table not found, creating it.', error = True)
            self.create_init_db()
        else:
            self.base.print_message(' ... Liquid_sample table found!')

        self.close_DB()
        
        self.count_liquid_sample_nowait()        
        # self.new_liquid_sample_nowait(liquid_sample())


    def create_init_db(self):
        # create tables
        create_initial_sqllitedb(dbcur=self.cur)
        self.base.print_message('Liquid_sample table created', info = True)
        # commit changes
        self.con.commit()


    def open_DB(self):
        self.con = sqlite3.connect(self.DB)
        self.cur = self.con.cursor()


    def close_DB(self):
        if self.con is not None:
            # commit any changes
            self.con.commit()
            self.con.close()
            self.con = None
            self.cur = None


    async def count_samples(self):
        return self.count_liquid_sample_nowait()


    def count_samples_nowait(self):
        self.open_DB()
        self.cur.execute("select count(idx) from liquid_sample;")
        counts = self.cur.fetchone()[0]
        self.base.print_message(f"sqlite db liquid sample count: {counts}", info = True)
        self.close_DB()
        return counts


    async def new_sample(self, samples: List[liquid_sample] = [], use_supplied_no: Optional[bool] = False):
        self.new_sample_nowait(samples=samples, use_supplied_no=use_supplied_no)


    def new_sample_nowait(self, samples: List[liquid_sample] = [], use_supplied_no: Optional[bool] = False):
        counts = self.count_samples_nowait()
        dataentry = []
        if type(samples) is not list:
            samples = [samples]

        for i, sample in enumerate(samples):

          # global_label TEXT NOT NULL,
          # sample_type VARCHAR(255) NOT NULL,
          # sample_no INTEGER NOT NULL,
          # sample_creation_timecode VARCHAR(255) NOT NULL,
          # machine_name VARCHAR(255) NOT NULL,
          # last_update VARCHAR(255) NOT NULL,
          # volume_mL REAL NOT NULL,

            if use_supplied_no == False:
                liquid_sample.sample_no = counts+1+i


            if sample.machine_name is None:
                sample.machine_name = self.base.hostname

            if sample.volume_mL is None:
                sample.volume_mL = 0.0

            if sample.server_name is None:
                sample.server_name = self.base.server_name
                
            if sample.process_queue_time is None:
                atime = datetime.fromtimestamp(datetime.now().timestamp() + self.base.ntp_offset)
                sample.process_queue_time = atime.strftime("%Y%m%d.%H%M%S%f")

            if sample.sample_creation_timecode is None:
                sample.sample_creation_timecode = self.base.set_realtime_nowait()

            if sample.last_update is None:
                sample.last_update = self.base.set_realtime_nowait()



            # if liquid_sample.process_group_uuid is None:
            #     liquid_sample.process_group_uuid = ""
            # if liquid_sample.process_uuid is None:
            #     liquid_sample.process_uuid = ""
            # if liquid_sample.source is None:
            #     liquid_sample.source = ""

            
            dataentry.append(
                (
                  sample.get_global_label(),
                  "liquid",#sample.sample_type,
                  sample.sample_no,
                  sample.sample_creation_timecode,
                  sample.sample_position,
                  sample.machine_name,
                  sample.sample_hash,
                  sample.last_update,
                  sample.status,
                  sample.inheritance,
                  sample.process_group_uuid,
                  sample.process_uuid,
                  sample.process_queue_time,
                  sample.server_name,
                  json.dumps(sample.chemical),
                  json.dumps(sample.mass),
                  json.dumps(sample.supplier),
                  json.dumps(sample.lot_number),
                  json.dumps(sample.source),
                  sample.comment,
                  sample.volume_mL,
                  sample.pH
                )
            )

        self.open_DB()
        self.con.executemany("""INSERT INTO liquid_sample(
              global_label,
              sample_type,
              sample_no,
              sample_creation_timecode,
              sample_position,
              machine_name,
              sample_hash,
              last_update,
              status,
              inheritance,
              process_group_uuid,
              process_uuid,
              process_queue_time,
              server_name,
              chemical,
              mass,
              supplier,
              lot_number,
              source,
              comment,
              volume_mL,
              pH
            ) VALUES (
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?
                )""", dataentry)        
        self.close_DB()


    # async def get_liquid_sample(self, sample_no = None, global_hash: Optional[str] = None):
    #     pass


    async def old_jsondb_to_sqlitedb(self):
        old_liquid_sample_DB = old_liquid_sample_API(self.base, os.path.join(self.DBfilepath, self.DBfile))
        counts = await old_liquid_sample_DB.count_liquid_sample()
        self.base.print_message(f"old db sample count: {counts}", info = True)
        for i in range(counts):
            liquid_sample_jsondict = await old_liquid_sample_DB.get_liquid_sample(i+1)
            self.new_sample_nowait(liquid_sample(**liquid_sample_jsondict), use_supplied_no=True)


class old_liquid_sample_API:
    def __init__(self, Serv_class, DBpath):
        self.base = Serv_class
        
        self.DBfile = "liquid_ID_database.csv"
        self.DBfilepath = DBpath
        # self.DBfilepath, self.DBfile = os.path.split(DB)
        self.fDB = None
        self.headerlines = 0
        # create folder first if it not exist
        if not os.path.exists(self.DBfilepath):
            os.makedirs(self.DBfilepath)

        if not os.path.exists(os.path.join(self.DBfilepath, self.DBfile)):
            # file does not exists, create file
            f = open(os.path.join(self.DBfilepath, self.DBfile), "w")
            f.close()

        self.base.print_message(
            f" ... liquid sample no database is: {os.path.join(self.DBfilepath, self.DBfile)}"
        )


    async def open_DB(self, mode):
        if os.path.exists(self.DBfilepath):
            self.fDB = await aiofiles.open(
                os.path.join(self.DBfilepath, self.DBfile), mode
            )
            return True
        else:
            return False


    async def close_DB(self):
        await self.fDB.close()


    async def count_liquid_sample(self):
        # TODO: faster way?
        _ = await self.open_DB("a+")
        counter = 0
        await self.fDB.seek(0)
        async for line in self.fDB:
            counter += 1
        await self.close_DB()
        return counter - self.headerlines


    async def new_liquid_sample(self, new_sample: liquid_sample):
        async def write_sample_no_jsonfile(filename, datadict):
            """write a separate json file for each new sample_no"""
            self.fjson = await aiofiles.open(os.path.join(self.DBfilepath, filename), "a+")
            await self.fjson.write(json.dumps(datadict))
            await self.fjson.close()

        async def add_line(line):
            if not line.endswith("\n"):
                line += "\n"
            await self.fDB.write(line)
                
        self.base.print_message(f" ... new entry dict: {new_sample.dict()}")
        new_sample.sample_no = await self.count_liquid_sample() + 1
        self.base.print_message(f" ... new liquid sample no: {new_sample.sample_no}")
        # dump dict to separate json file
        await write_sample_no_jsonfile(f"{new_sample.sample_no:08d}__{new_sample.process_group_uuid}__{new_sample.process_uuid}.json",new_sample.dict())
        # add newid to DB csv
        await self.open_DB("a+")
        await add_line(f"{new_sample.sample_no},{new_sample.process_group_uuid},{new_sample.process_uuid}")
        await self.close_DB()
        return new_sample


    async def get_liquid_sample(self, sample: liquid_sample):
        """accepts a liquid sample model with minimum information to find it in the db
        and returns its full information
        """
        async def load_json_file(filename, linenr=1):
            self.fjsonread = await aiofiles.open(
                os.path.join(self.DBfilepath, filename), "r+"
            )
            counter = 0
            retval = ""
            await self.fjsonread.seek(0)
            async for line in self.fjsonread:
                counter += 1
                if counter == linenr:
                    retval = line
            await self.fjsonread.close()
            retval = json.loads(retval)
            return retval

        async def get_liquid_sample_details(sample_no):
            # need to add headerline count
            sample_no = sample_no + self.headerlines
            await self.open_DB("r+")
            counter = 0
            retval = ""
            await self.fDB.seek(0)
            async for line in self.fDB:
                counter += 1
                if counter == sample_no:
                    retval = line
                    break
            await self.close_DB()
            return retval


        # for now it only checks against local samples
        if sample.machine_name != gethostname():
            self.base.print_message(f" ... can only load from local db, got {sample.machine_name}", error = True)
            return None # return default empty one

        

        data = await get_liquid_sample_details(sample.sample_no)
        if data != "":
            data = data.strip("\n").split(",")
            fileID = int(data[0])
            process_group_uuid = data[1]
            process_uuid = data[2]
            filename = f"{fileID:08d}__{process_group_uuid}__{process_uuid}.json"
            self.base.print_message(f" ... data json file: {filename}")
            
            
            liquid_sample_jsondict = await load_json_file(filename, 1)
            # fix for old db version
            if "id" in liquid_sample_jsondict: # old v1
                # liquid_sample_jsondict["plate_sample_no"] = liquid_sample_jsondict["sample_no"]
                liquid_sample_jsondict["sample_no"] = liquid_sample_jsondict["id"]
                del liquid_sample_jsondict["id"]
                if "plate_id" in liquid_sample_jsondict:
                    del liquid_sample_jsondict["plate_id"]

            if "sample_id" in liquid_sample_jsondict:
                liquid_sample_jsondict["sample_no"] = liquid_sample_jsondict["sample_id"]
                del liquid_sample_jsondict["sample_id"]
                
            if "AUID" in liquid_sample_jsondict:
                liquid_sample_jsondict["process_uuid"] = liquid_sample_jsondict["AUID"]
                del liquid_sample_jsondict["AUID"]
                
            if "DUID" in liquid_sample_jsondict:
                liquid_sample_jsondict["process_group_uuid"] = liquid_sample_jsondict["DUID"]
                del liquid_sample_jsondict["DUID"]
                


            ret_liquid_sample = liquid_sample(**liquid_sample_jsondict)
            self.base.print_message(f" ... data json content: {ret_liquid_sample.dict()}")
            
            return ret_liquid_sample
        else:
            return None # will be default empty one


def create_md5():
    pass


def create_initial_sqllitedb(dbcur):
    """create initial sqlite3 db for gas, liquid, assemblies"""
    dbcur.execute(
          """CREATE TABLE liquid_sample(
          idx INTEGER PRIMARY KEY AUTOINCREMENT,
          global_label TEXT NOT NULL,
          sample_type VARCHAR(255) NOT NULL,
          sample_no INTEGER NOT NULL,
          sample_creation_timecode INTEGER NOT NULL,
          sample_position VARCHAR(255),
          machine_name VARCHAR(255) NOT NULL,
          sample_hash VARCHAR(255),
          last_update INTEGER NOT NULL,
          status TEXT,
          inheritance TEXT,
          process_group_uuid VARCHAR(255),
          process_uuid VARCHAR(255),
          process_queue_time VARCHAR(255),
          server_name VARCHAR(255),
          chemical TEXT,
          mass TEXT,
          supplier TEXT,
          lot_number TEXT,
          source TEXT,
          comment TEXT,
          volume_mL REAL NOT NULL,
          pH REAL
          );""")



class unified_sample_data_API():
    def __init__(self, Serv_class, DBpath):
        self.base = Serv_class
        self.DBfilepath = DBpath
        self.local_liquidDB = liquid_sample_API(self.base, self.DBfilepath)
        