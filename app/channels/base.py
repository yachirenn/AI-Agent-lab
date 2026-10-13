from dataclasses import dataclass


@dataclass(frozen=True)
class InboundMessage:
    """Format internal. Semua channel (Telegram, WhatsApp, simulator) diterjemahkan ke sini."""

    channel: str
    user_id: str
    chat_id: str
    message_id: str          # unik per channel, dipakai untuk dedup retry
    text: str
    is_start: bool = False
    start_payload: str | None = None   # mis. kode stasiun dari QR / deep link