# operator

Standalone operator UI: a Bokeh app (`standalone_operator`) that talks to an orchestrator over HTTP and websockets. It is a generic framework server; the UI code is `helao/ui/bokeh/operator.py` and `helao/ui/shared/operator/`.

## Vendor software

No vendor software beyond the env files.

## Params

Host-level keys every server accepts: see docs/config-schema.md ("Group conventions for `params:`"). `doc_name` is also host-level (`helao/helpers/server_api.py:182` sets the document title); the operator reuses it as the page header text (`helao/ui/bokeh/operator.py:795`, default `BokehOperator`).

### `standalone_operator` (`bokeh:`)

All keys are optional.

| key | req | type | default | meaning / allowed values | read at |
|---|---|---|---|---|---|
| `orch_key` | no | str | `None` | Server key of the orchestrator to drive. When absent, the first `group: orchestrator` server in the config is used; with none, startup raises `ValueError`. A key that is not in `servers` raises `KeyError`. | `helao/deploy/hte/servers/operator/standalone_operator.py:31`, `helao/ui/shared/operator/orch_backend.py:59` |
| `poll_interval` | no | float (s) | `5.0` | Orchestrator poll interval of the remote backend. | `standalone_operator.py:32`, `orch_backend.py:63` |
| `plate_api` | no | str | `None` | Only the value `HTEPlateAPI` has an effect: it builds the shared plate-API client (needs the `HELAO_CREDENTIALS` environment variable, see `helao/helpers/plate_api.py`). Any other value leaves it unset. | `helao/ui/bokeh/operator.py:251` |
| `seqspec_parser_path` | no | str (file path) | `None` | Python file defining a `SpecParser`. Unset, missing, or failing to import disables the sequence-spec tab (a warning is logged). | `helao/ui/bokeh/operator.py:379`, `helao/ui/shared/operator/spec_parser.py:44` |
| `seqspec_folder_path` | no | str (dir) | `None` | Folder scanned for specification files. Ignored unless it is an existing directory. | `helao/ui/bokeh/operator.py:380` |
| `parser_kwargs` | no | dict | `{}` | Extra keyword arguments passed to the spec parser's `parser(...)` call. | `helao/ui/bokeh/operator.py:1861` |
| `skip_default_highlights` | no | list[str] | `[]` | Parameter-input names that are not highlighted when changed from their default. | `helao/ui/bokeh/operator.py:390` |

Example:
```yaml
params:
  orch_key: ORCH
  poll_interval: 5
  plate_api: HTEPlateAPI
  seqspec_parser_path: helao/deploy/hte/specifications/last3months.py
  seqspec_folder_path: C:\INST_hlo\DATA\RUNS
```

Notes:
- The operator also reads the first PAL server's `params.positions.custom` keys from the world config to fill its custom-position list (`helao/ui/bokeh/operator.py:278`); that key is documented under `pal`.
