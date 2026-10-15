from __future__ import annotations

import logging

from app.channels import telegram, whatsapp
from app.db import repo

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 6
LOCK_SECONDS = 120   # harus lebih lama dari satu pengiriman terlama


class DeliveryError(RuntimeError):
    def __init__(self, message: str, *, permanent: bool = False) -> None:
        super().__init__(message)
        self.permanent = permanent


def send(channel: str, recipient: str, text: str) -> None:
    """Satu pintu kirim untuk semua channel. Error diterjemahkan menjadi permanen/sementara."""
    try:
        if channel == "telegram":
            telegram.send_message(recipient, text)
        elif channel == "whatsapp":
            whatsapp.send_text(recipient, text)
        else:
            raise DeliveryError(f"channel tidak didukung: {channel}", permanent=True)
    except telegram.TelegramError as exc:
        # 400/403/404: chat tidak ada atau bot diblokir. Mengulang tidak akan membantu.
        raise DeliveryError(str(exc), permanent=exc.status in (400, 403, 404)) from None
    except whatsapp.WhatsAppError as exc:
        raise DeliveryError(str(exc), permanent=exc.permanent) from None


def _record_outbound(row: dict) -> None:
    if row["customer_id"] and row["kind"] == "notification":
        try:
            repo.record_message(row["customer_id"], row["channel"], "out", row["body"])
        except Exception:
            logger.exception("gagal mencatat pesan keluar", extra={"outbox_id": row["id"]})


def run_once(limit: int = 20) -> dict[str, int]:
    stats = {"sent": 0, "retry": 0, "dead": 0}
    for row in repo.claim_outbox(limit, LOCK_SECONDS):
        try:
            send(row["channel"], row["recipient"], row["body"])   # dicari saat dipanggil, jadi bisa di-monkeypatch di tes
        except DeliveryError as exc:
            error, permanent = str(exc), exc.permanent
        except Exception as exc:
            error, permanent = type(exc).__name__, False
        else:
            repo.complete_outbox(row["id"])
            _record_outbound(row)
            stats["sent"] += 1
            continue

        status = repo.fail_outbox(
            row["id"], error, permanent=permanent, attempts=row["attempts"], max_attempts=MAX_ATTEMPTS
        )
        stats["dead" if status == "dead" else "retry"] += 1
        logger.log(
            logging.ERROR if status == "dead" else logging.WARNING,
            "pengiriman outbox gagal",
            extra={"outbox_id": row["id"], "kind": row["kind"], "outcome": status,
                   "attempts": row["attempts"], "error": error},
        )
    return stats