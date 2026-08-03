"""Library resolution for configs launched from outside the deploy tree.

A config does not have to live at ``helao/deploy/<deployment>/configs/``. A
station operator copying one into ``USER_CONFIG``, editing it, and launching it
by full path is a supported workflow, and it used to leave the orchestrator
with an empty experiment and sequence library: the deployment was read as "two
directories up from the config", which for
``C:\\INST_hlo\\DATA\\USER_CONFIG\\eche10.yml`` is ``DATA``, and the resulting
``helao/deploy/DATA/experiments`` failed the directory check that returned
early -- before the per-library fallbacks that would have found every module.
"""

import os

import pytest

from helao.helpers import config_loader
from helao.helpers.import_autolibs import (
    deployment_from_config_path,
    import_autolibs,
)

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

IN_TREE = os.path.join(REPO_ROOT, "helao", "deploy", "test", "configs", "golden.yml")
#: The reported failure, in the reporter's own layout.
COPIED_OUT = os.path.join(
    "C:" + os.sep, "INST_hlo", "DATA", "USER_CONFIG", "eche10.yml"
)


@pytest.fixture(autouse=True)
def _at_repo_root(monkeypatch):
    """The deployment-tree fallbacks glob relative paths."""
    monkeypatch.chdir(REPO_ROOT)


@pytest.fixture(autouse=True)
def _no_cached_libs(monkeypatch):
    """Each case resolves from scratch; the module caches by config path."""
    monkeypatch.setattr("helao.helpers.import_autolibs._AUTOLIB_CACHE", {})


# -- deployment derivation ---------------------------------------------------


def test_an_in_tree_config_names_its_deployment():
    assert deployment_from_config_path(IN_TREE) == "test"


def test_a_config_outside_the_tree_names_no_deployment():
    """Answering 'DATA' here is what pointed every lookup at a path that has
    never existed."""
    assert deployment_from_config_path(COPIED_OUT) is None


def test_a_bare_deploy_directory_elsewhere_is_not_a_deployment():
    """Only `helao/deploy/<name>` counts -- an unrelated `deploy` directory in
    the path is not a HELAO deployment."""
    assert (
        deployment_from_config_path(os.path.join("srv", "deploy", "x", "c.yml")) is None
    )


def test_an_empty_path_is_answerable():
    assert deployment_from_config_path("") is None


# -- library loading ---------------------------------------------------------


def _config(path, **extra):
    cfg = {
        "loaded_config_path": path,
        "experiment_libraries": ["simulatews_exp"],
        "sequence_libraries": ["TEST_seq"],
    }
    cfg.update(extra)
    return cfg


def test_an_in_tree_config_loads_its_libraries():
    lib, _, _ = import_autolibs(_config(IN_TREE), lib_type="experiment")
    assert "SIM_websocket_data" in lib


def test_a_config_copied_out_of_the_tree_still_loads_its_libraries():
    """The regression: an unresolvable library directory returned an empty
    library, so the operator had nothing to select."""
    lib, _, _ = import_autolibs(_config(COPIED_OUT), lib_type="experiment")
    assert "SIM_websocket_data" in lib


def test_the_launcher_resolved_deployment_is_used_when_the_path_cannot_say(
    monkeypatch,
):
    """Only the launcher knows which deployment an out-of-tree config's servers
    were imported from."""
    monkeypatch.setattr(config_loader, "CONFIG", {"deployment": "test"})
    lib, _, codepath = import_autolibs(_config(COPIED_OUT), lib_type="experiment")
    assert "SIM_websocket_data" in lib
    assert "deploy/test/experiments" in codepath["SIM_websocket_data"]


def test_sequences_resolve_the_same_way():
    lib, _, _ = import_autolibs(_config(COPIED_OUT), lib_type="sequence")
    assert lib


def test_an_explicit_library_path_still_wins():
    lib, _, _ = import_autolibs(
        _config(
            COPIED_OUT,
            experiment_path=os.path.join("helao", "deploy", "test", "experiments"),
        ),
        lib_type="experiment",
    )
    assert "SIM_websocket_data" in lib


def test_an_explicit_path_that_does_not_exist_falls_back_rather_than_yielding_nothing():
    lib, _, _ = import_autolibs(
        _config(IN_TREE, experiment_path=os.path.join("nowhere", "experiments")),
        lib_type="experiment",
    )
    assert "SIM_websocket_data" in lib


def test_libraries_written_as_relative_paths_resolve_against_the_working_dir():
    """The reported config's form: entries written as repo-relative ``.py``
    paths, which `helao.bat` launching from the repo root makes valid. These
    never needed a library directory at all -- the invalid-lib_dir check
    returned before a single entry was looked at, so a correct path was
    discarded unread.
    """
    lib, _, codepath = import_autolibs(
        _config(
            COPIED_OUT,
            experiment_libraries=[
                os.path.join("helao", "deploy", "test", "experiments", "TEST_exp.py")
            ],
        ),
        lib_type="experiment",
    )
    assert lib
    assert all("deploy/test/experiments" in p for p in codepath.values())


def test_a_forward_slash_library_path_resolves_on_any_platform():
    """Configs are written with ``/`` even for Windows stations."""
    lib, _, _ = import_autolibs(
        _config(
            COPIED_OUT,
            sequence_libraries=["helao/deploy/test/sequences/TEST_seq.py"],
        ),
        lib_type="sequence",
    )
    assert lib


# -- working directory -------------------------------------------------------
#
# The Reflex process runs from its app directory, not the repo root. Every path
# here used to be resolved against the cwd, so the same config that worked
# under the FastAPI and Bokeh launchers found nothing under Reflex.


def test_a_bare_library_name_resolves_from_any_working_directory(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    lib, _, _ = import_autolibs(_config(IN_TREE), lib_type="experiment")
    assert "SIM_websocket_data" in lib


def test_a_relative_library_path_resolves_from_any_working_directory(
    monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    lib, _, _ = import_autolibs(
        _config(
            COPIED_OUT,
            experiment_libraries=["helao/deploy/test/experiments/TEST_exp.py"],
        ),
        lib_type="experiment",
    )
    assert lib


def test_the_deployment_fallbacks_resolve_from_any_working_directory(
    monkeypatch, tmp_path
):
    """The 'hte' fallback and the cross-deployment glob, reached only when the
    library directory is unresolvable -- exactly the Reflex case."""
    monkeypatch.chdir(tmp_path)
    lib, _, _ = import_autolibs(_config(COPIED_OUT), lib_type="experiment")
    assert "SIM_websocket_data" in lib


def test_a_relative_library_directory_resolves_from_any_working_directory(
    monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    lib, _, _ = import_autolibs(
        _config(
            COPIED_OUT,
            experiment_path=os.path.join("helao", "deploy", "test", "experiments"),
        ),
        lib_type="experiment",
    )
    assert "SIM_websocket_data" in lib


def test_a_library_no_deployment_has_is_still_an_error():
    """The fallbacks must not turn a typo into a silently empty library."""
    with pytest.raises(FileNotFoundError):
        import_autolibs(
            _config(COPIED_OUT, experiment_libraries=["no_such_exp"]),
            lib_type="experiment",
        )


def test_a_missing_user_library_directory_is_skipped_not_raised():
    """Reachable only now that an unresolvable lib_dir no longer returns first;
    os.listdir on an absent directory would raise."""
    lib, _, _ = import_autolibs(
        _config(COPIED_OUT),
        user_lib_dir=os.path.join("nowhere", "user"),
        lib_type="experiment",
    )
    assert "SIM_websocket_data" in lib
