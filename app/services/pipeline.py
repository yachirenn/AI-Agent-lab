import logging

from app.channels import telegram
from app.services.handler import handle_inbound

logger = logging.getLogger(__name__)


def process_update(update: dict) -> None:
    """Satu-satunya pintu masuk. Dipakai webhook maupun polling."""
    msg = telegram.parse_update(update)
    if msg is None:
        return
    try:
        reply = handle_inbound(msg)
        if reply:
            telegram.send_message(msg.chat_id, reply)
    except Exception:
        # Jangan log isi pesan: itu data pribadi.
        logger.exception("gagal memproses update_id=%s", update.get("update_id"))