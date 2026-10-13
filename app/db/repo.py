"""Semua akses SQL lewat modul ini. Layer lain (agent, API) tidak boleh menulis SQL."""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Iterator

from dotenv import load_dotenv
from psycopg import Connection
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


def register_customer(channel: str, external_id: str, name: str | None = None) -> dict[str, Any]:
    """Idempotent: identitas yang sama selalu mengembalikan customer yang sama,
    walaupun dua pesan pertama masuk bersamaan."""
    with tx() as conn:
        # Serialisasi per identitas supaya tidak lahir dua customer untuk satu orang.
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{channel}:{external_id}",))
        existing = _find_by_identity(conn, channel, external_id)
        if existing:
            return existing
        customer = conn.execute(
            "INSERT INTO customers (name) VALUES (%s) RETURNING *", (name,)
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