import os
import ruamel.yaml
from pathlib import Path
from typing import Union


def yml_dumps(obj, options=None):
    """
    Serializes a Python object to a YAML-formatted string.

    Args:
        obj (Any): The Python object to serialize.
        options (dict, optional): Additional options to pass to the YAML dumper. Defaults to None.

    Returns:
        str: The YAML-formatted string representation of the input object.

    Note:
        - The YAML dumper is configured to indent mappings by 2 spaces, sequences by 4 spaces, and offset by 2 spaces.
        - Duplicate keys are allowed in the YAML output.
        - `None` values are represented as "null" in the YAML output.
    """
    yaml = ruamel.yaml.YAML(typ="rt")
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.allow_duplicate_keys = True

    # show null
    def my_represent_none(self, data):
        return self.represent_scalar("tag:yaml.org,2002:null", "null")

    yaml.representer.add_representer(type(None), my_represent_none)

    if options is None:
        options = {}
    from io import StringIO

    string_stream = StringIO()
    yaml.dump(obj, string_stream, **options)
    output_str = string_stream.getvalue()
    string_stream.close()
    return output_str


def yml_load(input: Union[str, Path]):
    """
    Load a YAML file or string.

    This function loads a YAML file or string using the ruamel.yaml library.
    It supports loading from a file path, a Path object, or a YAML string.

    Args:
        input (Union[str, Path]): The input YAML data. This can be a file path (str),
                                  a Path object, or a YAML string.

    Returns:
        obj: The loaded YAML data as a Python object.

    Raises:
        FileNotFoundError: If the input is a file path that does not exist.
        ruamel.yaml.YAMLError: If there is an error parsing the YAML data.
    """
    yaml = ruamel.yaml.YAML(typ="rt")
    yaml.version = (1, 2)
    if isinstance(input, Path):
        with input.open("r") as f:
            obj = yaml.load(f)
    elif os.path.exists(input):
        with open(input, "r") as f:
            obj = yaml.load(f)
    else:
        obj = yaml.load(input)
    return obj
