"""The old parameter name keeps working (spec §5.1, D9)."""

import helao.helpers.param_alias as param_alias
from helao.helpers.param_alias import resolve_sequence_path


def test_new_name_passes_through():
    assert resolve_sequence_path({"sequence_path": "/d/RUNS/2026/0925/seq"}) == (
        "/d/RUNS/2026/0925/seq"
    )


def test_old_name_is_accepted(caplog):
    # The warning is once-per-process by design, so the dedupe set has to be
    # cleared or this asserts on whatever an earlier test already consumed.
    param_alias._WARNED.discard("sequence_zip_path")
    with caplog.at_level("WARNING", logger=param_alias.LOGGER.name):
        got = resolve_sequence_path({"sequence_zip_path": "/d/RUNS_SYNCED/s.zip"})
    assert got == "/d/RUNS_SYNCED/s.zip"
    assert "sequence_zip_path" in caplog.text


def test_new_name_wins_when_both_are_present():
    params = {
        "sequence_path": "/new",
        "sequence_zip_path": "/old",
    }
    assert resolve_sequence_path(params) == "/new"


def test_empty_new_name_falls_back_to_the_old_one():
    # The analysis endpoints declare `sequence_path: str = ""`, and that default
    # is folded into action_params before the resolver ever sees it. A
    # presence test instead of a truthiness test would shadow every live caller
    # that still sends the old name.
    params = {"sequence_path": "", "sequence_zip_path": "/old"}
    assert resolve_sequence_path(params) == "/old"


def test_neither_present_is_none():
    assert resolve_sequence_path({}) is None


def test_the_syncer_dispatches_the_new_name():
    """The auto-analysis dispatch must fill the new key with a directory."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    for src in (
        "helao/core/drivers/data/sync_driver.py",
        "helao/hexagon/adapters/native/sync_driver.py",
    ):
        text = (root / src).read_text()
        assert '"sequence_path": str(prog.yml.target.parent)' in text, src
        assert '"sequence_zip_path": str(' not in text, src


def test_the_executor_still_accepts_the_old_key():
    """A live caller sending only `sequence_zip_path` must still analyze.

    This is the wiring the alias exists for: the executor reads the raw
    `action_params`, so reaching for `action_params["sequence_path"]` would
    raise KeyError on every unported `*_postseq` sequence in the deployments.
    """
    import asyncio
    from types import SimpleNamespace
    from uuid import uuid4

    from helao.core.drivers.data.analysis_driver import AnalysisExecutor

    seen = {}

    class _StubDriver:
        async def batch_calc(self, analysis_class, **kwargs):
            seen.update(kwargs)

    ex = object.__new__(AnalysisExecutor)
    ex.action_params = {"sequence_zip_path": "/d/RUNS/2026/0925/seq"}
    ex.driver = _StubDriver()  # type: ignore[assignment]
    ex.analysis_class = object()  # type: ignore[assignment]
    ex.active = SimpleNamespace(action=SimpleNamespace(action_uuid=uuid4()))

    result = asyncio.run(ex._exec())
    assert result["error"].value == "none", result
    assert seen["sequence_path"] == "/d/RUNS/2026/0925/seq"
