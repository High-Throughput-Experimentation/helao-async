# action/experiment/sequence library runners

Runners are an alternative to the Orchestrator scheduling and queuing framework. They behave as "micro-orchestrators" which provide short-lived API endpoints for starting, stopping, resuming, checking status, and returning deferred updates.

The drawback to using runners is there is no assumed backend service, e.g. a long-lived orchestrator service, which has direct jurisdiction over queued and ongoing actions/experiments/sequences. Instead, the runner is known only to its calling frame.

A runner object maintains state: 1. counter for dispatched children 2. run status -- not started / running / paused / finished 3. child outputs 4. caller 5. subscribed servers

# config and subscription inheritance

Since action runners may be called by experiment runners, and experiment runners called by sequence runners, etc... Overhead can be reduced by sharing a subscriber and configuration context. The subscriber will provide the "update_status" API endpoint which will receive POST requests from action servers.

# /group feed

MicroOrch pushes frames to every `reflex:` server in `world_cfg` (backend `port + 1`). `group_urls=` overrides the targets; `group_urls=[]` disables the feed. `stop()` deregisters the runner.

The page fetches object details through the `get_object(kind, uuid)` RPC on the runner's existing dispatcher.

A second live runner with the same `server_key` gets a 409 and retries every 5 s (a restart under the same key appears once the old entry goes stale).

# Runner scripts

A runner script is a module under `helao/deploy/<deployment>/runners/` that the `/runners` page can list and launch.

- Contract: `async def run(orch: MicroOrch, <params with defaults>)`. Every parameter after `orch` needs a default. Annotate with `int`, `float`, `str` or `bool` to get typed form fields and coercion.
- `REQUIRES = {server: [action, ...]}` is optional. The page checks it against the group. Without it, the page infers requirements from literal action-building calls.
- The docstring of `run` (else the module docstring) is shown on the page.

Launcher:

```
python -m helao.core.runners.launch <config> <module> [--key K] [--params JSON] [--host H]
python -m helao.core.runners.launch --describe <module>
```

`--describe` prints one JSON line (docstring, params, `REQUIRES`, inferred requirements) or an `error` field. The default key is the module name upper-cased without a `_runner` suffix. A key that is a server key in the config is a usage error.

Exit codes: 0 clean or stopped, 1 runner exception or import failure, 2 usage error, 130 forced.

Stop semantics:
- The first SIGTERM (SIGINT, or CTRL_BREAK on Windows) is a cooperative stop. The runner dispatches nothing more, the in-flight action finishes, and the experiment/sequence is written as aborted. Exit 0.
- A second signal cancels the runner task at once. Exit 130.
- The page's Stop sends the first signal. Force kill (SIGKILL) is a separate button.
