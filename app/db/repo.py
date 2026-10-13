"""Semua akses SQL lewat modul ini. Layer lain (agent, API) tidak boleh menulis SQL."""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Iterator

from dotenv import load_dotenv
from psycopg import Connection, sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

load_dotenv()

_pool: ConnectionPool | None = None


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
        if vehicle_model:
            conn.execute(
                "INSERT INTO vehicles (customer_id, model) VALUES (%s, %s)",
                (customer_id, vehicle_model),
            )
        return True