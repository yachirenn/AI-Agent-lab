import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.db import repo
from app.services import alerts, dispatcher
from tests.test_charging import _payload, _post
from tests.test_escalation import _done_user


def _enqueue(n=1, **kw):
    for i in range(n):
        repo.enqueue_message(kind="notification", channel="telegram", recipient=f"r{i}", body="b", **kw)


def _row():
    with repo.tx() as conn:
        return conn.execute(
            "SELECT status, attempts, last_error, next_attempt_at > now() AS in_future FROM outbox ORDER BY id LIMIT 1"
        ).fetchone()


def _make_due():
    with repo.tx() as conn:
        conn.execute("UPDATE outbox SET next_attempt_at = now()")


def test_enqueue_is_idempotent_by_dedup_key():
    assert repo.enqueue_message(kind="notification", channel="telegram", recipient="r", body="b", dedup_key="k1")
    assert not repo.enqueue_message(kind="notification", channel="telegram", recipient="r", body="b", dedup_key="k1")


def test_transient_failure_retries_with_backoff_then_succeeds(monkeypatch):
    _enqueue()

    def down(*a):
        raise dispatcher.DeliveryError("HTTP 503")

    monkeypatch.setattr(dispatcher, "send", down)
    assert dispatcher.run_once() == {"sent": 0, "retry": 1, "dead": 0}
    r = _row()
    assert (r["status"], r["attempts"], r["in_future"]) == ("pending", 1, True)
    assert dispatcher.run_once() == {"sent": 0, "retry": 0, "dead": 0}   # belum waktunya

    monkeypatch.setattr(dispatcher, "send", lambda *a: None)
    _make_due()
    assert dispatcher.run_once()["sent"] == 1
    assert _row()["status"] == "sent"


def test_permanent_failure_goes_dead_immediately(monkeypatch):
    _enqueue()

    def blocked(*a):
        raise dispatcher.DeliveryError("HTTP 403", permanent=True)

    monkeypatch.setattr(dispatcher, "send", blocked)
    assert dispatcher.run_once()["dead"] == 1
    assert _row()["status"] == "dead"


def test_dead_after_max_attempts(monkeypatch):
    _enqueue()
    monkeypatch.setattr(dispatcher, "MAX_ATTEMPTS", 2)

    def down(*a):
        raise dispatcher.DeliveryError("HTTP 503")

    monkeypatch.setattr(dispatcher, "send", down)
    dispatcher.run_once()
    _make_due()
    assert dispatcher.run_once()["dead"] == 1


def test_stale_lock_is_reclaimed_after_worker_crash():
    _enqueue()
    first = repo.claim_outbox(10, 120)
    assert len(first) == 1 and repo.claim_outbox(10, 120) == []          # masih terkunci
    with repo.tx() as conn:                                                # simulasi: worker mati, lock kedaluwarsa
        conn.execute("UPDATE outbox SET locked_until = now() - interval '1 second'")
    again = repo.claim_outbox(10, 120)
    assert [r["id"] for r in again] == [first[0]["id"]] and again[0]["attempts"] == 2


def test_concurrent_workers_never_claim_the_same_row():
    _enqueue(10)
    with ThreadPoolExecutor(max_workers=4) as pool:
        batches = list(pool.map(lambda _: repo.claim_outbox(10, 120), range(4)))
    ids = [r["id"] for batch in batches for r in batch]
    assert len(ids) == 10 and len(set(ids)) == 10


def test_charging_enqueues_notification_once():
    c = repo.register_customer("telegram", f"tg-{uuid.uuid4()}")
    payload = _payload(c["customer_code"])
    assert _post(payload).json()["status"] == "created"
    assert _post(payload).json()["status"] == "duplicate"
    with repo.tx() as conn:
        rows = conn.execute("SELECT channel, kind, body FROM outbox").fetchall()
    assert len(rows) == 1 and rows[0]["channel"] == "telegram" and "423" in rows[0]["body"]


def test_sweep_requeues_urgent_ticket_missing_its_alert(monkeypatch):
    monkeypatch.setenv("STAFF_TELEGRAM_CHAT_ID", "staff-1")
    _, c = _done_user()
    repo.create_ticket(c["id"], 3, "safety", "ada asap", "rule")          # proses mati sebelum sempat mengantre alert
    with repo.tx() as conn:
        conn.execute("UPDATE cs_tickets SET created_at = now() - interval '5 minutes'")
    assert alerts.sweep() == 1
    assert alerts.sweep() == 0                                              # tidak menggandakan