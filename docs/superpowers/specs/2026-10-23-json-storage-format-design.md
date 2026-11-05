# JSON storage format: `.meta.json` + `.jsonl` data, `.json` record metadata

Date: 2026-10-23. Branch: `feat/hexagon-completion`.

## Goal

Replace the local `.hlo` data format and the YAML record metadata with standard JSON, while:

- keeping every S3 artifact byte-shape identical (`raw_data/<uuid>/X.hlo.json` = `{"meta", "data"}`, `{type}/{uuid}.json`, `process/{uuid}.json`);
- keeping every reader backward compatible with existing `.hlo`, `.yml`, and zipped sequence archives;
- keeping `read_hlo()` returning the same `(meta, data)` 2-tuple, now also accepting either half of a new pair.

Success: new runs write only the new formats; sync, run_state, reconcile, retire, loaders, data browser and the live analysis paths work on legacy, new, and mixed trees; S3 output is unchanged; the full test sweep passes against a pre-change baseline.

## Decisions

| Topic | Decision |
|---|---|
| Data pair naming | `X__N.meta.json` (header, pretty) + `X__N.jsonl` (rows). S3 name derived from the shared stem: `X__N.hlo.json`. |
| Record metadata | `<ts>-act.json`, `-exp.json`, `-seq.json`, `<pidx>__<uuid>__<tech>-prc.json`, pretty JSON. |
| Analysis model | `<analysis_uuid>-ana.json` (was `<analysis_uuid>.yml`). Outputs stay `<uuid>_output_<group>.json`. |
| `.prg` sidecar | Stays YAML. Path stays `record.with_suffix(".prg")`, so `X-act.json` -> `X-act.prg`. Its flat-text scanners are untouched. |
| Rollout | Hard switch. One writer path; readers dual-read. No config flag. |
| In-flight records | A writer updating an existing record keeps that record's format: if `<stem>.yml` exists it is rewritten as YAML; otherwise `.json`. New records are always `.json`. |
| `aux_files` (`.csv`) | Out of scope; unchanged (still YAML header + `%%` + body). |
| Private deployments | Live paths are updated to dual-read; one-off backfill scripts stay legacy-only. |

Private deployments are named by alias in this document because the parent repository is public.

## 1. Architecture and formats

No new package. Format knowledge lives in two existing modules:

- `helao/hexagon/domain/naming.py` — suffix constants and name helpers:
  - `META_KINDS = ("seq", "exp", "act", "prc", "ana")`
  - `META_SUFFIXES = (".json", ".yml")` (new first)
  - `DATA_SUFFIX = ".jsonl"`, `HEADER_SUFFIX = ".meta.json"`
  - `meta_kind(path) -> str | None` — kind from the `-<kind>.(json|yml)` ending
  - `data_stem(path) -> str` — strips `.hlo`, `.jsonl`, `.meta.json`, `.hlo.json`
  - `is_nosync_file` also matches `.jsonl`
- new `helao/helpers/meta_io.py` (beside `yml_tools.py`, which it uses for the YAML side) — `read_meta(path_or_bytes, name=None)`, `write_meta(path, d)` (applies the in-flight format rule), `dumps_meta(d)`, `meta_glob(root, kind, prefix_pattern)`.
- `helao/helpers/hlo_data.py` — `read_hlo`, `read_hlo_pair_bytes`, `resolve_data_file`, dual-format `read_hlo_header`, `read_hlo_data_chunks`, `hlo_to_parquet`.

Pretty JSON: `orjson` with `OPT_INDENT_2 | OPT_SERIALIZE_NUMPY | OPT_NON_STR_KEYS`, UTF-8, trailing newline. Input is already `clean_dict`-ed, so NaN is `None`. Data rows keep `hlo_json_dumps` unchanged: one compact object per line.

Data pair: `Action.files[].file_name` registers the `.jsonl` only (file_type unchanged); the header travels by stem. A header-less file has no `.meta.json`. Headers are always dicts: a list header becomes `{"text": "<joined lines>"}`; `gamry_server2` passes a dict instead of a pre-dumped YAML string.

Integer keys: `read_meta` returns plain dicts. Pydantic-validated paths (`Experiment.process_order_groups: dict[int, ...]`) coerce themselves. Raw-dict sync sites that compare or sort these keys (`s3_upload` ~209-212, `sync_driver` ~2615-2640) get explicit `int()`.

## 2. Writers

- `NativeDataFileWriter._resolve_output_path` / `init_datafile`: header stays a dict (no `yml_dumps`); `helao_files` -> `X__N.jsonl`; `nosync` checks `.jsonl` too.
- `log_data_set_output_file`: write `X__N.meta.json` atomically (`staging_path` + `os.replace`), then open `X__N.jsonl` `w+`. Empty header -> no `.meta.json`.
- `data_stream` logger: remove the `%%` write and `FileConn.added_hlo_separator`; rows unchanged.
- One-shot `write_file` / `write_file_nowait` (`helao_files`): header written atomically (overwrite), body appended to `.jsonl`, no `%%`. A repeat call to the same name rewrites the header and appends rows (was: second `%%` block).
- `PostHocRunWriter`: `_generated_filename` -> `.jsonl`; `write_file` writes the pair atomically; `write_act/exp/seq` -> `-*.json`. Deployment-C converter hardcoded names (`ms_recording.hlo`, `xy_bkgsub.hlo`, ...) -> `.jsonl`.
- `NativeMetaFileWriter.write_act/exp/seq`, `micro_orch._write_exp/_write_seq` -> `-*.json` via `write_meta` (with the in-flight format rule).
- `SyncDriver.sync_process` -> `-prc.json` (record dir and any PROCESSES mirror).
- `analysis_layout.write_model_yml` -> `write_model_json` writing `<uuid>-ana.json`.
- `action_host._register_present_files`: `.jsonl` -> `helao__file`; skip `.meta.json` and any path with `meta_kind(p)`.
- Stem users (`hlo_to_csv`, `spec_melt_wls`, Deployment-E `hispec2_process_all`, `s3_upload` parquet path) switch from `.replace(".hlo", ...)` to `data_stem`.

## 3. Readers and loaders

`read_hlo(path, keep_keys, omit_keys) -> (meta, data)`, dispatch by name:

- `.hlo` — legacy parser, unchanged.
- `.jsonl` — meta from sibling `X.meta.json` if present else `{}`; rows parsed with the existing `orjson` -> `json.loads` (NaN-tolerant) fallback.
- `.meta.json` — meta from the file, data from sibling `X.jsonl`; a missing `.jsonl` raises `FileNotFoundError` (missing header is legal, missing data is a lost artifact).
- `.hlo.json` — S3 shape `{"meta", "data"}` loaded directly.

`keep_keys` bug (`k in keep_keys or k not in omit_keys`) is fixed on the shared path; its only caller expects filtering.

`resolve_data_file(dir_or_namelist, name)`: reduce any of `X.hlo`, `X.jsonl`, `X.meta.json`, `X.hlo.json` to `X`, then try `X.jsonl`, then `X.hlo`. Replaces the scattered `.hlo.json -> .hlo` fallbacks in `FileMapper.locate` / `_locate_in_zip`, `HelaoData._detached_bytes` / `_resolve_zip_member`, `LocalLoader` `HelaoProcess.hlo`, and `model_base` `data_files` / `hlo_file_tup_type`.

Metadata: `read_meta` dispatches `.yml` -> `yml_load(fast=True)`, `.json` -> `orjson`; works on zip member bytes plus member name. Every `*-<kind>.yml` glob becomes `meta_glob`:

- `sync_driver`: `HelaoYml` (`check_paths`, `list_children`, `parent_yml`, `process_ymls`, `type` via `meta_kind`), `list_pending*`, `sync_yml` child check, `_node_keys`, `_write_off`, `enqueue_yml`, `quarantined`; `Progress.__init__` accepts `.json`.
- `run_state`: `_KIND_BY_SUFFIX`, `identify_record`, `rebuild_from_tree`; `_scan_top_level` gets a `.json` branch (`orjson.loads`, top-level scalars). `.prg` scanners untouched.
- `action_host._reconcile_one`, `ui/shared/retire.py`, `process_locator`, `helpers/processors.py`, `sync_server` / `sim_db_server` rank, `week_window`.
- `HelaoData` (dir and zip modes), `LocalLoader` index and `parse_prc_path`, data browser `sources.py`.

Data browser: `DATA_EXTS = (".hlo", ".jsonl", ".hlo.json", ".parquet")` (bare `.json` dropped); `_index_analyses` takes `*-ana.json` (else legacy first `*.yml`) as the model and `*.json` minus `-ana.json` as outputs; PyYAML `safe_load` replaced by `read_meta`.

Duplicate parsers moved onto `read_hlo` / `read_hlo_header`: hte `processors/libs/hispec_class_2.py`, `hispec_calibrate_downsample_parquet.py`; Deployment-C `scripts/common/session.py`.

Live private-deployment paths via the helpers above: Deployment-C `drivers/data/analyses/*_local.py`; Deployment-A `drivers/calc_driver.py`, `drivers/ml_driver.py`; Deployment-E `helpers/spectrum_utils.py`, `processors/hispec_scale_reference.py`, `processors/hispec2_process_all.py`. Plus hte `drivers/data/calc_driver.py`, `analyses/echeuvis_stability.py`, `analyses/uvis_bkgsubnorm.py`.

Harness (`harness/classify.py`, `hlo_pass`, `yaml_pass`, `treepass`): classify the new suffixes; golden parity compares normalized `(meta, data)` from `read_hlo` / `read_meta`, so legacy goldens match new captures.

## 4. SYNC and S3

- `s3_upload`: branch on `fp.suffix in (".hlo", ".jsonl")`; key `raw_data/{uuid}/{data_stem(fp)}.hlo.json`; payload `{"meta", "data"}` from `read_hlo`. Over 1 GB: `{data_stem}.parquet`. The `files[]` rename to `X.hlo.json` / `helao__json_file` is unchanged, so synced metadata, API rows and process records are identical.
- The header never uploads alone: `upload_files` reads `files[]`, which lists only the `.jsonl`. `warn_unregistered_files` skips a `.meta.json` whose `.jsonl` partner is registered. `native/CLAUDE.md`'s stale `misc_files` sentence is corrected to `upload_files`.
- Record meta: `HelaoYml.meta` via `read_meta`; `{type}/{uuid}.json` still built via `MOD_MAP[type](**meta).clean_dict()`.
- Processes: `-prc.json` beside `-exp.json`; `process/{uuid}.json` unchanged.
- `.prg`: YAML; `rebuild_from_tree` maps either record suffix to `.prg`.
- Routes `/finish_yml`, `/write_off`, `/quarantine` accept `.json` record paths; parameter names keep "yml" (frozen wire surface).
- Zipped sequences are read-only through the section 3 helpers; `micro_orch.zip_runs` zips whatever is on disk.

## 5. Testing

- New `helao/core/tests/test_storage_format.py`: `read_hlo` round-trip across `.meta.json`, `.jsonl`, legacy `.hlo` and S3 `.hlo.json` (all equal); header-less `.jsonl`; missing `.jsonl` raises; `keep_keys` filters (mutation check against the old `or`); `read_meta` `.yml` vs `.json` equality and int-key round-trip via `Experiment.model_validate`; table tests for `meta_kind`, `meta_glob`, `data_stem`, `resolve_data_file`; pretty-format assertions (2-space indent, trailing newline; `.jsonl` one compact object per line).
- Writer tests updated: `test_native_data_file`, `test_native_data_stream`, `test_native_meta_writer` (staging-length pin kept), `test_posthoc_writer`, `test_naming`, `test_action_writes_artifacts`; new names, no `%%`; `write_meta` on a stem with an existing `.yml` rewrites the YAML.
- Mixed-tree fixture (`harness/tests/synthtree.py`): legacy zipped sequence, legacy dir tree, all-new tree, and mixed tree (`-seq.yml` above `-exp.json`/`-act.json`). `HelaoData`, `FileMapper`, `LocalLoader`, data browser, `run_state`, `retire`, `process_locator`, `list_pending*` must report the same record/file counts as a legacy-only twin.
- SYNC golden: `test_sync_postfinish_golden`, `test_upload_set`, `test_s3_upload_parquet_failure` on a new-format record assert S3 keys, payload JSON and renamed `files[]` equal to the legacy-record run.
- Harness parity tests classify the new suffixes.
- Deployment live-path tests run on new-format fixtures plus existing legacy fixtures.
- Gate: full `python run_tests.py` sweep vs a pre-change baseline; pyright on changed files; one simulated group launch (`./helao.sh` with a `test` config) writing a real new-format run that SYNC processes in sim mode. No station or production paths are written.

## Out of scope

- `aux_files` CSV format.
- `.prg` format.
- Converting existing on-disk data.
- One-off backfill scripts in private deployments.
- Dead `HelaoYml.misc_files` / `_is_syncable_misc_file` (left as is).
