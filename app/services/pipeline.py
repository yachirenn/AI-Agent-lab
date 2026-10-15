import logging

from app.channels import telegram
from app.channels.base import InboundMessage
from app.services import dispatcher
from app.services.handler import handle_inbound

logger = logging.getLogger(__name__)


def process_message(msg: InboundMessage) -> None:
    """Pintu masuk semua channel. Balasan ke customer dikirim langsung (ia sedang menunggu)."""
    try:
        reply = handle_inbound(msg)
        if reply:
            dispatcher.send(msg.channel, msg.chat_id, reply)
    except Exception:
        logger.exception("gagal memproses pesan", extra={"channel": msg.channel})   # tanpa isi pesan


def process_update(update: dict) -> None:
    """Update mentah Telegram (dipakai webhook dan polling)."""
    msg = telegram.parse_update(update)
    if msg is not None:
        process_message(msg)