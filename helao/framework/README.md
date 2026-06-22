# helao.framework

Deployment-agnostic HELAO core, rebuilt as a layered hexagonal package.
See the design spec: `docs/superpowers/specs/2026-06-22-helao-framework-core-rewrite-design.md`.

## Layers

- `domain/` — pure logic, zero I/O. Imports only `models/` and `ports/`.
- `models/` — pydantic data models.
- `ports/` — abstract seams (Protocols): `clock`, `eventsink`, `storage`, `transport`. (`driver` lands in a later sub-project.)
- `adapters/` — concrete port implementations (I/O). `adapters/fakes/` holds in-memory test doubles.
- `app/` — wiring: composes domain + adapters into servers.
- `support/` — vendored generic utilities.

## Boundary rule

`domain/` may not import web/IO frameworks or `adapters`/`app`. Enforced by
`helao/framework/tests/test_boundaries.py`.

## Running tests

Always use the helao conda env (Python 3.12):

```bash
conda run -n helao python -m pytest          # run the suite
conda run -n helao python run_framework_tests.py   # suite + coverage gate (>=90% on domain+models)
```
