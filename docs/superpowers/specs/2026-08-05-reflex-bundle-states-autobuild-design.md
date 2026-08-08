# Config-specific Reflex bundles under `STATES`, with auto-build

*2026-08-08. Implements the per-`(config, server)` bundle layout, a staleness
stamp, and an auto-build at launch. Supersedes the single repo-root
`.reflex-bundle/helao_ui` and the "build on a dev machine and ship it" workflow.*

## The problem

A Reflex export is not portable. Two things are compiled into the JavaScript:

* the backend URL, from `HELAO_REFLEX_API_URL`; and
* this config's panel selection — server keys appear as literal comparisons and
  as event-handler arguments (`{server_key:'MOTOR'}`).

So one bundle is valid for exactly one `(config, reflex server)` pair. The old
layout gave the whole repository **one** bundle at `<repo>/.reflex-bundle/helao_ui`,
which could be right for only one config at a time — and `resolve_bundle` took
no `server_key` at all, so two `reflex:` servers in one config would have shared
it on different ports. Being wrong is silent: the page renders, then every
WebSocket is refused, and nothing appears in any log on either side. The same
silence applies to a bundle that is merely *out of date*: a stale one renders
new `class_name=` utilities completely unstyled, again with no error.

The mitigation until now was a human remembering to run `build_reflex_bundle.py`.

## Layout

```
<root>/STATES/reflex-bundles/<config_prefix>_<server_key>/
    helao_ui/       # the extracted export, 74 files / 3.0 MB
    bundle.json     # the stamp describing what it was built from
```

A config with no `root:` gets the same tree under `<repo>/.reflex-bundle/`
instead. The stamp is a *sibling* of the bundle, not a child, so the install's
own replace cannot take it with it.

Nothing prunes `STATES` (`check_dir` only creates; `prune_timestamped_exports`
is scoped to `queues_<ts>.pck`; log zipping targets `LOGS/`). Each pair costs
3.0 MB and is overwritten in place, so the growth is bounded by the number of
`(config, server)` pairs a station has ever launched.

## Stamp schema

`schema: 1`. Fields are either **compared** (a difference makes the bundle
stale) or **recorded** (diagnosis only).

| field | compared | what it catches |
|---|---|---|
| `schema` | yes | a stamp whose fields cannot be compared meaningfully |
| `api_url` | yes | the exact baked string; a port or host change |
| `config_prefix`, `server_key` | yes | a bundle directory that does not match its contents |
| `git_revs` | yes | a pulled commit, in the parent repo **and each nested `helao/deploy/*` repo** |
| `dirty_digests` | yes | an *uncommitted* panel edit — sha1 of each repo's `git status --porcelain` |
| `extra_files` | yes | `_app/rxconfig.py` and xy's ESM client, neither of which is in `sys.modules` |
| `tool_versions` | yes | `reflex`, `reflex-components-radix`, `xy` |
| `modules` | yes | every repository `.py` the app actually imported, by content sha1 |
| `js_runtime` | no | which bun/node produced it |
| `built_at`, `built_by_host` | no | provenance |

**Never mtime.** `git checkout` rewrites it on files whose content did not
change, and `cp -p` preserves it across a copy that did.

`git_revs`/`dirty_digests` come from `launch.py`'s own `discover_git_repos` and
`git_head` — borrowed, not reimplemented, so the hot-reload watcher and this
stamp can never disagree about which repos exist or what revision they are at.

### `modules` is the load-bearing field, and the trap

It is `loaded_repo_modules()` — a walk of `sys.modules` — so it contains exactly
the files the app imported, *including* the panel modules resolved from config
strings, which a static import graph or a `git ls-files` sweep would miss. It
costs <10 ms on top of an app import the launcher already performs, and measures
59 entries for a two-page config.

Because it is read from `sys.modules`, it must be captured **after** the Reflex
app is imported. Captured before, it degrades to a stub map that never changes —
i.e. a bundle that is never stale, served forever, with every other signal
reading healthy. `validate_stamp` therefore refuses to write a stamp whose map
lacks `helao/core/servers/reflex/app.py` or holds fewer than
`MIN_TRACKED_MODULES` (10) entries. Both launcher and build script import the
app first, and the guard is what keeps that ordering from silently rotting.

The map is scoped to the `helao` package, not the whole checkout. The repo root
also holds the entry-point scripts, and *which* of those is loaded depends only
on who is asking: measured, a stamp written by `build_reflex_bundle.py` and one
written by `reflex_launcher.py` differed by exactly one entry — their own
filenames — and would have rebuilt each other's bundle forever. With the
`helao/` scope the two processes produce byte-identical 59-entry maps. Nothing
at the repo root is importable by the Reflex app, so none of it can reach the
emitted JavaScript.

### Why `js_runtime` is recorded but not compared

The emitted bundle is produced by the toolchain pinned under `.web`, not by the
interpreter that ran it. Comparing the runtime's version would make a bundle
that is *correct* unserveable on the one machine that cannot rebuild it — a
station with no runtime at all — which is the exact opposite of what the
staleness check is for.

## Staleness rule

Any compared field differing makes the bundle stale, and **the log names every
field that differed**, not just the first: "the port changed" and "a panel
module changed" call for different reactions, and reporting one of them sends
the reader down the wrong path. Dict fields report the changed keys:

```
reason: stale: dirty_digests (1 changed (.)); modules (1 changed (helao/core/servers/reflex/plots.py))
```

A missing or malformed stamp reads as stale, never as trusted.

## Build policy

Measured on this hardware:

| situation | cost |
|---|---|
| `.web/node_modules` populated | **4.3 s** export |
| cold | ~270 MB npm fetch; 10 s wall with a warm package cache, minutes without |
| `node_modules` on disk | 229 MB, 154 packages, one per checkout |

Two branches:

* **warm** → build silently during launch. This is the point of the change: a
  station's UI follows its own code without anyone remembering to rebuild.
* **cold** → refuse, print the exact `python build_reflex_bundle.py <prefix>
  --server <key>`, and require `REFLEX_ALLOW_LOCAL_BUILD=1` to proceed anyway.
  A multi-minute network fetch must never start unasked while an operator is
  waiting on an instrument UI.

Either branch also needs `bun` or `node` on `PATH`.

### The `noexec` correction

`build_reflex_bundle.py` already staged the build off a `noexec` filesystem —
but into a fresh `TemporaryDirectory`, with `.web` excluded from the copy. So
every build on a `noexec` checkout (`/mnt/STORAGE` is mounted `noexec`) was
cold, and the warm branch was unreachable there. The staging directory is now
persistent, at `$XDG_CACHE_HOME/helao/reflex-build/<checkout digest>/_app`
(`%LOCALAPPDATA%` on Windows; `HELAO_REFLEX_BUILD_DIR` overrides), keyed by
checkout so two of them never share one `.web`. Sources are *replaced* rather
than merged on each sync, so a panel deleted upstream disappears from the build
instead of staying compiled in; `.web` is preserved. `node_modules_present`
asks about the directory the build will actually run in, not about the
repository.

## Failure and rollback

| situation | behaviour |
|---|---|
| current bundle | serve it |
| stale/absent, build possible, build succeeds | serve the new one |
| stale/absent, build possible, **build fails** | **exit non-zero**; the installed bundle is untouched |
| stale, build not possible | **exit non-zero** |
| absent, build not possible, legacy bundle present and baked for *this* URL | WARNING, serve the legacy one |
| absent, build not possible, legacy bundle baked for *another* URL | **exit non-zero**, naming both URLs |
| absent, build not possible, no legacy bundle | **exit non-zero** |

A wrongly-styled or silently disconnected control UI on an instrument is worse
than one that does not come up: the operator can see the second. Any Bokeh UIs
the config declares are unaffected either way. The build is verify-then-replace
— non-empty `frontend.zip`, extracted `index.html`, and a stamp that passes
`validate_stamp`, all checked before anything installed is disturbed — then an
atomic rename with the old tree kept aside until the new one is in place.

### Surfacing the refusal at the launcher

`launch.py`'s spawn loop registered each child's pid and never looked at its
exit status, so a refusal left only a dead pid and an ERROR scrolling past
inside every other server's startup chatter, while the launch read clean.
`supervise_early_exits` now runs on a daemon thread for
`EARLY_EXIT_WINDOW` (90 s) after launch and reports any child that exits on its
own, with a red banner. Polling rather than a single check right after `Popen`:
a refusal is a decision the child reaches only after loading its config and
importing its app — seconds later — and blocking the spawn loop that long to
find out would delay every launch. The watch stops the moment a stop is *asked
for* (teardown, CTRL-r, full relaunch), where a child exiting is the point
rather than a failure. This is generic across `fast:`/`bokeh:`/`reflex:`; it
adds reporting and changes no launch behaviour.

## Concurrency

Two launches of different configs write to different bundle directories but
build through **one** `_app/.web` per checkout, so the lock guards the *build*.
`filelock.FileLock` (declared in both environment files) with an
`O_CREAT|O_EXCL` spinlock fallback, at `_app/.reflex-build.lock`, gitignored —
a tracked lockfile would land in `git status --porcelain` and make every build
invalidate its own stamp. The holder writes its pid/host/time to a `.owner`
sidecar, so a timeout (`BUILD_LOCK_TIMEOUT`, 900 s — long, because the wait is
bounded by a real cold build) raises `BuildLockBusy` naming the holder rather
than hanging a launch forever.

## The one-release fallback

`<repo>/.reflex-bundle/helao_ui` is still served when **no** per-config bundle
exists, so upgrading a station cannot brick its UI. It carries no stamp, so the
only record of what it was built for is the JavaScript itself: `baked_api_url`
scans the bundle's `.js` files for the most frequent `http(s)://host:port` and
the warning reports it. If that URL is not this server's, serving it would
render a page that silently refuses every WebSocket, so the launcher refuses
instead and names both URLs.

It is offered only when the per-config bundle is *absent* — never in place of a
stale one, which is a bundle already known to be wrong and no less likely to be
right than the legacy one.

**Removal condition:** delete `legacy_bundle_dir`, its branch in
`resolve_bundle`, and the launcher's legacy branch once every station has
launched at least once on this release (i.e. has a
`STATES/reflex-bundles/<prefix>_<key>/` directory). The warning it emits names
itself as temporary.

## Known limitations

* Shipping a prebuilt bundle from a development machine to a station is no
  longer the supported path; the model is build-where-you-run, and
  `build_reflex_bundle.py` installs into the *local* root. A copied bundle
  whose stamp was written elsewhere will normally read as stale (different
  checkout state) and be rebuilt.
* When `git` is unavailable, `git_revs`/`dirty_digests` degrade (empty /
  `"unknown"`). The `modules` content hashes still carry the real signal, so
  staleness detection remains correct — just less specific about *why*.
* A bundle built by `build_reflex_bundle.py` and one built by the launcher now
  produce identical stamps, but that rests on the `helao/`-scoped module map. A
  future change that makes the Reflex app import something from the repo root
  would reintroduce the divergence.
