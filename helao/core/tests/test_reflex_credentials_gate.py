"""Credential-gated Reflex pages hide and disable without ``HELAO_CREDENTIALS``.

The composition, spectra and retire pages read the metadata API or S3. On a
station with no credentials they could only fail, so the navigation hides them
and each page renders a note in place of its body.
"""

import pytest

from helao.ui.reflex import app

pytestmark = pytest.mark.usefixtures("reflex_registration")


def test_unset_credentials_are_unavailable(monkeypatch):
    monkeypatch.delenv("HELAO_CREDENTIALS", raising=False)
    assert app.credentials_available() is False


def test_credentials_naming_a_missing_file_are_unavailable(monkeypatch, tmp_path):
    monkeypatch.setenv("HELAO_CREDENTIALS", str(tmp_path / "absent.env"))
    assert app.credentials_available() is False


def test_credentials_naming_a_file_are_available(monkeypatch, tmp_path):
    creds = tmp_path / "helao.env"
    creds.write_text("", encoding="utf-8")
    monkeypatch.setenv("HELAO_CREDENTIALS", str(creds))
    assert app.credentials_available() is True


def test_computed_var_reads_the_environment_at_call_time(monkeypatch, tmp_path):
    fget = app.CredentialsState.computed_vars["has_credentials"]._fget
    monkeypatch.delenv("HELAO_CREDENTIALS", raising=False)
    assert fget(None) is False  # type: ignore[arg-type]
    creds = tmp_path / "helao.env"
    creds.write_text("", encoding="utf-8")
    monkeypatch.setenv("HELAO_CREDENTIALS", str(creds))
    assert fget(None) is True  # type: ignore[arg-type]


@pytest.mark.parametrize("route", app.CREDENTIAL_ROUTES)
def test_gated_page_swaps_its_body_for_the_note(route):
    rendered = str(app._page("T", app.rx.text("BODY"), route))
    # the nav carries one gate of its own; the body must add another
    assert rendered.count("has_credentials") > str(app._nav()).count("has_credentials")
    assert "BODY" in rendered
    assert "HELAO_CREDENTIALS" in rendered


@pytest.mark.parametrize("route", ["/live", "/operator", "/browser", "/control"])
def test_ungated_page_is_unchanged(route):
    body = str(app._page("T", app.rx.text("BODY"), route))
    nav = str(app._nav())
    assert body.count("has_credentials") == nav.count("has_credentials")


def test_nav_hides_exactly_the_gated_links():
    nav = str(app._nav())
    gate = nav.index("has_credentials")
    for route in app.CREDENTIAL_ROUTES:
        assert nav.index(f'"{route}"') > gate, route
    for route in ("/live", "/action", "/operator", "/browser", "/control"):
        assert nav.index(f'"{route}"') < gate, route
