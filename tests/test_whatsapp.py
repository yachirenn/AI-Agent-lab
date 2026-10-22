import hashlib
import hmac
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.channels import whatsapp
from app.channels.base import InboundMessage
from app.db import repo
from app.services import handler, pipeline
from tests.test_escalation import _done_user, _msg

client = TestClient(app)
SECRET = "s3cret"


def _sign(raw: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def _payload(text="MULAI sunset-road", mid="wamid.1", sender="628123456789", kind="text"):
    msg = {"from": sender, "id": mid, "type": kind}
    if kind == "text":
        msg["text"] = {"body": text}
    return {"object": "whatsapp_business_account",
            "entry": [{"changes": [{"field": "messages", "value": {"messages": [msg]}}]}]}


@pytest.fixture(autouse=True)
def wa_env(monkeypatch):
    monkeypatch.setenv("WHATSAPP_APP_SECRET", SECRET)
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "verif-123")


def test_signature_accepts_valid_and_rejects_everything_else(monkeypatch):
    raw = b'{"a":1}'
    assert whatsapp.verify_signature(raw, _sign(raw))
    assert not whatsapp.verify_signature(raw, _sign(raw, "salah"))
    assert not whatsapp.verify_signature(raw, None)
    assert not whatsapp.verify_signature(raw + b" ", _sign(raw))          # body diubah
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "")
    assert not whatsapp.verify_signature(raw, _sign(raw, ""))             # tanpa secret: tolak semua


def test_parse_start_message_with_station_payload():
    (m,) = whatsapp.parse_webhook(_payload("MULAI Sunset-Road"))
    assert (m.channel, m.user_id, m.is_start, m.start_payload) == ("whatsapp", "628123456789", True, "sunset-road")


def test_parse_ordinary_text_is_not_start():
    (m,) = whatsapp.parse_webhook(_payload("poin saya berapa?"))
    assert not m.is_start and m.start_payload is None


@pytest.mark.parametrize("payload", [_payload(kind="image"), {"entry": "x"}, [], None, {"entry": [{"changes": [1]}]}])
def test_parse_ignores_non_text_and_garbage(payload):
    assert whatsapp.parse_webhook(payload) == []


def test_verification_handshake():
    ok = client.get("/webhook/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "verif-123", "hub.challenge": "42"})
    assert ok.status_code == 200 and ok.text == "42"
    bad = client.get("/webhook/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "salah", "hub.challenge": "42"})
    assert bad.status_code == 403


def test_webhook_rejects_bad_signature():
    raw = json.dumps(_payload()).encode()
    r = client.post("/webhook/whatsapp", content=raw, headers={"X-Hub-Signature-256": _sign(raw, "salah")})
    assert r.status_code == 403


def test_webhook_persists_signed_messages_to_inbox(monkeypatch):
    seen = []

    def fake_enqueue(**kwargs):
        seen.append(kwargs)
        return True

    monkeypatch.setattr(repo, "enqueue_inbox", fake_enqueue)
    raw = json.dumps(_payload()).encode()
    r = client.post(
        "/webhook/whatsapp",
        content=raw,
        headers={
            "X-Hub-Signature-256": _sign(raw),
            "Content-Type": "application/json",
        },
    )

    assert r.status_code == 200
    assert len(seen) == 1
    assert seen[0]["channel"] == "whatsapp"
    assert seen[0]["user_id"] == "628123456789"
    assert seen[0]["message_id"] == "wamid.1"
    assert seen[0]["body"] == "MULAI sunset-road"
    assert seen[0]["is_start"] is True
    assert seen[0]["start_payload"] == "sunset-road"


def test_first_message_is_greeting_not_a_name():
    user = f"62{uuid.uuid4().int % 10**10}"
    reply = handler.handle_inbound(InboundMessage("whatsapp", user, user, f"wamid.{uuid.uuid4()}", "halo"))
    assert "Siapa nama Anda?" in reply
    assert repo.get_customer_by_identity("whatsapp", user)["name"] is None


def test_plain_stop_withdraws_consent():
    user, c = _done_user()
    repo.set_marketing_consent(c["id"], True, "command")
    handler.handle_inbound(_msg(user, "stop"))
    assert repo.get_customer_by_identity("sim", user)["consent_marketing"] is False