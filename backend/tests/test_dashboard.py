from app.main import app
from fastapi.testclient import TestClient


def test_dashboard_page_is_served() -> None:
    response = TestClient(app).get("/dashboard")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'id="chat-ask"' in response.text
    assert "function renderAnswer" in response.text
    assert "function drawFigures" in response.text
    assert "function citeLink" in response.text
    assert "function loadChats" in response.text and 'id="chat-thread"' in response.text
