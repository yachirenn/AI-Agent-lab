import uuid

import pytest

from app.agent import loop
from app.agent.llm_client import LLMResponse, ToolCall
from app.channels.base import InboundMessage
from app.db import repo
from app.services import alerts, escalation, handler
from tests.test_agent import ScriptedLLM, _echo_tool_result


def _done_user(name="Tes"):
    user = f"u-{uuid.uuid4()}"
    c = repo.register_customer("sim", user)
    with repo.tx() as conn:
        conn.execute("UPDATE customers SET registration_state='done', name=%s WHERE id=%s", (name, c["id"]))
    return user, repo.get_customer_by_identity("sim", user)


def _msg(user, text):
    return InboundMessage("sim", user, user, f"{user}:{uuid.uuid4()}", text)


@pytest.mark.parametrize("text,category", [
    ("terbakar nih chargernya", "safety"),
    ("mobil saya mogok kehabisan baterai", "stranded"),
    ("charging berhenti sendiri jam 2", "charger_failure"),
    ("saldo terpotong dobel bayar", "payment"),
    ("ini darurat", "emergency"),
    ("poin saya tidak masuk", "points_issue"),
    ("saya mau refund", "refund"),
    ("saya kecewa dengan pelayanan", "complaint"),
])
def test_classify_known_categories(text, category):
    assert escalation.classify(text).category == category


@pytest.mark.parametrize("text", ["jam buka stasiun?", "poin saya berapa?"])
def test_normal_messages_are_level_1(text):
    assert escalation.classify(text) is None


def test_urgent_creates_ticket_alerts_staff_and_skips_llm(monkeypatch):
    sent = []
    monkeypatch.setenv("STAFF_TELEGRAM_CHAT_ID", "staff-1")
    monkeypatch.setattr(alerts.telegram, "send_message", lambda chat, text: sent.append((chat, text)))
    monkeypatch.setattr(handler, "run_agent", lambda *a, **k: pytest.fail("LLM tidak boleh dipanggil untuk urgent"))
    user, c = _done_user("Made")

    reply = handler.handle_inbound(_msg(user, "charger #04 berhenti sendiri, saya menunggu"))

    assert "tiket #" in reply
    assert len(sent) == 1 and sent[0][0] == "staff-1"
    assert "URGENT" in sent[0][1] and c["customer_code"] in sent[0][1]
    (ticket,) = repo.open_tickets(c["id"])
    assert (ticket["level"], ticket["category"], ticket["source"]) == (3, "charger_failure", "rule")
    assert ticket["notified_at"] is not None


def test_repeated_urgent_alerts_staff_only_once(monkeypatch):
    sent = []
    monkeypatch.setenv("STAFF_TELEGRAM_CHAT_ID", "staff-1")
    monkeypatch.setattr(alerts.telegram, "send_message", lambda chat, text: sent.append(text))
    user, c = _done_user()

    handler.handle_inbound(_msg(user, "terbakar!"))
    second = handler.handle_inbound(_msg(user, "masih terbakar"))

    assert len(sent) == 1
    assert "sudah kami terima" in second
    assert len(repo.open_tickets(c["id"])) == 1


def test_rate_limit_warns_once_then_stays_silent(monkeypatch):
    monkeypatch.setenv("AGENT_MSGS_PER_MINUTE", "3")
    monkeypatch.setattr(handler, "run_agent", lambda *a, **k: "ok")
    user, _ = _done_user()

    replies = [handler.handle_inbound(_msg(user, f"halo {i}")) for i in range(5)]

    assert replies[:3] == ["ok"] * 3
    assert replies[3] == handler.RATE_REPLY
    assert replies[4] is None


def test_agent_ticket_tool_creates_level2_for_session_customer():
    _, c = _done_user()
    call = ToolCall("create_support_ticket", {
        "category": "complaint", "summary": "Charger #02 lambat sekali", "customer_id": "bukan-saya",
    })
    reply = loop.run_agent(c["id"], "saya mau komplain", llm=ScriptedLLM(LLMResponse("", [call]), _echo_tool_result))

    assert "ticket_id" in reply
    assert [(t["level"], t["category"], t["source"]) for t in repo.open_tickets(c["id"])] == [(2, "complaint", "agent")]


def test_agent_cannot_create_urgent_ticket():
    _, c = _done_user()
    call = ToolCall("create_support_ticket", {"category": "safety", "summary": "ada asap dari charger"})
    reply = loop.run_agent(c["id"], "halo", llm=ScriptedLLM(LLMResponse("", [call]), _echo_tool_result))

    assert "error" in reply
    assert repo.open_tickets(c["id"]) == []


def test_resolved_ticket_allows_new_ticket_in_same_category():
    _, c = _done_user()
    t1, created1 = repo.create_ticket(c["id"], 2, "complaint", "satu", "rule")
    t2, created2 = repo.create_ticket(c["id"], 2, "complaint", "dua", "rule")
    assert created1 and not created2 and t1["id"] == t2["id"]

    repo.resolve_ticket(t1["id"])
    t3, created3 = repo.create_ticket(c["id"], 2, "complaint", "tiga", "rule")
    assert created3 and t3["id"] != t1["id"]