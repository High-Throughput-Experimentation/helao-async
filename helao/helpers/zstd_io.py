import os
import pyzstd
import _pickle as cPickle


def unzpickle(fpath):
    data = pyzstd.ZstdFile(fpath, "rb")
    data = cPickle.load(data)
    return data


def zpickle(fpath, data):
    with pyzstd.ZstdFile(fpath, "wb") as f:
        cPickle.dump(data, f)
    print(f"wrote to {os.path.abspath(f)}")
    return True
