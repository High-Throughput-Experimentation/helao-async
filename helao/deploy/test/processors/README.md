# processors

Post-processors for the `test` deployment, used by framework tests and golden configs so they need no instrument deployment: `sim_append_params.py` (metadata) and `sim_hlo_to_csv.py` (data export).

## Outputs

### `sim_append_params.PostProcess` (processor)

Runs at experiment or sequence finalization and adds one marker key to the record's params; writer `helao/deploy/test/processors/sim_append_params.py:16`, `:18`. Writes no files.

Inputs parsed: the in-memory experiment or sequence record (`MetaProcessor.meta`, selected by `meta_type`, `helao/deploy/test/processors/sim_append_params.py:15`).

Record params (in `-exp.json` / `-seq.json`):

| key | in | type | structure | meaning | set at |
|---|---|---|---|---|---|
| `appended_exp_param` | `experiment_params` | str | scalar | constant `"yes"`, experiments only | `helao/deploy/test/processors/sim_append_params.py:16` |
| `appended_seq_param` | `sequence_params` | str | scalar | constant `"yes"`, sequences only | `helao/deploy/test/processors/sim_append_params.py:18` |

### `sim_hlo_to_csv.PostProcess` (processor)

For each action data file it writes a CSV sibling, one CSV row per data row; writer `helao/deploy/test/processors/sim_hlo_to_csv.py:39`.

Inputs parsed: action data files whose `file_type` ends with `helao__file` and whose name ends `.hlo` or `.jsonl`, read with `read_hlo` (`helao/deploy/test/processors/sim_hlo_to_csv.py:30-34`).

| file | format | name pattern | meaning | written at |
|---|---|---|---|---|
| CSV sibling | CSV with header, no index | the data file name with suffix `.csv` (`data_sibling`), or with `_<comment>` before `.csv` when the action param `comment` is non-empty | the data file's columns, one column per key `read_hlo` returns; types are whatever the source file holds | `helao/deploy/test/processors/sim_hlo_to_csv.py:35-39` |

The CSV is registered as a copy of the source `FileInfo` with `file_type` `<server>_csv__file` (the source type with `helao__file` replaced by `csv__file`) and the new `file_name` (`helao/deploy/test/processors/sim_hlo_to_csv.py:40-45`); the source file entry is kept (`:50`).
