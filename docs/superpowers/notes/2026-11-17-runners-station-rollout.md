# Station rollout: MicroOrch detach and dead-subscriber eviction (2026-11-17)

These changes reach a station only after the station pulls and restarts its group. Hot reload restarts an action server only while it is idle, so a restart by hand is the reliable route.

## What changes on a station

- **Action servers** (`helao/hexagon/app/action_host.py`): a status subscriber whose whole retry round fails is dropped. The orchestrator is never dropped. Without this, one dead subscriber (a force-killed or crashed runner) delays every status push by about 165 s, until the action server restarts.
- **MicroOrch runners** (`helao/core/runners/micro_orch.py`): a runner detaches from every server when it stops. Stop no longer waits out RPC timeouts against a server that never answered attach.
- **Launcher** (`launch.py`): hot reload does not restart a Reflex server while it is running runners (`/runners_busy`).

No dependency changes and no wire-format changes. The orchestrator and action servers do not need to update together.

## Per station

Do this when the group is idle: no sequence running, or the orchestrator stopped.

1. Stop the group: `CTRL-x` in the launcher console.
2. Pull the parent repo on `unstable`: `git -C <repo> pull`. Nested deployment repos need no update for this change.
3. Relaunch: `./helao.sh <prefix>` on Linux, `helao.bat <prefix>` on Windows.
4. Check the launch:
   - every server of the group binds its port;
   - the launcher reports no early exits;
   - `git -C <repo> log -1` shows the pulled commit.
5. If a runner was force-killed earlier on this station, a restart alone clears the dead subscriber. To check that eviction works without a restart, force-kill a runner and watch the action server's log. Expect `evicted unresponsive status subscriber <KEY> (<host>:<port>)` within about 3 minutes, after which status reaches the orchestrator promptly.

## Known limits

- A runner that blocks its own event loop for a whole retry round (about 2.5 min) is evicted and then waits forever on its next action. Force kill it. This cost was accepted.
- On Windows, `/runners` launching has not yet been run on a station. The Reflex backend's event loop must support subprocesses. Open `/runners` and press Refresh once to confirm.
