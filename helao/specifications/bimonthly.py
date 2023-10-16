import os
import glob
from datetime import datetime, timedelta

from helao.helpers.sequence_constructor import constructor
from helao.helpers.read_hlo import HelaoData


def lister(folderpath: str):
    current_week = datetime.now().strftime("%y.%W")
    last_week = (datetime.now() + timedelta(weeks=-1)).strftime("%y.%W")
    specfiles = sorted(
        glob.glob(
            os.path.join(folderpath, current_week, "**", "*.zip"), recursive=True
        ),
        reverse=True,
    )
    specfiles += sorted(
        glob.glob(os.path.join(folderpath, last_week, "**", "*.zip"), recursive=True),
        reverse=True,
    )
    latest_50 = specfiles[:50]
    return latest_50


def parser(specfile: str, orch, params: dict = {}):
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
