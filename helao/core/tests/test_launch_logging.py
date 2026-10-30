"""launch.py starts the collector before anything logs (spec §2)."""

import ast
from pathlib import Path


def _main_src():
    text = Path("launch.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    (main,) = [
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"
    ]
    return ast.get_source_segment(text, main)


def test_collector_started_and_env_set_before_launch_logger():
    src = _main_src()
    i_start = src.index("collector.start()")
    i_env = src.index("os.environ[LOG_ENDPOINT_ENV]")
    i_logger = src.index("LAUNCH_LOGGER = logging.make_logger(")
    assert i_start < i_env < i_logger


def test_collector_stopped_in_teardown_and_detach():
    src = _main_src()
    teardown = src[src.index("def teardown_group") : src.index("def restart_server")]
    assert "collector.stop()" in teardown
    detach = src[src.index("Disconnecting action monitor") :]
    assert "collector.stop()" in detach


def test_stale_txt_zip_blocks_removed():
    assert "Compressing:" not in Path("launch.py").read_text(encoding="utf-8")
    assert "Compressing:" not in Path("helao/helpers/helao_dirs.py").read_text(
        encoding="utf-8"
    )


def test_wants_collector_skips_visualizer_only_launchers():
    import launch

    for opt in ("liveonly", "gpvis"):
        assert launch.wants_collector(opt) is False
    for opt in ("", "nolive", "actionvis", "other"):
        assert launch.wants_collector(opt) is True


def test_main_gates_the_collector_on_wants_collector_and_registers_atexit():
    src = _main_src()
    assert "wants_collector(extraopt)" in src
    i_start = src.index("collector.start()")
    assert "atexit.register(collector.stop)" in src[i_start : i_start + 900]


def test_teardown_stops_collector_in_a_finally():
    src = _main_src()
    teardown = src[src.index("def teardown_group") : src.index("def restart_server")]
    fin = teardown[teardown.index("finally:") :]
    assert "collector.stop()" in fin
    assert teardown.index("graceful_shutdown_all()") < teardown.index("finally:")
