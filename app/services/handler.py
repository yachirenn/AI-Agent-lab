from __future__ import annotations

from typing import Any

from app.channels.base import InboundMessage
from app.db import repo
from app.services import registration


def handle_inbound(msg: InboundMessage) -> str | None:
    """Kembalikan teks balasan, atau None jika pesan duplikat / tidak perlu dibalas."""
    customer = repo.register_customer(
        msg.channel, msg.user_id, station_code=msg.start_payload if msg.is_start else None
    )
    if not repo.record_message(customer["id"], msg.channel, "in", msg.text, msg.message_id):
        return None   # retry dari platform, sudah pernah diproses

    reply = _route(customer, msg)
    if reply:
        repo.record_message(customer["id"], msg.channel, "out", reply)
    return reply


def _route(customer: dict[str, Any], msg: InboundMessage) -> str:
    state = customer["registration_state"]

    if msg.is_start:   # /start tidak dianggap sebagai jawaban
        if state == "done":
            return f"Anda sudah terdaftar. Customer ID Anda: {customer['customer_code']}"
        return registration.PROMPTS[state]

    if state == "done":
        return "Pesan Anda sudah kami terima. Asisten Enerva akan segera tersedia."

    try:
        next_state, answer = registration.handle_answer(state, msg.text)
    except registration.InvalidAnswer as exc:
        return f"{exc}\n\n{registration.PROMPTS[state]}"

    if not repo.advance_registration(
        customer["id"], state, next_state, answer.fields, answer.vehicle_model
    ):
        return "Pesan sebelumnya masih diproses. Mohon kirim ulang jawaban Anda."

    if next_state == "done":
        return (
            f"Terima kasih, {customer['name']}! Pendaftaran selesai.\n"
            f"Customer ID Anda: {customer['customer_code']}"
        )
    return registration.PROMPTS[next_state]