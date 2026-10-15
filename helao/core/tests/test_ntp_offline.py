"""get_ntp_time must fall back to a zero offset when there is no DNS/network."""

import socket

import ntplib

from helao.helpers.time_utils import get_ntp_time, read_saved_offset


def test_get_ntp_time_survives_dns_failure(tmp_path, monkeypatch):
    def no_dns(self, *args, **kwargs):
        raise socket.gaierror(-2, "Name or service not known")

    monkeypatch.setattr(ntplib.NTPClient, "request", no_dns)
    out = tmp_path / "ntpLastSync.txt"

    get_ntp_time("time.invalid", str(out))

    assert read_saved_offset(str(out))[1] == 0.0
