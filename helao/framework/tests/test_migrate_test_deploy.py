"""SP7 Wave 3 — pilot-migration validation for the ``test`` deployment.

Proves the in-tree ``test`` deployment runs on ``helao.framework.*`` after the
Wave 2-E import-swap. Four groups (mirroring the SP7 design §5):

* **T1 lib_decorators** — ``@experiment`` tags ``experiment_version``, injects the
  parent :class:`RunExperiment` into ``EXPERIMENT_CTX`` for the call and resets the
  token afterwards (positional, keyword, and inherited forms); ``@sequence`` tags
  ``sequence_version``.
* **T2 import-resolution** — every migrated deploy module is free of residual
  ``helao.core.*`` / ``helao.helpers.*`` imports (static AST scan), and each
  importable module (those whose optional 3rd-party deps are installed) imports
  with no ``ImportError``.
* **T3 golden-master (WsSim, in-process)** — the migrated ``ws_simulator`` app is
  driven through an in-process ``httpx`` ASGI client; an ``acquire_data`` action
  runs end-to-end on the framework ``BaseAPI`` and produces a structurally-correct
  ``.hlo`` (``%%`` separator + JSON-per-row data) and a ``.act`` meta file.
* **T4 runner import smoke** — the MicroOrch example runners resolve to
  ``helao.framework.*`` with no ``ImportError``.

The driver background-poll loop and orchestrator-driven request body are SP8
concerns, so T3 seeds the live buffer via ``base.put_lbuf`` and POSTs a full
action body itself, isolating the SP7 action-execution path from SP8 driver
lifecycle / live-orch wiring.
"""
import ast
import asyncio
import importlib
import json
import uuid as _uuid
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from helao.framework.support.lib_decorators import experiment, sequence
from helao.framework.domain.plan_makers import EXPERIMENT_CTX
from helao.framework.domain.run_models import RunExperiment

REPO_ROOT = Path(__file__).resolve().parents[3]
DEPLOY_TEST = REPO_ROOT / "helao" / "deploy" / "test"


# ---------------------------------------------------------------------------
# T1 — lib_decorators
# ---------------------------------------------------------------------------


def test_experiment_decorator_tags_version_and_resets_ctx():
    @experiment(version=2)
    def MY_exp(foo: float = 1.0):
        # ctx is published during the call
        return EXPERIMENT_CTX.get(None)

    assert MY_exp.experiment_version == 2
    exp = RunExperiment(experiment_name="e")
    assert EXPERIMENT_CTX.get(None) is None
    seen = MY_exp(exp)  # positional RunExperiment
    assert seen is exp
    # token reset after the call
    assert EXPERIMENT_CTX.get(None) is None


def test_experiment_decorator_accepts_keyword_and_injects_declared_param():
    captured = {}

    @experiment()
    def MY_exp(experiment, bar: int = 0):
        captured["exp"] = experiment
        captured["ctx"] = EXPERIMENT_CTX.get(None)
        return bar

    exp = RunExperiment(experiment_name="e2")
    result = MY_exp(experiment=exp, bar=7)
    assert result == 7
    assert captured["exp"] is exp  # declared param received the parent
    assert captured["ctx"] is exp  # and it was on the ctx during the call


def test_experiment_decorator_inherits_ctx_when_unset():
    @experiment()
    def inner():
        return EXPERIMENT_CTX.get(None)

    exp = RunExperiment(experiment_name="parent")
    token = EXPERIMENT_CTX.set(exp)
    try:
        assert inner() is exp  # inherited from the surrounding ctx
    finally:
        EXPERIMENT_CTX.reset(token)


def test_sequence_decorator_tags_version_without_wrapping():
    @sequence(version=3)
    def MY_seq(foo: float = 1.0):
        return foo

    assert MY_seq.sequence_version == 3
    assert MY_seq(5.0) == 5.0  # not wrapped — call passes through unchanged


# ---------------------------------------------------------------------------
# T2 — import-resolution
# ---------------------------------------------------------------------------

# (dotted module, source path) for every file the Wave 2-E swap touched.
MIGRATED = [
    ("helao.deploy.test.servers.action.ws_simulator", "servers/action/ws_simulator.py"),
    ("helao.deploy.test.servers.action.cpsim_server", "servers/action/cpsim_server.py"),
    ("helao.deploy.test.servers.action.gpsim_server", "servers/action/gpsim_server.py"),
    ("helao.deploy.test.servers.action.motion_simulator", "servers/action/motion_simulator.py"),
    ("helao.deploy.test.servers.action.pstat_simulator", "servers/action/pstat_simulator.py"),
    ("helao.deploy.test.servers.action.analysis_simulator", "servers/action/analysis_simulator.py"),
    ("helao.deploy.test.servers.action.archive_simulator", "servers/action/archive_simulator.py"),
    ("helao.deploy.test.experiments.TEST_exp", "experiments/TEST_exp.py"),
    ("helao.deploy.test.experiments.OERSIM_exp", "experiments/OERSIM_exp.py"),
    ("helao.deploy.test.experiments.simulatews_exp", "experiments/simulatews_exp.py"),
    ("helao.deploy.test.sequences.TEST_seq", "sequences/TEST_seq.py"),
    ("helao.deploy.test.sequences.OERSIM_seq", "sequences/OERSIM_seq.py"),
    ("helao.deploy.test.runners.test_runner", "runners/test_runner.py"),
    ("helao.deploy.test.runners.oersim_runner", "runners/oersim_runner.py"),
    ("helao.deploy.test.runners.simulatews_runner", "runners/simulatews_runner.py"),
    ("helao.deploy.test.drivers.data.gpsim_driver", "drivers/data/gpsim_driver.py"),
    ("helao.deploy.test.drivers.pstat.cpsim_driver", "drivers/pstat/cpsim_driver.py"),
]


def _legacy_import_names(source: str) -> list[str]:
    """Return any ``helao.core.*`` / ``helao.helpers.*`` *imported* module names."""
    tree = ast.parse(source)
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            bad += [a.name for a in node.names
                    if a.name.startswith(("helao.core", "helao.helpers"))]
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod.startswith(("helao.core", "helao.helpers")):
                bad.append(mod)
    return bad


@pytest.mark.parametrize("dotted,relpath", MIGRATED, ids=[m[0] for m in MIGRATED])
def test_no_residual_legacy_imports(dotted, relpath):
    source = (DEPLOY_TEST / relpath).read_text(encoding="utf-8")
    bad = _legacy_import_names(source)
    assert not bad, f"{relpath} still imports legacy modules: {bad}"


@pytest.mark.parametrize("dotted,relpath", MIGRATED, ids=[m[0] for m in MIGRATED])
def test_migrated_module_imports(dotted, relpath):
    try:
        importlib.import_module(dotted)
    except ModuleNotFoundError as e:
        # optional 3rd-party deps (e.g. gpflow) are not installed in this env;
        # the framework import paths themselves resolve. Skip rather than fail.
        missing = (e.name or "").split(".")[0]
        if missing and not missing.startswith("helao"):
            pytest.skip(f"optional dependency {missing!r} not installed")
        raise


# ---------------------------------------------------------------------------
# T3 — golden-master via the migrated ws_simulator (in-process ASGI)
# ---------------------------------------------------------------------------


def _action_body(file_conn: str) -> dict:
    now = datetime.now().isoformat()
    return {
        "action": {
            "action_name": "acquire_data",
            "action_uuid": str(_uuid.uuid4()),
            "action_timestamp": now,
            "sequence_timestamp": now,
            "experiment_timestamp": now,
            "sequence_name": "seq",
            "experiment_name": "exp",
            "action_output_dir": "26.25/0623/0__0__SIM__acquire_data",
            "save_act": True,
            "save_data": True,
            "file_conn_keys": [file_conn],
            "action_params": {"duration": 0.2, "acquisition_rate": 0.05},
        }
    }


@pytest.mark.asyncio
async def test_ws_simulator_runs_action_and_writes_hlo():
    from helao.deploy.test.servers.action.ws_simulator import makeApp

    app = makeApp("SIM")
    save_root = Path(app.state.save_root)
    await app.base.myinit()  # start the live-buffer drain loop

    # SP8 owns the driver poll loop; seed the live buffer here so the executor
    # has a snapshot to forward on each poll.
    async def _seed():
        for _ in range(40):
            await app.base.put_lbuf({"sim_dict": {"series_0": 1.0, "series_1": 2.0}})
            await asyncio.sleep(0.02)

    seeder = asyncio.create_task(_seed())
    await asyncio.sleep(0.05)  # let the drain populate the buffer first

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/SIM/acquire_data", json=_action_body(str(_uuid.uuid4()))
        )
        assert resp.status_code == 200, resp.text
        await asyncio.sleep(0.5)  # let the bounded-duration executor finish
    seeder.cancel()

    hlo_files = list(save_root.rglob("*.hlo"))
    act_files = list(save_root.rglob("*.act"))
    assert hlo_files, "migrated ws_simulator wrote no .hlo file"
    assert act_files, "migrated ws_simulator wrote no .act meta"

    text = hlo_files[0].read_text(encoding="utf-8")
    # structural parity with the legacy HLO layout: a '%%' header/data separator
    # followed by one JSON object per data row (header content / hloheader model
    # stamping is SP8).
    assert "%%\n" in text
    body = text.split("%%\n", 1)[1].strip().splitlines()
    assert body, "no data rows written after the %% separator"
    row = json.loads(body[0])
    assert "series_0" in row and "epoch_s" in row


# ---------------------------------------------------------------------------
# T4 — runner import smoke
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "dotted",
    [
        "helao.deploy.test.runners.test_runner",
        "helao.deploy.test.runners.oersim_runner",
        "helao.deploy.test.runners.simulatews_runner",
    ],
)
def test_runner_imports(dotted):
    try:
        importlib.import_module(dotted)
    except ModuleNotFoundError as e:
        missing = (e.name or "").split(".")[0]
        if missing and not missing.startswith("helao"):
            pytest.skip(f"optional dependency {missing!r} not installed")
        raise
