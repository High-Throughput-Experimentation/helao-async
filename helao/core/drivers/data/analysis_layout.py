"""The analysis-artifact grammar: ONE implementation, two callers (spec §5 row 13).

Everything that decides *what an analysis record looks like on disk and in the
bucket* lives here and nowhere else:

* the scalar/array output split and the ``analysis/<uuid>_output_<group>.json``
  key template (:func:`analysis_output_models`),
* the content-hash analysis uuid (:func:`analysis_uuid_for`),
* the ``ANALYSES/<yy.ww>/<mmdd>/<HHMMSS>__<name>[__<suffix>]/`` directory
  grammar and its two suffix rules (:func:`analysis_suffix`,
  :func:`analysis_dir`),
* the local write and the S3 upload of the model plus one JSON per output group
  (:func:`write_model_yml`, :func:`publish_outputs`).

Two callers share it. :mod:`helao.core.drivers.data.analysis_driver` is the
live analysis server (``AnalysisSyncer.sync_ana``); the second is
:class:`helao.hexagon.adapters.native.analysis_artifact.NativeAnalysisArtifact`,
the :class:`~helao.hexagon.ports.analysis.AnalysisArtifactPort` implementor a
post-hoc converter publishes through. Before P6e a private deployment's XAFS
converter carried its own copy of all of the above, drifted in eleven places;
that copy is gone and this module is what replaced it.

The module is deliberately free of any server import: it takes an ana-root
string, a model dict and a flat values dict, and it is given an uploader rather
than reaching for one. That is what lets the hexagon native layer -- which may
not import ``helao.core.servers.*`` -- use it unchanged.

**Time is an argument, not an ambient read.** :func:`analysis_dir` takes the
timestamp whose ``%H%M%S`` names the directory. The server path passes each
analysis's own timestamp (one directory per analysis, as it always has); a
post-hoc converter passes one stamp for the whole conversion, so a batch that
happens to straddle a second boundary still lands in a single directory. Both
produce the same path *template*; only the choice of stamp differs, and making
that choice explicit is what stops it being decided by luck.
"""

__all__ = [
    "ANALYSES_DIRNAME",
    "analysis_dir",
    "analysis_model_key",
    "analysis_output_models",
    "analysis_root",
    "analysis_suffix",
    "analysis_uuid_for",
    "parse_analysis_timestamp",
    "sequence_part_of",
    "publish_outputs",
    "upload_json",
    "write_json",
    "write_model_yml",
]

import asyncio
import gzip
import io
import json
import os
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any, Awaitable, Callable, Optional, Union
from uuid import UUID

from pydasher.serialization import hasher

from helao.core.models.analysis import AnalysisOutputModel
from helao.core.models.s3locator import S3Locator
from helao.helpers import helao_logging as logging
from helao.helpers.time_utils import set_time
from helao.helpers.yml_tools import yml_dumps

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

#: Top-level directory, under a config ``root``, holding analysis records.
ANALYSES_DIRNAME = "ANALYSES"

#: ``strftime``/``strptime`` format of ``AnalysisModel.analysis_timestamp`` once
#: ``clean_dict`` has serialized it.
ANALYSIS_TS_FORMAT = "%Y-%m-%d %H:%M:%S.%f"

#: An uploader takes ``(payload, key, compress)`` and answers whether it landed.
Uploader = Callable[..., Awaitable[bool]]


def analysis_root(root: str) -> str:
    """Return the ``ANALYSES`` root under a config ``root``."""
    return os.path.join(root, ANALYSES_DIRNAME)


def analysis_uuid_for(
    analysis_name: str,
    analysis_params: dict,
    process_uuid,
    global_sample_label: Optional[str],
    analysis_codehash: Optional[str],
    run_use,
) -> UUID:
    """Derive the content-hash analysis uuid (spec §5 row 13).

    The uuid is a deterministic hash of the analysis identity, so re-running an
    analysis over the same process with the same parameters and the same source
    code re-mints the same uuid -- an overwrite of one logical record rather
    than a second one. Every field of the hash is part of that identity;
    ``analysis_timestamp`` deliberately is not.

    Args:
        analysis_name: Name of the analysis routine.
        analysis_params: Parameters the analysis was invoked with.
        process_uuid: UUID of the analysed process.
        global_sample_label: Label of the sample the analysis is about.
        analysis_codehash: Hash of the analysis source file.
        run_use: Run-use of the input data.

    Returns:
        The hashed UUID.
    """
    return UUID(
        hasher(
            {
                "analysis_name": analysis_name,
                "analysis_params": analysis_params,
                "process_uuid": process_uuid,
                "global_sample_label": global_sample_label,
                "analysis_codehash": analysis_codehash,
                "run_use": run_use,
            }
        )
    )


def analysis_output_models(
    analysis_uuid,
    bucket: str,
    region: str,
    output_type: str,
    groups: list[tuple[str, dict]],
) -> list[AnalysisOutputModel]:
    """Wrap each named output group in an :class:`AnalysisOutputModel`.

    ``output_keys`` names every key of the group; ``output`` carries only the
    group's SCALAR values. That asymmetry is the contract, not an oversight: the
    model yml is a manifest, and inlining megabyte arrays into it would make the
    yml the size of the payload it points at. The arrays travel in the group's
    own ``analysis/<uuid>_output_<name>.json`` object, whose key this builds.

    An empty group is dropped rather than emitted with no keys.

    Args:
        analysis_uuid: UUID naming the analysis, interpolated into each key.
        bucket: S3 bucket the outputs will be written to.
        region: AWS region of ``bucket``.
        output_type: Tag identifying the output flavour, copied onto each model.
        groups: ``(name, values)`` pairs, in the order they should appear.

    Returns:
        One model per non-empty group, in ``groups`` order.
    """
    models = []
    for name, values in groups:
        output_keys = list(values.keys())
        if not output_keys:
            continue
        models.append(
            AnalysisOutputModel(
                analysis_output_path=S3Locator(
                    bucket=bucket,
                    key=f"analysis/{analysis_uuid}_output_{name}.json",
                    region=region,
                ),
                content_type="application/json",
                output_type=output_type,
                output_keys=output_keys,
                output_name=name,
                output={k: v for k, v in values.items() if not isinstance(v, list)},
            )
        )
    return models


def sequence_part_of(action_output_dir: Union[str, os.PathLike]) -> str:
    """Return the sequence-directory element of an ``action_output_dir``.

    An action output dir is ``<seq dir>/<exp dir>/<action uuid>/``, so the
    sequence directory is the third element from the end. Callers hand this
    either the ``str`` a serialized process yml carries (always ``/``-separated,
    spec §5.1) or the ``Path`` ``premodels.Action`` coerces the field to, which
    on Windows prints with backslashes -- both are accepted, because a writer
    that only handled one of them would silently produce a different directory
    name on the other platform.

    Args:
        action_output_dir: The action's output directory.

    Returns:
        The sequence directory's name.
    """
    return PurePosixPath(str(action_output_dir).replace("\\", "/")).parts[-3]


def analysis_suffix(sequence_part: str, global_sample_label: str = "") -> str:
    """Return the ``__<label>`` suffix appended to an analysis directory name.

    Two rules, tried in order, matching what the live analysis server has always
    written:

    1. a sequence directory of the form ``<HHMMSS>__<name>__<label>`` (three
       ``__``-separated parts) contributes its trailing label;
    2. otherwise a ``legacy__solid__<plate>_<sample>`` sample label contributes
       the plate id plus a mod-10 digit-sum check digit.

    Neither matching yields an empty suffix, i.e. an unsuffixed directory.

    Args:
        sequence_part: Name of the sequence directory (see
            :func:`sequence_part_of`).
        global_sample_label: The analysis's global sample label, if any.

    Returns:
        ``"__<label>"``, or ``""`` when neither rule applies.
    """
    if len(sequence_part.split("__")) == 3:
        return f"__{sequence_part.split('__')[-1]}"
    if (global_sample_label or "").startswith("legacy__solid__"):
        plate_id = global_sample_label.split("legacy__solid__")[-1].split("_")[0]
        checksum = sum(int(x) for x in plate_id) % 10
        return f"__{plate_id}{checksum}"
    return ""


def parse_analysis_timestamp(model_dict: dict) -> datetime:
    """Return an analysis model dict's timestamp, defaulting to now.

    Args:
        model_dict: A cleaned ``AnalysisModel`` dict.

    Returns:
        The parsed ``analysis_timestamp``, or the current NTP-corrected time
        when the model carries none.
    """
    ts = model_dict.get("analysis_timestamp") or set_time().strftime(ANALYSIS_TS_FORMAT)
    if isinstance(ts, datetime):
        return ts
    return datetime.strptime(ts, ANALYSIS_TS_FORMAT)


def analysis_dir(
    ana_root: str, timestamp: datetime, analysis_name: str, suffix: str = ""
) -> str:
    """Return the local directory one analysis record is written into.

    The grammar is ``<ana_root>/<yy.ww>/<mmdd>/<HHMMSS>__<name><suffix>``; every
    time-derived element comes from the single ``timestamp`` argument, so a
    caller that passes one stamp for a batch cannot have that batch split across
    two directories -- or, at a midnight or week boundary, across two days.

    Args:
        ana_root: The ``ANALYSES`` root.
        timestamp: Stamp naming the week, day and second components.
        analysis_name: Name of the analysis routine.
        suffix: Suffix from :func:`analysis_suffix`.

    Returns:
        The absolute directory path (not created).
    """
    return os.path.join(
        ana_root,
        timestamp.strftime("%y.%U"),
        timestamp.strftime("%m%d"),
        f"{timestamp.strftime('%H%M%S')}__{analysis_name}{suffix}",
    )


def analysis_model_key(analysis_uuid) -> str:
    """Return the S3 key of an analysis model's JSON body."""
    return f"analysis/{analysis_uuid}.json"


def write_json(obj: dict, path: str) -> None:
    """Serialize ``obj`` to ``path``, creating its parent directory.

    A plain function so callers can hand it to :func:`asyncio.to_thread` rather
    than serializing potentially multi-megabyte array outputs on the event loop.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f)


def write_model_yml(local_ana_dir: str, analysis_uuid, model_dict: dict) -> str:
    """Write ``<local_ana_dir>/<analysis_uuid>.yml``, creating the directory.

    Args:
        local_ana_dir: Directory from :func:`analysis_dir`.
        analysis_uuid: UUID naming the file.
        model_dict: The cleaned ``AnalysisModel`` dict to dump.

    Returns:
        The path written.
    """
    os.makedirs(local_ana_dir, exist_ok=True)
    path = os.path.join(local_ana_dir, f"{analysis_uuid}.yml")
    with open(path, "w") as f:
        f.write(yml_dumps(model_dict))
    return path


async def upload_json(
    client,
    bucket: str,
    msg: dict,
    target: str,
    retries: int = 5,
    compress: bool = False,
) -> bool:
    """Upload ``msg`` as JSON to ``bucket``/``target``, retrying on failure.

    The single uploader behind :func:`publish_outputs`, so an analysis record
    reaches S3 the same way regardless of which caller produced it. Each attempt
    runs in a worker thread: boto3's client is blocking, and a post-hoc
    converter that called it inline stalled its own event loop for the length of
    a multi-megabyte array upload.

    Args:
        client: A boto3 S3 client (or a recording stand-in exposing
            ``upload_fileobj``). ``None`` means "S3 not configured": treated as
            success, matching the syncer.
        bucket: Destination bucket.
        msg: Dict to serialize.
        target: Destination key.
        retries: Attempts after the first, each following a 30s wait.
        compress: Gzip the body and append ``.gz`` to ``target``.

    Returns:
        True on success (including the not-configured case), else False.
    """
    try:
        if client is None:
            LOGGER.info("S3 is not configured. Skipping to S3 upload.")
            return True
        uploadee: Any = io.BytesIO(json.dumps(msg).encode("utf-8"))
        if compress:
            if not target.endswith(".gz"):
                target = f"{target}.gz"
            buffer = io.BytesIO()
            with gzip.GzipFile(fileobj=buffer, mode="wb") as f:
                f.write(uploadee.read())
            buffer.seek(0)
            uploadee = buffer
        for i in range(retries + 1):
            if i > 0:
                LOGGER.info(f"S3 retry [{i}/{retries}]: {bucket}, {target}")
            # A failed upload_fileobj leaves the buffer partly or wholly
            # consumed, so a retry that did not rewind would upload a truncated
            # body -- or nothing -- and call it a success.
            uploadee.seek(0)
            try:
                await asyncio.to_thread(client.upload_fileobj, uploadee, bucket, target)
                return True
            except Exception:
                LOGGER.error(
                    f"Failed to upload {target} to S3, retrying in 30 seconds",
                    exc_info=True,
                )
                await asyncio.sleep(30)
        LOGGER.info(f"Did not upload {target} after {retries} tries.")
        return False
    except Exception:
        LOGGER.error(f"Could not push {target}.", exc_info=True)
        return False


async def publish_outputs(
    model_dict: dict,
    values: dict,
    local_ana_dir: str,
    uploader: Optional[Uploader] = None,
) -> bool:
    """Write each output group's JSON locally and push model + groups to S3.

    Called after the model yml is on disk. For every entry of
    ``model_dict["outputs"]`` the group's values are selected out of ``values``
    by ``output_keys``, written beside the yml under the basename of the group's
    S3 key, and uploaded to that key.

    ``uploader=None`` is the ``local_only`` mode: the local files are still
    written, no upload is attempted, and the return value reports success. That
    is the *only* switch -- both the model and the group bodies are gated by it,
    which is what a capture run depends on, and what the drifted converter copy
    this replaced got wrong for the model body.

    Args:
        model_dict: The cleaned ``AnalysisModel`` dict already written as yml.
        values: Flat ``{output_key: value}`` mapping spanning every group.
        local_ana_dir: Directory from :func:`analysis_dir`.
        uploader: Async ``(payload, key, compress=...)`` callable, or None.

    Returns:
        True when every upload succeeded (or none was attempted).
    """
    analysis_uuid = model_dict.get("analysis_uuid")
    model_success = True
    if uploader is not None:
        LOGGER.info("uploading analysis model to S3 bucket")
        try:
            model_success = await uploader(
                model_dict, analysis_model_key(analysis_uuid)
            )
        except Exception:
            LOGGER.error(
                f"Failed to upload analysis model {analysis_uuid} to S3.",
                exc_info=True,
            )
            model_success = False
    else:
        LOGGER.info("Analysis publish is local_only, skipping S3/API push.")

    output_successes = []
    for output in model_dict.get("outputs", []):
        keys = output["output_keys"]
        body = {k: v for k, v in values.items() if k in keys}
        target = output["analysis_output_path"]["key"]
        local_json_out = os.path.join(local_ana_dir, os.path.basename(target))
        # Array outputs serialize to megabytes of JSON; keep that off the event
        # loop for the same reason as the analysis itself.
        await asyncio.to_thread(write_json, body, local_json_out)
        if uploader is not None:
            output_successes.append(await uploader(body, target, compress=False))
        else:
            output_successes.append(True)
    return model_success and all(output_successes)
