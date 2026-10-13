from __future__ import annotations

import logging
import os
from typing import Any

from app.channels import telegram
from app.db import repo

logger = logging.getLogger(__name__)


def notify_staff(ticket_id: int, customer: dict[str, Any], category: str, summary: str) -> None:
    """Kegagalan kirim hanya di-log: tiket sudah tersimpan, notified_at tetap NULL sebagai penanda."""
    chat_id = os.environ.get("STAFF_TELEGRAM_CHAT_ID")
    if not chat_id:
        logger.warning("STAFF_TELEGRAM_CHAT_ID kosong, alert tiket #%s tidak terkirim", ticket_id)
        return
    try:
        sessions = repo.recent_sessions(customer["id"], 1)
        last_station = sessions[0]["station"] if sessions else "-"
        text = (
            f"🚨 URGENT CUSTOMER ALERT — tiket #{ticket_id}\n"
            f"Kategori: {category}\n"
            f"Customer: {customer.get('name') or '-'} ({customer['customer_code']})\n"
            f"Stasiun terakhir: {last_station}\n"
            f"Pesan: {summary}\n"
            f"Status: customer menunggu bantuan."
        )
        telegram.send_message(chat_id, text)
        repo.mark_notified(ticket_id)
    except Exception:
        logger.exception("alert staf gagal tiket=%s", ticket_id)