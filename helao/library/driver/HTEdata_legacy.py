import os
import asyncio
import aiofiles


from helao.core.server import Base
from helao.core.data import liquid_sample_no_API, HTE_legacy_API


class LocalDataHandler:
    def __init__(self):
        self.filename = ""
        self.fileheader = ""
        self.filepath = "C:\\temp"  # some default value
        # self.fileext = '.txt' # some default value
        self.f = None

    # helper function
    def sample_to_header(self, sample):
        sampleheader = "%plate=" + str(sample["plate_id"])
        sampleheader += "\n%sample=" + "\t".join(
            [str(sample) for sample in sample["sample_no"]]
        )
        sampleheader += "\n%x=" + "\t".join([str(x) for x in sample["sample_x"]])
        sampleheader += "\n%y=" + "\t".join([str(y) for y in sample["sample_y"]])
        sampleheader += "\n%elements=" + "\t".join(
            [str(element) for element in sample["sample_elements"]]
        )
        sampleheader += "\n%composition=" + "\t".join(
            [str(comp) for comp in sample["sample_composition"]]
        )
        sampleheader += "\n%code=" + "\t".join(
            [str(code) for code in sample["sample_code"]]
        )
        return sampleheader

    async def open_file_async(self, mode: str = "a"):
        if not os.path.exists(self.filepath):
            os.makedirs(self.filepath)

        if mode == "r" or mode == "r+":
            if os.path.exists(os.path.join(self.filepath, self.filename)):
                self.f = await aiofiles.open(
                    os.path.join(self.filepath, self.filename), mode
                )
                return True
            else:
                return False

        if os.path.exists(os.path.join(self.filepath, self.filename)):
            self.f = await aiofiles.open(
                os.path.join(self.filepath, self.filename), mode
            )
            return True
        else:
            self.f = await aiofiles.open(
                os.path.join(self.filepath, self.filename), "w+"
            )
            if len(self.fileheader) > 0:
                await self.write_data_async(self.write_header)
            return True

    async def write_sampleinfo_async(self, sample):
        await self.write_data_async(self.sample_to_header(sample))

    async def write_data_async(self, data):
        if not data.endswith("\n"):
            data += "\n"
        await self.f.write(data)

    async def close_file_async(self):
        await self.f.close()

    def open_file_sync(self):

        if not os.path.exists(self.filepath):
            os.makedirs(self.filepath)

        if os.path.exists(os.path.join(self.filepath, self.filename)):
            # and just appends new data to excisting file
            self.f = open(os.path.join(self.filepath, self.filename), "a")

        else:
            # file does not exists, create file
            self.f = open(os.path.join(self.filepath, self.filename), "w")
            if len(self.fileheader) > 0:
                self.write_data_sync(self.write_header)

    def write_sampleinfo_sync(self, sample):
        self.write_data_sync(self.sample_to_header(sample))

    def write_data_sync(self, data):
        if not data.endswith("\n"):
            data += "\n"
        self.f.write(data)

    def close_file_sync(self):
        self.f.close()


# class cmd_exception(ValueError):
#     def __init__(self, arg):
#         self.args = arg


class HTEdata:
    def __init__(self, actServ: Base):
        self.base = actServ
        self.config_dict = actServ.server_cfg["params"]


        self.qdata = asyncio.Queue(maxsize=100)  # ,loop=asyncio.get_event_loop())
        self.liquidDBpath = self.config_dict["liquid_DBpath"]
        self.liquidDBfile = self.config_dict["liquid_DBfile"]
        self.liquid_sample_no_DB = liquid_sample_no_API(self.liquidDBpath, self.liquidDBfile)
        self.data = HTE_legacy_API()


    def get_platexycalibration(self, plateid: int):
        return None
    
    def save_platexycalibration(self, plateid: int):
        return None


    def get_rcp_plateid(self, plateid: int):
        return self.data.get_rcp_plateid(plateid)


    def get_info_plateid(self, plateid: int):
        return self.data.get_info_plateid(plateid)


    def check_annealrecord_plateid(self, plateid: int):
        return self.data.check_annealrecord_plateid(plateid)


    def check_printrecord_plateid(self, plateid: int):
        return self.data.check_printrecord_plateid(plateid)


    def check_plateid(self, plateid: int):
        return self.data.check_plateid(plateid)


    def get_platemap_plateid(self, plateid: int):
        return self.data.get_platemap_plateid(plateid)


    def get_elements_plateid(self, plateid: int):
        return self.data.get_elements_plateid(
            plateid,
            multielementink_concentrationinfo_bool=False,
            print_key_or_keyword="screening_print_id",
            exclude_elements_list=[""],
            return_defaults_if_none=False)


    async def get_last_liquid_sample_no(self):
        lastno = await self.liquid_sample_no_DB.count_IDs()
        return lastno


    async def get_liquid_sample_no(self, liquid_sample_no: int):
        dataCSV = await self.liquid_sample_no_DB.get_ID_line(liquid_sample_no)
        return dataCSV


    async def get_liquid_sample_no_json(self, liquid_sample_no: int):
        datajson = await self.liquid_sample_no_DB.get_json(liquid_sample_no)
        return datajson


    async def create_new_liquid_sample_no(
        self,
        DUID: str,
        AUID: str,
        source: str,
        sourcevol_mL: str,
        volume_mL: str,
        action_time: str,
        chemical: str,
        mass: str,
        supplier: str,
        lot_number: str,
        servkey: str,
    ):
        def tofloat(self, datastr):
            try:
                return float(datastr)
            except Exception:
                return None

        action_time = action_time.replace(",", ";")
        chemical = chemical.replace(",", ";")
        mass = mass.replace(",", ";")
        supplier = supplier.replace(",", ";")
        lot_number = lot_number.replace(",", ";")
        sourcevol_mL = sourcevol_mL.replace(",", ";")
        source = source.replace(",", ";")

        entry = dict(
            DUID=DUID,
            AUID=AUID,
            source=self.str_to_strarray(source),
            sourcevol_mL=[
                self.tofloat(vol) for vol in self.str_to_strarray(sourcevol_mL)
            ],
            volume_mL=volume_mL,
            action_time=action_time,
            chemical=self.str_to_strarray(chemical),
            mass=self.str_to_strarray(mass),
            supplier=self.str_to_strarray(supplier),
            lot_number=self.str_to_strarray(lot_number),
            servkey=servkey,
        )

        newID = await self.liquid_sample_no_DB.new_ID(entry)
        return newID
