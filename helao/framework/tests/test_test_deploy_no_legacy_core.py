# helao/framework/tests/test_test_deploy_no_legacy_core.py
"""Guard: the test deployment no longer imports legacy helao.core.servers."""
import os
import glob


def test_no_legacy_core_servers_import_in_test_deploy():
    root = os.path.join(os.path.dirname(__file__), "..", "..", "deploy", "test")
    root = os.path.abspath(root)
    offenders = []
    for path in glob.glob(os.path.join(root, "**", "*.py"), recursive=True):
        if "__pycache__" in path or os.sep + "tests" + os.sep in path:
            continue
        with open(path) as f:
            text = f.read()
        if "helao.core.servers" in text:
            offenders.append(os.path.relpath(path, root))
    assert offenders == [], f"test deploy still imports legacy core servers: {offenders}"
