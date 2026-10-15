from __future__ import annotations

import uuid
import pytest

from app.channels.base import InboundMessage
from app.db import repo
from app.services import dispatcher, handover, handler


def _user_with_ticket(channel: str = "sim", level: int = 2, category: str = "complaint"):
    ext = f"u-{uuid.uuid4()}"
    c = repo.register_customer(channel, ext)
    with repo.tx() as conn:
        conn.execute("UPDATE customers SET registration_state = 'done', name = 'Budi' WHERE id = %s", (c["id"],))
    ticket, _ = repo.create_ticket(c["id"], level, category, "Keluhan charger bermasalah", "rule")
    return c, ticket, ext


def test_send_reply_delivers_and_records_message(monkeypatch):
    sent = []
    monkeypatch.setattr(dispatcher, "send", lambda ch, rc, text: sent.append((ch, rc, text)))

    c, ticket, ext = _user_with_ticket("telegram")
    res = handover.send_reply(ticket["id"], "Sedang kami periksa ya", staff_name="Staf CS")

    assert res["status"] == "sent"
    assert len(sent) == 1
    assert sent[0][0] == "telegram"
    assert sent[0][1] == ext
    assert "[Staf CS] Sedang kami periksa ya" in sent[0][2]

    # Cek bahwa tersimpan di tabel conversations
    messages = repo.customer_conversations(c["id"])
    assert len(messages) == 1
    assert messages[0]["direction"] == "out"
    assert "[Staf CS]" in messages[0]["body"]

    # Status tiket otomatis berubah jadi in_progress
    t_after = repo.get_ticket(ticket["id"])
    assert t_after["status"] == "in_progress"


def test_send_reply_validations():
    c, ticket, _ = _user_with_ticket()

    with pytest.raises(handover.HandoverError, match="kosong"):
        handover.send_reply(ticket["id"], "   ")

    with pytest.raises(handover.HandoverError, match="panjang"):
        handover.send_reply(ticket["id"], "x" * 1501)

    with pytest.raises(handover.HandoverError, match="tidak ditemukan"):
        handover.send_reply(999999, "Halo")


def test_resolve_ticket_with_closing_message(monkeypatch):
    sent = []
    monkeypatch.setattr(dispatcher, "send", lambda ch, rc, text: sent.append((ch, rc, text)))

    c, ticket, ext = _user_with_ticket("telegram")
    handover.resolve(ticket["id"], closing_message="Kendala telah selesai diperbaiki.")

    assert len(sent) == 1
    assert "selesai diperbaiki" in sent[0][2]

    t_after = repo.get_ticket(ticket["id"])
    assert t_after["status"] == "resolved"


def test_active_handover_pauses_agent_automatic_replies(monkeypatch):
    monkeypatch.setattr(handler, "run_agent", lambda *a, **k: pytest.fail("LLM tidak boleh dipanggil saat Handover aktif"))

    c, ticket, ext = _user_with_ticket("sim")
    repo.update_ticket_status(ticket["id"], "in_progress")

    msg = InboundMessage("sim", ext, ext, f"m-{uuid.uuid4()}", "Halo, ada orang yang bisa bantu saya?")
    reply = handler.handle_inbound(msg)

    assert "staf CS Enerva yang sedang menangani" in reply

    # Jika tiket diselesaikan, bot AI aktif kembali
    repo.update_ticket_status(ticket["id"], "resolved")
    monkeypatch.setattr(handler, "run_agent", lambda *a, **k: "Jawaban normal agent AI")
    msg2 = InboundMessage("sim", ext, ext, f"m-{uuid.uuid4()}", "Poin saya berapa?")
    reply2 = handler.handle_inbound(msg2)
    assert reply2 == "Jawaban normal agent AI"


def test_active_handover_still_triggers_safety_rules(monkeypatch):
    c, ticket, ext = _user_with_ticket("sim")
    repo.update_ticket_status(ticket["id"], "in_progress")

    # Walaupun status in_progress, jika ada bahaya kebakaran/darurat, escalation rule tetap jalan
    msg = InboundMessage("sim", ext, ext, f"m-{uuid.uuid4()}", "DARURAT chargernya terbakar!")
    reply = handler.handle_inbound(msg)

    assert "darurat" in reply.lower() or "keselamatan" in reply.lower()
