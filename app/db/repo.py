"""Semua akses SQL lewat modul ini. Layer lain (agent, API) tidak boleh menulis SQL."""
from __future__ import annotations

import json
import os
import random

from contextlib import contextmanager
from typing import Any, Callable, Iterator

from dotenv import load_dotenv
from psycopg import Connection, sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

load_dotenv()

_pool: ConnectionPool | None = None


def _enqueue(
    conn: Connection, *, kind: str, channel: str, recipient: str, body: str,
    customer_id: Any = None, ticket_id: int | None = None, dedup_key: str | None = None,
) -> bool:
    cur = conn.execute(
        """
        INSERT INTO outbox (kind, channel, recipient, customer_id, ticket_id, body, dedup_key)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (dedup_key) DO NOTHING
        """,
        (kind, channel, recipient, customer_id, ticket_id, body, dedup_key),
    )
    return cur.rowcount == 1


def enqueue_message(**kwargs: Any) -> bool:
    """True jika baris baru dibuat; False jika dedup_key sudah ada."""
    with tx() as conn:
        return _enqueue(conn, **kwargs)


def claim_outbox(limit: int, lock_seconds: int) -> list[dict[str, Any]]:
    """Aman dijalankan beberapa worker: baris terkunci dilewati (SKIP LOCKED).
    Baris 'sending' yang lock-nya kedaluwarsa (worker mati) diklaim ulang."""
    with tx() as conn:
        return conn.execute(
            """
            UPDATE outbox SET status = 'sending', attempts = attempts + 1,
                   locked_until = now() + %s * interval '1 second'
            WHERE id IN (
              SELECT id FROM outbox
              WHERE (status = 'pending' AND next_attempt_at <= now())
                 OR (status = 'sending' AND locked_until < now())
              ORDER BY (kind = 'staff_alert') DESC, id
              LIMIT %s
              FOR UPDATE SKIP LOCKED)
            RETURNING id, kind, channel, recipient, customer_id, ticket_id, body, attempts
            """,
            (lock_seconds, limit),
        ).fetchall()


def complete_outbox(outbox_id: int) -> None:
    with tx() as conn:
        row = conn.execute(
            "UPDATE outbox SET status = 'sent', sent_at = now(), locked_until = NULL WHERE id = %s RETURNING ticket_id",
            (outbox_id,),
        ).fetchone()
        if row and row["ticket_id"]:   # bukti bahwa staf benar-benar diberi tahu
            conn.execute("UPDATE cs_tickets SET notified_at = now() WHERE id = %s", (row["ticket_id"],))


def fail_outbox(outbox_id: int, error: str, *, permanent: bool, attempts: int, max_attempts: int) -> str:
    status = "dead" if permanent or attempts >= max_attempts else "pending"
    delay = int(min(30 * 2 ** max(attempts - 1, 0), 1800) * random.uniform(0.8, 1.2))   # 30s, 60s, 120s ... maks 30 menit
    with tx() as conn:
        conn.execute(
            "UPDATE outbox SET status = %s, last_error = %s, locked_until = NULL, "
            "next_attempt_at = now() + %s * interval '1 second' WHERE id = %s",
            (status, error[:200], delay, outbox_id),
        )
    return status


def unalerted_urgent_tickets(min_age_seconds: int) -> list[dict[str, Any]]:
    """Tiket urgent terbuka yang belum diberitahukan dan belum punya baris outbox."""
    with tx() as conn:
        return conn.execute(
            """
            SELECT t.id, t.category, t.summary, c.id AS customer_id, c.customer_code, c.name
            FROM cs_tickets t JOIN customers c ON c.id = t.customer_id
            WHERE t.level = 3 AND t.status = 'open' AND t.notified_at IS NULL
              AND t.created_at < now() - %s * interval '1 second'
              AND NOT EXISTS (SELECT 1 FROM outbox o WHERE o.dedup_key = 'ticket:' || t.id)
            """,
            (min_age_seconds,),
        ).fetchall()


def outbox_stats() -> list[dict[str, Any]]:
    with tx() as conn:
        return conn.execute(
            """
            SELECT status, kind, count(*)::int AS n,
                   COALESCE(max(extract(epoch FROM now() - created_at))
                            FILTER (WHERE status IN ('pending', 'sending')), 0)::int AS oldest_s
            FROM outbox GROUP BY 1, 2 ORDER BY 1, 2
            """
        ).fetchall()


def dead_outbox(limit: int = 50) -> list[dict[str, Any]]:
    """Tanpa recipient dan body: itu data pribadi."""
    with tx() as conn:
        return conn.execute(
            "SELECT id, kind, channel, attempts, last_error, created_at FROM outbox "
            "WHERE status = 'dead' ORDER BY id DESC LIMIT %s",
            (limit,),
        ).fetchall()


def count_inbound(customer_id: Any) -> int:
    with tx() as conn:
        return conn.execute(
            "SELECT count(*)::int AS n FROM conversations WHERE customer_id = %s AND direction = 'in'",
            (customer_id,),
        ).fetchone()["n"]


def ping() -> None:
    with tx() as conn:
        conn.execute("SELECT 1")

def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            os.environ["DATABASE_URL"],
            min_size=1,
            max_size=5,
            kwargs={"row_factory": dict_row},
            open=True,
        )
    return _pool


@contextmanager
def tx() -> Iterator[Connection]:
    """Satu transaksi: commit jika sukses, rollback jika ada exception."""
    with get_pool().connection() as conn:
        yield conn


def close_pool() -> None:
    """Tutup pool koneksi database secara graceful saat aplikasi shutdown."""
    global _pool
    if _pool is not None:
        try:
            _pool.close()
        finally:
            _pool = None


def list_stations() -> list[dict[str, Any]]:
    """Daftar semua stasiun pengisian Enerva."""
    with tx() as conn:
        return conn.execute("SELECT id, code, name, area FROM stations ORDER BY name").fetchall()


def get_station_by_code(code: str) -> dict[str, Any] | None:
    """Ambil data stasiun berdasarkan kode unik stasiun."""
    with tx() as conn:
        return conn.execute(
            "SELECT id, code, name, area FROM stations WHERE code = %s",
            (code,),
        ).fetchone()


def find_stations_by_area(area: str) -> list[dict[str, Any]]:
    """Cari stasiun berdasarkan area atau nama stasiun (pencarian leksikal fleksibel)."""
    with tx() as conn:
        return conn.execute(
            "SELECT id, code, name, area FROM stations WHERE area ILIKE %s OR name ILIKE %s ORDER BY name",
            (f"%{area}%", f"%{area}%"),
        ).fetchall()


def upsert_station(code: str, name: str, area: str) -> dict[str, Any]:
    """Tambah atau perbarui stasiun pengisian kendaraan listrik secara real-time."""
    with tx() as conn:
        return conn.execute(
            """
            INSERT INTO stations (code, name, area)
            VALUES (%s, %s, %s)
            ON CONFLICT (code) DO UPDATE
            SET name = EXCLUDED.name, area = EXCLUDED.area
            RETURNING id, code, name, area
            """,
            (code, name, area),
        ).fetchone()


def station_performance(station_code: str, days: int = 30) -> dict[str, Any] | None:
    """Metrik analitik stasiun pengisian untuk staf: jumlah sesi, total kWh, pendapatan, dan jumlah pelanggan unik."""
    with tx() as conn:
        st = conn.execute("SELECT id, code, name, area FROM stations WHERE code = %s", (station_code,)).fetchone()
        if not st:
            return None
        stats = conn.execute(
            """
            SELECT count(*)::int AS total_sessions,
                   COALESCE(sum(kwh), 0)::float AS total_kwh,
                   COALESCE(sum(amount_idr), 0)::int AS total_revenue_idr,
                   count(DISTINCT customer_id)::int AS unique_customers
            FROM charging_sessions
            WHERE station_id = %s AND started_at > now() - %s * interval '1 day'
            """,
            (st["id"], days),
        ).fetchone()
        return {
            "code": st["code"],
            "name": st["name"],
            "area": st["area"],
            "period_days": days,
            "total_sessions": stats["total_sessions"],
            "total_kwh": round(stats["total_kwh"], 2),
            "total_revenue_idr": stats["total_revenue_idr"],
            "unique_customers": stats["unique_customers"],
        }




def _find_by_identity(conn: Connection, channel: str, external_id: str) -> dict[str, Any] | None:
    return conn.execute(
        """
        SELECT c.* FROM customers c
        JOIN customer_identities i ON i.customer_id = c.id
        WHERE i.channel = %s AND i.external_id = %s
        """,
        (channel, external_id),
    ).fetchone()


def register_customer(channel: str, external_id: str, name: str | None = None, station_code: str | None = None) -> dict[str, Any]:
    """Idempotent: identitas yang sama selalu mengembalikan customer yang sama,
    walaupun dua pesan pertama masuk bersamaan."""
    with tx() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{channel}:{external_id}",))
        existing = _find_by_identity(conn, channel, external_id)
        if existing:
            return existing
        customer = conn.execute(
            """
            INSERT INTO customers (name, registered_station_id)
            VALUES (%s, (SELECT id FROM stations WHERE code = %s))
            RETURNING *
            """,
            (name, station_code),
        ).fetchone()
        conn.execute(
            "INSERT INTO customer_identities (customer_id, channel, external_id) VALUES (%s, %s, %s)",
            (customer["id"], channel, external_id),
        )
        return customer


def award_points(customer_id: Any, delta: int, reason: str, ref_id: str) -> bool:
    """True jika poin baru dicatat, False jika (customer, reason, ref_id) sudah pernah ada."""
    with tx() as conn:
        cur = conn.execute(
            """
            INSERT INTO points_ledger (customer_id, delta, reason, ref_id)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (customer_id, reason, ref_id) DO NOTHING
            """,
            (customer_id, delta, reason, ref_id),
        )
        return cur.rowcount == 1


def get_balance(customer_id: Any) -> int:
    with tx() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(delta), 0)::int AS balance FROM points_ledger WHERE customer_id = %s",
            (customer_id,),
        ).fetchone()
        return row["balance"]
    
# Kolom yang boleh diubah lewat advance_registration. Whitelist ini yang membuat
# nama kolom dinamis di bawah aman dari SQL injection.
_CUSTOMER_FIELDS = frozenset({"name", "driver_type", "home_area", "main_route", "consent_marketing"})


def get_customer_by_identity(channel: str, external_id: str) -> dict[str, Any] | None:
    with tx() as conn:
        return _find_by_identity(conn, channel, external_id)


def list_vehicles(customer_id: Any) -> list[dict[str, Any]]:
    with tx() as conn:
        return conn.execute(
            "SELECT model, plate_no FROM vehicles WHERE customer_id = %s ORDER BY model",
            (customer_id,),
        ).fetchall()


def record_message(
    customer_id: Any,
    channel: str,
    direction: str,
    body: str,
    channel_message_id: str | None = None,
) -> bool:
    """False jika (channel, channel_message_id) sudah ada, artinya retry dari platform."""
    with tx() as conn:
        cur = conn.execute(
            """
            INSERT INTO conversations (customer_id, channel, channel_message_id, direction, body)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (customer_id, channel, channel_message_id, direction, body),
        )
        return cur.rowcount == 1


def advance_registration(
    customer_id: Any,
    from_state: str,
    to_state: str,
    fields: dict[str, Any] | None = None,
    vehicle_model: str | None = None,
) -> bool:
    """Compare-and-set: pindah state hanya jika state saat ini masih `from_state`.
    False berarti ada pesan lain yang sudah menggeser state lebih dulu."""
    fields = fields or {}
    unknown = set(fields) - _CUSTOMER_FIELDS
    if unknown:
        raise ValueError(f"kolom tidak diizinkan: {unknown}")

    assignments = [sql.SQL("{} = %s").format(sql.Identifier(col)) for col in fields]
    params: list[Any] = list(fields.values())
    assignments.append(sql.SQL("registration_state = %s"))
    params.append(to_state)
    if "consent_marketing" in fields:
        assignments.append(sql.SQL("consent_at = now()"))  # waktu keputusan, bukti persetujuan

    query = sql.SQL("UPDATE customers SET {} WHERE id = %s AND registration_state = %s").format(
        sql.SQL(", ").join(assignments)
    )
    with tx() as conn:
        cur = conn.execute(query, (*params, customer_id, from_state))
        if cur.rowcount != 1:
            return False
        if "consent_marketing" in fields:
            conn.execute(
                "INSERT INTO consent_events (customer_id, granted, source) VALUES (%s, %s, 'registration')",
                (customer_id, fields["consent_marketing"]),
            )
        if vehicle_model:
            conn.execute(
                "INSERT INTO vehicles (customer_id, model) VALUES (%s, %s)",
                (customer_id, vehicle_model),
            )
        return True
    
class UnknownStation(LookupError):
    pass


def set_marketing_consent(customer_id: Any, granted: bool, source: str) -> bool:
    """True jika nilainya benar-benar berubah. Memanggil /stop dua kali tidak menulis dua event."""
    with tx() as conn:
        cur = conn.execute(
            """
            UPDATE customers SET consent_marketing = %s, consent_at = now()
            WHERE id = %s AND consent_marketing IS DISTINCT FROM %s
            """,
            (granted, customer_id, granted),
        )
        if cur.rowcount != 1:
            return False
        conn.execute(
            "INSERT INTO consent_events (customer_id, granted, source) VALUES (%s, %s, %s)",
            (customer_id, granted, source),
        )
        return True


def consent_history(customer_id: Any) -> list[dict[str, Any]]:
    with tx() as conn:
        return conn.execute(
            "SELECT granted, source FROM consent_events WHERE customer_id = %s ORDER BY id",
            (customer_id,),
        ).fetchall()


def detect_inactive(*, min_sessions: int, factor: float, min_days: int, lookback_days: int) -> int:
    """Buat alert untuk customer yang absen lebih lama dari baseline-nya. Kembalikan jumlah alert baru."""
    with tx() as conn:
        cur = conn.execute(
            """
            WITH gaps AS (
              SELECT customer_id, started_at,
                     extract(epoch FROM started_at
                             - lag(started_at) OVER (PARTITION BY customer_id ORDER BY started_at)) AS gap_s
              FROM charging_sessions
              WHERE customer_id IS NOT NULL
                AND started_at > now() - %(lookback)s * interval '1 day'
            ), agg AS (
              SELECT customer_id, max(started_at) AS last_visit,
                     percentile_cont(0.5) WITHIN GROUP (ORDER BY gap_s) AS median_gap_s
              FROM gaps
              GROUP BY customer_id
              HAVING count(*) >= %(min_sessions)s
            )
            INSERT INTO inactivity_alerts (customer_id, last_visit_at, median_gap_hours)
            SELECT customer_id, last_visit, round((median_gap_s / 3600)::numeric, 1)
            FROM agg
            WHERE extract(epoch FROM now() - last_visit)
                  > GREATEST(median_gap_s * %(factor)s::float8, %(min_days)s * 86400)
            ON CONFLICT (customer_id) WHERE status = 'open' DO NOTHING
            """,
            {"lookback": lookback_days, "min_sessions": min_sessions, "factor": factor, "min_days": min_days},
        )
        return cur.rowcount


def resolve_returned_alerts() -> int:
    """Customer yang punya sesi baru setelah kunjungan terakhir yang tercatat di alert."""
    with tx() as conn:
        cur = conn.execute(
            """
            UPDATE inactivity_alerts a SET status = 'resolved', resolved_at = now()
            WHERE a.status = 'open' AND EXISTS (
              SELECT 1 FROM charging_sessions cs
              WHERE cs.customer_id = a.customer_id AND cs.started_at > a.last_visit_at)
            """
        )
        return cur.rowcount


def open_inactivity_alerts() -> list[dict[str, Any]]:
    with tx() as conn:
        return conn.execute(
            """
            SELECT a.id, a.customer_id, c.customer_code, c.name, c.consent_marketing,
                   a.last_visit_at, a.median_gap_hours, a.retention_sent_at, a.detected_at
            FROM inactivity_alerts a JOIN customers c ON c.id = a.customer_id
            WHERE a.status = 'open' ORDER BY a.detected_at, a.id
            """
        ).fetchall()


def pending_retention_alerts() -> list[dict[str, Any]]:
    with tx() as conn:
        return conn.execute(
            """
            SELECT a.id, a.customer_id FROM inactivity_alerts a
            JOIN customers c ON c.id = a.customer_id
            WHERE a.status = 'open' AND a.retention_sent_at IS NULL
              AND c.consent_marketing AND c.registration_state = 'done'
            ORDER BY a.id
            """
        ).fetchall()


def claim_retention(alert_id: int, cooldown_days: int) -> dict[str, Any] | None:
    """Klaim atomik: consent, status, dan cooldown dicek dalam SATU statement.
    None berarti tidak boleh kirim (consent dicabut, sudah dikirim, atau masih cooldown)."""
    with tx() as conn:
        return conn.execute(
            """
            UPDATE inactivity_alerts a SET retention_sent_at = now()
            FROM customers c
            WHERE a.id = %s AND a.status = 'open' AND a.retention_sent_at IS NULL
              AND c.id = a.customer_id AND c.consent_marketing AND c.registration_state = 'done'
              AND NOT EXISTS (
                SELECT 1 FROM inactivity_alerts p
                WHERE p.customer_id = a.customer_id
                  AND p.retention_sent_at > now() - %s * interval '1 day')
            RETURNING c.id AS customer_id, c.name
            """,
            (alert_id, cooldown_days),
        ).fetchone()


def release_retention(alert_id: int) -> None:
    with tx() as conn:
        conn.execute("UPDATE inactivity_alerts SET retention_sent_at = NULL WHERE id = %s", (alert_id,))

def get_identity(customer_id: Any, channel: str) -> str | None:
    with tx() as conn:
        row = conn.execute(
            "SELECT external_id FROM customer_identities WHERE customer_id = %s AND channel = %s",
            (customer_id, channel),
        ).fetchone()
        return row["external_id"] if row else None


def ingest_charging_session(
    *,
    external_id: str,
    station_code: str,
    charger_id: str,
    customer_code: str | None,
    kwh: Any,
    amount_idr: int,
    started_at: Any,
    ended_at: Any,
    points: int,
    notify: Callable[[int, int], str] | None = None
) -> dict[str, Any]:
    """Atomik: sesi + poin masuk bersama, atau tidak sama sekali.
    Kembalikan status 'created' atau 'duplicate'."""
    with tx() as conn:
        station = conn.execute("SELECT id FROM stations WHERE code = %s", (station_code,)).fetchone()
        if station is None:
            raise UnknownStation(station_code)

        customer_id = None
        if customer_code:
            row = conn.execute(
                "SELECT id FROM customers WHERE customer_code = %s", (customer_code,)
            ).fetchone()
            customer_id = row["id"] if row else None   # tidak cocok: tetap simpan, tanpa poin

        session = conn.execute(
            """
            INSERT INTO charging_sessions
              (external_id, customer_id, station_id, charger_id, kwh, amount_idr, started_at, ended_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (external_id) DO NOTHING
            RETURNING id
            """,
            (external_id, customer_id, station["id"], charger_id, kwh, amount_idr, started_at, ended_at),
        ).fetchone()
        if session is None:
            return {"status": "duplicate", "customer_id": None, "points_awarded": 0, "balance": None}

        awarded, balance = 0, None
        if customer_id is not None:
            if points > 0:
                conn.execute(
                    """
                    INSERT INTO points_ledger (customer_id, delta, reason, ref_id)
                    VALUES (%s, %s, 'charging', %s)
                    ON CONFLICT (customer_id, reason, ref_id) DO NOTHING
                    """,
                    (customer_id, points, str(session["id"])),
                )
                awarded = points
            balance = conn.execute(
                "SELECT COALESCE(SUM(delta), 0)::int AS b FROM points_ledger WHERE customer_id = %s",
                (customer_id,),
            ).fetchone()["b"]
            
            if notify and awarded > 0:
                ident = conn.execute(
                    "SELECT channel, external_id FROM customer_identities "
                    "WHERE customer_id = %s AND channel IN ('whatsapp', 'telegram') "
                    "ORDER BY (channel = 'telegram') DESC LIMIT 1",
                    (customer_id,),
                ).fetchone()
                if ident:
                    _enqueue(
                        conn, kind="notification", channel=ident["channel"], recipient=ident["external_id"],
                        body=notify(awarded, balance), customer_id=customer_id,
                        dedup_key=f"charge:{session['id']}"
                    )

        return {"status": "created", "customer_id": customer_id, "points_awarded": awarded, "balance": balance}
    
    
def get_customer(customer_id: Any) -> dict[str, Any] | None:
    with tx() as conn:
        return conn.execute(
            "SELECT customer_code, name, driver_type, home_area, main_route FROM customers WHERE id = %s",
            (customer_id,),
        ).fetchone()


def get_customer_by_code(customer_code: str) -> dict[str, Any] | None:
    with tx() as conn:
        return conn.execute("SELECT * FROM customers WHERE customer_code = %s", (customer_code,)).fetchone()


def recent_sessions(customer_id: Any, limit: int) -> list[dict[str, Any]]:
    with tx() as conn:
        return conn.execute(
            """
            SELECT s.name AS station, cs.charger_id, cs.kwh, cs.amount_idr, cs.started_at
            FROM charging_sessions cs JOIN stations s ON s.id = cs.station_id
            WHERE cs.customer_id = %s
            ORDER BY cs.started_at DESC LIMIT %s
            """,
            (customer_id, limit),
        ).fetchall()


def recent_messages(customer_id: Any, limit: int) -> list[dict[str, Any]]:
    """Urutan kronologis (terlama dulu)."""
    with tx() as conn:
        rows = conn.execute(
            "SELECT direction, body FROM conversations WHERE customer_id = %s ORDER BY id DESC LIMIT %s",
            (customer_id, limit),
        ).fetchall()
    return rows[::-1]


def create_ticket(
    customer_id: Any, level: int, category: str, summary: str, source: str
) -> tuple[dict[str, Any], bool]:
    """(tiket, created). created=False berarti sudah ada tiket aktif untuk kategori yang sama."""
    with tx() as conn:
        for _ in range(2):   # ulang sekali jika tiket lama di-resolve di sela INSERT dan SELECT
            row = conn.execute(
                """
                INSERT INTO cs_tickets (customer_id, level, category, summary, source)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (customer_id, category) WHERE status <> 'resolved' DO NOTHING
                RETURNING id, level, category
                """,
                (customer_id, level, category, summary, source),
            ).fetchone()
            if row:
                return row, True
            row = conn.execute(
                "SELECT id, level, category FROM cs_tickets "
                "WHERE customer_id = %s AND category = %s AND status <> 'resolved'",
                (customer_id, category),
            ).fetchone()
            if row:
                return row, False
    raise RuntimeError("gagal membuat tiket")


def open_tickets(customer_id: Any) -> list[dict[str, Any]]:
    with tx() as conn:
        return conn.execute(
            "SELECT id, level, category, summary, source, status, notified_at FROM cs_tickets "
            "WHERE customer_id = %s AND status <> 'resolved' ORDER BY id",
            (customer_id,),
        ).fetchall()


def resolve_ticket(ticket_id: int) -> bool:
    with tx() as conn:
        cur = conn.execute(
            "UPDATE cs_tickets SET status = 'resolved', resolved_at = now() "
            "WHERE id = %s AND status <> 'resolved'",
            (ticket_id,),
        )
        return cur.rowcount == 1


def mark_notified(ticket_id: int) -> None:
    with tx() as conn:
        conn.execute("UPDATE cs_tickets SET notified_at = now() WHERE id = %s", (ticket_id,))


def count_recent_inbound(customer_id: Any, seconds: int) -> int:
    with tx() as conn:
        return conn.execute(
            "SELECT count(*)::int AS n FROM conversations "
            "WHERE customer_id = %s AND direction = 'in' AND created_at > now() - %s * interval '1 second'",
            (customer_id, seconds),
        ).fetchone()["n"]
        
        
_BREAKDOWN_DIMS = {"driver_type": "driver_type", "home_area": "home_area"}   # whitelist nama kolom


def dashboard_kpis(days: int) -> dict[str, Any]:
    """days = jendela saat ini; jendela pembanding = `days` hari sebelumnya (untuk retention)."""
    with tx() as conn:
        return conn.execute(
            """
            WITH cur AS (
              SELECT customer_id, count(*) AS n
              FROM charging_sessions
              WHERE customer_id IS NOT NULL AND started_at > now() - %(d)s * interval '1 day'
              GROUP BY customer_id),
            prev AS (
              SELECT DISTINCT customer_id FROM charging_sessions
              WHERE customer_id IS NOT NULL
                AND started_at >  now() - %(d2)s * interval '1 day'
                AND started_at <= now() - %(d)s  * interval '1 day')
            SELECT
              (SELECT count(*) FROM customers WHERE registration_state = 'done')::int AS registered,
              (SELECT count(*) FROM cur)::int AS active_drivers,
              (SELECT COALESCE(sum(kwh), 0) FROM charging_sessions
                 WHERE started_at > now() - %(d)s * interval '1 day')::float AS total_kwh,
              (SELECT count(*) FROM cur WHERE n >= 2)::int AS repeat_drivers,
              (SELECT count(*) FROM prev)::int AS prev_active,
              (SELECT count(*) FROM prev WHERE customer_id IN (SELECT customer_id FROM cur))::int AS retained,
              (SELECT count(*) FROM cs_tickets WHERE status <> 'resolved')::int AS open_tickets,
              (SELECT count(*) FROM cs_tickets WHERE status <> 'resolved' AND level = 3)::int AS urgent_tickets,
              (SELECT count(*) FROM inactivity_alerts WHERE status = 'open')::int AS inactivity_alerts
            """,
            {"d": days, "d2": days * 2},
        ).fetchone()


def sessions_by_hour(days: int) -> list[dict[str, Any]]:
    with tx() as conn:
        return conn.execute(
            """
            SELECT extract(hour FROM started_at AT TIME ZONE 'Asia/Jakarta')::int AS hour, count(*)::int AS sessions
            FROM charging_sessions WHERE started_at > now() - %s * interval '1 day'
            GROUP BY 1 ORDER BY 1
            """,
            (days,),
        ).fetchall()


def sessions_by_station(days: int) -> list[dict[str, Any]]:
    with tx() as conn:
        return conn.execute(
            """
            SELECT st.name AS station, count(*)::int AS sessions, COALESCE(sum(cs.kwh), 0)::float AS kwh
            FROM charging_sessions cs JOIN stations st ON st.id = cs.station_id
            WHERE cs.started_at > now() - %s * interval '1 day'
            GROUP BY st.name ORDER BY kwh DESC
            """,
            (days,),
        ).fetchall()


def customer_breakdown(dim: str) -> list[dict[str, Any]]:
    column = _BREAKDOWN_DIMS[dim]   # KeyError jika di luar whitelist
    query = sql.SQL(
        "SELECT COALESCE({col}, '-') AS label, count(*)::int AS customers FROM customers "
        "WHERE registration_state = 'done' GROUP BY 1 ORDER BY 2 DESC"
    ).format(col=sql.Identifier(column))
    with tx() as conn:
        return conn.execute(query).fetchall()


def customer_list(search: str, limit: int) -> list[dict[str, Any]]:
    with tx() as conn:
        return conn.execute(
            """
            SELECT c.customer_code, c.name, c.driver_type, c.home_area,
                   max(cs.started_at) AS last_visit,
                   count(cs.id) FILTER (WHERE cs.started_at > now() - interval '30 days')::int AS sessions_30d,
                   COALESCE(sum(cs.kwh) FILTER (WHERE cs.started_at > now() - interval '30 days'), 0)::float AS kwh_30d,
                   (SELECT COALESCE(sum(l.delta), 0)::int FROM points_ledger l WHERE l.customer_id = c.id) AS points
            FROM customers c LEFT JOIN charging_sessions cs ON cs.customer_id = c.id
            WHERE c.registration_state = 'done'
              AND (%(q)s = '' OR c.customer_code ILIKE %(like)s OR c.name ILIKE %(like)s)
            GROUP BY c.id
            ORDER BY last_visit DESC NULLS LAST
            LIMIT %(limit)s
            """,
            {"q": search, "like": f"%{search}%", "limit": limit},
        ).fetchall()


def customer_360_raw(customer_code: str) -> dict[str, Any] | None:
    with tx() as conn:
        c = conn.execute(
            """
            SELECT c.id, c.customer_code, c.name, c.driver_type, c.home_area, c.main_route,
                   c.consent_marketing, c.created_at,
                   (SELECT COALESCE(sum(kwh), 0)::float FROM charging_sessions s
                      WHERE s.customer_id = c.id AND s.started_at > now() - interval '30 days') AS kwh_30d,
                   (SELECT count(*)::int FROM charging_sessions s
                      WHERE s.customer_id = c.id AND s.started_at > now() - interval '28 days') AS visits_28d,
                   (SELECT count(*)::int FROM charging_sessions s WHERE s.customer_id = c.id) AS total_sessions,
                   (SELECT max(started_at) FROM charging_sessions s WHERE s.customer_id = c.id) AS last_visit,
                   (SELECT COALESCE(sum(delta), 0)::int FROM points_ledger l WHERE l.customer_id = c.id) AS points,
                   EXISTS (SELECT 1 FROM inactivity_alerts a
                           WHERE a.customer_id = c.id AND a.status = 'open') AS has_open_alert
            FROM customers c WHERE c.customer_code = %s
            """,
            (customer_code,),
        ).fetchone()
        if c is None:
            return None
        hour = conn.execute(
            """
            SELECT extract(hour FROM started_at AT TIME ZONE 'Asia/Jakarta')::int AS h
            FROM charging_sessions WHERE customer_id = %s AND started_at > now() - interval '90 days'
            GROUP BY 1 ORDER BY count(*) DESC, 1 LIMIT 1
            """,
            (c["id"],),
        ).fetchone()
        station = conn.execute(
            """
            SELECT st.name FROM charging_sessions s JOIN stations st ON st.id = s.station_id
            WHERE s.customer_id = %s AND s.started_at > now() - interval '90 days'
            GROUP BY st.name ORDER BY count(*) DESC, st.name LIMIT 1
            """,
            (c["id"],),
        ).fetchone()
        gap = conn.execute(
            """
            SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY gap_s)::float AS median_gap_s
            FROM (SELECT extract(epoch FROM started_at - lag(started_at) OVER (ORDER BY started_at)) AS gap_s
                  FROM charging_sessions
                  WHERE customer_id = %s AND started_at > now() - interval '90 days') g
            WHERE gap_s IS NOT NULL
            """,
            (c["id"],),
        ).fetchone()
        return {
            **c,
            "preferred_hour": hour["h"] if hour else None,
            "preferred_station": station["name"] if station else None,
            "median_gap_s": gap["median_gap_s"] if gap else None,
        }


def ticket_queue() -> list[dict[str, Any]]:
    with tx() as conn:
        return conn.execute(
            """
            SELECT t.id, t.customer_id, t.level, t.category, t.status, t.source, t.created_at,
                   t.notified_at IS NOT NULL AS alerted, c.customer_code, c.name, t.summary,
                   COALESCE(
                     (SELECT channel FROM conversations WHERE customer_id = c.id ORDER BY id DESC LIMIT 1),
                     (SELECT channel FROM customer_identities WHERE customer_id = c.id ORDER BY id DESC LIMIT 1),
                     'telegram'
                   ) AS channel,
                   COALESCE(
                     (SELECT external_id FROM customer_identities ci 
                      WHERE ci.customer_id = c.id 
                        AND ci.channel = (SELECT channel FROM conversations WHERE customer_id = c.id ORDER BY id DESC LIMIT 1)
                      LIMIT 1),
                     (SELECT external_id FROM customer_identities ci WHERE ci.customer_id = c.id ORDER BY id DESC LIMIT 1)
                   ) AS recipient
            FROM cs_tickets t JOIN customers c ON c.id = t.customer_id
            WHERE t.status <> 'resolved'
            ORDER BY t.level DESC, t.created_at
            """
        ).fetchall()


def get_ticket(ticket_id: int) -> dict[str, Any] | None:
    with tx() as conn:
        return conn.execute(
            """
            SELECT t.id, t.customer_id, t.level, t.category, t.status, t.source, t.created_at,
                   t.notified_at IS NOT NULL AS alerted, c.customer_code, c.name, t.summary,
                   COALESCE(
                     (SELECT channel FROM conversations WHERE customer_id = c.id ORDER BY id DESC LIMIT 1),
                     (SELECT channel FROM customer_identities WHERE customer_id = c.id ORDER BY id DESC LIMIT 1),
                     'telegram'
                   ) AS channel,
                   COALESCE(
                     (SELECT external_id FROM customer_identities ci 
                      WHERE ci.customer_id = c.id 
                        AND ci.channel = (SELECT channel FROM conversations WHERE customer_id = c.id ORDER BY id DESC LIMIT 1)
                      LIMIT 1),
                     (SELECT external_id FROM customer_identities ci WHERE ci.customer_id = c.id ORDER BY id DESC LIMIT 1)
                   ) AS recipient
            FROM cs_tickets t JOIN customers c ON c.id = t.customer_id
            WHERE t.id = %s
            """,
            (ticket_id,),
        ).fetchone()


def update_ticket_status(ticket_id: int, status: str) -> bool:
    if status not in ("open", "in_progress", "resolved"):
        raise ValueError(f"status tidak valid: {status}")
    with tx() as conn:
        if status == "resolved":
            cur = conn.execute(
                "UPDATE cs_tickets SET status = %s, resolved_at = now() WHERE id = %s",
                (status, ticket_id),
            )
        else:
            cur = conn.execute(
                "UPDATE cs_tickets SET status = %s, resolved_at = NULL WHERE id = %s",
                (status, ticket_id),
            )
        return cur.rowcount == 1


def customer_conversations(customer_id: Any, limit: int = 50) -> list[dict[str, Any]]:
    with tx() as conn:
        return conn.execute(
            """
            SELECT id, channel, direction, body, created_at
            FROM conversations
            WHERE customer_id = %s
            ORDER BY id ASC
            LIMIT %s
            """,
            (customer_id, limit),
        ).fetchall()


def has_active_handover(customer_id: Any) -> bool:
    with tx() as conn:
        row = conn.execute(
            "SELECT 1 FROM cs_tickets WHERE customer_id = %s AND status = 'in_progress' LIMIT 1",
            (customer_id,),
        ).fetchone()
        return row is not None


def upsert_knowledge_item(
    *,
    slug: str,
    title: str,
    category: str,
    content: str,
    embedding: list[float] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with tx() as conn:
        return conn.execute(
            """
            INSERT INTO knowledge_base (slug, title, category, content, embedding, metadata, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (slug) DO UPDATE SET
                title = EXCLUDED.title,
                category = EXCLUDED.category,
                content = EXCLUDED.content,
                embedding = COALESCE(EXCLUDED.embedding, knowledge_base.embedding),
                metadata = EXCLUDED.metadata,
                updated_at = now()
            RETURNING id, slug, title, category, content, metadata, updated_at
            """,
            (slug, title, category, content, embedding, json.dumps(metadata or {})),
        ).fetchone()


def get_knowledge_item(slug: str) -> dict[str, Any] | None:
    with tx() as conn:
        return conn.execute(
            "SELECT id, slug, title, category, content, embedding, metadata, created_at, updated_at "
            "FROM knowledge_base WHERE slug = %s",
            (slug,),
        ).fetchone()


def list_knowledge_items(category: str | None = None) -> list[dict[str, Any]]:
    with tx() as conn:
        if category:
            return conn.execute(
                "SELECT id, slug, title, category, content, metadata, created_at, updated_at "
                "FROM knowledge_base WHERE category = %s ORDER BY title",
                (category,),
            ).fetchall()
        return conn.execute(
            "SELECT id, slug, title, category, content, metadata, created_at, updated_at "
            "FROM knowledge_base ORDER BY category, title"
        ).fetchall()


def delete_knowledge_item(slug: str) -> bool:
    with tx() as conn:
        cur = conn.execute("DELETE FROM knowledge_base WHERE slug = %s", (slug,))
        return cur.rowcount == 1


def count_knowledge_items() -> int:
    with tx() as conn:
        return conn.execute("SELECT count(*)::int AS n FROM knowledge_base").fetchone()["n"]


def all_knowledge_embeddings() -> list[dict[str, Any]]:
    with tx() as conn:
        return conn.execute(
            "SELECT id, slug, title, category, content, embedding, metadata "
            "FROM knowledge_base WHERE embedding IS NOT NULL"
        ).fetchall()


def search_knowledge_lexical(query: str, limit: int = 3) -> list[dict[str, Any]]:
    with tx() as conn:
        rows = conn.execute(
            """
            SELECT id, slug, title, category, content, metadata,
                   ts_rank_cd(to_tsvector('indonesian', title || ' ' || content), plainto_tsquery('indonesian', %s)) AS rank
            FROM knowledge_base
            WHERE to_tsvector('indonesian', title || ' ' || content) @@ plainto_tsquery('indonesian', %s)
            ORDER BY rank DESC
            LIMIT %s
            """,
            (query, query, limit),
        ).fetchall()
        if rows:
            return rows
        # Fallback ILIKE jika tsquery tidak cocok
        return conn.execute(
            """
            SELECT id, slug, title, category, content, metadata, 0.1 AS rank
            FROM knowledge_base
            WHERE title ILIKE %s OR content ILIKE %s
            ORDER BY title
            LIMIT %s
            """,
            (f"%{query}%", f"%{query}%", limit),
        ).fetchall()
        
        
def message_id_by_channel(channel: str, channel_message_id: str) -> int | None:
    with tx() as conn:
        row = conn.execute(
            "SELECT id FROM conversations WHERE channel = %s AND channel_message_id = %s",
            (channel, channel_message_id),
        ).fetchone()
        return row["id"] if row else None


def personalization_enabled(customer_id: Any) -> bool:
    with tx() as conn:
        row = conn.execute(
            "SELECT personalization_enabled FROM customers WHERE id = %s", (customer_id,)
        ).fetchone()
        return bool(row and row["personalization_enabled"])


def set_personalization(customer_id: Any, enabled: bool) -> None:
    with tx() as conn:
        conn.execute("UPDATE customers SET personalization_enabled = %s WHERE id = %s", (enabled, customer_id))


def upsert_preference(
    customer_id: Any, key: str, value: str, confidence: float, evidence_message_id: int | None
) -> None:
    """Pernyataan terbaru menimpa yang lama. Flag personalisasi dicek di SQL yang sama,
    sehingga /lupa yang masuk saat ekstraksi berjalan tidak bisa 'dikalahkan' oleh insert terlambat."""
    with tx() as conn:
        conn.execute(
            """
            INSERT INTO customer_preferences (customer_id, pref_key, pref_value, confidence, evidence_message_id)
            SELECT %s::uuid, %s::text, %s::text, %s::numeric, %s::bigint
            WHERE EXISTS (SELECT 1 FROM customers WHERE id = %s::uuid AND personalization_enabled)
            ON CONFLICT (customer_id, pref_key) DO UPDATE SET
              pref_value = EXCLUDED.pref_value,
              confidence = EXCLUDED.confidence,
              evidence_message_id = EXCLUDED.evidence_message_id,
              updated_at = now()
            """,
            (customer_id, key, value, confidence, evidence_message_id, customer_id),
        )


def list_preferences(customer_id: Any) -> list[dict[str, Any]]:
    with tx() as conn:
        return conn.execute(
            "SELECT pref_key, pref_value, confidence::float AS confidence, updated_at "
            "FROM customer_preferences WHERE customer_id = %s ORDER BY pref_key",
            (customer_id,),
        ).fetchall()


def delete_preferences(customer_id: Any) -> int:
    with tx() as conn:
        return conn.execute("DELETE FROM customer_preferences WHERE customer_id = %s", (customer_id,)).rowcount


def preference_summary() -> list[dict[str, Any]]:
    """Agregat saja, tanpa identitas."""
    with tx() as conn:
        return conn.execute(
            "SELECT pref_key, pref_value, count(*)::int AS customers FROM customer_preferences "
            "GROUP BY 1, 2 ORDER BY 1, 3 DESC"
        ).fetchall()
        
def create_reply_draft(ticket_id: int, body: str, drafted_by: str) -> int:
    with tx() as conn:
        open_ticket = conn.execute(
            "SELECT 1 FROM cs_tickets WHERE id = %s AND status <> 'resolved'", (ticket_id,)
        ).fetchone()
        if open_ticket is None:
            raise LookupError("tiket tidak ditemukan atau sudah selesai")
        pending = conn.execute(
            "SELECT count(*)::int AS n FROM reply_drafts WHERE ticket_id = %s AND status = 'pending'", (ticket_id,)
        ).fetchone()["n"]
        if pending >= 5:
            raise ValueError("terlalu banyak draf menunggu untuk tiket ini")
        draft = conn.execute(
            "INSERT INTO reply_drafts (ticket_id, body, drafted_by) VALUES (%s, %s, %s) RETURNING id",
            (ticket_id, body, drafted_by),
        ).fetchone()
        conn.execute(
            "INSERT INTO ticket_events (ticket_id, actor, action, detail) VALUES (%s, %s, 'draft_reply', %s)",
            (ticket_id, drafted_by, f"draft:{draft['id']}"),
        )
        return draft["id"]


def pending_drafts() -> list[dict[str, Any]]:
    with tx() as conn:
        return conn.execute(
            """
            SELECT d.id, d.ticket_id, d.body, d.drafted_by, d.created_at, c.customer_code, t.category
            FROM reply_drafts d
            JOIN cs_tickets t ON t.id = d.ticket_id
            JOIN customers c ON c.id = t.customer_id
            WHERE d.status = 'pending' ORDER BY d.id
            """
        ).fetchall()


def decide_draft(draft_id: int, approve: bool, actor: str) -> dict[str, Any] | None:
    """Klaim atomik: hanya satu pemanggil yang berhasil. None = sudah diputuskan orang lain."""
    with tx() as conn:
        return conn.execute(
            "UPDATE reply_drafts SET status = %s, decided_by = %s, decided_at = now() "
            "WHERE id = %s AND status = 'pending' RETURNING id, ticket_id, body",
            ("approved" if approve else "rejected", actor, draft_id),
        ).fetchone()


def reopen_draft(draft_id: int) -> None:
    with tx() as conn:
        conn.execute(
            "UPDATE reply_drafts SET status = 'pending', decided_by = NULL, decided_at = NULL "
            "WHERE id = %s AND status = 'approved'",
            (draft_id,),
        )


def log_ticket_event(ticket_id: int, actor: str, action: str, detail: str | None = None) -> None:
    with tx() as conn:
        conn.execute(
            "INSERT INTO ticket_events (ticket_id, actor, action, detail) VALUES (%s, %s, %s, %s)",
            (ticket_id, actor, action, detail),
        )

def enqueue_inbox(
    *,
    channel: str,
    user_id: str,
    chat_id: str,
    message_id: str,
    body: str,
    is_start: bool = False,
    start_payload: str | None = None,
) -> bool:
    """Simpan pesan masuk secara durable dan abaikan pesan duplikat."""
    with tx() as conn:
        cur = conn.execute(
            """
            INSERT INTO inbox (
                channel,
                user_id,
                chat_id,
                message_id,
                body,
                is_start,
                start_payload
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (channel, chat_id, message_id) DO NOTHING
            """,
            (
                channel,
                user_id,
                chat_id,
                message_id,
                body,
                is_start,
                start_payload,
            ),
        )
        return cur.rowcount == 1


def claim_inbox(limit: int = 10, lock_seconds: int = 120) -> list[dict[str, Any]]:
    """Klaim pesan yang siap diproses dengan token fencing baru."""
    if limit < 1:
        raise ValueError("limit harus minimal 1")
    if lock_seconds < 1:
        raise ValueError("lock_seconds harus minimal 1")

    with tx() as conn:
        rows = conn.execute(
            """
            WITH candidates AS (
                SELECT id
                FROM inbox
                WHERE
                    (
                        status = 'pending'
                        AND next_attempt_at <= now()
                    )
                    OR
                    (
                        status = 'processing'
                        AND (
                            locked_until IS NULL
                            OR locked_until <= now()
                        )
                    )
                ORDER BY next_attempt_at, id
                LIMIT %s
                FOR UPDATE SKIP LOCKED
            )
            UPDATE inbox AS i
            SET
                status = 'processing',
                attempts = i.attempts + 1,
                locked_until = now() + (%s * interval '1 second'),
                claim_token = gen_random_uuid()
            FROM candidates AS c
            WHERE i.id = c.id
            RETURNING
                i.id,
                i.channel,
                i.user_id,
                i.chat_id,
                i.message_id,
                i.body,
                i.is_start,
                i.start_payload,
                i.status,
                i.attempts,
                i.next_attempt_at,
                i.locked_until,
                i.last_error,
                i.customer_id,
                i.reply_body,
                i.result_ready,
                i.claim_token
            """,
            (limit, lock_seconds),
        ).fetchall()

        return rows

def store_inbox_result(
    inbox_id: int,
    *,
    claim_token: Any,
    customer_id: Any,
    reply_body: str | None,
) -> bool:
    """Simpan hasil hanya jika token cocok dengan klaim Inbox yang aktif."""
    with tx() as conn:
        row = conn.execute(
            """
            UPDATE inbox
            SET
                customer_id = %s,
                reply_body = %s,
                result_ready = TRUE,
                last_error = NULL
            WHERE id = %s
              AND status = 'processing'
              AND claim_token = %s
            RETURNING id
            """,
            (customer_id, reply_body, inbox_id, claim_token),
        ).fetchone()

        return row is not None

def finalize_stored_inbox_result(
    inbox_id: int,
    *,
    claim_token: Any,
) -> bool:
    """Masukkan balasan ke Outbox dan finalisasi Inbox secara atomik."""
    with tx() as conn:
        inbox = conn.execute(
            """
            SELECT
                id,
                channel,
                chat_id,
                message_id,
                customer_id,
                reply_body,
                result_ready
            FROM inbox
            WHERE id = %s
              AND status = 'processing'
              AND claim_token = %s
            FOR UPDATE
            """,
            (inbox_id, claim_token),
        ).fetchone()

        if inbox is None or not inbox["result_ready"]:
            return False

        if inbox["reply_body"]:
            if inbox["customer_id"] is None:
                raise RuntimeError(
                    f"Inbox {inbox_id} memiliki balasan tanpa customer_id"
                )

            _enqueue(
                conn,
                kind="reply",
                channel=inbox["channel"],
                recipient=inbox["chat_id"],
                body=inbox["reply_body"],
                customer_id=inbox["customer_id"],
                dedup_key=(
                    f"inbox-reply:{inbox['channel']}:"
                    f"{inbox['chat_id']}:{inbox['message_id']}"
                ),
            )

        updated = conn.execute(
            """
            UPDATE inbox
            SET
                status = 'processed',
                processed_at = now(),
                locked_until = NULL,
                last_error = NULL
            WHERE id = %s
              AND status = 'processing'
              AND claim_token = %s
            RETURNING id
            """,
            (inbox_id, claim_token),
        ).fetchone()

        return updated is not None

def fail_inbox(
    inbox_id: int,
    error: str,
    *,
    claim_token: Any,
    attempts: int,
    max_attempts: int = 6,
    permanent: bool = False,
) -> str:
    """Jadwalkan retry atau tandai Inbox dead jika percobaan habis."""
    if attempts < 1:
        raise ValueError("attempts harus minimal 1")
    if max_attempts < 1:
        raise ValueError("max_attempts harus minimal 1")

    dead = permanent or attempts >= max_attempts
    new_status = "dead" if dead else "pending"

    delay_seconds = int(
        min(30 * 2 ** max(attempts - 1, 0), 1800)
        * random.uniform(0.8, 1.2)
    )

    with tx() as conn:
        row = conn.execute(
            """
            UPDATE inbox
            SET
                status = %s,
                next_attempt_at = CASE
                    WHEN %s = 'pending'
                    THEN now() + (%s * interval '1 second')
                    ELSE next_attempt_at
                END,
                locked_until = NULL,
                last_error = %s
            WHERE id = %s
              AND status = 'processing'
              AND claim_token = %s
            RETURNING status
            """,
            (
                new_status,
                new_status,
                delay_seconds,
                error[:4000],
                inbox_id,
                claim_token,
            ),
        ).fetchone()

        if row is None:
            raise RuntimeError(
                f"Inbox {inbox_id} gagal diperbarui: "
                "klaim tidak aktif atau claim_token tidak cocok."
            )

        return row["status"]

def recover_dead_inbox_result(inbox_id: int) -> bool:
    """Pulihkan hasil tersimpan dari Inbox dead tanpa memproses AI ulang."""
    with tx() as conn:
        row = conn.execute(
            """
            UPDATE inbox
            SET
                status = 'processing',
                locked_until = now() + interval '120 seconds',
                claim_token = gen_random_uuid(),
                last_error = NULL
            WHERE id = %s
              AND status = 'dead'
              AND result_ready = TRUE
            RETURNING claim_token
            """,
            (inbox_id,),
        ).fetchone()

    if row is None:
        return False

    return finalize_stored_inbox_result(
        inbox_id,
        claim_token=row["claim_token"],
    )
