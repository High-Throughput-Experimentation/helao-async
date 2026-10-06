# Sequence Retire Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `/retire` Reflex page that, from a sequence uuid, inventories a published sequence's local run directories and metadata-API rows, deletes the rows children-first under guards, ledgers every outcome, and moves the run directories into `RUNS_SUPERSEDED` so that reconversion can reclaim the path.

**Architecture:** All logic lives in a Reflex-free module, `helao/ui/shared/retire.py` (locate, inventory, retire, ledger, guards). It takes the async metadata client as a parameter and is tested offline against a fake client. A thin Reflex page, `helao/ui/reflex/retire.py`, wraps it in one `RetireState` with two background handlers. The page is registered unconditionally in `app.py` and enabled per station by `retire: true` in the UI server's params.

**Tech Stack:** Python 3.14, Reflex 0.9.x, `helao.helpers.openapi_client.AsyncOpenAPIClient` (via `helao/ui/shared/composition/api.get_client()`), pytest, Playwright (manual check only).

**Spec:** `docs/superpowers/specs/2026-10-06-sequence-retire-page-design.md`. Read it first; this plan argues from it.

## Global Constraints

- **The parent repo is a PUBLIC remote.** Never name a private deployment, a private hostname, or a private path in code, comments, tests, commit messages, or this plan's deliverables. Say "a private deployment" and "the batch host".
- Run everything in the conda env `helao` from the repo root. Tests: `PYTHONPATH=. conda run -n helao python -m pytest <file> -q`, one file per pytest process (collecting several files in one session hangs).
- `black` (default settings, line length 88) on every changed `.py` file, as the last step before a commit. Never `black` anything under `helao/core/tests/fixtures/sweeper_calibration/`.
- **Colours.** Never hardcode a colour outside `helao/ui/shared/palette.py`; the AST sweep in `helao/core/tests/test_palette.py` fails the build otherwise. On the Reflex side that means:
  - Allowed: Tailwind utility strings in `class_name=` (`"text-red-600"`, `"text-amber-700"`), and the palette helpers (`palette.reflex_muted_text_class()`, `palette.reflex_page_class(route)`).
  - Forbidden: hex, `rgb(`, `color:` declarations, a bare CSS colour name in any keyword value (this includes `color_scheme="red"`, since the sweep flags a bare name that is not hyphen-flanked), and `text-slate-500` anywhere in the Reflex stack (use `reflex_muted_text_class()`).
- Logging goes through `helao.helpers.helao_logging`: `LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER` (the pattern in `composition/api.py`). Never `logging.getLogger`.
- **Escalate, don't choose.** An implementer who meets a decision this plan does not settle stops and reports it. This applies above all to anything that changes which rows are deleted, which directories move, or in what order.
- **No outward-facing actions by implementers.** No `git add`, `commit`, `push` or `stash`, and no writes outside the repo working tree or a pytest `tmp_path`. Use `git -C <repo>` for any read-only git call. The commit steps below are carried out by the **main session after review**, not by implementers.
- **Tests must be falsifiable.** Every `test_retire.py` test has a docstring line `Mutation: <what breaks it>`. Before reporting a task done, the implementer applies that mutation by hand, confirms the test fails, restores the code, and lists each mutation and its observed failure in the task report. A test that still passes against the mutation does not count.
- The metadata client's generated methods are coroutines. `AsyncOpenAPIClient`'s constructor fetches the spec synchronously, so `get_client()` is called only inside a background handler. `helao/ui/shared/retire.py` never calls `get_client` and never imports Reflex.

## Facts from the code that the tasks rely on

These are derived from `helao/helpers/openapi_client.py` and the served OpenAPI spec. They are not guesses.

- **HTTP errors** come from `_handle_response` as `RuntimeError("API call to '<op>' (<METHOD> <url>) failed: <status> - Details: ...")`, raised `from` an `httpx.HTTPStatusError`.
- **Transport errors**, timeouts included, come from `_raw_request` as `RuntimeError("Request failed for operation '<op>' to <url>: <exc>")`. This is raised inside `except httpx.RequestError` with no `from`, so the `httpx.TimeoutException` is reachable as `exc.__context__`. The client's per-request timeout is 30 s.
- **404 classifier** (the same semantics as the private gateway): `"failed: 404" in str(exc) or "Could not find" in str(exc)`. Nothing else counts as absent.
- **Timeout-or-504 classifier**: `"failed: 504" in str(exc)`, or an `httpx.TimeoutException` anywhere on the `__cause__`/`__context__` chain.
- **Operations and their keyword arguments:**
  - `read_sequence(sequence_uuid=)`
  - `read_experiment(experiment_uuid=)`
  - `read_action(action_uuid=)`
  - `read_process(process_uuid=)`
  - `read_analysis(analysis_uuid=)`
  - `read_processes_by_sequence(sequence_uuid=)` returns a `list` of process dicts (as `uvvis.records_for_plate` consumes it)
  - `read_analysis_by_process(process_uuid=)` returns a `list` of analysis dicts carrying `analysis_uuid`
  - `delete_command(entity_type=, primary_id=, delete_connected_processes=)`

  A missing operation is a `getattr` miss. Raise a `RuntimeError` that names it, rather than an `AttributeError`.
- **Run-tree layout:** `<root>/<RUNS*>/<yy.ww>/<mmdd>/<seqdir>/<ts>-seq.yml`. Experiments are at `<seqdir>/*/*-exp.yml` with a top-level `experiment_uuid:`. Actions are at `<seqdir>/*/*/*-act.yml` with top-level `action_uuid:` and `process_uuid:`, and the `process_uuid` may be `null`.
- **ANALYSES layout:** `<root>/ANALYSES/<yyyy>/<mmdd>/<HHMMSS>__<name>[__<suffix>]/` holding yml/json files (see `helao/core/drivers/data/analysis_layout.py`).
- **Routes and tints:** `test_palette.py::test_reflex_page_tints_cover_the_shell_routes` requires `set(REFLEX_PAGE_TINTS) == set(SHELL_ROUTES)` with every tint distinct, so `/retire` needs a new tint in the same task that adds the route. No test hardcodes the route list or the nav contents: `test_reflex_routes_e2e.py`, `test_reflex_control.py` and `helao/hexagon/tests/test_reflex_host.py` iterate `SHELL_ROUTES`, so they cover `/retire` without edits.

## Review Focus

1. **The same uuid in two run trees** (for example a copy in `RUNS_SYNCED` and one in `RUNS_FINISHED`): both locations are re-verified, pre-checked and moved, and a destination clash on either one refuses the retire before any delete. Owned by Task 3 (`test_two_locations_are_both_moved`, `test_second_location_dest_clash_refuses_before_deletes`).
2. **A retry after a partial failure** (rows already deleted, then a persisting PROCESS or a failed move): the operator re-gathers. The local tree is found again, the rows read 404 (`in_api` is empty), and the retire moves the directory with zero deletes. Owned by Task 3 (`test_retry_after_failure_moves_with_no_deletes`).
3. **The ledger cannot be written**, or `<root>/STATES` does not exist. A missing directory is created. An unwritable ledger fails the retire *before the first delete*, because the ledger is opened and a `start` line is written before any API call. Owned by Task 3 (`test_unwritable_ledger_fails_before_any_delete`, `test_ledger_dir_is_created`).
4. **A uuid typed with surrounding whitespace, in uppercase, or in braces** is normalised through `uuid.UUID(...)` to canonical lowercase before any I/O. Otherwise the anchored line match finds nothing and the page says "nothing to retire" for a sequence that exists. Owned by Task 4 (`test_gather_normalises_the_uuid`).
5. **Yml values of `null`, `None` or empty** (an action with `process_uuid: null`) are skipped and are never recorded or deleted as a uuid. Owned by Task 2 (`test_null_uuid_values_are_skipped`).

---

## File Structure

| File | Responsibility |
|---|---|
| `helao/ui/shared/retire.py` (create) | Pure logic: dataclasses, line-scan readers, `locate`, `in_flight`, `ledger_path_for`, the 404/timeout classifiers, `inventory`, `retire`. No Reflex. |
| `helao/core/tests/retire_fakes.py` (create) | `FakeMetadataClient` and the `make_run_tree` builder, shared by both test files. Not collected (no `test_` prefix). |
| `helao/core/tests/test_retire.py` (create) | Offline logic tests (Tasks 1–3). |
| `helao/ui/reflex/retire.py` (create) | `configure_retire`, `RetireState`, `retire_page`. |
| `helao/ui/reflex/app.py` (modify) | Imports, `SHELL_ROUTES`, `_nav`, the pre-creation assert, the `configure_retire` call, `add_page`. |
| `helao/ui/shared/palette.py` (modify) | `TW["orange-50"]` and the `REFLEX_PAGE_TINTS["/retire"]` entry. |
| `helao/core/tests/test_palette.py` (modify) | The canonical shade, the tint text rows, the slate-500 row, and the failing-set test. |
| `helao/core/tests/test_reflex_retire.py` (create) | Render and handler tests (Task 4). |
| `helao/core/tests/test_reflex_routes_e2e.py` (modify) | `/retire` registration and handler test. |
| `helao/ui/reflex/CLAUDE.md` (modify) | One bullet on `/retire`. |
| `helao/core/tests/browser_check_retire.py` (create) | Manual Playwright check (Task 5). |

---

### Task 1: `retire.py` skeleton, line scans, `locate`, `in_flight`, `ledger_path_for`

**Files:**
- Create: `helao/ui/shared/retire.py`
- Create: `helao/core/tests/retire_fakes.py` (the `make_run_tree` part only)
- Test: `helao/core/tests/test_retire.py`

**Interfaces:**
- Produces, in `helao/ui/shared/retire.py`:
  - `Progress`, `SeqLocation`, `Inventory`, `RetireResult`, exactly as in the spec's "Component contracts". `Inventory` also gets the property `nothing_to_retire -> bool`, which is true when there are no locations, `sequence_in_api` is false, and every `in_api` set is empty.
  - `ENTITY_TYPES = ("EXPERIMENT", "ACTION", "PROCESS", "ANALYSIS")`
  - `DELETE_ORDER = ("ANALYSIS", "ACTION", "PROCESS", "EXPERIMENT", "SEQUENCE")`
  - `MUST_404 = frozenset({"PROCESS", "ANALYSIS", "SEQUENCE"})`
  - `SUPERSEDED = "RUNS_SUPERSEDED"`
  - `top_level(path: str, keys: tuple[str, ...]) -> dict[str, str]`: a line scan. It takes the first occurrence of each key on an unindented `key: value` line, with the value `.strip()`ped. It stops once every key is found and never parses YAML. It drops values in `{"", "null", "None", "~"}`.
  - `names_uuid(seq_yml: str, sequence_uuid: str) -> bool`: `top_level(seq_yml, ("sequence_uuid",)).get("sequence_uuid") == sequence_uuid`. An unreadable file (`OSError`) returns `False`.
  - `locate(root: str, sequence_uuid: str) -> list[SeqLocation]`: globs `<root>/RUNS*/*/*/*/*-seq.yml` and skips `run_tree == SUPERSEDED`. `rel_dir` is `os.path.relpath(seq_dir, <root>/<run_tree>)` with `/` separators. Results are sorted by `(run_tree, rel_dir)`.
  - `in_flight(sources_root: str, sequence_uuid: str, rel_dirs: list[str]) -> str | None`: the first `<sources_root>/*/processing/*.state.json` whose top-level `sequence_uuid == sequence_uuid`, or whose `sequence_output_dir`, normalised with `.replace("\\", "/").strip("/")`, is in `rel_dirs`. A file that is not valid JSON or not a dict is skipped with a `LOGGER.warning`.
  - `ledger_path_for(root: str, sequence_uuid: str, now: datetime) -> str`: `<root>/STATES/retire_<uuid>_<now in UTC, %Y%m%dT%H%M%SZ>.jsonl`.
- Produces, in `helao/core/tests/retire_fakes.py`: `make_run_tree(root, run_tree, rel_dir, *, sequence_uuid, label="", name="SEQ", campaign="", experiments: dict[str, list[tuple[str, str | None]]] = {}) -> str`. It writes a seq yml (with an *indented* embedded `  sequence_uuid: <other>` block ahead of the top-level line, so the anchor matters), one exp dir per experiment, and one act dir per `(action_uuid, process_uuid)`. It returns the seq-dir path.

- [ ] **Step 1: Write the failing tests** in `test_retire.py`. Each docstring carries its `Mutation:` line.
  - `test_prefix_uuid_does_not_match`: one tree for `U`, one for `U + "0"` (a longer uuid that `U` is a prefix of). `locate(root, U)` returns only `U`'s location. Mutation: `startswith`/`in` instead of strip-equality.
  - `test_indented_sequence_uuid_creates_no_location`: a seq yml whose only `U` line is `  sequence_uuid: U`. Result is `[]`. Mutation: `line.lstrip()` before matching.
  - `test_runs_superseded_is_skipped`: the same tree under `RUNS_SUPERSEDED/20261005_retired/RUNS/...` and under `RUNS_FINISHED`. Exactly one location, with `run_tree == "RUNS_FINISHED"`. Mutation: removing the exclusion.
  - `test_locate_reads_label_name_campaign`: the fields are populated, and `campaign == ""` when the line is absent. Mutation: reading the indented line, or the first occurrence anywhere.
  - `test_in_flight_matches_uuid_or_output_dir`: four state files: one with a matching uuid, one with a matching backslashed `sequence_output_dir`, one claimed (both `null`), and one malformed. The first two return their path, each in isolation. Mutation: dropping the `sequence_output_dir` comparison, or dropping the backslash normalisation.
  - `test_ledger_path_for_is_utc_stamped`: `datetime(2026, 10, 6, 1, 2, 3, tzinfo=timezone(timedelta(hours=-7)))` gives `.../STATES/retire_<u>_20261006T080203Z.jsonl`. Mutation: dropping `astimezone(utc)`.

- [ ] **Step 2: Run, and expect `ModuleNotFoundError`.** `PYTHONPATH=. conda run -n helao python -m pytest helao/core/tests/test_retire.py -q`

- [ ] **Step 3: Implement** the Task 1 interface in `helao/ui/shared/retire.py` (with a module docstring that points at the spec) and `make_run_tree` in `retire_fakes.py`.

- [ ] **Step 4: Run, and expect all to PASS.** Then do the mutation check for each test and record the results.

- [ ] **Step 5: Commit (main session, after review).** Run `black` on the three files, then:
  ```bash
  git -C <repo> add helao/ui/shared/retire.py helao/core/tests/retire_fakes.py helao/core/tests/test_retire.py
  git -C <repo> commit -m "feat(retire): locate sequences by anchored seq-yml line scan"
  ```

---

### Task 2: `inventory`, the API probes, and the fake client

**Files:**
- Modify: `helao/ui/shared/retire.py`
- Modify: `helao/core/tests/retire_fakes.py` (add `FakeMetadataClient`)
- Test: `helao/core/tests/test_retire.py`

**Interfaces:**
- Consumes: Task 1.
- Produces, in `retire.py`:
  - `is_not_found(exc: BaseException) -> bool` and `is_timeout_or_504(exc: BaseException) -> bool`, exactly as in "Facts from the code".
  - `READ_OPS: dict[str, tuple[str, str]]`, mapping entity type to `(operation, kwarg)` for `SEQUENCE`/`EXPERIMENT`/`ACTION`/`PROCESS`/`ANALYSIS`.
  - `async exists(client, entity_type: str, uuid: str) -> bool`: `True` when the read returns, `False` on `is_not_found`, and anything else is re-raised as `RuntimeError(f"probe of {entity_type} {uuid} failed: {exc!r}")` chained `from exc`.
  - `async inventory(client, root, sequence_uuid, progress) -> Inventory`, following spec steps 1–5:
    - `local` holds all four keys, and `local["ANALYSIS"]` is always empty.
    - `read_processes_by_sequence` treats a 404 as `[]`. A non-list response raises `RuntimeError("read_processes_by_sequence returned <type>; expected a list")`.
    - `read_analysis_by_process` treats a 404 as `[]`.
    - Probing is bounded by `asyncio.Semaphore(8)`, and `progress("probe", done, total)` is called once per row.
    - `progress("scan", n, n)` is called once after the local scan.
    - When there are locations, `sequence_label`/`campaign_name` come from the first location. Otherwise they come from the `read_sequence` body (`sequence_label`, `campaign_name`, default `""`).
    - `analysis_dirs` is the sorted list of `<root>/ANALYSES/*/*/*` directories in which any file directly inside contains any known process or analysis uuid as a substring. A missing `ANALYSES` directory gives `[]`.
- Produces, in `retire_fakes.py`: `FakeMetadataClient(rows: dict[str, set[str]], *, seq_processes: dict[str, list[str]] = {}, analyses: dict[str, list[str]] = {})`, plus these attributes:
  - `fail: dict[tuple[str, str], str]`, keyed `(op_kind, uuid)` where `op_kind` is `"read"` or `"delete"`, with the value `"404"`, `"500"`, `"504"` or `"timeout"`.
  - `persist: set[str]`: uuids whose delete is acknowledged but whose row stays.
  - `calls: list[tuple[str, str, str]]`: `("delete", entity_type, uuid)` in call order.

  It exposes every operation in "Facts from the code" with the real keyword names. An absent row raises a 404. Status errors are raised as `RuntimeError(f"API call to '{op}' (GET https://fake/api/x) failed: {code} - Details: {{'detail': '...'}}")`. A timeout is raised as `RuntimeError(f"Request failed for operation '{op}' to https://fake: ")` *inside* `except httpx.ReadTimeout`, so that `__context__` is set the way the real client sets it.

- [ ] **Step 1: Write the failing tests.**
  - `test_classifiers_read_the_real_client_error_format`: build `c = object.__new__(AsyncOpenAPIClient)`. Then `c._handle_response("read_sequence", httpx.Response(404, json={"detail": "x"}, request=httpx.Request("GET", "https://h/api/sequence/u")))` raises a `RuntimeError` for which `is_not_found` is true. The same call with a 500 gives `is_not_found` false and `is_timeout_or_504` false. With a 504, `is_timeout_or_504` is true. Mutation: matching `"404"` anywhere (which a uuid containing `404` would trip; include such a uuid in the URL), or folding 5xx into not-found.
  - `test_inventory_counts_local_and_api_including_api_only_processes`: a local tree with 2 experiments and 3 actions (3 processes). The API holds all of them plus one extra process, `P_api`, reachable only through `read_processes_by_sequence`, and one analysis on `P_api`. Assert `local["PROCESS"]` has 3 entries, `in_api["PROCESS"]` has 4, `in_api["ANALYSIS"]` has 1, and `sequence_in_api` is true. Mutation: dropping the `read_processes_by_sequence` union.
  - `test_probe_500_raises_and_is_not_counted_absent`: `fail[("read", A1)] = "500"`, and `inventory` raises `RuntimeError`. Mutation: `except Exception: return False` in `exists`.
  - `test_api_only_inventory`: no tree, the sequence and a process in the API. `api_only` is true, `local` is all empty, and `sequence_label` comes from the API body. Mutation: setting `api_only` from `in_api` alone.
  - `test_nothing_to_retire`: no tree and an empty API, so `nothing_to_retire` is true. Mutation: a property that ignores `sequence_in_api`.
  - `test_null_uuid_values_are_skipped` (Review Focus 5): an act yml with `process_uuid: null`. The string `"null"` is in no set, and no read is issued for it. Mutation: removing the null-value filter in `top_level`.
  - `test_analysis_dirs_are_reported_not_required`: a file under `ANALYSES/2026/1005/120000__x/` that mentions a process uuid appears in `analysis_dirs`. With no `ANALYSES` directory the result is `[]` and nothing raises. Mutation: globbing one level too shallow.

- [ ] **Step 2: Run, and expect FAIL** (`AttributeError`/`ImportError` on the new names).

- [ ] **Step 3: Implement** the Task 2 interface.

- [ ] **Step 4: Run all of `test_retire.py`, and expect PASS.** Then do the mutation checks.

- [ ] **Step 5: Commit (main session, after review).** `black`, then commit with `feat(retire): inventory local and API rows, 404-only absence`.

---

### Task 3: `retire`: re-verify, deletes, ledger, read-back, move guards

**Files:**
- Modify: `helao/ui/shared/retire.py`
- Test: `helao/core/tests/test_retire.py`

**Interfaces:**
- Consumes: Tasks 1 and 2.
- Produces: `async retire(client, root, inv: Inventory, progress, ledger_path: str) -> RetireResult`. **It never raises.** Every failure is `ok=False` with `error` set.

Algorithm (the spec fixes the order; these are the parts the spec leaves open, settled here):

1. **Ledger first.** `os.makedirs(dirname(ledger_path), exist_ok=True)`. Write a `start` line: `{ts, entity_type: "SEQUENCE", uuid, outcome: "start", detail: <counts>}`. An `OSError` here returns `ok=False`, with no API call made. Each later line is written by `open(path, "a")`, `write(json + "\n")` and `flush()`, one open per line. An `OSError` on any line sets a stop flag; no further delete starts, and the result is `ok=False`. Use the outcomes `deleted`, `absent`, `error`, `persists`, `moved` and `move_failed`. Directory lines use `entity_type: "DIR"`, with `uuid` set to the src path and `detail` to the dst path.
2. **Re-verify.** `names_uuid(loc.seq_yml, inv.sequence_uuid)` must hold for every location. If it does not, return an error containing `"re-gather"`, with no deletes.
3. **Pre-check moves**, using `date = datetime.now(timezone.utc).strftime("%Y%m%d")`, `src = <root>/<run_tree>/<rel_dir>` and `dst = <root>/RUNS_SUPERSEDED/<date>_retired/<run_tree>/<rel_dir>`. Refuse the move unless all of these hold:
   - `fnmatch(run_tree, "RUNS*")` and `run_tree != SUPERSEDED`
   - `realpath(src)` sits strictly under `realpath(<root>/<run_tree>) + os.sep`
   - `dst` does not exist
   - `_st_dev(src) == _st_dev(nearest existing ancestor of dirname(dst))`

   `_st_dev(path) -> int` is a module-level helper so that tests can monkeypatch it.
4. **Delete.** Rows are `inv.in_api[t]` for each type in `DELETE_ORDER`, plus the sequence when `inv.sequence_in_api`. Concurrency within a type is bounded by `asyncio.Semaphore(8)`, and each type completes (`gather(..., return_exceptions=True)`) before the next one starts. Each task checks the stop flag after acquiring the semaphore. The sequence delete passes `delete_connected_processes=True`. Classify each outcome:
   - a return is `deleted`
   - `is_not_found` is `absent`
   - an exception on the SEQUENCE delete that passes `is_timeout_or_504` gets `exists(client, "SEQUENCE", uuid)`: `False` is `deleted` with detail `"confirmed absent after timeout/504"`, while `True` or a raise is an error
   - anything else is `error`

   Any error sets the stop flag and ends the run after the current type, with `ok=False`. `done` counts every finished delete, and the call is `progress(f"delete:{t}", done, total)`.
5. **Read-back** every row whose outcome was `deleted`, through `exists` with the semaphore. Call `progress("readback", done, total)` once. A row still present in `MUST_404` fails the retire before the move. A row still present that is `EXPERIMENT` or `ACTION` goes into `persisting[t]` and gets a `persists` ledger line. A probe that raises fails the retire.
6. **Move** each location in order. Call `os.makedirs(dirname(dst))`, re-check the device on that parent, then `os.rename(src, dst)` (no `shutil` fallback). Append to `moved`, write a `moved` line, and call `progress("move", done, total)`. An `OSError`, or a guard failure at move time, writes a `move_failed` line and returns `ok=False`. The error names the un-moved src and says "API rows are already deleted".
7. Error strings for any failure before the move end with `"; no files were moved"`.

`total = sum(len(in_api[t])) + int(sequence_in_api) + len(locations)`.

- [ ] **Step 1: Write the failing tests**, using `FakeMetadataClient` and `make_run_tree`. Read the ledger lines back with `json.loads`.
  - `test_delete_order_is_children_first`: the types in `calls` appear in `DELETE_ORDER` order, with no interleaving. Mutation: swapping two entries of `DELETE_ORDER`, or starting all the types at once.
  - `test_action_500_stops_before_sequence_and_move`: `fail[("delete", A1)] = "500"` gives no `SEQUENCE`/`PROCESS`/`EXPERIMENT` call, leaves the run dir in place, `ok=False`, and `"no files were moved"` in `error`. Mutation: `continue` instead of stop, or moving before checking.
  - `test_sequence_504_then_probe_404_succeeds`: `fail[("delete", S)] = "504"`, and the fake removes the row anyway. Result `ok=True`, with the ledger line detail `"confirmed absent after timeout/504"`. Mutation: trusting the 504 as an error without probing.
  - `test_sequence_timeout_then_probe_200_fails`: a timeout with the row still present gives `ok=False` and no move. Mutation: treating any timeout as success.
  - `test_persisting_experiment_action_warn_but_succeed`: `persist = {E1, A1}` gives `ok=True`, `persisting == {"EXPERIMENT": [E1], "ACTION": [A1]}`, and the directory moved. Mutation: putting EXPERIMENT in `MUST_404`.
  - `test_persisting_process_fails_before_move`: `persist = {P1}` gives `ok=False` and the dir in place. Mutation: removing PROCESS from `MUST_404`.
  - `test_ledger_has_one_line_per_row_and_survives_failure`: a 500 on the second ACTION of three, with the semaphore set to 1 via monkeypatched `retire.DELETE_CONCURRENCY = 1`. (Expose the 8 as a `DELETE_CONCURRENCY` module constant.) The ledger holds the `start` line, plus a line for every ANALYSIS, a line for every ACTION attempted, and the `error` line. Read it *before* `retire` returns by making the fake's failing delete assert that the file already holds the earlier lines. Mutation: buffering lines and writing them at the end.
  - `test_run_dir_lands_in_superseded_layout`: the dst is `<root>/RUNS_SUPERSEDED/<today UTC>_retired/RUNS_FINISHED/<rel_dir>`, and the src is gone. Mutation: dropping `<run_tree>` from the dst.
  - `test_changed_seq_yml_refuses_with_zero_deletes`: rewrite the top-level uuid line after `inventory`. Result `calls == []` and `"re-gather"` in the error. Mutation: removing the re-verify.
  - `test_source_equal_to_run_tree_root_is_refused`: an `Inventory` with `rel_dir="."`. No deletes and `ok=False`. Mutation: `>=` containment instead of strict.
  - `test_existing_destination_is_refused_before_deletes`: pre-create the dst. `calls == []`. Mutation: deferring the dst check to move time.
  - `test_cross_device_is_refused_before_deletes`: monkeypatch `retire._st_dev` so the src and the dst parent differ. `calls == []`. Mutation: removing the device comparison.
  - `test_two_locations_are_both_moved` (Review Focus 1): the uuid sits under both `RUNS_SYNCED` and `RUNS_FINISHED`, and both move. Mutation: moving `locations[0]` only.
  - `test_second_location_dest_clash_refuses_before_deletes` (Review Focus 1): `calls == []`. Mutation: pre-checking only the first location.
  - `test_retry_after_failure_moves_with_no_deletes` (Review Focus 2): first run with `persist = {P1}` gives `ok=False`. Then clear `persist`, remove P1 from the fake, re-run `inventory` (`in_api` is empty everywhere) and then `retire`. The second run has no `delete` calls, `ok=True`, and the dir moved. Mutation: making `retire` refuse an inventory with no API rows.
  - `test_unwritable_ledger_fails_before_any_delete` (Review Focus 3): put `ledger_path` inside a directory that is a regular file. `calls == []` and `ok=False`. Mutation: opening the ledger lazily on the first outcome.
  - `test_ledger_dir_is_created` (Review Focus 3): with no `<root>/STATES`, the ledger exists afterwards. Mutation: removing the `makedirs`.

- [ ] **Step 2: Run, and expect FAIL.**
- [ ] **Step 3: Implement `retire`** and its helpers.
- [ ] **Step 4: Run all of `test_retire.py`, and expect PASS.** Do the mutation checks, and report each mutation with its failing assertion.
- [ ] **Step 5: Commit (main session, after review).** `black`, then commit with `feat(retire): guarded children-first delete, ledger, read-back and move`.

---

### Task 4: The Reflex page, its registration, the tint, and the tests

**Files:**
- Create: `helao/ui/reflex/retire.py`
- Modify: `helao/ui/reflex/app.py` (imports near line 69, `SHELL_ROUTES` at 83–94, `_nav` at 301–319, the asserts at 471–474, the `configure_*` calls at 477–482, and `add_page` after line 579)
- Modify: `helao/ui/shared/palette.py` (`TW` and `REFLEX_PAGE_TINTS`)
- Modify: `helao/core/tests/test_palette.py`
- Modify: `helao/core/tests/test_reflex_routes_e2e.py`
- Modify: `helao/ui/reflex/CLAUDE.md`
- Test: `helao/core/tests/test_reflex_retire.py`

**Interfaces:**
- Consumes: `helao.ui.shared.retire`, imported as `from helao.ui.shared import retire as retire_logic` and called as `retire_logic.locate(...)` etc., so that tests can monkeypatch through `rr.retire_logic`. It uses `locate`, `in_flight`, `inventory`, `retire`, `ledger_path_for`, `Inventory` and `ENTITY_TYPES`. It also consumes `helao.ui.shared.composition.api`, imported as `api` and called as `api.get_client()`.
- Produces, in `helao/ui/reflex/retire.py`:
  - `_CONFIG: dict` with the keys `enabled: bool`, `root: str` and `sources_root: str`.
  - `configure_retire(world_cfg: dict, server_key: str) -> None`. It uses the guard pattern of `control.configure_control` (an `isinstance` check at every level, never raising). `enabled` holds only when `params.get("retire") is True` **and** the world config's `root` is a non-empty `str`. `sources_root` is `params.get("retire_sources_root")` when it is a non-empty `str`, and `""` otherwise.
  - `retire_enabled() -> bool`.
  - `_RETIRE_LOCK = asyncio.Lock()`, with the spec's `# ponytail:` comment.
  - `class RetireState(rx.State)` with the vars from the spec:
    - `uuid_text: str`, `status: str`, `error: str`
    - `counts: list[list[str]]`
    - `label: str`, `confirm_text: str`, `armed: bool`, `busy: bool`
    - `progress: int`
    - `ledger: str`, `warnings: list[str]`, `moved: list[str]`
    - `phase: str = "idle"`
    - `run_dirs: list[str]` and `analysis_dirs: list[str]` (needed by the "gathered" view)
    - the backend-only `_inv: Inventory | None = None`

    And its handlers: `set_uuid(v: str)`, `set_confirm(v: str)`, and `gather()` and `do_retire()`, both under `@rx.event(background=True)`.
  - `retire_page() -> rx.Component`.

Settled behaviour:

- **`counts` rows.** `[[t, str(len(inv.local[t])), str(len(inv.in_api[t]))] for t in ENTITY_TYPES]`, then `["SEQUENCE", str(len(inv.locations)), "present" if inv.sequence_in_api else "absent"]`. When `api_only`, append to `warnings` the line "experiments/actions unknowable from API alone; processes may already be gone".
- **Arming.** `armed = self._inv is not None and self.confirm_text == (self.label or self._inv.sequence_uuid)`. `set_confirm` moves `phase` between `"gathered"` and `"armed"`. `set_uuid` resets every result var and `_inv`, and sets `phase="idle"` unless the page is disabled.
- **`gather`.** Inside `async with self`, return at once if the page is disabled or `busy`. Parse `str(uuid.UUID(self.uuid_text.strip()))`; a `ValueError` sets `error="not a uuid"` and returns without I/O. Then set `busy`, `phase="gathering"`, and write the canonical uuid back into `uuid_text`. Outside the lock, run in order:
  1. `locate`
  2. `in_flight(sources_root, u, [l.rel_dir for l in locs])` when `sources_root` is set. A hit sets `error=f"batch conversion in flight: {path}"`.
  3. `client = api.get_client()`
  4. `inventory(client, root, u, _cb)`

  Any exception sets `error=str(exc)` and `phase="idle"`. `nothing_to_retire` sets `status="nothing to retire"` and `phase="idle"`. Otherwise fill the vars and set `phase="gathered"`. `busy` is reset in every path.
- **`do_retire`.** Inside `async with self`, return if the page is disabled, and set `error="gather and confirm first"` and return unless `phase == "armed"` and `_inv` is set. Outside the state lock, check `_RETIRE_LOCK.locked()` and then `await _RETIRE_LOCK.acquire()` **with no `await` between them**. A held lock sets `error="a retire is already running"` and returns. Inside `try/finally: release`, set `busy`, `phase="retiring"` and `ledger=ledger_path_for(root, u, datetime.now(timezone.utc))`, then run `retire(api.get_client(), root, inv, _cb, ledger)`. Map the result:
  - `ok` sets `phase="done"`. Each `persisting` type adds a warning, `f"{t}: {n} acknowledged-but-persists, e.g. {', '.join(uuids[:3])}"`. `moved` becomes the list of `f"{src} -> {dst}"`.
  - Otherwise `phase="failed"` and `error=result.error`.

  In both cases set `_inv=None`, `armed=False` and `busy=False`. A raise from `get_client` also sets `failed`.
- **`_cb(phase, done, total)`.** `async with self:` then `status=f"{phase}: {done}/{total}"` and `progress=round(100*done/total) if total else 0`.
- **`retire_page()`.**
  - When `not retire_enabled()`, it is just `rx.text("Retire is disabled on this station.", padding_x="1em")`, with no input and no button.
  - Otherwise it shows:
    - a uuid `rx.input`, `on_change=RetireState.set_uuid`, `disabled=RetireState.busy`
    - a "Gather" button, `on_click=RetireState.gather`, `disabled=RetireState.busy`
    - the status line, using `palette.reflex_muted_text_class()`
    - the error, using `class_name="text-red-600"`
    - the counts table via `rx.foreach`
    - the run dirs, the analysis dirs, and the label/campaign
    - a confirm `rx.input`, `on_change=RetireState.set_confirm`, with a placeholder naming what to type
    - a "Retire" button, `on_click=RetireState.do_retire`, `disabled=~RetireState.armed | RetireState.busy`
    - `rx.progress(value=RetireState.progress)` under `rx.cond(phase == "retiring" | phase == "done", ...)`
    - the result panel (the ledger, warnings with `class_name="text-amber-700"`, and moved)

  No `color_scheme`, no `rx.moment`.
- **Tint.** Add `"orange-50": "#fff7ed"` to `TW`, with a comment saying it is the `/retire` canvas: warm and cautionary, and deliberately not in the red/ESTOP family, matching the reasoning of the `rose-50` comment. Add `"/retire": "orange-50"` to `REFLEX_PAGE_TINTS`. The measured values (WCAG, pinned arithmetic) are: slate-900 on orange-50 **16.81**, slate-600 **7.14**, slate-500 **4.48**. These fall inside the docstring's "16.25–17.25" and "6.90–7.32" ranges, so that text stays true. No table hue's worst tint changes (rose-50 is still the worst for every border).
- **`app.py`.** Add `from helao.ui.reflex.retire import RetireState, configure_retire, retire_page`. Append `"/retire"` to `SHELL_ROUTES`. Add `rx.link("Retire", href="/retire")` after the XRD link. Add `assert RetireState is not None` with the other asserts. Call `configure_retire(world_cfg, server_key)` after `configure_composition`. Then:
  ```python
  application.add_page(
      lambda: _page("Retire sequence", retire_page(), "/retire"),
      route="/retire",
      title="HELAO retire",
  )
  ```
- **`CLAUDE.md` bullet** (in `helao/ui/reflex/`): "`/retire` deletes metadata-API rows and moves run dirs. It is disabled unless the Reflex server's params set `retire: true`, and the handlers re-check that server-side. All logic is in `helao/ui/shared/retire.py`, which is Reflex-free and tested offline. Never add a code path that treats a non-404 error as absent."

- [ ] **Step 1: Write the failing tests.**
  - In `test_reflex_retire.py` (with `pytestmark = pytest.mark.usefixtures("reflex_registration")`):
    - `test_configure_enables_only_on_literal_true`, parametrised over `True`, `"true"`, `1`, a missing key, `servers` being a list, `params` being a string, and `root` missing with `retire: True`. Only the first case enables, and none of them raises.
    - `test_page_renders_enabled_and_disabled`: `str(retire_page())` contains `"Gather"` when enabled. When disabled it contains `"Retire is disabled on this station."` and not `"Gather"`. Restore `_CONFIG` in a `finally`.
    - `test_gather_disabled_does_no_io`: monkeypatch `rr.api.get_client` and `rr.retire_logic.locate` to raise `AssertionError`, then `asyncio.run(_FakeRetireState.gather(state))` returns and the vars are unchanged.
    - `test_gather_rejects_non_uuid`: `error == "not a uuid"`, and the `AssertionError` patches do not fire.
    - `test_gather_fills_counts`: a fake tree under `tmp_path`, plus `FakeMetadataClient`. `counts[2] == ["PROCESS", "3", "3"]`, `phase == "gathered"` and `label == "LBL"`.
    - `test_gather_normalises_the_uuid` (Review Focus 4): `uuid_text = "  {" + U.upper() + "}  "` gives `phase == "gathered"` and `uuid_text == U`.
    - `test_set_uuid_clears_inventory_and_disarms`.
    - `test_confirm_must_equal_label_or_uuid_when_label_empty`: the wrong text leaves the state unarmed, the label arms it, and with an empty label it is the uuid that arms it.
    - `test_do_retire_while_lock_held_reports_busy`: acquire `rr._RETIRE_LOCK` in the test's loop, then `error == "a retire is already running"` and no `retire` call (monkeypatch it to raise).
    - `test_do_retire_unarmed_does_nothing`.
    - `test_in_flight_state_file_blocks_gather`: a state file under `sources_root` that names U blocks the gather, with the path in `error`.
    - `test_do_retire_success_reports_ledger_and_moved`: the full handler path against a fake. `phase == "done"`, the ledger file exists, and `len(moved) == 1`.
    - `test_every_foreach_var_carries_an_element_annotation`: `RetireState.get_fields()["counts"].annotated_type == list[list[str]]`, and the same check gives `list[str]` for `warnings`, `moved`, `run_dirs` and `analysis_dirs`.

    `_FakeRetireState` copies the pattern of `test_reflex_composition._FakeCompositionState`: plain attributes for every var plus `_inv`, `__aenter__`/`__aexit__` returning `self`/`False`, and `gather = rr.RetireState.gather.fn` (likewise `do_retire`, `set_uuid` and `set_confirm`). Import the logic module as `rr.retire_logic`; the page module imports it under that alias.
  - In `test_reflex_routes_e2e.py`, add `test_retire_route_is_the_real_page_and_its_handlers_register(reflex_cfg)`, in the style of the xrds test: `"/retire" in SHELL_ROUTES`, and `set_uuid`, `set_confirm`, `gather` and `do_retire` are all in `RetireState.event_handlers` after `build_app(reflex_cfg, "UI")`.
  - In `test_palette.py`:
    - Add `"orange-50": "#fff7ed"` to `CANONICAL_TAILWIND`.
    - Add `("slate-900", "orange-50"): 16.81,  # /retire` and `("slate-600", "orange-50"): 7.14` to `PAGE_TINT_TEXT_ROWS`.
    - Add `("slate-500", "orange-50"): 4.48` to `SLATE_500_ON_TINT_ROWS`.
    - Rename `test_slate_500_fails_the_body_floor_on_three_of_the_seven_tints` to `..._on_four_of_the_eleven_tints`, with the expected set `{"sky-50", "violet-50", "rose-50", "orange-50"}`. Extend its docstring with one sentence: "`orange-50` joined them with `/retire`, at 4.48."
    - If any value the test computes differs from these by more than 0.01, stop and report it; do not adjust the floor.

- [ ] **Step 2: Run, and expect FAIL.**
  ```
  PYTHONPATH=. conda run -n helao python -m pytest helao/core/tests/test_reflex_retire.py -q
  PYTHONPATH=. conda run -n helao python -m pytest helao/core/tests/test_palette.py -q
  ```

- [ ] **Step 3: Implement** `helao/ui/reflex/retire.py`, the `app.py` edits, the palette entries, and the `CLAUDE.md` bullet.

- [ ] **Step 4: Run, and expect PASS**, each file in its own process:
  - `test_reflex_retire.py`
  - `test_palette.py` (all of it, including the AST colour sweep and `test_no_muted_slate_500_remains_in_the_reflex_stack`)
  - `test_reflex_routes_e2e.py`
  - `test_reflex_control.py`
  - `test_reflex_composition.py`
  - `helao/hexagon/tests/test_reflex_host.py`
  - `test_retire.py`

  Then run `pyright helao/ui/shared/retire.py helao/ui/reflex/retire.py helao/ui/reflex/app.py` from the main checkout path. Under `.claude/worktrees/`, pyright analyses zero files and reports a vacuous 0 errors, so confirm that the file count it reports is non-zero.

- [ ] **Step 5: Commit (main session, after review).** `black` on the changed `.py` files (not the fixtures directory), then commit with `feat(reflex): /retire page for retiring a mis-identified sequence`.

---

### Task 5: Manual browser check `browser_check_retire.py`

**Files:**
- Create: `helao/core/tests/browser_check_retire.py` (not collected: no `test_` prefix and no pytest functions, in the style of `browser_check_operator.py`)

**Settled deviation from the spec.** The spec says to patch `get_client` to the fake. The Reflex backend is a child process of the launcher, so a patch made in the checking script cannot reach it, and adding an environment-variable backdoor to production code just for a manual check is not justified. The check instead uses a run tree whose uuids are freshly generated (`uuid.uuid4()`) and exist in no API. Gather then issues only GETs, which return 404, so `in_api` is empty. Retire then issues **zero** API deletes, because it deletes only `in_api` rows (Task 3, step 4), and the whole UI path still runs, through the move. If the main session wants the fake client in the browser instead, that is an escalation, not an implementer choice.

**Interfaces:**
- Consumes: `make_run_tree` from `retire_fakes.py`.
- Produces: a CLI with two subcommands.
  - `prepare <workdir>` builds `<workdir>/root` with **two** locations for one fresh uuid (under `RUNS_SYNCED` and `RUNS_FINISHED`, so the progress bar takes two steps), labelled `CHECK-<first 8 of uuid>`. It also writes `<workdir>/retirecheck.yml`: a copy of `goldenreflex.yml` with `root:` set to `<workdir>/root` and `retire: true` added to `servers.UI.params`. It prints the uuid, the label, and the launch command `./helao.sh <workdir>/retirecheck.yml`. It writes nothing outside `<workdir>`.
  - `check <base_url> <uuid> <label>` runs the Playwright sequence and exits 0 or 1, printing `PASS`/`FAIL: <reasons>`.

- [ ] **Step 1: Write the script.** The `check` sequence:
  1. `goto /retire` and fill the uuid.
  2. Click Gather and wait for the counts table. Assert that the `SEQUENCE` row's local count is `2`.
  3. Assert that the Retire button is disabled.
  4. Type a wrong confirm text and assert Retire is still disabled. Type the label and assert it is enabled.
  5. Edit the uuid (append and then delete a character) and assert Retire is disabled again. Re-gather and re-type the label.
  6. Click Retire. Poll for the `progressbar` role; it must reach `aria-valuenow="100"` and must have read a value below 100 at least once (or `done` must appear within 10 s).
  7. The result panel shows a path ending `.jsonl` and two `->` lines containing `RUNS_SUPERSEDED`.
  8. No console errors were collected.

  `rx.select` is not used, so the combobox trap does not apply.

- [ ] **Step 2: Smoke-test `prepare`** into a temp dir. Confirm that the yml loads with `config_loader.read_validated_config(<path>)` and that `servers.UI.params.retire is True`. If `read_validated_config` will not accept a path outside `helao/deploy/*/configs/`, stop and report it.

- [ ] **Step 3: Run the full check once** (whoever has a warm Reflex build): prepare, launch, check, then `CTRL-x`. Record the PASS output in the task report. If it cannot be run in the implementer's environment, say so explicitly; it is a manual gate, not a pytest one.

- [ ] **Step 4: Commit (main session, after review).** `black`, then commit with `test(retire): manual Playwright check for /retire`.

---

### Task 6: Enable on the batch host (main session only, private repo)

Not an implementer task, and not a parent-repo change.

- [ ] **Step 1:** In the private deployment's batch-host config (inside that deployment's own nested git repo under `helao/deploy/`), add `retire: true` and `retire_sources_root: <the batch host's sources root>` to the Reflex UI server's `params:`. The main session knows the value. It never appears in the parent repo.
- [ ] **Step 2:** Commit in that nested repo with `git -C helao/deploy/<that deployment>`, as a separate commit, after the user approves.
- [ ] **Step 3:** On the batch host, pull and relaunch via `./helao.sh <prefix>`. The bundle stamp rebuilds the bundle because `app.py` changed. Open `/retire` and confirm that it is enabled. Gather one known-good sequence (read-only) and check that the counts match `locate` plus the API. Do **not** retire anything unless the user names a sequence to retire.

---

## Spec ambiguities found and how this plan settles them

1. **The browser check's fake client cannot cross into the backend process.** Settled in Task 5 by using fresh uuids, which give a zero-delete, read-only API path. Escalate if the fake is wanted in the browser instead.
2. **`delete_command` declares `security: APIKeyHeader`, and `get_client()` sends no key.** The private gateway deletes through an unkeyed client too, and the 2026-10-02 cleanup succeeded, so the plan uses `get_client()` as the spec says. If the API starts demanding a key, the delete returns a non-404 error and the retire stops before any move, which is safe and visible.
3. **`read_processes_by_sequence` declares `limit`/`last_evaluated_key`,** and the generated method's own `limit=` kwarg shadows the API's `limit`, so only the first page is ever returned. A capped page would undercount API-only processes; locally known processes are still probed individually. The plan raises on a non-list response, but it cannot detect a silently capped list. This is noted, not fixed (out of scope).
4. **Which rows are deleted.** The spec says "delete those rows" without saying whether that means local ∪ API or `in_api`. The plan uses `in_api` (the rows that read 200 at gather), which is also what makes the Review Focus 2 retry and Task 5's zero-delete check work.
5. **ANALYSIS probing.** Spec step 4 lists only four read operations, but ANALYSIS is in the must-404 read-back set. The served spec has `read_analysis(analysis_uuid=)`, and the plan uses it for both the probe and the read-back.
6. **`analysis_dirs` matching** is unspecified. The plan uses a substring match of known process or analysis uuids in the files directly inside each `ANALYSES/*/*/*` directory. It is report-only.
7. **The date in `<YYYYMMDD>_retired`** is UTC, to match the ledger stamp.
8. **The `/retire` tint** is unspecified, but `test_palette.py` requires one. The plan uses `orange-50`, which is cautionary without being in the red/ESTOP family, and makes `slate-500` fail on a fourth tint (4.48). The plan updates that pinned test rather than choosing a tint to avoid it.
9. **Malformed `*.state.json`** in the in-flight check is skipped with a warning. Treating it as blocking would wedge the page on any stray file.
10. **The spec puts the "handlers registered" check in `test_reflex_retire.py`.** The plan puts it in `test_reflex_routes_e2e.py`, where the `goldenreflex` `reflex_cfg` fixture and the matching uvvis/xafs/xrds checks already live.
