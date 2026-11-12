"""Script otomatis untuk membuat dan menyiapkan database test PostgreSQL lokal (enerva_test)."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg
from psycopg import sql
from dotenv import load_dotenv

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def _update_env_file(test_url: str) -> None:
    if not ENV_FILE.exists():
        ENV_FILE.write_text(f"TEST_DATABASE_URL={test_url}\n", encoding="utf-8")
        print(f"File .env dibuat dengan TEST_DATABASE_URL.")
        return

    content = ENV_FILE.read_text(encoding="utf-8")
    lines = content.splitlines()
    found = False
    new_lines = []
    for line in lines:
        if line.strip().startswith("TEST_DATABASE_URL="):
            new_lines.append(f"TEST_DATABASE_URL={test_url}")
            found = True
        else:
            new_lines.append(line)

    if not found:
        new_lines.append(f"\n# Database Pengujian (Wajib berakhiran _test)")
        new_lines.append(f"TEST_DATABASE_URL={test_url}")

    ENV_FILE.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    print(f"File .env berhasil diperbarui dengan TEST_DATABASE_URL.")


def setup_test_db(
    host: str = "localhost",
    port: int = 5432,
    user: str = "postgres",
    password: str = "",
    db_name: str = "enerva_test",
) -> None:
    if not db_name.endswith("_test"):
        raise ValueError(f"Nama database test wajib berakhiran '_test' (diberikan: {db_name})")

    maintenance_url = f"postgresql://{user}:{password}@{host}:{port}/postgres"
    test_db_url = f"postgresql://{user}:{password}@{host}:{port}/{db_name}"

    print(f"Menghubungi PostgreSQL di {host}:{port} sebagai user '{user}'...")
    try:
        with psycopg.connect(maintenance_url, autocommit=True, connect_timeout=5) as conn:
            exists = conn.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (db_name,)
            ).fetchone()
            if exists:
                print(f"Database '{db_name}' sudah ada.")
            else:
                print(f"Membuat database '{db_name}'...")
                conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name)))
                print(f"Database '{db_name}' berhasil dibuat!")
    except Exception as exc:
        print(f"\n[GAGAL] Tidak dapat terhubung ke PostgreSQL ({maintenance_url}):")
        print(f"Detail error: {exc}")
        print("\nTips:")
        print("1. Pastikan service PostgreSQL sudah berjalan di Windows Services.")
        print(f"2. Pastikan user dan password sudah sesuai (coba gunakan flag --user dan --password).")
        sys.exit(1)

    # Terapkan schema dan seluruh migrasi ke database test
    print(f"\nMenerapkan skema dan migrasi ke '{db_name}'...")
    os.environ["DATABASE_URL"] = test_db_url
    os.environ["TEST_DATABASE_URL"] = test_db_url

    # Reset repo pool jika sudah terinisialisasi
    from app.db import repo
    repo.close_pool()

    from scripts import migrate
    migrate.run_migrations()

    # Perbarui file .env
    _update_env_file(test_db_url)

    print("\n" + "=" * 60)
    print(f"SUKSES! Database test '{db_name}' telah siap digunakan.")
    print("Sekarang Anda bisa menjalankan seluruh test suite dengan:")
    print("  .venv/Scripts/python -m pytest -q")
    print("=" * 60)


def main() -> None:
    load_dotenv(ENV_FILE)
    parser = argparse.ArgumentParser(description="Setup enerva_test database")
    parser.add_argument("--host", default=os.environ.get("POSTGRES_HOST", "localhost"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("POSTGRES_PORT", "5432")))
    parser.add_argument("--user", default=os.environ.get("POSTGRES_USER", "postgres"))
    parser.add_argument("--password", default=os.environ.get("POSTGRES_PASSWORD", ""))
    parser.add_argument("--dbname", default="enerva_test")

    args = parser.parse_args()

    # Jika password kosong, coba minta input interaktif jika di TTY
    password = args.password
    if not password and sys.stdin.isatty():
        import getpass
        password = getpass.getpass(f"Masukkan password PostgreSQL untuk user '{args.user}': ")

    setup_test_db(
        host=args.host,
        port=args.port,
        user=args.user,
        password=password,
        db_name=args.dbname,
    )


if __name__ == "__main__":
    main()
