from scripts import inbox_worker


def make_item(**overrides):
    item = {
        "id": 101,
        "claim_token": "test-claim-token",
        "channel": "telegram",
        "user_id": "user-123",
        "chat_id": "chat-123",
        "message_id": "chat-123:77",
        "body": "Halo, saya ingin bertanya",
        "is_start": False,
        "start_payload": None,
        "attempts": 1,
        "result_ready": False,
        "customer_id": None,
        "reply_body": None,
    }
    item.update(overrides)
    return item


def test_process_once_finalizes_existing_result(monkeypatch):
    item = make_item(result_ready=True)
    calls = []

    monkeypatch.setattr(
        inbox_worker.repo, "claim_inbox", lambda limit: [item]
    )
    monkeypatch.setattr(
        inbox_worker.repo,
        "finalize_stored_inbox_result",
        lambda inbox_id, *, claim_token: calls.append((inbox_id, claim_token)) or True,
    )
    monkeypatch.setattr(
        inbox_worker, "handle_inbound",
        lambda msg: (_ for _ in ()).throw(
            AssertionError("Handler tidak boleh dijalankan ulang")
        ),
    )

    assert inbox_worker.process_once() == 1
    assert calls == [(101, item["claim_token"])]


def test_process_once_handles_new_message(monkeypatch):
    item = make_item()
    calls = []
    customer = {"id": "customer-123"}

    monkeypatch.setattr(
        inbox_worker.repo, "claim_inbox", lambda limit: [item]
    )
    monkeypatch.setattr(
        inbox_worker.repo,
        "message_id_by_channel",
        lambda channel, message_id: None,
    )
    monkeypatch.setattr(
        inbox_worker, "handle_inbound",
        lambda msg: calls.append(("handle", msg.text)) or "Halo juga!",
    )
    monkeypatch.setattr(
        inbox_worker.repo,
        "get_customer_by_identity",
        lambda channel, user_id: customer,
    )
    monkeypatch.setattr(
        inbox_worker.repo,
        "store_inbox_result",
        lambda inbox_id, **kwargs: (
            calls.append(("store", inbox_id, kwargs)) or True
        ),
    )
    monkeypatch.setattr(
        inbox_worker.repo,
        "finalize_stored_inbox_result",
        lambda inbox_id, *, claim_token: calls.append(("finalize", inbox_id, claim_token)) or True,
    )

    assert inbox_worker.process_once() == 1
    assert ("handle", item["body"]) in calls
    assert (
        "store",
        101,
        {
            "claim_token": item["claim_token"],
            "customer_id": "customer-123",
            "reply_body": "Halo juga!",
        },
    ) in calls
    assert ("finalize", 101, item["claim_token"]) in calls


def test_process_once_dead_letters_message_with_missing_result(
    monkeypatch,
):
    item = make_item()
    calls = []

    monkeypatch.setattr(
        inbox_worker.repo, "claim_inbox", lambda limit: [item]
    )
    monkeypatch.setattr(
        inbox_worker.repo,
        "message_id_by_channel",
        lambda channel, message_id: "existing-conversation-id",
    )
    monkeypatch.setattr(
        inbox_worker.repo,
        "fail_inbox",
        lambda inbox_id, error, **kwargs: calls.append(
            (inbox_id, error, kwargs)
        ) or "dead",
    )
    monkeypatch.setattr(
        inbox_worker, "handle_inbound",
        lambda msg: (_ for _ in ()).throw(
            AssertionError("Handler tidak boleh dijalankan ulang")
        ),
    )

    assert inbox_worker.process_once() == 1
    assert len(calls) == 1
    assert calls[0][0] == 101
    assert calls[0][2]["permanent"] is True


def test_process_once_schedules_retry_after_handler_error(monkeypatch):
    item = make_item()
    calls = []

    monkeypatch.setattr(
        inbox_worker.repo, "claim_inbox", lambda limit: [item]
    )
    monkeypatch.setattr(
        inbox_worker.repo,
        "message_id_by_channel",
        lambda channel, message_id: None,
    )
    monkeypatch.setattr(
        inbox_worker, "handle_inbound",
        lambda msg: (_ for _ in ()).throw(
            RuntimeError("Simulasi handler gagal")
        ),
    )
    monkeypatch.setattr(
        inbox_worker.repo,
        "fail_inbox",
        lambda inbox_id, error, **kwargs: calls.append(
            (inbox_id, error, kwargs)
        ) or "retry",
    )

    assert inbox_worker.process_once() == 1
    assert len(calls) == 1
    assert calls[0][0] == 101
    assert "Simulasi handler gagal" in calls[0][1]
    assert calls[0][2]["attempts"] == 1


def test_process_once_retries_when_finalization_fails(monkeypatch):
    item = make_item()
    calls = []

    monkeypatch.setattr(
        inbox_worker.repo, "claim_inbox", lambda limit: [item]
    )
    monkeypatch.setattr(
        inbox_worker.repo,
        "message_id_by_channel",
        lambda channel, message_id: None,
    )
    monkeypatch.setattr(
        inbox_worker,
        "handle_inbound",
        lambda msg: calls.append("handler") or "Balasan tersimpan",
    )
    monkeypatch.setattr(
        inbox_worker.repo,
        "get_customer_by_identity",
        lambda channel, user_id: {"id": "customer-123"},
    )
    monkeypatch.setattr(
        inbox_worker.repo,
        "store_inbox_result",
        lambda inbox_id, **kwargs: True,
    )
    monkeypatch.setattr(
        inbox_worker.repo,
        "finalize_stored_inbox_result",
        lambda inbox_id, *, claim_token: False,
    )
    monkeypatch.setattr(
        inbox_worker.repo,
        "fail_inbox",
        lambda inbox_id, error, **kwargs: calls.append(
            ("fail", inbox_id, error, kwargs)
        ) or "retry",
    )

    assert inbox_worker.process_once() == 1
    assert calls.count("handler") == 1
    assert any(
        isinstance(call, tuple) and call[0] == "fail"
        for call in calls
    )
