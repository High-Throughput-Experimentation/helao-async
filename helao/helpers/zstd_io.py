import os
import pyzstd
import _pickle as cPickle


def unzpickle(fpath):
    """
    Uncompresses a zstd compressed file and deserializes the contained pickle object.

    Args:
        fpath (str): The file path to the zstd compressed file.

    Returns:
        object: The deserialized object from the pickle file.
    """
    data = pyzstd.ZstdFile(fpath, "rb")
    data = cPickle.load(data)
    return data


def zpickle(fpath, data):
    """
    Serializes the given data and writes it to a file using Zstandard compression.

    Args:
        fpath (str): The file path where the compressed data will be written.
        data (Any): The data to be serialized and compressed.

    Returns:
        bool: True if the operation is successful.

    Raises:
        Exception: If there is an error during the file writing process.

    Example:
        zpickle('data.zst', my_data)
    """
    with pyzstd.ZstdFile(fpath, "wb") as f:
        cPickle.dump(data, f)
    print(f"wrote to {os.path.abspath(f)}")
    return True
