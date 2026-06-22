# Framework Support Utilities — Design Spec (Sub-project 2)

**Date:** 2026-06-22
**Status:** Approved (standing authorization)
**Parent spec:** `docs/superpowers/specs/2026-06-22-helao-framework-core-rewrite-design.md` (§3 `support/`)
**Branch:** stacked on `feat/framework-scaffold` (PR #176), per user directive (all sub-projects on one branch).

---

## 1. Goal

Vendor the deployment-agnostic generic utilities the framework needs into `helao/framework/support/`, cleaned to framework-only imports, pure where practical, and pytest-covered. Depends on SP0 (scaffold) and SP1 (models).

## 2. Scope: leaf utilities only

Port these, in dependency order:

| Module | Source | Notes |
|---|---|---|
| `time_utils.py` | `helao/helpers/time_utils.py` | `gen_uuid`, `set_time`, NTP offset read/save. Pure stdlib (+ntplib). Leaf. |
| `make_str_enum.py` | `helao/helpers/make_str_enum.py` | `make_str_enum` factory + pydantic JSON-schema hooks. Used 23× by deployments. |
| `constants.py` | `helao/helpers/constants.py` | Imports `MachineModel` → repoint to `helao.framework.models.machine`. |
| `helao_logging.py` | `helao/helpers/helao_logging.py` | `make_logger`/`LOGGER`. Depends on `time_utils.read_saved_offset`. |
| `yml_tools.py` | `helao/helpers/yml_tools.py` | yaml load/dump (ruamel) + remote fetch (aiohttp). |
| `config_loader.py` | `helao/helpers/config_loader.py` | Prefix→config resolution, global `CONFIG`. |
| `codehash.py` | derive from `helao/helpers/import_autolibs.py` + `helao/core/version.py` | Small util: stable hash of a python source string/file (used for sequence/experiment code versioning). |

Already ported in SP1 and reused here: `support/version.py`, `models/errors.py`.

## 3. Out of scope

- **`dispatcher.py`** and **`helao/core/rpc/` (zmq RPC)** — these are the inter-server **transport mechanism**, coupling to models + aiohttp + zmq. They belong to the transport **adapter** (SP5), implementing the `ports/transport.py` Protocol, not to generic `support/`. (Parent spec listed dispatcher under support; this is a deliberate refinement — it is an adapter concern.)
- Runtime/domain logic, action servers, orchestrator.
- Deployment migration; old `helao/helpers` stays untouched.

## 4. Cleanups (rewrite, not copy)

1. **Framework-only imports.** Repoint every `helao.core.*` / `helao.helpers.*` import to `helao.framework.*`. No imports of the old packages remain under `support/`.
2. **No import-time side effects.** No network/disk/subprocess at module import or default-factory time (SP1 already hit this in `version.py`). `config_loader`'s module-level `CONFIG` global: keep the API but ensure merely importing the module does not read a config file — resolution happens on an explicit call.
3. **Pydantic v2 hygiene** where pydantic is used (`make_str_enum`, `config_loader`).
4. **Keep public function/signature names** that deployments import (`make_logger`, `gen_uuid`, `set_time`, `make_str_enum`, config-loader entry points) so later deployment migration is an import-path change.
5. `support/` may import `models/` and other `support/` modules; it must NOT import `adapters/`, `app/`, `domain/`, or web frameworks.

## 5. Testing

- pytest module per ported util under `helao/framework/tests/` (`test_support_time.py`, `test_support_logging.py`, `test_support_enum.py`, `test_support_constants.py`, `test_support_yml.py`, `test_support_config.py`, `test_support_codehash.py`).
- Port relevant assertions from existing tests where they exist (`helao/core/tests/unit_test_logging.py`, `unit_test_config_loader.py`).
- Mock disk/network: `yml_tools` remote fetch and `config_loader` file resolution tested against tmp files / monkeypatched fetch, never real network.
- **Coverage gate:** the gate enforces ≥90% on `domain/`+`models/`. `support/` is not gated by default; nonetheless target ≥90% on each ported `support/` module as a quality bar (add `support/` to the gated prefixes OR assert per-module coverage in a test — implementer's choice, must be enforced).

## 6. Risks

| Risk | Mitigation |
|---|---|
| `config_loader` global `CONFIG` singleton hides coupling | Port API as-is but no import-time read; note for later explicit-injection refactor (domain SPs) |
| NTP/time utils touch network at import | Ensure offset read is lazy/file-based; no socket at import |
| Hidden dep on `dispatcher`/rpc | Out of scope — if a ported util references it, stub the seam or defer that util |
