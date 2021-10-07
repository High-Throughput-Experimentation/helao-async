
__all__ = ["LiquidSampleAPI",
           "GasSampleAPI",
           "AssemblySampleAPI",
           "UnifiedSampleDataAPI",
           "OldLiquidSampleAPI"]

import os
import aiofiles
import json
import asyncio
from datetime import datetime
from typing import Optional, List
from socket import gethostname

import sqlite3
import pandas as pd

import helao.core.model.sample as hcms


class _BaseSampleAPI(object):
    def __init__(
            self, 
            sampleclass,
            Serv_class, 
            dbpath: str, 
            extra_columns: str):

        self.extra_columns = extra_columns
        self.columns = f"""global_label TEXT NOT NULL,
              sample_type VARCHAR(255) NOT NULL,
              sample_no INTEGER NOT NULL,
              sample_creation_timecode INTEGER NOT NULL,
              sample_position VARCHAR(255),
              machine_name VARCHAR(255) NOT NULL,
              sample_hash VARCHAR(255),
              last_update INTEGER NOT NULL,
              inheritance TEXT,
              status TEXT,
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
              {self.extra_columns}"""


        self.column_names = self.columns.replace("\n","").strip().split(",")
        for i, name in enumerate(self.column_names):
            self.column_names[i] = name.strip().split(" ")[0]
        self.column_count = len(self.column_names)
        
        self._sampleclass = sampleclass
        self._sample_type = f"{sampleclass.sample_type}_sample"
        self._dbfilename = gethostname()+f"__{self._sample_type}.db"
        self._dbfilepath = dbpath
        self._base = Serv_class
        self._db = os.path.join(self._dbfilepath, self._dbfilename)
        self._con = None
        self._cur = None
        # convert these to json when saving them to the db
        self._jsonkeys = ["chemical", "mass", "supplier", "lot_number", "source"]


    def _open_db(self):
        self._con = sqlite3.connect(self._db)
        self._cur = self._con.cursor()


    def _close_db(self):
        if self._con is not None:
            # commit any changes
            self._con.commit()
            self._con.close()
            self._con = None
            self._cur = None


    def _df_to_sample(self, df):
        """converts db dataframe back to a sample basemodel
           and performs a simply data integrity check"""
        if df.size == 0:
            return None
        sampledict = dict(df.iloc[-1, :])

        for key in self._jsonkeys:
            sampledict.update({key:json.loads(sampledict[key])})

        if sampledict["idx"] != sampledict["sample_no"]: # integrity check
            raise ValueError(f"sampledict['idx'] != sampledict['sample_no']: {sampledict['idx']} != {sampledict['sample_no']}")

        retsample = hcms.SampleList(samples=[sampledict])
        if len(retsample.samples):
            return retsample.samples[0]
        else:
            return None


    def _create_init_db(self):
        self._cur.execute(
              f"""CREATE TABLE {self._sample_type}(
              idx INTEGER PRIMARY KEY AUTOINCREMENT,
              {self.columns}
              );""")
        
        self._base.print_message(f"{self._sample_type} table created", info = True)
        # commit changes
        self._con.commit()


    async def _append_sample(self,sample):
        await asyncio.sleep(0.001)
        lock = asyncio.Lock()
        async with lock:
            self._open_db()
            self._cur.execute(f"select count(idx) from {self._sample_type};")
            counts = self._cur.fetchone()[0]
            sample.sample_no = counts+1
            if sample.machine_name is None:
                sample.machine_name = self._base.hostname
            if sample.server_name is None:
                sample.server_name = self._base.server_name
            if sample.process_queue_time is None:
                atime = datetime.fromtimestamp(datetime.now().timestamp() + self._base.ntp_offset)
                sample.process_queue_time = atime.strftime("%Y%m%d.%H%M%S%f")
            if sample.sample_creation_timecode is None:
                sample.sample_creation_timecode = self._base.set_realtime_nowait()
            if sample.last_update is None:
                sample.last_update = self._base.set_realtime_nowait()
            sample.global_label = sample.get_global_label()

            
            dfdict = sample.dict()
            for key in self._jsonkeys:
                dfdict.update({key:[json.dumps(dfdict[key])]})

            keys_to_deletes = []
            for key in dfdict.keys():
                if key not in self.column_names:
                    self._base.print_message(f"Invalid {self._sample_type} data key '{key}', skipping it.", error = True)
                    keys_to_deletes.append(key)
                    
            for key in keys_to_deletes:
                del dfdict[key]
            
            df = pd.DataFrame(data=dfdict)
            df.to_sql(name=self._sample_type, con=self._con, if_exists='append', index=False)
            
            # now read back the sample and compare and return it
            retdf = pd.read_sql_query(f"""select * from {self._sample_type} ORDER BY idx DESC LIMIT 1;""", con=self._con)
            self._close_db()
            retsample = self._df_to_sample(retdf)
            return retsample


    async def _key_checks(self, sample):
        return sample


    async def new_sample(self, samples: list = []):
        if type(samples) is not list:
            samples = [samples]
        ret_samples = []
        for i, sample in enumerate(samples):
            if type(sample) == type(self._sampleclass):
                await asyncio.sleep(0.001)
                sample = await self._key_checks(sample)
                added_sample = await self._append_sample(sample=sample)
                ret_samples.append(added_sample)
            else:
                self._base.print_message(f"wrong sample type {type(sample)}!={self._sample_type}, skipping it", info = True)
        return hcms.SampleList(samples = ret_samples)


    async def init_db(self):
        lock = asyncio.Lock()
        async with lock:
            self._open_db()
            # check if table exists
            listOfTables = self._cur.execute(
              f"""SELECT name FROM sqlite_master WHERE type='table'
              AND name='{self._sample_type}';""").fetchall()
             
            if listOfTables == []:
                self._base.print_message(f" ... {self._sample_type} table not found, creating it.", error = True)
                self._create_init_db()
            else:
                self._base.print_message(f" ... {self._sample_type} table found!")
    
            self._close_db()
        await self.count_samples() # has also a separate lock


    async def count_samples(self):
        await asyncio.sleep(0.001)
        lock = asyncio.Lock()
        async with lock:
            self._open_db()
            self._cur.execute(f"select count(idx) from {self._sample_type};")
            counts = self._cur.fetchone()[0]
            self._base.print_message(f"sqlite db {self._sample_type} count: {counts}", info = True)
            self._close_db()
            return counts

    
    async def get_sample(self,samples: hcms.SampleList = []):
        """this will only use the sample_no for local sample, or global_label for external samples
        and fills in the rest from the db and returns the list again.
        We expect to not have mixed sample types here.
        """

        await asyncio.sleep(0.001)
        if type(samples) is not list:
            samples = [samples]
        
        ret_samples = []
        lock = asyncio.Lock()
        async with lock:
            self._open_db()

            for i, sample in enumerate(samples):
                self._base.print_message(f"getting sample {self._sample_type} {sample.sample_no}", info = True)
                await asyncio.sleep(0.001)
                retdf = pd.read_sql_query(f"""select * from {self._sample_type} where idx={sample.sample_no};""", con=self._con)
                retsample = self._df_to_sample(retdf)
                ret_samples.append(retsample)
            self._close_db()
        return hcms.SampleList(samples = ret_samples)


class LiquidSampleAPI(_BaseSampleAPI):
    def __init__(self, Serv_class, dbpath: str):
        super().__init__(
            sampleclass = hcms.LiquidSample(),
            Serv_class=Serv_class, 
            dbpath=dbpath, 
            extra_columns="volume_ml REAL NOT NULL, ph REAL"
            )


    async def _key_checks(self, sample):
        if sample.volume_ml is None:
            sample.volume_ml = 0.0
        return sample


    async def old_jsondb_to_sqlitedb(self):
        old_liquid_sample_db = OldLiquidSampleAPI(self._base, self._dbfilepath)
        counts = await old_liquid_sample_db.count_samples()
        self._base.print_message(f"old db sample count: {counts}", info = True)
        for i in range(counts):
            liquid_sample_jsondict = await old_liquid_sample_db.get_sample(i+1)
            self.new_sample_nowait(hcms.LiquidSample(**liquid_sample_jsondict), use_supplied_no=True)



class GasSampleAPI(_BaseSampleAPI):
    def __init__(self, Serv_class, dbpath: str):
        super().__init__(
            sampleclass = hcms.GasSample(),
            Serv_class=Serv_class, 
            dbpath=dbpath, 
            extra_columns="volume_ml REAL NOT NULL"
            )


    async def _key_checks(self, sample):
        if sample.volume_ml is None:
            sample.volume_ml = 0.0
        return sample


class AssemblySampleAPI(_BaseSampleAPI):
    def __init__(self, Serv_class, dbpath: str):
        super().__init__(
            sampleclass = hcms.AssemblySample(),
            Serv_class=Serv_class, 
            dbpath=dbpath, 
            extra_columns="parts TEXT"
            )
        self._jsonkeys.append("parts")



class OldLiquidSampleAPI:
    def __init__(self, Serv_class, dbpath):
        self._base = Serv_class
        
        self._dbfile = "liquid_ID_database.csv"
        self._dbfilepath = dbpath
        # self._dbfilepath, self._dbfile = os.path.split(db)
        self.fdb = None
        self.headerlines = 0
        # create folder first if it not exist
        if not os.path.exists(self._dbfilepath):
            os.makedirs(self._dbfilepath)

        if not os.path.exists(os.path.join(self._dbfilepath, self._dbfile)):
            # file does not exists, create file
            f = open(os.path.join(self._dbfilepath, self._dbfile), "w")
            f.close()

        self._base.print_message(
            f" ... liquid sample no database is: {os.path.join(self._dbfilepath, self._dbfile)}"
        )


    async def _open_db(self, mode):
        if os.path.exists(self._dbfilepath):
            self.fdb = await aiofiles.open(
                os.path.join(self._dbfilepath, self._dbfile), mode
            )
            return True
        else:
            return False


    async def _close_db(self):
        await self.fdb.close()


    async def count_samples(self):
        # TODO: faster way?
        _ = await self._open_db("a+")
        counter = 0
        await self.fdb.seek(0)
        async for line in self.fdb:
            counter += 1
        await self._close_db()
        return counter - self.headerlines


    async def new_sample(self, new_sample: hcms.LiquidSample):
        async def write_sample_no_jsonfile(filename, datadict):
            """write a separate json file for each new sample_no"""
            self.fjson = await aiofiles.open(os.path.join(self._dbfilepath, filename), "a+")
            await self.fjson.write(json.dumps(datadict))
            await self.fjson.close()

        async def add_line(line):
            if not line.endswith("\n"):
                line += "\n"
            await self.fdb.write(line)
                
        self._base.print_message(f" ... new entry dict: {new_sample.dict()}")
        new_sample.sample_no = await self.count_samples() + 1
        self._base.print_message(f" ... new liquid sample no: {new_sample.sample_no}")
        # dump dict to separate json file
        await write_sample_no_jsonfile(f"{new_sample.sample_no:08d}__{new_sample.process_group_uuid}__{new_sample.process_uuid}.json",new_sample.dict())
        # add newid to db csv
        await self._open_db("a+")
        await add_line(f"{new_sample.sample_no},{new_sample.process_group_uuid},{new_sample.process_uuid}")
        await self._close_db()
        return new_sample


    async def get_sample(self, sample: hcms.LiquidSample):
        """accepts a liquid sample model with minimum information to find it in the db
        and returns its full information
        """
        async def load_json_file(filename, linenr=1):
            self.fjsonread = await aiofiles.open(
                os.path.join(self._dbfilepath, filename), "r+"
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

        async def get_sample_details(sample_no):
            # need to add headerline count
            sample_no = sample_no + self.headerlines
            await self._open_db("r+")
            counter = 0
            retval = ""
            await self.fdb.seek(0)
            async for line in self.fdb:
                counter += 1
                if counter == sample_no:
                    retval = line
                    break
            await self._close_db()
            return retval


        # for now it only checks against local samples
        if sample.machine_name != gethostname():
            self._base.print_message(f" ... can only load from local db, got {sample.machine_name}", error = True)
            return None # return default empty one

        

        data = await get_sample_details(sample.sample_no)
        if data != "":
            data = data.strip("\n").split(",")
            fileID = int(data[0])
            process_group_uuid = data[1]
            process_uuid = data[2]
            filename = f"{fileID:08d}__{process_group_uuid}__{process_uuid}.json"
            self._base.print_message(f" ... data json file: {filename}")
            
            
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
                


            ret_liquid_sample = hcms.LiquidSample(**liquid_sample_jsondict)
            self._base.print_message(f" ... data json content: {ret_liquid_sample.dict()}")
            
            return ret_liquid_sample
        else:
            return None # will be default empty one


class UnifiedSampleDataAPI():
    def __init__(self, Serv_class, dbpath):
        self._base = Serv_class
        self._dbfilepath = dbpath
        self.local_liquiddb = LiquidSampleAPI(self._base, self._dbfilepath)
        