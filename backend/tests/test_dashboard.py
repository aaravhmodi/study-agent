from app.main import app
from fastapi.testclient import TestClient


def test_dashboard_page_is_served() -> None:
    response = TestClient(app).get("/dashboard")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    # The icon is inline, so the page needs no second file wherever it is served.
    assert '<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,' in response.text
    assert 'id="chat-ask"' in response.text
    assert "function renderAnswer" in response.text
    assert "function drawFigures" in response.text
    assert "function citeLink" in response.text
    assert "function loadChats" in response.text and 'id="chat-thread"' in response.text
