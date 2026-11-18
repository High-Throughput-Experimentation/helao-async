# Output catalog in folder READMEs: design

Date: 2026-11-18
Status: approved in conversation, pending written-spec review

## Goal

Every output that helao produces or parses gets a written description next to the
code that writes it. A reader opens a server, analysis, processor or batch-script
folder's `README.md` and finds, for each output field: its name, data type, structure,
unit (where physical), meaning, and the `file:line` that writes it.

Readers: people analysing helao data downstream, and agents editing the writers.

## Scope

In scope:

- **Action servers.** For each action (endpoint) that writes data: the data files
  (`.jsonl` + `.meta.json`, `.parquet`, images, vendor raw files, zips) and the
  `action_output` dict saved in the `-act.json` record.
- **Analyses.** Analysis modules under each deployment's `servers/analysis/analyses/`:
  the inline `output` dict of each `AnalysisOutputModel`
  (`helao/core/models/analysis.py:69`) and each S3 artifact (`output_type`,
  `content_type`).
- **Hooked processors.** Each deployment's `processors/` folder, including
  `hte/processors/hispec_process_all.py` and its `libs/`, and Deployment-E's equivalent.
- **Batch processing scripts.** Each instrument folder under Deployment-C's `scripts/`
  that converts third-party data into helao records or analyses, plus Deployment-C's
  `batch_convert` and analysis servers. Shared helper folders get a section only where
  they write an output themselves.
- A presence guard test per repo (see Verification).

Out of scope:

- Code changes to writers. A defect found while documenting is listed in the folder
  README's `## Notes`, not fixed.
- Reading production data. Types come from code only (user ruling). Where code cannot
  settle a type, write `unknown (dynamic)` with the reason. Never guess.
- Rewriting existing `## Params`, `## Vendor software` or `## Notes` sections.

## Format

Each README gains an `## Outputs` section after `## Params`. Inside it, one `###`
heading per action, analysis, processor or script entry point.

```markdown
## Outputs

### `run_CV` (action)

Data file `<abbr>-<n>.jsonl` with `<abbr>-<n>.meta.json`, one row per sample,
written at `gamry_server2.py:NNN`.

| field | type | structure | unit | meaning | written at |
|---|---|---|---|---|---|
| `t_s` | float | scalar per row | s | time since technique start | `driver.py:NNN` |

`action_output` (in `-act.json`):

| key | type | structure | meaning | set at |
|---|---|---|---|---|
| `fom_ocv` | float | scalar | ... | `...:NNN` |
```

Rules:

- `type` is one of `int`, `float`, `str`, `bool`, `null`, `dict`, or a union
  (`float | null`). A `dict` gets a nested table under its row, or a link to one.
- `structure` is one of `scalar`, `scalar per row` (a column of a `.jsonl` or
  `.parquet`), `list[<type>]`, `array[<type>, <shape>]`, `dict`.
- Dynamic keys are written as a pattern (`ch_<n>_V`) with a sentence naming the source
  of `<n>` (config param, driver channel list, etc.).
- Non-tabular files (image, vendor raw, zip): one row each, giving format, file name
  pattern, and writer.
- An action that writes nothing gets one line: `No data files or action_output.` so
  absence is explicit rather than an omission.
- Analyses: one table for the `output` dict keys, one row per S3 artifact.
- Processors and batch scripts: same tables, plus a short list of the input files each
  one parses (format, name pattern).
- `written at` / `set at` cite `path:line`, with the path written the same way the
  folder's `## Params` table writes it (full `helao/deploy/<deployment>/...` path).
- Folders with no README (most batch-script folders, processors) get a new `README.md`
  with a one-paragraph purpose line and the `## Outputs` section only.
- Tracked parent-repo files never name a private deployment. Parent-repo READMEs cover
  only `base` and `test`.

## Phases

One implementation plan, executed repo by repo. Each phase is reviewed and committed in
its own repo before the next starts.

1. Parent repo (`base` and `test` servers, `test/processors`) and `hte` (servers,
   `servers/analysis/analyses`, `processors/` with `libs/`).
2. Deployment-C: analysis server and its analyses, `batch_convert` server, each
   instrument folder under `scripts/`.
3. Deployment-A, Deployment-B, Deployment-E, Deployment-F.

## Verification

Per phase:

- **Writer pass** (implementer): builds the tables from code with `file:line` citations.
- **Review pass** (reviewer, separate agent): samples rows against their cited lines,
  checks type and structure, and searches each folder for writers the tables miss.
- **Guard test** `test_readme_outputs.py` in each repo's tests: walks the repo's server,
  analysis, processor and script folders; for any folder whose Python writes an output
  (matches `json_data_keys`, `to_parquet`, `AnalysisOutputModel`, or a `.jsonl` write),
  asserts the folder's `README.md` exists and contains `## Outputs`. It checks presence
  only, not content. A mutation check (delete one `## Outputs` section, the test must
  fail) is required before the test is accepted.
- Each repo's `CLAUDE.md`, where one exists, gains one line: when a change alters a
  written field, update that folder README's `## Outputs`.

## Delivery

- `black` on the new test files before each commit.
- One commit per repo per phase. No push until the user approves.

## Success criteria

- Every folder the guard test flags has an `## Outputs` section, and the test passes in
  every repo.
- The reviewer finds no row whose type, structure or citation disagrees with the code.
- `hispec_process_all.py` and every Deployment-C batch-script entry point are covered.
