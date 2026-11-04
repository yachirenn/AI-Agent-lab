from __future__ import annotations

import hashlib
import hmac
import os
import re
from typing import Any

import httpx

from app.channels.base import InboundMessage

_GRAPH = "https://graph.facebook.com"
# Pesan pertama dari QR: "MULAI sunset-road" (teks isian wa.me). WhatsApp tidak punya tombol /start.
_START_RE = re.compile(r"^(?:mulai|start)(?:\s+([A-Za-z0-9_-]{1,64}))?$", re.IGNORECASE)
_client = httpx.Client(timeout=httpx.Timeout(20.0, connect=10.0))


class WhatsAppError(RuntimeError):
    def __init__(self, message: str, *, permanent: bool = False) -> None:
        super().__init__(message)
        self.permanent = permanent


def verify_signature(raw_body: bytes, header: str | None) -> bool:
    """HMAC-SHA256 atas body MENTAH dengan App Secret. Tanpa secret: tolak semua (fail closed)."""
    secret = os.environ.get("WHATSAPP_APP_SECRET", "") or os.environ.get("WHATSAPP_WEBHOOK_SECRET", "")
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header[len("sha256="):], expected)


def _dicts(value: Any) -> list[dict[str, Any]]:
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def parse_webhook(payload: Any) -> list[InboundMessage]:
    """Mendukung payload webhook dari GOWA (go-whatsapp-web-multidevice) dan Meta Cloud API."""
    if not isinstance(payload, dict):
        return []

    # 1. Format GOWA (go-whatsapp-web-multidevice)
    if payload.get("event") == "message" or ("payload" in payload and isinstance(payload.get("payload"), dict)):
        p = payload.get("payload", {})
        if p.get("is_from_me"):
            return []  # Abaikan pesan keluar dari nomor bot sendiri agar tidak looping

        sender = str(p.get("from") or p.get("sender") or "")
        clean_sender = sender.split("@")[0].strip()
        body = str(p.get("body") or p.get("text") or "").strip()
        mid = str(p.get("id") or "")

        if not body or not clean_sender or not mid:
            return []

        start = _START_RE.match(body)
        return [
            InboundMessage(
                channel="whatsapp",
                user_id=clean_sender,
                chat_id=clean_sender,
                message_id=mid,
                text=body,
                is_start=bool(start),
                start_payload=start.group(1).lower() if start and start.group(1) else None,
            )
        ]

    # 2. Format Meta Cloud API
    out: list[InboundMessage] = []
    for entry in _dicts(payload.get("entry")):
        for change in _dicts(entry.get("changes")):
            value = change.get("value") if isinstance(change.get("value"), dict) else {}
            for m in _dicts(value.get("messages")):
                body = m.get("text", {}).get("body") if isinstance(m.get("text"), dict) else None
                sender, mid = m.get("from"), m.get("id")
                if m.get("type") != "text" or not all(isinstance(x, str) and x for x in (body, sender, mid)):
                    continue
                start = _START_RE.match(body.strip())
                out.append(InboundMessage(
                    channel="whatsapp", user_id=sender, chat_id=sender, message_id=mid, text=body,
                    is_start=bool(start),
                    start_payload=start.group(1).lower() if start and start.group(1) else None,
                ))
    return out


def _is_permanent(status: int) -> bool:
    # 401 (token kedaluwarsa), 408, 429 akan pulih setelah diperbaiki/ditunggu. 4xx lain tidak.
    return 400 <= status < 500 and status not in (401, 408, 429)


def _post_meta(payload: dict[str, Any]) -> None:
    token = os.environ["WHATSAPP_ACCESS_TOKEN"]
    url = f"{_GRAPH}/{os.environ['WHATSAPP_API_VERSION']}/{os.environ['WHATSAPP_PHONE_NUMBER_ID']}/messages"
    try:
        resp = _client.post(url, json=payload, headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError as exc:
        raise WhatsAppError(f"koneksi gagal: {type(exc).__name__}") from None
    if resp.status_code != 200:
        try:
            code = resp.json()["error"]["code"]
        except Exception:
            code = None
        raise WhatsAppError(f"HTTP {resp.status_code} code={code}", permanent=_is_permanent(resp.status_code))


def send_text(to: str, text: str) -> None:
    """Mengirim pesan teks via GOWA (default) atau Meta Cloud API."""
    provider = os.environ.get("WHATSAPP_PROVIDER", "gowa").lower()
    if provider == "meta":
        _post_meta({"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text, "preview_url": False}})
        return

    # Kirim via GOWA (go-whatsapp-web-multidevice)
    gowa_url = os.environ.get("GOWA_BASE_URL", "http://127.0.0.1:3000").rstrip("/")
    url = f"{gowa_url}/send/message"

    clean_to = to.split("@")[0].strip()
    if clean_to.startswith("08"):
        clean_to = "628" + clean_to[2:]
    elif clean_to.startswith("+"):
        clean_to = clean_to[1:]

    payload = {
        "phone": clean_to,
        "message": text,
    }
    headers = {"Content-Type": "application/json"}
    basic_user = os.environ.get("GOWA_BASIC_AUTH_USER")
    basic_pass = os.environ.get("GOWA_BASIC_AUTH_PASS")
    auth = (basic_user, basic_pass) if basic_user and basic_pass else None

    try:
        resp = _client.post(url, json=payload, headers=headers, auth=auth)
    except httpx.HTTPError as exc:
        raise WhatsAppError(f"koneksi ke GOWA gagal: {type(exc).__name__}") from None

    if resp.status_code not in (200, 201):
        raise WhatsAppError(f"GOWA HTTP {resp.status_code}: {resp.text}", permanent=_is_permanent(resp.status_code))


def send_template(to: str, name: str, params: list[str], language: str = "id") -> None:
    """Wajib di Meta Cloud API untuk pesan di luar jendela 24 jam; di GOWA dikirim langsung sebagai teks."""
    provider = os.environ.get("WHATSAPP_PROVIDER", "gowa").lower()
    if provider == "meta":
        _post_meta({
            "messaging_product": "whatsapp", "to": to, "type": "template",
            "template": {"name": name, "language": {"code": language},
                         "components": [{"type": "body", "parameters": [{"type": "text", "text": p} for p in params]}]},
        })
        return

    # Untuk GOWA, gabungkan parameter template menjadi pesan teks biasa
    text = " ".join(params) if params else f"[{name}]"
    send_text(to, text)
