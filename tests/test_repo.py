import uuid

import pytest

from app.db import repo


def test_register_is_idempotent():
    ext = f"tg-{uuid.uuid4()}"
    first = repo.register_customer("telegram", ext, "Made")
    second = repo.register_customer("telegram", ext)
    assert first["id"] == second["id"]
    assert first["customer_code"].startswith("ENV-")


def test_award_points_is_not_double_counted():
    customer = repo.register_customer("telegram", f"tg-{uuid.uuid4()}")
    assert repo.award_points(customer["id"], 423, "charging", "session-1") is True
    assert repo.award_points(customer["id"], 423, "charging", "session-1") is False
    assert repo.get_balance(customer["id"]) == 423

def test_enqueue_inbox_deduplicates_message():
    message = {
        "channel": "telegram",
        "user_id": "user-101",
        "chat_id": "chat-101",
        "message_id": "chat-101:501",
        "body": "Halo",
    }

    assert repo.enqueue_inbox(**message) is True
    assert repo.enqueue_inbox(**message) is False


def test_claim_inbox_increments_attempts():
    assert repo.enqueue_inbox(
        channel="telegram",
        user_id="user-102",
        chat_id="chat-102",
        message_id="chat-102:502",
        body="Tes klaim",
    ) is True

    claimed = repo.claim_inbox(limit=10, lock_seconds=120)

    assert len(claimed) == 1
    assert claimed[0]["message_id"] == "chat-102:502"
    assert claimed[0]["status"] if "status" in claimed[0] else True
    assert claimed[0]["attempts"] == 1



def test_claim_inbox_reclaims_expired_lease():
    assert repo.enqueue_inbox(
        channel="telegram",
        user_id="user-expired-lease",
        chat_id="chat-expired-lease",
        message_id="chat-expired-lease:1",
        body="Tes klaim kedaluwarsa",
    ) is True

    first = repo.claim_inbox(limit=1, lock_seconds=120)
    assert len(first) == 1
    inbox_id = first[0]["id"]
    first_token = first[0]["claim_token"]
    assert first[0]["attempts"] == 1

    with repo.tx() as conn:
        conn.execute(
            """
            UPDATE inbox
            SET locked_until = now() - interval '1 second'
            WHERE id = %s AND status = 'processing'
            """,
            (inbox_id,),
        )

    second = repo.claim_inbox(limit=1, lock_seconds=120)

    assert len(second) == 1
    assert second[0]["id"] == inbox_id
    assert second[0]["attempts"] == 2
    assert second[0]["claim_token"] != first_token

    # Worker lama tidak boleh menyimpan hasil dengan token kedaluwarsa.
    assert repo.store_inbox_result(
        inbox_id,
        claim_token=first_token,
        customer_id=None,
        reply_body="Hasil dari worker lama",
    ) is False


def test_finalize_stored_inbox_result_enqueues_one_reply():
    customer = repo.register_customer("telegram", "user-103")

    repo.enqueue_inbox(
        channel="telegram",
        user_id="user-103",
        chat_id="chat-103",
        message_id="chat-103:503",
        body="Apa kabar?",
    )
    claimed = repo.claim_inbox()

    assert len(claimed) == 1
    inbox_id = claimed[0]["id"]

    assert repo.store_inbox_result(
        inbox_id,
        claim_token=claimed[0]["claim_token"],
        customer_id=customer["id"],
        reply_body="Saya baik!",
    ) is True

    assert repo.finalize_stored_inbox_result(
        inbox_id, claim_token=claimed[0]["claim_token"]
    ) is True
    assert repo.finalize_stored_inbox_result(
        inbox_id, claim_token=claimed[0]["claim_token"]
    ) is False

    with repo.tx() as conn:
        rows = conn.execute(
            """
            SELECT kind, channel, recipient, body, dedup_key
            FROM outbox
            WHERE dedup_key = %s
            """,
            ("inbox-reply:telegram:chat-103:chat-103:503",),
        ).fetchall()

        inbox = conn.execute(
            "SELECT status FROM inbox WHERE id = %s",
            (inbox_id,),
        ).fetchone()

    assert len(rows) == 1
    assert rows[0]["kind"] == "reply"
    assert rows[0]["recipient"] == "chat-103"
    assert rows[0]["body"] == "Saya baik!"
    assert inbox["status"] == "processed"


def test_finalize_stored_result_without_reply():
    repo.enqueue_inbox(
        channel="telegram",
        user_id="user-104",
        chat_id="chat-104",
        message_id="chat-104:504",
        body="Pesan tanpa balasan",
    )
    claimed = repo.claim_inbox()
    inbox_id = claimed[0]["id"]

    assert repo.store_inbox_result(
        inbox_id,
        claim_token=claimed[0]["claim_token"],
        customer_id=None,
        reply_body=None,
    ) is True

    assert repo.finalize_stored_inbox_result(
        inbox_id, claim_token=claimed[0]["claim_token"]
    ) is True

    with repo.tx() as conn:
        inbox = conn.execute(
            "SELECT status FROM inbox WHERE id = %s",
            (inbox_id,),
        ).fetchone()
        count = conn.execute(
            "SELECT count(*) AS total FROM outbox"
        ).fetchone()["total"]

    assert inbox["status"] == "processed"
    assert count == 0


def test_fail_inbox_schedules_retry_then_dead(monkeypatch):
    repo.enqueue_inbox(
        channel="telegram",
        user_id="user-105",
        chat_id="chat-105",
        message_id="chat-105:505",
        body="Pesan gagal",
    )
    claimed = repo.claim_inbox()
    inbox_id = claimed[0]["id"]

    assert repo.fail_inbox(
        inbox_id,
        "Gangguan sementara",
        claim_token=claimed[0]["claim_token"],
        attempts=1,
        max_attempts=2,
    ) == "pending"

    with repo.tx() as conn:
        row = conn.execute(
            "SELECT status, last_error, locked_until FROM inbox WHERE id = %s",
            (inbox_id,),
        ).fetchone()

    assert row["status"] == "pending"
    assert row["last_error"] == "Gangguan sementara"
    assert row["locked_until"] is None

    with repo.tx() as conn:
        conn.execute(
            """
            UPDATE inbox
            SET next_attempt_at = now()
            WHERE id = %s
            """,
            (inbox_id,),
        )

    claimed = repo.claim_inbox()
    assert len(claimed) == 1
    assert claimed[0]["attempts"] == 2

    assert repo.fail_inbox(
        inbox_id,
        "Batas percobaan tercapai",
        claim_token=claimed[0]["claim_token"],
        attempts=2,
        max_attempts=2,
    ) == "dead"


def test_fail_inbox_preserves_stored_result_for_retry():
    customer = repo.register_customer("telegram", "user-106")

    repo.enqueue_inbox(
        channel="telegram",
        user_id="user-106",
        chat_id="chat-106",
        message_id="chat-106:606",
        body="Tolong cek pesanan saya",
    )
    claimed = repo.claim_inbox()
    inbox_id = claimed[0]["id"]

    assert repo.store_inbox_result(
        inbox_id,
        claim_token=claimed[0]["claim_token"],
        customer_id=customer["id"],
        reply_body="Hasil sudah disimpan",
    )

    assert repo.fail_inbox(
        inbox_id,
        "Gangguan saat finalisasi",
        claim_token=claimed[0]["claim_token"],
        attempts=claimed[0]["attempts"],
        max_attempts=6,
    ) == "pending"

    with repo.tx() as conn:
        row = conn.execute(
            """
            SELECT status, result_ready, customer_id, reply_body
            FROM inbox
            WHERE id = %s
            """,
            (inbox_id,),
        ).fetchone()

    assert row["status"] == "pending"
    assert row["result_ready"] is True
    assert str(row["customer_id"]) == str(customer["id"])
    assert row["reply_body"] == "Hasil sudah disimpan"


def test_recover_dead_inbox_result_finalizes_saved_reply():
    customer = repo.register_customer("telegram", "user-recovery-201")
    repo.enqueue_inbox(
        channel="telegram",
        user_id="user-recovery-201",
        chat_id="chat-recovery-201",
        message_id="chat-recovery-201:201",
        body="Tes pemulihan",
    )

    claimed = repo.claim_inbox()
    inbox_id = claimed[0]["id"]

    assert repo.store_inbox_result(
        inbox_id,
        claim_token=claimed[0]["claim_token"],
        customer_id=customer["id"],
        reply_body="Balasan hasil pemulihan",
    )

    assert repo.fail_inbox(
        inbox_id,
        "Batas percobaan tercapai",
        claim_token=claimed[0]["claim_token"],
        attempts=6,
        max_attempts=6,
    ) == "dead"

    assert repo.recover_dead_inbox_result(inbox_id) is True
    assert repo.recover_dead_inbox_result(inbox_id) is False

    with repo.tx() as conn:
        inbox = conn.execute(
            "SELECT status FROM inbox WHERE id = %s",
            (inbox_id,),
        ).fetchone()
        replies = conn.execute(
            """
            SELECT count(*) AS total
            FROM outbox
            WHERE dedup_key = %s
            """,
            (
                "inbox-reply:telegram:"
                "chat-recovery-201:chat-recovery-201:201",
            ),
        ).fetchone()["total"]

    assert inbox["status"] == "processed"
    assert replies == 1


def test_recover_dead_inbox_without_saved_result_returns_false():
    repo.enqueue_inbox(
        channel="telegram",
        user_id="user-recovery-202",
        chat_id="chat-recovery-202",
        message_id="chat-recovery-202:202",
        body="Tes tanpa hasil",
    )

    claimed = repo.claim_inbox()
    inbox_id = claimed[0]["id"]

    assert repo.fail_inbox(
        inbox_id,
        "Kegagalan permanen",
        claim_token=claimed[0]["claim_token"],
        attempts=1,
        permanent=True,
    ) == "dead"

    assert repo.recover_dead_inbox_result(inbox_id) is False

    with repo.tx() as conn:
        inbox = conn.execute(
            "SELECT status, result_ready FROM inbox WHERE id = %s",
            (inbox_id,),
        ).fetchone()

    assert inbox["status"] == "dead"
    assert inbox["result_ready"] is False


def test_finalize_rolls_back_outbox_when_finalization_fails(monkeypatch):
    customer = repo.register_customer(
        "telegram",
        f"tg-rollback-{uuid.uuid4()}",
    )
    message_id = f"rollback-{uuid.uuid4()}"

    assert repo.enqueue_inbox(
        channel="telegram",
        user_id="user-rollback",
        chat_id="chat-rollback",
        message_id=message_id,
        body="Tes rollback",
    ) is True

    claimed = repo.claim_inbox(limit=10, lock_seconds=120)
    inbox = next(
        item for item in claimed
        if item["message_id"] == message_id
    )
    inbox_id = inbox["id"]
    claim_token = inbox["claim_token"]

    assert repo.store_inbox_result(
        inbox_id,
        claim_token=claim_token,
        customer_id=customer["id"],
        reply_body="Balasan untuk tes rollback",
    ) is True

    original_enqueue = repo._enqueue

    def enqueue_then_fail(conn, **kwargs):
        original_enqueue(conn, **kwargs)
        raise RuntimeError("Simulasi kegagalan setelah insert Outbox")

    monkeypatch.setattr(repo, "_enqueue", enqueue_then_fail)

    with pytest.raises(
        RuntimeError,
        match="Simulasi kegagalan setelah insert Outbox",
    ):
        repo.finalize_stored_inbox_result(
            inbox_id,
            claim_token=claim_token,
        )

    with repo.tx() as conn:
        inbox_row = conn.execute(
            """
            SELECT status, result_ready, customer_id, reply_body
            FROM inbox
            WHERE id = %s
            """,
            (inbox_id,),
        ).fetchone()

        outbox_count = conn.execute(
            """
            SELECT count(*) AS total
            FROM outbox
            WHERE dedup_key = %s
            """,
            (
                f"inbox-reply:telegram:chat-rollback:{message_id}",
            ),
        ).fetchone()["total"]

    assert inbox_row["status"] == "processing"
    assert inbox_row["result_ready"] is True
    assert inbox_row["customer_id"] == customer["id"]
    assert inbox_row["reply_body"] == "Balasan untuk tes rollback"
    assert outbox_count == 0

def test_recover_dead_inbox_rolls_back_claim_when_finalization_fails(monkeypatch):
    customer = repo.register_customer(
        "telegram",
        f"tg-recovery-rollback-{uuid.uuid4()}",
    )
    message_id = f"recovery-rollback-{uuid.uuid4()}"

    assert repo.enqueue_inbox(
        channel="telegram",
        user_id="user-recovery-rollback",
        chat_id="chat-recovery-rollback",
        message_id=message_id,
        body="Tes pemulihan yang gagal",
    ) is True

    claimed = repo.claim_inbox(limit=10, lock_seconds=120)
    inbox = next(
        item for item in claimed
        if item["message_id"] == message_id
    )
    inbox_id = inbox["id"]
    claim_token = inbox["claim_token"]

    assert repo.store_inbox_result(
        inbox_id,
        claim_token=claim_token,
        customer_id=customer["id"],
        reply_body="Balasan yang harus tetap tersimpan",
    ) is True

    assert repo.fail_inbox(
        inbox_id,
        "Simulasi batas percobaan",
        claim_token=claim_token,
        attempts=6,
        max_attempts=6,
    ) == "dead"

    original_enqueue = repo._enqueue

    def enqueue_then_fail(conn, **kwargs):
        original_enqueue(conn, **kwargs)
        raise RuntimeError("Simulasi kegagalan saat recovery")

    monkeypatch.setattr(repo, "_enqueue", enqueue_then_fail)

    with pytest.raises(
        RuntimeError,
        match="Simulasi kegagalan saat recovery",
    ):
        repo.recover_dead_inbox_result(inbox_id)

    with repo.tx() as conn:
        inbox_row = conn.execute(
            """
            SELECT status, result_ready, customer_id, reply_body
            FROM inbox
            WHERE id = %s
            """,
            (inbox_id,),
        ).fetchone()

        outbox_count = conn.execute(
            """
            SELECT count(*) AS total
            FROM outbox
            WHERE dedup_key = %s
            """,
            (
                f"inbox-reply:telegram:"
                f"chat-recovery-rollback:{message_id}",
            ),
        ).fetchone()["total"]

    assert inbox_row["status"] == "dead"
    assert inbox_row["result_ready"] is True
    assert str(inbox_row["customer_id"]) == str(customer["id"])
    assert inbox_row["reply_body"] == "Balasan yang harus tetap tersimpan"
    assert outbox_count == 0
