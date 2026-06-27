"""SP-ARTIFACT Task 2: app-rooting tests.

Verifies that:
1. Action app built from a config with ``root=<tmp>`` has
   ``storage.save_root == <tmp>`` and ``helaodirs.save_root == <tmp>/RUNS_ACTIVE``.
2. Orch app built from a config with ``root=<tmp>`` has the same properties.
3. When NO ``root`` key is present, a tempdir is used and ``helaodirs is None``.
4. Base construction does NOT zip pre-existing ``*.txt`` logs (Constraint 6) —
   confirmed by dropping a dummy log under ``<tmp>/LOGS/<server>/`` and asserting
   it survives after app construction.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _patch_config(cfg_dict):
    """Return a context manager that patches CONFIG in all relevant modules."""
    from munch import munchify
    munch_cfg = munchify(cfg_dict)

    patches = [
        mock.patch("helao.framework.support.config_loader.CONFIG", munch_cfg),
        mock.patch("helao.framework.app.base_api.FrameworkBase._load_global_cfg",
                   staticmethod(lambda: dict(cfg_dict))),
    ]
    return patches


# ---------------------------------------------------------------------------
# Action app rooting
# ---------------------------------------------------------------------------

def test_action_app_save_root_from_config(tmp_path):
    """makeActionApp with CONFIG.root=<tmp> must root storage at <tmp>."""
    root = str(tmp_path / "INST")
    os.makedirs(root, exist_ok=True)
    cfg = {"root": root, "servers": {}}

    from munch import munchify
    munch_cfg = munchify(cfg)

    with mock.patch("helao.framework.support.config_loader.CONFIG", munch_cfg), \
         mock.patch("helao.framework.app.factory.CONFIG", munch_cfg, create=True):
        from helao.framework.app.factory import makeActionApp
        app = makeActionApp("SRV")

    base = app.state.base
    assert str(base.storage.save_root) == root, (
        f"Expected save_root={root}, got {base.storage.save_root}"
    )
    # helaodirs must be set and point at RUNS_ACTIVE
    assert base.helaodirs is not None, "helaodirs should be set when config has root"
    assert str(base.helaodirs.save_root) == os.path.join(root, "RUNS_ACTIVE"), (
        f"helaodirs.save_root should be <root>/RUNS_ACTIVE, got {base.helaodirs.save_root}"
    )
    # app.state.save_root must be the config root
    assert str(app.state.save_root) == root


def test_action_app_save_root_explicit_wins(tmp_path):
    """Explicit save_root= arg must take priority over config root."""
    root = str(tmp_path / "INST")
    explicit = str(tmp_path / "EXPLICIT")
    os.makedirs(root, exist_ok=True)
    os.makedirs(explicit, exist_ok=True)
    cfg = {"root": root, "servers": {}}

    from munch import munchify
    munch_cfg = munchify(cfg)

    with mock.patch("helao.framework.support.config_loader.CONFIG", munch_cfg), \
         mock.patch("helao.framework.app.factory.CONFIG", munch_cfg, create=True):
        from helao.framework.app.factory import makeActionApp
        app = makeActionApp("SRV", save_root=explicit)

    base = app.state.base
    assert str(base.storage.save_root) == explicit


def test_action_app_no_root_uses_tempdir(tmp_path):
    """makeActionApp without config root must fall back to a tempdir."""
    with mock.patch("helao.framework.support.config_loader.CONFIG", None), \
         mock.patch("helao.framework.app.factory.CONFIG", None, create=True):
        from helao.framework.app.factory import makeActionApp
        app = makeActionApp("SRV2")

    base = app.state.base
    # Save root must exist and be a directory (tempdir created)
    assert os.path.isdir(str(base.storage.save_root))
    # helaodirs must be None when no root key
    assert base.helaodirs is None, "helaodirs should be None when config has no root"


# ---------------------------------------------------------------------------
# Orch app rooting
# ---------------------------------------------------------------------------

def test_orch_app_save_root_from_config(tmp_path):
    """makeOrchApp with CONFIG.root=<tmp> must root storage at <tmp>."""
    root = str(tmp_path / "INST_ORCH")
    os.makedirs(root, exist_ok=True)
    cfg = {"root": root, "servers": {}}

    from munch import munchify
    munch_cfg = munchify(cfg)

    with mock.patch("helao.framework.support.config_loader.CONFIG", munch_cfg), \
         mock.patch("helao.framework.app.factory.CONFIG", munch_cfg, create=True):
        from helao.framework.app.orch_api import makeOrchApp, OrchPorts
        from helao.framework.adapters.fs_storage import FsStorage
        from helao.framework.adapters.ntp_clock import NtpClock
        from helao.framework.adapters.queue_eventsink import QueueEventSink
        from helao.framework.adapters.fakes.transport import FakeTransport

        ports = OrchPorts(
            transport=FakeTransport(),
            storage=FsStorage(save_root=root),  # orch ports storage is separate
            eventsink=QueueEventSink(),
            clock=NtpClock(),
        )
        app = makeOrchApp("ORCH", ports=ports)

    # The orch-base (app.state.base) is separate from orch ports storage.
    # Its save_root should be the config root (not RUNS_HLO/<server_key>).
    base = app.state.base
    assert str(base.storage.save_root) == root, (
        f"Orch base save_root should be config root={root}, got {base.storage.save_root}"
    )


def test_orch_app_no_root_uses_tempdir():
    """makeOrchApp without config root must fall back to a tempdir for orch-base."""
    with mock.patch("helao.framework.support.config_loader.CONFIG", None), \
         mock.patch("helao.framework.app.factory.CONFIG", None, create=True):
        from helao.framework.app.orch_api import makeOrchApp, OrchPorts
        from helao.framework.adapters.fs_storage import FsStorage
        from helao.framework.adapters.ntp_clock import NtpClock
        from helao.framework.adapters.queue_eventsink import QueueEventSink
        from helao.framework.adapters.fakes.transport import FakeTransport
        import tempfile

        tmp = tempfile.mkdtemp()
        ports = OrchPorts(
            transport=FakeTransport(),
            storage=FsStorage(save_root=tmp),
            eventsink=QueueEventSink(),
            clock=NtpClock(),
        )
        app = makeOrchApp("ORCH", ports=ports)

    base = app.state.base
    # Must be a valid directory path (tempdir created)
    assert os.path.isdir(str(base.storage.save_root))
    # helaodirs must be None when no root
    assert base.helaodirs is None


# ---------------------------------------------------------------------------
# No log-zip on construction (Constraint 6)
# ---------------------------------------------------------------------------

def test_base_construction_does_not_zip_logs(tmp_path):
    """Base construction MUST NOT rotate/zip pre-existing *.txt logs.

    The launcher already rotates logs; calling helao_dirs with server_name would
    re-zip them. We call without server_name so existing logs survive.
    """
    root = str(tmp_path / "INST_LOG")
    server = "SRV"
    log_dir = os.path.join(root, "LOGS", server)
    os.makedirs(log_dir, exist_ok=True)
    dummy_log = os.path.join(log_dir, f"{server}.txt")
    with open(dummy_log, "w") as f:
        f.write("[12:34:56] dummy log line\n")

    cfg = {"root": root, "servers": {}}
    from munch import munchify
    munch_cfg = munchify(cfg)

    with mock.patch("helao.framework.support.config_loader.CONFIG", munch_cfg), \
         mock.patch("helao.framework.app.factory.CONFIG", munch_cfg, create=True):
        from helao.framework.app.factory import makeActionApp
        makeActionApp(server)

    # The dummy log must still exist (not zipped away by Base construction)
    assert os.path.exists(dummy_log), (
        f"Base construction must not zip logs — {dummy_log} was removed"
    )
    # No zip should have been created
    zips = [n for n in os.listdir(log_dir) if n.endswith(".zip")]
    assert not zips, f"Base construction created unexpected zip(s): {zips}"
