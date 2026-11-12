from __future__ import annotations

import json
from fastapi.testclient import TestClient

from app.api.main import app

client = TestClient(app)
TELEGRAM_SECRET = "telegram-secret-limit-test"
CMS_SECRET = "cms-secret-limit-test"


def test_telegram_payload_under_limit_accepted(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", TELEGRAM_SECRET)
    monkeypatch.setattr("app.db.repo.enqueue_inbox", lambda **kw: True)

    normal_payload = {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "chat": {"id": 123, "type": "private"},
            "from": {"id": 123, "is_bot": False},
            "text": "Halo",
        },
    }
    res = client.post(
        "/webhook/telegram",
        json=normal_payload,
        headers={"X-Telegram-Bot-Api-Secret-Token": TELEGRAM_SECRET},
    )
    assert res.status_code == 200
    assert res.json() == {"ok": True}


def test_telegram_payload_over_content_length_limit_returns_413():
    # 256 KB = 262,144 bytes; buat payload sebesar 270 KB
    large_body = b"x" * (270 * 1024)
    res = client.post(
        "/webhook/telegram",
        content=large_body,
        headers={
            "Content-Length": str(len(large_body)),
            "Content-Type": "application/json",
            "X-Telegram-Bot-Api-Secret-Token": TELEGRAM_SECRET,
        },
    )
    assert res.status_code == 413
    data = res.json()
    assert "melebihi batas maksimal" in data["detail"].lower()
    assert "262144" in data["detail"]


def test_whatsapp_payload_over_content_length_limit_returns_413():
    # 1 MB = 1,048,576 bytes; buat payload sebesar 1.1 MB
    large_body = b"w" * (1100 * 1024)
    res = client.post(
        "/webhook/whatsapp",
        content=large_body,
        headers={
            "Content-Length": str(len(large_body)),
            "Content-Type": "application/json",
        },
    )
    assert res.status_code == 413
    data = res.json()
    assert "melebihi batas maksimal" in data["detail"].lower()
    assert "1048576" in data["detail"]


def test_whatsapp_gowa_payload_over_limit_returns_413():
    large_body = b"g" * (1050 * 1024)
    res = client.post(
        "/webhook/whatsapp/gowa",
        content=large_body,
        headers={
            "Content-Length": str(len(large_body)),
            "Content-Type": "application/json",
        },
    )
    assert res.status_code == 413
    assert res.json()["detail"].startswith("Ukuran payload melebihi batas")


def test_cms_payload_over_limit_returns_413(monkeypatch):
    monkeypatch.setenv("CMS_WEBHOOK_SECRET", CMS_SECRET)
    large_body = b"c" * (1050 * 1024)
    res = client.post(
        "/webhook/cms",
        content=large_body,
        headers={
            "Content-Length": str(len(large_body)),
            "Content-Type": "application/json",
            "X-CMS-Secret": CMS_SECRET,
        },
    )
    assert res.status_code == 413


def test_custom_env_payload_limit_override(monkeypatch):
    # Set limit Telegram menjadi sangat kecil (500 bytes)
    monkeypatch.setenv("MAX_TELEGRAM_PAYLOAD_BYTES", "500")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", TELEGRAM_SECRET)

    body_600_bytes = json.dumps({"text": "a" * 600}).encode("utf-8")
    res = client.post(
        "/webhook/telegram",
        content=body_600_bytes,
        headers={
            "Content-Length": str(len(body_600_bytes)),
            "Content-Type": "application/json",
            "X-Telegram-Bot-Api-Secret-Token": TELEGRAM_SECRET,
        },
    )
    assert res.status_code == 413
    assert "500" in res.json()["detail"]


def test_streaming_chunked_payload_over_limit_returns_413(monkeypatch):
    monkeypatch.setenv("MAX_TELEGRAM_PAYLOAD_BYTES", "1000")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", TELEGRAM_SECRET)

    def chunk_generator():
        yield b"a" * 600
        yield b"b" * 600

    res = client.post(
        "/webhook/telegram",
        content=chunk_generator(),
        headers={
            "Content-Type": "application/json",
            "X-Telegram-Bot-Api-Secret-Token": TELEGRAM_SECRET,
        },
    )
    assert res.status_code == 413
    assert "1000" in res.json()["detail"]


def test_get_endpoints_and_unlimited_paths_unaffected():
    # GET tidak terpengaruh middleware limit
    res_health = client.get("/health")
    assert res_health.status_code == 200

    res_ready = client.get("/health/ready")
    assert res_ready.status_code in (200, 503)
