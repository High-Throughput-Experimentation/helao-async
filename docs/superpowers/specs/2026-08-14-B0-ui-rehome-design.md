# B0 — UI Re-home: `helao/core/servers/` UI survivors to `helao/ui/`

**Date:** 2026-08-14
**Parent:** `docs/superpowers/specs/2026-08-14-legacy-separation-program-design.md` (D-S3)
**Baseline:** `unstable` @ `b6a475a0`
**Privacy rule:** the private deployments are **Deployment-A/B/C** only.

---

## 1. Purpose

`helao/core/servers/` holds two unrelated things: the legacy engine that the rest of the
program replaces, and the UI layer that both stacks render from and that nothing in the
program touches. B0 separates them by moving the UI out, so that later sub-projects delete a
directory instead of picking through one, and so the UI cannot silently re-couple to an
engine that is being dismantled underneath it.

B0 changes no behaviour. It is a relocation plus a boundary test.

## 2. The cut is clean, measured

The survivors import nothing from the engine. Grepping `core.servers.base`,
`core.servers.orch` and `core.servers.active` across `palette.py`, `bokeh_theme.py`,
`vis.py`, `vis_subscriber.py`, `io_control.py`, `io_control_vis.py`, `motion_control.py`,
`motion_control_vis.py`, `reflex/`, `operator/` and `data_browser/` returns zero hits.

Stack coupling is equally clear-cut. `vis_subscriber.py` imports bokeh; `palette.py`,
`io_control.py`, `motion_control.py`, all four `operator/` logic modules and all three
`data_browser/` logic modules import neither bokeh nor reflex. The shared/bokeh/reflex split
below therefore describes the code rather than being imposed on it.

## 3. Target layout

```
helao/ui/shared/
    palette.py
    io_control.py
    motion_control.py
    operator/{orch_backend,param_forms,param_store,spec_parser,object_tree,helao_operator}.py
    data_browser/{readers,sources,state}.py

helao/ui/bokeh/
    theme.py                 <- bokeh_theme.py
    vis.py
    vis_subscriber.py
    io_control_vis.py
    motion_control_vis.py
    operator.py              <- operator/bokeh_operator.py
    data_browser.py          <- data_browser/app.py

helao/ui/reflex/
    app.py control.py discovery.py ingest.py plots.py ringbuffer.py
    state.py xy_component.py
    _app/
    operator.py              <- operator/app_reflex.py
    data_browser.py          <- data_browser/app_reflex.py
```

Two placements are worth stating because they are not obvious from a file name.
`object_tree.py` goes to `shared/operator/` because both operator UIs import it.
`helao_operator.py` goes to `shared/operator/` because Deployment-C's four batch-processing
scripts import it and it touches no UI toolkit at all.

Five modules are renamed (marked `<-`). Every other module keeps its basename, so the bulk of
the edit is a mechanical path substitution that can be reviewed as one rule.

## 4. Dependency direction, and the rule that outlives B0

After the move `helao/ui/` imports `helao/helpers`, `helao/core/models` and
`helao/core/error`, and nothing from `helao/core/servers/`. That is already true; B0 makes it
enforceable.

**A boundary test asserts that no module under `helao/ui/**` imports `helao.core.servers`.**
Its value is mostly in B1–B6: while the engine is being replaced, that test is what stops a
port quietly reaching back into legacy hosting from UI code, which is exactly the kind of edge
that would not surface until B7 tried to delete the engine.

The test walks the AST rather than grepping, so a dynamic `import_module("helao.core.servers…")`
string is caught as well — the Reflex stack resolves panel modules from config strings, so a
grep-only check would have a real blind spot here.

## 5. What an import rewrite alone would miss

These sites carry the old path as data, not as an import statement, and each must be updated
deliberately:

- `helao/core/tests/test_palette.py`
  - `SWEEP_EXEMPT_PATHS` — the two source-of-truth modules, exempt by **exact path**. A test
    (`test_exemption_list_holds_exactly_two_entries`) pins the tuple, so both the tuple and
    the assertion move together. New values: `helao/ui/shared/palette.py` and
    `helao/ui/bokeh/theme.py`.
  - `SWEEP_EXEMPT_SITES` — a frozenset of `(path, lineno)` pairs. **Line numbers are
    re-derived from the moved files, never translated**, because a rename that shifts a line
    silently converts an exemption into an un-exempted literal or vice versa.
  - `REFLEX_STACK_GLOBS` — four entries, three of which name the old paths. They collapse to
    `helao/ui/reflex/**/*.py` plus the unchanged `helao/deploy/*/servers/reflex/**/*.py`,
    because the renamed `operator.py` and `data_browser.py` now sit inside
    `helao/ui/reflex/` and are already covered by the recursive glob. Collapsing four entries
    to two must be verified to lose no file: enumerate both glob sets before and after and
    assert the resulting path sets are equal modulo the rename map.
  - the whole-tree sweep in `test_no_raw_color_literals_anywhere`, which globs three roots:
    `helao/deploy/*/servers/**/*.py`, `helao/core/servers/**/*.py`, `helao/hexagon/**/*.py`.
    **Add `helao/ui/**/*.py`; do not replace the `helao/core/servers/**` entry** — the engine
    still exists until B7 and is swept clean today, so dropping that root would silently
    reduce coverage. B7 removes it along with the directory.
  - a **vacuity guard for the new root**, mirroring the existing
    `test_sweep_reaches_hexagon_tree`: an empty or mistyped glob makes the sweep pass by
    reaching nothing, which reads identically to a clean sweep.
- `helao/core/servers/reflex/_app/rxconfig.py` — names the app module in a docstring and
  derives the app from the directory.
- `reflex_launcher.py` — `HELAO_REFLEX_APP_MODULE` and the hexagon-hosted app-module
  resolution.
- roughly ten Sphinx `:mod:`/`:class:` cross-references in module docstrings.
- `CLAUDE.md` — the Reflex-stack and palette sections name these paths throughout.

Historical documents under `docs/superpowers/` are **not** rewritten. They describe the tree
as it stood on their date; editing them would make them lie about the past.

**Before each of the five renames, verify no config names that module as a string** — a
`bokeh:`, `fast:`, `live_vis:`, `action_vis:` or `control_vis:` value, or a `params:` entry.
A dynamic import by name is invisible to a grep for `from`, and a config that names a moved
module fails at launch, not at import.

## 6. Two mechanisms that react to the move

**The Reflex bundle rebuilds itself, and that is correct.** The bundle stamp includes a
content-hash map of every `helao/` module the app imported. Moving the modules changes the
map, so the next launch detects the mismatch, logs which field moved, and rebuilds. Where
`.web/node_modules` is warm this costs about 4.3 s; cold, the launcher refuses and prints the
explicit `build_reflex_bundle.py` command. B0's verification runs an explicit rebuild rather
than relying on a station discovering it.

**The build's cache key changes.** The build stages into
`$XDG_CACHE_HOME/helao/reflex-build/<checkout digest>/_app`, and `_app/` itself moves under
`helao/ui/reflex/`. Expect one cold-ish build after the move; this is why the parent repo's
verification includes an explicit build step rather than assuming the incremental path.

## 7. Execution order across four repos

Lockstep, no compatibility shim. A re-export layer would leave 13 modules in the very
directory B7 deletes, and would have to be carried through B1–B6 for no benefit — the four
repos already deploy together at a station.

Order within the change:

1. Parent repo: `git mv` the modules into `helao/ui/` (using `git mv` so history follows),
   rewrite parent-repo imports and the §5 path-literal sites, add the boundary test.
2. Deployment-A (6 files), Deployment-B (9), Deployment-C (8): rewrite imports.
3. Verify (§8) with all four working trees in the new state.
4. Commit the three private repos first, then the parent. **Parent last**, so no private repo
   is ever committed pointing at a path the parent has not yet published.

`black` runs on the changed files in each repo immediately before that repo's `git add`.

## 8. Verification

- Full pytest sweep via `python run_tests.py`, which runs one file per process — the tree
  hangs indefinitely when collected as a single session, so a per-file run is the only
  meaningful green.
- `python run_unit_tests.py` green (it also gates every launch).
- `helao/core/tests/test_palette.py` green. **Baseline measured 2026-08-14 at `b6a475a0`: 170
  passed in 3.39 s** — so the post-move count must be 170 plus whatever guard tests §5 adds,
  with none failing. (Note for whoever reads that file: the
  `test_no_raw_color_literals_anywhere` docstring still says it is "EXPECTED TO FAIL until the
  final sweep phase lands". That is stale — the sweep landed and the test passes. Do not treat
  a failure there as the expected state.) Includes the two-entry exemption pin at its new
  paths, and the frozen sweeper-calibration fixtures untouched: the fixtures under
  `helao/core/tests/fixtures/sweeper_calibration/` are **not** reformatted or refreshed —
  their pinned line numbers are the point.
- `test_standalone_operator.py`'s 48 tests green with the Bokeh operator otherwise unedited.
- Explicit `python build_reflex_bundle.py` for a Reflex config, then `python launch.py
  goldenhexreflex` and `python launch.py goldenhex` come up clean with no child exiting under
  `supervise_early_exits`.
- Headless render of `/`, `/live`, `/action`, `/operator`, `/browser` and `/control`
  asserting computed styles and drawn content — not source greps, since a stale bundle
  renders new utilities completely unstyled with no error on either side.
- `pyright` shows no new errors. Run it against a plain path, not a worktree: under
  `.claude/worktrees` it analyzes 0 files and reports a vacuous clean pass.
- The new boundary test green.

## 9. Risks

- **The `(path, lineno)` exemption frozenset.** Translating rather than re-deriving those
  line numbers produces a test that passes while exempting the wrong line. Re-derive.
- **A config naming a renamed module by string.** Fails at launch, not at import, so the
  suite would stay green. Mitigated by the §5 check before each rename.
- **A stale Reflex bundle.** Renders unstyled with no error on either side. Mitigated by the
  explicit rebuild plus computed-style assertions.
- **Cross-repo skew.** A private repo committed before the parent points at a path that does
  not exist yet. Mitigated by the parent-last order in §7.

## 10. Rollback

`freeze/pre-legacy-removal_2608` in each of the four repos. B0 introduces no behaviour change,
so rollback is the relocation reverted — there is no data or on-disk state to migrate back.
