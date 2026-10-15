from __future__ import annotations

import logging
from typing import Any

from app.db import repo
from app.services import dispatcher

logger = logging.getLogger(__name__)


class HandoverError(RuntimeError):
    pass


def send_reply(
    ticket_id: int,
    text: str,
    staff_name: str = "Staf CS",
) -> dict[str, Any]:
    """Kirim balasan staf manusia langsung ke pelanggan (Telegram/WhatsApp) dan catat di riwayat obrolan."""
    clean_text = " ".join(text.strip().split())
    if not clean_text:
        raise HandoverError("Pesan tidak boleh kosong.")
    if len(clean_text) > 1500:
        raise HandoverError("Pesan terlalu panjang (maksimal 1500 karakter).")

    ticket = repo.get_ticket(ticket_id)
    if ticket is None:
        raise HandoverError(f"Tiket #{ticket_id} tidak ditemukan.")

    channel = ticket.get("channel")
    recipient = ticket.get("recipient")
    if not channel or not recipient:
        raise HandoverError(
            f"Tidak dapat menemukan channel atau tujuan pengiriman untuk pelanggan {ticket.get('customer_code', '')}."
        )

    outbound_text = f"[{staff_name}] {clean_text}"

    # Kirim langsung ke channel pelanggan via dispatcher
    try:
        dispatcher.send(channel, recipient, outbound_text)
    except Exception as exc:
        logger.exception("Gagal mengirim pesan live handover tiket=%s", ticket_id)
        raise HandoverError(f"Gagal mengirim ke {channel}: {exc}") from None

    # Catat pesan keluar ke tabel conversations
    repo.record_message(ticket["customer_id"], channel, "out", outbound_text)

    # Otomatis tandai tiket menjadi 'in_progress' jika sebelumnya masih 'open'
    if ticket["status"] == "open":
        repo.update_ticket_status(ticket_id, "in_progress")

    logger.info(
        "Live handover terkirim: tiket=#%s customer=%s channel=%s",
        ticket_id,
        ticket["customer_id"],
        channel,
    )
    return {
        "status": "sent",
        "ticket_id": ticket_id,
        "customer_id": ticket["customer_id"],
        "channel": channel,
        "recipient": recipient,
        "message": outbound_text,
    }


def set_status(ticket_id: int, status: str) -> bool:
    """Ubah status tiket: open, in_progress, atau resolved."""
    if status not in ("open", "in_progress", "resolved"):
        raise HandoverError(f"Status tidak valid: {status}")
    return repo.update_ticket_status(ticket_id, status)


def resolve(
    ticket_id: int,
    closing_message: str | None = None,
    staff_name: str = "Staf CS",
) -> bool:
    """Selesaikan tiket dengan pesan penutup opsional ke pelanggan."""
    if closing_message and closing_message.strip():
        send_reply(ticket_id, closing_message, staff_name=staff_name)
    return repo.update_ticket_status(ticket_id, "resolved")
