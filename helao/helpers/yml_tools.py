"""YAML serialization helpers and post-run record finishing.

Wraps :mod:`ruamel.yaml` with HELAO conventions (2/4/2 indent, ``null`` for
None, duplicate keys allowed) and provides the asynchronous :func:`move_dir`
that marks a record finished in place and notifies the syncer server.
"""

import asyncio
import os
import threading
from io import StringIO
from pathlib import Path
from typing import Optional, Union

import aiohttp
import ruamel.yaml
from ruamel.yaml.representer import RepresenterError

from helao.core.models.run_dir import redirect_manual_dir
from helao.helpers.run_state import DONE as RUN_STATE_DONE
from helao.helpers.run_state import root_relative
from helao.helpers.server_keys import get_sync_server_cfg

#: Per-thread dumper cache. ``ruamel.yaml.YAML`` instances hold emitter state
#: and are not thread-safe, so each thread gets its own.
_DUMPERS = threading.local()

#: Per-thread loader cache, for the same reason as ``_DUMPERS``: parser and
#: scanner state live on the ``YAML`` instance.
_LOADERS = threading.local()


def _represent_none(self, data):
    """Render ``None`` as the literal scalar ``null``."""
    return self.represent_scalar("tag:yaml.org,2002:null", "null")


def _get_dumper(fast: bool) -> ruamel.yaml.YAML:
    """Return this thread's cached dumper for the ``fast``/round-trip variant.

    ``fast=False`` is the round-trip (``typ="rt"``) dumper: it preserves
    comments and ruamel's 2/4/2 indentation, and can represent round-trip
    types such as ``CommentedMap``.

    ``fast=True`` is the C-backed safe dumper (``typ="safe", pure=False``),
    which is ~4x faster but only handles plain Python objects and emits block
    sequences at the parent indent instead of ruamel's indented style. Mapping
    key order is preserved (the safe representer's default alphabetical sort is
    switched off) so the output stays diffable against the round-trip form; the
    two parse to equal objects.
    """
    key = "fast" if fast else "rt"
    yaml = getattr(_DUMPERS, key, None)
    if yaml is not None:
        return yaml

    if fast:
        yaml = ruamel.yaml.YAML(typ="safe", pure=False)
        yaml.default_flow_style = False
        yaml.representer.sort_base_mapping_type_on_output = False
    else:
        yaml = ruamel.yaml.YAML(typ="rt")
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.allow_duplicate_keys = True
    yaml.representer.add_representer(type(None), _represent_none)

    setattr(_DUMPERS, key, yaml)
    return yaml


def yml_dumps(obj, options=None, fast: bool = False) -> str:
    """Serialize ``obj`` to a YAML string using HELAO formatting conventions.

    The dumper is configured for 2/4/2 indentation, allows duplicate keys,
    and renders ``None`` as the literal ``null``.

    Args:
        obj: Python object to serialize.
        options: Extra keyword arguments forwarded to ``yaml.dump``.
        fast: Use the C-backed safe emitter instead of the round-trip one.
            ~4x faster, for callers serializing large volumes of plain
            dict/list/scalar data (the offline batch converters write ~800
            act/exp ymls per plate). Falls back to the round-trip dumper for
            any object the safe representer cannot handle, so it is always
            safe to pass; the only visible difference is block-sequence
            indentation.

    Returns:
        YAML-formatted string.
    """
    if options is None:
        options = {}

    if fast:
        try:
            return _dump_to_str(_get_dumper(True), obj, options)
        except RepresenterError:
            # Round-trip types (CommentedMap), numpy scalars, datetimes and
            # friends: fall through to the general dumper rather than fail.
            # Drop the cached instance first -- a dump that raised mid-emit
            # leaves serializer/emitter state open, which would corrupt the
            # next document written through it.
            _DUMPERS.fast = None

    return _dump_to_str(_get_dumper(False), obj, options)


def _dump_to_str(yaml: ruamel.yaml.YAML, obj, options: dict) -> str:
    """Dump ``obj`` with ``yaml`` into a string."""
    string_stream = StringIO()
    yaml.dump(obj, string_stream, **options)
    output_str = string_stream.getvalue()
    string_stream.close()
    return output_str


def _get_loader(fast: bool) -> ruamel.yaml.YAML:
    """Return this thread's cached loader for the ``fast``/round-trip variant.

    ``fast=False`` is the round-trip (``typ="rt"``) loader, which returns
    ``CommentedMap`` / ``CommentedSeq`` carrying the comments and formatting
    needed to re-emit a document unchanged.

    ``fast=True`` is the C-backed safe loader (``typ="safe", pure=False``),
    which returns plain dicts and lists. It is several times faster to parse,
    but the real cost it avoids is downstream: a ``CommentedSeq``'s
    ``__deepcopy__`` is quadratic in length, so any consumer that copies the
    loaded object pays 75s on a 10k-element sequence that a plain list copies
    in 0.6ms.
    """
    key = "fast" if fast else "rt"
    yaml = getattr(_LOADERS, key, None)
    if yaml is not None:
        return yaml

    if fast:
        # No ``version`` pin here: the C loader is left exactly as measured,
        # and the round-trip branch keeps the 1.2 pin it has always carried.
        yaml = ruamel.yaml.YAML(typ="safe", pure=False)
    else:
        yaml = ruamel.yaml.YAML(typ="rt")
        yaml.version = (1, 2)

    setattr(_LOADERS, key, yaml)
    return yaml


def yml_load(input: Union[str, Path], fast: bool = False):
    """Load YAML from a path, :class:`pathlib.Path`, or raw string.

    Args:
        input: Filesystem path, ``Path`` object, or YAML string.
        fast: Use the C-backed safe loader instead of the round-trip one. Only
            for callers that read a document as data and never re-emit it with
            its comments intact -- the run-tree ymls the syncer walks are the
            motivating case. Verified to read all 472 run ymls on a production
            checkout to objects equal to the round-trip loader's.

    Returns:
        Parsed Python object (typically a dict).

    Raises:
        ruamel.yaml.YAMLError: If the YAML is malformed.
    """
    yaml = _get_loader(fast)
    try:
        if isinstance(input, Path):
            with input.open("r") as f:
                obj = yaml.load(f)
        elif os.path.exists(input):
            with open(input, "r") as f:
                obj = yaml.load(f)
        else:
            obj = yaml.load(input)
    except Exception:
        # A load that raised mid-parse can leave scanner/parser state on the
        # cached instance; drop it so the next document is not read through a
        # half-consumed one.
        setattr(_LOADERS, "fast" if fast else "rt", None)
        raise
    return obj


async def yml_finisher(yml_path: str, sync_config: dict = {}, retry: int = 3) -> bool:
    """POST a finished YAML path to the syncer's ``/finish_yml`` endpoint.

    Args:
        yml_path: Filesystem path to the finalized YAML.
        sync_config: Mapping with at least ``host`` and ``port`` for the syncer
            server; missing keys cause an immediate False return.
        retry: Maximum number of attempts on non-200 responses.

    Returns:
        True on a 200 response, False on missing config, missing file, or
        repeated failure.
    """
    from helao.helpers import helao_logging as logging

    LOGGER = (
        logging.LOGGER if logging.LOGGER is not None else logging.make_logger(__file__)
    )

    yp = Path(yml_path)

    if "host" not in sync_config or "port" not in sync_config:
        return False
    else:
        dbp_port = sync_config["port"]
        dbp_host = sync_config["host"]

    if not yp.exists():
        LOGGER.info(f"{yml_path} was not found, was it already moved?")
        return False

    # Type from the suffix, as /finish_yml ranks it. A full load only to name
    # the type took ~25 s on a 9.7 MB -seq.yml and blocked the caller's loop.
    yml_type = {"seq": "sequence", "exp": "experiment", "act": "action"}.get(
        yp.stem.rsplit("-", 1)[-1], "yml"
    )

    req_params = {"yml_path": yml_path}
    req_url = f"http://{dbp_host}:{dbp_port}/finish_yml"
    async with aiohttp.ClientSession() as session:
        for i in range(retry):
            try:
                async with session.post(req_url, params=req_params) as resp:
                    if resp.status == 200:
                        LOGGER.info(f"Finished {yml_type}: {yml_path}.")
                        return True
                    else:
                        LOGGER.info(
                            f"Retry [{i}/{retry}] finish {yml_type} {yml_path}."
                        )
                        await asyncio.sleep(1)
            except asyncio.TimeoutError:
                continue
        LOGGER.info(f"Could not finish {yml_path} after {retry} tries.")
        return False


async def move_dir(hobj, base: Optional[object] = None, retry_delay: int = 5):
    """Mark an Action/Experiment/Sequence finished. Nothing moves.

    Records are written once, under ``RUNS`` (or ``DIAG`` for a manual run),
    and stay there for life; lifecycle state lives in the per-server journals
    (spec §2). What used to be ~160 lines of copy-with-60-retries followed by
    remove-with-30-retries is now an eviction from this server's journal and
    the same ``yml_finisher`` call as before.

    The old body computed its destination as
    ``yml_dir.replace("RUNS_ACTIVE", dest_dir)``. Under the single
    ``RUNS`` tree that substitution is the identity, so every record was
    copied onto itself and then deleted (plan A24). Nothing here computes a
    destination any more; :func:`helao.core.models.run_dir.is_same_location`
    is the guard any future mover must call before it removes anything.

    ``retry_delay`` is accepted and ignored: there is no longer anything to
    retry. It is kept so the ~30 call sites need no edit.

    Args:
        hobj: An ``Action``, ``Experiment``, or ``Sequence``.
        base: Server object providing ``helaodirs`` and ``world_cfg``.
        retry_delay: Unused. Retained for signature compatibility.

    Returns:
        Empty dict when ``hobj`` is not a supported type; otherwise None.
    """
    from helao.helpers import helao_logging as logging

    LOGGER = (
        logging.LOGGER if logging.LOGGER is not None else logging.make_logger(__file__)
    )

    obj_type = hobj.__class__.__name__.lower()
    if obj_type not in ("action", "experiment", "sequence"):
        LOGGER.info(
            f"Invalid object {obj_type} was provided. Can only move Action, "
            "Experiment, or Sequence."
        )
        return {}

    is_manual = bool(getattr(hobj, "manual_action", False))
    save_dir = str(base.helaodirs.save_root)
    if is_manual:
        save_dir = redirect_manual_dir(save_dir)

    # getattr, not a dict of the three bound methods: a dict literal evaluates
    # every value before the key is selected, so building one looks up
    # `get_action_dir` on an Experiment and raises AttributeError. The raise
    # lands in the event loop's exception handler, so the experiment and
    # sequence are simply never handed to the syncer and the run silently
    # never ships.
    target_subdir = getattr(hobj, f"get_{obj_type}_dir")()
    yml_dir = os.path.normpath(os.path.join(save_dir, target_subdir))

    timestamp = getattr(hobj, f"{obj_type}_timestamp").strftime("%y%m%d.%H%M%S%f")
    yml_path = os.path.join(yml_dir, f"{timestamp}-{obj_type[:3]}.yml")

    # The producing server evicts here, before the handoff: whether or not a
    # syncer exists, this server is done with the record (spec §4.3). A manual
    # record has no handoff at all, so the eviction must not sit under the
    # `not is_manual` branch below or its journal entry would never be dropped.
    journal = getattr(base, "run_journal", None)
    if journal is not None:
        journal.append(
            str(getattr(hobj, f"{obj_type}_uuid")),
            obj_type,
            RUN_STATE_DONE,
            root_relative(yml_dir, base.helaodirs.root),
        )

    if not is_manual:
        await yml_finisher(
            yml_path,
            sync_config=get_sync_server_cfg(base.world_cfg),
        )
    LOGGER.info(f"Finished {yml_dir}")
