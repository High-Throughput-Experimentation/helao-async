__all__ = ["HTEdata"]

# import os
# import asyncio
# import aiofiles


from helao.servers.base import Base
from helao.core.data import HTELegacyAPI


# class LocalDataHandler:
#     def __init__(self):
#         self.filename = ""
#         self.fileheader = ""
#         self.filepath = "C:\\temp"  # some default value
#         # self.fileext = '.txt' # some default value
#         self.f = None

#     # helper function
#     def sample_to_header(self, sample):
#         sampleheader = "%plate=" + str(sample["plate_id"])
#         sampleheader += "\n%sample=" + "\t".join(
#             [str(sample) for sample in sample["sample_no"]]
#         )
#         sampleheader += "\n%x=" + "\t".join([str(x) for x in sample["sample_x"]])
#         sampleheader += "\n%y=" + "\t".join([str(y) for y in sample["sample_y"]])
#         sampleheader += "\n%elements=" + "\t".join(
#             [str(element) for element in sample["sample_elements"]]
#         )
#         sampleheader += "\n%composition=" + "\t".join(
#             [str(comp) for comp in sample["sample_composition"]]
#         )
#         sampleheader += "\n%code=" + "\t".join(
#             [str(code) for code in sample["sample_code"]]
#         )
#         return sampleheader

#     async def open_file_async(self, mode: str = "a"):
#         if not os.path.exists(self.filepath):
#             os.makedirs(self.filepath)

#         if mode == "r" or mode == "r+":
#             if os.path.exists(os.path.join(self.filepath, self.filename)):
#                 self.f = await aiofiles.open(
#                     os.path.join(self.filepath, self.filename), mode
#                 )
#                 return True
#             else:
#                 return False

#         if os.path.exists(os.path.join(self.filepath, self.filename)):
#             self.f = await aiofiles.open(
#                 os.path.join(self.filepath, self.filename), mode
#             )
#             return True
#         else:
#             self.f = await aiofiles.open(
#                 os.path.join(self.filepath, self.filename), "w+"
#             )
#             if len(self.fileheader) > 0:
#                 await self.write_data_async(self.write_header)
#             return True

#     async def write_sampleinfo_async(self, sample):
#         await self.write_data_async(self.sample_to_header(sample))

#     async def write_data_async(self, data):
#         if not data.endswith("\n"):
#             data += "\n"
#         await self.f.write(data)

#     async def close_file_async(self):
#         await self.f.close()

#     def open_file_sync(self):

#         if not os.path.exists(self.filepath):
#             os.makedirs(self.filepath)

#         if os.path.exists(os.path.join(self.filepath, self.filename)):
#             # and just appends new data to excisting file
#             self.f = open(os.path.join(self.filepath, self.filename), "a")

#         else:
#             # file does not exists, create file
#             self.f = open(os.path.join(self.filepath, self.filename), "w")
#             if len(self.fileheader) > 0:
#                 self.write_data_sync(self.write_header)

#     def write_sampleinfo_sync(self, sample):
#         self.write_data_sync(self.sample_to_header(sample))

#     def write_data_sync(self, data):
#         if not data.endswith("\n"):
#             data += "\n"
#         self.f.write(data)

#     def close_file_sync(self):
#         self.f.close()


# class cmd_exception(ValueError):
#     def __init__(self, arg):
#         self.args = arg


class HTEdata:
    def __init__(self, action_serv: Base):
        self.base = action_serv
        self.config_dict = action_serv.server_cfg.get("params", {})

        self.dataAPI = HTELegacyAPI()

    def get_platexycalibration(self, plateid: int, *args, **kwargs):
        return None

    def save_platexycalibration(self, plateid: int, *args, **kwargs):
        return None

    def get_rcp_plateid(self, plateid: int, *args, **kwargs):
        return self.dataAPI.get_rcp_plateid(plateid)

    def get_info_plateid(self, plateid: int, *args, **kwargs):
        return self.dataAPI.get_info_plateid(plateid)

    def check_annealrecord_plateid(self, plateid: int, *args, **kwargs):
        return self.dataAPI.check_annealrecord_plateid(plateid)

    def check_printrecord_plateid(self, plateid: int, *args, **kwargs):
        return self.dataAPI.check_printrecord_plateid(plateid)

    def check_plateid(self, plateid: int, *args, **kwargs):
        return self.dataAPI.check_plateid(plateid)

    def get_platemap_plateid(self, plateid: int, *args, **kwargs):
        return self.dataAPI.get_platemap_plateid(plateid)

    def get_elements_plateid(self, plateid: int, *args, **kwargs) -> list:
        return self.dataAPI.get_elements_plateid(
            plateid,
            multielementink_concentrationinfo_bool=False,
            print_key_or_keyword="screening_print_id",
            exclude_elements_list=[""],
            return_defaults_if_none=False,
        )
