import pytest

from app.channels import telegram
from app.db import repo
from scripts import poll


def _update():
    return {
        "update_id": 100,
        "message": {
            "message_id": 77,
            "chat": {"id": 12345, "type": "private"},
            "from": {"id": 12345, "is_bot": False},
            "text": "Halo dari Telegram",
        },
    }


def test_polling_advances_offset_after_persisting(monkeypatch):
    offsets = []
    saved = []

    monkeypatch.setattr(telegram, "delete_webhook", lambda: None)

    def fake_get_updates(offset):
        offsets.append(offset)
        if len(offsets) == 1:
            return [_update()]
        raise KeyboardInterrupt

    def fake_enqueue(**kwargs):
        saved.append(kwargs)
        return True

    monkeypatch.setattr(telegram, "get_updates", fake_get_updates)
    monkeypatch.setattr(repo, "enqueue_inbox", fake_enqueue)

    with pytest.raises(KeyboardInterrupt):
        poll.main()

    assert offsets == [None, 101]
    assert len(saved) == 1
    assert saved[0]["message_id"] == "12345:77"


def test_polling_does_not_advance_offset_when_persist_fails(monkeypatch):
    offsets = []
    attempts = []

    monkeypatch.setattr(telegram, "delete_webhook", lambda: None)
    monkeypatch.setattr(poll.time, "sleep", lambda _: None)

    def fake_get_updates(offset):
        offsets.append(offset)

        if len(offsets) <= 2:
            return [_update()]

        raise KeyboardInterrupt

    def fake_enqueue(**kwargs):
        attempts.append(kwargs)

        if len(attempts) == 1:
            raise RuntimeError("database unavailable")

        return True

    monkeypatch.setattr(telegram, "get_updates", fake_get_updates)
    monkeypatch.setattr(repo, "enqueue_inbox", fake_enqueue)

    with pytest.raises(KeyboardInterrupt):
        poll.main()

    assert offsets == [None, None, 101]
    assert len(attempts) == 2
