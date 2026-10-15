from __future__ import annotations

from typing import Any

from app.channels.base import InboundMessage
from app.db import repo
from app.services import registration
from app.agent.loop import run_agent
import os

from app.services import escalation, preferences, registration   # gabungkan dengan import registration yang sudah ada

RATE_WINDOW_SECONDS = 60
RATE_REPLY = "Pesan Anda terlalu cepat. Mohon tunggu sebentar sebelum mengirim pesan berikutnya."

_CONSENT_COMMANDS = {"/stop": False, "/subscribe": True}
STOP_REPLY = (
    "Baik, Anda tidak akan menerima pesan promo lagi. "
    "Pesan layanan seperti struk charging dan notifikasi poin tetap kami kirim."
)
SUBSCRIBE_REPLY = "Terima kasih, Anda akan menerima info promo dan reward Enerva. Balas /stop kapan saja untuk berhenti."

_PRIVACY_COMMANDS = {"/preferensi", "/lupa", "/ingat"}


def _privacy_command(customer: dict[str, Any], msg: InboundMessage, state: str) -> str | None:
    parts = msg.text.strip().lower().split()
    if not parts:
        return None
    command = parts[0].split("@")[0]
    if command not in _PRIVACY_COMMANDS:
        return None
    if state != "done":
        return "Selesaikan pendaftaran dulu.\n\n" + registration.PROMPTS[state]

    cid = customer["id"]
    if command == "/preferensi":
        return preferences.describe(repo.list_preferences(cid))
    if command == "/lupa":
        deleted = repo.delete_preferences(cid)
        repo.set_personalization(cid, False)
        return f"{deleted} preferensi dihapus. Enerva berhenti mempelajari preferensi dari chat Anda. Balas /ingat untuk mengaktifkan lagi."
    repo.set_personalization(cid, True)
    return "Personalisasi diaktifkan lagi. Balas /preferensi untuk melihat data Anda kapan saja."


def _consent_command(customer: dict[str, Any], msg: InboundMessage, state: str) -> str | None:
    parts = msg.text.strip().lower().split()
    if not parts:
        return None
    command = parts[0].split("@")[0]
    if len(parts) == 1 and command in {"stop", "berhenti"}:
        command = "/stop"
    if len(parts) == 1 and command in {"subscribe", "langganan"}:
        command = "/subscribe"
    if command not in _CONSENT_COMMANDS:
        return None
    granted = _CONSENT_COMMANDS[command]
    if granted and state != "done":
        return "Selesaikan pendaftaran dulu, lalu kirim /subscribe lagi.\n\n" + registration.PROMPTS[state]
    repo.set_marketing_consent(customer["id"], granted, "command")
    if granted:
        return SUBSCRIBE_REPLY
    return STOP_REPLY if state == "done" else STOP_REPLY + "\n\n" + registration.PROMPTS[state]

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


def _handle_registered(customer: dict[str, Any], msg: InboundMessage) -> str | None:
    esc = escalation.classify(msg.text)
    if esc is not None:   # aturan pasti, LLM tidak dilibatkan
        return escalation.process(customer, esc, msg.text)

    recent = repo.count_recent_inbound(customer["id"], RATE_WINDOW_SECONDS)   # sudah termasuk pesan ini
    limit = int(os.environ.get("AGENT_MSGS_PER_MINUTE", "8"))
    if recent > limit:
        return RATE_REPLY if recent == limit + 1 else None   # beri tahu sekali, lalu diam

    reply = run_agent(customer["id"], msg.text)
    preferences.schedule(customer["id"], msg.channel, msg.message_id, msg.text)
    return reply


def _route(customer: dict[str, Any], msg: InboundMessage) -> str | None:
    state = customer["registration_state"]
    
    command_reply = _consent_command(customer, msg, state)
    privacy_reply = _privacy_command(customer, msg, state)
    if privacy_reply is not None:
        return privacy_reply
    if command_reply is not None:
        return command_reply

    first_contact = state == "ask_name" and repo.count_inbound(customer["id"]) <= 1
    if msg.is_start or first_contact:   # pesan pertama apa pun dari customer baru dianggap sapaan, bukan nama
      if state == "done":
          return f"Anda sudah terdaftar. Customer ID Anda: {customer['customer_code']}"
      return registration.PROMPTS[state]

    if state == "done":
        return _handle_registered(customer, msg)

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