# P7-UI station rollout runbook

**For:** whoever is at the instrument PC flipping a station's `bokeh:` / `reflex:` servers
to hexagon hosting, or restarting a visualizer after P7 lands.
**Scope:** deployment mechanics and verification. P7's correctness is discharged on Linux;
a station window verifies that what was proven there is what this machine is running.
**Privacy:** the private nested deployments are **Deployment-A / B / C**. Their configs are
named only by alias here.

---

## 0. Correction to the P7 plan, read this first

The P7-UI plan (`docs/superpowers/plans/2026-08-05-P7-UI-both-stacks.md`, P7k item 3) says
every affected runbook gains an **unconditional** `python build_reflex_bundle.py <config>`
step. That instruction predates the bundle-from-STATES work that has since landed and is
merged into this line. **It is no longer the step.**

What actually happens now, measured against `reflex_bundle.py` and `reflex_launcher.py`:

- Every launch computes a **stamp** per `(config, reflex server)` — the baked `api_url`, the
  git HEAD *and* `git status --porcelain` digest for the parent repo and each nested
  deployment repo, a content-hash map of every `helao/` module the app imported, `rxconfig.py`,
  xy's ESM client, and the `reflex`/`reflex-components-radix`/`xy` versions. Never mtime.
- If the stamp moved and `_app/.web/node_modules` is **warm**, the launcher rebuilds
  **silently, in about 4–5 seconds**, and carries on.
- If the stamp moved and the cache is **cold**, it **refuses to start that server** rather
  than serving a stale bundle, and prints the exact command to run.

So the station step is: **make the cache warm once, then let the launcher do it.** The manual
build is what you run when the launcher tells you to, and once per new machine.

---

## 1. Which configs this touches

Swept from `helao/deploy/*/configs/` on 2026-08-08.

**Configs declaring a `reflex:` server — these need a bundle.**

| Config | Kind |
|---|---|
| `hte/clad.yml` | station |
| `hte/eche10.yml` | station |
| `hte/hispec.yml` | station |
| `hte/htereflex.yml` | development (legacy lane) |
| `hte/htehexreflex.yml` | development (hexagon lane, new in P7k) |
| `test/goldenreflex.yml`, `test/goldenreflexspec.yml`, `test/goldenhexreflex.yml` | simulated |
| Deployment-A's demo config | already declared `reflex:` before P7 |
| Deployment-C's station config | declares both `reflex:` and `control_vis` |

The plan said "3 hte station + 1 hte dev"; that was right when it was written and is now
**3 station + 2 dev**, because P7k added the hexagon dev sibling.

**Configs declaring `control_vis` — 19 in total.** These get the control page and its
buttons. The ones that do *not* also declare `reflex:` need only a visualizer restart: no
bundle exists for them and none is built.

---

## 2. Before the window

1. **Preflight the in-tree config path**, not a copy:

   ```
   python -m helao.hexagon.preflight helao/deploy/<deployment>/configs/<station>.yml
   ```

   Expect `PREFLIGHT OK`. **Do not preflight a config you copied somewhere else to edit.**
   `preflight` infers the deployment from the config's *path*, so the same bytes in a scratch
   directory resolve no deployment, hence no checklist directory, hence nothing checked — and
   it still prints `PREFLIGHT OK`. This trap is pinned by
   `helao/hexagon/tests/test_preflight.py::test_a_scratch_copy_of_a_config_does_not_exercise_the_checklist_gate`;
   the point of that test is that a clean result from a copied-out config certifies less than
   it appears to.

2. **Tell the station's users about the button relabelling** (§4.2). A safety control changed
   its label; that is not something to discover during an incident.

3. **Check whether any bookmark names a grafted server's URL** (§4.3).

---

## 3. The bundle

**Warm machine (the normal case).** Nothing to do. Launch; the launcher rebuilds if the stamp
moved. Confirm in the log that it did:

```
built and installed <root>/STATES/reflex-bundles/<config>_<server>/helao_ui
```

**Cold machine, or the launcher refused.** The refusal is explicit and names the command:

> no usable Reflex frontend bundle for `<config>/<server>` at '…' (…), and this machine
> cannot build one now. Build it with:
>     `python build_reflex_bundle.py <config> --server <KEY>`
> A first build downloads ~270 MB of npm packages, so it is not run unasked at launch; once
> '…/.web/node_modules' exists a rebuild takes a few seconds and happens automatically. To
> allow the first build here too, set `REFLEX_ALLOW_LOCAL_BUILD=1` (bun or node must be on
> PATH).

Run that command. It needs `bun` or `node` on `PATH` — present in the *development*
environment files, not the station ones. `REFLEX_ALLOW_LOCAL_BUILD=1` lets the launcher do
the first build itself; prefer running it by hand so a multi-minute download is not mistaken
for a hang.

**Two other refusals you may meet, both deliberate:**

- *"the only bundle available is the pre-config one … built for `<url>` while this server
  needs `<url>`"* — the one-release fallback at `<repo>/.reflex-bundle/helao_ui` exists, but
  it was baked for a different port. Serving it would render the page and then refuse every
  WebSocket, silently, with nothing in any log. Build the right one.
- *"the Reflex frontend build failed and nothing was replaced"* — the old bundle is untouched
  and the server does not start. **A build failure never falls back.** The config's Bokeh UIs
  are unaffected, so a station keeps a working UI either way.

**A build never runs on a `noexec` filesystem in place.** It stages into
`$XDG_CACHE_HOME/helao/reflex-build/<checkout digest>/_app`, which is persistent — a fresh
temp dir would discard `.web` and make every build cold. Only the build needs exec; the
bundle is static files.

---

## 4. Three things P7 changed that are visible at a station

### 4.1 The bundle must be rebuilt because the button markup changed

P7i added stop/estop buttons to the Reflex station panels, which changed `class_name=` usage.
The compiled CSS only contains the utilities present **at build time**, so a stale bundle
renders the new controls **completely unstyled, with no error on either side**. This is the
one bundle rebuild that is unconditional at P7 rollout — but the stamp now forces it for you
(the edited modules change their content hashes), which is exactly the failure this mechanism
was added to close. Do not rely on remembering; do confirm the rebuild happened in the log.

### 4.2 The three stop controls were relabelled and recoloured, on both stacks

| Was | Now | Colour |
|---|---|---|
| "emergency stop: all hardware" | **HALT ACTIONS** | amber (warning) |
| "abort orchestrator" | **ESTOP** | red (danger) |
| "safe stop" | **STOP QUEUE** | blue (primary) |

The wire is unchanged — each button fires exactly the command set it fired before. Only the
label and colour moved, and they moved on the **Bokeh** panel as well as the Reflex one, so
there is no stack where the old labels survive. Brief the station before the window.

### 4.3 A grafted server serves at `/graft`

P7e's generic graft mounts at the config's code-key value, so a server flipped to
`bokeh: graft` serves its document at `/graft` rather than at the old module-named path.
Internally consistent, and invisible to anything that follows the launcher — but **a bookmark,
a wall display, or a runbook naming the old path breaks on the flip.** Collect those before
flipping and update them in the same window.

---

## 5. The rendered check

The lane is one command with one exit code:

```
python run_browser_parity.py               # the whole lane
python run_browser_parity.py --lane bokeh  # one lane
python run_browser_parity.py --build       # rebuild the Reflex bundle first
python run_browser_parity.py --self-test   # harness self-checks, launches nothing
```

It launches each config it needs, runs every browser check, tears the group down, and diffs
the legacy-hosted matrix against the hexagon-hosted one. Non-zero exit means a check failed or
the diff was non-empty.

Three things about running it, each learned by getting it wrong:

- **The conda environment must be on `PATH`, not merely the interpreter.** `launch.py` spawns
  children as a bare `python`; invoking it by absolute path starts a launcher that reports
  success while every child dies on `ModuleNotFoundError`.
- **Teardown is slow and must be waited for, by port** — 60–90 seconds. Launching the next
  config early yields a group that binds nothing and silently keeps serving the *old*
  processes' code.
- **`pgrep -f` matches the script's own command line**, so readiness and teardown are decided
  by whether ports are bound, not by process matching. Do not "improve" that.

If you are checking one station by hand instead, the thing to look at is **computed styles and
drawn pixels**, not page source: a stale bundle and a missing utility both leave the source
looking correct.

---

## 6. If the window also captures goldens

Amendment §4.2's capture-window rule applies: a control surface that can be touched during a
capture makes the capture unreproducible. Record `control_surface_idle: true` as an explicit
sign-off for the window — i.e. nobody drove a control page while the capture ran — or do not
treat the capture as a golden.

---

## 7. Rollback

All config-only, per server, and P7 **deletes nothing** — both UI stacks remain fully present
in legacy core in-tree.

- **Reflex:** delete `deployment: hexagon` from the server entry. The launcher then sets no
  `HELAO_REFLEX_APP_MODULE` and the entry module imports what it always did. Note that the
  rollback **also moves the stamp**, so it forces one rebuild — a few seconds warm, a refusal
  cold. Plan the rollback on a machine with a warm cache.
- **Bokeh:** restore the `bokeh:` module name and drop `legacy_module:`.
- **Aligner / ports:** nothing to roll back — the legacy stack never consumed them, and a
  hexagon composition raises loudly rather than falling back if a port is unwired.

---

## 8. Scheduling

P7k delivers this runbook and the Linux-green everything; it consumes no station windows
itself. Flips are canary-first, per-station, individually rollback-able, following the P3–P6
practice. One station per window; do not batch.

---

## Open questions

- The per-station bundle build time on the instrument PCs themselves has not been measured;
  the 4–5 s warm figure is from a development machine. Expect the first build on a station to
  be dominated by the npm download, not by the export.
- Deployment-A's Bokeh servers resolve into hte's modules by launcher fallback today. When
  they flip, P7e's explicit `legacy_module:` should be used to turn that implicit fallback
  into a stated config value — but no window is scheduled for it and the conversion is
  untested at that station.
