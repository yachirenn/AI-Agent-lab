import logging
import time

from dotenv import load_dotenv

load_dotenv()

from app.channels import telegram
from app.db import repo
from app.logging_config import setup_logging

setup_logging()
log = logging.getLogger("poll")


def main() -> None:
    telegram.delete_webhook()
    log.info("polling dimulai (Ctrl+C untuk berhenti)")
    offset: int | None = None

    while True:
        try:
            updates = telegram.get_updates(offset)
        except telegram.TelegramError as exc:
            log.warning("%s, coba lagi 3 detik", exc)
            time.sleep(3)
            continue

        for update in updates:
            try:
                msg = telegram.parse_update(update)

                if msg is not None:
                    repo.enqueue_inbox(
                        channel=msg.channel,
                        user_id=msg.user_id,
                        chat_id=msg.chat_id,
                        message_id=msg.message_id,
                        body=msg.text,
                        is_start=msg.is_start,
                        start_payload=msg.start_payload,
                    )
            except Exception:
                log.exception(
                    "gagal menyimpan update Telegram; offset belum dimajukan"
                )
                time.sleep(3)
                break
            else:
                # Pesan tersimpan atau update tidak relevan.
                offset = update["update_id"] + 1


if __name__ == "__main__":
    main()
