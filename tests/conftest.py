import os
import socket
from urllib.parse import urlsplit

from psycopg import sql
import pytest
from dotenv import load_dotenv

load_dotenv()
# Harus dijalankan sebelum app.db.repo diimpor, supaya pool memakai DB tes.
os.environ["DATABASE_URL"] = os.environ["DATABASE_URL"].rsplit("/", 1)[0] + "/enerva_test"
os.environ["PREFERENCES_LEARNING"] = "off"
os.environ["PREFERENCE_LEARNING"] = "off"

os.environ["MCP_DATABASE_URL"] = os.environ["DATABASE_URL"]   # tes MCP memakai DB tes, bukan DB dev
os.environ["ENERVA_ALLOW_OWNER"] = "1"                        # hanya berlaku di database berakhiran _test

from app.db import repo  # noqa: E402

KEEP = {"stations"}      # data seed yang dibutuhkan tes, tidak ikut dihapus

_db_available: bool | None = None


def is_db_available() -> bool:
    global _db_available
    if _db_available is None:
        try:
            import psycopg
            with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=1) as conn:
                _db_available = True
        except Exception:
            _db_available = False
    return _db_available


def _truncate_all() -> None:
    if not is_db_available():
        return
    assert os.environ["DATABASE_URL"].endswith("_test"), "menolak TRUNCATE di database non-tes"
    try:
        with repo.tx() as conn:
            names = [
                r["tablename"]
                for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'").fetchall()
                if r["tablename"] not in KEEP
            ]
            if names:
                conn.execute(
                    sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(
                        sql.SQL(", ").join(sql.Identifier(n) for n in names)
                    )
                )
    except Exception:
        pass


@pytest.fixture(autouse=True)
def clean_db():
    _truncate_all()
    yield
    _truncate_all()
