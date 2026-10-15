"""``GZipRotator`` compresses in-process when no ``gzip`` binary is on PATH."""

import gzip
import subprocess

from helao.helpers.helao_logging import GZipRotator


def test_rotator_falls_back_to_python_gzip(tmp_path, monkeypatch):
    def no_gzip(*_a, **_k):
        raise FileNotFoundError("gzip")

    monkeypatch.setattr(subprocess, "Popen", no_gzip)
    src, dst = tmp_path / "x.log", tmp_path / "x.log.2026-01-01"
    src.write_bytes(b"hello log\n")
    GZipRotator()(str(src), str(dst))
    assert not src.exists() and not dst.exists()
    assert gzip.open(str(dst) + ".gz").read() == b"hello log\n"
