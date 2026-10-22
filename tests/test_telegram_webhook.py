import json

from fastapi.testclient import TestClient

from app.api.main import app
from app.db import repo

client = TestClient(app)
SECRET = "telegram-test-secret"


def _update(text="Halo dari Telegram", chat_id=12345, message_id=77):
    return {
        "update_id": 9001,
        "message": {
            "message_id": message_id,
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": chat_id, "is_bot": False},
            "text": text,
        },
    }


def test_telegram_webhook_persists_message(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", SECRET)
    seen = []

    def fake_enqueue(**kwargs):
        seen.append(kwargs)
        return True

    monkeypatch.setattr(repo, "enqueue_inbox", fake_enqueue)

    response = client.post(
        "/webhook/telegram",
        json=_update(),
        headers={"X-Telegram-Bot-Api-Secret-Token": SECRET},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert len(seen) == 1
    assert seen[0]["channel"] == "telegram"
    assert seen[0]["user_id"] == "12345"
    assert seen[0]["chat_id"] == "12345"
    assert seen[0]["message_id"] == "12345:77"
    assert seen[0]["body"] == "Halo dari Telegram"


def test_telegram_webhook_rejects_wrong_secret(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", SECRET)

    response = client.post(
        "/webhook/telegram",
        json=_update(),
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong-secret"},
    )

    assert response.status_code == 403


def test_telegram_webhook_returns_503_when_inbox_fails(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", SECRET)

    def fail_enqueue(**kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(repo, "enqueue_inbox", fail_enqueue)

    response = client.post(
        "/webhook/telegram",
        json=_update(),
        headers={"X-Telegram-Bot-Api-Secret-Token": SECRET},
    )

    assert response.status_code == 503


def test_telegram_webhook_ignores_non_private_updates(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", SECRET)
    called = []

    monkeypatch.setattr(
        repo, "enqueue_inbox", lambda **kwargs: called.append(kwargs)
    )

    update = _update()
    update["message"]["chat"]["type"] = "group"

    response = client.post(
        "/webhook/telegram",
        json=update,
        headers={"X-Telegram-Bot-Api-Secret-Token": SECRET},
    )

    assert response.status_code == 200
    assert called == []
