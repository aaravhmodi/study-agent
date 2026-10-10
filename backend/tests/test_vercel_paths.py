import re
from pathlib import Path

from app.main import app

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "deploy-frontend.sh"


def test_vercel_forwards_every_address_the_server_answers_on() -> None:
    """A route the page calls but Vercel does not forward is a 404 on the public site."""

    listed = re.search(r'^paths="([^"]+)"$', SCRIPT.read_text(encoding="utf-8"), re.MULTILINE)
    assert listed is not None
    forwarded = set(listed.group(1).split("|"))

    answered = {route.path.split("/")[1] for route in app.routes}  # type: ignore[attr-defined]
    # Vercel serves the page itself; /redoc is the API docs' second skin, not linked.
    answered -= {"dashboard", "redoc"}

    assert answered - forwarded == set()
