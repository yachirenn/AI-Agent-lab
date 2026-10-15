from __future__ import annotations

import logging
import os
from typing import Any

from app.db import repo

logger = logging.getLogger(__name__)


def _text(ticket_id: int, customer: dict[str, Any], category: str, summary: str) -> str:
    sessions = repo.recent_sessions(customer["id"], 1)
    station = sessions[0]["station"] if sessions else "-"
    return (
        f"🚨 URGENT CUSTOMER ALERT — tiket #{ticket_id}\n"
        f"Kategori: {category}\n"
        f"Customer: {customer.get('name') or '-'} ({customer['customer_code']})\n"
        f"Stasiun terakhir: {station}\n"
        f"Pesan: {summary}\n"
        f"Status: customer menunggu bantuan."
    )


def notify_staff(ticket_id: int, customer: dict[str, Any], category: str, summary: str) -> bool:
    """Hanya mengantre. Pengiriman, retry, dan penandaan notified_at dikerjakan worker."""
    chat_id = os.environ.get("STAFF_TELEGRAM_CHAT_ID")
    if not chat_id:
        logger.warning("STAFF_TELEGRAM_CHAT_ID kosong, alert tidak diantre", extra={"ticket_id": ticket_id})
        return False
    try:
        return repo.enqueue_message(
            kind="staff_alert", channel="telegram", recipient=chat_id,
            body=_text(ticket_id, customer, category, summary),
            ticket_id=ticket_id, dedup_key=f"ticket:{ticket_id}",
        )
    except Exception:
        logger.exception("gagal mengantre alert", extra={"ticket_id": ticket_id})
        return False


def sweep(min_age_seconds: int = 30) -> int:
    """Jaring pengaman: tiket urgent yang prosesnya mati sebelum sempat mengantre alert."""
    queued = 0
    for t in repo.unalerted_urgent_tickets(min_age_seconds):
        customer = {"id": t["customer_id"], "customer_code": t["customer_code"], "name": t["name"]}
        if notify_staff(t["id"], customer, t["category"], t["summary"]):
            queued += 1
            logger.warning("alert urgent disapu ulang", extra={"ticket_id": t["id"]})
    return queued