import pytest
import uvicorn
from app import main
from app.cli import commands
from app.cli.commands import app as cli
from app.config import Settings
from app.services.access import (
    FAILURE_WINDOW_SECONDS,
    MAX_FAILURES,
    SESSION_COOKIE,
    SESSION_SECONDS,
    LoginAttempts,
    password_matches,
    session_token,
    valid_session,
)
from fastapi.testclient import TestClient
from pydantic import ValidationError
from typer.testing import CliRunner

PASSWORD = "correct horse battery"
NOW = 1_800_000_000.0


def test_a_session_lasts_until_it_expires() -> None:
    token = session_token(PASSWORD, NOW)

    assert valid_session(token, PASSWORD, NOW)
    assert valid_session(token, PASSWORD, NOW + SESSION_SECONDS - 1)
    assert not valid_session(token, PASSWORD, NOW + SESSION_SECONDS + 1)


def test_a_session_cannot_be_forged_or_outlive_its_password() -> None:
    token = session_token(PASSWORD, NOW)
    expires, signature = token.split(".")

    # A later expiry needs a new signature, which needs the password.
    assert not valid_session(f"{int(expires) + 60}.{signature}", PASSWORD, NOW)
    assert not valid_session(token, "a different password", NOW)
    for junk in (None, "", "abc", ".", f"{expires}.", f".{signature}", "١٢٣.abc"):
        assert not valid_session(junk, PASSWORD, NOW)


def test_passwords_are_compared_whole() -> None:
    assert password_matches(PASSWORD, PASSWORD)
    assert not password_matches(PASSWORD[:-1], PASSWORD)
    assert not password_matches("", PASSWORD)


def test_sign_in_pauses_after_a_run_of_wrong_passwords() -> None:
    attempts = LoginAttempts()
    for _ in range(MAX_FAILURES):
        assert attempts.allowed(NOW)
        attempts.failed(NOW)

    assert not attempts.allowed(NOW + 60)
    assert attempts.allowed(NOW + FAILURE_WINDOW_SECONDS + 1)


def test_a_blank_password_means_none_and_a_short_one_is_refused() -> None:
    assert Settings(_env_file=None, dashboard_password="  ").dashboard_password is None
    with pytest.raises(ValidationError):
        Settings(_env_file=None, dashboard_password="hunter2")


@pytest.fixture()
def locked(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    settings = Settings(_env_file=None, dashboard_password=PASSWORD)
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    monkeypatch.setattr(main, "_login_attempts", LoginAttempts())
    return TestClient(main.app)


def test_without_a_password_nothing_asks_for_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "get_settings", lambda: Settings(_env_file=None))
    client = TestClient(main.app)

    assert client.get("/openapi.json").status_code == 200
    assert client.post("/login", json={"password": "anything"}).json() == {"signed_in": True}


def test_only_the_page_and_health_check_are_open_before_sign_in(locked: TestClient) -> None:
    assert locked.get("/dashboard").status_code == 200
    assert locked.get("/health").status_code == 200
    for path in ("/openapi.json", "/docs", "/api/dashboard", "/chat/sessions", "/resources"):
        response = locked.get(path)
        assert (response.status_code, response.json()) == (
            401,
            {"detail": "Sign in to continue."},
        ), path
    assert locked.post("/chat", json={"question": "What is stress?"}).status_code == 401
    assert locked.get("/course-resources/any/pages/1").status_code == 401


def test_the_password_signs_a_device_in_and_out(locked: TestClient) -> None:
    wrong = locked.post("/login", json={"password": "not the password"})
    assert (wrong.status_code, wrong.json()) == (401, {"detail": "Wrong password."})
    assert locked.get("/openapi.json").status_code == 401

    signed_in = locked.post("/login", json={"password": PASSWORD})
    cookie = signed_in.headers["set-cookie"]
    assert signed_in.status_code == 200 and cookie.startswith(f"{SESSION_COOKIE}=")
    # Kept from page scripts and from other sites; plain http is the private network.
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Secure" not in cookie
    assert locked.get("/openapi.json").status_code == 200

    assert locked.post("/logout").json() == {"signed_in": False}
    assert locked.get("/openapi.json").status_code == 401


def test_the_cookie_is_https_only_behind_a_public_address(locked: TestClient) -> None:
    signed_in = locked.post(
        "/login", json={"password": PASSWORD}, headers={"X-Forwarded-Proto": "https"}
    )

    assert "Secure" in signed_in.headers["set-cookie"]


def test_guessing_is_cut_off_even_for_the_right_password(locked: TestClient) -> None:
    for _ in range(MAX_FAILURES):
        assert locked.post("/login", json={"password": "a wrong guess"}).status_code == 401

    assert locked.post("/login", json={"password": PASSWORD}).status_code == 429
    assert locked.get("/openapi.json").status_code == 401


def test_the_dashboard_is_not_served_beyond_this_computer_without_a_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(uvicorn, "run", lambda target, **kwargs: calls.append(kwargs["host"]))
    monkeypatch.setattr(commands, "get_settings", lambda: Settings(_env_file=None))

    refused = CliRunner().invoke(cli, ["dashboard", "--host", "0.0.0.0", "--no-open"])
    assert refused.exit_code == 1 and "DASHBOARD_PASSWORD" in refused.output

    protected = Settings(_env_file=None, dashboard_password=PASSWORD)
    monkeypatch.setattr(commands, "get_settings", lambda: protected)
    served = CliRunner().invoke(cli, ["dashboard", "--host", "0.0.0.0", "--no-open"])
    assert served.exit_code == 0 and calls == ["0.0.0.0"]
