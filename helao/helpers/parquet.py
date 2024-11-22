"""
This module provides helper functions to read HLO files, process their data, and convert them to Parquet format.

Functions:
    read_hlo_header(file_path):

    read_hlo_data_chunks(file_path, data_start_index, chunk_size=100):
        Reads the data chunks from a HLO file starting from a given index.

    hlo_to_parquet(input_hlo_path, output_parquet_path, chunk_size=100):
        Converts a HLO file to a Parquet file.

    read_helao_metadata(parquet_file_path):
        Reads the custom metadata from a Parquet file.
"""
import json
import cysimdjson
from ruamel.yaml import YAML
from collections import defaultdict

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

yaml = YAML()


def read_hlo_header(file_path):
    """
    Reads the header of a HLO file and returns the parsed YAML content and the index where the data starts.

    Args:
        file_path (str): The path to the HLO file.

    Returns:
        tuple: A tuple containing:
            - dict: Parsed YAML content from the header.
            - int: The index where the data starts in the file.
    """
    yml_lines = []
    data_start_index = -1
    with open(file_path) as f:
        for i, line in enumerate(f):
            if line.strip().startswith("%%"):
                data_start_index = i + 1
                break
            else:
                yml_lines.append(line)
        yd = dict(yaml.load("\n".join(yml_lines)))
    return yd, data_start_index


def read_hlo_data_chunks(file_path, data_start_index, chunk_size=100, keep_keys=[], omit_keys=[]):
    """
    Reads data from a file in chunks and yields the data as dictionaries.

    Args:
        file_path (str): The path to the file to read.
        data_start_index (int): The line index to start reading data from.
        chunk_size (int, optional): The number of lines to read in each chunk. Defaults to 100.

    Yields:
        tuple: A tuple containing:
            - dict: A dictionary where keys are the JSON keys from the file and values are lists of the corresponding values.
            - int: The maximum length of the lists in the dictionary.
    """
    parser = cysimdjson.JSONParser()
    with open(file_path, "rb") as f:
        chunkd = defaultdict(list)
        for i, line in enumerate(f):
            if i < data_start_index:
                continue
            else:
                jd = parser.parse_in_place(line)
                for k, jval in jd.items():
                    if k in keep_keys or k not in omit_keys:
                        val = jval.export()
                        if isinstance(val, list):
                            chunkd[k] += val
                        else:
                            chunkd[k].append(val)
                if (i - data_start_index + 1) % chunk_size == 0:
                    yield dict(chunkd), max([len(v) for v in chunkd.values()])
                    chunkd = defaultdict(list)
        if chunkd:
            yield dict(chunkd), max([len(v) for v in chunkd.values()])


def hlo_to_parquet(input_hlo_path, output_parquet_path, chunk_size=100):
    """
    Converts HLO (custom format) data to Parquet format.

    Parameters:
    input_hlo_path (str): Path to the input HLO file.
    output_parquet_path (str): Path to the output Parquet file.
    chunk_size (int, optional): Number of rows to process at a time. Default is 100.

    Returns:
    None
    """
    writer = None
    schema = None
    metadata = None
    current_idx = 0
    header, data_start = read_hlo_header(input_hlo_path)

    for chunk, chunklen in read_hlo_data_chunks(
        input_hlo_path, data_start, chunk_size=chunk_size
    ):
        df = pd.DataFrame(chunk, index=range(current_idx, current_idx + chunklen))
        current_idx += chunklen
        table = pa.Table.from_pandas(df)
        if schema is None:
            schema = table.schema
            existing_metadata = schema.metadata
            custom_metadata = json.dumps(header.get("optional", {})).encode("utf8")
            metadata = {**{"helao_metadata": custom_metadata}, **existing_metadata}

        table = table.replace_schema_metadata(metadata)
        schema = table.schema

        if writer is None:
            writer = pq.ParquetWriter(output_parquet_path, schema)

        writer.write_table(table)

    if writer:
        writer.close()


def read_helao_metadata(parquet_file_path):
    """
    Reads Helao metadata from a Parquet file.

    Args:
        parquet_file_path (str): The file path to the Parquet file.

    Returns:
        dict: A dictionary containing the Helao metadata.
    """
    parser = cysimdjson.JSONParser()
    meta = pq.read_metadata(parquet_file_path)
    metadict = parser.parse(meta.metadata.get(b"helao_metadata", b"{}"))
    return metadict
