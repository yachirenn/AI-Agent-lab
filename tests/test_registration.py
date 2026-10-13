import uuid

from app.channels.base import InboundMessage
from app.db import repo
from app.services.handler import handle_inbound


def _msg(user: str, text: str, payload: str | None = None, message_id: str | None = None):
    return InboundMessage(
        channel="sim",
        user_id=user,
        chat_id=user,
        message_id=message_id or f"{user}:{uuid.uuid4()}",
        text=text,
        is_start=text.startswith("/start"),
        start_payload=payload,
    )


def test_full_registration_flow():
    user = f"u-{uuid.uuid4()}"
    handle_inbound(_msg(user, "/start sunset-road", payload="sunset-road"))
    for answer in ["Made", "BYD M6", "1", "Jimbaran", "Jimbaran - Airport - Seminyak"]:
        assert handle_inbound(_msg(user, answer))
    reply = handle_inbound(_msg(user, "ya"))

    assert "ENV-" in reply
    c = repo.get_customer_by_identity("sim", user)
    assert c["registration_state"] == "done"
    assert c["name"] == "Made"
    assert c["driver_type"] == "ride_hailing"
    assert c["consent_marketing"] is True and c["consent_at"] is not None
    assert c["registered_station_id"] is not None
    assert [v["model"] for v in repo.list_vehicles(c["id"])] == ["BYD M6"]


def test_duplicate_delivery_is_ignored():
    user = f"u-{uuid.uuid4()}"
    first = _msg(user, "/start")
    assert handle_inbound(first) is not None
    assert handle_inbound(first) is None   # message_id sama = retry platform


def test_invalid_answer_keeps_state_and_reprompts():
    user = f"u-{uuid.uuid4()}"
    for text in ["/start", "Made", "BYD M6"]:
        handle_inbound(_msg(user, text))
    reply = handle_inbound(_msg(user, "banana"))

    assert "1. Ride-hailing" in reply
    assert repo.get_customer_by_identity("sim", user)["registration_state"] == "ask_driver_type"