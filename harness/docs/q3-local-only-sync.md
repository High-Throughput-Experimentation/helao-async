# Q3 verification — local-only sync completion (spec §14 Q3, §12 P0)

**Question:** does a no-S3, no-API `HelaoSyncer` (aws_bucket set, no
aws_config_path) complete the RUNS_FINISHED → RUNS_SYNCED move end-to-end,
including the destructive sequence zip?

**Procedure:** `goldenlocal` config (local-only sim DB server), one
`SIM_websocket_data_seq` run, quiesce via ORCH /global_status + DB
/n_queue + /tasks, then tree inspection (Task 12 steps 1–3).

**Run date:** 2026-07-17
**Legacy SHA:** 2cf99ddff8e4ae14f66a5e2eb956b6da89ca303b
**Verdict:** YES — RUNS_SYNCED zip present, RUNS_FINISHED emptied,
2 prc ymls, no exceptions.

**Evidence:**
- RUNS_SYNCED zip: `/home/dan/INST_hlo_goldenlocal/RUNS_SYNCED/26.28/0717/061532__SIM_websocket_data_seq__q3check.zip`
- RUNS_FINISHED residue: empty (`find RUNS_FINISHED -name '*.yml'` and
  `find RUNS_FINISHED -type f` both return nothing after the syncer
  finished; only the empty directory skeleton under `RUNS_ACTIVE`/
  `RUNS_FINISHED` remains, no files)
- PROCESSES: two `-prc.yml` files found —
  `PROCESSES/26.28/0717/061532__SIM_websocket_data_seq__q3check/260717.061532__SIM_websocket_data/0__06a5a2af-4c9e-7921-8000-ad090a2f96af__SIM_websocket_data-prc.yml`
  and `.../1__06a5a2af-4c9e-7fa1-8000-b051ecfb12f0__SIM_websocket_data-prc.yml`
- `/list_exceptions`: `{}`

**Additional log evidence** (`LOGS/DB.log`, the `sim_db_server`/`sync_driver.py`
instance, no `aws_config_path` configured in `goldenlocal.yml`):
```
06:14:03,112 checking for aws_config_path
06:14:05,216 creating syncer tasks
06:15:40,535 enqueue_yml: Added .../0__0__ORCH__wait/...-act.yml to syncer queue with priority 0.
06:15:45,064 enqueue_yml: Added .../1__0__SIM__acquire_data/...-act.yml to syncer queue with priority 0.
06:15:56,342 enqueue_yml: Added .../061532126399-seq.yml to syncer queue with priority 2.
06:15:56,587 sync_yml: Full sequence has synced, creating zip: RUNS_SYNCED/26.28/0717/061532__SIM_websocket_data_seq__q3check.zip
06:15:56,598 zip_dir: Zipped .../061532__SIM_websocket_data_seq__q3check to .../061532__SIM_websocket_data_seq__q3check.zip
```
The syncer runs its enqueue/move/zip pipeline the same way with or without
an S3 destination configured; `aws_bucket` alone (no `aws_config_path`)
does not block the terminal RUNS_FINISHED → RUNS_SYNCED move.

**Timing note:** the orchestrator's `/global_status` reports `loop_state:
stopped` (queue quiesced) a few seconds *before* the syncer's background
queue has drained and produced the zip — the harness poll loop in Task 12
Step 2 declares "quiesced" on loop/queue state alone. In this run the zip
appeared ~15s after the poll first observed `stopped`. `harness/capture.py`
(Task 13) must poll the DB server's own queue/zip-completion signal (or
simply re-check `RUNS_SYNCED` for the expected zip with a short retry/
timeout) rather than treating orchestrator quiescence as proof that sync
has finished.

One pre-existing benign warning observed in `LOGS/ORCH.log` (unrelated to
sync completion, and not surfaced via `/list_exceptions`):
```
WARNING | ORCH :: move_dir @ yml_tools.py:257 - Error removing
/home/dan/INST_hlo_goldenlocal/RUNS_ACTIVE/26.28/0717/061532__SIM_websocket_data_seq__q3check,
perhaps removed by another operation.
```
This is a race between two directory-removal paths during the
RUNS_ACTIVE → RUNS_FINISHED handoff; the end state still shows
`RUNS_ACTIVE` fully emptied and no residue, and it does not appear in
`/list_exceptions`.

**Consequence:** YES — both capture modes are viable; the gate uses
recording mode (`golden.yml`) for GM-1..GM-5 and this local-only result
stands as the Q3 record. `goldenlocal.yml` is confirmed as a viable
low-overhead capture config (no S3 recorder dependency) for any harness
work that only needs to observe local sync completion. Task 13's poll
logic must account for the quiesce/zip-completion timing gap noted above.
