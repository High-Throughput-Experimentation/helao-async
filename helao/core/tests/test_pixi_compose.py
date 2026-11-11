from pathlib import Path

import pytest

import pixi_compose as pc

BASE = {
    "workspace": {
        "name": "helao",
        "channels": ["conda-forge"],
        "platforms": ["linux-64", "win-64"],
    },
    "dependencies": {"python": "3.14.*", "numpy": "*", "paramiko": "3.*"},
    "target": {
        "win-64": {
            "dependencies": {"comtypes": "*"},
            "activation": {"env": {"PYTHONPATH": "%PIXI_PROJECT_ROOT%"}},
        },
        "linux-64": {"activation": {"env": {"PYTHONPATH": "$PIXI_PROJECT_ROOT"}}},
    },
    "pypi-dependencies": {"uuid7": "*"},
}


def _folder(root: Path, name: str, **files: str) -> Path:
    f = root / name
    f.mkdir(parents=True)
    for fname, text in files.items():
        (f / fname.replace("__", ".")).write_bytes(text.encode("utf-8"))
    return f


@pytest.mark.parametrize(
    "line, want",
    [
        ("pyserial", ("pyserial", "*")),
        ("bokeh=3", ("bokeh", "3.*")),
        ("python=3.14", ("python", "3.14.*")),
        ("nodejs>=22.12", ("nodejs", ">=22.12")),
        ("setuptools<82", ("setuptools", "<82")),
        ("conda-forge::jupyterlab", ("jupyterlab", "*")),
        ("pytorch=*=cuda129*", ("pytorch", {"version": "*", "build": "cuda129*"})),
        ("x=1.2=py_0", ("x", {"version": "1.2.*", "build": "py_0"})),
    ],
)
def test_conda_spec(line, want):
    assert pc.conda_spec(line) == want


@pytest.mark.parametrize(
    "line, want",
    [
        ("nidaqmx", ("nidaqmx", "*", None)),
        ("xy[reflex]", ("xy", {"version": "*", "extras": ["reflex"]}, None)),
        ("x==1.0", ("x", "==1.0", None)),
        (
            'comtypes; sys_platform == "win32"',
            ("comtypes", "*", 'sys_platform == "win32"'),
        ),
        (
            "https://github.com/meerstetter/pyMeCom/archive/master.zip",
            (
                "mecom",
                {"url": "https://github.com/meerstetter/pyMeCom/archive/master.zip"},
                None,
            ),
        ),
        (
            "GSAS-II[useful] @ git+https://github.com/AdvancedPhotonSource/GSAS-II.git",
            (
                "GSAS-II",
                {
                    "git": "https://github.com/AdvancedPhotonSource/GSAS-II.git",
                    "extras": ["useful"],
                },
                None,
            ),
        ),
    ],
)
def test_pypi_spec(line, want):
    assert pc.pypi_spec(line) == want


def test_pypi_spec_ignores_comments_blank_and_crlf(tmp_path):
    f = _folder(
        tmp_path,
        "a",
        requirements__txt="# hdr\r\n\r\nfabio  # tiff io\r\nzaber-motion\r\n",
    )
    m = pc.compose(BASE, {f}, "linux-64", tmp_path)
    assert m["pypi-dependencies"] == {"uuid7": "*", "fabio": "*", "zaber-motion": "*"}


def test_unmapped_url_requirement_is_an_error():
    with pytest.raises(pc.ComposeError, match="URL_DIST_NAMES"):
        pc.pypi_spec("https://example.com/foo/bar/archive/master.zip")


def test_requirements_option_line_is_an_error():
    with pytest.raises(pc.ComposeError, match="not supported"):
        pc.pypi_spec("-r other.txt")


def test_compose_folds_host_target_and_keeps_host_platform_only(tmp_path):
    m = pc.compose(BASE, set(), "win-64", tmp_path)
    assert m["workspace"]["platforms"] == ["win-64"]
    assert "target" not in m
    assert m["dependencies"]["comtypes"] == "*"
    m = pc.compose(BASE, set(), "linux-64", tmp_path)
    assert "comtypes" not in m["dependencies"]


def test_compose_sets_absolute_activation(tmp_path):
    states = [tmp_path / "r1/STATES/s.json", tmp_path / "r2/STATES/s.json"]
    m = pc.compose(BASE, set(), "linux-64", tmp_path, states)
    env = m["activation"]["env"]
    assert env["PYTHONPATH"] == str(tmp_path)
    assert env["HELAOLAUNCH"] == str(tmp_path / "helao.sh")
    assert env["HELAO_STATION_PREFIXES"] == ":".join(sorted(map(str, states)))
    w = pc.compose(BASE, set(), "win-64", tmp_path, states)["activation"]["env"]
    assert w["HELAOLAUNCH"] == str(tmp_path / "helao.bat")
    assert w["HELAO_STATION_PREFIXES"] == ";".join(sorted(map(str, states)))


def test_compose_reads_root_env_files_for_the_host_platform_only(tmp_path):
    f = _folder(
        tmp_path,
        "srv",
        environment__yml="dependencies: [minimalmodbus, {pip: [pyft232]}]\n",
        **{
            "environment_linux-64__yml": "dependencies: [gfortran]\n",
            "environment_win-64__yml": "dependencies: [m2w64-gcc]\n",
        },
    )
    sub = f / "sidecar"
    sub.mkdir()
    (sub / "environment.yml").write_text("dependencies: [python=3.9]\n", "utf-8")
    (f / "environment-sim.yml").write_text("dependencies: [python=3.9]\n", "utf-8")
    m = pc.compose(BASE, {f}, "linux-64", tmp_path)
    assert {"minimalmodbus", "gfortran"} <= set(m["dependencies"])
    assert "m2w64-gcc" not in m["dependencies"]
    assert m["dependencies"]["python"] == "3.14.*"  # sidecar/sim ymls never read
    assert m["pypi-dependencies"]["pyft232"] == "*"


def test_win32_marker_selects_by_platform(tmp_path):
    f = _folder(
        tmp_path,
        "g",
        requirements__txt="comtypes; sys_platform == \"win32\"\nposixonly; sys_platform != 'win32'\n",
    )
    lin = pc.compose(BASE, {f}, "linux-64", tmp_path)["pypi-dependencies"]
    win = pc.compose(BASE, {f}, "win-64", tmp_path)["pypi-dependencies"]
    assert "comtypes" not in lin and "posixonly" in lin
    assert "comtypes" in win and "posixonly" not in win


def test_unsupported_marker_is_an_error(tmp_path):
    f = _folder(tmp_path, "g", requirements__txt='x; python_version < "3.10"\n')
    with pytest.raises(pc.ComposeError, match="marker"):
        pc.compose(BASE, {f}, "linux-64", tmp_path)


def test_two_folders_disagreeing_on_a_spec_is_an_error(tmp_path):
    a = _folder(tmp_path, "a", environment__yml="dependencies: [pyvisa=1.13]\n")
    b = _folder(tmp_path, "b", environment__yml="dependencies: [pyvisa=1.14]\n")
    with pytest.raises(pc.ComposeError, match="pyvisa"):
        pc.compose(BASE, {a, b}, "linux-64", tmp_path)


def test_identical_specs_from_two_folders_dedupe(tmp_path):
    a = _folder(tmp_path, "a", environment__yml="dependencies: [pyserial]\n")
    b = _folder(tmp_path, "b", environment__yml="dependencies: [pyserial]\n")
    assert (
        pc.compose(BASE, {a, b}, "linux-64", tmp_path)["dependencies"]["pyserial"]
        == "*"
    )


def test_folder_overriding_a_base_spec_warns(tmp_path):
    f = _folder(tmp_path, "a", environment__yml="dependencies: [numpy=2.2]\n")
    said = []
    m = pc.compose(BASE, {f}, "linux-64", tmp_path, warn=said.append)
    assert m["dependencies"]["numpy"] == "2.2.*"
    assert len(said) == 1 and "numpy" in said[0]
    same = _folder(tmp_path, "b", environment__yml="dependencies: [paramiko=3]\n")
    said.clear()
    pc.compose(BASE, {same}, "linux-64", tmp_path, warn=said.append)
    assert said == []  # same spec as base: no warning


def test_cuda_pytorch_overrides_pytorch_cpu(tmp_path):
    cpu = _folder(
        tmp_path, "sim", environment__yml="dependencies: [pytorch-cpu, gpytorch]\n"
    )
    gpu = _folder(
        tmp_path,
        "gpu",
        **{"environment_linux-64__yml": "dependencies: [pytorch=*=cuda129*]\n"},
    )
    both = pc.compose(BASE, {cpu, gpu}, "linux-64", tmp_path)["dependencies"]
    assert "pytorch-cpu" not in both and "gpytorch" in both
    only_cpu = pc.compose(BASE, {cpu}, "linux-64", tmp_path)["dependencies"]
    assert "pytorch-cpu" in only_cpu


def test_cuda_platform_entry_is_named_and_keyed(tmp_path):
    gpu = _folder(
        tmp_path,
        "gpu",
        **{"environment_linux-64__yml": "dependencies: [pytorch=*=cuda129*]\n"},
    )
    m = pc.compose(BASE, {gpu}, "linux-64", tmp_path)
    assert m["workspace"]["platforms"] == [
        {"name": "linux-64-cuda", "platform": "linux-64", "cuda": "12.9"}
    ]
    assert pc.platform_key(m) == "linux-64-cuda"
    assert pc.platform_key(pc.compose(BASE, set(), "linux-64", tmp_path)) == "linux-64"


def test_two_cuda_versions_is_an_error(tmp_path):
    a = _folder(tmp_path, "a", environment__yml="dependencies: [pytorch=*=cuda129*]\n")
    b = _folder(
        tmp_path, "b", environment__yml="dependencies: [torchvision=*=cuda118*]\n"
    )
    with pytest.raises(pc.ComposeError, match="CUDA"):
        pc.compose(BASE, {a, b}, "linux-64", tmp_path)


def test_pip_env_becomes_activation_with_shell_syntax(tmp_path):
    f = _folder(tmp_path, "a", requirements__txt="x\n")
    over = {f: {"PKG_CONFIG_LIBDIR": "{prefix}/lib/pkgconfig", "FC_LD": ""}}
    lin = pc.compose(BASE, {f}, "linux-64", tmp_path, pip_env_for=over.get)
    assert (
        lin["activation"]["env"]["PKG_CONFIG_LIBDIR"] == "$CONDA_PREFIX/lib/pkgconfig"
    )
    assert lin["activation"]["env"]["FC_LD"] == ""
    over = {f: {"PATH": "{prefix}\\Library\\bin;{PATH}"}}
    win = pc.compose(BASE, {f}, "win-64", tmp_path, pip_env_for=over.get)
    assert win["activation"]["env"]["PATH"] == "%CONDA_PREFIX%\\Library\\bin;%PATH%"


def test_two_folders_setting_one_variable_differently_is_an_error(tmp_path):
    a = _folder(tmp_path, "a", requirements__txt="x\n")
    b = _folder(tmp_path, "b", requirements__txt="y\n")
    over = {a: {"CC": "gcc"}, b: {"CC": "clang"}}
    with pytest.raises(pc.ComposeError, match="CC"):
        pc.compose(BASE, {a, b}, "linux-64", tmp_path, pip_env_for=over.get)


def test_compose_does_not_mutate_base(tmp_path):
    import copy

    before = copy.deepcopy(BASE)
    f = _folder(tmp_path, "a", environment__yml="dependencies: [pyserial]\n")
    pc.compose(BASE, {f}, "win-64", tmp_path)
    assert BASE == before
