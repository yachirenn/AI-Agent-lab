import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from app.api.main import app
from app.db import repo
from app.services import loyalty

client = TestClient(app)


def _customer():
    return repo.register_customer("sim", f"u-{uuid.uuid4()}")


def _payload(code=None, **override):
    end = datetime.now(timezone.utc)
    base = {
        "external_id": f"cms-{uuid.uuid4()}",
        "station_code": "sunset-road",
        "charger_id": "04",
        "customer_code": code,
        "kwh": "42.30",
        "amount_idr": 95000,
        "started_at": (end - timedelta(minutes=38)).isoformat(),
        "ended_at": end.isoformat(),
    }
    return {**base, **override}


def _post(payload, secret=None):
    return client.post(
        "/webhook/cms", json=payload, headers={"X-CMS-Secret": secret or os.environ["CMS_WEBHOOK_SECRET"]}
    )


def _count_sessions():
    with repo.tx() as conn:
        return conn.execute("SELECT count(*) AS n FROM charging_sessions").fetchone()["n"]


def test_points_formula_uses_exact_decimal(monkeypatch):
    monkeypatch.setenv("POINTS_PER_KWH", "10")
    assert loyalty.points_for_kwh(Decimal("42.3")) == 423
    assert loyalty.points_for_kwh(Decimal("0.09")) == 0       # dibulatkan ke bawah


def test_charging_awards_points():
    c = _customer()
    r = _post(_payload(c["customer_code"]))
    assert r.status_code == 200
    assert r.json() == {"status": "created", "points_awarded": 423}
    assert repo.get_balance(c["id"]) == 423


def test_duplicate_event_does_not_double_points():
    c = _customer()
    payload = _payload(c["customer_code"])
    assert _post(payload).json()["status"] == "created"
    assert _post(payload).json()["status"] == "duplicate"
    assert repo.get_balance(c["id"]) == 423
    assert _count_sessions() == 1


def test_concurrent_duplicates_create_exactly_one():
    c = _customer()
    kwargs = dict(
        external_id="cms-race", station_code="sunset-road", charger_id="04",
        customer_code=c["customer_code"], kwh=Decimal("10.00"), amount_idr=1000,
        started_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        ended_at=datetime.now(timezone.utc), points=100,
    )
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: repo.ingest_charging_session(**kwargs), range(8)))
    assert [r["status"] for r in results].count("created") == 1
    assert repo.get_balance(c["id"]) == 100


def test_wrong_secret_is_rejected():
    assert _post(_payload(), secret="salah").status_code == 403


def test_unknown_station_is_422():
    assert _post(_payload(station_code="tidak-ada")).status_code == 422


def test_invalid_payload_is_422_and_stores_nothing():
    assert _post(_payload(kwh="-5")).status_code == 422
    assert _post(_payload(started_at="2026-10-13T10:00:00")).status_code == 422   # tanpa timezone
    assert _count_sessions() == 0


def test_unmatched_customer_stores_session_without_points():
    r = _post(_payload("ENV-999999"))
    assert r.json() == {"status": "created", "points_awarded": 0}
    assert _count_sessions() == 1