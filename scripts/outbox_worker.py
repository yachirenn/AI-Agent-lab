import logging
import time

from dotenv import load_dotenv

load_dotenv()
from app.logging_config import setup_logging  # noqa: E402
from app.services import alerts, dispatcher  # noqa: E402

setup_logging()
log = logging.getLogger("outbox")


def main() -> None:
    log.info("outbox worker aktif (Ctrl+C untuk berhenti)")
    last_sweep = 0.0
    while True:
        try:
            if time.monotonic() - last_sweep > 30:
                alerts.sweep()
                last_sweep = time.monotonic()
            stats = dispatcher.run_once()
        except Exception:
            log.exception("siklus worker gagal")
            time.sleep(5)
            continue
        if not any(stats.values()):
            time.sleep(2)


if __name__ == "__main__":
    main()
