import os
from urllib.parse import urlsplit, urlunsplit

from psycopg import sql
import pytest
from dotenv import load_dotenv

load_dotenv()


def _resolve_test_database_url() -> str | None:
    source = os.environ.get("TEST_DATABASE_URL")
    if not source:
        return None

    parsed = urlsplit(source)
    database = parsed.path.strip("/")
    if not database:
        raise RuntimeError("URL database test tidak memiliki nama database")
    if not database.endswith("_test"):
        raise RuntimeError(
            f"SAFETY ERROR: database test '{database}' harus berakhiran _test"
        )

    # Rebuild the URL so surrounding whitespace is not accidentally retained,
    # while preserving credentials, host, port, query parameters, and options.
    return urlunsplit(parsed._replace(path=f"/{database}"))


def _database_name_from_url(url: str) -> str:
    return urlsplit(url).path.strip("/")


def _assert_test_database(conn) -> None:
    row = conn.execute("SELECT current_database()").fetchone()
    # repo connections use dict_row, while this direct psycopg connection
    # may use the default tuple row factory.
    database = row["current_database"] if isinstance(row, dict) else row[0]
    if not database.endswith("_test"):
        raise RuntimeError(f"SAFETY VIOLATION: terhubung ke database non-test '{database}'")


# Isolasi database test dari database utama (Supabase/Dev):
TEST_DATABASE_URL = _resolve_test_database_url()
if TEST_DATABASE_URL:
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    os.environ["MCP_DATABASE_URL"] = TEST_DATABASE_URL
    os.environ["ENERVA_ALLOW_OWNER"] = "1"  # hanya aman untuk database _test
else:
    # Tanpa TEST_DATABASE_URL, pytest menolak memakai DATABASE_URL utama untuk mencegah TRUNCATE
    os.environ["DATABASE_URL"] = ""
    os.environ["MCP_DATABASE_URL"] = ""

os.environ["PREFERENCES_LEARNING"] = "off"
os.environ["PREFERENCE_LEARNING"] = "off"

from app.db import repo  # noqa: E402

KEEP = {"stations"}  # data seed yang dibutuhkan tes, tidak ikut dihapus
_db_available: bool | None = None


def is_db_available() -> bool:
    global _db_available
    if _db_available is None:
        if not TEST_DATABASE_URL:
            _db_available = False
            return False
        try:
            import psycopg

            with psycopg.connect(TEST_DATABASE_URL, connect_timeout=1) as conn:
                _assert_test_database(conn)
                _db_available = True
        except RuntimeError:
            # Jangan pernah menelan safety violation; tes harus gagal seketika
            raise
        except Exception:
            _db_available = False
    return _db_available


def _truncate_all() -> None:
    if not is_db_available() or not TEST_DATABASE_URL:
        return
    assert urlsplit(TEST_DATABASE_URL).path.strip("/").endswith("_test"), (
        "menolak TRUNCATE di database non-tes"
    )
    with repo.tx() as conn:
        _assert_test_database(conn)
        names = [
            r["tablename"]
            for r in conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            ).fetchall()
            if r["tablename"] not in KEEP
        ]
        if names:
            conn.execute(
                sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(
                    sql.SQL(", ").join(sql.Identifier(n) for n in names)
                )
            )


@pytest.fixture(autouse=True)
def clean_db():
    _truncate_all()
    yield
    _truncate_all()
