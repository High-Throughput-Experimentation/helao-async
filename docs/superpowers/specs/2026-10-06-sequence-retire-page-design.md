# Sequence retire page: design

Date: 2026-10-06
Status: approved design (approach 1). Questions raised in review are resolved at the end.

## Purpose and background

Batch conversion gives a published sequence a *deterministic* identity that
depends on which batch source a folder was dropped into. An example is a
campaign-attributing source compared with the plain one. When an operator drops
a folder into the wrong source, the sequence is published with the wrong
identity. Re-dropping the folder into the right source then fails with
`SequenceCollisionError`, because the old sequence still holds the target run
directory.

The fix is to retire the old sequence. That means deleting its metadata-API
rows and moving its local run directory aside, which frees the directory for
reconversion. The motivating case was a 2026-10-05 XRFS sequence, and it needed
a hand-written one-off script. This page turns that script into a repeatable UI
operation with guards.

## Goals

- From a sequence uuid, find every local run directory and every API row that
  belongs to it, and show counts before anything is changed.
- Delete those rows children-first. Stop before touching any file if a delete
  fails.
- Move the run directory into `RUNS_SUPERSEDED` so that reconversion can claim
  the original path.
- Leave an append-only ledger of every row outcome.
- Keep the logic testable offline, with no Reflex and no network.
- Make the page reachable only on a station that opts in.

## Non-goals

- Deleting S3 objects. Raw data in S3 is left alone.
- Moving `ANALYSES/` directories. They are listed in the report and not moved.
- Re-dropping or reconverting the source folder. That remains an operator step.
- Authorization beyond the typed confirmation.
- Retiring sequences that did not come from batch conversion. This is not
  prevented, but it is not a design target either, so no guarantees are made
  for that case.

## Architecture

The page and its logic both live in the parent repo. The logic runs inside the
Reflex backend process on the batch host, which is the same machine as the
data root, so the run trees are local paths.

```
helao/ui/shared/retire.py          # pure logic: locate / inventory / retire (no Reflex import)
helao/ui/reflex/retire.py          # RetireState + retire_page() + configure(world_cfg, server_key)
helao/ui/reflex/app.py             # registration: SHELL_ROUTES, _nav, State pre-creation, configure, add_page
helao/core/tests/test_retire.py            # offline logic tests
helao/core/tests/test_reflex_retire.py     # render + handler tests
helao/core/tests/browser_check_retire.py   # manual Playwright check (not collected)
```

The batch-recovery gateway in the private deployment already implements the
delete and probe semantics this needs: `delete_entity`, `sequence_exists`,
`delete_sequence`, the 404 classifier, and the line-scan uuid readers. The
parent repo cannot import a private deployment, so `retire.py` re-implements
equivalent helpers. They must keep the same semantics: a 404 is reported as
absent, and every other error raises.

The metadata client is the shared lazy `AsyncOpenAPIClient` from
`helao/ui/shared/composition/api.py:get_client()`. Its generated methods are
**coroutines**. Its constructor fetches the OpenAPI spec synchronously, so it
is called inside the background event and never at import. `retire.py`
receives the client as a parameter and never calls `get_client` itself.

## Component contracts

### `helao/ui/shared/retire.py`

```python
Progress = Callable[[str, int, int], Awaitable[None]]   # (phase, done, total)

@dataclass(frozen=True)
class SeqLocation:
    run_tree: str          # "RUNS", "RUNS_SYNCED", "RUNS_FINISHED", ...
    rel_dir: str           # output dir relative to <root>/<run_tree>
    seq_yml: str           # absolute path of the *-seq.yml
    label: str             # sequence_label ("" if absent)
    name: str              # sequence_name
    campaign: str          # campaign_name

@dataclass
class Inventory:
    sequence_uuid: str
    locations: list[SeqLocation]
    local: dict[str, set[str]]        # {"EXPERIMENT"|"ACTION"|"PROCESS"|"ANALYSIS": uuids}
    in_api: dict[str, set[str]]       # subset of the union that read back 200
    sequence_in_api: bool
    sequence_label: str
    campaign_name: str
    api_only: bool                    # not found locally, present in API
    analysis_dirs: list[str]          # local ANALYSES/ dirs referencing these processes (report only)

@dataclass
class RetireResult:
    ok: bool
    ledger_path: str
    deleted: dict[str, int]
    already_absent: dict[str, int]
    persisting: dict[str, list[str]]  # EXPERIMENT/ACTION rows acknowledged but still readable
    moved: list[tuple[str, str]]      # (src, dst)
    error: str = ""

def locate(root: str, sequence_uuid: str) -> list[SeqLocation]: ...
async def inventory(client, root: str, sequence_uuid: str, progress: Progress) -> Inventory: ...
async def retire(client, root: str, inv: Inventory, progress: Progress, ledger_path: str) -> RetireResult: ...
def ledger_path_for(root: str, sequence_uuid: str, now: datetime) -> str:
    # <root>/STATES/retire_<uuid>_<UTC %Y%m%dT%H%M%SZ>.jsonl
```

**`locate`** scans `<root>/RUNS*/*/*/*/*-seq.yml` line by line and skips
`RUNS_SUPERSEDED`. It does not parse YAML, because a seq yml can be around
10 MB. A location matches only on an exact top-level line
`sequence_uuid: <uuid>`: the line has no indentation and the value, once
stripped, equals the uuid. A uuid that is a prefix of another uuid therefore
does not match. Nor does an indented `sequence_uuid:` inside an embedded
experiment block. The same scan reads `sequence_label:`, `sequence_name:` and
`campaign_name:` from top-level lines. On the batch host this covered about 50
seq ymls in about 70 ms.

**`inventory`** works as follows:
1. Collect local children: `<seq_dir>/*/*-exp.yml` gives `experiment_uuid`, and
   `<seq_dir>/*/*/*-act.yml` gives `action_uuid` and `process_uuid`, both read
   by line scan.
2. Union the processes with `read_processes_by_sequence`.
3. Collect analyses with `read_analysis_by_process` for each process.
4. Probe every row with `read_sequence` / `read_experiment` / `read_action` /
   `read_process`. A 404 means absent. **Any other error raises.** It is never
   counted as absent.
5. Fill in `analysis_dirs` by matching process uuids against
   `<root>/ANALYSES/`. These are reported only.

Outcomes:
- Not found locally and not in the API: the page says "nothing to retire".
- Not found locally but present in the API: `api_only=True`. The inventory comes
  from the API alone (processes and analyses), so experiments and actions are
  unknowable and the UI says so. Retire deletes what it can and moves nothing.

Progress phases are `"scan"` and `"probe"`, with `done`/`total` measured in rows.

**`retire`**:
1. **Re-verify.** Every `inv.locations[i].seq_yml` must still name
   `inv.sequence_uuid` on its top-level line. If any does not, refuse with no
   deletes. The move guards below (containment, destination absent, same
   device) are also pre-checked here, so a move that is bound to be refused
   fails before any row is deleted.
2. **Delete** in the order ANALYSIS → ACTION → PROCESS → EXPERIMENT → SEQUENCE.
   Concurrency within a type is bounded at 8 (`asyncio.Semaphore`), and each
   type finishes before the next starts. The sequence delete passes
   `delete_connected_processes=True`.
3. **Classify each delete outcome** as `True` (deleted), `False` (404, already
   absent) or a raise. A raise stops the retire before any file is moved and
   returns `ok=False` with the error.
4. **Handle a sequence delete that times out or returns 504** with a
   `read_sequence` existence probe. A 404 settles it as deleted. A 200 is a
   failure, and so is any other error.
5. **Ledger.** Append one jsonl line per row outcome
   (`{ts, entity_type, uuid, outcome, detail}`) as it happens, so a crash still
   leaves a record of what was done.
6. **Read-back.** PROCESS, ANALYSIS and SEQUENCE rows must all 404, or the
   retire fails before the move. EXPERIMENT and ACTION rows that still read 200
   go into `persisting` as a warning. This "acknowledged-but-persists"
   behaviour of the metadata API was observed on 2026-10-02.
7. **Move** each location: `<root>/<run_tree>/<rel_dir>` goes to
   `<root>/RUNS_SUPERSEDED/<YYYYMMDD>_retired/<run_tree>/<rel_dir>` via
   `os.rename`, after creating the parent directories (the safety guards are
   listed below). Each move is one progress step.

Progress phases are `"delete:<TYPE>"`, `"readback"` and `"move"`. `total` is
the row count plus the location count.

### `helao/ui/reflex/retire.py`

- `configure(world_cfg, server_key) -> None` reads `root` from the world config
  and `retire` / `retire_sources_root` from
  `servers[server_key].params`. It is guarded like `control.configure_control`:
  a malformed block yields "disabled", never an exception, because this runs at
  import time from `build_app`. The values are stored in module globals.
- `class RetireState(rx.State)` is a single concrete state. No mixin is needed
  because no panel shares it. It holds these vars:
  - `uuid_text`, `status`, `error`
  - `counts: list[list[str]]`, annotated so that `rx.foreach` builds
  - `label: str`, `confirm_text: str`, `armed: bool`, `busy: bool`
  - `progress: int` (0-100)
  - `ledger: str`, `warnings: list[str]`, `moved: list[str]`
  - `phase: str`, one of the UI states below
  - backend-only `_inv`, which holds the `Inventory`
- Handlers:
  - `set_uuid(v)`: sets the text, clears the inventory, counts and result, and disarms.
  - `set_confirm(v)`: recomputes `armed`.
  - `gather()` and `do_retire()`: `@rx.event(background=True)`, taking no
    arguments, bound to buttons only. Neither is bound to `rx.moment`, so the
    tick-argument rule does not apply.
- `retire_page()` returns the page body.
- The module-level `asyncio.Lock` (`_RETIRE_LOCK`) allows one retire per backend
  process. If it is already held, `do_retire` sets `error="a retire is already
  running"` and returns.
  `# ponytail: process-wide lock; fine for one batch-host backend.`

### `app.py` registration

The rules come from `helao/ui/reflex/CLAUDE.md`:
- Add `"/retire"` to `SHELL_ROUTES`. It is registered unconditionally, so config
  can make the page empty but never absent.
- Add `rx.link("Retire", href="/retire")` to `_nav`.
- Import `RetireState` at module scope and add it to the pre-creation asserts
  before `add_page`. A state class first touched inside `add_page`'s lazy
  callable never exists in a `--backend-only` process.
- Call `configure_retire(world_cfg, server_key)` next to the other `configure_*`
  calls.
- Add `application.add_page(lambda: _page("Retire sequence", retire_page(), "/retire"), route="/retire", title="HELAO retire")`.

## UI states

```
disabled                       (retire param not true; static note, no handlers wired)
idle --Gather--> gathering --ok--> gathered --confirm matches--> armed --Retire--> retiring --> done
                     |                 ^   \                        |                 |
                     +--error--> idle  |    +--uuid edited--> idle  +--uuid edited--> idle
                                       +--confirm mismatch---------+                  +--error--> failed
```

- **disabled**: the page renders "Retire is disabled on this station." and no
  input or button. Both background handlers also check the enabled flag
  server-side and return at once, so a crafted event does nothing.
- **gathering / retiring**: buttons are disabled. `status` shows the phase and
  `done/total`. During retire, `rx.progress(value=progress)` shows
  `round(100*done/total)`.
- **gathered**: shows a counts table (`type | local | in API`), the sequence row
  present/absent, the label and campaign, the run directories found, and the
  ANALYSES directories as an informational list. An API-only inventory says
  "experiments/actions unknowable from API alone".
- **armed**: requires a successful gather *and* `confirm_text == label`. If the
  label is empty, the full uuid must be typed instead.
- **done**: shows the ledger path, any warnings (persisting EXPERIMENT/ACTION
  uuids, as counts plus the first few), and the new run-dir locations.
- **failed**: shows the error, the ledger path, and "no files were moved"
  whenever the failure came before the move.

## Data flow

```
browser --gather()--> RetireState (bg) --get_client()--> retire.inventory(client, root, uuid, cb)
                                                             |-- locate(): <root>/RUNS*/.../*-seq.yml
                                                             |-- line-scan exp/act ymls
                                                             '-- read_* / read_processes_by_sequence / read_analysis_by_process
        <-- counts/status via `async with self` in cb --------'
browser --do_retire()--> _RETIRE_LOCK --> retire.retire(client, root, _inv, cb, ledger_path)
                                            |-- re-verify seq yml
                                            |-- delete_command x N (sem=8, typed order) --> ledger.jsonl
                                            |-- read-back probes
                                            '-- os.rename run dirs -> RUNS_SUPERSEDED/<date>_retired/
```

The progress callback follows `spectra_page._load_and_draw`: an inner
`async def _cb(phase, done, total)` that does `async with self:` and sets
`status` and `progress`. All API and file work runs outside the state lock.

## Error handling

| Situation | Behaviour |
|---|---|
| uuid input not a valid UUID | Gather refuses with "not a uuid"; no I/O |
| Batch conversion in flight for this sequence (`retire_sources_root` set) | Gather refuses with the matching state-file path |
| Not found locally and not in API | "nothing to retire"; stays idle |
| Found only in API | API-only inventory, with a warning shown; retire deletes rows and moves nothing |
| Probe returns non-404 error during gather | Gather fails with the error; no inventory, not armed |
| seq yml changed or vanished between gather and retire | Refuse with no deletes; tells the user to re-gather |
| Delete returns non-404 error (500, transport) | Stop at once; ledger keeps the rows done so far; no move; `failed` |
| Sequence delete times out or returns 504 | Probe `read_sequence`: 404 means deleted, anything else fails |
| PROCESS/ANALYSIS/SEQUENCE still reads 200 after delete | `failed` before the move |
| EXPERIMENT/ACTION still reads 200 after acknowledged delete | Warning ("acknowledged-but-persists"); retire continues |
| Move target exists | Refuse that move (no overwrite); `failed`; API rows are already gone, which the error states |
| Source and target on different devices | Refuse; never copy |
| Second retire while one runs | "a retire is already running"; nothing starts |
| Ledger write fails (OSError) | Stop before the next delete; `failed` |

## Safety guards

- A typed confirmation of the exact label (or the uuid) is required, after a
  successful gather in the same session. Any uuid edit disarms.
- Before deleting, every seq yml from the gather is re-checked for the exact
  anchored uuid line.
- A non-404 error is never treated as absent, whether it occurs in a probe, a
  delete, or a read-back.
- Every delete and read-back passes before any file moves.
- Move guards:
  - The resolved source (`os.path.realpath`) must sit strictly inside
    `<root>/<run_tree>`, at least one level below the run-tree root.
  - `run_tree` must match `RUNS*` and must not be `RUNS_SUPERSEDED`.
  - The destination must not exist.
  - `os.stat(src).st_dev` must equal the `st_dev` of the destination parent.
  - `os.rename` only; no `shutil.move` fallback.
- One retire per backend process.
- Only stations that set `retire: true` can run it, and the handlers enforce
  this server-side as well as in the page.
- The ledger is append-only and is never truncated. Its name carries a
  timestamp, so each run gets a fresh file.

## Config contract

These keys go under the Reflex server entry's `params:`:

| key | type | default | meaning |
|---|---|---|---|
| `retire` | bool | `false` | Enables the page. Anything other than literal `true` leaves it disabled. |
| `retire_sources_root` | str | unset | Batch sources root. When set, Gather refuses if any `<retire_sources_root>/*/processing/*.state.json` has a top-level `sequence_uuid` equal to the target, or a `sequence_output_dir` equal to a located `rel_dir`. A checkpoint still in phase `claimed` carries neither (both are null until conversion), so this check cannot see a conversion that has only been claimed. That gap is accepted. When unset, this check is skipped. |

The data root is the world config's top-level `root:`. The keys are set only in
a private deployment's batch-host UI config, as a separate commit in that repo.
No tracked parent-repo config sets them. `goldenreflex` stays disabled, and the
browser check enables the page through a temporary config.

## Testing

### `helao/core/tests/test_retire.py` (offline pytest)

The tests use a fake async client: dict-backed rows per entity type, with
per-uuid injectable outcomes (`404`, `500`, `timeout`, `504`) and an
"ack-but-persists" set for EXPERIMENT/ACTION. It raises `RuntimeError` text in
the real client's format (`"... failed: 404 ..."`) so that the 404 classifier
is exercised for real. Run trees are built under `tmp_path`.

| Test | Mutation it must catch |
|---|---|
| exact-match locate: uuid that is a prefix of another does not match | Dropping the anchor or the strip-equality check |
| an indented `sequence_uuid:` in an embedded exp creates no location | Allowing leading whitespace |
| `RUNS_SUPERSEDED` is skipped | Removing the exclusion |
| inventory counts per type, local versus API, including API-only processes | Dropping the `read_processes_by_sequence` union |
| a 500 during a probe raises and does not count as absent | Folding non-404 into `False` |
| delete order is ANALYSIS→ACTION→PROCESS→EXPERIMENT→SEQUENCE (fake records the call order) | Reordering the types |
| a 500 on an ACTION delete leaves no SEQUENCE delete and the run dir still in place | Moving before checking, or continuing after an error |
| sequence 504 followed by a probe 404 counts as success; probe 200 counts as failure | Skipping the probe, or trusting the 504 |
| persisting EXPERIMENT/ACTION goes to `persisting` with `ok=True` | Treating it as a failure (or the reverse for PROCESS) |
| a persisting PROCESS gives `ok=False` and no move | Read-back skipping PROCESS |
| the ledger has one line per row and survives a mid-run failure | Buffering writes until the end |
| the run dir lands at `RUNS_SUPERSEDED/<date>_retired/<tree>/<rel>` | Wrong target layout |
| changing the seq yml uuid between inventory and retire refuses with zero deletes | Dropping the re-verify |
| source equal to the run-tree root is refused, and so is an existing destination | Dropping the guards |

Every test must be mutation-checked: break the guarded line by hand, confirm
the test fails, then restore it. A test that still passes against broken logic
does not count.

### `helao/core/tests/test_reflex_retire.py`

- Use the `reflex_registration` fixture and render `build_page()` for `/retire`,
  which catches event-binding errors that only show at render.
- Render the page with `retire` unset and assert the disabled note is present
  and the Gather button is absent. Then call `gather.fn` on a fake state and
  assert it returns without I/O.
- Drive background handlers through `.fn` on a fake state with
  `__aenter__`/`__aexit__` (the `test_reflex_composition.py` pattern) and a
  monkeypatched `get_client` returning the fake client. Assert:
  - gather fills `counts`
  - an editing `set_uuid` clears `_inv` and disarms
  - the confirm text must equal the label (or the uuid when the label is empty)
    to arm
  - `do_retire` while the lock is held reports busy
  - an in-flight state file under `retire_sources_root` blocks gather
- Assert `RetireState` is created before `add_page`, by checking that its
  handlers are registered after importing `app` (the same check the other pages
  have).

### `helao/core/tests/browser_check_retire.py` (manual, described only)

Launches `goldenreflex` with a temporary config that sets `retire: true` and
points `root` at a `tmp` run tree, with `get_client` patched to the fake client.
Playwright then checks the following:
- Gather shows the counts.
- Retire stays disabled until the label is typed.
- The progress bar advances.
- The result panel shows the ledger path and the moved directory.
- Editing the uuid disarms.

It is not collected by `run_tests.py`.

## Resolved questions

Settled during spec review on 2026-10-06, by evidence on the batch host:

1. **`delete_command` accepts `ANALYSIS`.** A 2026-10-02 cleanup deleted
   ANALYSIS rows through it and they read back 404, so analyses stay in the
   delete order and in the must-404 read-back set.
2. **`read_processes_by_sequence` returns nothing once a retire has run.**
   Probed on a retired sequence it returned 0 processes, where the live
   reconversion of the same source returns 296. Because processes are deleted
   before the sequence row, the API cannot rediscover them on a retry. **A
   retry therefore relies on the local run tree**, which is why the move is the
   last step and is skipped whenever any delete fails. An API-only inventory
   (no local tree found) shows that experiments and actions cannot be
   enumerated and that processes may already be gone.
3. **A move that fails after the deletes ends in the `failed` state.** That
   state names the un-moved directory and writes a `move_failed` ledger line,
   and the directory is cleaned up by hand. The pre-move guards make this
   reachable only through a race or an OS error.

## Addendum 2026-10-06: synced-or-override guard

On an instrument station a record is written once under `RUNS` and stays there
for life, while its run state lives in per-server journals. `locate` therefore
finds sequences that are still running or still uploading, and retiring one
races the orchestrator or the syncer. The batch host is unaffected: its
sequences are finished when written.

- **Synced predicate.** `is_synced(loc)` is
  `run_state._prg_is_complete(<seq yml>.prg)`, reused rather than
  re-implemented. A missing `.prg` is unsynced.
- **`Inventory.synced`** is true only when there is at least one location and
  every location is synced. An API-only inventory is `synced=False`, because
  the sequence may be running on another station.
- **`retire(..., allow_unsynced=False)`** recomputes `is_synced` per location in
  the re-verify step, after the ledger `start` line and before any delete. An
  unsynced location, or no location at all, is refused with zero deletes: the
  error contains `not synced` and ends with `; no files were moved`. The
  `start` line's detail records `allow_unsynced` and the per-location flags.
- **Page.** When the gathered sequence is not synced, the page adds a warning
  and a second input; Retire arms only when the label (or uuid) matches *and*
  the second input reads `UNSYNCED`. Synced sequences see neither. `do_retire`
  passes `allow_unsynced` only when the sequence is unsynced and the override
  is typed.
