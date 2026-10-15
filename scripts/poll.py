import logging
import time

from app.channels import telegram
from app.services.pipeline import process_update

from dotenv import load_dotenv
load_dotenv()
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
            process_update(update)
            offset = update["update_id"] + 1   # konfirmasi: update ini tidak dikirim ulang


if __name__ == "__main__":
    main()