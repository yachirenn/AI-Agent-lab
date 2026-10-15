import os

import pytest
from dotenv import load_dotenv

load_dotenv()
# Harus dijalankan sebelum app.db.repo diimpor, supaya pool memakai DB tes.
os.environ["DATABASE_URL"] = os.environ["DATABASE_URL"].rsplit("/", 1)[0] + "/enerva_test"
os.environ["PREFERENCES_LEARNING"] = "off"

from app.db import repo  # noqa: E402


@pytest.fixture(autouse=True)
def clean_db():
    assert os.environ["DATABASE_URL"].endswith("_test"), "menolak TRUNCATE di database non-tes"
    yield
    with repo.tx() as conn:
        conn.execute(
            "TRUNCATE inactivity_alerts, consent_events, cs_tickets, conversations, points_ledger, charging_sessions, vehicles, outbox,"
            "customer_identities, customers, knowledge_base RESTART IDENTITY CASCADE"
        )