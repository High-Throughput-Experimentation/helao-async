import ruamel.yaml
from pathlib import Path
from typing import Union


def yml_dumps(obj, options=None):
    """Dump yaml to string.

    https://stackoverflow.com/a/63179923

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
    yaml = ruamel.yaml.YAML(typ="rt")
    yaml.version = (1, 2)
    if isinstance(input, Path):
        obj = yaml.load(input.open("r"))
    else:
        obj = yaml.load(open(input, "r"))
    return obj
