from typing import Any

import pytest
import uvicorn
from app.cli.commands import app
from app.main import app as web_app
from typer.testing import CliRunner


def test_dashboard_command_serves_the_web_app_locally(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[Any, dict[str, Any]]] = []
    monkeypatch.setattr(uvicorn, "run", lambda target, **kwargs: calls.append((target, kwargs)))

    result = CliRunner().invoke(app, ["dashboard", "--port", "8123", "--no-open"])

    assert result.exit_code == 0, result.output
    assert "http://127.0.0.1:8123/dashboard" in result.output
    assert calls == [(web_app, {"host": "127.0.0.1", "port": 8123, "log_level": "warning"})]
