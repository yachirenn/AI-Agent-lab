from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.main import app
from app.db import repo

client = TestClient(app)


def test_health_liveness():
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"ok": True}


def test_health_ready_healthy():
    res = client.get("/health/ready")
    assert res.status_code == 200, res.json()
    data = res.json()
    assert data["ok"] is True
    assert data["checks"]["database"]["ok"] is True
    assert data["checks"]["tables"]["ok"] is True
    assert data["checks"]["tables"]["missing"] == []
    assert data["checks"]["migrations"]["ok"] is True
    assert data["checks"]["inbox"]["ok"] is True
    assert data["checks"]["outbox"]["ok"] is True


def test_health_ready_fails_when_database_unreachable(monkeypatch):
    def broken_snapshot(*args, **kwargs):
        raise RuntimeError("koneksi database terputus")

    monkeypatch.setattr(repo, "readiness_snapshot", broken_snapshot)
    res = client.get("/health/ready")
    assert res.status_code == 503
    data = res.json()
    assert data["ok"] is False
    assert data["checks"]["database"]["ok"] is False


def test_health_ready_fails_when_migration_outdated(monkeypatch):
    # Simulasi migrasi yang diharapkan belum terpasang
    monkeypatch.setenv("EXPECTED_MIGRATION_VERSION", "999_future_migration.sql")
    res = client.get("/health/ready")
    assert res.status_code == 503
    data = res.json()
    assert data["ok"] is False
    assert data["checks"]["migrations"]["ok"] is False
    assert data["checks"]["migrations"]["expected"] == "999_future_migration.sql"


def test_health_ready_fails_when_required_table_missing(monkeypatch):
    from app.api import main as api_main

    monkeypatch.setattr(
        api_main, "READINESS_REQUIRED_TABLES", ("customers", "non_existent_table_xyz")
    )
    res = client.get("/health/ready")
    assert res.status_code == 503
    data = res.json()
    assert data["ok"] is False
    assert data["checks"]["tables"]["ok"] is False
    assert "non_existent_table_xyz" in data["checks"]["tables"]["missing"]


def test_health_ready_fails_when_inbox_backlog_exceeded(monkeypatch):
    # Set limit backlog ke 0, lalu tambahkan 1 pesan ke inbox
    monkeypatch.setattr("app.api.main.READINESS_MAX_INBOX_BACKLOG", 0)
    repo.enqueue_inbox(
        channel="telegram",
        user_id="user-probe",
        chat_id="chat-probe",
        message_id="msg-probe-1",
        body="test probe",
    )
    res = client.get("/health/ready")
    assert res.status_code == 503
    data = res.json()
    assert data["ok"] is False
    assert data["checks"]["inbox"]["ok"] is False
    assert data["checks"]["inbox"]["total"] >= 1
