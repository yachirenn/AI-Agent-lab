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
from tests.conftest import is_db_available
from tests.test_escalation import _done_user, _msg

client = TestClient(app)
SECRET = "s3cret"


def _sign(raw: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


GOWA_SECRET = "gowa-secret"


def _gowa_payload(text="Halo dari GOWA", mid="GOWA-MSG-API"):
    return {
        "event": "message",
        "payload": {
            "id": mid,
            "from": "628987654321@s.whatsapp.net",
            "body": text,
            "is_from_me": False,
        },
    }


def _gowa_sign(raw: bytes) -> str:
    return _sign(raw, GOWA_SECRET)


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
    assert whatsapp.verify_signature(raw, _sign(raw), SECRET)
    assert not whatsapp.verify_signature(raw, _sign(raw, "salah"), SECRET)
    assert not whatsapp.verify_signature(raw, None, SECRET)
    assert not whatsapp.verify_signature(raw + b" ", _sign(raw), SECRET)  # body diubah
    assert not whatsapp.verify_signature(raw, _sign(raw), "")  # tanpa secret: tolak semua


def test_webhook_secrets_are_provider_specific(monkeypatch):
    monkeypatch.setenv("WHATSAPP_APP_SECRET", SECRET)
    monkeypatch.setenv("WHATSAPP_WEBHOOK_SECRET", GOWA_SECRET)
    raw = b'{"a":1}'

    assert whatsapp.verify_signature(raw, _sign(raw, SECRET), whatsapp.webhook_secret("meta"))
    assert whatsapp.verify_signature(raw, _sign(raw, GOWA_SECRET), whatsapp.webhook_secret("gowa"))
    assert not whatsapp.verify_signature(raw, _sign(raw, GOWA_SECRET), whatsapp.webhook_secret("meta"))
    assert not whatsapp.verify_signature(raw, _sign(raw, SECRET), whatsapp.webhook_secret("gowa"))


def test_webhook_secret_rejects_unknown_provider():
    with pytest.raises(ValueError, match="tidak didukung"):
        whatsapp.webhook_secret("unknown")


def test_gowa_webhook_persists_signed_message_to_inbox(monkeypatch):
    monkeypatch.setenv("WHATSAPP_WEBHOOK_SECRET", GOWA_SECRET)
    seen = []
    monkeypatch.setattr(repo, "enqueue_inbox", lambda **kwargs: seen.append(kwargs))
    raw = json.dumps(_gowa_payload()).encode()

    response = client.post(
        "/webhook/whatsapp/gowa",
        content=raw,
        headers={"X-Hub-Signature-256": _gowa_sign(raw)},
    )

    assert response.status_code == 200
    assert len(seen) == 1
    assert seen[0]["channel"] == "whatsapp"
    assert seen[0]["message_id"] == "GOWA-MSG-API"


def test_gowa_webhook_rejects_meta_signature(monkeypatch):
    monkeypatch.setenv("WHATSAPP_WEBHOOK_SECRET", GOWA_SECRET)
    raw = json.dumps(_gowa_payload()).encode()
    response = client.post(
        "/webhook/whatsapp/gowa",
        content=raw,
        headers={"X-Hub-Signature-256": _sign(raw, SECRET)},
    )
    assert response.status_code == 403


def test_webhook_whatsapp_accepts_either_configured_secret(monkeypatch):
    monkeypatch.setenv("WHATSAPP_APP_SECRET", SECRET)
    monkeypatch.setenv("WHATSAPP_WEBHOOK_SECRET", GOWA_SECRET)
    monkeypatch.setattr(repo, "enqueue_inbox", lambda **kwargs: True)
    raw = json.dumps(_payload()).encode()

    # Diterima jika ditandatangani dengan secret Meta
    r_meta = client.post(
        "/webhook/whatsapp",
        content=raw,
        headers={"X-Hub-Signature-256": _sign(raw, SECRET)},
    )
    assert r_meta.status_code == 200

    # Diterima jika ditandatangani dengan secret GOWA
    r_gowa = client.post(
        "/webhook/whatsapp",
        content=raw,
        headers={"X-Hub-Signature-256": _sign(raw, GOWA_SECRET)},
    )
    assert r_gowa.status_code == 200

    # Ditolak jika signature salah / tidak cocok dengan secret mana pun
    r_bad = client.post(
        "/webhook/whatsapp",
        content=raw,
        headers={"X-Hub-Signature-256": _sign(raw, "kunci-salah")},
    )
    assert r_bad.status_code == 403


def test_gowa_webhook_requires_configured_secret(monkeypatch):
    monkeypatch.delenv("WHATSAPP_WEBHOOK_SECRET", raising=False)
    raw = json.dumps(_gowa_payload()).encode()
    response = client.post(
        "/webhook/whatsapp/gowa",
        content=raw,
        headers={"X-Hub-Signature-256": _gowa_sign(raw)},
    )
    assert response.status_code == 403


def test_gowa_webhook_rejects_tampered_body(monkeypatch):
    monkeypatch.setenv("WHATSAPP_WEBHOOK_SECRET", GOWA_SECRET)
    raw = json.dumps(_gowa_payload()).encode()
    response = client.post(
        "/webhook/whatsapp/gowa",
        content=raw + b" ",
        headers={"X-Hub-Signature-256": _gowa_sign(raw)},
    )
    assert response.status_code == 403


# Existing Meta endpoint regression tests continue below.


def test_signature_legacy_behavior_is_explicit(monkeypatch):
    raw = b'{"a":1}'
    monkeypatch.setenv("WHATSAPP_APP_SECRET", SECRET)
    assert whatsapp.verify_signature(raw, _sign(raw), SECRET)
    monkeypatch.delenv("WHATSAPP_APP_SECRET", raising=False)
    assert not whatsapp.verify_signature(raw, _sign(raw), None)


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


@pytest.mark.skipif(not is_db_available(), reason="Membutuhkan database test")
def test_first_message_is_greeting_not_a_name():
    user = f"62{uuid.uuid4().int % 10**10}"
    reply = handler.handle_inbound(InboundMessage("whatsapp", user, user, f"wamid.{uuid.uuid4()}", "halo"))
    assert "Siapa nama Anda?" in reply
    assert repo.get_customer_by_identity("whatsapp", user)["name"] is None


@pytest.mark.skipif(not is_db_available(), reason="Membutuhkan database test")
def test_plain_stop_withdraws_consent():
    user, c = _done_user()
    repo.set_marketing_consent(c["id"], True, "command")
    handler.handle_inbound(_msg(user, "stop"))
    assert repo.get_customer_by_identity("sim", user)["consent_marketing"] is False


def test_parse_gowa_message():
    gowa_payload = {
        "event": "message",
        "payload": {
            "id": "GOWA-MSG-123",
            "from": "628987654321@s.whatsapp.net",
            "body": "Halo min, mau tanya stasiun Sanur",
            "is_from_me": False,
        },
    }
    msgs = whatsapp.parse_webhook(gowa_payload)
    assert len(msgs) == 1
    m = msgs[0]
    assert m.channel == "whatsapp"
    assert m.user_id == "628987654321"
    assert m.chat_id == "628987654321"
    assert m.message_id == "GOWA-MSG-123"
    assert m.text == "Halo min, mau tanya stasiun Sanur"
    assert not m.is_start


def test_parse_gowa_ignores_own_messages():
    gowa_payload = {
        "event": "message",
        "payload": {
            "id": "GOWA-MSG-999",
            "from": "628987654321@s.whatsapp.net",
            "body": "Pesan bot sendiri",
            "is_from_me": True,
        },
    }
    assert whatsapp.parse_webhook(gowa_payload) == []


def test_parse_gowa_start_payload():
    gowa_payload = {
        "event": "message",
        "payload": {
            "id": "GOWA-MSG-START",
            "from": "628987654321@s.whatsapp.net",
            "body": "MULAI sunset-road",
            "is_from_me": False,
        },
    }
    msgs = whatsapp.parse_webhook(gowa_payload)
    assert len(msgs) == 1
    assert msgs[0].is_start is True
    assert msgs[0].start_payload == "sunset-road"


def test_gowa_send_text_calls_correct_endpoint(monkeypatch):
    called = {}

    class FakeResponse:
        status_code = 200
        text = "ok"

    def fake_post(url, json, headers, auth):
        called["url"] = url
        called["json"] = json
        called["headers"] = headers
        called["auth"] = auth
        return FakeResponse()

    monkeypatch.setattr(whatsapp._client, "post", fake_post)
    monkeypatch.setenv("WHATSAPP_PROVIDER", "gowa")
    monkeypatch.setenv("GOWA_BASE_URL", "http://127.0.0.1:3000")

    whatsapp.send_text("08123456789", "Halo Budi")
    assert called["url"] == "http://127.0.0.1:3000/send/message"
    assert called["json"]["phone"] == "628123456789"
    assert called["json"]["message"] == "Halo Budi"
    assert called["headers"]["X-Device-Id"] == "enerva-bot"


def test_gowa_send_chat_presence_calls_correct_endpoint(monkeypatch):
    called = {}

    class FakeResponse:
        status_code = 200
        text = "ok"

    def fake_post(url, json, headers, auth):
        called["url"] = url
        called["json"] = json
        called["headers"] = headers
        called["auth"] = auth
        return FakeResponse()

    monkeypatch.setattr(whatsapp._client, "post", fake_post)
    monkeypatch.setenv("WHATSAPP_PROVIDER", "gowa")
    monkeypatch.setenv("GOWA_BASE_URL", "http://127.0.0.1:3000")

    whatsapp.send_chat_presence("08123456789", "start")
    assert called["url"] == "http://127.0.0.1:3000/send/chat-presence"
    assert called["json"] == {"phone": "628123456789", "action": "start"}
    assert called["headers"]["X-Device-Id"] == "enerva-bot"


def test_gowa_send_chat_presence_rejects_invalid_action(monkeypatch):
    monkeypatch.setenv("WHATSAPP_PROVIDER", "gowa")
    with pytest.raises(ValueError, match="action presence tidak didukung"):
        whatsapp.send_chat_presence("08123456789", "invalid_action")


def test_gowa_send_chat_presence_maps_composing_to_start(monkeypatch):
    called = {}

    class FakeResponse:
        status_code = 200
        text = "ok"

    monkeypatch.setattr(
        whatsapp._client,
        "post",
        lambda url, json, headers, auth: called.update(url=url, json=json) or FakeResponse(),
    )
    monkeypatch.setenv("WHATSAPP_PROVIDER", "gowa")
    whatsapp.send_chat_presence("08123456789", "composing")
    assert called["json"]["action"] == "start"


def test_meta_send_chat_presence_is_noop(monkeypatch):
    monkeypatch.setenv("WHATSAPP_PROVIDER", "meta")
    called = []
    monkeypatch.setattr(whatsapp._client, "post", lambda *a, **k: called.append(True))
    whatsapp.send_chat_presence("08123456789", "composing")
    assert called == []


def test_indicate_typing_swallows_failure_safely(monkeypatch):
    from app.services.presence import indicate_typing
    msg = InboundMessage("whatsapp", "user1", "user1", "m1", "halo")
    monkeypatch.setattr(
        whatsapp,
        "send_chat_presence",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("GOWA offline")),
    )
    # Tidak boleh melempar exception: agent tetap aman berjalan
    indicate_typing(msg)
