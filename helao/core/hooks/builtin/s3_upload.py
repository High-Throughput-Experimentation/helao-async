"""Built-in post-finish hook: today's S3 leg of ``sync_yml``, moved verbatim.

Blocking (spec §6.1). For an action: push every file the record names
(``.hlo`` -> ``.hlo.json`` under 1 GB, parquet above; anything else as-is),
record ``files_s3``/``files_pending`` as it goes so a partial upload resumes,
and rename the uploaded entries in the meta it is about to ship. For an
experiment: finish its pending processes (``sync_process`` writes the local
``-prc.yml`` and uploads ``process/<uuid>.json``) and set ``process_list``.
Then patch the meta through the pydantic model, split a list
``technique_name``, upload ``<type>/<uuid>.json`` and set the ``s3``/``api``
flags. For an action that contributes to a process, fold it into its parent's
process bookkeeping and push the process (settled decision A2).

Failure = raise: a pass that uploads nothing, processes that will not finish,
an unreadable ``.hlo``, or a failed meta upload all leave the record unsynced
for the next pass, exactly as ``return False`` did.
"""

import asyncio
import os
from copy import copy
from pathlib import Path

from helao.core.hooks import FinishHook, PostfinishContext
from helao.core.models.file import FileInfo
from helao.core.models.process import ProcessModel
from helao.helpers import helao_logging as logging
from helao.helpers.hlo_data import hlo_to_parquet, read_hlo
from helao.helpers.premodels import Action, Experiment, Sequence

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

# Same tables as the sync drivers'; duplicated rather than imported so this
# module depends on neither twin (they import the hooks package at module top).
MOD_MAP = {
    "action": Action,
    "experiment": Experiment,
    "sequence": Sequence,
    "process": ProcessModel,
}
MOD_PATCH = {"exid": "exec_id"}


class Hook(FinishHook):
    blocking = True
    phase = "postfinish"

    async def run(self, ctx: PostfinishContext) -> None:
        syncer = ctx.syncer
        prog = ctx.prg
        opts = ctx.opts or {}
        compress = bool(opts.get("compress", False))
        force_s3 = bool(opts.get("force_s3", False))
        force_api = bool(opts.get("force_api", False))
        retries = int(opts.get("retries", 3))

        meta = copy(prog.yml.meta)
        # Own the files list: the upload loop renames entries to their S3 names
        # (.hlo -> .hlo.json), and a shared list would leak that into
        # prog.yml.meta, where warn_unregistered_files reads it as missing.
        if "files" in meta:
            meta["files"] = list(meta["files"] or [])

        # next push files to S3 (actions only)
        if prog.yml.type == "action":
            LOGGER.debug(f"Checking file lists for {prog.yml.target.name}")
            prog.dict["files_pending"] += [
                rel
                for rel in (prog.relpath(p) for p in prog.yml.upload_files)
                if rel not in prog.dict["files_pending"]
                and rel not in prog.dict["files_s3"]
            ]
            while prog.dict.get("files_pending", []):
                pending_before = len(prog.dict["files_pending"])
                for sp in list(prog.dict["files_pending"]):
                    fp = prog.abspath(sp)
                    if not fp.exists():
                        LOGGER.error(
                            f"Pending file {sp} for {prog.yml.target.name} is not on "
                            "disk; dropping it from the upload list."
                        )
                        prog.dict["files_pending"].remove(sp)
                        prog.write_dict()
                        continue
                    LOGGER.debug(f"Pushing {sp} to S3 for {prog.yml.target.name}")
                    if fp.suffix == ".hlo":
                        if fp.stat().st_size < 1024**3:  # 1GB
                            file_s3_key = (
                                f"raw_data/{meta['action_uuid']}/{fp.name}.json"
                            )
                            if compress:
                                file_s3_key += ".gz"
                            LOGGER.debug("Parsing hlo dicts.")
                            try:
                                file_meta, file_data = await asyncio.to_thread(
                                    read_hlo, fp
                                )
                            except Exception:
                                LOGGER.error(
                                    f"Failed to read hlo file {fp}; leaving it "
                                    "pending rather than uploading an empty "
                                    "payload.",
                                    exc_info=True,
                                )
                                raise
                            msg = {"meta": file_meta, "data": file_data}
                        else:
                            LOGGER.debug(
                                "hlo file larger than 1GB, converting to parquet."
                            )
                            file_s3_key = (
                                f"raw_data/{meta['action_uuid']}/{fp.stem}.parquet"
                            )
                            try:
                                parquet_path = str(fp).replace(".hlo", ".parquet")
                                await asyncio.to_thread(
                                    hlo_to_parquet, fp, parquet_path
                                )
                                msg = Path(parquet_path)
                            except Exception:
                                LOGGER.error(
                                    f"Failed to convert hlo file {fp} to parquet, skipping upload.",
                                    exc_info=True,
                                )
                                msg = None
                    else:
                        file_s3_key = f"raw_data/{meta['action_uuid']}/{sp}"
                        msg = fp
                    LOGGER.debug(f"Destination: {file_s3_key}")
                    file_success = await syncer.to_s3(
                        msg=msg,
                        target=file_s3_key,
                        compress=compress,
                    )
                    if file_success:
                        LOGGER.debug("Removing file from pending list.")
                        prog.dict["files_pending"].remove(sp)
                        LOGGER.info(f"Adding file to S3 dict. {sp}: {file_s3_key}")
                        prog.dict["files_s3"].update({sp: file_s3_key})
                        LOGGER.debug(f"Updating progress: {prog.dict}")
                        prog.write_dict()

                        # update files list with uploaded filename
                        if fp.name != os.path.basename(file_s3_key):
                            file_idx = [
                                i
                                for i, x in enumerate(meta["files"])
                                if x["file_name"]
                                == str(fp.relative_to(prog.yml.targetdir))
                            ][0]
                            fileinfo = FileInfo.model_validate(
                                meta["files"].pop(file_idx)
                            )
                            fileinfo.file_name = str(
                                fp.relative_to(prog.yml.targetdir)
                            ).replace("\\", "/")
                            if "." in file_s3_key.split("/")[-1]:
                                fileinfo.file_name = os.path.basename(file_s3_key)
                            else:
                                fileinfo.file_name = fileinfo.file_name.replace(
                                    f"{fp.suffix}", ""
                                )
                            if fileinfo.file_type.endswith(
                                "helao__file"
                            ):  # generic file
                                fileinfo.file_type = fileinfo.file_type.replace(
                                    "helao__file",
                                    f"helao__{file_s3_key.split('.')[-1]}_file",
                                )
                            meta["files"].append(fileinfo.model_dump())
                if len(prog.dict["files_pending"]) == pending_before:
                    raise RuntimeError(
                        f"No file uploaded for {prog.yml.target.name} in a full pass; "
                        f"leaving {prog.dict['files_pending']} pending for the next scan."
                    )

        # experiments: finish processes before pushing the meta
        if prog.yml.type == "experiment":
            LOGGER.debug(f"Finishing processes for {prog.yml.target.name}")
            retry_count = 0
            s3_unf, api_unf = prog.list_unfinished_procs()
            while s3_unf or api_unf:
                if retry_count == retries:
                    break
                await syncer.sync_process(prog, force=True)
                s3_unf, api_unf = prog.list_unfinished_procs()
                retry_count += 1
            if s3_unf or api_unf:
                raise RuntimeError(
                    f"Processes in {str(prog.yml.target)} did not sync after "
                    f"{retries} tries."
                )
            if prog.dict["process_metas"]:
                meta["process_list"] = [
                    d["process_uuid"]
                    for _, d in sorted(prog.dict["process_metas"].items())
                ]

        LOGGER.debug(f"Patching model for {prog.yml.target.name}")
        patched_meta = {MOD_PATCH.get(k, k): v for k, v in meta.items()}
        meta = MOD_MAP[prog.yml.type](**patched_meta).clean_dict(strip_private=True)

        # patch technique lists in meta
        tech_name = meta.get("technique_name", "NA")
        if isinstance(tech_name, list):
            split_technique = tech_name[meta.get("action_split", 0)]
            meta["technique_name"] = split_technique

        # next push prog.yml to S3
        if not prog.s3_done or force_s3:
            LOGGER.debug(f"Pushing prog.yml->json to S3 for {prog.yml.target.name}")
            uuid_key = patched_meta[f"{prog.yml.type}_uuid"]
            meta_s3_key = f"{prog.yml.type}/{uuid_key}.json"
            s3_success = await syncer.to_s3(meta, meta_s3_key)
            if not s3_success:
                raise RuntimeError(f"Failed to upload {meta_s3_key}")
            prog.dict["s3"] = True
            prog.write_dict()

        # The API leg is retired: the SQL database is offline. The flag is
        # still set so legacy readers of the sidecar close the record out.
        if not prog.api_done or force_api:
            prog.dict["api"] = True
            prog.write_dict()

        # if action contributes processes, update processes (moved from after
        # the DONE journal entry: it needs the patched meta -- decision A2)
        if (
            prog.s3_done
            and prog.api_done
            and prog.yml.type == "action"
            and meta.get("process_contrib", False)
        ):
            exp_prog = syncer.update_process(prog.yml, meta)
            await syncer.sync_process(exp_prog)
