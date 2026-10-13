import uuid

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
