"""Unit tests for the per-config Reflex bundle: its layout, stamp, and build.

The stamp is the only thing standing between a station and a silently wrong
frontend, and every way it can fail fails *quietly*: a bundle baked for another
port renders and then refuses every WebSocket, a stub module map makes every
comparison pass, a merged build tree keeps a deleted panel compiled in. So each
test here is written to be able to actually fail -- the staleness cases are
parameterized over ``COMPARED_FIELDS`` rather than spot-checking ``api_url``,
because a test that covers one field lets the other eight rot.
"""

import json
import os
import threading
import zipfile

import pytest

import launch
import reflex_bundle as rb

# --- Layout -----------------------------------------------------------------


def test_bundles_live_under_the_server_root_when_there_is_one():
    assert rb.install_dir("/repo", "/data", "golden", "UI") == os.path.join(
        "/data", "STATES", "reflex-bundles", "golden_UI", "helao_ui"
    )


def test_bundles_fall_back_into_the_repo_when_the_config_has_no_root():
    assert rb.install_dir("/repo", None, "golden", "UI").startswith(
        os.path.join("/repo", ".reflex-bundle")
    )


def test_each_server_of_one_config_gets_its_own_bundle():
    """Two ``reflex:`` servers in one config listen on different ports.

    Sharing one bundle between them would serve the second a frontend baked
    for the first's backend URL -- a page that renders and then never connects.
    """
    first = rb.install_dir("/repo", "/data", "golden", "UI")
    second = rb.install_dir("/repo", "/data", "golden", "UI2")
    assert first != second


def test_the_legacy_bundle_path_cannot_collide_with_a_config_bundle():
    legacy = rb.legacy_bundle_dir("/repo")
    assert legacy != rb.install_dir("/repo", None, "golden", "UI")


def test_the_stamp_sits_beside_the_bundle_not_inside_it():
    """Inside, the export's own rmtree/replace would take the stamp with it."""
    stamp = rb.stamp_path("/repo", "/data", "golden", "UI")
    assert not stamp.startswith(rb.install_dir("/repo", "/data", "golden", "UI"))
    assert os.path.dirname(stamp) == rb.bundle_dir("/repo", "/data", "golden", "UI")


# --- The index.html guards --------------------------------------------------


def _make_bundle(path, index_text="<html></html>"):
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "index.html"), "w", encoding="utf8") as handle:
        handle.write(index_text)
    return str(path)


def test_a_directory_without_index_html_is_not_usable(tmp_path):
    (tmp_path / "helao_ui").mkdir()
    assert rb.usable_bundle(str(tmp_path / "helao_ui")) is False


def test_a_zero_byte_index_html_is_not_usable(tmp_path):
    """An interrupted export leaves a truncated index.html.

    Serving it yields a blank browser page and a silent log; treating it as
    absent routes into the loud failure path instead.
    """
    assert rb.usable_bundle(_make_bundle(tmp_path / "helao_ui", "")) is False


def test_an_exported_bundle_is_usable(tmp_path):
    assert rb.usable_bundle(_make_bundle(tmp_path / "helao_ui")) is True


def test_resolve_bundle_reads_a_zero_byte_index_html_as_absent(tmp_path):
    _make_bundle(rb.install_dir(str(tmp_path), None, "golden", "UI"), "")
    choice = rb.resolve_bundle(str(tmp_path), None, "golden", "UI", _stamp())
    assert choice.path == ""
    assert choice.source is None


# --- Staleness --------------------------------------------------------------


def _stamp(**overrides):
    """A complete, believable stamp. Every dict field is non-empty on purpose.

    An empty dict cannot be perturbed by changing a value, so a stamp built
    with empty fields would make the parameterized staleness test pass without
    testing anything.
    """
    stamp = {
        "schema": rb.STAMP_SCHEMA,
        "api_url": "http://127.0.0.1:5011",
        "config_prefix": "golden",
        "server_key": "UI",
        "git_revs": {".": "a" * 40, "helao/deploy/hte": "b" * 40},
        "dirty_digests": {".": "", "helao/deploy/hte": ""},
        "extra_files": {"rxconfig.py": "c" * 40, "xy-client.js": "d" * 40},
        "tool_versions": {"reflex": "0.9.7", "reflex-components-radix": "0.9.6"},
        "modules": {
            rb.APP_MODULE_REL: "e" * 40,
            **{f"helao/core/servers/reflex/m{i}.py": "f" * 40 for i in range(20)},
        },
        "js_runtime": "bun 1.3.14",
        "built_at": "2026-08-08T00:00:00-0700",
        "built_by_host": "somewhere",
    }
    stamp.update(overrides)
    return stamp


def _perturb(value):
    """Return a value that differs from ``value`` in the same shape."""
    if isinstance(value, dict):
        changed = dict(value)
        key = sorted(changed)[0]
        changed[key] = f"{changed[key]}-changed"
        return changed
    if isinstance(value, int) and not isinstance(value, bool):
        return value + 1
    return f"{value}-changed"


def test_an_unchanged_stamp_is_not_stale():
    """The control. Without it every parameterized case below could pass by
    reporting a mismatch for any two stamps at all."""
    assert rb.stamp_mismatch(_stamp(), _stamp()) == ""


@pytest.mark.parametrize("field", rb.COMPARED_FIELDS)
def test_every_compared_field_independently_makes_the_bundle_stale(field):
    current = _stamp()
    recorded = _stamp(**{field: _perturb(current[field])})
    reason = rb.stamp_mismatch(current, recorded)
    assert reason, f"a changed {field} did not make the bundle stale"
    assert field in reason, f"the reason does not name {field}: {reason}"


@pytest.mark.parametrize("field", ("js_runtime", "built_at", "built_by_host"))
def test_the_recorded_only_fields_do_not_make_the_bundle_stale(field):
    """These are diagnostics.

    ``js_runtime`` in particular must not be compared: the emitted bundle is
    produced by the pinned toolchain under ``.web``, not by the interpreter
    that ran it, and comparing it would make a correct bundle unserveable on
    the one machine that cannot rebuild it -- a station with no runtime at all.
    """
    current = _stamp()
    recorded = _stamp(**{field: _perturb(current[field])})
    assert rb.stamp_mismatch(current, recorded) == ""


def test_a_missing_stamp_is_stale():
    assert rb.stamp_mismatch(_stamp(), None) == "no bundle stamp recorded"


def test_the_reason_names_the_module_that_changed():
    """ "a panel changed" and "the port changed" want different reactions."""
    current = _stamp()
    recorded = _stamp()
    recorded["modules"]["helao/core/servers/reflex/m3.py"] = "9" * 40
    assert "helao/core/servers/reflex/m3.py" in rb.stamp_mismatch(current, recorded)


def test_every_differing_field_is_reported_not_only_the_first():
    current = _stamp()
    recorded = _stamp(api_url="http://127.0.0.1:9999")
    recorded["modules"][rb.APP_MODULE_REL] = "9" * 40
    reason = rb.stamp_mismatch(current, recorded)
    assert "api_url" in reason and "modules" in reason


def test_an_unreadable_stamp_reads_as_absent(tmp_path):
    """The safe direction: a corrupt stamp makes the bundle stale, not trusted."""
    path = tmp_path / "bundle.json"
    path.write_text("{not json")
    assert rb.read_stamp(str(path)) is None
    assert rb.read_stamp(str(tmp_path / "nope.json")) is None


def test_a_written_stamp_round_trips(tmp_path):
    path = str(tmp_path / "b" / "bundle.json")
    rb.write_stamp(path, _stamp())
    assert rb.read_stamp(path) == _stamp()


# --- The vacuity guard ------------------------------------------------------


def test_a_stamp_with_no_module_map_is_refused():
    with pytest.raises(rb.BundleStampError):
        rb.validate_stamp(_stamp(modules=None))


def test_a_stamp_captured_before_the_app_import_is_refused():
    """The failure this guard exists for.

    ``compute_stamp`` reads ``sys.modules``; called before the Reflex app is
    imported it returns a stub map that never changes, so every later
    comparison passes and the bundle is never rebuilt -- with every other
    signal reading healthy.
    """
    stub = {f"helao/helpers/h{i}.py": "0" * 40 for i in range(30)}
    with pytest.raises(rb.BundleStampError) as excinfo:
        rb.validate_stamp(_stamp(modules=stub))
    assert rb.APP_MODULE_REL in str(excinfo.value)


def test_a_stub_sized_module_map_is_refused():
    tiny = {rb.APP_MODULE_REL: "0" * 40, "helao/core/servers/reflex/x.py": "1" * 40}
    with pytest.raises(rb.BundleStampError) as excinfo:
        rb.validate_stamp(_stamp(modules=tiny))
    assert str(len(tiny)) in str(excinfo.value)


def test_write_stamp_refuses_rather_than_recording_an_unbelievable_stamp(tmp_path):
    path = str(tmp_path / "bundle.json")
    with pytest.raises(rb.BundleStampError):
        rb.write_stamp(path, _stamp(modules={}))
    assert not os.path.exists(path)


def test_a_real_capture_passes_the_guard():
    """The guard must not be so strict that the real thing trips it."""
    rb.validate_stamp(_stamp())


# --- The legacy fallback ----------------------------------------------------


def test_the_legacy_bundle_is_offered_only_when_no_config_bundle_exists(tmp_path):
    _make_bundle(rb.legacy_bundle_dir(str(tmp_path)))
    choice = rb.resolve_bundle(str(tmp_path), None, "golden", "UI", _stamp())
    assert choice.source == "legacy"
    assert choice.path == rb.legacy_bundle_dir(str(tmp_path))


def test_the_legacy_bundle_is_not_offered_in_place_of_a_stale_one(tmp_path):
    """A stale config bundle is a bundle we know is wrong.

    The legacy one is no more likely to be right, and serving it would hide the
    rebuild that is actually needed.
    """
    _make_bundle(rb.legacy_bundle_dir(str(tmp_path)))
    installed = rb.install_dir(str(tmp_path), None, "golden", "UI")
    _make_bundle(installed)
    rb.write_stamp(
        rb.stamp_path(str(tmp_path), None, "golden", "UI"),
        _stamp(api_url="http://127.0.0.1:9999"),
    )
    choice = rb.resolve_bundle(str(tmp_path), None, "golden", "UI", _stamp())
    assert choice.source is None
    assert choice.reason.startswith("stale:")
    assert "api_url" in choice.reason


def test_the_legacy_fallback_reports_the_backend_url_it_was_built_for(tmp_path):
    """A legacy bundle carries no stamp, so the JavaScript is the only record.

    Without it the warning can only say "this might be wrong"; with it the
    launcher can tell a usable fallback from one that will render and then
    refuse every WebSocket.
    """
    legacy = rb.legacy_bundle_dir(str(tmp_path))
    _make_bundle(legacy)
    with open(os.path.join(legacy, "app.js"), "w", encoding="utf8") as handle:
        handle.write('const x="http://station5.example:6011";//http://other:1')
    choice = rb.resolve_bundle(str(tmp_path), None, "golden", "UI", _stamp())
    assert choice.source == "legacy"
    assert choice.reason == "http://station5.example:6011"


def test_a_bundle_with_no_readable_url_reports_an_empty_one(tmp_path):
    _make_bundle(rb.legacy_bundle_dir(str(tmp_path)))
    assert rb.baked_api_url(rb.legacy_bundle_dir(str(tmp_path))) == ""


def test_a_current_config_bundle_wins_over_the_legacy_one(tmp_path):
    _make_bundle(rb.legacy_bundle_dir(str(tmp_path)))
    installed = _make_bundle(rb.install_dir(str(tmp_path), None, "golden", "UI"))
    rb.write_stamp(rb.stamp_path(str(tmp_path), None, "golden", "UI"), _stamp())
    choice = rb.resolve_bundle(str(tmp_path), None, "golden", "UI", _stamp())
    assert choice == rb.BundleChoice(installed, "config", "")


# --- The build lock ---------------------------------------------------------


class _FakeLogger:
    def __init__(self):
        self.errors = []

    def error(self, message):
        self.errors.append(str(message))

    def info(self, message):
        pass

    def warning(self, message):
        pass


def _app_tree(tmp_path):
    """A repo root with just enough of ``_app`` for the lock to live in."""
    os.makedirs(os.path.join(str(tmp_path), rb.APP_DIR), exist_ok=True)
    return str(tmp_path)


def test_a_second_build_does_not_deadlock_and_names_the_holder(tmp_path, monkeypatch):
    """Contention must end in a message, not a launch that hangs forever."""
    monkeypatch.setattr(rb, "_FileLock", None)  # exercise the spinlock fallback
    repo = _app_tree(tmp_path)
    logger = _FakeLogger()
    held = threading.Event()
    release = threading.Event()

    def hold():
        with rb.build_lock(repo, timeout=5.0):
            held.set()
            release.wait(10)

    holder = threading.Thread(target=hold, daemon=True)
    holder.start()
    assert held.wait(5), "the first lock was never acquired"
    try:
        with pytest.raises(rb.BuildLockBusy) as excinfo:
            with rb.build_lock(repo, timeout=0.5, logger=logger):
                pass
    finally:
        release.set()
        holder.join(10)
    assert str(os.getpid()) in str(excinfo.value), str(excinfo.value)
    assert logger.errors and "did not finish" in logger.errors[0]


def test_the_lock_is_released_so_the_next_build_can_take_it(tmp_path, monkeypatch):
    monkeypatch.setattr(rb, "_FileLock", None)
    repo = _app_tree(tmp_path)
    with rb.build_lock(repo, timeout=1.0):
        pass
    with rb.build_lock(repo, timeout=1.0):
        pass  # would raise BuildLockBusy if the first had leaked


def test_the_lock_guards_the_build_tree_not_the_bundle(tmp_path):
    """Two configs build to different bundles through one shared ``.web``."""
    repo = _app_tree(tmp_path)
    assert rb.build_lock(repo).path.startswith(os.path.join(repo, rb.APP_DIR))


# --- Building ---------------------------------------------------------------


def _fake_export(zip_body=b"", index="<html>ok</html>"):
    """Return a ``_run`` stand-in that writes a plausible export."""

    def run(command, cwd, env, what, logger=None):
        if "export" not in " ".join(str(c) for c in command):
            return
        with zipfile.ZipFile(os.path.join(cwd, "frontend.zip"), "w") as archive:
            archive.writestr("index.html", index)
            archive.writestr("app.js", zip_body or b"//built")

    return run


@pytest.fixture
def buildable(tmp_path, monkeypatch):
    """A repo root whose build runs entirely in-process.

    Neither reflex nor a JavaScript runtime is involved; what is under test is
    the install: verify, replace atomically, then stamp.
    """
    repo = _app_tree(tmp_path / "repo")
    monkeypatch.setattr(rb.shutil, "which", lambda name: "/usr/bin/bun")
    monkeypatch.setattr(rb, "_copy_client_asset", lambda dest: dest)
    monkeypatch.setattr(
        rb,
        "effective_build_dir",
        lambda root: os.path.join(str(tmp_path), "build", "_app"),
    )
    monkeypatch.setattr(rb, "staging_is_usable", lambda path: True)
    monkeypatch.setattr(rb, "_sync_app_sources", lambda src, dst: None)
    monkeypatch.setattr(rb, "compute_stamp", lambda *a, **k: _stamp())
    os.makedirs(os.path.join(str(tmp_path), "build", "_app", ".web"), exist_ok=True)
    return repo


def test_a_build_installs_the_bundle_and_its_stamp(buildable, tmp_path, monkeypatch):
    monkeypatch.setattr(rb, "_run", _fake_export())
    root = str(tmp_path / "data")
    target = rb.build_bundle(buildable, "golden.yml", "UI", "http://h:5011", root=root)
    assert rb.usable_bundle(target)
    assert rb.read_stamp(rb.stamp_path(buildable, root, "golden", "UI")) == _stamp()


def test_a_failed_build_leaves_the_installed_bundle_untouched(
    buildable, tmp_path, monkeypatch
):
    """A wrongly-built control UI on an instrument is worse than one that is
    simply absent, so a failure must never disturb what is already serving."""
    root = str(tmp_path / "data")
    installed = _make_bundle(
        rb.install_dir(buildable, root, "golden", "UI"), "<html>old</html>"
    )
    rb.write_stamp(rb.stamp_path(buildable, root, "golden", "UI"), _stamp())

    def boom(command, cwd, env, what, logger=None):
        raise SystemExit("reflex export failed (exit 1):\nboom")

    monkeypatch.setattr(rb, "_run", boom)
    with pytest.raises(SystemExit):
        rb.build_bundle(buildable, "golden.yml", "UI", "http://h:5011", root=root)
    with open(os.path.join(installed, "index.html"), encoding="utf8") as handle:
        assert handle.read() == "<html>old</html>"
    assert rb.read_stamp(rb.stamp_path(buildable, root, "golden", "UI")) == _stamp()


def test_an_export_that_produces_no_zip_leaves_the_old_bundle(
    buildable, tmp_path, monkeypatch
):
    """`reflex export` can fail while still exiting zero."""
    root = str(tmp_path / "data")
    installed = _make_bundle(
        rb.install_dir(buildable, root, "golden", "UI"), "<html>old</html>"
    )
    monkeypatch.setattr(rb, "_run", lambda *a, **k: None)
    with pytest.raises(SystemExit) as excinfo:
        rb.build_bundle(buildable, "golden.yml", "UI", "http://h:5011", root=root)
    assert "left in place" in str(excinfo.value)
    with open(os.path.join(installed, "index.html"), encoding="utf8") as handle:
        assert handle.read() == "<html>old</html>"


def test_an_unbelievable_stamp_aborts_before_the_old_bundle_is_replaced(
    buildable, tmp_path, monkeypatch
):
    root = str(tmp_path / "data")
    installed = _make_bundle(
        rb.install_dir(buildable, root, "golden", "UI"), "<html>old</html>"
    )
    monkeypatch.setattr(rb, "_run", _fake_export())
    with pytest.raises(rb.BundleStampError):
        rb.build_bundle(
            buildable,
            "golden.yml",
            "UI",
            "http://h:5011",
            root=root,
            stamp=_stamp(modules={}),
        )
    with open(os.path.join(installed, "index.html"), encoding="utf8") as handle:
        assert handle.read() == "<html>old</html>"


def test_a_build_refuses_without_a_javascript_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(rb.shutil, "which", lambda name: None)
    with pytest.raises(SystemExit) as excinfo:
        rb.build_bundle(str(tmp_path), "golden.yml", "UI", "http://h:5011")
    assert "JavaScript runtime" in str(excinfo.value)


# --- Staging ----------------------------------------------------------------


def test_a_noexec_checkout_builds_in_a_persistent_directory(tmp_path, monkeypatch):
    """The staged tree must survive between builds.

    Staging into a fresh temporary directory discarded ``.web`` with it, so
    every build on a ``noexec`` checkout re-fetched ~270 MB and the incremental
    branch of the auto-build policy could never be reached there.
    """
    monkeypatch.setattr(rb, "staging_is_usable", lambda path: False)
    first = rb.effective_build_dir(str(tmp_path))
    second = rb.effective_build_dir(str(tmp_path))
    assert first == second
    assert not first.startswith(str(tmp_path))


def test_two_checkouts_do_not_share_one_staged_build_tree(monkeypatch):
    monkeypatch.setattr(rb, "staging_is_usable", lambda path: False)
    assert rb.effective_build_dir("/a/repo") != rb.effective_build_dir("/b/repo")


def test_node_modules_is_looked_for_where_the_build_will_run(tmp_path, monkeypatch):
    """On a ``noexec`` checkout the repo's own ``.web`` is not the one reused."""
    repo = _app_tree(tmp_path)
    os.makedirs(os.path.join(repo, rb.APP_DIR, ".web", "node_modules"))
    monkeypatch.setattr(rb, "staging_is_usable", lambda path: False)
    assert rb.node_modules_present(repo) is False
    monkeypatch.setattr(rb, "staging_is_usable", lambda path: True)
    assert rb.node_modules_present(repo) is True


def test_syncing_a_staged_tree_keeps_web_and_drops_removed_sources(tmp_path):
    """A panel deleted in the repository must disappear from the build too."""
    source = tmp_path / "src"
    (source / "helao_ui").mkdir(parents=True)
    (source / "rxconfig.py").write_text("config = 1")
    staged = tmp_path / "staged"
    (staged / ".web" / "node_modules").mkdir(parents=True)
    (staged / "helao_ui").mkdir()
    (staged / "helao_ui" / "gone.py").write_text("deleted upstream")

    rb._sync_app_sources(str(source), str(staged))

    assert (staged / ".web" / "node_modules").is_dir()
    assert (staged / "rxconfig.py").is_file()
    assert not (staged / "helao_ui" / "gone.py").exists()


# --- The single revision reader ---------------------------------------------


def test_the_stamp_borrows_launch_pys_revision_reader():
    """One definition of "which repos" and "what revision".

    The hot-reload watcher and this stamp must never disagree about either, so
    the stamp calls launch.py's readers rather than carrying its own.
    """
    discover, head = rb._git_readers()
    assert discover is launch.discover_git_repos
    assert head is launch.git_head


def test_repo_revisions_covers_the_parent_repo_and_its_deployments(tmp_path):
    repo = str(tmp_path)
    os.makedirs(os.path.join(repo, ".git"))
    os.makedirs(os.path.join(repo, "helao", "deploy", "somewhere", ".git"))
    revs, dirty = rb.repo_revisions(repo)
    assert set(revs) == {".", "helao/deploy/somewhere"}
    assert set(dirty) == set(revs)


def test_a_worktree_checkout_is_still_recognised_as_a_repo(tmp_path):
    """In a linked worktree ``.git`` is a *file* naming the real git directory.

    An ``isdir`` test skipped the parent repo entirely, so the stamp -- and the
    hot-reload watcher that shares this reader -- silently watched only the
    deployments.
    """
    (tmp_path / ".git").write_text("gitdir: /elsewhere/.git/worktrees/wt\n")
    assert launch.discover_git_repos(str(tmp_path)) == [str(tmp_path)]


def test_a_dirty_tree_gets_a_different_digest_than_a_clean_one(tmp_path):
    """An uncommitted panel edit is as much a bundle input as a committed one."""
    import subprocess

    repo = str(tmp_path)
    subprocess.run(["git", "init", "-q", repo], check=True, capture_output=True)
    (tmp_path / "a.py").write_text("x = 1")
    subprocess.run(["git", "-C", repo, "add", "a.py"], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            repo,
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-qm",
            "a",
        ],
        check=True,
        capture_output=True,
    )
    clean = rb._git_dirty_digest(repo)
    (tmp_path / "a.py").write_text("x = 2")
    assert clean == ""
    assert rb._git_dirty_digest(repo) not in ("", "unknown")


# --- launch.py's early-exit supervision -------------------------------------


class _FakeProc:
    def __init__(self, code=None):
        self.code = code

    def poll(self):
        return self.code


def test_a_child_that_is_still_running_is_not_reported():
    assert launch.early_exits({"UI": _FakeProc(None)}) == []


def test_a_child_that_exited_is_reported_with_its_code():
    assert launch.early_exits({"UI": _FakeProc(1), "MOTOR": _FakeProc(None)}) == [
        ("UI", 1)
    ]


def test_a_refusal_after_launch_is_surfaced_once():
    """The spawn loop registers a pid and never looks at it again.

    Before this, a server that declined to start left only a dead pid and an
    ERROR buried in the multiplexed console, while the launch read clean.
    """
    procs = {"UI": _FakeProc(None)}
    ticks = {"n": 0}
    seen = []

    def monotonic():
        return ticks["n"]

    def sleep(_seconds):
        ticks["n"] += 1
        if ticks["n"] == 3:
            procs["UI"] = _FakeProc(1)

    reported = launch.supervise_early_exits(
        procs,
        lambda key, code: seen.append((key, code)),
        window=10,
        interval=1,
        sleep=sleep,
        monotonic=monotonic,
    )
    assert reported == [("UI", 1)]
    assert seen == [("UI", 1)], "the refusal was reported more or less than once"


def test_supervision_stops_once_a_stop_was_asked_for():
    """After CTRL-r or a teardown a child exiting is the point, not a failure."""
    seen = []
    ticks = {"n": 0}

    def sleep(_seconds):
        ticks["n"] += 1

    reported = launch.supervise_early_exits(
        {"UI": _FakeProc(1)},
        lambda key, code: seen.append(key),
        window=10,
        interval=1,
        stop=lambda: True,
        sleep=sleep,
        monotonic=lambda: ticks["n"],
    )
    assert reported == [] and seen == []


def test_a_proc_that_cannot_be_polled_is_skipped():
    class _Broken:
        def poll(self):
            raise OSError("gone")

    assert launch.early_exits({"UI": _Broken()}) == []


# --- Assembled JSON ---------------------------------------------------------


def test_the_stamp_is_json_serializable():
    """It is written to disk; a value that cannot be encoded loses the stamp
    entirely, which degrades staleness to "never stale"."""
    json.dumps(_stamp())
