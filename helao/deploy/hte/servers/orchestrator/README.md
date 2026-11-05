# orchestrator

Orchestrator entrypoint (`async_orch2`): builds the framework `OrchHost` for an orchestration group. It is a generic framework server.

## Vendor software

No vendor software beyond the env files.

## Params

Host-level keys every server accepts: see docs/config-schema.md ("Group conventions for `params:`").

### `async_orch2` (`fast:`)

`makeApp` passes no params to anything itself (`helao/deploy/hte/servers/orchestrator/async_orch2.py:44`); every key it honours is read by `OrchHost` and is covered by the host-level docs. Station configs commonly use `params: {}`.

Unused keys seen in configs:
- `enable_op`: deprecated and ignored; the operator runs as a separate `group: operator` server (`helao/helpers/config_loader.py:170`).
