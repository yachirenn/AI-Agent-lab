"""Runner untuk mengeksekusi migrasi database secara urut dan idempotent."""
from __future__ import annotations

import os
from pathlib import Path

from app.db import repo

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "app" / "db" / "migrations"


def init_migrations_table() -> None:
    with repo.tx() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )


def get_applied_migrations() -> set[str]:
    with repo.tx() as conn:
        rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
        return {r["version"] for r in rows}


def run_migrations() -> None:
    init_migrations_table()
    applied = get_applied_migrations()

    # Cek apakah schema awal sudah terpasang
    with repo.tx() as conn:
        tables = {
            r["tablename"]
            for r in conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            ).fetchall()
        }
        if "customers" in tables and "schema.sql" not in applied:
            conn.execute("INSERT INTO schema_migrations (version) VALUES ('schema.sql') ON CONFLICT DO NOTHING")
            applied.add("schema.sql")

        cols = {
            r["column_name"]
            for r in conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'customers'"
            ).fetchall()
        }
        if "registration_state" in cols and "002_registration.sql" not in applied:
            conn.execute("INSERT INTO schema_migrations (version) VALUES ('002_registration.sql') ON CONFLICT DO NOTHING")
            applied.add("002_registration.sql")

        if "cs_tickets" in tables and "003_escalation.sql" not in applied:
            conn.execute("INSERT INTO schema_migrations (version) VALUES ('003_escalation.sql') ON CONFLICT DO NOTHING")
            applied.add("003_escalation.sql")

    sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not sql_files:
        print("Tidak ada berkas migrasi ditemukan.")
        return

    migrated_count = 0
    for sql_file in sql_files:
        filename = sql_file.name
        if filename in applied:
            continue

        print(f"Applying migration: {filename}...")
        sql_content = sql_file.read_text(encoding="utf-8-sig")
        with repo.tx() as conn:
            conn.execute(sql_content)
            conn.execute(
                "INSERT INTO schema_migrations (version) VALUES (%s)",
                (filename,)
            )
        migrated_count += 1
        print(f"Applied: {filename} [OK]")

    if migrated_count == 0:
        print("Semua migrasi sudah up-to-date!")
    else:
        print(f"Selesai! {migrated_count} migrasi berhasil diterapkan.")


if __name__ == "__main__":
    run_migrations()
