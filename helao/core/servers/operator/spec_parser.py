"""The operator's spec-file layer, shared by both UIs.

A *specification file* describes a sequence in a deployment's own format. The
parser that reads it is deployment code, loaded at runtime from the path in
``seqspec_parser_path``, so nothing here knows the format -- only the contract:

* ``SpecParser()`` -- the class the module must expose
* ``.lister(folder) -> [path, ...]``
* ``.PARAM_TYPES -> {name: type}`` -- every parameter the parser understands
* ``.list_params(path, backend) -> {name: ...}`` -- the ones this file uses
* ``.parser(path, backend, params=..., **kwargs) -> Sequence``

The whole feature is opt-in. Most stations configure no parser, and every
function here degrades to "nothing configured" rather than raising, because a
deployment's parser is code this repo never sees and cannot test.
"""

__all__ = [
    "load_parser",
    "clear_parser_cache",
    "spec_files",
    "spec_fields",
    "build_spec_sequence",
]

import importlib.util
import os
import sys

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

#: Parser modules by path. Loading one executes it, so a per-session reload
#: would re-run its import side effects on every operator tab.
_PARSER_MODULE_CACHE: dict = {}


def clear_parser_cache() -> None:
    """Drop the loaded-module cache. For tests that write a new parser."""
    _PARSER_MODULE_CACHE.clear()


def load_parser(parser_path):
    """Load a deployment's ``SpecParser``, or ``None``.

    Returns ``None`` for every failure -- unset, missing file, a module that
    raises while importing, a module with no ``SpecParser`` -- because the tab
    it feeds is optional and a broken parser must disable that tab rather than
    take down the page.
    """
    if not parser_path:
        return None
    if not os.path.isfile(parser_path):
        LOGGER.warning(f"seqspec parser path does not exist: {parser_path}")
        return None
    module = _PARSER_MODULE_CACHE.get(parser_path)
    if module is None:
        try:
            module_name = os.path.basename(parser_path).replace(".py", "")
            spec = importlib.util.spec_from_file_location(module_name, parser_path)
            if spec is None or spec.loader is None:
                LOGGER.warning(f"{parser_path} is not an importable module")
                return None
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        except Exception as exc:
            LOGGER.exception(f"seqspec parser {parser_path} failed to import: {exc}")
            return None
        _PARSER_MODULE_CACHE[parser_path] = module
    parser_class = getattr(module, "SpecParser", None)
    if parser_class is None:
        LOGGER.warning(f"{parser_path} defines no SpecParser class")
        return None
    try:
        return parser_class()
    except Exception as exc:
        LOGGER.exception(f"SpecParser in {parser_path} could not be created: {exc}")
        return None


def spec_files(parser, folder) -> list:
    """Specification files the parser finds in ``folder``."""
    if parser is None or not folder or not os.path.isdir(folder):
        return []
    try:
        return list(parser.lister(folder))
    except Exception as exc:
        LOGGER.warning(f"seqspec parser could not list {folder}: {exc}")
        return []


def spec_fields(parser, spec_file: str, backend) -> list:
    """Describe the parameters one specification file needs.

    ``PARAM_TYPES`` declares every parameter the parser understands;
    ``list_params`` says which of them this file uses. Only the intersection is
    prompted for -- asking for the rest would demand values the spec has no use
    for. Fields carry no default: the Bokeh panel calls these "Required
    sequence parameters" and starts them empty.

    Returns:
        list[dict]: The same shape :func:`app_reflex.fields_for_item` returns,
        so the same form renders both.
    """
    if parser is None:
        return []
    try:
        used = parser.list_params(spec_file, backend)
    except Exception as exc:
        LOGGER.warning(f"seqspec parser could not read {spec_file}: {exc}")
        return []
    declared = getattr(parser, "PARAM_TYPES", {}) or {}
    fields = []
    for name, argtype in declared.items():
        if name not in (used or {}):
            continue
        fields.append(
            {
                "name": name,
                "kind": "number" if argtype in (int, float) else "text",
                "default": "",
                "help": "",
                "options": [],
                "argtype": argtype,
            }
        )
    return fields


def build_spec_sequence(parser, spec_file: str, backend, params: dict, kwargs: dict):
    """Parse a specification file into a ``Sequence``.

    Returns:
        tuple: ``(sequence, error)``. Exactly one is meaningful. A parser
        failure is reported with its message rather than swallowed: the file
        is the operator's own input, and "it did nothing" is unactionable.
    """
    if parser is None:
        return None, "no spec parser is configured for this station"
    if not spec_file:
        return None, "no specification file is selected"
    try:
        sequence = parser.parser(spec_file, backend, params=params, **(kwargs or {}))
    except Exception as exc:
        LOGGER.exception(f"seqspec parser failed on {spec_file}: {exc}")
        return None, f"{os.path.basename(spec_file)} could not be parsed: {exc}"
    return sequence, ""
