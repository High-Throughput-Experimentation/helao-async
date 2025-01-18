import json
from ruamel.yaml import YAML
from collections import defaultdict

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pathlib
import os
from pathlib import Path  
import numpy as np  

"""
This module provides helper functions to read HLO files, process their data, and convert them to Parquet format.

Functions:
    read_hlo_header(file_path):

    read_hlo_data_chunks(file_path, data_start_index, chunk_size=100):
        Reads the data chunks from a HLO file starting from a given index.
        The data is at this point downsampled to every 1 nm, the wavelengths
        are set to be the columns and the time is set to be the index.

    hlo_to_parquet(input_hlo_path, output_parquet_path, chunk_size=100):
        Converts a HLO file to a Parquet file.

    read_helao_metadata(parquet_file_path):
        Reads the custom metadata from a Parquet file.
"""

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


def read_hlo_data_chunks(file_path, data_start_index, chunk_size=100):
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
    with open(file_path) as f:
        chunkd = defaultdict(list)
        for i, line in enumerate(f):
            if i < data_start_index:
                continue
            else:
                jd = json.loads(line.strip())
                for k, val in jd.items():
                    if isinstance(val, list):
                        chunkd[k] += val
                    else:
                        chunkd[k].append(val)
                if (i - data_start_index + 1) % chunk_size == 0:
                    yield dict(chunkd), max([len(v) for v in chunkd.values()])
                    chunkd = defaultdict(list)
        if chunkd:
            yield dict(chunkd), max([len(v) for v in chunkd.values()])


def hlo_to_parquet(input_hlo_path, output_parquet_path, chunk_size=100, HiSpEC:bool=False):
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

    if HiSpEC:
        df_headers_no_time = header['optional']['wl']
        df_headers_all = ([000] + df_headers_no_time)
        df_headers_all= list(map(float, df_headers_all))
    #print(len(df_headers_all))

    for chunk, chunklen in read_hlo_data_chunks(
        input_hlo_path, data_start, chunk_size=chunk_size
    ):
        df0 = pd.DataFrame(chunk, index=range(current_idx, current_idx + chunklen))

        if current_idx == 0:
            start_ticktime = df0.iloc[0, 0]     
        
        if HiSpEC:
     
            # convert from ticktime to time
            df0.iloc[:,0] = df0.iloc[:,0].apply(lambda x: x - start_ticktime)

            # rename the first collumn to Time (s)
            #df0.rename(columns={df0.columns[0]: 'Time (s)'}, inplace=True)


            # rename the collumns using df_headers
            #print(current_idx, current_idx+chunklen)
            df0.columns = df_headers_all
            
            # create a new dataframe with collumns 1:-1 of df0
            df = df0.iloc[:, 1:-1]



            

            # downsample the data to every 1 nm
            df=df.T.groupby(df.columns//1).mean().T

            # insert the time collumn from df into df0 as collumn 0
            df.insert(0, 't_s', df0.iloc[:,0])

            df.columns= df.columns.astype(str)
 
            
            
            table = pa.Table.from_pandas(df)
            current_idx += chunklen
            df=pd.DataFrame()

        else:
            table = pa.Table.from_pandas(df0)
            current_idx += chunklen

        #print(df.head())
       
        
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
    meta = pq.read_metadata(parquet_file_path)
    metadict = json.loads(meta.metadata.get(b"helao_metadata", b"{}").decode())
    return metadict


if __name__ == "__main__":    
    input_hlo_path = r"/Users/benj/Documents/MnOxEpoxidation2/2024-07-18-MnOx-attempt3/1mVSpEC/ANDORSPEC-0.0.0.0__0.hlo"
    output_parquet_path = r"/Users/benj/Documents/SpEC_Class_2/test_data/test.parquet"
    hlo_to_parquet(input_hlo_path, output_parquet_path, HiSpEC=True)
