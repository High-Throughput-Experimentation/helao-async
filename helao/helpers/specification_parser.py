import os
import glob
# import inspect

# from helao.helpers.sequence_constructor import constructor
from helao.helpers.premodels import Sequence

class BaseParser:
    def __init__(self):
        self.PARAM_TYPES = {
            "plate_id": int,
            "plate_sample_no": int,
            "plate_sample_no_list": list,
        }

    def lister(self, folderpath: str, limit: int = 50):
        specfiles = []
        specfiles = sorted(glob.glob(os.path.join(folderpath, "*")))
        limited = specfiles[:limit]
        return limited

    def list_params(self, specfile: str, orch):
        ## extract params from sequence name on running orch
        # seqfunc = orch.sequence_lib[seqname]
        # argspec = inspect.getfullargspec(seqfunc)
        # tmpargs = list(argspec.args)
        # tmptypes = [argspec.annotations.get(k, "unspecified") for k in list(tmpargs)]
        tmpargs = []
        tmptypes = []
        return {k: v for k, v in zip(tmpargs, tmptypes)}

    def parser(specfile: str, orch, params: dict = {}, **kwargs):
        ## create sequence from sequence name on running orch
        # seqfunc = orch.sequence_lib[seqname]
        # newseq = constructor(seqfunc, params)
        # newseq.sequence_codehash = orch.sequence_codehash_lib[seqname]
        # newseq.sequence_label = "synced-seq-params"
        # return newseq
        return Sequence()
