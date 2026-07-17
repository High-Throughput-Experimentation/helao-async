# P0 gate record (spec §12 P0)

**Date:** 2026-07-17
**Legacy SHA:** bb1fbfc0e0ae76a53a45d8fdfd8bd994b044d889
**Harness version:** 0.1.0
**Golden store:** /home/dan/helao_goldens/ (Q2 default: untracked share;
at-station goldens for private deployments must stay off the public repo)

## Legacy-vs-legacy baseline (two independent runs, normalized-identical)

| Scenario | run1 captured | run2 captured | parity run_id | status |
|---|---|---|---|---|
| GM-1 | 2026-07-17T06:26:40 | 2026-07-17T07:03:24 | f221536989b7 | PASS |
| GM-2 | 2026-07-17T06:32:00 | 2026-07-17T07:05:03 | 5058fd46bdd1 | PASS |
| GM-3 | 2026-07-17T06:33:14 | 2026-07-17T07:06:13 | 211c958dad90 | PASS |
| GM-4 | — | — | — | **DEFERRED** (see below) |
| GM-5 | 2026-07-17T06:30:16 | 2026-07-17T07:08:12 | 3f19aa03637b | PASS |

run1 for GM-1/GM-2/GM-3/GM-5 was captured live in Task 13 and verified
present (provenance.yml + root/ snapshot) before reuse here. run2 for each
was captured independently in this task: fresh `rm -rf
/home/dan/INST_hlo_golden` + fresh `launch.py golden --no-hot-reload` per
scenario, one launch per capture, clean `/shutdown` + process reap between
captures (verified via `ps aux` — no leftover `golden`-group processes at
any point). All four `parity` runs report `PASS (0 diffs)`, exit 0.

Sync leg (FINISHED→SYNCED→S3-recorded) covered by every recording-mode
capture and doubly by GM-5's reset_sync/finish_pending round-trip (the
`.orig` sidecar produced by `reset_sync` — see harness fixes below —
normalized-identical between run1 and run2 too).

### GM-4 deferral

GM-4 cannot be captured: Task 13 confirmed a deterministic PRE-EXISTING
LEGACY BUG (not harness code) — `helao/core/models/server.py:317-324`
`clear_in_finished` iterates `self.nonactive_dict[HloStatus.finished].keys()`
while deleting from that same dict inside the loop, raising `RuntimeError:
dictionary changed size during iteration` on every `clear_estop()` call
once the finished bucket is non-empty (which GM-4's estop leg always
produces — not scenario-driver flakiness, a genuine, deterministic legacy
defect). This is out of scope for the P0 gate (zero legacy edits) and was
NOT worked around or patched here per this task's explicit instructions.
GM-4 is deferred to a separate change that fixes
`clear_in_finished` (e.g. snapshotting `list(...)` before iterating, or
reassigning the dict like the sibling branch above it already does), after
which GM-4 can be captured and gated the same way as GM-1/2/3/5.

## Mutation self-test

Golden: GM-1/run1. Command:
`python -m harness.mutate --golden /home/dan/helao_goldens/GM-1/run1 --workdir /home/dan/helao_goldens/mutation-work`

```
mutation param_value: mutated action_params.duration in 260717.062605884028-act.yml (4.0 -> 4.5) -> fail
mutation drop_file: deleted WsSim-1.1.0.0__0.hlo -> fail
mutation add_hlo_column: appended a row with a new column to WsSim-1.1.0.0__0.hlo -> fail
mutation break_uuid_link: rewired experiment_uuid in 260717.062603561456-act.yml -> fail
{'sanity_pass': True, 'caught': {'param_value': True, 'drop_file': True, 'add_hlo_column': True, 'break_uuid_link': True}, 'ok': True}
```

Exit 0. All 4 mutation classes CAUGHT (parity failed each), sanity pass
(unmutated exploded copy vs golden) True.

## Q3

Resolved in harness/docs/q3-local-only-sync.md — verdict: **YES**, a
local-only (`aws_bucket` set, no `aws_config_path`) `HelaoSyncer` completes
the RUNS_FINISHED → RUNS_SYNCED move end-to-end, including the destructive
sequence zip (real GM-1-style run: zip produced, RUNS_FINISHED emptied, 2
`-prc.yml`, `/list_exceptions` `{}`).

## Determinism levers exercised (if any)

None — no §6.1 manifest-resident lever (quiesce settle polls,
`hlo_row_count_tolerance`, `content_masked_files` pattern) needed
adjusting, and no capture was re-run for that reason.

## Harness normalizer bugs found and fixed (not legacy edits, not §5.5 loosening)

Running the gate against REAL captures (rather than the single-
experiment synthetic trees the normalizer unit tests use) surfaced three
genuine normalizer bugs in the P0 harness code itself. Per this task's
explicit instructions these are in scope to fix ("fix the harness or the
scenario driver, never the volatile list") — none of them touch legacy
code, and none of them add to or loosen the §5.5 volatile-field list or any
manifest-resident masking config.

1. **Sibling exp/seq-dir collision in `treepass.snapshot()`
   (`harness/treepass.py`).** The §5.5 timestamp-strip grammar collapsed
   every wall-clock-derived directory prefix to a fixed literal `"TS"`
   token. This is correct for a run with exactly one experiment of a given
   name, but GM-1 (two `SIM_websocket_data` experiments per sequence),
   GM-2 (`cycles=2` → two `TEST_sub_noblocking` experiments), and GM-5
   (same structure as GM-1) all legitimately repeat an experiment name
   within one run — two real sibling directories then collapsed onto the
   identical normalized string, raising `ValueError: normalized-name
   collision` inside `snapshot()` on a SINGLE tree (before any golden-vs-
   candidate comparison). Fixed by adding `_sibling_tokens()`: for each
   real parent directory, siblings that share a normalized token are
   disambiguated with a `#0`/`#1`/... ordinal assigned in sorted (i.e.
   chronological, since the raw timestamp-bearing prefixes sort lexically
   in execution order) order — capture-independent because two runs of
   the same scripted scenario execute their repeated experiments in the
   same relative order. Directories whose token is already unique among
   siblings are untouched (no suffix), so single-experiment scenarios
   (GM-3) and all existing normalizer unit tests (single-exp synthetic
   trees) are unaffected. Verified: 66/66 harness tests still pass; GM-1/
   GM-2/GM-5 now snapshot without error.

2. **S3-recorded content masking bypassed for non-JSON/non-manifest
   uploads (`harness/s3_pass.py`).** `classify_file` puts every file under
   `S3_SIM/` into `ArtifactRow.S3_RECORD`, which `parity.compare_file`
   routes to `diff_s3_record` — never to the `AUX_FILE` branch where
   `content_masked_files` (§6.4, manifest-resident) is applied. The
   `hlo_to_csv` postprocess output (masked, unseeded-random WsSim data)
   is also uploaded to S3 under `raw_data/<uuid>/...`, so its S3 copy fell
   into `diff_s3_record`'s "other raw_data misc uploads: exact bytes"
   fallback and was compared byte-for-byte, spuriously failing GM-1
   (4 diffs) even though the identical on-disk `.csv` was correctly
   line-count-masked. Fixed by hoisting the mask-mode lookup into a shared
   `harness.manifest.content_mask_mode()` (used by both `parity._diff_aux`
   and `s3_pass.diff_s3_record`'s fallback branch) so S3-recorded and
   on-disk copies of the same masked file get the identical treatment —
   still driven entirely by the golden set's own `content_masked_files`
   manifest entry, not a new hardcoded rule.
3. **`reset_sync`'s `.orig` sidecar never exploded
   (`harness/classify.py` + `harness/treepass.py`).** GM-5 specifically
   exercises `reset_sync`, which (per `sync_driver.py` `reset_sync()`)
   renames a synced `.zip` to `.orig` IN PLACE — it is still a valid zip
   archive, just with a different extension — but `explode_zips` only
   globbed `*.zip`, so the `.orig` file was left intact and classified as
   a generic `AUX_FILE`, byte-compared as an opaque archive blob (zip
   member mtimes plus the same masked-random WsSim payload inside it made
   this always differ). Fixed by adding the parallel `RE_SEQ_ORIG`/
   `RE_SEQ_ORIGDIR` grammar (mirroring `RE_SEQ_ZIP`/`RE_SEQ_ZIPDIR`) and
   exploding `*.orig` into `*.origdir` in `explode_zips`, so its members go
   through the ordinary per-file passes (yaml/hlo/content-mask) exactly
   like a `.zip`'s members do.
4. **`mutate.mutate_param_value` fixture-specific literal
   (`harness/mutate.py`).** The mutation self-test's `param_value` case
   searched for the literal string `"duration: 2.0"` — true only for the
   synthetic single-action fixture in `synthtree.py`. Against a real
   GM-1 capture the alphabetically-first `-act.yml` is an ORCH `wait`
   action (no `duration` param at all), and the SIM `acquire_data`
   action's `duration` is scenario-parameterized (`data_duration: 4.0`,
   not 2.0), so the mutation raised `RuntimeError` instead of mutating.
   Fixed by searching every action file (sorted, for capture-independence)
   for the first `duration: <float>` occurrence via regex and perturbing
   that value, rather than assuming a fixed literal old/new pair.

All four fixes were verified by re-running `pytest harness/tests -q`
(66/66 pass, no regressions) after each change, then re-running the
affected `parity`/`mutate` invocations to confirm PASS/CAUGHT before
moving on. `black` was run on every changed file as the final step.
