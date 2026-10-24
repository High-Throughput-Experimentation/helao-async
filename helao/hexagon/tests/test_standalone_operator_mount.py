"""The real hte standalone_operator builds a Bokeh document with the operator UI."""

from __future__ import annotations

import asyncio
import copy
from importlib import import_module
from pathlib import Path

import pytest
from bokeh.document import Document

REPO_ROOT = Path(__file__).resolve().parents[3]
VIS_CONFIG = REPO_ROOT / "helao" / "deploy" / "test" / "configs" / "goldenhexvis.yml"


@pytest.fixture()
def real_config(tmp_path, monkeypatch):
    """The gate config with its root redirected into tmp_path."""
    from helao.helpers import config_loader
    from helao.helpers.config_loader import read_config

    cfg = copy.deepcopy(read_config(str(VIS_CONFIG)))
    cfg["root"] = str(tmp_path)
    monkeypatch.setattr(config_loader, "CONFIG", cfg)
    return cfg


async def _cancel_new_tasks(before):
    for task in asyncio.all_tasks() - before:
        task.cancel()
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_standalone_operator_document_mounts_the_operator(real_config):
    operator = import_module("helao.deploy.hte.servers.operator.standalone_operator")
    before = asyncio.all_tasks()
    doc = Document()
    try:
        out = operator.makeBokehApp(
            doc,
            confPrefix="goldenhexvis",
            server_key="OPERATOR",
            helao_repo_root=str(REPO_ROOT),
        )
        assert out is doc
        assert doc.operator is not None  # type: ignore[attr-defined]
        assert len(doc.roots) >= 1
    finally:
        await _cancel_new_tasks(before)
