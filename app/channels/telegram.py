from __future__ import annotations

import logging
import os
import re
from typing import Any

import httpx
from dotenv import load_dotenv

from app.channels.base import InboundMessage

load_dotenv()

# URL request Telegram berisi token bot. Jangan sampai ikut tercetak di log.
logging.getLogger("httpx").setLevel(logging.WARNING)

_API = "https://api.telegram.org"
_PAYLOAD_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_client = httpx.Client(timeout=httpx.Timeout(40.0, connect=10.0))


class TelegramError(RuntimeError):
    pass


def _call(method: str, **params: Any) -> Any:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    try:
        resp = _client.post(f"{_API}/bot{token}/{method}", json=params)
    except httpx.HTTPError as exc:
        # `from None`: pesan exception asli memuat URL (dan token), jadi tidak diteruskan.
        raise TelegramError(f"{method} gagal: {type(exc).__name__}") from None
    if resp.status_code != 200:
        raise TelegramError(f"{method} -> HTTP {resp.status_code}")
    return resp.json()["result"]


def parse_update(update: dict[str, Any]) -> InboundMessage | None:
    """Hanya pesan teks dari chat pribadi. Selain itu diabaikan."""
    message = update.get("message")
    if not message:
        return None
    chat, sender, text = message.get("chat", {}), message.get("from", {}), message.get("text")
    if chat.get("type") != "private" or sender.get("is_bot") or not text:
        return None

    parts = text.split(maxsplit=1)
    is_start = parts[0].split("@")[0] == "/start"
    payload = None
    if is_start and len(parts) > 1 and _PAYLOAD_RE.match(parts[1].strip()):
        payload = parts[1].strip().lower()

    return InboundMessage(
        channel="telegram",
        user_id=str(sender["id"]),
        chat_id=str(chat["id"]),
        message_id=f"{chat['id']}:{message['message_id']}",
        text=text,
        is_start=is_start,
        start_payload=payload,
    )


def send_message(chat_id: str, text: str) -> None:
    # Sengaja tanpa parse_mode: nama customer adalah input tak tepercaya.
    _call("sendMessage", chat_id=chat_id, text=text)


def get_updates(offset: int | None) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"timeout": 30, "allowed_updates": ["message"]}
    if offset is not None:
        params["offset"] = offset
    return _call("getUpdates", **params)


def delete_webhook() -> None:
    _call("deleteWebhook")   # Telegram menolak getUpdates selagi webhook aktif


def set_webhook(url: str, secret: str) -> None:
    _call("setWebhook", url=url, secret_token=secret, allowed_updates=["message"])