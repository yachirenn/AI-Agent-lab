from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone

_SECRETS = [
    (re.compile(r"bot\d{6,}:[A-Za-z0-9_-]{20,}"), "bot<redacted>"),
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/-]{10,}"), "Bearer <redacted>"),
    (re.compile(r"\b(?:gsk_|sk-or-|sk-|AIza)[A-Za-z0-9_-]{16,}"), "<redacted-key>"),
]
_STD = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


def redact(text: str) -> str:
    for pattern, replacement in _SECRETS:
        text = pattern.sub(replacement, text)
    return text


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


class JsonFormatter(logging.Formatter):
    """Satu baris JSON per log. Field di `extra={...}` ikut masuk, jadi bisa difilter per customer/tiket."""

    def format(self, record: logging.LogRecord) -> str:
        data = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        data.update({k: v for k, v in record.__dict__.items() if k not in _STD and not k.startswith("_")})
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return redact(json.dumps(data, ensure_ascii=False, default=str))


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    if os.environ.get("LOG_FORMAT", "text") == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(TextFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for noisy in ("httpx", "httpcore"):   # URL request bisa memuat rahasia
        logging.getLogger(noisy).setLevel(logging.WARNING)