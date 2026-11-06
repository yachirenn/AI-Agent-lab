from __future__ import annotations

import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from app.db import repo

logger = logging.getLogger(__name__)
WIB = ZoneInfo("Asia/Jakarta")


def detect() -> int:
    return repo.detect_inactive(
        min_sessions=int(os.environ.get("INACTIVITY_MIN_SESSIONS", "4")),
        factor=float(os.environ.get("INACTIVITY_FACTOR", "2")),
        min_days=int(os.environ.get("INACTIVITY_MIN_DAYS", "7")),
        lookback_days=90,
    )


def in_send_window(now: datetime) -> bool:
    start = int(os.environ.get("RETENTION_START_HOUR", "8"))
    end = int(os.environ.get("RETENTION_END_HOUR", "20"))
    return start <= now.astimezone(WIB).hour < end


def _message(name: str | None) -> str:
    greeting = f"Halo {name}," if name else "Halo,"
    return (
        f"{greeting} sudah lama Anda tidak charging di Enerva ⚡\n"
        "Ada kendala yang bisa kami bantu? Balas pesan ini kapan saja.\n\n"
        "(Pesan promo. Balas /stop untuk berhenti menerima info promo.)"
    )


def send_retention(now: datetime) -> int:
    """Antrekan pesan retensi ke Outbox (bukan kirim langsung).

    Outbox worker yang mengirim dan menandai `retention_sent_at` setelah delivery sukses,
    sehingga proses yang mati di tengah jalan tidak lagi bisa menghilangkan pesan.
    """
    if not in_send_window(now):
        return 0   # alert tetap 'pending', dikirim pada run berikutnya yang masuk jam kirim
    cooldown = int(os.environ.get("RETENTION_COOLDOWN_DAYS", "30"))
    queued = 0
    for alert in repo.pending_retention_alerts():
        # Utamakan Telegram, lalu WhatsApp
        chat_id = repo.get_identity(alert["customer_id"], "telegram")
        channel = "telegram"
        if chat_id is None:
            chat_id = repo.get_identity(alert["customer_id"], "whatsapp")
            channel = "whatsapp"
        if chat_id is None:
            continue
        claimed = repo.claim_retention(alert["id"], cooldown)
        if claimed is None:
            continue
        try:
            added = repo.enqueue_retention(
                alert["id"],
                channel=channel,
                recipient=chat_id,
                body=_message(claimed["name"]),
                customer_id=claimed["customer_id"],
            )
        except Exception:
            logger.exception("gagal mengantre retensi alert=%s", alert["id"])
            continue
        queued += int(added)
    return queued


def run_once(now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now(WIB)
    result = {
        "resolved": repo.resolve_returned_alerts(),
        "detected": detect(),
        "sent": send_retention(now),
    }
    logger.info("inaktivitas: %s", result)
    return result