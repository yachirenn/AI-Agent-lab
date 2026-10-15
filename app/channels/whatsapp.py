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
    secret = os.environ.get("WHATSAPP_APP_SECRET", "")
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header[len("sha256="):], expected)


def _dicts(value: Any) -> list[dict[str, Any]]:
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def parse_webhook(payload: Any) -> list[InboundMessage]:
    """Hanya pesan teks. Status pengiriman, gambar, dan lokasi diabaikan."""
    if not isinstance(payload, dict):
        return []
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


def _post(payload: dict[str, Any]) -> None:
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
    """Teks bebas hanya diterima dalam jendela layanan (24 jam sejak pesan terakhir customer)."""
    _post({"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text, "preview_url": False}})


def send_template(to: str, name: str, params: list[str], language: str = "id") -> None:
    """Wajib untuk pesan yang kita mulai di luar jendela 24 jam (struk, retensi, campaign)."""
    _post({
        "messaging_product": "whatsapp", "to": to, "type": "template",
        "template": {"name": name, "language": {"code": language},
                     "components": [{"type": "body", "parameters": [{"type": "text", "text": p} for p in params]}]},
    })