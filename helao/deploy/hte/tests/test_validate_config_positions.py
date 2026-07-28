"""Launch guardrail test: at most one server may declare params.positions.

Run (from repo root, ``helao`` conda env, ``PYTHONPATH`` = repo root)::

    conda run -n helao python helao/deploy/hte/tests/test_validate_config_positions.py

Phase 4 adds a launch-blocking check to ``launch.validateConfig``: a config in
which more than one server declares ``params.positions`` must be rejected
(``validateConfig`` returns ``False``). After Phase 4 each hte PAL-bearing
config has exactly one positions owner (SAMPLE), so the real configs pass.
"""

import glob
import logging
import re
from types import SimpleNamespace

import yaml

import launch
from launch import validateConfig

# validateConfig logs via the module-global LAUNCH_LOGGER (set by launch.main
# at runtime, None on bare import); supply a real logger for the test.
launch.LAUNCH_LOGGER = logging.getLogger("test_validate_config")

_PIDD = SimpleNamespace(reqKeys=("host", "port", "group"), codeKeys=("fast", "bokeh"))


def _base_server(port, positions=False):
    d = {
        "host": "127.0.0.1",
        "port": port,
        "group": "action",
        "fast": "some_server",
        "params": {},
    }
    if positions:
        d["params"]["positions"] = {"custom": {"cell1_we": "cell"}}
    return d


def _test_two_positions_blocks_rejected():
    conf = {
        "servers": {
            "SAMPLE": _base_server(8009, positions=True),
            "PAL": _base_server(8007, positions=True),  # deliberate 2nd owner
        }
    }
    ok = validateConfig(_PIDD, conf, ".")
    assert ok is False, "config with TWO positions blocks must be REJECTED"
    print("PASS: two-positions config rejected by validateConfig")


def _test_single_positions_block_accepted():
    conf = {
        "servers": {
            "SAMPLE": _base_server(8009, positions=True),
            "PAL": _base_server(8007, positions=False),
        }
    }
    ok = validateConfig(_PIDD, conf, ".")
    assert ok is True, "config with ONE positions block must be accepted"
    print("PASS: single-positions config accepted by validateConfig")


def _test_real_post_p4_configs_pass():
    files = [
        f
        for f in sorted(glob.glob("helao/deploy/hte/configs/*.yml"))
        if re.search(r"^\s*fast:\s*sample_server", open(f).read(), re.M)
    ]
    assert files, "no post-P4 hte configs found"
    for f in files:
        conf = yaml.safe_load(open(f))
        owners = [
            s
            for s, d in conf["servers"].items()
            if isinstance(d.get("params"), dict) and d["params"].get("positions")
        ]
        assert len(owners) == 1, f"{f}: expected 1 positions owner, got {owners}"
        assert validateConfig(
            _PIDD, conf, "."
        ), f"{f}: validateConfig unexpectedly failed"
    print(
        f"PASS: {len(files)} real post-P4 configs each have 1 positions owner and validate"
    )


def main():
    _test_two_positions_blocks_rejected()
    _test_single_positions_block_accepted()
    _test_real_post_p4_configs_pass()
    print("ALL VALIDATECONFIG POSITIONS CHECKS PASSED")


if __name__ == "__main__":
    main()
