# Pixi environment migration — design

Date: 2026-11-11. Branch: `feat/pixi-env`. Status: approved in conversation, pending spec review.

## Goal

Replace the conda + uv `helao` environment with [pixi](https://github.com/prefix-dev/pixi) on every host (Linux and Windows) and keep exactly one helao environment per host. Pixi gives one tool for conda and PyPI packages, a lock file that pins exact builds for both platforms, and a Windows solve that runs on Linux.

## Background and evidence

A throwaway spike on 2026-11-10 (pixi 0.84.2, nothing committed) translated the dev env file, `requirements.txt` and every server folder's env files into a pixi manifest. Results:

- `pixi lock` solved every config's package set for `linux-64` and `win-64` from Linux, including conda, PyPI, a git source (GSAS-II, pinned to a commit) and a URL zip.
- In the resulting env, `run_unit_tests.py` passed and 489 pytest tests (palette sweep and `helao/deploy/base/tests`) passed. `[activation.env]` set `PYTHONPATH`. `launch.py` children found the env's `python` on `PATH`.
- On Linux, GSAS-II built from source and its Fortran extensions imported. CUDA `pytorch` loaded.

Problems the spike found, each handled below:

- One shared solve across CPU and CUDA torch fails.
- `CONDA_OVERRIDE_CUDA` is ignored by `pixi lock`.
- The `[system-requirements]` table is deprecated in pixi 0.84.
- The pyMeCom zip's dist name is `mecom`.

A second probe on 2026-11-11 tested seeding a host lock from a base lock:

- An environment that only adds features **keeps the seeded base versions** if it is solved together with the base. That means it is the same `default` env, or it shares an explicit solve group with `default`.
- A new environment in its own solve group is solved fresh and ignores the seed.

Today's pinned files (`helao_pinned_<plat>.yml`, `requirements_pinned_<plat>.txt`) are not read by any setup or update script (see `readme.md`). Every host installs fresh from the dev yml, so stations drift.

On note1, a read-only check found five consumers of `/opt/tljh/user/envs/helao`:

1. the station server group, through `helao.sh`;
2. JupyterHub notebook kernels, auto-discovered by `nb_conda_kernels`;
3. ad-hoc scripts that call the env's python by path;
4. one private-repo script with a hardcoded env path;
5. `setup_env.sh` / `update_env.sh`.

No TLJH system service uses it. TLJH itself (hub, proxy, single-user servers) runs from TLJH's own conda base, which stays.

**Other conda environments stay.** The XAFS action server (`hte/servers/xafs`) spawns its vendor sidecar directly with the configured `sidecar_python`, an absolute path to a separate Python 3.9 conda env (`easyxafs_env` on the station; `servers/xafs/sidecar/environment-sim.yml` for the simulator). It does not go through `conda run`, and the sidecar imports nothing from helao. That env, and conda itself, remain installed wherever they are used. This migration replaces only the `helao` environment.

## Decisions

| # | Decision |
|---|---|
| D1 | All hosts move, Linux and Windows. `pixi.toml` becomes the source of truth for base dependencies. |
| D2 | The parent repo tracks a base-only `pixi.toml` and `pixi.lock`. Private deployments' dependencies never appear in a tracked parent file. |
| D3 | Each host composes an untracked workspace `<repo>/.helao-env/`. It holds the base manifest plus the server folders of the host's configs, **merged into the single `default` environment**. |
| D4 | Server folders keep their current env files: `environment.yml`, `environment_<plat>.yml`, `requirements.txt`, `pip_env_<plat>.yml`. No format change in any deployment repo. |
| D5 | The host lock is seeded from the parent lock, so base versions match across stations. Drift that a station addition forces is reported. |
| D6 | `helao.sh` / `helao.bat` activate with `pixi shell-hook` and run `python launch.py` directly. No `pixi run` process sits between the shell and the launcher. |
| D7 | Deleted: `helao_dev_<plat>.yml`, `helao_pinned_<plat>.yml`, root `requirements.txt`, `requirements_pinned_<plat>.txt`, `repin_envs.py`, `helao/core/tests/test_repin_envs.py`. |

## Architecture

### Tracked in the parent repo

`pixi.toml`, holding the base only:

- `[workspace]`: `name = "helao"`, `channels = ["conda-forge"]`, `platforms = ["linux-64", "win-64"]`.
- `[dependencies]`: the current `helao_dev_linux-64.yml` list, translated (`bokeh=3` becomes `bokeh = "3.*"`, `conda-forge::jupyterlab` becomes `jupyterlab`). `comtypes` goes under `[target.win-64.dependencies]`, matching today's only difference between the two dev files.
- `[pypi-dependencies]`: the current root `requirements.txt`. The pyMeCom zip is listed as `mecom = { url = "..." }`.
- `[activation.env]`: `PYTHONPATH = "$PIXI_PROJECT_ROOT"` and `HELAOLAUNCH` (the `.sh` or `.bat` wrapper, per platform target). These values serve only someone who uses the parent workspace directly; host workspaces overwrite them with absolute paths.

`pixi.lock`: solved on Linux for both platforms. Updating it (`pixi update` in the repo root, then commit) replaces `repin_envs.py`.

`.gitignore` gains `.helao-env/` and `.pixi/`.

### Host workspace `<repo>/.helao-env/` (untracked)

| File | Content |
|---|---|
| `pixi.toml` | composed by `helao_env.py` (see Composer) |
| `pixi.lock` | seeded from the parent lock, then extended by `pixi install` |
| `.seed` | sha256 of the parent `pixi.lock` last copied in |
| `.pixi/envs/default/` | the environment |

The workspace is always composed, even on a host with no station prefixes. Then it equals the base for the host platform, so there is a single code path.

### Bootstrap (`setup_env.sh|.bat`, `update_env.sh|.bat`)

1. **Find pixi.** Look on `PATH`, then `~/.pixi/bin`. If it is missing, install it with the official installer: `curl -fsSL https://pixi.sh/install.sh | bash` on Linux, the `install.ps1` one-liner on Windows. Abort with a clear message if that fails.
2. **Create the base env.** Create `.helao-env/` if it is missing. If it has no `pixi.toml` yet, copy the parent `pixi.toml` and `pixi.lock` in and run `pixi install --frozen`. This installs the base env straight from the lock, with no solve.
3. **Add station packages.** Run `<env python> helao_env.py setup|update <args>` (`.helao-env/.pixi/envs/default/bin/python`, or `python.exe` on Windows). It handles the hte clone (unchanged), resolves configs, composes the manifest, seeds the lock and runs `pixi install`.
4. `setup_env` no longer runs `conda env config vars set`. `PYTHONPATH`, `HELAOLAUNCH` and `HELAO_STATION_PREFIXES` come from the composed `[activation.env]`.

Prefixes are still recorded in `<root>/STATES/setup_env_prefixes.json`, unchanged. `update_env` with no arguments reads the recorded list through `HELAO_STATION_PREFIXES`, now set by the env's activation. If a host has not been set up with pixi yet, that variable is unset. In that case `update_env` must accept explicit prefixes, and `setup_env` sets the variable going forward.

### Launch (`helao.sh`, `helao.bat`)

- `helao.sh`: `eval "$(pixi shell-hook --frozen --manifest-path "$HA_DIR/.helao-env/pixi.toml" --shell bash)"`, then `python "$HA_DIR/launch.py" "$@"`. The existing leftover-folder cleanup stays.
- `helao.bat`: `pixi shell-hook --frozen --manifest-path "%HA_DIR%\.helao-env\pixi.toml" --shell cmd > "%TEMP%\helao_activate.bat"`, then `call` that file, then `python "%HA_DIR%\launch.py" %*`.
- Why not `pixi run`: an extra process between the console and `launch.py` would sit outside the guarantees in `helao/helpers/CLAUDE.md` (PDEATHSIG on Linux, the Job Object on Windows, the shared raw console mode used by the hotkeys, and `CTRL-d` children surviving). With `shell-hook` the process tree is the same as under `conda activate`.
- **Transition fallback.** A station can pull this branch before running `setup_env`, and it would then have no `.helao-env/pixi.toml`. If that file is missing and a conda env named `helao` exists, both wrappers print a warning ("helao is still on conda; run setup_env to move to pixi") and run `conda activate helao` as today. If neither exists, they exit with that instruction. The fallback is deleted once every station is on pixi; that removal is a separate change.
- `launch.py`'s `CONDA_DEFAULT_ENV != "helao"` check needs no change. Pixi sets `CONDA_DEFAULT_ENV` to the workspace name (`helao`) for the default env.

## Composer (`helao_env.py`)

`install()` (a conda env update, then `uv` per folder) is replaced by:

- `compose(base: dict, folders, platform: str, repo_root: Path, states_files: list[Path]) -> dict`. A pure function: the parsed parent manifest in, the host manifest out.
- `install(manifest: dict, workspace: Path, runner=_run, dry_run=False)`. Writes `pixi.toml`, seeds the lock, runs `pixi install --manifest-path ...`, then runs the drift check.

### Translation rules (each gets a fixture test)

| Source | Target |
|---|---|
| conda `name` | `name = "*"` |
| conda `name=1.2` | `name = "1.2.*"` |
| conda `name>=1` or `name<82` | `name = ">=1"` or `"<82"` |
| conda `name=*=cuda129*` | `name = { version = "*", build = "cuda129*" }` |
| conda `chan::name` | `name` (single channel, conda-forge) |
| `environment.yml` | merged into `[dependencies]` |
| `environment_<host plat>.yml` | merged into `[dependencies]` (only the host platform is composed) |
| `environment_<other plat>.yml` | ignored on this host |
| any other yml, or any yml in a subfolder (e.g. `servers/xafs/sidecar/environment-sim.yml`, the Python 3.9 sidecar env) | never read. Only the folder-root names above are composed |
| `requirements.txt` plain spec, with extras | `[pypi-dependencies]`, e.g. `xy = { version = "*", extras = ["reflex"] }` |
| `requirements.txt` with `; sys_platform == "win32"` | included only when composing `win-64`. Other markers go into the spec unchanged where pixi supports them, else `EnvSetupError` |
| `requirements.txt` URL | `{ url = ... }`, keyed by the dist name. The name comes from a small explicit map (`pyMeCom` gives `mecom`). An unmapped URL raises `EnvSetupError` naming the line |
| `requirements.txt` `name[extras] @ git+URL` | `{ git = URL, extras = [...] }` |
| `pip_env_<host plat>.yml` | `[activation.env]`. `{prefix}` becomes `$CONDA_PREFIX`, `{PATH}` becomes `$PATH` (Windows: `%PATH%`), and `""` means an empty value |
| both `pytorch-cpu` and CUDA `pytorch` present | drop `pytorch-cpu` (CUDA `pytorch` overrides `pytorch-cpu`) |
| any dependency whose build string matches `cuda<major><minor>*` | declare CUDA `<major>.<minor>` on the host platform entry (pixi 0.84 platform syntax; the exact form is checked in the plan's first task) |

Conflicts:

- The same name with two different specs from two folders raises `EnvSetupError` naming both folders. The exception is the `pytorch` rule above.
- An identical spec is deduplicated.
- A folder spec that names a base package overrides the base spec, with a printed warning.

Composed `[activation.env]`: absolute `PYTHONPATH` (the repo root), `HELAOLAUNCH`, `HELAO_STATION_PREFIXES` (the `os.pathsep`-joined states files), plus every folder's `pip_env` entries. Two folders that set the same variable to different values raise `EnvSetupError`.

`platforms` is the host platform only, from `platform_tag()`, which already exists.

### Seed and drift

Seed:

- Before `pixi install`, compare the parent `pixi.lock` sha256 with `.helao-env/.seed`.
- If they differ, or the host has no lock, copy the parent lock over the host lock and write `.seed`.
- Pixi then keeps every seeded version the composed manifest still allows, and solves only the additions.

Drift check, after install:

- Read both locks (YAML), restricted to the host platform and the `default` env.
- For every package in the parent lock, compare its version with the host lock.
- Print `warning: base package <name> <parent> -> <host> (forced by station packages)` for each difference.
- Warn only, never fail. A station that genuinely needs a newer base package must still install.

### Errors

- Every failure is an `EnvSetupError` or a nonzero exit, with the cause named, in the existing style.
- `pixi install` failing to solve: pixi writes no lock and leaves the env untouched, so the previous env stays usable. `helao_env.py` exits nonzero with pixi's output passed through.
- `--dry-run` prints the composed `pixi.toml` and the commands, and writes nothing.
- `ensure_hte` and the prefix resolution logic are unchanged.

## Other changes

- **Tests that hardcode `conda run -n helao python launch.py ...`** (about 20, under deployment `tests/smoke/` and similar) switch to `sys.executable`. Private deployment repos get the same edit in their own commits.
- **One private-repo script with a hardcoded `envs/helao` path** gets the new path in its own repo.
- **Docs:** `CLAUDE.md` (Environment & common commands), `readme.md`, and the env sections of the deployment READMEs. Also the docstring mentions in `helao/helpers/win_job.py` and `helao/ui/reflex/CLAUDE.md`, and the `helao_env.py` module docstring. `test_framework_deployment_free.py` keeps exempting `helao_env.py`.
- **JupyterHub on note1:** a TLJH kernel registration script, tested locally on 2026-11-11, becomes tracked at `tools/tljh_pixi_kernel.sh`. It is root-run through sudo. It freezes `pixi shell-hook` into an activation script, as the invoking user, and writes a kernelspec under `/opt/tljh/user/share/jupyter/kernels/` whose argv sources that script and `exec`s `ipykernel_launcher`. At cutover it is run with the old helao kernel's name, so saved notebooks keep working.

## Testing

Unit tests, offline:

- `compose()`: one fixture per translation rule and per conflict rule, built from small server-folder trees in `tmp_path`.
- Seed and drift: small fake lock files cover copy-on-changed-hash, no copy when the hash matches, and the drift warning text.
- `test_helao_env.py` (82 tests): the install path assertions change from conda and uv commands to the composed manifest and the `pixi install` command. Resolution, recording and hte tests keep their behaviour.
- `test_repin_envs.py` is deleted together with `repin_envs.py`.
- Every new rule test is checked by mutation: break the rule and confirm the test fails.

Integration gates. **All must pass before merge:**

1. **fuyu:**
   - `setup_env.sh` from a clean `.helao-env/` with a multi-feature config prefix;
   - the full `run_tests.py` sweep in the pixi env, with the failing set compared to the conda baseline;
   - `./helao.sh goldenreflex` launches, the reflex UI serves, and `CTRL-x` tears the group down.
2. **note1 cutover:**
   - the station group stopped and no long job running in the conda env;
   - `setup_env.sh <note1 prefix>`;
   - the kernel script run with the old kernel name;
   - ad-hoc script paths repointed;
   - group relaunched, UI and ANA smoke checks pass;
   - then `conda env remove -n helao`.
3. **One Windows station:**
   - `setup_env.bat <prefix>` from scratch;
   - launch via `helao.bat`;
   - `CTRL-r` restarts a server, `CTRL-d` detaches with children alive, `--reconnect` reattaches.
   - If the station runs the XAFS server with `spawn_sidecar: true`: the sidecar starts from its own conda env under the pixi-activated launcher and answers `/health`. It inherits the launcher's environment, as it does under `conda activate helao` today.
   - If any Windows host uses the GSAS-II server folder: that build must succeed with its `pip_env_win-64.yml` variables. If pixi does not pass activation variables to PyPI source builds, this gate fails and the design gains a pre-build step before merge.

## Out of scope

- Converting server folder env files to pixi TOML fragments (rejected option C).
- Moving TLJH itself, or any conda env other than `helao`, including the XAFS sidecar env (Python 3.9, with proprietary vendor packages installed by hand).
- Uninstalling conda from any host.
- Changing `run_unit_tests.py` / `run_tests.py` behaviour beyond what the interpreter switch needs.

## Rollout

Stations move one at a time after the branch merges, by running `setup_env` with their prefixes. A station that has pulled the change but not yet run `setup_env` keeps launching on its conda env through the transition fallback in `helao.sh` / `helao.bat`. After a station is confirmed on pixi, its conda `helao` env is removed: there must not be two helao environments on one host.
