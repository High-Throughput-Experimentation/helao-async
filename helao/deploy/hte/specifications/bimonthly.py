import os
import glob
import inspect
from datetime import datetime, timedelta

from helao.helpers.specification_parser import BaseParser
from helao.helpers.sequence_constructor import constructor
from helao.helpers.helao_data import HelaoData


class SpecParser(BaseParser):
    def __init__(self):
        self.PARAM_TYPES = {
            "plate_id": int,
            "plate_sample_no": int,
            "plate_sample_no_list": list,
        }

    def lister(self, folderpath: str):
        specfiles = []
        for i in range(2):
            yearweek = (datetime.now() + timedelta(weeks=-i)).strftime("%y.%W")
            specfiles += sorted(
                glob.glob(
                    os.path.join(folderpath, yearweek, "**", "*.zip"),
                    recursive=True,
                ),
                reverse=True,
            )
        # filter manual experiments
        specfiles = [x for x in specfiles if "__manual_orch_seq__" not in x]
        latest_50 = specfiles[:50]
        return latest_50

    def list_params(self, specfile: str, orch):
        zdat = HelaoData(specfile)
        zyml = zdat.yml
        seqname = zyml["sequence_name"]
        seqfunc = orch.sequence_lib[seqname]
        argspec = inspect.getfullargspec(seqfunc)
        tmpargs = list(argspec.args)
        tmptypes = [argspec.annotations.get(k, "unspecified") for k in list(tmpargs)]
        return {k: v for k, v in zip(tmpargs, tmptypes)}

    def parser(self, specfile: str, orch, params: dict = {}, **kwargs):
        zdat = HelaoData(specfile)
        zyml = zdat.yml
        loaded_params = zyml["sequence_params"]
        loaded_params.update(params)
        seqname = zyml["sequence_name"]
        seqfunc = orch.sequence_lib[seqname]
        newseq = constructor(seqfunc, loaded_params)
        newseq.sequence_codehash = orch.sequence_codehash_lib[seqname]
        newseq.sequence_label = "synced-seq-params"
        return newseq
