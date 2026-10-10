"""Sign-in for a dashboard served beyond this computer: one password, one cookie.

The cookie is a signed expiry time, so the server keeps no list of sessions, and
changing the password signs every device out.
"""

import hashlib
import hmac

SESSION_COOKIE = "study_session"
SESSION_SECONDS = 30 * 24 * 60 * 60

# Wrong passwords allowed from everyone together before sign-in pauses.
MAX_FAILURES = 8
FAILURE_WINDOW_SECONDS = 15 * 60


def password_matches(given: str, password: str) -> bool:
    return hmac.compare_digest(given.encode(), password.encode())


def session_token(password: str, now: float) -> str:
    """A cookie value that proves the password was given, good for SESSION_SECONDS."""

    expires = int(now) + SESSION_SECONDS
    return f"{expires}.{_signature(password, expires)}"


def valid_session(token: str | None, password: str, now: float) -> bool:
    expires, _, signature = (token or "").partition(".")
    if not expires.isascii() or not expires.isdigit() or int(expires) < now:
        return False
    return hmac.compare_digest(signature.encode(), _signature(password, int(expires)).encode())


def _signature(password: str, expires: int) -> str:
    key = hashlib.sha256(b"study-agent session:" + password.encode()).digest()
    return hmac.new(key, str(expires).encode(), hashlib.sha256).hexdigest()


class LoginAttempts:
    """Pauses sign-in after a run of wrong passwords, to slow down guessing."""

    def __init__(self) -> None:
        self._failures: list[float] = []

    def allowed(self, now: float) -> bool:
        self._failures = [at for at in self._failures if now - at < FAILURE_WINDOW_SECONDS]
        return len(self._failures) < MAX_FAILURES

    def failed(self, now: float) -> None:
        self._failures.append(now)
