import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from app.channels.base import InboundMessage
from app.db import repo
from app.services import handler, inactivity

WIB = ZoneInfo("Asia/Jakarta")
NOON = datetime(2026, 10, 14, 12, 0, tzinfo=WIB)
NIGHT = datetime(2026, 10, 14, 3, 0, tzinfo=WIB)
DAILY_LAST_10_DAYS_AGO = list(range(10, 31))   # charging tiap hari, terakhir 10 hari lalu


def _customer(consent=True, state="done", channel="telegram"):
    user = f"u-{uuid.uuid4()}"
    c = repo.register_customer(channel, user)
    with repo.tx() as conn:
        conn.execute(
            "UPDATE customers SET registration_state = %s, consent_marketing = %s, consent_at = now(), name = 'Tes' "
            "WHERE id = %s",
            (state, consent, c["id"]),
        )
    return user, c["id"]


def _sessions(customer_id, days_ago):
    with repo.tx() as conn:
        station = conn.execute("SELECT id FROM stations WHERE code = 'sunset-road'").fetchone()["id"]
        for d in days_ago:
            conn.execute(
                """
                INSERT INTO charging_sessions
                  (external_id, customer_id, station_id, charger_id, kwh, amount_idr, started_at, ended_at)
                VALUES (%s, %s, %s, '01', 10, 1000,
                        now() - %s * interval '1 day', now() - %s * interval '1 day' + interval '30 minutes')
                """,
                (f"t-{uuid.uuid4()}", customer_id, station, d, d),
            )


def _msg(user, text):
    return InboundMessage(
        "sim", user, user, f"{user}:{uuid.uuid4()}", text, is_start=text.startswith("/start")
    )


def _alerted_ids():
    return {a["customer_id"] for a in repo.open_inactivity_alerts()}


# ---------- deteksi ----------

def test_detects_regular_customer_once():
    _, cid = _customer()
    _sessions(cid, DAILY_LAST_10_DAYS_AGO)
    assert inactivity.detect() == 1
    assert inactivity.detect() == 0          # job kedua tidak menggandakan alert
    assert _alerted_ids() == {cid}


def test_not_detected_before_min_days():
    _, cid = _customer()
    _sessions(cid, list(range(3, 24)))       # absen baru 3 hari
    assert inactivity.detect() == 0


def test_threshold_adapts_to_rhythm():
    _, weekly_ok = _customer()
    _sessions(weekly_ok, [10, 17, 24, 31, 38])      # biasa mingguan, absen 10 hari: wajar
    _, weekly_late = _customer()
    _sessions(weekly_late, [16, 23, 30, 37, 44])    # biasa mingguan, absen 16 hari: > 2x7
    _, daily = _customer()
    _sessions(daily, DAILY_LAST_10_DAYS_AGO)       # biasa harian, absen 10 hari: terlambat

    inactivity.detect()
    assert _alerted_ids() == {weekly_late, daily}


def test_needs_minimum_sessions():
    _, cid = _customer()
    _sessions(cid, [10, 11, 12])             # hanya 3 sesi: baseline belum bisa dipercaya
    assert inactivity.detect() == 0


def test_alert_resolves_when_customer_returns():
    _, cid = _customer()
    _sessions(cid, DAILY_LAST_10_DAYS_AGO)
    inactivity.detect()
    _sessions(cid, [0])
    assert repo.resolve_returned_alerts() == 1
    assert repo.open_inactivity_alerts() == []


# ---------- retensi ----------
# Retensi sekarang melewati Outbox: run_once() mengantrekan, outbox worker yang mengirim
# dan menandai retention_sent_at hanya setelah delivery berhasil.

def _drain_outbox(monkeypatch):
    """Jalankan outbox worker dengan pengiriman palsu; kembalikan daftar (channel, penerima, teks)."""
    from app.services import dispatcher
    sent = []
    monkeypatch.setattr(
        dispatcher, "send", lambda ch, to, text: sent.append((ch, to, text))
    )
    dispatcher.run_once()
    return sent


def _retention_rows():
    with repo.tx() as conn:
        return conn.execute("SELECT * FROM outbox WHERE kind = 'retention'").fetchall()


def test_retention_is_queued_then_sent_once(monkeypatch):
    user, cid = _customer(consent=True)
    _sessions(cid, DAILY_LAST_10_DAYS_AGO)

    assert inactivity.run_once(NOON) == {"resolved": 0, "detected": 1, "sent": 1}
    # Belum terkirim sebelum worker jalan, dan belum ditandai terkirim.
    assert repo.open_inactivity_alerts()[0]["retention_sent_at"] is None
    assert inactivity.run_once(NOON)["sent"] == 0   # dedup: tidak mengantre dua kali

    sent = _drain_outbox(monkeypatch)
    assert len(sent) == 1 and sent[0][0] == "telegram"
    assert sent[0][1] == user and "/stop" in sent[0][2]
    assert repo.open_inactivity_alerts()[0]["retention_sent_at"] is not None
    assert inactivity.run_once(NOON)["sent"] == 0


def test_retention_outbox_row_is_linked_to_alert():
    _, cid = _customer(consent=True)
    _sessions(cid, DAILY_LAST_10_DAYS_AGO)
    inactivity.run_once(NOON)

    (alert,) = repo.open_inactivity_alerts()
    (row,) = _retention_rows()
    assert row["retention_alert_id"] == alert["id"]
    assert row["dedup_key"] == f"retention:{alert['id']}"


def test_retention_skips_non_consented_but_keeps_alert(monkeypatch):
    _, cid = _customer(consent=False)
    _sessions(cid, DAILY_LAST_10_DAYS_AGO)

    assert inactivity.run_once(NOON)["sent"] == 0
    assert _drain_outbox(monkeypatch) == []   # tidak ada antrean promo
    assert _alerted_ids() == {cid}            # tetap tampil di dashboard untuk ditindak manusia


def test_retention_respects_quiet_hours(monkeypatch):
    _, cid = _customer()
    _sessions(cid, DAILY_LAST_10_DAYS_AGO)

    assert inactivity.run_once(NIGHT)["sent"] == 0
    assert _drain_outbox(monkeypatch) == []
    assert inactivity.run_once(NOON)["sent"] == 1   # alert yang tertunda diantrekan di jam wajar
    assert len(_drain_outbox(monkeypatch)) == 1


def test_retention_cooldown_between_alerts(monkeypatch):
    _, cid = _customer()
    _sessions(cid, DAILY_LAST_10_DAYS_AGO)
    inactivity.run_once(NOON)
    _drain_outbox(monkeypatch)               # delivery sukses -> retention_sent_at terisi
    with repo.tx() as conn:                  # simulasi: alert ditutup, customer masih absen, alert baru muncul
        conn.execute("UPDATE inactivity_alerts SET status = 'resolved'")

    result = inactivity.run_once(NOON)
    assert result["detected"] == 1 and result["sent"] == 0
    assert len(_drain_outbox(monkeypatch)) == 0


def test_failed_retention_delivery_is_retried_not_marked_sent(monkeypatch):
    from app.services import dispatcher

    def boom(*a):
        raise dispatcher.DeliveryError("telegram down")

    monkeypatch.setattr(dispatcher, "send", boom)
    _, cid = _customer()
    _sessions(cid, DAILY_LAST_10_DAYS_AGO)

    assert inactivity.run_once(NOON)["sent"] == 1
    dispatcher.run_once()
    # Delivery gagal: retention TIDAK ditandai terkirim dan baris outbox menunggu retry.
    assert repo.open_inactivity_alerts()[0]["retention_sent_at"] is None
    (row,) = _retention_rows()
    assert row["status"] == "pending" and row["attempts"] == 1


# ---------- /stop dan /subscribe ----------

def test_stop_withdraws_consent_and_is_logged():
    user, cid = _customer(consent=True, channel="sim")
    assert "tidak akan menerima" in handler.handle_inbound(_msg(user, "/stop"))
    assert repo.get_customer_by_identity("sim", user)["consent_marketing"] is False
    handler.handle_inbound(_msg(user, "/stop"))
    assert repo.consent_history(cid) == [{"granted": False, "source": "command"}]   # idempotent


def test_stop_works_mid_registration():
    user = f"u-{uuid.uuid4()}"
    handler.handle_inbound(_msg(user, "/start"))
    reply = handler.handle_inbound(_msg(user, "/stop"))
    assert "Siapa nama Anda?" in reply
    assert repo.get_customer_by_identity("sim", user)["consent_marketing"] is False
    assert repo.get_customer_by_identity("sim", user)["registration_state"] == "ask_name"


def test_subscribe_regrants_only_when_registered():
    user, cid = _customer(consent=False, state="ask_name", channel="sim")
    assert "pendaftaran" in handler.handle_inbound(_msg(user, "/subscribe"))
    assert repo.get_customer_by_identity("sim", user)["consent_marketing"] is False

    with repo.tx() as conn:
        conn.execute("UPDATE customers SET registration_state = 'done' WHERE id = %s", (cid,))
    handler.handle_inbound(_msg(user, "/subscribe"))
    assert repo.get_customer_by_identity("sim", user)["consent_marketing"] is True
    assert repo.consent_history(cid) == [{"granted": True, "source": "command"}]