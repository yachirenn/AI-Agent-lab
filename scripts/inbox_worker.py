from __future__ import annotations

import logging
import time

from dotenv import load_dotenv

load_dotenv()

from app.channels.base import InboundMessage
from app.db import repo
from app.logging_config import setup_logging
from app.services.handler import handle_inbound

setup_logging()
log = logging.getLogger("inbox")

BATCH_SIZE = 10
MAX_ATTEMPTS = 6
IDLE_SECONDS = 2


def process_once() -> int:
    """Proses satu batch Inbox. Mengembalikan jumlah item yang diklaim."""
    items = repo.claim_inbox(limit=BATCH_SIZE)
    for item in items:
        inbox_id = item["id"]
        claim_token = item["claim_token"]

        try:
            # Hasil yang sudah tersimpan cukup difinalisasi ke Outbox.
            if item["result_ready"]:
                finalized = repo.finalize_stored_inbox_result(
                    inbox_id, claim_token=claim_token
                )
                if not finalized:
                    raise RuntimeError(
                        "Finalisasi hasil Inbox gagal; status atau hasil "
                        "Inbox tidak memenuhi syarat."
                    )
                continue

            # Jika pesan sudah tercatat tetapi hasil Inbox belum tersimpan,
            # jangan jalankan handler lagi karena efek samping mungkin terjadi.
            existing = repo.message_id_by_channel(
                item["channel"], item["message_id"]
            )
            if existing is not None:
                repo.fail_inbox(
                    inbox_id,
                    "Pemulihan manual diperlukan: pesan sudah tercatat di "
                    "conversations, tetapi hasil Inbox belum tersimpan.",
                    claim_token=claim_token,
                    attempts=item["attempts"],
                    max_attempts=MAX_ATTEMPTS,
                    permanent=True,
                )
                log.error(
                    "Inbox %s ditandai dead: hasil pemrosesan tidak ditemukan",
                    inbox_id,
                )
                continue

            msg = InboundMessage(
                channel=item["channel"],
                user_id=item["user_id"],
                chat_id=item["chat_id"],
                message_id=item["message_id"],
                text=item["body"],
                is_start=item["is_start"],
                start_payload=item["start_payload"],
            )

            reply = handle_inbound(msg)
            customer = repo.get_customer_by_identity(
                item["channel"], item["user_id"]
            )
            if customer is None:
                raise RuntimeError(
                    "Customer tidak ditemukan setelah pemrosesan pesan"
                )

            stored = repo.store_inbox_result(
                inbox_id,
                claim_token=claim_token,
                customer_id=customer["id"],
                reply_body=reply,
            )
            if not stored:
                raise RuntimeError(
                    "Hasil Inbox gagal disimpan; status bukan processing"
                )

            finalized = repo.finalize_stored_inbox_result(
                inbox_id, claim_token=claim_token
            )
            if not finalized:
                raise RuntimeError(
                    "Finalisasi hasil Inbox gagal; status atau hasil "
                    "Inbox tidak memenuhi syarat."
                )

        except Exception as exc:
            log.exception("Pemrosesan Inbox %s gagal", inbox_id)
            try:
                repo.fail_inbox(
                    inbox_id,
                    str(exc),
                    claim_token=claim_token,
                    attempts=item["attempts"],
                    max_attempts=MAX_ATTEMPTS,
                )
            except Exception:
                log.exception(
                    "Gagal memperbarui status Inbox %s setelah error",
                    inbox_id,
                )

    return len(items)


def main() -> None:
    repo.get_pool()
    log.info("Inbox worker aktif (Ctrl+C untuk berhenti)")

    try:
        while True:
            try:
                processed = process_once()
            except Exception:
                log.exception("Siklus Inbox worker gagal")
                time.sleep(IDLE_SECONDS)
                continue

            if processed == 0:
                time.sleep(IDLE_SECONDS)
    finally:
        repo.close_pool()


if __name__ == "__main__":
    main()
