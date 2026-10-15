import json
import logging

from app.logging_config import JsonFormatter, redact


def test_redact_hides_bot_token_and_bearer():
    text = ("POST https://api.telegram.org/bot123456789:ABCdefGHIjklMNOpqrsTUVwxyz0123456789/sendMessage "
            "Authorization: Bearer abcdefghijklmnop123456")
    out = redact(text)
    assert "ABCdef" not in out and "abcdefghijklmnop" not in out


def test_json_formatter_keeps_extra_fields_and_redacts():
    rec = logging.LogRecord("t", logging.INFO, "f", 1, "kunci gsk_" + "a" * 30, (), None)
    rec.ticket_id = 7
    data = json.loads(JsonFormatter().format(rec))
    assert data["ticket_id"] == 7 and "aaaa" not in data["msg"]