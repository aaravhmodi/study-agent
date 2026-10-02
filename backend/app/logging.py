import logging
import re

_SENSITIVE_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|authorization|cookie|password|token|mfa)(\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"(?i)Bearer\s+[A-Za-z0-9._~+/=-]+"),
)


def redact(value: str) -> str:
    result = value
    for pattern in _SENSITIVE_PATTERNS:
        result = pattern.sub(
            lambda match: f"{match.group(1)}=[REDACTED]" if match.lastindex else "[REDACTED]",
            result,
        )
    return result


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
