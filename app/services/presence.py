"""Best-effort chat presence indicators for inbound processing."""
from __future__ import annotations

import logging

from app.channels import telegram, whatsapp
from app.channels.base import InboundMessage

log = logging.getLogger(__name__)


def indicate_typing(msg: InboundMessage) -> None:
    """Tampilkan typing tanpa pernah menggagalkan pemrosesan pesan utama."""
    try:
        if msg.channel == "telegram":
            telegram.send_typing(msg.chat_id)
        elif msg.channel == "whatsapp":
            whatsapp.send_chat_presence(msg.chat_id, "start")
    except Exception:
        # Presence hanya UX tambahan. Jika platform/GOWA gagal, agent tetap berjalan.
        log.warning("gagal mengirim indikator typing", extra={"channel": msg.channel}, exc_info=True)
